"""SEC EDGAR: company_tickers.json(CIK 매핑) + XBRL companyfacts(연간 재무).

추출 지표: Revenue, OperatingIncome, NetIncome, 총차입금, 현금 (USD → USD mn).
SEC fair access: User-Agent 헤더(이름 + 이메일) 필수, 초당 10건 미만, Accept-Encoding: gzip, deflate.

403 진단: python -m src.data_fetch.sec --diagnose          (실제 전송 헤더 확인, 네트워크 호출 없음)
          python -m src.data_fetch.sec --diagnose --probe  (company_tickers.json 1회 실제 요청)

오프라인 모드: 프로그램 요청이 403이면(또는 --sec-offline) 브라우저로 받은 파일을 같은 방식으로 처리한다.
          python -m src.data_fetch.sec --offline-check               (필요 파일·URL 목록, 네트워크 호출 없음)
          python -m src.data_fetch.fetch_all --source sec --sec-offline
          파일 위치: data/raw/sec_manual/ (company_tickers.json, CIK##########.json) — 로컬 전용, 커밋하지 않음
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import pandas as pd

from .base import (PROJECT_ROOT, FetchError, FetchResult, HttpStatusError, Progress, SkipSource,
                   STATUS_FAILED, STATUS_PARTIAL, STATUS_SKIPPED, STATUS_SUCCESS, build_url, get_secret, load_config,
                   make_client, mask_secrets, names_equal, register_secret, resolve_path, save_processed, save_raw,
                   write_meta)

logger = logging.getLogger("data_fetch.sec")

SOURCE = "sec"
SOURCE_LABEL = "SEC EDGAR (U.S. Securities and Exchange Commission)"
USD_PER_MN = 1e6


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------
def parse_company_tickers(payload: Mapping) -> pd.DataFrame:
    """{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...} → DataFrame."""
    rows = [{"ticker": str(v["ticker"]).upper(), "cik": int(v["cik_str"]), "title": v["title"]}
            for v in payload.values()]
    return pd.DataFrame(rows)


def normalize_cik(v: Any) -> int | None:
    """CIK 정규화 → 정수. companyfacts "cik"는 숫자(1551182)·0 채운 문자열("0001868275")이 섞여 있다.

    'CIK0001868275', ' 1868275 ', 1868275.0 도 같은 값. 해석 불가면 None.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if v == v and float(v).is_integer() and v >= 0 else None
    t = str(v).strip().upper().removeprefix("CIK")
    return int(t) if t.isdigit() else None


def cik10(cik: int | str) -> str:
    n = normalize_cik(cik)
    if n is None:
        raise ValueError(f"CIK 해석 불가: {cik!r}")
    return str(n).zfill(10)


def fiscal_year_label(end: str, cutoff_month: int = 6) -> int:
    """회계연도 종료일 → 회계연도 (ASSUMPTION: 종료월 < cutoff_month이면 전년도)."""
    d = datetime.strptime(end, "%Y-%m-%d")
    return d.year if d.month >= cutoff_month else d.year - 1


def _entries(facts: Mapping, taxonomy: str, tag: str, unit: str) -> list[dict]:
    try:
        return facts["facts"][taxonomy][tag]["units"][unit]
    except KeyError:
        return []


def annual_values(facts: Mapping, tag: str, *, kind: str, forms: list[str], duration_days: tuple[int, int],
                  cutoff_month: int, taxonomy: str = "us-gaap", unit: str = "USD") -> dict[int, dict]:
    """연간 값 추출 → {fiscal_year: {val, end, accn, filed, form}}.

    kind="flow": start~end가 duration_days 범위(약 1년)인 항목만 (분기 누적값 제외)
    kind="instant": start가 없는 시점 값
    동일 종료일이 여러 공시에 나오면 가장 최근 filed(재작성 반영) 채택.
    """
    best: dict[str, dict] = {}
    for e in _entries(facts, taxonomy, tag, unit):
        if e.get("form") not in forms or "end" not in e or e.get("val") is None:
            continue
        if kind == "flow":
            if "start" not in e:
                continue
            days = (datetime.strptime(e["end"], "%Y-%m-%d") - datetime.strptime(e["start"], "%Y-%m-%d")).days
            if not (duration_days[0] <= days <= duration_days[1]):
                continue
        elif "start" in e:
            continue
        prev = best.get(e["end"])
        if prev is None or e.get("filed", "") > prev.get("filed", ""):
            best[e["end"]] = e
    out: dict[int, dict] = {}
    for end, e in best.items():
        fy = fiscal_year_label(end, cutoff_month)
        if fy not in out or end > out[fy]["end"]:
            out[fy] = {"val": float(e["val"]), "end": end, "accn": e.get("accn"),
                       "filed": e.get("filed"), "form": e.get("form"), "tag": tag}
    return out


def first_available(facts: Mapping, tags: list[str], fy: int, **kw) -> dict | None:
    for tag in tags:
        v = annual_values(facts, tag, **kw).get(fy)
        if v is not None:
            return v
    return None


