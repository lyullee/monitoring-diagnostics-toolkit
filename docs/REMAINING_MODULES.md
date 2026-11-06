# 4~10순위 후속 개선 — v0.8.0

4번부터 10번까지 검토하고, 열교환기·RO·기화기·스팀트랩·증류탑의 구현 가능한 부분을 보완했습니다.
냉동기는 기존 동결 모델의 오경보 채널을 분석했습니다. 보일러 총재고 관측기는 필수 설비 정보가 없어 구현을 보류했습니다.
이번에 새로 평가한 진단 비교는 **모두 시뮬레이션**입니다. 실제 설비 고장 자료의 새로운 정확도를 확보한 것은 아닙니다.

| 순위 | 모듈 | 이번 완료 내용 | 아직 완료하지 못한 부분 |
|---|---|---|---|
| 4 | 열교환기 | 유량별 정상 열저항 모델, 선택적 유량 과도 구간 제외 | 현장 전열 상관식·정상/고장 검증, 상변화·다른 유동 배치 |
| 5 | RO | 압력·삼투압→NDP, 명시한 Arrhenius 식→온도 보정계수 연결 | 막별 보정 파라미터·온도 범위의 현장 적합성, 삼투압/농도분극 계산, 오염 라벨 검증 |
| 6 | 냉동기 | 기존 동결 모델의 오경보 주도 채널 분석 | 운전정책 정보 기반의 새 정상 모델과 독립 블라인드 검증 |
| 7 | 기화기 | 정상 예측값 없이 출구 저온 한계를 감시하는 선택 모드 | 정상 전열·출구 온도 예측, 착상·편류·액적 동반 진단 |
| 8 | 스팀트랩 | 공급 시작/재개 시 준비 구간 자동 판단 제외 | 트랩별 정상 배출과 누설의 실제 음향 구분 |
| 9 | 증류탑 | 정상 기액 부하–차압 지수 관계 학습 | 물리적인 습식 탑 모델·범람 예측·원인 분류 |
| 10 | 보일러 | 적용에 필요한 입력·관측기 조건을 명시 | 증기·물 총재고 관측기 구현 및 검증 |

기존 기본 모드와 설정 서명은 유지했습니다. 새 기능은 명시적으로 선택하며, 과거 냉동기 추가 경보를 자동 활성화하지 않습니다.

## 4. 열교환기: 유량에 따른 정상 UA

선택 모드 `reference_mode='flow_resistance'`에서 정상 열저항을 다음처럼 학습합니다.

```text
1/UA_expected = R0 + Rh*(mh_ref/mh)^nh + Rc*(mc_ref/mc)^nc
R0, Rh, Rc >= 0
UA_retention = UA_measured / UA_expected
score = max(1-UA_retention, 0) / degradation_limit
```

정상 양측 유량의 중앙값이 기준 유량입니다. 비음수 최소제곱의 내부 해와 경계 해를 비교합니다.
양측 유량이 충분히 독립적으로 변하지 않으면 학습을 거부합니다. 실패한 재학습은 이전 정상 기준도 지웁니다.
출력에 `expected_ua_w_k`, `ua_retention_fraction`, `added_thermal_resistance_k_w`를 추가했습니다.
온도·열수지·접근온도 검사와 정상 유량 범위 제한은 유지합니다.

기본 지수 nh=nc=0.8은 난류형 유량 의존성을 나타내는 시험용 출발값입니다. 모든 열교환기의 보편적 지수가 아닙니다.
물성·유동 영역에 맞는 `hot_flow_exponent`, `cold_flow_exponent`를 지정해야 합니다.
단상·일정 cp·준정상·대향류라는 기존 범위는 확대하지 않았습니다.
선택적 `max_flow_change_fraction_s`는 양측 상대 유량 변화율이 기준을 넘는 표본을 UNKNOWN으로 제외합니다.
이 기준은 사용자가 정해야 하며 고정된 준비 시간이나 동적 전열기를 대신하지 않습니다.

```python
from equipment_diagnostics import HeatExchangerDiagnostic
model = HeatExchangerDiagnostic(
    {'hot_in':'hi', 'hot_out':'ho', 'cold_in':'ci', 'cold_out':'co',
     'hot_flow':'hf', 'cold_flow':'cf'},
    cp_hot_j_kg_k=4180, cp_cold_j_kg_k=4180,
    reference_mode='flow_resistance', hot_flow_exponent=.8, cold_flow_exponent=.8,
    # max_flow_change_fraction_s=.01,  # 실제 운전 구간으로 별도 결정
)
model.fit(train_normal)
result = model.score(evaluation)
```

