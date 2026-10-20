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

# 3. 데이터 수집 (자세한 내용은 아래 '데이터 수집 실행 방법')
python -m src.data_fetch.fetch_all --source all --asof 2026-10-20

# 4. 분석 실행 (placeholder)
# python -m src.analysis.<step>

# 5. 테스트
pytest
```

## 데이터 수집 실행 방법

> 데이터 수집은 **로컬에서만** 실행합니다. 클라우드 세션은 커밋된 `data/raw/`, `data/manual/` 파일만 사용합니다.

### 1) 준비

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # 키 입력 (.env는 커밋 금지, .gitignore 처리됨)
pytest -q                   # 네트워크 없이 도는 단위테스트 (응답 mock)
```

| .env 변수 | 소스 | 비고 |
|---|---|---|
| `DART_API_KEY` | Open DART | 재무제표·발행공시·원문 |
| `KRX_API_KEY` | KRX Open API | 승인 서비스: 유가증권 일별매매정보, 유가증권 종목기본정보 |
| `ECOS_API_KEY` | 한국은행 ECOS | 원/달러 환율, 국고채 3·10년 |
| `SEC_USER_AGENT` | SEC EDGAR | 키 대신 User-Agent(이름 + 이메일) 필수 |
| `FRED_API_KEY` | FRED | DGS10, DEXKOUS |
| `EIA_API_KEY` | EIA Open Data | 미국 전력 소매판매량·가격 |
| `KRX_ID`, `KRX_PW` | pykrx (선택) | 비어 있으면 pykrx 대체 수집이 실패할 수 있음 |

키가 비어 있는 소스는 **SKIPPED**로 건너뛰고 나머지는 계속 수집합니다. 로그·meta·요약표에서 키는 `***`로 마스킹됩니다.

### 2) 실행

```powershell
# 전체 수집 (+ peers 식별자 검증 + 재무 통합)
python -m src.data_fetch.fetch_all --source all --asof 2026-10-20

# 개별 소스 (쉼표 또는 공백으로 여러 개): dart / krx / ecos / sec / fred / eia / global
python -m src.data_fetch.fetch_all --source krx,ecos,sec --asof 2026-10-20

# DART 발행공시 검색 생략 (기본값도 OFF: config dart.filings.enabled=false)
python -m src.data_fetch.fetch_all --source dart --skip-filings --asof 2026-10-20

# 옵션: --no-cache (캐시 무시), --no-post (검증·통합 생략), --skip-filings, -v (디버그 로그)
python -m src.data_fetch.validate_peers      # 식별자 검증만 다시
```

요청마다 진행 로그가 한 줄씩 출력됩니다.

```text
[dart] 재무제표 3/12 LS ELECTRIC FY2025 ... 완료(0.8초) (CFS, 212행)
[dart] 재무제표 4/12 LS ELECTRIC FY2023 ... 타임아웃→건너뜀(25.0초): ...
```

실행이 끝나면 소스별 **SUCCESS / PARTIAL / FAILED / SKIPPED** 요약표가 출력되고 `reports/data_fetch_summary.md`에 저장됩니다.

**타임아웃·재시도** (`config.yaml` → `data_fetch.http`)

| 항목 | 기본값 | 설명 |
|---|---|---|
| `connect_timeout_sec` | 5 | 연결 타임아웃 |
| `read_timeout_sec` | 20 | 응답 헤더+본문 수신 상한. 서버가 바이트를 조금씩 흘려보내도 벽시계 기준으로 끊음 |
| `max_retries` | 3 | 지수 백오프(1→2→4초) 재시도 |
| `max_total_wait_sec` | 60 | 한 요청의 재시도·대기 포함 총 소요 상한 |

타임아웃이 끝내 해소되지 않으면 그 요청(회사·연도, 시계열, 검색 구간)만 건너뛰고 요약표 message에 기록한 뒤 다음 요청을 계속합니다.

**DART 발행공시 검색** (`config.yaml` → `data_fetch.dart.filings`, 기본 `enabled: false`)
- `mode: market`: corp_code 없이 `window_months`(3개월) 단위로 나눠 반복 검색 (DART 검색기간 제한 대응)
- `mode: peers`: config peers의 corp_code별로 검색
- `max_pages`: 구간(회사)당 페이지 상한. 넘으면 기록 후 생략

**SEC 403 진단**