def total_debt(facts: Mapping, components: list[Mapping], fy: int, fy_end: str | None,
               **kw) -> tuple[float, list[dict], list[str]]:
    """총차입금 = 구성요소별 첫 번째 사용 가능한 대안의 합 (ASSUMPTION: config sec.total_debt_components).

    대안의 첫 태그가 있어야 채택. 나머지 태그가 없으면 0으로 보고 플래그.
    fy_end가 주어지면 같은 종료일의 값만 사용 (손익 기준일과 일치).
    """
    total, detail, flags, found_any = 0.0, [], [], False
    for comp in components:
        for alt in comp["alternatives"]:
            vals = {t: annual_values(facts, t, kind="instant", **kw).get(fy) for t in alt}
            head = vals[alt[0]]
            if head is None or (fy_end and head["end"] != fy_end):
                continue
            found_any = True
            for t, v in vals.items():
                if v is None or (fy_end and v["end"] != fy_end):
                    flags.append(f"total_debt:{comp['name']}:{t}=missing→0")
                    continue
                total += v["val"]
                detail.append({"component": comp["name"], "tag": t, "val_usd": v["val"], "end": v["end"],
                               "accn": v["accn"]})
            break
    if not found_any:
        return float("nan"), detail, flags + ["total_debt:missing"]
    return total, detail, flags


def extract_company_financials(facts: Mapping, scfg: Mapping, fiscal_years: list[int]) -> tuple[list[dict], list[dict]]:
    """companyfacts → 연도별 지표 행(USD mn) + 차입금 구성 상세."""
    kw = dict(forms=scfg["forms"], duration_days=tuple(scfg["flow_duration_days"]),
              cutoff_month=int(scfg["fy_label_cutoff_month"]))
    rows, debt_detail = [], []
    for fy in fiscal_years:
        rec: dict[str, Any] = {"fiscal_year": f"FY{fy}A"}
        flags = []
        rev = first_available(facts, scfg["metrics"]["revenue"], fy, kind="flow", **kw)
        fy_end = rev["end"] if rev else None
        for metric, tags in scfg["metrics"].items():
            kind = "instant" if metric == "cash" else "flow"
            v = rev if metric == "revenue" else first_available(facts, tags, fy, kind=kind, **kw)
            if v is not None and fy_end and v["end"] != fy_end:
                flags.append(f"{metric}:end_mismatch({v['end']})")
            if v is None:
                rec[metric] = float("nan")
                flags.append(f"{metric}:missing")
            else:
                rec[metric] = v["val"] / USD_PER_MN
                rec[f"{metric}_tag"] = v["tag"]
                if v["tag"] != tags[0]:
                    flags.append(f"{metric}:tag={v['tag']}")
        debt, detail, dflags = total_debt(facts, scfg["total_debt_components"], fy, fy_end, **kw)
        rec["total_debt"] = debt / USD_PER_MN if debt == debt else float("nan")
        rec["fiscal_year_end"] = fy_end
        rec["accn"] = rev["accn"] if rev else None
        rec["flags"] = ";".join(flags + dflags)
        rows.append(rec)
        debt_detail += [{"fiscal_year": f"FY{fy}A", **d, "val_usd_mn": d["val_usd"] / USD_PER_MN} for d in detail]
    return rows, debt_detail


def latest_shares_outstanding(facts: Mapping, taxonomy: str = "dei",
                              tag: str = "EntityCommonStockSharesOutstanding") -> dict | None:
    """표지(cover page) 발행주식수 중 가장 최근 값. 복수 클래스는 같은 end의 합."""
    entries = _entries(facts, taxonomy, tag, "shares")
    if not entries:
        return None
    last_end = max(e["end"] for e in entries)
    same = [e for e in entries if e["end"] == last_end]
    latest_filed = max(e.get("filed", "") for e in same)
    same = [e for e in same if e.get("filed", "") == latest_filed]
    # 동일 공시 내 클래스별 값(중복 제거 후 합)
    vals = {(e.get("accn"), e.get("frame"), e["val"]) for e in same}
    return {"shares": float(sum(v[2] for v in vals)), "end": last_end, "filed": latest_filed}


# ---------------------------------------------------------------------------
# User-Agent 정리·검증 / 403 요약
# ---------------------------------------------------------------------------
_QUOTES = "\"'`\u201c\u201d\u2018\u2019\u00ab\u00bb"   # 곧은·둥근 따옴표, 백틱, 겹화살괄호
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def normalize_user_agent(raw: str | None) -> str:
    """.env 값 정리: BOM·제어문자·따옴표 제거, 공백 정리. 예) ' "Hong Gildong  a@b.com" ' → 'Hong Gildong a@b.com'."""
    s = (raw or "").replace("\ufeff", "")
    s = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in s)  # 줄바꿈·탭 등
    s = s.translate({ord(q): None for q in _QUOTES})
    return re.sub(r"\s+", " ", s).strip()


