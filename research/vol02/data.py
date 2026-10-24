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
CSV_COLUMNS = ["case", "item", "value", "low", "high", "unit", "tag", "source_name", "url", "published", "page", "current", "hint"]
TAG_SOURCED, TAG_JUDGMENT = "ASSUMPTION(sourced)", "ASSUMPTION(judgment)"

# 항목 이름 (국문, 영문) — 보고서 가정표·회색 박스 문구
LABELS: dict[str, tuple[str, str]] = {
    "phase1_mw": ("1단계 용량", "Phase 1 capacity"), "phase2_mw": ("2단계(옵션) 용량", "Phase 2 (option) capacity"),
    "capex_per_mw": ("MW당 CAPEX", "CAPEX per MW"), "power_equipment_share": ("CAPEX 중 전력설비 비중", "Power equipment share of CAPEX"),
    "construction_quarters": ("건설기간", "Construction period"), "rent_per_kw_month": ("임대료(kW·월)", "Rent (per kW-month)"),
    "rent_escalation": ("임대료 연 인상률", "Rent escalation"), "prelease": ("사전 임대율", "Pre-lease ratio"),
    "stabilized_occupancy": ("안정화 가동률", "Stabilised occupancy"), "ramp_elasticity": ("램프업 탄력성", "Ramp-up elasticity"),
    "opex_per_kw_year": ("OPEX 고정분(kW·년, 전력비 제외)", "Fixed OPEX (per kW-year, ex power)"),
    "opex_ratio": ("OPEX(안정화 매출 대비, 전력비 제외)", "OPEX (% of stabilised revenue, ex power)"),
    "opex_escalation": ("OPEX 연 인상률", "OPEX escalation"), "ramp_years": ("램프업 기간", "Ramp-up period"),
    "lease_term_years": ("임대 계약 기간", "Lease term"), "tenor_basis": ("만기 기준", "Tenor basis"),
    "tax_brackets": ("법인세 누진세율(국세)", "Corporate tax brackets (national)"),
    "pue": ("PUE", "PUE"), "it_load_factor": ("IT 부하율", "IT load factor"), "power_price": ("전력 단가", "Power price"),
    "power_passthrough": ("전력비 패스스루 비율", "Power pass-through"),
    "power_escalation": ("전력단가 연 인상률", "Power price escalation"),
    "capex_yoy_change": ("AI 사양 공사비 1년 상승률", "AI-spec build cost, 1-yr change"), "tax_rate_national": ("법인세율(국세·연방)", "Corporate tax (national/federal)"),
    "tax_rate_local": ("지방세(지방소득세·주세)", "Local/state tax"), "tax_rate": ("법인세율(합산)", "Combined tax rate"), "dep_years": ("감가상각 기간", "Depreciation life"),
    "operating_years": ("운영기간", "Operating period"), "exit_cap_rate": ("잔존가치 cap rate", "Exit cap rate"),
    "margin_bp": ("가산금리", "Credit margin"), "target_dscr": ("목표 DSCR", "Target DSCR"), "max_gearing": ("최대 대출 비율", "Maximum gearing"),
    "tenor_years": ("대출 만기", "Loan tenor"), "grace_years": ("거치기간(COD 후)", "Grace period (after COD)"), "grace_interest": ("거치기간 이자", "Grace-period interest"),
    "interest_reserve_buffer": ("이자유보계좌 여유율", "Interest-reserve buffer"),
    "dsra_months": ("DSRA 개월 수", "DSRA months"), "discount_rate": ("할인율(자기자본)", "Discount rate (equity)"),
    "grid_approval_prob": ("추가 계통 승인 확률", "Grid-approval probability"), "approval_decision_year": ("승인 결정 시점", "Approval decision year"),
    "option_window_years": ("착공 대기 가능 기간", "Option window"), "rent_volatility": ("임대료 변동성", "Rent volatility"),
}

# PF 엔진에 반드시 필요한 항목
# (감가상각 기간·할인율은 없어도 계산: 감가상각 미반영(법인세 보수적), 할인율은 NPV·옵션에서 민감도 격자)
REQUIRED = ["phase1_mw", "capex_per_mw", "construction_quarters", "rent_per_kw_month", "rent_escalation", "prelease",
            "stabilized_occupancy", "ramp_elasticity", "opex_escalation", "tax_rate", "operating_years", "margin_bp",
            "target_dscr", "max_gearing", "tenor_years", "grace_years", "dsra_months"]
