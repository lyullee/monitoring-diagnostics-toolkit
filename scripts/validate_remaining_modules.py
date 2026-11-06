"""Rank 4/5/7/8/9: frozen normal-only simulation comparisons; no field claims."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import (SensorBatch,HeatExchangerDiagnostic,ROMembraneDiagnostic,
    ColumnHydraulicsDiagnostic,SteamTrapDiagnostic,VaporizerDiagnostic,__version__)
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import score_threshold

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'/'remaining_modules'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def batch(cols,units,asset):
    n=max(np.size(a) for a in cols.values())
    return SensorBatch(np.arange(n,dtype=float),np.column_stack([np.broadcast_to(x,(n,)) for x in cols.values()]),
        tuple(cols),tuple(units),'simulation_clock',asset,'simulation')

def heat_data(seed,retention=1):
    from ht.hx import effectiveness_from_NTU
    rng=np.random.default_rng(seed);n=400
    hf=rng.uniform(.4,2.5,n);cf=rng.uniform(.4,2.5,n);hf[:2]=[.4,2.5];cf[2:4]=[.4,2.5]
    ua=retention/(.0001+.0002*hf**-.8+.0003*cf**-.8)
    ch=hf*4180;cc=cf*4180;small=np.minimum(ch,cc)
    eps=np.array([effectiveness_from_NTU(NTU=u/c,Cr=c/max(h,k),subtype='counterflow') for u,c,h,k in zip(ua,small,ch,cc)])
    q=eps*small*70
    return batch(dict(hi=360.,ho=360-q/ch,ci=290.,co=290+q/cc,hf=hf,cf=cf),['K']*4+['kg/s']*2,'heat')

RO_CHANNELS=dict(permeate_flow='q',feed_pressure='pf',concentrate_pressure='pc',permeate_pressure='pp',
    feed_osmotic_pressure='of',concentrate_osmotic_pressure='oc',permeate_osmotic_pressure='op',membrane_temperature='t')
def ro_data(seed,retention=1):
    rng=np.random.default_rng(seed);n=400;t=rng.uniform(288.15,308.15,n);ndp=rng.uniform(.7e6,.9e6,n)
    factor=np.exp(20000/8.31446261815324*(1/t-1/298.15))
    q=retention*2e-12*10*ndp/factor*(1+rng.uniform(-.005,.005,n))
    pf=ndp+4e5;pc=pf-1e5
    return batch(dict(q=q,pf=pf,pc=pc,pp=1e5,of=2e5,oc=3e5,op=0.,t=t,ndp=ndp,factor=factor),
        ['m3/s']+['Pa']*6+['K','Pa','1'],'ro')

def column_data(seed,growth=1):
    rng=np.random.default_rng(seed);n=400;v=rng.uniform(.5,1.5,n);l=rng.uniform(.6,1.4,n)
    v[:2]=[.5,1.5];l[2:4]=[.6,1.4]
    dp=1000*v**1.7*l**.4*growth*(1+rng.uniform(-.005,.005,n))
    return batch(dict(dp=dp,v=v,l=l),['Pa','kg/s','kg/s'],'column')

def aggregate(rows,common=False):
    return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm','common' if common else 'valid','eligible')])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    hc=dict(hot_in='hi',hot_out='ho',cold_in='ci',cold_out='co',hot_flow='hf',cold_flow='cf')
    heat0=HeatExchangerDiagnostic(hc,cp_hot_j_kg_k=4180,cp_cold_j_kg_k=4180)
    heat1=HeatExchangerDiagnostic(hc,cp_hot_j_kg_k=4180,cp_cold_j_kg_k=4180,reference_mode='flow_resistance')
    ro0=ROMembraneDiagnostic(dict(permeate_flow='q',net_driving_pressure='ndp',temperature_correction='factor'),membrane_area_m2=10)
    ro1=ROMembraneDiagnostic(RO_CHANNELS,membrane_area_m2=10,input_mode='pressures_temperature',
        activation_energy_j_mol=20000,temperature_range_k=(285,315))
    cc=dict(pressure_drop='dp',vapor_flow='v',liquid_flow='l')
    col0=ColumnHydraulicsDiagnostic(cc,reference_vapor_flow_kg_s=1,reference_liquid_flow_kg_s=1,vapor_exponent=2,liquid_exponent=1)
    col1=ColumnHydraulicsDiagnostic(cc,reference_vapor_flow_kg_s=1,reference_liquid_flow_kg_s=1,reference_mode='learned_power')
    sc=dict(steam_temperature='steam',trap_temperature='trap',acoustic_level='sound',supply_on='on')
    sp=dict(acoustic_quiet_max=.2,acoustic_loud_min=2,cold_margin_k=40,hot_margin_k=10)
    trap0=SteamTrapDiagnostic(sc,**sp);trap1=SteamTrapDiagnostic(sc,**sp,startup_exclusion_s=60)
    vapor=VaporizerDiagnostic(dict(outlet_temperature='t',mass_flow='q'),shortfall_limit_k=5,
        minimum_outlet_k=280,prediction_mode='minimum_only')
    pairs={'heat':(heat0,heat1),'ro':(ro0,ro1),'column':(col0,col1),'steam_trap':(trap0,trap1)}
    generators={'heat':heat_data,'ro':ro_data,'column':column_data}; development={}; thresholds={}
    for kind,make in generators.items():
        train=make(202611051);cal=make(202611052);thresholds[kind]={};refs={}
        for key,m in zip(('before','after'),pairs[kind]):
            m.fit(train);r=m.score(cal)
            cut=max(1.,float(np.nextafter(np.quantile(r.scores[r.valid],.99),np.inf)))
            thresholds[kind][key]=cut;refs[key]=m.reference
        development[kind]=dict(train_seed=202611051,calibration_seed=202611052,test_seeds=[202611053,202611054],
            train_fingerprint=train.fingerprint,calibration_fingerprint=cal.fingerprint,references=refs,thresholds=thresholds[kind])
    thresholds['steam_trap']={'before':1.,'after':1.}
    code=[Path(__file__),ROOT/'scripts'/'validate_public_data.py',*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in code}
    frozen={'version':__version__,'evidence_type':'simulation_only','development':development,
        'source_sha256':hashes,'policy':'Normal training only, separate normal calibration q99 floor1. '
            'All hyperparameters/physics scenarios specified before test generation. No fault/test tuning.',
        'steam_trap':dict(before_params=trap0.params,after_params=trap1.params),
        'vaporizer':dict(after_params=vapor.params,before_status='cannot_run_without_external_prediction'),
        'test_physics':{'heat':'external ht counterflow epsilon-NTU; prescribed series resistance with flow exponents .8',
            'ro':'prescribed solution-diffusion with explicit test Ea=20kJ/mol and known NDP',
            'column':'empirical prescribed DP=1000*v^1.7*l^.4; not a flooding simulator',
            'steam_trap':'Newton startup plus persistent cold blockage; not acoustic/steam-loss physics',
            'vaporizer':'temperature threshold test only; no vaporization/icing simulator'}}
    path=OUT/'frozen_development.json';path.write_bytes(json.dumps(frozen,indent=2,sort_keys=True).encode());frozen_hash=digest(path)
    snapshots={k:[json.dumps(m.reference,sort_keys=True) for m in ms] for k,ms in pairs.items()}
    scenarios=[('heat','normal',heat_data(202611053),False),('heat','ua_loss_40pct',heat_data(202611054,.6),True),
        ('ro','normal',ro_data(202611053),False),('ro','permeability_loss_40pct',ro_data(202611054,.6),True),
        ('column','normal',column_data(202611053),False),('column','pressure_growth_60pct',column_data(202611054,1.6),True)]
    t=np.arange(600.)
    scenarios += [('steam_trap','normal_cold_start',batch(dict(steam=450.,trap=450-150*np.exp(-t/40),sound=.1,on=1),['K','K','1','1'],'trap'),False),
        ('steam_trap','persistent_cold_blockage',batch(dict(steam=450.,trap=np.full(len(t),300.),sound=.1,on=1),['K','K','1','1'],'trap'),True)]
    rows={k:{p:[] for p in ('before','after')} for k in pairs}; files=[]
    with (OUT/'predictions.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['module','scenario','time_s','label','eligible','before_available','before_valid','before_alarm','after_valid','after_alarm'])
        for kind,name,b,fault in scenarios:
            results=[m.score(b) for m in pairs[kind]];e=np.ones(len(b.time_s),bool);label=np.full(len(e),fault,bool)
            common=results[0].valid&results[1].valid;alarms=[];item=dict(module=kind,scenario=name,fingerprint=b.fingerprint,policies={})
            for key,r in zip(('before','after'),results):
                alarm=score_threshold(r,b,thresholds[kind][key],0);alarms.append(alarm)
                row=dict(label=label,alarm=alarm,valid=r.valid,common=common,eligible=e)
                rows[kind][key].append(row);item['policies'][key]=dict(metrics=aggregate([row]),common_metrics=aggregate([row],True))
                if kind=='heat':
                    item['policies'][key]['ua_retention_relative_std']=float(np.std(r.metrics['ua_w_k'][r.valid]/
                        (r.metrics['expected_ua_w_k'][r.valid] if key=='after' else pairs[kind][0].reference['center'])))
            files.append(item)
            for i,time in enumerate(b.time_s):
                w.writerow([kind,name,time,int(fault),1,1,*[v for r,a in zip(results,alarms) for v in (int(r.valid[i]),int(a[i]))]])
        b=batch(dict(t=np.r_[np.full(300,290.),np.full(300,270.)],q=1),['K','kg/s'],'vaporizer')
        r=vapor.score(b);label=b.values[:,0]<280;e=np.ones(len(label),bool)
        vrow=dict(label=label,alarm=r.alarms,valid=r.valid,common=r.valid,eligible=e)
        files.append(dict(module='vaporizer',scenario='minimum_only',fingerprint=b.fingerprint,
            before_status='not_runnable_missing_external_prediction',policies={'after':dict(metrics=aggregate([vrow]))}))
        for i,time in enumerate(b.time_s):w.writerow(['vaporizer','minimum_only',time,int(label[i]),1,0,0,0,int(r.valid[i]),int(r.alarms[i])])
    comparison={k:{p:dict(metrics=aggregate(v),common_metrics=aggregate(v,True)) for p,v in groups.items()} for k,groups in rows.items()}
    comparison['vaporizer']={'before':{'status':'not_runnable_missing_external_prediction'},'after':{'metrics':aggregate([vrow])}}
    assert snapshots=={k:[json.dumps(m.reference,sort_keys=True) for m in ms] for k,ms in pairs.items()}
    assert digest(path)==frozen_hash and hashes=={str(p.relative_to(ROOT)):digest(p) for p in code}
    result=dict(version=__version__,evidence_type='simulation_only',development_sha256=frozen_hash,source_sha256=hashes,
        comparison=comparison,scenarios=files,limitations=[
            'No new actual equipment fault data obtained; all results here are scenario-level simulations.',
            'Heat flow exponents .8 match prescribed test physics; user must qualify exponents and property regime.',
            'RO baseline has correctly supplied external NDP/TCF; new mode automates conversion, not higher accuracy.',
            'Column test uses an empirical power law; no wet-tower/flooding identification or prediction claim.',
            'Steam-trap warmup is UNKNOWN, not corrected normal; startup faults can be delayed/missed.',
            'Vaporizer result validates only a temperature threshold; external prediction was not fabricated.',
            'Boiler total inventory observer remains blocked by missing geometry/state/qualified measured data.'])
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(comparison,indent=2))

if __name__=='__main__':main()
