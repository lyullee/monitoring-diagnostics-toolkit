"""Causal EWMA/CUSUM evidence on an upstream diagnostic's dimensionless score."""
import numpy as np
from .base import Diagnostic,finish,number


class TemporalEvidenceDiagnostic(Diagnostic):
    kind='temporal_evidence'
    reference_metric='positive_base_score'
    requires_full_history=True # exact CUSUM replay requires the episode's history
    score_semantics='accumulated_score_seconds_to_normal_calibrated_limit'

    def __init__(self,channels,*,time_constant_s=20.,drift_quantile=.8,minimum_evidence_s=10.,**kwargs):
        super().__init__(channels,**kwargs)
        self.tau=number(time_constant_s,'time_constant_s',positive=True)
        self.quantile=number(drift_quantile,'drift_quantile',positive=True)
        if self.quantile>=1:raise ValueError('invalid drift_quantile')
        self.minimum=number(minimum_evidence_s,'minimum_evidence_s',positive=True)
        self.params=dict(time_constant_s=self.tau,drift_quantile=self.quantile,minimum_evidence_s=self.minimum)

    def _raw(self,batch):
        c,v=self._columns(batch,dict(indication_score='1',heat_demand='W'))
        s,load=c['indication_score'],c['heat_demand']
        good=v&(s>=0)&(load>0)
        smooth=np.zeros(len(s));reset=np.zeros(len(s),bool)
        for i in range(len(s)):
            reset[i]=self._break(batch,i,good) or (i>0 and load[i]!=load[i-1])
            if not good[i]:continue
            if reset[i]:smooth[i]=s[i]
            else:
                alpha=-np.expm1(-(batch.time_s[i]-batch.time_s[i-1])/self.tau)
                smooth[i]=smooth[i-1]+alpha*(s[i]-smooth[i-1])
        increments=np.r_[0.,np.diff(batch.time_s)];increments[reset]=0.
        return finish(dict(positive_base_score=np.maximum(s,1e-12),base_score=s,heat_demand_w=load,
            smoothed_score=smooth,reset=reset.astype(float),elapsed_increment_s=increments),v,physical=(s>=0)&(load>0))

    def fit(self,batch,*,minimum_samples=20):
        super().fit(batch,minimum_samples=minimum_samples)
        try:
            m,v,_=self._raw(batch);groups=[]
            for load in np.unique(m['heat_demand_w'][v]):
                mask=v&(m['heat_demand_w']==load)
                if mask.sum()<minimum_samples:raise ValueError('insufficient normal group')
                drift=max(1e-6,float(np.quantile(m['smoothed_score'][mask],self.quantile)))
                groups.append(dict(load_w=float(load),drift=drift,accepted_samples=int(mask.sum())))
            self.reference['evidence_groups']=groups
        except Exception:self.reference=None;raise
        return self

    def _score(self,metrics):
        groups=self.reference['evidence_groups'];load=metrics['heat_demand_w'];smooth=metrics['smoothed_score']
        # _score receives only arrays, so exact elapsed increments are carried
        # explicitly by _raw; no assumed uniform sampling or future observations.
        drift=np.full(len(load),np.nan);cut=np.full(len(load),np.nan)
        calibration=self.reference.get('evidence_calibration',{}).get('groups',[])
        for group in groups:
            mask=np.isclose(load,group['load_w'],rtol=0,atol=1e-6);drift[mask]=group['drift'];cut[mask]=self.minimum
            for cal in calibration:
                if cal['load_w']==group['load_w']:cut[mask]=cal['threshold_score_seconds']
        values=np.full(len(load),np.nan);state=0.
        for i in range(len(load)):
            if metrics['reset'][i] or not np.isfinite(drift[i]):state=0.
            if not np.isfinite(drift[i]):continue
            state=max(0.,state+metrics['elapsed_increment_s'][i]*(smooth[i]-drift[i]));values[i]=state
        metrics['cusum_score_seconds']=values;metrics['normal_drift_score']=drift
        return values/cut

    def calibrate(self,batch,*,minimum_samples=10):
        if self.reference is None:raise ValueError('fit before calibration')
        if isinstance(minimum_samples,bool) or not isinstance(minimum_samples,int) or minimum_samples<2:raise ValueError('invalid minimum_samples')
        if batch.fingerprint==self.reference['training_fingerprint']:raise ValueError('separate calibration required')
        previous=self.reference.pop('evidence_calibration',None)
        try:
            r=self.score(batch);groups=[]
            for group in self.reference['evidence_groups']:
                mask=r.valid&(r.metrics['heat_demand_w']==group['load_w'])
                if mask.sum()<minimum_samples:raise ValueError('insufficient normal calibration group')
                cut=max(self.minimum,float(np.nextafter(np.max(r.metrics['cusum_score_seconds'][mask]),np.inf)))
                groups.append(dict(load_w=group['load_w'],threshold_score_seconds=cut,accepted_samples=int(mask.sum())))
            self.reference['evidence_calibration']=dict(groups=groups,fingerprint=batch.fingerprint,rule='max_observed_normal_calibration_evidence_with_floor')
        except Exception:
            if previous is not None:self.reference['evidence_calibration']=previous
            raise
        return self

    def set_reference(self,reference):
        groups=reference.get('evidence_groups')
        if not isinstance(groups,list) or not groups:raise ValueError('missing evidence groups')
        loads=[]
        for g in groups:
            loads.append(number(g.get('load_w'),'load_w',positive=True));number(g.get('drift'),'drift',positive=True)
        if len(set(loads))!=len(loads):raise ValueError('duplicate load')
        cal=reference.get('evidence_calibration')
        if cal:
            if not isinstance(cal,dict):raise ValueError('invalid calibration')
            if not cal.get('fingerprint') or cal['fingerprint']==reference.get('training_fingerprint'):raise ValueError('separate calibration required')
            if sorted(g['load_w'] for g in cal.get('groups',[]))!=sorted(loads):raise ValueError('incomplete calibration')
            for g in cal['groups']:number(g.get('threshold_score_seconds'),'threshold',positive=True)
        return super().set_reference(reference)
