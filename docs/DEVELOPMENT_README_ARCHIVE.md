# Equipment Diagnostics

v0.16.0: 엔진 정상 조건 보완→EF10.1 원시 판정→경보 유지 정책을 분리해 검증했습니다.
재사용 실측 EF10.1의 추가 지표 판정률은49.08→98.16%, 관측 지연510→30초입니다.
응축온도 편차에 의존해 날짜/계측 편차와 유량 고장 원인의 분리는 남았습니다.
필터 후보와 경보 해제 지연은 오경보 문제로 미채택했습니다.
[정확도·검출률·오경보율·판단률·지연 및 원인 특이성](TWO_TARGET_IMPROVEMENT.md)을 확인하세요.

v0.15.0: 외부 문헌을 근거로 signed CUSUM·정상 블록 보정·AR1 예측 오차 후보와
증발기 열전달 근사 지표를 구현했습니다. 히트펌프 재사용 검출률97.75→98.18%,
EF96.17→96.47%이며 약한 EF10.1은49.08%로 그대로입니다. 필터 후보는 오경보가 늘어 미채택했습니다.
시작 전 활성 경보와 새 경보, 정상 관측 시간당 경보 빈도를 구분합니다.
[문헌→구현 대응·모든 실패 후보·채택 범위](LITERATURE_IMPROVEMENT.md)를 확인하세요.

v0.14.0: 7~13순위 검토·구현·검증을 이어 진행했습니다. 새 실제 엔진 필터 자료에
부하·회전수 보정을 적용했고, 탱크 교정·시각 정렬, 젖은 코일 공기측 계산,
기화기 정상 예측기와 명시적 형상·기포율을 받는 보일러 재고 계산을 추가했습니다.
냉동기 후보는 미채택했으며, 스팀트랩·증류탑의 실제 고장 검증은 자료 적합성 문제로 남았습니다.
[7~13번 결과·전체 사용 수준·실측/시뮬레이션 구분](COMPLETION_7_13.md)을 확인하세요.

v0.13.0: 히트펌프 정상 잔차 상관관계 감시를 추가해 재사용 EF 검출률96.17%를
확인했습니다. 필터는 학습 내부 시험별 교차검증·부스팅·결합 후보를 구현했지만
검출·오경보 교환이 남아 기본값을 유지했습니다.
[5~6번 구현·선택·미채택 결과](STAGE56_IMPROVEMENT.md)를 확인하세요.

v0.12.0: 1~4순위 분석 후 히트펌프 EWMA/CUSUM 경로와 필터 학습 범위·예측 차이
출력을 추가했습니다. 재사용 평가에서 EF 검출률78.30→94.75%, 정상490표본 오경보0건.
필터 성능 후보 두 개는 미채택하고 기존 결정을 유지했습니다.
새 독립 R290195관측은 계산 일치만 확인했고, 새 RO36398행은 압력 품질 문제가 반복됐습니다.
[순차 분석·채택/미채택 결과·새 자료 검증 범위](DIAGNOSTIC_FOLLOWUP.md)를 확인하세요.

v0.11.0: 필터에 관측 분진 조건을 사용하는 위험 분류기, 히트펌프에 부하별 증발기
관련 감시를 추가했습니다. 재사용 Test에서 필터 검출률58.19→68.90%,
오경보율4.65→2.14%, 히트펌프 물 유량 감소 검출률55.10→78.30%입니다.
[후반 자료 비교·모든 개발 후보·추가 입력·새 데이터 미검증](FILTER_HEATPUMP_OPERATING_POINTS.md)을 확인하세요.

v0.10.0: 필터의 미래 교체 한계 지도학습 모형과 히트펌프 확장 잔차를 추가했습니다.
기존 평가 자료 재사용에서 필터 위험 오경보율 37.03→4.65%(검출률 82.45→58.19%),
히트펌프 증발기 물 유량 감소 검출률 6.71→55.10%입니다.
필터의 이전 미사용 후반 자료에서는 오경보율이 38.14%로 남았습니다.
[분리 방법·전후 비교·새 독립 자료 미검증 항목](FILTER_HEATPUMP_IMPROVEMENT.md)을 확인하세요.
새 필터 수명 모형은 정상 기준 학습 CLI 11종과 별도의 지도학습 Python API입니다.

