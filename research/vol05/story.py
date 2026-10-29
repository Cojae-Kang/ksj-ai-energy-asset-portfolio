"""Vol.5 페이지 구성·문구 (국문/영문). 숫자는 모두 data.Facts(= Vol.1~4 load_facts)에서, 판정·트리거는 저자 판단(J).

표기: 결론값마다 [원 편·쪽·등급]을 붙인다. 등급 = 그 값을 만든 주요 입력 중 가장 약한 등급(A2 출처 지도).
공개용 원칙(Vol.1~4와 같음): 내부 파일·명령은 본문에 쓰지 않는다.
"""
from __future__ import annotations

from typing import Mapping

from research.vol01.layout import BigBox, Cell, Page, TableSpec, toc_line

from . import charts
from .data import (CODE_EN, J_ASSUME, J_DESIGN, NO_VALUE, TIER_EN, TIER_KR, VERDICT_EN, VERDICT_KR, Asset, Facts, Ref, bucket_keys,
                   sourceable)

ASSET_KR = {"cfd_equity": "한전 CfD 태양광 지분", "dc_pf_loan": "데이터센터 PF 선순위 대출", "direct_ppa": "데이터센터 직접 PPA",
            "target_ipo": "Target Co. IPO", "merchant_solar": "시장 판매 태양광", "legacy_rec": "기존 REC 의존 자산",
            "listed_equip": "PER 40배 구간 상장 전력기기주"}
ASSET_EN = {"cfd_equity": "Solar equity on a KEPCO CfD", "dc_pf_loan": "Data-centre PF senior loan", "direct_ppa": "Direct PPA with a data centre",
            "target_ipo": "Target Co. IPO", "merchant_solar": "Merchant solar", "legacy_rec": "Existing REC-dependent assets",
            "listed_equip": "Listed power-equipment names at ~40x P/E"}

# 맺음말 국문 원문 — 저자 원문 그대로(문장 수정 금지, 맞춤법만 확인). 첫 줄 제목·마지막 줄 서명은 레이아웃에서 따로 그린다.
AFTERWORD_KR = [
    "이 시리즈는 하나의 질문에서 시작했습니다. \"AI가 전기를 이만큼 쓴다면, 그 돈은 어디로 흐르고, 각 길목에서 금융은 무엇을 결정해야 하는가.\"",
    "저는 고려대학교 환경생태공학부를 거쳐 KAIST 녹색성장지속가능대학원에서 에너지와 기후를 공부하고 있습니다. 공부할수록 궁금해진 것은 기술 자체보다 그 기술이 실제로 지어지는 과정이었습니다. "
    "좋은 기술과 정책이 있어도 자본이 움직이지 않으면 아무것도 지어지지 않기 때문입니다. 프로젝트가 어떻게 자금을 조달하고, 어떤 구조로 수익을 내는지 알고 싶어서 금융을 따로 공부해 왔습니다.",
    "학부에서는 식품자원경제학과 수업을 찾아 들었고, KAIST에서는 회계원리와 기후금융을 배우며 바이오차 플랜트의 현금흐름을 금융공학 방법론으로 추정해 보았습니다. "
    "한화 금융 공모전에서는 배리어옵션 구조로 상품의 가격을 산정해 보았고, iM증권 ECM 사업부와의 프로젝트에서는 배운 것을 실무의 언어로 옮겨 보는 연습을 했습니다. "
    "이 시리즈는 그렇게 따로 쌓아 온 공부를 하나의 산업 위에서 처음으로 엮어 본 것입니다.",
    "네 편에서 저는 매번 다른 자리에 앉아 보려 했습니다. 섹터 애널리스트로 주가 상승을 나눠 보고, PF 대주로 대출 한도를 정하고, ECM 뱅커로 공모가 밴드를 잡고, 지분투자자로 전력 계약의 가격을 따졌습니다. "
    "같은 산업이라도 앉은 자리에 따라 묻는 질문이 달랐고, 판단은 그 질문들을 이어 붙일 때 비로소 단단해진다는 것을 배웠습니다.",
    "숫자에는 특히 공을 들였습니다. 모든 입력값에 출처와 신뢰 등급을 붙였고, 요금표와 고시 원문을 직접 찾아 한 줄씩 대조했습니다. 게시한 뒤에도 독립 검토로 결론을 바꾸는 가정을 찾아냈고, "
    "고친 내용은 감추지 않고 기록으로 남겼습니다. 코드는 AI의 도움을 받았지만, 무엇을 물을지 정하고 그 숫자를 믿어도 되는지 확인하는 일은 끝까지 제 몫으로 두었습니다.",
    "그럼에도 이 작업은 졸업과 취업을 준비하는 틈틈이 혼자 공부하고 혼자 추정한 결과입니다. 공개 자료와 가정 위에 세운 연습이라 실무의 눈으로 보시면 부족한 점이 많을 것입니다. "
    "실제 딜에는 계약서의 한 조항, 협상 테이블의 분위기, 숫자로 잡히지 않는 위험이 훨씬 많다는 것도 압니다. 부족한 부분을 짚어 주시면 무엇이든 감사히 배우겠습니다.",
    "돌아보면 저는 늘 꿈을 놓지 않으려고 애써 왔습니다. 전공의 경계를 넘어 금융을 찾아 공부하는 동안, 너무 이상만 좇으며 살아온 것은 아닌가 스스로 묻게 되는 날도 있었습니다. "
    "금융인으로서 잘 자리 잡고 성장할 수 있을지, 솔직히 아직 확신하지는 못합니다. 그래도 이 시리즈를 마치며 분명해진 것이 하나 있습니다. 이제는 앞으로 나아가는 일만 남았다는 것입니다.",
    "앞으로도 이 시리즈에서 연습한 방식을 이어 가려 합니다. 같은 자산을 두고, 자금을 운용하는 사람이라면 어떻게 가치를 지킬지, 자금을 맡기는 사람이라면 어떤 조건에서 맡길지 함께 생각해 보겠습니다. "
    "새로운 사업 기회를 먼저 알아보는 사람이라면 무엇을 볼지, 투자 전략을 수립해 가치를 키우는 사람이라면 무엇을 바꿀지도 물어보겠습니다. "
    "그 출발점은 딜을 구조화하고 자금 조달을 설계하는 일이라고 생각합니다. 어느 자리에 있든 에너지·인프라 자산을 숫자로 판단하고, 그 판단의 근거를 끝까지 설명할 수 있는 금융인이 되는 것이 목표입니다.",
    "이 시리즈를 완성본이 아니라 그 길의 출발점으로 남겨 둡니다. 석사를 마친 뒤에도 이 질문들을 놓지 않고 계속 공부해 나가겠습니다.",
    "읽어 주신 모든 분께 감사드립니다.",
]
AFTERWORD_EN = [
    "This series began with a single question: \"If AI uses this much electricity, where does the money flow, and what does finance have to decide at each turn along the way?\"",
    "I studied in the Division of Environmental Science and Ecological Engineering at Korea University, and I am now studying energy and climate at the KAIST Graduate School of Green Growth and Sustainability. "
    "The more I studied, the more I found myself curious not about the technology itself but about how it actually gets built. Even with good technology and good policy, nothing gets built unless capital moves. "
    "I wanted to understand how projects raise money and how they are structured to earn a return, so I have studied finance on the side.",
    "As an undergraduate I sought out courses in the Department of Food and Resource Economics, and at KAIST I learned accounting principles and climate finance, estimating the cash flows of a biochar plant with "
    "financial-engineering methods. In a Hanwha finance competition I priced a product built on a barrier-option structure, and in a project with the ECM division of iM Securities I practised putting what I had learned "
    "into the language of practice. This series is the first time I have tried to weave those separate threads of study together on a single industry.",
    "Across the four volumes I tried to sit in a different seat each time. As a sector analyst I took apart a rise in share prices; as a PF lender I set a loan limit; as an ECM banker I drew an IPO price range; "
    "and as an equity investor I weighed the price of a power contract. The same industry raised different questions depending on where I sat, and I learned that judgement only becomes solid when those questions are joined together.",
    "I took particular care with the numbers. Every input carries a source and a reliability grade, and I went back to the tariff tables and official notices themselves to check them line by line. "
    "After publishing, independent reviews still found assumptions that changed conclusions; I corrected them and kept the corrections on the record rather than hiding them. "
    "AI helped me write the code, but deciding what to ask, and checking whether the numbers could be trusted, remained my job to the end.",
    "Even so, this is work I studied and estimated on my own, in the gaps between preparing to graduate and looking for a job. It is an exercise built on public information and assumptions, "
    "and to a practitioner's eye it will fall short in many places. I also know that a real deal holds far more: a single clause in a contract, the mood at the negotiating table, risks that numbers do not capture. "
    "If you point out where it falls short, I will be grateful to learn from it.",
    "Looking back, I have always tried not to let go of my dreams. While I crossed the boundaries of my major to study finance, there were days when I asked myself whether I had been chasing ideals too much. "
    "Honestly, I am not yet sure that I can settle in and grow well as a finance professional. Still, one thing became clear as I finished this series: all that is left now is to move forward.",
    "I want to keep practising the approach of this series. Looking at the same asset, I will think about how someone who manages capital would protect its value, and on what terms someone who entrusts capital would commit it. "
    "I will also ask what someone who spots new business opportunities early would look for, and what someone who sets an investment strategy to grow value would change. "
    "I believe the starting point for all of this is structuring deals and designing how they are financed. Wherever I sit, my goal is to become a finance professional who judges energy and infrastructure assets "
    "through numbers and can explain the basis for that judgement all the way through.",
    "I leave this series not as a finished piece but as the starting point of that path. After my master's, I will hold on to these questions and keep studying.",
    "Thank you to everyone who has read this series.",
]
SIGN_KR, SIGN_EN = "강신재 드림", "With gratitude, Shinjae Kang"


