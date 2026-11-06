"""Recount predictions against original labels and check split/source integrity."""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from measured_validation_data import filter_table,hp_table,hp_batch
from improvement_data import full_filter_trials

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'filter_heatpump_improvement'
OLD=ROOT/'outputs'/'acquired_modules_validation'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))

def recount(data,expected):
    result={}
    for policy in ('before','after'):
        c=dict(total=0,eligible=0,valid=0,TP=0,TN=0,FP=0,FN=0)
        for row in data:
            c['total']+=1
            if not int(row['eligible']):continue
            c['eligible']+=1
            if not int(row[policy+'_valid']):continue
            c['valid']+=1
            y=bool(int(row['label']));a=bool(int(row[policy+'_alarm']))
            c['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
        m=expected[policy]
        for k,v in c.items():assert v==m[k],(policy,k,v,m[k])
        def div(n,d):return n/d if d else None
        rates=dict(accuracy_valid=div(c['TP']+c['TN'],c['valid']),recall_valid=div(c['TP'],c['TP']+c['FN']),
            false_positive_rate_valid=div(c['FP'],c['FP']+c['TN']),coverage=div(c['valid'],c['eligible']),coverage_all_rows=div(c['valid'],c['total']))
        for k,v in rates.items():assert v is None and m[k] is None or v is not None and abs(v-m[k])<1e-12
        result[policy]=c
    return result

def main():
    r=read(OUT/'results.json');p=read(OUT/'protocol.json')
    assert sha(OUT/'protocol.json')==r['protocol_sha256']
    for name,h in r['source_sha256'].items():assert sha(ROOT/name)==h,name
    for name,h in p['original_data_sha256'].items():assert sha(ROOT/name)==h
    assert sha(OLD/'results.json')==p['baseline_results_sha256']
    ff=read(OUT/'filter_frozen.json');hf=read(OUT/'heatpump_frozen.json')
    assert sha(OUT/'filter_frozen.json')==r['filter']['frozen_sha256']
    assert sha(OUT/'heatpump_frozen.json')==r['heatpump']['frozen_sha256']
    tr=set(ff['training_ids']);ca=set(ff['calibration_ids']);ev=set(ff['new_observation_evaluation_ids'])
    assert not tr&ca and not tr&ev and not ca&ev
    assert len(tr)==29 and len(ca)==10 and len(ev)==10
    for sheet,splits in hf['splits'].items():
        sets={k:set(v) for k,v in splits.items()}
        for a in sets:
            for b in sets:
                if a!=b:assert not sets[a]&sets[b]
        assert max(sets['train'])<min(sets['calibration'])<max(sets['calibration'])<min(sets['evaluation'])
    assert hf['reference']['training_fingerprint']!=hf['reference']['score_calibration']['fingerprint']
    assert ff['reference']['training_fingerprint']!=ff['reference']['risk_calibration']['fingerprint']
    full,checks=full_filter_trials();lookup={int(g.Data_No.iloc[0]):g for g in full}
    old_filter=rows(OLD/'filter_predictions.csv');old_filter={(int(x['trial']),int(x['source_row'])):x for x in old_filter}
    summary={}
    for scope in ('reused_test','unused_suffix_known_specimens'):
        data=rows(OUT/(scope+'_predictions.csv'));seen=set();raw=filter_table('test') if scope=='reused_test' else None
        for row in data:
            ident=int(row['trial']);index=int(row['source_row']);key=(ident,index)
            assert key not in seen;seen.add(key)
            g=raw.loc[index] if raw is not None else lookup[ident].loc[index]
            assert int(g.Data_No)==ident and abs(float(row['time_s'])-g.Time)<1e-9
            assert abs(float(row['rul_s'])-g.RUL)<1e-8
            assert int(row['label'])==int(g.RUL<=30)
            eligible=g.Time>=10 and np.isfinite(g.RUL) and g.RUL>=0
            if raw is None:eligible=eligible and bool(g.new_observation);assert ident in ev
            assert bool(int(row['eligible']))==eligible
            if raw is not None:
                old=old_filter[key]
                for new,oldkey in [('before_valid','after_valid'),('before_alarm','after_alarm')]:assert row[new]==old[oldkey]
        expected=r['filter']['evaluations'][scope]['comparison'];summary[scope]=recount(data,expected)
    data=rows(OUT/'heatpump_reused_predictions.csv');seen=set();gold={}
    for sheet in {x['sheet'] for x in data}:
        d=hp_table(sheet);_,e,y,_=hp_batch(d,sheet)
        gold[sheet]={int(i):(bool(a),bool(b),t) for i,a,b,t in zip(d.index,e,y,d.Date)}
    old_hp={(x['sheet'],x['source_row']):x for x in rows(OLD/'heatpump_predictions.csv')}
    for row in data:
        key=(row['sheet'],row['source_row']);assert key not in seen;seen.add(key)
        e,y,t=gold[row['sheet']][int(row['source_row'])]
        assert bool(int(row['eligible']))==e and bool(int(row['label']))==y
        assert abs(float(row['time_s'])-t.value/1e9)<1e-6
        old=old_hp[key]
        for new,oldkey in [('before_valid','after_valid'),('before_alarm','after_alarm')]:assert row[new]==old[oldkey]
    summary['heatpump_reused']=recount(data,{k:v['metrics'] for k,v in r['heatpump']['comparison'].items()})
    bycat=defaultdict(list)
    for row in data:bycat['normal' if row['sheet'].startswith('NF') else row['sheet'].rstrip('0123456789')].append(row)
    for cat,rs in bycat.items():recount(rs,{k:v['by_category'][cat] for k,v in r['heatpump']['comparison'].items()})
    assert r['heatpump']['new_independent_EF_validation']['recall'] is None
    report=dict(successful=True,independent_counts=summary,original_labels_checked=True,
        baseline_reused_predictions_identical=True,splits_disjoint=True,source_and_data_hashes_verified=True,
        mat_reader_crosschecked_with_50_original_csv_prefixes=True,excluded_uncensored_clock_trial=28,
        new_filter_scope='Unused observations on known specimens, not new independent assets',
        new_heatpump_EF_unavailable=True,results_sha256=sha(OUT/'results.json'),
        prediction_sha256={n:sha(OUT/n) for n in ('reused_test_predictions.csv','unused_suffix_known_specimens_predictions.csv','heatpump_reused_predictions.csv')})
    (OUT/'independent_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
