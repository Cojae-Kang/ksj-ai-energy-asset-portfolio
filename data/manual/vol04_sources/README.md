# Vol.4 원문 보관함

Vol.4(와 Vol.5)가 쓰는 공식 원문을 받은 그대로 보관한다. 파일마다 같은 이름의 `.meta.json`에
출처·기준일·쓰인 입력을 적었다. 입력값과 신뢰 등급은 `data/manual/vol04_inputs.csv`가 기준이다.

## 보관 중인 원문 (2026-10-29 기준)

| 파일 | 내용 | 쓰인 곳 | 등급 |
|---|---|---|---|
| `(완료)기본04_…실증+연구.pdf` | 에너지경제연구원 기본연구 25-04 (태양광 설치비용) | capex_per_kw · capacity_factor · lcoe_target · lcoe_discount_rate | A |
| `17-13_수시_그리드+패리티…연구.pdf` | 에너지경제연구원 수시연구 17-13 (그리드 패리티) | 개념 참고 (입력값 없음) | — |
| `2512_전력통계월보(제566호).pdf` · `.xlsx` | 한전 전력통계월보 제566호 (2025.12) | kepco_industrial_price · solar_cf · solar_month_weights | A · D |
| `HOME_전력거래_계통한계가격_가중평균SMP.xlsx` | 전력거래소 EPSIS 월별 가중평균 SMP | smp_base · smp_sigma · smp_phi | A · D |
| `HOME_전력거래_계통한계가격_시간별SMP.xlsx` · `(1).xlsx` | EPSIS 시간별 SMP (육지·제주 각 1개, `sources.land_hourly`가 자동 판정) | 시간대 확인 | A |
| `HOME_전력거래_계통한계가격_연료원별SMP결정.xlsx` | EPSIS 연료원별 SMP 결정 횟수 | 참고 (입력값 없음) | — |
| `계절·시간대별 전기요금 체계 개편안 공개(보도참고자료)(전력시장 3.13).pdf` | 기후에너지환경부·한전 보도참고자료 (2026-03-13) | tou_tariff · tou_weekend_discount | A |
| `kepco_climate_charge_2023-01.pdf` | 한전ON 기후환경요금 9.0원/kWh ('23.1 적용) | climate_env | A |
| `kepco_fuel_adj_rule.pdf` | 한전ON 연료비조정요금 (연간 상하한 ±5.0원/kWh) | fuel_adj_cap (4분기 +5원 적용값은 보도 B) | A |
| `electricity_act_decree_fund_rate.pdf` | 전기사업법 시행령 제36조 (전력산업기반기금 1천분의 27) | power_fund_rate | A |
| `re_direct_ppa_notice_current.pdf` | 「재생에너지전기의 직접전력거래 등에 관한 고시」 제2025-61호 | 직접 PPA 사용자 부담 항목(제25조③) | A |
| `re_act_amendment_21943.pdf` | 재생에너지법 법률 제21943호 (2026.9.15 공포, 2027.1.1 시행) | rec_eligible · rec_legacy_continue (부칙 제2·3조) | A |
| `sfoc_stranded_re100_2021-12.pdf` | 기후솔루션 「좌초되는 RE100 제도」 표 2 (인쇄 9쪽) | net_charge_example 40원 | B |
| `kimchang_direct_ppa_2022-09-13.pdf` | 김·장 법률사무소 「직접 PPA 고시 시행」 | 직접 PPA 부담 항목 보조 근거 | B |
| `distributed_energy_direct_trade_notice_2026-158.pdf` | 「분산에너지 특화지역에서의 전력 직접거래 등에 관한 고시」 제2026-158호 | 유사 제도 참고만 (직접 PPA 고시 아님) | — |

## 아직 원문이 없는 것

| 항목 | 지금 근거 | 원문을 받으면 |
|---|---|---|
| 2026년 1차 태양광 고정가격계약 선정결과 (한국에너지공단) | 기후에너지환경부 공고의 입찰 상한 147.686원 (저자 판단, 대리값) | cfd_price를 낙찰 평균으로 |
| 한전 송·배전 이용요금 단가표 | 공개 사례 40원 (B, 한전 중개 제3자 PPA) | 직접 PPA 부대비용을 공식 요금으로 재계산 |
| 4분기 연료비조정단가 한전 발표 원문 | 보도 2건 (B) | fuel_adj를 A로 |
| 직접 PPA 고시 제25조③6호 '기타 장관 고시 비용' | 지정 여부 미확인 | 각주만 바뀜 |

내부 결재 문서처럼 공개 여부가 불분명한 자료는 받아도 보관하지 않는다(프로젝트 규칙: 공개 자료만).
