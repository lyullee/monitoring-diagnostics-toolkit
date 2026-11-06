"""Development on reused holdout; separate unseen observations on known units.

No independent fresh heat-pump EF benchmark is claimed. All choices below are
fixed before evaluation and calibration never uses the old Test labels.
"""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import FilterServiceRiskModel,HydraulicResistanceDiagnostic,HeatPumpPerformanceDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics
from measured_validation_data import filter_table,filter_batch,hp_table,hp_batch,normal_partition,concatenate,HP_CHANNELS,DATA
from validate_acquired_modules import filter_reference_batch
from validate_public_data import score_threshold
from improvement_data import full_filter_trials

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'filter_heatpump_improvement'
OLD=ROOT/'outputs'/'acquired_modules_validation'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,obj):
    p=OUT/name;p.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');return digest(p)
def metrics(y,r,e):return binary_metrics(y,r.alarms,r.valid,e)
def combined(rows):
    return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('y','alarm','valid','eligible')])

def collection(frames,flow_ref):
    # Reference-only clock offsets keep independent trial histories separate.
    import pandas as pd
    d=pd.concat(frames,ignore_index=True)
    b=filter_reference_batch(d,flow_ref)
    y=np.concatenate([g.RUL.to_numpy(float) for g in sorted(frames,key=lambda f:int(f.Data_No.iloc[0]))])
    return b,y

def filter_run():
    frames,checks=full_filter_trials()
    tr=[d for d in frames if int(d.Data_No.iloc[0])%5 in (1,2,3)]
    ca=[d for d in frames if int(d.Data_No.iloc[0])%5==4]
    ev=[d for d in frames if int(d.Data_No.iloc[0])%5==0]
    flow=float(np.median(np.concatenate([d.Flow_rate.to_numpy()[(d.Time>=10)&(d.Time<=20)] for d in tr])))
    train,yt=collection(tr,flow);cal,yc=collection(ca,flow)
    model=FilterServiceRiskModel(dict(pressure_drop='dp',flow_ratio='flow_ratio'),persistence_s=1)
    model.fit(train,yt).calibrate(cal,yc,negative_quantile=.95)
    old=json.loads((OLD/'filter_frozen.json').read_text(encoding='utf-8'))
    op=old['policies']['after'];baseline=HydraulicResistanceDiagnostic(dict(pressure_drop='dp',flow_ratio='flow_ratio'),**op['parameters']).set_reference(op['reference'])
    frozen=dict(training_ids=[int(d.Data_No.iloc[0]) for d in tr],calibration_ids=[int(d.Data_No.iloc[0]) for d in ca],
        new_observation_evaluation_ids=[int(d.Data_No.iloc[0]) for d in ev],flow_reference_raw=flow,
        model_params=model.params,reference=model.reference,old_frozen_sha256=digest(OLD/'filter_frozen.json'),
        new_data_scope='Previously unused suffixes of 10 known original Train specimens. Independent trial split for new predictor; not new corpus or new asset. Baseline historically saw their early calibration prefixes.',
        supervised_label='time until first observed DP>600Pa; no present-clogging onset labels',window_s=10,horizon_s=30,persistence_s=1)
    fh=save('filter_frozen.json',frozen);snap=json.dumps(model.reference,sort_keys=True)
    reports={}
    for scope,groups in [('reused_test',[g for _,g in filter_table('test').groupby('Data_No',sort=True)]),('unused_suffix_known_specimens',ev)]:
        rows={k:[] for k in ('before','after')};detail=[]
        with (OUT/(scope+'_predictions.csv')).open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['trial','source_row','time_s','rul_s','eligible','label','before_valid','before_alarm','after_valid','after_alarm','after_score','predicted_rul_s'])
            for d in groups:
                ident=int(d.Data_No.iloc[0]);b=filter_batch(d,flow,episode=f'{scope}:{ident}')
                r=model.score(b);bb=filter_batch(d,old['flow_reference_raw_unit'],episode=f'{scope}:{ident}')
                rb=baseline.score(bb);ab=score_threshold(rb,bb,op['threshold'],1)
                y=d.RUL.to_numpy(float)<=30;e=(d.Time.to_numpy(float)>=10)&np.isfinite(d.RUL)&(d.RUL>=0)
                if scope!='reused_test':e&=d.new_observation.to_numpy(bool)
                for k,rr,alarm in [('before',rb,ab),('after',r,r.alarms)]:
                    rows[k].append(dict(y=np.asarray(y),alarm=alarm,valid=rr.valid,eligible=np.asarray(e)))
                detail.append(dict(trial=ident,eligible=int(e.sum())))
                for i in range(len(d)):
                    w.writerow([ident,int(d.index[i]),b.time_s[i],float(d.RUL.iloc[i]),int(e.iloc[i] if hasattr(e,'iloc') else e[i]),int(y[i]),
                        int(rb.valid[i]),int(ab[i]),int(r.valid[i]),int(r.alarms[i]),float(r.scores[i]) if r.valid[i] else '',
                        float(r.metrics['predicted_remaining_service_life_s'][i]) if r.valid[i] else ''])
        reports[scope]=dict(comparison={k:combined(v) for k,v in rows.items()},trials=detail)
    assert json.dumps(model.reference,sort_keys=True)==snap and digest(OUT/'filter_frozen.json')==fh
    return dict(frozen_sha256=fh,matlab_prefix_checks=checks,evaluations=reports,
        historical_baseline=json.loads((OLD/'filter_results.json').read_text())['comparison']['after']['metrics'])

