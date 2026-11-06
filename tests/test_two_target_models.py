from copy import deepcopy
import json
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch,ConditionalResidualDiagnostic,WindowChangeDiagnostic,StreamingDiagnostic

def batch(x,y,*,time=None,episodes=None,basis='example'):
    n=len(x)
    return SensorBatch(np.arange(n,dtype=float) if time is None else time,np.column_stack((x,y)),('x','y'),('1','1'),
        'clock','asset','simulation',episodes=episodes,metadata={'signal_basis_id':basis})
def model(**kw):return ConditionalResidualDiagnostic(dict(x='x',y='y'),features=dict(x=dict(unit='1',log=False)),
    targets=dict(y=dict(unit='1',log=False,direction=1,scale_floor=.1)),**kw)

def test_conditional_hand_reference_and_response():
    x=np.linspace(1,3,50);m=model(ridge_alpha=1e-12).fit(batch(x,2*x+1))
    r=m.score(batch(x,2*x+1+.6))
    np.testing.assert_allclose(r.metrics['expected_y'],2*x+1,atol=1e-10)
    np.testing.assert_allclose(r.metrics['residual_y'],6,atol=1e-9)
    assert r.alarms.all()

def test_per_context_calibration_does_not_pool_wider_context():
    x=np.r_[np.ones(30),np.full(30,2.)];m=model(calibration_role='x',minimum_z=1).fit(batch(x,np.zeros(60)))
    cal=batch(x,np.r_[np.zeros(30),np.tile([-.4,.4],15)])
    m.calibrate(cal,quantile=.99);groups=m.reference['residual_calibration']['groups']
    assert groups[0]['threshold']==1 and groups[1]['threshold']>3
    r=m.score(batch([1,2],[.3,.3]));assert r.alarms.tolist()==[True,False]
    clone=model(calibration_role='x',minimum_z=1).set_reference(m.reference)
    np.testing.assert_allclose(clone.score(batch([1,2],[.3,.3])).scores,r.scores)

def test_conditional_mean_causality_boundaries_and_identity():
    x=np.linspace(1,3,30);m=model(window_s=3,ridge_alpha=1e-12,max_gap_s=2).fit(batch(x,2*x))
    b=batch(np.full(8,2.),[4,4,4,4,5,5,5,5]);r=m.score(b)
    assert not r.valid[:3].any() and r.valid[3:].all()
    np.testing.assert_allclose(r.metrics['mean_residual_y'][4:],[2.5,5,7.5,10],atol=1e-9)
    s=StreamingDiagnostic(m,max_history_samples=100)
    a=s.push(b.subset(slice(0,5)));c=s.push(b.subset(slice(5,8)))
    np.testing.assert_allclose(np.r_[a.scores,c.scores],r.scores,equal_nan=True)
    with pytest.raises(ValueError):m.score(batch(np.full(8,2.),np.full(8,4.),basis='wrong'))

def test_conditional_calibration_rollback_domain_and_invalid_reference():
    x=np.linspace(1,3,50);b=batch(x,2*x);m=model().fit(b)
    with pytest.raises(ValueError):m.calibrate(b)
    old=deepcopy(m.reference)
    with pytest.raises(ValueError):m.calibrate(batch([100]*20,[1]*20))
    assert m.reference==old
    r=m.score(batch([100,2],[1,np.nan]));assert not r.valid.any()
    bad=deepcopy(old);bad['conditional_model']['scale'][0]=0
    with pytest.raises(ValueError):m.set_reference(bad)

def signal(a,*,episodes=None,time=None,basis='change'):
    return SensorBatch(np.arange(len(a),dtype=float) if time is None else time,np.asarray(a,float)[:,None],('s',),('1',),
        'clock','asset','simulation',episodes=episodes,metadata={'signal_basis_id':basis})
def change(**kw):return WindowChangeDiagnostic(dict(signal='s'),**dict(dict(mean_window_s=2,lags_s=[2,4],minimum_change=.1),**kw))

