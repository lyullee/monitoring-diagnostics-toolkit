"""Further5/6 candidates, fit/calibrate separately and compare reused holdouts."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import (SensorBatch,HeatPumpPerformanceDiagnostic,TemporalEvidenceDiagnostic,
    ResidualCoherenceDiagnostic,FilterRiskClassifier,FilterBoostedRiskClassifier,FilterBoostedLifeModel,HysteresisAlarmDiagnostic,FilterRiskEnsemble,__version__)
from measured_validation_data import hp_table,hp_batch,HP_CHANNELS,concatenate,filter_table,filter_batch,DATA
from improvement_data import full_filter_trials
from improve_filter_heatpump import collection,combined,digest
from improve_from_gap_analysis import evidence_batch,condition_batch

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'outputs/diagnostic_followup';UPSTREAM=ROOT/'outputs/filter_heatpump_operating_points';OUT=ROOT/'outputs/stage56_ensemble'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(name,x):
    p=OUT/name;p.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');return digest(p)

COHERENCE_CHANNELS=dict(evaporator_residual='ev',power_residual='power',speed_residual='speed',cop_residual='cop',heat_demand='load')

def residual_batch(b,result,model):
    keys=['evaporating_temperature_k','log_electric_power','log_compressor_speed','log_heating_cop'];sign=[-1.,1.,1.,-1.]
    scale=np.asarray(model.reference['refrigerant_model']['residual_scale'])
    x=np.column_stack([s*(result.metrics[k]-result.metrics['expected_'+k])/scale[model.KEYS.index(k)] for k,s in zip(keys,sign)])
    x=np.where(result.valid[:,None],x,0.)
    return SensorBatch(b.time_s,np.column_stack((x,b.values[:,-1])),('ev','power','speed','cop','load'),('1','1','1','1','W'),
        b.clock_id,b.asset_id,b.origin,valid=np.broadcast_to(result.valid[:,None],(len(x),5)),episodes=b.episodes,
        metadata={'signal':'signed standard residuals from frozen nominal-demand heat-pump model'})

def joint_evidence_batch(b,result,reference_hash):
    score=np.where(result.valid,result.scores,0.)
    return SensorBatch(b.time_s,np.column_stack((score,b.values[:,-1])),('s','load'),('1','W'),b.clock_id,b.asset_id,b.origin,
        valid=np.broadcast_to(result.valid[:,None],(len(score),2)),episodes=b.episodes,metadata={'coherence_reference_sha256':reference_hash})

def select_filter_model(train,y,channels):
    from sklearn.model_selection import GroupKFold
    from sklearn.metrics import roc_auc_score
    factories={
        'extra_trees':lambda:FilterRiskClassifier(channels,persistence_s=1),
        'boosted_classifier':lambda:FilterBoostedRiskClassifier(channels,persistence_s=1),
        'trial_balanced_classifier':lambda:FilterBoostedRiskClassifier(channels,balance_trials=True,persistence_s=1),
        'trial_balanced_life':lambda:FilterBoostedLifeModel(channels,persistence_s=1)}
    folds=list(GroupKFold(n_splits=3).split(np.zeros(len(y)),groups=train.episodes));records={}
    predictions=[]
    for name,factory in factories.items():
        values=[];detail=[]
        for fold,(fit_indices,hold_indices) in enumerate(folds):
            fit=train.subset(fit_indices);hold=train.subset(hold_indices);model=factory().fit(fit,y[fit_indices]);r=model.score(hold);v=r.valid
            target=y[hold_indices][v]<=30
            partial=float(roc_auc_score(target,r.scores[v],max_fpr=.05));full=float(roc_auc_score(target,r.scores[v]));values.append(partial)
            detail.append(dict(fold=fold,training_episodes=sorted(set(map(str,fit.episodes))),validation_episodes=sorted(set(map(str,hold.episodes))),
                fit_fingerprint=fit.fingerprint,validation_fingerprint=hold.fingerprint,valid_rows=int(v.sum()),partial_auc_fpr05=partial,auc=full))
            for j,index in enumerate(hold_indices):predictions.append([name,fold,int(index),str(train.episodes[index]),int(y[index]<=30),int(v[j]),float(r.scores[j]) if v[j] else ''])
            print(name,'inner_training_fold',fold,'completed',flush=True)
        records[name]=dict(mean_partial_auc_fpr05=float(np.mean(values)),folds=detail)
    frame=pd.DataFrame(predictions,columns=['candidate','fold','row','episode','label','valid','score'])
    paired=frame[frame.candidate=='extra_trees'].merge(frame[frame.candidate=='boosted_classifier'],on=['fold','row','episode','label'],suffixes=('_et','_hb'))
    assert (paired.valid_et==paired.valid_hb).all()
    for mode in ['arithmetic','geometric']:
        for weight in [.25,.5,.75]:
            name=f'ensemble_{mode}_b{int(weight*100):03d}';detail=[];values=[]
            a=pd.to_numeric(paired.score_et,errors='coerce');b=pd.to_numeric(paired.score_hb,errors='coerce')
            score=(1-weight)*a+weight*b if mode=='arithmetic' else np.maximum(a,1e-12)**(1-weight)*np.maximum(b,1e-12)**weight
            for fold,g in paired.groupby('fold'):
                valid=g.valid_et.astype(bool);ix=g.index[valid];partial=float(roc_auc_score(g.loc[ix,'label'],score.loc[ix],max_fpr=.05));full=float(roc_auc_score(g.loc[ix,'label'],score.loc[ix]));values.append(partial)
                d={**records['extra_trees']['folds'][int(fold)],'partial_auc_fpr05':partial,'auc':full};detail.append(d)
            for index,row in paired.iterrows():predictions.append([name,int(row.fold),int(row.row),row.episode,int(row.label),int(row.valid_et),float(score.loc[index]) if row.valid_et else ''])
            records[name]=dict(mean_partial_auc_fpr05=float(np.mean(values)),folds=detail)
            factories[name]=lambda mode=mode,weight=weight:FilterRiskEnsemble(channels,booster_weight=weight,aggregation=mode,persistence_s=1)
    selected=max(records,key=lambda n:records[n]['mean_partial_auc_fpr05'])
    with (OUT/'training_cv_predictions.csv').open('w',newline='',encoding='utf-8') as file:
        w=csv.writer(file);w.writerow(['candidate','fold','training_source_row','episode','label','valid','score']);w.writerows(predictions)
    save('training_model_selection.json',dict(selected=selected,criterion='largest mean standardized partial ROC AUC atFPR<=5%, training trial GroupKFold3 only',
        calibration_and_evaluation_data_not_used=True,candidates=records))
    return selected,factories[selected]()

def policy_batch(batch,result,reference_hash):
    return SensorBatch(batch.time_s,np.where(result.valid,result.scores,0.)[:,None],('risk',),('1',),batch.clock_id,batch.asset_id,batch.origin,
        valid=result.valid[:,None],episodes=batch.episodes,metadata={'model_reference_sha256':reference_hash})

def hp_run():
    old=read(BASE/'heatpump_frozen.json');hf=read(UPSTREAM/'heatpump_frozen.json');hhash=digest(UPSTREAM/'heatpump_frozen.json')
    assert hhash==old['upstream_frozen_sha256']
    hp=HeatPumpPerformanceDiagnostic(HP_CHANNELS,**hf['parameters'],persistence_s=30).set_reference(hf['reference'])
    previous=TemporalEvidenceDiagnostic(dict(indication_score='indication',heat_demand='load'),**old['parameters']).set_reference(old['reference'])
    tr=[];ca=[];normal=[]
    for sheet in ['NF10','NF12']:
        d=hp_table(sheet);b,_,_,_=hp_batch(d,sheet);s=old['splits'][sheet]
        tr.append(b.subset(np.isin(d.index,s['train'])));ca.append(b.subset(np.isin(d.index,s['calibration'])));normal.append((sheet,d,np.isin(d.index,s['evaluation'])))
    train=concatenate(tr);cal=concatenate(ca)
    assert train.fingerprint==old['normal_training_fingerprint'] and cal.fingerprint==old['normal_calibration_fingerprint']
    jt=residual_batch(train,hp.score(train),hp);jc=residual_batch(cal,hp.score(cal),hp)
    coherence=ResidualCoherenceDiagnostic(COHERENCE_CHANNELS,shrinkage=.1).fit(jt).calibrate(jc,quantile=.99)
    chash=save('coherence_frozen.json',dict(parameters=coherence.params,reference=coherence.reference,channels=COHERENCE_CHANNELS))
    et=joint_evidence_batch(train,coherence.score(jt),chash);ec=joint_evidence_batch(cal,coherence.score(jc),chash)
    temporal=TemporalEvidenceDiagnostic(dict(indication_score='s',heat_demand='load'),time_constant_s=20,drift_quantile=.8,minimum_evidence_s=10).fit(et).calibrate(ec)
    assert not temporal.score(ec).alarms.any()
    fh=save('heatpump_frozen.json',dict(coherence_reference_sha256=chash,parameters=temporal.params,reference=temporal.reference,splits=old['splits'],
        upstream_heatpump_sha256=hhash,upstream_evidence_sha256=digest(BASE/'heatpump_frozen.json'),normal_training_fingerprint=train.fingerprint,normal_calibration_fingerprint=cal.fingerprint,
        policy='OR existingv0.12 with normal-only directional residual covariance and EWMA/CUSUM; no fault labels in model/calibration'))
    snap=[json.dumps(m.reference,sort_keys=True) for m in [hp,previous,coherence,temporal]];rows={k:[] for k in ['before','after']}
    with (OUT/'heatpump_predictions.csv').open('w',newline='',encoding='utf-8') as file:
        w=csv.writer(file);w.writerow(['sheet','experiment','intensity','source_row','time_s','eligible','label','before_valid','before_alarm','after_valid','after_alarm','upstream_alarm','old_evidence_alarm','new_evidence_alarm','coherence_score','smoothed_score','cusum_score_seconds','evidence_ratio'])
        for sheet,d,selection in normal+[(s,None,None) for s in ['EF10','EF12','CVL10','CVL12','LL10','LL12','OC10','OC12']]:
            if d is None:d=hp_table(sheet)
            b,e,y,codes=hp_batch(d,sheet)
            if selection is not None:b=b.subset(selection);e=e[selection];y=y[selection];codes=codes[selection];d=d.loc[selection]
            r=hp.score(b);oldr=previous.score(evidence_batch(b,r,hp,hhash));j=coherence.score(residual_batch(b,r,hp));new=temporal.score(joint_evidence_batch(b,j,chash))
            old_valid=r.valid&oldr.valid;new_valid=old_valid&j.valid&new.valid;old_alarm=(r.alarms|oldr.alarms)&old_valid;new_alarm=(old_alarm|new.alarms)&new_valid
            cat='normal' if sheet.startswith('NF') else sheet.rstrip('0123456789')
            for key,valid,a in [('before',old_valid,old_alarm),('after',new_valid,new_alarm)]:rows[key].append(dict(y=y,valid=valid,alarm=a,eligible=e,category=cat))
            for i in range(len(d)):
                valid=new_valid[i];value=lambda k:float(new.metrics[k][i]) if valid else ''
                w.writerow([sheet,codes[i],float(d['Fault intensity'].iloc[i]),int(d.index[i]),b.time_s[i],int(e[i]),int(y[i]),int(old_valid[i]),int(old_alarm[i]),int(valid),int(new_alarm[i]),int(r.alarms[i]),int(oldr.alarms[i]),int(new.alarms[i]),
                    float(j.scores[i]) if valid else '',value('smoothed_score'),value('cusum_score_seconds'),float(new.scores[i]) if valid else ''])
    assert snap==[json.dumps(m.reference,sort_keys=True) for m in [hp,previous,coherence,temporal]] and digest(OUT/'heatpump_frozen.json')==fh
    return dict(frozen_sha256=fh,comparison={k:dict(metrics=combined(v),by_category={c:combined([x for x in v if x['category']==c]) for c in ['normal','EF','CVL','LL','OC']}) for k,v in rows.items()},scope='reused_evaluation')

def filter_run():
    f=read(BASE/'filter_frozen.json');base=FilterRiskClassifier(f['channels'],**f['parameters'],persistence_s=1).set_reference(f['reference'])
    frames,_=full_filter_trials();meta=filter_table('train').groupby('Data_No').first()
    for d in frames:d['Dust_feed'],d['Dust']=float(meta.loc[int(d.Data_No.iloc[0]),'Dust_feed']),meta.loc[int(d.Data_No.iloc[0]),'Dust']
    tr=[d for d in frames if int(d.Data_No.iloc[0]) in f['training_ids']];ca=[d for d in frames if int(d.Data_No.iloc[0]) in f['calibration_ids']];ev=[d for d in frames if int(d.Data_No.iloc[0]) in f['evaluation_ids']]
    train,ytr=collection(tr,f['flow_reference_raw']);cal,ycal=collection(ca,f['flow_reference_raw'])
    train=condition_batch(train,pd.concat(sorted(tr,key=lambda g:int(g.Data_No.iloc[0])),ignore_index=True),f);cal=condition_batch(cal,pd.concat(sorted(ca,key=lambda g:int(g.Data_No.iloc[0])),ignore_index=True),f)
    assert train.fingerprint==base.reference['training_fingerprint'] and cal.fingerprint==base.reference['risk_calibration']['fingerprint']
    selected,model=select_filter_model(train,ytr,f['channels'])
    model.fit(train,ytr).calibrate(cal,ycal,negative_quantile=.95)
    reference_hash=hashlib.sha256(json.dumps(model.reference,sort_keys=True).encode()).hexdigest()
    rc=model.score(cal);pc=policy_batch(cal,rc,reference_hash);calibration_policies=[];chosen=None
    for quantile in [.95,.975,.99,1.]:
        mask=rc.valid&(ycal>30);on=max(1e-12,float(np.nextafter(np.quantile(rc.scores[mask],quantile),np.inf)))
        candidate=HysteresisAlarmDiagnostic(dict(indication_score='risk'),on_threshold=on,confirmation_s=2,release_ratio=.25,release_s=5)
        pr=candidate.score(pc);negative=pr.valid&(ycal>30);positive=pr.valid&(ycal<=30)
        fp=float(pr.alarms[negative].mean());recall=float(pr.alarms[positive].mean())
        calibration_policies.append(dict(negative_quantile=quantile,parameters=candidate.params,false_positive_rate=fp,recall=recall,calibration_fingerprint=cal.fingerprint))
        if chosen is None and fp<=.05:chosen=candidate
    if chosen is None:raise ValueError('no calibration policy meets false-indication cap')
    save('policy_calibration.json',dict(policies=calibration_policies,selected=chosen.params,selection='lowest tested negative quantile with calibrationFPR<=5%',
        model_reference_sha256=reference_hash,evaluation_labels_not_used=True))
    fh=save('filter_frozen.json',dict(parameters=model.params,reference=model.reference,channels=f['channels'],training_ids=f['training_ids'],calibration_ids=f['calibration_ids'],evaluation_ids=f['evaluation_ids'],
        flow_reference_raw=f['flow_reference_raw'],dust_feed_reference_raw=f['dust_feed_reference_raw'],dust_material_order=f['dust_material_order'],baseline_frozen_sha256=digest(BASE/'filter_frozen.json'),
        selected=selected,selection_sha256=digest(OUT/'training_model_selection.json'),model_kind=model.kind,
        early_stopping=False,calibration_quantile=.95,active_policy='direct_1s',hysteresis_candidate_parameters=chosen.params,policy_calibration_sha256=digest(OUT/'policy_calibration.json'),
        policy='training-only grouped model selection; separate95th-percentile calibration; retained1s alarm; hysteresis alternative recorded separately'))
    snap=json.dumps(model.reference,sort_keys=True);reports={}
    for scope,groups in [('original_test',[g for _,g in filter_table('test').groupby('Data_No',sort=True)]),('reused_suffix',ev)]:
        rows={k:[] for k in ['before','after']}
        with (OUT/('filter_'+scope+'_predictions.csv')).open('w',newline='',encoding='utf-8') as file:
            w=csv.writer(file);w.writerow(['trial','source_row','time_s','rul_s','eligible','label','material','before_valid','before_alarm','after_valid','after_alarm','after_score','model_output','contribution_dispersion','training_support_fraction','model_score','model_alarm'])
            for d in groups:
                ident=int(d.Data_No.iloc[0]);b=condition_batch(filter_batch(d,f['flow_reference_raw'],episode=scope+':'+str(ident)),d,f);rb=base.score(b);mr=model.score(b);r=mr
                e=(b.time_s>=10)&np.isfinite(d.RUL.to_numpy(float))&(d.RUL.to_numpy(float)>=0);y=d.RUL.to_numpy(float)<=30
                if scope=='reused_suffix':e&=d.new_observation.to_numpy(bool)
                for key,result in [('before',rb),('after',r)]:rows[key].append(dict(y=y,valid=result.valid,alarm=result.alarms,eligible=e))
                for i in range(len(d)):
                    value=lambda k:float(mr.metrics[k][i]) if r.valid[i] else ''
                    output_key='predicted_remaining_service_life_s' if 'predicted_remaining_service_life_s' in mr.metrics else 'risk_vote_fraction'
                    dispersion_key='component_disagreement' if 'component_disagreement' in mr.metrics else 'boost_contribution_std' if 'boost_contribution_std' in mr.metrics else 'tree_vote_std'
                    w.writerow([ident,int(d.index[i]),b.time_s[i],float(d.RUL.iloc[i]),int(e[i]),int(y[i]),int(b.values[i,-1]),int(rb.valid[i]),int(rb.alarms[i]),int(r.valid[i]),int(r.alarms[i]),float(r.scores[i]) if r.valid[i] else '',value(output_key),value(dispersion_key),value('training_support_fraction'),float(mr.scores[i]) if r.valid[i] else '',int(mr.alarms[i])])
        reports[scope]=dict(comparison={k:combined(v) for k,v in rows.items()},scope='reused_evaluation')
    assert snap==json.dumps(model.reference,sort_keys=True) and digest(OUT/'filter_frozen.json')==fh
    return dict(frozen_sha256=fh,evaluations=reports)

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    sources=[Path(__file__),ROOT/'scripts/improve_from_gap_analysis.py',ROOT/'scripts/improve_filter_heatpump.py',ROOT/'scripts/improvement_data.py',ROOT/'scripts/measured_validation_data.py',
        ROOT/'scripts/validate_acquired_modules.py',ROOT/'scripts/validate_public_data.py',*sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    ph=save('protocol.json',dict(version=__version__,source_sha256=hashes,baseline_results_sha256=digest(BASE/'results.json'),
        raw_sha256={str(p.relative_to(ROOT)):digest(p) for p in [DATA/'filter_hse/filter.zip',DATA/'heatpump_propane/H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx']},
        unchanged_training_calibration_splits=True,reused_evaluation=True,design_informed_by_prior_reused_evaluation=True,
        independent_receiver_data_not_used_for_fit_calibration_or_selection=True))
    hp=hp_run();print('5_heatpump completed',flush=True);f=filter_run();print('6_filter completed',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):digest(p) for p in sources}
    old=hp['comparison']['before']['metrics'];new=hp['comparison']['after']['metrics']
    hp_ok=new['recall_valid']>=old['recall_valid'] and new['false_positive_rate_valid']<=old['false_positive_rate_valid'] and new['coverage']>=old['coverage']
    filter_ok=all(v['comparison']['after']['recall_valid']>=v['comparison']['before']['recall_valid'] and
        v['comparison']['after']['false_positive_rate_valid']<=v['comparison']['before']['false_positive_rate_valid'] and
        v['comparison']['after']['coverage']>=v['comparison']['before']['coverage'] for v in f['evaluations'].values())
    adoption=dict(criterion='No recall loss, no false-positive increase, no coverage loss across the relevant reused cohorts; development decision, not field qualification',
        heatpump_candidate_adopted=bool(hp_ok),filter_candidate_adopted=bool(filter_ok),
        filter_default_reference='outputs/diagnostic_followup/filter_frozen.json' if not filter_ok else str((OUT/'filter_frozen.json').relative_to(ROOT)),
        candidate_filter_reference=str((OUT/'filter_frozen.json').relative_to(ROOT)))
    save('adoption.json',adoption)
    save('results.json',dict(version=__version__,protocol_sha256=ph,source_sha256=hashes,heatpump=hp,filter=f,adoption=adoption,
        new_independent_fault_validation=dict(accuracy=None,recall=None,false_positive_rate=None,reason='No new compatible fault labels used. New charge-sweep identities and RO QC fromv0.12 remain separate.')))
    print(json.dumps(dict(hp=hp['comparison'],filter={k:v['comparison'] for k,v in f['evaluations'].items()}),indent=2))
if __name__=='__main__':main()
