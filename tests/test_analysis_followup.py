import json
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch,TemporalEvidenceDiagnostic,FilterRiskClassifier,StreamingDiagnostic
from equipment_diagnostics.heat_pump import heating_temperature_metrics
from test_risk_improvement import filter_data


def score_batch(score,time=None,offset=0,load=100):
    score=np.asarray(score,float);time=np.arange(len(score))*10. if time is None else np.asarray(time,float)
    return SensorBatch(time+offset,np.column_stack((score,np.full(len(score),load))),('s','load'),('1','W'),'c','a','laboratory_measured')


def evidence(**kw):return TemporalEvidenceDiagnostic(dict(indication_score='s',heat_demand='load'),**kw)


def test_temporal_ewma_cusum_irregular_hand_calculation():
    m=evidence(time_constant_s=10).fit(score_batch(np.full(20,.2)))
    ref=json.loads(json.dumps(m.reference));ref['evidence_groups'][0]['drift']=.5;m.set_reference(ref)
    r=m.score(score_batch([0,1,1],[0,10,30],offset=1000))
    expected_smooth=np.array([0,1-np.exp(-1),1-np.exp(-3)])
    expected_e=np.array([0,10*(expected_smooth[1]-.5),10*(expected_smooth[1]-.5)+20*(expected_smooth[2]-.5)])
    np.testing.assert_allclose(r.metrics['smoothed_score'],expected_smooth)
    np.testing.assert_allclose(r.metrics['cusum_score_seconds'],expected_e)
    np.testing.assert_array_equal(r.alarms,[False,False,True])


def test_temporal_normal_calibration_and_streaming_causality():
    train=score_batch(np.tile([.2,.4],20));cal=score_batch(np.tile([.2,.5],20),offset=1000)
    m=evidence().fit(train).calibrate(cal);assert not m.score(cal).alarms.any()
    b=score_batch(np.r_[np.full(20,.3),np.full(30,1.5)],offset=2000);r=m.score(b)
    assert r.alarms[-1]
    ref=json.loads(json.dumps(m.reference,allow_nan=False));clone=evidence().set_reference(ref);stream=StreamingDiagnostic(clone)
    chunks=[stream.push(b.subset(slice(i,i+7))) for i in range(0,len(b.time_s),7)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in chunks]),r.scores)
    prefix=m.score(b.subset(slice(0,23)));np.testing.assert_allclose(prefix.scores,r.scores[:23])
    assert ref==m.reference
    with pytest.raises(ValueError):m.calibrate(train)
    with pytest.raises(ValueError):m.calibrate(cal,minimum_samples=True)
    with pytest.raises(ValueError):m.calibrate(score_batch([-1]*20,offset=3000))
    assert m.reference==ref


def test_temporal_gap_and_unsupported_load_do_not_accumulate():
    m=evidence().fit(score_batch([.2]*20))
    b=score_batch([2]*5,[0,10,20,100,110],offset=1000);r=m.score(b)
    assert r.metrics['cusum_score_seconds'][3]==0 and not r.alarms[3]
    unknown=m.score(score_batch([2]*20,offset=2000,load=101))
    assert not unknown.valid.any() and not unknown.alarms.any()
    bad=json.loads(json.dumps(m.reference));bad['evidence_groups'][0]['drift']=0
    with pytest.raises(ValueError):evidence().set_reference(bad)
    with pytest.raises(ValueError):evidence(time_constant_s=0)


def test_physical_temperature_indicators_need_no_invented_load_or_shaft_speed():
    m=heating_temperature_metrics(np.array([10000.]),np.array([2000.]),np.array([280.]),np.array([320.]),np.array([315.]),np.array([340.]))
    assert m['heating_cop'][0]==5 and m['isothermal_heating_carnot_cop'][0]==8
    assert m['subcooling_k'][0]==5 and m['discharge_superheat_k'][0]==20
    assert m['log_carnot_efficiency_proxy'][0]==pytest.approx(np.log(5/8))
    assert 'heat_demand_w' not in m and 'mass_per_revolution_kg' not in m


def dusty(offset=0,material=2,feed=2.):
    b,y=filter_data(offset);x=np.column_stack((b.values,np.full(len(y),feed),np.full(len(y),material)))
    return SensorBatch(b.time_s,x,(*b.channels,'feed','dust'),(*b.units,'1','1'),b.clock_id,b.asset_id,b.origin),y


CH=dict(pressure_drop='dp',flow_ratio='q',dust_feed_ratio='feed',dust_class='dust')


def test_filter_dose_features_are_causal_and_hand_calculated():
    pytest.importorskip('sklearn');b,y=dusty();m=FilterRiskClassifier(CH,feature_set='dose',n_estimators=3,min_samples_leaf=2,max_depth=4).fit(b,y)
    raw,v,_=m._raw(b);i=40
    assert raw['log_dose_proxy'][i]==pytest.approx(np.log1p(2*b.time_s[i]))
    assert raw['log_reference_flow_pressure'][i]==pytest.approx(np.log1p(b.values[i,0]/1.1**2))
    assert raw['growth_per_feed_ratio'][i]==pytest.approx(raw['log_growth_per_s'][i]/2)
    assert m.reference['risk_forest']['feature_count']==13
    ref=json.loads(json.dumps(m.reference));clone=FilterRiskClassifier(CH,feature_set='dose',n_estimators=3,min_samples_leaf=2,max_depth=4).set_reference(ref)
    np.testing.assert_allclose(clone.score(b).scores,m.score(b).scores,equal_nan=True)
    np.testing.assert_allclose(m.score(b.subset(slice(0,80))).scores,m.score(b).scores[:80],equal_nan=True)


def test_filter_support_and_dispersion_do_not_hide_eligible_rows():
    pytest.importorskip('sklearn');b,y=dusty();m=FilterRiskClassifier(CH,n_estimators=3,min_samples_leaf=2,max_depth=4).fit(b,y)
    c,_=dusty(offset=1000,feed=5.);r=m.score(c)
    assert (r.metrics['training_support_fraction'][r.valid]<1).all()
    assert (r.metrics['tree_vote_std'][r.valid]>=0).all() and r.valid.sum()==m.score(b).valid.sum()
    bad=json.loads(json.dumps(m.reference));bad['risk_forest']['training_support'][0]['material']=7
    with pytest.raises(ValueError):m.set_reference(bad)


def test_material_calibration_missing_group_restores_previous_reference():
    pytest.importorskip('sklearn');b,y=dusty();m=FilterRiskClassifier(CH,calibration_scope='material',n_estimators=3,min_samples_leaf=2,max_depth=4).fit(b,y)
    ref=json.loads(json.dumps(m.reference));c,yc=dusty(1000)
    with pytest.raises(ValueError,match='material'):m.calibrate(c,yc)
    assert m.reference==ref
