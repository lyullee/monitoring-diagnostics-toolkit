import json
import numpy as np
import pytest
from equipment_diagnostics import FilterRiskClassifier,HeatPumpPerformanceDiagnostic,SensorBatch,StreamingDiagnostic
from test_risk_improvement import filter_data
from test_measured_adapters import heatpump,HP


def classifier(**kw):return FilterRiskClassifier(dict(pressure_drop='dp',flow_ratio='q'),n_estimators=4,min_samples_leaf=2,max_depth=5,**kw)


def test_classifier_labels_separate_and_causal_streaming():
    pytest.importorskip('sklearn')
    b,y=filter_data();c,yc=filter_data(1000);e,_=filter_data(2000)
    m=classifier(persistence_s=1).fit(b,y).calibrate(c,yc,negative_quantile=.9)
    r=m.score(e);ref=json.loads(json.dumps(m.reference,allow_nan=False))
    clone=classifier(persistence_s=1).set_reference(ref)
    stream=StreamingDiagnostic(clone)
    pieces=[stream.push(e.subset(slice(i,i+17))) for i in range(0,len(y),17)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in pieces]),r.scores,equal_nan=True)
    np.testing.assert_array_equal(np.concatenate([p.alarms for p in pieces]),r.alarms)
    x=e.values.copy();x[80:,0]*=5
    changed=SensorBatch(e.time_s,x,e.channels,e.units,e.clock_id,e.asset_id,e.origin)
    np.testing.assert_allclose(m.score(changed).scores[:80],r.scores[:80],equal_nan=True)
    assert m.reference==ref and 'predicted_remaining_service_life_s' not in r.metrics
    assert ((r.metrics['risk_vote_fraction'][r.valid]>=0)&(r.metrics['risk_vote_fraction'][r.valid]<=1)).all()
    with pytest.raises(ValueError):m.calibrate(b,y)


def test_tree_hand_calculation_and_invalid_structure():
    pytest.importorskip('sklearn')
    b,y=filter_data();m=FilterRiskClassifier(dict(pressure_drop='dp',flow_ratio='q'),n_estimators=1,min_samples_leaf=2,max_depth=2).fit(b,y)
    ref=json.loads(json.dumps(m.reference))
    ref['risk_forest']['trees']=[dict(left=[1,-1,-1],right=[2,-1,-1],feature=[0,-2,-2],threshold=[5.,-2.,-2.],vote=[.5,.2,.8])]
    m.set_reference(ref);x=np.zeros((3,8));x[:,0]=[4,5,6]
    np.testing.assert_allclose(m._votes(x),[.2,.2,.8])
    bad=json.loads(json.dumps(ref));bad['risk_forest']['trees'][0]['left'][0]=0
    with pytest.raises(ValueError,match='cyclic'):m.set_reference(bad)
    bad=json.loads(json.dumps(ref));bad['risk_forest']['trees'][0]['feature'][0]=8
    with pytest.raises(ValueError,match='feature'):m.set_reference(bad)


def test_classifier_observed_dust_conditions_not_trial_identity():
    pytest.importorskip('sklearn')
    b,y=filter_data();x=np.column_stack((b.values,np.ones(len(y)),np.full(len(y),2.)))
    d=SensorBatch(b.time_s,x,(*b.channels,'feed','material'),(*b.units,'1','1'),b.clock_id,b.asset_id,b.origin)
    ch=dict(pressure_drop='dp',flow_ratio='q',dust_feed_ratio='feed',dust_class='material')
    m=FilterRiskClassifier(ch,n_estimators=2,min_samples_leaf=2,max_depth=3).fit(d,y)
    assert m.reference['risk_forest']['feature_count']==10
    x[:,3]=7;bad=SensorBatch(b.time_s,x,d.channels,d.units,d.clock_id,d.asset_id,d.origin)
    result=m.score(bad)
    assert not result.valid.any() and set(result.reasons)=={'invalid_observed_dust_conditions'}
    with pytest.raises(ValueError):FilterRiskClassifier(dict(pressure_drop='dp',flow_ratio='q',dust_feed_ratio='feed'))
    with pytest.raises(ValueError):FilterRiskClassifier(ch,n_estimators=True)


@pytest.mark.parametrize('scope',['load_groups','evaporator_groups'])
def test_heatpump_group_calibration_reference_stream_and_unknown_load(scope):
    kw=dict(reference_mode='load_conditioned',feature_set='extended',calibration_scope=scope,evaporator_directional=True,persistence_s=30)
    m=HeatPumpPerformanceDiagnostic(HP,**kw).fit(heatpump()).calibrate(heatpump(1000))
    b=heatpump(2000);r=m.score(b);ref=json.loads(json.dumps(m.reference));assert len(ref['score_calibration']['load_groups'])==2
    clone=HeatPumpPerformanceDiagnostic(HP,**kw).set_reference(ref)
    np.testing.assert_allclose(clone.score(b).scores,r.scores)
    stream=StreamingDiagnostic(clone)
    parts=[stream.push(b.subset(slice(i,i+13))) for i in range(0,len(b.time_s),13)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in parts]),r.scores)
    x=b.values.copy();x[:,-1]=11250
    unknown=SensorBatch(b.time_s,x,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    ru=m.score(unknown);assert not ru.valid.any() and not ru.alarms.any()
    x=b.values.copy();x[:,2]-=4
    bad=SensorBatch(b.time_s,x,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    assert m.score(bad).alarms[3:40].all() and m.score(bad).alarms[43:].all()
    broken=json.loads(json.dumps(ref));broken['score_calibration']['load_groups'][0]['channel_scales'][4]=0
    with pytest.raises(ValueError):clone.set_reference(broken)
    with pytest.raises(ValueError):m.calibrate(heatpump(3000).subset(slice(0,40)))
    assert m.reference==ref


def test_group_heatpump_evaporation_channel_direction():
    m=HeatPumpPerformanceDiagnostic(HP,reference_mode='load_conditioned',feature_set='extended',calibration_scope='evaporator_groups',evaporator_directional=True).fit(heatpump()).calibrate(heatpump(1000))
    b=heatpump(2000);x=b.values.copy();x[:,2]+=1
    higher=SensorBatch(b.time_s,x,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    r=m.score(higher);assert (r.metrics['channel_evaporating_temperature_k_score']==0).all()
    # Other physical channels can still alarm: holding power and duty fixed
    # while raising evaporation temperature changes the Carnot-efficiency proxy.
    assert r.valid.all()
