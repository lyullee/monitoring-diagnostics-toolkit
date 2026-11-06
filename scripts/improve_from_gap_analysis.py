"""Stages5/6, after the read-only1..4 analysis; v0.11 splits unchanged."""
import csv
import json
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import SensorBatch,HeatPumpPerformanceDiagnostic,TemporalEvidenceDiagnostic,FilterRiskClassifier,__version__
from measured_validation_data import hp_table,hp_batch,HP_CHANNELS,concatenate,filter_table,filter_batch,DATA
from improvement_data import full_filter_trials
from improve_filter_heatpump import collection,combined,digest

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'outputs/filter_heatpump_operating_points';ANALYSIS=ROOT/'outputs/diagnostic_gap_analysis';OUT=ROOT/'outputs/diagnostic_followup'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(name,x):
    p=OUT/name;p.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');return digest(p)

def evaporation_score(result,model):
    selected=[model.KEYS.index(k) for k in ['evaporating_temperature_k','log_electric_power','log_compressor_speed','log_heating_cop']]
    channels=np.column_stack([result.metrics['channel_'+k+'_score'] for k in model.KEYS]);score=np.zeros(len(result.time_s))
    for g in model.reference['score_calibration']['load_groups']:
        mask=result.valid&np.isclose(result.metrics['heat_demand_w'],g['load_w'],rtol=0,atol=1e-6)
        score[mask]=np.max((channels[mask]/np.asarray(g['channel_scales']))[:,selected],axis=1)/g['threshold']
    return score

def evidence_batch(b,result,model,upstream_digest):
    score=evaporation_score(result,model)
    return SensorBatch(b.time_s,np.column_stack((score,b.values[:,-1])),('indication','load'),('1','W'),b.clock_id,b.asset_id,b.origin,
        valid=np.broadcast_to(result.valid[:,None],(len(score),2)),episodes=b.episodes,
        metadata={'upstream_reference_sha256':upstream_digest,'signal':'directional evaporation branch only; excludes drifting cycle channels'})

def hp_run():
    f=read(BASE/'heatpump_frozen.json');upstream_digest=digest(BASE/'heatpump_frozen.json')
    base=HeatPumpPerformanceDiagnostic(HP_CHANNELS,**f['parameters'],persistence_s=30).set_reference(f['reference'])
    training=[];calibration=[];normal=[]
    for sheet in ['NF10','NF12']:
        d=hp_table(sheet);b,_,_,_=hp_batch(d,sheet);splits=f['splits'][sheet]
        training.append(b.subset(np.isin(d.index,splits['train'])));calibration.append(b.subset(np.isin(d.index,splits['calibration'])))
        normal.append((sheet,d,np.isin(d.index,splits['evaluation'])))
    train=concatenate(training);cal=concatenate(calibration)
    assert train.fingerprint==base.reference['training_fingerprint'] and cal.fingerprint==base.reference['score_calibration']['fingerprint']
    et=evidence_batch(train,base.score(train),base,upstream_digest);ec=evidence_batch(cal,base.score(cal),base,upstream_digest)
    model=TemporalEvidenceDiagnostic(dict(indication_score='indication',heat_demand='load'),time_constant_s=20.,drift_quantile=.8,minimum_evidence_s=10.)
    model.fit(et).calibrate(ec);assert not model.score(ec).alarms.any()
    fh=save('heatpump_frozen.json',dict(parameters=model.params,reference=model.reference,upstream_frozen_sha256=upstream_digest,
        splits=f['splits'],normal_training_fingerprint=train.fingerprint,normal_calibration_fingerprint=cal.fingerprint,
        policy='OR original30s alarm with causal EWMA/CUSUM; drift from normal training; evidence limit=max separate normal calibration with10score-second floor',
        fault_labels_used_for_fit_or_calibration=False))
    snap=json.dumps(model.reference,sort_keys=True);rows={k:[] for k in ['before','after']}
    with (OUT/'heatpump_predictions.csv').open('w',newline='',encoding='utf-8') as file:
        w=csv.writer(file);w.writerow(['sheet','experiment','intensity','source_row','time_s','eligible','label','before_valid','before_alarm','after_valid','after_alarm','base_score','evaporation_score','smoothed_score','cusum_score_seconds','evidence_ratio','evidence_alarm'])
        for sheet,d,sel in normal+[(s,None,None) for s in ['EF10','EF12','CVL10','CVL12','LL10','LL12','OC10','OC12']]:
            if d is None:d=hp_table(sheet)
            b,e,y,codes=hp_batch(d,sheet)
            if sel is not None:b=b.subset(sel);e=e[sel];y=y[sel];codes=codes[sel];d=d.loc[sel]
            r=base.score(b);eb=evidence_batch(b,r,base,upstream_digest);er=model.score(eb);v=r.valid&er.valid;alarm=(r.alarms|er.alarms)&v
            cat='normal' if sheet.startswith('NF') else sheet.rstrip('0123456789')
            for key,valid,a in [('before',r.valid,r.alarms),('after',v,alarm)]:rows[key].append(dict(y=y,valid=valid,alarm=a,eligible=e,category=cat))
            for i in range(len(d)):
                valid=bool(v[i]);value=lambda k:float(er.metrics[k][i]) if valid else ''
                w.writerow([sheet,codes[i],float(d['Fault intensity'].iloc[i]),int(d.index[i]),b.time_s[i],int(e[i]),int(y[i]),int(r.valid[i]),int(r.alarms[i]),int(valid),int(alarm[i]),
                    float(r.scores[i]) if r.valid[i] else '',float(eb.values[i,0]),value('smoothed_score'),value('cusum_score_seconds'),float(er.scores[i]) if valid else '',int(er.alarms[i])])
    assert snap==json.dumps(model.reference,sort_keys=True) and digest(OUT/'heatpump_frozen.json')==fh
    return dict(frozen_sha256=fh,comparison={k:dict(metrics=combined(v),by_category={c:combined([x for x in v if x['category']==c]) for c in ['normal','EF','CVL','LL','OC']}) for k,v in rows.items()},scope='reused_evaluation')