def user_agent_problems(ua: str) -> list[str]:
    """SEC 요구 형식(이름 + 이메일) 및 HTTP 헤더 인코딩 검사. 문제 없으면 빈 리스트."""
    problems = []
    if not ua:
        problems.append("값이 비어 있음")
    try:
        ua.encode("latin-1")
    except UnicodeEncodeError:
        problems.append("헤더에 쓸 수 없는 문자(한글·특수 따옴표 등) 포함 → 영문 이름 + 이메일로 입력")
    if not _EMAIL_RE.search(ua):
        problems.append("이메일 주소 없음 → '이름 이메일' 형식 필요 (예: Hong Gildong hong@example.com)")
    elif not _EMAIL_RE.sub("", ua).strip():
        problems.append("이름(또는 회사명) 없음 → '이름 이메일' 형식 권장")
    return problems


def mask_user_agent(ua: str) -> str:
    """진단 출력용 부분 마스킹: 'Shinjae Kang abc+x@users.noreply.github.com' → 'S*** K*** ab***@users.noreply.github.com'."""
    def mask_token(t: str) -> str:
        if "@" in t:
            local, domain = t.split("@", 1)
            return f"{local[:2]}***@{domain}"
        return f"{t[:1]}***" if len(t) > 1 else t
    return " ".join(mask_token(t) for t in ua.split())


def classify_block_page(body: bytes, markers: Mapping[str, str]) -> str | None:
    text = body.decode("utf-8", errors="replace")
    return next((desc for marker, desc in markers.items() if marker.lower() in text.lower()), None)


class SecAccessDenied(FetchError):
    """SEC 403. 같은 원인으로 이후 요청도 실패하므로 호출부는 수집을 중단한다."""


def summarize_403(e: HttpStatusError, markers: Mapping[str, str]) -> str:
    kind = classify_block_page(e.body, markers)
    return (f"SEC 403: User-Agent 확인 필요 ({e.url})" + (f" — {kind}" if kind else "")
            + " → python -m src.data_fetch.sec --diagnose")


# --- 403 지속 기록: 하루 이상 이어지면 User-Agent 문제가 아니라 네트워크·클라이언트 차단일 가능성 ---------
PERSISTENT_403_HINT = ("네트워크·클라이언트 차단 가능성 → 브라우저 다운로드 후 오프라인 모드 "
                       "(python -m src.data_fetch.sec --offline-check)")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def record_403(state_path: Path, now: datetime | None = None) -> float:
    """403 발생 기록 → 최초 403 이후 경과 시간(시간). 상태 파일은 성공하면 clear_403으로 지운다."""
    now = now or _now_utc()
    first = now
    if state_path.exists():
        try:
            first = datetime.fromisoformat(json.loads(state_path.read_text(encoding="utf-8"))["first_403_at"])
        except (ValueError, KeyError, json.JSONDecodeError):
            first = now
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"first_403_at": first.isoformat(), "last_403_at": now.isoformat()}),
                          encoding="utf-8")
    return max((now - first).total_seconds() / 3600, 0.0)


def clear_403(state_path: Path) -> None:
    state_path.unlink(missing_ok=True)


def persistent_403_note(hours: float, threshold_hours: float) -> str:
    """하루(threshold) 이상 403 지속 시 안내 문구, 아니면 빈 문자열."""
    if hours < threshold_hours:
        return ""
    return f"403이 {hours:.0f}시간째 지속 — {PERSISTENT_403_HINT}"


# ---------------------------------------------------------------------------
# 시총(상장사) vs 재무(companyfacts 법인) 주체 검사
# ---------------------------------------------------------------------------
ENTITY_OK, ENTITY_WARN = "OK", "WARN"


