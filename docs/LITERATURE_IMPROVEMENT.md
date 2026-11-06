# 문헌 기반 추가 보완 — v0.15.0 (2026-11-06)

외부 원문·공식 해설·저자/발행기관 자료를 검색해 후보를 구현했다. 학습·보정·평가 분리는 유지했다. **이번 성능 수치는 전부 기존 실제 실험 자료를 재사용한 개발 평가다. 새 독립 고장 검증은 없다.** 다른 논문의 진단 정확도를 이 프로그램의 정확도로 사용하지 않았다.

히트펌프는 블록 보정 signed CUSUM을 추가하는 개발 프로파일을 선택했다. 엔진 필터 후보는 모두 미채택했다. 기존 HSE 필터, 냉동기, RO 등의 기준은 바꾸지 않았다. 가장 약한 EF10.1의 미검출은 해결되지 않았다.

## 문헌에서 가져온 아이디어와 구현 차이

| 번호 | 1차 출처 | 실제로 반영한 범위 / 재현하지 않은 부분 |
| --- | --- | --- |
| 1 | [NIST tabular CUSUM](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm) | Signed standardized one-sided C=max(0,C+z-k); predeclare target0.5sigma so k=.25. Do not use independent-normal ARL formulas. |
| 2 | [NIST EWMA](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc324.htm) | Small persistent changes motivate temporal monitoring; previous EWMA retained as historical baseline, not newly invented improvement. |
| 3 | [Larsen et al.2019, Model based Level Shift Detection in Autocorrelated Data Streams using a moving window](https://arxiv.org/abs/1907.05453) | Autocorrelation invalidates naive independence assumptions. We diagnose dependence and use blocked calibration; not reproducing their moving-window test. |
| 4 | [Politis and Romano1994, The Stationary Bootstrap](https://doi.org/10.1080/01621459.1994.10476870) | Preserve short-range serial dependence by resampling blocks. Our fixed-length noncircular within-episode resampling is a stated adaptation, not their geometric-length stationary bootstrap. |
| 5 | [Bootstrap Design of Control Charts for Autocorrelated Data2007](https://www.research.unipd.it/handle/11577/2474400) | Control limits should account for dependent residuals and parameter uncertainty; ours conditions on a frozen upstream model and does not refit bootstrap parameters or reproduce AR-sieve calibration. |
| 6 | [Bellanco et al.2022, Common fault effects on a natural refrigerant, variable-speed heat pump](https://doi.org/10.1016/j.ijrefrig.2021.10.017) | Same propane experimental system: variable-speed control compensates faults, and evaporator-flow fault has weak COP effect. Study a joint signed residual direction; not assuming COP alone suffices. The chosen projection is our implementation, not their algorithm. |
| 7 | [Soft fault detection strategies in heat pumps: A case study investigating virtual sensor methodologies for evaporator fouling](https://doi.org/10.1016/j.csite.2024.105508) | Motivates physics-derived evaporator-side features and experimental checks. Our (Qcond-W)/(Tsource,in-Tevap) proxy is a simplification we derive, not their virtual airflow algorithm; missing source measurements cannot be manufactured. |
| 8 | [Experimental validation of a neural-network-based method for fault detection in heat pump evaporators](https://publications.rwth-aachen.de/record/1038664) | Supports decoupled evaporator flow features and experimental validation; does not establish that our available channels can recover water flow or weak faults. |

문헌의 일반 원리를 적용한 자체 구현이며 논문 알고리즘을 그대로 재현했다는 주장은 하지 않는다. 특히 고정 표본 길이의 블록 재표본화는 Politis–Romano의 기하분포 블록 길이를 쓰는 stationary bootstrap과 다르다. AR-sieve 논문의 재학습 불확실성도 구현하지 않았다.

## 구현 내용

1. `SignedResidualCUSUM`: 양/음 방향을 보존한 정상 표준화 잔차에 C=max(0,C+(z−k)Δt/Δt_ref)를 적용했다. 목표 변화 0.5σ에 대응해 k=0.25를 선언했으며 평가 결과로 최적화하지 않았다. 음의 잔차는 누적 증거를 감소시킨다.
2. 별도 정상 보정: 최소 한계 5와 실제 정상 보정 경로의 최대 통계량을 사용했다. 블록 후보는 정상 보정 자료를 256회 재표본화해 1시간 경로 최대값의 99백분위수도 반영했다. 시험 고장이나 평가 정상 자료로 임계값을 맞추지 않았다.
3. 블록은 실제 결측·운전 구간·모드·문맥 경계를 넘지 않는다. 명목 60초를 기준 간격으로 환산한 고정 표본 길이다. 불규칙 시계에서는 실제 구간 길이가 달라지므로 actual_block_span_range_s를 저장했다. 블록 내부 실제 Δt를 보존하고 인공 연결부는 선언한 기준 간격을 사용한다.
4. AR(1) 후보: 정상 학습 자료의 연속 표본 쌍에서 계수와 예측 오차 분포를 추정했다. 안정 조건 내 ±0.99로 제한하며 첫 관측은 판단 보류한다. 불규칙 시계의 정확한 연속시간 AR 모형은 아니다.
5. 히트펌프: 기존 증발온도 감소·전력 증가·속도 증가·COP 감소 잔차를 정상 공분산으로 선형 투영했다. 양의 부분만 남기는 거리 요약과 비교하기 위한 별도 경로다. 기존 경보와 OR로 결합하며 새 경로가 판단 보류해도 기존 판단을 유지한다.
6. `evaporator_conductance_proxy`: (Qcond−W)/(Tsource,in−Tevap)를 계산했다. 이는 정상 상태 열수지 근사와 입구 온도를 쓰는 자체 지표이며 실제 UA·열원 유량이 아니다. 10℃는 원 실험 논문의 설정값이고 새로 측정한 온도가 아니다. 손실·열 저장을 무시한 이 후보는 기본 프로파일로 선택하지 않았다.
7. 평가: 고장 시작 전부터 활성화된 경보, 시작 후 새 경보, 유효 정상 관측 시간당 오경보 구간 수를 추가했다. 시작 전 오경보를 지연 0초의 조기 진단으로 해석하지 않는다.

이 경험적 블록 보정은 정상 분포의 전이나 블록보다 긴 의존성까지 보장하지 않는다. 99백분위수를 썼다는 사실은 현장 오경보율 1%를 보증하지 않는다.

## 히트펌프 — 기존 실제 평가 재사용

| 후보 | 정확도 | 검출률 | 오경보율 | 대상 판단률 | TP / FN / FP / TN |
| --- | --- | --- | --- | --- | --- |
| baseline | 97.9394% | 97.7483% | 0.0000% | 100.0000% | 5166 / 119 / 0 / 490 |
| innovation_block60 | 97.9221% | 97.7483% | 0.2041% | 100.0000% | 5166 / 119 / 1 / 489 |
| innovation_empirical | 97.8009% | 97.7483% | 1.6327% | 100.0000% | 5166 / 119 / 8 / 482 |
| signed_block60 | 98.3377% | 98.1835% | 0.0000% | 100.0000% | 5189 / 96 / 0 / 490 |
| signed_empirical | 98.3550% | 98.2025% | 0.0000% | 100.0000% | 5190 / 95 / 0 / 490 |
| source_proxy_signed_block60 | 98.1818% | 98.0132% | 0.0000% | 100.0000% | 5180 / 105 / 0 / 490 |
| source_proxy_signed_empirical | 98.1818% | 98.0132% | 0.0000% | 100.0000% | 5180 / 105 / 0 / 490 |

대상 5,775행(정상 490 / 고장 5,285), 시동 제외 등을 포함한 원시 6,405행 기준 판단률은 90.1639%로 유지했다. 표의 100%는 평가 대상 중 판단률이다.

| 지표 | 기존 v0.13 | 선택 signed_block60 |
| --- | --- | --- |
| EF 검출률 | 96.1656% | 96.4724% |
| 약한 EF10.1 검출률 | 49.0798% | 49.0798% |
| 약한 EF10.1 TP / FN | 80 / 83 | 80 / 83 |
| 정상 FP / 대상 | 0 / 490 | 0 / 490 |
| 관측 양성 구간 검출 | 35 / 35 | 35 / 35 |
| 첫 유효 양성부터 최대 지연 | 510초 | 510초 |

전체 TP는 5,166→5,189로 23개 증가했다. 가장 약한 EF10.1과 최대 지연은 개선되지 않았다. 35개 구간은 시동 제외 후 알려진 실험 조건의 관측 구간이며 독립 고장 35건이 아니다. 정상 490개도 같은 정상 두 실험을 시간 분리한 상관 표본이다.

signed_empirical도 재사용 지표는 통과했지만, 자기상관을 고려하는 방향에 맞춰 signed_block60을 개발 프로파일로 선택했다. 이는 결과를 본 뒤 내린 개발 선택이다. 평가 자료를 새 검증으로 재명명하지 않았다. AR1 후보는 정상 오경보가 생겨 미채택했다.

## 엔진 필터 — 기존 실제 평가 재사용

| 후보 | 정확도 | 검출률 | 오경보율 | 대상 판단률 | TP / FN / FP / TN |
| --- | --- | --- | --- | --- | --- |
| baseline | 94.7758% | 90.0889% | 0.0294% | 100.0000% | 13580 / 1494 / 4 / 13596 |
| innovation_block60 | 80.6373% | 99.9005% | 40.8418% | 99.7105% | 15058 / 15 / 5521 / 7997 |
| innovation_empirical | 80.5568% | 99.9005% | 41.0120% | 99.7105% | 15058 / 15 / 5544 / 7974 |
| signed_block60 | 84.9655% | 99.7346% | 31.4044% | 100.0000% | 15034 / 40 / 4271 / 9329 |
| signed_empirical | 78.0324% | 99.8474% | 46.1471% | 100.0000% | 15051 / 23 / 6276 / 7324 |

필터는 새 후보 모두 미채택했다. 블록 보정 signed 후보는 검출률이 높아졌지만 오경보율도 31.40%로 증가했다. AR1 예측 오차 감시 역시 정상 전이를 해결하지 못했다. 기존 기준의 60% 부하 최대 지연 2,314초는 남아 있다.

| 파일 | 제공자 정상 구간 log(DP/정상 예측DP) 평균 | 표준편차 |
| --- | --- | --- |
| Reference_Data.csv | 0.02403 | 0.04213 |
| AF_Clogging_40_Load.csv | 0.18083 | 0.06223 |
| AF_Clogging_60_Load.csv | 0.04117 | 0.01493 |
| AF_Clogging_75_Load.csv | 0.11093 | 0.05918 |
| AF_Clogging_85_Load.csv | 0.12608 | 0.05218 |

정상 평가에서도 운전 파일별 잔차 평균 차이가 관찰됐다. 이런 차이는 지속 누적으로 경보가 될 수 있다. 위 표는 실패 원인 분석용이며 이 정상 평가 자료로 재보정하지 않았다. 원인에는 모델·센서·실제 운전 차이가 있을 수 있어 물리 원인을 확정하지 않았다. 정상 시험의 시작 부분을 자동으로 정상이라고 가정해 새 기준으로 학습하는 우회도 하지 않았다.

## 평가 지표 보완

| 대상 | 후보 | 양성 관측 구간 | 시작 전 이미 활성 경보 | 정상 경보 구간 | 유효 정상 관측 시간(h) | 정상 시간당 경보 구간 |
| --- | --- | --- | --- | --- | --- | --- |
| marine | baseline | 4 | 0 | 4 | 6.0894 | 0.6569 |
| marine | innovation_block60 | 5 | 4 | 5 | 6.0378 | 0.8281 |
| marine | innovation_empirical | 5 | 4 | 5 | 6.0378 | 0.8281 |
| marine | signed_block60 | 4 | 4 | 4 | 6.0894 | 0.6569 |
| marine | signed_empirical | 4 | 4 | 5 | 6.0894 | 0.8211 |
| heatpump | baseline | 35 | 0 | 0 | 1.3556 | 0.0000 |
| heatpump | innovation_block60 | 35 | 0 | 1 | 1.3556 | 0.7377 |
| heatpump | innovation_empirical | 35 | 0 | 7 | 1.3556 | 5.1639 |
| heatpump | signed_block60 | 35 | 0 | 0 | 1.3556 | 0.0000 |
| heatpump | signed_empirical | 35 | 0 | 0 | 1.3556 | 0.0000 |
| heatpump | source_proxy_signed_block60 | 35 | 0 | 0 | 1.3556 | 0.0000 |
| heatpump | source_proxy_signed_empirical | 35 | 0 | 0 | 1.3556 | 0.0000 |

시간 노출량은 연속하며 유효한 정상 표본 사이의 Δt만 합산한다. 기록 공백을 정상 운전 시간으로 더하지 않았다. 위 시간당 수치는 관측 범위의 경보 구간 빈도이며 전체 현장 운전의 장기 빈도가 아니다.

## 검증과 보존

- 비연동 회귀·물리 시험 **277개** 및 기존 프로젝트 객체 연동 **7개** 통과. 새 시험은 NIST 형태의 손계산, 음의 잔차에 의한 증거 감소, Δt·결측·문맥·운전 구간 및 경보 지속시간 초기화, AR1 손계산, 블록 경계·실패 복구, 직렬화·스트리밍 일치, 극단값과 열전달 근사 계산을 다룬다. 새 파이프라인은 signal_basis_id로 상위 기준/변환을 묶어 같은 무차원 단위라도 다른 파생 신호의 잘못된 연결을 거부한다.
- 별도 코드가 원본 정답·시각·회귀 입력을 확인하고 **153,126개 후보 표본의 CUSUM·AR1·지속시간·경보 결합을 재구성**했다. 독립 고장 표본 153,126개라는 뜻은 아니다.
- baseline_v014_source.zip에 변경 전 소스를 보존했다. initial_signed와 innovation_attempt에 앞선 후보의 결과·예측·동결 기준을 남겼다. 최신 결과는 해당 버전 소스 해시·원본 기준 해시·학습/보정 지문과 연결했다.
- SignedResidualCUSUM은 Python API이며 기존 CLI 진단 종류 11개는 유지한다. 저장한 channels/params/reference로 복원하며, 파이프라인 조립·실행 예시는 scripts/improve_from_literature.py에 있다.

## 다른 설비에서 문헌이 제시한 다음 보완

| 설비 | 1차 자료 | 다음 적용 아이디어 | 이번에 남긴 제한 |
| --- | --- | --- | --- |
| 젖은 코일 | [Hu et al., outdoor air-side fouling and frost growth](https://www.osti.gov/servlets/purl/1673810) | 착상·오염·공기 조건을 함께 봐야 한다. 다음 후보는 팬 제어/회전수와 열·차압 잔차를 함께 사용한다. | 현재 팬 운전 신호·정상 반복 자료가 부족하다. 오염으로 감소한 유량을 단순 범위 밖으로 제외해 높은 검출률을 주장하지 않는다. |
| RO | [DuPont FilmTec technical manual](https://www.dupont.com/content/dam/water/amer/us/en/water/public/documents/en/RO-NF-FilmTec-Manual-45-D01504-en.pdf) | 유량·온도 영향을 보정한 성능과 feed-to-concentrate 차압을 함께 감시하고 초기 기준을 확보한다. | 현재 압력 순서 오류를 임의 상쇄하지 않는다. 압력 교정·기준 확인 후 정규화 지표와 막 건전성 지표를 추가한다. |
| 보일러 | [Astrom and Bell2000, Drum-boiler dynamics](https://doi.org/10.1016/S0005-1098(99)00171-5) | 수위와 재고를 연결하려면 압력·질량/에너지 수지·순환 및 기포 거동을 다루는 동적 모델이 필요하다. | 현재는 외부 기포율을 받는 재고 계산이다. 형상·열입력·급수 엔탈피·상태 자료 없이 동적 관측기를 구현 완료했다고 하지 않는다. |

다음 우선순위는 ① 엔진 필터의 별도 날짜/운전 모드 정상 기준과 독립 막힘 반복시험 ② 히트펌프 약한 EF 반복시험 및 실제 열원 입출구 계측 ③ 젖은 코일 팬 운전 신호 확보다. 현재 평가 자료의 정상 부분을 학습으로 옮겨 수치를 높이는 방식은 사용하지 않는다.