OPTION_REQUIRED = ["phase2_mw", "grid_approval_prob", "rent_volatility"]
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
        """보고서 표기용 상태: input | sourced(근거 있음) | judgment(저자 판단) | verify(원문 확인) | data | design | neutral | derived"""
        if self.value is None:
            return "input"
        if self.origin == "data":
            return "data"
        t = self.tag or ""
        if "judgment" in t:
            return "judgment"
        if "sourced" in t or self.url or self.page:
            return "sourced"
        if self.origin == "derived":
            return "derived"
        if "design" in t:
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
    if ":" in s:                                   # 누진세율 등 텍스트 구조값
        return s
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


def norm_tag(t: str | None) -> str | None:
    """CSV tag 칸: sourced / judgment (또는 ASSUMPTION(sourced) …) → ASSUMPTION(…)."""
    t = (t or "").strip()
    if not t:
        return None
    low = t.lower()
    for key in ("sourced", "judgment", "verify", "design", "neutral"):
        if key in low:
            return f"ASSUMPTION({key})"
    return t


def parse_brackets(text: str | None) -> tuple | None:
    """'2:10,200:20,3000:22,inf:25' (상한:세율%) → ((2, 0.10), (200, 0.20), (3000, 0.22), (inf, 0.25))."""
    if not text:
        return None
    out = []
    for part in str(text).split(","):
        hi, rate = part.split(":")
        out.append((math.inf if hi.strip().lower() in ("inf", "∞") else float(hi), float(rate) / 100.0))
    return tuple(out)


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
        for bound in ("low", "high"):
            b = csv_to_value(r.get(bound), cur.unit)
            if b is not None:
                setattr(cur, bound, b)
        if norm_tag(r.get("tag")):
            cur.tag = norm_tag(r.get("tag"))
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
    """A: 법인세(누진 또는 단일) × (1 + 지방소득세 비율). B: 연방 + 주 × (1 − 연방) (주세는 연방 과세소득에서 공제)."""
    n, l = d.get("tax_rate_national"), d.get("tax_rate_local")
    br = d.get("tax_brackets")
    if br is not None and br.value and l is not None and l.value is not None:
        top = parse_brackets(br.value)[-1][1]
        return Assumption(case, "tax_rate", top * (1 + l.value), "%", tag=br.tag, origin="derived",
                          source="누진세율 × (1 + 지방소득세) — 표시값은 최고 한계세율")
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
                "case": case, "item": key, "value": prev.get("value", ""), "low": prev.get("low", ""),
                "high": prev.get("high", ""), "unit": a.unit, "tag": prev.get("tag", ""),
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
    index: pd.DataFrame                 # period, VA, US 판매량 지수 (기준연도 = 100)
    base_year: int
    last_year: int
    va_cagr: float
    us_cagr: float
    va_yoy_last: float
    us_price: pd.Series | None          # 미국 상업용 평균 요금 (cents/kWh, 비교용)
    va_price: pd.Series                 # 버지니아 상업용 평균 요금 (cents/kWh) — 케이스 B 전력 단가
    sales_file: str

    @property
    def price_latest(self) -> tuple[int, float]:
        return int(self.va_price.index.max()), float(self.va_price.iloc[-1])

    def price_cagr(self, y0: int | None = None) -> float:
        y0 = y0 or int(self.va_price.index.min())
        y1 = int(self.va_price.index.max())
        return cagr(float(self.va_price.loc[y0]), float(self.va_price.loc[y1]), y1 - y0)

    @property
    def price_max_yoy(self) -> tuple[int, float]:
        y = self.va_price.pct_change().dropna()
        return int(y.idxmax()), float(y.max())


def virginia(cfg: Mapping) -> Virginia | Unavailable:
    """케이스 B 수요·전력비 근거: EIA 버지니아·미국 상업용 판매량과 요금 (vol02_eia_va_com.csv 우선)."""
    vp = _read(_inp(cfg, "eia_va_price")[0])
    if vp is None or "price" not in vp or "VA" not in set(vp["stateid"]):
        return Unavailable("EIA 버지니아 상업용 요금 없음", "EIA Virginia commercial price missing", ["eia_va_price"])
    vp = vp[vp["sectorid"] == "COM"].copy()
    vp["period"] = vp["period"].astype(int)
    for c in ("sales", "price"):
        if c in vp:
            vp[c] = vp[c].map(to_number)
    sales_src = _inp(cfg, "eia_va_price")[0].name
    if "sales" in vp and {"VA", "US"} <= set(vp["stateid"]):
        w = vp.pivot_table(index="period", columns="stateid", values="sales", aggfunc="first")[["VA", "US"]].dropna()
    else:
        st = _read(_inp(cfg, "eia_state")[0])
        if st is None:
            return Unavailable("EIA 버지니아 판매량 없음", "EIA Virginia sales missing")
        st = st[st["sectorid"] == "COM"].copy()
        st["period"] = st["period"].astype(int)
        st["sales"] = st["sales"].map(to_number)
        w = st.pivot_table(index="period", columns="stateid", values="sales", aggfunc="first")[["VA", "US"]].dropna()
        sales_src = _inp(cfg, "eia_state")[0].name
    y0, y1 = int(w.index.min()), int(w.index.max())
    idx = w.div(w.loc[y0]).mul(100).reset_index()
    prices = vp.pivot_table(index="period", columns="stateid", values="price", aggfunc="first").sort_index()
    yoy = w.pct_change().iloc[-1]
    return Virginia(idx, y0, y1, cagr(w.loc[y0, "VA"], w.loc[y1, "VA"], y1 - y0), cagr(w.loc[y0, "US"], w.loc[y1, "US"], y1 - y0),
                    float(yoy["VA"]), prices["US"].dropna() if "US" in prices else None, prices["VA"].dropna(), sales_src)


