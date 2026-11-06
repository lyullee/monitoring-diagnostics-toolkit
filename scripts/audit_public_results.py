"""Independently recount saved CSV decisions with stdlib counters, not evaluation.py."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'public_validation'


def main():
    report=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    archive=ROOT/'research_support'/'public_data'/'chiller'/'rp1043.zip'
    md5=hashlib.md5(archive.read_bytes()).hexdigest()
    assert md5=='390f7619c61c43b05f425f10c249aba8', 'Chiller archive differs from Figshare metadata'
    checked=[]
    for module,name in [('chiller_performance','chiller'),('valve_tracking','valve')]:
        expected=next(r for r in report['evaluated'] if r['module']==module)['policies']['normal_calibrated']['metrics']
        counts=Counter(); p=OUT/f'{name}_predictions.csv'
        with p.open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                y,e,v,a=(row[k]=='1' for k in ('fault_label','eligible','valid','alarm'))
                counts['total']+=1
                assert not a or v, 'An invalid decision raised an alarm'
                if not e: counts['excluded']+=1; continue
                counts['eligible']+=1
                if not v: counts['unknown']+=1; continue
                counts['valid']+=1
                counts['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
        for k in ('total','eligible','excluded','valid','unknown','TP','FN','FP','TN'):
            assert counts[k]==expected[k],(module,k,counts[k],expected[k])
        checked.append({'module':module,'counts':dict(counts),'csv_sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    for p,h in report['source_sha256'].items():
        assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h, 'Source changed since evaluation: '+p
    result={'successful':True,'method':'Independent stdlib CSV recount; invalid/UNKNOWN never treated as correct negatives',
            'results_sha256':hashlib.sha256((OUT/'results.json').read_bytes()).hexdigest(),
            'chiller_publisher_md5_verified':md5,'checks':checked}
    (OUT/'independent_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
