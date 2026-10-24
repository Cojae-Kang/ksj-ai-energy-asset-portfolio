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
    for label, key in (("3", "corridor"), ("5", "price_irr"), ("5", "tou")):
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
    out = [f"지분 IRR: 직접 PPA(회랑 중간 {f.ppa_mid:,.1f}원) {_p(irr['ppa'], 2)} · 한전 CfD {_p(irr['cfd'], 2)} · 시장 SMP {_p(irr['merchant'])}",
           f"필요 PPA 가격(연 해지 {hz * 100:.0f}%) {p['price']:,.1f}원/kWh = 한전 계약 +{p['premium']:,.1f}원 → 망이용료 여유 {p['max_fee']:+,.1f}원/kWh "
           f"(구매자 상한 = 태양광 시간대 회피 요금 {f.corridor[1]:,.1f}원 = 에너지요금 {f.extra['tou']['energy']:,.1f} + 추가 요금 {f.extra['tou']['adder']:,.1f}; 평균 판매단가 {f.extra['avg_tariff']:,.1f}원 기준이면 {p['max_fee_avg']:,.1f}원)"]
    if ok(f.mc):
        s, m = mc_stats(f.mc["ppa"], f.V("equity_hurdle")), mc_stats(f.mc["merchant"], f.V("equity_hurdle"))
        out.append(f"몬테카를로: 직접 PPA P10/P50 {_p(s['p10'])}/{_p(s['p50'])}, 시장 판매 손실 확률 {_p(m['neg'], 0)}")
    return out


def net_basis_lines(f: data.Facts) -> list[str]:
    """공개 사례 부대비용 비교 기준: 사례 성격·내역(반올림 차이) · 직접 PPA 사용자 부담 항목(B) · 기반기금 비대칭(요율 TODO면 문장만)."""
    n, t = f.extra["net"], f.extra["tou"]
    nb = n["basis"]
    nm = {"fuel": "연료비조정", "climate": "기후환경요금"}
    adds = [nm[k] for k, v in t["stages"] if k != "energy" and v is not None]
    items = " · ".join(f"{k} {v:g}" for k, v in n["items"])
    L = [f"- 공개 사례 부대비용 {n['total']:.0f}원(B) = {nb['case_kr']}({nb['conditions_kr']}) — {nb['table_ref_kr']}(2021-12): {items}"
         + (f" (표 총계 {n['total']:.0f} vs 항목 합 {n['item_sum']:.0f}, 원문 반올림)" if abs(n["item_sum"] - n["total"]) >= 0.5 else ""),
         f"- 같은 기준 비교: 직접 PPA 사용자 추가 부담 = {'·'.join(nb['direct_ppa_items_kr'])}"
         + (f", {'·'.join(adds)}은 해당 항목 아님({nb['direct_ppa_source_kr']}, B; 직접 PPA 고시 원문 TODO) → 상한 = 에너지요금 + 추가 요금 {t['adder']:,.1f}원" if adds
            else f"({nb['direct_ppa_source_kr']}, B; 직접 PPA 고시 원문 TODO)")]
    if n["fund"] is not None:
        L.append(f"- 기반기금 비대칭: 사례 {n['total']:.0f}원에 전력산업기반기금 {n['fund']:g}원 포함, 회피 요금에는 미포함 → "
                 + ("기준을 맞추면 여유가 기반기금만큼 커짐 (요율 TODO(data): 입력 power_fund_rate 비어 있음, 추정하지 않음)" if n["fund_add"] is None
                    else f"요율 {n['fund_rate']:g}% 포함 시 상한 {t['annual'] + n['fund_add']:,.2f}원(여유 +{n['fund_add']:,.2f})"))
    return L


