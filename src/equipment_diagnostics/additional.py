"""Additional equipment screens with declared physical inputs and limited claims."""
from __future__ import annotations
import numpy as np
from .base import Diagnostic, finish, number


class ColumnHydraulicsDiagnostic(Diagnostic):
    """Compare column dp [Pa] with a normal internal-load power relation.

    Vapor/liquid inputs are internal mass flows [kg/s]. Learned or declared
    exponents are empirical normal compensation, not a flooding correlation.
    Feed flow cannot silently stand in for unknown internal circulation.
    """
    kind = "column_hydraulics"
    references = ("10.1016/j.dche.2023.100098",)
    reference_metric = "normalized_pressure_drop_pa"
    envelope_roles = ("vapor_flow_kg_s", "liquid_flow_kg_s")

    def __init__(self, channels, *, reference_vapor_flow_kg_s, reference_liquid_flow_kg_s,
                 vapor_exponent=None, liquid_exponent=None, growth_limit_fraction=0.3,
                 reference_mode='declared_power', **kwargs):
        super().__init__(channels, **kwargs)
        self.vref = number(reference_vapor_flow_kg_s, "reference_vapor_flow_kg_s", positive=True)
        self.lref = number(reference_liquid_flow_kg_s, "reference_liquid_flow_kg_s", positive=True)
        if reference_mode not in ('declared_power','learned_power'): raise ValueError('invalid column reference_mode')
        self.reference_mode=reference_mode
        if reference_mode=='learned_power' and (vapor_exponent is not None or liquid_exponent is not None):
            raise ValueError('omit exponents for learned_power')
        self.nv = number(vapor_exponent, "vapor_exponent", nonnegative=True) if reference_mode=='declared_power' else 0.
        self.nl = number(liquid_exponent, "liquid_exponent", nonnegative=True) if reference_mode=='declared_power' else 0.
        self.limit = number(growth_limit_fraction, "growth_limit_fraction", positive=True)
        self.params = {"reference_vapor_flow_kg_s": self.vref,
                       "reference_liquid_flow_kg_s": self.lref, "vapor_exponent": self.nv,
                       "liquid_exponent": self.nl, "growth_limit_fraction": self.limit}
        if reference_mode=='learned_power': self.params['reference_mode']=reference_mode

    def fit(self, normal_batch, *, minimum_samples=10):
        super().fit(normal_batch,minimum_samples=minimum_samples)
        if self.reference_mode=='learned_power':
            try:
                from .operating_models import fit_column
                fit_column(self,normal_batch)
            except Exception:
                self.reference=None
                raise
        return self

    def set_reference(self, reference):
        if self.reference_mode=='learned_power':
            from .operating_models import validate_column
            validate_column(reference.get('learned_power_model'))
            with np.errstate(all='ignore'):
                expected=np.exp(reference['learned_power_model']['intercept_log_pa'])
            if not np.isclose(expected,reference.get('center'),rtol=1e-12,atol=0):
                raise ValueError('inconsistent learned column center')
        return super().set_reference(reference)

    def _raw(self, batch):
        c, valid = self._columns(batch, {"pressure_drop": "Pa", "vapor_flow": "kg/s",
                                         "liquid_flow": "kg/s"})
        dp, vapor, liquid = c["pressure_drop"], c["vapor_flow"], c["liquid_flow"]
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            pressure = dp*(self.vref/vapor)**self.nv*(self.lref/liquid)**self.nl
            pressure = np.where((dp > 0) & (pressure == 0), np.nan, pressure)
        metrics={"normalized_pressure_drop_pa": pressure,"vapor_flow_kg_s": vapor,"liquid_flow_kg_s": liquid}
        if self.reference_mode=='learned_power':
            metrics['measured_pressure_drop_pa']=dp
            if self.reference and 'learned_power_model' in self.reference:
                from .operating_models import column_predict
                with np.errstate(all='ignore'):
                    predicted=column_predict(self,metrics)
                    normalized=dp/predicted*self.reference['center']
                    normalized=np.where((dp>0)&(normalized==0),np.nan,normalized)
                metrics.update(expected_pressure_drop_pa=predicted,normalized_pressure_drop_pa=normalized)
        return finish(metrics, valid,
                      physical=(dp > 0) & (vapor > 0) & (liquid > 0))

    def _score(self, metrics):
        return np.maximum(metrics[self.reference_metric]/self.reference["center"]-1, 0)/self.limit


