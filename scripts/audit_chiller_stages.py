"""Independent stdlib-only counts, rates, split and artifact integrity audit."""
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'chiller_stages'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    result=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    stages=range(4); actual=[Counter() for _ in stages]; common=[Counter() for _ in stages]
    pairs={f'{i-1}_to_{i}':{'before':Counter(),'after':Counter()} for i in range(1,4)}
    sources=set(); perfile={}; last_time={}
    def count(c,y,a,v,e):
        c['total']+=1
        c['excluded' if not e else 'eligible']+=1
        if not e: return
        c['fault_eligible' if y else 'normal_eligible']+=1
        if not v:
            c['unknown']+=1; c['fault_unknown' if y else 'normal_unknown']+=1; return
        c['valid']+=1
        c['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
    with (OUT/'predictions.csv').open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            name=r['source']; sources.add(name); t=float(r['time_s'])
            assert name not in last_time or t>last_time[name]
            last_time[name]=t
            y=r['label']=='1'; e=r['eligible']=='1'
            vs=[r[f'stage{i}_valid']=='1' for i in stages]
            alarms=[r[f'stage{i}_alarm']=='1' for i in stages]
            file_counts=perfile.setdefault(name,[Counter() for _ in stages])
            for i in stages:
                assert not vs[i] or e
                assert not alarms[i] or vs[i]
                assert bool(r[f'stage{i}_score'])==vs[i]
                count(actual[i],y,alarms[i],vs[i],e)
                count(common[i],y,alarms[i],all(vs),e)
                count(file_counts[i],y,alarms[i],vs[i],e)
            for i in range(1,4):
                for side,j in [('before',i-1),('after',i)]:
                    count(pairs[f'{i-1}_to_{i}'][side],y,alarms[j],vs[i-1] and vs[i],e)
    def check(c,m):
        for k in ('total','excluded','eligible','fault_eligible','normal_eligible','unknown','normal_unknown','fault_unknown',
                  'valid','TP','FN','FP','TN'): assert c[k]==m[k],(k,c[k],m[k])
        rates={'coverage':(c['valid'],c['eligible']),'coverage_all_rows':(c['valid'],c['total']),
            'accuracy_valid':(c['TP']+c['TN'],c['valid']),'recall_valid':(c['TP'],c['TP']+c['FN']),
            'false_positive_rate_valid':(c['FP'],c['FP']+c['TN']),
            'fault_detection_all_eligible':(c['TP'],c['fault_eligible'])}
        for k,(n,d) in rates.items(): assert m[k]==(n/d if d else None),k
    for i in stages:
        check(actual[i],result['comparison'][str(i)]['metrics'])
        check(common[i],result['comparison'][str(i)]['common_valid_metrics'])
    for key,v in pairs.items():
        for side,c in v.items(): check(c,result['adjacent_common_valid'][key][side])
    for item in result['files']:
        for i in stages: check(perfile[item['file']][i],item['stages'][str(i)]['metrics'])
    frozen=json.loads((OUT/'frozen_development.json').read_text(encoding='utf-8'))
    assert digest(OUT/'frozen_development.json')==result['development_sha256']
    assert sources==set(frozen['test_files']) and len(sources)==35
    split=frozen['split']; tests={Path(s).name for s in sources}
    assert len(tests)==35 and split['train']!=split['calibration']
    assert not {split['train'],split['calibration']}&tests
    assert frozen['train_fingerprint']!=frozen['calibration_fingerprint']
    for i in stages:
        ref=frozen['stages'][str(i)]['reference']
        assert ref['training_fingerprint']==frozen['train_fingerprint']
        assert ref['score_calibration']['fingerprint']==frozen['calibration_fingerprint']
    for name,h in result['source_sha256'].items(): assert digest(ROOT/name)==h,name
    assert digest(ROOT/'research_support'/'public_data'/'chiller'/'rp1043.zip')==result['dataset_sha256']
    old=json.loads((ROOT/'outputs'/'chiller_upgrade'/'results.json').read_text(encoding='utf-8'))
    for k in ('total','eligible','valid','unknown','TP','FP','TN','FN'):
        assert actual[0][k]==old['comparison']['after_calibrated']['metrics'][k]
    audit={'successful':True,'four_stage_counts':[dict(c) for c in actual],
        'common_and_adjacent_counts_verified':True,'perfile_counts_verified':True,'rates_verified':True,
        'split_and_fingerprints_verified':True,'frozen_source_and_data_hashes_verified':True,
        'baseline_counts_reproduced':True,'python':sys.version,
        'dependencies':{p:importlib.metadata.version(p) for p in ('numpy','pandas','xlrd','CoolProp')},
        'results_sha256':digest(OUT/'results.json'),'predictions_sha256':digest(OUT/'predictions.csv')}
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit,indent=2))

if __name__=='__main__': main()
