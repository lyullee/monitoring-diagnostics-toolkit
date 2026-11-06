import builtins
import json
import numpy as np
import pytest
from equipment_diagnostics import (FilterBoostedRiskClassifier,FilterBoostedLifeModel,FilterRiskEnsemble,HysteresisAlarmDiagnostic,ResidualCoherenceDiagnostic,SensorBatch,StreamingDiagnostic)
from test_risk_improvement import filter_data


def boosted(**kw):return FilterBoostedRiskClassifier(dict(pressure_drop='dp',flow_ratio='q'),n_estimators=4,min_samples_leaf=2,max_depth=3,max_leaf_nodes=4,**kw)


def test_boosted_export_roundtrip_and_numpy_only_inference(monkeypatch):
    pytest.importorskip('sklearn');b,y=filter_data();c,yc=filter_data(1000);d,_=filter_data(2000)
    m=boosted().fit(b,y).calibrate(c,yc);ref=json.loads(json.dumps(m.reference,allow_nan=False));r=m.score(d)
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name.startswith('sklearn'):raise AssertionError('sklearn imported during inference')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    clone=boosted().set_reference(ref);np.testing.assert_allclose(clone.score(d).scores,r.scores,equal_nan=True)
    assert r.alarms[-1] and 'boost_contribution_std' in r.metrics and 'tree_vote_std' not in r.metrics
    stream=StreamingDiagnostic(clone);chunks=[stream.push(d.subset(slice(i,i+17))) for i in range(0,len(d.time_s),17)]
    np.testing.assert_allclose(np.concatenate([x.scores for x in chunks]),r.scores,equal_nan=True)
    assert ref==m.reference


def test_boosted_signed_leaf_contributions_hand_calculation_and_bad_reference():
    pytest.importorskip('sklearn');b,y=filter_data()
    m=FilterBoostedRiskClassifier(dict(pressure_drop='dp',flow_ratio='q'),n_estimators=2,min_samples_leaf=2,max_depth=2).fit(b,y)
    ref=json.loads(json.dumps(m.reference));ref['risk_forest']['baseline_log_odds']=-.4
    ref['risk_forest']['trees']=[dict(left=[-1],right=[-1],feature=[-2],threshold=[0.],vote=[v]) for v in [.2,.3]]
    m.set_reference(ref);p,std=m._vote_statistics(np.zeros((2,8)))
    np.testing.assert_allclose(p,1/(1+np.exp(-.1)));np.testing.assert_allclose(std,.05)
    ref['risk_forest']['trees'][0]['vote'][0]=float('inf')
    with pytest.raises(ValueError):m.set_reference(ref)


CH=dict(evaporator_residual='ev',power_residual='p',speed_residual='n',cop_residual='cop',heat_demand='load')


def residuals(offset=0,shift=0,load=100):
    t=np.arange(40.)*10;v=np.sin(np.arange(40.)*.3)
    x=np.column_stack((v,v*.8,v*1.1,v*.9))+shift
    return SensorBatch(t+offset,np.column_stack((x,np.full(len(t),load))),('ev','p','n','cop','load'),('1','1','1','1','W'),'c','a','laboratory_measured')


def test_coherence_positive_projection_hand_distance_and_unknown_load():
    m=ResidualCoherenceDiagnostic(CH).fit(residuals());ref=json.loads(json.dumps(m.reference))
    ref['residual_groups'][0]['center']=[0.]*4;ref['residual_groups'][0]['inverse_covariance']=np.eye(4).tolist();m.set_reference(ref)
    b=SensorBatch(np.array([1000.,1010.]),np.array([[1,-2,3,0,100],[-1,-2,-3,-4,100.]]),('ev','p','n','cop','load'),('1','1','1','1','W'),'c','a','laboratory_measured')
    r=m.score(b);np.testing.assert_allclose(r.metrics['directional_mahalanobis_distance'],[np.sqrt(10),0]);assert r.alarms.tolist()==[True,False]
    unknown=m.score(residuals(offset=2000,load=101));assert not unknown.valid.any() and not unknown.alarms.any()


def test_coherence_collinearity_calibration_restore_and_stream():
    m=ResidualCoherenceDiagnostic(CH).fit(residuals()).calibrate(residuals(1000))
    assert np.linalg.eigvalsh(m.reference['residual_groups'][0]['inverse_covariance']).min()>0
    ref=json.loads(json.dumps(m.reference));b=residuals(2000,shift=2);r=m.score(b);assert r.alarms.any()
    clone=ResidualCoherenceDiagnostic(CH).set_reference(ref);stream=StreamingDiagnostic(clone)
    pieces=[stream.push(b.subset(slice(i,i+11))) for i in range(0,len(b.time_s),11)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in pieces]),r.scores)
    with pytest.raises(ValueError):m.calibrate(residuals())
    with pytest.raises(ValueError):m.calibrate(residuals(3000,load=101))
    assert m.reference==ref
    ref['residual_groups'][0]['inverse_covariance'][0][0]=-1
    with pytest.raises(ValueError):clone.set_reference(ref)


