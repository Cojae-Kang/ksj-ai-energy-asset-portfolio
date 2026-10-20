"""SEC EDGAR: company_tickers.json(CIK 매핑) + XBRL companyfacts(연간 재무).

추출 지표: Revenue, OperatingIncome, NetIncome, 총차입금, 현금 (USD → USD mn).
SEC fair access: User-Agent 헤더(이름 + 이메일) 필수, 초당 10건 미만, Accept-Encoding: gzip, deflate.

403 진단: python -m src.data_fetch.sec --diagnose          (실제 전송 헤더 확인, 네트워크 호출 없음)
          python -m src.data_fetch.sec --diagnose --probe  (company_tickers.json 1회 실제 요청)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import unicodedata
from datetime import datetime
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import pandas as pd

from .base import (PROJECT_ROOT, FetchError, FetchResult, HttpStatusError, Progress, SkipSource,
                   STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS, build_url, get_secret, load_config,
                   make_client, mask_secrets, register_secret, resolve_path, save_processed, save_raw)

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


def cik10(cik: int | str) -> str:
    return str(int(cik)).zfill(10)


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


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: SecClient | None = None) -> FetchResult:
    c = client or SecClient(cfg, as_of, use_cache=use_cache)
    scfg = cfg["data_fetch"]["sec"]
    years = cfg["data_fetch"]["fiscal_years"]
    skip = set(scfg.get("not_sec_registrants", []))
    try:
        with Progress(SOURCE, "CIK 매핑", 1).step("company_tickers.json"):
            tick = c.fetch_tickers()
    except SecAccessDenied as e:  # HTML 차단 페이지 대신 한 줄 요약만 기록
        return FetchResult(SOURCE, STATUS_FAILED, message=str(e))
    outputs = [str(c.raw_dir / "company_tickers.json")]
    notes, fin_rows, debt_rows, share_rows = [], [], [], []

    prog = Progress(SOURCE, "companyfacts", len([p for p in cfg["peers"]["overseas"]
                                                 if p["ticker"].upper() not in skip]))
    for peer in cfg["peers"]["overseas"]:
        t = peer["ticker"].upper()
        if t in skip:
            notes.append(f"{peer['name']}({t}): SEC 공시 대상 아님 → data/manual 수기 입력 대상")
            continue
        hit = tick[tick["ticker"] == t]
        if hit.empty:
            notes.append(f"{peer['name']}({t}): company_tickers.json에 없음")
            continue
        cik = int(hit.iloc[0]["cik"])
        try:
            with prog.step(f"{peer['name']} CIK{cik10(cik)}"):
                facts = c.fetch_companyfacts(cik)
        except SecAccessDenied as e:  # 403은 이후 요청도 같은 원인 → 반복 요청하지 않고 중단
            notes.append(f"{peer['name']}: {e} (이후 companyfacts 요청 중단)")
            break
        except FetchError as e:  # 타임아웃 포함: 해당 회사만 건너뜀
            notes.append(mask_secrets(f"{peer['name']} companyfacts 실패: {e}"))
            continue
        rows, detail = extract_company_financials(facts, scfg, years)
        base = {"company": peer["name"], "ticker": t, "cik": cik10(cik), "entity_name": facts.get("entityName")}
        fin_rows += [{**base, "basis": "US GAAP (consolidated)", "currency": "USD", "unit": "mn", **r}
                     for r in rows]
        debt_rows += [{**base, **d} for d in detail]
        tag = scfg.get("shares_tag", ["dei", "EntityCommonStockSharesOutstanding"])
        sh = latest_shares_outstanding(facts, tag[0], tag[1])
        if sh:
            share_rows.append({**base, **sh})

    processed = resolve_path(cfg["paths"]["processed"])
    if fin_rows:
        save_processed(processed / "sec_financials.csv", pd.DataFrame(fin_rows), sources=[SOURCE_LABEL],
                       as_of=as_of, note="USD mn, 10-K 연간값(최신 filed 기준). 총차입금 정의는 config ASSUMPTION 참조.")
        save_processed(processed / "sec_debt_components.csv", pd.DataFrame(debt_rows), sources=[SOURCE_LABEL],
                       as_of=as_of, note="총차입금 구성 태그 (검산용)")
        outputs += [str(processed / "sec_financials.csv"), str(processed / "sec_debt_components.csv")]
    if share_rows:
        save_processed(processed / "sec_shares_outstanding.csv", pd.DataFrame(share_rows),
                       sources=[SOURCE_LABEL], as_of=as_of, note="dei:EntityCommonStockSharesOutstanding (표지)")
        outputs.append(str(processed / "sec_shares_outstanding.csv"))

    n_target = len([p for p in cfg["peers"]["overseas"] if p["ticker"].upper() not in skip])
    n_done = len({r["ticker"] for r in fin_rows})
    errs = [n for n in notes if "SEC 공시 대상 아님" not in n]
    status = STATUS_SUCCESS if n_done == n_target and not errs else (STATUS_PARTIAL if n_done else STATUS_FAILED)
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
            out(f"  ✗ {e}")
            out("    다음 확인: ① 이메일을 실제 주소로 ② VPN·회사 프록시 끄고 재시도 ③ 직전 과다 요청이면 10분 후 재시도")
        except FetchError as e:
            ok = False
            out(f"  ✗ {mask_secrets(e)}")
    else:
        out("- 실제 요청은 하지 않음 (--probe를 붙이면 company_tickers.json 1회 요청)")
    return 0 if ok else 1


def _client_with_session(cfg: Mapping, session: Any):
    return make_client(SOURCE, cfg, cfg["data_fetch"]["sec"], use_cache=False, session=session)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SEC EDGAR 수집 도구 (수집은 fetch_all --source sec)")
    p.add_argument("--diagnose", action="store_true", help="실제 전송 헤더·프록시·속도 설정 출력 (네트워크 호출 없음)")
    p.add_argument("--probe", action="store_true", help="--diagnose와 함께: company_tickers.json 1회 실제 요청")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    if not args.diagnose:
        p.print_help()
        print("\n수집 실행: python -m src.data_fetch.fetch_all --source sec")
        return 0
    return diagnose(load_config(args.config), probe=args.probe)


if __name__ == "__main__":
    sys.exit(main())
