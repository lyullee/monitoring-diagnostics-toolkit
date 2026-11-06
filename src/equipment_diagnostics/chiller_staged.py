"""Cumulative chiller residual channels, causal EWMA and apparent condenser indicators."""
import numpy as np
from .chiller_reference import features,targets,predict

SENSOR_UNITS={'oil_sump_temperature':'K','oil_feed_temperature':'K','oil_feed_pressure':'Pa',
              'oil_net_pressure':'Pa','subcooling':'K','suction_superheat':'K','discharge_superheat':'K'}
AUX_KEYS=tuple(SENSOR_UNITS)
AUX_FLOORS=np.array([.2,.2,6894.757293168,6894.757293168,.2,.2,.2])
COND_KEYS=('log_condenser_ua','condenser_effectiveness','log_condenser_energy_ratio')
COND_FLOORS=np.array([np.log1p(.02),.01,np.log1p(.02)])
BASE_NAMES=('power','evaporator_approach','condenser_approach','chilled_flow')


def design(x,degree):
    cols=[np.ones(len(x)),*x.T]
    if degree==2: cols.extend(x[:,i]*x[:,j] for i in range(x.shape[1]) for j in range(i,x.shape[1]))
    return np.column_stack(cols)


def fit_model(x,y,names,floors,degree,alpha):
    center=x.mean(axis=0); scale=x.std(axis=0); scale=np.where(scale>1e-8,scale,1.)
    a=design((x-center)/scale,degree); penalty=np.eye(a.shape[1])*alpha; penalty[0,0]=0
    coef=np.linalg.solve(a.T@a/len(x)+penalty,a.T@y/len(x))
    residual=y-a@coef; bias=np.median(residual,axis=0)
    sigma=np.maximum(1.4826*np.median(abs(residual-bias),axis=0),floors)
    return dict(center=center.tolist(),scale=scale.tolist(),coefficients=coef.tolist(),
                residual_center=bias.tolist(),residual_scale=sigma.tolist(),targets=list(names))


def residual(model,x,y,degree):
    a=design((x-np.asarray(model['center']))/np.asarray(model['scale']),degree)
    expected=a@np.asarray(model['coefficients'])+np.asarray(model['residual_center'])
    return (y-expected)/np.asarray(model['residual_scale']),expected


def condenser_inputs(metrics):
    return np.column_stack((features(metrics),np.log(metrics['cooling_flow_kg_s'])))


def auxiliary_inputs(diagnostic,metrics):
    x=features(metrics)
    if diagnostic.auxiliary_conditioning=='water_refrigerant':
        # Saturation temperatures represent refrigerant-side operating state.
        # These are conditioning inputs, so faults expressed ONLY by their
        # changes may be masked. No claim of oil fault isolation is made.
        x=np.column_stack((x,metrics['evaporating_temperature_k'],metrics['condensing_temperature_k']))
    return x


def fit_reference(diagnostic,batch):
    metrics,valid,_=diagnostic._raw(batch)
    valid &= np.logical_and.reduce([np.isfinite(v) for v in metrics.values()])
    if valid.sum()<20: raise ValueError('insufficient staged chiller normal samples')
    x=auxiliary_inputs(diagnostic,metrics)[valid]
    ref={'schema':'equipment-diagnostics.chiller-staged.v1','stage':diagnostic.diagnostic_stage,
         'auxiliary':fit_model(x,np.column_stack([metrics[k] for k in AUX_KEYS])[valid],AUX_KEYS,
                               AUX_FLOORS,diagnostic.degree,diagnostic.ridge)}
    if diagnostic.diagnostic_stage==3:
        ref['condenser']=fit_model(condenser_inputs(metrics)[valid],
            np.column_stack([metrics[k] for k in COND_KEYS])[valid],COND_KEYS,COND_FLOORS,
            diagnostic.degree,diagnostic.ridge)
    return ref