SEC는 User-Agent(영문 이름 + 연락 가능한 이메일)가 없거나 요청이 초당 10건 이상이면 403 차단 페이지를 돌려줍니다
([SEC: Accessing EDGAR Data](https://www.sec.gov/os/accessing-edgar-data)). 수집 코드는 www.sec.gov·data.sec.gov
모든 요청에 `User-Agent`와 `Accept-Encoding: gzip, deflate`를 세션 기본 헤더로 붙이고, 초당 8건 이하로 제한합니다.
`.env` 값의 따옴표·공백은 자동으로 정리합니다.

```powershell
python -m src.data_fetch.sec --diagnose           # 실제 전송 헤더(이메일 부분 마스킹)·프록시·속도 확인. 네트워크 호출 없음
python -m src.data_fetch.sec --diagnose --probe   # company_tickers.json 1회 실제 요청 → 차단 유형 한 줄 요약
```

403이면 요약표에 `SEC 403: User-Agent 확인 필요 (URL) — 차단 유형` 한 줄만 기록되고, 나머지 SEC 요청은 중단됩니다.
이때 validate는 해외 peers를 FAIL이 아니라 `SKIPPED(sec unavailable)`로 표기합니다(티커 오류와 구분).

### 3) 소스별 수집 내용

| 모듈 | 수집 내용 | 주요 산출물 |
|---|---|---|
| `dart.py` | corpCode.xml(종목코드↔corp_code), fnlttSinglAcntAll(사업보고서 11011, CFS 우선→OFS, FY2023~2025), list.json 발행공시(C, 기본 OFF), document.xml 원문 | `data/raw/dart/`, `data/processed/dart_financials.csv` |
| `krx.py` | KRX Open API 종가·시가총액·상장주식수 (휴장일이면 직전 거래일). 실패 시 FinanceDataReader → pykrx | `data/processed/krx_peers_market.csv`, `reports/crosscheck_krx.md` |
| `ecos.py` | 원/달러 일별 → 연평균·연말, 국고채 3년·10년 | `data/processed/ecos_fx_annual.csv`, `ecos_ktb_daily.csv` |
| `sec.py` | company_tickers.json(CIK) → companyfacts: Revenue, OperatingIncome, NetIncome, 총차입금, 현금 | `data/processed/sec_financials.csv` |
| `fred.py` | DGS10, DEXKOUS | `data/processed/fred_series.csv` |
| `eia.py` | 미국 전력 소매판매량·가격 (부문별, 연간) — 출처: U.S. Energy Information Administration (EIA) | `data/processed/eia_retail_sales_annual.csv` |
| `market_global.py` | yfinance 해외 peers 주가·시총 (보조 소스, `cross_check_required=True`) | `data/processed/global_peers_market.csv`, `reports/crosscheck_global.md` |
| `validate_peers.py` | config peers 티커 ↔ DART corp_code / SEC CIK 검증 (Schneider Electric은 SEC 비대상으로 별도 표기) | `reports/peer_validation.md` |
| `consolidate.py` | 국내·해외 재무 통합 (통화·단위·회계연도 정규화, KRW 억원·USD mn 환산) | `data/processed/peers_financials.csv` |

### 4) 데이터 규칙

- 모든 raw 파일은 같은 이름의 `.meta.json`(source, endpoint, params(키 제외), fetched_at, as_of, license_note)을 동반합니다.
- base URL·endpoint·시리즈 코드·계정 매핑은 모두 `config.yaml`의 `data_fetch`에서 관리합니다. `ASSUMPTION(verify)` 항목은 공식 문서로 확인한 뒤 태그를 지웁니다.
- 대용량 원본(DART 원문 zip, SEC companyfacts)은 `data/raw/large/`, 응답 캐시는 `data/raw/_cache/`에 저장되며 git에서 제외됩니다.
- 환산: 손익은 연평균 환율, 재무상태(차입금·현금)는 연말 환율(ECOS 매매기준율)을 씁니다.
- Schneider Electric 재무는 `data/manual/overseas_financials_manual.csv`에 연차보고서 기준으로 직접 입력합니다(`TODO(data)`).

## 면책 문구

이 프로젝트는 **교육·연구 목적의 개인 포트폴리오**이며, **투자 권유가 아닙니다**.
분석 대상인 "Target Co."는 가상 기업이고, 실존 기업과 관련이 없습니다.
분석에 사용한 데이터는 모두 공개 자료이며, 정확성과 완전성을 보장하지 않습니다.
이 자료를 근거로 한 투자 판단의 책임은 투자자 본인에게 있습니다.
