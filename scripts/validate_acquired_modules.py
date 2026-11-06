"""Sequential measured-data applications: filter, RO, then refrigerant-side heat pump.

All splits, engineering limits and model settings precede held-out scoring.
Filter RUL risk is explicitly separate from present-fault diagnosis. RO has no
fault ground truth, so binary diagnostic metrics are deliberately not produced.
"""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import SensorBatch,HydraulicResistanceDiagnostic,ROMembraneDiagnostic,HeatPumpPerformanceDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import score_threshold
from measured_validation_data import DATA,HP_CHANNELS,filter_table,filter_batch,ro_table,ro_groups,ro_batch,hp_table,hp_batch,normal_partition,concatenate

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'acquired_modules_validation'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,obj):
    path=OUT/name;path.write_bytes(json.dumps(obj,indent=2,sort_keys=True).encode('utf-8'));return digest(path)
def aggregate(rows,common=False):
    return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm','common' if common else 'valid','eligible')])
def ratio(n,d):return float(n/d) if d else None

def filter_reference_batch(d,flow_reference):
    batches=[];offset=0
    for ident,g in d.groupby('Data_No',sort=True):
        b=filter_batch(g,flow_reference,episode=f'train:{ident}')
        shifted=b.time_s-b.time_s[0]+offset;offset=shifted[-1]+120
        batches.append(SensorBatch(shifted,b.values,b.channels,b.units,b.clock_id,b.asset_id,b.origin,episodes=b.episodes,
            metadata={'collection_clock':'independent per-trial clocks offset by separators for reference fitting only; no cross-trial integration'}))
    return concatenate(batches)

