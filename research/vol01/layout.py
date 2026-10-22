"""가로형 4:3 리서치 보고서 레이아웃 (ReportLab canvas).

페이지 사양(Page/Cell/TableSpec)을 받아 그린다. 숫자·문구는 story.py가 만들고, 여기서는 배치만 한다.
본문 페이지: 차콜 헤더 바(결론 문장, 흰색 굵게) → 굵은 부제 한 줄 → 골드 가는 구분선 → 2×2 Exhibit 그리드.
각 Exhibit: 주장형 굵은 제목 + 각주 표시(*1) → 범례·단위 한 줄 → 차트/표 → 출처·주 두 줄.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from .fonts import RL_BOLD, RL_REGULAR

MX = 34            # 좌우 여백
BAR_H = 60         # 헤더 바 높이
GRID_TOP_GAP = 50  # 헤더 바 아래 ~ 그리드 시작
FOOT_H = 30        # 하단 쪽 번호 영역
COL_GAP = 26
ROW_GAP = 16


def hexc(h: str):
    return rl_colors.HexColor(h)


# ---------------------------------------------------------------------------
# 사양
# ---------------------------------------------------------------------------
@dataclass
class TableSpec:
    header: list[str]
    rows: list[list[str]]
    widths: list[float]                       # 비율 (합 1)
    align: list[str] | None = None            # 'L' | 'R' | 'C'
    shade_rows: set[int] = field(default_factory=set)          # 핵심 행 #F5F2ED 음영 (본문 행 인덱스)
    bold_rows: set[int] = field(default_factory=set)
    gold_cells: set[tuple[int, int]] = field(default_factory=set)   # 핵심 숫자 골드
    strong_cells: set[tuple[int, int]] = field(default_factory=set)  # 굵은 다크 브라운
    brick_cells: set[tuple[int, int]] = field(default_factory=set)   # 음수·리스크
    font_size: float = 8.4
    fill: bool = True                         # 셀 높이에 맞춰 글자·행 간격을 키움
    max_grow: float = 1.32
    single_line_cols: set[int] = field(default_factory=set)   # 줄바꿈 없이 한 줄로 유지할 열
    spans: list[tuple[int, int, int]] = field(default_factory=list)  # (본문 행, 시작 열, 끝 열) 병합


@dataclass
class Cell:
    title: str = ""
    src: list[str] = field(default_factory=list)             # 출처 키 → *1, *2 …
    legend: list[tuple[str, str]] = field(default_factory=list)  # (색, 라벨)
    unit: str = ""
    note: str = ""                                            # "주:" 뒤 문장
    chart: Callable[[Path, float, float], None] | None = None  # (png 경로, 폭 pt, 높이 pt)
    chart_key: str = ""
    table: TableSpec | None = None
    bullets: list[str] | None = None                          # 패널(음영 박스) 글머리표
    panel_lead: str = ""
    placeholder: tuple[str, str] | None = None                # (사유, 실행 명령)
    strip: str = ""                                           # 본문 아래 음영 띠 한 줄 (예: 구현 방법)


@dataclass
class BigBox:
    number: str
    caption: str          # 숫자 설명 한 줄
    title: str            # 결론 제목
    bullets: list[str]


@dataclass
class Page:
    kind: str                         # cover | exec | toc | body | full | back
    label: str = ""                   # 쪽 번호 (예: "3", "A1")
    title: str = ""
    subtitle: str = ""
    cells: list[Cell] = field(default_factory=list)
    grid: str = "2x2"                 # 2x2 | 1x1 | 2x1 (위아래) | 1x2 (좌우)
    boxes: list[BigBox] = field(default_factory=list)    # exec
    toc: list[tuple[str, str, str, str]] = field(default_factory=list)  # (번호, 제목, 결론, 쪽)
    extra: dict = field(default_factory=dict)


@dataclass
class Ctx:
    """렌더링 공통 정보."""
    colors: Mapping[str, str]
    w: float
    h: float
    lang: str
    brand: str
    sources: dict[str, str]           # 출처 키 → 표기
    labels: dict[str, str]            # 고정 문구 (출처:, 주:, 데이터 수집 후 생성 …)
    build_dir: Path
    footer: str
    copyright: str = ""               # 바닥글 왼쪽·표지 (예: © 2026 Shinjae Kang)
    warnings: list[str] = field(default_factory=list)   # 렌더링 점검 결과 (목차 한 줄 넘침 등)


# ---------------------------------------------------------------------------
# 문단 도우미
# ---------------------------------------------------------------------------
def style(ctx: Ctx, size: float, bold=False, color="text", leading=1.32, align=0) -> ParagraphStyle:
    return ParagraphStyle(f"s{size}{bold}{color}", fontName=RL_BOLD if bold else RL_REGULAR, fontSize=size,
                          leading=size * leading, textColor=hexc(ctx.colors[color]), alignment=align,
                          wordWrap=None)


def para(text: str, st: ParagraphStyle, markup: bool = False) -> Paragraph:
    return Paragraph(text if markup else escape(text), st)


def draw_para(c, p: Paragraph, x: float, y_top: float, w: float) -> float:
    """y_top에 위쪽을 맞춰 그리고 높이 반환."""
    _, h = p.wrap(w, 10_000)
    p.drawOn(c, x, y_top - h)
    return h


def fit_size(text: str, font: str, size: float, max_w: float, min_size: float) -> float:
    while size > min_size and stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size


# ---------------------------------------------------------------------------
# 페이지 틀
# ---------------------------------------------------------------------------
def header(c, ctx: Ctx, title: str, subtitle: str) -> float:
    """헤더 바 + 부제 + 골드 선. 그리드 시작 y 반환."""
    col = ctx.colors
    c.setFillColor(hexc(col["charcoal"]))
    c.rect(0, ctx.h - BAR_H, ctx.w, BAR_H, fill=1, stroke=0)
    # 워드마크 (우상단, 작은 텍스트)
    c.setFillColor(hexc(col["gold"]))
    c.setFont(RL_BOLD, 9.5)
    c.drawRightString(ctx.w - MX, ctx.h - 20, ctx.brand)
    # 결론 문장 제목: 한 줄에 맞추되 넘치면 두 줄
    max_w = ctx.w - 2 * MX - 96
    size = fit_size(title, RL_BOLD, 19, max_w, 15.5)
    if stringWidth(title, RL_BOLD, size) <= max_w:
        c.setFillColor(rl_colors.white)
        c.setFont(RL_BOLD, size)
        c.drawString(MX, ctx.h - BAR_H / 2 - size * 0.36, title)
    else:
        st = ParagraphStyle("hb", fontName=RL_BOLD, fontSize=15, leading=19, textColor=rl_colors.white)
        p = Paragraph(escape(title), st)
        _, ph = p.wrap(max_w, 100)
        p.drawOn(c, MX, ctx.h - BAR_H / 2 - ph / 2)
    # 부제 (굵게 한 줄)
    sub_size = fit_size(subtitle, RL_BOLD, 12.5, ctx.w - 2 * MX, 9.5)
    c.setFillColor(hexc(col["text"]))
    c.setFont(RL_BOLD, sub_size)
    c.drawString(MX, ctx.h - BAR_H - 22, subtitle)
    c.setStrokeColor(hexc(col["gold"]))
    c.setLineWidth(0.9)
    c.line(MX, ctx.h - BAR_H - 33, ctx.w - MX, ctx.h - BAR_H - 33)
    return ctx.h - BAR_H - GRID_TOP_GAP


def footer_text(ctx: Ctx) -> str:
    return f"{ctx.copyright} · {ctx.footer}" if ctx.copyright else ctx.footer


def footer(c, ctx: Ctx, label: str) -> None:
    col = ctx.colors
    text = footer_text(ctx)
    size = fit_size(text, RL_REGULAR, 7.4, ctx.w - 2 * MX - 60, 5.5)     # 쪽 번호 자리를 남기고 넘치면 축소
    if stringWidth(text, RL_REGULAR, size) > ctx.w - 2 * MX - 60:
        ctx.warnings.append(f"바닥글 넘침: {text[:40]}…")
    c.setFillColor(hexc(col["note"]))
    c.setFont(RL_REGULAR, size)
    c.drawString(MX, 14, text)
    if label:
        c.setFont(RL_BOLD, 9.5)
        c.setFillColor(hexc(col["text"]))
        c.drawRightString(ctx.w - MX, 13, label)


def grid_rects(ctx: Ctx, top: float, grid: str) -> list[tuple[float, float, float, float]]:
    """(x, y_top, w, h) 목록."""
    bottom = FOOT_H + 4
    full_w, full_h = ctx.w - 2 * MX, top - bottom
    cw, ch = (full_w - COL_GAP) / 2, (full_h - ROW_GAP) / 2
    if grid == "1x1":
        return [(MX, top, full_w, full_h)]
    if grid == "2x1":
        return [(MX, top, full_w, ch), (MX, top - ch - ROW_GAP, full_w, ch)]
    if grid == "3-2":   # 위 3칸 + 아래 2칸
        gap = COL_GAP * 0.75
        w3 = (full_w - 2 * gap) / 3
        y2 = top - ch - ROW_GAP
        return [(MX, top, w3, ch), (MX + w3 + gap, top, w3, ch), (MX + 2 * (w3 + gap), top, w3, ch),
                (MX, y2, cw, ch), (MX + cw + COL_GAP, y2, cw, ch)]
    if grid == "1x2":
        return [(MX, top, cw, full_h), (MX + cw + COL_GAP, top, cw, full_h)]
    return [(MX, top, cw, ch), (MX + cw + COL_GAP, top, cw, ch),
            (MX, top - ch - ROW_GAP, cw, ch), (MX + cw + COL_GAP, top - ch - ROW_GAP, cw, ch)]


# ---------------------------------------------------------------------------
# Exhibit 셀
# ---------------------------------------------------------------------------
def markers(src: list[str]) -> str:
    return ",".join(f"*{i}" for i in range(1, len(src) + 1))


LEGEND_LINE = 11


def legend_items(ctx: Ctx, legend: list[tuple[str, str]], unit: str) -> list[tuple[str | None, str, float]]:
    items = [(color, label, 10 + stringWidth(label, RL_REGULAR, 7.8)) for color, label in legend]
    if unit:
        txt = f"{ctx.labels['unit']}: {unit}"
        items.append((None, txt, stringWidth(txt, RL_REGULAR, 7.8)))
    return items


def legend_lines(ctx: Ctx, w: float, legend: list[tuple[str, str]], unit: str) -> int:
    lines, cx = 1, 0.0
    for _, _, iw in legend_items(ctx, legend, unit):
        if cx > 0 and cx + iw > w:
            lines, cx = lines + 1, 0.0
        cx += iw + 12
    return lines


def draw_legend(c, ctx: Ctx, x: float, y: float, w: float, legend: list[tuple[str, str]], unit: str) -> None:
    """범례·단위를 한 줄에 배치하고, 넘치면 다음 줄로 (겹침 방지)."""
    c.setFont(RL_REGULAR, 7.8)
    cx, cy = x, y
    for color, label, iw in legend_items(ctx, legend, unit):
        if cx > x and cx + iw > x + w:
            cx, cy = x, cy - LEGEND_LINE
        if color is None:
            c.setFillColor(hexc(ctx.colors["note"]))
            c.drawString(cx, cy, label)
        else:
            c.setFillColor(hexc(color))
            c.rect(cx, cy - 1, 7, 7, fill=1, stroke=0)
            c.setFillColor(hexc(ctx.colors["text"]))
            c.drawString(cx + 10, cy, label)
        cx += iw + 12


def build_table(ctx: Ctx, spec: TableSpec, w: float, size: float, pad: float = 2.6) -> Table:
    col = ctx.colors
    hs = ParagraphStyle("th", fontName=RL_BOLD, fontSize=size, leading=size * 1.25, textColor=rl_colors.white)
    rows = [[Paragraph(escape(h), ParagraphStyle(f"th{i}", parent=hs, alignment=_al(spec, i)))
             for i, h in enumerate(spec.header)]]
    for r, row in enumerate(spec.rows):
        out = []
        for i, v in enumerate(row):
            bold = r in spec.bold_rows or (r, i) in spec.strong_cells or (r, i) in spec.gold_cells
            color = (col["gold"] if (r, i) in spec.gold_cells else col["brown_dark"] if (r, i) in spec.strong_cells
                     else col["brick"] if (r, i) in spec.brick_cells else col["text"])
            st = ParagraphStyle(f"td{r}{i}", fontName=RL_BOLD if bold else RL_REGULAR, fontSize=size,
                                leading=size * 1.28, textColor=hexc(color), alignment=_al(spec, i))
            out.append(Paragraph(escape(str(v)), st))
        rows.append(out)
    t = Table(rows, colWidths=[f * w for f in spec.widths], repeatRows=1)
    cmds = [("BACKGROUND", (0, 0), (-1, 0), hexc(col["charcoal"])),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, hexc(col["warm_grey_light"]))]
    for r in spec.shade_rows:
        cmds.append(("BACKGROUND", (0, r + 1), (-1, r + 1), hexc(col["panel"])))
    for r, c0, c1 in spec.spans:
        cmds.append(("SPAN", (c0, r + 1), (c1, r + 1)))
    t.setStyle(TableStyle(cmds))
    return t


def _al(spec: TableSpec, i: int) -> int:
    a = (spec.align or ["L"] + ["R"] * (len(spec.header) - 1))[i]
    return {"L": 0, "C": 1, "R": 2}[a]


def draw_table(c, ctx: Ctx, spec: TableSpec, x: float, y_top: float, w: float, h: float) -> None:
    """셀 높이에 맞춤: 넘치면 글자를 줄이고, 남으면 글자(최대 max_grow배) → 행 간격 순으로 키운다."""
    size, pad = spec.font_size, 2.6
    # 한 줄 유지 열: 가장 긴 값이 열 폭(좌우 여백 8pt 제외)에 들어가는 글자 크기 상한
    cap = 99.0
    for j in spec.single_line_cols:
        cw = spec.widths[j] * w - 8.5
        for r, row in enumerate(spec.rows):
            bold = r in spec.bold_rows or (r, j) in spec.gold_cells or (r, j) in spec.strong_cells
            unit_w = stringWidth(str(row[j]), RL_BOLD if bold else RL_REGULAR, 1)
            if unit_w:
                cap = min(cap, cw / unit_w)
    size = min(size, cap)
    t = build_table(ctx, spec, w, size, pad)
    _, th = t.wrap(w, h)
    while th > h and size > 6.0:
        size -= 0.3
        t = build_table(ctx, spec, w, size, pad)
        _, th = t.wrap(w, h)
    if th > h + 0.5:
        ctx.warnings.append(f"표 넘침: {spec.header[0] or spec.header[1]} ({th:.0f} > {h:.0f}pt)")
    if spec.fill and th < h * 0.9:
        while size + 0.3 <= min(spec.font_size * spec.max_grow, cap):
            t2 = build_table(ctx, spec, w, size + 0.3, pad)
            _, th2 = t2.wrap(w, h)
            if th2 > h * 0.9:
                break
            size, t, th = size + 0.3, t2, th2
        n = len(spec.rows) + 1
        extra = (h * 0.94 - th) / (2 * n)
        if extra > 0.3:
            pad = 2.6 + min(extra, 10)
            t = build_table(ctx, spec, w, size, pad)
            _, th = t.wrap(w, h)
    t.drawOn(c, x, y_top - th)


def draw_placeholder(c, ctx: Ctx, x: float, y_top: float, w: float, h: float, reason: str, cmd: str) -> None:
    col = ctx.colors
    c.setFillColor(hexc(col["panel"]))
    c.setStrokeColor(hexc(col["warm_grey_light"]))
    c.setDash(4, 3)
    c.roundRect(x, y_top - h, w, h, 4, fill=1, stroke=1)
    c.setDash()
    cy = y_top - h / 2 + 22
    c.setFillColor(hexc(col["warm_grey"]))
    c.setFont(RL_BOLD, 12)
    c.drawCentredString(x + w / 2, cy, ctx.labels["pending"])
    c.setFont(RL_REGULAR, 8.2)
    c.setFillColor(hexc(col["note"]))
    if stringWidth(reason, RL_REGULAR, 8.2) <= w - 24:
        c.drawCentredString(x + w / 2, cy - 18, reason)
    else:   # 긴 사유(빠진 입력 목록 등)는 줄바꿈
        st = ParagraphStyle("ph", fontName=RL_REGULAR, fontSize=8.2, leading=11.5, textColor=hexc(col["note"]),
                            alignment=1)
        p = Paragraph(escape(reason), st)
        _, ph = p.wrap(w - 28, h)
        p.drawOn(c, x + 14, cy - 10 - ph)
        cy -= ph - 10
    if cmd:
        size = fit_size(cmd, "Courier", 8.2, w - 24, 6)
        c.setFont("Courier", size)
        c.setFillColor(hexc(col["brown_dark"]))
        c.drawCentredString(x + w / 2, cy - 36, cmd)


def draw_panel(c, ctx: Ctx, x: float, y_top: float, w: float, h: float, lead: str, bullets: list[str]) -> None:
    col = ctx.colors
    c.setFillColor(hexc(col["panel"]))
    c.rect(x, y_top - h, w, h, fill=1, stroke=0)
    c.setFillColor(hexc(col["gold"]))
    c.rect(x, y_top - h, 2.5, h, fill=1, stroke=0)
    y = y_top - 12
    size = 11.6
    while size > 6.8:   # 패널을 채우되 넘치지 않는 가장 큰 글자 크기
        need = 0
        if lead:
            need += para(lead, style(ctx, size + 0.8, bold=True)).wrap(w - 28, 1000)[1] + 10
        for b in bullets:
            need += Paragraph(escape(b), ParagraphStyle("b", fontName=RL_REGULAR, fontSize=size, leading=size * 1.5,
                                                       leftIndent=11)).wrap(w - 28, 1000)[1] + size * 0.7
        if need <= h - 22:
            break
        size -= 0.3
    if lead:
        y -= draw_para(c, para(lead, style(ctx, size + 0.8, bold=True, color="brown_dark")), x + 14, y, w - 28) + 10
    for b in bullets:
        st = ParagraphStyle("pb", fontName=RL_REGULAR, fontSize=size, leading=size * 1.5,
                            textColor=hexc(col["text"]), leftIndent=11, bulletIndent=0)
        p = Paragraph(escape(b), st, bulletText="•")
        y -= draw_para(c, p, x + 14, y, w - 28) + size * 0.7


def draw_cell(c, ctx: Ctx, cell: Cell, x: float, y_top: float, w: float, h: float, page_label: str, idx: int) -> None:
    col = ctx.colors
    y = y_top
    if cell.title:
        mk = markers(cell.src)
        t = escape(cell.title) + (f' <font color="{col["gold"]}" size="8"><super>{mk}</super></font>' if mk else "")
        y -= draw_para(c, Paragraph(t, style(ctx, 11.2 if w > 330 else 10.2, bold=True, leading=1.28)), x, y, w) + 4
    if cell.legend or cell.unit:
        draw_legend(c, ctx, x, y - 8, w, cell.legend, cell.unit)
        y -= 15 + LEGEND_LINE * (legend_lines(ctx, w, cell.legend, cell.unit) - 1)
    # 각주 두 줄 (높이 먼저 측정)
    fn_st = style(ctx, 6.9, color="note", leading=1.3)
    lines = []
    if cell.src:
        lines.append(f"{ctx.labels['source']}: " + "  ".join(f"*{i} {ctx.sources[k]}" for i, k in enumerate(cell.src, 1)))
    if cell.note:
        lines.append(f"{ctx.labels['note']}: {cell.note}")
    fps = [para(s, fn_st) for s in lines]
    fh = sum(p.wrap(w, 1000)[1] for p in fps) + (4 if fps else 0)
    sp = para(cell.strip, style(ctx, 9.2, leading=1.35)) if cell.strip else None
    sh = (sp.wrap(w - 22, 1000)[1] + 14) if sp else 0
    body_h = y - (y_top - h) - fh - 2 - (sh + 8 if sp else 0)
    if cell.placeholder:
        draw_placeholder(c, ctx, x, y, w, body_h, *cell.placeholder)
    elif cell.chart:
        png = ctx.build_dir / f"{ctx.lang}_{page_label}_{idx}_{cell.chart_key or 'chart'}.png"
        cell.chart(png, w, body_h)
        c.drawImage(str(png), x, y - body_h, width=w, height=body_h, mask="auto")
    elif cell.table:
        draw_table(c, ctx, cell.table, x, y, w, body_h)
    elif cell.bullets is not None:
        draw_panel(c, ctx, x, y, w, body_h, cell.panel_lead, cell.bullets)
    if sp:
        sy = y - body_h - 8                                   # 띠 위쪽
        c.setFillColor(hexc(col["panel"]))
        c.rect(x, sy - sh, w, sh, stroke=0, fill=1)
        c.setFillColor(hexc(col["gold"]))
        c.rect(x, sy - sh, 3, sh, stroke=0, fill=1)
        draw_para(c, sp, x + 14, sy - 7, w - 22)
    fy = y_top - h + fh - 2
    for p in fps:
        fy -= draw_para(c, p, x, fy, w)


# ---------------------------------------------------------------------------
# 특수 페이지
# ---------------------------------------------------------------------------
def draw_bigbox(c, ctx: Ctx, b: BigBox, x: float, y_top: float, w: float, h: float) -> None:
    col = ctx.colors
    c.setFillColor(hexc(col["panel"]))
    c.rect(x, y_top - h, w, h, fill=1, stroke=0)
    c.setFillColor(hexc(col["gold"]))
    c.rect(x, y_top - h, 3, h, fill=1, stroke=0)
    num_w = 168
    size = fit_size(b.number, RL_BOLD, 46, num_w - 20, 24)
    c.setFillColor(hexc(col["gold"]))
    c.setFont(RL_BOLD, size)
    c.drawString(x + 18, y_top - 22 - size * 0.8, b.number)
    p = para(b.caption, style(ctx, 8.4, color="note", leading=1.35))
    draw_para(c, p, x + 18, y_top - 34 - size, num_w - 22)
    tx, tw = x + num_w + 6, w - num_w - 22
    fs = 10.2
    while fs > 7.6:     # 박스 높이에 맞는 가장 큰 글자
        need = para(b.title, style(ctx, fs + 2.4, bold=True, leading=1.3)).wrap(tw, 1000)[1] + 10
        need += sum(Paragraph(escape(bl), ParagraphStyle("m", fontName=RL_REGULAR, fontSize=fs, leading=fs * 1.45,
                                                         leftIndent=10)).wrap(tw, 1000)[1] + 5 for bl in b.bullets)
        if need <= h - 30:
            break
        fs -= 0.3
    y = y_top - 18
    y -= draw_para(c, para(b.title, style(ctx, fs + 2.4, bold=True, leading=1.3)), tx, y, tw) + 10
    for bl in b.bullets:
        st = ParagraphStyle("bb", fontName=RL_REGULAR, fontSize=fs, leading=fs * 1.45, textColor=hexc(col["text"]),
                            leftIndent=10, bulletIndent=0)
        y -= draw_para(c, Paragraph(escape(bl), st, bulletText="•"), tx, y, tw) + 5


def draw_exec(c, ctx: Ctx, page: Page) -> None:
    top = header(c, ctx, page.title, page.subtitle)
    bottom = FOOT_H + 4
    lw = (ctx.w - 2 * MX) * 0.40
    rx, rw = MX + lw + COL_GAP, ctx.w - 2 * MX - lw - COL_GAP
    draw_cell(c, ctx, page.cells[0], MX, top, lw, top - bottom, page.label, 0)
    n = len(page.boxes)
    gap = 10
    bh = (top - bottom - gap * (n - 1)) / n
    for i, b in enumerate(page.boxes):
        draw_bigbox(c, ctx, b, rx, top - i * (bh + gap), rw, bh)


TOC_MAX, TOC_MIN = 11.2, 8.0


def toc_line(text: str) -> str:
    """목차 한 줄 요약: 앞의 '장 이름:' 머리와 괄호 속 보충 설명을 뺀다 (장 이름은 왼쪽 열에 이미 있다)."""
    t = re.sub(r"^[^:：—]{1,32}[:：]\s*", "", text.strip())
    prev = None
    while prev != t:                                   # 중첩 괄호까지 제거
        prev, t = t, re.sub(r"\s*\([^()]*\)", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t[:1].upper() + t[1:] if t[:1].isascii() else t


def toc_size(ctx: Ctx, texts: list[str], width: float, start: float = TOC_MAX, min_size: float = TOC_MIN) -> tuple[float, list[int]]:
    """모든 행에 같은 글자 크기: 가장 긴 요약이 한 줄(width)에 들어가는 크기. (크기, 넘치는 행 번호)."""
    size = start
    while size > min_size and any(stringWidth(t, RL_REGULAR, size) > width for t in texts):
        size = round(size - 0.2, 2)
    return size, [i for i, t in enumerate(texts) if stringWidth(t, RL_REGULAR, size) > width]


def draw_toc(c, ctx: Ctx, page: Page) -> None:
    """목차: 행마다 '번호 · 장 이름 · 한 줄 요약 · 쪽'. 요약은 모든 행이 같은 글자 크기(한 줄)."""
    col = ctx.colors
    top = header(c, ctx, page.title, page.subtitle)
    y = top - 6
    row_h = (top - FOOT_H - 20) / max(len(page.toc), 1)
    cw = ctx.w - 2 * MX - 190
    size, over = toc_size(ctx, [concl for _, _, concl, _ in page.toc], cw)
    for i in over:
        ctx.warnings.append(f"목차 한 줄 넘침: {page.toc[i][0]} {page.toc[i][1]}")
    for num, name, concl, pg in page.toc:
        c.setFillColor(hexc(col["gold"]))
        c.setFont(RL_BOLD, 30 if len(num) <= 3 else 20)
        c.drawString(MX, y - 34, num)
        c.setFillColor(hexc(col["text"]))
        c.setFont(RL_BOLD, 16)
        c.drawString(MX + 100, y - 20, name)
        c.setFont(RL_REGULAR, size)
        c.drawString(MX + 100, y - 30 - size * 1.1, concl)
        c.setFont(RL_BOLD, 14)
        c.setFillColor(hexc(col["brown_dark"]))
        c.drawRightString(ctx.w - MX, y - 18, pg)
        c.setStrokeColor(hexc(col["warm_grey_light"]))
        c.setLineWidth(0.5)
        c.line(MX, y - row_h + 6, ctx.w - MX, y - row_h + 6)
        y -= row_h


def draw_cover(c, ctx: Ctx, page: Page, bg_png: Path) -> None:
    col = ctx.colors
    c.drawImage(str(bg_png), 0, 0, width=ctx.w, height=ctx.h)
    x = 64
    c.setFillColor(hexc(col["gold"]))
    c.setFont(RL_BOLD, 11)
    c.drawString(x, ctx.h - 82, ctx.brand.upper())
    c.setLineWidth(0.8)
    c.setStrokeColor(hexc(col["gold"]))
    c.line(x, ctx.h - 94, x + 220, ctx.h - 94)
    c.setFont(RL_REGULAR, 12)
    c.drawString(x, ctx.h - 250, page.extra["kicker"])
    st = ParagraphStyle("ct", fontName=RL_BOLD, fontSize=36, leading=46, textColor=rl_colors.white)
    y = ctx.h - 268
    y -= draw_para(c, Paragraph(escape(page.title), st), x, y, ctx.w * 0.86)
    st2 = ParagraphStyle("cs", fontName=RL_REGULAR, fontSize=13.5, leading=19, textColor=hexc(col["warm_grey_light"]))
    y -= 14
    y -= draw_para(c, Paragraph(escape(page.subtitle), st2), x, y, ctx.w * 0.62)
    c.setStrokeColor(hexc(col["gold"]))
    c.setLineWidth(1.2)
    c.line(x, y - 26, x + 60, y - 26)
    c.setFillColor(rl_colors.white)
    c.setFont(RL_BOLD, 13)
    c.drawString(x, 96, page.extra["author"])
    c.setFont(RL_REGULAR, 12)
    c.setFillColor(hexc(col["warm_grey_light"]))
    c.drawString(x, 76, page.extra["date"])
    c.setFont(RL_REGULAR, 8)
    c.setFillColor(hexc(col["warm_grey"]))
    c.drawRightString(ctx.w - 48, 48, page.extra["note"])
    if ctx.copyright:
        c.drawString(x, 48, ctx.copyright)


def draw_back(c, ctx: Ctx, page: Page) -> None:
    col = ctx.colors
    c.setFillColor(hexc(col["charcoal"]))
    c.rect(0, 0, ctx.w, ctx.h, fill=1, stroke=0)
    c.setFillColor(hexc(col["gold"]))
    c.setFont(RL_BOLD, 12)
    c.drawString(64, ctx.h - 96, page.title)
    c.setStrokeColor(hexc(col["gold"]))
    c.setLineWidth(0.8)
    c.line(64, ctx.h - 108, 64 + 200, ctx.h - 108)
    top = ctx.h - 136
    floor = 118                                    # 브랜드(92)·저장소(72)·연락처(56) 위
    size = 10.5
    while True:                                    # 항목이 많으면 글자를 줄여 하단 정보와 겹치지 않게
        st = ParagraphStyle(f"bk{size}", fontName=RL_REGULAR, fontSize=size, leading=size * 1.57,
                            textColor=hexc(col["warm_grey_light"]), leftIndent=12, bulletIndent=0)
        ps = [Paragraph(escape(t), st, bulletText="•") for t in page.extra["items"]]
        total = sum(p.wrap(ctx.w * 0.78, 10_000)[1] + 6 for p in ps)
        if top - total >= floor or size <= 8:
            break
        size = round(size - 0.3, 2)
    if top - total < floor:
        ctx.warnings.append("뒤표지 고지 넘침")
    y = top
    for p in ps:
        y -= draw_para(c, p, 64, y, ctx.w * 0.78) + 6
    c.setFillColor(hexc(col["gold"]))
    c.setFont(RL_BOLD, 18)
    c.drawString(64, 92, ctx.brand)
    c.setFont(RL_REGULAR, 9.5)
    c.setFillColor(hexc(col["warm_grey_light"]))
    c.drawString(64, 72, page.extra["repo"])
    if page.extra.get("contact"):
        c.drawString(64, 56, page.extra["contact"])


def render(path: Path, ctx: Ctx, pages: list[Page], cover_bg: Path, meta: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(path), pagesize=(ctx.w, ctx.h))
    c.setTitle(meta["title"])
    c.setAuthor(meta["author"])
    c.setSubject(meta["subject"])
    c.setCreator("KSJ Research build.py")
    for pg in pages:
        c.setFillColor(rl_colors.white)
        c.rect(0, 0, ctx.w, ctx.h, fill=1, stroke=0)
        if pg.kind == "cover":
            draw_cover(c, ctx, pg, cover_bg)
        elif pg.kind == "back":
            draw_back(c, ctx, pg)
        elif pg.kind == "exec":
            draw_exec(c, ctx, pg)
            footer(c, ctx, pg.label)
        elif pg.kind == "toc":
            draw_toc(c, ctx, pg)
            footer(c, ctx, pg.label)
        else:
            top = header(c, ctx, pg.title, pg.subtitle)
            for i, (cell, (x, y, w, h)) in enumerate(zip(pg.cells, grid_rects(ctx, top, pg.grid))):
                draw_cell(c, ctx, cell, x, y, w, h, pg.label, i)
            footer(c, ctx, pg.label)
        c.showPage()
    c.save()
    return len(pages)
