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
                         build_dir, st.footer(), cfg["research"].get("copyright", ""))
        path = out_dir / f"KSJ_Research_Vol02_{lang.upper()}.pdf"
        n = layout.render(path, ctx, pages, cover_bg, {
            "title": v["title_kr"] if lang == "kr" else v["title_en"], "author": cfg["research"]["author"],
            "subject": f"{cfg['research']['brand']} Research Note Vol.2"})
        result["pdfs"][lang], result["pages"][lang] = path, n
        result.setdefault("render_warnings", {})[lang] = list(ctx.warnings)
        result["pending"][lang] = [(pg.label, cell.title, cell.placeholder[0]) for pg in pages for cell in pg.cells if cell.placeholder]
        if lang == "kr":
            result["exec_lines"] = st.exec_conclusions()
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
        pair = a.power_pair()
        out.append(f"케이스 A 대출 한도 {a.base.debt:,.0f}억원(총사업비의 {a.base.gearing * 100:.0f}%, 구속 조건 {a.base.binding}, 이자유보계좌 {a.base.cons.reserve_initial:,.0f}억원 포함), "
                   f"최소 DSCR {a.base.min_dscr:.2f}배, Equity IRR {_f(a.base.equity_irr, 1, True)}(잔존가치 제외 {_f(a.base.equity_irr_ex_tv, 1, True)})"
                   + (f" — 전력비 부담 조항 하나로 Equity IRR {_f(pair[0].equity_irr, 1, True)}(별도 청구) vs {_f(pair[1].equity_irr, 1, True)}(전력 포함)" if pair else ""))
    elif g.ratio is not None:
        out.append(f"케이스 A: 계통 승인률 건수 {_f(g.ratio_n, 1, True)}·용량 {g.ratio * 100:.1f}%, 사전 임대율이 병목. 대출 한도는 가정 입력 후 산출")
    if ok(b):
        ms = b.margin_scenarios
        rng_ = (f" (가산금리 {min(ms):.0f}~{max(ms):.0f}bp: USD {ms[max(ms)].base.debt:,.0f}~{ms[min(ms)].base.debt:,.0f}mn)" if ms else "")
        ct = b.alts.get("contracted")
        out.append(f"케이스 B 대출 한도 USD {b.base.debt:,.0f}mn(총사업비의 {b.base.gearing * 100:.0f}%, {b.base.binding}){rng_}, "
                   f"최소 DSCR {b.base.min_dscr:.2f}배, Equity IRR {_f(b.base.equity_irr, 1, True)}(잔존가치 제외 {_f(b.base.equity_irr_ex_tv, 1, True)})"
                   + (f"; 계약 매출 sizing이면 USD {ct.debt:,.0f}mn" if ct is not None else ""))
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


CHECK_RANGES = {"yoc": (0.08, 0.14), "equity_irr": (0.10, 0.25)}   # 사용자 지정 점검 범위 (원가 대비 수익률, Equity IRR)
YOC_TOLERANCE = 0.01                                                 # 원가 대비 수익률 ±1%p 허용


def check_rows(f: data.Facts) -> list[dict]:
    """케이스·대안별 점검: 원가 대비 수익률 8~14%, Equity IRR 10~25%, 최소 DSCR ≥ 목표, 마이너스 상환 없음."""
    from src.analysis import pf_model as pf
    items = []
    a, b = f.cases.get("A"), f.cases.get("B")
    if ok(a):
        gross = a.inp.power_passthrough < 1
        items.append(("A 기준(전력 포함 임대, SPC 전력비 부담)" if gross else "A 기준(전력비 별도 청구)", a.base))
        for k, lab in (("passthrough", "A 전력비 별도 청구"), ("gross", "A 전력 포함 임대(스트레스, 재sizing)"),
                       ("power_cut", "A 전력 포함 + 단가 −10원(제안, 민감도)")):
            if k in a.alts:
                items.append((lab, a.alts[k]))
    if ok(b):
        items.append((f"B 기준(가산금리 {b.margin_bp:.0f}bp)" if b.margin_bp is not None else "B 기준", b.base))
        for m, x in (b.margin_scenarios or {}).items():
            if ok(x) and m != b.margin_bp:
                items.append((f"B 가산금리 {m:.0f}bp", x.base))
        if "contracted" in b.alts:
            items.append(("B 계약 매출 sizing", b.alts["contracted"]))
    rows = []
    for lab, r in items:
        y, e = pf.yield_on_cost(r), r.equity_irr
        neg = pf.negative_amortization_years(r)
        flags = []
        lo, hi = CHECK_RANGES["yoc"]
        if not lo - YOC_TOLERANCE <= y <= hi + YOC_TOLERANCE:
            flags.append(f"원가 대비 수익률 {y * 100:.1f}% (범위 {lo * 100:.0f}~{hi * 100:.0f}% ±1%p 밖)")
        lo, hi = CHECK_RANGES["equity_irr"]
        if e is None or not lo <= e <= hi:
            flags.append(f"Equity IRR {_f(e, 1, True)} (범위 {lo * 100:.0f}~{hi * 100:.0f}% 밖)")
        if r.min_dscr < r.inp.target_dscr - 1e-6:
            flags.append(f"최소 DSCR {r.min_dscr:.2f}배 < 목표 {r.inp.target_dscr:.2f}배")
        if neg:
            flags.append(f"마이너스 상환 {neg}년차")
        rows.append({"케이스": lab, "원가 대비 수익률": _f(y, 1, True), "Equity IRR": _f(e, 1, True),
                     "Project / Equity IRR (잔존가치 제외)": f"{_f(r.project_irr_ex_tv, 1, True)} / {_f(r.equity_irr_ex_tv, 1, True)}",
                     "최소 DSCR / 목표": f"{r.min_dscr:.2f} / {r.inp.target_dscr:.2f}", "마이너스 상환": "없음" if not neg else str(neg),
                     "대출 한도": f"{r.debt:,.0f}", "판정": "범위 내" if not flags else "⚠ " + "; ".join(flags)})
    return rows


