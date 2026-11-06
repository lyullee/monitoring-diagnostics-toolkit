import json
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch,ChillerPerformanceDiagnostic,StreamingDiagnostic

CHANNELS=dict(chilled_in='in',chilled_out='out',cooling_out='coolout',cooling_in='coolin',
              evaporating_temperature='evap',condensing_temperature='cond',chilled_flow='flow',electric_power='p')


def data(*,power_factor=1.,flow_factor=1.,cool_offset=0.):
    # Deliberately simple synthetic normal curve, not experimental validation.
    q,tout,tc=np.meshgrid(np.linspace(30000,90000,5),[280.,283.,286.],[296.,300.,304.])
    q,tout,tc=q.ravel(),tout.ravel(),tc.ravel()
    logp=9+.7*(q/60000)-.02*(tout-283)+.025*(tc-300)+.08*(q/60000)**2
    flow=np.full(len(q),2.)*flow_factor
    values=np.column_stack((tout+q/(4180*flow),tout,tc+2,tc+cool_offset,tout-2-q/60000,
                            tc+5+q/60000,flow,np.exp(logp)*power_factor))
    return SensorBatch(np.arange(len(q),dtype=float),values,tuple(CHANNELS.values()),
                       ('K','K','K','K','K','K','kg/s','W'),'clock','asset','synthetic')


def model(**kw):
    return ChillerPerformanceDiagnostic(CHANNELS,reference_mode='conditioned',ridge_alpha=.001,**kw)


def test_conditioned_reference_matches_normal_and_detects_power_or_flow():
    m=model().fit(data())
    normal=m.score(data())
    assert normal.valid.all() and not normal.alarms.any()
    assert m.score(data(power_factor=1.5)).alarms.all()
    # Comparable cooling duty with a lower measured flow is an anomaly, not an abstention.
    reduced=m.score(data(flow_factor=.6))
    assert reduced.valid.all() and reduced.alarms.all()
    assert np.isfinite(normal.metrics['expected_cop']).all()


def test_roundtrip_domain_and_failed_refit():
    m=model().fit(data()); ref=json.loads(json.dumps(m.reference,allow_nan=False))
    clone=model().set_reference(ref)
    np.testing.assert_allclose(clone.score(data()).scores,m.score(data()).scores)
    assert not clone.score(data(cool_offset=40)).valid.any()
    outside=data(); values=outside.values.copy(); values[:,[2,3,5]]+=40
    outside=SensorBatch(outside.time_s,values,outside.channels,outside.units,outside.clock_id,outside.asset_id,outside.origin)
    r=clone.score(outside)
    assert not r.valid.any() and set(r.reasons)=={'outside_reference_operating_envelope'}
    damaged=json.loads(json.dumps(ref)); damaged['conditioned_model']['residual_scale'][0]=0
    with pytest.raises(ValueError): model().set_reference(damaged)
    with pytest.raises(ValueError):
        ChillerPerformanceDiagnostic(CHANNELS,reference_mode='conditioned',ridge_alpha=1).set_reference(ref)
    with pytest.raises(ValueError): m.fit(data().subset(slice(0,3)))
    assert m.reference is None


def test_missing_new_sensor_rejected_and_scoring_does_not_learn():
    channels=dict(CHANNELS); del channels['cooling_in']
    with pytest.raises(ValueError,match='cooling_in'):
        ChillerPerformanceDiagnostic(channels,reference_mode='conditioned').fit(data())
    m=model().fit(data()); before=json.dumps(m.reference,sort_keys=True)
    m.score(data(power_factor=2))
    assert json.dumps(m.reference,sort_keys=True)==before


def test_streaming_and_missing_values_preserve_conditional_decisions():
    m=model().fit(data()); b=data(power_factor=1.5)
    mask=b.valid.copy(); mask[10,0]=False
    b=SensorBatch(b.time_s,b.values,b.channels,b.units,b.clock_id,b.asset_id,b.origin,valid=mask)
    expected=m.score(b); stream=StreamingDiagnostic(m)
    chunks=[stream.push(b.subset(slice(i,i+7))) for i in range(0,len(b.time_s),7)]
    np.testing.assert_allclose(np.concatenate([r.scores for r in chunks]),expected.scores,equal_nan=True)
    assert not expected.valid[10] and not expected.alarms[10]
    for k in range(10,len(b.time_s),10):
        np.testing.assert_allclose(m.score(b.subset(slice(0,k))).scores,expected.scores[:k],equal_nan=True)


def test_calibration_is_separate_frozen_and_survives_reference_json():
    b=data(); m=model().fit(b)
    with pytest.raises(ValueError,match='differ'): m.calibrate(b)
    cal=SensorBatch(b.time_s+1000,b.values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    m.calibrate(cal)
    threshold=m.reference['score_calibration']['threshold']
    clone=model().set_reference(json.loads(json.dumps(m.reference)))
    result=clone.score(data(power_factor=1.5))
    assert result.metadata['score_semantics']=='ratio_to_normal_calibrated_threshold'
    np.testing.assert_allclose(result.scores,result.metrics['condition_residual_score']/threshold)
    assert result.alarms.all()
    before=json.dumps(clone.reference,sort_keys=True)
    clone.score(data(power_factor=2))
    assert json.dumps(clone.reference,sort_keys=True)==before
    with pytest.raises(ValueError,match='insufficient'):
        clone.calibrate(cal.subset(slice(0,2)))
    assert 'score_calibration' not in clone.reference