def condition_batch(b,d,f):
    code=d.Dust.map({s:i+1 for i,s in enumerate(f['dust_material_order'])}).to_numpy(float)
    return SensorBatch(b.time_s,np.column_stack((b.values,d.Dust_feed.to_numpy(float)/f['dust_feed_reference_raw'],code)),
        (*b.channels,'dust_feed_ratio','dust_class'),(*b.units,'1','1'),b.clock_id,b.asset_id,b.origin,
        valid=np.column_stack((b.valid,np.ones((len(d),2),bool))),episodes=b.episodes,
        metadata={**b.metadata,'added_observed_conditions':'publisher dust loading and material; no inferred fault label'})

def filter_run():
    f=read(BASE/'filter_frozen.json');base=FilterRiskClassifier(f['channels'],**f['parameters'],persistence_s=1).set_reference(f['reference'])
    frames,checks=full_filter_trials();raw=filter_table('train');metadata=raw.groupby('Data_No').first()
    for d in frames:d['Dust_feed'],d['Dust']=float(metadata.loc[int(d.Data_No.iloc[0]),'Dust_feed']),metadata.loc[int(d.Data_No.iloc[0]),'Dust']
    train=[d for d in frames if int(d.Data_No.iloc[0]) in f['training_ids']];cal=[d for d in frames if int(d.Data_No.iloc[0]) in f['calibration_ids']];ev=[d for d in frames if int(d.Data_No.iloc[0]) in f['evaluation_ids']]
    bt,yt=collection(train,f['flow_reference_raw']);bc,yc=collection(cal,f['flow_reference_raw'])
    bt=condition_batch(bt,pd.concat(sorted(train,key=lambda x:int(x.Data_No.iloc[0])),ignore_index=True),f)
    bc=condition_batch(bc,pd.concat(sorted(cal,key=lambda x:int(x.Data_No.iloc[0])),ignore_index=True),f)
    assert bt.fingerprint==base.reference['training_fingerprint'] and bc.fingerprint==base.reference['risk_calibration']['fingerprint']
    # Rejected material/dose alternatives are retained separately. Preserve the
    # established decision policy, adding descriptive support/disagreement only.
    model=FilterRiskClassifier(f['channels'],**f['parameters'],persistence_s=1).fit(bt,yt).calibrate(bc,yc,negative_quantile=.95)
    assert model.reference['risk_forest']['trees']==base.reference['risk_forest']['trees']
    assert model.reference['risk_calibration']['threshold']==base.reference['risk_calibration']['threshold']
    fh=save('filter_frozen.json',dict(parameters=model.params,channels=f['channels'],reference=model.reference,training_ids=f['training_ids'],calibration_ids=f['calibration_ids'],evaluation_ids=f['evaluation_ids'],
        flow_reference_raw=f['flow_reference_raw'],dust_feed_reference_raw=f['dust_feed_reference_raw'],dust_material_order=f['dust_material_order'],upstream_frozen_sha256=digest(BASE/'filter_frozen.json'),
        uncertainty_policy='Tree vote dispersion and training feature support are descriptive; no rows excluded to improve headline metrics'))
    snap=json.dumps(model.reference,sort_keys=True);reports={}
    for scope,groups in [('original_test',[g for _,g in filter_table('test').groupby('Data_No',sort=True)]),('reused_suffix',ev)]:
        rows={k:[] for k in ['before','after']};support=[]
        with (OUT/('filter_'+scope+'_predictions.csv')).open('w',newline='',encoding='utf-8') as file:
            w=csv.writer(file);w.writerow(['trial','source_row','time_s','rul_s','eligible','label','material','before_valid','before_alarm','after_valid','after_alarm','after_score','risk_vote_fraction','tree_vote_std','training_support_fraction'])
            for d in groups:
                ident=int(d.Data_No.iloc[0]);b=condition_batch(filter_batch(d,f['flow_reference_raw'],episode=scope+':'+str(ident)),d,f)
                rb=base.score(b);r=model.score(b);y=d.RUL.to_numpy(float)<=30;e=(b.time_s>=10)&np.isfinite(d.RUL.to_numpy(float))&(d.RUL.to_numpy(float)>=0)
                if scope=='reused_suffix':e&=d.new_observation.to_numpy(bool)
                for key,result in [('before',rb),('after',r)]:rows[key].append(dict(y=y,valid=result.valid,alarm=result.alarms,eligible=e))
                support.extend(r.metrics['training_support_fraction'][r.valid&e].tolist())
                for i in range(len(d)):
                    valid=r.valid[i];value=lambda k:float(r.metrics[k][i]) if valid else ''
                    w.writerow([ident,int(d.index[i]),b.time_s[i],float(d.RUL.iloc[i]),int(e[i]),int(y[i]),int(b.values[i,-1]),int(rb.valid[i]),int(rb.alarms[i]),int(valid),int(r.alarms[i]),
                        float(r.scores[i]) if valid else '',value('risk_vote_fraction'),value('tree_vote_std'),value('training_support_fraction')])
        reports[scope]=dict(comparison={k:combined(v) for k,v in rows.items()},support_warning_rows=sum(x<1 for x in support),
            eligible_rows_with_support=len(support),scope='reused_evaluation')
    assert snap==json.dumps(model.reference,sort_keys=True) and digest(OUT/'filter_frozen.json')==fh
    return dict(frozen_sha256=fh,evaluations=reports,adopted='unchanged decision policy with new uncertainty/support annotations',
        rejected_candidates={name:digest(ROOT/'outputs'/name/'results.json') for name in ['analysis_driven_improvement','analysis_driven_dose']})

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[Path(__file__),ROOT/'scripts/analyze_diagnostic_gaps.py',ROOT/'scripts/improvement_data.py',ROOT/'scripts/measured_validation_data.py',ROOT/'scripts/improve_filter_heatpump.py',
        ROOT/'scripts/validate_acquired_modules.py',ROOT/'scripts/validate_public_data.py',*sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    ph=save('protocol.json',dict(version=__version__,source_sha256=hashes,sequence=[1,2,3,4,5,6],baseline_results_sha256=digest(BASE/'results.json'),
        analysis_sha256={n:digest(ANALYSIS/n) for n in ['1_events.json','2_heatpump_misses.json','3_filter_conditions.json','4_ro_quality.json','analysis_protocol.json']},
        raw_sha256={str(p.relative_to(ROOT)):digest(p) for p in [DATA/'filter_hse/filter.zip',DATA/'heatpump_propane/H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx']},
        reused_evaluation=True,design_informed_by_analysis_of_reused_evaluation=True,unchanged_training_calibration_splits=True,
        independent_receiver_data_excluded_from_fit_calibration_and_selection=True,
        evaluated_candidate_results_sha256={name:digest(ROOT/'outputs'/name/'results.json') for name in ['analysis_driven_improvement','analysis_driven_dose']}))
    hp=hp_run();print('5_heatpump completed',flush=True);f=filter_run();print('6_filter completed',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):digest(p) for p in sources}
    result=dict(version=__version__,protocol_sha256=ph,source_sha256=hashes,heatpump=hp,filter=f,
        new_data_validation=dict(physical_indicator_results='../diagnostic_gap_analysis/new_independent_physical_validation.json',
            fault_accuracy=None,fault_recall=None,false_positive_rate=None,reason='New independent charge-sweep data support physical indicators, not EF or filter-risk truth.'))
    save('results.json',result)
    print(json.dumps(dict(heatpump=hp['comparison'],filter={k:v['comparison'] for k,v in f['evaluations'].items()}),indent=2))
if __name__=='__main__':main()
