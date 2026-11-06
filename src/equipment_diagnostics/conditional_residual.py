"""Explicit normal response model with causal residual means and separate calibration."""
from copy import deepcopy
import numpy as np
from .base import Diagnostic,finish,number
from .chiller_staged import design


class ConditionalResidualDiagnostic(Diagnostic):
    """Predict normal responses from explicit observed operating features.

    Every feature/target specifies its unit and log transform. Targets add
    direction and scale_floor; preserve feature_order and target_order in
    configuration and saved references. Fit normal regression, calibrate on
    separate normal data, then freeze before evaluation. observed/expected
    metrics remain in transformed space, not necessarily physical units.
    """
    kind='conditional_normal_residual'
    reference_metric='response_magnitude'
    requires_full_history=True
    score_semantics='normal_standardized_residual_to_calibrated_limit'

    def __init__(self,channels,*,features,targets,degree=1,ridge_alpha=.01,window_s=0.,minimum_z=3.,calibration_role=None,
                 feature_order=None,target_order=None,**kwargs):
        super().__init__(channels,**kwargs)
        if degree not in (1,2) or isinstance(degree,bool):raise ValueError('degree1 or2 required')
        if not isinstance(features,dict) or not features or not isinstance(targets,dict) or not targets:
            raise ValueError('explicit feature and target specifications required')
        if set(features)&set(targets) or set(channels)!=set(features)|set(targets):raise ValueError('inconsistent role specifications')
        fo=list(features) if feature_order is None else list(feature_order)
        to=list(targets) if target_order is None else list(target_order)
        if len(fo)!=len(features) or set(fo)!=set(features) or len(to)!=len(targets) or set(to)!=set(targets):raise ValueError('complete unique feature/target order required')
        self.features={k:deepcopy(features[k]) for k in fo};self.targets={k:deepcopy(targets[k]) for k in to}
        for role,spec in {**self.features,**self.targets}.items():
            if not isinstance(spec,dict) or not isinstance(spec.get('unit'),str) or not spec['unit'].strip() or not isinstance(spec.get('log'),bool):raise ValueError('unit/log specification required')
        for spec in self.targets.values():
            if isinstance(spec.get('direction'),bool) or spec.get('direction') not in (-1,0,1):raise ValueError('direction -1/0/1 required')
            number(spec.get('scale_floor'),'scale_floor',positive=True)
        self.degree=degree;self.ridge=number(ridge_alpha,'ridge_alpha',positive=True)
        self.window=number(window_s,'window_s',nonnegative=True);self.minimum=number(minimum_z,'minimum_z',positive=True)
        if calibration_role is not None and calibration_role not in features:raise ValueError('calibration role must be an observed feature')
        self.calibration_role=calibration_role
        self.params=dict(features=self.features,targets=self.targets,degree=degree,ridge_alpha=self.ridge,window_s=self.window,minimum_z=self.minimum)
        self.params.update(feature_order=fo,target_order=to)
        if calibration_role is not None:self.params['calibration_role']=calibration_role
        self.envelope_roles=tuple('context_'+str(i) for i in range(len(features)))

    def _inputs(self,batch):
        specs={**self.features,**self.targets};c,v=self._columns(batch,{k:s['unit'] for k,s in specs.items()})
        result={}
        for key,s in specs.items():
            a=c[key]
            if s['log'] or s['unit'] in ('K','W','1/s'):v &= a>0
            with np.errstate(all='ignore'):result[key]=np.log(a) if s['log'] else a
            v &= np.isfinite(result[key])
        return np.column_stack([result[k] for k in self.features]),np.column_stack([result[k] for k in self.targets]),v

    def _raw(self,batch):
        x,y,valid=self._inputs(batch);input_valid=valid.copy();outside=np.zeros(len(valid),bool)
        metrics={**{'context_'+str(i):x[:,i] for i in range(x.shape[1])},
            'response_magnitude':np.maximum(np.linalg.norm(y,axis=1),1e-12)}
        residual=np.zeros_like(y);expected=np.zeros_like(y)
        if self.reference is not None and 'conditional_model' in self.reference:
            m=self.reference['conditional_model']
            with np.errstate(all='ignore'):expected=design((x-m['center'])/m['scale'],self.degree)@np.asarray(m['coefficients'])+m['residual_center']
            residual=(y-expected)/m['residual_scale']
            for i,bounds in enumerate(self.reference['envelope'].values()):outside |= (x[:,i]<bounds[0])|(x[:,i]>bounds[1])
            valid &= ~outside
        valid &= np.isfinite(residual).all(axis=1)
        mean=residual.copy();accepted=valid.copy();start=0
        if self.window:
            cumulative=np.zeros((len(y)+1,y.shape[1]))
            for i in range(len(y)):
                if not valid[i]:start=i+1;accepted[i]=False;continue
                if self._break(batch,i,valid):start=i;cumulative[i]=0
                cumulative[i+1]=cumulative[i]+residual[i]
                j=max(start,int(np.searchsorted(batch.time_s,batch.time_s[i]-self.window)))
                if batch.time_s[i]-batch.time_s[start]<self.window:accepted[i]=False
                mean[i]=(cumulative[i+1]-cumulative[j])/(i-j+1)
        for i,k in enumerate(self.targets):
            metrics['observed_'+k]=y[:,i];metrics['expected_'+k]=expected[:,i]
            metrics['residual_'+k]=residual[:,i];metrics['mean_residual_'+k]=mean[:,i]
        metrics,accepted,reasons=finish(metrics,accepted)
        reasons[input_valid&outside]='outside_normal_context_envelope'
        reasons[valid&~accepted]='causal_residual_mean_warmup'
        return metrics,accepted,reasons

    def fit(self,batch,*,minimum_samples=20):
        # Fit before any residual-window warmup; only caller-selected normal rows.
        self.reference=None
        try:
            if isinstance(minimum_samples,bool) or not isinstance(minimum_samples,int) or minimum_samples<2:raise ValueError('minimum_samples integer>=2 required')
            basis=batch.metadata.get('signal_basis_id')
            if basis is not None and (not isinstance(basis,str) or not basis.strip()):raise ValueError('valid input basis identifier required')
            x,y,v=self._inputs(batch)
            if v.sum()<minimum_samples:raise ValueError('insufficient normal samples')
            center=x[v].mean(axis=0);scale=np.maximum(x[v].std(axis=0),1e-8)
            a=design((x[v]-center)/scale,self.degree);penalty=np.eye(a.shape[1])*self.ridge;penalty[0,0]=0
            coef=np.linalg.solve(a.T@a/len(a)+penalty,a.T@y[v]/len(a));res=y[v]-a@coef
            bias=np.median(res,axis=0);sigma=np.maximum(1.4826*np.median(abs(res-bias),axis=0),[s['scale_floor'] for s in self.targets.values()])
            if not all(np.isfinite(value).all() for value in (center,scale,coef,bias,sigma)):
                raise ValueError('unrepresentable normal regression moments')
            model=dict(center=center.tolist(),scale=scale.tolist(),coefficients=coef.tolist(),residual_center=bias.tolist(),residual_scale=sigma.tolist(),
                feature_order=list(self.features),target_order=list(self.targets))
            # Base reference establishes identity/configuration. No fitted residual
            # model is needed during this call, and window0 avoids artificial loss.
            window=self.window;self.window=0
            try:super().fit(batch,minimum_samples=minimum_samples)
            finally:self.window=window
            # Signature includes declared params, which retain the original window.
            envelope={}
            for i,key in enumerate(self.envelope_roles):
                lo,hi=float(x[v,i].min()),float(x[v,i].max());padding=max(.1*(hi-lo),1e-8)
                envelope[key]=[lo-padding,hi+padding]
            self.reference.update(conditional_model=model,envelope=envelope,
                signal_basis_id=batch.metadata.get('signal_basis_id'))
        except Exception:
            self.reference=None
            raise
        return self

    def _score(self,m):
        responses=[]
        for key,s in self.targets.items():
            z=m['mean_residual_'+key]
            responses.append(abs(z) if s['direction']==0 else np.maximum(s['direction']*z,0))
        raw=np.max(np.column_stack(responses),axis=1);m['uncalibrated_residual_score']=raw
        cal=self.reference.get('residual_calibration',{})
        if self.calibration_role is not None and cal.get('groups'):
            context=m['context_'+str(list(self.features).index(self.calibration_role))];cut=np.full(len(raw),np.nan)
            for group in cal['groups']:cut[context==group['context']]=group['threshold']
            return raw/cut
        return raw/cal.get('threshold',self.minimum)

    def calibrate(self,batch,*,quantile=.999):
        if self.reference is None or batch.fingerprint==self.reference['training_fingerprint']:raise ValueError('separate calibration required')
        q=number(quantile,'quantile',positive=True)
        if q>=1:raise ValueError('quantile below1 required')
        old=deepcopy(self.reference)
        try:
            self.reference.pop('residual_calibration',None);r=self.score(batch)
            if r.valid.sum()<10:raise ValueError('insufficient in-domain normal calibration')
            cut=max(self.minimum,float(np.nextafter(np.quantile(r.metrics['uncalibrated_residual_score'][r.valid],q),np.inf)))
            self.reference['residual_calibration']=dict(threshold=cut,quantile=q,fingerprint=batch.fingerprint,accepted_samples=int(r.valid.sum()))
            if self.calibration_role is not None:
                context=r.metrics['context_'+str(list(self.features).index(self.calibration_role))];groups=[]
                for value in np.unique(context[r.valid]):
                    ix=r.valid&(context==value)
                    if ix.sum()<10:raise ValueError('insufficient normal calibration context')
                    threshold=max(self.minimum,float(np.nextafter(np.quantile(r.metrics['uncalibrated_residual_score'][ix],q),np.inf)))
                    groups.append(dict(context=float(value),threshold=threshold,accepted_samples=int(ix.sum())))
                self.reference['residual_calibration']['groups']=groups
        except Exception:self.reference=old;raise
        return self

    def set_reference(self,reference):
        m=reference.get('conditional_model');n=len(self.features);p=1+n+(n*(n+1)//2 if self.degree==2 else 0);d=len(self.targets)
        if not isinstance(m,dict):raise ValueError('conditional model required')
        if m.get('feature_order')!=list(self.features) or m.get('target_order')!=list(self.targets):raise ValueError('conditional model column order mismatch')
        for key,shape in [('center',(n,)),('scale',(n,)),('coefficients',(p,d)),('residual_center',(d,)),('residual_scale',(d,))]:
            a=np.asarray(m.get(key),float)
            if a.shape!=shape or not np.isfinite(a).all() or (key in ('scale','residual_scale') and (a<=0).any()):raise ValueError('invalid conditional '+key)
        c=reference.get('residual_calibration')
        if c:
            number(c.get('threshold'),'threshold',positive=True)
            q=number(c.get('quantile'),'quantile',positive=True)
            if q>=1:raise ValueError('invalid calibration quantile')
            if not c.get('fingerprint') or c['fingerprint']==reference.get('training_fingerprint'):raise ValueError('invalid calibration provenance')
            if self.calibration_role is not None:
                gs=c.get('groups')
                if not isinstance(gs,list) or not gs or len({g.get('context') for g in gs})!=len(gs):raise ValueError('invalid calibration groups')
                for g in gs:number(g.get('context'),'context');number(g.get('threshold'),'group threshold',positive=True)
        return super().set_reference(reference)

    def score(self,batch):
        if self.reference and self.reference.get('signal_basis_id') is not None and batch.metadata.get('signal_basis_id')!=self.reference['signal_basis_id']:
            raise ValueError('conditional input basis differs')
        return super().score(batch)
