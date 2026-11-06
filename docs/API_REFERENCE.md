# Python API reference

Generated from the shipped source by `python scripts/prepare_public_documentation.py`.
Constructor signatures are authoritative for names and defaults. Common `**kwargs` are
`persistence_s=0.0`, `max_gap_s=60.0`, `allowed_modes=None` for Diagnostic subclasses.
`channels` maps semantic roles to SensorBatch column names; a role is not a CSV column position.
Role declarations below are source expressions: conditional branches must also be read.
All scoring methods return DiagnosticResult unless a helper explicitly returns arrays/dicts.

## `SensorBatch`

```python
SensorBatch(time_s: 'np.ndarray', values: 'np.ndarray', channels: 'tuple[str, ...]', units: 'tuple[str, ...]', clock_id: 'str', asset_id: 'str', origin: 'str', valid: 'np.ndarray | None' = None, episodes: 'np.ndarray | None' = None, modes: 'np.ndarray | None' = None, metadata: 'dict[str, Any]' = <factory>) -> None
```

Source: [src/equipment_diagnostics/contracts.py](../src/equipment_diagnostics/contracts.py) (definition line 31).

SensorBatch(time_s: 'np.ndarray', values: 'np.ndarray', channels: 'tuple[str, ...]', units: 'tuple[str, ...]', clock_id: 'str', asset_id: 'str', origin: 'str', valid: 'np.ndarray | None' = None, episodes: 'np.ndarray | None' = None, modes: 'np.ndarray | None' = None, metadata: 'dict[str, Any]' = <factory>)


## `DiagnosticResult`

```python
DiagnosticResult(detector: 'str', time_s: 'np.ndarray', scores: 'np.ndarray', valid: 'np.ndarray', alarms: 'np.ndarray', states: 'tuple[str, ...]', reasons: 'tuple[str, ...]', metrics: 'dict[str, np.ndarray]', metadata: 'dict[str, Any]') -> None
```

Source: [src/equipment_diagnostics/contracts.py](../src/equipment_diagnostics/contracts.py) (definition line 116).

DiagnosticResult(detector: 'str', time_s: 'np.ndarray', scores: 'np.ndarray', valid: 'np.ndarray', alarms: 'np.ndarray', states: 'tuple[str, ...]', reasons: 'tuple[str, ...]', metrics: 'dict[str, np.ndarray]', metadata: 'dict[str, Any]')


## `MassBalanceDiagnostic`

```python
MassBalanceDiagnostic(channels, *, loss_limit_kg_s, window_s=60.0, inventory_error_bound_kg=0.0, inflow_error_bound_kg_s=0.0, outflow_error_bound_kg_s=0.0, known_loss_error_bound_kg_s=0.0, **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 7).

Estimate positive unexplained loss over a causal inventory window.

Map inventory_mass [kg], inflow/outflow [kg/s] and optional known_loss
[kg/s]. Configure an engineering loss limit, window and sensor bounds.
Metrics contain loss, mean net flow and inventory change [kg/s]. This is
boundary accounting, not leak localization. See docs/MODEL_GUIDE.md.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {'inventory_mass': 'kg', 'inflow': 'kg/s', 'outflow': 'kg/s'}, {'known_loss': 'kg/s'})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `BoilerBalanceDiagnostic`

```python
BoilerBalanceDiagnostic(channels, *, loss_limit_kg_s, window_s=60.0, inventory_error_bound_kg=0.0, inflow_error_bound_kg_s=0.0, outflow_error_bound_kg_s=0.0, known_loss_error_bound_kg_s=0.0, **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 93).

Inventory must include steam/water accumulation from a qualified estimator.

Drum level alone is deliberately not converted to total inventory here.
Map steam to outflow and measured blowdown to known_loss.

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `HeatExchangerDiagnostic`