@dataclass
class GridStats:
    applied: float | None              # MW
    approved: float | None
    applied_n: float | None            # 건수
    approved_n: float | None
    threshold_mw: float | None
    period: str
    basis_note: str
    source_name: str = ""
    source_url: str = ""

    @property
    def ratio(self) -> float | None:
        """용량 기준 승인률."""
        return self.approved / self.applied if self.applied and self.approved is not None else None

    @property
    def ratio_n(self) -> float | None:
        """건수 기준 승인률."""
        return self.approved_n / self.applied_n if self.applied_n and self.approved_n is not None else None


def grid_stats(cfg: Mapping) -> GridStats:
    g = cfg["research"]["vol02"]["grid_stats"]
    gv = lambda k: (g.get(k) or {}).get("value")  # noqa: E731
    src = g.get("source") or {}
    return GridStats(gv("applied_mw"), gv("approved_mw"), gv("applied_count"), gv("approved_count"),
                     gv("review_threshold_mw"), g["period"], g.get("basis_note", ""), src.get("name", ""), src.get("url", ""))


# ---------------------------------------------------------------------------
# 케이스 → PF 입력 → 결과
# ---------------------------------------------------------------------------
def missing_items(a: Mapping[str, Assumption], keys: list[str]) -> list[str]:
    return [k for k in keys if k not in a or a[k].value is None]


def case_power_price(case: str, a: Mapping[str, Assumption], va: Virginia | Unavailable) -> Assumption:
    """B: 사용자 값이 없으면 EIA 버지니아 상업용 평균 요금(최근 연도)을 USD/kWh로 사용."""
    p = a["power_price"]
    if p.value is not None or case != "B" or not ok(va):
        return p
    year, cents = va.price_latest
    return replace(p, value=cents / 100.0, origin="data", tag="DATA",
                   source=f"EIA commercial average price, Virginia, {year}")


def pf_inputs(cfg: Mapping, case: str, a: Mapping[str, Assumption], r: Rates | Unavailable, growth: float,
              mw_key: str = "phase1_mw", margin_bp: float | None = None) -> pf.PFInputs | Unavailable:
    """가정 → 엔진 입력. margin_bp를 주면 가산금리 가정 대신 그 값(시나리오)을 쓴다.

    만기 기준(tenor_basis) = fc이면 만기는 금융약정(FC)부터 → COD 이후 상환 기간 = 만기 − 건설기간.
    OPEX는 고정분(kW·년)과 안정화 매출 비율 중 하나 이상 필요.
    """
    keys = [k for k in REQUIRED if not (k == "margin_bp" and margin_bp is not None)]
    miss = missing_items(a, keys + ([mw_key] if mw_key != "phase1_mw" else []))
    if (a.get("opex_ratio") is None or a["opex_ratio"].value is None) and a["opex_per_kw_year"].value is None:
        miss.append("opex_ratio")
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
    q = int(v["construction_quarters"])
    tenor = float(v["tenor_years"])
    if str(opt("tenor_basis") or "cod") == "fc":
        tenor -= q / 4
    try:
        return pf.PFInputs(
            mw=float(v[mw_key]), capex_per_mw=float(v["capex_per_mw"]), construction_quarters=q,
            rent_per_kw_month=float(v["rent_per_kw_month"]), money_scale=float(spec["money_scale"]),
            rent_escalation=float(v["rent_escalation"]), prelease=float(v["prelease"]),
            stabilized_occupancy=float(v["stabilized_occupancy"]), ramp_growth=growth,
            ramp_elasticity=float(v["ramp_elasticity"]), opex_per_kw_year=float(opt("opex_per_kw_year") or 0.0),
            opex_escalation=float(v["opex_escalation"]), tax_rate=float(v["tax_rate"]),
            dep_years=int(v["dep_years"]) if opt("dep_years") else None,
            operating_years=int(v["operating_years"]), base_rate_construction=rc, base_rate_term=rt,
            margin=float(margin_bp if margin_bp is not None else v["margin_bp"]) / 10000.0,
            target_dscr=float(v["target_dscr"]), max_gearing=float(v["max_gearing"]),
            tenor_years=int(round(tenor)), grace_years=int(v["grace_years"]), dsra_months=float(v["dsra_months"]),
            discount_rate=float(v["discount_rate"]) if opt("discount_rate") is not None else None,
            power_passthrough=1.0 if opt("power_passthrough") is None else float(opt("power_passthrough")),
            power_price=opt("power_price"), pue=opt("pue"), it_load_factor=opt("it_load_factor"),
            power_escalation=float(opt("power_escalation") or 0.0),
            exit_cap_rate=opt("exit_cap_rate"), grace_interest=str(opt("grace_interest") or "paid"),
            reserve_buffer=float(opt("interest_reserve_buffer") or 0.0),
            opex_ratio=float(v["opex_ratio"]) if opt("opex_ratio") is not None else None,
            ramp_years=float(v["ramp_years"]) if opt("ramp_years") is not None else None,
            lease_term_years=int(v["lease_term_years"]) if opt("lease_term_years") else None,
            tax_brackets=parse_brackets(opt("tax_brackets")),
            tax_surcharge=float(v["tax_rate_local"]) if opt("tax_brackets") and opt("tax_rate_local") is not None else 0.0,
            gearing_basis=str(cfg["research"]["vol02"].get("gearing_basis", "total")))
    except ValueError as e:
        return Unavailable(f"입력값 오류: {e}", f"Invalid inputs: {e}", [])


