"""Independent serialization/count/source checks for the paired chiller comparison."""
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'chiller_upgrade'


def main():
    result=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    keys=('before_fixed','before_calibrated','after_fixed','after_calibrated')
    actual={k:Counter() for k in keys}; common={k:Counter() for k in keys}
    def count(target,y,a,v,e):
        target['total']+=1
        if not e: target['excluded']+=1; return
        target['eligible']+=1
        if not v: target['unknown']+=1; return
        target['valid']+=1
        target['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
    with (OUT/'predictions.csv').open(encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            y=row['label']=='1'; e=row['eligible']=='1'
            bv=row['before_valid']=='1'; av=row['after_valid']=='1'
            for k in keys:
                a=row[k]=='1'; v=bv if k.startswith('before') else av
                assert not a or v,'Invalid decision emitted an alarm'
                count(actual[k],y,a,v,e); count(common[k],y,a,bv and av,e)
    for k in keys:
        for mode,counters in [('metrics',actual),('common_valid_metrics',common)]:
            for name in ('total','eligible','excluded','valid','unknown','TP','FN','FP','TN'):
                assert counters[k][name]==result['comparison'][k][mode][name],(k,mode,name)
    for path,h in result['source_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h,'Source changed after evaluation: '+path
    assert hashlib.sha256((OUT/'frozen_development.json').read_bytes()).hexdigest()==result['development_sha256']
    frozen=json.loads((OUT/'frozen_development.json').read_text(encoding='utf-8'))
    split=frozen['split']; tests=[n+'.xls' for n in split['normal_test']]
    tests += [n+'.xls' for names in split['fault_test'].values() for n in names]
    assert len(tests)==len(set(tests))==35
    assert split['train']!=split['calibration'] and not {split['train'],split['calibration']}&set(tests)
    assert frozen['train_fingerprint']!=frozen['calibration_fingerprint']
    report={'successful':True,'four_policies_recounted':{k:dict(v) for k,v in actual.items()},
        'python':sys.version,'dependencies':{p:importlib.metadata.version(p) for p in ('numpy','pandas','xlrd','CoolProp')},
        'common_sample_counts_verified':True,'frozen_development_verified':True,'disjoint_files_verified':True,
        'source_hashes_verified':True,'original_baseline_counts_reproduced':result['baseline_counts_reproduced'],
        'results_sha256':hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest(),
        'predictions_sha256':hashlib.sha256((OUT/'predictions.csv').read_bytes()).hexdigest()}
    (OUT/'independent_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
