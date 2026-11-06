"""Literature-informed signed CUSUM candidates; freeze before reusing known tests."""
import csv,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import (SensorBatch,SignedResidualCUSUM,LoadConditionedPressureDiagnostic,
    HeatPumpPerformanceDiagnostic,evaporator_conductance_proxy,__version__)
from equipment_diagnostics.evaluation import binary_metrics
from measured_validation_data import hp_table,hp_batch,concatenate,HP_CHANNELS
from improve_stage56 import residual_batch
from validate_independent_marine import make as marine_batch

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/literature_improvement'
MARINE=ROOT/'outputs/completion_7_13/independent_marine';HP=ROOT/'outputs/stage56_ensemble'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,value):
    p=OUT/n;p.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');return sha(p)
def aggregate(rows):return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm','valid','eligible')])

SOURCES=[dict(title='NIST tabular CUSUM',url='https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm',
    use='Signed standardized one-sided C=max(0,C+z-k); predeclare target0.5sigma so k=.25. Do not use independent-normal ARL formulas.'),
 dict(title='NIST EWMA',url='https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc324.htm',
    use='Small persistent changes motivate temporal monitoring; previous EWMA retained as historical baseline, not newly invented improvement.'),
 dict(title='Larsen et al.2019, Model based Level Shift Detection in Autocorrelated Data Streams using a moving window',url='https://arxiv.org/abs/1907.05453',
    use='Autocorrelation invalidates naive independence assumptions. We diagnose dependence and use blocked calibration; not reproducing their moving-window test.'),
 dict(title='Politis and Romano1994, The Stationary Bootstrap',url='https://doi.org/10.1080/01621459.1994.10476870',
    use='Preserve short-range serial dependence by resampling blocks. Our fixed-length noncircular within-episode resampling is a stated adaptation, not their geometric-length stationary bootstrap.'),
 dict(title='Bootstrap Design of Control Charts for Autocorrelated Data2007',url='https://www.research.unipd.it/handle/11577/2474400',
    use='Control limits should account for dependent residuals and parameter uncertainty; ours conditions on a frozen upstream model and does not refit bootstrap parameters or reproduce AR-sieve calibration.'),
 dict(title='Bellanco et al.2022, Common fault effects on a natural refrigerant, variable-speed heat pump',url='https://doi.org/10.1016/j.ijrefrig.2021.10.017',
    use='Same propane experimental system: variable-speed control compensates faults, and evaporator-flow fault has weak COP effect. Study a joint signed residual direction; not assuming COP alone suffices. The chosen projection is our implementation, not their algorithm.'),
 dict(title='Soft fault detection strategies in heat pumps: A case study investigating virtual sensor methodologies for evaporator fouling',url='https://doi.org/10.1016/j.csite.2024.105508',
    use='Motivates physics-derived evaporator-side features and experimental checks. Our (Qcond-W)/(Tsource,in-Tevap) proxy is a simplification we derive, not their virtual airflow algorithm; missing source measurements cannot be manufactured.'),
 dict(title='Experimental validation of a neural-network-based method for fault detection in heat pump evaporators',url='https://publications.rwth-aachen.de/record/1038664',
    use='Supports decoupled evaporator flow features and experimental validation; does not establish that our available channels can recover water flow or weak faults.')]

def signal_batch(b,signal,context,valid,unit,basis):
    return SensorBatch(b.time_s,np.column_stack((signal,context)),('signal','context'),('1',unit),b.clock_id,b.asset_id,b.origin,
        valid=np.broadcast_to(np.asarray(valid,bool)[:,None],(len(signal),2)),episodes=b.episodes,modes=b.modes,
        metadata={'input_model':'frozen upstream signed residual; gold labels excluded','signal_basis_id':basis})

def fit_variants(train,cal,unit,step,gap,persistence):
    models={};errors={}
    for name,block,whiten in [('signed_empirical',None,False),('signed_block60',60.,False),
                            ('innovation_empirical',None,True),('innovation_block60',60.,True)]:
        m=SignedResidualCUSUM(dict(signal='signal',context='context'),context_unit=unit,reference_step_s=step,
            drift_sigma=.25,scale_floor=.05,minimum_limit=5.,prewhiten=whiten,max_gap_s=gap,persistence_s=persistence)
        m.fit(train)
        try:m.calibrate(cal,block_s=block,horizon_s=3600,replicates=256,quantile=.99,seed=20261106)
        except ValueError as e:errors[name]=str(e);continue
        assert not m.score(cal).alarms.any();models[name]=m
    return models,errors