2026-11-05 실제 데이터 추가 확보: 필터 열화·동적 RO·습식 코일·3탱크 누설·프로판 히트펌프
5종의 배포 원본 8파일과 읽기용 CSV 83개를 보관했습니다.
[센서·단위·고장 정답·호환성 점검](ACTUAL_DATA_ACQUISITION.md)을 확인하세요.
v0.9.0에서 필터 → RO → 히트펌프를 적용·검증했습니다.
[분할·성능 비교·고장 정답 없는 항목](ACQUIRED_MODULES_VALIDATION.md)을 확인하세요.
필터는 30초 내 교체 한계 위험 평가, 히트펌프는 실제 주입 고장 평가입니다.
RO는 압력 품질 문제와 고장 정답 부재로 진단 정확도를 평가하지 못했습니다.

밸브 지속 추종 감시: 기존 지연·오차 한계에 10초 지속 경보 프로파일을 적용하고,
새 실제 공장 자료 17일×2개 밸브에서 사전 감시 기준을 통과했습니다.
경보 발생 구간 362→2회, 기존 고장 사건 6/6 검출 유지(경보 지연 증가).
[실제 검증 범위·수치·실행 프로파일](VALVE_MONITOR_QUALIFICATION.md)을 확인하세요.
기존 고장 사건은 재생 검증이며 새 현장·새 독립 고장 검증과 구분합니다.

v0.8.0: 4~10순위 후속 검토를 진행해 열교환기 유량별 정상 열저항,
RO 보정 입력 계산, 기화기 독립 저온 한계, 스팀트랩 시동 제외,
증류탑 정상 부하 학습을 추가했습니다. 냉동기 오경보의 채널 기여도 분석했습니다.
[구현 범위·입력·시뮬레이션 검증·보류 조건](REMAINING_MODULES.md)을 확인하세요.
보일러 총재고 관측기와 기화기 전열 예측은 설비 정보가 필요해 보류했습니다.

v0.7.0: 빠른 개선 후보인 밸브 정상 1차 응답, 점성·관성 혼합 차압,
탱크 계측 오차 한계 전파를 선택 기능으로 추가했습니다.
[10개 모듈의 개선 우선순위·구현·검증·한계](QUICK_IMPROVEMENTS.md)를 확인하세요.
실제 공장 자료와 독립 물리식 시뮬레이션 결과를 구분하며, 기존 설정을 자동 대체하지 않습니다.

v0.6.0: 냉동기 오일·과냉·과열 잔차 → 채널별 EWMA → 응축기 지표를 순서대로
구현하고, 학습·보정·평가 분리를 유지해 네 단계를 비교했습니다.
추가 단계의 오경보가 커 현재 설정의 현장 채택은 보류합니다.
[단계별 구현·검증 결과](CHILLER_STAGES.md)와 `outputs/chiller_stages/report.html`에
각 단계 및 공통 표본의 정확도·검출률·오경보율·판단률을 정리했습니다.

온도·압력·유량 등 공정 신호로 설비별 물리 지표를 계산하는 Python 패키지입니다.
기존 `process-monitoring-toolkit`의 통계·머신러닝 엔진과 연결하는 설비 진단 계층으로
구현했습니다. Python 3.11 이상, 핵심 의존성은 NumPy입니다.

## 구현 범위

