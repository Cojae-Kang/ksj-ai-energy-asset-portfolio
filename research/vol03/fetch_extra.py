"""Vol.3 추가 수집 (로컬 실행 전용). Vol.1·Vol.2와 같은 src/data_fetch 인프라를 쓴다. 클라우드 세션에서는 실행하지 않는다.

    python -m research.vol03.fetch_extra --asof 2026-10-20               # market + sec + dart
    python -m research.vol03.fetch_extra --asof 2026-10-20 --only market

A) market: 미국 피어 종가(yfinance, 보조 소스) — 2023년 첫 거래일(start_2023)·기준일 직전 거래일(latest, KRX와 같은 규칙)
   + 각 시점 직전의 SEC 표지 발행주식수(dei:EntityCommonStockSharesOutstanding 이력) + yfinance 현재 주식수(교차 확인)
   → data/processed/vol03_global_market_points.csv
B) sec: companyfacts → FY2022A 지배순이익(보수 시나리오 분모) · FY2022A~FY2025A D&A → data/processed/vol03_peer_extra.csv (US)
C) dart: 사업보고서 현금흐름표 감가상각비·무형자산상각비(사용권자산 제외) FY2022A~FY2025A → vol03_peer_extra.csv (KR)
companyfacts는 data/raw/sec_manual/ 브라우저 다운로드 파일을 먼저 쓰고(403 환경), 없으면 SEC API(SEC_USER_AGENT).
키·라이브러리가 없으면 SKIPPED. 원자료(data/raw)는 커밋하지 않는다.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

import pandas as pd

from src.data_fetch.base import (FetchResult, SkipSource, STATUS_FAILED, STATUS_SKIPPED, STATUS_SUCCESS, load_config,
                                 mask_secrets, resolve_path, save_processed, setup_logging, to_number)
from src.data_fetch.market_global import _get
from src.data_fetch.sec import OfflineSecSource, _entries, cik10, first_available

logger = logging.getLogger("research.vol03.fetch_extra")
KRW_PER_100M = 1e8
USD_PER_MN = 1e6
EXTRA_COLUMNS = ["company", "ticker", "region", "fiscal_year", "metric", "value", "unit", "source", "detail"]


# ---------------------------------------------------------------------------
# 순수 함수 (테스트 대상)
# ---------------------------------------------------------------------------
def shares_on(facts: Mapping, date: str, taxonomy: str = "dei", tag: str = "EntityCommonStockSharesOutstanding") -> dict | None:
    """date 이전(포함) 가장 최근 표지 발행주식수. 같은 end·같은 공시의 복수 클래스는 합산."""
    entries = [e for e in _entries(facts, taxonomy, tag, "shares") if e.get("end", "") <= date]
    if not entries:
        return None
    last = max(e["end"] for e in entries)
    same = [e for e in entries if e["end"] == last]
    filed = max(e.get("filed", "") for e in same)
    vals = {(e.get("accn"), e.get("frame"), e["val"]) for e in same if e.get("filed", "") == filed}
    return {"shares": float(sum(v[2] for v in vals)), "end": last, "filed": filed}


def sec_extra_rows(company: str, ticker: str, facts: Mapping, scfg: Mapping, years: list[int], da_tags: list[str],
                   start_fy: int, source: str) -> list[dict]:
    """companyfacts → D&A(연도별) + 보수 시나리오 분모(start_fy 지배순이익) 행 (USD mn)."""
    kw = dict(forms=scfg["forms"], duration_days=tuple(scfg["flow_duration_days"]), cutoff_month=int(scfg["fy_label_cutoff_month"]))
    rows = []
    for fy in years:
        v = first_available(facts, da_tags, fy, kind="flow", **kw)
        if v is not None:
            rows.append({"company": company, "ticker": ticker, "region": "US", "fiscal_year": f"FY{fy}A", "metric": "da",
                         "value": v["val"] / USD_PER_MN, "unit": "USD mn", "source": source, "detail": f"{v['tag']} {v['end']} {v['accn']}"})
    ni = first_available(facts, scfg["metrics"]["net_income"], start_fy, kind="flow", **kw)
    if ni is not None:
        rows.append({"company": company, "ticker": ticker, "region": "US", "fiscal_year": f"FY{start_fy}A", "metric": "net_income",
                     "value": ni["val"] / USD_PER_MN, "unit": "USD mn", "source": source, "detail": f"{ni['tag']} {ni['end']} {ni['accn']}"})
    return rows


def dart_da(rows: list[dict], spec: Mapping) -> tuple[float, list[str]]:
    """DART 현금흐름표 행 → D&A (KRW 억원) = 이름 패턴 일치 합계(세부 행·제외 패턴 빼고). 없으면 nan."""
    norm = lambda s: re.sub(r"\s+", "", str(s or ""))  # noqa: E731
    inc = [re.compile(p) for p in spec["include_name_patterns"]]
    exc = [re.compile(p) for p in spec["exclude_name_patterns"]]
    hits = [r for r in rows if r.get("sj_div") in spec["sj_div"] and str(r.get("account_detail", "-") or "-").strip() in ("-", "")
            and any(p.search(norm(r.get("account_nm"))) for p in inc) and not any(p.search(norm(r.get("account_nm"))) for p in exc)]
    vals = [to_number(r.get("thstrm_amount")) for r in hits]
    vals = [v for v in vals if v == v]
    return (sum(vals) / KRW_PER_100M if vals else float("nan")), [str(r.get("account_nm")) for r in hits]


def first_trading_close(hist: pd.DataFrame, start: str, end: str, forward: bool) -> tuple[str, float] | None:
    """yfinance history → [start, end] 구간의 첫(forward) 또는 마지막 거래일 종가."""
    if hist is None or hist.empty:
        return None
    idx = pd.to_datetime(hist.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    h = hist.assign(_d=idx)
    h = h[(h["_d"] >= pd.Timestamp(start)) & (h["_d"] <= pd.Timestamp(end))]
    if h.empty:
        return None
    r = h.iloc[0] if forward else h.iloc[-1]
    return r["_d"].strftime("%Y-%m-%d"), float(r["Close"])


# ---------------------------------------------------------------------------
# companyfacts 원천 (오프라인 파일 우선)
# ---------------------------------------------------------------------------
def facts_loader(cfg: Mapping, as_of: str) -> Callable[[int], dict]:
    off = OfflineSecSource(cfg, as_of)
    client = None

    def load(cik: int) -> dict:
        nonlocal client
        if off.facts_path(cik).exists():
            return off.fetch_companyfacts(cik)
        if client is None:
            from src.data_fetch.sec import SecClient
            client = SecClient(cfg, as_of)               # SEC_USER_AGENT 없으면 SkipSource
        return client.fetch_companyfacts(cik)
    return load


def _ciks(cfg: Mapping) -> dict[str, int]:
    return {k.upper(): int(v) for k, v in (cfg["data_fetch"]["sec"].get("offline", {}).get("expected_ciks") or {}).items()}


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def fetch_market(cfg: Mapping, as_of: str, *, ticker_factory: Callable[[str], Any] | None = None,
                 load_facts: Callable[[int], dict] | None = None) -> FetchResult:
    v3 = cfg["research"]["vol03"]
    fx = v3["fetch_extra"]
    if ticker_factory is None:
        try:
            import yfinance as yf
        except ImportError as e:
            return FetchResult("vol03_market", STATUS_SKIPPED, message=f"yfinance 미설치: {e}")
        ticker_factory = yf.Ticker
    load_facts = load_facts or facts_loader(cfg, as_of)
    ciks = _ciks(cfg)
    s0 = fx["start_from"]
    s1 = (datetime.strptime(s0, "%Y-%m-%d") + timedelta(days=int(fx["max_forward_days"]))).strftime("%Y-%m-%d")
    l1 = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")      # 기준일 당일 제외 (KRX와 같은 규칙)
    l0 = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=int(fx["lookback_days"]))).strftime("%Y-%m-%d")
    rows, notes = [], []
    for p in cfg["peers"]["overseas"]:
        tk = p["ticker"].upper()
        if tk in [t.upper() for t in cfg["data_fetch"]["sec"].get("not_sec_registrants", [])]:
            notes.append(f"{tk}: SEC 비대상 → 수기 입력 양식")
            continue
        try:
            t = ticker_factory(tk)
            facts = load_facts(ciks[tk]) if tk in ciks else None
            for point, (a, b, fwd) in {"start_2023": (s0, s1, True), "latest": (l0, l1, False)}.items():
                end_excl = (datetime.strptime(b, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                hit = first_trading_close(t.history(start=a, end=end_excl, auto_adjust=False), a, b, fwd)
                if hit is None:
                    notes.append(f"{tk} {point}: {a}~{b} 거래 없음 (상장 전 가능성)")
                    continue
                sh = shares_on(facts, hit[0]) if facts is not None else None
                yf_sh = float(_get(t.fast_info, "shares") or float("nan")) if point == "latest" else float("nan")
                rows.append({"point": point, "date": hit[0], "company": p["name"], "ticker": tk, "close": hit[1], "currency": "USD",
                             "shares_sec": sh["shares"] if sh else float("nan"), "shares_sec_end": sh["end"] if sh else "",
                             "shares_yf": yf_sh, "mcap_usd_mn": hit[1] * sh["shares"] / USD_PER_MN if sh else float("nan"),
                             "source": "yfinance (close) + SEC dei (shares)"})
        except SkipSource as e:
            notes.append(f"{tk}: {e}")
        except Exception as e:  # noqa: BLE001 — 한 종목 실패는 기록 후 계속
            notes.append(mask_secrets(f"{tk}: {type(e).__name__}: {e}"))
    if not rows:
        return FetchResult("vol03_market", STATUS_FAILED, message="; ".join(notes) or "수집 행 없음")
    out = resolve_path(v3["inputs"]["market_points"])
    save_processed(out, pd.DataFrame(rows), sources=["yfinance (보조)", "SEC EDGAR dei:EntityCommonStockSharesOutstanding"], as_of=as_of,
                   note="종가 USD(yfinance, auto_adjust=False) × 그 날짜 이전 최근 SEC 표지 발행주식수 = 시총 USD mn. "
                        f"start_2023 = {s0} 이후 첫 거래일, latest = {as_of} 직전 거래일(기준일 당일 제외)")
    return FetchResult("vol03_market", STATUS_SUCCESS, n_items=len(rows), outputs=[str(out)], message="; ".join(notes))


def fetch_sec_extra(cfg: Mapping, as_of: str, *, load_facts: Callable[[int], dict] | None = None) -> list[dict]:
    v3 = cfg["research"]["vol03"]
    scfg = cfg["data_fetch"]["sec"]
    load_facts = load_facts or facts_loader(cfg, as_of)
    start_fy = int(v3["multiples"]["start_fy"][2:6])
    rows = []
    for p in cfg["peers"]["overseas"]:
        tk = p["ticker"].upper()
        cik = _ciks(cfg).get(tk)
        if cik is None:
            continue
        rows += sec_extra_rows(p["name"], tk, load_facts(cik), scfg, list(v3["fetch_extra"]["sec_fiscal_years"]),
                               list(v3["fetch_extra"]["sec_da_tags"]), start_fy, f"SEC EDGAR companyfacts CIK{cik10(cik)}")
    return rows


def fetch_dart_extra(cfg: Mapping, as_of: str, *, client=None) -> list[dict]:
    from src.data_fetch.dart import DartClient
    v3 = cfg["research"]["vol03"]
    client = client or DartClient(cfg, as_of)          # DART_API_KEY 없으면 SkipSource
    fin = pd.read_csv(resolve_path(v3["inputs"]["dart"][0]), dtype={"ticker": str, "corp_code": str}, encoding="utf-8-sig")
    codes = fin.drop_duplicates("ticker").set_index("ticker")["corp_code"].to_dict()
    rows = []
    for p in cfg["peers"]["domestic"]:
        t = str(p["ticker"]).zfill(6)
        if t not in codes:
            continue
        for fy in v3["fetch_extra"]["sec_fiscal_years"]:
            items, fs = client.fetch_financials(str(codes[t]).zfill(8), int(fy), t)
            da, names = dart_da(items, v3["fetch_extra"]["dart_da"])
            if da == da:
                rows.append({"company": p["name"], "ticker": t, "region": "KR", "fiscal_year": f"FY{fy}A", "metric": "da", "value": da,
                             "unit": "억원", "source": f"Open DART fnlttSinglAcntAll ({fs}, 11011)", "detail": " + ".join(names)})
    return rows


def write_extra(cfg: Mapping, as_of: str, rows: list[dict]) -> str:
    out = resolve_path(cfg["research"]["vol03"]["inputs"]["peer_extra"])
    old = pd.read_csv(out, dtype={"ticker": str}, encoding="utf-8-sig") if out.exists() else pd.DataFrame(columns=EXTRA_COLUMNS)
    frames = [x for x in (pd.DataFrame(rows, columns=EXTRA_COLUMNS), old) if not x.empty]   # 빈 DataFrame concat은 pandas FutureWarning
    df = (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=EXTRA_COLUMNS)).drop_duplicates(
        ["ticker", "fiscal_year", "metric"], keep="first")
    save_processed(out, df.sort_values(["region", "ticker", "fiscal_year", "metric"]).reset_index(drop=True),
                   sources=["SEC EDGAR companyfacts", "Open DART fnlttSinglAcntAll"], as_of=as_of,
                   note="da = 감가상각비 + 무형자산상각비(KR 억원, 사용권자산 제외) / DepreciationDepletionAndAmortization 등(US USD mn). "
                        "net_income = 보수 시나리오 분모(FY2022A, US)")
    return str(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Vol.3 추가 수집 (로컬 실행)")
    p.add_argument("--asof", default=None)
    p.add_argument("--only", choices=["market", "sec", "dart"], default=None)
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    as_of = args.asof or cfg["research"]["vol03"]["as_of"]
    results, extra = [], []
    steps = [args.only] if args.only else ["market", "sec", "dart"]
    for step in steps:
        try:
            if step == "market":
                results.append(fetch_market(cfg, as_of))
                continue
            rows = fetch_sec_extra(cfg, as_of) if step == "sec" else fetch_dart_extra(cfg, as_of)
            extra += rows
            results.append(FetchResult(f"vol03_{step}", STATUS_SUCCESS if rows else STATUS_FAILED, n_items=len(rows)))
        except SkipSource as e:
            results.append(FetchResult(f"vol03_{step}", STATUS_SKIPPED, message=str(e)))
        except Exception as e:  # noqa: BLE001
            results.append(FetchResult(f"vol03_{step}", STATUS_FAILED, message=mask_secrets(f"{type(e).__name__}: {e}")))
    if extra:
        results.append(FetchResult("vol03_extra", STATUS_SUCCESS, n_items=len(extra), outputs=[write_extra(cfg, as_of, extra)]))
    print("\n=== Vol.3 추가 수집 ===")
    for r in results:
        print(f"{r.source:<14} {r.status:<8} {r.n_items:>4}  {r.message}")
    return 1 if any(r.status == STATUS_FAILED for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
