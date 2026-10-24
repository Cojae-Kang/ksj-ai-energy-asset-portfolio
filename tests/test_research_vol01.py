"""KSJ Research Vol.1 (가로형 보고서) 테스트 — 네트워크 없이 실행. 입력은 tmp_path의 테스트용 합성 데이터."""
from __future__ import annotations

import copy
import math
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.vol01 import data, fetch_extra
from research.vol01.data import Unavailable, ok
from research.vol01.fonts import resolve_fonts
from src.data_fetch import base

PEERS = [("267260", "HD현대일렉트릭", "HD Hyundai Electric"), ("010120", "LS ELECTRIC", "LS ELECTRIC"),
         ("298040", "효성중공업", "Hyosung Heavy Industries"), ("034020", "두산에너빌리티", "Doosan Enerbility")]

IEA_ROWS = [
    ("dc_electricity_consumption", "2024", "415"), ("dc_electricity_consumption_base", "2030", "945"),
    ("dc_electricity_consumption_base", "2035", "1200"), ("dc_electricity_consumption_range_low", "2035", "700"),
    ("dc_electricity_consumption_range_high", "2035", "1700"), ("dc_share_of_global_electricity", "2024", "1.5"),
    ("dc_consumption_growth_rate", "2017-2024", "12"), ("dc_regional_share_US", "2024", "45"),
    ("dc_regional_share_China", "2024", "25"), ("dc_regional_share_Europe", "2024", "15"),
    ("dc_demand_growth_yoy", "2025", "17"), ("ai_dc_demand_growth_yoy", "2025", "50"),
    ("global_electricity_demand_growth_yoy", "2025", "3"),
]


# ---------------------------------------------------------------------------
# 합성 입력 작성
# ---------------------------------------------------------------------------
def write_iea(path: Path, rows=IEA_ROWS):
    pd.DataFrame([{"metric": m, "period": p, "value": v, "unit": "x", "source": "IEA", "url": "u", "published": "2025-04"}
                  for m, p, v in rows]).to_csv(path, index=False)


def write_eia_state(path: Path, va=1.06, us=1.01, years=range(2015, 2026)):
    rows = []
    for y in years:
        rows += [{"period": y, "stateid": "VA", "sectorid": "COM", "sales": 100 * va ** (y - 2015)},
                 {"period": y, "stateid": "US", "sectorid": "COM", "sales": 1000 * us ** (y - 2015)}]
    pd.DataFrame(rows).to_csv(path, index=False)


def write_eia_sectors(path: Path):
    rows = []
    for y in range(2015, 2026):
        for s, base_, g, p in (("RES", 1400, 1.007, 12.6), ("COM", 1360, 1.009, 10.6), ("IND", 990, 1.005, 6.9)):
            rows.append({"period": y, "stateid": "US", "sectorid": s, "sales": base_ * 1000 * g ** (y - 2015),
                         "price": p * 1.025 ** (y - 2015)})
    pd.DataFrame(rows).to_csv(path, index=False)


def write_krx(path: Path, mcap0=(14581.0661075, 16530.0, 6928.139164, 97341.9750325),
              mcap1=(189247.45875, 246900.0, 180523.24928, 426613.723236),
              close0=(40450, 55100, 74300, 15250), close1=(525000, 164600, 1936000, 66600),
              sh0=(36047135, 30000000, 9324548, 638308033), sh1=(36047135, 150000000, 9324548, 640561146)):
    rows = []
    for i, (t, kr, en) in enumerate(PEERS):
        rows.append({"point": "start_2023", "bas_dd": "20230102", "company": kr, "company_en": en, "ticker": t,
                     "close_krw": close0[i], "market_cap_krw_100m": mcap0[i], "listed_shares": sh0[i]})
        rows.append({"point": "latest", "bas_dd": "20261019", "company": kr, "company_en": en, "ticker": t,
                     "close_krw": close1[i], "market_cap_krw_100m": mcap1[i], "listed_shares": sh1[i]})
    pd.DataFrame(rows).to_csv(path, index=False)


