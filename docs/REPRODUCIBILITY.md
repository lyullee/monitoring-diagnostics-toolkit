# 재검증·재현 절차

## 재현의 세 범위

| 범위 | 필요한 것 | 결과 해석 |
| --- | --- | --- |
| 공개 소프트웨어 시험 | 이 저장소·Python·선택 의존성 | 입력 계약·계산·경계·연결·회귀 동작 |
| 역사적 실측 연구 재현 | 당시 원자료·분리/보정 프로토콜·당시 소스 스냅샷·환경 | 기록한 장치/조건의 계산·평가 재현; 새 독립 시험 아님 |
| 새 독립 검증 | 모델 고정 후 확보한 새 정상·고장·계측/시각/조건/정답 | 일반화·오경보·원인 특이성에 대한 추가 증거 |

0.17 공개 설명 보강에서 과거 성능 숫자를 새 독립 결과로 바꾸지 않았다.
0.16 당시 소스는 `evidence/v016_evaluated_source_snapshot.zip`에 별도 보존한다.
기존 프로토콜의 SHA256은 당시 파일 바이트를 대상으로 하므로, 주석·버전까지 바뀐
현재 파일로 과거 감사가 통과해야 한다고 기대하지 않는다. 당시 폴더는 별도 복원한다.

## 새 환경: 외부 자료 없는 검증

```bash
python -m venv .venv
# 활성화 후 다음 명령 실행 (Windows: .venv\Scripts\Activate.ps1)
python -m pip install -e ".[dev]"
python -m pytest
python -m pip install -e ".[physics,learning,public-data]"
python -m pytest -o addopts="" -m "not integration" --junitxml=outputs/recheck/regression.xml
python scripts/verify_physics.py
python scripts/verify_stages.py
python examples/generate_demo.py --output outputs/recheck/demo
equipment-diagnose fit --config outputs/recheck/demo/config.json --data outputs/recheck/demo/normal.csv --output outputs/recheck/demo/reference.json
equipment-diagnose run --config outputs/recheck/demo/config.json --data outputs/recheck/demo/operation.csv --reference outputs/recheck/demo/reference.json --output outputs/recheck/demo/report.json
```

pytest 기본 설정은 integration/physics marker를 제외한다. 전체 비연동 시험은
`-o addopts="" -m "not integration"`를 사용한다. 선택 의존성이 없는 시험은 실패/skip
내역을 보고하고 무조건 전체 성공으로 합산하지 않는다. 기존 warning도 기록한다.

## 기존 프로젝트 연결 재현

`docs/UPSTREAM_REVISIONS.json`의 저장소를 `.upstream/<이름>`에 별도 체크아웃한다.
각 저장소는 `https://github.com/lyullee/<이름>`에서 확보하며 JSON의 정확한 커밋으로
checkout한다. 외부 소스는 읽기 전용으로 취급하고 각각의 라이선스/설치 설명을 따른다.
`EQUIPMENT_UPSTREAM_ROOT`로 별도 루트 지정도 가능하다. 테스트가 참조하는
외부 런타임 의존성은 `tests/test_integrations.py`에서 확인한다.

```bash
python scripts/verify_integrations.py
```

이 스크립트는 객체·직렬화 및 Monitor 연결을 확인한다. rotorvibe는 조사만 하므로
같은 '검증 완료' 수로 계산하지 않는다. 외부 네이티브 시뮬레이터·서비스 실운전이 아니다.

## 실측 분석: 순서와 결과 위치

아래는 역사적 실행 순서 지도다. **전체 실행을 새 디렉터리 복사본에서 수행한다.**
대부분 스크립트는 경로 상수를 사용하며 같은 outputs 위치를 덮어쓸 수 있다.
원자료·이전 기준·초기 실패 결과가 없으면 중간 단계부터의 단독 실행은 완전 재현이 아니다.
실측 재현에는 `.[learning,physics,public-data]` 외에도 당시 환경 버전 확인이 필요하다.

