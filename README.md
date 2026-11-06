# Monitoring Diagnostics Toolkit

**온도·압력·유량·재고·위치 센서로 설비의 물리 성능과 정상 상태 편차를 감시하는 Python 툴킷입니다.**
단위 설비 모듈을 독립적으로 사용하거나 공통 시계열 계약으로 연결합니다. 물질수지·열수지·저항·투수성·정상 잔차를 계산하고, 계산량·유효성·판단 이유·경보를 함께 반환합니다.

Equipment-specific process monitoring with explicit SI inputs, inspectable residuals,
separate normal fitting/calibration, causal alarms and reproducible research records.

**연구용 Alpha입니다.** 계산 검증과 실제 고장 검증을 구분합니다. 경보는 고장 원인 확정이나 확률이 아닙니다.
최신 히트펌프 개선은 응축온도 0.3 K 차이에 의존하며 날짜·계측 편차와 유량 고장의 효과를 분리하지 못했습니다.

| 항목 | 값 |
| --- | --- |
| 배포 이름 | `monitoring-diagnostics-toolkit` |
| Python import / CLI | `equipment_diagnostics` / `equipment-diagnose` |
| Python / 기본 의존성 | 3.11 이상 / NumPy |
| 공개 릴리스 | 0.17.0: 공개 배포·설명 보강. 최신 수치 연구 기준은 0.16.0 |
| 코드 라이선스 | [MIT](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/LICENSE), 외부 자료는 [별도 권리](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/THIRD_PARTY_NOTICES.md) |
| 전체 생성자·기본값 | [API_REFERENCE](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/API_REFERENCE.md), [JSON 목록](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/API_CATALOG.json) |

## 문서 바로가기

[사용 설명서](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/USER_GUIDE.md) · [모델 식·가정·출력](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/MODEL_GUIDE.md) ·
[개발 이력](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/DEVELOPMENT_HISTORY.md) · [재검증 절차](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/REPRODUCIBILITY.md) ·
[데이터 출처](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/DATA_PROVENANCE.md) · [후속 연구 인수인계](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/RESEARCH_HANDOFF.md) · [전체 문서 지도](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/INDEX.md)

## 설비별 단위 모듈: CLI 11종과 Python API

아래 입력은 **역할(role) 이름**입니다. 실제 열 이름은 `channels={역할: 열이름}`으로 연결합니다.
`?`는 선택 센서입니다. 모든 진단은 공통 `DiagnosticResult`를 반환하며 정확한 설정 철자와 기본값은 [API_REFERENCE](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/API_REFERENCE.md)에 있습니다.

