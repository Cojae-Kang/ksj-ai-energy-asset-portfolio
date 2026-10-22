"""국내 IPO 희망공모가 할인율 실증 (로컬 실행 전용 — 클라우드 세션에서는 실행하지 않는다).

    python -m research.vol03.ipo_discounts --asof 2026-10-20               # 공시검색 + 원문 다운로드 + 추출
    python -m research.vol03.ipo_discounts --asof 2026-10-20 --max-docs 50
    python -m research.vol03.ipo_discounts --asof 2026-10-20 --listing-dates   # KRX 종목기본정보 → 상장일 표만 만듦

1) 공시검색: Open DART list.json(발행공시 C, 증권신고서(지분증권) C001), config research.vol03.ipo_discounts 기간을
   월 단위 구간(window_months)으로 나눠 구간마다 total_page 끝까지 순회(기존 DartClient.search_filings, 상한 max_pages)
   → 스팩/리츠 제외 → IPO 여부는 '접수 시점' 기준으로 판정(DART corp_cls는 현재 상태라 필터로 쓰지 않음 — look-ahead bias):
     (b) 현재 stock_code가 있고 로컬 KRX 종목기본정보의 상장일 ≤ 접수일이면 원문 없이 제외(상장사 유상증자 등)
     (a) 원문에 희망공모가 밴드와 IPO 문구(수요예측·상장 예정 등)가 있어야 사용
   → 회사별로 접수 순서대로 원문을 열어 '희망공모가 밴드가 처음 나온 신고서' 1건만 사용
   (같은 회사의 이후 기재정정·발행조건확정은 기록만: data/processed/vol03_ipo_filings_log.csv)
2) 원문: document.xml(zip, 기존 DartClient.download_document). 이미 받은 zip(data/raw/large/dart/documents)은 다시 받지 않는다
3) 추출: 주당 평가가액, 희망공모가 밴드, 할인율 하단·상단, 적용 배수 종류(PER·EV/EBITDA 등), 상장 시장, 공모주식수·공모금액
   → data/processed/vol03_ipo_discounts.csv (+ .meta.json). 추출 신뢰도(high·medium·low), 이상치(할인율 > 50% 또는 < 10%)와
   수동 확인 필요 플래그. 구간별·시장별·공모금액 규모별 요약 → docs/qa/vol03_ipo_discounts.md
호출 간격·타임아웃·재시도·진행 로그는 data_fetch 공통 규칙(config data_fetch.http, dart.request_delay_sec). 파싱 실패는 건너뛰고 기록.
"""
from __future__ import annotations

import argparse
import copy
import html
import io
import logging
import re
import sys
import zipfile
from pathlib import Path
from typing import Mapping

import pandas as pd

from src.data_fetch.base import (FetchError, FetchResult, Progress, SkipSource, STATUS_FAILED, STATUS_PARTIAL, STATUS_SKIPPED,
                                 STATUS_SUCCESS, load_config, mask_secrets, resolve_path, save_processed, setup_logging, to_number)

logger = logging.getLogger("research.vol03.ipo_discounts")
DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
COLUMNS = ["company", "corp_code", "market", "rcept_dt", "rcept_no", "url", "report_nm", "value_per_share", "band_low", "band_high",
           "discount_low", "discount_high", "discount_implied_low", "discount_implied_high", "offer_shares", "offer_amount_low",
           "offer_amount_high", "multiples", "confidence", "outlier", "needs_review", "corp_cls_now", "list_dt", "pit_check", "notes"]
LOG_COLUMNS = ["window", "corp_name", "corp_code", "corp_cls", "stock_code", "list_dt", "rcept_dt", "rcept_no", "report_nm", "decision", "note"]
# 판정 사유 (로그 decision → 요약 표 문구). 순서 = 요약 표 순서
DECISIONS = {"used": "사용", "low_confidence": "추출 신뢰도 낮음", "after_first": "같은 회사 이후 신고서(기록만)",
             "listed_at_filing": "접수 시점 상장사(상장일 ≤ 접수일, 원문 없이 제외)", "not_ipo_text": "원문에 IPO 문구·밴드 없음(상장사 유상증자 등)",
             "after_not_ipo": "접수 시점 상장사로 판정된 회사의 이후 신고서", "no_band": "원문에서 밴드 미검출(IPO 문구는 있음)",
             "download_fail": "원문 다운로드·해석 실패", "skipped_limit": "원문 상한 초과", "excluded_report": "보고서명 불일치",
             "excluded_name": "스팩·리츠 등 제외 이름", "excluded_cls": "현재 corp_cls ≠ E로 제외(예전 방식, look-ahead bias)"}
LISTED_CLS = {"Y", "K", "N"}      # DART corp_cls: 유가증권·코스닥·코넥스 (현재 상태)
TOL_PP = 0.015          # 본문 할인율 vs (1 − 밴드 ÷ 평가가액) 허용 차이 (1.5%p)
OUTLIER_HIGH, OUTLIER_LOW = 0.50, 0.10   # config ipo_discounts.outlier_high/low로 덮어씀 (set_outlier_bounds)


def set_outlier_bounds(icfg: Mapping) -> None:
    global OUTLIER_HIGH, OUTLIER_LOW
    OUTLIER_HIGH, OUTLIER_LOW = float(icfg.get("outlier_high", OUTLIER_HIGH)), float(icfg.get("outlier_low", OUTLIER_LOW))

