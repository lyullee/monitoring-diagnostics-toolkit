"""Independent analytic/numerical checks; synthetic cases are not field accuracy."""
import json
import numpy as np
import pytest
from equipment_diagnostics import (SensorBatch,ValveTrackingDiagnostic,HydraulicResistanceDiagnostic,
    MassBalanceDiagnostic,StreamingDiagnostic)

def batch(t,cols,units,**kw):
    return SensorBatch(np.asarray(t,float),np.column_stack([np.broadcast_to(v,(len(t),)) for v in cols.values()]),
        tuple(cols),tuple(units),'clock','asset','simulation',**kw)

def valve(**kw):
    return ValveTrackingDiagnostic({'command':'u','position':'x'},error_limit_fraction=.04,**kw)

def hydraulic(**kw):
    return HydraulicResistanceDiagnostic({'pressure_drop':'dp','volume_flow':'q','density':'rho','viscosity':'mu'},
        reference_flow_m3_s=.001,normalization_mode='mixed',**kw)

def pressure_data(offset=0,damage=1):
    t=np.arange(80.)+offset; q=np.linspace(.0004,.0016,len(t))
    rho=1000+100*np.sin(t/7); mu=.001*(1+.2*np.cos(t/9))
    dp=damage*(1000*(mu/.001)*(q/.001)+2000*(rho/1000)*(q/.001)**2)
    return batch(t,dict(dp=dp,q=q,rho=rho,mu=mu),['Pa','m3/s','kg/m3','Pa*s'])

def test_valve_healthy_step_and_ramp_and_fault():
    t=np.arange(300.)*.2; tau=2
    b=batch(t,dict(u=.8,x=.8-.6*np.exp(-t/tau)),['1','1'])
    old=valve().score(b); new=valve(response_time_s=tau).score(b)
    assert old.alarms.any() and not new.alarms.any()
    np.testing.assert_allclose(new.metrics['tracking_error_fraction'][new.valid],0,atol=2e-15)
    t=np.cumsum(np.r_[0,np.resize([.1,.3,.7,.2],199)])
    x=.2+.003*(t-tau+tau*np.exp(-t/tau))
    ramp=batch(t,dict(u=.2+.003*t,x=x),['1','1'])
    r=valve(response_time_s=tau).score(ramp)
    np.testing.assert_allclose(r.metrics['tracking_error_fraction'][r.valid],0,atol=2e-15)
    damaged=batch(t,dict(u=.2+.003*t,x=x+np.where(t>30,.1,0)),['1','1'])
    r=valve(response_time_s=tau).score(damaged)
    assert r.alarms[t>30].all()

@pytest.mark.physics
def test_delayed_first_order_against_independent_ode():
    from scipy.integrate import solve_ivp
    t=np.arange(81.)*.5; u=.5+.3*np.sin(t/3); delay=.7; tau=1.3
    # Simulation begins at first timestamp where delayed command is available.
    start=int(np.searchsorted(t,delay)); x=np.full(len(t),.5)
    knots=np.unique(np.r_[t[start:],(t+delay)[(t+delay)>t[start]]]); knots=knots[knots<=t[-1]]
    state=.5; predictions={t[start]:state}
    for left,right in zip(knots[:-1],knots[1:]):
        sol=solve_ivp(lambda s,v:(np.interp(s-delay,t,u)-v)/tau,(left,right),[state],rtol=1e-11,atol=1e-13)
        state=float(sol.y[0,-1]); predictions[right]=state
    for i in range(start,len(t)): x[i]=predictions[t[i]]
    b=batch(t,dict(u=u,x=x),['1','1'])
    r=valve(delay_s=delay,response_time_s=tau).score(b)
    np.testing.assert_allclose(r.metrics['tracking_error_fraction'][r.valid],0,atol=1e-10)

def test_dynamic_valve_segments_and_stream_equivalence():
    t=np.arange(200.)*.5; x=.8-.6*np.exp(-t/2)
    x[80]=np.nan; episodes=np.where(t<60,0,1)
    b=batch(t,dict(u=.8,x=x),['1','1'],episodes=episodes)
    m=valve(response_time_s=2); r=m.score(b)
    assert not r.valid[80:101].any() and not r.valid[120:140].any()
    stream=StreamingDiagnostic(m,max_history_samples=500)
    parts=[stream.push(b.subset(slice(i,i+13))) for i in range(0,len(t),13)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in parts]),r.scores,equal_nan=True)
    for n in (33,82,151):
        np.testing.assert_allclose(m.score(b.subset(slice(0,n))).scores,r.scores[:n],equal_nan=True)

def test_mixed_hydraulic_fit_normal_fault_and_roundtrip():
    m=hydraulic().fit(pressure_data()); ref=json.loads(json.dumps(m.reference))
    np.testing.assert_allclose(ref['mixed_coefficients_pa'],[1000,2000],rtol=1e-12)
    b=pressure_data(offset=1000); r=m.score(b)
    assert r.valid.all() and not r.alarms.any()
    np.testing.assert_allclose(r.metrics['normalized_pressure_drop_pa'],3000,rtol=1e-12)
    assert m.score(pressure_data(offset=1000,damage=1.4)).alarms.all()
    clone=hydraulic().set_reference(ref)
    np.testing.assert_allclose(clone.score(b).scores,r.scores)
    damaged=json.loads(json.dumps(ref)); damaged['mixed_coefficients_pa'][0]=-1
    with pytest.raises(ValueError): hydraulic().set_reference(damaged)
    assert json.dumps(m.reference)==json.dumps(ref)

