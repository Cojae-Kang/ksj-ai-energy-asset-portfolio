# 데이터 수집 요약

- 기준일(as_of): 2026-10-20
- 실행 시각(UTC): 2026-10-22T04:30:58+00:00

| source | status | items | sec | message |
|---|---|---|---|---|
| sec | SUCCESS | 5 | 0.3 | 오프라인 모드(--sec-offline): SEC EDGAR (manual browser download); Schneider Electric(SU.PA): SEC 공시 대상 아님 → data/manual 수기 입력 대상; Vistra: 주체 검사 WARN — CIK·보통주·EPS는 상… |
| validate | PARTIAL | 10 | 0.1 | FAIL 0, WARN 1, 재무 주체 WARN 1 |
| consolidate | SUCCESS | 30 | 0.1 |  |

## 생성 파일

- `data\processed\peers_financials.csv`
- `data\processed\sec_debt_components.csv`
- `data\processed\sec_entity_check.csv`
- `data\processed\sec_financials.csv`
- `data\processed\sec_shares_outstanding.csv`
- `data\raw\sec\company_tickers.json`
- `docs\qa\peer_validation.md`
- `research\vol03\data_notes.md`
