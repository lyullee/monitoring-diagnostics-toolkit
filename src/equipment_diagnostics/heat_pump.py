"""Measured refrigerant-side heat-pump screening, distinct from water-side chillers."""
import numpy as np
from .base import Diagnostic,finish,number


def heating_temperature_metrics(q,p,te,tc,tl,td):
    """SI heating indicators without assuming load, clock or shaft frequency.

    Inputs may contain invalid measurements; downstream callers retain their
    physical validity masks. This function does not classify a fault.
    """
    with np.errstate(all='ignore'):
        cop=q/p;carnot=tc/(tc-te)
        return dict(heating_cop=cop,isothermal_heating_carnot_cop=carnot,
            condenser_duty_w=q,electric_power_w=p,log_carnot_efficiency_proxy=np.log(cop/carnot),
            subcooling_k=tc-tl,discharge_superheat_k=td-tc)


def evaporator_conductance_proxy(condenser_duty_w,electric_power_w,evaporating_temperature_k,
                                 source_inlet_temperature_k):
    """Approximate (Qcond-W)/(Tsource,in-Tevap), W/K; not a measured UA.

    Neglects compressor/environmental losses and thermal storage, and uses the
    SOURCE INLET instead of unknown LMTD. Caller must identify measured versus
    assumed source temperatures. Cannot isolate flow reduction from fouling.
    """
    arrays=np.broadcast_arrays(*[np.asarray(a,float) for a in (condenser_duty_w,electric_power_w,
        evaporating_temperature_k,source_inlet_temperature_k)])
    q,p,te,ts=arrays
    with np.errstate(all='ignore'):
        duty=q-p;gap=ts-te;proxy=duty/gap
    valid=np.logical_and.reduce([np.isfinite(a) for a in arrays])&(q>p)&(p>0)&(te>0)&(ts>te)&np.isfinite(proxy)&(proxy>0)
    return dict(conductance_proxy_w_k=np.where(valid,proxy,np.nan),evaporator_duty_proxy_w=np.where(valid,duty,np.nan),valid=valid)

