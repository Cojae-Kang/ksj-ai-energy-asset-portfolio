"""Vol.1 추가 수집 (로컬 실행 전용). 기존 src/data_fetch/base.py 인프라를 그대로 사용한다.

    python -m research.vol01.fetch_extra --asof 2026-10-20
    python -m research.vol01.fetch_extra --only eia
    python -m research.vol01.fetch_extra --only krx --no-cache

A-1) EIA: 상업용(COM) 전력 소매판매량, 연간, 2015~최신, 버지니아(VA)·미국 전체(US)
     → data/processed/vol01_eia_state.csv (+ .meta.json), raw: data/raw/eia/vol01_retail_sales_com_states.json
A-2) KRX Open API: 국내 peers 4사 시가총액 두 시점
     ① 2023년 첫 거래일 (config start_from부터 앞으로 탐색) ② 기준일 직전 거래일 (기준일 당일 제외, 뒤로 탐색)
     → data/processed/vol01_krx_mcap_points.csv (+ .meta.json), raw: data/raw/krx/daily_trade_YYYYMMDD.json
키가 없으면 해당 항목만 SKIPPED로 건너뛴다.
"""
from __future__ import annotations

import argparse
import copy
import logging
import sys
import time
from datetime import date, datetime, timedelta
from typing import Mapping

import pandas as pd

from src.data_fetch import eia, krx
from src.data_fetch.base import (FetchError, FetchResult, Progress, SkipSource, STATUS_FAILED,
                                 STATUS_PARTIAL, STATUS_SKIPPED, STATUS_SUCCESS, load_config, mask_secrets,
                                 resolve_path, save_processed, setup_logging)

logger = logging.getLogger("research.vol01.fetch_extra")

EIA_RAW_NAME = "vol01_retail_sales_com_states.json"
EIA_OUT = "vol01_eia_state.csv"
KRX_OUT = "vol01_krx_mcap_points.csv"


# ---------------------------------------------------------------------------
# A-1) EIA 주별 상업용 전력 판매
# ---------------------------------------------------------------------------
def eia_state_config(cfg: Mapping) -> dict:
    """기존 data_fetch.eia 설정을 복사해 Vol.1 범위(주·부문·시작연도)로 덮어쓴 cfg."""
    v = cfg["research"]["vol01"]["eia_state"]
    c = copy.deepcopy(dict(cfg))
    e = c["data_fetch"]["eia"]
    e.update(state=list(v["states"]), sectors=[v["sector"]], data_fields=["sales"], start=str(v["start"]), end=None)
    return c


def tidy_eia_state(rows: list[dict], states: list[str], sector: str, source_label: str) -> pd.DataFrame:
    df = eia.tidy(rows, ["sales"], source_label)
    if df.empty:
        return df
    df = df[df["stateid"].isin(states) & (df["sectorid"] == sector)].copy()
    df["period"] = df["period"].astype(int)
    cols = ["period", "stateid", "stateDescription", "sectorid", "sectorName", "sales", "sales-units", "source"]
    return df[[c for c in cols if c in df]].sort_values(["stateid", "period"]).reset_index(drop=True)


def fetch_eia_state(cfg: Mapping, as_of: str, *, use_cache: bool = True, client=None) -> FetchResult:
    c2 = eia_state_config(cfg)
    v = cfg["research"]["vol01"]["eia_state"]
    client = client or eia.EiaClient(c2, as_of, use_cache=use_cache)   # 키 없으면 SkipSource
    rows, _ = client.fetch_retail_sales(raw_name=EIA_RAW_NAME)
    df = tidy_eia_state(rows, v["states"], v["sector"], c2["data_fetch"]["eia"]["source_label"])
    missing = [s for s in v["states"] if df.empty or s not in set(df["stateid"])]
    if df.empty:
        return FetchResult("eia_state", STATUS_FAILED, message="EIA 응답에 VA/US 상업용 데이터 없음")
    out = resolve_path(cfg["paths"]["processed"]) / EIA_OUT
    save_processed(out, df, sources=[c2["data_fetch"]["eia"]["source_label"]], as_of=as_of,
                   note=f"electricity/retail-sales, sector={v['sector']}, annual, {v['start']}~최신. "
                        "sales 단위: million kWh (sales-units 열)")
    status = STATUS_PARTIAL if missing else STATUS_SUCCESS
    return FetchResult("eia_state", status, n_items=len(df),
                       outputs=[str(client.raw_dir / EIA_RAW_NAME), str(out)],
                       message=f"누락 주: {missing}" if missing else
                       f"{df['period'].min()}~{df['period'].max()}, {sorted(set(df['stateid']))}")


# ---------------------------------------------------------------------------
# A-2) KRX 시가총액 두 시점
# ---------------------------------------------------------------------------
def _d(s: str) -> date:
    return datetime.strptime(s.replace("-", ""), "%Y%m%d").date()


