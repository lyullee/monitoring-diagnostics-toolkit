import json
import numpy as np
import pytest
from equipment_diagnostics import FilterServiceRiskModel,SensorBatch,StreamingDiagnostic,HeatPumpPerformanceDiagnostic
from test_measured_adapters import heatpump,HP


def filter_data(offset=0):
    t=np.arange(0,80,.5);q=np.full(len(t),1.1);dp=10*np.exp(.04*t)
    b=SensorBatch(t+offset,np.column_stack((dp,q)),('dp','q'),('Pa','1'),'c','a','laboratory_measured')
    y=np.log(600/10)/.04-t
    return b,y


def risk(**kw):return FilterServiceRiskModel(dict(pressure_drop='dp',flow_ratio='q'),**kw)


def test_risk_causal_window_and_hand_slope():
    b,y=filter_data();m=risk().fit(b,y);r=m.score(b)
    i=40;t=b.time_s[i-20:i+1];z=np.log1p(b.values[i-20:i+1,0]);dt=t-t.mean()
    assert r.metrics['log_growth_per_s'][i]==pytest.approx(np.dot(dt,z-z.mean())/np.dot(dt,dt))
    assert not r.valid[:18].any()
    prefix=m.score(b.subset(slice(0,50)))
    np.testing.assert_allclose(prefix.scores,r.scores[:50],equal_nan=True)
    values=b.values.copy();values[50:,0]=5000
    changed=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    np.testing.assert_allclose(m.score(changed).scores[:50],r.scores[:50],equal_nan=True)


def test_risk_split_calibration_json_and_stream():
    b,y=filter_data();c,yc=filter_data(1000);d,_=filter_data(2000)
    m=risk(persistence_s=1).fit(b,y).calibrate(c,yc)
    ref=json.loads(json.dumps(m.reference,allow_nan=False));clone=risk(persistence_s=1).set_reference(ref)
    r=clone.score(d);stream=StreamingDiagnostic(clone)
    chunks=[stream.push(d.subset(slice(i,i+11))) for i in range(0,len(y),11)]
    np.testing.assert_allclose(np.concatenate([x.scores for x in chunks]),r.scores,equal_nan=True)
    assert clone.reference==ref
    with pytest.raises(ValueError,match='separate'):m.calibrate(b,y)
    with pytest.raises(ValueError):m.calibrate(c,np.full(len(y),-1.))
    assert m.reference==ref
    bad=json.loads(json.dumps(ref));bad['risk_model']['scale'][0]=0
    with pytest.raises(ValueError):risk().set_reference(bad)
    with pytest.raises(ValueError):risk(window_s=0)
    with pytest.raises(ValueError):risk().fit(b,y[:-1])


def test_risk_gap_and_invalid_input_reset_window():
    b,y=filter_data();m=risk().fit(b,y);x=b.values.copy();x[50,1]=0
    bad=SensorBatch(b.time_s,x,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    r=m.score(bad);assert not r.valid[50:69].any() and not r.alarms[50:69].any()
    with pytest.raises(ValueError):risk().fit(b,np.full(len(y),np.nan))
    wrong=SensorBatch(b.time_s,b.values,b.channels,('kPa','1'),b.clock_id,b.asset_id,b.origin)
    with pytest.raises(ValueError):m.score(wrong)


def test_extended_heatpump_detects_evaporating_temperature_drop_hidden_by_carnot_proxy():
    train=heatpump();cal=heatpump(1000);test=heatpump(2000)
    m=HeatPumpPerformanceDiagnostic(HP,reference_mode='load_conditioned',feature_set='extended').fit(train).calibrate(cal)
    x=test.values.copy();x[:,2]-=4
    bad=SensorBatch(test.time_s,x,test.channels,test.units,test.clock_id,test.asset_id,test.origin)
    assert m.score(bad).alarms.all() and not m.score(test).alarms.any()
    ref=json.loads(json.dumps(m.reference));clone=HeatPumpPerformanceDiagnostic(HP,reference_mode='load_conditioned',feature_set='extended').set_reference(ref)
    np.testing.assert_allclose(clone.score(bad).scores,m.score(bad).scores)
    assert len(ref['score_calibration']['channel_scales'])==9
    assert m.score(bad).metrics['evaporating_temperature_k'][0]==pytest.approx(test.values[0,2]-4)
    assert m.reference==ref
    ref['score_calibration']['channel_scales'][0]=0
    with pytest.raises(ValueError):clone.set_reference(ref)


def test_extended_heatpump_failed_calibration_preserves_reference():
    m=HeatPumpPerformanceDiagnostic(HP,reference_mode='load_conditioned',feature_set='extended').fit(heatpump()).calibrate(heatpump(1000))
    ref=json.loads(json.dumps(m.reference))
    with pytest.raises(ValueError):m.calibrate(heatpump())
    b=heatpump(3000);x=b.values.copy();x[:,7]=0
    bad=SensorBatch(b.time_s,x,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    with pytest.raises(ValueError):m.calibrate(bad)
    assert m.reference==ref
    with pytest.raises(ValueError):HeatPumpPerformanceDiagnostic(HP,feature_set='wrong')
