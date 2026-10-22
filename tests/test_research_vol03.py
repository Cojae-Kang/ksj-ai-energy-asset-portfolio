"""KSJ Research Vol.3 (IPO 희망공모가 밴드) 테스트 — 네트워크 없이 실행.

입력: 커밋된 data/processed(DART·KRX·SEC) + tmp_path의 합성 미국 시세(테스트 전용, 사실 주장 아님).
"""
from __future__ import annotations

import copy
import csv
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.vol03 import data as D
from src.analysis import ipo_model as im
from src.data_fetch import base

PUBLIC_FORBIDDEN = ["config", "ASSUMPTION", "TODO", ".meta.json", "data/manual", "data/raw", "회색 박스", "(저자 견해)",
                    "(author's view)", "null", "python -m"]

# 합성 미국 시세 (테스트 전용): (ticker, 2023 초 종가, 2023 초 주식수, 기준일 종가, yfinance 주식수)
SYNTH_US = [("VRT", 13.0, 3.8e8, 150.0, 3.85e8), ("ETN", 160.0, 4.0e8, 380.0, 3.884e8), ("GEV", None, None, 600.0, 2.7e8),
            ("CEG", 85.0, 3.27e8, 300.0, 3.54e8), ("VST", 23.0, 4.0e8, 190.0, 3.36e8)]


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(base.load_config())
    v = c["research"]["vol03"]
    v["assumptions_csv"] = str(tmp_path / "vol03_assumptions.csv")
    for k in ("market_points", "global_market", "market_manual", "peer_extra", "peer_manual", "ipo_discounts", "ipo_log"):
        v["inputs"][k] = str(tmp_path / f"{k}.csv")          # 미국 시세·D&A·IPO 실증 없음 (수집 전 상태를 재현)
    v["ipo_discounts"]["qa_report"] = str(tmp_path / "qa_ipo.md")
    v["ipo_discounts"]["listing_sources"] = {"krx_raw_globs": [], "processed": str(tmp_path / "listing.csv"), "manual": str(tmp_path / "listing_manual.csv")}
    c["monte_carlo"]["n_sims"] = 4000
    v["monte_carlo"]["convergence"] = [500, 1000, 2000, 4000]
    return c


def with_us_market(cfg, tmp_path, ni2022: bool = True):
    c = copy.deepcopy(cfg)
    rows = []
    for tk, c0, s0, c1, yf in SYNTH_US:
        if c0 is not None:
            rows.append({"point": "start_2023", "date": "2023-01-03", "ticker": tk, "close": c0, "shares_sec": s0, "shares_yf": ""})
        rows.append({"point": "latest", "date": "2026-10-19", "ticker": tk, "close": c1, "shares_sec": "", "shares_yf": yf})
    pd.DataFrame(rows).to_csv(c["research"]["vol03"]["inputs"]["market_points"], index=False)
    if ni2022:   # 보수 시나리오 분모 (합성)
        ex = [{"company": tk, "ticker": tk, "region": "US", "fiscal_year": "FY2022A", "metric": "net_income", "value": v, "unit": "USD mn",
               "source": "synthetic", "detail": ""} for tk, v in (("VRT", 177.0), ("ETN", 2462.0), ("CEG", -160.0), ("VST", -1210.0))]
        pd.DataFrame(ex).to_csv(c["research"]["vol03"]["inputs"]["peer_extra"], index=False)
    return c


# ---------------------------------------------------------------------------
# 엔진 (src/analysis/ipo_model.py)
# ---------------------------------------------------------------------------
def test_multiple_and_screen_rules():
    assert im.multiple(100, 4) == 25 and math.isnan(im.multiple(100, 0)) and math.isnan(im.multiple(100, -5))
    assert im.screen_per(25, 4, per_max=100).included
    assert im.screen_per(float("nan"), -5, per_max=100).rule == "R1"
    s = im.screen_per(503, 848, per_max=100)
    assert not s.included and s.rule == "R2"
    assert im.screen_per(30, 10, per_max=100, entity_warn=True).rule == "R3"
    assert im.screen_ev(70, 10, 700, ev_max=60).rule == "R5" and im.screen_ev(float("nan"), 10, float("nan"), ev_max=60).rule == "no_ev"
    assert im.flag_high({"a": 25.8, "b": 86.1, "c": 34.7}, 2.0) == {"b"} and im.flag_high({"a": 1, "b": 9}, 2.0) == set()


def test_group_multiple_and_normalization():
    g = im.group_multiple([("a", 100, 10), ("b", 300, 5), ("c", 50, 0)])     # 분모 0은 제외
    assert g.n == 2 and g.aggregate == pytest.approx(400 / 15) and g.mean == pytest.approx(35) and g.median == pytest.approx(35)
    assert im.normalized_multiple(40.0, 13.5) == pytest.approx(math.sqrt(40 * 13.5))
    assert im.normalized_multiple(40.0, 10.0, 0.5, "arithmetic") == pytest.approx(25)
    assert im.combine_groups([40.0, float("nan"), 30.0]) == pytest.approx(35)


def test_deal_shares_identities():
    sh = im.deal_shares(10_000_000, 0.25, 0.8)
    assert sh.post == pytest.approx(sh.pre + sh.new)
    assert sh.offered == pytest.approx(0.25 * sh.post) and sh.new == pytest.approx(0.8 * sh.offered)
    assert sh.overhang == pytest.approx(sh.pre - sh.old) and sh.dilution == pytest.approx(sh.new / sh.post)
    with pytest.raises(ValueError):
        im.deal_shares(100, 1.2, 0.5)
    assert im.per_share(1000, 10_000_000) == pytest.approx(10_000)          # 1,000억원 ÷ 1,000만주 = 1만원
    assert im.round_price(62849.5, 100) == 62800 and im.implied_discount(100, 75) == pytest.approx(0.25)
    s = im.sensitivity(100, 1e7, [10, 20], [0.1, 0.3])
    assert s.loc[20, 0.3] == pytest.approx(100 * 20 * 1e8 / 1e7 * 0.7)


def test_monte_carlo_reproducible_and_converges():
    a = im.monte_carlo(300, 1.25e7, 0.17, 0.06, (13.5, 23.3, 40.1), 6000, 42, [1000, 3000, 6000], 0.02)
    b = im.monte_carlo(300, 1.25e7, 0.17, 0.06, (13.5, 23.3, 40.1), 6000, 42)
    assert a.q(0.5) == b.q(0.5) and a.converged
    assert a.q(0.1) < a.q(0.5) < a.q(0.9) and 13.5 <= a.per.min() and a.per.max() <= 40.1
    assert a.prob_below(a.q(0.5)) == pytest.approx(0.5, abs=0.01)
    mu, sd = im.log_growth_params([0.1, 0.2, 0.3])
    assert mu == pytest.approx(np.mean(np.log1p([0.1, 0.2, 0.3]))) and sd > 0