def write_actions(path: Path, ratio=5, after=150000000):
    pd.DataFrame([{"ticker": "010120", "company": "LS ELECTRIC", "event_date": "2026-04-13", "action": "stock_split",
                   "ratio": ratio, "shares_before": 30000000, "shares_after": after, "source": "test",
                   "verified_on": "2026-10-21", "notes": ""}]).to_csv(path, index=False)


def write_dart(path: Path, years=(2023, 2024, 2025), ni_scale=1.0, ni_override=None):
    ni = {2022: (1500, 1700, 900, 400), 2023: (2591.5, 2059.6, 1159.8, 556.0), 2024: (5015.7, 2387.2, 2226.3, 1113.7),
          2025: (7326.1, 2866.2, 5198.9, 847.6)}
    rows = []
    for y in years:
        for i, (t, kr, _) in enumerate(PEERS):
            n = ni[y][i] * ni_scale
            if ni_override and (t, y) in ni_override:
                n = ni_override[(t, y)]
            rows.append({"company": kr, "ticker": t, "fiscal_year": f"FY{y}A", "fs_div": "CFS", "revenue": 10000 * (i + 1) * (1 + (y - 2022) * 0.1),
                         "operating_income": 1000 * (i + 1) * (1 + (y - 2022) * 0.15), "net_income": n})
    pd.DataFrame(rows).to_csv(path, index=False)


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(base.load_config())
    c["paths"]["processed"] = str(tmp_path / "processed")
    c["paths"]["raw"] = str(tmp_path / "raw")
    c["data_fetch"]["output"]["cache"] = str(tmp_path / "cache")
    (tmp_path / "processed").mkdir()
    inp = c["research"]["vol01"]["inputs"]
    for k, v in list(inp.items()):
        inp[k] = [str(tmp_path / f"{k}_{i}.csv") for i in range(len(v))] if isinstance(v, list) else str(tmp_path / f"{k}.csv")
    return c


def p(cfg, key, i=0) -> Path:
    v = cfg["research"]["vol01"]["inputs"][key]
    return Path(v[i] if isinstance(v, list) else v)


def full_inputs(cfg, fy2022=True):
    write_iea(p(cfg, "iea"))
    write_eia_state(p(cfg, "eia_state"))
    write_eia_sectors(p(cfg, "eia_sectors", 1))      # 폴백 파일 경로(eia_retail_sales_annual 대응)
    write_krx(p(cfg, "krx_points"))
    write_actions(p(cfg, "corporate_actions"))
    write_dart(p(cfg, "dart", 0))
    if fy2022:
        write_dart(p(cfg, "dart", 1), years=(2022,))


# ---------------------------------------------------------------------------
# I~II 수요·현장
# ---------------------------------------------------------------------------
def test_demand_values_and_todo(cfg):
    write_iea(p(cfg, "iea"))
    d = data.demand(cfg)
    assert d.mult_2030 == pytest.approx(945 / 415) and d.region_other == pytest.approx(15)
    assert d.ai_vs_global == pytest.approx(50 / 3)
    rows = [r if r[0] != "dc_electricity_consumption_range_low" else (r[0], r[1], "TODO(data)") for r in IEA_ROWS]
    write_iea(p(cfg, "iea"), rows)
    assert data.demand(cfg).v["dc_2035_low"] is None


@pytest.mark.parametrize("va, us, verdict", [(1.06, 1.01, "ahead"), (1.00, 1.04, "behind"), (1.02, 1.02, "similar")])
def test_ground_verdict_follows_data(cfg, va, us, verdict):
    write_eia_state(p(cfg, "eia_state"), va, us)
    g = data.ground(cfg)
    assert g.verdict == verdict
    assert g.va_change_pct == pytest.approx((va ** 10 - 1) * 100)
    assert g.va_recent_cagr_pct == pytest.approx((va - 1) * 100)


def test_sectors_uses_fallback_file(cfg):
    assert isinstance(data.sectors(cfg), Unavailable)
    write_eia_sectors(p(cfg, "eia_sectors", 1))
    s = data.sectors(cfg)
    assert s.source_file == p(cfg, "eia_sectors", 1).name and list(s.sales.columns) == ["RES", "COM", "IND"]
    assert s.change_pct("price", "COM") == pytest.approx((1.025 ** 10 - 1) * 100)


