"""Vol.2 페이지 구성·문구 (국문/영문). 숫자는 모두 data.Facts에서, 결론 문장도 계산 결과로 만든다.

공개용 원칙(Vol.1과 같음): 제목에 '(저자 견해)'를 붙이지 않고 요약 쪽 하단·뒤표지에 한 줄만 둔다.
내부 파일·설정·실행 명령·태그는 보고서에 쓰지 않는다. 입력이 없는 계산은 "입력·출처 확인 후 생성" 박스로 둔다.
"""
from __future__ import annotations

import math
import re
from typing import Mapping

import numpy as np

from research.vol01.layout import BigBox, Cell, Page, TableSpec

from . import charts
from .data import LABELS, SCENARIOS, Assumption, CaseResult, Facts, Unavailable, fmt_missing, ok

def josa(word: str, pair: tuple[str, str] = ("이", "가")) -> str:
    """받침 유무로 조사 선택: '사전 임대율' + 이, '임대료 ±10%' + 가. 끝 괄호는 무시."""
    w = re.sub(r"\s*\([^)]*\)\s*$", "", word).rstrip()
    ch = w[-1] if w else ""
    if "가" <= ch <= "힣":
        has = (ord(ch) - 0xAC00) % 28 != 0
    elif ch.isdigit():
        has = ch in "013678"                      # 영·일·삼·육·칠·팔
    elif ch.isascii() and ch.isalpha():
        has = ch.lower() in "lmnr"                # 엘·엠·엔·알
    else:
        has = False                               # %(퍼센트) 등
    return word + (pair[0] if has else pair[1])


SCEN_KR = {"downside": "하단", "base": "기준", "upside": "상단"}
SCEN_EN = {"downside": "Low", "base": "Base", "upside": "High"}