def filter_run():
    d=filter_table('train')
    prefix=(d.Time>=10)&(d.Time<=20)&(d.Flow_rate>0)
    cal_ids=sorted(int(i) for i in d.Data_No.unique() if int(i)%5==0)
    train_ids=sorted(int(i) for i in d.Data_No.unique() if int(i)%5!=0)
    train_rows=d[prefix&d.Data_No.isin(train_ids)];cal_rows=d[prefix&d.Data_No.isin(cal_ids)]
    flow_ref=float(train_rows.Flow_rate.median())
    train=filter_reference_batch(train_rows,flow_ref);cal=filter_reference_batch(cal_rows,flow_ref)
    channels=dict(pressure_drop='dp',flow_ratio='flow_ratio')
    models={'before':HydraulicResistanceDiagnostic(channels,flow_input='ratio',flow_exponent=2,growth_limit_fraction=.25),
        'after':HydraulicResistanceDiagnostic(channels,flow_input='ratio',normalization_mode='mixed',growth_limit_fraction=.25)}
    cuts={}
    for k,m in models.items():
        m.fit(train);r=m.score(cal)
        if r.valid.sum()<10:raise ValueError('insufficient separate filter calibration')
        cuts[k]=max(1.,float(np.nextafter(np.quantile(r.scores[r.valid],.99),np.inf)))
    frozen=dict(split={'training_source':'Train_Data_CSV.csv','training_ids':train_ids,'calibration_ids':cal_ids,
        'evaluation_source':'Test_Data_CSV.csv','evaluation_ids':list(range(1,51))},
        training_keys=[f'train:{int(i)}:{int(j)}' for j,i in zip(train_rows.index,train_rows.Data_No)],
        calibration_keys=[f'train:{int(i)}:{int(j)}' for j,i in zip(cal_rows.index,cal_rows.Data_No)],
        train_fingerprint=train.fingerprint,calibration_fingerprint=cal.fingerprint,flow_reference_raw_unit=flow_ref,
        early_reference_rule='Time10..20s, positive flow; early-life reference, not independently certified healthy',
        risk_label='provided RUL <=30s; future provider service limit DP>600Pa, NOT present clogging-onset truth',
        threshold_quantile=.99,persistence_s=1.,evaluation_warmup_s=10.,
        policies={k:dict(parameters=m.params,reference=m.reference,threshold=cuts[k]) for k,m in models.items()})
    frozen_hash=save('filter_frozen.json',frozen);snap=[json.dumps(m.reference,sort_keys=True) for m in models.values()]
    test=filter_table('test');rows={k:[] for k in models};files=[];rul_consistency=[]
    with (OUT/'filter_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['source_row','trial','time_s','rul_s','label_risk30','eligible',
            'before_valid','before_score','before_alarm','after_valid','after_score','after_alarm'])
        for ident,g in test.groupby('Data_No',sort=True):
            b=filter_batch(g,flow_ref,episode=f'test:{ident}');rul=g.RUL.to_numpy(float)
            e=(b.time_s>=10)&np.isfinite(rul)&(rul>=0);y=rul<=30
            rs={k:m.score(b) for k,m in models.items()};common=np.logical_and.reduce([r.valid for r in rs.values()]);alarms={}
            item=dict(trial=int(ident),policies={})
            for k,r in rs.items():
                alarm=score_threshold(r,b,cuts[k],1.);alarms[k]=alarm
                row=dict(label=y,alarm=alarm,valid=r.valid,common=common,eligible=e);rows[k].append(row)
                item['policies'][k]=dict(metrics=aggregate([row]),unknown_reasons=dict(Counter(np.asarray(r.reasons)[e&~r.valid])))
            files.append(item);rul_consistency.append(float(np.ptp(g.Time.to_numpy()+rul)))
            for i,t in enumerate(b.time_s):
                w.writerow([int(g.index[i]),int(ident),t,rul[i],int(y[i]),int(e[i]),
                    *[v for k,r in rs.items() for v in (int(r.valid[i]),r.scores[i]/cuts[k] if r.valid[i] else '',int(alarms[k][i]))]])
    assert max(rul_consistency)<1e-6,'RUL and Time do not define a consistent future service-limit time'
    assert snap==[json.dumps(m.reference,sort_keys=True) for m in models.values()]
    assert digest(OUT/'filter_frozen.json')==frozen_hash
    return dict(module='hydraulic_resistance',status='measured_RUL_risk_proxy_evaluated',
        diagnostic_fault_metrics_status='not_evaluated_missing_independent_present_clogging_truth',
        target='service-limit risk within30s, from provided RUL, not current binary clogging diagnosis',
        frozen_sha256=frozen_hash,comparison={k:dict(metrics=aggregate(v),common_valid_metrics=aggregate(v,True)) for k,v in rows.items()},
        files=files,rul_plus_time_max_range_s=max(rul_consistency),
        limitations=['Pressure-derived service-life targets; these metrics cannot be called independent present-clogging accuracy.',
            'Early-life training/calibration prefixes are not certified fault-free; manufacturing variation and dust loading remain.',
            'Unknown absolute flow unit canceled by a dimensionless ratio; no guessed m3/s conversion.',
            'Original Test RUL never used to fit models, choose thresholds or tune the30s horizon.'])

