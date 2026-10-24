# 강신재 AI 에너지 자산 포트폴리오 | KSJ AI Energy Asset Portfolio

IB·인프라금융 직무 준비를 위한 개인 리서치 포트폴리오입니다. 분석 로직과 코드를 공개합니다. (A personal research portfolio prepared for IB and infrastructure-finance roles; analysis logic and code are public.)

> **핵심 질문: AI 데이터센터 전력 수요는 진짜인가, 그리고 주식시장은 그것을 이미 가격에 반영했나?**
>
> 기준일 2026-10-20 · 저자 강신재(Shinjae Kang) · 교육·연구 목적, 투자 권유 아님 · [English below](#english)

## 핵심 발견 (Vol.1)

아래 세 줄은 보고서 빌드 때 공식 출처 데이터에서 다시 계산해 채워집니다.

<!-- vol01:findings:kr -->
1. **수요는 진짜다 — 2030년 945TWh, AI 데이터센터 수요 +50%**<br><sub>데이터센터 전력 소비 2030E ÷ 2024 (IEA 기준 시나리오): 2.3배</sub>
2. **현장에서도 보인다 — 미국 전체(+10%)를 지수 63포인트 앞섰다**<br><sub>버지니아 상업용 전력 판매 2015→2025 (EIA): +73%</sub>
3. **이익이 이끌었다 — 3사(두산에너빌리티 제외) 시총 증가의 61%가 이익 증가**<br><sub>4사 시총 합계 기준, 2023-01-02→2026-10-19 (회사별 4.4배~26.1배): 7.7배</sub>
<!-- /vol01:findings:kr -->

![Vol.1 p4 대표 Exhibit: 국내 전력기기 상장사 시가총액](docs/img/vol01_p4_kr.png)

<sub>Vol.1 4쪽 "시장" 대표 Exhibit — 그림은 빌드 때 데이터에서 다시 그려집니다.</sub>

## Research Notes

| Vol | 제목 | 날짜 | 국문 | English | 게시물 |
|---|---|---|---|---|---|
| 1 | AI 전력 수요는 진짜인가, 시장은 이미 알고 있나 | 2026.10 | [PDF](research/vol01/KSJ_Research_Vol01_KR.pdf) | [PDF](research/vol01/KSJ_Research_Vol01_EN.pdf) | [LinkedIn](https://lnkd.in/p/g48PyHjZ) |
| 2 | AI 데이터센터, 대출은 얼마까지 가능한가 — 대주의 눈으로 본 한국 40MW와 미국 100MW | 2026.10 | [PDF](research/vol02/KSJ_Research_Vol02_KR.pdf) | [PDF](research/vol02/KSJ_Research_Vol02_EN.pdf) | [LinkedIn](https://www.linkedin.com/feed/update/urn:li:activity:7518930802538201088/) |
| 3 | PER 40배 섹터의 IPO — 가상 전력기기 기업의 희망공모가 밴드 | 2026.10 | [PDF](research/vol03/KSJ_Research_Vol03_KR.pdf) | [PDF](research/vol03/KSJ_Research_Vol03_EN.pdf) | — |
| 4 | 데이터센터에 전기를 파는 법 — 가상 태양광 35MW의 지분투자: 한전 계약·직접 PPA·시장 판매 (공식 원문 반영) | 2026.10 | [PDF](research/vol04/KSJ_Research_Vol04_KR.pdf) | [PDF](research/vol04/KSJ_Research_Vol04_EN.pdf) | — |

**시리즈 로드맵**: Vol.1 수요·시장 → Vol.2 데이터센터 PF(한국 40MW·미국 100MW) → Vol.3 IPO 공모가·해외 피어 → Vol.4 데이터센터 전력 공급(발전 자산·PPA) → Vol.5 완결: AI 에너지 자산 투자 지도

## 분석 방법

1. **수집** — IEA·EIA·DART·KRX·한국은행 ECOS·FRED 등 공식 출처 데이터만 사용하고, 모든 수치에 출처와 기준일을 적습니다.
2. **검증** — 시가총액 = 종가 × 상장주식수 검산, 액면분할 대조(LS ELECTRIC 2026-04-13 5:1), 종목 식별자 확인.
3. **계산** — Δln(시총) = Δln(지배순이익) + Δln(PER) 로그 분해로 시총 증가를 이익과 멀티플로 나누고, 국문·영문 보고서로 정리합니다.

구현: AI 코딩 도구(Claude Code)로 데이터 수집·계산·보고서 생성 코드를 작성. 질문 설계, 분석 범위 결정, 숫자 검증은 저자.

<details>
<summary><b>재현 방법</b></summary>

```powershell
git clone https://github.com/Cojae-Kang/ksj-ai-energy-asset-portfolio.git
cd ksj-ai-energy-asset-portfolio
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                                              # API 키 입력 (.env는 커밋되지 않음)
python -m src.data_fetch.fetch_all --source all --asof 2026-10-20   # 공식 출처 데이터 수집
python -m research.vol01.fetch_extra --asof 2026-10-20              # Vol.1 추가 데이터
python -m research.vol01.build                                      # 국문·영문 PDF + README 핵심 발견·그림 갱신
python -m research.vol02.build                                      # Vol.2 데이터센터 PF 국문·영문 PDF (가정: data/manual/vol02_assumptions.csv)
python -m research.vol03.fetch_extra --asof 2026-10-20              # Vol.3 미국 피어 종가(yfinance)·SEC 주식수 이력·D&A (로컬 전용)
python -m research.vol03.ipo_discounts --asof 2026-10-20 --listing-dates   # KRX 종목기본정보 → 상장일 표 (IPO 접수 시점 판정용, 원문 다운로드 절감)
python -m research.vol03.ipo_discounts --asof 2026-10-20            # Vol.3 국내 IPO 할인율 실증 (접수 시점 판정: 상장일 > 접수일 · 원문 IPO 문구, corp_cls 미사용 → docs/qa/vol03_ipo_discounts.md)
python -m research.vol03.ipo_discounts --estimate-log              # 기존 로그로 예전 corp_cls 제외분 중 IPO 추정 (네트워크 없음 → docs/qa/vol03_ipo_pit_estimate.md)
python -m src.data_fetch.dart --debt-candidates 267260             # 총차입금 계정 매핑 점검 (로컬 원자료, API 호출 없음; 회사별 대용 계정은 config total_debt.company_overrides)
python -m src.data_fetch.dart --da-candidates 298040               # D&A(감가상각비·상각비) 계정 후보 점검 (로컬 원자료) → 없으면 data/manual/vol03_peer_manual.csv
python -m research.vol03.build                                      # Vol.3 IPO 희망공모가 밴드 국문·영문 PDF (가정: data/manual/vol03_assumptions.csv)
python -m research.vol04.build                                      # Vol.4 발전자산 지분투자(한전 CfD·직접 PPA·SMP) 국문·영문 PDF (입력·신뢰 등급: data/manual/vol04_inputs.csv)
pytest -q                                                           # 네트워크 없이 도는 테스트
```

데이터 소스별 수집 내용, 폴더 구조, 타임아웃·검증 규칙은 [docs/data_pipeline.md](docs/data_pipeline.md), 수집 요약과 교차검증 기록은 [docs/qa/](docs/qa/)에 있습니다.

</details>

## 데이터 출처와 이용 조건

| 출처 | 제공기관 | 사용 데이터 | 이용 조건 |
|---|---|---|---|
| IEA | International Energy Agency | *Energy and AI* (2025.4), *Key Questions on Energy and AI* (2026.4) 요약 수치 | CC BY 4.0, 출처 표기 (© IEA) |
| EIA | U.S. Energy Information Administration | 미국 주별·부문별 전력 소매판매량 | 미국 정부 공개 데이터, 출처 표기 |
| KRX | 한국거래소 | 종가, 시가총액, 상장주식수 | KRX 정보데이터시스템·Open API 이용약관, 출처 표기 |
| DART | 금융감독원 | 사업보고서 연결 재무제표 | Open DART 이용약관, 출처 표기 |
| ECOS | 한국은행 | 원/달러 환율, 국고채 금리 | 한국은행 ECOS 이용약관, 출처 표기 |
| FRED | Federal Reserve Bank of St. Louis | 미 국채 10년 금리 | FRED 이용약관, 출처 표기 |
| SEC EDGAR | U.S. Securities and Exchange Commission | 미국 피어 10-K 재무(XBRL)·표지 발행주식수 | 미국 정부 공개 데이터, SEC fair access 정책 준수 |
| yfinance (보조) | Yahoo Finance 비공식 래퍼 | 미국 피어 종가 (SEC 발행주식수로 교차 확인) | 개인·연구 용도, Yahoo 약관 적용 |

- 원자료(API 응답 원본)는 저장소에 올리지 않고, 가공 데이터와 출처·기준일만 공개합니다.
- 코드: [MIT License](LICENSE) · 보고서·도표: [CC BY 4.0](LICENSE-CONTENT) · 폰트: Noto Sans KR (SIL Open Font License 1.1, `assets/fonts/`)

## 면책

이 저장소는 교육·연구 목적의 개인 포트폴리오이며 투자 권유가 아닙니다. 본문의 판단은 저자 개인의 견해입니다.
분석 대상 "Target Co."는 가상 기업으로 실존 기업과 관련이 없습니다. 공개 자료를 사용했으나 정확성과 완전성을 보장하지 않으며,
이 자료를 근거로 한 투자 판단의 책임은 투자자 본인에게 있습니다.

---

<a id="english"></a>

## English

> **Core question: Is AI data-centre power demand real — and has the stock market already priced it in?**
>
> As of 2026-10-20 · Author: Shinjae Kang · For education and research only; not investment advice

### Key findings (Vol.1)

Recalculated from official-source data each time the report is built.

<!-- vol01:findings:en -->
1. **Demand is real — 945 TWh by 2030; AI data-centre demand +50%**<br><sub>Data-centre power 2030E ÷ 2024 (IEA Base Case): 2.3x</sub>
2. **It shows up on the ground — 63 index points ahead of the U.S. (+10%)**<br><sub>Virginia commercial power sales 2015→2025 (EIA): +73%</sub>
3. **Earnings led — 61% of the gain for 3 names (ex. Doosan Enerbility) is earnings growth**<br><sub>4 names, combined cap, 2023-01-02→2026-10-19 (range 4.4x–26.1x): 7.7x</sub>
<!-- /vol01:findings:en -->

![Vol.1 p4 representative exhibit: market cap of listed Korean power-equipment names](docs/img/vol01_p4_en.png)

<sub>Vol.1 page 4 "Market" representative exhibit — redrawn from the data at each build.</sub>

### Research Notes

| Vol | Title | Date | Korean | English | Post |
|---|---|---|---|---|---|
| 1 | Is AI Power Demand Real, and Does the Market Already Know? | 2026.10 | [PDF](research/vol01/KSJ_Research_Vol01_KR.pdf) | [PDF](research/vol01/KSJ_Research_Vol01_EN.pdf) | [LinkedIn](https://lnkd.in/p/g48PyHjZ) |
| 2 | How Much Can an AI Data Centre Borrow? A lender's view of a 40 MW Korean and a 100 MW U.S. project | 2026.10 | [PDF](research/vol02/KSJ_Research_Vol02_KR.pdf) | [PDF](research/vol02/KSJ_Research_Vol02_EN.pdf) | [LinkedIn](https://www.linkedin.com/feed/update/urn:li:activity:7518930802538201088/) |
| 3 | Pricing an IPO in a 40x P/E Sector — an indicative price range for a hypothetical power-equipment maker | 2026.10 | [PDF](research/vol03/KSJ_Research_Vol03_KR.pdf) | [PDF](research/vol03/KSJ_Research_Vol03_EN.pdf) | — |
| 4 | Selling Power to a Data Centre — equity in a hypothetical 35 MW solar asset: KEPCO contract, direct PPA or merchant (official sources) | 2026.10 | [PDF](research/vol04/KSJ_Research_Vol04_KR.pdf) | [PDF](research/vol04/KSJ_Research_Vol04_EN.pdf) | — |

**Series roadmap**: Vol.1 demand and market → Vol.2 data-centre PF (Korea 40 MW, U.S. 100 MW) → Vol.3 IPO pricing and overseas peers → Vol.4 powering data centres (generation assets, PPAs) → Vol.5 finale: an AI energy asset investment map

### Methodology

1. **Collect** — official sources only (IEA, EIA, DART, KRX, Bank of Korea ECOS, FRED), each figure with its source and as-of date.
2. **Validate** — market cap = close × listed shares, stock-split check (LS ELECTRIC 5:1 on 2026-04-13), identifier check.
3. **Calculate** — split the market-cap gain into earnings and multiple with Δln(cap) = Δln(NI) + Δln(P/E), then publish Korean and English reports.

Built with an AI coding tool (Claude Code); question design, scope decisions and number verification by the author.

<details>
<summary><b>How to reproduce</b></summary>

See the commands in the Korean section above and [docs/data_pipeline.md](docs/data_pipeline.md) (Korean). API keys are read from `.env` only and are never committed.

</details>

### Data sources and terms

IEA (CC BY 4.0, © IEA) · U.S. EIA (U.S. government data) · KRX · DART (Financial Supervisory Service) · Bank of Korea ECOS · FRED (Federal Reserve Bank of St. Louis) · SEC EDGAR (U.S. government data) · yfinance (secondary, cross-checked with SEC shares). Each is used with attribution under its provider's terms; raw API responses are not redistributed. Code under the [MIT License](LICENSE); reports and charts under [CC BY 4.0](LICENSE-CONTENT); fonts under the SIL Open Font License 1.1.

### Disclaimer

Personal portfolio for education and research; not investment advice. Judgements are the author's own. "Target Co." is hypothetical and unrelated to any real company. Public data are used without any guarantee of accuracy or completeness.

---

## License

| 대상 · Scope | 라이선스 · License |
|---|---|
| 코드 (`src/`, `research/**/*.py`, `tests/` 등) · Code | [MIT License](LICENSE) — 저작권 표시 유지 조건 · keep the copyright notice |
| 보고서·도표·문장 (`research/vol01/`, `research/vol02/`, `research/vol03/` PDF, `figures/`, `reports/`, `docs/`) · Reports, charts, text | [CC BY 4.0](LICENSE-CONTENT) ([https://creativecommons.org/licenses/by/4.0/](https://creativecommons.org/licenses/by/4.0/)) — 인용·활용 시 "Shinjae Kang (KSJ Research)"와 출처 표시 · credit required |
| 제3자 데이터·자료 (IEA, EIA, CBRE, KRX, DART, ECOS, FRED, SEC EDGAR, Yahoo Finance, 보도·업계 보고서 등) · Third-party data | 각 원저작자의 권리와 이용 조건을 따릅니다 · subject to each owner's terms |

© 2026 Shinjae Kang (강신재). 특정 금융회사·부서와 무관한 개인 리서치입니다 · Not affiliated with any financial institution.

**인용 예시 · Suggested citation**

> Kang, Shinjae (2026). KSJ Research Note Vol.2. https://github.com/Cojae-Kang/ksj-ai-energy-asset-portfolio

**연락처 · Contact:** toonword@naver.com
