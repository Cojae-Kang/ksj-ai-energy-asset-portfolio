# 데이터 파이프라인과 재현 방법

공개 첫 화면은 [README](../README.md)입니다. 이 문서는 데이터 수집·검증·보고서 생성 코드를 직접 돌려 보려는 분을 위한 기술 문서입니다.

- 소스 우선순위: 공식 공시(DART, SEC) > 공공기관(ECOS, FRED, EIA, KRX, KPX) > 보조 라이브러리(pykrx, FDR, yfinance)
- 모든 수치에 출처와 기준일을 기록하고, 가정치는 `config.yaml`에서 근거와 함께 관리합니다.
- 해외 피어(SEC EDGAR) 비교는 Vol.3(IPO 공모가·해외 피어)에서 다룹니다. SEC가 프로그램 요청을 403으로 막는 환경은 [SEC 오프라인 모드](#sec-오프라인-모드-브라우저-다운로드)로 수집합니다.
- 시리즈: Vol.1 수요·시장 → Vol.2 데이터센터 PF(한국 40MW·미국 100MW) → Vol.3 IPO 공모가·해외 피어

## Vol.1 재현

```powershell
pip install -r requirements.txt                                    # matplotlib + ReportLab, 추가 설치 없음
python -m src.data_fetch.fetch_all --source all --asof 2026-10-20   # 1단계 데이터 (키 없는 소스는 SKIPPED)
python -m research.vol01.fetch_extra --asof 2026-10-20              # Vol.1 추가: EIA 주별·부문별, KRX 두 시점, DART FY2022
python -m research.vol01.build                                      # 국문/영문 PDF + build_summary.md
pytest -q                                                           # 네트워크 없는 테스트
```

- 보고서의 모든 숫자·제목·결론은 `data/` 파일에서 계산합니다. 데이터가 없으면 그 Exhibit만 "데이터 수집 후 생성" 안내 박스로 남깁니다.
- 시총 변화 분해: Δln(시총) = Δln(지배순이익) + Δln(PER). 2023년 초 시총 ↔ FY2022A, 최근 시총 ↔ FY2025A 지배순이익.
- 커밋 대상: `data/processed/`, `data/manual/`, `research/vol01/*.pdf`, `build_summary.md`. 원자료 `data/raw/`와 차트 중간 산출물 `research/vol01/_build/`는 커밋하지 않습니다(.gitignore).
- 한글 폰트는 저장소의 Noto Sans KR(OFL, `assets/fonts/`)을 쓰고, 없으면 Windows 맑은 고딕으로 대체합니다.

## Vol.2 재현 (데이터센터 PF)

```powershell
python -m research.vol02.fetch_extra --asof 2026-10-20   # (선택) EIA 버지니아 상업용 요금 → data/processed/vol02_eia_va_com.csv
python -m research.vol02.build --write-template          # data/manual/vol02_assumptions.csv 양식 갱신 (입력값 보존)
python -m research.vol02.build                           # 국문/영문 PDF + research/vol02/build_summary.md
pytest -q tests/test_pf_model.py tests/test_research_vol02.py
```

- 모델: `src/analysis/pf_model.py` (분기 건설·IDC → 연 운영 → CFADS → sculpting vs 최대 대출 비율 → waterfall·DSRA →
  최소·평균 DSCR, LLCR, Project/Equity IRR, 회수기간), `src/analysis/real_option.py` (2단계 증설 옵션, LSM 몬테카를로, seed 고정).
- 가정: `config.yaml` → `research.vol02.cases.{A,B}.params`. 모든 항목에 tag(ASSUMPTION(design/verify/neutral))와 근거 칸이 있고,
  근거를 모르는 값은 `null` + `TODO(source)`입니다. **null이 있으면 그 계산만 건너뛰고 해당 Exhibit을 회색 박스로 둡니다.**
- 사용자 입력: `data/manual/vol02_assumptions.csv`(case, item, value, low, high, unit, tag, source_name, url, published, page, current, hint).
  value가 있으면 config보다 우선하고, 출처 칸만 채우면 config 값에 출처가 붙습니다. % 단위는 퍼센트 숫자(2.5 = 2.5%), 가산금리는 bp,
  누진세율은 `상한:세율` 목록(예: `2:10,200:20,3000:22,inf:25`, 억원·%). low·high는 스트레스 범위(CAPEX·임대료·사전 임대율·승인 확률).
- tag: `sourced` = 출처가 있는 값 → ASSUMPTION(sourced), 보고서 가정표에 **근거 있음**(골드) / `judgment` = 저자 판단 → ASSUMPTION(judgment),
  **저자 판단**(음영·브라운). 빌드 요약에 "근거 있는 가정 n개 / 저자 판단 n개 / 미입력 n개"를 집계합니다.
- 미확정 처리: 가산금리 null(케이스 B) → 150/250/350bp 시나리오, 옵션 할인율·대기 기간 null → `real_option.discount_grid`·`window_grid` 격자,
  승인 결정 시점 null → 1단계 램프업 종료 연도로 도출. 감가상각 null → 미반영(법인세 보수적), PUE·IT 부하율 null → 전력비 순액 0(패스스루 100%).
- 진단: 램프업 초기 원리금이 이자보다 작으면(음수 원금) "매년 이자 현금 지급 제약 시 한도"를 함께 표시하고 빌드 요약의 '점검 필요 수치'에 기록합니다.
- Vol.1 데이터 연결: IEA 2024→2035 성장률(하단·기준·상단) → 가동률 램프업, ECOS 국고채 3·10년·FRED DGS10(기준일 2026-10-20 이전 최근값)
  → 기준금리, DART 피어 3사 영업이익률 FY2022A→FY2025A → 함의 가격 상승률(상한값) × 전력설비 비중 → CAPEX 스트레스,
  EIA 버지니아 상업용 판매·요금(`data/processed/vol02_eia_va_com.csv`, 2015~2025) → 케이스 B 수요 근거·전력 단가·전력비 민감도(PUE 축 × 요금).
- 검산: 회계 항등식(조달=사용, 대출 잔액, waterfall, DSRA·배당 잠금), DSCR = CFADS ÷ 원리금, IRR, 환율 환산(USD mn × 원/달러 ÷ 100 = 억원)을
  테스트와 `build_summary.md`에 기록합니다.
- 커밋 대상: `research/vol02/*.pdf`, `build_summary.md`, `data/manual/vol02_assumptions.csv`. 차트 중간 산출물 `research/vol02/_build/`는 제외.

## 단계 구성

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

자세한 내용은 [data/source_registry.yaml](../data/source_registry.yaml)에 있습니다.

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

보조 라이브러리(pykrx, FinanceDataReader, yfinance)로 받은 수치는 공식 소스와 교차검증하고, 그 결과를 `docs/qa/`에 기록합니다.

## 폴더 구조

```
.
├── src/
│   ├── analysis/        # 분석 함수 (pf_model.py: PF 엔진, real_option.py: 증설 옵션)
│   └── data_fetch/      # 데이터 수집 스크립트 (로컬 실행)
├── research/
│   ├── vol01/           # Research Note Vol.1 (fetch_extra.py, data.py, story.py, layout.py, charts.py, build.py, PDF)
│   ├── vol02/           # Research Note Vol.2 데이터센터 PF (data.py, story.py, charts.py, build.py, fetch_extra.py, PDF)
│   └── vol03/           # Vol.3 IPO·해외 피어 — data_notes.md (SEC 주체 검사, validate가 갱신)
├── assets/fonts/        # Noto Sans KR (SIL OFL 1.1)
├── data/
│   ├── raw/             # 원본 데이터 + .meta.json
│   ├── processed/       # 가공 데이터
│   ├── manual/          # 수작업 다운로드 자료
│   └── source_registry.yaml
├── figures/             # 그래프 (PNG 200dpi + PDF)
├── reports/             # 단계별 결과 요약 (Markdown / Excel)
├── docs/                # 데이터 파이프라인 문서, qa/(수집 요약·교차검증), img/(README 그림)
├── tests/               # pytest
├── config.yaml          # 전역 파라미터·가정치
└── requirements.txt
```

## 실행 방법

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

> 데이터 수집은 **로컬에서만** 실행합니다. 원자료 `data/raw/`는 커밋하지 않으며, 클라우드 세션은 커밋된 `data/processed/`, `data/manual/` 파일만 사용합니다.

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

실행이 끝나면 소스별 **SUCCESS / PARTIAL / FAILED / SKIPPED** 요약표가 출력되고 `docs/qa/data_fetch_summary.md`에 저장됩니다.

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
403이 하루(`offline.persistent_403_hours`, 24시간) 이상 이어지면 메시지에
"네트워크·클라이언트 차단 가능성 → 브라우저 다운로드 후 오프라인 모드" 안내가 붙습니다(최초·최근 403 시각은 `data/raw/sec/_403_state.json`, 성공 시 삭제).

<a id="sec-오프라인-모드-브라우저-다운로드"></a>
**SEC 오프라인 모드 (브라우저 다운로드)**

User-Agent가 맞는데도 python·curl 모두 403이고 브라우저만 통과하는 네트워크(회사·학교 프록시, 클라이언트 지문 차단 등)에서 씁니다.
SEC 데이터는 Vol.3(IPO·해외 피어)에서 사용합니다.

1. 필요한 파일·URL 확인 (네트워크 호출 없음)

   ```powershell
   python -m src.data_fetch.sec --offline-check
   ```

2. 브라우저로 아래 URL을 열어 **원본 JSON**으로 저장 → `data/raw/sec_manual/` (로컬 전용, `data/raw/` 전체가 .gitignore)

   | 파일 | 티커 | URL |
   |---|---|---|
   | `company_tickers.json` | (CIK 매핑) | https://www.sec.gov/files/company_tickers.json |
   | `CIK0001674101.json` | VRT | https://data.sec.gov/api/xbrl/companyfacts/CIK0001674101.json |
   | `CIK0001551182.json` | ETN | https://data.sec.gov/api/xbrl/companyfacts/CIK0001551182.json |
   | `CIK0001996810.json` | GEV | https://data.sec.gov/api/xbrl/companyfacts/CIK0001996810.json |
   | `CIK0001868275.json` | CEG | https://data.sec.gov/api/xbrl/companyfacts/CIK0001868275.json |
   | `CIK0001692819.json` | VST | https://data.sec.gov/api/xbrl/companyfacts/CIK0001692819.json |

3. 수집 (온라인과 같은 추출·저장 로직)

   ```powershell
   python -m src.data_fetch.fetch_all --source sec --sec-offline --asof 2026-10-20
   ```

   - 온라인 실행 중 403이 나면(`offline.auto_on_403: true`) 같은 실행 안에서 오프라인 모드로 자동 전환합니다.
   - 파일이 없으면 필요한 CIK·URL 목록을 출력하고 **SKIPPED**, 일부만 있으면 있는 회사만 처리하고 PARTIAL.
   - 각 파일 옆에 `.meta.json`(source = `SEC EDGAR (manual browser download)`, fetched_at = **파일 수정 시각**, endpoint = 원 URL, sha256)을 쓰고,
     `company_tickers.json`은 validate 입력 위치(`data/raw/sec/`)에도 같은 meta와 함께 복사합니다. 가공본 `sec_financials.csv`의
     `data_source` 열은 `manual browser download`.
   - companyfacts의 `cik` 값은 숫자(`1551182`)와 0 채운 문자열(`"0001868275"`)이 섞여 있어 모두 정수로 정규화해 매칭합니다.

4. **시총(상장사)과 재무(법인) 주체 검사** — `data/processed/sec_entity_check.csv`, `docs/qa/peer_validation.md`, `research/vol03/data_notes.md`
   - company_tickers의 티커·CIK(시가총액 주체)와 companyfacts의 `cik`·`entityName`(재무 주체)을 비교합니다.
   - 판정: ① CIK 일치 ② 법인명 완전일치(법인격 표기 제외) ③ 보통주 발행주식수(dei) 보고 ④ EPS 보고.
     `same_consolidated` = yes(같은 법인) / likely(같은 CIK·보통주·EPS, 이름 표기만 다름) / no(다른 CIK) / unknown(보통주·EPS 미보고).
   - yes가 아니면 validate가 해당 피어를 **WARN + 사유**로 표기하고 Vol.3 데이터 노트에 기록합니다. Vol.3 배수 계산에서는 제외합니다.
   - **수동 확인 override**: 사람이 원문(10-K 표지 registrant 등)으로 확인하면 `config.yaml` → `data_fetch.sec.entity_check.manual_overrides`에
     `{cik, verdict, note, detail, url, verified_on}`을 적습니다. 상장사·재무 법인 CIK가 모두 `cik`와 같고 url·확인일이 있을 때만 적용되며,
     자동 판정은 `auto_verdict`로 남고 `peer_validation.md`·`research/vol03/data_notes.md`에 근거 URL·확인일이 기록됩니다.
     (2026-10-22: VST — CIK 0001692819 10-K registrant = Vistra Corp., entityName 'Vistra Operations Company LLC'는 표기 차이 → OK)
   - 예: `CIK0001692819.json`의 entityName이 `Vistra Oper...`(운영 자회사로 보임)로 시작하면, company_tickers상 VST(Vistra Corp.)와
     법인명이 달라 WARN. 보통주·EPS도 없으면 `unknown`(자회사 재무 가능성), 다른 CIK면 `no`(상장사 CIK 파일로 교체).

### 3) 소스별 수집 내용

| 모듈 | 수집 내용 | 주요 산출물 |
|---|---|---|
| `dart.py` | corpCode.xml(종목코드↔corp_code), fnlttSinglAcntAll(사업보고서 11011, CFS 우선→OFS, FY2023~2025), list.json 발행공시(C, 기본 OFF), document.xml 원문 | `data/raw/dart/`, `data/processed/dart_financials.csv` |
| `krx.py` | KRX Open API 종가·시가총액·상장주식수 (휴장일이면 직전 거래일). 실패 시 FinanceDataReader → pykrx | `data/processed/krx_peers_market.csv`, `docs/qa/crosscheck_krx.md` |
| `ecos.py` | 원/달러 일별 → 연평균·연말, 국고채 3년·10년 | `data/processed/ecos_fx_annual.csv`, `ecos_ktb_daily.csv` |
| `sec.py` | company_tickers.json(CIK) → companyfacts: Revenue, OperatingIncome, NetIncome, 총차입금, 현금. 403이면 오프라인 모드(브라우저 다운로드 파일) | `data/processed/sec_financials.csv`, `sec_entity_check.csv` |
| `fred.py` | DGS10, DEXKOUS | `data/processed/fred_series.csv` |
| `eia.py` | 미국 전력 소매판매량·가격 (부문별, 연간) — 출처: U.S. Energy Information Administration (EIA) | `data/processed/eia_retail_sales_annual.csv` |
| `market_global.py` | yfinance 해외 peers 주가·시총 (보조 소스, `cross_check_required=True`) | `data/processed/global_peers_market.csv`, `docs/qa/crosscheck_global.md` |
| `validate_peers.py` | config peers 티커 ↔ DART corp_code / SEC CIK 검증 + 시총·재무 주체 검사 (Schneider Electric은 SEC 비대상) | `docs/qa/peer_validation.md`, `research/vol03/data_notes.md` |
| `consolidate.py` | 국내·해외 재무 통합 (통화·단위·회계연도 정규화, KRW 억원·USD mn 환산) | `data/processed/peers_financials.csv` |

### 4) 데이터 규칙

- 모든 raw 파일은 같은 이름의 `.meta.json`(source, endpoint, params(키 제외), fetched_at, as_of, license_note)을 동반합니다.
- base URL·endpoint·시리즈 코드·계정 매핑은 모두 `config.yaml`의 `data_fetch`에서 관리합니다. `ASSUMPTION(verify)` 항목은 공식 문서로 확인한 뒤 태그를 지웁니다.
- 원자료(`data/raw/` 전체: API 응답, DART 원문 zip, SEC companyfacts, 응답 캐시)는 git에서 제외됩니다. 가공본 `data/processed/`만 커밋합니다.
- 환산: 손익은 연평균 환율, 재무상태(차입금·현금)는 연말 환율(ECOS 매매기준율)을 씁니다.
- Schneider Electric 재무는 `data/manual/overseas_financials_manual.csv`에 연차보고서 기준으로 직접 입력합니다(`TODO(data)`).