```python
HeatExchangerDiagnostic(channels, *, cp_hot_j_kg_k, cp_cold_j_kg_k, degradation_limit_fraction=0.2, max_energy_imbalance_fraction=0.15, min_lmtd_k=0.5, max_inlet_rate_k_s=0.05, reference_mode='constant', hot_flow_exponent=0.8, cold_flow_exponent=0.8, max_flow_change_fraction_s=None, **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 102).

Monitor single-phase, quasi-steady counterflow heat transfer.

Four temperatures [K], two mass flows [kg/s] and declared cp values give
heat duties [W], LMTD [K] and UA [W/K]. Normal references can compensate
flow-dependent resistance. Heat-balance validity is separate from alarm
scoring; neither an alarm nor a UA decline identifies foulant chemistry.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {'hot_in': 'K', 'hot_out': 'K', 'cold_in': 'K', 'cold_out': 'K', 'hot_flow': 'kg/s', 'cold_flow': 'kg/s'})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `HydraulicResistanceDiagnostic`

```python
HydraulicResistanceDiagnostic(channels, *, reference_flow_m3_s=None, flow_exponent=None, reference_density_kg_m3=1000.0, density_exponent=1.0, growth_limit_fraction=0.25, normalization_mode='power', reference_viscosity_pa_s=0.001, flow_input='volume', **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 216).

Detect increased pressure loss after declared flow/property correction.

Input dp [Pa] and volume flow [m3/s] or a dimensionless flow ratio. Optional
density [kg/m3] and viscosity [Pa*s] support explicitly chosen models.
The geometry and phase regime must remain applicable; zero flow cannot
be normalized. This one-sided detector does not qualify bypass/leakage.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {'pressure_drop': 'Pa', flow_role: 'm3/s' if self.flow_input == 'volume' else '1'}, {'density': 'kg/m3', **({'viscosity': 'Pa*s'} if self.normalization_mode == 'mixed' else {})})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `VaporizerDiagnostic`

```python
VaporizerDiagnostic(channels, *, shortfall_limit_k, minimum_outlet_k=None, prediction_mode='external', **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 309).

Compare outlet temperature with a prediction or a declared low limit.

Outlet/predicted temperatures use K and mass flow uses kg/s. Optional
enthalpies require a shared J/kg basis. Metrics describe temperature
shortfall and optional duty, not measured vapor quality or frost cause.
minimum_only deliberately needs no predicted-temperature sensor role.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {'outlet_temperature': 'K', 'mass_flow': 'kg/s', **({'predicted_temperature': 'K'} if self.prediction_mode == 'external' else {})}, {'inlet_enthalpy': 'J/kg', 'outlet_enthalpy': 'J/kg'})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `ROMembraneDiagnostic`

```python
ROMembraneDiagnostic(channels, *, membrane_area_m2, decline_limit_fraction=0.15, input_mode='corrected', activation_energy_j_mol=None, reference_temperature_k=298.15, temperature_range_k=None, **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 355).

Monitor reference-temperature permeability, not foulant identity.

Qp [m3/s], area [m2], positive NDP [Pa] and TCF=A_ref/A(T) give
Qp*TCF/(area*NDP) [m/(Pa*s)]. The raw-input correction path requires
pressure ordering, osmotic pressures and explicit qualified temperature
parameters; do not repair inconsistent sensor tags by guessing offsets.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, RO_UNITS)
self._columns(batch, {'permeate_flow': 'm3/s', 'net_driving_pressure': 'Pa', 'temperature_correction': '1'})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `ValveTrackingDiagnostic`

