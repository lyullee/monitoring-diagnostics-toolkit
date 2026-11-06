"""Wet/frosting coil air-side restriction and moist-air heat balance, not dry UA."""
from copy import deepcopy
import numpy as np
from .base import Diagnostic,finish,number
from .physical_inputs import moist_air_exchange


class WetCoilAirsideDiagnostic(Diagnostic):
    kind='wet_coil_airside'
    reference_metric='normalized_pressure_drop_pa'
    envelope_roles=('air_volume_flow_m3_s',)
    references=('10.17632/s6d23g2m2w.1',)
    def __init__(self,channels,*,reference_volume_flow_m3_s,reference_density_kg_m3=1.2,
                 flow_exponent=2.,restriction_growth_limit_fraction=.25,**kwargs):
        super().__init__(channels,**kwargs)
        self.qref=number(reference_volume_flow_m3_s,'reference_volume_flow_m3_s',positive=True)
        self.rho=number(reference_density_kg_m3,'reference_density_kg_m3',positive=True)
        self.exponent=number(flow_exponent,'flow_exponent',nonnegative=True)
        self.limit=number(restriction_growth_limit_fraction,'restriction_growth_limit_fraction',positive=True)
        self.params=dict(reference_volume_flow_m3_s=self.qref,reference_density_kg_m3=self.rho,
            flow_exponent=self.exponent,restriction_growth_limit_fraction=self.limit)

    def _raw(self,batch):
        c,good=self._columns(batch,dict(pressure_drop='Pa',volume_flow='m3/s',dry_air_flow='kg/s',
            inlet_temperature='K',outlet_temperature='K',inlet_humidity='1',outlet_humidity='1'))
        dp=c['pressure_drop'];q=c['volume_flow'];m=c['dry_air_flow']
        wi=c['inlet_humidity'];wo=c['outlet_humidity']
        r=moist_air_exchange(m,c['inlet_temperature'],c['outlet_temperature'],wi,wo)
        with np.errstate(all='ignore'):
            rho=m*(1+wo)/q
            normalized=dp*(self.qref/q)**self.exponent*(self.rho/rho if self.exponent else 1.)
            normalized=np.where((dp>0)&(normalized==0),np.nan,normalized)
        return finish(dict(normalized_pressure_drop_pa=normalized,measured_pressure_drop_pa=dp,
            air_volume_flow_m3_s=q,moist_air_density_kg_m3=rho,air_side_heat_w=r['air_side_heat_w'],
            moisture_removal_kg_s=r['moisture_removal_kg_s']),good,
            physical=r['valid']&(dp>=0)&(q>0)&(rho>0))

    def _score(self,metrics):
        raw=np.maximum(metrics[self.reference_metric]/self.reference['center']-1,0)/self.limit
        return raw/self.reference.get('score_calibration',{}).get('threshold',1.)

    def calibrate(self,normal_batch,*,quantile=.99):
        q=number(quantile,'quantile',positive=True)
        if q>=1 or self.reference is None: raise ValueError('fit reference and 0<quantile<1 required')
        if normal_batch.fingerprint==self.reference['training_fingerprint']: raise ValueError('separate normal calibration required')
        old=deepcopy(self.reference)
        try:
            self.reference.pop('score_calibration',None)
            r=self.score(normal_batch)
            if r.valid.sum()<10: raise ValueError('insufficient in-domain calibration samples')
            threshold=max(1.,float(np.nextafter(np.quantile(r.scores[r.valid],q),np.inf)))
            self.reference['score_calibration']=dict(threshold=threshold,quantile=q,
                fingerprint=normal_batch.fingerprint,accepted_samples=int(r.valid.sum()))
        except Exception:
            self.reference=old
            raise
        return self

    def set_reference(self,reference):
        c=reference.get('score_calibration')
        if c is not None:
            if not isinstance(c,dict): raise ValueError('invalid wet-coil calibration')
            number(c.get('threshold'),'threshold',positive=True)
            q=number(c.get('quantile'),'quantile',positive=True)
            if q>=1 or not c.get('fingerprint') or c['fingerprint']==reference.get('training_fingerprint'):
                raise ValueError('invalid wet-coil calibration provenance')
        return super().set_reference(reference)
