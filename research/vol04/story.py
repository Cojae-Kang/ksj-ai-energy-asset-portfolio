"""Vol.4 페이지 구성·문구 (국문/영문). 숫자는 모두 data.Facts에서, 결론 문장도 계산 결과로 만든다.

공개용 원칙(Vol.1~3과 같음): 내부 파일·설정·명령은 보고서에 쓰지 않는다. 공식 원문으로 교체 대기 중인 입력을 쓰는
Exhibit은 각주에 '잠정'을 붙인다(신뢰 등급 A 공식 원문 · B 공식 발표 보도 · C 민간 2차 · J 저자 판단).
"""
from __future__ import annotations

import math
from typing import Mapping

import numpy as np

from research.vol01.layout import BigBox, Cell, Page, TableSpec, toc_line

from . import charts
from .data import LABELS, TIER_EN, TIER_KR, Facts, mc_stats, ok

ROUTE_KR = {"cfd": "한전 계약(CfD)", "ppa": "데이터센터 직접 PPA", "merchant": "시장 판매(SMP)"}
ROUTE_EN = {"cfd": "KEPCO contract (CfD)", "ppa": "Direct PPA with data centre", "merchant": "Merchant (SMP)"}
ROUTE_S_KR = {"cfd": "한전 CfD", "ppa": "직접 PPA", "merchant": "시장 SMP"}
ROUTE_S_EN = {"cfd": "KEPCO CfD", "ppa": "Direct PPA", "merchant": "Merchant"}


