"""Rank 8: predeclared refrigerant-state conditioning; unchanged train/cal/holdouts."""
import csv,json,hashlib
from pathlib import Path
import numpy as np
from equipment_diagnostics import ChillerPerformanceDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import chiller,PROTOCOL,DATA
from validate_chiller_upgrade import CHANNELS
from validate_chiller_stages import EXTRA

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'/'completion_7_13'/'chiller'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def aggregate(rows): return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm','valid','eligible')])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    load,audit=chiller(loader_only=True,extended_sensors=True); p=PROTOCOL['chiller']
    train,_=load('Chiller Data/Benchmark Tests/'+p['train'])
    cal,_=load('Chiller Data/Benchmark Tests/'+p['calibration'])
    old=json.loads((ROOT/'outputs/chiller_stages/frozen_development.json').read_text(encoding='utf-8'))
    models={}
    for i in (0,1):
        ref=old['stages'][str(i)]
        m=ChillerPerformanceDiagnostic({**CHANNELS,'cooling_in':'tci',**(EXTRA if i else {})},**ref['params'],persistence_s=30)
        m.set_reference(ref['reference']);models['stage'+str(i)]=m
    candidate=ChillerPerformanceDiagnostic({**CHANNELS,'cooling_in':'tci',**EXTRA},
        reference_mode='conditioned',diagnostic_stage=1,regression_degree=1,ridge_alpha=.001,
        auxiliary_conditioning='water_refrigerant',persistence_s=30)
    candidate.fit(train).calibrate(cal,quantile=.99);models['candidate']=candidate
    specs=[('Chiller Data/Benchmark Tests/'+n+'.xls',False,'normal') for n in p['normal_test']]
    specs += [('Chiller Data/'+c+'/'+n+'.xls',True,c) for c,names in p['fault_test'].items() for n in names]
    frozen=dict(version=__version__,params=candidate.params,reference=candidate.reference,
        train_fingerprint=train.fingerprint,calibration_fingerprint=cal.fingerprint,test_files=[n for n,_,_ in specs],
        policy='Degree1/ridge.001, five water/refrigerant features, q99 normal calibration; no fault/test selection.',
        reuse='35 previously inspected test files; developmental reused evaluation, not independent qualification',
        source_sha256={str(q.relative_to(ROOT)):sha(q) for q in sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))},
        dataset_sha256=sha(DATA/'chiller/rp1043.zip'))
    fp=OUT/'frozen.json';fp.write_text(json.dumps(frozen,indent=2),encoding='utf-8');h=sha(fp)
    rows={k:[] for k in models};files=[]
    with (OUT/'predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['source','time_s','label','eligible',*[k+'_'+v for k in models for v in ('valid','alarm','score')]])
        for name,fault,category in specs:
            b,e=load(name);rr={k:m.score(b) for k,m in models.items()}
            for k,r in rr.items():rows[k].append(dict(label=np.full(len(e),fault),eligible=e,valid=r.valid,alarm=r.alarms,category=category))
            for i,t in enumerate(b.time_s):w.writerow([name,t,int(fault),int(e[i]),*[x for r in rr.values() for x in (int(r.valid[i]),int(r.alarms[i]),r.scores[i] if r.valid[i] else '')]])
            files.append(dict(file=name,category=category,metrics={k:aggregate([rows[k][-1]]) for k in models}))
    metrics={k:aggregate(r) for k,r in rows.items()}
    # Refuse to relabel historical populations or silently change prior baselines.
    baseline=json.loads((ROOT/'outputs/chiller_stages/results.json').read_text(encoding='utf-8'))
    for k in ('stage0','stage1'):
        for c in ('eligible','valid','TP','FP','TN','FN'):
            assert metrics[k][c]==baseline['comparison'][k[-1]]['metrics'][c],(k,c)
    assert sha(fp)==h
    after=metrics['candidate']; before=metrics['stage0']
    adopt=(after['recall_valid']>=before['recall_valid'] and after['false_positive_rate_valid']<=before['false_positive_rate_valid'] and after['coverage']>=before['coverage'])
    result=dict(version=__version__,evidence='reused measured laboratory data',frozen_sha256=h,
        comparison=metrics,files=files,candidate_adopted=adopt,by_category={k:{c:aggregate([x for x in r if x['category']==c]) for c in sorted({x['category'] for x in r})} for k,r in rows.items()},
        limitation='Refrigerant-state conditioning can hide faults changing these predictors. No oil fault root-cause claim. Same single RP1043 chiller.',
        new_independent_fault_metrics=None)
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(comparison=metrics,adopt=adopt),indent=2))
if __name__=='__main__':main()