def test_coherence_unit_and_parameter_checks():
    with pytest.raises(ValueError):ResidualCoherenceDiagnostic(CH,shrinkage=1.1)
    b=residuals();wrong=SensorBatch(b.time_s,b.values,b.channels,('K','1','1','1','W'),b.clock_id,b.asset_id,b.origin)
    with pytest.raises(ValueError):ResidualCoherenceDiagnostic(CH).fit(wrong)


def test_boosted_life_reference_has_life_units_and_restores():
    pytest.importorskip('sklearn');b,y=filter_data();cal,yc=filter_data(1000)
    kw=dict(n_estimators=4,min_samples_leaf=2,max_depth=3,max_leaf_nodes=4)
    m=FilterBoostedLifeModel(dict(pressure_drop='dp',flow_ratio='q'),**kw).fit(b,y).calibrate(cal,yc)
    r=m.score(b);assert (r.metrics['predicted_remaining_service_life_s'][r.valid]>0).all() and 'risk_vote_fraction' not in r.metrics
    ref=json.loads(json.dumps(m.reference,allow_nan=False));clone=FilterBoostedLifeModel(dict(pressure_drop='dp',flow_ratio='q'),**kw).set_reference(ref)
    np.testing.assert_allclose(clone.score(b).scores,r.scores,equal_nan=True)
    assert ref['risk_forest']['prediction_mode']=='additive_log_life' and 'baseline_log_life' in ref['risk_forest']
    with pytest.raises(ValueError):FilterBoostedLifeModel(dict(pressure_drop='dp',flow_ratio='q'),calibration_scope='material')


def test_hysteresis_hand_confirmation_release_and_streaming():
    t=np.arange(10.);s=np.array([0,2,2,2,.7,.2,.2,.2,.2,.2]);b=SensorBatch(t,s[:,None],('risk',),('1',),'c','a','laboratory_measured')
    m=HysteresisAlarmDiagnostic(dict(indication_score='risk'),confirmation_s=2,release_ratio=.25,release_s=2)
    r=m.score(b);np.testing.assert_array_equal(r.alarms,[False,False,False,True,True,True,True,False,False,False])
    assert r.scores[4]<1 and r.alarms[4] and 'held' in r.metadata['score_semantics']
    stream=StreamingDiagnostic(m);pieces=[stream.push(b.subset(slice(i,i+3))) for i in range(0,len(t),3)]
    np.testing.assert_array_equal(np.concatenate([p.alarms for p in pieces]),r.alarms)
    prefix=m.score(b.subset(slice(0,5)));np.testing.assert_array_equal(prefix.alarms,r.alarms[:5])


def test_hysteresis_invalid_or_episode_change_resets_alarm():
    t=np.arange(8.);s=np.full((8,1),2.);v=np.ones_like(s,bool);v[4]=False
    b=SensorBatch(t,s,('risk',),('1',),'c','a','laboratory_measured',valid=v)
    m=HysteresisAlarmDiagnostic(dict(indication_score='risk'),confirmation_s=1)
    r=m.score(b);assert not r.valid[4] and not r.alarms[4] and not r.alarms[5] and r.alarms[6]
    with pytest.raises(ValueError):HysteresisAlarmDiagnostic(dict(indication_score='risk'),release_ratio=1)


def test_ensemble_convex_output_serialization_and_component_integrity():
    pytest.importorskip('sklearn');b,y=filter_data();cal,yc=filter_data(1000)
    m=FilterRiskEnsemble(dict(pressure_drop='dp',flow_ratio='q'),n_estimators=4,min_samples_leaf=2,max_depth=3,booster_weight=.75).fit(b,y).calibrate(cal,yc)
    raw,valid,_=m._raw(b);x=m._features(raw);a,c=[component._votes(x) for component in m.components]
    r=m.score(b);np.testing.assert_allclose(r.metrics['risk_vote_fraction'][valid],(.25*a+.75*c)[valid])
    assert 'component_disagreement' in r.metrics and 'tree_vote_std' not in r.metrics
    ref=json.loads(json.dumps(m.reference,allow_nan=False));clone=FilterRiskEnsemble(dict(pressure_drop='dp',flow_ratio='q'),**m.params).set_reference(ref)
    np.testing.assert_allclose(clone.score(b).scores,r.scores,equal_nan=True)
    clone.components[0].reference['center']+=1
    with pytest.raises(ValueError,match='component changed'):clone.score(b)
