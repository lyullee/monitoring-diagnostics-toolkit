"""Normal-only conditional chiller reference; NumPy, no labels or online refits."""
import numpy as np


def features(metrics):
    return np.column_stack([metrics[k] for k in ('evaporator_duty_w','chilled_out_k','cooling_in_k')])


def targets(metrics):
    with np.errstate(divide='ignore',invalid='ignore'):
        return np.column_stack((np.log(metrics['electric_power_w']),metrics['evaporator_approach_k'],
                                metrics['condenser_approach_k'],np.log(metrics['chilled_flow_kg_s'])))


def design(x,degree):
    columns=[np.ones(len(x)),*x.T]
    if degree==2:
        columns.extend(x[:,i]*x[:,j] for i in range(3) for j in range(i,3))
    return np.column_stack(columns)


def fit(x,y,*,degree,alpha,floors):
    center=x.mean(axis=0); scale=x.std(axis=0)
    scale=np.where(scale>1e-8,scale,1.)
    a=design((x-center)/scale,degree)
    penalty=np.eye(a.shape[1])*alpha; penalty[0,0]=0
    coef=np.linalg.solve(a.T@a/len(a)+penalty,a.T@y/len(a))
    residual=y-a@coef
    residual_center=np.median(residual,axis=0)
    residual_scale=np.maximum(1.4826*np.median(np.abs(residual-residual_center),axis=0),floors)
    return {'schema':'equipment-diagnostics.chiller-regression.v1','degree':degree,'ridge_alpha':alpha,
            'feature_center':center.tolist(),'feature_scale':scale.tolist(),'coefficients':coef.tolist(),
            'residual_center':residual_center.tolist(),'residual_scale':residual_scale.tolist(),
            'features':['evaporator_duty_w','chilled_out_k','cooling_in_k'],
            'targets':['log_electric_power','evaporator_approach_k','condenser_approach_k','log_chilled_flow']}


def predict(model,x):
    a=design((x-np.asarray(model['feature_center']))/np.asarray(model['feature_scale']),model['degree'])
    return a@np.asarray(model['coefficients'])+np.asarray(model['residual_center'])


def augment(metrics,model):
    pred=predict(model,features(metrics))
    # Normal approach cannot be negative; clip only the predicted normal value,
    # never a measured value or a diagnostic residual.
    pred[:,1:3]=np.maximum(pred[:,1:3],0)
    residual=targets(metrics)-pred
    z=residual/np.asarray(model['residual_scale'])
    with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
        power=np.exp(pred[:,0]); flow=np.exp(pred[:,3])
        metrics.update({'expected_power_w':power,'expected_cop':metrics['evaporator_duty_w']/power,
            'expected_evaporator_approach_k':pred[:,1],'expected_condenser_approach_k':pred[:,2],
            'expected_chilled_flow_kg_s':flow,'power_excess_score':np.maximum(z[:,0],0),
            'evaporator_residual_score':np.abs(z[:,1]),'condenser_residual_score':np.abs(z[:,2]),
            'flow_residual_score':np.abs(z[:,3])})
    return metrics


def validate(model,degree,alpha):
    if (not isinstance(model,dict) or model.get('schema')!='equipment-diagnostics.chiller-regression.v1'
            or model.get('degree')!=degree or model.get('ridge_alpha')!=alpha):
        raise ValueError('incompatible conditional chiller reference')
    for key,shape in [('feature_center',(3,)),('feature_scale',(3,)),
            ('coefficients',(4 if degree==1 else 10,4)),('residual_center',(4,)),('residual_scale',(4,))]:
        a=np.asarray(model.get(key),dtype=float)
        if a.shape!=shape or not np.isfinite(a).all(): raise ValueError('invalid chiller model '+key)
        if key.endswith('scale') and np.any(a<=0): raise ValueError('nonpositive chiller model '+key)
