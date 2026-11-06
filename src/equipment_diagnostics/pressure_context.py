"""Load-conditioned filter pressure excess; no unmeasured airflow or RUL claim."""
from copy import deepcopy
import numpy as np
from .base import Diagnostic,finish,number
from .chiller_staged import design


class LoadConditionedPressureDiagnostic(Diagnostic):
    kind='load_conditioned_filter_pressure'
    reference_metric='pressure_drop_pa'
    envelope_roles=('shaft_power_w','engine_speed_hz')
    def __init__(self,channels,*,conditioned=True,growth_limit_fraction=.25,
                 minimum_excess_pa=10.,ridge_alpha=.001,**kwargs):
        super().__init__(channels,**kwargs)
        if not isinstance(conditioned,bool): raise ValueError('conditioned must be boolean')
        self.conditioned=conditioned
        self.limit=number(growth_limit_fraction,'growth_limit_fraction',positive=True)
        self.floor=number(minimum_excess_pa,'minimum_excess_pa',positive=True)
        self.ridge=number(ridge_alpha,'ridge_alpha',positive=True)
        self.params=dict(conditioned=conditioned,growth_limit_fraction=self.limit,minimum_excess_pa=self.floor,ridge_alpha=self.ridge)

    def _raw(self,batch):
        c,v=self._columns(batch,dict(pressure_drop='Pa',shaft_power='W',engine_speed='1/s'))
        return finish(dict(pressure_drop_pa=c['pressure_drop'],shaft_power_w=c['shaft_power'],engine_speed_hz=c['engine_speed']),v,
            physical=(c['pressure_drop']>0)&(c['shaft_power']>0)&(c['engine_speed']>0))

    @staticmethod
    def _features(metrics):
        with np.errstate(all='ignore'):
            return np.column_stack((np.log(metrics['shaft_power_w']),np.log(metrics['engine_speed_hz'])))

    def fit(self,normal_batch,*,minimum_samples=20):
        super().fit(normal_batch,minimum_samples=minimum_samples)
        if self.conditioned:
            try:
                metrics,valid,_=self._raw(normal_batch)
                x=self._features(metrics)[valid];y=np.log(metrics['pressure_drop_pa'][valid])
                center=x.mean(axis=0);scale=np.maximum(x.std(axis=0),1e-8)
                a=design((x-center)/scale,2);penalty=np.eye(a.shape[1])*self.ridge;penalty[0,0]=0
                coef=np.linalg.solve(a.T@a/len(a)+penalty,a.T@y/len(a))
                self.reference['pressure_model']=dict(center=center.tolist(),scale=scale.tolist(),coefficients=coef.tolist())
            except Exception:
                self.reference=None
                raise
        return self

    def _score(self,metrics):
        if self.conditioned:
            r=self.reference['pressure_model'];x=self._features(metrics)
            with np.errstate(all='ignore'):expected=np.exp(design((x-r['center'])/r['scale'],2)@r['coefficients'])
        else:expected=np.full(len(metrics['pressure_drop_pa']),self.reference['center'])
        metrics['expected_pressure_drop_pa']=expected
        with np.errstate(all='ignore'):raw=np.maximum(metrics['pressure_drop_pa']-expected,0)/np.maximum(self.floor,self.limit*expected)
        return raw/self.reference.get('score_calibration',{}).get('threshold',1.)

    def calibrate(self,normal_batch,*,quantile=.99):
        q=number(quantile,'quantile',positive=True)
        if q>=1 or self.reference is None:raise ValueError('fit reference and 0<quantile<1 required')
        if normal_batch.fingerprint==self.reference['training_fingerprint']:raise ValueError('separate normal calibration required')
        old=deepcopy(self.reference)
        try:
            self.reference.pop('score_calibration',None);r=self.score(normal_batch)
            if r.valid.sum()<20:raise ValueError('insufficient normal calibration')
            self.reference['score_calibration']=dict(threshold=max(1.,float(np.nextafter(np.quantile(r.scores[r.valid],q),np.inf))),
                quantile=q,fingerprint=normal_batch.fingerprint,accepted_samples=int(r.valid.sum()))
        except Exception:
            self.reference=old
            raise
        return self

    def set_reference(self,reference):
        if self.conditioned:
            r=reference.get('pressure_model')
            if not isinstance(r,dict):raise ValueError('pressure model required')
            for k,shape in [('center',(2,)),('scale',(2,)),('coefficients',(6,))]:
                a=np.asarray(r.get(k),float)
                if a.shape!=shape or not np.isfinite(a).all() or (k=='scale' and (a<=0).any()):raise ValueError('invalid pressure '+k)
        c=reference.get('score_calibration')
        if c is not None:
            if not isinstance(c,dict):raise ValueError('invalid calibration')
            number(c.get('threshold'),'threshold',positive=True)
            q=number(c.get('quantile'),'quantile',positive=True)
            if q>=1 or not c.get('fingerprint') or c['fingerprint']==reference.get('training_fingerprint'):raise ValueError('invalid calibration provenance')
        return super().set_reference(reference)
