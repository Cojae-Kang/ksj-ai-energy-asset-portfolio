"""KSJ Research Note Vol.5 (완결편) 생성 — 가로형 4:3, Vol.1~4와 같은 레이아웃. 새 데이터 없음: Vol.1~4의 load_facts·build_summary만 읽는다.

    python -m research.vol05.build                 # 국문·영문 PDF + build_summary.md + figures/vol05_*.png·pdf
    python -m research.vol05.build --lang kr       # 빠른 확인용

산출물 (research/vol05/): KSJ_Research_Vol05_KR.pdf, KSJ_Research_Vol05_EN.pdf, build_summary.md
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph

from research.vol01.fonts import RL_BOLD, RL_REGULAR, register_matplotlib, register_reportlab, resolve_fonts
from src.data_fetch.base import load_config, markdown_table, resolve_path, setup_logging, utc_now_iso

from . import data
from .data import NO_VALUE, TIER_KR, VERDICT_KR

logger = logging.getLogger("research.vol05.build")


# ---------------------------------------------------------------------------
# 렌더링: Vol.1 layout 그대로 + 맺음말 쪽(afterword)
# ---------------------------------------------------------------------------
def draw_afterword(c, ctx, page, warnings: list[str]) -> None:
    """맺음말 한 쪽: 키커 · 제목 · 골드 선 · 문단(한 쪽에 들어가는 가장 큰 글자) · 서명. 문장은 그대로, 글자 크기·행간만 조정."""
    from research.vol01.layout import FOOT_H, hexc
    col = ctx.colors
    x0 = 112.0
    w = ctx.w - 2 * x0
    y = ctx.h - 64
    if page.extra.get("kicker"):
        c.setFillColor(hexc(col["gold"]))
        c.setFont(RL_BOLD, 9.5)
        c.drawString(x0, y, page.extra["kicker"])
        y -= 30
    c.setFillColor(hexc(col["text"]))
    c.setFont(RL_BOLD, 22)
    c.drawString(x0, y - 4, page.title)
    c.setStrokeColor(hexc(col["gold"]))
    c.setLineWidth(1.0)
    c.line(x0, y - 16, x0 + 60, y - 16)
    top = y - 34
    bottom = FOOT_H + 34                         # 서명 자리 포함
    paras = page.extra["paras"]
    size, lead = 12.6, 1.72
    while True:
        st = ParagraphStyle(f"aw{size}{lead}", fontName=RL_REGULAR, fontSize=size, leading=size * lead, textColor=hexc(col["text"]))
        ps = [Paragraph(escape(t), st) for t in paras]
        gap = size * 0.72
        need = sum(p.wrap(w, 10_000)[1] for p in ps) + gap * (len(ps) - 1) + size * 2.6
        if need <= top - bottom or size <= 8.0:
            break
        if lead > 1.5:
            lead = round(lead - 0.04, 2)
        else:
            size = round(size - 0.1, 2)
    if need > top - bottom:
        warnings.append(f"맺음말 넘침 ({need:.0f} > {top - bottom:.0f}pt)")
    yy = top
    for p in ps:
        _, ph = p.wrap(w, 10_000)
        p.drawOn(c, x0, yy - ph)
        yy -= ph + gap
    c.setFont(RL_BOLD, size + 1.4)
    c.setFillColor(hexc(col["brown_dark"]))
    c.drawRightString(x0 + w, yy - size * 0.9, page.extra["sign"])
    page.extra["fit"] = {"size": size, "leading": lead}


def grid_rects(ctx, top: float, grid: str) -> list[tuple[float, float, float, float]]:
    """Vol.1 격자 + Vol.5 추가 격자: '2-1'(위 2칸 + 아래 전체 폭 1칸), '3x2'(위아래 3칸씩)."""
    from research.vol01 import layout as L
    if grid not in ("2-1", "3x2"):
        return L.grid_rects(ctx, top, grid)
    full_w, full_h = ctx.w - 2 * L.MX, top - (L.FOOT_H + 4)
    ch = (full_h - L.ROW_GAP) / 2
    y2 = top - ch - L.ROW_GAP
    if grid == "2-1":
        cw = (full_w - L.COL_GAP) / 2
        return [(L.MX, top, cw, ch), (L.MX + cw + L.COL_GAP, top, cw, ch), (L.MX, y2, full_w, ch)]
    gap = L.COL_GAP * 0.75
    w3 = (full_w - 2 * gap) / 3
    return [(L.MX + k * (w3 + gap), y, w3, ch) for y in (top, y2) for k in range(3)]


def render(path: Path, ctx, pages: list, cover_bg: Path, meta: dict) -> int:
    from research.vol01 import layout as L
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
            L.draw_cover(c, ctx, pg, cover_bg)
        elif pg.kind == "back":
            L.draw_back(c, ctx, pg)
        elif pg.kind == "afterword":
            draw_afterword(c, ctx, pg, ctx.warnings)
            L.footer(c, ctx, pg.label)
        elif pg.kind == "exec":
            L.draw_exec(c, ctx, pg)
            L.footer(c, ctx, pg.label)
        elif pg.kind == "toc":
            L.draw_toc(c, ctx, pg)
            L.footer(c, ctx, pg.label)
        else:
            top = L.header(c, ctx, pg.title, pg.subtitle)
            for i, (cell, (x, y, w, h)) in enumerate(zip(pg.cells, grid_rects(ctx, top, pg.grid))):
                L.draw_cell(c, ctx, cell, x, y, w, h, pg.label, i)
            L.footer(c, ctx, pg.label)
        c.showPage()
    c.save()
    return len(pages)


def header_checks(ctx, pages: list) -> list[str]:
    """헤더 제목(두 줄 15pt)·부제(최소 9.5pt 한 줄)가 넘치지 않는지 — layout은 넘침을 기록하지 않으므로 여기서 확인."""
    from research.vol01.layout import BAR_H, MX
    out = []
    for pg in pages:
        if pg.kind not in ("body", "full", "exec", "toc"):
            continue
        max_w = ctx.w - 2 * MX - 96
        if stringWidth(pg.title, RL_BOLD, 15.5) > max_w:
            p = Paragraph(escape(pg.title), ParagraphStyle("hb", fontName=RL_BOLD, fontSize=15, leading=19))
            _, ph = p.wrap(max_w, 1000)
            if ph > BAR_H - 4:
                out.append(f"헤더 제목 넘침 p{pg.label} ({ph:.0f} > {BAR_H - 4}pt)")
        if pg.subtitle and stringWidth(pg.subtitle, RL_BOLD, 9.5) > ctx.w - 2 * MX:
            out.append(f"부제 넘침 p{pg.label}")
    return out


# ---------------------------------------------------------------------------
def build(cfg: Mapping, langs: tuple[str, ...] = ("kr", "en"), out_dir: Path | None = None, figures: bool = True,
          facts: data.Facts | None = None) -> dict:
    from research.vol01 import layout

    from . import charts, story

    v = cfg["research"]["vol05"]
    default_out = resolve_path(v["output_dir"])
    out_dir = out_dir or default_out
    build_dir = resolve_path(v["build_dir"]) if out_dir == default_out else out_dir / "_build"
    fonts = resolve_fonts(cfg)
    register_matplotlib(fonts)
    register_reportlab(fonts)
    f = facts or data.load_facts(cfg)
    w, h = (float(x) for x in v["page_pt"])
    cover_bg = charts.cover_background(build_dir / "cover_bg.png", w, h, cfg["research"]["colors"])
    result = {"pdfs": {}, "pages": {}, "fonts": fonts.label, "facts": f, "figures": [], "render_warnings": {}}
    for lang in langs:
        st = story.Story(cfg, f, lang)
        pages = st.pages()
        ctx = layout.Ctx(cfg["research"]["colors"], w, h, lang, cfg["research"]["brand"], st.sources(), st.labels(),
                         build_dir, st.footer(), cfg["research"].get("copyright", ""))
        path = out_dir / f"KSJ_Research_Vol05_{lang.upper()}.pdf"
        n = render(path, ctx, pages, cover_bg, {"title": v["title_kr"] if lang == "kr" else v["title_en"], "author": cfg["research"]["author"],
                                                "subject": f"{cfg['research']['brand']} Research Note Vol.5"})
        result["pdfs"][lang], result["pages"][lang] = path, n
        result["render_warnings"][lang] = list(ctx.warnings) + header_checks(ctx, pages)
        aw = next((p for p in pages if p.kind == "afterword"), None)
        result.setdefault("afterword_fit", {})[lang] = aw.extra.get("fit") if aw else None
        if lang == "kr":
            result["exec_lines"] = st.exec_conclusions()
            result["page_titles"] = [(pg.label, pg.title) for pg in pages if pg.kind not in ("cover", "back")]
            result["map_rows"] = st.map_rows()
        if figures and out_dir == default_out:
            result["figures"] += export_figures(cfg, st, pages, lang)
    write_summary(out_dir / "build_summary.md", result, cfg)
    return result


def export_figures(cfg: Mapping, st, pages, lang: str) -> list[Path]:
    from . import charts
    out, fig_dir, dpi = [], resolve_path(cfg["paths"]["figures"]), int(cfg["figures"]["dpi"])
    by = {p.label: p for p in pages}
    for spec in cfg["research"]["vol05"].get("figures", []):
        label, key = spec.split(":")
        cell = next((c_ for c_ in by[label].cells if c_.chart_key == key), None)
        if cell is None or cell.chart is None:
            continue
        foot = st.T("출처: ", "Source: ") + " · ".join(st.sources()[k] for k in cell.src if k != "ksj") + " · KSJ Research " + st.T("계산", "calculation")
        out += charts.export_figure(cell.chart, fig_dir / f"vol05_p{label}_{key}_{lang}", cell.title, cell.unit, foot, cfg["research"]["colors"], dpi=dpi)
    return out


def key_conclusions(f: data.Facts, cfg: Mapping) -> list[str]:
    """빌드 요약 '핵심 결론 3줄' — 판정별 한 줄 = 국문 PDF 요약 쪽 박스 제목 (값은 Facts, 판정은 저자 판단 J)."""
    from . import story
    st = story.Story(cfg, f, "kr")
    return [f"{VERDICT_KR[v]}(J) {len(st.assets_in(v))}개 — {b.title}" for v, b in zip(("invest", "wait", "avoid"), st.boxes())]


def write_summary(path: Path, r: dict, cfg: Mapping) -> None:
    f: data.Facts = r["facts"]
    v = cfg["research"]["vol05"]
    order = list(f.extra["order"])
    L = ["# Vol.5 빌드 요약\n", f"- 기준일: {f.as_of} (Vol.1~4 숫자는 각 편 기준일 그대로) · 빌드(UTC): {utc_now_iso()}", f"- 폰트: {r['fonts']}",
         "- 새 데이터 없음 — Vol.1~4의 load_facts·Story·build_summary.md에서 불러옴. 판정·트리거는 저자 판단(J). 교육·연구 목적, 투자 권유 아님", ""]
    L += ["## 핵심 결론 3줄", ""] + [f"{i}. {t}" for i, t in enumerate(key_conclusions(f, cfg), 1)] + [""]
    if r.get("exec_lines"):
        L += ["## Executive Summary 결론 문장 (국문 PDF와 같은 문장)", "", f"- 헤드라인: {r['exec_lines'][0]}"] + [f"{i}. {t}" for i, t in enumerate(r["exec_lines"][1:], 1)] + [""]
    L += ["## 근거", "", "### 투자 지도 (판정표 전문, 국문)", ""]
    L += [markdown_table([{"자산 (편 · 자리)": x["name"].replace("\n", " — "), "기준 수익률 · 핵심 숫자": x["base"], "결론을 뒤집는 가정과 그 폭": x["flip"],
                           "판정 (J)": x["verdict"], "트리거 (J)": x["trigger"]} for x in r.get("map_rows", [])]), ""]
    L += ["- 판정 규칙(J): " + " / ".join(f"{VERDICT_KR[a.verdict]} {a.key} — {a.rule_kr}" for a in f.assets), ""]
    L += ["### 결론값 출처 지도 (원 편·쪽·등급·대조)", "",
          markdown_table([{"키": k, "결론값": x.label_kr, "값": x.kr, "원 편·쪽": x.where(), "등급": x.tier, "가장 약한 입력": x.weakest_kr or "—",
                           "쪽 대조": "✓" if x.page_ok else "✗", "요약 대조": "—" if x.summary_ok is None else ("✓" if x.summary_ok else "✗")} for k, x in f.refs.items()]), ""]
    L += ["### Vol.1~4 입력 신뢰 등급 분포 (코드 집계)", ""]
    keys = data.bucket_keys(order)
    L += [markdown_table([{"편": f"Vol.{n}", **{f"{k} {TIER_KR[k]}": f.dist[n][k] for k in keys}, "합계": sum(f.dist[n].values()),
                           "입력 수": sum(1 for g in f.grades if g.vol == n),
                           "출처 가능(값 있음 − J-설계)": data.sourceable(f.dist[n])[0], "그중 A·D": data.sourceable(f.dist[n])[1]} for n in data.VOLS]
                         + [{"편": "전체", **{f"{k} {TIER_KR[k]}": f.total[k] for k in keys}, "합계": sum(f.total.values()), "입력 수": len(f.grades),
                            "출처 가능(값 있음 − J-설계)": data.sourceable(f.total)[0], "그중 A·D": data.sourceable(f.total)[1]}]), ""]
    L += ["- J 세분(J): J-설계 = " + ", ".join(f"Vol.{g.vol} {g.key}" for g in f.grades if g.bucket == data.J_DESIGN)
          + f" · J-가정 = 나머지 J {sum(1 for g in f.grades if g.bucket == data.J_ASSUME)}개. Vol.4 패턴: {v['grading']['j_design_pattern']}", ""]
    L += ["- 집계 규칙(J): Vol.1 = 공식 원자료 소스(" + ", ".join(v["grading"]["vol01_sources"]) + ") A · Vol.2 = 케이스 A·B 가정표 · Vol.3 = 가정표 · Vol.4 = 입력 CSV tier. "
          "Vol.2·3 상태 → 등급: " + ", ".join(f"{a}→{b}" for a, b in v["grading"]["status_map"].items()) + ", sourced→공식 도메인이면 A 아니면 B, 미입력은 '—'", ""]
    L += ["### 정정 기록 (git 대조)", "",
          markdown_table([{"편": f"Vol.{c['vol']}", "커밋": c["commit_first"] if c["commit_first"] == c["commit_last"] else f"{c['commit_first']}..{c['commit_last']}",
                           "날짜": c["date"], "무엇을": c["issue_kr"], "전": c["before_kr"], "후": c["after_kr"],
                           "git 대조": {True: "일치", False: "불일치", None: "미확인"}[c["verified"]]} for c in f.corrections]), ""]
    L += ["### 편별 한 줄 결론 (원 편 build_summary 헤드라인 vs 원 편 Story 국문 제목)", ""]
    L += [f"- Vol.{n}: {'일치' if h['match'] else '불일치'} — {h['kr']}" for n, h in f.headlines.items()] + [""]
    L += ["## 한계", "",
          "- 판정(넣는다/기다린다/피한다)·트리거·판정 규칙·등급 변환 규칙은 저자 판단(J). 결론값 등급은 주요 입력만 따진 것(모든 입력이 아님)",
          f"- 기존 REC 의존 자산은 수치 모델 없음 — REC 현물시장 {f.refs['v4_rec_end'].kr}(B, Vol.4 입력 rec_eligible 출처 문구). TODO(data): 기후에너지환경부 보도자료 원문·경과 규정, 기존 설비 잔존 계약·REC 비중",
          "- Vol.4 몬테카를로는 Vol.5에서 다시 돌리지 않음(결정론 결과만 사용, config vol05.vol04_mc_n)",
          f"- Vol.4 공식 원문 교체 대기 입력 {len(f.vols[4].provisional)}개는 원 편 그대로 잠정 (Vol.4 A4)",
          f"- Vol.1 KRX 교차검증 미해소 표시는 원 편 그대로: {cfg['research']['vol01'].get('source_note_kr', '')}", ""]
    n_bad_page = [k for k, x in f.refs.items() if not x.page_ok]
    n_bad_sum = [k for k, x in f.refs.items() if x.summary_ok is False]
    grade_ok = sum(sum(d.values()) for d in f.dist.values()) == len(f.grades)
    no_src = [a.key for a in f.assets if not a.refs or any(not f.refs[k].tier or not f.refs[k].page for k in a.refs)]
    L += ["## 검산", "",
          f"- 결론값 {len(f.refs)}개: 원 편 쪽 대조 불일치 {len(n_bad_page)}개 {n_bad_page or ''} · 빌드 요약 대조 불일치 {len(n_bad_sum)}개 {n_bad_sum or ''}",
          f"- 등급 집계 합 {sum(sum(d.values()) for d in f.dist.values())} = 입력 수 {len(f.grades)}: {grade_ok}",
          f"- 판정표 자산 {len(f.assets)}개 모두 출처·등급 있음: {not no_src}" + (f" (없음: {no_src})" if no_src else ""),
          f"- 정정 기록 git 대조: 일치 {sum(1 for c in f.corrections if c['verified'])} / 불일치 {sum(1 for c in f.corrections if c['verified'] is False)} / 미확인 {sum(1 for c in f.corrections if c['verified'] is None)}",
          f"- 편별 헤드라인 대조: {sum(1 for h in f.headlines.values() if h['match'])}/4", ""]
    L += ["## 산출물", ""] + [f"- `{p.name}` — {r['pages'][lg]}쪽 (960×720pt, 4:3)" for lg, p in r["pdfs"].items()]
    L += [f"- 맺음말 맞춤({lg}): 글자 {x['size']}pt · 행간 {x['leading']}" for lg, x in (r.get("afterword_fit") or {}).items() if x]
    L += [f"- 그림: {', '.join(p.name for p in r['figures'])}" if r["figures"] else "- 그림: 없음", ""]
    L += ["## 페이지 제목 (국문)", ""] + [f"- **{lab or '맺으며'}** {t}" for lab, t in r.get("page_titles", [])] + [""]
    warns = [f"- {lg}: {w}" for lg, ws in (r.get("render_warnings") or {}).items() for w in ws]
    L += ["## 렌더링 점검", ""] + (warns or ["- 없음"])
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Note Vol.5 (완결편) 생성 (가로형 4:3)")
    p.add_argument("--lang", choices=["kr", "en", "both"], default="both")
    p.add_argument("--no-figures", action="store_true")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    langs = ("kr", "en") if args.lang == "both" else (args.lang,)
    r = build(cfg, langs, figures=not args.no_figures)
    print("\n=== KSJ Research Vol.5 빌드 결과 ===")
    print(f"폰트: {r['fonts']}")
    for lang, path in r["pdfs"].items():
        print(f"{path}  ({r['pages'][lang]}쪽)")
    for t in key_conclusions(r["facts"], cfg):
        print(f"  · {t}")
    n_w = sum(len(w) for w in r["render_warnings"].values())
    print(f"  렌더링 경고 {n_w}건 → build_summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
