"""Vol.2 데이터·가정 로드와 계산 (순수 함수). 보고서의 모든 숫자·서술 방향은 여기서 계산한다.

가정: config research.vol02.cases[*].params (master) + data/manual/vol02_assumptions.csv (사용자 입력, 우선).
값이 null인 가정이 계산에 필요하면 그 계산만 Unavailable(빠진 항목 목록)로 두고 보고서는 회색 박스로 표시한다.
Vol.1 데이터 연결: IEA 수요 → 램프업 시나리오, ECOS·FRED 금리, DART 피어 영업이익률 → CAPEX 스트레스, EIA 버지니아.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.analysis import pf_model as pf
from src.analysis import real_option as ro
from src.data_fetch.base import meta_path_for, resolve_path, to_number

CASES = ("A", "B")
SCENARIOS = ("downside", "base", "upside")
CSV_COLUMNS = ["case", "item", "value", "unit", "source_name", "url", "published", "page", "current", "hint"]

# 항목 이름 (국문, 영문) — 보고서 가정표·회색 박스 문구
LABELS: dict[str, tuple[str, str]] = {
    "phase1_mw": ("1단계 용량", "Phase 1 capacity"), "phase2_mw": ("2단계(옵션) 용량", "Phase 2 (option) capacity"),
    "capex_per_mw": ("MW당 CAPEX", "CAPEX per MW"), "power_equipment_share": ("CAPEX 중 전력설비 비중", "Power equipment share of CAPEX"),
    "construction_quarters": ("건설기간", "Construction period"), "rent_per_kw_month": ("임대료(kW·월)", "Rent (per kW-month)"),
    "rent_escalation": ("임대료 연 인상률", "Rent escalation"), "prelease": ("사전 임대율", "Pre-lease ratio"),
    "stabilized_occupancy": ("안정화 가동률", "Stabilised occupancy"), "ramp_elasticity": ("램프업 탄력성", "Ramp-up elasticity"),
    "opex_per_kw_year": ("OPEX(kW·년, 전력비 제외)", "OPEX (per kW-year, ex power)"), "opex_escalation": ("OPEX 연 인상률", "OPEX escalation"),
    "pue": ("PUE", "PUE"), "it_load_factor": ("IT 부하율", "IT load factor"), "power_price": ("전력 단가", "Power price"),
    "power_passthrough": ("전력비 패스스루 비율", "Power pass-through"), "tax_rate_national": ("법인세율(국세·연방)", "Corporate tax (national/federal)"),
    "tax_rate_local": ("지방세(지방소득세·주세)", "Local/state tax"), "tax_rate": ("법인세율(합산)", "Combined tax rate"), "dep_years": ("감가상각 기간", "Depreciation life"),
    "operating_years": ("운영기간", "Operating period"), "exit_cap_rate": ("잔존가치 cap rate", "Exit cap rate"),
    "margin_bp": ("가산금리", "Credit margin"), "target_dscr": ("목표 DSCR", "Target DSCR"), "max_gearing": ("최대 대출 비율", "Maximum gearing"),
    "tenor_years": ("대출 만기", "Loan tenor"), "grace_years": ("거치기간", "Grace period"), "grace_interest": ("거치기간 이자", "Grace-period interest"),
    "dsra_months": ("DSRA 개월 수", "DSRA months"), "discount_rate": ("할인율(자기자본)", "Discount rate (equity)"),
    "grid_approval_prob": ("추가 계통 승인 확률", "Grid-approval probability"), "approval_decision_year": ("승인 결정 시점", "Approval decision year"),
    "option_window_years": ("착공 대기 가능 기간", "Option window"), "rent_volatility": ("임대료 변동성", "Rent volatility"),
}

# PF 엔진에 반드시 필요한 항목
REQUIRED = ["phase1_mw", "capex_per_mw", "construction_quarters", "rent_per_kw_month", "rent_escalation", "prelease",
            "stabilized_occupancy", "ramp_elasticity", "opex_per_kw_year", "opex_escalation", "tax_rate", "dep_years",
            "operating_years", "margin_bp", "target_dscr", "max_gearing", "tenor_years", "grace_years", "dsra_months",
            "discount_rate"]
OPTION_REQUIRED = ["phase2_mw", "grid_approval_prob", "approval_decision_year", "option_window_years", "rent_volatility"]
PCT_UNITS = ("%", "%/년", "법인세 대비 %")


@dataclass
class Unavailable:
    """계산 생략 사유 + 필요한 입력 항목."""
    reason: str
    reason_en: str = ""
    missing: list[str] = field(default_factory=list)


def ok(x: Any) -> bool:
    return not isinstance(x, Unavailable)


# ---------------------------------------------------------------------------
# 가정 로드
# ---------------------------------------------------------------------------
@dataclass
class Assumption:
    case: str
    key: str
    value: Any
    unit: str
    tag: str | None = None
    source: str | None = None
    url: str | None = None
    published: str | None = None
    page: str | None = None
    todo: str | None = None
    low: float | None = None
    high: float | None = None
    origin: str = "config"          # config | csv | derived | data

    @property
    def missing(self) -> bool:
        return self.value is None

    @property
    def status(self) -> str:
        """보고서 표기용 상태: input(입력 필요) | sourced(출처 기재) | verify(원문 확인 필요) | data | design"""
        if self.value is None:
            return "input"
        if self.origin == "data":
            return "data"
        if self.url or self.page:
            return "sourced"
        if self.tag and "design" in self.tag:
            return "design"
        if self.tag and "neutral" in self.tag:
            return "neutral"
        return "verify"


def _is_pct(unit: str) -> bool:
    return unit in PCT_UNITS


def csv_to_value(raw: str, unit: str) -> Any:
    """CSV 값 → 내부 값. % 단위는 퍼센트로 입력(2.5 = 2.5%) → 소수, bp는 그대로, 텍스트는 그대로."""
    s = str(raw or "").strip()
    if s == "":
        return None
    n = to_number(s)
    if n != n:
        return s
    return n / 100.0 if _is_pct(unit) else n


def value_to_csv(v: Any, unit: str) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        x = v * 100 if _is_pct(unit) else v
        return f"{x:g}"
    return str(v)


def config_assumptions(cfg: Mapping) -> dict[str, dict[str, Assumption]]:
    out: dict[str, dict[str, Assumption]] = {}
    for case, spec in cfg["research"]["vol02"]["cases"].items():
        out[case] = {}
        for key, p in spec["params"].items():
            out[case][key] = Assumption(case, key, p.get("value"), p.get("unit", ""), p.get("tag"), p.get("source"),
                                        p.get("url"), p.get("published"), p.get("page"), p.get("todo"),
                                        p.get("low"), p.get("high"))
    return out


def read_csv_overrides(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("case") or "").strip()]


def load_assumptions(cfg: Mapping) -> dict[str, dict[str, Assumption]]:
    """config 가정 + CSV 사용자 입력(값·출처) 병합 + 파생값(사전 임대율 중간값, 세율 합산)."""
    a = config_assumptions(cfg)
    for r in read_csv_overrides(resolve_path(cfg["research"]["vol02"]["assumptions_csv"])):
        case, key = r["case"].strip(), r["item"].strip()
        if case not in a or key not in a[case]:
            continue
        cur = a[case][key]
        v = csv_to_value(r.get("value"), cur.unit)
        if v is not None:
            cur.value, cur.origin = v, "csv"
            cur.tag = "user"
        for k_csv, k_attr in (("source_name", "source"), ("url", "url"), ("published", "published"), ("page", "page")):
            if (r.get(k_csv) or "").strip():
                setattr(cur, k_attr, r[k_csv].strip())
    for case, d in a.items():
        p = d.get("prelease")
        if p is not None and p.value is None and p.low is not None and p.high is not None:
            p.value, p.origin = (p.low + p.high) / 2, "derived"
        d["tax_rate"] = combined_tax(case, d)
    return a


def combined_tax(case: str, d: Mapping[str, Assumption]) -> Assumption:
    """A: 법인세 × (1 + 지방소득세 비율). B: 연방 + 주 × (1 − 연방) (주세는 연방 과세소득에서 공제)."""
    n, l = d.get("tax_rate_national"), d.get("tax_rate_local")
    if n is None or l is None or n.value is None or l.value is None:
        return Assumption(case, "tax_rate", None, "%", todo="법인세율 입력 필요", origin="derived")
    v = n.value * (1 + l.value) if case == "A" else n.value + l.value * (1 - n.value)
    return Assumption(case, "tax_rate", v, "%", tag="derived", source="국세 + 지방세 합산", origin="derived")


def write_template(cfg: Mapping, path: Path | None = None) -> Path:
    """data/manual/vol02_assumptions.csv 양식 생성·갱신. 사용자가 채운 value·출처 칸은 보존한다."""
    path = path or resolve_path(cfg["research"]["vol02"]["assumptions_csv"])
    old = {(r["case"], r["item"]): r for r in read_csv_overrides(path)}
    eff = load_assumptions(cfg)
    rows = []
    for case, d in config_assumptions(cfg).items():
        for key, a in d.items():
            prev = old.get((case, key), {})
            cur = eff[case][key]
            rows.append({
                "case": case, "item": key, "value": prev.get("value", ""), "unit": a.unit,
                "source_name": prev.get("source_name", ""), "url": prev.get("url", ""),
                "published": prev.get("published", ""), "page": prev.get("page", ""),
                "current": value_to_csv(cur.value, a.unit) if cur.value is not None else "null",
                "hint": " / ".join(x for x in (LABELS.get(key, (key,))[0], a.source or "", a.todo or "") if x),
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# Vol.1 데이터 연결
# ---------------------------------------------------------------------------
def _read(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, dtype={"ticker": str, "period": str}, keep_default_na=False, encoding="utf-8-sig")


def _inp(cfg: Mapping, key: str) -> list[Path]:
    v = cfg["research"]["vol02"]["inputs"][key]
    return [resolve_path(p) for p in (v if isinstance(v, list) else [v])]


def meta_as_of(path: Path) -> str | None:
    m = meta_path_for(path)
    if not m.exists():
        return None
    d = json.loads(m.read_text(encoding="utf-8"))
    return d.get("verified_on") or d.get("as_of")


def cagr(a: float, b: float, years: float) -> float:
    return (b / a) ** (1 / years) - 1 if a > 0 and b > 0 and years > 0 else float("nan")


@dataclass
class Demand:
    values: dict[str, float]            # base_year, downside, base, upside (TWh)
    years: tuple[int, int]
    growth: dict[str, float]            # 시나리오 → 연평균 성장률 (소수)
    near_term: dict[str, float]         # dc_2025, ai_2025 (%), base_2030 cagr
    as_of: str | None


def demand(cfg: Mapping) -> Demand | Unavailable:
    v2 = cfg["research"]["vol02"]["demand_scenarios"]
    path = _inp(cfg, "iea")[0]
    df = _read(path)
    if df is None:
        return Unavailable("IEA 수요 데이터 없음", "IEA demand data missing")

    def get(metric: str, period: str) -> float | None:
        hit = df[(df["metric"] == metric) & (df["period"].astype(str) == str(period))]
        x = to_number(hit.iloc[0]["value"]) if not hit.empty else float("nan")
        return None if x != x else x
    vals = {k: get(v2[k]["metric"], v2[k]["period"]) for k in ("base_year", *SCENARIOS)}
    if any(x is None for x in vals.values()):
        return Unavailable("IEA 시나리오 값 누락", "IEA scenario values missing")
    y0, y1 = int(v2["base_year"]["period"]), int(v2["base"]["period"])
    growth = {s: cagr(vals["base_year"], vals[s], y1 - y0) for s in SCENARIOS}
    near = {"dc_2025": get("dc_demand_growth_yoy", "2025"), "ai_2025": get("ai_dc_demand_growth_yoy", "2025"),
            "base_2030": get("dc_electricity_consumption_base", "2030")}
    if near["base_2030"]:
        near["cagr_2024_2030"] = cagr(vals["base_year"], near["base_2030"], 2030 - y0)
    return Demand(vals, (y0, y1), growth, near, meta_as_of(path))


@dataclass
class Rates:
    as_of: str
    ktb_3y: float | None
    ktb_10y: float | None
    ktb_date: str | None
    dgs10: float | None
    dgs10_date: str | None
    usdkrw: float | None
    fx_date: str | None
    monthly: pd.DataFrame               # month, ktb_3y, ktb_10y, DGS10 (월평균, %)

    def base(self, case: str, which: str, cfg: Mapping) -> float | None:
        series = cfg["research"]["vol02"]["rates"][case][which]
        v = {"ktb_3y": self.ktb_3y, "ktb_10y": self.ktb_10y, "DGS10": self.dgs10}[series]
        return None if v is None else v / 100.0


def _on_or_before(df: pd.DataFrame | None, col: str, date: str) -> tuple[float | None, str | None]:
    if df is None or col not in df:
        return None, None
    s = df.assign(**{col: df[col].map(to_number)})
    s = s[(s["date"] <= date) & s[col].notna()]
    return (float(s.iloc[-1][col]), str(s.iloc[-1]["date"])) if not s.empty else (None, None)


def rates(cfg: Mapping, as_of: str) -> Rates | Unavailable:
    k, f, x = _read(_inp(cfg, "ktb")[0]), _read(_inp(cfg, "fred")[0]), _read(_inp(cfg, "fx")[0])
    if k is None and f is None:
        return Unavailable("ECOS·FRED 금리 없음", "ECOS/FRED rates missing")
    k3, kd = _on_or_before(k, "ktb_3y", as_of)
    k10, _ = _on_or_before(k, "ktb_10y", as_of)
    d10, dd = _on_or_before(f, "DGS10", as_of)
    fx, fd = _on_or_before(x, "usdkrw", as_of)
    frames = []
    for df, cols in ((k, ["ktb_3y", "ktb_10y"]), (f, ["DGS10"])):
        if df is not None:
            m = df[["date", *cols]].copy()
            for c in cols:
                m[c] = m[c].map(to_number)
            m["month"] = m["date"].str[:7]
            frames.append(m[m["date"] <= as_of].groupby("month")[cols].mean())
    monthly = pd.concat(frames, axis=1).reset_index() if frames else pd.DataFrame()
    return Rates(as_of, k3, k10, kd, d10, dd, fx, fd, monthly)


@dataclass
class PeerPricing:
    table: pd.DataFrame                 # company, company_en, ticker, opm0, opm1, implied (소수)
    agg_opm0: float
    agg_opm1: float
    agg_implied: float
    fy0: str
    fy1: str

    @property
    def low(self) -> float:
        return float(self.table["implied"].min())

    @property
    def high(self) -> float:
        return float(self.table["implied"].max())

    def scenarios(self) -> dict[str, float]:
        return {"low": self.low, "mid": self.agg_implied, "high": self.high}


def implied_price_rise(opm0: float, opm1: float) -> float:
    """영업이익률 상승이 모두 가격에서 왔고 단위 원가는 그대로라고 볼 때의 가격 상승률 (상한값).

    OPM = 1 − 원가/매출 → 원가 고정, 가격 (1+x)배: OPM1 = 1 − (1 − OPM0)/(1+x) → x = (1 − OPM0)/(1 − OPM1) − 1
    """
    return (1 - opm0) / (1 - opm1) - 1


def peer_pricing(cfg: Mapping) -> PeerPricing | Unavailable:
    cs = cfg["research"]["vol02"]["capex_stress"]
    frames = [d for d in (_read(p) for p in _inp(cfg, "dart")) if d is not None]
    if not frames:
        return Unavailable("DART 재무 없음", "DART financials missing")
    df = pd.concat(frames, ignore_index=True)
    df["ticker"] = df["ticker"].astype(str).str.zfill(6)
    for c in ("revenue", "operating_income"):
        df[c] = df[c].map(to_number)
    names = {str(p["ticker"]).zfill(6): (p["name"], p.get("name_en", p["name"])) for p in cfg["peers"]["domestic"]}
    rows, r0, o0, r1, o1 = [], 0.0, 0.0, 0.0, 0.0
    for t in cs["peers"]:
        a = df[(df["ticker"] == t) & (df["fiscal_year"] == cs["fy_start"])]
        b = df[(df["ticker"] == t) & (df["fiscal_year"] == cs["fy_end"])]
        if a.empty or b.empty:
            return Unavailable(f"{names.get(t, (t,))[0]} {cs['fy_start']}·{cs['fy_end']} 영업이익 없음",
                               f"{names.get(t, (t, t))[1]} operating income missing")
        a, b = a.iloc[0], b.iloc[0]
        opm0, opm1 = a["operating_income"] / a["revenue"], b["operating_income"] / b["revenue"]
        rows.append({"company": names[t][0], "company_en": names[t][1], "ticker": t, "opm0": opm0, "opm1": opm1,
                     "implied": implied_price_rise(opm0, opm1)})
        r0, o0, r1, o1 = r0 + a["revenue"], o0 + a["operating_income"], r1 + b["revenue"], o1 + b["operating_income"]
    return PeerPricing(pd.DataFrame(rows), o0 / r0, o1 / r1, implied_price_rise(o0 / r0, o1 / r1), cs["fy_start"], cs["fy_end"])


@dataclass
class Virginia:
    index: pd.DataFrame                 # period, VA, US (기준연도 = 100)
    base_year: int
    last_year: int
    va_cagr: float
    us_cagr: float
    va_yoy_last: float
    us_price: pd.Series                 # 미국 상업용 평균 요금 (cents/kWh)
    va_price: pd.Series | None          # 버지니아 상업용 요금 (수집 시)
    price_source: str                   # "VA" | "US"

    @property
    def price_latest(self) -> tuple[int, float]:
        s = self.va_price if self.va_price is not None else self.us_price
        return int(s.index.max()), float(s.iloc[-1])


def virginia(cfg: Mapping) -> Virginia | Unavailable:
    df = _read(_inp(cfg, "eia_state")[0])
    if df is None:
        return Unavailable("EIA 버지니아 판매량 없음", "EIA Virginia sales missing")
    df = df[df["sectorid"] == "COM"].copy()
    df["period"] = df["period"].astype(int)
    df["sales"] = df["sales"].map(to_number)
    w = df.pivot_table(index="period", columns="stateid", values="sales", aggfunc="first")[["VA", "US"]].dropna()
    y0, y1 = int(w.index.min()), int(w.index.max())
    idx = w.div(w.loc[y0]).mul(100).reset_index()
    us_price = None
    for p in _inp(cfg, "eia_sectors"):
        s = _read(p)
        if s is None or "price" not in s:
            continue
        s = s[(s.get("stateid", "US") == "US") & (s["sectorid"] == "COM")].copy()
        s["period"] = s["period"].astype(int)
        s = s[s["period"] >= y0]
        if len(s) >= 3:
            us_price = s.set_index("period")["price"].map(to_number).sort_index()
            break
    if us_price is None:
        return Unavailable("EIA 미국 상업용 요금 없음", "EIA U.S. commercial price missing")
    va_price, src = None, "US"
    vp = _read(_inp(cfg, "eia_va_price")[0])
    if vp is not None and "price" in vp:
        vp = vp[(vp["stateid"] == "VA") & (vp["sectorid"] == "COM")].copy()
        if len(vp):
            vp["period"] = vp["period"].astype(int)
            va_price, src = vp.set_index("period")["price"].map(to_number).sort_index(), "VA"
    yoy = w.pct_change().iloc[-1]
    return Virginia(idx, y0, y1, cagr(w.loc[y0, "VA"], w.loc[y1, "VA"], y1 - y0), cagr(w.loc[y0, "US"], w.loc[y1, "US"], y1 - y0),
                    float(yoy["VA"]), us_price, va_price, src)


@dataclass
class GridStats:
    applied: float | None
    approved: float | None
    memo_pct: float | None
    threshold_mw: float | None
    period: str

    @property
    def ratio(self) -> float | None:
        return self.approved / self.applied if self.applied and self.approved is not None else None

    @property
    def memo_mismatch(self) -> bool:
        return self.ratio is not None and self.memo_pct is not None and abs(self.ratio * 100 - self.memo_pct) > 0.15


def grid_stats(cfg: Mapping) -> GridStats:
    g = cfg["research"]["vol02"]["grid_stats"]
    return GridStats(g["applied_mw"]["value"], g["approved_mw"]["value"], g.get("memo_ratio_pct"),
                     g["review_threshold_mw"]["value"], g["period"])


# ---------------------------------------------------------------------------
# 케이스 → PF 입력 → 결과
# ---------------------------------------------------------------------------
def missing_items(a: Mapping[str, Assumption], keys: list[str]) -> list[str]:
    return [k for k in keys if k not in a or a[k].value is None]


def case_power_price(case: str, a: Mapping[str, Assumption], va: Virginia | Unavailable) -> Assumption:
    """B: 사용자 값이 없으면 EIA 상업용 평균 요금(버지니아, 없으면 미국)을 USD/kWh로 사용."""
    p = a["power_price"]
    if p.value is not None or case != "B" or not ok(va):
        return p
    year, cents = va.price_latest
    who = "Virginia" if va.price_source == "VA" else "U.S. (proxy)"
    return replace(p, value=cents / 100.0, origin="data", tag="DATA",
                   source=f"EIA commercial average price, {who}, {year}")


def pf_inputs(cfg: Mapping, case: str, a: Mapping[str, Assumption], r: Rates | Unavailable, growth: float,
              mw_key: str = "phase1_mw") -> pf.PFInputs | Unavailable:
    miss = missing_items(a, REQUIRED + ([mw_key] if mw_key != "phase1_mw" else []))
    if not ok(r):
        return Unavailable("기준금리 데이터 없음", "Base-rate data missing", ["base_rate"])
    rc, rt = r.base(case, "construction", cfg), r.base(case, "term", cfg)
    if rc is None or rt is None:
        miss.append("base_rate")
    if miss:
        return Unavailable("입력 필요", "Inputs needed", miss)
    v = {k: x.value for k, x in a.items()}
    spec = cfg["research"]["vol02"]["cases"][case]

    def opt(k):
        return v.get(k)
    try:
        return pf.PFInputs(
            mw=float(v[mw_key]), capex_per_mw=float(v["capex_per_mw"]), construction_quarters=int(v["construction_quarters"]),
            rent_per_kw_month=float(v["rent_per_kw_month"]), money_scale=float(spec["money_scale"]),
            rent_escalation=float(v["rent_escalation"]), prelease=float(v["prelease"]),
            stabilized_occupancy=float(v["stabilized_occupancy"]), ramp_growth=growth,
            ramp_elasticity=float(v["ramp_elasticity"]), opex_per_kw_year=float(v["opex_per_kw_year"]),
            opex_escalation=float(v["opex_escalation"]), tax_rate=float(v["tax_rate"]), dep_years=int(v["dep_years"]),
            operating_years=int(v["operating_years"]), base_rate_construction=rc, base_rate_term=rt,
            margin=float(v["margin_bp"]) / 10000.0, target_dscr=float(v["target_dscr"]), max_gearing=float(v["max_gearing"]),
            tenor_years=int(v["tenor_years"]), grace_years=int(v["grace_years"]), dsra_months=float(v["dsra_months"]),
            discount_rate=float(v["discount_rate"]), power_passthrough=float(opt("power_passthrough") or 1.0),
            power_price=opt("power_price"), pue=opt("pue"), it_load_factor=opt("it_load_factor"),
            exit_cap_rate=opt("exit_cap_rate"), grace_interest=str(opt("grace_interest") or "paid"))
    except ValueError as e:
        return Unavailable(f"입력값 오류: {e}", f"Invalid inputs: {e}", [])


@dataclass
class CaseResult:
    case: str
    inp: pf.PFInputs
    base: pf.PFResult
    scenarios: dict[str, pf.PFResult]           # 시나리오별 sizing
    stresses: dict[str, pf.PFResult]            # 이름 → 고정 대출 스트레스 결과
    tornado: pd.DataFrame
    breakeven: pd.DataFrame                     # variable, level(1.0|target), value
    heatmap: pd.DataFrame | None
    capex_stress: dict[str, float] | Unavailable   # 시나리오(low/mid/high) → CAPEX 배수
    power: dict | None                          # 전력비 통계 (모델링 가능 시)
    checks: dict[str, float]
    tax_timing: list[str] = field(default_factory=list)   # 유리한 쪽 < 기준인 변수 중 세율 0 재계산으로 원인 확인된 것
    heatmap_tax_timing: bool = False            # 히트맵의 유리한 칸(임대료↑·CAPEX↓)이 기준보다 낮은 원인이 세금 시점인지


def capex_multipliers(a: Mapping[str, Assumption], pp: PeerPricing | Unavailable) -> dict[str, float] | Unavailable:
    """CAPEX 배수 = 1 + 전력설비 비중 × 피어 함의 가격 상승률 (저·중·고)."""
    share = a["power_equipment_share"].value
    if share is None or not ok(pp):
        return Unavailable("전력설비 비중 입력 필요" if share is None else "피어 데이터 없음",
                           "Power-equipment share needed" if share is None else "Peer data missing",
                           ["power_equipment_share"] if share is None else [])
    return {k: 1 + share * x for k, x in pp.scenarios().items()}


def run_case(cfg: Mapping, case: str, a: Mapping[str, Assumption], r: Rates | Unavailable, d: Demand | Unavailable,
             pp: PeerPricing | Unavailable) -> CaseResult | Unavailable:
    if not ok(d):
        return Unavailable("수요 시나리오 없음", "Demand scenarios missing", ["iea"])
    inp = pf_inputs(cfg, case, a, r, d.growth["base"])
    if not ok(inp):
        return inp
    base = pf.run(inp)
    scen = {s: (base if s == "base" else pf.run(replace(inp, ramp_growth=d.growth[s]))) for s in SCENARIOS}
    sc = cfg["research"]["vol02"]["sensitivity"]
    rp, op_, bp = float(sc["rent_pct"]), float(sc["occupancy_pct"]), float(sc["rate_bp"]) / 10000
    pre = a["prelease"]
    cm = capex_multipliers(a, pp)
    st = {
        "rent_down": pf.Stress(rent_mult=1 - rp), "rent_up": pf.Stress(rent_mult=1 + rp),
        "occ_down": pf.Stress(occ_mult=1 - op_), "occ_up": pf.Stress(occ_mult=1 + op_),
        "rate_up": pf.Stress(rate_shift=bp), "rate_down": pf.Stress(rate_shift=-bp),
    }
    for q in sc["delay_quarters"]:
        st[f"delay_{q}"] = pf.Stress(delay_quarters=int(q))
    if pre.low is not None and pre.high is not None:
        st["prelease_low"], st["prelease_high"] = pf.Stress(prelease=pre.low), pf.Stress(prelease=pre.high)
    if ok(cm):
        for k, m in cm.items():
            st[f"capex_{k}"] = pf.Stress(capex_mult=m)
    stresses = {k: pf.stress(base, s) for k, s in st.items()}
    torn_cases = {"rent": (st["rent_down"], st["rent_up"]), "occupancy": (st["occ_down"], st["occ_up"]),
                  "rate": (st["rate_up"], st["rate_down"]),
                  "delay": (st[f"delay_{max(sc['delay_quarters'])}"], pf.BASE)}
    if "prelease_low" in st:
        torn_cases["prelease"] = (st["prelease_low"], st["prelease_high"])
    if ok(cm):
        torn_cases["capex"] = (st["capex_high"], pf.BASE)
    torn = pf.tornado(base, torn_cases)
    rng = sc["breakeven_ranges"]
    be_rows = []
    near = {"rent_mult": 1.0, "occ_mult": 1.0, "prelease": inp.prelease, "capex_mult": 1.0, "rate_shift": 0.0,
            "delay_quarters": 0.0}
    at_target = abs(base.min_dscr - inp.target_dscr) < 1e-6      # sculpting으로 기준 = 목표 → 목표 손익분기는 기준값
    for var in near:
        lo, hi = rng[var]
        for level in (1.0, inp.target_dscr):
            if level == inp.target_dscr and at_target:
                be_rows.append({"variable": var, "level": level, "value": float("nan"), "at_target": True})
                continue
            be_rows.append({"variable": var, "level": level, "at_target": False,
                            "value": pf.breakeven(base, var, level, lo, hi, near=near[var])})
    be = pd.DataFrame(be_rows)
    hm = pf.heatmap(base, sc["heatmap"]["rent_mult"], sc["heatmap"]["capex_mult"]) if case == "A" else None
    power = None
    if inp.power_modeled():
        o = base.ops
        power = {"power_cost_y1": float(o["power_cost"].iloc[0]), "rent_y1": float(o["revenue"].iloc[0]),
                 "share_of_tenant_cost": float(o["power_cost"].iloc[0] / (o["power_cost"].iloc[0] + o["revenue"].iloc[0]))}
    # 유리한 스트레스가 최소 DSCR을 낮추는 경우: 세율 0으로 다시 계산해 법인세 시점 효과인지 확인
    tax_timing = []
    anomalies = [r_["variable"] for _, r_ in torn.iterrows() if r_["high"] < r_["base"] - 1e-6]
    if anomalies and inp.tax_rate > 0:
        b0 = pf.run(replace(inp, tax_rate=0.0))
        for var in anomalies:
            fav = torn_cases[var][1]
            if pf.stress(b0, fav).min_dscr >= b0.min_dscr - 1e-6:
                tax_timing.append(var)
    hm_tt = False
    if hm is not None and inp.tax_rate > 0:
        odd = [(r_, c_) for r_ in hm.index for c_ in hm.columns
               if r_ >= 1 and c_ <= 1 and (r_, c_) != (1.0, 1.0) and hm.loc[r_, c_] < base.min_dscr - 1e-6]
        if odd:
            b0 = pf.run(replace(inp, tax_rate=0.0))
            r_, c_ = odd[0]
            hm_tt = pf.stress(b0, pf.Stress(rent_mult=r_, capex_mult=c_)).min_dscr >= b0.min_dscr - 1e-6
    return CaseResult(case, inp, base, scen, stresses, torn, be, hm, cm, power, pf.identity_checks(base), tax_timing, hm_tt)


@dataclass
class OptionFacts:
    result: ro.OptionResult
    inputs: ro.OptionInputs
    grid_ratio: float | None


def run_option(cfg: Mapping, a: Mapping[str, Assumption], r: Rates | Unavailable, d: Demand | Unavailable,
               case_res: CaseResult | Unavailable, gs: GridStats) -> OptionFacts | Unavailable:
    if not ok(case_res):
        return Unavailable("케이스 A 모델 입력 필요", "Case A model inputs needed", list(getattr(case_res, "missing", [])))
    miss = missing_items(a, OPTION_REQUIRED)
    if miss:
        return Unavailable("입력 필요", "Inputs needed", miss)
    if not a["phase2_mw"].value:
        return Unavailable("2단계 용량 0", "Phase 2 capacity is zero", ["phase2_mw"])
    roc = cfg["research"]["vol02"]["real_option"]
    p2 = replace(case_res.inp, mw=float(a["phase2_mw"].value))
    w = cfg["research"]["vol02"]["demand_scenarios"]["weights"]
    oi = ro.OptionInputs(p2, case_res.inp.prelease, dict(d.growth), {k: float(w[k]) for k in SCENARIOS},
                         float(a["grid_approval_prob"].value), int(a["approval_decision_year"].value),
                         int(a["option_window_years"].value), float(a["rent_volatility"].value),
                         int(roc["n_paths"]), int(roc["seed"]), int(roc["basis_degree"]))
    res = ro.value(oi, roc["prob_grid"], roc["convergence_paths"])
    return OptionFacts(res, oi, gs.ratio)


# ---------------------------------------------------------------------------
# 데이터 소스 상태
# ---------------------------------------------------------------------------
SOURCES = [
    ("iea", "IEA", "IEA", "Energy and AI (2025.4), Key Questions on Energy and AI (2026.4)",
     "Energy and AI (Apr 2025), Key Questions on Energy and AI (Apr 2026)", "데이터센터 전력 2024·2035 시나리오", "Data-centre power, 2024 and 2035 scenarios", "iea"),
    ("ecos", "ECOS · 한국은행", "ECOS · Bank of Korea", "시장금리(일별), 주요국 통화의 대원화환율", "Market rates (daily), KRW exchange rates",
     "국고채 3·10년, 원/달러", "KTB 3y/10y, USD/KRW", "ktb"),
    ("fred", "FRED · St. Louis Fed", "FRED · St. Louis Fed", "10-Year Treasury Constant Maturity (DGS10)",
     "10-Year Treasury Constant Maturity (DGS10)", "미 국채 10년", "UST 10y", "fred"),
    ("dart", "DART · 금융감독원", "DART · FSS", "사업보고서 연결 재무제표", "Annual reports, consolidated", "피어 3사 매출·영업이익",
     "Three peers' revenue and operating income", "dart"),
    ("eia", "EIA · 미 에너지정보청", "EIA · U.S. EIA", "Electricity retail sales (주별·부문별, 연간)", "Electricity retail sales (state/sector, annual)",
     "버지니아·미국 상업용 판매량·요금", "Virginia and U.S. commercial sales and price", "eia_state"),
]


def source_status(cfg: Mapping, va: Virginia | Unavailable) -> list[dict]:
    rows = []
    for sid, org_kr, org_en, ds_kr, ds_en, it_kr, it_en, key in SOURCES:
        path = _inp(cfg, key)[0]
        rows.append({"id": sid, "org_kr": org_kr, "org_en": org_en, "ds_kr": ds_kr, "ds_en": ds_en, "item_kr": it_kr,
                     "item_en": it_en, "as_of": meta_as_of(path) if path.exists() else None, "ok": path.exists()})
    vp = _inp(cfg, "eia_va_price")[0]
    rows.append({"id": "eia_va_price", "org_kr": "EIA · 미 에너지정보청", "org_en": "EIA · U.S. EIA",
                 "ds_kr": "Electricity retail sales (버지니아 상업용 요금)", "ds_en": "Electricity retail sales (Virginia commercial price)",
                 "item_kr": "버지니아 상업용 평균 요금", "item_en": "Virginia commercial average price",
                 "as_of": meta_as_of(vp) if vp.exists() else None, "ok": vp.exists()})
    return rows


# ---------------------------------------------------------------------------
# 전체 묶음
# ---------------------------------------------------------------------------
@dataclass
class Facts:
    as_of: str
    assumptions: dict[str, dict[str, Assumption]]
    demand: Demand | Unavailable
    rates: Rates | Unavailable
    peers: PeerPricing | Unavailable
    va: Virginia | Unavailable
    grid: GridStats
    cases: dict[str, CaseResult | Unavailable]
    option: OptionFacts | Unavailable
    sources: list[dict]

    def fx(self) -> float | None:
        return self.rates.usdkrw if ok(self.rates) else None


def load_facts(cfg: Mapping, as_of: str | None = None) -> Facts:
    v = cfg["research"]["vol02"]
    as_of = as_of or v["as_of"]
    a = load_assumptions(cfg)
    d, r, pp, va = demand(cfg), rates(cfg, as_of), peer_pricing(cfg), virginia(cfg)
    for case in a:
        a[case]["power_price"] = case_power_price(case, a[case], va)
    gs = grid_stats(cfg)
    cases = {c: run_case(cfg, c, a[c], r, d, pp) for c in CASES if c in a}
    opt = run_option(cfg, a["A"], r, d, cases.get("A", Unavailable("")), gs) if "A" in a else Unavailable("")
    return Facts(as_of, a, d, r, pp, va, gs, cases, opt, source_status(cfg, va))


def fmt_missing(keys: list[str], kr: bool = True) -> str:
    return ", ".join(LABELS.get(k, ("기준금리", "base rate") if k == "base_rate" else (k, k))[0 if kr else 1] for k in keys)


def finite(x: Any) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)
