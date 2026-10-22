"""KSJ Research Note Vol.2 생성 (가로형 4:3, Vol.1과 같은 레이아웃). 커밋된 data/ 파일과 config·가정 CSV만 읽는다.

    python -m research.vol02.build                    # 국문·영문 PDF + build_summary.md
    python -m research.vol02.build --lang kr
    python -m research.vol02.build --write-template   # data/manual/vol02_assumptions.csv 양식 생성·갱신 (입력값 보존)

산출물 (research/vol02/): KSJ_Research_Vol02_KR.pdf, KSJ_Research_Vol02_EN.pdf, build_summary.md
중간 산출물(차트 PNG)은 research/vol02/_build/ (git 제외).
가정이 null이면 그 계산만 건너뛰고 해당 Exhibit을 회색 박스 "입력·출처 확인 후 생성"으로 둔다.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys

import numpy as np
from pathlib import Path
from typing import Mapping

from research.vol01.fonts import register_matplotlib, register_reportlab, resolve_fonts
from src.data_fetch.base import load_config, markdown_table, resolve_path, setup_logging, utc_now_iso

from . import data
from .data import LABELS, ok

logger = logging.getLogger("research.vol02.build")


def build(cfg: Mapping, as_of: str | None = None, langs: tuple[str, ...] = ("kr", "en"), out_dir: Path | None = None) -> dict:
    from research.vol01 import layout   # matplotlib/ReportLab은 실행 시점에만 로드

    from . import charts, story

    v = cfg["research"]["vol02"]
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
        path = out_dir / f"KSJ_Research_Vol02_{lang.upper()}.pdf"
        n = layout.render(path, ctx, pages, cover_bg, {
            "title": v["title_kr"] if lang == "kr" else v["title_en"], "author": cfg["research"]["author"],
            "subject": f"{cfg['research']['brand']} Research Note Vol.2"})
        result["pdfs"][lang], result["pages"][lang] = path, n
        result["pending"][lang] = [(pg.label, cell.title, cell.placeholder[0]) for pg in pages for cell in pg.cells if cell.placeholder]
        if lang == "kr":
            result["page_titles"] = [(pg.label, pg.title) for pg in pages if pg.kind not in ("cover", "back")]
    write_summary(out_dir / "build_summary.md", result, facts.as_of)
    return result


def _f(x, d: int = 2, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:.{d}f}%" if pct else f"{x:,.{d}f}"


def key_conclusions(f: data.Facts) -> list[str]:
    """핵심 결론 3줄 (계산 결과로 생성). 모델 입력이 없으면 데이터로 확인되는 것만."""
    out = []
    a, b = f.cases.get("A"), f.cases.get("B")
    g = f.grid
    if ok(a):
        out.append(f"케이스 A 대출 한도 {a.base.debt:,.0f}억원(총사업비의 {a.base.gearing * 100:.0f}%, 구속 조건 {a.base.binding}), "
                   f"최소 DSCR {a.base.min_dscr:.2f}배, Equity IRR {_f(a.base.equity_irr, 1, True)}, 계약 임대료만으로는 최소 DSCR {a.base.min_dscr_contracted:.2f}배")
    elif g.ratio is not None:
        out.append(f"케이스 A: 계통 승인률 건수 {_f(g.ratio_n, 1, True)}·용량 {g.ratio * 100:.1f}%, 사전 임대율이 병목. 대출 한도는 가정 입력 후 산출")
    if ok(b):
        ms = b.margin_scenarios
        rng_ = (f" (가산금리 {min(ms):.0f}~{max(ms):.0f}bp: USD {ms[max(ms)].base.debt:,.0f}~{ms[min(ms)].base.debt:,.0f}mn)" if ms else "")
        out.append(f"케이스 B 대출 한도 USD {b.base.debt:,.0f}mn(총사업비의 {b.base.gearing * 100:.0f}%, {b.base.binding}){rng_}, "
                   f"최소 DSCR {b.base.min_dscr:.2f}배, Equity IRR {_f(b.base.equity_irr, 1, True)}")
    elif ok(f.rates):
        out.append(f"케이스 B: 기준금리 DGS10 {f.rates.dgs10:.2f}%. 대출 한도는 가정 입력 후 산출")
    op = f.option
    if ok(op):
        out.append(f"2단계 20MW 옵션 가치 {op.result.value:,.0f}억원(승인 확률 30%, 할인율 {op.inputs.phase2.discount_rate * 100:.0f}%·대기 {op.inputs.window_years}년) "
                   f"vs 지금 짓기 {op.result.build_now:,.0f}억원 — 승인 확률 10/50%면 {op.prob_values.get(0.1, float('nan')):,.0f}/{op.prob_values.get(0.5, float('nan')):,.0f}억원")
    elif ok(f.peers):
        sc = f.peers.scenarios()
        out.append(f"공사비 스트레스 근거: 피어 3사 함의 가격 상승률 {sc['low'] * 100:.1f}~{sc['high'] * 100:.1f}%(상한값, 인과 아님)")
    return out[:3]


def assumption_counts(f: data.Facts) -> dict[str, dict[str, int]]:
    """케이스별 근거 있음 / 저자 판단 / 미입력 / 기타 개수 (보고서 가정표와 같은 항목 기준)."""
    out = {}
    for c in data.CASES:
        d = f.assumptions[c]
        keys = data.table_keys(c, d)
        st = [d[k].status for k in keys]
        out[c] = {"근거 있음": st.count("sourced"), "저자 판단": st.count("judgment"), "미입력": st.count("input"),
                  "기타(설계값·원문 확인·데이터·중립)": len(st) - st.count("sourced") - st.count("judgment") - st.count("input")}
    return out


def anomalies(f: data.Facts) -> list[str]:
    """PF 실무 상식에서 벗어나 보이는 숫자 (자동 점검)."""
    out = []
    a, b = f.cases.get("A"), f.cases.get("B")
    fx = f.fx()
    if ok(a):
        if a.negative_amort:
            it1 = float(a.base.ops["interest"].iloc[0])
            out.append(f"A: {', '.join(map(str, a.negative_amort))}년차 원리금 < 이자(1년차 원리금 {a.base.ops['debt_service'].iloc[0]:,.1f} vs 이자 {it1:,.1f}억원) — "
                       f"음수 원금. 매년 이자 현금 지급 제약 시 한도 {a.interest_cover_debt:,.0f}억원(채택 {a.base.debt:,.0f}억원)")
        if a.base.binding == "gearing" and a.base.min_dscr > a.inp.target_dscr * 1.3:
            out.append(f"A: 최대 대출 비율이 묶여 최소 DSCR {a.base.min_dscr:.2f}배 = 목표 {a.inp.target_dscr:.2f}배의 {a.base.min_dscr / a.inp.target_dscr:.1f}배 (여유 큼)")
        neg = [k for k, x in a.stresses.items() if x.min_dscr < 0]
        if neg:
            out.append(f"A: 스트레스 {', '.join(neg)}에서 최소 DSCR 음수 — 램프업 1년차 CFADS 적자(1년차 원리금이 작아 비율이 크게 흔들림)")
    if ok(a) and ok(b) and fx:
        ka, kb = a.inp.capex_per_mw, b.inp.capex_per_mw * fx / 100
        if kb / ka > 1.8:
            out.append(f"MW당 CAPEX: A {ka:,.0f}억원 vs B {kb:,.0f}억원(USD {b.inp.capex_per_mw:.2f}mn × {fx:,.1f}) = {kb / ka:.1f}배 차이 — A 공사비의 용량 기준(IT·수전)·포함 범위 확인 필요")
        for c_, x in (("A", a), ("B", b)):
            st_i = int(np.ceil(x.inp.ramp_years or 0))
            y = float(x.base.ops["ebitda"].iloc[min(st_i, len(x.base.ops) - 1)]) / x.base.cons.uses
            out.append(f"{c_}: 안정화 EBITDA ÷ 총사업비(yield on cost) {y * 100:.1f}%")
    if ok(b):
        allin = b.inp.term_rate
        if b.base.project_irr is not None and b.base.project_irr < allin + 0.005:
            out.append(f"B: Project IRR {b.base.project_irr * 100:.1f}% ≈ 대출 금리 {allin * 100:.2f}% — 레버리지 효과 거의 없음(Equity IRR {b.base.equity_irr * 100:.1f}%)")
        out.append(f"B: 계약 임대료만의 최소 DSCR {b.base.min_dscr_contracted:.2f}배 (사전 임대율 {b.inp.prelease * 100:.0f}%, 임대 {b.inp.lease_term_years}년)")
    for c_ in ("A", "B"):
        x = f.cases.get(c_)
        if ok(x) and not x.inp.dep_years:
            out.append(f"{c_}: 감가상각 미반영(기간 null) → 법인세 과대·IRR 보수적")
    return out


PROPOSALS = [  # null 유지 항목의 저자 판단 제안값 (미반영 — 사용자 확인 후 CSV에 입력)
    ("A·B", "dep_years", "20년", "건물 40년(법인세법 시행규칙 별표5)·전기·기계설비 15년 내외 가중 — 비중 확인 필요"),
    ("A·B", "pue", "1.3", "신규 대형 데이터센터 설계값 범위의 중간 — 사업 계획 공시로 확인"),
    ("A·B", "it_load_factor", "70%", "임차 용량 대비 실사용 — 계약·운영 자료로 확인"),
    ("A", "exit_cap_rate", "7.0%", "국내 데이터센터 거래 cap rate 공개 사례 확인 필요"),
    ("B", "exit_cap_rate", "6.0%", "북미 데이터센터 거래 cap rate 보고서 확인 필요"),
]


def write_summary(path: Path, r: dict, as_of: str) -> None:
    f: data.Facts = r["facts"]
    L = ["# Vol.2 빌드 요약\n", f"- 기준일: {as_of} · 빌드(UTC): {utc_now_iso()}", f"- 폰트: {r['fonts']}",
         "- 가상 케이스(실존 프로젝트 아님). 교육·연구 목적, 투자 권유 아님", ""]
    L += ["## 핵심 결론", ""] + [f"{i}. {t}" for i, t in enumerate(key_conclusions(f), 1)] + [""]
    L += ["## 산출물", ""] + [f"- `{p.name}` — {r['pages'][lang]}쪽 (960×720pt, 4:3)" for lang, p in r["pdfs"].items()]
    L += ["", "## 페이지 제목 (국문)", ""] + [f"- **{lab}** {t}" for lab, t in r.get("page_titles", [])]
    pend = r["pending"].get("kr") or next(iter(r["pending"].values()), [])
    L += ["", "## 입력·출처 확인 후 생성되는 Exhibit", ""] + ([f"- p{lab}: {t} — {why}" for lab, t, why in pend] or ["- 없음"])
    # 데이터 연결
    L += ["", "## Vol.1 데이터 연결 (계산값)", ""]
    rows = []
    if ok(f.demand):
        for s in data.SCENARIOS:
            rows.append({"항목": f"수요 성장률 {s} ({f.demand.years[0]}→{f.demand.years[1]})", "값": _f(f.demand.growth[s], 2, True),
                         "근거": f"IEA {f.demand.values['base_year']:.0f}→{f.demand.values[s]:.0f} TWh"})
    if ok(f.rates):
        rr = f.rates
        rows += [{"항목": "국고채 3년 / 10년", "값": f"{rr.ktb_3y:.3f}% / {rr.ktb_10y:.3f}%", "근거": f"ECOS {rr.ktb_date}"},
                 {"항목": "DGS10", "값": f"{rr.dgs10:.2f}%", "근거": f"FRED {rr.dgs10_date}"},
                 {"항목": "원/달러", "값": f"{rr.usdkrw:,.1f}", "근거": f"ECOS {rr.fx_date}"}]
    if ok(f.peers):
        for _, x in f.peers.table.iterrows():
            rows.append({"항목": f"{x['company']} OPM {f.peers.fy0}→{f.peers.fy1}", "값": f"{x['opm0'] * 100:.2f}% → {x['opm1'] * 100:.2f}%",
                         "근거": f"함의 가격 상승률 {x['implied'] * 100:.2f}%"})
        rows.append({"항목": "3사 합산 OPM", "값": f"{f.peers.agg_opm0 * 100:.2f}% → {f.peers.agg_opm1 * 100:.2f}%",
                     "근거": f"함의 가격 상승률 {f.peers.agg_implied * 100:.2f}%"})
    if ok(f.va):
        y, p = f.va.price_latest
        my, mx = f.va.price_max_yoy
        rows += [{"항목": f"VA / US 상업용 판매 CAGR {f.va.base_year}→{f.va.last_year}", "값": f"{f.va.va_cagr * 100:.2f}% / {f.va.us_cagr * 100:.2f}%",
                  "근거": f"EIA ({f.va.sales_file})"},
                 {"항목": "버지니아 상업용 평균 요금 (케이스 B 전력 단가)", "값": f"{p:.2f}¢/kWh ({y})", "근거": "EIA vol02_eia_va_com.csv"},
                 {"항목": "버지니아 요금 최대 연간 상승", "값": f"{mx * 100:+.1f}% ({my})", "근거": "EIA (전력비 민감도)"}]
    g = f.grid
    if g.ratio is not None:
        if g.ratio_n is not None:
            rows.append({"항목": f"계통 승인률 건수 ({g.period})", "값": f"{g.approved_n:,.0f} ÷ {g.applied_n:,.0f} = {g.ratio_n * 100:.2f}%", "근거": g.basis_note})
        rows.append({"항목": f"계통 승인률 용량 ({g.period})", "값": f"{g.approved:,.0f} ÷ {g.applied:,.0f} = {g.ratio * 100:.2f}%",
                     "근거": f"{g.basis_note} — 건수·용량 두 기준 병기(1.9% vs 3.0%는 기준 차이, 불일치 아님)"})
    L += [markdown_table(rows)]
    # 케이스 결과
    for c in data.CASES:
        cr = f.cases.get(c)
        L += ["", f"## 케이스 {c} 결과", ""]
        if not ok(cr):
            L += [f"- 계산 보류: {cr.reason} — {data.fmt_missing(cr.missing)}"]
            continue
        b = cr.base
        s = b.summary()
        L += [markdown_table([{k: (_f(v, 4) if isinstance(v, float) else v) for k, v in s.items()}])]
        L += ["**검산 (회계 항등식, 0에 가까워야 함)**", "", markdown_table([{k: f"{v:.2e}" for k, v in cr.checks.items()}])]
        if b.warnings:
            L += ["**경고**", ""] + [f"- {w}" for w in b.warnings]
        if cr.margin_scenarios:
            L += ["", "**가산금리 시나리오 (가산금리 미확정)**", "",
                  markdown_table([{"가산금리(bp)": f"{m:.0f}", "대출 한도": f"{x.base.debt:,.1f}", "대출 비율": f"{x.base.gearing * 100:.1f}%",
                                   "구속": x.base.binding, "최소 DSCR": f"{x.base.min_dscr:.3f}", "평균 DSCR": f"{x.base.avg_dscr:.3f}",
                                   "LLCR": f"{x.base.llcr:.3f}", "Project IRR": _f(x.base.project_irr, 2, True), "Equity IRR": _f(x.base.equity_irr, 2, True)}
                                  for m, x in cr.margin_scenarios.items() if ok(x)])]
        if cr.negative_amort:
            L += [f"- 진단: 원리금 < 이자 연차 {cr.negative_amort} → 매년 이자 현금 지급 제약 시 한도 {cr.interest_cover_debt:,.1f}"]
    op = f.option
    L += ["", "## 실물옵션 (케이스 A 2단계)", ""]
    if ok(op):
        rr = op.result
        L += [f"- 대표 셀: 할인율 {op.inputs.phase2.discount_rate * 100:.0f}%, 대기 {op.inputs.window_years}년, 결정 시점 COD+{op.inputs.decision_year}년"
              + (" (램프업 종료로 도출)" if op.decision_derived else "")
              + (" — 할인율 미확정" if op.discount_pending else "") + (" — 대기 기간 미확정" if op.window_pending else ""),
              f"- 옵션 가치 {rr.value:,.2f} · 조건부 {rr.value_conditional:,.2f} (표준오차 {rr.stderr_conditional:,.2f}) · 지금 짓기 {rr.build_now:,.2f} · 유연성 {rr.flexibility:,.2f}",
              "- 승인 확률 시나리오: " + " · ".join(f"{p_ * 100:.0f}% → {v:,.1f}" for p_, v in op.prob_values.items()),
              "", "**할인율 × 대기 기간 격자 (억원, p = 30%)**", "", markdown_table(op.grid.round(3).to_dict("records")),
              "**수렴 (대표 셀)**", "", markdown_table(rr.convergence.round(4).to_dict("records"))]
    else:
        L += [f"- 계산 보류: {op.reason} — {data.fmt_missing(op.missing)}"]
    # 점검 필요 수치
    L += ["", "## 점검 필요 수치 (PF 실무 상식 대비, 자동 점검)", ""] + ([f"- {x}" for x in anomalies(f)] or ["- 없음"])
    # 한계
    L += ["", "## 한계", "", "- 미입력 가정: 감가상각 → 미반영(법인세 보수적), PUE·IT 부하율 → 전력비 순액 0(패스스루 100%), cap rate → 잔존가치 제외",
          "- 가산금리(B)·할인율·대기 기간(옵션)은 미확정 → 시나리오·격자로 계산, 가운데 값을 대표로 표기",
          "- 피어 이익률→가격은 상한값(인과 아님), 계통 승인 수치는 공개 보도 기준(원문 확인 필요)"]
    # 가정 집계
    L += ["", "## 가정 집계 (보고서 가정표 기준)", ""]
    cnt = assumption_counts(f)
    L += [markdown_table([{"케이스": c, **v} for c, v in cnt.items()])]
    for c in data.CASES:
        n = cnt[c]
        L += [f"- 케이스 {c}: 근거 있는 가정 {n['근거 있음']}개 / 저자 판단 {n['저자 판단']}개 / 미입력 {n['미입력']}개"]
    for c in data.CASES:
        d = f.assumptions[c]
        miss = [k for k in data.table_keys(c, d) if d[k].value is None]
        nosrc = [k for k in LABELS if k in d and d[k].origin == "csv" and not (d[k].source or d[k].url)]
        L += [f"- 케이스 {c} 미입력: {', '.join(miss) or '없음'}"]
        if nosrc:
            L += [f"  - 출처 미기재(CSV 값만 입력): {', '.join(nosrc)}"]
    L += ["", "**null 유지 항목의 저자 판단 제안값 (미반영)**", "",
          markdown_table([{"케이스": c, "항목": k, "제안": v, "근거·확인할 것": why} for c, k, v, why in PROPOSALS])]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Note Vol.2 생성 (가로형 4:3)")
    p.add_argument("--asof", default=None, help="금리·환율 기준일 (기본: config research.vol02.as_of)")
    p.add_argument("--lang", choices=["kr", "en", "both"], default="both")
    p.add_argument("--write-template", action="store_true", help="가정 입력 CSV 양식 생성·갱신 (입력값 보존)")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    if args.write_template:
        print(f"가정 입력 양식: {data.write_template(cfg)}")
        return 0
    langs = ("kr", "en") if args.lang == "both" else (args.lang,)
    r = build(cfg, args.asof, langs)
    print("\n=== KSJ Research Vol.2 빌드 결과 ===")
    print(f"폰트: {r['fonts']}")
    for lang, path in r["pdfs"].items():
        print(f"{path}  ({r['pages'][lang]}쪽)")
    for lab, t, why in next(iter(r["pending"].values()), []):
        print(f"  p{lab} 입력 후 생성: {t}  —  {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