# ---------------------------------------------------------------------------
# III 실적
# ---------------------------------------------------------------------------
def test_financials_merge_extra_year_and_loss_rule(cfg):
    write_dart(p(cfg, "dart", 0), ni_override={("034020", 2023): -100})
    fin = data.financials(cfg)
    assert fin.years == [2023, 2024, 2025] and fin.missing_years == [2022]
    assert math.isnan(fin.value("034020", 2024, "ni_yoy") or float("nan"))   # 직전 적자 → 증가율 없음
    write_dart(p(cfg, "dart", 1), years=(2022,))
    fin = data.financials(cfg)
    assert fin.years == [2022, 2023, 2024, 2025] and fin.missing_years == []
    assert fin.value("267260", 2025, "opm") == pytest.approx(1000 * 1.45 / (10000 * 1.3) * 100)


# ---------------------------------------------------------------------------
# IV 시장: 주식수·분할 검산, 합계 vs 평균
# ---------------------------------------------------------------------------
def test_market_split_and_share_checks(cfg):
    write_krx(p(cfg, "krx_points"))
    write_actions(p(cfg, "corporate_actions"))
    mk = data.market(cfg)
    t = mk.table.set_index("ticker")
    ls = t.loc["010120"]
    assert ls["share_note"] == "split_consistent" and ls["split_factor"] == 5
    assert ls["price_multiple_raw"] == pytest.approx(164600 / 55100)                 # 주가 2.99배
    assert ls["price_multiple_adj"] == pytest.approx(ls["multiple"], rel=1e-4)         # 분할 조정 = 시총 배수 14.9배
    assert round(ls["multiple"], 1) == 14.9
    assert t.loc["034020", "share_note"] == "changed_unexplained"                      # 두산 +0.35%
    assert t.loc["267260", "share_note"] == "unchanged"
    assert all(abs(t[c]).max() < 0.01 for c in ("mcap_check_t0", "mcap_check_t1"))   # 종가×주식수 = MKTCAP
    assert round(mk.total_multiple, 1) == 7.7 and round(mk.mean_multiple, 1) == 14.6
    assert mk.largest_t0["company"] == "두산에너빌리티" and round(mk.largest_t0_share) == 72
    assert [round(x, 1) for x in t["multiple"]] == [13.0, 14.9, 26.1, 4.4]


def test_market_split_mismatch_is_flagged(cfg):
    write_krx(p(cfg, "krx_points"))
    write_actions(p(cfg, "corporate_actions"), ratio=4)
    assert data.market(cfg).table.set_index("ticker").loc["010120", "share_note"] == "split_mismatch"


# ---------------------------------------------------------------------------
# 분해식: Δln(시총) = Δln(지배순이익) + Δln(PER)
# ---------------------------------------------------------------------------
def test_decomposition_identity_and_aggregate(cfg):
    full_inputs(cfg)
    f = data.load_facts(cfg, "2026-10-20")
    dc = f.decomp
    assert ok(dc) and dc.fy0 == "FY2022A" and dc.fy1 == "FY2025A"
    for _, r in dc.table[dc.table["valid"]].iterrows():
        assert r["dln_mcap"] == pytest.approx(r["dln_ni"] + r["dln_per"])               # 로그 항등식
        assert r["mcap_t1"] / r["mcap_t0"] == pytest.approx((r["ni1"] / r["ni0"]) * (r["per1"] / r["per0"]))
        assert r["earn_share"] + r["mult_share"] == pytest.approx(1.0)
        assert r["per0"] == pytest.approx(r["mcap_t0"] / r["ni0"])                       # 2023 초 시총 ↔ FY2022A
        assert r["per1"] == pytest.approx(r["mcap_t1"] / r["ni1"])                       # 최근 시총 ↔ FY2025A
    a = dc.agg
    assert a["earn_part"] + a["mult_part"] == pytest.approx(a["d_mcap"])
    assert a["dln_mcap"] == pytest.approx(math.log(a["mcap1"] / a["mcap0"]))
    assert dc.n_multiple_led == int((dc.table["dln_per"] > dc.table["dln_ni"]).sum())