| 종류 / Python 클래스 | 목적·진단 대상 | 입력 센서·단위 | 주요 설정 | 물리 출력·적용 범위 |
| --- | --- | --- | --- | --- |
| `mass_balance` / `MassBalanceDiagnostic` | 탱크 미설명 질량 손실 | `inventory_mass` kg, `inflow`, `outflow` kg/s, `known_loss`? kg/s | `loss_limit_kg_s`, `window_s`, 재고·유량 오차 한계 | 창 평균 손실 kg/s, 순유량·재고변화율, 손실 하한/상한. 누설 위치·원인 미확정 |
| `boiler_mass_balance` / `BoilerBalanceDiagnostic` | 보일러 급수·증기·총재고 수지 | **물+증기 총재고** kg, 급수·증기 kg/s, 블로다운? kg/s | 탱크와 동일 | 손실 kg/s. 드럼 수위만으로 총재고를 대체할 수 없음 |
| `heat_exchanger` / `HeatExchangerDiagnostic` | 정상 대비 열전달 저하 | `hot_in`, `hot_out`, `cold_in`, `cold_out` K; `hot_flow`, `cold_flow` kg/s | `cp_hot_j_kg_k`, `cp_cold_j_kg_k`, 저하 한계, 유량 저항 모델 | 열량 W, 열수지 불일치, LMTD K, UA W/K. 단상·준정상·대향류 |
| `hydraulic_resistance` / `HydraulicResistanceDiagnostic` | 필터·배관 저항 증가 | `pressure_drop` Pa, `volume_flow` m3/s 또는 `flow_ratio` 1; `density`? kg/m3, `viscosity`? Pa*s | 참조 유량·밀도, 지수 또는 점성/관성 혼합 모형, 증가 한계 | 보정 차압 Pa·저항 지표. 고정 형상·단상; 0 유량은 판단 불가 |
| `vaporizer` / `VaporizerDiagnostic` | 출구 저온·예측 대비 온도 부족 | `outlet_temperature` K, `mass_flow` kg/s; 예측 모드의 `predicted_temperature` K; 선택 엔탈피 J/kg | `shortfall_limit_k`, `minimum_outlet_k`, `prediction_mode` | 온도 부족 K, 저온 한계, 선택 열량 W. 착상·불완전 기화 원인 확정 아님 |
| `ro_membrane` / `ROMembraneDiagnostic` | 보정 투수성 저하 | `permeate_flow` m3/s, `net_driving_pressure` Pa, `temperature_correction` 1; 또는 원 압력·삼투압·막온도 경로 | `membrane_area_m2`, 저하 한계, 온도보정 계수·범위 | 정규화 투수성 m/(Pa*s). 압력 순서·TCF 방향 중요; 오염 종류 분류 아님 |
| `valve_tracking` / `ValveTrackingDiagnostic` | 명령–실측 위치 추종 편차 | `command`, `position`: 모두 0~1 분율, 단위 `1` | `error_limit_fraction`, `delay_s`, 선택 1차 응답 시정수 | 기대 위치·추종 오차. 미계측 위치 추정·스틱션 원인 확정 아님 |
| `column_hydraulics` / `ColumnHydraulicsDiagnostic` | 부하 대비 탑 차압 증가 | `pressure_drop` Pa, 내부 `vapor_flow`, `liquid_flow` kg/s | 참조 내부 유량·선언/학습 멱지수·증가 한계 | 정상 부하 보정 차압 Pa. 공급 유량을 내부 유량으로 대체하면 안 됨 |
| `steam_trap` / `SteamTrapDiagnostic` | 공급 중 저온·저음향 / 고온·고음향 | `steam_temperature`, `trap_temperature` K; `acoustic_level`, `supply_on` 1 | 현장 음향 임계값·온도 여유 K·시동 제외 s | 온도 부족 K, 패턴 점수. 정상 응축수와 증기 누설 구별 미검증 |
| `chiller_performance` / `ChillerPerformanceDiagnostic` | 냉동기 성능·조건별 정상 잔차 | `chilled_in`, `chilled_out`, `cooling_out`, `evaporating_temperature`, `condensing_temperature` K; `chilled_flow` kg/s, `electric_power` W; 확장 센서? | cp·정상 모드·회귀·단계별 잔차 한계; 확장 모드에 냉각수 입구·오일 압력/온도 등 필요 | 냉동능력 W·냉방 COP·접근온도 K·잔차. 추가 단계 높은 오경보로 미채택 |
| `heat_pump_performance` / `HeatPumpPerformanceDiagnostic` | 히트펌프 냉매측 상태 편차 | `condenser_duty`, `electric_power`, `heat_demand` W; `evaporating_temperature`, `condensing_temperature`, `liquid_line_temperature`, `discharge_temperature` K; `refrigerant_mass_flow` kg/s, `compressor_speed` 1/s | 부하 조건부 기준·cycle/extended 특징·별도 정상 보정 | 난방 COP·과냉/토출 과열 K·회전당 냉매량 kg·잔차. 물측 냉동기와 별개 |

공통 경보 설정은 `persistence_s`, `max_gap_s`, `allowed_modes`입니다. `operating` 역할을 선택 제공하면 값 1인 관측만 판정합니다.
기본 임계값이 현장에 적합하다고 보장하지 않습니다. 참조값이 필요한 모형은 정상 자료로 `fit`하거나 동결 기준을 `set_reference`로 복원합니다.

## 추가 Python 모듈

이들은 CLI 11종에 자동 등록되지 않습니다. `from equipment_diagnostics import ...`로 사용합니다.