| 모듈 | 입력 역할과 SI 단위 | 계산·진단 내용 | 정상 기준 학습 |
|---|---|---|---|
| `mass_balance` | `inventory_mass` kg, `inflow/outflow/known_loss` kg/s | 창 구간 순유입 적분과 재고 변화의 차이. 양의 미설명 손실 | 불필요 |
| `boiler_mass_balance` | 검증된 물·증기 총재고 kg, 급수·증기·블로다운 kg/s | 동일한 동적 물질수지. 드럼 수위만으로 총재고를 임의 계산하지 않음 | 불필요 |
| `heat_exchanger` | 양측 입출구 K, 양측 kg/s, 사용자가 제공하는 cp J/(kg·K) | 열수지 점검, 대향류 LMTD, UA 감소 | 필요 |
| `hydraulic_resistance` | ΔP Pa, 체적유량 m3/s, 선택적 밀도 kg/m3 | 명시한 유량지수·밀도로 기준유량 ΔP 환산. 저항 증가 | 필요 |
| `vaporizer` | 출구 실측·예측 K, 질량유량 kg/s | 외부 정상 모델 대비 출구 온도 부족 및 저온 한계. 선택적 엔탈피로 전달열량 | 불필요: 외부 예측 필요 |
| `ro_membrane` | 투과수 m3/s, 순구동압 Pa, 온도 보정계수 1, 막면적 m2 | 기준온도로 정규화한 투수성 감소 | 필요 |
| `valve_tracking` | 밸브 명령·실측 위치 0–1 | 지정 응답지연을 반영한 추종 오차 | 불필요 |
| `column_hydraulics` | 탑 ΔP Pa, 증기·액체 kg/s, 선언된 유량 보정지수 | 부하 보정 차압 증가. 플러딩·오염 원인 분리는 하지 않음 | 필요 |
| `steam_trap` | 증기 기준·트랩 표면 K, 정규화 음향 1, 증기 공급 여부 1 | 저온·저음향 또는 고온·고음향의 지속 패턴 | 불필요: 현장 임계값 필요 |
| `chiller_performance` | 냉수 입출구·냉각수 출구·냉매 포화 K, 냉수 kg/s, 전력 W | COP 감소, 증발기·응축기 접근온도 증가 | 필요 |
| `heat_pump_performance` | 응축 열량·압축기 전력·명목 부하 W, 냉매 온도 K, 냉매 kg/s, 압축기 1/s | 난방 COP·과냉·토출 과열·회전당 냉매량의 부하별 정상 잔차 | 필요: 별도 정상 보정도 필요 |

공통 기능은 유효성 마스크, 관측 운전모드, 에피소드·시간 단절 구분, 경과시간 기반
경보 지속조건, SI 단위 검사, JSON 직렬화, 정상 기준의 설정·설비·데이터 출처 확인입니다.
결측치와 계산 적용범위 밖의 값은 `UNKNOWN`으로 남깁니다.

이 구현은 조사 논문의 물리 원리를 참고한 **독립적인 공학적 스크리닝 구현**입니다.
논문의 EKF·LSTM·PCA 모델이나 논문에 보고된 성능을 재현했다고 주장하지 않습니다.
원인 확정, 현장 검증, 안전계장 동작, 누설 위치 추정은 구현 범위 밖입니다.
현재 진단 종류는 11종입니다. 증류탑·스팀트랩·냉동기에도 기초 스크리닝을 제공하지만,
조사 논문의 플러딩 예측 Random Forest, 음향 분류기, 냉동기 다중고장 CNN은 미구현입니다.

## 빠른 실행

현재 작업 폴더에는 `.venv` 실행환경을 준비했습니다. PowerShell에서:

```powershell
.\.venv\Scripts\python.exe -m equipment_diagnostics list
.\.venv\Scripts\python.exe -m equipment_diagnostics list --details
.\.venv\Scripts\python.exe examples/generate_demo.py --output outputs/python_demo
.\.venv\Scripts\python.exe -m equipment_diagnostics fit --config outputs/python_demo/config.json --data outputs/python_demo/normal.csv --output outputs/python_demo/reference.json
.\.venv\Scripts\python.exe -m equipment_diagnostics run --config outputs/python_demo/config.json --data outputs/python_demo/operation.csv --reference outputs/python_demo/reference.json --output outputs/python_demo/report.json
```

다른 환경에서는 먼저 다음처럼 설치합니다.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
# 위 명령은 활성화된 가상환경의 python으로 실행합니다.
```

데모는 정상 구간과 별도 운전 구간을 생성합니다. `t=900 s` 이후에 모듈별 이상을
주입하고 `t=840 s`에는 차압을 결측 처리합니다. 여러 설비 신호를 모은 합성 예제이며
물리적으로 결합된 플랜트 시뮬레이션이나 실제 설비 데이터가 아닙니다.
`truth.json`은 평가용으로만 사용하고 측정 행렬에는 넣지 않습니다.

## Python API

```python
import numpy as np
from equipment_diagnostics import SensorBatch, MassBalanceDiagnostic

