"""Ranks11/13 independent numerical forward calculations; simulation only."""
import csv,hashlib,json
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from CoolProp.CoolProp import PropsSI
from equipment_diagnostics import (SensorBatch,PiecewiseVaporizer,SaturatedBoilerInventory,
    VaporizerDiagnostic,BoilerBalanceDiagnostic,__version__)
from equipment_diagnostics.evaluation import binary_metrics

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/completion_7_13/physics'
VP=dict(saturation_temperature_k=250.,latent_heat_j_kg=350000.,liquid_cp_j_kg_k=2300.,
        vapor_cp_j_kg_k=1500.,ua_w_k=5000.,property_basis_id='synthetic:constant-isobaric-properties')

def ode_vapor(m,hin,source,ua):
    def temperature(h):
        return 250+(h/2300 if h<0 else (h-350000)/1500 if h>350000 else 0)
    # Independent adaptive integration of d(h)/d(UA)=(Tsource-T(h))/massflow.
    sol=solve_ivp(lambda u,y:[(source-temperature(y[0]))/m],[0,ua],[hin],rtol=1e-10,atol=1e-5,max_step=ua/100)
    assert sol.success
    h=sol.y[0,-1];return temperature(h),h

def vb(seed,actual_ua):
    rng=np.random.default_rng(seed);n=120
    flow=rng.uniform(.15,1.5,n);hin=rng.uniform(-50000,100000,n);source=rng.uniform(285,305,n)
    gold=np.array([ode_vapor(m,h,t,actual_ua) for m,h,t in zip(flow,hin,source)])
    b=SensorBatch(np.arange(n)*10.,np.column_stack((flow,hin,source,gold[:,0])),
        ('flow','hin','source','out'),('kg/s','J/kg','K','K'),'simulation','vaporizer','numerical_ODE',
        metadata={'enthalpy_basis_id':VP['property_basis_id']})
    return b,gold

