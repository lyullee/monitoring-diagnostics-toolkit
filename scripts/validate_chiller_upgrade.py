"""Frozen normal-only development, then paired held-out comparison with v0.4 protocol."""
from collections import Counter
from datetime import datetime,timezone
from html import escape
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import ChillerPerformanceDiagnostic,__version__
from equipment_diagnostics.chiller_reference import features,targets,fit,predict
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import chiller,PROTOCOL,DATA,score_threshold

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'chiller_upgrade'
CHANNELS=dict(chilled_in='tei',chilled_out='teo',cooling_out='tco',evaporating_temperature='evap',
              condensing_temperature='cond',chilled_flow='flow',electric_power='power')


def choose_model(train):
    probe=ChillerPerformanceDiagnostic({**CHANNELS,'cooling_in':'tci'},reference_mode='conditioned')
    metrics,valid,_=probe._raw(train)
    x,y=features(metrics),targets(metrics)
    valid &= np.isfinite(x).all(axis=1)&np.isfinite(y).all(axis=1)
    starts=valid & ~np.r_[False,valid[:-1]]
    groups=np.cumsum(starts)[valid]
    if len(np.unique(groups))<5: raise ValueError('Need >=5 independent normal operating segments for grouped CV')
    x,y=x[valid],y[valid]
    floors=np.array([np.log1p(.02),.2,.2,np.log1p(.02)])
    # A whole contiguous steady segment belongs to one fold; adjacent rows aren't shuffled.
    folds=(groups-1)%5
    scale=np.maximum(y.std(axis=0),floors)
    choices=[]
    for degree in (1,2):
        for alpha in (.001,.01,.1,1.):
            errors=[]
            for fold in range(5):
                a=folds!=fold; b=~a
                m=fit(x[a],y[a],degree=degree,alpha=alpha,floors=floors)
                errors.append(float(np.mean(((predict(m,x[b])-y[b])/scale)**2)))
            choices.append({'degree':degree,'ridge_alpha':alpha,'grouped_cv_rmse':float(np.sqrt(np.mean(errors)))})
    selected=min(choices,key=lambda r:r['grouped_cv_rmse'])
    return selected,choices,{'normal_valid_samples':len(y),'normal_segments':len(np.unique(groups)),
                            'fold_samples':[int(np.sum(folds==f)) for f in range(5)]}


