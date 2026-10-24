"""Vol.4 발전자산 모델 검산: LCOE 역산, sculpting DSCR, 가격 경로, 해지·손익분기."""
import math

import numpy as np
import pytest

from src.analysis import ppa_model as pm

BR = pm.parse_brackets("2:10,200:20,3000:22,inf:25")


def _asset(capex=None):
    capex = capex or pm.capex_from_lcoe(100, 0.15, 0.005, 25, 130.0, 0.045, 0.015, 0.02)
    return pm.Asset(100, 0.15, 0.005, capex, 0.015, 0.02, 25, 20, BR, 0.10)


def test_capex_from_lcoe_roundtrip():
    a = _asset()
    t = np.arange(1, 26)
    disc = 1.045 ** -t
    gen = pm.generation(a)
    lcoe = (a.capex + (pm.opex(a) * disc).sum()) / (gen * disc).sum() * 100      # 억원/GWh → 원/kWh
    assert lcoe == pytest.approx(130.0, rel=1e-9)


def test_generation_and_revenue_units():
    a = _asset()
    assert pm.generation(a)[0] == pytest.approx(100 * 1000 * 0.15 * 8760 / 1e6)      # 131.4 GWh
    r = pm.run("cfd", a, pm.Market(smp0=100, cfd_price=150), pm.Debt(0.05, 1.2, 0.8, 18))
    assert r.revenue[0] == pytest.approx(131.4 * 150 / 100)                          # 197.1억원


def test_price_paths():
    m = pm.Market(smp0=100, cfd_price=150, cfd_term=20, ppa_price=160, ppa_term=20)
    assert list(pm.price_path("cfd", m, 25)[[0, 19, 20]]) == [150, 150, 100]
    p = pm.price_path("ppa", m, 25, default_year=5)
    assert list(p[[0, 3, 4]]) == [160, 160, 100]                                     # 5년 차부터 SMP
    assert pm.price_path("merchant", m, 3).tolist() == [100, 100, 100]


def test_sculpting_hits_target_or_gearing_cap():
    a = _asset()
    m = pm.Market(smp0=110, cfd_price=147.686)
    for d in (pm.Debt(0.054, 1.2, 0.95, 18), pm.Debt(0.054, 1.2, 0.5, 18)):
        r = pm.run("cfd", a, m, d)
        assert r.debt <= a.capex * d.gearing + 1e-6
        assert r.min_dscr >= d.dscr - 1e-6
        if r.debt < a.capex * d.gearing - 1e-6:                                      # DSCR이 구속이면 매년 같은 DSCR
            dd = r.dscr[np.isfinite(r.dscr)]
            assert dd.max() - dd.min() < 1e-6
        assert np.allclose(r.cfads, r.ebitda - r.tax)
        sch = pm.pf.amortize(r.debt, r.ds[:d.tenor], d.rate)
        assert sch["closing"].iloc[-1] == pytest.approx(0, abs=1e-6)


def test_ppa_breakeven_and_termination_monotone():
    a = _asset()
    m = pm.Market(smp0=110, cfd_price=147.686, ppa_price=165)
    d = pm.Debt(0.054, 1.3, 0.75, 18)
    r0 = pm.run("ppa", a, m, d)
    irr = [pm.run("ppa", a, m, d, default_year=y, fixed_debt=(r0.debt, r0.ds)).irr for y in (2, 8, 15)]
    assert irr[0] < irr[1] < irr[2] < r0.irr                                         # 늦게 해지할수록 IRR ↑
    f = lambda p: pm.run("ppa", a, pm.Market(**{**m.__dict__, "ppa_price": p}), d).irr  # noqa: E731
    p = pm.solve(f, 100, 250, 0.07, tol=1e-4)
    assert f(p) == pytest.approx(0.07, abs=1e-4)


def test_expected_npv_hazard_zero_equals_plain():
    a = _asset()
    m = pm.Market(smp0=110, cfd_price=147.686, ppa_price=160)
    d = pm.Debt(0.054, 1.3, 0.75, 18)
    r0 = pm.run("ppa", a, m, d)
    assert pm.expected_npv_ppa(a, m, d, 0.0, 0.08, (r0.debt, r0.ds)) == pytest.approx(pm.npv(r0.equity_flows, 0.08))
    assert pm.expected_npv_ppa(a, m, d, 0.03, 0.08, (r0.debt, r0.ds)) < pm.npv(r0.equity_flows, 0.08)


