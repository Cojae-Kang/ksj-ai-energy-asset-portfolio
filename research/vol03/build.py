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
        basis = {"mc": "몬테카를로 분위", "evidence": "국내 IPO 할인율 분포", "config": "입력 할인율"}[b.basis]
        out.append(f"Target Co. 주당 평가가액 {v.per_share['current']:,.0f}원 → 현재 기준 희망공모가 {b.low:,.0f}~{b.high:,.0f}원(할인율 {b.d_low * 100:.1f}~{b.d_high * 100:.1f}%, "
                   f"{basis} 기준), 공모금액 {v.shares.offered * b.low / 1e8:,.0f}~{v.shares.offered * b.high / 1e8:,.0f}억원")
    if ok(f.mc) and ok(f.mc_dp) and ok(f.band_dp):
        mc, dp, bd = f.mc, f.mc_dp, f.band_dp
        g = cfg_grid_top(f)
        out.append(f"이중 고점(순이익률 {dp.npm_tri[0] * 100:.1f}~{dp.npm_tri[2] * 100:.1f}%) 반영 밴드 {bd.low:,.0f}~{bd.high:,.0f}원 — 필요 할인율 {mc.required[0.5] * 100:.1f}% → "
                   f"{dp.required[0.5] * 100:.1f}%(P50), 할인율 {g * 100:.0f}%에서도 1년 후 손실 확률 {dp.loss_grid[g] * 100:.1f}%"
                   + (" — 할인율만으로는 덮이지 않음" if dp.required[0.5] > g else ""))
    elif ok(f.mc):
        mc = f.mc
        out.append(f"1년 후 주당가치 P10/P50/P90 {mc.result.q(0.1):,.0f}/{mc.result.q(0.5):,.0f}/{mc.result.q(0.9):,.0f}원 — 필요 할인율 "
                   f"{mc.required[0.5] * 100:.1f}%(P50)~{mc.required[0.25] * 100:.1f}%(P25)")
    return out[:3]


def ev_cmd(f: data.Facts) -> str:
    return f"python -m research.vol03.ipo_discounts --asof {f.as_of} (로컬, DART)"


