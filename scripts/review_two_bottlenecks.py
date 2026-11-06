"""Focused exploratory review; no model replacement, split changes or test-based fitting."""
import hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import SensorBatch,HysteresisAlarmDiagnostic
from equipment_diagnostics.evaluation import binary_metrics

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/two_bottleneck_review'
BASE=ROOT/'outputs/literature_improvement'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def runs(t,flag):
    starts=np.flatnonzero(np.r_[True,flag[1:]!=flag[:-1]])
    return [dict(alarm=bool(flag[s]),rows=int(end-s),start_from_first_eligible_s=float(t[s]-t[0]),
        last_from_first_eligible_s=float(t[end-1]-t[0])) for s,end in zip(starts,np.r_[starts[1:],len(flag)])]
def pc(x):return '—' if x is None else f'{100*x:.4f}%'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    protected=[BASE/'results.json',BASE/'heatpump_frozen.json',BASE/'marine_frozen.json',BASE/'adoption.json']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in protected}
    d=pd.read_csv(BASE/'heatpump_predictions.csv');policies={'raw':d.signed_block60_alarm.to_numpy(bool)}
    for delay in (30.,60.):
        alarm=np.zeros(len(d),bool)
        for sheet,g in d.groupby('sheet',sort=False):
            a=g.signed_block60_alarm.to_numpy(float);v=g.signed_block60_valid.to_numpy(bool)
            b=SensorBatch(g.time_s.to_numpy(),a[:,None],('alarm_flag',),('1',),'publisher_epoch',
                'tri_hp_propane','reused_measured_evaluation',valid=v[:,None],episodes=np.asarray(g.experiment,dtype=str),
                metadata={'signal':'frozen upstream alarm flag; not a new physical fault measurement'})
            model=HysteresisAlarmDiagnostic(dict(indication_score='alarm_flag'),on_threshold=.5,
                confirmation_s=0,release_ratio=.5,release_s=delay,max_gap_s=60)
            r=model.score(b);assert np.array_equal(r.valid,v)
            alarm[g.index]=r.alarms
        policies['off_delay_'+str(int(delay))+'s']=alarm
    summaries={};weak=(d.experiment=='EF10.1').to_numpy()&d.eligible.to_numpy(bool)
    for k,a in policies.items():
        v=d.signed_block60_valid.to_numpy(bool);e=d.eligible.to_numpy(bool);y=d.label.to_numpy(bool)
        ix=weak&v;t=d.time_s.to_numpy()[ix];hit=np.flatnonzero(a[ix])
        summaries[k]=dict(whole=binary_metrics(y,a,v,e),weak=binary_metrics(y[ix],a[ix],np.ones(ix.sum(),bool)),
            first_observed_weak_alarm_delay_s=None if not len(hit) else float(t[hit[0]]-t[0]),weak_alarm_runs=runs(t,a[ix]),
            meaning='raw detection' if k=='raw' else 'alarm-state coverage after release delay; not new sensor detection ability')
        d[k+'_review_alarm']=a.astype(int)
    raw=policies['raw'][weak];first=int(np.flatnonzero(raw)[0]);false_total=int((~raw).sum())
    weak_analysis=dict(eligible_rows=len(raw),detected_rows=int(raw.sum()),missed_rows=false_total,
        missed_before_first_alarm=first,missed_after_first_alarm=false_total-first,
        first_delay_s=summaries['raw']['first_observed_weak_alarm_delay_s'],
        note='Onset is first eligible observation after fixed180s exclusion, not an independently timed physical fault onset.')
    # Original marine normalization script only rewrites schema/labels/encoding.
    path=ROOT/'research_support/public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip'
    z=zipfile.ZipFile(path);refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'))
    ref=pd.read_csv(io.BytesIO(z.read(refname)),skiprows=[1,2])
    frozen=json.loads((ROOT/'outputs/completion_7_13/independent_marine/frozen.json').read_bytes())
    train=ref.iloc[frozen['split_indices']['train']];environment=[]
    features=['Engine room Temp.','Charge Air Press.','Charge Air IC Air Temp. In','Charge Air IC Air Temp. Out']
    for name in frozen['test_files']:
        frame=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);normal=frame[frame['Anomaly State']==0]
        power=float(normal['Shaft Power'].median());matched=train[abs(train['Shaft Power']-power)<=3]
        info={}
        for f in features:
            info[f]=dict(matched_train_median=float(matched[f].median()),matched_train_range=[float(matched[f].min()),float(matched[f].max())],
                evaluation_normal_median=float(normal[f].median()),evaluation_normal_range=[float(normal[f].min()),float(normal[f].max())])
        environment.append(dict(file=name,matched_training_rows=len(matched),evaluation_normal_rows=len(normal),
            matching_rule='training ShaftPower within3kW of evaluation-normal median; exploratory analysis only',features=info))
    m=frozen['models']['load_conditioned_pressure']['reference']['pressure_model']
    x=(np.column_stack((np.log(train['Shaft Power']*1000),np.log(train['Engine Speed']/60)))-m['center'])/m['scale']
    a,b=x.T;design=np.column_stack((np.ones(len(x)),a,b,a*a,a*b,b*b))
    conditioning=dict(log_power_speed_correlation=float(np.corrcoef(x.T)[0,1]),design_condition_number=float(np.linalg.cond(design)),
        interpretation='Correlated inputs warrant regularization/normal-only validation; this value alone does not establish a numerical failure.')
    report=dict(scope='focused exploratory review of previously reused measured evaluation; no refit or split changes',
        baseline_sha256=hashes,heatpump_weak_analysis=weak_analysis,alarm_policy_sensitivity=summaries,
        marine_environment=environment,marine_design=conditioning,
        no_recovery_truth=True,new_independent_fault_metrics=None,
        cautions=['Off-delay sensitivity is an alarm-policy comparison. Raw detections and first delay remain separate.',
            '30/60s release periods are illustrative, not optimized or approved operating settings.',
            'No measured fault recovery transitions: delayed-clear false alarms cannot be evaluated.',
            'Marine normal prefixes were inspected for diagnosis only, never moved into training/calibration.',
            'Temperature/pressure covariates may explain part of distribution shift; no physical cause or performance improvement is established.'])
    (OUT/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    d.to_csv(OUT/'heatpump_alarm_policy_comparison.csv',index=False)
    assert hashes=={str(p.relative_to(ROOT)):sha(p) for p in protected}
    rows='\n'.join(f"| {k} | {pc(v['weak']['recall_valid'])} | {v['weak']['TP']} / {v['weak']['FN']} | {pc(v['whole']['false_positive_rate_valid'])} | {v['first_observed_weak_alarm_delay_s']:.0f}초 |" for k,v in summaries.items())
    text=f'''# EF10.1·엔진 필터 두 병목 재검토 (2026-11-06)

이번은 기존 실제 평가 자료의 탐색적 재검토다. 코어·기본 모델·학습/보정/평가 분리를 변경하지 않았다.

EF10.1은 실험 설정상 증발기 물 유량10% 감소 조건이다. 유효163표본 중80검출·83미검출이며, 미검출은 최초 경보 전51개와 이후 경보 중단32개로 나뉜다. 첫 경보 지연510초는 고정180초 제외 후 첫 유효 양성 관측부터 계산한 값이다. 독립적으로 확인한 실제 고장 발생 시각부터의 지연이 아니다.

경보 해제 지연의 영향만 별도 확인했다. 결과를 새 센서 검출률로 부르지 않는다.

| 정책 | 양성 중 경보 상태 비율 | 경보 / 비경보 표본 | 전체 평가 정상 오경보율 | 첫 관측 경보 지연 |
| --- | --- | --- | --- | --- |
{rows}

해제 지연은 이후 경보 단절을 줄이지만 최초 지연을 해결하지 못한다. 정상490개는 정상 두 시험의 시간 분할이며, 실제 고장 복구 구간 정답은 없어 복구 후 경보 해제 지연에 의한 오경보를 평가하지 못했다. 30/60초는 예시 설정으로 최적화·운영 승인된 값이 아니다. 기본값으로 채택하지 않았다.

엔진 필터는 같은 출력±3kW의 정상 학습 표본과 평가 파일의 정상 구간을 비교했다. 40% 부하에서 실내 온도 중앙값은 약30.39→24.85℃, 과급 공기압도 달랐다. 기존 출력·회전수 모델에는 이 입력들이 없다. 회전수·출력 로그의 상관은{conditioning['log_power_speed_correlation']:.4f}, 설계행렬 조건수는{conditioning['design_condition_number']:.2f}다. 상관이 높지만 이것만으로 수치 불안정이 원인이라고 확정할 수 없다. 원 배포 전처리 코드는 문자열·단위 표기·스키마 정리에 해당하며, 검토한 코드에서 수치 재보정은 찾지 못했다.

다음 실험은 엔진 필터의 정상 모델을 원자료에 존재하는 환경/흡기 조건으로 보완하되, 후보 입력은 정상 학습 내부의 시각 블록 검증으로 선택한다. 실내 온도는 우선 검토할 수 있으나 과급압·흡기 온도는 고장 영향도 받을 수 있어 조건 입력으로 넣으면 이상을 가릴 가능성도 함께 시험해야 한다. 실제 흡기 유량이라고 부르거나 계측되지 않은 압력 기준을 임의 가정하지 않는다. 과거 평가 정상 구간을 재학습에 넣지 않는다.

히트펌프는 경보 유지와 초기 검출을 분리한다. 현재 센서에서 정상과 약한 고장의 운전조건별 구별 가능성을 먼저 확인하고, 필요하면 이미 존재하는 별도 과열도 로거를 타임스탬프로 검토한다. 시계 동기·지연 검증 전에는 두 로거를 동일 행으로 결합하지 않는다. 열원 실제 입출구 온도·유량은 공개 주 로거에 없어 이를 새 관측값으로 만들어 쓰지 않는다.

출처: [원 실험 논문](https://doi.org/10.1016/j.ijrefrig.2021.10.017), [원 엔진 데이터 설명](https://arxiv.org/abs/2607.19444), [ISA의 경보 관리 해설](https://www.isa.org/intech-home/2019/january-february/features/applying-alarm-management), [Emerson 경보 기법](https://www.emerson.com/is/content/emerson/en/systems-and-software/deltav-distributed-control-system-dcs/white-papers/documents/advanced-alarming-techniques.pdf), [제조사 경보 해제 지연 설명](https://www.octave.com/learn/resources/blogs/taming-wild-alarm-system-part-three).
'''
    (ROOT/'docs/TWO_BOTTLENECK_REVIEW.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(weak=weak_analysis,policy_comparison={k:dict(weak_alarm_coverage=v['weak']['recall_valid'],normal_fpr=v['whole']['false_positive_rate_valid'],first_delay_s=v['first_observed_weak_alarm_delay_s']) for k,v in summaries.items()},baseline_unchanged=True),indent=2))
if __name__=='__main__':main()