class SteamTrapDiagnostic(Diagnostic):
    """Apply site-configured temperature/acoustic patterns during supply.

    Steam/trap temperatures use K; acoustic_level and supply_on use 1.
    Acoustic normalization and quiet/loud thresholds belong to the caller.
    Warmup exclusion also delays fault decisions. No steam-leak mass rate
    or independently qualified condensate-versus-steam classifier is implied.
    """
    kind = "steam_trap"
    references = ("Emerson: Productivity Improvement with Wireless Steam Trap Monitoring (2020)",)

    def __init__(self, channels, *, acoustic_quiet_max, acoustic_loud_min,
                 cold_margin_k, hot_margin_k, startup_exclusion_s=0.0, **kwargs):
        super().__init__(channels, **kwargs)
        self.quiet = number(acoustic_quiet_max, "acoustic_quiet_max", nonnegative=True)
        self.loud = number(acoustic_loud_min, "acoustic_loud_min", positive=True)
        self.cold = number(cold_margin_k, "cold_margin_k", positive=True)
        self.hot = number(hot_margin_k, "hot_margin_k", nonnegative=True)
        if self.quiet >= self.loud or self.hot >= self.cold:
            raise ValueError("quiet < loud and hot_margin < cold_margin required")
        self.params = {"acoustic_quiet_max": self.quiet, "acoustic_loud_min": self.loud,
                       "cold_margin_k": self.cold, "hot_margin_k": self.hot}
        self.startup_exclusion=number(startup_exclusion_s,'startup_exclusion_s',nonnegative=True)
        if self.startup_exclusion:
            self.params['startup_exclusion_s']=self.startup_exclusion
            self.window=self.startup_exclusion

    def _raw(self, batch):
        c, valid = self._columns(batch, {"steam_temperature": "K", "trap_temperature": "K",
                                         "acoustic_level": "1", "supply_on": "1"})
        steam, trap, sound, supply = (c[k] for k in
                                     ("steam_temperature", "trap_temperature", "acoustic_level", "supply_on"))
        delta = steam-trap
        cold_score = np.where(sound <= self.quiet, np.maximum(delta, 0)/self.cold, 0)
        hot_score = np.where(delta <= self.hot, sound/self.loud, 0)
        metrics,valid,reasons=finish({"temperature_deficit_k": delta, "cold_quiet_score": cold_score,
                       "hot_loud_score": hot_score}, valid,
                      physical=(steam > 0) & (trap > 0) & (sound >= 0) & (supply == 1),
                      reason="steam_supply_off_or_invalid_physical_input")
        if self.startup_exclusion:
            input_valid=valid.copy(); start=None
            for i in range(len(valid)):
                if not input_valid[i]: start=None; continue
                if self._break(batch,i,input_valid) or start is None: start=batch.time_s[i]
                if batch.time_s[i]-start<self.startup_exclusion:
                    valid[i]=False; reasons[i]='steam_trap_startup_exclusion'
        return metrics,valid,reasons

    def _score(self, metrics):
        return np.maximum(metrics["cold_quiet_score"], metrics["hot_loud_score"])


