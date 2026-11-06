"""Original equipment screening equations; not reproductions of paper algorithms."""
from __future__ import annotations
import numpy as np
from .base import Diagnostic, finish, number


class MassBalanceDiagnostic(Diagnostic):
    """Estimate positive unexplained loss over a causal inventory window.

    Map inventory_mass [kg], inflow/outflow [kg/s] and optional known_loss
    [kg/s]. Configure an engineering loss limit, window and sensor bounds.
    Metrics contain loss, mean net flow and inventory change [kg/s]. This is
    boundary accounting, not leak localization. See docs/MODEL_GUIDE.md.
    """
    kind = "mass_balance"
    references = ("10.1016/S0098-1354(02)00147-3",)

    def __init__(self, channels, *, loss_limit_kg_s, window_s=60.0,
                 inventory_error_bound_kg=0.0, inflow_error_bound_kg_s=0.0,
                 outflow_error_bound_kg_s=0.0, known_loss_error_bound_kg_s=0.0, **kwargs):
        super().__init__(channels, **kwargs)
        self.limit = number(loss_limit_kg_s, "loss_limit_kg_s", positive=True)
        self.window = number(window_s, "window_s", positive=True)
        self.params = {"loss_limit_kg_s": self.limit, "window_s": self.window}
        bounds={k:number(v,k,nonnegative=True) for k,v in dict(
            inventory_error_bound_kg=inventory_error_bound_kg,
            inflow_error_bound_kg_s=inflow_error_bound_kg_s,
            outflow_error_bound_kg_s=outflow_error_bound_kg_s,
            known_loss_error_bound_kg_s=known_loss_error_bound_kg_s).items()}
        self.loss_error_bound=2*bounds['inventory_error_bound_kg']/self.window+sum(
            v for k,v in bounds.items() if k!='inventory_error_bound_kg')
        number(self.loss_error_bound,'combined loss error bound',nonnegative=True)
        if any(bounds.values()): self.params.update(bounds)

    def _raw(self, batch):
        c, mask = self._columns(batch, {"inventory_mass": "kg", "inflow": "kg/s",
                                        "outflow": "kg/s"}, {"known_loss": "kg/s"})
        m, inc, out = c["inventory_mass"], c["inflow"], c["outflow"]
        loss = c.get("known_loss", np.zeros(len(m)))
        physical = (m >= 0) & (inc >= 0) & (out >= 0) & (loss >= 0)
        _, mask, reasons = finish({}, mask, physical=physical)
        residual = np.full(len(m), np.nan)
        net_mean = residual.copy(); inventory_rate = residual.copy()
        flow = inc-out-loss
        t = batch.time_s
        integral = np.zeros(len(t)); start = 0
        usable = np.zeros(len(m), bool)
        for i in range(len(t)):
            if not mask[i]:
                start = i+1
                continue
            if self._break(batch, i, mask):
                start = i
                integral[i] = 0.0
            else:
                integral[i] = integral[i-1] + (flow[i]+flow[i-1])*0.5*(t[i]-t[i-1])
            cut = t[i]-self.window
            if cut >= t[i]:
                reasons[i] = "inventory_window_below_clock_resolution"
                continue
            if cut < t[start]:
                reasons[i] = "inventory_window_warmup"
                continue
            # Exact partial trapezoid under a piecewise-linear boundary flow.
            j = start + int(np.searchsorted(t[start:i+1], cut, side="right"))-1
            dt = cut-t[j]
            if dt == 0:
                mass_at_cut, integrated_at_cut = m[j], integral[j]
            else:
                span = t[j+1]-t[j]
                partial_flow = flow[j]*dt + 0.5*(flow[j+1]-flow[j])*dt*dt/span
                full_flow = 0.5*(flow[j]+flow[j+1])*span
                # Preserve the observed interval closure. Boundary flow is linear;
                # unresolved loss is constant within this sampling interval.
                mass_at_cut = m[j]+partial_flow+(dt/span)*(m[j+1]-m[j]-full_flow)
                integrated_at_cut = integral[j]+partial_flow
            net_mean[i] = (integral[i]-integrated_at_cut)/self.window
            inventory_rate[i] = (m[i]-mass_at_cut)/self.window
            residual[i] = net_mean[i]-inventory_rate[i]
            usable[i] = True
        metrics={"unaccounted_loss_kg_s": residual, "net_boundary_flow_kg_s": net_mean,
                 "inventory_change_kg_s": inventory_rate}
        if self.loss_error_bound:
            metrics.update(loss_error_bound_kg_s=np.full(len(m),self.loss_error_bound),
                loss_lower_bound_kg_s=residual-self.loss_error_bound,
                loss_upper_bound_kg_s=residual+self.loss_error_bound)
        return metrics, usable, reasons

    def _score(self, metrics):
        return np.maximum(metrics["unaccounted_loss_kg_s"]-self.loss_error_bound, 0)/self.limit


