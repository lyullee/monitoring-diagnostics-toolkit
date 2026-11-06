"""Recount measured and simulated comparisons without the library metric function."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'/'quick_improvements'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def count(c,y,a,v,e):
    c['total']+=1; c['eligible' if e else 'excluded']+=1
    if not e: return
    c['fault_eligible' if y else 'normal_eligible']+=1
    if not v: c['unknown']+=1; return
    c['valid']+=1; c['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
def check(c,m):
    for k in ('total','eligible','excluded','valid','unknown','TP','FN','FP','TN'): assert c[k]==m[k],(k,c[k],m[k])
    for k,n,d in [('accuracy_valid',c['TP']+c['TN'],c['valid']),
                  ('recall_valid',c['TP'],c['TP']+c['FN']),('false_positive_rate_valid',c['FP'],c['FP']+c['TN']),
                  ('coverage',c['valid'],c['eligible']),('coverage_all_rows',c['valid'],c['total'])]:
        assert m[k]==(n/d if d else None),k

def main():
    results={}
    for kind in ('physics','valve'):
        result=json.loads((OUT/f'{kind}_results.json').read_text(encoding='utf-8'))
        frozen_path=OUT/f'{kind}_frozen.json'; frozen=json.loads(frozen_path.read_text(encoding='utf-8'))
        assert digest(frozen_path)==result['frozen_sha256']
        for name,h in result['source_sha256'].items(): assert digest(ROOT/name)==h,name
        aggregate={k:Counter() for k in ('before','after')}; common={k:Counter() for k in aggregate}
        groups={}; sources=set()
        with (OUT/f'{kind}_predictions.csv').open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                group=row['scenario'] if kind=='physics' else row['asset']+'/'+row['date']
                sources.add(group); gs=groups.setdefault(group,{k:Counter() for k in aggregate})
                y=row['label']=='1'; e=row['eligible']=='1'
                vs=[row[k+'_valid']=='1' for k in aggregate]
                for i,k in enumerate(aggregate):
                    a=row[k+'_alarm']=='1'; assert not a or vs[i]
                    count(aggregate[k],y,a,vs[i],e); count(common[k],y,a,all(vs),e); count(gs[k],y,a,vs[i],e)
        if kind=='valve':
            for k in aggregate:
                check(aggregate[k],result['comparison'][k]['metrics']); check(common[k],result['comparison'][k]['common_metrics'])
            for item in result['files']:
                for k in aggregate: check(groups[item['asset']+'/'+item['date']][k],item['policies'][k]['metrics'])
            p=frozen['split']
            assert p['train']!=p['calibration'] and not {p['train'],p['calibration']}&set(p['test'])
            assert sources=={a+'/'+d for a in p['actuators'] for d in p['test']}
            for asset,v in frozen['assets'].items():
                assert v['train_fingerprint']!=v['calibration_fingerprint']
            for name,h in frozen['data_sha256'].items(): assert digest(ROOT/name)==h,name
            old=json.loads((ROOT/'outputs'/'public_validation'/'valve_results.json').read_text(encoding='utf-8'))
            check(aggregate['before'],old['policies']['normal_calibrated']['metrics'])
        else:
            for item in result['scenarios']:
                for k in aggregate: check(groups[item['scenario']][k],item['policies'][k]['metrics'])
            h=frozen['hydraulic']
            assert len({h['train_seed'],h['calibration_seed'],*h['test_seeds']})==4
            assert h['train_fingerprint']!=h['calibration_fingerprint']
            assert not {h['train_fingerprint'],h['calibration_fingerprint']}&{s['fingerprint'] for s in result['scenarios']}
        results[kind]={'results_sha256':digest(OUT/f'{kind}_results.json'),
            'predictions_sha256':digest(OUT/f'{kind}_predictions.csv'),'counts':{k:dict(v) for k,v in aggregate.items()}}
    report={'successful':True,'counts_rates_common_samples_verified':True,'sources_and_frozen_protocols_verified':True,
        'disjoint_train_calibration_test_verified':True,'baseline_valve_counts_reproduced':True,'evaluations':results}
    (OUT/'independent_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