| API | 목적 | 입력·학습 정보 | 출력·주의점 |
| --- | --- | --- | --- |
| `LoadConditionedPressureDiagnostic` | 엔진 부하·회전수 보정 차압 | 차압 Pa, 축동력 W, 회전수 1/s; 정상 학습·보정 | 기대/과잉 차압·점수. 공기 유량을 측정한 저항 모형 아님 |
| `WetCoilAirsideDiagnostic` | 젖은/착상 코일 공기측 감시 | 차압 Pa, 체적유량 m3/s, 건공기 kg/s, 입출구 K·습도비 1 | 열량 W·수분 제거 kg/s·밀도·보정 차압. 실제 오염 검출력 부족 |
| `FilterServiceRiskModel` | 미래 교체 한계까지 수명 회귀 | 차압 Pa, 유량비 1, 별도 정답 수명 s | 추정 수명·위험. 현재 막힘 정답과 다름 |
| `FilterRiskClassifier` | 미래 교체 한계 위험 분류 | 위 입력 + 선택 분진 공급비·재료 코드 1, 정답 수명 s | 트리 투표·보정 위험; 학습은 `learning` extra |
| `FilterBoostedRiskClassifier`, `FilterBoostedLifeModel`, `FilterRiskEnsemble` | 부스팅·결합 비교 후보 | 위 입력·정답, 개별 모형 설정 | 위험/수명·예측 차이. 최신 비교 후보는 미채택 |
| `TemporalEvidenceDiagnostic` | EWMA/CUSUM 누적 편차 | 양의 상위 점수 1, 난방 요구 W; 정상 학습·보정 | 부하별 누적 지표. 앞단 점수의 출처 보존 |
| `ResidualCoherenceDiagnostic` | 여러 잔차 동시 변화 | 정규화 잔차 4개(1), 부하 W | 정상 공분산 대비 방향성 거리; 원인 확정 아님 |
| `SignedResidualCUSUM` | 작은 양의 잔차 누적 | 부호 있는 잔차 1, 문맥 코드 1 또는 부하 W | 시간 가중 누적합·정상 블록 보정·선택 AR1 오차 |
| `ConditionalResidualDiagnostic` | 운전조건별 정상 응답 예측 | 역할별 특징/응답 단위·로그·방향·최소 scale·고정 순서 | 기대값·표준화 잔차·과거 평균. 로그 설정의 observed/expected는 변환 공간 값 |
| `WindowChangeDiagnostic` | 과거 잔차 평균 사이 증가 | 잔차 1, 창·과거 지연 s, 증가 한계 | 변화 점수. 일정 오프셋에 불변; 필터 후보는 오경보로 미채택 |
| `HysteresisAlarmDiagnostic` | 경보 확인·해제 지연 | 상위 점수 1, 켜짐/꺼짐 비율·확인/유지 s | 경보 상태. 유지 효과는 원시 검출력 개선과 별도 |
| `StreamingDiagnostic` | 연속 청크 인과 재생 | 진단 객체·겹치지 않는 배치·표본 상한 | `push(batch)` → 진단 결과. 전체 이력 모형은 상한 초과 시 실패 |
| `calibrated_level` | 교정 전압→수위 | 전압 V·기울기 m/V·절편 m·검증 범위 | 수위 m를 추가한 배치; 범위 밖 invalid |
| `causal_asof` | 다른 주기 관측 정렬 | 같은 설비/출처/시계/구간의 배치·최대 나이 s | 현재 이하 최근 관측만 연결; 미래 관측 금지 |
| `moist_air_exchange` | 습공기 열·수분 수지 | 건공기 kg/s, 입출구 K, 습도비 1 | 열량 W·수분 kg/s·유효성 |
| `horizontal_cylinder_liquid_volume` | 수평 원통 충전 부피 | 수위·반지름·길이 m; 평평한 끝면 | 액체 부피 m3 |
| `SaturatedBoilerInventory` | 선언된 형상·상태의 총재고 | 형상 m/m3, 절대압 Pa, 수위 m, 외부 기포율 1; CoolProp | 물+증기 kg. 기포율/swell 관측기 아님 |
| `PiecewiseVaporizer` | 예열·비등·과열 정상 예측 | 질량 kg/s·상대 엔탈피 J/kg·열원 K; Tsat·잠열·cp·UA·기준 ID | 출구 K·엔탈피 J/kg·열량 W·모델 증기율. 고정 압력/물성/열원 |
| `evaporator_conductance_proxy` | 증발기 근사 전열 지표 | 응축 열량·전력 W, 증발온도·열원 입구 K | `(Qcond-W)/(Tsource,in-Tevap)` W/K. 측정 UA·추정 유량 아님 |

## 설치와 실행

```bash
python -m pip install monitoring-diagnostics-toolkit
equipment-diagnose list --details
# 저장소에서 개발/검증
python -m pip install -e ".[dev]"
# 필요한 경우만 선택
python -m pip install -e ".[learning,physics,public-data]"
```

배포명은 변경했지만 기존 import·CLI·JSON의 `equipment-diagnostics.*` 식별자는 호환성을 위해 유지합니다.
공개 원자료와 기존 사용자 프로젝트는 기본 설치에 포함되지 않습니다.

### 최소 Python 예제: 기화기 저온 감시