def marine():
    old=read(MARINE/'frozen.json');source=ROOT/'research_support/public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip'
    assert sha(source)==old['raw_sha256'];z=zipfile.ZipFile(source)
    refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'))
    ref=pd.read_csv(io.BytesIO(z.read(refname)),skiprows=[1,2]);bs={}
    for key,indices in old['split_indices'].items():
        ix=np.asarray(indices);ep=np.cumsum(np.r_[True,np.diff(ix)>1]);bs[key]=marine_batch(ref.iloc[ix],refname,True,ep)
        assert bs[key].fingerprint==old['fingerprints'][key]
    cfg=old['models']['load_conditioned_pressure']
    upstream=LoadConditionedPressureDiagnostic(dict(pressure_drop='dp',shaft_power='power',engine_speed='speed'),**cfg['params'],persistence_s=10,max_gap_s=5).set_reference(cfg['reference'])
    def inputs(b):
        r=upstream.score(b)
        with np.errstate(all='ignore'):x=np.log(b.values[:,0]/r.metrics['expected_pressure_drop_pa'])
        return signal_batch(b,x,np.ones(len(x)),r.valid,'1',sha(MARINE/'frozen.json')+':signed_log_pressure_ratio')
    train,cal=inputs(bs['train']),inputs(bs['calibration'])
    models,errors=fit_variants(train,cal,'1',1.,5.,10.)
    frozen=dict(version=__version__,baseline_sha256=sha(MARINE/'results.json'),normal_fingerprints=old['fingerprints'],
        signal='signed log(measuredDP / frozen load/rpm expectedDP)',
        upstream_reference_sha256=sha(MARINE/'frozen.json'),
        variants={k:dict(channels=m.channels,params={**m.params,'max_gap_s':m.max_gap_s,'persistence_s':m.persistence_s},reference=m.reference) for k,m in models.items()},unavailable_variants=errors,
        split='exact v0.14 global20s-purged splits; same four fault files reused',
        adoption_rule='No worse sample recall/FPR/coverage than baseline, per-load recall loss<=0, maximum event delay no worse; new blind data absent.')
    fh=save('marine_frozen.json',frozen)
    baseline=pd.read_csv(MARINE/'predictions.csv');rows={k:[] for k in ['baseline',*models]};files=[]
    records=[]
    for name in [refname,*old['test_files']]:
        if name==refname:b=bs['normal_evaluation'];label=np.zeros(len(b.time_s),bool)
        else:
            d=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);b=marine_batch(d,name);label=d['Anomaly State'].to_numpy(bool)
        base=upstream.score(b);prior=baseline[baseline.file==name]
        assert np.array_equal(base.alarms,prior.load_conditioned_pressure_alarm.to_numpy(bool))
        assert np.array_equal(base.valid,prior.load_conditioned_pressure_valid.to_numpy(bool))
        rr={k:m.score(inputs(b)) for k,m in models.items()}
        rr={'baseline':base,**rr};per={}
        for key,r in rr.items():
            item=dict(label=label,alarm=r.alarms,valid=r.valid,eligible=np.ones(len(label),bool));rows[key].append(item);per[key]=aggregate([item])
        files.append(dict(file=name,metrics=per))
        for i,t in enumerate(b.time_s):records.append([name,t,int(label[i]),*[v for r in rr.values() for v in (int(r.valid[i]),int(r.alarms[i]),r.scores[i] if r.valid[i] else '')]])
    with (OUT/'marine_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['file','time_s','label',*[k+'_'+a for k in rows for a in ('valid','alarm','score')]]);w.writerows(records)
    assert sha(OUT/'marine_frozen.json')==fh
    return dict(frozen_sha256=fh,comparison={k:aggregate(v) for k,v in rows.items()},files=files,unavailable_variants=errors,
        evidence='reused actual laboratory apparatus data; no new independent fault qualification')

def hp():
    upstream_cfg=read(ROOT/'outputs/filter_heatpump_operating_points/heatpump_frozen.json')
    upstream=HeatPumpPerformanceDiagnostic(HP_CHANNELS,**upstream_cfg['parameters'],persistence_s=30).set_reference(upstream_cfg['reference'])
    old=read(HP/'heatpump_frozen.json');splits=old['splits'];batches={'train':[],'calibration':[]};normal=[]
    for sheet in ['NF10','NF12']:
        d=hp_table(sheet);b,_,_,_=hp_batch(d,sheet)
        for key in batches:batches[key].append(b.subset(np.isin(d.index,splits[sheet][key])))
        normal.append((sheet,d,np.isin(d.index,splits[sheet]['evaluation'])))
    train=concatenate(batches['train']);cal=concatenate(batches['calibration'])
    assert train.fingerprint==old['normal_training_fingerprint'] and cal.fingerprint==old['normal_calibration_fingerprint']
    # Fixed joint direction (+Te-deficit,+power,+speed,+COP-deficit), chosen from
    # physical fault-response rationale and prior profile, not this evaluation.
    tr=residual_batch(train,upstream.score(train),upstream);groups=[]
    for context in np.unique(tr.values[tr.valid.all(axis=1),-1]):
        mask=tr.valid.all(axis=1)&(tr.values[:,-1]==context);x=tr.values[mask,:4];center=x.mean(axis=0)
        cov=np.cov(x,rowvar=False);cov=.9*cov+.1*np.diag(np.diag(cov))+np.eye(4)*1e-8
        direction=np.ones(4);weights=np.linalg.solve(cov,direction);weights/=np.sqrt(direction@weights)
        groups.append(dict(context=float(context),center=center.tolist(),weights=weights.tolist()))
    def inputs(b):
        r=upstream.score(b);j=residual_batch(b,r,upstream);signal=np.full(len(b.time_s),np.nan)
        for group in groups:
            mask=j.values[:,-1]==group['context'];signal[mask]=(j.values[mask,:4]-group['center'])@group['weights']
        basis=hashlib.sha256(json.dumps(groups,sort_keys=True).encode()).hexdigest()+':'+sha(ROOT/'outputs/filter_heatpump_operating_points/heatpump_frozen.json')
        return signal_batch(b,signal,b.values[:,-1],r.valid&np.isfinite(signal),'W',basis)
    models,errors=fit_variants(inputs(train),inputs(cal),'W',10.,60.,0.)
    def proxy_inputs(b):
        # 10C is the nominal test-source inlet condition in Bellanco Table1,
        # NOT a newly measured sensor channel in the workbook.
        q,p,te=b.values[:,0],b.values[:,1],b.values[:,2]
        a=evaporator_conductance_proxy(q,p,te,283.15)
        with np.errstate(all='ignore'):x=-np.log(a['conductance_proxy_w_k'])
        good=b.valid.all(axis=1)&a['valid']
        return signal_batch(b,x,b.values[:,-1],good,'W','apparent_evaporator_conductance:nominal_source283.15K:Qcond-minus-W:v1')
    proxy_models,proxy_errors=fit_variants(proxy_inputs(train),proxy_inputs(cal),'W',10.,60.,0.)
    # Only the predeclared empirical/block variants for this physical proxy;
    # AR1 proxy variants are not another tuning grid.
    models.update({'source_proxy_'+k:m for k,m in proxy_models.items() if k.startswith('signed_')})
    errors.update({'source_proxy_'+k:v for k,v in proxy_errors.items() if k.startswith('signed_')})
    fh=save('heatpump_frozen.json',dict(version=__version__,projection_groups=groups,
        normal_training_fingerprint=train.fingerprint,normal_calibration_fingerprint=cal.fingerprint,splits=splits,
        upstream_reference_sha256=sha(ROOT/'outputs/filter_heatpump_operating_points/heatpump_frozen.json'),
        baseline_predictions_sha256=sha(HP/'heatpump_predictions.csv'),
        source_proxy=dict(source_inlet_temperature_k=283.15,basis='nominal test condition from Bellanco Table1, not measured',
            equation='-log((Qcond-W)/(Tsource,in-Tevap))',scope='apparent conductance proxy, neglects losses/storage and is not UA or a virtual flow meter'),
        variants={k:dict(channels=m.channels,params={**m.params,'max_gap_s':m.max_gap_s,'persistence_s':m.persistence_s},reference=m.reference) for k,m in models.items()},unavailable_variants=errors,
        policy='Additive OR with frozen v0.13 decisions; normal-only signed projection/CUSUM; same evaluation reused; exact upstream180s exclusion maintained.'))
    baseline=pd.read_csv(HP/'heatpump_predictions.csv');rows={k:[] for k in ['baseline',*models]};records=[];files=[]
    for sheet,d,selection in normal+[(s,None,None) for s in ['EF10','EF12','CVL10','CVL12','LL10','LL12','OC10','OC12']]:
        if d is None:d=hp_table(sheet)
        b,e,y,codes=hp_batch(d,sheet)
        if selection is not None:b=b.subset(selection);e=e[selection];y=y[selection];codes=codes[selection];d=d.loc[selection]
        oldrows=baseline[baseline.sheet==sheet];assert np.array_equal(oldrows.source_row,d.index)
        oldv=oldrows.after_valid.to_numpy(bool);olda=oldrows.after_alarm.to_numpy(bool)
        assert np.array_equal(oldrows.label.to_numpy(bool),y)
        rr={k:m.score(proxy_inputs(b) if k.startswith('source_proxy_') else inputs(b)) for k,m in models.items()};category='normal' if sheet.startswith('NF') else sheet.rstrip('0123456789')
        policies={'baseline':(oldv,olda)}
        for k,r in rr.items():
            # Preserve the established decision wherever the new path abstains.
            policies[k]=(oldv,olda|(r.alarms&r.valid&oldv))
        per={}
        for k,(valid,alarm) in policies.items():
            item=dict(label=y,alarm=alarm,valid=valid,eligible=e,category=category);rows[k].append(item);per[k]=aggregate([item])
        files.append(dict(sheet=sheet,metrics=per))
        for i,t in enumerate(b.time_s):records.append([sheet,str(codes[i]),int(d.index[i]),float(d['Fault intensity'].iloc[i]),t,int(y[i]),int(e[i]),
            *[v for valid,alarm in policies.values() for v in (int(valid[i]),int(alarm[i]))],
            *[r.scores[i] if r.valid[i] else '' for r in rr.values()]])
    with (OUT/'heatpump_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['sheet','experiment','source_row','intensity','time_s','label','eligible',*[k+'_'+a for k in rows for a in ('valid','alarm')],*[k+'_score' for k in rr]]);w.writerows(records)
    assert sha(OUT/'heatpump_frozen.json')==fh
    return dict(frozen_sha256=fh,comparison={k:aggregate(v) for k,v in rows.items()},
        by_category={k:{c:aggregate([x for x in v if x['category']==c]) for c in ['normal','EF','CVL','LL','OC']} for k,v in rows.items()},
        files=files,unavailable_variants=errors,evidence='reused same heat-pump prototype evaluation, not new independent EF data')

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    save('literature.json',dict(retrieved_date='2026-11-06',sources=SOURCES))
    sources=[Path(__file__),ROOT/'scripts/improve_stage56.py',ROOT/'scripts/measured_validation_data.py',ROOT/'scripts/validate_independent_marine.py',*sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):sha(p) for p in sources}
    save('protocol.json',dict(version=__version__,source_sha256=hashes,literature_sha256=sha(OUT/'literature.json'),
        candidates_predeclared=['signed_empirical','signed_block60','innovation_empirical','innovation_block60'],drift_sigma=.25,block_s=60,horizon_s=3600,
        revision='Innovation variants added after initial signed results; first attempt archived. Same evaluations reused for this development extension; AR1 estimated on normal training only.',
        physical_proxy_revision='Evaporator conductance proxy added after weak EF remained unchanged; prior innovation attempt archived. Nominal source10C from the original experimental paper, not fitted to fault data. Same evaluations reused.',
        replicates=256,seed=20261106,calibration_quantile=.99,reused_evaluation=True,
        new_independent_fault_evaluation=False,baseline_results_sha256=dict(marine=sha(MARINE/'results.json'),hp=sha(HP/'results.json'))))
    mr=marine();print('marine evaluated',flush=True);hr=hp();print('heatpump evaluated',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):sha(p) for p in sources}
    result=dict(version=__version__,source_sha256=hashes,marine=mr,heatpump=hr,new_independent_fault_metrics=None)
    save('results.json',result)
    print(json.dumps(dict(marine=mr['comparison'],heatpump=hr['comparison']),indent=2))
if __name__=='__main__':main()
