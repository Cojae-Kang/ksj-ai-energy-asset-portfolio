"""국내 IPO 희망공모가 할인율 실증 (로컬 실행 전용 — 클라우드 세션에서는 실행하지 않는다).

    python -m research.vol03.ipo_discounts --asof 2026-10-20               # 공시검색 + 원문 다운로드 + 추출
    python -m research.vol03.ipo_discounts --asof 2026-10-20 --max-docs 50

1) 공시검색: Open DART list.json(발행공시 C, 증권신고서(지분증권) C001), config research.vol03.ipo_discounts 기간을
   월 단위 구간(window_months)으로 나눠 구간마다 total_page 끝까지 순회(기존 DartClient.search_filings, 상한 max_pages)
   → 신고 시점 비상장(corp_cls E)·스팩/리츠 제외 → 회사별로 접수 순서대로 원문을 열어 '희망공모가 밴드가 처음 나온 신고서' 1건만 사용
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
           "offer_amount_high", "multiples", "confidence", "outlier", "needs_review", "notes"]
LOG_COLUMNS = ["window", "corp_name", "corp_code", "corp_cls", "rcept_dt", "rcept_no", "report_nm", "decision", "note"]
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
    return out


def pick_filings(df: pd.DataFrame, icfg: Mapping) -> tuple[pd.DataFrame, list[dict]]:
    """공시검색 결과 → 신규 상장 후보(corp_cls)·제외 이름 필터 → 회사·접수 순 정렬 (회사당 여러 신고서 유지).

    반환: (후보 DataFrame, 제외 기록). 회사별 사용 신고서는 run()에서 원문을 접수 순으로 열어 밴드가 처음 나온 1건으로 정한다.
    """
    cols = ["corp_code", "corp_name", "corp_cls", "rcept_no", "rcept_dt", "report_nm"]
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
    if icfg.get("corp_cls"):
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


def _log(r, decision: str, note: str = "") -> dict:
    dt = str(r.get("rcept_dt", ""))
    return {"window": dt[:6], "corp_name": r.get("corp_name", ""), "corp_code": r.get("corp_code", ""), "corp_cls": r.get("corp_cls", ""),
            "rcept_dt": dt, "rcept_no": str(r.get("rcept_no", "")), "report_nm": r.get("report_nm", ""), "decision": decision, "note": note}


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
            for k, lab in (("no_band", "원문에서 밴드 미검출"), ("download_fail", "원문 다운로드·해석 실패"), ("excluded_cls", "상장사(corp_cls ≠ E)"),
                           ("excluded_name", "스팩·리츠 등"), ("low_confidence", "추출 신뢰도 낮음")):
                n = int((log["decision"] == k).sum())
                if n:
                    why.append(f"{lab} {n}건")
        L += [f"**목표 표본 {tgt}건 미달 ({len(d)}건)**: " + ("; ".join(why) or "사유 불명 — 로그 확인"), ""]
    return "\n".join(L)


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
    limit = int(max_docs if max_docs is not None else icfg.get("max_documents", 400))
    markets = icfg.get("markets", {})
    use = set(icfg.get("use_confidence", ["high", "medium"]))
    rows, n_docs = [], 0
    groups = list(cand.groupby("corp_code", sort=False))
    prog = Progress("dart", "증권신고서 원문", len(groups))
    for _, g in groups:
        chosen = None
        for _, r in g.iterrows():                                  # 접수 순: 밴드가 처음 나온 신고서 1건
            rno = str(r["rcept_no"])
            if chosen is not None:
                log.append(_log(r, "after_first", f"같은 회사 {chosen} 이후 신고서(기록만)"))
                continue
            if n_docs >= limit:
                log.append(_log(r, "skipped_limit", f"원문 상한 {limit}건"))
                continue
            try:
                with prog.step(f"{r['corp_name']} {rno}") as st:
                    cached = client.large_dir / "documents" / f"{rno}.zip"
                    path = cached if cached.exists() else client.download_document(rno)
                    n_docs += 0 if cached.exists() else 1
                    info = parse_prospectus(zip_text(Path(path).read_bytes()))
                    st["note"] = f"({info['confidence']})"
            except (FetchError, zipfile.BadZipFile, OSError) as e:   # 원문 실패는 건너뛰고 기록
                notes.append(mask_secrets(f"{r['corp_name']} {rno}: {type(e).__name__}: {e}"))
                log.append(_log(r, "download_fail", f"{type(e).__name__}"))
                continue
            if info["band_low"] != info["band_low"]:
                log.append(_log(r, "no_band", info["notes"]))
                continue
            chosen = rno
            if info["confidence"] not in use:
                log.append(_log(r, "low_confidence", info["notes"]))
            else:
                log.append(_log(r, "used", info["notes"]))
            rows.append({"company": r["corp_name"], "corp_code": r["corp_code"], "rcept_dt": r["rcept_dt"], "rcept_no": rno,
                         "url": DART_VIEW.format(rcept_no=rno), "report_nm": r["report_nm"],
                         **info, "market": markets.get(info["market"], info["market"])})
    out = resolve_path(cfg["research"]["vol03"]["inputs"]["ipo_discounts"])
    lg = pd.DataFrame(log, columns=LOG_COLUMNS)
    save_processed(resolve_path(cfg["research"]["vol03"]["inputs"]["ipo_log"]), lg, sources=["Open DART list.json"], as_of=as_of,
                   note="신고서별 처리: used(사용) · after_first(같은 회사 이후 신고서, 기록만) · no_band · low_confidence · download_fail · excluded_*")
    if not rows:
        return FetchResult("vol03_ipo_discounts", STATUS_FAILED, message="; ".join(notes) or "추출 행 없음")
    df = pd.DataFrame(rows, columns=COLUMNS)
    save_processed(out, df, sources=["Open DART list.json · document.xml (증권신고서(지분증권))"], as_of=as_of,
                   note=f"{icfg['bgn_de']}~{end} 검색(월 구간·전체 페이지). 회사별 희망공모가 밴드가 처음 나온 신고서 1건. "
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
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    as_of = args.asof or cfg["research"]["vol03"]["as_of"]
    try:
        r = run(cfg, as_of, max_docs=args.max_docs)
    except SkipSource as e:
        r = FetchResult("vol03_ipo_discounts", STATUS_SKIPPED, message=str(e))
    except Exception as e:  # noqa: BLE001
        r = FetchResult("vol03_ipo_discounts", STATUS_FAILED, message=mask_secrets(f"{type(e).__name__}: {e}"))
    print(f"\n=== Vol.3 IPO 할인율 실증 ===\n{r.source:<20} {r.status:<8} {r.n_items:>4}  {r.message}")
    return 1 if r.status == STATUS_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