def tou_section(f: data.Facts) -> list[str]:
    """구매자 상한(태양광 시간대 회피 전력량요금) 근거표."""
    from .tou import BAND_KR, SEASON_KR
    t = f.extra["tou"]
    b = t["base"]
    v, o = t["contract"]
    L = ["### 구매자 상한: 태양광 시간대 회피 전력량요금", "",
         f"- 요금: 기후에너지환경부·한전 보도참고자료(2026-03-13) PDF 8쪽 [붙임2] 산업용(을) {v} {o} 개편 후 전력량요금 (data/processed/vol04_tou_tariff.csv)",
         "- 월 가중치: 한전 전력통계월보 제566호 시트 '16-1.태양광 발전량 추계정보' 2025년 월별(시장+한전PPA+자가용)",
         "- 요일: 2025년 달력. 평일 = 시간대 구분표, 일요일 = 전 시간 경부하, 토요일 = 평일 시간대(J), 봄·가을 토·일 11~14시 50% 할인. 평일 공휴일 미반영(TODO)",
         "- 하루 형상: max(cos 천정각, 0)^p (Spencer 1971, 북위 36°·동경 127°) — 저자 판단(J)",
         f"- kWh당 추가 요금: 연료비조정 = 입력 fuel_adj {f.inputs['fuel_adj'].value}원(B, 보도) · 기후환경 = 입력 climate_env "
         + (f"{f.inputs['climate_env'].value}원(A, 한전ON {f.inputs['climate_env'].published} 적용)" if isinstance(f.inputs['climate_env'].value, (int, float)) else "(원문 대기 → 미포함, TODO)"),
         *net_basis_lines(f), ""]
    # 3단 상한 × 단계별 망이용료 여유 (스프레드 0, 해지 확률별)
    nm = {"energy": "① 에너지요금만", "fuel": "② + 연료비조정", "climate": "③ + 기후환경"}
    L += ["#### 구매자 상한 3단과 망이용료 여유 (위험 스프레드 0)", "",
          markdown_table([{"단계": nm[k], "상한(원/kWh)": f"{v:,.2f}" if v is not None else "TODO(data)",
                           **{f"여유 @해지 {p['hazard'] * 100:.1f}%": (f"{p['max_fee_stage'][k]:+,.2f}" if p['max_fee_stage'][k] is not None else "TODO") for p in f.premium}}
                          for k, v in t["stages"]]), "",
          f"- 보고서 상한 = {t['annual']:,.2f}원 (에너지 {t['energy']:,.2f} + 추가 요금 {t['adder']:,.2f}), 아래 계절·월별 표는 에너지요금만", ""]
    L += [markdown_table([{"계절": SEASON_KR[k], "회피 요금(원/kWh)": f"{b['season'][k]:,.2f}", "발전량 비중": f"{b['gen_share'][k] * 100:.1f}%",
                           "한전 계약가 대비": f"{b['season'][k] - f.corridor[0]:+,.2f}",
                           **{f"평일 {BAND_KR[x]} 비중": f"{t['band_share'][k][x] * 100:.1f}%" for x in ("off", "mid", "peak")}}
                          for k in ("spring_autumn", "summer", "winter")]
                         + [{"계절": "연간(발전량 가중)", "회피 요금(원/kWh)": f"{t['annual']:,.2f}", "발전량 비중": "100.0%",
                             "한전 계약가 대비": f"{t['annual'] - f.corridor[0]:+,.2f}"}]), ""]
    L += ["월별(원/kWh): " + " · ".join(f"{m}월 {x:,.1f}" for m, x in b["month"].items()), ""]
    lab = {"opt1": "고압A 선택Ⅰ", "opt3": "고압A 선택Ⅲ", "hvb": "고압B 선택Ⅱ", "sat_mid": "토요일 최대→중간부하",
           "no_discount": "봄·가을 주말 할인 종료(2031~)", "before": "개편 전 요금(참고)"}
    p1 = f.premium[[q['hazard'] for q in f.premium].index(0.01)]['price']
    ad = t["adder"]
    L += [f"민감도 (에너지요금 기준값 → 추가 요금 {ad:,.2f}원 포함 상한, 여유 = 상한 − 필요 PPA {p1:,.2f}원):", "",
          markdown_table([{"민감도": f"형상 p = {p:g}", "에너지요금": f"{x:,.2f}", "상한(추가 요금 포함)": f"{x + ad:,.2f}", "여유(연 해지 1%·스프레드 0)": f"{x + ad - p1:+,.2f}"}
                          for p, x in t["shape"].items()]
                         + [{"민감도": lab.get(k, k), "에너지요금": f"{x:,.2f}", "상한(추가 요금 포함)": f"{x + ad:,.2f}", "여유(연 해지 1%·스프레드 0)": f"{x + ad - p1:+,.2f}"}
                            for k, x in t["sens"].items()]
                         + ([{"민감도": "회피 요금에 기반기금 포함", "에너지요금": f"{t['energy']:,.2f}",
                              "상한(추가 요금 포함)": f"{t['annual'] + fa:,.2f}" if (fa := f.extra["net"]["fund_add"]) is not None else "TODO(data)",
                              "여유(연 해지 1%·스프레드 0)": f"{t['annual'] + fa - p1:+,.2f}" if fa is not None else "TODO(data)"}]
                            if f.extra["net"]["fund"] is not None else [])), ""]
    return L