def scenario_inputs(inp: pf.PFInputs, d: "Demand", s: str) -> pf.PFInputs:
    """수요 시나리오: 선형 램프업이면 램프업 기간 × (기준 성장률 ÷ 시나리오 성장률), 아니면 성장률 교체."""
    if inp.ramp_years is not None:
        return replace(inp, ramp_years=inp.ramp_years * d.growth["base"] / d.growth[s], ramp_growth=d.growth[s])
    return replace(inp, ramp_growth=d.growth[s])


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
    margin_bp: float | None = None              # 시나리오 가산금리 (가정 미확정일 때)
    margin_scenarios: dict = field(default_factory=dict)   # bp → CaseResult (가산금리 미확정 시 3개 시나리오)
    interest_cover_debt: float = float("nan")  # 진단: 매년 이자 현금 지급 제약 시 대출 한도
    negative_amort: list[int] = field(default_factory=list)   # 원리금 < 이자인 연차
    alts: dict = field(default_factory=dict)    # 대안 sizing: gross(전력 포함 임대) · passthrough(별도 청구) · power_cut(단가 인하 제안) · contracted(계약 매출)
    power_curve: dict = field(default_factory=dict)   # 전력비 포함 비율(SPC 부담, 0~1) → 다시 sizing한 결과
    cost_counterfactual: pf.PFResult | None = None   # 공사비 1년 상승 전(÷(1+상승률))·임대료 1년 전(÷(1+인상률)) 재계산
    gearing_alt: dict = field(default_factory=dict)   # 최대 대출 비율 분모를 바꾼 sizing {분모: {base, scenarios}}
    gearing_bench: dict | None = None           # 비교 사례 수준(총사업비 기준 대출 비율) sizing {ratio, result, source…}

    @property
    def yoc(self) -> float:
        return pf.yield_on_cost(self.base)

    def power_pair(self) -> tuple[pf.PFResult, pf.PFResult] | None:
        """(전력비 별도 청구, 전력 포함 임대) 결과 — 전력비 조항 비교용. 곡선이 없으면 None."""
        c = self.power_curve
        return (c[0.0], c[1.0]) if 0.0 in c and 1.0 in c else None


def capex_multipliers(a: Mapping[str, Assumption], pp: PeerPricing | Unavailable) -> dict[str, float] | Unavailable:
    """CAPEX 배수 = 1 + 전력설비 비중 × 피어 함의 가격 상승률 (저·중·고)."""
    share = a["power_equipment_share"].value
    if share is None or not ok(pp):
        return Unavailable("전력설비 비중 입력 필요" if share is None else "피어 데이터 없음",
                           "Power-equipment share needed" if share is None else "Peer data missing",
                           ["power_equipment_share"] if share is None else [])
    return {k: 1 + share * x for k, x in pp.scenarios().items()}