```python
import numpy as np
from equipment_diagnostics import SensorBatch, VaporizerDiagnostic

batch = SensorBatch(
    time_s=np.arange(5.0),
    values=np.column_stack((np.full(5, 270.0), np.full(5, 0.1))),
    channels=("gas_out_k", "flow"), units=("K", "kg/s"),
    clock_id="logger_elapsed_s", asset_id="vaporizer_01", origin="synthetic",
)
monitor = VaporizerDiagnostic(
    {"outlet_temperature": "gas_out_k", "mass_flow": "flow"},
    shortfall_limit_k=5.0, minimum_outlet_k=280.0,
    prediction_mode="minimum_only", persistence_s=2.0,
)
result = monitor.score(batch)
print(list(result.states))
print(result.to_dict()["summary"])
```

### CSV/JSON 전체 실행: 원자료 없이 합성 데모

소스 저장소에서 실행합니다. 데모는 10개 모듈 연결 예시이며 물리적으로 결합한 공장이나 11종의 실제 검증이 아닙니다.

```bash
python examples/generate_demo.py --output outputs/demo
equipment-diagnose fit --config outputs/demo/config.json --data outputs/demo/normal.csv --output outputs/demo/reference.json
equipment-diagnose run --config outputs/demo/config.json --data outputs/demo/operation.csv --reference outputs/demo/reference.json --output outputs/demo/report.json
```

`fit` 입력은 호출자가 확인한 정상 학습 자료여야 합니다. `calibrate`가 있는 Python API에는 별도 정상 보정 배치를 사용합니다.
CLI가 정상 여부를 자동 확인하거나 고장 자료를 자동 제외하지 않습니다. [설정·저장·스트리밍 설명](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/USER_GUIDE.md)을 참고하세요.

## 공통 입출력 계약

| SensorBatch 입력 | 의미 |
| --- | --- |
| `time_s[n]` | 유한한 초, 엄격히 증가, 같은 시계 |
| `values[n,d]`, `channels[d]`, `units[d]` | 계측값·고유 열 이름·명시적 단위 |
| `clock_id`, `asset_id`, `origin` | 시계·설비·출처 식별; 실제와 합성 구분 |
| `valid[n,d]` | 계측 유효성; NaN은 정상으로 처리하지 않음 |
| `episodes[n]`, `modes[n]` | 시험 구간·운전모드, 경계에서 창/지속 경보 초기화 |
| `metadata` | 교정·엔탈피 기준·변환 출처 등 추가 계약 |

단위 문자열을 정확히 맞춰야 합니다: `K`, `Pa`, `kg/s`, `m3/s`, `W`, `1/s`, `1` 등.
섭씨→K, kPa→Pa, rpm→1/s 변환은 명시적으로 수행하세요. 절대압과 차압을 혼동하지 마세요.

| DiagnosticResult 출력 | 의미 |
| --- | --- |
| `scores[n]` | 기본 한계 1에 대한 점수, 확률 아님. `score_semantics` 확인 |
| `valid[n]`, `states[n]` | 판정 유효성 및 `NORMAL`, `PENDING`, `ALARM`, `UNKNOWN` |
| `alarms[n]` | 경과시간 지속 등을 반영한 경보. 해제 지연은 낮아진 점수에서도 경보 유지 가능 |
| `reasons[n]` | 결측·물리 범위·창 준비·학습 영역 밖 등의 판단 이유 |
| `metrics` | 모델별 물리량·잔차 배열. 정확한 키는 모델 가이드·실행 결과 확인 |
| `metadata` | 시계·설비·출처·기준·설정 서명·점수 의미; `root_cause_confirmed=False` |

`UNKNOWN`은 정상 음성 판정이 아닙니다. `PENDING`은 유효하지만 지속 시간 미충족입니다.
정확도와 함께 판단률을 보고하고, 시계·설비·출처가 다른 자료를 식별자만 바꿔 연결하지 마세요.

## 현재 검증 수준

아래 수치는 기록된 연구 결과입니다. 공개 배포 자체가 새 독립 고장 검증은 아닙니다.
[최신 상세 비교](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/TWO_TARGET_IMPROVEMENT.md)와 [개발 연표](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/DEVELOPMENT_HISTORY.md)에 분할·모수·실패 후보가 있습니다.