class BoilerBalanceDiagnostic(MassBalanceDiagnostic):
    """Inventory must include steam/water accumulation from a qualified estimator.

    Drum level alone is deliberately not converted to total inventory here.
    Map steam to outflow and measured blowdown to known_loss.
    """
    kind = "boiler_mass_balance"


class HeatExchangerDiagnostic(Diagnostic):
    """Monitor single-phase, quasi-steady counterflow heat transfer.

    Four temperatures [K], two mass flows [kg/s] and declared cp values give
    heat duties [W], LMTD [K] and UA [W/K]. Normal references can compensate
    flow-dependent resistance. Heat-balance validity is separate from alarm
    scoring; neither an alarm nor a UA decline identifies foulant chemistry.
    """
    kind = "heat_exchanger"
    references = ("10.1080/00986445.2023.2202316",)
    reference_metric = "ua_w_k"
    envelope_roles = ("hot_flow_kg_s", "cold_flow_kg_s")

    def __init__(self, channels, *, cp_hot_j_kg_k, cp_cold_j_kg_k,
                 degradation_limit_fraction=0.2, max_energy_imbalance_fraction=0.15,
                 min_lmtd_k=0.5, max_inlet_rate_k_s=0.05, reference_mode='constant',
                 hot_flow_exponent=0.8, cold_flow_exponent=0.8,
                 max_flow_change_fraction_s=None, **kwargs):
        super().__init__(channels, **kwargs)
        self.cp_hot = number(cp_hot_j_kg_k, "cp_hot_j_kg_k", positive=True)
        self.cp_cold = number(cp_cold_j_kg_k, "cp_cold_j_kg_k", positive=True)
        self.limit = number(degradation_limit_fraction, "degradation_limit_fraction", positive=True)
        self.imbalance = number(max_energy_imbalance_fraction, "max_energy_imbalance_fraction", positive=True)
        if self.limit >= 1 or self.imbalance >= 1:
            raise ValueError("degradation and energy imbalance fractions must be < 1")
        self.min_lmtd = number(min_lmtd_k, "min_lmtd_k", positive=True)
        self.max_rate = number(max_inlet_rate_k_s, "max_inlet_rate_k_s", positive=True)
        self.params = {"cp_hot_j_kg_k": self.cp_hot, "cp_cold_j_kg_k": self.cp_cold,
                       "degradation_limit_fraction": self.limit,
                       "max_energy_imbalance_fraction": self.imbalance,
                       "min_lmtd_k": self.min_lmtd, "max_inlet_rate_k_s": self.max_rate}
        if reference_mode not in ('constant','flow_resistance'): raise ValueError('invalid heat-exchanger reference_mode')
        self.reference_mode=reference_mode
        self.hot_exponent=number(hot_flow_exponent,'hot_flow_exponent',positive=True)
        self.cold_exponent=number(cold_flow_exponent,'cold_flow_exponent',positive=True)
        if reference_mode=='flow_resistance': self.params.update(reference_mode=reference_mode,
            hot_flow_exponent=self.hot_exponent,cold_flow_exponent=self.cold_exponent)
        self.max_flow_change=(None if max_flow_change_fraction_s is None else
            number(max_flow_change_fraction_s,'max_flow_change_fraction_s',positive=True))
        if self.max_flow_change is not None:self.params['max_flow_change_fraction_s']=self.max_flow_change

    def fit(self, normal_batch, *, minimum_samples=10):
        super().fit(normal_batch,minimum_samples=minimum_samples)
        if self.reference_mode=='flow_resistance':
            try:
                from .operating_models import fit_heat
                fit_heat(self,normal_batch)
            except Exception:
                self.reference=None
                raise
        return self

    def set_reference(self, reference):
        if self.reference_mode=='flow_resistance':
            from .operating_models import validate_heat
            validate_heat(reference.get('flow_resistance_model'))
        return super().set_reference(reference)

    def _raw(self, batch):
        c, valid = self._columns(batch, {"hot_in": "K", "hot_out": "K", "cold_in": "K",
                                        "cold_out": "K", "hot_flow": "kg/s", "cold_flow": "kg/s"})
        hi, ho, ci, co, hf, cf = (c[k] for k in
                                  ("hot_in", "hot_out", "cold_in", "cold_out", "hot_flow", "cold_flow"))
        d1, d2 = hi-co, ho-ci
        physical = ((hi > 0) & (ho > 0) & (ci > 0) & (co > 0) & (hf > 0) & (cf > 0)
                    & (hi > ho) & (co > ci) & (d1 > 0) & (d2 > 0))
        qh = hf*self.cp_hot*(hi-ho); qc = cf*self.cp_cold*(co-ci)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            # log1p avoids cancellation near equal approaches; a difference of
            # logs avoids overflow when the approaches have very different scales.
            relative = (d1-d2)/d2
            logarithm = np.where(np.abs(relative) < 0.5, np.log1p(relative),
                                 np.log(d1)-np.log(d2))
            lmtd = np.divide(d1-d2, logarithm, out=d1.copy(), where=d1 != d2)
            imbalance = np.abs(qh-qc)/np.maximum(np.abs(qh), np.abs(qc))
            ua = 0.5*(qh+qc)/lmtd
        metrics, valid, reasons = finish(
            {"ua_w_k": ua, "hot_duty_w": qh, "cold_duty_w": qc,
             "energy_imbalance_fraction": imbalance, "lmtd_k": lmtd,
             "hot_flow_kg_s": hf, "cold_flow_kg_s": cf}, valid, physical=physical)
        bad = valid & ((imbalance > self.imbalance) | (lmtd < self.min_lmtd))
        reasons[bad] = "energy_closure_or_temperature_approach_failed"
        valid[bad] = False
        input_good = valid.copy()
        for i in range(len(valid)):
            if not input_good[i]:
                continue
            if self._break(batch, i, input_good):
                valid[i] = False; reasons[i] = "steady_state_check_warmup"
            else:
                dt = batch.time_s[i]-batch.time_s[i-1]
                rate = max(abs(hi[i]-hi[i-1]), abs(ci[i]-ci[i-1]))/dt
                if rate > self.max_rate:
                    valid[i] = False; reasons[i] = "inlet_temperature_transient"
                elif self.max_flow_change is not None:
                    flow_rate=max(abs(hf[i]-hf[i-1])/max(hf[i],hf[i-1]),
                                  abs(cf[i]-cf[i-1])/max(cf[i],cf[i-1]))/dt
                    if flow_rate>self.max_flow_change:
                        valid[i]=False;reasons[i]='heat_exchanger_flow_transient'
        if self.reference_mode=='flow_resistance' and self.reference and 'flow_resistance_model' in self.reference:
            from .operating_models import heat_basis
            ref=self.reference['flow_resistance_model']
            with np.errstate(all='ignore'):
                resistance=heat_basis(metrics,ref['flow_reference_kg_s'],self.hot_exponent,self.cold_exponent)@np.asarray(ref['coefficients_k_w'])
                metrics.update(expected_ua_w_k=1/resistance,ua_retention_fraction=metrics['ua_w_k']*resistance,
                    added_thermal_resistance_k_w=1/metrics['ua_w_k']-resistance)
        return metrics, valid, reasons

    def _score(self, metrics):
        if self.reference_mode=='flow_resistance':
            return np.maximum(1-metrics['ua_retention_fraction'],0)/self.limit
        return np.maximum(1-metrics["ua_w_k"]/self.reference["center"], 0)/self.limit