t = np.arange(0, 121, 10, dtype=float)
batch = SensorBatch(
    time_s=t,
    values=np.column_stack((100 - 0.2*t, np.zeros_like(t), np.zeros_like(t))),
    channels=("tank_mass", "inlet", "outlet"),
    units=("kg", "kg/s", "kg/s"),
    clock_id="experiment_elapsed_s", asset_id="tank_01", origin="synthetic",
)
diagnostic = MassBalanceDiagnostic(
    {"inventory_mass": "tank_mass", "inflow": "inlet", "outflow": "outlet"},
    loss_limit_kg_s=0.05, window_s=30, persistence_s=20, max_gap_s=15,
)
result = diagnostic.score(batch)
print(result.summary())
```

경보 점수는 대체로 `이상 방향 편차 / 사용자가 정한 한계`이며, 1을 **초과**하고
`persistence_s` 이상 이어지면 `ALARM`입니다. 확률·신뢰도 백분율이 아닙니다.
마지막 표본 상태와 전체 분석 구간에 경보가 있었는지는 `latest_state`와 `status`로
분리합니다. `no_alarm`은 정상·건전성이 증명되었다는 뜻이 아닙니다.

`score()`는 배치마다 상태를 새로 계산합니다. 분할 데이터는 `StreamingDiagnostic`으로
처리하면 물리적 계산 창·응답지연·경보 지속조건에 필요한 과거를 보관해 재평가합니다.
이력 한도를 넘으면 임의로 이력을 버리지 않고 오류를 반환합니다. 미래 표본은 현재
표본의 판단에 사용하지 않습니다.

```python
from equipment_diagnostics import StreamingDiagnostic

# 정상 기준이 필요한 model은 먼저 fit 또는 set_reference를 완료합니다.
stream = StreamingDiagnostic(model, max_history_samples=10000)
first = stream.push(first_chunk)
second = stream.push(second_chunk)
# 시계·설비·컬럼·단위·metadata는 같아야 하고, 표본 시간이 겹치면 안 됩니다.
```

## 기존 저장소 연동

| 저장소 | 제공 연결 | 실제 확인 범위 |
|---|---|---|
| [process-monitoring-toolkit](https://github.com/lyullee/process-monitoring-toolkit) | `SignalBatch` 입출력, `DetectionResult` 출력, 설비 점수를 `Monitor` 입력으로 전달 | 실제 객체 왕복·마스크·모드·에피소드 및 `Monitor` 실행 테스트 |
| [h2physics](https://github.com/lyullee/h2physics) | `TimeSeries`, `ObservationTable` 입력 | 실제 공개 객체 테스트. `ObservationTable`은 시간이 없으므로 별도 행 정렬 시간 필수 |
| [pipeline-safety-toolkit](https://github.com/lyullee/pipeline-safety-toolkit) | `Calculation`에 표본별 진단 근거 전달 | 실제 계약 객체 생성, 설비·시계·출처 일치 확인 |
| [rotorvibe](https://github.com/lyullee/rotorvibe) | 결과 구조·시계 규칙 검토 | 직접 어댑터·진동 특징 융합은 미구현 |

```python
from equipment_diagnostics.adapters import (
    from_process_monitoring, to_detection_result, residual_signal_batch,
    from_h2physics_timeseries, from_h2physics_observations,
)