def aggregate(rows,*,common=False):
    y=np.concatenate([r['label'] for r in rows]); a=np.concatenate([r['alarm'] for r in rows])
    v=np.concatenate([r['common'] if common else r['valid'] for r in rows])
    e=np.concatenate([r['eligible'] for r in rows])
    return binary_metrics(y,a,v,e)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    old=json.loads((ROOT/'outputs'/'public_validation'/'chiller_results.json').read_text(encoding='utf-8'))
    p=PROTOCOL['chiller']; load,audit=chiller(loader_only=True)
    train,_=load('Chiller Data/Benchmark Tests/'+p['train'])
    selected,choices,cv=choose_model(train)
    before=ChillerPerformanceDiagnostic(CHANNELS,persistence_s=30).fit(train)
    after=ChillerPerformanceDiagnostic({**CHANNELS,'cooling_in':'tci'},reference_mode='conditioned',
        regression_degree=selected['degree'],ridge_alpha=selected['ridge_alpha'],persistence_s=30).fit(train)
    cal,_=load('Chiller Data/Benchmark Tests/'+p['calibration'])
    thresholds={}
    for key,m in [('before',before),('after',after)]:
        r=m.score(cal)
        if r.valid.sum()<10: raise ValueError('Insufficient independent normal calibration')
        thresholds[key]=max(1.,float(np.nextafter(np.quantile(r.scores[r.valid],.99),np.inf)))
    uncalibrated_after=ChillerPerformanceDiagnostic({**CHANNELS,'cooling_in':'tci'},reference_mode='conditioned',
        regression_degree=selected['degree'],ridge_alpha=selected['ridge_alpha'],persistence_s=30).set_reference(after.reference)
    after.calibrate(cal,quantile=.99)
    assert after.reference['score_calibration']['threshold']==thresholds['after']
    specs=[('Chiller Data/Benchmark Tests/'+n+'.xls',False,'normal') for n in p['normal_test']]
    specs += [('Chiller Data/'+category+'/'+n+'.xls',True,category) for category,names in p['fault_test'].items() for n in names]
    assert len({Path(n).name for n,_,_ in specs})==len(specs)
    assert p['train']!=p['calibration'] and not {p['train'],p['calibration']} & {Path(n).name for n,_,_ in specs}
    frozen={'schema':'equipment-diagnostics.chiller-upgrade-development.v1','utc':datetime.now(timezone.utc).isoformat(),
        'split':p,'train_fingerprint':train.fingerprint,'calibration_fingerprint':cal.fingerprint,
        'selection_data':'normal.xls only; contiguous stable-segment grouped CV',
        'cv':cv,'candidates':choices,'selected':selected,'thresholds':thresholds,
        'before_reference':before.reference,'after_reference':after.reference,
        'policy':'Fixed 99th normal calibration quantile, 30s persistence. No test-based model/threshold selection.',
        'evaluation_reuse_note':'These evaluation files were examined in the previous baseline study; this is a development-round comparison, not a new blind qualification set.'}
    development=json.dumps(frozen,indent=2,sort_keys=True)
    (OUT/'frozen_development.json').write_bytes(development.encode('utf-8'))
    # Everything above is frozen before accessing any held-out file in this run.
    allrows={k:[] for k in ('before_fixed','before_calibrated','after_fixed','after_calibrated')}
    perfile=[]
    with (OUT/'predictions.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f); writer.writerow(['source','time_s','label','eligible','before_valid','after_valid',
            'before_score','after_score','before_fixed','before_calibrated','after_fixed','after_calibrated'])
        for name,fault,category in specs:
            batch,eligible=load(name); b=before.score(batch); a=after.score(batch)
            raw_a=uncalibrated_after.score(batch)
            label=np.full(len(batch.time_s),fault,bool); common=b.valid&a.valid
            item={'file':name,'category':category,'policies':{}}
            alarms={}
            for key,r,threshold in [('before_fixed',b,1.),('before_calibrated',b,thresholds['before']),
                                   ('after_fixed',raw_a,1.),('after_calibrated',a,1.)]:
                alarm=score_threshold(r,batch,threshold,30); alarms[key]=alarm
                if key=='after_calibrated': np.testing.assert_array_equal(alarm,a.alarms)
                row=dict(label=label,alarm=alarm,valid=r.valid,eligible=eligible,common=common,category=category)
                allrows[key].append(row)
                item['policies'][key]={'metrics':binary_metrics(label,alarm,r.valid,eligible),
                    'unknown_reasons':dict(Counter(np.asarray(r.reasons)[eligible & ~r.valid]))}
            for i,t in enumerate(batch.time_s):
                writer.writerow([name,t,int(fault),int(eligible[i]),int(b.valid[i]),int(a.valid[i]),
                    b.scores[i] if b.valid[i] else '',raw_a.scores[i] if a.valid[i] else '',
                    *[int(alarms[k][i]) for k in allrows]])
            perfile.append(item)
            print(Path(name).stem,'valid before/after',int(b.valid.sum()),int(a.valid.sum()),flush=True)
    results={key:{'metrics':aggregate(rows),'common_valid_metrics':aggregate(rows,common=True),
        'by_category':{c:aggregate([r for r in rows if r['category']==c]) for c in sorted({r['category'] for r in rows})}}
        for key,rows in allrows.items()}
    # Reproduce original confusion counts, not merely similar rounded headline rates.
    for key,previous in [('before_fixed','default'),('before_calibrated','normal_calibrated')]:
        for metric in ('total','eligible','valid','unknown','TP','FP','TN','FN'):
            assert results[key]['metrics'][metric]==old['policies'][previous]['metrics'][metric],(key,metric)
    assert json.dumps(frozen,indent=2,sort_keys=True)==development, 'Development state changed during held-out evaluation'
    result={'schema':'equipment-diagnostics.chiller-upgrade.v1','utc':datetime.now(timezone.utc).isoformat(),
        'version':__version__,'development_sha256':hashlib.sha256(development.encode()).hexdigest(),
        'source':'https://doi.org/10.6084/m9.figshare.28435232','dataset_sha256':hashlib.sha256((DATA/'chiller'/'rp1043.zip').read_bytes()).hexdigest(),
        'baseline_counts_reproduced':True,'selected':selected,'thresholds':thresholds,'cv':cv,
        'comparison':results,'files':perfile,'data_audit':audit,
        'source_sha256':{str(q.relative_to(ROOT)):hashlib.sha256(q.read_bytes()).hexdigest() for q in
            [Path(__file__),ROOT/'scripts'/'validate_public_data.py',*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]},
        'limitations':['Single experimental chiller, public redistribution; no external machine validation.',
          'All metrics conditional on valid samples; report raw-row and eligible coverage and common-valid comparisons.',
          'Water density/cp, pressure-to-saturation and steady-state assumptions unchanged from baseline.',
          'Measured load includes water-flow and temperature signals; errors can propagate into both predictor and residual.',
          'Flow anomaly means departure from learned normal flow policy; a legitimate new flow-control strategy needs requalification.',
          'Previously evaluated holdout reused; no new blind final validation set.',
          'No fault class identification, point adjustment or IID confidence-interval claim.']}
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    render(result)
    print(json.dumps({k:v['metrics'] for k,v in results.items()},indent=2))