def validate_reference(diagnostic,ref):
    if not isinstance(ref,dict) or ref.get('schema')!='equipment-diagnostics.chiller-staged.v1' or ref.get('stage')!=diagnostic.diagnostic_stage:
        raise ValueError('incompatible staged chiller reference')
    naux=5 if diagnostic.auxiliary_conditioning=='water_refrigerant' else 3
    for key,names,nfeatures in [('auxiliary',AUX_KEYS,naux)]+([('condenser',COND_KEYS,4)] if diagnostic.diagnostic_stage==3 else []):
        model=ref.get(key)
        if not isinstance(model,dict) or model.get('targets')!=list(names): raise ValueError('incomplete staged reference '+key)
        p=1+nfeatures+(nfeatures*(nfeatures+1)//2 if diagnostic.degree==2 else 0)
        for field,shape in [('center',(nfeatures,)),('scale',(nfeatures,)),('coefficients',(p,len(names))),
                            ('residual_center',(len(names),)),('residual_scale',(len(names),))]:
            a=np.asarray(model.get(field),float)
            if a.shape!=shape or not np.isfinite(a).all(): raise ValueError('invalid staged reference '+field)
            if field in ('scale','residual_scale') and (a<=0).any(): raise ValueError('nonpositive staged reference scale')


def ewma(diagnostic,batch,z,valid):
    """Initialize at normal mean zero and warm up by elapsed time; no future data."""
    filtered=np.full(z.shape,np.nan); accepted=valid.copy(); state=None; start=None
    for i in range(len(valid)):
        if not valid[i]: state=None; start=None; continue
        if diagnostic._break(batch,i,valid) or state is None:
            state=np.zeros(z.shape[1]); start=batch.time_s[i]
            filtered[i]=state; accepted[i]=False; continue
        alpha=-np.expm1(-(batch.time_s[i]-batch.time_s[i-1])/diagnostic.ewma_tau)
        state=alpha*z[i]+(1-alpha)*state; filtered[i]=state
        if batch.time_s[i]-start<diagnostic.ewma_warmup: accepted[i]=False
    return filtered,accepted


def enrich(diagnostic,batch,c,metrics,valid,reasons):
    metrics.update({k:c[k] for k in AUX_KEYS})
    physical=(c['oil_sump_temperature']>0)&(c['oil_feed_temperature']>0)&(c['oil_feed_pressure']>0)
    reasons[valid & ~physical]='invalid_oil_temperature_or_absolute_pressure'
    valid &= physical
    if diagnostic.diagnostic_stage==3:
        flow=c['cooling_flow']; hot=c['condensing_temperature']; inlet=c['cooling_in']; outlet=c['cooling_out']
        d1=hot-outlet; d2=hot-inlet
        with np.errstate(all='ignore'):
            relative=(d2-d1)/d1
            logratio=np.where(abs(relative)<.5,np.log1p(relative),np.log(d2)-np.log(d1))
            lmtd=np.divide(d2-d1,logratio,out=d1.copy(),where=d2!=d1)
            duty=flow*diagnostic.cp*(outlet-inlet); ua=duty/lmtd
            effectiveness=(outlet-inlet)/(hot-inlet)
            ratio=duty/(metrics['evaporator_duty_w']+metrics['electric_power_w'])
            metrics.update(cooling_flow_kg_s=flow,condenser_duty_w=duty,condenser_lmtd_k=lmtd,
                apparent_condenser_ua_w_k=ua,log_condenser_ua=np.log(ua),condenser_effectiveness=effectiveness,
                log_condenser_energy_ratio=np.log(ratio))
        physical=(flow>0)&(d1>0)&(d2>0)&(duty>0)&(ua>0)&(effectiveness>0)&(effectiveness<1)&(ratio>0)
        reasons[valid & ~physical]='condenser_indicator_outside_physical_domain'
        valid &= physical
    ref=None if diagnostic.reference is None else diagnostic.reference.get('staged_reference')
    if ref is None: return metrics,valid,reasons
    base=diagnostic.reference['conditioned_model']; expected=predict(base,features(metrics)); expected[:,1:3]=np.maximum(expected[:,1:3],0)
    with np.errstate(all='ignore'):
        zbase=(targets(metrics)-expected)/np.asarray(base['residual_scale'])
        zaux,paux=residual(ref['auxiliary'],auxiliary_inputs(diagnostic,metrics),np.column_stack([metrics[k] for k in AUX_KEYS]),diagnostic.degree)
    arrays=[zbase,zaux]; names=[*BASE_NAMES,*AUX_KEYS]
    for j,key in enumerate(AUX_KEYS):
        metrics['expected_'+key]=paux[:,j]
        metrics['instant_'+key+'_score']=abs(zaux[:,j])
    if diagnostic.diagnostic_stage==3:
        with np.errstate(all='ignore'):
            zcond,pcond=residual(ref['condenser'],condenser_inputs(metrics),
                                np.column_stack([metrics[k] for k in COND_KEYS]),diagnostic.degree)
        arrays.append(zcond); names.extend(COND_KEYS)
        for j,key in enumerate(COND_KEYS): metrics['expected_'+key]=pcond[:,j]
    z=np.column_stack(arrays)
    input_valid=valid.copy()
    # Domain gating must precede any temporal accumulation, not just final decisions.
    for role,(low,high) in diagnostic.reference['envelope'].items():
        outside=(metrics[role]<low)|(metrics[role]>high)
        reasons[input_valid & outside]='outside_reference_operating_envelope'; input_valid &= ~outside
    finite=np.isfinite(z).all(axis=1)&np.logical_and.reduce([np.isfinite(v) for v in metrics.values()])
    reasons[input_valid & ~finite]='nonfinite_staged_chiller_metric'; input_valid &= finite
    if diagnostic.diagnostic_stage>=2:
        filtered,accepted=ewma(diagnostic,batch,z,input_valid)
        reasons[input_valid & ~accepted]='ewma_warmup'
        valid=accepted
    else: filtered=z; valid=input_valid
    scores=abs(filtered); scores[:,0]=np.maximum(filtered[:,0],0)
    if diagnostic.diagnostic_stage==3: scores[:,-3]=np.maximum(-filtered[:,-3],0) # UA loss direction
    for j,key in enumerate(names): metrics['channel_'+key+'_score']=scores[:,j]
    metrics['staged_max_score']=np.max(scores,axis=1)
    return metrics,valid,reasons