def test_decomposition_requires_fy2022_and_handles_losses(cfg):
    full_inputs(cfg, fy2022=False)
    dc = data.load_facts(cfg, "2026-10-20").decomp
    assert isinstance(dc, Unavailable) and dc.command == data.CMD_DART and "FY2022A" in dc.reason_en
    write_dart(p(cfg, "dart", 1), years=(2022,), ni_override={("034020", 2022): -500})
    dc = data.load_facts(cfg, "2026-10-20").decomp
    assert dc.n_valid == 3 and not dc.table.set_index("ticker").loc["034020", "valid"]
    assert dc.agg["n_in_agg"] == 3


def test_valuation_current_per(cfg):
    full_inputs(cfg, fy2022=False)
    val = data.load_facts(cfg, "2026-10-20").val
    per = val.per.set_index("ticker")["per"]
    assert per["034020"] == pytest.approx(426613.723236 / 847.6)
    assert val.median_per == pytest.approx(per.median())
    assert val.growth_from == "FY2023A" and val.fy == "FY2025A"


# ---------------------------------------------------------------------------
# fetch_extra (네트워크 없음)
# ---------------------------------------------------------------------------
class FakeKrx:
    def __init__(self, open_days, peers):
        self.open, self.peers, self.calls = open_days, peers, []

    def fetch(self, name, bas_dd):
        self.calls.append(bas_dd)
        if bas_dd not in self.open:
            return []
        return [{"ISU_CD": pp["ticker"], "TDD_CLSPRC": "1000", "MKTCAP": str(1e12 * (i + 1)), "LIST_SHRS": "1"}
                for i, pp in enumerate(self.peers)]


def test_fetch_krx_points_first_and_prior_trading_day(cfg):
    fake = FakeKrx({"20230102", "20261016"}, cfg["peers"]["domestic"])
    res = fetch_extra.fetch_krx_points(cfg, "2026-10-20", client=fake)
    assert res.status == base.STATUS_SUCCESS and "20261020" not in fake.calls
    assert fake.calls[:2] == ["20230101", "20230102"]


def test_find_trading_day_gives_up(cfg):
    fake = FakeKrx(set(), cfg["peers"]["domestic"])
    with pytest.raises(base.FetchError):
        fetch_extra.find_trading_day(fake, date(2023, 1, 1), +1, 3, "t")


