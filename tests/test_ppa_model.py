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
    assert f.be_price > f.corridor[0]                                                 # 한전 계약 IRR을 맞추려면 계약가보다 비싸야
    assert f.corridor[1] == pytest.approx(f.extra["tou"]["annual"])                   # 구매자 상한 = 태양광 시간대 회피 요금
    assert f.extra["avg_tariff"] == pytest.approx(f.V("kepco_industrial_price"))      # 평균 판매단가는 참고선·전력비 계산용
    assert f.dc["power_cost"] == pytest.approx(f.dc["consumption_gwh"] * f.V("kepco_industrial_price") / 100)
    assert p[0.01]["max_fee_avg"] - p[0.01]["max_fee"] == pytest.approx(f.V("kepco_industrial_price") - f.corridor[1])
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


# --- Vol.4 구매자 상한: 산업용(을) 계절·시간대별 요금 -------------------------------------------------
def _tou():
    import pandas as pd
    from src.data_fetch.base import load_config, resolve_path
    t = load_config()["research"]["vol04"]["tou"]
    rd = lambda k: pd.read_csv(resolve_path(t[k]), encoding="utf-8-sig")  # noqa: E731
    return rd("tariff_csv"), rd("bands_csv"), rd("solar_monthly_csv").set_index("month")["total_mwh"], t


def test_tou_tariff_csv_equals_hand_and_pdf():
    """요금 CSV = 손 입력 표 = (pdftotext가 있으면) PDF 8쪽 기계 추출, 개편 전후 차이 = PDF 머리 문구."""
    from research.vol04 import sources as S, tou as T
    rates, *_ = _tou()
    hand = T.rates_frame()
    key = ["regime", "voltage", "option", "season", "band"]
    j = rates.merge(hand, on=key, suffixes=("", "_h"))
    assert len(j) == len(hand) == 162
    assert (j["krw_per_kwh"] == j["krw_per_kwh_h"]).all() and (j["basic_krw_per_kw"] == j["basic_krw_per_kw_h"]).all()
    assert T.check_stated_change(hand) == []
    pdf = S.tou_from_pdf()
    if pdf is not None:
        m = T.rates_frame(pdf)
        jj = hand.merge(m, on=key, suffixes=("", "_p"))
        assert len(jj) == 162 and (jj["krw_per_kwh"] == jj["krw_per_kwh_p"]).all()
    # 원문 대표값 (PDF 8쪽): 고압A 선택Ⅱ 개편 후
    r = rates[(rates.regime == "after") & (rates.voltage == "고압A") & (rates.option == "선택Ⅱ")].set_index(["season", "band"])["krw_per_kwh"]
    assert (r[("spring_autumn", "mid")], r[("summer", "peak")], r[("winter", "off")]) == (133.4, 229.0, 123.0)


def test_tou_bands_reform_matches_text():
    """봄·여름·가을 평일: 11~12·13~15시 최대→중간, 18~21시 중간→최대 (PDF 2·3쪽), 겨울은 그대로."""
    _, bands, *_ = _tou()
    for s in ("summer", "spring_autumn"):
        b = bands[bands.season == s].pivot(index="hour", columns="regime", values="band")
        ch = b[b["before"] != b["after"]]
        assert sorted(ch.index[ch["after"] == "mid"]) == [11, 13, 14]
        assert sorted(ch.index[ch["after"] == "peak"]) == [18, 19, 20]
    w = bands[bands.season == "winter"].pivot(index="hour", columns="regime", values="band")
    assert (w["before"] == w["after"]).all()
    assert (bands.groupby(["regime", "season"]).size() == 24).all()


def test_solar_monthly_weights():
    _, _, sol, _ = _tou()
    assert list(sol.index) == list(range(1, 13))
    assert sol.sum() == pytest.approx(45_452_754, abs=1)                               # 월보 16-1, 2025년 합계


def test_solar_shape_and_days():
    from research.vol04 import tou as T
    sh = T.solar_hourly_shape(2025, 36.0, 127.0, 1.0)
    assert np.allclose(sh.sum(axis=1), 1.0)
    assert (sh[[0, 1, 2, 3, 21, 22, 23]].values == 0).all()                            # 밤 발전 없음
    assert sh.loc[7, list(range(0, 8))].sum() > sh.loc[1, list(range(0, 8))].sum()     # 여름은 아침 일찍 시작
    peak = {m: int(sh.loc[m].idxmax()) for m in range(1, 13)}
    assert all(p in (12, 13) for p in peak.values())                                   # 동경 127° → 태양 남중 12시 반 무렵
    d = T.day_counts(2025)
    assert d.sum().sum() == 365 and d.loc[1, "weekday"] == 23                          # 2025-01: 평일 23일


