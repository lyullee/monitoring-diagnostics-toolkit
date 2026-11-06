"""Freeze four cumulative normal-only models, then evaluate the unchanged 35 runs."""
from collections import Counter
from datetime import datetime,timezone
from html import escape
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import ChillerPerformanceDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import chiller,PROTOCOL,DATA
from validate_chiller_upgrade import CHANNELS

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'chiller_stages'
LABELS=['0 · 부하·운전조건 모델','1 · 오일·과냉·과열 잔차 추가',
        '2 · 전체 잔차에 EWMA 적용','3 · 응축기 지표 추가']
EXTRA=dict(oil_sump_temperature='oil_sump',oil_feed_temperature='oil_feed',
           oil_feed_pressure='oil_feed_p',oil_net_pressure='oil_net_p',
           subcooling='subcool',suction_superheat='suction_sh',discharge_superheat='discharge_sh')

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def aggregate(rows,mask='valid'):
    return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm',mask,'eligible')])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    p=PROTOCOL['chiller']; load,audit=chiller(loader_only=True,extended_sensors=True)
    train,_=load('Chiller Data/Benchmark Tests/'+p['train'])
    cal,_=load('Chiller Data/Benchmark Tests/'+p['calibration'])
    models=[]
    for stage in range(4):
        channels={**CHANNELS,'cooling_in':'tci'}
        if stage: channels.update(EXTRA)
        if stage==3: channels['cooling_flow']='cw_flow'
        m=ChillerPerformanceDiagnostic(channels,reference_mode='conditioned',diagnostic_stage=stage,
            regression_degree=1,ridge_alpha=.001,persistence_s=30,ewma_tau_s=60,ewma_warmup_s=180)
        m.fit(train).calibrate(cal,quantile=.99)
        models.append(m)
    specs=[('Chiller Data/Benchmark Tests/'+n+'.xls',False,'normal') for n in p['normal_test']]
    specs += [('Chiller Data/'+c+'/'+n+'.xls',True,c) for c,names in p['fault_test'].items() for n in names]
    assert not {p['train'],p['calibration']} & {Path(n).name for n,_,_ in specs}
    assert p['train']!=p['calibration'] and len(set(n for n,_,_ in specs))==35
    code=[Path(__file__),ROOT/'scripts'/'validate_public_data.py',ROOT/'scripts'/'validate_chiller_upgrade.py',
          *sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]
    frozen={'schema':'equipment-diagnostics.chiller-stages-development.v1','utc':datetime.now(timezone.utc).isoformat(),
        'split':p,'test_files':[n for n,_,_ in specs],
        'train_fingerprint':train.fingerprint,'calibration_fingerprint':cal.fingerprint,
        'dataset_sha256':digest(DATA/'chiller'/'rp1043.zip'),
        'source_sha256':{str(q.relative_to(ROOT)):digest(q) for q in code},
        'policy':'Cumulative stages 0..3; degree=1 ridge=.001 retained from prior normal-only CV; '
            'q=.99 separate normal calibration per stage; 30s persistence; signed EWMA tau=60s warmup=180s. '
            'No fault/test data for model, parameter or threshold selection.',
        'reuse_note':'Previously examined holdout reused; development-round comparison, not new blind qualification.',
        'stages':{str(i):{'label':LABELS[i],'params':m.params,'reference':m.reference} for i,m in enumerate(models)}}
    frozen_path=OUT/'frozen_development.json'
    frozen_path.write_bytes(json.dumps(frozen,indent=2,sort_keys=True).encode('utf-8'))
    frozen_hash=digest(frozen_path)
    reference_snapshots=[json.dumps(m.reference,sort_keys=True) for m in models]
    # No held-out run is loaded until all four model references have been frozen above.
    allrows={str(i):[] for i in range(4)}; files=[]
    with (OUT/'predictions.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['source','time_s','label','eligible',*[f'stage{i}_{k}' for i in range(4) for k in ('valid','score','alarm')]])
        for name,fault,category in specs:
            batch,eligible=load(name); results=[m.score(batch) for m in models]
            common=np.logical_and.reduce([r.valid for r in results])
            item={'file':name,'category':category,'stages':{}}
            for i,r in enumerate(results):
                row=dict(label=np.full(len(batch.time_s),fault,bool),alarm=r.alarms,valid=r.valid,
                    common=common,eligible=eligible,category=category)
                for j,s in enumerate(results): row[f'pair{j}']=r.valid&s.valid
                allrows[str(i)].append(row)
                item['stages'][str(i)]={'metrics':aggregate([row]),
                    'unknown_reasons':dict(Counter(np.asarray(r.reasons)[eligible&~r.valid]))}
            for k,t in enumerate(batch.time_s):
                writer.writerow([name,t,int(fault),int(eligible[k]),
                    *[v for r in results for v in (int(r.valid[k]),r.scores[k] if r.valid[k] else '',int(r.alarms[k]))]])
            files.append(item)
            print(Path(name).stem,'valid:',*[int(r.valid.sum()) for r in results],flush=True)
    comparison={key:{'metrics':aggregate(rows),'common_valid_metrics':aggregate(rows,'common'),
        'by_category':{c:aggregate([r for r in rows if r['category']==c]) for c in sorted({r['category'] for r in rows})}}
        for key,rows in allrows.items()}
    pairs={f'{i-1}_to_{i}':{'before':aggregate(allrows[str(i-1)],f'pair{i}'),
        'after':aggregate(allrows[str(i)],f'pair{i-1}')} for i in range(1,4)}
    old=json.loads((ROOT/'outputs'/'chiller_upgrade'/'results.json').read_text(encoding='utf-8'))
    for metric in ('total','eligible','valid','unknown','TP','FP','TN','FN'):
        assert comparison['0']['metrics'][metric]==old['comparison']['after_calibrated']['metrics'][metric],metric
    assert digest(frozen_path)==frozen_hash
    assert reference_snapshots==[json.dumps(m.reference,sort_keys=True) for m in models]
    assert frozen['source_sha256']=={str(q.relative_to(ROOT)):digest(q) for q in code}
    result={'schema':'equipment-diagnostics.chiller-stages.v1','version':__version__,'utc':datetime.now(timezone.utc).isoformat(),
        'development_sha256':frozen_hash,'source':'https://doi.org/10.6084/m9.figshare.28435232',
        'dataset_sha256':frozen['dataset_sha256'],'source_sha256':frozen['source_sha256'],
        'baseline_counts_reproduced':True,'comparison':comparison,'adjacent_common_valid':pairs,
        'files':files,'data_audit':audit,'thresholds':{str(i):m.reference['score_calibration'] for i,m in enumerate(models)},
        'limitations':['Single experimental chiller; publicly redistributed observations, not independent field validation.',
            'Reused evaluation files; this is not a new blind test. No test-based tuning in this run.',
            'Binary detection, not fault-class identification. UNKNOWN is excluded from conditional accuracy/recall/FPR.',
            'Stage 2/3 warmup and extra sensors reduce coverage; common-valid cohorts and all-eligible recall are reported.',
            'Oil-control policy/charge differed between some healthy runs; no retraining on these test runs.',
            'UA is apparent: uses measured water duty and isothermal saturation-temperature LMTD; not an exact condenser solver.',
            'Water cp/density and R134a saturation conversion assumptions unchanged; subcool/superheat channels are derived measurements.',
            'EWMA resets on invalid input/gaps/episode or mode changes. Streaming replays full history with an explicit sample cap.']}
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    render(result)
    print(json.dumps({k:v['metrics'] for k,v in comparison.items()},indent=2))

def render(result):
    pct=lambda x:'—' if x is None else f'{100*x:.2f}%'
    cols=('accuracy_valid','recall_valid','false_positive_rate_valid','coverage','coverage_all_rows','fault_detection_all_eligible')
    headers=['단계','정확도','검출률','오경보율','대상 중 판단률','원본 전체 판단률','전체 대상 고장 검출률']
    def table(common=False):
        rows=[]
        for k,v in result['comparison'].items():
            m=v['common_valid_metrics' if common else 'metrics']
            rows.append([LABELS[int(k)],*[pct(m[c]) for c in cols]])
        return tab(headers,rows)
    def tab(head,rows):
        return '<table><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in head)+'</tr>'+''.join(
            '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    deltas=[]
    for i in range(1,4):
        b=result['comparison'][str(i-1)]['metrics']; a=result['comparison'][str(i)]['metrics']
        deltas.append([f'{i-1} → {i}',*[f'{100*(a[c]-b[c]):+.2f} %p' for c in cols[:4]]])
    bycat=[]
    for c in result['comparison']['0']['by_category']:
        bycat.append([c,*[pct(result['comparison'][str(i)]['by_category'][c]['recall_valid'])+' / '+
                         pct(result['comparison'][str(i)]['by_category'][c]['coverage']) for i in range(4)]])
    pair_rows=[]
    for k,v in result['adjacent_common_valid'].items():
        for label,m in v.items(): pair_rows.append([k+' '+label,*[pct(m[c]) for c in cols]])
    html='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>냉동기 단계별 검증</title>
<style>body{font:16px/1.6 system-ui;max-width:1450px;margin:30px auto;padding:20px;color:#193149}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #c6d4df;padding:9px;text-align:left}th{background:#eaf1f7}pre{white-space:pre-wrap;overflow-wrap:anywhere}.note{background:#fff2d6;padding:16px}</style>
<h1>냉동기 진단: 순차 구현·검증</h1><p>학습 normal.xls · 보정 normal1.xls · 평가 정상 12파일 / 고장 23파일. 모든 단계의 모델·정상 보정 임계값을 평가 전에 동결했습니다.</p>
<p class="note">같은 실험 냉동기 자료를 재사용한 개발 비교입니다. 새로운 블라인드 시험이나 다른 현장 설비의 정확도를 보장하지 않습니다. 추가 단계가 나빠지는 결과도 그대로 보고합니다. 판단 보류는 정상으로 세지 않습니다.</p>
<h2>단계별 판단 범위</h2>'''+table()+ '<h2>직전 단계 대비 변화</h2>'+tab(headers[:5],deltas)+ \
        '<h2>네 단계가 모두 판단한 동일 표본</h2>'+table(True)+ \
        '<h2>인접 단계가 함께 판단한 표본</h2>'+tab(headers,pair_rows)+ \
        '<h2>고장 종류별 검출률 / 판단률</h2>'+tab(['고장 종류',*LABELS],bycat)+ \
        '<h2>해석 범위와 제한</h2><ul>'+''.join('<li>'+escape(v)+'</li>' for v in result['limitations'])+ \
        '</ul><h2>정상 보정 임계값</h2><pre>'+escape(json.dumps(result['thresholds'],indent=2))+ \
        '</pre><h2>파일별 혼동행렬·보류 사유</h2><pre>'+escape(json.dumps(result['files'],ensure_ascii=False,indent=2))+'</pre></html>'
    (OUT/'report.html').write_text(html,encoding='utf-8')

if __name__=='__main__': main()
