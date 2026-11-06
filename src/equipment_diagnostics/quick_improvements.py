"""Normal actuator dynamics and nonnegative viscous/inertial pressure reference."""
import numpy as np


def first_order_step(state,u0,u1,dt,tau):
    """Exact first-order response for a linearly varying input over dt."""
    with np.errstate(all='ignore'):
        r=np.float64(dt)/tau
        alpha=-np.expm1(-r)
        g=(r/2-r*r/6+r*r*r/24) if r<1e-4 else 1-alpha/r
        return (1-alpha)*state+(alpha-g)*u0+g*u1


def dynamic_valve(model,batch,command,position,mask,reasons):
    t=batch.time_s; error=np.full(len(t),np.nan); expected=error.copy()
    valid=np.zeros(len(t),bool); state=None; start=0; initialized=None
    for i in range(len(t)):
        if model._break(batch,i,mask): start=i; state=None; initialized=None
        if not mask[i]: continue
        target=t[i]-model.delay
        if target<t[start]: reasons[i]='actuator_delay_warmup'; continue
        if state is None:
            # Measured initial state is used only at a segment boundary, never at each row.
            state=position[i]; initialized=t[i]
            expected[i]=state; error[i]=0; reasons[i]='actuator_response_warmup'; continue
        left=t[i-1]-model.delay
        j0=max(start,int(np.searchsorted(t,left,side='right')))
        j1=min(i+1,int(np.searchsorted(t,target,side='left')))
        if j0>=j1:
            u0,u1=np.interp([left,target],t[start:i+1],command[start:i+1])
            state=first_order_step(state,u0,u1,target-left,model.response_time)
        else:
            knots=np.r_[left,t[j0:j1],target]
            u=np.interp(knots,t[start:i+1],command[start:i+1])
            for j,dt in enumerate(np.diff(knots)):
                state=first_order_step(state,u[j],u[j+1],dt,model.response_time)
        expected[i]=state; error[i]=position[i]-state
        if t[i]-initialized<model.response_warmup: reasons[i]='actuator_response_warmup'
        else: valid[i]=True; reasons[i]=''
    return {'tracking_error_fraction':error,'expected_position_fraction':expected},valid,reasons


def fit_hydraulic(model,metrics,valid):
    valid=valid&np.logical_and.reduce([np.isfinite(v) for v in metrics.values()])
    a=np.column_stack((metrics['viscous_basis'],metrics['inertial_basis']))[valid]
    y=metrics['measured_pressure_drop_pa'][valid]
    # Reject a constant/narrow flow experiment instead of claiming identifiable terms.
    if len(y)<10 or np.linalg.cond(a)>1e4:
        raise ValueError('insufficient independent viscous/inertial excitation')
    scale=float(np.max(y))
    if not np.isfinite(scale) or scale<=0: raise ValueError('positive pressure reference required')
    y=y/scale
    candidates=[np.linalg.lstsq(a,y,rcond=None)[0]]
    for j in range(2):
        c=np.zeros(2); c[j]=max(0,float(a[:,j]@y/(a[:,j]@a[:,j]))); candidates.append(c)
    candidates=[c for c in candidates if np.isfinite(c).all() and (c>=0).all()]
    coefficients=min(candidates,key=lambda c:np.sum((a@c-y)**2))*scale
    center=float(coefficients.sum())
    if not np.isfinite(center) or center<=0: raise ValueError('invalid mixed pressure fit')
    model.reference.update(mixed_coefficients_pa=coefficients.tolist(),center=center,
        mixed_model='a*(mu/muref)*(q/qref)+b*(rho/rhoref)*(q/qref)^2; a,b>=0')