# 기존 process_monitoring.SignalBatch를 사용할 때
batch = from_process_monitoring(existing_batch, clock_id="plant_elapsed_s", asset_id="filter_01")
# model은 같은 channels/units 설정으로 만든 진단기입니다.
result = model.score(batch)
existing_result = to_detection_result(result)
score_signals = residual_signal_batch(result)
```

선택 모듈은 지연 import합니다. 핵심 진단만 쓰면 외부 저장소는 설치할 필요가 없습니다.
외부 패키지는 각 저장소의 설치 지침대로 설치하고, 동일 환경의 의존성 호환성을
확인해야 합니다. `.upstream`은 이번 확인에 사용한 읽기용 체크아웃이며 배포에 포함하지
않습니다. 외부 저장소로 커밋·푸시는 하지 않았습니다.

## 입력·보정·적용 한계

- CSV는 숫자형 `time_s`와 선택한 센서 컬럼을 사용합니다. 시계·설비·출처와 각 컬럼의
  단위는 JSON 설정에서 명시합니다. 자동 단위 추론·압력 기준 추정은 하지 않습니다.
- `NaN`, 무한대, 빈값·파싱 불가 측정값은 무효입니다. 비단조·중복 시간, 단위 불일치,
  잘못된 설정은 오류로 중단합니다. 단위가 다른 값은 외부 어댑터에서 먼저 변환합니다.
- 물질수지는 모든 관련 유입·유출을 포함해야 합니다. `known_loss` 생략은 그 항을 0으로
  놓는 명시적 모델 가정입니다. 미계측 벤트·블로다운·계측 드리프트도 손실처럼 나타납니다.
- 열교환기는 일정 cp를 쓸 수 있는 **단상·준정상 대향류**에 한정합니다. 상변화 기화기에
  이 LMTD/UA 모듈을 그대로 적용하지 않습니다. 입구 온도 변화·열수지 불일치·음의
  접근온도·학습 유량범위 이탈은 판단을 보류합니다. 온도 변화 게이트만으로 모든
  정상상태 조건이 검증되는 것은 아닙니다.
- 차압 보정 유량지수는 장치별로 확인해야 합니다. 기본 다상 배관 모델·압축성 유동 모델은
  없으며, 점도 변화가 큰 유체에는 현재 모델만으로 오염을 확정할 수 없습니다.
  `density_exponent`도 지정할 수 있습니다. 일정 점도 층류는 유량지수 1·밀도지수 0,
  일정 마찰계수 관성 극한은 각각 2·1입니다. 기존 정상 기준은 다시 학습해야 합니다.
- 기화기의 `predicted_temperature`는 정상 운전 모델의 예측이어야 합니다. 고장 정답이나
  실측 출구 온도를 다시 넣으면 유효한 진단이 아닙니다. 엔탈피 차로 열량을 계산할 때는
  공통 `enthalpy_basis_id`를 설정해야 하며 잠열을 cp·ΔT로 대체하지 않습니다.
- RO의 `net_driving_pressure`는 삼투압 등을 반영해 외부에서 계산한 순구동압입니다.
  `temperature_correction`은 **현재 유량에 곱해 기준온도로 바꾸는 계수**입니다.
  원수 압력이나 역방향 정의의 보정계수를 그대로 넣지 않습니다.
- 밸브 모듈은 실측 위치와 명령의 추종 오차를 검출합니다. 정지마찰, 외란, 포지셔너 이상을
  분리하는 논문의 미지입력 추정 알고리즘을 구현한 것은 아닙니다.
  현재 보정은 순수 시간 지연이며 1차 관성·속도 제한 모델은 없습니다. 정상 관성 응답도
  오차로 잡힐 수 있으므로 준정상 구간 선정이나 별도 동특성 모델이 필요합니다.
- 증류탑은 증기·액체 부하를 보정한 차압을 비교합니다. 유체 물성·트레이 구조 변화는
  직접 모델링하지 않으며 플러딩·퇴적·내부 손상을 분리하지 않습니다.
- 스팀트랩은 현장 센서에서 정규화한 음향 크기와 설치 위치에 맞는 온도 기준을 사용합니다.
  임계값은 현장·트랩 형식에 맞게 정해야 합니다. 정상 배출 주기를 경보로 오인하지 않도록
  지속시간을 설정해야 하며 증기 공급 중단은 UNKNOWN으로 처리합니다.
  냉간 시동은 정상 설비에서도 저온·저음향 패턴을 만들 수 있습니다. 관측 모드와
  `allowed_modes`로 시동 구간을 제외해야 합니다.
- 냉동기는 전력 경계에 맞춘 COP와 접근온도를 계산합니다. 증발·응축 온도는 해당 냉매의
  검증된 포화 상태에서 계산해 제공해야 합니다. COP 저하만으로 냉매 부족을 확정하지
  않으며 기초 구현은 안정 운전 구간에 사용해야 합니다.
  `isothermal_carnot_cop`는 등온 증발·응축의 참고값입니다. 이 가정이 확인된 경우
  `enforce_isothermal_carnot_bound=True`로 상한 위반을 UNKNOWN 처리할 수 있습니다.
  온도 글라이드·과냉각·과도 축열이 있는 사이클에는 일반 상한으로 강제하지 않습니다.
- 정상 기준은 사용자가 검토한 정상 구간으로만 `fit`합니다. 이 단계는 오경보 확률을
  보정하지 않습니다. 한계값·지속시간은 독립 정상·고장 데이터로 별도 검증해야 합니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 선택: 읽기용 외부 체크아웃과 해당 의존성이 있는 경우
.\.venv\Scripts\python.exe scripts/verify_integrations.py
```

