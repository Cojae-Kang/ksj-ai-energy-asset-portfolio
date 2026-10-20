"""Open DART 수집: 고유번호 매핑, 단일회사 전체 재무제표, 발행공시 검색, 공시 원문.

출처: 금융감독원 전자공시시스템 Open DART (https://opendart.fss.or.kr)
금액 단위: API 원(KRW) → 가공 시 KRW 억원.
"""
from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping

import pandas as pd

from .base import (FetchError, FetchResult, Progress, STATUS_FAILED, STATUS_PARTIAL,
                   STATUS_SUCCESS, build_url, get_secret, make_client, mask_secrets, resolve_path,
                   save_processed, save_raw, to_number)

logger = logging.getLogger("data_fetch.dart")

SOURCE = "dart"
KRW_PER_100M = 1e8  # 1억원

STATUS_OK = "000"
STATUS_NO_DATA = "013"


class DartAPIError(FetchError):
    def __init__(self, status: str, message: str):
        super().__init__(f"DART status {status}: {message}")
        self.status = status


# ---------------------------------------------------------------------------
# 순수 파싱 함수 (테스트 대상)
# ---------------------------------------------------------------------------
def parse_corp_code_zip(content: bytes) -> pd.DataFrame:
    """corpCode.xml 응답(zip 안의 CORPCODE.xml) → DataFrame[corp_code, corp_name, stock_code, modify_date]."""
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise _error_from_payload(content)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
        root = ET.fromstring(zf.read(xml_name))
    rows = []
    for item in root.iter("list"):
        rows.append({
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "corp_eng_name": (item.findtext("corp_eng_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        })
    return pd.DataFrame(rows, dtype=str)


def _error_from_payload(content: bytes) -> DartAPIError:
    """zip 대신 돌아온 오류 응답(XML 또는 JSON)에서 status/message 추출."""
    text = content.decode("utf-8", errors="replace")
    m_status = re.search(r'<status>(\w+)</status>|"status"\s*:\s*"(\w+)"', text)
    m_msg = re.search(r"<message>(.*?)</message>|\"message\"\s*:\s*\"(.*?)\"", text, re.S)
    status = next((g for g in (m_status.groups() if m_status else ()) if g), "unknown")
    message = next((g for g in (m_msg.groups() if m_msg else ()) if g), text[:200])
    return DartAPIError(status, message)


def check_status(payload: Mapping) -> bool:
    """정상이면 True, 데이터 없음(013)이면 False, 그 외 오류는 예외."""
    status = str(payload.get("status", ""))
    if status == STATUS_OK:
        return True
    if status == STATUS_NO_DATA:
        return False
    raise DartAPIError(status, str(payload.get("message", "")))


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _pick_account(rows: list[dict], sj_divs: list[str], ids: list[str], names: list[str]) -> dict | None:
    """sj_div 우선순위대로 account_id 일치 → account_nm 일치 순으로 첫 행 선택."""
    for sj in sj_divs:
        cand = [r for r in rows if r.get("sj_div") == sj]
        for aid in ids:
            hit = next((r for r in cand if r.get("account_id") == aid), None)
            if hit:
                return hit
        norm_names = [_norm(n) for n in names]
        for nn in norm_names:
            hit = next((r for r in cand if _norm(r.get("account_nm")) == nn), None)
            if hit:
                return hit
    return None


def _is_detail_row(r: Mapping) -> bool:
    d = str(r.get("account_detail", "-") or "-").strip()
    return d not in ("-", "")


def select_debt_lines(rows: list[dict], debt_cfg: Mapping) -> list[dict]:
    """총차입금 구성 행 선택 (ASSUMPTION: config dart.total_debt)."""
    inc = [re.compile(p) for p in debt_cfg.get("include_name_patterns", [])]
    exc = [re.compile(p) for p in debt_cfg.get("exclude_name_patterns", [])]
    sj_divs = set(debt_cfg.get("sj_div", ["BS"]))
    out = []
    for r in rows:
        if r.get("sj_div") not in sj_divs:
            continue
        if debt_cfg.get("exclude_detail_rows", True) and _is_detail_row(r):
            continue
        nm = _norm(r.get("account_nm"))
        if any(p.search(nm) for p in inc) and not any(p.search(nm) for p in exc):
            out.append(r)
    return out


def extract_dart_metrics(rows: list[dict], dart_cfg: Mapping) -> tuple[dict, list[dict], list[str]]:
    """fnlttSinglAcntAll list → (지표 dict[KRW 억원], 차입금 구성행, 플래그).

    thstrm_amount(당기) 기준. 금액은 원 → 억원.
    """
    acc = dart_cfg["accounts"]
    metrics: dict[str, float] = {}
    flags: list[str] = []
    for metric, spec in acc.items():
        hit = _pick_account(rows, spec["sj_div"], spec.get("account_ids", []), spec.get("account_names", []))
        if hit is None and (spec.get("fallback_account_ids") or spec.get("fallback_account_names")):
            hit = _pick_account(rows, spec["sj_div"], spec.get("fallback_account_ids", []),
                                spec.get("fallback_account_names", []))
            if hit is not None:
                flags.append(f"{metric}:fallback({hit.get('account_nm')})")
        if hit is None:
            metrics[metric] = float("nan")
            flags.append(f"{metric}:missing")
        else:
            metrics[metric] = to_number(hit.get("thstrm_amount")) / KRW_PER_100M

    debt_rows = select_debt_lines(rows, dart_cfg["total_debt"])
    if debt_rows:
        metrics["total_debt"] = sum(
            v for v in (to_number(r.get("thstrm_amount")) for r in debt_rows) if v == v
        ) / KRW_PER_100M
    else:
        metrics["total_debt"] = float("nan")
        flags.append("total_debt:missing")
    debt_detail = [{"account_id": r.get("account_id"), "account_nm": r.get("account_nm"),
                    "amount_krw_100m": to_number(r.get("thstrm_amount")) / KRW_PER_100M}
                   for r in debt_rows]
    return metrics, debt_detail, flags


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    last_day = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


def month_windows(bgn: date, end: date, months: int = 3) -> list[tuple[date, date]]:
    """[bgn, end]를 months개월 단위 구간으로 분할 (corp_code 미지정 시 DART 검색기간 3개월 제한 대응).

    예: 2025-01-01~2025-12-31, 3개월 → 01-01~03-31, 04-01~06-30, 07-01~09-30, 10-01~12-31
    """
    out, cur = [], bgn
    while cur <= end:
        stop = min(_add_months(cur, months) - timedelta(days=1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out


def _ymd(s: str | date) -> date:
    if isinstance(s, date):
        return s
    s = str(s).replace("-", "")
    return datetime.strptime(s, "%Y%m%d").date()


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------
class DartClient:
    def __init__(self, cfg: Mapping, as_of: str, *, http=None, use_cache: bool = True,
                 raw_dir: Path | None = None, large_dir: Path | None = None):
        self.cfg = cfg
        self.dcfg = cfg["data_fetch"]["dart"]
        self.key = get_secret(self.dcfg["env_key"])  # 없으면 SkipSource
        self.as_of = as_of
        self.http = http or make_client(SOURCE, cfg, self.dcfg, use_cache=use_cache)
        self.raw_dir = raw_dir or resolve_path(cfg["paths"]["raw"]) / "dart"
        self.large_dir = large_dir or resolve_path(cfg["data_fetch"]["output"]["raw_large"]) / "dart"
        self._corp_map: pd.DataFrame | None = None

    def _url(self, name: str) -> str:
        return build_url(self.dcfg["base_url"], self.dcfg["endpoints"][name])

    def _meta(self, name: str, params: Mapping, fetched_at: str | None = None, **extra) -> dict:
        return dict(source="Open DART (금융감독원)", endpoint=self._url(name), params=params,
                    as_of=self.as_of, license_note=self.dcfg["license_note"], fetched_at=fetched_at,
                    extra=extra or None)

    def _get_json(self, name: str, params: dict) -> tuple[dict, str]:
        resp = self.http.get(self._url(name), params={"crtfc_key": self.key, **params})
        return resp.json(), resp.fetched_at

    # --- 1) 고유번호 매핑 ---------------------------------------------------
    def fetch_corp_codes(self) -> pd.DataFrame:
        resp = self.http.get(self._url("corp_code"), params={"crtfc_key": self.key})
        df = parse_corp_code_zip(resp.content)
        save_raw(self.large_dir / "corpCode.zip", resp.content, **self._meta("corp_code", {}, resp.fetched_at))
        listed = df[df["stock_code"].str.len() > 0].reset_index(drop=True)
        save_raw(self.raw_dir / "corp_codes_listed.csv", listed,
                 **self._meta("corp_code", {}, resp.fetched_at, note="상장사(stock_code 보유)만 저장"))
        self._corp_map = df
        logger.info("DART 고유번호 %d건 (상장 %d건)", len(df), len(listed))
        return df

    def corp_code_for(self, stock_code: str) -> str | None:
        if self._corp_map is None:
            self.fetch_corp_codes()
        hit = self._corp_map[self._corp_map["stock_code"] == str(stock_code).zfill(6)]
        return None if hit.empty else hit.iloc[0]["corp_code"]

    # --- 2) 단일회사 전체 재무제표 ------------------------------------------
    def fetch_financials(self, corp_code: str, year: int, stock_code: str = "") -> tuple[list[dict], str | None]:
        """CFS 우선, 없으면(013) OFS. 반환: (list rows, 사용한 fs_div 또는 None)."""
        for fs_div in self.dcfg["fs_div_priority"]:
            params = {"corp_code": corp_code, "bsns_year": str(year),
                      "reprt_code": self.dcfg["reprt_code"], "fs_div": fs_div}
            payload, fetched_at = self._get_json("fnltt_all", params)
            if not check_status(payload):
                logger.info("DART %s FY%s %s 데이터 없음 → 다음 구분", stock_code or corp_code, year, fs_div)
                continue
            fname = f"fnltt_{stock_code or corp_code}_{year}_{fs_div}.json"
            save_raw(self.raw_dir / fname, payload, **self._meta("fnltt_all", params, fetched_at))
            return payload.get("list", []), fs_div
        return [], None

    # --- 3) 발행공시 검색 --------------------------------------------------
    def search_filings(self, bgn_de: str, end_de: str, *, corp_code: str | None = None,
                       label: str = "", prog: Progress | None = None) -> tuple[pd.DataFrame, list[str]]:
        """발행공시 검색. corp_code 없으면 window_months 단위로 나눠 반복, 구간(회사)당 max_pages 상한.

        타임아웃 등 요청 오류는 해당 구간만 건너뛰고 notes에 기록 후 계속.
        반환: (필터링된 DataFrame, notes)
        """
        f = self.dcfg["filings"]
        bgn, end = _ymd(bgn_de), _ymd(end_de)
        windows = [(bgn, end)] if corp_code else month_windows(bgn, end, int(f["window_months"]))
        max_pages = int(f["max_pages"])
        prog = prog or Progress(SOURCE, "공시검색", len(windows))
        frames, notes = [], []
        for wb, we in windows:
            page = 1
            while True:
                params = {"bgn_de": wb.strftime("%Y%m%d"), "end_de": we.strftime("%Y%m%d"),
                          "pblntf_ty": f["pblntf_ty"], "page_no": page, "page_count": f["page_count"]}
                if f.get("pblntf_detail_ty"):
                    params["pblntf_detail_ty"] = f["pblntf_detail_ty"]
                if corp_code:
                    params["corp_code"] = corp_code
                span = f"{label} {params['bgn_de']}~{params['end_de']} p{page}".strip()
                try:
                    with prog.step(span) as st:
                        payload, _ = self._get_json("list", params)
                        has_data = check_status(payload)
                        total_page = int(payload.get("total_page", 1) or 1) if has_data else 0
                        st["note"] = f"({len(payload.get('list', []) or [])}건, 총 {total_page}p)" if has_data else ""
                        if not has_data:
                            st["status"] = "데이터 없음"
                except FetchError as e:  # RequestTimeout 포함 → 이 구간만 건너뜀
                    notes.append(mask_secrets(f"공시검색 {span} 건너뜀: {e}"))
                    break
                if not has_data:
                    break
                frames.append(pd.DataFrame(payload.get("list", [])))
                if page >= total_page:
                    break
                if page >= max_pages:
                    notes.append(f"공시검색 {span}: 총 {total_page}p 중 max_pages={max_pages}에서 중단")
                    break
                page += 1
        frames = [x for x in frames if not x.empty]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if not df.empty and f.get("report_nm_contains"):
            pat = "|".join(re.escape(k) for k in f["report_nm_contains"])
            df = df[df["report_nm"].str.contains(pat, na=False)].reset_index(drop=True)
        return df, notes

    # --- 4) 공시 원문 ------------------------------------------------------
    def download_document(self, rcept_no: str) -> Path:
        params = {"rcept_no": rcept_no}
        resp = self.http.get(self._url("document"), params={"crtfc_key": self.key, **params})
        if not zipfile.is_zipfile(io.BytesIO(resp.content)):
            raise _error_from_payload(resp.content)
        return save_raw(self.large_dir / "documents" / f"{rcept_no}.zip", resp.content,
                        **self._meta("document", params, resp.fetched_at))


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run_filings(c: DartClient, cfg: Mapping, as_of: str, peer_codes: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """발행공시 검색 + 원문 다운로드 (config dart.filings.enabled=true일 때만)."""
    f = cfg["data_fetch"]["dart"]["filings"]
    end_de = f.get("end_de") or as_of.replace("-", "")
    outputs, notes = [], []
    if f.get("mode", "market") == "peers":
        prog = Progress(SOURCE, "공시검색(peers)", len(peer_codes))
        parts = []
        for name, code in peer_codes:
            df, n = c.search_filings(f["bgn_de"], end_de, corp_code=code, label=name, prog=prog)
            parts.append(df)
            notes += n
        parts = [x for x in parts if not x.empty]
        filings = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    else:
        filings, notes = c.search_filings(f["bgn_de"], end_de)

    fpath = c.raw_dir / f"filings_{f.get('mode', 'market')}_{f['bgn_de']}_{end_de}.csv"
    save_raw(fpath, filings, **c._meta("list", {"pblntf_ty": f["pblntf_ty"], "pblntf_detail_ty": f.get("pblntf_detail_ty"),
                                                "bgn_de": f["bgn_de"], "end_de": end_de, "mode": f.get("mode")}))
    outputs.append(str(fpath))

    docs_cfg = f.get("documents") or {}
    docs = [str(r) for r in (docs_cfg.get("rcept_nos") or [])]
    n_auto = int(docs_cfg.get("max_from_search") or 0)
    if n_auto and not filings.empty:
        docs += [str(r) for r in filings["rcept_no"].head(n_auto) if str(r) not in docs]
    prog = Progress(SOURCE, "공시원문", len(docs))
    for rno in docs:
        try:
            with prog.step(rno):
                outputs.append(str(c.download_document(rno)))
        except FetchError as e:
            notes.append(mask_secrets(f"원문 {rno}: {e}"))
    return outputs, notes


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: DartClient | None = None) -> FetchResult:
    c = client or DartClient(cfg, as_of, use_cache=use_cache)  # 키 없으면 SkipSource
    dcfg = cfg["data_fetch"]["dart"]
    years = cfg["data_fetch"]["fiscal_years"]
    outputs, errors = [], []

    with Progress(SOURCE, "고유번호", 1).step("corpCode.xml"):
        c.fetch_corp_codes()  # 실패하면 소스 전체 FAILED (재무제표 조회 불가)
    outputs.append(str(c.raw_dir / "corp_codes_listed.csv"))

    fin_rows, debt_rows, peer_codes = [], [], []
    peers = cfg["peers"]["domestic"]
    prog = Progress(SOURCE, "재무제표", len(peers) * len(years))
    for peer in peers:
        ticker = str(peer["ticker"]).zfill(6)
        corp_code = c.corp_code_for(ticker)
        if not corp_code:
            errors.append(f"{peer['name']}({ticker}) corp_code 없음")
            prog.i += len(years)
            continue
        peer_codes.append((peer["name"], corp_code))
        for year in years:
            try:
                with prog.step(f"{peer['name']} FY{year}") as st:
                    rows, fs_div = c.fetch_financials(corp_code, year, ticker)
                    st["note"] = f"({fs_div}, {len(rows)}행)" if rows else ""
                    if not rows:
                        st["status"] = "데이터 없음"
            except FetchError as e:  # 타임아웃 포함: 해당 회사·연도만 건너뛰고 계속
                errors.append(mask_secrets(f"{peer['name']} FY{year}: {e}"))
                continue
            if not rows:
                errors.append(f"{peer['name']} FY{year}: 사업보고서 재무제표 없음 (TODO(data))")
                continue
            metrics, debt_detail, flags = extract_dart_metrics(rows, dcfg)
            fin_rows.append({
                "company": peer["name"], "ticker": ticker, "corp_code": corp_code,
                "fiscal_year": f"FY{year}A", "fs_div": fs_div, "rcept_no": rows[0].get("rcept_no"),
                "currency": "KRW", "unit": "억원", **metrics, "flags": ";".join(flags),
            })
            debt_rows += [{"company": peer["name"], "ticker": ticker, "fiscal_year": f"FY{year}A", **d}
                          for d in debt_detail]

    processed = resolve_path(cfg["paths"]["processed"])
    if fin_rows:
        save_processed(processed / "dart_financials.csv", pd.DataFrame(fin_rows),
                       sources=["Open DART fnlttSinglAcntAll"], as_of=as_of,
                       note="금액 KRW 억원, 사업보고서(11011) 당기 금액. 총차입금 정의는 config ASSUMPTION 참조.")
        save_processed(processed / "dart_debt_lines.csv", pd.DataFrame(debt_rows),
                       sources=["Open DART fnlttSinglAcntAll"], as_of=as_of, note="총차입금 구성 계정 (검산용)")
        outputs += [str(processed / "dart_financials.csv"), str(processed / "dart_debt_lines.csv")]

    if dcfg.get("filings", {}).get("enabled", False):
        out, notes = run_filings(c, cfg, as_of, peer_codes)
        outputs += out
        errors += notes
    else:
        logger.info("[dart] 발행공시 검색 비활성 (config dart.filings.enabled=false 또는 --skip-filings)")

    status = STATUS_SUCCESS if not errors else (STATUS_PARTIAL if fin_rows else STATUS_FAILED)
    return FetchResult(SOURCE, status, n_items=len(fin_rows), outputs=outputs, message="; ".join(errors))
