"""Second improvement: both former test and former unused suffix are REUSED.

Candidate choices are fixed in code before held-out scoring. Only the original
training/calibration portions set parameters; no fresh independent result claimed.
"""
import csv
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import FilterRiskClassifier,FilterServiceRiskModel,HeatPumpPerformanceDiagnostic,SensorBatch,__version__
from measured_validation_data import filter_table,filter_batch,hp_table,hp_batch,normal_partition,concatenate,HP_CHANNELS,DATA
from improvement_data import full_filter_trials
from improve_filter_heatpump import collection,combined,digest

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'filter_heatpump_operating_points';OLD=ROOT/'outputs'/'filter_heatpump_improvement'
def save(name,obj):
    p=OUT/name;p.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');return digest(p)

def filter_run():
    frames,checks=full_filter_trials();old=json.loads((OLD/'filter_frozen.json').read_text())
    original=filter_table('train');metadata={}
    for ident,g in original.groupby('Data_No'):
        assert g.Dust_feed.nunique()==1 and g.Dust.nunique()==1
        metadata[int(ident)]=(float(g.Dust_feed.iloc[0]),str(g.Dust.iloc[0]))
    for d in frames:
        d['Dust_feed'],d['Dust']=metadata[int(d.Data_No.iloc[0])]
    tr=[d for d in frames if int(d.Data_No.iloc[0]) in old['training_ids']]
    ca=[d for d in frames if int(d.Data_No.iloc[0]) in old['calibration_ids']]
    ev=[d for d in frames if int(d.Data_No.iloc[0]) in old['new_observation_evaluation_ids']]
    flow=old['flow_reference_raw'];train,yt=collection(tr,flow);cal,yc=collection(ca,flow)
    feed_ref=float(np.median([float(d.Dust_feed.iloc[0]) for d in tr]))
    dust_names=['ISO 12103-1, A2 Fine Test Dust','ISO 12103-1, A3 Medium Test Dust','ISO 12103-1, A4 Coarse Test Dust']
    def conditions(b,d):
        codes=d.Dust.map({name:i+1 for i,name in enumerate(dust_names)}).to_numpy(float)
        if not np.isfinite(codes).all():raise ValueError('unseen dust material')
        return SensorBatch(b.time_s,np.column_stack((b.values,d.Dust_feed.to_numpy(float)/feed_ref,codes)),
            (*b.channels,'dust_feed_ratio','dust_class'),(*b.units,'1','1'),b.clock_id,b.asset_id,b.origin,
            valid=np.column_stack((b.valid,np.ones((len(d),2),bool))),episodes=b.episodes,
            metadata={**b.metadata,'added_observed_conditions':'publisher dust loading and material; no inferred fault label'})
    import pandas as pd
    train=conditions(train,pd.concat(sorted(tr,key=lambda g:int(g.Data_No.iloc[0])),ignore_index=True))
    cal=conditions(cal,pd.concat(sorted(ca,key=lambda g:int(g.Data_No.iloc[0])),ignore_index=True))
    channels=dict(pressure_drop='dp',flow_ratio='flow_ratio',dust_feed_ratio='dust_feed_ratio',dust_class='dust_class')
    model=FilterRiskClassifier(channels,persistence_s=1)
    # Middle operating point: same5% negative calibration indication cap as
    # the previous linear risk model, before the1s persistence filter. The
    #10% and2.5% alternatives already scored are retained for comparison.
    model.fit(train,yt).calibrate(cal,yc,negative_quantile=.95)
    baseline=FilterServiceRiskModel(dict(pressure_drop='dp',flow_ratio='flow_ratio'),**old['model_params'],persistence_s=1).set_reference(old['reference'])
    frozen=dict(training_ids=old['training_ids'],calibration_ids=old['calibration_ids'],evaluation_ids=old['new_observation_evaluation_ids'],
        parameters=model.params,channels=channels,reference=model.reference,flow_reference_raw=flow,dust_feed_reference_raw=feed_ref,dust_material_order=dust_names,old_frozen_sha256=digest(OLD/'filter_frozen.json'),
        old_suffix_is_now_reused=True,previous_threshold_quantile=.95,new_threshold_quantile=.95,persistence_s=1)
    fh=save('filter_frozen.json',frozen);snap=json.dumps(model.reference,sort_keys=True)
    reports={}
    for scope,groups in [('reused_original_test',[g for _,g in filter_table('test').groupby('Data_No',sort=True)]),('reused_uncensored_suffix',ev)]:
        rs={k:[] for k in ('before','after')}
        with (OUT/(scope+'_predictions.csv')).open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['trial','source_row','time_s','rul_s','eligible','label','before_valid','before_alarm','after_valid','after_alarm','after_score','risk_vote_fraction'])
            for d in groups:
                ident=int(d.Data_No.iloc[0]);b=filter_batch(d,flow,episode=scope+':'+str(ident));rb=baseline.score(b);r=model.score(conditions(b,d))
                y=d.RUL.to_numpy(float)<=30;e=(d.Time.to_numpy(float)>=10)&np.isfinite(d.RUL.to_numpy(float))&(d.RUL.to_numpy(float)>=0)
                if scope=='reused_uncensored_suffix':e&=d.new_observation.to_numpy(bool)
                for key,result in [('before',rb),('after',r)]:rs[key].append(dict(y=y,alarm=result.alarms,valid=result.valid,eligible=e))
                for i in range(len(d)):
                    w.writerow([ident,int(d.index[i]),b.time_s[i],float(d.RUL.iloc[i]),int(e[i]),int(y[i]),int(rb.valid[i]),int(rb.alarms[i]),int(r.valid[i]),int(r.alarms[i]),
                        float(r.scores[i]) if r.valid[i] else '',float(r.metrics['risk_vote_fraction'][i]) if r.valid[i] else ''])
        reports[scope]=dict(comparison={k:combined(v) for k,v in rs.items()},scope='reused_evaluation')
    assert snap==json.dumps(model.reference,sort_keys=True) and digest(OUT/'filter_frozen.json')==fh
    return dict(frozen_sha256=fh,evaluations=reports,source_checks=checks,
        new_independent_validation=dict(status='not_available',accuracy=None,recall=None,false_positive_rate=None,
            reason='All compatible HSE held-out observations were already evaluated. No new compatible 30s-to-600Pa reference obtained.'))