def cfg_grid_top(f: data.Facts) -> float:
    """할인율 시나리오 상단 (몬테카를로 손실 확률 격자의 최대 키)."""
    return max(f.mc.loss_grid)


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
    if ok(f.val) and f.val.nn:
        nn, sh = f.val.nn, f.val.shares
        ps = f.val.rev * nn["npm"] * nn["per"] * 1e8 / sh.post
        rows.append({"검산": "정상화 이익 × 정상화 배수 = 매출 × 사이클 평균 순이익률 × 정상화 PER ÷ 주식수",
                     "계산": f"{f.val.rev:,.0f} × {nn['npm']:.4f} × {nn['per']:.4f} × 1e8 ÷ {sh.post:,.0f} = {ps:,.2f}",
                     "보고서 값": f"{nn['per_share']:,.2f}", "차이": f"{abs(ps - nn['per_share']):.1e}"})
        hist = f.der.hist if f.der else {}
        if hist:
            cyc = sum(h["npm"] * h["revenue"] for h in hist.values()) / sum(h["revenue"] for h in hist.values())
            rows.append({"검산": "사이클 평균 순이익률 = Σ지배순이익 ÷ Σ매출 (FY2022A~FY2025A, 3사)", "계산": f"{cyc:.6f}",
                         "보고서 값": f"{nn['npm']:.6f}", "차이": f"{abs(cyc - nn['npm']):.1e}"})
    if ok(f.band_dp) and ok(f.val):
        bd, v0 = f.band_dp, f.val.per_share["current"]
        rows.append({"검산": "이중 고점 밴드 할인율 = 1 − 가격 ÷ 평가가액", "계산": f"1 − {bd.high:,.0f} ÷ {v0:,.0f} = {1 - bd.high / v0:.4f}",
                     "보고서 값": f"{bd.d_low:.4f}", "차이": f"{abs(1 - bd.high / v0 - bd.d_low):.1e}"})
    if ok(f.band) and ok(f.val):
        b, v0 = f.band, f.val.per_share["current"]
        rows.append({"검산": "밴드 할인율 = 1 − 가격 ÷ 평가가액", "계산": f"1 − {b.high:,.0f} ÷ {v0:,.0f} = {1 - b.high / v0:.4f}; 1 − {b.low:,.0f} ÷ {v0:,.0f} = {1 - b.low / v0:.4f}",
                     "보고서 값": f"{b.d_low:.4f}; {b.d_high:.4f}", "차이": f"{abs(1 - b.high / v0 - b.d_low) + abs(1 - b.low / v0 - b.d_high):.1e}"})
    if ok(f.mc) and ok(f.val):
        mc = f.mc
        r2 = im.monte_carlo(f.val.ni, f.val.shares.post, mc.mu, mc.sd, mc.per_tri, mc.n, mc.seed)
        rows.append({"검산": f"몬테카를로 재현 (seed {mc.seed})", "계산": f"P50 재실행 {r2.q(0.5):,.4f}", "보고서 값": f"{mc.result.q(0.5):,.4f}",
                     "차이": f"{abs(r2.q(0.5) - mc.result.q(0.5)):.1e}"})
    if ok(f.mc_dp) and ok(f.val):
        dp = f.mc_dp
        r3 = im.monte_carlo(f.val.ni, f.val.shares.post, dp.mu, dp.sd, dp.per_tri, dp.n, dp.seed, npm_tri=dp.npm_tri,
                            npm_base=f.val.ni / f.val.rev, corr=dp.corr)
        rows.append({"검산": f"이중 고점 몬테카를로 재현 (seed {dp.seed})", "계산": f"P50 재실행 {r3.q(0.5):,.4f}", "보고서 값": f"{dp.result.q(0.5):,.4f}",
                     "차이": f"{abs(r3.q(0.5) - dp.result.q(0.5)):.1e}"})
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
        for _, r in t[t["status"] == "held"].iterrows():
            out.append(f"{r['company']} R6 보류(10-K 확인 전 PER·EV 제외): 순이익 ÷ 영업이익 {r['ni_to_oi']:.1f}배, 장기차입금 태그 "
                       f"{'미보고' if str(r.get('lt_debt_tag')) == 'False' else '있음'}, EV/{f.peers.ev_basis} {r['evm1']:.0f}배")
        for _, r in t[t["high_flag"]].iterrows():
            med = f.mult.groups[r["group"]]["current"].median if ok(f.mult) else float("nan")
            out.append(f"{r['company']} PER {r['per1']:.1f}배 = 그룹 중앙값({med:.1f}배)의 {r['per1'] / med:.1f}배 — 지배순이익률 {r['ni1'] / r['rev1'] * 100:.1f}%로 피어 최저, 시총은 최대(R4 표시·포함)")
        for _, r in t[t["step2"] == "R2"].iterrows():
            out.append(f"{r['company']} PER {r['per1']:.0f}배 (FY2025A 지배순이익 {r['ni1']:,.0f}{'억원' if r['region'] == 'KR' else ' USD mn'}) — 분모 왜곡, R2로 제외")
        us = t[t["region"] == "US"]
        for _, r in us.iterrows():
            if np.isfinite(r["net_debt1"]) and np.isfinite(r["rev1"]) and r["net_debt1"] / r["rev1"] > 0.75:
                out.append(f"{r['company']} 순차입금 ÷ 매출 {r['net_debt1'] / r['rev1'] * 100:.0f}% (FY2025A) — 발전·유틸리티의 자산·차입 구조, 핵심 비교군에서 분리")
            if np.isfinite(r["net_debt1"]) and r["net_debt1"] < 0 and r["status"] != "held":
                out.append(f"{r['company']} 순현금 {(-r['net_debt1']):,.0f} USD mn (총차입금이 단기차입금 태그만 잡힘 — 장기차입금 태그 미보고 가능성, 10-K 주석 확인 필요)")
            if np.isfinite(r["ni1"]) and np.isfinite(r["oi1"]) and r["ni1"] > r["oi1"] * 1.5 and r["oi1"] > 0 and r["status"] != "held":
                out.append(f"{r['company']} FY2025A 순이익 {r['ni1']:,.0f} > 영업이익 {r['oi1']:,.0f} USD mn ({r['ni1'] / r['oi1']:.1f}배) — 영업외 이익(일회성) 가능성, PER 분모 과대 → 배수 과소")
        if f.peers.ev_basis == "EBIT":
            m = t[t["group"].isin(["domestic", "core"]) & (t["status"] == "applied") & t["da1"].isna()]
            out.append(f"EV 배수는 D&A 미수집({', '.join(m['company'])})으로 EV/EBIT 대용 — EV/EBITDA보다 높게 나온다")
        if t["debt_proxy"].any():
            out.append(f"{', '.join(t[t['debt_proxy']]['company'])} 총차입금 = 기타금융부채 대용치(주석 확인 전) — 리스·파생 포함 가능성")
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
        for lab, m in (("현재 기준", mc), ("이중 고점", f.mc_dp), ("동조 민감도", f.mc_stress)):
            if ok(m) and not m.result.converged:
                cv = m.result.convergence
                out.append(f"몬테카를로 {lab}: 5,000→10,000회 P50 변화 {cv['rel_change_p50'].iloc[-1] * 100:.2f}% > 기준 1% (미수렴 판정) — "
                           f"배치 표준오차 {m.se_p50 * 100:.2f}%, {m.check_n:,}회 재실행 P50 {m.check_p50:,.0f}원({(m.check_p50 / m.result.q(0.5) - 1) * 100:+.2f}%)로 결론 불변")
    if ok(f.mc_dp):
        dp = f.mc_dp
        if dp.required[0.5] > grid[-1]:
            out.append(f"이중 고점의 중앙값 손익분기 할인율 {dp.required[0.5] * 100:.0f}% > 할인율 시나리오 상단 {grid[-1] * 100:.0f}% — 할인율 {grid[-1] * 100:.0f}%에서도 1년 후 손실 확률 {dp.loss_grid[grid[-1]] * 100:.0f}%")
    if f.der and f.der.hist:
        y0, y1 = min(f.der.hist), max(f.der.hist)
        r = f.der.hist[y0]["npm"] / f.der.hist[y1]["npm"]
        out.append(f"3사 합산 순이익률 FY{y0}A {f.der.hist[y0]['npm'] * 100:.1f}% → FY{y1}A {f.der.hist[y1]['npm'] * 100:.1f}% (FY{y0}A 이익률이면 평가가액 {r * 100:.0f}%) — 이중 고점 몬테카를로(p7)로 반영")
    if ok(f.ipo):
        ev = f.ipo
        for _, r in ev.full.table[ev.full.table["outlier"]].iterrows():
            out.append(f"IPO 할인율 {r['company']}({r['rcept_no']}) {r['discount_low'] * 100:.1f}~{r['discount_high'] * 100:.1f}% — 50% 초과·10% 미만 범위 밖, 원문 확인 필요(분포에는 유지)")
        if ev.full.n < ev.target_n:
            out.append(f"IPO 할인율 표본 {ev.full.n}건(실제 신고일 {ev.full.period[0]}~{ev.full.period[1]}) < 목표 {ev.target_n}건 — 검색 기간 일부만 반영, 분위 신뢰 제한")
        if ev.n_cls_excluded:
            out.append(f"IPO 표본이 DART corp_cls(현재 상장 상태)로 걸러짐 — 이후 상장한 회사의 신고서 {ev.n_cls_excluded:,}건 제외(look-ahead bias). "
                       "남은 표본은 철회·지연 딜과 아직 상장 전 딜에 치우침 → 접수 시점 판정으로 재수집 필요")
        if ev.chosen == "full":
            out.append(f"Target(공모 2,000억원대)과 비슷한 하위 표본({ev.sub_rule}) {ev.sub.n}건 < {ev.sub_min_n}건 — 전체 표본 분포로 대체")
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
        held = t[t["status"] == "held"]
        for _, r in held.iterrows():
            out.append(f"[verify] {r['company']} 10-K 주석: 영업외 이익(순이익 {r['ni1']:,.0f} vs 영업이익 {r['oi1']:,.0f} USD mn)·장기차입금 — 확인 후 config multiples.hold_out에서 삭제")
        kr_da = t[(t["region"] == "KR") & (t["status"] == "applied") & t["da1"].isna()]
        if len(kr_da):
            out.append(f"[data] 국내 D&A 미수집: {', '.join(kr_da['company'])} — python -m src.data_fetch.dart --da-candidates " + "/".join(kr_da["ticker"]) + " (로컬 원자료로 계정 후보 확인) → 현금흐름표에 없으면 주석 수치를 data/manual/vol03_peer_manual.csv에 입력")
        if (t["region"] == "KR").any() and t[(t["region"] == "KR") & (t["status"] == "applied")]["debt_missing"].any():
            out.append("[check] 국내 총차입금 매핑 점검: python -m src.data_fetch.dart --debt-candidates 267260 (로컬 원자료, API 호출 없음) → "
                       "후보가 없으면 무차입, 이름만 다르면 IFRS account_id 2차 매칭(id_fallback)으로 재수집")
    if not ok(f.ipo):
        out.append(f"[data] 국내 IPO 할인율 실증: python -m research.vol03.ipo_discounts --asof {f.as_of} (DART 증권신고서, 로컬)")
    elif f.ipo.n_cls_excluded or not f.ipo.pit:
        out.append(f"[data] IPO 표본 접수 시점 재판정: python -m research.vol03.ipo_discounts --asof {f.as_of} (corp_cls 필터 제거, 캐시 원문 재사용; "
                   f"상장일 표는 --listing-dates로 먼저 만들면 원문 다운로드가 줄어듦)")
    if ok(f.ipo) and f.ipo.full.n < f.ipo.target_n:
        out.append(f"[data] IPO 할인율 표본 {f.ipo.full.n}건 < 목표 {f.ipo.target_n}건 (실제 신고일 {f.ipo.full.period[0]}~{f.ipo.full.period[1]}) — "
                   f"python -m research.vol03.ipo_discounts --asof {f.as_of} (월 구간·전체 페이지 재검색, 로컬)")
    if ok(f.peers) and f.peers.table["debt_proxy"].any():
        names = ", ".join(f.peers.table[f.peers.table["debt_proxy"]]["company"])
        out.append(f"[verify] 총차입금 대용치(주석 확인 전): {names} — 사업보고서 차입금 주석과 대조 후 config data_fetch.dart.total_debt.company_overrides 정리")
    out.append("[manual] Schneider Electric: data/manual/overseas_financials_manual.csv(재무) + data/manual/vol03_market_manual.csv(종가·주식수, EUR) — 이번 편 제외")
    return out


