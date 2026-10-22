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
    for k in ("market_points", "global_market", "market_manual", "peer_extra", "peer_manual"):
        v["inputs"][k] = str(tmp_path / f"{k}.csv")          # 미국 시세·D&A 없음 = 저장소 현재 상태
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
    assert {r["case"] for r in rows} == {"target", "deal", "mc"}
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
    assert set(core["status"]) == {"applied"}
    sh = f.ovs.shares.set_index("ticker")["shares"]
    assert core.loc["VRT", "mcap1"] == pytest.approx(150.0 * sh["VRT"] / 1e6)        # 종가 × SEC 주식수
    assert core.loc["VRT", "shares_check"] == pytest.approx(3.85e8 / sh["VRT"] - 1)
    assert math.isnan(core.loc["GEV", "mcap0"])                                     # 2023 초 상장 전 → 보수에서 제외
    assert mu.groups["core"]["start"].members == ["VRT", "ETN"]
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
    for head in ("## 핵심 결론 3줄", "## 근거", "## 한계", "### 검산", "## 점검 필요 수치", "## 출처를 채워야 할 가정·데이터 (TODO)", "**수렴**"):
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
