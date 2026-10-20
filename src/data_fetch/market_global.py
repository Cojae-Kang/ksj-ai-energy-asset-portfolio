"""해외 peers 주가·시가총액 (yfinance, 보조 소스).

- 모든 행에 cross_check_required=True, source_priority=3 표시
- 발행주식수는 SEC dei:EntityCommonStockSharesOutstanding(공식)과 비교해 docs/qa/에 기록
- yfinance 발행주식수는 "현재" 값이다. 기준일 시가총액 = 기준일 종가 × 현재 주식수 (ASSUMPTION, 플래그)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

import pandas as pd

from .base import (FetchResult, Progress, STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS, markdown_table,
                   mask_secrets, resolve_path, save_processed, save_raw, utc_now_iso)

logger = logging.getLogger("data_fetch.global")

SOURCE = "global"
LIB_LABEL = "yfinance (Yahoo Finance 비공식 래퍼)"


def _default_ticker_factory(symbol: str):
    import yfinance as yf

    return yf.Ticker(symbol)


def _get(obj: Any, key: str):
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, None)


def fetch_quote(symbol: str, as_of: str, lookback_days: int,
                ticker_factory: Callable[[str], Any] = _default_ticker_factory, timeout: float = 20) -> dict:
    t = ticker_factory(symbol)
    end = datetime.strptime(as_of, "%Y-%m-%d") + timedelta(days=1)  # yfinance end는 미포함
    start = end - timedelta(days=lookback_days + 1)
    hist = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), auto_adjust=False,
                     timeout=timeout)
    if hist is None or hist.empty:
        raise ValueError(f"{symbol}: {as_of} 이전 {lookback_days}일 가격 없음")
    idx = pd.to_datetime(hist.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    hist = hist.loc[idx <= pd.Timestamp(as_of)]
    if hist.empty:
        raise ValueError(f"{symbol}: {as_of} 이전 가격 없음")
    last = hist.iloc[-1]
    fi = t.fast_info
    shares = _get(fi, "shares")
    close = float(last["Close"])
    return {
        "price_date": pd.Timestamp(hist.index[-1]).strftime("%Y-%m-%d"),
        "close": close,
        "currency": _get(fi, "currency"),
        "shares_current": float(shares) if shares else float("nan"),
        "market_cap_current": float(_get(fi, "market_cap") or float("nan")),
        "market_cap_asof": close * float(shares) if shares else float("nan"),
    }


def crosscheck_shares(quotes: pd.DataFrame, sec_shares: pd.DataFrame | None, tol_pct: float) -> list[dict]:
    rows = []
    sec_map = {} if sec_shares is None or sec_shares.empty else sec_shares.set_index("ticker").to_dict("index")
    for _, q in quotes.iterrows():
        s = sec_map.get(q["ticker"])
        sec_val = s["shares"] if s else float("nan")
        diff = (q["shares_current"] / sec_val - 1) * 100 if s and sec_val and not pd.isna(q["shares_current"]) else float("nan")
        rows.append({
            "company": q["company"], "ticker": q["ticker"],
            "yfinance 주식수(mn)": round(q["shares_current"] / 1e6, 2) if not pd.isna(q["shares_current"]) else None,
            "SEC dei 주식수(mn)": round(sec_val / 1e6, 2) if not pd.isna(sec_val) else None,
            "SEC 기준일": s["end"] if s else None,
            "차이(%)": None if pd.isna(diff) else round(diff, 2),
            "판정": "SEC 비대상/데이터 없음" if pd.isna(diff) else ("OK" if abs(diff) <= tol_pct else "CHECK"),
        })
    return rows


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True,
        ticker_factory: Callable[[str], Any] = _default_ticker_factory) -> FetchResult:
    gcfg = cfg["data_fetch"]["global_market"]
    rows, notes = [], []
    timeout = float(cfg["data_fetch"]["http"].get("read_timeout_sec", 20))
    prog = Progress(SOURCE, "yfinance", len(cfg["peers"]["overseas"]))
    for p in cfg["peers"]["overseas"]:
        try:
            with prog.step(f"{p['name']} {p['ticker']}"):
                q = fetch_quote(p["ticker"], as_of, int(gcfg["lookback_days"]), ticker_factory, timeout)
        except ImportError as e:
            return FetchResult(SOURCE, STATUS_FAILED, message=f"yfinance 미설치: {e}")
        except Exception as e:
            notes.append(mask_secrets(f"{p['ticker']}: {type(e).__name__}: {e}"))
            continue
        rows.append({"company": p["name"], "ticker": p["ticker"], "market": p["market"], "as_of": as_of, **q,
                     "unit_price": "local currency", "source": LIB_LABEL, "source_priority": 3,
                     "cross_check_required": True,
                     "flags": "market_cap_asof=close×current_shares (ASSUMPTION)"})
    if not rows:
        return FetchResult(SOURCE, STATUS_FAILED, message="; ".join(notes))

    df = pd.DataFrame(rows)
    raw = resolve_path(cfg["paths"]["raw"]) / "global" / f"yfinance_peers_{as_of}.csv"
    save_raw(raw, df, source=LIB_LABEL, endpoint="yfinance.Ticker.history / fast_info",
             params={"tickers": [p["ticker"] for p in cfg["peers"]["overseas"]]}, as_of=as_of,
             license_note=gcfg["license_note"], fetched_at=utc_now_iso())
    out = resolve_path(cfg["paths"]["processed"]) / "global_peers_market.csv"
    save_processed(out, df, sources=[LIB_LABEL], as_of=as_of,
                   note="보조 소스. 시가총액은 현지통화 기준(USD/EUR). 공식 소스 교차검증 필요.")

    sec_path = resolve_path(cfg["paths"]["processed"]) / "sec_shares_outstanding.csv"
    sec_shares = pd.read_csv(sec_path, dtype={"ticker": str}) if sec_path.exists() else None
    if sec_shares is None:
        notes.append("SEC 발행주식수 파일 없음 → --source sec 실행 후 교차검증")
    check = crosscheck_shares(df, sec_shares, float(gcfg["crosscheck_tolerance_pct"]))
    report = resolve_path(cfg["data_fetch"]["output"]["crosscheck_report_global"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# 해외 peers 교차검증 (yfinance vs SEC EDGAR)\n\n"
        f"- 기준일: {as_of} · 생성: {utc_now_iso()} · 허용오차: ±{gcfg['crosscheck_tolerance_pct']}%\n"
        "- 공식: SEC dei:EntityCommonStockSharesOutstanding(10-K/10-Q 표지) / 보조: yfinance fast_info.shares\n"
        "- 시점 차이(공시 표지일 vs 현재)로 자사주 매입·주식보상만큼 차이가 날 수 있음\n"
        "- Schneider Electric(SU.PA)은 SEC 공시 대상이 아니므로 연차보고서(Universal Registration Document)로 수기 확인\n\n"
        + markdown_table(check), encoding="utf-8")

    status = STATUS_SUCCESS if len(rows) == len(cfg["peers"]["overseas"]) else STATUS_PARTIAL
    return FetchResult(SOURCE, status, n_items=len(rows), outputs=[str(raw), str(out), str(report)],
                       message="; ".join(notes + ["보조 소스: 교차검증 필요"]))
