"""국내 IPO 희망공모가 할인율 실증 (로컬 실행 전용 — 클라우드 세션에서는 실행하지 않는다).

    python -m research.vol03.ipo_discounts --asof 2026-10-20               # 공시검색 + 원문 다운로드 + 추출
    python -m research.vol03.ipo_discounts --asof 2026-10-20 --max-docs 50

1) 공시검색: Open DART list.json(발행공시 C, 증권신고서(지분증권) C001), config research.vol03.ipo_discounts 기간을
   3개월 창으로 나눠 반복(기존 DartClient.search_filings) → 신고 시점 비상장(corp_cls E)·스팩/리츠 제외 → 회사별 최신 신고서
2) 원문: document.xml(zip, 기존 DartClient.download_document). 이미 받은 zip(data/raw/large/dart/documents)은 다시 받지 않는다
3) 추출: 주당 평가가액, 희망공모가 밴드, 할인율 하단·상단, 적용 배수 종류(PER·EV/EBITDA 등), 상장 시장
   → data/processed/vol03_ipo_discounts.csv (+ .meta.json). 추출 신뢰도(high·medium·low)와 수동 확인 필요 플래그
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
           "discount_low", "discount_high", "discount_implied_low", "discount_implied_high", "multiples", "confidence", "needs_review", "notes"]
TOL_PP = 0.015          # 본문 할인율 vs (1 − 밴드 ÷ 평가가액) 허용 차이 (1.5%p)

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
    if not out["market"]:
        notes.append("상장 시장 미검출")
    if not out["multiples"]:
        notes.append("적용 배수 미검출")
    out["needs_review"] = out["confidence"] != "high"
    out["notes"] = "; ".join(notes)
    return out


def pick_filings(df: pd.DataFrame, icfg: Mapping) -> pd.DataFrame:
    """공시검색 결과 → 신규 상장 후보(corp_cls)·제외 이름 필터 → 회사별 최신 신고서(정정 반영)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["corp_code", "corp_name", "rcept_no", "rcept_dt", "report_nm"])
    d = df.copy()
    if icfg.get("corp_cls") and "corp_cls" in d:
        d = d[d["corp_cls"].isin(icfg["corp_cls"])]
    pat = "|".join(re.escape(x) for x in icfg.get("exclude_name_patterns", []))
    if pat:
        d = d[~d["corp_name"].str.contains(pat, na=False)]
    keys = icfg.get("report_nm_contains") or []
    if keys:
        d = d[d["report_nm"].str.contains("|".join(re.escape(k) for k in keys), na=False)]
    d = d.sort_values(["corp_code", "rcept_dt", "rcept_no"])
    return d.groupby("corp_code", as_index=False).tail(1).sort_values("rcept_dt").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 실행 (로컬)
# ---------------------------------------------------------------------------
def filings_cfg(cfg: Mapping) -> dict:
    """기존 DartClient.search_filings가 읽는 data_fetch.dart.filings를 Vol.3 기간·필터로 덮은 cfg 사본."""
    c = copy.deepcopy(dict(cfg))
    icfg = cfg["research"]["vol03"]["ipo_discounts"]
    c["data_fetch"]["dart"]["filings"].update(pblntf_ty=icfg["pblntf_ty"], pblntf_detail_ty=icfg["pblntf_detail_ty"],
                                              report_nm_contains=icfg["report_nm_contains"])
    return c


def run(cfg: Mapping, as_of: str, *, client=None, max_docs: int | None = None) -> FetchResult:
    from src.data_fetch.dart import DartClient
    icfg = cfg["research"]["vol03"]["ipo_discounts"]
    c2 = filings_cfg(cfg)
    client = client or DartClient(c2, as_of)                      # DART_API_KEY 없으면 SkipSource
    end = min(str(icfg.get("end_de") or as_of.replace("-", "")), as_of.replace("-", ""))
    found, notes = client.search_filings(str(icfg["bgn_de"]), end, label="IPO")
    cand = pick_filings(found, icfg)
    limit = int(max_docs if max_docs is not None else icfg.get("max_documents", 400))
    if len(cand) > limit:
        notes.append(f"원문 상한 {limit}건 (후보 {len(cand)}건 중 최근 순)")
        cand = cand.tail(limit)
    markets = icfg.get("markets", {})
    rows = []
    prog = Progress("dart", "증권신고서 원문", len(cand))
    for _, r in cand.iterrows():
        rno = str(r["rcept_no"])
        try:
            with prog.step(f"{r['corp_name']} {rno}") as st:
                cached = client.large_dir / "documents" / f"{rno}.zip"
                path = cached if cached.exists() else client.download_document(rno)
                info = parse_prospectus(zip_text(Path(path).read_bytes()))
                st["note"] = f"({info['confidence']})"
        except (FetchError, zipfile.BadZipFile, OSError) as e:   # 원문 실패는 건너뛰고 기록
            notes.append(mask_secrets(f"{r['corp_name']} {rno}: {type(e).__name__}: {e}"))
            continue
        rows.append({"company": r["corp_name"], "corp_code": r["corp_code"], "rcept_dt": r["rcept_dt"], "rcept_no": rno,
                     "url": DART_VIEW.format(rcept_no=rno), "report_nm": r["report_nm"],
                     **info, "market": markets.get(info["market"], info["market"])})
    out = resolve_path(cfg["research"]["vol03"]["inputs"]["ipo_discounts"])
    if not rows:
        return FetchResult("vol03_ipo_discounts", STATUS_FAILED, message="; ".join(notes) or "추출 행 없음")
    df = pd.DataFrame(rows, columns=COLUMNS)
    save_processed(out, df, sources=["Open DART list.json · document.xml (증권신고서(지분증권))"], as_of=as_of,
                   note=f"{icfg['bgn_de']}~{end} 신규 상장 증권신고서. 할인율 = 1 − 희망공모가 ÷ 주당 평가가액(소수). "
                        "confidence high = 본문 할인율과 계산값 일치(±1.5%p), medium = 계산값만/불일치, low = 추출 실패. needs_review = high 아님")
    n_hi = int((df["confidence"] == "high").sum())
    status = STATUS_SUCCESS if not notes else STATUS_PARTIAL
    return FetchResult("vol03_ipo_discounts", status, n_items=len(df), outputs=[str(out)],
                       message=f"high {n_hi} · medium {int((df['confidence'] == 'medium').sum())} · low {int((df['confidence'] == 'low').sum())}; "
                               + "; ".join(notes[:10]))


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