class FakeDart:
    def __init__(self):
        self.calls = []

    def fetch_corp_codes(self):
        pass

    def corp_code_for(self, ticker):
        return "C" + ticker

    def fetch_financials(self, corp_code, year, stock_code=""):
        self.calls.append((corp_code, year))
        rows = [{"rcept_no": "R", "sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "account_detail": "-", "thstrm_amount": "100000000000"},
                {"rcept_no": "R", "sj_div": "IS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "account_detail": "-", "thstrm_amount": "10000000000"},
                {"rcept_no": "R", "sj_div": "IS", "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent", "account_nm": "지배", "account_detail": "-", "thstrm_amount": "5000000000"}]
        return rows, "CFS"


def test_fetch_dart_extra_fy2022(cfg):
    fake = FakeDart()
    res = fetch_extra.fetch_dart_extra(cfg, "2026-10-20", client=fake)
    assert res.status == base.STATUS_SUCCESS and {y for _, y in fake.calls} == {2022}
    df = pd.read_csv(Path(cfg["paths"]["processed"]) / fetch_extra.DART_OUT, dtype={"ticker": str})
    assert set(df["fiscal_year"]) == {"FY2022A"} and df["net_income"].iloc[0] == pytest.approx(50.0)   # 원 → 억원
    assert list(df.columns)[:6] == ["company", "ticker", "corp_code", "fiscal_year", "fs_div", "rcept_no"]


def test_eia_configs(cfg):
    e = fetch_extra.eia_sectors_config(cfg)["data_fetch"]["eia"]
    assert e["sectors"] == ["RES", "COM", "IND"] and e["data_fields"] == ["sales", "price"] and e["start"] == "2015"
    s = fetch_extra.eia_state_config(cfg)["data_fetch"]["eia"]
    assert s["state"] == ["VA", "US"] and cfg["data_fetch"]["eia"]["state"] == "US"


def test_fetch_extra_skips_without_keys(cfg, monkeypatch, capsys):
    monkeypatch.setattr(base, "_DOTENV_LOADED", True)
    for k in ("EIA_API_KEY", "KRX_API_KEY", "DART_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(fetch_extra, "load_config", lambda path=None: cfg)
    assert fetch_extra.main(["--asof", "2026-10-20"]) == 0
    assert capsys.readouterr().out.count("SKIPPED") == 4


# ---------------------------------------------------------------------------
# 문구: 데이터로 결정, 기준 명시, 영문에 한글 없음
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


@pytest.mark.parametrize("fy2022", [False, True])
def test_story_wording(cfg, fy2022):
    pytest.importorskip("matplotlib")
    from research.vol01.story import Story
    full_inputs(cfg, fy2022=fy2022)
    f = data.load_facts(cfg, "2026-10-20")
    kr = _texts(Story(cfg, f, "kr").pages())
    en = _texts(Story(cfg, f, "en").pages())
    joined = "\n".join(kr)
    assert "시총 시총" not in joined
    assert "합계 기준 7.7배(회사별 4.4배~26.1배, 단순평균 14.6배)" in joined          # Executive Summary 기준 명시
    assert "LS ELECTRIC 주가는 3배인데 왜 시총은 15배인가?" in joined
    assert "합계 7.7배와 평균 14.6배 중 무엇이 맞나?" in joined
    assert "2026-04-13 5:1 액면분할" in joined and "분할 조정" in joined
    assert "(저자 견해)" not in joined
    assert sum("본문의 판단은 저자 개인의 견해" in t for t in kr) >= 1
    hangul = re.compile(r"[가-힣]")
    leaks = [t for t in en if t and hangul.search(t)]
    assert not leaks, leaks[:3]
    if fy2022:
        assert "멀티플 기여" in joined and "데이터 수집 후 생성" not in joined
    else:
        assert any("FY2022A 지배순이익 없음" in t for t in kr)


# ---------------------------------------------------------------------------
# 폰트 · 설정 · README
# ---------------------------------------------------------------------------
def test_font_fallback_order(tmp_path):
    reg = tmp_path / "malgun.ttf"
    reg.write_bytes(b"x")
    cands = [(tmp_path / "none.ttf", tmp_path / "none-b.ttf", "Noto Sans KR"), (reg, tmp_path / "malgunbd.ttf", "malgun")]
    fs = resolve_fonts({}, cands)
    assert fs.regular == reg and fs.bold == reg
    with pytest.raises(FileNotFoundError, match="한글 폰트"):
        resolve_fonts({}, cands[:1])


def test_repo_url_single_source_and_gitignore():
    cfg = base.load_config()
    url = cfg["research"]["repo_url"]
    assert url == "https://github.com/Cojae-Kang/ksj-ai-energy-asset-portfolio"
    readme = base.resolve_path("README.md").read_text(encoding="utf-8")
    assert url in readme and "ai-dc-power-ecm" not in readme
    for must in ("<!-- vol01:findings:kr -->", "<!-- /vol01:findings:en -->", "<details>", "docs/img/vol01_p4_kr.png",
                 "CC BY 4.0", "LICENSE", "Claude Code"):
        assert must in readme, must
    assert "준비 중" not in readme and "면접관" not in readme
    assert "면접관" not in base.resolve_path("CLAUDE.md").read_text(encoding="utf-8")
    assert base.resolve_path("LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_qa_reports_moved_to_docs():
    out = base.load_config()["data_fetch"]["output"]
    for k in ("summary_report", "peer_validation_report", "crosscheck_report_krx", "crosscheck_report_global"):
        assert out[k].startswith("docs/qa/"), k


def test_update_readme_markers(tmp_path):
    from research.vol01.build import update_readme
    rd = tmp_path / "README.md"
    rd.write_text("top\n<!-- vol01:findings:kr -->\nold\n<!-- /vol01:findings:kr -->\nbottom\n", encoding="utf-8")
    update_readme(rd, {"kr": {"findings": ["가", "나", "다"]}, "en": {"findings": ["a"]}})   # en 마커 없음 → 건너뜀
    t = rd.read_text(encoding="utf-8")
    assert "old" not in t and "1. 가\n2. 나\n3. 다" in t and t.startswith("top") and t.endswith("bottom\n")
    update_readme(rd, {"kr": {"findings": ["라"]}})                                        # 반복 실행해도 한 번만
    assert rd.read_text(encoding="utf-8").count("<!-- vol01:findings:kr -->") == 1 and "1. 라" in rd.read_text(encoding="utf-8")
    gi = base.resolve_path(".gitignore").read_text(encoding="utf-8")
    assert "data/raw/*" in gi and "research/*/_build/" in gi


def test_iea_meta_verified():
    import json
    m = json.loads(base.resolve_path("data/manual/iea_energy_ai.meta.json").read_text(encoding="utf-8"))
    assert m["verified_on"] == "2026-10-21" and "TODO" not in json.dumps(m, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 빌드 (matplotlib + ReportLab)
# ---------------------------------------------------------------------------
def _pdf_pages(path: Path) -> list[tuple[float, float]]:
    raw = path.read_bytes()
    n = len(re.findall(rb"/Type\s*/Page[^s]", raw))
    boxes = [tuple(float(x) for x in m.groups()) for m in re.finditer(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)]
    return boxes[:n]


@pytest.mark.parametrize("fy2022", [False, True])
def test_build_landscape_pdfs(cfg, tmp_path, fy2022):
    pytest.importorskip("matplotlib")
    pytest.importorskip("reportlab")
    from research.vol01.build import build
    full_inputs(cfg, fy2022=fy2022)
    out = tmp_path / "vol01"
    r = build(cfg, "2026-10-20", out_dir=out)
    for lang in ("kr", "en"):
        pages = _pdf_pages(out / f"KSJ_Research_Vol01_{lang.upper()}.pdf")
        assert len(pages) == r["pages"][lang] == 13
        assert all((w, h) == (960, 720) for w, h in pages)                     # 가로형 4:3
    pend = r["pending"]["kr"]
    if fy2022:
        assert pend == []
    else:
        assert [lab for lab, _, _ in pend] == ["4", "4"] and all(cmd == data.CMD_DART for _, _, cmd in pend)
    assert r["render_warnings"] == {"kr": [], "en": []}                         # 목차·바닥글·뒤표지 넘침 없음
    raw = (out / "KSJ_Research_Vol01_KR.pdf").read_bytes()
    assert b"/Author (Shinjae Kang)" in raw or b"Shinjae Kang" in raw
    summary = (out / "build_summary.md").read_text(encoding="utf-8")
    assert "렌더링 점검" in summary and "이상 없음" in summary
    assert "KRX 시총 검산" in summary and "split_consistent" in summary
    assert ("시총 분해 (FY2022A → FY2025A)" in summary) == fy2022
    assert (out / "_build").exists()
    rd = tmp_path / "README.md"
    rd.write_text("<!-- vol01:findings:kr -->\n<!-- /vol01:findings:kr -->\n<!-- vol01:findings:en -->\n<!-- /vol01:findings:en -->\n",
                  encoding="utf-8")
    r2 = build(cfg, "2026-10-20", out_dir=out, readme=rd)
    for lang in ("kr", "en"):
        a = r2["readme"][lang]
        assert len(a["findings"]) == 3 and a["img"].exists() and a["decomposed"] == fy2022
    assert rd.read_text(encoding="utf-8").count("\n1. **") == 2


# ---------------------------------------------------------------------------
# 기준 이익 0 이하: 배수 미계산·라벨, 3사 표기, 대표 PER (두산 FY2022 지배순손실 시나리오)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("v0, v1, kind", [(100, 300, "multiple"), (-50, 80, "turned_profit"), (0, 80, "turned_profit"),
                                          (50, -10, "turned_loss"), (-5, -10, "loss_both"), (None, 3, "missing")])
def test_growth_kind(v0, v1, kind):
    assert data.growth_kind(v0, v1) == kind


def test_sum_growth_excludes_non_positive_base(cfg):
    write_dart(p(cfg, "dart", 0))
    write_dart(p(cfg, "dart", 1), years=(2022,), ni_override={("034020", 2022): -500})
    fin = data.financials(cfg)
    sg = fin.sum_growth("ni", 2022, 2025)
    assert sg.n == 3 and [e["ticker"] for e in sg.excluded] == ["034020"] and sg.excluded[0]["kind"] == "turned_profit"
    assert sg.multiple == pytest.approx((7326.1 + 2866.2 + 5198.9) / (1500 + 1700 + 900))
    assert sg.multiple > 0


def loss_case(cfg):
    full_inputs(cfg, fy2022=False)
    write_dart(p(cfg, "dart", 1), years=(2022,), ni_override={("034020", 2022): -500})
    return data.load_facts(cfg, "2026-10-20")


def _pages(cfg, f, lang):
    pytest.importorskip("matplotlib")
    from research.vol01.story import Story
    return Story(cfg, f, lang).pages()


def _titles_tables(pages) -> list[str]:
    out = []
    for pg in pages:
        out += [pg.title, pg.subtitle]
        for c in pg.cells:
            out.append(c.title)
            if c.table:
                out += c.table.header + [str(v) for r in c.table.rows for v in r]
        for b in pg.boxes:
            out += [b.number, b.title, b.caption]
    return out


def test_no_negative_multiples_in_titles(cfg):
    f = loss_case(cfg)
    for lang, pat in (("kr", r"[-−]\d+(\.\d+)?배"), ("en", r"[-−]\d+(\.\d+)?x\b")):
        texts = _titles_tables(_pages(cfg, f, lang))
        bad = [t for t in texts if re.search(pat, t)]
        assert not bad, bad[:3]


def test_three_name_labels_and_doosan_rows(cfg):
    f = loss_case(cfg)
    pages = {pg.label: pg for pg in _pages(cfg, f, "kr")}
    texts = "\n".join(_titles_tables(pages.values()))
    assert "4사 합산" not in texts                                              # 표·제목에 4사 합산 오표기 없음
    assert "3사(두산에너빌리티 제외: FY2022 지배순손실)" in pages["3"].title       # p3 제목에 제외 명시
    p3_table = pages["3"].cells[3].table
    doosan = next(r for r in p3_table.rows if r[0] == "두산에너빌리티")
    assert doosan[4] == "-500" and doosan[6] == "흑자전환"                       # 실제 값 + 라벨
    assert "3사(두산에너빌리티 제외)" in pages["4"].title
    assert "시작 시총의 72%" in pages["4"].subtitle and "FY2022A 지배순손실" in pages["4"].subtitle
    assert pages["4"].grid == "3-2" and len(pages["4"].cells) == 5
    t4 = pages["4"].cells[4].table
    assert any("분해 불가(FY2022A 지배순손실)" in v for r in t4.rows for v in r)
    assert t4.rows[-2][0] == "3사 합산" and t4.rows[-1][0] == "참고: 4사 영업이익 기준"   # 합산 행 + 대안 분해(영업이익) 참고 행
    per_cell = pages["4"].cells[2]
    assert "4사 합산 64.2배" in per_cell.note and "분모 왜곡" in per_cell.note    # 4사 값은 p4 각주에만


def test_representative_per_is_three_name(cfg):
    f = loss_case(cfg)
    a = f.decomp.agg
    rep = f"{a['per0']:.1f}배 → {a['per1']:.1f}배"
    pages = {pg.label: pg for pg in _pages(cfg, f, "kr")}
    agg4 = f"{f.val.agg_per:.1f}배"
    med = f"{f.val.median_per:.1f}배"
    for lab in ("i", "5", "A1"):
        texts = "\n".join(_titles_tables([pages[lab]]) + [b for pg in [pages[lab]] for c in pg.cells for b in (c.bullets or [])]
                          + [bl for b in pages[lab].boxes for bl in b.bullets])
        assert agg4 not in texts and med not in texts, lab                       # 4사 합산·중앙값은 대표값으로 쓰지 않음
    es_rows = {r[0]: r[1] for r in pages["i"].cells[0].table.rows}
    assert es_rows["3사 합산 PER (2023 초→최근)"] == f"{a['per0']:.1f} → {a['per1']:.1f}배"
    assert rep in pages["5"].subtitle and f"PER {a['per1']:.0f}배" in pages["5"].title


def test_a1_questions_and_wording(cfg):
    f = loss_case(cfg)
    pages = {pg.label: pg for pg in _pages(cfg, f, "kr")}
    qs = [r[0] for r in pages["A1"].cells[0].table.rows]
    assert "두산에너빌리티는 왜 분해에서 빠졌나?" in qs
    led = f.decomp.valid_rows[f.decomp.valid_rows["mult_share"] > f.decomp.valid_rows["earn_share"]]
    for _, r in led.iterrows():
        assert any(q.startswith(r["company"]) and "멀티플이 주도한 이유" in q for q in qs)
    assert re.search(r"지수 \d+포인트", pages["2"].title) and not re.search(r"\d+p ", pages["2"].title)
    a3 = "\n".join(t for c in pages["A3"].cells for t in [c.title, c.note, c.strip] + (c.bullets or []))
    assert "테스트 함수" not in a3 and "python -m" not in a3
    en = {pg.label: pg for pg in _pages(cfg, f, "en")}
    assert "index points" in en["2"].title


# ---------------------------------------------------------------------------
# 공개본 정리: 내부 용어·SEC '준비 중'·명령어 없음, A3 GitHub·구현 문장
# ---------------------------------------------------------------------------
PUBLIC_FORBIDDEN = ["config", "ASSUMPTION", ".meta.json", "data/manual", "data/raw", "회색 박스", "(저자 견해)",
                    "(author's view)", "준비 중", "SEC 수집", "테스트", "What I built"]


@pytest.mark.parametrize("fy2022", [False, True])
def test_public_text_clean(cfg, fy2022):
    pytest.importorskip("matplotlib")
    from research.vol01.story import Story
    full_inputs(cfg, fy2022=fy2022)
    f = data.load_facts(cfg, "2026-10-20")
    url = cfg["research"]["repo_url"]
    for lang in ("kr", "en"):
        st = Story(cfg, f, lang)
        pages = st.pages()
        held = {t for pg in pages for c in pg.cells for t in (c.placeholder or ())}  # 데이터 미수집 안내는 제외
        texts = [t for t in _texts(pages) + list(st.sources().values()) + [st.footer()] if t and t not in held]
        joined = "\n".join(texts)
        bad = [w for w in PUBLIC_FORBIDDEN if w in joined]                          # 대문자 태그 ASSUMPTION만 금지
        assert not bad, (lang, bad)
        assert all("저자 견해" not in pg.title and "author's view" not in pg.title.lower() for pg in pages)
        by = {pg.label: pg for pg in pages}
        a2 = by["A2"].cells[0].table
        assert not any("SEC" in str(r[0]) for r in a2.rows)                         # A2 출처 표에 SEC 행 없음
        a3 = by["A3"].cells[0]
        assert url in a3.note and "GitHub" in a3.note
        assert a3.strip == (Story.BUILT_WITH_KR if lang == "kr" else Story.BUILT_WITH_EN)
        assert "Claude Code" in a3.strip


def test_vol01_decomposition_scope_and_op_alternative():
    """'이익 주도'는 순이익 흑자 회사(시작 시총 일부)만의 결론 → 대상 비중과 4사 영업이익 기준 대안 분해를 함께 계산."""
    import math
    from src.data_fetch.base import load_config
    from research.vol01 import data as D
    cfg = load_config()
    f = D.load_facts(cfg, cfg["data_fetch"]["as_of_default"])
    dc, mk = f.decomp, f.market
    a = dc.agg
    assert a["coverage_t0"] == pytest.approx(a["mcap0"] / mk.total_t0)
    assert 0 < a["coverage_t0"] < 1 and dc.excluded                                   # 적자 회사 제외 → 부분 범위
    o = dc.op_all
    assert o is not None and o["n"] == len(mk.table)
    assert o["earn_share"] == pytest.approx(math.log(o["op1"] / o["op0"]) / math.log(mk.total_multiple))
    assert o["earn_share"] + o["mult_share"] == pytest.approx(1.0)
    # 커밋 데이터 기준 값(손계산: ln(29,314/15,699) / ln(7.706) = 0.306, 38,039/135,381 = 0.281)
    assert o["earn_share"] == pytest.approx(0.306, abs=0.002) and a["coverage_t0"] == pytest.approx(0.281, abs=0.002)