def anomalies(f: data.Facts) -> list[str]:
    """PF 실무 상식에서 벗어나 보이는 숫자 (자동 점검)."""
    out = [f"{r['케이스']}: {r['판정'][2:]}" for r in check_rows(f) if r["판정"] != "범위 내"]
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
            out.append(f"A: 스트레스 {', '.join(neg)}에서 최소 DSCR 음수")
        short = {k: x.ops["shortfall"].sum() for k, x in a.stresses.items() if x.ops["shortfall"].sum() > 1e-6 and k != "power_gross"}
        if short:
            out.append("A: 대출 고정 스트레스에서 유보계좌·DSRA 소진 후 원리금 부족 — " + ", ".join(f"{k} {v:,.1f}억원" for k, v in short.items()))
        pg = a.stresses.get("power_gross")
        if pg is not None:
            out.append(f"A: 전력 포함 임대(SPC 부담) 스트레스(대출 고정) — 최소 DSCR {pg.min_dscr:.2f}배, 유보계좌·DSRA 이후 원리금 부족 {pg.ops['shortfall'].sum():,.1f}억원. "
                       "다시 sizing하면 범위 점검 표의 'A 전력 포함 임대' 행")
        if a.tax_timing:
            out.append(f"A: 토네이도 {', '.join(a.tax_timing)}의 유리한 쪽이 기준보다 낮음 — 세율 0 재계산 시 사라짐(이월결손금 소진 시점이 바뀌어 특정 연도 법인세 증가). "
                       "sculpting으로 기준 DSCR이 모든 상환 연도에서 같은 값(유효 DSCR)이라, 어느 해 CFADS가 조금만 줄어도 최소 DSCR이 내려간다")
        if a.inp.grace_interest == "reserve" and a.base.llcr < a.base.min_dscr - 1e-6:
            out.append(f"A: LLCR {a.base.llcr:.2f}배 < 최소 DSCR {a.base.min_dscr:.2f}배 — LLCR은 램프업 {a.inp.grace_years}년 CFADS 적자(유보계좌로 충당)까지 대출 기간 현재가치에 넣기 때문")
        rng = [k for k in ("prelease_low", "prelease_high") if k in a.stresses]
        if rng and all(abs(a.stresses[k].min_dscr - a.base.min_dscr) < 1e-6 for k in rng):
            pl = a.stresses.get("prelease_low")
            out.append(f"A: 사전 임대율 범위가 최소 DSCR에 영향 없음 — 램프업 {a.inp.grace_years}년(유보계좌 구간)에만 작용. 하단이면 유보계좌 인출 {pl.reserve_used:,.1f}억원"
                       f"/적립 {a.base.cons.reserve_initial:,.1f}억원, DSRA 이후 부족 {pl.grace_shortfall:,.1f}억원" if pl is not None else "")
    if ok(a) and ok(b) and fx:
        ka, kb = a.inp.capex_per_mw, b.inp.capex_per_mw * fx / 100
        if kb / ka > 1.8:
            out.append(f"MW당 CAPEX: A {ka:,.0f}억원 vs B {kb:,.0f}억원(USD {b.inp.capex_per_mw:.2f}mn × {fx:,.1f}) = {kb / ka:.1f}배 차이 — A 공사비의 용량 기준(IT·수전)·포함 범위 확인 필요")
    if ok(b):
        allin = b.inp.term_rate
        if b.base.project_irr is not None and b.base.project_irr < allin + 0.005:
            out.append(f"B: Project IRR {b.base.project_irr * 100:.1f}% ≈ 대출 금리 {allin * 100:.2f}% — 레버리지 효과 거의 없음(Equity IRR {b.base.equity_irr * 100:.1f}%)")
        if b.base.min_dscr_contracted < 1.1:
            out.append(f"B: 계약 임대료만의 최소 DSCR {b.base.min_dscr_contracted:.2f}배 (사전 임대율 {b.inp.prelease * 100:.0f}%, 임대 {b.inp.lease_term_years}년) — 계약 매출 sizing이면 "
                       + (f"USD {b.alts['contracted'].debt:,.0f}mn" if "contracted" in b.alts else "—"))
        r20 = next((x for k, x in b.stresses.items() if k.startswith("rent_-")), None)
        if r20 is not None and r20.min_dscr < 1.0:
            out.append(f"B: 임대료 −20% 스트레스 최소 DSCR {r20.min_dscr:.2f}배 < 1.0배")
        if b.cost_counterfactual is not None:
            from src.analysis import pf_model as pf
            s0, s1 = pf.yield_on_cost(b.cost_counterfactual) - allin, b.yoc - allin
            out.append(f"B: 원가 대비 수익률 − 대출금리 = {s1 * 100:.1f}%p(공사비 상승 전 {s0 * 100:.1f}%p)")
    from dataclasses import replace
    from src.analysis import pf_model as pf
    for c_ in ("A", "B"):                                  # 잔존가치 의존도: cap rate를 빼고 다시 계산
        x = f.cases.get(c_)
        if ok(x) and x.inp.exit_cap_rate:
            y = pf.run(replace(x.inp, exit_cap_rate=None))
            out.append(f"{c_}: 잔존가치(cap rate {x.inp.exit_cap_rate * 100:.1f}%, 저자 판단) 제외 시 Project IRR {_f(x.base.project_irr, 1, True)} → {_f(y.project_irr, 1, True)}, "
                       f"Equity IRR {_f(x.base.equity_irr, 1, True)} → {_f(y.equity_irr, 1, True)}")
    for c_ in ("A", "B"):
        x = f.cases.get(c_)
        if ok(x) and not x.inp.dep_years:
            out.append(f"{c_}: 감가상각 미반영(기간 null) → 법인세 과대·IRR 보수적")
    return [o for o in out if o]