_DASH = r"[~∼～\-–—]"
RE_VALUE = [re.compile(r"주당\s*평가\s*가액[^\d]{0,40}?([\d,]{3,}(?:\.\d+)?)\s*원"),
            re.compile(r"(?:1주당|주당)\s*(?:희망)?\s*평가\s*가격[^\d]{0,40}?([\d,]{3,}(?:\.\d+)?)\s*원")]
RE_BAND = [re.compile(r"희망\s*공모\s*가(?:액)?\s*(?:밴드|범위)?[^\d]{0,40}?([\d,]{3,})\s*원?\s*" + _DASH + r"\s*([\d,]{3,})\s*원"),
           re.compile(r"공모\s*희망\s*가(?:액)?[^\d]{0,40}?([\d,]{3,})\s*원?\s*" + _DASH + r"\s*([\d,]{3,})\s*원")]
RE_DISC = [re.compile(r"할인율[^\d%]{0,40}?(\d{1,2}(?:\.\d+)?)\s*%\s*" + _DASH + r"\s*(\d{1,2}(?:\.\d+)?)\s*%")]
RE_MULT = {"PER": re.compile(r"(?<![A-Za-z])PER(?![A-Za-z])"), "EV/EBITDA": re.compile(r"EV\s*/\s*EBITDA"),
           "PSR": re.compile(r"(?<![A-Za-z])PSR(?![A-Za-z])"), "PBR": re.compile(r"(?<![A-Za-z])PBR(?![A-Za-z])"),
           "EV/Sales": re.compile(r"EV\s*/\s*Sales", re.I), "DCF": re.compile(r"(?<![A-Za-z])DCF(?![A-Za-z])")}
RE_MARKET = re.compile(r"(유가증권시장|코스닥시장)\s*(?:에\s*)?(?:신규\s*)?상장")
RE_SHARES = [re.compile(r"모집\s*(?:또는|및)?\s*매출\s*(?:할\s*)?증권의\s*(?:종류\s*및\s*)?수[^\d]{0,40}?([\d,]{4,})\s*주"),
             re.compile(r"공모\s*주식\s*수[^\d]{0,20}?([\d,]{4,})\s*주")]


# ---------------------------------------------------------------------------
# 순수 함수 (테스트 대상)
# ---------------------------------------------------------------------------
def _decode(b: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="ignore")


def to_text(markup: str) -> str:
    """XML/HTML 원문 → 공백 정리된 평문 (표 칸 사이는 공백 하나)."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def zip_text(content: bytes) -> str:
    """document.xml zip → 모든 xml/htm 파일의 평문을 이어 붙인 문자열."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        parts = [to_text(_decode(z.read(n))) for n in sorted(z.namelist()) if n.lower().endswith((".xml", ".htm", ".html"))]
    return " ".join(p for p in parts if p)


def _num(s: str) -> float:
    v = to_number(str(s).replace(",", ""))
    return float(v) if v == v else float("nan")


def _first(patterns: list[re.Pattern], text: str) -> re.Match | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m
    return None


def ipo_signals(text: str, keywords: list[str]) -> list[str]:
    """원문에서 찾은 IPO 문구 (config ipo_keywords 정규식 중 일치한 것)."""
    return [k for k in keywords if re.search(k, text)]


def parse_prospectus(text: str) -> dict:
    """평문 → 평가가액·밴드·할인율·적용 배수·시장 + 신뢰도.

    high   = 평가가액·밴드·본문 할인율이 모두 있고, 본문 할인율 ≈ 1 − 밴드 ÷ 평가가액 (±1.5%p)
    medium = 평가가액·밴드만 있음(할인율은 계산값) 또는 본문 할인율과 계산값이 어긋남(플래그)
    low    = 평가가액 또는 밴드를 못 찾음 → 분포에 쓰지 않음
    """
    out: dict = {"value_per_share": float("nan"), "band_low": float("nan"), "band_high": float("nan"), "discount_low": float("nan"),
                 "offer_shares": float("nan"), "offer_amount_low": float("nan"), "offer_amount_high": float("nan"), "outlier": False,
                 "discount_high": float("nan"), "discount_implied_low": float("nan"), "discount_implied_high": float("nan"),
                 "multiples": "", "market": "", "confidence": "low", "needs_review": True, "notes": ""}
    notes = []
    m = _first(RE_VALUE, text)
    if m:
        out["value_per_share"] = _num(m.group(1))
    m = _first(RE_BAND, text)
    if m:
        a, b = sorted((_num(m.group(1)), _num(m.group(2))))
        out["band_low"], out["band_high"] = a, b
    m = _first(RE_DISC, text)
    parsed = None
    if m:
        a, b = sorted((_num(m.group(1)) / 100, _num(m.group(2)) / 100))
        parsed = (a, b)
    counts = {k: len(p.findall(text)) for k, p in RE_MULT.items()}
    out["multiples"] = ";".join(k for k, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n >= 2)
    m = _first(RE_SHARES, text)
    out["offer_shares"] = _num(m.group(1)) if m else float("nan")
    mk = [x for x in RE_MARKET.findall(text)]
    if mk:
        out["market"] = max(set(mk), key=mk.count)
    v, lo, hi = out["value_per_share"], out["band_low"], out["band_high"]
    have_core = v == v and lo == lo and hi == hi and v > 0
    if have_core:
        if hi > v:
            notes.append("밴드 상단 > 평가가액(할증 또는 오인식)")
        out["discount_implied_low"], out["discount_implied_high"] = 1 - hi / v, 1 - lo / v
    if have_core and parsed:
        ok_ = abs(parsed[0] - out["discount_implied_low"]) <= TOL_PP and abs(parsed[1] - out["discount_implied_high"]) <= TOL_PP
        out["discount_low"], out["discount_high"] = parsed
        out["confidence"] = "high" if ok_ and not notes else "medium"
        if not ok_:
            notes.append("본문 할인율 ≠ 1 − 밴드 ÷ 평가가액")
    elif have_core:
        out["discount_low"], out["discount_high"] = out["discount_implied_low"], out["discount_implied_high"]
        out["confidence"] = "medium"
        notes.append("할인율 본문 미검출 → 밴드·평가가액으로 계산")
    else:
        notes.append("평가가액 또는 희망공모가 밴드 미검출")
        if parsed:
            out["discount_low"], out["discount_high"] = parsed
    if out["offer_shares"] == out["offer_shares"] and lo == lo:
        out["offer_amount_low"], out["offer_amount_high"] = out["offer_shares"] * lo / 1e8, out["offer_shares"] * hi / 1e8   # 억원
    else:
        notes.append("공모주식수 미검출 → 공모금액 없음")
    if not out["market"]:
        notes.append("상장 시장 미검출")
    if not out["multiples"]:
        notes.append("적용 배수 미검출")
    dl, dh = out["discount_low"], out["discount_high"]
    if (dh == dh and dh > OUTLIER_HIGH) or (dl == dl and dl < OUTLIER_LOW):
        out["outlier"] = True
        notes.append(f"할인율 {dl * 100:.1f}~{dh * 100:.1f}% — 범위({OUTLIER_LOW * 100:.0f}~{OUTLIER_HIGH * 100:.0f}%) 밖, 원문 확인 필요")
    out["needs_review"] = out["confidence"] != "high" or out["outlier"]
    out["notes"] = "; ".join(notes)
    out["_text"] = text            # run()에서 IPO 문구 판정에 사용 (CSV에는 쓰지 않음)
    return out