def test_simulate_reproducible():
    a = _asset()
    m = pm.Market(smp0=110, cfd_price=147.686, ppa_price=160)
    debts = {"cfd": pm.Debt(0.054, 1.2, 0.8, 18), "ppa": pm.Debt(0.054, 1.3, 0.75, 18), "merchant": pm.Debt(0.054, 1.6, 0.55, 12)}
    sizing = {k: (lambda r: (r.debt, r.ds))(pm.run(k, a, m, debts[k])) for k in pm.ROUTES}
    spec = pm.MCSpec(40, 7, 0.2, 0.6, 0.05, 0.04, 0.02)
    x1, x2 = pm.simulate(a, m, debts, sizing, spec), pm.simulate(a, m, debts, sizing, spec)
    assert all(np.array_equal(x1[k], x2[k]) for k in pm.ROUTES)
    assert np.nanstd(x1["cfd"]) < np.nanstd(x1["merchant"])


def test_vol04_facts_build(tmp_path):
    from src.data_fetch.base import load_config
    from research.vol04 import data as D
    f = D.load_facts(load_config(), mc_n=0)
    p = {x["hazard"]: x for x in f.premium}
    assert p[0.0]["price"] < p[0.01]["price"] < p[0.05]["price"]                     # 해지 위험 ↑ → 필요 가격 ↑
    assert p[0.01]["max_fee"] == pytest.approx(f.corridor[1] - p[0.01]["price"])
    assert f.corridor[0] <= f.be_price <= f.corridor[1]
    assert all(f.inputs[k].tier in "ABCDJ" for k in f.inputs)
    assert all(f.inputs[k].official_todo for k in f.provisional)                      # 교체 대기 = 원문 할 일이 적힌 항목
    g = {(x["hazard"], x["spread"]): x["price"] for x in f.extra["premium_grid"]}
    assert g[(0.01, 0.0)] < g[(0.01, 0.01)] < g[(0.01, 0.02)]                          # 위험 스프레드 ↑ → 필요 가격 ↑
    assert f.asset.mw * 1000 <= f.V("dc_it_mw") * 1000 * f.V("dc_it_load") * f.V("dc_pue")   # 최대 출력 ≤ 데이터센터 평균 부하
    assert not any(x.tier == "C" for x in f.inputs.values())                           # 민간 2차 자료는 확정본에 없음
    assert f.lcoe_check["base_lcoe"] == pytest.approx(f.V("lcoe_target"))             # 사업비 = KEEI LCOE에 맞춘 값


def test_vol04_official_values_reproduce():
    """입력 파일의 공식값 = 원본 파일(전력거래소·한전)에서 다시 계산한 값."""
    from pathlib import Path
    from src.data_fetch.base import load_config, resolve_path
    from research.vol04 import data as D, sources as S
    if not list(Path(resolve_path(S.SRC)).glob("*가중평균SMP*.xlsx")):
        pytest.skip("공식 원본 파일 없음")
    r = S.run()
    I = D.load_inputs(resolve_path(load_config()["research"]["vol04"]["inputs_csv"]))
    assert float(I["kepco_industrial_price"].value) == pytest.approx(r["kepco_industrial_price"], abs=0.005)
    assert float(I["smp_base"].value) == pytest.approx(r["smp_base"], abs=0.05)
    assert float(I["smp_sigma"].value) == pytest.approx(r["smp_sigma"], abs=0.0005)
    assert float(I["smp_phi"].value) == pytest.approx(r["smp_phi"], abs=0.0005)
    assert r["hourly_match_err"] < 1.0                                                  # 시간별 파일 = 육지


def test_irr_handles_negative_terminal_flow():
    """끝 현금흐름이 음수여도(바닥 구간 재탐색) IRR을 찾는다."""
    f = np.array([-100.0] + [15.0] * 15 + [-5.0])
    r = pm.pf.irr(f, periods_per_year=1)
    assert r is not None and pm.npv(f, r) == pytest.approx(0, abs=1e-6)