class HydraulicResistanceDiagnostic(Diagnostic):
    """Detect increased pressure loss after declared flow/property correction.

    Input dp [Pa] and volume flow [m3/s] or a dimensionless flow ratio. Optional
    density [kg/m3] and viscosity [Pa*s] support explicitly chosen models.
    The geometry and phase regime must remain applicable; zero flow cannot
    be normalized. This one-sided detector does not qualify bypass/leakage.
    """
    kind = "hydraulic_resistance"
    references = ("10.5220/0010405401020109",)
    reference_metric = "normalized_pressure_drop_pa"
    envelope_roles = ("volume_flow_m3_s",)

    def __init__(self, channels, *, reference_flow_m3_s=None, flow_exponent=None,
                 reference_density_kg_m3=1000.0, density_exponent=1.0,
                 growth_limit_fraction=0.25, normalization_mode='power',
                 reference_viscosity_pa_s=0.001, flow_input='volume', **kwargs):
        super().__init__(channels, **kwargs)
        if flow_input not in ('volume','ratio'):raise ValueError('flow_input must be volume or ratio')
        self.flow_input=flow_input
        if flow_input=='ratio' and reference_flow_m3_s is not None:raise ValueError('ratio mode has no dimensional reference flow')
        self.qref = number(reference_flow_m3_s, "reference_flow_m3_s", positive=True) if flow_input=='volume' else 1.
        self.flow_metric='volume_flow_m3_s' if flow_input=='volume' else 'flow_ratio'
        self.envelope_roles=(self.flow_metric,)
        if normalization_mode not in ('power','mixed'): raise ValueError('normalization_mode must be power or mixed')
        self.normalization_mode=normalization_mode
        self.exponent = number(flow_exponent, "flow_exponent", positive=True) if flow_exponent is not None else None
        if normalization_mode=='power' and self.exponent is None: raise ValueError('flow_exponent required for power mode')
        if normalization_mode=='mixed' and self.exponent is not None: raise ValueError('mixed mode learns two terms; omit flow_exponent')
        self.rho = number(reference_density_kg_m3, "reference_density_kg_m3", positive=True)
        self.rho_exponent = number(density_exponent, "density_exponent", nonnegative=True)
        self.limit = number(growth_limit_fraction, "growth_limit_fraction", positive=True)
        self.mu=number(reference_viscosity_pa_s,'reference_viscosity_pa_s',positive=True)
        self.params = {"reference_flow_m3_s": self.qref if flow_input=='volume' else None, "flow_exponent": self.exponent,
                       "reference_density_kg_m3": self.rho, "density_exponent": self.rho_exponent,
                       "growth_limit_fraction": self.limit}
        if flow_input=='ratio':self.params['flow_input']='ratio'
        if normalization_mode=='mixed':
            self.params.update(normalization_mode='mixed',reference_viscosity_pa_s=self.mu)
            self.envelope_roles=(*self.envelope_roles,'density_kg_m3','viscosity_pa_s')

    def fit(self, normal_batch, *, minimum_samples=10):
        super().fit(normal_batch,minimum_samples=minimum_samples)
        if self.normalization_mode=='mixed':
            try:
                from .quick_improvements import fit_hydraulic
                metrics,valid,_=self._raw(normal_batch)
                fit_hydraulic(self,metrics,valid)
            except Exception:
                self.reference=None
                raise
        return self

    def set_reference(self, reference):
        if self.normalization_mode=='mixed':
            a=np.asarray(reference.get('mixed_coefficients_pa'),float)
            if a.shape!=(2,) or not np.isfinite(a).all() or (a<0).any() or a.sum()<=0:
                raise ValueError('invalid mixed pressure coefficients')
            if not np.isclose(a.sum(),reference.get('center'),rtol=1e-12,atol=0):
                raise ValueError('mixed pressure reference center mismatch')
        return super().set_reference(reference)

    def _raw(self, batch):
        flow_role='volume_flow' if self.flow_input=='volume' else 'flow_ratio'
        c, mask = self._columns(batch, {"pressure_drop": "Pa", flow_role: "m3/s" if self.flow_input=='volume' else '1'},
                                {"density": "kg/m3",**({'viscosity':'Pa*s'} if self.normalization_mode=='mixed' else {})})
        dp, q = c["pressure_drop"], c[flow_role]
        rho = c.get("density", np.full(len(q), self.rho))
        if self.normalization_mode=='mixed':
            mu=c.get('viscosity',np.full(len(q),self.mu))
            with np.errstate(all='ignore'):
                terms=np.column_stack(((mu/self.mu)*(q/self.qref),(rho/self.rho)*(q/self.qref)**2))
                coefficients=None if self.reference is None else self.reference.get('mixed_coefficients_pa')
                expected=terms@np.asarray(coefficients) if coefficients is not None else np.ones(len(q))
                normalized=dp/expected*(sum(coefficients) if coefficients is not None else 1.)
                normalized=np.where((dp>0)&(normalized==0),np.nan,normalized)
            return finish({'normalized_pressure_drop_pa':normalized,self.flow_metric:q,
                'density_kg_m3':rho,'viscosity_pa_s':mu,'measured_pressure_drop_pa':dp,
                'viscous_basis':terms[:,0],'inertial_basis':terms[:,1],
                'expected_pressure_drop_pa':expected},mask,
                physical=(q>0)&(rho>0)&(mu>0)&(dp>=0)&(expected>0))
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            normalized = dp*(self.qref/q)**self.exponent*(self.rho/rho)**self.rho_exponent
            # A measured zero DP is admissible; a positive DP lost to arithmetic
            # underflow must not become evidence of low resistance.
            normalized = np.where((dp > 0) & (normalized == 0), np.nan, normalized)
        return finish({"normalized_pressure_drop_pa": normalized, self.flow_metric: q},
                      mask, physical=(q > 0) & (rho > 0) & (dp >= 0))

    def _score(self, metrics):
        return np.maximum(metrics[self.reference_metric]/self.reference["center"]-1, 0)/self.limit