class Story:
    BUILT_WITH_KR = "구현: AI 코딩 도구(Claude Code)로 현금흐름·대출 sizing·손익분기·몬테카를로·보고서 생성 코드를 작성. 질문 설계, 출처 등급 판정, 가정 판단, 숫자 검증은 저자."
    BUILT_WITH_EN = ("Built with an AI coding tool (Claude Code) for cash flows, debt sizing, break-evens, Monte Carlo and report generation; "
                     "question design, source grading, assumption judgments and number checks by the author.")

    def __init__(self, cfg: Mapping, f: Facts, lang: str, vol2: dict | None = None):
        self.cfg, self.f, self.lang, self.kr = cfg, f, lang, lang == "kr"
        self.c = cfg["research"]["colors"]
        self.v = cfg["research"]["vol04"]
        self.vol2 = vol2 or {}
        self.hurdle = f.V("equity_hurdle")
        self.mc_h = float(self.v["monte_carlo"]["hazard"])

    # --- 도우미 -------------------------------------------------------------
    def T(self, kr: str, en: str) -> str:
        return kr if self.kr else en

    @staticmethod
    def pct(v: float | None, d: int = 1, sign: bool = False) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        x = round(v * 100, d) + 0.0                  # -0.0% 방지
        return f"{x:+.{d}f}%" if sign else f"{x:.{d}f}%"

    def kwh(self, v: float | None, d: int = 1) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:,.{d}f}원/kWh" if self.kr else f"KRW {v:,.{d}f}/kWh"

    def won(self, v: float | None, d: int = 1) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:,.{d}f}원" if self.kr else f"KRW {v:,.{d}f}"

    def eok(self, v: float | None) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:,.0f}억원" if self.kr else (f"KRW {v / 10:,.0f}bn" if abs(v) >= 1000 else f"KRW {v / 10:,.1f}bn")

    def gwh(self, v: float) -> str:
        return f"{v:,.1f}GWh" if self.kr else f"{v:,.1f} GWh"

    def x(self, v: float | None, d: int = 2) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:,.{d}f}배" if self.kr else f"{v:,.{d}f}x"

    def route(self, k: str, short: bool = False) -> str:
        return (ROUTE_S_KR if short else ROUTE_KR)[k] if self.kr else (ROUTE_S_EN if short else ROUTE_EN)[k]

    def lab(self, key: str) -> str:
        return LABELS.get(key, (key, key))[0 if self.kr else 1]

    def prem(self, h: float) -> dict:
        return next(p for p in self.f.premium if abs(p["hazard"] - h) < 1e-12)

    def prov_note(self, keys: list[str]) -> str:
        """이 Exhibit이 쓰는 입력 중 공식 원문 교체 대기 항목 → 각주 꼬리."""
        p = [k for k in keys if k in self.f.provisional]
        if not p:
            return ""
        names = ", ".join(self.lab(k) for k in p)
        return self.T(f" · 잠정: {names}는 공식 원문 확인 전 값(A3)", f" · Provisional: {names} pending official source (A3)")

    def clear_text(self) -> str:
        ok_ = [k for k in ("cfd", "ppa", "merchant") if (self.irr[k] or -1) >= self.hurdle]
        no = [k for k in ("cfd", "ppa", "merchant") if k not in ok_]
        a = "·".join(self.route(k, True) for k in ok_) or self.T("없음", "none")
        b = "·".join(self.route(k, True) for k in no) or self.T("없음", "none")
        return self.T(f"{a} 통과, {b} 미달", f"{a} clear, {b} miss")

    @property
    def irr(self) -> dict[str, float | None]:
        return {k: r.irr for k, r in self.f.base.items()}

    # --- 출처·고정 문구 ----------------------------------------------------
    def sources(self) -> dict[str, str]:
        return {
            "mcee": self.T("기후에너지환경부 보도자료(2026-07-16, 2026년도 1차 태양광 경쟁입찰 공고)",
                           "Ministry of Climate, Energy and Environment release (16 Jul 2026, round-1 solar auction)"),
            "react": self.T("재생에너지법 개정(법률 제21943호, 2026-09-15 공포) 제12조의14·부칙 제1~4조 — 국가법령정보센터 원문",
                            "Renewable Energy Act amendment (Act No. 21943, promulgated 15 Sep 2026), art. 12-14 and addendum arts. 1–4 — law.go.kr original"),
            "kepco_fuel": self.T("한전ON 원가연계형 요금제(연료비조정요금) — 조정단가 연간 상하한", "KEPCO ON cost-linked tariff (fuel cost adjustment) — annual band on the adjustment rate"),
            "reform": self.T("파이낸셜뉴스(2026-09-15, 기후에너지환경부 발표 인용): 재생에너지법 개정·계약시장 전환",
                             "Financial News (15 Sep 2026, citing the ministry): Renewable Energy Act reform"),
            "kepco": self.T("한전 전력통계월보 제566호(2025.12) 표 18·18-2(계약종별 판매전력량·판매수입)", "KEPCO Monthly Statistics no.566 (Dec 2025), tables 18 and 18-2"),
            "tou": self.T("기후에너지환경부·한전 보도참고자료(2026-03-13) [붙임2] 산업용(을) 계절·시간대별 요금 개편", "Ministry of Climate, Energy and Environment and KEPCO release (13 Mar 2026), annex 2: industrial (B) time-of-use rates"),
            "solar": self.T("한전 전력통계월보 제566호 16-1(2025년 월별 태양광 발전량)", "KEPCO Monthly Statistics no.566, table 16-1 (2025 monthly solar output)"),
            "keei": self.T("에너지경제연구원 기본연구 25-04(2025) — LCOE(이근대·임덕오 2024 재인용)·이용률·WACC(BNEF 인용)·설치비", "KEEI Basic Research 25-04 (2025) — LCOE (citing Lee & Lim 2024), CF and WACC (citing BNEF), unit cost"),
            "smp": self.T("전력거래소 EPSIS 계통한계가격(월별 가중평균·시간별, 육지)", "KPX EPSIS system marginal price (monthly weighted and hourly, mainland)"),
            "ecos": self.T("한국은행 ECOS 국고채 3년·원/달러", "Bank of Korea ECOS KTB 3-yr, USD/KRW"),
            "nrel": self.T("NREL Jordan & Kurtz(2012), PV 열화율 리뷰", "NREL Jordan & Kurtz (2012), PV degradation review"),
            "sec": self.T("Talen Energy 8-K(2025-06-11, SEC EDGAR)", "Talen Energy Form 8-K (11 Jun 2025, SEC EDGAR)"),
            "levelten": self.T("TaiyangNews(2026-07-23, LevelTen 2026년 2분기 보고서 인용)", "TaiyangNews (23 Jul 2026, citing LevelTen Q2 2026)"),
            "dist": self.T("헤럴드K(2026-05-09) · 한국경제(2026-02-03): 분산에너지·AI 데이터센터 특별법", "Herald K (9 May 2026) · Hankyung (3 Feb 2026): distributed energy, AI data-centre act"),
            "law": self.T("법인세법 제55조 · 지방세법(국가법령정보센터)", "Corporate Tax Act art. 55 · Local Tax Act (law.go.kr)"),
            "vol2": self.T("KSJ Research Vol.2(2026.10)", "KSJ Research Vol.2 (Oct 2026)"),
            "sfoc": self.T("기후솔루션 「좌초되는 RE100 제도」(2021-12) 인쇄 9쪽(PDF 11쪽) 표 2 — 한전 에너지마켓플레이스 제3자 PPA 요금 시뮬레이션", "SFOC, 'Stranded RE100' (Dec 2021), printed p.9 (PDF p.11) table 2 — KEPCO's third-party PPA charge simulator"),
            "notice": self.T("직접 PPA 고시(기후에너지환경부고시 제2025-61호) 제25조③·제9조④", "Direct-PPA notice (MCEE 2025-61), art. 25(3), 9(4)"),
            "decree": self.T("전기사업법 시행령 제36조(대통령령 제36587호)", "Electricity Business Act decree art. 36"),
            "kimchang": self.T("김·장 법률사무소 뉴스레터(2022-09-13): 직접 PPA 고시 시행", "Kim & Chang newsletter (13 Sep 2022): direct-PPA notice in force"),
            "kpx": self.T("한국전력거래소 질의응답(2023-12-19): 직접 PPA 부가정산금 단가", "KPX Q&A (19 Dec 2023): direct-PPA ancillary settlement rate"),
            "survey": self.T("뉴시스(2026-05-04): 기후솔루션 기업 설문·전력거래소 직접 PPA 연구 용역", "Newsis (4 May 2026): SFOC corporate survey, KPX direct-PPA study"),
            "ksj": "KSJ Research",
        }

    def labels(self) -> dict[str, str]:
        return {"source": self.T("출처", "Source"), "note": self.T("주", "Note"), "unit": self.T("단위", "Unit"),
                "pending": self.T("데이터·출처 확인 후 생성", "Generated once data are collected")}

    def footer(self) -> str:
        return self.T(f"KSJ Research · Research Note Vol.4 · {self.v['date_label']} · 교육·연구 목적, 투자 권유 아님 · 발전자산은 가상 자산",
                      f"KSJ Research · Research Note Vol.4 · {self.v['date_label']} · For education and research only, not investment advice · "
                      "the asset is hypothetical")

    # =======================================================================
    def pages(self) -> list[Page]:
        return [self.cover(), self.executive(), self.toc_page(), self.p1(), self.p2(), self.p3(), self.p4(), self.p5(),
                self.p6(), self.p7(), self.p8(), self.a1(), self.a2(0), self.a2(1), self.a4(), self.a5(), self.back()]

    def cover(self) -> Page:
        return Page("cover", title=self.v["title_kr"] if self.kr else self.v["title_en"],
                    subtitle=(self.v["subtitle_kr"] if self.kr else self.v["subtitle_en"]).format(mw=f"{self.f.asset.mw:,.0f}"),
                    extra={"kicker": "Research Note Vol.4", "author": self.cfg["research"]["author"], "date": self.v["date_label"],
                           "note": self.T("KSJ Research · 교육·연구 목적 · 투자 권유 아님 · 발전자산은 가상 자산",
                                          "KSJ Research · For education and research only · Not investment advice · Hypothetical asset")})

    def back(self) -> Page:
        items = [
            self.T("이 자료는 교육·연구 목적의 개인 포트폴리오이며, 투자 권유나 특정 자산·종목에 대한 의견이 아니다.",
                   "This is a personal portfolio for education and research. It is not investment advice or a view on any asset or security."),
            self.T(f"태양광 {self.f.asset.mw:,.0f}MW 발전자산과 데이터센터 오프테이커는 가상 사례다. 실제 계약 가격·조건이 아니다.",
                   f"The {self.f.asset.mw:,.0f} MW solar asset and the data-centre offtaker are hypothetical; no actual contract prices or terms are shown."),
            self.T("본문의 판단은 저자 개인의 견해이며, 저자가 속했거나 속할 어떤 기관의 견해도 대변하지 않는다.",
                   "Views are the author's own and do not represent any current or future employer."),
            self.T("모든 입력에 신뢰 등급(공식 원문 · 공식 자료 계산 · 공식 발표 보도 · 민간 2차 · 저자 판단)을 붙였다. 목록과 출처는 Appendix A2~A4에 있다.",
                   "Every input carries a source grade (official · computed from official data · press report of official release · secondary · judgement); see Appendix A2–A4."),
            self.T(f"기준일 {self.f.as_of}. 계산 방법과 코드는 저장소에서 재현할 수 있다.",
                   f"As of {self.f.as_of}. Methods and code can be reproduced from the repository."),
        ]
        from research.disclosures import contact_line, license_items
        items += license_items(self.cfg, self.kr)
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"],
                                                         "contact": contact_line(self.cfg)})

    # --- 요약 ----------------------------------------------------------------
    def pg(self, h: float, sp: float) -> dict:
        return next(p for p in self.f.extra["premium_grid"] if abs(p["hazard"] - h) < 1e-12 and abs(p["spread"] - sp) < 1e-12)

    def prem_rng(self) -> tuple[dict, dict]:
        sp = self.v["risk_spreads"]
        return self.pg(self.mc_h, min(sp)), self.pg(self.mc_h, max(sp))

    def rec_end(self) -> str:
        """REC 조항 효력 종료 연도 — 입력 rec_eligible 출처(재생에너지법 부칙 제2조 원문)에서 읽는다."""
        import re
        m = re.search(r"(\d{4})-12-31까지 효력", self.f.inputs["rec_eligible"].source)
        return m.group(1) if m else "TODO"

    def fuel_cap_text(self) -> str:
        """연료비조정 적용값 vs 약관상 연간 상한(한전ON, A): 상한과 같으면 '구매자 상한을 가장 높게 잡은 가정' 문장."""
        cap = self.f.inputs.get("fuel_adj_cap")
        fa = self.f.inputs["fuel_adj"].value
        if cap is None or not isinstance(cap.value, (int, float)) or not isinstance(fa, (int, float)):
            return ""
        lo = self.prem_rng()[0]
        at_cap = abs(float(fa) - float(cap.value)) < 1e-9
        short = self.verdict() != "ok"
        if at_cap:
            return self.T(f"연료비조정 +{fa:g}원은 약관상 연간 상한(±{cap.value:g}원, 한전ON, A) — 20년 적용은 구매자 상한을 가장 높게 잡은 가정이며"
                          + (f", 그래도 망이용료를 덮지 못함(여유 최대 {lo['max_fee']:.1f}원 < 사례 {self.net_ex():.0f}원). " if short else ". "),
                          f"The +{fa:g} fuel adjustment is the KEPCO rule's annual cap (±{cap.value:g}, KEPCO ON, A) — holding it for 20 years puts the buyer ceiling at its highest"
                          + (f", and it still does not cover network charges (room at most {lo['max_fee']:.1f} < {self.net_ex():.0f} example). " if short else ". "))
        return self.T(f"연료비조정 +{fa:g}원은 약관상 연간 상한(±{cap.value:g}원, A) 안. ", f"The +{fa:g} fuel adjustment sits inside the ±{cap.value:g} annual cap (A). ")

    def net_ex(self) -> float:
        return self.f.V("net_charge_example")

    # --- 구매자 상한(태양광 시간대 회피 전력량요금) ---------------------------------
    @property
    def tc(self) -> dict:
        return self.f.extra["tou"]

    def avg(self) -> float:
        """한전 산업용 평균 판매단가(기본요금 포함) — 참고선."""
        return float(self.f.extra["avg_tariff"])

    def season(self, k: str) -> float:
        """계절 회피 요금 = 시간대별 에너지요금 + kWh당 추가 요금(연료비조정 등, 확보된 것만)."""
        return float(self.tc["base"]["season"][k]) + float(self.tc["adder"])

    def stage_val(self, key: str) -> float | None:
        return dict(self.tc["stages"]).get(key)

    def stage_text(self, d: int = 1) -> str:
        """'에너지요금 151.3 → +연료비조정 156.3 → +기후환경 TODO' (3단 상한)."""
        nm = {"energy": self.T("에너지요금", "energy rate"), "fuel": self.T("+연료비조정", "+fuel adj."), "climate": self.T("+기후환경", "+climate"),
              "fund": self.T("+기반기금", "+fund levy")}
        return " → ".join(f"{nm[k]} " + (f"{v:,.{d}f}" if v is not None else self.T("TODO(원문 대기)", "TODO (pending)")) for k, v in self.tc["stages"])

    def cap_basis(self, fund: bool = False) -> str:
        """상한에 들어간 요소 이름 (예: '에너지요금 + 연료비조정'). fund=True면 망이용료 비교 기준(+기반기금)."""
        nm = {"energy": self.T("에너지요금", "energy rate"), "fuel": self.T("연료비조정", "fuel adjustment"), "climate": self.T("기후환경요금", "climate charge"),
              "fund": self.T("기반기금", "fund levy")}
        return " + ".join(nm[k] for k, v in self.tc["stages"] if v is not None and (fund or k != "fund"))

    def room_cap(self) -> float:
        """망이용료 여유의 기준 = 회피 요금 × (1 + 기반기금 요율). 기반기금을 포함한 부대비용(공개 사례)과 같은 기준. 요율이 없으면 회피 요금."""
        return float(self.tc["room_cap"])

    def fund_pct(self) -> str:
        r = self.tc.get("fund_rate")
        return f"{r * 100:g}%" if r is not None else "TODO"

    def climate_text(self) -> str:
        """기후환경요금 반영 상태 (값이 있으면 단가·출처, 없으면 원문 대기)."""
        v = self.stage_val("climate")
        if v is None:
            return self.T("기후환경요금은 원문 대기로 미포함", "climate charge pending and excluded")
        x = self.f.inputs["climate_env"]
        return self.T(f"기후환경요금 {float(x.value):,.1f}원(한전ON, {x.published} 적용, 공식 원문)", f"climate charge {float(x.value):,.1f} (KEPCO ON, effective {x.published}, official)")

    NET_ITEM_EN = {"송배전 기본": "T&D base", "사용": "usage", "손실": "losses", "부가정산금": "settlement", "거래수수료": "trading fee",
                   "복지/특례할인": "welfare/special discounts", "전력산업기반기금": "fund levy"}

    def net_case(self) -> str:
        """공개 사례의 성격 (예: '한전 중개 제3자 PPA, 태양광 중대형 Case 1, 2020년 기준 분석')."""
        nb = self.v["net_charge_basis"]
        return self.T(nb["case_kr"], nb["case_en"])

    def fund_text(self) -> str:
        """기반기금 비대칭: 사례 부대비용에는 있고 회피 요금에는 없다 → 요율(시행령 제36조)로 기준을 맞춘다. 요율이 없으면 문장만(숫자 추정 금지)."""
        n = self.f.extra["net"]
        if n["fund"] is None:
            return ""
        if n["fund_add"] is None:
            return self.T(f"사례 {n['total']:.0f}원에는 기반기금 {n['fund']:g}원이 들어 있으나 회피 요금에는 없다 — 기준을 맞추면 여유가 기반기금만큼 커짐(요율 원문 대기, TODO)",
                          f"The {n['total']:.0f} example includes a {n['fund']:g} fund levy that the avoided rate omits — on a matched basis the room grows by the levy (rate pending, TODO)")
        return self.T(f"사례 {n['total']:.0f}원에는 기반기금 {n['fund']:g}원이 들어 있고, 한전 요금에도 기반기금(전기요금의 {self.fund_pct()}, 전기사업법 시행령 제36조, A)이 붙는다 → 망이용료 여유는 회피 요금 × (1 + {self.fund_pct()}) = {self.room_cap():,.1f}원 기준(+{n['fund_add']:,.1f}원; 전기요금 전체 부과 비율을 kWh당 요금에 곱한 근사). "
                      f"PPA 대금에도 같은 비율이 붙어 PPA 가격 상한 {self.f.corridor[1]:,.1f}원에서는 상쇄",
                      f"The {n['total']:.0f} example includes a {n['fund']:g} fund levy; KEPCO bills carry it too ({self.fund_pct()}, decree art. 36, A) → room on the avoided rate × (1 + {self.fund_pct()}) = {self.room_cap():,.1f} (+{n['fund_add']:,.1f}, per-kWh approximation); "
                      f"it cancels in the {self.f.corridor[1]:,.1f} price ceiling as the PPA payment bears it too")

    def net_basis_note(self, items_shown: bool = True) -> str:
        """공개 사례 부대비용과 구매자 상한이 같은 기준인지: 사례 성격·조건·시점·내역(반올림), 직접 PPA 고시 제25조③ 부담 항목(A), 사례에만 있는 항목, 기반기금.

        items_shown=False: 본문 차트 각주용 — 표 2 내역·반올림·고시 단서·기반기금 상세는 A4에만(차트 높이 확보)."""
        n, nb = self.f.extra["net"], self.v["net_charge_basis"]
        ad = float(self.tc["adder"])
        names = {"fuel": self.T("연료비조정", "fuel adjustment"), "climate": self.T("기후환경요금", "climate charge")}
        adds = [names[k] for k, v in self.tc["stages"] if k in names and v is not None]
        items = " · ".join(f"{k if self.kr else self.NET_ITEM_EN.get(k, k)} {v:g}" for k, v in n["items"])
        rnd = abs(n["item_sum"] - n["total"]) >= 0.5
        only = n.get("case_only", [])
        only_v = dict(n["items"])
        kr = (f" 공개 사례 {n['total']:.0f}원 = {nb['case_kr']}(B; " + (f"{nb['conditions_kr']}; " if items_shown else "") + f"{nb['timing_kr']}) — {nb['table_ref_kr']}"
              + ((f": {items}" + (f"(표 총계 {n['total']:.0f} vs 항목 합 {n['item_sum']:.0f}, 반올림)" if rnd else "")) if items_shown else ", 내역 A4") + "."
              + f" 직접 PPA 사용자 부담 = {'·'.join(nb['direct_ppa_items_kr'])}({nb['direct_ppa_source_kr']}"
              + (f"; {nb['direct_ppa_aux_kr']}; {nb['other_item_kr']}" if items_shown else "") + ")"
              + (f" — {'·'.join(adds)}은 없음 → 상한에 {ad:,.1f}원을 더한 것이 같은 기준 비교." if adds and ad > 0 else ".")
              + (f" 사례의 {'·'.join(f'{k} {only_v[k]:g}원' for k in only)}은 고시 항목에 없어 직접 PPA 부대비용은 사례보다 작을 수 있음." if only and items_shown else ""))
        en = (f" Public example {n['total']:.0f} = {nb['case_en']} (B; " + (f"{nb['conditions_en']}; " if items_shown else "") + f"{nb['timing_en']}) — {nb['table_ref_en']}"
              + ((f": {items}" + (f" (table total {n['total']:.0f} vs item sum {n['item_sum']:.0f}, rounding)" if rnd else "")) if items_shown else "; breakdown in A4") + "."
              + f" A direct-PPA buyer pays {', '.join(nb['direct_ppa_items_en'])} ({nb['direct_ppa_source_en']}"
              + (f"; {nb['direct_ppa_aux_en']}; {nb['other_item_en']}" if items_shown else "") + ")"
              + (f" — no {' or '.join(adds)} → the ceiling with the {ad:,.1f} added is the like-for-like comparison." if adds and ad > 0 else ".")
              + (f" The example's {', '.join(f'{self.NET_ITEM_EN.get(k, k)} {only_v[k]:g}' for k in only)} is not a notice item, so direct-PPA charges may be lower than the example." if only and items_shown else ""))
        out = self.T(kr, en)
        if items_shown:
            out += " " + self.T(nb["proviso_kr"], nb["proviso_en"]) + "."
            ft = self.fund_text()
            out += f" {ft}." if ft else ""
        elif n["fund"] is not None:
            out += self.T(f" 망이용료 여유는 기반기금({self.fund_pct()}) 포함 기준 {self.room_cap():,.1f}원 — 상세 A4.", f" Room is measured with the {self.fund_pct()} fund levy, {self.room_cap():,.1f} — details in A4.")
        return out

    def verdict(self) -> str:
        """'none' = 망이용료 0원이어도 손해(스프레드 0에서도 여유 음수) · 'charges' = 여유는 있으나 공개 사례 망이용료보다 작음 · 'ok'."""
        lo = self.prem_rng()[0]
        return "none" if lo["max_fee_ex"] < 0 else ("charges" if lo["max_fee"] < self.net_ex() else "ok")

    def season_name(self, k: str, short: bool = False) -> str:
        if short:
            return self.T({"summer": "여름", "spring_autumn": "봄·가을", "winter": "겨울"}[k], {"summer": "summer", "spring_autumn": "spring/autumn", "winter": "winter"}[k])
        from .tou import SEASON_EN, SEASON_KR
        return (SEASON_KR if self.kr else SEASON_EN)[k]

    def below_cfd(self) -> list[str]:
        """회피 요금이 한전 계약가보다 낮은 계절."""
        return [k for k in ("spring_autumn", "summer", "winter") if self.season(k) < self.f.corridor[0]]

    def contract(self) -> str:
        v, o = self.tc["contract"]
        return self.T(f"{v} {o}", f"HV-{v[-1]} option {'I' * (('Ⅰ', 'Ⅱ', 'Ⅲ').index(o[-1]) + 1)}")

    @staticmethod
    def sg(v: float | None, d: int = 1, plus: bool = False) -> str:
        """부호 있는 숫자 (음수는 −, plus면 양수에 +)."""
        if v is None or not math.isfinite(v):
            return "—"
        x = round(v, d) + 0.0
        t = f"{abs(x):,.{d}f}"
        return ("−" + t) if x < 0 else (("+" + t) if plus else t)

    def room_rng(self, a: float, b: float, d: int = 1) -> str:
        """여유 범위 a(작은 값)~b(큰 값) 원."""
        sep = " ~ " if (a < 0 or b < 0) else "~"
        return f"{self.sg(a, d)}{sep}{self.sg(b, d)}" + self.T("원", "")

    def no_room(self) -> bool:
        """연 해지 기준·스프레드 0에서도 여유가 음수(망이용료 0원이어도 구매자 손해)인가."""
        return self.prem_rng()[0]["max_fee_ex"] < 0

    def wtp_need(self, p: dict, charge: float, fund_incl: bool = True) -> float:
        """PPA 성립에 필요한 구매자 추가 지불(RE100 가치 등) = 필요 가격 + 부대비용 − 회피 요금 (원/kWh). 음수면 0(추가 지불 불필요).

        fund_incl: 부대비용이 기반기금을 포함(공개 사례 40원)하면 회피 요금도 기반기금 포함(room_cap), 아니면(부가정산금 단가) 기반기금 제외 상한."""
        return max(0.0, p["price"] + charge - (self.room_cap() if fund_incl else self.f.corridor[1]))

    def headline(self) -> str:
        lo, hi = self.prem_rng()
        cap = self.f.corridor[1]
        if self.no_room():
            return self.T(f"데이터센터가 실제로 아끼는 태양광 시간대 요금은 {cap:,.1f}원({self.cap_basis()}) — 발전사 필요 가격 {lo['price']:,.1f}~{hi['price']:,.1f}원보다 낮아, 망이용료 전부터 직접 PPA가 닫힌다",
                          f"The data centre's solar-hour saving is KRW {cap:,.1f} ({self.cap_basis()}) — below the seller's required {lo['price']:,.1f}–{hi['price']:,.1f}, so the direct PPA fails before any network charge")
        if self.verdict() == "charges":
            cap = self.room_cap()
            return self.T(f"데이터센터가 아끼는 요금 {cap:,.1f}원({self.cap_basis(True)}) − 필요 PPA {lo['price']:,.1f}~{hi['price']:,.1f}원 = 망이용료 여유 {self.room_rng(hi['max_fee'], lo['max_fee'])} — 최대 약 {lo['max_fee']:,.0f}원 < 공개 사례 망이용료 {self.net_ex():.0f}원(B)",
                          f"The data centre saves {cap:,.1f} ({self.cap_basis(True)}) − required PPA {lo['price']:,.1f}–{hi['price']:,.1f} = room {self.room_rng(hi['max_fee'], lo['max_fee'])} — at most ~{lo['max_fee']:,.0f} < ~{self.net_ex():.0f} network charges in a public example (B)")
        return self.T(f"직접 PPA 가격은 맞출 수 있다(한전 계약 +{lo['premium']:.0f}~{hi['premium']:.0f}원) — 막히는 곳은 망이용료: 데이터센터 여유 {self.room_rng(hi['max_fee'], lo['max_fee'], 0)} vs 공개 사례 약 {self.net_ex():.0f}원",
                      f"A direct PPA can be priced (+KRW {lo['premium']:.0f}–{hi['premium']:.0f} over KEPCO) — network charges block it: the buyer's room is {self.room_rng(hi['max_fee'], lo['max_fee'], 0)} vs ~{self.net_ex():.0f} in a public example")

    def exec_conclusions(self) -> list[str]:
        return [self.headline()] + [b.title for b in self.boxes()]

    def boxes(self) -> list[BigBox]:
        f, irr = self.f, self.irr
        lo, hi = self.prem_rng()
        sp = self.v["risk_spreads"]
        g = f.extra["gearing_check"]
        b1 = BigBox(self.ip("ppa"), self.T(f"지분 IRR · 직접 PPA (회랑 중간 {self.kwh(f.ppa_mid)}, 해지 없음)", f"Equity IRR · direct PPA (corridor mid {self.kwh(f.ppa_mid)}, no termination)"),
                    self.T("같은 발전소, 파는 곳만 다르면 지분 IRR " + " → ".join(f"{self.route(k, True)} {self.ip(k)}" for k in self.irr_order()),
                           "Same plant, different buyer: equity IRR " + " → ".join(f"{self.route(k, True)} {self.ip(k)}" for k in self.irr_order())),
                    [self.T(f"한전 계약: 2026년 입찰 상한 {self.kwh(f.market.cfd_price)}을 2027년 계약시장 가격 대리값으로 → 대출 {self.pct(f.base['cfd'].gearing, 0)}, IRR {self.pct(irr['cfd'])}",
                            f"KEPCO: the 2026 auction cap {self.kwh(f.market.cfd_price)} as a proxy for the 2027 contract market → gearing {self.pct(f.base['cfd'].gearing, 0)}, IRR {self.pct(irr['cfd'])}"),
                     self.T(f"시장 판매: SMP {self.kwh(f.market.smp0, 1)}(최근 12개월 육지 평균), 2027년 이후 신규 사업자는 REC 없음 → {self.pct(irr['merchant'])}",
                            f"Merchant: SMP {self.kwh(f.market.smp0, 1)} (12-month mainland average), no RECs for post-2027 entrants → {self.pct(irr['merchant'])}"),
                     self.T(f"IRR 수준은 사업비(LCOE 역산, 저자 판단)에 민감 — 2022년 실제 설치비면 한전 계약 IRR {self.pct(f.lcoe_check['actual_irr']['cfd'])}. 경로 간 가격 차이는 거의 그대로",
                            f"IRR levels depend on CAPEX (backed out of LCOE, judgement) — at 2022 actual cost KEPCO IRR is {self.pct(f.lcoe_check['actual_irr']['cfd'])}; the price gap between routes barely moves")])
        b2 = BigBox(f"+{lo['premium']:.0f}~{hi['premium']:.0f}" + self.T("원", ""),
                    self.T(f"필요 PPA 프리미엄 (연 해지 {self.pct(self.mc_h, 0)}, PPA 할인율 +{sp[0] * 100:.0f}~{sp[-1] * 100:.0f}%p, kWh당)", f"Required PPA premium ({self.pct(self.mc_h, 0)} termination, PPA discount +{sp[0] * 100:.0f}–{sp[-1] * 100:.0f}pp, per kWh)"),
                    self.T(f"한전 계약 대신 PPA를 받아들일 가격: {self.kwh(lo['price'])}~{self.kwh(hi['price'])}",
                           f"Price to accept a PPA instead of KEPCO: {self.kwh(lo['price'])}–{self.kwh(hi['price'])}"),
                    [self.T("기준(NPV): 지분 NPV 기대값이 한전 계약과 같아지는 PPA 가격 — PPA 쪽은 요구수익률에 위험 스프레드 0~2%p를 더해 할인, 해지 후엔 SMP 판매",
                            "Rule (NPV): PPA price at which expected equity NPV equals KEPCO's — PPA flows discounted at the hurdle plus a 0–2pp risk spread; SMP after termination"),
                     self.T(f"결과를 움직이는 저자 판단: PPA 대출 비율 65%면 +{g[0.65]:.0f}원, 80%면 +{g[0.8]:.0f}원 (스프레드 0)",
                            f"Judgement that moves it: PPA gearing 65% → +{g[0.65]:.0f}, 80% → +{g[0.8]:.0f} (spread 0)"),
                     self.T("해지 확률·스프레드는 공개 근거가 없어 격자로 제시 — 실제 딜에선 오프테이커 신용평가로 정한다",
                            "Termination rate and spread have no public basis, so grids are shown; a deal sets them from the offtaker's credit")])
        cap, kpx = self.room_cap(), f.V("kpx_ancillary")
        low_s = self.below_cfd()
        b3 = BigBox(self.room_rng(hi["max_fee"], lo["max_fee"], 0),
                    self.T(f"데이터센터의 망이용료·부대비용 여유 (태양광 시간대 회피 요금 + 기반기금 {cap:,.1f}원 기준, kWh당)", f"Buyer's room for network and other charges (solar-hour saving + fund levy {cap:,.1f}, per kWh)"),
                    self.T(f"회피 요금 {cap:,.1f}원 − 필요 PPA 가격 = 여유 {self.room_rng(hi['max_fee'], lo['max_fee'])}"
                           + (" — 망이용료 0원이어도 구매자 손해" if self.no_room() else f" < 공개 사례 부대비용 약 {self.net_ex():.0f}원(B)"),
                           f"Saving {cap:,.1f} − required PPA = room {self.room_rng(hi['max_fee'], lo['max_fee'])}"
                           + (" — the buyer loses even with zero network charges" if self.no_room() else f" < ~{self.net_ex():.0f} of charges in a public example")),
                    [self.T(f"구매자 상한 {len(self.tc['stages'])}단: {self.stage_text()} — PPA 가격 상한은 {f.corridor[1]:,.1f}원(기반기금은 PPA 대금에도 붙어 상쇄), 망이용료 여유는 기반기금 포함 기준. 기본요금은 PPA로 못 줄인다. 평균 판매단가 {self.avg():,.1f}원 기준이었다면 여유 {self.room_rng(hi['max_fee_avg'], lo['max_fee_avg'], 0)}",
                            f"Buyer ceiling in {len(self.tc['stages'])} stages: {self.stage_text()} — the PPA price ceiling is {f.corridor[1]:,.1f} (the levy also hits the PPA payment and cancels); room is measured with the levy. Demand charges are not avoided. On the {self.avg():,.1f} average tariff the room would be {self.room_rng(hi['max_fee_avg'], lo['max_fee_avg'], 0)}"),
                     self.T(f"계절이 갈린다: " + " · ".join(f"{self.season_name(k, True)} {self.season(k):,.1f}원" for k in ("spring_autumn", "summer", "winter"))
                            + (f" — {'·'.join(self.season_name(k, True) for k in low_s)}은 한전 계약가 {f.corridor[0]:,.1f}원보다 낮다" if low_s else ""),
                            "Seasons split: " + " · ".join(f"{self.season_name(k, True)} {self.season(k):,.1f}" for k in ("spring_autumn", "summer", "winter"))
                            + (f" — {', '.join(self.season_name(k, True) for k in low_s)} below the KEPCO price {f.corridor[0]:,.1f}" if low_s else "")),
                     self.T(f"성립 조건: 구매자가 RE100 가치로 kWh당 더 낼 금액 = 필요 가격 + 부대비용 − 회피 요금 → 부가정산금 {kpx:.2f}원만 쳐도 {self.wtp_need(lo, kpx, False):,.0f}~{self.wtp_need(hi, kpx, False):,.0f}원, 공개 사례 {self.net_ex():.0f}원이면 {self.wtp_need(lo, self.net_ex()):,.0f}~{self.wtp_need(hi, self.net_ex()):,.0f}원",
                            f"To close, the buyer must pay extra (RE100 value) = required + charges − saving → {self.wtp_need(lo, kpx, False):,.0f}–{self.wtp_need(hi, kpx, False):,.0f} with the {kpx:.2f} KPX settlement alone, {self.wtp_need(lo, self.net_ex()):,.0f}–{self.wtp_need(hi, self.net_ex()):,.0f} at the {self.net_ex():.0f} example")])
        return [b1, b2, b3]

    def irr_close(self) -> bool:
        """직접 PPA와 한전 CfD 지분 IRR 차이가 0.1%p 미만 → 소수 둘째 자리로 표기하고 '같은 수준'으로 쓴다."""
        a, b = self.irr["ppa"], self.irr["cfd"]
        return a is not None and b is not None and abs(a - b) < 0.001

    def ip(self, k: str) -> str:
        """경로 IRR 표기 (PPA·CfD가 가까우면 소수 둘째 자리)."""
        return self.pct(self.irr[k], 2 if self.irr_close() and k in ("ppa", "cfd") else 1)

    def irr_order(self) -> list[str]:
        return sorted(("cfd", "ppa", "merchant"), key=lambda k: self.irr[k] if self.irr[k] is not None else -9)

    def executive(self) -> Page:
        f, irr = self.f, self.irr
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        p1 = self.prem(self.mc_h)
        lo, hi = self.prem_rng()
        add(self.T("가상 태양광 · 사업비 (LCOE 역산, 저자 판단)", "Hypothetical solar · CAPEX (backed out of LCOE, judgement)"),
            f"{f.asset.mw:,.0f}MW · {self.eok(f.asset.capex)}", "1")
        add(self.T("1년차 발전량 · 데이터센터 사용량 대비", "Yr-1 output · share of data-centre use"), f"{self.gwh(f.dc['solar_gwh'])} · {self.pct(f.dc['share'], 0)}", "1")
        add(self.T("가격 회랑: 한전 계약가 ~ 태양광 시간대 회피 요금", "Corridor: KEPCO contract ~ solar-hour saving"),
            f"{f.corridor[0]:,.1f} ~ {f.corridor[1]:,.1f}" + self.T("원", ""), "3", True)
        add(self.T("구매자 상한: 에너지 / +연료비조정 / +기후환경 / +기반기금", "Ceiling: energy / +fuel adj. / +climate / +fund levy"),
            " / ".join(f"{v:,.1f}" if v is not None else "TODO" for _, v in self.tc["stages"]), "3")
        add(self.T("회피 요금 · 봄가을 / 여름 / 겨울", "Saving · spring-autumn / summer / winter"),
            " / ".join(f"{self.season(k):,.1f}" for k in ("spring_autumn", "summer", "winter")) + self.T("원", ""), "5")
        add(self.T("지분 IRR · 한전 CfD / 직접 PPA(중간) / 시장", "Equity IRR · CfD / PPA (mid) / merchant"),
            " / ".join(self.ip(k) for k in ("cfd", "ppa", "merchant")), "4", True)
        add(self.T("대출 비율 · 한전 CfD / 직접 PPA / 시장", "Gearing · CfD / PPA / merchant"), " / ".join(self.pct(f.base[k].gearing, 0) for k in ("cfd", "ppa", "merchant")), "4")
        add(self.T(f"필요 PPA 프리미엄 (연 해지 {self.pct(self.mc_h, 0)}, 스프레드 0~2%p, NPV 기준)", f"Required PPA premium ({self.pct(self.mc_h, 0)} term., 0–2pp spread, NPV)"),
            f"+{lo['premium']:,.1f} ~ +{hi['premium']:,.1f}" + self.T("원", ""), "5", True)
        add(self.T("데이터센터 망이용료 여유 (회피 요금 + 기반기금 기준)", "Buyer's room for network charges (saving + fund levy)"), self.room_rng(hi["max_fee"], lo["max_fee"]), "5", True)
        add(self.T("공개 사례 부대비용 (한전 중개 제3자 PPA, 태양광 Case 1, B)", "Public example of charges (KEPCO-brokered 3rd-party PPA, solar Case 1, B)"), self.T(f"약 {self.net_ex():.0f}원", f"~KRW {self.net_ex():.0f}"), "3", True)
        if ok(f.mc):
            s = mc_stats(f.mc["ppa"], self.hurdle)
            add(self.T(f"몬테카를로 · 직접 PPA 지분 IRR P5 / P50", "Monte Carlo · PPA equity IRR P5 / P50"), f"{self.pct(s['p5'])} / {self.pct(s['p50'])}", "7")
            sm = mc_stats(f.mc["merchant"], self.hurdle)
            add(self.T("몬테카를로 · 시장 판매 손실 확률(IRR < 0)", "Monte Carlo · merchant loss probability (IRR < 0)"), self.pct(sm["neg"], 0), "7")
        table = TableSpec([self.T("핵심 지표", "Key metric"), self.T("값", "Value"), self.T("쪽", "p.")], rows, [0.58, 0.33, 0.09], ["L", "R", "C"],
                          shade_rows=shade, gold_cells=gold, font_size=8.2, single_line_cols={1})
        left = Cell(title=self.T("핵심 지표", "Key metrics"), src=["mcee", "kepco", "keei", "sfoc", "ksj"], table=table,
                    note=self.T("KSJ Research 계산. 발전자산·오프테이커는 가상 사례. 가격 단위 원/kWh, 금액 억원. 신뢰 등급과 잠정 입력은 A2~A4",
                                "KSJ Research. Asset and offtaker are hypothetical. Prices KRW/kWh, amounts KRW 100mn. Source grades and provisional inputs in A2–A4"))
        sub = self.T("가격 근거(공식 원문 우선) → 판매 경로 3개의 현금흐름·대출 → 손익분기(가격·해지 확률·망이용료) → 몬테카를로 → IC 메모",
                     "Price evidence (official first) → cash flows and debt for three routes → break-evens (price, termination, network charges) → Monte Carlo → IC memo")
        return Page("exec", label="i", title=self.headline(), subtitle=sub, cells=[left], boxes=self.boxes())

    def toc_page(self) -> Page:
        heads = [self.p1(), self.p2(), self.p3(), self.p4(), self.p5(), self.p6(), self.p7(), self.p8()]
        names = [self.T("출발점", "Starting point"), self.T("제도", "Rules"), self.T("가격 회랑", "Price corridor"), self.T("지분 IRR", "Equity IRR"),
                 self.T("PPA 협상", "PPA negotiation"), self.T("오프테이커", "Offtaker"), self.T("몬테카를로", "Monte Carlo"), self.T("시사점", "Implications")]
        toc = [(n, nm, toc_line(h.title), h.label) for n, nm, h in zip(["I", "II", "III", "IV", "V", "VI", "VII", "VIII"], names, heads)]
        toc.append(("App.", "Appendix", self.T("A1 IC 메모 · A2~A3 입력과 신뢰 등급 · A4 데이터 노트·방법 · A5 용어",
                                               "A1 IC memo · A2–A3 Inputs and source grades · A4 Data notes, method · A5 Glossary"), "A1–A5"))
        return Page("toc", label="ii", title=self.T("목차", "Contents"),
                    subtitle=self.T("출발점 → 제도 → 가격 → 수익률 → 협상 → 상대방 → 불확실성 → 시사점: 각 장의 결론",
                                    "Start → rules → prices → returns → negotiation → counterparty → uncertainty → implications: each section's conclusion"),
                    toc=toc)

    # --- p1 ------------------------------------------------------------------
    def p1(self) -> Page:
        f, c, dc = self.f, self.c, self.f.dc
        c1 = Cell(title=self.T(f"데이터센터 연 {self.gwh(dc['consumption_gwh'])} vs 태양광 {self.gwh(dc['solar_gwh'])} — {self.pct(dc['share'], 0)}를 직접 공급",
                               f"Data centre {self.gwh(dc['consumption_gwh'])} a year vs solar {self.gwh(dc['solar_gwh'])} — {self.pct(dc['share'], 0)} supplied directly"),
                  src=["vol2", "ksj"], unit="GWh",
                  chart_key="demand", chart=charts.hbars([self.T("데이터센터 연간 사용량", "Data-centre annual use"), self.T(f"태양광 {f.asset.mw:,.0f}MW 1년차 발전량", f"Solar {f.asset.mw:,.0f} MW yr-1 output")],
                                                         [dc["consumption_gwh"], dc["solar_gwh"]], [c["brown_dark"], c["gold"]], c, lambda v: f"{v:,.1f}"),
                  note=self.T(f"Vol.2 한국 케이스(IT 40MW) 기준. 태양광 용량 {f.asset.mw:,.0f}MW = 최대 출력이 데이터센터 평균 부하 {f.dc['consumption_gwh'] * 1000 / 8760:,.1f}MW를 넘지 않는 규모 → 발전량 전부를 데이터센터가 쓴다. 밤과 부족분은 한전에서 산다" + self.prov_note(["capacity_factor"]),
                              f"Vol.2 Korean case (IT 40 MW). {f.asset.mw:,.0f} MW of solar = peak output within the data centre's {f.dc['consumption_gwh'] * 1000 / 8760:,.1f} MW average load, so all output is consumed; nights and gaps come from KEPCO" + self.prov_note(["capacity_factor"])))
        rows = [[self.T("데이터센터 IT 용량 × 부하율 × PUE", "IT capacity × load × PUE"), f"{f.V('dc_it_mw'):.0f}MW × {self.pct(f.V('dc_it_load'), 0)} × {f.V('dc_pue'):.1f}"],
                [self.T("× 8,760시간 = 연간 사용량", "× 8,760 h = annual use"), self.gwh(dc["consumption_gwh"])],
                [self.T("× 한전 산업용 평균 판매단가(2025)", "× KEPCO industrial average tariff (2025)"), self.kwh(self.avg())],
                [self.T("= 연간 전력비", "= Annual power bill"), self.eok(dc["power_cost"])],
                [self.T("태양광 용량 × 이용률 × 8,760시간", "Solar MW × capacity factor × 8,760 h"), f"{f.asset.mw:.0f}MW × {self.pct(f.asset.capacity_factor, 0)}"],
                [self.T("= 1년차 발전량 (열화 연 0.5%)", "= Yr-1 output (0.5% annual degradation)"), self.gwh(dc["solar_gwh"])]]
        c2 = Cell(title=self.T(f"전력비 연 {self.eok(dc['power_cost'])}: Vol.2에서 임차인에게 별도 청구한 그 비용", f"Power bill {self.eok(dc['power_cost'])} a year — the cost Vol.2 passed to tenants"),
                  src=["vol2", "kepco", "nrel", "ksj"],
                  table=TableSpec([self.T("계산", "Step"), self.T("값", "Value")], rows, [0.62, 0.38], ["L", "R"], shade_rows={3, 5}, gold_cells={(3, 1), (5, 1)}, font_size=8.4),
                  note=self.T(f"연간 전력비 추정용 = 기본요금 포함 평균 판매단가. PPA로 아끼는 단가는 이보다 낮다 — 태양광 시간대 회피 요금({self.cap_basis()}) {self.kwh(f.corridor[1])}(p3·p5)" + self.prov_note(["capacity_factor"]),
                              f"For the annual bill = average tariff incl. demand charges. A PPA saves less — the solar-hour saving ({self.cap_basis()}), {self.kwh(f.corridor[1])} (p3, p5)" + self.prov_note(["capacity_factor"])))
        c3 = Cell(title=self.T("질문: 같은 전기를 한전 대신 데이터센터에 팔면, 더 받는 값이 위험을 보상하나", "Question: if the plant sells to the data centre instead of KEPCO, does the extra price pay for the risk?"),
                  src=["vol2", "ksj"], panel_lead=self.T("지분 투자자의 세 갈래", "An equity investor's three routes"),
                  bullets=[self.T("① 한전 계약(CfD): 2027년부터 신규 태양광의 표준. 20년 고정가, 상대방은 한전", "① KEPCO contract (CfD): standard for new solar from 2027; 20-yr fixed price, KEPCO as counterparty"),
                           self.T("② 데이터센터 직접 PPA: 협상 가격, 상대방은 Vol.2의 데이터센터 SPV", "② Direct PPA: negotiated price; counterparty is Vol.2's data-centre SPV"),
                           self.T("③ 시장 판매(SMP): 가격 변동을 그대로 진다. 신규 사업자는 REC 없음", "③ Merchant (SMP): full price risk; no RECs for new entrants"),
                           self.T("Vol.2는 대주(돈 빌려주는 쪽), Vol.3는 ECM(공모가)의 눈 — 이번 편은 지분 투자자의 눈", "Vol.2 took the lender's view, Vol.3 the ECM view — this note takes the equity investor's")])
        steps = [(self.T("1. 가격 근거", "1. Price evidence"), [self.T("한전 계약가", "KEPCO price"), self.T("시간대별 요금", "Time-of-use tariff"), "SMP · LCOE", self.T("신뢰 등급", "Source grade")]),
                 (self.T("2. 현금흐름", "2. Cash flows"), [self.T("경로 3개", "3 routes"), self.T("법인세·감가", "Tax, depreciation"), self.T("DSCR sculpting", "DSCR sculpting"), self.T("지분 IRR·MOIC", "Equity IRR, MOIC")]),
                 (self.T("3. 손익분기", "3. Break-evens"), [self.T("PPA 가격", "PPA price"), self.T("해지 확률", "Termination rate"), self.T("망이용료 상한", "Network-charge cap"), self.T("해지 시점", "Termination year")]),
                 (self.T("4. 검증·IC", "4. Checks, IC"), [self.T("몬테카를로", "Monte Carlo"), self.T("민감도", "Sensitivity"), self.T("IC 메모", "IC memo"), self.T("국문·영문", "Korean & English")])]
        c4 = Cell(title=self.T("분석 구조: 가격 근거 → 현금흐름 → 손익분기 → 검증·IC 메모", "Structure: prices → cash flows → break-evens → checks and IC memo"), src=["ksj"],
                  chart_key="flow", chart=charts.flow4(steps, c))
        return Page("body", "1", self.T(f"출발점: 데이터센터 40MW의 전력비 연 {self.eok(dc['power_cost'])} — 부하를 넘지 않는 태양광 {f.asset.mw:,.0f}MW가 그 {self.pct(dc['share'], 0)}를 댄다",
                                        f"Starting point: a 40 MW data centre's power bill is {self.eok(dc['power_cost'])} a year — {f.asset.mw:,.0f} MW of solar sized within its load covers {self.pct(dc['share'], 0)}"),
                    self.T("Vol.2 데이터센터(대주의 눈) → Vol.4 그 데이터센터에 전기를 파는 발전자산(지분 투자자의 눈)",
                           "Vol.2 data centre (lender's view) → Vol.4 the plant that sells it power (equity investor's view)"), [c1, c2, c3, c4])

    # --- p2 ------------------------------------------------------------------
    def p2(self) -> Page:
        f = self.f
        G = TIER_KR if self.kr else TIER_EN
        tl = [
            ["2026-02-03", self.T("분산에너지특화지역 추진단: 산단 구역전기 이용 기업도 재생에너지 PPA 허용 방침, 구역전기 35MW 한도 완화 검토", "Distributed-energy zones: firms on local grids to be allowed renewable PPAs; 35 MW cap under review"), G["B"]],
            ["2026-05-07", self.T("AI 데이터센터 특별법 본회의 통과 — 업계가 요청한 LNG 발전 직접 PPA 특례는 제외", "AI Data Centre Act passed — the requested LNG direct-PPA carve-out was dropped"), G["B"]],
            ["2026-05", self.T("분산에너지 설비 원칙상 40MW 이하 — 대형 데이터센터 직접 공급 특례안은 국회 계류(기후부 부정적 입장, 보도)", "Distributed resources capped at 40 MW in principle; a data-centre carve-out bill is pending (ministry reported opposed)"), G["B"]],
            ["2026-07-16", self.T(f"2026년 1차 태양광 경쟁입찰 공고: 상한 {self.kwh(f.market.cfd_price, 3)}(전년 대비 약 5% 하향), 약 1,000MW", f"2026 round-1 solar auction: cap {self.kwh(f.market.cfd_price, 3)} (about 5% lower), ~1,000 MW"), G["A"]],
            ["2026-09-15", self.T("재생에너지법 개정 공포(법률 제21943호) — 장기 고정가격계약 등 계약시장제도 신설(제12조의14). 한전과의 계약 일원화는 보도 기준", "Renewable Energy Act amended (Act No. 21943) — a contract market incl. long-term fixed-price contracts (art. 12-14); a single KEPCO channel is per press reports"), G["A"]],
            ["2027-01-01", self.T(f"시행 — REC 조항(제12조의7) {self.rec_end()}-12-31까지 효력, 발급기한 2026-12-31 · 기존 발급자·시행 전 허가자 중 고시 인정자는 종전 규정 유지(부칙 제2·3조)",
                                  f"Effective — REC article (12-7) in force to 31 Dec {self.rec_end()}, issuance deadline 31 Dec 2026 · existing holders and pre-act licensees recognised by notice keep the former rules (addendum arts. 2–3)"), G["A"]],
        ]
        c1 = Cell(title=self.T("제도 타임라인: 2027년부터 한전 장기계약이 기본값, 직접 PPA는 선택지", "Timeline: from 2027 a KEPCO long-term contract is the default, a direct PPA the alternative"),
                  src=["mcee", "react", "reform", "dist"],
                  table=TableSpec([self.T("날짜", "Date"), self.T("내용", "Change"), self.T("신뢰 등급", "Grade")], tl, [0.12, 0.72, 0.16], ["C", "L", "C"],
                                  gold_cells={(3, 2), (4, 2), (5, 2)}, shade_rows={3, 4, 5}, font_size=8.0),
                  note=self.T("신뢰 등급: 공식 원문 = 정부 보도자료 원문 확인 · 보도·외부 보고서 = 정부 발표를 인용한 언론 보도(정부 원문 미대조) — 날짜·내용은 보도 기준",
                              "Grades: official = government release checked · press/outside report = media citing a government release (original not yet matched) — dates and content as reported"))
        d = f.debts
        rows = [[self.T("가격", "Price"), self.T(f"입찰가 20년 고정 (상한 {f.market.cfd_price:,.1f})", f"Auction price fixed 20 yrs (cap {f.market.cfd_price:,.1f})"),
                 self.T("한전 계약가 ~ 구매자 회피 요금 사이 협상", "Negotiated between KEPCO price and buyer's saving"), self.T("SMP 변동 (REC 없음)", "SMP (no RECs)")],
                [self.T("상대방", "Counterparty"), self.T("한전", "KEPCO"), self.T("데이터센터 SPV (Vol.2)", "Data-centre SPV (Vol.2)"), self.T("시장", "Market")],
                [self.T("계약 기간", "Term"), self.T(f"{f.market.cfd_term}년", f"{f.market.cfd_term} yrs"), self.T(f"{f.market.ppa_term}년 (해외 원전 PPA 사례)", f"{f.market.ppa_term} yrs (U.S. nuclear PPA precedents)"), "—"],
                [self.T("목표 DSCR · 최대 대출 비율", "Target DSCR · max gearing"), f"{d['cfd'].dscr:.2f} · {self.pct(d['cfd'].gearing, 0)}", f"{d['ppa'].dscr:.2f} · {self.pct(d['ppa'].gearing, 0)}",
                 f"{d['merchant'].dscr:.2f} · {self.pct(d['merchant'].gearing, 0)}"],
                [self.T("대출 만기", "Tenor"), self.T(f"{d['cfd'].tenor}년", f"{d['cfd'].tenor} yrs"), self.T(f"{d['ppa'].tenor}년", f"{d['ppa'].tenor} yrs"), self.T(f"{d['merchant'].tenor}년", f"{d['merchant'].tenor} yrs")],
                [self.T("지분 투자자가 지는 위험", "Equity risk"), self.T("수익 상단이 막힘 · 입찰 탈락", "Capped upside · losing the auction"),
                 self.T("오프테이커 신용 · 망이용료 · 해지", "Offtaker credit · network charges · termination"), self.T("가격 변동 전부", "All price risk")]]
        c2 = Cell(title=self.T("판매 경로 3개: 가격 · 상대방 · 대출 조건이 함께 바뀐다", "Three routes: price, counterparty and debt terms move together"), src=["mcee", "reform", "ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.route("cfd"), self.route("ppa"), self.route("merchant")], rows, [0.19, 0.27, 0.30, 0.24], ["L", "C", "C", "C"],
                                  shade_rows={3}, font_size=8.0),
                  note=self.T("대출 조건은 저자 판단(공개 약정 근거 없음) — 상대방 신용이 낮을수록 DSCR을 높이고 대출 비율을 낮춘다는 관행만 반영. 이자율 = 국고채 3년 "
                              f"{self.pct(f.ktb, 2)}({f.ktb_date}) + {f.V('margin_bp'):.0f}bp",
                              "Debt terms are author judgments (no public term sheets): weaker counterparty → higher DSCR, lower gearing. Rate = KTB 3-yr "
                              f"{self.pct(f.ktb, 2)} ({f.ktb_date}) + {f.V('margin_bp'):.0f}bp"))
        return Page("body", "2", self.T("제도: 2027년부터 신규 태양광은 한전 20년 계약이 기본 — 직접 PPA는 대안, 시장 판매엔 REC가 없다",
                                        "Rules: from 2027 new solar defaults to a 20-yr KEPCO contract — a PPA is the alternative, merchant sales get no RECs"),
                    self.T("계약시장 신설 · REC 조항 시한 · 분산에너지 한도 · AI 데이터센터 특별법 → 지분 투자자의 선택지 3개", "Contract market · REC sunset · distributed-energy cap · AI data-centre act → three routes"),
                    [c1, c2], grid="2x1")

    # --- p3 ------------------------------------------------------------------
    def p3(self) -> Page:
        f, c = self.f, self.c
        p1 = self.prem(self.mc_h)
        lo, hi = f.corridor
        lc = f.inputs["lcoe_target"]
        pts = [(self.T("시장 SMP (최근 12개월)", "Merchant SMP (12 months)"), f.market.smp0, c["warm_grey"]),
               (self.T(f"회피 요금 + 기반기금 − 공개 사례 {self.net_ex():.0f}", f"Saving + levy − public example {self.net_ex():.0f}"), self.room_cap() - self.net_ex(), c["charcoal"]),
               (self.T("한전 계약가 (입찰 상한)", "KEPCO contract (cap)"), lo, c["brown_dark"]),
               (self.T("PPA 회랑 중간", "Corridor mid"), f.ppa_mid, c["brown_mid"]),
               (self.T("태양광 시간대 에너지요금만", "Solar-hour energy rate only"), self.stage_val("energy"), c["warm_grey"]),
               (self.T(f"구매자 상한: {self.cap_basis()}", f"Ceiling: {self.cap_basis()}".replace(" adjustment", " adj.").replace(" charge", "")), hi, c["brick"]),
               (self.T(f"필요 PPA (연 해지 {self.pct(self.mc_h, 0)})", f"Required PPA ({self.pct(self.mc_h, 0)} term.)"), p1["price"], c["gold"]),
               (self.T("참고: 산업용 평균 판매단가", "Ref.: industrial average tariff"), self.avg(), c["warm_grey"])]
        if self.no_room():
            t1 = self.T(f"가격 회랑 {lo:,.1f}~{hi:,.1f}원(폭 {hi - lo:,.1f}원) — 필요 PPA 가격 {p1['price']:,.1f}원이 구매자 상한보다 높아 부대비용 전에 회랑이 닫혀 있다",
                        f"Corridor {lo:,.1f}–{hi:,.1f} (width {hi - lo:,.1f}) — the required PPA price {p1['price']:,.1f} already exceeds the buyer's ceiling, before any charges")
        else:
            t1 = self.T(f"가격 회랑 {lo:,.1f}~{hi:,.1f}원 — 공개 사례 부대비용 약 {self.net_ex():.0f}원을 빼면 구매자 실효 상한 {self.room_cap() - self.net_ex():,.1f}원(기반기금 포함 기준)으로 회랑이 닫힌다",
                        f"Corridor {lo:,.1f}–{hi:,.1f} — net of ~{self.net_ex():.0f} in public-example charges the buyer's ceiling falls to {self.room_cap() - self.net_ex():,.1f} (levy-matched) and the corridor closes")
        c1 = Cell(title=t1,
                  src=["mcee", "tou", "solar", "kepco", "kepco_fuel", "keei", "smp", "sfoc", "notice", "decree", "ksj"], unit=self.T("원/kWh", "KRW/kWh"),
                  legend=[(c["warm_grey_light"], self.T(f"태양광 LCOE {lc.low:.0f}~{lc.high:.0f}", f"Solar LCOE {lc.low:.0f}–{lc.high:.0f}"))],
                  chart_key="corridor",
                  chart=charts.corridor(pts, [("LCOE", lc.low, lc.high, c["warm_grey_light"], 0.45)], c, lambda v: f"{v:,.1f}", (80, 200),
                                        gap=None),
                  note=self.T(f"한전 계약가 = 2026년 1차 입찰 상한(2027년 계약시장 가격 대리값). 구매자 상한 = {self.stage_text()} — 에너지요금은 산업용(을) {self.contract()} 개편 후 전력량요금을 태양광 발전 시간에 맞춰 2025년 월별 발전량으로 가중(기본요금 제외, 하루 발전 형상은 저자 판단), 연료비조정은 2026년 4분기 단가(보도, B), {self.climate_text()}. 평균 판매단가는 참고선. LCOE = 2024년 국내 범위. " + self.fuel_cap_text() + self.net_basis_note(items_shown=False)
                              + self.prov_note(["solar_shape_p", "tou_saturday", "fuel_adj", "climate_env"]),
                              f"KEPCO price = 2026 round-1 cap (proxy for 2027). Buyer ceiling = {self.stage_text()} — energy = post-reform industrial (B) {self.contract()} rates in solar hours, weighted by 2025 monthly output (no demand charge; daily shape is a judgement); fuel adjustment = Q4 2026 rate (press report, B); {self.climate_text()}. Average tariff = reference only. LCOE = 2024 Korean range. " + self.fuel_cap_text() + self.net_basis_note(items_shown=False)
                              + self.prov_note(["solar_shape_p", "tou_saturday", "fuel_adj", "climate_env"])))
        G = TIER_KR if self.kr else TIER_EN
        I = f.inputs
        rows = []
        pk = ("cfd_price", "kepco_industrial_price", "lcoe_target", "smp_base", "kpx_ancillary", "net_charge_example")
        gold_, brick_ = set(), set()
        tiers = []
        for i, k in enumerate(pk):
            x = I[k]
            val = f"{float(x.value):,.1f}" + (f" ({x.low:,.0f}~{x.high:,.0f})" if x.low is not None and x.high is not None else "")
            rows.append([self.lab(k), val, G[x.tier], x.published or "—"])
            tiers.append(x.tier)
            (gold_ if x.tier in ("A", "D") else brick_ if x.tier == "C" else set()).add((i, 2))
            if k == "kepco_industrial_price":       # 구매자 상한(계산값)은 평균 단가 바로 위에
                shp, ad = self.tc["shape"], float(self.tc["adder"])
                rows.insert(i, [self.T(f"구매자 상한: 회피 요금({self.contract()}, {self.cap_basis()})", f"Buyer ceiling: saving ({self.contract()}, {self.cap_basis()})"),
                                f"{hi:,.1f} ({min(shp.values()) + ad:,.1f}~{max(shp.values()) + ad:,.1f})", G["J"], I["tou_tariff"].published])
                tiers.insert(i, "J")
                for j, kk in enumerate(("fuel_adj", "climate_env"), start=1):
                    xx = I[kk]
                    vv = f"{float(xx.value):,.1f}" if isinstance(xx.value, (int, float)) else self.T("TODO(원문 대기)", "TODO (pending)")
                    rows.insert(i + j, [self.lab(kk), vv, G[xx.tier] + ("" if isinstance(xx.value, (int, float)) else self.T(" 예정", " (pending)")), xx.published or "—"])
                    tiers.insert(i + j, xx.tier if isinstance(xx.value, (int, float)) else "pending")
        gold_ = {(r, 2) for r, t in enumerate(tiers) if t in ("A", "D")}
        brick_ = {(r, 2) for r, t in enumerate(tiers) if t == "C"}
        na, nj, nb, npd = (sum(t in ("A", "D") for t in tiers), sum(t == "J" for t in tiers), sum(t in ("B", "C") for t in tiers),
                           sum(t == "pending" for t in tiers))
        c2 = Cell(title=self.T(f"가격 근거와 신뢰 등급: {len(tiers)}개 중 공식 원문·공식 자료 {na} · 저자 판단 {nj} · 보도·외부 보고서 {nb}" + (f" · 원문 대기 {npd}" if npd else ""),
                               f"Price evidence: {len(tiers)} items — official {na} · judgement {nj} · press/outside report {nb}" + (f" · pending {npd}" if npd else "")),
                  src=["mcee", "tou", "kepco", "keei", "smp", "kpx", "sfoc"],
                  table=TableSpec([self.T("항목 (원/kWh)", "Item (KRW/kWh)"), self.T("값 (범위)", "Value (range)"), self.T("신뢰 등급", "Grade"), self.T("발표", "Published")],
                                  rows, [0.44, 0.20, 0.20, 0.16], ["L", "R", "C", "C"], gold_cells=gold_, brick_cells=brick_, font_size=8.0),
                  note=self.T(f"회피 요금 = 공식 요금표(2026-03-13)·2025년 월별 발전량(공식)에 저자 판단 하루 형상 적용(괄호 = 형상 민감도) + 연료비조정요금(보도) + " + self.climate_text() + " · 평균 판매단가 = 2025년 산업용 판매수입 ÷ 판매전력량(참고) · SMP = 2025-09~2026-08 월별 육지 가중평균의 평균(시간별 10~16시 평균으로 교차 확인)",
                              "Saving = official tariff (13 Mar 2026) and 2025 monthly output (official) with a judgement daily shape (range = shape sensitivity) · Average tariff = 2025 industrial revenue ÷ volume (reference) · SMP = mean of monthly mainland SMP, Sep 2025–Aug 2026 (cross-checked with 10:00–16:00 hourly)"))
        fx = self.fx()
        us = f.us
        rows_us = [[self.T("Talen–AWS 원전 PPA (17년, 1,920MW)", "Talen–AWS nuclear PPA (17 yrs, 1,920 MW)"), f"≥ {us['talen_floor']:,.0f}", G["A"]],
                   [self.T("LevelTen 북미 태양광 PPA 평균 (2026 2Q)", "LevelTen N. America solar PPA avg (Q2 2026)"), f"{us['levelten']:,.1f}", G["B"]]]
        if fx:
            rows_us += [[self.T(f"참고: 한국 한전 계약가 (원/달러 {fx[0]:,.1f})", f"Ref.: Korea KEPCO price (USD/KRW {fx[0]:,.1f})"), f"{lo * 1000 / fx[0]:,.0f}", G[I["cfd_price"].tier]],
                        [self.T("참고: 한국 구매자 회피 요금(태양광 시간대)", "Ref.: Korea buyer's solar-hour saving"), f"{hi * 1000 / fx[0]:,.0f}", G["J"]]]
        c3 = Cell(title=self.T(f"미국 비교: 하이퍼스케일러 원전 PPA 최소 ${us['talen_floor']:,.0f}/MWh — 한국 태양광 계약가가 더 비싸다",
                               f"U.S. check: hyperscaler nuclear PPA at least ${us['talen_floor']:,.0f}/MWh — Korean solar contracts cost more"),
                  src=["sec", "levelten", "ecos"],
                  table=TableSpec([self.T("항목", "Item"), "USD/MWh", self.T("신뢰 등급", "Grade")], rows_us, [0.60, 0.18, 0.22], ["L", "R", "C"], gold_cells={(0, 1)}, font_size=8.4),
                  note=self.T("Talen: 명목 매출 약 180억 달러 ÷ (1,920MW × 8,760h × 17년) = 전량·전시간 공급 가정의 평균 단가. 실제는 2032년까지 단계 증가라 단가는 이보다 높다(하한). "
                              "Meta–Constellation 등 다른 원전 PPA는 가격 비공개", "Talen: ~USD 18bn notional ÷ (1,920 MW × 8,760 h × 17 yrs) = average price at full, round-the-clock volume; "
                              "the ramp to 2032 means the true price is higher (floor). Other nuclear PPAs (e.g. Meta–Constellation) are undisclosed"))
        c4 = Cell(title=self.T("읽는 법: 발전사의 하한은 한전 계약, 구매자의 상한은 태양광 시간대 한전 요금", "How to read it: the seller's floor is KEPCO's contract, the buyer's ceiling KEPCO's solar-hour rate"),
                  src=["ksj"], panel_lead=self.T("PPA 가격은 두 대안 사이에서 정해진다", "A PPA price lives between two outside options"),
                  bullets=[self.T(f"발전사: 한전 계약({lo:,.1f}원)보다 위험이 큰 만큼 더 받아야 한다 → 하한 + 위험 프리미엄", f"Seller: needs more than KEPCO ({lo:,.1f}) for extra risk → floor + risk premium"),
                           self.T(f"구매자: PPA 가격 + 부대비용이 태양광 시간대 요금({hi:,.1f}원)보다 싸야 산다 — 기본요금은 그대로 낸다. 공개 사례 {self.net_ex():.0f}원이면 PPA는 {self.room_cap() - self.net_ex():,.1f}원 아래여야(기반기금 포함 기준)",
                                  f"Buyer: PPA + charges must beat the solar-hour rate ({hi:,.1f}); demand charges stay. With the {self.net_ex():.0f} example, the PPA must be below {self.room_cap() - self.net_ex():,.1f} (levy-matched)"),
                           self.T(f"시장 SMP({f.market.smp0:,.1f}원)는 한전 계약가보다 낮다 — 2027년 이후 신규 사업자에게 REC가 없어서", f"Merchant SMP ({f.market.smp0:,.1f}) sits below the KEPCO price — no RECs for post-2027 entrants"),
                           self.T("미국은 원전 24시간 전력이 $63+/MWh — 한국 PPA는 '싼 재생에너지'가 아니라 'RE100용 프리미엄 상품'", "U.S. 24/7 nuclear at $63+/MWh — a Korean PPA is an RE100 premium product, not cheap power")])
        return Page("body", "3", self.T(f"가격 회랑: 한전 계약 {lo:,.1f}원 ~ 태양광 시간대 회피 요금 {hi:,.1f}원 — 평균 판매단가({self.avg():,.1f}원)로 잴 때보다 회랑이 {self.avg() - hi:,.1f}원 좁다",
                                        f"Price corridor: KEPCO {lo:,.1f} to the solar-hour saving {hi:,.1f} — {self.avg() - hi:,.1f} narrower than on the average tariff ({self.avg():,.1f})"),
                    self.T("하한 = 발전사의 대안(한전 계약) · 상한 = 구매자의 대안(태양광 시간대 한전 요금) · 원가 = LCOE · 시장가 = SMP · 미국 비교", "Floor = seller's alternative · ceiling = buyer's alternative (solar-hour rate) · cost = LCOE · merchant = SMP · U.S. check"),
                    [c1, c2, c3, c4])

    def fx(self) -> tuple[float, str] | None:
        import pandas as pd
        from src.data_fetch.base import resolve_path
        p = resolve_path("data/processed/ecos_fx_daily.csv")
        if not p.exists():
            return None
        d = pd.read_csv(p, encoding="utf-8-sig")
        d = d[d["date"] <= self.f.as_of].dropna()
        return (float(d.iloc[-1]["usdkrw"]), str(d.iloc[-1]["date"])) if not d.empty else None

    # --- p4 ------------------------------------------------------------------
    def p4(self) -> Page:
        f, c, irr = self.f, self.c, self.irr
        R = ("cfd", "ppa", "merchant")
        ey = int(f.V("exit_year"))
        top_h = max(R, key=lambda k: irr[k] or -9)
        top_s = max(R, key=lambda k: f.exit[k][0] if f.exit[k][0] is not None else -9)
        lead = (self.T(f"{self.route(top_h, True)}가 두 방식 모두 가장 높다", f"{self.route(top_h, True)} leads either way") if top_h == top_s else
                self.T(f"보유는 {self.route(top_h, True)}, 매각은 {self.route(top_s, True)}가 가장 높다", f"{self.route(top_h, True)} leads on hold, {self.route(top_s, True)} on sale"))
        c1 = Cell(title=self.T(f"지분 IRR: 보유(25년) vs {ey}년 차 매각 — ", f"Equity IRR: hold (25 yrs) vs sale in year {ey} — ") + lead,
                  src=["ksj"], unit="%", legend=[(c["gold"], self.T("보유", "Hold")), (c["brown_mid"], self.T(f"{ey}년 차 매각", f"Sale in yr {ey}"))],
                  chart_key="irr",
                  chart=charts.grouped([self.route(k, True) for k in R],
                                       [(self.T("보유", "Hold"), [irr[k] * 100 for k in R], c["gold"]),
                                        (self.T("매각", "Sale"), [(f.exit[k][0] or math.nan) * 100 for k in R], c["brown_mid"])], c, lambda v: f"{v:.1f}%"),
                  note=self.T(f"직접 PPA = 회랑 중간 {self.kwh(f.ppa_mid)}, 해지 없음. 매각가 = 이후 지분 흐름을 매수자 요구수익률 {self.pct(f.V('buyer_return'), 0)}로 할인"
                              + self.prov_note(["capacity_factor", "lcoe_target", "opex_pct", "smp_base"]),
                              f"PPA at corridor mid {self.kwh(f.ppa_mid)}, no termination. Sale price = later equity flows at the buyer's {self.pct(f.V('buyer_return'), 0)}"
                              + self.prov_note(["capacity_factor", "lcoe_target", "opex_pct", "smp_base"])))
        rows = []
        for k in R:
            r = f.base[k]
            rows.append([self.route(k, True), self.eok(r.debt), self.pct(r.gearing, 0), self.x(r.min_dscr), self.eok(r.equity), self.pct(r.irr), self.x(r.moic)])
        c2 = Cell(title=self.T("대출 sizing: 상대방이 단단할수록 대출이 커지고 지분이 작아진다", "Debt sizing: the stronger the counterparty, the more debt and the less equity"),
                  src=["ecos", "law", "ksj"],
                  table=TableSpec([self.T("경로", "Route"), self.T("대출", "Debt"), self.T("대출 비율", "Gearing"), self.T("최소 DSCR", "Min DSCR"), self.T("지분", "Equity"),
                                   self.T("지분 IRR", "Eq. IRR"), "MOIC"], rows, [0.19, 0.15, 0.12, 0.13, 0.14, 0.14, 0.13], ["L", "R", "R", "R", "R", "R", "R"],
                                  gold_cells={(1, 5)}, brick_cells={(2, 5)}, shade_rows={1}, font_size=8.4),
                  note=self.T(f"사업비 {self.eok(f.asset.capex)}(kW당 {f.asset.capex * 100 / f.asset.mw:,.0f}천원, LCOE·WACC·이용률에서 역산한 저자 판단) · 법인세 누진세율 + 지방세 10% · 정액 감가 {int(f.V('dep_years'))}년 · 대출은 목표 DSCR sculpting과 최대 대출 비율 중 작은 값",
                              f"CAPEX {self.eok(f.asset.capex)} (KRW {f.asset.capex * 100 / f.asset.mw:,.0f}k/kW, backed out of LCOE/WACC/CF — judgement) · progressive corporate tax + 10% local · straight-line {int(f.V('dep_years'))} yrs · debt = min(DSCR sculpting, max gearing)"))
        srows, brick = [], set()
        for i, s in enumerate(f.sens):
            k = s["key"]
            fmt = (lambda v: f"{v * 100:.0f}%") if k in ("capacity_factor", "opex_pct") else (lambda v: f"{v:,.0f}")
            srows.append([f"{self.lab(k)} {fmt(s['lo_v'])}~{fmt(s['hi_v'])}" if self.kr else f"{self.lab(k)} {fmt(s['lo_v'])}–{fmt(s['hi_v'])}"]
                         + [f"{self.pct(s['low'][r], 1)} ~ {self.pct(s['high'][r], 1)}" for r in R])
        c3 = Cell(title=self.T("민감도: 사업비와 이용률이 SMP보다 IRR을 더 흔든다 — 계약 경로의 위험은 원가", "Sensitivity: CAPEX and capacity factor move IRR more than SMP — contracted routes carry cost risk"),
                  src=["keei", "smp", "ksj"],
                  table=TableSpec([self.T("입력 (하단~상단)", "Input (low–high)"), self.route("cfd", True), self.route("ppa", True), self.route("merchant", True)], srows,
                                  [0.34, 0.22, 0.22, 0.22], ["L", "C", "C", "C"], font_size=8.2),
                  note=self.T("한 번에 한 입력만 범위 끝으로 (대출 재sizing). 사업비 하단 = 2022년 실제 설치비, 상단 = LCOE 상단 136원에 맞춘 값 · 이용률 범위는 저자 민감도" + self.prov_note(["capacity_factor", "smp_base", "opex_pct"]),
                              "One input at a time at its range ends (debt re-sized). CAPEX low = 2022 actual cost, high = matched to the 136 LCOE · CF range is an author sensitivity" + self.prov_note(["capacity_factor", "smp_base", "opex_pct"])))
        ppa_lt = (irr["ppa"] or -9) < (irr["cfd"] or -9)
        dpm = f.ppa_mid - f.market.cfd_price
        if self.irr_close():
            t44 = self.T(f"읽는 법: 회랑 중간 가격(한전 계약 +{dpm:,.1f}원)이면 PPA와 한전 계약 IRR이 같은 수준({self.ip('ppa')} vs {self.ip('cfd')}) — 그런데 PPA만 해지 위험을 진다",
                         f"How to read it: at the corridor mid (+{dpm:,.1f} over KEPCO) PPA and KEPCO IRRs are level ({self.ip('ppa')} vs {self.ip('cfd')}) — but only the PPA carries termination risk")
        elif ppa_lt:
            t44 = self.T(f"읽는 법: 회랑 중간 가격(한전 계약 +{dpm:,.1f}원)으로는 PPA가 한전 계약의 대출 효과를 못 넘는다",
                         f"How to read it: at the corridor mid (+{dpm:,.1f} over KEPCO) the PPA cannot beat KEPCO's leverage")
        else:
            t44 = self.T("읽는 법: 한전 계약은 대출로 IRR을 만들고, PPA는 가격으로 만든다", "How to read it: the KEPCO route earns through leverage, the PPA through price")
        c4 = Cell(title=t44,
                  src=["ksj"], panel_lead=self.T("같은 발전소, 다른 자본구조", "Same plant, different capital structures"),
                  bullets=[self.T(f"한전 계약: 가격 {f.market.cfd_price:,.1f}원 vs LCOE {f.V('lcoe_target'):.1f}원, 대출 {self.pct(f.base['cfd'].gearing, 0)}로 지분 IRR {self.pct(irr['cfd'])}", f"KEPCO: price {f.market.cfd_price:,.1f} vs LCOE {f.V('lcoe_target'):.1f}, {self.pct(f.base['cfd'].gearing, 0)} debt → {self.pct(irr['cfd'])}"),
                           self.T(f"직접 PPA: 회랑 중간 {self.kwh(f.ppa_mid)}이면 IRR {self.pct(irr['ppa'])}(해지 없음) — 한전 계약과 같아지려면 {self.kwh(f.be_price)}(p5)",
                                  f"PPA: {self.pct(irr['ppa'])} at the corridor mid {self.kwh(f.ppa_mid)} (no termination) — it needs {self.kwh(f.be_price)} to match KEPCO (p5)"),
                           self.T(f"시장 판매: 대주가 대출을 {self.pct(f.base['merchant'].gearing, 0)}만 해 주고 SMP도 낮아 IRR {self.pct(irr['merchant'])}", f"Merchant: lenders give only {self.pct(f.base['merchant'].gearing, 0)} and SMP is low → {self.pct(irr['merchant'])}"),
                           self.T(f"요구수익률 {self.pct(self.hurdle, 0)} 기준: {self.clear_text()} — 계약 경로끼리는 가격 차이와 해지 위험의 교환", f"Against the {self.pct(self.hurdle, 0)} hurdle: {self.clear_text()} — between contracts it is price vs termination risk")])
        return Page("body", "4", self.T(f"지분 IRR: 직접 PPA {self.ip('ppa')} · 한전 계약 {self.ip('cfd')} · 시장 {self.pct(irr['merchant'])} — 요구수익률 {self.pct(self.hurdle, 0)} 기준 {self.clear_text()}",
                                        f"Equity IRR: PPA {self.ip('ppa')} · KEPCO {self.ip('cfd')} · merchant {self.pct(irr['merchant'])} — against the {self.pct(self.hurdle, 0)} hurdle: {self.clear_text()}"),
                    self.T("경로별 대출 sizing → 지분 IRR·MOIC → 매각 → 민감도", "Debt sizing by route → equity IRR and MOIC → exit → sensitivity"), [c1, c2, c3, c4])

    # --- p5 ------------------------------------------------------------------
    def p5(self) -> Page:
        f, c, irr = self.f, self.c, self.irr
        lo, hi = f.corridor
        sp = self.v["risk_spreads"]
        xs = [p for p, _ in f.price_curve]
        ys = [v for _, v in f.price_curve]
        p0 = self.pg(0.0, 0.0)
        p1 = self.prem(self.mc_h)
        where = (self.T(f"구매자 상한 {hi:,.1f}원보다 높다", f"above the buyer's {hi:,.1f} ceiling") if f.be_price > hi else
                 self.T("회랑 하단 근처", "near the corridor floor") if f.be_price - lo < (hi - lo) / 3 else self.T("회랑 안", "inside the corridor"))
        c1 = Cell(title=self.T(f"PPA 가격별 지분 IRR: {f.be_price:,.1f}원에서 한전 계약 IRR과 같다 — {where}",
                               f"Equity IRR by PPA price: equals KEPCO's IRR at KRW {f.be_price:,.1f} — {where}"),
                  src=["mcee", "tou", "ksj"], unit=self.T("지분 IRR (해지 없음)", "Equity IRR (no termination)"),
                  chart_key="price_irr",
                  chart=charts.line_ref(xs, [("", ys, c["gold"])], c, lambda v: f"{v:,.0f}", lambda v: f"{v * 100:.0f}%",
                                        hlines=[(irr["cfd"], self.T(f"한전 계약 {self.pct(irr['cfd'])}", f"KEPCO {self.pct(irr['cfd'])}"), c["brown_dark"]),
                                                (self.hurdle, self.T(f"요구수익률 {self.pct(self.hurdle, 0)}", f"Hurdle {self.pct(self.hurdle, 0)}"), c["brick"])],
                                        vlines=[(f.be_price, self.T(f"IRR 기준 {f.be_price:,.1f}", f"IRR basis {f.be_price:,.1f}"), c["brown_dark"])],
                                        shade=(lo, hi, self.T("가격 회랑", "Corridor")), label_left=True),
                  note=self.T(f"가격마다 대출을 다시 sizing(PPA 조건). 이 쪽의 '필요 가격'은 모두 NPV 기준(오른쪽 표) — 해지 없음·스프레드 0이면 {p0['price']:,.1f}원. "
                              f"IRR 기준({f.be_price:,.1f}원)이 더 높은 이유: 두 경로의 지분 규모가 달라(대출 비율 {self.pct(f.debts['cfd'].gearing, 0)} vs {self.pct(f.debts['ppa'].gearing, 0)}) IRR과 NPV 순위가 다르게 나온다",
                              f"Debt re-sized at each price (PPA terms). All 'required prices' here are NPV-based (table) — {p0['price']:,.1f} with no termination and no spread. "
                              f"The IRR basis ({f.be_price:,.1f}) is higher because equity sizes differ (gearing {self.pct(f.debts['cfd'].gearing, 0)} vs {self.pct(f.debts['ppa'].gearing, 0)})"))
        rows, gold, shade = [], set(), set()
        for i, h in enumerate(self.v["hazards"]):
            ps = [self.pg(float(h), float(s_)) for s_ in sp]
            rows.append([self.pct(float(h), 1)] + [f"+{p['premium']:,.1f}" for p in ps] + [self.room_rng(ps[-1]["max_fee"], ps[0]["max_fee"]).replace("원", "")])
            if abs(float(h) - self.mc_h) < 1e-12:
                shade.add(i)
                gold |= {(i, j) for j in range(1, len(sp) + 2)}
        hdr = [self.T("연 해지 확률", "Annual term.")] + [self.T(f"프리미엄 +{s_ * 100:.0f}%p", f"Premium +{s_ * 100:.0f}pp") for s_ in sp] + [self.T("망이용료 여유", "Room for charges")]
        lo_p, hi_p = self.prem_rng()
        c2 = Cell(title=self.T(f"필요 PPA 프리미엄: 연 해지 {self.pct(self.mc_h, 0)}면 +{lo_p['premium']:.0f}~{hi_p['premium']:.0f}원 — PPA 위험 스프레드가 해지 확률만큼 중요",
                               f"Required premium: +{lo_p['premium']:.0f}–{hi_p['premium']:.0f} at {self.pct(self.mc_h, 0)} termination — the risk spread matters as much as the termination rate"),
                  src=["mcee", "tou", "solar", "ksj"],
                  table=TableSpec(hdr, rows, [0.18] + [0.17] * len(sp) + [0.31], ["C"] + ["R"] * len(sp) + ["R"], gold_cells=gold, shade_rows=shade, font_size=8.2),
                  note=self.T(f"필요 가격(NPV 기준) = 지분 NPV 기대값이 한전 계약 지분 NPV(요구수익률 {self.pct(self.hurdle, 0)})와 같아지는 PPA 가격. PPA 쪽 할인율 = 요구수익률 + 스프레드(민간 상대방 위험 프리미엄, 저자 판단 격자). "
                              f"해지는 PPA 기간 중 연 확률로 발생(기하분포), 해지 후 SMP 판매, 대출은 해지 없는 sizing 그대로. 프리미엄 = 필요 가격 − 한전 계약가, 여유 = 태양광 시간대 회피 요금 {hi:,.1f}원 × (1 + 기반기금 {self.fund_pct()}) = {self.room_cap():,.1f}원 − 필요 가격(기반기금을 포함한 부대비용과 같은 기준)",
                              f"Required price (NPV) = PPA price at which expected equity NPV equals KEPCO's equity NPV at {self.pct(self.hurdle, 0)}. PPA flows discounted at the hurdle plus a spread (private-counterparty premium, judgement grid). "
                              f"Constant annual termination during the PPA, SMP afterwards, debt kept at no-termination sizing. Premium = required − KEPCO price; room = solar-hour saving {hi:,.1f} × (1 + {self.fund_pct()} fund levy) = {self.room_cap():,.1f} − required (same basis as levy-inclusive charges)"))
        net, kpx = self.net_ex(), f.V("kpx_ancillary")
        base = self.tc["base"]
        from .tou import SEASON_OF_MONTH
        scol = {"spring_autumn": c["warm_grey_light"], "summer": c["gold"], "winter": c["brown_mid"]}
        months = list(range(1, 13))
        mv = [base["month"][m] + float(self.tc["adder"]) for m in months]
        low_s = self.below_cfd()
        sh = base["gen_share"]
        low_share = sum(sh[k] for k in low_s)
        c3 = Cell(title=self.T(f"계절별 회피 요금 vs 한전 계약가: " + (f"{'·'.join(self.season_name(k, True) for k in low_s)}(발전량 {self.pct(low_share, 0)})은 {self.season(low_s[0]):,.1f}원으로 한전 계약가 {lo:,.1f}원보다 낮다" if low_s
                                                              else f"모든 계절이 한전 계약가 {lo:,.1f}원보다 높다"),
                               "Seasonal saving vs KEPCO price: " + (f"{', '.join(self.season_name(k, True) for k in low_s)} ({self.pct(low_share, 0)} of output) at {self.season(low_s[0]):,.1f}, below KEPCO's {lo:,.1f}" if low_s
                                                                     else f"every season above KEPCO's {lo:,.1f}")),
                  src=["tou", "solar", "mcee", "kepco", "ksj"], unit=self.T(f"원/kWh (월별 회피 요금 = {self.cap_basis()})", f"KRW/kWh (monthly saving = {self.cap_basis()})"),
                  legend=[(scol[k], f"{self.season_name(k, True)} {self.season(k):,.1f}") for k in ("spring_autumn", "summer", "winter")],
                  chart_key="tou",
                  chart=charts.month_bars([self.T(f"{m}월", f"{m}") for m in months], mv, [scol[SEASON_OF_MONTH[m]] for m in months], c, lambda v: f"{v:,.0f}",
                                          [(lo, self.T(f"한전 계약가 {lo:,.1f}", f"KEPCO {lo:,.1f}"), c["brown_dark"]),
                                           (p1["price"], self.T(f"필요 PPA {p1['price']:,.1f}", f"Req. PPA {p1['price']:,.1f}"), c["gold"]),
                                           (hi, self.T(f"연간 {hi:,.1f}", f"Annual {hi:,.1f}"), c["brick"]),
                                           (self.avg(), self.T(f"평균 단가 {self.avg():,.1f}(참고)", f"Avg tariff {self.avg():,.1f} (ref.)"), c["warm_grey"])],
                                          (100, 190)),
                  note=self.T(f"산업용(을) {self.contract()} 개편 후 전력량요금 × 하루 발전 형상(저자 판단) × 2025년 요일 구성(일요일 전 시간 경부하, 봄·가을 주말 11~14시 50% 할인) — 계절·연간 값은 2025년 월별 발전량 가중. "
                              f"필요 PPA = 연 해지 {self.pct(self.mc_h, 0)}·스프레드 0. 할인이 2030년 말 끝나면 연간 {self.tc['sens']['no_discount'] + self.tc['adder']:,.1f}원" + self.prov_note(["solar_shape_p", "tou_saturday", "tou_sunday_holiday", "fuel_adj", "climate_env"]),
                              f"Post-reform industrial (B) {self.contract()} energy rates × daily output shape (judgement) × 2025 calendar (Sundays off-peak all day, 50% off 11:00–14:00 on spring/autumn weekends); seasonal and annual values weighted by 2025 monthly output. "
                              f"Required PPA at {self.pct(self.mc_h, 0)} termination, no spread. If the discount ends after 2030: {self.tc['sens']['no_discount'] + self.tc['adder']:,.1f} a year" + self.prov_note(["solar_shape_p", "tou_saturday", "tou_sunday_holiday", "fuel_adj", "climate_env"])))
        g = f.extra["gearing_check"]
        vd = self.verdict()
        c4 = Cell(title={"none": self.T("협상의 결론: 태양광 시간대 요금으로는 PPA 가격부터 맞지 않는다 — 성패는 구매자가 RE100 가치를 얼마나 쳐주느냐",
                                        "The negotiation: on solar-hour rates the price itself does not close — it turns on what the buyer pays for RE100 value"),
                         "charges": (self.T(f"협상의 결론: 가격은 맞출 수 있지만(여유 {self.room_rng(hi_p['max_fee'], lo_p['max_fee'], 0)}) 망이용료(공개 사례 {net:.0f}원, B)를 내면 성립하지 않는다 — 성패는 구매자의 RE100 지불의사",
                                            f"The negotiation: the price can be agreed (room {self.room_rng(hi_p['max_fee'], lo_p['max_fee'], 0)}) but fails once network charges (~{net:.0f} public example, B) are paid — it turns on the buyer's RE100 willingness to pay")
                                     if hi_p["max_fee_ex"] >= 0 else
                                     self.T("협상의 결론: 가격은 위험 스프레드가 작을 때만 간신히 맞고, 망이용료를 내면 성립하지 않는다 — 성패는 구매자의 RE100 지불의사",
                                            "The negotiation: the price only just works at a low risk spread and fails once network charges are paid — it turns on the buyer's RE100 willingness to pay")),
                         "ok": self.T("협상의 결론: 가격은 맞출 수 있다 — 거래의 성패는 부대비용과 구매자 상한의 정확한 계산",
                                      "The negotiation: price can be agreed — the deal turns on the charges and the buyer's true ceiling")}[vd],
                  src=["survey", "tou", "ksj"], panel_lead=self.T("IC가 물을 질문", "What the IC will ask"),
                  bullets=[self.T(f"회랑 {hi - lo:,.1f}원 vs 발전사 몫 +{lo_p['premium']:.0f}~{hi_p['premium']:.0f}원 → 구매자 여유 {self.room_rng(hi_p['max_fee'], lo_p['max_fee'])} (공개 사례 부대비용 {net:.0f}원)",
                                  f"A {hi - lo:,.1f} corridor vs the seller's +{lo_p['premium']:.0f}–{hi_p['premium']:.0f} → buyer room {self.room_rng(hi_p['max_fee'], lo_p['max_fee'])} ({net:.0f} public example)"),
                           self.T(f"성립 조건: 구매자가 kWh당 {self.wtp_need(lo_p, kpx, False):,.0f}~{self.wtp_need(hi_p, kpx, False):,.0f}원(부가정산금 {kpx:.2f}원만 반영) ~ {self.wtp_need(lo_p, net):,.0f}~{self.wtp_need(hi_p, net):,.0f}원(공개 사례)을 RE100 가치로 더 내야 — 평균 판매단가 기준({self.avg():,.1f}원)으로 재면 이 부담이 가려진다",
                                  f"To close, the buyer must pay {self.wtp_need(lo_p, kpx, False):,.0f}–{self.wtp_need(hi_p, kpx, False):,.0f} (KPX settlement only) to {self.wtp_need(lo_p, net):,.0f}–{self.wtp_need(hi_p, net):,.0f} (public example) per kWh for RE100 value — the {self.avg():,.1f} average tariff hides this"),
                           self.T(f"결과를 움직이는 저자 판단: PPA 대출 비율 65%면 프리미엄 +{g[0.65]:.0f}원, 80%면 +{g[0.8]:.0f}원(연 해지 {self.pct(self.mc_h, 0)}, 스프레드 0)",
                                  f"Judgement that moves it: PPA gearing 65% → +{g[0.65]:.0f}, 80% → +{g[0.8]:.0f} ({self.pct(self.mc_h, 0)}, no spread)"),
                           self.T("기업 설문에서도 망이용요금 산정 과정의 불투명성이 PPA 기피 이유 2위(45.2%) — 전력거래소가 직접 PPA 정책 연구 용역 중(뉴시스 2026-05-04)",
                                  "In a corporate survey, opaque network-charge setting is the No.2 reason to avoid PPAs (45.2%); KPX has commissioned a direct-PPA policy study (Newsis, 4 May 2026)")])
        if self.no_room():
            t5 = self.T(f"PPA 협상: 발전사는 한전 계약 +{lo_p['premium']:.0f}~{hi_p['premium']:.0f}원이 필요한데 데이터센터가 아끼는 요금은 +{hi - lo:,.1f}원뿐 — 망이용료 전 여유가 {self.room_rng(hi_p['max_fee_ex'], lo_p['max_fee_ex'])}",
                        f"PPA negotiation: the seller needs +{lo_p['premium']:.0f}–{hi_p['premium']:.0f} over KEPCO, the buyer saves only +{hi - lo:,.1f} — room before charges is {self.room_rng(hi_p['max_fee_ex'], lo_p['max_fee_ex'])}")
        else:
            t5 = self.T(f"PPA 협상: 발전사는 +{lo_p['premium']:.0f}~{hi_p['premium']:.0f}원이면 되지만, 데이터센터 여유 {self.room_rng(hi_p['max_fee'], lo_p['max_fee'], 0)}은 공개 사례 부대비용 {net:.0f}원(B)보다 작다",
                        f"PPA negotiation: the seller needs +{lo_p['premium']:.0f}–{hi_p['premium']:.0f}, but the buyer's {self.room_rng(hi_p['max_fee'], lo_p['max_fee'], 0)} room is below the {net:.0f} public example (B)")
        return Page("body", "5", t5,
                    self.T("PPA 가격별 IRR → 해지 확률 × 위험 스프레드별 필요 가격(NPV) → 계절별 구매자 회피 요금 → 성립 조건", "IRR by price → required price by termination × spread (NPV) → buyer's seasonal saving → what it takes to close"),
                    [c1, c2, c3, c4])

    # --- p6 ------------------------------------------------------------------
    def p6(self) -> Page:
        f, c, irr = self.f, self.c, self.irr
        ys = [v for _, v in f.default_curve]
        yrs = [y for y, _ in f.default_curve]
        cross = next((y for y, v in f.default_curve if v is not None and v >= irr["cfd"]), None)
        cross_h = next((y for y, v in f.default_curve if v is not None and v >= self.hurdle), None)
        if cross is not None:
            t61 = self.T(f"해지 시점별 지분 IRR: PPA가 {cross - 1}년을 못 채우고 끊기면 한전 계약보다 못하다", f"Equity IRR by termination year: a PPA that ends before {cross - 1} full years does worse than KEPCO")
        else:
            t61 = (self.T(f"해지 시점별 지분 IRR: 회랑 중간 가격이면 해지가 없어야 한전 계약과 같은 수준({self.ip('ppa')} vs {self.ip('cfd')}) — 한 번이라도 끊기면 못하다",
                          f"Equity IRR by termination year: at the corridor mid the PPA only matches KEPCO ({self.ip('ppa')} vs {self.ip('cfd')}) if it never ends early — any break leaves it behind")
                   if self.irr_close() else
                   self.T(f"해지 시점별 지분 IRR: 회랑 중간 가격이면 PPA가 끝까지 유지돼도 한전 계약({self.pct(irr['cfd'])})보다 낮다", f"Equity IRR by termination year: at the corridor mid the PPA trails KEPCO ({self.pct(irr['cfd'])}) even if it runs to term"))
        c1 = Cell(title=t61,
                  src=["ksj"], unit=self.T("지분 IRR", "Equity IRR"),
                  chart_key="default",
                  chart=charts.line_ref(yrs, [("", ys, c["gold"])], c, lambda v: f"{v:.0f}", lambda v: f"{v * 100:.0f}%",
                                        hlines=[(irr["cfd"], self.T(f"한전 계약 {self.pct(irr['cfd'])}", f"KEPCO {self.pct(irr['cfd'])}"), c["brown_dark"]),
                                                (self.hurdle, self.T(f"요구수익률 {self.pct(self.hurdle, 0)}", f"Hurdle {self.pct(self.hurdle, 0)}"), c["brick"]),
                                                (irr["ppa"], self.T(f"해지 없음 {self.pct(irr['ppa'])}", f"No termination {self.pct(irr['ppa'])}"), c["gold"])],
                                        label_left=True, xticks=[1, 5, 10, 15, 20]),
                  note=self.T(f"x축 = 해지 연차 N(N년 차부터 SMP {f.market.smp0:,.1f}원 판매 = PPA N−1년 유지). PPA 가격 = 회랑 중간 {self.kwh(f.ppa_mid)}, 대출 고정(재조달 없음), 위약금 0",
                              f"x-axis = termination year N (SMP {f.market.smp0:,.1f} from year N = PPA lasted N−1 years). PPA at corridor mid {self.kwh(f.ppa_mid)}, debt fixed (no refinancing), no termination payment"))
        pick = [1, 3, 5, 8, 10, 15, 20]
        rows = []
        for y, v in f.default_curve:
            if y in pick:
                rows.append([self.T(f"{y}년 차 해지 (PPA {y - 1}년 유지)", f"Year {y} (PPA lasted {y - 1} yrs)"), self.pct(v), self.T("미달" if (v or -1) < irr["cfd"] else "상회", "below" if (v or -1) < irr["cfd"] else "above")])
        rows.append([self.T("해지 없음", "No termination"), self.pct(irr["ppa"]), "—"])
        c2 = Cell(title=self.T(f"요구수익률 {self.pct(self.hurdle, 0)}를 지키려면 PPA가 {cross_h - 1}년 이상 유지돼야 한다", f"To keep the {self.pct(self.hurdle, 0)} hurdle the PPA must last {cross_h - 1}+ years"),
                  src=["ksj"],
                  table=TableSpec([self.T("해지 시점", "Termination"), self.T("지분 IRR", "Equity IRR"), self.T("한전 계약 대비", "vs KEPCO")], rows, [0.50, 0.25, 0.25], ["L", "R", "C"],
                                  brick_cells={(i, 2) for i, r in enumerate(rows) if r[2] in ("미달", "below")}, font_size=8.6),
                  note=self.T("해지 후 판매 가격이 SMP라 초기 해지일수록 손실이 크다 — 위약금(남은 기간 가치의 일부)이 이 곡선의 왼쪽을 받친다",
                              "After termination the plant earns SMP, so early breaks hurt most — termination payments prop up the left side of this curve"))
        v2 = self.vol2
        rows2 = [[self.T("데이터센터 SPV 최소 DSCR (Vol.2 한국 케이스)", "Data-centre SPV min DSCR (Vol.2 Korea)"), self.x(v2.get("min_dscr"))],
                 [self.T("데이터센터 지분 IRR (Vol.2)", "Data-centre equity IRR (Vol.2)"), self.pct(v2.get("equity_irr"))],
                 [self.T("전력비 처리 (Vol.2)", "Power cost treatment (Vol.2)"), self.T("임차인 별도 청구(100%)", "Billed to tenants (100%)")],
                 [self.T("PPA 물량 / 데이터센터 사용량", "PPA volume / data-centre use"), self.pct(f.dc["share"], 0)]]
        dscr_v2 = self.T(f"최소 DSCR {self.x(v2.get('min_dscr'))}", f"min DSCR {self.x(v2.get('min_dscr'))}") if v2.get("min_dscr") else self.T("DSCR 미확인", "DSCR n/a")
        c3 = Cell(title=self.T(f"오프테이커 = Vol.2 데이터센터: 대주 기준 {dscr_v2}, 전력비는 임차인에게 넘긴다", f"Offtaker = Vol.2's data centre: lender {dscr_v2}, power passed to tenants"),
                  src=["vol2"], table=TableSpec([self.T("항목", "Item"), self.T("값", "Value")], rows2, [0.66, 0.34], ["L", "R"], font_size=8.6),
                  note=self.T("PPA 대금의 실제 원천은 임차인(하이퍼스케일러 등)의 전력비 — 임대 계약이 PPA보다 짧으면 그 차이가 해지 위험이 된다",
                              "The PPA is ultimately paid from tenants' power bills — if leases are shorter than the PPA, the gap becomes termination risk"))
        c4 = Cell(title=self.T("완화책: 해지 확률과 손실을 줄이는 계약 조항", "Mitigants: contract terms that cut termination risk and loss"), src=["ksj"],
                  panel_lead=self.T("텀시트에서 지킬 것 (A1)", "What to hold in the term sheet (A1)"),
                  bullets=[self.T("해지 위약금: 남은 기간 PPA 가치와 SMP의 차이 일부를 보전", "Termination payment: covers part of the PPA-vs-SMP gap for the remaining term"),
                           self.T("신용보강: 모회사 보증·신용장, 또는 임대 계약의 전력비 조항을 PPA와 같은 기간으로", "Credit support: parent guarantee or LC, or align lease power clauses with the PPA term"),
                           self.T("계약 승계: 데이터센터 매각·재조달 시 PPA가 따라가게(assignment)", "Assignment: the PPA follows the data centre on sale or refinancing"),
                           self.T("법 변경 조항: 망이용료 개편으로 구매자 비용이 바뀔 때의 재협상 기준", "Change in law: a renegotiation rule if network-charge reform changes the buyer's cost")])
        if cross is not None:
            t6 = self.T(f"오프테이커 위험: PPA가 {cross - 1}년을 못 채우면 한전 계약보다 못하다 — 위약금·보증으로 초기 해지 손실을 막아야",
                        f"Offtaker risk: a PPA shorter than {cross - 1} years underperforms KEPCO — termination payments and guarantees must cover early breaks")
        else:
            lv = self.irr_close()
            k1 = "해지가 없어야 한전 계약과 같은 수준이고" if lv else "해지가 없어도 한전 계약보다 낮고"
            e1 = "only matches KEPCO without termination" if lv else "trails KEPCO even without termination"
            t6 = self.T(f"오프테이커 위험: 회랑 중간 가격의 PPA는 {k1}, 해지되면 더 떨어진다 — {self.pct(self.hurdle, 0)}를 지키려면 {cross_h - 1}년 이상 유지돼야" if cross_h else
                        f"오프테이커 위험: 회랑 중간 가격의 PPA는 {k1}, 해지되면 더 떨어진다",
                        f"Offtaker risk: at the corridor mid the PPA {e1} and falls further on a break — it must last {cross_h - 1}+ years to hold {self.pct(self.hurdle, 0)}" if cross_h else
                        f"Offtaker risk: at the corridor mid the PPA {e1} and falls further on a break")
        return Page("body", "6", t6,
                    self.T("해지 시점별 지분 IRR → 요구수익률 유지 기간 → Vol.2 데이터센터 신용 → 계약 완화책", "Equity IRR by termination year → hurdle-holding term → Vol.2 credit → contractual mitigants"),
                    [c1, c2, c3, c4])

    # --- p7 ------------------------------------------------------------------
    def p7(self) -> Page:
        f, c = self.f, self.c
        if not ok(f.mc):
            cell = Cell(title=self.T("몬테카를로", "Monte Carlo"), placeholder=(f.mc.reason, ""))
            return Page("body", "7", self.T("몬테카를로: 실행 후 생성", "Monte Carlo: generated after a run"), "", [cell], grid="1x1")
        R = ("cfd", "ppa", "merchant")
        st = {k: mc_stats(f.mc[k], self.hurdle) for k in R}
        clip = lambda a: list(np.clip(a, -0.05, 0.20))  # noqa: E731
        worse = float((f.mc["ppa"] < f.mc["cfd"]).mean())
        med_hi = st["ppa"]["p50"] > st["cfd"]["p50"]
        c1 = Cell(title=self.T(f"지분 IRR 분포 ({f.mc_spec.n:,}회): 직접 PPA는 " + ("중앙값이 높지만" if med_hi else "중앙값도 낮고") + f" 하위 5%는 한전 계약보다 낮다 (P50 {self.pct(st['ppa']['p50'])} vs {self.pct(st['cfd']['p50'])} · P5 {self.pct(st['ppa']['p5'])} vs {self.pct(st['cfd']['p5'])})",
                               f"Equity IRR ({f.mc_spec.n:,} runs): the PPA has " + ("the higher median but" if med_hi else "a lower median and") + f" a weaker bottom 5% (P50 {self.pct(st['ppa']['p50'])} vs {self.pct(st['cfd']['p50'])} · P5 {self.pct(st['ppa']['p5'])} vs {self.pct(st['cfd']['p5'])})"),
                  src=["smp", "ksj"], legend=[(c["warm_grey_light"], self.T("사분위 상자 · 중앙값", "IQR box · median"))], unit=self.T("지분 IRR", "Equity IRR"),
                  chart_key="mc", chart=charts.irr_boxes([(self.route(k, True), clip(f.mc[k])) for k in R], c,
                                                         [(self.hurdle, self.T("요구수익률", "Hurdle"), c["brick"])]),
                  note=self.T(f"같은 난수(SMP·발전량)를 세 경로에 공통 적용 — 차이는 계약 구조에서만 나온다. 직접 PPA는 연 해지 {self.pct(self.mc_h, 0)}. 표시 범위 −5~20%(밖은 끝에 표시)"
                              + self.prov_note(["smp_sigma", "smp_phi", "smp_base"]),
                              f"Common random numbers (SMP, output) across routes — differences come from the contracts only. PPA termination {self.pct(self.mc_h, 0)} a year. Shown −5% to 20%"
                              + self.prov_note(["smp_sigma", "smp_phi", "smp_base"])))
        rows = [[self.route(k, True), self.pct(st[k]["p5"]), self.pct(st[k]["p10"]), self.pct(st[k]["p50"]), self.pct(st[k]["p90"]), self.pct(st[k]["below"], 0), self.pct(st[k]["neg"], 0)] for k in R]
        c2 = Cell(title=self.T(f"요구수익률 {self.pct(self.hurdle, 0)} 미달 확률: 한전 계약 {self.pct(st['cfd']['below'], 0)} · 직접 PPA {self.pct(st['ppa']['below'], 0)}",
                               f"Probability below the {self.pct(self.hurdle, 0)} hurdle: KEPCO {self.pct(st['cfd']['below'], 0)} · PPA {self.pct(st['ppa']['below'], 0)}"),
                  src=["ksj"],
                  table=TableSpec([self.T("경로", "Route"), "P5", "P10", "P50", "P90", self.T("요구수익률 미달", "< hurdle"), self.T("손실(IRR<0)", "Loss (IRR<0)")], rows,
                                  [0.18, 0.11, 0.11, 0.11, 0.11, 0.20, 0.18], ["L", "R", "R", "R", "R", "R", "R"], gold_cells={(1, 3)}, brick_cells={(1, 1), (2, 6)}, font_size=8.4),
                  note=self.T(f"직접 PPA가 같은 경로(같은 난수)에서 한전 계약보다 못한 확률 {self.pct(worse, 0)}. 대출은 기준 sizing으로 고정 — 나쁜 해에 지분이 부족분을 메운다(지분 흐름 음수 허용, 배당 제한·채무불이행 처리는 모델에 없음)",
                              f"The PPA underperforms KEPCO on the same path {self.pct(worse, 0)} of the time. Debt fixed at base sizing — equity funds shortfalls (no lock-up or default mechanics in the model)"))
        I = f.inputs
        mrows = [[self.lab("smp_sigma"), f"{f.mc_spec.smp_sigma:.2f}", (TIER_KR if self.kr else TIER_EN)[I["smp_sigma"].tier]],
                 [self.lab("smp_phi"), f"{f.mc_spec.smp_phi:.2f}", (TIER_KR if self.kr else TIER_EN)[I["smp_phi"].tier]],
                 [self.lab("cf_sd_annual"), self.pct(f.mc_spec.cf_sd_annual, 0), (TIER_KR if self.kr else TIER_EN)[I["cf_sd_annual"].tier]],
                 [self.lab("cf_sd_resource"), self.pct(f.mc_spec.cf_sd_resource, 0), (TIER_KR if self.kr else TIER_EN)[I["cf_sd_resource"].tier]],
                 [self.T("PPA 연 해지 확률", "PPA annual termination"), self.pct(self.mc_h, 0), (TIER_KR if self.kr else TIER_EN)["J"]],
                 [self.T("반복 · seed", "Runs · seed"), f"{f.mc_spec.n:,} · {f.mc_spec.seed}", "—"]]
        c3 = Cell(title=self.T(f"입력: SMP 변동성 {f.mc_spec.smp_sigma:.2f}·평균회귀 {f.mc_spec.smp_phi:.2f}는 2002~2025년 연평균 SMP 24년에서 추정", f"Inputs: SMP volatility {f.mc_spec.smp_sigma:.2f} and mean reversion {f.mc_spec.smp_phi:.2f} estimated from 24 years of annual SMP (2002–2025)"),
                  src=["ksj"], table=TableSpec([self.T("입력", "Input"), self.T("값", "Value"), self.T("신뢰 등급", "Grade")], mrows, [0.50, 0.22, 0.28], ["L", "R", "C"], font_size=8.6),
                  note=self.T("SMP: 로그 AR(1), 평균 보존 보정 · 발전량: 장기 추정 오차(한 번) × 연간 변동(매년) · 해지: PPA 기간 중 기하분포",
                              "SMP: log AR(1), mean-preserving · output: one resource error × annual noise · termination: geometric within the PPA term"))
        c4 = Cell(title=self.T("읽는 법: PPA의 위험은 '평균'이 아니라 '꼬리'에 있다", "How to read it: the PPA's risk is in the tail, not the average"), src=["ksj"],
                  panel_lead=self.T("분포가 말하는 것", "What the distribution says"),
                  bullets=[self.T(f"한전 계약: 분포가 좁다(P10 {self.pct(st['cfd']['p10'])}~P90 {self.pct(st['cfd']['p90'])}) — 발전량만 흔든다", f"KEPCO: narrow (P10 {self.pct(st['cfd']['p10'])}–P90 {self.pct(st['cfd']['p90'])}) — only output varies"),
                           (self.T(f"직접 PPA: P10까지는 한전 계약보다 높지만 P5 {self.pct(st['ppa']['p5'])} — 초기 해지 경로(약 {self.pct(worse, 0)})가 맨 아래 꼬리를 만든다", f"PPA: above KEPCO down to P10, but P5 {self.pct(st['ppa']['p5'])} — early terminations (~{self.pct(worse, 0)}) form the bottom tail")
                            if st["ppa"]["p10"] > st["cfd"]["p10"] else
                            self.T(f"직접 PPA: 회랑 중간 가격이면 분포가 한전 계약 아래로 내려온다(P50 {self.pct(st['ppa']['p50'])}, P5 {self.pct(st['ppa']['p5'])}) — {self.pct(worse, 0)} 경로에서 한전 계약보다 못하다",
                                   f"PPA: at the corridor mid the distribution sits below KEPCO (P50 {self.pct(st['ppa']['p50'])}, P5 {self.pct(st['ppa']['p5'])}) — worse than KEPCO on {self.pct(worse, 0)} of paths")),
                           self.T(f"시장 판매: 손실 확률 {self.pct(st['merchant']['neg'], 0)} — 신규 태양광의 무계약 판매는 지분 투자 대상이 아니다", f"Merchant: {self.pct(st['merchant']['neg'], 0)} loss probability — uncontracted new solar is not an equity case"),
                           (self.T("IC 관점: 가격(구매자의 RE100 지불의사)부터 확인 — 그다음이 꼬리를 자르는 장치(위약금·보증)", "IC view: settle the price (the buyer's RE100 willingness to pay) first, then tail protection (termination payments, guarantees)")
                            if self.verdict() != "ok" else
                            self.T("IC 관점: PPA를 택하면 꼬리를 자르는 장치(위약금·보증)가 가격보다 먼저다", "IC view: with a PPA, tail protection (termination payments, guarantees) comes before price"))])
        return Page("body", "7", self.T(f"몬테카를로: 직접 PPA 지분 IRR P50 {self.pct(st['ppa']['p50'])} · P5 {self.pct(st['ppa']['p5'])} — {self.pct(worse, 0)} 확률로 한전 계약보다 못하고, 시장 판매는 {self.pct(st['merchant']['neg'], 0)} 확률로 손실",
                                        f"Monte Carlo: PPA equity IRR P50 {self.pct(st['ppa']['p50'])} · P5 {self.pct(st['ppa']['p5'])} — below KEPCO {self.pct(worse, 0)} of the time; merchant loses money {self.pct(st['merchant']['neg'], 0)} of the time"),
                    self.T(f"{f.mc_spec.n:,}회 × 3경로 · seed {f.mc_spec.seed} · SMP(로그 AR1) × 발전량 × PPA 해지", f"{f.mc_spec.n:,} runs × 3 routes · seed {f.mc_spec.seed} · SMP (log AR1) × output × PPA termination"),
                    [c1, c2, c3, c4])

    # --- p8 ------------------------------------------------------------------
    def p8(self) -> Page:
        f, irr = self.f, self.irr
        p1 = self.prem(self.mc_h)
        lo, hi = self.prem_rng()
        net = self.net_ex()
        vd = self.verdict()
        c1 = Cell(title={"none": self.T("결론: 태양광 시간대 요금 기준으로는 직접 PPA 가격이 맞지 않는다", "Conclusion: on solar-hour rates the direct-PPA price does not close"),
                         "charges": self.T("결론: 태양광 시간대 요금 기준으로는 망이용료까지 내면 직접 PPA가 맞지 않는다", "Conclusion: on solar-hour rates the direct PPA fails once network charges are paid"),
                         "ok": self.T("결론: 직접 PPA는 가격보다 부대비용과 구조의 문제", "Conclusion: a direct PPA turns on charges and structure, not price")}[vd],
                  src=["tou", "sfoc", "ksj"],
                  panel_lead="", bullets=[
                      self.T(f"가격: 발전사는 한전 계약 +{lo['premium']:,.1f}~{hi['premium']:,.1f}원(연 해지 {self.pct(self.mc_h, 0)}, 스프레드 0~2%p)이 필요 — 구매자가 태양광 시간대에 아끼는 몫은 +{f.corridor[1] - f.corridor[0]:,.1f}원"
                             + (" → 회랑보다 크다" if lo["premium"] > f.corridor[1] - f.corridor[0] else " 안"),
                             f"Price: the seller needs +{lo['premium']:,.1f}–{hi['premium']:,.1f} over KEPCO ({self.pct(self.mc_h, 0)} termination, 0–2pp spread) — the buyer saves only +{f.corridor[1] - f.corridor[0]:,.1f} in solar hours"),
                      self.T(f"성패: 구매자 여유 {self.room_rng(hi['max_fee'], lo['max_fee'])}(회피 요금 + 기반기금 기준) — 망이용료(공개 사례 약 {net:.0f}원)까지 내려면 구매자가 RE100 가치로 kWh당 {self.wtp_need(lo, net):,.0f}~{self.wtp_need(hi, net):,.0f}원을 더 내야",
                             f"Make-or-break: buyer room {self.room_rng(hi['max_fee'], lo['max_fee'])} on the saving plus fund levy — covering ~{net:.0f} of charges needs {self.wtp_need(lo, net):,.0f}–{self.wtp_need(hi, net):,.0f} per kWh of RE100 value from the buyer"),
                      self.T("위험: 초기 해지 — 위약금·보증·계약 승계로 손실을 줄이면 필요 프리미엄도 내려간다", "Risk: early termination — termination payments, guarantees and assignment lower the loss and the premium"),
                      self.T(f"대안 비교: 한전 계약 지분 IRR {self.ip('cfd')}(회랑 중간 PPA {self.ip('ppa')}" + ("와 같은 수준 — 해지 위험은 PPA만" if self.irr_close() else ("보다 높다" if (irr['cfd'] or 0) > (irr['ppa'] or 0) else "보다 낮다")) + f"), 무계약 시장 판매는 {self.pct(irr['merchant'])}",
                       f"Alternatives: KEPCO at {self.ip('cfd')} (" + ("level with" if self.irr_close() else ("above" if (irr['cfd'] or 0) > (irr['ppa'] or 0) else "below")) + f" the corridor-mid PPA's {self.ip('ppa')}{', which alone carries termination risk' if self.irr_close() else ''}), merchant at {self.pct(irr['merchant'])}")])
        rows = [[self.T("가격", "Price"), self.T(f"회랑 {f.corridor[0]:,.1f}~{f.corridor[1]:,.1f}원", f"Corridor {f.corridor[0]:,.1f}–{f.corridor[1]:,.1f}"),
                 self.T("2027년 계약시장 상한 · 데이터센터 실제 계약종별·선택요금 · 시간별 발전 실측 · 기후환경·연료비조정요금", "2027 contract-market cap · actual tariff class and option · measured hourly output · climate and fuel add-ons"), "3, 5"],
                [self.T("망이용료", "Network charges"), self.T(f"여유 {self.room_rng(hi['max_fee'], lo['max_fee'], 0)} vs 사례 {net:.0f}원", f"Room {self.room_rng(hi['max_fee'], lo['max_fee'], 0)} vs {net:.0f} example"), self.T("현재 송배전이용요금 · 부가정산금 · 손실 · 기반기금 · 구매자 RE100 지불의사", "Current T&D tariffs · settlements · losses · fund levy · buyer's RE100 willingness to pay"), "3, 5"],
                [self.T("오프테이커", "Offtaker"), self.T("해지 확률 격자 0~5%", "Termination grid 0–5%"), self.T("신용평가 · 임대 계약 기간 · 보증", "Rating · lease term · guarantees"), "6"],
                [self.T("발전량", "Output"), self.T(f"이용률 {self.pct(f.asset.capacity_factor, 0)}(BNEF·KEEI)", f"CF {self.pct(f.asset.capacity_factor, 0)} (BNEF/KEEI)"), self.T("P50/P90 발전량 보고서 · 출력제한 이력", "P50/P90 yield report · curtailment"), "4, 7"],
                [self.T("사업비", "CAPEX"), self.T(f"{self.eok(f.asset.capex)}(LCOE 역산)", f"{self.eok(f.asset.capex)} (from LCOE)"), self.T("EPC 견적 · 토지 · 계통 접속비", "EPC quote · land · grid connection"), "4"],
                [self.T("프로파일", "Shape"), self.T("발전량 그대로 판매(pay-as-produced)", "Pay-as-produced"), self.T("24시간 공급 요구 시 부족분 조달 비용(ESS·한전)", "24/7 firming cost (storage, KEPCO)"), "—"]]
        c2 = Cell(title=self.T("IC 체크리스트: 이번 분석의 가정 vs 실제 딜에서 확인할 것", "IC checklist: this note's assumption vs what a real deal must confirm"), src=["ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("이번 분석", "This note"), self.T("실제 딜에서 확인", "Confirm in a deal"), self.T("쪽", "p.")], rows,
                                  [0.15, 0.30, 0.45, 0.10], ["L", "L", "L", "C"], font_size=8.0))
        c3 = Cell(title=self.T("이 노트의 한계", "Limits of this note"), src=["ksj"], panel_lead="", bullets=[
            self.T(f"사업비: 2022년 실제 설치비(kW당 {f.V('capex_per_kw'):,.0f}천원)로 계산한 LCOE {f.lcoe_check['actual_lcoe']:.0f}원이 에너지경제연구원 LCOE {f.lcoe_check['keei'][0]:.0f}~{f.lcoe_check['keei'][1]:.0f}원보다 낮다 — 보수적으로 LCOE 쪽에 맞춤",
                   f"CAPEX: 2022 actual installed cost (KRW {f.V('capex_per_kw'):,.0f}k/kW) implies an LCOE of {f.lcoe_check['actual_lcoe']:.0f}, below KEEI's {f.lcoe_check['keei'][0]:.0f}–{f.lcoe_check['keei'][1]:.0f} — matched to the LCOE to stay conservative"),
            self.T(f"구매자 상한 = 태양광 시간대 에너지요금({self.contract()}) + 연료비조정(2026년 4분기 단가, 보도 B, 분기마다 변동): 하루 발전 형상·토요일·공휴일 규칙은 저자 판단, {self.climate_text()}, 봄·가을 주말 할인은 2030년 말까지(끝나면 +{self.tc['sens']['no_discount'] - self.stage_val('energy'):,.1f}원) · RE100 가치·요금 인상 미반영",
                   f"Buyer ceiling = solar-hour energy rate ({self.contract()}) + fuel adjustment (Q4 2026, press report B, changes quarterly): daily shape and Saturday/holiday rules are judgements, {self.climate_text()}, weekend discount ends 2030 (+{self.tc['sens']['no_discount'] - self.stage_val('energy'):,.1f} after) · no RE100 value or tariff rises"),
            self.T(f"발전량 전부를 데이터센터가 쓰도록 용량을 {f.asset.mw:,.0f}MW로 맞춤 — 24시간 공급(형상) 위험·ESS·출력제한은 제외", f"Plant sized at {f.asset.mw:,.0f} MW so all output is used — 24/7 shape risk, storage and curtailment left out"),
            self.T("대출 조건(DSCR·대출 비율·만기)·해지 확률·위험 스프레드는 공개 근거가 없는 저자 판단 — 격자와 민감도로 공개", "Debt terms, termination rate and risk spread are unsourced judgements — shown as grids and sensitivities")])
        c4 = Cell(title=self.T("Vol.5 예고 (완결): AI 에너지 자산 투자 지도", "Next, Vol.5 (finale): an AI energy asset investment map"), src=["ksj"],
                  panel_lead=self.T("수요 · 기기 · PF · IPO · 발전을 한 장에", "Demand, equipment, PF, IPO and power on one page"),
                  bullets=[self.T("Vol.1~4의 결론을 위험·수익 지도에 배치 — 어느 자산이 어떤 투자자에게 맞나", "Place Vol.1–4 on one risk-return map — which asset fits which investor"),
                           self.T("IC 메모 형식: 투자 포인트 · 위험과 완화책 · 텀시트", "IC memo format: thesis, risks and mitigants, term sheet"),
                           self.T("시리즈 전체의 가정·출처 등급을 한 표로", "All assumptions and source grades in one table")])
        t8 = {"none": self.T("시사점: 태양광 시간대로 구매자 상한을 다시 재면 가격부터 막힌다 — 구매자의 RE100 지불의사 확인이 먼저, 부대비용·해지 보호는 그다음",
                             "Implications: measured on solar-hour rates the price itself blocks the deal — confirm the buyer's RE100 willingness to pay first, then charges and termination protection"),
              "charges": self.T(f"시사점: 구매자 여유 최대 약 {lo['max_fee']:,.0f}원은 공개 사례 망이용료 {net:.0f}원(B)에 못 미친다 — 구매자의 RE100 지불의사와 실제 망이용료 확인이 먼저, 해지 보호는 그다음",
                                f"Implications: the buyer's room of at most ~{lo['max_fee']:,.0f} falls short of the ~{net:.0f} public network-charge example (B) — confirm RE100 willingness to pay and actual charges first, then termination protection"),
              "ok": self.T("시사점: 직접 PPA는 가격보다 구조의 문제 — 부대비용 확인, 해지 보호가 먼저",
                           "Implications: a direct PPA is about structure, not price — verify charges and protect against termination")}[vd]
        return Page("body", "8", t8,
                    self.T("결론 · IC 체크리스트 · 한계 · Vol.5 예고", "Conclusion · IC checklist · limits · Vol.5 preview"), [c1, c2, c3, c4])

    # --- A1 IC 메모 ---------------------------------------------------------
    def a1(self) -> Page:
        f, irr = self.f, self.irr
        p1 = self.prem(self.mc_h)
        r = f.base["ppa"]
        st = mc_stats(f.mc["ppa"], self.hurdle) if ok(f.mc) else None
        rows = [[self.T("자산", "Asset"), self.T(f"가상 태양광 {f.asset.mw:,.0f}MW, {int(f.V('cod_year'))}년 상업운전", f"Hypothetical {f.asset.mw:,.0f} MW solar, COD {int(f.V('cod_year'))}")],
                [self.T("매출 구조", "Revenue"), self.T(f"데이터센터 직접 PPA {f.market.ppa_term}년, 발전량 그대로 판매", f"{f.market.ppa_term}-yr direct PPA with a data centre, pay-as-produced")],
                [self.T("사업비 · 자금", "Uses · sources"), self.T(f"{self.eok(f.asset.capex)} = 대출 {self.eok(r.debt)}({self.pct(r.gearing, 0)}) + 지분 {self.eok(r.equity)}",
                                                                    f"{self.eok(f.asset.capex)} = debt {self.eok(r.debt)} ({self.pct(r.gearing, 0)}) + equity {self.eok(r.equity)}")],
                [self.T("지분 수익률", "Equity return"), self.T(f"IRR {self.pct(irr['ppa'])}(회랑 중간) · 몬테카를로 P50 {self.pct(st['p50']) if st else '—'}",
                                                              f"IRR {self.pct(irr['ppa'])} (corridor mid) · Monte Carlo P50 {self.pct(st['p50']) if st else '—'}")],
                [self.T("가격 기준", "Pricing rule"), self.T(f"최소 {self.kwh(self.prem_rng()[0]['price'])}~{self.kwh(self.prem_rng()[1]['price'])} (한전 계약 +{self.prem_rng()[0]['premium']:,.0f}~{self.prem_rng()[1]['premium']:,.0f}원, 연 해지 {self.pct(self.mc_h, 0)}, 스프레드 0~2%p)",
                                                           f"At least {self.kwh(self.prem_rng()[0]['price'])}–{self.kwh(self.prem_rng()[1]['price'])} (KEPCO +{self.prem_rng()[0]['premium']:,.0f}–{self.prem_rng()[1]['premium']:,.0f}, {self.pct(self.mc_h, 0)} termination, 0–2pp spread)")]]
        c1 = Cell(title=self.T("투자 개요 (예시 — 가상 자산)", "Deal summary (illustrative — hypothetical asset)"), src=["ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("내용", "Detail")], rows, [0.24, 0.76], ["L", "L"], shade_rows={3, 4}, font_size=8.4))
        c2 = Cell(title=self.T("투자 포인트 3", "Three investment points"), src=["ksj"], panel_lead="", bullets=[
            (self.T(f"가격 우위: 회랑 중간이면 한전 계약 대비 IRR {self.sg((irr['ppa'] - irr['cfd']) * 100, 1, True)}%p", f"Price edge: at the corridor mid, {self.sg((irr['ppa'] - irr['cfd']) * 100, 1, True)}pp IRR over KEPCO")
             if irr["ppa"] > irr["cfd"] else
             (self.T(f"가격은 우위가 아니다: 회랑 중간이면 한전 계약 대비 IRR {self.sg((irr['ppa'] - irr['cfd']) * 100, 2, True)}%p — 한전 계약과 같아지는 {self.kwh(f.be_price)}은 구매자 상한 {self.kwh(f.corridor[1])} 위",
                     f"No price edge: at the corridor mid, {self.sg((irr['ppa'] - irr['cfd']) * 100, 2, True)}pp IRR vs KEPCO — matching KEPCO needs {self.kwh(f.be_price)}, above the buyer's {self.kwh(f.corridor[1])} ceiling")
              if f.be_price > f.corridor[1] else
              self.T(f"가격은 우위가 아니다: 회랑 중간이면 한전 계약 대비 IRR {self.sg((irr['ppa'] - irr['cfd']) * 100, 2, True)}%p — 한전 계약과 같아지는 {self.kwh(f.be_price)}은 구매자 상한 {self.kwh(f.corridor[1])} 안이지만, 그 차이 {f.corridor[1] - f.be_price:,.1f}원으로 망이용료를 내야 한다",
                     f"No price edge: at the corridor mid, {self.sg((irr['ppa'] - irr['cfd']) * 100, 2, True)}pp IRR vs KEPCO — matching KEPCO needs {self.kwh(f.be_price)}, inside the {self.kwh(f.corridor[1])} ceiling, leaving only {f.corridor[1] - f.be_price:,.1f} for network charges"))),
            self.T("수요 확실성: AI 데이터센터의 RE100 조달 수요 — 2027년 계약시장 전환·REC 발급기한(2026-12-31) 후 직접 조달 경로가 귀해진다", "Demand: AI data centres need RE100 supply — direct routes get scarcer after the 2027 contract-market shift and the REC issuance deadline (31 Dec 2026)"),
            self.T(f"하방 점검: 1년 차에 해지돼 SMP {f.market.smp0:,.0f}원에 팔면 최소 DSCR {f.extra['downside']['base']:.2f}배(원리금은 내지만 통상 배당 제한 수준), SMP {f.extra['downside']['low_smp']:,.0f}원이면 {f.extra['downside']['low']:.2f}배로 원리금 부족 — 위약금·보증이 필수",
                   f"Downside: terminated in year 1 and selling at SMP {f.market.smp0:,.0f}, min DSCR {f.extra['downside']['base']:.2f}x (debt paid, lock-up territory); at SMP {f.extra['downside']['low_smp']:,.0f} it falls to {f.extra['downside']['low']:.2f}x — termination payments and guarantees are essential")])
        rr = [[self.T("오프테이커 해지", "Offtaker termination"), self.T("위약금(잔여 가치 차액 일부) · 모회사 보증·신용장 · 계약 승계", "Termination payment · parent guarantee/LC · assignment")],
              [self.T("부대비용이 구매자 여유 초과", "Charges exceed the buyer's room"), self.T("계약 전 현재 송배전이용요금·부가정산금으로 구매자 실효 단가 확정, 법 변경 재협상 조항", "Fix the buyer's all-in price with current T&D tariffs and settlements before signing; change-in-law reopener")],
              [self.T("발전량 부족", "Output shortfall"), self.T("P90 기준 대출 sizing · 출력제한 보상 조항", "P90 debt sizing · curtailment compensation")],
              [self.T("SMP 하락(해지 후)", "SMP fall (after termination)"), self.T("해지 시 재계약 우선권 · 한전 계약시장 재입찰 가능성 검토", "Re-contracting rights · re-bidding into the KEPCO market")],
              [self.T("제도 변경", "Policy change"), self.T("시행 전 허가 + 고시 인정 시 REC 유지 가능(부칙 제3조③) — 이 자산은 2027년 이후 허가 가정이라 해당 없음, 허가 시점·고시 확인",
                                                           "Pre-act licence + recognition by notice keeps RECs (addendum art. 3(3)) — not this plant (licensed after 2027 by assumption); check licence date and the notice")]]
        c3 = Cell(title=self.T("위험과 완화책", "Risks and mitigants"), src=["ksj"],
                  table=TableSpec([self.T("위험", "Risk"), self.T("완화책", "Mitigant")], rr, [0.30, 0.70], ["L", "L"], font_size=8.2))
        ts = [[self.T("기간", "Term"), self.T(f"{f.market.ppa_term}년 (임대 계약과 맞춤)", f"{f.market.ppa_term} yrs (aligned with leases)")],
              [self.T("가격", "Price"), self.T(f"{max(f.ppa_mid, p1['price']):,.1f}원/kWh 이상 고정 (연 해지 {self.pct(self.mc_h, 0)} 손익분기 {p1['price']:,.1f}" + (f", 회랑 중간 {f.ppa_mid:,.1f}은 미달)" if f.ppa_mid < p1["price"] else ")"),
                                              f"At least KRW {max(f.ppa_mid, p1['price']):,.1f}/kWh fixed ({self.pct(self.mc_h, 0)} break-even {p1['price']:,.1f}" + (f"; corridor mid {f.ppa_mid:,.1f} falls short)" if f.ppa_mid < p1["price"] else ")"))],
              [self.T("물량", "Volume"), self.T("발전량 전량 (pay-as-produced)", "All output (pay-as-produced)")],
              [self.T("해지 위약금", "Termination"), self.T("잔여 기간 (PPA − SMP) 현재가치의 일정 비율", "A share of the PV of (PPA − SMP) over the remaining term")],
              [self.T("신용보강", "Credit support"), self.T("모회사 보증 또는 연간 대금 1년분 신용장", "Parent guarantee or a one-year LC")],
              [self.T("환경가치", "Attributes"), self.T("재생에너지 사용 확인서 구매자 귀속 — 구매자가 이 가치로 회피 요금과의 차이를 메워야 성립", "Renewable certificates to the buyer — their value must bridge the gap to the buyer's saving")]]
        c4 = Cell(title=self.T("PPA 텀시트 (예시)", "PPA term sheet (illustrative)"), src=["ksj"],
                  table=TableSpec([self.T("조항", "Clause"), self.T("제안", "Proposal")], ts, [0.24, 0.76], ["L", "L"], font_size=8.2),
                  note=self.T("예시 조건 — 실제 계약 조건이 아니다", "Illustrative terms, not an actual contract"))
        kpx = f.V("kpx_ancillary")
        need, base_ = (self.wtp_need(p1, kpx, False), self.T("부가정산금만 반영", "KPX settlement only"))
        if need <= 0:
            need, base_ = self.wtp_need(p1, self.net_ex()), self.T(f"공개 사례 망이용료 {self.net_ex():.0f}원 반영", f"with the ~{self.net_ex():.0f} public charge example")
        if self.verdict() != "ok" and need > 0:
            ta1 = self.T(f"IC 메모: 직접 PPA 지분투자 — 보류. 구매자가 RE100 가치로 kWh당 {need:,.0f}원 이상({base_}) 더 내는지 확인 전에는 한전 계약이 기본안",
                         f"IC memo: equity in a direct-PPA plant — on hold; KEPCO is the base case until the buyer is shown to pay {need:,.0f}+ per kWh for RE100 value ({base_})")
        else:
            ta1 = self.T("IC 메모: 직접 PPA 지분투자 — 조건부 검토, 부대비용 확인 전에는 승인 보류", "IC memo: equity in a direct-PPA plant — conditional; hold approval until charges are verified")
        return Page("body", "A1", ta1,
                    self.T("투자 개요 · 투자 포인트 · 위험과 완화책 · 텀시트 (예시)", "Summary · points · risks and mitigants · term sheet (illustrative)"), [c1, c2, c3, c4])

    # --- A2·A3 입력표 ---------------------------------------------------------
    def short_source(self, x) -> str:
        """입력표 출처 칸: CSV source_short(영문 source_short_en). 없으면 긴 출처 전체(자르지 않음)."""
        if self.kr:
            return x.source_short or x.source
        return x.source_short_en or x.source_en or x.source

    def a2(self, part: int) -> Page:
        f = self.f
        G = TIER_KR if self.kr else TIER_EN
        keys = list(f.inputs.keys())
        half = (len(keys) + 1) // 2
        keys = keys[:half] if part == 0 else keys[half:]
        rows, gold, brick, strong = [], set(), set(), set()
        for i, k in enumerate(keys):
            x = f.inputs[k]
            sv = x.value if self.kr or not x.value_en else x.value_en          # 문자 값은 영문 열 (영문 PDF에 한국어가 남지 않게)
            val = (sv or "TODO(data)") if isinstance(x.value, str) else (f"{x.value:,.4g}" if x.value is not None else "—")
            if k in ("cod_year", "solar_month_weights"):
                val = f"{int(float(x.value))}"
            if k == "ktb_3y":
                val = f"{f.ktb * 100:.2f}"
            rng_ = f" ({x.low:,.4g}{self.T('~', '–')}{x.high:,.4g})" if x.low is not None and x.high is not None else ""
            src = self.short_source(x)                                        # 짧은 출처만, 자르지 않는다 (긴 근거는 입력 CSV)
            unit = x.unit if self.kr or not x.unit_en else x.unit_en
            rows.append([self.lab(k), str(val) + rng_, unit, G[x.tier] + (self.T("(예정)", " (pending)") if val == "TODO(data)" else ""), src])
            if x.tier == "A":
                gold.add((i, 3))
            elif x.tier == "C":
                brick.add((i, 3))
            elif x.tier == "J":
                strong.add((i, 3))
        cnt = {t: sum(f.inputs[k].tier == t for k in f.inputs) for t in "ABCDJ"}
        cell = Cell(title=self.T(f"입력 {len(f.inputs)}개: 공식 원문 {cnt['A']} · 공식 자료 계산 {cnt['D']} · 공식 발표 보도 {cnt['B']} · 민간 2차 {cnt['C']} · 저자 판단 {cnt['J']}",
                                 f"{len(f.inputs)} inputs: official {cnt['A']} · computed from official {cnt['D']} · press report {cnt['B']} · secondary {cnt['C']} · judgement {cnt['J']}"),
                    src=["mcee", "tou", "kepco", "keei", "sec", "ksj"],
                    table=TableSpec([self.T("항목", "Item"), self.T("값 (범위)", "Value (range)"), self.T("단위", "Unit"), self.T("신뢰 등급", "Grade"), self.T("출처·근거", "Source / basis")],
                                    rows, [0.19, 0.12, 0.10, 0.11, 0.48], ["L", "R", "C", "C", "L"], gold_cells=gold, brick_cells=brick, strong_cells=strong, font_size=6.6),
                    note=self.T("신뢰 등급: 공식 원문(골드) = 정부·공공기관·법령·SEC 원문 · 공식 발표 보도 = 정부 발표를 인용한 언론(원문 대조 대기) · 민간 2차(적색) = 확정 전 교체 · 저자 판단(브라운) = 근거를 적고 민감도로 공개",
                                "Grades: official (gold) = government, public body, statute or SEC original · press report = media citing an official release · secondary (red) = replace before final · judgement (brown) = stated basis, stress-tested"))
        lab = "A2" if part == 0 else "A3"
        return Page("full", lab, self.T(f"입력과 신뢰 등급 ({part + 1}/2): 모든 숫자에 출처 등급을 붙였다", f"Inputs and source grades ({part + 1}/2): every number carries a grade"),
                    self.T("값 · 범위 · 단위 · 신뢰 등급 · 출처 (원문 링크는 저장소 입력 파일)", "Value · range · unit · grade · source (links in the repository input file)"), [cell], grid="1x1")

    # --- A4 데이터 노트·방법 --------------------------------------------------
    def a4(self) -> Page:
        f = self.f
        G = TIER_KR if self.kr else TIER_EN
        rows = []
        for k in f.provisional:
            x = f.inputs[k]
            todo = x.official_todo.replace("TODO(data):", "").strip() if self.kr else (x.official_todo_en or x.official_todo.replace("TODO(data):", "")).strip()
            empty = isinstance(x.value, str) and not x.value.strip()    # 값 자체가 원문 대기(예: 기반기금 요율) → 등급은 '예정'
            rows.append([self.lab(k), G[x.tier] + (self.T("(예정)", " (pending)") if empty else ""), todo])
        c1 = Cell(title=self.T(f"공식 원문으로 교체 대기 {len(rows)}개: 확정 전 모두 원자료로 바꾼다", f"{len(rows)} inputs awaiting official sources — all replaced before final"),
                  src=["ksj"], table=TableSpec([self.T("항목", "Item"), self.T("지금 등급", "Current grade"), self.T("교체할 공식 원문", "Official source to use")], rows,
                                              [0.22, 0.16, 0.62], ["L", "C", "L"], font_size=7.4),
                  strip=self.T(self.BUILT_WITH_KR, self.BUILT_WITH_EN),
                  note=self.T(f"원칙: 보고서 숫자는 공식 원문(정부·공공기관·법령·SEC) 우선 · 언론은 공식 발표를 인용한 경우만 · 민간 자료는 잠정으로만. 전체 코드·링크: GitHub {self.cfg['research']['repo_url']}",
                              f"Rule: official originals first (government, public bodies, statutes, SEC) · media only when citing an official release · private data provisional only. Code and links: GitHub {self.cfg['research']['repo_url']}"))
        t = self.tc
        p1 = self.prem(self.mc_h)
        lab = {"opt1": self.T("계약종별: 고압A 선택Ⅰ", "Class: HV-A option I"), "opt3": self.T("계약종별: 고압A 선택Ⅲ", "Class: HV-A option III"),
               "hvb": self.T("계약종별: 고압B 선택Ⅱ", "Class: HV-B option II"), "sat_mid": self.T("토요일 최대부하 → 중간부하", "Saturday peak → mid-peak"),
               "no_discount": self.T("봄·가을 주말 할인 종료(2031년~)", "Spring/autumn weekend discount ends (2031+)"),
               "before": self.T("참고: 개편 전 요금(2026-04-15까지)", "Ref.: pre-reform rates (to 15 Apr 2026)")}
        ad = float(t["adder"])
        rp = lambda x: self.sg(x - p1["price"], 1, True) if x is not None else "TODO"  # noqa: E731
        stage_lab = {"energy": self.T("① 에너지요금만", "① Energy rate only"), "fuel": self.T("② + 연료비조정(보도 B)", "② + fuel adjustment (press B)"),
                     "climate": self.T("③ + 기후환경요금" + ("(한전ON, 공식 원문) = PPA 가격 상한" if self.stage_val("climate") is not None else "(원문 대기)"),
                                       "③ + climate (official) = price cap" if self.stage_val("climate") is not None else "③ + climate (pending)"),
                     "fund": self.T(f"④ 회피 요금에 기반기금 포함 시(× {1 + (t.get('fund_rate') or 0):g}, 시행령 제36조) = 망이용료 여유 기준",
                                    f"④ + fund levy (× {1 + (t.get('fund_rate') or 0):g}) = room basis")}
        g_ = 1 + (t.get("fund_rate") or 0.0)
        rq = lambda x: self.sg(x * g_ - p1["price"], 1, True)  # noqa: E731  민감도 여유 = ④ 기준(기반기금 포함)
        srows = [[stage_lab[k], f"{v:,.1f}" if v is not None else "TODO", rp(v)] for k, v in t["stages"]]
        nst = len(srows)
        srows += [[self.T(f"하루 발전 형상 p = {p:g}", f"Daily shape p = {p:g}"), f"{x + ad:,.1f}", rq(x + ad)]
                  for p, x in t["shape"].items() if abs(p - f.V("solar_shape_p")) > 1e-9]
        srows += [[lab.get(k, k), f"{x + ad:,.1f}", rq(x + ad)] for k, x in t["sens"].items()]
        cur = [x + ad for k, x in t["sens"].items() if k != "before"] + [x + ad for x in t["shape"].values()]     # 개편 전은 참고라 범위에서 제외
        base_row = [k for k, _ in t["stages"]].index("climate")                       # PPA 가격 상한(회랑)
        room_row = max(i for i, (k, v) in enumerate(t["stages"]) if v is not None)     # 망이용료 여유 기준(④, 없으면 ③)
        c2 = Cell(title=self.T(f"구매자 상한 {nst}단과 민감도: {self.stage_text()} · 민감도 {min(cur):,.1f}~{max(cur):,.1f}원 — 계약종별이 하루 형상보다 크게 움직인다",
                               f"Buyer ceiling, {nst} stages: {self.stage_text()} · sensitivities {min(cur):,.1f}–{max(cur):,.1f}, led by tariff class"),
                  src=["tou", "solar", "kepco_fuel", "sfoc", "notice", "decree", "kimchang", "ksj"],
                  table=TableSpec([self.T("가정", "Assumption"), self.T("연간 회피 요금 (원/kWh)", "Annual saving (KRW/kWh)"),
                                   self.T(f"망이용료 여유 (필요 PPA {p1['price']:,.1f} 대비)", f"Room (vs required {p1['price']:,.1f})")],
                                  srows, [0.56, 0.22, 0.22], ["L", "R", "R"], shade_rows=set(range(nst)), gold_cells={(base_row, 1), (room_row, 2)}, font_size=7.4),
                  note=self.T(f"①~③ = 기준 가정(고압A 선택Ⅱ · 형상 p = {f.V('solar_shape_p'):g} · 토요일 평일 시간대)에서 kWh당 추가 요금을 차례로 더한 값, ④ = ③ × (1 + 기반기금 {self.fund_pct()}). 골드 = PPA 가격 상한(③)과 보고서 망이용료 여유(④). 아래 민감도는 추가 요금({ad:,.1f}원)을 포함한 회피 요금, 여유는 ④ 기준(× (1 + {self.fund_pct()}) − 필요 PPA), 한 번에 한 가정만 바꿈. "
                              f"필요 PPA = 연 해지 {self.pct(self.mc_h, 0)}·스프레드 0. " + self.fuel_cap_text() + self.net_basis_note(),
                              f"①–③ = base assumptions (HV-A option II · shape p = {f.V('solar_shape_p'):g} · Saturday as weekday) adding per-kWh charges in turn; ④ = ③ × (1 + {self.fund_pct()} fund levy). Gold = PPA price ceiling (③) and the room used (④). Sensitivities show the avoided rate with add-ons ({ad:,.1f}); room on the ④ basis (× (1 + {self.fund_pct()}) − required PPA), one assumption at a time. "
                              f"Required PPA at {self.pct(self.mc_h, 0)} termination, no spread. " + self.fuel_cap_text() + self.net_basis_note()))
        return Page("full", "A4", self.T("데이터 노트: 공신력 원칙 — 공식 원문 우선, 나머지는 교체 대기로 표시", "Data notes: official sources first; everything else flagged for replacement"),
                    self.T(f"기준일 {f.as_of} · 국고채 3년 {self.pct(f.ktb, 2)}({f.ktb_date}) · 모델: 연 단위 명목, 금액 억원, 가격 원/kWh",
                           f"As of {f.as_of} · KTB 3-yr {self.pct(f.ktb, 2)} ({f.ktb_date}) · annual nominal model, KRW 100mn, KRW/kWh"), [c1, c2], grid="2x1")

    def a5(self) -> Page:
        terms = [
            ("PPA", self.T("전력구매계약 — 발전사와 구매자가 가격·기간·물량을 정해 직접 사고파는 계약", "Power purchase agreement — seller and buyer fix price, term and volume directly")),
            ("CfD", self.T("차액계약 — 계약가와 시장가(SMP)의 차이를 정산. 2027년부터 한전과의 장기 고정가 계약", "Contract for difference — settles contract vs market price; from 2027, long-term contracts with KEPCO")),
            ("SMP", self.T("계통한계가격 — 전력시장의 시간별 도매가격", "System marginal price — Korea's hourly wholesale power price")),
            ("REC", self.T(f"신재생에너지 공급인증서 — RPS 의무 이행용 인증서. 발급기한 2026-12-31, REC 조항 {self.rec_end()}년 말 효력 종료 · 기존 발급자·고시 인정자는 종전 규정 유지(재생에너지법 부칙 제2·3조)",
                           f"Renewable energy certificate under RPS. Issuance deadline 31 Dec 2026; REC article lapses end-{self.rec_end()}; existing holders and recognised licensees keep the former rules (RE Act addendum arts. 2–3)")),
            ("RPS", self.T("신재생에너지 공급의무화 제도 — 2027년부터 신규 설비는 계약시장제도(제12조의14) 중심", "Renewable portfolio standard — from 2027 new plants go through the contract market (art. 12-14)")),
            ("LCOE", self.T("균등화발전비용 — 수명 동안 비용 현재가치 ÷ 발전량 현재가치", "Levelised cost of electricity — PV of lifetime costs ÷ PV of output")),
            (self.T("망이용료", "Network charges"), self.T("직접 PPA 구매자가 한전에 내는 송배전망 이용 요금과 부가 비용", "Transmission and distribution charges a direct-PPA buyer pays KEPCO")),
            (self.T("오프테이커", "Offtaker"), self.T("전력을 사는 계약 상대방 (이번 편: 데이터센터 SPV)", "The buyer under the contract (here the data-centre SPV)")),
            ("DSCR", self.T("원리금상환비율 = CFADS ÷ 원리금", "Debt service coverage = CFADS ÷ debt service")),
            (self.T("Sculpting", "Sculpting"), self.T("매년 DSCR이 목표와 같도록 원리금을 현금흐름에 맞춰 설계", "Shaping debt service so each year's DSCR equals the target")),
            (self.T("지분 IRR · MOIC", "Equity IRR · MOIC"), self.T("지분 투자 수익률 · 회수 배수(총분배 ÷ 투자)", "Return on equity · multiple of invested capital")),
            (self.T("해지 확률", "Termination rate"), self.T("PPA 기간 중 매년 계약이 끊길 확률(이번 편: 격자로 제시)", "Annual chance the PPA ends early (shown as a grid)")),
            (self.T("가격 회랑", "Price corridor"), self.T("발전사의 대안(한전 계약가)과 구매자의 대안(태양광 시간대 한전 전력량요금) 사이 범위", "Range between the seller's (KEPCO contract) and buyer's (solar-hour KEPCO energy rate) outside options")),
            (self.T("회피 요금", "Avoided rate"), self.T("PPA 전력 1kWh가 대신하는 한전 요금 — 태양광 발전 시간의 계절·시간대별 전력량요금(발전량 가중) + kWh당 추가 요금(연료비조정·기후환경). 기본요금 제외", "The KEPCO rate a PPA kWh replaces — time-of-use energy rates in solar hours (output-weighted) plus per-kWh add-ons (fuel adjustment, climate charge); no demand charge")),
            (self.T("pay-as-produced", "Pay-as-produced"), self.T("발전한 만큼만 판매 — 24시간 공급 의무 없음", "Sell what is produced — no 24/7 obligation")),
            (self.T("신뢰 등급", "Source grade"), self.T("공식 원문 · 공식 자료 계산 · 공식 발표 보도 · 민간 2차 · 저자 판단", "Official · computed from official data · press report of official release · secondary · judgement")),
        ]
        cell = Cell(title=self.T("용어 정의", "Glossary"),
                    table=TableSpec([self.T("용어", "Term"), self.T("정의", "Definition")], [list(t) for t in terms], [0.20, 0.80], ["L", "L"], shade_rows={0, 1, 6}, font_size=8.2),
                    note=self.T("음영 = 이번 편 핵심 용어", "Shaded = core terms"))
        return Page("full", "A5", self.T("용어 정의: 전기를 사고파는 말", "Glossary: the language of buying and selling power"),
                    self.T("가격 원/kWh · 금액 억원 · 미국 USD/MWh", "Prices KRW/kWh · amounts KRW 100mn · U.S. USD/MWh"), [cell], grid="1x1")
