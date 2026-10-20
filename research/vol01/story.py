"""Vol.1 페이지 구성·문구 (국문/영문). 숫자는 모두 data.Facts에서, 서술 방향도 데이터로 결정한다.

판단 문장에는 '(저자 견해)' / '(author's view)'를 붙인다.
"""
from __future__ import annotations

from typing import Mapping

from . import charts
from .data import CMD_DART, Facts, Unavailable, ok
from .layout import BigBox, Cell, Page, TableSpec

COMPANY_COLORS = ("gold", "brown_dark", "brown_mid", "warm_grey")


class Story:
    def __init__(self, cfg: Mapping, f: Facts, lang: str):
        self.cfg, self.f, self.lang, self.kr = cfg, f, lang, lang == "kr"
        self.c = cfg["research"]["colors"]
        self.v = cfg["research"]["vol01"]
        self.rules = self.v["text_rules"]

    # --- 문구·숫자 도우미 ---------------------------------------------------
    def T(self, kr: str, en: str) -> str:
        return kr if self.kr else en

    def x(self, v: float, d: int = 1) -> str:
        return f"{v:.{d}f}배" if self.kr else f"{v:.{d}f}x"

    @staticmethod
    def pct(v: float, d: int = 0, sign: bool = True) -> str:
        return f"{v:+.{d}f}%" if sign else f"{v:.{d}f}%"

    @staticmethod
    def num(v: float, d: int = 0) -> str:
        return f"{v:,.{d}f}"

    def share(self, v: float) -> str:
        return f"{v * 100:.0f}%"

    def name(self, row) -> str:
        return row["company"] if self.kr else row["company_en"]

    def view(self) -> str:
        return self.T(" (저자 견해)", " (author's view)")

    def reason(self, u: Unavailable) -> str:
        return u.reason if self.kr or not u.reason_en else u.reason_en

    def pending_cell(self, title: str, src: list[str], u: Unavailable, note: str = "") -> Cell:
        return Cell(title=title, src=src, placeholder=(self.T("사유: ", "Reason: ") + self.reason(u), u.command), note=note)

    def unit(self, kr: str, en: str) -> str:
        return self.T(kr, en)

    # --- 출처·고정 문구 ----------------------------------------------------
    def sources(self) -> dict[str, str]:
        return {
            "iea_ai": self.T("IEA, Energy and AI (2025.4) 요약", "IEA, Energy and AI (Apr 2025), executive summary"),
            "iea_kq": self.T("IEA, Key Questions on Energy and AI (2026.4)", "IEA, Key Questions on Energy and AI (Apr 2026)"),
            "eia": "U.S. Energy Information Administration (EIA), Electricity retail sales",
            "krx": self.T("한국거래소(KRX) Open API 유가증권 일별매매정보", "Korea Exchange (KRX) Open API, KOSPI daily trading"),
            "corp": self.T("회사 공시(주식분할), 저자 검산", "Company filing (stock split), author's check"),
            "dart": self.T("금융감독원 DART 사업보고서(연결)", "FSS DART annual reports (consolidated)"),
            "ecos": self.T("한국은행 ECOS 시장금리(일별)", "Bank of Korea ECOS market rates (daily)"),
            "fred": "FRED, Federal Reserve Bank of St. Louis (DGS10)",
            "ksj": "KSJ Research",
        }

    def labels(self) -> dict[str, str]:
        return {"source": self.T("출처", "Source"), "note": self.T("주", "Note"), "unit": self.T("단위", "Unit"),
                "pending": self.T("데이터 수집 후 생성", "Generated after data collection")}

    def footer(self) -> str:
        return self.T(f"KSJ Research · Research Note Vol.1 · {self.v['date_label']} · 교육·연구 목적, 투자 권유 아님",
                      f"KSJ Research · Research Note Vol.1 · {self.v['date_label']} · For education and research only, "
                      "not investment advice")

    # =======================================================================
    # 핵심 계산 결과 → 문장 조각
    # =======================================================================
    def market_basis(self) -> str:
        """'합계 기준 7.7배(회사별 4.4배~26.1배, 단순평균 14.6배)' — 호출부가 '시총'을 앞에 붙인다."""
        mk = self.f.market
        return self.T(f"합계 기준 {self.x(mk.total_multiple)}(회사별 {self.x(mk.bottom['multiple'])}~"
                      f"{self.x(mk.top['multiple'])}, 단순평균 {self.x(mk.mean_multiple)})",
                      f"{self.x(mk.total_multiple)} combined (range {self.x(mk.bottom['multiple'])}–"
                      f"{self.x(mk.top['multiple'])}, simple average {self.x(mk.mean_multiple)})")

    def multiple_led(self) -> bool | None:
        """멀티플이 이익보다 앞서 달렸나: 분해 가능하면 멀티플 기여 비중, 아니면 가용 이익 배수와 시총 배수 비교."""
        dc = self.f.decomp
        if ok(dc):
            return dc.agg["mult_share"] > float(self.rules["multiple_led_share"])
        if ok(self.f.val):
            g = self.f.val.ni_growth.dropna(subset=["ni_multiple"])
            if len(g):
                return int((g["mcap_multiple"] > g["ni_multiple"]).sum()) * 2 > len(g)
        return None

    def n_mcap_beats_ni(self) -> tuple[int, int]:
        g = self.f.val.ni_growth.dropna(subset=["ni_multiple"])
        return int((g["mcap_multiple"] > g["ni_multiple"]).sum()), len(g)

    def fin_sum(self, fy: int, col: str) -> float:
        t = self.f.fin.table
        return float(t[t["fy"] == fy][col].sum())

    # =======================================================================
    # 페이지
    # =======================================================================
    def pages(self) -> list[Page]:
        p = [self.cover(), self.executive(), self.toc_page(), self.p1(), self.p2(), self.p3(), self.p4(), self.p5(),
             self.a1(), self.a2(), self.a3(), self.a4(), self.back()]
        return p

    # --- 표지 / 뒤표지 ------------------------------------------------------
    def cover(self) -> Page:
        return Page("cover", title=self.v["title_kr"] if self.kr else self.v["title_en"],
                    subtitle=self.v["subtitle_kr"] if self.kr else self.v["subtitle_en"],
                    extra={"kicker": "Research Note Vol.1", "author": self.cfg["research"]["author"],
                           "date": self.v["date_label"],
                           "note": self.T("KSJ Research · 교육·연구 목적 · 투자 권유 아님",
                                          "KSJ Research · For education and research only · Not investment advice")})

    def back(self) -> Page:
        items = [
            self.T("이 자료는 교육·연구 목적의 개인 포트폴리오이며, 투자 권유나 특정 종목에 대한 매수·매도 의견이 아니다.",
                   "This is a personal portfolio for education and research. It is not investment advice or a "
                   "recommendation to buy or sell any security."),
            self.T("본문의 판단은 저자 개인의 견해이며, 저자가 속했거나 속할 어떤 기관의 견해도 대변하지 않는다.",
                   "Views are the author's own and do not represent any current or future employer."),
            self.T("모든 데이터는 공개 자료이며 정확성과 완전성을 보장하지 않는다. 이 자료를 근거로 한 투자 판단의 책임은 "
                   "투자자 본인에게 있다.",
                   "All data are public; accuracy and completeness are not guaranteed. Investors are solely "
                   "responsible for their decisions."),
            self.T("KSJ Research는 개인 리서치 브랜드로, 실존 금융회사와 관련이 없다.",
                   "KSJ Research is a personal research brand and is not affiliated with any financial institution."),
            self.T(f"기준일 {self.f.as_of}. 수치·출처·계산 방법은 Appendix A2와 저장소 코드로 재현할 수 있다.",
                   f"As of {self.f.as_of}. Figures, sources and methods can be reproduced from Appendix A2 and the code."),
        ]
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"]})

    # --- Executive Summary --------------------------------------------------
    def executive(self) -> Page:
        f, d, g, mk, dc, val = self.f, self.f.demand, self.f.ground, self.f.market, self.f.decomp, self.f.val
        led = self.multiple_led()
        # 제목: 데이터로 결정
        parts = []
        parts.append(self.T("수요는 진짜이고", "Demand is real") if ok(d) else self.T("수요 데이터 확인 중", "Demand data pending"))
        if ok(g):
            parts.append({"ahead": self.T("현장에서도 보인다", "it shows up on the ground"),
                          "behind": self.T("현장 데이터는 엇갈린다", "ground data is mixed"),
                          "similar": self.T("현장 차이는 아직 작다", "the ground gap is still small")}[g.verdict])
        if ok(mk) and led is not None:
            parts.append(self.T("시장은 이미 알고 있고 이익보다 멀티플이 앞서 달렸다" if led else
                                "시장은 반영했고 이익이 이를 뒷받침한다",
                                "the market already knows, and multiples ran ahead of earnings" if led else
                                "the market has priced it, backed by earnings"))
        title = self.T(" ".join([parts[0], parts[1] if len(parts) > 1 else ""]).strip() + (" — " + parts[2] if len(parts) > 2 else ""),
                       ", ".join(parts[:2]) + (" — " + parts[2] if len(parts) > 2 else "")) + (self.view() if len(parts) > 2 else "")
        sub = []
        if ok(d):
            sub.append(self.T(f"IEA 2030E {self.num(d.v['dc_2030'])}TWh(2024년의 {self.x(d.mult_2030)})",
                              f"IEA 2030E {self.num(d.v['dc_2030'])} TWh ({self.x(d.mult_2030)} 2024)"))
        if ok(g):
            sub.append(self.T(f"버지니아 상업용 판매 {self.pct(g.va_change_pct)} vs 미국 {self.pct(g.us_change_pct)}",
                              f"Virginia commercial sales {self.pct(g.va_change_pct)} vs U.S. {self.pct(g.us_change_pct)}"))
        if ok(mk):
            sub.append(self.T(f"4사 시총 {self.market_basis()}", f"4 names' market cap {self.market_basis()}"))
        # 왼쪽: 핵심 지표표
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        if ok(d):
            add(self.T("2030E 데이터센터 전력 소비", "2030E data-centre power use"),
                self.T(f"{self.num(d.v['dc_2030'])} TWh (2024년의 {self.x(d.mult_2030)})",
                       f"{self.num(d.v['dc_2030'])} TWh ({self.x(d.mult_2030)} 2024)"), "1", key=True)
            add(self.T("2035E 전망 범위", "2035E outlook range"),
                f"{self.num(d.v['dc_2035_low'])}~{self.num(d.v['dc_2035_high'])} TWh", "1")
            add(self.T("2025 증가율: AI DC / DC / 전 세계", "2025 growth: AI DC / DC / world"),
                f"{self.pct(d.v['growth_ai'])} / {self.pct(d.v['growth_dc'])} / {self.pct(d.v['growth_global'])}", "1")
        if ok(g):
            add(self.T(f"버지니아 상업용 판매 지수 {g.last_year} ({g.base_year}=100)",
                       f"Virginia commercial sales index {g.last_year} ({g.base_year}=100)"),
                self.T(f"{100 + g.va_change_pct:.0f} vs 미국 {100 + g.us_change_pct:.0f}",
                       f"{100 + g.va_change_pct:.0f} vs U.S. {100 + g.us_change_pct:.0f}"), "2", key=True)
        if ok(mk):
            add(self.T("4사 시총 변화 (합계 기준)", "4 names' market cap (combined)"),
                f"{self.x(mk.total_multiple)}  ({mk.t0} → {mk.t1})", "4", key=True)
            add(self.T("4사 시총 변화 (단순평균 / 범위)", "4 names' market cap (simple avg / range)"),
                f"{self.x(mk.mean_multiple)} / {self.x(mk.bottom['multiple'])}~{self.x(mk.top['multiple'])}", "4")
        if ok(dc):
            add(self.T(f"이익 기여 vs 멀티플 기여 ({dc.fy0}→{dc.fy1})", f"Earnings vs multiple ({dc.fy0}→{dc.fy1})"),
                f"{self.share(dc.agg['earn_share'])} vs {self.share(dc.agg['mult_share'])}", "4", key=True)
        elif ok(val):
            n, tot = self.n_mcap_beats_ni()
            add(self.T(f"이익 vs 시총 (가용: {val.growth_from}→{val.fy})", f"Earnings vs mkt cap (avail.: {val.growth_from}→{val.fy})"),
                self.T(f"{tot}사 중 {n}곳 시총 배수 > 지배순이익 배수", f"{n} of {tot}: mkt-cap x > NI x"), "3·4", key=True)
            add(self.T("이익·멀티플 기여 (FY2022A 기준)", "Earnings vs multiple (FY2022A base)"),
                self.T("FY2022 수집 후 산출", "after FY2022 collection"), "4")
        if ok(val):
            add(self.T(f"현재 PER ({val.fy} 지배순이익)", f"Current P/E ({val.fy} NI to parent)"),
                self.T(f"합산 {self.x(val.agg_per)} · 중앙값 {self.x(val.median_per)}",
                       f"aggregate {self.x(val.agg_per)} · median {self.x(val.median_per)}"), "4")
        r = f.rates
        if ok(r) and r.ktb10_t0 is not None:
            add(self.T("국고채 10년 (2023 초 → 최근)", "KTB 10y (start-2023 → latest)"),
                f"{r.ktb10_t0:.2f}% → {r.ktb10_t1:.2f}%", "5")
        table = TableSpec([self.T("핵심 지표", "Key metric"), self.T("값", "Value"), self.T("쪽", "Page")], rows,
                          [0.47, 0.43, 0.10], ["L", "R", "C"], shade_rows=shade, gold_cells=gold, font_size=8.6)
        left = Cell(title=self.T("핵심 지표", "Key metrics"), src=["iea_ai", "iea_kq", "eia", "krx", "dart"],
                    table=table, note=self.T("KSJ Research 계산. 각 지표의 정의·계산은 해당 쪽 각주 참조",
                                             "KSJ Research calculations; see footnotes on each page"))
        boxes = [self.box_demand(), self.box_ground(), self.box_market()]
        return Page("exec", label="i", title=title, subtitle=" · ".join(sub), cells=[left], boxes=boxes)

    def box_demand(self) -> BigBox:
        d = self.f.demand
        if not ok(d):
            return BigBox("—", self.reason(d), self.T("수요: 데이터 확인 중", "Demand: data pending"), [])
        rng = (d.v["dc_2035_high"] / d.v["dc_2035"] - 1) * 100
        return BigBox(self.x(d.mult_2030), self.T("데이터센터 전력 소비 2030E ÷ 2024 (IEA 기준 시나리오)",
                                                   "Data-centre power 2030E ÷ 2024 (IEA Base Case)"),
                      self.T(f"수요는 진짜다 — 2030년 {self.num(d.v['dc_2030'])}TWh, AI 데이터센터 수요 {self.pct(d.v['growth_ai'])}",
                             f"Demand is real — {self.num(d.v['dc_2030'])} TWh by 2030; AI data-centre demand {self.pct(d.v['growth_ai'])}"),
                      [self.T(f"2025년 데이터센터 {self.pct(d.v['growth_dc'])}, AI 데이터센터 {self.pct(d.v['growth_ai'])} vs 전 세계 전력 {self.pct(d.v['growth_global'])}",
                              f"2025: data centres {self.pct(d.v['growth_dc'])}, AI data centres {self.pct(d.v['growth_ai'])} vs world {self.pct(d.v['growth_global'])}"),
                       self.T(f"2017~2024년 연 {d.v['cagr_17_24']:.0f}% 증가, 2024년 세계 전력의 {d.v['share_2024']:.1f}% · 미국 비중 {d.v['region_us']:.0f}%",
                              f"Grew {d.v['cagr_17_24']:.0f}%/yr in 2017–2024; {d.v['share_2024']:.1f}% of world power in 2024; U.S. {d.v['region_us']:.0f}%"),
                       self.T(f"다만 2035년 범위 {self.num(d.v['dc_2035_low'])}~{self.num(d.v['dc_2035_high'])}TWh — 기준 대비 ±{rng:.0f}%로 넓다",
                              f"But the 2035 range is wide: {self.num(d.v['dc_2035_low'])}–{self.num(d.v['dc_2035_high'])} TWh (±{rng:.0f}% vs base)")])

    def box_ground(self) -> BigBox:
        g, s = self.f.ground, self.f.sectors
        if not ok(g):
            return BigBox("—", self.reason(g), self.T("현장: 데이터 확인 중", "Ground: data pending"), [g.command])
        title = {"ahead": self.T(f"현장에서도 보인다 — 미국 전체({self.pct(g.us_change_pct)})를 {g.gap_pts:.0f}p 앞섰다",
                                 f"It shows up on the ground — {g.gap_pts:.0f} pts ahead of the U.S. ({self.pct(g.us_change_pct)})"),
                 "behind": self.T(f"현장 데이터는 엇갈린다 — 미국 전체({self.pct(g.us_change_pct)})보다 느렸다",
                                  f"Ground data is mixed — behind the U.S. ({self.pct(g.us_change_pct)})"),
                 "similar": self.T(f"현장 차이는 아직 작다 — 미국 전체 {self.pct(g.us_change_pct)}",
                                   f"The ground gap is small — U.S. {self.pct(g.us_change_pct)}")}[g.verdict]
        bl = [self.T(f"연평균 버지니아 {g.va_cagr_pct:.1f}% vs 미국 {g.us_cagr_pct:.1f}% ({g.base_year}~{g.last_year})",
                     f"CAGR Virginia {g.va_cagr_pct:.1f}% vs U.S. {g.us_cagr_pct:.1f}% ({g.base_year}–{g.last_year})"),
              self.T(f"최근 3년({g.recent_from}→{g.last_year}) 연평균 {g.va_recent_cagr_pct:.1f}% vs {g.us_recent_cagr_pct:.1f}%",
                     f"Last 3 years ({g.recent_from}→{g.last_year}) CAGR {g.va_recent_cagr_pct:.1f}% vs {g.us_recent_cagr_pct:.1f}%")]
        if ok(s):
            bl.append(self.T(f"미국 상업용 요금 {s.first_year}년 대비 {self.pct(s.change_pct('price', 'COM'))} (판매량 {self.pct(s.change_pct('sales', 'COM'), 1)})",
                             f"U.S. commercial price {self.pct(s.change_pct('price', 'COM'))} since {s.first_year} (volume {self.pct(s.change_pct('sales', 'COM'), 1)})"))
        return BigBox(self.pct(g.va_change_pct), self.T(f"버지니아 상업용 전력 판매 {g.base_year}→{g.last_year} (EIA)",
                                                         f"Virginia commercial power sales {g.base_year}→{g.last_year} (EIA)"),
                      title, bl)

    def box_market(self) -> BigBox:
        mk, dc, val = self.f.market, self.f.decomp, self.f.val
        if not ok(mk):
            return BigBox("—", self.reason(mk), self.T("시장: 데이터 확인 중", "Market: data pending"), [mk.command])
        led = self.multiple_led()
        if ok(dc):
            title = self.T(f"시장은 이미 알고 있다 — 시총 증가의 {self.share(dc.agg['mult_share'])}가 멀티플 확대{self.view()}"
                           if led else f"이익이 시총 증가의 {self.share(dc.agg['earn_share'])}를 설명한다{self.view()}",
                           f"The market already knows — {self.share(dc.agg['mult_share'])} of the gain is multiple expansion{self.view()}"
                           if led else f"Earnings explain {self.share(dc.agg['earn_share'])} of the gain{self.view()}")
        else:
            n, tot = self.n_mcap_beats_ni()
            title = self.T(f"시장은 이미 알고 있다 — {tot}사 중 {n}곳은 시총이 이익보다 빠르게 늘었다{self.view()}"
                           if led else f"시장은 반영했지만 이익도 따라왔다{self.view()}",
                           f"The market already knows — for {n} of {tot}, market cap outgrew earnings{self.view()}"
                           if led else f"Priced in, but earnings kept pace{self.view()}")
        big = mk.largest_t0
        bl = [self.T(f"단순평균 {self.x(mk.mean_multiple)} — 시작 시총의 {mk.largest_t0_share:.0f}%인 {self.name(big)}({self.x(big['multiple'])})가 합계를 낮춤",
                     f"Simple average {self.x(mk.mean_multiple)} — {self.name(big)} ({self.x(big['multiple'])}), {mk.largest_t0_share:.0f}% of starting cap, drags the total")]
        if ok(val):
            bl.append(self.T(f"현재 PER 합산 {self.x(val.agg_per)}, 중앙값 {self.x(val.median_per)} (최근 시총 ÷ {val.fy} 지배순이익)",
                             f"Current P/E aggregate {self.x(val.agg_per)}, median {self.x(val.median_per)} (latest cap ÷ {val.fy} NI)"))
        if ok(dc):
            bl.append(self.T(f"이익 기여 {self.share(dc.agg['earn_share'])} vs 멀티플 기여 {self.share(dc.agg['mult_share'])} ({dc.fy0}→{dc.fy1}, 로그 분해)",
                             f"Earnings {self.share(dc.agg['earn_share'])} vs multiple {self.share(dc.agg['mult_share'])} ({dc.fy0}→{dc.fy1}, log split)"))
        elif ok(val):
            ni0, ni1 = self.fin_sum(int(val.growth_from[2:6]), "ni"), self.fin_sum(int(val.fy[2:6]), "ni")
            bl.append(self.T(f"4사 지배순이익 {val.growth_from}→{val.fy} {self.x(ni1 / ni0)} vs 시총 {self.x(mk.total_multiple)} — FY2022 기준 분해는 수집 후",
                             f"4 names' NI {val.growth_from}→{val.fy} {self.x(ni1 / ni0)} vs cap {self.x(mk.total_multiple)}; FY2022-based split after collection"))
        return BigBox(self.x(mk.total_multiple), self.T(f"4사 시총 합계 기준, {mk.t0}→{mk.t1} (회사별 {self.x(mk.bottom['multiple'])}~{self.x(mk.top['multiple'])})",
                                                        f"4 names, combined cap, {mk.t0}→{mk.t1} (range {self.x(mk.bottom['multiple'])}–{self.x(mk.top['multiple'])})"),
                      title, bl)

    # --- 목차 ---------------------------------------------------------------
    def toc_page(self) -> Page:
        heads = [self.p1(), self.p2(), self.p3(), self.p4(), self.p5()]
        names = [self.T("수요", "Demand"), self.T("현장", "Ground truth"), self.T("실적", "Earnings"),
                 self.T("시장", "Market"), self.T("시사점", "Implications")]
        toc = [(n, nm, h.title, h.label) for n, nm, h in zip(["I", "II", "III", "IV", "V"], names, heads)]
        toc.append(("App.", "Appendix", self.T("A1 예상 질의응답 · A2 데이터 노트(출처·API·기준일·주식수 검산) · A3 What I built · A4 용어",
                                               "A1 Q&A · A2 Data notes (sources, APIs, dates, share-count check) · A3 What I built · A4 Glossary"),
                    "A1–A4"))
        return Page("toc", label="ii", title=self.T("목차", "Contents"),
                    subtitle=self.T("수요 → 현장 → 실적 → 시장 → 시사점: 각 장의 결론", "Demand → ground → earnings → market → implications: "
                                    "the conclusion of each section"), toc=toc)

    # --- p1 수요 ------------------------------------------------------------
    def p1(self) -> Page:
        d, c = self.f.demand, self.c
        if not ok(d):
            u = d
            return Page("body", "1", self.T("수요: 데이터 확인 중", "Demand: data pending"), self.reason(u),
                        [self.pending_cell(self.T("수요", "Demand"), ["iea_ai"], u)] * 4)
        v = d.v
        lo, hi = (v["dc_2035_low"] / v["dc_2035"] - 1) * 100, (v["dc_2035_high"] / v["dc_2035"] - 1) * 100
        top3 = v["region_us"] + v["region_cn"] + v["region_eu"]
        title = self.T(f"수요는 진짜다: 데이터센터 전력 소비는 2030년 {self.x(d.mult_2030)}, 2025년 AI 데이터센터 수요는 {self.pct(v['growth_ai'])}",
                       f"Demand is real: data-centre power use reaches {self.x(d.mult_2030)} by 2030; AI data-centre demand {self.pct(v['growth_ai'])} in 2025")
        sub = self.T(f"IEA 기준 시나리오 2024년 {self.num(v['dc_2024'])}TWh → 2030년 {self.num(v['dc_2030'])}TWh → 2035년 {self.num(v['dc_2035'])}TWh — "
                     f"다만 2035년 범위({self.num(v['dc_2035_low'])}~{self.num(v['dc_2035_high'])}TWh)는 넓다",
                     f"IEA Base Case: {self.num(v['dc_2024'])} TWh (2024) → {self.num(v['dc_2030'])} TWh (2030) → {self.num(v['dc_2035'])} TWh (2035) — "
                     f"but the 2035 range ({self.num(v['dc_2035_low'])}–{self.num(v['dc_2035_high'])} TWh) is wide")
        tw = lambda x: f"{x:,.0f}"  # noqa: E731
        cells = [
            Cell(title=self.T(f"데이터센터 전력 소비 2030E {self.num(v['dc_2030'])}TWh — 2024년의 {self.x(d.mult_2030)}",
                              f"Data-centre power use 2030E {self.num(v['dc_2030'])} TWh — {self.x(d.mult_2030)} 2024"),
                 src=["iea_ai"], legend=[(c["brown_dark"], self.T("2024 추정", "2024 estimate")),
                                          (c["gold"], self.T("2030E 기준 시나리오", "2030E Base Case")),
                                          (c["brown_mid"], self.T("2035E 기준 시나리오", "2035E Base Case"))], unit="TWh",
                 chart_key="dc_outlook",
                 chart=charts.bars(["2024", "2030E", "2035E"], [v["dc_2024"], v["dc_2030"], v["dc_2035"]],
                                   [c["brown_dark"], c["gold"], c["brown_mid"]], c, tw,
                                   notes=["", f"×{d.mult_2030:.1f}", f"×{d.mult_2035:.1f}"]),
                 note=self.T("KSJ Research 계산. 막대 안 배수 = 각 연도 ÷ 2024년",
                             "KSJ Research. Multiples inside bars = year ÷ 2024")),
            Cell(title=self.T(f"2035년 전망 범위 {self.num(v['dc_2035_low'])}~{self.num(v['dc_2035_high'])}TWh — 기준({self.num(v['dc_2035'])}) 대비 {lo:.0f}%~+{hi:.0f}%".replace("-", "−"),
                              f"2035 range {self.num(v['dc_2035_low'])}–{self.num(v['dc_2035_high'])} TWh — {lo:.0f}% to +{hi:.0f}% vs Base Case".replace("-", "−", 1)),
                 src=["iea_ai"], legend=[(c["warm_grey_light"], self.T("2035E 범위", "2035E range")),
                                          (c["gold"], self.T("기준 시나리오", "Base Case"))], unit="TWh", chart_key="range",
                 chart=charts.range_chart([("2024", 0, v["dc_2024"], c["brown_dark"]), ("2030E", 0, v["dc_2030"], c["brown_mid"]),
                                           ("2035E", v["dc_2035_low"], v["dc_2035_high"], c["warm_grey_light"])],
                                          (v["dc_2035"], self.T(f"기준 {self.num(v['dc_2035'])}", f"Base {self.num(v['dc_2035'])}")),
                                          c, tw, v["dc_2035_high"] * 1.18),
                 note=self.T("범위 = IEA가 제시한 2035년 전망 하단~상단. % = 기준 시나리오 대비 (KSJ Research 계산)",
                             "Range = IEA's 2035 low–high; % vs Base Case (KSJ Research)")),
            Cell(title=self.T(f"2024년 데이터센터 전력의 {v['region_us']:.0f}%가 미국 — 미국·중국·유럽이 {top3:.0f}%",
                              f"The U.S. used {v['region_us']:.0f}% of data-centre power in 2024; U.S., China and Europe {top3:.0f}%"),
                 src=["iea_ai"], legend=[(c["gold"], self.T("미국", "U.S.")), (c["brown_mid"], self.T("중국·유럽", "China, Europe")),
                                          (c["warm_grey_light"], self.T("기타(계산)", "Other (calc.)"))], unit="%", chart_key="regions",
                 chart=charts.hbars([self.T("미국", "U.S."), self.T("중국", "China"), self.T("유럽", "Europe"), self.T("기타", "Other")],
                                    [v["region_us"], v["region_cn"], v["region_eu"], d.region_other],
                                    [c["gold"], c["brown_mid"], c["brown_mid"], c["warm_grey_light"]], c,
                                    lambda x: f"{x:.0f}%", left=0.16),
                 note=self.T(f"기타 = 100 − 미국·중국·유럽 (KSJ Research 계산). 데이터센터 전력 2017~2024년 연 {v['cagr_17_24']:.0f}% 증가, "
                             f"2024년 세계 전력의 {v['share_2024']:.1f}%",
                             f"Other = 100 − U.S., China, Europe (KSJ Research). Data-centre power grew {v['cagr_17_24']:.0f}%/yr in "
                             f"2017–2024; {v['share_2024']:.1f}% of world power in 2024")),
            Cell(title=self.T(f"2025년 AI 데이터센터 수요 {self.pct(v['growth_ai'])} — 전 세계 전력({self.pct(v['growth_global'])})의 {d.ai_vs_global:.0f}배 속도",
                              f"AI data-centre demand {self.pct(v['growth_ai'])} in 2025 — {d.ai_vs_global:.0f}x the pace of world power ({self.pct(v['growth_global'])})"),
                 src=["iea_kq"], legend=[(c["gold"], self.T("AI 데이터센터", "AI data centres")),
                                          (c["brown_mid"], self.T("데이터센터 전체", "All data centres")),
                                          (c["warm_grey_light"], self.T("전 세계 전력", "World electricity"))],
                 unit=self.T("2025년 전년 대비 %", "2025, % y/y"), chart_key="growth",
                 chart=charts.bars([self.T("전 세계 전력", "World"), self.T("데이터센터", "Data centres"), self.T("AI 데이터센터", "AI data centres")],
                                   [v["growth_global"], v["growth_dc"], v["growth_ai"]],
                                   [c["warm_grey_light"], c["brown_mid"], c["gold"]], c, lambda x: f"+{x:.0f}%"),
                 note=self.T(f"배수 = {v['growth_ai']:.0f} ÷ {v['growth_global']:.0f} (KSJ Research 계산)",
                             f"Multiple = {v['growth_ai']:.0f} ÷ {v['growth_global']:.0f} (KSJ Research)")),
        ]
        return Page("body", "1", title, sub, cells)

    # --- p2 현장 ------------------------------------------------------------
    def p2(self) -> Page:
        g, s, c = self.f.ground, self.f.sectors, self.c
        cells = []
        if ok(g):
            title = {"ahead": self.T(f"현장에서도 보인다: 버지니아 상업용 전력 판매 {g.base_year}년 대비 {self.pct(g.va_change_pct)}, 미국 전체({self.pct(g.us_change_pct)})를 {g.gap_pts:.0f}p 앞섰다",
                                     f"It shows up on the ground: Virginia commercial sales {self.pct(g.va_change_pct)} since {g.base_year}, {g.gap_pts:.0f} pts ahead of the U.S. ({self.pct(g.us_change_pct)})"),
                     "behind": self.T(f"현장 데이터는 엇갈린다: 버지니아 상업용 판매({self.pct(g.va_change_pct)})가 미국({self.pct(g.us_change_pct)})보다 느렸다",
                                      f"Ground data is mixed: Virginia commercial sales ({self.pct(g.va_change_pct)}) lagged the U.S. ({self.pct(g.us_change_pct)})"),
                     "similar": self.T(f"현장 차이는 아직 작다: 버지니아 {self.pct(g.va_change_pct)} vs 미국 {self.pct(g.us_change_pct)}",
                                       f"The ground gap is small: Virginia {self.pct(g.va_change_pct)} vs U.S. {self.pct(g.us_change_pct)}")}[g.verdict]
            sub = self.T(f"데이터센터 집적지로 알려진 버지니아의 상업용 판매가 미국보다 연 {g.va_cagr_pct - g.us_cagr_pct:.1f}%p 빠르게 늘었다",
                         f"Virginia, known as a data-centre hub, grew commercial sales {g.va_cagr_pct - g.us_cagr_pct:.1f}pp a year faster than the U.S.")
            if ok(s):
                sub += self.T(f" — 미국 상업용 요금은 같은 기간 {self.pct(s.change_pct('price', 'COM'))}",
                              f" — U.S. commercial prices rose {self.pct(s.change_pct('price', 'COM'))}")
            yrs = list(g.index["period"])
            cells.append(Cell(
                title=self.T(f"버지니아 상업용 판매 {self.pct(g.va_change_pct)} vs 미국 {self.pct(g.us_change_pct)} — {g.last_year}년 지수 차이 {g.gap_pts:.0f}p",
                             f"Virginia commercial sales {self.pct(g.va_change_pct)} vs U.S. {self.pct(g.us_change_pct)} — {g.gap_pts:.0f}-pt gap in {g.last_year}"),
                src=["eia"], legend=[(c["gold"], self.T("버지니아", "Virginia")), (c["warm_grey"], self.T("미국 전체", "U.S. total"))],
                unit=self.T(f"지수 ({g.base_year}=100)", f"Index ({g.base_year}=100)"), chart_key="va_us",
                chart=charts.lines(yrs, [(self.T("버지니아", "VA"), list(g.index["VA"]), c["gold"], 2.2),
                                         (self.T("미국", "U.S."), list(g.index["US"]), c["warm_grey"], 1.5)], c,
                                   lambda x: f"{x:.0f}", ref=100),
                note=self.T(f"지수 = 판매량 ÷ {g.base_year}년 × 100 (KSJ Research 계산). 연평균 버지니아 {g.va_cagr_pct:.1f}% vs 미국 {g.us_cagr_pct:.1f}%",
                            f"Index = sales ÷ {g.base_year} × 100 (KSJ Research). CAGR Virginia {g.va_cagr_pct:.1f}% vs U.S. {g.us_cagr_pct:.1f}%")))
        else:
            title, sub = self.T("현장: 데이터 확인 중", "Ground truth: data pending"), self.reason(g)
            cells.append(self.pending_cell(self.T("버지니아 vs 미국 상업용 판매 지수", "Virginia vs U.S. commercial sales index"), ["eia"], g))
        if ok(s):
            secs = [("COM", self.T("상업용", "Commercial"), c["gold"], 2.2), ("RES", self.T("주거용", "Residential"), c["brown_dark"], 1.5),
                    ("IND", self.T("산업용", "Industrial"), c["warm_grey"], 1.5)]
            order = sorted(secs, key=lambda t: -s.change_pct("sales", t[0]))
            yrs = list(s.sales.index)
            cells.append(Cell(
                title=self.T(f"미국 부문별 판매 {s.first_year}→{s.last_year}: " + " · ".join(f"{nm} {self.pct(s.change_pct('sales', k), 1)}" for k, nm, _, _ in order),
                             f"U.S. sales by sector {s.first_year}→{s.last_year}: " + " · ".join(f"{nm} {self.pct(s.change_pct('sales', k), 1)}" for k, nm, _, _ in order)),
                src=["eia"], legend=[(col, nm) for _, nm, col, _ in secs], unit="TWh", chart_key="sectors",
                chart=charts.lines(yrs, [(nm, [x / 1000 for x in s.sales[k]], col, lw) for k, nm, col, lw in secs], c,
                                   lambda x: f"{x:,.0f}"),
                note=self.T("판매량 million kWh ÷ 1,000 = TWh (KSJ Research 계산). 2020년 상업용 감소 구간 포함",
                            "Sales in million kWh ÷ 1,000 = TWh (KSJ Research). Includes the 2020 commercial dip")))
            pc = s.price["COM"]
            mid = s.first_year + (s.last_year - s.first_year) // 2
            c1 = ((pc[mid] / pc[s.first_year]) ** (1 / (mid - s.first_year)) - 1) * 100
            c2 = ((pc[s.last_year] / pc[mid]) ** (1 / (s.last_year - mid)) - 1) * 100
            accel = c2 > c1 + 1
            cells.append(Cell(
                title=self.T(f"상업용 평균 요금 {pc[s.first_year]:.2f}¢ → {pc[s.last_year]:.2f}¢ ({self.pct(s.change_pct('price', 'COM'))})"
                             + (f" — {mid}년 이후 상승 가속" if accel else ""),
                             f"Commercial average price {pc[s.first_year]:.2f}¢ → {pc[s.last_year]:.2f}¢ ({self.pct(s.change_pct('price', 'COM'))})"
                             + (f" — faster rise since {mid}" if accel else "")),
                src=["eia"], legend=[(col, nm) for _, nm, col, _ in secs], unit=self.T("센트/kWh (명목)", "cents/kWh (nominal)"),
                chart_key="price",
                chart=charts.lines(list(s.price.index), [(nm, list(s.price[k]), col, lw) for k, nm, col, lw in secs], c,
                                   lambda x: f"{x:.1f}"),
                note=self.T(f"상업용 연평균 상승률 {s.first_year}~{mid} {c1:.1f}% → {mid}~{s.last_year} {c2:.1f}% (KSJ Research 계산)",
                            f"Commercial price CAGR {s.first_year}–{mid} {c1:.1f}% → {mid}–{s.last_year} {c2:.1f}% (KSJ Research)")))
        else:
            for t in (self.T("미국 부문별 판매 추이", "U.S. sales by sector"), self.T("상업용 평균 요금", "Commercial price")):
                cells.append(self.pending_cell(t, ["eia"], s))
        if ok(g):
            y = g.yoy[g.yoy["period"] >= g.last_year - 7].reset_index(drop=True)
            rows = [[str(int(r["period"])), self.pct(r["VA"], 1), self.pct(r["US"], 1), f"{r['VA'] - r['US']:+.1f}p"]
                    for _, r in y.iterrows()]
            n = len(rows)
            best = int((y["VA"] - y["US"]).idxmax())
            cells.append(Cell(
                title=self.T(f"최근 3년 연평균 버지니아 {g.va_recent_cagr_pct:.1f}% vs 미국 {g.us_recent_cagr_pct:.1f}%",
                             f"Last 3 years CAGR: Virginia {g.va_recent_cagr_pct:.1f}% vs U.S. {g.us_recent_cagr_pct:.1f}%"),
                src=["eia"], unit=self.T("전년 대비 %, 차이는 %p", "% y/y; gap in pp"),
                table=TableSpec([self.T("연도", "Year"), self.T("버지니아", "Virginia"), self.T("미국 전체", "U.S. total"),
                                 self.T("차이", "Gap")], rows, [0.22, 0.26, 0.26, 0.26], ["C", "R", "R", "R"],
                                shade_rows={n - 3, n - 2, n - 1}, gold_cells={(best, 3)},
                                strong_cells={(i, 1) for i in range(n - 3, n)},
                                brick_cells={(i, j) for i, (_, r) in enumerate(y.iterrows()) for j, val in ((1, r["VA"]), (2, r["US"])) if val < 0},
                                font_size=8.6),
                note=self.T(f"상업용 판매 전년 대비 증가율 (KSJ Research 계산). 음영 = 최근 3년, 골드 = 차이 최대({int(y.loc[best, 'period'])}년)",
                            f"Commercial sales growth y/y (KSJ Research). Shaded = last 3 years; gold = largest gap ({int(y.loc[best, 'period'])})")))
        else:
            cells.append(self.pending_cell(self.T("연도별 증가율", "Growth by year"), ["eia"], g))
        return Page("body", "2", title, sub, cells)

    # --- p3 실적 ------------------------------------------------------------
    def p3(self) -> Page:
        fin, c, mk = self.f.fin, self.c, self.f.market
        if not ok(fin):
            return Page("body", "3", self.T("실적: 데이터 확인 중", "Earnings: data pending"), self.reason(fin),
                        [self.pending_cell(self.T("실적", "Earnings"), ["dart"], fin)] * 4)
        t, yrs = fin.table, fin.years
        y0, y1 = yrs[0], yrs[-1]
        peers = list(dict.fromkeys(t["ticker"]))
        nm = {r["ticker"]: self.name(r) for _, r in t.iterrows()}
        rev0, rev1 = self.fin_sum(y0, "revenue"), self.fin_sum(y1, "revenue")
        op0, op1 = self.fin_sum(y0, "op"), self.fin_sum(y1, "op")
        ni0, ni1 = self.fin_sum(y0, "ni"), self.fin_sum(y1, "ni")
        missing = fin.missing_years
        miss_note = self.T(f" FY{', FY'.join(map(str, missing))}A는 수집 후 추가 ({CMD_DART})",
                           f" FY{', FY'.join(map(str, missing))}A added after collection ({CMD_DART})") if missing else ""
        slower = ok(mk) and ni1 / ni0 < mk.total_multiple
        title = self.T(f"실적도 늘었다: 4사 지배순이익 합계 FY{y0}A→FY{y1}A {self.x(ni1 / ni0)}"
                       + (f" — 다만 시총({self.x(mk.total_multiple)})보다 느렸다" if slower else ""),
                       f"Earnings grew too: 4 names' NI to parent {self.x(ni1 / ni0)} from FY{y0}A to FY{y1}A"
                       + (f" — but slower than market cap ({self.x(mk.total_multiple)})" if slower else ""))
        sub = self.T(f"4사 합계 매출 {self.pct((rev1 / rev0 - 1) * 100)}, 영업이익 {self.pct((op1 / op0 - 1) * 100)} (FY{y0}A→FY{y1}A, 연결 기준)",
                     f"4 names combined: revenue {self.pct((rev1 / rev0 - 1) * 100)}, operating profit {self.pct((op1 / op0 - 1) * 100)} (FY{y0}A→FY{y1}A, consolidated)")
        fy_colors = {2022: c["warm_grey_light"], 2023: c["warm_grey"], 2024: c["brown_mid"], 2025: c["gold"]}
        # 1) 매출
        rg = {tk: (fin.value(tk, y1, "revenue") / fin.value(tk, y0, "revenue") - 1) * 100 for tk in peers}
        top = max(rg, key=rg.get)
        cats = [nm[tk] for tk in peers]
        rev_series = [(f"FY{y}A", [fin.value(tk, y, "revenue") or float("nan") for tk in peers], fy_colors.get(y, c["warm_grey"])) for y in yrs]
        cells = [Cell(
            title=self.T(f"4사 매출 FY{y0}A→FY{y1}A: 합계 {self.pct((rev1 / rev0 - 1) * 100)}, {nm[top]} {self.pct(rg[top])}로 최대",
                         f"Revenue FY{y0}A→FY{y1}A: combined {self.pct((rev1 / rev0 - 1) * 100)}; {nm[top]} leads at {self.pct(rg[top])}"),
            src=["dart"], legend=[(col, lab) for lab, _, col in rev_series], unit=self.T("억원", "KRW 100mn"),
            chart_key="revenue", chart=charts.grouped(cats, rev_series, c, lambda x: f"{x:,.0f}", label_series={len(rev_series) - 1}),
            note=self.T("연결 기준(없으면 별도), 사업보고서 당기 금액. 막대 위 값 = 최근 연도." + miss_note,
                        "Consolidated (separate if unavailable), as reported. Labels = latest year." + miss_note))]
        # 2) 영업이익률
        opm = {tk: [fin.value(tk, y, "opm") for y in yrs] for tk in peers}
        best = max(peers, key=lambda tk: opm[tk][-1])
        n_up = sum(1 for tk in peers if opm[tk][-1] > opm[tk][0])
        cells.append(Cell(
            title=self.T(f"영업이익률 FY{y1}A {nm[best]} {opm[best][-1]:.1f}% 최고 — {len(peers)}사 중 {n_up}곳 개선",
                         f"Operating margin FY{y1}A: {nm[best]} highest at {opm[best][-1]:.1f}%; {n_up} of {len(peers)} improved"),
            src=["dart"], legend=[(c[COMPANY_COLORS[i]], nm[tk]) for i, tk in enumerate(peers)], unit="%", chart_key="opm",
            chart=charts.lines(yrs, [(nm[tk], opm[tk], c[COMPANY_COLORS[i]], 2.0 if i == 0 else 1.5) for i, tk in enumerate(peers)],
                               c, lambda x: f"{x:.1f}%", right=0.66),
            note=self.T("영업이익률 = 영업이익 ÷ 매출 (KSJ Research 계산)." + miss_note,
                        "Operating margin = operating profit ÷ revenue (KSJ Research)." + miss_note)))
        # 3) 지배순이익 증가율
        yoy_years = [y for y in yrs if y - 1 in yrs]
        series = [(f"FY{y}A", [fin.value(tk, y, "ni_yoy") if fin.value(tk, y, "ni_yoy") is not None else float("nan") for tk in peers],
                   fy_colors.get(y, c["brown_mid"])) for y in yoy_years]
        nim = {tk: fin.value(tk, y1, "ni") / fin.value(tk, y0, "ni") for tk in peers if (fin.value(tk, y0, "ni") or 0) > 0}
        topn = max(nim, key=nim.get)
        cells.append(Cell(
            title=self.T(f"지배순이익 FY{y0}A→FY{y1}A: 4사 합계 {self.x(ni1 / ni0)}, {nm[topn]} {self.x(nim[topn])}로 최대",
                         f"NI to parent FY{y0}A→FY{y1}A: combined {self.x(ni1 / ni0)}; {nm[topn]} leads at {self.x(nim[topn])}"),
            src=["dart"], legend=[(col, lab) for lab, _, col in series] + [(c["brick"], self.T("감소", "Decline"))],
            unit=self.T("전년 대비 %", "% y/y"), chart_key="ni_yoy",
            chart=charts.grouped(cats, series, c, lambda x: f"{x:+.0f}%", zero_line=True),
            note=self.T("지배기업 소유주 귀속 당기순이익. 직전 연도 적자면 증가율 생략." + miss_note,
                        "Net income attributable to owners of the parent; growth omitted after a loss year." + miss_note)))
        # 4) 재무 요약표
        rows, gold = [], set()
        for i, tk in enumerate(peers):
            rv, o, n, m = (fin.value(tk, y1, k) for k in ("revenue", "op", "ni", "opm"))
            rows.append([nm[tk], self.num(rv), self.num(o), f"{m:.1f}%", self.num(n), self.x(nim.get(tk, float("nan")))])
            if tk == topn:
                gold.add((i, 5))
        rows.append([self.T("4사 합계", "Total"), self.num(rev1), self.num(op1), f"{op1 / rev1 * 100:.1f}%", self.num(ni1), self.x(ni1 / ni0)])
        k = len(rows) - 1
        cells.append(Cell(
            title=self.T(f"FY{y1}A 4사 합계 매출 {self.num(rev1)}억원 · 영업이익 {self.num(op1)}억원 · 지배순이익 {self.num(ni1)}억원",
                         f"FY{y1}A combined: revenue {self.num(rev1)}, OP {self.num(op1)}, NI {self.num(ni1)} (KRW 100mn)"),
            src=["dart"], unit=self.T("억원, %, 배", "KRW 100mn, %, x"),
            table=TableSpec([self.T("회사", "Company"), self.T("매출", "Revenue"), self.T("영업이익", "OP"), self.T("영업이익률", "OPM"),
                             self.T("지배순이익", "NI"), self.T(f"순이익 배수 FY{y0}→{y1}", f"NI x FY{y0}→{y1}")],
                            rows, [0.25, 0.15, 0.14, 0.14, 0.14, 0.18], shade_rows={k}, bold_rows={k}, gold_cells=gold,
                            strong_cells={(k, 5)}, font_size=8.4),
            note=self.T(f"FY{y1}A 연결 기준. 순이익 배수 = FY{y1}A ÷ FY{y0}A 지배순이익 (KSJ Research 계산)",
                        f"FY{y1}A consolidated. NI multiple = FY{y1}A ÷ FY{y0}A (KSJ Research)")))
        return Page("body", "3", title, sub, cells)

    # --- p4 시장 (핵심) -------------------------------------------------------
    def p4(self) -> Page:
        mk, dc, val, c = self.f.market, self.f.decomp, self.f.val, self.c
        if not ok(mk):
            return Page("body", "4", self.T("시장: 데이터 확인 중", "Market: data pending"), self.reason(mk),
                        [self.pending_cell(self.T("시장", "Market"), ["krx"], mk)] * 4)
        led = self.multiple_led()
        if ok(dc):
            a = dc.agg
            title = (self.T(f"시장은 이미 알고 있다: 4사 시총 증가의 {self.share(a['mult_share'])}는 멀티플 확대, {self.share(a['earn_share'])}는 이익 증가",
                            f"The market already knows: {self.share(a['mult_share'])} of the 4 names' gain is multiple expansion, {self.share(a['earn_share'])} earnings")
                     if led else
                     self.T(f"이익이 주도했다: 4사 시총 증가의 {self.share(a['earn_share'])}는 이익 증가, {self.share(a['mult_share'])}는 멀티플",
                            f"Earnings led: {self.share(a['earn_share'])} of the gain is earnings growth, {self.share(a['mult_share'])} multiple")) + self.view()
            sub = self.T(f"4사 합산 PER {self.x(a['per0'])} → {self.x(a['per1'])} · 시총 배수 = 지배순이익 배수 × PER 배수 ({dc.fy0}→{dc.fy1})",
                         f"Aggregate P/E {self.x(a['per0'])} → {self.x(a['per1'])} · market-cap multiple = NI multiple × P/E multiple ({dc.fy0}→{dc.fy1})")
        else:
            title = self.T(f"시장은 이미 크게 움직였다: 4사 시총 {self.market_basis()}",
                           f"The market has already moved: 4 names' market cap {self.market_basis()}")
            if ok(val):
                n, tot = self.n_mcap_beats_ni()
                sub = self.T(f"가용 실적({val.growth_from}→{val.fy})으로도 {tot}사 중 {n}곳은 시총 배수가 지배순이익 배수를 웃돈다 — FY2022 기준 분해는 수집 후",
                             f"Even on available earnings ({val.growth_from}→{val.fy}), {n} of {tot} saw market cap outgrow NI — FY2022-based split after collection")
            else:
                sub = self.T("이익·멀티플 분해는 FY2022 수집 후", "Earnings/multiple split after FY2022 collection")
        t = mk.table
        split_rows = t[t["split_factor"] != 1]
        split_note = ""
        for _, r in split_rows.iterrows():
            split_note += self.T(f" {r['company']}: {r['action_date']} {r['split_factor']:.0f}:1 액면분할 — 주가 배수 {r['price_multiple_raw']:.1f}배가 아닌 시총 배수 {r['multiple']:.1f}배 사용"
                                 f"(분할 조정 주가 배수 {r['price_multiple_adj']:.1f}배와 일치).",
                                 f" {r['company_en']}: {r['split_factor']:.0f}:1 split on {r['action_date']} — we use the market-cap multiple "
                                 f"{r['multiple']:.1f}x, not the raw price multiple {r['price_multiple_raw']:.1f}x (split-adjusted {r['price_multiple_adj']:.1f}x).")
        big = mk.largest_t0
        cells = [Cell(
            title=self.T(f"4사 시총: 합계 기준 {self.x(mk.total_multiple)} · 단순평균 {self.x(mk.mean_multiple)} — 회사별 {self.x(mk.bottom['multiple'])}~{self.x(mk.top['multiple'])}",
                         f"Market cap: {self.x(mk.total_multiple)} combined · {self.x(mk.mean_multiple)} simple average — {self.x(mk.bottom['multiple'])} to {self.x(mk.top['multiple'])} by name"),
            src=["krx", "corp"], legend=[(c["warm_grey_light"], mk.t0), (c["brown_dark"], mk.t1), (c["gold"], self.T("시총 배수", "Mkt-cap x"))],
            unit=self.T("억원", "KRW 100mn"), chart_key="mcap",
            chart=charts.grouped([self.name(r) for _, r in t.iterrows()],
                                 [(mk.t0, list(t["mcap_t0"]), c["warm_grey_light"]), (mk.t1, list(t["mcap_t1"]), c["brown_dark"])],
                                 c, lambda x: f"{x:,.0f}", label_series={1}, horizontal=True,
                                 extra_labels=[f"×{m:.1f}" for m in t["multiple"]], left=0.25),
            note=self.T(f"시총 = 각 시점 종가 × 그 시점 상장주식수(KRX MKTCAP). 합계 기준은 시작 시총의 {mk.largest_t0_share:.0f}%인 {big['company']}({big['multiple']:.1f}배)의 비중이 커 단순평균보다 낮다." + split_note,
                        f"Market cap = close × listed shares at each date (KRX MKTCAP). The combined multiple is below the average because "
                        f"{big['company_en']} ({big['multiple']:.1f}x) was {mk.largest_t0_share:.0f}% of the starting cap." + split_note))]
        decomp_note = self.T("로그 분해 Δln(시총) = Δln(지배순이익) + Δln(PER). 2023 초 시총 ↔ FY2022A, 최근 시총 ↔ FY2025A 지배순이익. "
                             "억원 배분 = Δ시총 × 각 항의 로그 비중 (KSJ Research 계산)",
                             "Log split Δln(cap) = Δln(NI) + Δln(P/E). Start-2023 cap ↔ FY2022A, latest cap ↔ FY2025A NI to parent. "
                             "KRW split = Δcap × each term's log share (KSJ Research)")
        if ok(dc):
            a = dc.agg
            cells.append(Cell(
                title=self.T(f"시총 증가 {self.num(a['d_mcap'])}억원 = 이익 기여 {self.num(a['earn_part'])}억원 + 멀티플 기여 {self.num(a['mult_part'])}억원",
                             f"Cap gain {self.num(a['d_mcap'])} = earnings {self.num(a['earn_part'])} + multiple {self.num(a['mult_part'])} (KRW 100mn)"),
                src=["krx", "dart"], legend=[(c["brown_dark"], mk.t0), (c["brown_mid"], self.T("기여(+)", "Contribution (+)")),
                                              (c["brick"], self.T("기여(−)", "Contribution (−)")), (c["gold"], mk.t1)],
                unit=self.T("억원 (분해 가능 기업 합산)", "KRW 100mn (names with positive NI)"), chart_key="waterfall",
                chart=charts.waterfall([(mk.t0, a["mcap0"], "total"), (self.T("이익 기여", "Earnings"), a["earn_part"], "delta"),
                                        (self.T("멀티플 기여", "Multiple"), a["mult_part"], "delta"), (mk.t1, a["mcap1"], "total")],
                                       c, lambda x: f"{x:,.0f}"),
                note=decomp_note + (self.T(f" 합산 대상 {a['n_in_agg']}사.", f" {a['n_in_agg']} names included.") if a["n_in_agg"] < len(t) else "")))
        else:
            cells.append(self.pending_cell(self.T("시총 변화 분해: 이익 기여 vs 멀티플 기여 (FY2022A 기준)", "Market-cap change split: earnings vs multiple (FY2022A base)"),
                                           ["krx", "dart"], dc, note=decomp_note))
        # PER
        if ok(val):
            names = [self.name(r) for _, r in val.per.iterrows()]
            if ok(dc):
                d = dc.table.set_index("ticker")
                ser = [(self.T("2023 초 (FY2022A)", "Start-2023 (FY2022A)"), [d.loc[tk, "per0"] if d.loc[tk, "valid"] else float("nan") for tk in val.per["ticker"]], c["warm_grey_light"]),
                       (self.T("최근 (FY2025A)", "Latest (FY2025A)"), list(val.per["per"]), c["gold"])]
                ttl = self.T(f"PER 4사 합산 {self.x(dc.agg['per0'])} → {self.x(dc.agg['per1'])} — {dc.n_multiple_led}사에서 멀티플 기여가 이익 기여보다 컸다",
                             f"Aggregate P/E {self.x(dc.agg['per0'])} → {self.x(dc.agg['per1'])}; multiple outweighed earnings for {dc.n_multiple_led} names")
                pnote = self.T("PER = 시가총액 ÷ 지배순이익 (KSJ Research 계산). 로그 축", "P/E = market cap ÷ NI to parent (KSJ Research). Log scale")
            else:
                ser = [(self.T("최근 (FY2025A)", "Latest (FY2025A)"), list(val.per["per"]), c["gold"])]
                hi = val.per.sort_values("per", ascending=False).iloc[0]
                ttl = self.T(f"현재 PER: 합산 {self.x(val.agg_per)} · 중앙값 {self.x(val.median_per)} — {hi['company']} {self.x(hi['per'], 0)}는 작은 이익의 영향",
                             f"Current P/E: aggregate {self.x(val.agg_per)} · median {self.x(val.median_per)} — {hi['company_en']} {self.x(hi['per'], 0)} reflects thin earnings")
                pnote = self.T(f"PER = 최근 시총 ÷ {val.fy} 지배순이익 (KSJ Research 계산). 로그 축. 2023 초 PER(FY2022A 기준)은 수집 후 표시 ({CMD_DART})",
                               f"P/E = latest cap ÷ {val.fy} NI (KSJ Research). Log scale. Start-2023 P/E (FY2022A) shown after collection ({CMD_DART})")
            cells.append(Cell(title=ttl, src=["krx", "dart"], legend=[(col, lab) for lab, _, col in ser],
                              unit=self.T("배 (로그 축)", "x (log scale)"), chart_key="per",
                              chart=charts.grouped(names, ser, c, lambda x: f"{x:,.1f}", horizontal=True, log=True, left=0.25),
                              note=pnote))
        else:
            cells.append(self.pending_cell(self.T("PER: 2023 초 vs 최근", "P/E: start-2023 vs latest"), ["krx", "dart"], val))
        # 분해 결과표
        if ok(dc):
            rows, gold, brick = [], set(), set()
            for i, (_, r) in enumerate(dc.table.iterrows()):
                if not r["valid"]:
                    rows.append([self.name(r), self.x(r["mcap_t1"] / r["mcap_t0"]), "n/a", "n/a", "n/a", self.T("분해 불가(적자)", "n/a (loss)")])
                    continue
                rows.append([self.name(r), self.x(r["mcap_t1"] / r["mcap_t0"]), self.x(r["ni1"] / r["ni0"]), self.x(r["per1"] / r["per0"]),
                             self.share(r["earn_share"]), self.share(r["mult_share"])])
                if r["mult_share"] > 0.5:
                    gold.add((i, 5))
                for j, val_ in ((4, r["earn_share"]), (5, r["mult_share"])):
                    if val_ < 0:
                        brick.add((i, j))
            a = dc.agg
            rows.append([self.T("4사 합산", "Aggregate"), self.x(a["mcap1"] / a["mcap0"]), self.x(a["ni1"] / a["ni0"]), self.x(a["per1"] / a["per0"]),
                         self.share(a["earn_share"]), self.share(a["mult_share"])])
            k = len(rows) - 1
            n_led = dc.n_multiple_led
            cells.append(Cell(
                title=self.T(f"{dc.n_valid}사 중 {n_led}곳은 멀티플 기여가 이익 기여보다 컸다 — 합산 멀티플 기여 {self.share(a['mult_share'])}",
                             f"Multiple outweighed earnings for {n_led} of {dc.n_valid} names; aggregate multiple share {self.share(a['mult_share'])}"),
                src=["krx", "dart"], unit=self.T("배, 로그 기여 비중 %", "x, share of log change %"),
                table=TableSpec([self.T("회사", "Company"), self.T("시총 배수", "Cap x"), self.T("지배순이익 배수", "NI x"), self.T("PER 배수", "P/E x"),
                                 self.T("이익 기여", "Earnings"), self.T("멀티플 기여", "Multiple")], rows,
                                [0.26, 0.14, 0.17, 0.14, 0.14, 0.15], shade_rows={k}, bold_rows={k}, gold_cells=gold | {(k, 5)},
                                brick_cells=brick, font_size=8.6),
                note=self.T("기여 비중 = Δln(지배순이익)/Δln(시총), Δln(PER)/Δln(시총). 시총 배수 = 지배순이익 배수 × PER 배수 (검산: 표 값 곱 = 시총 배수)",
                            "Shares = Δln(NI)/Δln(cap), Δln(P/E)/Δln(cap). Cap x = NI x × P/E x (check: product of columns = cap x)")))
        else:
            cells.append(self.pending_cell(self.T("회사별 분해 결과표 (FY2022A 기준)", "Split by company (FY2022A base)"), ["krx", "dart"], dc,
                                           note=self.T("표 열: 시총 배수 · 지배순이익 배수 · PER 배수 · 이익 기여 · 멀티플 기여",
                                                       "Columns: cap x · NI x · P/E x · earnings share · multiple share")))
        return Page("body", "4", title, sub, cells)

    # --- p5 시사점 ------------------------------------------------------------
    def p5(self) -> Page:
        c, d, g, s, mk, val, r, fin = self.c, self.f.demand, self.f.ground, self.f.sectors, self.f.market, self.f.val, self.f.rates, self.f.fin
        led = self.multiple_led()
        title = self.T("그래서 Vol.2: " + ("멀티플이 높아진 섹터에서 IPO 공모가는 어떻게 정하나" if led else "이익이 이끈 섹터에서 IPO 공모가는 어떻게 정하나") + self.view(),
                       "Hence Vol.2: how to price an IPO in a sector whose multiples have " + ("re-rated" if led else "followed earnings") + self.view())
        sub = self.T("세 렌즈(ECM 공모가 · 데이터센터 PF · 증설 옵션)와 네 가지 리스크로 본 시사점",
                     "Implications through three lenses (ECM pricing · data-centre PF · capacity options) and four risks")
        ecm_data = (self.T(f"피어 현재 PER 중앙값 {self.x(val.median_per)}, 합산 {self.x(val.agg_per)}; 시총 {self.market_basis()}",
                           f"Peer P/E median {self.x(val.median_per)}, aggregate {self.x(val.agg_per)}; cap {self.market_basis()}")
                    if ok(val) and ok(mk) else self.T("데이터 확인 중", "pending"))
        pf_data = (self.T(f"버지니아 상업용 판매 연 {g.va_cagr_pct:.1f}%" + (f", 미국 상업용 요금 {self.pct(s.change_pct('price', 'COM'))} ({s.first_year}→{s.last_year})" if ok(s) else ""),
                          f"Virginia commercial sales {g.va_cagr_pct:.1f}%/yr" + (f"; U.S. commercial price {self.pct(s.change_pct('price', 'COM'))} ({s.first_year}→{s.last_year})" if ok(s) else ""))
                   if ok(g) else self.T("데이터 확인 중", "pending"))
        if ok(fin) and ok(d):
            y0, y1 = fin.years[0], fin.years[-1]
            rv = (self.fin_sum(y1, "revenue") / self.fin_sum(y0, "revenue") - 1) * 100
            best = fin.table[fin.table["fy"] == y1].sort_values("opm", ascending=False).iloc[0]
            cap_data = self.T(f"4사 매출 {self.pct(rv)} (FY{y0}A→FY{y1}A), 최고 영업이익률 {best['opm']:.1f}%; IEA 2035 범위 {self.num(d.v['dc_2035_low'])}~{self.num(d.v['dc_2035_high'])}TWh",
                              f"Revenue {self.pct(rv)} (FY{y0}A→FY{y1}A); top OPM {best['opm']:.1f}%; IEA 2035 range {self.num(d.v['dc_2035_low'])}–{self.num(d.v['dc_2035_high'])} TWh")
        else:
            cap_data = self.T("데이터 확인 중", "pending")
        lens_rows = [
            [self.T("ECM 공모가", "ECM pricing"), ecm_data,
             self.T("피어 멀티플이 이익보다 앞서 오른 구간에서는 피어 PER을 그대로 쓰기보다 이익 추정의 보수성과 공모 할인으로 방어해야 한다" if led
                    else "피어 멀티플이 이익을 따라온 구간이라 이익 추정의 신뢰성이 공모가의 핵심이다",
                    "When peer multiples have run ahead of earnings, defend the price with conservative earnings and an IPO discount rather than raw peer P/E"
                    if led else "With multiples tracking earnings, the credibility of the earnings forecast drives pricing")],
            [self.T("데이터센터 PF", "Data-centre PF"), pf_data,
             self.T("물량과 요금이 함께 오른 지역에서는 전력구매계약·계통 접속 일정이 PF 현금흐름의 핵심 변수다",
                    "Where volume and price rise together, PPAs and grid-connection timing are the key PF cash-flow variables")],
            [self.T("증설 옵션", "Capacity options"), cap_data,
             self.T("2035년 전망 범위가 넓어 한 번에 짓기보다 단계적 증설로 수요 확인 후 확장하는 구조가 유리하다",
                    "With a wide 2035 range, phased capacity additions that expand as demand is confirmed are preferable")],
        ]
        cells = [Cell(title=self.T("세 렌즈로 본 시사점: 데이터 → 판단", "Three lenses: data → judgement"), src=["krx", "dart", "eia", "iea_ai"],
                      table=TableSpec([self.T("렌즈", "Lens"), self.T("데이터가 말하는 것", "What the data says"),
                                       self.T("시사점 (저자 견해)", "Implication (author's view)")], lens_rows, [0.17, 0.38, 0.45],
                                      ["L", "L", "L"], shade_rows={0}, font_size=8.2),
                      note=self.T("데이터 열의 숫자는 p1~p4에서 계산한 값", "Figures in the data column come from pages 1–4"))]
        # 리스크 매트릭스
        names = {"outlook": self.T("전망 불확실성", "Outlook uncertainty"), "cycle_peak": self.T("사이클 고점", "Cycle peak"),
                 "rates": self.T("금리", "Rates"), "supply_chain": self.T("공급망", "Supply chain")}
        pts = [(names[p["key"]], p["likelihood"], p["impact"]) for p in self.v["risk_matrix"]]
        top2 = sorted(self.v["risk_matrix"], key=lambda p: -(p["likelihood"] * p["impact"]))[:2]
        anchors = []
        if ok(d):
            anchors.append(self.T(f"IEA 2035 범위 기준 대비 ±{(d.v['dc_2035_high'] / d.v['dc_2035'] - 1) * 100:.0f}%",
                                  f"IEA 2035 range ±{(d.v['dc_2035_high'] / d.v['dc_2035'] - 1) * 100:.0f}% vs base"))
        if ok(val):
            anchors.append(self.T(f"현재 PER 중앙값 {self.x(val.median_per)}", f"current P/E median {self.x(val.median_per)}"))
        if ok(r) and r.ktb10_t0 is not None:
            anchors.append(self.T(f"국고채 10년 {r.ktb10_t0:.2f}→{r.ktb10_t1:.2f}%", f"KTB 10y {r.ktb10_t0:.2f}→{r.ktb10_t1:.2f}%"))
        if ok(r) and r.ust10_t0 is not None:
            anchors.append(self.T(f"미 국채 10년 {r.ust10_t0:.2f}→{r.ust10_t1:.2f}% ({r.d0}→{r.ust_d1})",
                                  f"UST 10y {r.ust10_t0:.2f}→{r.ust10_t1:.2f}% ({r.d0}→{r.ust_d1})"))
        anchors.append(self.T("공급망은 정성 판단", "supply chain is qualitative"))
        cells.append(Cell(
            title=self.T(f"리스크 매트릭스: {names[top2[0]['key']]}·{names[top2[1]['key']]}이 핵심{self.view()}",
                         f"Risk matrix: {names[top2[0]['key']].lower()} and {names[top2[1]['key']].lower()} matter most{self.view()}"),
            src=["iea_ai", "ecos", "fred"], legend=[(c["brick"], self.T("핵심(가능성·영향 높음)", "Key (high likelihood and impact)")),
                                                     (c["brown_dark"], self.T("관찰", "Watch"))],
            unit=self.T("정성 1~5", "qualitative 1–5"), chart_key="risk",
            chart=charts.risk_matrix(pts, c, self.T("발생 가능성 →", "Likelihood →"), self.T("영향 →", "Impact →"),
                                     (self.T("낮음", "Low"), self.T("높음", "High"))),
            note=self.T("근거: " + " · ".join(anchors) + ". 위치는 저자 정성 판단(config ASSUMPTION)",
                        "Anchors: " + " · ".join(anchors) + ". Positions are the author's judgement (config ASSUMPTION)")))
        cells.append(Cell(
            title=self.T("Vol.2 예고: 가상 비상장 전력기기 기업의 희망공모가 밴드", "Next in Vol.2: price range for a hypothetical unlisted power-equipment IPO"),
            panel_lead=self.T("멀티플이 높아진 섹터에서 IPO 공모가는 어떻게 정하나" if led else "이익이 이끈 섹터에서 IPO 공모가는 어떻게 정하나",
                              "How to price an IPO when sector multiples have re-rated" if led else "How to price an IPO when earnings lead"),
            bullets=[self.T("가상 기업 Target Co. 설정 — 사업·재무 가정은 모두 ASSUMPTION으로 공개", "Set up Target Co. — every business and financial assumption disclosed"),
                     self.T("피어 PER·EV/EBITDA 산출: 국내 4사 + 해외 peers(SEC 수집 재개 후)", "Peer P/E and EV/EBITDA: 4 Korean names + overseas peers (after SEC resumes)"),
                     self.T("적정 시총 → 공모 할인 → 희망공모가 밴드", "Fair value → IPO discount → indicative price range"),
                     self.T("몬테카를로로 밴드 민감도 점검", "Monte Carlo sensitivity of the range")],
            note=self.T("Vol.2 일정·방법은 변경될 수 있음", "Timing and method of Vol.2 may change")))
        cells.append(Cell(
            title=self.T("이 노트의 한계", "Limitations of this note"),
            bullets=[self.T("현장 데이터는 상업용 판매만 봤다. 데이터센터 부하는 주에 따라 산업용으로 분류될 수 있다", "Ground data covers commercial sales only; data-centre load may be classified as industrial"),
                     self.T("IEA 수치는 보고서 요약값을 원문 대조해 수기 입력했다", "IEA figures are summary values entered manually and checked against the source"),
                     self.T("시총 구간(2023.1~2026.10)과 실적 구간(FY2022A~FY2025A)은 완전히 일치하지 않는다", "The market window (Jan 2023–Oct 2026) and earnings window (FY2022A–FY2025A) do not match exactly"),
                     self.T("PER은 지배순이익 기준이며 일회성 손익을 조정하지 않았다. 이익이 작은 회사는 PER이 크게 왜곡된다", "P/E uses reported NI without one-off adjustments; thin earnings distort P/E"),
                     self.T("표본은 국내 4사다. 해외 peers(SEC)는 준비 중이다", "The sample is four Korean names; overseas peers (SEC) are in progress")],
            note=self.T("한계는 Vol.2 이후 순차 보완", "To be addressed from Vol.2 onward")))
        return Page("body", "5", title, sub, cells)

    # --- Appendix -----------------------------------------------------------
    def a1(self) -> Page:
        d, g, mk, dc, val, fin = self.f.demand, self.f.ground, self.f.market, self.f.decomp, self.f.val, self.f.fin
        qa = []
        if ok(d):
            qa.append([self.T("AI 전력 수요는 과장 아닌가?", "Isn't AI power demand overhyped?"),
                       self.T(f"IEA 기준 2030E {self.num(d.v['dc_2030'])}TWh(2024년의 {self.x(d.mult_2030)}), 2025년 AI 데이터센터 {self.pct(d.v['growth_ai'])} vs 전 세계 {self.pct(d.v['growth_global'])}. "
                              f"다만 2035년 범위 {self.num(d.v['dc_2035_low'])}~{self.num(d.v['dc_2035_high'])}TWh로 불확실성은 크다",
                              f"IEA: {self.num(d.v['dc_2030'])} TWh in 2030E ({self.x(d.mult_2030)} 2024); AI data centres {self.pct(d.v['growth_ai'])} in 2025 vs world {self.pct(d.v['growth_global'])}. "
                              f"The 2035 range ({self.num(d.v['dc_2035_low'])}–{self.num(d.v['dc_2035_high'])} TWh) is wide"), "1"])
        if ok(g):
            qa.append([self.T("버지니아만의 특수 사례 아닌가?", "Isn't Virginia a special case?"),
                       self.T(f"한 주의 사례인 것은 맞다. 다만 상업용 판매가 {g.base_year}년 대비 {self.pct(g.va_change_pct)}(미국 {self.pct(g.us_change_pct)}), 최근 3년 연 {g.va_recent_cagr_pct:.1f}%로 차이가 커지고 있다. 산업용 분류 가능성은 한계로 둔다",
                              f"It is one state. But commercial sales are {self.pct(g.va_change_pct)} since {g.base_year} (U.S. {self.pct(g.us_change_pct)}) and the gap is widening ({g.va_recent_cagr_pct:.1f}%/yr over 3 years). Industrial classification is a stated limitation"), "2, 5"])
        if ok(fin):
            y0, y1 = fin.years[0], fin.years[-1]
            qa.append([self.T("실적이 받쳐주나?", "Do earnings support it?"),
                       self.T(f"4사 지배순이익 합계 FY{y0}A→FY{y1}A {self.x(self.fin_sum(y1, 'ni') / self.fin_sum(y0, 'ni'))}, 매출 {self.pct((self.fin_sum(y1, 'revenue') / self.fin_sum(y0, 'revenue') - 1) * 100)}. 이익은 늘었지만 시총보다는 느렸다",
                              f"Combined NI {self.x(self.fin_sum(y1, 'ni') / self.fin_sum(y0, 'ni'))} FY{y0}A→FY{y1}A; revenue {self.pct((self.fin_sum(y1, 'revenue') / self.fin_sum(y0, 'revenue') - 1) * 100)}. Earnings grew, but slower than market cap"), "3"])
        if ok(mk):
            if ok(dc):
                ans = self.T(f"그렇다고 본다. 4사 시총 증가의 {self.share(dc.agg['mult_share'])}가 멀티플 확대({dc.fy0}→{dc.fy1}, 로그 분해){self.view()}",
                             f"We think so: {self.share(dc.agg['mult_share'])} of the gain is multiple expansion ({dc.fy0}→{dc.fy1}, log split){self.view()}")
            else:
                n, tot = self.n_mcap_beats_ni() if ok(val) else (0, 0)
                ans = self.T(f"4사 시총 {self.market_basis()}. 가용 실적으로도 {tot}사 중 {n}곳은 시총이 이익보다 빨랐다{self.view()}. FY2022 기준 분해는 수집 후",
                             f"Cap {self.market_basis()}; on available earnings, {n} of {tot} saw cap outgrow NI{self.view()}. FY2022-based split after collection")
            qa.append([self.T("시장은 이미 반영했나?", "Has the market priced it in?"), ans, "4"])
            for _, r in mk.table[mk.table["split_factor"] != 1].iterrows():
                qa.append([self.T(f"{r['company']} 주가는 {r['price_multiple_raw']:.0f}배인데 왜 시총은 {r['multiple']:.0f}배인가?",
                                  f"Why is {r['company_en']}'s price up {r['price_multiple_raw']:.0f}x but its market cap {r['multiple']:.0f}x?"),
                           self.T(f"{r['action_date']} {r['split_factor']:.0f}:1 액면분할 때문이다. 주가 {self.num(r['close_t0'])}원 → {self.num(r['close_t1'])}원({r['price_multiple_raw']:.2f}배)은 분할 전후 주식 1주의 크기가 다르다. "
                                  f"분할 조정 주가 배수 {r['price_multiple_raw']:.2f}×{r['split_factor']:.0f} = {r['price_multiple_adj']:.1f}배로 시총 배수(상장주식수 {self.num(r['shares_t0'])}→{self.num(r['shares_t1'])}주)와 같다",
                                  f"A {r['split_factor']:.0f}:1 split on {r['action_date']}. The price move KRW {self.num(r['close_t0'])} → {self.num(r['close_t1'])} ({r['price_multiple_raw']:.2f}x) compares different share sizes; "
                                  f"split-adjusted {r['price_multiple_raw']:.2f}×{r['split_factor']:.0f} = {r['price_multiple_adj']:.1f}x, matching the cap multiple (shares {self.num(r['shares_t0'])}→{self.num(r['shares_t1'])})"),
                           "4, A2"])
            big = mk.largest_t0
            qa.append([self.T(f"합계 {self.x(mk.total_multiple)}와 평균 {self.x(mk.mean_multiple)} 중 무엇이 맞나?",
                              f"Which is right: {self.x(mk.total_multiple)} combined or {self.x(mk.mean_multiple)} average?"),
                       self.T(f"둘 다 맞고 질문이 다르다. 합계는 4사 바스켓(시총 가중), 평균은 회사별 동일 가중이다. 시작 시총의 {mk.largest_t0_share:.0f}%가 {big['company']}({big['multiple']:.1f}배)라 합계가 낮다. "
                              "섹터 전체 가치 변화는 합계, 종목별 재평가 폭은 평균으로 본다",
                              f"Both — they answer different questions. Combined is a cap-weighted basket; the average weights names equally. {big['company_en']} ({big['multiple']:.1f}x) was "
                              f"{mk.largest_t0_share:.0f}% of the starting cap, pulling the combined figure down. Use combined for sector value, average for per-name re-rating"),
                       "4"])
        if ok(val):
            hi = val.per.sort_values("per", ascending=False).iloc[0]
            qa.append([self.T("현재 PER이 높은데 거품인가?", "P/Es are high — is it a bubble?"),
                       self.T(f"합산 {self.x(val.agg_per)}, 중앙값 {self.x(val.median_per)}. {hi['company']} {self.x(hi['per'], 0)}는 지배순이익 {self.num(hi['ni'])}억원으로 분모가 작아 생긴 왜곡이다. "
                              f"거품 여부는 이익 지속성에 달렸다{self.view()}",
                              f"Aggregate {self.x(val.agg_per)}, median {self.x(val.median_per)}. {hi['company_en']}'s {self.x(hi['per'], 0)} reflects thin NI ({self.num(hi['ni'])}, KRW 100mn). "
                              f"Whether it is a bubble depends on earnings durability{self.view()}"), "4, 5"])
        qa.append([self.T("이 분석을 어떻게 재현하나?", "How can this be reproduced?"),
                   self.T("python -m src.data_fetch.fetch_all → python -m research.vol01.fetch_extra → python -m research.vol01.build. 모든 숫자는 코드가 data/ 파일에서 계산한다",
                          "python -m src.data_fetch.fetch_all → python -m research.vol01.fetch_extra → python -m research.vol01.build. Code computes every figure from data/ files"), "A3"])
        cell = Cell(title=self.T(f"예상 질문 {len(qa)}개와 답", f"{len(qa)} expected questions"), src=["iea_ai", "eia", "krx", "dart", "corp"],
                    table=TableSpec([self.T("질문", "Question"), self.T("답", "Answer"), self.T("근거 쪽", "Page")], qa, [0.24, 0.68, 0.08],
                                    ["L", "L", "C"], shade_rows={i for i, q in enumerate(qa) if "LS" in q[0] or "7.7" in q[0] or "합계" in q[0] or "combined" in q[0]},
                                    font_size=8.3),
                    note=self.T("답의 숫자는 본문과 같은 계산 결과", "Numbers in answers match the body calculations"))
        return Page("full", "A1", self.T("예상 질의응답: 숫자로 답한다", "Expected Q&A: answered with numbers"),
                    self.T("면접·실사에서 나올 질문과 근거 쪽수", "Questions likely in interviews or due diligence, with page references"), [cell], grid="1x1")

    def a2(self) -> Page:
        mk = self.f.market
        rows = [[s["org_kr"] if self.kr else s["org_en"], s["api"] if self.kr else s["api_en"], s["item_kr"] if self.kr else s["item_en"], s["as_of"] or "—",
                 s["status_kr"] if self.kr else s["status_en"]] for s in self.f.sources]
        pend = {i for i, s in enumerate(self.f.sources) if not s["ok"]}
        c1 = Cell(title=self.T("데이터 소스 · API · 기준일 · 상태", "Data sources · APIs · as-of · status"),
                  table=TableSpec([self.T("소스", "Source"), "API", self.T("항목", "Items"), self.T("기준일", "As of"), self.T("상태", "Status")],
                                  rows, [0.17, 0.36, 0.23, 0.11, 0.13], ["L", "L", "L", "C", "C"], shade_rows=pend,
                                  brick_cells={(i, 4) for i in pend}, font_size=8.2),
                  note=self.T(f"기준일 = 각 파일 .meta.json의 as_of(IEA는 원문 대조일). 원자료(data/raw)는 커밋하지 않고 가공본(data/processed)·수기 입력(data/manual)만 커밋. 저장소: {self.cfg['research']['repo_url']}",
                              f"As-of = as_of in each .meta.json (IEA: verification date). Raw API data (data/raw) is not committed; processed and manual files are. Repo: {self.cfg['research']['repo_url']}"))
        if ok(mk):
            krows, shade, brick = [], set(), set()
            for i, (_, r) in enumerate(mk.table.iterrows()):
                act = {"split_consistent": self.T(f"{r['action_date']} {r['split_factor']:.0f}:1 액면분할 (주식수 비율 일치)", f"{r['split_factor']:.0f}:1 split {r['action_date']} (ratio matches)"),
                       "split_mismatch": self.T("분할 기록과 주식수 비율 불일치 — 확인 필요", "Split record and share ratio differ — check"),
                       "unchanged": self.T("변동 없음", "No change"),
                       "changed_unexplained": self.T(f"주식수 {(r['share_ratio'] - 1) * 100:+.2f}% — 기업행위 기록 없음, 공시 확인 필요", f"Shares {(r['share_ratio'] - 1) * 100:+.2f}% — no recorded action; check filings")}[r["share_note"]]
                krows.append([self.name(r), self.num(r["shares_t0"]), self.num(r["shares_t1"]), act, self.x(r["price_multiple_raw"], 2),
                              self.x(r["price_multiple_adj"], 2), self.x(r["multiple"], 2), f"{max(abs(r['mcap_check_t0']), abs(r['mcap_check_t1'])):.2f}%"])
                if r["share_note"] != "unchanged":
                    shade.add(i)
                if r["share_note"] in ("split_mismatch", "changed_unexplained"):
                    brick.add((i, 3))
            c2 = Cell(title=self.T(f"KRX 시총 검산: 각 시점 상장주식수 사용 확인 ({mk.t0} · {mk.t1})", f"KRX market-cap check: listed shares at each date ({mk.t0} · {mk.t1})"),
                      src=["krx", "corp"],
                      table=TableSpec([self.T("회사", "Company"), self.T(f"상장주식수 {mk.t0}", f"Shares {mk.t0}"), self.T(f"상장주식수 {mk.t1}", f"Shares {mk.t1}"),
                                       self.T("증자·분할", "Corporate action"), self.T("주가 배수(원)", "Price x (raw)"), self.T("분할 조정 주가 배수", "Split-adj. price x"),
                                       self.T("시총 배수", "Cap x"), self.T("시총 검산 오차", "Cap check")], krows,
                                      [0.14, 0.12, 0.12, 0.25, 0.09, 0.11, 0.08, 0.09], ["L", "R", "R", "L", "R", "R", "R", "R"],
                                      shade_rows=shade, brick_cells=brick,
                                      gold_cells={(i, 6) for i, (_, r) in enumerate(mk.table.iterrows()) if r["split_factor"] != 1},
                                      font_size=8.0),
                      note=self.T("시총 = KRX MKTCAP(각 시점 종가 × 그 시점 상장주식수). 검산 오차 = 종가 × 상장주식수 ÷ MKTCAP − 1. 분할 조정 주가 배수 = 주가 배수 × 분할 비율. "
                                  "주가 차트를 그릴 때는 분할 조정 주가를 쓴다. 기업행위는 data/manual/krx_corporate_actions.csv(저자 검산)에 기록",
                                  "Cap = KRX MKTCAP (close × listed shares at each date). Check = close × shares ÷ MKTCAP − 1. Split-adjusted price x = price x × split ratio. "
                                  "Price charts must use split-adjusted prices. Actions are recorded in data/manual/krx_corporate_actions.csv (author's check)"))
        else:
            c2 = self.pending_cell(self.T("KRX 시총 검산", "KRX market-cap check"), ["krx"], mk)
        return Page("full", "A2", self.T("데이터 노트: 출처·API·기준일, 그리고 KRX 시총 검산", "Data notes: sources, APIs, dates and the KRX market-cap check"),
                    self.T("SEC는 준비 중 · LS ELECTRIC 액면분할 반영 방법 명시 · 시총은 각 시점 상장주식수 기준",
                           "SEC in progress · LS ELECTRIC split treatment stated · market cap uses listed shares at each date"),
                    [c1, c2], grid="2x1")

    def a3(self) -> Page:
        f = self.f
        n_ok = sum(s["ok"] for s in f.sources if s["id"] != "iea")
        n_src = sum(1 for s in f.sources if s["id"] != "iea")
        stages = [(self.T("자동 수집", "Collection"), [self.T("재시도·타임아웃·캐시", "Retries, timeouts, cache"), self.T("요청 속도 제한", "Rate limiting"),
                                                      self.T("원본마다 .meta.json", ".meta.json per file"), self.T("API 키 마스킹", "API keys masked"),
                                                      self.T("키 없으면 건너뜀", "Skip if no key")]),
                  (self.T("검증", "Validation"), [self.T("식별자 (DART·SEC)", "IDs (DART, SEC)"), self.T("시총 = 종가×주식수 검산", "Cap = close × shares"),
                                                 self.T("기업행위(분할) 대조", "Corporate actions"), self.T("분해식 항등 검산", "Split identity check"),
                                                 self.T(f"테스트 함수 {f.n_tests}개", f"{f.n_tests} test functions")]),
                  (self.T("보고서", "Report"), [self.T("결론형 제목 자동 생성", "Data-driven titles"), self.T("국문·영문 PDF", "KR & EN PDFs"),
                                              self.T("없는 데이터는 회색 박스", "Gaps shown, not filled"), self.T("명령 한 줄로 재빌드", "One-command rebuild"),
                                              self.T("판단에 (저자 견해)", "Judgements labelled")])]
        c1 = Cell(title=self.T(f"공식 출처 {n_src}곳 → 자동 수집 → 검증 → 보고서", f"{n_src} official sources → collection → validation → report"),
                  src=["ksj"], chart_key="pipeline", chart=charts.pipeline([s for s in f.sources if s["id"] != "iea"], stages, self.c, self.lang),
                  note=self.T(f"수집 완료 {n_ok}/{n_src}곳 (SEC 준비 중). IEA 보고서 수치는 수기 입력 후 원문 대조", f"{n_ok}/{n_src} collected (SEC in progress). IEA figures entered manually and verified"))
        c2 = Cell(title=self.T("재현 명령 (로컬)", "Reproduce (local)"),
                  panel_lead=self.cfg["research"]["repo_url"],
                  bullets=["pip install -r requirements.txt",
                           "python -m src.data_fetch.fetch_all --source all --asof " + f.as_of,
                           "python -m research.vol01.fetch_extra --asof " + f.as_of,
                           "python -m research.vol01.build",
                           "pytest -q",
                           self.T("키는 .env에서만 로드, 원자료(data/raw)는 커밋하지 않음", "Keys only from .env; raw data (data/raw) not committed")],
                  note=self.T("명령은 저장소 루트에서 실행", "Run from the repository root"))
        return Page("full", "A3", self.T(f"What I built: 공식 출처 {n_src}곳을 자동 수집·검증해 이 보고서를 만든다", f"What I built: {n_src} official sources, collected and validated automatically into this report"),
                    self.T("모든 숫자는 코드가 데이터 파일에서 계산한다 — 데이터가 없으면 회색 박스로 남긴다",
                           "Code computes every number from data files — missing data stays a grey box"), [c1, c2], grid="2x1")

    def a4(self) -> Page:
        terms = [
            ("TWh", self.T("테라와트시. 10억 kWh. 연간 전력 소비량 단위", "Terawatt-hour, one billion kWh; annual electricity use")),
            (self.T("기준 시나리오", "Base Case"), self.T("IEA 전망의 중심 시나리오. 범위는 IEA가 제시한 하단~상단", "IEA's central scenario; the range is IEA's low–high")),
            (self.T("상업용 부문", "Commercial sector"), self.T("EIA 소매판매 분류. 사무실·상업시설 등. 데이터센터는 주에 따라 상업용 또는 산업용", "EIA retail-sales class; data centres may be commercial or industrial by state")),
            (self.T("지수 (2015=100)", "Index (2015=100)"), self.T("해당 연도 값 ÷ 2015년 값 × 100", "Year value ÷ 2015 value × 100")),
            ("CAGR", self.T("연평균 성장률 = (끝 ÷ 시작)^(1/연수) − 1", "Compound annual growth = (end ÷ start)^(1/years) − 1")),
            (self.T("시가총액 (시총)", "Market cap"), self.T("종가 × 그 시점 상장주식수 (KRX MKTCAP)", "Close × listed shares at that date (KRX MKTCAP)")),
            (self.T("합계 기준 배수", "Combined multiple"), self.T("4사 시총 합계(끝) ÷ 합계(시작). 시총 가중", "Sum of caps (end) ÷ sum (start); cap-weighted")),
            (self.T("단순평균 배수", "Simple-average multiple"), self.T("회사별 시총 배수의 평균. 동일 가중", "Average of each name's multiple; equal-weighted")),
            (self.T("액면분할", "Stock split"), self.T("1주를 여러 주로 나눔. 시총 불변, 주가는 비율만큼 낮아짐 → 주가 비교 시 분할 조정", "One share becomes several; cap unchanged, price adjusts → compare split-adjusted prices")),
            (self.T("지배순이익", "NI to parent"), self.T("지배기업 소유주 귀속 당기순이익 (DART 연결)", "Net income attributable to owners of the parent (DART consolidated)")),
            ("PER", self.T("시가총액 ÷ 지배순이익", "Market cap ÷ NI to parent")),
            (self.T("로그 분해", "Log decomposition"), self.T("Δln(시총) = Δln(지배순이익) + Δln(PER). 시총 = 지배순이익 × PER이므로 항등식", "Δln(cap) = Δln(NI) + Δln(P/E), an identity since cap = NI × P/E")),
            (self.T("이익 기여 / 멀티플 기여", "Earnings / multiple share"), self.T("각 항 ÷ Δln(시총)", "Each term ÷ Δln(cap)")),
            ("ECM", self.T("주식자본시장. IPO·유상증자 등 주식 발행 업무", "Equity capital markets: IPOs, follow-ons")),
            (self.T("희망공모가 밴드", "Indicative price range"), self.T("수요예측 전에 제시하는 공모가 범위", "Price range set before book-building")),
            ("PF", self.T("프로젝트 파이낸싱. 사업 현금흐름을 상환 재원으로 하는 금융", "Project finance, repaid from project cash flows")),
        ]
        cell = Cell(title=self.T("용어 정의", "Glossary"),
                    table=TableSpec([self.T("용어", "Term"), self.T("정의", "Definition")], [list(t) for t in terms], [0.22, 0.78], ["L", "L"],
                                    shade_rows={5, 6, 7, 11}, font_size=8.6),
                    note=self.T("음영 = 이 노트의 핵심 계산 용어", "Shaded = core calculation terms in this note"))
        return Page("full", "A4", self.T("용어 정의: 이 노트에서 쓰는 단위와 계산", "Glossary: units and calculations used in this note"),
                    self.T("단위: TWh, 억원, %, 배 · 금액은 KRW 억원", "Units: TWh, KRW 100mn, %, x"), [cell], grid="1x1")