class ChillerPerformanceDiagnostic(Diagnostic):
    """Compute water-side cooling COP and normal performance deviations.

    Base roles include five temperatures [K], chilled flow [kg/s] and
    electrical power [W]. Conditioned/auxiliary stages require additional
    explicit roles; inspect the constructor and stage validation logic.
    Additional-stage research candidates have high false alarms and are
    not promoted to default fault-specific alarms by being implemented.
    """
    kind = "chiller_performance"
    references = ("10.3390/s20092458",)
    reference_metric = "cop"
    envelope_roles = ("evaporator_duty_w", "chilled_flow_kg_s")

    @property
    def score_semantics(self):
        if self.reference_mode=='conditioned':
            return ('ratio_to_normal_calibrated_threshold' if self.reference and self.reference.get('score_calibration')
                    else 'normalized_normal_model_residual')
        return 'ratio_to_engineering_limit'

    def __init__(self, channels, *, water_cp_j_kg_k=4180.0, cop_decline_limit_fraction=0.2,
                 approach_increase_limit_k=3.0, enforce_isothermal_carnot_bound=False,
                 reference_mode='constant', regression_degree=2, ridge_alpha=0.01,
                 fractional_residual_floor=0.02, approach_residual_floor_k=0.2,
                 diagnostic_stage=0, ewma_tau_s=60.0, ewma_warmup_s=180.0,
                 auxiliary_conditioning='water', **kwargs):
        super().__init__(channels, **kwargs)
        self.cp = number(water_cp_j_kg_k, "water_cp_j_kg_k", positive=True)
        self.limit = number(cop_decline_limit_fraction, "cop_decline_limit_fraction", positive=True)
        self.approach_limit = number(approach_increase_limit_k, "approach_increase_limit_k", positive=True)
        if not isinstance(enforce_isothermal_carnot_bound, bool):
            raise ValueError("enforce_isothermal_carnot_bound must be boolean")
        self.carnot_gate = enforce_isothermal_carnot_bound
        if reference_mode not in ('constant','conditioned'):
            raise ValueError('reference_mode must be constant or conditioned')
        if isinstance(regression_degree,bool) or regression_degree not in (1,2):
            raise ValueError('regression_degree must be 1 or 2')
        self.reference_mode=reference_mode; self.degree=int(regression_degree)
        if isinstance(diagnostic_stage,bool) or not isinstance(diagnostic_stage,int) or diagnostic_stage not in (0,1,2,3):
            raise ValueError('diagnostic_stage must be 0, 1, 2 or 3')
        if diagnostic_stage and reference_mode!='conditioned':
            raise ValueError('staged diagnostics require reference_mode=conditioned')
        self.diagnostic_stage=diagnostic_stage
        if auxiliary_conditioning not in ('water','water_refrigerant'):
            raise ValueError('invalid auxiliary_conditioning')
        if auxiliary_conditioning!='water' and not diagnostic_stage:
            raise ValueError('auxiliary conditioning requires a staged model')
        self.auxiliary_conditioning=auxiliary_conditioning
        self.ewma_tau=number(ewma_tau_s,'ewma_tau_s',positive=True)
        self.ewma_warmup=number(ewma_warmup_s,'ewma_warmup_s',nonnegative=True)
        self.ridge=number(ridge_alpha,'ridge_alpha',positive=True)
        self.fraction_floor=number(fractional_residual_floor,'fractional_residual_floor',positive=True)
        self.temperature_floor=number(approach_residual_floor_k,'approach_residual_floor_k',positive=True)
        if self.limit >= 1:
            raise ValueError("COP decline fraction must be < 1")
        self.params = {"water_cp_j_kg_k": self.cp, "cop_decline_limit_fraction": self.limit,
                       "approach_increase_limit_k": self.approach_limit,
                       "enforce_isothermal_carnot_bound": self.carnot_gate}
        if auxiliary_conditioning!='water': self.params['auxiliary_conditioning']=auxiliary_conditioning
        if reference_mode=='conditioned':
            self.envelope_roles=('evaporator_duty_w','chilled_out_k','cooling_in_k')
            self.params.update(reference_mode=reference_mode,regression_degree=self.degree,ridge_alpha=self.ridge,
                fractional_residual_floor=self.fraction_floor,approach_residual_floor_k=self.temperature_floor)
            if diagnostic_stage:
                self.params.update(diagnostic_stage=diagnostic_stage,ewma_tau_s=self.ewma_tau,ewma_warmup_s=self.ewma_warmup)
            if diagnostic_stage==3:
                self.envelope_roles=(*self.envelope_roles,'cooling_flow_kg_s')

    @property
    def requires_full_history(self):
        # EWMA has infinite memory. Exact chunk replay cannot silently trim it.
        return self.diagnostic_stage>=2

    def _raw(self, batch):
        required={"chilled_in": "K", "chilled_out": "K",
            "cooling_out": "K", "evaporating_temperature": "K", "condensing_temperature": "K",
            "chilled_flow": "kg/s", "electric_power": "W"}
        if self.reference_mode=='conditioned': required['cooling_in']='K'
        if self.diagnostic_stage:
            from .chiller_staged import SENSOR_UNITS
            required.update(SENSOR_UNITS)
            if self.diagnostic_stage==3: required['cooling_flow']='kg/s'
        c, valid = self._columns(batch,required)
        a, b, cooling, evap, cond, flow, power = (c[k] for k in
            ("chilled_in", "chilled_out", "cooling_out", "evaporating_temperature",
             "condensing_temperature", "chilled_flow", "electric_power"))
        duty = flow*self.cp*(a-b)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            cop = duty/power
            cop = np.where((flow > 0) & (a > b) & (cop == 0), np.nan, cop)
            carnot = evap/(cond-evap)
        physical = ((a > b) & (b > 0) & (cooling > 0) & (evap > 0) & (cond > evap)
                    & (b >= evap) & (cond >= cooling) & (flow > 0) & (power > 0))
        # This bound assumes isothermal refrigerant heat transfer at the supplied
        # temperatures. It is opt-in: glide, subcooling and transient storage need
        # a cycle-specific entropy balance instead.
        if self.carnot_gate:
            physical &= cop <= carnot*(1+1e-10)
        metrics={"cop": cop, "evaporator_duty_w": duty,
                       "isothermal_carnot_cop": carnot,
                       "evaporator_approach_k": b-evap, "condenser_approach_k": cond-cooling,
                       "chilled_flow_kg_s": flow}
        if self.reference_mode=='conditioned':
            physical &= (c['cooling_in']>0)&(cooling>=c['cooling_in'])
            metrics.update(chilled_out_k=b,cooling_in_k=c['cooling_in'],electric_power_w=power)
            if self.reference is not None and 'conditioned_model' in self.reference:
                from .chiller_reference import augment
                with np.errstate(all='ignore'):
                    metrics=augment(metrics,self.reference['conditioned_model'])
        metrics,valid,reasons=finish(metrics,valid,physical=physical)
        if self.diagnostic_stage:
            if self.auxiliary_conditioning=='water_refrigerant':
                metrics.update(evaporating_temperature_k=evap,condensing_temperature_k=cond)
            from .chiller_staged import enrich
            metrics,valid,reasons=enrich(self,batch,c,metrics,valid,reasons)
        return metrics,valid,reasons

    def fit(self, normal_batch, *, minimum_samples=10):
        super().fit(normal_batch, minimum_samples=minimum_samples)
        try:
            metrics, valid, _ = self._raw(normal_batch)
            for key in ("evaporator_approach_k", "condenser_approach_k"):
                self.reference[key] = float(np.median(metrics[key][valid]))
            if self.reference_mode=='conditioned':
                from .chiller_reference import fit,features,targets
                valid &= np.logical_and.reduce([np.isfinite(v) for v in metrics.values()])
                if valid.sum()<max(minimum_samples,20):
                    raise ValueError('insufficient conditional chiller training samples')
                floors=np.array([np.log1p(self.fraction_floor),self.temperature_floor,
                                 self.temperature_floor,np.log1p(self.fraction_floor)])
                self.reference['conditioned_model']=fit(features(metrics)[valid],targets(metrics)[valid],
                    degree=self.degree,alpha=self.ridge,floors=floors)
                for key in self.envelope_roles:
                    low=float(metrics[key][valid].min()); high=float(metrics[key][valid].max())
                    pad=max(abs(low),abs(high))*.1 if key in ('evaporator_duty_w','cooling_flow_kg_s') else max((high-low)*.1,1.)
                    self.reference['envelope'][key]=[low-pad,high+pad]
                if self.diagnostic_stage:
                    from .chiller_staged import fit_reference
                    self.reference['staged_reference']=fit_reference(self,normal_batch)
        except Exception:
            self.reference = None
            raise
        return self

    def set_reference(self, reference):
        if self.reference_mode=='conditioned':
            from .chiller_reference import validate
            validate(reference.get('conditioned_model'),self.degree,self.ridge)
            if self.diagnostic_stage:
                from .chiller_staged import validate_reference
                validate_reference(self,reference.get('staged_reference'))
            calibration=reference.get('score_calibration')
            if calibration is not None:
                if not isinstance(calibration,dict): raise ValueError('invalid chiller calibration')
                number(calibration.get('threshold'),'calibration threshold',positive=True)
                q=number(calibration.get('quantile'),'calibration quantile',positive=True)
                if q>=1 or not calibration.get('fingerprint') or calibration['fingerprint']==reference.get('training_fingerprint'):
                    raise ValueError('independent normal chiller calibration required')
        for key in ("evaporator_approach_k", "condenser_approach_k"):
            number(reference.get(key), key, nonnegative=True)
        return super().set_reference(reference)

    def calibrate(self, normal_batch, *, quantile=0.99, minimum_samples=10):
        """Freeze a normal-only score threshold on a separately supplied batch.

        Caller must independently establish normal status; no fault labels are
        consumed. Fingerprints detect identical reuse, not statistical independence.
        """
        if self.reference_mode!='conditioned' or self.reference is None:
            raise ValueError('fit a conditioned chiller reference before calibration')
        q=number(quantile,'quantile',positive=True)
        if q>=1: raise ValueError('quantile must be <1')
        if isinstance(minimum_samples,bool) or not isinstance(minimum_samples,int) or minimum_samples<2:
            raise ValueError('minimum_samples must be an integer >=2')
        if normal_batch.fingerprint==self.reference['training_fingerprint']:
            raise ValueError('calibration must differ from training batch')
        self.reference.pop('score_calibration',None)
        result=self.score(normal_batch)
        if result.valid.sum()<minimum_samples:
            raise ValueError('insufficient normal chiller calibration samples')
        threshold=max(1.,float(np.nextafter(np.quantile(result.scores[result.valid],q),np.inf)))
        self.reference['score_calibration']={'threshold':threshold,'quantile':q,
            'fingerprint':normal_batch.fingerprint,'accepted_samples':int(result.valid.sum()),
            'normal_status_is_caller_declared':True}
        return self

    def _score(self, metrics):
        if self.reference_mode=='conditioned':
            raw=(metrics['staged_max_score'] if self.diagnostic_stage else
                 np.maximum.reduce([metrics[k] for k in ('power_excess_score','evaporator_residual_score',
                                                        'condenser_residual_score','flow_residual_score')]))
            metrics['condition_residual_score']=raw
            threshold=self.reference.get('score_calibration',{}).get('threshold',1.)
            return raw/threshold
        cop_score = np.maximum(1-metrics["cop"]/self.reference["center"], 0)/self.limit
        evap_score = np.maximum(metrics["evaporator_approach_k"]-self.reference["evaporator_approach_k"], 0)/self.approach_limit
        cond_score = np.maximum(metrics["condenser_approach_k"]-self.reference["condenser_approach_k"], 0)/self.approach_limit
        return np.maximum.reduce([cop_score, evap_score, cond_score])