class VaporizerDiagnostic(Diagnostic):
    """Compare outlet temperature with a prediction or a declared low limit.

    Outlet/predicted temperatures use K and mass flow uses kg/s. Optional
    enthalpies require a shared J/kg basis. Metrics describe temperature
    shortfall and optional duty, not measured vapor quality or frost cause.
    minimum_only deliberately needs no predicted-temperature sensor role.
    """
    kind = "vaporizer"
    references = ("10.1016/j.compchemeng.2024.108878", "10.3744/SNAK.2022.59.5.280")

    def __init__(self, channels, *, shortfall_limit_k, minimum_outlet_k=None,
                 prediction_mode='external', **kwargs):
        super().__init__(channels, **kwargs)
        self.limit = number(shortfall_limit_k, "shortfall_limit_k", positive=True)
        self.minimum = None if minimum_outlet_k is None else number(
            minimum_outlet_k, "minimum_outlet_k", positive=True)
        self.params = {"shortfall_limit_k": self.limit, "minimum_outlet_k": self.minimum}
        if prediction_mode not in ('external','minimum_only'): raise ValueError('invalid vaporizer prediction_mode')
        if prediction_mode=='minimum_only' and self.minimum is None: raise ValueError('minimum_outlet_k required')
        self.prediction_mode=prediction_mode
        if prediction_mode!='external': self.params['prediction_mode']=prediction_mode

    def _raw(self, batch):
        c, mask = self._columns(batch, {"outlet_temperature": "K", "mass_flow": "kg/s",
                                        **({'predicted_temperature':'K'} if self.prediction_mode=='external' else {})},
                                {"inlet_enthalpy": "J/kg", "outlet_enthalpy": "J/kg"})
        if ("inlet_enthalpy" in c) != ("outlet_enthalpy" in c):
            raise ValueError("provide both inlet and outlet enthalpy, with a shared caloric basis")
        metrics = {"outlet_temperature_k": c["outlet_temperature"]}
        if self.prediction_mode=='external': metrics['temperature_shortfall_k']=c['predicted_temperature']-c['outlet_temperature']
        if "inlet_enthalpy" in c:
            if not batch.metadata.get("enthalpy_basis_id"):
                raise ValueError("enthalpy_basis_id metadata required for duty calculation")
            metrics["absorbed_duty_w"] = c["mass_flow"]*(c["outlet_enthalpy"]-c["inlet_enthalpy"])
        return finish(metrics, mask, physical=(c["mass_flow"] > 0)
                      & (c["outlet_temperature"] > 0)
                      & ((c['predicted_temperature']>0) if self.prediction_mode=='external' else True))

    def _score(self, metrics):
        score = np.maximum(metrics["temperature_shortfall_k"], 0)/self.limit if self.prediction_mode=='external' else np.zeros(len(metrics['outlet_temperature_k']))
        if self.minimum is not None:
            score = np.maximum(score, 1+(self.minimum-metrics["outlet_temperature_k"])/self.limit)
        return np.maximum(score, 0)