# ---------------------------------------------------------------------------
# 데이터 (커밋된 DART·KRX·SEC)
# ---------------------------------------------------------------------------
def test_domestic_multiples_match_vol01(cfg):
    f = D.load_facts(cfg)
    mu, t = f.mult, f.peers.table
    assert mu.applied_group == "domestic" and f.peers.overseas_pending
    dom = mu.groups["domestic"]["current"]
    a = t[(t["group"] == "domestic") & (t["status"] == "applied")]
    assert list(a["ticker"]) == ["267260", "010120", "298040"]
    assert dom.aggregate == pytest.approx(a["mcap1"].sum() / a["ni1"].sum())
    assert dom.aggregate == pytest.approx(f.links.per1) and mu.scen["domestic"]["conservative"] == pytest.approx(f.links.per0)
    assert mu.applied("normalized") == pytest.approx(math.sqrt(mu.applied("current") * mu.applied("conservative")))
    dx = t[t["ticker"] == "034020"].iloc[0]
    assert dx["status"] == "excluded" and dx["step2"] == "R2" and dx["per1"] > 100
    assert bool(t[t["ticker"] == "010120"]["high_flag"].iloc[0])                  # LS ELECTRIC: 중앙값 2배 초과 → 표시
    assert t[t["ticker"] == "SU.PA"]["status"].iloc[0] == "excluded"
    assert set(t[t["group"] == "core"]["status"]) == {"pending"}
    assert f.peers.ev_basis == "EBIT"                                             # D&A 미수집 → 대용


def test_derived_assumptions_from_dart(cfg):
    f = D.load_facts(cfg)
    a, dom = f.assumptions, f.dom
    tick = ["267260", "010120", "298040"]
    r0 = sum(dom.val(t, 2022, "revenue") for t in tick)
    r1 = sum(dom.val(t, 2025, "revenue") for t in tick)
    assert a["revenue_growth"].value == pytest.approx((r1 / r0) ** (1 / 3) - 1) and a["revenue_growth"].status == "data"
    assert a["npm"].value == pytest.approx(sum(dom.val(t, 2025, "net_income") for t in tick) / r1)
    assert a["npm"].low <= a["npm"].value <= a["npm"].high
    assert len(f.der.growth_obs) == 9
    assert a["da_ratio"].value is None and a["da_ratio"].status == "input"
    assert a["band_discount_low"].value is None                                   # 근거 없는 값은 null
    assert {a[k].status for k in ("revenue", "shares_pre", "new_share_ratio")} == {"design"}
    assert a["offer_ratio"].status == "verify" and a["band_q_low"].status == "judgment"


def test_valuation_band_and_mc(cfg):
    f = D.load_facts(cfg)
    v, b, mc = f.val, f.band, f.mc
    assert v.ni == pytest.approx(f.assumptions["revenue"].value * f.assumptions["npm"].value)
    assert v.per_share["current"] == pytest.approx(v.ni * f.mult.applied("current") * 1e8 / v.shares.post)
    assert v.per_share["conservative"] < v.per_share["normalized"] < v.per_share["current"]
    assert b.basis == "mc" and b.low < b.high < v.per_share["current"]
    assert b.low % 100 == 0 and b.high % 100 == 0
    assert b.d_low == pytest.approx(1 - b.high / v.per_share["current"])
    assert abs(b.raw_high - mc.result.q(0.5)) < 1e-6 and abs(b.raw_low - mc.result.q(0.25)) < 1e-6
    assert mc.required[0.5] < mc.required[0.25] < mc.required[0.1]
    loss = [mc.loss_grid[d] for d in cfg["research"]["vol03"]["discount_grid"]]
    assert loss == sorted(loss, reverse=True)                                    # 할인율이 클수록 손실 확률 하락
    assert list(v.grid["price"]) == sorted(v.grid["price"], reverse=True)


def test_band_from_config_discounts(cfg):
    c = copy.deepcopy(cfg)
    c["research"]["vol03"]["params"]["deal"]["band_discount_low"]["value"] = 0.2
    c["research"]["vol03"]["params"]["deal"]["band_discount_high"]["value"] = 0.3
    f = D.load_facts(c)
    v0 = f.val.per_share["current"]
    assert f.band.basis == "config"
    assert f.band.high == im.round_price(v0 * 0.8, 100) and f.band.low == im.round_price(v0 * 0.7, 100)


def test_csv_override_and_template(cfg):
    path = Path(cfg["research"]["vol03"]["assumptions_csv"])
    D.write_template(cfg)
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    assert [k for k in D.CSV_COLUMNS] == list(rows[0].keys())                    # Vol.2와 같은 열 구조
    assert {r["case"] for r in rows} == {"target", "deal", "mc", "market"}
    for r in rows:
        if r["item"] == "npm":
            r.update(value="8", source_name="테스트 출처", url="https://example.org")
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=D.CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    f = D.load_facts(cfg)
    assert f.assumptions["npm"].value == pytest.approx(0.08) and f.assumptions["npm"].origin == "csv"
    assert f.assumptions["npm"].status == "sourced"
    D.write_template(cfg)                                                        # 다시 써도 사용자 입력 보존
    kept = {r["item"]: r for r in csv.DictReader(open(path, encoding="utf-8-sig"))}
    assert kept["npm"]["value"] == "8" and kept["npm"]["source_name"] == "테스트 출처"


def test_us_market_data_enters_combined(cfg, tmp_path):
    c = with_us_market(cfg, tmp_path)
    f = D.load_facts(c)
    mu, t = f.mult, f.peers.table
    assert mu.applied_group == "combined"
    core = t[t["group"] == "core"].set_index("ticker")
    assert core.loc["GEV", "status"] == "held" and set(core.drop("GEV")["status"]) == {"applied"}   # GE Vernova: 10-K 확인 전 보류
    sh = f.ovs.shares.set_index("ticker")["shares"]
    assert core.loc["VRT", "mcap1"] == pytest.approx(150.0 * sh["VRT"] / 1e6)        # 종가 × SEC 주식수
    assert core.loc["VRT", "shares_check"] == pytest.approx(3.85e8 / sh["VRT"] - 1)
    assert math.isnan(core.loc["GEV", "mcap0"])                                     # 2023 초 상장 전 → 보수에서 제외
    assert mu.groups["core"]["start"].members == ["VRT", "ETN"] and mu.groups["core"]["current"].members == ["VRT", "ETN"]
    assert mu.applied("current") == pytest.approx((mu.scen["domestic"]["current"] + mu.scen["core"]["current"]) / 2)
    ref = t[t["group"] == "reference"]
    assert set(ref["status"]) == {"reference"}                                     # 참고 비교군은 적용 배수에 넣지 않음
    assert mu.groups["reference"]["start"].n == 0                                   # FY2022A 적자(합성) → R1


# ---------------------------------------------------------------------------
# 보고서 문구·PDF
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


@pytest.mark.parametrize("us", [False, True])
def test_story_public_text_and_numbers(cfg, tmp_path, us):
    pytest.importorskip("matplotlib")
    from research.vol03.story import Story
    c = with_us_market(cfg, tmp_path) if us else cfg
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
        assert "Claude Code" in by["A4"].cells[0].strip and c["research"]["repo_url"] in by["A4"].cells[0].note
        assert len(by["A1"].cells[0].table.rows) == 8 and all(r[1] != "—" for r in by["A1"].cells[0].table.rows)
        back = pages[-1]
        assert back.kind == "back" and any("CC BY 4.0" in t for t in back.extra["items"]) and back.extra["contact"] == "Contact: toonword@naver.com"
        assert "Target Co." in st.footer()
    kr = Story(c, f, "kr")
    by = {p.label: p for p in kr.pages()}
    assert kr.band_text() in by["i"].title and kr.band_text() in by["6"].title
    assert f"{f.val.per_share['current']:,.0f}원" in by["6"].title
    held = [cell for p in kr.pages() for cell in p.cells if cell.placeholder]
    assert bool(held) != us                                                         # 미국 시세가 없을 때만 회색 박스(시총 교차 확인)
    toc = by["ii"].toc
    assert len(toc) == 9 and all("(" not in t for _, _, t, _ in toc[:-1])            # 한 줄 요약: 괄호 보충 설명 제거


