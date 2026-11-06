"""Freeze alarm policy and acceptance gates before reading new plant-background dates.

Historical positive cases are explicitly reused development evidence, never a
new blind positive test. Project gates are not a certification standard.
"""
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
import numpy as np
from equipment_diagnostics import SensorBatch,ValveTrackingDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import DATA,EVENTS

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'qualification'
NEW_DATES=['30102001','31102001','02112001','03112001','04112001','05112001','06112001','07112001',
    '10112001','11112001','12112001','13112001','14112001','15112001','16112001','18112001','19112001']
OLD_DATES=['08112001','09112001','17112001','20112001','21112001','22112001']
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def metrics(rows):return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('y','alarm','valid','eligible')])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    old=json.loads((ROOT/'outputs'/'public_validation'/'valve_results.json').read_text(encoding='utf-8'))
    models={}; configs={}
    for asset in ('A1','A3'):
        p=old['tuning'][asset];models[asset]={}
        for key,persistence in [('baseline',3.),('sustained',10.)]:
            models[asset][key]=ValveTrackingDiagnostic(dict(command='command',position='position'),
                error_limit_fraction=p['error_limit_fraction'],delay_s=p['delay_s'],persistence_s=persistence)
        configs[asset]={'schema':'equipment-diagnostics.config.v1','clock_id':'damadics_seconds_from_midnight',
            'asset_id':asset,'origin':'historian_measured','units':{'command':'1','position':'1'},
            'diagnostics':[{'id':'persistent_tracking','kind':'valve_tracking','channels':dict(command='command',position='position'),
                'parameters':models[asset]['sustained'].params,'alarm':{'persistence_s':10.}}]}
    code=[Path(__file__),ROOT/'scripts'/'validate_public_data.py',*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in code}
    # Technical monitoring gates chosen for this study, not imported from a standard.
    gates=dict(new_background_fpr_max=.001,new_background_coverage_min=.999,
        worst_asset_day_fpr_max=.005,alarm_episode_rate_per_24h_max=5.,worst_asset_day_alarm_episodes_max=10,
        historical_fault_event_recall_min=1.,historical_fault_sample_recall_min=.85,historical_detection_delay_max_s=30.)
    frozen={'version':__version__,'scope':'DAMADICS A1/A3 command-position persistent tracking monitoring only',
        'new_background_dates':NEW_DATES,'historical_positive_replay_dates':OLD_DATES,
        'train_date':'29102001','calibration_date':'01112001','configurations':configs,'gates':gates,
        'source_sha256':hashes,'data_sha256':{str(p.relative_to(ROOT)):digest(p) for p in sorted((DATA/'damadics').glob('*.zip'))},
        'policy':'Retain original normal-only delay and q99 position-error limits; increase persistence from3 to10 seconds. '
            'No new-background values inspected before freezing. All results reported, no post-test changes.',
        'positive_evidence_note':'Six f16 faults already used in past development. No new independent positive faults available.',
        'background_note':'No documented injected target fault; not certified healthy by maintenance.',
        'exclusions':[{'asset':'A1','date':'30102001','start':58800,'end':59800,'fault':'f18'},
                      {'asset':'A3','date':'30102001','start':57340,'end':57890,'fault':'f18'}]}
    path=OUT/'frozen_protocol.json';path.write_bytes(json.dumps(frozen,indent=2,sort_keys=True).encode());frozen_hash=digest(path)
    assert len(set(NEW_DATES+OLD_DATES+['29102001','01112001']))==25
    archives=[zipfile.ZipFile(DATA/'damadics'/f'part{i}.zip') for i in range(1,5)]
    lookup={Path(n).stem:(z,n) for z in archives for n in z.namelist() if n.endswith('.txt')}
    assert set(lookup)==set(NEW_DATES+OLD_DATES+['29102001','01112001'])
    rows={cohort:{policy:[] for policy in ('baseline','sustained')} for cohort in ('new_background','historical_replay')}
    files=[];events=[]
    with (OUT/'predictions.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['cohort','asset','date','time_s','label','eligible','valid','baseline_alarm','sustained_alarm'])
        for date in NEW_DATES+OLD_DATES:
            z,name=lookup[date];x=np.loadtxt(io.BytesIO(z.read(name)))
            cohort='new_background' if date in NEW_DATES else 'historical_replay'
            for asset,cols in [('A1',[5,6]),('A3',[27,28])]:
                b=SensorBatch(x[:,0],x[:,cols]/100,('command','position'),('1','1'),
                    'damadics_seconds_from_midnight',asset,'historian_measured',metadata={'source_date':date})
                t=b.time_s;y=np.zeros(len(t),bool);excluded=y.copy()
                evs=[e for e in EVENTS if e[0]==asset and e[1]==date]
                evs += [(asset,date,e['start'],e['end'],e['fault']) for e in frozen['exclusions'] if e['asset']==asset and e['date']==date]
                for _,_,start,end,fault in evs:
                    if fault=='f16':y|=(t>=start)&(t<=end)
                    else:excluded|=(t>=start)&(t<=end)
                eligible=~excluded;results={key:m.score(b) for key,m in models[asset].items()}
                np.testing.assert_array_equal(results['baseline'].valid,results['sustained'].valid)
                item={'cohort':cohort,'date':date,'asset':asset,'policies':{}}
                for key,r in results.items():
                    row=dict(y=y,alarm=r.alarms,valid=r.valid,eligible=eligible);rows[cohort][key].append(row)
                    a=r.alarms&eligible&r.valid
                    # Count starts inside eligible observation runs, never merge across invalid/excluded rows.
                    starts=a&~np.r_[False,a[:-1]]
                    normal=eligible&r.valid&~y;normal_alarm=a&~y
                    normal_starts=normal_alarm&~np.r_[False,normal_alarm[:-1]]
                    item['policies'][key]={'metrics':metrics([row]),'normal_alarm_episodes':int(normal_starts.sum()),
                        'normal_valid_seconds':int(normal.sum()),'alarm_episodes':int(starts.sum())}
                    for _,_,start,end,fault in evs:
                        if fault!='f16':continue
                        hits=np.flatnonzero((t>=start)&(t<=end)&r.valid&r.alarms)
                        events.append(dict(policy=key,asset=asset,date=date,start=start,end=end,detected=bool(len(hits)),
                            delay_s=float(t[hits[0]]-start) if len(hits) else None))
                for i,time in enumerate(t):w.writerow([cohort,asset,date,time,int(y[i]),int(eligible[i]),int(results['baseline'].valid[i]),
                    int(results['baseline'].alarms[i]),int(results['sustained'].alarms[i])])
                files.append(item);print(date,asset,cohort,flush=True)
    comparison={cohort:{key:metrics(group) for key,group in policies.items()} for cohort,policies in rows.items()}
    for k in ('total','eligible','valid','unknown','TP','FN','FP','TN'):
        assert comparison['historical_replay']['baseline'][k]==old['policies']['normal_calibrated']['metrics'][k],k
    decisions={}
    for policy in ('baseline','sustained'):
        m=comparison['new_background'][policy];h=comparison['historical_replay'][policy]
        cohort_files=[f['policies'][policy] for f in files if f['cohort']=='new_background']
        episodes=sum(v['normal_alarm_episodes'] for v in cohort_files)
        hours=sum(v['normal_valid_seconds'] for v in cohort_files)/3600
        rate=episodes/(hours/24)
        ev=[e for e in events if e['policy']==policy]
        checks={'new_background_fpr':m['false_positive_rate_valid']<=gates['new_background_fpr_max'],
            'new_background_coverage':m['coverage']>=gates['new_background_coverage_min'],
            'worst_asset_day_fpr':max(v['metrics']['false_positive_rate_valid'] for v in cohort_files)<=gates['worst_asset_day_fpr_max'],
            'alarm_episode_rate':rate<=gates['alarm_episode_rate_per_24h_max'],
            'worst_asset_day_episodes':max(v['normal_alarm_episodes'] for v in cohort_files)<=gates['worst_asset_day_alarm_episodes_max'],
            'historical_event_recall':sum(e['detected'] for e in ev)/len(ev)>=gates['historical_fault_event_recall_min'],
            'historical_sample_recall':h['recall_valid']>=gates['historical_fault_sample_recall_min'],
            'historical_detection_delay':all(e['detected'] and e['delay_s']<=gates['historical_detection_delay_max_s'] for e in ev)}
        decisions[policy]={'passes_project_monitoring_gates':all(checks.values()),'checks':checks,
            'new_background_alarm_episodes':episodes,'new_background_normal_hours':hours,'normal_alarm_episodes_per_24h':rate,
            'status_scope':'Measured benchmark monitoring gates only; no independent positive or new-site qualification.'}
    assert digest(path)==frozen_hash and hashes=={str(p.relative_to(ROOT)):digest(p) for p in code}
    result={'version':__version__,'schema':'equipment-diagnostics.valve-monitor-qualification.v1','protocol_sha256':frozen_hash,
        'source_sha256':hashes,'comparison':comparison,'decisions':decisions,'events':events,'files':files,
        'new_background_asset_days':34,'new_independent_positive_tests':0,'baseline_counts_reproduced':True,
        'limitations':['Same factory, same two valves. New dates are independent of prior train/cal/test files, not independent sites.',
            'Background labels mean no documented injected target fault, not independently certified healthy operation.',
            'Historical positive events are development/replay evidence, not blind positive qualification.',
            'No operating-safety approval or universal fault diagnosis claim. Passing gates is a project criterion, not a standard.',
            'Episode counts depend on 1Hz sampling and emitted alarm runs; episodes may be multiple responses to one underlying cause.']}
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (OUT/'configs').mkdir(exist_ok=True)
    for asset,cfg in configs.items():(OUT/'configs'/f'{asset}_persistent_tracking.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    print(json.dumps({'comparison':comparison,'decisions':decisions},indent=2))

if __name__=='__main__':main()