def pick_filings(df: pd.DataFrame, icfg: Mapping) -> tuple[pd.DataFrame, list[dict]]:
    """공시검색 결과 → 신규 상장 후보(corp_cls)·제외 이름 필터 → 회사·접수 순 정렬 (회사당 여러 신고서 유지).

    반환: (후보 DataFrame, 제외 기록). 회사별 사용 신고서는 run()에서 원문을 접수 순으로 열어 밴드가 처음 나온 1건으로 정한다.
    """
    cols = ["corp_code", "corp_name", "corp_cls", "stock_code", "rcept_no", "rcept_dt", "report_nm"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols), []
    d = df.copy()
    for c in cols:
        if c not in d:
            d[c] = ""
    log = []
    keys = icfg.get("report_nm_contains") or []
    if keys:
        bad = ~d["report_nm"].str.contains("|".join(re.escape(k) for k in keys), na=False)
        log += [_log(r, "excluded_report", "보고서명 불일치") for _, r in d[bad].iterrows()]
        d = d[~bad]
    if icfg.get("corp_cls_filter") and icfg.get("corp_cls"):     # 예전 방식 (현재 상태 기준 → look-ahead bias). 기본 꺼짐
        bad = ~d["corp_cls"].isin(icfg["corp_cls"])
        log += [_log(r, "excluded_cls", f"corp_cls {r['corp_cls']} (상장사 유상증자 등)") for _, r in d[bad].iterrows()]
        d = d[~bad]
    pat = "|".join(re.escape(x) for x in icfg.get("exclude_name_patterns", []))
    if pat:
        bad = d["corp_name"].str.contains(pat, na=False)
        log += [_log(r, "excluded_name", "스팩·리츠 등 제외 이름") for _, r in d[bad].iterrows()]
        d = d[~bad]
    d = d.drop_duplicates("rcept_no").sort_values(["corp_code", "rcept_dt", "rcept_no"]).reset_index(drop=True)
    return d[cols], log


def _log(r, decision: str, note: str = "", list_dt: str = "") -> dict:
    dt = str(r.get("rcept_dt", ""))
    return {"window": dt[:6], "corp_name": r.get("corp_name", ""), "corp_code": r.get("corp_code", ""), "corp_cls": r.get("corp_cls", ""),
            "stock_code": str(r.get("stock_code", "") or "").strip(), "list_dt": list_dt, "rcept_dt": dt, "rcept_no": str(r.get("rcept_no", "")),
            "report_nm": r.get("report_nm", ""), "decision": decision, "note": note}


# ---------------------------------------------------------------------------
# 접수 시점 판정 (b): 상장일
# ---------------------------------------------------------------------------
def _ymd8(x) -> str:
    s_ = re.sub(r"\D", "", str(x or ""))
    return s_[:8] if len(s_) >= 8 else ""


