"""KSJ Research 시리즈 1쪽 요약 (국·영) — Vol.1 레이아웃 그대로, 표 1개 + 글 몇 줄. 새 데이터 없음.

숫자·결론은 Vol.5 load_facts(= Vol.1~4 load_facts·build_summary)와 Vol.5 Story에서 코드로 불러온다.

    python -m research.series.build             # research/series/KSJ_Research_Series_Summary_{KR,EN}.pdf
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Mapping

from research.vol01.fonts import register_matplotlib, register_reportlab, resolve_fonts
from src.data_fetch.base import load_config, resolve_path, setup_logging

logger = logging.getLogger("research.series.build")


def verdict_counts(f5) -> dict[str, int]:
    out = {"invest": 0, "wait": 0, "avoid": 0}
    for a in f5.assets:
        out[a.verdict] += 1
    return out


def check_line(st) -> str:
    """검증 방식 한 줄 — Vol.5 p6과 같은 집계(입력 수 · 출처가 있을 수 있는 입력 중 A·D · 정정 건수와 git 대조)."""
    from research.vol05.data import sourceable
    f = st.f
    tot = f.total
    n_all = sum(tot.values())
    n_src, n_ad = sourceable(tot)
    n_cor = len(f.corrections)
    n_ok = sum(1 for r in f.corrections if r["verified"])
    return st.T(f"검증: 입력 {n_all}개 모두 출처 신뢰 등급 표시 — 출처가 있을 수 있는 입력 {n_src}개 중 공식 원문·계산(A·D) {n_ad}개({n_ad / n_src * 100:.0f}%), "
                f"게시 후 정정 {n_cor}건은 커밋으로 남김(git 대조 {n_ok}/{n_cor}) — Vol.5 p6",
                f"Checks: all {n_all} inputs carry a source grade — {n_ad} of {n_src} that could have a source ({n_ad / n_src * 100:.0f}%) are official or computed (A·D); "
                f"all {n_cor} post-publication corrections kept as commits (git check {n_ok}/{n_cor}) — Vol.5 p6")


def rows(st, cfg: Mapping) -> list[list[str]]:
    """편마다 한 줄: 편 · 앉은 자리 · 질문 · 핵심 숫자 · 결론(Vol.1~4 = 각 편 Executive Summary 제목 그대로, Vol.5 = Vol.5 헤드라인)."""
    f, T, t = st.f, st.T, st.t
    keynum = {1: T(f"PER {t('v1_per')} · 멀티플 기여 {t('v1_mult_ni')} / {t('v1_mult_op')}", f"P/E {t('v1_per')} · multiple share {t('v1_mult_ni')} / {t('v1_mult_op')}"),
              2: T(f"대출 {t('v2_debt')} · 최소 DSCR {t('v2_min_dscr')}", f"Debt {t('v2_debt')} · min DSCR {t('v2_min_dscr')}"),
              3: T(f"밴드 {t('v3_band')} · 이중 고점 필요 할인율 {t('v3_req_dp')}", f"Range {t('v3_band')} · double-peak required discount {t('v3_req_dp')}"),
              4: T(f"PPA 여유 {t('v4_room')} vs 부대비용 {t('v4_net_charge')}", f"PPA room {t('v4_room')} vs charges {t('v4_net_charge')}")}
    vc = verdict_counts(f)
    keynum[5] = T(f"넣는다 {vc['invest']} · 기다린다 {vc['wait']} · 피한다 {vc['avoid']}", f"Invest {vc['invest']} · wait {vc['wait']} · avoid {vc['avoid']}")
    lens = dict(cfg["research"]["vol05"]["lenses"])
    lens[5] = cfg["research"]["series"]["vol05_lens"]
    k = "kr" if st.kr else "en"
    out = []
    for n in (1, 2, 3, 4, 5):
        L = lens[n]
        concl = f.headlines[n][k] if n < 5 else st.headline()
        out.append([f"Vol.{n} · {L['stage_' + k]}", L["seat_" + k], L["question_" + k], keynum[n], concl])
    return out


def page(st, cfg: Mapping):
    from research.vol01.layout import Cell, Page, TableSpec
    s = cfg["research"]["series"]
    T = st.T
    cell = Cell(title=T("한 산업, 다섯 자리: 편마다 앉은 자리 · 질문 · 핵심 숫자 · 결론", "One industry, five seats: each volume's seat, question, key numbers and conclusion"),
                src=["v1", "v2", "v3", "v4", "v5"],
                table=TableSpec([T("편", "Vol."), T("앉은 자리", "Seat"), T("질문", "Question"), T("핵심 숫자", "Key numbers"), T("결론", "Conclusion")],
                                rows(st, cfg), [0.09, 0.11, 0.15, 0.20, 0.45], ["L", "L", "L", "L", "L"],
                                strong_cells={(i, 1) for i in range(5)}, font_size=8.4, max_grow=1.2),
                strip=f"{check_line(st)} · GitHub {cfg['research']['repo_url']}",
                note=T("숫자·결론은 각 편 계산(기준일 2026-10-20)과 빌드 요약에서 코드로 불러옴. Target Co.·발전 자산·데이터센터는 가상. 교육·연구 목적, 투자 권유 아님",
                       "Numbers and conclusions are loaded in code from each volume's calculations (as of 20 Oct 2026) and build summaries. Target Co., the plant and the data centres are hypothetical. "
                       "For education and research only, not investment advice"))
    return Page("body", "", s["title_kr"] if st.kr else s["title_en"],
                T("AI 전력 수요 → 데이터센터·발전 자산 → 전력기기 상장 → 전력 계약 → 투자 지도", "AI power demand → data-centre and generation assets → equipment listings → power contracts → investment map"),
                [cell], grid="1x1")


def build(cfg: Mapping, langs: tuple[str, ...] = ("kr", "en"), out_dir: Path | None = None) -> dict:
    from research.vol01 import layout
    from research.vol05 import data as D5
    from research.vol05.story import Story
    s = cfg["research"]["series"]
    out_dir = out_dir or resolve_path(s["output_dir"])
    build_dir = out_dir / "_build"
    fonts = resolve_fonts(cfg)
    register_matplotlib(fonts)
    register_reportlab(fonts)
    f5 = D5.load_facts(cfg)
    w, h = (float(x) for x in s["page_pt"])
    res = {"pdfs": {}, "pages": {}, "rows": {}, "check": {}, "render_warnings": {}}
    for lang in langs:
        st = Story(cfg, f5, lang)
        src = dict(st.sources())
        src["v5"] = st.T("KSJ Research Vol.5(2026.11) — AI 에너지 자산 투자 지도", "KSJ Research Vol.5 (Nov 2026) — investment map of AI energy assets")
        foot = st.T(f"KSJ Research · 시리즈 요약 · {s['date_label']} · 교육·연구 목적, 투자 권유 아님 · 자산·기업은 가상",
                    f"KSJ Research · Series summary · {s['date_label']} · For education and research only, not investment advice · assets and company are hypothetical")
        ctx = layout.Ctx(cfg["research"]["colors"], w, h, lang, cfg["research"]["brand"], src, st.labels(), build_dir, foot, cfg["research"].get("copyright", ""))
        path = out_dir / f"KSJ_Research_Series_Summary_{lang.upper()}.pdf"
        res["pages"][lang] = layout.render(path, ctx, [page(st, cfg)], build_dir / "unused.png",
                                           {"title": s["title_kr"] if lang == "kr" else s["title_en"], "author": cfg["research"]["author"],
                                            "subject": f"{cfg['research']['brand']} Research — series summary"})
        res["pdfs"][lang] = path
        res["rows"][lang] = rows(st, cfg)
        res["check"][lang] = check_line(st)
        res["render_warnings"][lang] = list(ctx.warnings)
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research 시리즈 1쪽 요약 PDF")
    p.add_argument("--lang", choices=["kr", "en", "both"], default="both")
    a = p.parse_args(argv)
    setup_logging()
    try:
        r = build(load_config(), ("kr", "en") if a.lang == "both" else (a.lang,))
    except Exception as e:  # noqa: BLE001
        logger.error("빌드 실패: %s", e)
        return 1
    for lang, path in r["pdfs"].items():
        print(f"{path}  ({r['pages'][lang]}쪽) · 렌더링 경고 {len(r['render_warnings'][lang])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
