# Peers 식별자 검증 (DART corp_code / SEC CIK)

- 기준일: 2026-10-20 · 생성: 2026-10-22T04:54:51+00:00
- 출처: Open DART corpCode.xml(금융감독원), SEC EDGAR company_tickers.json
- 판정: OK = 티커·회사명 일치 / WARN = 티커는 있으나 회사명 불일치 또는 재무 주체(법인)가 상장사와 다를 수 있음 / FAIL = 티커 없음 / N/A = SEC 비대상 / SKIPPED(sec unavailable) = SEC 매핑 수집 실패로 검증 보류(티커 오류 아님)

## 핵심 결론

1. 검증 10개 중 OK 9개, N/A (SEC 비대상) 1개
2. 불일치(WARN/FAIL): 0개 — config 티커 그대로 사용 가능
3. Schneider Electric(SU.PA)은 SEC 비대상 → 재무 수치는 회사 연차보고서로 수기 입력(data/manual)

## 상세

| 구분 | 회사(config) | ticker | 시장 | 식별자 | 공시상 회사명 | 결과 | 비고 |
|---|---|---|---|---|---|---|---|
| 국내 | HD현대일렉트릭 | 267260 | KOSPI | corp_code 01205851 | HD현대일렉트릭 | OK |  |
| 국내 | LS ELECTRIC | 010120 | KOSPI | corp_code 00105855 | 엘에스일렉트릭 | OK |  |
| 국내 | 효성중공업 | 298040 | KOSPI | corp_code 01316245 | 효성중공업 | OK |  |
| 국내 | 두산에너빌리티 | 034020 | KOSPI | corp_code 00159616 | 두산에너빌리티 | OK |  |
| 해외 | Vertiv | VRT | NYSE | CIK 0001674101 | Vertiv Holdings Co | OK |  |
| 해외 | Eaton | ETN | NYSE | CIK 0001551182 | Eaton Corp plc | OK |  |
| 해외 | GE Vernova | GEV | NYSE | CIK 0001996810 | GE Vernova Inc. | OK |  |
| 해외 | Schneider Electric | SU.PA | Euronext Paris |  |  | N/A (SEC 비대상) | SEC 등록 공시기업 아님(Euronext Paris 상장). 재무는 연차보고서(URD) 기반 data/manual 수기 입력. TODO(data) |
| 해외 | Constellation Energy | CEG | NASDAQ | CIK 0001868275 | Constellation Energy Corp | OK |  |
| 해외 | Vistra | VST | NYSE | CIK 0001692819 | Vistra Corp. | OK | OK(수동 확인: 10-K registrant = Vistra Corp.) |

## 시총(상장사) vs 재무(법인) 주체 검사

- 상장사 = company_tickers.json의 티커·CIK(시가총액 주체), 재무 = companyfacts의 cik·entityName
- same_consolidated: yes 같은 법인 / likely 같은 CIK·보통주·EPS(법인명 표기만 다름) / no 다른 법인 / unknown 보통주·EPS 미보고 / yes (manual) 수동 확인

| company | ticker | listed_cik | listed_title | entity_cik | entity_name | same_consolidated | verdict | reason |
|---|---|---|---|---|---|---|---|---|
| Vertiv | VRT | 0001674101 | Vertiv Holdings Co | 0001674101 | Vertiv Holdings Co | yes | OK | 상장사 = 재무 주체 |
| Eaton | ETN | 0001551182 | Eaton Corp plc | 0001551182 | EATON CORPORATION plc | yes | OK | 상장사 = 재무 주체 |
| GE Vernova | GEV | 0001996810 | GE Vernova Inc. | 0001996810 | GE Vernova Inc. | yes | OK | 상장사 = 재무 주체 |
| Constellation Energy | CEG | 0001868275 | Constellation Energy Corp | 0001868275 | CONSTELLATION ENERGY CORPORATION | yes | OK | 상장사 = 재무 주체 |
| Vistra | VST | 0001692819 | Vistra Corp. | 0001692819 | Vistra Operations Company LLC | yes (manual) | OK | 수동 확인: 10-K registrant = Vistra Corp. (확인일 2026-10-22, 근거 https://www.sec.gov/Archives/edgar/data/1692819/000169281922000005/vistra-20211231.htm) |

**수동 확인 (자동 판정 override)**

| ticker | 자동 판정 | 수동 판정 | 내용 | 근거 URL | 확인일 |
|---|---|---|---|---|---|
| VST | WARN (likely) | OK(수동 확인: 10-K registrant = Vistra Corp.) | CIK 0001692819로 제출된 10-K 표지의 registrant가 Vistra Corp.; companyfacts entityName 'Vistra Operations Company LLC'는 표기 차이로 판단 | https://www.sec.gov/Archives/edgar/data/1692819/000169281922000005/vistra-20211231.htm | 2026-10-22 |

## 한계

- 회사명 비교는 공백·법인격 표기를 제거한 부분일치 기준이라, 동명이사(同名異社)는 수동 확인 필요
- company_tickers.json은 SEC가 수시 갱신하는 매핑으로, 티커 변경 직후에는 반영이 늦을 수 있음
