"""KSJ Research Vol.1 테스트 — 네트워크 없이 실행. EIA/KRX 값은 테스트용 합성 데이터(tmp_path)만 사용."""
from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.vol01 import data, fetch_extra, text
from research.vol01.data import Unavailable
from research.vol01.fonts import resolve_fonts
from src.data_fetch import base

IEA_ROWS = [
    ("dc_electricity_consumption", "2024", "415"), ("dc_electricity_consumption_base", "2030", "945"),
    ("dc_electricity_consumption_base", "2035", "1200"), ("dc_demand_growth_yoy", "2025", "17"),
    ("ai_dc_demand_growth_yoy", "2025", "50"), ("global_electricity_demand_growth_yoy", "2025", "3"),
]


def write_iea(path: Path, rows=IEA_ROWS):
    pd.DataFrame([{"metric": m, "period": p, "value": v, "unit": "x", "source": "IEA test", "url": "u",
                   "published": "2025-04"} for m, p, v in rows]).to_csv(path, index=False)


def write_eia(path: Path, va_growth=1.06, us_growth=1.01, years=range(2015, 2026)):
    rows = []
    for y in years:
        rows.append({"period": y, "stateid": "VA", "stateDescription": "Virginia", "sectorid": "COM",
                     "sectorName": "commercial", "sales": 100 * va_growth ** (y - 2015), "source": "TEST"})
        rows.append({"period": y, "stateid": "US", "stateDescription": "U.S. Total", "sectorid": "COM",
                     "sectorName": "commercial", "sales": 1000 * us_growth ** (y - 2015), "source": "TEST"})
    pd.DataFrame(rows).to_csv(path, index=False)


def write_krx(path: Path, cfg, mult=(2.0, 3.0, 4.0, 1.5)):
    rows = []
    for p, m in zip(cfg["peers"]["domestic"], mult):
        for point, dd, v in (("start_2023", "20230102", 1000.0), ("latest", "20261019", 1000.0 * m)):
            rows.append({"point": point, "bas_dd": dd, "company": p["name"], "company_en": p["name_en"],
                         "ticker": p["ticker"], "market_cap_krw_100m": v})
    pd.DataFrame(rows).to_csv(path, index=False)


def write_dart(path: Path, cfg, op23=(100, 100, 100, 100), op25=(150, 100, 200, 200)):
    rows = []
    for p, a, b in zip(cfg["peers"]["domestic"], op23, op25):
        rows += [{"company": p["name"], "ticker": p["ticker"], "fiscal_year": "FY2023A", "operating_income": a},
                 {"company": p["name"], "ticker": p["ticker"], "fiscal_year": "FY2025A", "operating_income": b}]
    pd.DataFrame(rows).to_csv(path, index=False)


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(base.load_config())
    c["paths"]["processed"] = str(tmp_path / "processed")
    c["paths"]["raw"] = str(tmp_path / "raw")
    c["data_fetch"]["output"]["cache"] = str(tmp_path / "cache")
    (tmp_path / "processed").mkdir()
    inp = c["research"]["vol01"]["inputs"]
    for k in inp:
        inp[k] = str(tmp_path / f"{k}.csv")
    return c


# ---------------------------------------------------------------------------
# 데이터 규칙: 없음/TODO → Unavailable
# ---------------------------------------------------------------------------
def test_missing_files_are_unavailable(cfg):
    for fn in (data.exhibit1, data.exhibit2, data.exhibit3, data.exhibit4):
        assert isinstance(fn(cfg), Unavailable)


def test_iea_todo_value_makes_exhibit_unavailable(cfg):
    rows = [r if r[0] != "dc_electricity_consumption_base" or r[1] != "2030" else (r[0], r[1], "TODO(data)")
            for r in IEA_ROWS]
    write_iea(Path(cfg["research"]["vol01"]["inputs"]["iea"]), rows)
    e1 = data.exhibit1(cfg)
    assert isinstance(e1, Unavailable) and "2030" in e1.reason
    assert not isinstance(data.exhibit2(cfg), Unavailable)      # 다른 Exhibit은 영향 없음


def test_exhibit1_2_values_and_titles(cfg):
    write_iea(Path(cfg["research"]["vol01"]["inputs"]["iea"]))
    e1, e2 = data.exhibit1(cfg), data.exhibit2(cfg)
    assert e1.values_twh == [415, 945, 1200] and e1.multiple_2030 == pytest.approx(945 / 415)
    t1 = text.ex1_text(e1, "kr").title
    assert "2.3배" in t1 and "415TWh" in t1 and "1,200TWh" in t1
    t2 = text.ex2_text(e2, "en").title
    assert "50%" in t2 and "17x" in t2 and "(3%)" in t2           # 50/3 = 16.7 → 17x


