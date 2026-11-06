"""Independent stdlib counts, rates, common cohorts and frozen-split checks."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'remaining_modules'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def count(c,y,a,v,e):
    c['total']+=1;c['eligible' if e else 'excluded']+=1
    if not e:return
    c['fault_eligible' if y else 'normal_eligible']+=1
    if not v:c['unknown']+=1;return
    c['valid']+=1;c['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
def check(c,m):
    for k in ('total','eligible','excluded','valid','unknown','TP','FN','FP','TN'):assert c[k]==m[k],(k,c[k],m[k])
    for k,n,d in [('accuracy_valid',c['TP']+c['TN'],c['valid']),('recall_valid',c['TP'],c['TP']+c['FN']),
        ('false_positive_rate_valid',c['FP'],c['FP']+c['TN']),('coverage',c['valid'],c['eligible']),
        ('coverage_all_rows',c['valid'],c['total']),('fault_detection_all_eligible',c['TP'],c['fault_eligible'])]:
        assert m[k]==(n/d if d else None),k
def main():
    r=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
    frozen=json.loads((OUT/'frozen_development.json').read_text(encoding='utf-8'))
    assert digest(OUT/'frozen_development.json')==r['development_sha256']
    for p,h in r['source_sha256'].items():assert digest(ROOT/p)==h,p
    totals={};common={};groups={}
    with (OUT/'predictions.csv').open(encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            mod=row['module'];scenario=row['scenario'];available=row['before_available']=='1'
            y=row['label']=='1';e=row['eligible']=='1';vs=[row[k+'_valid']=='1' for k in ('before','after')]
            for i,k in enumerate(('before','after')):
                if k=='before' and not available:continue
                a=row[k+'_alarm']=='1';assert not a or vs[i]
                c=totals.setdefault((mod,k),Counter());g=groups.setdefault((mod,scenario,k),Counter())
                c2=common.setdefault((mod,k),Counter())
                count(c,y,a,vs[i],e);count(g,y,a,vs[i],e);count(c2,y,a,all(vs),e)
    for mod,policies in r['comparison'].items():
        for k,p in policies.items():
            if 'metrics' not in p:continue
            check(totals[mod,k],p['metrics'])
            if 'common_metrics' in p:check(common[mod,k],p['common_metrics'])
    for s in r['scenarios']:
        for k,p in s['policies'].items():check(groups[s['module'],s['scenario'],k],p['metrics'])
    for kind,d in frozen['development'].items():
        assert len({d['train_seed'],d['calibration_seed'],*d['test_seeds']})==4
        assert d['train_fingerprint']!=d['calibration_fingerprint']
        assert not {d['train_fingerprint'],d['calibration_fingerprint']}&{s['fingerprint'] for s in r['scenarios'] if s['module']==kind}
        for ref in d['references'].values():assert ref['training_fingerprint']==d['train_fingerprint']
    ch=json.loads((OUT/'chiller_attribution.json').read_text(encoding='utf-8'))
    for p,h in ch['source_sha256'].items():assert digest(ROOT/p)==h,p
    assert ch['old_normal_counts_reproduced'] and ch['reference_models_unchanged']
    old=json.loads((ROOT/'outputs'/'chiller_stages'/'results.json').read_text(encoding='utf-8'))
    for stage,c in ch['normal_counts'].items():
        assert sum(ch['dominant_channel_counts'][stage].values())==c['FP']
        previous=old['comparison'][stage]['by_category']['normal']
        assert c['valid']==previous['valid'] and c['FP']==previous['FP']
    audit={'successful':True,'counts_rates_common_cohorts_verified':True,'per_scenario_counts_verified':True,
        'disjoint_train_calibration_test_verified':True,'source_and_frozen_hashes_verified':True,
        'chiller_original_normal_counts_and_channel_totals_verified':True,
        'evidence_type':'simulation comparisons plus experimental-data score attribution; no new field qualification',
        'results_sha256':digest(OUT/'results.json'),'predictions_sha256':digest(OUT/'predictions.csv'),
        'chiller_attribution_sha256':digest(OUT/'chiller_attribution.json')}
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