@pytest.mark.parametrize("us", [False, True])
def test_build_pdfs(cfg, tmp_path, us):
    pytest.importorskip("matplotlib")
    pytest.importorskip("reportlab")
    from research.vol03.build import build
    c = with_us_market(cfg, tmp_path) if us else cfg
    out = tmp_path / "vol03"
    r = build(c, out_dir=out)
    for lang in ("kr", "en"):
        raw = (out / f"KSJ_Research_Vol03_{lang.upper()}.pdf").read_bytes()
        n = len(re.findall(rb"/Type\s*/Page[^s]", raw))
        boxes = [tuple(float(x) for x in m.groups()) for m in re.finditer(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)]
        assert n == r["pages"][lang] == 17 and all(bx == (960, 720) for bx in boxes[:n])
    assert r["render_warnings"] == {"kr": [], "en": []}
    s = (out / "build_summary.md").read_text(encoding="utf-8")
    for head in ("## 핵심 결론 3줄", "## 근거", "## 한계", "### 검산", "## 점검 필요 수치", "## 출처를 채워야 할 가정·데이터 (TODO)",
                 "### 몬테카를로 (현재 기준 · 이중 고점 · 동조 민감도)", "**이중 고점**", "### 국내 IPO 할인율 실증"):
        assert head in s, head
    assert s.index("## 핵심 결론 3줄") < s.index("## 근거") < s.index("## 한계")
    assert ("미국 피어 시총" in s) != us
    assert not r["figures"]                                                         # tmp 출력은 figures/에 쓰지 않음


@pytest.mark.parametrize("us", [False, True])
def test_checks_are_zero(cfg, tmp_path, us):
    from research.vol03.build import checks
    c = with_us_market(cfg, tmp_path) if us else cfg
    rows = checks(D.load_facts(c), c)
    assert len(rows) >= 7 + (4 if us else 0)
    for r in rows:
        if r["차이"] != "—":
            assert float(r["차이"]) < 1e-6, r


# ---------------------------------------------------------------------------
# 추가 수집 (네트워크 없이 순수 함수·가짜 클라이언트)
# ---------------------------------------------------------------------------
FACTS = {"facts": {
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2022-10-20", "val": 400, "accn": "a1", "filed": "2022-10-30"},
        {"end": "2023-02-10", "val": 390, "accn": "a2", "filed": "2023-02-20"},
        {"end": "2026-07-31", "val": 350, "accn": "a3", "filed": "2026-08-06"}]}}},
    "us-gaap": {"DepreciationDepletionAndAmortization": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 1.5e9, "form": "10-K", "accn": "x", "filed": "2026-02-10"}]}},
        "NetIncomeLoss": {"units": {"USD": [
            {"start": "2022-01-01", "end": "2022-12-31", "val": -1.6e8, "form": "10-K", "accn": "y", "filed": "2023-02-10"}]}}}}}


def test_fetch_extra_pure_functions(cfg):
    from research.vol03 import fetch_extra as fx
    assert fx.shares_on(FACTS, "2023-01-03")["shares"] == 400 and fx.shares_on(FACTS, "2026-10-19")["shares"] == 350
    assert fx.shares_on(FACTS, "2020-01-01") is None
    rows = fx.sec_extra_rows("X", "XX", FACTS, cfg["data_fetch"]["sec"], [2024, 2025], ["DepreciationDepletionAndAmortization"], 2022, "src")
    got = {(r["fiscal_year"], r["metric"]): r["value"] for r in rows}
    assert got == {("FY2025A", "da"): 1500.0, ("FY2022A", "net_income"): -160.0}
    spec = cfg["research"]["vol03"]["fetch_extra"]["dart_da"]
    items = [{"sj_div": "CF", "account_nm": "감가상각비", "account_detail": "-", "thstrm_amount": "1,000,000,000"},
             {"sj_div": "CF", "account_nm": "무형자산상각비", "account_detail": "-", "thstrm_amount": "200000000"},
             {"sj_div": "CF", "account_nm": "사용권자산감가상각비", "account_detail": "-", "thstrm_amount": "500000000"},
             {"sj_div": "IS", "account_nm": "감가상각비", "account_detail": "-", "thstrm_amount": "999"}]
    da, names = fx.dart_da(items, spec)
    assert da == pytest.approx(12.0) and names == ["감가상각비", "무형자산상각비"]
    h = pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=pd.to_datetime(["2022-12-30", "2023-01-03", "2023-01-04"]))
    assert fx.first_trading_close(h, "2023-01-01", "2023-01-11", True) == ("2023-01-03", 11.0)
    assert fx.first_trading_close(h, "2022-12-01", "2023-01-03", False) == ("2023-01-03", 11.0)


def test_fetch_market_with_fake_clients(cfg):
    from research.vol03 import fetch_extra as fx

    class T:
        fast_info = {"shares": 355.0}

        def history(self, start, end, auto_adjust=False):
            idx = pd.date_range(start, end, freq="B")[:-1]
            return pd.DataFrame({"Close": np.linspace(10, 20, len(idx))}, index=idx)
    r = fx.fetch_market(cfg, "2026-10-20", ticker_factory=lambda s: T(), load_facts=lambda cik: FACTS)
    assert r.status == "SUCCESS"
    df = pd.read_csv(cfg["research"]["vol03"]["inputs"]["market_points"])
    assert set(df["point"]) == {"start_2023", "latest"} and "SU.PA" not in set(df["ticker"])
    lat = df[df["point"] == "latest"].iloc[0]
    assert lat["date"] < "2026-10-20" and lat["shares_sec"] == 350 and lat["shares_yf"] == 355
    assert lat["mcap_usd_mn"] == pytest.approx(lat["close"] * 350 / 1e6)


