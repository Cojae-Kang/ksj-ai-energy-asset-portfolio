# Vol.3 데이터 노트 — 해외 피어(SEC EDGAR)

- 기준일: 2026-10-20 · 갱신: 2026-10-22T04:05:07+00:00 · 생성: `python -m src.data_fetch.validate_peers`
- 출처: SEC EDGAR company_tickers.json(상장사 티커·CIK), XBRL companyfacts(연간 재무). 403 환경에서는 브라우저 다운로드 파일(SEC EDGAR (manual browser download))

## 핵심 결론

1. 재무 주체 검사 보류 — SEC companyfacts 미수집(TODO(data))
2. 시총은 상장사(company_tickers 티커), 재무는 companyfacts 법인 기준 — 둘이 다르면 배수 계산에서 제외
3. VST: 로컬 관찰(2026-10): CIK0001692819.json의 entityName이 'Vistra Oper...'로 시작 — 운영 자회사 재무일 가능성 (검사 대기)

## 근거

- TODO(data): SEC companyfacts 수집 후 자동 작성 — `python -m src.data_fetch.fetch_all --source sec --sec-offline`

**검사 대기 중인 관찰 기록**

- VST: 로컬 관찰(2026-10): CIK0001692819.json의 entityName이 'Vistra Oper...'로 시작 — 운영 자회사 재무일 가능성

## 한계

- 법인 일치 판정은 CIK·법인명·보통주 발행주식수·EPS 보고 여부로 한 자동 판정이다. 최종 확인은 10-K 표지(registrant)와 연결범위 주석
- 오프라인 모드 수치의 기준 시각은 브라우저 다운로드 파일의 수정 시각(.meta.json fetched_at)
