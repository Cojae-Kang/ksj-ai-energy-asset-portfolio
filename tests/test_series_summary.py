"""시리즈 1쪽 요약 (research/series/build.py): 1쪽·경고 0건, 숫자는 Vol.5 load_facts에서, 연락처 없음."""
from __future__ import annotations

import pytest

from src.data_fetch import base


def test_series_summary_one_page_numbers_from_facts(tmp_path):
    pytest.importorskip("reportlab")
    pytest.importorskip("matplotlib")
    from research.series import build as B
    cfg = base.load_config()
    r = B.build(cfg, out_dir=tmp_path)
    for lang in ("kr", "en"):
        assert r["pages"][lang] == 1 and r["render_warnings"][lang] == [] and r["pdfs"][lang].exists()
        rows = r["rows"][lang]
        assert [x[0][:5] for x in rows] == [f"Vol.{n}" for n in range(1, 6)]
        assert all(len(x) == 5 and all(c.strip() for c in x) for x in rows)
    from research.vol05 import data as D5
    from research.vol05.story import Story
    st = Story(cfg, D5.load_facts(cfg), "kr")
    rows = B.rows(st, cfg)
    assert st.t("v2_min_dscr") in rows[1][3] and st.t("v3_band") in rows[2][3]               # 핵심 숫자 = Vol.5 결론값
    assert rows[0][4] == st.f.headlines[1]["kr"] and rows[4][4] == st.headline()            # 결론 = 각 편 제목 그대로
    n_src, n_ad = D5.sourceable(st.f.total)
    line = B.check_line(st)
    assert f"{n_ad}개" in line and f"{n_src}개" in line and f"정정 {len(st.f.corrections)}건" in line
    hl = pytest.importorskip("pdfminer.high_level")
    for lang in ("kr", "en"):
        text = hl.extract_text(str(r["pdfs"][lang]))
        assert cfg["research"]["contact"] not in text and cfg["research"]["repo_url"] in text.replace("\n", "")   # 연락처 없음, GitHub 주소 있음