def test_mixed_hydraulic_rejects_unidentifiable_and_missing_units():
    b=batch(np.arange(30.),dict(dp=1000,q=.001,rho=1000,mu=.001),['Pa','m3/s','kg/m3','Pa*s'])
    m=hydraulic().fit(pressure_data())
    with pytest.raises(ValueError,match='excitation'): m.fit(b)
    assert m.reference is None
    wrong=batch(np.arange(30.),dict(dp=1000,q=.001,rho=1000,mu=1),['Pa','m3/s','kg/m3','cP'])
    with pytest.raises(ValueError,match='expected Pa'): hydraulic().fit(wrong)

@pytest.mark.parametrize('coefficient',[0,1])
def test_mixed_nonnegative_boundary_solutions(coefficient):
    b=pressure_data(); values=b.values.copy()
    values[:,0]=3000*((values[:,3]/.001)*(values[:,1]/.001) if coefficient==0 else
                      (values[:,2]/1000)*(values[:,1]/.001)**2)
    b=batch(b.time_s,dict(zip(b.channels,values.T)),b.units)
    m=hydraulic().fit(b); r=m.score(b)
    assert r.valid.all() and not r.alarms.any()
    assert m.reference['mixed_coefficients_pa'][coefficient]==pytest.approx(3000,rel=1e-12)

def test_inventory_bounded_measurement_error_and_detectable_loss():
    t=np.arange(100.)*.5; channels=dict(inventory_mass='m',inflow='i',outflow='o')
    normal=batch(t,dict(m=100+np.sin(t),i=1.08,o=1),['kg','kg/s','kg/s'])
    old=MassBalanceDiagnostic(channels,loss_limit_kg_s=.05,window_s=10)
    new=MassBalanceDiagnostic(channels,loss_limit_kg_s=.05,window_s=10,
        inventory_error_bound_kg=1,inflow_error_bound_kg_s=.08)
    r=new.score(normal)
    assert old.score(normal).alarms.any() and not r.alarms.any()
    np.testing.assert_allclose(r.metrics['loss_error_bound_kg_s'][r.valid],.28)
    # True loss .7kg/s exceeds .05+2*.28 even with worst-case adverse errors.
    fault=batch(t,dict(m=100-.7*t+np.sin(t),i=.92,o=1),['kg','kg/s','kg/s'])
    r=new.score(fault); assert r.alarms[r.valid].all()
    for n in (35,80):
        np.testing.assert_allclose(new.score(fault.subset(slice(0,n))).scores,r.scores[:n],equal_nan=True)

@pytest.mark.parametrize('kwargs',[
    dict(response_time_s=-1),dict(response_time_s=float('nan')),dict(response_warmup_s=2),
])
def test_valve_invalid_dynamic_configuration(kwargs):
    with pytest.raises(ValueError): valve(**kwargs)

def test_mass_bounds_invalid_and_zero_defaults_compatible():
    channels=dict(inventory_mass='m',inflow='i',outflow='o')
    with pytest.raises(ValueError): MassBalanceDiagnostic(channels,loss_limit_kg_s=.1,inventory_error_bound_kg=-1)
    a=MassBalanceDiagnostic(channels,loss_limit_kg_s=.1)
    b=MassBalanceDiagnostic(channels,loss_limit_kg_s=.1,inventory_error_bound_kg=0)
    assert a.signature==b.signature


def test_first_order_numerical_limits_and_initial_fault():
    from equipment_diagnostics.quick_improvements import first_order_step
    assert first_order_step(.2,.3,.4,1.,1e300)==pytest.approx(.2)
    assert first_order_step(.2,.3,.4,1.,1e-300)==pytest.approx(.4)
    t=np.arange(100.)*.5
    b=batch(t,dict(u=.8,x=.9),['1','1'])
    r=valve(response_time_s=2).score(b)
    assert not r.valid[:20].any() and r.alarms[r.valid].all()


def test_mixed_physical_domain_and_extreme_calculation_unknown():
    m=hydraulic().fit(pressure_data()); b=pressure_data(offset=1000)
    values=b.values.copy(); values[:,3]=-1
    r=m.score(batch(b.time_s,dict(zip(b.channels,values.T)),b.units))
    assert not r.valid.any() and not r.alarms.any()
    values=b.values.copy(); values[:,1]=1e308
    with np.errstate(all='ignore'):
        r=m.score(batch(b.time_s,dict(zip(b.channels,values.T)),b.units))
    assert not r.valid.any() and not r.alarms.any()
    json.dumps(r.to_dict(),allow_nan=False)


def test_inventory_bounds_streaming_and_combined_overflow_rejection():
    channels=dict(inventory_mass='m',inflow='i',outflow='o')
    with pytest.raises(ValueError):
        MassBalanceDiagnostic(channels,loss_limit_kg_s=.1,window_s=.1,inventory_error_bound_kg=1e308)
    m=MassBalanceDiagnostic(channels,loss_limit_kg_s=.05,window_s=10,inventory_error_bound_kg=.1)
    t=np.cumsum(np.r_[0,np.resize([.1,.3,.7,.2],199)])
    b=batch(t,dict(m=100-.3*t,i=1,o=1),['kg','kg/s','kg/s']); r=m.score(b)
    stream=StreamingDiagnostic(m); parts=[stream.push(b.subset(slice(i,i+17))) for i in range(0,len(t),17)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in parts]),r.scores,equal_nan=True)