def find_trading_day(client, start: date, step: int, max_days: int, label: str) -> tuple[str, list[dict]]:
    """start부터 step(+1 앞으로 / −1 뒤로) 방향으로 일별매매정보가 있는 첫 날 탐색."""
    prog = Progress("krx", f"거래일 탐색({label})", max_days + 1)
    for i in range(max_days + 1):
        bas_dd = (start + timedelta(days=step * i)).strftime("%Y%m%d")
        with prog.step(bas_dd) as st:
            rows = client.fetch("daily_trade", bas_dd)
            if rows:
                st["note"] = f"({len(rows)}종목) → 사용"
            else:
                st["status"] = "데이터 없음(휴장일?)"
        if rows:
            return bas_dd, rows
    raise FetchError(f"KRX {label}: {start}부터 {max_days}일 탐색했지만 거래일 데이터 없음")


def mcap_points_frame(points: list[tuple[str, str, list[dict]]], peers: list[Mapping]) -> pd.DataFrame:
    """[(point, bas_dd, trade_rows)] → 회사×시점 시가총액 표 (KRW 억원)."""
    tickers = [str(p["ticker"]).zfill(6) for p in peers]
    out = []
    for point, bas_dd, rows in points:
        sel = krx.select_peer_rows(rows, [], tickers)
        for p, t in zip(peers, tickers):
            r = sel.get(t, {})
            mcap = r.get("market_cap_krw", float("nan"))
            out.append({"point": point, "bas_dd": bas_dd, "company": p["name"], "company_en": p.get("name_en", p["name"]),
                        "ticker": t, "close_krw": r.get("close_krw", float("nan")),
                        "market_cap_krw_100m": mcap / 1e8 if mcap == mcap else float("nan"),
                        "listed_shares": r.get("listed_shares", float("nan")), "source": "KRX Open API"})
    return pd.DataFrame(out)


def fetch_krx_points(cfg: Mapping, as_of: str, *, use_cache: bool = True, client=None) -> FetchResult:
    kp = cfg["research"]["vol01"]["krx_points"]
    client = client or krx.KrxOpenApiClient(cfg, as_of, use_cache=use_cache)   # 키 없으면 SkipSource
    t0, rows0 = find_trading_day(client, _d(kp["start_from"]), +1, int(kp["max_forward_days"]), "2023년 첫 거래일")
    t1, rows1 = find_trading_day(client, _d(as_of) - timedelta(days=1), -1, int(kp["max_lookback_days"]),
                                 "기준일 직전 거래일")
    df = mcap_points_frame([("start_2023", t0, rows0), ("latest", t1, rows1)], cfg["peers"]["domestic"])
    missing = df[df["market_cap_krw_100m"].isna()][["point", "company"]].values.tolist()
    out = resolve_path(cfg["paths"]["processed"]) / KRX_OUT
    save_processed(out, df, sources=["KRX Open API (유가증권 일별매매정보)"], as_of=as_of,
                   note=f"MKTCAP(원)→KRW 억원. start_2023={t0}, latest={t1} (기준일 {as_of} 직전 거래일)")
    status = STATUS_PARTIAL if missing else STATUS_SUCCESS
    return FetchResult("krx_points", status, n_items=int(df["market_cap_krw_100m"].notna().sum()),
                       outputs=[str(out)], message=f"start_2023={t0}, latest={t1}"
                       + (f"; 누락 {missing}" if missing else ""))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
TASKS = {"eia": fetch_eia_state, "krx": fetch_krx_points}


def run_task(name: str, cfg: Mapping, as_of: str, use_cache: bool) -> FetchResult:
    t0 = time.monotonic()
    try:
        res = TASKS[name](cfg, as_of, use_cache=use_cache)
    except SkipSource as e:
        res = FetchResult(name, STATUS_SKIPPED, message=str(e))
    except Exception as e:  # 한 항목 실패가 다른 항목을 막지 않도록
        res = FetchResult(name, STATUS_FAILED, message=mask_secrets(f"{type(e).__name__}: {e}"))
    res.elapsed_sec = round(time.monotonic() - t0, 1)
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Vol.1 추가 수집 (로컬 실행)")
    p.add_argument("--asof", default=None, help="기준일 YYYY-MM-DD (기본: config data_fetch.as_of_default)")
    p.add_argument("--only", choices=list(TASKS), nargs="+", default=list(TASKS))
    p.add_argument("--config", default=None)
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    as_of = args.asof or cfg["data_fetch"]["as_of_default"]
    results = [run_task(n, cfg, as_of, not args.no_cache) for n in args.only]
    print("\n=== Vol.1 추가 수집 요약 ===")
    for r in results:
        print(f"{r.source:<11} {r.status:<8} {r.n_items:>4}  {r.elapsed_sec:>5}s  {r.message}")
    return 1 if any(r.status == STATUS_FAILED for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
