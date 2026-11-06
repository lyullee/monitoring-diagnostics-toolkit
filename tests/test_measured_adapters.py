import json
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch,HydraulicResistanceDiagnostic,HeatPumpPerformanceDiagnostic,StreamingDiagnostic

HP=dict(condenser_duty='q',electric_power='p',evaporating_temperature='te',condensing_temperature='tc',
    liquid_line_temperature='tl',discharge_temperature='td',refrigerant_mass_flow='m',compressor_speed='speed',heat_demand='load')
def heatpump(offset=0,power_factor=1):
    load=np.repeat([10200.,12300.],40);n=len(load);te=np.full(n,278.15);tc=np.full(n,318.15)
    eta=.45+.02*(load-10200)/2100;cop=eta*tc/(tc-te)
    values=np.column_stack((load,load/cop*power_factor,te,tc,tc-3-(load-10200)/2100,
        tc+15+(load-10200)/2100,(.0005+.00003*(load-10200)/2100)*60,np.full(n,60.),load))
    return SensorBatch(np.arange(n,dtype=float)*10+offset,values,tuple(HP.values()),
        ('W','W','K','K','K','K','kg/s','1/s','W'),'clock','asset','laboratory_measured')
def model(mode='load_conditioned',**kw):return HeatPumpPerformanceDiagnostic(HP,reference_mode=mode,**kw)

@pytest.mark.parametrize('mode',['constant','load_conditioned'])
def test_heatpump_reference_calibration_serialization_and_alarm(mode):
    m=model(mode).fit(heatpump()).calibrate(heatpump(offset=1000));b=heatpump(offset=2000)
    normal=m.score(b);assert normal.valid.all() and not normal.alarms.any()
    ref=json.loads(json.dumps(m.reference,allow_nan=False));clone=model(mode).set_reference(ref)
    np.testing.assert_allclose(clone.score(b).scores,normal.scores)
    bad=m.score(heatpump(offset=2000,power_factor=2));assert bad.alarms.all()
    assert ref==m.reference
    stream=StreamingDiagnostic(m);pieces=[stream.push(b.subset(slice(i,i+13))) for i in range(0,len(b.time_s),13)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in pieces]),normal.scores)

def test_heatpump_physical_metrics_hand_calculated():
    b=heatpump();m=model().fit(b);r=m.score(b)
    assert r.metrics['heating_cop'][0]==pytest.approx(.45*318.15/40)
    assert r.metrics['isothermal_heating_carnot_cop'][0]==pytest.approx(318.15/40)
    assert r.metrics['log_carnot_efficiency_proxy'][0]==pytest.approx(np.log(.45))
    assert r.metrics['subcooling_k'][0]==pytest.approx(3)
    assert r.metrics['discharge_superheat_k'][0]==pytest.approx(15)
    assert r.metrics['mass_per_revolution_kg'][0]==pytest.approx(.0005)

def test_heatpump_rejects_bad_inputs_and_incompatible_reference_and_calibration():
    m=model().fit(heatpump())
    with pytest.raises(ValueError,match='differ'):m.calibrate(heatpump())
    m.calibrate(heatpump(offset=1000));ref=json.loads(json.dumps(m.reference))
    bad=json.loads(json.dumps(ref));bad['refrigerant_model']['residual_scale'][0]=0
    with pytest.raises(ValueError):model().set_reference(bad)
    with pytest.raises(ValueError):model('constant').set_reference(ref)
    b=heatpump(offset=2000);values=b.values.copy();values[:,7]=0
    bad=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    assert not m.score(bad).valid.any()
    with pytest.raises(ValueError):m.calibrate(bad)
    assert m.reference==ref # failed calibration must preserve the prior threshold
    with pytest.raises(ValueError):model().fit(b.subset(slice(0,40)))