| 모듈 | 실제 설비·실험 증거 | 계산·시뮬레이션 / 남은 문제 |
| --- | --- | --- |
| 밸브 | 공장 새 배경 34 설비·일, 경보 362→2구간, 표본 오경보율 0.000170%; 기존 고장 6/6 재검출·지연 14~18초 | 새 독립 고장·다른 공장 필요; 배경은 정비로 정상 인증한 자료 아님 |
| 엔진 필터 | 실험 엔진 1대 재사용: 정확도 94.7758%, 검출률 90.0889%, 오경보율 0.0294%, 판단률 100%, 최대 지연 2314초 | 빠른 후보는 오경보 증가로 미채택; 다른 엔진·독립 정상 변동 필요 |
| 히트펌프 | 재사용 새 경로: 정확도 99.7229%, 검출률 99.6973%, 정상 490개 오경보 0, 대상 판단률 100% / 원자료 90.16%; 약한 EF10.1 98.16%, 지연 30초 | 응축온도 0.3K 차이 의존. 정상에 합성 ±0.3K 편차 주입 시 경보 99.28%. **유량 고장 특이성 미검증** |
| HSE 필터 위험 | 원 Test 검출률 68.90%·오경보 2.14%; 후반 재사용 검출률 100%·오경보 21.58% | 정답은 30초 내 서비스 한계 위험; 범용 막힘·수명 보증 아님 |
| 열교환기 / 일반 차압 | 실제 오염·막힘 정답 검증 없음 | 유량 보정·경계 시험 완료. 시뮬레이션 성능을 실제 정확도로 사용하지 않음 |
| 젖은 코일 | 검출률 5.88%, 유효 정상 75개 오경보 0, 판단률 54.96% | 자동 오염 진단 미채택; 착상 조건 혼재 |
| 탱크 | 실제 수위 교정 재현, 누설 정답·유량 교정 부족 | 오차 한계로 오경보 감소하지만 작은 누설 검출력 감소 |
| RO | 자료 확보, 압력 순서 검사 실패·고장 정답 없음 | 보정식 확인. 센서를 임의 교환/편차 보정해 통과시키지 않음 |
| 기화기 | 실제 고장 검증 없음 | 저온 한계·정상 예측 계산 확인; 온도만으로 2상 증기율 확정 불가 |
| 냉동기 | 단일 RP-1043 실험 0단계 검출률 34.56%·오경보 0.28% | 보조 감시; 추가 단계 높은 오경보로 미채택 |
| 증류탑 / 스팀트랩 / 보일러 | 적용 가능한 독립 고장 정답 미확보 | 부하 경험식·트랩 규칙·선언된 총재고 계산 검증. 현장 고장 진단 완료 아님 |

정확도=(TP+TN)/유효 정답 표본, 검출률=TP/(TP+FN), 오경보율=FP/(FP+TN), 판단률=유효 판정/선언 대상입니다.
시동 제외 후 판단률과 원자료 대비 판단률은 구별합니다. 정상 표본 없는 고장 부분집합의 오경보율은 계산하지 않습니다.
학습·보정 표본을 분리해도 평가 결과를 보고 설계를 고쳤다면 **재사용 개발 평가**입니다. 검출 지연은 각 기록의 시작점 정의를 확인하세요.

## 검증·연동·라이선스

```bash
python -m pytest
python -m pytest -o addopts="" -m "not integration"
python scripts/verify_physics.py
python scripts/verify_stages.py
```

두 번째 명령은 선택 물리 의존성이 필요합니다. 외부 `integration`은 고정 리비전의 소스 체크아웃이 필요합니다.
실제 자료 재현은 [REPRODUCIBILITY](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/REPRODUCIBILITY.md)를 따르세요. 과거 해시 감사는 당시 소스 스냅샷으로 수행합니다.

`equipment_diagnostics.adapters`는 process-monitoring-toolkit, h2physics, pipeline-safety-toolkit의 명시적 객체 계약과 연결합니다.
[고정 리비전](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/UPSTREAM_REVISIONS.json), `examples/project_bridge.py`에 범위가 있습니다. 객체/직렬화 확인은 네이티브 솔버·공장 검증과 다릅니다.
rotorvibe는 조사만 했으며 여기서 어댑터 시험을 주장하지 않습니다.

원본 코드와 자체 문서는 MIT입니다. 외부 자료·논문·물성 라이브러리 권리는 유지하며 원자료는 배포하지 않습니다.
모델 이름·식·인용·라이선스 고지는 유지합니다. [출처·권리 안내](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/THIRD_PARTY_NOTICES.md), [인용 메타데이터](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/CITATION.cff)를 참고하세요.
후속 작업은 [RESEARCH_HANDOFF](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/RESEARCH_HANDOFF.md)의 실패 후보·필요 데이터·다음 우선순위부터 확인하세요.