def check_entity(ticker: str, listed_cik: int, listed_title: str, facts: Mapping) -> dict:
    """company_tickers의 상장사(시총 주체)와 companyfacts 법인(재무 주체)이 같은 연결 재무인지 검사.

    판정 근거: ① CIK 일치 ② 법인명 완전일치(법인격 표기 제외) ③ 보통주 발행주식수(dei) 보고 ④ EPS 보고.
    상장 지배회사의 연결 재무는 ③·④를 보고하고, 운영 자회사(LLC 등)는 보통 보고하지 않는다.
    same_consolidated: yes(같은 법인) / likely(같은 CIK·보통주·EPS, 이름 표기만 다름) / no(다른 CIK) / unknown
    """
    file_cik = normalize_cik(facts.get("cik"))
    name = str(facts.get("entityName") or "")
    shares = latest_shares_outstanding(facts)
    has_eps = bool(_entries(facts, "us-gaap", "EarningsPerShareBasic", "USD/shares")
                   or _entries(facts, "us-gaap", "EarningsPerShareDiluted", "USD/shares"))
    cik_ok = file_cik is not None and file_cik == int(listed_cik)
    name_ok = names_equal(listed_title, name)
    reasons = []
    if file_cik is None:
        reasons.append("companyfacts에 cik 없음")
    elif not cik_ok:
        reasons.append(f"재무 법인 CIK {cik10(file_cik)} ≠ 상장사 CIK {cik10(listed_cik)}")
    if not name_ok:
        reasons.append(f"entityName '{name}' ≠ 상장사명 '{listed_title}'")
    if shares is None:
        reasons.append("보통주 발행주식수(dei) 미보고")
    if not has_eps:
        reasons.append("EPS 미보고")
    if cik_ok and name_ok and shares is not None:
        same, verdict, why = "yes", ENTITY_OK, "상장사 = 재무 주체"
    elif cik_ok and shares is not None and has_eps:
        same, verdict = "likely", ENTITY_WARN
        why = ("CIK·보통주·EPS는 상장사와 같아 연결 재무일 가능성이 높으나 법인명 표기가 다름 → "
               "10-K 표지 registrant명으로 확인")
    elif not cik_ok and file_cik is not None:
        same, verdict = "no", ENTITY_WARN
        why = ("시총(상장사)과 재무(다른 법인) 주체 불일치 → 배수 계산에 쓰지 말고 "
               f"상장사 CIK{cik10(listed_cik)}.json으로 교체")
    else:
        same, verdict = "unknown", ENTITY_WARN
        why = "보통주·EPS 미보고 → 운영 자회사 등 비상장 법인 재무일 가능성. 상장사 연결 재무 확인 전 배수 계산 보류"
    return {"ticker": ticker, "listed_cik": cik10(listed_cik), "listed_title": listed_title,
            "entity_cik": cik10(file_cik) if file_cik is not None else None, "entity_name": name,
            "cik_match": cik_ok, "name_match": name_ok, "has_shares": shares is not None, "has_eps": has_eps,
            "same_consolidated": same, "verdict": verdict, "reason": why + (f" ({'; '.join(reasons)})" if reasons else "")}


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------
class SecClient:
    def __init__(self, cfg: Mapping, as_of: str, *, http=None, use_cache: bool = True):
        self.cfg = cfg
        self.scfg = cfg["data_fetch"]["sec"]
        self.user_agent = normalize_user_agent(get_secret(self.scfg["env_key"]))  # 없으면 SkipSource
        problems = user_agent_problems(self.user_agent)
        if problems:
            raise SkipSource(f"{self.scfg['env_key']} 형식 오류: {'; '.join(problems)}")
        register_secret(self.user_agent)  # 로그에는 이메일이 남지 않게 마스킹 대상 등록
        self.as_of = as_of
        # 모든 요청(www.sec.gov, data.sec.gov)에 붙는 세션 기본 헤더
        self.session_headers = {"User-Agent": self.user_agent,
                                **{k: str(v) for k, v in (self.scfg.get("session_headers") or {}).items()}}
        self.http = http or make_client(SOURCE, cfg, self.scfg, use_cache=use_cache,
                                        default_headers=self.session_headers)
        if http is not None:
            self.http.session.headers.update(self.session_headers)
        # 초당 요청 상한: 간격 = max(request_delay_sec, 1 / max_requests_per_sec)
        rps = float(self.scfg.get("max_requests_per_sec", 8))
        self.http.request_delay = max(float(self.http.request_delay), 1.0 / rps)
        self.markers = self.scfg.get("block_page_markers") or {}
        self.raw_dir = resolve_path(cfg["paths"]["raw"]) / "sec"
        self.large_dir = resolve_path(cfg["data_fetch"]["output"]["raw_large"]) / "sec"

    def _meta(self, endpoint: str, params: Mapping, fetched_at: str) -> dict:
        return dict(source=SOURCE_LABEL, endpoint=endpoint, params=params, as_of=self.as_of,
                    license_note=self.scfg["license_note"], fetched_at=fetched_at)

    def _get(self, url: str):
        try:
            return self.http.get(url)
        except HttpStatusError as e:
            if e.status_code == 403:
                raise SecAccessDenied(summarize_403(e, self.markers)) from None
            raise

    def fetch_tickers(self) -> pd.DataFrame:
        url = self.scfg["tickers_url"]
        resp = self._get(url)
        payload = resp.json()
        save_raw(self.raw_dir / "company_tickers.json", payload, **self._meta(url, {}, resp.fetched_at))
        return parse_company_tickers(payload)

    def fetch_companyfacts(self, cik: int) -> dict:
        url = build_url(self.scfg["base_url"], self.scfg["endpoints"]["companyfacts"], cik10=cik10(cik))
        resp = self._get(url)
        payload = resp.json()
        # companyfacts 원본은 수 MB → large/ (git 제외)
        save_raw(self.large_dir / f"companyfacts_CIK{cik10(cik)}.json", resp.content,
                 **self._meta(url, {"cik": cik10(cik)}, resp.fetched_at))
        return payload


# ---------------------------------------------------------------------------
# 오프라인 모드: 브라우저로 받은 파일을 온라인 응답과 같은 방식으로 처리
# ---------------------------------------------------------------------------
class ManualFileMissing(FetchError):
    """오프라인 모드에서 필요한 파일이 data/raw/sec_manual/에 없음."""

    def __init__(self, path: Path, url: str):
        super().__init__(f"파일 없음: {path.name} ← {url}")
        self.path, self.url = path, url


def _mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