def hp_run():
    old=json.loads((OLD/'heatpump_frozen.json').read_text());tr=[];ca=[];normal=[]
    for sheet in ('NF10','NF12'):
        d=hp_table(sheet);b,_,_,_=hp_batch(d,sheet);split=old['splits'][sheet]
        tr.append(b.subset(np.isin(d.index,split['train'])));ca.append(b.subset(np.isin(d.index,split['calibration'])))
        normal.append((sheet,d,np.isin(d.index,split['evaluation'])))
    train=concatenate(tr);cal=concatenate(ca)
    model=HeatPumpPerformanceDiagnostic(HP_CHANNELS,reference_mode='load_conditioned',feature_set='extended',
        calibration_scope='evaporator_groups',evaporator_directional=True,persistence_s=30)
    model.fit(train).calibrate(cal,quantile=.99)
    baseline=HeatPumpPerformanceDiagnostic(HP_CHANNELS,**old['parameters'],persistence_s=30).set_reference(old['reference'])
    fh=save('heatpump_frozen.json',dict(splits=old['splits'],parameters=model.params,reference=model.reference,
        persistence_s=30,warmup_s=180,scope='reused',old_frozen_sha256=digest(OLD/'heatpump_frozen.json'),
        policy='Retain pooled cycle branch, add per-demand directional evaporation branch with normal-only99th-percentile and physical residual floors0.05K/0.002log.'))
    snap=json.dumps(model.reference,sort_keys=True);rs={k:[] for k in ('before','after')}
    with (OUT/'heatpump_reused_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['sheet','source_row','time_s','eligible','label','before_valid','before_alarm','after_valid','after_alarm','after_score'])
        for sheet,d,sel in normal+[(s,None,None) for s in ['EF10','EF12','CVL10','CVL12','LL10','LL12','OC10','OC12']]:
            if d is None:d=hp_table(sheet)
            b,e,y,_=hp_batch(d,sheet)
            if sel is not None:b=b.subset(sel);e=e[sel];y=y[sel];d=d.loc[sel]
            rb=baseline.score(b);r=model.score(b)
            cat='normal' if sheet.startswith('NF') else sheet.rstrip('0123456789')
            for key,result in [('before',rb),('after',r)]:rs[key].append(dict(y=y,alarm=result.alarms,valid=result.valid,eligible=e,category=cat,sheet=sheet))
            for i in range(len(d)):
                w.writerow([sheet,int(d.index[i]),b.time_s[i],int(e[i]),int(y[i]),int(rb.valid[i]),int(rb.alarms[i]),int(r.valid[i]),int(r.alarms[i]),float(r.scores[i]) if r.valid[i] else ''])
    assert snap==json.dumps(model.reference,sort_keys=True) and digest(OUT/'heatpump_frozen.json')==fh
    return dict(frozen_sha256=fh,scope='reused_evaluation',comparison={k:dict(metrics=combined(v),
        by_category={c:combined([r for r in v if r['category']==c]) for c in ['normal','EF','CVL','LL','OC']},
        by_sheet={s:combined([r for r in v if r['sheet']==s]) for s in sorted({r['sheet'] for r in v})}) for k,v in rs.items()},
        new_independent_validation=dict(status='not_available',accuracy=None,recall=None,false_positive_rate=None,
            reason='No newly acquired compatible labeled evaporator water-flow-reduction trials. New publications are not new test observations.'))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[Path(__file__),ROOT/'scripts/improvement_data.py',ROOT/'scripts/measured_validation_data.py',ROOT/'scripts/improve_filter_heatpump.py',
        ROOT/'scripts/validate_acquired_modules.py',ROOT/'scripts/validate_public_data.py',*sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    ph=save('protocol.json',dict(version=__version__,source_sha256=hashes,baseline_results_sha256=digest(OLD/'results.json'),
        raw_sha256={str(p.relative_to(ROOT)):digest(p) for p in [DATA/'filter_hse/filter.zip',DATA/'heatpump_propane/H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx']},
        all_former_evaluation_data_now_reused=True,filter_negative_quantile=.95,heatpump_normal_quantile=.99,
        training_and_calibration_fit_do_not_use_evaluation_labels=True,
        design_informed_by_reused_evaluation=True,development_attempts=4,
        earlier_attempt_results_sha256={n:digest(ROOT/'outputs'/n/'results.json') for n in ['filter_heatpump_refinement','filter_heatpump_refinement_final','filter_heatpump_balanced']}))
    fr=filter_run();print('filter completed',flush=True);hp=hp_run();print('heatpump completed',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):digest(p) for p in sources}
    save('results.json',dict(version=__version__,source_sha256=hashes,protocol_sha256=ph,filter=fr,heatpump=hp))
    print(json.dumps(dict(filter={k:v['comparison'] for k,v in fr['evaluations'].items()},heatpump=hp['comparison']),indent=2))
if __name__=='__main__':main()