def listing_dates(cfg: Mapping) -> dict[str, str]:
    """단축코드(6자리) → 상장일(YYYYMMDD). 로컬 파일만 읽는다 (KRX 종목기본정보 raw → 처리본 → 수동 CSV 순으로 덮어씀)."""
    import json
    src = cfg["research"]["vol03"]["ipo_discounts"].get("listing_sources") or {}
    out: dict[str, str] = {}
    raw = resolve_path(cfg["paths"]["raw"]) / "krx"
    for g in src.get("krx_raw_globs", []):
        files = sorted(raw.glob(g)) if raw.exists() else []
        if not files:
            continue
        try:
            payload = json.loads(files[-1].read_text(encoding="utf-8"))          # 가장 최근 기준일 파일
        except (OSError, ValueError):
            continue
        for r in payload.get(cfg["data_fetch"]["krx"].get("response_block", "OutBlock_1"), []) or []:
            code, dt = str(r.get("ISU_SRT_CD", "")).strip(), _ymd8(r.get("LIST_DD"))
            if code and dt:
                out[code.zfill(6)] = dt
    for key in ("processed", "manual"):
        p_ = resolve_path(src[key]) if src.get(key) else None
        if p_ is not None and p_.exists():
            d = pd.read_csv(p_, dtype=str, comment=None).fillna("")
            for _, r in d.iterrows():
                code, dt = str(r.get("stock_code", "")).strip(), _ymd8(r.get("list_dt"))
                if code and dt:
                    out[code.zfill(6)] = dt
    return out


def listed_at_filing(stock_code: str, rcept_dt: str, dates: Mapping[str, str]) -> tuple[bool | None, str]:
    """접수 시점에 이미 상장사였나: True(상장일 ≤ 접수일) · False(상장일 > 접수일) · None(현재 비상장이거나 상장일 미확인)."""
    code = str(stock_code or "").strip()
    if not code:
        return None, ""
    dt = dates.get(code.zfill(6), "")
    if not dt:
        return None, ""
    return dt <= _ymd8(rcept_dt), dt


def size_bucket(amount: float, edges: list[float]) -> str:
    if amount != amount:
        return "미상"
    lo = 0
    for e in edges:
        if amount < e:
            return f"{lo:,.0f}~{e:,.0f}억" if lo else f"<{e:,.0f}억"
        lo = e
    return f"≥{lo:,.0f}억"


def breakdown(df: pd.DataFrame, log: pd.DataFrame | None, icfg: Mapping) -> str:
    """구간(월)별·시장별·공모금액 규모별 건수와 할인율 분위 (Markdown). 목표 표본 미달이면 사유."""
    from src.data_fetch.base import markdown_table
    d = df.copy()
    d["month"] = d["rcept_dt"].astype(str).str[:6]
    d["size"] = [size_bucket(x, list(icfg.get("size_buckets", [300, 1000]))) for x in d["offer_amount_low"]]

    def q(x: pd.Series) -> str:
        x = x.dropna()
        return "—" if x.empty else "/".join(f"{v * 100:.1f}" for v in x.quantile([0.25, 0.5, 0.75]))
    rows = lambda key: [{"구분": k, "n": len(g), "이상치": int(g["outlier"].astype(bool).sum()),  # noqa: E731
                         "할인율 하단 Q1/중앙/Q3 %": q(g["discount_low"]), "할인율 상단 Q1/중앙/Q3 %": q(g["discount_high"])}
                        for k, g in d.groupby(key)]
    fmt = lambda x: f"{x[:4]}-{x[4:6]}-{x[6:8]}" if len(str(x)) == 8 else str(x)  # noqa: E731
    dt = d["rcept_dt"].astype(str)
    L = [f"- 사용 {len(d)}건 · 실제 접수일 {fmt(dt.min()) if len(d) else '—'}~{fmt(dt.max()) if len(d) else '—'} "
         f"(검색 기간 {fmt(str(icfg['bgn_de']))}~{fmt(str(icfg['end_de']))})", ""]
    has_log = log is not None and not log.empty
    if has_log:
        log = log.fillna("").astype(str)
    months = pd.period_range(pd.Period(str(icfg["bgn_de"])[:6], "M"), pd.Period(str(icfg["end_de"])[:6], "M"), freq="M").strftime("%Y%m")
    by_m = d.groupby("month").size()
    found = log.groupby("window").size() if has_log else pd.Series(dtype=int)
    L += ["**구간(월)별**", "", markdown_table([{"월": m, "검색 결과(신고서)": int(found.get(m, 0)) if has_log else "—", "사용": int(by_m.get(m, 0))}
                                              for m in months]), ""]
    L += ["**시장별**", "", markdown_table(rows("market")), "", "**공모금액(밴드 하단 기준) 규모별**", "", markdown_table(rows("size")), ""]
    tgt = int(icfg.get("target_n", 40))
    if len(d) < tgt:
        why = []
        empty = [m for m in months if int(found.get(m, 0)) == 0] if has_log else []
        if not has_log:
            why.append("검색 로그(vol03_ipo_filings_log.csv) 없음 — 이전 버전(검색 결과 마지막 페이지만 반영)으로 만든 파일, 월 구간·전체 페이지 재수집 필요")
        if (d["size"] == "미상").all() and len(d):
            why.append("공모주식수 미추출(이전 버전 파일) — 규모별 분해·공모금액 기준 하위 표본은 재수집 후 채워짐")
        if empty:
            why.append(f"검색 결과가 없는 월 {len(empty)}개({empty[0]}~{empty[-1]} 중) — 해당 구간 공시검색 응답·오류 로그 확인")
        if log is not None and not log.empty:
            for k, lab in (("no_band", "원문에서 밴드 미검출"), ("download_fail", "원문 다운로드·해석 실패"),
                           ("excluded_cls", "현재 corp_cls ≠ E(접수 시점 판정 전 방식 — look-ahead bias)"),
                           ("excluded_name", "스팩·리츠 등"), ("low_confidence", "추출 신뢰도 낮음"), ("skipped_limit", "원문 상한 초과")):
                n = int((log["decision"] == k).sum())
                if n:
                    why.append(f"{lab} {n}건")
        L += [f"**목표 표본 {tgt}건 미달 ({len(d)}건)**: " + ("; ".join(why) or "사유 불명 — 로그 확인"), ""]
    L += pit_summary(d, log)
    return "\n".join(L)