class OfflineSecSource:
    """data/raw/sec_manual/의 company_tickers.json, CIK##########.json을 읽는다 (네트워크 호출 없음).

    각 파일 옆에 .meta.json(source = 'SEC EDGAR (manual browser download)', fetched_at = 파일 수정 시각)을 쓰고,
    company_tickers.json은 validate가 읽는 data/raw/sec/에도 같은 meta와 함께 복사한다.
    """
    offline = True

    def __init__(self, cfg: Mapping, as_of: str):
        self.cfg = cfg
        self.scfg = cfg["data_fetch"]["sec"]
        self.ocfg = self.scfg.get("offline") or {}
        raw = resolve_path(cfg["paths"]["raw"])
        self.dir = raw / self.ocfg.get("dir", "sec_manual")
        self.raw_dir = raw / "sec"
        self.as_of = as_of
        self.label = self.ocfg.get("source_label", "SEC EDGAR (manual browser download)")

    # --- 경로·URL ------------------------------------------------------------
    def tickers_path(self) -> Path:
        return self.dir / self.ocfg.get("tickers_file", "company_tickers.json")

    def facts_path(self, cik: int | str) -> Path:
        return self.dir / self.ocfg.get("companyfacts_file", "CIK{cik10}.json").format(cik10=cik10(cik))

    def facts_url(self, cik: int | str) -> str:
        return build_url(self.scfg["base_url"], self.scfg["endpoints"]["companyfacts"], cik10=cik10(cik))

    def required(self, ciks: Mapping[str, int] | None = None) -> list[dict]:
        """필요한 파일 목록 [{label, cik, file, url, exists}] (CIK는 config expected_ciks 또는 인자)."""
        ciks = ciks if ciks is not None else (self.ocfg.get("expected_ciks") or {})
        rows = [{"label": "company_tickers.json (CIK 매핑)", "cik": "", "file": self.tickers_path(),
                 "url": self.scfg["tickers_url"], "exists": self.tickers_path().exists()}]
        for t, cik in ciks.items():
            f = self.facts_path(cik)
            rows.append({"label": t, "cik": cik10(cik), "file": f, "url": self.facts_url(cik), "exists": f.exists()})
        return rows

    # --- 읽기 ---------------------------------------------------------------
    def _meta(self, path: Path, url: str, params: Mapping) -> dict:
        return dict(source=self.label, endpoint=url, params=params, as_of=self.as_of,
                    license_note=self.scfg["license_note"], fetched_at=_mtime_utc(path),
                    extra={"download_method": "browser (manual)", "manual_file": path.name,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    def _read(self, path: Path, url: str) -> Any:
        if not path.exists():
            raise ManualFileMissing(path, url)
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:   # 브라우저가 HTML 차단 페이지를 저장한 경우 등
            raise FetchError(f"{path.name} JSON 해석 실패({e.msg}) → 브라우저에서 '원본 JSON'으로 다시 저장") from None

    def fetch_tickers(self) -> pd.DataFrame:
        path, url = self.tickers_path(), self.scfg["tickers_url"]
        payload = self._read(path, url)
        meta = self._meta(path, url, {})
        write_meta(path, **meta)
        save_raw(self.raw_dir / "company_tickers.json", payload, **meta)   # validate 입력 위치
        return parse_company_tickers(payload)

    def fetch_companyfacts(self, cik: int) -> dict:
        path, url = self.facts_path(cik), self.facts_url(cik)
        payload = self._read(path, url)
        write_meta(path, **self._meta(path, url, {"cik": cik10(cik)}))
        return payload


def offline_requirements_text(src: OfflineSecSource, ciks: Mapping[str, int] | None = None) -> str:
    """오프라인 모드에 필요한 파일·URL 목록 (사용자가 브라우저로 받을 대상)."""
    lines = [f"SEC 오프라인 모드 — 브라우저로 받아 {src.dir} 에 저장할 파일:"]
    for r in src.required(ciks):
        mark = "있음" if r["exists"] else "없음"
        cik = f" CIK {r['cik']}" if r["cik"] else ""
        lines.append(f"  [{mark}] {r['label']}{cik}: {r['file'].name}  ←  {r['url']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def _state_path(cfg: Mapping) -> Path:
    o = cfg["data_fetch"]["sec"].get("offline") or {}
    return resolve_path(cfg["paths"]["raw"]) / o.get("state_file", "sec/_403_state.json")


def _on_403(cfg: Mapping, e: Exception, now: datetime | None = None) -> str:
    """403 기록 + 하루 이상 지속이면 차단 가능성 안내를 붙인 한 줄."""
    o = cfg["data_fetch"]["sec"].get("offline") or {}
    hours = record_403(_state_path(cfg), now)
    note = persistent_403_note(hours, float(o.get("persistent_403_hours", 24)))
    return str(e) + (f" | {note}" if note else "")


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: Any = None, offline: bool | None = None,
        out: Callable[[str], None] = print, now: datetime | None = None) -> FetchResult:
    """SEC 수집. offline=True(--sec-offline) 또는 config offline.enabled면 브라우저 다운로드 파일 사용.

    온라인 403이면 offline.auto_on_403일 때 오프라인으로 자동 전환. 오프라인 파일이 없으면 필요한 CIK·URL을
    출력하고 SKIPPED.
    """
    scfg = cfg["data_fetch"]["sec"]
    ocfg = scfg.get("offline") or {}
    use_offline = bool(ocfg.get("enabled")) if offline is None else offline
    notes: list[str] = []
    mode = "online"
    if use_offline:
        src: Any = client if getattr(client, "offline", False) else OfflineSecSource(cfg, as_of)
        mode = "offline"
        notes.append("오프라인 모드(--sec-offline): " + src.label)
    else:
        src = client or SecClient(cfg, as_of, use_cache=use_cache)
    return _collect(cfg, as_of, src, mode, notes, out, now)


def _switch_offline(cfg: Mapping, as_of: str, notes: list[str], e: Exception, now: datetime | None) -> Any:
    o = cfg["data_fetch"]["sec"].get("offline") or {}
    notes.append(_on_403(cfg, e, now))
    if not o.get("auto_on_403", True):
        return None
    src = OfflineSecSource(cfg, as_of)
    notes.append("→ 오프라인 모드 자동 전환: " + src.label)
    return src


def _collect(cfg: Mapping, as_of: str, src: Any, mode: str, notes: list[str], out: Callable[[str], None],
             now: datetime | None) -> FetchResult:
    scfg = cfg["data_fetch"]["sec"]
    ocfg = scfg.get("offline") or {}
    years = cfg["data_fetch"]["fiscal_years"]
    skip = set(scfg.get("not_sec_registrants", []))
    expected = {k.upper(): int(v) for k, v in (ocfg.get("expected_ciks") or {}).items()}
    targets = [p for p in cfg["peers"]["overseas"] if p["ticker"].upper() not in skip]
    missing: list[ManualFileMissing] = []

    def skipped_missing() -> FetchResult:
        off = src if getattr(src, "offline", False) else OfflineSecSource(cfg, as_of)
        out(offline_requirements_text(off))
        notes.append(f"오프라인 파일 없음 {len(missing)}개 → 필요한 CIK·URL 목록 출력 (python -m src.data_fetch.sec --offline-check)")
        return FetchResult(SOURCE, STATUS_SKIPPED, message="; ".join(notes))

    # 1) CIK 매핑 -----------------------------------------------------------------
    try:
        with Progress(SOURCE, "CIK 매핑", 1).step("company_tickers.json" + (" (offline)" if mode == "offline" else "")):
            tick = src.fetch_tickers()
    except SecAccessDenied as e:  # HTML 차단 페이지 대신 한 줄 요약만 기록
        src = _switch_offline(cfg, as_of, notes, e, now)
        if src is None:
            return FetchResult(SOURCE, STATUS_FAILED, message="; ".join(notes))
        mode = "offline"
        try:
            tick = src.fetch_tickers()
        except ManualFileMissing as m:
            missing.append(m)
            return skipped_missing()
    except ManualFileMissing as m:
        missing.append(m)
        return skipped_missing()
    if mode == "online":
        clear_403(_state_path(cfg))
    raw_dir = resolve_path(cfg["paths"]["raw"]) / "sec"
    outputs = [str(raw_dir / "company_tickers.json")]
    fin_rows, debt_rows, share_rows, entity_rows = [], [], [], []

    # 2) companyfacts ---------------------------------------------------------------
    prog = Progress(SOURCE, "companyfacts", len(targets))
    for peer in cfg["peers"]["overseas"]:
        t = peer["ticker"].upper()
        if t in skip:
            notes.append(f"{peer['name']}({t}): SEC 공시 대상 아님 → data/manual 수기 입력 대상")
            continue
        hit = tick[tick["ticker"] == t]
        if hit.empty:
            notes.append(f"{peer['name']}({t}): company_tickers.json에 없음")
            continue
        listed_cik, listed_title = int(hit.iloc[0]["cik"]), str(hit.iloc[0]["title"])
        if t in expected and expected[t] != listed_cik:
            notes.append(f"{peer['name']}: config expected_ciks {cik10(expected[t])} ≠ company_tickers {cik10(listed_cik)}")
        cik = listed_cik
        if getattr(src, "offline", False) and not src.facts_path(cik).exists() and t in expected \
                and src.facts_path(expected[t]).exists():
            cik = expected[t]   # 사용자가 받은 파일(다른 CIK) → 주체 검사에서 불일치로 표시
        try:
            with prog.step(f"{peer['name']} CIK{cik10(cik)}" + (" (offline)" if getattr(src, "offline", False) else "")):
                facts = src.fetch_companyfacts(cik)
        except SecAccessDenied as e:  # 403은 이후 요청도 같은 원인 → 반복 요청하지 않고 오프라인 전환 또는 중단
            new = _switch_offline(cfg, as_of, notes, e, now)
            if new is None:
                notes[-1] = f"{peer['name']}: {notes[-1]} (이후 companyfacts 요청 중단)"
                break
            src, mode = new, "offline"
            try:
                facts = src.fetch_companyfacts(cik)
            except ManualFileMissing as m:
                missing.append(m)
                continue
        except ManualFileMissing as m:
            missing.append(m)
            continue
        except FetchError as e:  # 타임아웃·JSON 오류 포함: 해당 회사만 건너뜀
            notes.append(mask_secrets(f"{peer['name']} companyfacts 실패: {e}"))
            continue
        rows, detail = extract_company_financials(facts, scfg, years)
        ent = check_entity(t, listed_cik, listed_title, facts)
        entity_rows.append({"company": peer["name"], **ent})
        data_source = "manual browser download" if getattr(src, "offline", False) else "online API"
        base = {"company": peer["name"], "ticker": t, "cik": cik10(normalize_cik(facts.get("cik")) or cik),
                "entity_name": facts.get("entityName")}
        fin_rows += [{**base, "basis": "US GAAP (consolidated)", "currency": "USD", "unit": "mn",
                      "data_source": data_source, "entity_check": ent["verdict"], **r} for r in rows]
        debt_rows += [{**base, **d} for d in detail]
        tag = scfg.get("shares_tag", ["dei", "EntityCommonStockSharesOutstanding"])
        sh = latest_shares_outstanding(facts, tag[0], tag[1])
        if sh:
            share_rows.append({**base, **sh})
        if ent["verdict"] != ENTITY_OK:
            notes.append(f"{peer['name']}: 주체 검사 WARN — {ent['reason']}")

    processed = resolve_path(cfg["paths"]["processed"])
    label = (ocfg.get("source_label", SOURCE_LABEL) if mode == "offline" else SOURCE_LABEL)
    if fin_rows:
        save_processed(processed / "sec_financials.csv", pd.DataFrame(fin_rows), sources=[label],
                       as_of=as_of, note="USD mn, 10-K 연간값(최신 filed 기준). 총차입금 정의는 config ASSUMPTION 참조. "
                                         "data_source 열: online API / manual browser download")
        save_processed(processed / "sec_debt_components.csv", pd.DataFrame(debt_rows), sources=[label],
                       as_of=as_of, note="총차입금 구성 태그 (검산용)")
        outputs += [str(processed / "sec_financials.csv"), str(processed / "sec_debt_components.csv")]
    if share_rows:
        save_processed(processed / "sec_shares_outstanding.csv", pd.DataFrame(share_rows),
                       sources=[label], as_of=as_of, note="dei:EntityCommonStockSharesOutstanding (표지)")
        outputs.append(str(processed / "sec_shares_outstanding.csv"))
    if entity_rows:
        ep = processed / (scfg.get("entity_check") or {}).get("output", "sec_entity_check.csv")
        save_processed(ep, pd.DataFrame(entity_rows), sources=[label], as_of=as_of,
                       note="시총(company_tickers 상장사) vs 재무(companyfacts 법인) 주체 검사. verdict OK/WARN")
        outputs.append(str(ep))

    n_done = len({r["ticker"] for r in fin_rows})
    if missing:
        off = src if getattr(src, "offline", False) else OfflineSecSource(cfg, as_of)
        need = {t: c for t, c in expected.items()}
        for p in targets:   # 매핑에서 확인한 CIK 우선
            h = tick[tick["ticker"] == p["ticker"].upper()]
            if not h.empty:
                need[p["ticker"].upper()] = int(h.iloc[0]["cik"])
        out(offline_requirements_text(off, need))
        notes.append(f"오프라인 파일 없음 {len(missing)}개: " + ", ".join(m.path.name for m in missing))
        if n_done == 0:
            return FetchResult(SOURCE, STATUS_SKIPPED, outputs=outputs, message="; ".join(notes))
    errs = [n for n in notes if "SEC 공시 대상 아님" not in n and not n.startswith("오프라인 모드(")
            and not n.startswith("→ 오프라인") and "SEC 403" not in n and "주체 검사 WARN" not in n
            and "expected_ciks" not in n]   # 정보성 메모(검증 결과는 validate·주체 검사에서 판정)
    status = (STATUS_SUCCESS if n_done == len(targets) and not errs and not missing
              else (STATUS_PARTIAL if n_done else STATUS_FAILED))
    return FetchResult(SOURCE, status, n_items=n_done, outputs=outputs, message="; ".join(notes))


# ---------------------------------------------------------------------------
# 진단: python -m src.data_fetch.sec --diagnose [--probe]
# ---------------------------------------------------------------------------
def _mask_proxy(url: str) -> str:
    parts = urlsplit(url)
    return url.replace(parts.netloc, f"***@{parts.hostname}:{parts.port}") if parts.username else url


def diagnose(cfg: Mapping, *, probe: bool = False, out: Callable[[str], None] = print,
             session: Any = None) -> int:
    """403 원인 확인용. 실제로 보낼 헤더(User-Agent 부분 마스킹)·프록시·속도 설정 출력. probe=True면 1회 실제 요청."""
    import os

    import requests

    from .base import load_env

    scfg = cfg["data_fetch"]["sec"]
    env_key = scfg["env_key"]
    ok = True
    out("=== SEC 접속 진단 ===")
    env_path = PROJECT_ROOT / ".env"
    load_env()
    out(f"- .env 파일: {'있음' if env_path.exists() else '없음'} ({env_path})")
    raw = os.environ.get(env_key)
    if not raw:
        out(f"- {env_key}: 미설정 → .env에 '{env_key}=영문이름 이메일' 입력")
        return 1
    ua = normalize_user_agent(raw)
    register_secret(ua)
    cleaned = []
    if raw != raw.strip():
        cleaned.append("앞뒤 공백")
    if any(q in raw for q in _QUOTES):
        cleaned.append("따옴표")
    if re.search(r"\s{2,}", raw.strip()):
        cleaned.append("연속 공백")
    out(f"- {env_key} 원문 길이 {len(raw)}자" + (f", 정리한 항목: {', '.join(cleaned)}" if cleaned else ", 정리 불필요"))
    out(f"- 전송할 User-Agent (부분 마스킹): {mask_user_agent(ua)}")
    for p in user_agent_problems(ua):
        ok = False
        out(f"  ✗ {p}")
    if ok:
        out("  ✓ 형식 확인: ASCII, 이름 + 이메일")
    if "noreply" in ua.lower():
        out("  ! 참고(ASSUMPTION): SEC는 연락 가능한 이메일을 요구함. noreply 주소가 403 원인일 수 있어 실제 메일 주소로 바꿔 시험 권장")

    try:
        client = SecClient(cfg, cfg["data_fetch"]["as_of_default"], use_cache=False,
                           http=None if session is None else _client_with_session(cfg, session))
    except SkipSource as e:
        out(f"- 클라이언트 생성 실패: {e}")
        return 1
    out(f"- 요청 간격 {client.http.request_delay:.3f}초 → 최대 {1 / client.http.request_delay:.1f}건/초 (SEC 상한 10건/초 미만)")
    out(f"- 타임아웃 (연결 {client.http.connect_timeout:.0f}초, 응답 {client.http.read_timeout:.0f}초)")

    urls = [scfg["tickers_url"], build_url(scfg["base_url"], scfg["endpoints"]["companyfacts"], cik10=cik10(1674101))]
    sess = client.http.session
    preview = requests.Session()               # 요청은 보내지 않고, requests의 헤더 병합 결과만 계산
    preview.headers.update(dict(sess.headers))
    for url in urls:
        prepared = preview.prepare_request(requests.Request("GET", url))
        out(f"- 실제 전송 헤더: GET {url}")
        out(f"    Host: {urlsplit(url).hostname}  (URL에서 자동 설정)")
        for k, v in prepared.headers.items():
            out(f"    {k}: {mask_user_agent(v) if k.lower() == 'user-agent' else v}")
        proxies = requests.utils.get_environ_proxies(url) if getattr(sess, "trust_env", True) else {}
        proxies = {k: v for k, v in proxies.items() if k in ("http", "https", "all")}
        out("    프록시: " + (", ".join(f"{k}={_mask_proxy(v)}" for k, v in proxies.items()) or "없음 (직접 연결)"))

    if probe:
        url = scfg["tickers_url"]
        out(f"- 실제 요청 1회: GET {url}")
        try:
            resp = client._get(url)
            out(f"  ✓ HTTP {resp.status_code}, {len(resp.content):,} bytes → 접속 정상")
        except SecAccessDenied as e:
            ok = False
            out(f"  ✗ {_on_403(cfg, e)}")
            out("    다음 확인: ① 이메일을 실제 주소로 ② VPN·회사 프록시 끄고 재시도 ③ 직전 과다 요청이면 10분 후 재시도")
            out(f"    하루 이상 403이 이어지면: {PERSISTENT_403_HINT}")
        except FetchError as e:
            ok = False
            out(f"  ✗ {mask_secrets(e)}")
    else:
        out("- 실제 요청은 하지 않음 (--probe를 붙이면 company_tickers.json 1회 요청)")
    off = OfflineSecSource(cfg, cfg["data_fetch"]["as_of_default"])
    req = off.required()
    out(f"- 오프라인 파일 ({off.dir}): {sum(r['exists'] for r in req)}/{len(req)}개 있음 "
        "→ 목록: python -m src.data_fetch.sec --offline-check")
    return 0 if ok else 1


def _client_with_session(cfg: Mapping, session: Any):
    return make_client(SOURCE, cfg, cfg["data_fetch"]["sec"], use_cache=False, session=session)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SEC EDGAR 수집 도구 (수집은 fetch_all --source sec)")
    p.add_argument("--diagnose", action="store_true", help="실제 전송 헤더·프록시·속도 설정 출력 (네트워크 호출 없음)")
    p.add_argument("--probe", action="store_true", help="--diagnose와 함께: company_tickers.json 1회 실제 요청")
    p.add_argument("--offline-check", action="store_true",
                   help="오프라인 모드에 필요한 파일·URL과 존재 여부 출력 (네트워크 호출 없음)")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    if args.offline_check:
        cfg = load_config(args.config)
        src = OfflineSecSource(cfg, cfg["data_fetch"]["as_of_default"])
        print(offline_requirements_text(src))
        missing = [r for r in src.required() if not r["exists"]]
        print(f"\n없는 파일 {len(missing)}개." + (" 브라우저로 위 URL을 열어 '원본 JSON'으로 저장하세요." if missing else
              " 수집: python -m src.data_fetch.fetch_all --source sec --sec-offline"))
        return 0
    if not args.diagnose:
        p.print_help()
        print("\n수집 실행: python -m src.data_fetch.fetch_all --source sec  (403이면 --sec-offline)")
        return 0
    return diagnose(load_config(args.config), probe=args.probe)


if __name__ == "__main__":
    sys.exit(main())
