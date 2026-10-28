"""KSJ Research Vol.5 (완결편 · 투자 지도) 테스트 — 네트워크 없이 실행.

입력: 커밋된 data/·config와 Vol.1~4 계산(각 편 load_facts). 순수 함수 테스트는 합성 객체(테스트 전용, 사실 주장 아님).
"""
from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from research.vol05 import data as D
from src.data_fetch import base

PUBLIC_FORBIDDEN = ["config", "ASSUMPTION", "TODO", ".meta.json", "data/manual", "data/raw", "python -m", "null"]


@pytest.fixture(scope="module")
def cfg():
    return base.load_config()


@pytest.fixture(scope="module")
def F(cfg):
    return D.load_facts(cfg)


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------
ORDER = ["A", "D", "B", "C", "J"]


def _g(vol, key, grade):
    return D.Grade(vol, key, key, key, grade, "test")


def test_weakest_picks_weakest_and_applies_floor():
    gm = {(4, "a"): _g(4, "a", "A"), (4, "b"): _g(4, "b", "B"), (4, "j"): _g(4, "j", "J")}
    assert D.weakest([(4, "a"), (4, "b")], gm, ORDER)[0] == "B"
    assert D.weakest([(4, "a"), (4, "j"), (4, "b")], gm, ORDER)[:2] == ("J", "j")
    assert D.weakest([(4, "a")], gm, ORDER) == ("D", "", "")            # 계산값: 입력이 모두 A여도 최소 D
    assert D.weakest([(4, "a")], gm, ORDER, floor=None)[0] == "A"       # 입력을 그대로 옮긴 값
    assert D.weakest([], gm, ORDER)[0] == "D"


def test_grade_assumption_mapping(cfg):
    g = cfg["research"]["vol05"]["grading"]
    A = lambda **kw: SimpleNamespace(**{"value": 1.0, "origin": "csv", "status": "sourced", "url": "", **kw})  # noqa: E731
    assert D.grade_assumption(A(url="https://www.law.go.kr/x"), g)[0] == "A"
    assert D.grade_assumption(A(url="https://www.edaily.co.kr/x ; https://www.etoday.co.kr/y"), g)[0] == "B"
    assert D.grade_assumption(A(url="https://press.example.com ; https://www.sec.gov/Archives/x"), g)[0] == "A"
    assert D.grade_assumption(A(origin="evidence"), g)[0] == "D"
    assert D.grade_assumption(A(status="data"), g)[0] == "D"
    assert D.grade_assumption(A(status="verify"), g)[0] == "B"
    for st in ("judgment", "design", "neutral"):
        assert D.grade_assumption(A(status=st), g)[0] == "J"
    assert D.grade_assumption(A(value=None), g)[0] == D.NO_VALUE


def test_rec_end_year_read_from_input_source_text():
    f4 = SimpleNamespace(inputs={"rec_eligible": SimpleNamespace(source="신규 사업자 제한, REC 현물시장은 2031년 말까지 — 보도")})
    assert D.rec_end_year(f4) == 2031
    f4.inputs["rec_eligible"].source = "출처 문구 없음"
    assert D.rec_end_year(f4) is None


def _refs(**vals):
    base_ = dict(v4_hurdle=0.08, v4_irr_cfd=0.12, v2_min_dscr=1.7, v2_target_dscr=1.45, v4_irr_ppa=0.13, v4_room=(5.0, 17.0),
                 v4_net_charge=40.0, v3_req_alt=0.38, v3_band_disc=(0.22, 0.35), v4_irr_merchant=0.037, v1_mult_op=0.69)
    base_.update(vals)
    return {k: D.Ref(k, 4, "1", v, "", "", "", "") for k, v in base_.items()}