def pit_summary(d: pd.DataFrame, log: pd.DataFrame | None) -> list[str]:
    """접수 시점 판정 요약: 복원 건수(현재 상장사지만 접수 때 비상장) + 판정 사유별 건수 (Markdown 줄 목록)."""
    from src.data_fetch.base import markdown_table
    now = d["corp_cls_now"].astype(str) if "corp_cls_now" in d else pd.Series([""] * len(d), index=d.index)
    restored = int(now.isin(LISTED_CLS).sum())
    L = ["**접수 시점 판정 (look-ahead bias 제거)**", "",
         f"- 시점 기준 판정으로 복원된 건수: {restored}건 (현재 corp_cls Y·K·N이지만 접수 시점엔 비상장 — 예전 corp_cls 필터라면 제외됐을 표본)"
         + ("" if "corp_cls_now" in d else " — 이전 버전 파일(corp_cls_now 없음), 재수집 후 집계"), ""]
    if log is not None and not log.empty:
        log = log.fillna("").astype(str)
        cnt = log["decision"].value_counts()
        rows = [{"판정": k, "설명": v, "신고서": int(cnt.get(k, 0)), "회사": int(log[log["decision"] == k]["corp_code"].nunique())}
                for k, v in DECISIONS.items() if cnt.get(k, 0)]
        rows += [{"판정": k, "설명": "(미정의)", "신고서": int(n), "회사": int(log[log["decision"] == k]["corp_code"].nunique())}
                 for k, n in cnt.items() if k not in DECISIONS]
        L += ["**판정 사유별 건수**", "", markdown_table(rows), ""]
    return L


def estimate_from_log(log: pd.DataFrame, icfg: Mapping) -> dict:
    """예전 corp_cls 필터로 제외된 신고서(excluded_cls) 중 실제 IPO 신고서 추정 — 로그만 사용 (원문·API 없음).

    방법: 회사별 '최초 신고서'(접두어 없는 증권신고서) = 공모 1건의 시작. 현재 corp_cls가 E로 남은 최근 구간(아직 상장 전)에서
    상장사(Y·K)의 최초 신고서 비율 = 상장사 유상증자 발생률로 보고, 그 발생률 × 개월 수를 제외분에서 뺀다.
    포아송 90% 구간으로 범위를 준다. 원문 판정 전의 1차 추정치.
    """
    from scipy import stats
    d = log.fillna("").astype(str)                       # 숫자로 읽힌 window·rcept_dt도 문자열로
    pat = "|".join(re.escape(x) for x in icfg.get("exclude_name_patterns", []))
    d["spac"] = d["corp_name"].str.contains(pat, na=False) if pat else False
    d["init"] = d["report_nm"].str.replace(r"\[정정제출요구\]", "", regex=True).str.match(r"\s*증권신고서")
    x = d[d["decision"] == "excluded_cls"]
    ns = x[~x["spac"]]
    has_init = ns.groupby("corp_code")["init"].any()
    init = d[d["init"] & ~d["spac"]]
    # 최근 구간: 최초 신고서가 대부분 E(상장 전)인 마지막 달들 → 그 구간 Y·K 최초 신고서 = 상장사 유상증자 발생률 (상한)
    by = pd.crosstab(init["window"], init["corp_cls"].isin(LISTED_CLS))
    by.columns = ["unlisted" if not c else "listed" for c in by.columns]
    for c in ("unlisted", "listed"):
        if c not in by:
            by[c] = 0
    tail = []
    for m in reversed(list(by.index)):                    # 끝에서부터 연속으로 E 우위인 달
        if by.loc[m, "unlisted"] > by.loc[m, "listed"]:
            tail.append(m)
        else:
            break
    tail = sorted(tail)
    end_day = int(str(icfg.get("end_de", "20261031"))[6:8] or 31)
    months_tail = max(len(tail) - 1 + min(end_day, 30) / 30, 0.5) if tail else 0
    k = int(by.loc[tail, "listed"].sum()) if tail else 0
    base_months = sorted(set(x["window"]) - set(tail))
    n_m = len(base_months)
    lo_r = stats.chi2.ppf(0.05, 2 * k) / 2 / months_tail if k and months_tail else 0.0
    hi_r = stats.chi2.ppf(0.95, 2 * (k + 1)) / 2 / months_tail if months_tail else float("nan")
    rate = k / months_tail if months_tail else float("nan")
    ep = int(ns[ns["init"] & ns["window"].isin(base_months)]["corp_code"].nunique())     # 제외된 비스팩 회사 중 최초 신고서가 있는 회사
    est = lambda r: max(ep - r * n_m, 0)  # noqa: E731
    return {"rows": len(x), "companies": int(x["corp_code"].nunique()), "spac_rows": int(x["spac"].sum()),
            "spac_companies": int(x[x["spac"]]["corp_code"].nunique()), "ns_rows": len(ns), "ns_companies": int(ns["corp_code"].nunique()),
            "ns_with_init": int(has_init.sum()), "ns_amend_only": int((~has_init).sum()), "tail_months": tail, "tail_listed_inits": k,
            "rate": float(rate), "rate_lo": float(lo_r), "rate_hi": float(hi_r), "base_months": n_m, "base_init_companies": ep,
            "ipo_est": float(est(rate)), "ipo_lo": float(est(hi_r)), "ipo_hi": float(est(lo_r)),
            "monthly": by.reset_index().rename(columns={"index": "window"}).to_dict("records")}