def hp_run():
    tr=[];ca=[];normal=[];splits={}
    for sheet in ('NF10','NF12'):
        d=hp_table(sheet);b,_,_,_=hp_batch(d,sheet);m=normal_partition(d)
        tr.append(b.subset(m['train']));ca.append(b.subset(m['calibration']));normal.append((sheet,d,m['evaluation']))
        splits[sheet]={k:[int(i) for i in d.index[v]] for k,v in m.items()}
    train=concatenate(tr);cal=concatenate(ca)
    model=HeatPumpPerformanceDiagnostic(HP_CHANNELS,reference_mode='load_conditioned',feature_set='extended',persistence_s=30)
    model.fit(train).calibrate(cal,quantile=.99)
    old=json.loads((OLD/'heatpump_frozen.json').read_text());op=old['policies']['after']
    baseline=HeatPumpPerformanceDiagnostic(HP_CHANNELS,**op['parameters'],persistence_s=30).set_reference(op['reference'])
    fh=save('heatpump_frozen.json',dict(splits=splits,parameters=model.params,reference=model.reference,
        old_frozen_sha256=digest(OLD/'heatpump_frozen.json'),persistence_s=30,warmup_s=180,
        evidence_scope='Reused original normal holdouts and all original fault sheets. No fresh EF trials.',
        feature_policy='Normal-load-only extended residuals; normal per-channel quantile calibration. No fault labels or compressor speed as driving variable.'))
    snap=json.dumps(model.reference,sort_keys=True);rows={k:[] for k in ('before','after')}
    with (OUT/'heatpump_reused_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['sheet','source_row','time_s','eligible','label','before_valid','before_alarm','after_valid','after_alarm','after_score'])
        for sheet,d,sel in normal+[(s,None,None) for s in ['EF10','EF12','CVL10','CVL12','LL10','LL12','OC10','OC12']]:
            if d is None:d=hp_table(sheet)
            b,e,y,_=hp_batch(d,sheet)
            if sel is not None:b=b.subset(sel);e=e[sel];y=y[sel];d=d.loc[sel]
            rb=baseline.score(b);r=model.score(b)
            for k,rr in [('before',rb),('after',r)]:rows[k].append(dict(y=y,alarm=rr.alarms,valid=rr.valid,eligible=e,category='normal' if sheet.startswith('NF') else sheet.rstrip('0123456789')))
            for i in range(len(d)):
                w.writerow([sheet,int(d.index[i]),b.time_s[i],int(e[i]),int(y[i]),int(rb.valid[i]),int(rb.alarms[i]),int(r.valid[i]),int(r.alarms[i]),float(r.scores[i]) if r.valid[i] else ''])
    assert snap==json.dumps(model.reference,sort_keys=True) and digest(OUT/'heatpump_frozen.json')==fh
    return dict(frozen_sha256=fh,scope='reused_evaluation',comparison={k:dict(metrics=combined(v),
        by_category={c:combined([r for r in v if r['category']==c]) for c in ['normal','EF','CVL','LL','OC']}) for k,v in rows.items()},
        new_independent_EF_validation=dict(status='not_available',accuracy=None,recall=None,false_positive_rate=None,
            reason='No newly obtained compatible labeled evaporator water-flow-reduction trials; NIST cooling-mode spreadsheet download returned HTTP403. Charge-sweep data do not label EF.'))

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    sources=[Path(__file__),ROOT/'scripts'/'improvement_data.py',ROOT/'scripts'/'measured_validation_data.py',
        ROOT/'scripts'/'validate_acquired_modules.py',ROOT/'scripts'/'validate_public_data.py',*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    protocol=dict(version=__version__,source_sha256=hashes,baseline_results_sha256=digest(OLD/'results.json'),
        original_data_sha256={str(p.relative_to(ROOT)):digest(p) for p in [DATA/'filter_hse'/'filter.zip',DATA/'heatpump_propane'/'H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx']},
        split_policy='Full Train specimens modulo5:1,2,3 train;4 calibration;0 unseen suffix evaluation. Original Test reused only. HP keeps original purged normal split.',
        no_test_based_parameter_search=True,filter_negative_calibration_quantile=.95,hp_normal_quantile=.99)
    ph=save('protocol.json',protocol)
    filters=filter_run();print('filter done',flush=True);hp=hp_run();print('heatpump done',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):digest(p) for p in sources}
    result=dict(version=__version__,protocol_sha256=ph,source_sha256=hashes,filter=filters,heatpump=hp)
    save('results.json',result)
    print(json.dumps({'filter':{k:v['comparison'] for k,v in filters['evaluations'].items()},'heatpump':hp['comparison']},indent=2))
if __name__=='__main__':main()