def test_avoided_rate_logic():
    """회피 요금 성질: 형상을 한 시간에 몰면 그 시간 요금, 할인 끄면 오르고, 개편 전이 개편 후보다 높다(낮 최대부하 → 중간)."""
    import pandas as pd
    from research.vol04 import tou as T
    rates, bands, sol, t = _tou()
    days = T.day_counts(2025)
    noon = pd.DataFrame(0.0, index=range(1, 13), columns=range(24))
    noon[12] = 1.0
    a = T.avoided_rate(rates, bands, sol, noon, days)
    wd = days.loc[4]
    exp_apr = (wd["weekday"] * 133.4 + wd["saturday"] * 133.4 * 0.5 + wd["sunday"] * 116.0 * 0.5) / wd.sum()   # 4월 12시: 평일 중간, 주말 50%
    assert a["month"][4] == pytest.approx(exp_apr)
    exp_jul = (days.loc[7, "weekday"] * 163.8 + days.loc[7, "saturday"] * 163.8 + days.loc[7, "sunday"] * 116.0) / days.loc[7].sum()
    assert a["month"][7] == pytest.approx(exp_jul)
    sh = T.solar_hourly_shape(2025, 36.0, 127.0, 1.0)
    base = T.avoided_rate(rates, bands, sol, sh, days)
    assert T.avoided_rate(rates, bands, sol, sh, days, discount=0.0)["annual"] > base["annual"]
    assert T.avoided_rate(rates, bands, sol, sh, days, regime="before")["annual"] > base["annual"]
    assert T.avoided_rate(rates, bands, sol, sh, days, saturday="peak_to_mid")["annual"] < base["annual"]
    assert base["season"]["spring_autumn"] < base["season"]["summer"] < base["season"]["winter"]
    w = np.array([sol[m] for m in range(1, 13)])
    assert base["annual"] == pytest.approx(float((np.array(list(base["month"].values())) * w).sum() / w.sum()))
    assert sum(base["gen_share"].values()) == pytest.approx(1.0)


def test_vol04_ceiling_three_stages():
    """구매자 상한 3단: 에너지요금 → +연료비조정(입력값) → +기후환경(값 없으면 None·TODO). 상한 = 가장 포괄적인 확보 단계, 여유 = 단계 − 필요 가격."""
    from src.data_fetch.base import load_config
    from research.vol04 import data as D
    f = D.load_facts(load_config(), mc_n=0)
    t = f.extra["tou"]
    st = dict(t["stages"])
    assert list(st) == ["energy", "fuel", "climate"]
    assert st["energy"] == pytest.approx(t["base"]["annual"])
    fa, ce = f.inputs["fuel_adj"].value, f.inputs["climate_env"].value
    assert st["fuel"] == pytest.approx(st["energy"] + float(fa))
    if isinstance(ce, (int, float)):
        assert st["climate"] == pytest.approx(st["fuel"] + float(ce))
    else:
        assert st["climate"] is None and f.inputs["climate_env"].pending_official      # 추정값 넣지 않음, TODO만
    last = [v for v in st.values() if v is not None][-1]
    assert f.corridor[1] == pytest.approx(last) and t["adder"] == pytest.approx(last - st["energy"])
    for p in f.extra["premium_grid"]:
        for k, v in st.items():
            m = p["max_fee_stage"][k]
            assert (m is None) if v is None else m == pytest.approx(v - p["price"])


def test_vol04_net_charge_breakdown():
    """공개 사례 부대비용 내역: 기후솔루션 표 2(인쇄 9쪽) 항목 그대로 파싱 — 총계 40 vs 항목 합 41(반올림), 기반기금 6.
    기반기금 요율이 비어 있으면 민감도는 None(TODO) — 숫자를 추정하지 않는다."""
    from src.data_fetch.base import load_config, resolve_path
    from research.vol04 import data as D
    cfg = load_config()
    I = D.load_inputs(resolve_path(cfg["research"]["vol04"]["inputs_csv"]))
    n = D.net_breakdown(cfg, I, 165.0)
    names = [k for k, _ in n["items"]]
    assert "복지/특례할인" in names and "거래수수료" in names and "기타" not in names
    assert n["total"] == pytest.approx(float(I["net_charge_example"].value))
    assert n["item_sum"] == pytest.approx(sum(v for _, v in n["items"]))
    assert n["fund"] == pytest.approx(dict(n["items"])["전력산업기반기금"])
    rate = I["power_fund_rate"].value
    if isinstance(rate, (int, float)):
        assert n["fund_add"] == pytest.approx(165.0 * rate / 100)
    else:
        assert n["fund_rate"] is None and n["fund_add"] is None and I["power_fund_rate"].pending_official
    # 요율이 주어지면 회피 요금 × 요율 (입력 사본으로만 검증)
    import dataclasses
    I2 = {**I, "power_fund_rate": dataclasses.replace(I["power_fund_rate"], value=2.0)}
    assert D.net_breakdown(cfg, I2, 150.0)["fund_add"] == pytest.approx(3.0)


def test_vol04_net_basis_note_like_for_like():
    """비교 기준 각주: 사례 성격·조건·표 위치, 직접 PPA 부담 항목(B), 상한에 추가 요금을 더한 것이 같은 기준, 기반기금 문장(요율 TODO)."""
    from src.data_fetch.base import load_config
    from research.vol04 import data as D
    from research.vol04.story import Story
    cfg = load_config()
    f = D.load_facts(cfg, mc_n=0)
    s = Story(cfg, f, "kr")
    full, short = s.net_basis_note(), s.net_basis_note(items_shown=False)
    nb = cfg["research"]["vol04"]["net_charge_basis"]
    for t in (full, short):
        assert nb["case_kr"] in t and nb["conditions_kr"] in t and "인쇄 9쪽(PDF 11쪽)" in t
        assert "망이용요금·거래수수료·부가정산금·전력산업기반기금" in t and "같은 기준 비교" in t
        assert f"{f.extra['tou']['adder']:,.1f}원을 더한" in t
    assert "항목 합 41" in full and "기준을 맞추면 여유가 기반기금만큼 커짐" in full
    assert "송배전 기본" not in short
