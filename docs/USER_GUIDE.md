# 사용 설명서

## 1. 모형을 선택하기 전에

README의 단위 모듈 표에서 센서가 실제로 있는 모형을 고른다. 같은 압력이라도
절대압·게이지압·차압은 다른 물리량이다. 엔진 동력과 회전수로 공기 유량을 측정한
것처럼 취급하지 않는다. 실측·모델 예측·가정값은 origin/metadata에 구분한다.
상대습도(%)는 습도비(kg/kg)가 아니다. 유량이 kg/s인지 m3/s인지 확인한다.

모든 생성자·필수/선택 설정·메서드 인자는 [API_REFERENCE](API_REFERENCE.md)에 있다.
파이썬에서도 `help(HeatExchangerDiagnostic)` 또는 `inspect.signature(...)`로 확인할 수 있다.
CLI `list --details`는 11종의 목적·정상 기준 필요 여부·참고 근거를 출력한다.

## 2. 자료 계약과 CSV

SensorBatch의 시간은 초이고 엄격히 증가해야 한다. 시간대가 있는 원시 시각을
경과시간으로 바꿨다면 원점·시간대·동기화 방법을 metadata에 남긴다. 서로 다른 로거의
시간이 비슷해 보인다는 이유로 같은 clock_id를 부여하지 않는다.

CLI CSV는 첫 행에 이름이 있고 각 계측 열의 단위는 JSON의 `units`로 선언한다.
빈 수치 셀은 유효하지 않은 계측이다. 임의의 0 채우기로 정상 판정을 만들지 않는다.
episode/mode 열은 설정한 경우만 읽는다. 계측 열에 정답 고장 코드·실험 이름을
운전 특징처럼 넣지 않는다. 학습·보정·평가 분리 목록은 별도 보존한다.

최소 설정 예시(외부 정상 기준이 필요 없는 기화기 저온 감시):

```json
{
  "schema": "equipment-diagnostics.config.v1",
  "clock_id": "logger_01_elapsed_s",
  "asset_id": "vaporizer_01",
  "origin": "synthetic",
  "time_column": "time_s",
  "units": {"out_k": "K", "flow_kg_s": "kg/s"},
  "diagnostics": [{
    "id": "outlet_low_temperature",
    "kind": "vaporizer",
    "channels": {"outlet_temperature": "out_k", "mass_flow": "flow_kg_s"},
    "parameters": {"prediction_mode": "minimum_only", "minimum_outlet_k": 280.0, "shortfall_limit_k": 5.0},
    "alarm": {"persistence_s": 2.0, "max_gap_s": 5.0}
  }]
}
```

```csv
time_s,out_k,flow_kg_s
0,270,0.1
1,270,0.1
2,270,0.1
3,270,0.1
```

```bash
equipment-diagnose run --config config.json --data observations.csv --output report.json
```

알 수 없는 설정 키·중복 JSON 키·잘못된 단위는 수정해야 한다.
잘못된 설정·파일 오류는 CLI 종료 코드 2로 보고된다. 입력 파일과 같은 경로로 결과를
덮어쓰는 작업은 거부된다. JSON 저장은 임시 파일과 원자적 교체를 사용한다.

## 3. 정상 기준 학습·보정·평가

1. 시험/설비/날짜 단위로 분리 목록을 먼저 고정한다. 시간 경계에는 모델 창과
   센서 시간 오차에 맞는 purge 간격을 둔다. 랜덤 행 분할은 인접 표본 누설 위험이 있다.
2. 정상이라고 확인한 학습 자료로 `model.fit(normal_train)`을 호출한다.
   지도학습 Filter API는 `remaining_life_s` 정답 배열을 별도 인자로 받는다.
3. `calibrate`를 제공하는 모형은 별도 정상 보정 자료로 한계를 결정한다.
   정상 보정 지문은 학습 지문과 달라야 한다. 이것만으로 임의의 행 중복까지
   자동 보증하지는 않으므로 분리 목록·원시 센서 중복도 확인한다.
4. 설정과 `model.reference`를 JSON으로 저장하고 다시 읽어 `set_reference`로 복원한다.
   모형 종류·센서 매핑·설정·설비·출처 등의 계약이 맞아야 한다.
5. 평가에서 기준을 갱신하지 않는다. 평가를 본 뒤 설계를 고쳤다면 결과는 재사용
   평가로 표시하고 새 독립 시험을 별도로 확보한다.

