# CLAUDE.md — Project Rules

## Goal
ECM 직무 포트폴리오. AI 데이터센터 전력 수요 → 전력 인프라 밸류체인 → 가상 비상장 기업의
IPO 희망공모가 밴드 산정. 독자는 증권사 ECM·IB 실무자.

## Data rules (가장 중요)
- 공개 데이터만 사용. 출처(URL 또는 기관명)와 기준일을 항상 기록.
- 숫자를 절대 지어내지 말 것. 데이터를 못 구하면 멈추지 말고 data/raw/에 CSV 양식을 만들고
  `TODO(data):`로 필요한 항목을 명시.
- 가정치는 반드시 `ASSUMPTION:` 태그와 근거를 붙이고 config.yaml에서 관리.
- 실존 비상장 기업을 타깃으로 쓰지 말 것. 타깃은 가상 기업("Target Co.").
- 회사·기관 내부 자료, 비공개 자료는 사용 금지.

## Data pipeline
- 데이터 수집은 로컬에서 src/data_fetch/ 스크립트로 수행. 클라우드 세션에서는 외부 API를 호출하지 말고
  data/raw/, data/manual/에 커밋된 파일만 사용할 것.
- 필요한 데이터가 없으면 직접 긁지 말고 `TODO(data):`로 소스(source_registry.yaml 기준)·항목·기간을
  명시한 뒤 나머지 작업을 계속할 것.
- 모든 raw 파일은 같은 이름의 .meta.json 동반: source, endpoint, params(키 제외), fetched_at, as_of, license_note
- 소스 우선순위: 공식 공시(DART, SEC) > 공공기관(ECOS, FRED, EIA, KRX, KPX) > 보조 라이브러리(pykrx, FDR, yfinance).
  보조 라이브러리 수치는 공식 소스와 교차검증 결과를 docs/qa/에 기록.
- API 키는 .env에서만 로드(python-dotenv). 코드·로그·커밋에 키 출력 금지.

## Conventions
- Python 3.12, 분석 로직은 src/에 함수로. 하드코딩 금지, 파라미터는 config.yaml.
- 단위 명시: 금액은 KRW 억원 / USD mn, 회계연도 표기(FY2025A, FY2026E).
- 그래프: figures/에 PNG(200dpi) + PDF, 제목·축·단위·출처 각주 포함.
- 표: reports/에 Markdown, 필요 시 Excel(openpyxl).
- 단계별 결과 요약은 reports/stepN_*.md에 "핵심 결론 3줄 → 근거 → 한계" 순서로.

## Quality
- 주요 계산 함수는 tests/에 pytest 작성.
- 작업이 끝나면 스스로 검산(배수 계산, 단위, 환율 적용) 후 이상치 보고.
- 커밋 메시지: feat/fix/docs/data/chore 접두어.

## Disclaimer
교육·연구 목적. 투자 권유 아님.
