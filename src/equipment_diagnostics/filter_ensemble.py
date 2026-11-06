"""Convex risk aggregation; weights selected on training-only out-of-fold data."""
from copy import deepcopy
import numpy as np
from .base import Diagnostic,number
from .filter_classifier import FilterRiskClassifier
from .boosted_filter import FilterBoostedRiskClassifier


class FilterRiskEnsemble(FilterRiskClassifier):
    kind='filter_risk_ensemble'

    def __init__(self,channels,*,booster_weight=.75,aggregation='arithmetic',**kwargs):
        super().__init__(channels,**kwargs)
        if self.calibration_scope!='pooled' or self.feature_set!='basic':raise ValueError('ensemble uses pooled basic features')
        self.weight=number(booster_weight,'booster_weight',positive=True)
        if self.weight>=1 or aggregation not in ('arithmetic','geometric'):raise ValueError('invalid aggregation')
        self.aggregation=aggregation;self.params.update(booster_weight=self.weight,aggregation=aggregation)
        self.components=None

    def fit(self,batch,remaining_life_s,*,minimum_samples=20):
        self.reference=None;y=np.asarray(remaining_life_s,float)
        if y.shape!=batch.time_s.shape or not np.isfinite(y).all() or (y<0).any():raise ValueError('invalid remaining life')
        Diagnostic.fit(self,batch,minimum_samples=minimum_samples)
        try:
            common=dict(horizon_s=self.horizon,window_s=self.window,ridge_alpha=self.ridge,max_gap_s=self.max_gap_s,allowed_modes=self.allowed_modes)
            et=FilterRiskClassifier(self.channels,**common,**self.forest_params).fit(batch,y,minimum_samples=minimum_samples)
            hb=FilterBoostedRiskClassifier(self.channels,**common).fit(batch,y,minimum_samples=minimum_samples)
            self.components=[et,hb]
            self.reference['components']=[dict(kind=m.kind,parameters=m.params,reference=deepcopy(m.reference)) for m in self.components]
            self.reference['risk_forest']=dict(feature_count=et.reference['risk_forest']['feature_count'],training_only=True,
                training_support=deepcopy(et.reference['risk_forest']['training_support']))
        except Exception:self.reference=None;self.components=None;raise
        return self

    def _vote_statistics(self,x):
        for model,descriptor in zip(self.components,self.reference['components']):
            if model.reference!=descriptor['reference'] or model.signature!=descriptor['reference']['signature']:
                raise ValueError('component changed; reload ensemble reference')
        a,b=[m._votes(x) for m in self.components];w=self.weight
        mean=(1-w)*a+w*b if self.aggregation=='arithmetic' else np.maximum(a,1e-12)**(1-w)*np.maximum(b,1e-12)**w
        disagreement=np.sqrt((1-w)*(a-mean)**2+w*(b-mean)**2)
        return mean,disagreement

    def _score(self,metrics):
        score=super()._score(metrics);metrics['component_disagreement']=metrics.pop('tree_vote_std')
        return score

    def set_reference(self,reference):
        components=reference.get('components')
        if not isinstance(components,list) or [x.get('kind') for x in components]!=['filter_risk_classifier','filter_boosted_risk']:raise ValueError('invalid components')
        models=[]
        for descriptor,cls in zip(components,[FilterRiskClassifier,FilterBoostedRiskClassifier]):
            model=cls(self.channels,**descriptor['parameters'],max_gap_s=self.max_gap_s,allowed_modes=self.allowed_modes).set_reference(descriptor['reference'])
            for key in ['asset_id','origin','clock_id','training_fingerprint']:
                if model.reference.get(key)!=reference.get(key):raise ValueError('component provenance mismatch')
            if model.reference.get('risk_calibration') is not None:raise ValueError('components must be uncalibrated')
            models.append(model)
        expected=models[0].reference['risk_forest'];support=reference.get('risk_forest',{})
        if support.get('feature_count')!=expected['feature_count'] or support.get('training_support')!=expected['training_support']:raise ValueError('inconsistent ensemble support')
        cal=reference.get('risk_calibration')
        if cal:
            number(cal.get('threshold'),'threshold',positive=True)
            if not cal.get('fingerprint') or cal['fingerprint']==reference.get('training_fingerprint'):raise ValueError('separate calibration required')
        Diagnostic.set_reference(self,reference);self.components=models
        return self
