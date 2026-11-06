import json
import numpy as np
import pytest
from equipment_diagnostics import (SensorBatch,HeatExchangerDiagnostic,ROMembraneDiagnostic,
    ColumnHydraulicsDiagnostic,VaporizerDiagnostic,SteamTrapDiagnostic,StreamingDiagnostic)

def batch(cols,units,offset=0):
    n=max(np.size(x) for x in cols.values())
    return SensorBatch(np.arange(n,dtype=float)+offset,
        np.column_stack([np.broadcast_to(x,(n,)) for x in cols.values()]),tuple(cols),tuple(units),'clock','asset','simulation')

HEAT=dict(hot_in='hi',hot_out='ho',cold_in='ci',cold_out='co',hot_flow='hf',cold_flow='cf')
def heat_data(offset=0,remaining=1):
    hf,cf=np.meshgrid(np.linspace(.5,2,9),np.linspace(.6,2.1,8)); hf=hf.ravel();cf=cf.ravel()
    ua=remaining/(.0001+.0002*hf**-.8+.0003*cf**-.8)
    ch=hf*4180; cc=cf*4180; small=np.minimum(ch,cc); ratio=small/np.maximum(ch,cc)
    ntu=ua/small
    # Analytic counterflow epsilon, including equal-capacity limit.
    with np.errstate(all='ignore'):
        e=np.where(abs(1-ratio)<1e-12,ntu/(1+ntu),-np.expm1(-ntu*(1-ratio))/(1-ratio*np.exp(-ntu*(1-ratio))))
    q=e*small*70
    return batch(dict(hi=360.,ho=360-q/ch,ci=290.,co=290+q/cc,hf=hf,cf=cf),['K']*4+['kg/s']*2,offset)

def heat(): return HeatExchangerDiagnostic(HEAT,cp_hot_j_kg_k=4180,cp_cold_j_kg_k=4180,reference_mode='flow_resistance')

def ro_data(offset=0,remaining=1):
    t=np.linspace(288.15,308.15,50); ndp=np.linspace(.7e6,.9e6,50)
    # At 298.15K Aref=2e-12; Ea is an explicit test specification.
    a=remaining*2e-12*np.exp(20000/8.31446261815324*(1/298.15-1/t))
    pf=ndp+4e5; pc=pf-1e5; pp=np.full(len(t),1e5)
    return batch(dict(q=a*10*ndp,pf=pf,pc=pc,pp=pp,of=2e5,oc=3e5,op=0.,t=t),
        ['m3/s']+['Pa']*6+['K'],offset)

RO=dict(permeate_flow='q',feed_pressure='pf',concentrate_pressure='pc',permeate_pressure='pp',
        feed_osmotic_pressure='of',concentrate_osmotic_pressure='oc',permeate_osmotic_pressure='op',membrane_temperature='t')
def ro(): return ROMembraneDiagnostic(RO,membrane_area_m2=10,input_mode='pressures_temperature',
    activation_energy_j_mol=20000,temperature_range_k=(285,315))

def column_data(offset=0,growth=1):
    v,l=np.meshgrid(np.linspace(.5,1.5,8),np.linspace(.6,1.4,9));v=v.ravel();l=l.ravel()
    return batch(dict(dp=growth*1000*v**1.7*l**.4,v=v,l=l),['Pa','kg/s','kg/s'],offset)
def column(): return ColumnHydraulicsDiagnostic(dict(pressure_drop='dp',vapor_flow='v',liquid_flow='l'),
    reference_vapor_flow_kg_s=1,reference_liquid_flow_kg_s=1,reference_mode='learned_power')

@pytest.mark.parametrize('make,data,damage',[(heat,heat_data,dict(remaining=.6)),(ro,ro_data,dict(remaining=.6)),
                                         (column,column_data,dict(growth=1.6))])
def test_operating_fit_normal_fault_roundtrip_and_immutability(make,data,damage):
    m=make().fit(data()); snapshot=json.dumps(m.reference,sort_keys=True)
    normal=m.score(data(offset=1000)); fault=m.score(data(offset=2000,**damage))
    assert normal.valid.sum()>20 and not normal.alarms.any()
    assert fault.alarms[fault.valid].all()
    ref=json.loads(json.dumps(m.reference)); clone=make().set_reference(ref)
    np.testing.assert_allclose(clone.score(data(offset=1000)).scores,normal.scores,equal_nan=True)
    assert snapshot==json.dumps(m.reference,sort_keys=True)
    stream=StreamingDiagnostic(m); b=data(offset=3000)
    parts=[stream.push(b.subset(slice(i,i+11))) for i in range(0,len(b.time_s),11)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in parts]),m.score(b).scores,equal_nan=True)

def test_heat_resistance_and_column_exponents_match_known_answers():
    m=heat().fit(heat_data()); r=m.score(heat_data(offset=1000))
    np.testing.assert_allclose(r.metrics['ua_retention_fraction'][r.valid],1,atol=1e-12)
    np.testing.assert_allclose(r.metrics['added_thermal_resistance_k_w'][r.valid],0,atol=1e-15)
    c=column().fit(column_data()); ref=c.reference['learned_power_model']
    np.testing.assert_allclose(ref['exponents'],[1.7,.4],atol=1e-12)
    assert np.exp(ref['intercept_log_pa'])==pytest.approx(1000)

def test_ro_pressure_and_temperature_hand_calculation_and_pressure_offset_invariance():
    m=ro().fit(ro_data()); b=ro_data(offset=1000); r=m.score(b)
    np.testing.assert_allclose(r.metrics['net_driving_pressure_pa'],np.linspace(.7e6,.9e6,50))
    np.testing.assert_allclose(r.metrics['normalized_permeability_m_pa_s'],2e-12,rtol=1e-14)
    values=b.values.copy(); values[:,1:4]+=101325
    shifted=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    np.testing.assert_allclose(m.score(shifted).scores,r.scores,atol=1e-14)

