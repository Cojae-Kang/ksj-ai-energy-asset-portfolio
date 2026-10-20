"""Vol.1 추가 수집 (로컬 실행 전용). 기존 src/data_fetch/base.py 인프라를 그대로 사용한다.

    python -m research.vol01.fetch_extra --asof 2026-10-20
    python -m research.vol01.fetch_extra --only eia
    python -m research.vol01.fetch_extra --only krx --no-cache
    python -m research.vol01.fetch_extra --only dart eia_sectors

A-1) EIA: 상업용(COM) 전력 소매판매량, 연간, 2015~최신, 버지니아(VA)·미국 전체(US)
     → data/processed/vol01_eia_state.csv (+ .meta.json), raw: data/raw/eia/vol01_retail_sales_com_states.json
A-2) KRX Open API: 국내 peers 4사 시가총액 두 시점
     ① 2023년 첫 거래일 (config start_from부터 앞으로 탐색) ② 기준일 직전 거래일 (기준일 당일 제외, 뒤로 탐색)
     → data/processed/vol01_krx_mcap_points.csv (+ .meta.json), raw: data/raw/krx/daily_trade_YYYYMMDD.json
A-3) DART: 국내 peers FY2022 사업보고서 재무(매출·영업이익·지배순이익) — 2023년 초 시총과 짝을 맞출 이익
     → data/processed/vol01_dart_extra.csv (+ .meta.json), 스키마는 dart_financials.csv와 동일
A-4) EIA: 미국 부문별(주거·상업·산업) 전력 판매량·평균 가격, 연간 2015~최신
     → data/processed/vol01_eia_us_sectors.csv (+ .meta.json)
키가 없으면 해당 항목만 SKIPPED로 건너뛴다. 원자료(data/raw)는 커밋하지 않는다.
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

from src.data_fetch import dart, eia, krx
from src.data_fetch.base import (FetchError, FetchResult, Progress, SkipSource, STATUS_FAILED,
                                 STATUS_PARTIAL, STATUS_SKIPPED, STATUS_SUCCESS, load_config, mask_secrets,
                                 resolve_path, save_processed, setup_logging)

logger = logging.getLogger("research.vol01.fetch_extra")

EIA_RAW_NAME = "vol01_retail_sales_com_states.json"
EIA_OUT = "vol01_eia_state.csv"
KRX_OUT = "vol01_krx_mcap_points.csv"
DART_OUT = "vol01_dart_extra.csv"
EIA_SECTORS_RAW = "vol01_retail_sales_us_sectors.json"
EIA_SECTORS_OUT = "vol01_eia_us_sectors.csv"


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
# A-3) DART 추가 연도 (FY2022)
# ---------------------------------------------------------------------------
def dart_rows_for_year(client, peer: Mapping, corp_code: str, year: int, dcfg: Mapping) -> dict | None:
    rows, fs_div = client.fetch_financials(corp_code, year, str(peer["ticker"]).zfill(6))
    if not rows:
        return None
    metrics, _debt, flags = dart.extract_dart_metrics(rows, dcfg)
    return {"company": peer["name"], "ticker": str(peer["ticker"]).zfill(6), "corp_code": corp_code,
            "fiscal_year": f"FY{year}A", "fs_div": fs_div, "rcept_no": rows[0].get("rcept_no"),
            "currency": "KRW", "unit": "억원", **metrics, "flags": ";".join(flags)}


def fetch_dart_extra(cfg: Mapping, as_of: str, *, use_cache: bool = True, client=None) -> FetchResult:
    years = [int(y) for y in cfg["research"]["vol01"]["dart_extra_years"]]
    dcfg = cfg["data_fetch"]["dart"]
    client = client or dart.DartClient(cfg, as_of, use_cache=use_cache)   # 키 없으면 SkipSource
    with Progress("dart", "고유번호", 1).step("corpCode.xml"):
        client.fetch_corp_codes()
    peers = cfg["peers"]["domestic"]
    prog = Progress("dart", "추가 연도 재무제표", len(peers) * len(years))
    out_rows, notes = [], []
    for peer in peers:
        corp_code = client.corp_code_for(str(peer["ticker"]).zfill(6))
        for year in years:
            try:
                with prog.step(f"{peer['name']} FY{year}") as st:
                    row = dart_rows_for_year(client, peer, corp_code, year, dcfg) if corp_code else None
                    if row is None:
                        st["status"] = "데이터 없음"
                    else:
                        st["note"] = f"({row['fs_div']})"
            except FetchError as e:
                notes.append(mask_secrets(f"{peer['name']} FY{year}: {e}"))
                continue
            if row is None:
                notes.append(f"{peer['name']} FY{year}: 재무제표 없음")
            else:
                out_rows.append(row)
    if not out_rows:
        return FetchResult("dart_extra", STATUS_FAILED, message="; ".join(notes) or "수집 결과 없음")
    out = resolve_path(cfg["paths"]["processed"]) / DART_OUT
    save_processed(out, pd.DataFrame(out_rows), sources=["Open DART fnlttSinglAcntAll"], as_of=as_of,
                   note=f"FY{years} 사업보고서(11011) 당기 금액, KRW 억원. 지배순이익 우선(net_income). "
                        "스키마는 dart_financials.csv와 동일")
    status = STATUS_PARTIAL if notes else STATUS_SUCCESS
    return FetchResult("dart_extra", status, n_items=len(out_rows), outputs=[str(out)], message="; ".join(notes))


# ---------------------------------------------------------------------------
# A-4) EIA 미국 부문별 판매량·가격
# ---------------------------------------------------------------------------
def eia_sectors_config(cfg: Mapping) -> dict:
    v = cfg["research"]["vol01"]["eia_sectors"]
    c = copy.deepcopy(dict(cfg))
    c["data_fetch"]["eia"].update(state=v["state"], sectors=list(v["sectors"]), data_fields=list(v["data_fields"]),
                                  start=str(v["start"]), end=None)
    return c


def fetch_eia_sectors(cfg: Mapping, as_of: str, *, use_cache: bool = True, client=None) -> FetchResult:
    c2 = eia_sectors_config(cfg)
    v = cfg["research"]["vol01"]["eia_sectors"]
    client = client or eia.EiaClient(c2, as_of, use_cache=use_cache)
    rows, _ = client.fetch_retail_sales(raw_name=EIA_SECTORS_RAW)
    df = eia.tidy(rows, list(v["data_fields"]), c2["data_fetch"]["eia"]["source_label"])
    if df.empty:
        return FetchResult("eia_sectors", STATUS_FAILED, message="EIA 부문별 데이터 없음")
    df = df[df["sectorid"].isin(v["sectors"])].copy()
    df["period"] = df["period"].astype(int)
    out = resolve_path(cfg["paths"]["processed"]) / EIA_SECTORS_OUT
    save_processed(out, df, sources=[c2["data_fetch"]["eia"]["source_label"]], as_of=as_of,
                   note="electricity/retail-sales, US, RES/COM/IND, annual. sales: million kWh, price: cents/kWh")
    return FetchResult("eia_sectors", STATUS_SUCCESS, n_items=len(df), outputs=[str(out)],
                       message=f"{df['period'].min()}~{df['period'].max()}, {sorted(set(df['sectorid']))}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
TASKS = {"eia": fetch_eia_state, "krx": fetch_krx_points, "dart": fetch_dart_extra, "eia_sectors": fetch_eia_sectors}


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