def render(result):
    pct=lambda v:'산출 불가' if v is None else f'{v*100:.2f}%'
    labels={'before_fixed':'개선 전·고정 한계','before_calibrated':'개선 전·정상 보정',
            'after_fixed':'개선 후·원시 점수 1','after_calibrated':'개선 후·정상 보정'}
    def table(common=False):
        rows=''
        for k,v in result['comparison'].items():
            m=v['common_valid_metrics' if common else 'metrics']
            values=[labels[k],pct(m['accuracy_valid']),pct(m['recall_valid']),pct(m['false_positive_rate_valid']),
                    pct(m['coverage']),pct(m['coverage_all_rows']),pct(m['fault_detection_all_eligible'])]
            rows+='<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in values)+'</tr>'
        return '<table><tr><th>설정</th><th>정확도</th><th>검출률</th><th>오경보율</th><th>대상 중 판단률</th><th>원본 전체 판단률</th><th>전체 대상 고장 검출률</th></tr>'+rows+'</table>'
    categories=''
    for c,m in result['comparison']['before_calibrated']['by_category'].items():
        n=result['comparison']['after_calibrated']['by_category'][c]
        values=[c,pct(m['recall_valid']),pct(n['recall_valid']),pct(m['coverage']),pct(n['coverage'])]
        categories+='<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in values)+'</tr>'
    html=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>냉동기 개선 전후 검증</title>
<style>body{{font:16px/1.65 system-ui;max-width:1300px;margin:35px auto;padding:20px;color:#193149}}table{{border-collapse:collapse;width:100%;margin:16px 0}}td,th{{border:1px solid #c6d4df;padding:10px;text-align:left}}th{{background:#eaf1f7}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.note{{background:#fff2d6;padding:16px}}</style>
<h1>냉동기: 부하·운전조건 반영 전후 비교</h1><p>{escape(result['utc'])} · v{escape(result['version'])}</p>
<p>학습 normal.xls, 보정 normal1.xls, 평가 정상 12파일·고장 23파일을 유지했습니다. 모델은 학습 파일 안에서만 구간별 교차검증으로 선택했고 임계값은 정상 보정 파일의 99백분위수입니다. 평가 시작 전에 frozen_development.json으로 동결했습니다.</p>
<p class="note">이전에 평가한 같은 시험 자료를 다시 사용한 개선 비교입니다. 새로운 설비·새로운 블라인드 시험의 성능으로 해석하지 않습니다. 기존 설정의 혼동행렬을 정확히 재현했고, UNKNOWN을 정상으로 세지 않습니다. 원본의 안정 운전 구간 선택과 물성·단위 가정은 유지했습니다.</p>
<h2>각 모듈의 판단 범위에서 비교</h2>{table()}
<h2>두 모듈이 모두 판단한 동일 표본에서 비교</h2>{table(True)}
<h2>정상 보정 설정: 고장 종류별 비교</h2><table><tr><th>종류</th><th>전 검출률</th><th>후 검출률</th><th>전 판단률</th><th>후 판단률</th></tr>{categories}</table>
<h2>바뀐 계산</h2><p>정상 전력·접근온도·유량을 냉각부하, 냉수 출구온도, 냉각수 입구온도의 함수로 예측합니다. 전력 초과, 양방향 접근온도 잔차, 정상 유량 대비 편차를 감시합니다. 유량 자체를 학습 영역 제한으로 써서 유량 고장을 모두 판단 보류하는 대신 잔차 지표로 평가합니다. 온도·부하의 정상 학습 영역 제한과 물리 입력 검사는 유지합니다.</p>
<p>참고 원리는 <a href="https://bigladdersoftware.com/epx/docs/25-2/engineering-reference/chillers.html">EnergyPlus 냉동기 성능의 부하·온도 의존성</a>이며, EnergyPlus solver 재현을 주장하지 않습니다.</p>
<h2>선택 모델·임계값</h2><pre>{escape(json.dumps({k:result[k] for k in ('selected','thresholds','cv')},ensure_ascii=False,indent=2))}</pre>
<h2>파일별 혼동행렬·판단 보류 사유</h2><pre>{escape(json.dumps(result['files'],ensure_ascii=False,indent=2))}</pre></html>'''
    (OUT/'report.html').write_text(html,encoding='utf-8')


if __name__=='__main__': main()
