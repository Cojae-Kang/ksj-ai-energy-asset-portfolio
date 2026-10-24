"""Vol.4 입력 로드와 계산 (순수 함수). 보고서의 모든 숫자는 여기서 계산한다.

입력: data/manual/vol04_inputs.csv — 항목마다 신뢰 등급(tier)과 출처를 둔다.
  A = 1차 공식 원문(정부·공공기관 발표, 법령, SEC 공시, 공공 연구기관 원문)
  B = 공식 발표를 인용한 주요 언론 보도 (원문 대조 대기)
  C = 민간 2차 자료 (보고서 확정 전 반드시 교체 — 잠정 표시)
  J = 저자 판단·설계값 (근거를 쓰고 민감도로 공개)
official_todo가 있으면 '공식 원문으로 교체 대기' 항목 → 해당 Exhibit 각주에 잠정 표시, 빌드 요약에 목록.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.analysis import ppa_model as pm
from src.data_fetch.base import resolve_path

TIER_KR = {"A": "공식 원문", "B": "공식 발표 보도", "C": "민간 2차(잠정)", "J": "저자 판단"}
TIER_EN = {"A": "Official source", "B": "Press report of official release", "C": "Secondary (provisional)", "J": "Author judgement"}

LABELS: dict[str, tuple[str, str]] = {
    "asset_mw": ("발전 용량", "Capacity"), "cod_year": ("상업운전 연도", "COD year"),
    "capacity_factor": ("이용률", "Capacity factor"), "degradation": ("연 열화율", "Annual degradation"),
    "lcoe_target": ("태양광 LCOE", "Solar LCOE"), "lcoe_discount_rate": ("LCOE 역산 할인율", "LCOE discount rate"),
    "opex_pct": ("OPEX (CAPEX 대비)", "OPEX (% of CAPEX)"), "opex_escalation": ("OPEX 인상률", "OPEX escalation"),
    "operating_years": ("운영기간", "Operating life"), "dep_years": ("감가상각 기간", "Depreciation life"),
    "tax_brackets": ("법인세 누진세율", "Corporate tax brackets"), "tax_rate_local": ("지방소득세", "Local income tax"),
    "cfd_price": ("한전 계약가(2026년 1차 입찰 상한)", "KEPCO contract price (2026 round-1 cap)"), "cfd_term": ("계약기간", "Contract term"),
    "kepco_industrial_price": ("한전 산업용 판매단가(2025)", "KEPCO industrial tariff (2025)"),
    "smp_base": ("SMP 기준값", "SMP base"), "smp_escalation": ("SMP 추세", "SMP trend"),
    "smp_sigma": ("SMP 변동성", "SMP volatility"), "smp_phi": ("SMP 평균회귀(AR1)", "SMP mean reversion (AR1)"),
    "rec_eligible": ("REC 수익 여부", "REC revenue"), "cf_sd_annual": ("발전량 연 변동", "Annual output variation"),
    "cf_sd_resource": ("발전량 추정 오차", "Resource estimate error"), "ktb_3y": ("국고채 3년", "KTB 3-yr"),
    "margin_bp": ("가산금리", "Credit margin"), "dscr_cfd": ("목표 DSCR · CfD", "Target DSCR · CfD"),
    "dscr_ppa": ("목표 DSCR · PPA", "Target DSCR · PPA"), "dscr_merchant": ("목표 DSCR · 시장", "Target DSCR · merchant"),
    "gearing_cfd": ("최대 대출 비율 · CfD", "Max gearing · CfD"), "gearing_ppa": ("최대 대출 비율 · PPA", "Max gearing · PPA"),
    "gearing_merchant": ("최대 대출 비율 · 시장", "Max gearing · merchant"), "tenor_cfd": ("대출 만기 · CfD", "Tenor · CfD"),
    "tenor_ppa": ("대출 만기 · PPA", "Tenor · PPA"), "tenor_merchant": ("대출 만기 · 시장", "Tenor · merchant"),
    "ppa_term": ("PPA 기간", "PPA term"), "ppa_escalation": ("PPA 가격 인상률", "PPA escalation"),
    "equity_hurdle": ("지분 요구수익률", "Equity hurdle"), "exit_year": ("매각 시점", "Exit year"),
    "buyer_return": ("매수자 요구수익률", "Buyer's required return"), "dc_it_mw": ("데이터센터 IT 용량", "Data-centre IT capacity"),
    "dc_pue": ("PUE", "PUE"), "dc_it_load": ("IT 부하율", "IT load factor"),
    "talen_notional_usd_bn": ("Talen–AWS PPA 명목 매출", "Talen–AWS PPA notional revenue"), "talen_years": ("Talen–AWS 계약기간", "Talen–AWS term"),
    "talen_mw": ("Talen–AWS 계약 용량", "Talen–AWS contract capacity"), "levelten_solar_na": ("LevelTen 북미 태양광 PPA", "LevelTen N. America solar PPA"),
}


class Unavailable:
    def __init__(self, reason: str, reason_en: str = "", missing: list[str] | None = None):
        self.reason, self.reason_en, self.missing = reason, reason_en or reason, missing or []


def ok(x: Any) -> bool:
    return not isinstance(x, Unavailable)


@dataclass
class Input:
    key: str
    value: Any
    low: float | None
    high: float | None
    unit: str
    tier: str
    source: str
    url: str
    published: str
    official_todo: str

    @property
    def pending_official(self) -> bool:
        return bool(self.official_todo.strip())


def _num(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_inputs(path: Path) -> dict[str, Input]:
    out = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            v = r["value"]
            val: Any = _num(v) if _num(v) is not None else v
            out[r["key"]] = Input(r["key"], val, _num(r["low"]), _num(r["high"]), r["unit"], r["tier"].strip(), r["source_name"],
                                  r["url"], r["published"], r.get("official_todo", "") or "")
    return out


def ktb_on(cfg: Mapping, as_of: str) -> tuple[float | None, str | None]:
    p = resolve_path(cfg["research"]["vol04"]["inputs"]["ktb"])
    if not p.exists():
        return None, None
    d = pd.read_csv(p, encoding="utf-8-sig")
    d = d[d["date"] <= as_of].dropna(subset=["ktb_3y"])
    if d.empty:
        return None, None
    r = d.iloc[-1]
    return float(r["ktb_3y"]) / 100, str(r["date"])


@dataclass
class Facts:
    as_of: str
    inputs: dict[str, Input]
    asset: pm.Asset
    market: pm.Market
    debts: dict[str, pm.Debt]
    rate: float
    ktb: float
    ktb_date: str
    base: dict[str, pm.Result]
    ppa_mid: float
    corridor: tuple[float, float]
    be_price: float | None                       # PPA 가격: 해지 없음, CfD 지분 IRR과 같아지는 값
    premium: list[dict]                          # 해지 확률별 필요 PPA 가격·최대 망이용료
    default_curve: list[tuple[int, float | None]]
    exit: dict[str, tuple[float | None, float]]
    price_curve: list[tuple[float, float | None]]
    mc: dict[str, np.ndarray] | Unavailable
    mc_spec: pm.MCSpec
    dc: dict
    us: dict
    sens: list[dict]
    provisional: list[str] = field(default_factory=list)

    def V(self, k: str) -> float:
        return float(self.inputs[k].value)


def build_asset(I: Mapping[str, Input], cf: float | None = None, capex: float | None = None) -> pm.Asset:
    V = lambda k: float(I[k].value)  # noqa: E731
    cf = V("capacity_factor") if cf is None else cf
    if capex is None:
        capex = pm.capex_from_lcoe(V("asset_mw"), cf, V("degradation"), int(V("operating_years")), V("lcoe_target"),
                                   V("lcoe_discount_rate"), V("opex_pct"), V("opex_escalation"))
    return pm.Asset(V("asset_mw"), cf, V("degradation"), capex, V("opex_pct"), V("opex_escalation"), int(V("operating_years")),
                    int(V("dep_years")), pm.parse_brackets(I["tax_brackets"].value), V("tax_rate_local"))


def ppa_for_npv_match(a: pm.Asset, m: pm.Market, d: pm.Debt, hazard: float, hurdle: float, target_npv: float,
                      lo: float, hi: float) -> float | None:
    def f(p: float) -> float:
        mm = pm.Market(**{**m.__dict__, "ppa_price": p})
        r0 = pm.run("ppa", a, mm, d)
        return pm.expected_npv_ppa(a, mm, d, hazard, hurdle, (r0.debt, r0.ds))
    return pm.solve(f, lo, hi, target_npv, tol=0.01)


def load_facts(cfg: Mapping, as_of: str | None = None, mc_n: int | None = None) -> Facts:
    v = cfg["research"]["vol04"]
    as_of = as_of or v["as_of"]
    I = load_inputs(resolve_path(v["inputs_csv"]))
    V = lambda k: float(I[k].value)  # noqa: E731
    ktb, ktb_date = ktb_on(cfg, as_of)
    if ktb is None:
        raise RuntimeError("ECOS 국고채 3년 데이터 없음 (data/processed/ecos_ktb_daily.csv)")
    rate = ktb + V("margin_bp") / 1e4
    a = build_asset(I)
    lo_c, hi_c = V("cfd_price"), V("kepco_industrial_price")
    mid = (lo_c + hi_c) / 2
    m = pm.Market(smp0=V("smp_base"), smp_escalation=V("smp_escalation"), cfd_price=lo_c, cfd_term=int(V("cfd_term")),
                  ppa_price=mid, ppa_term=int(V("ppa_term")), ppa_escalation=V("ppa_escalation"))
    debts = {k: pm.Debt(rate, V(f"dscr_{k}"), V(f"gearing_{k}"), int(V(f"tenor_{k}"))) for k in pm.ROUTES}
    base = {k: pm.run(k, a, m, debts[k]) for k in pm.ROUTES}
    hurdle = V("equity_hurdle")

    # 1) 해지 없음: CfD 지분 IRR과 같아지는 PPA 가격
    cfd_irr = base["cfd"].irr

    def irr_at(p: float) -> float:
        r = pm.run("ppa", a, pm.Market(**{**m.__dict__, "ppa_price": p}), debts["ppa"]).irr
        return r if r is not None else -1.0
    be = pm.solve(irr_at, 60.0, 300.0, cfd_irr, tol=0.01) if cfd_irr is not None else None
    price_curve = [(p, irr_at(p)) for p in np.arange(130.0, 200.0 + 1e-9, 5.0)]

    # 2) 해지 확률별: 지분 NPV(@요구수익률) 기대값이 CfD와 같아지는 PPA 가격 → 데이터센터가 감당할 망이용료 상한
    cfd_npv = pm.npv(base["cfd"].equity_flows, hurdle)
    premium = []
    for h in v["hazards"]:
        p = ppa_for_npv_match(a, m, debts["ppa"], float(h), hurdle, cfd_npv, 60.0, 400.0)
        premium.append({"hazard": float(h), "price": p, "premium": (p - lo_c) if p is not None else None,
                        "max_fee": (hi_c - p) if p is not None else None})

    # 3) 해지 시점별 지분 IRR (회랑 중간 가격, 대출 고정)
    r0 = base["ppa"]
    curve = [(y, pm.run("ppa", a, m, debts["ppa"], default_year=y, fixed_debt=(r0.debt, r0.ds)).irr) for y in range(1, int(V("ppa_term")) + 1)]

    # 4) 매각
    ex = {k: base[k].exit_irr(int(V("exit_year")), V("buyer_return")) for k in pm.ROUTES}

    # 5) 민감도: 핵심 입력 범위별 경로 IRR
    sens = []
    for key in ("capacity_factor", "lcoe_target", "smp_base", "opex_pct"):
        inp = I[key]
        if inp.low is None or inp.high is None:
            continue
        row = {"key": key, "lo_v": inp.low, "hi_v": inp.high}
        for side, val in (("low", inp.low), ("high", inp.high)):
            if key == "smp_base":
                mm, aa = pm.Market(**{**m.__dict__, "smp0": val}), a
            elif key == "capacity_factor":
                mm, aa = m, build_asset(I, cf=val, capex=a.capex)
            elif key == "lcoe_target":
                mm = m
                aa = build_asset(I, capex=pm.capex_from_lcoe(a.mw, a.capacity_factor, a.degradation, a.years, val,
                                                             V("lcoe_discount_rate"), a.opex_pct, a.opex_escalation))
            else:
                mm = m
                aa = pm.Asset(**{**a.__dict__, "opex_pct": val})
            row[side] = {k: pm.run(k, aa, mm, debts[k]).irr for k in pm.ROUTES}
        sens.append(row)

    # 6) 몬테카를로
    mcv = v["monte_carlo"]
    spec = pm.MCSpec(int(mcv["n"] if mc_n is None else mc_n), int(mcv["seed"]), V("smp_sigma"), V("smp_phi"), V("cf_sd_annual"), V("cf_sd_resource"),
                     float(mcv["hazard"]))
    sizing = {k: (base[k].debt, base[k].ds) for k in pm.ROUTES}
    mc: dict | Unavailable = pm.simulate(a, m, debts, sizing, spec) if spec.n > 0 else Unavailable("몬테카를로 생략", "Monte Carlo skipped")

    # 데이터센터(Vol.2) 연결
    cons = V("dc_it_mw") * V("dc_it_load") * V("dc_pue") * pm.HOURS / 1000          # GWh
    dc = {"consumption_gwh": cons, "power_cost": cons * hi_c / 100, "solar_gwh": float(base["cfd"].gen[0]),
          "share": float(base["cfd"].gen[0]) / cons}
    # 미국 비교: Talen–AWS 명목 매출 ÷ (전량 MW × 8,760h × 년) = 전량·전시간 기준 평균 단가(하한 추정)
    us = {"talen_floor": V("talen_notional_usd_bn") * 1e9 / (V("talen_mw") * pm.HOURS * V("talen_years")),
          "levelten": V("levelten_solar_na")}
    prov = [k for k, x in I.items() if x.pending_official]
    return Facts(as_of, I, a, m, debts, rate, ktb, ktb_date, base, mid, (lo_c, hi_c), be, premium, curve, ex, price_curve,
                 mc, spec, dc, us, sens, prov)


def mc_stats(x: np.ndarray, hurdle: float) -> dict:
    q = np.quantile(x, [0.1, 0.5, 0.9])
    return {"p10": float(q[0]), "p50": float(q[1]), "p90": float(q[2]), "below": float((x < hurdle).mean()),
            "neg": float((x < 0).mean())}
