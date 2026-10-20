# Peers 식별자 검증 (DART corp_code / SEC CIK)

- 기준일: 2026-10-20 · 생성: 2026-10-20T14:35:15+00:00
- 출처: Open DART corpCode.xml(금융감독원), SEC EDGAR company_tickers.json
- 판정: OK = 티커·회사명 일치 / WARN = 티커는 있으나 회사명 불일치 / FAIL = 티커 없음 / N/A = SEC 비대상

## 핵심 결론

1. 검증 10개 중 FAIL 5개, OK 4개, N/A (SEC 비대상) 1개
2. 불일치(WARN/FAIL): 5개 — 아래 표의 비고 확인
3. Schneider Electric(SU.PA)은 SEC 비대상 → 재무 수치는 회사 연차보고서로 수기 입력(data/manual)

## 상세

| 구분 | 회사(config) | ticker | 시장 | 식별자 | 공시상 회사명 | 결과 | 비고 |
|---|---|---|---|---|---|---|---|
| 국내 | HD현대일렉트릭 | 267260 | KOSPI | corp_code 01205851 | HD현대일렉트릭 | OK |  |
| 국내 | LS ELECTRIC | 010120 | KOSPI | corp_code 00105855 | 엘에스일렉트릭 | OK |  |
| 국내 | 효성중공업 | 298040 | KOSPI | corp_code 01316245 | 효성중공업 | OK |  |
| 국내 | 두산에너빌리티 | 034020 | KOSPI | corp_code 00159616 | 두산에너빌리티 | OK |  |
| 해외 | Vertiv | VRT | NYSE |  |  | FAIL | SEC company_tickers 파일 없음 → --source sec 먼저 실행 |
| 해외 | Eaton | ETN | NYSE |  |  | FAIL | SEC company_tickers 파일 없음 → --source sec 먼저 실행 |
| 해외 | GE Vernova | GEV | NYSE |  |  | FAIL | SEC company_tickers 파일 없음 → --source sec 먼저 실행 |
| 해외 | Schneider Electric | SU.PA | Euronext Paris |  |  | N/A (SEC 비대상) | SEC 등록 공시기업 아님(Euronext Paris 상장). 재무는 연차보고서(URD) 기반 data/manual 수기 입력. TODO(data) |
| 해외 | Constellation Energy | CEG | NASDAQ |  |  | FAIL | SEC company_tickers 파일 없음 → --source sec 먼저 실행 |
| 해외 | Vistra | VST | NYSE |  |  | FAIL | SEC company_tickers 파일 없음 → --source sec 먼저 실행 |

## 한계

- 회사명 비교는 공백·법인격 표기를 제거한 부분일치 기준이라, 동명이사(同名異社)는 수동 확인 필요
- company_tickers.json은 SEC가 수시 갱신하는 매핑으로, 티커 변경 직후에는 반영이 늦을 수 있음