def run_case(cfg: Mapping, case: str, a: Mapping[str, Assumption], r: Rates | Unavailable, d: Demand | Unavailable,
             pp: PeerPricing | Unavailable, margin_bp: float | None = None) -> CaseResult | Unavailable:
    if not ok(d):
        return Unavailable("수요 시나리오 없음", "Demand scenarios missing", ["iea"])
    inp = pf_inputs(cfg, case, a, r, d.growth["base"], margin_bp=margin_bp)
    if not ok(inp):
        return inp
    base = pf.run(inp)
    scen = {s: (base if s == "base" else pf.run(scenario_inputs(inp, d, s))) for s in SCENARIOS}
    # 최대 대출 비율 분모 민감도: 기준 외의 분모(총사업비 · CAPEX+DSRA · CAPEX)로 다시 sizing — 기준 + 수요 시나리오
    bm = cfg["research"]["vol02"].get("gearing_benchmark") or {}
    gearing_bench = None
    if bm and bm.get("case") == case:              # 비교 사례 수준(총사업비 기준 대출 비율)으로 다시 sizing — 민감도
        ratio = float(bm["debt"]) / float(bm["cost"])
        gearing_bench = {"ratio": ratio, "result": pf.run(replace(inp, gearing_basis="total", max_gearing=ratio)), **bm}
    gearing_alt = {g: {"base": pf.run(replace(inp, gearing_basis=g)),
                       "scenarios": {s: pf.run(replace(scenario_inputs(inp, d, s), gearing_basis=g)) for s in SCENARIOS}}
                   for g in pf.GEARING_BASES if g != inp.gearing_basis}
    sc = cfg["research"]["vol02"]["sensitivity"]
    rp, op_, bp = float(sc["rent_pct"]), float(sc["occupancy_pct"]), float(sc["rate_bp"]) / 10000
    xp = float(sc.get("opex_pct", 0.2))
    pre, cx = a["prelease"], a["capex_per_mw"]
    cm = capex_multipliers(a, pp)
    st = {
        "rent_down": pf.Stress(rent_mult=1 - rp), "rent_up": pf.Stress(rent_mult=1 + rp),
        "occ_down": pf.Stress(occ_mult=1 - op_), "occ_up": pf.Stress(occ_mult=1 + op_),
        "rate_up": pf.Stress(rate_shift=bp), "rate_down": pf.Stress(rate_shift=-bp),
        "opex_up": pf.Stress(opex_mult=1 + xp), "opex_down": pf.Stress(opex_mult=1 - xp),
    }
    spc_power = inp.power_modeled() and inp.power_passthrough < 1     # SPC가 전력비를 부담하는 케이스
    clause = case in (sc.get("power_inclusion_grid") or {})   # 전력비 조항을 비교하는 케이스 (A)
    if inp.power_modeled() and not spc_power and clause:   # 별도 청구가 기준 → 전력 포함 임대(SPC 부담)는 스트레스
        st["power_gross"] = pf.Stress(passthrough=0.0)
    mid = ((sc.get("capex_mid") or {}).get(case) or {}).get("value")
    if mid and cx.value:
        st["capex_mid"] = pf.Stress(capex_mult=float(mid) / cx.value)
    if spc_power:
        pw = float(sc.get("power_pct", 0.1))
        st["power_up"], st["power_down"] = pf.Stress(power_mult=1 + pw), pf.Stress(power_mult=1 - pw)
    for q in sc["delay_quarters"]:
        st[f"delay_{q}"] = pf.Stress(delay_quarters=int(q))
    for x in (sc.get("rent_extra") or {}).get(case, []):
        st[f"rent_{int(round(x * 100)):+d}"] = pf.Stress(rent_mult=1 + float(x))
    if pre.low is not None and pre.high is not None:
        st["prelease_low"], st["prelease_high"] = pf.Stress(prelease=pre.low), pf.Stress(prelease=pre.high)
    if cx.low is not None and cx.high is not None and cx.value:
        st["capex_range_high"] = pf.Stress(capex_mult=cx.high / cx.value)
        st["capex_range_low"] = pf.Stress(capex_mult=cx.low / cx.value)
    if ok(cm):
        for k, m in cm.items():
            st[f"capex_{k}"] = pf.Stress(capex_mult=m)
    stresses = {k: pf.stress(base, s) for k, s in st.items()}
    torn_cases = {"rent": (st["rent_down"], st["rent_up"]), "occupancy": (st["occ_down"], st["occ_up"]),
                  "rate": (st["rate_up"], st["rate_down"]), "opex": (st["opex_up"], st["opex_down"]),
                  "delay": (st[f"delay_{max(sc['delay_quarters'])}"], pf.BASE)}
    if spc_power:
        torn_cases["power"] = (st["power_up"], st["power_down"])
    for x in (sc.get("rent_extra") or {}).get(case, []):
        torn_cases[f"rent_extra"] = (st[f"rent_{int(round(x * 100)):+d}"], pf.BASE)
    if "prelease_low" in st:
        torn_cases["prelease"] = (st["prelease_low"], st["prelease_high"])
    if "capex_range_high" in st:
        torn_cases["capex_range"] = (st["capex_range_high"], st["capex_range_low"])
    if ok(cm):
        torn_cases["capex"] = (st["capex_high"], pf.BASE)
    torn = pf.tornado(base, torn_cases)
    rng = sc["breakeven_ranges"]
    be_rows = []
    near = {"rent_mult": 1.0, "occ_mult": 1.0, "prelease": inp.prelease, "capex_mult": 1.0, "opex_mult": 1.0,
            "rate_shift": 0.0, "delay_quarters": 0.0}
    if spc_power:
        near["power_mult"] = 1.0
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
    hm_cm = sc["heatmap"]["capex_mult"]
    if cx.low is not None and cx.high is not None and cx.value:   # CAPEX 축 = 가정 범위(하단~상단)
        hm_cm = sorted({round(cx.low / cx.value, 4), 1.0, round(cx.high / cx.value, 4)}
                       | ({round(float(mid) / cx.value, 4)} if mid else {round((cx.value + cx.high) / 2 / cx.value, 4)}))
    hm = pf.heatmap(base, sc["heatmap"]["rent_mult"], hm_cm) if case == "A" else None
    power = None
    if inp.power_modeled():
        o = base.ops
        si = min(int(math.ceil(inp.ramp_years or 0)), len(o) - 1)       # 안정화 첫해
        power = {"power_cost_y1": float(o["power_cost"].iloc[0]), "rent_y1": float(o["revenue"].iloc[0]),
                 "share_of_tenant_cost": float(o["power_cost"].iloc[0] / (o["power_cost"].iloc[0] + o["revenue"].iloc[0])),
                 "stab_year": si + 1, "power_cost_stab": float(o["power_cost"].iloc[si]), "revenue_stab": float(o["revenue"].iloc[si]),
                 "net_power_stab": float(o["net_power"].iloc[si]),
                 "share_of_revenue_stab": float(o["power_cost"].iloc[si] / o["revenue"].iloc[si]) if o["revenue"].iloc[si] else float("nan")}
    # 유리한 스트레스가 최소 DSCR을 낮추는 경우: 세율 0으로 다시 계산해 법인세 시점 효과인지 확인
    no_tax = replace(inp, tax_rate=0.0, tax_brackets=None)
    tax_timing = []
    anomalies = [r_["variable"] for _, r_ in torn.iterrows() if r_["high"] < r_["base"] - 1e-6]
    if anomalies and (inp.tax_rate > 0 or inp.tax_brackets):
        b0 = pf.run(no_tax)
        for var in anomalies:
            fav = torn_cases[var][1]
            if pf.stress(b0, fav).min_dscr >= b0.min_dscr - 1e-6:
                tax_timing.append(var)
    hm_tt = False
    if hm is not None and (inp.tax_rate > 0 or inp.tax_brackets):
        odd = [(r_, c_) for r_ in hm.index for c_ in hm.columns
               if r_ >= 1 and c_ <= 1 and (r_, c_) != (1.0, 1.0) and hm.loc[r_, c_] < base.min_dscr - 1e-6]
        if odd:
            b0 = pf.run(no_tax)
            r_, c_ = odd[0]
            hm_tt = pf.stress(b0, pf.Stress(rent_mult=r_, capex_mult=c_)).min_dscr >= b0.min_dscr - 1e-6
    alts, curve = {}, {}
    if inp.power_modeled() and (clause or spc_power):
        for sh in (sc.get("power_inclusion_grid") or {}).get(case, []):   # 전력비 포함 비율 곡선 (부분 패스스루)
            sh = float(sh)
            curve[sh] = base if abs((1 - sh) - inp.power_passthrough) < 1e-12 else pf.run(replace(inp, power_passthrough=1 - sh))
        if spc_power:                                   # 전력비 별도 청구(pass-through) 시 다시 sizing
            alts["passthrough"] = curve.get(0.0) or pf.run(replace(inp, power_passthrough=1.0))
        else:                                           # 전력 포함 임대(SPC 부담) 시 다시 sizing
            alts["gross"] = curve.get(1.0) or pf.run(replace(inp, power_passthrough=0.0))
        cut = (sc.get("power_price_cut") or {}).get(case)
        if cut and cut.get("value") is not None:        # 확정 전 인하 제안 → SPC가 전력비를 낼 때의 민감도
            alts["power_cut"] = pf.run(replace(inp, power_passthrough=min(inp.power_passthrough, 0.0),
                                               power_price=inp.power_price + float(cut["value"])))
    if case in (sc.get("contracted_sizing") or []):     # 계약 매출(사전 임대분) CFADS로 sculpting
        alts["contracted"] = pf.run(replace(inp, sizing_basis="contracted"))
    cf_ = None
    chg = a.get("capex_yoy_change")
    if chg is not None and chg.value:                   # 공사비 1년 상승 전·임대료 1년 전 수준으로 재계산
        cf_ = pf.run(replace(inp, capex_per_mw=inp.capex_per_mw / (1 + chg.value),
                             rent_per_kw_month=inp.rent_per_kw_month / (1 + inp.rent_escalation)))
    return CaseResult(case, inp, base, scen, stresses, torn, be, hm, cm, power, pf.identity_checks(base), tax_timing, hm_tt,
                      margin_bp=margin_bp, interest_cover_debt=pf.interest_cover_cap(base),
                      negative_amort=pf.negative_amortization_years(base), alts=alts, cost_counterfactual=cf_, power_curve=curve,
                      gearing_alt=gearing_alt, gearing_bench=gearing_bench)


