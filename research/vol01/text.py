"""Vol.1 국문·영문 문구. 숫자는 data.py 결과에서만 가져오고, 서술 방향(앞섬/뒤처짐 등)도 데이터로 결정한다."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .data import Exhibit1, Exhibit2, Exhibit3, Exhibit4, Table1, Unavailable

PENDING = {"kr": "데이터 확인 중", "en": "Data under review"}


def pct(x: float) -> str:
    return f"{x:+.0f}%"


def updown(x: float) -> str:
    """영문 증감 표현: +79 → 'up 79%', -5 → 'down 5%' (부호 중복 'up +79%' 방지)."""
    return f"up {x:.0f}%" if x >= 0 else f"down {abs(x):.0f}%"


def times(x: float, lang: str) -> str:
    return f"{x:.1f}배" if lang == "kr" else f"{x:.1f}x"


@dataclass
class ExhibitText:
    number: int
    label: str                 # "Exhibit 1"
    title: str                 # 결론형 제목
    source: str                # 하단 출처 한 줄
    body: str = ""             # 본문 해설
    pending: str | None = None  # 데이터 확인 중 사유


@dataclass
class Copy:
    lang: str
    title: str
    subtitle: str
    date: str
    takeaways: list[str]
    intro: str
    sections: dict[str, str]
    exhibits: dict[int, ExhibitText]
    table1_title: str
    table1_note: str
    table1_sentence: str | None
    conclusion: str
    methodology: list[str]
    disclosures: list[str]
    labels: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exhibit 제목·출처·해설
# ---------------------------------------------------------------------------
def ex1_text(e: Exhibit1 | Unavailable, lang: str) -> ExhibitText:
    src = {"kr": "자료: IEA, Energy and AI (2025.4) — 2030·2035년은 기준 시나리오(Base Case). KSJ Research 정리",
           "en": "Source: IEA, Energy and AI (Apr 2025) — 2030/2035 are Base Case projections. KSJ Research"}[lang]
    if isinstance(e, Unavailable):
        return ExhibitText(1, "Exhibit 1", PENDING[lang], src, pending=e.reason)
    v0, v1, v2 = e.values_twh
    if lang == "kr":
        title = f"데이터센터 전력 소비, 2030년 {times(e.multiple_2030, lang)}로 — 2024년 {v0:,.0f}TWh → 2035년 {v2:,.0f}TWh"
        body = (f"IEA는 전 세계 데이터센터 전력 소비가 2024년 {v0:,.0f}TWh에서 2030년 {v1:,.0f}TWh로 "
                f"{times(e.multiple_2030, lang)}, 2035년 {v2:,.0f}TWh로 {times(e.multiple_2035, lang)}가 될 것으로 본다(기준 시나리오). "
                "증가분의 대부분은 2030년 이전에 몰려 있어, 전력망·변압기 같은 설비 투자가 앞당겨져야 하는 구조다.")
    else:
        title = f"Data-centre power use set to reach {times(e.multiple_2030, lang)} by 2030 — {v0:,.0f} TWh (2024) to {v2:,.0f} TWh (2035)"
        body = (f"The IEA expects global data-centre electricity use to rise from {v0:,.0f} TWh in 2024 to {v1:,.0f} TWh in 2030 "
                f"({times(e.multiple_2030, lang)}) and {v2:,.0f} TWh by 2035 ({times(e.multiple_2035, lang)}) in its Base Case. "
                "Most of the increase is front-loaded before 2030, which pulls forward grid and transformer investment.")
    return ExhibitText(1, "Exhibit 1", title, src, body)


def ex2_text(e: Exhibit2 | Unavailable, lang: str) -> ExhibitText:
    src = {"kr": "자료: IEA, Key Questions on Energy and AI (2026.4). KSJ Research 정리",
           "en": "Source: IEA, Key Questions on Energy and AI (Apr 2026). KSJ Research"}[lang]
    if isinstance(e, Unavailable):
        return ExhibitText(2, "Exhibit 2", PENDING[lang], src, pending=e.reason)
    ratio = e.ai_dc / e.global_ if e.global_ else float("nan")
    if lang == "kr":
        title = (f"2025년 AI 데이터센터 전력 수요 {e.ai_dc:.0f}% 증가 — 전 세계 전력 수요({e.global_:.0f}%)의 "
                 f"{ratio:.0f}배 속도")
        body = (f"2025년 데이터센터 전력 수요는 {e.dc:.0f}%, 그중 AI 데이터센터는 {e.ai_dc:.0f}% 늘었다. "
                f"같은 해 전 세계 전력 수요 증가율 {e.global_:.0f}%와 비교하면 AI가 전력 수요의 '증가분'을 이끄는 축이 됐다는 뜻이다.")
    else:
        title = (f"AI data-centre demand grew {e.ai_dc:.0f}% in 2025 — {ratio:.0f}x the pace of global electricity "
                 f"demand ({e.global_:.0f}%)")
        body = (f"Data-centre electricity demand rose {e.dc:.0f}% in 2025, and AI-focused data centres {e.ai_dc:.0f}%. "
                f"Against {e.global_:.0f}% growth in global demand, AI has become a leading driver of incremental load.")
    return ExhibitText(2, "Exhibit 2", title, src, body)


def ex3_text(e: Exhibit3 | Unavailable, lang: str) -> ExhibitText:
    src = {"kr": "자료: U.S. Energy Information Administration (EIA), electricity retail sales (commercial, 연간). KSJ Research",
           "en": "Source: U.S. Energy Information Administration (EIA), electricity retail sales (commercial, annual). KSJ Research"}[lang]
    if isinstance(e, Unavailable):
        return ExhibitText(3, "Exhibit 3", PENDING[lang], src, pending=e.reason)
    b, va, us, gap = e.base_year, e.va_change_pct, e.us_change_pct, e.gap_pts
    if lang == "kr":
        title = {
            "ahead": f"버지니아 상업용 전력 판매 {b}년 대비 {pct(va)} — 미국 전체({pct(us)})를 {gap:.0f}p 앞서",
            "behind": f"버지니아 상업용 전력 판매 {b}년 대비 {pct(va)} — 미국 전체({pct(us)})보다 {abs(gap):.0f}p 낮아",
            "similar": f"버지니아와 미국 전체의 상업용 전력 판매, {b}년 이후 비슷한 흐름 ({pct(va)} vs {pct(us)})",
        }[e.verdict]
        read = {
            "ahead": "데이터센터가 몰린 지역의 전력 판매가 전국 평균보다 빠르게 늘었다는 점은 AI 전력 수요가 '전망'만이 아니라 "
                     "실제 계량기에 찍히고 있다는 근거다.",
            "behind": "데이터센터 밀집 지역이라는 통념과 달리 상업용 판매 기준으로는 전국보다 느렸다. 데이터센터 일부가 산업용으로 "
                      "분류되거나 자가발전·직접계약으로 잡히지 않을 가능성을 Vol.2에서 확인한다.",
            "similar": "상업용 판매 기준으로는 지역 차이가 크지 않았다. 데이터센터 부하가 산업용으로 분류되는 경우가 있어, "
                       "부문 합산 기준으로 다시 확인할 필요가 있다.",
        }[e.verdict]
        body = (f"{b}년을 100으로 놓으면 {e.last_year}년 버지니아는 {100 + va:.0f}, 미국 전체는 {100 + us:.0f}이다 "
                f"(연평균 {e.va_cagr_pct:.1f}% vs {e.us_cagr_pct:.1f}%). " + read)
    else:
        title = {
            "ahead": f"Virginia commercial power sales {updown(va)} since {b}, outpacing the U.S. ({pct(us)}) by {gap:.0f} pts",
            "behind": f"Virginia commercial power sales {updown(va)} since {b}, lagging the U.S. ({pct(us)}) by {abs(gap):.0f} pts",
            "similar": f"Virginia and U.S. commercial power sales have tracked closely since {b} ({pct(va)} vs {pct(us)})",
        }[e.verdict]
        read = {
            "ahead": "Faster growth where data centres cluster suggests AI-related load is already showing up on the meter, "
                     "not just in forecasts.",
            "behind": "Contrary to the data-centre-hub narrative, Virginia lagged on commercial sales. Part of the load may be "
                      "classified as industrial or served outside retail sales — a check for Vol.2.",
            "similar": "On commercial sales alone, the regional gap is small. Some data-centre load is classified as "
                       "industrial, so an all-sector view is the next check.",
        }[e.verdict]
        body = (f"Indexed to {b}=100, Virginia stood at {100 + va:.0f} and the U.S. at {100 + us:.0f} in {e.last_year} "
                f"(CAGR {e.va_cagr_pct:.1f}% vs {e.us_cagr_pct:.1f}%). " + read)
    return ExhibitText(3, "Exhibit 3", title, src, body)


def ex4_text(e: Exhibit4 | Unavailable, lang: str) -> ExhibitText:
    src = {"kr": "자료: 한국거래소(KRX) Open API 유가증권 일별매매정보(시가총액). KSJ Research",
           "en": "Source: Korea Exchange (KRX) Open API, KOSPI daily trading data (market cap). KSJ Research"}[lang]
    if isinstance(e, Unavailable):
        return ExhibitText(4, "Exhibit 4", PENDING[lang], src, pending=e.reason)
    top = e.table.sort_values("multiple", ascending=False).iloc[0]
    chg = (e.total_multiple - 1) * 100
    if lang == "kr":
        head = (f"{times(e.total_multiple, lang)}" if e.total_multiple >= 1 else f"{chg:+.0f}%")
        title = f"국내 전력기기 4사 시가총액 합계, 2023년 첫 거래일 대비 {head} — {top['company']} {times(top['multiple'], lang)}로 최대"
        body = (f"4사 시가총액 합계는 {e.t0} {e.total_t0:,.0f}억원에서 {e.t1} {e.total_t1:,.0f}억원으로 "
                f"{times(e.total_multiple, lang)}가 됐다. 회사별로는 {top['company']}가 {times(top['multiple'], lang)}로 가장 크게 올랐다.")
    else:
        head = (f"{times(e.total_multiple, lang)}" if e.total_multiple >= 1 else f"{chg:+.0f}%")
        title = (f"Combined market cap of four Korean power-equipment names at {head} its start-2023 level — "
                 f"{top['company_en']} leads at {times(top['multiple'], lang)}")
        body = (f"The four names' combined market cap moved from {e.total_t0:,.0f} (KRW 100mn) on {e.t0} to "
                f"{e.total_t1:,.0f} (KRW 100mn) on {e.t1} ({times(e.total_multiple, lang)}). "
                f"{top['company_en']} rose the most ({times(top['multiple'], lang)}).")
    return ExhibitText(4, "Exhibit 4", title, src, body)


def ex5_text(lang: str, n_ok: int, n_total: int) -> ExhibitText:
    if lang == "kr":
        return ExhibitText(5, "Exhibit 5", f"공식 출처 {n_total}곳 → 자동 수집 → 검증 → 리포트: 명령 두 줄로 이 노트를 재현",
                           "자료: KSJ Research (src/data_fetch, research/vol01). SEC는 접속 일시 차단으로 준비 중")
    return ExhibitText(5, "Exhibit 5", f"{n_total} official sources → automated collection → validation → report, "
                       "reproducible with two commands",
                       "Source: KSJ Research (src/data_fetch, research/vol01). SEC collection in progress (temporary access block)")


def table1_texts(t: Table1 | Unavailable, ex4: Exhibit4 | Unavailable, lang: str) -> tuple[str, str, str | None]:
    if lang == "kr":
        title = "Table 1. 시가총액 배수 = 영업이익 배수 × 밸류에이션(시가총액/영업이익) 배수"
        note = ("시가총액: 2023년 첫 거래일 → 기준일 직전 거래일(KRX). 영업이익: FY2023A → FY2025A 연결(DART). "
                "밸류에이션 배수 = 각 시점 시가총액 ÷ 해당 연도 영업이익. 자료: KRX, DART. KSJ Research")
    else:
        title = "Table 1. Market-cap multiple = operating-profit multiple × valuation (market cap / OP) multiple"
        note = ("Market cap: first trading day of 2023 → last trading day before the as-of date (KRX). Operating profit: "
                "FY2023A → FY2025A consolidated (DART). Valuation = market cap ÷ that year's OP. Source: KRX, DART. KSJ Research")
    if isinstance(t, Unavailable) or t.n_valid == 0:
        return title, note, None
    n, up = t.n_valid, t.n_valuation_up
    if lang == "kr":
        if up == n:
            s = (f"{n}사 모두 시가총액이 영업이익보다 빠르게 올라 밸류에이션 배수가 커졌다. 주가는 이미 나온 실적보다 "
                 "앞으로의 이익을 먼저 반영하고 있다는 것이 저자의 판단이다.")
        elif up * 2 >= n:
            s = (f"{n}사 중 {up}곳은 시가총액 상승이 영업이익 증가를 웃돌아 밸류에이션 배수가 커졌다. "
                 "기대가 실적보다 먼저 가격에 들어간 구간으로 본다(저자 견해).")
        else:
            s = (f"{n}사 중 {up}곳만 밸류에이션 배수가 커졌다. 시가총액 상승의 상당 부분은 실적 증가로 설명된다(저자 견해).")
    else:
        if up == n:
            s = (f"For all {n} names, market cap grew faster than operating profit, expanding valuation multiples. "
                 "In the author's view, prices are discounting future earnings ahead of reported results.")
        elif up * 2 >= n:
            s = (f"For {up} of {n} names, market cap outgrew operating profit, expanding valuation multiples — "
                 "expectations moved ahead of results (author's view).")
        else:
            s = (f"Only {up} of {n} names saw multiple expansion; most of the market-cap gain is explained by "
                 "earnings growth (author's view).")
    return title, note, s


def answer_q1(ex1, ex3, lang: str) -> str:
    """질문 1(수요는 진짜인가)의 답: IEA 전망 + EIA 실측 방향으로 결정."""
    kr = lang == "kr"
    if isinstance(ex1, Unavailable):
        return "수요 판단은 IEA 데이터 확인 후 갱신한다." if kr else "The demand call awaits the IEA data check."
    if isinstance(ex3, Unavailable):
        return ("AI 전력 수요는 전망(IEA) 기준으로는 분명하고, 실측(EIA) 확인은 데이터 수집 후 덧붙인다." if kr else
                "AI power demand is clear in the IEA outlook; the metered (EIA) check will follow once data is in.")
    if ex3.verdict == "ahead":
        return ("AI 전력 수요는 전망(IEA)과 실측(EIA) 모두에서 확인된다 — 진짜다." if kr else
                "AI power demand shows up in both the outlook (IEA) and metered sales (EIA) — it is real.")
    return ("AI 전력 수요는 전망(IEA)으로는 분명하지만, 상업용 실측(EIA)에서는 아직 뚜렷하지 않다 — 부문 분류를 넓혀 다시 본다." if kr else
            "AI power demand is clear in the IEA outlook but not yet decisive in commercial metered sales (EIA) — "
            "a broader sector view is next.")


def answer_q2(ex4, t1, big: float, lang: str) -> str:
    """질문 2(시장은 이미 알고 있나)의 답: 시가총액 배수 + 밸류에이션 배수 확대 기업 수로 결정."""
    kr = lang == "kr"
    if isinstance(ex4, Unavailable):
        return "시장 반영 여부는 KRX 데이터 확인 후 갱신한다." if kr else "The market call awaits the KRX data check."
    expanded = not isinstance(t1, Unavailable) and t1.n_valid and t1.n_valuation_up * 2 >= t1.n_valid
    if ex4.total_multiple >= big and expanded:
        return ("시장은 상당 부분 알고 있다 — 이제 관건은 실적이 이미 오른 기대를 따라잡는 속도다(저자 견해)." if kr else
                "The market largely knows — the question now is how fast earnings catch up with expectations (author's view).")
    if ex4.total_multiple >= 1:
        return ("시장은 일부 반영했지만 상승의 상당 부분은 실적으로 설명된다(저자 견해)." if kr else
                "The market has partly priced it, but much of the move is explained by earnings (author's view).")
    return ("시장은 아직 충분히 반영하지 않았다(저자 견해)." if kr else "The market has not fully priced it yet (author's view).")


# ---------------------------------------------------------------------------
# 노트 전체 문구
# ---------------------------------------------------------------------------
def build_copy(lang: str, cfg: Mapping, ex1, ex2, ex3, ex4, t1, sources: list[dict], n_tests: int,
               as_of: str) -> Copy:
    v = cfg["research"]["vol01"]
    big = float(v["text_rules"]["big_move_multiple"])
    exh = {1: ex1_text(ex1, lang), 2: ex2_text(ex2, lang), 3: ex3_text(ex3, lang), 4: ex4_text(ex4, lang),
           5: ex5_text(lang, sum(s["ok"] for s in sources), len(sources))}
    t_title, t_note, t_sentence = table1_texts(t1, ex4, lang)
    kr = lang == "kr"

    # Key Takeaways (데이터 없으면 '데이터 확인 중')
    if isinstance(ex1, Unavailable) or isinstance(ex2, Unavailable):
        k1 = ("수요: IEA 전망 " + PENDING[lang]) if kr else ("Demand: IEA figures " + PENDING[lang].lower())
    elif kr:
        k1 = (f"수요는 숫자로 확인된다: IEA는 데이터센터 전력 소비가 2030년 {times(ex1.multiple_2030, lang)}가 될 것으로 보며, "
              f"2025년 AI 데이터센터 수요는 {ex2.ai_dc:.0f}% 늘어 전 세계 전력({ex2.global_:.0f}%)을 크게 앞질렀다.")
    else:
        k1 = (f"Demand is real on the numbers: the IEA sees data-centre power use at {times(ex1.multiple_2030, lang)} by 2030, "
              f"and AI data-centre demand grew {ex2.ai_dc:.0f}% in 2025 vs {ex2.global_:.0f}% for global electricity.")
    if isinstance(ex3, Unavailable):
        k2 = "현장 데이터(EIA 주별 상업용 전력): 데이터 확인 중" if kr else "On-the-ground data (EIA state sales): data under review"
    elif kr:
        k2 = {"ahead": f"현장에서도 보인다: 버지니아 상업용 전력 판매는 {ex3.base_year}년 대비 {pct(ex3.va_change_pct)}로 "
                       f"미국 전체({pct(ex3.us_change_pct)})를 {ex3.gap_pts:.0f}p 앞섰다.",
              "behind": f"현장 데이터는 엇갈린다: 버지니아 상업용 전력 판매({pct(ex3.va_change_pct)})가 미국 전체"
                        f"({pct(ex3.us_change_pct)})보다 느렸다 — 부문 분류 확인이 필요하다.",
              "similar": f"현장 데이터는 아직 뚜렷하지 않다: 버지니아({pct(ex3.va_change_pct)})와 미국 전체"
                         f"({pct(ex3.us_change_pct)})의 상업용 판매 흐름이 비슷했다."}[ex3.verdict]
    else:
        k2 = {"ahead": f"It shows up on the meter: Virginia commercial sales are {updown(ex3.va_change_pct)} since "
                       f"{ex3.base_year}, {ex3.gap_pts:.0f} pts ahead of the U.S. ({pct(ex3.us_change_pct)}).",
              "behind": f"Ground data is mixed: Virginia commercial sales ({pct(ex3.va_change_pct)}) lagged the U.S. "
                        f"({pct(ex3.us_change_pct)}) — sector classification needs checking.",
              "similar": f"Ground data is not yet decisive: Virginia ({pct(ex3.va_change_pct)}) and the U.S. "
                         f"({pct(ex3.us_change_pct)}) tracked closely on commercial sales."}[ex3.verdict]
    if isinstance(ex4, Unavailable):
        k3 = "시장 반영(KRX 시가총액): 데이터 확인 중" if kr else "Market pricing (KRX market cap): data under review"
    else:
        lead_kr = ("시장은 이미 크게 움직였다" if ex4.total_multiple >= big else
                   "시장은 일부 반영했다" if ex4.total_multiple >= 1 else "시장은 아직 반영하지 않았다")
        lead_en = ("The market has already moved a lot" if ex4.total_multiple >= big else
                   "The market has partly priced it" if ex4.total_multiple >= 1 else "The market has not priced it yet")
        tail_kr = (f", {t1.n_valid}사 중 {t1.n_valuation_up}곳은 이익보다 주가가 더 올랐다." if
                   not isinstance(t1, Unavailable) and t1.n_valid else ".")
        tail_en = (f"; for {t1.n_valuation_up} of {t1.n_valid}, price outran profit." if
                   not isinstance(t1, Unavailable) and t1.n_valid else ".")
        k3 = (f"{lead_kr}: 국내 전력기기 4사 시가총액 합계는 2023년 초 대비 {times(ex4.total_multiple, lang)}" + tail_kr if kr
              else f"{lead_en}: four Korean power-equipment names are at {times(ex4.total_multiple, lang)} their start-2023 "
                   "combined market cap" + tail_en)

    if kr:
        intro = ("이 노트는 두 가지 질문에 공개 데이터로 답한다. 첫째, AI 전력 수요는 진짜인가 — IEA 전망과 미국 에너지정보청(EIA)의 "
                 "실측 판매 데이터로 확인한다. 둘째, 시장은 이미 알고 있나 — 국내 전력기기 4사의 시가총액(KRX)과 실적(DART)을 "
                 "나란히 놓고 본다. 모든 수치는 공식 출처에서 자동으로 수집·검증한 데이터로 계산했고, 출처와 기준일을 함께 적었다.")
        sections = {"s1": "1. 수요는 진짜인가 — 글로벌 전망", "s2": "2. 현장 데이터 — 미국 상업용 전력 판매",
                    "s3": "3. 시장은 이미 알고 있나 — 국내 전력기기 4사", "s4": "4. What I built — 데이터 파이프라인",
                    "s5": "Methodology", "s6": "Disclosures", "takeaways": "Key Takeaways", "sources": "데이터 소스 상태"}
        s4_body = (f"이 노트의 그래프·표·문장 속 숫자는 모두 코드가 데이터 파일에서 계산한다. 공식 출처 {len(sources)}곳의 API를 "
                   "재시도·타임아웃·캐시를 갖춘 공통 모듈로 수집하고, 모든 원본 파일에 출처·기준일·수집 시각을 담은 .meta.json을 "
                   f"남긴다. 수집 후에는 종목 식별자(DART 고유번호·SEC CIK) 검증, 보조 소스 교차검증, 단위·환율 검산을 거치며, "
                   f"핵심 계산은 테스트 함수 {n_tests}개로 확인한다. API 키는 로그와 기록에서 가린다.")
        conclusion = "결론. " + answer_q1(ex1, ex3, lang) + " " + answer_q2(ex4, t1, big, lang) + (
            " 다음 Vol.2에서는 이 기대가 가상 비상장 전력기기 기업(Target Co.)의 공모가 밴드에 어떻게 반영되는지 다룬다.")
    else:
        intro = ("This note answers two questions with public data. First, is AI power demand real? We test it with IEA "
                 "projections and metered sales data from the U.S. Energy Information Administration (EIA). Second, has the "
                 "market already priced it in? We set the market caps (KRX) of four Korean power-equipment names against "
                 "their reported earnings (DART). Every figure is computed from data collected and validated automatically "
                 "from official sources, with source and as-of date noted.")
        sections = {"s1": "1. Is demand real? — Global outlook", "s2": "2. Ground truth — U.S. commercial power sales",
                    "s3": "3. Has the market priced it? — Four Korean names", "s4": "4. What I built — Data pipeline",
                    "s5": "Methodology", "s6": "Disclosures", "takeaways": "Key Takeaways", "sources": "Data source status"}
        s4_body = (f"Every number in this note's charts, tables and text is computed by code from data files. APIs from "
                   f"{len(sources)} official sources are collected through a shared module with retries, timeouts and caching, "
                   "and every raw file carries a .meta.json with source, as-of date and fetch time. After collection, "
                   "identifiers (DART corp codes, SEC CIKs) are validated, secondary sources are cross-checked, and units and "
                   f"FX are re-checked; core calculations are covered by {n_tests} test functions. API keys are masked in logs.")
        conclusion = "Bottom line. " + answer_q1(ex1, ex3, lang) + " " + answer_q2(ex4, t1, big, lang) + (
            " Vol.2 will look at how these expectations feed into the IPO price range of a hypothetical "
            "unlisted power-equipment company (Target Co.).")

    have4 = not isinstance(ex4, Unavailable)
    if kr:
        points = (f"{ex4.t0}(2023년 첫 거래일)과 {ex4.t1}(기준일 직전 거래일)" if have4 else
                  "2023년 첫 거래일과 기준일 직전 거래일 (KRX 수집 후 확정)")
        methodology = [
            f"기준일: {as_of}. 시장 데이터 시점은 {points}.",
            "파이프라인: src/data_fetch(공통 수집·검증) → research/vol01/fetch_extra.py(추가 수집) → research/vol01/build.py(Exhibit·PDF 생성).",
            "Exhibit 1·2: IEA 공개 보고서 요약 수치를 data/manual/iea_energy_ai.csv에 출처 URL·발표월과 함께 수기 입력.",
            "Exhibit 3: EIA electricity/retail-sales, 상업용(commercial), 연간. 지수 = 해당 연도 판매량 ÷ 2015년 × 100. "
            "버지니아는 데이터센터 밀집 지역이라는 통념을 검증하기 위해 비교 대상으로 골랐다.",
            "Exhibit 4·Table 1: KRX 유가증권 일별매매정보의 시가총액(MKTCAP, 원 → 억원). 영업이익은 DART 사업보고서 연결 기준.",
            "한계: 데이터센터 전력은 주에 따라 산업용으로 분류될 수 있어 상업용 판매만으로는 일부만 보인다. 시가총액 변화에는 "
            "유상증자 등 주식 수 변화가 포함된다. 시가총액 구간(2023.1~)과 실적 구간(FY2023A~FY2025A)은 완전히 일치하지 않는다.",
            "SEC(해외 peers 재무)는 접속 일시 차단으로 준비 중이며, 이 노트의 결론에는 쓰지 않았다.",
        ]
        disclosures = [
            "이 자료는 교육·연구 목적의 개인 포트폴리오이며, 투자 권유나 특정 종목에 대한 매수·매도 의견이 아니다.",
            "본문의 판단은 저자 개인의 견해이며, 저자가 속했거나 속할 어떤 기관의 견해도 대변하지 않는다.",
            "모든 데이터는 공개 자료이며 정확성과 완전성을 보장하지 않는다. 이 자료를 근거로 한 투자 판단의 책임은 투자자 본인에게 있다.",
            "KSJ Research는 개인 리서치 브랜드로, 실존 금융회사와 관련이 없다.",
        ]
    else:
        methodology = [
            f"As-of date: {as_of}. Market data points: " + (
                f"{ex4.t0} (first trading day of 2023) and {ex4.t1} (last trading day before as-of)." if have4 else
                "first trading day of 2023 and last trading day before as-of (set after KRX collection)."),
            "Pipeline: src/data_fetch (shared collection and validation) → research/vol01/fetch_extra.py (extra data) → "
            "research/vol01/build.py (exhibits and PDFs).",
            "Exhibits 1–2: headline figures from public IEA reports, entered in data/manual/iea_energy_ai.csv with source URL and month.",
            "Exhibit 3: EIA electricity/retail-sales, commercial sector, annual. Index = year's sales ÷ 2015 × 100. Virginia "
            "was chosen to test the common view that it is a data-centre hub.",
            "Exhibit 4 / Table 1: market cap (MKTCAP, KRW → KRW 100mn) from KRX daily trading data; operating profit from "
            "DART annual reports (consolidated).",
            "Limitations: data-centre load may be classified as industrial in some states, so commercial sales show only part "
            "of it. Market-cap changes include share-count changes. The market-cap window (from Jan 2023) and the earnings "
            "window (FY2023A–FY2025A) do not match exactly.",
            "SEC (overseas peers' financials) is in progress due to a temporary access block and is not used in this note.",
        ]
        disclosures = [
            "This is a personal portfolio for education and research. It is not investment advice or a recommendation to buy "
            "or sell any security.",
            "Views are the author's own and do not represent any current or future employer.",
            "All data are public; accuracy and completeness are not guaranteed. Investors are solely responsible for their decisions.",
            "KSJ Research is a personal research brand and is not affiliated with any financial institution.",
        ]
    exh[5].body = s4_body
    labels = {"date": v["date_kr"] if kr else v["date_en"], "author": cfg["research"]["author"],
              "note_no": "Research Note · Vol.1", "pending": PENDING[lang],
              "page_footer": "교육·연구 목적 · 투자 권유 아님" if kr else "For education and research only · Not investment advice"}
    return Copy(lang, v["title_kr"] if kr else v["title_en"], v["title_en"] if kr else v["title_kr"],
                labels["date"], [k1, k2, k3], intro, sections, exh, t_title, t_note, t_sentence, conclusion,
                methodology, disclosures, labels)
