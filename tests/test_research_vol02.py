"""KSJ Research Vol.2 (데이터센터 PF) 테스트 — 네트워크 없이 실행. 입력은 tmp_path의 합성 데이터와 합성 가정(테스트 전용)."""
from __future__ import annotations

import copy
import csv
import math
import re
from pathlib import Path

import pandas as pd
import pytest

from research.vol02 import data as D
from src.analysis.pf_model import usd_mn_to_krw_100m
from src.data_fetch import base

IEA_ROWS = [("dc_electricity_consumption", "2024", "415"), ("dc_electricity_consumption_base", "2030", "945"),
            ("dc_electricity_consumption_base", "2035", "1200"), ("dc_electricity_consumption_range_low", "2035", "700"),
            ("dc_electricity_consumption_range_high", "2035", "1700"), ("dc_demand_growth_yoy", "2025", "17"),
            ("ai_dc_demand_growth_yoy", "2025", "50")]
PEERS = [("267260", "HD현대일렉트릭", (20000, 1300), (40000, 9700)), ("010120", "LS ELECTRIC", (33000, 1900), (49000, 4200)),
         ("298040", "효성중공업", (35000, 1400), (59000, 7400))]

# 테스트용 합성 가정 (사실 주장 아님 — 엔진·레이아웃 검증 전용)
SYNTH = {
    "A": dict(capex_per_mw=150, power_equipment_share=0.4, construction_quarters=8, stabilized_occupancy=0.9,
              opex_per_kw_year=300000, opex_escalation=0.02, tax_rate_national=0.24, dep_years=20, operating_years=20,
              margin_bp=200, target_dscr=1.3, max_gearing=0.7, tenor_years=15, grace_years=2, grace_interest="capitalized",
              dsra_months=6, discount_rate=0.09, grid_approval_prob=0.3, approval_decision_year=2, option_window_years=4,
              rent_volatility=0.15),
    "B": dict(capex_per_mw=11, power_equipment_share=0.4, construction_quarters=8, rent_per_kw_month=130, rent_escalation=0.03,
              prelease=0.6, stabilized_occupancy=0.95, opex_per_kw_year=150, opex_escalation=0.025, dep_years=20,
              operating_years=20, margin_bp=225, target_dscr=1.35, max_gearing=0.65, tenor_years=15, grace_years=1,
              dsra_months=6, discount_rate=0.1, pue=1.3, it_load_factor=0.7),
}


def write_inputs(cfg, tmp: Path):
    inp = cfg["research"]["vol02"]["inputs"]
    paths = {k: (tmp / f"{k}.csv") for k in ("iea", "ktb", "fx", "fred", "eia_state", "eia_va_price")}
    paths["dart"] = [tmp / "dart0.csv", tmp / "dart1.csv"]
    paths["eia_sectors"] = [tmp / "sec0.csv", tmp / "sec1.csv"]
    for k, v in paths.items():
        inp[k] = [str(x) for x in v] if isinstance(v, list) else str(v)
    pd.DataFrame([{"metric": m, "period": p, "value": v, "unit": "x"} for m, p, v in IEA_ROWS]).to_csv(paths["iea"], index=False)
    days = ["2026-09-30", "2026-10-15", "2026-10-20", "2026-10-21"]
    pd.DataFrame({"date": days, "ktb_3y": [3.9, 3.86, 3.84, 9.99], "ktb_10y": [4.3, 4.2, 4.176, 9.99]}).to_csv(paths["ktb"], index=False)
    pd.DataFrame({"date": days, "usdkrw": [1350.0, 1338.6, 1332.1, 9999.0]}).to_csv(paths["fx"], index=False)
    pd.DataFrame({"date": ["2026-09-30", "2026-10-16", "2026-10-21"], "DGS10": [4.9, 5.09, 9.99]}).to_csv(paths["fred"], index=False)
    rows0, rows1 = [], []
    for t, nm, (r0, o0), (r1, o1) in PEERS:
        rows0.append({"company": nm, "ticker": t, "fiscal_year": "FY2025A", "revenue": r1, "operating_income": o1})
        rows1.append({"company": nm, "ticker": t, "fiscal_year": "FY2022A", "revenue": r0, "operating_income": o0})
    pd.DataFrame(rows0).to_csv(paths["dart"][0], index=False)
    pd.DataFrame(rows1).to_csv(paths["dart"][1], index=False)
    st = []
    for y in range(2015, 2026):
        st += [{"period": y, "stateid": "VA", "sectorid": "COM", "sales": 100 * 1.06 ** (y - 2015)},
               {"period": y, "stateid": "US", "sectorid": "COM", "sales": 1000 * 1.01 ** (y - 2015)}]
    pd.DataFrame(st).to_csv(paths["eia_state"], index=False)
    pd.DataFrame([{"period": y, "stateid": "US", "sectorid": "COM", "sales": 1, "price": 10 + 0.3 * (y - 2015)}
                  for y in range(2015, 2026)]).to_csv(paths["eia_sectors"][1], index=False)   # 폴백 파일만 존재
    return paths


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(base.load_config())
    c["paths"]["processed"] = str(tmp_path / "processed")
    c["research"]["vol02"]["assumptions_csv"] = str(tmp_path / "vol02_assumptions.csv")
    c["research"]["vol02"]["real_option"].update(n_paths=400, convergence_paths=[100, 200, 400])
    write_inputs(c, tmp_path)
    return c


