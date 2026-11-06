"""Recount gold labels, training-only selection and residual/CUSUM arithmetic."""
import csv
import hashlib
import json
from pathlib import Path
import zipfile
import numpy as np
from measured_validation_data import hp_table,hp_batch,filter_table
from improvement_data import full_filter_trials
from audit_filter_heatpump_improvement import recount
from audit_diagnostic_followup import replay_evidence

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/stage56_ensemble';BASE=ROOT/'outputs/diagnostic_followup'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))

def aucs(label,score,max_fpr=.05):
    label=np.asarray(label,int);score=np.asarray(score,float);order=np.argsort(-score,kind='stable');label=label[order];score=score[order]
    pos=int(label.sum());neg=len(label)-pos;assert pos>0 and neg>0
    x=[0.];y=[0.];tp=0;fp=0;i=0
    while i<len(label):
        j=i+1
        while j<len(label) and score[j]==score[i]:j+=1
        tp+=int(label[i:j].sum());fp+=j-i-int(label[i:j].sum());x.append(fp/neg);y.append(tp/pos);i=j
    full=sum((x[i]-x[i-1])*(y[i]+y[i-1])/2 for i in range(1,len(x)));area=0.
    for i in range(1,len(x)):
        if x[i]>max_fpr:
            yy=y[i-1]+(y[i]-y[i-1])*(max_fpr-x[i-1])/(x[i]-x[i-1]);area+=(max_fpr-x[i-1])*(yy+y[i-1])/2;break
        area+=(x[i]-x[i-1])*(y[i]+y[i-1])/2
    minimum=.5*max_fpr**2;partial=.5*(1+(area-minimum)/(max_fpr-minimum))
    return full,partial

