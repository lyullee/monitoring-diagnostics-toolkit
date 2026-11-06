import json
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch,ChillerPerformanceDiagnostic,StreamingDiagnostic
from equipment_diagnostics.chiller_staged import ewma
from test_conditioned_chiller import data,CHANNELS

AUX=dict(oil_sump_temperature='oil_sump',oil_feed_temperature='oil_feed',oil_feed_pressure='oil_p',
         oil_net_pressure='oil_net',subcooling='subcool',suction_superheat='sh_suc',discharge_superheat='sh_dis')


def measured(*,offset=0,oil_shift=0.,missing=False):
    b=data(); q=2*4180*(b.values[:,0]-b.values[:,1]); load=q/60000
    extra=np.column_stack((305+.2*load+oil_shift,310+.3*load,800000+1000*load,500000+5000*load,
                           4+.3*load,5+.2*load,20+load,np.full(len(q),20.)))
    values=np.column_stack((b.values,extra))
    if missing: values[25,8]=np.nan
    return SensorBatch(b.time_s*10+offset,values,(*b.channels,*AUX.values(),'cw'),
        (*b.units,'K','K','Pa','Pa','K','K','K','kg/s'),'clock','asset','synthetic')


def model(stage,**kw):
    channels={**CHANNELS,**AUX}
    if stage==3: channels['cooling_flow']='cw'
    return ChillerPerformanceDiagnostic(channels,reference_mode='conditioned',diagnostic_stage=stage,
        regression_degree=1,ridge_alpha=.001,**kw)


@pytest.mark.parametrize('stage',[1,2,3])
def test_stage_calibration_and_serialization_and_frozen_model(stage):
    m=model(stage).fit(measured()).calibrate(measured(offset=1000))
    normal=m.score(measured(offset=2000))
    assert normal.valid.sum()>10
    assert not normal.alarms[normal.valid].any()
    # A very large independent oil temperature perturbation must reach the diagnostic.
    r=m.score(measured(offset=2000,oil_shift=30))
    assert r.alarms[r.valid].all()
    ref=json.loads(json.dumps(m.reference,allow_nan=False))
    clone=model(stage).set_reference(ref)
    np.testing.assert_allclose(clone.score(measured(offset=2000)).scores,normal.scores,equal_nan=True)
    assert json.dumps(m.reference,sort_keys=True)==json.dumps(ref,sort_keys=True)
    damaged=json.loads(json.dumps(ref)); damaged['staged_reference']['auxiliary']['residual_scale'][0]=0
    with pytest.raises(ValueError): model(stage).set_reference(damaged)


def test_ewma_matches_continuous_time_step_and_resets_at_gap():
    m=model(2,ewma_tau_s=60,ewma_warmup_s=120)
    b=SensorBatch(np.array([0.,60,120,300,360]),np.ones((5,1)),('x',),('1',),'c','a','synthetic')
    filtered,valid=ewma(m,b,np.ones((5,1)),np.ones(5,bool))
    np.testing.assert_allclose(filtered[:,0],[0,1-np.exp(-1),1-np.exp(-2),0,1-np.exp(-1)])
    np.testing.assert_array_equal(valid,[False,False,True,False,False])


def test_ewma_batch_chunk_and_prefix_equivalence_with_exact_history():
    m=model(2,ewma_warmup_s=60).fit(measured()).calibrate(measured(offset=1000))
    b=measured(offset=2000,oil_shift=10,missing=True); expected=m.score(b)
    stream=StreamingDiagnostic(m,max_history_samples=100)
    pieces=[stream.push(b.subset(slice(i,i+7))) for i in range(0,len(b.time_s),7)]
    np.testing.assert_allclose(np.concatenate([r.scores for r in pieces]),expected.scores,equal_nan=True)
    assert stream.history_samples==len(b.time_s)
    for n in (15,29,40):
        np.testing.assert_allclose(m.score(b.subset(slice(0,n))).scores,expected.scores[:n],equal_nan=True)
    small=StreamingDiagnostic(m,max_history_samples=20); small.push(b.subset(slice(0,15)))
    with pytest.raises(ValueError,match='history'): small.push(b.subset(slice(15,30)))
    assert small.history_samples==15


def test_condenser_indicators_match_hand_calculation():
    m=model(3).fit(measured()); r=m.score(measured(offset=1000))
    # First synthetic point: CW rise=2 K, mass flow=20kg/s, cp=4180.
    # Condensing approach is 3.5/5.5 K on the two ends.
    raw,valid,_=m._raw(measured(offset=1000))
    assert raw['condenser_duty_w'][0]==pytest.approx(167200)
    assert raw['condenser_lmtd_k'][0]==pytest.approx(2/np.log(5.5/3.5))
    assert raw['apparent_condenser_ua_w_k'][0]==pytest.approx(167200*np.log(5.5/3.5)/2)
    assert raw['condenser_effectiveness'][0]==pytest.approx(2/5.5)
    assert not r.valid[:18].any()  # 180-second EWMA warmup


def test_stages_require_matching_sensor_roles_units_and_references():
    b=measured(); bad=dict(CHANNELS)
    with pytest.raises(ValueError,match='missing channel'):
        ChillerPerformanceDiagnostic(bad,reference_mode='conditioned',diagnostic_stage=1).fit(b)
    units=list(b.units); units[8]='degC'
    wrong=SensorBatch(b.time_s,b.values,b.channels,tuple(units),b.clock_id,b.asset_id,b.origin)
    with pytest.raises(ValueError,match='expected K'): model(1).fit(wrong)
    ref=model(1).fit(b).reference
    with pytest.raises(ValueError): model(2).set_reference(ref)
    with pytest.raises(ValueError):
        ChillerPerformanceDiagnostic(CHANNELS,diagnostic_stage=1)


def test_condenser_equal_end_differences_limit_and_invalid_domain():
    m=model(3).fit(measured()); b=measured(offset=1000)
    # An infinitesimal positive water rise approaches the equal-LMTD limit.
    values=b.values.copy(); values[:,2]=values[:,3]+1e-10
    tiny=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    raw,_,_=m._raw(tiny)
    np.testing.assert_allclose(raw['condenser_lmtd_k'],values[:,5]-values[:,3],rtol=1e-9)
    # The exact equal-end limit has no heat transfer and must be UNKNOWN, never a valid alarm.
    values[:,2]=values[:,3]
    zero=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    r=m.score(zero)
    assert not r.valid.any() and not r.alarms.any()
    json.dumps(r.to_dict(),allow_nan=False)


@pytest.mark.parametrize('role,value',[('oil_sump',-1.),('oil_p',0.),('cw',-1.),('oil_feed',1e308)])
def test_staged_unphysical_and_overflow_are_unknown(role,value):
    m=model(3).fit(measured()); b=measured(offset=1000)
    values=b.values.copy(); values[:,b.channels.index(role)]=value
    bad=SensorBatch(b.time_s,values,b.channels,b.units,b.clock_id,b.asset_id,b.origin)
    with np.errstate(all='ignore'): r=m.score(bad)
    assert not r.valid.any() and not r.alarms.any()
    json.dumps(r.to_dict(),allow_nan=False)
