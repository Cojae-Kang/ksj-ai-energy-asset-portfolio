"""Vol.1 페이지 구성·문구 (국문/영문). 숫자는 모두 data.Facts에서, 서술 방향도 데이터로 결정한다.

공개용 원칙: 제목에 '(저자 견해)'를 붙이지 않고, 요약 쪽 하단과 뒤표지에 "본문의 판단은 저자 개인의 견해" 한 줄만 둔다.
내부 파일·설정·실행 명령은 보고서에 쓰지 않는다(만드는 과정은 GitHub에 공개).
"""
from __future__ import annotations

from typing import Mapping

from . import charts
from .data import GROWTH_LABELS, Facts, SumGrowth, Unavailable, growth_kind, ok
from .layout import BigBox, Cell, Page, TableSpec, toc_line

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
        return ""   # 공개용: 판단 표기는 요약 쪽 하단·뒤표지 한 줄로 대체

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

    # --- 기준값 0 이하 처리 -------------------------------------------------
    def ename(self, e: dict) -> str:
        return e["company"] if self.kr else e["company_en"]

    def num_or_dash(self, v: float | None) -> str:
        return "—" if v is None else self.num(v)

    def gx(self, v0: float | None, v1: float | None) -> str:
        """배수 또는 라벨(흑자전환·적자전환·적자 지속). 음수 배수는 절대 만들지 않는다."""
        kind = growth_kind(v0, v1)
        if kind == "multiple":
            return self.x(v1 / v0)
        kr, en = GROWTH_LABELS[kind]
        return self.T(kr, en)

    def loss_reason(self, e: dict, y0: int, y1: int) -> tuple[str, str]:
        return {"turned_profit": (f"FY{y0} 지배순손실", f"FY{y0} net loss"),
                "turned_loss": (f"FY{y1} 지배순손실", f"FY{y1} net loss"),
                "loss_both": (f"FY{y0}·FY{y1} 지배순손실", f"FY{y0} and FY{y1} net loss"),
                "missing": ("데이터 없음", "data missing")}[e["kind"]]

    def ni_fallback_note(self) -> str:
        """지배순이익 계정이 없어 당기순이익(총계)으로 대체한 회사·연도 각주 (없으면 빈 문자열)."""
        fin = self.f.fin
        fb = fin.ni_fallback if ok(fin) else []
        if not fb:
            return ""
        kr = ", ".join(f"{c} FY{y}A" for c, _, y in fb)
        en = ", ".join(f"{e} FY{y}A" for _, e, y in fb)
        return self.T(f" {kr}: 공시에 지배순이익 계정이 없어 연결 당기순이익(비지배지분 포함)으로 대체.",
                      f" {en}: no NI-to-parent line in the filing, consolidated net income (incl. minorities) used.")

    def excl_note(self, sg: SumGrowth, y0: int, y1: int) -> str:
        """'두산에너빌리티 제외: FY2022 지배순손실' (제외 없으면 빈 문자열)."""
        parts = [f"{self.ename(e)} {self.T('제외', 'excluded')}: {self.T(*self.loss_reason(e, y0, y1))}" for e in sg.excluded]
        return "; ".join(parts)

    def group_label(self, sg: SumGrowth, y0: int, y1: int) -> str:
        """'3사(두산에너빌리티 제외: FY2022 지배순손실)' 또는 '4사'."""
        ex = self.excl_note(sg, y0, y1)
        return self.T(f"{sg.n}사" + (f"({ex})" if ex else ""), f"{sg.n} names" + (f" ({ex})" if ex else ""))

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
        from research.disclosures import contact_line, license_items
        items += license_items(self.cfg, self.kr)
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"],
                                                         "contact": contact_line(self.cfg)})

    # --- 대표 PER ---------------------------------------------------------------
    def per_rep(self) -> str | None:
        """본문 대표 PER: 분해 가능하면 'n사 합산 PER 13.5배 → 40.1배', 아니면 현재 PER(가용 데이터)."""
        dc, val = self.f.decomp, self.f.val
        if ok(dc):
            a = dc.agg
            return self.T(f"{self.dc_short()} 합산 PER {self.x(a['per0'])} → {self.x(a['per1'])}",
                          f"aggregate P/E of {self.dc_short()} {self.x(a['per0'])} → {self.x(a['per1'])}")
        if ok(val):
            return self.T(f"현재 PER 합산 {self.x(val.agg_per)} · 중앙값 {self.x(val.median_per)} ({val.fy})",
                          f"current P/E aggregate {self.x(val.agg_per)} · median {self.x(val.median_per)} ({val.fy})")
        return None

    def per4_footnote(self) -> str:
        """p4 각주 전용: '두산 포함 4사 합산 64.2배(두산 503배: FY2025A 지배순이익 848억원의 분모 왜곡)'."""
        val = self.f.val
        if not ok(val):
            return ""
        hi = val.per.sort_values("per", ascending=False).iloc[0]
        return self.T(f"{hi['company']} 포함 4사 합산 {self.x(val.agg_per)}({hi['company']} {self.x(hi['per'], 0)}: {val.fy} 지배순이익 {self.num(hi['ni'])}억원의 분모 왜곡)",
                      f"Including {hi['company_en']}, 4-name aggregate {self.x(val.agg_per)} ({hi['company_en']} {self.x(hi['per'], 0)}: denominator distortion from {val.fy} NI of {self.num(hi['ni'])}, KRW 100mn)")

    # --- Executive Summary --------------------------------------------------
    def executive(self) -> Page:
        f, d, g, mk, dc, val = self.f, self.f.demand, self.f.ground, self.f.market, self.f.decomp, self.f.val
        led = self.multiple_led()
        parts = [self.T("수요는 진짜이고", "Demand is real") if ok(d) else self.T("수요 데이터 확인 중", "Demand data pending")]
        if ok(g):
            parts.append({"ahead": self.T("현장에서도 보인다", "it shows up on the ground"),
                          "behind": self.T("현장 데이터는 엇갈린다", "ground data is mixed"),
                          "similar": self.T("현장 차이는 아직 작다", "the ground gap is still small")}[g.verdict])
        if ok(mk) and led is not None:
            if ok(dc):
                parts.append(self.T("시장은 이미 알고 있고 이익보다 멀티플이 앞서 달렸다" if led else
                                    f"시장 상승은 이익이 이끌었지만({self.head_scope()}) PER도 {self.x(dc.agg['per0'])}에서 {self.x(dc.agg['per1'])}로 올랐다",
                                    "the market already knows, and multiples ran ahead of earnings" if led else
                                    f"earnings led the market ({self.head_scope()}), but P/E also rose from {self.x(dc.agg['per0'])} to {self.x(dc.agg['per1'])}"))
            else:
                parts.append(self.T("시장은 이미 알고 있고 이익보다 멀티플이 앞서 달렸다" if led else "시장은 반영했고 이익이 이를 뒷받침한다",
                                    "the market already knows, and multiples ran ahead of earnings" if led else "the market has priced it, backed by earnings"))
        title = self.T(" ".join(parts[:2]) + (" — " + parts[2] if len(parts) > 2 else ""),
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
        # 왼쪽: 핵심 지표표 — 지표명은 넓게, 값은 한 줄
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        if ok(d):
            add(self.T("2030E 데이터센터 전력", "2030E data-centre power"),
                self.T(f"{self.num(d.v['dc_2030'])} TWh ({self.x(d.mult_2030)})", f"{self.num(d.v['dc_2030'])} TWh ({self.x(d.mult_2030)})"), "1", key=True)
            add(self.T("2035E 전망 범위", "2035E outlook range"), f"{self.num(d.v['dc_2035_low'])}~{self.num(d.v['dc_2035_high'])} TWh", "1")
            add(self.T("2025 증가율: AI DC · DC · 세계", "2025 growth: AI DC · DC · world"),
                f"{self.pct(d.v['growth_ai'])} · {self.pct(d.v['growth_dc'])} · {self.pct(d.v['growth_global'])}", "1")
        if ok(g):
            add(self.T(f"버지니아 상업용 지수 ({g.last_year})", f"Virginia commercial index ({g.last_year})"),
                self.T(f"{100 + g.va_change_pct:.0f} vs 미국 {100 + g.us_change_pct:.0f}", f"{100 + g.va_change_pct:.0f} vs U.S. {100 + g.us_change_pct:.0f}"), "2", key=True)
        if ok(mk):
            add(self.T(f"4사 시총 합계 ({mk.t0[:7]}→{mk.t1[:7]})", f"4 names' combined cap ({mk.t0[:7]}→{mk.t1[:7]})"),
                self.x(mk.total_multiple), "4", key=True)
            add(self.T("4사 시총 단순평균 / 범위", "Simple average / range"),
                f"{self.x(mk.mean_multiple)} / {self.x(mk.bottom['multiple'])}~{self.x(mk.top['multiple'])}", "4")
        if ok(dc):
            a = dc.agg
            add(self.T(f"{dc.n_valid}사 이익 · 멀티플 기여", f"{dc.n_valid}-name earnings · multiple share"),
                f"{self.share(a['earn_share'])} · {self.share(a['mult_share'])}", "4", key=True)
            add(self.T(f"{dc.n_valid}사 합산 PER (2023 초→최근)", f"{dc.n_valid}-name P/E (start-2023→latest)"),
                f"{a['per0']:.1f} → {self.x(a['per1'])}", "4", key=True)
        elif ok(val):
            n, tot = self.n_mcap_beats_ni()
            add(self.T(f"시총 배수 > 이익 배수 ({val.growth_from}→{val.fy})", f"Cap x > NI x ({val.growth_from}→{val.fy})"),
                self.T(f"{tot}사 중 {n}곳", f"{n} of {tot}"), "3·4", key=True)
            add(self.T("이익 · 멀티플 기여 (FY2022A 기준)", "Earnings · multiple (FY2022A base)"), self.T("FY2022 수집 후", "after FY2022"), "4")
            add(self.T(f"현재 PER ({val.fy})", f"Current P/E ({val.fy})"),
                self.T(f"합산 {self.x(val.agg_per)} · 중앙값 {self.x(val.median_per)}", f"agg. {self.x(val.agg_per)} · median {self.x(val.median_per)}"), "4")
        r = f.rates
        if ok(r) and r.ktb10_t0 is not None:
            add(self.T("국고채 10년 (2023 초→최근)", "KTB 10y (start-2023→latest)"), f"{r.ktb10_t0:.2f} → {r.ktb10_t1:.2f}%", "5")
        table = TableSpec([self.T("핵심 지표", "Key metric"), self.T("값", "Value"), self.T("쪽", "p.")], rows,
                          [0.58, 0.33, 0.09], ["L", "R", "C"], shade_rows=shade, gold_cells=gold, font_size=8.6,
                          single_line_cols={1})
        left = Cell(title=self.T("핵심 지표", "Key metrics"), src=["iea_ai", "iea_kq", "eia", "krx", "dart"],
                    table=table, note=self.T("KSJ Research 계산. 각 지표의 정의·계산은 해당 쪽 각주 참조. 본문의 판단은 저자 개인의 견해",
                                             "KSJ Research calculations; see footnotes on each page. Judgements are the author's own"))
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
        title = {"ahead": self.T(f"현장에서도 보인다 — 미국 전체({self.pct(g.us_change_pct)})를 지수 {g.gap_pts:.0f}포인트 앞섰다",
                                 f"It shows up on the ground — {g.gap_pts:.0f} index points ahead of the U.S. ({self.pct(g.us_change_pct)})"),
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
        big = mk.largest_t0
        bl = [self.T(f"단순평균 {self.x(mk.mean_multiple)} — 시작 시총의 {mk.largest_t0_share:.0f}%인 {self.name(big)}({self.x(big['multiple'])})가 합계를 낮춤",
                     f"Simple average {self.x(mk.mean_multiple)} — {self.name(big)} ({self.x(big['multiple'])}), {mk.largest_t0_share:.0f}% of starting cap, drags the total")]
        if ok(dc):
            a, g = dc.agg, self.dc_short()
            title = (self.T(f"시장은 이미 알고 있다 — {g} 시총 증가의 {self.share(a['mult_share'])}가 멀티플 확대", f"The market already knows — {self.share(a['mult_share'])} of the gain for {g} is multiple expansion")
                     if led else
                     self.T(f"이익이 이끌었다 — {g} 시총 증가의 {self.share(a['earn_share'])}가 이익 증가({self.scope_text()}) · {self.op_alt_text()}",
                            f"Earnings led — {self.share(a['earn_share'])} of the gain for {g} is earnings growth ({self.scope_text()}) · {self.op_alt_text()}")) + self.view()
            bl.append(self.T(f"{dc.n_valid}사 합산 PER {self.x(a['per0'])} → {self.x(a['per1'])} (2023 초 ↔ {dc.fy0}, 최근 ↔ {dc.fy1})",
                             f"{dc.n_valid}-name aggregate P/E {self.x(a['per0'])} → {self.x(a['per1'])} (start-2023 ↔ {dc.fy0}, latest ↔ {dc.fy1})"))
            bl.append(self.contrib_sentence())
        else:
            n, tot = self.n_mcap_beats_ni() if ok(val) else (0, 0)
            title = self.T(f"시장은 이미 알고 있다 — {tot}사 중 {n}곳은 시총이 이익보다 빠르게 늘었다{self.view()}"
                           if led else f"시장은 반영했지만 이익도 따라왔다{self.view()}",
                           f"The market already knows — for {n} of {tot}, market cap outgrew earnings{self.view()}"
                           if led else f"Priced in, but earnings kept pace{self.view()}")
            if ok(val):
                bl.append(self.T(f"현재 PER 합산 {self.x(val.agg_per)}, 중앙값 {self.x(val.median_per)} (최근 시총 ÷ {val.fy} 지배순이익)",
                                 f"Current P/E aggregate {self.x(val.agg_per)}, median {self.x(val.median_per)} (latest cap ÷ {val.fy} NI)"))
                sg = self.f.fin.sum_growth("ni", int(val.growth_from[2:6]), int(val.fy[2:6]))
                bl.append(self.T(f"{self.group_label(sg, int(val.growth_from[2:6]), int(val.fy[2:6]))} 지배순이익 {val.growth_from}→{val.fy} {self.x(sg.multiple)} vs 시총 {self.x(mk.total_multiple)} — FY2022 기준 분해는 수집 후",
                                 f"NI of {self.group_label(sg, int(val.growth_from[2:6]), int(val.fy[2:6]))} {val.growth_from}→{val.fy} {self.x(sg.multiple)} vs cap {self.x(mk.total_multiple)}; FY2022-based split after collection"))
        return BigBox(self.x(mk.total_multiple), self.T(f"4사 시총 합계 기준, {mk.t0}→{mk.t1} (회사별 {self.x(mk.bottom['multiple'])}~{self.x(mk.top['multiple'])})",
                                                        f"4 names, combined cap, {mk.t0}→{mk.t1} (range {self.x(mk.bottom['multiple'])}–{self.x(mk.top['multiple'])})"),
                      title, bl)

    # --- 목차 ---------------------------------------------------------------
    def toc_page(self) -> Page:
        heads = [self.p1(), self.p2(), self.p3(), self.p4(), self.p5()]
        names = [self.T("수요", "Demand"), self.T("현장", "Ground truth"), self.T("실적", "Earnings"),
                 self.T("시장", "Market"), self.T("시사점", "Implications")]
        toc = [(n, nm, toc_line(h.extra.get("toc") or h.title), h.label) for n, nm, h in zip(["I", "II", "III", "IV", "V"], names, heads)]
        toc.append(("App.", "Appendix", self.T("A1 예상 질의응답 · A2 데이터 노트(출처·데이터셋·기준일·주식수 검산) · A3 분석 방법과 데이터 · A4 용어",
                                               "A1 Q&A · A2 Data notes (sources, datasets, dates, share-count check) · A3 Methodology · A4 Glossary"),
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
                                    lambda x: f"{x:.0f}%"),
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
            title = {"ahead": self.T(f"현장에서도 보인다: 버지니아 상업용 전력 판매 {g.base_year}년 대비 {self.pct(g.va_change_pct)}, 미국 전체({self.pct(g.us_change_pct)})를 지수 {g.gap_pts:.0f}포인트 앞섰다",
                                     f"It shows up on the ground: Virginia commercial sales {self.pct(g.va_change_pct)} since {g.base_year}, {g.gap_pts:.0f} index points ahead of the U.S. ({self.pct(g.us_change_pct)})"),
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
                title=self.T(f"버지니아 상업용 판매 {self.pct(g.va_change_pct)} vs 미국 {self.pct(g.us_change_pct)} — {g.last_year}년 지수 차이 {g.gap_pts:.0f}포인트",
                             f"Virginia commercial sales {self.pct(g.va_change_pct)} vs U.S. {self.pct(g.us_change_pct)} — {g.gap_pts:.0f}-index-point gap in {g.last_year}"),
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
            rows = [[str(int(r["period"])), self.pct(r["VA"], 1), self.pct(r["US"], 1), f"{r['VA'] - r['US']:+.1f}%p"]
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
        peers = fin.tickers()
        nm = {r["ticker"]: self.name(r) for _, r in t.iterrows()}
        sg_rev, sg_op, sg_ni = (fin.sum_growth(col, y0, y1) for col in ("revenue", "op", "ni"))
        grp = self.group_label(sg_ni, y0, y1)
        excl = self.excl_note(sg_ni, y0, y1)
        missing = fin.missing_years
        miss_note = self.T(f" FY{', FY'.join(map(str, missing))}A는 데이터 수집 후 추가",
                           f" FY{', FY'.join(map(str, missing))}A to be added") if missing else ""
        dc = self.f.decomp
        if ok(dc):   # p4와 같은 방향: 이익이 시총 증가의 몇 %를 설명하나
            a = dc.agg
            title = self.T(f"실적도 늘었다: {grp} 지배순이익 {self.x(sg_ni.multiple)} — 시총 증가({self.x(a['mcap1'] / a['mcap0'])})의 {self.share(a['earn_share'])}를 설명",
                           f"Earnings grew too: NI to parent of {grp} {self.x(sg_ni.multiple)} explains {self.share(a['earn_share'])} of the market-cap gain ({self.x(a['mcap1'] / a['mcap0'])})")
        else:
            slower = ok(mk) and sg_ni.multiple < mk.total_multiple
            title = self.T(f"실적도 늘었다: {grp} 지배순이익 합계 FY{y0}A→FY{y1}A {self.x(sg_ni.multiple)}"
                           + (f" — 다만 시총({self.x(mk.total_multiple)})보다 느렸다" if slower else ""),
                           f"Earnings grew too: NI to parent of {grp} {self.x(sg_ni.multiple)} from FY{y0}A to FY{y1}A"
                           + (f" — but slower than market cap ({self.x(mk.total_multiple)})" if slower else ""))
        sub = self.T(f"{self.group_label(sg_rev, y0, y1)} 합계 매출 {self.pct((sg_rev.multiple - 1) * 100)}, "
                     f"{self.group_label(sg_op, y0, y1)} 합계 영업이익 {self.pct((sg_op.multiple - 1) * 100)} (FY{y0}A→FY{y1}A, 연결 기준)",
                     f"Combined revenue of {self.group_label(sg_rev, y0, y1)} {self.pct((sg_rev.multiple - 1) * 100)}, operating profit of "
                     f"{self.group_label(sg_op, y0, y1)} {self.pct((sg_op.multiple - 1) * 100)} (FY{y0}A→FY{y1}A, consolidated)")
        fy_colors = {2022: c["warm_grey_light"], 2023: c["warm_grey"], 2024: c["brown_mid"], 2025: c["gold"]}
        # 1) 매출 지수 (FY{y0}=100) — 회사별 성장 차이. 절대값은 오른쪽 아래 표
        cats = [nm[tk] for tk in peers]
        ridx = {tk: [fin.value(tk, y, "revenue") / fin.value(tk, y0, "revenue") * 100 for y in yrs] for tk in peers}
        top = max(peers, key=lambda tk: ridx[tk][-1])
        low = min(peers, key=lambda tk: ridx[tk][-1])
        cells = [Cell(
            title=self.T(f"매출 지수(FY{y0}=100): {nm[top]} {ridx[top][-1]:.0f}로 최대 · {nm[low]} {ridx[low][-1]:.0f} — 합계 {self.pct((sg_rev.multiple - 1) * 100)}",
                         f"Revenue index (FY{y0}=100): {nm[top]} highest at {ridx[top][-1]:.0f} · {nm[low]} {ridx[low][-1]:.0f} — combined {self.pct((sg_rev.multiple - 1) * 100)}"),
            src=["dart"], legend=[(c[COMPANY_COLORS[i]], nm[tk]) for i, tk in enumerate(peers)],
            unit=self.T(f"지수 (FY{y0}=100)", f"Index (FY{y0}=100)"), chart_key="revenue_idx",
            chart=charts.lines(yrs, [(nm[tk], ridx[tk], c[COMPANY_COLORS[i]], 2.0 if tk == top else 1.5) for i, tk in enumerate(peers)],
                               c, lambda x: f"{x:.0f}", ref=100, right=0.66),
            note=self.T(f"지수 = 매출 ÷ FY{y0}A 매출 × 100 (KSJ Research 계산). 연결 기준, 절대값은 FY{y1}A 요약표 참조." + miss_note,
                        f"Index = revenue ÷ FY{y0}A × 100 (KSJ Research). Consolidated; absolute values in the FY{y1}A table." + miss_note))]
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
        # 3) 지배순이익 증가율 (직전 연도 적자면 증가율 생략)
        yoy_years = [y for y in yrs if y - 1 in yrs]
        series = [(f"FY{y}A", [fin.value(tk, y, "ni_yoy") if fin.value(tk, y, "ni_yoy") is not None else float("nan") for tk in peers],
                   fy_colors.get(y, c["brown_mid"])) for y in yoy_years]
        nim = {tk: fin.value(tk, y1, "ni") / fin.value(tk, y0, "ni") for tk in peers
               if growth_kind(fin.value(tk, y0, "ni"), fin.value(tk, y1, "ni")) == "multiple"}
        topn = max(nim, key=nim.get) if nim else None
        turned = [e for e in sg_ni.excluded if e["kind"] == "turned_profit"]
        tail_kr = "".join(f", {self.ename(e)} 흑자전환" for e in turned)
        tail_en = "".join(f"; {self.ename(e)} turned profitable" for e in turned)
        cells.append(Cell(
            title=self.T(f"지배순이익 FY{y0}A→FY{y1}A: {grp} 합계 {self.x(sg_ni.multiple)}"
                         + (f", {nm[topn]} {self.x(nim[topn])}로 최대" if topn else "") + tail_kr,
                         f"NI to parent FY{y0}A→FY{y1}A: {grp} combined {self.x(sg_ni.multiple)}"
                         + (f"; {nm[topn]} leads at {self.x(nim[topn])}" if topn else "") + tail_en),
            src=["dart"], legend=[(col, lab) for lab, _, col in series] + [(c["brick"], self.T("감소", "Decline"))],
            unit=self.T("전년 대비 %", "% y/y"), chart_key="ni_yoy",
            chart=charts.grouped(cats, series, c, lambda x: f"{x:+.0f}%", zero_line=True),
            note=self.T("지배기업 소유주 귀속 당기순이익. 직전 연도가 적자면 증가율을 계산하지 않음(막대 없음)." + (f" 합계 배수는 {excl}." if excl else "") + self.ni_fallback_note() + miss_note,
                        "NI attributable to owners of the parent; no growth rate after a loss year (no bar)." + (f" Combined multiple {excl}." if excl else "") + self.ni_fallback_note() + miss_note)))
        # 4) 재무 요약표: 기준·최근 지배순이익 실제 값 + 배수(또는 흑자전환 라벨)
        rows, gold, brick = [], set(), set()
        for i, tk in enumerate(peers):
            rv, o, m = (fin.value(tk, y1, k) for k in ("revenue", "op", "opm"))
            n0, n1 = fin.value(tk, y0, "ni"), fin.value(tk, y1, "ni")
            rows.append([nm[tk], self.num(rv), self.num(o), f"{m:.1f}%", self.num_or_dash(n0), self.num_or_dash(n1), self.gx(n0, n1)])
            if tk == topn:
                gold.add((i, 6))
            if n0 is not None and n0 <= 0:
                brick.add((i, 4))
            if n1 is not None and n1 <= 0:
                brick.add((i, 5))
            if growth_kind(n0, n1) != "multiple":
                brick.add((i, 6))
        tot = lambda y, col: sum(fin.value(tk, y, col) or 0 for tk in peers)  # noqa: E731
        rows.append([self.T(f"{len(peers)}사 합계", "Total"), self.num(tot(y1, "revenue")), self.num(tot(y1, "op")),
                     f"{tot(y1, 'op') / tot(y1, 'revenue') * 100:.1f}%", self.num(tot(y0, "ni")), self.num(tot(y1, "ni")),
                     self.x(sg_ni.multiple) + (self.T(f" ({sg_ni.n}사)", f" ({sg_ni.n} names)") if sg_ni.excluded else "")])
        k = len(rows) - 1
        cells.append(Cell(
            title=self.T(f"FY{y1}A 합계 매출 {self.num(tot(y1, 'revenue'))}억원 · 영업이익 {self.num(tot(y1, 'op'))}억원 · 지배순이익 {self.num(tot(y1, 'ni'))}억원",
                         f"FY{y1}A combined: revenue {self.num(tot(y1, 'revenue'))}, OP {self.num(tot(y1, 'op'))}, NI {self.num(tot(y1, 'ni'))} (KRW 100mn)"),
            src=["dart"], unit=self.T("억원, %, 배", "KRW 100mn, %, x"),
            table=TableSpec([self.T("회사", "Company"), self.T("매출", "Revenue"), self.T("영업이익", "OP"), self.T("영업이익률", "OPM"),
                             self.T(f"지배순이익 FY{y0}", f"NI FY{y0}"), self.T(f"지배순이익 FY{y1}", f"NI FY{y1}"),
                             self.T("순이익 배수", "NI x")],
                            rows, [0.21, 0.13, 0.12, 0.11, 0.14, 0.14, 0.15], shade_rows={k}, bold_rows={k}, gold_cells=gold,
                            brick_cells=brick, strong_cells={(k, 6)}, font_size=8.2),
            note=self.T(f"매출·영업이익·영업이익률은 FY{y1}A 연결 기준. 순이익 배수 = FY{y1}A ÷ FY{y0}A, 기준 이익이 0 이하이면 배수 대신 라벨"
                        + (f". 합계 배수는 {excl}" if excl else "") + " (KSJ Research 계산)",
                        f"Revenue, OP and OPM are FY{y1}A consolidated. NI x = FY{y1}A ÷ FY{y0}A; a label replaces the multiple when the base is ≤0"
                        + (f". Combined multiple {excl}" if excl else "") + " (KSJ Research)")))
        return Page("body", "3", title, sub, cells)

    # --- p4 시장 (핵심) -------------------------------------------------------
    def dc_group(self) -> str:
        """분해 대상 표기: '3사(두산에너빌리티 제외: FY2022 지배순손실)' 또는 '4사'."""
        dc = self.f.decomp
        ex = "; ".join(f"{self.ename(e)} {self.T('제외', 'excluded')}: {self.T(e['reason'], e['reason_en'])}" for e in dc.excluded)
        return self.T(f"{dc.n_valid}사" + (f"({ex})" if ex else ""), f"{dc.n_valid} names" + (f" ({ex})" if ex else ""))

    def dc_short(self) -> str:
        """제목용 짧은 표기: '3사(두산에너빌리티 제외)'."""
        dc = self.f.decomp
        ex = ", ".join(self.ename(e) for e in dc.excluded)
        return self.T(f"{dc.n_valid}사" + (f"({ex} 제외)" if ex else ""), f"{dc.n_valid} names" + (f" (ex. {ex})" if ex else ""))

    def scope_text(self) -> str:
        """'3사 순이익 기준, 시작 시총의 28%' 범위 표기."""
        dc = self.f.decomp
        return self.T(f"{dc.n_valid}사 순이익 기준, 시작 시총의 {dc.agg['coverage_t0'] * 100:.0f}%",
                      f"{dc.n_valid}-name net-income basis, {dc.agg['coverage_t0'] * 100:.0f}% of starting cap")

    def head_scope(self) -> str:
        """헤드라인용 짧은 병기: '3사 순이익 기준·시작 시총의 28% — 4사 영업이익 기준이면 멀티플 주도'."""
        o, a = self.f.decomp.op_all, self.f.decomp.agg
        alt_kr = (f" — {o['n']}사 영업이익 기준이면 " + ("멀티플 주도" if o["mult_share"] > o["earn_share"] else "이익 주도")) if o else ""
        alt_en = (f"; {'multiple' if o['mult_share'] > o['earn_share'] else 'earnings'}-led on {o['n']}-name operating income") if o else ""
        return self.T(f"{self.f.decomp.n_valid}사 순이익 기준·시작 시총의 {a['coverage_t0'] * 100:.0f}%{alt_kr}",
                      f"{self.f.decomp.n_valid}-name net income, {a['coverage_t0'] * 100:.0f}% of starting cap{alt_en}")

    def op_alt_text(self) -> str:
        """대안 분해(4사 영업이익 기준) 한 줄 — 없으면 빈 문자열."""
        o = self.f.decomp.op_all if ok(self.f.decomp) else None
        if not o:
            return ""
        lead_kr = "멀티플 주도" if o["mult_share"] > o["earn_share"] else "이익 주도"
        lead_en = "multiple-led" if o["mult_share"] > o["earn_share"] else "earnings-led"
        return self.T(f"{o['n']}사 영업이익 기준이면 이익 기여 {self.share(o['earn_share'])}·멀티플 {self.share(o['mult_share'])}({lead_kr})",
                      f"on {o['n']}-name operating income: earnings {self.share(o['earn_share'])}, multiple {self.share(o['mult_share'])} ({lead_en})")

    def dc_excl_sentence(self) -> str:
        """'두산에너빌리티(시작 시총의 72%)는 FY2022 지배순손실로 분해에서 제외 — 4사 합계 시총 배수 7.7배와 별도'."""
        dc, mk = self.f.decomp, self.f.market
        if not dc.excluded:
            return ""
        parts = [self.T(f"{e['company']}(시작 시총의 {e['share_t0']:.0f}%)는 {e['reason']}로 분해에서 제외",
                        f"{e['company_en']} ({e['share_t0']:.0f}% of starting cap) is excluded from the split: {e['reason_en']}")
                 for e in dc.excluded]
        return "; ".join(parts) + self.T(f" — 4사 합계 시총 배수 {self.x(mk.total_multiple)}와는 별도",
                                         f" — separate from the 4-name combined {self.x(mk.total_multiple)}")

    def contrib_sentence(self) -> str:
        """회사별 해석: 이익 기여 최대 회사 + 멀티플 기여가 더 큰 회사 (계산값으로 생성)."""
        dc = self.f.decomp
        v = dc.valid_rows
        top = v.sort_values("earn_share", ascending=False).iloc[0]
        led = v[v["mult_share"] > v["earn_share"]]
        n = len(v)
        s_top = self.T(f"{top['company']} 이익 기여 {self.share(top['earn_share'])}로 최대",
                       f"{top['company_en']} has the largest earnings share ({self.share(top['earn_share'])})")
        if len(led) == 0:
            s_led = self.T(f"{n}사 모두 이익 기여가 더 컸다", f"earnings outweighed multiples for all {n}")
        elif len(led) == 1:
            r = led.iloc[0]
            s_led = self.T(f"{r['company']}만 멀티플 기여가 더 컸다({self.share(r['mult_share'])})",
                           f"only {r['company_en']} was multiple-led ({self.share(r['mult_share'])})")
        elif len(led) == n:
            s_led = self.T(f"{n}사 모두 멀티플 기여가 더 컸다", f"all {n} were multiple-led")
        else:
            names = ", ".join(self.name(r) for _, r in led.iterrows())
            s_led = self.T(f"{names}는 멀티플 기여가 더 컸다", f"{names} were multiple-led")
        return s_top + " — " + s_led

    def p4(self) -> Page:
        mk, dc, val, c = self.f.market, self.f.decomp, self.f.val, self.c
        if not ok(mk):
            return Page("body", "4", self.T("시장: 데이터 확인 중", "Market: data pending"), self.reason(mk),
                        [self.pending_cell(self.T("시장", "Market"), ["krx"], mk)] * 4)
        led = self.multiple_led()
        if ok(dc):
            a = dc.agg
            g = self.dc_short()
            title = (self.T(f"시장은 이미 알고 있다: {g} 시총 증가의 {self.share(a['mult_share'])}는 멀티플 확대, {self.share(a['earn_share'])}는 이익 증가",
                            f"The market already knows: {self.share(a['mult_share'])} of the gain for {g} is multiple expansion, {self.share(a['earn_share'])} earnings")
                     if led else
                     self.T(f"{g} 순이익 기준으로는 이익 주도({self.share(a['earn_share'])}) — 시작 시총의 {a['coverage_t0'] * 100:.0f}%만 대상, " + self.op_alt_text(),
                            f"On {g} net income, earnings led ({self.share(a['earn_share'])}) — only {a['coverage_t0'] * 100:.0f}% of starting cap; " + self.op_alt_text())) + self.view()
            excl = self.dc_excl_sentence()
            sub = self.T(f"{dc.n_valid}사 합산 PER {self.x(a['per0'])} → {self.x(a['per1'])}" + (f" · {excl}" if excl else ""),
                         f"{dc.n_valid}-name aggregate P/E {self.x(a['per0'])} → {self.x(a['per1'])}" + (f" · {excl}" if excl else ""))
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
        split_note = ""
        for _, r in t[t["split_factor"] != 1].iterrows():
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
                                 extra_labels=[f"×{m:.1f}" for m in t["multiple"]]),
            note=self.T(f"시총 = 각 시점 종가 × 그 시점 상장주식수(KRX MKTCAP). 합계 기준은 시작 시총의 {mk.largest_t0_share:.0f}%인 {big['company']}({big['multiple']:.1f}배)의 비중이 커 단순평균보다 낮다." + split_note,
                        f"Market cap = close × listed shares at each date (KRX MKTCAP). The combined multiple is below the average because "
                        f"{big['company_en']} ({big['multiple']:.1f}x) was {mk.largest_t0_share:.0f}% of the starting cap." + split_note))]
        decomp_note = self.T("로그 분해 Δln(시총) = Δln(지배순이익) + Δln(PER). 2023 초 시총 ↔ FY2022A, 최근 시총 ↔ FY2025A 지배순이익. "
                             "기준·최근 지배순이익이 모두 양수인 회사만 분해 (KSJ Research 계산)",
                             "Log split Δln(cap) = Δln(NI) + Δln(P/E). Start-2023 cap ↔ FY2022A, latest cap ↔ FY2025A NI to parent. "
                             "Only names with positive NI in both years are split (KSJ Research)")
        if ok(dc):
            a = dc.agg
            g = self.dc_group()
            # 2) 합산 폭포
            cells.append(Cell(
                title=self.T(f"{self.dc_short()} 시총 증가 {self.num(a['d_mcap'])}억원 = 이익 기여 {self.num(a['earn_part'])}억원 + 멀티플 기여 {self.num(a['mult_part'])}억원",
                             f"Cap gain for {self.dc_short()}: {self.num(a['d_mcap'])} = earnings {self.num(a['earn_part'])} + multiple {self.num(a['mult_part'])} (KRW 100mn)"),
                src=["krx", "dart"], legend=[(c["brown_dark"], mk.t0), (c["brown_mid"], self.T("기여(+)", "Contribution (+)")),
                                              (c["brick"], self.T("기여(−)", "Contribution (−)")), (c["gold"], mk.t1)],
                unit=self.T(f"억원, {dc.n_valid}사 합산", f"KRW 100mn, {dc.n_valid} names"), chart_key="waterfall",
                chart=charts.waterfall([(mk.t0, a["mcap0"], "total"), (self.T("이익 기여", "Earnings"), a["earn_part"], "delta"),
                                        (self.T("멀티플 기여", "Multiple"), a["mult_part"], "delta"), (mk.t1, a["mcap1"], "total")],
                                       c, lambda x: f"{x:,.0f}"),
                note=self.T(f"대상: {g}. 억원 배분 = Δ시총 × 각 항의 로그 비중. ", f"Scope: {g}. KRW split = Δcap × each term's log share. ") + decomp_note))
            # 3) PER 2023 초 vs 최근 — 분해 가능한 회사만 막대, 제외 회사는 각주
            v = dc.valid_rows
            ex_notes = []
            for e in dc.excluded:   # 최근 PER 왜곡은 per4_footnote 한 곳에서만 설명
                ex_notes.append(self.T(f"{e['company']}: 막대 제외, 시작 PER 없음({e['reason']})",
                                       f"{e['company_en']}: not shown, no starting P/E ({e['reason_en']})"))
            hi_per = v.sort_values("per1", ascending=False).iloc[0]
            cells.append(Cell(
                title=self.T(f"{dc.n_valid}사 합산 PER {self.x(a['per0'])} → {self.x(a['per1'])} — {hi_per['company']} {self.x(hi_per['per1'])}로 최고",
                             f"{dc.n_valid}-name P/E {self.x(a['per0'])} → {self.x(a['per1'])}; {hi_per['company_en']} highest at {self.x(hi_per['per1'])}"),
                src=["krx", "dart"], legend=[(c["warm_grey_light"], self.T(f"2023 초 ({dc.fy0})", f"Start-2023 ({dc.fy0})")),
                                              (c["gold"], self.T(f"최근 ({dc.fy1})", f"Latest ({dc.fy1})"))],
                unit=self.T("배", "x"), chart_key="per",
                chart=charts.grouped([self.name(r) for _, r in v.iterrows()],
                                     [(dc.fy0, list(v["per0"]), c["warm_grey_light"]), (dc.fy1, list(v["per1"]), c["gold"])],
                                     c, lambda x: f"{x:,.1f}", horizontal=True),
                note=self.T("PER = 시총 ÷ 지배순이익. " + "; ".join(ex_notes) + ". " + self.per4_footnote() + self.ni_fallback_note(),
                            "P/E = cap ÷ NI to parent. " + "; ".join(ex_notes) + ". " + self.per4_footnote() + self.ni_fallback_note())))
            # 4) 회사별 이익 vs 멀티플 기여
            cells.append(Cell(
                title=self.contrib_sentence(),
                src=["krx", "dart"], legend=[(c["brown_mid"], self.T("이익 기여", "Earnings share")), (c["gold"], self.T("멀티플 기여", "Multiple share")),
                                              (c["brick"], self.T("음(−)의 기여", "Negative share"))],
                unit=self.T("Δln(시총) 대비 %", "% of Δln(cap)"), chart_key="contrib",
                chart=charts.contrib_bars([self.name(r) for _, r in v.iterrows()], [r["earn_share"] * 100 for _, r in v.iterrows()],
                                          [r["mult_share"] * 100 for _, r in v.iterrows()], c,
                                          (self.T("이익", "Earnings"), self.T("멀티플", "Multiple"))),
                note=self.T("이익 기여 = Δln(지배순이익)/Δln(시총), 멀티플 기여 = Δln(PER)/Δln(시총), 두 값의 합 = 100%. 점선 = 50%. "
                            + "; ".join(f"{e['company']}: {e['reason']}로 분해 불가" for e in dc.excluded),
                            "Earnings share = Δln(NI)/Δln(cap); multiple share = Δln(P/E)/Δln(cap); they sum to 100%. Dashed = 50%. "
                            + "; ".join(f"{e['company_en']}: not split ({e['reason_en']})" for e in dc.excluded))))
            # 5) 분해 결과표 (PER 포함)
            rows, gold, brick, shade, spans = [], set(), set(), set(), []
            for i, (_, r) in enumerate(dc.table.iterrows()):
                cap_x = self.x(r["mcap_t1"] / r["mcap_t0"])
                if not r["valid"]:
                    label = self.T(f"분해 불가({r['reason']})", f"Not split ({r['reason_en']})")
                    rows.append([self.name(r), cap_x, self.gx(r["ni0"], r["ni1"]), "—", label, ""])
                    brick |= {(i, 2), (i, 4)}
                    spans.append((i, 4, 5))
                    continue
                rows.append([self.name(r), cap_x, self.x(r["ni1"] / r["ni0"]),
                             f"{r['per0']:.1f} → {r['per1']:.1f}", self.share(r["earn_share"]), self.share(r["mult_share"])])
                if r["mult_share"] > r["earn_share"]:
                    gold.add((i, 5))
                    shade.add(i)
                for j, val_ in ((4, r["earn_share"]), (5, r["mult_share"])):
                    if val_ < 0:
                        brick.add((i, j))
            rows.append([self.T(f"{dc.n_valid}사 합산", f"{dc.n_valid}-name total"), self.x(a["mcap1"] / a["mcap0"]), self.x(a["ni1"] / a["ni0"]),
                         f"{a['per0']:.1f} → {a['per1']:.1f}", self.share(a["earn_share"]), self.share(a["mult_share"])])
            k = len(rows) - 1
            oa = dc.op_all
            if oa:
                rows.append([self.T(f"참고: {oa['n']}사 영업이익 기준", f"Ref.: {oa['n']}-name operating income"), self.x(oa["mcap1"] / oa["mcap0"]),
                             self.x(oa["op1"] / oa["op0"]) + self.T("(영업)", " (OP)"), f"{oa['pop0']:.1f} → {oa['pop1']:.1f}" + self.T("(시총/영업)", " (cap/OP)"),
                             self.share(oa["earn_share"]), self.share(oa["mult_share"])])
                if oa["mult_share"] > oa["earn_share"]:
                    gold.add((len(rows) - 1, 5))
            cells.append(Cell(
                title=self.T(f"{dc.n_valid}사 합산 PER {self.x(a['per0'])} → {self.x(a['per1'])}: 지배순이익 {self.x(a['ni1'] / a['ni0'])} × PER {self.x(a['per1'] / a['per0'])} = 시총 {self.x(a['mcap1'] / a['mcap0'])}",
                             f"{dc.n_valid}-name aggregate P/E {self.x(a['per0'])} → {self.x(a['per1'])}: NI {self.x(a['ni1'] / a['ni0'])} × P/E {self.x(a['per1'] / a['per0'])} = cap {self.x(a['mcap1'] / a['mcap0'])}"),
                src=["krx", "dart"], unit=self.T("배, PER은 배(2023 초 → 최근), 기여는 %", "x; P/E start-2023 → latest; shares in %"),
                table=TableSpec([self.T("회사", "Company"), self.T("시총 배수", "Cap x"), self.T("지배순이익 배수", "NI x"), self.T("PER (전 → 후)", "P/E (start → latest)"),
                                 self.T("이익 기여", "Earnings"), self.T("멀티플 기여", "Multiple")], rows,
                                [0.22, 0.12, 0.15, 0.19, 0.17, 0.15], shade_rows=shade | {k}, bold_rows={k}, gold_cells=gold | {(k, 5)},
                                brick_cells=brick, font_size=8.4, spans=spans),
                note=self.T("PER = 시총 ÷ 지배순이익(2023 초 ↔ FY2022A, 최근 ↔ FY2025A). 시총 배수 = 지배순이익 배수 × PER 배수. 음영 = 멀티플 기여가 더 큰 회사. 기준 이익이 0 이하인 회사는 배수 대신 라벨. "
                            "참고 행 = 영업이익은 4사 모두 흑자라 바스켓 전체(시작 시총 100%)를 같은 로그 방식으로 분해 — 이익 정의(순이익 vs 영업이익)와 대상 범위에 따라 결론이 갈린다",
                            "P/E = cap ÷ NI (start-2023 ↔ FY2022A, latest ↔ FY2025A). Cap x = NI x × P/E x. Shaded = multiple-led. A label replaces the multiple when the base NI is ≤0. "
                            "Ref. row = all four names have positive operating income, so the whole basket (100% of starting cap) is split the same way — the verdict depends on the earnings definition and scope")))
        else:
            cells.append(self.pending_cell(self.T("시총 변화 분해: 이익 기여 vs 멀티플 기여 (FY2022A 기준)", "Market-cap change split: earnings vs multiple (FY2022A base)"),
                                           ["krx", "dart"], dc, note=decomp_note))
            if ok(val):
                names = [self.name(r) for _, r in val.per.iterrows()]
                hi = val.per.sort_values("per", ascending=False).iloc[0]
                cells.append(Cell(
                    title=self.T(f"현재 PER: 합산 {self.x(val.agg_per)} · 중앙값 {self.x(val.median_per)} — {hi['company']} {self.x(hi['per'], 0)}는 작은 이익의 영향",
                                 f"Current P/E: aggregate {self.x(val.agg_per)} · median {self.x(val.median_per)} — {hi['company_en']} {self.x(hi['per'], 0)} reflects thin earnings"),
                    src=["krx", "dart"], legend=[(c["gold"], self.T("최근 (FY2025A)", "Latest (FY2025A)"))],
                    unit=self.T("배 (로그 축)", "x (log scale)"), chart_key="per",
                    chart=charts.grouped(names, [(self.T("최근 (FY2025A)", "Latest (FY2025A)"), list(val.per["per"]), c["gold"])], c,
                                         lambda x: f"{x:,.1f}", horizontal=True, log=True),
                    note=self.T(f"PER = 최근 시총 ÷ {val.fy} 지배순이익 (KSJ Research 계산). 로그 축. 2023 초 PER(FY2022A 기준)은 데이터 수집 후 표시",
                                f"P/E = latest cap ÷ {val.fy} NI (KSJ Research). Log scale. Start-2023 P/E (FY2022A) shown once collected")))
            else:
                cells.append(self.pending_cell(self.T("PER: 2023 초 vs 최근", "P/E: start-2023 vs latest"), ["krx", "dart"], val))
            cells.append(self.pending_cell(self.T("회사별 분해 결과표 (FY2022A 기준)", "Split by company (FY2022A base)"), ["krx", "dart"], dc,
                                           note=self.T("표 열: 시총 배수 · 지배순이익 배수 · PER · 이익 기여 · 멀티플 기여",
                                                       "Columns: cap x · NI x · P/E · earnings share · multiple share")))
        return Page("body", "4", title, sub, cells, grid="3-2" if len(cells) == 5 else "2x2")

    # --- p5 시사점 ------------------------------------------------------------
    def p5(self) -> Page:
        c, d, g, s, mk, r, fin = self.c, self.f.demand, self.f.ground, self.f.sectors, self.f.market, self.f.rates, self.f.fin
        led = self.multiple_led()
        dc = self.f.decomp
        if ok(dc):
            a = dc.agg
            up = a["per1"] > a["per0"]
            q_kr = (f"{'멀티플이 이끈' if led else '이익이 이끈'} 섹터, {'그러나 ' if up and not led else ''}PER {a['per1']:.0f}배: IPO 공모가는 어떻게 정하나")
            q_en = (f"{'a multiple-led' if led else 'an earnings-led'} sector{', yet' if up and not led else ' at'} {a['per1']:.0f}x P/E: how should an IPO be priced?")
            sub = self.T(f"{self.dc_short()} 합산 PER {self.x(a['per0'])} → {self.x(a['per1'])} · 세 렌즈(ECM 공모가 · 데이터센터 PF · 증설 옵션)와 네 가지 리스크",
                         f"Aggregate P/E of {self.dc_short()} {self.x(a['per0'])} → {self.x(a['per1'])} · three lenses (ECM pricing · data-centre PF · capacity) and four risks")
        else:
            q_kr = "멀티플이 높아진 섹터에서 IPO 공모가는 어떻게 정하나" if led else "이익이 이끈 섹터에서 IPO 공모가는 어떻게 정하나"
            q_en = "how to price an IPO in a sector whose multiples have " + ("re-rated" if led else "followed earnings")
            sub = self.T("세 렌즈(ECM 공모가 · 데이터센터 PF · 증설 옵션)와 네 가지 리스크로 본 시사점",
                         "Implications through three lenses (ECM pricing · data-centre PF · capacity options) and four risks")
        # 제목: 섹터 진단(질문 앞부분) + 다음 노트 로드맵. 질문 전체는 다음 노트 패널에 둔다
        title = self.T(q_kr.split(":")[0] + f" — 그래서 {self.ROADMAP_KR}",
                       q_en.split(":")[0][:1].upper() + q_en.split(":")[0][1:] + f" — hence {self.ROADMAP_EN}") + self.view()
        ecm_data = (f"{self.per_rep()}; " + self.T(f"시총 {self.market_basis()}", f"cap {self.market_basis()}")
                    if self.per_rep() and ok(mk) else self.T("데이터 확인 중", "pending"))
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
            [self.T("ECM 공모가", "ECM pricing"), ecm_data, self.ecm_implication(led)],
            [self.T("데이터센터 PF", "Data-centre PF"), pf_data,
             self.T("판매 물량이 늘고(버지니아) 상업용 요금도 오르는(미국 평균, 명목) 환경에서는 전력구매계약·계통 접속 일정이 PF 현금흐름의 핵심 변수다",
                    "With volumes rising (Virginia) and commercial prices rising (U.S. average, nominal), PPAs and grid-connection timing are the key PF cash-flow variables")],
            [self.T("증설 옵션", "Capacity options"), cap_data,
             self.T("2035년 전망 범위가 넓어 한 번에 짓기보다 단계적 증설로 수요 확인 후 확장하는 구조가 유리하다",
                    "With a wide 2035 range, phased capacity additions that expand as demand is confirmed are preferable")],
        ]
        cells = [Cell(title=self.T("세 렌즈로 본 시사점: 데이터 → 판단", "Three lenses: data → judgement"), src=["krx", "dart", "eia", "iea_ai"],
                      table=TableSpec([self.T("렌즈", "Lens"), self.T("데이터가 말하는 것", "What the data says"),
                                       self.T("시사점", "Implication")], lens_rows, [0.17, 0.38, 0.45],
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
        if self.per_rep():
            anchors.append(self.per_rep())
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
            note=self.T("근거: " + " · ".join(anchors) + ". 위치는 저자의 정성 판단",
                        "Anchors: " + " · ".join(anchors) + ". Positions reflect the author's qualitative judgement")))
        cells.append(Cell(
            title=self.T(f"다음 노트: {self.ROADMAP_KR}", f"Next: {self.ROADMAP_EN}"),
            panel_lead=self.T(q_kr, q_en[:1].upper() + q_en[1:]),
            bullets=[self.T("Vol.2 데이터센터 PF — 한국 40MW(원화)·미국 100MW(달러) 가상 케이스, 대주의 눈으로 본 대출 한도·DSCR·증설 옵션",
                            "Vol.2 data-centre PF — hypothetical Korea 40 MW (KRW) and U.S. 100 MW (USD): debt capacity, DSCR and expansion option from a lender's view"),
                     self.T("Vol.3 IPO 공모가 — 가상 기업 Target Co., 사업·재무 가정과 근거를 함께 공개", "Vol.3 IPO pricing — hypothetical Target Co., assumptions disclosed with their rationale"),
                     self.T("Vol.3 해외 피어 — 국내 피어 PER·EV/EBITDA와 해외 피어(SEC EDGAR) 비교", "Vol.3 overseas peers — Korean peer P/E and EV/EBITDA vs overseas peers (SEC EDGAR)"),
                     self.T("적정 시총 → 공모 할인 → 희망공모가 밴드, 몬테카를로 민감도", "Fair value → IPO discount → indicative price range, Monte Carlo sensitivity")],
            note=self.T("Vol.2·Vol.3 일정·방법은 변경될 수 있음", "Timing and method of Vol.2 and Vol.3 may change")))
        cells.append(Cell(
            title=self.T("이 노트의 한계", "Limitations of this note"),
            bullets=[self.T("현장 데이터는 상업용 판매만 봤다. 데이터센터 부하는 주에 따라 산업용으로 분류될 수 있다", "Ground data covers commercial sales only; data-centre load may be classified as industrial"),
                     self.T("IEA 수치는 보고서 요약값을 원문 대조해 수기 입력했다", "IEA figures are summary values entered manually and checked against the source"),
                     self.T("시총 구간(2023.1~2026.10)과 실적 구간(FY2022A~FY2025A)은 완전히 일치하지 않는다", "The market window (Jan 2023–Oct 2026) and earnings window (FY2022A–FY2025A) do not match exactly"),
                     self.T("PER은 지배순이익 기준이며 일회성 손익을 조정하지 않았다. 이익이 작은 회사는 PER이 크게 왜곡된다", "P/E uses reported NI without one-off adjustments; thin earnings distort P/E"),
                     self.T("표본은 국내 4사다. 해외 피어 비교는 Vol.3에서 다룬다", "The sample is four Korean names; overseas peer comparison comes in Vol.3")]
            + ([self.T(f"분해·대표 PER은 기준 이익이 양수인 {self.f.decomp.n_valid}사 기준이다 — " + ", ".join(f"{e['company']}({e['reason']})" for e in self.f.decomp.excluded) + " 제외",
                       f"The split and headline P/E cover the {self.f.decomp.n_valid} names with positive base NI — excluding " + ", ".join(f"{e['company_en']} ({e['reason_en']})" for e in self.f.decomp.excluded))]
               if ok(self.f.decomp) and self.f.decomp.excluded else []),
            note=self.T("한계는 Vol.2 이후 순차 보완", "To be addressed from Vol.2 onward")))
        return Page("body", "5", title, sub, cells)

    def ecm_implication(self, led: bool | None) -> str:
        """ECM 렌즈 시사점: 멀티플 주도 / 이익 주도 + PER 상승 / 이익 주도 + PER 정체를 데이터로 구분."""
        dc = self.f.decomp
        per_up = ok(dc) and dc.agg["per1"] > dc.agg["per0"]
        if led:
            return self.T("피어 멀티플이 이익보다 앞서 오른 구간에서는 피어 PER을 그대로 쓰기보다 이익 추정의 보수성과 공모 할인으로 방어해야 한다",
                          "When peer multiples have run ahead of earnings, defend the price with conservative earnings and an IPO discount rather than raw peer P/E")
        if per_up:
            a = dc.agg
            g = self.dc_short()
            alt = self.f.decomp.op_all
            alt_kr = " 4사 영업이익 기준이면 멀티플 주도라 단정하지 않는다." if alt and alt["mult_share"] > alt["earn_share"] else ""
            alt_en = " On 4-name operating income it is multiple-led, so no firm verdict." if alt and alt["mult_share"] > alt["earn_share"] else ""
            return self.T(f"{g} 기준 시총 상승은 이익이 주로 설명하지만 PER도 {self.x(a['per0'])}→{self.x(a['per1'])}로 올랐다." + alt_kr + " 피어 PER을 그대로 쓰기보다 이익 지속성 검증과 공모 할인으로 방어해야 한다",
                          f"For {g}, earnings explain most of the gain, but P/E also rose {self.x(a['per0'])}→{self.x(a['per1'])}." + alt_en + " Rather than applying peer P/E as is, test earnings durability and apply an IPO discount")
        return self.T("피어 멀티플이 이익을 따라온 구간이라 이익 추정의 신뢰성이 공모가의 핵심이다",
                      "With multiples tracking earnings, the credibility of the earnings forecast drives pricing")

    # --- Appendix -----------------------------------------------------------
    def a1(self) -> Page:
        d, g, mk, dc, val, fin = self.f.demand, self.f.ground, self.f.market, self.f.decomp, self.f.val, self.f.fin
        qa, key = [], set()
        if ok(d):
            qa.append([self.T("AI 전력 수요는 과장 아닌가?", "Isn't AI power demand overhyped?"),
                       self.T(f"IEA 기준 2030E {self.num(d.v['dc_2030'])}TWh(2024년의 {self.x(d.mult_2030)}), 2025년 AI 데이터센터 {self.pct(d.v['growth_ai'])} vs 전 세계 {self.pct(d.v['growth_global'])}. "
                              f"다만 2035년 범위 {self.num(d.v['dc_2035_low'])}~{self.num(d.v['dc_2035_high'])}TWh로 불확실성은 크다",
                              f"IEA: {self.num(d.v['dc_2030'])} TWh in 2030E ({self.x(d.mult_2030)} 2024); AI data centres {self.pct(d.v['growth_ai'])} in 2025 vs world {self.pct(d.v['growth_global'])}. "
                              f"The 2035 range ({self.num(d.v['dc_2035_low'])}–{self.num(d.v['dc_2035_high'])} TWh) is wide"), "1"])
        if ok(g):
            yy = g.yoy.dropna().set_index("period")
            gap = (yy["VA"] - yy["US"]).loc[lambda x: x.index >= g.recent_from]
            g0y, g1y = int(gap.index[0]), int(gap.index[-1])
            shrink = gap.iloc[-1] < gap.iloc[0]
            qa.append([self.T("버지니아만의 특수 사례 아닌가?", "Isn't Virginia a special case?"),
                       self.T(f"한 주의 사례인 것은 맞다. 다만 상업용 판매가 {g.base_year}년 대비 {self.pct(g.va_change_pct)}(미국 {self.pct(g.us_change_pct)}), 최근 3년 연 {g.va_recent_cagr_pct:.1f}%(미국 {g.us_recent_cagr_pct:.1f}%)다. "
                              f"누적 격차는 {g.gap_pts:.0f}포인트로 벌어졌지만 연간 증가율 격차는 {g0y}년 {gap.iloc[0]:.1f}%p → {g1y}년 {gap.iloc[-1]:.1f}%p로 " + ("줄고 있다" if shrink else "커지고 있다") + ". 산업용 분류 가능성은 한계로 둔다",
                              f"It is one state. But commercial sales are {self.pct(g.va_change_pct)} since {g.base_year} (U.S. {self.pct(g.us_change_pct)}), {g.va_recent_cagr_pct:.1f}%/yr over 3 years (U.S. {g.us_recent_cagr_pct:.1f}%). "
                              f"The cumulative gap has reached {g.gap_pts:.0f} points, but the annual growth gap " + ("narrowed" if shrink else "widened") + f" from {gap.iloc[0]:.1f}pp ({g0y}) to {gap.iloc[-1]:.1f}pp ({g1y}). Industrial classification is a stated limitation"), "2, 5"])
        if ok(fin):
            y0, y1 = fin.years[0], fin.years[-1]
            sg = fin.sum_growth("ni", y0, y1)
            grp = self.group_label(sg, y0, y1)
            if ok(dc):
                a = dc.agg
                ans = self.T(f"{grp} 지배순이익 {self.x(sg.multiple)}(FY{y0}A→FY{y1}A)로 시총 증가({self.x(a['mcap1'] / a['mcap0'])})의 {self.share(a['earn_share'])}를 설명한다",
                             f"NI of {grp} rose {self.x(sg.multiple)} (FY{y0}A→FY{y1}A), explaining {self.share(a['earn_share'])} of the market-cap gain ({self.x(a['mcap1'] / a['mcap0'])})")
            else:
                ans = self.T(f"{grp} 지배순이익 FY{y0}A→FY{y1}A {self.x(sg.multiple)}, 이익은 늘었지만 시총({self.x(mk.total_multiple)})보다는 느렸다" if ok(mk) else f"{grp} 지배순이익 {self.x(sg.multiple)}",
                             f"NI of {grp} {self.x(sg.multiple)} FY{y0}A→FY{y1}A — growing, but slower than market cap ({self.x(mk.total_multiple)})" if ok(mk) else f"NI of {grp} {self.x(sg.multiple)}")
            qa.append([self.T("실적이 받쳐주나?", "Do earnings support it?"), ans, "3, 4"])
        if ok(mk):
            if ok(dc):
                a = dc.agg
                ans = self.T(f"{self.dc_short()} 시총 증가 중 이익 기여 {self.share(a['earn_share'])}, 멀티플 기여 {self.share(a['mult_share'])}({self.scope_text()}). PER은 {self.x(a['per0'])} → {self.x(a['per1'])}로 올랐다{self.view()}. "
                             + (f"다만 {self.op_alt_text()} — 이익 정의와 범위에 따라 결론이 갈린다" if self.f.decomp.op_all else ""),
                             f"For {self.dc_short()}, earnings explain {self.share(a['earn_share'])} and multiples {self.share(a['mult_share'])} ({self.scope_text()}); P/E rose {self.x(a['per0'])} → {self.x(a['per1'])}{self.view()}. "
                             + (f"But {self.op_alt_text()} — the verdict depends on the earnings definition and scope" if self.f.decomp.op_all else ""))
            else:
                n, tot = self.n_mcap_beats_ni() if ok(val) else (0, 0)
                ans = self.T(f"4사 시총 {self.market_basis()}. 가용 실적으로도 {tot}사 중 {n}곳은 시총이 이익보다 빨랐다{self.view()}. FY2022 기준 분해는 수집 후",
                             f"Cap {self.market_basis()}; on available earnings, {n} of {tot} saw cap outgrow NI{self.view()}. FY2022-based split after collection")
            qa.append([self.T("시장은 이미 반영했나?", "Has the market priced it in?"), ans, "4"])
            for _, r in mk.table[mk.table["split_factor"] != 1].iterrows():
                key.add(len(qa))
                qa.append([self.T(f"{r['company']} 주가는 {r['price_multiple_raw']:.0f}배인데 왜 시총은 {r['multiple']:.0f}배인가?",
                                  f"Why is {r['company_en']}'s price up {r['price_multiple_raw']:.0f}x but its market cap {r['multiple']:.0f}x?"),
                           self.T(f"{r['action_date']} {r['split_factor']:.0f}:1 액면분할 때문이다. 주가 {self.num(r['close_t0'])}원 → {self.num(r['close_t1'])}원({r['price_multiple_raw']:.2f}배)은 분할 전후 주식 1주의 크기가 다르다. "
                                  f"분할 조정 주가 배수 {r['price_multiple_raw']:.2f}×{r['split_factor']:.0f} = {r['price_multiple_adj']:.1f}배로 시총 배수(상장주식수 {self.num(r['shares_t0'])}→{self.num(r['shares_t1'])}주)와 같다",
                                  f"A {r['split_factor']:.0f}:1 split on {r['action_date']}. The price move KRW {self.num(r['close_t0'])} → {self.num(r['close_t1'])} ({r['price_multiple_raw']:.2f}x) compares different share sizes; "
                                  f"split-adjusted {r['price_multiple_raw']:.2f}×{r['split_factor']:.0f} = {r['price_multiple_adj']:.1f}x, matching the cap multiple (shares {self.num(r['shares_t0'])}→{self.num(r['shares_t1'])})"),
                           "4, A2"])
            big = mk.largest_t0
            key.add(len(qa))
            qa.append([self.T(f"합계 {self.x(mk.total_multiple)}와 평균 {self.x(mk.mean_multiple)} 중 무엇이 맞나?",
                              f"Which is right: {self.x(mk.total_multiple)} combined or {self.x(mk.mean_multiple)} average?"),
                       self.T(f"둘 다 맞고 질문이 다르다. 합계는 4사 바스켓(시총 가중), 평균은 회사별 동일 가중이다. 시작 시총의 {mk.largest_t0_share:.0f}%가 {big['company']}({big['multiple']:.1f}배)라 합계가 낮다. "
                              "섹터 전체 가치 변화는 합계, 종목별 재평가 폭은 평균으로 본다",
                              f"Both — they answer different questions. Combined is a cap-weighted basket; the average weights names equally. {big['company_en']} ({big['multiple']:.1f}x) was "
                              f"{mk.largest_t0_share:.0f}% of the starting cap, pulling the combined figure down. Use combined for sector value, average for per-name re-rating"),
                       "4"])
        if ok(dc):
            # 분해에서 빠진 회사
            for e in dc.excluded:
                key.add(len(qa))
                cur = self.f.val.per.set_index("ticker").loc[e["ticker"]] if ok(val) else None
                qa.append([self.T(f"{e['company']}는 왜 분해에서 빠졌나?", f"Why is {e['company_en']} excluded from the split?"),
                           self.T(f"PER = 시총 ÷ 지배순이익인데 {dc.fy0} 지배순이익이 {self.num(e['ni0'])}억원으로 0 이하라 시작 PER과 로그 변화를 정의할 수 없다"
                                  f"({dc.fy1} {self.num(e['ni1'])}억원, 흑자전환). 시작 시총의 {e['share_t0']:.0f}%라 4사 합계 시총 배수({self.x(mk.total_multiple)})에는 포함하고, 분해·대표 PER은 {dc.n_valid}사 기준으로 계산했다"
                                  + (f". 최근 PER {self.x(cur['per'], 0)}는 작은 이익의 분모 왜곡" if cur is not None and cur['per'] == cur['per'] else ""),
                                  f"P/E = cap ÷ NI, and {dc.fy0} NI was {self.num(e['ni0'])} (KRW 100mn), ≤0, so the starting P/E and log change are undefined "
                                  f"({dc.fy1}: {self.num(e['ni1'])}, turned profitable). At {e['share_t0']:.0f}% of the starting cap it stays in the 4-name combined multiple ({self.x(mk.total_multiple)}), "
                                  f"but the split and headline P/E use {dc.n_valid} names"
                                  + (f". Its latest P/E of {self.x(cur['per'], 0)} reflects a thin denominator" if cur is not None and cur['per'] == cur['per'] else "")),
                           "3, 4"])
            # 멀티플이 주도한 회사 (데이터 범위 내 답)
            v = dc.valid_rows
            ranked = v.assign(nix=v["ni1"] / v["ni0"]).sort_values("nix")
            for _, r in v[v["mult_share"] > v["earn_share"]].iterrows():
                rank = list(ranked["ticker"]).index(r["ticker"]) + 1
                only = len(v[v["mult_share"] > v["earn_share"]]) == 1
                key.add(len(qa))
                qa.append([self.T(f"{r['company']}{'만' if only else '는'} 멀티플이 주도한 이유는?", f"Why was {r['company_en']} multiple-led?"),
                           self.T(f"시총 {self.x(r['mcap_t1'] / r['mcap_t0'])} 중 지배순이익은 {self.x(r['ni1'] / r['ni0'])}로 {dc.n_valid}사 중 {'가장' if rank == 1 else f'{rank}번째로'} 작게 늘었고, PER은 {self.x(r['per0'])} → {self.x(r['per1'])}로 올라 "
                                  f"멀티플 기여가 {self.share(r['mult_share'])}가 됐다. 수주·사업 구성 등 원인은 이 노트의 데이터 범위 밖이라 판단하지 않는다",
                                  f"Its cap rose {self.x(r['mcap_t1'] / r['mcap_t0'])} while NI rose {self.x(r['ni1'] / r['ni0'])} (rank {rank} of {dc.n_valid}, smallest first), and P/E went "
                                  f"{self.x(r['per0'])} → {self.x(r['per1'])}, so the multiple share is {self.share(r['mult_share'])}. Causes such as orders or business mix are outside this note's data"),
                           "4"])
        if self.per_rep():
            if ok(dc):
                ans = self.T(f"대표값은 {self.per_rep()}. 이익이 늘었는데도 PER이 올랐다는 점이 핵심이다. 거품 여부는 이익 지속성에 달렸다{self.view()}",
                             f"Headline: {self.per_rep()}. P/E rose even as earnings grew; whether it is a bubble depends on earnings durability{self.view()}")
            else:
                hi = val.per.sort_values("per", ascending=False).iloc[0]
                ans = self.T(f"{self.per_rep()}. {hi['company']} {self.x(hi['per'], 0)}는 지배순이익 {self.num(hi['ni'])}억원으로 분모가 작아 생긴 왜곡이다. 거품 여부는 이익 지속성에 달렸다{self.view()}",
                             f"{self.per_rep()}. {hi['company_en']}'s {self.x(hi['per'], 0)} reflects thin NI ({self.num(hi['ni'])}, KRW 100mn). It depends on earnings durability{self.view()}")
            qa.append([self.T("PER이 높은데 거품인가?", "P/Es are high — is it a bubble?"), ans, "4, 5"])
        qa.append([self.T("다음 노트는?", "What comes next?"),
                   self.T(f"{self.ROADMAP_KR}. Vol.2는 AI 데이터센터 PF의 대출 한도를 대주의 눈으로, Vol.3는 이 노트의 PER 수준을 반영한 IPO 희망공모가 밴드와 해외 피어 비교를 다룬다",
                          f"{self.ROADMAP_EN}. Vol.2 sizes AI data-centre PF debt from a lender's view; Vol.3 sets an IPO price range reflecting this note's P/E levels and compares overseas peers"),
                   "5"])
        qa.append([self.T("이 분석을 어떻게 재현하나?", "How can this be reproduced?"),
                   self.T(f"전체 코드와 데이터 출처는 GitHub에 공개: {self.cfg['research']['repo_url']}",
                          f"Full code and data sources are public on GitHub: {self.cfg['research']['repo_url']}"), "A3"])
        cell = Cell(title=self.T(f"예상 질문 {len(qa)}개와 답", f"{len(qa)} expected questions"), src=["iea_ai", "eia", "krx", "dart", "corp"],
                    table=TableSpec([self.T("질문", "Question"), self.T("답", "Answer"), self.T("근거 쪽", "Page")], qa, [0.24, 0.68, 0.08],
                                    ["L", "L", "C"], shade_rows=key, font_size=8.1),
                    note=self.T("답의 숫자는 본문과 같은 계산 결과. 음영 = 데이터 처리 방식 관련 질문", "Numbers match the body; shaded = data-treatment questions"))
        return Page("full", "A1", self.T("예상 질의응답: 숫자로 답한다", "Expected Q&A: answered with numbers"),
                    self.T("투자검토·실사에서 나올 질문과 근거 쪽수", "Questions likely in investment review or due diligence, with page references"), [cell], grid="1x1")

    # A2 데이터셋 이름 (API 코드명 대신 통계 이름)
    DATASETS = {
        "dart": ("단일회사 전체 재무제표 (사업보고서, 연결 우선)", "Single-company full financial statements (annual report, consolidated first)"),
        "krx": ("유가증권 일별매매정보", "KOSPI daily trading data"),
        "eia": ("Electricity retail sales (주별·부문별, 연간)", "Electricity retail sales (by state and sector, annual)"),
        "ecos": ("시장금리(일별), 주요국 통화의 대원화환율", "Market interest rates (daily), KRW exchange rates"),
        "fred": ("10-Year Treasury Constant Maturity (DGS10), KRW/USD (DEXKOUS)", "10-Year Treasury Constant Maturity (DGS10), KRW/USD (DEXKOUS)"),
        "iea": ("Energy and AI (2025.4), Key Questions on Energy and AI (2026.4)", "Energy and AI (Apr 2025), Key Questions on Energy and AI (Apr 2026)"),
    }
    ROADMAP_KR = "Vol.2 데이터센터 PF(한국 40MW·미국 100MW), Vol.3 IPO 공모가·해외 피어"
    ROADMAP_EN = "Vol.2 data-centre PF (Korea 40 MW, U.S. 100 MW), Vol.3 IPO pricing and overseas peers"
    BUILT_WITH_KR = "구현: AI 코딩 도구(Claude Code)로 데이터 수집·계산·보고서 생성 코드를 작성. 질문 설계, 분석 범위 결정, 숫자 검증은 저자."
    BUILT_WITH_EN = "Built with an AI coding tool (Claude Code); question design, scope decisions and number verification by the author."
    PUBLIC_SOURCES = ("dart", "krx", "eia", "ecos", "fred", "iea")   # 해외 피어(SEC)는 Vol.3

    def a2(self) -> Page:
        mk = self.f.market
        srcs = [s for s in self.f.sources if s["id"] in self.PUBLIC_SOURCES]
        rows = [[s["org_kr"] if self.kr else s["org_en"], self.T(*self.DATASETS[s["id"]]), s["item_kr"] if self.kr else s["item_en"],
                 s["as_of"] or "—", s["status_kr"] if self.kr else s["status_en"]] for s in srcs]
        pend = {i for i, s in enumerate(srcs) if not s["ok"]}
        c1 = Cell(title=self.T("데이터 소스 · 통계 · 기준일", "Data sources · datasets · as-of dates"),
                  table=TableSpec([self.T("소스", "Source"), self.T("통계", "Dataset"), self.T("항목", "Items"), self.T("기준일", "As of"), self.T("상태", "Status")],
                                  rows, [0.17, 0.36, 0.23, 0.11, 0.13], ["L", "L", "L", "C", "C"], shade_rows=pend,
                                  brick_cells={(i, 4) for i in pend}, font_size=8.4),
                  note=self.T("기준일 = 데이터 수집 기준일(IEA는 원문 대조일). 해외 피어 비교는 Vol.3에서 다룸. " + self.cfg["research"]["vol01"].get("source_note_kr", ""),
                              "As-of = data collection date (IEA: date checked against the source). Overseas peer comparison comes in Vol.3. " + self.cfg["research"]["vol01"].get("source_note_en", "")))
        if ok(mk):
            krows, shade, brick = [], set(), set()
            for i, (_, r) in enumerate(mk.table.iterrows()):
                act = {"split_consistent": self.T(f"{r['action_date']} {r['split_factor']:.0f}:1 액면분할 (주식수 비율 일치)", f"{r['split_factor']:.0f}:1 split {r['action_date']} (ratio matches)"),
                       "split_mismatch": self.T("분할 비율과 주식수 비율 불일치 — 확인 필요", "Split ratio and share ratio differ — check"),
                       "unchanged": self.T("변동 없음", "No change"),
                       "changed_unexplained": self.T(f"주식수 {(r['share_ratio'] - 1) * 100:+.2f}% — 공시 확인 필요(시총 배수 영향 미미)", f"Shares {(r['share_ratio'] - 1) * 100:+.2f}% — to be checked in filings (negligible effect)")}[r["share_note"]]
                krows.append([self.name(r), self.num(r["shares_t0"]), self.num(r["shares_t1"]), act, self.x(r["price_multiple_raw"], 2),
                              self.x(r["price_multiple_adj"], 2), self.x(r["multiple"], 2), f"{max(abs(r['mcap_check_t0']), abs(r['mcap_check_t1'])):.2f}%"])
                if r["share_note"] != "unchanged":
                    shade.add(i)
                if r["share_note"] in ("split_mismatch", "changed_unexplained"):
                    brick.add((i, 3))
            c2 = Cell(title=self.T(f"시총 검산: 각 시점 상장주식수 사용 확인 ({mk.t0} · {mk.t1})", f"Market-cap check: listed shares at each date ({mk.t0} · {mk.t1})"),
                      src=["krx", "corp"],
                      table=TableSpec([self.T("회사", "Company"), self.T(f"상장주식수 {mk.t0}", f"Shares {mk.t0}"), self.T(f"상장주식수 {mk.t1}", f"Shares {mk.t1}"),
                                       self.T("증자·분할", "Corporate action"), self.T("주가 배수(원)", "Price x (raw)"), self.T("분할 조정 주가 배수", "Split-adj. price x"),
                                       self.T("시총 배수", "Cap x"), self.T("시총 검산 오차", "Cap check")], krows,
                                      [0.14, 0.12, 0.12, 0.25, 0.09, 0.11, 0.08, 0.09], ["L", "R", "R", "L", "R", "R", "R", "R"],
                                      shade_rows=shade, brick_cells=brick,
                                      gold_cells={(i, 6) for i, (_, r) in enumerate(mk.table.iterrows()) if r["split_factor"] != 1},
                                      font_size=8.0),
                      note=self.T("시총 = 한국거래소 시가총액(각 시점 종가 × 그 시점 상장주식수). 검산 오차 = 종가 × 상장주식수 ÷ 시가총액 − 1. 분할 조정 주가 배수 = 주가 배수 × 분할 비율. "
                                  "주가를 비교할 때는 분할 조정 주가를 쓴다. 기업행위는 회사 공시로 확인",
                                  "Cap = KRX market cap (close × listed shares at each date). Check = close × shares ÷ market cap − 1. Split-adjusted price x = price x × split ratio. "
                                  "Price comparisons use split-adjusted prices. Corporate actions checked against company filings"))
        else:
            c2 = self.pending_cell(self.T("시총 검산", "Market-cap check"), ["krx"], mk)
        return Page("full", "A2", self.T("데이터 노트: 출처·통계·기준일, 그리고 시총 검산", "Data notes: sources, datasets, dates and the market-cap check"),
                    self.T("LS ELECTRIC 액면분할 반영 방법 명시 · 시총은 각 시점 상장주식수 기준 · 해외 피어 비교는 Vol.3",
                           "LS ELECTRIC split treatment stated · market cap uses listed shares at each date · overseas peers in Vol.3"),
                    [c1, c2], grid="2x1")

    def a3(self) -> Page:
        f = self.f
        names = [s["org_kr"].split(" · ")[0] if self.kr else s["org_en"].split(" · ")[0]
                 for s in f.sources if s["id"] in self.PUBLIC_SOURCES and s["id"] != "iea"]
        steps = [
            (self.T("1. 공식 출처 수집", "1. Official sources"),
             names + [self.T("IEA 보고서(원문 대조)", "IEA reports (verified)")]),
            (self.T("2. 검증", "2. Validation"),
             [self.T("시총 = 종가 × 상장주식수", "Cap = close × listed shares"), self.T("액면분할 대조", "Stock-split check"),
              self.T("종목 식별자 확인", "Identifier check"), self.T("단위·환율 검산", "Units and FX")]),
            (self.T("3. 계산", "3. Calculation"),
             [self.T("지수·CAGR", "Indices, CAGR"), self.T("로그 분해", "Log decomposition"), "Δln(cap) = Δln(NI) + Δln(P/E)",
              self.T("기준 이익 ≤0 제외", "Exclude base NI ≤0")]),
            (self.T("4. 보고서", "4. Report"),
             [self.T("결론형 제목", "Conclusion titles"), self.T("국문·영문", "Korean & English"), self.T("출처·기준일 각주", "Sources and dates")]),
        ]
        url = self.cfg["research"]["repo_url"]
        c1 = Cell(title=self.T("공식 출처 수집 → 검증 → 계산 → 보고서", "Official sources → validation → calculation → report"),
                  src=["ksj"], chart_key="method", chart=charts.flow4(steps, self.c), strip=self.T(self.BUILT_WITH_KR, self.BUILT_WITH_EN),
                  note=self.T(f"전체 코드·데이터 출처: GitHub {url}", f"Full code and data sources: GitHub {url}"))
        return Page("full", "A3", self.T("분석 방법과 데이터: 공식 출처를 검증하고 계산해 보고서로", "Methodology: official data, validated and calculated into this report"),
                    self.T("모든 숫자는 공식 출처 데이터에서 계산했고, 출처와 기준일을 각주에 적었다",
                           "Every figure is calculated from official-source data, with sources and dates in the footnotes"),
                    [c1], grid="1x1")

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