독립 ht ε–NTU 정방향 모델에 유량별 직렬 열저항을 지정해 입력을 만들었습니다.
시험의 전열 지수와 진단 모델의 지수가 일치하는 이상적인 검증이므로 결과를 현장 성능으로 일반화하지 않습니다.
시뮬레이션은 매 시각이 별개의 준정상 운전점이며 실제 유량 급변에 따른 과도 축열을 재현하지 않습니다.

## 5. RO: 보정 입력의 자동 연결

기존 `input_mode='corrected'`는 외부에서 NDP와 온도 보정계수를 받습니다.
새 `input_mode='pressures_temperature'`는 다음 **계측 또는 별도 검증 모델에서 얻은 값**을 받습니다.

| 역할 | 단위 |
|---|---|
| permeate_flow | m3/s |
| feed_pressure, concentrate_pressure, permeate_pressure | Pa, 공통 기준 |
| feed_osmotic_pressure, concentrate_osmotic_pressure, permeate_osmotic_pressure | Pa |
| membrane_temperature | K |

```text
hydraulic = (Pfeed+Pconcentrate)/2 − Ppermeate
osmotic = (pi_feed+pi_concentrate)/2 − pi_permeate
NDP = hydraulic − osmotic
factor = exp[(Ea/R)*(1/T − 1/Treference)]
normalized_permeability = permeate_flow*factor/(area*NDP)
```

막별 `activation_energy_j_mol`과 식의 검증 온도 범위 `temperature_range_k`를 **필수**로 요구합니다.
기준온도는 기본 298.15 K이며 검증 범위 안에 있어야 합니다. 이 범위 밖은 UNKNOWN입니다.
유동 방향의 압력 순서·음의 삼투압·양의 NDP도 검사합니다.
TCF의 곱셈 방향은 위 정의에 고정되어 있어 제조사의 역수 정의를 그대로 넣으면 안 됩니다.

```python
from equipment_diagnostics import ROMembraneDiagnostic
model = ROMembraneDiagnostic(
    {'permeate_flow':'q', 'feed_pressure':'pf', 'concentrate_pressure':'pc',
     'permeate_pressure':'pp', 'feed_osmotic_pressure':'pi_f',
     'concentrate_osmotic_pressure':'pi_c', 'permeate_osmotic_pressure':'pi_p',
     'membrane_temperature':'t'},
    membrane_area_m2=10, input_mode='pressures_temperature',
    activation_energy_j_mol=20000, temperature_range_k=(285,315),
)
```

면적·활성화에너지·온도 범위의 예제 숫자는 **시뮬레이션 설정**이며 실제 막의 권장값이 아닙니다.
TDS/전도도에서 삼투압을 임의 추정하지 않았습니다. 농도분극·분포형 회수율의 효과를 해석하는 완전 RO 모델도 아닙니다.
올바른 외부 NDP/TCF를 제공한 기존 모드와 결과가 일치하는 것을 확인했습니다. 진단 정확도를 높였다기보다 보정 입력의 정의·단위·적용 범위를 모듈에 연결한 개선입니다.

## 6. 냉동기: 오경보의 채널별 기여

v0.6의 학습·보정된 기준을 그대로 불러와 정상 평가 12개 파일만 재분석했습니다.
학습·보정·임계값 변경·파일명에 따른 정상 모드 생성은 하지 않았습니다. 이전 정상 FP/판단 표본 수를 정확히 재현했습니다.
각 **경보 표본**에서 원시 채널 점수가 가장 큰 채널을 집계했습니다. 동률은 채널명 정렬 순서로 하나만 셉니다.

| 누적 단계 | 정상 오경보 표본 | 오일 공급압력 채널이 최대인 표본 | 비중 |
|---|---:|---:|---:|
| 1 오일·과냉·과열 | 16,301 | 15,918 | 97.65% |
| 2 EWMA | 23,516 | 22,572 | 95.99% |
| 3 응축기 지표 | 23,486 | 22,538 | 95.96% |

이는 **점수 기여**이지 공급압력 센서 고장이나 오일 회로 고장의 증명이 아닙니다.
정상 오일 충전·조정·압력 제어 조건에 따른 분포 차이를 먼저 확인해야 합니다.
같은 평가 자료에서 문제 채널을 보고 제거한 뒤 개선 성능을 최종 성능처럼 보고하지 않았습니다.
추가로 필요한 것은 오일 회로 제어 상태·설정 압력·운전모드 정보와 새 독립 평가 자료입니다.
`chiller_attribution.json`에 파일별 채널 기여를 저장했습니다. 기존 냉동기 모델의 성능 수치는 바꾸지 않았습니다.