class ROMembraneDiagnostic(Diagnostic):
    """Monitor reference-temperature permeability, not foulant identity.

    Qp [m3/s], area [m2], positive NDP [Pa] and TCF=A_ref/A(T) give
    Qp*TCF/(area*NDP) [m/(Pa*s)]. The raw-input correction path requires
    pressure ordering, osmotic pressures and explicit qualified temperature
    parameters; do not repair inconsistent sensor tags by guessing offsets.
    """
    kind = "ro_membrane"
    references = ("10.3390/membranes9090117",)
    reference_metric = "normalized_permeability_m_pa_s"
    envelope_roles = ("net_driving_pressure_pa",)

    def __init__(self, channels, *, membrane_area_m2, decline_limit_fraction=0.15,
                 input_mode='corrected', activation_energy_j_mol=None,
                 reference_temperature_k=298.15, temperature_range_k=None, **kwargs):
        super().__init__(channels, **kwargs)
        self.area = number(membrane_area_m2, "membrane_area_m2", positive=True)
        self.limit = number(decline_limit_fraction, "decline_limit_fraction", positive=True)
        if self.limit >= 1:
            raise ValueError("decline_limit_fraction must be < 1")
        self.params = {"membrane_area_m2": self.area, "decline_limit_fraction": self.limit}
        if input_mode not in ('corrected','pressures_temperature'): raise ValueError('invalid RO input_mode')
        self.input_mode=input_mode
        if input_mode=='pressures_temperature':
            self.activation=number(activation_energy_j_mol,'activation_energy_j_mol',positive=True)
            self.reference_temperature=number(reference_temperature_k,'reference_temperature_k',positive=True)
            if not isinstance(temperature_range_k,(list,tuple)) or len(temperature_range_k)!=2:
                raise ValueError('qualified temperature_range_k required')
            self.temp_range=[number(t,'temperature bound',positive=True) for t in temperature_range_k]
            if not self.temp_range[0]<=self.reference_temperature<=self.temp_range[1] or self.temp_range[0]>=self.temp_range[1]:
                raise ValueError('invalid qualified temperature range')
            self.params.update(input_mode=input_mode,activation_energy_j_mol=self.activation,
                reference_temperature_k=self.reference_temperature,temperature_range_k=self.temp_range)
            self.envelope_roles=(*self.envelope_roles,'membrane_temperature_k')

    def _raw(self, batch):
        extra={}; physical=True
        if self.input_mode=='pressures_temperature':
            from .operating_models import RO_UNITS,ro_inputs
            c,mask=self._columns(batch,RO_UNITS)
            p,factor,physical,extra=ro_inputs(self,c); q=c['permeate_flow']
        else:
            c, mask = self._columns(batch, {"permeate_flow": "m3/s", "net_driving_pressure": "Pa",
                                            "temperature_correction": "1"})
            q, p, factor = (c[k] for k in ("permeate_flow", "net_driving_pressure", "temperature_correction"))
        with np.errstate(divide="ignore", invalid="ignore"):
            permeability = q*factor/(self.area*p)
            permeability = np.where((q > 0) & (permeability == 0), np.nan, permeability)
        return finish({"normalized_permeability_m_pa_s": permeability,
                       "net_driving_pressure_pa": p,**extra}, mask,
                      physical=physical & (q >= 0) & (p > 0) & (factor > 0))

    def _score(self, metrics):
        return np.maximum(1-metrics[self.reference_metric]/self.reference["center"], 0)/self.limit