@pytest.mark.parametrize('make,data',[(heat,heat_data),(column,column_data)])
def test_learning_rejects_unexcited_data_and_bad_reference(make,data):
    m=make().fit(data()); b=data(); values=np.tile(b.values[0],(len(b.time_s),1))
    flat=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    with pytest.raises(ValueError,match='excitation'):m.fit(flat)
    assert m.reference is None
    m=make().fit(data()); ref=json.loads(json.dumps(m.reference))
    ref.pop('flow_resistance_model' if make==heat else 'learned_power_model')
    with pytest.raises(ValueError):make().set_reference(ref)

def test_ro_requires_qualified_parameters_and_rejects_temperature_and_pressure_domain():
    with pytest.raises(ValueError):ROMembraneDiagnostic(RO,membrane_area_m2=10,input_mode='pressures_temperature')
    m=ro().fit(ro_data()); b=ro_data(offset=1000)
    for index,value in [(7,330),(1,-1),(4,-1),(3,1e8)]:
        values=b.values.copy(); values[:,index]=value
        wrong=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
        with np.errstate(all='ignore'):r=m.score(wrong)
        assert not r.valid.any() and not r.alarms.any()
        json.dumps(r.to_dict(),allow_nan=False)

def test_vaporizer_minimum_only_without_fabricated_prediction():
    b=batch(dict(t=np.array([290.,280.,270.]),q=1),['K','kg/s'])
    m=VaporizerDiagnostic(dict(outlet_temperature='t',mass_flow='q'),shortfall_limit_k=5,
        minimum_outlet_k=280,prediction_mode='minimum_only')
    r=m.score(b); np.testing.assert_array_equal(r.alarms,[False,False,True])
    assert 'temperature_shortfall_k' not in r.metrics
    with pytest.raises(ValueError):VaporizerDiagnostic(dict(outlet_temperature='t',mass_flow='q'),
        shortfall_limit_k=5,prediction_mode='minimum_only')

def trap(warmup):return SteamTrapDiagnostic(dict(steam_temperature='steam',trap_temperature='trap',
    acoustic_level='sound',supply_on='on'),acoustic_quiet_max=.2,acoustic_loud_min=2,
    cold_margin_k=40,hot_margin_k=10,startup_exclusion_s=warmup)

def test_steam_trap_cold_start_exclusion_and_fault_and_stream():
    t=np.arange(300.); b=batch(dict(steam=450,trap=450-150*np.exp(-t/40),sound=.1,on=1),['K','K','1','1'])
    assert trap(0).score(b).alarms.any()
    m=trap(60);r=m.score(b)
    assert not r.valid[:60].any() and not r.alarms.any()
    stream=StreamingDiagnostic(m);parts=[stream.push(b.subset(slice(i,i+17))) for i in range(0,len(t),17)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in parts]),r.scores,equal_nan=True)
    fault=batch(dict(steam=450,trap=np.full(300,300.),sound=.1,on=1),['K','K','1','1'])
    assert m.score(fault).alarms[60:].all()
    values=b.values.copy();values[100:120,3]=0
    off=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    r=m.score(off);assert not r.valid[100:180].any() and r.valid[180]


def test_heat_optional_flow_transient_gate_and_invalid_model():
    b=heat_data();train=SensorBatch(np.arange(2*len(b.time_s),dtype=float),np.repeat(b.values,2,axis=0),
        b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    m=HeatExchangerDiagnostic(HEAT,cp_hot_j_kg_k=4180,cp_cold_j_kg_k=4180,
        max_flow_change_fraction_s=.01).fit(train)
    r=m.score(b);assert not r.valid[1] and r.reasons[1]=='heat_exchanger_flow_transient'
    ref=json.loads(json.dumps(heat().fit(b).reference));ref['flow_resistance_model']['coefficients_k_w'][0]=-1
    with pytest.raises(ValueError):heat().set_reference(ref)


@pytest.mark.parametrize('make,data,index,value',[(heat,heat_data,4,1e308),(ro,ro_data,7,1e-308),
    (column,column_data,1,1e308)])
def test_operating_extreme_inputs_never_become_valid_alarms(make,data,index,value):
    m=make().fit(data());b=data(offset=1000);values=b.values.copy();values[:,index]=value
    extreme=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    with np.errstate(all='ignore'):r=m.score(extreme)
    assert not r.valid.any() and not r.alarms.any()
    json.dumps(r.to_dict(),allow_nan=False)


def test_ro_derived_temperature_unit_and_wrong_reference_configuration():
    b=ro_data();units=list(b.units);units[-1]='degC'
    wrong=SensorBatch(b.time_s,b.values,b.channels,tuple(units),b.clock_id,b.asset_id,b.origin)
    with pytest.raises(ValueError,match='expected K'):ro().fit(wrong)
    ref=ro().fit(b).reference
    changed=ROMembraneDiagnostic(RO,membrane_area_m2=10,input_mode='pressures_temperature',
        activation_energy_j_mol=25000,temperature_range_k=(285,315))
    with pytest.raises(ValueError):changed.set_reference(ref)


def test_column_constant_pressure_is_valid_when_flows_excite_both_terms():
    b=column_data();values=b.values.copy();values[:,0]=1000
    flat_response=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    m=column().fit(flat_response);r=m.score(flat_response)
    assert r.valid.all() and not r.alarms.any()
    np.testing.assert_allclose(m.reference['learned_power_model']['exponents'],[0,0],atol=1e-12)