# ---------------------------------------------------------------------------
# Exhibit 3: 데이터가 보여주는 대로 결론형 제목
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("va, us, verdict, kr_word, en_word", [
    (1.06, 1.01, "ahead", "앞서", "outpacing"),
    (1.00, 1.04, "behind", "낮아", "lagging"),
    (1.02, 1.02, "similar", "비슷한 흐름", "tracked closely"),
])
def test_exhibit3_verdict_follows_data(cfg, va, us, verdict, kr_word, en_word):
    write_eia(Path(cfg["research"]["vol01"]["inputs"]["eia_state"]), va, us)
    e = data.exhibit3(cfg)
    assert e.verdict == verdict
    assert e.index.loc[e.index["period"] == 2015, ["VA", "US"]].values.tolist() == [[100.0, 100.0]]
    assert e.va_change_pct == pytest.approx((va ** 10 - 1) * 100)
    kr, en = text.ex3_text(e, "kr").title, text.ex3_text(e, "en").title
    assert kr_word in kr and en_word in en
    assert f"{e.va_change_pct:+.0f}%" in kr
    assert "up +" not in en and "up -" not in en                  # 영문 부호 중복 방지


def test_exhibit3_requires_base_year(cfg):
    write_eia(Path(cfg["research"]["vol01"]["inputs"]["eia_state"]), years=range(2017, 2026))
    assert isinstance(data.exhibit3(cfg), Unavailable)


# ---------------------------------------------------------------------------
# Exhibit 4 + Table 1
# ---------------------------------------------------------------------------
def test_exhibit4_and_table1_decomposition(cfg):
    write_krx(Path(cfg["research"]["vol01"]["inputs"]["krx_points"]), cfg)
    write_dart(Path(cfg["research"]["vol01"]["inputs"]["dart"]), cfg)
    e4 = data.exhibit4(cfg)
    assert e4.t0 == "2023-01-02" and e4.t1 == "2026-10-19"
    assert e4.total_multiple == pytest.approx((2 + 3 + 4 + 1.5) / 4)
    assert list(e4.table["ticker"]) == [p["ticker"] for p in cfg["peers"]["domestic"]]   # config 순서 유지
    t1 = data.table1(cfg, e4)
    row = t1.table.iloc[0]
    assert row["mcap_multiple"] == pytest.approx(row["op_multiple"] * row["val_multiple"])  # 분해 항등식
    assert t1.n_valid == 4 and t1.n_valuation_up == 3   # 4번째: 시총 1.5배 < 영업이익 2배 → 배수 축소
    assert "4사 중 3곳" in text.table1_texts(t1, e4, "kr")[2]
    assert "효성중공업" in text.ex4_text(e4, "kr").title          # 최대 상승 회사 (4.0배)


def test_table1_handles_negative_operating_profit(cfg):
    write_krx(Path(cfg["research"]["vol01"]["inputs"]["krx_points"]), cfg)
    write_dart(Path(cfg["research"]["vol01"]["inputs"]["dart"]), cfg, op23=(-10, 100, 100, 100))
    t1 = data.table1(cfg, data.exhibit4(cfg))
    assert t1.n_valid == 3 and pd.isna(t1.table.iloc[0]["val_multiple"])


# ---------------------------------------------------------------------------
# fetch_extra (네트워크 없음: fake 클라이언트)
# ---------------------------------------------------------------------------
class FakeKrx:
    """휴장일은 빈 리스트. 요청한 basDd를 기록."""

    def __init__(self, open_days: set[str], peers):
        self.open, self.peers, self.calls = open_days, peers, []

    def fetch(self, name, bas_dd):
        self.calls.append(bas_dd)
        if bas_dd not in self.open:
            return []
        k = 2 if bas_dd.startswith("2026") else 1
        return [{"ISU_CD": p["ticker"], "TDD_CLSPRC": "1000", "MKTCAP": str(k * 1e12 * (i + 1)), "LIST_SHRS": "1"}
                for i, p in enumerate(self.peers)]


def test_fetch_krx_points_first_trading_day_and_prior_day(cfg):
    fake = FakeKrx({"20230102", "20261016"}, cfg["peers"]["domestic"])   # 2026-10-19(월)도 휴장 가정
    res = fetch_extra.fetch_krx_points(cfg, "2026-10-20", client=fake)
    assert res.status == base.STATUS_SUCCESS, res.message
    assert "20261020" not in fake.calls                    # 기준일 당일은 조회하지 않음
    assert fake.calls[:2] == ["20230101", "20230102"]      # 1/1 휴장 → 1/2 첫 거래일
    df = pd.read_csv(Path(cfg["paths"]["processed"]) / fetch_extra.KRX_OUT, dtype={"ticker": str, "bas_dd": str})
    assert set(df["bas_dd"]) == {"20230102", "20261016"}
    first = df[(df["point"] == "start_2023") & (df["ticker"] == "267260")].iloc[0]
    assert first["market_cap_krw_100m"] == pytest.approx(1e12 / 1e8)    # 원 → 억원
    meta = json.loads((Path(cfg["paths"]["processed"]) / "vol01_krx_mcap_points.meta.json").read_text(encoding="utf-8"))
    assert meta["as_of"] == "2026-10-20" and "latest=20261016" in meta["license_note"]


def test_find_trading_day_gives_up(cfg):
    fake = FakeKrx(set(), cfg["peers"]["domestic"])
    with pytest.raises(base.FetchError):
        fetch_extra.find_trading_day(fake, date(2023, 1, 1), +1, 3, "t")
    assert len(fake.calls) == 4


