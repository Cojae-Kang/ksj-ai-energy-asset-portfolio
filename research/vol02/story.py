"""Vol.2 페이지 구성·문구 (국문/영문). 숫자는 모두 data.Facts에서, 결론 문장도 계산 결과로 만든다.

공개용 원칙(Vol.1과 같음): 제목에 '(저자 견해)'를 붙이지 않고 요약 쪽 하단·뒤표지에 한 줄만 둔다.
내부 파일·설정·실행 명령·태그는 보고서에 쓰지 않는다. 입력이 없는 계산은 "입력·출처 확인 후 생성" 박스로 둔다.
"""
from __future__ import annotations

import math
import re
from typing import Mapping

import numpy as np

from research.vol01.layout import BigBox, Cell, Page, TableSpec, toc_line

from . import charts
from src.analysis.pf_model import yield_on_cost as pf_yoc

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
            "grid": self.T("블록미디어, 국내 AI 데이터센터 프로젝트 4건의 가동 준비 현황과 손익분기 조건(2024.8~2026.3 수도권 1단계 계통 신청·최종 공급 승인)",
                           "Blockmedia, readiness and breakeven conditions of four Korean AI data-centre projects (Seoul-metro phase-1 grid applications and final supply approvals, Aug 2024–Mar 2026)"),
            "law": self.T("분산에너지 활성화 특별법(전력계통영향평가)", "Distributed Energy Act (grid impact assessment)"),
            "market": self.T("블록미디어(CBRE 인용), CBRE Global Data Center Trends 2026, CBRE North America Data Center Trends H1 2026",
                             "Blockmedia (citing CBRE); CBRE Global Data Center Trends 2026; CBRE North America Data Center Trends H1 2026"),
            "cost": self.T("이투데이(다올투자증권 리포트 인용, 2026-10-01), 이데일리(2026-10-12), Cushman & Wakefield 2026 Data Center Development Cost Guide",
                           "Etoday (citing Daol Investment & Securities, 1 Oct 2026); Edaily (12 Oct 2026); Cushman & Wakefield 2026 Data Center Development Cost Guide"),
            "finance": self.T("Gridlines(2026), Lev(2026-08-20), 이데일리(2026-10-12)", "Gridlines (2026); Lev (20 Aug 2026); Edaily (12 Oct 2026)"),
            "tax": self.T("법인세법 제55조(택스가이드), 미국 연방 세법 26 U.S.C. §11(b), 버지니아 주법 §58.1-400",
                          "Korean Corporate Tax Act Art. 55 (Taxguide); 26 U.S.C. §11(b); Va. Code §58.1-400"),
            "lease": self.T("Data Center Scouts, Data center leasing(2026-09-25 게시, 2026-10-08 갱신); gr1d, Powered Shell vs Turnkey vs Colocation(2026-10-15)",
                            "Data Center Scouts, Data center leasing (posted 25 Sep 2026, updated 8 Oct 2026); gr1d, Powered Shell vs Turnkey vs Colocation (15 Oct 2026)"),
            "hl": "Houlihan Lokey, Data Center Update (Oct 2026)",
            "power": self.T("시대일보(2026-08-27, 한전 2025년 평균 산업용 판매단가)", "Sidae Ilbo (27 Aug 2026; KEPCO 2025 average industrial tariff)"),
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
    def grid_short(self) -> str:
        """'건수 1.9%·용량 3.0%'."""
        g = self.f.grid
        if g.ratio is None:
            return "—"
        if g.ratio_n is None:
            return self.pct(g.ratio)
        return self.T(f"건수 {self.pct(g.ratio_n)}·용량 {self.pct(g.ratio)}", f"{self.pct(g.ratio_n)} count / {self.pct(g.ratio)} MW")

    def grid_sentence(self) -> str | None:
        g = self.f.grid
        if g.ratio is None:
            return None
        cnt = (self.T(f"건수 {self.pct(g.ratio_n)}({g.applied_n:,.0f}건 중 {g.approved_n:,.0f}건), ",
                      f"{self.pct(g.ratio_n)} by count ({g.approved_n:,.0f} of {g.applied_n:,.0f}), ") if g.ratio_n is not None else "")
        return self.T(f"수도권 계통 승인률 {cnt}용량 {self.pct(g.ratio)}({g.applied:,.0f}MW 중 {g.approved:,.0f}MW)",
                      f"Seoul-metro grid approval {cnt}{self.pct(g.ratio)} by capacity ({g.approved:,.0f} of {g.applied:,.0f} MW)")

    def grid_basis(self) -> str:
        g = self.f.grid
        return self.T(f"{g.period}, {g.basis_note}", f"{g.period}, all Seoul-metro phase-1 grid applications (final supply approval)")

    def capex_range_text(self) -> str:
        cx = self.A("capex_per_mw")
        if cx.low is None or cx.high is None:
            return self.T("MW당 CAPEX 범위 미입력", "CAPEX range not set")
        mid = ((self.v["sensitivity"].get("capex_mid") or {}).get("A") or {}).get("value")
        return self.T(f"MW당 {cx.low:,.0f}~{cx.high:,.0f}억원 범위" + (f"(중간 {mid:,.0f}억원)" if mid else ""),
                      f"KRW {cx.low / 10:,.1f}–{cx.high / 10:,.1f}bn per MW" + (f" (mid {mid / 10:,.1f}bn)" if mid else ""))

    def prelease_range(self) -> str:
        p = self.A("prelease")
        if p.low is None:
            return "—"
        return f"{p.low * 100:.0f}~{p.high * 100:.1f}%" if self.kr else f"{p.low * 100:.0f}–{p.high * 100:.1f}%"

    def base_label(self, case: str) -> str:
        ser = self.v["rates"][case]["term"]
        return {"ktb_3y": self.T("국고채 3년", "KTB 3y"), "ktb_10y": self.T("국고채 10년", "KTB 10y"),
                "DGS10": self.T("미 국채 10년", "UST 10y")}[ser]

    def base_value(self, case: str) -> float | None:
        r = self.f.rates
        v = r.base(case, "term", self.cfg) if ok(r) else None
        return None if v is None else v * 100

    def rate_spread(self) -> float | None:
        """모델 기준금리 차이(%p): 케이스 B − 케이스 A."""
        a, b = self.base_value("A"), self.base_value("B")
        return None if a is None or b is None else b - a

    def lease_up_years(self, s: str = "base") -> float | None:
        d, p = self.f.demand, self.A("prelease").value
        if not ok(d) or p is None:
            return None
        g = d.growth[s] * float(self.A("ramp_elasticity").value or 1.0)
        return math.log(1 / p) / math.log(1 + g) if g > 0 else None

    def binding_text(self, r) -> str:
        return {"dscr": self.T("목표 DSCR이 한도를 정했다", "the target DSCR sets the limit"),
                "gearing": self.T("최대 대출 비율이 한도를 정했다", "maximum gearing sets the limit")}.get(r.binding, "")

    def a_gross(self) -> bool:
        """케이스 A 임대료를 전력 포함(gross)으로 보고 SPC가 전력비를 부담하는지."""
        v = self.A("power_passthrough").value
        return v is not None and v < 1

    def irr2(self, r, which: str = "equity") -> str:
        """'16.1% (잔존가치 제외 14.0%)' 형식."""
        v, ex = (r.equity_irr, r.equity_irr_ex_tv) if which == "equity" else (r.project_irr, r.project_irr_ex_tv)
        if not r.terminal_value:
            return self.pct(v)
        return self.T(f"{self.pct(v)} (잔존가치 제외 {self.pct(ex)})", f"{self.pct(v)} (ex-TV {self.pct(ex)})")

    def power_clause(self) -> tuple | None:
        """케이스 A 전력비 조항 비교: (별도 청구 결과, 전력 포함 결과, 기준이 별도 청구인지)."""
        a = self.case("A")
        if not ok(a) or a.power_pair() is None:
            return None
        pt_r, gr_r = a.power_pair()
        return pt_r, gr_r, not self.a_gross()

    def clause_sentence(self) -> str | None:
        pc = self.power_clause()
        if pc is None:
            return None
        pt_r, gr_r, _ = pc
        return self.T(f"전력비 부담 조항 하나로 Equity IRR이 {self.pct(pt_r.equity_irr)}(별도 청구) vs {self.pct(gr_r.equity_irr)}(전력 포함 임대)로 갈린다",
                      f"One power-cost clause splits equity IRR: {self.pct(pt_r.equity_irr)} (passed through) vs {self.pct(gr_r.equity_irr)} (gross rent)")

    def rent20(self):
        b = self.case("B")
        return next((x for k, x in b.stresses.items() if k.startswith("rent_-")), None) if ok(b) else None

    def contracted_min(self, case: str) -> tuple[float, int] | None:
        """계약분 최소 DSCR과 그 연차 (p3·p6 '계약분 DSCR'과 같은 정의: 원금 상환 기간, 계약 임대료 CFADS만)."""
        cr = self.case(case)
        if not ok(cr):
            return None
        o, inp = cr.base.ops, cr.inp
        t0 = inp.grace_years if inp.grace_interest == "reserve" else 0
        dc = (o["cfads_contracted"] / o["debt_service"]).iloc[t0:inp.tenor_years].to_numpy()
        if not len(dc) or not np.isfinite(dc).any():
            return None
        i = int(np.nanargmin(dc))
        return float(dc[i]), int(o["year"].iloc[t0 + i])

    def lease_vs_tenor(self, case: str) -> str:
        """체크리스트 '임대 만기 ≥ 대출 만기' 칸: 임대 기간 vs COD 후 상환 기간 + 계약분 최소 DSCR(연차)."""
        cr = self.case(case)
        if not ok(cr):
            return self.T("임대 기간 · 대출 만기 확인", "Check lease term vs loan tenor")
        lt, tn = cr.inp.lease_term_years, cr.inp.tenor_years
        cm = self.contracted_min(case)
        dscr = (self.T(f"계약분 최소 DSCR {self.x(cm[0])}({cm[1]}년차)", f"contracted min DSCR {self.x(cm[0])} (year {cm[1]})") if cm else "")
        if lt is None:
            return self.T(f"임대 기간 미확정 · 대출 COD 후 {tn}년 — {dscr}: 만기까지 신규 임차·재임대에 의존",
                          f"Lease term not set; {tn}-yr loan after COD — {dscr}: repayment relies on new leasing and re-letting")
        ok_ = lt >= tn
        return self.T(f"임대 {lt:.0f}년 {'≥' if ok_ else '<'} 대출 COD 후 {tn}년 — {dscr}" + ("" if ok_ else ": 재임대 위험"),
                      f"Lease {lt:.0f} yrs {'≥' if ok_ else '<'} {tn}-yr loan after COD — {dscr}" + ("" if ok_ else "; re-letting risk"))

    def reserve_on(self) -> bool:
        return self.A("grace_interest").value == "reserve" and (self.A("grace_years").value or 0) > 0

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
                self.p6(), self.p7(), self.p8(), self.a1(), self.a_assumptions("A", "A2"), self.a_assumptions("B", "A3"), self.a4(),
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
        from research.disclosures import contact_line, license_items
        items += license_items(self.cfg, self.kr)
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"],
                                                         "contact": contact_line(self.cfg)})

    # --- Executive Summary --------------------------------------------------
    def headline(self) -> str:
        a, b = self.case("A"), self.case("B")
        if ok(a) and ok(b) and self.clause_sentence():
            return self.T(f"대출 한도는 총사업비의 한국 {self.pct(a.base.gearing, 0)}, 미국 {self.pct(b.base.gearing, 0)} — 한국은 {self.clause_sentence()}",
                          f"Debt capacity: {self.pct(a.base.gearing, 0)} of cost in Korea, {self.pct(b.base.gearing, 0)} in the U.S. — in Korea, {self.clause_sentence()[0].lower() + self.clause_sentence()[1:]}")
        if ok(a) and ok(b):
            ka, kb = a.base.gearing, b.base.gearing
            vk, ve = self.VAR_KR, self.VAR_EN
            ta, tb = a.tornado.iloc[0]["variable"], b.tornado.iloc[0]["variable"]
            return self.T(f"대출 한도는 총사업비의 한국 {self.pct(ka, 0)}, 미국 {self.pct(kb, 0)} — 최소 DSCR을 가장 흔드는 변수는 한국 {vk[ta]}, 미국 {vk[tb]}",
                          f"Debt capacity: {self.pct(ka, 0)} of cost in Korea, {self.pct(kb, 0)} in the U.S. — min DSCR is most sensitive to {ve[ta].lower()} (Korea) and {ve[tb].lower()} (U.S.)")
        parts = []
        if self.f.grid.ratio is not None:
            parts.append(self.T(f"한국은 계통(승인률 {self.grid_short()})과 사전 임대율({self.prelease_range()})",
                                f"Korea: grid (approval {self.grid_short()}) and pre-leasing ({self.prelease_range()})"))
        sp = self.rate_spread()
        if sp is not None:
            parts.append(self.T(f"미국은 규모와 금리({josa(self.base_label('B'))} {self.base_label('A')}보다 {sp:.2f}%p 높다)",
                                f"U.S.: scale and rates ({self.base_label('B')} {sp:.2f}pp above {self.base_label('A')})"))
        body = self.T(" · ".join(parts) + "가 대출 한도의 첫 변수", "; ".join(parts) + " — the first drivers of debt capacity")
        return body if parts else self.T("AI 데이터센터 PF: 대주의 눈으로 본 대출 한도", "AI data-centre PF: debt capacity through a lender's eyes")

    def exec_conclusions(self) -> list[str]:
        """Executive Summary 결론 문장: 헤드라인 + 세 박스 제목."""
        return [self.headline()] + [b.title for b in (self.box_korea(), self.box_us(), self.box_cost())]

    def executive(self) -> Page:
        f, r, d, pp = self.f, self.f.rates, self.f.demand, self.f.peers
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        if f.grid.ratio is not None:
            add(self.T(f"수도권 계통 승인률 ({f.grid.period})", f"Seoul-metro grid approval ({f.grid.period})"), self.grid_short(), "1", True)
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
                add(self.T(f"{self.name(c)} 최소 DSCR · Equity IRR (잔존가치 제외)", f"{self.name(c)} min DSCR · equity IRR (ex-TV)"),
                    f"{self.x(b.min_dscr)} · {self.pct(b.equity_irr)} ({self.pct(b.equity_irr_ex_tv)})", "3" if c == "A" else "6")
            else:
                add(self.T(f"{self.name(c)} 대출 한도", f"{self.name(c)} debt capacity"), self.T("입력 후 산출", "after inputs"), "3" if c == "A" else "6")
        pc = self.power_clause()
        if pc is not None:
            add(self.T("한국 Equity IRR: 전력비 별도 청구 vs 전력 포함 임대", "Korea equity IRR: power passed through vs gross rent"),
                f"{self.pct(pc[0].equity_irr)} vs {self.pct(pc[1].equity_irr)}", "7", True)
        if ok(self.case("A")) and ok(self.case("B")):
            add(self.T("원가 대비 수익률 (한국 · 미국)", "Yield on cost (Korea · U.S.)"), f"{self.pct(self.case('A').yoc)} · {self.pct(self.case('B').yoc)}", "7")
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
            cs = self.clause_sentence()
            pc0 = self.power_clause()
            title = (self.T(f"한국 40MW — 별도 청구 기준 대출 {self.money('A', pc0[0].debt)}·Equity IRR {self.pct(pc0[0].equity_irr)}, 전력 포함 임대면 {self.money('A', pc0[1].debt)}·{self.pct(pc0[1].equity_irr)}",
                            f"Korea 40 MW — passed-through power: debt {self.money('A', pc0[0].debt)}, equity IRR {self.pct(pc0[0].equity_irr)}; gross rent: {self.money('A', pc0[1].debt)}, {self.pct(pc0[1].equity_irr)}")
                     if cs and pc0 else
                     self.T(f"한국 40MW — {cs}", f"Korea 40 MW — {cs[0].lower() + cs[1:]}") if cs else
                     self.T(f"한국 40MW — {self.binding_text(b)}, 최소 DSCR {self.x(b.min_dscr)}",
                            f"Korea 40 MW — {self.binding_text(b)}; min DSCR {self.x(b.min_dscr)}"))
            pc = self.power_clause()
            if pc is not None:
                pt_r, gr_r, _ = pc
                bl.append(self.T(f"{cs} — 기준은 별도 청구(도매 임대 관행, Data Center Scouts·gr1d). CBRE 임대료의 전력 포함 정의는 원문 미확인. 도매 임대 관행상 전력은 별도 청구가 일반적",
                                 f"{cs} — base is pass-through (wholesale practice; Data Center Scouts, gr1d). CBRE's definition of whether rent includes power is not verified; in wholesale leasing, power is usually billed separately"))
            bl.append(self.T(f"{self.binding_text(b)}: 최소 DSCR {self.x(b.min_dscr)}, Equity IRR {self.irr2(b)}",
                             f"{self.binding_text(b)[0].upper() + self.binding_text(b)[1:]}: min DSCR {self.x(b.min_dscr)}, equity IRR {self.irr2(b)}"))
        else:
            num = self.pct(g.ratio) if g.ratio is not None else "—"
            cap = self.T(f"수도권 계통 승인률, 용량 기준 ({self.grid_basis()})", f"Seoul-metro grid approval by capacity ({self.grid_basis()})")
            title = self.T("한국 40MW — 계통 승인과 사전 임대율이 먼저 묶는다", "Korea 40 MW — grid approval and pre-leasing bind first")
        if self.grid_sentence() and not ok(a):
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
            num = f"${b.base.debt:,.0f}mn"                      # 큰 숫자 칸 폭에 맞춘 표기
            ms = b.margin_scenarios
            rng_ = (f" · {self.T('가산금리', 'margin')} {min(ms):.0f}~{max(ms):.0f}bp: {self.money('B', ms[min(ms)].base.debt)}~{self.money('B', ms[max(ms)].base.debt)}"
                    if ms and all(ok(x) for x in ms.values()) else "")
            cap = self.T(f"대출 한도 (원화 {self.krw(self.to_krw(b.base.debt))}, 총사업비의 {self.pct(b.base.gearing, 0)})",
                         f"Debt capacity ({self.krw(self.to_krw(b.base.debt))}; {self.pct(b.base.gearing, 0)} of cost)")
            r20 = self.rent20()
            title = (self.T(f"미국 100MW — 최소 DSCR {self.x(b.base.min_dscr)}, 하이퍼스케일 실계약 임대료가 CBRE 호가보다 20% 낮으면 {self.x(r20.min_dscr)}",
                            f"U.S. 100 MW — min DSCR {self.x(b.base.min_dscr)}; {self.x(r20.min_dscr)} if hyperscale rents sit 20% below CBRE quotes")
                     if r20 is not None else
                     self.T(f"미국 100MW — {self.binding_text(b.base)}, 최소 DSCR {self.x(b.base.min_dscr)}",
                            f"U.S. 100 MW — {self.binding_text(b.base)}; min DSCR {self.x(b.base.min_dscr)}"))
            if r20 is not None:
                bl.append(self.T(f"CBRE 호가 USD {self.B('rent_per_kw_month').value:,.0f}/kW·월은 250~500kW 기준 — 100MW 실계약이 20% 낮으면 대출 고정 시 최소 DSCR {self.x(r20.min_dscr)}(1.0배 미만)",
                                 f"CBRE's USD {self.B('rent_per_kw_month').value:,.0f}/kW-month quote is for 250–500 kW; 20% lower on a 100 MW lease gives min DSCR {self.x(r20.min_dscr)} at fixed debt (below 1.0x)"))
            bl.append(self.T(f"Equity IRR {self.irr2(b.base)}", f"Equity IRR {self.irr2(b.base)}"))
            if ms:
                bl.append(self.T(f"가산금리 미확정 → {b.margin_bp:.0f}bp 시나리오 대표값{rng_}",
                                 f"Margin not yet sourced → {b.margin_bp:.0f}bp scenario shown{rng_}"))
        else:
            num = f"{r.dgs10:.2f}%" if ok(r) else "—"
            cap = self.T(f"미 국채 10년 ({r.dgs10_date}, FRED)" if ok(r) else "미 국채 10년",
                         f"UST 10y ({r.dgs10_date}, FRED)" if ok(r) else "UST 10y")
            title = self.T("미국 100MW — 수요는 크고, 기준금리가 높다", "U.S. 100 MW — demand is large; base rates are higher")
        if sp is not None:
            bl.append(self.T(f"기준금리 차이: {self.base_label('B')} {self.base_value('B'):.2f}% − {self.base_label('A')} {self.base_value('A'):.2f}% = {sp:+.2f}%p",
                             f"Base-rate gap: {self.base_label('B')} {self.base_value('B'):.2f}% − {self.base_label('A')} {self.base_value('A'):.2f}% = {sp:+.2f}pp"))
        if ok(va):
            y, p = va.price_latest
            bl.append(self.T(f"버지니아 상업용 판매 연 {self.pct(va.va_cagr)}(미국 {self.pct(va.us_cagr)}), 요금 {p:.2f}¢/kWh({y}) — 전력비는 임차인 부담",
                             f"Virginia commercial sales {self.pct(va.va_cagr)}/yr (U.S. {self.pct(va.us_cagr)}); price {p:.2f}¢/kWh ({y}), passed through to the tenant"))
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
        elif ok(a) and "capex_mid" in a.stresses:
            cx = self.A("capex_per_mw")
            mid = self.v["sensitivity"]["capex_mid"]["A"]["value"]
            r_m = a.stresses["capex_mid"]
            bl.append(self.T(f"MW당 CAPEX {cx.value:,.0f}억원(군산 실제 PF 딜) → {mid:,.0f}억원(중간)이면 최소 DSCR {self.x(a.base.min_dscr)} → {self.x(r_m.min_dscr)}, Equity IRR {self.pct(a.base.equity_irr)} → {self.pct(r_m.equity_irr)}",
                             f"CAPEX KRW {cx.value / 10:,.1f}bn/MW (Gunsan deal) → {mid / 10:,.1f}bn (mid): min DSCR {self.x(a.base.min_dscr)} → {self.x(r_m.min_dscr)}; equity IRR {self.pct(a.base.equity_irr)} → {self.pct(r_m.equity_irr)}"))
        elif ok(a) and "capex_range_high" in a.stresses:
            cx = self.A("capex_per_mw")
            r_hi = a.stresses["capex_range_high"]
            bl.append(self.T(f"MW당 CAPEX {cx.value:,.0f}억원 → 상단 {cx.high:,.0f}억원이면 최소 DSCR {self.x(a.base.min_dscr)} → {self.x(r_hi.min_dscr)}, Equity IRR {self.pct(a.base.equity_irr)} → {self.pct(r_hi.equity_irr)}",
                             f"CAPEX KRW {cx.value / 10:,.1f}bn → {cx.high / 10:,.1f}bn per MW: min DSCR {self.x(a.base.min_dscr)} → {self.x(r_hi.min_dscr)}; equity IRR {self.pct(a.base.equity_irr)} → {self.pct(r_hi.equity_irr)}"))
        else:
            bl.append(self.T("CAPEX 영향 = 전력설비 비중 × 함의 가격 상승률 (비중 근거 확인 후 계산)",
                             "CAPEX impact = power-equipment share × implied price rise (computed once the share is sourced)"))
        return BigBox(self.pct(sc["mid"], 1, True), self.T(f"피어 3사 합산 함의 가격 상승률 ({pp.fy0}→{pp.fy1})",
                                                         f"Three peers' combined implied price rise ({pp.fy0}→{pp.fy1})"), title, bl)

    # --- 목차 ---------------------------------------------------------------
    def toc_page(self) -> Page:
        heads = [self.p1(), self.p2(), self.p3(), self.p4(), self.p5(), self.p6(), self.p7(), self.p8()]
        names = [self.T("구조", "Structure"), self.T("데이터 연결", "Data links"), self.T("대출 한도", "Debt sizing"),
                 self.T("스트레스", "Stress"), self.T("증설 옵션", "Expansion option"), self.T("한·미 비교", "Korea vs U.S."),
                 self.T("개발 수익률", "Development yield"), self.T("시사점", "Implications")]
        toc = [(n, nm, toc_line(h.extra.get("toc") or h.title), h.label) for n, nm, h in zip(["I", "II", "III", "IV", "V", "VI", "VII", "VIII"], names, heads)]
        toc.append(("App.", "Appendix", self.T("A1 예상 질의응답 · A2·A3 케이스별 가정과 출처 · A4 데이터 노트 · A5 분석 방법 · A6 용어",
                                               "A1 Q&A · A2–A3 assumptions and sources by case · A4 Data notes · A5 Methodology · A6 Glossary"), "A1–A6"))
        return Page("toc", label="ii", title=self.T("목차", "Contents"),
                    subtitle=self.T("구조 → 데이터 → 대출 한도 → 스트레스 → 옵션 → 비교 → 개발 수익률 → 시사점: 각 장의 결론",
                                    "Structure → data → sizing → stress → option → comparison → yield → implications: each section's conclusion"),
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
        gross, res = self.a_gross(), self.reserve_on()
        edges = [("sponsor", "spc", self.T("자기자본", "equity")), ("lenders", "spc", self.T("대출·DSRA", "loan, DSRA")),
                 ("tenant", "spc", self.T("임대료(전력 포함)", "gross rent") if gross else self.T("임대료·전력비", "rent, power")),
                 ("epc", "spc", self.T("시공", "build")), ("om", "spc", self.T("운영", "operate")),
                 ("power", "spc", self.T("전력(SPC 부담)", "power (SPC pays)") if gross else self.T("전력(패스스루)", "power (pass-through)"))]
        gy = int(self.A("grace_years").value or 0)
        if res:
            nodes["reserve"] = (self.T("이자유보계좌", "Interest reserve"), self.T(f"램프업 {gy}년 이자 부족분", f"{gy}-yr ramp-up interest gap"))
            edges += [("spc", "reserve", self.T("FC 적립", "funded at FC")), ("reserve", "lenders", self.T("램프업 이자", "ramp-up interest"))]
        pt = self.A("power_passthrough").value
        a = self.case("A")
        rs = (self.T(f" 이자유보계좌 {self.money('A', a.base.cons.reserve_initial)} = 램프업 {gy}년 이자 부족분 + {self.pct(a.inp.reserve_buffer, 0)} 여유, 사업비에 포함",
                     f" Interest reserve {self.money('A', a.base.cons.reserve_initial)} = {gy}-yr ramp-up interest gap + {self.pct(a.inp.reserve_buffer, 0)} buffer, inside project cost")
              if res and ok(a) else "")
        c1 = Cell(title=(self.T("SPC는 전력 포함 임대료로 전력비·대출을 감당하고, 램프업 이자 부족분은 이자유보계좌가 메운다",
                                "The SPC pays power and debt from gross rent; an interest reserve covers the ramp-up interest gap")
                         if gross and res else
                         self.T("SPC는 장기 책임임대 임대료로 대출을 갚고 전력비는 임차인이 부담(별도 청구) — 램프업 이자 부족분은 이자유보계좌가 메운다",
                                "The SPC repays debt from committed rent, power is billed to the tenant — an interest reserve covers the ramp-up gap")
                         if res else
                         self.T("SPC는 장기 책임임대 임대료로 대출을 갚고, 전력비는 임차인이 부담한다(패스스루)",
                                "The SPC repays debt from long-term committed rent; power is passed through to the tenant")),
                  src=["ksj", "lease"], chart_key="structure", chart=charts.structure(nodes, edges, c),
                  note=(self.T(f"케이스 A 기준 구조도(가상). 임대료를 전력 포함(gross)으로 보고 SPC가 전력비 부담(원문에서 전력 포함 여부 미확인 → p7에 별도 청구 비교).",
                               f"Case A structure (hypothetical). Rent treated as gross of power, so the SPC pays power (inclusion not confirmed in the source; pass-through compared on p7).")
                        if gross else
                        self.T(f"케이스 A 기준 구조도(가상). 전력비 별도 청구 {pt * 100:.0f}%(도매 임대는 kW당 임대료 + 전력 별도 청구가 일반적: Data Center Scouts·gr1d, 한·미 임대료를 같은 전력 제외 정의로 처리). CBRE 임대료의 전력 포함 정의는 원문 미확인. 도매 임대 관행상 전력은 별도 청구가 일반적. 전력 포함 임대는 p7 스트레스.",
                               f"Case A structure (hypothetical). Power billed separately, {pt * 100:.0f}% (wholesale leases quote rent per kW with power billed on top: Data Center Scouts, gr1d; both rents use one ex-power definition). CBRE's definition of whether rent includes power is not verified; in wholesale leasing, power is usually billed separately. Gross rent is a stress on p7.")) + rs)
        rows = [
            [self.T("임대차", "Lease"), self.T("임차인", "Tenant"), self.T("장기 책임임대 · 임대료 kW·월 · 연 인상", "Long-term committed lease; rent per kW-month; annual escalation"),
             self.T("사전 임대율 · 임차인 신용", "Pre-lease ratio; tenant credit")],
            [self.T("대출", "Loan"), self.T("대주단", "Lenders"),
             self.T(f"목표 DSCR · 최대 대출 비율 · 만기 · 램프업 거치 {gy}년 · DSRA · 이자유보계좌", f"Target DSCR; max gearing; tenor; {gy}-yr ramp-up grace; DSRA; interest reserve")
             if res else self.T("목표 DSCR · 최대 대출 비율 · 만기·거치 · DSRA", "Target DSCR; max gearing; tenor, grace; DSRA"),
             self.T("CFADS 변동 · 금리", "CFADS volatility; rates")],
            [self.T("EPC", "EPC"), self.T("시공사", "Contractor"), self.T("고정가 · 준공일 · 지연 배상", "Fixed price; completion date; delay LDs"),
             self.T("전력기기 가격 · 지연", "Equipment prices; delay")],
            [self.T("전력 공급", "Power supply"), self.T("전력회사", "Utility"), self.T("계통 접속 승인 · 수전 용량", "Grid-connection approval; capacity"),
             self.T("2단계 계통 승인", "Phase 2 grid approval")],
            ([self.T("전력비", "Power cost"), self.T("SPC → 전력회사", "SPC → utility"),
              self.T(f"사용량 × 단가(연 {self.pct(self.A('power_escalation').value or 0, 0)} 인상) · 전력 포함 임대료",
                     f"Usage × tariff (+{self.pct(self.A('power_escalation').value or 0, 0)}/yr); rent gross of power"),
              self.T("단가 상승 · 임대료의 전력 포함 여부", "Tariff rises; whether rent includes power")]
             if gross else
             [self.T("전력비", "Power cost"), self.T("임차인", "Tenant"), self.T(f"사용량 × 단가 패스스루 {pt * 100:.0f}%", f"Usage × tariff, {pt * 100:.0f}% pass-through"),
              self.T("패스스루 예외 조항", "Pass-through carve-outs")]),
        ]
        c2 = Cell(title=self.T("계약 다섯 개가 현금흐름을 만든다 — 대주가 보는 위험은 임대·금리·공사비·계통",
                               "Five contracts shape the cash flow — lenders watch leasing, rates, cost and grid"),
                  src=["ksj", "power"] if gross else ["ksj"], table=TableSpec([self.T("계약", "Contract"), self.T("상대방", "Party"), self.T("핵심 조건", "Key terms"),
                                                self.T("대주 관점 위험", "Lender risk")], rows, [0.15, 0.15, 0.42, 0.28], ["L", "L", "L", "L"],
                                               shade_rows={0, 1}, font_size=8.2),
                  note=self.T("가상 구조. 실제 계약 조건은 사업별로 다르다", "Hypothetical structure; actual terms vary by project"))
        rr = self.f.rates
        base_a = f"{self.base_label('A')} ({self.base_value('A'):.2f}%)" if ok(rr) else "ECOS"
        base_b = f"DGS10 ({rr.dgs10:.2f}%)" if ok(rr) else "FRED"
        thr = g.threshold_mw
        rows3 = [
            [self.T("위치", "Location"), self.T("수도권 외곽(인천·경기 서부)", "Outer Seoul metro (Incheon, W. Gyeonggi)"), self.T("미국 버지니아", "Virginia, U.S.")],
            [self.T("용량(IT 부하)", "Capacity (IT load)"), self.T("40MW = 1단계 20MW 확정 + 2단계 20MW 옵션", "40 MW = 20 MW firm + 20 MW option"),
             self.T("100MW 단일 단계", "100 MW, single phase")],
            [self.T("조달 통화 · 기준금리", "Currency · base rate"), f"KRW · {base_a}", f"USD · {base_b}"],
            [self.T("설정 근거", "Rationale"),
             self.T(f"계통 승인률 {self.grid_short()} · 전력계통영향평가 {thr:.0f}MW 이상 적용 · 국내 운영 사례 40MW급" if g.ratio is not None else "계통 제약",
                    f"Grid approval {self.grid_short()}; grid impact assessment from {thr:.0f} MW; domestic operating scale ~40 MW" if g.ratio is not None else "Grid constraint"),
             self.T("하이퍼스케일 규모 · 버지니아 상업용 판매 성장(EIA)", "Hyperscale scale; Virginia commercial sales growth (EIA)")],
        ]
        c3 = Cell(title=self.T("한국은 20MW씩 나눠 짓고, 미국은 100MW를 한 번에 — 같은 엔진, 다른 파라미터",
                               "Korea builds in 20 MW steps, the U.S. in one 100 MW block — same engine, different parameters"),
                  src=["grid", "law", "ecos", "fred", "eia"],
                  table=TableSpec(["", self.T("케이스 A (메인)", "Case A (main)"), self.T("케이스 B (비교)", "Case B (comparison)")], rows3,
                                  [0.2, 0.42, 0.38], ["L", "L", "L"], shade_rows={1}, font_size=8.4),
                  note=self.T("실존 프로젝트 아님. 기준금리는 2026-10-20 이전 최근 영업일 값", "Not real projects. Base rates: latest business day on or before 2026-10-20"))
        if g.ratio is not None:
            labs = ([self.T("건수 기준", "By count")] if g.ratio_n is not None else []) + [self.T("용량 기준", "By capacity")]
            vals = ([g.ratio_n * 100] if g.ratio_n is not None else []) + [g.ratio * 100]
            c4 = Cell(title=self.T(f"수도권 신규 계통 신청의 승인률은 {self.grid_short()} — 2단계를 '옵션'으로 둔 이유",
                                   f"Seoul-metro grid approval is {self.grid_short()} — why phase 2 is an option"),
                      src=["grid"], legend=[(c["brown_mid"], self.T("건수 기준", "By count")), (c["gold"], self.T("용량 기준", "By capacity"))], unit="%",
                      chart_key="grid", chart=charts.bars(labs, vals, [c["brown_mid"], c["gold"]][-len(vals):], c, lambda v: f"{v:.1f}%"),
                      note=self.T(f"{self.grid_sentence()}. {self.grid_basis()}. {thr:.0f}MW 이상은 전력계통영향평가 대상",
                                  f"{self.grid_sentence()}. {self.grid_basis()}. Projects ≥{thr:.0f} MW need a grid impact assessment"))
        else:
            c4 = self.pending(self.T("계통 신청·승인", "Grid applications and approvals"), ["grid"], Unavailable("계통 통계 없음", "Grid data missing"))
        title = (self.T(f"구조: 한국은 전력 포함 임대 + 램프업 {gy}년 이자유보계좌, 미국은 전력비 패스스루 — 20MW 확정 + 20MW 옵션 vs 100MW 단일",
                        f"Structure: Korea — gross rent plus a {gy}-yr ramp-up interest reserve; U.S. — power pass-through; 20 MW + 20 MW option vs 100 MW")
                 if gross and res else
                 self.T(f"구조: 장기 책임임대 + 전력비 별도 청구 SPC, 한국은 램프업 {gy}년 이자유보계좌 — 20MW 확정 + 20MW 옵션 vs 미국 100MW 단일",
                        f"Structure: committed leases with power billed separately; Korea adds a {gy}-yr ramp-up interest reserve — 20 MW + 20 MW option vs U.S. 100 MW")
                 if res else
                 self.T("구조: 장기 책임임대 + 전력비 패스스루 SPC — 한국은 20MW 확정 + 20MW 옵션, 미국은 100MW 단일",
                        "Structure: an SPC with long-term committed leases and power pass-through — Korea 20 MW + 20 MW option, U.S. 100 MW"))
        sub = self.T(f"케이스 A(메인) 수도권 외곽 40MW · 원화, 케이스 B(비교) 버지니아 100MW · 달러 — " + (self.grid_sentence() or ""),
                     f"Case A (main) 40 MW outer Seoul metro, KRW; Case B (comparison) 100 MW Virginia, USD — " + (self.grid_sentence() or ""))
        return Page("body", "1", title, sub, [c1, c2, c3, c4])

    # --- p2 Vol.1 데이터 연결 -----------------------------------------------
    def p2(self) -> Page:
        c, d, r, pp, va = self.c, self.f.demand, self.f.rates, self.f.peers, self.f.va
        cells = []
        pre = self.A("prelease").value
        stab = self.A("stabilized_occupancy").value
        ca = self.case("A")
        if ok(d) and ok(ca):
            from src.analysis.pf_model import BASE as PF_BASE, occupancy
            from .data import scenario_inputs
            n = 12
            yrs = list(range(1, n + 1))
            cols = {"downside": c["warm_grey"], "base": c["gold"], "upside": c["brown_dark"]}
            sin = {s_: scenario_inputs(ca.inp, d, s_) for s_ in SCENARIOS}
            series = [(self.scen(s_), list(occupancy(sin[s_], PF_BASE, n) * 100), cols[s_], 2.2 if s_ == "base" else 1.4) for s_ in SCENARIOS]
            ry = {s_: sin[s_].ramp_years for s_ in SCENARIOS}
            if ry["base"] is not None:
                rtitle = self.T(f"사전 임대율 {self.pct(pre)} → 안정화 {self.pct(stab, 0)}: 램프업 기준 {ry['base']:.0f}년, IEA 성장률로 하단 {ry['downside']:.1f}년·상단 {ry['upside']:.1f}년",
                                f"Pre-lease {self.pct(pre)} → stabilised {self.pct(stab, 0)}: ramp-up {ry['base']:.0f} yrs (base); IEA growth implies {ry['downside']:.1f} (low) and {ry['upside']:.1f} yrs (high)")
                rnote_kr = f"시나리오 램프업 = 기준 {ry['base']:.0f}년(저자 판단) × 기준 성장률 ÷ 시나리오 성장률"
                rnote_en = f"Scenario ramp-up = base {ry['base']:.0f} yrs (author's judgment) × base growth ÷ scenario growth"
            else:
                rtitle = self.T(f"사전 임대율 {self.pct(pre)} → 안정화 {self.pct(stab, 0)}: IEA 수요 성장률로 램프업",
                                f"Pre-lease {self.pct(pre)} → stabilised {self.pct(stab, 0)}: ramp-up at IEA demand growth")
                rnote_kr, rnote_en = "가동률 = 사전 임대율 × (1+성장률)^t, 안정화 가동률 상한", "Occupancy = pre-lease × (1+growth)^t, capped at stabilised occupancy"
            cells.append(Cell(
                title=rtitle,
                src=["iea", "market"], legend=[(cols[s_], f"{self.scen(s_)} {self.pct(d.growth[s_])}") for s_ in SCENARIOS],
                unit=self.T("가동률 %, COD 후 연차 (케이스 A)", "Occupancy %, years after COD (Case A)"), chart_key="ramp",
                chart=charts.lines(yrs, series, c, lambda v: f"{v:.0f}%", right=0.84),
                note=self.T(f"성장률 = IEA 데이터센터 전력 {d.years[0]}→{d.years[1]} 연평균({self.num(d.values['base_year'])}→하단 {self.num(d.values['downside'])}·기준 {self.num(d.values['base'])}·상단 {self.num(d.values['upside'])}TWh). "
                            + rnote_kr,
                            f"Growth = IEA data-centre power CAGR {d.years[0]}→{d.years[1]} ({self.num(d.values['base_year'])}→low {self.num(d.values['downside'])}, base {self.num(d.values['base'])}, high {self.num(d.values['upside'])} TWh). "
                            + rnote_en)))
        else:
            cells.append(self.pending(self.T("수요 → 가동률 램프업", "Demand → occupancy ramp-up"), ["iea"], d if not ok(d) else (ca if not ok(ca) else Unavailable("", "", []))))
        if ok(r) and not r.monthly.empty:
            m = r.monthly
            sp = self.rate_spread()
            cells.append(Cell(
                title=self.T(f"기준금리({r.ktb_date}): 국고채 3년 {r.ktb_3y:.2f}%·10년 {r.ktb_10y:.2f}%, 미 국채 10년 {r.dgs10:.2f}% — 모델 기준금리 차이 {sp:.2f}%p",
                             f"Base rates ({r.ktb_date}): KTB 3y {r.ktb_3y:.2f}%, 10y {r.ktb_10y:.2f}%; UST 10y {r.dgs10:.2f}% — model base-rate gap {sp:.2f}pp"),
                src=["ecos", "fred"], legend=[(c["brown_mid"], self.T("국고채 3년", "KTB 3y")), (c["brown_dark"], self.T("국고채 10년", "KTB 10y")),
                                              (c["gold"], self.T("미 국채 10년", "UST 10y"))], unit=self.T("% (월평균)", "% (monthly avg.)"),
                chart_key="rates",
                chart=charts.ts_lines(list(m["month"]), [(self.T("국고채 3년", "KTB 3y"), list(m["ktb_3y"]), c["brown_mid"], 1.4),
                                                        (self.T("국고채 10년", "KTB 10y"), list(m["ktb_10y"]), c["brown_dark"], 1.6),
                                                        (self.T("미 국채 10년", "UST 10y"), list(m["DGS10"]), c["gold"], 2.2)], c,
                                      lambda v: f"{v:.2f}%", end_values=[r.ktb_3y, r.ktb_10y, r.dgs10]),
                note=self.T(f"선 = 월평균, 끝 라벨 = 기준일 값. 모델 기준금리: 한국 = {self.base_label('A')}, 미국 = {self.base_label('B')} ({r.dgs10_date}). 가산금리는 별도 가정",
                            f"Lines = monthly averages; end labels = as-of values. Model base rates: Korea = {self.base_label('A')}; U.S. = {self.base_label('B')} ({r.dgs10_date}). Margins are separate")))
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
            yp = [int(x) for x in va.va_price.index]
            ser = [(self.T("버지니아", "VA"), list(va.va_price.values), c["gold"], 2.2)]
            if va.us_price is not None:
                ser.append((self.T("미국", "U.S."), list(va.us_price.reindex(yp).values), c["warm_grey"], 1.5))
            my, mx = va.price_max_yoy
            cells.append(Cell(
                title=self.T(f"버지니아: 상업용 판매 연 {self.pct(va.va_cagr)}(미국 {self.pct(va.us_cagr)}), 요금 {p:.2f}¢/kWh({y}) — 수요는 빠르고 요금은 미국보다 낮다"
                             if va.us_price is not None and p < float(va.us_price.iloc[-1]) else
                             f"버지니아: 상업용 판매 연 {self.pct(va.va_cagr)}(미국 {self.pct(va.us_cagr)}), 요금 {p:.2f}¢/kWh({y})",
                             f"Virginia: commercial sales {self.pct(va.va_cagr)}/yr (U.S. {self.pct(va.us_cagr)}); price {p:.2f}¢/kWh ({y}) — faster demand, cheaper power than the U.S."
                             if va.us_price is not None and p < float(va.us_price.iloc[-1]) else
                             f"Virginia: commercial sales {self.pct(va.va_cagr)}/yr (U.S. {self.pct(va.us_cagr)}); price {p:.2f}¢/kWh ({y})"),
                src=["eia"], legend=[(c["gold"], self.T("버지니아", "Virginia")), (c["warm_grey"], self.T("미국 전체", "U.S. total"))],
                unit=self.T("상업용 평균 요금, 센트/kWh (명목)", "Commercial average price, cents/kWh (nominal)"), chart_key="va_price",
                chart=charts.lines(yp, ser, c, lambda v: f"{v:.2f}"),
                note=self.T(f"케이스 B 수요 근거: 버지니아 상업용 판매 {va.base_year}→{va.last_year} 연 {self.pct(va.va_cagr)}, {va.last_year}년 {self.pct(va.va_yoy_last, 1, True)}. "
                            f"전력비 단가 = 버지니아 {y}년 요금. 최대 연간 상승 {my}년 {self.pct(mx, 1, True)} (민감도 p8)",
                            f"Case B demand: Virginia commercial sales {va.base_year}→{va.last_year} {self.pct(va.va_cagr)}/yr, {self.pct(va.va_yoy_last, 1, True)} in {va.last_year}. "
                            f"Power price = Virginia {y}. Largest annual rise {self.pct(mx, 1, True)} in {my} (sensitivity on p8)")))
        else:
            cells.append(self.pending(self.T("버지니아 전력", "Virginia power"), ["eia"], va))
        d_ok = ok(d)
        title = self.T(f"Vol.1 데이터를 PF 가정으로: 수요 성장 {self.pct(d.growth['base'])}(기준), {josa(self.base_label('B'))} {self.base_label('A')}보다 {self.rate_spread():.2f}%p 높고, 피어 이익률은 가격 결정력을 시사"
                       if d_ok and self.rate_spread() is not None else "Vol.1 데이터를 PF 가정으로 연결",
                       f"Vol.1 data into PF inputs: base demand growth {self.pct(d.growth['base'])}, {self.base_label('B')} {self.rate_spread():.2f}pp above {self.base_label('A')}, peer margins point to pricing power"
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
            sub = self.T(f"엔진은 준비됨 — 임대료 kW당 월 {self.A('rent_per_kw_month').value:,.0f}원, 사전 임대율 {self.prelease_range()}(기준 {self.pct(self.A('prelease').value)}), {self.base_label('A')} 기준",
                         f"Engine ready — rent KRW {self.A('rent_per_kw_month').value:,.0f}/kW-month, pre-lease {self.prelease_range()} (base {self.pct(self.A('prelease').value)}), {self.base_label('A')} base")
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
        def mfmt(v):
            return f"{v:,.0f}" if abs(v) >= 0.5 else "0"           # −0 표기 방지
        unit = self.v["cases"][case]["money_unit_kr" if self.kr else "money_unit_en"]
        res = inp.grace_interest == "reserve" and inp.grace_years > 0
        g = inp.grace_years
        dscr_show = list(o["dscr"][:n_show])
        if res:                                                   # 램프업 거치기간 = 이자유보계좌 구간 → DSCR 선은 상환 기간만
            dscr_show = [float("nan") if i < g else v for i, v in enumerate(dscr_show)]
        grace_kr = (f"COD 후 램프업 {g}년 이자만 납부(부족분은 이자유보계좌), 이후 원금 sculpting {inp.tenor_years - g}년" if res
                    else f"COD 후 상환 {inp.tenor_years}년, COD 후 추가 거치 {g}년")
        grace_en = (f"after COD, {g} ramp-up years interest-only (gap from the interest reserve), then {inp.tenor_years - g} yrs sculpted principal" if res
                    else f"{inp.tenor_years} yrs repayment after COD; extra grace after COD {g} yrs")
        c1 = Cell(title=self.T(f"CFADS ÷ 목표 DSCR {inp.target_dscr:.2f}배로 원리금을 깎으면 대출 한도 {self.money(case, b.sculpt_debt)}",
                               f"Sculpting debt service at CFADS ÷ {inp.target_dscr:.2f}x gives {self.money(case, b.sculpt_debt)}"),
                  src=["ksj"], legend=[(c["brown_mid"], "CFADS"), (c["gold"], self.T("원리금", "Debt service")), (c["charcoal"], "DSCR")],
                  unit=f"{unit}, " + self.T("COD 후 연차", "years after COD"), chart_key=f"cfads_{case}",
                  chart=charts.cfads_ds(yrs, list(o["cfads"][:n_show]), list(o["debt_service"][:n_show]), dscr_show,
                                        c, inp.target_dscr, ("CFADS", self.T("원리금", "DS"), self.T("목표", "Target")), mfmt),
                  note=self.T(f"CFADS = EBITDA − 법인세{'(전력비 포함 비용 차감)' if inp.power_modeled() and inp.power_passthrough < 1 else ''}. 대출 만기 = 건설 {inp.construction_quarters / 4:g}년 + {grace_kr}. 기준 시나리오"
                            + (f". 감가상각 정액 {inp.dep_years}년" if inp.dep_years else ". 감가상각 미반영(기간 미입력 → 법인세 보수적)")
                            + (". DSCR 선 = 원금 상환 기간" if res else ""),
                            f"CFADS = EBITDA − tax{' (after power cost)' if inp.power_modeled() and inp.power_passthrough < 1 else ''}. Tenor = {inp.construction_quarters / 4:g} yrs construction + {grace_en}. Base scenario"
                            + (f"; straight-line depreciation {inp.dep_years} yrs" if inp.dep_years else ". No depreciation (life not set → tax conservative)")
                            + ("; DSCR line = principal repayment years" if res else "")))
        cons = b.cons
        rows = [[self.T("Sculpting 한도 (목표 DSCR)", "Sculpting limit (target DSCR)"), self.money(case, b.sculpt_debt)],
                [self.T(f"최대 대출 비율 한도 ({self.pct(inp.max_gearing, 0)})", f"Gearing limit ({self.pct(inp.max_gearing, 0)})"), self.money(case, b.gearing_debt)],
                [self.T("채택 대출 한도 (작은 값)", "Debt adopted (lower)"), self.money(case, b.debt)],
                [self.T("구속 조건 · 유효 DSCR", "Binding constraint · effective DSCR"), f"{self.binding_text(b)} · {self.x(b.effective_dscr)}"],
                ([self.T("총사업비 = CAPEX + 건설이자 + DSRA + 이자유보계좌", "Cost = CAPEX + IDC + DSRA + interest reserve"),
                  f"{self.money(case, cons.uses)} = {self.money(case, cons.capex)} + {self.money(case, cons.idc)} + {self.money(case, cons.dsra_initial)} + {self.money(case, cons.reserve_initial)}"]
                 if res else
                 [self.T("총사업비 = CAPEX + 건설이자 + 초기 DSRA", "Total cost = CAPEX + IDC + initial DSRA"),
                  f"{self.money(case, cons.uses)} = {self.money(case, cons.capex)} + {self.money(case, cons.idc)} + {self.money(case, cons.dsra_initial)}"]),
                [self.T("자기자본 · 대출 비율", "Equity · gearing"), f"{self.money(case, cons.equity)} · {self.pct(b.gearing)}"],
                [self.T("최소 · 평균 DSCR · LLCR", "Min · avg DSCR · LLCR"), f"{self.x(b.min_dscr)} · {self.x(b.avg_dscr)} · {self.x(b.llcr)}"],
                [self.T("Project IRR · Equity IRR · 회수기간(FC 기준)", "Project IRR · equity IRR · payback (from FC)"),
                 f"{self.pct(b.project_irr)} · {self.pct(b.equity_irr)} · {self.yrs(b.payback_years)}"]]
        if b.terminal_value:
            rows.append([self.T(f"잔존가치 제외 Project IRR · Equity IRR (cap rate {self.pct(inp.exit_cap_rate)})", f"Ex-TV project IRR · equity IRR (cap rate {self.pct(inp.exit_cap_rate)})"),
                         f"{self.pct(b.project_irr_ex_tv)} · {self.pct(b.equity_irr_ex_tv)}"])
        if res:
            gap = float((o["interest"][:g] - o["cfads"][:g]).clip(lower=0).sum())
            rows.insert(5, [self.T(f"이자유보계좌 = 램프업 {g}년 이자 부족분 {mfmt(gap)} × (1 + {self.pct(inp.reserve_buffer, 0)})",
                                   f"Interest reserve = {g}-yr interest gap {mfmt(gap)} × (1 + {self.pct(inp.reserve_buffer, 0)})"),
                            f"{self.money(case, cons.reserve_initial)} ({self.T('인출', 'drawn')} {mfmt(b.reserve_used)})"])
            rows.append([self.T("램프업 최소 CFADS ÷ 이자 (유보계좌 인출 전)", "Ramp-up min CFADS ÷ interest (before reserve)"), self.x(b.min_icr_grace)])
        if a.negative_amort:
            rows.append([self.T("진단: 매년 이자 현금 지급 제약 시 한도", "Check: debt if interest is paid in cash every year"),
                         self.money(case, a.interest_cover_debt)])
        neg = a.negative_amort
        neg_note = self.T(f" {', '.join(map(str, neg))}년차 원리금이 이자보다 작아 잔액이 늘어난다(음수 원금) — 램프업 이자 적립·자본화 없이는 마지막 행 한도가 현실적",
                          f" In year(s) {', '.join(map(str, neg))} debt service is below interest (negative principal); without a ramp-up interest reserve the last row is the realistic limit") if neg else ""
        c2 = Cell(title=self.T(f"대출 한도 {self.money(case, b.debt)} — {self.binding_text(b)}", f"Debt {self.money(case, b.debt)} — {self.binding_text(b)}"),
                  src=["ksj", "finance"] if res else ["ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("값", "Value")], rows, [0.48, 0.52], ["L", "R"],
                                  shade_rows={2} | ({len(rows) - 1} if neg else set()) | ({5} if res else set()),
                                  gold_cells={(2, 1)} | ({(5, 1)} if res else set()), brick_cells={(len(rows) - 1, 1)} if neg else set(), font_size=8.0),
                  note=self.T("대출 한도 = min(sculpting, 최대 대출 비율 × 총사업비). 총사업비에 건설이자(IDC)·초기 DSRA" + ("·이자유보계좌" if res else "") + " 포함, 반복 계산."
                              + (" 최소·평균 DSCR = 원금 상환 기간 기준. 램프업 구조는 이자 원금 가산 대신 유보계좌(저자 판단, Gridlines 2026: 램프업 의존 사업은 초기 레버리지가 낮고 지분이 더 필요)" if res else "")
                              + (f". LLCR {self.x(b.llcr)} < 최소 DSCR {self.x(b.min_dscr)}: LLCR에는 램프업 {g}년 적자(유보계좌로 충당)가 포함되기 때문" if res and b.llcr < b.min_dscr - 1e-6 else ""),
                              "Debt = min(sculpting, max gearing × total cost); cost includes IDC and initial DSRA" + (" and the interest reserve" if res else "") + ", solved iteratively."
                              + (" Min/avg DSCR over principal repayment years. Ramp-up uses a reserve, not capitalised interest (author's judgment; Gridlines 2026: ramp-up-dependent projects carry lower initial leverage and more equity)" if res else "")
                              + (f". LLCR {self.x(b.llcr)} < min DSCR {self.x(b.min_dscr)} because LLCR includes the {g}-yr ramp-up deficit (covered by the reserve)" if res and b.llcr < b.min_dscr - 1e-6 else "")) + neg_note)
        pick = sorted({1, 2, 3, min(5, inp.tenor_years), min(10, inp.tenor_years), inp.tenor_years} | ({g + 1} if res else set()))
        wrows = []
        for y in pick:
            r_ = o.iloc[y - 1]
            dist = mfmt(r_["distribution"])
            if r_["lockup_in"] > 0:
                dist = self.T(f"0 (잠금 {mfmt(r_['lockup_in'])})", f"0 (locked {mfmt(r_['lockup_in'])})")
            row_ = [str(y), mfmt(r_["cfads"]), mfmt(r_["interest"]), mfmt(r_["principal"])]
            if res:
                row_.append(mfmt(-r_["reserve_draw"] - r_["reserve_release"]) if (r_["reserve_draw"] or r_["reserve_release"]) else "–")
            row_ += [mfmt(r_["dsra_topup"] - r_["dsra_draw"] - r_["dsra_release"]), dist,
                     self.x(r_["dscr"]) if not (res and y <= g) else self.T(f"({self.x(r_['dscr'])})", f"({self.x(r_['dscr'])})")]
            wrows.append(row_)
        wh = [self.T("연차", "Year"), "CFADS", self.T("이자", "Interest"), self.T("원금", "Princ." if res else "Principal")]
        ww = [0.1, 0.16, 0.14, 0.14]
        if res:
            wh.append(self.T("유보계좌", "Reserve"))
            ww = [0.08, 0.13, 0.12, 0.12, 0.13]
        wh += [self.T("DSRA 순적립", "DSRA net"), self.T("배당", "Distrib."), "DSCR"]
        ww += [0.16, 0.16, 0.14] if not res else [0.14, 0.14, 0.14]
        c3 = Cell(title=(self.T(f"상환 Waterfall: 램프업 {g}년은 이자만, 부족분은 이자유보계좌 → 이후 원금 → DSRA({inp.dsra_months:.0f}개월) → 배당",
                                f"Waterfall: {g} ramp-up years interest-only, gap from the reserve → then principal → DSRA ({inp.dsra_months:.0f} months) → distributions")
                         if res else
                         self.T(f"상환 Waterfall: CFADS → 이자 → 원금 → DSRA({inp.dsra_months:.0f}개월) → 배당",
                                f"Waterfall: CFADS → interest → principal → DSRA ({inp.dsra_months:.0f} months) → distributions")),
                  src=["ksj"], unit=unit,
                  table=TableSpec(wh, wrows, ww, ["C"] + ["R"] * (len(wh) - 1), font_size=8.0),
                  note=self.T(("유보계좌: 음수 = 인출(이자 부족분), 거치 마지막 해 잔액은 배당으로 해제. 괄호 DSCR = 램프업 CFADS ÷ 이자(유보계좌 인출 전). " if res else "")
                              + "DSRA 목표 = 다음 해 원리금 × 개월/12, 만기 해에 해제. 원금 음수 = 원리금 < 이자(잔액 증가)",
                              ("Reserve: negative = draw (interest gap); the balance is released to equity in the last grace year. Bracketed DSCR = ramp-up CFADS ÷ interest before reserve. " if res else "")
                              + "DSRA target = next year's debt service × months/12, released at maturity. Negative principal = debt service below interest"))
        t0_ = inp.grace_years if inp.grace_interest == "reserve" else 0
        dc_ = (o["cfads_contracted"] / o["debt_service"]).iloc[t0_:inp.tenor_years]
        c_year = int(o["year"].iloc[t0_ + int(np.nanargmin(dc_.to_numpy()))]) if len(dc_) else None
        srows = []
        for s in SCENARIOS:
            r_ = a.scenarios[s]
            lab_s = (self.T(f"{self.scen(s)} (램프업 {r_.inp.ramp_years:.1f}년)", f"{self.scen(s)} (ramp {r_.inp.ramp_years:.1f} yrs)")
                     if r_.inp.ramp_years is not None else f"{self.scen(s)} ({self.pct(r_.inp.ramp_growth)})")
            srows.append([lab_s, self.money(case, r_.debt), self.x(r_.min_dscr), self.x(r_.llcr),
                          self.pct(r_.project_irr), self.pct(r_.equity_irr), self.x(r_.min_dscr_contracted)])
        dd = sorted(x.debt for x in a.scenarios.values())
        same_b = all(x.binding == "gearing" for x in a.scenarios.values())
        dtxt = self.money(case, dd[-1]) if same_b else f"{self.money(case, dd[0])}~{self.money(case, dd[-1])}"
        c4 = Cell(title=(self.T(f"수요 시나리오가 달라도 대출 한도는 {dtxt}{'(최대 대출 비율 상한)' if same_b else ''} — 최소 DSCR {self.x(min(x.min_dscr for x in a.scenarios.values()))}~{self.x(max(x.min_dscr for x in a.scenarios.values()))}",
                                f"Debt barely moves across demand scenarios ({dtxt}{', gearing cap' if same_b else ''}); min DSCR {self.x(min(x.min_dscr for x in a.scenarios.values()))}–{self.x(max(x.min_dscr for x in a.scenarios.values()))}")
                         if dd[-1] - dd[0] < 0.02 * dd[-1] else
                         self.T(f"수요 시나리오별 대출 한도 {self.money(case, dd[0])}~{self.money(case, dd[-1])}",
                                f"Debt by demand scenario: {self.money(case, dd[0])}–{self.money(case, dd[-1])}")),
                  src=["iea", "ksj"],
                  table=TableSpec([self.T("시나리오(성장률)", "Scenario (growth)"), self.T("대출 한도", "Debt"), self.T("최소 DSCR", "Min DSCR"), "LLCR",
                                   "Project IRR", "Equity IRR", self.T("계약분 DSCR", "Contr. DSCR")], srows,
                                  [0.2, 0.17, 0.12, 0.1, 0.13, 0.13, 0.15], ["L", "R", "R", "R", "R", "R", "R"], shade_rows={1}, font_size=8.2),
                  note=self.T("시나리오마다 대출을 다시 산정(sizing). 램프업 = 기준 기간 × IEA 기준 성장률 ÷ 시나리오 성장률. "
                              f"계약분 DSCR = 사전 임대율 {self.pct(inp.prelease)}의 계약 임대료만으로 본 원금 상환 기간 최소 DSCR"
                              + (f"({c_year}년차)" if c_year else "") + " — 앵커 임차인 부재 위험을 보여주는 지표",
                              "Debt re-sized per scenario. Ramp-up = base period × IEA base growth ÷ scenario growth. "
                              f"Contracted DSCR = min DSCR over principal repayment years on {self.pct(inp.prelease)} pre-leased rent only"
                              + (f" (year {c_year})" if c_year else "") + " — a gauge of the risk of having no anchor tenant"))
        title = self.T(f"{self.name(case)} 대출 한도 {self.money(case, b.debt)}(총사업비의 {self.pct(b.gearing, 0)}) — {self.binding_text(b)}",
                       f"{self.name(case)} debt capacity {self.money(case, b.debt)} ({self.pct(b.gearing, 0)} of cost) — {self.binding_text(b)}")
        if b.min_dscr_contracted < 0:
            ctxt = self.T(f"계약 임대료(사전 임대 {self.pct(inp.prelease)})만으로는 OPEX·전력비도 못 덮는다(최소 DSCR {self.x(b.min_dscr_contracted)})",
                          f"contracted rent ({self.pct(inp.prelease)} pre-let) does not even cover OPEX and power (min DSCR {self.x(b.min_dscr_contracted)})")
        else:
            ctxt = self.T(f"계약 임대료만으로는 최소 DSCR {self.x(b.min_dscr_contracted)}", f"on contracted rent only, min DSCR {self.x(b.min_dscr_contracted)}")
        rs_ = (self.T(f" · 이자유보계좌 {self.money(case, b.cons.reserve_initial)}", f" · interest reserve {self.money(case, b.cons.reserve_initial)}") if res else "")
        sub = self.T(f"최소 DSCR {self.x(b.min_dscr)} · LLCR {self.x(b.llcr)} · Equity IRR {self.irr2(b)}{rs_}",
                     f"Min DSCR {self.x(b.min_dscr)} · LLCR {self.x(b.llcr)} · equity IRR {self.irr2(b)}{rs_}")
        return title, sub, [c1, c2, c3, c4]

    # --- p4 민감도·스트레스 ---------------------------------------------------
    VAR_KR = {"rent": "임대료 ±10%", "occupancy": "가동률 ±10%", "rate": "금리 ±100bp", "delay": "건설 지연", "prelease": "사전 임대율",
              "capex": "CAPEX(전력기기 가격)", "capex_range": "CAPEX(가정 범위)", "opex": "OPEX ±20%", "rent_extra": "임대료 −20%",
              "power": "전력단가 ±10%"}
    VAR_EN = {"rent": "Rent ±10%", "occupancy": "Occupancy ±10%", "rate": "Rates ±100bp", "delay": "Construction delay",
              "prelease": "Pre-lease ratio", "capex": "CAPEX (equipment prices)", "capex_range": "CAPEX (assumed range)",
              "opex": "OPEX ±20%", "rent_extra": "Rent −20%", "power": "Power price ±10%"}
    BE_KR = {"rent_mult": "임대료 (기준 대비)", "occ_mult": "가동률 (기준 대비)", "prelease": "사전 임대율", "capex_mult": "CAPEX (기준 대비)",
             "opex_mult": "OPEX (기준 대비)", "rate_shift": "기준금리 변화", "delay_quarters": "건설 지연", "power_mult": "전력단가 (기준 대비)"}
    BE_EN = {"rent_mult": "Rent (vs base)", "occ_mult": "Occupancy (vs base)", "prelease": "Pre-lease ratio", "capex_mult": "CAPEX (vs base)",
             "opex_mult": "OPEX (vs base)", "rate_shift": "Base-rate change", "delay_quarters": "Construction delay", "power_mult": "Power price (vs base)"}

    def be_fmt(self, var: str, v: float | None, inp) -> str:
        if v is None:
            return self.T("범위 내 없음", "none in range")
        if var in ("rent_mult", "occ_mult", "capex_mult", "opex_mult", "power_mult"):
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
            res_note = ""
            if a.inp.grace_interest == "reserve" and a.inp.grace_years > 0:
                pl = a.stresses.get("prelease_low")
                used = ""
                if pl is not None:
                    used = self.T(f"(사전 임대율 {self.pct(self.A('prelease').low)}면 유보계좌 인출 {self.money('A', pl.reserve_used)} / 적립 {self.money('A', a.base.cons.reserve_initial)}, DSRA 이후 부족 {self.money('A', pl.grace_shortfall)})",
                                  f" (pre-lease {self.pct(self.A('prelease').low)}: reserve draw {self.money('A', pl.reserve_used)} of {self.money('A', a.base.cons.reserve_initial)}, uncovered after DSRA {self.money('A', pl.grace_shortfall)})")
                res_note = self.T(f" 최소 DSCR = 원금 상환 기간 기준: 사전 임대율은 램프업 {a.inp.grace_years}년(유보계좌 구간)에만 영향{used}.",
                                  f" Min DSCR covers principal repayment years: pre-lease only affects the {a.inp.grace_years}-yr ramp-up (reserve period){used}.")
            pg = a.stresses.get("power_gross")
            pg_note = (self.T(f" 전력 포함 임대(SPC 부담)로 바뀌면(대출 고정) 최소 DSCR {self.x(pg.min_dscr)}, 유보계좌·DSRA 이후 원리금 부족 {self.money('A', float(pg.ops['shortfall'].sum()))} — p7.",
                              f" If rent turns gross (SPC pays power, debt fixed): min DSCR {self.x(pg.min_dscr)}, uncovered debt service {self.money('A', float(pg.ops['shortfall'].sum()))} — p7.")
                       if pg is not None else "")
            c1 = Cell(title=self.T(f"최소 DSCR을 가장 크게 흔드는 변수는 {vn[top['variable']]} ({self.x(top['low'])}~{self.x(top['high'])})",
                                   f"{vn[top['variable']]} moves min DSCR the most ({self.x(top['low'])}–{self.x(top['high'])})"),
                      src=["ksj", "dart"], legend=[(c["brick"], self.T("불리", "Adverse")), (c["brown_mid"], self.T("유리", "Favourable"))],
                      unit=self.T(f"최소 DSCR (기준 {self.x(a.base.min_dscr)})", f"Min DSCR (base {self.x(a.base.min_dscr)})"), chart_key="tornado_A",
                      chart=charts.tornado(rows, a.base.min_dscr, c, lambda v: f"{v:.2f}", ref=1.0, ref_label="1.0x"),
                      note=self.T(f"대출 스케줄은 기준 케이스로 고정. 건설 지연 = +{max(sc['delay_quarters'])}분기, 사전 임대율 = {self.prelease_range()}, "
                                  f"CAPEX = {self.capex_range_text()}, OPEX ±20%(출처 없는 저자 판단)" + (", 전력단가 ±10%" if "power" in set(t["variable"]) else "") + ".",
                                  f"Debt schedule fixed at base. Delay = +{max(sc['delay_quarters'])} quarters; pre-lease {self.prelease_range()}; "
                                  f"CAPEX = {self.capex_range_text()}; OPEX ±20% (unsourced judgment)" + ("; power price ±10%" if "power" in set(t["variable"]) else "") + ".") + res_note + tt_note + pg_note)
            bn = self.BE_KR if self.kr else self.BE_EN
            be = a.breakeven
            brow = []
            for var in [v_ for v_ in bn if v_ in set(be["variable"])]:
                v1 = be[(be["variable"] == var) & (be["level"] == 1.0)]["value"].iloc[0]
                rt = be[(be["variable"] == var) & (be["level"] == a.inp.target_dscr)].iloc[0]
                vt = rt["value"]
                base_v = {"prelease": self.pct(a.inp.prelease), "rate_shift": self.T("0bp", "0bp"), "delay_quarters": self.T("0분기", "0 qtrs"),
                          "power_mult": self.T(f"{a.inp.power_price:,.1f}원/kWh", f"KRW {a.inp.power_price:,.1f}/kWh") if a.inp.power_price else "0%"}.get(var, "0%")
                tcol = self.T("기준 = 목표", "base = target") if rt.get("at_target") else self.be_fmt(var, vt if vt == vt else None, a.inp)
                c1v = self.be_fmt(var, v1 if v1 == v1 else None, a.inp)
                if var == "prelease" and v1 != v1 and a.inp.grace_interest == "reserve" and a.inp.grace_years > 0:
                    c1v = self.T("상환 기간 영향 없음", "no effect on repayment years")
                brow.append([bn[var], base_v, tcol, c1v])
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
            cpm = a.inp.capex_per_mw
            clab = [self.T(f"{cpm * c_:,.0f}억원", f"{cpm * c_ / 10:,.1f}bn") for c_ in hm.columns]
            r_lo, c_hi = min(hm.index), max(hm.columns)
            worst = float(hm.loc[r_lo, c_hi])
            c3 = Cell(title=self.T(f"임대료 {(r_lo - 1) * 100:+.0f}%·CAPEX {cpm * c_hi:,.0f}억원/MW가 겹치면 최소 DSCR {self.x(worst)}",
                                   f"Rent {(r_lo - 1) * 100:+.0f}% with CAPEX KRW {cpm * c_hi / 10:,.1f}bn/MW: min DSCR {self.x(worst)}"),
                      src=["ksj"], legend=[(c["brick"], self.T("1.0배 미만", "Below 1.0x")), (c["warm_grey_light"], self.T("1.0배~목표", "1.0x–target")),
                                           (c["gold"], self.T("목표 이상", "At/above target"))], unit=self.T("최소 DSCR", "Min DSCR"), chart_key="heatmap_A",
                      chart=charts.heatmap(hm.to_numpy(dtype=float), rlab, clab, c, (1.0, a.inp.target_dscr),
                                           self.T("MW당 CAPEX (가정 범위)", "CAPEX per MW (assumed range, KRW)"), self.T("임대료 (기준 대비)", "Rent (vs base)")),
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
            r20 = next((x for k, x in b.stresses.items() if k.startswith("rent_-")), None)
            t20 = (self.T(f" — 실계약 임대료가 CBRE 호가보다 20% 낮으면 {self.x(r20.min_dscr)}", f" — {self.x(r20.min_dscr)} if contract rents sit 20% below CBRE quotes") if r20 is not None else "")
            cells.append(Cell(title=self.T(f"케이스 B: 최소 DSCR {self.x(b.base.min_dscr)}, 가장 민감한 변수 {vn[b.tornado.iloc[0]['variable']]}{t20}",
                                           f"Case B: min DSCR {self.x(b.base.min_dscr)}; most sensitive: {vn[b.tornado.iloc[0]['variable']]}{t20}"),
                              src=["ksj"], table=TableSpec([self.T("변수", "Variable"), self.T("불리", "Adverse"), self.T("유리", "Favourable")], rows,
                                                           [0.5, 0.25, 0.25], ["L", "R", "R"], font_size=8.6),
                              note=self.T(f"같은 스트레스 + 임대료 −20%: 하이퍼스케일 실계약 임대료가 CBRE 호가(250~500kW 기준)보다 낮을 경우의 위험. "
                                          + (f"CAPEX(전력기기 가격) = 전력설비 비중 {self.pct(self.B('power_equipment_share').value, 0)}(C&W 2026) × 피어 함의 가격 상승률(고 {self.pct((b.capex_stress['high'] - 1) / self.B('power_equipment_share').value)}) = +{(b.capex_stress['high'] - 1) * 100:.1f}%. " if ok(b.capex_stress) else "")
                                          + "대출 스케줄 고정"
                                          + (f", 가산금리 {b.margin_bp:.0f}bp 시나리오(미확정)" if b.margin_bp is not None else ""),
                                          f"Same stresses plus rent −20%: the risk that hyperscale contract rents sit below CBRE quotes (250–500 kW). "
                                          + (f"CAPEX (equipment prices) = power-equipment share {self.pct(self.B('power_equipment_share').value, 0)} (C&W 2026) × peer-implied price rise (high) = +{(b.capex_stress['high'] - 1) * 100:.1f}%. " if ok(b.capex_stress) else "")
                                          + "Debt schedule fixed"
                                          + (f"; {b.margin_bp:.0f}bp margin scenario (not yet sourced)" if b.margin_bp is not None else ""))))
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
                             self.T("불확실성 ③ 수요: IEA 하단·기준·상단 램프업 속도를 경로마다 추첨 — 1단계 가동률로 관측", "Uncertainty ③: IEA low/base/high ramp-up drawn per path — observed via phase 1 occupancy"),
                             self.T("2단계 사전 임대율 = 결정 연도의 1단계 가동률 (임차 수요 확인 후 착공)", "Phase 2 pre-lease = phase 1 occupancy in the decision year (build after demand is confirmed)"),
                             self.T("평가: 몬테카를로 + LSM(최소제곱 회귀로 '기다림'의 가치 추정), seed 고정·경로 수별 수렴 확인", "Valuation: Monte Carlo + LSM (least-squares continuation value), fixed seed, convergence by path count")],
                    note=self.T("무차입 NPV 기준. 옵션 가치 = p × 승인 조건부 가치", "Unlevered NPV. Option value = p × value given approval"))
        if not ok(op):
            cells = [self.pending(t, ["ksj", "grid"], op) for t in (
                self.T("승인 확률별 옵션 가치", "Option value by approval probability"), self.T("지금 짓기 vs 기다리기", "Build now vs wait"),
                self.T("할인율 × 대기 기간", "Discount rate × waiting window"))] + [tree]
            title = self.T(f"2단계 20MW는 '옵션' — 승인 확률별 가치와 착공 임계 임대료는 입력 확인 후 계산 (참고: 승인률 {self.grid_short()})",
                           f"Phase 2 (20 MW) is an option — values and trigger rent computed once inputs are sourced (ref.: approval {self.grid_short()})")
            sub = self.T("불확실성: 추가 계통 승인(확률) · 임대료(확률과정) · 수요(IEA 시나리오) — LSM 몬테카를로, seed 고정",
                         "Uncertainty: grid approval (probability), rent (stochastic), demand (IEA scenarios) — LSM Monte Carlo, fixed seed")
            return Page("body", "5", title, sub, cells)
        r, oi = op.result, op.inputs
        bp = r.by_prob
        pend = []
        if op.discount_pending:
            pend.append(self.T("할인율", "discount rate"))
        if op.window_pending:
            pend.append(self.T("대기 기간", "waiting window"))
        pend_kr = f"{'·'.join(pend)} 미확정 → 격자 가운데 셀({self.pct(oi.phase2.discount_rate, 0)}, {oi.window_years}년)" if pend else ""
        pend_en = f"{' and '.join(pend)} not yet sourced → middle grid cell ({self.pct(oi.phase2.discount_rate, 0)}, {oi.window_years} yrs)" if pend else ""
        vl = None
        if g.ratio is not None:
            vl = (g.ratio * 100, self.T(f"참고: 승인률 용량 {self.pct(g.ratio)}", f"ref.: approval {self.pct(g.ratio)} by capacity"))
        pv = op.prob_values
        c1 = Cell(title=self.T("승인 확률 " + "·".join(f"{p * 100:.0f}%" for p in pv) + "에서 옵션 가치 " + " · ".join(self.money('A', v) for v in pv.values()),
                               "Option value at approval probability " + "/".join(f"{p * 100:.0f}%" for p in pv) + ": " + " / ".join(self.money('A', v) for v in pv.values())),
                  src=["ksj", "grid"], legend=[(c["gold"], self.T("옵션 가치", "Option value"))], unit=self.T("억원 (1단계 COD 시점)", "KRW 100mn (at phase-1 COD)"),
                  chart_key="opt_prob",
                  chart=charts.xy([(self.T("옵션 가치", "Option"), list(bp["approval_prob"] * 100), list(bp["value"]), c["gold"])], c,
                                  lambda v: f"{v:.0f}%", lambda v: f"{v:,.0f}", vline=vl),
                  note=self.T(f"승인 확률 시나리오 10/30/50%(기준 30%, 저자 판단). 승인률은 수도권 1단계 신청 전체 기준(블록미디어)이라 개별 사업 확률이 아니다. 가치 = p × 승인 조건부 가치. {pend_kr}",
                              f"Approval scenarios 10/30/50% (base 30%, author's judgment). The approval rate covers all Seoul-metro phase-1 applications (Blockmedia), not one project's odds. Value = p × conditional value. {pend_en}"))
        crit = r.critical_rent
        rows = [[self.T("지금 짓기 (승인 즉시 착공)", "Build now (on approval)"), self.money("A", r.build_now)],
                [self.T("기다리기 (최적 착공, 옵션 가치)", "Wait (optimal timing, option value)"), self.money("A", r.value)],
                [self.T("유연성 가치 = 옵션 − max(지금, 0)", "Flexibility = option − max(now, 0)"), self.money("A", r.flexibility)]]
        for s_ in SCENARIOS:
            v = crit.get(s_)
            rows.append([self.T(f"착공 임계 임대료 ({self.scen(s_)})", f"Trigger rent ({self.scen(s_)})"),
                         self.T(f"{v:,.0f}원/kW·월", f"KRW {v:,.0f}/kW-mo") if v else self.T("결정 시점 착공 없음", "no build at decision date")])
        be = r.breakeven_rent.get("base")
        rows.append([self.T("NPV = 0 임대료 (기준)", "NPV-zero rent (base)"), self.T(f"{be:,.0f}원/kW·월", f"KRW {be:,.0f}/kW-mo") if be else "—"])
        rows.append([self.T("착공 경로 비율 · 평균 착공 연차", "Share of paths built · mean build year"),
                     f"{self.pct(r.exercise_share, 0)} · {self.yrs(r.mean_exercise_year)}"])
        dec_kr = f"1단계 COD 후 {oi.decision_year}년" + ("(= 램프업 종료, 수요 확인 시점)" if op.decision_derived else "")
        dec_en = f"year {oi.decision_year} after phase-1 COD" + (" (= end of ramp-up, when demand is confirmed)" if op.decision_derived else "")
        cv = r.convergence
        last = cv.iloc[-1]
        same = [s_ for s_ in SCENARIOS if s_ != "base" and crit.get(s_) is not None and crit.get(s_) == crit.get("base")]
        crit_note_kr = crit_note_en = ""
        if same:
            occ_note = {s_: oi.scenarios[s_].get("ramp_years") for s_ in ["base"] + same}
            crit_note_kr = (f" 임계 임대료 {'·'.join(self.scen(x) for x in same)} = 기준: 결정 시점(COD+{oi.decision_year}년)에 두 시나리오 모두 1단계가 안정화 가동률 "
                            f"{self.pct(oi.phase2.stabilized_occupancy, 0)}에 도달(램프업 " + "·".join(f"{v:.1f}년" for v in occ_note.values() if v) + ")해 "
                            "2단계 사전 임대율과 NPV가 같다(격자 해상도 문제 아님).")
            crit_note_en = (f" Trigger rent for {', '.join(self.scen(x).lower() for x in same)} = base: by the decision date (COD+{oi.decision_year}) phase 1 is stabilised at "
                            f"{self.pct(oi.phase2.stabilized_occupancy, 0)} in both (ramp-up " + "/".join(f"{v:.1f}" for v in occ_note.values() if v) + " yrs), "
                            "so phase-2 pre-lease and NPV are identical (not a grid-resolution effect).")
        c2 = Cell(title=self.T(f"지금 짓기 {self.money('A', r.build_now)} vs 기다리기 {self.money('A', r.value)} — 기다림의 가치 {self.money('A', r.flexibility)}",
                               f"Build now {self.money('A', r.build_now)} vs wait {self.money('A', r.value)} — value of waiting {self.money('A', r.flexibility)}"),
                  src=["ksj"], table=TableSpec([self.T("항목 (p = 30%)", "Item (p = 30%)"), self.T("값", "Value")], rows, [0.56, 0.44], ["L", "R"],
                                               shade_rows={1}, gold_cells={(1, 1), (2, 1)}, font_size=8.2),
                  note=self.T(f"결정 시점 = {dec_kr}, 대기 {oi.window_years}년, 할인율 {self.pct(oi.phase2.discount_rate, 0)}, 임대료 변동성 {self.pct(oi.rent_volatility, 0)}(저자 판단), "
                              f"경로 {oi.n_paths:,}개·seed {oi.seed}: 표준오차 {last['stderr'] / last['value_conditional'] * 100:.1f}%"
                              f"(경로 {int(cv.iloc[0]['n_paths']):,}개 {cv.iloc[0]['stderr'] / cv.iloc[0]['value_conditional'] * 100:.1f}%) — 수렴 확인." + crit_note_kr,
                              f"Decision {dec_en}; window {oi.window_years} yrs; discount {self.pct(oi.phase2.discount_rate, 0)}; rent vol. {self.pct(oi.rent_volatility, 0)} (judgment); "
                              f"{oi.n_paths:,} paths, seed {oi.seed}: s.e. {last['stderr'] / last['value_conditional'] * 100:.1f}% "
                              f"({int(cv.iloc[0]['n_paths']):,} paths: {cv.iloc[0]['stderr'] / cv.iloc[0]['value_conditional'] * 100:.1f}%) — converged." + crit_note_en))
        gd = op.grid
        drs, wins = sorted(gd["discount_rate"].unique()), sorted(gd["window_years"].unique())
        grows = []
        for dr in drs:
            row = [self.pct(dr, 0)]
            for w in wins:
                x = gd[(gd["discount_rate"] == dr) & (gd["window_years"] == w)].iloc[0]
                row.append(f"{x['value']:,.0f} ({x['flexibility']:,.0f})" if self.kr else f"{x['value'] / 10:,.1f} ({x['flexibility'] / 10:,.1f})")
            grows.append(row)
        mid_r = drs.index(min(drs, key=lambda x: abs(x - oi.phase2.discount_rate)))
        mid_c = wins.index(min(wins, key=lambda x: abs(x - oi.window_years))) + 1
        c3 = Cell(title=self.T(f"할인율·대기 기간에 따른 옵션 가치 {gd['value'].min():,.0f}~{gd['value'].max():,.0f}억원 — 기다릴수록 유연성 가치가 커진다",
                               f"Option value KRW {gd['value'].min() / 10:,.1f}–{gd['value'].max() / 10:,.1f}bn across discount rates and windows — waiting adds flexibility"),
                  src=["ksj"], unit=self.T("억원, 괄호 = 유연성 가치 (p = 30%)", "KRW bn; brackets = flexibility (p = 30%)"),
                  table=TableSpec([self.T("할인율 \\ 대기", "Discount \\ window")] + [self.T(f"{w}년", f"{w} yrs") for w in wins], grows,
                                  [0.25] + [0.75 / len(wins)] * len(wins), ["L"] + ["R"] * len(wins), gold_cells={(mid_r, mid_c)}, font_size=8.6),
                  note=self.T(("할인율·대기 기간은 근거 확인 전이라 민감도 격자로 보였다(저자 설정 축). 골드 = 대표 셀. " if pend else
                               f"대표 셀(골드) = 저자 판단 할인율 {self.pct(oi.phase2.discount_rate, 0)}·대기 {oi.window_years}년, 나머지는 민감도 축. ") + f"경로 {int(self.v['real_option'].get('grid_paths', 0)):,}개/셀",
                              ("Discount rate and window are not yet sourced, so a sensitivity grid is shown (author-set axes). Gold = headline cell. " if pend else
                               f"Gold = headline cell at the author's {self.pct(oi.phase2.discount_rate, 0)} discount rate and {oi.window_years}-yr window; other cells are sensitivity axes. ") + f"{int(self.v['real_option'].get('grid_paths', 0)):,} paths per cell"))
        title = (self.T(f"2단계 20MW: 지금 지으면 {self.money('A', r.build_now)}, 기다리면 {self.money('A', r.value)} — 승인 확률 30%에서 가치는 기다릴 권리에서 나온다",
                        f"Phase 2 (20 MW): build now {self.money('A', r.build_now)}, wait {self.money('A', r.value)} — at p = 30% the value lies in the right to wait")
                 if r.build_now <= 0 else
                 self.T(f"2단계 20MW: 옵션 가치 {self.money('A', r.value)}(승인 확률 30%) — 기다릴 권리가 {josa(self.money('A', r.flexibility), ('을', '를'))} 더한다",
                        f"Phase 2 (20 MW): option value {self.money('A', r.value)} at p = 30% — the right to wait adds {self.money('A', r.flexibility)}"))
        sub = self.T(f"승인 확률 10/30/50% · 결정 {dec_kr} · 참고: 수도권 승인률 {self.grid_short()}(1단계 신청 전체 기준)" + (f" · {pend_kr}" if pend else ""),
                     f"Approval 10/30/50% · decision at COD+{oi.decision_year} yrs · ref.: Seoul-metro approval {self.grid_short()}" + (" · discount rate and window on a grid" if pend else ""))
        return Page("body", "5", title, sub, [c1, c2, c3, tree])

    # --- p6 한·미 비교 --------------------------------------------------------
    def p6(self) -> Page:
        a, b, r, g, c = self.case("A"), self.case("B"), self.f.rates, self.f.grid, self.c
        fx = self.f.fx()
        pend = self.T("입력 후 산출", "after inputs")

        def val(cr, fn):
            return fn(cr) if ok(cr) else pend

        def rng(cr, fn, fmt):
            """가산금리 시나리오가 있으면 '대표값 (범위)'."""
            if not ok(cr):
                return pend
            base_s = fmt(fn(cr))
            ms = cr.margin_scenarios
            if not ms or not all(ok(x) for x in ms.values()):
                return base_s
            vs = [fn(x) for x in ms.values()]
            if fmt(min(vs)) == fmt(max(vs)):                      # 가산금리와 무관한 지표 (예: Project IRR)
                return base_s
            return f"{base_s} ({fmt(min(vs))}~{fmt(max(vs))})" if self.kr else f"{base_s} ({fmt(min(vs))}–{fmt(max(vs))})"
        sp = self.rate_spread()
        margin_b = (self.T(f"미확정: {b.margin_bp:.0f}bp 시나리오 (150/250/350bp)", f"Not sourced: {b.margin_bp:.0f}bp scenario (150/250/350bp)")
                    if ok(b) and b.margin_bp is not None else self.val_assump("B", "margin_bp"))
        rows = [
            [self.T("용량 · 단계", "Capacity · phasing"), self.T("40MW (20 확정 + 20 옵션)", "40 MW (20 firm + 20 option)"), self.T("100MW 단일", "100 MW single")],
            [self.T("조달 통화 · 기준금리", "Currency · base rate"), f"KRW · {self.base_label('A')} {self.base_value('A'):.2f}%" if ok(r) else "KRW",
             f"USD · {self.base_label('B')} {self.base_value('B'):.2f}%" if ok(r) else "USD"],
            [self.T("가산금리", "Margin"), self.val_assump("A", "margin_bp"), margin_b],
            [self.T("대출 한도 (현지 통화)", "Debt (local currency)"), val(a, lambda x: self.money("A", x.base.debt)),
             rng(b, lambda x: x.base.debt, lambda v: self.money("B", v))],
            [self.T("대출 한도 (원화 환산)", "Debt (KRW)"), val(a, lambda x: self.krw(x.base.debt)), val(b, lambda x: self.krw(self.to_krw(x.base.debt)))],
            [self.T("MW당 대출 (원화)", "Debt per MW (KRW)"), val(a, lambda x: self.krw(x.base.debt_per_mw)), val(b, lambda x: self.krw(self.to_krw(x.base.debt_per_mw)))],
            [self.T("대출 비율 · 구속 조건", "Gearing · binding"), val(a, lambda x: f"{self.pct(x.base.gearing, 0)} · {x.base.binding.upper()}"),
             val(b, lambda x: f"{self.pct(x.base.gearing, 0)} · {x.base.binding.upper()}")],
            [self.T("최소 · 평균 DSCR", "Min · avg DSCR"), val(a, lambda x: f"{self.x(x.base.min_dscr)} · {self.x(x.base.avg_dscr)}"),
             val(b, lambda x: f"{self.x(x.base.min_dscr)} · {self.x(x.base.avg_dscr)}")],
            ["LLCR", val(a, lambda x: self.x(x.base.llcr)), val(b, lambda x: self.x(x.base.llcr))],
            ["Project IRR", val(a, lambda x: self.pct(x.base.project_irr)), rng(b, lambda x: x.base.project_irr, self.pct)],
            ["Equity IRR", val(a, lambda x: self.pct(x.base.equity_irr)), rng(b, lambda x: x.base.equity_irr, self.pct)],
            [self.T("Project IRR (잔존가치 제외)", "Project IRR (ex-TV)"), val(a, lambda x: self.pct(x.base.project_irr_ex_tv)),
             rng(b, lambda x: x.base.project_irr_ex_tv, self.pct)],
            [self.T("Equity IRR (잔존가치 제외)", "Equity IRR (ex-TV)"), val(a, lambda x: self.pct(x.base.equity_irr_ex_tv)),
             rng(b, lambda x: x.base.equity_irr_ex_tv, self.pct)],
            [self.T("핵심 병목", "Key bottleneck"),
             self.T(f"계통(승인률 {self.grid_short()}) · 사전 임대율({self.prelease_range()})", f"Grid (approval {self.grid_short()}) · pre-leasing ({self.prelease_range()})"),
             self.T(f"규모(100MW, 한국 1단계의 5배) · 금리(+{sp:.2f}%p)" if sp is not None else "규모 · 금리",
                    f"Scale (100 MW, 5x Korea phase 1) · rates (+{sp:.2f}pp)" if sp is not None else "Scale · rates")],
        ]
        n = len(rows)
        c1 = Cell(title=self.T("대출 한도·DSCR·Equity IRR을 나란히 — 같은 엔진, 다른 병목", "Debt, DSCR and equity IRR side by side — same engine, different bottlenecks"),
                  src=["ecos", "fred", "grid", "market", "cost", "finance", "ksj"],
                  table=TableSpec(["", self.T("한국 40MW (케이스 A)", "Korea 40 MW (Case A)"), self.T("미국 100MW (케이스 B)", "U.S. 100 MW (Case B)")], rows,
                                  [0.24, 0.36, 0.40], ["L", "R", "R"], shade_rows={3, n - 1}, gold_cells={(n - 1, 1), (n - 1, 2)}, font_size=8.4),
                  note=self.T((f"원화 환산 = USD mn × ECOS 원/달러 {fx:,.1f}원({r.fx_date}) ÷ 100. 한국 대출 한도는 1단계 20MW 기준. " if fx else "")
                              + "케이스 B 괄호 = 가산금리 150~350bp 시나리오 범위(가산금리 미확정). " + self.irr_basis(),
                              (f"KRW = USD mn × ECOS USD/KRW {fx:,.1f} ({r.fx_date}) ÷ 100. Korea debt is for phase 1 (20 MW). " if fx else "")
                              + "Case B brackets = 150–350bp margin range (margin not yet sourced). " + self.irr_basis()))
        if ok(a) and ok(b):
            vals = [self.to_krw(b.base.debt_per_mw), a.base.debt_per_mw]
            c2 = Cell(title=self.T(f"MW당 대출: 미국 {self.krw(vals[0])} vs 한국 {self.krw(vals[1])}", f"Debt per MW: U.S. {self.krw(vals[0])} vs Korea {self.krw(vals[1])}"),
                      src=["ecos", "ksj"], legend=[(c["gold"], self.T("미국 100MW", "U.S. 100 MW")), (c["brown_dark"], self.T("한국 1단계 20MW", "Korea phase 1"))],
                      unit=self.T("억원/MW", "KRW 100mn per MW"), chart_key="per_mw",
                      chart=charts.bars([self.T("미국", "U.S."), self.T("한국", "Korea")], vals, [c["gold"], c["brown_dark"]], c, lambda v: f"{v:,.0f}"),
                      note=self.T(f"달러 대출은 기준일 환율로 환산 (환헤지 비용 미반영). MW당 CAPEX가 한국 {a.inp.capex_per_mw:,.0f}억원, 미국 USD {b.inp.capex_per_mw:.1f}mn(약 {self.krw(self.to_krw(b.inp.capex_per_mw))})으로 달라 MW당 대출 차이의 대부분을 설명",
                                  f"USD debt converted at the as-of rate (no hedging cost). CAPEX per MW (KRW {a.inp.capex_per_mw / 10:,.1f}bn vs USD {b.inp.capex_per_mw:.1f}mn) explains most of the gap"))
        elif ok(r):
            c2 = Cell(title=self.T(f"기준금리: {self.base_label('B')} {self.base_value('B'):.2f}% vs {self.base_label('A')} {self.base_value('A'):.2f}%",
                                   f"Base rates: {self.base_label('B')} {self.base_value('B'):.2f}% vs {self.base_label('A')} {self.base_value('A'):.2f}%"),
                      src=["ecos", "fred"], legend=[(c["brown_dark"], self.T("국고채", "KTB")), (c["gold"], self.T("미 국채", "UST"))], unit="%",
                      chart_key="base_rates",
                      chart=charts.bars([self.T("국고채 3년", "KTB 3y"), self.T("국고채 10년", "KTB 10y"), self.T("미 국채 10년", "UST 10y")],
                                        [r.ktb_3y, r.ktb_10y, r.dgs10], [c["brown_mid"], c["brown_dark"], c["gold"]], c, lambda v: f"{v:.2f}%"),
                      note=self.T(f"ECOS {r.ktb_date}, FRED {r.dgs10_date}", f"ECOS {r.ktb_date}, FRED {r.dgs10_date}"))
        else:
            c2 = self.pending(self.T("기준금리 비교", "Base-rate comparison"), ["ecos", "fred"], r)
        title = self.T("한·미 비교: 대출 한도를 정하는 병목이 다르다 — 한국은 계통·사전 임대율, 미국은 규모·금리",
                       "Korea vs U.S.: different bottlenecks set debt capacity — grid and pre-leasing in Korea, scale and rates in the U.S.")
        sub = self.T((f"기준금리 차이 {sp:+.2f}%p({self.base_label('B')} − {self.base_label('A')}) · 계통 승인률 {self.grid_short()} · 사전 임대율 {self.prelease_range()}" if sp is not None else "")
                     + (" · 환율 " + f"{fx:,.1f}원" if fx else ""),
                     (f"Base-rate gap {sp:+.2f}pp ({self.base_label('B')} − {self.base_label('A')}) · grid approval {self.grid_short()} · pre-leasing {self.prelease_range()}" if sp is not None else "")
                     + (f" · FX {fx:,.1f}" if fx else ""))
        return Page("body", "6", title, sub, [c1, c2], grid="1x2")

    def irr_basis(self) -> str:
        """IRR 계산 기준 한 줄: 감가상각·잔존가치."""
        da, db = self.A("dep_years").value, self.B("dep_years").value
        ca, cb = self.A("exit_cap_rate").value, self.B("exit_cap_rate").value
        dep = (self.T(f"감가상각 정액 {da:.0f}년", f"straight-line depreciation {da:.0f} yrs") if da and da == db
               else self.T("감가상각 미반영 → IRR 보수적", "no depreciation → IRRs conservative"))
        ny = int(self.A("operating_years").value or 0) + 1
        tv = (self.T(f"잔존가치 = {ny}년차 EBITDA ÷ cap rate(A {self.pct(ca)} 저자 판단: 국내 거래 근거 없어 미국보다 1%p 높게 · B {self.pct(cb)}: Houlihan Lokey 안정화 하이퍼스케일 5.0~7.5%(같은 문서 1H 2026 표 5.0~7.25%), 북버지니아 실제 거래 5%대 초반보다 보수적)",
                     f"terminal value = year-{ny} EBITDA ÷ cap rate (A {self.pct(ca)}, judgment: no Korean deal evidence, set 1pp above the U.S.; B {self.pct(cb)}: Houlihan Lokey stabilised hyperscale 5.0–7.5% (5.0–7.25% in the same document's 1H 2026 table), conservative vs low-5% Northern Virginia deals)")
              if ca and cb else self.T("잔존가치 제외", "no terminal value"))
        return f"{dep}, {tv}" if self.kr else f"{dep[0].upper() + dep[1:]}; {tv}"

    def val_assump(self, case: str, key: str) -> str:
        a = self.f.assumptions[case][key]
        if a.value is None:
            return self.T("근거 확인 중", "being sourced")
        return f"{a.value:,.0f}bp" if key == "margin_bp" else str(a.value)

    # --- p7 개발 수익률 ------------------------------------------------------
    def p7(self) -> Page:
        a, b, c, pp, r = self.case("A"), self.case("B"), self.c, self.f.peers, self.f.rates
        if not (ok(a) and ok(b)):
            u = a if not ok(a) else b
            cells = [self.pending(t, ["ksj"], u) for t in (
                self.T("케이스 A 전력비 부담: 전력 포함 vs 별도 청구", "Case A power: gross vs pass-through"), self.T("원가 대비 수익률", "Yield on cost"),
                self.T("케이스 B 계약 매출 기준 sizing", "Case B contracted-revenue sizing"), self.T("공사비와 임대료", "Build cost vs rent"))]
            return Page("body", "7", self.T("개발 수익률: 입력 확인 후 계산", "Development yield: computed once inputs are sourced"), "", cells)
        from src.analysis.pf_model import yield_on_cost as yoc
        mb = b.margin_bp if b.margin_bp is not None else b.inp.margin * 1e4      # 케이스 B 가산금리(시나리오 또는 입력값)
        pc = self.power_clause()
        cut = a.alts.get("power_cut")
        cut_cfg = (self.v["sensitivity"].get("power_price_cut") or {}).get("A") or {}
        cut_v = cut_cfg.get("value")
        curve = a.power_curve
        if pc is not None and curve:
            pt_r, gr_r, pt_base = pc
            shares = sorted(curve)
            labs = [self.T(f"{sh * 100:.0f}%", f"{sh * 100:.0f}%") for sh in shares]
            notes = [self.T(f"최소 DSCR {curve[sh].min_dscr:.2f}배", f"min DSCR {curve[sh].min_dscr:.2f}x") for sh in shares]
            dfmt = (lambda v: f"{v:,.0f}") if self.kr else (lambda v: f"{v / 10:,.0f}bn")
            pw = a.power or {}
            si = pw.get("stab_year", 1) - 1
            pcost = float(gr_r.ops["power_cost"].iloc[si])
            c1 = Cell(title=self.T(f"전력비 포함 비율 0%→100%: Equity IRR {self.pct(curve[shares[0]].equity_irr)} → {self.pct(curve[shares[-1]].equity_irr)}, 대출 한도 {self.money('A', curve[shares[0]].debt)} → {self.money('A', curve[shares[-1]].debt)}",
                                   f"Power share in rent 0%→100%: equity IRR {self.pct(curve[shares[0]].equity_irr)} → {self.pct(curve[shares[-1]].equity_irr)}; debt {self.money('A', curve[shares[0]].debt)} → {self.money('A', curve[shares[-1]].debt)}"),
                      src=["market", "lease", "power", "ksj"],
                      legend=[(c["warm_grey_light"], self.T("대출 한도(억원)", "Debt (KRW)")), (c["gold"], "Equity IRR"),
                              (c["brick"], self.T("잔존가치 제외", "Ex-TV"))],
                      unit=self.T("x축 = 임대료에 포함된 전력비 비율(SPC 부담), 단계마다 다시 sizing", "x-axis = share of power cost inside rent (SPC-borne), re-sized at each step"),
                      chart_key="power_curve",
                      chart=charts.debt_irr_curve(labs, [curve[sh].debt for sh in shares], [curve[sh].equity_irr * 100 for sh in shares],
                                                  [curve[sh].equity_irr_ex_tv * 100 for sh in shares] if curve[shares[0]].terminal_value else None,
                                                  notes, c, dfmt, ("debt", "IRR", "ex-TV")),
                      note=self.T(f"0% = 전력비 별도 청구(기준: 도매 임대는 kW당 임대료 + 전력 별도 청구가 일반적, Data Center Scouts·gr1d — CBRE 임대료의 전력 포함 정의는 원문 미확인. 도매 임대 관행상 전력은 별도 청구가 일반적), 100% = 전력 포함 임대(SPC 부담, 스트레스). "
                                  f"전력비 = IT {a.inp.mw:,.0f}MW × 가동률 × IT 부하율 {self.pct(a.inp.it_load_factor, 0)} × PUE {a.inp.pue:.1f} × 8,760시간 × {a.inp.power_price:,.1f}원/kWh(한전 2025년 평균 산업용, 시대일보 2026-08-27), 연 {self.pct(a.inp.power_escalation, 0)} 인상 — 안정화 첫해 {self.money('A', pcost)}. "
                                  + (f"전력 포함 시 단가 {cut_v:+.0f}원({cut_cfg.get('note', '')}, 시대일보 {cut_cfg.get('published', '')})이면 Equity IRR {self.pct(cut.equity_irr)}·대출 {self.money('A', cut.debt)} — 제안 단계라 민감도로만" if cut is not None else ""),
                                  f"0% = power billed separately (base: wholesale leases quote rent per kW with power on top, Data Center Scouts, gr1d — CBRE's definition of whether rent includes power is not verified; in wholesale leasing, power is usually billed separately); 100% = gross rent (SPC pays; stress). "
                                  f"Power = IT {a.inp.mw:,.0f} MW × occupancy × IT load {self.pct(a.inp.it_load_factor, 0)} × PUE {a.inp.pue:.1f} × 8,760 h × KRW {a.inp.power_price:,.1f}/kWh (KEPCO 2025 avg industrial), +{self.pct(a.inp.power_escalation, 0)}/yr — {self.money('A', pcost)} in the first stabilised year. "
                                  + (f"With gross rent, a KRW {cut_v:+.0f}/kWh cut (proposal for the northern Seoul metro, Sidae Ilbo {cut_cfg.get('published', '')}) gives equity IRR {self.pct(cut.equity_irr)}, debt {self.money('A', cut.debt)} — proposal only, sensitivity" if cut is not None else "")))
        else:
            pt_r = gr_r = None
            c1 = self.pending(self.T("전력비 포함 비율별 Equity IRR·대출 한도", "Equity IRR and debt by power share"), ["ksj"], Unavailable("전력비 입력 필요", "Power inputs needed", ["pue", "it_load_factor", "power_price"]))
        # 원가 대비 수익률 막대
        cf_ = b.cost_counterfactual
        chg = self.B("capex_yoy_change").value
        bars_ = [(self.T("A 기준", "A base"), a.yoc, a.inp.term_rate, c["brown_dark"])]
        if pc is not None:
            other = gr_r if pt_base else pt_r
            bars_.append((self.T("A 전력 포함", "A gross") if pt_base else self.T("A 전력 별도", "A pass-thru"), yoc(other), a.inp.term_rate, c["brown_mid"]))
        bars_.append((self.T("B 기준", "B base"), b.yoc, b.inp.term_rate, c["gold"]))
        if cf_ is not None:
            bars_.append((self.T("B 공사비 상승 전", "B pre-cost rise"), yoc(cf_), b.inp.term_rate, c["warm_grey"]))
        band = (0.08, 0.14)
        out_ = [lab for lab, v, _, _ in bars_ if not band[0] - 0.01 <= v <= band[1] + 0.01]
        c2 = Cell(title=self.T(f"원가 대비 수익률 " + " · ".join(f"{lab} {self.pct(v)}" for lab, v, _, _ in bars_) + (f" — 8~14%(±1%p) 밖: {', '.join(out_)}" if out_ else ""),
                               "Yield on cost: " + "; ".join(f"{lab} {self.pct(v)}" for lab, v, _, _ in bars_) + (f" — outside 8–14% (±1pp): {', '.join(out_)}" if out_ else "")),
                  src=["cost", "ecos", "fred", "ksj"], legend=[(c["warm_grey_light"], self.T("점검 범위 8~14%", "Check range 8–14%")), (c["brick"], self.T("대출금리(기준금리 + 가산)", "Loan rate (base + margin)"))],
                  unit="%", chart_key="yoc",
                  chart=charts.yield_bars([lab for lab, *_ in bars_], [v * 100 for _, v, _, _ in bars_], [col for *_, col in bars_], c,
                                          lambda v: f"{v:.1f}%", band=(8, 14), band_label=self.T("점검 범위", "check range"),
                                          marks=[m * 100 for _, _, m, _ in bars_], mark_label=self.T("대출금리", "loan rate")),
                  note=self.T(f"원가 대비 수익률 = 안정화 첫해 EBITDA ÷ 총사업비(CAPEX + IDC + DSRA + 유보계좌). 대출금리 = {self.base_label('A')} {self.base_value('A'):.2f}% + {self.val_assump('A', 'margin_bp')}, "
                              f"{self.base_label('B')} {self.base_value('B'):.2f}% + {mb:.0f}bp(시나리오). 8~14%(±1%p 허용)는 점검 범위",
                              f"Yield on cost = first stabilised-year EBITDA ÷ total cost (CAPEX + IDC + DSRA + reserve). Loan rate = {self.base_label('A')} {self.base_value('A'):.2f}% + {self.val_assump('A', 'margin_bp')}; "
                              f"{self.base_label('B')} {self.base_value('B'):.2f}% + {mb:.0f}bp (scenario). 8–14% (±1pp) is the check range"))
        # 케이스 B: 전체 매출 vs 계약 매출 sizing
        ct = b.alts.get("contracted")
        bb = b.base
        if ct is not None:
            cols_b = [(self.T("전체 매출 sizing (기준)", "Total-revenue sizing (base)"), bb), (self.T(f"계약 매출 sizing (사전 임대 {self.pct(b.inp.prelease, 0)})", f"Contracted sizing ({self.pct(b.inp.prelease, 0)} pre-let)"), ct)]
            brows = [[self.T("대출 한도 (총사업비 대비)", "Debt (share of cost)")] + [f"{self.money('B', x.debt)} ({self.pct(x.gearing, 0)})" for _, x in cols_b],
                     [self.T("원화 환산", "KRW equivalent")] + [self.krw(self.to_krw(x.debt)) for _, x in cols_b],
                     [self.T("최소 DSCR (전체 매출)", "Min DSCR (total revenue)")] + [self.x(x.min_dscr) for _, x in cols_b],
                     [self.T("최소 DSCR (계약 매출만)", "Min DSCR (contracted only)")] + [self.x(x.min_dscr_contracted) for _, x in cols_b],
                     [self.T("평균 DSCR · LLCR", "Avg DSCR · LLCR")] + [f"{self.x(x.avg_dscr)} · {self.x(x.llcr)}" for _, x in cols_b],
                     ["Equity IRR"] + [self.pct(x.equity_irr) for _, x in cols_b]]
            c3 = Cell(title=self.T(f"계약 매출만으로 DSCR {b.inp.target_dscr:.2f}배를 맞추면 대출 {self.money('B', ct.debt)}({self.pct(ct.debt / bb.debt - 1, 0, True)}) — 전체 매출 기준 {self.money('B', bb.debt)}",
                                   f"Sizing on contracted revenue at {b.inp.target_dscr:.2f}x gives {self.money('B', ct.debt)} ({self.pct(ct.debt / bb.debt - 1, 0, True)}) vs {self.money('B', bb.debt)} on total revenue"),
                      src=["market", "finance", "ksj"],
                      table=TableSpec([self.T("케이스 B (100MW)", "Case B (100 MW)")] + [h for h, _ in cols_b], brows, [0.36, 0.32, 0.32], ["L", "R", "R"],
                                      shade_rows={0}, gold_cells={(0, 2)}, font_size=8.2),
                      note=self.T(f"계약 매출 sizing = 사전 임대 {self.pct(b.inp.prelease, 0)}·임대 {b.inp.lease_term_years}년 매출에서 전체 OPEX를 뺀 CFADS ÷ {b.inp.target_dscr:.2f}배로 원리금 sculpting. "
                                  f"가산금리 {mb:.0f}bp 시나리오. 대주가 미계약분을 담보로 보지 않을 때의 하한",
                                  f"Contracted sizing sculpts debt service at CFADS ÷ {b.inp.target_dscr:.2f}x using {self.pct(b.inp.prelease, 0)} pre-let rent over the {b.inp.lease_term_years}-yr lease, net of full OPEX. "
                                  f"{mb:.0f}bp margin scenario. A floor if lenders ignore unlet capacity"))
        else:
            c3 = self.pending(self.T("케이스 B 계약 매출 기준 sizing", "Case B contracted sizing"), ["ksj"], Unavailable("계약 매출 sizing 미설정", "Not configured"))
        # 공사비 vs 임대료
        if cf_ is not None and chg:
            rate_b = b.inp.term_rate
            s0, s1 = yoc(cf_) - rate_b, b.yoc - rate_b
            lead = self.T(f"공사비가 임대료를 앞질렀다: AI 사양 공사비 1년 {self.pct(chg, 0, True)}(Cushman & Wakefield 2026) vs 임대료 인상 가정 연 {self.pct(b.inp.rent_escalation, 0)}",
                          f"Cost outran rent: AI-spec build cost {self.pct(chg, 0, True)} in a year (Cushman & Wakefield 2026) vs rent escalation of {self.pct(b.inp.rent_escalation, 0)}/yr")
            bl = [self.T(f"원가 대비 수익률 {self.pct(yoc(cf_))} → {self.pct(b.yoc)} ({(b.yoc - yoc(cf_)) * 100:+.1f}%p): 공사비 상승 전·임대료 1년 전 수준으로 다시 계산한 값과 비교",
                         f"Yield on cost {self.pct(yoc(cf_))} → {self.pct(b.yoc)} ({(b.yoc - yoc(cf_)) * 100:+.1f}pp) vs a re-run at pre-rise cost and last year's rent"),
                  self.T(f"대출금리 {self.pct(rate_b, 2)}({self.base_label('B')} {self.base_value('B'):.2f}% + {mb:.0f}bp)와의 격차 {s0 * 100:.1f}%p → {s1 * 100:.1f}%p — 개발 수익률이 대출금리 쪽으로 눌렸다",
                         f"Spread over the {self.pct(rate_b, 2)} loan rate ({self.base_label('B')} {self.base_value('B'):.2f}% + {mb:.0f}bp): {s0 * 100:.1f}pp → {s1 * 100:.1f}pp — development yield pressed towards the cost of debt"),
                  self.T(f"Project IRR {self.pct(cf_.project_irr)} → {self.pct(bb.project_irr)}, Equity IRR {self.pct(cf_.equity_irr)} → {self.pct(bb.equity_irr)}, 대출 한도 {self.money('B', cf_.debt)} → {self.money('B', bb.debt)}",
                         f"Project IRR {self.pct(cf_.project_irr)} → {self.pct(bb.project_irr)}; equity IRR {self.pct(cf_.equity_irr)} → {self.pct(bb.equity_irr)}; debt {self.money('B', cf_.debt)} → {self.money('B', bb.debt)}")]
            if ok(pp):
                bl.append(self.T(f"Vol.1과의 연결: 전력기기 업체의 이익은 개발자의 비용 — 피어 3사 영업이익률 {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)}({pp.fy0}→{pp.fy1}, DART)는 공사비 쪽에서 보면 원가다(인과 단정이 아닌 연결)",
                                 f"Link to Vol.1: equipment makers' profit is the developer's cost — peer margins {self.pct(pp.agg_opm0)}→{self.pct(pp.agg_opm1)} ({pp.fy0}→{pp.fy1}, DART) sit on the cost side (a link, not a causal claim)"))
            c4 = Cell(title=self.T(f"미국: 원가 대비 수익률 {self.pct(b.yoc)} − 대출금리 {self.pct(rate_b, 2)} = {s1 * 100:.1f}%p (공사비 상승 전 {s0 * 100:.1f}%p)",
                                   f"U.S.: yield on cost {self.pct(b.yoc)} − loan rate {self.pct(rate_b, 2)} = {s1 * 100:.1f}pp ({s0 * 100:.1f}pp before the cost rise)"),
                      src=["cost", "market", "fred", "dart", "ksj"], panel_lead=lead, bullets=bl,
                      note=self.T(f"공사비 상승 전 = MW당 CAPEX ÷ (1 + {self.pct(chg, 0)}), 임대료 ÷ (1 + {self.pct(b.inp.rent_escalation, 0)}), OPEX 비율 동일. {self.pct(chg, 0)}는 C&W 2026 Data Center Development Cost Guide 보도 기준",
                                  f"Pre-rise = CAPEX per MW ÷ (1 + {self.pct(chg, 0)}), rent ÷ (1 + {self.pct(b.inp.rent_escalation, 0)}), same OPEX ratio. {self.pct(chg, 0)} per reporting on the C&W 2026 Data Center Development Cost Guide"))
        else:
            c4 = self.pending(self.T("공사비와 임대료", "Build cost vs rent"), ["cost"], Unavailable("공사비 상승률 입력 필요", "Cost change needed", ["capex_yoy_change"]))
        cs = self.clause_sentence()
        spread = (b.yoc - b.inp.term_rate) * 100
        title = self.T(f"개발 수익률: 한국은 {cs}, 미국은 대출금리와의 격차가 {spread:.1f}%p로 좁혀졌다" if cs else "개발 수익률",
                       f"Development yield: in Korea {cs[0].lower() + cs[1:]}; in the U.S. the spread over debt is down to {spread:.1f}pp" if cs else "Development yield")
        sub = self.T("전력비 포함 비율(0~100%)별 대출 한도·Equity IRR·최소 DSCR · 원가 대비 수익률 점검(8~14%) · 케이스 B 계약 매출 sizing · 공사비 vs 임대료",
                     "Debt, equity IRR and min DSCR by power share in rent (0–100%) · yield-on-cost check (8–14%) · Case B contracted sizing · build cost vs rent")
        return Page("body", "7", title, sub, [c1, c2, c3, c4])

    # --- p8 시사점 ------------------------------------------------------------
    def p8(self) -> Page:
        a, b, g, r, va = self.case("A"), self.case("B"), self.f.grid, self.f.rates, self.f.va
        pre_be = None
        if ok(a):
            be = a.breakeven
            hit = be[(be["variable"] == "prelease") & (be["level"] == 1.0)]["value"]
            pre_be = hit.iloc[0] if len(hit) and hit.iloc[0] == hit.iloc[0] else None
        pc = self.power_clause()
        power_row = [self.T("① 전력비 부담", "① Power-cost clause"),
                     (self.T(f"별도 청구 vs 전력 포함: Equity IRR {self.pct(pc[0].equity_irr)} vs {self.pct(pc[1].equity_irr)}, 대출 {self.money('A', pc[0].debt)} vs {self.money('A', pc[1].debt)}",
                             f"Pass-through vs gross: equity IRR {self.pct(pc[0].equity_irr)} vs {self.pct(pc[1].equity_irr)}; debt {self.money('A', pc[0].debt)} vs {self.money('A', pc[1].debt)}")
                      if pc is not None else self.T("패스스루 조항 · 예외(공용부) 확인", "Pass-through clause; carve-outs"))
                     + self.T(" — 확인: 별도 청구 시 take-or-pay 최소 요금 유무(배정 전력의 60~85%로 늘어나는 추세)",
                              " — check: take-or-pay minimum on billed power (trending to 60–85% of allocated power)"),
                     self.T("패스스루 · take-or-pay 최소 요금 조항 · 버지니아 요금 상승 시 임차인 부담 (오른쪽 아래 표)",
                            "Pass-through and take-or-pay clauses; tenant burden as Virginia prices rise (table below right)"), "7, 8, A1"]
        rows = [
            power_row,
            [self.T("계통 승인", "Grid approval"), self.T(f"1단계 확정 승인 필수 · 2단계는 옵션 (승인률 {self.grid_short()})", f"Phase 1 approval a must; phase 2 as an option ({self.grid_short()})"),
             self.T("접속 일정 확인", "Confirm connection timing"), "1, 5"],
            [self.T("사전 임대율", "Pre-leasing"),
             self.T(f"최소 DSCR 1.0배 손익분기 {self.pct(pre_be)} (시장 {self.prelease_range()})" if pre_be else f"시장 {self.prelease_range()}",
                    f"Breakeven for 1.0x: {self.pct(pre_be)} (market {self.prelease_range()})" if pre_be else f"Market {self.prelease_range()}"),
             self.T(f"사전 임대율 {self.pct(self.B('prelease').value, 0)} · 임대 {self.B('lease_term_years').value:.0f}년" if self.B('prelease').value and self.B('lease_term_years').value else "앵커 임차인",
                    f"Pre-lease {self.pct(self.B('prelease').value, 0)}; {self.B('lease_term_years').value:.0f}-yr lease" if self.B('prelease').value and self.B('lease_term_years').value else "Anchor tenant"), "3, 4"],
            [self.T("임대 만기 ≥ 대출 만기인가 (재임대 위험)", "Lease term ≥ loan tenor? (re-letting risk)"), self.lease_vs_tenor("A"), self.lease_vs_tenor("B"), "3, 6"],
            [self.T("금리", "Rates"), f"{self.base_label('A')} {self.base_value('A'):.2f}% + {self.val_assump('A', 'margin_bp')}" if ok(r) else "—",
             self.T(f"{self.base_label('B')} {self.base_value('B'):.2f}% + 가산금리 미확정" if ok(r) else "—",
                    f"{self.base_label('B')} {self.base_value('B'):.2f}% + margin TBC" if ok(r) else "—"), "2, 6"],
            [self.T("공사비", "Construction cost"), self.capex_range_text(),
             self.T("규모가 커 절대 금액 위험 큼", "Large absolute exposure"), "2, 4"],
            [self.T("운영비", "OPEX"), self.T("근거 없는 저자 판단 → ±20% 스트레스", "Unsourced judgment → ±20% stress"),
             self.T("근거 없는 저자 판단 → ±20% 스트레스", "Unsourced judgment → ±20% stress"), "4"],
            [self.T("램프업", "Ramp-up"),
             (self.T(f"이자유보계좌 {self.money('A', a.base.cons.reserve_initial)}(사업비 포함) · 램프업 {a.inp.grace_years}년 이자만",
                     f"Interest reserve {self.money('A', a.base.cons.reserve_initial)} (in cost); {a.inp.grace_years}-yr interest-only")
              if ok(a) and a.base.cons.reserve_initial > 0 else self.T("램프업 이자 재원 확인", "Fund ramp-up interest")),
             (self.T(f"계약 매출 sizing {self.money('B', b.alts['contracted'].debt)} vs 전체 {self.money('B', b.base.debt)}",
                     f"Contracted sizing {self.money('B', b.alts['contracted'].debt)} vs total {self.money('B', b.base.debt)}")
              if ok(b) and "contracted" in b.alts else self.T("앵커 임차인 계약 기간", "Anchor lease term")), "3, 7"],
        ]
        c1 = Cell(title=self.T("대주 체크리스트: 첫 번째 확인 항목은 전력비 부담 구조, 그다음 한국은 '승인과 임차인', 미국은 '금리와 공사비'",
                               "Lender checklist: check the power-cost structure first; then Korea — approval and tenants, U.S. — rates and cost"),
                  src=["lease", "grid", "market", "cost", "finance", "ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("한국 40MW", "Korea 40 MW"), self.T("미국 100MW", "U.S. 100 MW"), self.T("근거 쪽", "Pages")], rows,
                                  [0.15, 0.40, 0.33, 0.12], ["L", "L", "L", "C"], shade_rows={0}, gold_cells={(0, 1)}, font_size=8.0,
                                  brick_cells={(3, j) for j, c_ in ((1, "A"), (2, "B")) if ok(self.case(c_)) and (self.case(c_).inp.lease_term_years or 0) < self.case(c_).inp.tenor_years}),
                  note=self.T("가상 케이스 기준의 점검 항목. 숫자는 본문 계산값", "Checklist for the hypothetical cases; figures from the body"))
        limits = [self.T("두 케이스 모두 실존 프로젝트가 아니며, 저자 판단 가정은 가정표(A2·A3)에 '저자 판단'으로 구분했다", "Both cases are hypothetical; author's judgments are flagged as such in A2–A3")]
        if self.A("dep_years").value and self.A("exit_cap_rate").value:
            tv_kr = tv_en = ""
            if ok(a) and ok(b):
                tv_kr = f": 잔존가치 제외 시 Equity IRR 한국 {self.pct(a.base.equity_irr)} → {self.pct(a.base.equity_irr_ex_tv)}, 미국 {self.pct(b.base.equity_irr)} → {self.pct(b.base.equity_irr_ex_tv)}"
                tv_en = f": ex-TV equity IRR Korea {self.pct(a.base.equity_irr)} → {self.pct(a.base.equity_irr_ex_tv)}, U.S. {self.pct(b.base.equity_irr)} → {self.pct(b.base.equity_irr_ex_tv)}"
            limits.append(self.T(f"감가상각(정액 {self.A('dep_years').value:.0f}년)·PUE {self.A('pue').value:.1f}·IT 부하율 {self.pct(self.A('it_load_factor').value, 0)}·cap rate는 출처 없는 저자 판단 — IRR은 cap rate에 민감{tv_kr}",
                                 f"Depreciation ({self.A('dep_years').value:.0f} yrs), PUE {self.A('pue').value:.1f}, IT load {self.pct(self.A('it_load_factor').value, 0)} and cap rates are unsourced judgments — IRRs depend on cap rates{tv_en}"))
        else:
            limits.append(self.T("감가상각·잔존가치 미입력 → 법인세 과대, IRR 보수적", "No depreciation or terminal value → tax overstated, IRRs conservative"))
        if not self.a_gross() and self.power_clause() is not None:
            limits.append(self.T("케이스 A 임대료 25만원은 전력 제외(별도 청구)로 보고 미국 CBRE 수치와 같은 정의로 처리했다 — CBRE 임대료의 전력 포함 정의는 원문 미확인. 도매 임대 관행상 전력은 별도 청구가 일반적. 전력 포함이면 p7 스트레스",
                                 "Case A's KRW 250k rent is treated as ex-power (billed separately), the same definition as the U.S. CBRE figures — CBRE's definition of whether rent includes power is not verified; in wholesale leasing, power is usually billed separately. Gross rent is the p7 stress"))
        if self.a_gross():
            limits.append(self.T("케이스 A 임대료 25만원의 전력 포함 여부는 원문에서 미확인 — 전력 포함(SPC 부담)을 기준으로 두고 별도 청구를 비교(p7)",
                                 "Whether Case A's KRW 250k rent includes power is unconfirmed — gross is the base, pass-through compared (p7)"))
        limits.append(self.T("피어 이익률→가격 상승은 상한값이며 인과가 아니다(물량·환율·제품 구성 미분리)", "Peer margin → price is an upper bound, not causal (volume, FX, mix not separated)"))
        if ok(a) and a.negative_amort:
            limits.insert(1, self.T(f"케이스 A 램프업 초기({', '.join(map(str, a.negative_amort))}년차) 원리금 < 이자: 이자 적립 없이는 대출 한도 {self.money('A', a.interest_cover_debt)}",
                                    f"Case A early ramp-up (year {', '.join(map(str, a.negative_amort))}): debt service < interest; without an interest reserve the limit is {self.money('A', a.interest_cover_debt)}"))
        c2 = Cell(title=self.T("이 노트의 한계", "Limitations of this note"), bullets=limits, note=self.T("가정 근거가 확인되는 대로 갱신", "Updated as sources are confirmed"))
        c3 = Cell(title=self.T("Vol.3 예고: IPO 공모가와 해외 피어", "Next in Vol.3: IPO pricing and overseas peers"),
                  panel_lead=self.T("멀티플이 높아진 섹터의 가상 비상장 전력기기 기업, 희망공모가 밴드는?", "A hypothetical unlisted power-equipment IPO in a re-rated sector: what price range?"),
                  bullets=[self.T("국내 피어 PER·EV/EBITDA + 해외 피어(SEC EDGAR: Vertiv·Eaton·GE Vernova·Constellation·Vistra)", "Korean peers' P/E and EV/EBITDA + overseas peers (SEC EDGAR)"),
                           self.T("시총(상장사)과 재무(공시 법인) 주체 일치 검증 — 5개사 확인 완료", "Market cap (listed parent) vs financials (filer) checked for all five"),
                           self.T("적정 시총 → 공모 할인 → 희망공모가 밴드 · 몬테카를로 민감도", "Fair value → IPO discount → indicative price range · Monte Carlo sensitivity")],
                  note=self.T("Vol.3 일정·방법은 변경될 수 있음", "Timing and method of Vol.3 may change"))
        from .data import power_cost_grid
        rent_b = self.B("rent_per_kw_month").value
        load_b = self.B("it_load_factor").value or 1.0
        pue_b = self.B("pue").value
        pg = power_cost_grid(va, rent_b, list(self.v["sensitivity"].get("pue_grid", [1.3])), load_b)
        if pg is not None:
            labels_ = list(dict.fromkeys(pg["price_label"]))
            prow = []
            for pue in dict.fromkeys(pg["pue"]):
                row = [f"{pue:.1f}"]
                for lb in labels_:
                    x = pg[(pg["pue"] == pue) & (pg["price_label"] == lb)].iloc[0]
                    row.append(f"${x['usd_per_kw_month']:,.0f} ({x['share_of_rent'] * 100:.0f}%)" if rent_b else f"${x['usd_per_kw_month']:,.0f}")
                prow.append(row)
            y, p = va.price_latest
            hi = pg["share_of_rent"].max()
            lo_u, hi_u = pg["usd_per_kw_month"].min(), pg["usd_per_kw_month"].max()
            c4 = Cell(title=(self.T(f"버지니아 요금 {p:.2f}¢ 기준 전력비는 임대료의 {pg['share_of_rent'].min() * 100:.0f}~{hi * 100:.0f}% — 패스스루가 SPC를 보호하지만 임차인 부담은 크다",
                                    f"At Virginia's {p:.2f}¢, power costs {pg['share_of_rent'].min() * 100:.0f}–{hi * 100:.0f}% of rent — pass-through shields the SPC, not the tenant")
                             if rent_b else
                             self.T(f"버지니아 요금 {p:.2f}¢ 기준 전력비 IT kW당 월 ${lo_u:,.0f}~{hi_u:,.0f}", f"At Virginia's {p:.2f}¢, power costs ${lo_u:,.0f}–{hi_u:,.0f} per IT kW-month")),
                      src=["eia", "market"], unit=(self.T(f"USD/IT kW·월 (괄호 = 임대료 USD {rent_b:,.0f} 대비)", f"USD per IT kW-month (brackets = share of USD {rent_b:,.0f} rent)")
                                                   if rent_b else self.T("USD/IT kW·월", "USD per IT kW-month")),
                      table=TableSpec(["PUE"] + [self.T(f"요금 {lb}", f"Price {lb}") for lb in labels_], prow,
                                      [0.2] + [0.8 / len(labels_)] * len(labels_), ["C"] + ["R"] * len(labels_), font_size=8.6,
                                      shade_rows={i for i, pue in enumerate(dict.fromkeys(pg["pue"])) if pue_b is not None and abs(pue - pue_b) < 1e-9}),
                      note=self.T(f"전력비 = 730시간 × IT 부하율 {self.pct(load_b, 0)} × PUE × 요금. 요금 = EIA 버지니아 상업용 {y}년, 오른쪽 열 = {va.price_max_yoy[0]}년 최대 연간 상승률 적용. "
                                  + (f"음영 = 기준 PUE {pue_b:.1f}(저자 판단), 나머지는 민감도 축" if pue_b else "PUE는 민감도 축"),
                                  f"Power = 730 h × IT load {self.pct(load_b, 0)} × PUE × price. Price = EIA Virginia commercial {y}; right column applies the largest annual rise ({va.price_max_yoy[0]}). "
                                  + (f"Shaded = base PUE {pue_b:.1f} (judgment); other rows are sensitivities" if pue_b else "PUE is a sensitivity axis")))
        else:
            c4 = self.pending(self.T("케이스 B 전력비 민감도", "Case B power-cost sensitivity"), ["eia"], va if not ok(va) else Unavailable("", "", []))
        title = self.T("시사점: 데이터센터 PF 심사의 첫 번째 확인 항목은 전력비 부담 구조 — 그다음이 계통 승인과 앵커 임차인",
                       "Implication: the first item in data-centre PF credit review is the power-cost structure — then grid approval and an anchor tenant")
        sub = self.T("대주 체크리스트 · 한계 · Vol.3 예고(IPO 공모가·해외 피어) · 케이스 B 전력비 민감도(버지니아 요금)",
                     "Lender checklist · limitations · next: Vol.3 (IPO pricing, overseas peers) · Case B power-cost sensitivity (Virginia prices)")
        return Page("body", "8", title, sub, [c1, c2, c3, c4])

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
            if pbe is None and a.inp.grace_interest == "reserve" and a.inp.grace_years > 0:
                pl = a.stresses.get("prelease_low")
                lo_ = self.A("prelease").low
                ans = self.T(f"계약 임대료(사전 임대율 {self.pct(a.inp.prelease)})만으로는 OPEX·전력비도 못 덮는다(최소 DSCR {self.x(a.base.min_dscr_contracted)}). 그래서 램프업 {a.inp.grace_years}년 이자를 이자유보계좌로 미리 쌓고, "
                             f"대출은 안정화 이후 CFADS로 sculpting했다. 사전 임대율이 {self.pct(lo_)}면 유보계좌 {self.money('A', a.base.cons.reserve_initial)}이 모두 소진되고 DSRA가 나머지를 메운다"
                             + (f"(부족 {self.money('A', pl.grace_shortfall)})" if pl is not None and pl.grace_shortfall > 0.05 else "") + ". 앵커 임차인 없이는 지분이 램프업 위험을 진다",
                             f"Contracted rent ({self.pct(a.inp.prelease)} pre-let) does not even cover OPEX and power (min DSCR {self.x(a.base.min_dscr_contracted)}). Ramp-up interest is pre-funded in a reserve "
                             f"and debt is sculpted on stabilised CFADS. At {self.pct(lo_)} pre-lease the {self.money('A', a.base.cons.reserve_initial)} reserve is used up and the DSRA covers the rest"
                             + (f" (gap {self.money('A', pl.grace_shortfall)})" if pl is not None and pl.grace_shortfall > 0.05 else "") + ". Without an anchor tenant, equity carries the ramp-up risk")
            else:
                ans = None
            ans = ans or self.T(f"계약 임대료만 보면 최소 DSCR {self.x(a.base.min_dscr_contracted)}(사전 임대율 {self.pct(a.inp.prelease)}). 최소 DSCR 1.0배 손익분기 사전 임대율은 {self.pct(pbe)}다. "
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
                          + (f"대신 기준금리({self.base_label('B')})가 {self.base_label('A')}보다 {self.rate_spread():.2f}%p 높아 같은 DSCR에서도 원리금 부담이 크다" if self.rate_spread() is not None else ""),
                          (f"Virginia commercial sales grow {self.pct(va.va_cagr)}/yr vs U.S. {self.pct(va.us_cagr)}. " if ok(va) else "")
                          + (f"But its base rate ({self.base_label('B')}) is {self.rate_spread():.2f}pp above {self.base_label('A')}, so debt service is heavier at the same DSCR" if self.rate_spread() is not None else "")), "2, 6"])
        # 4 금리 +100bp
        if ok(a):
            ru = a.stresses["rate_up"]
            ans = self.T(f"대출 스케줄을 고정하면 최소 DSCR {self.x(a.base.min_dscr)} → {self.x(ru.min_dscr)}, Equity IRR {self.pct(a.base.equity_irr)} → {self.pct(ru.equity_irr)}",
                         f"With the schedule fixed, min DSCR {self.x(a.base.min_dscr)} → {self.x(ru.min_dscr)}; equity IRR {self.pct(a.base.equity_irr)} → {self.pct(ru.equity_irr)}")
        else:
            ans = self.T(f"기준금리({self.base_label('A')} {self.base_value('A'):.2f}%, {self.base_label('B')} {self.base_value('B'):.2f}%)에 ±100bp를 더해 최소 DSCR 변화를 p4에서 계산한다(가산금리 확인 후)" if ok(r) else "가정 확인 후 계산",
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
                     + (f"(버지니아 상업용 평균 {p:.2f}¢/kWh, {y}; 민감도 p8)" if ok(va) else ""),
                     f"A {pt * 100:.0f}% pass-through: the tenant pays usage × tariff, so the SPC's net power cost is zero and tariff risk becomes a tenant-affordability question"
                     + (f" (Virginia commercial average {p:.2f}¢/kWh, {y}; sensitivity on p8)" if ok(va) else ""))
        pc = self.power_clause()
        if pc is not None and not self.a_gross():
            pt_r, gr_r, _ = pc
            pcs = float(gr_r.ops["power_cost"].iloc[a.power["stab_year"] - 1]) if a.power else float("nan")
            ans = self.T(f"케이스 A·B 모두 임차인이 사용량 × 단가로 낸다(별도 청구: 도매 임대는 kW당 임대료 + 전력 별도 청구가 일반적 — Data Center Scouts·gr1d, 한·미 임대료를 같은 정의로 처리). "
                         f"임대료에 전력이 포함되면 SPC가 안정화 첫해 {self.money('A', pcs)}을 부담해 Equity IRR {self.pct(pt_r.equity_irr)} → {self.pct(gr_r.equity_irr)}, 대출 한도 {self.money('A', pt_r.debt)} → {self.money('A', gr_r.debt)}. "
                         "그래서 대주가 가장 먼저 확인할 조항이다",
                         f"In both cases the tenant pays usage × tariff (billed separately: wholesale rent is quoted per kW with power on top — Data Center Scouts, gr1d; one definition for both rents). "
                         f"If rent included power, the SPC would bear {self.money('A', pcs)} in the first stabilised year: equity IRR {self.pct(pt_r.equity_irr)} → {self.pct(gr_r.equity_irr)}, debt {self.money('A', pt_r.debt)} → {self.money('A', gr_r.debt)}. "
                         "That makes it the first clause a lender checks")
            key.add(len(qa))
        if self.a_gross() and ok(a) and "passthrough" in a.alts:
            ptr = a.alts["passthrough"]
            ans = self.T(f"케이스 A는 임대료 25만원을 전력 포함(gross)으로 보고 SPC가 낸다(원문에서 전력 포함 여부 미확인 → 보수적 대주 관점). 안정화 첫해 전력비 {self.money('A', a.power['power_cost_stab'])}"
                         f"(매출의 {self.pct(a.power['share_of_revenue_stab'], 0)}). 별도 청구면 원가 대비 수익률 {self.pct(a.yoc)} → {self.pct(pf_yoc(ptr))}, 대출 한도 {self.money('A', a.base.debt)} → {self.money('A', ptr.debt)}. "
                         + self.T("케이스 B는 임차인 부담(패스스루)", ""),
                         f"Case A treats the KRW 250k rent as gross of power, so the SPC pays (inclusion unconfirmed → conservative lender view). Stabilised power cost {self.money('A', a.power['power_cost_stab'])} "
                         f"({self.pct(a.power['share_of_revenue_stab'], 0)} of revenue). If passed through, yield on cost {self.pct(a.yoc)} → {self.pct(pf_yoc(ptr))}, debt {self.money('A', a.base.debt)} → {self.money('A', ptr.debt)}. Case B passes power to the tenant")
        qa.append([self.T("전력비는 누가 내나?", "Who pays for power?"), ans, "1, 7"])
        if pc is not None and not self.a_gross():
            mid_ = a.power_curve.get(0.5)
            qa.append([self.T("전력비를 임차인이 내면 SPC의 전력 위험은 사라지나?", "If the tenant pays for power, is the SPC's power risk gone?"),
                       self.T("아니다. take-or-pay 최소 요금과 미사용 전력 처리 조항에 달려 있다. 임차인이 배정 전력보다 덜 쓰면 계약 전력 기준 요금이 SPC에 남을 수 있어, "
                              "별도 청구 계약에도 최소 요금(배정 전력의 60~85%로 늘어나는 추세, Data Center Scouts)이 있는지 확인해야 한다. 조항이 있으면 위험은 임차인 신용 위험으로 바뀐다. "
                              + (f"이 노트의 Base는 전액 전가를 가정했고, 절반만 전가되면 Equity IRR {self.pct(pc[0].equity_irr)} → {self.pct(mid_.equity_irr)}(p7 곡선)" if mid_ is not None else ""),
                              "No. It depends on take-or-pay minimums and how unused power is treated. If the tenant draws less than its allocation, charges based on contracted capacity can stay with the SPC, "
                              "so check whether the lease sets a minimum (trending to 60–85% of allocated power, Data Center Scouts). With one, the risk becomes tenant credit risk. "
                              + (f"The base assumes full pass-through; at half, equity IRR falls {self.pct(pc[0].equity_irr)} → {self.pct(mid_.equity_irr)} (p7 curve)" if mid_ is not None else "")),
                       "7, 8"])
        # 6-2 램프업 이자
        if ok(a) and a.inp.grace_interest == "reserve" and a.inp.grace_years > 0:
            g_ = a.inp.grace_years
            gap = float((a.base.ops["interest"][:g_] - a.base.ops["cfads"][:g_]).clip(lower=0).sum())
            ans = self.T(f"준공 후 램프업 {g_}년은 원금 없이 이자만 낸다. CFADS가 이자에 못 미치는 금액(기준 시나리오 합계 {self.money('A', gap)})에 {self.pct(a.inp.reserve_buffer, 0)}를 더한 {self.money('A', a.base.cons.reserve_initial)}을 "
                         f"금융 종결 때 사업비 안에 이자유보계좌로 적립해 지급한다. 이자를 원금에 붙이지 않으므로 잔액이 늘지 않고, 원금은 {g_ + 1}년차부터 CFADS에 맞춰(sculpting) 갚는다",
                         f"For {g_} ramp-up years after COD only interest is paid. The gap where CFADS falls short of interest (base-case total {self.money('A', gap)}) plus {self.pct(a.inp.reserve_buffer, 0)} — {self.money('A', a.base.cons.reserve_initial)} — "
                         f"is funded at financial close inside project cost as an interest reserve. Interest is never capitalised, so the balance does not grow; principal is sculpted to CFADS from year {g_ + 1}")
            key.add(len(qa))
            qa.append([self.T("램프업 기간 이자는 어떻게 내나?", "How is interest paid during ramp-up?"), ans, "1, 3"])
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
                    src=["grid", "market", "lease", "iea", "ecos", "fred", "dart", "eia"],
                    table=TableSpec([self.T("질문", "Question"), self.T("답", "Answer"), self.T("근거 쪽", "Page")], qa, [0.22, 0.7, 0.08],
                                    ["L", "L", "C"], shade_rows=key, font_size=7.8 if len(qa) > 9 else 8.1),
                    note=self.T("답의 숫자는 본문과 같은 계산 결과. 음영 = 대주 관점 핵심 질문", "Numbers match the body; shaded = core lender questions"))
        return Page("full", "A1", self.T("예상 질의응답: 대주가 먼저 묻는 것", "Expected Q&A: what lenders ask first"),
                    self.T("투자심사·대주 실사에서 나올 질문과 근거 쪽수", "Questions likely in credit review and lender due diligence, with page references"), [cell], grid="1x1")

    STATUS_KR = {"input": "입력 필요", "verify": "원문 확인", "sourced": "근거 있음", "judgment": "저자 판단", "data": "데이터",
                 "design": "설계값", "neutral": "중립값", "derived": "계산"}
    STATUS_EN = {"input": "Input needed", "verify": "Verify", "sourced": "Sourced", "judgment": "Judgment", "data": "Data",
                 "design": "Design", "neutral": "Neutral", "derived": "Derived"}

    def fmt_assump(self, a: Assumption) -> str:
        v = a.value
        if v is None:
            return "—"
        if a.key == "grace_interest":
            return {"reserve": self.T("이자만 + 이자유보계좌", "interest-only + reserve"), "paid": self.T("현금 지급", "paid"),
                    "capitalized": self.T("원금 가산", "capitalised")}.get(str(v), str(v))
        if a.key == "tax_brackets":
            br = [x.split(":") for x in str(v).split(",")]
            return "/".join(r_ for _, r_ in br) + "%"
        if isinstance(v, str):
            return v
        u = a.unit
        rng_ = ""
        if a.low is not None and a.high is not None:
            lo, hi = (a.low * 100, a.high * 100) if u in ("%", "%/년", "법인세 대비 %") else (a.low, a.high)
            rng_ = f" ({lo:,.4g}~{hi:,.4g})" if self.kr else f" ({lo:,.4g}–{hi:,.4g})"
        if u in ("%", "%/년", "법인세 대비 %"):
            return f"{v * 100:.2f}".rstrip("0").rstrip(".") + "%" + rng_.replace(")", "%)") if rng_ else f"{v * 100:.2f}".rstrip("0").rstrip(".") + "%"
        if a.key == "power_price" and abs(v) >= 10:
            core = f"{v:,.1f}"
        elif abs(v) < 10:
            core = f"{v:,.4g}"
        elif abs(v) < 100 and abs(v - round(v)) > 1e-9:
            core = f"{v:,.2f}"
        else:
            core = f"{v:,.0f}"
        return core + rng_

    UNIT_EN = {"억원:%": "KRW 100mn:%", "억원/MW": "KRW 100mn/MW", "분기": "quarters", "원/kW·월": "KRW/kW-month", "%/년": "%/yr", "배": "x", "원/kW·년": "KRW/kW-yr",
               "원/kWh": "KRW/kWh", "년": "yrs", "개월": "months", "법인세 대비 %": "% of national tax", "년(1단계 COD 후)": "yrs after phase-1 COD",
               "USD/kW·월": "USD/kW-month", "USD/kW·년": "USD/kW-yr", "USD mn/MW": "USD mn/MW"}

    PUBLISHERS = [("etoday", "이투데이(다올투자증권 리포트 인용)", "Etoday (citing Daol Investment & Securities)"),
                  ("edaily", "이데일리", "Edaily"), ("blockmedia", "블록미디어(CBRE 인용)", "Blockmedia (citing CBRE)"),
                  ("gridlines", "Gridlines 2026", "Gridlines 2026"), ("taxguide", "택스가이드·법인세법 제55조", "Taxguide; Corporate Tax Act Art. 55"),
                  ("stocktitan", "Cushman & Wakefield 2026 Cost Guide", "Cushman & Wakefield 2026 Cost Guide"),
                  ("global-data-center-trends", "CBRE Global DC Trends 2026", "CBRE Global DC Trends 2026"),
                  ("north-america-data-center", "CBRE NA DC Trends H1 2026", "CBRE NA DC Trends H1 2026"), ("lev.com", "Lev 2026", "Lev 2026"),
                  ("sidae", "시대일보", "Sidae Ilbo"), ("datacenterscouts", "Data Center Scouts", "Data Center Scouts"),
                  ("gr1d", "gr1d", "gr1d"), ("hl.com", "Houlihan Lokey 2026.10", "Houlihan Lokey (Oct 2026)")]

    def publishers(self, a: Assumption) -> list[str]:
        u = a.url or ""
        return [kr if self.kr else en for key, kr, en in self.PUBLISHERS if key in u]

    def source_text(self, a: Assumption) -> str:
        """가정표 '근거·출처' 칸: 근거 있음 = 출처명, 저자 판단 = '저자 판단' + 참고 출처. 영문은 출처명만 영문으로."""
        if a.origin == "data":
            return a.source or ""
        if a.value is None:
            grid = {"discount_rate": self.v["real_option"].get("discount_grid"), "option_window_years": self.v["real_option"].get("window_grid")}.get(a.key)
            ms = (self.v["sensitivity"].get("margin_scenarios_bp") or {}).get(a.case) if a.key == "margin_bp" else None
            if a.key == "dep_years":
                return self.T("미입력 → 감가상각 미반영(법인세 보수적)", "Not set → no depreciation (tax conservative)")
            if a.key == "exit_cap_rate":
                return self.T("미입력 → 잔존가치 제외", "Not set → no terminal value")
            if a.key in ("pue", "it_load_factor"):
                return self.T("미입력 → 전력비 패스스루 100%로 SPC 순액 0", "Not set → 100% pass-through, SPC net power cost zero")
            if ms:
                return self.T(f"미확정 → {'/'.join(str(x) for x in ms)}bp 시나리오", f"Not sourced → {'/'.join(str(x) for x in ms)}bp scenarios")
            if grid and a.case == "A":
                vals = "/".join(f"{x * 100:.0f}%" if a.key == "discount_rate" else f"{x}" for x in grid)
                return self.T(f"미확정 → 민감도 격자 {vals}" + ("" if a.key == "discount_rate" else "년"), f"Not sourced → sensitivity grid {vals}" + ("" if a.key == "discount_rate" else " yrs"))
            return self.T("근거 확인 중", "Being sourced")
        pubs = self.publishers(a)
        st = a.status
        if self.kr:
            text = a.source or ""
            if st == "sourced" and pubs and not any(p_.split("(")[0] in text for p_ in pubs):
                text += " · " + ", ".join(pubs)
            extra = " · ".join(x for x in (a.published,) if x)
            return text + (f" · {extra}" if extra else "")
        if st == "judgment":
            return "Author's judgment" + (f"; ref. {', '.join(pubs)}" if pubs else "")
        if st == "sourced":
            if pubs:
                return ", ".join(pubs) + (f" · {a.published}" if a.published else "")
            return {"tax_rate_local": "Local income tax (10% of corporate tax)"}.get(a.key, "Public source")
        if st == "verify":
            return {"tax_rate_national": "26 U.S.C. §11(b)", "tax_rate_local": "Va. Code §58.1-400"}.get(a.key, "Public source, to verify")
        return {"design": "Hypothetical case design", "neutral": "Neutral value pending evidence", "derived": "Derived"}.get(st, "")

    def a_assumptions(self, case: str, label: str) -> Page:
        d = self.f.assumptions[case]
        from .data import table_keys
        keys = table_keys(case, d)
        rows, brick, shade, gold, strong = [], set(), set(), set(), set()
        st = self.STATUS_KR if self.kr else self.STATUS_EN
        for i, k in enumerate(keys):
            a = d[k]
            unit = a.unit if self.kr else self.UNIT_EN.get(a.unit, a.unit)
            rows.append([self.lab(k), self.fmt_assump(a), unit, self.source_text(a), st[a.status]])
            if a.status == "input":
                brick.add((i, 4))
            elif a.status == "sourced":
                gold.add((i, 4))
            elif a.status == "judgment":
                strong.add((i, 4))
                shade.add(i)
        n_s = sum(d[k].status == "sourced" for k in keys)
        n_j = sum(d[k].status == "judgment" for k in keys)
        n_i = sum(d[k].status == "input" for k in keys)
        cell = Cell(title=self.T(f"{self.name(case)}: 근거 있음 {n_s}개 · 저자 판단 {n_j}개 · 미입력 {n_i}개 — 판단은 음영으로 구분",
                                 f"{self.name(case)}: {n_s} sourced · {n_j} author's judgment · {n_i} not set — judgments shaded"),
                    src=["market", "cost", "finance", "tax", "hl"] if case == "B" else ["market", "lease", "cost", "finance", "tax", "grid", "hl"],
                    table=TableSpec([self.T("항목", "Item"), self.T("값 (범위)", "Value (range)"), self.T("단위", "Unit"), self.T("근거·출처", "Basis / source"),
                                     self.T("상태", "Status")], rows, [0.19, 0.14, 0.10, 0.46, 0.11], ["L", "R", "L", "L", "C"],
                                    shade_rows=shade, brick_cells=brick, gold_cells=gold, strong_cells=strong, font_size=7.4),
                    note=self.T("상태: 근거 있음(골드) = 공개 출처 값 · 저자 판단(음영·브라운) = 출처를 참고한 저자 설정, 민감도로 점검 · 입력 필요(적색) = 미입력, 계산 제외 또는 보수적 처리 · "
                                "원문 확인 = 법령 등 공개 근거, 원문 대조 전 · 설계값 = 가상 케이스 설정 · 데이터 = 공식 통계",
                                "Status: sourced (gold) = public source · judgment (shaded, brown) = author's setting informed by sources, stress-tested · input needed (red) = not set, excluded or treated conservatively · "
                                "verify = public basis, not yet checked against the original · design = hypothetical case setting · data = official statistics"))
        name = self.v["cases"][case]["name_kr" if self.kr else "name_en"]
        return Page("full", label, self.T(f"가정과 출처: {self.name(case)} — 근거 있음과 저자 판단을 구분", f"Assumptions and sources: {self.name(case)} — sourced vs judgment"),
                    name, [cell], grid="1x1")

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
            if g.ratio_n is not None:
                krows.append([self.T("계통 승인률 (건수)", "Grid approval (count)"), f"{g.approved_n:,.0f} ÷ {g.applied_n:,.0f} = {self.pct(g.ratio_n, 2)}", g.period,
                              self.T("블록미디어(확인 완료)", "Blockmedia (verified)")])
            krows.append([self.T("계통 승인률 (용량)", "Grid approval (capacity)"), f"{g.approved:,.0f} ÷ {g.applied:,.0f} = {self.pct(g.ratio, 2)}", g.period,
                          self.T("블록미디어(확인 완료)", "Blockmedia (verified)")])
        if ok(self.f.va):
            y, p = self.f.va.price_latest
            krows.append([self.T("버지니아 상업용 평균 요금", "Virginia commercial average price"), f"{p:.2f}¢/kWh", str(y), "EIA"])
        pa = self.A("power_price")
        if pa.value is not None and pa.origin == "csv":
            krows.append([self.T("한전 평균 산업용 판매단가 (케이스 A)", "KEPCO average industrial tariff (Case A)"),
                          self.T(f"{pa.value:,.1f}원/kWh", f"KRW {pa.value:,.1f}/kWh"), "2025", self.T(f"시대일보 {pa.published or ''}", f"Sidae Ilbo {pa.published or ''}")])
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
            (self.T("이자유보계좌", "Interest reserve"), self.T("램프업 기간 CFADS가 이자에 못 미치는 금액을 금융 종결 때 사업비로 미리 적립한 계좌", "Account funded at close from project cost to pay ramp-up interest that CFADS cannot cover")),
            (self.T("원가 대비 수익률", "Yield on cost"), self.T("안정화 첫해 EBITDA ÷ 총사업비. 대출금리·cap rate와 비교하는 개발 수익률", "First stabilised-year EBITDA ÷ total cost; development yield compared with debt cost and cap rates")),
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
                                    shade_rows={0, 1, 2, 3, 5}, font_size=8.0),
                    note=self.T("음영 = 대주 관점 핵심 지표", "Shaded = core lender metrics"))
        return Page("full", "A6", self.T("용어 정의: 대주가 쓰는 말", "Glossary: the lender's vocabulary"),
                    self.T("금액 단위: 원화 억원, 달러 USD mn · 비율 %, 배", "Units: KRW 100mn, USD mn · %, x"), [cell], grid="1x1")
