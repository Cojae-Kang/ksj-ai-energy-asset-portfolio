"""KSJ Research Note Vol.1 생성 (로컬 실행). 커밋된 data/ 파일만 읽고 외부 API는 호출하지 않는다.

    python -m research.vol01.build
    python -m research.vol01.build --asof 2026-10-20 --lang kr

산출물 (research/vol01/):
  exhibits/exhibit{1..5}_{kr|en}.png (200dpi) + .svg
  KSJ_Research_Vol01_KR.pdf, KSJ_Research_Vol01_EN.pdf (A4 세로)
  linkedin_carousel.pdf (1080×1350, 8장)
  build_summary.md (포함/제외 Exhibit, 쪽수, 폰트)
데이터 파일이 없거나 값이 TODO인 Exhibit은 빼고 '데이터 확인 중'으로 표기한다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Mapping

from src.data_fetch.base import load_config, markdown_table, resolve_path, setup_logging, utc_now_iso

from . import data
from .data import Unavailable
from .fonts import register_matplotlib, register_reportlab, resolve_fonts
from .text import build_copy

logger = logging.getLogger("research.vol01.build")

PAGE_RANGE = (5, 7)


def build(cfg: Mapping, as_of: str, langs: tuple[str, ...] = ("kr", "en"), out_dir: Path | None = None) -> dict:
    from . import carousel, charts, note_pdf   # matplotlib/ReportLab은 실행 시점에만 로드

    v = cfg["research"]["vol01"]
    out_dir = out_dir or resolve_path(v["output_dir"])
    ex_dir = out_dir / "exhibits"
    fonts = resolve_fonts(cfg)
    register_matplotlib(fonts)
    register_reportlab(fonts)
    colors = cfg["research"]["colors"]

    ex1, ex2, ex3, ex4 = data.exhibit1(cfg), data.exhibit2(cfg), data.exhibit3(cfg), data.exhibit4(cfg)
    t1 = data.table1(cfg, ex4)
    sources = data.source_status(cfg)
    n_tests = data.count_tests()

    result = {"pdfs": {}, "pages": {}, "exhibits": {}, "skipped": {}, "fonts": fonts.label, "carousel": None}
    copies = {}
    for lang in ("kr", "en"):  # 캐러셀은 국문+영문 부제가 필요하므로 두 언어 문구는 항상 생성
        copies[lang] = build_copy(lang, cfg, ex1, ex2, ex3, ex4, t1, sources, n_tests, as_of)

    makers = {1: (ex1, charts.exhibit1), 2: (ex2, charts.exhibit2), 3: (ex3, charts.exhibit3), 4: (ex4, charts.exhibit4)}
    imgs: dict[str, dict[int, Path | None]] = {"kr": {}, "en": {}}
    for lang in ("kr", "en"):
        cp = copies[lang]
        for n, (e, fn) in makers.items():
            if isinstance(e, Unavailable):
                imgs[lang][n] = None
                result["skipped"][n] = e.reason
                continue
            png, _svg = fn(e, cp.exhibits[n], colors, lang, ex_dir)
            imgs[lang][n] = png
        png, _svg = charts.exhibit5(cp.exhibits[5], sources, n_tests, colors, lang, ex_dir)
        imgs[lang][5] = png
    result["exhibits"] = {n: n not in result["skipped"] for n in range(1, 6)}
    car_imgs: dict[int, Path | None] = {}       # 캐러셀용(국문, 글자 크게)
    for n, (e, fn) in makers.items():
        car_imgs[n] = None if isinstance(e, Unavailable) else fn(e, copies["kr"].exhibits[n], colors, "kr", ex_dir,
                                                                 variant="carousel")[0]
    car_imgs[5] = charts.exhibit5(copies["kr"].exhibits[5], sources, n_tests, colors, "kr", ex_dir, variant="carousel")[0]

    for lang in langs:
        path = out_dir / f"KSJ_Research_Vol01_{lang.upper()}.pdf"
        pages = note_pdf.build_note(path, copies[lang], imgs[lang], t1, sources, cfg)
        result["pdfs"][lang], result["pages"][lang] = path, pages
        if not PAGE_RANGE[0] <= pages <= PAGE_RANGE[1]:
            logger.warning("%s: %d쪽 — 목표 %d~%d쪽 벗어남", path.name, pages, *PAGE_RANGE)

    car = out_dir / "linkedin_carousel.pdf"
    n_slides = carousel.build_carousel(car, cfg, copies["kr"], copies["en"], car_imgs)
    result["carousel"], result["slides"] = car, n_slides
    result["takeaways"] = copies["kr"].takeaways
    write_summary(out_dir / "build_summary.md", result, as_of, copies["kr"])
    return result


def write_summary(path: Path, r: dict, as_of: str, kr) -> None:
    rows = [{"Exhibit": f"Exhibit {n}", "상태": "포함" if ok else "제외(데이터 확인 중)",
             "제목/사유": kr.exhibits[n].title if ok else r["skipped"].get(n, "")} for n, ok in r["exhibits"].items()]
    files = [f"- `{p.name}` — {r['pages'][lang]}쪽" for lang, p in r["pdfs"].items()]
    files.append(f"- `linkedin_carousel.pdf` — {r['slides']}장 (1080×1350)")
    path.write_text(
        f"# Vol.1 빌드 요약\n\n- 기준일: {as_of} · 빌드(UTC): {utc_now_iso()}\n- 폰트: {r['fonts']}\n\n"
        "## 산출물\n\n" + "\n".join(files) + "\n\n## Exhibits\n\n" + markdown_table(rows)
        + "\n## Key Takeaways (국문)\n\n" + "\n".join(f"{i}. {k}" for i, k in enumerate(r["takeaways"], 1)) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Note Vol.1 생성")
    p.add_argument("--asof", default=None, help="기준일 (기본: config data_fetch.as_of_default)")
    p.add_argument("--lang", choices=["kr", "en", "both"], default="both")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    as_of = args.asof or cfg["data_fetch"]["as_of_default"]
    langs = ("kr", "en") if args.lang == "both" else (args.lang,)
    r = build(cfg, as_of, langs)
    print("\n=== KSJ Research Vol.1 빌드 결과 ===")
    print(f"폰트: {r['fonts']}")
    for n, ok in r["exhibits"].items():
        print(f"Exhibit {n}: {'포함' if ok else '제외 — 데이터 확인 중: ' + r['skipped'][n]}")
    for lang, path in r["pdfs"].items():
        print(f"{path}  ({r['pages'][lang]}쪽)")
    print(f"{r['carousel']}  ({r['slides']}장)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
