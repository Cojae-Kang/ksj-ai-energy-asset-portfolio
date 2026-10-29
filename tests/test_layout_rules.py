"""전 편 공통 레이아웃 규칙 (research/vol01/layout.py): 잘림 없음 · 각주 최소 글자 · 표 출처 칸 = 입력 CSV의 짧은 출처.

PDF 검사는 저장소에 커밋된 Vol.1~5 국·영 PDF를 읽는다(pdfminer.six — 한글 글꼴을 내장하지 않은 PDF도 글자 크기까지 읽힌다).
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data_fetch import base

ROOT = Path(__file__).resolve().parents[1]
PDFS = sorted(ROOT.glob("research/vol0*/KSJ_Research_Vol0*_[KE][RN].pdf"))
FOOT_LINE = re.compile(r"^\s*(출처:|Sources?:|주:|Notes?:|상세:|Details:|\*\d+ \S)")   # 각주 줄(출처 첫 줄·이어지는 *n 줄·주·상세)
SHORT_CSV = {"02": "vol02_assumptions.csv", "03": "vol03_assumptions.csv", "04": "vol04_inputs.csv"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


@lru_cache(maxsize=None)
def _pages(pdf: Path) -> tuple:
    """쪽별 [(줄 텍스트, 최소 글자 크기)] — pdfminer 줄 단위."""
    hl = pytest.importorskip("pdfminer.high_level")
    from pdfminer.layout import LTChar, LTTextContainer, LTTextLine
    out = []
    for p in hl.extract_pages(str(pdf)):
        lines = []
        for e in p:
            if not isinstance(e, LTTextContainer):
                continue
            for ln in e:
                if isinstance(ln, LTTextLine):
                    sizes = [ch.size for ch in ln if isinstance(ch, LTChar)]
                    lines.append((ln.get_text(), min(sizes) if sizes else None))
        out.append(lines)
    return tuple(out)


def _foot_cfg() -> dict:
    return base.load_config()["research"]["footnote"]


def test_pdfs_present():
    assert len(PDFS) == 10, [p.name for p in PDFS]                       # Vol.1~5 × 국·영


def test_footnote_config_floor():
    f = _foot_cfg()
    assert float(f["size"]) >= float(f["min_size"]) > 0
    assert f["sep"] == " | "


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_no_ellipsis_in_pdf(pdf):
    """표·각주 어디에도 잘림 표시('…', '...')가 없다."""
    hits = [(i, t.strip()[:60]) for i, pg in enumerate(_pages(pdf), 1) for t, _ in pg if "…" in t or "..." in t]
    assert hits == []


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_footnote_font_not_below_min(pdf):
    """각주 줄의 글자 크기 ≥ config research.footnote.min_size (넘쳐도 줄이지 않는다)."""
    mn = float(_foot_cfg()["min_size"])
    found, small = 0, []
    for i, pg in enumerate(_pages(pdf), 1):
        for t, s in pg:
            if s is not None and FOOT_LINE.match(t):
                found += 1
                if s < mn - 0.05:
                    small.append((i, round(s, 2), t.strip()[:50]))
    assert found > 0 and small == []


def _short_rows(vol: str) -> list[dict]:
    with open(ROOT / "data" / "manual" / SHORT_CSV[vol], encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.parametrize("vol", sorted(SHORT_CSV))
def test_csv_short_source_columns(vol):
    """모든 입력 행에 짧은 출처(국·영)가 있고, 긴 근거 문장(source_name)은 그대로 남아 있다."""
    rows = _short_rows(vol)
    assert rows and {"source_short", "source_short_en"} <= set(rows[0])
    for r in rows:
        assert r["source_short"].strip() and r["source_short_en"].strip(), r
        assert "…" not in r["source_short"] + r["source_short_en"]
        assert not re.search(r"[가-힣]", r["source_short_en"]), r["source_short_en"]
    if vol == "04":
        assert sum(len(r["source_name"]) > 92 for r in rows) > 0          # 예전에 표에서 잘리던 긴 근거가 CSV에 그대로


def _shown_keys(vol: str) -> set | None:
    """표에 실제로 나오는 항목 (Vol.2는 쓰이지 않는 대체 항목을 표에서 뺀다)."""
    if vol != "02":
        return None
    from research.vol02 import data as D
    a = D.load_assumptions(base.load_config())
    return {(c, k) for c in a for k in D.table_keys(c, a[c])}


@pytest.mark.parametrize("vol", sorted(SHORT_CSV))
@pytest.mark.parametrize("lang", ["KR", "EN"])
def test_table_source_cells_match_csv_short(vol, lang):
    """A2·A3 출처 칸 = CSV source_short(_en) 원문 그대로(잘림 없음): 표에 나오는 모든 행의 짧은 출처가 PDF에 통째로 있다."""
    pdf = ROOT / "research" / f"vol{vol}" / f"KSJ_Research_Vol{vol}_{lang}.pdf"
    text = _norm("".join(t for pg in _pages(pdf) for t, _ in pg))
    col = "source_short" if lang == "KR" else "source_short_en"
    shown = _shown_keys(vol)
    miss = []
    for r in _short_rows(vol):
        s = r[col].strip()
        if s == "—" or (shown is not None and (r["case"], r["item"]) not in shown):
            continue
        if _norm(s) not in text:
            miss.append(s)
    assert miss == []


def test_story_short_source_uses_csv_column():
    """표 칸 문자열은 짧은 출처 그대로 — 길이로 자르지 않는다(긴 문자열도 통째로)."""
    from research.vol02.story import Story as S2
    from research.vol03.story import Story as S3
    from research.vol04.story import Story as S4
    long_kr, long_en = "가" * 200, "x" * 200
    a = SimpleNamespace(value=1.0, source_short=long_kr, source_short_en=long_en)
    for S in (S2, S3):
        assert S.short_source(SimpleNamespace(kr=True), a) == long_kr
        assert S.short_source(SimpleNamespace(kr=False), a) == long_en
    x = SimpleNamespace(source_short=long_kr, source_short_en=long_en, source="s", source_en="se")
    assert S4.short_source(SimpleNamespace(kr=True), x) == long_kr
    assert S4.short_source(SimpleNamespace(kr=False), x) == long_en
    x2 = SimpleNamespace(source_short="", source_short_en="", source="긴 근거", source_en="")
    assert S4.short_source(SimpleNamespace(kr=False), x2) == "긴 근거"


@pytest.fixture
def ctx():
    pytest.importorskip("reportlab")
    from research.vol01 import layout
    from research.vol01.fonts import register_reportlab, resolve_fonts
    cfg = base.load_config()
    register_reportlab(resolve_fonts(cfg))
    src = {f"s{i}": f"Source {i} — a public document title, table {i}" for i in range(12)}
    return layout.Ctx(cfg["research"]["colors"], 960, 720, "en", "KSJ", src, {"source": "Source", "note": "Note"}, Path("."), "footer")


def _texts(ps):
    return [p.getPlainText() for p in ps if hasattr(p, "getPlainText")]


def test_footnote_one_source_per_line_then_pack(ctx):
    from research.vol01 import layout
    mn = float(_foot_cfg()["min_size"])
    cell = layout.Cell(title="t", src=["s1", "s2", "s3"], note="A separate note paragraph.")
    ps, move = layout.footnote_paras(ctx, cell, 400, 400)
    t = _texts(ps)
    assert t[0].startswith("Source: *1 ") and t[1].startswith("*2 ") and t[2].startswith("*3 ")   # 한 개당 한 줄
    assert t[-1] == "Note: A separate note paragraph." and not move                             # 주는 별도 문단
    assert all(p.style.fontSize >= mn for p in ps if hasattr(p, "style"))
    many = layout.Cell(title="t", src=[f"s{i}" for i in range(12)], note="n")
    ps, _ = layout.footnote_paras(ctx, many, 900, 150)                                          # 공간 부족 → ' | '로 묶음
    t = _texts(ps)
    assert len(t) < 13 and " | " in t[0]
    assert all(p.style.fontSize >= mn for p in ps if hasattr(p, "style"))                       # 글자는 줄이지 않는다
    joined = " ".join(t)
    assert all(f"*{i + 1} {ctx.sources[f's{i}']}" in joined for i in range(12))                 # 출처 문자열은 통째로


def test_footnote_note_moved_to_notes_page(ctx):
    from research.vol01 import layout
    long_note = "Long explanation. " * 60
    cell = layout.Cell(title="t", src=["s1", "s2"], note=long_note)
    _, move = layout.footnote_paras(ctx, cell, 300, 200)
    assert move                                                                                 # 셀 높이 대비 상한 초과 → 옮김
    ps, _ = layout.footnote_paras(ctx, cell, 300, 200, moved_to="A6")
    assert _texts(ps)[-1] == "Details: A6"