def estimate_markdown(e: Mapping) -> str:
    from src.data_fetch.base import markdown_table
    t = ", ".join(e["tail_months"]) or "—"
    L = ["# Vol.3 IPO 표본 — corp_cls 필터 제외분 중 실제 IPO 신고서 추정 (로그 기준, 원문 판정 전)", "",
         f"- 예전 필터(현재 corp_cls ≠ E)로 제외: 신고서 {e['rows']:,}건 · {e['companies']}개사",
         f"  - 스팩·리츠 등 이름: {e['spac_rows']}건 · {e['spac_companies']}개사 (IPO지만 이름 규칙으로 어차피 제외)",
         f"  - 그 외 {e['ns_rows']:,}건 · {e['ns_companies']}개사 = 최초 신고서가 검색 기간 안에 있는 {e['ns_with_init']}개사"
         f" + 정정·확정·첨부만 있는 {e['ns_amend_only']}개사(최초 신고서가 기간 이전 등)",
         f"- 상장사 유상증자 발생률: 최초 신고서가 대부분 아직 상장 전(E)인 최근 구간({t})의 상장사 최초 신고서 {e['tail_listed_inits']}건 "
         f"→ 월 {e['rate']:.1f}건 (포아송 90% 구간 {e['rate_lo']:.1f}~{e['rate_hi']:.1f})",
         f"- **추정: 제외된 비스팩 {e['base_init_companies']}개사(최초 신고서 기준, {e['base_months']}개월) 중 IPO 약 {e['ipo_est']:.0f}개사 "
         f"(범위 {e['ipo_lo']:.0f}~{e['ipo_hi']:.0f})** — 나머지는 상장사 유상증자 추정",
         "- 한계: 최근 구간 표본이 작아 범위가 넓다. 확정은 접수 시점 판정(상장일 > 접수일 · 원문 IPO 문구) 재수집으로", "",
         "## 월별 최초 신고서 (스팩·리츠 제외, 현재 corp_cls 기준)", "",
         markdown_table([{"월": r["window"], "현재 비상장(E)": int(r["unlisted"]), "현재 상장(Y·K·N)": int(r["listed"])} for r in e["monthly"]])]
    return "\n".join(L) + "\n"


def fetch_listing_dates(cfg: Mapping, as_of: str, *, client=None) -> FetchResult:
    """KRX 종목기본정보(유가증권·코스닥) → 단축코드·상장일 표 (로컬 실행, KRX_API_KEY 필요)."""
    from datetime import date, timedelta

    from src.data_fetch.krx import KrxOpenApiClient
    icfg = cfg["research"]["vol03"]["ipo_discounts"]
    client = client or KrxOpenApiClient(cfg, as_of)               # 키 없으면 SkipSource
    d0 = date.fromisoformat(as_of)
    rows, notes = [], []
    for name in icfg.get("listing_endpoints", ["base_info"]):
        got = []
        for i in range(int(cfg["data_fetch"]["krx"].get("max_lookback_days", 10)) + 1):   # 휴장일이면 직전 영업일
            bas = (d0 - timedelta(days=i)).strftime("%Y%m%d")
            try:
                with Progress("krx", f"종목기본정보 {name}", None).step(bas) as st:
                    got = client.fetch(name, bas)
                    st["note"] = f"({len(got)}종목)"
            except FetchError as e:
                notes.append(mask_secrets(f"{name}: {e}"))
                break
            if got:
                break
        rows += [{"stock_code": str(r.get("ISU_SRT_CD", "")).strip().zfill(6), "company": r.get("ISU_ABBRV") or r.get("ISU_NM", ""),
                  "market": r.get("MKT_TP_NM", ""), "list_dt": _ymd8(r.get("LIST_DD")), "source": f"KRX Open API {name}"} for r in got]
    out = resolve_path(icfg["listing_sources"]["processed"])
    if not rows:
        return FetchResult("vol03_listing_dates", STATUS_FAILED, message="; ".join(notes) or "응답 없음")
    df = pd.DataFrame(rows).drop_duplicates("stock_code")
    save_processed(out, df, sources=["KRX Open API 종목기본정보 (LIST_DD)"], as_of=as_of, note="IPO 접수 시점 판정용 상장일 (상장일 > 접수일 → 접수 시점 비상장)")
    return FetchResult("vol03_listing_dates", STATUS_PARTIAL if notes else STATUS_SUCCESS, n_items=len(df), outputs=[str(out)], message="; ".join(notes))


# ---------------------------------------------------------------------------
# 실행 (로컬)
# ---------------------------------------------------------------------------
def filings_cfg(cfg: Mapping) -> dict:
    """기존 DartClient.search_filings가 읽는 data_fetch.dart.filings를 Vol.3 기간·필터로 덮은 cfg 사본."""
    c = copy.deepcopy(dict(cfg))
    icfg = cfg["research"]["vol03"]["ipo_discounts"]
    c["data_fetch"]["dart"]["filings"].update(pblntf_ty=icfg["pblntf_ty"], pblntf_detail_ty=icfg["pblntf_detail_ty"],
                                              report_nm_contains=icfg["report_nm_contains"],
                                              window_months=int(icfg.get("window_months", 1)), max_pages=int(icfg.get("max_pages", 100)),
                                              page_count=int(icfg.get("page_count", 100)))
    return c


