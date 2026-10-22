# Vol.3 데이터 노트 — 해외 피어(SEC EDGAR)

- 기준일: 2026-10-20 · 갱신: 2026-10-22T04:30:58+00:00 · 생성: `python -m src.data_fetch.validate_peers`
- 출처: SEC EDGAR company_tickers.json(상장사 티커·CIK), XBRL companyfacts(연간 재무). 403 환경에서는 브라우저 다운로드 파일(SEC EDGAR (manual browser download))

## 핵심 결론

1. 재무 주체 검사 5개사 중 WARN 1개
2. 시총은 상장사(company_tickers 티커), 재무는 companyfacts 법인 기준 — 둘이 다르면 배수 계산에서 제외
3. VST: CIK·보통주·EPS는 상장사와 같아 연결 재무일 가능성이 높으나 법인명 표기가 다름 → 10-K 표지 registrant명으로 확인 (entityName 'Vistra Operations Company LLC' ≠ 상장사명 'Vistra Corp.')

## 근거

| company | ticker | listed_cik | listed_title | entity_cik | entity_name | same_consolidated | verdict | reason |
|---|---|---|---|---|---|---|---|---|
| Vertiv | VRT | 0001674101 | Vertiv Holdings Co | 0001674101 | Vertiv Holdings Co | yes | OK | 상장사 = 재무 주체 |
| Eaton | ETN | 0001551182 | Eaton Corp plc | 0001551182 | EATON CORPORATION plc | yes | OK | 상장사 = 재무 주체 |
| GE Vernova | GEV | 0001996810 | GE Vernova Inc. | 0001996810 | GE Vernova Inc. | yes | OK | 상장사 = 재무 주체 |
| Constellation Energy | CEG | 0001868275 | Constellation Energy Corp | 0001868275 | CONSTELLATION ENERGY CORPORATION | yes | OK | 상장사 = 재무 주체 |
| Vistra | VST | 0001692819 | Vistra Corp. | 0001692819 | Vistra Operations Company LLC | likely | WARN | CIK·보통주·EPS는 상장사와 같아 연결 재무일 가능성이 높으나 법인명 표기가 다름 → 10-K 표지 registrant명으로 확인 (entityName 'Vistra Operations Company LLC' ≠ 상장사명 'Vistra Corp.') |

## 한계

- 법인 일치 판정은 CIK·법인명·보통주 발행주식수·EPS 보고 여부로 한 자동 판정이다. 최종 확인은 10-K 표지(registrant)와 연결범위 주석
- 오프라인 모드 수치의 기준 시각은 브라우저 다운로드 파일의 수정 시각(.meta.json fetched_at)