```python
ValveTrackingDiagnostic(channels, *, error_limit_fraction, delay_s=0.0, response_time_s=0.0, response_warmup_s=None, **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 412).

Compare normalized command and observed position in the same clock.

Both roles use fractions [1], not percent. A causal delay or declared
first-order normal response produces expected position; engineering
error limits and elapsed persistence produce the alarm. Tracking error
alone does not establish stiction or a particular actuator root cause.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {'command': '1', 'position': '1'})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `create_diagnostic`

```python
create_diagnostic(kind, **kwargs)
```

Source: [src/equipment_diagnostics/diagnostics.py](../src/equipment_diagnostics/diagnostics.py) (definition line 480).

See module guide and source.

## `ColumnHydraulicsDiagnostic`

```python
ColumnHydraulicsDiagnostic(channels, *, reference_vapor_flow_kg_s, reference_liquid_flow_kg_s, vapor_exponent=None, liquid_exponent=None, growth_limit_fraction=0.3, reference_mode='declared_power', **kwargs)
```

Source: [src/equipment_diagnostics/additional.py](../src/equipment_diagnostics/additional.py) (definition line 7).

Compare column dp [Pa] with a normal internal-load power relation.

Vapor/liquid inputs are internal mass flows [kg/s]. Learned or declared
exponents are empirical normal compensation, not a flooding correlation.
Feed flow cannot silently stand in for unknown internal circulation.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {'pressure_drop': 'Pa', 'vapor_flow': 'kg/s', 'liquid_flow': 'kg/s'})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `SteamTrapDiagnostic`

```python
SteamTrapDiagnostic(channels, *, acoustic_quiet_max, acoustic_loud_min, cold_margin_k, hot_margin_k, startup_exclusion_s=0.0, **kwargs)
```

Source: [src/equipment_diagnostics/additional.py](../src/equipment_diagnostics/additional.py) (definition line 82).

Apply site-configured temperature/acoustic patterns during supply.

Steam/trap temperatures use K; acoustic_level and supply_on use 1.
Acoustic normalization and quiet/loud thresholds belong to the caller.
Warmup exclusion also delays fault decisions. No steam-leak mass rate
or independently qualified condensate-versus-steam classifier is implied.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {'steam_temperature': 'K', 'trap_temperature': 'K', 'acoustic_level': '1', 'supply_on': '1'})
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `ChillerPerformanceDiagnostic`

```python
ChillerPerformanceDiagnostic(channels, *, water_cp_j_kg_k=4180.0, cop_decline_limit_fraction=0.2, approach_increase_limit_k=3.0, enforce_isothermal_carnot_bound=False, reference_mode='constant', regression_degree=2, ridge_alpha=0.01, fractional_residual_floor=0.02, approach_residual_floor_k=0.2, diagnostic_stage=0, ewma_tau_s=60.0, ewma_warmup_s=180.0, auxiliary_conditioning='water', **kwargs)
```

Source: [src/equipment_diagnostics/additional.py](../src/equipment_diagnostics/additional.py) (definition line 134).

Compute water-side cooling COP and normal performance deviations.

Base roles include five temperatures [K], chilled flow [kg/s] and
electrical power [W]. Conditioned/auxiliary stages require additional
explicit roles; inspect the constructor and stage validation logic.
Additional-stage research candidates have high false alarms and are
not promoted to default fault-specific alarms by being implemented.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, required)
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `calibrate(self, normal_batch, *, quantile=0.99, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `StreamingDiagnostic`

```python
StreamingDiagnostic(diagnostic, *, max_history_samples=10000)
```

Source: [src/equipment_diagnostics/streaming.py](../src/equipment_diagnostics/streaming.py) (definition line 13).

See module guide and source.

- `push(self, batch)`
- `reset(self)`

## `list_diagnostics`

```python
list_diagnostics()
```

Source: [src/equipment_diagnostics/catalog.py](../src/equipment_diagnostics/catalog.py) (definition line 20).

See module guide and source.

## `HeatPumpPerformanceDiagnostic`

```python
HeatPumpPerformanceDiagnostic(channels, *, reference_mode='constant', ridge_alpha=0.001, log_residual_floor=0.02, temperature_residual_floor_k=0.2, feature_set='cycle', calibration_scope='pooled', evaporator_directional=False, **kwargs)
```

Source: [src/equipment_diagnostics/heat_pump.py](../src/equipment_diagnostics/heat_pump.py) (definition line 35).

Monitor refrigerant-side heating behavior under observed heat demand.

Input condenser duty/power/demand [W], four temperatures [K], refrigerant
mass flow [kg/s] and shaft speed [1/s]. Output heating COP, temperature
differences, mass/revolution and normal residuals. Normal fit and separate
calibration are caller-selected; this is not a flow-fault classifier.
The latest weak-fault response branch is a separate Python model profile.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(condenser_duty='W', electric_power='W', evaporating_temperature='K', condensing_temperature='K', liquid_line_temperature='K', discharge_temperature='K', refrigerant_mass_flow='kg/s', compressor_speed='1/s', heat_demand='W'))
```

- `fit(self, normal_batch, *, minimum_samples=20)`
- `calibrate(self, normal_batch, *, quantile=0.99, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `FilterServiceRiskModel`

```python
FilterServiceRiskModel(channels, *, horizon_s=30.0, window_s=10.0, ridge_alpha=0.01, **kwargs)
```

Source: [src/equipment_diagnostics/filter_risk.py](../src/equipment_diagnostics/filter_risk.py) (definition line 6).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(pressure_drop='Pa', flow_ratio='1'), dict(dust_feed_ratio='1', dust_class='1'))
```

- `fit(self, batch, remaining_life_s, *, minimum_samples=20)`
- `calibrate(self, batch, remaining_life_s, *, negative_quantile=0.95)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `FilterRiskClassifier`

