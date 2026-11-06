import numpy as np
import pytest
from equipment_diagnostics import (SensorBatch,calibrated_level,causal_asof,moist_air_exchange,
    horizontal_cylinder_liquid_volume,SaturatedBoilerInventory,PiecewiseVaporizer,
    VaporizerDiagnostic,BoilerBalanceDiagnostic)
from equipment_diagnostics import WetCoilAirsideDiagnostic,LoadConditionedPressureDiagnostic


def batch(cols,units,*,time=None,**kw):
    n=max(np.size(a) for a in cols.values())
    return SensorBatch(np.arange(n,dtype=float) if time is None else time,
        np.column_stack([np.broadcast_to(a,(n,)) for a in cols.values()]),tuple(cols),tuple(units),
        'availability','asset','simulation',**kw)


def test_level_hand_answer_and_metadata():
    b=batch(dict(v=[0,.5,1,1.1]),['V'],episodes=[0,0,1,1],modes=['a']*4)
    r=calibrated_level(b,'v',slope_m_v=.3,offset_m=.05,qualified_voltage_range_v=(0,1))
    np.testing.assert_allclose(r.column('level_m','m')[0],[.05,.2,.35,.38])
    assert r.column('level_m','m')[1].tolist()==[True,True,True,False]
    assert (r.asset_id,r.clock_id,r.origin)==(b.asset_id,b.clock_id,b.origin)
    np.testing.assert_array_equal(r.episodes,b.episodes)
    np.testing.assert_array_equal(r.modes,b.modes)
    with pytest.raises(ValueError):calibrated_level(batch(dict(v=[1]),['Pa']),'v',slope_m_v=1,offset_m=0,qualified_voltage_range_v=(0,2))
    with pytest.raises(ValueError):calibrated_level(b,'v',slope_m_v=True,offset_m=0,qualified_voltage_range_v=(0,1))


def test_asof_no_future_stale_episode_or_clock_leak():
    a=batch(dict(flow=[10,20,30]),['kg/s'],time=[1,3,7],episodes=[0,0,1])
    b=batch(dict(level=np.ones(8)),['m'],episodes=[0]*6+[1]*2)
    r=causal_asof(a,b,max_age_s=1)
    assert r.column('flow','kg/s')[1].tolist()==[False,True,True,True,True,False,False,True]
    np.testing.assert_allclose(r.column('flow','kg/s')[0][[1,2,3,4,7]],[10,10,20,20,30])
    alien=SensorBatch(a.time_s,a.values,a.channels,a.units,'other',a.asset_id,a.origin)
    with pytest.raises(ValueError):causal_asof(alien,b,max_age_s=1)


def test_moist_air_units_dry_and_latent_hand_answers():
    r=moist_air_exchange(2,303.15,293.15,.01,.005)
    expected=2*(1006*10+2501000*.005+1860*(.01*30-.005*20))
    assert float(r['air_side_heat_w'])==pytest.approx(expected)
    assert float(r['moisture_removal_kg_s'])==pytest.approx(.01)
    assert float(moist_air_exchange(1,300,290,0,0)['air_side_heat_w'])==pytest.approx(10060)
    assert not moist_air_exchange(1,300,290,10,5)['valid'] # g/kg is not kg/kg


def test_drum_geometry_limits_and_numerical_quadrature():
    v=horizontal_cylinder_liquid_volume(np.array([0,1,2,-1,2.1,1e-12]),radius_m=1,length_m=3)
    np.testing.assert_allclose(v[:3],[0,1.5*np.pi,3*np.pi])
    assert np.isnan(v[3:5]).all() and v[5]>0
    y=np.linspace(-1,-.3,100001)
    integrate=np.trapezoid if hasattr(np,'trapezoid') else np.trapz
    quadrature=3*integrate(2*np.sqrt(np.maximum(1-y*y,0)),y)
    assert horizontal_cylinder_liquid_volume(.7,radius_m=1,length_m=3)==pytest.approx(quadrature,rel=1e-7)
    with pytest.raises(ValueError):horizontal_cylinder_liquid_volume(1,radius_m=1e200,length_m=1e200)
    assert np.isnan(horizontal_cylinder_liquid_volume(1e-300,radius_m=1,length_m=3))