def filled(cfg):
    c = copy.deepcopy(cfg)
    for case, kv in SYNTH.items():
        for k, v in kv.items():
            c["research"]["vol02"]["cases"][case]["params"][k]["value"] = v
    return c


# ---------------------------------------------------------------------------
# 가정: CSV 입력·단위·세율·양식
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, unit, expected", [("2.5", "%", 0.025), ("23.5", "%/년", 0.235), ("200", "bp", 200.0),
                                                 ("250,000", "원/kW·월", 250000.0), ("paid", "-", "paid"), ("", "%", None),
                                                 ("10", "법인세 대비 %", 0.10)])
def test_csv_value_conversion(raw, unit, expected):
    v = D.csv_to_value(raw, unit)
    assert v == (pytest.approx(expected) if isinstance(expected, float) else expected)
    if isinstance(expected, float):
        assert D.csv_to_value(D.value_to_csv(v, unit), unit) == pytest.approx(expected)


def test_assumption_defaults_and_derivations(cfg):
    a = D.load_assumptions(cfg)
    p = a["A"]["prelease"]
    assert p.value == pytest.approx((0.16 + 0.235) / 2) and p.origin == "derived"
    assert a["A"]["rent_per_kw_month"].value == 250000 and a["A"]["rent_per_kw_month"].status == "verify"
    assert a["A"]["capex_per_mw"].value is None and a["A"]["capex_per_mw"].status == "input"
    assert a["B"]["tax_rate"].value == pytest.approx(0.21 + 0.06 * (1 - 0.21))             # 주세 연방 공제
    assert a["A"]["tax_rate"].value is None                                               # 법인세율 null → 합산 null