class Story:
    def __init__(self, cfg: Mapping, f: Facts, lang: str):
        self.cfg, self.f, self.lang, self.kr = cfg, f, lang, lang == "kr"
        self.c = cfg["research"]["colors"]
        self.v = cfg["research"]["vol05"]
        self.asset = {a.key: a for a in f.assets}

    # --- 도우미 -------------------------------------------------------------
    def T(self, kr: str, en: str) -> str:
        return kr if self.kr else en

    def R(self, k: str) -> Ref:
        return self.f.refs[k]

    def t(self, k: str) -> str:
        """값 표기 (언어별)."""
        r = self.R(k)
        return r.kr if self.kr else r.en

    def g(self, k: str, grade: bool = True) -> str:
        """[원 편·쪽·등급] 꼬리표."""
        r = self.R(k)
        return f"[{r.where(self.kr)}" + (f" · {r.tier}]" if grade else "]")

    def lab(self, k: str) -> str:
        r = self.R(k)
        return r.label_kr if self.kr else r.label_en

    def name(self, a: str) -> str:
        return (ASSET_KR if self.kr else ASSET_EN)[a]

    def verdict(self, a: str) -> str:
        return (VERDICT_KR if self.kr else VERDICT_EN)[self.asset[a].verdict]

    def tier_name(self, t: str) -> str:
        return (TIER_KR if self.kr else TIER_EN)[t]

    def pp(self, v: float, d: int = 1) -> str:
        return f"{v * 100:.{d}f}%p" if self.kr else f"{v * 100:.{d}f}pp"

    def assets_in(self, verdict: str) -> list[Asset]:
        return [a for a in self.f.assets if a.verdict == verdict]

    def lens(self, n: int) -> dict:
        return self.v["lenses"][n]

    def seat(self, n: int) -> str:
        return self.lens(n)["seat_kr" if self.kr else "seat_en"]

    @property
    def hurdle(self) -> str:
        return self.t("v4_hurdle")

    def room_hi(self) -> float:
        return max(self.f.V("v4_room"))

    def ipo_gap(self) -> tuple[float, float]:
        """필요 할인율 − 밴드 최대 할인율 (하한 FY2023A, FY2022A)."""
        r3 = lambda x: round(x, 3)  # noqa: E731  표시값(소수 첫째 자리 %) 기준 차이 — 37.9% − 35.0% = 2.9%p
        dmax = r3(max(self.f.V("v3_band_disc")))
        return r3(self.f.V("v3_req_alt")) - dmax, r3(self.f.V("v3_req_dp")) - dmax

    @staticmethod
    def sgn(v: float, d: int = 0) -> str:
        """부호 있는 퍼센트 (음수는 −)."""
        x = round(v * 100, d) + 0.0
        return ("−" if x < 0 else "+") + f"{abs(x):.{d}f}%"

    def per_drop(self) -> float:
        pc, pn = self.f.V("v3_per")
        return pn / pc - 1

    # --- 출처·고정 문구 -----------------------------------------------------
    def sources(self) -> dict[str, str]:
        return {
            "v1": self.T("KSJ Research Vol.1(2026.10) — DART·KRX 시총 분해", "KSJ Research Vol.1 (Oct 2026) — DART/KRX market-cap split"),
            "v2": self.T("KSJ Research Vol.2(2026.10) — 한국 40MW 데이터센터 PF", "KSJ Research Vol.2 (Oct 2026) — Korean 40 MW data-centre PF"),
            "v3": self.T("KSJ Research Vol.3(2026.10) — Target Co. 희망공모가 밴드", "KSJ Research Vol.3 (Oct 2026) — Target Co. price range"),
            "v4": self.T("KSJ Research Vol.4(2026.10) — 가상 태양광 35MW 지분", "KSJ Research Vol.4 (Oct 2026) — hypothetical 35 MW solar equity"),
            "git": self.T("저장소 git 이력(커밋 해시) · 각 편 빌드 요약의 커밋 전·후 문구", "Repository git history (commit hashes) · each volume's build summary before/after"),
            "ksj": "KSJ Research",
        }

    def labels(self) -> dict[str, str]:
        return {"source": self.T("출처", "Source"), "note": self.T("주", "Note"), "unit": self.T("단위", "Unit"),
                "pending": self.T("데이터·출처 확인 후 생성", "Generated once data are collected")}

    def footer(self) -> str:
        return self.T(f"KSJ Research · Research Note Vol.5 · {self.v['date_label']} · 교육·연구 목적, 투자 권유 아님 · 판정·트리거는 저자 판단(J) · 자산·기업은 가상",
                      f"KSJ Research · Research Note Vol.5 · {self.v['date_label']} · For education and research only, not investment advice · "
                      "verdicts and triggers are the author's judgement (J) · assets and company are hypothetical")

    def grade_note(self) -> str:
        return self.T("[원 편·쪽·등급]: 등급 = 그 값을 만든 주요 입력 중 가장 약한 등급(A 공식 원문 > D 공식 자료 계산 > B 보도·외부 보고서 > C 민간 2차 > J 저자 판단), 계산값은 최소 D — A2",
                      "[volume · page · grade]: grade = weakest grade among the main inputs (A official > D computed from official > B press/external > C secondary > J judgement); computed values at least D — A2")

    # =======================================================================
    def pages(self) -> list[Page]:
        return [self.cover(), self.executive(), self.toc_page(), self.p1(), self.p2(), self.p3(), self.p4(), self.p5(), self.p6(),
                self.a1(), self.a2(), self.a3(), self.afterword(), self.back()]

    def cover(self) -> Page:
        return Page("cover", title=self.v["title_kr"] if self.kr else self.v["title_en"],
                    subtitle=self.v["subtitle_kr"] if self.kr else self.v["subtitle_en"],
                    extra={"kicker": self.T("Research Note Vol.5 · 완결편", "Research Note Vol.5 · Finale"), "author": self.cfg["research"]["author"],
                           "date": self.v["date_label"],
                           "note": self.T("KSJ Research · 교육·연구 목적 · 투자 권유 아님 · 판정은 저자 판단", "KSJ Research · For education and research only · Not investment advice · Verdicts are judgement")})

    def back(self) -> Page:
        items = [
            self.T("이 자료는 교육·연구 목적의 개인 포트폴리오이며, 투자 권유나 특정 자산·종목에 대한 의견이 아니다.",
                   "This is a personal portfolio for education and research. It is not investment advice or a view on any asset or security."),
            self.T("넣는다·기다린다·피한다 판정과 트리거는 저자 판단(J)이다. 숫자는 Vol.1~4의 계산을 그대로 불러왔고, 원 편·쪽·신뢰 등급을 함께 적었다(A2).",
                   "Invest / wait / avoid verdicts and triggers are the author's judgement (J). Numbers are carried over from Vol.1–4 with their volume, page and source grade (A2)."),
            self.T("Target Co.·태양광 35MW·데이터센터는 가상 사례다. 실존 기업·실제 계약 가격과 무관하다. 상장 전력기기주는 섹터 수준 판단이며 특정 종목 의견이 아니다.",
                   "Target Co., the 35 MW solar asset and the data centres are hypothetical. Listed power-equipment names are discussed at sector level, not as a view on any stock."),
            self.T("본문의 판단은 저자 개인의 견해이며, 저자가 속했거나 속할 어떤 기관의 견해도 대변하지 않는다.",
                   "Views are the author's own and do not represent any current or future employer."),
            self.T(f"Vol.5 기준일 {self.f.as_of} (Vol.1~4 숫자는 각 편 기준일 그대로). 계산 방법과 코드는 저장소에서 재현할 수 있다.",
                   f"Vol.5 as of {self.f.as_of} (Vol.1–4 numbers keep their own as-of dates). Methods and code can be reproduced from the repository."),
        ]
        from research.disclosures import contact_line, license_items
        items += license_items(self.cfg, self.kr)
        return Page("back", title="Disclosures", extra={"items": items, "repo": self.cfg["research"]["repo_url"], "contact": contact_line(self.cfg)})

    # --- i 요약 ----------------------------------------------------------------
    VPAGE = {"invest": "3", "wait": "4", "avoid": "5"}

    def headline(self) -> str:
        room = f"{self.room_hi():.0f}"
        net = f"{self.f.V('v4_net_charge'):.0f}"
        return self.T(f"계약된 현금흐름엔 넣고(CfD IRR {self.t('v4_irr_cfd')} · PF 최소 DSCR {self.t('v2_min_dscr')}), 성립 조건이 안 맞으면 기다리고"
                      f"(PPA 여유 최대 {room}원 < 부대비용 {net}원(B)), 시장 가격·배수에 기대면 피한다(시장 판매 IRR {self.t('v4_irr_merchant')})",
                      f"Invest in contracted cash flows (CfD IRR {self.t('v4_irr_cfd')}, PF min DSCR {self.t('v2_min_dscr')}), wait where deals "
                      f"cannot close (PPA room ≤ {room} < {net} charges, B), avoid what leans on prices or multiples (merchant IRR {self.t('v4_irr_merchant')})")

    def exec_conclusions(self) -> list[str]:
        return [self.headline()] + [b.title for b in self.boxes()]

    def rec_wait(self) -> bool:
        """기존 REC 자산: 부칙 제3조②③ 경과조치가 있으면(입력 rec_legacy_continue = 1) 판정이 '기다린다'."""
        return self.asset["legacy_rec"].verdict == "wait"

    # 판정별 머리 문구 (박스 제목 앞) · 쪽 꼬리 문구
    BOX_LEAD = {"invest": ("계약이 있는 현금흐름", "Contracted cash flows"),
                "wait": ("수익률·제도는 되지만 거래가 아직 안 닫힌다", "Returns or rules hold but the deals do not close yet"),
                "avoid": ("시장 가격·배수에 기댄다", "They lean on market prices or multiples")}
    PAGE_TAIL = {"invest": ("계약된 현금흐름", "contracted cash flows"), "wait": ("수익률이 아니라 성립 조건이 아직", "not the return, the closing conditions"),
                 "avoid": ("계약으로 막을 수 없는 가격에 기댄다", "returns hang on prices no contract can fix")}

    def seg(self, k: str) -> str:
        """쪽 제목용 자산 한 토막."""
        r_hi, net = self.room_hi(), self.f.V("v4_net_charge")
        return {
            "cfd_equity": self.T(f"한전 CfD 지분(IRR {self.t('v4_irr_cfd')})", f"KEPCO CfD equity (IRR {self.t('v4_irr_cfd')})"),
            "dc_pf_loan": self.T(f"데이터센터 PF 선순위 대출(최소 DSCR {self.t('v2_min_dscr')})", f"data-centre PF senior loan (min DSCR {self.t('v2_min_dscr')})"),
            "direct_ppa": self.T(f"직접 PPA(IRR {self.t('v4_irr_ppa')}, 여유 {r_hi:.0f}원 < {net:.0f}원)", f"direct PPA (IRR {self.t('v4_irr_ppa')}, room {r_hi:.0f} < {net:.0f})"),
            "target_ipo": self.T(f"Target Co. IPO(필요 할인율 {self.t('v3_req_alt')}~{self.t('v3_req_dp')})", f"Target Co. IPO (required {self.t('v3_req_alt')}–{self.t('v3_req_dp')})"),
            "merchant_solar": self.T(f"시장 판매(IRR {self.t('v4_irr_merchant')})", f"merchant (IRR {self.t('v4_irr_merchant')})"),
            "legacy_rec": (self.T("기존 REC 의존 자산(종전 규정 유지, 고시 대기)", "REC-dependent assets (former rules kept, notice pending)") if self.rec_wait()
                           else self.T(f"기존 REC 의존 자산(REC 조항 {self.t('v4_rec_end')} 종료)", f"REC-dependent assets (REC article lapses {self.t('v4_rec_end')})")),
            "listed_equip": self.T(f"PER 40배 구간 추격(멀티플 기여 {self.t('v1_mult_ni')}~{self.t('v1_mult_op')})", f"chasing ~40x P/E (multiple share {self.t('v1_mult_ni')}–{self.t('v1_mult_op')})"),
        }[k]

    def box_phrase(self, k: str) -> str:
        dmax = max(self.f.V("v3_band_disc")) * 100
        return {
            "cfd_equity": self.T(f"한전 CfD 지분 IRR {self.t('v4_irr_cfd')}(요구 {self.hurdle})", f"KEPCO CfD equity IRR {self.t('v4_irr_cfd')} (hurdle {self.hurdle})"),
            "dc_pf_loan": self.T(f"데이터센터 PF 최소 DSCR {self.t('v2_min_dscr')}(목표 {self.t('v2_target_dscr')})", f"data-centre PF min DSCR {self.t('v2_min_dscr')} (target {self.t('v2_target_dscr')})"),
            "direct_ppa": self.T(f"PPA 여유 {self.t('v4_room')} < 부대비용 {self.t('v4_net_charge')}(B)", f"PPA room {self.t('v4_room')} < charges {self.t('v4_net_charge')} (B)"),
            "target_ipo": self.T(f"IPO 필요 할인율 {self.t('v3_req_alt')}~{self.t('v3_req_dp')} > 밴드 최대 {dmax:.1f}%", f"IPO required discount {self.t('v3_req_alt')}–{self.t('v3_req_dp')} > the range's widest {dmax:.1f}%"),
            "merchant_solar": self.T(f"시장 판매 IRR {self.t('v4_irr_merchant')}", f"merchant IRR {self.t('v4_irr_merchant')}"),
            "legacy_rec": (self.T("기존 REC 자산은 종전 규정 유지(부칙 제3조, A) — 고시 대기", "existing REC assets keep the former rules (addendum art. 3, A) — notice pending") if self.rec_wait()
                           else self.T(f"REC 조항 {self.t('v4_rec_end')} 효력 종료", f"REC article lapses {self.t('v4_rec_end')}")),
            "listed_equip": self.T(f"멀티플 기여 {self.t('v1_mult_ni')}~{self.t('v1_mult_op')}", f"multiple contribution {self.t('v1_mult_ni')}–{self.t('v1_mult_op')}"),
        }[k]

    def box_bullet(self, k: str) -> str:
        lo_g, hi_g = self.ipo_gap()
        return {
            "cfd_equity": self.T(f"CfD 지분: 대출 {self.t('v4_cfd_gearing')} · 최소 DSCR {self.t('v4_cfd_dscr')} — 뒤집는 가정: {self.t('v4_cfd_cf_low')} {self.g('v4_cfd_cf_low')}",
                                 f"CfD equity: gearing {self.t('v4_cfd_gearing')} · min DSCR {self.t('v4_cfd_dscr')} — flipped by output: {self.t('v4_cfd_cf_low')} {self.g('v4_cfd_cf_low')}"),
            "dc_pf_loan": self.T(f"DC PF 대출 {self.t('v2_debt')}(총사업비 {self.t('v2_gearing')}): 선행조건은 전력비 별도 청구 — 포함이면 같은 대출에서 최소 DSCR {self.t('v2_dscr_gross')}, 다시 잡으면 Equity IRR {self.t('v2_irr_gross')} {self.g('v2_irr_gross')}",
                                 f"DC PF loan {self.t('v2_debt')} ({self.t('v2_gearing')} of cost): condition precedent = power billed separately — if included, min DSCR {self.t('v2_dscr_gross')} on the same debt; re-sized, equity IRR {self.t('v2_irr_gross')} {self.g('v2_irr_gross')}"),
            "direct_ppa": self.T(f"직접 PPA(IRR {self.t('v4_irr_ppa')}): 부대비용이 {self.t('v4_gap')} 줄거나 구매자가 그만큼 더 내야 성립 — 트리거는 망이용료 인하 · 망 미이용 공급 {self.g('v4_gap')}",
                                 f"Direct PPA (IRR {self.t('v4_irr_ppa')}): charges must fall by {self.t('v4_gap')} or the buyer must pay that much more — triggers: lower network charges, supply without the grid {self.g('v4_gap')}"),
            "target_ipo": self.T(f"Target Co. IPO(밴드 {self.t('v3_band')}): 필요 할인율이 밴드보다 {self.pp(lo_g)}~{self.pp(hi_g)} 크다 — 트리거는 이익률 하한 확인 {self.g('v3_req_dp')}",
                                 f"Target Co. IPO (range {self.t('v3_band')}): required discount exceeds the range by {self.pp(lo_g)}–{self.pp(hi_g)} — trigger: confirming the margin floor {self.g('v3_req_dp')}"),
            "merchant_solar": self.T(f"시장 판매: SMP가 범위 상단에 머물러야 {self.R('v4_merchant_smp_hi').value[1] * 100:.1f}%로 겨우 요구수익률 — REC 없음 {self.g('v4_irr_merchant')}",
                                     f"Merchant: only at the top of the SMP range does it reach {self.R('v4_merchant_smp_hi').value[1] * 100:.1f}%, barely the hurdle — no RECs {self.g('v4_irr_merchant')}"),
            "legacy_rec": (self.T(f"기존 REC 자산: 제도 종료로 수입이 사라지지 않는다(부칙 제3조②③) — 남은 위험은 REC 가격·수요와 고시의 인정 범위, 트리거는 고시 확정 {self.g('v4_rec_continue')}",
                                  f"Existing REC assets: revenue does not vanish with the scheme (addendum art. 3(2)–(3)) — what remains is REC price and demand and the notice's scope; trigger: the notice {self.g('v4_rec_continue')}") if self.rec_wait()
                           else self.T(f"기존 REC 자산: REC 조항 {self.t('v4_rec_end')} 효력 종료 {self.g('v4_rec_end')}", f"Existing REC assets: REC article lapses {self.t('v4_rec_end')} {self.g('v4_rec_end')}")),
            "listed_equip": self.T(f"PER {self.t('v1_per')}: 이익 기준을 3사 순이익으로 잡느냐 4사 영업이익으로 잡느냐에 따라 멀티플 기여 {self.t('v1_mult_ni')} vs {self.t('v1_mult_op')} {self.g('v1_mult_op')}",
                                   f"P/E {self.t('v1_per')}: the multiple's share is {self.t('v1_mult_ni')} on 3-name net income vs {self.t('v1_mult_op')} on 4-name operating income {self.g('v1_mult_op')}"),
        }[k]

    def boxes(self) -> list[BigBox]:
        out = []
        for v in ("invest", "wait", "avoid"):
            aa = self.assets_in(v)
            names = " · ".join(self.name(a.key) for a in aa)
            lead = self.T(*self.BOX_LEAD[v])
            out.append(BigBox(VERDICT_KR[v] if self.kr else VERDICT_EN[v],
                              self.T(f"자산 {len(aa)}개: {names}", f"{len(aa)} assets: {names}"),
                              f"{lead}: " + self.T(", ", "; ").join(self.box_phrase(a.key) for a in aa),
                              [self.box_bullet(a.key) for a in aa]))
        return out

    def exec_rows(self, k: str) -> list[tuple[str, str, bool]]:
        """요약 쪽 핵심 지표 (자산별: 라벨, 값, 강조)."""
        return {
            "cfd_equity": [(self.T("한전 CfD 지분 IRR / 요구수익률", "KEPCO CfD equity IRR / hurdle"), f"{self.t('v4_irr_cfd')} / {self.hurdle}", True)],
            "dc_pf_loan": [(self.T("DC PF 최소 DSCR / 목표", "DC PF min DSCR / target"), f"{self.t('v2_min_dscr')} / {self.t('v2_target_dscr')}", True),
                           (self.T("  선행조건: 전력비 포함이면 최소 DSCR", "  CP: min DSCR if power is in the rent"), self.t("v2_dscr_gross"), False)],
            "direct_ppa": [(self.T("직접 PPA 여유 vs 부대비용(B)", "PPA room vs charges (B)"), f"{self.t('v4_room')} vs {self.t('v4_net_charge')}", True)],
            "target_ipo": [(self.T("IPO 필요 할인율 vs 밴드 할인율", "IPO required vs range discount"),
                            f"{self.t('v3_req_alt')}{self.T('~', '–')}{self.t('v3_req_dp')} vs {self.t('v3_band_disc')}", True)],
            "merchant_solar": [(self.T("시장 판매 지분 IRR", "merchant equity IRR"), self.t("v4_irr_merchant"), True)],
            "legacy_rec": [(self.T("기존 REC 자산 경과조치(부칙 제3조, A)", "REC transitional rule (addendum art. 3, A)"), self.T("종전 규정 유지 · 고시 대기", "former rules · notice pending"), False)
                           if self.rec_wait() else (self.T("REC 조항 효력 종료(A)", "REC article lapses (A)"), self.t("v4_rec_end"), False)],
            "listed_equip": [(self.T("멀티플 기여 3사 순이익 / 4사 영업이익", "multiple share 3-name NI / 4-name OP"), f"{self.t('v1_mult_ni')} / {self.t('v1_mult_op')}", False)],
        }[k]

    def executive(self) -> Page:
        f = self.f
        rows, shade, gold = [], set(), set()

        def add(label, value, page, key=False):
            if key:
                shade.add(len(rows))
                gold.add((len(rows), 1))
            rows.append([label, value, page])
        for v in ("invest", "wait", "avoid"):
            for a in self.assets_in(v):
                for lab, val, key in self.exec_rows(a.key):
                    pre = "" if lab.startswith("  ") else f"{self.verdict(a.key)} · "
                    add(pre + lab, val, self.VPAGE[v], key)
        tot = f.total
        ns, nad = sourceable(tot)
        add(self.T(f"출처가 있을 수 있는 입력 중 A·D (전체 {sum(tot.values())}개)", f"A·D among sourceable inputs ({sum(tot.values())} in all)"),
            f"{nad} / {ns} ({nad / ns * 100:.0f}%)", "6", True)
        ok_ = sum(1 for c in f.corrections if c["verified"])
        add(self.T("정정 기록 (git 대조 일치)", "Corrections (git-verified)"), self.T(f"{len(f.corrections)}건 ({ok_}/{len(f.corrections)})", f"{len(f.corrections)} ({ok_}/{len(f.corrections)})"), "6")
        table = TableSpec([self.T("핵심 지표", "Key metric"), self.T("값", "Value"), self.T("쪽", "p.")], rows, [0.56, 0.35, 0.09], ["L", "R", "C"],
                          shade_rows=shade, gold_cells=gold, font_size=8.2)
        left = Cell(title=self.T("핵심 지표", "Key metrics"), src=["v1", "v2", "v3", "v4", "ksj"], table=table,
                    note=self.T("숫자는 Vol.1~4 계산 그대로(각 편 기준일 2026-10-20). 판정은 저자 판단(J). 원 편·쪽·등급은 A2", "Numbers carried over from Vol.1–4 (as of 20 Oct 2026). Verdicts are judgement (J). Volume, page and grade in A2"))
        sub = self.T("네 편 · 네 자리의 결론을 자산 7개의 판정으로 — 판정을 가르는 것은 수익률보다 결론을 뒤집는 가정의 크기",
                     "Four volumes, four seats, seven verdicts — what separates them is less the return than the size of the assumption that flips it")
        return Page("exec", label="i", title=self.headline(), subtitle=sub, cells=[left], boxes=self.boxes())

    def toc_page(self) -> Page:
        heads = [self.p1(), self.p2(), self.p3(), self.p4(), self.p5(), self.p6()]
        names = [self.T("네 렌즈", "Four lenses"), self.T("투자 지도", "The map"), self.T("넣는다", "Invest"), self.T("기다린다", "Wait"),
                 self.T("피한다", "Avoid"), self.T("숫자 관리", "Number discipline")]
        toc = [(n, nm, toc_line(h.title), h.label) for n, nm, h in zip(["I", "II", "III", "IV", "V", "VI"], names, heads)]
        toc.append(("App.", "Appendix", self.T("A1 IC 메모 · A2 출처 지도 · A3 용어 · 맺으며", "A1 IC memo · A2 Source map · A3 Glossary · Afterword"), "A1–A3"))
        return Page("toc", label="ii", title=self.T("목차", "Contents"),
                    subtitle=self.T("돈의 흐름 → 지도 → 넣는다 · 기다린다 · 피한다 → 숫자를 지킨 방법: 각 장의 결론",
                                    "Money flow → map → invest · wait · avoid → how the numbers were kept: each section's conclusion"), toc=toc)

    # --- p1 돈의 흐름과 네 렌즈 -------------------------------------------------
    def p1(self) -> Page:
        f = self.f
        keynum = {1: self.T(f"멀티플 기여 {self.t('v1_mult_ni')} / {self.t('v1_mult_op')}", f"Multiple share {self.t('v1_mult_ni')} / {self.t('v1_mult_op')}"),
                  2: self.T(f"최소 DSCR {self.t('v2_min_dscr')}", f"Min DSCR {self.t('v2_min_dscr')}"),
                  3: self.T(f"밴드 {self.t('v3_band')}", f"Range {self.t('v3_band')}"),
                  4: self.T(f"PPA 여유 {self.t('v4_room')}", f"PPA room {self.t('v4_room')}")}
        steps = [(self.lens(n)["stage_kr" if self.kr else "stage_en"], f"Vol.{n}", self.seat(n), self.lens(n)["question_kr" if self.kr else "question_en"], keynum[n])
                 for n in (1, 2, 3, 4)]
        c1 = Cell(title=self.T("AI 전력 수요가 만든 돈은 네 길목을 지난다 — 길목마다 앉은 자리와 금융이 정할 것이 다르다",
                               "The money AI power demand creates passes four turns — each with its own seat and its own decision"),
                  src=["v1", "v2", "v3", "v4"], chart_key="flow",
                  chart=charts.lens_flow(steps, self.c, self.T("돈의 흐름: 전력 수요 → 데이터센터·발전 자산 → 전력기기 상장 → 전력 계약", "Money flow: power demand → data-centre and generation assets → equipment listings → power contracts")),
                  note=self.T("박스 아래 숫자 = 각 편 핵심 결론값(원 편 그대로). Vol.1 수요는 상장 전력기기주 시총으로, Vol.4 계약은 가상 태양광 35MW로 잰다",
                              "Number at the foot of each box = the volume's key result. Vol.1 measures demand through listed equipment caps; Vol.4 uses a hypothetical 35 MW solar plant"))
        rows, warn = [], []
        for n in (1, 2, 3, 4):
            h = f.headlines[n]
            rows.append([f"Vol.{n} · {self.lens(n)['stage_kr' if self.kr else 'stage_en']}", self.seat(n), self.lens(n)["question_kr" if self.kr else "question_en"],
                         h["kr"] if self.kr else h["en"]])
            if not h["match"]:
                warn.append(n)
        n_ok = sum(1 for n in (1, 2, 3, 4) if f.headlines[n]["match"])
        c2 = Cell(title=self.T(f"편별 한 줄 결론 — 원 편 Executive Summary 제목 그대로 (국문은 각 편 빌드 요약과 대조 {n_ok}/4 일치)",
                               f"One-line conclusion per volume — each volume's executive-summary title, verbatim (Korean matched to its build summary {n_ok}/4)"),
                  src=["v1", "v2", "v3", "v4"],
                  table=TableSpec([self.T("편 · 단계", "Vol. · stage"), self.T("앉은 자리", "Seat"), self.T("질문", "Question"), self.T("한 줄 결론", "One-line conclusion")],
                                  rows, [0.11, 0.12, 0.18, 0.59], ["L", "L", "L", "L"], strong_cells={(i, 1) for i in range(4)}, font_size=7.8, max_grow=1.15),
                  note=self.T("같은 산업이라도 앉은 자리에 따라 묻는 질문이 다르다 — 지도(p2)는 이 네 질문의 답을 자산 단위로 이어 붙인 것", "The same industry asks different questions from different seats — the map (p2) joins the four answers asset by asset"))
        return Page("body", "1", self.T("돈의 흐름과 네 렌즈: 수요(Vol.1) → 자산(Vol.2) → 상장(Vol.3) → 계약(Vol.4) — 같은 산업, 자리마다 다른 질문",
                                        "Money flow and four lenses: demand (Vol.1) → assets (Vol.2) → listing (Vol.3) → contracts (Vol.4) — one industry, a different question from each seat"),
                    self.T("섹터 애널리스트 · PF 대주 · ECM 뱅커 · 지분투자자 — 네 편이 앉았던 자리와 각 편의 결론", "Sector analyst · PF lender · ECM banker · equity investor — the seat each volume took and what it concluded"),
                    [c1, c2], grid="2x1")

    # --- p2 투자 지도 -----------------------------------------------------------
    def map_rows(self) -> list[dict]:
        """자산별: 이름·편·자리, 기준, 뒤집는 가정, 판정, 트리거 (국/영)."""
        lo_g, hi_g = self.ipo_gap()
        cf_lo, irr_lo = self.f.V("v4_cfd_cf_low")
        smp_hi, m_hi = self.f.V("v4_merchant_smp_hi")
        dmax = max(self.f.V("v3_band_disc"))
        T = self.T
        rows = {
            "cfd_equity": (T(f"지분 IRR {self.t('v4_irr_cfd')}(요구 {self.hurdle}) · 대출 {self.t('v4_cfd_gearing')} · 최소 DSCR {self.t('v4_cfd_dscr')} {self.g('v4_irr_cfd')}",
                             f"Equity IRR {self.t('v4_irr_cfd')} (hurdle {self.hurdle}) · gearing {self.t('v4_cfd_gearing')} · min DSCR {self.t('v4_cfd_dscr')} {self.g('v4_irr_cfd')}"),
                           T(f"이용률 {self.t('v4_cf_base')} → {cf_lo * 100:.0f}%(KEEI 범위 하단)면 IRR {irr_lo * 100:.1f}% < {self.hurdle} {self.g('v4_cfd_cf_low')} · 사업비 KEEI 상단이면 {self.t('v4_cfd_capex_hi')}",
                             f"Capacity factor {self.t('v4_cf_base')} → {cf_lo * 100:.0f}% (KEEI low) cuts IRR to {irr_lo * 100:.1f}% < {self.hurdle} {self.g('v4_cfd_cf_low')} · CAPEX at KEEI top: {self.t('v4_cfd_capex_hi')}"),
                           T(f"계약시장 낙찰가가 입찰 상한 {self.t('v4_cfd_price')}보다 낮거나, P90 이용률이 {cf_lo * 100:.0f}%에 가까우면 재검토",
                             f"Re-examine if the contract-market price clears below the {self.t('v4_cfd_price')} cap, or P90 output nears {cf_lo * 100:.0f}%")),
            "dc_pf_loan": (T(f"최소 DSCR {self.t('v2_min_dscr')}(목표 {self.t('v2_target_dscr')}) · 대출 {self.t('v2_debt')}(총사업비 {self.t('v2_gearing')}) {self.g('v2_min_dscr')}",
                             f"Min DSCR {self.t('v2_min_dscr')} (target {self.t('v2_target_dscr')}) · debt {self.t('v2_debt')} ({self.t('v2_gearing')} of cost) {self.g('v2_min_dscr')}"),
                           T(f"임대료에 전력비 포함이면 같은 대출에서 최소 DSCR {self.t('v2_dscr_gross')} {self.g('v2_dscr_gross')} — 다시 sizing하면 대출 {self.t('v2_debt_gross')}·Equity IRR {self.t('v2_irr_gross')} {self.g('v2_irr_gross')}",
                             f"With power inside the rent, min DSCR {self.t('v2_dscr_gross')} on the same debt {self.g('v2_dscr_gross')} — re-sized, debt {self.t('v2_debt_gross')}, equity IRR {self.t('v2_irr_gross')} {self.g('v2_irr_gross')}"),
                           T("임대차계약서의 전력비 별도 청구 조항 = 인출 선행조건. 확인 못 하면 한도를 전력 포함 기준으로 낮춘다",
                             "Separate power billing in the lease = condition precedent to drawdown; if unconfirmed, size on the power-included basis")),
            "direct_ppa": (T(f"지분 IRR {self.t('v4_irr_ppa')}(회랑 중간 {self.t('v4_ppa_mid')}) {self.g('v4_irr_ppa')}",
                             f"Equity IRR {self.t('v4_irr_ppa')} (corridor mid {self.t('v4_ppa_mid')}) {self.g('v4_irr_ppa')}"),
                           T(f"구매자 여유 {self.t('v4_room')} {self.g('v4_room')} vs 공개 사례 부대비용 {self.t('v4_net_charge')} {self.g('v4_net_charge')} — {self.t('v4_gap')}이 모자란다 {self.g('v4_gap', False)}",
                             f"Buyer's room {self.t('v4_room')} {self.g('v4_room')} vs public-example charges {self.t('v4_net_charge')} {self.g('v4_net_charge')} — {self.t('v4_gap')} short {self.g('v4_gap', False)}"),
                           T(f"망이용료(송·배전 이용요금·부가정산금) 인하 · 망 미이용 공급(고시 단서: 망을 쓰지 않으면 두 항목 제외) {self.g('v4_proviso')}",
                             f"Lower network charges (T&D use, settlements) · supply without the grid (notice proviso drops both items) {self.g('v4_proviso')}")),
            "target_ipo": (T(f"희망공모가 {self.t('v3_band')}(할인율 {self.t('v3_band_disc')}) {self.g('v3_band')}",
                             f"Range {self.t('v3_band')} (discount {self.t('v3_band_disc')}) {self.g('v3_band')}"),
                           T(f"순이익률 하한 {self.lab('v3_req_dp').split('하한 ')[-1]} → 필요 할인율 {self.t('v3_req_dp')}, {self.lab('v3_req_alt').split('하한 ')[-1]} → {self.t('v3_req_alt')} {self.g('v3_req_dp')} — 밴드 최대 {dmax * 100:.1f}%보다 {self.pp(lo_g)}~{self.pp(hi_g)} 큼",
                             f"Margin floor {self.lab('v3_req_dp').split('floor ')[-1]} → required {self.t('v3_req_dp')}; {self.lab('v3_req_alt').split('floor ')[-1]} → {self.t('v3_req_alt')} {self.g('v3_req_dp')} — {self.pp(lo_g)}–{self.pp(hi_g)} above the widest {dmax * 100:.1f}%"),
                           T(f"이익률 하한 확인: 다음 결산에서 순이익률 바닥이 확인돼 필요 할인율이 밴드 할인율(최대 {dmax * 100:.1f}%) 안으로 들어올 때",
                             f"Confirm the margin floor: when the next results pin down the trough margin and the required discount falls inside the range (max {dmax * 100:.1f}%)")),
            "merchant_solar": (T(f"지분 IRR {self.t('v4_irr_merchant')}(요구 {self.hurdle}) {self.g('v4_irr_merchant')} · 2027년 이후 신규 사업자 {self.t('v4_rec_none')} {self.g('v4_rec_none')}",
                                 f"Equity IRR {self.t('v4_irr_merchant')} (hurdle {self.hurdle}) {self.g('v4_irr_merchant')} · {self.t('v4_rec_none')} for post-2027 entrants {self.g('v4_rec_none')}"),
                               T(f"SMP {smp_hi:,.1f}원(범위 상단)이 이어져야 {m_hi * 100:.1f}%로 겨우 통과 {self.g('v4_merchant_smp_hi')} · 2022년 실제 설치비로도 {self.t('v4_merchant_actual')}",
                                 f"Only SMP held at {smp_hi:,.1f} (range top) lifts it to {m_hi * 100:.1f}%, barely clearing {self.g('v4_merchant_smp_hi')} · even at 2022 actual cost: {self.t('v4_merchant_actual')}"),
                               T("장기 고정가 계약(한전 계약시장) 확보, 또는 SMP 범위 상단 고착이 확인될 때", "A long fixed-price contract (KEPCO market), or SMP settling at the top of its range")),
            "legacy_rec": ((T(f"수치 모델 없음 — REC 조항 {self.t('v4_rec_end')} 효력 종료(부칙 제2조), 기한까지 발급받은 자·고시 인정자는 종전 규정 유지(부칙 제3조②③) {self.g('v4_rec_continue')}",
                              f"No model — REC article lapses {self.t('v4_rec_end')} (addendum art. 2); holders issued by the deadline and recognised licensees keep the former rules (art. 3(2)–(3)) {self.g('v4_rec_continue')}"),
                            T("제도 종료로 수입이 사라지지는 않는다 — 남은 위험은 REC 가격·수요 변화와 고시의 인정 범위(정성 판단)",
                              "Revenue does not vanish with the scheme — what remains is REC price and demand, and the notice's scope (qualitative)"),
                            T("장관 고시(부칙 제3조③ 인정 범위·제4조 이행실적 인정 방법) 확정, REC 거래가격 추이",
                              "The ministerial notice (scope under art. 3(3), counting method under art. 4) and REC prices")) if self.rec_wait() else
                           (T(f"수치 모델 없음 — REC 조항 {self.t('v4_rec_end')} 효력 종료(부칙 제2조) {self.g('v4_rec_end')}", f"No model — REC article lapses {self.t('v4_rec_end')} (addendum art. 2) {self.g('v4_rec_end')}"),
                            T("경과조치가 확인되면 바뀔 수 있다 — 정성 판단", "Could change if a transitional rule is confirmed — qualitative"),
                            T("경과조치 원문 확인", "A transitional rule in the original"))),
            "listed_equip": (T(f"3사 PER {self.t('v1_per')} · 멀티플 기여 3사 순이익 {self.t('v1_mult_ni')} / 4사 영업이익 {self.t('v1_mult_op')} {self.g('v1_mult_op')}",
                               f"3-name P/E {self.t('v1_per')} · multiple share {self.t('v1_mult_ni')} (3-name NI) / {self.t('v1_mult_op')} (4-name OP) {self.g('v1_mult_op')}"),
                             T(f"이익 기준 선택이 결론을 가른다({self.t('v1_mult_ni')} vs {self.t('v1_mult_op')}) · 적용 PER {self.t('v3_per')}이면 같은 이익에서 가치 {self.sgn(self.per_drop())} {self.g('v3_per')}",
                               f"The earnings basis decides it ({self.t('v1_mult_ni')} vs {self.t('v1_mult_op')}) · P/E {self.t('v3_per')} means {self.sgn(self.per_drop())} value on the same earnings {self.g('v3_per')}"),
                             T("PER이 정상화 배수 근처로 내려오거나, 이익 증가가 배수를 따라잡을 때(4사 영업이익 기준 멀티플 기여 50% 아래)", "P/E nears the normalised multiple, or earnings catch up (multiple share below 50% on 4-name operating income)")),
        }
        out = []
        for a in self.f.assets:
            base, flip, trig = rows[a.key]
            out.append({"key": a.key, "name": f"{self.name(a.key)}\nVol.{a.vol} · {self.seat(a.vol)}", "base": base, "flip": flip,
                        "verdict": self.verdict(a.key), "trigger": trig, "v": a.verdict})
        return out

    def p2(self) -> Page:
        rows, gold, strong, brick = [], set(), set(), set()
        for i, r in enumerate(self.map_rows()):
            rows.append([r["name"].replace("\n", " — "), r["base"], r["flip"], r["verdict"], r["trigger"]])
            (gold if r["v"] == "invest" else strong if r["v"] == "wait" else brick).add((i, 3))
        cell = Cell(title=self.T("자산 7개: 기준 수익률 · 결론을 뒤집는 가정과 그 폭 · 판정 · 트리거", "Seven assets: base return · the assumption that flips it and by how much · verdict · trigger"),
                    src=["v1", "v2", "v3", "v4", "ksj"],
                    table=TableSpec([self.T("자산 (편 · 자리)", "Asset (vol. · seat)"), self.T("기준 수익률 · 핵심 숫자", "Base return · key numbers"),
                                     self.T("결론을 뒤집는 가정과 그 폭", "Assumption that flips it, and by how much"), self.T("판정 (J)", "Verdict (J)"),
                                     self.T("트리거 — 판정을 바꾸는 신호 (J)", "Trigger — what would change it (J)")],
                                    rows, [0.14, 0.24, 0.30, 0.08, 0.24], ["L", "L", "L", "C", "L"], gold_cells=gold, strong_cells=strong, brick_cells=brick,
                                    font_size=7.6, max_grow=1.36),
                    note=self.T("판정·트리거 = 저자 판단(J). 판정 규칙(J): 넣는다 = 기준 수익률이 요구수익률·목표 DSCR을 넘고 뒤집는 가정을 계약 조건·선행조건(실사 포함)으로 관리할 수 있음 · 기다린다 = 수익률(또는 제도상 수입)은 있지만 거래 성립 조건·고시가 아직 · "
                                "피한다 = 요구수익률 미달이거나 가격이 배수·시장 가격에 기댐(상장 전력기기주는 4사 영업이익 기준 멀티플 기여 > 50%). " + self.grade_note(),
                                "Verdicts and triggers = judgement (J). Rule (J): invest = clears the hurdle or target DSCR and the flipping assumption can be managed by contract terms or CPs (incl. due diligence) · wait = returns (or statutory revenue) hold but closing conditions or a notice are still pending · avoid = misses the hurdle or leans on multiples or market prices (listed equipment: multiple share > 50% on 4-name operating income). " + self.grade_note()))
        n = {k: len(self.assets_in(k)) for k in ("invest", "wait", "avoid")}
        return Page("full", "2", self.T(f"투자 지도: 넣는다 {n['invest']} · 기다린다 {n['wait']} · 피한다 {n['avoid']} — 판정을 가르는 것은 수익률보다 '뒤집는 가정'의 크기",
                                        f"The map: invest {n['invest']} · wait {n['wait']} · avoid {n['avoid']} — the size of the flipping assumption matters more than the return"),
                    self.T("기준은 원 편 숫자 그대로 · [원 편·쪽·등급] · 판정과 트리거는 저자 판단(J)", "Base numbers as in each volume · [volume · page · grade] · verdicts and triggers are judgement (J)"),
                    [cell], grid="1x1")

    # --- p3 넣는다 ---------------------------------------------------------------
    def ref_table(self, keys: list[str], extra: list[list[str]] | None = None, gold_keys: set[str] | None = None) -> TableSpec:
        rows, gold = [], set()
        for i, k in enumerate(keys):
            rows.append([self.lab(k), self.t(k), self.R(k).where(self.kr), self.R(k).tier])
            if gold_keys and k in gold_keys:
                gold.add((i, 1))
        for e in extra or []:
            rows.append(e)
        return TableSpec([self.T("항목", "Item"), self.T("값", "Value"), self.T("원 편·쪽", "Source"), self.T("등급", "Grade")], rows,
                         [0.50, 0.24, 0.15, 0.11], ["L", "R", "C", "C"], gold_cells=gold, font_size=8.0, single_line_cols={2})

    def pct_fmt(self, d: int = 1):
        return lambda v: f"{v:.{d}f}%"

    def cells_cfd_equity(self) -> tuple[list[Cell], list[Cell]]:
        f, c = self.f, self.c
        h = f.V("v4_hurdle") * 100
        cf_lo, irr_lo = f.V("v4_cfd_cf_low")
        vals = [f.V("v4_irr_merchant"), f.V("v4_irr_cfd"), f.V("v4_irr_ppa"), irr_lo, f.V("v4_cfd_capex_hi")]
        labs = [self.T("시장 판매", "Merchant"), self.T("한전 CfD (기준)", "KEPCO CfD (base)"), self.T("직접 PPA (회랑 중간)", "Direct PPA (mid)"),
                self.T(f"CfD · 이용률 {cf_lo * 100:.0f}%", f"CfD · CF {cf_lo * 100:.0f}%"), self.T("CfD · 사업비 KEEI 상단", "CfD · CAPEX at KEEI top")]
        cols = [c["brick"] if v * 100 < h else (c["gold"] if i == 1 else c["warm_grey"]) for i, v in enumerate(vals)]
        c1 = Cell(title=self.T(f"한전 CfD 지분 IRR {self.t('v4_irr_cfd')} — 요구수익률 {self.hurdle}을 넘지만, 이용률 {cf_lo * 100:.0f}%면 {irr_lo * 100:.1f}%로 미달",
                               f"KEPCO CfD equity IRR {self.t('v4_irr_cfd')} clears the {self.hurdle} hurdle — but a {cf_lo * 100:.0f}% capacity factor cuts it to {irr_lo * 100:.1f}%"),
                  src=["v4"], unit="%", legend=[(c["gold"], self.T("기준", "Base")), (c["brick"], self.T("요구수익률 미달", "Below hurdle"))],
                  chart_key="cfd", chart=charts.hbar_ref(labs, [v * 100 for v in vals], cols, c, self.pct_fmt(), [(h, self.T(f"요구수익률 {h:.0f}%", f"Hurdle {h:.0f}%"), c["brick"])]),
                  note=self.T(f"Vol.4 p4 지분 IRR·민감도(한 번에 한 입력) {self.g('v4_irr_cfd')}. 이용률 범위 = KEEI(A), 사업비 상단 = KEEI LCOE 상단에 맞춘 값",
                              f"Vol.4 p.4 equity IRR and one-at-a-time sensitivities {self.g('v4_irr_cfd')}. CF range = KEEI (A); CAPEX top = fitted to the KEEI LCOE top"))
        c2 = Cell(title=self.T(f"넣는 이유: 매출이 한전 20년 계약 — 대출 {self.t('v4_cfd_gearing')}에도 최소 DSCR {self.t('v4_cfd_dscr')}(목표 {self.t('v4_cfd_dscr_target')})",
                               f"Why invest: revenue under a 20-year KEPCO contract — {self.t('v4_cfd_gearing')} gearing still leaves min DSCR {self.t('v4_cfd_dscr')} (target {self.t('v4_cfd_dscr_target')})"),
                  src=["v4"], table=self.ref_table(["v4_irr_cfd", "v4_hurdle", "v4_cfd_gearing", "v4_cfd_dscr", "v4_cfd_dscr_target", "v4_cfd_price", "v4_cf_base", "v4_cfd_cf_low", "v4_cfd_capex_hi"],
                                                   gold_keys={"v4_irr_cfd", "v4_cfd_dscr"}),
                  note=self.T("조건(J): 대출 비율은 P90 발전량 실사 후 확정 · 계약시장 낙찰가가 입찰 상한보다 낮으면 IRR 재계산. 한전 계약가(J) = 2026년 입찰 상한을 2027년 계약시장 대리값으로",
                              "Conditions (J): fix gearing after a P90 resource study · recompute if the auction clears below the cap. KEPCO price (J) = the 2026 cap as a proxy for the 2027 market"))
        return [c1], [c2]

    def cells_dc_pf_loan(self) -> tuple[list[Cell], list[Cell]]:
        f, c = self.f, self.c
        d0, dg, tg = f.V("v2_min_dscr"), f.V("v2_dscr_gross"), f.V("v2_target_dscr")
        c1 = Cell(title=self.T(f"데이터센터 PF 최소 DSCR {self.t('v2_min_dscr')} — 임대료에 전력비가 들어가면 같은 대출에서 {self.t('v2_dscr_gross')}",
                               f"Data-centre PF min DSCR {self.t('v2_min_dscr')} — with power inside the rent, {self.t('v2_dscr_gross')} on the same debt"),
                  src=["v2"], unit=self.T("배", "x"),
                  chart_key="pf", chart=charts.hbar_ref([self.T("전력비 별도 청구 (기준)", "Power billed separately (base)"), self.T("같은 대출 · 전력비 포함 임대", "Same debt · power in rent")],
                                                        [d0, dg], [c["gold"], c["brick"]], c, lambda v: f"{v:.2f}" + self.T("배", "x"),
                                                        [(tg, self.T(f"목표 {tg:.2f}배", f"Target {tg:.2f}x"), c["brown_dark"]), (1.0, "1.00" + self.T("배", "x"), c["brick"])]),
                  note=self.T(f"Vol.2 한국 40MW 케이스 A — 기준 {self.g('v2_min_dscr')}, 전력 포함 스트레스 {self.g('v2_dscr_gross')}. 목표 DSCR은 저자 판단(J)",
                              f"Vol.2 Korean 40 MW case A — base {self.g('v2_min_dscr')}, power-included stress {self.g('v2_dscr_gross')}. Target DSCR is judgement (J)"))
        c2 = Cell(title=self.T(f"선행조건(CP): 임대차계약서의 전력비 별도 청구 — 포함이면 한도 {self.t('v2_debt_gross')}·Equity IRR {self.t('v2_irr_gross')}",
                               f"Condition precedent: power billed separately in the lease — otherwise capacity {self.t('v2_debt_gross')}, equity IRR {self.t('v2_irr_gross')}"),
                  src=["v2"], table=self.ref_table(["v2_debt", "v2_gearing", "v2_min_dscr", "v2_target_dscr", "v2_irr_pt", "v2_dscr_gross", "v2_debt_gross", "v2_irr_gross"],
                                                   gold_keys={"v2_min_dscr", "v2_debt"}),
                  note=self.T("대주 관점: 원리금은 계약 임대료가 갚는다 — 전력비가 임대료 안에 있으면 그 일부가 한전으로 빠져나가 DSCR이 1배 아래로",
                              "Lender's view: contracted rent services the debt — if power sits inside the rent, part of it flows to KEPCO and DSCR drops below 1x"))
        return [c1], [c2]

    def cells_direct_ppa(self) -> tuple[list[Cell], list[Cell]]:
        f, c = self.f, self.c
        r_lo, r_hi = f.V("v4_room")
        net = f.V("v4_net_charge")
        c1 = Cell(title=self.T(f"직접 PPA: 구매자 여유 {self.t('v4_room')} < 공개 사례 부대비용 {self.t('v4_net_charge')}(B) — {self.t('v4_gap')}이 모자란다",
                               f"Direct PPA: buyer's room {self.t('v4_room')} < public-example charges {self.t('v4_net_charge')} (B) — {self.t('v4_gap')} short"),
                  src=["v4"], unit=self.T("원/kWh", "KRW/kWh"),
                  chart_key="ppa", chart=charts.spans([(self.T("구매자 여유", "Buyer's room"), r_lo, r_hi, c["gold"]),
                                                       (self.T("공개 사례 부대비용 (B)", "Public-example charges (B)"), 0.0, net, c["brick"])],
                                                      c, lambda v: f"{v:,.1f}", net * 1.18,
                                                      (r_hi, net, self.T(f"부족 {self.t('v4_gap')}", f"Short by {self.t('v4_gap')}"))),
                  note=self.T(f"Vol.4 p5 {self.g('v4_room')} · 부대비용 = 한전 중개 제3자 PPA 태양광 Case 1(기후솔루션 2021) {self.g('v4_net_charge')} — 직접 PPA 부대비용은 사례보다 작을 수 있음(Vol.4 A4)",
                              f"Vol.4 p.5 {self.g('v4_room')} · charges = KEPCO-brokered third-party PPA, solar Case 1 (SFOC 2021) {self.g('v4_net_charge')} — direct-PPA charges may be lower (Vol.4 A4)"))
        c2 = Cell(title=self.T(f"트리거: 망이용료 인하 · 망 미이용 공급 — 망을 쓰지 않으면 송·배전 이용요금·부가정산금이 빠진다(고시 단서, A)",
                               "Triggers: lower network charges · supply without the grid — no grid use drops T&D and settlement charges (notice proviso, A)"),
                  src=["v4"], table=self.ref_table(["v4_irr_ppa", "v4_ppa_mid", "v4_ppa_need", "v4_room", "v4_net_charge", "v4_gap"], gold_keys={"v4_room", "v4_gap"}),
                  note=self.T(f"고시 단서: {self.t('v4_proviso')} {self.g('v4_proviso')}. 판정이 바뀌는 선(J): 부대비용 ≤ 구매자 여유 최대 {r_hi:,.1f}원",
                              f"Notice proviso: {self.t('v4_proviso')} {self.g('v4_proviso')}. Line that changes the verdict (J): charges ≤ the buyer's maximum room {r_hi:,.1f}"))
        return [c1], [c2]

    def cells_target_ipo(self) -> tuple[list[Cell], list[Cell]]:
        f, c = self.f, self.c
        d_lo, d_hi = f.V("v3_band_disc")
        q_alt, q_dp = f.V("v3_req_alt"), f.V("v3_req_dp")
        lo_g, hi_g = self.ipo_gap()
        c1 = Cell(title=self.T(f"Target Co. IPO: 필요 할인율 {self.t('v3_req_alt')}~{self.t('v3_req_dp')} > 밴드 할인율 {self.t('v3_band_disc')} — 이익률 하한 확인 전엔 밴드가 높다",
                               f"Target Co. IPO: required discount {self.t('v3_req_alt')}–{self.t('v3_req_dp')} > range discount {self.t('v3_band_disc')} — the range is high until the margin floor is known"),
                  src=["v3"], unit="%",
                  chart_key="ipo", chart=charts.spans([(self.T("밴드 할인율", "Range discount"), d_lo * 100, d_hi * 100, c["gold"]),
                                                       (self.T("필요 할인율 P50", "Required discount P50"), q_alt * 100, q_dp * 100, c["brick"])],
                                                      c, lambda v: f"{v:.1f}%", q_dp * 100 * 1.18,
                                                      (d_hi * 100, q_alt * 100, self.T(f"격차 {self.pp(lo_g)}~", f"Gap {self.pp(lo_g)}+"))),
                  note=self.T(f"Vol.3 p6 밴드 {self.g('v3_band')} · p7 이중 고점(순이익률 삼각분포) 몬테카를로 {self.g('v3_req_dp')}. 격차 {self.pp(lo_g)}~{self.pp(hi_g)}",
                              f"Vol.3 p.6 range {self.g('v3_band')} · p.7 double-peak (triangular margin) Monte Carlo {self.g('v3_req_dp')}. Gap {self.pp(lo_g)}–{self.pp(hi_g)}"))
        c2 = Cell(title=self.T("트리거: 이익률 하한 확인 — 다음 결산에서 순이익률 바닥이 확인돼 필요 할인율이 밴드 안으로 들어올 때",
                               "Trigger: confirm the margin floor — when the next results pin down the trough and the required discount falls inside the range"),
                  src=["v3"], table=self.ref_table(["v3_band", "v3_value", "v3_band_disc", "v3_npm_now", "v3_npm_floor", "v3_req_dp", "v3_req_alt"], gold_keys={"v3_req_dp", "v3_req_alt"}),
                  note=self.T("ECM 관점(J): 밴드를 낮춰 제시하기보다, 이익률 하한의 근거(수주잔고·가격 결정력)를 먼저 확인 — 하한이 FY2023A 수준이어도 격차가 남는다",
                              "ECM view (J): before cutting the range, evidence the margin floor (backlog, pricing power) — even an FY2023A floor leaves a gap"))
        return [c1], [c2]

    def cells_merchant_solar(self) -> tuple[list[Cell], list[Cell]]:
        f, c = self.f, self.c
        h = f.V("v4_hurdle") * 100
        smp_hi, m_hi = f.V("v4_merchant_smp_hi")
        smp_lo, m_lo = f.V("v4_merchant_smp_lo")
        vals = [f.V("v4_irr_merchant"), m_lo, m_hi, f.V("v4_merchant_actual"), f.V("v4_irr_cfd")]
        labs = [self.T("시장 판매 (기준)", "Merchant (base)"), self.T(f"SMP {smp_lo:,.1f}원 (범위 하단)", f"SMP {smp_lo:,.1f} (range low)"),
                self.T(f"SMP {smp_hi:,.1f}원 (범위 상단)", f"SMP {smp_hi:,.1f} (range top)"), self.T("2022년 실제 설치비", "2022 actual unit cost"), self.T("참고: 한전 CfD", "Ref.: KEPCO CfD")]
        cols = [c["brick"] if v * 100 < h else c["warm_grey"] for v in vals[:4]] + [c["warm_grey_light"]]
        c1 = Cell(title=self.T(f"시장 판매 IRR {self.t('v4_irr_merchant')} < 요구 {self.hurdle} — SMP가 범위 상단 {smp_hi:,.1f}원에 머물러야 {m_hi * 100:.1f}%",
                               f"Merchant IRR {self.t('v4_irr_merchant')} < {self.hurdle} hurdle — only SMP held at the {smp_hi:,.1f} top gives {m_hi * 100:.1f}%"),
                  src=["v4"], unit="%", legend=[(c["brick"], self.T("요구수익률 미달", "Below hurdle"))],
                  chart_key="merchant", chart=charts.hbar_ref(labs, [v * 100 for v in vals], cols, c, self.pct_fmt(), [(h, self.T(f"요구 {h:.0f}%", f"Hurdle {h:.0f}%"), c["brick"])]),
                  note=self.T(f"Vol.4 p4 {self.g('v4_irr_merchant')} · SMP 범위 = EPSIS 최근 12개월 육지(A) · 2027년 이후 신규 사업자 {self.t('v4_rec_none')} {self.g('v4_rec_none')}",
                              f"Vol.4 p.4 {self.g('v4_irr_merchant')} · SMP range = EPSIS 12-month mainland (A) · {self.t('v4_rec_none')} for post-2027 entrants {self.g('v4_rec_none')}"))
        return [c1], []

    def cells_listed_equip(self) -> tuple[list[Cell], list[Cell]]:
        f, c = self.f, self.c
        ni_e, ni_m = f.V("v1_earn_ni"), f.V("v1_mult_ni")
        op_m = f.V("v1_mult_op")
        c1 = Cell(title=self.T(f"PER {self.t('v1_per')}: 멀티플 기여는 기준에 따라 {self.t('v1_mult_ni')}~{self.t('v1_mult_op')} — 추격 매수는 배수가 유지된다는 데 거는 것",
                               f"P/E {self.t('v1_per')}: the multiple's share is {self.t('v1_mult_ni')}–{self.t('v1_mult_op')} by basis — chasing bets the multiple holds"),
                  src=["v1"], legend=[(c["brown_mid"], self.T("이익 기여", "Earnings")), (c["gold"], self.T("멀티플 기여", "Multiple"))], unit=self.T("Δln 시총 대비 %", "% of Δln market cap"),
                  chart_key="per", chart=charts.contrib_bars([self.T(f"3사 · 순이익 (시작 시총 {self.t('v1_cover')})", f"3 names · NI ({self.t('v1_cover')} of cap)"), self.T("4사 · 영업이익", "4 names · OP")],
                                                             [ni_e * 100, (1 - op_m) * 100], [ni_m * 100, op_m * 100], c, (self.T("이익", "Earnings"), self.T("멀티플", "Multiple"))),
                  note=self.T(f"Vol.1 p4 {self.g('v1_mult_op')} — 두산에너빌리티(FY2022A 지배순손실)는 순이익 기준 분해 불가. 정상화 PER {self.g('v3_per')}",
                              f"Vol.1 p.4 {self.g('v1_mult_op')} — Doosan Enerbility (FY2022A net loss) cannot be split on net income. Normalised P/E {self.g('v3_per')}"))
        return [c1], []

    def cells_legacy_rec(self) -> tuple[list[Cell], list[Cell]]:
        f = self.f
        yr = f.V("v4_rec_end")
        if self.rec_wait():
            c1 = Cell(title=self.T("기존 REC 의존 자산: 기존 발급자·고시 인정자는 종전 규정 유지(부칙 제3조②③, A) — 고시가 나올 때까지 기다린다",
                                   "Existing REC-dependent assets: existing holders and recognised licensees keep the former rules (addendum art. 3(2)–(3), A) — wait for the notice"),
                      src=["v4"], panel_lead="", bullets=[
                          self.T(f"REC 조항(제12조의7)은 {yr}년 말까지 효력, REC 발급기한은 2026-12-31(재생에너지법 부칙 제2조·제3조①) {self.g('v4_rec_end')}",
                                 f"The REC article (12-7) stays in force to end-{yr}; the issuance deadline is 31 Dec 2026 (RE Act addendum arts. 2, 3(1)) {self.g('v4_rec_end')}"),
                          self.T(f"기한까지 발급받은 자는 종전 규정에 따라 계속 발급·거래하고, 시행 전 허가를 받은 발전사업자 중 장관 고시로 인정한 자도 같다(부칙 제3조②③) — '제도 종료로 수입 소멸' 논리는 성립하지 않는다 {self.g('v4_rec_continue')}",
                                 f"Holders issued RECs by the deadline keep issuing and trading under the former rules, as do pre-act licensees recognised by ministerial notice (addendum art. 3(2)–(3)) — 'the scheme ends, so the revenue goes' does not hold {self.g('v4_rec_continue')}"),
                          self.T("남은 위험(J): REC 가격·수요 변화와 고시의 인정 범위 — 의무량을 넘겨 산 REC의 이행실적 인정(부칙 제4조)도 방법은 고시로 정한다. 수치 모델 없이 정성 판단",
                                 "What remains (J): REC price and demand, and the notice's scope — even counting excess RECs toward targets (addendum art. 4) awaits a notice. Qualitative, no model"),
                          self.T("트리거(J): 장관 고시(부칙 제3조③ 인정 범위 · 제4조 이행실적 인정 방법) 확정과 REC 거래가격 추이 — 그 뒤 잔존 발급기간·REC 매출 비중 자료로 가치를 계산한다",
                                 "Trigger (J): the ministerial notice (scope under art. 3(3), counting method under art. 4) and REC prices — then value the asset from remaining issuance years and REC revenue share")])
        else:
            c1 = Cell(title=self.T(f"기존 REC 의존 자산: REC 조항 {yr}년 말 효력 종료(A) — 수치 모델 없이 정성 판단", f"Existing REC-dependent assets: REC article lapses end-{yr} (A) — qualitative"),
                      src=["v4"], panel_lead="", bullets=[
                          self.T(f"REC 조항(제12조의7)은 {yr}년 말까지 효력(부칙 제2조) {self.g('v4_rec_end')}", f"The REC article (12-7) stays in force to end-{yr} (addendum art. 2) {self.g('v4_rec_end')}"),
                          self.T("경과조치가 확인되지 않아 REC 매출이 이어진다고 볼 근거가 없다(J)", "No transitional rule confirmed, so REC revenue cannot be assumed to continue (J)")])
        return [c1], []

    def avoid_row(self, k: str) -> list[str]:
        f = self.f
        return {
            "merchant_solar": [self.name(k), self.T(f"IRR {self.t('v4_irr_merchant')} < {self.hurdle}, REC 없음", f"IRR {self.t('v4_irr_merchant')} < {self.hurdle}, no RECs"),
                               self.T("장기 고정가 계약 확보", "A long fixed-price contract")],
            "legacy_rec": [self.name(k), self.T(f"REC 조항 {self.t('v4_rec_end')} 효력 종료", f"REC article lapses {self.t('v4_rec_end')}"), self.T("경과조치 확인", "A transitional rule")],
            "listed_equip": [self.name(k), self.T(f"멀티플 기여 {self.t('v1_mult_ni')}~{self.t('v1_mult_op')} · 정상화 시 {self.sgn(self.per_drop())}",
                                                  f"Multiple share {self.t('v1_mult_ni')}–{self.t('v1_mult_op')} · {self.sgn(self.per_drop())} if normalised"),
                             self.T(f"PER이 정상화 {f.V('v3_per')[1]:.1f}배 근처로", f"P/E near the normalised {f.V('v3_per')[1]:.1f}x")],
        }.get(k, [self.name(k), "—", "—"])

    DRIVER = {"merchant_solar": ("SMP", "SMP"), "legacy_rec": ("REC", "RECs"), "listed_equip": ("배수", "multiples")}
    COND = {"cfd_equity": ("CfD는 이용률(P90 실사)", "output for the CfD (P90 study)"),
            "dc_pf_loan": ("PF는 전력비 별도 청구 조항(인출 선행조건)", "separate power billing for the PF loan (CP to drawdown)"),
            "direct_ppa": ("PPA는 망이용료", "network charges for the PPA"), "target_ipo": ("IPO는 이익률 하한", "the margin floor for the IPO"),
            "legacy_rec": ("기존 REC 자산은 장관 고시", "the ministerial notice for REC assets")}

    def verdict_page(self, v: str) -> Page:
        """판정별 쪽: 자산별 주 셀(차트·패널) + 상세 셀(표). 피한다 쪽은 요약표를 덧붙인다. 셀 수로 격자를 정한다."""
        aa = self.assets_in(v)
        mains, details = [], []
        for a in aa:
            m, d = getattr(self, f"cells_{a.key}")()
            mains.append(m)
            details.append(d)
        if v == "avoid":
            rows = [self.avoid_row(a.key) for a in aa]
            details.append([Cell(title=self.T(f"피하는 이유와 다시 볼 신호 — {len(rows)}개 모두 계약으로 정할 수 없는 가격에 기댄다", f"Why avoid, and what would bring them back — all {len(rows)} lean on prices nobody can contract"),
                                 src=["v1", "v3", "v4"], table=TableSpec([self.T("자산", "Asset"), self.T("피하는 이유", "Why avoid"), self.T("다시 볼 신호 (J)", "Signal to revisit (J)")], rows,
                                                                         [0.30, 0.40, 0.30], ["L", "L", "L"], brick_cells={(i, 1) for i in range(len(rows))}, font_size=8.2),
                                 note=self.T("피한다 = 영구 제외가 아니라 지금 가격에서 사지 않는다는 뜻(J). 상장 전력기기주는 섹터 수준 판단이며 특정 종목 의견이 아니다",
                                             "Avoid = not at today's price, not never (J). Listed names are a sector-level view, not a call on any stock"))])
        flat_m = [c for m in mains for c in m]
        flat_d = [c for d in details for c in d]
        if len(flat_m) == len(flat_d) and all(len(m) == 1 and len(d) == 1 for m, d in zip(mains, details)):
            cells = [c for m, d in zip(flat_m, flat_d) for c in (m, d)]           # 자산마다 한 줄: 차트 | 표
        else:
            cells = flat_m + flat_d                                               # 위: 차트·패널, 아래: 표
        grid = {1: "1x1", 2: "1x2", 3: "2-1", 4: "2x2", 5: "3-2", 6: "3x2"}[len(cells)]
        tail = self.T(*self.PAGE_TAIL[v])
        title = f"{self.T(VERDICT_KR[v], VERDICT_EN[v])}: " + " · ".join(self.seg(a.key) for a in aa) + f" — {tail}"
        if v == "avoid":
            sub = self.T("공통점: 계약으로 막을 수 없는 가격(" + "·".join(self.DRIVER[a.key][0] for a in aa if a.key in self.DRIVER) + ")에 수익이 달려 있다",
                         "Common thread: returns hang on prices no contract can fix (" + ", ".join(self.DRIVER[a.key][1] for a in aa if a.key in self.DRIVER) + ")")
        elif v == "wait":
            sub = self.T("트리거가 오면 넣는다로: ", "Triggers move them to invest: ") + self.T(", ", "; ").join(self.T(*self.COND[a.key]) for a in aa if a.key in self.COND)
        else:
            sub = self.T(f"조건은 {len(aa)}개: ", f"{len(aa)} conditions: ") + self.T(", ", "; ").join(self.T(*self.COND[a.key]) for a in aa if a.key in self.COND)
        return Page("body", self.VPAGE[v], title, sub, cells, grid=grid)

    def p3(self) -> Page:
        return self.verdict_page("invest")

    def p4(self) -> Page:
        return self.verdict_page("wait")

    def p5(self) -> Page:
        return self.verdict_page("avoid")

    # --- p6 숫자는 어떻게 지켰나 -------------------------------------------------
    GRADE_COLORS = {"A": "gold", "D": "brown_mid", "B": "warm_grey", "C": "brick", J_DESIGN: "brown_dark", J_ASSUME: "charcoal", NO_VALUE: "warm_grey_light"}

    def code(self, k: str) -> str:
        """등급 칸 표기 (J-설계·J-가정은 영문 별칭)."""
        return k if self.kr else CODE_EN.get(k, k)

    def p6(self) -> Page:
        f, c = self.f, self.c
        rows, ok_cells = [], set()
        for i, r in enumerate(f.corrections):
            com = r["commit_first"] if r["commit_first"] == r["commit_last"] else f"{r['commit_first']}·{r['commit_last']}"
            chk = {True: self.T("일치", "match"), False: self.T("불일치", "mismatch"), None: self.T("미확인", "n/a")}[r["verified"]]
            rows.append([f"Vol.{r['vol']}", f"{com}\n{r['date']}".replace("\n", " · "), r["issue_kr"] if self.kr else r["issue_en"],
                         r["before_kr"] if self.kr else r["before_en"], r["after_kr"] if self.kr else r["after_en"], chk])
            if r["verified"]:
                ok_cells.add((i, 5))
        n_ok = len(ok_cells)
        c1 = Cell(title=self.T(f"정정 {len(rows)}건: 게시 후 독립 검토로 결론을 바꾸는 가정을 찾았고, 전→후를 감추지 않고 남겼다 (git 대조 {n_ok}/{len(rows)} 일치)",
                               f"{len(rows)} corrections: independent reviews after publishing found assumptions that changed conclusions — kept on record, before → after (git check {n_ok}/{len(rows)})"),
                  src=["git"],
                  table=TableSpec([self.T("편", "Vol."), self.T("커밋 · 날짜", "Commit · date"), self.T("무엇을 고쳤나", "What changed"), self.T("전", "Before"), self.T("후", "After"),
                                   self.T("git 대조", "git check")], rows, [0.05, 0.14, 0.20, 0.26, 0.28, 0.07], ["C", "L", "L", "L", "L", "C"],
                                  gold_cells=ok_cells, font_size=7.4, max_grow=1.1),
                  note=self.T("git 대조 = 첫 커밋의 부모와 마지막 커밋의 각 편 빌드 요약에서 '전' 문구가 사라지고 '후' 문구가 생겼는지 코드로 확인. 숫자는 각 시점 보고서 값",
                              "git check = code confirms the 'before' text leaves and the 'after' text appears in the volume's build summary between the first commit's parent and the last commit. Numbers are as published at each point"))
        keys = [k for k in bucket_keys(f.extra["order"]) if k != NO_VALUE or f.total.get(NO_VALUE)]
        cats = [f"Vol.{n} · {self.T(['공식 소스', '가정표(한·미)', '가정표', '입력표'][n - 1], ['official sources', 'assumptions (KR+US)', 'assumptions', 'inputs'][n - 1])}" for n in (1, 2, 3, 4)] + [self.T("전체", "All")]
        series = []
        for k in keys:
            vals = [f.dist[n][k] for n in (1, 2, 3, 4)] + [f.total[k]]
            series.append((k, vals, c[self.GRADE_COLORS[k]]))
        rows_d = [f.dist[n] for n in (1, 2, 3, 4)] + [f.total]
        tots = []
        for d in rows_d:
            ns, nad = sourceable(d)
            tots.append(self.T(f"{sum(d.values())}개 · A·D {nad}/{ns}", f"{sum(d.values())} · A·D {nad}/{ns}"))
        tot = f.total
        n_all = sum(tot.values())
        n_src, n_ad = sourceable(tot)
        legend = [(c[self.GRADE_COLORS[k]], f"{self.code(k)} {self.tier_name(k)}") for k in keys]
        brk = " · ".join(f"{self.code(k)} {tot[k]}" for k in keys if k != NO_VALUE) + (self.T(f" · 미입력 {tot[NO_VALUE]}", f" · not set {tot[NO_VALUE]}") if tot.get(NO_VALUE) else "")
        c2 = Cell(title=self.T(f"입력 {n_all}개: {brk} — 가상 자산 정의값(J-설계)을 빼면 출처가 있을 수 있는 입력 {n_src}개, 그중 J-가정 {tot[J_ASSUME] / n_src * 100:.0f}% → 판정마다 '뒤집는 가정'을 붙였다",
                               f"{n_all} inputs: {brk} — excluding hypothetical-asset definitions, {n_src} inputs could have a source; J-assumption is {tot[J_ASSUME] / n_src * 100:.0f}% of them, hence a flipping assumption on every verdict"),
                  src=["v1", "v2", "v3", "v4"], legend=legend, unit=self.T("개 (막대 끝: 전체 · A·D/출처 가능)", "count (bar end: total · A·D/sourceable)"),
                  chart_key="grades", chart=charts.stacked_h(cats, series, c, tots),
                  note=self.T("코드 집계. Vol.4 = 입력 CSV 등급 그대로 · Vol.1 = 공식 원자료 소스(공시·공공기관·IEA) A · Vol.2·3 = 가정표 상태를 옮김(데이터·실증 → D, 근거 있음 → 공식 도메인이면 A 아니면 B, "
                              "원문 확인 → B, 저자 판단·중립값 → J-가정, 설계값 → J-설계). J-설계 = 용량·일정·구조처럼 가상 자산·기업·거래를 정의하는 값(Vol.4는 출처란 '저자 설계' 표기) — 출처가 존재할 수 없어 분모에서 뺌. "
                              "분모 = 값이 있는 입력 − J-설계. 변환·분류 규칙은 저자 판단(J)",
                              "Counted in code. Vol.4 = grades in its input file · Vol.1 = official raw-data sources (filings, public bodies, IEA) A · Vol.2–3 = assumption status mapped (data/evidence → D, sourced → A if an official "
                              "domain else B, verify → B, judgement/neutral → J-assumption, design → J-design). J-design = values that define the hypothetical asset, company or deal (size, timing, structure; "
                              "Vol.4: 'author's design' in the source field) — no source can exist, so excluded from the base. Base = inputs with a value − J-design. Mapping rules are judgement (J)"))
        pct_ad = n_ad / n_src * 100
        return Page("body", "6", self.T(f"숫자는 어떻게 지켰나: 출처가 있을 수 있는 입력 {n_src}개 중 공식 원문·계산(A·D) {n_ad}개({pct_ad:.0f}%) — 정정 {len(rows)}건은 모두 커밋으로 남겼다",
                                        f"How the numbers were kept: {n_ad} of {n_src} inputs that could have a source ({pct_ad:.0f}%) are official or computed (A·D) — all {len(rows)} corrections kept as commits"),
                    self.T("편별 정정 기록(git·빌드 요약 기준, 전→후) · Vol.1~4 입력 신뢰 등급 분포(J = 가상 자산 정의값 · 시장·재무 가정 판단)",
                           "Corrections by volume (git and build summaries, before → after) · source grades of Vol.1–4 inputs (J split into definitions and assumptions)"),
                    [c1, c2], grid="2x1")

    # --- A1 IC 메모 ---------------------------------------------------------------
    def a1(self) -> Page:
        f = self.f
        rec = {"cfd_equity": self.T("기본안으로 투자 — P90 발전량 실사 후 대출 비율 확정", "Invest as the base case — fix gearing after a P90 resource study"),
               "dc_pf_loan": self.T("대출 승인 — 전력비 별도 청구 조항을 인출 선행조건으로", "Approve — separate power billing as a CP to drawdown"),
               "direct_ppa": self.T("보류 — 부대비용 확정·구매자 RE100 지불의사 확인 후 재상정", "Hold — resubmit once charges and the buyer's RE100 premium are confirmed"),
               "target_ipo": self.T("밴드 제시 보류 — 이익률 하한 근거 확인 후 재산정", "Hold the range — re-price once the margin floor is evidenced"),
               "merchant_solar": self.T("투자하지 않음 — 장기 계약 없이는 요구수익률 미달", "Do not invest — misses the hurdle without a long contract"),
               "legacy_rec": (self.T("편입 보류 — 허가 시점·고시 인정 여부 실사, 고시 확정 후 재상정", "Hold — check licence date and recognition; resubmit once the notice is out") if self.rec_wait()
                              else self.T("신규 편입 안 함 — 경과조치 확인 전", "Do not add — until a transitional rule is confirmed")),
               "listed_equip": self.T("추격 매수 안 함 — 정상화 배수 근처에서 재검토", "Do not chase — revisit near the normalised multiple")}
        rows, gold, strong, brick = [], set(), set(), set()
        for i, a in enumerate(f.assets):
            rows.append([self.name(a.key), self.verdict(a.key), rec[a.key]])
            (gold if a.verdict == "invest" else strong if a.verdict == "wait" else brick).add((i, 1))
        c1 = Cell(title=self.T("권고 (저자 판단 J)", "Recommendation (judgement, J)"), src=["ksj"],
                  table=TableSpec([self.T("자산", "Asset"), self.T("판정", "Verdict"), self.T("권고", "Recommendation")], rows, [0.30, 0.13, 0.57], ["L", "C", "L"],
                                  gold_cells=gold, strong_cells=strong, brick_cells=brick, font_size=7.8))
        risks = [[self.T("이용률 하락", "Lower output"), f"{self.t('v4_cfd_cf_low')}", self.g("v4_cfd_cf_low", False)],
                 [self.T("전력비가 임대료 안에", "Power inside the rent"), self.T(f"같은 대출 최소 DSCR {self.t('v2_dscr_gross')}", f"Min DSCR {self.t('v2_dscr_gross')} on the same debt"), self.g("v2_dscr_gross", False)],
                 [self.T("부대비용 > 구매자 여유", "Charges > buyer's room"), self.T(f"{self.t('v4_room')} vs {self.t('v4_net_charge')}", f"{self.t('v4_room')} vs {self.t('v4_net_charge')}"), self.g("v4_room", False)],
                 [self.T("이익률 정점(이중 고점)", "Peak margins (double peak)"), self.T(f"필요 할인율 {self.t('v3_req_dp')}", f"Required discount {self.t('v3_req_dp')}"), self.g("v3_req_dp", False)],
                 [self.T("SMP 하락", "SMP fall"), self.t("v4_merchant_smp_lo"), self.g("v4_merchant_smp_lo", False)],
                 [self.T("REC 가격·고시 인정 범위", "REC prices, scope of the notice"), self.T("종전 규정 유지(부칙 제3조②③) — 인정 범위·방법은 고시 대기", "Former rules kept (art. 3(2)–(3)) — scope and method await a notice"), self.g("v4_rec_continue", False)],
                 [self.T("배수 정상화", "Multiple normalises"), self.T(f"PER {self.t('v3_per')} → 가치 {self.sgn(self.per_drop())}", f"P/E {self.t('v3_per')} → value {self.sgn(self.per_drop())}"), self.g("v3_per", False)]]
        c2 = Cell(title=self.T("핵심 위험 — 숫자로", "Key risks, in numbers"), src=["v1", "v2", "v3", "v4"],
                  table=TableSpec([self.T("위험", "Risk"), self.T("영향", "Impact"), self.T("원 편·쪽", "Source")], risks, [0.34, 0.46, 0.20], ["L", "L", "C"], font_size=7.8))
        cps = [[self.T("임대차계약서 전력비 별도 청구 조항", "Separate power billing in the lease"), self.name("dc_pf_loan"), self.g("v2_irr_gross", False)],
               [self.T(f"P90 발전량 실사 (이용률 {f.V('v4_cfd_cf_low')[0] * 100:.0f}% 위)", f"P90 resource study (CF above {f.V('v4_cfd_cf_low')[0] * 100:.0f}%)"), self.name("cfd_equity"), self.g("v4_cfd_cf_low", False)],
               [self.T(f"계약시장 낙찰가 확인 (가정 {self.t('v4_cfd_price')})", f"Auction clearing price (assumed {self.t('v4_cfd_price')})"), self.name("cfd_equity"), self.g("v4_cfd_price", False)],
               [self.T("현재 송배전 이용요금·부가정산금으로 구매자 실효 단가 확정", "Buyer's all-in price at current T&D and settlement rates"), self.name("direct_ppa"), self.g("v4_gap", False)],
               [self.T("오프테이커 위약금·모회사 보증", "Termination payment, parent guarantee"), self.name("direct_ppa"), "[Vol.4 pA1]" if self.kr else "[Vol.4 p.A1]"],
               [self.T("다음 결산 순이익률(하한 근거)", "Next results: net-margin floor"), self.name("target_ipo"), self.g("v3_req_alt", False)],
               [self.T("REC 발급 이력(2026-12-31 전)·시행 전 허가·고시 인정 여부", "REC issuance before 31 Dec 2026, pre-act licence, recognition by notice"), self.name("legacy_rec"), self.g("v4_rec_continue", False)]]
        c3 = Cell(title=self.T("선행조건 (CP)", "Conditions precedent (CP)"), src=["v2", "v3", "v4"],
                  table=TableSpec([self.T("선행조건", "Condition"), self.T("대상", "Applies to"), self.T("근거", "Basis")], cps, [0.50, 0.30, 0.20], ["L", "L", "C"], font_size=7.6))
        mon = [[self.T("한전 계약시장 낙찰가", "KEPCO contract-market price"), self.t("v4_cfd_price"), self.T("상한보다 낮으면 CfD IRR 재계산", "Below the cap → recompute CfD IRR")],
               [self.T("직접 PPA 부대비용", "Direct-PPA charges"), self.t("v4_net_charge"), self.T(f"{max(f.V('v4_room')):,.1f}원 이하면 PPA 성립", f"≤ {max(f.V('v4_room')):,.1f} → PPA closes")],
               [self.T("SMP (12개월 육지 평균)", "SMP (12-month mainland)"), self.t("v4_smp_base"), self.T(f"{f.V('v4_merchant_smp_hi')[0]:,.1f}원 이상 지속이면 시장 판매 재검토", f"Sustained ≥ {f.V('v4_merchant_smp_hi')[0]:,.1f} → revisit merchant")],
               [self.T("3사 합산 순이익률", "3-name net margin"), self.t("v3_npm_now"), self.T(f"필요 할인율 ≤ 밴드 최대 {max(f.V('v3_band_disc')) * 100:.1f}%가 되는 하한 확인 시 — FY2023A {f.V('v3_npm_floor')[1] * 100:.1f}%로도 {self.t('v3_req_alt')}라 부족",
                                                                     f"A floor that brings the required discount to ≤ {max(f.V('v3_band_disc')) * 100:.1f}% — even FY2023A {f.V('v3_npm_floor')[1] * 100:.1f}% gives {self.t('v3_req_alt')}")],
               [self.T("전력기기 적용 PER", "Equipment P/E"), f"{f.V('v3_per')[0]:.1f}" + self.T("배", "x"), self.T(f"정상화 {f.V('v3_per')[1]:.1f}배 근처면 재검토", f"Near the normalised {f.V('v3_per')[1]:.1f}x → revisit")],
               [self.T("국고채 3년", "KTB 3-yr"), self.t("v4_ktb"), self.T("금리 변화 → CfD·PF 금리 재계산", "Rate moves → recompute CfD and PF")],
               [self.T("REC 경과조치 고시·REC 가격", "REC transitional notice, REC prices"), self.T("법률 원문(A), 고시 미정", "Act (A), notice pending"),
                self.T("고시 확정(인정 범위·제4조 방법)·가격 추이 → 기존 자산 재평가", "Notice issued (scope, art. 4 method) and prices → re-assess existing assets")]]
        c4 = Cell(title=self.T("모니터링 지표 — 판정을 바꾸는 수준(J)", "Monitoring — levels that change a verdict (J)"), src=["v3", "v4"],
                  table=TableSpec([self.T("지표", "Indicator"), self.T("현재", "Now"), self.T("판정을 바꾸는 수준 (J)", "Level that changes it (J)")], mon, [0.30, 0.26, 0.44], ["L", "R", "L"], font_size=7.6),
                  note=self.T("현재 값은 각 편 기준일(2026-10-20). 수준은 원 편 계산값에서 가져왔고, 그 수준을 판정 변경선으로 쓰는 것은 저자 판단",
                              "'Now' = each volume's as-of date (20 Oct 2026). Levels come from the volumes; using them as verdict lines is judgement"))
        n_in = len(self.assets_in("invest"))
        return Page("body", "A1", self.T(f"IC 메모: {n_in}개 자산에 조건부 투자 — CfD 지분은 P90 실사, PF 대출은 전력비 별도 청구가 선행조건, 나머지는 트리거까지 보류",
                                         f"IC memo: conditional yes on {n_in} assets — P90 study for the CfD equity, separate power billing for the PF loan; the rest wait for triggers"),
                    self.T("권고 · 핵심 위험 · 선행조건(CP) · 모니터링 지표 (예시 — 가상 자산·기업)", "Recommendation · key risks · CPs · monitoring (illustrative — hypothetical assets and company)"),
                    [c1, c2, c3, c4])

    # --- A2 출처 지도 -------------------------------------------------------------
    def a2(self) -> Page:
        f = self.f
        keys = list(f.refs.keys())
        half = (len(keys) + 1) // 2
        cells = []
        for part in (keys[:half], keys[half:]):
            rows, gold, brick, strong = [], set(), set(), set()
            for i, k in enumerate(part):
                r = f.refs[k]
                chk = ("O" if r.page_ok else "X") + (" ·" if r.summary_ok is None else (" O" if r.summary_ok else " X"))
                wk = r.weakest_kr if self.kr else r.weakest_en
                rows.append([self.lab(k), self.t(k), r.where(self.kr), r.tier + (f" ({wk})" if wk and r.tier == "J" else ""), chk])
                (gold if r.tier == "A" else brick if r.tier == "C" else strong if r.tier == "J" else set()).add((i, 3))
            cells.append(Cell(table=TableSpec([self.T("결론값", "Result"), self.T("값", "Value"), self.T("원 편·쪽", "Source"), self.T("등급 (가장 약한 입력)", "Grade (weakest input)"),
                                               self.T("대조", "Check")], rows, [0.33, 0.20, 0.12, 0.27, 0.08], ["L", "R", "C", "L", "C"],
                                              gold_cells=gold, brick_cells=brick, strong_cells=strong, font_size=6.6, max_grow=1.1)))
        n_p = sum(1 for r in f.refs.values() if r.page_ok)
        sm = [r for r in f.refs.values() if r.summary_ok is not None]
        n_s = sum(1 for r in sm if r.summary_ok)
        cells[0].title = self.T(f"결론값 {len(keys)}개 → 원 편·쪽·등급: 원 편 쪽 대조 {n_p}/{len(keys)} · 빌드 요약 대조 {n_s}/{len(sm)}",
                                f"{len(keys)} results → volume, page, grade: page check {n_p}/{len(keys)} · build-summary check {n_s}/{len(sm)}")
        cells[0].src = ["v1", "v2", "v3", "v4"]
        cells[1].title = self.T("등급: A 공식 원문 · D 공식 자료 계산 · B 보도·외부 보고서 · C 민간 2차 · J 저자 판단", "Grades: A official · D computed from official · B press/external · C secondary · J judgement")
        cells[1].note = self.T("대조: 첫 O = 원 편 국문 해당 쪽 문구에 같은 값이 있음, 둘째 O = 원 편 빌드 요약에도 있음(· = 요약에 해당 문구 없음). 둘 다 빌드 때 코드로 확인. "
                               "원 편 쪽에는 반올림 표기일 수 있음(예: 12.25% → 12.2%, 정밀값은 원 편 빌드 요약). 등급 = 주요 입력 중 가장 약한 등급(계산값 최소 D), 괄호 = 그 입력",
                               "Check: first O = the same value appears on that page of the volume (Korean text); second O = also in the volume's build summary (· = not applicable). Both verified in code at build. "
                               "The page may show a rounded figure (e.g. 12.25% → 12.2%; exact values in the build summary). Grade = weakest main input (computed values at least D); brackets name that input")
        return Page("body", "A2", self.T("출처 지도: 모든 결론값을 원 편·쪽·신뢰 등급으로 되짚는다", "Source map: every result traced to its volume, page and source grade"),
                    self.T(f"Vol.1~4 각 편 계산(기준일 2026-10-20)에서 불러온 값 — 지어낸 숫자 없음", "Values loaded from each volume's calculation (as of 20 Oct 2026) — no invented numbers"),
                    cells, grid="1x2")

    # --- A3 용어 ---------------------------------------------------------------
    def a3(self) -> Page:
        terms = [
            (self.T("넣는다 · 기다린다 · 피한다", "Invest · wait · avoid"), self.T("저자 판단(J)의 세 판정 — 수익률·성립 조건·뒤집는 가정으로 가른다(p2 규칙)", "The three verdicts (judgement, J), set by return, closing conditions and flipping assumptions (rule on p2)")),
            (self.T("트리거", "Trigger"), self.T("판정을 바꾸는 관찰 가능한 신호 (저자 판단)", "An observable signal that would change a verdict (judgement)")),
            (self.T("뒤집는 가정", "Flipping assumption"), self.T("결론(판정)이 바뀌는 입력과 그 변화 폭 — 원 편 민감도에서 가져옴", "The input, and the move in it, that changes the conclusion — from each volume's sensitivities")),
            (self.T("신뢰 등급", "Source grade"), self.T("A 공식 원문 · D 공식 자료로 계산 · B 보도·외부 보고서 · C 민간 2차(잠정) · J 저자 판단", "A official · D computed from official data · B press/external report · C secondary (provisional) · J judgement")),
            ("CfD", self.T("차액계약 — 계약가와 SMP의 차이를 정산. 2027년부터 신규 태양광은 한전 장기 계약이 기본", "Contract for difference with KEPCO; from 2027 the default for new solar")),
            ("PPA", self.T("전력구매계약 — 발전사와 구매자가 가격·기간·물량을 직접 정하는 계약", "Power purchase agreement — seller and buyer fix price, term and volume directly")),
            ("SMP · REC", self.T("계통한계가격(도매 전력가격) · 신재생에너지 공급인증서(발급기한 2026-12-31, 기존 발급자·고시 인정자는 종전 규정 — 재생에너지법 부칙 제3조)",
                                 "System marginal price (wholesale power) · renewable certificate (issuance deadline 31 Dec 2026; existing holders and recognised licensees keep the former rules — RE Act addendum art. 3)")),
            ("DSCR", self.T("원리금상환비율 = 상환 가능 현금흐름 ÷ 원리금. 대주는 최소값과 목표값을 본다", "Debt service coverage = cash flow available ÷ debt service; lenders watch the minimum against a target")),
            (self.T("선행조건 (CP)", "Condition precedent (CP)"), self.T("대출 인출·투자 실행 전에 충족해야 하는 조건", "A condition to be met before drawdown or closing")),
            (self.T("지분 IRR · 요구수익률", "Equity IRR · hurdle"), self.T("지분 투자 수익률 · 투자자가 요구하는 최소 수익률(Vol.4 저자 판단)", "Return on equity · minimum return required (judgement in Vol.4)")),
            (self.T("희망공모가 밴드 · 할인율", "Price range · discount"), self.T("공모가 범위 · 1 − 밴드 ÷ 주당 평가가액", "IPO price range · 1 − range ÷ value per share")),
            (self.T("이중 고점 · 필요 할인율", "Double peak · required discount"), self.T("이익과 배수가 함께 정점일 위험 · 1년 후 가치 분포에서 손실을 피하는 데 필요한 할인율(P50)", "Risk that earnings and multiples peak together · discount needed to avoid a loss in the 1-year value distribution (P50)")),
            (self.T("멀티플 기여", "Multiple contribution"), self.T("Δln(시총) 중 Δln(PER)의 비중 — 이익 기준(순이익·영업이익)에 따라 달라진다", "Share of Δln(cap) due to Δln(P/E) — depends on the earnings basis (NI or OP)")),
            (self.T("망이용료 · 부대비용", "Network and ancillary charges"), self.T("직접 PPA 구매자가 내는 송·배전 이용요금·거래수수료·부가정산금·기반기금", "T&D use charges, trading fee, settlements and fund levy a direct-PPA buyer pays")),
        ]
        cell = Cell(title=self.T("용어 정의", "Glossary"),
                    table=TableSpec([self.T("용어", "Term"), self.T("정의", "Definition")], [list(t) for t in terms], [0.22, 0.78], ["L", "L"], shade_rows={0, 1, 2, 3}, font_size=8.4),
                    note=self.T("음영 = 이번 편에서 새로 쓰는 말. 나머지는 Vol.1~4 용어 정의와 같다", "Shaded = terms new in this volume; the rest match the Vol.1–4 glossaries"))
        return Page("full", "A3", self.T("용어 정의: 지도를 읽는 말", "Glossary: the words on the map"),
                    self.T("가격 원/kWh · 금액 억원 · 비율 % · 배수 배", "Prices KRW/kWh · amounts KRW 100mn · ratios % · multiples x"), [cell], grid="1x1")

    # --- 맺음말 ---------------------------------------------------------------
    def afterword(self) -> Page:
        return Page("afterword", label="", title=self.T("맺으며", "Afterword"),
                    extra={"kicker": "AFTERWORD" if self.kr else "", "paras": AFTERWORD_KR if self.kr else AFTERWORD_EN, "sign": SIGN_KR if self.kr else SIGN_EN})