@pytest.mark.parametrize('index,value',[(0,1e308),(3,1e-308),(6,0),(7,-1)])
def test_heatpump_extreme_domain_no_valid_alarm(index,value):
    m=model().fit(heatpump());b=heatpump(offset=1000);x=b.values.copy();x[:,index]=value
    bad=SensorBatch(b.time_s,x,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    with np.errstate(all='ignore'):r=m.score(bad)
    if index==0:
        # A huge finite heat duty can produce huge but finite intermediate values;
        # whenever arithmetic remains finite it must still be JSON serializable.
        assert np.isfinite(r.scores[r.valid]).all()
    else:assert not r.valid.any() and not r.alarms.any()
    json.dumps(r.to_dict(),allow_nan=False)

def test_ratio_hydraulics_equals_dimensional_calculation_and_scale_invariance():
    t=np.arange(60.);q=np.linspace(.0005,.0015,len(t));dp=1000*(q/.001)**2
    a=SensorBatch(t,np.column_stack((dp,q)),('dp','q'),('Pa','m3/s'),'c','a','laboratory_measured')
    b=SensorBatch(t,np.column_stack((dp,q/.001)),('dp','ratio'),('Pa','1'),'c','a','laboratory_measured')
    old=HydraulicResistanceDiagnostic(dict(pressure_drop='dp',volume_flow='q'),reference_flow_m3_s=.001,flow_exponent=2).fit(a)
    new=HydraulicResistanceDiagnostic(dict(pressure_drop='dp',flow_ratio='ratio'),flow_input='ratio',flow_exponent=2).fit(b)
    np.testing.assert_allclose(old.score(a).scores,new.score(b).scores,atol=2e-14)
    assert 'volume_flow_m3_s' not in new.score(b).metrics
    np.testing.assert_allclose((q*1e6)/(.001*1e6),b.values[:,1])
    with pytest.raises(ValueError):HydraulicResistanceDiagnostic(dict(pressure_drop='dp',flow_ratio='ratio'),
        flow_input='ratio',reference_flow_m3_s=.001,flow_exponent=2)


def test_documented_ro_conversion_direction_and_ideal_pressure():
    from equipment_diagnostics.observed_inputs import filmtec_inverse_temperature_factor,ideal_nacl_osmotic_pressure
    f=filmtec_inverse_temperature_factor(np.array([20.,25.,30.]))
    np.testing.assert_allclose(f,[np.exp(3020*(1/293-1/298)),1.,np.exp(2640*(1/303-1/298))])
    assert f[0]>1>f[2]
    assert ideal_nacl_osmotic_pressure(5.844,298.15)==pytest.approx(200*8.31446261815324*298.15)
    assert np.isnan(ideal_nacl_osmotic_pressure(-1,298.15))
    assert np.isnan(filmtec_inverse_temperature_factor(-274))


def test_ratio_mixed_reference_serialization():
    r=np.linspace(.5,1.5,50);dp=1000*r+2000*r*r
    b=SensorBatch(np.arange(50.),np.column_stack((dp,r)),('dp','r'),('Pa','1'),'c','a','laboratory_measured')
    m=HydraulicResistanceDiagnostic(dict(pressure_drop='dp',flow_ratio='r'),flow_input='ratio',normalization_mode='mixed').fit(b)
    np.testing.assert_allclose(m.reference['mixed_coefficients_pa'],[1000,2000],rtol=1e-12)
    c=HydraulicResistanceDiagnostic(dict(pressure_drop='dp',flow_ratio='r'),**m.params).set_reference(json.loads(json.dumps(m.reference)))
    np.testing.assert_allclose(c.score(b).scores,m.score(b).scores)


def test_heatpump_loader_microsecond_datetime_is_explicitly_seconds(monkeypatch):
    import sys
    from pathlib import Path
    pd=pytest.importorskip('pandas')
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from measured_validation_data import hp_batch
    times=np.array(['2020-11-19T09:00:00','2020-11-19T09:00:10','2020-11-19T09:03:00'],dtype='datetime64[us]')
    d=pd.DataFrame({'Date':times,'Condenser_heat_duty':10.,'Compressor_power_consumption':2.,
        'Evaporator_saturation_temperature':5.,'Condenser_saturation_temperature':45.,
        'Liquid_line_refrigerant_temperature':42.,'Compressor_outlet_temperature':65.,
        'Refrigerant_Mass_flow':30.,'Compressor_speed':60.,'Test code':'NF10','Fault intensity':0.})
    b,e,y,codes=hp_batch(d,'NF10')
    np.testing.assert_allclose(np.diff(b.time_s),[10,170])
    assert not e.any() # the >60s acquisition gap must restart the 180s warmup
    assert not y.any()