def test_fetch_extra_skips_without_keys(cfg, monkeypatch, capsys):
    from research.vol03 import fetch_extra as fx
    monkeypatch.setattr(base, "_DOTENV_LOADED", True)
    for k in ("DART_API_KEY", "SEC_USER_AGENT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(fx, "load_config", lambda path=None: cfg)
    assert fx.main(["--only", "dart"]) == 0 and "SKIPPED" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 목차 규칙 (Vol.1·Vol.2·Vol.3 공통): 모든 행 같은 크기, 한 줄 요약
# ---------------------------------------------------------------------------
def test_toc_rows_one_line_same_size():
    pytest.importorskip("reportlab")
    from research.vol01 import layout
    from research.vol01.fonts import register_reportlab, resolve_fonts
    cfg = base.load_config()
    register_reportlab(resolve_fonts(cfg))
    assert layout.toc_line("수요는 진짜다: 데이터센터 전력 소비는 2030년 2.3배(IEA 기준)") == "데이터센터 전력 소비는 2030년 2.3배"
    assert layout.toc_line("Market: for 3 names (ex. Doosan) the gain") == "For 3 names the gain"
    ctx = layout.Ctx(cfg["research"]["colors"], 960, 720, "kr", "KSJ", {}, {}, Path("."), "footer")
    size, over = layout.toc_size(ctx, ["짧다", "조금 더 긴 요약 문장"], 702)
    assert size == layout.TOC_MAX and over == []
    size, over = layout.toc_size(ctx, ["짧다", "아주 긴 문장 " * 40], 702)
    assert size == layout.TOC_MIN and over == [1]


# ---------------------------------------------------------------------------
# GE Vernova 보류 · 이중 고점 (커밋된 실제 데이터: DART·KRX·SEC·미국 시세)
# ---------------------------------------------------------------------------
@pytest.fixture
def real_cfg(tmp_path):
    c = copy.deepcopy(base.load_config())
    c["research"]["vol03"]["assumptions_csv"] = str(tmp_path / "vol03_assumptions.csv")
    c["research"]["vol03"]["inputs"]["ipo_discounts"] = str(tmp_path / "ipo.csv")
    c["research"]["vol03"]["inputs"]["ipo_log"] = str(tmp_path / "ipo_log.csv")
    return c


def test_engine_copula_and_margin():
    u = np.linspace(0, 1, 11)
    x = im.tri_ppf(u, 3.0, 7.0, 10.0)
    assert x[0] == pytest.approx(3.0) and x[-1] == pytest.approx(10.0) and np.all(np.diff(x) >= 0)
    assert im.tri_ppf(np.array([(7 - 3) / (10 - 3)]), 3.0, 7.0, 10.0)[0] == pytest.approx(7.0)
    with pytest.raises(np.linalg.LinAlgError):
        im.corr_matrix(0.9, -0.9, 0.9)
    args = (300, 1.25e7, 0.17, 0.06, (20.0, 28.5, 41.4), 20000, 42)
    base_ = im.monte_carlo(*args)
    assert base_.npm is None
    dp = im.monte_carlo(*args, npm_tri=(0.031, 0.07, 0.1025), npm_base=0.1025, corr=im.corr_matrix())
    st = im.monte_carlo(*args, npm_tri=(0.031, 0.07, 0.1025), npm_base=0.1025, corr=im.corr_matrix(0.5, 0.5, 0.5))
    assert 0.031 <= dp.npm.min() and dp.npm.max() <= 0.1025 and dp.q(0.5) < base_.q(0.5)
    assert st.q(0.1) < dp.q(0.1)                                                    # 동조하면 하방이 두꺼워진다
    assert np.corrcoef(st.per, st.npm)[0, 1] > 0.3 and abs(np.corrcoef(dp.per, dp.npm)[0, 1]) < 0.05
    same = im.monte_carlo(*args, npm_tri=(0.1025, 0.1025, 0.1025), npm_base=0.1025, corr=np.eye(3))
    assert np.allclose(same.npm, 0.1025)


def test_gev_held_with_evidence(real_cfg):
    f = D.load_facts(real_cfg)
    t = f.peers.table.set_index("ticker")
    g = t.loc["GEV"]
    assert g["status"] == "held" and g["step2"] == "R6" and {g["s1"].rule, g["s0"].rule, g["sev"].rule} == {"R6"}
    assert g["ni_to_oi"] > 1.5 and str(g["lt_debt_tag"]) == "False" and g["evm1"] > 60     # 보류 근거는 데이터로 재계산
    mu = f.mult
    assert mu.groups["core"]["current"].members == ["VRT", "ETN"] and "GEV" not in mu.groups["core"]["ev"].members
    core = t.loc[["VRT", "ETN"]]
    assert mu.groups["core"]["current"].aggregate == pytest.approx(core["mcap1"].sum() / core["ni1"].sum())
    assert mu.applied("current") == pytest.approx((mu.scen["domestic"]["current"] + mu.scen["core"]["current"]) / 2)
    from research.vol03.story import Story
    st = Story(real_cfg, f, "kr")
    assert st.core_with_held() == pytest.approx(t.loc[["VRT", "ETN", "GEV"], "mcap1"].sum() / t.loc[["VRT", "ETN", "GEV"], "ni1"].sum())
    by = {p.label: p for p in st.pages()}
    rows3 = {r[0]: r for r in by["3"].cells[0].table.rows}
    assert rows3["GE Vernova"][-1] == "10-K 확인 전 제외"
    r6 = [r for r in by["4"].cells[2].table.rows if r[0] == "R6"][0]
    assert "GE Vernova" in r6[3]


def test_double_peak_results(real_cfg):
    f = D.load_facts(real_cfg)
    mc, dp, st, v = f.mc, f.mc_dp, f.mc_stress, f.val
    hist = f.der.hist
    assert dp.npm_tri == pytest.approx((hist[2022]["npm"], f.assumptions["npm_mode"].value, hist[2025]["npm"]))
    assert f.assumptions["npm_mode"].value == pytest.approx(sum(h["npm"] * h["revenue"] for h in hist.values()) / sum(h["revenue"] for h in hist.values()))
    assert f.assumptions["npm_shape"].status == "judgment" and f.assumptions["corr_npm_per"].status == "neutral"
    assert dp.required[0.5] > mc.required[0.5] and f.band_dp.high < f.band.low                   # 이중 고점이면 밴드가 통째로 아래
    assert st.result.q(0.1) < dp.result.q(0.1) and dp.n == 10000 and dp.seed == real_cfg["monte_carlo"]["seed"]
    assert abs(dp.check_p50 / dp.result.q(0.5) - 1) < 0.01 and dp.se_p50 < 0.01                   # 수렴 진단 (보고값은 10,000회 그대로)
    nn = v.nn
    assert nn["per_share"] == pytest.approx(v.rev * nn["npm"] * f.mult.applied("normalized") * 1e8 / v.shares.post)
    from research.vol03.story import Story
    for lang in ("kr", "en"):
        s_ = Story(real_cfg, f, lang)
        by = {p.label: p for p in s_.pages()}
        assert s_.band_text() in by["i"].title and s_.won_rng(f.band_dp.low, f.band_dp.high) in by["i"].title
        assert len(by["5"].cells[1].table.rows) == 4 and s_.won(nn["per_share"]) in by["5"].cells[1].table.rows[3][-1]
        assert len(by["7"].cells[1].table.header) == 4
        assert any(s_.won_rng(f.band_dp.low, f.band_dp.high) in b for b in by["8"].cells[0].bullets)
    a2 = {r[0]: r for r in {p.label: p for p in Story(real_cfg, f, "kr").pages()}["A2"].cells[0].table.rows}
    assert a2["기관 의무보유확약 비율 2025"][-1] == "근거 있음" and "41" in a2["기관 의무보유확약 비율 2025"][1]


# ---------------------------------------------------------------------------
# 증권신고서 할인율 실증 (가짜 원문 fixture)
# ---------------------------------------------------------------------------
DOC_HIGH = """<html><body><p>나. 공모가격 산정 개요</p><table><tr><td>주당 평가가액</td><td>32,145원</td></tr>
<tr><td>평가액 대비 할인율</td><td>22.23% ~ 34.67%</td></tr><tr><td>희망공모가액 밴드</td><td>21,000원 ~ 25,000원</td></tr></table>
<p>비교회사 PER 산정 … 적용 PER 25.1배 … PER 비교회사 선정</p><p>당사는 유가증권시장에 상장할 예정입니다.</p></body></html>"""
DOC_IMPLIED = """<p>주당 평가가액 : 40,000원</p><p>희망 공모가액 범위 : 28,000원 ~ 32,000원</p><p>EV/EBITDA 방식 EV / EBITDA 비교회사</p>
<p>코스닥시장 상장 예정</p>"""
DOC_MISMATCH = DOC_HIGH.replace("22.23% ~ 34.67%", "15.00% ~ 25.00%")
DOC_LOW = "<p>공모 개요만 있고 가격 정보가 없는 문서. PER PER</p>"


def _zip(text: str, enc: str = "utf-8") -> bytes:
    import io as _io
    import zipfile as _zf
    b = _io.BytesIO()
    with _zf.ZipFile(b, "w") as z:
        z.writestr("00000000.xml", text.encode(enc))
    return b.getvalue()


def test_parse_prospectus_fixtures():
    from research.vol03 import ipo_discounts as ip
    h = ip.parse_prospectus(ip.zip_text(_zip(DOC_HIGH, "cp949")))
    assert (h["value_per_share"], h["band_low"], h["band_high"]) == (32145, 21000, 25000)
    assert h["discount_low"] == pytest.approx(0.2223) and h["discount_high"] == pytest.approx(0.3467)
    assert h["discount_implied_low"] == pytest.approx(1 - 25000 / 32145) and h["confidence"] == "high" and not h["needs_review"]
    assert h["multiples"].startswith("PER") and h["market"] == "유가증권시장"
    m = ip.parse_prospectus(ip.to_text(DOC_IMPLIED))
    assert m["confidence"] == "medium" and m["needs_review"] and m["discount_low"] == pytest.approx(0.2) and m["discount_high"] == pytest.approx(0.3)
    assert "EV/EBITDA" in m["multiples"] and m["market"] == "코스닥시장"
    x = ip.parse_prospectus(ip.to_text(DOC_MISMATCH))
    assert x["confidence"] == "medium" and "≠" in x["notes"] and x["discount_low"] == pytest.approx(0.15)
    lo = ip.parse_prospectus(ip.to_text(DOC_LOW))
    assert lo["confidence"] == "low" and math.isnan(lo["value_per_share"])


DOC_NOBAND = "<p>수요예측 일정 미정. 코스닥시장 상장 예정. 공모가격은 추후 정정신고서로 기재</p>"
DOC_RIGHTS = ("<p>주주배정 후 실권주 일반공모 방식의 유상증자. 1차 발행가액 8,000원, 확정발행가액은 청약일 전 산정. "
              "주당 평가가액 같은 문구는 없음. 기존 주주 신주인수권증서</p>")


def test_pick_filings_and_run_with_fake_client(cfg, tmp_path):
    from research.vol03 import ipo_discounts as ip
    F = lambda code, name, cls, rno, dt, nm="증권신고서(지분증권)", sc="": {"corp_code": code, "corp_name": name, "corp_cls": cls,  # noqa: E731
                                                                         "report_nm": nm, "rcept_no": rno, "rcept_dt": dt, "stock_code": sc}
    found = pd.DataFrame([
        F("001", "가나다", "E", "20250301000001", "20250301"),
        F("001", "가나다", "E", "20250320000002", "20250320", "[기재정정]증권신고서(지분증권)"),
        F("001", "가나다", "E", "20250405000007", "20250405", "[기재정정]증권신고서(지분증권)"),
        F("002", "라마바", "E", "20250401000003", "20250401"),
        F("003", "엔에이치스팩30호", "E", "20250402000004", "20250402"),
        F("004", "상장사", "Y", "20250403000005", "20250403", sc="111111"),                   # 상장일 2010 ≤ 접수일 → 원문 없이 제외
        F("005", "깨진문서", "E", "20250404000006", "20250404"),
        F("006", "신규상장사", "K", "20250410000008", "20250410", sc="222222"),               # 지금은 상장사, 접수 땐 비상장 → 복원
        F("007", "유상증자사", "K", "20250415000009", "20250415", sc="333333"),               # 상장일 모름 → 원문(유상증자)으로 제외
        F("007", "유상증자사", "K", "20250425000010", "20250425", "[발행조건확정]증권신고서(지분증권)", "333333")])
    icfg = cfg["research"]["vol03"]["ipo_discounts"]
    pd.DataFrame([{"stock_code": "111111", "list_dt": "2010-05-03"}, {"stock_code": "222222", "list_dt": "20250601"}]).to_csv(
        icfg["listing_sources"]["manual"], index=False)
    cand, log0 = ip.pick_filings(found, icfg)
    assert "004" in set(cand["corp_code"]) and "006" in set(cand["corp_code"])          # 현재 corp_cls로 거르지 않음
    assert {r["decision"] for r in log0} == {"excluded_name"}
    old, log_old = ip.pick_filings(found, {**icfg, "corp_cls_filter": True})              # 예전 방식이면 006까지 빠짐 (look-ahead)
    assert "006" not in set(old["corp_code"]) and sum(r["decision"] == "excluded_cls" for r in log_old) == 4
    docs = {"01": DOC_NOBAND, "02": DOC_HIGH.replace("</body>", "<p>공모주식수 : 8,000,000주</p></body>"), "07": DOC_MISMATCH,
            "03": DOC_IMPLIED, "08": DOC_IMPLIED.replace("40,000원", "50,000원"), "09": DOC_RIGHTS, "10": DOC_RIGHTS}
    downloaded = []

    class Fake:
        large_dir = tmp_path / "large"

        def search_filings(self, bgn, end, label=""):
            assert bgn == icfg["bgn_de"] and end <= "20261020"
            return found, []

        def download_document(self, rno):
            downloaded.append(rno)
            p_ = tmp_path / f"{rno}.zip"
            p_.write_bytes(b"not a zip" if rno.endswith("06") else _zip(docs[rno[-2:]]))
            return p_
    r = ip.run(cfg, "2026-10-20", client=Fake())
    df = pd.read_csv(cfg["research"]["vol03"]["inputs"]["ipo_discounts"], dtype={"rcept_no": str, "corp_code": str, "list_dt": str})
    assert list(df.columns) == ip.COLUMNS and len(df) == 3 and r.status == "PARTIAL" and "깨진문서" in r.message
    g = df.set_index("corp_code")
    assert g.loc["001", "rcept_no"] == "20250320000002"          # 밴드가 처음 나온 신고서 (첫 신고서는 밴드 없음, 이후 정정은 기록만)
    assert g.loc["001", "offer_amount_low"] == pytest.approx(8e6 * 21000 / 1e8) and g.loc["001", "offer_amount_high"] == pytest.approx(2000.0)
    assert g.loc["006", "corp_cls_now"] == "K" and g.loc["006", "list_dt"] == "20250601" and "복원" in g.loc["006", "pit_check"]
    assert "004" not in g.index and "007" not in g.index
    assert "20250403000005" not in downloaded and "20250425000010" not in downloaded      # 상장일로 거른 건·유상증자 회사의 이후 신고서는 안 받음
    assert set(df["market"]) == {"KOSPI", "KOSDAQ"} and df["url"].str.contains("dart.fss.or.kr/dsaf001").all()
    assert Path(str(cfg["research"]["vol03"]["inputs"]["ipo_discounts"]).replace(".csv", ".meta.json")).exists()
    lg = pd.read_csv(cfg["research"]["vol03"]["inputs"]["ipo_log"], dtype=str).set_index("rcept_no")
    assert set(lg.reset_index().columns) == set(ip.LOG_COLUMNS)
    dec = lg["decision"].to_dict()
    assert dec["20250301000001"] == "no_band" and dec["20250405000007"] == "after_first" and dec["20250320000002"] == "used"
    assert dec["20250404000006"] == "download_fail" and dec["20250402000004"] == "excluded_name"
    assert dec["20250403000005"] == "listed_at_filing" and dec["20250415000009"] == "not_ipo_text" and dec["20250425000010"] == "after_not_ipo"
    qa = Path(icfg["qa_report"]).read_text(encoding="utf-8")
    assert "구간(월)별" in qa and "목표 표본 40건 미달 (3건)" in qa and "원문에서 밴드 미검출 1건" in qa and "2025-03-20~2025-04-10" in qa
    assert "복원된 건수: 1건" in qa and "listed_at_filing" in qa and "not_ipo_text" in qa
    # 두 번째 실행: 받은 원문은 캐시에서 다시 쓴다
    for rno in downloaded:
        if not rno.endswith("06"):
            (Fake.large_dir / "documents").mkdir(parents=True, exist_ok=True)
            (Fake.large_dir / "documents" / f"{rno}.zip").write_bytes((tmp_path / f"{rno}.zip").read_bytes())
    downloaded.clear()
    ip.run(cfg, "2026-10-20", client=Fake())
    assert downloaded == ["20250404000006"]


def test_listing_dates_and_ipo_signals(cfg, tmp_path):
    import json as _json
    from research.vol03 import ipo_discounts as ip
    raw = tmp_path / "raw" / "krx"
    raw.mkdir(parents=True)
    (raw / "ksq_base_info_20261019.json").write_text(_json.dumps({"OutBlock_1": [{"ISU_SRT_CD": "222222", "LIST_DD": "2025/06/01"}]}), encoding="utf-8")
    c = copy.deepcopy(cfg)
    c["paths"]["raw"] = str(tmp_path / "raw")
    c["research"]["vol03"]["ipo_discounts"]["listing_sources"]["krx_raw_globs"] = ["ksq_base_info_*.json"]
    pd.DataFrame([{"stock_code": "111111", "list_dt": "2010-05-03"}]).to_csv(c["research"]["vol03"]["ipo_discounts"]["listing_sources"]["manual"], index=False)
    dates = ip.listing_dates(c)
    assert dates == {"222222": "20250601", "111111": "20100503"}
    assert ip.listed_at_filing("222222", "20250410", dates) == (False, "20250601")
    assert ip.listed_at_filing("111111", "20250410", dates) == (True, "20100503")
    assert ip.listed_at_filing("", "20250410", dates) == (None, "") and ip.listed_at_filing("999999", "20250410", dates) == (None, "")
    kw = cfg["research"]["vol03"]["ipo_discounts"]["ipo_keywords"]
    assert len(ip.ipo_signals(ip.to_text(DOC_IMPLIED), kw)) >= 2 and len(ip.ipo_signals(DOC_HIGH, kw)) >= 2
    assert len(ip.ipo_signals(DOC_RIGHTS, kw)) == 0


def test_estimate_from_log():
    from research.vol03 import ipo_discounts as ip
    rows = []
    for m in range(1, 13):                       # 2025: 매월 상장사 최초 신고서 4건(= IPO 3 + 유상증자 1, 지금은 모두 상장사)
        for k in range(4):
            rows.append({"window": f"2025{m:02d}", "corp_name": f"회사{m}_{k}", "corp_code": f"{m:02d}{k}", "corp_cls": "K",
                         "rcept_dt": f"2025{m:02d}10", "rcept_no": f"r{m}{k}", "report_nm": "증권신고서(지분증권)", "decision": "excluded_cls", "note": ""})
    for m, (ne, nk) in {"202609": (6, 1), "202610": (5, 1)}.items():   # 최근: 대부분 아직 상장 전(E) → 상장사 최초 신고서 = 유상증자
        for k in range(ne):
            rows.append({"window": m, "corp_name": f"E{m}{k}", "corp_code": f"E{m}{k}", "corp_cls": "E", "rcept_dt": m + "05",
                         "rcept_no": f"e{m}{k}", "report_nm": "증권신고서(지분증권)", "decision": "used", "note": ""})
        for k in range(nk):
            rows.append({"window": m, "corp_name": f"K{m}{k}", "corp_code": f"K{m}{k}", "corp_cls": "K", "rcept_dt": m + "05",
                         "rcept_no": f"k{m}{k}", "report_nm": "증권신고서(지분증권)", "decision": "excluded_cls", "note": ""})
    rows.append({"window": "202503", "corp_name": "엔에이치스팩1호", "corp_code": "S1", "corp_cls": "K", "rcept_dt": "20250310",
                 "rcept_no": "s1", "report_nm": "증권신고서(지분증권)", "decision": "excluded_cls", "note": ""})
    e = ip.estimate_from_log(pd.DataFrame(rows), {"exclude_name_patterns": ["스팩"], "end_de": "20261020"})
    assert e["rows"] == 51 and e["spac_companies"] == 1 and e["tail_months"] == ["202609", "202610"] and e["tail_listed_inits"] == 2
    assert e["base_months"] == 12 and e["base_init_companies"] == 48
    assert e["rate"] == pytest.approx(2 / (1 + 20 / 30)) and e["ipo_lo"] <= e["ipo_est"] <= e["ipo_hi"] <= 48
    assert e["ipo_est"] == pytest.approx(48 - e["rate"] * 12)
    assert "IPO 약" in ip.estimate_markdown(e)


def test_outlier_flag_and_size_bucket():
    from research.vol03 import ipo_discounts as ip
    ip.set_outlier_bounds({"outlier_high": 0.5, "outlier_low": 0.1})
    hi = ip.parse_prospectus(ip.to_text(DOC_HIGH.replace("32,145원", "58,824원").replace("22.23% ~ 34.67%", "57.50% ~ 64.30%")))
    assert hi["outlier"] and hi["needs_review"] and "원문 확인 필요" in hi["notes"]
    assert not ip.parse_prospectus(ip.zip_text(_zip(DOC_HIGH)))["outlier"]
    assert [ip.size_bucket(x, [300, 1000]) for x in (100, 300, 999, 2000, float("nan"))] == ["<300억", "300~1,000억", "300~1,000억", "≥1,000억", "미상"]


def _ipo_rows(n: int, n_sub: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    lo = rng.uniform(0.15, 0.25, n)
    return pd.DataFrame({"company": [f"합성{i}" for i in range(n)], "corp_code": "x",
                         "market": ["KOSPI" if i < n_sub else "KOSDAQ" for i in range(n)],
                         "rcept_dt": [f"2025{1 + i % 12:02d}15" for i in range(n)], "offer_amount_low": 200.0,
                         "rcept_no": [f"2025{i:010d}" for i in range(n)], "url": "u", "report_nm": "증권신고서(지분증권)",
                         "value_per_share": 10000.0, "band_low": 10000 * (1 - lo - 0.1), "band_high": 10000 * (1 - lo),
                         "discount_low": lo, "discount_high": lo + 0.1, "discount_implied_low": lo, "discount_implied_high": lo + 0.1,
                         "multiples": "PER", "confidence": "high", "needs_review": False, "notes": ""})


@pytest.mark.parametrize("n", [5, 12])
def test_ipo_evidence_switches_band(real_cfg, tmp_path, n):
    pytest.importorskip("reportlab")
    _ipo_rows(n).to_csv(real_cfg["research"]["vol03"]["inputs"]["ipo_discounts"], index=False)
    f = D.load_facts(real_cfg)
    assert f.ipo.n == n and f.ipo.used == (n >= 10)
    a = f.assumptions["band_discount_low"]
    if n >= 10:
        assert f.band.basis == "evidence" and a.status == "sourced" and a.value == pytest.approx(np.median(_ipo_rows(n)["discount_low"]))
        assert f.band.high == im.round_price(f.val.per_share["current"] * (1 - a.value), 100)
    else:
        assert f.band.basis == "mc" and a.value is None
    from research.vol03.build import build
    out = tmp_path / f"b{n}"
    r = build(real_cfg, out_dir=out, langs=("kr",))
    assert r["render_warnings"] == {"kr": []}
    from research.vol03.story import Story
    by = {p.label: p for p in Story(real_cfg, f, "kr").pages()}
    assert by["6"].grid == "3-2" and by["8"].grid == "3-2" and any(c_.chart_key.startswith("ipo_") for c_ in by["6"].cells)


def test_ipo_sub_sample_and_outliers(real_cfg):
    t = _ipo_rows(30, n_sub=12)
    t.loc[29, ["discount_low", "discount_high"]] = [0.49, 0.575]       # 크리에이츠형 이상치 (원문 확인 필요)
    t.loc[28, "offer_amount_low"] = 1500.0                             # 코스닥이지만 공모금액 1,000억원 이상 → 하위 표본
    t.to_csv(real_cfg["research"]["vol03"]["inputs"]["ipo_discounts"], index=False)
    ev = D.ipo_evidence(real_cfg)
    assert ev.full.n == 30 and ev.sub.n == 13 and ev.chosen == "sub" and ev.used
    assert ev.full.n_outlier == 1 and ev.full.stats_ex["high"][1] < ev.full.stats["high"][1]
    assert ev.full.period == ("2025-01-15", "2025-12-15")
    sub = t[(t["market"] == "KOSPI") | (t["offer_amount_low"] >= 1000)]
    a = D.load_facts(real_cfg).assumptions["band_discount_low"]
    assert a.value == pytest.approx(np.median(sub["discount_low"])) and "하위 표본" in a.source and "2025-" in a.source
    t["market"], t["offer_amount_low"] = "KOSDAQ", 200.0                # 하위 표본 < 10건 → 전체 표본 + 각주
    t.to_csv(real_cfg["research"]["vol03"]["inputs"]["ipo_discounts"], index=False)
    f = D.load_facts(real_cfg)
    assert f.ipo.chosen == "full" and f.ipo.sub.n == 0 and f.assumptions["band_discount_low"].value == pytest.approx(np.median(t["discount_low"]))
    from research.vol03.story import Story
    by = {p.label: p for p in Story(real_cfg, f, "kr").pages()}
    txt = " ".join(str(c_.note or "") + " ".join(map(str, c_.bullets or [])) for c_ in by["6"].cells)
    assert "전체 분포 사용" in txt and "이상치" in txt and "2025-01-15" in txt
    from research.vol03 import build as B
    assert any("하위 표본" in x for x in B.anomalies(f, real_cfg)) and any("목표 40건" in x for x in B.todo_items(f, real_cfg))


def test_pit_notes_in_a3_a4(real_cfg, tmp_path):
    from research.vol03.story import Story
    t = _ipo_rows(12)
    t["corp_cls_now"] = ["K"] * 5 + ["E"] * 7                        # 접수 시점 판정 파일: 5건은 지금 상장사(복원)
    t.to_csv(real_cfg["research"]["vol03"]["inputs"]["ipo_discounts"], index=False)
    f = D.load_facts(real_cfg)
    assert f.ipo.pit and f.ipo.n_restored == 5 and f.ipo.n_cls_excluded == 0
    for lang, key in (("kr", "5건 복원"), ("en", "5 filings restored")):
        by = {p.label: p for p in Story(real_cfg, f, lang).pages()}
        assert key in by["A3"].cells[0].note and ("시점 원칙" if lang == "kr" else "Point-in-time") in by["A4"].cells[0].note
    lg = pd.DataFrame([{"window": "202505", "corp_name": "x", "corp_code": "1", "corp_cls": "K", "rcept_dt": "20250510", "rcept_no": "1",
                        "report_nm": "증권신고서(지분증권)", "decision": "excluded_cls", "note": ""}] * 3)
    lg.to_csv(real_cfg["research"]["vol03"]["inputs"]["ipo_log"], index=False)
    t.drop(columns="corp_cls_now").to_csv(real_cfg["research"]["vol03"]["inputs"]["ipo_discounts"], index=False)
    f = D.load_facts(real_cfg)
    assert not f.ipo.pit and f.ipo.n_cls_excluded == 3
    a3 = {p.label: p for p in Story(real_cfg, f, "kr").pages()}["A3"].cells[0].note
    assert "3건이 빠짐" in a3 and "재수집 예정" in a3


def test_breakdown_shortfall_without_log():
    from research.vol03 import ipo_discounts as ip
    d = _ipo_rows(5)
    d["outlier"] = False
    icfg = {"bgn_de": "20250101", "end_de": "20250331", "target_n": 40, "size_buckets": [300, 1000]}
    md = ip.breakdown(d, None, icfg)
    assert "202502" in md and "검색 로그" in md and "목표 표본 40건 미달 (5건)" in md
    lg = pd.DataFrame([ip._log({"rcept_dt": "20250115", "rcept_no": "1"}, "no_band")])
    md2 = ip.breakdown(d, lg, icfg)
    assert "원문에서 밴드 미검출 1건" in md2 and "검색 결과가 없는 월 2개" in md2


def _dart_rows(extra):
    base_ = [{"sj_div": "BS", "account_id": "ifrs-full_OtherCurrentFinancialLiabilities", "account_nm": "단기금융부채", "account_detail": "-", "thstrm_amount": "139200000000"},
             {"sj_div": "BS", "account_id": "ifrs-full_OtherNoncurrentFinancialLiabilities", "account_nm": "장기금융부채", "account_detail": "-", "thstrm_amount": "46900000000"},
             {"sj_div": "BS", "account_id": "ifrs-full_ContractLiabilities", "account_nm": "계약부채", "account_detail": "-", "thstrm_amount": "900000000000"}]
    return base_ + extra


def test_hde_debt_proxy_override_and_manual(real_cfg, tmp_path):
    from src.data_fetch import dart
    dcfg = real_cfg["data_fetch"]["dart"]
    m, _, flags = dart.extract_dart_metrics(_dart_rows([]), dcfg, ticker="267260")
    assert m["total_debt"] == pytest.approx(1392 + 469) and any("proxy" in x and "주석 확인 전" in x for x in flags)   # 계약부채 제외
    m2, _, flags2 = dart.extract_dart_metrics(_dart_rows([]), dcfg, ticker="298040")
    assert not any("proxy" in x for x in flags2) and m2.get("total_debt") != pytest.approx(1392 + 469)
    cand = {c["account_nm"]: c for c in dart.debt_candidates(_dart_rows([]), dcfg["total_debt"], ticker="267260")}
    assert cand["단기금융부채"]["selected"] and not cand["계약부채"]["selected"]
    f = D.load_facts(real_cfg)                                         # 커밋된 수동 대용치 CSV (DART 총차입금이 비었을 때만)
    hd = f.peers.table.set_index("ticker").loc["267260"]
    assert bool(hd["debt_proxy"]) and not bool(f.peers.table.set_index("ticker").loc["010120", "debt_proxy"])
    from research.vol03.story import Story
    by = {p.label: p for p in Story(real_cfg, f, "kr").pages()}
    ev_rows = [r for c_ in by["4"].cells if c_.table for r in c_.table.rows if "HD현대일렉트릭" in str(r[0])]
    assert ev_rows and any("대용" in str(r[0]) for r in ev_rows)


def test_ev_ebitda_auto_switch(real_cfg, tmp_path):
    f0 = D.load_facts(real_cfg)
    t = f0.peers.table
    app = t[t["group"].isin(["domestic", "core"]) & t["has_fin"] & (t["status"] != "held")]       # EV 후보 전원 (보류 R6 제외)
    assert f0.peers.ev_basis == "EBIT" and app["da1"].isna().any()
    rows = [{"company": r["company"], "ticker": r["ticker"], "region": r["region"], "fiscal_year": "FY2025A", "metric": "da",
             "value": round(float(r["oi1"]) * 0.2, 1), "unit": "억원" if r["region"] == "KR" else "USD mn", "source": "synthetic", "detail": "test"}
            for _, r in app.iterrows()]
    p_ = tmp_path / "peer_manual.csv"
    pd.DataFrame(rows).to_csv(p_, index=False)
    real_cfg["research"]["vol03"]["inputs"]["peer_manual"] = str(p_)
    f = D.load_facts(real_cfg)
    assert f.peers.ev_basis == "EBITDA"
    from research.vol03.story import Story
    st = Story(real_cfg, f, "kr")
    by = {p.label: p for p in st.pages()}
    assert st.da_missing() == ([], [])
    gl = [r[0] for c_ in by["A5"].cells if c_.table for r in c_.table.rows]
    assert "EV/EBITDA" in gl and "EV/EBIT" not in gl
    txt = " ".join(str(c_.note or "") for c_ in by["4"].cells)
    assert "EV/EBIT 대용" not in txt and "D&A 미수집" not in txt


# ---------------------------------------------------------------------------
# 정리: DART 총차입금 2차 매칭·점검, fetch_extra concat 경고
# ---------------------------------------------------------------------------
def test_dart_debt_id_fallback_and_candidates(tmp_path, monkeypatch, capsys):
    from src.data_fetch import dart
    cfg = copy.deepcopy(base.load_config())
    dcfg = cfg["data_fetch"]["dart"]
    rows = [{"sj_div": "BS", "account_id": "ifrs-full_ShorttermBorrowings", "account_nm": "단기금융부채", "account_detail": "-", "thstrm_amount": "10000000000"},
            {"sj_div": "BS", "account_id": "ifrs-full_LeaseLiabilities", "account_nm": "리스부채", "account_detail": "-", "thstrm_amount": "5000000000"},
            {"sj_div": "BS", "account_id": "dart_X", "account_nm": "매입채무", "account_detail": "-", "thstrm_amount": "1"}]
    m, detail, flags = dart.extract_dart_metrics(rows, dcfg)
    assert m["total_debt"] == pytest.approx(100.0) and "total_debt:id_fallback" in flags and len(detail) == 1
    named = rows + [{"sj_div": "BS", "account_id": "dart_Y", "account_nm": "장기차입금", "account_detail": "-", "thstrm_amount": "2000000000"}]
    assert [r["account_nm"] for r in dart.select_debt_lines(named, dcfg["total_debt"])] == ["장기차입금"]    # 이름 매칭이 있으면 2차 매칭 안 함
    cand = {c["account_nm"]: c for c in dart.debt_candidates(named, dcfg["total_debt"])}
    assert cand["장기차입금"]["selected"] and cand["리스부채"]["reason"] == "제외 패턴" and cand["단기금융부채"]["reason"] == "이름 패턴 불일치"
    raw = tmp_path / "raw" / "dart"
    raw.mkdir(parents=True)
    import json as _json
    (raw / "fnltt_267260_2025_CFS.json").write_text(_json.dumps({"list": named}, ensure_ascii=False), encoding="utf-8")
    cfg["paths"]["raw"] = str(tmp_path / "raw")
    monkeypatch.setattr(base, "load_config", lambda path=None: cfg)
    assert dart.main(["--debt-candidates", "267260", "--year", "2025"]) == 0
    out = capsys.readouterr().out
    assert "차입금 후보" in out and "장기차입금" in out
    assert dart.main(["--debt-candidates", "999999", "--year", "2025"]) == 1
    da_rows = named + [{"sj_div": "CF", "account_id": "dart_Dep", "account_nm": "감가상각비", "account_detail": "-", "thstrm_amount": "30000000000"},
                       {"sj_div": "CF", "account_id": "dart_RouDep", "account_nm": "사용권자산상각비", "account_detail": "-", "thstrm_amount": "1000000000"}]
    spec = cfg["research"]["vol03"]["fetch_extra"]["dart_da"]
    dc = {c["account_nm"]: c for c in dart.da_candidates(da_rows, spec)}
    assert set(dc) == {"감가상각비", "사용권자산상각비"} and dc["감가상각비"]["selected"] and dc["감가상각비"]["amount_krw_100m"] == pytest.approx(300.0)
    (raw / "fnltt_298040_2025_CFS.json").write_text(_json.dumps({"list": da_rows}, ensure_ascii=False), encoding="utf-8")
    assert dart.main(["--da-candidates", "298040", "--year", "2025"]) == 0
    assert "상각 계정 후보 2개" in capsys.readouterr().out


def test_write_extra_no_future_warning(cfg, recwarn):
    import warnings
    from research.vol03 import fetch_extra as fx
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        fx.write_extra(cfg, "2026-10-20", [{"company": "X", "ticker": "XX", "region": "US", "fiscal_year": "FY2025A", "metric": "da",
                                             "value": 1.0, "unit": "USD mn", "source": "s", "detail": ""}])
        fx.write_extra(cfg, "2026-10-20", [])
    df = pd.read_csv(cfg["research"]["vol03"]["inputs"]["peer_extra"])
    assert len(df) == 1