핵심 검증은 적분·축적량·단위·결측·에피소드·경과시간·인과성 및 CLI 합성 실험입니다.
외부 객체 연결 검증 결과와 정확한 커밋은 `outputs/python_verification/integration_results.json`에
기록합니다. 테스트 통과와 실제 설비 적용 정확도는 별개입니다.

## 0.5.0 냉동기 부하·운전조건 모델

`ChillerPerformanceDiagnostic(..., reference_mode="conditioned")`는 냉각부하·냉수
출구온도·냉각수 입구온도로 정상 전력·접근온도·유량을 예측합니다. `cooling_in`(K)이
추가로 필요하며, `fit(normal_train).calibrate(separate_normal_calibration)` 순서로
정상 기준과 보정 한계를 저장합니다. 기존 단일 기준 모드는 기본값으로 보존했습니다.

학습 normal.xls, 보정 normal1.xls, 평가 정상 12파일·고장 23파일을 그대로 유지했습니다.
정상 학습 파일 안에서만 후보를 선택하고 정상 보정 파일로만 경보 한계를 정했습니다.
정상 보정 설정끼리 비교한 정확도는 39.40→56.79%, 검출률은 3.61→34.56%,
오경보율은 0.6583→0.2751%, 평가 대상 중 판단률은 90.99→99.66%입니다.
원본 전체 판단률은 62.62→68.58%이며, UNKNOWN은 정상 정답으로 집계하지 않았습니다.

```powershell
.\.venv\Scripts\python.exe scripts/validate_chiller_upgrade.py
.\.venv\Scripts\python.exe scripts/audit_chiller_upgrade.py
```

[docs/CHILLER_UPGRADE.md](CHILLER_UPGRADE.md)에 API·모델 선택·고장별 한계가 있고,
`outputs/chiller_upgrade/report.html`에 고정/보정 설정과 공통 표본 비교가 있습니다.
과다 오일·약한 오염 검출은 여전히 부족하며, 같은 평가 파일을 재사용한 개발 비교입니다.