def tri_median(lo: float, mode: float, hi: float) -> float:
    """삼각분포 중앙값 (손계산 검산용)."""
    if hi <= lo:
        return lo
    if (mode - lo) / (hi - lo) >= 0.5:
        return lo + math.sqrt(0.5 * (hi - lo) * (mode - lo))
    return hi - math.sqrt(0.5 * (hi - lo) * (hi - mode))


def floor_section(f) -> list[str]:
    """이중 고점 순이익률 하한 가정 두 값(코드 재현) + 손계산 근사 검산."""
    dp, alt = f.mc_dp, f.dp_floor_alt
    if not data.ok(dp) or not alt:
        return []
    v0, ni, sh = f.val.per_share["current"], f.val.ni, f.val.shares.post
    g_med = math.exp(dp.mu)                                   # 1년 후 성장 배수 중앙값 = e^μ (로그정규)
    per_med = tri_median(*dp.per_tri)
    npm_base = f.val.ni / f.val.rev
    rows = []
    for lab, m in ((f"FY{alt['fy'] - 1}A (기준·사이클 바닥)", dp), (f"FY{alt['fy']}A (대안)", alt["mc"])):
        lo, mo, hi = m.npm_tri
        nm = tri_median(lo, mo, hi)
        approx = ni * g_med * (nm / npm_base) * per_med * 1e8 / sh
        rows.append({"순이익률 하한": lab, "삼각분포(최소·최빈·최대)": f"{lo * 100:.2f}% · {mo * 100:.2f}% · {hi * 100:.2f}%",
                     "필요 할인율 P50 (모델)": f"{m.required[0.5] * 100:.1f}%", "P25 (모델)": f"{m.required[0.25] * 100:.1f}%",
                     "손계산 근사 P50 가치": f"{approx:,.0f}원", "손계산 필요 할인율": f"{(1 - approx / v0) * 100:.1f}%"})
    return ["", "### 이중 고점: 순이익률 하한 가정이 결론을 좌우 (같은 seed·같은 입력, 하한만 변경)", "", markdown_table(rows), "",
            f"- 손계산 근사 = 지배순이익 {ni:,.2f}억원 × 성장 중앙값 e^μ {g_med:.3f} × (순이익률 삼각분포 중앙값 ÷ 현재 {npm_base * 100:.2f}%) × PER 삼각분포 중앙값 {per_med:.2f}배 ÷ 공모 후 {sh:,.0f}주 "
            f"— 중앙값끼리 곱한 근사라 모델(결합분포의 중앙값)과 1%p 안팎 차이. 주당 평가가액 {v0:,.0f}원"]


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
                                                          "주당 평가가액(원)": _f(v.per_share[s], 0)} for s in SCEN]
                                                        + ([{"시나리오": f"정상화 이익(순이익률 {v.nn['npm'] * 100:.2f}%) × 정상화 배수", "적용 PER": _f(v.nn["per"]),
                                                             "적정 시총(억원)": _f(v.nn["equity"], 1), "주당 평가가액(원)": _f(v.nn["per_share"], 0)}] if v.nn else [])),
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
        L += ["", "### 몬테카를로 (현재 기준 · 이중 고점 · 동조 민감도)", "",
              f"- n = {mc.n:,} · seed {mc.seed} · ln(1+g) ~ N({mc.mu:.4f}, {mc.sd:.4f}) · PER 삼각({mc.per_tri[0]:.3f}, {mc.per_tri[1]:.3f}, {mc.per_tri[2]:.3f})"]
        if ok(f.mc_dp):
            dp = f.mc_dp
            L += [f"- 이중 고점: 순이익률 삼각({dp.npm_tri[0]:.4f}, {dp.npm_tri[1]:.4f}, {dp.npm_tri[2]:.4f}), 상관 행렬 {np.round(dp.corr, 2).tolist()}; "
                  f"동조 민감도 상관 {np.round(f.mc_stress.corr, 2).tolist() if ok(f.mc_stress) else '—'}"]
        for lab, m in (("현재 기준", mc), ("이중 고점", f.mc_dp), ("동조 민감도", f.mc_stress)):
            if not ok(m):
                continue
            L += ["", f"**{lab}**", "",
                  "- 분위(원): " + " · ".join(f"P{q * 100:.0f} {x:,.0f}" for q, x in m.result.quantiles.items()),
                  "- 필요 할인율: " + " · ".join(f"P{q * 100:.0f} {d * 100:.1f}%" for q, d in m.required.items()),
                  "- 손실 확률: " + " · ".join(f"할인 {d * 100:.0f}% → {p * 100:.1f}%" for d, p in m.loss_grid.items()),
                  f"- 수렴: {'수렴' if m.result.converged else '기준 초과(미수렴 판정)'} · 배치 표준오차 {m.se_p50 * 100:.2f}% · {m.check_n:,}회 재실행 P50 {m.check_p50:,.0f}원",
                  "", markdown_table(m.result.convergence.round(4).to_dict("records"))]
        if ok(f.band_dp):
            bd = f.band_dp
            L += ["", f"- 이중 고점 밴드: {bd.low:,.0f}~{bd.high:,.0f}원 (원값 {bd.raw_low:,.1f}~{bd.raw_high:,.1f}, 할인율 {bd.d_low * 100:.2f}~{bd.d_high * 100:.2f}%)"]
    L += ["", "### 국내 IPO 할인율 실증 (DART 증권신고서)", ""]
    if ok(f.ipo):
        ev = f.ipo
        q = lambda st: " · ".join(f"{k} {a * 100:.1f}/{b * 100:.1f}/{c * 100:.1f}%" for k, (a, b, c) in st.items())  # noqa: E731
        for s_, lab in ((ev.full, "전체"), (ev.sub, f"하위 표본({ev.sub_rule})")):
            L += [f"- {lab}: n = {s_.n} · 실제 신고일 {s_.period[0] or '—'}~{s_.period[1] or '—'} · Q1/중앙값/Q3 {q(s_.stats) if s_.n else '—'}"
                  + (f" · 이상치 {s_.n_outlier}건 제외 시 {q(s_.stats_ex)}" if s_.n_outlier else "")]
        L += [f"- 파일 {ev.n_all}행 · 밴드 기준 표본: {'하위 표본' if ev.chosen == 'sub' else '전체'}"
              + ("" if ev.chosen == "sub" else f" (하위 표본 {ev.sub.n}건 < {ev.sub_min_n}건)")
              + (f" → n ≥ {ev.min_n}: 밴드 할인율에 사용(sourced)" if ev.used else f" → n < {ev.min_n}: 몬테카를로 밴드 유지")]
        L += [f"- 접수 시점 판정: {'적용 — 복원 ' + str(ev.n_restored) + '건(현재 상장사지만 접수 때 비상장)' if ev.pit else '미적용(이전 버전 파일)'}"
              + (f" · 로그의 예전 corp_cls 필터 제외 {ev.n_cls_excluded:,}건 (look-ahead bias)" if ev.n_cls_excluded else "")]
        if ev.n_cls_excluded:
            try:
                from research.vol03 import ipo_discounts as idc
                e = idc.estimate_from_log(data._read(data._inp(cfg, "ipo_log")[0]), cfg["research"]["vol03"]["ipo_discounts"])
                L += [f"- 로그 기준 추정: 제외된 비스팩 {e['base_init_companies']}개사 중 IPO 약 {e['ipo_est']:.0f}개사(범위 {e['ipo_lo']:.0f}~{e['ipo_hi']:.0f}) — "
                      f"상장사 유상증자 월 {e['rate']:.1f}건(최근 {', '.join(e['tail_months'])} 기준) 차감"]
            except Exception as e_:  # noqa: BLE001
                L += [f"- 로그 기준 추정 생략: {type(e_).__name__}"]
        if ev.full.n < ev.target_n:
            L += [f"- 목표 표본 {ev.target_n}건 미달 ({ev.full.n}건) — 월 구간 재검색: {ev_cmd(f)}"]
        out_t = ev.full.table[ev.full.table["outlier"]]
        if len(out_t):
            L += ["", "원문 확인 필요(할인율 상단 > 50% 또는 하단 < 10%, 분포에는 유지):", "",
                  markdown_table([{"회사": r["company"], "접수번호": r["rcept_no"], "할인율 %": f"{r['discount_low'] * 100:.1f}~{r['discount_high'] * 100:.1f}"}
                                  for _, r in out_t.iterrows()])]
        try:
            from research.vol03 import ipo_discounts as idc
            icfg = cfg["research"]["vol03"]["ipo_discounts"]
            lp = data._inp(cfg, "ipo_log")[0]
            lg = data._read(lp) if lp.exists() else None
            L += ["", idc.breakdown(ev.full.table, lg, icfg)]
        except Exception as e:  # noqa: BLE001 — 분해표는 보조
            L += [f"- 구간·시장·규모별 분해 생략: {type(e).__name__}"]
    else:
        L += [f"- 미수집 — {ev_cmd(f)}"]
    L += ["", "### 검산 (배수·단위·환율·공모 구조·재현)", "", markdown_table(checks(f, cfg)) if checks(f, cfg) else "- 계산 보류"]
    L += floor_section(f)
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
          "- 이중 고점 몬테카를로의 순이익률 분포(최빈 = 4년 사이클 평균)·상관 0(기준)은 저자 판단/중립값 — 동조(ρ=0.5) 민감도 병기",
          "- 보류(R6) 회사는 10-K 주석 확인 전 — 확인 후 편입 시 해외 핵심 배수 변동",
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