## 7. 기화기: 예측 모델 없이 가능한 저온 감시

`prediction_mode='minimum_only'`에서 출구 온도 K·질량유량 kg/s만 받습니다.
`minimum_outlet_k`를 반드시 지정하며, 흐르는 상태에서 해당 한계보다 낮을 때 경보를 냅니다.
기존 `shortfall_limit_k`는 점수 정규화 온도 폭으로 사용합니다. 기본 모드 `external`은 유지했습니다.

```python
from equipment_diagnostics import VaporizerDiagnostic
model = VaporizerDiagnostic(
    {'outlet_temperature':'t', 'mass_flow':'q'},
    shortfall_limit_k=5, minimum_outlet_k=280, prediction_mode='minimum_only',
)
```

한계 온도 280 K는 시험 숫자입니다. 현장 한계는 공정 조건으로 정해야 합니다.
별도 정상 예측값을 만들어 넣지 않습니다. 단순 저온 감시이며 착상·기화 부족 원인 진단이나 안전계장 검증은 아닙니다.
기화기 종류(AAV/수조식/해수식), 형상·전열면, 유체·압력, 열원 상태·유량이 없으므로 일반화한 정상 전열 예측기는 보류했습니다.

## 8. 스팀트랩: 시동 경보의 구분

`startup_exclusion_s`를 지정하면 관측된 공급 ON 구간 시작 이후 해당 시간은 UNKNOWN입니다.
공급 OFF→ON, 결측, 시간 단절, 에피소드/관측 모드 변경 시 재시작합니다. 첫 데이터가 이미 정상 운전 중이어도 시작 경과시간을 모르므로 동일하게 준비 구간을 둡니다.
이력 창을 반영해 배치/청크 판단이 일치하도록 했습니다. 기본값 0은 기존 동작입니다.
예제 60초는 Newton 가열 시험을 위한 값이며 모든 트랩에 적용하는 보편적 시간은 아닙니다.
시동 오경보를 정상으로 재분류한 것이 아니라 판단을 보류한 것이므로 판단률과 전체 대상 고장 검출률 감소를 함께 보고합니다.
정상 배출과 증기 누설의 음향이 유사한 문제는 해결하지 않았습니다.

## 9. 증류탑: 정상 부하 관계의 학습

`reference_mode='learned_power'`는 정상 자료에서 다음 경험식을 학습합니다.

```text
ln(DP_expected) = intercept + nv*ln(v/vref) + nl*ln(l/lref)
nv,nl >= 0
DP_normalized = DP_measured/DP_expected * exp(intercept)
```

기존 수동 지수 지정 `declared_power`를 유지했습니다. 새 모드에서는 지수 인수를 생략합니다.
독립적인 기체/액체 **내부 부하** 변화가 부족하면 학습을 거부하고, 정상 유량 범위 밖은 UNKNOWN입니다.
원료 유량·탑정 유출량을 내부 양상 유량으로 자동 대체하지 않습니다.

```python
from equipment_diagnostics import ColumnHydraulicsDiagnostic
model = ColumnHydraulicsDiagnostic(
    {'pressure_drop':'dp', 'vapor_flow':'v', 'liquid_flow':'l'},
    reference_vapor_flow_kg_s=1, reference_liquid_flow_kg_s=1,
    reference_mode='learned_power',
)
model.fit(train_normal)
```

시험은 지정한 정상 멱함수와 0.5% 이내 잡음을 쓴 경험식 시뮬레이션입니다. 실제 습식 탑이나 플러딩의 독립 물리 검증은 아닙니다.
실제 플러딩으로 부하가 학습 영역을 벗어나면 판단 보류할 수 있습니다. 범람 조기 예측기로 해석하지 않습니다.

## 10. 보일러: 남은 구현 조건

현재 질량수지와 오차 한계 전파는 사용할 수 있지만 검증된 총 증기·물 재고가 입력되어야 합니다.
다음 정보 없이 드럼 수위를 총재고로 바꾸는 관측기를 만들지 않았습니다.