def run(cfg: Mapping, as_of: str, *, client=None, max_docs: int | None = None) -> FetchResult:
    from src.data_fetch.dart import DartClient
    icfg = cfg["research"]["vol03"]["ipo_discounts"]
    set_outlier_bounds(icfg)
    c2 = filings_cfg(cfg)
    client = client or DartClient(c2, as_of)                      # DART_API_KEY 없으면 SkipSource
    end = min(str(icfg.get("end_de") or as_of.replace("-", "")), as_of.replace("-", ""))
    found, notes = client.search_filings(str(icfg["bgn_de"]), end, label="IPO")
    cand, log = pick_filings(found, icfg)
    if found is not None and not found.empty:
        logger.info("공시검색 %d건 → 신규 상장 후보 %d건 (%d개사)", len(found), len(cand), cand["corp_code"].nunique())
    limit = int(max_docs if max_docs is not None else icfg.get("max_documents", 3000))
    markets = icfg.get("markets", {})
    use = set(icfg.get("use_confidence", ["high", "medium"]))
    kws, kmin = list(icfg.get("ipo_keywords", [])), int(icfg.get("ipo_min_keywords", 2))
    dates = listing_dates(cfg)
    logger.info("상장일 표 %d종목 (로컬 KRX 종목기본정보·처리본·수동 CSV) — 없으면 원문 문구로만 판정", len(dates))
    rows, n_docs, n_cache = [], 0, 0
    groups = sorted(cand.groupby("corp_code", sort=False), key=lambda kv: (str(kv[1]["rcept_dt"].min()), kv[0]))
    months = sorted({str(g["rcept_dt"].min())[:6] for _, g in groups})
    prog = Progress("dart", "증권신고서 원문", len(groups))
    cur, mstat = None, {}

    def month_done(m: str) -> None:
        st_ = mstat.get(m)
        if st_:
            logger.info("[IPO] %s 완료 (%d/%d개월): 회사 %d · 새 원문 %d · 캐시 %d · 사용 %d · 접수 시점 상장사 제외 %d",
                        m, months.index(m) + 1, len(months), st_["corp"], st_["new"], st_["cache"], st_["used"], st_["listed"])
    for code, g in groups:
        m = str(g["rcept_dt"].min())[:6]
        if m != cur:
            if cur is not None:
                month_done(cur)
            cur = m
        ms = mstat.setdefault(m, {"corp": 0, "new": 0, "cache": 0, "used": 0, "listed": 0})
        ms["corp"] += 1
        chosen, listed_co = None, False
        for _, r in g.iterrows():                                  # 접수 순: 밴드가 처음 나온 신고서 1건
            rno = str(r["rcept_no"])
            if chosen is not None:
                log.append(_log(r, "after_first", f"같은 회사 {chosen} 이후 신고서(기록만)"))
                continue
            if listed_co:
                log.append(_log(r, "after_not_ipo", "앞선 신고서에서 접수 시점 상장사로 판정"))
                continue
            was_listed, ldt = listed_at_filing(r.get("stock_code", ""), r["rcept_dt"], dates)
            if was_listed:                                         # (b) 상장일 ≤ 접수일 → 원문 없이 제외
                log.append(_log(r, "listed_at_filing", f"상장일 {ldt} ≤ 접수일 {r['rcept_dt']}", ldt))
                ms["listed"] += 1
                continue
            cached = client.large_dir / "documents" / f"{rno}.zip"
            if not cached.exists() and n_docs >= limit:
                log.append(_log(r, "skipped_limit", f"새 원문 상한 {limit}건", ldt))
                continue
            try:
                with prog.step(f"{m} {r['corp_name']} {rno}") as st:
                    hit = cached.exists()
                    path = cached if hit else client.download_document(rno)
                    n_docs += 0 if hit else 1
                    n_cache += 1 if hit else 0
                    ms["cache" if hit else "new"] += 1
                    info = parse_prospectus(zip_text(Path(path).read_bytes()))
                    st["note"] = f"({info['confidence']}{', 캐시' if hit else ''})"
            except (FetchError, zipfile.BadZipFile, OSError) as e:   # 원문 실패는 건너뛰고 기록
                notes.append(mask_secrets(f"{r['corp_name']} {rno}: {type(e).__name__}: {e}"))
                log.append(_log(r, "download_fail", f"{type(e).__name__}", ldt))
                continue
            sig = ipo_signals(info.pop("_text"), kws)
            has_band = info["band_low"] == info["band_low"]
            if len(sig) < kmin:                                    # (a) IPO 문구 부족 → 접수 시점 상장사 유상증자 등
                log.append(_log(r, "not_ipo_text", f"IPO 문구 {len(sig)}개({', '.join(sig) or '없음'}) < {kmin}" + ("" if has_band else " · 밴드 없음"), ldt))
                if not has_band:
                    listed_co = str(r.get("corp_cls", "")) in LISTED_CLS   # 현재 상장사 → 이후 신고서도 IPO일 수 없음
                continue
            if not has_band:
                log.append(_log(r, "no_band", info["notes"], ldt))
                continue
            chosen = rno
            now = str(r.get("corp_cls", ""))
            pit = (f"상장일 {ldt} > 접수일" if ldt else "원문 IPO 문구(상장일 미확인)") + (f" · 현재 {now} → 시점 기준 복원" if now in LISTED_CLS else "")
            log.append(_log(r, "used" if info["confidence"] in use else "low_confidence", (info["notes"] + "; " if info["notes"] else "") + pit, ldt))
            ms["used"] += info["confidence"] in use
            rows.append({"company": r["corp_name"], "corp_code": r["corp_code"], "rcept_dt": r["rcept_dt"], "rcept_no": rno,
                         "url": DART_VIEW.format(rcept_no=rno), "report_nm": r["report_nm"],
                         **info, "market": markets.get(info["market"], info["market"]), "corp_cls_now": now, "list_dt": ldt, "pit_check": pit})
    if cur is not None:
        month_done(cur)
    logger.info("원문 새로 받음 %d · 캐시 재사용 %d", n_docs, n_cache)
    out = resolve_path(cfg["research"]["vol03"]["inputs"]["ipo_discounts"])
    lg = pd.DataFrame(log, columns=LOG_COLUMNS)
    save_processed(resolve_path(cfg["research"]["vol03"]["inputs"]["ipo_log"]), lg, sources=["Open DART list.json"], as_of=as_of,
                   note="신고서별 처리(접수 시점 판정): " + " · ".join(f"{k}={v}" for k, v in DECISIONS.items()))
    if not rows:
        return FetchResult("vol03_ipo_discounts", STATUS_FAILED, message="; ".join(notes) or "추출 행 없음")
    df = pd.DataFrame(rows, columns=COLUMNS)
    save_processed(out, df, sources=["Open DART list.json · document.xml (증권신고서(지분증권))"], as_of=as_of,
                   note=f"{icfg['bgn_de']}~{end} 검색(월 구간·전체 페이지). IPO 여부는 접수 시점 기준(상장일 > 접수일 또는 원문 IPO 문구, 현재 corp_cls 미사용). "
                        "회사별 희망공모가 밴드가 처음 나온 신고서 1건. "
                        "할인율 = 1 − 희망공모가 ÷ 주당 평가가액(소수). 공모금액 = 공모주식수 × 밴드(억원). "
                        "confidence high = 본문 할인율과 계산값 일치(±1.5%p), medium = 계산값만/불일치, low = 추출 실패. "
                        f"outlier = 할인율 상단 > {OUTLIER_HIGH:.0%} 또는 하단 < {OUTLIER_LOW:.0%} (원문 확인 필요, 분포에는 유지)")
    qa = resolve_path(icfg.get("qa_report", "docs/qa/vol03_ipo_discounts.md"))
    qa.parent.mkdir(parents=True, exist_ok=True)
    qa.write_text("# Vol.3 국내 IPO 할인율 실증 — 표본 요약\n\n" + breakdown(df[df["confidence"].isin(use)], lg, {**icfg, "end_de": end}) + "\n",
                  encoding="utf-8")
    n_hi = int((df["confidence"] == "high").sum())
    status = STATUS_SUCCESS if not notes else STATUS_PARTIAL
    return FetchResult("vol03_ipo_discounts", status, n_items=len(df), outputs=[str(out), str(qa)],
                       message=f"high {n_hi} · medium {int((df['confidence'] == 'medium').sum())} · low {int((df['confidence'] == 'low').sum())} · "
                               f"이상치 {int(df['outlier'].sum())}; " + "; ".join(notes[:10]))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Vol.3 국내 IPO 할인율 실증 (로컬 실행, DART)")
    p.add_argument("--asof", default=None)
    p.add_argument("--max-docs", type=int, default=None)
    p.add_argument("--config", default=None)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--listing-dates", action="store_true", help="KRX 종목기본정보 → 상장일 표만 만든다 (KRX_API_KEY)")
    g.add_argument("--estimate-log", action="store_true", help="기존 로그로 corp_cls 제외분 중 IPO 추정 (네트워크 없음)")
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    as_of = args.asof or cfg["research"]["vol03"]["as_of"]
    icfg = cfg["research"]["vol03"]["ipo_discounts"]
    if args.estimate_log:
        lp = resolve_path(cfg["research"]["vol03"]["inputs"]["ipo_log"])
        if not lp.exists():
            print(f"로그 없음: {lp}")
            return 1
        md = estimate_markdown(estimate_from_log(pd.read_csv(lp, dtype=str), icfg))
        qa = resolve_path(icfg.get("estimate_report", "docs/qa/vol03_ipo_pit_estimate.md"))
        qa.parent.mkdir(parents=True, exist_ok=True)
        qa.write_text(md, encoding="utf-8")
        print(md)
        return 0
    try:
        r = fetch_listing_dates(cfg, as_of) if args.listing_dates else run(cfg, as_of, max_docs=args.max_docs)
    except SkipSource as e:
        r = FetchResult("vol03_ipo_discounts", STATUS_SKIPPED, message=str(e))
    except Exception as e:  # noqa: BLE001
        r = FetchResult("vol03_ipo_discounts", STATUS_FAILED, message=mask_secrets(f"{type(e).__name__}: {e}"))
    print(f"\n=== Vol.3 IPO 할인율 실증 ===\n{r.source:<20} {r.status:<8} {r.n_items:>4}  {r.message}")
    return 1 if r.status == STATUS_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
