"""Normal-only dynamic model selection, separate calibration and reused plant holdout."""
from collections import Counter
from datetime import datetime,timezone
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
import numpy as np
from equipment_diagnostics import SensorBatch,ValveTrackingDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import DATA,PROTOCOL,EVENTS

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'/'quick_improvements'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def aggregate(rows,common=False):
    return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in
        ('label','alarm','common' if common else 'valid','eligible')])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    old=json.loads((ROOT/'outputs'/'public_validation'/'valve_results.json').read_text(encoding='utf-8'))
    archives=[zipfile.ZipFile(DATA/'damadics'/f'part{i}.zip') for i in range(1,5)]
    lookup={Path(n).stem:(z,n) for z in archives for n in z.namelist() if n.endswith('.txt')}; cache={}
    def load(date,asset,cols):
        if date not in cache:
            z,name=lookup[date]; cache[date]=np.loadtxt(io.BytesIO(z.read(name)))
        x=cache[date]
        return SensorBatch(x[:,0],x[:,cols]/100,('command','position'),('1','1'),
            'damadics_seconds_from_midnight',asset,'historian_measured',metadata={'source_date':date})
    p=PROTOCOL['valve']; channels=dict(command='command',position='position')
    selected={}; models={}; development={}
    for asset,cols in p['actuators'].items():
        train=load(p['train'],asset,cols); cal=load(p['calibration'],asset,cols)
        delay=old['tuning'][asset]['delay_s']
        candidates=[]; errors=[]; masks=[]
        for tau in (0.,.5,1.,2.,4.,8.):
            m=ValveTrackingDiagnostic(channels,error_limit_fraction=.04,delay_s=delay,
                response_time_s=tau,persistence_s=3)
            r=m.score(train); candidates.append(m)
            errors.append(abs(r.metrics['tracking_error_fraction'])); masks.append(r.valid)
            print(asset,'train candidate tau',tau,flush=True)
        common=np.logical_and.reduce(masks)
        if common.sum()<100: raise ValueError('insufficient common normal training data')
        maes=[float(e[common].mean()) for e in errors]; winner=int(np.argmin(maes))
        baseline=ValveTrackingDiagnostic(channels,error_limit_fraction=old['tuning'][asset]['error_limit_fraction'],
            delay_s=delay,persistence_s=3)
        chosen=candidates[winner]; r=chosen.score(cal)
        threshold=max(.005,float(np.quantile(abs(r.metrics['tracking_error_fraction'][r.valid]),.99)))
        upgraded=ValveTrackingDiagnostic(channels,error_limit_fraction=threshold,delay_s=delay,
            response_time_s=chosen.response_time,persistence_s=3)
        models[asset]=[baseline,upgraded]
        selected[asset]={'delay_s':delay,'tau_s':chosen.response_time,'error_limit_fraction':threshold}
        development[asset]={'train_fingerprint':train.fingerprint,'calibration_fingerprint':cal.fingerprint,
            'train_mae_common':[{'tau_s':m.response_time,'mae':mae} for m,mae in zip(candidates,maes)],
            'train_common_samples':int(common.sum()),'selected':selected[asset],
            'baseline_params':baseline.params,'after_params':upgraded.params}
    assert p['train']!=p['calibration'] and not {p['train'],p['calibration']}&set(p['test'])
    code_files=[Path(__file__),ROOT/'scripts'/'validate_public_data.py',*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]
    source_hashes={str(q.relative_to(ROOT)):digest(q) for q in code_files}
    frozen={'schema':'equipment-diagnostics.valve-dynamic-development.v1','version':__version__,'split':p,
        'assets':development,'source_sha256':source_hashes,
        'data_sha256':{str(q.relative_to(ROOT)):digest(q) for q in sorted((DATA/'damadics').glob('*.zip'))},
        'policy':'Existing normal-train-selected delay retained. Tau chosen by common-valid normal training MAE; '
            'separate normal-calibration q99 absolute error, floor .005, persistence 3s. No test tuning.',
        'reuse_note':'Previously examined evaluation dates reused; not new blind validation.'}
    path=OUT/'valve_frozen.json'; path.write_bytes(json.dumps(frozen,sort_keys=True,indent=2).encode())
    frozen_hash=digest(path); rows={'before':[],'after':[]}; files=[]; events=[]
    with (OUT/'valve_predictions.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(['asset','date','time_s','label','eligible','before_valid','before_alarm','after_valid','after_alarm'])
        for date in p['test']:
            for asset,cols in p['actuators'].items():
                b=load(date,asset,cols); t=b.time_s
                label=np.zeros(len(t),bool); other=label.copy()
                evs=[e for e in EVENTS if e[0]==asset and e[1]==date]
                for _,_,start,end,code in evs:
                    if code=='f16': label|=(t>=start)&(t<=end)
                    else: other|=(t>=start)&(t<=end)
                eligible=~other; results=[m.score(b) for m in models[asset]]
                common=results[0].valid&results[1].valid
                item={'asset':asset,'date':date,'policies':{}}
                for key,r in zip(rows,results):
                    row=dict(label=label,alarm=r.alarms,valid=r.valid,common=common,eligible=eligible,asset=asset)
                    rows[key].append(row); item['policies'][key]={'metrics':binary_metrics(label,r.alarms,r.valid,eligible),
                        'unknown_reasons':dict(Counter(np.asarray(r.reasons)[eligible&~r.valid]))}
                    for _,_,start,end,code in evs:
                        if code!='f16': continue
                        hits=np.flatnonzero((t>=start)&(t<=end)&r.valid&r.alarms)
                        events.append(dict(policy=key,asset=asset,date=date,start=start,end=end,
                            detected=bool(len(hits)),delay_s=float(t[hits[0]]-start) if len(hits) else None))
                files.append(item)
                for i,time in enumerate(t):
                    w.writerow([asset,date,time,int(label[i]),int(eligible[i]),
                        *[v for r in results for v in (int(r.valid[i]),int(r.alarms[i]))]])
                print('evaluated',asset,date,flush=True)
    comparison={k:{'metrics':aggregate(v),'common_metrics':aggregate(v,True),
        'by_asset':{a:aggregate([r for r in v if r['asset']==a]) for a in models}} for k,v in rows.items()}
    for key in ('total','eligible','valid','unknown','TP','FN','FP','TN'):
        assert comparison['before']['metrics'][key]==old['policies']['normal_calibrated']['metrics'][key],key
    assert digest(path)==frozen_hash
    assert source_hashes=={str(q.relative_to(ROOT)):digest(q) for q in code_files}
    result={'schema':'equipment-diagnostics.valve-dynamics.v1','version':__version__,'utc':datetime.now(timezone.utc).isoformat(),
        'selected':selected,'comparison':comparison,'files':files,'events':events,
        'baseline_counts_reproduced':True,'frozen_sha256':frozen_hash,'source_sha256':source_hashes,
        'limitations':['Actual factory data, two valves, six documented f16 events only.',
            'Reused evaluation dates, not new blind validation; no test-based tuning.',
            'Other documented fault windows excluded, unrecorded natural faults may contaminate background labels.',
            'First-order dynamics assume linear command interpolation and constant tau; rate limiting/stiction not identified.',
            'Segment initialization uses measured position, followed by 5*tau warmup. Faults at startup can be temporarily hidden.',
            'Sample-level metrics with UNKNOWN excluded, event detections separately listed.']}
    (OUT/'valve_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v['metrics'] for k,v in comparison.items()},indent=2))

if __name__=='__main__': main()
