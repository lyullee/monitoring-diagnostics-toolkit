from copy import deepcopy
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch,SignedResidualCUSUM,StreamingDiagnostic,evaporator_conductance_proxy

def batch(x,*,time=None,context=None,episode=None,basis=None):
    x=np.asarray(x,float);n=len(x)
    return SensorBatch(np.arange(n,dtype=float) if time is None else time,
        np.column_stack((x,np.ones(n) if context is None else context)),('s','g'),('1','1'),
        'clock','asset','simulation',episodes=episode,metadata={} if basis is None else {'signal_basis_id':basis})

def model(**kw):return SignedResidualCUSUM(dict(signal='s',context='g'),scale_floor=1,**kw)

def test_signed_hand_formula_negative_residual_releases_evidence():
    m=model().fit(batch(np.zeros(30)))
    r=m.score(batch([0,1,1,-2,1]))
    np.testing.assert_allclose(r.metrics['cusum_statistic'],[0,.75,1.5,0,.75])
    np.testing.assert_allclose(r.scores,[0,.15,.3,0,.15])

def test_elapsed_time_gap_context_and_episode_reset():
    m=model(max_gap_s=3).fit(batch(np.zeros(40),context=[1]*20+[2]*20))
    r=m.score(batch([1,1,1,1,1],time=[0,2,3,10,11],context=[1,1,2,2,2],episode=[0,0,0,0,1]))
    np.testing.assert_allclose(r.metrics['cusum_statistic'],[.75,2.25,.75,.75,.75])
    assert not m.score(batch([1,1],context=[7,7])).valid.any()

def test_blocked_normal_calibration_and_roundtrip():
    m=model().fit(batch(np.sin(np.arange(100))*.1))
    cal=batch(np.cos(np.arange(100))*.1)
    m.calibrate(cal,block_s=5,horizon_s=60,replicates=20,seed=123)
    assert not m.score(cal).alarms.any()
    frozen=deepcopy(m.reference)
    clone=model().set_reference(frozen)
    x=batch(np.full(100,2.))
    np.testing.assert_allclose(clone.score(x).scores,m.score(x).scores)
    assert len(frozen['signed_calibration']['groups'][0]['bootstrap_maxima'])==20

def test_calibration_failure_transaction_and_no_cross_episode_blocks():
    m=model().fit(batch(np.zeros(30)));cal=batch(np.zeros(30))
    with pytest.raises(ValueError):m.calibrate(batch(np.zeros(30),episode=np.arange(30)),block_s=5,horizon_s=60,replicates=20)
    assert 'signed_calibration' not in m.reference
    with pytest.raises(ValueError):m.calibrate(cal) # exact same training fingerprint
    m.calibrate(batch(np.full(30,.01)))
    old=deepcopy(m.reference)
    with pytest.raises(ValueError):m.calibrate(batch(np.ones(2)))
    assert m.reference==old

def test_innovation_hand_calculation_and_first_sample_abstention():
    m=model(prewhiten=True).fit(batch(np.sin(np.arange(40))))
    ref=deepcopy(m.reference);g=ref['signed_groups'][0]
    g.update(center=0.,scale=1.,ar1_phi=.5,innovation_center=0.,innovation_scale=1.)
    m.set_reference(ref);r=m.score(batch([1,1,2,2,1]))
    assert not r.valid[0] and r.valid[1:].all()
    np.testing.assert_allclose(r.metrics['cusum_statistic'][1:],[.25,1.5,2.25,2])

def test_streaming_exact_match_reference_immutability_and_limit():
    m=model(prewhiten=True).fit(batch(np.sin(np.arange(50))))
    b=batch(np.sin(np.arange(60))+1);whole=m.score(b);s=StreamingDiagnostic(m,max_history_samples=100)
    chunks=[s.push(b.subset(slice(0,23))),s.push(b.subset(slice(23,60)))]
    np.testing.assert_allclose(np.concatenate([r.scores for r in chunks]),whole.scores,equal_nan=True)
    np.testing.assert_array_equal(np.concatenate([r.alarms for r in chunks]),whole.alarms)
    m.reference['signed_groups'][0]['center']+=.1
    with pytest.raises(ValueError):s.push(batch([1,2],time=[61,62]))
    small=StreamingDiagnostic(model().fit(batch(np.zeros(30))),max_history_samples=10)
    with pytest.raises(ValueError):small.push(b)

@pytest.mark.parametrize('kw',[dict(prewhiten=1),dict(reference_step_s=0),dict(context_unit='Pa'),dict(drift_sigma=True)])
def test_invalid_configuration(kw):
    with pytest.raises(ValueError):model(**kw)

def test_reference_structure_and_nonfinite_input():
    m=model(prewhiten=True).fit(batch(np.sin(np.arange(40))));r=deepcopy(m.reference)
    r['signed_groups'][0]['ar1_phi']=1
    with pytest.raises(ValueError):m.set_reference(r)
    x=m.score(batch([1,np.nan,1,1]));assert not x.valid[:3].any() and x.valid[3]

def test_evaporator_proxy_hand_answer_and_invalid_domain():
    r=evaporator_conductance_proxy([10000,2000,10000],[3000]*3,[278,278,283],[283]*3)
    assert r['conductance_proxy_w_k'][0]==pytest.approx(1400)
    assert r['evaporator_duty_proxy_w'][0]==pytest.approx(7000)
    assert r['valid'].tolist()==[True,False,False]

def test_extreme_signal_and_corrupt_units_are_not_normal_evidence():
    m=model().fit(batch(np.zeros(30)))
    r=m.score(batch([1e308,1e308,1e308]))
    assert not r.valid[-1] and not r.alarms[-1]
    bad=SensorBatch([0],[[1,1]],('s','g'),('Pa','1'),'clock','asset','simulation')
    with pytest.raises(ValueError):m.score(bad)


def test_nominal_heat_demand_context_rejects_nonpositive_training():
    b=SensorBatch(np.arange(30.),np.column_stack((np.zeros(30),-np.ones(30))),('s','g'),('1','W'),
        'clock','asset','simulation')
    m=SignedResidualCUSUM(dict(signal='s',context='g'),context_unit='W')
    with pytest.raises(ValueError):m.fit(b)


def test_context_switch_resets_alarm_persistence_without_changing_identity():
    m=model(persistence_s=2).fit(batch(np.zeros(40),context=[1]*20+[2]*20))
    b=batch(np.full(6,10.),context=[1,1,1,2,2,2]);r=m.score(b)
    assert r.alarms.tolist()==[False,False,True,False,False,True]
    assert r.metadata['episodes']==b.episodes.tolist()


def test_derived_signal_binding_rejects_another_upstream_model():
    m=model().fit(batch(np.zeros(30),basis='upstream-reference-A'))
    assert m.score(batch(np.ones(5),basis='upstream-reference-A')).valid.all()
    with pytest.raises(ValueError):m.score(batch(np.ones(5),basis='upstream-reference-B'))
    with pytest.raises(ValueError):m.score(batch(np.ones(5)))