def ro_run():
    d=ro_table('steady_state/steady_state.csv','steady_state.zip')
    masks={k:np.zeros(len(d),bool) for k in ('train','calibration','evaluation','purge')}
    for _,g in d.groupby('Steady-State Pressure (psi)',sort=True):
        for k,mask in normal_partition(g).items():masks[k][g.index.to_numpy()]=mask
    models={k:ROMembraneDiagnostic(dict(permeate_flow='q',net_driving_pressure='ndp',temperature_correction='factor'),
        membrane_area_m2=7.4,decline_limit_fraction=.15) for k in ('before','after')}
    cuts={};fingerprints={}
    for k,m in models.items():
        b=ro_batch(d,corrected=k=='after',episode='steady',pressure_basis='feed_only_assumption')
        train=b.subset(masks['train']);cal=b.subset(masks['calibration']);m.fit(train);r=m.score(cal)
        if r.valid.sum()<10:raise ValueError('insufficient RO calibration')
        cuts[k]=max(1.,float(np.nextafter(np.quantile(r.scores[r.valid],.99),np.inf)))
        fingerprints[k]=dict(train=train.fingerprint,calibration=cal.fingerprint)
    frozen=dict(split={k:np.flatnonzero(v).tolist() for k,v in masks.items()},fingerprints=fingerprints,
        temporal_rule='within each steady pressure condition: train0..40%, purge40..50%, calibration50..70%, purge70..80%, test80..100%',
        dynamic_evaluation_files=ro_groups(),before='hydraulic pressure only; factor1',
        after='subtract ideal NaCl osmotic pressure, inverse FilmTec empirical temperature factor',
        pressure_basis='UNQUALIFIED feed-pressure-only zero-vessel-loss approximation; strict order failure reported separately',
        parameter_assumptions=dict(area_m2=7.4,permeate_gauge_pressure_pa=0,conductivity_to_g_l=.6638),
        no_fault_labels=True,policies={k:dict(reference=m.reference,threshold=cuts[k]) for k,m in models.items()},persistence_s=5)
    frozen_hash=save('ro_frozen.json',frozen);snap=[json.dumps(m.reference,sort_keys=True) for m in models.values()]
    records={k:[] for k in models};files=[]
    specs=[('steady_state/steady_state.csv','steady_state.zip',masks['evaluation'])]+[(n,a,None) for n,a in ro_groups()]
    with (OUT/'ro_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['source','source_row','time_s','pressure_order_ok','before_valid','before_score','before_alarm','before_permeability',
            'after_valid','after_score','after_alarm','after_permeability','flow_closure_fraction','flux_relative_error'])
        for name,archive,selection in specs:
            raw=d if selection is not None else ro_table(name,archive)
            frames=raw.loc[selection] if selection is not None else raw
            results={};alarms={};item=dict(file=name,policies={})
            for k,m in models.items():
                b=ro_batch(raw,corrected=k=='after',episode=name,pressure_basis='feed_only_assumption')
                if selection is not None:b=b.subset(selection)
                r=m.score(b);alarm=score_threshold(r,b,cuts[k],5);results[k]=r;alarms[k]=alarm
                perm=r.metrics['normalized_permeability_m_pa_s'];p=perm[r.valid]
                item['policies'][k]=dict(total=len(r.valid),valid=int(r.valid.sum()),coverage=ratio(int(r.valid.sum()),len(r.valid)),
                    observed_alarm_fraction=ratio(int(alarm.sum()),int(r.valid.sum())),
                    permeability_relative_std=ratio(float(np.std(p)),float(np.mean(p))) if len(p) else None,
                    unknown_reasons=dict(Counter(np.asarray(r.reasons)[~r.valid])))
                records[k].append(dict(valid=r.valid,alarm=alarm,permeability=perm))
            qf=frames['Feed Flowrate (L/min)'].to_numpy(float);qp=frames['Permeate 1 Flowrate (L/min)'].to_numpy(float);qc=frames['Reject Flowrate (L/min)'].to_numpy(float)
            order_ok=(frames['Feed Pressure (psi)'].to_numpy(float)>=frames['Reject Pressure (psi)'].to_numpy(float))
            with np.errstate(all='ignore'):
                closure=(qf-qp-qc)/qf;derived_flux=qp*60/7.4
                flux_difference=frames['Water Flux (LMH)'].to_numpy(float)-derived_flux
                flux_error=np.divide(flux_difference,abs(derived_flux),out=np.full(len(derived_flux),np.nan),where=derived_flux!=0)
            item['flow_closure_abs_median']=float(np.nanmedian(abs(closure)));item['flow_closure_abs_p99']=float(np.nanquantile(abs(closure),.99))
            item['pressure_order_valid_rows']=int(order_ok.sum())
            item['flux_relative_error_abs_max']=float(np.nanmax(abs(flux_error)));files.append(item)
            item['flux_relative_error_undefined_zero_flow_rows']=int((derived_flux==0).sum())
            item['flux_absolute_error_lmh_max']=float(np.nanmax(abs(flux_difference)))
            for i,t in enumerate(results['after'].time_s):
                w.writerow([name,int(frames.index[i]),t,int(order_ok[i]),*[v for k,r in results.items() for v in
                    (int(r.valid[i]),r.scores[i]/cuts[k] if r.valid[i] else '',int(alarms[k][i]),r.metrics['normalized_permeability_m_pa_s'][i] if r.valid[i] else '')],closure[i],flux_error[i]])
    summary={}
    for k,rs in records.items():
        v=np.concatenate([r['valid'] for r in rs]);a=np.concatenate([r['alarm'] for r in rs]);perm=np.concatenate([r['permeability'] for r in rs]);p=perm[v]
        summary[k]=dict(total=len(v),valid=int(v.sum()),coverage=ratio(int(v.sum()),len(v)),
            observed_alarm_fraction=ratio(int(a.sum()),int(v.sum())),permeability_relative_std=ratio(float(np.std(p)),float(np.mean(p))) if len(p) else None,
            accuracy_valid=None,recall_valid=None,false_positive_rate_valid=None)
    assert snap==[json.dumps(m.reference,sort_keys=True) for m in models.values()] and digest(OUT/'ro_frozen.json')==frozen_hash
    return dict(module='ro_membrane',status='strict_pressure_quality_failed_reference_only_approximation',frozen_sha256=frozen_hash,
        strict_training_pressure_order_valid_rows=int((d['Feed Pressure (psi)']>=d['Reject Pressure (psi)']).loc[masks['train']].sum()),
        strict_evaluation_pressure_order_fraction=ratio(sum(v['pressure_order_valid_rows'] for v in files),sum(v['policies']['after']['total'] for v in files)),
        comparison=summary,files=files,limitations=['No membrane fouling/damage truth. Alarm fraction is not an established false-positive rate.',
            'Strict feed>=reject pressure order fails on all steady training observations. Core calibration shown only for an UNQUALIFIED feed-pressure-only approximation.',
            'Ideal NaCl osmotic pressure, empirical temperature correction, zero permeate gauge-pressure assumption; sensitivity remains.',
            'Steady runs split chronologically with purge gaps, not independent machines; dynamic experiments kept entirely in evaluation.',
            'Flux consistency checks reuse a provider-derived quantity and are unit/area checks, not independent flow validation.'])

