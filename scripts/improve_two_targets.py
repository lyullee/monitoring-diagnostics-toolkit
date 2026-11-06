"""Filter context -> heatpump early detection -> independent alarm-release policy.

Exact historical outer splits. Select expectation models by purged normal-only
CV; freeze references before reusing known evaluation. No fault fitting.
"""
import csv,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import (SensorBatch,ConditionalResidualDiagnostic,WindowChangeDiagnostic,LoadConditionedPressureDiagnostic,HysteresisAlarmDiagnostic,__version__)
from equipment_diagnostics.physical_inputs import append_observations
from equipment_diagnostics.chiller_staged import design
from equipment_diagnostics.evaluation import binary_metrics
from measured_validation_data import hp_table,hp_batch,concatenate
from validate_independent_marine import make as marine_legacy

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/two_target_improvement'
MARINE=ROOT/'outputs/completion_7_13/independent_marine';BASE=ROOT/'outputs/literature_improvement'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,value):
    p=OUT/name;p.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8');return sha(p)
def spec(unit,log=False):return dict(unit=unit,log=log)
def target(unit,log,direction,floor):return dict(unit=unit,log=log,direction=direction,scale_floor=floor)
def metrics(rows):return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm','valid','eligible')])

def normal_cv(b,feature_sets,targets,gap,parent_groups=False):
    # Three120s time-block folds entirely INSIDE the established training set.
    # Remove fitting rows within20s of any validation row, including across bins.
    fold=(np.floor((b.time_s-b.time_s.min())/120).astype(np.int64)%3)
    if parent_groups:
        parents=np.array([str(e).split('|')[0] for e in b.episodes])
        lookup={name:i%3 for i,name in enumerate(np.unique(parents))}
        fold=np.array([lookup[p] for p in parents])
    result=[]
    for name,features in feature_sets.items():
        for degree in (1,2):
            for ridge in (.01,.1,1.):
                losses=[];details=[]
                for f in range(3):
                    hold=fold==f;fit=~hold;t=b.time_s[hold];j=np.searchsorted(t,b.time_s)
                    distance=np.minimum(abs(b.time_s-t[np.clip(j,0,len(t)-1)]),abs(b.time_s-t[np.clip(j-1,0,len(t)-1)]))
                    fit &= distance>20
                    if fit.sum()<30 or hold.sum()<10:raise ValueError('insufficient purged inner fold')
                    m=ConditionalResidualDiagnostic({k:k for k in [*features,*targets]},features=features,targets=targets,
                        degree=degree,ridge_alpha=ridge,max_gap_s=gap)
                    tr=b.subset(fit);va=b.subset(hold);m.fit(tr)
                    x,y,valid=m._inputs(va);model=m.reference['conditional_model']
                    prediction=design((x-model['center'])/model['scale'],degree)@np.asarray(model['coefficients'])+model['residual_center']
                    _,yt,vtr=m._inputs(tr);scale=np.maximum(yt[vtr].std(axis=0),[s['scale_floor'] for s in targets.values()])
                    # Include out-of-domain validation predictions in selection
                    # error, rather than winning by dropping hard conditions.
                    loss=float(np.mean(((prediction[valid]-y[valid])/scale)**2));losses.append(loss)
                    details.append(dict(fold=f,fit_rows=int(fit.sum()),hold_rows=int(hold.sum()),
                        fit_fingerprint=tr.fingerprint,hold_fingerprint=va.fingerprint,
                        minimum_temporal_separation_s=float(distance[fit].min()),loss=loss))
                result.append(dict(name=name,features=features,degree=degree,ridge_alpha=ridge,
                    mean_scaled_mse=float(np.mean(losses)),folds=details))
    chosen=min(result,key=lambda x:(x['mean_scaled_mse'],x['degree'],len(x['features'])))
    return chosen,result