class ValveTrackingDiagnostic(Diagnostic):
    """Compare normalized command and observed position in the same clock.

    Both roles use fractions [1], not percent. A causal delay or declared
    first-order normal response produces expected position; engineering
    error limits and elapsed persistence produce the alarm. Tracking error
    alone does not establish stiction or a particular actuator root cause.
    """
    kind = "valve_tracking"
    references = ("10.1016/j.jprocont.2009.10.004",)

    def __init__(self, channels, *, error_limit_fraction, delay_s=0.0,
                 response_time_s=0.0, response_warmup_s=None, **kwargs):
        super().__init__(channels, **kwargs)
        self.limit = number(error_limit_fraction, "error_limit_fraction", positive=True)
        if self.limit >= 1:
            raise ValueError("error_limit_fraction must be < 1")
        self.delay = number(delay_s, "delay_s", nonnegative=True)
        self.params = {"error_limit_fraction": self.limit, "delay_s": self.delay}
        self.response_time=number(response_time_s,'response_time_s',nonnegative=True)
        if response_warmup_s is not None and not self.response_time:
            raise ValueError('response_warmup_s requires a positive response_time_s')
        self.response_warmup=(5*self.response_time if response_warmup_s is None else
            number(response_warmup_s,'response_warmup_s',nonnegative=True))
        number(self.response_warmup,'response_warmup_s',nonnegative=True)
        if self.response_time:
            self.params.update(response_time_s=self.response_time,response_warmup_s=self.response_warmup)

    @property
    def requires_full_history(self): return self.response_time>0

    def _raw(self, batch):
        c, mask = self._columns(batch, {"command": "1", "position": "1"})
        command, position = c["command"], c["position"]
        physical = (command >= 0) & (command <= 1) & (position >= 0) & (position <= 1)
        _, mask, reasons = finish({}, mask, physical=physical)
        if self.response_time:
            from .quick_improvements import dynamic_valve
            return dynamic_valve(self,batch,command,position,mask,reasons)
        error = np.full(len(command), np.nan)
        usable = mask.copy(); start = 0
        for i in range(len(command)):
            if self._break(batch, i, mask):
                start = i
            if not mask[i]:
                continue
            target = batch.time_s[i]-self.delay
            if target < batch.time_s[start]:
                usable[i] = False; reasons[i] = "actuator_delay_warmup"
            else:
                delayed = np.interp(target, batch.time_s[start:i+1], command[start:i+1])
                error[i] = position[i]-delayed
        return {"tracking_error_fraction": error}, usable, reasons

    def _score(self, metrics):
        return np.abs(metrics["tracking_error_fraction"])/self.limit


from .additional import ColumnHydraulicsDiagnostic, SteamTrapDiagnostic, ChillerPerformanceDiagnostic
from .heat_pump import HeatPumpPerformanceDiagnostic


DIAGNOSTICS = {d.kind: d for d in (MassBalanceDiagnostic, BoilerBalanceDiagnostic,
                HeatExchangerDiagnostic, HydraulicResistanceDiagnostic, VaporizerDiagnostic,
                ROMembraneDiagnostic, ValveTrackingDiagnostic, ColumnHydraulicsDiagnostic,
                SteamTrapDiagnostic, ChillerPerformanceDiagnostic, HeatPumpPerformanceDiagnostic)}


def create_diagnostic(kind, **kwargs):
    if kind not in DIAGNOSTICS:
        raise ValueError(f"unknown diagnostic {kind!r}; choose {sorted(DIAGNOSTICS)}")
    return DIAGNOSTICS[kind](**kwargs)