def write_summary(path: Path, r: dict, cfg: Mapping) -> None:
    f: data.Facts = r["facts"]
    hz = float(cfg["research"]["vol04"]["monte_carlo"]["hazard"])
    L = ["# Vol.4 빌드 요약\n", f"- 기준일: {f.as_of} · 빌드(UTC): {utc_now_iso()}", f"- 폰트: {r['fonts']}",
         "- 발전자산·오프테이커는 가상 사례. 교육·연구 목적, 투자 권유 아님", ""]
    L += ["## 핵심 결론 3줄", ""] + [f"{i}. {t}" for i, t in enumerate(key_conclusions(f, hz), 1)] + [""]
    if r.get("exec_lines"):
        L += ["## Executive Summary 결론 문장 (국문 PDF와 같은 문장)", "", f"- 헤드라인: {r['exec_lines'][0]}"] \
             + [f"{i}. {t}" for i, t in enumerate(r["exec_lines"][1:], 1)] + [""]
    lc = f.lcoe_check
    L += ["## 근거", "", f"- 사업비 {f.asset.capex:,.1f}억원 (KEEI LCOE {f.V('lcoe_target')}원·WACC {f.V('lcoe_discount_rate') * 100:.0f}%·이용률 {f.asset.capacity_factor * 100:.0f}%에 맞춤, kW당 {f.asset.capex * 100 / f.asset.mw:,.0f}천원)",
          f"- 교차 확인: 2022년 실제 설치비 {f.V('capex_per_kw'):,.0f}천원/kW → 사업비 {lc['actual_capex']:,.0f}억원 · LCOE {lc['actual_lcoe']:.1f}원 (KEEI 범위 {lc['keei'][0]:.0f}~{lc['keei'][1]:.0f}원) · "
          f"이 경우 지분 IRR CfD {_p(lc['actual_irr']['cfd'])} · PPA {_p(lc['actual_irr']['ppa'])} · 시장 {_p(lc['actual_irr']['merchant'])}",
          f"- 금리 {f.rate * 100:.2f}% = 국고채 3년 {f.ktb * 100:.2f}% ({f.ktb_date}) + {f.V('margin_bp'):.0f}bp", ""]
    L += [markdown_table([{"경로": k, "대출(억원)": f"{x.debt:,.1f}", "대출 비율": _p(x.gearing), "최소 DSCR": f"{x.min_dscr:.3f}",
                           "지분(억원)": f"{x.equity:,.1f}", "지분 IRR": _p(x.irr, 2), "MOIC": f"{x.moic:.2f}",
                           f"{int(f.V('exit_year'))}년 매각 IRR": _p(f.exit[k][0], 2), "매각가(억원)": f"{f.exit[k][1]:,.1f}"} for k, x in f.base.items()]), ""]
    L += ["### 해지 확률별 필요 PPA 가격", "", markdown_table([{"연 해지": _p(p["hazard"]), "필요 가격": f"{p['price']:,.2f}", "프리미엄": f"{p['premium']:,.2f}",
                                                            "망이용료 여유": f"{p['max_fee']:,.2f}", "여유(평균 판매단가 기준, 참고)": f"{p['max_fee_avg']:,.2f}"} for p in f.premium]), ""]
    L += [f"- 해지 없음 IRR 손익분기 PPA 가격: {f.be_price:,.2f}원/kWh", ""]
    L += tou_section(f)
    if ok(f.mc):
        L += ["### 몬테카를로", "", markdown_table([{"경로": k, **{a: _p(b) for a, b in mc_stats(f.mc[k], f.V('equity_hurdle')).items()}} for k in ("cfd", "ppa", "merchant")]), ""]
    v2 = r.get("vol2") or {}
    L += ["### Vol.2 연결", "", (f"- 데이터센터 SPV 최소 DSCR {v2['min_dscr']:.2f}배 · 지분 IRR {v2['equity_irr'] * 100:.1f}%" if v2 else "- Vol.2 결과 없음"), ""]
    L += ["### 위험 스프레드 격자 (PPA 할인율 = 요구수익률 + 스프레드)", "",
          markdown_table([{"연 해지": _p(p["hazard"]), "스프레드": _p(p["spread"], 0), "필요 가격": f"{p['price']:,.2f}", "프리미엄": f"{p['premium']:,.2f}",
                           "망이용료 여유": f"{p['max_fee']:,.2f}"} for p in f.extra.get("premium_grid", [])]), "",
          f"- PPA 대출 비율별 프리미엄(연 해지 {hz * 100:.0f}%, 스프레드 0): " + ", ".join(f"{g * 100:.0f}% → {v:,.2f}원" for g, v in f.extra.get("gearing_check", {}).items()),
          f"- 하방: 1년 차 해지 후 최소 DSCR {f.extra['downside']['base']:.3f} (SMP 기준) · {f.extra['downside']['low']:.3f} (SMP {f.extra['downside']['low_smp']})", ""]
    L += ["## 한계 · 공식 원문 교체 대기 (공신력 원칙)", ""]
    for k in f.provisional:
        x = f.inputs[k]
        L.append(f"- [{TIER_KR[x.tier]}] {k} = {x.value if x.value != '' else '(비어 있음)'} — {x.official_todo}")
    L += ["", "## 검산", ""]
    for k, x in f.base.items():
        cf_chk = abs(float((x.cfads - (x.ebitda - x.tax)).sum()))
        rev_chk = abs(float((x.revenue - x.gen * x.price / 100).sum()))
        L.append(f"- {k}: 매출 = 발전량 × 가격 오차 {rev_chk:.1e} · CFADS = EBITDA − 세금 오차 {cf_chk:.1e} · 대출 비율 ≤ 상한 {x.gearing <= f.debts[k].gearing + 1e-9} · "
                 f"최소 DSCR ≥ 목표 {x.min_dscr >= f.debts[k].dscr - 1e-6}")
    warns = [f"- {lg}: {w}" for lg, ws in (r.get("render_warnings") or {}).items() for w in ws]
    L += ["", "## 렌더링 점검", ""] + (warns or ["- 없음"])
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