class Story:
    def __init__(self, cfg: Mapping, f: Facts, lang: str):
        self.cfg, self.f, self.lang, self.kr = cfg, f, lang, lang == "kr"
        self.c = cfg["research"]["colors"]
        self.v = cfg["research"]["vol02"]

    # --- 문구·숫자 도우미 ---------------------------------------------------
    def T(self, kr: str, en: str) -> str:
        return kr if self.kr else en

    def x(self, v: float | None, d: int = 2) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:.{d}f}배" if self.kr else f"{v:.{d}f}x"

    @staticmethod
    def pct(v: float | None, d: int = 1, sign: bool = False) -> str:
        """소수 → %."""
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v * 100:+.{d}f}%" if sign else f"{v * 100:.{d}f}%"

    @staticmethod
    def pp(v: float, d: int = 2) -> str:
        return f"{v:+.{d}f}%p"

    def money(self, case: str, v: float | None, d: int = 0) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        if case == "A":
            return f"{v:,.{d}f}억원" if self.kr else f"KRW {v / 10:,.{0 if abs(v) >= 1000 else 1}f}bn"
        return f"USD {v:,.{d}f}mn"

    def krw(self, v: float | None) -> str:
        """억원 표기 (B 환산용)."""
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:,.0f}억원" if self.kr else f"KRW {v / 10:,.{0 if abs(v) >= 1000 else 1}f}bn"

    def yrs(self, v: float | None, d: int = 1) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:.{d}f}년" if self.kr else f"{v:.{d}f} yrs"

    def name(self, case: str) -> str:
        s = self.v["cases"][case]
        return s["short_kr"] if self.kr else s["short_en"]

    def scen(self, s: str) -> str:
        return SCEN_KR[s] if self.kr else SCEN_EN[s]

    def lab(self, key: str) -> str:
        return LABELS.get(key, (key, key))[0 if self.kr else 1]

    def missing_text(self, u: Unavailable, limit: int = 8) -> str:
        if not u.missing:
            return self.T(u.reason, u.reason_en or u.reason)
        keys = u.missing[:limit]
        more = len(u.missing) - len(keys)
        s = fmt_missing(keys, self.kr) + (self.T(f" 외 {more}개", f" and {more} more") if more > 0 else "")
        return self.T(f"입력 필요: {s}", f"Inputs needed: {s}")

    def pending(self, title: str, src: list[str], u: Unavailable, note: str = "") -> Cell:
        return Cell(title=title, src=src, placeholder=(self.missing_text(u), ""), note=note)

    def case(self, c: str) -> CaseResult | Unavailable:
        return self.f.cases.get(c, Unavailable("", "", []))

    def A(self, key: str) -> Assumption:
        return self.f.assumptions["A"][key]

    def B(self, key: str) -> Assumption:
        return self.f.assumptions["B"][key]

    # --- 출처·고정 문구 ----------------------------------------------------
    def sources(self) -> dict[str, str]:
        return {
            "iea": self.T("IEA, Energy and AI (2025.4) 요약", "IEA, Energy and AI (Apr 2025), executive summary"),
            "iea_kq": self.T("IEA, Key Questions on Energy and AI (2026.4)", "IEA, Key Questions on Energy and AI (Apr 2026)"),
            "ecos": self.T("한국은행 ECOS 시장금리(일별)·원/달러 환율", "Bank of Korea ECOS market rates (daily), USD/KRW"),
            "fred": "FRED, Federal Reserve Bank of St. Louis (DGS10)",
            "dart": self.T("금융감독원 DART 사업보고서(연결)", "FSS DART annual reports (consolidated)"),
            "eia": "U.S. Energy Information Administration (EIA), Electricity retail sales",
            "grid": self.T("수도권 계통 신청·승인 공개 보도(2024.8~2026.3, 원문 확인 중)",
                           "Public reports on Seoul-metro grid applications (Aug 2024–Mar 2026; source being verified)"),
            "law": self.T("분산에너지 활성화 특별법(전력계통영향평가)", "Distributed Energy Act (grid impact assessment)"),
            "market": self.T("시장 보고서 인용 보도(임대료·사전 임대율, 원문 확인 중)",
                             "Press citing market reports (rent, pre-leasing; source being verified)"),
            "tax": self.T("미국 연방 세법 26 U.S.C. §11(b), 버지니아 주법 §58.1-400", "26 U.S.C. §11(b); Va. Code §58.1-400"),
            "ksj": "KSJ Research",
        }

    def labels(self) -> dict[str, str]:
        return {"source": self.T("출처", "Source"), "note": self.T("주", "Note"), "unit": self.T("단위", "Unit"),
                "pending": self.T("입력·출처 확인 후 생성", "Generated once inputs are sourced")}

    def footer(self) -> str:
        return self.T(f"KSJ Research · Research Note Vol.2 · {self.v['date_label']} · 교육·연구 목적, 투자 권유 아님 · 가상 케이스",
                      f"KSJ Research · Research Note Vol.2 · {self.v['date_label']} · For education and research only, "
                      "not investment advice · hypothetical cases")

    # =======================================================================
    # 계산 결과 → 문장 조각
    # =======================================================================
    def grid_sentence(self) -> str | None:
        g = self.f.grid
        if g.ratio is None:
            return None
        return self.T(f"수도권 1단계 계통 신청 {g.applied:,.0f}MW 중 최종 승인 {g.approved:,.0f}MW({self.pct(g.ratio)})",
                      f"{g.approved:,.0f} MW approved of {g.applied:,.0f} MW applied in the Seoul metro, phase 1 ({self.pct(g.ratio)})")

    def prelease_range(self) -> str:
        p = self.A("prelease")
        if p.low is None:
            return "—"
        return f"{p.low * 100:.0f}~{p.high * 100:.1f}%" if self.kr else f"{p.low * 100:.0f}–{p.high * 100:.1f}%"

    def rate_spread(self) -> float | None:
        r = self.f.rates
        if not ok(r) or r.dgs10 is None or r.ktb_10y is None:
            return None
        return r.dgs10 - r.ktb_10y

    def lease_up_years(self, s: str = "base") -> float | None:
        d, p = self.f.demand, self.A("prelease").value
        if not ok(d) or p is None:
            return None
        g = d.growth[s] * float(self.A("ramp_elasticity").value or 1.0)
        return math.log(1 / p) / math.log(1 + g) if g > 0 else None

    def binding_text(self, r) -> str:
        return {"dscr": self.T("목표 DSCR이 한도를 정했다", "the target DSCR sets the limit"),
                "gearing": self.T("최대 대출 비율이 한도를 정했다", "maximum gearing sets the limit")}.get(r.binding, "")

    def to_krw(self, usd_mn: float | None) -> float | None:
        fx = self.f.fx()
        if usd_mn is None or fx is None:
            return None
        from src.analysis.pf_model import usd_mn_to_krw_100m
        return usd_mn_to_krw_100m(usd_mn, fx)

    # =======================================================================
    # 페이지
    # =======================================================================
    def pages(self) -> list[Page]:
        return [self.cover(), self.executive(), self.toc_page(), self.p1(), self.p2(), self.p3(), self.p4(), self.p5(),
                self.p6(), self.p7(), self.a1(), self.a_assumptions("A", "A2"), self.a_assumptions("B", "A3"), self.a4(),
                self.a5(), self.a6(), self.back()]

    def cover(self) -> Page:
        return Page("cover", title=self.v["title_kr"] if self.kr else self.v["title_en"],
                    subtitle=(self.v["subtitle_kr"] if self.kr else self.v["subtitle_en"]),
                    extra={"kicker": "Research Note Vol.2", "author": self.cfg["research"]["author"], "date": self.v["date_label"],
                           "note": self.T("KSJ Research · 교육·연구 목적 · 투자 권유 아님 · 실존 프로젝트 아님",
                                          "KSJ Research · For education and research only · Not investment advice · Not a real project")})

    def back(self) -> Page:
        items = [
            self.T("이 자료는 교육·연구 목적의 개인 포트폴리오이며, 투자 권유나 금융 자문이 아니다.",
                   "This is a personal portfolio for education and research. It is not investment or financial advice."),
            self.T("두 케이스는 실존 프로젝트가 아닌 가상 케이스다. 같은 모델 엔진에 가정만 다르게 넣었다.",
                   "Both cases are hypothetical, not real projects; the same model engine runs with different assumptions."),
            self.T("본문의 판단은 저자 개인의 견해이며, 저자가 속했거나 속할 어떤 기관의 견해도 대변하지 않는다.",
                   "Views are the author's own and do not represent any current or future employer."),
            self.T("모든 데이터는 공개 자료이며 정확성과 완전성을 보장하지 않는다. 가정과 그 근거는 Appendix A2·A3에 있다.",
                   "All data are public; accuracy and completeness are not guaranteed. Assumptions and their sources are in Appendix A2–A3."),
            self.T(f"기준일 {self.f.as_of}. 계산 방법과 코드는 저장소에서 재현할 수 있다.",
                   f"As of {self.f.as_of}. Methods and code can be reproduced from the repository."),
        ]
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"]})

    # --- Executive Summary --------------------------------------------------
    def headline(self) -> str:
        a, b = self.case("A"), self.case("B")
        if ok(a) and ok(b):
            ka, kb = a.base.gearing, b.base.gearing
            vk, ve = self.VAR_KR, self.VAR_EN
            ta, tb = a.tornado.iloc[0]["variable"], b.tornado.iloc[0]["variable"]
            return self.T(f"대출 한도는 총사업비의 한국 {self.pct(ka, 0)}, 미국 {self.pct(kb, 0)} — 최소 DSCR을 가장 흔드는 변수는 한국 {vk[ta]}, 미국 {vk[tb]}",
                          f"Debt capacity: {self.pct(ka, 0)} of cost in Korea, {self.pct(kb, 0)} in the U.S. — min DSCR is most sensitive to {ve[ta].lower()} (Korea) and {ve[tb].lower()} (U.S.)")
        parts = []
        if self.f.grid.ratio is not None:
            parts.append(self.T(f"한국은 계통(승인 {self.pct(self.f.grid.ratio)})과 사전 임대율({self.prelease_range()})",
                                f"Korea: grid ({self.pct(self.f.grid.ratio)} approved) and pre-leasing ({self.prelease_range()})"))
        sp = self.rate_spread()
        if sp is not None:
            parts.append(self.T(f"미국은 규모와 금리(미 국채 10년이 국고채보다 {sp:.2f}%p 높다)",
                                f"U.S.: scale and rates (UST 10y {sp:.2f}pp above KTB 10y)"))
        body = self.T(" · ".join(parts) + "가 대출 한도의 첫 변수", "; ".join(parts) + " — the first drivers of debt capacity")
        return body if parts else self.T("AI 데이터센터 PF: 대주의 눈으로 본 대출 한도", "AI data-centre PF: debt capacity through a lender's eyes")

    def executive(self) -> Page:
        f, r, d, pp = self.f, self.f.rates, self.f.demand, self.f.peers
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        if f.grid.ratio is not None:
            add(self.T(f"수도권 계통 승인 비율 ({f.grid.period})", f"Seoul-metro grid approval ({f.grid.period})"), self.pct(f.grid.ratio), "1", True)
        add(self.T("수도권 사전 임대율 (2027·2028 준공분)", "Seoul-metro pre-leasing (2027–28 deliveries)"), self.prelease_range(), "1")
        if ok(d):
            add(self.T("수요 성장률 IEA 2024→2035 (하단·기준·상단)", "Demand growth IEA 2024→2035 (low·base·high)"),
                " · ".join(self.pct(d.growth[s]) for s in SCENARIOS), "2")
        if ok(r):
            add(self.T(f"국고채 3년 · 10년 ({r.ktb_date})", f"KTB 3y · 10y ({r.ktb_date})"), f"{r.ktb_3y:.2f}% · {r.ktb_10y:.2f}%", "2")
            add(self.T(f"미 국채 10년 ({r.dgs10_date})", f"UST 10y ({r.dgs10_date})"), f"{r.dgs10:.2f}%", "2", True)
        if ok(pp):
            sc = pp.scenarios()
            add(self.T("피어 함의 전력기기 가격 상승률 (저·중·고)", "Peer-implied equipment price rise (low·mid·high)"),
                " · ".join(self.pct(sc[k]) for k in ("low", "mid", "high")), "2")
        for c in ("A", "B"):
            cr = self.case(c)
            if ok(cr):
                b = cr.base
                add(self.T(f"{self.name(c)} 대출 한도 (총사업비 대비)", f"{self.name(c)} debt (share of cost)"),
                    f"{self.money(c, b.debt)} ({self.pct(b.gearing, 0)})", "3" if c == "A" else "6", True)
                add(self.T(f"{self.name(c)} 최소 DSCR · Equity IRR", f"{self.name(c)} min DSCR · equity IRR"),
                    f"{self.x(b.min_dscr)} · {self.pct(b.equity_irr)}", "3" if c == "A" else "6")
            else:
                add(self.T(f"{self.name(c)} 대출 한도", f"{self.name(c)} debt capacity"), self.T("입력 후 산출", "after inputs"), "3" if c == "A" else "6")
        op = f.option
        add(self.T("2단계 20MW 증설 옵션 가치", "Phase 2 (20 MW) option value"),
            self.money("A", op.result.value) if ok(op) else self.T("입력 후 산출", "after inputs"), "5")
        table = TableSpec([self.T("핵심 지표", "Key metric"), self.T("값", "Value"), self.T("쪽", "p.")], rows,
                          [0.60, 0.31, 0.09], ["L", "R", "C"], shade_rows=shade, gold_cells=gold, font_size=8.4,
                          single_line_cols={1})
        left = Cell(title=self.T("핵심 지표", "Key metrics"), src=["grid", "market", "iea", "ecos", "fred", "dart"], table=table,
                    note=self.T("KSJ Research 계산. 가상 케이스이며 각 지표의 정의·근거는 해당 쪽 각주와 A2·A3. 본문의 판단은 저자 개인의 견해",
                                "KSJ Research. Hypothetical cases; definitions and sources in footnotes and A2–A3. Judgements are the author's own"))
        sub = self.T("같은 PF 엔진(sculpting · waterfall · DSRA · LLCR · IRR)에 한국 40MW(원화)와 미국 100MW(달러) 가정을 넣어 비교",
                     "One PF engine (sculpting, waterfall, DSRA, LLCR, IRR) run on a 40 MW Korean (KRW) and a 100 MW U.S. (USD) case")
        return Page("exec", label="i", title=self.headline(), subtitle=sub, cells=[left],
                    boxes=[self.box_korea(), self.box_us(), self.box_cost()])

    def box_korea(self) -> BigBox:
        a, g = self.case("A"), self.f.grid
        bl = []
        if ok(a):
            b = a.base
            num, cap = self.money("A", b.debt), self.T(f"1단계 20MW 대출 한도 (총사업비의 {self.pct(b.gearing, 0)})",
                                                        f"Phase 1 (20 MW) debt ({self.pct(b.gearing, 0)} of cost)")
            title = self.T(f"한국 40MW — {self.binding_text(b)}, 최소 DSCR {self.x(b.min_dscr)}",
                           f"Korea 40 MW — {self.binding_text(b)}; min DSCR {self.x(b.min_dscr)}")
            bl.append(self.T(f"계약 임대료만으로 본 최소 DSCR {self.x(b.min_dscr_contracted)} (사전 임대율 {self.pct(a.inp.prelease)})",
                             f"Min DSCR on contracted rent only: {self.x(b.min_dscr_contracted)} (pre-lease {self.pct(a.inp.prelease)})"))
        else:
            num = self.pct(g.ratio) if g.ratio is not None else "—"
            cap = self.T(f"수도권 1단계 계통 승인 비율 ({g.period})", f"Seoul-metro phase-1 grid approval ({g.period})")
            title = self.T("한국 40MW — 계통 승인과 사전 임대율이 먼저 묶는다", "Korea 40 MW — grid approval and pre-leasing bind first")
        if self.grid_sentence():
            bl.append(self.grid_sentence())
        bl.append(self.T(f"수도권 2027·2028 준공분 사전 임대율 {self.prelease_range()}, 임대료 kW당 월 약 {self.A('rent_per_kw_month').value / 1e4:.0f}만원",
                         f"Pre-leasing {self.prelease_range()} for 2027–28 deliveries; rent about KRW {self.A('rent_per_kw_month').value:,.0f}/kW-month"))
        ly = self.lease_up_years()
        if ly:
            bl.append(self.T(f"시장 수요 성장(IEA 기준 연 {self.pct(self.f.demand.growth['base'])})만큼 채우면 만실까지 {self.yrs(ly)}",
                             f"Filling at market growth (IEA base {self.pct(self.f.demand.growth['base'])}/yr) takes {self.yrs(ly)} to full"))
        return BigBox(num, cap, title, bl[:3])

    def box_us(self) -> BigBox:
        b, r, va = self.case("B"), self.f.rates, self.f.va
        bl = []
        sp = self.rate_spread()
        if ok(b):
            num = self.money("B", b.base.debt)
            cap = self.T(f"대출 한도 (원화 {self.krw(self.to_krw(b.base.debt))}, 총사업비의 {self.pct(b.base.gearing, 0)})",
                         f"Debt capacity ({self.krw(self.to_krw(b.base.debt))}; {self.pct(b.base.gearing, 0)} of cost)")
            title = self.T(f"미국 100MW — {self.binding_text(b.base)}, 최소 DSCR {self.x(b.base.min_dscr)}",
                           f"U.S. 100 MW — {self.binding_text(b.base)}; min DSCR {self.x(b.base.min_dscr)}")
        else:
            num = f"{r.dgs10:.2f}%" if ok(r) else "—"
            cap = self.T(f"미 국채 10년 ({r.dgs10_date}, FRED)" if ok(r) else "미 국채 10년",
                         f"UST 10y ({r.dgs10_date}, FRED)" if ok(r) else "UST 10y")
            title = self.T("미국 100MW — 수요는 크고, 기준금리가 높다", "U.S. 100 MW — demand is large; base rates are higher")
        if sp is not None:
            bl.append(self.T(f"기준금리 차이: 미 국채 10년 {r.dgs10:.2f}% − 국고채 10년 {r.ktb_10y:.2f}% = {sp:+.2f}%p",
                             f"Base-rate gap: UST 10y {r.dgs10:.2f}% − KTB 10y {r.ktb_10y:.2f}% = {sp:+.2f}pp"))
        if ok(va):
            bl.append(self.T(f"버지니아 상업용 전력 판매 연 {self.pct(va.va_cagr)} vs 미국 {self.pct(va.us_cagr)} ({va.base_year}~{va.last_year}, EIA)",
                             f"Virginia commercial sales {self.pct(va.va_cagr)}/yr vs U.S. {self.pct(va.us_cagr)} ({va.base_year}–{va.last_year}, EIA)"))
            y, p = va.price_latest
            who = self.T("버지니아", "Virginia") if va.price_source == "VA" else self.T("미국", "U.S.")
            bl.append(self.T(f"{who} 상업용 평균 요금 {p:.2f}¢/kWh ({y}) — 전력비는 임차인 부담(패스스루) 가정",
                             f"{who} commercial average price {p:.2f}¢/kWh ({y}); power is passed through to the tenant"))
        return BigBox(num, cap, title, bl[:3])

    def box_cost(self) -> BigBox:
        pp, a = self.f.peers, self.case("A")
        if not ok(pp):
            return BigBox("—", self.T(pp.reason, pp.reason_en), self.T("공사비: 데이터 확인 중", "Cost: data pending"), [])
        sc = pp.scenarios()
        title = self.T(f"공사비 위험 — 피어 이익률 {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)}, 전력기기 가격 결정력의 근거",
                       f"Cost risk — peer margins {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)}, evidence of pricing power")
        bl = [self.T(f"이익률 상승이 모두 가격이라면 함의 가격 상승률 {self.pct(sc['low'])}~{self.pct(sc['high'])} (상한값, 인과 아님)",
                     f"If all margin gain were price: implied rise {self.pct(sc['low'])}–{self.pct(sc['high'])} (upper bound, not causal)")]
        if ok(a) and ok(a.capex_stress):
            cm = a.capex_stress
            r_hi = a.stresses["capex_high"]
            bl.append(self.T(f"CAPEX +{(cm['high'] - 1) * 100:.1f}%(고) 시 최소 DSCR {self.x(a.base.min_dscr)} → {self.x(r_hi.min_dscr)}",
                             f"CAPEX +{(cm['high'] - 1) * 100:.1f}% (high): min DSCR {self.x(a.base.min_dscr)} → {self.x(r_hi.min_dscr)}"))
        else:
            bl.append(self.T("CAPEX 영향 = 전력설비 비중 × 함의 가격 상승률 (비중 근거 확인 후 계산)",
                             "CAPEX impact = power-equipment share × implied price rise (computed once the share is sourced)"))
        return BigBox(self.pct(sc["mid"], 1, True), self.T(f"피어 3사 합산 함의 가격 상승률 ({pp.fy0}→{pp.fy1})",
                                                         f"Three peers' combined implied price rise ({pp.fy0}→{pp.fy1})"), title, bl)

    # --- 목차 ---------------------------------------------------------------
    def toc_page(self) -> Page:
        heads = [self.p1(), self.p2(), self.p3(), self.p4(), self.p5(), self.p6(), self.p7()]
        names = [self.T("구조", "Structure"), self.T("데이터 연결", "Data links"), self.T("대출 한도", "Debt sizing"),
                 self.T("스트레스", "Stress"), self.T("증설 옵션", "Expansion option"), self.T("한·미 비교", "Korea vs U.S."),
                 self.T("시사점", "Implications")]
        toc = [(n, nm, h.title, h.label) for n, nm, h in zip(["I", "II", "III", "IV", "V", "VI", "VII"], names, heads)]
        toc.append(("App.", "Appendix", self.T("A1 예상 질의응답 · A2·A3 케이스별 가정과 출처 · A4 데이터 노트 · A5 분석 방법 · A6 용어",
                                               "A1 Q&A · A2–A3 assumptions and sources by case · A4 Data notes · A5 Methodology · A6 Glossary"), "A1–A6"))
        return Page("toc", label="ii", title=self.T("목차", "Contents"),
                    subtitle=self.T("구조 → 데이터 → 대출 한도 → 스트레스 → 옵션 → 비교 → 시사점: 각 장의 결론",
                                    "Structure → data → sizing → stress → option → comparison → implications: each section's conclusion"),
                    toc=toc)

    # --- p1 사업 구조 -------------------------------------------------------
    def p1(self) -> Page:
        c, g = self.c, self.f.grid
        nodes = {"sponsor": (self.T("스폰서(자기자본)", "Sponsor (equity)"), self.T("출자·후순위", "Equity, subordinated")),
                 "spc": ("SPC", self.T("데이터센터 소유·임대", "Owns and leases the DC")),
                 "lenders": (self.T("대주단", "Lenders"), self.T("선순위 PF 대출", "Senior PF loan")),
                 "tenant": (self.T("임차인", "Tenant"), self.T("장기 책임임대", "Long-term lease")),
                 "epc": ("EPC", self.T("고정가·준공 책임", "Fixed price, completion")),
                 "om": ("O&M", self.T("운영·유지보수", "Operations, maintenance")),
                 "power": (self.T("전력 공급", "Power supply"), self.T("계통 접속·수전", "Grid connection"))}
        edges = [("sponsor", "spc", self.T("자기자본", "equity")), ("lenders", "spc", self.T("대출·DSRA", "loan, DSRA")),
                 ("tenant", "spc", self.T("임대료·전력비", "rent, power")), ("epc", "spc", self.T("시공", "build")),
                 ("om", "spc", self.T("운영", "operate")), ("power", "spc", self.T("전력(패스스루)", "power (pass-through)"))]
        pt = self.A("power_passthrough").value
        c1 = Cell(title=self.T("SPC는 장기 책임임대 임대료로 대출을 갚고, 전력비는 임차인이 부담한다(패스스루)",
                               "The SPC repays debt from long-term committed rent; power is passed through to the tenant"),
                  src=["ksj"], chart_key="structure", chart=charts.structure(nodes, edges, c),
                  note=self.T(f"케이스 A 기준 구조도(가상). 전력비 패스스루 {pt * 100:.0f}% 가정: SPC의 전력비 순액 = 0",
                              f"Case A structure (hypothetical). Power pass-through {pt * 100:.0f}%: SPC's net power cost = 0"))
        rows = [
            [self.T("임대차", "Lease"), self.T("임차인", "Tenant"), self.T("장기 책임임대 · 임대료 kW·월 · 연 인상", "Long-term committed lease; rent per kW-month; annual escalation"),
             self.T("사전 임대율 · 임차인 신용", "Pre-lease ratio; tenant credit")],
            [self.T("대출", "Loan"), self.T("대주단", "Lenders"), self.T("목표 DSCR · 최대 대출 비율 · 만기·거치 · DSRA", "Target DSCR; max gearing; tenor, grace; DSRA"),
             self.T("CFADS 변동 · 금리", "CFADS volatility; rates")],
            [self.T("EPC", "EPC"), self.T("시공사", "Contractor"), self.T("고정가 · 준공일 · 지연 배상", "Fixed price; completion date; delay LDs"),
             self.T("전력기기 가격 · 지연", "Equipment prices; delay")],
            [self.T("전력 공급", "Power supply"), self.T("전력회사", "Utility"), self.T("계통 접속 승인 · 수전 용량", "Grid-connection approval; capacity"),
             self.T("2단계 계통 승인", "Phase 2 grid approval")],
            [self.T("전력비", "Power cost"), self.T("임차인", "Tenant"), self.T(f"사용량 × 단가 패스스루 {pt * 100:.0f}%", f"Usage × tariff, {pt * 100:.0f}% pass-through"),
             self.T("패스스루 예외 조항", "Pass-through carve-outs")],
        ]
        c2 = Cell(title=self.T("계약 다섯 개가 현금흐름을 만든다 — 대주가 보는 위험은 임대·금리·공사비·계통",
                               "Five contracts shape the cash flow — lenders watch leasing, rates, cost and grid"),
                  src=["ksj"], table=TableSpec([self.T("계약", "Contract"), self.T("상대방", "Party"), self.T("핵심 조건", "Key terms"),
                                                self.T("대주 관점 위험", "Lender risk")], rows, [0.15, 0.15, 0.42, 0.28], ["L", "L", "L", "L"],
                                               shade_rows={0, 1}, font_size=8.2),
                  note=self.T("가상 구조. 실제 계약 조건은 사업별로 다르다", "Hypothetical structure; actual terms vary by project"))
        rr = self.f.rates
        base_a = self.T(f"국고채 3년·10년 ({rr.ktb_3y:.2f}%·{rr.ktb_10y:.2f}%)", f"KTB 3y/10y ({rr.ktb_3y:.2f}%/{rr.ktb_10y:.2f}%)") if ok(rr) else "ECOS"
        base_b = f"DGS10 ({rr.dgs10:.2f}%)" if ok(rr) else "FRED"
        thr = g.threshold_mw
        rows3 = [
            [self.T("위치", "Location"), self.T("수도권 외곽(인천·경기 서부)", "Outer Seoul metro (Incheon, W. Gyeonggi)"), self.T("미국 버지니아", "Virginia, U.S.")],
            [self.T("용량(IT 부하)", "Capacity (IT load)"), self.T("40MW = 1단계 20MW 확정 + 2단계 20MW 옵션", "40 MW = 20 MW firm + 20 MW option"),
             self.T("100MW 단일 단계", "100 MW, single phase")],
            [self.T("조달 통화 · 기준금리", "Currency · base rate"), f"KRW · {base_a}", f"USD · {base_b}"],
            [self.T("설정 근거", "Rationale"),
             self.T(f"계통 승인률 {self.pct(g.ratio)} · 전력계통영향평가 {thr:.0f}MW 이상 적용 · 국내 운영 사례 40MW급" if g.ratio is not None else "계통 제약",
                    f"Grid approval {self.pct(g.ratio)}; grid impact assessment from {thr:.0f} MW; domestic operating scale ~40 MW" if g.ratio is not None else "Grid constraint"),
             self.T("하이퍼스케일 규모 · 버지니아 상업용 판매 성장(EIA)", "Hyperscale scale; Virginia commercial sales growth (EIA)")],
        ]
        c3 = Cell(title=self.T("한국은 20MW씩 나눠 짓고, 미국은 100MW를 한 번에 — 같은 엔진, 다른 파라미터",
                               "Korea builds in 20 MW steps, the U.S. in one 100 MW block — same engine, different parameters"),
                  src=["grid", "law", "ecos", "fred", "eia"],
                  table=TableSpec(["", self.T("케이스 A (메인)", "Case A (main)"), self.T("케이스 B (비교)", "Case B (comparison)")], rows3,
                                  [0.2, 0.42, 0.38], ["L", "L", "L"], shade_rows={1}, font_size=8.4),
                  note=self.T("실존 프로젝트 아님. 기준금리는 2026-10-20 이전 최근 영업일 값", "Not real projects. Base rates: latest business day on or before 2026-10-20"))
        if g.ratio is not None:
            c4 = Cell(title=self.T(f"수도권 1단계 계통 신청의 {self.pct(g.ratio)}만 최종 승인 — 2단계를 '옵션'으로 둔 이유",
                                   f"Only {self.pct(g.ratio)} of phase-1 grid applications approved — why phase 2 is an option"),
                      src=["grid"], legend=[(c["warm_grey_light"], self.T("신청", "Applied")), (c["gold"], self.T("최종 승인", "Approved"))], unit="MW",
                      chart_key="grid", chart=charts.hbars([self.T("신청", "Applied"), self.T("최종 승인", "Approved")], [g.applied, g.approved],
                                                           [c["warm_grey_light"], c["gold"]], c, lambda v: f"{v:,.0f}"),
                      note=self.T(f"{g.period}. 비율 = 승인 ÷ 신청 (KSJ Research 계산). {thr:.0f}MW 이상은 전력계통영향평가 대상",
                                  f"{g.period}. Ratio = approved ÷ applied (KSJ Research). Projects ≥{thr:.0f} MW need a grid impact assessment"))
        else:
            c4 = self.pending(self.T("계통 신청·승인", "Grid applications and approvals"), ["grid"], Unavailable("계통 통계 없음", "Grid data missing"))
        title = self.T("구조: 장기 책임임대 + 전력비 패스스루 SPC — 한국은 20MW 확정 + 20MW 옵션, 미국은 100MW 단일",
                       "Structure: an SPC with long-term committed leases and power pass-through — Korea 20 MW + 20 MW option, U.S. 100 MW")
        sub = self.T(f"케이스 A(메인) 수도권 외곽 40MW · 원화, 케이스 B(비교) 버지니아 100MW · 달러 — " + (self.grid_sentence() or ""),
                     f"Case A (main) 40 MW outer Seoul metro, KRW; Case B (comparison) 100 MW Virginia, USD — " + (self.grid_sentence() or ""))
        return Page("body", "1", title, sub, [c1, c2, c3, c4])

    # --- p2 Vol.1 데이터 연결 -----------------------------------------------
    def p2(self) -> Page:
        c, d, r, pp, va = self.c, self.f.demand, self.f.rates, self.f.peers, self.f.va
        cells = []
        pre = self.A("prelease").value
        stab = self.A("stabilized_occupancy").value
        if ok(d) and pre is not None:
            from src.analysis.pf_model import occupancy_path
            n = 20
            k = float(self.A("ramp_elasticity").value or 1.0)
            cap = stab if stab is not None else 1.0
            yrs = list(range(1, n + 1))
            cols = {"downside": c["warm_grey"], "base": c["gold"], "upside": c["brown_dark"]}
            series = [(self.scen(s), list(occupancy_path(pre, cap, d.growth[s], k, n) * 100), cols[s], 2.2 if s == "base" else 1.4)
                      for s in SCENARIOS]
            ly = self.lease_up_years()
            cells.append(Cell(
                title=self.T(f"시장 수요 성장만큼 채우면 사전 임대율 {self.pct(pre)}에서 만실까지 기준 {self.yrs(ly)} — 대주는 계약된 임대료를 본다",
                             f"Filling at market growth, pre-lease {self.pct(pre)} reaches full in {self.yrs(ly)} (base) — lenders count contracted rent"),
                src=["iea", "market"], legend=[(cols[s], f"{self.scen(s)} {self.pct(d.growth[s])}") for s in SCENARIOS],
                unit=self.T("가동률 %, COD 후 연차", "Occupancy %, years after COD"), chart_key="ramp",
                chart=charts.lines(yrs, series, c, lambda v: f"{v:.0f}%", right=0.84),
                note=self.T(f"성장률 = IEA 데이터센터 전력 {d.years[0]}→{d.years[1]} 연평균({self.num(d.values['base_year'])}→하단 {self.num(d.values['downside'])}·기준 {self.num(d.values['base'])}·상단 {self.num(d.values['upside'])}TWh). "
                            f"가동률 = 사전 임대율 × (1+성장률)^t" + ("" if stab is not None else ", 안정화 가동률 근거 확인 전 100% 상한"),
                            f"Growth = IEA data-centre power CAGR {d.years[0]}→{d.years[1]} ({self.num(d.values['base_year'])}→low {self.num(d.values['downside'])}, base {self.num(d.values['base'])}, high {self.num(d.values['upside'])} TWh). "
                            "Occupancy = pre-lease × (1+growth)^t" + ("" if stab is not None else "; capped at 100% until stabilised occupancy is sourced"))))
        else:
            cells.append(self.pending(self.T("수요 → 가동률 램프업", "Demand → occupancy ramp-up"), ["iea"], d if not ok(d) else Unavailable("", "", ["prelease"])))
        if ok(r) and not r.monthly.empty:
            m = r.monthly
            sp = self.rate_spread()
            cells.append(Cell(
                title=self.T(f"기준금리({r.ktb_date}): 국고채 3년 {r.ktb_3y:.2f}%·10년 {r.ktb_10y:.2f}%, 미 국채 10년 {r.dgs10:.2f}% — 미국이 {sp:.2f}%p 높다",
                             f"Base rates ({r.ktb_date}): KTB 3y {r.ktb_3y:.2f}%, 10y {r.ktb_10y:.2f}%; UST 10y {r.dgs10:.2f}% — {sp:.2f}pp higher"),
                src=["ecos", "fred"], legend=[(c["brown_mid"], self.T("국고채 3년", "KTB 3y")), (c["brown_dark"], self.T("국고채 10년", "KTB 10y")),
                                              (c["gold"], self.T("미 국채 10년", "UST 10y"))], unit=self.T("% (월평균)", "% (monthly avg.)"),
                chart_key="rates",
                chart=charts.ts_lines(list(m["month"]), [(self.T("국고채 3년", "KTB 3y"), list(m["ktb_3y"]), c["brown_mid"], 1.4),
                                                        (self.T("국고채 10년", "KTB 10y"), list(m["ktb_10y"]), c["brown_dark"], 1.6),
                                                        (self.T("미 국채 10년", "UST 10y"), list(m["DGS10"]), c["gold"], 2.2)], c,
                                      lambda v: f"{v:.2f}%", end_values=[r.ktb_3y, r.ktb_10y, r.dgs10]),
                note=self.T(f"선 = 월평균, 끝 라벨 = 기준일 값. 모델 기준금리: 한국 = 건설 국고채 3년·운영 국고채 10년, 미국 = DGS10 ({r.dgs10_date}). 가산금리는 별도 가정",
                            f"Lines = monthly averages; end labels = as-of values. Model base rates: Korea = KTB 3y (construction), 10y (term); U.S. = DGS10 ({r.dgs10_date}). Margins are separate")))
        else:
            cells.append(self.pending(self.T("기준금리", "Base rates"), ["ecos", "fred"], r if not ok(r) else Unavailable("", "")))
        if ok(pp):
            t = pp.table
            names = [r_["company"] if self.kr else r_["company_en"] for _, r_ in t.iterrows()] + [self.T("3사 합산", "3 combined")]
            o0 = [x * 100 for x in t["opm0"]] + [pp.agg_opm0 * 100]
            o1 = [x * 100 for x in t["opm1"]] + [pp.agg_opm1 * 100]
            imp = [f"+{x * 100:.1f}%" for x in t["implied"]] + [f"+{pp.agg_implied * 100:.1f}%"]
            sc = pp.scenarios()
            cells.append(Cell(
                title=self.T(f"피어 영업이익률 {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)} — 모두 가격이라면 전력기기 가격 +{sc['mid'] * 100:.1f}%({sc['low'] * 100:.1f}~{sc['high'] * 100:.1f}%)",
                             f"Peer margins {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)} — if all price, equipment +{sc['mid'] * 100:.1f}% ({sc['low'] * 100:.1f}–{sc['high'] * 100:.1f}%)"),
                src=["dart"], legend=[(c["warm_grey_light"], pp.fy0), (c["gold"], pp.fy1)], unit=self.T("영업이익률 %, 오른쪽 = 함의 가격 상승률", "OPM %, right = implied price rise"),
                chart_key="opm",
                chart=charts.grouped(names, [(pp.fy0, o0, c["warm_grey_light"]), (pp.fy1, o1, c["gold"])], c, lambda v: f"{v:.1f}%",
                                     horizontal=True, extra_labels=imp),
                note=self.T("함의 가격 상승률 = (1 − 시작 이익률) ÷ (1 − 끝 이익률) − 1: 단위 원가 불변·이익률 상승 전부가 가격일 때의 상한값. 물량·환율·제품 구성 효과를 구분하지 않는다 — 인과가 아니라 스트레스 근거",
                            "Implied rise = (1 − start OPM) ÷ (1 − end OPM) − 1: an upper bound if unit costs were flat and all margin gain came from price. Volume, FX and mix are not separated — evidence for a stress, not causation")))
        else:
            cells.append(self.pending(self.T("피어 영업이익률", "Peer margins"), ["dart"], pp))
        if ok(va):
            y, p = va.price_latest
            who = self.T("버지니아", "Virginia") if va.price_source == "VA" else self.T("미국", "U.S.")
            yrs_ = list(va.index["period"].astype(int))
            cells.append(Cell(
                title=self.T(f"버지니아 상업용 전력 판매 연 {self.pct(va.va_cagr)}(미국 {self.pct(va.us_cagr)}) — {who} 상업용 요금 {p:.2f}¢/kWh({y})",
                             f"Virginia commercial sales {self.pct(va.va_cagr)}/yr (U.S. {self.pct(va.us_cagr)}) — {who} commercial price {p:.2f}¢/kWh ({y})"),
                src=["eia"], legend=[(c["gold"], self.T("버지니아", "Virginia")), (c["warm_grey"], self.T("미국 전체", "U.S. total"))],
                unit=self.T(f"판매량 지수 ({va.base_year}=100)", f"Sales index ({va.base_year}=100)"), chart_key="va",
                chart=charts.lines(yrs_, [(self.T("버지니아", "VA"), list(va.index["VA"]), c["gold"], 2.2),
                                          (self.T("미국", "U.S."), list(va.index["US"]), c["warm_grey"], 1.5)], c, lambda v: f"{v:.0f}", ref=100),
                note=self.T(f"케이스 B 수요 근거(버지니아 {va.last_year}년 전년 대비 {self.pct(va.va_yoy_last, 1, True)}). 전력비 민감도 단가 = {who} 상업용 평균 요금"
                            + ("" if va.price_source == "VA" else "(버지니아 요금 수집 전 대용치)"),
                            f"Demand evidence for Case B (Virginia {va.last_year} {self.pct(va.va_yoy_last, 1, True)} y/y). Power-cost sensitivity uses the {who} commercial average price"
                            + ("" if va.price_source == "VA" else " (proxy until the Virginia price is collected)"))))
        else:
            cells.append(self.pending(self.T("버지니아 전력", "Virginia power"), ["eia"], va))
        d_ok = ok(d)
        title = self.T(f"Vol.1 데이터를 PF 가정으로: 수요 성장 {self.pct(d.growth['base'])}(기준), 미 국채가 국고채보다 {self.rate_spread():.2f}%p 높고, 피어 이익률은 가격 결정력을 시사"
                       if d_ok and self.rate_spread() is not None else "Vol.1 데이터를 PF 가정으로 연결",
                       f"Vol.1 data into PF inputs: base demand growth {self.pct(d.growth['base'])}, UST {self.rate_spread():.2f}pp above KTB, peer margins point to pricing power"
                       if d_ok and self.rate_spread() is not None else "Linking Vol.1 data to PF inputs")
        sub = self.T("수요(IEA) → 가동률 램프업 · 금리(ECOS·FRED) → 기준금리 · 피어 이익률(DART) → CAPEX 스트레스 · 버지니아(EIA) → 케이스 B 수요·전력비",
                     "Demand (IEA) → ramp-up · rates (ECOS, FRED) → base rates · peer margins (DART) → CAPEX stress · Virginia (EIA) → Case B demand and power")
        return Page("body", "2", title, sub, cells)

    @staticmethod
    def num(v: float, d: int = 0) -> str:
        return f"{v:,.{d}f}"

    # --- p3 케이스 A 대출 한도 ----------------------------------------------
    def p3(self) -> Page:
        a = self.case("A")
        if not ok(a):
            u = a
            title = self.T("케이스 A 대출 한도: 공사비·운영비·금융 조건의 근거를 확인한 뒤 산출한다",
                           "Case A debt sizing: computed once cost, OPEX and financing terms are sourced")
            sub = self.T(f"엔진은 준비됨 — 임대료 kW당 월 {self.A('rent_per_kw_month').value:,.0f}원, 사전 임대율 {self.prelease_range()}(기준 {self.pct(self.A('prelease').value)}), 국고채 10년 기준",
                         f"Engine ready — rent KRW {self.A('rent_per_kw_month').value:,.0f}/kW-month, pre-lease {self.prelease_range()} (base {self.pct(self.A('prelease').value)}), KTB 10y base")
            cells = [self.pending(t, ["ksj"], u) for t in (
                self.T("CFADS와 원리금, DSCR", "CFADS, debt service and DSCR"), self.T("대출 한도: sculpting vs 최대 대출 비율", "Debt: sculpting vs gearing cap"),
                self.T("상환 Waterfall", "Repayment waterfall"), self.T("수요 시나리오별 결과", "Results by demand scenario"))]
            return Page("body", "3", title, sub, cells)
        return Page("body", "3", *self.sizing_page("A", a))

    def sizing_page(self, case: str, a: CaseResult):
        c, b, inp = self.c, a.base, a.inp
        o = b.ops
        n_show = min(inp.operating_years, inp.tenor_years + 2)
        yrs = list(o["year"][:n_show])
        mfmt = (lambda v: f"{v:,.0f}") if case == "A" else (lambda v: f"{v:,.0f}")
        unit = self.v["cases"][case]["money_unit_kr" if self.kr else "money_unit_en"]
        c1 = Cell(title=self.T(f"CFADS ÷ 목표 DSCR {inp.target_dscr:.2f}배로 원리금을 깎으면 대출 한도 {self.money(case, b.sculpt_debt)}",
                               f"Sculpting debt service at CFADS ÷ {inp.target_dscr:.2f}x gives {self.money(case, b.sculpt_debt)}"),
                  src=["ksj"], legend=[(c["brown_mid"], "CFADS"), (c["gold"], self.T("원리금", "Debt service")), (c["charcoal"], "DSCR")],
                  unit=f"{unit}, " + self.T("COD 후 연차", "years after COD"), chart_key=f"cfads_{case}",
                  chart=charts.cfads_ds(yrs, list(o["cfads"][:n_show]), list(o["debt_service"][:n_show]), list(o["dscr"][:n_show]),
                                        c, inp.target_dscr, ("CFADS", self.T("원리금", "DS"), self.T("목표", "Target")), mfmt),
                  note=self.T(f"CFADS = EBITDA − 법인세. 거치 {inp.grace_years}년(이자 {'지급' if inp.grace_interest == 'paid' else '자본화'}), 만기 {inp.tenor_years}년. 기준 시나리오",
                              f"CFADS = EBITDA − tax. Grace {inp.grace_years} yrs (interest {inp.grace_interest}), tenor {inp.tenor_years} yrs. Base scenario"))
        cons = b.cons
        rows = [[self.T("Sculpting 한도 (목표 DSCR)", "Sculpting limit (target DSCR)"), self.money(case, b.sculpt_debt)],
                [self.T(f"최대 대출 비율 한도 ({self.pct(inp.max_gearing, 0)})", f"Gearing limit ({self.pct(inp.max_gearing, 0)})"), self.money(case, b.gearing_debt)],
                [self.T("채택 대출 한도 (작은 값)", "Debt adopted (lower)"), self.money(case, b.debt)],
                [self.T("구속 조건 · 유효 DSCR", "Binding constraint · effective DSCR"), f"{self.binding_text(b)} · {self.x(b.effective_dscr)}"],
                [self.T("총사업비 = CAPEX + 건설이자 + 초기 DSRA", "Total cost = CAPEX + IDC + initial DSRA"),
                 f"{self.money(case, cons.uses)} = {self.money(case, cons.capex)} + {self.money(case, cons.idc)} + {self.money(case, cons.dsra_initial)}"],
                [self.T("자기자본 · 대출 비율", "Equity · gearing"), f"{self.money(case, cons.equity)} · {self.pct(b.gearing)}"],
                [self.T("최소 · 평균 DSCR · LLCR", "Min · avg DSCR · LLCR"), f"{self.x(b.min_dscr)} · {self.x(b.avg_dscr)} · {self.x(b.llcr)}"],
                [self.T("Project IRR · Equity IRR · 회수기간(FC 기준)", "Project IRR · equity IRR · payback (from FC)"),
                 f"{self.pct(b.project_irr)} · {self.pct(b.equity_irr)} · {self.yrs(b.payback_years)}"]]
        c2 = Cell(title=self.T(f"대출 한도 {self.money(case, b.debt)} — {self.binding_text(b)}", f"Debt {self.money(case, b.debt)} — {self.binding_text(b)}"),
                  src=["ksj"], table=TableSpec([self.T("항목", "Item"), self.T("값", "Value")], rows, [0.48, 0.52], ["L", "R"],
                                               shade_rows={2}, gold_cells={(2, 1)}, font_size=8.4),
                  note=self.T("대출 한도 = min(sculpting, 최대 대출 비율 × 총사업비). 총사업비에 건설이자(IDC)·초기 DSRA 포함, IDC는 반복 계산",
                              "Debt = min(sculpting, max gearing × total cost); cost includes IDC and initial DSRA, solved iteratively"))
        pick = sorted({1, 2, 3, min(5, inp.tenor_years), min(10, inp.tenor_years), inp.tenor_years})
        wrows = []
        for y in pick:
            r_ = o.iloc[y - 1]
            dist = mfmt(r_["distribution"])
            if r_["lockup_in"] > 0:
                dist = self.T(f"0 (잠금 {mfmt(r_['lockup_in'])})", f"0 (locked {mfmt(r_['lockup_in'])})")
            wrows.append([str(y), mfmt(r_["cfads"]), mfmt(r_["interest"]), mfmt(r_["principal"]),
                          mfmt(r_["dsra_topup"] - r_["dsra_draw"] - r_["dsra_release"]), dist, self.x(r_["dscr"])])
        c3 = Cell(title=self.T(f"상환 Waterfall: CFADS → 이자 → 원금 → DSRA({inp.dsra_months:.0f}개월) → 배당",
                               f"Waterfall: CFADS → interest → principal → DSRA ({inp.dsra_months:.0f} months) → distributions"),
                  src=["ksj"], unit=unit,
                  table=TableSpec([self.T("연차", "Year"), "CFADS", self.T("이자", "Interest"), self.T("원금", "Principal"),
                                   self.T("DSRA 순적립", "DSRA net"), self.T("배당", "Distrib."), "DSCR"], wrows,
                                  [0.1, 0.16, 0.14, 0.14, 0.16, 0.16, 0.14], ["C", "R", "R", "R", "R", "R", "R"], font_size=8.2),
                  note=self.T("DSRA 목표 = 다음 해 원리금 × 개월/12, 만기 해에 해제. 이자 자본화 거치기간의 배당은 잠갔다가 거치 종료 다음 해에 해제. 원금 음수 = 원리금 < 이자(잔액 증가)",
                              "DSRA target = next year's debt service × months/12, released at maturity. Distributions are locked while interest is capitalised and released after grace. Negative principal = debt service below interest"))
        srows = []
        for s in SCENARIOS:
            r_ = a.scenarios[s]
            srows.append([f"{self.scen(s)} ({self.pct(r_.inp.ramp_growth)})", self.money(case, r_.debt), self.x(r_.min_dscr), self.x(r_.llcr),
                          self.pct(r_.project_irr), self.pct(r_.equity_irr), self.x(r_.min_dscr_contracted)])
        c4 = Cell(title=self.T(f"수요 시나리오별 대출 한도 {self.money(case, a.scenarios['downside'].debt)}~{self.money(case, a.scenarios['upside'].debt)}",
                               f"Debt by demand scenario: {self.money(case, a.scenarios['downside'].debt)}–{self.money(case, a.scenarios['upside'].debt)}"),
                  src=["iea", "ksj"],
                  table=TableSpec([self.T("시나리오(성장률)", "Scenario (growth)"), self.T("대출 한도", "Debt"), self.T("최소 DSCR", "Min DSCR"), "LLCR",
                                   "Project IRR", "Equity IRR", self.T("계약분 DSCR", "Contracted DSCR")], srows,
                                  [0.2, 0.17, 0.12, 0.1, 0.13, 0.13, 0.15], ["L", "R", "R", "R", "R", "R", "R"], shade_rows={1}, font_size=8.2),
                  note=self.T("시나리오마다 대출을 다시 산정(sizing). 계약분 DSCR = 사전 임대 계약 임대료만으로 본 최소 DSCR",
                              "Debt re-sized per scenario. Contracted DSCR = min DSCR on pre-leased rent only"))
        title = self.T(f"{self.name(case)} 대출 한도 {self.money(case, b.debt)}(총사업비의 {self.pct(b.gearing, 0)}) — {self.binding_text(b)}",
                       f"{self.name(case)} debt capacity {self.money(case, b.debt)} ({self.pct(b.gearing, 0)} of cost) — {self.binding_text(b)}")
        sub = self.T(f"최소 DSCR {self.x(b.min_dscr)} · LLCR {self.x(b.llcr)} · Equity IRR {self.pct(b.equity_irr)} — 계약 임대료만으로는 최소 DSCR {self.x(b.min_dscr_contracted)}",
                     f"Min DSCR {self.x(b.min_dscr)} · LLCR {self.x(b.llcr)} · equity IRR {self.pct(b.equity_irr)} — on contracted rent only, min DSCR {self.x(b.min_dscr_contracted)}")
        return title, sub, [c1, c2, c3, c4]

    # --- p4 민감도·스트레스 ---------------------------------------------------
    VAR_KR = {"rent": "임대료 ±10%", "occupancy": "가동률 ±10%", "rate": "금리 ±100bp", "delay": "건설 지연", "prelease": "사전 임대율",
              "capex": "CAPEX(전력기기 가격)"}
    VAR_EN = {"rent": "Rent ±10%", "occupancy": "Occupancy ±10%", "rate": "Rates ±100bp", "delay": "Construction delay",
              "prelease": "Pre-lease ratio", "capex": "CAPEX (equipment prices)"}
    BE_KR = {"rent_mult": "임대료 (기준 대비)", "occ_mult": "가동률 (기준 대비)", "prelease": "사전 임대율", "capex_mult": "CAPEX (기준 대비)",
             "rate_shift": "기준금리 변화", "delay_quarters": "건설 지연"}
    BE_EN = {"rent_mult": "Rent (vs base)", "occ_mult": "Occupancy (vs base)", "prelease": "Pre-lease ratio", "capex_mult": "CAPEX (vs base)",
             "rate_shift": "Base-rate change", "delay_quarters": "Construction delay"}

    def be_fmt(self, var: str, v: float | None, inp) -> str:
        if v is None:
            return self.T("범위 내 없음", "none in range")
        if var in ("rent_mult", "occ_mult", "capex_mult"):
            return f"{(v - 1) * 100:+.0f}%"
        if var == "prelease":
            return self.pct(v)
        if var == "rate_shift":
            return f"{v * 10000:+.0f}bp"
        return self.T(f"+{v:.0f}분기", f"+{v:.0f} qtrs")

    def p4(self) -> Page:
        a, b, c = self.case("A"), self.case("B"), self.c
        sc = self.v["sensitivity"]
        if not ok(a):
            cells = [self.pending(t, ["ksj"], a) for t in (
                self.T("토네이도: 최소 DSCR", "Tornado: min DSCR"), self.T("손익분기 값 (DSCR 1.0배·목표)", "Breakevens (DSCR 1.0x and target)"),
                self.T("DSCR 히트맵: 임대료 × CAPEX", "DSCR heatmap: rent × CAPEX"))]
        else:
            t = a.tornado
            vn = self.VAR_KR if self.kr else self.VAR_EN
            rows = [(vn[r_["variable"]], r_["low"], r_["high"]) for _, r_ in t.iterrows()]
            top = t.iloc[0]
            tt = a.tax_timing
            tt_note = self.T(f" 유리한 쪽이 기준보다 낮은 {', '.join(vn[v] for v in tt)}: 이익 증가로 이월결손금이 일찍 소진돼 특정 연도 법인세가 늘어난 효과(세율 0으로 재계산 시 사라짐 확인)" if tt else "",
                             f" Where the favourable side is below base ({', '.join(vn[v] for v in tt)}): higher profit uses up loss carryforwards sooner, raising tax in a sculpted year (disappears when re-run at a 0% tax rate)" if tt else "")
            c1 = Cell(title=self.T(f"최소 DSCR을 가장 크게 흔드는 변수는 {vn[top['variable']]} ({self.x(top['low'])}~{self.x(top['high'])})",
                                   f"{vn[top['variable']]} moves min DSCR the most ({self.x(top['low'])}–{self.x(top['high'])})"),
                      src=["ksj", "dart"], legend=[(c["brick"], self.T("불리", "Adverse")), (c["brown_mid"], self.T("유리", "Favourable"))],
                      unit=self.T(f"최소 DSCR (기준 {self.x(a.base.min_dscr)})", f"Min DSCR (base {self.x(a.base.min_dscr)})"), chart_key="tornado_A",
                      chart=charts.tornado(rows, a.base.min_dscr, c, lambda v: f"{v:.2f}", ref=1.0, ref_label="1.0x"),
                      note=self.T(f"대출 스케줄은 기준 케이스로 고정. 건설 지연 = +{max(sc['delay_quarters'])}분기, 사전 임대율 = {self.prelease_range()}, CAPEX = 전력설비 비중 × 피어 함의 가격 상승률(고).",
                                  f"Debt schedule fixed at base. Delay = +{max(sc['delay_quarters'])} quarters; pre-lease {self.prelease_range()}; CAPEX = equipment share × peer-implied price rise (high).") + tt_note)
            bn = self.BE_KR if self.kr else self.BE_EN
            be = a.breakeven
            brow = []
            for var in bn:
                v1 = be[(be["variable"] == var) & (be["level"] == 1.0)]["value"].iloc[0]
                rt = be[(be["variable"] == var) & (be["level"] == a.inp.target_dscr)].iloc[0]
                vt = rt["value"]
                base_v = {"prelease": self.pct(a.inp.prelease), "rate_shift": self.T("0bp", "0bp"), "delay_quarters": self.T("0분기", "0 qtrs")}.get(var, "0%")
                tcol = self.T("기준 = 목표", "base = target") if rt.get("at_target") else self.be_fmt(var, vt if vt == vt else None, a.inp)
                brow.append([bn[var], base_v, tcol, self.be_fmt(var, v1 if v1 == v1 else None, a.inp)])
            c2 = Cell(title=self.T(f"최소 DSCR이 목표({a.inp.target_dscr:.2f}배)·1.0배 밑으로 내려가는 손익분기 값", f"Breakevens where min DSCR falls below target ({a.inp.target_dscr:.2f}x) and 1.0x"),
                      src=["ksj"], table=TableSpec([self.T("변수", "Variable"), self.T("기준", "Base"), self.T(f"목표 {a.inp.target_dscr:.2f}배", f"Target {a.inp.target_dscr:.2f}x"),
                                                    self.T("1.0배", "1.0x")], brow, [0.34, 0.18, 0.24, 0.24], ["L", "R", "R", "R"],
                                                   gold_cells={(i, 3) for i in range(len(brow))}, font_size=8.6),
                      note=self.T("한 변수만 움직이고 나머지는 기준값. 대출 스케줄 고정(추가 CAPEX·지연 이자는 기준 대출 비율로 조달). 교차가 여럿이면 기준값에 가장 가까운 값. "
                                  "'기준 = 목표' = 목표 DSCR로 원리금을 깎아(sculpting) 기준 최소 DSCR이 이미 목표와 같음. '범위 내 없음' = 탐색 구간에서 교차 없음",
                                  "One variable at a time; debt schedule fixed (extra CAPEX and delay interest funded at base gearing); nearest crossing to base. "
                                  "'Base = target': sculpting already sets base min DSCR at target. 'None in range': no crossing in the search range"))
            hm = a.heatmap
            rlab = [f"{(r_ - 1) * 100:+.0f}%" for r_ in hm.index]
            clab = [f"{(c_ - 1) * 100:+.0f}%" for c_ in hm.columns]
            c3 = Cell(title=self.T("임대료 −10%와 CAPEX +20%가 겹치면 최소 DSCR " + self.x(float(hm.loc[0.9, 1.2])) if 0.9 in hm.index and 1.2 in hm.columns else "DSCR 히트맵",
                                   "Rent −10% with CAPEX +20%: min DSCR " + self.x(float(hm.loc[0.9, 1.2])) if 0.9 in hm.index and 1.2 in hm.columns else "DSCR heatmap"),
                      src=["ksj"], legend=[(c["brick"], self.T("1.0배 미만", "Below 1.0x")), (c["warm_grey_light"], self.T("1.0배~목표", "1.0x–target")),
                                           (c["gold"], self.T("목표 이상", "At/above target"))], unit=self.T("최소 DSCR", "Min DSCR"), chart_key="heatmap_A",
                      chart=charts.heatmap(hm.to_numpy(dtype=float), rlab, clab, c, (1.0, a.inp.target_dscr),
                                           self.T("CAPEX (기준 대비)", "CAPEX (vs base)"), self.T("임대료 (기준 대비)", "Rent (vs base)")),
                      note=self.T("추가 CAPEX는 기준 대출 비율로 조달(대출·원금 스케줄 비례 확대)" + (
                                      ". 임대료↑·CAPEX↓ 칸이 기준보다 낮은 것은 감가상각·이월결손금 변화로 특정 연도 법인세가 늘어난 효과(세율 0 재계산으로 확인)"
                                      if a.heatmap_tax_timing else ""),
                                  "Extra CAPEX funded at base gearing (debt and principal scaled)" + (
                                      ". Cells with higher rent or lower CAPEX below base reflect higher tax in a sculpted year from depreciation and loss-carryforward timing (confirmed at a 0% tax rate)"
                                      if a.heatmap_tax_timing else "")))
            cells = [c1, c2, c3]
        if ok(b):
            vn = self.VAR_KR if self.kr else self.VAR_EN
            rows = [[vn[r_["variable"]], self.x(r_["low"]), self.x(r_["high"])] for _, r_ in b.tornado.iterrows()]
            cells.append(Cell(title=self.T(f"케이스 B 요약: 최소 DSCR {self.x(b.base.min_dscr)}, 가장 민감한 변수 {vn[b.tornado.iloc[0]['variable']]}",
                                           f"Case B summary: min DSCR {self.x(b.base.min_dscr)}; most sensitive: {vn[b.tornado.iloc[0]['variable']]}"),
                              src=["ksj"], table=TableSpec([self.T("변수", "Variable"), self.T("불리", "Adverse"), self.T("유리", "Favourable")], rows,
                                                           [0.5, 0.25, 0.25], ["L", "R", "R"], font_size=8.6),
                              note=self.T("같은 스트레스를 케이스 B에 적용 (대출 스케줄 고정)", "Same stresses applied to Case B (debt schedule fixed)")))
        else:
            cells.append(self.pending(self.T("케이스 B 스트레스 요약", "Case B stress summary"), ["ksj"], b))
        if ok(a):
            top = a.tornado.iloc[0]
            vn = self.VAR_KR if self.kr else self.VAR_EN
            title = self.T(f"스트레스: {josa(vn[top['variable']])} 최소 DSCR을 가장 크게 흔든다 — 기준 {self.x(a.base.min_dscr)}",
                           f"Stress: {vn[top['variable']].lower()} moves min DSCR the most — base {self.x(a.base.min_dscr)}")
        else:
            title = self.T("스트레스: 임대료·가동률·사전 임대율·CAPEX·금리(±100bp)·건설 지연 — 입력 확인 후 손익분기를 계산한다",
                           "Stress: rent, occupancy, pre-lease, CAPEX, rates (±100bp), delay — breakevens computed once inputs are sourced")
        sub = self.T("케이스 A 중심, B는 요약 · 손익분기 = 최소 DSCR 1.0배·목표 DSCR 경계 · 토네이도 · 히트맵(임대료 × CAPEX)",
                     "Case A in full, Case B summarised · breakevens at min DSCR 1.0x and target · tornado · heatmap (rent × CAPEX)")
        return Page("body", "4", title, sub, cells)

    # --- p5 실물옵션 ----------------------------------------------------------
    def p5(self) -> Page:
        op, c, g = self.f.option, self.c, self.f.grid
        tree = Cell(title=self.T("의사결정 구조: 계통 승인(확률 p) → 임대료·수요 관측 → 지금 착공 또는 대기", "Decision structure: grid approval (p) → observe rent and demand → build now or wait"),
                    src=["ksj"], panel_lead=self.T("2단계 20MW = 계통 승인과 임차 수요 확인을 기다릴 수 있는 권리", "Phase 2 (20 MW) = the right to wait for grid approval and demand"),
                    bullets=[self.T("불확실성 ① 추가 계통 승인: 결정 시점에 확률 p로 승인 — 미승인이면 가치 0", "Uncertainty ①: grid approval with probability p at the decision date; zero value if refused"),
                             self.T("불확실성 ② 임대료: 기하 브라운 운동(기대 증가율 = 연 인상률, 변동성 σ)", "Uncertainty ②: rent follows geometric Brownian motion (drift = escalation, volatility σ)"),
                             self.T("불확실성 ③ 수요: IEA 하단·기준·상단 성장률을 경로마다 추첨 — 1단계 가동률로 관측", "Uncertainty ③: demand path drawn from IEA low/base/high growth — observed via phase 1 occupancy"),
                             self.T("2단계 사전 임대율 = 결정 연도의 1단계 가동률 (임차 수요 확인 후 착공)", "Phase 2 pre-lease = phase 1 occupancy in the decision year (build after demand is confirmed)"),
                             self.T("평가: 몬테카를로 + LSM(최소제곱 회귀로 '기다림'의 가치 추정), seed 고정·경로 수별 수렴 확인", "Valuation: Monte Carlo + LSM (least-squares continuation value), fixed seed, convergence by path count")],
                    note=self.T("무차입 NPV 기준 (자기자본 할인율). 옵션 가치 = p × 승인 조건부 가치", "Unlevered NPV at the equity discount rate. Option value = p × value given approval"))
        if not ok(op):
            cells = [self.pending(t, ["ksj", "grid"], op) for t in (
                self.T("승인 확률별 옵션 가치", "Option value by approval probability"), self.T("지금 짓기 vs 기다리기", "Build now vs wait"),
                self.T("몬테카를로 수렴", "Monte Carlo convergence"))] + [tree]
            title = self.T(f"2단계 20MW는 '옵션' — 승인 확률별 가치와 착공 임계 임대료는 입력 확인 후 계산 (참고: 1단계 승인 비율 {self.pct(g.ratio)})"
                           if g.ratio is not None else "2단계 20MW는 '옵션' — 입력 확인 후 계산",
                           f"Phase 2 (20 MW) is an option — values and trigger rent computed once inputs are sourced (ref.: phase-1 approval {self.pct(g.ratio)})"
                           if g.ratio is not None else "Phase 2 (20 MW) is an option — computed once inputs are sourced")
            sub = self.T("불확실성: 추가 계통 승인(확률) · 임대료(확률과정) · 수요(IEA 시나리오) — LSM 몬테카를로, seed 고정",
                         "Uncertainty: grid approval (probability), rent (stochastic), demand (IEA scenarios) — LSM Monte Carlo, fixed seed")
            return Page("body", "5", title, sub, cells)
        r, oi = op.result, op.inputs
        bp = r.by_prob
        c1 = Cell(title=self.T(f"옵션 가치는 승인 확률에 비례: p = {self.pct(oi.approval_prob, 0)}에서 {self.money('A', r.value)}",
                               f"Option value scales with approval probability: {self.money('A', r.value)} at p = {self.pct(oi.approval_prob, 0)}"),
                  src=["ksj", "grid"], legend=[(c["gold"], self.T("옵션 가치", "Option value"))], unit=self.T("억원 (1단계 COD 시점)", "KRW 100mn (at phase-1 COD)"),
                  chart_key="opt_prob",
                  chart=charts.xy([(self.T("옵션 가치", "Option"), list(bp["approval_prob"] * 100), list(bp["value"]), c["gold"])], c,
                                  lambda v: f"{v:.0f}%", lambda v: f"{v:,.0f}",
                                  vline=(g.ratio * 100, self.T(f"1단계 승인 비율 {self.pct(g.ratio)}", f"Phase-1 approval {self.pct(g.ratio)}")) if g.ratio else None),
                  note=self.T("승인 여부는 다른 불확실성과 독립 가정 → 가치 = p × 승인 조건부 가치(선형)", "Approval assumed independent → value = p × conditional value (linear)"))
        crit = r.critical_rent
        rows = [[self.T("지금 짓기 (승인 즉시 착공)", "Build now (on approval)"), self.money("A", r.build_now)],
                [self.T("기다리기 (최적 착공, 옵션 가치)", "Wait (optimal timing, option value)"), self.money("A", r.value)],
                [self.T("유연성 가치 = 옵션 − max(지금, 0)", "Flexibility = option − max(now, 0)"), self.money("A", r.flexibility)]]
        for s in SCENARIOS:
            v = crit.get(s)
            rows.append([self.T(f"착공 임계 임대료 ({self.scen(s)})", f"Trigger rent ({self.scen(s)})"),
                         self.T(f"{v:,.0f}원/kW·월", f"KRW {v:,.0f}/kW-mo") if v else self.T("결정 시점 착공 없음", "no build at decision date")])
        be = r.breakeven_rent.get("base")
        rows.append([self.T("NPV = 0 임대료 (기준)", "NPV-zero rent (base)"), self.T(f"{be:,.0f}원/kW·월", f"KRW {be:,.0f}/kW-mo") if be else "—"])
        rows.append([self.T("착공 경로 비율 · 평균 착공 연차", "Share of paths built · mean build year"),
                     f"{self.pct(r.exercise_share, 0)} · {self.yrs(r.mean_exercise_year)}"])
        c2 = Cell(title=self.T(f"기다림의 가치 {self.money('A', r.flexibility)} — 기준 시나리오 임계 임대료 {crit.get('base') or 0:,.0f}원 이상이면 바로 착공",
                               f"Value of waiting {self.money('A', r.flexibility)} — build at once above KRW {crit.get('base') or 0:,.0f} (base)"),
                  src=["ksj"], table=TableSpec([self.T("항목", "Item"), self.T("값", "Value")], rows, [0.56, 0.44], ["L", "R"],
                                               shade_rows={1}, gold_cells={(1, 1), (2, 1)}, font_size=8.4),
                  note=self.T(f"결정 시점 = 1단계 COD 후 {oi.decision_year}년, 대기 가능 {oi.window_years}년, 임대료 변동성 {self.pct(oi.rent_volatility, 0)}, 경로 {oi.n_paths:,}개, seed {oi.seed}",
                              f"Decision at year {oi.decision_year} after phase-1 COD; window {oi.window_years} yrs; rent vol. {self.pct(oi.rent_volatility, 0)}; {oi.n_paths:,} paths; seed {oi.seed}"))
        cv = r.convergence
        last = cv.iloc[-1]
        c3 = Cell(title=self.T(f"경로 {int(last['n_paths']):,}개에서 표준오차 {last['stderr'] / last['value_conditional'] * 100:.1f}% — 수렴 확인",
                               f"Standard error {last['stderr'] / last['value_conditional'] * 100:.1f}% at {int(last['n_paths']):,} paths — converged"),
                  src=["ksj"], legend=[(c["brown_dark"], self.T("승인 조건부 가치 ±1.96 표준오차", "Conditional value ±1.96 s.e."))],
                  unit=self.T("억원, 경로 수(로그)", "KRW 100mn; paths (log)"), chart_key="conv",
                  chart=charts.xy([(self.T("조건부 가치", "Conditional"), list(cv["n_paths"]), list(cv["value_conditional"]), c["brown_dark"])], c,
                                  lambda v: f"{v:,.0f}", lambda v: f"{v:,.0f}", band=list(cv["stderr"] * 1.96), logx=True,
                                  hline=float(last["value_conditional"])),
                  note=self.T("같은 seed로 경로 수만 늘려 재계산", "Recomputed with the same seed, increasing paths"))
        if r.build_now <= 0:
            title = self.T(f"2단계 20MW: 지금 지으면 {self.money('A', r.build_now)}, 기다리면 {self.money('A', r.value)} — 승인 확률 {self.pct(oi.approval_prob, 0)}에서 가치는 기다릴 권리에서 나온다",
                           f"Phase 2 (20 MW): build now {self.money('A', r.build_now)}, wait {self.money('A', r.value)} — at p = {self.pct(oi.approval_prob, 0)} the value lies in the right to wait")
        else:
            title = self.T(f"2단계 20MW: 기다릴 권리의 가치 {self.money('A', r.flexibility)} — 승인 확률 {self.pct(oi.approval_prob, 0)}에서 옵션 가치 {self.money('A', r.value)}",
                           f"Phase 2 (20 MW): the right to wait is worth {self.money('A', r.flexibility)} — option value {self.money('A', r.value)} at p = {self.pct(oi.approval_prob, 0)}")
        sub = self.T(f"지금 짓기 {self.money('A', r.build_now)} vs 기다리기 {self.money('A', r.value)} · 착공 경로 {self.pct(r.exercise_share, 0)} · 참고: 1단계 승인 비율 {self.pct(g.ratio)}",
                     f"Build now {self.money('A', r.build_now)} vs wait {self.money('A', r.value)} · built on {self.pct(r.exercise_share, 0)} of paths · ref.: phase-1 approval {self.pct(g.ratio)}")
        return Page("body", "5", title, sub, [c1, c2, c3, tree])

    # --- p6 한·미 비교 --------------------------------------------------------
    def p6(self) -> Page:
        a, b, r, g, c = self.case("A"), self.case("B"), self.f.rates, self.f.grid, self.c
        fx = self.f.fx()
        pend = self.T("입력 후 산출", "after inputs")

        def val(cr, fn):
            return fn(cr) if ok(cr) else pend
        sp = self.rate_spread()
        rows = [
            [self.T("용량 · 단계", "Capacity · phasing"), self.T("40MW (20 확정 + 20 옵션)", "40 MW (20 firm + 20 option)"), self.T("100MW 단일", "100 MW single")],
            [self.T("조달 통화 · 기준금리", "Currency · base rate"), f"KRW · {r.ktb_10y:.2f}%" if ok(r) else "KRW", f"USD · {r.dgs10:.2f}%" if ok(r) else "USD"],
            [self.T("가산금리", "Margin"), self.val_assump("A", "margin_bp"), self.val_assump("B", "margin_bp")],
            [self.T("대출 한도 (현지 통화)", "Debt (local currency)"), val(a, lambda x: self.money("A", x.base.debt)), val(b, lambda x: self.money("B", x.base.debt))],
            [self.T("대출 한도 (원화 환산)", "Debt (KRW)"), val(a, lambda x: self.krw(x.base.debt)), val(b, lambda x: self.krw(self.to_krw(x.base.debt)))],
            [self.T("MW당 대출 (원화)", "Debt per MW (KRW)"), val(a, lambda x: self.krw(x.base.debt_per_mw)), val(b, lambda x: self.krw(self.to_krw(x.base.debt_per_mw)))],
            [self.T("대출 비율 · 구속 조건", "Gearing · binding"), val(a, lambda x: f"{self.pct(x.base.gearing, 0)} · {x.base.binding.upper()}"),
             val(b, lambda x: f"{self.pct(x.base.gearing, 0)} · {x.base.binding.upper()}")],
            [self.T("최소 · 평균 DSCR", "Min · avg DSCR"), val(a, lambda x: f"{self.x(x.base.min_dscr)} · {self.x(x.base.avg_dscr)}"),
             val(b, lambda x: f"{self.x(x.base.min_dscr)} · {self.x(x.base.avg_dscr)}")],
            ["LLCR", val(a, lambda x: self.x(x.base.llcr)), val(b, lambda x: self.x(x.base.llcr))],
            ["Project IRR · Equity IRR", val(a, lambda x: f"{self.pct(x.base.project_irr)} · {self.pct(x.base.equity_irr)}"),
             val(b, lambda x: f"{self.pct(x.base.project_irr)} · {self.pct(x.base.equity_irr)}")],
            [self.T("핵심 병목", "Key bottleneck"),
             self.T(f"계통(승인 {self.pct(g.ratio)}) · 사전 임대율({self.prelease_range()})", f"Grid ({self.pct(g.ratio)} approved) · pre-leasing ({self.prelease_range()})"),
             self.T(f"규모(100MW, 한국 1단계의 5배) · 금리(+{sp:.2f}%p)" if sp is not None else "규모 · 금리",
                    f"Scale (100 MW, 5x Korea phase 1) · rates (+{sp:.2f}pp)" if sp is not None else "Scale · rates")],
        ]
        n = len(rows)
        c1 = Cell(title=self.T("대출 한도·DSCR·Equity IRR을 나란히 — 같은 엔진, 다른 병목", "Debt, DSCR and equity IRR side by side — same engine, different bottlenecks"),
                  src=["ecos", "fred", "grid", "market", "ksj"],
                  table=TableSpec(["", self.T("한국 40MW (케이스 A)", "Korea 40 MW (Case A)"), self.T("미국 100MW (케이스 B)", "U.S. 100 MW (Case B)")], rows,
                                  [0.26, 0.37, 0.37], ["L", "R", "R"], shade_rows={3, n - 1}, gold_cells={(n - 1, 1), (n - 1, 2)}, font_size=8.6),
                  note=self.T(f"원화 환산 = USD mn × ECOS 원/달러 {fx:,.1f}원({r.fx_date}) ÷ 100. 한국 대출 한도는 1단계 20MW 기준" if fx else "원화 환산 환율 데이터 없음",
                              f"KRW = USD mn × ECOS USD/KRW {fx:,.1f} ({r.fx_date}) ÷ 100. Korea debt is for phase 1 (20 MW)" if fx else "FX data missing"))
        if ok(a) and ok(b):
            vals = [self.to_krw(b.base.debt_per_mw), a.base.debt_per_mw]
            c2 = Cell(title=self.T(f"MW당 대출: 미국 {self.krw(vals[0])} vs 한국 {self.krw(vals[1])}", f"Debt per MW: U.S. {self.krw(vals[0])} vs Korea {self.krw(vals[1])}"),
                      src=["ecos", "ksj"], legend=[(c["gold"], self.T("미국 100MW", "U.S. 100 MW")), (c["brown_dark"], self.T("한국 1단계 20MW", "Korea phase 1"))],
                      unit=self.T("억원/MW", "KRW 100mn per MW"), chart_key="per_mw",
                      chart=charts.bars([self.T("미국", "U.S."), self.T("한국", "Korea")], vals, [c["gold"], c["brown_dark"]], c, lambda v: f"{v:,.0f}"),
                      note=self.T("달러 대출은 기준일 환율로 환산 (환헤지 비용 미반영)", "USD debt converted at the as-of rate (no hedging cost)"))
        elif ok(r):
            c2 = Cell(title=self.T(f"기준금리: 미 국채 10년 {r.dgs10:.2f}% vs 국고채 10년 {r.ktb_10y:.2f}% — 같은 DSCR이면 미국 원리금 부담이 크다",
                                   f"Base rates: UST 10y {r.dgs10:.2f}% vs KTB 10y {r.ktb_10y:.2f}% — at the same DSCR, U.S. debt service is heavier"),
                      src=["ecos", "fred"], legend=[(c["brown_dark"], self.T("국고채", "KTB")), (c["gold"], self.T("미 국채", "UST"))], unit="%",
                      chart_key="base_rates",
                      chart=charts.bars([self.T("국고채 3년", "KTB 3y"), self.T("국고채 10년", "KTB 10y"), self.T("미 국채 10년", "UST 10y")],
                                        [r.ktb_3y, r.ktb_10y, r.dgs10], [c["brown_mid"], c["brown_dark"], c["gold"]], c, lambda v: f"{v:.2f}%"),
                      note=self.T(f"ECOS {r.ktb_date}, FRED {r.dgs10_date}. 대출 한도 비교는 가정 입력 후 산출", f"ECOS {r.ktb_date}, FRED {r.dgs10_date}. Debt comparison after inputs"))
        else:
            c2 = self.pending(self.T("기준금리 비교", "Base-rate comparison"), ["ecos", "fred"], r)
        title = self.T("한·미 비교: 대출 한도를 정하는 병목이 다르다 — 한국은 계통·사전 임대율, 미국은 규모·금리",
                       "Korea vs U.S.: different bottlenecks set debt capacity — grid and pre-leasing in Korea, scale and rates in the U.S.")
        sub = self.T((f"기준금리 차이 {sp:+.2f}%p(미 국채 10년 − 국고채 10년) · 계통 승인 비율 {self.pct(g.ratio)} · 사전 임대율 {self.prelease_range()}" if sp is not None else "")
                     + (" · 환율 " + f"{fx:,.1f}원" if fx else ""),
                     (f"Base-rate gap {sp:+.2f}pp (UST 10y − KTB 10y) · grid approval {self.pct(g.ratio)} · pre-leasing {self.prelease_range()}" if sp is not None else "")
                     + (f" · FX {fx:,.1f}" if fx else ""))
        return Page("body", "6", title, sub, [c1, c2], grid="1x2")

    def val_assump(self, case: str, key: str) -> str:
        a = self.f.assumptions[case][key]
        if a.value is None:
            return self.T("근거 확인 중", "being sourced")
        return f"{a.value:,.0f}bp" if key == "margin_bp" else str(a.value)

    # --- p7 시사점 ------------------------------------------------------------
    def p7(self) -> Page:
        a, b, g, r = self.case("A"), self.case("B"), self.f.grid, self.f.rates
        pre_be = None
        if ok(a):
            be = a.breakeven
            hit = be[(be["variable"] == "prelease") & (be["level"] == 1.0)]["value"]
            pre_be = hit.iloc[0] if len(hit) and hit.iloc[0] == hit.iloc[0] else None
        rows = [
            [self.T("계통 승인", "Grid approval"), self.T(f"1단계 확정 승인 필수 · 2단계는 옵션 (승인 비율 {self.pct(g.ratio)})", f"Phase 1 approval a must; phase 2 as an option ({self.pct(g.ratio)})"),
             self.T("접속 일정 확인", "Confirm connection timing"), "1, 5"],
            [self.T("사전 임대율", "Pre-leasing"),
             self.T(f"최소 DSCR 1.0배 손익분기 {self.pct(pre_be)}" if pre_be else f"시장 {self.prelease_range()} — 손익분기는 입력 후", f"Breakeven for 1.0x: {self.pct(pre_be)}" if pre_be else f"Market {self.prelease_range()}; breakeven after inputs"),
             self.T("앵커 임차인 확보", "Anchor tenant"), "3, 4"],
            [self.T("금리", "Rates"), self.T(f"국고채 10년 {r.ktb_10y:.2f}%" if ok(r) else "국고채", f"KTB 10y {r.ktb_10y:.2f}%" if ok(r) else "KTB"),
             self.T(f"미 국채 10년 {r.dgs10:.2f}% — 헤지·가산금리 협상" if ok(r) else "미 국채", f"UST 10y {r.dgs10:.2f}% — hedging, margin" if ok(r) else "UST"), "2, 6"],
            [self.T("공사비", "Construction cost"), self.T("EPC 고정가 · 전력기기 가격 조항", "Fixed-price EPC; equipment price clauses"),
             self.T("규모가 커 절대 금액 위험 큼", "Large absolute exposure"), "2, 4"],
            [self.T("전력비", "Power cost"), self.T("패스스루 조항 · 예외(공용부) 확인", "Pass-through clause; carve-outs"),
             self.T("요금 상승기 임차인 부담 확인", "Tenant burden as prices rise"), "1, 2"],
            [self.T("유동성", "Liquidity"), self.T("DSRA · 램프업 기간 거치", "DSRA; grace over ramp-up"), self.T("DSRA", "DSRA"), "3"],
        ]
        c1 = Cell(title=self.T("대주 체크리스트: 한국은 '승인과 임차인', 미국은 '금리와 공사비'를 먼저 본다", "Lender checklist: Korea — approval and tenants first; U.S. — rates and cost first"),
                  src=["grid", "market", "ecos", "fred", "ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("한국 40MW", "Korea 40 MW"), self.T("미국 100MW", "U.S. 100 MW"), self.T("근거 쪽", "Pages")], rows,
                                  [0.16, 0.40, 0.32, 0.12], ["L", "L", "L", "C"], shade_rows={0, 1}, font_size=8.4),
                  note=self.T("가상 케이스 기준의 점검 항목. 숫자는 본문 계산값", "Checklist for the hypothetical cases; figures from the body"))
        limits = [self.T("두 케이스 모두 실존 프로젝트가 아니며, 공개 근거가 확인되지 않은 가정은 계산에 넣지 않았다", "Both cases are hypothetical; assumptions without a verified public source are not used"),
                  self.T("임대료·사전 임대율은 시장 보고서 인용 보도 수치로, 원문 확인 전이다", "Rent and pre-leasing figures come from press citing market reports, pending source checks"),
                  self.T("가동률 램프업은 IEA 세계 데이터센터 전력 성장률로 근사했다 — 지역 시장 흡수율과 다를 수 있다", "Ramp-up is proxied by IEA global data-centre power growth; local absorption may differ"),
                  self.T("피어 이익률→가격 상승은 상한값이며 인과가 아니다(물량·환율·제품 구성 미분리)", "Peer margin → price is an upper bound, not causal (volume, FX, mix not separated)"),
                  self.T("환헤지 비용·세무 조정(이월결손금 한도 등)·유지보수 CAPEX는 단순화했다", "FX hedging, tax details (loss-carryforward limits) and maintenance CAPEX are simplified")]
        if ok(self.f.va) and self.f.va.price_source == "US":
            limits.append(self.T("케이스 B 전력 단가는 버지니아 요금 수집 전 미국 상업용 평균을 대용했다", "Case B power price uses the U.S. commercial average until Virginia's is collected"))
        c2 = Cell(title=self.T("이 노트의 한계", "Limitations of this note"), bullets=limits, note=self.T("가정 근거가 확인되는 대로 갱신", "Updated as sources are confirmed"))
        c3 = Cell(title=self.T("Vol.3 예고: IPO 공모가와 해외 피어", "Next in Vol.3: IPO pricing and overseas peers"),
                  panel_lead=self.T("멀티플이 높아진 섹터의 가상 비상장 전력기기 기업, 희망공모가 밴드는?", "A hypothetical unlisted power-equipment IPO in a re-rated sector: what price range?"),
                  bullets=[self.T("국내 피어 PER·EV/EBITDA + 해외 피어(SEC EDGAR: Vertiv·Eaton·GE Vernova·Constellation·Vistra)", "Korean peers' P/E and EV/EBITDA + overseas peers (SEC EDGAR)"),
                           self.T("시총(상장사)과 재무(공시 법인) 주체 일치 검증", "Check that market cap (listed parent) and financials (filer) are the same entity"),
                           self.T("적정 시총 → 공모 할인 → 희망공모가 밴드 · 몬테카를로 민감도", "Fair value → IPO discount → price range · Monte Carlo sensitivity")],
                  note=self.T("Vol.3 일정·방법은 변경될 수 있음", "Timing and method of Vol.3 may change"))
        na = sum(x.value is None for k, x in self.f.assumptions["A"].items() if k in LABELS)
        nb = sum(x.value is None for k, x in self.f.assumptions["B"].items() if k in LABELS)
        c4 = Cell(title=self.T(f"근거 확인 대기 가정: 케이스 A {na}개, 케이스 B {nb}개", f"Assumptions awaiting sources: Case A {na}, Case B {nb}"),
                  bullets=[self.T("숫자를 지어내지 않는다: 공개 근거가 없는 가정은 계산하지 않고 빈칸으로 둔다", "No invented numbers: unsourced assumptions are left blank, not computed"),
                           self.T("근거가 확인되면 같은 엔진으로 모든 표·그림·결론 문장이 다시 계산된다", "Once sourced, every table, chart and conclusion is recalculated by the same engine"),
                           self.T("케이스별 가정·단위·출처·상태는 Appendix A2·A3", "Assumptions, units, sources and status by case: Appendix A2–A3")],
                  note=self.T("상태: 입력 필요 · 원문 확인 · 출처 기재 · 데이터 · 설계값 · 중립값", "Status: input needed · verify · sourced · data · design · neutral"))
        title = self.T("시사점: 한국 AI 데이터센터 PF는 '얼마나 빌리나'보다 '언제 빌릴 수 있나' — 계통 승인과 앵커 임차인이 먼저다",
                       "Implication: for Korean AI data-centre PF, 'when' comes before 'how much' — grid approval and an anchor tenant first")
        sub = self.T("대주 체크리스트 · 한계 · 근거 확인 대기 가정 · Vol.3 예고(IPO 공모가·해외 피어)",
                     "Lender checklist · limitations · assumptions awaiting sources · next: Vol.3 (IPO pricing, overseas peers)")
        return Page("body", "7", title, sub, [c1, c2, c3, c4])

    # --- Appendix ------------------------------------------------------------
    def a1(self) -> Page:
        a, b, r, g, pp, op, va, d = (self.case("A"), self.case("B"), self.f.rates, self.f.grid, self.f.peers, self.f.option,
                                     self.f.va, self.f.demand)
        qa, key = [], set()
        # 1 앵커 임차인
        if ok(a):
            be = a.breakeven
            hit = be[(be["variable"] == "prelease") & (be["level"] == 1.0)]["value"]
            pbe = hit.iloc[0] if len(hit) and hit.iloc[0] == hit.iloc[0] else None
            ans = self.T(f"계약 임대료만 보면 최소 DSCR {self.x(a.base.min_dscr_contracted)}(사전 임대율 {self.pct(a.inp.prelease)}). 최소 DSCR 1.0배 손익분기 사전 임대율은 {self.pct(pbe)}다. "
                         "대주는 계약된 현금흐름으로 원리금을 갚을 수 있어야 하므로 앵커 임차인 없는 대출은 한도가 크게 줄거나 불가능하다",
                         f"On contracted rent only, min DSCR is {self.x(a.base.min_dscr_contracted)} (pre-lease {self.pct(a.inp.prelease)}); the 1.0x breakeven pre-lease is {self.pct(pbe)}. "
                         "Lenders need contracted cash flow to cover debt service, so without an anchor tenant capacity shrinks sharply or disappears")
        else:
            ly = self.lease_up_years()
            ans = self.T(f"어렵다. 수도권 신규 물량의 사전 임대율은 {self.prelease_range()}이고, 시장 수요 성장(IEA 기준 연 {self.pct(d.growth['base']) if ok(d) else '—'})만큼 채우면 만실까지 {self.yrs(ly)}이 걸린다. "
                         "대주는 계약된 임대료로 원리금을 갚을 수 있는지를 먼저 보며, 손익분기 사전 임대율은 가정 확인 후 p4에서 계산한다",
                         f"Hard. Pre-leasing for new Seoul-metro supply is {self.prelease_range()}, and filling at market growth (IEA base {self.pct(d.growth['base']) if ok(d) else '—'}/yr) takes {self.yrs(ly)}. "
                         "Lenders first ask whether contracted rent covers debt service; the breakeven pre-lease is computed on p4 once inputs are sourced")
        key.add(len(qa))
        qa.append([self.T("앵커 임차인 없이 대출 가능한가?", "Can it borrow without an anchor tenant?"), ans, "2, 3, 4"])
        # 2 왜 40MW
        qa.append([self.T("한국은 왜 40MW인가?", "Why 40 MW in Korea?"),
                   self.T(f"{self.grid_sentence() or '계통 제약'}. 10MW 이상은 전력계통영향평가 대상이고 국내 운영 사례도 40MW급이다. 그래서 20MW를 확정 개발하고 20MW는 추가 승인·임차 수요 확인 후 짓는 옵션으로 나눴다",
                          f"{self.grid_sentence() or 'Grid constraints'}. Projects of 10 MW or more need a grid impact assessment, and domestic operating sites are around 40 MW. Hence 20 MW firm plus a 20 MW option built after approval and demand are confirmed"),
                   "1, 5"])
        key.add(len(qa) - 1)
        # 3 왜 미국 100MW
        qa.append([self.T("미국은 왜 100MW이고, 무엇이 다른가?", "Why 100 MW in the U.S., and what differs?"),
                   self.T((f"버지니아 상업용 전력 판매가 연 {self.pct(va.va_cagr)}로 미국({self.pct(va.us_cagr)})보다 빠르다. " if ok(va) else "")
                          + (f"대신 기준금리가 국고채보다 {self.rate_spread():.2f}%p 높아 같은 DSCR에서도 원리금 부담이 크다" if self.rate_spread() is not None else ""),
                          (f"Virginia commercial sales grow {self.pct(va.va_cagr)}/yr vs U.S. {self.pct(va.us_cagr)}. " if ok(va) else "")
                          + (f"But base rates are {self.rate_spread():.2f}pp above KTB, so debt service is heavier at the same DSCR" if self.rate_spread() is not None else "")), "2, 6"])
        # 4 금리 +100bp
        if ok(a):
            ru = a.stresses["rate_up"]
            ans = self.T(f"대출 스케줄을 고정하면 최소 DSCR {self.x(a.base.min_dscr)} → {self.x(ru.min_dscr)}, Equity IRR {self.pct(a.base.equity_irr)} → {self.pct(ru.equity_irr)}",
                         f"With the schedule fixed, min DSCR {self.x(a.base.min_dscr)} → {self.x(ru.min_dscr)}; equity IRR {self.pct(a.base.equity_irr)} → {self.pct(ru.equity_irr)}")
        else:
            ans = self.T(f"기준금리(국고채 10년 {r.ktb_10y:.2f}%, 미 국채 10년 {r.dgs10:.2f}%)에 ±100bp를 더해 최소 DSCR 변화를 p4에서 계산한다(가산금리 확인 후)" if ok(r) else "가정 확인 후 계산",
                         f"±100bp on base rates (KTB 10y {r.ktb_10y:.2f}%, UST 10y {r.dgs10:.2f}%); the DSCR impact is computed on p4 once margins are sourced" if ok(r) else "After inputs")
        qa.append([self.T("금리가 100bp 오르면?", "What if rates rise 100bp?"), ans, "4"])
        # 5 공사비
        if ok(pp):
            sc = pp.scenarios()
            extra = ""
            if ok(a) and ok(a.capex_stress):
                extra = self.T(f" 전력설비 비중을 곱하면 CAPEX +{(a.capex_stress['high'] - 1) * 100:.1f}%(고), 최소 DSCR {self.x(a.stresses['capex_high'].min_dscr)}",
                               f" Times the equipment share: CAPEX +{(a.capex_stress['high'] - 1) * 100:.1f}% (high), min DSCR {self.x(a.stresses['capex_high'].min_dscr)}")
            ans = self.T(f"피어 3사 영업이익률 {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)}({pp.fy0}→{pp.fy1})이 모두 가격이라면 전력기기 가격 {self.pct(sc['low'])}~{self.pct(sc['high'])} 상승에 해당한다(상한값, 인과 아님).{extra}",
                         f"If the three peers' margin rise {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)} ({pp.fy0}→{pp.fy1}) were all price, equipment prices rose {self.pct(sc['low'])}–{self.pct(sc['high'])} (upper bound, not causal).{extra}")
        else:
            ans = self.T("피어 데이터 확인 중", "Peer data pending")
        qa.append([self.T("전력기기 가격이 오르면 공사비는?", "What if equipment prices rise?"), ans, "2, 4"])
        # 6 전력비
        pt = self.A("power_passthrough").value
        if ok(va):
            y, p = va.price_latest
        ans = self.T(f"임차인이 사용량 × 단가로 부담하는 패스스루 {pt * 100:.0f}%를 가정했다. SPC의 전력비 순액은 0이고, 요금 상승은 임차인 부담 능력의 문제로 넘어간다"
                     + (f"(미국 상업용 평균 {p:.2f}¢/kWh, {y})" if ok(va) else ""),
                     f"A {pt * 100:.0f}% pass-through: the tenant pays usage × tariff, so the SPC's net power cost is zero and tariff risk becomes a tenant-affordability question"
                     + (f" (U.S. commercial average {p:.2f}¢/kWh, {y})" if ok(va) else ""))
        qa.append([self.T("전력비는 누가 내나?", "Who pays for power?"), ans, "1, 2"])
        # 7 지금 vs 기다리기
        if ok(op):
            rr = op.result
            ans = self.T(f"승인 확률 {self.pct(op.inputs.approval_prob, 0)}에서 지금 짓기 {self.money('A', rr.build_now)} vs 기다리기 {self.money('A', rr.value)}. 기다릴 권리의 가치는 {self.money('A', rr.flexibility)}",
                         f"At p = {self.pct(op.inputs.approval_prob, 0)}: build now {self.money('A', rr.build_now)} vs wait {self.money('A', rr.value)}; the right to wait is worth {self.money('A', rr.flexibility)}")
        else:
            ans = self.T(f"승인 여부(참고: 1단계 승인 비율 {self.pct(g.ratio)})와 임대료·수요 불확실성을 몬테카를로(LSM)로 평가한다. 승인 확률·결정 시점·임대료 변동성 확인 후 p5에서 계산",
                         f"Grid approval (ref.: phase-1 approval {self.pct(g.ratio)}) plus rent and demand uncertainty valued by LSM Monte Carlo; computed on p5 once inputs are sourced")
        qa.append([self.T("2단계는 지금 짓나, 기다리나?", "Build phase 2 now or wait?"), ans, "5"])
        # 8 환율
        fx = self.f.fx()
        qa.append([self.T("미국 케이스 환율은 어떻게 반영했나?", "How is FX handled for the U.S. case?"),
                   self.T(f"달러로 계산한 뒤 ECOS 원/달러 {fx:,.1f}원({r.fx_date})으로 환산: 억원 = USD mn × 환율 ÷ 100. 환헤지 비용은 반영하지 않았다" if fx else "환율 데이터 확인 중",
                          f"Computed in USD, converted at ECOS USD/KRW {fx:,.1f} ({r.fx_date}): KRW 100mn = USD mn × FX ÷ 100. Hedging costs are excluded" if fx else "FX data pending"),
                   "6, A4"])
        cell = Cell(title=self.T(f"예상 질문 {len(qa)}개와 답 — 대주 관점 포함", f"{len(qa)} expected questions, including the lender's view"),
                    src=["grid", "market", "iea", "ecos", "fred", "dart", "eia"],
                    table=TableSpec([self.T("질문", "Question"), self.T("답", "Answer"), self.T("근거 쪽", "Page")], qa, [0.22, 0.7, 0.08],
                                    ["L", "L", "C"], shade_rows=key, font_size=8.1),
                    note=self.T("답의 숫자는 본문과 같은 계산 결과. 음영 = 대주 관점 핵심 질문", "Numbers match the body; shaded = core lender questions"))
        return Page("full", "A1", self.T("예상 질의응답: 대주가 먼저 묻는 것", "Expected Q&A: what lenders ask first"),
                    self.T("투자심사·대주 실사에서 나올 질문과 근거 쪽수", "Questions likely in credit review and lender due diligence, with page references"), [cell], grid="1x1")

    STATUS_KR = {"input": "입력 필요", "verify": "원문 확인", "sourced": "출처 기재", "data": "데이터", "design": "설계값", "neutral": "중립값"}
    STATUS_EN = {"input": "Input needed", "verify": "Verify", "sourced": "Sourced", "data": "Data", "design": "Design", "neutral": "Neutral"}

    def fmt_assump(self, a: Assumption) -> str:
        v = a.value
        if v is None:
            return "—"
        if isinstance(v, str):
            return v
        u = a.unit
        if u in ("%", "%/년", "법인세 대비 %"):
            s = f"{v * 100:.2f}".rstrip("0").rstrip(".") + "%"
            if a.low is not None and a.high is not None:
                s += f" ({a.low * 100:g}~{a.high * 100:g}%)" if self.kr else f" ({a.low * 100:g}–{a.high * 100:g}%)"
            return s
        return f"{v:,.4g}" if abs(v) < 10 else f"{v:,.0f}"

    UNIT_EN = {"억원/MW": "KRW 100mn/MW", "분기": "quarters", "원/kW·월": "KRW/kW-month", "%/년": "%/yr", "배": "x", "원/kW·년": "KRW/kW-yr",
               "원/kWh": "KRW/kWh", "년": "yrs", "개월": "months", "법인세 대비 %": "% of national tax", "년(1단계 COD 후)": "yrs after phase-1 COD",
               "USD/kW·월": "USD/kW-month", "USD/kW·년": "USD/kW-yr", "USD mn/MW": "USD mn/MW"}

    def source_text(self, a: Assumption) -> str:
        if a.origin == "data":
            return a.source or ""
        if a.value is None:
            return self.T("근거 확인 중", "Being sourced")
        s = a.source or ""
        if not self.kr:
            s = {"design": "Hypothetical case design", "neutral": "Neutral value pending evidence"}.get(a.status, "")
            if a.status in ("verify", "sourced"):
                s = {"rent_per_kw_month": "Press citing CBRE (2025)", "rent_escalation": "2–3% p.a. (mid 2.5%)",
                     "prelease": "Seoul-metro 2027–28 deliveries 16–23.5% (base = midpoint)", "tax_rate_national": "26 U.S.C. §11(b)",
                     "tax_rate_local": "Va. Code §58.1-400 (B) / local income tax (A)"}.get(a.key, "Public source, being verified")
        extra = " · ".join(x for x in (a.url, a.published, a.page) if x)
        return s + (f" · {extra}" if extra else "")

    def a_assumptions(self, case: str, label: str) -> Page:
        d = self.f.assumptions[case]
        keys = [k for k in LABELS if k in d and not (case == "B" and k in ("grid_approval_prob", "approval_decision_year", "option_window_years", "rent_volatility"))]
        rows, brick, shade = [], set(), set()
        st = self.STATUS_KR if self.kr else self.STATUS_EN
        for i, k in enumerate(keys):
            a = d[k]
            unit = a.unit if self.kr else self.UNIT_EN.get(a.unit, a.unit)
            rows.append([self.lab(k), self.fmt_assump(a), unit, self.source_text(a), st[a.status]])
            if a.status == "input":
                brick.add((i, 4))
            if a.status in ("verify", "data"):
                shade.add(i)
        cnt = sum(d[k].value is None for k in keys)
        cell = Cell(title=self.T(f"{self.name(case)}: 가정 {len(keys)}개 중 {cnt}개는 근거 확인 후 입력 — 근거 없는 숫자는 계산에 넣지 않는다",
                                 f"{self.name(case)}: {cnt} of {len(keys)} assumptions await sources — unsourced numbers are not used"),
                    src=["market", "tax"] if case == "B" else ["market", "grid"],
                    table=TableSpec([self.T("항목", "Item"), self.T("값", "Value"), self.T("단위", "Unit"), self.T("근거·출처", "Basis / source"),
                                     self.T("상태", "Status")], rows, [0.22, 0.14, 0.13, 0.39, 0.12], ["L", "R", "L", "L", "C"],
                                    shade_rows=shade, brick_cells=brick, font_size=7.6),
                    note=self.T("상태: 입력 필요 = 공개 근거 확인 전(계산 제외) · 원문 확인 = 공개 근거 있음, 원문 대조 전 · 설계값 = 가상 케이스 설정 · 중립값 = 근거 부재 시 중립 · 데이터 = 공식 통계에서 계산",
                                "Status: input needed = not yet sourced (excluded) · verify = public basis, not yet checked against the original · design = hypothetical case setting · neutral = neutral pending evidence · data = from official statistics"))
        name = self.v["cases"][case]["name_kr" if self.kr else "name_en"]
        return Page("full", label, self.T(f"가정과 출처: {self.name(case)}", f"Assumptions and sources: {self.name(case)}"), name, [cell], grid="1x1")

    DATASETS_NOTE = None

    def a4(self) -> Page:
        srcs = self.f.sources
        rows = [[s["org_kr"] if self.kr else s["org_en"], s["ds_kr"] if self.kr else s["ds_en"], s["item_kr"] if self.kr else s["item_en"],
                 s["as_of"] or "—", self.T("수집 완료", "Collected") if s["ok"] else self.T("미수집", "Not collected")] for s in srcs]
        pend = {i for i, s in enumerate(srcs) if not s["ok"]}
        c1 = Cell(title=self.T("데이터 소스 · 통계 · 기준일", "Data sources · datasets · as-of dates"),
                  table=TableSpec([self.T("소스", "Source"), self.T("통계", "Dataset"), self.T("항목", "Items"), self.T("기준일", "As of"), self.T("상태", "Status")],
                                  rows, [0.17, 0.35, 0.25, 0.11, 0.12], ["L", "L", "L", "C", "C"], shade_rows=pend, brick_cells={(i, 4) for i in pend},
                                  font_size=8.2),
                  note=self.T("기준일 = 데이터 수집 기준일(IEA는 원문 대조일). 해외 피어(SEC) 데이터는 Vol.3에서 사용",
                              "As-of = collection date (IEA: date checked against source). Overseas peers (SEC) are used in Vol.3"))
        r, g = self.f.rates, self.f.grid
        krows = []
        if ok(r):
            krows += [[self.T("국고채 3년 · 10년", "KTB 3y · 10y"), f"{r.ktb_3y:.3f}% · {r.ktb_10y:.3f}%", r.ktb_date, "ECOS"],
                      [self.T("미 국채 10년 (DGS10)", "UST 10y (DGS10)"), f"{r.dgs10:.2f}%", r.dgs10_date, "FRED"],
                      [self.T("원/달러 (매매기준율)", "USD/KRW"), f"{r.usdkrw:,.1f}", r.fx_date, "ECOS"]]
        if ok(self.f.demand):
            d = self.f.demand
            krows.append([self.T("수요 성장률 (하단·기준·상단)", "Demand growth (low·base·high)"), " · ".join(self.pct(d.growth[s], 2) for s in SCENARIOS),
                          f"{d.years[0]}→{d.years[1]}", "IEA"])
        if ok(self.f.peers):
            pp = self.f.peers
            krows.append([self.T("피어 3사 합산 영업이익률", "3-peer combined OPM"), f"{self.pct(pp.agg_opm0, 2)} → {self.pct(pp.agg_opm1, 2)}", f"{pp.fy0}→{pp.fy1}", "DART"])
        if g.ratio is not None:
            krows.append([self.T("계통 승인 비율", "Grid approval ratio"), f"{g.approved:,.0f} ÷ {g.applied:,.0f} = {self.pct(g.ratio, 2)}", g.period,
                          self.T("공개 보도(원문 확인 중)", "Public reports (verifying)")])
        if ok(self.f.va):
            y, p = self.f.va.price_latest
            krows.append([self.T("상업용 평균 요금", "Commercial average price"), f"{p:.2f}¢/kWh ({'VA' if self.f.va.price_source == 'VA' else 'US'})", str(y), "EIA"])
        c2 = Cell(title=self.T("모델에 들어간 데이터 값과 기준일", "Data values used in the model, with dates"),
                  table=TableSpec([self.T("항목", "Item"), self.T("값", "Value"), self.T("기준", "Date / period"), self.T("출처", "Source")], krows,
                                  [0.3, 0.32, 0.2, 0.18], ["L", "R", "C", "L"], font_size=8.4),
                  note=self.T("기준일 2026-10-20 이전 최근 영업일 값. 원화 환산 = USD mn × 원/달러 ÷ 100", "Latest business day on or before 2026-10-20. KRW = USD mn × USD/KRW ÷ 100"))
        return Page("full", "A4", self.T("데이터 노트: 출처·통계·기준일과 모델 입력값", "Data notes: sources, datasets, dates and model inputs"),
                    self.T("Vol.1과 같은 공식 출처 데이터를 PF 가정에 연결 · 해외 피어(SEC)는 Vol.3", "The same official-source data as Vol.1, linked to PF inputs · overseas peers (SEC) in Vol.3"),
                    [c1, c2], grid="2x1")

    BUILT_WITH_KR = "구현: AI 코딩 도구(Claude Code)로 데이터 연결·PF 모델·몬테카를로·보고서 생성 코드를 작성. 케이스 설계, 가정 근거 판단, 숫자 검증은 저자."
    BUILT_WITH_EN = "Built with an AI coding tool (Claude Code) for data links, the PF model, Monte Carlo and report generation; case design, assumption sourcing and number checks by the author."

    def a5(self) -> Page:
        steps = [
            (self.T("1. 데이터 연결", "1. Data links"), ["IEA → " + self.T("램프업", "ramp-up"), "ECOS · FRED → " + self.T("기준금리", "base rates"),
                                                         "DART → " + self.T("CAPEX 스트레스", "CAPEX stress"), "EIA → " + self.T("케이스 B", "Case B")]),
            (self.T("2. PF 모델", "2. PF model"), [self.T("분기 건설·IDC", "Quarterly build, IDC"), "CFADS → sculpting", self.T("최대 대출 비율 한도", "Gearing cap"),
                                                    "Waterfall · DSRA"]),
            (self.T("3. 스트레스·옵션", "3. Stress, option"), [self.T("손익분기·토네이도", "Breakevens, tornado"), self.T("히트맵", "Heatmap"),
                                                              self.T("LSM 몬테카를로", "LSM Monte Carlo"), self.T("seed 고정·수렴", "Fixed seed, convergence")]),
            (self.T("4. 검증·보고서", "4. Checks, report"), [self.T("회계 항등식", "Accounting identities"), self.T("DSCR·IRR·환율 검산", "DSCR, IRR, FX checks"),
                                                            self.T("결론형 제목", "Conclusion titles"), self.T("국문·영문", "Korean & English")]),
        ]
        url = self.cfg["research"]["repo_url"]
        c1 = Cell(title=self.T("데이터 연결 → PF 모델 → 스트레스·옵션 → 검증·보고서", "Data links → PF model → stress and option → checks and report"),
                  src=["ksj"], chart_key="method", chart=charts.flow4(steps, self.c), strip=self.T(self.BUILT_WITH_KR, self.BUILT_WITH_EN),
                  note=self.T(f"전체 코드·데이터 출처: GitHub {url}", f"Full code and data sources: GitHub {url}"))
        return Page("full", "A5", self.T("분석 방법: 같은 엔진, 케이스별 파라미터, 검증된 계산", "Methodology: one engine, case parameters, verified calculations"),
                    self.T("모든 숫자는 데이터와 가정에서 계산하고, 결론 문장도 계산 결과로 만든다",
                           "Every figure is calculated from data and assumptions, and conclusions are generated from the results"), [c1], grid="1x1")

    def a6(self) -> Page:
        terms = [
            ("CFADS", self.T("원리금 상환 가능 현금흐름 = EBITDA − 법인세 (유지보수 CAPEX 단순화)", "Cash flow available for debt service = EBITDA − tax")),
            ("DSCR", self.T("원리금 상환 비율 = CFADS ÷ 원리금(이자 + 원금). 연도별, 최소·평균", "Debt service cover ratio = CFADS ÷ (interest + principal)")),
            ("LLCR", self.T("대출 기간 CFADS의 현재가치(대출 금리 할인) ÷ 대출 잔액", "Loan life cover ratio = PV of CFADS over loan life ÷ debt")),
            ("Sculpting", self.T("연도별 원리금 = CFADS ÷ 목표 DSCR로 맞춰 대출 한도를 정하는 방식", "Sizing debt by setting each year's debt service = CFADS ÷ target DSCR")),
            (self.T("최대 대출 비율", "Maximum gearing"), self.T("대출 ÷ 총사업비 상한 (LTC)", "Cap on debt ÷ total project cost (LTC)")),
            ("DSRA", self.T("원리금 적립 계좌. 다음 해 원리금의 일정 개월분을 쌓아 둔다", "Debt service reserve account: months of next year's debt service")),
            ("IDC", self.T("건설기간 이자. 총사업비에 자본화", "Interest during construction, capitalised into project cost")),
            (self.T("거치기간", "Grace period"), self.T("원금 상환을 미루는 기간(이자는 지급 또는 자본화)", "Principal holiday (interest paid or capitalised)")),
            (self.T("책임임대", "Committed lease"), self.T("임차인이 사용 여부와 무관하게 약정 용량의 임대료를 내는 장기 계약", "Long-term lease paying for contracted capacity regardless of use")),
            (self.T("패스스루", "Pass-through"), self.T("전력비를 임차인에게 사용량 × 단가로 넘기는 조항", "Clause passing power cost to the tenant at usage × tariff")),
            ("MW (IT)", self.T("서버 등 IT 장비가 쓰는 전력 용량 기준. 냉각 등 포함 전체 = IT × PUE", "Capacity for IT equipment; total facility = IT × PUE")),
            ("PUE", self.T("전체 시설 전력 ÷ IT 전력", "Total facility power ÷ IT power")),
            ("Project IRR / Equity IRR", self.T("무차입 세후 현금흐름의 IRR / 자기자본 현금흐름의 IRR", "IRR of unlevered after-tax cash flow / of equity cash flow")),
            (self.T("실물옵션", "Real option"), self.T("투자 시점을 미룰 권리의 가치", "Value of the right to defer an investment")),
            ("LSM", self.T("최소제곱 몬테카를로: 회귀로 '기다림'의 기대가치를 추정해 최적 행사 시점을 정함", "Least-squares Monte Carlo: regression estimates continuation value to time exercise")),
            (self.T("전력계통영향평가", "Grid impact assessment"), self.T("대규모 전력 수요(10MW 이상)의 계통 영향 사전 평가", "Pre-assessment of grid impact for large loads (10 MW+)")),
        ]
        cell = Cell(title=self.T("용어 정의", "Glossary"),
                    table=TableSpec([self.T("용어", "Term"), self.T("정의", "Definition")], [list(t) for t in terms], [0.22, 0.78], ["L", "L"],
                                    shade_rows={0, 1, 2, 3, 5}, font_size=8.6),
                    note=self.T("음영 = 대주 관점 핵심 지표", "Shaded = core lender metrics"))
        return Page("full", "A6", self.T("용어 정의: 대주가 쓰는 말", "Glossary: the lender's vocabulary"),
                    self.T("금액 단위: 원화 억원, 달러 USD mn · 비율 %, 배", "Units: KRW 100mn, USD mn · %, x"), [cell], grid="1x1")
