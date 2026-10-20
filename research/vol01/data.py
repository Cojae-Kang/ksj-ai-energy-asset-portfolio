"""Vol.1 데이터 로드·계산 (순수 함수). 보고서의 모든 숫자·서술 방향은 여기서 계산한다.

데이터 파일이 없거나 값이 비어 있거나 'TODO'이면 Unavailable(사유, 실행 명령)을 돌려주고,
보고서는 그 Exhibit만 회색 박스 "데이터 수집 후 생성"으로 둔다.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.data_fetch.base import meta_path_for, resolve_path, to_number

CMD_EIA_STATE = "python -m research.vol01.fetch_extra --only eia"
CMD_EIA_SECTORS = "python -m research.vol01.fetch_extra --only eia_sectors"
CMD_KRX = "python -m research.vol01.fetch_extra --only krx"
CMD_DART = "python -m research.vol01.fetch_extra --only dart"


@dataclass
class Unavailable:
    """Exhibit 생략 사유(국문·영문) + 데이터를 채우는 실행 명령."""
    reason: str
    command: str = ""
    reason_en: str = ""


def ok(x: Any) -> bool:
    return not isinstance(x, Unavailable)


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


def _paths(v: str | list[str]) -> list[Path]:
    return [resolve_path(p) for p in (v if isinstance(v, list) else [v])]


def inputs(cfg: Mapping) -> dict[str, list[Path]]:
    return {k: _paths(v) for k, v in cfg["research"]["vol01"]["inputs"].items()}


def meta_as_of(path: Path) -> str | None:
    m = meta_path_for(path)
    if not m.exists():
        return None
    d = json.loads(m.read_text(encoding="utf-8"))
    return d.get("verified_on") or d.get("as_of")


# ---------------------------------------------------------------------------
# I. 수요 (IEA)
# ---------------------------------------------------------------------------
@dataclass
class Demand:
    v: dict[str, float | None]          # config iea_metrics 키 → 값
    as_of: str | None

    def has(self, *keys: str) -> bool:
        return all(self.v.get(k) is not None for k in keys)

    @property
    def mult_2030(self) -> float:
        return self.v["dc_2030"] / self.v["dc_2024"]

    @property
    def mult_2035(self) -> float:
        return self.v["dc_2035"] / self.v["dc_2024"]

    @property
    def region_other(self) -> float:
        return 100 - self.v["region_us"] - self.v["region_cn"] - self.v["region_eu"]

    @property
    def ai_vs_global(self) -> float:
        return self.v["growth_ai"] / self.v["growth_global"] if self.v["growth_global"] else float("nan")


def demand(cfg: Mapping) -> Demand | Unavailable:
    path = inputs(cfg)["iea"][0]
    df = _read_csv(path)
    if df is None:
        return Unavailable("data/manual/iea_energy_ai.csv 없음", "", "data/manual/iea_energy_ai.csv missing")
    vals: dict[str, float | None] = {}
    for key, spec in cfg["research"]["vol01"]["iea_metrics"].items():
        hit = df[(df["metric"] == spec["metric"]) & (df["period"].astype(str) == str(spec["period"]))]
        vals[key] = None if hit.empty or _is_missing(hit.iloc[0]["value"]) else to_number(hit.iloc[0]["value"])
    return Demand(vals, meta_as_of(path))


# ---------------------------------------------------------------------------
# II. 현장 (EIA)
# ---------------------------------------------------------------------------
def cagr_pct(start: float, end: float, years: int) -> float:
    return ((end / start) ** (1 / years) - 1) * 100 if years > 0 and start > 0 else float("nan")


@dataclass
class Ground:
    index: pd.DataFrame                 # period, VA, US (기준연도=100)
    sales: pd.DataFrame                 # period, VA, US (million kWh)
    base_year: int
    last_year: int
    va_change_pct: float
    us_change_pct: float
    gap_pts: float
    va_cagr_pct: float
    us_cagr_pct: float
    va_recent_cagr_pct: float           # 최근 3년
    us_recent_cagr_pct: float
    recent_from: int
    verdict: str                        # ahead | behind | similar
    yoy: pd.DataFrame                   # period, VA, US (전년 대비 %)

    @property
    def speed_ratio(self) -> float:
        return self.va_change_pct / self.us_change_pct if self.us_change_pct > 0 else float("nan")


def ground(cfg: Mapping) -> Ground | Unavailable:
    v = cfg["research"]["vol01"]["eia_state"]
    df = _read_csv(inputs(cfg)["eia_state"][0])
    if df is None:
        return Unavailable("vol01_eia_state.csv 없음", CMD_EIA_STATE, "vol01_eia_state.csv missing")
    df = df[df["sectorid"] == v["sector"]].copy()
    df["period"] = df["period"].astype(int)
    df["sales"] = df["sales"].map(to_number)
    wide = df.pivot_table(index="period", columns="stateid", values="sales", aggfunc="first")
    base = int(v["base_year"])
    if any(s not in wide for s in ("VA", "US")) or base not in wide.index:
        return Unavailable(f"EIA VA/US {base}년 기준값 없음", CMD_EIA_STATE, f"EIA VA/US {base} base value missing")
    wide = wide[["VA", "US"]].dropna()
    wide = wide[wide.index >= base]
    if len(wide) < 4 or (wide.loc[base] <= 0).any():
        return Unavailable("EIA VA/US 시계열 부족", CMD_EIA_STATE, "EIA VA/US series too short")
    idx = wide.div(wide.loc[base]).mul(100)
    last = int(idx.index.max())
    va, us = float(idx.loc[last, "VA"]), float(idx.loc[last, "US"])
    gap = va - us
    thr = float(v["divergence_pts"])
    verdict = "ahead" if gap >= thr else ("behind" if gap <= -thr else "similar")
    rf = last - 3
    yoy = wide.pct_change().mul(100).dropna()
    return Ground(idx.reset_index(), wide.reset_index(), base, last, va - 100, us - 100, gap,
                  cagr_pct(wide.loc[base, "VA"], wide.loc[last, "VA"], last - base),
                  cagr_pct(wide.loc[base, "US"], wide.loc[last, "US"], last - base),
                  cagr_pct(wide.loc[rf, "VA"], wide.loc[last, "VA"], 3) if rf in wide.index else float("nan"),
                  cagr_pct(wide.loc[rf, "US"], wide.loc[last, "US"], 3) if rf in wide.index else float("nan"),
                  rf, verdict, yoy.reset_index())


@dataclass
class Sectors:
    sales: pd.DataFrame                 # period × RES/COM/IND (million kWh)
    price: pd.DataFrame                 # period × RES/COM/IND (cents/kWh)
    source_file: str
    first_year: int
    last_year: int

    def change_pct(self, frame: str, sector: str) -> float:
        d = getattr(self, frame)
        return (d.loc[self.last_year, sector] / d.loc[self.first_year, sector] - 1) * 100


def sectors(cfg: Mapping) -> Sectors | Unavailable:
    v = cfg["research"]["vol01"]["eia_sectors"]
    secs = list(v["sectors"])
    for path in inputs(cfg)["eia_sectors"]:
        df = _read_csv(path)
        if df is None or "price" not in df:
            continue
        df = df[(df.get("stateid", "US") == v["state"]) & df["sectorid"].isin(secs)].copy()
        df["period"] = df["period"].astype(int)
        df = df[df["period"] >= int(v["start"])]
        for c in ("sales", "price"):
            df[c] = df[c].map(to_number)
        sales = df.pivot_table(index="period", columns="sectorid", values="sales", aggfunc="first")
        price = df.pivot_table(index="period", columns="sectorid", values="price", aggfunc="first")
        if all(s in sales for s in secs) and len(sales) >= 3:
            return Sectors(sales[secs], price[secs], path.name, int(sales.index.min()), int(sales.index.max()))
    return Unavailable("EIA 미국 부문별 판매량·가격 없음", CMD_EIA_SECTORS, "EIA U.S. sales and prices by sector missing")


# ---------------------------------------------------------------------------
# III. 실적 (DART)
# ---------------------------------------------------------------------------
@dataclass
class Financials:
    table: pd.DataFrame                 # company, company_en, ticker, fiscal_year, fy(int), revenue, op, ni, opm, ni_yoy
    years: list[int]                    # 데이터가 있는 회계연도
    wanted: list[int]                   # config fiscal_years

    @property
    def missing_years(self) -> list[int]:
        return [y for y in self.wanted if y not in self.years]

    def value(self, ticker: str, fy: int, col: str) -> float | None:
        hit = self.table[(self.table["ticker"] == ticker) & (self.table["fy"] == fy)]
        if hit.empty or pd.isna(hit.iloc[0][col]):
            return None
        return float(hit.iloc[0][col])


def financials(cfg: Mapping) -> Financials | Unavailable:
    frames = [d for d in (_read_csv(p) for p in inputs(cfg)["dart"]) if d is not None]
    if not frames:
        return Unavailable("dart_financials.csv 없음", CMD_DART, "dart_financials.csv missing")
    df = pd.concat(frames, ignore_index=True)
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    df["fy"] = df["fiscal_year"].str[2:6].astype(int)
    for c in ("revenue", "operating_income", "net_income"):
        df[c] = df[c].map(to_number)
    df = df.drop_duplicates(["ticker", "fy"], keep="first").rename(columns={"operating_income": "op", "net_income": "ni"})
    names = {str(p["ticker"]).zfill(6): (p["name"], p.get("name_en", p["name"])) for p in cfg["peers"]["domestic"]}
    df = df[df["ticker"].isin(names)].copy()
    df["company"] = df["ticker"].map(lambda t: names[t][0])
    df["company_en"] = df["ticker"].map(lambda t: names[t][1])
    df = df.sort_values(["ticker", "fy"])
    df["opm"] = df["op"] / df["revenue"] * 100
    df["ni_yoy"] = df.groupby("ticker")["ni"].pct_change(fill_method=None) * 100
    prev = df.groupby("ticker")["ni"].shift(1)
    df.loc[(prev <= 0) | prev.isna(), "ni_yoy"] = float("nan")   # 직전 적자면 증가율 정의 안 함
    wanted = [int(y) for y in cfg["research"]["vol01"]["fiscal_years"]]
    years = sorted(set(df["fy"]) & set(wanted))
    order = [str(p["ticker"]).zfill(6) for p in cfg["peers"]["domestic"]]
    df["_o"] = df["ticker"].map(order.index)
    df = df.sort_values(["_o", "fy"]).drop(columns="_o").reset_index(drop=True)
    cols = ["company", "company_en", "ticker", "fiscal_year", "fy", "revenue", "op", "ni", "opm", "ni_yoy"]
    return Financials(df[cols], years, wanted)


# ---------------------------------------------------------------------------
# IV. 시장 (KRX) + 기업행위 + 분해
# ---------------------------------------------------------------------------
def _ymd(s: str) -> str:
    s = str(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


def corporate_actions(cfg: Mapping) -> pd.DataFrame:
    df = _read_csv(inputs(cfg)["corporate_actions"][0])
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "event_date", "action", "ratio", "shares_before", "shares_after"])
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    for c in ("ratio", "shares_before", "shares_after"):
        df[c] = df[c].map(to_number)
    return df


@dataclass
class Market:
    table: pd.DataFrame     # company, company_en, ticker, mcap_t0/t1, close_t0/t1, shares_t0/t1, multiple,
                            # price_multiple_raw, split_factor, price_multiple_adj, share_ratio, mcap_check_t0/t1 (%),
                            # action, action_date, share_note
    t0: str
    t1: str
    total_t0: float
    total_t1: float

    @property
    def total_multiple(self) -> float:
        return self.total_t1 / self.total_t0

    @property
    def mean_multiple(self) -> float:
        return float(self.table["multiple"].mean())

    @property
    def largest_t0(self) -> pd.Series:
        return self.table.sort_values("mcap_t0", ascending=False).iloc[0]

    @property
    def largest_t0_share(self) -> float:
        return float(self.largest_t0["mcap_t0"] / self.total_t0 * 100)

    @property
    def top(self) -> pd.Series:
        return self.table.sort_values("multiple", ascending=False).iloc[0]

    @property
    def bottom(self) -> pd.Series:
        return self.table.sort_values("multiple").iloc[0]


def market(cfg: Mapping) -> Market | Unavailable:
    df = _read_csv(inputs(cfg)["krx_points"][0])
    if df is None:
        return Unavailable("vol01_krx_mcap_points.csv 없음", CMD_KRX, "vol01_krx_mcap_points.csv missing")
    for c in ("market_cap_krw_100m", "close_krw", "listed_shares"):
        df[c] = df[c].map(to_number)
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    p0, p1 = df[df["point"] == "start_2023"].set_index("ticker"), df[df["point"] == "latest"].set_index("ticker")
    if p0.empty or p1.empty:
        return Unavailable("KRX 두 시점 중 하나 없음", CMD_KRX, "One of the two KRX dates is missing")
    t0, t1 = _ymd(p0.iloc[0]["bas_dd"]), _ymd(p1.iloc[0]["bas_dd"])
    acts = corporate_actions(cfg)
    rows = []
    for p in cfg["peers"]["domestic"]:
        t = str(p["ticker"]).zfill(6)
        if t not in p0.index or t not in p1.index:
            return Unavailable(f"KRX {p['name']} 시점 데이터 누락", CMD_KRX, f"KRX data missing for {p.get('name_en', p['name'])}")
        a, b = p0.loc[t], p1.loc[t]
        if any(pd.isna(x) for x in (a["market_cap_krw_100m"], b["market_cap_krw_100m"])):
            return Unavailable(f"KRX {p['name']} 시가총액 누락", CMD_KRX, f"KRX market cap missing for {p.get('name_en', p['name'])}")
        act = acts[(acts["ticker"] == t) & (acts["event_date"] > t0) & (acts["event_date"] <= t1)]
        split = float(act["ratio"].prod()) if not act.empty else 1.0
        share_ratio = b["listed_shares"] / a["listed_shares"]
        if not act.empty:
            note = "split_consistent" if abs(share_ratio / split - 1) < 0.005 else "split_mismatch"
        else:
            note = "unchanged" if abs(share_ratio - 1) < 1e-9 else "changed_unexplained"
        rows.append({
            "company": p["name"], "company_en": p.get("name_en", p["name"]), "ticker": t,
            "mcap_t0": a["market_cap_krw_100m"], "mcap_t1": b["market_cap_krw_100m"],
            "close_t0": a["close_krw"], "close_t1": b["close_krw"],
            "shares_t0": a["listed_shares"], "shares_t1": b["listed_shares"],
            "multiple": b["market_cap_krw_100m"] / a["market_cap_krw_100m"],
            "price_multiple_raw": b["close_krw"] / a["close_krw"], "split_factor": split,
            "price_multiple_adj": b["close_krw"] * split / a["close_krw"], "share_ratio": share_ratio,
            # 검산: 종가 × 상장주식수 ÷ 1억 vs KRX MKTCAP (%)
            "mcap_check_t0": (a["close_krw"] * a["listed_shares"] / 1e8 / a["market_cap_krw_100m"] - 1) * 100,
            "mcap_check_t1": (b["close_krw"] * b["listed_shares"] / 1e8 / b["market_cap_krw_100m"] - 1) * 100,
            "action": "; ".join(f"{r['action']} {r['ratio']:.0f}:1" for _, r in act.iterrows()),
            "action_date": "; ".join(act["event_date"]), "share_note": note,
        })
    t = pd.DataFrame(rows)
    return Market(t, t0, t1, float(t["mcap_t0"].sum()), float(t["mcap_t1"].sum()))


@dataclass
class Decomposition:
    """Δln(시총) = Δln(지배순이익) + Δln(PER).  PER = 시총 ÷ 지배순이익 (같은 시점 짝)."""
    table: pd.DataFrame     # company, ticker, mcap_t0/t1, ni0/ni1, per0/per1, dln_mcap, dln_ni, dln_per,
                            # earn_share, mult_share, valid, reason
    fy0: str
    fy1: str
    agg: dict               # mcap0, mcap1, ni0, ni1, per0, per1, dln_mcap, dln_ni, dln_per, earn_share, mult_share,
                            # d_mcap, earn_part, mult_part (억원, 로그 비중 배분)
    n_valid: int
    n_multiple_led: int     # 멀티플 기여가 이익 기여보다 큰 회사 수


def decompose(cfg: Mapping, mk: Market | Unavailable, fin: Financials | Unavailable) -> Decomposition | Unavailable:
    d = cfg["research"]["vol01"]["decomposition"]
    fy0, fy1 = int(d["fy_start"][2:6]), int(d["fy_end"][2:6])
    if not ok(mk):
        return Unavailable("KRX 두 시점 시가총액 없음", CMD_KRX, "KRX market caps for the two dates missing")
    if not ok(fin):
        return Unavailable("DART 재무 없음", CMD_DART, "DART financials missing")
    if fy0 not in fin.years:
        return Unavailable(f"{d['fy_start']} 지배순이익 없음 (2023년 초 시총과 짝)", CMD_DART,
                           f"{d['fy_start']} NI to parent missing (pairs with start-2023 market cap)")
    if fy1 not in fin.years:
        return Unavailable(f"{d['fy_end']} 지배순이익 없음", CMD_DART, f"{d['fy_end']} NI to parent missing")
    rows = []
    for _, r in mk.table.iterrows():
        ni0, ni1 = fin.value(r["ticker"], fy0, "ni"), fin.value(r["ticker"], fy1, "ni")
        valid = ni0 is not None and ni1 is not None and ni0 > 0 and ni1 > 0
        row = {"company": r["company"], "company_en": r["company_en"], "ticker": r["ticker"],
               "mcap_t0": r["mcap_t0"], "mcap_t1": r["mcap_t1"], "ni0": ni0, "ni1": ni1, "valid": valid,
               "reason": "" if valid else "적자 또는 이익 없음 → 분해 불가"}
        if valid:
            dm = math.log(r["mcap_t1"] / r["mcap_t0"])
            dn = math.log(ni1 / ni0)
            per0, per1 = r["mcap_t0"] / ni0, r["mcap_t1"] / ni1
            dp = math.log(per1 / per0)
            row.update(per0=per0, per1=per1, dln_mcap=dm, dln_ni=dn, dln_per=dp,
                       earn_share=dn / dm if dm else float("nan"), mult_share=dp / dm if dm else float("nan"))
        rows.append(row)
    t = pd.DataFrame(rows)
    v = t[t["valid"]]
    if v.empty:
        return Unavailable("분해 가능한 회사 없음 (지배순이익 적자)", CMD_DART, "No name can be split (negative NI)")
    m0, m1, n0, n1 = v["mcap_t0"].sum(), v["mcap_t1"].sum(), v["ni0"].sum(), v["ni1"].sum()
    dm, dn = math.log(m1 / m0), math.log(n1 / n0)
    dp = dm - dn
    d_mcap = m1 - m0
    agg = {"mcap0": m0, "mcap1": m1, "ni0": n0, "ni1": n1, "per0": m0 / n0, "per1": m1 / n1, "dln_mcap": dm,
           "dln_ni": dn, "dln_per": dp, "earn_share": dn / dm, "mult_share": dp / dm, "d_mcap": d_mcap,
           "earn_part": d_mcap * dn / dm, "mult_part": d_mcap * dp / dm, "n_in_agg": len(v)}
    return Decomposition(t, d["fy_start"], d["fy_end"], agg, len(v), int((v["dln_per"] > v["dln_ni"]).sum()))


@dataclass
class Valuation:
    """현재 PER (최근 시총 ÷ FY2025A 지배순이익) + 가용 데이터 기반 이익 증가(분해 전 잠정 비교)."""
    per: pd.DataFrame       # company, company_en, ticker, mcap_t1, ni, per
    agg_per: float
    median_per: float
    fy: str
    ni_growth: pd.DataFrame  # company, ticker, ni_from, ni_to, ni_multiple, mcap_multiple (가용 첫 연도 → FY2025A)
    growth_from: str


def valuation(cfg: Mapping, mk: Market | Unavailable, fin: Financials | Unavailable) -> Valuation | Unavailable:
    fy1 = int(cfg["research"]["vol01"]["decomposition"]["fy_end"][2:6])
    if not (ok(mk) and ok(fin)) or fy1 not in fin.years:
        return Unavailable("현재 PER 계산 불가 (KRX 또는 DART 없음)", CMD_KRX, "Current P/E unavailable (KRX or DART missing)")
    first = min(fin.years)
    rows, g = [], []
    for _, r in mk.table.iterrows():
        ni = fin.value(r["ticker"], fy1, "ni")
        rows.append({"company": r["company"], "company_en": r["company_en"], "ticker": r["ticker"],
                     "mcap_t1": r["mcap_t1"], "ni": ni, "per": r["mcap_t1"] / ni if ni and ni > 0 else float("nan")})
        n0 = fin.value(r["ticker"], first, "ni")
        g.append({"company": r["company"], "company_en": r["company_en"], "ticker": r["ticker"], "ni_from": n0,
                  "ni_to": ni, "ni_multiple": ni / n0 if n0 and ni and n0 > 0 else float("nan"),
                  "mcap_multiple": r["multiple"]})
    per = pd.DataFrame(rows)
    pos = per[per["ni"] > 0]
    return Valuation(per, float(pos["mcap_t1"].sum() / pos["ni"].sum()), float(pos["per"].median()),
                     f"FY{fy1}A", pd.DataFrame(g), f"FY{first}A")


# ---------------------------------------------------------------------------
# V. 금리 (리스크 렌즈)
# ---------------------------------------------------------------------------
@dataclass
class Rates:
    ktb10_t0: float | None
    ktb10_t1: float | None
    ust10_t0: float | None
    ust10_t1: float | None
    d0: str
    d1: str
    ust_d1: str | None


def _at_or_after(df: pd.DataFrame, col: str, date: str) -> float | None:
    s = df[df["date"] >= date][col].dropna()
    return float(s.iloc[0]) if not s.empty else None


def _at_or_before(df: pd.DataFrame, col: str, date: str) -> tuple[float | None, str | None]:
    s = df[df["date"] <= date][["date", col]].dropna()
    return (float(s.iloc[-1][col]), s.iloc[-1]["date"]) if not s.empty else (None, None)


def rates(cfg: Mapping, mk: Market | Unavailable, as_of: str) -> Rates | Unavailable:
    k, f = _read_csv(inputs(cfg)["ktb"][0]), _read_csv(inputs(cfg)["fred"][0])
    if k is None and f is None:
        return Unavailable("ECOS/FRED 금리 없음", "", "ECOS/FRED rates missing")
    d0 = mk.t0 if ok(mk) else "2023-01-02"
    d1 = mk.t1 if ok(mk) else as_of
    k10_0 = _at_or_after(k.assign(ktb_10y=k["ktb_10y"].map(to_number)), "ktb_10y", d0) if k is not None else None
    k10_1 = _at_or_before(k.assign(ktb_10y=k["ktb_10y"].map(to_number)), "ktb_10y", d1)[0] if k is not None else None
    u0 = _at_or_after(f.assign(DGS10=f["DGS10"].map(to_number)), "DGS10", d0) if f is not None else None
    u1, ud = _at_or_before(f.assign(DGS10=f["DGS10"].map(to_number)), "DGS10", d1) if f is not None else (None, None)
    return Rates(k10_0, k10_1, u0, u1, d0, d1, ud)


# ---------------------------------------------------------------------------
# 데이터 소스 상태 (A2)
# ---------------------------------------------------------------------------
SOURCES = [
    # id, 기관(KR), 기관(EN), API·경로(KR), 항목(KR), 항목(EN), 대표 파일 — API 영문은 API_EN
    ("dart", "DART · 금융감독원", "DART · FSS", "Open DART fnlttSinglAcntAll (사업보고서 11011, 연결 우선)",
     "4사 매출·영업이익·지배순이익", "Revenue, OP, NI to parent (4 peers)", "dart_financials.csv"),
    ("krx", "KRX · 한국거래소", "KRX · Korea Exchange", "KRX Open API stk_bydd_trd (유가증권 일별매매정보)",
     "종가·시가총액·상장주식수", "Close, market cap, listed shares", "vol01_krx_mcap_points.csv"),
    ("eia", "EIA · 미 에너지정보청", "EIA · U.S. EIA", "EIA API v2 electricity/retail-sales",
     "주별·부문별 판매량·가격", "Retail sales and price by state/sector", "vol01_eia_state.csv"),
    ("ecos", "ECOS · 한국은행", "ECOS · Bank of Korea", "ECOS StatisticSearch 817Y002 (시장금리 일별)",
     "국고채 3·10년, 원/달러", "KTB 3y/10y, USD/KRW", "ecos_ktb_daily.csv"),
    ("fred", "FRED · St. Louis Fed", "FRED · St. Louis Fed", "FRED series/observations", "DGS10, DEXKOUS",
     "DGS10, DEXKOUS", "fred_series.csv"),
    ("sec", "SEC EDGAR", "SEC EDGAR", "data.sec.gov companyfacts (XBRL)", "해외 peers 재무",
     "Overseas peers' financials", "sec_financials.csv"),
    ("iea", "IEA 보고서", "IEA reports", "수기 입력 (Energy and AI 2025.4, Key Questions 2026.4)",
     "데이터센터 전력 전망·증가율", "Data-centre power outlook and growth", "../manual/iea_energy_ai.csv"),
]


API_EN = {
    "dart": "Open DART fnlttSinglAcntAll (annual report 11011, consolidated first)",
    "krx": "KRX Open API stk_bydd_trd (KOSPI daily trading)",
    "eia": "EIA API v2 electricity/retail-sales",
    "ecos": "ECOS StatisticSearch 817Y002 (daily market rates)",
    "fred": "FRED series/observations",
    "sec": "data.sec.gov companyfacts (XBRL)",
    "iea": "Manual entry (Energy and AI Apr 2025, Key Questions Apr 2026)",
}


def source_status(cfg: Mapping) -> list[dict]:
    processed = resolve_path(cfg["paths"]["processed"])
    override = cfg["research"]["vol01"].get("source_status_override") or {}
    rows = []
    for sid, org_kr, org_en, api, item_kr, item_en, fname in SOURCES:
        path = (processed / fname).resolve()
        as_of = meta_as_of(path) if path.exists() else None
        if sid in override:
            st_kr, st_en, done = override[sid], "In progress", False
        elif path.exists():
            st_kr, st_en, done = ("원문 대조 완료" if sid == "iea" else "수집 완료"), (
                "Verified vs source" if sid == "iea" else "Collected"), True
        else:
            st_kr, st_en, done = "미수집", "Not collected", False
        rows.append({"id": sid, "org_kr": org_kr, "org_en": org_en, "api": api, "api_en": API_EN[sid], "item_kr": item_kr,
                     "item_en": item_en, "status_kr": st_kr, "status_en": st_en, "ok": done,
                     "as_of": as_of if done else None})
    return rows


def count_tests(root: Path | None = None) -> int:
    root = root or resolve_path("tests")
    return sum(Path(p).read_text(encoding="utf-8").count("\ndef test_") for p in root.glob("test_*.py"))


# ---------------------------------------------------------------------------
# 전체 묶음
# ---------------------------------------------------------------------------
@dataclass
class Facts:
    as_of: str
    demand: Demand | Unavailable
    ground: Ground | Unavailable
    sectors: Sectors | Unavailable
    fin: Financials | Unavailable
    market: Market | Unavailable
    decomp: Decomposition | Unavailable
    val: Valuation | Unavailable
    rates: Rates | Unavailable
    sources: list[dict] = field(default_factory=list)
    n_tests: int = 0


def load_facts(cfg: Mapping, as_of: str) -> Facts:
    mk, fin = market(cfg), financials(cfg)
    return Facts(as_of, demand(cfg), ground(cfg), sectors(cfg), fin, mk, decompose(cfg, mk, fin),
                 valuation(cfg, mk, fin), rates(cfg, mk, as_of), source_status(cfg), count_tests())
