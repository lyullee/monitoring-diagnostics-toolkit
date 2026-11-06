"""Independent counts, CUSUM replay, immutable splits and new-data qualification."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd
from measured_validation_data import hp_table,hp_batch,filter_table
from improvement_data import full_filter_trials
from audit_filter_heatpump_improvement import recount

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/diagnostic_followup';BASE=ROOT/'outputs/filter_heatpump_operating_points';ANALYSIS=ROOT/'outputs/diagnostic_gap_analysis'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def snapshot(path,hashes):
    with zipfile.ZipFile(path) as z:
        for name,h in hashes.items():assert hashlib.sha256(z.read(name.replace('\\','/'))).hexdigest()==h,name

def replay_evidence(data,reference,parameters):
    drifts={g['load_w']:g['drift'] for g in reference['evidence_groups']}
    limits={g['load_w']:g['threshold_score_seconds'] for g in reference['evidence_calibration']['groups']}
    previous=None;state=0.;smooth=0.;checked=0
    for row in data:
        load=10200. if row['sheet'].endswith('10') else 12300.
        valid=bool(int(row['before_valid']));score=float(row['evaporation_score']);t=float(row['time_s'])
        reset=previous is None or not previous['valid'] or not valid or row['sheet']!=previous['sheet'] or row['experiment']!=previous['experiment'] or t-previous['time']>60
        if reset:state=0.;smooth=score if valid else 0.
        if valid and not reset:
            dt=t-previous['time'];smooth+=-math.expm1(-dt/parameters['time_constant_s'])*(score-smooth)
            state=max(0.,state+dt*(smooth-drifts[load]))
        if valid:
            assert math.isclose(smooth,float(row['smoothed_score']),rel_tol=1e-10,abs_tol=1e-9)
            assert math.isclose(state,float(row['cusum_score_seconds']),rel_tol=1e-10,abs_tol=1e-8)
            ratio=state/limits[load];assert math.isclose(ratio,float(row['evidence_ratio']),rel_tol=1e-10,abs_tol=1e-9)
            assert bool(int(row['evidence_alarm']))==(ratio>1)
            checked+=1
        assert bool(int(row['after_alarm']))==((bool(int(row['before_alarm'])) or bool(int(row['evidence_alarm']))) and bool(int(row['after_valid'])))
        previous=dict(sheet=row['sheet'],experiment=row['experiment'],valid=valid,time=t)
    return checked

def check_events(data,keys,expected):
    from collections import defaultdict
    grouped=defaultdict(list)
    for row in data:grouped[tuple(row[k] for k in keys)].append(row)
    for policy in ['before','after']:
        alarms=0;negative=0;windows=0;detected=0;delays=[]
        for group in grouped.values():
            t=[float(x['time_s']) for x in group];v=[bool(int(x['eligible'])) and bool(int(x[policy+'_valid'])) for x in group]
            y=[bool(int(x['label'])) for x in group];a=[bool(int(x[policy+'_alarm'])) and good for x,good in zip(group,v)]
            gap=max(60.,3*float(np.median(np.diff(t)))) if len(t)>1 else 60.
            def runs(flags):
                result=[];i=0
                while i<len(flags):
                    if not flags[i]:i+=1;continue
                    j=i
                    while j+1<len(flags) and flags[j+1] and t[j+1]-t[j]<=gap:j+=1
                    result.append((i,j));i=j+1
                return result
            alarms+=len(runs(a));negative+=len(runs([flag and not label for flag,label in zip(a,y)]))
            for lo,hi in runs([good and label for good,label in zip(v,y)]):
                windows+=1;hits=[i for i in range(lo,hi+1) if a[i]]
                if hits:detected+=1;delays.append(t[hits[0]]-t[lo])
        e=expected[policy]
        assert (alarms,negative,windows,detected)==tuple(e[n] for n in ['alarm_segments','negative_alarm_fragments','positive_windows','detected_positive_windows'])
        assert (float(np.median(delays)) if delays else None)==e['delay_median_s']
        assert (max(delays) if delays else None)==e['delay_max_s']

def main():
    r=read(OUT/'results.json');p=read(OUT/'protocol.json');hf=read(OUT/'heatpump_frozen.json');ff=read(OUT/'filter_frozen.json')
    assert sha(OUT/'protocol.json')==r['protocol_sha256'] and sha(BASE/'results.json')==p['baseline_results_sha256']
    for name,h in r['source_sha256'].items():assert sha(ROOT/name)==h,name
    for name,h in p['raw_sha256'].items():assert sha(ROOT/name)==h,name
    for name,h in p['analysis_sha256'].items():assert sha(ANALYSIS/name)==h,name
    assert sha(OUT/'heatpump_frozen.json')==r['heatpump']['frozen_sha256'] and sha(OUT/'filter_frozen.json')==r['filter']['frozen_sha256']
    snapshot(ANALYSIS/'baseline_source_snapshot.zip',read(BASE/'results.json')['source_sha256'])
    before_f=read(BASE/'filter_frozen.json');before_h=read(BASE/'heatpump_frozen.json')
    assert hf['splits']==before_h['splits']
    for key in ['training_ids','calibration_ids','evaluation_ids']:assert ff[key]==before_f[key]
    tr,ca,ev=[set(ff[k]) for k in ['training_ids','calibration_ids','evaluation_ids']]
    assert not tr&ca and not tr&ev and not ca&ev
    for splits in hf['splits'].values():
        sets={k:set(v) for k,v in splits.items()}
        for a in sets:
            for b in sets:
                if a!=b:assert not sets[a]&sets[b]
    assert hf['reference']['training_fingerprint']!=hf['reference']['evidence_calibration']['fingerprint']
    assert ff['reference']['training_fingerprint']==before_f['reference']['training_fingerprint']
    assert ff['reference']['risk_calibration']==before_f['reference']['risk_calibration']
    assert ff['reference']['risk_forest']['trees']==before_f['reference']['risk_forest']['trees']
    counts={};predictions={}
    events=read(OUT/'event_comparison.json')
    data=rows(OUT/'heatpump_predictions.csv');old={(x['sheet'],x['source_row']):x for x in rows(BASE/'heatpump_reused_predictions.csv')};gold={}
    for sheet in {x['sheet'] for x in data}:
        d=hp_table(sheet);_,e,y,codes=hp_batch(d,sheet);gold[sheet]={int(i):(bool(a),bool(b),str(c),t) for i,a,b,c,t in zip(d.index,e,y,codes,d.Date)}
    seen=set()
    for x in data:
        key=(x['sheet'],x['source_row']);assert key not in seen;seen.add(key)
        e,y,code,t=gold[x['sheet']][int(x['source_row'])]
        assert bool(int(x['eligible']))==e and bool(int(x['label']))==y and code==x['experiment'] and abs(float(x['time_s'])-t.value/1e9)<1e-6
        for k in ['valid','alarm']:assert x['before_'+k]==old[key]['after_'+k]
    counts['heatpump']=recount(data,{k:v['metrics'] for k,v in r['heatpump']['comparison'].items()})
    for category in ['normal','EF','CVL','LL','OC']:
        subset=[x for x in data if ('normal' if x['sheet'].startswith('NF') else x['sheet'].rstrip('0123456789'))==category]
        recount(subset,{k:v['by_category'][category] for k,v in r['heatpump']['comparison'].items()})
    checked=replay_evidence(data,hf['reference'],hf['parameters']);predictions['heatpump_predictions.csv']=sha(OUT/'heatpump_predictions.csv')
    check_events(data,['sheet','experiment'],events['heatpump'])
    full,_=full_filter_trials();lookup={int(g.Data_No.iloc[0]):g for g in full};test=filter_table('test')
    for scope,oldname in [('original_test','reused_original_test'),('reused_suffix','reused_uncensored_suffix')]:
        name='filter_'+scope+'_predictions.csv';data=rows(OUT/name);old={(x['trial'],x['source_row']):x for x in rows(BASE/(oldname+'_predictions.csv'))};seen=set()
        for x in data:
            key=(x['trial'],x['source_row']);assert key not in seen;seen.add(key);ident=int(x['trial']);index=int(x['source_row'])
            g=test.loc[index] if scope=='original_test' else lookup[ident].loc[index]
            assert int(g.Data_No)==ident and abs(float(x['time_s'])-g.Time)<1e-9 and abs(float(x['rul_s'])-g.RUL)<1e-8
            assert bool(int(x['label']))==(g.RUL<=30)
            eligible=g.Time>=10 and np.isfinite(g.RUL) and g.RUL>=0
            if scope=='reused_suffix':eligible=eligible and bool(g.new_observation);assert ident in ev
            assert bool(int(x['eligible']))==eligible
            for k in ['valid','alarm']:
                assert x['before_'+k]==old[key]['after_'+k] and x['after_'+k]==x['before_'+k]
            if int(x['after_valid']):assert 0<=float(x['training_support_fraction'])<=1 and float(x['tree_vote_std'])>=0
        counts[scope]=recount(data,r['filter']['evaluations'][scope]['comparison']);predictions[name]=sha(OUT/name)
        check_events(data,['trial'],events['filter_'+scope])
    candidates={}
    for name,h in p['evaluated_candidate_results_sha256'].items():
        directory=ROOT/'outputs'/name;assert sha(directory/'results.json')==h;prior=read(directory/'results.json');snapshot(directory/'evaluated_source_snapshot.zip',prior['source_sha256'])
        for scope in ['original_test','reused_suffix']:
            recount(rows(directory/('filter_'+scope+'_predictions.csv')),prior['filter']['evaluations'][scope]['comparison'])
        candidates[name]=dict(results_sha256=h,source_snapshot_verified=True,counts_reproduced=True)
    manifest=read(ANALYSIS/'followup_download_manifest.json')
    for file in manifest['files']:
        raw=(ROOT/file['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==file['sha256']
        if file['publisher_md5']:assert hashlib.md5(raw).hexdigest()==file['publisher_md5']
    new=read(ANALYSIS/'new_independent_physical_validation.json')
    for name,h in new['source_sha256'].items():assert sha(ROOT/name)==h
    assert new['fault_accuracy'] is None and new['fault_recall'] is None and new['false_positive_rate'] is None
    with zipfile.ZipFile(ROOT/'research_support/public_data/gap_analysis_20261105/r290_receiver/thermodynamic.zip') as z:
        d=pd.read_csv(io.BytesIO(z.read('thermodynamic/thermodynamic_averaged_with_uncertainty.csv')))
    assert len(d)==195 and d.measurement_id.nunique()==9
    for name,calculated,provided in [('heating_cop',d.Q_flow_con_hyd_kW/d.P_el_com_kW,d.COP_hyd),('subcooling_k',d.T_c_C-d.T_con_out_C,d.dT_sc_con_out_K)]:
        assert abs(float(abs(calculated-provided).max())-new['checks'][name]['max_absolute_difference'])<1e-10
    ro=read(ANALYSIS/'ro_new_quality.json')
    if ro['status']=='obtained_quality_checked':
        assert ro.get('fault_accuracy') is None and ro.get('fault_recall') is None and ro.get('false_positive_rate') is None
        if 'source_sha256' in ro:assert sha(ROOT/'scripts/validate_followup_ro.py')==ro['source_sha256']
        path=ROOT/'research_support/public_data/gap_analysis_20261105/ro/wec_sim.zip';assert sha(path)==ro['sha256']
        with zipfile.ZipFile(path) as z:
            for file in ro['files']:
                d=pd.read_csv(io.BytesIO(z.read(file['file'])));assert len(d)==file['rows'];assert int((d['Feed Pressure (psi)']>=d['Reject Pressure (psi)']).sum())==file['pressure_order_ok']
    audit=dict(successful=True,results_sha256=sha(OUT/'results.json'),counts=counts,prediction_sha256=predictions,
        ewma_cusum_independently_replayed_rows=checked,source_and_frozen_hashes_verified=True,baseline_source_snapshot_verified=True,
        unchanged_disjoint_splits_verified=True,original_gold_labels_verified=True,filter_decisions_unchanged=True,rejected_candidates=candidates,
        new_data_files_verified=len(manifest['files']),new_independent_measured_rows=195,new_ro_observations_same_apparatus=sum(x['rows'] for x in ro.get('files',[])),
        new_data_fault_accuracy_remains_null=True,new_physical_identity_checks_reproduced=True)
    audit['alarm_segments_windows_and_delays_independently_recounted']=True
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
