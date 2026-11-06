"""Independent raw-label recount and lineage audit of the four development rounds."""
import json
import csv
import hashlib
from pathlib import Path
from collections import defaultdict
import numpy as np
from measured_validation_data import filter_table,hp_table,hp_batch
from improvement_data import full_filter_trials
from audit_filter_heatpump_improvement import recount

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/filter_heatpump_operating_points';OLD=ROOT/'outputs/filter_heatpump_improvement'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def csvrows(p):
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))

def check_snapshot(directory,result):
    import zipfile
    with zipfile.ZipFile(directory/'evaluated_source_snapshot.zip') as z:
        for name,h in result['source_sha256'].items():assert hashlib.sha256(z.read(name.replace('\\','/'))).hexdigest()==h,name

def main():
    r=read(OUT/'results.json');p=read(OUT/'protocol.json');ff=read(OUT/'filter_frozen.json');hf=read(OUT/'heatpump_frozen.json')
    assert r['protocol_sha256']==sha(OUT/'protocol.json')
    for name,h in r['source_sha256'].items():assert sha(ROOT/name)==h,name
    for name,h in p['raw_sha256'].items():assert sha(ROOT/name)==h,name
    assert sha(OLD/'results.json')==p['baseline_results_sha256']
    assert sha(OUT/'filter_frozen.json')==r['filter']['frozen_sha256']
    assert sha(OUT/'heatpump_frozen.json')==r['heatpump']['frozen_sha256']
    before_filter=read(OLD/'filter_frozen.json');before_hp=read(OLD/'heatpump_frozen.json')
    tr,ca,ev=[set(ff[k]) for k in ('training_ids','calibration_ids','evaluation_ids')]
    assert (len(tr),len(ca),len(ev))==(29,10,10) and not tr&ca and not tr&ev and not ca&ev
    assert tr==set(before_filter['training_ids']) and ca==set(before_filter['calibration_ids']) and ev==set(before_filter['new_observation_evaluation_ids'])
    assert hf['splits']==before_hp['splits']
    for _,s in hf['splits'].items():
        sets={k:set(v) for k,v in s.items()}
        for a in sets:
            for b in sets:
                if a!=b:assert not sets[a]&sets[b]
        assert max(sets['train'])<min(sets['calibration']) and max(sets['calibration'])<min(sets['evaluation'])
    assert ff['reference']['risk_calibration']['negative_quantile']==.95
    assert ff['reference']['training_fingerprint']!=ff['reference']['risk_calibration']['fingerprint']
    assert hf['reference']['training_fingerprint']!=hf['reference']['score_calibration']['fingerprint']
    assert set(ff['channels'])=={'pressure_drop','flow_ratio','dust_feed_ratio','dust_class'}
    assert ff['reference']['risk_forest']['feature_count']==10
    assert ff['reference']['risk_forest']['training_only']
    meta=filter_table('train').groupby('Data_No').first()
    assert ff['dust_feed_reference_raw']==float(np.median([meta.loc[i].Dust_feed for i in sorted(tr)]))
    full,_=full_filter_trials();lookup={int(g.Data_No.iloc[0]):g for g in full};original=filter_table('test')
    counts={};checksums={}
    scope_map={'reused_original_test':'reused_test','reused_uncensored_suffix':'unused_suffix_known_specimens'}
    for scope,oldscope in scope_map.items():
        path=OUT/(scope+'_predictions.csv');data=csvrows(path);seen=set()
        previous={(x['trial'],x['source_row']):x for x in csvrows(OLD/(oldscope+'_predictions.csv'))}
        for x in data:
            key=(x['trial'],x['source_row']);assert key not in seen;seen.add(key)
            ident=int(x['trial']);index=int(x['source_row']);g=original.loc[index] if scope=='reused_original_test' else lookup[ident].loc[index]
            assert int(g.Data_No)==ident and abs(g.Time-float(x['time_s']))<1e-9 and abs(g.RUL-float(x['rul_s']))<1e-8
            e=g.Time>=10 and np.isfinite(g.RUL) and g.RUL>=0
            if scope!='reused_original_test':e=e and bool(g.new_observation);assert ident in ev
            assert bool(int(x['eligible']))==e and bool(int(x['label']))==(g.RUL<=30)
            old=previous[key]
            for k in ('valid','alarm'):assert x['before_'+k]==old['after_'+k]
        counts[scope]=recount(data,r['filter']['evaluations'][scope]['comparison']);checksums[path.name]=sha(path)
    path=OUT/'heatpump_reused_predictions.csv';data=csvrows(path);previous={(x['sheet'],x['source_row']):x for x in csvrows(OLD/path.name)}
    gold={};seen=set();cats=defaultdict(list);sheets=defaultdict(list)
    for sheet in {x['sheet'] for x in data}:
        d=hp_table(sheet);_,e,y,_=hp_batch(d,sheet);gold[sheet]={int(i):(bool(a),bool(b),t) for i,a,b,t in zip(d.index,e,y,d.Date)}
    for x in data:
        key=(x['sheet'],x['source_row']);assert key not in seen;seen.add(key)
        e,y,t=gold[x['sheet']][int(x['source_row'])]
        assert bool(int(x['eligible']))==e and bool(int(x['label']))==y and abs(float(x['time_s'])-t.value/1e9)<1e-6
        for k in ('valid','alarm'):assert x['before_'+k]==previous[key]['after_'+k]
        cats['normal' if x['sheet'].startswith('NF') else x['sheet'].rstrip('0123456789')].append(x);sheets[x['sheet']].append(x)
    counts['heatpump_reused']=recount(data,{k:v['metrics'] for k,v in r['heatpump']['comparison'].items()})
    for category,subset in cats.items():recount(subset,{k:v['by_category'][category] for k,v in r['heatpump']['comparison'].items()})
    for sheet,subset in sheets.items():recount(subset,{k:v['by_sheet'][sheet] for k,v in r['heatpump']['comparison'].items()})
    checksums[path.name]=sha(path)
    attempts={}
    for name,h in p['earlier_attempt_results_sha256'].items():
        directory=ROOT/'outputs'/name;assert sha(directory/'results.json')==h;prior=read(directory/'results.json');check_snapshot(directory,prior)
        for scope in scope_map:
            data=csvrows(directory/(scope+'_predictions.csv'));recount(data,prior['filter']['evaluations'][scope]['comparison'])
        data=csvrows(directory/'heatpump_reused_predictions.csv');recount(data,{k:v['metrics'] for k,v in prior['heatpump']['comparison'].items()})
        attempts[name]=dict(results_sha256=h,source_snapshot_verified=True,counts_reproduced=True)
    for module in ('filter','heatpump'):assert r[module]['new_independent_validation']['recall'] is None
    audit=dict(successful=True,results_sha256=sha(OUT/'results.json'),counts=counts,prediction_sha256=checksums,
        source_data_frozen_hashes_verified=True,splits_unchanged_and_disjoint=True,baseline_row_predictions_unchanged=True,
        raw_gold_labels_verified=True,observed_conditions_training_only_normalization_verified=True,
        earlier_attempts=attempts,all_evaluations_are_reused=True,new_independent_validation_unavailable=True)
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