def fit_profiles(train,cal,feature_sets,targets,gap,persistence,windows,parent_groups=False,quantile=.999,minimum_z=3.,calibration_role=None):
    chosen,cv=normal_cv(train,feature_sets,targets,gap,parent_groups);models={};errors={}
    for window in windows:
        name='point' if window==0 else 'mean'+str(int(window))
        m=ConditionalResidualDiagnostic({k:k for k in [*chosen['features'],*targets]},features=chosen['features'],targets=targets,
            degree=chosen['degree'],ridge_alpha=chosen['ridge_alpha'],window_s=window,minimum_z=minimum_z,calibration_role=calibration_role,
            persistence_s=persistence if window==0 else 0,max_gap_s=gap)
        m.fit(train)
        try:m.calibrate(cal,quantile=quantile)
        except ValueError as e:errors[name]=str(e);continue
        models[name]=m
    return models,dict(chosen=chosen,candidates=cv,criterion='minimum threefold purged normal-training scaled prediction MSE',
        grouping='whole parent experiment' if parent_groups else '120s time blocks',unavailable=errors)

def frozen_models(models):return {k:dict(kind=m.kind,channels=m.channels,params={**m.params,'max_gap_s':m.max_gap_s,'persistence_s':m.persistence_s},reference=m.reference) for k,m in models.items()}
def restored_models(records):
    classes={'conditional_normal_residual':ConditionalResidualDiagnostic,'window_residual_change':WindowChangeDiagnostic}
    return {k:classes[c['kind']](c['channels'],**c['params']).set_reference(c['reference']) for k,c in records.items()}