def test_change_hand_step_offset_invariance_and_no_future_baseline():
    m=change().fit(signal(np.zeros(30)))
    b=signal([0,0,0,0,0,.3,.3,.3,.3]);r=m.score(b)
    assert not r.valid[:4].any()
    assert r.metrics['change_0'][5]==pytest.approx(.1)
    assert r.metrics['change_0'][6]==pytest.approx(.2)
    shifted=m.score(signal(np.array([0,0,0,0,0,.3,.3,.3,.3])+100))
    np.testing.assert_allclose(shifted.scores,r.scores,equal_nan=True,atol=1e-10)
    early=m.score(b.subset(slice(0,7)))
    np.testing.assert_allclose(early.scores,r.scores[:7],equal_nan=True)

def test_change_reset_calibration_and_streaming():
    m=change(max_gap_s=2).fit(signal(np.zeros(30)))
    cal=signal(np.sin(np.arange(40))*.01);m.calibrate(cal,quantile=.99)
    old=deepcopy(m.reference)
    with pytest.raises(ValueError):m.calibrate(signal(np.zeros(10),episodes=np.arange(10)))
    assert old==m.reference
    b=signal(np.r_[np.zeros(10),np.ones(10)]);r=m.score(b)
    s=StreamingDiagnostic(m,max_history_samples=100);a=s.push(b.subset(slice(0,13)));c=s.push(b.subset(slice(13,20)))
    np.testing.assert_allclose(np.r_[a.scores,c.scores],r.scores,equal_nan=True)
    m2=change(max_gap_s=2).set_reference(m.reference)
    np.testing.assert_allclose(m2.score(b).scores,r.scores,equal_nan=True)
    with pytest.raises(ValueError):m.score(signal(np.zeros(30),basis='other'))

def test_new_model_units_and_invalid_configuration():
    with pytest.raises(ValueError):change(lags_s=[4,2])
    with pytest.raises(ValueError):model(degree=True)
    bad=SensorBatch(np.arange(30.),np.column_stack((np.ones(30),np.ones(30))),('x','y'),('Pa','1'),'clock','asset','simulation')
    with pytest.raises(ValueError):model().fit(bad)


def test_sorted_json_roundtrip_preserves_feature_and_target_matrix_order():
    features={'z':dict(unit='1',log=False),'a':dict(unit='1',log=False)}
    targets={'yy':dict(unit='1',log=False,direction=1,scale_floor=.1),'bb':dict(unit='1',log=False,direction=-1,scale_floor=.2)}
    n=60;x=np.linspace(1,3,n);a=np.sin(x)
    b=SensorBatch(np.arange(n,dtype=float),np.column_stack((x,a,2*x+3*a,4*x-2*a)),('z','a','yy','bb'),('1',)*4,'clock','asset','simulation')
    m=ConditionalResidualDiagnostic({k:k for k in [*features,*targets]},features=features,targets=targets).fit(b)
    saved=json.loads(json.dumps(dict(channels=m.channels,params=m.params,reference=m.reference),sort_keys=True))
    restored=ConditionalResidualDiagnostic(saved['channels'],**saved['params']).set_reference(saved['reference'])
    np.testing.assert_allclose(restored.score(b).scores,m.score(b).scores)
    wrong=deepcopy(saved['params']);wrong['target_order']=list(reversed(wrong['target_order']))
    with pytest.raises(ValueError):ConditionalResidualDiagnostic(saved['channels'],**wrong).set_reference(saved['reference'])


def test_unrepresentable_normal_fit_is_rejected_and_clears_reference():
    m=model().fit(batch(np.linspace(1,3,30),np.ones(30)))
    with np.errstate(all='ignore'),pytest.raises((ValueError,np.linalg.LinAlgError)):
        m.fit(batch(np.full(30,1e308),np.tile([1e308,-1e308],15)))
    assert m.reference is None
