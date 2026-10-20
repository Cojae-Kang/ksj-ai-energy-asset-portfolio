# AI 데이터센터 전력 밸류체인 — 가상 비상장 전력기기 기업 IPO 밸류에이션 (ECM 관점)

> 기준일: 2026-10-20 · 상태: 🚧 프로젝트 뼈대 (분석 코드 작성 전)

## 프로젝트 소개

AI 데이터센터가 늘면서 전력 수요가 커지고 있습니다. 이 프로젝트는 그 수요가 변압기·배전·발전설비 같은
전력 인프라 밸류체인으로 어떻게 이어지는지 공개 데이터로 정리합니다. 그 다음 **가상의 비상장 전력기기 기업(Target Co.)**을
상정해, 증권사 ECM 실무 방식으로 **IPO 희망공모가 밴드**를 산정합니다.

- **독자**: 증권사 ECM/IB 실무자, 면접관
- **원칙**: 공개 데이터만 사용, 모든 수치에 출처와 기준일 기록, 가정치는 `ASSUMPTION:` 태그로 명시
- **타깃**: 실존 기업이 아닌 가상 기업 "Target Co."

## 분석 구조 (5단계)

| 단계 | 주제 | 내용 | 산출물 |
|---|---|---|---|
| 1 | 테마 | AI 데이터센터 전력수요 전망 → 전력 인프라 수요로 연결 | `reports/step1_*.md` |
| 2 | Comps | 국내외 상장 peers 선정, 멀티플(PER, EV/EBITDA 등) 산출 | `reports/step2_*.md` |
| 3 | 가상 타깃 | Target Co. 사업·재무 가정 설계 (FY2025A, FY2026E~) | `reports/step3_*.md` |
| 4 | IPO 공모가 | 적정 시가총액 → 공모가 할인 → 희망공모가 밴드 | `reports/step4_*.md` |
| 5 | 몬테카를로 | 핵심 가정 분포를 시뮬레이션해 밸류에이션 민감도 분석 | `reports/step5_*.md` |

**Peers**
- 국내: HD현대일렉트릭, LS ELECTRIC, 효성중공업, 두산에너빌리티
- 해외: Vertiv, Eaton, GE Vernova, Schneider Electric, Constellation Energy, Vistra

## 데이터 소스

자세한 내용은 [data/source_registry.yaml](data/source_registry.yaml)에 있습니다.

| 소스 | 제공기관 | 주요 용도 | API 키 | 사용 단계 |
|---|---|---|---|---|
| [DART](https://opendart.fss.or.kr) | 금융감독원 | 국내 재무제표, 증권신고서 | 필요 | 2, 3, 4 |
| [KRX](https://data.krx.co.kr) | 한국거래소 | 주가, 시가총액, 상장주식수 | 필요 (Open API) | 2, 4 |
| [ECOS](https://ecos.bok.or.kr) | 한국은행 | 환율, 국고채 금리 | 필요 | 2, 4, 5 |
| [EPSIS](https://epsis.kpx.or.kr) | 전력거래소(KPX) | 국내 전력수요·설비 통계 | 웹 불필요 / API 필요 | 1 |
| [KIND](https://kind.krx.co.kr) | 한국거래소 | IPO 공모가·수요예측 사례 | 불필요 | 4 |
| [SEC EDGAR](https://www.sec.gov/edgar) | 미국 SEC | 해외 peers 10-K/10-Q | 불필요 (User-Agent 필수) | 2 |
| [FRED](https://fred.stlouisfed.org) | St. Louis Fed | 미국 금리, 매크로 | 필요 | 2, 5 |
| [EIA](https://www.eia.gov/opendata/) | 미국 에너지정보청 | 미국 전력 소비·발전 | 필요 | 1 |
| [IEA](https://www.iea.org) / [LBNL](https://eta.lbl.gov) 보고서 | IEA, 로렌스버클리연구소 | 데이터센터 전력수요 전망 | 불필요 | 1 |

보조 라이브러리(pykrx, FinanceDataReader, yfinance)로 받은 수치는 공식 소스와 교차검증하고, 그 결과를 `reports/`에 기록합니다.

## 폴더 구조

```
.
├── src/
│   ├── analysis/        # 단계별 분석 함수
│   └── data_fetch/      # 데이터 수집 스크립트 (로컬 실행)
├── data/
│   ├── raw/             # 원본 데이터 + .meta.json
│   ├── processed/       # 가공 데이터
│   ├── manual/          # 수작업 다운로드 자료
│   └── source_registry.yaml
├── figures/             # 그래프 (PNG 200dpi + PDF)
├── reports/             # 단계별 결과 요약 (Markdown / Excel)
├── docs/                # 방법론 문서
├── tests/               # pytest
├── config.yaml          # 전역 파라미터·가정치
└── requirements.txt
```

## 실행 방법

> 🚧 분석 코드 작성 후 업데이트 예정입니다.

```powershell
# 1. 가상환경 생성 및 패키지 설치
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. API 키 설정: .env.example을 .env로 복사한 뒤 값 입력
copy .env.example .env

# 3. 데이터 수집 (placeholder)
# python -m src.data_fetch.<script>

# 4. 분석 실행 (placeholder)
# python -m src.analysis.<step>

# 5. 테스트
pytest
```

## 면책 문구

이 프로젝트는 **교육·연구 목적의 개인 포트폴리오**이며, **투자 권유가 아닙니다**.
분석 대상인 "Target Co."는 가상 기업이고, 실존 기업과 관련이 없습니다.
분석에 사용한 데이터는 모두 공개 자료이며, 정확성과 완전성을 보장하지 않습니다.
이 자료를 근거로 한 투자 판단의 책임은 투자자 본인에게 있습니다.