def power_cost_grid(va: "Virginia", rent: float | None, pues: list[float], load: float = 1.0) -> pd.DataFrame | None:
    """버지니아 상업용 요금 × PUE 격자 → 임차 IT kW·월당 전력비(USD, IT 부하율 load)와 임대료 대비 비율.

    요금 열: 최근 연도, 최근 연도 × (1 + 2015년 이후 최대 연간 상승률). PUE 격자는 민감도 축(기준 가정 PUE 포함).
    """
    if not ok(va):
        return None
    y, p = va.price_latest
    my, mx = va.price_max_yoy
    rows = []
    for pue in pues:
        for label, cents in ((f"{y}", p), (f"{y} +{mx * 100:.1f}%", p * (1 + mx))):
            usd = 730 * load * pue * cents / 100
            rows.append({"pue": pue, "price_label": label, "cents": cents, "usd_per_kw_month": usd,
                         "share_of_rent": usd / rent if rent else float("nan")})
    return pd.DataFrame(rows)


@dataclass
class OptionFacts:
    result: ro.OptionResult                    # 대표 셀(할인율·대기기간 격자의 가운데) 결과
    inputs: ro.OptionInputs
    grid_ratio: float | None
    grid: pd.DataFrame                          # discount_rate, window_years, value_conditional, value, build_now, flexibility, exercise_share
    prob_values: dict[float, float]             # 승인 확률 시나리오 → 옵션 가치 (대표 셀)
    decision_derived: bool                      # 결정 시점을 램프업 기간에서 도출했는지
    discount_pending: bool                      # 할인율 미확정(격자)
    window_pending: bool                        # 대기 기간 미확정(격자)


