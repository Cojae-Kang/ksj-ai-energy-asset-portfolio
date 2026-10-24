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
        return f"{v * 100:+.{d}f}%" if sign else f"{v * 100:.{d}f}%"

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
            "reform": self.T("파이낸셜뉴스(2026-09-15, 기후에너지환경부 발표 인용): 재생에너지법 개정·계약시장 전환",
                             "Financial News (15 Sep 2026, citing the ministry): Renewable Energy Act reform"),
            "kepco": self.T("한전 전력통계월보 제566호(2025.12) 표 18·18-2(계약종별 판매전력량·판매수입)", "KEPCO Monthly Statistics no.566 (Dec 2025), tables 18 and 18-2"),
            "keei": self.T("에너지경제연구원 기본연구 25-04(2025): 태양광 설치비용 영향요인 실증 연구 — LCOE·이용률·WACC·설치비", "KEEI Basic Research 25-04 (2025): solar installation costs — LCOE, capacity factor, WACC, unit cost"),
            "smp": self.T("전력거래소 EPSIS 계통한계가격(월별 가중평균·시간별, 육지)", "KPX EPSIS system marginal price (monthly weighted and hourly, mainland)"),
            "ecos": self.T("한국은행 ECOS 국고채 3년·원/달러", "Bank of Korea ECOS KTB 3-yr, USD/KRW"),
            "nrel": self.T("NREL Jordan & Kurtz(2012), PV 열화율 리뷰", "NREL Jordan & Kurtz (2012), PV degradation review"),
            "sec": self.T("Talen Energy 8-K(2025-06-11, SEC EDGAR)", "Talen Energy Form 8-K (11 Jun 2025, SEC EDGAR)"),
            "levelten": self.T("TaiyangNews(2026-07-23, LevelTen 2026년 2분기 보고서 인용)", "TaiyangNews (23 Jul 2026, citing LevelTen Q2 2026)"),
            "dist": self.T("헤럴드K(2026-05-09) · 한국경제(2026-02-03): 분산에너지·AI 데이터센터 특별법", "Herald K (9 May 2026) · Hankyung (3 Feb 2026): distributed energy, AI data-centre act"),
            "law": self.T("법인세법 제55조 · 지방세법(국가법령정보센터)", "Corporate Tax Act art. 55 · Local Tax Act (law.go.kr)"),
            "vol2": self.T("KSJ Research Vol.2(2026.10)", "KSJ Research Vol.2 (Oct 2026)"),
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
                    subtitle=self.v["subtitle_kr"] if self.kr else self.v["subtitle_en"],
                    extra={"kicker": "Research Note Vol.4", "author": self.cfg["research"]["author"], "date": self.v["date_label"],
                           "note": self.T("KSJ Research · 교육·연구 목적 · 투자 권유 아님 · 발전자산은 가상 자산",
                                          "KSJ Research · For education and research only · Not investment advice · Hypothetical asset")})

    def back(self) -> Page:
        items = [
            self.T("이 자료는 교육·연구 목적의 개인 포트폴리오이며, 투자 권유나 특정 자산·종목에 대한 의견이 아니다.",
                   "This is a personal portfolio for education and research. It is not investment advice or a view on any asset or security."),
            self.T("태양광 100MW 발전자산과 데이터센터 오프테이커는 가상 사례다. 실제 계약 가격·조건이 아니다.",
                   "The 100 MW solar asset and the data-centre offtaker are hypothetical; no actual contract prices or terms are shown."),
            self.T("본문의 판단은 저자 개인의 견해이며, 저자가 속했거나 속할 어떤 기관의 견해도 대변하지 않는다.",
                   "Views are the author's own and do not represent any current or future employer."),
            self.T("모든 입력에 신뢰 등급(공식 원문 · 공식 발표 보도 · 민간 2차 · 저자 판단)을 붙였다. 목록과 출처는 Appendix A2~A4에 있다.",
                   "Every input carries a source grade (official · press report of official release · secondary · judgement); see Appendix A2–A4."),
            self.T(f"기준일 {self.f.as_of}. 계산 방법과 코드는 저장소에서 재현할 수 있다.",
                   f"As of {self.f.as_of}. Methods and code can be reproduced from the repository."),
        ]
        from research.disclosures import contact_line, license_items
        items += license_items(self.cfg, self.kr)
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"],
                                                         "contact": contact_line(self.cfg)})

    # --- 요약 ----------------------------------------------------------------
    def headline(self) -> str:
        p1 = self.prem(self.mc_h)
        return self.T(f"데이터센터 직접 PPA는 한전 계약보다 kWh당 {p1['premium']:.0f}원만 더 받으면 된다 — 거래를 막는 건 가격이 아니라 망이용료",
                      f"A direct PPA needs only KRW {p1['premium']:.0f}/kWh over the KEPCO contract — network charges, not price, decide the deal")

    def exec_conclusions(self) -> list[str]:
        return [self.headline()] + [b.title for b in self.boxes()]

    def boxes(self) -> list[BigBox]:
        f, irr = self.f, self.irr
        p1, p5 = self.prem(self.mc_h), self.prem(max(self.v["hazards"]))
        b1 = BigBox(self.pct(irr["ppa"]), self.T(f"지분 IRR · 직접 PPA (회랑 중간 {self.kwh(f.ppa_mid)})", f"Equity IRR · direct PPA (corridor mid {self.kwh(f.ppa_mid)})"),
                    self.T(f"같은 발전소, 파는 곳만 다르면 지분 IRR {self.pct(irr['merchant'])} → {self.pct(irr['cfd'])} → {self.pct(irr['ppa'])}",
                           f"Same plant, different buyer: equity IRR {self.pct(irr['merchant'])} → {self.pct(irr['cfd'])} → {self.pct(irr['ppa'])}"),
                    [self.T(f"한전 계약: 입찰 상한 {self.kwh(f.market.cfd_price)} 20년 고정 → 대출 {self.pct(f.base['cfd'].gearing, 0)}, 지분 IRR {self.pct(irr['cfd'])}",
                            f"KEPCO contract: auction cap {self.kwh(f.market.cfd_price)} for 20 years → gearing {self.pct(f.base['cfd'].gearing, 0)}, equity IRR {self.pct(irr['cfd'])}"),
                     self.T(f"시장 판매: SMP {self.kwh(f.market.smp0, 1)}(최근 12개월 육지 평균), 2027년 이후 신규 사업자는 REC 없음 → {self.pct(irr['merchant'])}",
                            f"Merchant: SMP {self.kwh(f.market.smp0, 1)} (12-month mainland average), no RECs for post-2027 entrants → {self.pct(irr['merchant'])}"),
                     self.T(f"사업비는 에너지경제연구원 LCOE {f.V('lcoe_target'):.1f}원에 맞춘 값 — 2022년 실제 설치비 기준이면 한전 계약 IRR {self.pct(f.lcoe_check['actual_irr']['cfd'])}",
                            f"CAPEX matched to KEEI's {f.V('lcoe_target'):.1f} LCOE — at 2022 actual installed cost the KEPCO IRR would be {self.pct(f.lcoe_check['actual_irr']['cfd'])}")])
        b2 = BigBox(f"+{p1['premium']:.0f}" + self.T("원", ""), self.T(f"필요 PPA 프리미엄 (연 해지 확률 {self.pct(self.mc_h, 0)}, kWh당)", f"Required PPA premium (annual termination {self.pct(self.mc_h, 0)}, per kWh)"),
                    self.T(f"한전 계약 대신 PPA를 받아들일 가격: {self.kwh(p1['price'])} (해지 없으면 {self.kwh(self.prem(0.0)['price'])})",
                           f"Price to accept a PPA instead of KEPCO: {self.kwh(p1['price'])} ({self.kwh(self.prem(0.0)['price'])} with no termination)"),
                    [self.T("기준: 지분 NPV(요구수익률 할인) 기대값이 한전 계약과 같아지는 PPA 가격, 해지 후엔 SMP로 판매",
                            "Rule: PPA price at which expected equity NPV (at the hurdle) equals the KEPCO contract; after termination the plant sells at SMP"),
                     self.T(f"연 해지 확률 {self.pct(max(self.v['hazards']), 0)}면 +{p5['premium']:.0f}원 → {self.kwh(p5['price'])}",
                            f"At {self.pct(max(self.v['hazards']), 0)} a year: +KRW {p5['premium']:.0f} → {self.kwh(p5['price'])}"),
                     self.T("해지 확률은 공개 근거가 없어 격자(0~5%)로 제시 — 실제 딜에선 오프테이커 신용평가로 정한다",
                            "No public basis for the termination rate, so a 0–5% grid is shown; a real deal sets it from the offtaker's credit")])
        b3 = BigBox(self.kwh(p1["max_fee"], 0), self.T("데이터센터가 감당할 망이용료·부대비용 상한 (kWh당)", "Ceiling on network and ancillary charges the data centre can bear (per kWh)"),
                    self.T(f"한전 산업용 {self.kwh(f.corridor[1])} − 필요 PPA 가격 {self.kwh(p1['price'])} = 망이용료 여유 {self.kwh(p1['max_fee'])}",
                           f"KEPCO industrial {self.kwh(f.corridor[1])} − required PPA {self.kwh(p1['price'])} = room for network charges {self.kwh(p1['max_fee'])}"),
                    [self.T("직접 PPA 구매자는 발전사에 PPA 가격, 한전에 망이용료를 따로 낸다 — 합이 한전 요금을 넘으면 살 이유가 없다",
                            "A direct-PPA buyer pays the generator and, separately, KEPCO's network charges — above the tariff there is no reason to buy"),
                     self.T("망이용료 산정 방식은 공개되지 않아 기업들이 PPA를 피하는 2순위 이유(기후솔루션 설문) — 전력거래소가 개편 연구 중",
                            "Network-charge methods are not public — the No.2 reason firms avoid PPAs (SFOC survey); KPX is studying a reform"),
                     self.T("RE100 가치(녹색프리미엄 대체)는 상한을 올리고, 한전 요금 인상은 PPA 고정가의 매력을 키운다 — 보수적으로 제외",
                            "RE100 value (vs green premiums) raises the ceiling and tariff increases favour a fixed PPA — both left out to stay conservative")])
        return [b1, b2, b3]

    def executive(self) -> Page:
        f, irr = self.f, self.irr
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        p1 = self.prem(self.mc_h)
        add(self.T("가상 태양광 · 사업비 (에너지경제연구원 LCOE 기준)", "Hypothetical solar · CAPEX (KEEI LCOE basis)"),
            f"{f.asset.mw:,.0f}MW · {self.eok(f.asset.capex)}", "1")
        add(self.T("1년차 발전량 · 데이터센터 사용량 대비", "Yr-1 output · share of data-centre use"), f"{self.gwh(f.dc['solar_gwh'])} · {self.pct(f.dc['share'], 0)}", "1")
        add(self.T("가격 회랑: 한전 계약가 ~ 한전 산업용", "Price corridor: KEPCO contract ~ industrial tariff"),
            f"{f.corridor[0]:,.1f} ~ {f.corridor[1]:,.1f}" + self.T("원", ""), "3", True)
        add(self.T("지분 IRR · 한전 CfD / 직접 PPA(중간) / 시장", "Equity IRR · CfD / PPA (mid) / merchant"),
            " / ".join(self.pct(irr[k]) for k in ("cfd", "ppa", "merchant")), "4", True)
        add(self.T("MOIC · 한전 CfD / 직접 PPA / 시장", "MOIC · CfD / PPA / merchant"), " / ".join(self.x(f.base[k].moic) for k in ("cfd", "ppa", "merchant")), "4")
        add(self.T("대출 비율 · 한전 CfD / 직접 PPA / 시장", "Gearing · CfD / PPA / merchant"), " / ".join(self.pct(f.base[k].gearing, 0) for k in ("cfd", "ppa", "merchant")), "4")
        add(self.T("PPA 손익분기 가격 (해지 없음, IRR 기준)", "PPA break-even (no termination, IRR basis)"), self.kwh(f.be_price), "5")
        add(self.T(f"필요 PPA 가격 · 프리미엄 (연 해지 {self.pct(self.mc_h, 0)})", f"Required PPA price · premium ({self.pct(self.mc_h, 0)} termination)"),
            f"{p1['price']:,.1f} · +{p1['premium']:,.1f}" + self.T("원", ""), "5", True)
        add(self.T("망이용료·부대비용 상한", "Ceiling on network charges"), self.kwh(p1["max_fee"]), "5", True)
        if ok(f.mc):
            s = mc_stats(f.mc["ppa"], self.hurdle)
            add(self.T(f"몬테카를로 · 직접 PPA 지분 IRR P10 / P50", "Monte Carlo · PPA equity IRR P10 / P50"), f"{self.pct(s['p10'])} / {self.pct(s['p50'])}", "7")
            sm = mc_stats(f.mc["merchant"], self.hurdle)
            add(self.T("몬테카를로 · 시장 판매 손실 확률(IRR < 0)", "Monte Carlo · merchant loss probability (IRR < 0)"), self.pct(sm["neg"], 0), "7")
        table = TableSpec([self.T("핵심 지표", "Key metric"), self.T("값", "Value"), self.T("쪽", "p.")], rows, [0.58, 0.33, 0.09], ["L", "R", "C"],
                          shade_rows=shade, gold_cells=gold, font_size=8.2, single_line_cols={1})
        left = Cell(title=self.T("핵심 지표", "Key metrics"), src=["mcee", "kepco", "keei", "ecos", "ksj"], table=table,
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
                  chart_key="demand", chart=charts.hbars([self.T("데이터센터 연간 사용량", "Data-centre annual use"), self.T("태양광 100MW 1년차 발전량", "Solar 100 MW yr-1 output")],
                                                         [dc["consumption_gwh"], dc["solar_gwh"]], [c["brown_dark"], c["gold"]], c, lambda v: f"{v:,.1f}"),
                  note=self.T("Vol.2 한국 케이스(IT 40MW) 기준. 태양광은 낮에만 발전하므로 시간대별 부족분은 한전에서 산다" + self.prov_note(["capacity_factor"]),
                              "Vol.2 Korean case (IT 40 MW). Solar runs only by day, so the data centre still buys the rest from KEPCO" + self.prov_note(["capacity_factor"])))
        rows = [[self.T("데이터센터 IT 용량 × 부하율 × PUE", "IT capacity × load × PUE"), f"{f.V('dc_it_mw'):.0f}MW × {self.pct(f.V('dc_it_load'), 0)} × {f.V('dc_pue'):.1f}"],
                [self.T("× 8,760시간 = 연간 사용량", "× 8,760 h = annual use"), self.gwh(dc["consumption_gwh"])],
                [self.T("× 한전 산업용 판매단가(2025)", "× KEPCO industrial tariff (2025)"), self.kwh(f.corridor[1])],
                [self.T("= 연간 전력비", "= Annual power bill"), self.eok(dc["power_cost"])],
                [self.T("태양광 용량 × 이용률 × 8,760시간", "Solar MW × capacity factor × 8,760 h"), f"{f.asset.mw:.0f}MW × {self.pct(f.asset.capacity_factor, 0)}"],
                [self.T("= 1년차 발전량 (열화 연 0.5%)", "= Yr-1 output (0.5% annual degradation)"), self.gwh(dc["solar_gwh"])]]
        c2 = Cell(title=self.T(f"전력비 연 {self.eok(dc['power_cost'])}: Vol.2에서 임차인에게 별도 청구한 그 비용", f"Power bill {self.eok(dc['power_cost'])} a year — the cost Vol.2 passed to tenants"),
                  src=["vol2", "kepco", "nrel", "ksj"],
                  table=TableSpec([self.T("계산", "Step"), self.T("값", "Value")], rows, [0.62, 0.38], ["L", "R"], shade_rows={3, 5}, gold_cells={(3, 1), (5, 1)}, font_size=8.4),
                  note=self.T("한전 산업용 판매단가는 평균값(계약종별·시간대별 요금 차이 미반영)" + self.prov_note(["kepco_industrial_price", "capacity_factor"]),
                              "Average industrial tariff (no tariff-class or time-of-use detail)" + self.prov_note(["kepco_industrial_price", "capacity_factor"])))
        c3 = Cell(title=self.T("질문: 같은 전기를 한전 대신 데이터센터에 팔면, 더 받는 값이 위험을 보상하나", "Question: if the plant sells to the data centre instead of KEPCO, does the extra price pay for the risk?"),
                  src=["vol2", "ksj"], panel_lead=self.T("지분 투자자의 세 갈래", "An equity investor's three routes"),
                  bullets=[self.T("① 한전 계약(CfD): 2027년부터 신규 태양광의 표준. 20년 고정가, 상대방은 한전", "① KEPCO contract (CfD): standard for new solar from 2027; 20-yr fixed price, KEPCO as counterparty"),
                           self.T("② 데이터센터 직접 PPA: 협상 가격, 상대방은 Vol.2의 데이터센터 SPV", "② Direct PPA: negotiated price; counterparty is Vol.2's data-centre SPV"),
                           self.T("③ 시장 판매(SMP): 가격 변동을 그대로 진다. 신규 사업자는 REC 없음", "③ Merchant (SMP): full price risk; no RECs for new entrants"),
                           self.T("Vol.2는 대주(돈 빌려주는 쪽), Vol.3는 ECM(공모가)의 눈 — 이번 편은 지분 투자자의 눈", "Vol.2 took the lender's view, Vol.3 the ECM view — this note takes the equity investor's")])
        steps = [(self.T("1. 가격 근거", "1. Price evidence"), [self.T("한전 계약가", "KEPCO price"), self.T("한전 산업용", "Industrial tariff"), "SMP · LCOE", self.T("신뢰 등급", "Source grade")]),
                 (self.T("2. 현금흐름", "2. Cash flows"), [self.T("경로 3개", "3 routes"), self.T("법인세·감가", "Tax, depreciation"), self.T("DSCR sculpting", "DSCR sculpting"), self.T("지분 IRR·MOIC", "Equity IRR, MOIC")]),
                 (self.T("3. 손익분기", "3. Break-evens"), [self.T("PPA 가격", "PPA price"), self.T("해지 확률", "Termination rate"), self.T("망이용료 상한", "Network-charge cap"), self.T("해지 시점", "Termination year")]),
                 (self.T("4. 검증·IC", "4. Checks, IC"), [self.T("몬테카를로", "Monte Carlo"), self.T("민감도", "Sensitivity"), self.T("IC 메모", "IC memo"), self.T("국문·영문", "Korean & English")])]
        c4 = Cell(title=self.T("분석 구조: 가격 근거 → 현금흐름 → 손익분기 → 검증·IC 메모", "Structure: prices → cash flows → break-evens → checks and IC memo"), src=["ksj"],
                  chart_key="flow", chart=charts.flow4(steps, c))
        return Page("body", "1", self.T(f"출발점: 데이터센터 40MW의 전력비 연 {self.eok(dc['power_cost'])} — 태양광 100MW가 그 {self.pct(dc['share'], 0)}를 댈 수 있다",
                                        f"Starting point: a 40 MW data centre's power bill is {self.eok(dc['power_cost'])} a year — 100 MW of solar can cover {self.pct(dc['share'], 0)}"),
                    self.T("Vol.2 데이터센터(대주의 눈) → Vol.4 그 데이터센터에 전기를 파는 발전자산(지분 투자자의 눈)",
                           "Vol.2 data centre (lender's view) → Vol.4 the plant that sells it power (equity investor's view)"), [c1, c2, c3, c4])

    # --- p2 ------------------------------------------------------------------
    def p2(self) -> Page:
        f = self.f
        G = TIER_KR if self.kr else TIER_EN
        tl = [
            ["2026-02-03", self.T("분산에너지특화지역 추진단: 산단 구역전기 이용 기업도 재생에너지 PPA 허용 방침, 구역전기 35MW 한도 완화 검토", "Distributed-energy zones: firms on local grids to be allowed renewable PPAs; 35 MW cap under review"), G["B"]],
            ["2026-05-07", self.T("AI 데이터센터 특별법 본회의 통과 — 업계가 요청한 LNG 발전 직접 PPA 특례는 제외", "AI Data Centre Act passed — the requested LNG direct-PPA carve-out was dropped"), G["B"]],
            ["2026-05", self.T("분산에너지 설비 원칙상 40MW 이하 — 대형 데이터센터 직접 공급 특례안은 국회 계류(정부 부정적)", "Distributed resources capped at 40 MW in principle; a data-centre carve-out bill is pending (ministry opposed)"), G["B"]],
            ["2026-07-16", self.T(f"2026년 1차 태양광 경쟁입찰 공고: 상한 {self.kwh(f.market.cfd_price, 3)}(전년 대비 약 5% 하향), 약 1,000MW", f"2026 round-1 solar auction: cap {self.kwh(f.market.cfd_price, 3)} (about 5% lower), ~1,000 MW"), G["A"]],
            ["2026-09-15", self.T("재생에너지법 개정 공포 — RPS 폐지, 한전과 장기 고정가 계약시장으로 일원화", "Renewable Energy Act amended — RPS ends; a single long-term contract market with KEPCO"), G["B"]],
            ["2027-01-01", self.T("시행 — 신규 사업자 REC 발급 제한, REC 현물시장은 2029년 말까지", "Effective — RECs restricted for new entrants; REC spot market until end-2029"), G["B"]],
        ]
        c1 = Cell(title=self.T("제도 타임라인: 2027년부터 한전 장기계약이 기본값, 직접 PPA는 선택지", "Timeline: from 2027 a KEPCO long-term contract is the default, a direct PPA the alternative"),
                  src=["mcee", "reform", "dist"],
                  table=TableSpec([self.T("날짜", "Date"), self.T("내용", "Change"), self.T("신뢰 등급", "Grade")], tl, [0.12, 0.72, 0.16], ["C", "L", "C"],
                                  gold_cells={(3, 2)}, shade_rows={3, 4}, font_size=8.0),
                  note=self.T("신뢰 등급: 공식 원문 = 정부 보도자료 원문 확인 · 공식 발표 보도 = 정부 발표를 인용한 언론 보도(원문 대조 대기, A4 목록)",
                              "Grades: official = government release checked · press report = media citing a government release (to be matched to the original, list in A4)"))
        d = f.debts
        rows = [[self.T("가격", "Price"), self.T(f"입찰가 20년 고정 (상한 {f.market.cfd_price:,.1f})", f"Auction price fixed 20 yrs (cap {f.market.cfd_price:,.1f})"),
                 self.T("한전 계약가 ~ 한전 산업용 사이 협상", "Negotiated between KEPCO price and tariff"), self.T("SMP 변동 (REC 없음)", "SMP (no RECs)")],
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
                    self.T("RPS 폐지 · 계약시장 · 분산에너지 한도 · AI 데이터센터 특별법 → 지분 투자자의 선택지 3개", "RPS repeal · contract market · distributed-energy cap · AI data-centre act → three routes"),
                    [c1, c2], grid="2x1")

    # --- p3 ------------------------------------------------------------------
    def p3(self) -> Page:
        f, c = self.f, self.c
        p1 = self.prem(self.mc_h)
        lo, hi = f.corridor
        lc = f.inputs["lcoe_target"]
        pts = [(self.T("시장 SMP (최근 12개월)", "Merchant SMP (12 months)"), f.market.smp0, c["warm_grey"]),
               (self.T("한전 계약가 (입찰 상한)", "KEPCO contract (cap)"), lo, c["brown_dark"]),
               (self.T(f"필요 PPA (연 해지 {self.pct(self.mc_h, 0)})", f"Required PPA ({self.pct(self.mc_h, 0)} term.)"), p1["price"], c["gold"]),
               (self.T("PPA 회랑 중간", "Corridor mid"), f.ppa_mid, c["brown_mid"]),
               (self.T("한전 산업용 판매단가", "KEPCO industrial tariff"), hi, c["brick"])]
        c1 = Cell(title=self.T(f"가격 회랑 {lo:,.1f}~{hi:,.1f}원: 그 사이 {hi - lo:,.1f}원이 PPA 가격과 망이용료가 나눠 가질 몫",
                               f"Corridor KRW {lo:,.1f}–{hi:,.1f}: the {hi - lo:,.1f} between is split by the PPA price and network charges"),
                  src=["mcee", "kepco", "keei", "smp", "ksj"], unit=self.T("원/kWh", "KRW/kWh"),
                  legend=[(c["warm_grey_light"], self.T(f"태양광 LCOE {lc.low:.0f}~{lc.high:.0f}", f"Solar LCOE {lc.low:.0f}–{lc.high:.0f}"))],
                  chart_key="corridor",
                  chart=charts.corridor(pts, [("LCOE", lc.low, lc.high, c["warm_grey_light"], 0.45)], c, lambda v: f"{v:,.1f}", (80, 200),
                                        gap=(p1["price"], hi, self.T(f"망이용료 여유 {p1['max_fee']:.0f}원", f"room {p1['max_fee']:.0f}"))),
                  note=self.T("한전 계약가 = 2026년 1차 입찰 상한(낙찰 평균은 공단 결과 공고로 교체 예정). LCOE는 2024년 말 연구 범위" + self.prov_note(["smp_base", "kepco_industrial_price", "lcoe_target"]),
                              "KEPCO price = 2026 round-1 cap (to be replaced by the KEA average award). LCOE = late-2024 study range" + self.prov_note(["smp_base", "kepco_industrial_price", "lcoe_target"])))
        G = TIER_KR if self.kr else TIER_EN
        I = f.inputs
        rows = []
        for k in ("cfd_price", "kepco_industrial_price", "lcoe_target", "smp_base"):
            x = I[k]
            val = f"{float(x.value):,.1f}" + (f" ({x.low:,.0f}~{x.high:,.0f})" if x.low is not None and x.high is not None else "")
            rows.append([self.lab(k), val, G[x.tier], x.published or "—"])
        na = sum(I[k].tier == "A" for k in ("cfd_price", "kepco_industrial_price", "lcoe_target", "smp_base"))
        c2 = Cell(title=self.T(f"가격 근거와 신뢰 등급: 4개 중 {na}개가 공식 원문 — 정부 보도자료·한전 통계·전력거래소·에너지경제연구원", f"Price evidence: {na} of 4 from official originals — ministry, KEPCO, KPX, KEEI"),
                  src=["mcee", "kepco", "keei", "smp"],
                  table=TableSpec([self.T("항목 (원/kWh)", "Item (KRW/kWh)"), self.T("값 (범위)", "Value (range)"), self.T("신뢰 등급", "Grade"), self.T("발표", "Published")],
                                  rows, [0.42, 0.22, 0.20, 0.16], ["L", "R", "C", "C"], gold_cells={(0, 2)}, brick_cells={(3, 2)}, font_size=8.4),
                  note=self.T("한전 판매단가 = 2025년 산업용 판매수입 ÷ 판매전력량 · SMP = 2025-09~2026-08 월별 육지 가중평균의 평균(시간별 10~16시 평균으로 교차 확인) · LCOE = 2024년 국내 범위",
                              "Tariff = 2025 industrial revenue ÷ volume · SMP = mean of monthly mainland SMP, Sep 2025–Aug 2026 (cross-checked with 10:00–16:00 hourly) · LCOE = 2024 Korean range"))
        fx = self.fx()
        us = f.us
        rows_us = [[self.T("Talen–AWS 원전 PPA (17년, 1,920MW)", "Talen–AWS nuclear PPA (17 yrs, 1,920 MW)"), f"≥ {us['talen_floor']:,.0f}", G["A"]],
                   [self.T("LevelTen 북미 태양광 PPA 평균 (2026 2Q)", "LevelTen N. America solar PPA avg (Q2 2026)"), f"{us['levelten']:,.1f}", G["B"]]]
        if fx:
            rows_us += [[self.T(f"참고: 한국 한전 계약가 (원/달러 {fx[0]:,.1f})", f"Ref.: Korea KEPCO price (USD/KRW {fx[0]:,.1f})"), f"{lo * 1000 / fx[0]:,.0f}", G["A"]],
                        [self.T("참고: 한국 산업용 판매단가", "Ref.: Korea industrial tariff"), f"{hi * 1000 / fx[0]:,.0f}", G["B"]]]
        c3 = Cell(title=self.T(f"미국 비교: 하이퍼스케일러 원전 PPA 최소 ${us['talen_floor']:,.0f}/MWh — 한국 태양광 계약가가 더 비싸다",
                               f"U.S. check: hyperscaler nuclear PPA at least ${us['talen_floor']:,.0f}/MWh — Korean solar contracts cost more"),
                  src=["sec", "levelten", "ecos"],
                  table=TableSpec([self.T("항목", "Item"), "USD/MWh", self.T("신뢰 등급", "Grade")], rows_us, [0.60, 0.18, 0.22], ["L", "R", "C"], gold_cells={(0, 1)}, font_size=8.4),
                  note=self.T("Talen: 명목 매출 약 180억 달러 ÷ (1,920MW × 8,760h × 17년) = 전량·전시간 공급 가정의 평균 단가. 실제는 2032년까지 단계 증가라 단가는 이보다 높다(하한). "
                              "Meta–Constellation 등 다른 원전 PPA는 가격 비공개", "Talen: ~USD 18bn notional ÷ (1,920 MW × 8,760 h × 17 yrs) = average price at full, round-the-clock volume; "
                              "the ramp to 2032 means the true price is higher (floor). Other nuclear PPAs (e.g. Meta–Constellation) are undisclosed"))
        c4 = Cell(title=self.T("읽는 법: 발전사의 하한은 한전 계약, 구매자의 상한은 한전 요금", "How to read it: the seller's floor is KEPCO's contract, the buyer's ceiling KEPCO's tariff"),
                  src=["ksj"], panel_lead=self.T("PPA 가격은 두 대안 사이에서 정해진다", "A PPA price lives between two outside options"),
                  bullets=[self.T(f"발전사: 한전 계약({lo:,.1f}원)보다 위험이 큰 만큼 더 받아야 한다 → 하한 + 위험 프리미엄", f"Seller: needs more than KEPCO ({lo:,.1f}) for extra risk → floor + risk premium"),
                           self.T(f"구매자: PPA 가격 + 망이용료가 한전 요금({hi:,.1f}원)보다 싸야 산다 → 상한 − 망이용료", f"Buyer: PPA + network charges must beat the tariff ({hi:,.1f}) → ceiling − network charges"),
                           self.T(f"시장 SMP({f.market.smp0:,.1f}원)는 한전 계약가보다 낮다 — 2027년 이후 신규 사업자에게 REC가 없어서", f"Merchant SMP ({f.market.smp0:,.1f}) sits below the KEPCO price — no RECs for post-2027 entrants"),
                           self.T("미국은 원전 24시간 전력이 $63+/MWh — 한국 PPA는 '싼 재생에너지'가 아니라 'RE100용 프리미엄 상품'", "U.S. 24/7 nuclear at $63+/MWh — a Korean PPA is an RE100 premium product, not cheap power")])
        return Page("body", "3", self.T(f"가격 회랑: 한전 계약 {lo:,.1f}원 ~ 한전 산업용 {hi:,.1f}원 — 그 사이 {hi - lo:,.1f}원이 PPA 협상 여지",
                                        f"Price corridor: KEPCO contract {lo:,.1f} to industrial tariff {hi:,.1f} — {hi - lo:,.1f} of room to negotiate a PPA"),
                    self.T("하한 = 발전사의 대안(한전 계약) · 상한 = 구매자의 대안(한전 요금) · 원가 = LCOE · 시장가 = SMP · 미국 비교", "Floor = seller's alternative · ceiling = buyer's alternative · cost = LCOE · merchant = SMP · U.S. check"),
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
        c1 = Cell(title=self.T(f"지분 IRR: 보유(25년) vs {ey}년 차 매각 — 직접 PPA가 두 방식 모두 가장 높다", f"Equity IRR: hold (25 yrs) vs sale in year {ey} — the PPA leads either way"),
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
                  note=self.T(f"사업비 {self.eok(f.asset.capex)}(kW당 {f.asset.capex * 100 / f.asset.mw:,.0f}천원, 에너지경제연구원 LCOE·WACC·이용률 기준) · 법인세 누진세율 + 지방세 10% · 정액 감가 {int(f.V('dep_years'))}년 · 대출은 목표 DSCR sculpting과 최대 대출 비율 중 작은 값",
                              f"CAPEX {self.eok(f.asset.capex)} (KRW {f.asset.capex * 100 / f.asset.mw:,.0f}k/kW, KEEI LCOE/WACC/CF basis) · progressive corporate tax + 10% local · straight-line {int(f.V('dep_years'))} yrs · debt = min(DSCR sculpting, max gearing)"))
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
        c4 = Cell(title=self.T("읽는 법: 한전 계약은 대출로 IRR을 만들고, PPA는 가격으로 만든다", "How to read it: the KEPCO route earns through leverage, the PPA through price"),
                  src=["ksj"], panel_lead=self.T("같은 발전소, 다른 자본구조", "Same plant, different capital structures"),
                  bullets=[self.T(f"한전 계약: 가격 {f.market.cfd_price:,.1f}원 vs LCOE {f.V('lcoe_target'):.1f}원, 대출 {self.pct(f.base['cfd'].gearing, 0)}로 지분 IRR {self.pct(irr['cfd'])}", f"KEPCO: price {f.market.cfd_price:,.1f} vs LCOE {f.V('lcoe_target'):.1f}, {self.pct(f.base['cfd'].gearing, 0)} debt → {self.pct(irr['cfd'])}"),
                           self.T(f"직접 PPA: 회랑 중간 가격이면 IRR {self.pct(irr['ppa'])} — 단 해지 위험이 없을 때(p5·p6)", f"PPA: {self.pct(irr['ppa'])} at the corridor mid — if nobody terminates (p5–p6)"),
                           self.T(f"시장 판매: 대주가 대출을 {self.pct(f.base['merchant'].gearing, 0)}만 해 주고 SMP도 낮아 IRR {self.pct(irr['merchant'])}", f"Merchant: lenders give only {self.pct(f.base['merchant'].gearing, 0)} and SMP is low → {self.pct(irr['merchant'])}"),
                           self.T(f"요구수익률 {self.pct(self.hurdle, 0)} 기준: {self.clear_text()} — 계약 경로끼리는 가격 차이와 해지 위험의 교환", f"Against the {self.pct(self.hurdle, 0)} hurdle: {self.clear_text()} — between contracts it is price vs termination risk")])
        return Page("body", "4", self.T(f"지분 IRR: 직접 PPA {self.pct(irr['ppa'])} · 한전 계약 {self.pct(irr['cfd'])} · 시장 {self.pct(irr['merchant'])} — 시장 판매만 요구수익률 미달",
                                        f"Equity IRR: PPA {self.pct(irr['ppa'])} · KEPCO {self.pct(irr['cfd'])} · merchant {self.pct(irr['merchant'])} — only merchant misses the hurdle"),
                    self.T("경로별 대출 sizing → 지분 IRR·MOIC → 매각 → 민감도", "Debt sizing by route → equity IRR and MOIC → exit → sensitivity"), [c1, c2, c3, c4])

    # --- p5 ------------------------------------------------------------------
    def p5(self) -> Page:
        f, c, irr = self.f, self.c, self.irr
        lo, hi = f.corridor
        xs = [p for p, _ in f.price_curve]
        ys = [v for _, v in f.price_curve]
        c1 = Cell(title=self.T(f"PPA 가격별 지분 IRR: {f.be_price:,.1f}원이면 한전 계약과 같다 — 회랑 하단에 거의 붙어 있다",
                               f"Equity IRR by PPA price: KRW {f.be_price:,.1f} matches KEPCO — almost at the corridor floor"),
                  src=["mcee", "kepco", "ksj"], unit=self.T("지분 IRR (해지 없음)", "Equity IRR (no termination)"),
                  chart_key="price_irr",
                  chart=charts.line_ref(xs, [("", ys, c["gold"])], c, lambda v: f"{v:,.0f}", lambda v: f"{v * 100:.0f}%",
                                        hlines=[(irr["cfd"], self.T(f"한전 계약 {self.pct(irr['cfd'])}", f"KEPCO {self.pct(irr['cfd'])}"), c["brown_dark"]),
                                                (self.hurdle, self.T(f"요구수익률 {self.pct(self.hurdle, 0)}", f"Hurdle {self.pct(self.hurdle, 0)}"), c["brick"])],
                                        vlines=[(f.be_price, self.T(f"손익분기 {f.be_price:,.1f}", f"B/E {f.be_price:,.1f}"), c["brown_dark"])],
                                        shade=(lo, hi, self.T("가격 회랑", "Corridor"))),
                  note=self.T("가격마다 대출을 다시 sizing(PPA 조건: DSCR·대출 비율·만기). 손익분기가 한전 계약가보다 약간 높은 이유 = PPA 대출 조건이 더 보수적"
                              + self.prov_note(["capacity_factor", "lcoe_target"]),
                              "Debt re-sized at each price (PPA terms). Break-even sits just above the KEPCO price because PPA debt terms are stricter" + self.prov_note(["capacity_factor", "lcoe_target"])))
        rows, gold = [], set()
        for i, p in enumerate(f.premium):
            rows.append([self.pct(p["hazard"], 1), self.kwh(p["price"]), f"+{p['premium']:,.1f}", f"{p['max_fee']:,.1f}"])
            if abs(p["hazard"] - self.mc_h) < 1e-12:
                gold |= {(i, 1), (i, 3)}
        c2 = Cell(title=self.T(f"해지 확률별 필요 PPA 가격: 연 {self.pct(self.mc_h, 0)}면 한전 계약보다 kWh당 약 {self.prem(self.mc_h)['premium']:.0f}원 더", f"Required PPA price by termination rate: about KRW {self.prem(self.mc_h)['premium']:.0f}/kWh over KEPCO at {self.pct(self.mc_h, 0)} a year"),
                  src=["mcee", "kepco", "ksj"],
                  table=TableSpec([self.T("연 해지 확률", "Annual termination"), self.T("필요 PPA 가격", "Required PPA"), self.T("프리미엄 (원/kWh)", "Premium (KRW/kWh)"),
                                   self.T("망이용료 상한 (원/kWh)", "Network-charge cap (KRW/kWh)")], rows, [0.22, 0.28, 0.24, 0.26], ["C", "R", "R", "R"],
                                  gold_cells=gold, shade_rows={i for i, _ in enumerate(rows) if (i, 1) in gold}, font_size=8.4),
                  note=self.T(f"필요 가격 = 지분 NPV 기대값(요구수익률 {self.pct(self.hurdle, 0)} 할인)이 한전 계약과 같아지는 PPA 가격. 해지는 PPA 기간 중 연 확률로 발생(기하분포), 해지 후 SMP 판매, 대출은 해지 없는 sizing 그대로. "
                              "망이용료 상한 = 한전 산업용 − 필요 가격",
                              f"Required price = PPA price at which expected equity NPV (at {self.pct(self.hurdle, 0)}) equals KEPCO's. Termination arrives at a constant annual rate during the PPA; "
                              "afterwards the plant sells at SMP; debt keeps its no-termination sizing. Cap = industrial tariff − required price"))
        c3 = Cell(title=self.T("망이용료 상한: 해지 확률이 오를수록 데이터센터 몫이 줄어든다", "Network-charge cap shrinks as termination risk rises"), src=["kepco", "ksj"], unit=self.T("원/kWh", "KRW/kWh"),
                  chart_key="fee", chart=charts.bars([self.pct(p["hazard"], 1) for p in f.premium], [p["max_fee"] for p in f.premium],
                                                     [c["gold"] if abs(p["hazard"] - self.mc_h) < 1e-12 else c["brown_mid"] for p in f.premium], c, lambda v: f"{v:,.1f}"),
                  note=self.T("x축 = 오프테이커 연 해지 확률. 막대 = 데이터센터가 PPA 외에 낼 수 있는 망이용료·부대비용의 최대치" + self.prov_note(["kepco_industrial_price"]),
                              "x-axis = offtaker's annual termination rate; bar = the most the data centre can pay in network and ancillary charges on top of the PPA" + self.prov_note(["kepco_industrial_price"])))
        p1 = self.prem(self.mc_h)
        c4 = Cell(title=self.T("협상의 결론: 가격은 쉽게 맞는다 — 문제는 망이용료가 공개되지 않는다는 것", "The negotiation: price is easy to agree — the problem is that network charges are opaque"),
                  src=["ksj"], panel_lead=self.T("IC가 물을 질문", "What the IC will ask"),
                  bullets=[self.T(f"회랑 폭 {hi - lo:,.1f}원 중 발전사 몫은 +{p1['premium']:,.0f}원(연 해지 {self.pct(self.mc_h, 0)}) — 나머지 {p1['max_fee']:,.0f}원은 망이용료와 구매자 절감분",
                                  f"Of the {hi - lo:,.1f} corridor the seller needs +{p1['premium']:,.0f} ({self.pct(self.mc_h, 0)} termination); the other {p1['max_fee']:,.0f} covers network charges and buyer savings"),
                           self.T("망이용료 산정 방식이 비공개 → 구매자가 상한을 모르면 계약이 성립하지 않는다", "Opaque network-charge methods → if the buyer cannot see its ceiling, no deal"),
                           self.T("실제 딜 체크: 송배전이용요금 고시 · 부가정산금 · 손실 · 대체 전력(밤 시간) 비용을 구매자 모델에 넣었나", "Deal check: transmission/distribution tariffs, ancillary settlements, losses and night-time backup power in the buyer's model"),
                           self.T("발전사 쪽 레버: 해지 위약금·보증으로 해지 확률을 낮추면 필요 프리미엄도 내려간다(p6)", "Seller's lever: termination payments and guarantees cut the effective termination rate and the premium (p6)")])
        return Page("body", "5", self.T(f"PPA 협상: 연 해지 {self.pct(self.mc_h, 0)}면 {self.kwh(p1['price'])}(+{p1['premium']:,.0f}원)로 충분 — 데이터센터 몫 망이용료 상한은 {p1['max_fee']:,.0f}원",
                                        f"PPA negotiation: at {self.pct(self.mc_h, 0)} termination {self.kwh(p1['price'])} (+{p1['premium']:,.0f}) suffices — the data centre can bear {p1['max_fee']:,.0f} in network charges"),
                    self.T("손익분기 PPA 가격(IRR) → 해지 확률별 필요 가격(NPV 기대값) → 망이용료 상한", "Break-even PPA (IRR) → required price by termination rate (expected NPV) → network-charge ceiling"),
                    [c1, c2, c3, c4])

    # --- p6 ------------------------------------------------------------------
    def p6(self) -> Page:
        f, c, irr = self.f, self.c, self.irr
        ys = [v for _, v in f.default_curve]
        yrs = [y for y, _ in f.default_curve]
        cross = next((y for y, v in f.default_curve if v is not None and v >= irr["cfd"]), None)
        cross_h = next((y for y, v in f.default_curve if v is not None and v >= self.hurdle), None)
        c1 = Cell(title=self.T(f"해지 시점별 지분 IRR: {cross}년 차 전에 끊기면 한전 계약보다 못하다", f"Equity IRR by termination year: a break before year {cross} does worse than KEPCO"),
                  src=["ksj"], unit=self.T("지분 IRR", "Equity IRR"),
                  chart_key="default",
                  chart=charts.line_ref(yrs, [("", ys, c["gold"])], c, lambda v: f"{v:.0f}", lambda v: f"{v * 100:.0f}%",
                                        hlines=[(irr["cfd"], self.T(f"한전 계약 {self.pct(irr['cfd'])}", f"KEPCO {self.pct(irr['cfd'])}"), c["brown_dark"]),
                                                (self.hurdle, self.T(f"요구수익률 {self.pct(self.hurdle, 0)}", f"Hurdle {self.pct(self.hurdle, 0)}"), c["brick"]),
                                                (irr["ppa"], self.T(f"해지 없음 {self.pct(irr['ppa'])}", f"No termination {self.pct(irr['ppa'])}"), c["gold"])]),
                  note=self.T(f"x축 = 해지 연차(그 해부터 SMP {f.market.smp0:,.1f}원 판매). PPA 가격 = 회랑 중간 {self.kwh(f.ppa_mid)}, 대출 고정(재조달 없음), 위약금 0",
                              f"x-axis = termination year (SMP {f.market.smp0:,.1f} from then). PPA at corridor mid {self.kwh(f.ppa_mid)}, debt fixed (no refinancing), no termination payment"))
        pick = [1, 3, 5, 8, 10, 15, 20]
        rows = []
        for y, v in f.default_curve:
            if y in pick:
                rows.append([self.T(f"{y}년 차", f"Year {y}"), self.pct(v), self.T("미달" if (v or -1) < irr["cfd"] else "상회", "below" if (v or -1) < irr["cfd"] else "above")])
        rows.append([self.T("해지 없음", "No termination"), self.pct(irr["ppa"]), "—"])
        c2 = Cell(title=self.T(f"요구수익률 {self.pct(self.hurdle, 0)}를 지키려면 PPA가 {cross_h}년 이상 유지돼야 한다", f"To keep the {self.pct(self.hurdle, 0)} hurdle the PPA must last {cross_h}+ years"),
                  src=["ksj"],
                  table=TableSpec([self.T("해지 시점", "Termination"), self.T("지분 IRR", "Equity IRR"), self.T("한전 계약 대비", "vs KEPCO")], rows, [0.36, 0.32, 0.32], ["L", "R", "C"],
                                  brick_cells={(i, 2) for i, r in enumerate(rows) if r[2] in ("미달", "below")}, font_size=8.6),
                  note=self.T("해지 후 판매 가격이 SMP라 초기 해지일수록 손실이 크다 — 위약금(남은 기간 가치의 일부)이 이 곡선의 왼쪽을 받친다",
                              "After termination the plant earns SMP, so early breaks hurt most — termination payments prop up the left side of this curve"))
        v2 = self.vol2
        rows2 = [[self.T("데이터센터 SPV 최소 DSCR (Vol.2 한국 케이스)", "Data-centre SPV min DSCR (Vol.2 Korea)"), self.x(v2.get("min_dscr"))],
                 [self.T("데이터센터 지분 IRR (Vol.2)", "Data-centre equity IRR (Vol.2)"), self.pct(v2.get("equity_irr"))],
                 [self.T("전력비 처리 (Vol.2)", "Power cost treatment (Vol.2)"), self.T("임차인 별도 청구(100%)", "Billed to tenants (100%)")],
                 [self.T("PPA 물량 / 데이터센터 사용량", "PPA volume / data-centre use"), self.pct(f.dc["share"], 0)]]
        c3 = Cell(title=self.T("오프테이커 = Vol.2 데이터센터: 대주 기준 DSCR 1.6배대, 전력비는 임차인에게 넘긴다", "Offtaker = Vol.2's data centre: lender DSCR in the 1.6x range, power passed to tenants"),
                  src=["vol2"], table=TableSpec([self.T("항목", "Item"), self.T("값", "Value")], rows2, [0.66, 0.34], ["L", "R"], font_size=8.6),
                  note=self.T("PPA 대금의 실제 원천은 임차인(하이퍼스케일러 등)의 전력비 — 임대 계약이 PPA보다 짧으면 그 차이가 해지 위험이 된다",
                              "The PPA is ultimately paid from tenants' power bills — if leases are shorter than the PPA, the gap becomes termination risk"))
        c4 = Cell(title=self.T("완화책: 해지 확률을 낮추는 계약 조항이 프리미엄보다 싸다", "Mitigants: contract terms that cut termination risk are cheaper than a premium"), src=["ksj"],
                  panel_lead=self.T("텀시트에서 지킬 것 (A1)", "What to hold in the term sheet (A1)"),
                  bullets=[self.T("해지 위약금: 남은 기간 PPA 가치와 SMP의 차이 일부를 보전", "Termination payment: covers part of the PPA-vs-SMP gap for the remaining term"),
                           self.T("신용보강: 모회사 보증·신용장, 또는 임대 계약의 전력비 조항을 PPA와 같은 기간으로", "Credit support: parent guarantee or LC, or align lease power clauses with the PPA term"),
                           self.T("계약 승계: 데이터센터 매각·재조달 시 PPA가 따라가게(assignment)", "Assignment: the PPA follows the data centre on sale or refinancing"),
                           self.T("법 변경 조항: 망이용료 개편으로 구매자 비용이 바뀔 때의 재협상 기준", "Change in law: a renegotiation rule if network-charge reform changes the buyer's cost")])
        return Page("body", "6", self.T(f"오프테이커 위험: PPA가 {cross}년 안에 끊기면 한전 계약보다 못하다 — 위약금·보증이 프리미엄보다 싸다",
                                        f"Offtaker risk: a PPA that breaks within {cross} years underperforms KEPCO — guarantees beat a premium"),
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
        c1 = Cell(title=self.T(f"지분 IRR 분포 ({f.mc_spec.n:,}회): 직접 PPA는 꼬리가 길고, 시장 판매는 중앙값이 {self.pct(st['merchant']['p50'])}",
                               f"Equity IRR distribution ({f.mc_spec.n:,} runs): the PPA has a long left tail, merchant centres on {self.pct(st['merchant']['p50'])}"),
                  src=["smp", "ksj"], legend=[(c["warm_grey_light"], self.T("사분위 상자 · 중앙값", "IQR box · median"))], unit=self.T("지분 IRR", "Equity IRR"),
                  chart_key="mc", chart=charts.irr_boxes([(self.route(k, True), clip(f.mc[k])) for k in R], c,
                                                         [(self.hurdle, self.T("요구수익률", "Hurdle"), c["brick"])]),
                  note=self.T(f"같은 난수(SMP·발전량)를 세 경로에 공통 적용 — 차이는 계약 구조에서만 나온다. 직접 PPA는 연 해지 {self.pct(self.mc_h, 0)}. 표시 범위 −5~20%(밖은 끝에 표시)"
                              + self.prov_note(["smp_sigma", "smp_phi", "smp_base"]),
                              f"Common random numbers (SMP, output) across routes — differences come from the contracts only. PPA termination {self.pct(self.mc_h, 0)} a year. Shown −5% to 20%"
                              + self.prov_note(["smp_sigma", "smp_phi", "smp_base"])))
        rows = [[self.route(k, True), self.pct(st[k]["p10"]), self.pct(st[k]["p50"]), self.pct(st[k]["p90"]), self.pct(st[k]["below"], 0), self.pct(st[k]["neg"], 0)] for k in R]
        c2 = Cell(title=self.T(f"요구수익률 {self.pct(self.hurdle, 0)} 미달 확률: 한전 계약 {self.pct(st['cfd']['below'], 0)} · 직접 PPA {self.pct(st['ppa']['below'], 0)}",
                               f"Probability below the {self.pct(self.hurdle, 0)} hurdle: KEPCO {self.pct(st['cfd']['below'], 0)} · PPA {self.pct(st['ppa']['below'], 0)}"),
                  src=["ksj"],
                  table=TableSpec([self.T("경로", "Route"), "P10", "P50", "P90", self.T("요구수익률 미달", "< hurdle"), self.T("손실(IRR<0)", "Loss (IRR<0)")], rows,
                                  [0.22, 0.13, 0.13, 0.13, 0.20, 0.19], ["L", "R", "R", "R", "R", "R"], gold_cells={(1, 2)}, brick_cells={(2, 5)}, font_size=8.6),
                  note=self.T("대출은 기준 sizing으로 고정(나쁜 해에 지분이 부족분을 메운다 = 지분 흐름 음수 허용)", "Debt fixed at base sizing (equity funds shortfalls in bad years)"))
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
                           self.T(f"직접 PPA: 중앙값은 높지만 P10 {self.pct(st['ppa']['p10'])} — 초기 해지 경로가 왼쪽 꼬리를 만든다", f"PPA: higher median but P10 {self.pct(st['ppa']['p10'])} — early terminations make the left tail"),
                           self.T(f"시장 판매: 손실 확률 {self.pct(st['merchant']['neg'], 0)} — 신규 태양광의 무계약 판매는 지분 투자 대상이 아니다", f"Merchant: {self.pct(st['merchant']['neg'], 0)} loss probability — uncontracted new solar is not an equity case"),
                           self.T("IC 관점: PPA를 택하면 꼬리를 자르는 장치(위약금·보증)가 가격보다 먼저다", "IC view: with a PPA, tail protection (termination payments, guarantees) comes before price")])
        return Page("body", "7", self.T(f"몬테카를로: 직접 PPA 지분 IRR P50 {self.pct(st['ppa']['p50'])} · P10 {self.pct(st['ppa']['p10'])} — 시장 판매는 {self.pct(st['merchant']['neg'], 0)} 확률로 손실",
                                        f"Monte Carlo: PPA equity IRR P50 {self.pct(st['ppa']['p50'])} · P10 {self.pct(st['ppa']['p10'])} — merchant loses money {self.pct(st['merchant']['neg'], 0)} of the time"),
                    self.T(f"{f.mc_spec.n:,}회 × 3경로 · seed {f.mc_spec.seed} · SMP(로그 AR1) × 발전량 × PPA 해지", f"{f.mc_spec.n:,} runs × 3 routes · seed {f.mc_spec.seed} · SMP (log AR1) × output × PPA termination"),
                    [c1, c2, c3, c4])

    # --- p8 ------------------------------------------------------------------
    def p8(self) -> Page:
        f, irr = self.f, self.irr
        p1 = self.prem(self.mc_h)
        c1 = Cell(title=self.T("결론: 직접 PPA는 가격보다 구조의 문제", "Conclusion: a direct PPA is a structuring problem more than a pricing one"), src=["ksj"],
                  panel_lead="", bullets=[
                      self.T(f"가격: 한전 계약보다 +{p1['premium']:,.0f}원(연 해지 {self.pct(self.mc_h, 0)})이면 지분 투자자에게 충분 — 회랑 {f.corridor[1] - f.corridor[0]:,.0f}원 안에 있다",
                             f"Price: +{p1['premium']:,.0f} over KEPCO ({self.pct(self.mc_h, 0)} termination) is enough — well inside the {f.corridor[1] - f.corridor[0]:,.0f} corridor"),
                      self.T(f"성패: 데이터센터가 낼 망이용료가 {p1['max_fee']:,.0f}원/kWh 이하인지 — 산정 방식이 공개돼야 판단할 수 있다",
                             f"Make-or-break: network charges must stay under {p1['max_fee']:,.0f}/kWh — which needs a public method to judge"),
                      self.T("위험: 초기 해지 — 위약금·보증·계약 승계로 꼬리를 자르면 프리미엄도 줄어든다", "Risk: early termination — termination payments, guarantees and assignment cut the tail and the premium"),
                      self.T(f"대안 비교: 한전 계약은 안전하지만 지분 IRR {self.pct(irr['cfd'])}, 무계약 시장 판매는 {self.pct(irr['merchant'])}", f"Alternatives: KEPCO is safe at {self.pct(irr['cfd'])}, merchant earns {self.pct(irr['merchant'])}")])
        rows = [[self.T("가격", "Price"), self.T(f"회랑 {f.corridor[0]:,.1f}~{f.corridor[1]:,.1f}원", f"Corridor {f.corridor[0]:,.1f}–{f.corridor[1]:,.1f}"),
                 self.T("낙찰 평균가(공단 결과) · 계약종별 요금", "Average award (KEA) · tariff class"), "3"],
                [self.T("망이용료", "Network charges"), self.T(f"상한 {p1['max_fee']:,.0f}원(역산)", f"Cap {p1['max_fee']:,.0f} (implied)"), self.T("송배전이용요금 고시 · 부가정산금 · 손실", "T&D tariffs · settlements · losses"), "5"],
                [self.T("오프테이커", "Offtaker"), self.T("해지 확률 격자 0~5%", "Termination grid 0–5%"), self.T("신용평가 · 임대 계약 기간 · 보증", "Rating · lease term · guarantees"), "6"],
                [self.T("발전량", "Output"), self.T(f"이용률 {self.pct(f.asset.capacity_factor, 0)}(BNEF·KEEI)", f"CF {self.pct(f.asset.capacity_factor, 0)} (BNEF/KEEI)"), self.T("P50/P90 발전량 보고서 · 출력제한 이력", "P50/P90 yield report · curtailment"), "4, 7"],
                [self.T("사업비", "CAPEX"), self.T(f"{self.eok(f.asset.capex)}(LCOE 기준)", f"{self.eok(f.asset.capex)} (LCOE basis)"), self.T("EPC 견적 · 토지 · 계통 접속비", "EPC quote · land · grid connection"), "4"],
                [self.T("프로파일", "Shape"), self.T("발전량 그대로 판매(pay-as-produced)", "Pay-as-produced"), self.T("24시간 공급 요구 시 부족분 조달 비용(ESS·한전)", "24/7 firming cost (storage, KEPCO)"), "—"]]
        c2 = Cell(title=self.T("IC 체크리스트: 이번 분석의 가정 vs 실제 딜에서 확인할 것", "IC checklist: this note's assumption vs what a real deal must confirm"), src=["ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("이번 분석", "This note"), self.T("실제 딜에서 확인", "Confirm in a deal"), self.T("쪽", "p.")], rows,
                                  [0.15, 0.30, 0.45, 0.10], ["L", "L", "L", "C"], font_size=8.0))
        c3 = Cell(title=self.T("이 노트의 한계", "Limits of this note"), src=["ksj"], panel_lead="", bullets=[
            self.T(f"사업비: 2022년 실제 설치비(kW당 {f.V('capex_per_kw'):,.0f}천원)로 계산한 LCOE {f.lcoe_check['actual_lcoe']:.0f}원이 에너지경제연구원 LCOE {f.lcoe_check['keei'][0]:.0f}~{f.lcoe_check['keei'][1]:.0f}원보다 낮다 — 보수적으로 LCOE 쪽에 맞춤",
                   f"CAPEX: 2022 actual installed cost (KRW {f.V('capex_per_kw'):,.0f}k/kW) implies an LCOE of {f.lcoe_check['actual_lcoe']:.0f}, below KEEI's {f.lcoe_check['keei'][0]:.0f}–{f.lcoe_check['keei'][1]:.0f} — matched to the LCOE to stay conservative"),
            self.T("PPA는 발전량 그대로 판매로 단순화 — 24시간 공급(형상) 위험과 ESS는 제외", "PPA simplified to pay-as-produced — 24/7 shape risk and storage left out"),
            self.T("한전 요금 인상·RE100 가치는 구매자 상한을 올리지만 보수적으로 제외", "Tariff increases and RE100 value would raise the buyer's ceiling; excluded to stay conservative"),
            self.T("해지 확률은 공개 부도율 근거가 없어 격자로 제시 — 실제는 신용평가로", "No public default data for termination — shown as a grid; a deal uses a credit rating")])
        c4 = Cell(title=self.T("Vol.5 예고 (완결): AI 에너지 자산 투자 지도", "Next, Vol.5 (finale): an AI energy asset investment map"), src=["ksj"],
                  panel_lead=self.T("수요 · 기기 · PF · IPO · 발전을 한 장에", "Demand, equipment, PF, IPO and power on one page"),
                  bullets=[self.T("Vol.1~4의 결론을 위험·수익 지도에 배치 — 어느 자산이 어떤 투자자에게 맞나", "Place Vol.1–4 on one risk-return map — which asset fits which investor"),
                           self.T("IC 메모 형식: 투자 포인트 · 위험과 완화책 · 텀시트", "IC memo format: thesis, risks and mitigants, term sheet"),
                           self.T("시리즈 전체의 가정·출처 등급을 한 표로", "All assumptions and source grades in one table")])
        return Page("body", "8", self.T("시사점: 직접 PPA는 가격보다 구조의 문제 — 망이용료 공개, 해지 보호, 프로파일 배분이 먼저",
                                        "Implications: a direct PPA is about structure, not price — transparent network charges, termination protection, shape allocation first"),
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
                [self.T("가격 기준", "Pricing rule"), self.T(f"최소 {self.kwh(p1['price'])} (한전 계약 +{p1['premium']:,.0f}원, 연 해지 {self.pct(self.mc_h, 0)})",
                                                           f"At least {self.kwh(p1['price'])} (KEPCO +{p1['premium']:,.0f}, {self.pct(self.mc_h, 0)} termination)")]]
        c1 = Cell(title=self.T("투자 개요 (예시 — 가상 자산)", "Deal summary (illustrative — hypothetical asset)"), src=["ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("내용", "Detail")], rows, [0.24, 0.76], ["L", "L"], shade_rows={3, 4}, font_size=8.4))
        c2 = Cell(title=self.T("투자 포인트 3", "Three investment points"), src=["ksj"], panel_lead="", bullets=[
            self.T(f"가격 우위: 회랑 중간이면 한전 계약 대비 IRR +{(irr['ppa'] - irr['cfd']) * 100:.1f}%p", f"Price edge: at the corridor mid, +{(irr['ppa'] - irr['cfd']) * 100:.1f}pp IRR over KEPCO"),
            self.T("수요 확실성: AI 데이터센터의 RE100 조달 수요 — 2027년 RPS 폐지 후 직접 조달 경로가 귀해진다", "Demand: AI data centres need RE100 supply — direct routes get scarcer after the 2027 RPS repeal"),
            self.T("하방 보호: 해지돼도 SMP 판매로 대출은 유지 가능한 구조(대출 고정 시나리오에서 원리금 점검)", "Downside: on termination the plant still sells at SMP; debt service is checked with fixed debt")])
        rr = [[self.T("오프테이커 해지", "Offtaker termination"), self.T("위약금(잔여 가치 차액 일부) · 모회사 보증·신용장 · 계약 승계", "Termination payment · parent guarantee/LC · assignment")],
              [self.T("망이용료 불확실", "Network-charge opacity"), self.T("법 변경·요금 개편 재협상 조항, 구매자 비용 상한 공유", "Change-in-law reopener; shared buyer cost cap")],
              [self.T("발전량 부족", "Output shortfall"), self.T("P90 기준 대출 sizing · 출력제한 보상 조항", "P90 debt sizing · curtailment compensation")],
              [self.T("SMP 하락(해지 후)", "SMP fall (after termination)"), self.T("해지 시 재계약 우선권 · 한전 계약시장 재입찰 가능성 검토", "Re-contracting rights · re-bidding into the KEPCO market")],
              [self.T("제도 변경", "Policy change"), self.T("RPS→계약시장 경과 규정 확인(2027년 이전 사용전검사 여부)", "Check transition rules (pre-2027 commissioning)")]]
        c3 = Cell(title=self.T("위험과 완화책", "Risks and mitigants"), src=["ksj"],
                  table=TableSpec([self.T("위험", "Risk"), self.T("완화책", "Mitigant")], rr, [0.30, 0.70], ["L", "L"], font_size=8.2))
        ts = [[self.T("기간", "Term"), self.T(f"{f.market.ppa_term}년 (임대 계약과 맞춤)", f"{f.market.ppa_term} yrs (aligned with leases)")],
              [self.T("가격", "Price"), self.T(f"{f.ppa_mid:,.1f}원/kWh 고정 (하한 {p1['price']:,.1f})", f"KRW {f.ppa_mid:,.1f}/kWh fixed (floor {p1['price']:,.1f})")],
              [self.T("물량", "Volume"), self.T("발전량 전량 (pay-as-produced)", "All output (pay-as-produced)")],
              [self.T("해지 위약금", "Termination"), self.T("잔여 기간 (PPA − SMP) 현재가치의 일정 비율", "A share of the PV of (PPA − SMP) over the remaining term")],
              [self.T("신용보강", "Credit support"), self.T("모회사 보증 또는 연간 대금 1년분 신용장", "Parent guarantee or a one-year LC")],
              [self.T("환경가치", "Attributes"), self.T("재생에너지 사용 확인서 구매자 귀속", "Renewable certificates to the buyer")]]
        c4 = Cell(title=self.T("PPA 텀시트 (예시)", "PPA term sheet (illustrative)"), src=["ksj"],
                  table=TableSpec([self.T("조항", "Clause"), self.T("제안", "Proposal")], ts, [0.24, 0.76], ["L", "L"], font_size=8.2),
                  note=self.T("예시 조건 — 실제 계약 조건이 아니다", "Illustrative terms, not an actual contract"))
        return Page("body", "A1", self.T("IC 메모: 직접 PPA 지분투자 — 가격은 회랑 중간, 위험은 계약 조항으로 자른다",
                                         "IC memo: equity in a direct-PPA plant — price at the corridor mid, risks cut by contract terms"),
                    self.T("투자 개요 · 투자 포인트 · 위험과 완화책 · 텀시트 (예시)", "Summary · points · risks and mitigants · term sheet (illustrative)"), [c1, c2, c3, c4])

    # --- A2·A3 입력표 ---------------------------------------------------------
    def a2(self, part: int) -> Page:
        f = self.f
        G = TIER_KR if self.kr else TIER_EN
        keys = list(f.inputs.keys())
        half = (len(keys) + 1) // 2
        keys = keys[:half] if part == 0 else keys[half:]
        rows, gold, brick, strong = [], set(), set(), set()
        for i, k in enumerate(keys):
            x = f.inputs[k]
            val = x.value if isinstance(x.value, str) else (f"{x.value:,.4g}" if x.value is not None else "—")
            if k == "cod_year":
                val = f"{int(x.value)}"
            if k == "ktb_3y":
                val = f"{f.ktb * 100:.2f}"
            rng_ = f" ({x.low:,.4g}~{x.high:,.4g})" if x.low is not None and x.high is not None else ""
            src = x.source if len(x.source) <= 92 else x.source[:90] + "…"
            rows.append([self.lab(k), str(val) + rng_, x.unit, G[x.tier], src])
            if x.tier == "A":
                gold.add((i, 3))
            elif x.tier == "C":
                brick.add((i, 3))
            elif x.tier == "J":
                strong.add((i, 3))
        cnt = {t: sum(f.inputs[k].tier == t for k in f.inputs) for t in "ABCJ"}
        cell = Cell(title=self.T(f"입력 {len(f.inputs)}개: 공식 원문 {cnt['A']} · 공식 발표 보도 {cnt['B']} · 민간 2차 {cnt['C']} · 저자 판단 {cnt['J']}",
                                 f"{len(f.inputs)} inputs: official {cnt['A']} · press report {cnt['B']} · secondary {cnt['C']} · judgement {cnt['J']}"),
                    src=["mcee", "kepco", "keei", "sec", "ksj"],
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
            todo = x.official_todo.replace("TODO(data):", "").strip()
            rows.append([self.lab(k), G[x.tier], todo if self.kr else todo])
        c1 = Cell(title=self.T(f"공식 원문으로 교체 대기 {len(rows)}개: 확정 전 모두 원자료로 바꾼다", f"{len(rows)} inputs awaiting official sources — all replaced before final"),
                  src=["ksj"], table=TableSpec([self.T("항목", "Item"), self.T("지금 등급", "Current grade"), self.T("교체할 공식 원문", "Official source to use")], rows,
                                              [0.22, 0.16, 0.62], ["L", "C", "L"], font_size=7.4),
                  strip=self.T(self.BUILT_WITH_KR, self.BUILT_WITH_EN),
                  note=self.T(f"원칙: 보고서 숫자는 공식 원문(정부·공공기관·법령·SEC) 우선 · 언론은 공식 발표를 인용한 경우만 · 민간 자료는 잠정으로만. 전체 코드·링크: GitHub {self.cfg['research']['repo_url']}",
                              f"Rule: official originals first (government, public bodies, statutes, SEC) · media only when citing an official release · private data provisional only. Code and links: GitHub {self.cfg['research']['repo_url']}"))
        return Page("full", "A4", self.T("데이터 노트: 공신력 원칙 — 공식 원문 우선, 나머지는 교체 대기로 표시", "Data notes: official sources first; everything else flagged for replacement"),
                    self.T(f"기준일 {f.as_of} · 국고채 3년 {self.pct(f.ktb, 2)}({f.ktb_date}) · 모델: 연 단위 명목, 금액 억원, 가격 원/kWh",
                           f"As of {f.as_of} · KTB 3-yr {self.pct(f.ktb, 2)} ({f.ktb_date}) · annual nominal model, KRW 100mn, KRW/kWh"), [c1], grid="1x1")

    def a5(self) -> Page:
        terms = [
            ("PPA", self.T("전력구매계약 — 발전사와 구매자가 가격·기간·물량을 정해 직접 사고파는 계약", "Power purchase agreement — seller and buyer fix price, term and volume directly")),
            ("CfD", self.T("차액계약 — 계약가와 시장가(SMP)의 차이를 정산. 2027년부터 한전과의 장기 고정가 계약", "Contract for difference — settles contract vs market price; from 2027, long-term contracts with KEPCO")),
            ("SMP", self.T("계통한계가격 — 전력시장의 시간별 도매가격", "System marginal price — Korea's hourly wholesale power price")),
            ("REC", self.T("신재생에너지 공급인증서 — RPS 의무 이행용 인증서. 신규 사업자는 2027년부터 발급 제한", "Renewable energy certificate under RPS; restricted for new entrants from 2027")),
            ("RPS", self.T("신재생에너지 공급의무화 제도 — 2027년 계약시장으로 전환", "Renewable portfolio standard — replaced by a contract market in 2027")),
            ("LCOE", self.T("균등화발전비용 — 수명 동안 비용 현재가치 ÷ 발전량 현재가치", "Levelised cost of electricity — PV of lifetime costs ÷ PV of output")),
            (self.T("망이용료", "Network charges"), self.T("직접 PPA 구매자가 한전에 내는 송배전망 이용 요금과 부가 비용", "Transmission and distribution charges a direct-PPA buyer pays KEPCO")),
            (self.T("오프테이커", "Offtaker"), self.T("전력을 사는 계약 상대방 (이번 편: 데이터센터 SPV)", "The buyer under the contract (here the data-centre SPV)")),
            ("DSCR", self.T("원리금상환비율 = CFADS ÷ 원리금", "Debt service coverage = CFADS ÷ debt service")),
            (self.T("Sculpting", "Sculpting"), self.T("매년 DSCR이 목표와 같도록 원리금을 현금흐름에 맞춰 설계", "Shaping debt service so each year's DSCR equals the target")),
            (self.T("지분 IRR · MOIC", "Equity IRR · MOIC"), self.T("지분 투자 수익률 · 회수 배수(총분배 ÷ 투자)", "Return on equity · multiple of invested capital")),
            (self.T("해지 확률", "Termination rate"), self.T("PPA 기간 중 매년 계약이 끊길 확률(이번 편: 격자로 제시)", "Annual chance the PPA ends early (shown as a grid)")),
            (self.T("가격 회랑", "Price corridor"), self.T("발전사의 대안(한전 계약가)과 구매자의 대안(한전 요금) 사이 범위", "Range between the seller's and buyer's outside options")),
            (self.T("pay-as-produced", "Pay-as-produced"), self.T("발전한 만큼만 판매 — 24시간 공급 의무 없음", "Sell what is produced — no 24/7 obligation")),
            (self.T("신뢰 등급", "Source grade"), self.T("공식 원문 · 공식 발표 보도 · 민간 2차 · 저자 판단", "Official · press report of official release · secondary · judgement")),
        ]
        cell = Cell(title=self.T("용어 정의", "Glossary"),
                    table=TableSpec([self.T("용어", "Term"), self.T("정의", "Definition")], [list(t) for t in terms], [0.20, 0.80], ["L", "L"], shade_rows={0, 1, 6}, font_size=8.2),
                    note=self.T("음영 = 이번 편 핵심 용어", "Shaded = core terms"))
        return Page("full", "A5", self.T("용어 정의: 전기를 사고파는 말", "Glossary: the language of buying and selling power"),
                    self.T("가격 원/kWh · 금액 억원 · 미국 USD/MWh", "Prices KRW/kWh · amounts KRW 100mn · U.S. USD/MWh"), [cell], grid="1x1")
