"""Causal residual growth relative to earlier observations; never learns evaluation baselines."""
from copy import deepcopy
import numpy as np
from .base import Diagnostic,finish,number


class WindowChangeDiagnostic(Diagnostic):
    """Compare causal residual means with earlier observed windows.

    The signal is a signed dimensionless upstream residual whose basis must
    be preserved. Window/lag values use seconds. Constant offsets cancel;
    invalid observations and episode/context changes reset history. Faster
    engine-filter candidates raised false alarms and were not adopted.
    """
    kind='window_residual_change'
    reference_metric='positive_signal_magnitude'
    requires_full_history=True
    score_semantics='causal_residual_increase_to_normal_calibrated_limit'

    def __init__(self,channels,*,mean_window_s=60.,lags_s=(60.,300.,900.),minimum_change=np.log1p(.05),**kwargs):
        super().__init__(channels,**kwargs)
        self.window=number(mean_window_s,'mean_window_s',positive=True)
        self.lags=tuple(number(v,'lag_s',positive=True) for v in lags_s)
        if not self.lags or list(self.lags)!=sorted(set(self.lags)):raise ValueError('unique increasing lags required')
        self.minimum=number(minimum_change,'minimum_change',positive=True)
        self.params=dict(mean_window_s=self.window,lags_s=list(self.lags),minimum_change=self.minimum)

    def _raw(self,batch):
        if self.reference and 'signal_basis_id' in self.reference and self.reference.get('signal_basis_id')!=batch.metadata.get('signal_basis_id'):
            raise ValueError('residual basis mismatch')
        c,v=self._columns(batch,dict(signal='1'));x=c['signal'];n=len(x);mean=np.zeros(n);available=np.zeros(n,bool)
        start=0;total=np.zeros(n+1)
        for i in range(n):
            if not v[i]:start=i+1;continue
            if self._break(batch,i,v):start=i;total[i]=0
            total[i+1]=total[i]+x[i]
            j=max(start,int(np.searchsorted(batch.time_s,batch.time_s[i]-self.window)))
            mean[i]=(total[i+1]-total[j])/(i-j+1)
            available[i]=batch.time_s[i]-batch.time_s[start]>=self.window
        changes=[];mask=[];start=0
        for lag in self.lags:
            delta=np.zeros(n);good=np.zeros(n,bool);start=0
            for i in range(n):
                if not v[i]:start=i+1;continue
                if self._break(batch,i,v):start=i
                j=int(np.searchsorted(batch.time_s,batch.time_s[i]-lag,side='right'))-1
                if j>=start and available[i] and available[j] and batch.time_s[i]-lag-batch.time_s[j]<=self.max_gap_s:
                    delta[i]=mean[i]-mean[j];good[i]=True
            changes.append(delta);mask.append(good)
        accepted=v&np.logical_or.reduce(mask)
        m=dict(positive_signal_magnitude=np.maximum(abs(x),1e-12),signal=x)
        for i,(d,g) in enumerate(zip(changes,mask)):m['change_'+str(i)]=d;m['available_'+str(i)]=g.astype(float)
        return finish(m,accepted)

    def _score(self,m):
        cuts=self.reference.get('change_scales',[self.minimum]*len(self.lags));values=[]
        for i,cut in enumerate(cuts):values.append(np.where(m['available_'+str(i)]>0,np.maximum(m['change_'+str(i)],0)/cut,0))
        raw=np.max(np.column_stack(values),axis=1);m['joint_change_score']=raw
        return raw/self.reference.get('change_calibration',{}).get('threshold',1.)

    def fit(self,batch,*,minimum_samples=20):
        super().fit(batch,minimum_samples=minimum_samples)
        try:
            m,v,_=self._raw(batch);scales=[]
            for i in range(len(self.lags)):
                a=m['change_'+str(i)][v&(m['available_'+str(i)]>0)]
                # Long-lag evidence may be unavailable in fragmented normal training.
                noise=0. if len(a)<10 else float(3*1.4826*np.median(abs(a-np.median(a))))
                scales.append(max(self.minimum,noise))
            if not np.isfinite(scales).all():raise ValueError('unrepresentable normal change scales')
            self.reference.update(change_scales=scales,signal_basis_id=batch.metadata.get('signal_basis_id'))
        except Exception:self.reference=None;raise
        return self

    def calibrate(self,batch,*,quantile=.9999):
        if self.reference is None or batch.fingerprint==self.reference['training_fingerprint']:raise ValueError('separate normal calibration required')
        q=number(quantile,'quantile',positive=True)
        if q>=1:raise ValueError('quantile below1 required')
        old=deepcopy(self.reference)
        try:
            self.reference.pop('change_calibration',None);r=self.score(batch)
            if r.valid.sum()<10:raise ValueError('insufficient normal change calibration')
            cut=max(1.,float(np.nextafter(np.quantile(r.metrics['joint_change_score'][r.valid],q),np.inf)))
            self.reference['change_calibration']=dict(threshold=cut,quantile=q,fingerprint=batch.fingerprint,accepted_samples=int(r.valid.sum()))
        except Exception:self.reference=old;raise
        return self

    def set_reference(self,reference):
        a=np.asarray(reference.get('change_scales'),float)
        if a.shape!=(len(self.lags),) or not np.isfinite(a).all() or (a<=0).any():raise ValueError('invalid change scales')
        c=reference.get('change_calibration')
        if c is not None:
            number(c.get('threshold'),'threshold',positive=True)
            if not c.get('fingerprint') or c['fingerprint']==reference.get('training_fingerprint'):raise ValueError('invalid change calibration')
        return super().set_reference(reference)
