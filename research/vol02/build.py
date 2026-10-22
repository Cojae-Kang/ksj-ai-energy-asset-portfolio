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
                   f"최소 DSCR {a.base.min_dscr:.2f}배, 계약 임대료만으로는 {a.base.min_dscr_contracted:.2f}배")
    else:
        out.append(f"케이스 A: 데이터로 보이는 병목은 계통 승인 비율 {g.ratio * 100:.1f}%·사전 임대율 {f.assumptions['A']['prelease'].low * 100:.0f}~"
                   f"{f.assumptions['A']['prelease'].high * 100:.1f}%(원문 확인 중). 대출 한도는 가정 근거 확인 후 산출(필요 입력 {len(a.missing)}개)"
                   if g.ratio is not None and not ok(a) else "케이스 A: 입력 대기")
    if ok(b):
        out.append(f"케이스 B 대출 한도 USD {b.base.debt:,.0f}mn(총사업비의 {b.base.gearing * 100:.0f}%), 최소 DSCR {b.base.min_dscr:.2f}배")
    elif ok(f.rates):
        out.append(f"케이스 B: 기준금리 DGS10 {f.rates.dgs10:.2f}%가 국고채 10년 {f.rates.ktb_10y:.2f}%보다 "
                   f"{f.rates.dgs10 - f.rates.ktb_10y:.2f}%p 높다. 대출 한도는 가정 근거 확인 후 산출")
    if ok(f.peers):
        sc = f.peers.scenarios()
        out.append(f"공사비 스트레스 근거: 피어 3사 영업이익률 {f.peers.agg_opm0 * 100:.1f}%→{f.peers.agg_opm1 * 100:.1f}% → "
                   f"함의 가격 상승률 {sc['low'] * 100:.1f}~{sc['high'] * 100:.1f}%(상한값, 인과 아님)")
    return out[:3]


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
        rows += [{"항목": f"VA / US 상업용 판매 CAGR {f.va.base_year}→{f.va.last_year}", "값": f"{f.va.va_cagr * 100:.2f}% / {f.va.us_cagr * 100:.2f}%", "근거": "EIA"},
                 {"항목": "상업용 평균 요금", "값": f"{p:.2f}¢/kWh ({y})", "근거": f"EIA {'Virginia' if f.va.price_source == 'VA' else 'U.S. (VA 수집 전 대용)'}"}]
    g = f.grid
    if g.ratio is not None:
        rows.append({"항목": f"계통 승인 비율 ({g.period})", "값": f"{g.approved:,.0f} ÷ {g.applied:,.0f} = {g.ratio * 100:.2f}%",
                     "근거": "사용자 메모 수치(원문 확인 필요)" + (f" — 메모상 {g.memo_pct}%와 불일치" if g.memo_mismatch else "")})
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
    op = f.option
    L += ["", "## 실물옵션 (케이스 A 2단계)", ""]
    if ok(op):
        rr = op.result
        L += [f"- 옵션 가치 {rr.value:,.2f} · 조건부 {rr.value_conditional:,.2f} (표준오차 {rr.stderr_conditional:,.2f}) · 지금 짓기 {rr.build_now:,.2f} · 유연성 {rr.flexibility:,.2f}",
              "", markdown_table(rr.convergence.round(4).to_dict("records"))]
    else:
        L += [f"- 계산 보류: {op.reason} — {data.fmt_missing(op.missing)}"]
    # 한계
    L += ["", "## 한계", "", "- 근거가 확인되지 않은 가정(null)은 계산하지 않음 → 해당 Exhibit은 회색 박스",
          "- 가동률 램프업은 IEA 세계 데이터센터 전력 성장률 근사, 피어 이익률→가격은 상한값(인과 아님)",
          "- 계통 승인 수치·임대료·사전 임대율은 사용자 메모·보도 인용값(원문 확인 필요)"]
    # 가정 상태
    L += ["", "## 가정 상태 (null = 근거 확인 후 입력)", ""]
    for c in data.CASES:
        d = f.assumptions[c]
        miss = [k for k in LABELS if k in d and d[k].value is None]
        nosrc = [k for k in LABELS if k in d and d[k].origin == "csv" and not (d[k].source or d[k].url)]
        L += [f"- 케이스 {c}: null {len(miss)}개 — {', '.join(miss) or '없음'}"]
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