## 0.4.0 공개 실측 데이터 평가

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,physics,public-data]"
.\.venv\Scripts\python.exe scripts/validate_public_data.py --download
.\.venv\Scripts\python.exe scripts/audit_public_results.py
```

실제 공장 DAMADICS 밸브와 ASHRAE RP-1043 냉동기 실험 자료 공개 재배포본을 현재 진단기에
입력했습니다. 날짜·운전 파일로 학습/정상 보정/평가를 분리했고, 시험 고장 라벨로 임계값을
맞추지 않았습니다. UNKNOWN은 정상 정답으로 집계하지 않으며 판단률을 별도 공개합니다.

정상 자료 보정 후 밸브 f16 고장 표본 검출률은 91.16%, 배경 정상 표본 오경보율은 0.0221%이고,
알려진 공급압력 저하 6건을 7–11 s 안에 검출했습니다. 한 공장·2개 밸브의 결과입니다.
냉동기는 고정 설정의 검출률 32.67%·오경보율 23.06%이며, 보정 후 오경보율 0.66%로
줄었지만 검출률도 3.61%로 낮아졌습니다. 현재 규칙의 성능 한계로 남겼습니다.

나머지 8종은 자료 비공개, 필수 센서·독립 고장 정답 부족, 모델 범위 불일치로 미검증입니다.
결과와 분모·데이터 출처·한계는 [docs/PUBLIC_DATA_VALIDATION.md](PUBLIC_DATA_VALIDATION.md),
파일별 실제 결과는 `outputs/public_validation/report.html`과 `results.json`에 있습니다.
공개 실측 자료는 패키지에 포함하지 않습니다.

## 0.3.1 여섯 단계 검증

```powershell
.\.venv\Scripts\python.exe scripts/verify_stages.py
```

입력 검사 41개, 손계산 비교 10개, 수치 경계 17개, 모듈 연결 17개,
기존 시험 재실행 78개, 별도 프로세스 전체 실행 4개로 나누어 총 167개를 실행했습니다.
82개 신규 시험과 기존 85개이며 같은 시험을 합계에서 중복 집계하지 않았습니다.
외부 실제 객체 연결에는 `.upstream` 체크아웃·의존성이, 기존 물리 시험에는 `[physics]`
선택 의존성이 필요합니다. 생략된 시험은 통과로 집계하지 않습니다.

공백 단위, 양수 계산값이 0으로 소실되는 언더플로, 시계 정밀도보다 짧은 재고 창에
대한 6개 실패 사례를 재현하고 보완했습니다. 측정 유량/차압의 실제 0과 연산 소실의
0을 구별합니다. 수치 정밀도 부족은 UNKNOWN이며 경보의 근거로 사용하지 않습니다.
이 조치는 임의 크기의 수에서 계산 정확도를 보장하는 고정밀 연산 구현은 아닙니다.

비교표·시험별 근거는 `outputs/staged_verification/report.html`, 원시 결과·환경·소스 해시는
`outputs/staged_verification/results.json`, 방법과 한계는
[docs/SIX_STAGE_VERIFICATION.md](SIX_STAGE_VERIFICATION.md)에 기록했습니다.

## 0.3.0 물리·수치 검증

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[physics]"
.\.venv\Scripts\python.exe scripts/verify_physics.py
```

10종에 대한 독립 기준식·외부 물성 비교와 적용 한계 반례를 40개 테스트로 분리했습니다.
결과는 `outputs/physics_verification/report.html`, 수치 오차·환경·소스 해시는
`outputs/physics_verification/results.json`에 기록합니다. 범위와 남은 물리 검증은
[docs/PHYSICS_VALIDATION.md](PHYSICS_VALIDATION.md)에 정리했습니다.
물리 검증용 ht·fluids·CoolProp은 선택 의존성이며 핵심 모듈에 추가하지 않았습니다.

질량수지의 창 경계 보간, 유동 영역별 밀도지수, RO 유량 0 조건을 보완하고
냉동기의 선택적 등온 Carnot 상한 검사를 추가했습니다. 0.2.0 정상 기준 중
차압·냉동기 기준은 설정 서명이 변경되므로 재학습해야 합니다.

## 0.2.0 점검·보완

- 실패한 재학습 뒤 이전 정상 기준을 사용하지 못하도록 수정했습니다.
- 기준 학습 후 설정 변경, 외부 신호의 설비·시계 식별자 덮어쓰기를 차단했습니다.
- 점수 외 부가 계산값의 비정상 수치도 무효 처리하고 입력 metadata를 결과에 보존합니다.
- 정수·문자열 운전 식별자, 측정값의 실수 자료형, 센서 역할 중복을 검사합니다.
- 증류탑·스팀트랩·냉동기 3종, 분할 시계열 처리, 설명 포함 목록 API를 추가했습니다.

구현 전체 목록은 `list_diagnostics()` 또는 `equipment-diagnose list --details`,
빠진 연구 항목의 상태는 [docs/CAPABILITIES.md](CAPABILITIES.md)에서 확인합니다.

자세한 설계·참고 근거는 [docs/IMPLEMENTATION.md](IMPLEMENTATION.md),
외부 연결 실행 예제는 [examples/project_bridge.py](examples/project_bridge.py)를 참고하세요.