def test_verdict_rules_follow_numbers():
    v = {a.key: a.verdict for a in D.verdicts(_refs())}
    assert v == {"cfd_equity": "invest", "dc_pf_loan": "invest", "direct_ppa": "wait", "target_ipo": "wait",
                 "merchant_solar": "avoid", "legacy_rec": "avoid", "listed_equip": "avoid"}
    v = {a.key: a.verdict for a in D.verdicts(_refs(v4_room=(30.0, 45.0), v3_req_alt=0.30, v4_irr_cfd=0.07, v4_irr_merchant=0.09, v1_mult_op=0.4))}
    assert v["direct_ppa"] == "invest" and v["target_ipo"] == "invest" and v["cfd_equity"] == "wait"
    assert v["merchant_solar"] == "wait" and v["listed_equip"] == "wait"
    assert {a.key: a.verdict for a in D.verdicts(_refs(v4_irr_ppa=0.05))}["direct_ppa"] == "avoid"


# ---------------------------------------------------------------------------
# Vol.1~4에서 불러온 값 = 각 편 결론값
# ---------------------------------------------------------------------------
def test_values_equal_each_volume_result(F):
    f1, f2, f3, f4 = (F.vols[v] for v in D.VOLS)
    R = F.refs
    assert R["v1_mult_ni"].value == pytest.approx(f1.decomp.agg["mult_share"])
    assert R["v1_mult_op"].value == pytest.approx(f1.decomp.op_all["mult_share"])
    a = f2.cases["A"]
    assert R["v2_min_dscr"].value == pytest.approx(a.base.summary()["min_dscr"])
    assert R["v2_debt"].value == pytest.approx(a.base.debt)
    assert R["v2_irr_gross"].value == pytest.approx(a.power_pair()[1].summary()["equity_irr"])
    assert R["v2_dscr_gross"].value == pytest.approx(a.stresses["power_gross"].summary()["min_dscr"])
    assert R["v3_band"].value == (f3.band.low, f3.band.high)
    assert R["v3_req_dp"].value == pytest.approx(f3.mc_dp.required[0.5])
    assert R["v3_req_alt"].value == pytest.approx(f3.dp_floor_alt["mc"].required[0.5])
    for k in ("cfd", "ppa", "merchant"):
        assert R[f"v4_irr_{k}"].value == pytest.approx(f4.base[k].irr)
    assert R["v4_cfd_dscr"].value == pytest.approx(f4.base["cfd"].min_dscr)
    assert R["v4_net_charge"].value == pytest.approx(float(f4.inputs["net_charge_example"].value))
    assert R["v4_net_charge"].tier == f4.inputs["net_charge_example"].tier == "B"
    assert R["v4_rec_end"].tier == f4.inputs["rec_eligible"].tier


def test_values_found_on_source_page_and_in_build_summary(F):
    bad_page = [k for k, r in F.refs.items() if not r.page_ok]
    bad_sum = [k for k, r in F.refs.items() if r.summary_ok is False]
    assert not bad_page, f"원 편 쪽 대조 실패: {bad_page}"
    assert not bad_sum, f"빌드 요약 대조 실패: {bad_sum}"
    assert sum(1 for r in F.refs.values() if r.summary_ok) >= 20


def test_headlines_match_build_summary(F):
    for n, h in F.headlines.items():
        assert h["kr"] and h["en"], n
        assert h["match"], f"Vol.{n} 헤드라인이 build_summary와 다름"


def test_every_asset_has_source_and_grade(F):
    assert len(F.assets) == 7
    for a in F.assets:
        assert a.base, a.key
        for k in a.refs:
            r = F.refs[k]
            assert r.vol in D.VOLS and r.page, (a.key, k)
            assert r.tier in F.extra["order"], (a.key, k, r.tier)
    assert {a.verdict for a in F.assets} <= {"invest", "wait", "avoid"}


def test_grade_counts_sum_to_input_counts(F, cfg):
    from research.vol02 import data as d2
    from research.vol03 import data as d3
    n = {1: len(cfg["research"]["vol05"]["grading"]["vol01_sources"]),
         2: sum(len(d2.table_keys(c, d)) for c, d in F.vols[2].assumptions.items()),
         3: len(d3.table_keys(F.vols[3].assumptions)),
         4: len(F.vols[4].inputs)}
    for v in D.VOLS:
        assert sum(F.dist[v].values()) == n[v], v
    assert sum(F.total.values()) == len(F.grades) == sum(n.values())
    assert F.dist[4]["A"] == sum(1 for x in F.vols[4].inputs.values() if x.tier == "A")


