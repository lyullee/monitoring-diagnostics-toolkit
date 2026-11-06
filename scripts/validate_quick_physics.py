"""Independent forward-model comparisons. These are simulations, not plant accuracy."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from equipment_diagnostics import SensorBatch,HydraulicResistanceDiagnostic,MassBalanceDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics
from validate_public_data import score_threshold

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'/'quick_improvements'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def batch(t,cols,units):
    return SensorBatch(t,np.column_stack([np.broadcast_to(v,(len(t),)) for v in cols.values()]),tuple(cols),
        tuple(units),'simulation_clock','simulation_asset','simulation')

def packed_bed(seed,damage=1.):
    from fluids.packed_bed import Ergun
    rng=np.random.default_rng(seed); n=600
    q=rng.uniform(.0004,.0016,n); q[:2]=[.0004,.0016]
    rho=rng.uniform(900,1100,n); mu=rng.uniform(.0005,.0015,n)
    # Independent external forward function, including geometry and both pressure terms.
    dp=np.array([Ergun(dp=.005,voidage=.4,vs=f/.01,rho=r,mu=m,L=1.) for f,r,m in zip(q,rho,mu)])
    dp*=damage*(1+rng.uniform(-.005,.005,n))
    return batch(np.arange(n,dtype=float),dict(dp=dp,q=q,rho=rho,mu=mu),['Pa','m3/s','kg/m3','Pa*s'])

def inventory(phase,loss=0.):
    t=np.arange(1200.)*.5
    # Independent analytical true inventory plus explicitly bounded measurement errors.
    mass=1000-loss*t+np.sin(t/4+phase)
    inc=1+.08*np.sin(t/20+phase); out=1+.05*np.cos(t/13+phase)
    return batch(t,dict(m=mass,i=inc,o=out),['kg','kg/s','kg/s'])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    old=HydraulicResistanceDiagnostic({'pressure_drop':'dp','volume_flow':'q','density':'rho'},
        reference_flow_m3_s=.001,flow_exponent=2,growth_limit_fraction=.25)
    new=HydraulicResistanceDiagnostic({'pressure_drop':'dp','volume_flow':'q','density':'rho','viscosity':'mu'},
        reference_flow_m3_s=.001,normalization_mode='mixed',growth_limit_fraction=.25)
    train=packed_bed(20261105); cal=packed_bed(20261106)
    thresholds={}
    for k,m in [('before',old),('after',new)]:
        m.fit(train); r=m.score(cal)
        thresholds[k]=max(1.,float(np.nextafter(np.quantile(r.scores[r.valid],.99),np.inf)))
    ch=dict(inventory_mass='m',inflow='i',outflow='o')
    tank0=MassBalanceDiagnostic(ch,loss_limit_kg_s=.05,window_s=10)
    tank1=MassBalanceDiagnostic(ch,loss_limit_kg_s=.05,window_s=10,inventory_error_bound_kg=1,
        inflow_error_bound_kg_s=.08,outflow_error_bound_kg_s=.05)
    code=[Path(__file__),*sorted((ROOT/'src'/'equipment_diagnostics').glob('*.py'))]
    source={str(p.relative_to(ROOT)):digest(p) for p in code}
    frozen={'version':__version__,'evidence_type':'simulation_only','source_sha256':source,
        'hydraulic':{'train_seed':20261105,'calibration_seed':20261106,'test_seeds':[20261107,20261108],
            'train_fingerprint':train.fingerprint,'calibration_fingerprint':cal.fingerprint,
            'before_reference':old.reference,'after_reference':new.reference,'thresholds':thresholds,
            'policy':'Separate normal-only q99, floor1; same 25% growth engineering limit; no test tuning.'},
        'tank':{'before_params':tank0.params,'after_params':tank1.params,
            'policy':'No learned model or calibration; instrument error bounds declared from simulation specification.',
            'test_phases':[.3,1.3,2.3],'test_losses_kg_s':[0.,.8,.15],
            'warning':'Error-bound subtraction reduces false alarms but can hide real small leaks.'}}
    path=OUT/'physics_frozen.json'; path.write_bytes(json.dumps(frozen,indent=2,sort_keys=True).encode())
    frozen_hash=digest(path); records=[]
    scenarios=[('hydraulic_normal',old,new,packed_bed(20261107),False,thresholds),
        ('hydraulic_resistance_growth_40pct',old,new,packed_bed(20261108,damage=1.4),True,thresholds),
        ('tank_normal_bounded_error',tank0,tank1,inventory(.3),False,dict(before=1.,after=1.)),
        ('tank_large_loss_0.8kg_s',tank0,tank1,inventory(1.3,.8),True,dict(before=1.,after=1.)),
        ('tank_small_loss_0.15kg_s',tank0,tank1,inventory(2.3,.15),True,dict(before=1.,after=1.))]
    with (OUT/'physics_predictions.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(['scenario','time_s','label','eligible','before_valid','before_alarm','after_valid','after_alarm'])
        for name,before,after,b,fault,cut in scenarios:
            rs=[before.score(b),after.score(b)]; e=np.ones(len(b.time_s),bool); y=np.full(len(e),fault,bool)
            alarms=[score_threshold(r,b,cut[k],0) for k,r in zip(('before','after'),rs)]
            item={'scenario':name,'evidence_type':'simulation_only','fingerprint':b.fingerprint,'policies':{}}
            common=rs[0].valid&rs[1].valid
            for key,r,a in zip(('before','after'),rs,alarms):
                item['policies'][key]={'metrics':binary_metrics(y,a,r.valid,e),
                    'common_metrics':binary_metrics(y,a,common,e)}
                if name=='hydraulic_normal':
                    normalized=r.metrics['normalized_pressure_drop_pa'][r.valid]
                    item['policies'][key]['normalized_pressure_coefficient_of_variation']=float(normalized.std()/normalized.mean())
            records.append(item)
            for i,t in enumerate(b.time_s):
                w.writerow([name,t,int(fault),1,*[v for r,a in zip(rs,alarms) for v in (int(r.valid[i]),int(a[i]))]])
    assert digest(path)==frozen_hash
    assert source=={str(p.relative_to(ROOT)):digest(p) for p in code}
    result={'version':__version__,'evidence_type':'simulation_only','source_sha256':source,'frozen_sha256':frozen_hash,
        'scenarios':records,'limitations':['Independent forward equations with known parameters; not actual equipment observations.',
            'Strong/small tank losses intentionally both included; no universal detection accuracy claim.',
            'Hydraulic mixed model assumes fixed geometry and single-phase fluid; rank excitation and viscosity/density validity required.',
            'Tank bounds cover declared absolute instrument errors only, not omitted streams, timing errors or unmodeled inventory.',
            'Tank conservative guaranteed alarm requires true loss > engineering limit + twice combined error bound.']}
    (OUT/'physics_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(records,indent=2))

if __name__=='__main__': main()