def write_summary(path: Path, r: dict, as_of: str) -> None:
    f: data.Facts = r["facts"]
    L = ["# Vol.2 빌드 요약\n", f"- 기준일: {as_of} · 빌드(UTC): {utc_now_iso()}", f"- 폰트: {r['fonts']}",
         "- 가상 케이스(실존 프로젝트 아님). 교육·연구 목적, 투자 권유 아님", ""]
    L += ["## 핵심 결론", ""] + [f"{i}. {t}" for i, t in enumerate(key_conclusions(f), 1)] + [""]
    if r.get("exec_lines"):
        L += ["## Executive Summary 결론 문장 (국문 PDF와 같은 문장)", "", f"- 헤드라인: {r['exec_lines'][0]}"] \
             + [f"{i}. {t}" for i, t in enumerate(r["exec_lines"][1:], 1)] + [""]
    L += ["## 산출물", ""] + [f"- `{p.name}` — {r['pages'][lang]}쪽 (960×720pt, 4:3)" for lang, p in r["pdfs"].items()]
    rw = [f"{lang}: {w}" for lang, ws in r.get("render_warnings", {}).items() for w in ws]
    L += ["", "**렌더링 점검 (목차·바닥글·뒤표지 넘침)**: " + ("; ".join(rw) if rw else "이상 없음")]
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
        if b.cons.reserve_initial > 0:
            g_ = cr.inp.grace_years
            gap = float((b.ops["interest"][:g_] - b.ops["cfads"][:g_]).clip(lower=0).sum())
            L += [f"- 램프업 이자유보계좌: 거치 {g_}년 이자 부족분 {gap:,.1f} × (1 + {cr.inp.reserve_buffer:.0%}) = {b.cons.reserve_initial:,.1f} (인출 {b.reserve_used:,.1f}, "
                  f"램프업 최소 CFADS ÷ 이자 {b.min_icr_grace:.2f}배). 최소·평균 DSCR은 원금 상환 기간({g_ + 1}년차~) 기준"]
        if cr.alts or cr.cost_counterfactual is not None:
            from src.analysis import pf_model as pf
            names = {"passthrough": "전력비 별도 청구", "power_cut": "전력단가 −10원(제안)", "contracted": "계약 매출 sizing"}
            alt = [("기준", b)] + [(names.get(k, k), x) for k, x in cr.alts.items()]
            if cr.cost_counterfactual is not None:
                alt.append(("공사비 상승 전·임대료 1년 전", cr.cost_counterfactual))
            L += ["", "**대안 sizing·비교**", "",
                  markdown_table([{"구분": n, "대출 한도": f"{x.debt:,.1f}", "대출 비율": f"{x.gearing * 100:.1f}%", "구속": x.binding,
                                   "최소 DSCR": f"{x.min_dscr:.3f}", "계약분 최소 DSCR": f"{x.min_dscr_contracted:.3f}", "LLCR": f"{x.llcr:.3f}",
                                   "원가 대비 수익률": _f(pf.yield_on_cost(x), 2, True), "Project IRR": _f(x.project_irr, 2, True),
                                   "Equity IRR": _f(x.equity_irr, 2, True), "유보계좌": f"{x.cons.reserve_initial:,.1f}"} for n, x in alt])]
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
    # 최대 대출 비율 분모: 기준 vs 민감도(같은 엔진으로 재sizing)
    from src.analysis import pf_model as pf
    gname = {"capex": "CAPEX(금융비용 IDC·유보계좌·DSRA 제외)", "ex_financing": "CAPEX + 초기 DSRA", "total": "총사업비(+IDC·DSRA·유보계좌)"}
    L += ["", "## 최대 대출 비율 분모: 기준 vs 민감도 (기준은 config gearing_basis)", ""]
    gr = []
    for c, cr in f.cases.items():
        if not data.ok(cr) or not cr.gearing_alt:
            continue
        runs = [(cr.inp.gearing_basis, cr.base, cr.scenarios, "기준")] + [(g, x["base"], x["scenarios"], "민감도") for g, x in cr.gearing_alt.items()]
        for g, x, sc, tag in runs:
            gr.append({"케이스": c, "분모": f"{gname[g]} · {tag}", "대출": f"{x.debt:,.1f}", "구속 조건": x.binding,
                       "대출 ÷ 총사업비": f"{x.gearing * 100:.1f}%", "최소 DSCR": f"{x.min_dscr:.3f}",
                       "Equity IRR": f"{x.equity_irr * 100:.2f}%", "Project IRR": f"{x.project_irr * 100:.2f}%",
                       "시나리오별 대출(하단·기준·상단)": " · ".join(f"{y.debt:,.1f}" for y in sc.values())})
    L += [markdown_table(gr) if gr else "- 없음", ""]
    for c, cr in f.cases.items():
        if data.ok(cr) and cr.base.binding == "gearing":
            b = cr.base
            den = pf.gearing_base(cr.inp.gearing_basis, b.cons.uses, b.cons.capex, b.cons.dsra_initial)
            L.append(f"- 검산({c}): 대출 {b.debt:,.1f} = {cr.inp.max_gearing * 100:.0f}% × 분모 {den:,.1f}({gname[cr.inp.gearing_basis]}) = {cr.inp.max_gearing * den:,.1f}")
        if data.ok(cr) and cr.power_pair():
            pt, gr_ = cr.power_pair()
            L.append(f"- 전력비 조항({c}): 별도 청구 대출 {pt.debt:,.1f} · 최소 DSCR {pt.min_dscr:.3f} · Equity IRR {pt.equity_irr * 100:.2f}% / "
                     f"전력 포함 대출 {gr_.debt:,.1f} · 최소 DSCR {gr_.min_dscr:.3f} · Equity IRR {gr_.equity_irr * 100:.2f}% (구속 {gr_.binding})")
    # 범위 점검 + 점검 필요 수치
    L += ["", "## 범위 점검 (원가 대비 수익률 8~14% · Equity IRR 10~25% · 최소 DSCR ≥ 목표 · 마이너스 상환 없음)", "",
          markdown_table(check_rows(f))]
    L += ["", "## 점검 필요 수치 (PF 실무 상식 대비, 자동 점검)", ""] + ([f"- {x}" for x in anomalies(f)] or ["- 없음"])
    # 한계
    L += ["", "## 한계", "",
          "- 저자 판단 가정(감가상각 20년, PUE 1.3, IT 부하율 70%, cap rate A 7.0%·B 6.0%, 램프업 거치·유보계좌, 원가 대비 수익률 점검 범위 등)은 출처 없는 설정 — 민감도로 점검",
          "- 케이스 A 임대료의 전력 포함 여부는 원문에서 미확인 → 별도 청구(임차인 부담, 도매 임대 관행)를 기준, 전력 포함(SPC 부담)을 하방 시나리오로 병기",
          "- 가산금리(B)는 미확정 → 150/250/350bp 시나리오, 가운데 값을 대표로 표기. 옵션 할인율·대기 기간은 대표값 + 격자",
          "- 전력단가 인하 제안(수도권 북부 −10원/kWh)은 확정 전 → 민감도로만",
          "- 피어 이익률→가격은 상한값(인과 아님). 계통 승인 수치는 블록미디어 원문 확인 완료(2024.8~2026.3 수도권 1단계 신청 기준)"]
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