def test_corrections_verified_against_git(F):
    if shutil.which("git") is None or all(c["verified"] is None for c in F.corrections):
        pytest.skip("git 이력 없음")
    assert len(F.corrections) >= 1
    assert all(c["verified"] for c in F.corrections), [c["commit_first"] for c in F.corrections if not c["verified"]]


# ---------------------------------------------------------------------------
# 문구·렌더링
# ---------------------------------------------------------------------------
def test_public_text_and_judgement_labels(F, cfg):
    from research.vol05 import story
    for lang in ("kr", "en"):
        st = story.Story(cfg, F, lang)
        txt = "\n".join(D.page_text(p) for p in st.pages())
        for w in PUBLIC_FORBIDDEN:
            assert w not in txt, (lang, w)
        assert "(J)" in st.p2().cells[0].table.header[3]


def test_afterword_kept_verbatim_shape():
    from research.vol05.story import AFTERWORD_EN, AFTERWORD_KR
    assert len(AFTERWORD_KR) == len(AFTERWORD_EN) == 8
    assert AFTERWORD_KR[0].startswith("이 시리즈는 하나의 질문에서 시작했습니다.")
    assert "코드는 AI의 도움을 받았지만, 무엇을 물을지 정하고 그 숫자를 믿어도 되는지 확인하는 일은 끝까지 제 몫으로 두었습니다." in AFTERWORD_KR[4]
    assert AFTERWORD_KR[-1] == "읽어 주신 모든 분께 감사드립니다."


def test_build_has_no_render_warnings(F, cfg, tmp_path):
    from research.vol05 import build as B
    r = B.build(cfg, ("kr", "en"), out_dir=tmp_path, figures=False, facts=F)
    for lang in ("kr", "en"):
        assert r["pdfs"][lang].exists() and r["pages"][lang] == 14
        assert r["render_warnings"][lang] == [], r["render_warnings"][lang]
        assert r["afterword_fit"][lang]["size"] >= 9.0
    s = (tmp_path / "build_summary.md").read_text(encoding="utf-8")
    assert "## 핵심 결론 3줄" in s and "## 근거" in s and "## 한계" in s


def test_j_split_rule_and_sourceable_base(F, cfg):
    pat = cfg["research"]["vol05"]["grading"]["j_design_pattern"]
    assert D.j_kind_text("저자 설계값: 가상 태양광", pat) == "design"
    assert D.j_kind_text("KSJ Research Vol.2 한국 케이스 설계값(1단계 20MW, 저자 설계)", pat) == "design"
    assert D.j_kind_text("저자 판단: 신규 대형 데이터센터 설계값 범위의 중간", pat) == "assumption"
    assert D.j_kind_status(SimpleNamespace(status="design")) == "design"
    assert D.j_kind_status(SimpleNamespace(status="neutral")) == "assumption"
    # J 전체 = J-설계 + J-가정, 다른 등급은 그대로
    for v in D.VOLS:
        n_j = sum(1 for g in F.grades if g.vol == v and g.grade == "J")
        assert F.dist[v][D.J_DESIGN] + F.dist[v][D.J_ASSUME] == n_j
    # Vol.4 정의값(용량·운전 연도)은 J-설계, 금융 가정(요구수익률)은 J-가정
    b4 = {g.key: g.bucket for g in F.grades if g.vol == 4}
    assert b4["asset_mw"] == b4["cod_year"] == D.J_DESIGN and b4["equity_hurdle"] == D.J_ASSUME
    n, ad = D.sourceable(F.total)
    assert n == len(F.grades) - F.total[D.J_DESIGN] - F.total[D.NO_VALUE] and ad == F.total["A"] + F.total["D"]