def marine():
    legacy=read(MARINE/'frozen.json');path=ROOT/'research_support/public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip'
    assert sha(path)==legacy['raw_sha256'];z=zipfile.ZipFile(path);refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'))
    ref=pd.read_csv(io.BytesIO(z.read(refname)),skiprows=[1,2]);batches={}
    def batch(d,name,reference=False,episodes=None):
        old=marine_legacy(d,name,reference,episodes)
        return SensorBatch(old.time_s,np.column_stack((d['Shaft Power']*1000,d['Engine Speed']/60,d['Engine room Temp.']+273.15,
            d['Charge Air IC Cooling Water Temp. In']+273.15,d['Compressor Filter Loss'])),
            ('power','speed','ambient','cooling','dp'),('W','1/s','K','K','Pa'),old.clock_id,old.asset_id,old.origin,episodes=old.episodes,
            metadata={'signal_basis_id':'marine_measured_power_speed_room_cooling_DP:v1'})
    for key,ix in legacy['split_indices'].items():
        ix=np.asarray(ix);ep=np.cumsum(np.r_[True,np.diff(ix)>1]);batches[key]=batch(ref.iloc[ix],refname,True,ep)
        assert marine_legacy(ref.iloc[ix],refname,True,ep).fingerprint==legacy['fingerprints'][key]
    original_fingerprints={k:b.fingerprint for k,b in batches.items()}
    extra={'train':['AC_Fouling_40_Load.csv','AC_Fouling_75_Load.csv','Turbine_Degradation_60_Load.csv'],
           'calibration':['AC_Fouling_60_Load.csv','Turbine_Degradation_40_Load.csv','Turbine_Degradation_85_Load.csv']}
    manifest={};collections={k:[('Reference_Data.csv',batches[k])] for k in extra}
    for split,names in extra.items():
        for basename in names:
            name=next(n for n in z.namelist() if n.endswith('/'+basename));d=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2])
            normal=d['Anomaly State']==0;part=d.loc[normal].copy()
            assert part['Compressor Filter Loss'].notna().all() and name not in legacy['test_files']
            b=batch(part,name);collections[split].append((basename,b))
            manifest[name]=dict(split=split,rows=len(part),source_rows=part.index.tolist(),label_rule='publisher Anomaly State==0 only',
                fingerprint=b.fingerprint,member_sha256=hashlib.sha256(z.read(name)).hexdigest())
    assert not set(extra['train'])&set(extra['calibration'])
    def collect(items):
        offset=0.;times=[];values=[];valid=[];episodes=[]
        for name,b in items:
            t=b.time_s-b.time_s[0]+offset;offset=float(t[-1]+1000)
            times.append(t);values.append(b.values);valid.append(b.valid)
            episodes.extend(name+'|'+str(e) for e in b.episodes)
        first=items[0][1]
        return SensorBatch(np.concatenate(times),np.concatenate(values),first.channels,first.units,
            'reference_collection_within_file_offsets',first.asset_id,first.origin,valid=np.concatenate(valid),episodes=np.asarray(episodes),
            metadata={'signal_basis_id':first.metadata['signal_basis_id'],'clock_scope':'independent normal files concatenated for fitting only; not a physical event timeline'})
    batches['train']=collect(collections['train']);batches['calibration']=collect(collections['calibration'])
    save('marine_added_normal_manifest.json',dict(files=manifest,original_fingerprints=original_fingerprints,
        newness='previously unused normal prefixes from six other experiments, same apparatus; no AF evaluation rows moved',
        added_train_rows=sum(v['rows'] for v in manifest.values() if v['split']=='train'),
        added_calibration_rows=sum(v['rows'] for v in manifest.values() if v['split']=='calibration')))
    fs=dict(load=dict(power=spec('W',True),speed=spec('1/s',True)),
        ambient=dict(power=spec('W',True),speed=spec('1/s',True),ambient=spec('K')),
        ambient_cooling=dict(power=spec('W',True),speed=spec('1/s',True),ambient=spec('K'),cooling=spec('K')))
    ts=dict(dp=target('Pa',True,1,np.log1p(.05)))
    models,cv=fit_profiles(batches['train'],batches['calibration'],fs,ts,5,10,[0],parent_groups=True,quantile=.9999)
    oldcfg=legacy['models']['load_conditioned_pressure']
    oldmodel=LoadConditionedPressureDiagnostic(dict(pressure_drop='dp',shaft_power='power',engine_speed='speed'),
        **oldcfg['params'],persistence_s=10,max_gap_s=5).set_reference(oldcfg['reference'])
    def growth_inputs(b):
        r=oldmodel.score(b)
        with np.errstate(all='ignore'):signal=np.log(b.values[:,4]/r.metrics['expected_pressure_drop_pa'])
        return SensorBatch(b.time_s,signal[:,None],('signal',),('1',),b.clock_id,b.asset_id,b.origin,
            valid=r.valid[:,None],episodes=b.episodes,metadata={'signal_basis_id':sha(MARINE/'frozen.json')+':signed_log_DP_residual'})
    growth=WindowChangeDiagnostic(dict(signal='signal'),mean_window_s=60,lags_s=[60,300,900],minimum_change=np.log1p(.05),
        persistence_s=10,max_gap_s=5).fit(growth_inputs(batches['train'])).calibrate(growth_inputs(batches['calibration']),quantile=.9999)
    models['growth']=growth
    # Short-window ablation separates rapid changes from slow normal drift.
    # Same normal train/cal only; no evaluation-derived threshold adjustment.
    models['fast_change']=WindowChangeDiagnostic(dict(signal='signal'),mean_window_s=60,lags_s=[60],minimum_change=np.log1p(.05),
        persistence_s=10,max_gap_s=5).fit(growth_inputs(batches['train'])).calibrate(growth_inputs(batches['calibration']),quantile=.9999)
    save('marine_normal_cv.json',cv)
    h=save('marine_frozen.json',dict(version=__version__,models=frozen_models(models),normal_cv_sha256=sha(OUT/'marine_normal_cv.json'),
        outer_split=legacy['split_indices'],normal_fingerprints={k:b.fingerprint for k,b in batches.items()},
        baseline_frozen_sha256=sha(MARINE/'frozen.json'),baseline_prediction_sha256=sha(MARINE/'predictions.csv'),
        added_normal_manifest_sha256=sha(OUT/'marine_added_normal_manifest.json'),
        target='publisher filter-covering state, not RUL',fallback='Use baseline only when new context model abstains; record new-path support separately.',
        policy='Prediction model selected on normal training only, whole-parent normal CV. Original splits preserved; six previously unused NORMAL prefixes added by whole file to train/cal. Calibration q.9999 plus min3sigma. AF evaluation normal prefixes never used.'))
    models=restored_models(read(OUT/'marine_frozen.json')['models'])
    baseline=pd.read_csv(MARINE/'predictions.csv');rows={k:[] for k in ['baseline',*models]};common={k:[] for k in models};files=[];records=[]
    for name in [refname,*legacy['test_files']]:
        if name==refname:b=batches['normal_evaluation'];y=np.zeros(len(b.time_s),bool)
        else:
            frame=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);b=batch(frame,name);y=frame['Anomaly State'].to_numpy(bool)
        g=baseline[baseline.file==name];np.testing.assert_array_equal(g.time_s,b.time_s);assert np.array_equal(g.label.to_numpy(bool),y)
        oldv=g.load_conditioned_pressure_valid.to_numpy(bool);olda=g.load_conditioned_pressure_alarm.to_numpy(bool)
        rr={k:m.score(growth_inputs(b) if m.kind=='window_residual_change' else b) for k,m in models.items()};policies={'baseline':(oldv,olda)}
        for k,r in rr.items():policies[k]=((oldv,olda|(r.valid&r.alarms&oldv)) if models[k].kind=='window_residual_change' else (oldv|r.valid,np.where(r.valid,r.alarms,olda)))
        per={}
        for key,(v,a) in policies.items():
            row=dict(label=y,valid=v,alarm=a,eligible=np.ones(len(y),bool));rows[key].append(row);per[key]=metrics([row])
        for k,r in rr.items():
            mask=oldv&r.valid
            common[k].append(dict(label=y,valid=mask,alarm=r.alarms,eligible=np.ones(len(y),bool),before=olda))
        files.append(dict(file=name,metrics=per,new_path_valid_rows={k:int(r.valid.sum()) for k,r in rr.items()},total_rows=len(y)))
        for i,t in enumerate(b.time_s):records.append([name,t,int(y[i]),*[a for v,alarm in policies.values() for a in (int(v[i]),int(alarm[i]))],
            *[a for r in rr.values() for a in (int(r.valid[i]),int(r.alarms[i]),r.scores[i] if r.valid[i] else '')]])
    with (OUT/'marine_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['file','time_s','label',*[k+'_'+v for k in policies for v in ('valid','alarm')],*[k+'_path_'+v for k in rr for v in ('valid','alarm','score')]]);w.writerows(records)
    assert sha(OUT/'marine_frozen.json')==h
    comparisons={k:metrics(v) for k,v in rows.items()}
    common_metrics={k:dict(after=metrics(v),before=metrics([{**r,'alarm':r['before']} for r in v])) for k,v in common.items()}
    return dict(frozen_sha256=h,comparison=comparisons,common_valid=common_metrics,files=files,
        new_path_coverage={k:sum(x['new_path_valid_rows'][k] for x in files)/sum(x['total_rows'] for x in files) for k in models},
        evidence='reused measured evaluation; unchanged splits, no fresh independent qualification')

HP_PATH=ROOT/'research_support/public_data/acquisition_20261105/heatpump_propane/H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx'
def hp_enriched(sheet,d,b,auxiliary=False):
    q,p=b.values[:,0],b.values[:,1]
    with np.errstate(all='ignore'):cop=q/p
    cols={'load':(b.values[:,-1],'W',b.valid[:,-1]),'power':(p,'W',b.valid[:,1]),
        'evap':(b.values[:,2],'K',b.valid[:,2]),'cond':(b.values[:,3],'K',b.valid[:,3]),
        'rpm':(b.values[:,7],'1/s',b.valid[:,7]),'cop':(cop,'1',np.isfinite(cop)&b.valid[:,0]&b.valid[:,1])}
    if auxiliary:
        raw=pd.read_excel(HP_PATH,sheet_name=sheet).iloc[1:]
        # No auxiliary test codes/intensities are read or used for alignment.
        at=pd.to_datetime(raw['Date '],errors='coerce');values=pd.to_numeric(raw['Superheating'],errors='coerce')
        good=at.notna()&values.notna();at=at[good].to_numpy(dtype='datetime64[ns]').astype('int64')/1e9;values=values[good].to_numpy(float)
        if np.any(np.diff(at)<=0):raise ValueError('invalid auxiliary logger clock')
        ix=np.searchsorted(at,b.time_s,side='right')-1;j=np.maximum(ix,0);age=b.time_s-at[j]
        valid=(ix>=0)&(age>=0)&(age<=5)&(at[j]>=b.time_s[0])&(values[j]>=0)
        cols['sh']=(values[j],'K',valid);cols['sh_age']=(age,'s',valid)
    return SensorBatch(b.time_s,np.column_stack([v[0] for v in cols.values()]),tuple(cols),tuple(v[1] for v in cols.values()),
        b.clock_id,b.asset_id,b.origin,valid=np.column_stack([v[2] for v in cols.values()]),episodes=b.episodes,modes=b.modes,
        metadata={'signal_basis_id':'hp_main'+('_aux_causal5s' if auxiliary else '')+':v1',
            'aux_clock_caveat':'publisher wall clocks assumed comparable; synchronization error/delivery latency not independently verified' if auxiliary else None})

def heatpump():
    old=read(BASE/'heatpump_frozen.json');normal=[];tr={k:[] for k in ('main','aux')};ca={k:[] for k in tr}
    for sheet in ('NF10','NF12'):
        d=hp_table(sheet);b,_,_,_=hp_batch(d,sheet)
        for key,aux in [('main',False),('aux',True)]:
            for split,dest in [('train',tr),('calibration',ca)]:
                mask=np.isin(d.index,old['splits'][sheet][split]);part=b.subset(mask)
                dest[key].append(hp_enriched(sheet,d.loc[mask],part,aux))
        normal.append((sheet,d,np.isin(d.index,old['splits'][sheet]['evaluation'])))
    fs=dict(load=dict(load=spec('W')),load_cond=dict(load=spec('W'),cond=spec('K')))
    targets=dict(evap=target('K',False,-1,.2),power=target('W',True,1,.02),rpm=target('1/s',True,1,.02),cop=target('1',True,-1,.02))
    allmodels={};cvrecords={}
    for key in tr:
        train=concatenate(tr[key]);cal=concatenate(ca[key]);ts={**targets,**(dict(sh=target('K',False,0,.2)) if key=='aux' else {})}
        ms,cv=fit_profiles(train,cal,fs,ts,60,30,[0,60]);cvrecords[key]=cv
        allmodels.update({key+'_'+n:m for n,m in ms.items()})
    # Saturation temperature is an observed RESPONSE for this branch, not a
    # condition gate that removes EF10.1. Per-load calibration avoids pooling
    # the much wider normal12.3kW variation into10.2kW limits.
    train=concatenate(tr['main']);cal=concatenate(ca['main'])
    for name,ts in [('response',{**targets,'cond':target('K',False,0,.2)}),('without_cond',targets)]:
        ms,cv=fit_profiles(train,cal,dict(load=fs['load']),ts,60,30,[0,60],minimum_z=1.,calibration_role='load')
        cvrecords[name]=cv;allmodels.update({name+'_'+n:m for n,m in ms.items()})
    save('heatpump_normal_cv.json',cvrecords)
    h=save('heatpump_frozen.json',dict(version=__version__,models=frozen_models(allmodels),normal_cv_sha256=sha(OUT/'heatpump_normal_cv.json'),
        splits=old['splits'],normal_training_fingerprints={k:concatenate(v).fingerprint for k,v in tr.items()},
        normal_calibration_fingerprints={k:concatenate(v).fingerprint for k,v in ca.items()},
        baseline_prediction_sha256=sha(BASE/'heatpump_predictions.csv'),raw_sha256=sha(HP_PATH),
        auxiliary_scope='Experimental only: separate wall-clock logger, causal age<=5s, no index/code/intensity join; clock uncertainty unverified.',
        policy='Normal-only CV/calibration; OR additional raw detection path with frozen v0.15 baseline. Preserve baseline when path abstains. No off-delay in raw comparison.'))
    allmodels=restored_models(read(OUT/'heatpump_frozen.json')['models'])
    baseline=pd.read_csv(BASE/'heatpump_predictions.csv');rows={k:[] for k in ['baseline',*allmodels]};records=[];files=[]
    for sheet,d,selection in normal+[(s,None,None) for s in ['EF10','EF12','CVL10','CVL12','LL10','LL12','OC10','OC12']]:
        if d is None:d=hp_table(sheet)
        b,e,y,codes=hp_batch(d,sheet)
        if selection is not None:b=b.subset(selection);e=e[selection];y=y[selection];codes=codes[selection];d=d.loc[selection]
        g=baseline[baseline.sheet==sheet];assert np.array_equal(g.source_row,d.index)
        oldv=g.signed_block60_valid.to_numpy(bool);olda=g.signed_block60_alarm.to_numpy(bool)
        batches={k:hp_enriched(sheet,d,b,k=='aux') for k in ('main','aux')}
        rr={k:m.score(batches['aux' if k.startswith('aux_') else 'main']) for k,m in allmodels.items()}
        policies={'baseline':(oldv,olda)}
        for k,r in rr.items():policies[k]=(oldv,olda|(r.valid&r.alarms&oldv))
        per={}
        for k,(v,a) in policies.items():
            row=dict(label=y,alarm=a,valid=v,eligible=e);rows[k].append(row);per[k]=metrics([row])
        files.append(dict(sheet=sheet,metrics=per,new_path_valid_rows={k:int((r.valid&e).sum()) for k,r in rr.items()},eligible=int(e.sum())))
        for i,t in enumerate(b.time_s):records.append([sheet,str(codes[i]),int(d.index[i]),float(d['Fault intensity'].iloc[i]),t,int(y[i]),int(e[i]),
            *[a for v,alarm in policies.values() for a in (int(v[i]),int(alarm[i]))],*[a for r in rr.values() for a in (int(r.valid[i]),int(r.alarms[i]),r.scores[i] if r.valid[i] else '')]])
    with (OUT/'heatpump_raw_predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['sheet','experiment','source_row','intensity','time_s','label','eligible',*[k+'_'+v for k in policies for v in ('valid','alarm')],*[k+'_path_'+v for k in rr for v in ('valid','alarm','score')]]);w.writerows(records)
    assert sha(OUT/'heatpump_frozen.json')==h
    return dict(frozen_sha256=h,comparison={k:metrics(v) for k,v in rows.items()},files=files,
        new_path_eligible_coverage={k:sum(x['new_path_valid_rows'][k] for x in files)/sum(x['eligible'] for x in files) for k in allmodels},
        evidence='reused measured evaluation; main-only versus experimental auxiliary-clock paths separate')

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    code=[Path(__file__),ROOT/'scripts/measured_validation_data.py',ROOT/'scripts/validate_independent_marine.py',*sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):sha(p) for p in code}
    save('protocol.json',dict(version=__version__,source_sha256=hashes,reused_evaluation=True,new_independent_fault_test=False,
        stages=['marine normal context','heatpump raw early-detection paths','separate release-delay study'],
        cv=dict(block_s=120,purge_s=20,folds=3,ridge=[.01,.1,1],degrees=[1,2],selection='training-only prediction MSE'),
        calibration=dict(quantile=.999,minimum_z=3),hold_policy_delays_s=[30,60],
        marine_actual_calibration=dict(quantile=.9999,normal_parent_files_augmented=True,change_lags_s=[60,300,900],short_change_ablation_lags_s=[60]),
        heatpump_response_branch=dict(minimum_z=1.,calibration_role='load',temperature_floor_k=.2,
            rationale='condensing temperature treated as response rather than excluding observations as context; sensitivity and session confounding separately assessed'),
        development_revision='Architecture revised after examining earlier reused evaluation; original/augmented context attempts archived. No evaluation rows entered fit or calibration; final evaluation is not blind.',
        baseline_sha256=dict(marine=sha(MARINE/'results.json'),heatpump=sha(BASE/'results.json'))))
    mr=marine();print('1 marine complete',flush=True);hr=heatpump();print('2 heatpump raw complete',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):sha(p) for p in code}
    save('results.json',dict(version=__version__,source_sha256=hashes,marine=mr,heatpump=hr,new_independent_fault_metrics=None))
    print(json.dumps(dict(marine=mr['comparison'],heatpump=hr['comparison']),indent=2))
if __name__=='__main__':main()