```python
FilterRiskClassifier(channels, *, n_estimators=128, min_samples_leaf=30, max_depth=12, random_state=42, calibration_scope='pooled', feature_set='basic', **kwargs)
```

Source: [src/equipment_diagnostics/filter_classifier.py](../src/equipment_diagnostics/filter_classifier.py) (definition line 7).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(pressure_drop='Pa', flow_ratio='1'), dict(dust_feed_ratio='1', dust_class='1'))
```

- `fit(self, batch, remaining_life_s, *, minimum_samples=20)`
- `calibrate(self, batch, remaining_life_s, *, negative_quantile=0.95)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `TemporalEvidenceDiagnostic`

```python
TemporalEvidenceDiagnostic(channels, *, time_constant_s=20.0, drift_quantile=0.8, minimum_evidence_s=10.0, **kwargs)
```

Source: [src/equipment_diagnostics/temporal_evidence.py](../src/equipment_diagnostics/temporal_evidence.py) (definition line 6).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(indication_score='1', heat_demand='W'))
```

- `fit(self, batch, *, minimum_samples=20)`
- `calibrate(self, batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `FilterBoostedRiskClassifier`

```python
FilterBoostedRiskClassifier(channels, *, n_estimators=150, min_samples_leaf=30, max_depth=6, random_state=42, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0, balance_trials=False, **kwargs)
```

Source: [src/equipment_diagnostics/boosted_filter.py](../src/equipment_diagnostics/boosted_filter.py) (definition line 8).

See module guide and source.

- `fit(self, batch, remaining_life_s, *, minimum_samples=20)`
- `calibrate(self, batch, remaining_life_s, *, negative_quantile=0.95)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `ResidualCoherenceDiagnostic`

```python
ResidualCoherenceDiagnostic(channels, *, shrinkage=0.1, **kwargs)
```

Source: [src/equipment_diagnostics/residual_coherence.py](../src/equipment_diagnostics/residual_coherence.py) (definition line 6).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {**{k: '1' for k in self.ROLES}, 'heat_demand': 'W'})
```

- `fit(self, batch, *, minimum_samples=20)`
- `calibrate(self, batch, *, quantile=0.99, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `FilterBoostedLifeModel`

```python
FilterBoostedLifeModel(channels, **kwargs)
```

Source: [src/equipment_diagnostics/boosted_filter.py](../src/equipment_diagnostics/boosted_filter.py) (definition line 100).

Log remaining-service-life regression, equalized by training trial.

- `fit(self, batch, remaining_life_s, *, minimum_samples=20)`
- `calibrate(self, batch, remaining_life_s, *, negative_quantile=0.95)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `HysteresisAlarmDiagnostic`

```python
HysteresisAlarmDiagnostic(channels, *, on_threshold=1.0, confirmation_s=2.0, release_ratio=0.25, release_s=5.0, **kwargs)
```

Source: [src/equipment_diagnostics/alarm_hysteresis.py](../src/equipment_diagnostics/alarm_hysteresis.py) (definition line 7).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(indication_score='1'))
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `FilterRiskEnsemble`

```python
FilterRiskEnsemble(channels, *, booster_weight=0.75, aggregation='arithmetic', **kwargs)
```

Source: [src/equipment_diagnostics/filter_ensemble.py](../src/equipment_diagnostics/filter_ensemble.py) (definition line 9).