class HeatPumpPerformanceDiagnostic(Diagnostic):
    """Monitor refrigerant-side heating behavior under observed heat demand.

    Input condenser duty/power/demand [W], four temperatures [K], refrigerant
    mass flow [kg/s] and shaft speed [1/s]. Output heating COP, temperature
    differences, mass/revolution and normal residuals. Normal fit and separate
    calibration are caller-selected; this is not a flow-fault classifier.
    The latest weak-fault response branch is a separate Python model profile.
    """
    kind='heat_pump_performance'
    references=('10.5281/zenodo.5155136',)
    reference_metric='heating_cop'
    envelope_roles=('heat_demand_w',)
    KEYS=('log_carnot_efficiency_proxy','subcooling_k','discharge_superheat_k','log_mass_per_revolution')

    @property
    def score_semantics(self):
        return 'ratio_to_normal_calibrated_threshold' if self.reference and self.reference.get('score_calibration') else 'standardized_normal_reference_residual'

    def __init__(self,channels,*,reference_mode='constant',ridge_alpha=.001,
                 log_residual_floor=.02,temperature_residual_floor_k=.2,feature_set='cycle',
                 calibration_scope='pooled',evaporator_directional=False,**kwargs):
        super().__init__(channels,**kwargs)
        if reference_mode not in ('constant','load_conditioned'):raise ValueError('invalid heat-pump reference_mode')
        if feature_set not in ('cycle','extended'):raise ValueError('invalid heat-pump feature_set')
        self.feature_set=feature_set
        if calibration_scope not in ('pooled','load_groups','evaporator_groups'):raise ValueError('invalid calibration_scope')
        if not isinstance(evaporator_directional,bool):raise ValueError('invalid evaporator_directional')
        if (calibration_scope!='pooled' or evaporator_directional) and feature_set!='extended':raise ValueError('extended features required')
        self.calibration_scope=calibration_scope;self.evaporator_directional=evaporator_directional
        if feature_set=='extended':
            self.KEYS=(*type(self).KEYS,'evaporating_temperature_k','condensing_temperature_k',
                'log_electric_power','log_compressor_speed','log_heating_cop')
        self.mode=reference_mode;self.ridge=number(ridge_alpha,'ridge_alpha',positive=True)
        self.log_floor=number(log_residual_floor,'log_residual_floor',positive=True)
        self.temp_floor=number(temperature_residual_floor_k,'temperature_residual_floor_k',positive=True)
        self.params=dict(reference_mode=reference_mode,ridge_alpha=self.ridge,log_residual_floor=self.log_floor,
                         temperature_residual_floor_k=self.temp_floor)
        if feature_set!='cycle':self.params['feature_set']=feature_set
        if calibration_scope!='pooled':self.params['calibration_scope']=calibration_scope
        if evaporator_directional:self.params['evaporator_directional']=True

    def _raw(self,batch):
        c,v=self._columns(batch,dict(condenser_duty='W',electric_power='W',evaporating_temperature='K',
            condensing_temperature='K',liquid_line_temperature='K',discharge_temperature='K',
            refrigerant_mass_flow='kg/s',compressor_speed='1/s',heat_demand='W'))
        q,p,te,tc,tl,td,m,n,load=(c[k] for k in ('condenser_duty','electric_power','evaporating_temperature',
            'condensing_temperature','liquid_line_temperature','discharge_temperature',
            'refrigerant_mass_flow','compressor_speed','heat_demand'))
        with np.errstate(all='ignore'):
            metrics=heating_temperature_metrics(q,p,te,tc,tl,td);mass=m/n;cop=metrics['heating_cop']
            metrics.update(heat_demand_w=load,mass_per_revolution_kg=mass,log_mass_per_revolution=np.log(mass))
            if self.feature_set=='extended':
                metrics.update(evaporating_temperature_k=te,condensing_temperature_k=tc,
                    log_electric_power=np.log(p),log_compressor_speed=np.log(n),log_heating_cop=np.log(cop))
        return finish(metrics,v,physical=(q>0)&(p>0)&(te>0)&(tc>te)&(tl>0)&(td>0)&(m>0)&(n>0)&(load>0))

    def _design(self,load,model):
        if self.mode=='constant':return np.ones((len(load),1))
        return np.column_stack((np.ones(len(load)),(load-model['load_center'])/model['load_scale']))

    def fit(self,normal_batch,*,minimum_samples=20):
        super().fit(normal_batch,minimum_samples=minimum_samples)
        try:
            metrics,valid,_=self._raw(normal_batch);valid&=np.logical_and.reduce([np.isfinite(a) for a in metrics.values()])
            y=np.column_stack([metrics[k][valid] for k in self.KEYS]);load=metrics['heat_demand_w'][valid]
            if len(y)<minimum_samples:raise ValueError('insufficient heat-pump training data')
            center=float(load.mean());scale=float(load.std())
            if self.mode=='load_conditioned' and scale<1:raise ValueError('at least two normal heat-demand conditions required')
            model=dict(load_center=center,load_scale=max(scale,1.))
            a=self._design(load,model);penalty=np.eye(a.shape[1])*self.ridge;penalty[0,0]=0
            coef=np.linalg.solve(a.T@a/len(y)+penalty,a.T@y/len(y));res=y-a@coef
            bias=np.median(res,axis=0);sigma=np.maximum(1.4826*np.median(abs(res-bias),axis=0),
                [self.temp_floor if k.endswith('_k') else self.log_floor for k in self.KEYS])
            model.update(coefficients=coef.tolist(),residual_center=bias.tolist(),residual_scale=sigma.tolist(),targets=list(self.KEYS))
            self.reference['refrigerant_model']=model
        except Exception:
            self.reference=None;raise
        return self

    def set_reference(self,reference):
        m=reference.get('refrigerant_model')
        if not isinstance(m,dict) or m.get('targets')!=list(self.KEYS):raise ValueError('missing heat-pump normal model')
        size=len(self.KEYS)
        for k,shape in [('coefficients',(1 if self.mode=='constant' else 2,size)),('residual_center',(size,)),('residual_scale',(size,))]:
            a=np.asarray(m.get(k),float)
            if a.shape!=shape or not np.isfinite(a).all() or (k=='residual_scale' and (a<=0).any()):raise ValueError('invalid heat-pump '+k)
        number(m.get('load_center'),'model load_center',positive=True);number(m.get('load_scale'),'model load_scale',positive=True)
        cal=reference.get('score_calibration')
        if cal is not None:
            if not isinstance(cal,dict):raise ValueError('invalid heat-pump calibration')
            number(cal.get('threshold'),'calibration threshold',positive=True)
            q=number(cal.get('quantile'),'calibration quantile',positive=True)
            if q>=1 or not cal.get('fingerprint') or cal['fingerprint']==reference.get('training_fingerprint'):
                raise ValueError('separate calibration required')
            scales=cal.get('channel_scales')
            if self.feature_set=='extended' and (scales is None or np.asarray(scales).shape!=(size,) or
                    not np.isfinite(scales).all() or (np.asarray(scales)<1).any()):
                raise ValueError('invalid channel calibration scales')
            if self.feature_set=='cycle' and scales is not None:raise ValueError('unexpected channel scales')
            groups=cal.get('load_groups')
            if self.calibration_scope in ('load_groups','evaporator_groups'):
                if not isinstance(groups,list) or len(groups)<2:raise ValueError('missing load groups')
                loads=[]
                for group in groups:
                    loads.append(number(group.get('load_w'),'group load',positive=True))
                    number(group.get('threshold'),'group threshold',positive=True)
                    a=np.asarray(group.get('channel_scales'),float)
                    if a.shape!=(size,) or not np.isfinite(a).all() or (a<=0).any():raise ValueError('invalid group scales')
                if len(set(loads))!=len(loads):raise ValueError('duplicate load group')
            elif groups is not None:raise ValueError('unexpected load groups')
        return super().set_reference(reference)

    def calibrate(self,normal_batch,*,quantile=.99,minimum_samples=10):
        if self.reference is None:raise ValueError('fit before calibration')
        q=number(quantile,'quantile',positive=True)
        if q>=1 or isinstance(minimum_samples,bool) or not isinstance(minimum_samples,int) or minimum_samples<2:
            raise ValueError('invalid calibration parameters')
        if normal_batch.fingerprint==self.reference['training_fingerprint']:raise ValueError('calibration must differ from training')
        previous=self.reference.pop('score_calibration',None)
        try:
            r=self.score(normal_batch)
            if r.valid.sum()<minimum_samples:raise ValueError('insufficient calibration samples')
            # Optional channelwise calibration stops a drifting normal channel
            # from setting the detection limit for all other physical variables.
            if self.feature_set=='extended':
                scales=[max(1.,float(np.quantile(r.metrics['channel_'+k+'_score'][r.valid],q))) for k in self.KEYS]
                raw=np.max(np.column_stack([r.metrics['channel_'+k+'_score'][r.valid]/s for k,s in zip(self.KEYS,scales)]),axis=1)
            else:scales=None;raw=r.scores[r.valid]
            cut=max(1.,float(np.nextafter(np.quantile(raw,q),np.inf)))
            self.reference['score_calibration']=dict(threshold=cut,quantile=q,fingerprint=normal_batch.fingerprint,
                accepted_samples=int(r.valid.sum()),normal_status_is_caller_declared=True)
            if scales is not None:self.reference['score_calibration']['channel_scales']=scales
            if self.calibration_scope in ('load_groups','evaporator_groups'):
                groups=[]
                for load in np.unique(r.metrics['heat_demand_w'][r.valid]):
                    mask=r.valid&(r.metrics['heat_demand_w']==load)
                    if mask.sum()<minimum_samples:raise ValueError('insufficient load calibration')
                    selected=['evaporating_temperature_k','log_electric_power','log_compressor_speed','log_heating_cop'] if self.calibration_scope=='evaporator_groups' else list(self.KEYS)
                    floors=[(.05 if k.endswith('_k') else .002)/self.reference['refrigerant_model']['residual_scale'][i] if k in selected and self.calibration_scope=='evaporator_groups' else 1. for i,k in enumerate(self.KEYS)]
                    scale=[max(floor,float(np.quantile(r.metrics['channel_'+k+'_score'][mask],q))) for k,floor in zip(self.KEYS,floors)]
                    raw=np.max(np.column_stack([r.metrics['channel_'+k+'_score'][mask]/scale[self.KEYS.index(k)] for k in selected]),axis=1)
                    threshold=max(1.,float(np.nextafter(np.quantile(raw,q),np.inf)))
                    groups.append(dict(load_w=float(load),channel_scales=scale,threshold=threshold,accepted_samples=int(mask.sum())))
                if len(groups)<2:raise ValueError('at least two load calibration groups required')
                self.reference['score_calibration']['load_groups']=groups
        except Exception:
            self.reference.pop('score_calibration',None)
            if previous is not None:self.reference['score_calibration']=previous
            raise
        return self

    def _score(self,metrics):
        m=self.reference['refrigerant_model'];y=np.column_stack([metrics[k] for k in self.KEYS])
        expected=self._design(metrics['heat_demand_w'],m)@np.asarray(m['coefficients'])+np.asarray(m['residual_center'])
        z=(y-expected)/np.asarray(m['residual_scale']);scores=abs(z);scores[:,0]=np.maximum(-z[:,0],0)
        if self.evaporator_directional:
            for k,direction in [('evaporating_temperature_k',-1),('log_electric_power',1),('log_compressor_speed',1),('log_heating_cop',-1)]:
                j=self.KEYS.index(k);scores[:,j]=np.maximum(direction*z[:,j],0)
        for j,k in enumerate(self.KEYS):metrics['channel_'+k+'_score']=scores[:,j];metrics['expected_'+k]=expected[:,j]
        scales=self.reference.get('score_calibration',{}).get('channel_scales')
        raw=np.max(scores if scales is None else scores/np.asarray(scales),axis=1);metrics['raw_residual_score']=raw
        groups=self.reference.get('score_calibration',{}).get('load_groups')
        if groups is not None:
            pooled=raw/self.reference.get('score_calibration',{}).get('threshold',1.)
            raw=np.full(len(y),np.nan)
            for group in groups:
                mask=np.isclose(metrics['heat_demand_w'],group['load_w'],rtol=0,atol=1e-6)
                selected=[self.KEYS.index(k) for k in ['evaporating_temperature_k','log_electric_power','log_compressor_speed','log_heating_cop']] if self.calibration_scope=='evaporator_groups' else list(range(len(self.KEYS)))
                raw[mask]=np.max((scores[mask]/np.asarray(group['channel_scales']))[:,selected],axis=1)/group['threshold']
            if self.calibration_scope=='evaporator_groups':raw=np.maximum(raw,pooled)
            return raw
        return raw/self.reference.get('score_calibration',{}).get('threshold',1.)
