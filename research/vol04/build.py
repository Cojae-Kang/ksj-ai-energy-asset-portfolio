"""KSJ Research Note Vol.4 생성 (가로형 4:3, Vol.1~3과 같은 레이아웃). 커밋된 data/ 파일과 config·입력 CSV만 읽는다.

    python -m research.vol04.build                    # 국문·영문 PDF + build_summary.md + figures/vol04_*.png·pdf
    python -m research.vol04.build --lang kr --mc 500 # 빠른 확인용

산출물 (research/vol04/): KSJ_Research_Vol04_KR.pdf, KSJ_Research_Vol04_EN.pdf, build_summary.md
입력: data/manual/vol04_inputs.csv — 항목별 신뢰 등급(A 공식 원문 · B 공식 발표 보도 · C 민간 2차 · J 저자 판단).
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path
from typing import Mapping

from research.vol01.fonts import register_matplotlib, register_reportlab, resolve_fonts
from src.data_fetch.base import load_config, markdown_table, resolve_path, setup_logging, utc_now_iso

from . import data
from .data import TIER_KR, mc_stats, ok

logger = logging.getLogger("research.vol04.build")


def vol2_link(cfg: Mapping) -> dict:
    """Vol.2 한국 케이스(A) 기준 결과 — 오프테이커 신용 참고. 실패해도 Vol.4 빌드는 계속."""
    try:
        from research.vol02 import data as d2
        s = d2.load_facts(cfg).cases["A"].base.summary()
        return {"min_dscr": float(s["min_dscr"]), "equity_irr": float(s["equity_irr"])}
    except Exception as e:  # noqa: BLE001
        logger.warning("Vol.2 연결 실패: %s", e)
        return {}


def build(cfg: Mapping, as_of: str | None = None, langs: tuple[str, ...] = ("kr", "en"), out_dir: Path | None = None,
          figures: bool = True, mc_n: int | None = None) -> dict:
    from research.vol01 import layout

    from . import charts, story

    v = cfg["research"]["vol04"]
    default_out = resolve_path(v["output_dir"])
    out_dir = out_dir or default_out
    build_dir = resolve_path(v["build_dir"]) if out_dir == default_out else out_dir / "_build"
    fonts = resolve_fonts(cfg)
    register_matplotlib(fonts)
    register_reportlab(fonts)
    facts = data.load_facts(cfg, as_of, mc_n=mc_n)
    v2 = vol2_link(cfg)
    w, h = (float(x) for x in v["page_pt"])
    cover_bg = charts.cover_background(build_dir / "cover_bg.png", w, h, cfg["research"]["colors"])
    result = {"pdfs": {}, "pages": {}, "fonts": fonts.label, "facts": facts, "figures": [], "vol2": v2}
    for lang in langs:
        st = story.Story(cfg, facts, lang, v2)
        pages = st.pages()
        ctx = layout.Ctx(cfg["research"]["colors"], w, h, lang, cfg["research"]["brand"], st.sources(), st.labels(),
                         build_dir, st.footer(), cfg["research"].get("copyright", ""))
        path = out_dir / f"KSJ_Research_Vol04_{lang.upper()}.pdf"
        n = layout.render(path, ctx, pages, cover_bg, {
            "title": v["title_kr"] if lang == "kr" else v["title_en"], "author": cfg["research"]["author"],
            "subject": f"{cfg['research']['brand']} Research Note Vol.4"})
        result["pdfs"][lang], result["pages"][lang] = path, n
        result.setdefault("render_warnings", {})[lang] = list(ctx.warnings)
        if lang == "kr":
            result["exec_lines"] = st.exec_conclusions()
            result["page_titles"] = [(pg.label, pg.title) for pg in pages if pg.kind not in ("cover", "back")]
        if figures and out_dir == default_out:
            result["figures"] += export_figures(cfg, st, pages, lang)
    write_summary(out_dir / "build_summary.md", result, cfg)
    return result


def export_figures(cfg: Mapping, st, pages, lang: str) -> list[Path]:
    from . import charts
    out, fig_dir, dpi = [], resolve_path(cfg["paths"]["figures"]), int(cfg["figures"]["dpi"])
    by = {p.label: p for p in pages}
    for label, key in (("3", "corridor"), ("5", "price_irr")):
        cell = next((c_ for c_ in by[label].cells if c_.chart_key == key), None)
        if cell is None or cell.chart is None:
            continue
        foot = st.T("출처: ", "Source: ") + " · ".join(st.sources()[k] for k in cell.src if k != "ksj") + " · KSJ Research " + st.T("계산", "calculation")
        out += charts.export_figure(cell.chart, fig_dir / f"vol04_p{label}_{key}_{lang}", cell.title, cell.unit, foot,
                                    cfg["research"]["colors"], dpi=dpi)
    return out


def _p(x: float | None, d: int = 1) -> str:
    return "—" if x is None or not math.isfinite(x) else f"{x * 100:.{d}f}%"


def key_conclusions(f: data.Facts, hz: float) -> list[str]:
    irr = {k: r.irr for k, r in f.base.items()}
    p = next(x for x in f.premium if abs(x["hazard"] - hz) < 1e-12)
    out = [f"지분 IRR: 직접 PPA(회랑 중간 {f.ppa_mid:,.1f}원) {_p(irr['ppa'])} · 한전 CfD {_p(irr['cfd'])} · 시장 SMP {_p(irr['merchant'])}",
           f"필요 PPA 가격(연 해지 {hz * 100:.0f}%) {p['price']:,.1f}원/kWh = 한전 계약 +{p['premium']:,.1f}원 → 망이용료 상한 {p['max_fee']:,.1f}원/kWh"]
    if ok(f.mc):
        s, m = mc_stats(f.mc["ppa"], f.V("equity_hurdle")), mc_stats(f.mc["merchant"], f.V("equity_hurdle"))
        out.append(f"몬테카를로: 직접 PPA P10/P50 {_p(s['p10'])}/{_p(s['p50'])}, 시장 판매 손실 확률 {_p(m['neg'], 0)}")
    return out


def write_summary(path: Path, r: dict, cfg: Mapping) -> None:
    f: data.Facts = r["facts"]
    hz = float(cfg["research"]["vol04"]["monte_carlo"]["hazard"])
    L = ["# Vol.4 빌드 요약\n", f"- 기준일: {f.as_of} · 빌드(UTC): {utc_now_iso()}", f"- 폰트: {r['fonts']}",
         "- 발전자산·오프테이커는 가상 사례. 교육·연구 목적, 투자 권유 아님", ""]
    L += ["## 핵심 결론 3줄", ""] + [f"{i}. {t}" for i, t in enumerate(key_conclusions(f, hz), 1)] + [""]
    if r.get("exec_lines"):
        L += ["## Executive Summary 결론 문장 (국문 PDF와 같은 문장)", "", f"- 헤드라인: {r['exec_lines'][0]}"] \
             + [f"{i}. {t}" for i, t in enumerate(r["exec_lines"][1:], 1)] + [""]
    L += ["## 근거", "", f"- 사업비 {f.asset.capex:,.1f}억원 (LCOE {f.V('lcoe_target')}원 역산, kW당 {f.asset.capex * 1e8 / (f.asset.mw * 1000) / 1e4:,.1f}만원)",
          f"- 금리 {f.rate * 100:.2f}% = 국고채 3년 {f.ktb * 100:.2f}% ({f.ktb_date}) + {f.V('margin_bp'):.0f}bp", ""]
    L += [markdown_table([{"경로": k, "대출(억원)": f"{x.debt:,.1f}", "대출 비율": _p(x.gearing), "최소 DSCR": f"{x.min_dscr:.3f}",
                           "지분(억원)": f"{x.equity:,.1f}", "지분 IRR": _p(x.irr, 2), "MOIC": f"{x.moic:.2f}",
                           f"{int(f.V('exit_year'))}년 매각 IRR": _p(f.exit[k][0], 2), "매각가(억원)": f"{f.exit[k][1]:,.1f}"} for k, x in f.base.items()]), ""]
    L += ["### 해지 확률별 필요 PPA 가격", "", markdown_table([{"연 해지": _p(p["hazard"]), "필요 가격": f"{p['price']:,.2f}", "프리미엄": f"{p['premium']:,.2f}",
                                                            "망이용료 상한": f"{p['max_fee']:,.2f}"} for p in f.premium]), ""]
    L += [f"- 해지 없음 IRR 손익분기 PPA 가격: {f.be_price:,.2f}원/kWh", ""]
    if ok(f.mc):
        L += ["### 몬테카를로", "", markdown_table([{"경로": k, **{a: _p(b) for a, b in mc_stats(f.mc[k], f.V('equity_hurdle')).items()}} for k in ("cfd", "ppa", "merchant")]), ""]
    L += ["### Vol.2 연결", "", f"- {r.get('vol2') or 'Vol.2 결과 없음'}", ""]
    L += ["## 한계 · 공식 원문 교체 대기 (공신력 원칙)", ""]
    for k in f.provisional:
        x = f.inputs[k]
        L.append(f"- [{TIER_KR[x.tier]}] {k} = {x.value} — {x.official_todo}")
    L += ["", "## 검산", ""]
    for k, x in f.base.items():
        gap = abs((x.revenue - (x.ebitda + x.revenue - x.ebitda)).sum())
        cf_chk = abs(float((x.cfads - (x.ebitda - x.tax)).sum()))
        L.append(f"- {k}: CFADS = EBITDA − 세금 오차 {cf_chk:.2e} · 대출 비율 ≤ 상한 {x.gearing <= f.debts[k].gearing + 1e-9} · 최소 DSCR ≥ 목표 {x.min_dscr >= f.debts[k].dscr - 1e-6} {gap:.0e}")
    if r.get("render_warnings"):
        L += ["", "## 렌더링 점검", ""] + [f"- {lg}: {w}" for lg, ws in r["render_warnings"].items() for w in ws] or ["- 없음"]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Note Vol.4 생성 (가로형 4:3)")
    p.add_argument("--asof", default=None)
    p.add_argument("--lang", choices=["kr", "en", "both"], default="both")
    p.add_argument("--mc", type=int, default=None, help="몬테카를로 반복 수 (기본: config)")
    p.add_argument("--no-figures", action="store_true")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    langs = ("kr", "en") if args.lang == "both" else (args.lang,)
    r = build(cfg, args.asof, langs, figures=not args.no_figures, mc_n=args.mc)
    print("\n=== KSJ Research Vol.4 빌드 결과 ===")
    print(f"폰트: {r['fonts']}")
    for lang, path in r["pdfs"].items():
        print(f"{path}  ({r['pages'][lang]}쪽)")
    for t in key_conclusions(r["facts"], float(cfg["research"]["vol04"]["monte_carlo"]["hazard"])):
        print(f"  · {t}")
    print(f"  공식 원문 교체 대기 {len(r['facts'].provisional)}개 → build_summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