def vapor(ua):
    return PiecewiseVaporizer(saturation_temperature_k=300,latent_heat_j_kg=100000,
        liquid_cp_j_kg_k=2000,vapor_cp_j_kg_k=1000,ua_w_k=ua,property_basis_id='example:constant-P')


def test_vaporizer_three_hand_computable_segments():
    # Source350, inlet280. Preheat UA=2000 log(70/50), boil UA=100000/50.
    pre=2000*np.log(70/50); boil=2000
    r=vapor(pre/2).predict(1,-40000,350)
    assert r['outlet_temperature_k']==pytest.approx(350-70*np.exp(-pre/2/2000))
    r=vapor(pre+boil/2).predict(1,-40000,350)
    assert r['outlet_temperature_k']==pytest.approx(300)
    assert r['vapor_fraction']==pytest.approx(.5)
    r=vapor(pre+boil+1000*np.log(2)).predict(1,-40000,350)
    assert r['outlet_temperature_k']==pytest.approx(325)
    assert r['absorbed_duty_w']==pytest.approx(165000)


def test_vaporizer_limits_invalid_inputs_and_phase_warning():
    for ua in (1e-12,1e12):
        r=vapor(ua).predict([1,0,1,1],[-40000]*4,[350,350,299,270])
        assert r['valid'].tolist()==[True,False,False,False]
        assert 280<=r['outlet_temperature_k'][0]<=350
    # Same saturation temperature can hide incomplete vaporization: retain quality.
    assert vapor(100).predict(1,0,350)['vapor_fraction']==pytest.approx(.05)
    assert vapor(500).predict(1,0,350)['vapor_fraction']==pytest.approx(.25)


def test_vaporizer_chain_and_basis_rejection():
    b=batch(dict(m=[1]*3,hin=[-40000]*3,source=[350]*3,out=[300]*3),['kg/s','J/kg','K','K'],metadata={'enthalpy_basis_id':'example:constant-P'})
    x=vapor(5000).transform(b,mass_flow_channel='m',inlet_enthalpy_channel='hin',source_temperature_channel='source')
    r=VaporizerDiagnostic(dict(outlet_temperature='out',mass_flow='m',predicted_temperature='predicted_outlet_k'),shortfall_limit_k=5).score(x)
    assert r.valid.all() and r.alarms.all()
    b2=batch(dict(m=[1],hin=[0],source=[350]),['kg/s','J/kg','K'])
    with pytest.raises(ValueError):vapor(1000).transform(b2,mass_flow_channel='m',inlet_enthalpy_channel='hin',source_temperature_channel='source')


@pytest.mark.physics
def test_boiler_inventory_independent_density_identity_and_chain():
    from CoolProp.CoolProp import PropsSI
    model=SaturatedBoilerInventory(radius_m=1,length_m=3,circuit_volumes_m3={'riser':2,'downcomer':1})
    n=70
    b=batch(dict(p=np.full(n,1e6),h=np.ones(n),a=np.full(n,.2),b=np.zeros(n),feed=np.ones(n),steam=np.ones(n)),
        ['Pa','m','1','1','kg/s','kg/s'])
    x=model.transform(b,pressure_channel='p',level_channel='h',void_channels={'riser':'a','downcomer':'b'})
    rl=PropsSI('D','P',1e6,'Q',0,'Water');rv=PropsSI('D','P',1e6,'Q',1,'Water')
    expected=rl*(1.5*np.pi+2.6)+rv*(1.5*np.pi+.4)
    np.testing.assert_allclose(x.column('inventory_kg','kg')[0],expected)
    d=BoilerBalanceDiagnostic(dict(inventory_mass='inventory_kg',inflow='feed',outflow='steam'),loss_limit_kg_s=.1,window_s=60)
    r=d.score(x);assert r.valid.sum()==10 and not r.alarms.any()
    assert x.clock_id==b.clock_id and x.asset_id==b.asset_id
    with pytest.raises(ValueError):model.transform(b,pressure_channel='p',level_channel='h',void_channels={'riser':'a'})


@pytest.mark.physics
def test_boiler_invalid_phase_level_and_void_are_unknown():
    model=SaturatedBoilerInventory(radius_m=1,length_m=3,circuit_volumes_m3={'c':1})
    b=batch(dict(p=[1e6,22.064e6,1e6,1e6],h=[1,1,3,1],a=[.5,.5,.5,1.1]),['Pa','m','1'])
    r=model.transform(b,pressure_channel='p',level_channel='h',void_channels={'c':'a'})
    assert r.column('inventory_kg','kg')[1].tolist()==[True,False,False,False]


