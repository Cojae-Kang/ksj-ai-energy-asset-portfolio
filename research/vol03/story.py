"""Vol.3 페이지 구성·문구 (국문/영문). 숫자는 모두 data.Facts에서, 결론 문장도 계산 결과로 만든다.

공개용 원칙(Vol.1·Vol.2와 같음): 제목에 '(저자 견해)'를 붙이지 않고 요약 쪽 하단·뒤표지에 한 줄만 둔다.
내부 파일·설정·실행 명령·태그는 보고서에 쓰지 않는다. 데이터가 없는 계산은 "데이터·출처 확인 후 생성" 박스로 둔다.
"""
from __future__ import annotations

import math
import re
from typing import Mapping

import numpy as np

from research.vol01.layout import BigBox, Cell, Page, TableSpec, toc_line

from . import charts
from .data import LABELS, SCEN, Assumption, Facts, Unavailable, fmt_missing, ok

SCEN_KR = {"current": "현재", "normalized": "정상화", "conservative": "보수"}
SCEN_EN = {"current": "Current", "normalized": "Normalised", "conservative": "Conservative"}
SIM_KR = {"high": "높음", "mid": "중간", "low": "낮음"}
SIM_EN = {"high": "high", "mid": "medium", "low": "low"}
STATUS_KR = {"applied": "적용", "reference": "참고", "excluded": "제외", "pending": "시총 수집 후 확정", "held": "10-K 확인 전 제외"}
STATUS_EN = {"applied": "Applied", "reference": "Reference", "excluded": "Excluded", "pending": "After market data", "held": "Held: pending 10-K"}
A_STATUS_KR = {"input": "입력 필요", "verify": "원문 확인", "sourced": "근거 있음", "judgment": "저자 판단", "data": "데이터",
               "design": "설계값", "neutral": "중립값", "derived": "계산"}
A_STATUS_EN = {"input": "Input needed", "verify": "Verify", "sourced": "Sourced", "judgment": "Judgment", "data": "Data",
               "design": "Design", "neutral": "Neutral", "derived": "Derived"}
SOURCE_EN = {
    "revenue": "Hypothetical company size, FY2025A — above the mid-size threshold; sets the price unit only",
    "midsize_threshold": "Framework Act on SMEs, Enforcement Decree Annex 1 (electrical equipment: KRW 150bn average revenue)",
    "revenue_growth": "DART, 3-name combined revenue CAGR FY2022A→FY2025A (range = min–max)",
    "opm": "DART, 3-name combined operating margin FY2025A (range = min–max)",
    "npm": "DART, 3-name combined net margin to parent FY2025A (range = min–max)",
    "net_debt_ratio": "DART, net debt ÷ revenue FY2025A (names with debt data; range = min–max)",
    "da_ratio": "DART cash-flow statement D&A ÷ revenue FY2025A",
    "shares_pre": "Hypothetical pre-IPO share count — changes the price level only",
    "offer_ratio": "Offer as % of post-IPO shares — KRX listing rules' free-float requirement (e.g. 25% public holders)",
    "new_share_ratio": "Primary share of the offer (rest secondary sale) — hypothetical deal design",
    "growth_mean": "DART, 9 annual revenue growth observations FY2023A–FY2025A (log mean)",
    "growth_sd": "Same 9 observations (log standard deviation)",
    "per_shape": "Triangular: min conservative, mode normalised, max current — neutral shape without probability evidence",
    "band_q_low": "Band low = 25th percentile of 1-yr value (25% loss probability at the low end)",
    "band_q_high": "Band top = median 1-yr value (50% loss probability at the top)",
    "npm_low": "DART, 3-name combined net margin FY2022A (trough end)",
    "npm_mode": "DART, 3-name combined net margin over FY2022A–FY2025A (cycle average)",
    "npm_high": "DART, 3-name combined net margin FY2025A (today = peak end)",
    "npm_shape": "Triangular with the mode at the 4-yr cycle average = mean reversion; capped at today, floored at FY2022A",
    "corr_growth_per": "Growth–P/E correlation 0: no data to estimate (neutral); co-movement tested as a sensitivity",
    "corr_growth_npm": "Growth–margin correlation 0: no data to estimate (neutral)",
    "corr_npm_per": "Margin–P/E correlation 0: neutral; in reality both may fall together, so the downside may be understated",
    "inst_lockup_2025": "FSS release: institutional lock-up commitments 41% in 2025 (Money Today)",
    "inst_lockup_2024": "FSS release: institutional lock-up commitments 18% in 2024 (Money Today)",
    "inst_lockup_kospi_2025": "FSS release: KOSPI institutional lock-up commitments 54% in 2025 (Money Today)",
    "ipo_in_band_2025": "FSS release: every 2025 IPO priced within its range (Money Today)",
    "top_of_band_h2_2025": "FSS release: 97% of H2 2025 listings priced at the top of the range (Money Today)",
}
MISSING_KR = {"da_ratio": "미수집 → EV/EBIT로 대용", "lockup_months": "미입력 → 오버행은 주식수로만 표시",
              "band_discount_low": "미입력 → 몬테카를로 분위로 밴드", "band_discount_high": "미입력 → 몬테카를로 분위로 밴드"}
MISSING_EN = {"da_ratio": "Not collected → EV/EBIT as proxy", "lockup_months": "Not set → overhang shown in shares only",
              "band_discount_low": "Not sourced → band from Monte Carlo quantiles", "band_discount_high": "Not sourced → band from Monte Carlo quantiles"}
UNIT_EN = {"억원": "KRW 100mn", "주": "shares", "개월": "months", "%": "%", "-": "-"}