```python
import json
from equipment_diagnostics import HydraulicResistanceDiagnostic

model = HydraulicResistanceDiagnostic(
    {"pressure_drop": "dp_pa", "volume_flow": "flow_m3_s"},
    reference_flow_m3_s=0.01, flow_exponent=2.0,
)
# normal_train: 호출자가 정상으로 확인한 SensorBatch
model.fit(normal_train)
text = json.dumps(model.reference, allow_nan=False, sort_keys=True)
restored = HydraulicResistanceDiagnostic(
    {"pressure_drop": "dp_pa", "volume_flow": "flow_m3_s"},
    reference_flow_m3_s=0.01, flow_exponent=2.0,
)
restored.set_reference(json.loads(text))
result = restored.score(evaluation_batch)
```

위 조각은 사용자가 실제 배치를 제공하는 템플릿이다. 즉시 실행 가능한 예제는
README의 합성 데모이며, 실제 자료 재현은 [재현 절차](REPRODUCIBILITY.md)를 따른다.
CLI `fit`은 지원 진단의 기준을 JSON bundle로 저장하며 `run --reference`로 복원한다.
Python 추가 API의 개별 보정·결합 정책을 CLI가 자동 실행하지는 않는다.

## 4. 결과를 해석하기

물리 범위 위반·결측·시동/창 준비·학습 영역 밖은 UNKNOWN이 될 수 있다. reasons와
valid를 먼저 확인하고 scores를 읽는다. 점수 1 초과가 기본 경보 후보지만 경과시간
지속 정책을 통과해야 ALARM이다. PENDING은 유효한 음성 경보 상태이므로 원시
임계값 초과율과 지속 정책 후 검출률이 다를 수 있다.

`result.to_dict()`는 JSON 직렬화 가능한 사전과 summary를 만든다. 비유한 수치는
JSON null로 변환되므로 숫자만 읽지 말고 valid/state도 함께 저장한다. 정상 자료에
오경보 0건이 관측되었다고 실제 오경보 확률이 0이라고 결론 내리지 않는다.

설비별 계산량의 단위는 README/모델 가이드에서 확인한다. 조건부 모형의
observed/expected는 설정한 로그 변환 공간일 수 있다. 통계 거리는 확률이나
누설 kg/s가 아니다. 해제 지연 경보는 점수 하락 후에도 활성일 수 있다.

## 5. 청크·연동·오류 대응

```python
from equipment_diagnostics import StreamingDiagnostic

stream = StreamingDiagnostic(restored, max_history_samples=10000)
# 청크 시간은 서로 겹치지 않고 증가해야 한다.
r1 = stream.push(first_batch)
r2 = stream.push(second_batch)
```

설정·기준·metadata·시계·열·단위가 바뀌면 명시적으로 reset하고 새 구간을 시작한다.
전체 이력 모형을 상한까지 잘라 정확도를 바꾸지 않는다. 해당 모형은 상한 초과 시
실패하므로, 긴 운전에는 이력 예산과 에피소드 재시작을 설계해야 한다.
이 래퍼는 무제한 메모리의 영구 온라인 운전 보증이 아니다.

기존 프로젝트 연결은 `equipment_diagnostics.adapters`와
`examples/project_bridge.py`를 확인한다. 동일 origin/asset/clock 의미를 유지하고
모형 예측을 실측으로 바꾸지 않는다. `causal_asof`도 시계가 실제 정렬된 뒤 사용한다.

| 문제 | 점검할 항목 |
| --- | --- |
| expected K, received C | 열 값과 선언을 함께 변환했는지 |
| 기준 복원이 거부됨 | 종류·설정·센서 매핑·학습 계약 일치 여부 |
| 전부 UNKNOWN | 유효성·물리 범위·정상 학습 영역·시동/창 길이·모드 |
| 과도한 경보 | 단위·센서 편차·운전조건·정상 대표성·임계값·일시 과도 |
| 새 설비에서 낮은 검출 | 기존 장치의 기준 이전을 가정하지 말고 별도 정상·고장 검증 |
| RO 압력 순서 위반 | 센서 위치·절대/게이지 기준·로거 단위를 원자료에서 확인 |

## 6. 변경·배포

`CONTRIBUTING.md`의 여섯 시험 범주를 적용한다. 모델 식이나 기본값을 변경하면
기존 실제 평가 결과가 새 버전의 증거인 것처럼 표시하지 않는다. 실패 후보도 보존한다.
공개 릴리스에는 외부 원자료·PDF·외부 소스·개인 환경·자격증명을 넣지 않는다.