| 단계 | 생산 스크립트 / 그 다음 독립 감사 | 결과 디렉터리 |
| --- | --- | --- |
| 초기 실제 자료 | `validate_public_data.py` → `audit_public_results.py` | `outputs/public_validation` |
| 냉동기 조건 보정 | `validate_chiller_upgrade.py` → `audit_chiller_upgrade.py` | `outputs/chiller_upgrade` |
| 냉동기 누적 단계 | `validate_chiller_stages.py` → `audit_chiller_stages.py` | `outputs/chiller_stages` |
| 빠른 물리 개선 | `validate_quick_physics.py`, `validate_valve_dynamics.py` → `audit_quick_improvements.py` | `outputs/quick_improvements` |
| 나머지 모듈 | `validate_remaining_modules.py` → `audit_remaining_modules.py` | `outputs/remaining_modules` |
| 밸브 배경 검증 | `qualify_valve_monitor.py` → `audit_valve_qualification.py` | `outputs/qualification` |
| 추가 자료 적합성 | `acquire_actual_datasets.py`, `inspect_acquired_actual_data.py` → `audit_acquired_actual_data.py` | `outputs/actual_data_acquisition` |
| 필터·RO·HP 적용 | `validate_acquired_modules.py` → `audit_acquired_modules.py` | `outputs/acquired_modules_validation` |
| 필터·HP 보완 | `improve_filter_heatpump.py` → `audit_filter_heatpump_improvement.py` | `outputs/filter_heatpump_improvement` |
| 조건·운전점 | `refine_filter_heatpump.py` → `audit_filter_operating_points.py` | `outputs/filter_heatpump_operating_points` 및 refinement 변형 |
| 후속 누적 경로 | `analyze_diagnostic_gaps.py`, `improve_from_gap_analysis.py`, `analyze_followup_results.py` → `audit_diagnostic_followup.py` | `outputs/diagnostic_followup` 등 |
| 5~6 후보 | `improve_stage56.py`, `analyze_stage56_events.py` → `audit_stage56.py` | `outputs/stage56_*` |
| 7~13 실제/물리 | `acquire_completion_data.py`, `validate_independent_marine.py`, `validate_wet_coil.py`, `validate_tank_readiness.py`, `validate_chiller_refrigerant.py`, `validate_completion_physics.py` → `audit_completion.py` | `outputs/completion_7_13` |
| 문헌 보완 | `improve_from_literature.py` → `audit_literature_improvement.py` | `outputs/literature_improvement` |
| 두 항목 재검토 | `review_two_bottlenecks.py` | `outputs/two_bottleneck_review` |
| 최신 두 항목 | `improve_two_targets.py` → `assess_two_targets.py` → `audit_two_targets.py` → `render_two_targets.py` | `outputs/two_target_improvement` |

파일 이름은 실행 진입점이며 세부 결과 하위 경로·변형은 각 단계 문서와 스크립트의
`ROOT`, `OUT`, `BASE`, `RAW` 상수가 우선한다. 단일 명령으로 모든 역사적 후보를
자동 복원한다고 주장하지 않는다. 이전 실패 후보와 전 단계 frozen 기준이 일부
필요하다. 누락되면 당시 로컬 보존본에서 복원하거나 재현 불가능 범위를 표시한다.

## 최신 두 항목의 분리·감사

필터 기존 외부 분할 및 HP NF10/NF12 시간 분할을 유지했다. 추가 필터 정상 파일은
부모 시험 단위로 train/calibration을 분리했고 평가를 이동시키지 않았다.
정상 CV는 학습 내부에서만, 한계는 별도 정상 calibration에서 결정했다. 최종 모델은
JSON 저장 후 복원하여 평가했다. 고장 코드와 강도를 모델 특징으로 사용하지 않았다.

평가 관찰 후 아키텍처를 고친 이력 때문에 최종 결과는 재사용 평가다. 독립 감사는
다른 계산 코드로 원시 기록·고정 기준·경보를 재구성한다. 이 감사가 독립 데이터
검증을 뜻하지는 않는다. 주석 변경으로 해시가 달라진 것과 계산 변경도 구분한다.

평가에는 TP/TN/FP/FN, 정확도, 검출률, 오경보율, 대상/원자료 판단률, 사건 수,
고장 시작 전 경보, 첫 새 경보 지연, 정상 시간당 경보 빈도를 함께 보존한다.
고장 발생 시각이 독립 계측되지 않은 경우 고정 제외 후 첫 양성 관측부터의 지연임을
명시한다. 경보 해제 지연의 효과는 원시 감지력과 별도 표로 비교한다.

## 소프트웨어 공개 패키지 확인

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
python scripts/release_audit.py
```

wheel과 sdist 멤버가 허용된 원본 코드·문서·시험·예제로만 구성되는지 감사한다.
릴리스 테스트/의존성/해시는 `evidence/release_verification.json`에 기록한다.
자체 코드 스냅샷과 프로토콜 지문은 보존하지만 raw corpus나 학습 모델은 재배포하지 않는다.