def test_csv_overrides_values_and_sources(cfg):
    rows = [{"case": "A", "item": "tax_rate_national", "value": "24", "unit": "%", "source_name": "법인세법 제55조",
             "url": "https://law.go.kr", "published": "2025-12", "page": ""},
            {"case": "A", "item": "rent_per_kw_month", "value": "", "unit": "원/kW·월", "source_name": "",
             "url": "https://example.org/news", "published": "2025-06-01", "page": "3"},
            {"case": "B", "item": "margin_bp", "value": "225", "unit": "bp", "source_name": "", "url": "", "published": "", "page": ""}]
    with open(cfg["research"]["vol02"]["assumptions_csv"], "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=D.CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    a = D.load_assumptions(cfg)
    assert a["A"]["tax_rate_national"].value == pytest.approx(0.24) and a["A"]["tax_rate_national"].origin == "csv"
    assert a["A"]["tax_rate"].value == pytest.approx(0.24 * 1.10)                         # 법인세 × (1 + 지방소득세 10%)
    r = a["A"]["rent_per_kw_month"]
    assert r.value == 250000 and r.url == "https://example.org/news" and r.status == "sourced"   # 값 없이 출처만 보강
    assert a["B"]["margin_bp"].value == 225 and a["B"]["margin_bp"].source is None          # 출처 미기재 → 요약에 표시


def test_write_template_preserves_user_entries(cfg):
    path = Path(cfg["research"]["vol02"]["assumptions_csv"])
    D.write_template(cfg)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert list(df.columns) == D.CSV_COLUMNS
    assert {"A", "B"} == set(df["case"]) and (df["item"] == "capex_per_mw").sum() == 2
    row = df[(df["case"] == "A") & (df["item"] == "rent_per_kw_month")].iloc[0]
    assert row["current"] == "250000" and "CBRE" in row["hint"]
    assert df[(df["case"] == "A") & (df["item"] == "capex_per_mw")].iloc[0]["current"] == "null"
    df.loc[(df["case"] == "A") & (df["item"] == "capex_per_mw"), ["value", "source_name"]] = ["150", "DART 신규시설투자 공시"]
    df.to_csv(path, index=False, encoding="utf-8-sig")
    D.write_template(cfg)
    df2 = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    r2 = df2[(df2["case"] == "A") & (df2["item"] == "capex_per_mw")].iloc[0]
    assert r2["value"] == "150" and r2["source_name"] == "DART 신규시설투자 공시" and r2["current"] == "150"


# ---------------------------------------------------------------------------
# Vol.1 데이터 연결
# ---------------------------------------------------------------------------
def test_data_links(cfg):
    d = D.demand(cfg)
    assert d.growth["base"] == pytest.approx((1200 / 415) ** (1 / 11) - 1)
    assert d.growth["downside"] < d.growth["base"] < d.growth["upside"]
    r = D.rates(cfg, "2026-10-20")
    assert (r.ktb_3y, r.ktb_10y, r.ktb_date) == (3.84, 4.176, "2026-10-20")                 # 기준일 이후 값 미사용
    assert (r.dgs10, r.dgs10_date, r.usdkrw) == (5.09, "2026-10-16", 1332.1)
    assert r.base("A", "construction", cfg) == pytest.approx(0.0384) and r.base("B", "term", cfg) == pytest.approx(0.0509)
    pp = D.peer_pricing(cfg)
    o0, o1 = 1300 / 20000, 9700 / 40000
    hd = pp.table.set_index("ticker").loc["267260"]
    assert hd["implied"] == pytest.approx((1 - o0) / (1 - o1) - 1)
    agg0 = (1300 + 1900 + 1400) / (20000 + 33000 + 35000)
    assert pp.agg_opm0 == pytest.approx(agg0) and pp.low <= pp.agg_implied <= pp.high
    va = D.virginia(cfg)
    assert va.va_cagr == pytest.approx(0.06) and va.us_cagr == pytest.approx(0.01)
    assert va.price_source == "US" and va.price_latest == (2025, pytest.approx(13.0))


def test_virginia_price_used_when_collected(cfg):
    pd.DataFrame([{"period": y, "stateid": "VA", "sectorid": "COM", "price": 9 + 0.2 * (y - 2015)} for y in range(2015, 2026)]
                 ).to_csv(cfg["research"]["vol02"]["inputs"]["eia_va_price"], index=False)
    va = D.virginia(cfg)
    assert va.price_source == "VA" and va.price_latest[1] == pytest.approx(11.0)
    a = D.load_assumptions(cfg)
    p = D.case_power_price("B", a["B"], va)
    assert p.value == pytest.approx(0.11) and p.origin == "data" and "Virginia" in p.source


def test_implied_price_rise_formula():
    assert D.implied_price_rise(0.05, 0.15) == pytest.approx(0.95 / 0.85 - 1)
    assert D.implied_price_rise(0.1, 0.1) == 0


def test_grid_ratio_and_memo_mismatch(cfg):
    g = D.grid_stats(cfg)
    assert g.ratio == pytest.approx(1010 / 33592) and round(g.ratio * 100, 1) == 3.0
    assert g.memo_mismatch                                                               # 메모상 1.9%와 다름 → 원문 확인


# ---------------------------------------------------------------------------
# null → 계산 생략, 입력 → 결과
# ---------------------------------------------------------------------------
def test_null_assumptions_skip_calculations(cfg):
    f = D.load_facts(cfg)
    for c in ("A", "B"):
        u = f.cases[c]
        assert not D.ok(u) and "capex_per_mw" in u.missing
    assert not D.ok(f.option)
    assert "MW당 CAPEX" in D.fmt_missing(f.cases["A"].missing)


def test_filled_cases_run_and_check(cfg):
    f = D.load_facts(filled(cfg))
    for c in ("A", "B"):
        cr = f.cases[c]
        assert D.ok(cr), getattr(cr, "missing", None)
        for k, v in cr.checks.items():
            assert abs(v) < 1e-6 * cr.base.cons.uses, (c, k, v)
        assert set(cr.scenarios) == set(D.SCENARIOS)
        assert cr.scenarios["downside"].debt <= cr.scenarios["upside"].debt
        assert cr.base.inp.base_rate_term == pytest.approx(0.04176 if c == "A" else 0.0509)
    a = f.cases["A"]
    assert a.capex_stress["high"] == pytest.approx(1 + 0.4 * f.peers.high)
    assert a.heatmap is not None and f.cases["B"].heatmap is None
    be = a.breakeven
    assert set(be["variable"]) == {"rent_mult", "occ_mult", "prelease", "capex_mult", "rate_shift", "delay_quarters"}
    assert D.ok(f.option) and f.option.result.value == pytest.approx(0.3 * f.option.result.value_conditional)
    assert f.assumptions["B"]["power_price"].value == pytest.approx(0.13)                  # EIA 미국 상업용 13¢ 대용


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------
def _texts(pages):
    out = []
    for pg in pages:
        out += [pg.title, pg.subtitle] + [t for _, _, t, _ in pg.toc]
        for c in pg.cells:
            out += [c.title, c.note, c.unit, c.panel_lead, c.strip] + (c.bullets or [])
            if c.placeholder:
                out += list(c.placeholder)
            if c.table:
                out += c.table.header + [str(v) for r in c.table.rows for v in r]
        for b in pg.boxes:
            out += [b.number, b.caption, b.title] + b.bullets
        out += [str(v) for v in pg.extra.get("items", [])]
    return out


PUBLIC_FORBIDDEN = ["config", "ASSUMPTION", "TODO", ".meta.json", "data/manual", "data/raw", "회색 박스", "(저자 견해)",
                    "(author's view)", "null", "python -m"]


def test_josa():
    from research.vol02.story import josa
    assert josa("사전 임대율") == "사전 임대율이" and josa("임대료 ±10%") == "임대료 ±10%가"
    assert josa("건설 지연") == "건설 지연이" and josa("CAPEX(전력기기 가격)") == "CAPEX(전력기기 가격)가"


@pytest.mark.parametrize("fill", [False, True])
def test_story_public_text_and_numbers(cfg, fill):
    pytest.importorskip("matplotlib")
    from research.vol02.story import Story
    c = filled(cfg) if fill else cfg
    f = D.load_facts(c)
    for lang in ("kr", "en"):
        st = Story(c, f, lang)
        pages = st.pages()
        assert len(pages) == 17
        texts = [t for t in _texts(pages) + list(st.sources().values()) + [st.footer()] if t]
        joined = "\n".join(texts)
        bad = [w for w in PUBLIC_FORBIDDEN if w in joined]
        assert not bad, (lang, bad)
        if lang == "en":
            leaks = [t for t in texts if re.search(r"[가-힣]", t)]
            assert not leaks, leaks[:3]
        by = {p.label: p for p in pages}
        assert "Claude Code" in by["A5"].cells[0].strip and c["research"]["repo_url"] in by["A5"].cells[0].note
        assert len(by["A1"].cells[0].table.rows) == 8
        if lang == "kr":
            assert sum("본문의 판단은 저자 개인의 견해" in t for t in texts) >= 1
            assert "임대율가" not in joined and "지연가" not in joined
    kr = Story(c, f, "kr")
    by = {p.label: p for p in kr.pages()}
    if fill:
        a, b = f.cases["A"], f.cases["B"]
        assert kr.money("A", a.base.debt) in by["3"].title and kr.pct(a.base.gearing, 0) in by["3"].title
        p6 = {r[0]: r for r in by["6"].cells[0].table.rows}
        krw_b = usd_mn_to_krw_100m(b.base.debt, f.rates.usdkrw)
        assert p6["대출 한도 (원화 환산)"][2] == f"{krw_b:,.0f}억원"                         # 환율 환산 표시 검산
        assert p6["대출 한도 (현지 통화)"][2] == f"USD {b.base.debt:,.0f}mn"
        assert not [cell for p in kr.pages() for cell in p.cells if cell.placeholder]
    else:
        held = [cell for p in kr.pages() for cell in p.cells if cell.placeholder]
        assert held and all(cell.placeholder[0].startswith("입력 필요") for cell in held if cell.placeholder[0])
        assert "3.0%" in by["1"].subtitle                                                  # 데이터 기반 문장은 유지


@pytest.mark.parametrize("fill", [False, True])
def test_build_pdfs(cfg, tmp_path, fill):
    pytest.importorskip("matplotlib")
    pytest.importorskip("reportlab")
    from research.vol02.build import build
    out = tmp_path / "vol02"
    r = build(filled(cfg) if fill else cfg, out_dir=out)
    for lang in ("kr", "en"):
        raw = (out / f"KSJ_Research_Vol02_{lang.upper()}.pdf").read_bytes()
        n = len(re.findall(rb"/Type\s*/Page[^s]", raw))
        boxes = [tuple(float(x) for x in m.groups()) for m in re.finditer(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)]
        assert n == r["pages"][lang] == 17 and all(bx == (960, 720) for bx in boxes[:n])
    assert bool(r["pending"]["kr"]) != fill
    summary = (out / "build_summary.md").read_text(encoding="utf-8")
    assert "Vol.1 데이터 연결" in summary and "메모상 1.9%와 불일치" in summary
    assert ("검산 (회계 항등식" in summary) == fill


def test_vol01_roadmap_wording():
    pytest.importorskip("matplotlib")
    from research.vol01 import data as v1
    from research.vol01.story import Story
    cfg = base.load_config()
    f = v1.load_facts(cfg, "2026-10-20")
    for lang, s in (("kr", "Vol.2 데이터센터 PF(한국 40MW·미국 100MW), Vol.3 IPO 공모가·해외 피어"),
                    ("en", "Vol.2 data-centre PF (Korea 40 MW, U.S. 100 MW), Vol.3 IPO pricing and overseas peers")):
        by = {p.label: p for p in Story(cfg, f, lang).pages()}
        assert s in by["5"].title and s in by["5"].cells[2].title
        assert any(s in r[1] for r in by["A1"].cells[0].table.rows)


def test_fetch_extra_vol02_skips_without_key(cfg, monkeypatch, capsys):
    from research.vol02 import fetch_extra
    monkeypatch.setattr(base, "_DOTENV_LOADED", True)
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    monkeypatch.setattr(fetch_extra, "load_config", lambda path=None: cfg)
    assert fetch_extra.main([]) == 0 and "SKIPPED" in capsys.readouterr().out
    e = fetch_extra.eia_va_config(cfg)["data_fetch"]["eia"]
    assert e["state"] == ["VA", "US"] and e["data_fields"] == ["sales", "price"] and cfg["data_fetch"]["eia"]["state"] == "US"


def test_finite_helper():
    assert D.finite(1.0) and not D.finite(math.nan) and not D.finite(None)