See module guide and source.

- `fit(self, batch, remaining_life_s, *, minimum_samples=20)`
- `calibrate(self, batch, remaining_life_s, *, negative_quantile=0.95)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `calibrated_level`

```python
calibrated_level(batch, channel, *, slope_m_v, offset_m, qualified_voltage_range_v, output='level_m')
```

Source: [src/equipment_diagnostics/physical_inputs.py](../src/equipment_diagnostics/physical_inputs.py) (definition line 24).

Linear pressure-transducer calibration; extrapolation is invalid, never clipped.

## `causal_asof`

```python
causal_asof(source, target, *, max_age_s)
```

Source: [src/equipment_diagnostics/physical_inputs.py](../src/equipment_diagnostics/physical_inputs.py) (definition line 40).

Last observation available on the same declared clock, episode and mode.

Source timestamps must denote availability, not an uncorrected sensor clock.
No forward interpolation, carry across gaps, clock conversion or unit inference.

## `moist_air_exchange`

```python
moist_air_exchange(dry_air_flow_kg_s, inlet_temperature_k, outlet_temperature_k, inlet_humidity_kg_kg, outlet_humidity_kg_kg)
```

Source: [src/equipment_diagnostics/physical_inputs.py](../src/equipment_diagnostics/physical_inputs.py) (definition line 60).

ASHRAE-style ideal moist-air enthalpy balance, per kg dry air.

h=1006*T_C + w*(2501000+1860*T_C) J/kg_da. The moisture removal
rate is not a validated frost-growth rate: liquid drainage and frost enthalpy
are not measured here. No dry two-sided UA or brine flow is manufactured.

## `horizontal_cylinder_liquid_volume`

```python
horizontal_cylinder_liquid_volume(level_m, *, radius_m, length_m)
```

Source: [src/equipment_diagnostics/physical_inputs.py](../src/equipment_diagnostics/physical_inputs.py) (definition line 83).

Circular segment volume; flat heads only. Invalid levels return NaN.

## `SaturatedBoilerInventory`

```python
SaturatedBoilerInventory(*, radius_m, length_m, circuit_volumes_m3)
```

Source: [src/equipment_diagnostics/physical_inputs.py](../src/equipment_diagnostics/physical_inputs.py) (definition line 101).

Configured equilibrium inventory, NOT an unobserved swell/void estimator.

Pressure must be absolute Pa. Level is geometric height from drum bottom,
not raw DP or indicated percent. Every connected circuit volume and its
measured/externally estimated vapor void fraction must be supplied.

- `transform(self, batch, *, pressure_channel, level_channel, void_channels, output='inventory_kg')`

## `PiecewiseVaporizer`

```python
PiecewiseVaporizer(*, saturation_temperature_k, latent_heat_j_kg, liquid_cp_j_kg_k, vapor_cp_j_kg_k, ua_w_k, property_basis_id)
```

Source: [src/equipment_diagnostics/physical_inputs.py](../src/equipment_diagnostics/physical_inputs.py) (definition line 144).

Steady isobaric preheat/boil/superheat against a constant-temperature source.

Qualified constant cp, latent heat and saturation temperature are supplied
by the caller for ONE fluid/pressure. Enthalpy is relative to saturated liquid.
UA includes all thermal resistances. No pressure drop, icing dynamics,
multicomponent glide or source cooling is inferred.

- `transform(self, batch, *, mass_flow_channel, inlet_enthalpy_channel, source_temperature_channel, output='predicted_outlet_k')`
- `predict(self, mass_flow_kg_s, inlet_relative_enthalpy_j_kg, source_temperature_k)`

## `WetCoilAirsideDiagnostic`

```python
WetCoilAirsideDiagnostic(channels, *, reference_volume_flow_m3_s, reference_density_kg_m3=1.2, flow_exponent=2.0, restriction_growth_limit_fraction=0.25, **kwargs)
```

Source: [src/equipment_diagnostics/wet_coil.py](../src/equipment_diagnostics/wet_coil.py) (definition line 8).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(pressure_drop='Pa', volume_flow='m3/s', dry_air_flow='kg/s', inlet_temperature='K', outlet_temperature='K', inlet_humidity='1', outlet_humidity='1'))
```

