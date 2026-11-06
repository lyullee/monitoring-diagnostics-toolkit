"""Explicit operating-condition helpers; no hidden material/property assumptions."""
import itertools
import numpy as np

def nonnegative_fit(a,y):
    if len(y)<10 or not np.isfinite(a).all() or not np.isfinite(y).all() or np.linalg.cond(a)>1e4:
        raise ValueError('insufficient independent normal operating excitation')
    scale=float(np.max(abs(y)))
    if scale==0: return np.zeros(a.shape[1])
    candidates=[]
    for size in range(1,a.shape[1]+1):
        for ix in itertools.combinations(range(a.shape[1]),size):
            c=np.zeros(a.shape[1]); c[list(ix)]=np.linalg.lstsq(a[:,ix],y/scale,rcond=None)[0]
            if np.isfinite(c).all() and (c>=0).all(): candidates.append(c)
    if not candidates: raise ValueError('no nonnegative normal model')
    return min(candidates,key=lambda c:np.sum((a@c-y/scale)**2))*scale

def heat_basis(metrics,ref,nh,nc):
    with np.errstate(all='ignore'):
        return np.column_stack((np.ones(len(metrics['ua_w_k'])),
            (ref[0]/metrics['hot_flow_kg_s'])**nh,(ref[1]/metrics['cold_flow_kg_s'])**nc))

def fit_heat(model,batch):
    metrics,valid,_=model._raw(batch)
    valid &= np.logical_and.reduce([np.isfinite(v) for v in metrics.values()])
    flows=[float(np.median(metrics[k][valid])) for k in ('hot_flow_kg_s','cold_flow_kg_s')]
    a=heat_basis(metrics,flows,model.hot_exponent,model.cold_exponent)
    good=valid&np.isfinite(a).all(axis=1)
    coef=nonnegative_fit(a[good],1/metrics['ua_w_k'][good])
    if not np.isfinite(coef).all() or coef.sum()<=0: raise ValueError('invalid thermal resistance model')
    model.reference['flow_resistance_model']={'flow_reference_kg_s':flows,'coefficients_k_w':coef.tolist()}

def validate_heat(ref):
    if not isinstance(ref,dict): raise ValueError('thermal resistance model missing')
    for key,n in [('flow_reference_kg_s',2),('coefficients_k_w',3)]:
        a=np.asarray(ref.get(key),float)
        if a.shape!=(n,) or not np.isfinite(a).all() or (a<0).any() or (key.startswith('flow') and (a<=0).any()) or a.sum()<=0:
            raise ValueError('invalid thermal resistance '+key)

RO_UNITS=dict(permeate_flow='m3/s',feed_pressure='Pa',concentrate_pressure='Pa',permeate_pressure='Pa',
    feed_osmotic_pressure='Pa',concentrate_osmotic_pressure='Pa',permeate_osmotic_pressure='Pa',membrane_temperature='K')

def ro_inputs(model,c):
    pf,pc,pp=(c[k] for k in ('feed_pressure','concentrate_pressure','permeate_pressure'))
    of,oc,op=(c[k] for k in ('feed_osmotic_pressure','concentrate_osmotic_pressure','permeate_osmotic_pressure'))
    t=c['membrane_temperature']
    with np.errstate(all='ignore'):
        hydraulic=.5*pf+.5*pc-pp; osmotic=.5*of+.5*oc-op
        ndp=hydraulic-osmotic
        factor=np.exp(model.activation/8.31446261815324*(1/t-1/model.reference_temperature))
    physical=(pf>=pc)&(pc>=pp)&(pp>=0)&(of>=0)&(oc>=0)&(op>=0)&(osmotic>=0)&(t>=model.temp_range[0])&(t<=model.temp_range[1])
    return ndp,factor,physical,dict(hydraulic_driving_pressure_pa=hydraulic,osmotic_difference_pa=osmotic,
        temperature_correction_factor=factor,membrane_temperature_k=t)

def column_predict(model,metrics):
    r=model.reference['learned_power_model']
    with np.errstate(all='ignore'):
        x=np.column_stack((np.log(metrics['vapor_flow_kg_s']/model.vref),np.log(metrics['liquid_flow_kg_s']/model.lref)))
        return np.exp(r['intercept_log_pa']+x@np.asarray(r['exponents']))

def fit_column(model,batch):
    m,v,_=model._raw(batch)
    v &= np.logical_and.reduce([np.isfinite(a) for a in m.values()])
    x=np.column_stack((np.log(m['vapor_flow_kg_s'][v]/model.vref),np.log(m['liquid_flow_kg_s'][v]/model.lref)))
    y=np.log(m['measured_pressure_drop_pa'][v]); xc=x-x.mean(axis=0); yc=y-y.mean()
    c=nonnegative_fit(xc,yc)
    intercept=float(y.mean()-x.mean(axis=0)@c)
    with np.errstate(all='ignore'): center=float(np.exp(intercept))
    if not np.isfinite(center) or center<=0: raise ValueError('invalid learned column reference')
    model.reference.update(center=center,learned_power_model=dict(intercept_log_pa=intercept,exponents=c.tolist()))

def validate_column(ref):
    if not isinstance(ref,dict): raise ValueError('learned column model missing')
    c=np.asarray(ref.get('exponents'),float)
    intercept=ref.get('intercept_log_pa')
    if c.shape!=(2,) or not np.isfinite(c).all() or (c<0).any() or isinstance(intercept,bool) or not isinstance(intercept,(int,float)) or not np.isfinite(intercept):
        raise ValueError('invalid learned column model')