def hp_run():
    train=[];cal=[];normal_eval=[];split={}
    for sheet in ('NF10','NF12'):
        d=hp_table(sheet);b,e,y,codes=hp_batch(d,sheet);masks=normal_partition(d)
        train.append(b.subset(masks['train']));cal.append(b.subset(masks['calibration']))
        normal_eval.append((sheet,d,masks['evaluation']))
        split[sheet]={k:[int(i) for i in d.index[v]] for k,v in masks.items()}
    train=concatenate(train);cal=concatenate(cal)
    models={k:HeatPumpPerformanceDiagnostic(HP_CHANNELS,reference_mode=mode,persistence_s=30)
        for k,mode in [('before','constant'),('after','load_conditioned')]}
    for m in models.values():m.fit(train).calibrate(cal,quantile=.99)
    fault_sheets=['EF10','EF12','CVL10','CVL12','LL10','LL12','OC10','OC12']
    frozen=dict(normal_split=split,train_fingerprint=train.fingerprint,calibration_fingerprint=cal.fingerprint,
        temporal_rule='normal runs split0..40% training,50..70% calibration,80..100% evaluation; intervening10% gaps purged',
        fault_evaluation_sheets=fault_sheets,known_trial_warmup_s=180,persistence_s=30,
        policy='same four refrigerant-side residual channels; constant vs nominal-load-conditioned reference; no test tuning',
        nominal_demands_w=[10200,12300],superheat_stream_used=False,
        policies={k:dict(parameters=m.params,reference=m.reference) for k,m in models.items()})
    frozen_hash=save('heatpump_frozen.json',frozen);snap=[json.dumps(m.reference,sort_keys=True) for m in models.values()]
    rows={k:[] for k in models};files=[]
    specs=normal_eval+[(sh,None,None) for sh in fault_sheets]
    with (OUT/'heatpump_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['sheet','source_row','time_s','experiment','label','eligible','before_valid','before_score','before_alarm','after_valid','after_score','after_alarm'])
        for sheet,d,selection in specs:
            if d is None:d=hp_table(sheet)
            b,e,y,codes=hp_batch(d,sheet)
            if selection is not None:
                b=b.subset(selection);e=e[selection];y=y[selection];codes=codes[selection];d=d.loc[selection]
            rs={k:m.score(b) for k,m in models.items()};common=np.logical_and.reduce([r.valid for r in rs.values()])
            item=dict(sheet=sheet,policies={})
            for k,r in rs.items():
                row=dict(label=y,alarm=r.alarms,valid=r.valid,common=common,eligible=e,category='normal' if sheet.startswith('NF') else sheet.rstrip('0123456789'))
                rows[k].append(row);item['policies'][k]=dict(metrics=aggregate([row]),unknown_reasons=dict(Counter(np.asarray(r.reasons)[e&~r.valid])))
            files.append(item)
            for i,t in enumerate(b.time_s):
                w.writerow([sheet,int(d.index[i]),t,codes[i],int(y[i]),int(e[i]),
                    *[v for r in rs.values() for v in (int(r.valid[i]),r.scores[i] if r.valid[i] else '',int(r.alarms[i]))]])
    assert snap==[json.dumps(m.reference,sort_keys=True) for m in models.values()] and digest(OUT/'heatpump_frozen.json')==frozen_hash
    comparison={k:dict(metrics=aggregate(rs),common_valid_metrics=aggregate(rs,True),
        by_category={c:aggregate([r for r in rs if r['category']==c]) for c in sorted({r['category'] for r in rs})}) for k,rs in rows.items()}
    return dict(module='heat_pump_performance',status='measured_induced_faults_evaluated',frozen_sha256=frozen_hash,
        comparison=comparison,files=files,limitations=['One propane heating-mode prototype; no transfer claim from RP1043 cooling chiller.',
            'Normal calibration/evaluation are purged chronological portions of the same two normal runs, not independent replicate trials.',
            'EF is reduced evaporator water flow, CVL is compressor discharge-suction bypass; experimentally emulated mechanisms.',
            'Known trial boundaries and180s startup exclusion used; sample-level steady screening, not unqualified fault-onset detection.',
            'Nominal demand is experimental operating metadata; fault code/intensity/reported COP never used as diagnostic features.',
            'Independent superheat stream unused; no future/index-based join or invented water-side sensors.'])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[Path(__file__),ROOT/'scripts'/'measured_validation_data.py',ROOT/'scripts'/'validate_public_data.py',
             *sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    datafiles=[DATA/'filter_hse'/'filter.zip',DATA/'ro_nrel'/'steady_state.zip',DATA/'ro_nrel'/'ramp.zip',DATA/'ro_nrel'/'sine.zip',
               DATA/'heatpump_propane'/'H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx']
    protocol=dict(version=__version__,order=['filter','ro','heatpump'],source_sha256=hashes,
        data_sha256={str(p.relative_to(ROOT)):digest(p) for p in datafiles},
        fixed_rules=dict(filter_rul_horizon_s=30,filter_reference_s=[10,20],filter_calibration_id_mod5=0,
            normal_quantile=.99,heatpump_ridge=.001,heatpump_log_floor=.02,heatpump_temperature_floor_k=.2),
        no_test_based_tuning=True,missing_ground_truth_policy='binary diagnostic metrics null, never treat absence of labels as healthy')
    protocol_hash=save('protocol.json',protocol);results={}
    for name,fn in [('filter',filter_run),('ro',ro_run),('heatpump',hp_run)]:
        results[name]=fn();save(name+'_results.json',results[name]);print(name,'completed',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):digest(p) for p in sources} and digest(OUT/'protocol.json')==protocol_hash
    result=dict(schema='equipment-diagnostics.acquired-measured-validation.v1',version=__version__,protocol_sha256=protocol_hash,
        source_sha256=hashes,modules=results)
    save('results.json',result)
    print(json.dumps({k:v['comparison'] for k,v in results.items()},indent=2))
if __name__=='__main__':main()
