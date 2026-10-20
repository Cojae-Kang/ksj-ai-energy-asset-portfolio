"""KSJ Research Note Vol.1 생성 (가로형 4:3). 커밋된 data/ 파일만 읽고 외부 API는 호출하지 않는다.

    python -m research.vol01.build
    python -m research.vol01.build --lang kr

산출물 (research/vol01/):
  KSJ_Research_Vol01_KR.pdf, KSJ_Research_Vol01_EN.pdf (960×720pt, 4:3, 같은 레이아웃)
  build_summary.md (Exhibit 상태, 핵심 계산표, 폰트)
README용: docs/img/vol01_p4_{kr,en}.png (p4 시총 분해, 분해 불가 시 시총 차트) + README.md 핵심 발견 3줄 (마커 사이 교체)
중간 산출물(차트 PNG)은 research/vol01/_build/ (git 제외).
데이터가 없으면 해당 Exhibit만 회색 박스 "데이터 수집 후 생성 + 실행 명령"으로 둔다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Mapping

from src.data_fetch.base import load_config, markdown_table, resolve_path, setup_logging, utc_now_iso

from . import data
from .fonts import register_matplotlib, register_reportlab, resolve_fonts

logger = logging.getLogger("research.vol01.build")


README_IMG_PT = (720.0, 400.0)      # README 대표 Exhibit 크기 (pt)


def build(cfg: Mapping, as_of: str, langs: tuple[str, ...] = ("kr", "en"), out_dir: Path | None = None,
          readme: Path | None = None) -> dict:
    from . import charts, layout, story   # matplotlib/ReportLab은 실행 시점에만 로드

    v = cfg["research"]["vol01"]
    out_dir = out_dir or resolve_path(v["output_dir"])
    build_dir = out_dir / "_build" if out_dir != resolve_path(v["output_dir"]) else resolve_path(v["build_dir"])
    fonts = resolve_fonts(cfg)
    register_matplotlib(fonts)
    register_reportlab(fonts)
    facts = data.load_facts(cfg, as_of)
    w, h = (float(x) for x in v["page_pt"])
    cover_bg = charts.cover_background(build_dir / "cover_bg.png", w, h, cfg["research"]["colors"])

    result = {"pdfs": {}, "pages": {}, "fonts": fonts.label, "facts": facts, "pending": {}}
    for lang in langs:
        st = story.Story(cfg, facts, lang)
        pages = st.pages()
        ctx = layout.Ctx(cfg["research"]["colors"], w, h, lang, cfg["research"]["brand"], st.sources(), st.labels(),
                         build_dir, st.footer())
        path = out_dir / f"KSJ_Research_Vol01_{lang.upper()}.pdf"
        n = layout.render(path, ctx, pages, cover_bg, {
            "title": v["title_kr"] if lang == "kr" else v["title_en"], "author": cfg["research"]["author"],
            "subject": f"{cfg['research']['brand']} Research Note Vol.1"})
        result["pdfs"][lang], result["pages"][lang] = path, n
        result["pending"][lang] = [(pg.label, cell.title, cell.placeholder[1]) for pg in pages for cell in pg.cells
                                   if cell.placeholder]
        if lang == "kr":
            result["page_titles"] = [(pg.label, pg.title) for pg in pages if pg.kind not in ("cover", "back")]
        if readme is not None:
            result.setdefault("readme", {})[lang] = readme_assets(st, pages, readme.parent / "docs" / "img", lang)
    write_summary(out_dir / "build_summary.md", result, as_of)
    if readme is not None and readme.exists():
        update_readme(readme, result["readme"])
    return result


def readme_assets(st, pages, img_dir: Path, lang: str) -> dict:
    from . import charts

    """README용 핵심 발견 3줄(요약 쪽 세 박스의 결론)과 대표 Exhibit(p4 시총 분해, 없으면 시총 차트) PNG."""
    findings = [f"**{b.title}**<br><sub>{b.caption}: {b.number}</sub>" for b in st.executive().boxes if b.number != "—"]
    p4 = next(pg for pg in pages if pg.label == "4")
    cell = next((c for key in ("waterfall", "mcap") for c in p4.cells if c.chart_key == key and c.chart), None)
    img = None
    if cell is not None:
        img = img_dir / f"vol01_p4_{lang}.png"
        src = st.sources()
        lab = st.labels()
        foot = f"{lab['source']}: " + "; ".join(src[k] for k in cell.src) + " · KSJ Research Vol.1 p4"
        charts.exhibit_png(img, cell.chart, cell.title, cell.legend, f"{lab['unit']}: {cell.unit}" if cell.unit else "",
                           foot, st.c, *README_IMG_PT, wrap=58 if lang == "kr" else 92)
    return {"findings": findings, "img": img, "img_title": cell.title if cell else "", "decomposed": bool(cell and cell.chart_key == "waterfall")}


def update_readme(readme: Path, assets: Mapping[str, dict]) -> None:
    """README.md의 <!-- vol01:findings:{lang} --> … <!-- /vol01:findings:{lang} --> 사이를 데이터 기반 문장으로 교체."""
    text = readme.read_text(encoding="utf-8")
    for lang, a in assets.items():
        start, end = f"<!-- vol01:findings:{lang} -->", f"<!-- /vol01:findings:{lang} -->"
        if start not in text or end not in text:
            logger.warning("README 마커 없음: %s", start)
            continue
        body = "\n".join(f"{i}. {s}" for i, s in enumerate(a["findings"], 1))
        head, rest = text.split(start, 1)
        text = head + start + "\n" + body + "\n" + end + rest.split(end, 1)[1]
    readme.write_text(text, encoding="utf-8")


def write_summary(path: Path, r: dict, as_of: str) -> None:
    f = r["facts"]
    lines = ["# Vol.1 빌드 요약\n", f"- 기준일: {as_of} · 빌드(UTC): {utc_now_iso()}", f"- 폰트: {r['fonts']}", ""]
    lines += ["## 산출물", ""] + [f"- `{p.name}` — {r['pages'][lang]}쪽 (960×720pt, 4:3)" for lang, p in r["pdfs"].items()]
    lines += ["", "## 페이지 제목 (국문)", ""] + [f"- **{lab}** {t}" for lab, t in r.get("page_titles", [])]
    pend = r["pending"].get("kr") or next(iter(r["pending"].values()), [])
    lines += ["", "## 데이터 수집 후 생성되는 Exhibit", ""]
    lines += [f"- p{lab}: {t} → `{cmd}`" for lab, t, cmd in pend] or ["- 없음"]
    if data.ok(f.market):
        t = f.market.table
        rows = [{"회사": r_["company"], "시총 배수": f"{r_['multiple']:.2f}", "주가 배수(원)": f"{r_['price_multiple_raw']:.2f}",
                 "분할 비율": f"{r_['split_factor']:.0f}", "분할 조정 주가 배수": f"{r_['price_multiple_adj']:.2f}",
                 "주식수 비율": f"{r_['share_ratio']:.4f}", "검산 오차(%)": f"{max(abs(r_['mcap_check_t0']), abs(r_['mcap_check_t1'])):.4f}",
                 "판정": r_["share_note"]} for _, r_ in t.iterrows()]
        lines += ["", f"## KRX 시총 검산 ({f.market.t0} → {f.market.t1})", "", markdown_table(rows),
                  f"- 합계 기준 {f.market.total_multiple:.2f}배 · 단순평균 {f.market.mean_multiple:.2f}배 · "
                  f"시작 시총 최대 비중 {f.market.largest_t0['company']} {f.market.largest_t0_share:.1f}%"]
    if data.ok(f.decomp):
        rows = []
        for _, r_ in f.decomp.table.iterrows():
            if r_["valid"]:
                rows.append({"회사": r_["company"], "Δln 시총": f"{r_['dln_mcap']:.4f}", "Δln 이익": f"{r_['dln_ni']:.4f}",
                             "Δln PER": f"{r_['dln_per']:.4f}", "이익 기여": f"{r_['earn_share']:.1%}", "멀티플 기여": f"{r_['mult_share']:.1%}",
                             "PER": f"{r_['per0']:.1f} → {r_['per1']:.1f}"})
            else:
                rows.append({"회사": r_["company"], "Δln 시총": f"분해 불가({r_['reason']})", "Δln 이익": "", "Δln PER": "",
                             "이익 기여": "", "멀티플 기여": "", "PER": ""})
        a = f.decomp.agg
        excl = "; ".join(f"{e['company']} 제외({e['reason']}, 시작 시총의 {e['share_t0']:.0f}%)" for e in f.decomp.excluded)
        lines += ["", f"## 시총 분해 ({f.decomp.fy0} → {f.decomp.fy1})", "", markdown_table(rows),
                  f"- {f.decomp.n_valid}사 합산: 이익 기여 {a['earn_share']:.1%} · 멀티플 기여 {a['mult_share']:.1%} · "
                  f"PER {a['per0']:.1f} → {a['per1']:.1f}배" + (f" · {excl}" if excl else "")]
    else:
        lines += ["", "## 시총 분해", "", f"- 생성 보류: {f.decomp.reason} → `{f.decomp.command}`"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Note Vol.1 생성 (가로형 4:3)")
    p.add_argument("--asof", default=None, help="기준일 (기본: config data_fetch.as_of_default)")
    p.add_argument("--lang", choices=["kr", "en", "both"], default="both")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    as_of = args.asof or cfg["data_fetch"]["as_of_default"]
    langs = ("kr", "en") if args.lang == "both" else (args.lang,)
    r = build(cfg, as_of, langs, readme=resolve_path("README.md"))
    print("\n=== KSJ Research Vol.1 빌드 결과 ===")
    print(f"폰트: {r['fonts']}")
    for lang, path in r["pdfs"].items():
        print(f"{path}  ({r['pages'][lang]}쪽)")
    pend = next(iter(r["pending"].values()), [])
    for lab, t, cmd in pend:
        print(f"  p{lab} 데이터 수집 후 생성: {t}  →  {cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