def main():
    r=read(OUT/'results.json');p=read(OUT/'protocol.json');ff=read(OUT/'filter_frozen.json');hf=read(OUT/'heatpump_frozen.json');cf=read(OUT/'coherence_frozen.json')
    assert sha(OUT/'protocol.json')==r['protocol_sha256'] and sha(BASE/'results.json')==p['baseline_results_sha256']
    for name,h in r['source_sha256'].items():assert sha(ROOT/name)==h,name
    for name,h in p['raw_sha256'].items():assert sha(ROOT/name)==h,name
    assert sha(OUT/'filter_frozen.json')==r['filter']['frozen_sha256'] and sha(OUT/'heatpump_frozen.json')==r['heatpump']['frozen_sha256'] and sha(OUT/'coherence_frozen.json')==hf['coherence_reference_sha256']
    with zipfile.ZipFile(BASE/'evaluated_source_snapshot.zip') as z:
        for name,h in read(BASE/'results.json')['source_sha256'].items():assert hashlib.sha256(z.read(name.replace('\\','/'))).hexdigest()==h
    oldf=read(BASE/'filter_frozen.json');oldh=read(BASE/'heatpump_frozen.json')
    for key in ['training_ids','calibration_ids','evaluation_ids']:assert ff[key]==oldf[key]
    assert hf['splits']==oldh['splits']
    train_ids=set(ff['training_ids']);assert not train_ids&set(ff['calibration_ids']) and not train_ids&set(ff['evaluation_ids'])
    selection=read(OUT/'training_model_selection.json');assert sha(OUT/'training_model_selection.json')==ff['selection_sha256']
    assert selection['selected']==ff['selected'] and selection['calibration_and_evaluation_data_not_used']
    predictions=rows(OUT/'training_cv_predictions.csv');by={}
    for row in predictions:by.setdefault((row['candidate'],int(row['fold'])),[]).append(row)
    cv_curves=0
    for name,candidate in selection['candidates'].items():
        values=[];seen=set()
        for fold in candidate['folds']:
            tr=set(fold['training_episodes']);va=set(fold['validation_episodes']);assert not tr&va
            assert all(int(x.split(':')[-1]) in train_ids for x in tr|va)
            data=by[(name,fold['fold'])]
            for x in data:
                key=int(x['training_source_row']);assert key not in seen;seen.add(key);assert x['episode'] in va
            valid=[x for x in data if int(x['valid'])];full,partial=aucs([int(x['label']) for x in valid],[float(x['score']) for x in valid])
            assert abs(full-fold['auc'])<1e-12 and abs(partial-fold['partial_auc_fpr05'])<1e-12
            values.append(partial);cv_curves+=1
        assert abs(float(np.mean(values))-candidate['mean_partial_auc_fpr05'])<1e-12
    best=max(x['mean_partial_auc_fpr05'] for x in selection['candidates'].values());assert selection['candidates'][selection['selected']]['mean_partial_auc_fpr05']==best
    assert ff['active_policy']=='direct_1s'
    counts={};data=rows(OUT/'heatpump_predictions.csv');old={(x['sheet'],x['source_row']):x for x in rows(BASE/'heatpump_predictions.csv')};gold={}
    for sheet in {x['sheet'] for x in data}:
        d=hp_table(sheet);_,e,y,codes=hp_batch(d,sheet);gold[sheet]={int(i):(row,bool(a),bool(b),str(code)) for (i,row),a,b,code in zip(d.iterrows(),e,y,codes)}
    upstream=read(ROOT/'outputs/filter_heatpump_operating_points/heatpump_frozen.json')['reference']['refrigerant_model'];targets=upstream['targets'];coh_groups={g['load_w']:g for g in cf['reference']['residual_groups']};coh_cut={g['load_w']:g['threshold'] for g in cf['reference']['coherence_calibration']['groups']}
    replay=[];checked=0
    for x in data:
        key=(x['sheet'],x['source_row']);row,e,y,code=gold[x['sheet']][int(x['source_row'])]
        assert bool(int(x['eligible']))==e and bool(int(x['label']))==y and x['experiment']==code and abs(float(x['time_s'])-row.Date.value/1e9)<1e-6
        for k in ['valid','alarm']:assert x['before_'+k]==old[key]['after_'+k]
        if int(x['after_valid']):
            load=10200. if x['sheet'].endswith('10') else 12300.
            design=np.array([1.,(load-upstream['load_center'])/upstream['load_scale']]);expected=design@np.asarray(upstream['coefficients'])+np.asarray(upstream['residual_center'])
            measured=[float(row.Evaporator_saturation_temperature)+273.15,np.log(float(row.Compressor_power_consumption)*1000),np.log(float(row.Compressor_speed)),np.log(float(row.Condenser_heat_duty)/float(row.Compressor_power_consumption))]
            residual=np.array([s*(v-expected[targets.index(k)])/upstream['residual_scale'][targets.index(k)] for s,v,k in zip([-1,1,1,-1],measured,['evaporating_temperature_k','log_electric_power','log_compressor_speed','log_heating_cop'])])
            group=coh_groups[load];delta=np.maximum(residual-np.asarray(group['center']),0.);distance=np.sqrt(max(0.,float(delta@np.asarray(group['inverse_covariance'])@delta)));score=distance/coh_cut[load]
            assert np.isclose(score,float(x['coherence_score']),rtol=1e-8,atol=1e-8);checked+=1
        replay.append({**x,'evaporation_score':x['coherence_score'] or '0','evidence_alarm':x['new_evidence_alarm']})
    replayed=replay_evidence(replay,hf['reference'],hf['parameters']);assert replayed==checked
    counts['heatpump']=recount(data,{k:v['metrics'] for k,v in r['heatpump']['comparison'].items()})
    full,_=full_filter_trials();lookup={int(g.Data_No.iloc[0]):g for g in full};test=filter_table('test')
    for scope in ['original_test','reused_suffix']:
        data=rows(OUT/('filter_'+scope+'_predictions.csv'));old={(x['trial'],x['source_row']):x for x in rows(BASE/('filter_'+scope+'_predictions.csv'))};seen=set()
        for x in data:
            key=(x['trial'],x['source_row']);assert key not in seen;seen.add(key);ident=int(x['trial']);index=int(x['source_row']);g=test.loc[index] if scope=='original_test' else lookup[ident].loc[index]
            assert abs(float(x['time_s'])-g.Time)<1e-9 and abs(float(x['rul_s'])-g.RUL)<1e-8 and int(x['label'])==int(g.RUL<=30)
            eligible=g.Time>=10 and np.isfinite(g.RUL) and g.RUL>=0
            if scope=='reused_suffix':eligible=eligible and bool(g.new_observation);assert ident in set(ff['evaluation_ids'])
            assert bool(int(x['eligible']))==eligible
            for k in ['valid','alarm']:assert x['before_'+k]==old[key]['after_'+k]
            assert x['after_alarm']==x['model_alarm']
        counts[scope]=recount(data,r['filter']['evaluations'][scope]['comparison'])
    assert r['adoption']['heatpump_candidate_adopted'] and not r['adoption']['filter_candidate_adopted']
    assert r['new_independent_fault_validation']['accuracy'] is None
    audit=dict(successful=True,results_sha256=sha(OUT/'results.json'),source_data_frozen_hashes_verified=True,
        training_cv_curves_independently_integrated=cv_curves,training_calibration_evaluation_trial_sets_disjoint=True,
        old_prediction_rows_reproduced=True,residual_coherence_and_cusum_replayed_rows=checked,counts=counts,
        filter_default_kept=True,new_independent_fault_metrics_remain_null=True,
        prediction_sha256={name:sha(OUT/name) for name in ['heatpump_predictions.csv','filter_original_test_predictions.csv','filter_reused_suffix_predictions.csv','training_cv_predictions.csv']})
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
