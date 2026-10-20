"""peers 재무 통합 → data/processed/peers_financials.csv

정규화 규칙
- 회계연도: FY2023A 형식
- 원통화 값: 국내 KRW 억원 / 해외 USD mn (SEC) / 수기 입력(EUR mn 등)
- 환산: KRW 억원·USD mn 열을 모두 제공. 손익(flow)은 연평균 환율, 재무상태(stock)는 연말 환율
  (출처: ECOS 원/달러 매매기준율). EUR 등 기타 통화는 환율 소스 미연결 → NaN + 플래그 (TODO(data))
"""
from __future__ import annotations

import logging
from typing import Mapping

import numpy as np
import pandas as pd

from .base import (FetchResult, STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS, resolve_path,
                   save_processed)

logger = logging.getLogger("data_fetch.consolidate")

FLOW = ["revenue", "operating_income", "net_income"]
STOCK = ["total_debt", "cash", "net_debt"]
METRICS = FLOW + STOCK
COLUMNS = ["company", "ticker", "region", "source", "basis", "fiscal_year", "fiscal_year_end", "currency", "unit",
           *METRICS, "fx_usdkrw_avg", "fx_usdkrw_year_end",
           *[f"{m}_krw_100m" for m in METRICS], *[f"{m}_usd_mn" for m in METRICS], "flags"]


def usd_mn_to_krw_100m(v: float, fx: float) -> float:
    """USD mn × (KRW/USD) → KRW 억원.  1 USD mn × 1,400 = 14억원 → v × fx / 100."""
    return v * fx / 100.0


def krw_100m_to_usd_mn(v: float, fx: float) -> float:
    """KRW 억원 → USD mn.  14억원 / 1,400 = 1 USD mn → v × 100 / fx."""
    return v * 100.0 / fx


def _from_dart(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["region"], out["source"] = "KR", "Open DART"
    out["basis"] = out["fs_div"].map({"CFS": "K-IFRS 연결", "OFS": "K-IFRS 별도"}).fillna(out["fs_div"])
    out["fiscal_year_end"] = out["fiscal_year"].str[2:6] + "-12-31"  # ASSUMPTION: 국내 peers 12월 결산
    out["flags"] = out["flags"].fillna("").astype(str)
    return out


def _from_sec(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["region"], out["source"] = "US", "SEC EDGAR companyfacts"
    out["flags"] = out["flags"].fillna("").astype(str)
    return out


def _from_manual(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["region"] = out.get("region", "EU")
    out["source"] = out["source"].fillna("manual")
    out["basis"] = out.get("basis", "IFRS (manual)")
    empty = out[["revenue", "operating_income", "net_income", "total_debt", "cash"]].isna().all(axis=1)
    out["flags"] = np.where(empty, "TODO(data):manual_input_missing", "manual_input")
    return out


def consolidate(dart: pd.DataFrame | None, sec: pd.DataFrame | None, manual: pd.DataFrame | None,
                fx_annual: pd.DataFrame | None) -> pd.DataFrame:
    parts = []
    if dart is not None and not dart.empty:
        parts.append(_from_dart(dart))
    if sec is not None and not sec.empty:
        parts.append(_from_sec(sec))
    if manual is not None and not manual.empty:
        parts.append(_from_manual(manual))
    # pandas FutureWarning 방지: 빈 DataFrame은 제외하고, 전부 NA인 열(예: 미입력 수기 템플릿의 금액 열)은
    # concat 전에 떨어뜨린 뒤 아래에서 숫자형 NaN으로 다시 만든다 (dtype 추론에 NA 열이 끼지 않게).
    parts = [p.dropna(axis=1, how="all") for p in parts]
    parts = [p for p in parts if not p.empty and p.shape[1] > 0]
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(parts, ignore_index=True)
    for m in ["revenue", "operating_income", "net_income", "total_debt", "cash"]:
        df[m] = pd.to_numeric(df[m], errors="coerce") if m in df else np.nan
    for col in ["fiscal_year_end", "basis", "flags", "currency", "unit"]:
        if col not in df:
            df[col] = np.nan
    df["flags"] = df["flags"].fillna("").astype(str)
    df["net_debt"] = df["total_debt"] - df["cash"]

    fx = {} if fx_annual is None or fx_annual.empty else fx_annual.set_index("fiscal_year")[
        ["usdkrw_avg", "usdkrw_year_end"]].to_dict("index")
    df["fx_usdkrw_avg"] = df["fiscal_year"].str[:6].map(lambda k: fx.get(k, {}).get("usdkrw_avg", np.nan))
    df["fx_usdkrw_year_end"] = df["fiscal_year"].str[:6].map(lambda k: fx.get(k, {}).get("usdkrw_year_end", np.nan))

    for m in METRICS:
        rate = df["fx_usdkrw_avg"] if m in FLOW else df["fx_usdkrw_year_end"]
        is_krw = (df["currency"] == "KRW") & (df["unit"] == "억원")
        is_usd = (df["currency"] == "USD") & (df["unit"] == "mn")
        df[f"{m}_krw_100m"] = np.where(is_krw, df[m], np.where(is_usd, usd_mn_to_krw_100m(df[m], rate), np.nan))
        df[f"{m}_usd_mn"] = np.where(is_usd, df[m], np.where(is_krw, krw_100m_to_usd_mn(df[m], rate), np.nan))

    def add_flag(mask, flag):
        df.loc[mask, "flags"] = df.loc[mask, "flags"].map(lambda s: f"{s};{flag}" if s else flag)

    add_flag(~df["currency"].isin(["KRW", "USD"]), "fx_missing:non_KRW_USD(TODO(data))")
    add_flag(df["currency"].isin(["KRW", "USD"]) & df["fx_usdkrw_avg"].isna(), "fx_missing:ECOS_annual")
    return df.reindex(columns=COLUMNS).sort_values(["region", "company", "fiscal_year"]).reset_index(drop=True)


def _read(path) -> pd.DataFrame | None:
    return pd.read_csv(path, dtype={"ticker": str, "corp_code": str, "cik": str}) if path.exists() else None


def run(cfg: Mapping, as_of: str, **_) -> FetchResult:
    processed = resolve_path(cfg["paths"]["processed"])
    dart = _read(processed / "dart_financials.csv")
    sec = _read(processed / "sec_financials.csv")
    manual = _read(resolve_path(cfg["data_fetch"]["manual_overseas_financials"]))
    fx = _read(processed / "ecos_fx_annual.csv")
    notes = [f"{n} 없음" for n, d in [("dart_financials", dart), ("sec_financials", sec),
                                      ("ecos_fx_annual", fx)] if d is None]
    df = consolidate(dart, sec, manual, fx)
    if df.empty:
        return FetchResult("consolidate", STATUS_FAILED, message="통합할 재무 데이터 없음; " + "; ".join(notes))
    out = resolve_path(cfg["data_fetch"]["output"]["processed_peers"])
    save_processed(out, df, sources=["Open DART", "SEC EDGAR", "ECOS", "manual"], as_of=as_of,
                   note="원통화(KRW 억원/USD mn) + KRW 억원·USD mn 환산. flow=연평균, stock=연말 환율(ECOS).")
    status = STATUS_SUCCESS if not notes else STATUS_PARTIAL
    return FetchResult("consolidate", status, n_items=len(df), outputs=[str(out)], message="; ".join(notes))
