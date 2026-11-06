"""Reviewable rank7..13 report, computed tables and clear evidence boundaries."""
import hashlib,json
from pathlib import Path
from html import escape
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/completion_7_13'
def read(n):return json.loads((OUT/n/'results.json').read_bytes())
def pct(x):return '평가 불가' if x is None else f'{x*100:.4f}%'
def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows)
def comparisons(title,r):
    return '\n'+title+'\n\n'+table(['정책','정확도','검출률','오경보율','판단률','TP / FN / FP / TN'],
        [[k,*[pct(v[a]) for a in ('accuracy_valid','recall_valid','false_positive_rate_valid','coverage')],
            f"{v['TP']} / {v['FN']} / {v['FP']} / {v['TN']}"] for k,v in r.items()])+'\n'

def events():
    d=pd.read_csv(OUT/'independent_marine/predictions.csv');rows=[]
    for name,g in d.groupby('file',sort=False):
        label=g.label.to_numpy(bool);t=g.time_s.to_numpy();n=len(t)
        starts=np.flatnonzero(label&~np.r_[False,label[:-1]])
        ends=np.flatnonzero(label&~np.r_[label[1:],False])
        for policy in ('constant_pressure','load_conditioned_pressure'):
            alarm=g[policy+'_alarm'].to_numpy(bool)&g[policy+'_valid'].to_numpy(bool)
            neg=alarm&~label;false_events=int((neg&~np.r_[False,neg[:-1]]).sum())
            event=[]
            for a,b in zip(starts,ends):
                hit=np.flatnonzero(alarm[a:b+1]);event.append(dict(onset_s=float(t[a]),end_s=float(t[b]),
                    detected=bool(len(hit)),delay_s=None if not len(hit) else float(t[a+hit[0]]-t[a])))
            rows.append(dict(file=name,policy=policy,false_positive_alarm_fragments=false_events,positive_segments=event))
    (OUT/'independent_marine/event_analysis.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    return rows

def main():
    ch=read('chiller');wet=read('wet_coil');marine=read('independent_marine');physics=read('physics');tank=read('tank')
    scope=json.loads((OUT/'scope_availability.json').read_bytes());ev=events()
    summary=[
        ['7','탱크','실측 교정·시각 검토 + 입력 변환 구현','압력 9개 파일 1,839행에 작성자 수위 교정식 재현. 시계·출처·단위를 보존하는 인과적 정렬 API 추가.','유량 교정·신뢰도, 재고 환산 형상, 센서/시스템 시각 차이 해결 전 정량 누설 정확도 평가 불가.'],
        ['8','냉동기','재사용 실제 실험 평가; 후보 미채택','냉매 포화온도 2개를 추가한 정상 잔차 모델 검증. 추가 단계 오경보 38.3345→31.9545%.','검출률 27.3902→21.5019%로 하락; 0단계보다 불리해 교체하지 않음. 오일 제어·운전 모드별 정상 반복 자료 필요.'],
        ['9','새 독립 자료','실측 자료 3종 확보; 새 엔진 필터 적용','엔진 부하·회전수 조건을 반영한 차압 초과 감시 추가. 기존 HSE와 독립된 실제 장치. 배포자 MD5 확인.','엔진 1대 내부 분리 평가; HSE RUL 예측의 교차 설비 검증은 아님. 나머지 두 자료는 현재 센서·정답 부적합.'],
        ['10','젖은 코일','새 적용: 확보해 둔 실제 실험 자료','건공기 엔탈피·제습량 및 유량/밀도 보정 차압 계산. 학습 Baseline, 보정 RH85, 평가 V1/V2/F1~F4 파일 분리.','검출률 5.8824%, 판단률 54.9575%로 자동 진단 사용 어려움. 실제 정상 반복/유량·착상 조건 모델 필요.'],
        ['11','기화기','정상 예측기 구현 + 물리/시뮬레이션','예열·비등·과열의 정상 출구 온도/엔탈피/기화율 예측. 독립 ODE와 개발 온도 최대 차이 2.14e-6 K.','실제 설비 미검증. 일정 압력·일정 열원 온도·상수 물성 범위. 온도만으로 비등 중 기화율 저하 구분 불가.'],
        ['12','스팀트랩·증류탑','실제 자료 적합성 재조사; 고장 성능 미평가','스팀트랩 논문 원자료 비공개/정답 한계 확인. 증류탑 실제 실험 28개 메타데이터·센서 목록 재검토.','스팀트랩 독립 고장 정답과 T/음향 원자료 미확보. 증류탑 내부 기액 유량·플러딩 정답 미확보.'],
        ['13','보일러','명시적 입력 재고 계산 + 진단 연결 구현','드럼 원형 단면·포화 물/증기 밀도·회로별 기포율로 총재고 계산 후 질량수지 연결. 압력/기포율 변화 시뮬레이션 검증.','실제 검증 미실시. 기포율은 외부 관측/추정 입력이며 미계측 기포율·swell 동적 관측기는 미구현.']]
    text='# 7~13순위 구현·검증 결과 (v0.14.0, 2026-11-06)\n\n'
    text+='7~13번까지 구현과 자료 검토를 진행했다. 실제 고장 검증이 불가능한 항목은 성능 수치를 만들지 않았다. 5~6번 결과는 [이전 보고서](STAGE56_IMPROVEMENT.md)에 보존했고, 히트펌프 개발 프로파일 채택·기존 HSE 필터 기본값 유지 결정을 바꾸지 않았다.\n\n'
    text+=table(['순위','대상','검증 종류/상태','진행 결과','남은 문제'],summary)+'\n\n'
    text+='## 새로 확보한 실제 엔진 필터 자료\n\n'
    text+='[Zenodo 19857425](https://zenodo.org/records/19857425)의 실제 필터 표면을 가리는 시험이다. 입력은 필터 차압 Pa, 축동력 W, 회전수 1/s이며 고장 정답은 제공자의 Anomaly State다. 유량을 계측하지 않아 수력 저항이나 잔여수명으로 해석하지 않는다. 정상 파일에서 로그 차압을 로그 부하·회전수의 2차식으로 학습하고, 별도 정상 구간 q99로 보정했다. 성장 한계 25%, 최소 초과 10 Pa, ridge .001, 10초 지속 정책을 고장 평가 전에 정했다.\n\n'
    f=json.loads((OUT/'independent_marine/frozen.json').read_bytes())
    text+=f"정상 Reference 파일 분리: 학습 {len(f['split_indices']['train']):,}행 / 보정 {len(f['split_indices']['calibration']):,}행 / 정상 평가 {len(f['split_indices']['normal_evaluation']):,}행. 부하 구간 내 10% 공백 외에 **전체 시각 기준 20초 이상 공백**을 확인했다. 고장 파일 4개는 전부 평가 전용이다. 정상 파일은 한 실험의 일부이므로 독립 반복 실험으로 세지 않는다.\n\n"
    text+='첫 부하 구간 분리에서는 인접 구간 경계에 가까운 시각이 발견되어 전체 시각 공백을 강화했다. 첫 결과를 initial_bin_partition에 보존했다. 아래는 같은 고장 평가 파일을 재사용한 분리 무결성 보완 결과다. **새로 확보한 독립 장치 자료에 대한 개발 평가이며, 수정된 모델의 새 맹검·교차 엔진 성능은 아니다.** 기존 HSE의 RUL≤30초와 정답이 달라 수치를 직접 연결하지 않는다.\n'
    text+=comparisons('실제 자료: 같은 표본·정답에서 고정 기준과 운전조건 보정 비교',marine['comparison'])
    positives=[x for x in ev if x['policy']=='load_conditioned_pressure' and x['positive_segments']]
    delays=[p['delay_s'] for x in positives for p in x['positive_segments']]
    text+=f"\n고장 구간 {sum(len(x['positive_segments']) for x in positives)}개 중 {sum(p['detected'] for x in positives for p in x['positive_segments'])}개에서 경보했다. 구간별 지연(초): {delays}. **최대 지연 2,314초(약 38.6분)**로 조기 검출에는 큰 제한이 있다. 제공자가 표기한 점진적 필터 가림 시작부터 계산한 값이며, 가림 초기의 작은 이상도 미검출 표본으로 유지했다. 구간 한 번 검출로 전체 구간을 정답 처리하지 않았다.\n"
    text+='\n## 냉동기 재사용 평가\n\n'
    text+='정상 normal.xls 학습 / normal1.xls 보정과 기존 35개 평가 파일을 유지했다. 후보는 물 측 운전조건 3개에 증발/응축 포화온도 2개를 추가했다. PO_feed를 PO_net과 같다고 취급하거나 임의로 상쇄하지 않았다. 포화온도를 조건 입력에 쓰면 해당 값으로 나타나는 고장 신호가 가려질 수 있다. 후보는 정상 학습·보정만 했고, 평가 후 추가 조정을 하지 않았다.\n'
    text+=comparisons('실제 실험 1대, 평가 파일 재사용',ch['comparison'])
    text+='\n후보 미채택. 기존 0단계도 낮은 검출률 때문에 보조 감시 범위다. 오일 압력의 정상 제어 모드·충전 조건과 반복 실험을 확보해야 다음 단계로 갈 수 있다.\n'
    text+='\n## 젖은 코일 실제 자료\n\n'
    text+='[Mendeley s6d23g2m2w](https://data.mendeley.com/datasets/s6d23g2m2w/1)는 착상 중인 실제 마이크로채널 코일 실험이며 F1~F4는 제어된 표면 오염 조건이다. 청정 표면도 착상하므로 이를 고장 정답으로 혼동하지 않았다. 8개 시트의 463개 측정 관측 중 평가 6개 시트 353개를 사용했다. 건공기 유량·습도·엔탈피는 일부 제공자가 산출한 값이다.\n\n'
    text+='습공기 엔탈피 열량과 수분 제거량을 계산했다. 제공자의 m_w는 표기 g/s와 달리 수치가 g/min에 맞고 m_t는 m_w의 누적합에 맞았다. 해당 열을 그대로 g/s로 쓰지 않았다. 브라인 질량유량이 없어 양측 열수지·UA 정확도는 검증하지 못했다.\n'
    text+=comparisons('정상 시트 학습·보정 분리; 별도 청정/오염 시트 평가',wet['comparison'])
    text+='\n공기측 제한 감시 후보의 오경보는 줄었지만 미검출·판단 보류가 많아 자동 오염 진단으로 채택하지 않는다. 정상 기준의 유량 범위를 벗어난 표본은 UNKNOWN으로 남겼다.\n'
    text+='\n## 기화기·보일러 물리 검증\n\n'
    text+='기화기는 UA·포화온도·잠열·액/증기 비열·엔탈피 기준을 명시한다. 독립 solve_ivp 적분과 개발 240개 조건을 비교해 최대 온도 차이 2.133e-6 K, 엔탈피 차이 0.00320 J/kg였다. 이는 상수 물성 계산식 검증이며 실제 유체 물성/현장 성능 검증이 아니다.\n'
    text+=comparisons('기화기 시뮬레이션: 정상 120개 + UA 40% 저하 120개',physics['vaporizer'])
    text+='\n최소 출구 280 K를 만족하지 않는 정상 저부하 조건도 위 시뮬레이션에 포함되어 있다. 따라서 temperature_limit/normal_prediction의 오경보율은 **UA 저하라는 고장 정답 기준**이며, 온도 한계 위반 경보 자체가 잘못됐다는 뜻은 아니다. residual_only는 첫 두 결과를 본 뒤 설비 잔차와 온도 한계를 분리한 추가 분석이다. 동일 시뮬레이션을 재사용한 결과로 표시했으며 온도 한계 경보를 제거한 개선이라고 주장하지 않는다. 비등 중 정상·전열저하가 모두 포화온도이면 온도 잔차로 구별되지 않는다. 기화율 예측값을 실제 기화율 고장 정답으로 재사용하지 않았다.\n\n'
    text+='보일러는 수평 원통·평면 끝판 드럼, 절대압, 교정된 기하학적 수위, 연결 회로 부피와 회로별 증기 기포율을 입력한다. CoolProp의 포화 물·증기 밀도를 사용한다. 원형 단면 손계산·독립 적분, 양 끝 수위·작은 수위·잘못된 상/기포율을 시험했고 압력·기포율 변화 중 총재고→질량수지 연결을 검증했다. 실제 드럼 DP의 수위 보정, 비평형·서브쿨링·swell은 자동 추정하지 않는다.\n'
    text+=comparisons('보일러 시뮬레이션: 정상 / 0.2 kg/s 누설, 60초 질량수지 창 이후',{'configured_inventory':physics['boiler']['metrics']})
    text+='\n재고 최대 차이는 2.64e-9 kg 이내였다. 기포율을 참값으로 제공한 수치 시험이므로 현장 누설 검출률 100%라는 뜻이 아니다. 원본 360개 중 창 준비 12개 제외 후 348개 판단으로 원본 판단률은 96.67%다.\n'
    text+='\n## 실제 자료를 적용하지 못한 항목\n\n'
    text+=table(['대상','확보·검토','평가하지 않은 이유'],[
        ['탱크', '작성자 MLX 교정식과 9개 압력 파일 1,839행', '유량 교정·신뢰도와 시각 정렬이 미해결. 누설 펄스를 kg/s 정답으로 만들지 않음.'],
        ['압출기 필터','새 압출기 온도·전류·전압 60회, 27,748행','차압·유량 없음. 배포 설명의 Labels.csv가 파일 목록/파라미터 ZIP에 없어 실패 종류를 임의 추정하지 않음.'],
        ['배관 기밀시험','새 기체 5종×모세관 결함 2종, P/T 10프로파일','게이지압으로 절대 질량을 계산하지 않음. 유효 체적·절대 기준압·별도 정상 참조가 필요.'],
        ['증류탑','실제 실험 28개와 YAML 이상 설명','일반 공정 이상 정답과 플러딩은 다름. 내부 기액 질량유량의 적격한 입력 대응이 없음.'],
        ['스팀트랩','현장 T/음향 논문 및 배포 여부 재조사','독립 고장 정답을 갖춘 다운로드 원자료 미확보. 공개 코드·규칙 의사정답을 실측 고장 검증으로 세지 않음.'],
        ['기화기·보일러','계산·물리·시뮬레이션 검증','적합한 실제 설비 센서/형상/열원/고장 정답 없음. 기화기 착상 공개 계산 자료를 실제 실험으로 재분류하지 않음.']])+'\n'
    text+='\n## 구현 목록과 검증\n\n'
    text+=table(['Python API','기능/범위'],[
        ['calibrated_level','명시적 V→m 교정. 범위 밖은 무효.'],['causal_asof','같은 가용 시계·설비·출처·운전 구간에서 과거 관측만 전달; 오래된 값 무효.'],
        ['LoadConditionedPressureDiagnostic','정상 부하·회전수 대비 차압 초과 감시. 별도 정상 보정·기준 저장/복원.'],
        ['ChillerPerformanceDiagnostic(auxiliary_conditioning="water_refrigerant")','추가 2개 냉매 조건을 사용하는 실험 옵션. 이번 후보는 미채택.'],
        ['moist_air_exchange / WetCoilAirsideDiagnostic','습공기 열량·수분 제거량과 공기측 차압 보정. dry UA와 구분.'],
        ['PiecewiseVaporizer','명시적 상수 물성으로 정상 출구 상태 예측 후 기존 VaporizerDiagnostic에 전달.'],
        ['horizontal_cylinder_liquid_volume / SaturatedBoilerInventory','기하학적 수위·절대압·회로 부피/기포율→총재고→기존 BoilerBalanceDiagnostic.']])+'\n\n'
    text+='새 기능은 Python API다. 기존 CLI 종류 11개는 유지했다. 예제: examples/qualified_physical_inputs.py. core import/NumPy 추론에는 sklearn이나 CoolProp를 요구하지 않으며 보일러 물성 계산에서만 CoolProp를 지연 로드한다.\n\n'
    text+='입력 거부/무효 처리, 손계산, 극단·경계값, 단위·식별정보·기준 복원 연결, 전체 회귀, 입력→예측/재고→진단 실행을 검사했다. 비연동 시험 **261개**와 실제 기존 객체 연동 시험 **7개**가 통과했다. 별도 코드가 원본 체크섬·학습/보정/평가 시각 분리·실제 정답·혼동행렬·차압 점수·10초 지속 경보 28,674행을 재검산했다. 261개는 기능/물리 시험이며 현장 고장 표본 수가 아니다.\n\n'
    text+='실행 순서: acquire_completion_data.py → validate_tank_readiness.py → validate_chiller_refrigerant.py → validate_independent_marine.py → validate_wet_coil.py → validate_completion_physics.py → inspect_completion_scope.py → audit_completion.py → render_completion.py. 원본 자료·예측·동결 기준·초기 실패 후보는 outputs/completion_7_13와 research_support에 별도로 보존한다.\n'
    text+='\n## 다음 개선 우선순위\n\n'
    text+=table(['순위','다음 작업','필요 자료'],[
        ['1','엔진 필터의 별도 장치/날짜 정상·막힘 시험으로 동결 모델 검증','같은 센서·단위, 조작 시각/독립 고장 정답. 현재 새 자료 성능과 HSE 성능은 분리.'],
        ['2','기존 히트펌프 약한 EF 고장 재현·검증','정상/약한 유량 감소 반복시험; 현재 EF10.1 검출률 49.08%.'],
        ['3','탱크 유량 교정과 가용 시각 정렬','펄스당 체적·오차·수조 단면·시계 동기화 기록.'],
        ['4','냉동기 오일 제어 모드별 정상 기준','정상 반복 운전과 오일 제어/충전 설정. 현 평가를 학습으로 돌리지 않음.'],
        ['5','젖은 코일 착상·오염 분리','각 RH/유량의 정상 반복과 오염 반복, 브라인 유량 및 열량.'],
        ['6','기화기·보일러 실제 입력과 고장 정답 확보','기화기 열원·유량·입출구 상태; 보일러 형상·회로 기포율/상태와 독립 재고/누설량.']])+'\n'
    text+='\n## 1차 출처\n\n'
    text+='- [실제 엔진 필터·냉각기 이상 자료](https://zenodo.org/records/19857425)\n- [실제 젖은 코일·오염 실험과 열 정의](https://data.mendeley.com/datasets/s6d23g2m2w/1) (CC BY-NC 3.0; 원자료를 소프트웨어 배포본에 포함하지 않음)\n- [탱크 작성자 자료](https://github.com/iraptis/Liquid-Level-Control-System-Fault-Diagnosis-Data)\n- [실제 연속 증류 실험](https://zenodo.org/records/17628963)\n- [배관 기체 누설 시험](https://zenodo.org/records/20582921)\n- [압출기 필터 수명 자료](https://zenodo.org/records/21987832)\n- [스팀트랩 현장 연구: 비공개 원자료와 의사정답 제한](https://www.mdpi.com/1424-8220/26/21/6763)\n- [스팀트랩 음향 배경소음 연구: 원자료 미명시](https://www.sciencedirect.com/science/article/pii/S2772569325000374)\n- [기화기 착상 공개 자료: 제공자가 계산 결과라고 명시](https://data.mendeley.com/datasets/93mr76p6c4/1)\n- [CoolProp 포화 물/증기 상태 및 SI 인터페이스](https://coolprop.org/coolprop/HighLevelAPI.html)\n'
    (ROOT/'docs/COMPLETION_7_13.md').write_text(text,encoding='utf-8')
    # Small standalone HTML, using the same computed data rather than another set of numbers.
    rows=''.join('<tr>'+''.join('<td>'+escape(x)+'</td>' for x in row)+'</tr>' for row in summary)
    def ht(title,comp):
        h='<h2>'+escape(title)+'</h2><table><tr><th>정책</th><th>정확도</th><th>검출률</th><th>오경보율</th><th>판단률</th></tr>'
        return h+''.join('<tr><td>'+escape(k)+'</td>'+''.join('<td>'+pct(v[a])+'</td>' for a in ('accuracy_valid','recall_valid','false_positive_rate_valid','coverage'))+'</tr>' for k,v in comp.items())+'</table>'
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><title>7~13순위 구현·검증</title><style>body{font:15px/1.6 system-ui;margin:32px;max-width:1500px;color:#1e3042}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #c6d1dc;padding:10px;text-align:left;vertical-align:top}th{background:#e6edf4}.note{padding:18px;background:#fff1d7}pre{white-space:pre-wrap}</style><h1>7~13순위 구현·검증 · v0.14.0</h1><p class="note">실제 실험 / 재사용 평가 / 시뮬레이션을 분리합니다. 냉동기 후보는 미채택입니다. 새 필터 자료는 기존 HSE RUL과 정답이 다릅니다. 스팀트랩·증류탑·기화기·보일러의 실제 고장 성능은 확보하지 못했습니다.</p><table><tr><th>순위</th><th>대상</th><th>증거</th><th>진행 결과</th><th>남은 문제</th></tr>'+rows+'</table>'
    page+=ht('새 실제 엔진 필터 자료: 동일 파일 재평가로 전체 시각 분리 보완',marine['comparison'])
    page+=ht('냉동기: 이전 실제 평가 자료 재사용',ch['comparison'])+ht('젖은 코일: 확보 자료의 새 적용',wet['comparison'])
    page+=ht('기화기: 물리 가정 내 시뮬레이션, 온도 한계와 UA 이상 정답 구분 필요',physics['vaporizer'])
    page+=ht('보일러: 기포율 참값을 입력한 시뮬레이션, 실제 관측기 검증 아님',{'configured_inventory':physics['boiler']['metrics']})
    page+='<p>261개 회귀·물리 시험 + 7개 기존 객체 연동 시험 통과. 상세한 가정·데이터 분리·미채택 원인·다음 우선순위는 docs/COMPLETION_7_13.md에 있습니다.</p><details><summary>상세 보고서 원문</summary><pre>'+escape(text)+'</pre></details></html>'
    (OUT/'report.html').write_text(page,encoding='utf-8')
    (OUT/'summary.json').write_text(json.dumps(dict(version='0.14.0',ranked_results=summary,
        new_filter_metrics=marine['comparison'],chiller_metrics=ch['comparison'],wet_coil_metrics=wet['comparison'],
        physical_simulation=dict(vaporizer=physics['vaporizer'],boiler=physics['boiler']['metrics']),
        actual_unqualified=['tank quantitative mass balance','RO fouling','vaporizer','steam trap','column flooding','boiler']),indent=2),encoding='utf-8')
    print('Report and documentation written.')
if __name__=='__main__':main()