def option_scenarios(inp: pf.PFInputs, d: "Demand") -> dict[str, dict]:
    return {s: ({"ramp_years": inp.ramp_years * d.growth["base"] / d.growth[s], "ramp_growth": d.growth[s]}
                if inp.ramp_years is not None else {"ramp_growth": d.growth[s]}) for s in SCENARIOS}


def run_option(cfg: Mapping, a: Mapping[str, Assumption], r: Rates | Unavailable, d: Demand | Unavailable,
               case_res: CaseResult | Unavailable, gs: GridStats) -> OptionFacts | Unavailable:
    """2단계 옵션. 결정 시점이 없으면 1단계 램프업 종료(수요 확인) 연도로 도출한다. 할인율 × 대기 기간 격자(민감도 축)는
    항상 계산하고, 대표 셀 = 가정값(없으면 격자 가운데 + 보고서에 '미확정' 표기)."""
    if not ok(case_res):
        return Unavailable("케이스 A 모델 입력 필요", "Case A model inputs needed", list(getattr(case_res, "missing", [])))
    miss = missing_items(a, OPTION_REQUIRED)
    dec = a["approval_decision_year"].value
    derived = False
    if dec is None and case_res.inp.ramp_years is not None:
        dec, derived = int(math.ceil(case_res.inp.ramp_years)), True
    if dec is None:
        miss.append("approval_decision_year")
    if miss:
        return Unavailable("입력 필요", "Inputs needed", miss)
    if not a["phase2_mw"].value:
        return Unavailable("2단계 용량 0", "Phase 2 capacity is zero", ["phase2_mw"])
    roc = cfg["research"]["vol02"]["real_option"]
    dr_v, win_v = a["discount_rate"].value, a["option_window_years"].value
    drs = sorted({float(x) for x in roc["discount_grid"]} | ({float(dr_v)} if dr_v is not None else set()))
    wins = sorted({int(x) for x in roc["window_grid"]} | ({int(win_v)} if win_v is not None else set()))
    pa = a["grid_approval_prob"]
    probs = sorted({x for x in (pa.low, pa.value, pa.high) if x is not None})
    w = cfg["research"]["vol02"]["demand_scenarios"]["weights"]
    scen = option_scenarios(case_res.inp, d)

    def make(dr: float, win: int, n: int) -> ro.OptionInputs:
        p2 = replace(case_res.inp, mw=float(a["phase2_mw"].value), discount_rate=dr)
        return ro.OptionInputs(p2, case_res.inp.prelease, scen, {k: float(w[k]) for k in SCENARIOS}, float(pa.value),
                               int(dec), win, float(a["rent_volatility"].value), n, int(roc["seed"]), int(roc["basis_degree"]))
    rows = []
    for dr in drs:
        for win in wins:
            res = ro.value(make(dr, win, int(roc.get("grid_paths", roc["n_paths"]))), [pa.value], [])
            rows.append({"discount_rate": dr, "window_years": win, "value_conditional": res.value_conditional,
                         "value": res.value, "build_now": res.build_now, "flexibility": res.flexibility,
                         "exercise_share": res.exercise_share})
    oi = make(float(dr_v) if dr_v is not None else drs[len(drs) // 2], int(win_v) if win_v is not None else wins[len(wins) // 2],
              int(roc["n_paths"]))
    res = ro.value(oi, sorted(set(roc["prob_grid"]) | set(probs)), roc["convergence_paths"])
    pv = {p: p * res.value_conditional for p in probs}
    return OptionFacts(res, oi, gs.ratio, pd.DataFrame(rows), pv, derived, dr_v is None, win_v is None)


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
    cases = {}
    for c in CASES:
        if c not in a:
            continue
        ms = (v["sensitivity"].get("margin_scenarios_bp") or {}).get(c)
        if a[c]["margin_bp"].value is None and ms:      # 가산금리 미확정 → 시나리오별 계산, 가운데를 대표값으로
            runs = {float(m): run_case(cfg, c, a[c], r, d, pp, margin_bp=float(m)) for m in ms}
            mid = runs[float(ms[len(ms) // 2])]
            if ok(mid):
                mid.margin_scenarios = runs
            cases[c] = mid
        else:
            cases[c] = run_case(cfg, c, a[c], r, d, pp)
    opt = run_option(cfg, a["A"], r, d, cases.get("A", Unavailable("")), gs) if "A" in a else Unavailable("")
    if ok(opt) and opt.decision_derived:
        x = a["A"]["approval_decision_year"]
        x.value, x.origin, x.tag = opt.inputs.decision_year, "derived", TAG_JUDGMENT
        x.source = f"저자 판단(도출): 1단계 램프업 종료 = 수요 확인 시점 → COD 후 {opt.inputs.decision_year}년"
    return Facts(as_of, a, d, r, pp, va, gs, cases, opt, source_status(cfg, va))


def table_keys(case: str, d: Mapping[str, Assumption]) -> list[str]:
    """보고서 가정표·집계에 쓰는 항목: 쓰이지 않는 대체 항목은 뺀다."""
    hide = {"tax_rate"}
    if d.get("ramp_years") is not None and d["ramp_years"].value is not None:
        hide.add("ramp_elasticity")                       # 선형 램프업이면 성장률 탄력성 미사용
    if d.get("opex_ratio") is not None and d["opex_ratio"].value is not None and d["opex_per_kw_year"].value is None:
        hide.add("opex_per_kw_year")                      # OPEX를 매출 비율로 입력
    if d.get("power_equipment_share") is not None and d["power_equipment_share"].value is None \
            and d.get("capex_per_mw") is not None and d["capex_per_mw"].high is not None:
        hide.add("power_equipment_share")                 # CAPEX 스트레스를 가정 범위로 대체
    if case == "A":
        if d.get("power_price") is not None and d["power_price"].value is None:
            hide.add("power_price")                       # 패스스루 100% — 한국 요금 미사용
        if d.get("lease_term_years") is not None and d["lease_term_years"].value is None:
            hide.add("lease_term_years")                  # 운영기간 전체 계약으로 처리
    if d.get("grace_interest") is not None and d["grace_interest"].value != "reserve":
        hide.add("interest_reserve_buffer")
    if case == "B":
        hide |= {"grid_approval_prob", "approval_decision_year", "option_window_years", "rent_volatility", "phase2_mw",
                 "discount_rate"}                         # 할인율은 케이스 A 옵션에만 사용
    return [k for k in LABELS if k in d and k not in hide]


def fmt_missing(keys: list[str], kr: bool = True) -> str:
    return ", ".join(LABELS.get(k, ("기준금리", "base rate") if k == "base_rate" else (k, k))[0 if kr else 1] for k in keys)


def finite(x: Any) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)
