"""A4 세로 리서치 노트 PDF (ReportLab). 1쪽 표지+Key Takeaways, 본문 섹션, 마지막 쪽 Methodology·Disclosures."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors as rl_colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .data import Table1, Unavailable
from .fonts import RL_BOLD, RL_REGULAR
from .text import Copy

MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 20 * mm, 22 * mm, 18 * mm
CONTENT_W = A4[0] - 2 * MARGIN_X


def _c(hex_: str):
    return rl_colors.HexColor(hex_)


def styles(c: Mapping) -> dict[str, ParagraphStyle]:
    navy, teal, grey = _c(c["navy"]), _c(c["teal"]), _c(c["grey"])
    base = dict(fontName=RL_REGULAR, textColor=navy, alignment=TA_LEFT)
    return {
        "kicker": ParagraphStyle("kicker", **{**base, "fontName": RL_BOLD, "textColor": teal}, fontSize=9, leading=12),
        "title": ParagraphStyle("title", **{**base, "fontName": RL_BOLD}, fontSize=23, leading=31, spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", **{**base, "textColor": grey}, fontSize=11, leading=15, spaceAfter=10),
        "meta": ParagraphStyle("meta", **base, fontSize=9.5, leading=13),
        "h1": ParagraphStyle("h1", **{**base, "fontName": RL_BOLD}, fontSize=13.5, leading=18, spaceBefore=4, spaceAfter=6),
        "body": ParagraphStyle("body", **base, fontSize=9.8, leading=15.5, spaceAfter=6),
        "kt_head": ParagraphStyle("kt_head", **{**base, "fontName": RL_BOLD, "textColor": teal}, fontSize=10.5, leading=14),
        "kt": ParagraphStyle("kt", **base, fontSize=10, leading=15, leftIndent=11, bulletIndent=0, spaceAfter=3),
        "small": ParagraphStyle("small", **{**base, "textColor": grey}, fontSize=7.6, leading=10.5),
        "pending": ParagraphStyle("pending", **{**base, "textColor": grey}, fontSize=9, leading=13),
        "cell": ParagraphStyle("cell", **base, fontSize=8.3, leading=11),
        "cell_b": ParagraphStyle("cell_b", **{**base, "fontName": RL_BOLD}, fontSize=8.3, leading=11),
        "list": ParagraphStyle("list", **base, fontSize=9, leading=13.5, leftIndent=10, bulletIndent=0, spaceAfter=3),
        "conclusion": ParagraphStyle("conclusion", **{**base, "fontName": RL_BOLD}, fontSize=10, leading=15.5),
    }


def P(text: str, st: ParagraphStyle, bullet: str | None = None) -> Paragraph:
    return Paragraph(escape(text), st, bulletText=bullet)


def exhibit_block(copy: Copy, n: int, img: Path | None, st: dict, max_h: float | None = None) -> list:
    et = copy.exhibits[n]
    if img is None or et.pending:
        msg = f"{et.label} · {copy.labels['pending']}"
        box = Table([[P(msg, st["pending"])], [P(et.pending or "", st["small"])]], colWidths=[CONTENT_W])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, rl_colors.HexColor("#B8C0CB")),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return [box, Spacer(1, 4), P(f"* {et.label}: {copy.labels['pending']} — {et.pending or ''}", st["small"]),
                Spacer(1, 8)]
    from reportlab.lib.utils import ImageReader

    iw, ih = ImageReader(str(img)).getSize()
    w = CONTENT_W
    h = w * ih / iw
    if max_h and h > max_h:
        h, w = max_h, max_h * iw / ih
    return [KeepTogether([Image(str(img), width=w, height=h)]), Spacer(1, 6)]


def key_takeaways(copy: Copy, st: dict, c: Mapping) -> Table:
    rows = [[P(copy.sections["takeaways"], st["kt_head"])]] + [[P(k, st["kt"], bullet=f"{i}.")]
                                                              for i, k in enumerate(copy.takeaways, 1)]
    t = Table(rows, colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _c(c["teal_tint"])),
        ("LINEBEFORE", (0, 0), (0, -1), 3, _c(c["teal"])),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 9), ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
    ]))
    return t


def table1_flow(copy: Copy, t1: Table1 | Unavailable, st: dict, c: Mapping) -> list:
    if isinstance(t1, Unavailable):
        return [P(f"{copy.table1_title} · {copy.labels['pending']} — {t1.reason}", st["small"])]
    kr = copy.lang == "kr"
    head = (["회사", "시가총액 배수", "영업이익 배수", "시총/영업이익 (전)", "시총/영업이익 (후)", "밸류에이션 배수"] if kr else
            ["Company", "Mkt-cap x", "OP x", "Mcap/OP (start)", "Mcap/OP (latest)", "Valuation x"])

    def f(x, suffix="x"):
        return "n/a" if x != x else f"{x:.1f}{suffix}"

    rows = [[P(h, st["cell_b"]) for h in head]]
    for _, r in t1.table.iterrows():
        rows.append([P(r["company"] if kr else r["company_en"], st["cell"]), P(f(r["mcap_multiple"]), st["cell"]),
                     P(f(r["op_multiple"]), st["cell"]), P(f(r["val_t0"], ""), st["cell"]),
                     P(f(r["val_t1"], ""), st["cell"]), P(f(r["val_multiple"]), st["cell_b"])])
    widths = [0.24, 0.14, 0.14, 0.16, 0.16, 0.16]
    t = Table(rows, colWidths=[w * CONTENT_W for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, _c(c["teal"])),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _c(c["navy"])),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, _c(c["light_grey"])),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    out = [P(copy.table1_title, st["cell_b"]), Spacer(1, 3), t, Spacer(1, 3), P(copy.table1_note, st["small"])]
    if copy.table1_sentence:
        out += [Spacer(1, 6), P(copy.table1_sentence, st["body"])]
    return out


def status_table(copy: Copy, sources: list[dict], st: dict, c: Mapping) -> Table:
    kr = copy.lang == "kr"
    head = ["소스", "용도", "상태", "기준일"] if kr else ["Source", "Use", "Status", "As of"]
    rows = [[P(h, st["cell_b"]) for h in head]]
    for s in sources:
        rows.append([P(s["org_kr"] if kr else s["org_en"], st["cell"]), P(s["use_kr"] if kr else s["use_en"], st["cell"]),
                     P(s["status_kr"] if kr else s["status_en"], st["cell_b"] if s["ok"] else st["small"]),
                     P(s["as_of"] or "—", st["cell"])])
    t = Table(rows, colWidths=[w * CONTENT_W for w in (0.30, 0.34, 0.18, 0.18)])
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, _c(c["teal"])), ("LINEBELOW", (0, 0), (-1, 0), 0.6, _c(c["navy"])),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, _c(c["light_grey"])),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_note(path: Path, copy: Copy, imgs: dict[int, Path | None], t1, sources: list[dict], cfg: Mapping) -> int:
    """PDF 생성 후 총 쪽수 반환."""
    c = cfg["research"]["colors"]
    st = styles(c)
    brand = cfg["research"]["brand"]

    def on_page(canv, doc):
        canv.saveState()
        w, h = A4
        canv.setFillColor(_c(c["teal"]))
        canv.setFont(RL_BOLD, 8)
        canv.drawString(MARGIN_X, h - 12 * mm, brand.upper() if copy.lang == "en" else brand)
        canv.setFillColor(_c(c["grey"]))
        canv.setFont(RL_REGULAR, 8)
        canv.drawRightString(w - MARGIN_X, h - 12 * mm, f"{copy.labels['note_no']} | {copy.date}")
        canv.setStrokeColor(_c(c["teal"]))
        canv.setLineWidth(0.8)
        canv.line(MARGIN_X, h - 14 * mm, w - MARGIN_X, h - 14 * mm)
        canv.setStrokeColor(_c(c["light_grey"]))
        canv.line(MARGIN_X, 12 * mm, w - MARGIN_X, 12 * mm)
        canv.setFont(RL_REGULAR, 7.5)
        canv.drawString(MARGIN_X, 8 * mm, copy.labels["page_footer"])
        canv.drawRightString(w - MARGIN_X, 8 * mm, str(doc.page))
        canv.restoreState()

    s = copy.sections
    ex_h = 92 * mm   # 한 쪽에 Exhibit 2개 배치 시 높이 상한
    story = [
        Spacer(1, 6 * mm), P(copy.labels["note_no"].upper(), st["kicker"]), Spacer(1, 3),
        P(copy.title, st["title"]), P(copy.subtitle, st["subtitle"]),
        P(f"{copy.date}  ·  {copy.labels['author']}", st["meta"]), Spacer(1, 9 * mm),
        key_takeaways(copy, st, c), Spacer(1, 8 * mm), P(copy.intro, st["body"]), Spacer(1, 4 * mm),
        P(copy.conclusion, st["conclusion"]),
        PageBreak(),
        P(s["s1"], st["h1"]), P(copy.exhibits[1].body or "", st["body"]),
        *exhibit_block(copy, 1, imgs.get(1), st, ex_h),
        P(copy.exhibits[2].body or "", st["body"]),
        *exhibit_block(copy, 2, imgs.get(2), st, ex_h),
        PageBreak(),
        P(s["s2"], st["h1"]), P(copy.exhibits[3].body or "", st["body"]),
        *exhibit_block(copy, 3, imgs.get(3), st, 120 * mm),
        PageBreak(),
        P(s["s3"], st["h1"]), P(copy.exhibits[4].body or "", st["body"]),
        *exhibit_block(copy, 4, imgs.get(4), st, 105 * mm),
        *table1_flow(copy, t1, st, c),
        PageBreak(),
        P(s["s4"], st["h1"]), P(copy.exhibits[5].body, st["body"]),
        *exhibit_block(copy, 5, imgs.get(5), st, 118 * mm),
        P(s["sources"], st["cell_b"]), Spacer(1, 3), status_table(copy, sources, st, c),
        PageBreak(),
        P(s["s5"], st["h1"]), *[P(m, st["list"], bullet="•") for m in copy.methodology], Spacer(1, 6 * mm),
        P(s["s6"], st["h1"]), *[P(d, st["list"], bullet="•") for d in copy.disclosures],
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
                            topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
                            title=copy.title, author=copy.labels["author"], subject=brand,
                            creator="KSJ Research build.py")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return doc.page