def boiler(seed,leak):
    n=180;t=np.arange(n)*10.;rng=np.random.default_rng(seed)
    p=1e6+1e5*np.sin(t/300);a=.2+.03*np.sin(t/150);total_volume=np.pi*3+3
    rho=np.array([[PropsSI('D','P',x,'Q',q,'Water') for q in (0,1)] for x in p]);rl,rv=rho.T
    # Linear mass trajectory, known total-volume and given circuit void.
    inventory=6800-leak*t
    vl=(inventory-rv*total_volume)/(rl-rv)
    drum_vl=vl-(2*(1-a)+1)
    # Numerically integrate circle width; solve angle via scalar root (independent
    # of production segment-volume function, not its inverse called twice).
    theta=np.array([brentq(lambda theta:3*(theta-np.sin(theta)*np.cos(theta))-v,0,np.pi) for v in drum_vl])
    level=1-np.cos(theta)
    return SensorBatch(t,np.column_stack((p,level,a,np.zeros(n),np.full(n,3.),np.full(n,3.))),
        ('p','h','riser','down','feed','steam'),('Pa','m','1','1','kg/s','kg/s'),'simulation','boiler','independent_inventory_forward'),inventory

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    model=PiecewiseVaporizer(**VP)
    before=VaporizerDiagnostic(dict(outlet_temperature='out',mass_flow='flow'),shortfall_limit_k=5,minimum_outlet_k=280,prediction_mode='minimum_only')
    after=VaporizerDiagnostic(dict(outlet_temperature='out',mass_flow='flow',predicted_temperature='pred'),shortfall_limit_k=5,minimum_outlet_k=280)
    residual_only=VaporizerDiagnostic(dict(outlet_temperature='out',mass_flow='flow',predicted_temperature='pred'),shortfall_limit_k=5)
    protocol=dict(version=__version__,evidence_type='simulation_only',vaporizer_properties=VP,
        normal_development_seeds=[7101,7102],evaluation_seeds=[7103,7104],fault='40% reduction of effective UA',
        note='UA and thresholds declared engineering values. Normal development/calibration only verifies solver error, not data-fitted UA.',
        residual_only_addendum='Added after inspecting first two simulation profiles. Separates equipment residual from mandatory process-temperature limit; reused simulations, no new blind claim.',
        boiler=dict(radius_m=1,length_m=3,circuit_volumes_m3={'riser':2,'downcomer':1},
            test_seeds=[7131,7132],known_leak_kg_s=[0,.2],pressure='1MPa +/- .1MPa sinusoid',
            limitation='Void fraction is supplied ground truth. This is not an estimator of missing void/swell.'))
    fp=OUT/'frozen.json';fp.write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    frozen_hash=hashlib.sha256(fp.read_bytes()).hexdigest()
    errors=[]
    for seed in protocol['normal_development_seeds']:
        b,gold=vb(seed,5000)
        pred=model.predict(b.values[:,0],b.values[:,1],b.values[:,2])
        errors.append(dict(seed=seed,max_abs_temperature_error_k=float(np.max(abs(pred['outlet_temperature_k']-gold[:,0]))),
            max_abs_enthalpy_error_j_kg=float(np.max(abs(pred['outlet_relative_enthalpy_j_kg']-gold[:,1])))))
    rows={k:[] for k in ('temperature_limit','normal_prediction','residual_only')};output=[]
    for seed,ua,fault in [(7103,5000,False),(7104,3000,True)]:
        b,gold=vb(seed,ua);x=model.transform(b,mass_flow_channel='flow',inlet_enthalpy_channel='hin',source_temperature_channel='source',output='pred')
        for key,m in [('temperature_limit',before),('normal_prediction',after),('residual_only',residual_only)]:
            r=m.score(x);label=np.full(len(r.time_s),fault);e=np.ones(len(label),bool)
            rows[key].append((label,r.alarms,r.valid,e))
            output.extend([dict(module='vaporizer',policy=key,scenario='ua_loss40' if fault else 'normal',time_s=float(t),label=int(fault),valid=int(v),alarm=int(a)) for t,v,a in zip(r.time_s,r.valid,r.alarms)])
    bm=SaturatedBoilerInventory(radius_m=1,length_m=3,circuit_volumes_m3={'riser':2,'downcomer':1})
    diag=BoilerBalanceDiagnostic(dict(inventory_mass='inventory_kg',inflow='feed',outflow='steam'),loss_limit_kg_s=.1,window_s=60,max_gap_s=15)
    br=[];brfiles=[]
    for seed,leak in [(7131,0),(7132,.2)]:
        b,inventory=boiler(seed,leak)
        x=bm.transform(b,pressure_channel='p',level_channel='h',void_channels={'riser':'riser','downcomer':'down'})
        mass=x.column('inventory_kg','kg')[0]
        assert np.max(abs(mass-inventory))<1e-7
        r=diag.score(x);label=np.full(len(r.time_s),leak>0);eligible=b.time_s>=60
        br.append((label,r.alarms,r.valid,eligible));brfiles.append(dict(seed=seed,leak_kg_s=leak,
            inventory_max_abs_error_kg=float(np.max(abs(mass-inventory))),metrics=binary_metrics(*br[-1])))
        output.extend([dict(module='boiler',policy='configured_inventory',scenario='leak' if leak else 'normal',time_s=float(t),label=int(leak>0),valid=int(v),alarm=int(a)) for t,v,a in zip(r.time_s,r.valid,r.alarms)])
    aggregate=lambda rs:binary_metrics(*[np.concatenate([r[k] for r in rs]) for k in range(4)])
    result=dict(version=__version__,frozen_sha256=frozen_hash,evidence_type='simulation_only',
        independent_ode_error=errors,vaporizer={k:aggregate(r) for k,r in rows.items()},
        boiler=dict(metrics=aggregate(br),files=brfiles,before_status='no total-inventory input; full chain unavailable'),
        actual_field_fault_metrics=None,
        limitations=['Constant-property, isobaric vaporizer with constant-source temperature; no LNG mixture glide or frosting dynamics.',
            'In two-phase regime temperature alone cannot establish dryness; retained model vapor fraction is prediction, not a measured diagnostic truth.',
            'Normal low-temperature operation can trip a hard outlet-temperature limit; this remains an engineering requirement, not necessarily an equipment fault.',
            'Boiler requires calibrated geometric level and independent circuit void inputs; supplied simulated truth is not an implemented dynamic void observer.'])
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (OUT/'predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    assert hashlib.sha256(fp.read_bytes()).hexdigest()==frozen_hash
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