class Story:
    def __init__(self, cfg: Mapping, f: Facts, lang: str):
        self.cfg, self.f, self.lang, self.kr = cfg, f, lang, lang == "kr"
        self.c = cfg["research"]["colors"]
        self.v = cfg["research"]["vol03"]

    # --- 문구·숫자 도우미 ---------------------------------------------------
    def T(self, kr: str, en: str) -> str:
        return kr if self.kr else en

    def x(self, v: float | None, d: int = 1) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:,.{d}f}배" if self.kr else f"{v:,.{d}f}x"

    @staticmethod
    def pct(v: float | None, d: int = 1, sign: bool = False) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v * 100:+.{d}f}%" if sign else f"{v * 100:.{d}f}%"

    def won(self, v: float | None) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        return f"{v:,.0f}원" if self.kr else f"KRW {v:,.0f}"

    def won_rng(self, lo: float, hi: float) -> str:
        return f"{lo:,.0f}~{hi:,.0f}원" if self.kr else f"KRW {lo:,.0f}–{hi:,.0f}"

    def eok(self, v: float | None) -> str:
        if v is None or not math.isfinite(v):
            return "—"
        if self.kr:
            return f"{v:,.0f}억원"
        return f"KRW {v / 10:,.0f}bn" if abs(v) >= 1000 else f"KRW {v / 10:,.1f}bn"

    def usd(self, v: float | None) -> str:
        return "—" if v is None or not math.isfinite(v) else f"USD {v:,.0f}mn"

    def shares(self, v: float) -> str:
        return f"{v / 1e4:,.1f}만주".replace(".0만", "만") if self.kr else f"{v / 1e6:,.4g}mn shares"

    def money(self, r, v: float | None) -> str:
        """회사 통화 단위: 국내 억원, 해외 USD mn."""
        return self.eok(v) if r["region"] == "KR" else self.usd(v)

    def rng(self, lo: float, hi: float, fmt) -> str:
        return f"{fmt(lo)}~{fmt(hi)}" if self.kr else f"{fmt(lo)}–{fmt(hi)}"

    def scen(self, s: str) -> str:
        return SCEN_KR[s] if self.kr else SCEN_EN[s]

    def lab(self, key: str) -> str:
        return LABELS.get(key, (key, key))[0 if self.kr else 1]

    def cname(self, r) -> str:
        return r["company"] if self.kr else r["company_en"]

    def A(self, key: str) -> Assumption:
        return self.f.assumptions[key]

    def missing_text(self, u: Unavailable) -> str:
        if not u.missing:
            return self.T(u.reason, u.reason_en or u.reason)
        return self.T(f"{u.reason} — 필요: {fmt_missing(u.missing, True)}", f"{u.reason_en or u.reason} — needed: {fmt_missing(u.missing, False)}")

    def pending(self, title: str, src: list[str], reason: str, note: str = "") -> Cell:
        return Cell(title=title, src=src, placeholder=(reason, ""), note=note)

    def us_pending_reason(self) -> str:
        return self.T("미국 피어 시가총액(기준일·2023년 첫 거래일 종가 × SEC 발행주식수) 수집 후 생성",
                      "Generated once U.S. peers' market caps (close on the as-of date and first 2023 trading day × SEC shares) are collected")

    # --- 계산 결과 조각 -----------------------------------------------------
    @property
    def ok_all(self) -> bool:
        f = self.f
        return ok(f.peers) and ok(f.mult) and ok(f.val) and ok(f.mc) and ok(f.band)

    def n_dom(self) -> int:
        return self.f.mult.groups["domestic"]["current"].n if ok(self.f.mult) else 0

    def dom_label(self) -> str:
        return self.T(f"국내 {self.n_dom()}사", f"{self.n_dom()} Korean names")

    def applied_label(self) -> str:
        mu = self.f.mult
        if mu.applied_group == "domestic":
            return self.T(f"{self.dom_label()} (해외 시총 수집 전)", f"{self.dom_label()} (before U.S. market data)")
        return self.T("국내·해외 핵심 평균", "Korea and U.S. core average")

    def per(self, s: str = "current") -> float:
        return self.f.mult.applied(s)

    def band_text(self) -> str:
        b = self.f.band
        return self.won_rng(b.low, b.high) if ok(b) else "—"

    def disc_text(self) -> str:
        b = self.f.band
        if not ok(b):
            return "—"
        return f"{b.d_low * 100:.0f}~{b.d_high * 100:.0f}%" if self.kr else f"{b.d_low * 100:.0f}–{b.d_high * 100:.0f}%"

    def band_basis(self) -> str:
        b, a = self.f.band, self.f.assumptions
        if not ok(b):
            return ""
        if b.basis == "config":
            return self.T("입력 할인율 기준", "input discounts")
        if b.basis == "evidence":
            return self.T(f"국내 IPO {self.ipo_label()} 할인율 중앙값", f"median Korean IPO discount, {self.ipo_label()}")
        return self.T(f"1년 후 주당가치 P{a['band_q_low'].value * 100:.0f}~P{a['band_q_high'].value * 100:.0f}",
                      f"P{a['band_q_low'].value * 100:.0f}–P{a['band_q_high'].value * 100:.0f} of 1-yr value")

    def da_missing(self) -> tuple[list[str], list[str]]:
        """D&A가 없는 적용 비교기업 (국문, 영문 이름)."""
        t = self.f.peers.table
        m = t[t["group"].isin(["domestic", "core"]) & (t["status"] == "applied") & t["da1"].isna()]
        return list(m["company"]), list(m["company_en"])

    def core_with_held(self) -> float:
        """보류 회사를 다시 넣었을 때의 해외 핵심 합산 PER (비교용)."""
        t = self.f.peers.table
        r = t[(t["group"] == "core") & t["status"].isin(["applied", "held"]) & (t["ni1"] > 0) & t["mcap1"].notna()]
        return float(r["mcap1"].sum() / r["ni1"].sum()) if len(r) else float("nan")

    def high_flag_rows(self):
        t = self.f.peers.table
        return t[t["high_flag"]]

    def excluded_dom(self):
        t = self.f.peers.table
        return t[(t["group"] == "domestic") & (t["status"] == "excluded")]

    def offer_amount(self, price: float) -> float:
        return self.f.val.shares.offered * price / 1e8

    # --- 출처·고정 문구 ----------------------------------------------------
    def sources(self) -> dict[str, str]:
        return {
            "dart": self.T("금융감독원 DART 사업보고서(연결)", "FSS DART annual reports (consolidated)"),
            "krx": self.T("한국거래소 KRX 일별매매정보(종가·시가총액·상장주식수)", "Korea Exchange (KRX) daily trading data"),
            "sec": self.T("SEC EDGAR 10-K XBRL(companyfacts)·표지 발행주식수", "SEC EDGAR 10-K XBRL (companyfacts), cover-page shares"),
            "yf": self.T("yfinance(Yahoo Finance 보조 소스, SEC 주식수로 교차 확인)", "yfinance (Yahoo Finance, secondary; cross-checked with SEC shares)"),
            "ecos": self.T("한국은행 ECOS 원/달러 매매기준율", "Bank of Korea ECOS USD/KRW"),
            "law": self.T("중소기업기본법 시행령 별표1, 한국거래소 상장규정(주식분산 요건)",
                          "Framework Act on SMEs Enforcement Decree Annex 1; KRX listing rules (free-float requirement)"),
            "vol1": self.T("KSJ Research Vol.1(2026.10)", "KSJ Research Vol.1 (Oct 2026)"),
            "vol2": self.T("KSJ Research Vol.2(2026.10)", "KSJ Research Vol.2 (Oct 2026)"),
            "fss": self.T("머니투데이(2026-03-04, 금융감독원 발표 인용): 2025년 IPO 기관 의무보유확약·공모가 결정 위치",
                          "Money Today (4 Mar 2026, citing an FSS release): 2025 IPO lock-up commitments and pricing within the range"),
            "ipo": (self.T(f"DART 증권신고서(지분증권) 신규 상장, 신고일 {self.f.ipo.full.period[0]}~{self.f.ipo.full.period[1]}",
                           f"DART equity prospectuses, new listings filed {self.f.ipo.full.period[0]} to {self.f.ipo.full.period[1]}")
                    if ok(self.f.ipo) and self.f.ipo.full.n else self.T("DART 증권신고서(지분증권) 신규 상장", "DART equity prospectuses, new listings")),
            "ksj": "KSJ Research",
        }

    def labels(self) -> dict[str, str]:
        return {"source": self.T("출처", "Source"), "note": self.T("주", "Note"), "unit": self.T("단위", "Unit"),
                "pending": self.T("데이터·출처 확인 후 생성", "Generated once data are collected")}

    def footer(self) -> str:
        return self.T(f"KSJ Research · Research Note Vol.3 · {self.v['date_label']} · 교육·연구 목적, 투자 권유 아님 · Target Co.는 가상 기업",
                      f"KSJ Research · Research Note Vol.3 · {self.v['date_label']} · For education and research only, "
                      "not investment advice · Target Co. is hypothetical")

    # =======================================================================
    # 페이지
    # =======================================================================
    def pages(self) -> list[Page]:
        return [self.cover(), self.executive(), self.toc_page(), self.p1(), self.p2(), self.p3(), self.p4(), self.p5(),
                self.p6(), self.p7(), self.p8(), self.a1(), self.a2(), self.a3(), self.a4(), self.a5(), self.back()]

    def cover(self) -> Page:
        return Page("cover", title=self.v["title_kr"] if self.kr else self.v["title_en"],
                    subtitle=self.v["subtitle_kr"] if self.kr else self.v["subtitle_en"],
                    extra={"kicker": "Research Note Vol.3", "author": self.cfg["research"]["author"], "date": self.v["date_label"],
                           "note": self.T("KSJ Research · 교육·연구 목적 · 투자 권유 아님 · Target Co.는 가상 기업",
                                          "KSJ Research · For education and research only · Not investment advice · Target Co. is hypothetical")})

    def back(self) -> Page:
        items = [
            self.T("이 자료는 교육·연구 목적의 개인 포트폴리오이며, 투자 권유나 특정 종목에 대한 매수·매도 의견이 아니다.",
                   "This is a personal portfolio for education and research. It is not investment advice or a recommendation on any security."),
            self.T("Target Co.는 가상 기업이며 실존 기업과 관련이 없다. 희망공모가 밴드는 방법을 보여주기 위한 계산 예시다.",
                   "Target Co. is hypothetical and unrelated to any real company; the price range illustrates a method."),
            self.T("본문의 판단은 저자 개인의 견해이며, 저자가 속했거나 속할 어떤 기관의 견해도 대변하지 않는다.",
                   "Views are the author's own and do not represent any current or future employer."),
            self.T("모든 데이터는 공개 자료이며 정확성과 완전성을 보장하지 않는다. 가정과 근거는 Appendix A2에 있다.",
                   "All data are public; accuracy and completeness are not guaranteed. Assumptions and sources are in Appendix A2."),
            self.T(f"기준일 {self.f.as_of}. 계산 방법과 코드는 저장소에서 재현할 수 있다.",
                   f"As of {self.f.as_of}. Methods and code can be reproduced from the repository."),
        ]
        from research.disclosures import contact_line, license_items
        items += license_items(self.cfg, self.kr)
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"],
                                                         "contact": contact_line(self.cfg)})

    # --- Executive Summary --------------------------------------------------
    def headline(self) -> str:
        if not self.ok_all:
            return self.T("PER 40배 섹터의 IPO: 데이터 확인 후 희망공모가 밴드 산출", "Pricing an IPO in a 40x P/E sector: range computed once data are in")
        f = self.f
        if ok(f.band_dp) and ok(f.mc_dp):
            bd, g = f.band_dp, self.v["discount_grid"]
            if self.f.dp_floor_alt:
                tail = self.T(f"이중 고점 위험은 이익률 하한 가정이 좌우(필요 할인율 중앙값 {self.floor_text(True)})",
                              f"the margin floor drives the double-peak risk ({self.floor_text(True)} median discount)")
            else:
                tail = (self.T("할인율만으로는 이중 고점을 못 덮는다", f"a {g[0] * 100:.0f}–{g[-1] * 100:.0f}% discount alone cannot cover the double peak")
                        if not self.dp_covered() else self.T(f"이중 고점까지 덮으려면 할인율 {self.bd_text(bd)}", f"covering the double peak takes {self.bd_text(bd)}"))
            return self.T(f"희망공모가 {self.band_text()} vs 이익률 정점 반영 {self.won_rng(bd.low, bd.high)} — {tail}",
                          f"Indicative range {self.band_text()} (current basis) vs {self.won_rng(bd.low, bd.high)} (with peak margins) — {tail}")
        return self.T(f"희망공모가 {self.band_text()} — 현재 PER {self.x(self.per())} 기준 평가가액에서 {self.disc_text()} 할인해야 사이클 고점 위험을 덮는다",
                      f"Indicative range {self.band_text()}: a {self.disc_text()} discount to the {self.x(self.per())} P/E value is what covers cycle-peak risk")

    def exec_conclusions(self) -> list[str]:
        return [self.headline()] + [b.title for b in self.boxes()]

    def boxes(self) -> list[BigBox]:
        return [self.box_multiple(), self.box_price(), self.box_cycle()]

    def executive(self) -> Page:
        f = self.f
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        if ok(f.mult):
            mu, g = f.mult, f.mult.groups["domestic"]["current"]
            add(self.T(f"적용 PER 현재 · 정상화 · 보수 ({self.applied_label()})", "Applied P/E current · normalised · conservative"),
                " · ".join(self.x(self.per(s)) for s in SCEN), "5", True)
            add(self.T(f"{self.dom_label()} 합산 PER (평균 · 중앙값)", f"{self.dom_label()} aggregate P/E (mean · median)"),
                f"{self.x(g.aggregate)} ({self.x(g.mean)} · {self.x(g.median)})", "4")
            core = mu.groups["core"]["current"]
            cn = list(self.f.peers.table[(self.f.peers.table["group"] == "core") & (self.f.peers.table["status"] == "applied")]["company"])
            add(self.T(f"해외 핵심 비교군 PER ({'·'.join(cn) or '시총 수집 후'})", f"U.S. core peers' P/E ({', '.join(cn) or 'after market data'})"),
                self.x(core.aggregate) if core.n else self.T("시총 수집 후", "after market data"), "4")
            evn = mu.groups["domestic"]["ev"].n
            add(self.T(f"EV/{self.f.peers.ev_basis} 참고: 국내 {evn}사 합산 · 적용", f"EV/{self.f.peers.ev_basis} ref.: {evn} Korean names · applied"),
                f"{self.x(mu.groups['domestic']['ev'].aggregate)} · {self.x(mu.ev_applied)}", "4")
        if ok(f.val):
            v = f.val
            add(self.T("Target Co. 지배순이익 FY2025A (가정)", "Target Co. NI to parent FY2025A (assumed)"), self.eok(v.ni), "2")
            add(self.T("적정 시총 (현재 배수)", "Fair equity value (current multiple)"), self.eok(v.equity["current"]), "6")
            add(self.T("주당 평가가액 (공모 후 주식수 기준)", "Value per share (post-IPO shares)"), self.won(v.per_share["current"]), "6", True)
        if ok(f.band):
            add(self.T(f"희망공모가 밴드 · 현재 기준 (할인율 {self.disc_text()})", f"Range · current basis (discount {self.disc_text()})"), self.band_text(), "6", True)
        if ok(f.band_dp):
            add(self.T(f"희망공모가 밴드 · 이중 고점 반영 (할인율 {self.bd_text(f.band_dp)})", f"Range · double peak (discount {self.bd_text(f.band_dp)})"),
                self.won_rng(f.band_dp.low, f.band_dp.high), "7", True)
        if ok(f.val) and f.val.nn:
            add(self.T("정상화 이익 × 정상화 배수 주당가치", "Value: normalised earnings × multiple"), self.won(f.val.nn["per_share"]), "5")
            add(self.T("공모금액 (밴드 하단~상단)", "Offer size (range low–top)"),
                self.rng(self.offer_amount(f.band.low), self.offer_amount(f.band.high), self.eok), "6")
        if ok(f.mc):
            q = f.mc.result.quantiles
            add(self.T("1년 후 주당가치 P10 · P50 · P90 (현재 기준)", "1-yr value P10 · P50 · P90 (current basis)"),
                " · ".join(f"{q[k]:,.0f}" for k in (0.1, 0.5, 0.9)), "7")
            if ok(f.mc_dp) and ok(f.band):
                g = self.v["discount_grid"][-1]
                add(self.T(f"할인율 {g * 100:.0f}%의 1년 후 손실 확률 (현재 기준 · 이중 고점)", f"1-yr loss probability at {g * 100:.0f}% (current · double peak)"),
                    f"{self.pct(f.mc.loss_grid[g], 0)} · {self.pct(f.mc_dp.loss_grid[g], 0)}", "7")
        table = TableSpec([self.T("핵심 지표", "Key metric"), self.T("값", "Value"), self.T("쪽", "p.")], rows,
                          [0.60, 0.31, 0.09], ["L", "R", "C"], shade_rows=shade, gold_cells=gold, font_size=8.4, single_line_cols={1})
        left = Cell(title=self.T("핵심 지표", "Key metrics"), src=["dart", "krx", "sec", "ipo", "fss", "ksj"], table=table,
                    note=self.T("KSJ Research 계산. Target Co.는 가상 기업이며 각 지표의 정의·근거는 해당 쪽 각주와 A2. 본문의 판단은 저자 개인의 견해",
                                "KSJ Research. Target Co. is hypothetical; definitions and sources in footnotes and A2. Judgements are the author's own"))
        sub = self.T("비교기업 3단계 선정 → 적용 배수(PER 주·EV 보조) → 평가가액 → 할인 → 밴드 → 몬테카를로: 배수 고점과 이익률 고점(이중 고점)을 함께 점검",
                     "Three-step peer selection → multiple (P/E main, EV secondary) → value → discount → range → Monte Carlo on both the peak multiple and the peak margin")
        return Page("exec", label="i", title=self.headline(), subtitle=sub, cells=[left], boxes=self.boxes())

    def box_multiple(self) -> BigBox:
        f = self.f
        if not ok(f.mult):
            return BigBox("—", self.T("적용 배수", "Applied multiple"), self.T("비교기업 배수: 데이터 확인 중", "Peer multiples: data pending"), [])
        mu, L = f.mult, f.links
        cur, nm, cs = (self.per(s) for s in SCEN)
        bl = [self.T(f"정상화 {self.x(nm)}: 2023년 초 {self.x(cs)}와 현재의 로그 중간(멀티플 확대분의 절반이 되돌려지는 경우)",
                     f"Normalised {self.x(nm)}: log midpoint of early-2023 {self.x(cs)} and today (half the re-rating reverses)")]
        if L.earn_share is not None:
            bl.append(self.T(f"Vol.1: 같은 3사 시총 증가의 {self.pct(L.earn_share, 0)}는 이익 — 배수 자체는 이익이 아닌 정점 신호",
                             f"Vol.1: {self.pct(L.earn_share, 0)} of the same names' gain was earnings — the multiple itself signals a peak"))
        hf = self.high_flag_rows()
        if not hf.empty:
            r = hf.iloc[0]
            bl.append(self.T(f"{r['company']} {self.x(r['per1'])}는 중앙값의 2배 초과 — 합산 가중이라 포함(평균이면 {self.x(mu.groups['domestic']['current'].mean)})",
                             f"{r['company_en']} at {self.x(r['per1'])} exceeds 2x the median — kept under aggregate weighting (mean would be {self.x(mu.groups['domestic']['current'].mean)})"))
        if mu.applied_group == "domestic":
            bl.append(self.T("해외 핵심 비교군은 시총 수집 후 평균에 편입", "U.S. core peers join the average once market data are in"))
        held = f.peers.table[f.peers.table["status"] == "held"]
        if not held.empty:
            bl.append(self.T(f"{', '.join(held['company'])}는 10-K 확인 전 보류 — 넣으면 해외 핵심 {self.x(self.core_with_held())}(지금 {self.x(mu.groups['core']['current'].aggregate)})",
                             f"{', '.join(held['company'])} held pending its 10-K — including it gives U.S. core {self.x(self.core_with_held())} (now {self.x(mu.groups['core']['current'].aggregate)})"))
        return BigBox(self.x(cur), self.T(f"적용 PER ({self.applied_label()}, 기준일)", f"Applied P/E ({self.applied_label()}, as of)"),
                      self.T(f"PER {self.x(cur)}는 이익이 만든 배수지만 정점의 배수 — 정상화 {self.x(nm)}, 보수 {self.x(cs)}",
                             f"{self.x(cur)} is an earnings-made multiple, but a peak one — normalised {self.x(nm)}, conservative {self.x(cs)}"), bl)

    def box_price(self) -> BigBox:
        f = self.f
        if not (ok(f.val) and ok(f.band)):
            return BigBox("—", self.T("주당 평가가액", "Value per share"), self.T("공모가: 입력 확인 중", "Price: inputs pending"), [])
        v, b, sh = f.val, f.band, f.val.shares
        bl = [self.T(f"지배순이익 {self.eok(v.ni)} × {self.x(self.per())} = 적정 시총 {self.eok(v.equity['current'])} ÷ 공모 후 {self.shares(sh.post)}",
                     f"NI {self.eok(v.ni)} × {self.x(self.per())} = equity {self.eok(v.equity['current'])} ÷ {self.shares(sh.post)} post-IPO"),
              self.T(f"공모 {self.shares(sh.offered)}(신주 {self.pct(sh.new / sh.offered, 0)}·구주 {self.pct(sh.old / sh.offered, 0)}) → 공모금액 {self.rng(self.offer_amount(b.low), self.offer_amount(b.high), self.eok)}",
                     f"Offer {self.shares(sh.offered)} ({self.pct(sh.new / sh.offered, 0)} primary, {self.pct(sh.old / sh.offered, 0)} secondary) → {self.rng(self.offer_amount(b.low), self.offer_amount(b.high), self.eok)}"),
              self.T(f"할인율 10~40% 시나리오: {self.won(v.grid['price'].iloc[-1])}~{self.won(v.grid['price'].iloc[0])}",
                     f"10–40% discount scenarios: {self.won(v.grid['price'].iloc[-1])}–{self.won(v.grid['price'].iloc[0])}")]
        if v.ev_per_share:
            bl.append(self.T(f"EV/{f.peers.ev_basis} 참고: 주당 {self.won(v.ev_per_share)}(PER 기준 대비 {self.pct(v.ev_per_share / v.per_share['current'] - 1, 0, True)}) — 국내 부분은 PER과 같은 구성, 차이는 해외 피어",
                             f"EV/{f.peers.ev_basis} reference: {self.won(v.ev_per_share)} per share ({self.pct(v.ev_per_share / v.per_share['current'] - 1, 0, True)} vs P/E) — the Korean part mirrors P/E; the gap is U.S. peers"))
        return BigBox(self.won(v.per_share["current"]),
                      self.T("주당 평가가액 (현재 배수, 공모 후 주식수)", "Value per share (current multiple, post-IPO shares)"),
                      self.T(f"평가가액 {self.won(v.per_share['current'])} → 희망공모가 {self.band_text()} ({self.band_basis()})",
                             f"Value {self.won(v.per_share['current'])} → indicative range {self.band_text()} ({self.band_basis()})"), bl)

    def box_cycle(self) -> BigBox:
        f = self.f
        if not ok(f.mc):
            return BigBox("—", self.T("필요 할인율", "Required discount"), self.T("몬테카를로: 입력 확인 중", "Monte Carlo: inputs pending"), [])
        mc, grid = f.mc, self.v["discount_grid"]
        if not (ok(f.mc_dp) and ok(f.band_dp)):
            req = mc.required
            return BigBox(f"{req[0.5] * 100:.0f}~{req[0.25] * 100:.0f}%" if self.kr else f"{req[0.5] * 100:.0f}–{req[0.25] * 100:.0f}%",
                          self.T("필요 할인율 (1년 후 가치 P50 · P25 기준)", "Required discount (1-yr value at P50 · P25)"),
                          self.T(f"사이클 고점 위험의 값: 할인율 {req[0.5] * 100:.0f}~{req[0.25] * 100:.0f}%", f"The price of cycle-peak risk: {req[0.5] * 100:.0f}–{req[0.25] * 100:.0f}%"), [])
        dp, bd = f.mc_dp, f.band_dp
        inb, top = self.market_facts()
        b0 = f.band
        bl = [self.T(f"현재 기준(순이익률 {self.pct(f.assumptions['npm'].value)} 고정) 필요 할인율 {self.pct(mc.required[0.5], 0)}~{self.pct(mc.required[0.25], 0)}"
                     + (f" — 밴드 {self.band_text()}의 할인율 {self.pct(b0.d_low, 0)}~{self.pct(b0.d_high, 0)}(IPO 실증값)보다 작다" if ok(b0) else ""),
                     f"Current basis (margin fixed at {self.pct(f.assumptions['npm'].value)}): {self.pct(mc.required[0.5], 0)}–{self.pct(mc.required[0.25], 0)}"
                     + (f" — below the {self.pct(b0.d_low, 0)}–{self.pct(b0.d_high, 0)} IPO-evidence discount behind the {self.band_text()} band" if ok(b0) else "")),
              self.T(f"순이익률을 FY2022A {self.pct(dp.npm_tri[0])}~FY2025A {self.pct(dp.npm_tri[2])} 분포로 두면 {self.pct(dp.required[0.5], 0)}~{self.pct(dp.required[0.25], 0)} → {self.won_rng(bd.low, bd.high)}",
                     f"Letting margin range FY2022A {self.pct(dp.npm_tri[0])}–FY2025A {self.pct(dp.npm_tri[2])}: {self.pct(dp.required[0.5], 0)}–{self.pct(dp.required[0.25], 0)} → {self.won_rng(bd.low, bd.high)}"),
              self.T(f"할인율 {grid[-1] * 100:.0f}%에서도 1년 후 손실 확률 {self.pct(dp.loss_grid[grid[-1]], 0)}(현재 기준 {self.pct(mc.loss_grid[grid[-1]], 0)})",
                     f"Even at {grid[-1] * 100:.0f}% the 1-yr loss probability is {self.pct(dp.loss_grid[grid[-1]], 0)} (current basis {self.pct(mc.loss_grid[grid[-1]], 0)})")]
        if top is not None:
            bl.append(self.T(f"2025년 하반기 IPO {self.pct(top, 0)}가 밴드 최상단 결정(금융감독원 발표, 머니투데이 보도) — 할인은 밴드 설계에서 끝난다",
                             f"{self.pct(top, 0)} of H2 2025 IPOs priced at the top (FSS release via Money Today) — the discount is set when the range is designed"))
        return BigBox(f"{dp.required[0.5] * 100:.0f}~{dp.required[0.25] * 100:.0f}%" if self.kr else f"{dp.required[0.5] * 100:.0f}–{dp.required[0.25] * 100:.0f}%",
                      self.T("이중 고점 반영 필요 할인율 (1년 후 가치 P50 · P25)", "Required discount with a double peak (1-yr value P50 · P25)"),
                      (self.T(f"이중 고점의 값: {self.floor_text()} — 이중 고점 위험은 이 가정이 좌우",
                              f"The price of a double peak: {self.floor_text()} — the double-peak risk hinges on this assumption")
                       if self.f.dp_floor_alt else
                       self.T(f"이중 고점의 값: 할인율 {dp.required[0.5] * 100:.0f}% 이상 — 10~40% 시나리오 밖, 할인율만으로는 덮이지 않는다",
                              f"The price of a double peak: {dp.required[0.5] * 100:.0f}%+ — outside the 10–40% grid; a discount alone does not cover it")
                       if not self.dp_covered() else
                       self.T(f"이중 고점의 값: 할인율 {dp.required[0.5] * 100:.0f}~{dp.required[0.25] * 100:.0f}% — 배수만 본 할인율보다 {(dp.required[0.5] - mc.required[0.5]) * 100:.0f}%p 더",
                              f"The price of a double peak: {dp.required[0.5] * 100:.0f}–{dp.required[0.25] * 100:.0f}% — {(dp.required[0.5] - mc.required[0.5]) * 100:.0f}pp more than multiple-only")), bl)

    # --- 목차 ---------------------------------------------------------------
    def toc_page(self) -> Page:
        heads = [self.p1(), self.p2(), self.p3(), self.p4(), self.p5(), self.p6(), self.p7(), self.p8()]
        names = [self.T("출발점", "Starting point"), self.T("Target Co.", "Target Co."), self.T("비교기업", "Peers"),
                 self.T("적용 배수", "Applied multiple"), self.T("배수 시나리오", "Multiple scenarios"), self.T("공모가", "Offer price"),
                 self.T("몬테카를로", "Monte Carlo"), self.T("시사점", "Implications")]
        toc = [(n, nm, toc_line(h.extra.get("toc") or h.title), h.label)
               for n, nm, h in zip(["I", "II", "III", "IV", "V", "VI", "VII", "VIII"], names, heads)]
        toc.append(("App.", "Appendix", self.T("A1 예상 질의응답 · A2 가정과 출처 · A3 데이터 노트 · A4 분석 방법 · A5 용어",
                                               "A1 Q&A · A2 Assumptions and sources · A3 Data notes · A4 Methodology · A5 Glossary"), "A1–A5"))
        return Page("toc", label="ii", title=self.T("목차", "Contents"),
                    subtitle=self.T("출발점 → 가정 → 비교기업 → 배수 → 시나리오 → 공모가 → 몬테카를로 → 시사점: 각 장의 결론",
                                    "Start → assumptions → peers → multiple → scenarios → price → Monte Carlo → implications: each section's conclusion"),
                    toc=toc)

    # --- p1 출발점 -----------------------------------------------------------
    def p1(self) -> Page:
        f, c, L = self.f, self.c, self.f.links
        cells = []
        if ok(f.peers) and L.per1 is not None:
            t = f.peers.table
            d = t[(t["group"] == "domestic") & (t["status"] == "applied")]
            cats = [self.cname(r) for _, r in d.iterrows()] + [self.T("3사 합산", "3-name aggregate")]
            s0 = list(d["per0"]) + [L.per0]
            s1 = list(d["per1"]) + [L.per1]
            cells.append(Cell(title=self.T(f"3사 합산 PER {self.x(L.per0)}(2023년 초) → {self.x(L.per1)}(기준일) — 시총 증가의 {self.pct(L.earn_share, 0)}는 이익",
                                           f"3-name aggregate P/E {self.x(L.per0)} (early 2023) → {self.x(L.per1)} (as of) — {self.pct(L.earn_share, 0)} of the gain was earnings"),
                              src=["krx", "dart", "vol1"], legend=[(c["warm_grey"], self.T(f"{f.peers.t0} ÷ FY2022A", f"{f.peers.t0} ÷ FY2022A")),
                                                                   (c["gold"], self.T(f"{f.peers.t1} ÷ FY2025A", f"{f.peers.t1} ÷ FY2025A"))],
                              unit=self.T("배 (시가총액 ÷ 지배순이익)", "x (market cap ÷ NI to parent)"), chart_key="per_hist",
                              chart=charts.grouped(cats, [("t0", s0, c["warm_grey"]), ("t1", s1, c["gold"])], c, lambda v: f"{v:.1f}", horizontal=True),
                              note=self.T("Vol.1 로그 분해: Δln(시총) = Δln(지배순이익) + Δln(PER). 두산에너빌리티는 FY2022A 지배순손실로 분해 제외",
                                          "Vol.1 log split: Δln(cap) = Δln(NI) + Δln(P/E). Doosan Enerbility excluded (FY2022A net loss)")))
        else:
            cells.append(self.pending(self.T("Vol.1 연결: 3사 합산 PER", "Vol.1 link: 3-name P/E"), ["krx", "dart"], self.T("KRX·DART 데이터 확인 후", "After KRX and DART data")))
        if L.pp_table:
            rows = [[r["company"] if self.kr else r["company_en"], self.pct(r["opm0"]), self.pct(r["opm1"]), self.pct(r["implied"])] for r in L.pp_table]
            rows.append([self.T("3사 합산", "3-name total"), self.pct(L.opm0), self.pct(L.opm1), self.pct(L.implied)])
            cells.append(Cell(title=self.T(f"Vol.2: 피어 영업이익률 {self.pct(L.opm0)} → {self.pct(L.opm1)} — 상승분이 모두 가격이면 전력기기 가격 {self.pct(L.implied, 1, True)}(상한), 개발자의 공사비",
                                           f"Vol.2: peer margin {self.pct(L.opm0)} → {self.pct(L.opm1)} — if all from price, equipment prices {self.pct(L.implied, 1, True)} (upper bound), the developer's cost"),
                              src=["dart", "vol2"], table=TableSpec([self.T("회사", "Company"), "OPM FY2022A", "OPM FY2025A", self.T("함의 가격 상승률", "Implied price rise")],
                                                                    rows, [0.34, 0.2, 0.2, 0.26], ["L", "R", "R", "R"], shade_rows={len(rows) - 1},
                                                                    gold_cells={(len(rows) - 1, 3)}, font_size=8.8),
                              note=self.T("함의 가격 상승률 = (1 − OPM 시작) ÷ (1 − OPM 끝) − 1: 단위 원가 불변 가정의 상한값(인과 아님). 그 이익이 지금 PER의 분모",
                                          "Implied rise = (1 − OPM start) ÷ (1 − OPM end) − 1: an upper bound with unit cost unchanged (not causal). That profit is today's P/E denominator")))
        else:
            cells.append(self.pending(self.T("Vol.2 연결: 피어 영업이익률", "Vol.2 link: peer margins"), ["dart"], self.T("DART 데이터 확인 후", "After DART data")))
        a = f.assumptions
        sh = f.val.shares if ok(f.val) else None
        prof = [self.T(f"가상 기업(실존 기업 아님): 국내 중견 {self.v['target_business_kr']} 기업", f"Hypothetical (not a real company): a Korean mid-size maker of {self.v['target_business_en']}"),
                self.T(f"FY2025A 매출 {self.eok(a['revenue'].value)}(설계값) — 성장률·이익률·순차입금은 국내 비교기업 DART에서", f"FY2025A revenue {self.eok(a['revenue'].value)} (design) — growth, margins and net debt from Korean peers' DART data")]
        if sh is not None:
            prof.append(self.T(f"상장 전 {self.shares(sh.pre)} · 공모 {self.pct(a['offer_ratio'].value, 0)}(신주 {self.pct(a['new_share_ratio'].value, 0)}) → 공모 후 {self.shares(sh.post)}",
                               f"{self.shares(sh.pre)} pre-IPO · offer {self.pct(a['offer_ratio'].value, 0)} of post-IPO shares ({self.pct(a['new_share_ratio'].value, 0)} primary) → {self.shares(sh.post)}"))
        prof.append(self.T(f"평가 기준일 {f.as_of} — 시총은 직전 거래일, 이익은 FY2025A(최근 사업연도)", f"As of {f.as_of} — caps at the prior trading day, earnings FY2025A (latest fiscal year)"))
        cells.append(Cell(title=self.T("Target Co.: 가상 비상장 전력기기 기업", "Target Co.: a hypothetical unlisted power-equipment maker"),
                          panel_lead=self.T("질문: 이익이 만든 PER 40배를 비상장사 공모가에 그대로 써도 되나?", "Question: can an earnings-made 40x P/E be applied to an unlisted company's IPO price?"),
                          bullets=prof, note=self.T("가정의 근거와 상태는 p2·A2", "Assumptions and their status on p2 and A2")))
        steps = [(self.T("1. 비교기업", "1. Peers"), [self.T("업종", "Industry"), self.T("재무 요건", "Financial tests"), self.T("사업 유사성", "Business fit"), self.T("국내 + 미국", "Korea + U.S.")]),
                 (self.T("2. 적용 배수", "2. Multiple"), [self.T("PER(주)", "P/E (main)"), self.T("EV 배수(보조)", "EV multiple (sec.)"), self.T("이상치 규칙", "Outlier rules"), self.T("시나리오 3개", "3 scenarios")]),
                 (self.T("3. 평가→밴드", "3. Value→range"), [self.T("적정 시총", "Equity value"), self.T("공모 후 주식수", "Post-IPO shares"), self.T("할인율 10~40%", "Discount 10–40%"), self.T("민감도", "Sensitivity")]),
                 (self.T("4. 사이클 위험", "4. Cycle risk"), [self.T("몬테카를로", "Monte Carlo"), self.T("1년 후 가치", "1-yr value"), "P10·P50·P90", self.T("필요 할인율", "Required discount")])]
        cells.append(Cell(title=self.T("국내 IPO 실무 구조: 평가가액 산정 → 할인 → 희망공모가 밴드", "Korean IPO practice: value → discount → indicative range"),
                          src=["ksj"], chart_key="flow", chart=charts.flow4(steps, self.c),
                          note=self.T("특정 증권신고서를 복제하지 않은 일반 구조. 공모가 확정(수요예측)은 범위 밖", "A generic structure, not a copy of any filing; final pricing (book-building) is out of scope")))
        if L.per1 is not None and L.opm1 is not None:
            title = self.T(f"출발점: PER {self.x(L.per0)} → {self.x(L.per1)}, 시총 증가의 {self.pct(L.earn_share, 0)}는 이익 — 그 이익의 상당 부분은 개발자의 비용일 수 있다",
                           f"Starting point: P/E {self.x(L.per0)} → {self.x(L.per1)}, {self.pct(L.earn_share, 0)} of the gain was earnings — much of it may have been developers' costs")
        else:
            title = self.T("출발점: Vol.1·Vol.2의 결론에서 IPO 공모가 질문으로", "Starting point: from Vol.1 and Vol.2 to the IPO pricing question")
        sub = self.T("Vol.1 이익 주도 재평가 + Vol.2 전력기기 가격 결정력 → 이 배수로 가상 비상장사의 희망공모가를 정하면?",
                     "Vol.1 earnings-led re-rating + Vol.2 equipment pricing power → what range for a hypothetical unlisted company at this multiple?")
        return Page("body", "1", title, sub, cells)

    # --- p2 Target Co. 가정 ---------------------------------------------------
    def p2(self) -> Page:
        f, a = self.f, self.f.assumptions
        keys = ["revenue", "revenue_growth", "opm", "npm", "net_debt_ratio", "da_ratio", "shares_pre", "offer_ratio", "new_share_ratio"]
        rows, gold, strong, brick, shade = [], set(), set(), set(), set()
        st = A_STATUS_KR if self.kr else A_STATUS_EN
        for i, k in enumerate(keys):
            x = a[k]
            rng_ = self.rng(x.low, x.high, lambda v: self.pct(v)) if x.low is not None and x.high is not None else "—"
            rows.append([self.lab(k), self.fmt_assump(x, short=True), rng_, st[x.status]])
            if x.status == "data":
                gold.add((i, 3))
            elif x.status == "input":
                brick.add((i, 3))
            elif x.status in ("judgment", "design"):
                strong.add((i, 3))
                shade.add(i)
        n_d = sum(a[k].status == "data" for k in keys)
        c1 = Cell(title=self.T(f"Target Co. 가정 {len(keys)}개 중 {n_d}개는 국내 비교기업 DART 데이터 — 범위는 3사 최소~최대",
                               f"{n_d} of {len(keys)} Target Co. inputs come from Korean peers' DART data — ranges are the min–max of 3 names"),
                  src=["dart", "law", "ksj"],
                  table=TableSpec([self.T("항목", "Item"), self.T("적용값", "Applied"), self.T("피어 범위", "Peer range"), self.T("상태", "Status")], rows,
                                  [0.36, 0.2, 0.26, 0.18], ["L", "R", "R", "C"], shade_rows=shade, gold_cells=gold, strong_cells=strong,
                                  brick_cells=brick, font_size=8.2),
                  note=self.T("적용값 = 3사 합산(성장률은 합산 매출 CAGR FY2022A→FY2025A). 상태: 데이터 = DART 계산, 설계값 = 가상 기업·거래 설정, 원문 확인 = 공개 규정, 원문 대조 전." + self.ni_fallback_note(),
                              "Applied = 3-name combined (growth = combined revenue CAGR FY2022A→FY2025A). Status: data = DART, design = hypothetical setting, verify = public rule pending check." + self.ni_fallback_note()))
        rr = [(self.lab(k), a[k].low, a[k].high, a[k].value) for k in ("revenue_growth", "opm", "npm", "net_debt_ratio")
              if a[k].value is not None and a[k].low is not None]
        if rr:
            c2 = Cell(title=self._range_title(rr), src=["dart"],
                      legend=[(self.c["warm_grey_light"], self.T("피어 최소~최대", "Peer min–max")), (self.c["gold"], self.T("적용값", "Applied"))],
                      unit="%", chart_key="ranges", chart=charts.ranges(rr, self.c, lambda v: f"{v * 100:.1f}", self.T("적용", "applied")),
                      note=self._nd_note())
        else:
            c2 = self.pending(self.T("가정 범위", "Assumption ranges"), ["dart"], self.T("DART 데이터 확인 후", "After DART data"))
        if ok(f.val):
            v = f.val
            g = a["revenue_growth"].value
            eps = v.ni * 1e8 / v.shares.pre
            prow = [[self.T("매출", "Revenue"), self.eok(v.rev), self.eok(v.rev26)],
                    [self.T("영업이익", "Operating income"), self.eok(v.oi), self.eok(v.oi * (1 + g)) if g is not None else "—"],
                    [self.T("지배순이익", "NI to parent"), self.eok(v.ni), self.eok(v.ni26)],
                    [f.peers.ev_basis, self.eok(v.ev_base), "—"],
                    [self.T("순차입금", "Net debt"), self.eok(v.net_debt), "—"],
                    [self.T("EPS (상장 전 주식수)", "EPS (pre-IPO shares)"), self.won(eps), self.won(eps * (1 + g)) if g is not None else "—"]]
            c3 = Cell(title=self.T(f"FY2025A 지배순이익 {self.eok(v.ni)} — 공모가의 분모(적용 이익)", f"FY2025A NI to parent {self.eok(v.ni)} — the earnings the price is built on"),
                      src=["dart", "ksj"], unit=self.T("억원, 원", "KRW 100mn → bn, KRW"),
                      table=TableSpec([self.T("항목", "Item"), "FY2025A", self.T("FY2026E (성장률 적용)", "FY2026E (growth applied)")], prow,
                                      [0.42, 0.29, 0.29], ["L", "R", "R"], shade_rows={2}, gold_cells={(2, 1)}, font_size=8.8),
                      note=self.T(f"FY2026E = FY2025A × (1 + {self.pct(g)}), 이익률 고정. 공모가는 최근 사업연도 이익(FY2025A)에 같은 기준의 피어 PER을 곱한다",
                                  f"FY2026E = FY2025A × (1 + {self.pct(g)}), margins fixed. The price applies peers' P/E on the same basis (FY2025A)"))
        else:
            c3 = self.pending(self.T("Target Co. 손익", "Target Co. P&L"), ["ksj"], self.missing_text(f.val))
        hist = f.der.hist if f.der else {}
        y0, y1 = (min(hist), max(hist)) if hist else (None, None)
        bl = [self.T("매출 규모·주식수는 주당 가격의 단위만 정한다: 시총 = 이익 × 배수, 할인율 결론은 규모와 무관",
                     "Revenue scale and share count only set the price unit: value = earnings × multiple; the discount conclusion does not depend on scale"),
              self.T(f"순이익률 1%p = 지배순이익 {self.eok(a['revenue'].value * 0.01)} = 적정 시총 {self.eok(a['revenue'].value * 0.01 * self.per())}(현재 배수)",
                     f"1pp of net margin = {self.eok(a['revenue'].value * 0.01)} NI = {self.eok(a['revenue'].value * 0.01 * self.per())} of value at the current multiple")
              if ok(f.mult) and a["revenue"].value else ""]
        if hist and y0 != y1:
            bl.append(self.T(f"이익률도 사이클: 3사 합산 순이익률 FY{y0}A {self.pct(hist[y0]['npm'])} → FY{y1}A {self.pct(hist[y1]['npm'])}, 영업이익률 {self.pct(hist[y0]['opm'])} → {self.pct(hist[y1]['opm'])}",
                             f"Margins are cyclical too: 3-name net margin FY{y0}A {self.pct(hist[y0]['npm'])} → FY{y1}A {self.pct(hist[y1]['npm'])}, operating {self.pct(hist[y0]['opm'])} → {self.pct(hist[y1]['opm'])}"))
            bl.append(self.T(f"FY{y0}A 이익률이면 같은 매출의 지배순이익은 지금의 {self.pct(hist[y0]['npm'] / hist[y1]['npm'], 0)} — 배수와 이익이 함께 정점일 위험",
                             f"At FY{y0}A margins, NI on the same revenue would be {self.pct(hist[y0]['npm'] / hist[y1]['npm'], 0)} of today's — multiple and earnings may both be at a peak"))
        c4 = Cell(title=self.T("가정이 결론을 움직이는 길: 규모는 무관, 이익률과 배수가 핵심", "How inputs move the result: scale is irrelevant; margins and multiples matter"),
                  bullets=[b for b in bl if b], note=self.T("이익률 사이클은 p7 이중 고점 몬테카를로(순이익률 확률변수)에서 반영하고, 한계(p8)·질의응답(A1)에서도 다룬다",
                                                            "The margin cycle enters the p7 double-peak Monte Carlo (random net margin); see also limitations (p8) and Q&A (A1)"))
        title = (self.T(f"Target Co. 가정은 국내 비교기업 DART 합산값 — 성장률 {self.pct(a['revenue_growth'].value)} · 영업이익률 {self.pct(a['opm'].value)} · 순이익률 {self.pct(a['npm'].value)}",
                        f"Target Co. inputs are Korean peers' DART aggregates — growth {self.pct(a['revenue_growth'].value)}, operating margin {self.pct(a['opm'].value)}, net margin {self.pct(a['npm'].value)}")
                 if a["npm"].value is not None else self.T("Target Co. 가정: 데이터 확인 중", "Target Co. inputs: data pending"))
        sub = self.T(f"매출 {self.eok(a['revenue'].value)}·상장 전 주식수 {self.shares(a['shares_pre'].value)}는 설계값(주당 가격 단위), 나머지는 피어 범위 안의 합산값 — 근거와 상태 공개",
                     f"Revenue {self.eok(a['revenue'].value)} and {self.shares(a['shares_pre'].value)} pre-IPO are design values (price unit); the rest are peer aggregates within the peer range")
        return Page("body", "2", title, sub, [c1, c2, c3, c4])

    def _nd_note(self) -> str:
        d = self.f.der.detail if self.f.der else None
        nm = {str(p["ticker"]).zfill(6): (p["name"], p.get("name_en", p["name"])) for p in self.cfg["peers"]["domestic"]}
        miss = [nm[t] for t in d[d["nd1"].isna()]["ticker"]] if d is not None and not d.empty else []
        t = self.f.peers.table if ok(self.f.peers) else None
        px = [nm[k] for k in t[(t["region"] == "KR") & (t["status"] == "applied") & t["debt_proxy"].fillna(False).astype(bool)]["ticker"]] if t is not None and "debt_proxy" in t else []
        parts_kr, parts_en = ["범위 = 국내 비교기업 FY2025A 최소~최대"], ["Range = Korean peers' FY2025A min–max"]
        if px:
            parts_kr.append(f"{', '.join(m[0] for m in px)} 총차입금 = 기타금융부채(유동·비유동) 대용치, 주석 확인 전")
            parts_en.append(f"{', '.join(m[1] for m in px)}: debt = other financial liabilities (current + non-current), a proxy pending the notes")
        if miss:
            parts_kr.append(f"{', '.join(m[0] for m in miss)} 총차입금 미수집")
            parts_en.append(f"{', '.join(m[1] for m in miss)}: debt not collected")
        return self.T(". ".join(parts_kr), ". ".join(parts_en))

    def _range_title(self, rr) -> str:
        t = self.f.der.detail if self.f.der else None
        if t is None or t.empty:
            return self.T("적용값(◆)과 피어 범위", "Applied values (◆) and peer ranges")
        hi = t.sort_values("opm", ascending=False).iloc[0]
        lo = t.sort_values("opm").iloc[0]
        nm = {str(p["ticker"]).zfill(6): (p["name"], p.get("name_en", p["name"])) for p in self.cfg["peers"]["domestic"]}
        return self.T(f"적용값(◆)은 피어 범위 안 — 영업이익률 위 끝 {nm[hi['ticker']][0]} {self.pct(hi['opm'])}, 아래 끝 {nm[lo['ticker']][0]} {self.pct(lo['opm'])}",
                      f"Applied values (◆) sit inside the peer range — margins from {nm[lo['ticker']][1]} {self.pct(lo['opm'])} to {nm[hi['ticker']][1]} {self.pct(hi['opm'])}")

    def fmt_assump(self, a: Assumption, short: bool = False) -> str:
        v = a.value
        if v is None:
            return "—"
        if isinstance(v, str):
            return {"triangular": self.T("삼각분포", "Triangular")}.get(v, v)
        if a.unit == "%":
            return self.pct(v, 2 if abs(v) < 0.1 and a.key in ("growth_sd",) else 1)
        if a.unit == "주":
            return f"{v:,.0f}"
        if a.unit == "억원":
            return f"{v:,.0f}"
        return f"{v:,.4g}"

    # --- p3 비교기업 선정 ---------------------------------------------------
    def hold_reasons(self, r) -> list[str]:
        """R6 보류 근거 (데이터에서 계산): 순이익 ÷ 영업이익, 장기차입금 태그, EV 배수."""
        ho = (self.v["multiples"].get("hold_out") or {}).get(r["ticker"], {})
        out = []
        if np.isfinite(r["ni_to_oi"]) and r["ni_to_oi"] > float(ho.get("ni_to_oi_max", 1.5)):
            out.append(self.T(f"FY2025A 순이익 {self.money(r, r['ni1'])} = 영업이익 {self.money(r, r['oi1'])}의 {r['ni_to_oi']:.1f}배(일회성 이익 가능성)",
                              f"FY2025A NI {self.money(r, r['ni1'])} = {r['ni_to_oi']:.1f}x operating income {self.money(r, r['oi1'])} (possible one-offs)"))
        if str(r.get("lt_debt_tag")) == "False":
            out.append(self.T(f"장기차입금 태그 미보고 → 순차입금 {self.money(r, r['net_debt1'])}(순현금 과대 가능)",
                              f"No long-term-debt tag → net debt {self.money(r, r['net_debt1'])} (net cash may be overstated)"))
        if np.isfinite(r["evm1"]) and r["evm1"] > float(self.v["multiples"]["outlier"]["ev_ebitda_max"]):
            out.append(self.T(f"EV/{self.f.peers.ev_basis} {self.x(r['evm1'], 0)}", f"EV/{self.f.peers.ev_basis} {self.x(r['evm1'], 0)}"))
        return out

    def step2_text(self, r) -> str:
        pm = self.v["multiples"]["outlier"]["per_max"]
        s = r["step2"]
        if s == "R6":
            return self.T(f"보류: 순이익/영업이익 {r['ni_to_oi']:.1f}배 · EV/{self.f.peers.ev_basis} {self.x(r['evm1'], 0)}",
                          f"Held: NI/OI {r['ni_to_oi']:.1f}x · EV/{self.f.peers.ev_basis} {self.x(r['evm1'], 0)}")
        if s == "pass":
            return self.T(f"흑자 · PER {self.x(r['per1'])}", f"Profitable · P/E {self.x(r['per1'])}")
        if s == "R2":
            return self.T(f"PER {self.x(r['per1'], 0)} > {pm}배", f"P/E {self.x(r['per1'], 0)} > {pm}x")
        if s == "R1":
            return self.T("최근 사업연도 적자", "Loss in the latest year")
        if s == "R3":
            return self.T("재무 주체 불일치", "Filer ≠ listed entity")
        if s == "no_fin":
            return self.T("SEC 비대상 · 재무 수기 입력 전", "Not an SEC filer")
        return self.T("흑자 · 시총 수집 전", "Profitable · cap pending")

    def step3_text(self, r) -> str:
        b = (r["business_kr"] if self.kr else (r["business_en"] or r["segment"])).split(" — ")[0]
        if r["group"] == "reference":
            return self.T(f"{b} (발전·유틸리티)", f"{b} (generation)")
        if r["group"] == "excluded":
            return b
        sim = (SIM_KR if self.kr else SIM_EN)[r["similarity"]]
        return self.T(f"{b} (유사성 {sim})", f"{b} ({sim})")

    def p3(self) -> Page:
        f = self.f
        if not ok(f.peers):
            cells = [self.pending(t, ["dart", "krx", "sec"], self.missing_text(f.peers)) for t in (
                self.T("3단계 선정", "Three-step selection"), self.T("핵심·참고 비교군", "Core vs reference"),
                self.T("시총 교차 확인", "Market-cap cross-check"), self.T("제외 사유", "Exclusions"))]
            return Page("body", "3", self.T("비교기업: 데이터 확인 중", "Peers: data pending"), "", cells)
        t = f.peers.table
        stl = STATUS_KR if self.kr else STATUS_EN
        rows, gold, brick, shade = [], set(), set(), set()
        for i, (_, r) in enumerate(t.iterrows()):
            ind_en = "Generation equip." if r["similarity"] == "low" and r["region"] == "KR" else {"generation": "Power generation"}.get(r["kind"], "Power equipment")
            rows.append([self.cname(r), r["segment"] if self.kr else ind_en,
                         self.step2_text(r), self.step3_text(r), stl[r["status"]]])
            if r["status"] == "applied":
                gold.add((i, 4))
                shade.add(i)
            elif r["status"] in ("excluded", "held"):
                brick.add((i, 4))
        n_app = int((t["status"] == "applied").sum())
        n_pen = int(((t["status"] == "pending") & (t["group"] == "core")).sum())
        n_dom = int(((t["status"] == "applied") & (t["group"] == "domestic")).sum())
        n_core = int(((t["status"] == "applied") & (t["group"] == "core")).sum())
        held = t[t["status"] == "held"]
        c1 = Cell(title=self.T(f"후보 {len(t)}개 → 적용 {n_app}개" + (f" + 해외 핵심 {n_pen}개(시총 수집 후)" if n_pen else "") + (f" · 보류 {len(held)}개" if len(held) else "") + " — 업종 → 재무 요건 → 사업 유사성",
                               f"{len(t)} candidates → {n_app} applied" + (f" + {n_pen} U.S. core (after market data)" if n_pen else "") + (f" · {len(held)} held" if len(held) else "") + " — industry → financial tests → business fit"),
                  src=["dart", "krx", "sec"],
                  table=TableSpec([self.T("회사", "Company"), self.T("1단계 업종", "1. Industry"), self.T("2단계 재무 요건", "2. Financial tests"),
                                   self.T("3단계 사업 유사성", "3. Business fit"), self.T("결과", "Result")], rows,
                                  [0.2, 0.17, 0.2, 0.29, 0.14], ["L", "L", "L", "L", "C"], shade_rows=shade, gold_cells=gold, brick_cells=brick, font_size=7.8),
                  note=self.T(f"재무 요건: 공시 재무 확보 · 최근 사업연도(FY2025A) 흑자 · PER ≤ {self.v['multiples']['outlier']['per_max']}배 · 시총 주체 = 재무 주체(SEC). 사업 설명은 사업보고서·10-K 사업부 구성의 저자 요약",
                              f"Financial tests: filed financials, FY2025A profit, P/E ≤ {self.v['multiples']['outlier']['per_max']}x, listed entity = filer (SEC). Business notes summarise annual-report segments (author)"))
        # 핵심 vs 참고: SEC FY2025A 지표
        us = t[t["group"].isin(["core", "reference"]) & t["has_fin"]]
        crow = []
        agg = {}
        for _, r in us.iterrows():
            fin = f.ovs.fin[f.ovs.fin["ticker"] == r["ticker"]].set_index("fy")
            fy_a, fy_b = int(fin.index.min()), int(fin.index.max())
            cg = (fin.loc[fy_b, "revenue"] / fin.loc[fy_a, "revenue"]) ** (1 / (fy_b - fy_a)) - 1 if fy_b > fy_a else float("nan")
            opm = r["oi1"] / r["rev1"] if np.isfinite(r["oi1"]) else float("nan")
            crow.append([self.cname(r), (self.T("핵심 · 보류", "Core · held") if r["status"] == "held" else self.T("핵심 · 전력기기 제조", "Core · equipment"))
                         if r["group"] == "core" else self.T("참고 · 발전·유틸리티", "Ref. · generation"),
                         self.pct(cg), self.pct(opm), self.pct(r["ni1"] / r["rev1"]), self.pct(r["net_debt1"] / r["rev1"], 0)])
            if r["status"] != "held":                      # 보류 회사는 그룹 비교 합계에서 제외 (표에는 표시)
                k = agg.setdefault(r["kind"], [0.0, 0.0])
                k[0] += r["net_debt1"]
                k[1] += r["rev1"]
        nd_eq = agg.get("equipment", [float("nan"), 1])[0] / agg.get("equipment", [0, float("nan")])[1] if "equipment" in agg else float("nan")
        nd_gen = agg.get("generation", [float("nan"), 1])[0] / agg.get("generation", [0, float("nan")])[1] if "generation" in agg else float("nan")
        if crow:
            fy_a = int(f.ovs.fin["fy"].min())
            c2 = Cell(title=self.T(f"전력기기 제조와 발전·유틸리티는 다른 사업 — 순차입금 ÷ 매출 {self.pct(nd_eq, 0)} vs {self.pct(nd_gen, 0)}",
                                   f"Equipment makers and generators are different businesses — net debt ÷ revenue {self.pct(nd_eq, 0)} vs {self.pct(nd_gen, 0)}"),
                      src=["sec"],
                      table=TableSpec([self.T("회사", "Company"), self.T("구분", "Group"), self.T(f"매출 CAGR {fy_a % 100}→25", f"Rev. CAGR {fy_a % 100}→25"),
                                       "OPM", self.T("순이익률", "Net margin"), self.T("순차입금÷매출", "Net debt ÷ rev.")], crow,
                                      [0.2, 0.24, 0.17, 0.12, 0.13, 0.14], ["L", "L", "R", "R", "R", "R"],
                                      shade_rows={i for i, r in enumerate(crow) if i < sum(us["group"] == "core")}, font_size=8.0),
                      note=self.T(f"SEC 10-K FY2025A(USD), 매출 CAGR = FY{int(f.ovs.fin['fy'].min())}A→FY2025A. 전력기기 제조 = 수주·생산, 이익은 가격 결정력에 좌우 / 발전·유틸리티 = 전력 판매·PPA, 자산·차입이 커서 PER·EV 구조가 다르다 → 참고 비교군. Eaton 영업이익 태그 미보고(—)" + (". 순차입금 합계는 보류 회사 제외" if (us["status"] == "held").any() else ""),
                                  f"SEC 10-K FY2025A (USD); revenue CAGR FY{int(f.ovs.fin['fy'].min())}A→FY2025A. Equipment = orders and production, margins from pricing power / generation = power sales and PPAs with heavy assets and debt, so P/E and EV behave differently → reference only. Eaton reports no operating-income tag (—)" + ("; group net-debt totals exclude held names" if (us["status"] == "held").any() else "")))
        else:
            c2 = self.pending(self.T("핵심·참고 비교군", "Core vs reference"), ["sec"], self.T("SEC 재무 확인 후", "After SEC data"))
        mk = t[t["region"] == "US"]
        if ok(f.ovs) and mk["mcap1"].notna().any():
            fx = f.fx
            mrow = []
            for _, r in mk.iterrows():
                m = f.ovs.market[(f.ovs.market["ticker"] == r["ticker"]) & (f.ovs.market["point"] == "latest")]
                sec_sh = f.ovs.shares[f.ovs.shares["ticker"] == r["ticker"]]
                mrow.append([self.cname(r), f"{m.iloc[0]['close']:,.2f}" if not m.empty else "—",
                             f"{sec_sh.iloc[0]['shares'] / 1e6:,.1f}" if not sec_sh.empty else "—",
                             f"{m.iloc[0]['shares_yf'] / 1e6:,.1f}" if not m.empty and np.isfinite(m.iloc[0]["shares_yf"]) else "—",
                             self.pct(r["shares_check"], 1, True), self.usd(r["mcap1"]),
                             self.eok(r["mcap1"] * fx / 100) if fx and np.isfinite(r["mcap1"]) else "—"])
            tol = self.cfg["data_fetch"]["global_market"]["crosscheck_tolerance_pct"]
            bad = mk[mk["shares_check"].abs() > tol / 100]
            c3 = Cell(title=self.T(f"시총 = 종가 × SEC 발행주식수 — yfinance 주식수와 차이 ±{tol}% 밖 {len(bad)}개",
                                   f"Market cap = close × SEC shares — {len(bad)} outside ±{tol}% of yfinance shares"),
                      src=["yf", "sec", "ecos"],
                      table=TableSpec([self.T("회사", "Company"), self.T("종가 USD", "Close USD"), self.T("SEC 주식(mn)", "SEC shares (mn)"),
                                       self.T("yfinance(mn)", "yfinance (mn)"), self.T("차이", "Diff."), self.T("시총", "Market cap"), self.T("원화 환산", "In KRW")],
                                      mrow, [0.18, 0.12, 0.13, 0.13, 0.1, 0.17, 0.17], ["L"] + ["R"] * 6, font_size=7.8),
                      note=self.T(f"yfinance는 보조 소스 — 주식수는 SEC 표지 값을 쓰고 차이만 확인. 원화 환산 = USD mn × {fx:,.1f} ÷ 100 (ECOS {f.fx_date})" if fx else "yfinance는 보조 소스",
                                  f"yfinance is secondary — SEC cover shares are used; the difference is checked only. KRW = USD mn × {fx:,.1f} ÷ 100 (ECOS {f.fx_date})" if fx else "yfinance is secondary"))
        else:
            c3 = self.pending(self.T("미국 피어 시총 교차 확인 (yfinance 종가 × SEC 주식수)", "U.S. market caps (yfinance close × SEC shares)"), ["yf", "sec"], self.us_pending_reason(),
                              note=self.T("SEC 재무·발행주식수·재무 주체 검사는 완료(A3). 시총이 들어오면 PER·EV 배수와 2023년 초 배수를 같은 규칙으로 계산",
                                          "SEC financials, shares and the entity check are done (A3); once caps arrive, P/E, EV and early-2023 multiples follow the same rules"))
        ex = []
        for _, r in t[t["status"] == "excluded"].iterrows():
            if r["region"] == "KR":
                ex.append(self.T(f"{r['company']}: PER {self.x(r['per1'], 0)}(FY2025A 지배순이익 {self.eok(r['ni1'])}의 분모 왜곡) + 발전설비 중심으로 사업 유사성 낮음. Vol.1 분해에서도 FY2022A 순손실로 제외",
                                 f"{r['company_en']}: P/E {self.x(r['per1'], 0)} (denominator distortion from FY2025A NI of {self.eok(r['ni1'])}) and low fit (generation equipment). Also excluded from Vol.1's split (FY2022A loss)"))
            else:
                ex.append(self.T(f"{r['company']}: {r['reason_kr']}", f"{r['company']}: {r['reason_en']}"))
        for _, r in held.iterrows():
            ex.append(self.T(f"{r['company']}: 10-K 확인 전 PER·EV 배수에서 제외(표에는 유지) — " + " · ".join(self.hold_reasons(r)),
                             f"{r['company']}: excluded from P/E and EV multiples pending the 10-K (kept in tables) — " + "; ".join(self.hold_reasons(r))))
        e = [x for x in f.entity if str(x.get("manual_check", ""))]
        for x in e:
            ex.append(self.T(f"{x['company']}: 재무 주체 자동 판정 {x.get('auto_verdict', '')} → 10-K 표지 registrant 수동 확인으로 {x['verdict']} (확인일 {x.get('verified_on', '')})",
                             f"{x['company']}: automatic entity check {x.get('auto_verdict', '')} → {x['verdict']} after checking the 10-K cover registrant ({x.get('verified_on', '')})"))
        core_nolist = t[(t["group"] == "core") & (t["status"] == "applied") & t["mcap1"].notna() & t["mcap0"].isna()]
        if not core_nolist.empty:
            ex.append(self.T(f"{', '.join(core_nolist['company'])}: 2023년 첫 거래일 시총 없음 → 보수 시나리오 배수에서 제외",
                             f"{', '.join(core_nolist['company'])}: no market cap on the first 2023 trading day → excluded from the conservative multiple"))
        c4 = Cell(title=self.T("제외·확인 사유: 배수 왜곡 · 공시 범위 · 재무 주체", "Exclusions and checks: distorted multiple, disclosure scope, filer identity"),
                  bullets=ex, note=self.T("이상치 규칙은 p4 표", "Outlier rules in the p4 table"))
        dx = self.excluded_dom()
        dtext = (self.T(f"{dx.iloc[0]['company']}는 PER {self.x(dx.iloc[0]['per1'], 0)}로", f"{dx.iloc[0]['company_en']} at {self.x(dx.iloc[0]['per1'], 0)} P/E") if not dx.empty else "")
        hname = ", ".join(held["company"])
        htxt = self.T(f", {hname}는 10-K 확인 전 보류", f"; {hname} held pending the 10-K") if hname else ""
        nc = n_core or n_pen
        title = self.T(f"비교기업: 국내 {n_dom}사 + 해외 핵심 {nc}사(전력기기 제조), 발전·유틸리티 2사는 참고 — {dtext} Schneider Electric은 SEC 비대상으로 제외{htxt}",
                       f"Peers: {n_dom} Korean + {nc} U.S. core equipment makers; 2 generators as reference — {dtext} and Schneider Electric (not an SEC filer) excluded{htxt}")
        sub = self.T("증권신고서 방식 3단계: 업종(전력 인프라) → 재무 요건(흑자·배수·재무 주체) → 사업 유사성(배전·UPS·데이터센터 전력)",
                     "Prospectus-style three steps: industry (power infrastructure) → financial tests (profit, multiple, filer) → business fit (distribution, UPS, data-centre power)")
        return Page("body", "3", title, sub, [c1, c2, c3, c4],
                    extra={"toc": self.T(f"국내 {n_dom}사 + 해외 핵심 {nc}사, 발전·유틸리티 2사는 참고 — 두산에너빌리티·Schneider 제외" + (f", {hname} 보류" if hname else ""),
                                         f"{n_dom} Korean + {nc} U.S. core peers, 2 generators as reference — Doosan and Schneider excluded" + (f", {hname} held" if hname else ""))})

    # --- p4 적용 배수 -------------------------------------------------------
    def p4(self) -> Page:
        f, c = self.f, self.c
        if not ok(f.mult):
            cells = [self.pending(t, ["dart", "krx"], self.missing_text(f.mult)) for t in (
                self.T("회사별 PER", "P/E by company"), self.T("그룹 배수", "Group multiples"), self.T("이상치 규칙", "Outlier rules"), "EV")]
            return Page("body", "4", self.T("적용 배수: 데이터 확인 중", "Applied multiple: data pending"), "", cells)
        mu, t = f.mult, f.peers.table
        show = t[t["status"].isin(["applied", "reference"]) & t["per1"].notna() & t["s1"].map(lambda s: s.included)]
        col = {"domestic": c["gold"], "core": c["brown_dark"], "reference": c["warm_grey"]}
        labs = [self.cname(r) + (" *" if r["high_flag"] else "") for _, r in show.iterrows()]
        vals = list(show["per1"])
        cols = [col[g] for g in show["group"]]
        dom = mu.groups["domestic"]["current"]
        hf = self.high_flag_rows()
        hf_txt = (self.T(f" — {hf.iloc[0]['company']} {self.x(hf.iloc[0]['per1'])}는 중앙값의 2배 초과(*, 포함)", f" — {hf.iloc[0]['company_en']} {self.x(hf.iloc[0]['per1'])} exceeds 2x the median (*, kept)")
                  if not hf.empty else "")
        legend = [(c["gold"], self.T("국내", "Korea"))] + ([(c["brown_dark"], self.T("해외 핵심", "U.S. core"))] if (show["group"] == "core").any() else []) \
            + ([(c["warm_grey"], self.T("해외 참고", "U.S. reference"))] if (show["group"] == "reference").any() else [])
        dv = list(show[show["group"] == "domestic"]["per1"])
        cv = list(show[show["group"] == "core"]["per1"])
        rng_t = self.T(f"국내 {self.x(min(dv))}~{self.x(max(dv))}", f"Korea {self.x(min(dv))}–{self.x(max(dv))}") if dv else ""
        if cv:
            rng_t += self.T(f" · 해외 핵심 {self.x(min(cv))}~{self.x(max(cv))}", f" · U.S. core {self.x(min(cv))}–{self.x(max(cv))}")
        c1 = Cell(title=self.T(f"현재 PER: {rng_t}{hf_txt}", f"Current P/E: {rng_t}{hf_txt}") if vals else self.T("현재 PER", "Current P/E"),
                  src=["krx", "dart", "sec"], legend=legend, unit=self.T("배 (기준일 시총 ÷ FY2025A 지배순이익)", "x (as-of cap ÷ FY2025A NI)"),
                  chart_key="per_now", chart=charts.hbars(labs, vals, cols, c, lambda v: f"{v:.1f}"),
                  note=self.T(f"국내 = KRX {f.peers.t1} 시가총액 ÷ DART FY2025A 지배순이익. 제외 회사는 표시하지 않음(p3)" + ("" if (show['group'] == 'core').any() else ". 미국 피어는 시총 수집 후 추가"),
                              f"Korea = KRX {f.peers.t1} cap ÷ DART FY2025A NI to parent. Excluded names not shown (p3)" + ("" if (show['group'] == 'core').any() else "; U.S. peers added once caps are in")))
        grows = []
        names = {"domestic": self.dom_label(), "core": self.T("해외 핵심 (전력기기)", "U.S. core (equipment)"), "reference": self.T("해외 참고 (발전·유틸리티)", "U.S. reference (generation)")}
        for g in ("domestic", "core", "reference"):
            gm = mu.groups[g]["current"]
            grows.append([names[g], str(gm.n), self.x(gm.aggregate), self.x(gm.mean), self.x(gm.median),
                          self.x(mu.scen[g]["current"]) if g != "reference" else self.T("비교만", "compare only")])
        grows.append([self.T("적용", "Applied") + f" ({self.applied_label()})", "", "", "", "", self.x(self.per())])
        c2 = Cell(title=self.T(f"적용 PER {self.x(self.per())} — 그룹 안은 합산(이익 가중), 국내·해외는 그룹 평균", f"Applied P/E {self.x(self.per())} — aggregate within groups, average across groups"),
                  src=["krx", "dart", "sec"],
                  table=TableSpec([self.T("그룹", "Group"), "n", self.T("합산", "Aggregate"), self.T("평균", "Mean"), self.T("중앙값", "Median"), self.T("적용", "Applied")],
                                  grows, [0.36, 0.06, 0.14, 0.14, 0.14, 0.16], ["L", "C", "R", "R", "R", "R"], shade_rows={len(grows) - 1},
                                  gold_cells={(len(grows) - 1, 5)}, font_size=8.4),
                  note=self.T("합산 = Σ시총 ÷ Σ지배순이익. 3~5개 피어의 산술평균은 한 회사에 좌우되어 합산을 주 지표로, 평균·중앙값은 병기. 국내·해외는 시총 규모가 달라 그룹 배수의 단순평균",
                              "Aggregate = Σcap ÷ ΣNI. With 3–5 peers a simple mean is driven by one name, so the aggregate leads, mean and median shown. Korea and U.S. are averaged as groups (very different sizes)"))
        out = self.v["multiples"]["outlier"]
        rule_hits = {}
        for _, r in t.iterrows():
            for s in (r["s1"],):
                if s.rule:
                    rule_hits.setdefault(s.rule, []).append(self.cname(r))
            if r["sev"].rule == "R5":
                rule_hits.setdefault("R5", []).append(self.cname(r))
        rule_hits["R6"] = list(dict.fromkeys(rule_hits.get("R6", [])))
        if not hf.empty:
            rule_hits["R4"] = [self.cname(r) for _, r in hf.iterrows()]
        evn = t[t["sev"].map(lambda s: s.rule == "no_ev") & t["group"].isin(["domestic", "core"]) & t["has_fin"] & t["mcap1"].notna()]
        rrows = [["R1", self.T("최근 사업연도 지배순이익 ≤ 0", "NI to parent ≤ 0"), self.T("PER 제외", "Drop P/E"), ", ".join(rule_hits.get("R1", [])) or "—"],
                 ["R2", self.T(f"PER > {out['per_max']}배", f"P/E > {out['per_max']}x"), self.T("제외 (분모 왜곡)", "Drop (denominator distortion)"), ", ".join(rule_hits.get("R2", [])) or "—"],
                 ["R3", self.T("시총 주체 ≠ 재무 주체 (SEC)", "Listed entity ≠ filer (SEC)"), self.T("제외", "Drop"), ", ".join(rule_hits.get("R3", [])) or "—"],
                 ["R4", self.T(f"그룹 중앙값의 {out['flag_vs_median']:.0f}배 초과", f"> {out['flag_vs_median']:.0f}x group median"), self.T("표시·포함 (합산 가중)", "Flag, keep (aggregate)"), ", ".join(rule_hits.get("R4", [])) or "—"],
                 ["R5", self.T(f"EBITDA ≤ 0 또는 EV 배수 > {out['ev_ebitda_max']}배 · 순차입금 미수집", f"EBITDA ≤ 0, EV multiple > {out['ev_ebitda_max']}x, or no net debt"),
                  self.T("EV 배수 제외", "Drop EV multiple"), ", ".join(rule_hits.get("R5", []) + [self.cname(r) for _, r in evn.iterrows()]) or "—"],
                 ["R6", self.T("이익의 질·차입금 태그 의심 (순이익 > 영업이익 1.5배 등)", "Earnings quality / debt-tag doubts (NI > 1.5x OI etc.)"),
                  self.T("10-K 확인 전 PER·EV 제외 (표에는 유지)", "Drop P/E and EV pending the 10-K (kept in tables)"), ", ".join(rule_hits.get("R6", [])) or "—"]]
        c3 = Cell(title=self.T("이상치 규칙: 적자·극단 배수는 빼고, 고배수는 표시 후 남긴다", "Outlier rules: drop losses and extreme multiples; flag, but keep, high ones"),
                  src=["ksj"], table=TableSpec([self.T("규칙", "Rule"), self.T("기준", "Test"), self.T("처리", "Treatment"), self.T("해당", "Hit")], rrows,
                                               [0.08, 0.36, 0.26, 0.30], ["C", "L", "L", "L"], shade_rows={3, 5}, font_size=8.0),
                  note=self.T("규칙은 배수를 보기 전에 정한 저자 판단 — 보수 시나리오(2023년 초)에도 같은 규칙", "Rules set before looking at the multiples (author's judgment); the same rules apply to the early-2023 point"))
        ev_g = mu.groups["domestic"]["ev"]
        basis = f.peers.ev_basis
        erows = []
        for _, r in t[t["group"].isin(["domestic", "core"]) & t["has_fin"] & t["status"].isin(["applied", "pending", "held"])].iterrows():
            s = r["sev"]
            pmark = self.T(" (대용)", " (proxy)") if bool(r.get("debt_proxy")) is True else ""
            erows.append([self.cname(r) + pmark, self.money(r, r["ev1"]) if np.isfinite(r["ev1"]) else "—", self.money(r, r["ebitda1"]),
                          self.x(r["evm1"]) if np.isfinite(r["evm1"]) else "—",
                          self.T("포함", "Kept") if s.included else {"no_ev": self.T("순차입금·시총 없음", "No net debt / cap"), "R5": "R5", "R6": self.T("R6 보류", "R6 held")}.get(s.rule, self.T(f"{basis} 미보고", f"No {basis}"))])
        basis = f.peers.ev_basis
        v = f.val if ok(f.val) else None
        diff = (v.ev_per_share / v.per_share["current"] - 1) if v is not None and v.ev_per_share else None
        c4 = Cell(title=(self.T(f"EV/{basis} {self.x(mu.ev_applied)}(참고) — Target에 적용하면 PER 기준보다 {self.pct(diff, 0, True)}, 단 독립 근거는 아니다",
                                f"EV/{basis} {self.x(mu.ev_applied)} (reference) — applied to Target, {self.pct(diff, 0, True)} vs P/E, but not an independent check")
                         if diff is not None else self.T(f"EV/{basis} {self.x(mu.ev_applied)} (참고)", f"EV/{basis} {self.x(mu.ev_applied)} (reference)")),
                  src=["dart", "krx", "sec"],
                  table=TableSpec([self.T("회사", "Company"), "EV", basis, self.T("배수", "Multiple"), self.T("처리", "Treatment")], erows,
                                  [0.26, 0.22, 0.2, 0.13, 0.19], ["L", "R", "R", "R", "L"], font_size=8.0),
                  note=(self.T(f"D&A 미수집({', '.join(self.da_missing()[0])}) → EBITDA 대신 EBIT(영업이익)로 대용: EV/EBIT ≥ EV/EBITDA라 배수는 높게, Target에도 EBIT를 적용해 일관. 모든 적용 비교기업의 D&A가 들어오면 EV/EBITDA로 자동 전환. EV = 시총 + 순차입금(리스 제외). 합산 n = {ev_g.n}",
                               f"D&A missing ({', '.join(self.da_missing()[1])}) → EBIT stands in for EBITDA (EV/EBIT ≥ EV/EBITDA), applied to Target's EBIT for consistency; switches to EV/EBITDA automatically once all applied peers have D&A. EV = cap + net debt (ex leases). Aggregate n = {ev_g.n}")
                        if basis == "EBIT" else
                        self.T(f"EBITDA = 영업이익 + D&A(DART 현금흐름표·SEC). EV = 시총 + 순차입금(리스 제외). 합산 n = {ev_g.n}",
                               f"EBITDA = operating income + D&A (DART cash flow, SEC). EV = cap + net debt (ex leases). Aggregate n = {ev_g.n}")))
        title = self.T(f"적용 PER {self.x(self.per())}: {self.dom_label()} 합산 {self.x(dom.aggregate)}(평균 {self.x(dom.mean)} · 중앙값 {self.x(dom.median)})"
                       + (f" + 해외 핵심 {self.x(mu.groups['core']['current'].aggregate)}" if mu.groups['core']['current'].n else " — 해외 핵심은 시총 수집 후 평균에 편입"),
                       f"Applied P/E {self.x(self.per())}: Korea aggregate {self.x(dom.aggregate)} (mean {self.x(dom.mean)}, median {self.x(dom.median)})"
                       + (f" + U.S. core {self.x(mu.groups['core']['current'].aggregate)}" if mu.groups['core']['current'].n else " — U.S. core joins once caps are in"))
        sub = self.T(f"PER(주) · EV/{basis}(보조) · 이상치 규칙 R1~R6 — 국내·해외·합산을 각각 계산",
                     f"P/E (main) · EV/{basis} (secondary) · outlier rules R1–R6 — Korea, U.S. and combined computed separately")
        return Page("body", "4", title, sub, [c1, c2, c3, c4],
                    extra={"toc": self.T(f"적용 PER {self.x(self.per())} — 국내 합산 {self.x(dom.aggregate)}, 평균 {self.x(dom.mean)}·중앙값 {self.x(dom.median)}, EV 배수는 보조",
                                         f"Applied P/E {self.x(self.per())} — Korea aggregate {self.x(dom.aggregate)}, mean {self.x(dom.mean)}, median {self.x(dom.median)}; EV secondary")})

    # --- p5 배수 시나리오 ---------------------------------------------------
    def p5(self) -> Page:
        f, c = self.f, self.c
        if not ok(f.mult):
            cells = [self.pending(t, ["krx", "dart"], self.missing_text(f.mult)) for t in (
                self.T("시나리오", "Scenarios"), self.T("정의", "Definitions"), self.T("2023년 초 PER", "Early-2023 P/E"), self.T("정상화 근거", "Normalisation"))]
            return Page("body", "5", self.T("배수 시나리오: 데이터 확인 중", "Scenarios: data pending"), "", cells)
        mu, t = f.mult, f.peers.table
        cats = [self.scen(s) for s in SCEN]
        series = [(self.dom_label(), [mu.scen["domestic"][s] for s in SCEN], c["gold"])]
        if mu.groups["core"]["current"].n:
            series.append((self.T("해외 핵심", "U.S. core"), [mu.scen["core"][s] for s in SCEN], c["brown_dark"]))
            series.append((self.T("적용", "Applied"), [mu.applied(s) for s in SCEN], c["charcoal"]))
        cur, nm, cs = (self.per(s) for s in SCEN)
        c1 = Cell(title=self.T(f"현재 {self.x(cur)} → 정상화 {self.x(nm)} → 보수 {self.x(cs)}: 같은 이익에 시총은 {self.pct(nm / cur, 0)} · {self.pct(cs / cur, 0)}",
                               f"Current {self.x(cur)} → normalised {self.x(nm)} → conservative {self.x(cs)}: equity value falls to {self.pct(nm / cur, 0)} and {self.pct(cs / cur, 0)}"),
                  src=["krx", "dart", "sec"], legend=[(col, name) for name, _, col in series], unit=self.T("배", "x"), chart_key="scen",
                  chart=charts.grouped(cats, series, c, lambda v: f"{v:.1f}"),
                  note=self.T("시나리오는 확률이 아닌 범위. 몬테카를로(p7)에서 보수~현재를 삼각분포로", "Scenarios are a range, not probabilities; the Monte Carlo (p7) uses a triangular distribution from conservative to current"))
        w = self.v["multiples"]["normalization"]["weight"]
        v = f.val if ok(f.val) else None
        ps = (lambda k: self.won(v.per_share[k])) if v is not None else (lambda k: "—")
        drows = [[self.scen("current"), self.T(f"기준일({f.peers.t1}) 시총 ÷ FY2025A", f"As-of ({f.peers.t1}) cap ÷ FY2025A"),
                  self.x(mu.scen["domestic"]["current"]), self.x(mu.scen["core"]["current"]), self.x(cur), ps("current")],
                 [self.scen("normalized"), self.T(f"√(보수 × 현재): 로그 기준 {w * 100:.0f}% 되돌림", f"√(conservative × current): {w * 100:.0f}% log reversal"),
                  self.x(mu.scen["domestic"]["normalized"]), self.x(mu.scen["core"]["normalized"]), self.x(nm), ps("normalized")],
                 [self.scen("conservative"), self.T(f"2023년 첫 거래일({f.peers.t0}) 시총 ÷ FY2022A", f"First 2023 trading day ({f.peers.t0}) cap ÷ FY2022A"),
                  self.x(mu.scen["domestic"]["conservative"]), self.x(mu.scen["core"]["conservative"]), self.x(cs), ps("conservative")]]
        nn = v.nn if v is not None else None
        if nn:
            drows.append([self.T("정상화 이익 × 정상화 배수", "Normalised earnings × multiple"),
                          self.T(f"순이익률 {self.pct(nn['npm'])}(4년 사이클 평균) × 정상화 배수", f"Net margin {self.pct(nn['npm'])} (4-yr cycle average) × normalised multiple"),
                          "—", "—", self.x(nn["per"]), self.won(nn["per_share"])])
        c2 = Cell(title=(self.T(f"이익까지 정상화하면 주당 {self.won(nn['per_share'])} — 현재 기준 평가가액의 {self.pct(nn['per_share'] / v.per_share['current'], 0)}",
                                f"Normalise earnings too and value is {self.won(nn['per_share'])} per share — {self.pct(nn['per_share'] / v.per_share['current'], 0)} of the current-basis value")
                         if nn else self.T("세 시나리오는 모두 데이터: 현재·2023년 초 실측, 정상화는 두 값의 로그 중간", "All three are data: today and early 2023 observed; normalised is their log midpoint")),
                  src=["krx", "dart", "sec"],
                  table=TableSpec([self.T("시나리오", "Scenario"), self.T("정의", "Definition"), self.T("국내", "Korea"), self.T("해외 핵심", "U.S. core"),
                                   self.T("적용", "Applied"), self.T("주당 평가가액", "Value/share")],
                                  drows, [0.17, 0.35, 0.1, 0.11, 0.11, 0.16], ["L", "L", "R", "R", "R", "R"], shade_rows={1} | ({3} if nn else set()),
                                  gold_cells={(i, 4) for i in range(3)} | ({(3, 5)} if nn else set()), brick_cells={(3, 5)} if nn else set(), font_size=8.0),
                  note=self.T(("해외 핵심 '—' = 시총 수집 전 → 적용 = 국내. " if not mu.groups["core"]["current"].n else "적용 = 국내·해외 핵심 그룹 배수의 단순평균. ")
                              + "마지막 행 = 이익도 사이클 평균으로 되돌린 경우(이중 고점 해소) — 같은 매출·주식수",
                              ("U.S. core '—' = caps pending → applied = Korea. " if not mu.groups["core"]["current"].n else "Applied = simple average of Korea and U.S. core group multiples. ")
                              + "Last row = earnings also back to the cycle average (both peaks unwound) — same revenue and shares"))
        prow = []
        for _, r in t[t["status"].isin(["applied", "excluded", "pending", "held"]) & t["has_fin"]].iterrows():
            if r["group"] not in ("domestic", "core"):
                continue
            s0 = r["s0"]
            prow.append([self.cname(r), self.money(r, r["mcap0"]) if np.isfinite(r["mcap0"]) else "—", self.money(r, r["ni0"]),
                         self.x(r["per0"]) if np.isfinite(r["per0"]) else ("R1" if s0.rule == "R1" else "—"),
                         (self.x(r["per1"]) + (self.T(" (보류)", " (held)") if r["status"] == "held" else "")) if np.isfinite(r["per1"]) else "—",
                         self.x(r["per1"] / r["per0"]) if np.isfinite(r["per0"]) and np.isfinite(r["per1"]) else "—"])
        c3 = Cell(title=self.T(f"회사별: 국내 2023년 초 PER {self.x(np.nanmin(t.loc[t['group'] == 'domestic', 'per0']))}~{self.x(np.nanmax(t.loc[(t['group'] == 'domestic') & (t['status'] == 'applied'), 'per0']))} → 현재",
                               f"By company: Korea early-2023 P/E {self.x(np.nanmin(t.loc[t['group'] == 'domestic', 'per0']))}–{self.x(np.nanmax(t.loc[(t['group'] == 'domestic') & (t['status'] == 'applied'), 'per0']))} → today"),
                  src=["krx", "dart", "sec"],
                  table=TableSpec([self.T("회사", "Company"), self.T(f"시총 {f.peers.t0}", f"Cap {f.peers.t0}"), self.T("순이익 FY2022A", "NI FY2022A"),
                                   self.T("PER 2023초", "P/E early-23"), self.T("PER 현재", "P/E now"), self.T("배수 변화", "Change")], prow,
                                  [0.22, 0.2, 0.18, 0.13, 0.13, 0.14], ["L", "R", "R", "R", "R", "R"], font_size=8.0),
                  note=self.T("R1 = FY2022A 지배순손실 → 보수 시나리오에서도 제외. 미국 = 2023년 첫 거래일 종가 × 그 이전 최근 SEC 표지 주식수 ÷ FY2022A 순이익"
                              + (". 보류(R6) 회사는 두 시점 모두 제외" if (t["status"] == "held").any() else ""),
                              "R1 = FY2022A net loss → also excluded at the conservative point. U.S. = first-2023 close × latest prior SEC cover shares ÷ FY2022A NI"
                              + ("; held (R6) names excluded at both points" if (t["status"] == "held").any() else "")))
        L = f.links
        arith = (cur + cs) / 2
        bl = [self.T(f"Vol.1은 시총 증가를 로그로 나눴다: 이익 {self.pct(L.earn_share, 0)}, 멀티플 {self.pct(1 - L.earn_share, 0)}" if L.earn_share is not None else "Vol.1 로그 분해",
                     f"Vol.1 split the gain in logs: earnings {self.pct(L.earn_share, 0)}, multiple {self.pct(1 - L.earn_share, 0)}" if L.earn_share is not None else "Vol.1 log split"),
              self.T(f"정상화 = 같은 로그 척도에서 멀티플 확대분의 {w * 100:.0f}%가 되돌려지는 경우 → {self.x(nm)}", f"Normalised = {w * 100:.0f}% of the re-rating reverses on the same log scale → {self.x(nm)}"),
              self.T(f"산술 중간이면 {self.x(arith)} — 큰 배수 쪽으로 기울어 덜 보수적", f"An arithmetic midpoint would be {self.x(arith)} — tilted toward the high multiple"),
              self.T(f"적정 시총: 현재 {self.eok(f.val.equity['current'])} · 정상화 {self.eok(f.val.equity['normalized'])} · 보수 {self.eok(f.val.equity['conservative'])}",
                     f"Equity value: current {self.eok(f.val.equity['current'])} · normalised {self.eok(f.val.equity['normalized'])} · conservative {self.eok(f.val.equity['conservative'])}")
              if ok(f.val) else ""]
        if ok(f.val) and f.val.nn:
            nn = f.val.nn
            bl.append(self.T(f"배수만이 아니다: 순이익률도 FY2025A {self.pct(f.assumptions['npm'].value)}가 4년 평균 {self.pct(nn['npm'])}로 돌아가면 적정 시총 {self.eok(nn['equity'])}(정상화 이익 × 정상화 배수)",
                             f"Not only the multiple: if net margin also returns from {self.pct(f.assumptions['npm'].value)} to the 4-yr average {self.pct(nn['npm'])}, equity value is {self.eok(nn['equity'])} (normalised × normalised)"))
        c4 = Cell(title=self.T("정상화를 로그 중간으로 둔 이유: Vol.1 분해와 같은 척도", "Why a log midpoint: the same scale as Vol.1's split"),
                  bullets=[b for b in bl if b], note=self.T("되돌림 비율(50%)은 저자 판단 — 몬테카를로는 보수~현재 전 구간을 쓴다", "The 50% reversal is the author's judgment; the Monte Carlo spans conservative to current"))
        nn = f.val.nn if ok(f.val) else None
        if nn:
            title = self.T(f"배수 시나리오: 현재 {self.x(cur)} · 정상화 {self.x(nm)} · 보수 {self.x(cs)} — 이익까지 정상화하면 주당가치는 현재 기준의 {self.pct(nn['per_share'] / f.val.per_share['current'], 0)}",
                           f"Scenarios: current {self.x(cur)} · normalised {self.x(nm)} · conservative {self.x(cs)} — normalise earnings too and value is {self.pct(nn['per_share'] / f.val.per_share['current'], 0)} of the current basis")
        else:
            title = self.T(f"배수 시나리오: 현재 {self.x(cur)} · 정상화 {self.x(nm)} · 보수 {self.x(cs)} — 보수면 같은 이익의 시총이 현재의 {self.pct(cs / cur, 0)}",
                           f"Scenarios: current {self.x(cur)} · normalised {self.x(nm)} · conservative {self.x(cs)} — conservative values the same earnings at {self.pct(cs / cur, 0)} of today")
        sub = self.T("보수 = 2023년 초 실측 PER(같은 비교기업·같은 규칙), 정상화 = 로그 중간 — 이상치 규칙은 두 시점에 똑같이",
                     "Conservative = observed early-2023 P/E (same peers, same rules); normalised = log midpoint — outlier rules applied at both points")
        return Page("body", "5", title, sub, [c1, c2, c3, c4])

    # --- p6 공모가 산출 -----------------------------------------------------
    def p6(self) -> Page:
        f, c = self.f, self.c
        if not (ok(f.val) and ok(f.band)):
            u = f.val if not ok(f.val) else f.band
            cells = [self.pending(t, ["ksj"], self.missing_text(u)) for t in (
                self.T("평가가액 산정", "Valuation build"), self.T("할인율별 공모가", "Price by discount"), self.T("민감도", "Sensitivity"), self.T("공모 구조", "Deal structure"))]
            return Page("body", "6", self.T("공모가 산출: 입력 확인 중", "Offer price: inputs pending"), "", cells)
        v, b, sh, a = f.val, f.band, f.val.shares, f.assumptions
        v0 = v.per_share["current"]
        rows = [["①", self.T("적용 이익: Target Co. FY2025A 지배순이익", "Earnings: Target Co. FY2025A NI to parent"), self.eok(v.ni)],
                ["②", self.T(f"× 적용 PER ({self.applied_label()}, 현재)", "× applied P/E (current)"), self.x(self.per())],
                ["③", self.T("= 적정 시가총액", "= Fair equity value"), self.eok(v.equity["current"])],
                ["④", self.T(f"÷ 공모 후 주식수 (상장 전 {self.shares(sh.pre)} + 신주 {self.shares(sh.new)})", f"÷ post-IPO shares ({self.shares(sh.pre)} + {self.shares(sh.new)} new)"), self.shares(sh.post)],
                ["⑤", self.T("= 주당 평가가액", "= Value per share"), self.won(v0)],
                ["⑥", self.T(f"할인율 ({self.band_basis()})", f"Discount ({self.band_basis()})"), self.disc_text()],
                ["⑦", self.T(f"= 희망공모가 밴드 ({self.v['price_tick']:,}원 단위)", f"= Indicative range (rounded to KRW {self.v['price_tick']:,})"), self.band_text()]]
        bd = f.band_dp if ok(f.band_dp) else None
        if bd is not None:
            rows.append(["⑧", self.T(f"참고: 이중 고점 반영 밴드 (할인율 {bd.d_low * 100:.0f}~{bd.d_high * 100:.0f}%, p7)",
                                     f"Ref.: double-peak range ({bd.d_low * 100:.0f}–{bd.d_high * 100:.0f}% discount, p7)"), self.won_rng(bd.low, bd.high)])
        c1 = Cell(title=self.T(f"평가가액 {self.won(v0)} = {self.eok(v.ni)} × {self.x(self.per())} ÷ {self.shares(sh.post)} → 밴드 {self.band_text()}",
                               f"Value {self.won(v0)} = {self.eok(v.ni)} × {self.x(self.per())} ÷ {self.shares(sh.post)} → range {self.band_text()}"),
                  src=["ksj"], table=TableSpec(["", self.T("단계", "Step"), self.T("값", "Value")], rows, [0.06, 0.64, 0.30], ["C", "L", "R"],
                                               shade_rows={4, 6}, gold_cells={(4, 2), (6, 2)}, brick_cells={(7, 2)} if bd is not None else set(), font_size=8.6),
                  note=self.T("주당 평가가액은 공모 후 주식수로 나눈다(신주 대금은 더하지 않음 — 보수적). " + {
                                  "mc": "밴드 = 1년 후 주당가치 분위(순이익률 고정, p7)를 반올림",
                                  "evidence": "밴드 할인율 = 국내 IPO 증권신고서 할인율 분포의 중앙값(하단·상단)",
                                  "config": "밴드 = 평가가액 × (1 − 입력 할인율)"}[b.basis],
                              "Value per share uses post-IPO shares (new-share proceeds not added — conservative). " + {
                                  "mc": "Range = rounded quantiles of 1-yr value (margin fixed, p7)",
                                  "evidence": "Range discounts = medians of Korean IPO prospectus discounts (low and high)",
                                  "config": "Range = value × (1 − input discount)"}[b.basis]))
        labels = [f"{d * 100:.0f}%" for d in v.grid["discount"]]
        c2 = Cell(title=self.T(f"할인율 10~40%: {self.won(v.grid['price'].iloc[-1])}~{self.won(v.grid['price'].iloc[0])} — 밴드는 {self.disc_text()} 구간",
                               f"10–40% discount: {self.won(v.grid['price'].iloc[-1])}–{self.won(v.grid['price'].iloc[0])} — the range sits at {self.disc_text()}"),
                  src=["ksj"], legend=[(c["brown_mid"], self.T("할인율별 공모가", "Price by discount")), (c["gold"], self.T("희망공모가 밴드", "Indicative range")),
                                       (c["charcoal"], self.T("주당 평가가액", "Value per share"))],
                  unit=self.T("원, 할인율", "KRW, discount"), chart_key="ladder",
                  chart=charts.price_ladder(labels, list(v.grid["price"]), c, lambda x_: f"{x_:,.0f}", (b.low, b.high), self.T("밴드", "Range"),
                                            (v0, self.T("평가가액", "Value"))),
                  note=self.T("할인율 = 1 − 공모가 ÷ 주당 평가가액(현재 배수)", "Discount = 1 − price ÷ value per share (current multiple)"))
        rl = []
        for k, p in v.sens_rows:
            rl.append(self.T(f"{SCEN_KR[k]} {p:.1f}배", f"{SCEN_EN[k]} {p:.1f}x") if k in SCEN_KR else self.T(f"{p:.0f}배", f"{p:.0f}x"))
        z = v.sens.to_numpy()
        step = (self.v["per_grid"][1] - self.v["per_grid"][0]) if len(self.v["per_grid"]) > 1 else 5
        dprice = v.ni * step * 1e8 / sh.post
        c3 = Cell(title=self.T(f"민감도: 적용 PER {step}배 차이 = 주당 {self.won(dprice)}(할인 전) — 밴드 안 칸은 골드",
                               f"Sensitivity: {step}x of P/E = {self.won(dprice)} per share (before discount) — cells inside the range in gold"),
                  src=["ksj"], unit=self.T("원 (행 = 적용 PER, 열 = 할인율)", "KRW (rows = applied P/E, columns = discount)"), chart_key="heat",
                  chart=charts.price_heat(z, rl, [f"{d * 100:.0f}%" for d in self.v["discount_grid"]], c, (b.low, b.high), lambda x_: f"{x_:,.0f}",
                                          self.T("할인율", "Discount"), self.T("적용 PER", "Applied P/E"), bold_rows={0, 1, 2}),
                  note=self.T("위 세 행 = 배수 시나리오(p5), 아래 = 5배 간격 격자. 밴드보다 높은 칸 = 웜그레이", "Top three rows = scenarios (p5), below = 5x grid. Cells above the range in warm grey"))
        amt_lo, amt_hi = self.offer_amount(b.low), self.offer_amount(b.high)
        lockup = a["lockup_months"].value
        drows = [[self.T("상장 전 주식수", "Pre-IPO shares"), f"{sh.pre:,.0f}", "—"],
                 [self.T(f"공모주식 (공모 후의 {self.pct(a['offer_ratio'].value, 0)})", f"Offer shares ({self.pct(a['offer_ratio'].value, 0)} of post-IPO)"), f"{sh.offered:,.0f}",
                  self.rng(amt_lo, amt_hi, self.eok)],
                 [self.T("  신주 (회사 유입)", "  Primary (to company)"), f"{sh.new:,.0f}", self.rng(sh.new * b.low / 1e8, sh.new * b.high / 1e8, self.eok)],
                 [self.T("  구주매출 (기존 주주)", "  Secondary (to sellers)"), f"{sh.old:,.0f}", self.rng(sh.old * b.low / 1e8, sh.old * b.high / 1e8, self.eok)],
                 [self.T("공모 후 주식수", "Post-IPO shares"), f"{sh.post:,.0f}", self.T(f"시총 {self.rng(sh.post * b.low / 1e8, sh.post * b.high / 1e8, self.eok)}",
                                                                                         f"Cap {self.rng(sh.post * b.low / 1e8, sh.post * b.high / 1e8, self.eok)}")],
                 [self.T("기존 주주 잔여 (오버행)", "Existing holders' stake (overhang)"), f"{sh.overhang:,.0f}", self.pct(sh.overhang / sh.post)],
                 [self.T("신주 희석률", "Dilution from new shares"), "", self.pct(sh.dilution)]]
        c4 = Cell(title=self.T(f"공모 {self.shares(sh.offered)}(신주 {self.pct(sh.new / sh.offered, 0)}) · 공모금액 {self.rng(amt_lo, amt_hi, self.eok)} — 기존 주주 {self.pct(sh.overhang / sh.post, 0)}가 잠재 매도 물량",
                               f"Offer {self.shares(sh.offered)} ({self.pct(sh.new / sh.offered, 0)} primary) · {self.rng(amt_lo, amt_hi, self.eok)} — existing holders' {self.pct(sh.overhang / sh.post, 0)} is the overhang"),
                  src=["law", "ksj"], table=TableSpec([self.T("항목", "Item"), self.T("주식수", "Shares"), self.T("금액 (밴드 하단~상단)", "Amount (range low–top)")], drows,
                                                      [0.42, 0.24, 0.34], ["L", "R", "R"], shade_rows={1, 5}, font_size=8.4),
                  note=self.T("공모 비율은 상장규정 주식분산 요건 수준(원문 확인 전), 신주 비중은 가상 거래 설계. 최대주주 보호예수 기간 " + (f"{lockup:.0f}개월" if lockup else "미확정 → 물량만 표시")
                              + self.lockup_fact(),
                              "Offer size at the listing rules' free-float level (to verify); primary share is hypothetical. Major-holder lock-up " + (f"{lockup:.0f} months" if lockup else "not set → shares only")
                              + self.lockup_fact()))
        c4.src = ["law", "fss", "ksj"]
        cells = [c1, c2, c3, c4]
        grid = "2x2"
        ic = self.ipo_cell("p6")
        if ic is not None:
            cells, grid = [c2, ic, c3, c1, c4], "3-2"
        title = self.T(f"주당 평가가액 {self.won(v0)} → 희망공모가 {self.band_text()}(할인율 {self.disc_text()}) — 공모금액 {self.rng(amt_lo, amt_hi, self.eok)}",
                       f"Value {self.won(v0)} per share → indicative range {self.band_text()} ({self.disc_text()} discount) — offer {self.rng(amt_lo, amt_hi, self.eok)}")
        sub = self.T("적정 시총 → 공모 후 주식수(신주·구주) → 주당 평가가액 → 할인율 시나리오(10~40%) → 밴드 · 민감도(적용 배수 × 할인율)",
                     "Equity value → post-IPO shares (primary, secondary) → value per share → discount scenarios (10–40%) → range · sensitivity (multiple × discount)")
        return Page("body", "6", title, sub, cells, grid=grid)

    def lockup_fact(self) -> str:
        a = self.f.assumptions
        x, y, k = (a.get(n) for n in ("inst_lockup_2025", "inst_lockup_2024", "inst_lockup_kospi_2025"))
        if not (x and x.value is not None and y and y.value is not None):
            return ""
        kt = (self.T(f", 코스피 {self.pct(k.value, 0)}", f"; KOSPI {self.pct(k.value, 0)}") if k and k.value is not None else "")
        return self.T(f". 참고: 기관 의무보유확약 비율 2025년 {self.pct(x.value, 0)}(전년 {self.pct(y.value, 0)}){kt} — 금융감독원 발표(머니투데이 보도)",
                      f". Ref.: institutional lock-up commitments {self.pct(x.value, 0)} in 2025 (prior year {self.pct(y.value, 0)}){kt} — FSS release via Money Today")

    def ipo_label(self) -> str:
        ev = self.f.ipo
        return (self.T(f"하위 표본({ev.sub_rule}) {ev.sub.n}건", f"sub-sample (KOSPI or offer ≥ KRW {float(self.v['ipo_discounts']['sub_min_offer']) / 10:,.0f}bn), n = {ev.sub.n}")
                if ev.chosen == "sub" else self.T(f"전체 {ev.full.n}건", f"full sample, n = {ev.full.n}"))

    def ipo_cell(self, where: str) -> Cell | None:
        """국내 IPO 할인율 분포 Exhibit (증권신고서 실증 데이터가 있을 때만): 전체 + 하위 표본, Target 할인율 위치."""
        ev, b = self.f.ipo, self.f.band
        if not ok(ev) or ev.full.n == 0 or not ok(b):
            return None
        fs, ss = ev.full, ev.sub
        series = [(self.T(f"전체 하단 (n={fs.n})", f"All, low (n={fs.n})"), list(fs.table["discount_low"])),
                  (self.T(f"전체 상단 (n={fs.n})", f"All, high (n={fs.n})"), list(fs.table["discount_high"]))]
        if ss.n >= 3:
            series += [(self.T(f"하위 하단 (n={ss.n})", f"Sub, low (n={ss.n})"), list(ss.table["discount_low"])),
                       (self.T(f"하위 상단 (n={ss.n})", f"Sub, high (n={ss.n})"), list(ss.table["discount_high"]))]
        bd = self.f.band_dp if ok(self.f.band_dp) else None
        marks = [(b.d_low, self.T("Target 상단가", "Target top"), self.c["gold"]), (b.d_high, self.T("Target 하단가", "Target low"), self.c["brown_dark"])]
        if bd is not None and where == "p8":
            marks.append(((bd.d_low + bd.d_high) / 2, self.T("이중 고점 밴드 중간", "Double-peak mid"), self.c["brick"]))
        s_ = ev.sample
        (q1l, ml, q3l), (q1h, mh, q3h) = s_.stats["low"], s_.stats["high"]
        (_, mle, _), (_, mhe, _) = s_.stats_ex["low"], s_.stats_ex["high"]
        pos = ev.rank((b.d_low + b.d_high) / 2, "mid")
        span = self.T(f"접수 {fs.period[0]}~{fs.period[1]}", f"filed {fs.period[0]} to {fs.period[1]}")
        pick = (self.T(f"Target(공모금액 약 {self.offer_amount(b.low):,.0f}억원)에는 하위 표본({ev.sub_rule}) 사용(n ≥ {ev.sub_min_n})",
                       f"Target (offer ≈ KRW {self.offer_amount(b.low) / 10:,.0f}bn) uses the sub-sample (n ≥ {ev.sub_min_n})")
                if ev.chosen == "sub" else
                self.T(f"하위 표본({ev.sub_rule}) {ss.n}건 < {ev.sub_min_n} → 전체 분포 사용", f"Sub-sample n = {ss.n} < {ev.sub_min_n} → full distribution used"))
        used = "" if ev.used else self.T(f"; n < {ev.min_n}이라 밴드는 몬테카를로 유지", f"; n < {ev.min_n}, range stays Monte Carlo")
        d8 = lambda x: f"{x[:4]}-{x[4:6]}-{x[6:8]}" if len(x) == 8 else x  # noqa: E731
        sa, sb = d8(ev.search[0]), d8(ev.search[1])
        why = (self.T("현재 상장 상태로 거른 표본 — 접수 시점 판정으로 재수집 예정", "filtered on today's listing status — to be re-collected at filing date")
               if ev.n_cls_excluded else self.T(f"검색 {sa}~{sb} 중 실제 신고일 범위가 좁음", f"actual filing dates cover only part of {sa} to {sb}"))
        short = (self.T(f" 표본 {ev.full.n}건 < 목표 {ev.target_n}건({why})", f" Sample {ev.full.n} < target {ev.target_n} ({why})")
                 if ev.full.n < ev.target_n else "")
        short_lab = self.T(f"하위 표본 {ev.sub.n}건", "") if ev.chosen == "sub" else self.T(f"전체 {ev.full.n}건", "")
        return Cell(title=self.T(f"국내 IPO 할인율({short_lab}) 중앙값 {ml * 100:.0f}~{mh * 100:.0f}% — Target 밴드는 P{pos * 100:.0f}",
                                 f"Korean IPO discounts ({self.ipo_label()}): median {ml * 100:.0f}% (low) · {mh * 100:.0f}% (high) — Target's range at P{pos * 100:.0f}"),
                    src=["ipo"], legend=[(self.c["warm_grey_light"], self.T("전체", "All")), (self.c["panel"], self.T("하위 표본", "Sub-sample"))] if ss.n >= 3 else
                    [(self.c["warm_grey_light"], self.T("사분위 상자 · 중앙값", "IQR box · median"))], unit=self.T("할인율 (평가가액 대비)", "Discount to value"),
                    chart_key=f"ipo_{where}", chart=charts.discount_boxes(series, self.c, marks),
                    note=self.T(f"DART 증권신고서(지분증권) 신규 상장, {span}, 회사별 밴드가 처음 나온 신고서 1건. {pick}. 사분위 하단 {q1l * 100:.0f}~{q3l * 100:.0f}%, 상단 {q1h * 100:.0f}~{q3h * 100:.0f}%. "
                                f"이상치(상단 > {self.v['ipo_discounts']['outlier_high'] * 100:.0f}% 또는 하단 < {self.v['ipo_discounts']['outlier_low'] * 100:.0f}%, 원문 확인 필요) {s_.n_outlier}건 — 제외 시 중앙값 하단 {mle * 100:.1f}% · 상단 {mhe * 100:.1f}%{used}.{short}",
                                f"DART equity prospectuses for new listings, {span}; first filing with a price range per company. {pick}. IQR low {q1l * 100:.0f}–{q3l * 100:.0f}%, high {q1h * 100:.0f}–{q3h * 100:.0f}%. "
                                f"Outliers (high > {self.v['ipo_discounts']['outlier_high'] * 100:.0f}% or low < {self.v['ipo_discounts']['outlier_low'] * 100:.0f}%, to check) {s_.n_outlier} — excluding them, medians {mle * 100:.1f}% / {mhe * 100:.1f}%{used}.{short}"))

    # --- p7 몬테카를로 -------------------------------------------------------
    def ev_ref_reason(self) -> str:
        """EV 교차 확인이 독립 근거가 아닌 이유 (국내 = PER과 같은 구성, 차이 = 해외 EV 피어)."""
        t = self.f.peers.table
        cn = [r["company"] if self.kr else r["company_en"] for _, r in t[(t["group"] == "core") & (t["status"] == "applied") & t["evm1"].notna()].iterrows()]
        basis = self.f.peers.ev_basis
        return self.T(f"참고(독립 근거 아님): 국내 부분은 Target 이익률·순차입금을 같은 3사 합산에서 가져와 PER 평가와 같은 구성, 차이는 해외 {len(cn)}개사({'·'.join(cn)})의 EV/{basis}에서 나온다",
                      f"Reference, not independent: the Korean part uses the same 3-name margins and net debt as the P/E value, so the gap comes from {len(cn)} U.S. name(s) ({', '.join(cn)})")

    def margin_sens(self, ticker: str = "010120") -> dict | None:
        """Target 순이익률을 비교기업 한 곳(기본 LS ELECTRIC, 제품이 가장 가까운 회사)의 FY2025A 순이익률로 바꿨을 때 평가가액·밴드."""
        from src.analysis import ipo_model as im
        f = self.f
        if not (ok(f.val) and ok(f.band) and f.der is not None):
            return None
        d = f.der.detail
        hit = d[d["ticker"] == ticker]
        a = f.assumptions
        if hit.empty or a["npm"].value is None or a["band_discount_low"].value is None:
            return None
        r = hit.iloc[0]
        ratio = float(r["npm"]) / float(a["npm"].value)          # 순이익 ∝ 순이익률 (매출·배수·주식수 고정)
        v1 = f.val.per_share["current"] * ratio
        tick = float(self.v.get("price_tick") or 0)
        hi, lo = im.round_price(v1 * (1 - a["band_discount_low"].value), tick), im.round_price(v1 * (1 - a["band_discount_high"].value), tick)
        chg = (lo + hi) / (f.band.low + f.band.high) - 1
        top = d.sort_values("npm", ascending=False).iloc[0]
        en = {str(p["ticker"]).zfill(6): p.get("name_en", p["name"]) for p in self.cfg["peers"]["domestic"]}
        nm = lambda x: x["company"] if self.kr else en.get(str(x["ticker"]).zfill(6), x["company"])  # noqa: E731
        return {"company": nm(r), "npm": float(r["npm"]), "value": v1, "low": lo, "high": hi, "chg": chg,
                "top": nm(top), "top_npm": float(top["npm"])}

    def floor_text(self, short: bool = False) -> str:
        """이중 고점 순이익률 하한 가정 병기: 'FY2022A면 필요 할인율 중앙값 43.4%, FY2023A(5.2%)면 37.9%'."""
        dp, alt = self.f.mc_dp, self.f.dp_floor_alt
        if not ok(dp) or not alt:
            return ""
        y0 = alt["fy"] - 1                     # 기준 하한 = 비교 구간 첫해(사이클 바닥)
        r0, r1 = dp.required[0.5], alt["mc"].required[0.5]
        if short:
            return self.T(f"하한 FY{y0}A면 {self.pct(r0)}, FY{alt['fy']}A면 {self.pct(r1)}", f"FY{y0 % 100}A {self.pct(r0)} vs FY{alt['fy'] % 100}A {self.pct(r1)}")
        return self.T(f"순이익률 하한 FY{y0}A({self.pct(dp.npm_tri[0])})면 필요 할인율 중앙값 {self.pct(r0)}, FY{alt['fy']}A({self.pct(alt['npm_low'])})면 {self.pct(r1)}",
                      f"with a net-margin floor at FY{y0}A ({self.pct(dp.npm_tri[0])}) the median required discount is {self.pct(r0)}; at FY{alt['fy']}A ({self.pct(alt['npm_low'])}) it is {self.pct(r1)}")

    def dp_covered(self) -> bool:
        """이중 고점에서 중앙값 손익분기 할인율이 할인율 시나리오 상단 안에 들어오는지."""
        return ok(self.f.mc_dp) and self.f.mc_dp.required[0.5] <= self.v["discount_grid"][-1]

    def bd_text(self, b) -> str:
        return f"{b.d_low * 100:.0f}~{b.d_high * 100:.0f}%" if self.kr else f"{b.d_low * 100:.0f}–{b.d_high * 100:.0f}%"

    def p7(self) -> Page:
        f, c = self.f, self.c
        if not ok(f.mc):
            cells = [self.pending(t, ["dart", "ksj"], self.missing_text(f.mc)) for t in (
                self.T("1년 후 주당가치 분포", "1-yr value distribution"), self.T("현재 기준 vs 이중 고점", "Current basis vs double peak"),
                self.T("수렴", "Convergence"), self.T("입력", "Inputs"))]
            return Page("body", "7", self.T("몬테카를로: 입력 확인 중", "Monte Carlo: inputs pending"), "", cells)
        mc, dp, st, v, b = f.mc, f.mc_dp, f.mc_stress, f.val, f.band
        v0 = v.per_share["current"]
        q = mc.result.quantiles
        has_dp = ok(dp) and ok(f.band_dp)
        if has_dp:
            bd, qd = f.band_dp, dp.result.quantiles
            c1 = Cell(title=self.T(f"이익률까지 정점이면 1년 후 P50 {q[0.5]:,.0f} → {qd[0.5]:,.0f}원 ({self.pct(qd[0.5] / q[0.5] - 1, 0, True)}) — 평가가액 {self.won(v0)}은 이중 고점 분포의 P{dp.result.percentile_of(v0) * 100:.0f}",
                                   f"With margins also at a peak, 1-yr P50 falls {q[0.5]:,.0f} → {qd[0.5]:,.0f} ({self.pct(qd[0.5] / q[0.5] - 1, 0, True)}) — the {self.won(v0)} value sits at P{dp.result.percentile_of(v0) * 100:.0f} of the double-peak distribution"),
                      src=["dart", "krx", "sec", "ksj"],
                      legend=[(c["warm_grey_light"], self.T("현재 기준(순이익률 고정)", "Current basis (margin fixed)")), (c["brick"], self.T("이중 고점(순이익률 확률변수)", "Double peak (margin random)")),
                              (c["gold"], self.T("현재 기준 밴드", "Current-basis range"))],
                      unit=self.T("원/주", "KRW per share"), chart_key="hist",
                      chart=charts.histogram_pair(mc.result.values, dp.result.values, c, lambda x_: f"{x_:,.0f}", (c["warm_grey_light"], c["brick"]),
                                                  [(b.low, b.high, self.T("현재 기준 밴드", "Current range"), c["gold"]),
                                                   (bd.low, bd.high, self.T("이중 고점 밴드", "Double-peak range"), c["brick"])],
                                                  (v0, self.T("평가가액", "Value"))),
                      note=self.T("1년 후 주당가치 = FY2025A 지배순이익 × (1 + 성장률) × 1년 후 PER × (1년 후 순이익률 ÷ 현재 순이익률) ÷ 공모 후 주식수. 각 10,000회·같은 seed",
                                  "1-yr value = FY2025A NI × (1 + growth) × 1-yr P/E × (1-yr margin ÷ current margin) ÷ post-IPO shares. 10,000 runs each, same seed"))
        else:
            marks = [(q[0.1], "P10", c["brick"]), (q[0.5], "P50", c["charcoal"]), (q[0.9], "P90", c["brown_dark"]), (v0, self.T("평가가액", "Value"), c["gold"])]
            c1 = Cell(title=self.T(f"1년 후 주당가치 P10 {q[0.1]:,.0f} · P50 {q[0.5]:,.0f} · P90 {q[0.9]:,.0f}원", f"1-yr value P10 {q[0.1]:,.0f} · P50 {q[0.5]:,.0f} · P90 {q[0.9]:,.0f}"),
                      src=["dart", "krx", "ksj"], unit=self.T("원/주", "KRW per share"), chart_key="hist",
                      chart=charts.histogram(mc.result.values, c, lambda x_: f"{x_:,.0f}", marks, (b.low, b.high), self.T("밴드", "Range")))
        grid = self.v["discount_grid"]
        runs = [("base", mc)] + ([("dp", dp), ("stress", st)] if has_dp and ok(st) else [])
        hd = {"base": self.T("현재 기준", "Current basis"), "dp": self.T("이중 고점", "Double peak"), "stress": self.T(f"동조 ρ={self.v['monte_carlo'].get('corr_stress', 0.5)}", f"Co-move ρ={self.v['monte_carlo'].get('corr_stress', 0.5)}")}
        rows = []
        for k, lab in ((0.1, "P10"), (0.25, "P25"), (0.5, "P50"), (0.9, "P90")):
            rows.append([self.T(f"1년 후 주당가치 {lab}", f"1-yr value {lab}")] + [f"{m.result.q(k):,.0f}" for _, m in runs])
        for k, lab in ((0.5, "P50"), (0.25, "P25"), (0.1, "P10")):
            rows.append([self.T(f"필요 할인율 ({lab})", f"Needed discount ({lab})")] + [self.pct(m.required[k], 0) for _, m in runs])
        for d in grid:
            rows.append([self.T(f"할인율 {d * 100:.0f}% 손실 확률", f"Loss prob. at {d * 100:.0f}%")] + [self.pct(m.loss_grid[d], 0) for _, m in runs])
        bands = [b] + ([f.band_dp] if has_dp else [])
        rows.append([self.T("밴드 (P25~P50)", "Range (P25–P50)") if b.basis == "mc" else self.T("밴드", "Range")]
                    + [self.won_rng(x.low, x.high) for x in bands] + ([""] if len(runs) == 3 else []))
        shade = {6 + len(grid) - 1, len(rows) - 1}
        brick = {(i, j) for i in range(4, 7) for j in range(1, len(runs) + 1) if rows[i][j] != "—" and runs[j - 1][1].required[(0.5, 0.25, 0.1)[i - 4]] > grid[-1]}
        last_dp = dp.loss_grid[grid[-1]] if has_dp else None
        c2 = Cell(title=(self.T(f"할인율 {grid[-1] * 100:.0f}%(시나리오 상단)에서도 이중 고점이면 1년 후 손실 확률 {self.pct(last_dp, 0)} — 중앙값 손익분기 할인율 {self.pct(mc.required[0.5], 0)} → {self.pct(dp.required[0.5], 0)}",
                                f"Even at a {grid[-1] * 100:.0f}% discount the double-peak 1-yr loss probability is {self.pct(last_dp, 0)} — median break-even discount {self.pct(mc.required[0.5], 0)} → {self.pct(dp.required[0.5], 0)}")
                         if has_dp else self.T(f"할인율 {grid[0] * 100:.0f}%면 1년 후 손실 확률 {self.pct(mc.loss_grid[grid[0]], 0)}", f"At {grid[0] * 100:.0f}% the 1-yr loss probability is {self.pct(mc.loss_grid[grid[0]], 0)}")),
                  src=["ksj"], table=TableSpec([self.T("지표", "Metric")] + [hd[k] for k, _ in runs], rows,
                                               [0.4] + [0.6 / len(runs)] * len(runs), ["L"] + ["R"] * len(runs), shade_rows=shade,
                                               brick_cells=brick, gold_cells={(len(rows) - 1, 1)}, font_size=7.8),
                  note=self.T("필요 할인율 = 1 − 분위 ÷ 현재 기준 평가가액, 손실 확률 = P(1년 후 주당가치 < 공모가). 적색 = 할인율 시나리오 상단(40%) 초과. 동조 = 성장률·PER·순이익률 쌍별 상관 0.5(민감도)",
                              "Needed discount = 1 − quantile ÷ current-basis value; loss probability = P(1-yr value < price). Red = above the 40% grid top. Co-move = pairwise correlation 0.5 among growth, P/E and margin (sensitivity)"))
        crow = []
        tol = self.v["monte_carlo"]["tolerance"]
        for k, m in runs:
            cv = m.result.convergence
            crow.append([hd[k], f"{cv['P50'].iloc[-2]:,.0f}", f"{cv['P50'].iloc[-1]:,.0f}", self.pct(cv["rel_change_p50"].iloc[-1], 2),
                         self.T("수렴", "Yes") if m.result.converged else self.T("기준 초과", "Above tol."), self.pct(m.se_p50, 2),
                         f"{m.check_p50:,.0f} ({self.pct(m.check_p50 / m.result.q(0.5) - 1, 1, True)})"])
        bad = [hd[k] for k, m in runs if not m.result.converged]
        worst = max((abs(m.check_p50 / m.result.q(0.5) - 1) for _, m in runs), default=0.0)
        c3 = Cell(title=(self.T(f"수렴: {', '.join(bad)}은 5,000→10,000회 P50 변화가 기준({self.pct(tol, 0)}) 초과 — 배치 표준오차 ≤ {self.pct(max(m.se_p50 for _, m in runs), 2)}, 10배 재실행과 차이 ≤ {self.pct(worst, 1)}",
                                f"Convergence: {', '.join(bad)} moved more than {self.pct(tol, 0)} from 5,000 to 10,000 runs — batch s.e. ≤ {self.pct(max(m.se_p50 for _, m in runs), 2)}, ≤ {self.pct(worst, 1)} from a 10x rerun")
                         if bad else self.T(f"수렴: 세 경우 모두 5,000→10,000회 P50 변화 ≤ {self.pct(tol, 0)} (seed {mc.seed})", f"Convergence: all P50 changes ≤ {self.pct(tol, 0)} from 5,000 to 10,000 runs (seed {mc.seed})")),
                  src=["ksj"], table=TableSpec([self.T("구분", "Run"), self.T("P50 5,000회", "P50 at 5k"), self.T("P50 10,000회", "P50 at 10k"), self.T("변화", "Change"),
                                                self.T("판정", "Verdict"), self.T("배치 표준오차", "Batch s.e."), self.T(f"{mc.check_n:,}회 P50", f"P50 at {mc.check_n:,}")],
                                               crow, [0.16, 0.12, 0.12, 0.12, 0.12, 0.12, 0.24], ["L", "R", "R", "R", "C", "R", "R"], font_size=8.0,
                                               brick_cells={(i, 4) for i, (_, m) in enumerate(runs) if not m.result.converged}),
                  note=self.T(f"판정 = 같은 seed 앞 5,000개 vs 10,000개 P50 상대 차이 ≤ {self.pct(tol, 0)}. 기준 초과여도 보고값은 10,000회 그대로 두고, 오차 크기를 배치 표준오차(10개 배치)와 {mc.check_n:,}회 재실행으로 공개",
                              f"Verdict = relative P50 change between the first 5,000 and 10,000 draws ≤ {self.pct(tol, 0)}. Reported values stay at 10,000 runs even when above tolerance; the error size is shown via a 10-batch standard error and a {mc.check_n:,}-run rerun"))
        a = f.assumptions
        irows = [[self.T("이익 성장률 (1년)", "Earnings growth (1 yr)"), f"ln(1+g) ~ N({mc.mu:.3f}, {mc.sd:.3f})",
                  self.T(f"국내 비교기업 매출 성장 {len(f.der.growth_obs) if f.der else 0}개 관측(FY2023A~FY2025A)", f"{len(f.der.growth_obs) if f.der else 0} Korean peer revenue-growth observations")],
                 [self.T("1년 후 PER", "1-yr-ahead P/E"), self.T(f"삼각({mc.per_tri[0]:.1f}, {mc.per_tri[1]:.1f}, {mc.per_tri[2]:.1f})", f"Tri({mc.per_tri[0]:.1f}, {mc.per_tri[1]:.1f}, {mc.per_tri[2]:.1f})"),
                  self.T("최소 보수 · 최빈 정상화 · 최대 현재 (중립 형태)", "Min conservative · mode normalised · max current (neutral)")]]
        if has_dp:
            irows.append([self.T("1년 후 순이익률 (이중 고점)", "1-yr net margin (double peak)"),
                          self.T(f"삼각({self.pct(dp.npm_tri[0])}, {self.pct(dp.npm_tri[1])}, {self.pct(dp.npm_tri[2])})", f"Tri({self.pct(dp.npm_tri[0])}, {self.pct(dp.npm_tri[1])}, {self.pct(dp.npm_tri[2])})"),
                          self.T("FY2022A · 4년 사이클 평균(최빈, 평균회귀 판단) · FY2025A — 국내 3사 합산", "FY2022A · 4-yr cycle average (mode; mean-reversion judgment) · FY2025A — 3 Korean names")])
            rb = [float(a[k].value or 0) for k in ("corr_growth_per", "corr_growth_npm", "corr_npm_per")]
            irows.append([self.T("상관 (성장률·PER·순이익률)", "Correlation (growth, P/E, margin)"),
                          self.T(f"기준 {rb[0]:.1f}/{rb[1]:.1f}/{rb[2]:.1f} · 동조 {self.v['monte_carlo'].get('corr_stress', 0.5)}", f"Base {rb[0]:.1f}/{rb[1]:.1f}/{rb[2]:.1f} · co-move {self.v['monte_carlo'].get('corr_stress', 0.5)}"),
                          self.T("가우스 코퓰라. 추정 데이터 부재 → 기준 독립(중립), 함께 꺾이는 경우는 민감도", "Gaussian copula; no data to estimate → independent base (neutral); joint downturn as sensitivity")])
        else:
            irows.append([self.T("이익률", "Margins"), self.T(f"순이익률 {self.pct(a['npm'].value)} 고정", f"Net margin {self.pct(a['npm'].value)} fixed"), self.T("이중 고점 입력 없음", "No double-peak inputs")])
        if f.dp_floor_alt:
            al = f.dp_floor_alt
            irows.append([self.T("순이익률 하한 민감도", "Net-margin floor sensitivity"),
                          self.T(f"하한 FY{al['fy']}A {self.pct(al['npm_low'])} → 필요 할인율 중앙값 {self.pct(al['mc'].required[0.5])}", f"Floor FY{al['fy']}A {self.pct(al['npm_low'])} → median {self.pct(al['mc'].required[0.5])}"),
                          self.T(f"기준 하한 FY{al['fy'] - 1}A {self.pct(dp.npm_tri[0])}(사이클 바닥, 보수적) → {self.pct(dp.required[0.5])}", f"Base floor FY{al['fy'] - 1}A {self.pct(dp.npm_tri[0])} (trough, conservative) → {self.pct(dp.required[0.5])}")])
        irows += [[self.T("시뮬레이션 · seed", "Runs · seed"), f"{mc.n:,} · {mc.seed}", self.T("재현 가능", "Reproducible")],
                  [self.T("밴드 기준", "Range basis"), f"P{a['band_q_low'].value * 100:.0f} · P{a['band_q_high'].value * 100:.0f}", self.T("하단 손실 확률 25% · 상단 50% (저자 판단)", "Low 25% · top 50% loss probability (judgment)")]]
        c4 = Cell(title=self.T("입력: 성장률·배수에 순이익률을 더해 '정점 이익 × 정점 배수'를 함께 흔든다", "Inputs: growth and multiple, plus net margin, so peak earnings and peak multiples move together"),
                  src=["dart", "krx", "ksj"], table=TableSpec([self.T("입력", "Input"), self.T("분포·값", "Distribution / value"), self.T("근거", "Basis")], irows,
                                                              [0.24, 0.32, 0.44], ["L", "L", "L"], font_size=7.8),
                  note=self.T("현재 기준 = 순이익률 고정. 이중 고점 = 순이익률도 확률변수. 상관 0이면 성장 둔화·배수 하락·이익률 하락이 따로 온다는 가정",
                              "Current basis = margin fixed. Double peak = margin also random. Zero correlation assumes slowdown, de-rating and margin compression arrive separately"))
        if has_dp:
            title = self.T(f"현재 기준 할인율 {self.pct(mc.required[0.5], 0)}~{self.pct(mc.required[0.25], 0)} vs 이중 고점 {self.pct(dp.required[0.5], 0)}~{self.pct(dp.required[0.25], 0)} — 이익률 정점까지 넣으면 필요 할인율이 {(dp.required[0.5] - mc.required[0.5]) * 100:.0f}%p 커진다" + (f" ({self.floor_text(short=True)})" if self.floor_text(short=True) else ""),
                           f"Current basis {self.pct(mc.required[0.5], 0)}–{self.pct(mc.required[0.25], 0)} vs double peak {self.pct(dp.required[0.5], 0)}–{self.pct(dp.required[0.25], 0)} — adding peak margins raises the needed discount by {(dp.required[0.5] - mc.required[0.5]) * 100:.0f}pp" + (f" ({self.floor_text(short=True)})" if self.floor_text(short=True) else ""))
            toc = self.T(f"필요 할인율 현재 기준 {self.pct(mc.required[0.5], 0)}~{self.pct(mc.required[0.25], 0)} vs 이중 고점 {self.pct(dp.required[0.5], 0)}~{self.pct(dp.required[0.25], 0)}",
                         f"Needed discount: current basis {self.pct(mc.required[0.5], 0)}–{self.pct(mc.required[0.25], 0)} vs double peak {self.pct(dp.required[0.5], 0)}–{self.pct(dp.required[0.25], 0)}")
        else:
            title = self.T(f"1년 후 주당가치 P50 {q[0.5]:,.0f}원 = 평가가액의 {self.pct(q[0.5] / v0, 0)} — 필요 할인율 {self.pct(mc.required[0.5], 0)}~{self.pct(mc.required[0.25], 0)}",
                           f"1-yr P50 value {self.won(q[0.5])} = {self.pct(q[0.5] / v0, 0)} of value — needed discount {self.pct(mc.required[0.5], 0)}–{self.pct(mc.required[0.25], 0)}")
            toc = title
        sub = self.T(f"{mc.n:,}회 × 3 (현재 기준 · 이중 고점 · 동조 민감도) · seed {mc.seed} · 1년 후 이익 성장 × 배수(보수~현재) × 순이익률(FY2022A~FY2025A)",
                     f"{mc.n:,} runs × 3 (current basis · double peak · co-move sensitivity) · seed {mc.seed} · 1-yr growth × multiple (conservative–current) × margin (FY2022A–FY2025A)")
        return Page("body", "7", title, sub, [c1, c2, c3, c4], extra={"toc": toc})

    # --- p8 시사점 ----------------------------------------------------------
    def market_facts(self) -> tuple[float | None, float | None]:
        a = self.f.assumptions
        return (a["ipo_in_band_2025"].value if "ipo_in_band_2025" in a else None,
                a["top_of_band_h2_2025"].value if "top_of_band_h2_2025" in a else None)

    def p8(self) -> Page:
        f = self.f
        ready = self.ok_all
        mu = f.mult if ok(f.mult) else None
        has_dp = ready and ok(f.mc_dp) and ok(f.band_dp)
        t = f.peers.table if ok(f.peers) else None
        n_core = int(((t["status"] == "applied") & (t["group"] == "core")).sum()) if t is not None else 0
        held = ", ".join(t[t["status"] == "held"]["company"]) if t is not None else ""
        inb, top = self.market_facts()
        rows = [
            [self.T("비교기업 구성", "Peer set"), self.T(f"국내 {self.n_dom()}사 + 해외 핵심 {n_core}사, 참고 2사" + (f" · {held} 보류" if held else ""),
                                                         f"{self.n_dom()} Korean + {n_core} U.S. core, 2 reference" + (f" · {held} held" if held else "")),
             self.T("보류 회사 10-K 주석(일회성 이익·차입금) 확인 · Schneider 연차보고서 편입", "Check held names' 10-K notes (one-offs, debt); add Schneider from its annual report"), "3, 4"],
            [self.T("적용 배수", "Applied multiple"), self.T(f"PER {self.x(self.per())} (국내 합산 {self.x(mu.groups['domestic']['current'].aggregate)} · 해외 핵심 {self.x(mu.groups['core']['current'].aggregate)})",
                                                             f"P/E {self.x(self.per())} (Korea {self.x(mu.groups['domestic']['current'].aggregate)} · U.S. core {self.x(mu.groups['core']['current'].aggregate)})") if mu else "—",
             self.T("고배수(R4) 회사 포함 여부가 평균을 크게 움직임", "Whether the R4-flagged name stays moves the mean a lot"), "4"],
            [self.T("이익 기준", "Earnings basis"), self.T(f"FY2025A 순이익률 {self.pct(f.assumptions['npm'].value)} = 4년 중 최고", f"FY2025A net margin {self.pct(f.assumptions['npm'].value)} = highest in 4 years"),
             self.T("LTM 실적·수주잔고 마진으로 정점 여부 점검", "Check LTM results and backlog margins for a peak"), "2, 5"],
            [self.T("할인율", "Discount"), (self.T(f"현재 기준 {self.disc_text()} · 이중 고점 {self.bd_text(f.band_dp)}", f"Current {self.disc_text()} · double peak {self.bd_text(f.band_dp)}")
                                          if has_dp else self.disc_text()) if ok(f.band) else "—",
             self.T("국내 IPO 할인율 분포와 대조(증권신고서)", "Compare with Korean IPO prospectus discounts"), "6, 7"],
            [self.T("공모가 결정 위치", "Final pricing"), self.T(f"2025년 밴드 안 결정 {self.pct(inb, 0)}, 하반기 최상단 {self.pct(top, 0)}", f"2025: {self.pct(inb, 0)} within range, {self.pct(top, 0)} of H2 at the top")
             if inb is not None and top is not None else "—",
             self.T("밴드 상단 = 사실상 공모가 → 상단가 할인율을 기준으로 설계", "Range top ≈ final price → design around the top's discount"), "8"],
            [self.T("구주매출 · 오버행", "Secondary · overhang"), self.T(f"구주 {self.pct(f.val.shares.old / f.val.shares.offered, 0)} · 기존 주주 {self.pct(f.val.shares.overhang / f.val.shares.post, 0)}",
                                                                     f"Secondary {self.pct(f.val.shares.old / f.val.shares.offered, 0)} · existing {self.pct(f.val.shares.overhang / f.val.shares.post, 0)}") if ok(f.val) else "—",
             self.T("최대주주 보호예수·기관 확약 비율(2025년 41%)", "Major-holder lock-up; institutional commitments (41% in 2025)"), "6"],
        ]
        c1 = Cell(title=self.T("ECM 체크리스트: 배수보다 '어느 이익에 어느 배수를 얼마나 할인하나'가 먼저", "ECM checklist: which earnings, which multiple, and how much discount"),
                  src=["fss", "ksj"], table=TableSpec([self.T("항목", "Item"), self.T("이번 분석", "This note"), self.T("실제 딜에서 확인할 것", "Check in a real deal"), self.T("근거 쪽", "Pages")],
                                                      rows, [0.15, 0.36, 0.37, 0.12], ["L", "L", "L", "C"], shade_rows={2, 3}, gold_cells={(3, 1)}, font_size=7.8),
                  note=self.T("가상 기업 기준의 점검 항목. 숫자는 본문 계산값, 공모가 결정 위치는 금융감독원 발표(머니투데이 2026-03-04)",
                              "Checklist for the hypothetical company; figures from the body; final-pricing data from an FSS release (Money Today, 4 Mar 2026)"))
        lim = [self.T("Target Co.는 가상 기업: 규모·주식수·공모 구조는 설계값, 성장률·이익률은 국내 비교기업 합산값", "Target Co. is hypothetical: size, shares and structure are design values; growth and margins are Korean peer aggregates")]
        if mu and mu.applied_group == "domestic":
            lim.append(self.T("미국 피어 시총 미수집 → 적용 배수는 국내만", "U.S. caps not collected → applied multiple is Korea only"))
        if held:
            lim.append(self.T(f"{held}는 10-K 주석 확인 전 보류 — 확인 후 편입하면 해외 핵심 배수가 바뀐다", f"{held} held until its 10-K notes are checked; including it changes the U.S. core multiple"))
        if ok(f.peers) and f.peers.ev_basis == "EBIT":
            lim.append(self.T("국내 D&A 일부 미수집 → EV/EBITDA 대신 EV/EBIT(보조)", "Some Korean D&A missing → EV/EBIT instead of EV/EBITDA (secondary)"))
        lim += [self.T("이익은 FY2025A(약 10개월 전 마감) — LTM이면 배수·이익 모두 바뀐다", "Earnings are FY2025A (~10 months old); LTM would change multiple and earnings"),
                self.T("순이익률 분포(최빈 = 4년 평균)·상관 0·밴드 분위(P25~P50)·정상화 50%는 저자 판단 — 동조 민감도와 함께 공개", "Margin distribution (mode = 4-yr average), zero correlation, range quantiles and the 50% reversal are judgments — shown with a co-move sensitivity")]
        if not ok(f.ipo):
            lim.append(self.T("국내 IPO 할인율 실증(증권신고서) 미수집 → 밴드는 몬테카를로 분위", "Korean IPO discount evidence not yet collected → range from Monte Carlo quantiles"))
        c2 = Cell(title=self.T("이 노트의 한계", "Limitations of this note"), bullets=lim, note=self.T("데이터가 들어오는 대로 같은 코드로 갱신", "Updated with the same code as data arrive"))
        c3 = Cell(title=self.T("Vol.4 예고: 데이터센터 전력 공급 — 발전 자산·PPA", "Next in Vol.4: powering data centres — generation assets and PPAs"),
                  panel_lead=self.T("전력기기 다음은 전기 그 자체: 누가 데이터센터에 전력을 팔고, 어떤 계약으로 묶나?", "After equipment, the power itself: who sells electricity to data centres, and under what contracts?"),
                  bullets=[self.T("발전사업자(Constellation·Vistra: 이번 편 참고 비교군)의 가치평가와 PPA 구조", "Valuing generators (Constellation, Vistra — this volume's reference peers) and PPA structures"),
                           self.T("PPA 가격·기간이 Vol.2 PF의 전력비·대출 한도에 주는 영향", "How PPA price and tenor feed Vol.2's power cost and debt capacity"),
                           self.T("Vol.5 완결: AI 에너지 자산 투자 지도 — 수요·기기·PF·IPO·발전을 한 장에", "Vol.5 finale: an AI energy asset investment map — demand, equipment, PF, IPO and generation on one page")],
                  note=self.T("Vol.4·Vol.5 일정·방법은 변경될 수 있음", "Timing and method of Vol.4–5 may change"))
        grid = self.v["discount_grid"]
        if has_dp:
            mc, dp, b, bd = f.mc, f.mc_dp, f.band, f.band_dp
            bl = [self.T(f"현재 기준 밴드 {self.band_text()}(할인율 {self.disc_text()}) vs 이중 고점 반영 {self.won_rng(bd.low, bd.high)}(할인율 {self.bd_text(bd)})",
                         f"Current-basis range {self.band_text()} ({self.disc_text()} discount) vs double-peak {self.won_rng(bd.low, bd.high)} ({self.bd_text(bd)})")]
            if self.f.dp_floor_alt:
                bl.append(self.T(f"이익률 하한 가정: {self.floor_text()} — 하한을 바닥(FY2022A)으로 두면 시나리오 상단 {grid[-1] * 100:.0f}%를 넘고, 한 해 뒤로 옮기면 그 안에 들어온다",
                                 f"Margin-floor assumption: {self.floor_text()} — the cycle trough (FY2022A) puts it above the {grid[-1] * 100:.0f}% grid top; one year later puts it inside"))
            if not self.dp_covered():
                bl.append(self.T(f"이중 고점의 중앙값 손익분기 할인율 {self.pct(dp.required[0.5], 0)} > 시나리오 상단 {grid[-1] * 100:.0f}% — 할인율 {grid[-1] * 100:.0f}%에서도 1년 후 손실 확률 {self.pct(dp.loss_grid[grid[-1]], 0)}: 할인율만으로는 덮이지 않는다",
                                 f"The double-peak median break-even discount of {self.pct(dp.required[0.5], 0)} exceeds the {grid[-1] * 100:.0f}% grid top — even at {grid[-1] * 100:.0f}% the 1-yr loss probability is {self.pct(dp.loss_grid[grid[-1]], 0)}: a discount alone does not cover it"))
            else:
                bl.append(self.T(f"이중 고점까지 덮으려면 중앙값 기준 할인율 {self.pct(dp.required[0.5], 0)} — 현재 기준보다 {(dp.required[0.5] - mc.required[0.5]) * 100:.0f}%p 더",
                                 f"Covering the double peak takes a {self.pct(dp.required[0.5], 0)} median discount — {(dp.required[0.5] - mc.required[0.5]) * 100:.0f}pp more than the current basis"))
            if inb is not None and top is not None:
                bl.append(self.T(f"2025년 IPO는 {self.pct(inb, 0)}가 밴드 안, 하반기 {self.pct(top, 0)}가 최상단에서 결정 — 실제 할인율은 상단가 할인율({self.pct(b.d_low, 0)})에 가깝다",
                                 f"In 2025 {self.pct(inb, 0)} of IPOs priced within the range and {self.pct(top, 0)} of H2 at the top — the effective discount is the top's ({self.pct(b.d_low, 0)})"))
            bl.append(self.T("할인율 밖의 위험은 구조로: 이익률 지속성 근거(수주잔고·장기 계약) 공시, 구주매출 축소, 최대주주·기관 보호예수",
                             "Risk the discount cannot carry goes into structure: evidence of margin durability (backlog, long-term contracts), less secondary sale, lock-ups"))
            c4 = Cell(title=self.T("결론: 할인율이 덮는 것은 배수 고점, 이익률 고점은 구조와 공시로", "Conclusion: the discount covers the peak multiple; the peak margin needs structure and disclosure"),
                      bullets=bl, src=["fss", "ksj"], note=self.T("몬테카를로(p7) 계산값 · 공모가 결정 위치는 금융감독원 발표(머니투데이 보도)", "From the Monte Carlo (p7) · pricing positions from an FSS release (via Money Today)"))
            title = (self.T(f"시사점: 이중 고점 위험은 이익률 하한 가정이 좌우한다({self.floor_text(True)}) — 할인율과 함께 이익 지속성 공시·공모 구조가 가야 한다",
                            f"Implication: the double-peak risk hinges on the margin floor ({self.floor_text(True)}) — earnings-durability disclosure and deal structure must back the discount")
                     if self.f.dp_floor_alt else
                     self.T(f"시사점: 이중 고점은 할인율 {grid[0] * 100:.0f}~{grid[-1] * 100:.0f}%로 덮이지 않는다 — 이익 지속성과 공모 구조가 함께 가야 한다",
                            f"Implication: a double peak (peak earnings × peak multiple) is not covered by a {grid[0] * 100:.0f}–{grid[-1] * 100:.0f}% discount alone — earnings durability and deal structure must do the rest")
                     if not self.dp_covered() else
                     self.T(f"시사점: 이중 고점까지 덮으려면 할인율 {self.pct(dp.required[0.5], 0)} 이상 — 배수만 보는 할인율({self.pct(mc.required[0.5], 0)})은 부족하다",
                            f"Implication: covering the double peak takes a {self.pct(dp.required[0.5], 0)}+ discount — a multiple-only discount ({self.pct(mc.required[0.5], 0)}) falls short"))
        elif ready:
            mc, req = f.mc, f.mc.required
            c4 = Cell(title=self.T("결론: 사이클 고점 위험은 할인율로 얼마나 반영해야 하나", "Conclusion: how much discount for cycle-peak risk?"),
                      bullets=[self.T(f"중앙값 손익분기 할인율 {self.pct(req[0.5], 0)}, 하위 25%까지 {self.pct(req[0.25], 0)}", f"Median break-even {self.pct(req[0.5], 0)}; 25th percentile {self.pct(req[0.25], 0)}")],
                      note=self.T("몬테카를로(p7) 계산값", "From the Monte Carlo (p7)"))
            title = self.T(f"시사점: 정점 배수는 할인율 {self.pct(req[0.5], 0)}~{self.pct(req[0.25], 0)}로 되돌려 정한다", f"Implication: unwind the peak multiple with a {self.pct(req[0.5], 0)}–{self.pct(req[0.25], 0)} discount")
        else:
            c4 = self.pending(self.T("결론", "Conclusion"), ["ksj"], self.T("몬테카를로 계산 후", "After the Monte Carlo"))
            title = self.T("시사점: 데이터 확인 후", "Implications: after data")
        sub = self.T("결론(할인율로 덮이는 위험 vs 덮이지 않는 위험) · ECM 체크리스트 · 한계 · Vol.4 예고(데이터센터 전력 공급)",
                     "Conclusion (risks a discount covers vs does not) · ECM checklist · limitations · next: Vol.4 (data-centre power supply)")
        ic = self.ipo_cell("p8")
        if ic is not None:
            return Page("body", "8", title, sub, [c4, ic, c3, c1, c2], grid="3-2")
        return Page("body", "8", title, sub, [c4, c1, c3, c2])

    # --- Appendix ------------------------------------------------------------
    def a1(self) -> Page:
        f = self.f
        qa = []
        if self.ok_all:
            mu, t, v, mc = f.mult, f.peers.table, f.val, f.mc
            dom = mu.groups["domestic"]["current"]
            hf = self.high_flag_rows()
            if not hf.empty:
                r = hf.iloc[0]
                rest = t[(t["group"] == "domestic") & (t["status"] == "applied") & ~t["high_flag"]]
                ex_agg = rest["mcap1"].sum() / rest["ni1"].sum() if len(rest) else float("nan")
                qa.append([self.T(f"{r['company']} PER {self.x(r['per1'])}는 빼야 하지 않나?", f"Shouldn't {r['company_en']} at {self.x(r['per1'])} be dropped?"),
                           self.T(f"중앙값의 2배 초과라 표시(R4)했다. 합산 PER은 이익 가중이라 산술평균({self.x(dom.mean)})보다 덜 흔들리지만, 포함 {self.x(dom.aggregate)} vs 제외 {self.x(ex_agg)}로 여전히 민감하다 — 제외 여부는 판단이며 결과를 함께 공개",
                                  f"Flagged (R4, > 2x median). The earnings-weighted aggregate moves less than a simple mean ({self.x(dom.mean)}) but is still sensitive: {self.x(dom.aggregate)} with vs {self.x(ex_agg)} without — dropping it is a judgement, shown both ways"), "4"])
            dx = self.excluded_dom()
            if not dx.empty:
                r = dx.iloc[0]
                qa.append([self.T(f"{r['company']}는 왜 제외했나?", f"Why is {r['company_en']} excluded?"),
                           self.T(f"PER {self.x(r['per1'], 0)}(FY2025A 지배순이익 {self.eok(r['ni1'])})로 분모 왜곡(R2)이고, 원전·가스터빈 중심이라 배전·UPS와 사업 유사성도 낮다",
                                  f"P/E {self.x(r['per1'], 0)} (NI {self.eok(r['ni1'])}) is a denominator distortion (R2), and its nuclear/gas-turbine mix fits poorly"), "3"])
            qa.append([self.T("왜 PER이 주 지표이고 EV/EBITDA는 보조인가?", "Why P/E first and EV/EBITDA second?"),
                       self.T(f"공모가는 주주 가치(지배순이익)로 정하고, 순차입금·D&A 데이터가 일부 비어 있다. EV/{f.peers.ev_basis}는 PER 기준 대비 {self.pct(v.ev_per_share / v.per_share['current'] - 1, 0, True)}지만 {self.ev_ref_reason()}"
                              if v.ev_per_share else "공모가는 주주 가치(지배순이익)로 정하고, 순차입금·D&A 데이터가 일부 비어 있다",
                              f"IPO prices are set on equity value (NI to parent), and net-debt/D&A data are incomplete. EV/{f.peers.ev_basis} is {self.pct(v.ev_per_share / v.per_share['current'] - 1, 0, True)} vs P/E — {self.ev_ref_reason()}"
                              if v.ev_per_share else "IPO prices are set on equity value, and net-debt/D&A data are incomplete"), "4"])
            ms = self.margin_sens()
            if ms is not None:
                qa.append([self.T("Target 이익률을 3사 합산으로 둔 게 맞나?", "Is the 3-name margin right for Target?"),
                           self.T(f"가장 공격받을 가정이다. 3사 합산 순이익률 {self.pct(self.f.assumptions['npm'].value)}는 {ms['top']}(순이익률 {self.pct(ms['top_npm'])})이 끌어올린 값이다. 제품이 가장 가까운 {ms['company']}의 FY2025A 순이익률 {self.pct(ms['npm'])}를 쓰면 "
                                  f"주당 평가가액 {self.won(ms['value'])}, 밴드 {self.won_rng(ms['low'], ms['high'])}({self.pct(ms['chg'], 0, True)}) — 배수·할인율·주식수는 그대로",
                                  f"It is the most contestable input. The 3-name net margin {self.pct(self.f.assumptions['npm'].value)} is lifted by {ms['top']} ({self.pct(ms['top_npm'])}). With the closest product peer's ({ms['company']}) FY2025A margin {self.pct(ms['npm'])}, "
                                  f"value per share is {self.won(ms['value'])} and the range {self.won_rng(ms['low'], ms['high'])} ({self.pct(ms['chg'], 0, True)}) — multiple, discount and shares unchanged"), "2, 6"])
            held = t[t["status"] == "held"]
            if not held.empty:
                r = held.iloc[0]
                cw = self.core_with_held()
                qa.append([self.T(f"{r['company']}는 왜 빼나?", f"Why is {r['company_en']} left out?"),
                           self.T(f"{' · '.join(self.hold_reasons(r))} — 10-K 주석 확인 전 보류(표에는 유지). 포함하면 해외 핵심 {self.x(cw)} vs 제외 {self.x(mu.groups['core']['current'].aggregate)}",
                                  f"{'; '.join(self.hold_reasons(r))} — held until the 10-K notes are checked (kept in tables). Including it: U.S. core {self.x(cw)} vs {self.x(mu.groups['core']['current'].aggregate)} without"), "3, 4"])
            else:
                qa.append([self.T("미국 피어를 섞으면 결과가 바뀌나?", "Does adding U.S. peers change the answer?"),
                           self.T(f"해외 핵심 {self.x(mu.groups['core']['current'].aggregate)}를 국내와 그룹 평균해 적용 {self.x(self.per())}",
                                  f"U.S. core at {self.x(mu.groups['core']['current'].aggregate)} is averaged with Korea for {self.x(self.per())}"), "3, 4"])
            qa.append([self.T("Constellation·Vistra는 왜 참고 비교군인가?", "Why are Constellation and Vistra only references?"),
                       self.T("전력을 파는 발전·유틸리티 사업이라 이익이 전력 가격·PPA에 달리고, 자산·차입이 커서 PER·EV 구조가 전력기기 제조사와 다르다(p3 순차입금 ÷ 매출)",
                              "They sell power: profits depend on prices and PPAs, and heavy assets and debt make P/E and EV behave unlike equipment makers (p3 net debt ÷ revenue)"), "3"])
            hist = f.der.hist if f.der else {}
            g = self.v["discount_grid"]
            dp = f.mc_dp if ok(f.mc_dp) else None
            if hist and dp is not None:
                y0, y1 = min(hist), max(hist)
                qa.append([self.T("피어 정점 이익률을 그대로 쓴 것은 공격적이지 않나?", "Isn't using peak peer margins aggressive?"),
                           self.T(f"그래서 순이익률을 FY{y0}A {self.pct(hist[y0]['npm'])}~FY{y1}A {self.pct(hist[y1]['npm'])} 분포로 다시 돌렸다(이중 고점): 필요 할인율 {self.pct(mc.required[0.5], 0)} → {self.pct(dp.required[0.5], 0)}(P50). 정상화 이익 × 정상화 배수면 주당 {self.won(v.nn['per_share'])}",
                                  f"So the margin was re-run across FY{y0}A {self.pct(hist[y0]['npm'])}–FY{y1}A {self.pct(hist[y1]['npm'])} (double peak): needed discount {self.pct(mc.required[0.5], 0)} → {self.pct(dp.required[0.5], 0)} (P50). Normalised earnings × multiple gives {self.won(v.nn['per_share'])}")
                           if v.nn else "—", "5, 7"])
                qa.append([self.T(f"그럼 할인율을 {self.pct(dp.required[0.5], 0)}로 올리면 되나?", f"Then why not a {self.pct(dp.required[0.5], 0)} discount?"),
                           self.T(f"이중 고점에서는 할인율 {g[-1] * 100:.0f}%에서도 1년 후 손실 확률 {self.pct(dp.loss_grid[g[-1]], 0)}(현재 기준 {self.pct(mc.loss_grid[g[-1]], 0)}). 시나리오 밖 할인은 발행사가 받기 어렵고, 2025년 공모가는 밴드 최상단에 몰린다 — 이익률 지속성 공시·구주매출 축소·보호예수로 나눠 져야 한다",
                                  f"With a double peak, even a {g[-1] * 100:.0f}% discount leaves a {self.pct(dp.loss_grid[g[-1]], 0)} 1-yr loss probability (current basis {self.pct(mc.loss_grid[g[-1]], 0)}). Issuers rarely accept discounts beyond the grid and 2025 pricing clustered at the top — the rest is carried by margin disclosure, smaller secondary and lock-ups"), "7, 8"])
            else:
                qa.append([self.T(f"할인율 {self.disc_text()}는 과도하지 않나?", f"Isn't a {self.disc_text()} discount excessive?"),
                           self.T(f"할인율 {g[0] * 100:.0f}%면 1년 후 손실 확률 {self.pct(mc.loss_grid[g[0]], 0)}", f"At {g[0] * 100:.0f}% the 1-yr loss probability is {self.pct(mc.loss_grid[g[0]], 0)}"), "7"])
            sh = v.shares
            qa.append([self.T("구주매출과 오버행은 어떻게 보나?", "How should the secondary sale and overhang be read?"),
                       self.T(f"공모의 {self.pct(sh.old / sh.offered, 0)}가 구주(공모 후 {self.pct(sh.old / sh.post, 1)}). 기존 주주 잔여 {self.pct(sh.overhang / sh.post, 0)}는 보호예수 해제 시 잠재 매도 물량" + self.lockup_fact().replace(". 참고: ", " — "),
                              f"{self.pct(sh.old / sh.offered, 0)} of the offer is secondary ({self.pct(sh.old / sh.post, 1)} of post-IPO). Existing holders' {self.pct(sh.overhang / sh.post, 0)} is overhang once lock-ups end" + self.lockup_fact().replace(". Ref.: ", " — ")), "6"])
        while len(qa) < 8:
            qa.append([self.T("데이터 확인 후 생성", "Generated once data are in"), "—", "—"])
        qa = qa[:10]
        cell = Cell(title=self.T(f"ECM 실무에서 나올 질문 {len(qa)}개와 답", f"{len(qa)} questions an ECM desk would ask"), src=["dart", "krx", "sec", "fss", "ksj"],
                    table=TableSpec([self.T("질문", "Question"), self.T("답 (본문 계산값)", "Answer (from the body)"), self.T("쪽", "p.")], qa,
                                    [0.28, 0.64, 0.08], ["L", "L", "C"], font_size=7.4),
                    note=self.T("답의 숫자는 모두 본문과 같은 계산에서 생성", "All figures in the answers come from the same calculations as the body"))
        return Page("full", "A1", self.T("예상 질의응답: 배수·할인율·구조에 대한 질문", "Q&A: questions on the multiple, the discount and the structure"),
                    self.T("공모 주관 실무(밸류에이션·투자설명서·IR)에서 나올 질문과 근거 쪽수", "Questions likely in deal work (valuation, prospectus, investor meetings), with page references"),
                    [cell], grid="1x1")

    def ni_fallback_note(self) -> str:
        """DART 지배순이익 계정이 없어 당기순이익(총계)으로 대체한 회사·연도 (없으면 빈 문자열)."""
        from . import data as d3
        out = []
        en = {str(q["ticker"]).zfill(6): q.get("name_en", q["name"]) for q in self.cfg["peers"]["domestic"]}
        for path in d3._inp(self.cfg, "dart"):
            df = d3._read(path)
            if df is None or "flags" not in df:
                continue
            for _, r in df[df["flags"].astype(str).str.contains("net_income:fallback")].iterrows():
                out.append(f"{r['company'] if self.kr else en.get(str(r['ticker']).zfill(6), r['company'])} {r['fiscal_year']}")
        if not out:
            return ""
        return self.T(f" {', '.join(out)} 순이익은 지배순이익 계정이 공시에 없어 연결 당기순이익(비지배지분 포함)으로 대체.",
                      f" {', '.join(out)}: no NI-to-parent line in the filing; consolidated net income (incl. minorities) used.")

    def short_source(self, a) -> str:
        """가정표 출처 칸: 입력 CSV의 짧은 출처(source_short·source_short_en)만 — 긴 근거는 CSV에 그대로. 값이 없으면 처리 규칙 문장."""
        if a.value is None:
            return self.source_text(a)
        s_ = a.source_short if self.kr else a.source_short_en
        return s_ or self.source_text(a)

    def source_text(self, a: Assumption) -> str:
        if a.value is None:
            return (MISSING_KR if self.kr else MISSING_EN).get(a.key, self.T("근거 확인 중", "Being sourced"))
        if self.kr:
            return (a.source or "") + (f" · {a.published}" if a.published else "")
        if a.origin == "csv":
            return "User input" + (f"; {a.source}" if a.source and not re.search(r"[가-힣]", a.source) else "")
        if a.origin == "evidence" and ok(self.f.ipo):
            s_ = self.f.ipo.sample
            return (f"DART equity prospectuses (new listings), {'sub-sample' if self.f.ipo.chosen == 'sub' else 'full sample'} n={s_.n}: "
                    f"median discount (range = interquartile), filed {s_.period[0]} to {s_.period[1]}")
        return SOURCE_EN.get(a.key, "Public source")

    def a2(self) -> Page:
        a = self.f.assumptions
        keys = list(a.keys())
        st = A_STATUS_KR if self.kr else A_STATUS_EN
        rows, brick, shade, gold, strong = [], set(), set(), set(), set()
        for i, k in enumerate(keys):
            x = a[k]
            rng_ = ""
            if x.low is not None and x.high is not None and x.unit == "%":
                rng_ = f" ({x.low * 100:.1f}~{x.high * 100:.1f})" if self.kr else f" ({x.low * 100:.1f}–{x.high * 100:.1f})"
            unit = x.unit if self.kr else UNIT_EN.get(x.unit, x.unit)
            if k in ("growth_mean", "growth_sd"):
                unit = self.T("로그", "log")
            rows.append([self.lab(k), self.fmt_assump(x) + rng_, unit, self.short_source(x), st[x.status]])
            if x.status == "input":
                brick.add((i, 4))
            elif x.status in ("sourced", "data"):
                gold.add((i, 4))
            elif x.status == "judgment":
                strong.add((i, 4))
                shade.add(i)
        cnt = {s: sum(a[k].status == s for k in keys) for s in ("data", "sourced", "judgment", "input", "verify", "design", "neutral")}
        cell = Cell(title=self.T(f"가정 {len(keys)}개: 데이터 {cnt['data']} · 근거 있음 {cnt['sourced']} · 원문 확인 {cnt['verify']} · 설계값 {cnt['design']} · 저자 판단 {cnt['judgment']} · 중립값 {cnt['neutral']} · 입력 필요 {cnt['input']}",
                                 f"{len(keys)} inputs: data {cnt['data']} · sourced {cnt['sourced']} · verify {cnt['verify']} · design {cnt['design']} · judgment {cnt['judgment']} · neutral {cnt['neutral']} · needed {cnt['input']}"),
                    src=["dart", "ipo", "fss", "law", "ksj"],
                    table=TableSpec([self.T("항목", "Item"), self.T("값 (범위)", "Value (range)"), self.T("단위", "Unit"), self.T("근거·출처", "Basis / source"), self.T("상태", "Status")],
                                    rows, [0.2, 0.14, 0.07, 0.48, 0.11], ["L", "R", "C", "L", "C"], shade_rows=shade, brick_cells=brick, gold_cells=gold,
                                    strong_cells=strong, font_size=7.4),
                    note=self.T("상태(Vol.2와 같은 구분): 데이터·근거 있음(골드) = DART 계산·공개 출처 · 저자 판단(음영·브라운) = 출처 없는 설정, 민감도로 점검 · 입력 필요(적색) = 미입력, 대체 규칙 적용 · "
                                "원문 확인 = 법령 등 공개 근거, 원문 대조 전 · 설계값 = 가상 기업·거래 설정 · 중립값 = 근거 부재 시 중립 형태",
                                "Status (same as Vol.2): data/sourced (gold) = DART or public source · judgment (shaded, brown) = unsourced setting, stress-tested · needed (red) = not set, fallback rule · "
                                "verify = public basis, not yet checked · design = hypothetical setting · neutral = neutral shape without evidence"))
        return Page("full", "A2", self.T("가정과 출처: 데이터·근거·판단·설계값을 구분", "Assumptions and sources: data, sourced, judgment and design kept apart"),
                    self.T("Target Co.·공모 구조·몬테카를로 입력 — 값, 피어 범위, 근거, 상태", "Target Co., deal structure and Monte Carlo inputs — value, peer range, basis, status"), [cell], grid="1x1")

    def a3(self) -> Page:
        f = self.f
        rows = [[s["org_kr"] if self.kr else s["org_en"], s["ds_kr"] if self.kr else s["ds_en"], s["as_of"] or "—",
                 self.T("수집 완료", "Collected") if s["ok"] else self.T("미수집", "Not collected")] for s in f.sources]
        pend = {i for i, s in enumerate(f.sources) if not s["ok"]}
        c1 = Cell(title=self.T(f"데이터 소스 {len(rows)}개 중 {len(rows) - len(pend)}개 수집 — 미국 시총·D&A는 수집 후 같은 코드로 갱신" if pend else "데이터 소스 · 통계 · 기준일",
                               f"{len(rows) - len(pend)} of {len(rows)} sources collected — U.S. caps and D&A update with the same code" if pend else "Data sources · datasets · dates"),
                  table=TableSpec([self.T("소스", "Source"), self.T("통계·항목", "Dataset / items"), self.T("기준일", "As of"), self.T("상태", "Status")], rows,
                                  [0.2, 0.5, 0.14, 0.16], ["L", "L", "C", "C"], shade_rows=pend, brick_cells={(i, 3) for i in pend}, font_size=8.0),
                  note=self.T("소스 우선순위: 공식 공시(DART·SEC) > 공공기관(KRX·ECOS) > 보조 라이브러리(yfinance, SEC 주식수로 교차 확인)",
                              "Priority: official filings (DART, SEC) > public agencies (KRX, ECOS) > secondary libraries (yfinance, cross-checked with SEC shares)"))
        erows = []
        for x in f.entity:
            same = str(x.get("same_consolidated", ""))
            erows.append([x.get("company", ""), x.get("ticker", ""), str(x.get("listed_cik", "")).split(".")[0].zfill(10), str(x.get("entity_name", "")),
                          same, (x.get("auto_verdict") + " → " if x.get("auto_verdict") and x.get("auto_verdict") != x.get("verdict") else "") + str(x.get("verdict", ""))])
        warn = [x for x in f.entity if str(x.get("verdict", "")).upper() == "WARN"]
        man = [x for x in f.entity if x.get("manual_check")]
        mnames = ", ".join(x["company"] for x in man)
        mnote_kr = "".join(f" {x['company']} 근거: {x.get('manual_url', '')} (확인일 {x.get('verified_on', '')})" for x in man)
        mnote_en = "".join(f" {x['company']} source: {x.get('manual_url', '')} (checked {x.get('verified_on', '')})" for x in man)
        c2 = Cell(title=self.T(f"SEC 재무 주체 검사 {len(erows)}개사 — WARN {len(warn)}개" + (f", {mnames}는 10-K 표지 registrant 수동 확인으로 OK" if man else ""),
                               f"SEC entity check, {len(erows)} names — {len(warn)} WARN" + (f"; {mnames} OK after checking the 10-K cover registrant" if man else "")),
                  src=["sec"],
                  table=TableSpec([self.T("회사", "Company"), self.T("티커", "Ticker"), self.T("상장사 CIK", "Listed CIK"), self.T("재무 법인명(companyfacts)", "Filer name (companyfacts)"),
                                   self.T("같은 연결", "Same group"), self.T("판정", "Verdict")], erows, [0.18, 0.08, 0.14, 0.32, 0.12, 0.16],
                                  ["L", "C", "C", "L", "C", "C"], font_size=8.0),
                  note=self.T("시총은 상장사(company_tickers 티커) 기준, 재무는 companyfacts 법인 기준 — 다르면 배수에서 제외(R3). 수동 확인은 근거 URL·확인일과 함께 기록, 자동 판정은 보존." + mnote_kr,
                              "Market cap follows the listed entity (ticker map), financials the companyfacts filer — a mismatch drops the multiple (R3). Manual checks are recorded with URL and date; the automatic verdict is kept." + mnote_en)
                  ) if erows else self.pending(self.T("SEC 재무 주체 검사", "SEC entity check"), ["sec"], self.T("SEC 수집 후", "After SEC collection"))
        pit = self.pit_line()
        if pit:
            c1.note = c1.note + " " + pit
        return Page("full", "A3", self.T("데이터 노트: 출처·기준일과 SEC 재무 주체 검사", "Data notes: sources, dates and the SEC entity check"),
                    self.T(f"시리즈 기준일 {f.as_of} · 국내 KRX {f.peers.t1 if ok(f.peers) else '—'} · SEC {f.ovs.sec_as_of if ok(f.ovs) else '—'} · 원/달러 {f.fx:,.1f} ({f.fx_date})" if f.fx else f"시리즈 기준일 {f.as_of}",
                           f"Series as-of {f.as_of} · KRX {f.peers.t1 if ok(f.peers) else '—'} · SEC {f.ovs.sec_as_of if ok(f.ovs) else '—'} · USD/KRW {f.fx:,.1f} ({f.fx_date})" if f.fx else f"Series as-of {f.as_of}"),
                    [c1, c2], grid="2x1")

    def pit_line(self) -> str:
        """검증 사례 한 줄: DART corp_cls(현재 상태)로 IPO를 고르면 생기는 look-ahead bias와 처리."""
        ev = self.f.ipo
        if not ok(ev):
            return ""
        if ev.pit:
            return self.T(f"검증 사례: DART 회사구분(corp_cls)은 현재 상장 상태라 IPO 필터로 쓰면 이후 상장한 회사가 빠진다(시점 착오) → 접수 시점 판정(상장일 > 접수일 · 원문 IPO 문구)으로 {ev.n_restored}건 복원.",
                          f"Check: DART corp_cls is today's listing status, so filtering on it drops firms that listed later (look-ahead) → classified at filing date (listing date > filing date, IPO wording); {ev.n_restored} filings restored.")
        if ev.n_cls_excluded:
            return self.T(f"검증 사례: 현재 표본은 DART 회사구분(corp_cls, 현재 상장 상태)으로 걸러 이후 상장한 회사의 신고서 {ev.n_cls_excluded:,}건이 빠짐(시점 착오) → 접수 시점 판정으로 재수집 예정.",
                          f"Check: the current sample filters on DART corp_cls (today's status), dropping {ev.n_cls_excluded:,} filings by firms that listed later (look-ahead) → to be re-collected with filing-date classification.")
        return ""

    BUILT_WITH_KR = "구현: AI 코딩 도구(Claude Code)로 데이터 연결·배수 계산·몬테카를로·보고서 생성 코드를 작성. 질문 설계, 비교기업·가정 판단, 숫자 검증은 저자."
    BUILT_WITH_EN = "Built with an AI coding tool (Claude Code) for data links, multiples, Monte Carlo and report generation; question design, peer and assumption judgments and number checks by the author."

    def a4(self) -> Page:
        steps = [(self.T("1. 데이터", "1. Data"), ["DART · KRX", "SEC EDGAR", self.T("yfinance(보조)", "yfinance (sec.)"), self.T("주체·주식수 검산", "Entity, share checks")]),
                 (self.T("2. 배수", "2. Multiples"), [self.T("3단계 선정", "3-step screen"), self.T("합산·평균·중앙값", "Agg., mean, median"), self.T("이상치 R1~R5", "Outliers R1–R5"), self.T("시나리오 3개", "3 scenarios")]),
                 (self.T("3. 공모가", "3. Price"), [self.T("적정 시총", "Equity value"), self.T("공모 후 주식수", "Post-IPO shares"), self.T("할인율 격자", "Discount grid"), self.T("민감도", "Sensitivity")]),
                 (self.T("4. 검증·보고서", "4. Checks, report"), [self.T("몬테카를로 seed·수렴", "MC seed, convergence"), self.T("배수·단위·환율 검산", "Multiple, unit, FX checks"),
                                                               self.T("결론형 제목", "Conclusion titles"), self.T("국문·영문", "Korean & English")])]
        url = self.cfg["research"]["repo_url"]
        c1 = Cell(title=self.T("데이터 → 배수 → 공모가 → 검증·보고서", "Data → multiples → price → checks and report"), src=["ksj"], chart_key="method",
                  chart=charts.flow4(steps, self.c), strip=self.T(self.BUILT_WITH_KR, self.BUILT_WITH_EN),
                  note=self.T(f"시점 원칙: 표본 선정은 그 시점에 알 수 있던 정보로만 — IPO 여부는 현재 상장 상태(DART corp_cls)가 아니라 신고서 접수 시점(상장일 > 접수일 · 원문의 희망공모가·수요예측 문구)으로 판정. 전체 코드·데이터 출처: GitHub {url}",
                              f"Point-in-time rule: samples use only what was knowable then — an IPO is judged at the filing date (listing date > filing date, range and book-building wording), not by today's DART corp_cls. Full code and data sources: GitHub {url}"))
        return Page("full", "A4", self.T("분석 방법: 같은 규칙을 모든 피어·시점에, 결론은 계산에서", "Methodology: one rule set for every peer and date; conclusions from the numbers"),
                    self.T("모든 숫자는 데이터와 가정에서 계산하고, 결론 문장도 계산 결과로 만든다", "Every figure is calculated from data and assumptions, and conclusions are generated from the results"),
                    [c1], grid="1x1")

    def a5(self) -> Page:
        terms = [
            ("PER", self.T("주가수익비율 = 시가총액 ÷ 지배주주 순이익. 공모가 산정의 주 지표", "Price-to-earnings = market cap ÷ NI to parent; the main IPO metric")),
            (self.T("합산 PER", "Aggregate P/E"), self.T("Σ시가총액 ÷ Σ순이익 — 이익 가중 평균. 작은 이익의 고배수 영향을 줄인다", "Σcap ÷ ΣNI — an earnings-weighted average that damps high multiples on small profits")),
            ("EV/EBITDA", self.T("기업가치(시총 + 순차입금) ÷ 상각 전 영업이익. 자본구조 차이를 줄인 보조 지표", "Enterprise value (cap + net debt) ÷ EBITDA; a capital-structure-neutral cross-check")),
            ("EV/EBIT", self.T("D&A가 없을 때의 대용: EV ÷ 영업이익 (EV/EBITDA보다 높게 나온다)", "Proxy without D&A: EV ÷ operating income (higher than EV/EBITDA)")),
            (self.T("주당 평가가액", "Value per share"), self.T("적정 시총 ÷ 공모 후 주식수 — 할인 전 가격", "Equity value ÷ post-IPO shares — the price before discount")),
            (self.T("할인율", "IPO discount"), self.T("1 − 공모가 ÷ 주당 평가가액. 상장 후 불확실성·유동성에 대한 투자자 보상", "1 − offer price ÷ value per share; compensation for post-listing uncertainty")),
            (self.T("희망공모가 밴드", "Indicative price range"), self.T("수요예측 전에 제시하는 공모가 범위(하단~상단)", "The price range offered before book-building (low–top)")),
            (self.T("신주 · 구주매출", "Primary · secondary"), self.T("신주 = 회사가 새로 발행(자금 유입), 구주매출 = 기존 주주가 파는 주식(자금은 주주에게)", "Primary = new shares (cash to company); secondary = existing holders sell (cash to them)")),
            (self.T("오버행", "Overhang"), self.T("보호예수 해제 후 시장에 나올 수 있는 기존 주주 물량", "Existing holders' shares that may hit the market after lock-ups")),
            (self.T("보호예수(의무보유)", "Lock-up"), self.T("최대주주 등이 상장 후 일정 기간 주식을 팔지 못하게 하는 제도", "A period after listing during which major holders cannot sell")),
            (self.T("비교기업 3단계", "Three-step peer screen"), self.T("업종 → 재무 요건(흑자·배수·주체) → 사업 유사성", "Industry → financial tests (profit, multiple, filer) → business fit")),
            (self.T("사이클 고점", "Cycle peak"), self.T("이익과 배수가 동시에 높은 구간. 이후 이익 둔화와 배수 하락이 겹칠 위험", "Earnings and multiples both high; risk that slowing profits and de-rating coincide")),
            (self.T("몬테카를로", "Monte Carlo"), self.T("입력 분포에서 반복 추출해 결과 분포를 얻는 방법(seed 고정 = 재현 가능)", "Repeated draws from input distributions to get an output distribution (fixed seed = reproducible)")),
            ("P10 · P50 · P90", self.T("결과 분포의 10·50·90번째 백분위 값", "10th, 50th and 90th percentiles of the outcome")),
            (self.T("손실 확률", "Loss probability"), self.T("P(1년 후 주당가치 < 공모가)", "P(1-yr value per share < offer price)")),
            (self.T("이중 고점", "Double peak"), self.T("이익률과 배수가 모두 사이클 정점인 상태 — 정점 이익 × 정점 배수", "Margins and multiples both at a cycle peak — peak earnings × peak multiple")),
            (self.T("의무보유확약", "Lock-up commitment"), self.T("수요예측에 참여한 기관이 배정 주식을 일정 기간 팔지 않겠다고 약속하는 것", "An institution's pledge not to sell allotted shares for a set period")),
        ]
        if ok(self.f.peers) and self.f.peers.ev_basis == "EBITDA":
            terms = [t for t in terms if t[0] != "EV/EBIT"]                 # 대용 지표를 쓰지 않으면 용어에서도 뺀다
        core = {"PER", self.T("주당 평가가액", "Value per share"), self.T("할인율", "IPO discount"), self.T("신주 · 구주매출", "Primary · secondary"), self.T("오버행", "Overhang")}
        cell = Cell(title=self.T("용어 정의", "Glossary"),
                    table=TableSpec([self.T("용어", "Term"), self.T("정의", "Definition")], [list(t) for t in terms], [0.22, 0.78], ["L", "L"],
                                    shade_rows={i for i, t in enumerate(terms) if t[0] in core}, font_size=8.2),
                    note=self.T("음영 = 공모가 산정 핵심 용어", "Shaded = core IPO-pricing terms"))
        return Page("full", "A5", self.T("용어 정의: 공모가를 정하는 말", "Glossary: the language of IPO pricing"),
                    self.T("금액 단위: 원화 억원·원, 달러 USD mn · 비율 %, 배", "Units: KRW 100mn and KRW, USD mn · %, x"), [cell], grid="1x1")
