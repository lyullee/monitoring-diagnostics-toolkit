"""Normal-only directional multivariate residual distance, per nominal load."""
import numpy as np
from .base import Diagnostic,finish,number


class ResidualCoherenceDiagnostic(Diagnostic):
    kind='residual_coherence'
    reference_metric='positive_residual_norm'
    ROLES=('evaporator_residual','power_residual','speed_residual','cop_residual')

    def __init__(self,channels,*,shrinkage=.1,**kwargs):
        super().__init__(channels,**kwargs);self.shrinkage=number(shrinkage,'shrinkage',positive=True)
        if self.shrinkage>1:raise ValueError('invalid shrinkage')
        self.params=dict(shrinkage=self.shrinkage)

    def _raw(self,batch):
        c,v=self._columns(batch,{**{k:'1' for k in self.ROLES},'heat_demand':'W'})
        x=np.column_stack([c[k] for k in self.ROLES])
        with np.errstate(all='ignore'):norm=np.maximum(np.linalg.norm(x,axis=1),1e-12)
        return finish({**{k:c[k] for k in self.ROLES},'heat_demand_w':c['heat_demand'],'positive_residual_norm':norm},v,physical=c['heat_demand']>0)

    def fit(self,batch,*,minimum_samples=20):
        super().fit(batch,minimum_samples=minimum_samples)
        try:
            m,v,_=self._raw(batch);x=np.column_stack([m[k] for k in self.ROLES]);groups=[]
            for load in np.unique(m['heat_demand_w'][v]):
                xx=x[v&(m['heat_demand_w']==load)]
                if len(xx)<minimum_samples:raise ValueError('insufficient load group')
                center=xx.mean(axis=0);cov=np.cov(xx,rowvar=False)
                cov=(1-self.shrinkage)*cov+self.shrinkage*np.diag(np.diag(cov))
                cov+=np.eye(4)*max(1e-8,float(np.max(np.diag(cov)))*1e-6)
                inverse=np.linalg.solve(cov,np.eye(4))
                groups.append(dict(load_w=float(load),center=center.tolist(),inverse_covariance=inverse.tolist(),accepted_samples=len(xx)))
            self.reference['residual_groups']=groups
        except Exception:self.reference=None;raise
        return self

    def _score(self,metrics):
        x=np.column_stack([metrics[k] for k in self.ROLES]);distance=np.full(len(x),np.nan);cut=np.ones(len(x));cal=self.reference.get('coherence_calibration',{}).get('groups',[])
        for group in self.reference['residual_groups']:
            mask=np.isclose(metrics['heat_demand_w'],group['load_w'],rtol=0,atol=1e-6)
            delta=np.maximum(x[mask]-np.asarray(group['center']),0.)
            distance[mask]=np.sqrt(np.maximum(np.sum((delta@np.asarray(group['inverse_covariance']))*delta,axis=1),0.))
            for threshold in cal:
                if threshold['load_w']==group['load_w']:cut[mask]=threshold['threshold']
        metrics['directional_mahalanobis_distance']=distance
        return distance/cut

    def calibrate(self,batch,*,quantile=.99,minimum_samples=10):
        if self.reference is None:raise ValueError('fit before calibration')
        q=number(quantile,'quantile',positive=True)
        if q>=1 or isinstance(minimum_samples,bool) or not isinstance(minimum_samples,int) or minimum_samples<2:raise ValueError('invalid calibration')
        if batch.fingerprint==self.reference['training_fingerprint']:raise ValueError('separate calibration required')
        previous=self.reference.pop('coherence_calibration',None)
        try:
            r=self.score(batch);groups=[]
            for group in self.reference['residual_groups']:
                mask=r.valid&(r.metrics['heat_demand_w']==group['load_w'])
                if mask.sum()<minimum_samples:raise ValueError('insufficient calibration group')
                cut=max(1.,float(np.nextafter(np.quantile(r.scores[mask],q),np.inf)))
                groups.append(dict(load_w=group['load_w'],threshold=cut,accepted_samples=int(mask.sum())))
            self.reference['coherence_calibration']=dict(groups=groups,quantile=q,fingerprint=batch.fingerprint)
        except Exception:
            if previous is not None:self.reference['coherence_calibration']=previous
            raise
        return self

    def set_reference(self,reference):
        groups=reference.get('residual_groups')
        if not isinstance(groups,list) or not groups:raise ValueError('missing groups')
        loads=[]
        for g in groups:
            loads.append(number(g.get('load_w'),'load',positive=True));center=np.asarray(g.get('center'),float);inverse=np.asarray(g.get('inverse_covariance'),float)
            if center.shape!=(4,) or inverse.shape!=(4,4) or not np.isfinite(center).all() or not np.isfinite(inverse).all():raise ValueError('invalid residual model')
            if not np.allclose(inverse,inverse.T,atol=1e-9,rtol=1e-9) or np.linalg.eigvalsh(inverse).min()<=0:raise ValueError('nonpositive covariance inverse')
        if len(set(loads))!=len(loads):raise ValueError('duplicate load')
        cal=reference.get('coherence_calibration')
        if cal:
            if not isinstance(cal,dict) or not cal.get('fingerprint') or cal['fingerprint']==reference.get('training_fingerprint'):raise ValueError('invalid calibration')
            if sorted(g['load_w'] for g in cal.get('groups',[]))!=sorted(loads):raise ValueError('incomplete calibration')
            for g in cal['groups']:number(g.get('threshold'),'threshold',positive=True)
        return super().set_reference(reference)
