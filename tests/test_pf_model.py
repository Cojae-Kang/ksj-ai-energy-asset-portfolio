"""PF 모델 엔진·실물옵션 테스트 — 네트워크 없이 실행. 입력은 테스트용 합성 값(보고서에 쓰지 않음)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from src.analysis import pf_model as pf
from src.analysis import real_option as ro

# 테스트용 합성 입력 (사실 주장 아님)
BASE_INP = pf.PFInputs(
    mw=20, capex_per_mw=150, construction_quarters=8, rent_per_kw_month=250_000, money_scale=1e8,
    rent_escalation=0.025, prelease=0.6, stabilized_occupancy=0.9, ramp_growth=0.10, ramp_elasticity=1.0,
    opex_per_kw_year=300_000, opex_escalation=0.02, tax_rate=0.24, dep_years=20, operating_years=20,
    base_rate_construction=0.0384, base_rate_term=0.0418, margin=0.02, target_dscr=1.3, max_gearing=0.8,
    tenor_years=15, grace_years=0, dsra_months=6, discount_rate=0.09)

VARIANTS = {
    "dscr_bound": replace(BASE_INP, prelease=0.3, max_gearing=0.9),
    "gearing_bound": replace(BASE_INP, max_gearing=0.5),
    "grace_paid": replace(BASE_INP, grace_years=2),
    "grace_capitalized": replace(BASE_INP, prelease=0.2, grace_years=2, grace_interest="capitalized"),
    "power_partial": replace(BASE_INP, power_price=170, pue=1.3, it_load_factor=0.7, power_passthrough=0.9),
    "exit_value": replace(BASE_INP, exit_cap_rate=0.07),
    "grace_reserve": replace(BASE_INP, prelease=0.15, ramp_years=3, grace_years=3, grace_interest="reserve", reserve_buffer=0.1,
                             max_gearing=0.95),
    "power_gross": replace(BASE_INP, power_price=180, pue=1.3, it_load_factor=0.7, power_passthrough=0.0, power_escalation=0.02),
    "contracted_sizing": replace(BASE_INP, lease_term_years=15, sizing_basis="contracted"),
}


# ---------------------------------------------------------------------------
# 구성 요소
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n", [1, 4, 8, 11])
def test_drawdown_weights_sum_and_shape(n):
    w = pf.drawdown_weights(n)
    assert w.sum() == pytest.approx(1.0) and (w > 0).all()
    assert np.allclose(w, w[::-1])                                   # S-curve 대칭
    assert pf.drawdown_weights(n, "linear").sum() == pytest.approx(1.0)
    with pytest.raises(ValueError):
        pf.drawdown_weights(n, "bogus")


def test_occupancy_path_ramp_and_cap():
    p = pf.occupancy_path(0.2, 0.9, 0.10, 1.0, 30)
    assert p[0] == pytest.approx(0.2) and p[1] == pytest.approx(0.22)
    assert p.max() == pytest.approx(0.9) and (np.diff(p) >= -1e-12).all()
    assert pf.occupancy_path(0.2, 0.9, 0.10, 1.0, 5, occ_mult=10).max() == 1.0   # 물리 상한
    yrs = pf.growth_to_stabilize(0.2, 0.9, 0.10, 1.0)
    assert yrs == pytest.approx(np.log(4.5) / np.log(1.1))
    assert pf.growth_to_stabilize(0.2, 0.9, 0.0, 1.0) == np.inf


def test_tax_schedule_loss_carryforward():
    tax = pf.tax_schedule(np.array([-100.0, 60.0, 60.0, 60.0]), np.zeros(4), 0.25)
    assert list(tax) == pytest.approx([0.0, 0.0, 5.0, 15.0])        # 결손 100을 60 + 40으로 소진


def test_inputs_validation():
    with pytest.raises(ValueError):
        replace(BASE_INP, grace_years=15)
    with pytest.raises(ValueError):
        replace(BASE_INP, tenor_years=25)
    with pytest.raises(ValueError):
        replace(BASE_INP, max_gearing=1.2)
    with pytest.raises(ValueError):
        replace(BASE_INP, grace_interest="pik")


# ---------------------------------------------------------------------------
# Sculpting · DSCR 정의 · 회계 항등식
# ---------------------------------------------------------------------------
def test_sculpt_pv_identity_and_target_dscr():
    cf = np.array([50, 60, 70, 80, 90, 100, 100, 100], dtype=float)
    r, dscr = 0.06, 1.25
    debt, ds = pf.sculpt(cf, r, dscr, 8, 0)
    assert debt == pytest.approx(float((cf / dscr / (1 + r) ** np.arange(1, 9)).sum()))
    assert np.allclose(cf / ds, dscr)
    sch = pf.amortize(debt, ds, r)
    assert sch["closing"].iloc[-1] == pytest.approx(0.0, abs=1e-9)
    # 거치(이자 지급): 대출 ≤ min(CFADS_거치) ÷ (DSCR × r)
    d2, ds2 = pf.sculpt(cf, r, dscr, 8, 2)
    assert d2 <= cf[:2].min() / (dscr * r) + 1e-9 and ds2[0] == pytest.approx(d2 * r)
    # 거치(이자 자본화): 거치기간 원리금 0, 대출 = 거치 종료 잔액 ÷ (1+r)^거치
    d3, ds3 = pf.sculpt(cf, r, dscr, 8, 2, "capitalized")
    assert ds3[:2].sum() == 0 and pf.amortize(d3, ds3, r)["closing"].iloc[-1] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("name", list(VARIANTS))
def test_identities_hold(name):
    r = pf.run(VARIANTS[name])
    checks = pf.identity_checks(r)
    scale = r.cons.uses
    for k, v in checks.items():
        assert abs(v) <= 1e-9 * scale, (name, k, v)
    o = r.ops.iloc[: r.inp.tenor_years]
    d = o[o["debt_service"] > 0]
    assert np.allclose(d["dscr"], d["cfads"] / d["debt_service"])        # DSCR = CFADS ÷ 원리금
    assert r.debt <= r.inp.max_gearing * r.cons.uses * (1 + 1e-9)
    assert r.ops["debt_closing"].iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_dscr_binding_sets_min_dscr_at_target():
    r = pf.run(VARIANTS["dscr_bound"])
    assert r.binding == "dscr" and r.min_dscr == pytest.approx(r.inp.target_dscr, rel=1e-9)
    assert r.effective_dscr == pytest.approx(r.inp.target_dscr)


def test_gearing_binding_caps_debt_and_raises_dscr():
    r = pf.run(VARIANTS["gearing_bound"])
    assert r.binding == "gearing" and r.gearing == pytest.approx(0.5, rel=1e-9)
    assert r.min_dscr > r.inp.target_dscr and r.effective_dscr == pytest.approx(r.min_dscr, rel=1e-9)


def test_llcr_definition():
    r = pf.run(VARIANTS["dscr_bound"])
    rate = r.inp.term_rate
    t = r.inp.tenor_years
    npv = float((r.ops["cfads"][:t] / (1 + rate) ** np.arange(1, t + 1)).sum())
    assert r.llcr == pytest.approx(npv / r.debt)


def test_idc_and_sources_uses():
    r = pf.run(VARIANTS["dscr_bound"])
    c = r.cons
    assert c.capex == pytest.approx(BASE_INP.capex_total)
    assert c.idc > 0 and c.uses == pytest.approx(c.capex + c.idc + c.dsra_initial)
    assert c.dsra_initial == pytest.approx(BASE_INP.dsra_months / 12 * r.ops["debt_service"].iloc[0])
    q = c.quarters
    assert q["idc"].iloc[0] == 0 and (q["debt_draw"] / q["uses"]).round(12).nunique() == 1   # 비율대로 조달


def test_capitalized_grace_locks_distributions():
    r = pf.run(VARIANTS["grace_capitalized"])
    o = r.ops
    assert (o["debt_service"][:2] == 0).all() and (o["distribution"][:2] == 0).all()
    assert o["lockup_in"][:2].sum() > 0 and o["lockup_release"].iloc[2] == pytest.approx(o["lockup_in"][:2].sum())
    assert o["principal"][:2].sum() < 0                                  # 이자 자본화로 잔액 증가


def test_power_passthrough_net_cost():
    full = pf.run(replace(VARIANTS["power_partial"], power_passthrough=1.0))
    part = pf.run(VARIANTS["power_partial"])
    assert (full.ops["net_power"] == 0).all()
    assert part.ops["net_power"].iloc[0] == pytest.approx(-0.1 * part.ops["power_cost"].iloc[0])
    assert part.debt < full.debt                                         # 순전력비만큼 CFADS 감소


# ---------------------------------------------------------------------------
# IRR · 회수기간 · 환율
# ---------------------------------------------------------------------------
def test_irr_annualised_from_quarters():
    f = np.zeros(5)
    f[0], f[4] = -100, 110                                               # 4분기 후 110 → 연 10%
    assert pf.irr(f) == pytest.approx(0.10, abs=1e-10)
    assert pf.irr(np.array([100.0, 50.0])) is None                       # 부호 변화 없음
    assert pf.payback(np.array([-100.0, 30, 30, 30, 30])) == pytest.approx((3 + 1 / 3) / 4)


def test_all_equity_equity_irr_equals_project_irr():
    inp = replace(BASE_INP, construction_quarters=4)
    r = pf.run(inp)
    zero = pf.stress(r, pf.Stress())                                     # 기준 재현
    assert zero.equity_irr == pytest.approx(r.equity_irr)
    # 대출 0 케이스: 목표 DSCR을 매우 높여 한도 0에 가깝게 → 자기자본 = 프로젝트
    r0 = pf.run(replace(inp, target_dscr=1e9))
    assert r0.debt < 1e-3 * r0.cons.uses
    assert r0.equity_irr == pytest.approx(r0.project_irr, abs=1e-6)


def test_exit_value_raises_irr():
    assert pf.run(VARIANTS["exit_value"]).equity_irr > pf.run(BASE_INP).equity_irr


def test_fx_conversion():
    assert pf.usd_mn_to_krw_100m(1.0, 1332.1) == pytest.approx(13.321)  # 1 USD mn = 13.321억원
    assert pf.usd_mn_to_krw_100m(100.0, 1400.0) == pytest.approx(1400.0)


# ---------------------------------------------------------------------------
# 스트레스·손익분기·히트맵
# ---------------------------------------------------------------------------
def test_stress_fixed_schedule_and_directions():
    inp = replace(BASE_INP, tax_rate=0.0)                                # 세금 시점 효과 제거
    b = pf.run(inp)
    same = pf.stress(b, pf.Stress())
    assert same.min_dscr == pytest.approx(b.min_dscr) and same.debt == pytest.approx(b.debt)
    assert pf.stress(b, pf.Stress(rent_mult=0.9)).min_dscr < b.min_dscr < pf.stress(b, pf.Stress(rent_mult=1.1)).min_dscr
    assert pf.stress(b, pf.Stress(rate_shift=0.01)).min_dscr < b.min_dscr
    cap = pf.stress(b, pf.Stress(capex_mult=1.2))
    assert cap.debt == pytest.approx(b.debt * cap.cons.uses / b.cons.uses, rel=1e-3) and cap.min_dscr < b.min_dscr
    dl = pf.stress(b, pf.Stress(delay_quarters=4))
    assert dl.cons.cod_quarter == inp.construction_quarters + 4 and dl.cons.idc > b.cons.idc
    for s in (cap, dl):
        assert abs(pf.identity_checks(s)["cash_waterfall"]) < 1e-9 * s.cons.uses


def test_breakeven_hits_level_nearest_base():
    b = pf.run(replace(BASE_INP, tax_rate=0.0))
    x = pf.breakeven(b, "rent_mult", 1.0, 0.2, 2.0, near=1.0)
    assert x is not None and x < 1.0
    assert pf.stressed_metric(b, "rent_mult", x) == pytest.approx(1.0, abs=1e-6)
    assert pf.breakeven(b, "delay_quarters", 0.01, 0, 8) is None        # 교차 없음


def test_heatmap_and_tornado_shapes():
    b = pf.run(replace(BASE_INP, tax_rate=0.0))
    hm = pf.heatmap(b, [0.9, 1.0, 1.1], [1.0, 1.2])
    assert hm.shape == (3, 2) and hm.loc[1.0, 1.0] == pytest.approx(b.min_dscr)
    assert hm.loc[0.9, 1.2] < hm.loc[1.1, 1.0]
    t = pf.tornado(b, {"rent": (pf.Stress(rent_mult=0.9), pf.Stress(rent_mult=1.1)),
                       "rate": (pf.Stress(rate_shift=0.01), pf.Stress(rate_shift=-0.01))})
    assert list(t.columns) == ["variable", "low", "high", "base", "span"] and t["span"].is_monotonic_decreasing


# ---------------------------------------------------------------------------
# 실물옵션 (LSM)
# ---------------------------------------------------------------------------
def _opt(n=3000, p=0.3):
    return ro.OptionInputs(phase2=replace(BASE_INP, prelease=0.2), phase1_prelease=0.2,
                           scenarios={"downside": {"ramp_growth": 0.049}, "base": {"ramp_growth": 0.101}, "upside": {"ramp_growth": 0.137}},
                           weights={"downside": 1 / 3, "base": 1 / 3, "upside": 1 / 3}, approval_prob=p,
                           decision_year=2, window_years=4, rent_volatility=0.15, n_paths=n, seed=42)


def test_option_value_linear_in_probability_and_reproducible():
    o = _opt()
    r1 = ro.value(o, [0.0, 0.5, 1.0], [500, 1000, 3000])
    r2 = ro.value(o, [0.0, 0.5, 1.0], [500, 1000, 3000])
    assert r1.value == r2.value                                          # seed 고정 → 재현
    assert r1.value == pytest.approx(0.3 * r1.value_conditional)
    bp = r1.by_prob.set_index("approval_prob")["value"]
    assert bp[0.0] == 0 and bp[1.0] == pytest.approx(r1.value_conditional) and bp[0.5] == pytest.approx(0.5 * bp[1.0])
    assert r1.value_conditional >= 0                                     # 옵션은 음수가 될 수 없다


def test_option_convergence_stderr_shrinks():
    r = ro.value(_opt(), [0.3], [500, 2000, 3000])
    se = list(r.convergence["stderr"])
    assert se[0] > se[1] > se[2]
    assert abs(r.convergence["value_conditional"].iloc[-1] - r.value_conditional) < 1e-9


def test_option_npv_increases_with_rent():
    o = _opt()
    lo, hi = ro.npv_at(o, 2, 150_000, "base"), ro.npv_at(o, 2, 350_000, "base")
    assert hi > lo
    r = ro.value(o, [0.3], [3000])
    be = r.breakeven_rent["base"]
    if be is not None:
        assert ro.npv_at(o, 2, be, "base") == pytest.approx(0.0, abs=abs(hi - lo) * 0.02)


# ---------------------------------------------------------------------------
# 누진세 · 선형 램프업 · OPEX 비율 · 임대 기간 · 감가상각 미반영 · 이자 현금 지급 진단
# ---------------------------------------------------------------------------
KR_BRACKETS = ((2, 0.10), (200, 0.20), (3000, 0.22), (float("inf"), 0.25))   # 억원 상한 (2026 사업연도~)


def test_progressive_tax_korea():
    assert pf.progressive_tax(1.0, KR_BRACKETS) == pytest.approx(0.1)
    assert pf.progressive_tax(300.0, KR_BRACKETS) == pytest.approx(2 * 0.1 + 198 * 0.2 + 100 * 0.22)
    assert pf.progressive_tax(300.0, KR_BRACKETS, 0.10) == pytest.approx((0.2 + 39.6 + 22) * 1.1)   # + 지방소득세 10%
    assert pf.progressive_tax(4000.0, KR_BRACKETS) == pytest.approx(0.2 + 39.6 + 2800 * 0.22 + 1000 * 0.25)
    tax = pf.tax_schedule(np.array([-100.0, 400.0]), np.zeros(2), 0.0, KR_BRACKETS, 0.10)
    assert tax[0] == 0 and tax[1] == pytest.approx(pf.progressive_tax(300.0, KR_BRACKETS, 0.10))   # 결손 이월 후


def test_linear_ramp_opex_ratio_and_lease_term():
    inp = replace(BASE_INP, prelease=0.2, stabilized_occupancy=0.9, ramp_years=3, opex_per_kw_year=0.0, opex_ratio=0.2,
                  opex_escalation=0.025, lease_term_years=10)
    o = pf.operations(inp)
    assert list(o["occupancy"][:5]) == pytest.approx([0.2, 0.2 + 0.7 / 3, 0.2 + 1.4 / 3, 0.9, 0.9])
    opex1 = 0.2 * 0.9 * inp.kw * inp.rent_per_kw_month * 12 / inp.money_scale       # 안정화 매출의 20%
    assert o["opex"].iloc[0] == pytest.approx(opex1) and o["opex"].iloc[1] == pytest.approx(opex1 * 1.025)
    assert (o["contracted_occupancy"][:10] == 0.2).all() and (o["contracted_occupancy"][10:] == 0).all()
    st = pf.operations(inp, pf.Stress(rent_mult=0.8, opex_mult=1.2))
    assert st["opex"].iloc[0] == pytest.approx(opex1 * 1.2)                           # OPEX는 임대료 스트레스와 무관
    b = replace(inp, ramp_years=1)
    assert list(pf.operations(b)["occupancy"][:3]) == pytest.approx([0.2, 0.9, 0.9])


def test_no_depreciation_when_life_missing():
    r0 = pf.run(replace(BASE_INP, dep_years=None))
    r1 = pf.run(BASE_INP)
    assert (r0.ops["depreciation"] == 0).all() and r0.ops["tax"].sum() > r1.ops["tax"].sum()
    assert np.isnan(pf.run(replace(BASE_INP, discount_rate=None)).equity_npv)


def test_interest_cover_cap_and_negative_amortization():
    inp = replace(BASE_INP, prelease=0.2, ramp_years=3, opex_per_kw_year=0.0, opex_ratio=0.2, max_gearing=0.65, tax_rate=0.0)
    r = pf.run(inp)
    neg = pf.negative_amortization_years(r)
    assert neg and neg[0] == 1
    cap = pf.interest_cover_cap(r)
    assert 0 < cap < r.debt
    o = r.ops.iloc[: inp.tenor_years]
    scaled_interest = o["interest"] * cap / r.debt                                       # 같은 모양으로 비례 축소
    assert (o["cfads"] >= inp.target_dscr * scaled_interest - 1e-9).all()
    assert pf.interest_cover_cap(pf.run(BASE_INP)) == pytest.approx(pf.run(BASE_INP).debt)   # 램프업 없으면 제약 없음


def test_opex_stress_direction():
    b = pf.run(replace(BASE_INP, tax_rate=0.0, opex_ratio=0.2))
    assert pf.stress(b, pf.Stress(opex_mult=1.2)).min_dscr < b.min_dscr < pf.stress(b, pf.Stress(opex_mult=0.8)).min_dscr


# ---------------------------------------------------------------------------
# 램프업 이자유보계좌 · 전력단가 인상 · 계약 매출 sizing · 원가 대비 수익률
# ---------------------------------------------------------------------------
def test_ramp_up_interest_reserve():
    inp = VARIANTS["grace_reserve"]
    r = pf.run(inp)
    o, g = r.ops, inp.grace_years
    gap = float(np.maximum(o["interest"][:g] - o["cfads"][:g], 0).sum())
    assert gap > 0 and r.cons.reserve_initial == pytest.approx(gap * 1.1, rel=1e-6)   # 부족분 합계 + 10%
    assert r.cons.uses == pytest.approx(r.cons.capex + r.cons.idc + r.cons.dsra_initial + r.cons.reserve_initial)
    assert (o["principal"][:g].abs() < 1e-9).all() and np.allclose(o["debt_service"][:g], o["interest"][:g])  # 이자만
    assert r.reserve_used == pytest.approx(gap) and o["shortfall"].sum() == pytest.approx(0.0)   # 기준 시나리오: 유보계좌로 충당
    assert o["reserve_release"].sum() == pytest.approx(r.cons.reserve_initial - gap)        # 남은 10%는 거치 마지막 해 해제
    assert not pf.negative_amortization_years(r)                                            # 이자 원금 가산 없음
    assert r.min_icr_grace < 1 and r.min_dscr >= inp.target_dscr - 1e-9                     # DSCR = 상환 기간 기준
    assert r.avg_dscr == pytest.approx(r.min_dscr)                                          # sculpting: 상환 기간 DSCR 일정
    assert r.min_dscr == pytest.approx(np.nanmin(o["dscr"][g:inp.tenor_years]))
    for k, v in pf.identity_checks(r).items():
        assert abs(v) < 1e-6 * r.cons.uses, (k, v)
    # 같은 조건에서 거치기간 이자를 현금으로만 내면(paid) 거치기간 DSCR 제약 때문에 대출이 0에 가깝다
    assert pf.run(replace(inp, grace_interest="paid")).debt < r.debt
    # 스트레스: 유보계좌는 FC 적립액 그대로 → 사전 임대율이 더 낮으면 소진 후 DSRA 인출
    lo = pf.stress(r, pf.Stress(prelease=0.05))
    assert lo.cons.reserve_initial == r.cons.reserve_initial and lo.reserve_used == pytest.approx(r.cons.reserve_initial)
    assert lo.ops["dsra_draw"].sum() > 0


def test_power_escalation_and_gross_rent():
    inp = replace(VARIANTS["power_gross"], prelease=0.9, ramp_years=0)
    o = pf.operations(inp)
    base_kwh = 0.9 * inp.kw * 0.7 * 8760 * 1.3
    assert o["power_cost"].iloc[0] == pytest.approx(base_kwh * 180 / 1e8)
    assert o["power_cost"].iloc[5] == pytest.approx(base_kwh * 180 * 1.02 ** 5 / 1e8)
    assert o["net_power"].iloc[0] == pytest.approx(-o["power_cost"].iloc[0])                 # 패스스루 0% → SPC 전액 부담
    pt = pf.run(replace(inp, power_passthrough=1.0))
    assert pt.debt > pf.run(inp).debt and pf.yield_on_cost(pt) > pf.yield_on_cost(pf.run(inp))
    cut = pf.operations(inp, pf.Stress(power_mult=0.9))
    assert cut["power_cost"].iloc[0] == pytest.approx(0.9 * o["power_cost"].iloc[0])


def test_contracted_sizing_lowers_debt_and_hits_target_on_contracted():
    inp = replace(VARIANTS["contracted_sizing"], max_gearing=0.95)
    r_c, r_t = pf.run(inp), pf.run(replace(inp, sizing_basis="total"))
    assert r_c.binding == "dscr" and r_c.debt < r_t.debt
    assert r_c.min_dscr_contracted == pytest.approx(inp.target_dscr)
    assert r_c.min_dscr > inp.target_dscr
    with pytest.raises(ValueError):
        replace(inp, sizing_basis="bogus")


def test_yield_on_cost_definition():
    inp = replace(BASE_INP, ramp_years=3, prelease=0.3)
    r = pf.run(inp)
    assert pf.yield_on_cost(r) == pytest.approx(float(r.ops["ebitda"].iloc[3]) / r.cons.uses)  # 램프업 3년 → 4년차


def test_irr_ex_terminal_value():
    r = pf.run(VARIANTS["exit_value"])
    assert r.terminal_value > 0
    f = r.equity_flows["flow"].to_numpy().copy()
    f[-1] -= r.terminal_value
    assert r.equity_irr_ex_tv == pytest.approx(pf.irr(f)) and r.equity_irr_ex_tv < r.equity_irr
    assert r.project_irr_ex_tv < r.project_irr
    r0 = pf.run(BASE_INP)                                                  # 잔존가치 없음 → 같은 값
    assert r0.terminal_value == 0 and r0.equity_irr_ex_tv == r0.equity_irr
    assert r0.project_irr_ex_tv == pytest.approx(pf.run(replace(VARIANTS["exit_value"], exit_cap_rate=None)).project_irr)


def test_gearing_basis_capex_vol02():
    """최대 대출 비율 분모 = CAPEX(금융비용 IDC·이자유보계좌·DSRA 제외): 상한이 구속하면 대출 = 비율 × CAPEX,
    금리·유보계좌와 무관하므로 수요 시나리오가 달라도 대출이 같다. 기존 두 방식(총사업비, CAPEX+DSRA)은 민감도로 함께 계산."""
    from src.data_fetch.base import load_config
    from research.vol02 import data as D
    cfg = load_config()
    f = D.load_facts(cfg)
    a = f.cases["A"]
    b = a.base
    assert a.inp.gearing_basis == cfg["research"]["vol02"]["gearing_basis"] == "capex"
    assert set(a.gearing_alt) == {"total", "ex_financing"}
    if b.binding == "gearing":
        assert b.debt == pytest.approx(a.inp.max_gearing * b.cons.capex, rel=1e-6)
        assert b.gearing_cap_basis == pytest.approx(a.inp.max_gearing, rel=1e-6)
        assert len({round(x.debt, 6) for x in a.scenarios.values()}) == 1                     # 시나리오와 무관
    tot, exf = a.gearing_alt["total"]["base"], a.gearing_alt["ex_financing"]["base"]
    assert tot.gearing == pytest.approx(a.inp.max_gearing, rel=1e-6)                            # 기존: 총사업비의 65%
    assert tot.debt >= exf.debt >= b.debt                                                        # 분모가 작을수록 대출 감소
    assert a.gearing_alt["total"]["scenarios"]["downside"].debt > tot.debt                       # 총사업비 기준의 왜곡(기록용)
