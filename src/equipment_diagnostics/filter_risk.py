"""Experimental causal service-limit risk; not present-clogging diagnosis."""
import numpy as np
from .base import Diagnostic,finish,number


class FilterServiceRiskModel(Diagnostic):
    kind='filter_service_risk'
    reference_metric='pressure_pa'
    score_semantics='calibrated_inverse_remaining_service_life'

    def __init__(self,channels,*,horizon_s=30.,window_s=10.,ridge_alpha=.01,**kwargs):
        super().__init__(channels,**kwargs)
        self.horizon=number(horizon_s,'horizon_s',positive=True)
        self.window=number(window_s,'window_s',positive=True)
        self.ridge=number(ridge_alpha,'ridge_alpha',positive=True)
        self.params=dict(horizon_s=self.horizon,window_s=self.window,ridge_alpha=self.ridge)

    def _raw(self,batch):
        c,v=self._columns(batch,dict(pressure_drop='Pa',flow_ratio='1'),dict(dust_feed_ratio='1',dust_class='1'))
        p,q=c['pressure_drop'],c['flow_ratio'];v&=(p>=0)&(q>0)
        slope=np.zeros(len(p));ready=np.zeros(len(p),bool);start=0
        # Every window ends at the current observation. Invalid data, gaps,
        # episodes and observed mode changes reset the history.
        for i in range(len(p)):
            if self._break(batch,i,v):start=i
            while start<i and batch.time_s[start]<batch.time_s[i]-self.window:start+=1
            if v[i] and i-start>=2 and batch.time_s[i]-batch.time_s[start]>=.9*self.window:
                t=batch.time_s[start:i+1]-batch.time_s[i];z=np.log1p(p[start:i+1])
                t=t-t.mean();slope[i]=np.dot(t,z-z.mean())/np.dot(t,t);ready[i]=True
        m=dict(pressure_pa=p,flow_ratio=q,log_growth_per_s=slope)
        for k in ('dust_feed_ratio','dust_class'):
            if k in c:m[k]=c[k]
        return finish(m,v&ready)

    @staticmethod
    def _features(m):
        with np.errstate(all='ignore'):
            p=np.log1p(m['pressure_pa']);q=np.log(m['flow_ratio']);g=m['log_growth_per_s']
            return np.column_stack((p,q,g,p*p,p*q))

    def fit(self,batch,remaining_life_s,*,minimum_samples=20):
        # Labels are supplied separately and never placed in the sensor matrix.
        self.reference=None
        y=np.asarray(remaining_life_s,float)
        if y.shape!=batch.time_s.shape:raise ValueError('remaining life shape mismatch')
        if not np.isfinite(y).all() or (y<0).any():raise ValueError('invalid remaining life')
        super().fit(batch,minimum_samples=minimum_samples)
        try:
            m,v,_=self._raw(batch);x=self._features(m);v&=np.isfinite(x).all(axis=1)
            if v.sum()<minimum_samples:raise ValueError('insufficient risk training')
            center=x[v].mean(axis=0);scale=np.maximum(x[v].std(axis=0),1e-6)
            a=np.column_stack((np.ones(v.sum()),(x[v]-center)/scale))
            penalty=np.eye(a.shape[1])*self.ridge;penalty[0,0]=0
            coef=np.linalg.solve(a.T@a/len(a)+penalty,a.T@np.log(np.maximum(y[v],.1))/len(a))
            self.reference['risk_model']=dict(center=center.tolist(),scale=scale.tolist(),coefficients=coef.tolist())
        except Exception:self.reference=None;raise
        return self

    def set_reference(self,reference):
        m=reference.get('risk_model',{})
        for k,n in [('center',5),('scale',5),('coefficients',6)]:
            a=np.asarray(m.get(k),float)
            if a.shape!=(n,) or not np.isfinite(a).all() or (k=='scale' and (a<=0).any()):raise ValueError('invalid risk model')
        cal=reference.get('risk_calibration')
        if cal:
            number(cal.get('threshold'),'threshold',positive=True)
            if not cal.get('fingerprint') or cal['fingerprint']==reference.get('training_fingerprint'):raise ValueError('separate calibration required')
        return super().set_reference(reference)

    def calibrate(self,batch,remaining_life_s,*,negative_quantile=.95):
        if self.reference is None:raise ValueError('fit before calibration')
        q=number(negative_quantile,'negative_quantile',positive=True)
        if q>=1:raise ValueError('quantile must be below one')
        if batch.fingerprint==self.reference['training_fingerprint']:raise ValueError('separate calibration required')
        y=np.asarray(remaining_life_s,float)
        if y.shape!=batch.time_s.shape or not np.isfinite(y).all() or (y<0).any():raise ValueError('invalid remaining life')
        old=self.reference.pop('risk_calibration',None)
        try:
            r=self.score(batch);v=r.valid&(y>self.horizon)
            if v.sum()<20:raise ValueError('insufficient negative calibration')
            cut=max(1e-12,float(np.nextafter(np.quantile(r.scores[v],q),np.inf)))
            self.reference['risk_calibration']=dict(threshold=cut,negative_quantile=q,fingerprint=batch.fingerprint,
                negative_samples=int(v.sum()),label='future observed service limit, not present fault')
        except Exception:
            if old is not None:self.reference['risk_calibration']=old
            raise
        return self

    def _score(self,metrics):
        m=self.reference['risk_model'];x=self._features(metrics)
        a=np.column_stack((np.ones(len(x)),(x-np.asarray(m['center']))/np.asarray(m['scale'])))
        # Explicit finite numerical saturation, not infinite RUL or zero risk.
        pred=np.exp(np.clip(a@np.asarray(m['coefficients']),-20,30))
        metrics['predicted_remaining_service_life_s']=pred
        return self.horizon/pred/self.reference.get('risk_calibration',{}).get('threshold',1.)