- `fit(self, normal_batch, *, minimum_samples=10)`
- `calibrate(self, normal_batch, *, quantile=0.99)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `LoadConditionedPressureDiagnostic`

```python
LoadConditionedPressureDiagnostic(channels, *, conditioned=True, growth_limit_fraction=0.25, minimum_excess_pa=10.0, ridge_alpha=0.001, **kwargs)
```

Source: [src/equipment_diagnostics/pressure_context.py](../src/equipment_diagnostics/pressure_context.py) (definition line 8).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(pressure_drop='Pa', shaft_power='W', engine_speed='1/s'))
```

- `fit(self, normal_batch, *, minimum_samples=20)`
- `calibrate(self, normal_batch, *, quantile=0.99)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `SignedResidualCUSUM`

```python
SignedResidualCUSUM(channels, *, context_unit='1', reference_step_s=1.0, drift_sigma=0.25, scale_floor=0.05, minimum_limit=5.0, prewhiten=False, **kwargs)
```

Source: [src/equipment_diagnostics/signed_cusum.py](../src/equipment_diagnostics/signed_cusum.py) (definition line 13).

See module guide and source.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(signal='1', context=self.context_unit))
self._columns(batch, dict(signal='1', context=self.context_unit))
```

- `fit(self, batch, *, minimum_samples=20)`
- `calibrate(self, batch, *, block_s=None, horizon_s=3600.0, replicates=256, quantile=0.99, seed=20261106)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `evaporator_conductance_proxy`

```python
evaporator_conductance_proxy(condenser_duty_w, electric_power_w, evaporating_temperature_k, source_inlet_temperature_k)
```

Source: [src/equipment_diagnostics/heat_pump.py](../src/equipment_diagnostics/heat_pump.py) (definition line 19).

Approximate (Qcond-W)/(Tsource,in-Tevap), W/K; not a measured UA.

Neglects compressor/environmental losses and thermal storage, and uses the
SOURCE INLET instead of unknown LMTD. Caller must identify measured versus
assumed source temperatures. Cannot isolate flow reduction from fouling.

## `ConditionalResidualDiagnostic`

```python
ConditionalResidualDiagnostic(channels, *, features, targets, degree=1, ridge_alpha=0.01, window_s=0.0, minimum_z=3.0, calibration_role=None, feature_order=None, target_order=None, **kwargs)
```

Source: [src/equipment_diagnostics/conditional_residual.py](../src/equipment_diagnostics/conditional_residual.py) (definition line 8).

Predict normal responses from explicit observed operating features.

Every feature/target specifies its unit and log transform. Targets add
direction and scale_floor; preserve feature_order and target_order in
configuration and saved references. Fit normal regression, calibrate on
separate normal data, then freeze before evaluation. observed/expected
metrics remain in transformed space, not necessarily physical units.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, {k: s['unit'] for k, s in specs.items()})
```

- `fit(self, batch, *, minimum_samples=20)`
- `calibrate(self, batch, *, quantile=0.999)`
- `score(self, batch)`
- `set_reference(self, reference)`

## `WindowChangeDiagnostic`

```python
WindowChangeDiagnostic(channels, *, mean_window_s=60.0, lags_s=(60.0, 300.0, 900.0), minimum_change=np.float64(0.048790164169432), **kwargs)
```

Source: [src/equipment_diagnostics/window_change.py](../src/equipment_diagnostics/window_change.py) (definition line 7).

Compare causal residual means with earlier observed windows.

The signal is a signed dimensionless upstream residual whose basis must
be preserved. Window/lag values use seconds. Constant offsets cancel;
invalid observations and episode/context changes reset history. Faster
engine-filter candidates raised false alarms and were not adopted.

Sensor role and unit declarations (conditional alternatives may apply):

```python
self._columns(batch, dict(signal='1'))
```

- `fit(self, batch, *, minimum_samples=20)`
- `calibrate(self, batch, *, quantile=0.9999)`
- `score(self, batch)`
- `set_reference(self, reference)`
