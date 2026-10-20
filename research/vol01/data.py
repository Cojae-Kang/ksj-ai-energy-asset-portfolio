"""Vol.1 데이터 로드·계산 (순수 함수). 본문·제목의 모든 숫자는 여기서 계산한다.

데이터 파일이 없거나 값이 비어 있거나 'TODO'이면 해당 Exhibit은 None + 사유(reason)를 돌려준다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.data_fetch.base import meta_path_for, resolve_path, to_number


@dataclass
class Unavailable:
    """Exhibit 생략 사유 (각주 '데이터 확인 중'에 사용)."""
    reason: str


@dataclass
class Exhibit1:
    labels: list[str]
    values_twh: list[float]
    multiple_2030: float             # 2030E / 2024
    multiple_2035: float             # 2035E / 2024
    sources: list[str]


@dataclass
class Exhibit2:
    dc: float
    ai_dc: float
    global_: float
    sources: list[str]


@dataclass
class Exhibit3:
    index: pd.DataFrame              # columns: period, VA, US (기준연도=100)
    base_year: int
    last_year: int
    va_change_pct: float             # 기준연도 대비 %
    us_change_pct: float
    gap_pts: float                   # VA 지수 − US 지수 (최근연도)
    va_cagr_pct: float
    us_cagr_pct: float
    verdict: str                     # "ahead" | "behind" | "similar"


@dataclass
class Exhibit4:
    table: pd.DataFrame              # company, company_en, ticker, mcap_t0, mcap_t1, multiple
    t0: str                          # YYYY-MM-DD
    t1: str
    total_t0: float
    total_t1: float
    total_multiple: float


@dataclass
class Table1:
    table: pd.DataFrame              # company, mcap_multiple, op_multiple, val_t0, val_t1, val_multiple
    fy_from: str
    fy_to: str
    n_valuation_up: int              # 시가총액/영업이익 배수가 오른 회사 수
    n_valid: int


@dataclass
class SourceStatus:
    rows: list[dict] = field(default_factory=list)


def _is_missing(v: Any) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s.upper().startswith("TODO") or to_number(s) != to_number(s)


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, dtype={"ticker": str, "period": str, "bas_dd": str}, keep_default_na=False,
                       encoding="utf-8-sig")


def inputs(cfg: Mapping) -> dict[str, Path]:
    return {k: resolve_path(v) for k, v in cfg["research"]["vol01"]["inputs"].items()}


# ---------------------------------------------------------------------------
# IEA (Exhibit 1·2)
# ---------------------------------------------------------------------------
def _iea_lookup(df: pd.DataFrame, metric: str, period: str) -> tuple[float | None, str | None]:
    hit = df[(df["metric"] == metric) & (df["period"].astype(str) == str(period))]
    if hit.empty or _is_missing(hit.iloc[0]["value"]):
        return None, None
    r = hit.iloc[0]
    return to_number(r["value"]), f"{r.get('source', 'IEA')} ({r.get('published', '')})".replace(" ()", "")


def exhibit1(cfg: Mapping) -> Exhibit1 | Unavailable:
    df = _read_csv(inputs(cfg)["iea"])
    if df is None:
        return Unavailable("data/manual/iea_energy_ai.csv 없음")
    labels, vals, srcs = [], [], []
    for spec in cfg["research"]["vol01"]["iea_metrics"]["exhibit1"]:
        v, src = _iea_lookup(df, spec["metric"], spec["period"])
        if v is None:
            return Unavailable(f"IEA {spec['metric']} {spec['period']} 값 없음/TODO")
        labels.append(spec["label"]); vals.append(v); srcs.append(src)
    return Exhibit1(labels, vals, vals[1] / vals[0], vals[2] / vals[0], sorted(set(srcs)))


def exhibit2(cfg: Mapping) -> Exhibit2 | Unavailable:
    df = _read_csv(inputs(cfg)["iea"])
    if df is None:
        return Unavailable("data/manual/iea_energy_ai.csv 없음")
    got, srcs = {}, []
    for spec in cfg["research"]["vol01"]["iea_metrics"]["exhibit2"]:
        v, src = _iea_lookup(df, spec["metric"], spec["period"])
        if v is None:
            return Unavailable(f"IEA {spec['metric']} {spec['period']} 값 없음/TODO")
        got[spec["key"]] = v; srcs.append(src)
    return Exhibit2(got["dc"], got["ai_dc"], got["global"], sorted(set(srcs)))


# ---------------------------------------------------------------------------
# EIA (Exhibit 3)
# ---------------------------------------------------------------------------
def cagr_pct(start: float, end: float, years: int) -> float:
    return ((end / start) ** (1 / years) - 1) * 100 if years > 0 and start > 0 else float("nan")


def exhibit3(cfg: Mapping) -> Exhibit3 | Unavailable:
    v = cfg["research"]["vol01"]["eia_state"]
    df = _read_csv(inputs(cfg)["eia_state"])
    if df is None:
        return Unavailable("data/processed/vol01_eia_state.csv 없음 (research.vol01.fetch_extra --only eia 실행 필요)")
    df = df[df["sectorid"] == v["sector"]].copy()
    df["period"] = df["period"].astype(int)
    df["sales"] = df["sales"].map(to_number)
    wide = df.pivot_table(index="period", columns="stateid", values="sales", aggfunc="first")
    states = ["VA", "US"]
    base = int(v["base_year"])
    if any(s not in wide for s in states) or base not in wide.index:
        return Unavailable(f"EIA VA/US {base}년 기준값 없음")
    wide = wide[states].dropna()
    wide = wide[wide.index >= base]
    if len(wide) < 2 or (wide.loc[base] <= 0).any():
        return Unavailable("EIA VA/US 시계열 부족")
    idx = wide.div(wide.loc[base]).mul(100).reset_index()
    last = int(idx["period"].max())
    va, us = float(idx.iloc[-1]["VA"]), float(idx.iloc[-1]["US"])
    gap = va - us
    thr = float(v["divergence_pts"])
    verdict = "ahead" if gap >= thr else ("behind" if gap <= -thr else "similar")
    yrs = last - base
    return Exhibit3(idx, base, last, va - 100, us - 100, gap,
                    cagr_pct(wide.loc[base, "VA"], wide.loc[last, "VA"], yrs),
                    cagr_pct(wide.loc[base, "US"], wide.loc[last, "US"], yrs), verdict)


# ---------------------------------------------------------------------------
# KRX (Exhibit 4) + DART (Table 1)
# ---------------------------------------------------------------------------
def _ymd(s: str) -> str:
    s = str(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


def exhibit4(cfg: Mapping) -> Exhibit4 | Unavailable:
    df = _read_csv(inputs(cfg)["krx_points"])
    if df is None:
        return Unavailable("data/processed/vol01_krx_mcap_points.csv 없음 (research.vol01.fetch_extra --only krx 실행 필요)")
    df["market_cap_krw_100m"] = df["market_cap_krw_100m"].map(to_number)
    p0, p1 = df[df["point"] == "start_2023"], df[df["point"] == "latest"]
    if p0.empty or p1.empty:
        return Unavailable("KRX 두 시점 중 하나 없음")
    t = p0[["company", "company_en", "ticker", "market_cap_krw_100m"]].rename(columns={"market_cap_krw_100m": "mcap_t0"})
    t = t.merge(p1[["ticker", "market_cap_krw_100m"]].rename(columns={"market_cap_krw_100m": "mcap_t1"}), on="ticker")
    if t.empty or t[["mcap_t0", "mcap_t1"]].isna().any().any():
        return Unavailable("KRX 시가총액 일부 누락")
    order = [str(p["ticker"]).zfill(6) for p in cfg["peers"]["domestic"]]
    t["ticker"] = t["ticker"].str.zfill(6)
    t = t.set_index("ticker").reindex([o for o in order if o in set(t["ticker"])]).reset_index()
    t["multiple"] = t["mcap_t1"] / t["mcap_t0"]
    tot0, tot1 = float(t["mcap_t0"].sum()), float(t["mcap_t1"].sum())
    return Exhibit4(t, _ymd(p0.iloc[0]["bas_dd"]), _ymd(p1.iloc[0]["bas_dd"]), tot0, tot1, tot1 / tot0)


def table1(cfg: Mapping, ex4: Exhibit4 | Unavailable, fy_from: str = "FY2023A",
           fy_to: str = "FY2025A") -> Table1 | Unavailable:
    """시가총액 배수 = 영업이익 배수 × (시가총액/영업이익) 배수 로 분해."""
    if isinstance(ex4, Unavailable):
        return Unavailable("Exhibit 4 데이터 없음")
    d = _read_csv(inputs(cfg)["dart"])
    if d is None:
        return Unavailable("data/processed/dart_financials.csv 없음")
    d["operating_income"] = d["operating_income"].map(to_number)
    d["ticker"] = d["ticker"].str.zfill(6)
    op = d.pivot_table(index="ticker", columns="fiscal_year", values="operating_income", aggfunc="first")
    if fy_from not in op or fy_to not in op:
        return Unavailable(f"DART {fy_from}/{fy_to} 영업이익 없음")
    rows = []
    for _, r in ex4.table.iterrows():
        o0, o1 = (op.loc[r["ticker"], fy_from], op.loc[r["ticker"], fy_to]) if r["ticker"] in op.index else (None, None)
        ok = o0 is not None and o1 is not None and o0 > 0 and o1 > 0
        v0 = r["mcap_t0"] / o0 if ok else float("nan")
        v1 = r["mcap_t1"] / o1 if ok else float("nan")
        rows.append({"company": r["company"], "company_en": r["company_en"], "ticker": r["ticker"],
                     "mcap_multiple": r["multiple"], "op_t0": o0, "op_t1": o1,
                     "op_multiple": o1 / o0 if ok else float("nan"),
                     "val_t0": v0, "val_t1": v1, "val_multiple": v1 / v0 if ok else float("nan")})
    t = pd.DataFrame(rows)
    valid = t["val_multiple"].notna()
    return Table1(t, fy_from, fy_to, int((t.loc[valid, "val_multiple"] > 1).sum()), int(valid.sum()))


# ---------------------------------------------------------------------------
# 데이터 소스 상태 (What I built / Methodology)
# ---------------------------------------------------------------------------
SOURCES = [
    # id, 기관(KR), 기관(EN), 용도(KR), 용도(EN), 대표 산출물
    ("dart", "DART · 금융감독원", "DART · FSS", "국내 peers 재무제표", "Korean peers' financials", "dart_financials.csv"),
    ("krx", "KRX · 한국거래소", "KRX · Korea Exchange", "주가·시가총액", "Prices, market cap", "krx_peers_market.csv"),
    ("ecos", "ECOS · 한국은행", "ECOS · Bank of Korea", "환율·국고채 금리", "FX, KTB yields", "ecos_fx_annual.csv"),
    ("fred", "FRED · St. Louis Fed", "FRED · St. Louis Fed", "미 국채 금리·환율", "UST yield, FX", "fred_series.csv"),
    ("eia", "EIA · 미 에너지정보청", "EIA · U.S. EIA", "미국 전력 판매", "U.S. electricity sales", "eia_retail_sales_annual.csv"),
    ("sec", "SEC EDGAR", "SEC EDGAR", "해외 peers 재무제표", "Overseas peers' financials", "sec_financials.csv"),
]


def source_status(cfg: Mapping) -> list[dict]:
    processed = resolve_path(cfg["paths"]["processed"])
    override = cfg["research"]["vol01"].get("source_status_override") or {}
    rows = []
    for sid, org_kr, org_en, use_kr, use_en, fname in SOURCES:
        path = processed / fname
        as_of = None
        if path.exists() and meta_path_for(path).exists():
            as_of = json.loads(meta_path_for(path).read_text(encoding="utf-8")).get("as_of")
        if sid in override:
            st_kr, st_en, ok = override[sid], "In progress", False
        elif path.exists():
            st_kr, st_en, ok = "수집 완료", "Collected", True
        else:
            st_kr, st_en, ok = "미수집", "Not collected", False
        rows.append({"id": sid, "org_kr": org_kr, "org_en": org_en, "use_kr": use_kr, "use_en": use_en,
                     "status_kr": st_kr, "status_en": st_en, "ok": ok, "as_of": as_of if ok else None})
    return rows


def count_tests(root: Path | None = None) -> int:
    root = root or resolve_path("tests")
    return sum(Path(p).read_text(encoding="utf-8").count("\ndef test_") for p in root.glob("test_*.py"))