- 드럼 형상·유효 용적·수위–체적 관계와 증발관/다운커머 등 감시 경계의 용적
- 동기화된 수위·압력·온도와 급수·증기·블로다운 유량
- 이상 운전에서도 적용 가능한 기포/보이드·swell/shrink 모델
- 총재고 또는 독립적인 질량수지 정답으로 검증할 정상/고장 자료

드럼 한 곳의 포화 물성·액체 체적만 계산해 전체 보일러 재고로 선언하지 않습니다.

## 검증 결과와 재현

아래는 지정한 정상/고장 시뮬레이션의 **표본 단위** 결과입니다. 학습·정상 보정·정상 평가·고장 평가 시드는 각 모듈에서 202611051/52/53/54로 분리했습니다.
열교환기·RO·탑에 동일한 정상 보정 q99(원시 점수 최소 1) 정책을 적용하고 평가 전에 동결했습니다.
스팀트랩·기화기는 학습 없는 공학 한계이며 준비 시간/한계값을 평가 전에 고정했습니다.

| 모듈 | 정확도 전→후 | 검출률 전→후 | 오경보율 전→후 | 판단률 전→후 |
|---|---:|---:|---:|---:|
| 열교환기 | 67.54→100% | 37.59→100% | 2.51→0% | 99.75→99.75% |
| RO | 100→100% | 100→100% | 0→0% | 100→100% |
| 증류탑 | 79.88→100% | 62.25→100% | 2.50→0% | 100→100% |
| 스팀트랩 | 95.58→100% | 100→100% | 8.83→0% | 100→90% |
| 기화기 저온 한계 | 기존은 예측값 없어 실행 불가→100% | 미산출→100% | 미산출→0% | 미산출→100% |

정확도·검출률·오경보율은 유효 판단 표본 기준입니다. UNKNOWN을 정상으로 세지 않습니다.
스팀트랩의 판단 보류를 포함한 전체 대상 고장 검출률은 100→90%입니다. 두 설정이 함께 판단한 구간에서는 기존 설정도 오경보가 없습니다.
기화기의 100%는 임계값 위/아래를 넣은 기능 시험 결과이며 실제 고장 성능으로 의미를 확장하지 않습니다.
이상적인 모델 일치 시나리오의 100%가 실제 설비에서도 나온다는 뜻이 아닙니다.

추가 시험 16개를 포함한 비통합 시험 **210개**, 기존 외부 저장소 연동 시험 **7개**가 통과했습니다.
정상/고장·알려진 계수 회복·단위/참조 불일치·물리 범위/극단값·식별 불가 거부·JSON 왕복·모델 불변·배치/청크 일치를 확인했습니다.
독립 감사는 CSV에서 혼동행렬·비율·공통 표본을 패키지 지표 함수 없이 재집계하고, 자료 분리와 동결 파일/소스 해시를 검증했습니다.

```powershell
.\.venv\Scripts\python.exe scripts/validate_remaining_modules.py
.\.venv\Scripts\python.exe scripts/analyze_chiller_false_alarms.py
.\.venv\Scripts\python.exe scripts/audit_remaining_modules.py
.\.venv\Scripts\python.exe scripts/render_remaining_modules.py
.\.venv\Scripts\python.exe -m pytest -q -m 'not integration' -o junit_family=legacy --junitxml=outputs/remaining_modules/regression.xml
.\.venv\Scripts\python.exe scripts/verify_integrations.py
```

산출물은 `outputs/remaining_modules/`의 보고서·결과 JSON·예측 CSV·개발 동결 파일·냉동기 기여 분석·감사 JSON·회귀 시험 XML입니다.
이전 버전의 실제 공장/실험 평가 결과는 각 버전의 역사적 근거로 유지하며 이번 시뮬레이션 결과와 합치지 않습니다.

근거와 독립 시험 도구:

- [ht 내부 대류 문서](https://ht.readthedocs.io/en/latest/ht.conv_internal.html): 유동 영역별 상관식과 유량 지수 선택 참고. 실제 기하·물성별 상관식 검증은 별도 필요.
- [ht ε–NTU 문서](https://ht.readthedocs.io/en/latest/ht.hx.html#ht.hx.effectiveness_from_NTU): 열교환기 독립 정방향 시험에 사용.
- [WaterTAP RO 문서 원본](https://github.com/watertap-org/watertap/blob/main/docs/technical_reference/unit_models/reverse_osmosis_0D.rst): 압력·삼투압 구동의 기본 관계 참고. WaterTAP solver나 막별 Arrhenius 계수를 재현/검증한 것은 아님.
