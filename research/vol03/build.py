"""KSJ Research Note Vol.3 생성 (가로형 4:3, Vol.1·Vol.2와 같은 레이아웃). 커밋된 data/ 파일과 config·가정 CSV만 읽는다.

    python -m research.vol03.build                    # 국문·영문 PDF + build_summary.md + figures/vol03_*.png·pdf
    python -m research.vol03.build --lang kr
    python -m research.vol03.build --write-template   # data/manual/vol03_assumptions.csv 양식 생성·갱신 (입력값 보존)

산출물 (research/vol03/): KSJ_Research_Vol03_KR.pdf, KSJ_Research_Vol03_EN.pdf, build_summary.md
중간 산출물(차트 PNG)은 research/vol03/_build/ (git 제외). 데이터가 없는 Exhibit은 회색 박스로 두고 요약에 남긴다.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path
from typing import Mapping

import numpy as np

from research.vol01.fonts import register_matplotlib, register_reportlab, resolve_fonts
from src.analysis import ipo_model as im
from src.data_fetch.base import load_config, markdown_table, resolve_path, setup_logging, utc_now_iso

from . import data
from .data import LABELS, SCEN, ok

logger = logging.getLogger("research.vol03.build")


def build(cfg: Mapping, as_of: str | None = None, langs: tuple[str, ...] = ("kr", "en"), out_dir: Path | None = None,
          figures: bool = True) -> dict:
    from research.vol01 import layout   # matplotlib/ReportLab은 실행 시점에만 로드

    from . import charts, story

    v = cfg["research"]["vol03"]
    default_out = resolve_path(v["output_dir"])
    out_dir = out_dir or default_out
    build_dir = resolve_path(v["build_dir"]) if out_dir == default_out else out_dir / "_build"
    fonts = resolve_fonts(cfg)
    register_matplotlib(fonts)
    register_reportlab(fonts)
    facts = data.load_facts(cfg, as_of)
    w, h = (float(x) for x in v["page_pt"])
    cover_bg = charts.cover_background(build_dir / "cover_bg.png", w, h, cfg["research"]["colors"])
    result = {"pdfs": {}, "pages": {}, "fonts": fonts.label, "facts": facts, "pending": {}, "figures": []}
    for lang in langs:
        st = story.Story(cfg, facts, lang)
        pages = st.pages()
        ctx = layout.Ctx(cfg["research"]["colors"], w, h, lang, cfg["research"]["brand"], st.sources(), st.labels(),
                         build_dir, st.footer(), cfg["research"].get("copyright", ""))
        path = out_dir / f"KSJ_Research_Vol03_{lang.upper()}.pdf"
        n = layout.render(path, ctx, pages, cover_bg, {
            "title": v["title_kr"] if lang == "kr" else v["title_en"], "author": cfg["research"]["author"],
            "subject": f"{cfg['research']['brand']} Research Note Vol.3"})
        result["pdfs"][lang], result["pages"][lang] = path, n
        result.setdefault("render_warnings", {})[lang] = list(ctx.warnings)
        result["pending"][lang] = [(pg.label, cell.title, cell.placeholder[0]) for pg in pages for cell in pg.cells if cell.placeholder]
        if lang == "kr":
            result["exec_lines"] = st.exec_conclusions()
            result["page_titles"] = [(pg.label, pg.title) for pg in pages if pg.kind not in ("cover", "back")]
        if figures and out_dir == default_out:
            result["figures"] += export_figures(cfg, st, pages, lang)
    write_summary(out_dir / "build_summary.md", result, facts.as_of, cfg)
    return result


def export_figures(cfg: Mapping, st, pages, lang: str) -> list[Path]:
    """핵심 Exhibit 2개(p6 할인율별 공모가, p7 1년 후 주당가치 분포)를 figures/에 PNG(200dpi) + PDF로."""
    from . import charts
    out = []
    fig_dir = resolve_path(cfg["paths"]["figures"])
    dpi = int(cfg["figures"]["dpi"])
    by = {p.label: p for p in pages}
    for label, key in (("6", "ladder"), ("7", "hist")):
        cell = next((c_ for c_ in by[label].cells if c_.chart_key == key), None)
        if cell is None or cell.chart is None:
            continue
        foot = st.T("출처: ", "Source: ") + " · ".join(st.sources()[k] for k in cell.src if k != "ksj") + " · KSJ Research " + st.T("계산", "calculation")
        out += charts.export_figure(cell.chart, fig_dir / f"vol03_p{label}_{key}_{lang}", cell.title, cell.unit, foot,
                                    cfg["research"]["colors"], dpi=dpi)
    return out


def _f(x, d: int = 2, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:.{d}f}%" if pct else f"{x:,.{d}f}"


def key_conclusions(f: data.Facts) -> list[str]:
    """핵심 결론 3줄 (계산 결과로 생성)."""
    out = []
    if ok(f.mult):
        mu = f.mult
        g = mu.groups["domestic"]["current"]
        out.append(f"적용 PER {mu.applied('current'):.1f}배({'국내 ' + str(g.n) + '사, 해외 시총 수집 전' if mu.applied_group == 'domestic' else '국내·해외 핵심 평균'}) — "
                   f"정상화 {mu.applied('normalized'):.1f}배(로그 중간), 보수 {mu.applied('conservative'):.1f}배(2023년 초)")
    if ok(f.val) and ok(f.band):
        v, b = f.val, f.band
        out.append(f"Target Co. 주당 평가가액 {v.per_share['current']:,.0f}원 → 희망공모가 {b.low:,.0f}~{b.high:,.0f}원(할인율 {b.d_low * 100:.1f}~{b.d_high * 100:.1f}%, "
                   f"{'몬테카를로 분위' if b.basis == 'mc' else '할인율 사례'} 기준), 공모금액 {v.shares.offered * b.low / 1e8:,.0f}~{v.shares.offered * b.high / 1e8:,.0f}억원")
    if ok(f.mc):
        mc = f.mc
        out.append(f"1년 후 주당가치 P10/P50/P90 {mc.result.q(0.1):,.0f}/{mc.result.q(0.5):,.0f}/{mc.result.q(0.9):,.0f}원 — 사이클 고점 위험을 덮는 할인율 "
                   f"{mc.required[0.5] * 100:.1f}%(P50)~{mc.required[0.25] * 100:.1f}%(P25), P10까지면 {mc.required[0.1] * 100:.1f}%")
    return out[:3]


def checks(f: data.Facts, cfg: Mapping) -> list[dict]:
    """검산: 배수 재계산, 단위(억원→원), 환율 환산, 공모 구조 항등식, 몬테카를로 재현."""
    rows = []
    if ok(f.peers):
        t = f.peers.table
        for _, r in t[t["status"] == "applied"].iterrows():
            rows.append({"검산": f"{r['company']} PER = 시총 ÷ 지배순이익", "계산": f"{r['mcap1']:,.1f} ÷ {r['ni1']:,.1f} = {r['mcap1'] / r['ni1']:.4f}",
                         "보고서 값": f"{r['per1']:.4f}", "차이": f"{abs(r['mcap1'] / r['ni1'] - r['per1']):.1e}"})
    if ok(f.mult):
        mu = f.mult
        g = mu.groups["domestic"]["current"]
        t = f.peers.table
        a = t[(t["group"] == "domestic") & (t["status"] == "applied")]
        agg = a["mcap1"].sum() / a["ni1"].sum()
        rows.append({"검산": "국내 합산 PER = Σ시총 ÷ Σ지배순이익", "계산": f"{a['mcap1'].sum():,.0f} ÷ {a['ni1'].sum():,.0f} = {agg:.4f}",
                     "보고서 값": f"{g.aggregate:.4f}", "차이": f"{abs(agg - g.aggregate):.1e}"})
        if f.links.per1 is not None:
            rows.append({"검산": "Vol.1 3사 합산 PER과 일치", "계산": f"Vol.1 {f.links.per0:.4f} → {f.links.per1:.4f}",
                         "보고서 값": f"{mu.scen['domestic']['conservative']:.4f} → {mu.scen['domestic']['current']:.4f}",
                         "차이": f"{abs(f.links.per1 - mu.scen['domestic']['current']):.1e}"})
        groups = [g_ for g_ in ("domestic", "core") if mu.groups[g_]["current"].n and mu.groups[g_]["start"].n]
        for g_ in groups:
            sc = mu.scen[g_]
            nm = math.sqrt(sc["current"] * sc["conservative"])
            rows.append({"검산": f"정상화({g_}) = √(현재 × 보수)", "계산": f"√({sc['current']:.3f} × {sc['conservative']:.3f}) = {nm:.4f}",
                         "보고서 값": f"{sc['normalized']:.4f}", "차이": f"{abs(nm - sc['normalized']):.1e}"})
        if mu.applied_group == "combined":
            for s_ in SCEN:
                m_ = sum(mu.scen[g_][s_] for g_ in groups) / len(groups)
                rows.append({"검산": f"적용 {s_} = 그룹 배수 단순평균", "계산": " + ".join(f"{mu.scen[g_][s_]:.3f}" for g_ in groups) + f" ÷ {len(groups)} = {m_:.4f}",
                             "보고서 값": f"{mu.applied(s_):.4f}", "차이": f"{abs(m_ - mu.applied(s_)):.1e}"})
    if ok(f.val):
        v, sh = f.val, f.val.shares
        eq = v.ni * f.mult.applied("current")
        ps = eq * 1e8 / sh.post
        rows.append({"검산": "주당 평가가액 = 지배순이익 × PER(억원) × 1억 ÷ 공모 후 주식수", "계산": f"{v.ni:,.2f} × {f.mult.applied('current'):.4f} × 1e8 ÷ {sh.post:,.0f} = {ps:,.2f}",
                     "보고서 값": f"{v.per_share['current']:,.2f}", "차이": f"{abs(ps - v.per_share['current']):.1e}"})
        rows.append({"검산": "공모 후 = 상장 전 + 신주, 공모 = 공모 비율 × 공모 후",
                     "계산": f"{sh.pre:,.0f} + {sh.new:,.0f} = {sh.pre + sh.new:,.0f}; {f.assumptions['offer_ratio'].value} × {sh.post:,.0f} = {f.assumptions['offer_ratio'].value * sh.post:,.0f}",
                     "보고서 값": f"{sh.post:,.0f}; {sh.offered:,.0f}", "차이": f"{abs(sh.pre + sh.new - sh.post) + abs(f.assumptions['offer_ratio'].value * sh.post - sh.offered):.1e}"})
    if ok(f.band) and ok(f.val):
        b, v0 = f.band, f.val.per_share["current"]
        rows.append({"검산": "밴드 할인율 = 1 − 가격 ÷ 평가가액", "계산": f"1 − {b.high:,.0f} ÷ {v0:,.0f} = {1 - b.high / v0:.4f}; 1 − {b.low:,.0f} ÷ {v0:,.0f} = {1 - b.low / v0:.4f}",
                     "보고서 값": f"{b.d_low:.4f}; {b.d_high:.4f}", "차이": f"{abs(1 - b.high / v0 - b.d_low) + abs(1 - b.low / v0 - b.d_high):.1e}"})
    if ok(f.mc) and ok(f.val):
        mc = f.mc
        r2 = im.monte_carlo(f.val.ni, f.val.shares.post, mc.mu, mc.sd, mc.per_tri, mc.n, mc.seed)
        rows.append({"검산": f"몬테카를로 재현 (seed {mc.seed})", "계산": f"P50 재실행 {r2.q(0.5):,.4f}", "보고서 값": f"{mc.result.q(0.5):,.4f}",
                     "차이": f"{abs(r2.q(0.5) - mc.result.q(0.5)):.1e}"})
    if f.fx and ok(f.peers):
        t = f.peers.table
        us = t[(t["region"] == "US") & t["mcap1"].notna()]
        for _, r in us.head(1).iterrows():
            rows.append({"검산": f"원화 환산 {r['company']} = USD mn × 원/달러 ÷ 100", "계산": f"{r['mcap1']:,.1f} × {f.fx:,.1f} ÷ 100 = {r['mcap1'] * f.fx / 100:,.0f}억원",
                         "보고서 값": "p3 표", "차이": "—"})
    return rows


def anomalies(f: data.Facts, cfg: Mapping) -> list[str]:
    """ECM 실무 상식에서 벗어나 보이는 숫자 (자동 점검)."""
    out = []
    grid = cfg["research"]["vol03"]["discount_grid"]
    if ok(f.peers):
        t = f.peers.table
        for _, r in t[t["high_flag"]].iterrows():
            med = f.mult.groups[r["group"]]["current"].median if ok(f.mult) else float("nan")
            out.append(f"{r['company']} PER {r['per1']:.1f}배 = 그룹 중앙값({med:.1f}배)의 {r['per1'] / med:.1f}배 — 지배순이익률 {r['ni1'] / r['rev1'] * 100:.1f}%로 피어 최저, 시총은 최대(R4 표시·포함)")
        for _, r in t[t["step2"] == "R2"].iterrows():
            out.append(f"{r['company']} PER {r['per1']:.0f}배 (FY2025A 지배순이익 {r['ni1']:,.0f}{'억원' if r['region'] == 'KR' else ' USD mn'}) — 분모 왜곡, R2로 제외")
        us = t[t["region"] == "US"]
        for _, r in us.iterrows():
            if np.isfinite(r["net_debt1"]) and np.isfinite(r["rev1"]) and r["net_debt1"] / r["rev1"] > 0.75:
                out.append(f"{r['company']} 순차입금 ÷ 매출 {r['net_debt1'] / r['rev1'] * 100:.0f}% (FY2025A) — 발전·유틸리티의 자산·차입 구조, 핵심 비교군에서 분리")
            if np.isfinite(r["net_debt1"]) and r["net_debt1"] < 0:
                out.append(f"{r['company']} 순현금 {(-r['net_debt1']):,.0f} USD mn (총차입금이 단기차입금 태그만 잡힘 — 장기차입금 태그 미보고 가능성, 10-K 주석 확인 필요)")
            if np.isfinite(r["ni1"]) and np.isfinite(r["oi1"]) and r["ni1"] > r["oi1"] * 1.5 and r["oi1"] > 0:
                out.append(f"{r['company']} FY2025A 순이익 {r['ni1']:,.0f} > 영업이익 {r['oi1']:,.0f} USD mn ({r['ni1'] / r['oi1']:.1f}배) — 영업외 이익(일회성) 가능성, PER 분모 과대 → 배수 과소")
        if f.peers.ev_basis == "EBIT":
            out.append("EV 배수는 D&A 미수집으로 EV/EBIT 대용 — EV/EBITDA보다 높게 나온다")
    if ok(f.val) and f.val.ev_per_share:
        d = f.val.ev_per_share / f.val.per_share["current"] - 1
        if abs(d) > 0.2:
            out.append(f"EV/{f.peers.ev_basis} 기준 주당가치 {f.val.ev_per_share:,.0f}원 = PER 기준의 {d * 100:+.0f}% — 피어 영업이익률(합산 {f.assumptions['opm'].value * 100:.1f}%)과 순이익률({f.assumptions['npm'].value * 100:.1f}%)의 간극이 Target에 그대로 이전")
    if ok(f.mc):
        mc = f.mc
        if mc.required[0.1] > grid[-1]:
            out.append(f"P10 기준 필요 할인율 {mc.required[0.1] * 100:.0f}% > 할인율 시나리오 상단 {grid[-1] * 100:.0f}% — 국내 IPO 통상 범위를 넘는 하방")
        if mc.loss_grid[grid[0]] > 0.6:
            out.append(f"할인율 {grid[0] * 100:.0f}%로 공모 시 1년 후 손실 확률 {mc.loss_grid[grid[0]] * 100:.0f}% — 현재 배수가 정점이라는 시나리오 가정의 결과")
        if not mc.result.converged:
            out.append("몬테카를로 미수렴 — 시뮬레이션 수 확대 필요")
    if f.der and f.der.hist:
        y0, y1 = min(f.der.hist), max(f.der.hist)
        r = f.der.hist[y0]["npm"] / f.der.hist[y1]["npm"]
        out.append(f"3사 합산 순이익률 FY{y0}A {f.der.hist[y0]['npm'] * 100:.1f}% → FY{y1}A {f.der.hist[y1]['npm'] * 100:.1f}% (FY{y0}A 이익률이면 평가가액 {r * 100:.0f}%) — 이익률 정점 위험은 할인율 밖")
    if ok(f.mult) and f.mult.applied_group == "domestic":
        out.append("적용 배수가 국내 3사만 — 미국 핵심 비교군 시총 미수집(TODO(data))")
    return out


def todo_items(f: data.Facts, cfg: Mapping) -> list[str]:
    """출처를 채워야 할 가정·데이터 목록."""
    out = []
    for k, a in f.assumptions.items():
        p = cfg["research"]["vol03"]["params"][a.case][k]
        if a.value is None:
            out.append(f"[{a.case}] {k} ({LABELS.get(k, (k,))[0]}): {p.get('todo') or '미입력'}")
        elif a.status == "verify":
            out.append(f"[{a.case}] {k} ({LABELS.get(k, (k,))[0]}) = {a.value} — 원문 확인: {p.get('todo') or ''}")
    if ok(f.mult) and f.mult.applied_group == "domestic":
        out.append(f"[data] 미국 피어 시총: {data.CMD_FETCH} (yfinance 종가 2023 첫 거래일·기준일 + SEC 발행주식수 이력) 또는 {data.CMD_GLOBAL}")
    if ok(f.peers) and f.peers.ev_basis == "EBIT":
        out.append(f"[data] D&A(EBITDA용): {data.CMD_FETCH} (DART 현금흐름표 감가상각비·SEC DepreciationDepletionAndAmortization)")
    if ok(f.peers):
        t = f.peers.table
        if (t["region"] == "KR").any() and t[(t["region"] == "KR") & (t["status"] == "applied")]["debt_missing"].any():
            names = ", ".join(t[(t["region"] == "KR") & (t["status"] == "applied") & t["debt_missing"]]["company"])
            out.append(f"[data] 국내 총차입금 미수집: {names} — DART 재무상태표 차입금 계정 매핑 확인(config data_fetch.dart.total_debt)")
        if t[(t["group"] == "core") & t["ni0"].isna()].shape[0]:
            out.append("[data] 미국 피어 FY2022A 순이익(보수 시나리오 분모): " + data.CMD_FETCH)
    out.append("[manual] Schneider Electric: data/manual/overseas_financials_manual.csv(재무) + data/manual/vol03_market_manual.csv(종가·주식수, EUR) — 이번 편 제외")
    return out


def write_summary(path: Path, r: dict, as_of: str, cfg: Mapping) -> None:
    f: data.Facts = r["facts"]
    L = ["# Vol.3 빌드 요약\n", f"- 기준일: {as_of} · 빌드(UTC): {utc_now_iso()}", f"- 폰트: {r['fonts']}",
         "- Target Co.는 가상 기업(실존 기업 아님). 교육·연구 목적, 투자 권유 아님", ""]
    L += ["## 핵심 결론 3줄", ""] + [f"{i}. {t}" for i, t in enumerate(key_conclusions(f), 1)] + [""]
    if r.get("exec_lines"):
        L += ["## Executive Summary 결론 문장 (국문 PDF와 같은 문장)", "", f"- 헤드라인: {r['exec_lines'][0]}"] \
             + [f"{i}. {t}" for i, t in enumerate(r["exec_lines"][1:], 1)] + [""]
    L += ["## 근거", "", "### 비교기업 (3단계 선정)", ""]
    if ok(f.peers):
        t = f.peers.table
        L += [markdown_table([{"회사": x["company"], "티커": x["ticker"], "그룹": x["group"], "2단계": x["step2"], "3단계": x["step3"], "결과": x["status"],
                               "시총(현지 단위)": _f(x["mcap1"], 1), "지배순이익 FY2025A": _f(x["ni1"], 1), "PER 현재": _f(x["per1"], 2),
                               "PER 2023초": _f(x["per0"], 2), f"EV/{f.peers.ev_basis}": _f(x["evm1"], 2), "R4": "✓" if x["high_flag"] else ""}
                              for _, x in t.iterrows()])]
    if ok(f.mult):
        mu = f.mult
        L += ["", "### 그룹 배수 · 시나리오", ""]
        L += [markdown_table([{"그룹": g, "n(현재)": mu.groups[g]["current"].n, "합산": _f(mu.groups[g]["current"].aggregate), "평균": _f(mu.groups[g]["current"].mean),
                               "중앙값": _f(mu.groups[g]["current"].median), "n(2023초)": mu.groups[g]["start"].n, "보수": _f(mu.scen[g]["conservative"]),
                               "정상화": _f(mu.scen[g]["normalized"]), "EV 합산": _f(mu.groups[g]["ev"].aggregate)} for g in ("domestic", "core", "reference")]
                             + [{"그룹": f"적용({mu.applied_group})", "합산": _f(mu.applied("current")), "보수": _f(mu.applied("conservative")),
                                 "정상화": _f(mu.applied("normalized")), "EV 합산": _f(mu.ev_applied)}])]
    if ok(f.val):
        v = f.val
        L += ["", "### 공모가 산출", "", markdown_table([{"시나리오": s, "적용 PER": _f(f.mult.applied(s)), "적정 시총(억원)": _f(v.equity[s], 1),
                                                          "주당 평가가액(원)": _f(v.per_share[s], 0)} for s in SCEN]),
              "", markdown_table([{"할인율": f"{d * 100:.0f}%", "공모가(원)": _f(p, 0)} for d, p in zip(v.grid["discount"], v.grid["price"])])]
        sh = v.shares
        L += ["", f"- 주식: 상장 전 {sh.pre:,.0f} · 신주 {sh.new:,.0f} · 구주 {sh.old:,.0f} · 공모 {sh.offered:,.0f} · 공모 후 {sh.post:,.0f} (오버행 {sh.overhang / sh.post * 100:.1f}%)"]
        if v.ev_per_share:
            L += [f"- EV/{f.peers.ev_basis} 교차 확인: 적정 시총 {v.ev_equity:,.1f}억원 · 주당 {v.ev_per_share:,.0f}원"]
    if ok(f.band):
        b = f.band
        L += [f"- 밴드: {b.low:,.0f}~{b.high:,.0f}원 (원값 {b.raw_low:,.1f}~{b.raw_high:,.1f}, 기준 {b.basis}, 할인율 {b.d_low * 100:.2f}~{b.d_high * 100:.2f}%)"]
    if ok(f.mc):
        mc = f.mc
        L += ["", "### 몬테카를로", "", f"- n = {mc.n:,} · seed {mc.seed} · ln(1+g) ~ N({mc.mu:.4f}, {mc.sd:.4f}) · PER 삼각({mc.per_tri[0]:.3f}, {mc.per_tri[1]:.3f}, {mc.per_tri[2]:.3f})",
              "- 분위(원): " + " · ".join(f"P{q * 100:.0f} {x:,.0f}" for q, x in mc.result.quantiles.items()),
              "- 필요 할인율: " + " · ".join(f"P{q * 100:.0f} {d * 100:.1f}%" for q, d in mc.required.items()),
              "- 손실 확률: " + " · ".join(f"할인 {d * 100:.0f}% → {p * 100:.1f}%" for d, p in mc.loss_grid.items()),
              "", "**수렴**", "", markdown_table(mc.result.convergence.round(4).to_dict("records"))]
    L += ["", "### 검산 (배수·단위·환율·공모 구조·재현)", "", markdown_table(checks(f, cfg)) if checks(f, cfg) else "- 계산 보류"]
    L += ["", "## 산출물", ""] + [f"- `{p.name}` — {r['pages'][lang]}쪽 (960×720pt, 4:3)" for lang, p in r["pdfs"].items()]
    L += [f"- `figures/{p.name}`" for p in r.get("figures", [])]
    rw = [f"{lang}: {w}" for lang, ws in r.get("render_warnings", {}).items() for w in ws]
    L += ["", "**렌더링 점검 (목차 한 줄·바닥글·뒤표지 넘침)**: " + ("; ".join(rw) if rw else "이상 없음")]
    L += ["", "## 페이지 제목 (국문)", ""] + [f"- **{lab}** {t}" for lab, t in r.get("page_titles", [])]
    pend = r["pending"].get("kr") or next(iter(r["pending"].values()), [])
    L += ["", "## 데이터·출처 확인 후 생성되는 Exhibit", ""] + ([f"- p{lab}: {t} — {why}" for lab, t, why in pend] or ["- 없음"])
    L += ["", "## 점검 필요 수치 (ECM 실무 상식 대비, 자동 점검)", ""] + ([f"- {x}" for x in anomalies(f, cfg)] or ["- 없음"])
    L += ["", "## 출처를 채워야 할 가정·데이터 (TODO)", ""] + [f"- {x}" for x in todo_items(f, cfg)]
    cnt = {}
    for a in f.assumptions.values():
        cnt[a.status] = cnt.get(a.status, 0) + 1
    L += ["", "## 가정 집계 (보고서 A2 기준)", "", markdown_table([{"상태": k, "개수": v_} for k, v_ in sorted(cnt.items())])]
    lim = []
    if ok(f.mult) and f.mult.applied_group == "domestic":
        lim.append("- 미국 피어 시총이 커밋되지 않아 적용 배수는 국내 비교기업만 — 수집 후 같은 코드로 국내·해외 핵심 평균으로 갱신")
    if ok(f.peers) and f.peers.ev_basis == "EBIT":
        lim.append("- D&A 미수집 → EV/EBITDA 대신 EV/EBIT 대용(보조 지표)")
    L += ["", "## 한계", ""] + lim + [
          "- 이익 기준은 FY2025A(최근 사업연도). LTM이면 배수·이익 모두 달라짐",
          "- 몬테카를로는 성장률·배수만(독립), 이익률 고정 — 하방 과소 가능",
          "- 밴드 분위(P25~P50)·정상화 50%·이상치 기준·그룹 평균 결합은 저자 판단"]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Note Vol.3 생성 (가로형 4:3)")
    p.add_argument("--asof", default=None, help="기준일 (기본: config research.vol03.as_of)")
    p.add_argument("--lang", choices=["kr", "en", "both"], default="both")
    p.add_argument("--write-template", action="store_true", help="가정 입력 CSV 양식 생성·갱신 (입력값 보존)")
    p.add_argument("--no-figures", action="store_true", help="figures/ 단독 그림 생략")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    if args.write_template:
        print(f"가정 입력 양식: {data.write_template(cfg)}")
        return 0
    langs = ("kr", "en") if args.lang == "both" else (args.lang,)
    r = build(cfg, args.asof, langs, figures=not args.no_figures)
    print("\n=== KSJ Research Vol.3 빌드 결과 ===")
    print(f"폰트: {r['fonts']}")
    for lang, path in r["pdfs"].items():
        print(f"{path}  ({r['pages'][lang]}쪽)")
    for t in key_conclusions(r["facts"]):
        print(f"  · {t}")
    for lab, t, why in next(iter(r["pending"].values()), []):
        print(f"  p{lab} 데이터 수집 후 생성: {t}  —  {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