def test_eia_state_config_and_tidy(cfg):
    c2 = fetch_extra.eia_state_config(cfg)
    e = c2["data_fetch"]["eia"]
    assert e["state"] == ["VA", "US"] and e["sectors"] == ["COM"] and e["start"] == "2015"
    assert cfg["data_fetch"]["eia"]["state"] == "US"          # 원본 config는 그대로
    from src.data_fetch.eia import build_params
    params = build_params(e)
    assert ("facets[stateid][]", "VA") in params and ("facets[stateid][]", "US") in params
    rows = [{"period": "2015", "stateid": "VA", "sectorid": "COM", "sales": "10"},
            {"period": "2015", "stateid": "VA", "sectorid": "RES", "sales": "99"},
            {"period": "2015", "stateid": "US", "sectorid": "COM", "sales": "100"}]
    df = fetch_extra.tidy_eia_state(rows, ["VA", "US"], "COM", "EIA")
    assert len(df) == 2 and set(df["stateid"]) == {"VA", "US"}


def test_fetch_extra_skips_without_keys(cfg, monkeypatch, capsys):
    monkeypatch.setattr(base, "_DOTENV_LOADED", True)
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    monkeypatch.setattr(fetch_extra, "load_config", lambda path=None: cfg)
    assert fetch_extra.main(["--asof", "2026-10-20"]) == 0
    out = capsys.readouterr().out
    assert out.count("SKIPPED") == 2


# ---------------------------------------------------------------------------
# 폰트 대체
# ---------------------------------------------------------------------------
def test_font_fallback_order(tmp_path):
    reg, bold = tmp_path / "malgun.ttf", tmp_path / "malgunbd.ttf"
    reg.write_bytes(b"x")
    cands = [(tmp_path / "none.ttf", tmp_path / "none-b.ttf", "Noto Sans KR"), (reg, bold, "malgun")]
    fs = resolve_fonts({}, cands)
    assert fs.regular == reg and fs.bold == reg              # 굵은 체 없으면 보통 체
    with pytest.raises(FileNotFoundError, match="한글 폰트"):
        resolve_fonts({}, cands[:1])


def test_repo_ships_noto_sans_kr():
    fs = resolve_fonts(base.load_config())
    assert fs.regular.name == "NotoSansKR-Regular.ttf" and fs.bold.name == "NotoSansKR-Bold.ttf"


# ---------------------------------------------------------------------------
# 빌드 (matplotlib + ReportLab, 네트워크 없음)
# ---------------------------------------------------------------------------
def _pdf_pages(path: Path) -> list[tuple[float, float]]:
    raw = path.read_bytes()
    n = len(re.findall(rb"/Type\s*/Page[^s]", raw))
    boxes = [tuple(float(x) for x in m.groups()) for m in
             re.finditer(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)]
    return boxes[:n] if boxes else [(0, 0)] * n


@pytest.mark.parametrize("full", [False, True])
def test_build_outputs(cfg, tmp_path, full):
    pytest.importorskip("matplotlib")
    pytest.importorskip("reportlab")
    from research.vol01.build import build

    inp = cfg["research"]["vol01"]["inputs"]
    write_iea(Path(inp["iea"]))
    write_dart(Path(inp["dart"]), cfg)
    if full:
        write_eia(Path(inp["eia_state"]))
        write_krx(Path(inp["krx_points"]), cfg)
    out = tmp_path / "vol01"
    r = build(cfg, "2026-10-20", out_dir=out)
    assert set(r["skipped"]) == (set() if full else {3, 4})
    for lang in ("kr", "en"):
        pdf = out / f"KSJ_Research_Vol01_{lang.upper()}.pdf"
        pages = _pdf_pages(pdf)
        assert 5 <= len(pages) <= 7, f"{pdf.name}: {len(pages)}쪽"
        assert r["pages"][lang] == len(pages)
        assert all(abs(w - 595.27) < 1 and abs(h - 841.89) < 1 for w, h in pages)   # A4 세로
    car = _pdf_pages(out / "linkedin_carousel.pdf")
    assert len(car) == 8 and all((w, h) == (1080, 1350) for w, h in car)
    exhibits = {p.name for p in (out / "exhibits").glob("*.*")}
    present = [1, 2, 5] + ([3, 4] if full else [])
    for n in present:
        for lang in ("kr", "en"):
            assert {f"exhibit{n}_{lang}.png", f"exhibit{n}_{lang}.svg"} <= exhibits
    assert not any(f"exhibit{n}_" in x for n in ({1, 2, 3, 4, 5} - set(present)) for x in exhibits)
    summary = (out / "build_summary.md").read_text(encoding="utf-8")
    assert ("제외(데이터 확인 중)" in summary) != full
    if full:
        assert "버지니아" in r["takeaways"][1] and "4사 중" in r["takeaways"][2]
    else:
        assert "데이터 확인 중" in r["takeaways"][1] and "데이터 확인 중" in r["takeaways"][2]
