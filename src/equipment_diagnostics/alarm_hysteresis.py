"""Causal alarm confirmation and hysteresis; no inferred maintenance labels."""
import numpy as np
from .base import Diagnostic,finish,number
from .contracts import DiagnosticResult,frozen_array


class HysteresisAlarmDiagnostic(Diagnostic):
    kind='alarm_hysteresis'
    requires_full_history=True
    score_semantics='instantaneous_on_threshold_ratio_alarm_can_be_held_by_hysteresis'

    def __init__(self,channels,*,on_threshold=1.,confirmation_s=2.,release_ratio=.25,release_s=5.,**kwargs):
        if 'persistence_s' in kwargs:raise ValueError('use confirmation_s')
        super().__init__(channels,persistence_s=confirmation_s,**kwargs)
        self.on=number(on_threshold,'on_threshold',positive=True);self.off=number(release_ratio,'release_ratio',positive=True)
        self.release=number(release_s,'release_s',nonnegative=True)
        if self.off>=1:raise ValueError('release_ratio must be below one')
        self.params=dict(on_threshold=self.on,confirmation_s=self.persistence_s,release_ratio=self.off,release_s=self.release)

    def _raw(self,batch):
        c,v=self._columns(batch,dict(indication_score='1'));s=c['indication_score']
        return finish(dict(indication_score=s),v,physical=s>=0)

    def _score(self,metrics):return metrics['indication_score']/self.on

    def score(self,batch):
        r=super().score(batch);active=False;since=None;release_since=None;alarms=np.zeros(len(r.scores),bool);states=[]
        for i,score in enumerate(r.scores):
            if self._break(batch,i,r.valid):active=False;since=None;release_since=None
            if not r.valid[i]:states.append('UNKNOWN');continue
            if active:
                if score<self.off:
                    if release_since is None:release_since=float(batch.time_s[i])
                    if batch.time_s[i]-release_since>=self.release:active=False;release_since=None;since=None
                else:release_since=None
            elif score>1:
                if since is None:since=float(batch.time_s[i])
                if batch.time_s[i]-since>=self.persistence_s:active=True
            else:since=None
            alarms[i]=active;states.append('ALARM' if active else 'PENDING' if since is not None else 'NORMAL')
        metadata={**r.metadata,'alarm_policy':'confirmation_then_hysteresis','policy_parameters':self.params,
            'interpretation':'Alarm holding/release policy, not a statement that physical clogging recovered.'}
        return DiagnosticResult(self.kind,r.time_s,r.scores,r.valid,frozen_array(alarms),tuple(states),r.reasons,r.metrics,metadata)