def pressure_data(seed,factor=1):
    rng=np.random.default_rng(seed);n=300;p=rng.uniform(50000,250000,n);s=rng.uniform(4,7,n)
    p[:2]=[50000,250000];s[:2]=[4,7]
    dp=factor*100*(p/100000)**.7*(s/5)**1.5
    return batch(dict(dp=dp,p=p,s=s),['Pa','W','1/s'])


def test_pressure_context_normal_fit_calibration_roundtrip_and_fault():
    from copy import deepcopy
    channels=dict(pressure_drop='dp',shaft_power='p',engine_speed='s')
    m=LoadConditionedPressureDiagnostic(channels)
    m.fit(pressure_data(1)).calibrate(pressure_data(2))
    assert m.score(pressure_data(3)).valid.all() and not m.score(pressure_data(3)).alarms.any()
    r=m.score(pressure_data(4,2));assert r.valid.all() and r.alarms.all()
    clone=LoadConditionedPressureDiagnostic(channels).set_reference(m.reference)
    np.testing.assert_allclose(clone.score(pressure_data(4,2)).scores,r.scores)
    old=deepcopy(m.reference)
    with pytest.raises(ValueError):m.calibrate(pressure_data(2).subset(slice(0,2)))
    assert m.reference==old
    bad=deepcopy(old);bad['pressure_model']['scale'][0]=0
    with pytest.raises(ValueError):clone.set_reference(bad)
    x=pressure_data(5);xx=x.values.copy();xx[0,1]=1e12
    other=SensorBatch(x.time_s,xx,x.channels,x.units,x.clock_id,x.asset_id,x.origin)
    assert not m.score(other).valid[0]


def wet_data(scale=1):
    q=np.linspace(.04,.1,30);m=q*1.2/1.005;dp=100*(q/.1)**2*scale
    return batch(dict(dp=dp,q=q,m=m,ti=300,to=290,wi=.01,wo=.005),['Pa','m3/s','kg/s','K','K','1','1'])


def test_wet_coil_corrected_pressure_hand_answer_and_reference():
    channels=dict(pressure_drop='dp',volume_flow='q',dry_air_flow='m',inlet_temperature='ti',outlet_temperature='to',inlet_humidity='wi',outlet_humidity='wo')
    m=WetCoilAirsideDiagnostic(channels,reference_volume_flow_m3_s=.1)
    normal=wet_data();m.fit(normal)
    r=m.score(normal)
    np.testing.assert_allclose(r.metrics['normalized_pressure_drop_pa'],100,rtol=1e-14)
    assert not r.alarms.any()
    r=m.score(wet_data(2));assert r.alarms.all()
    restored=WetCoilAirsideDiagnostic(channels,reference_volume_flow_m3_s=.1).set_reference(m.reference)
    np.testing.assert_allclose(restored.score(wet_data(2)).scores,r.scores)
    with pytest.raises(ValueError):m.calibrate(normal)


def test_chiller_refrigerant_feature_definition_and_shape_validation():
    from types import SimpleNamespace
    from equipment_diagnostics.chiller_staged import auxiliary_inputs,fit_model,residual,validate_reference,AUX_KEYS,AUX_FLOORS
    metrics=dict(evaporator_duty_w=np.arange(30.)+100,chilled_out_k=np.full(30,280.),cooling_in_k=np.full(30,300.),
                 evaporating_temperature_k=np.full(30,275.),condensing_temperature_k=np.full(30,310.))
    d=SimpleNamespace(auxiliary_conditioning='water_refrigerant',diagnostic_stage=1,degree=1)
    x=auxiliary_inputs(d,metrics);assert x.shape==(30,5)
    np.testing.assert_array_equal(x[0],[100,280,300,275,310])
    y=np.tile(np.arange(7.),(30,1));model=fit_model(x,y,AUX_KEYS,AUX_FLOORS,1,.001)
    ref=dict(schema='equipment-diagnostics.chiller-staged.v1',stage=1,auxiliary=model)
    validate_reference(d,ref)
    z,_=residual(model,x,y,1);assert np.max(abs(z))<1e-10
    model['coefficients']=model['coefficients'][:-1]
    with pytest.raises(ValueError):validate_reference(d,ref)
