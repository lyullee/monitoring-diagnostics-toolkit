# Monitoring Diagnostics Toolkit

**Equipment-specific monitoring from temperature, pressure, flow, inventory and position sensors.**
Use independent Python modules to calculate mass and heat balances, hydraulic resistance,
membrane permeability, normal-performance residuals and causal alarms. Every diagnostic
returns its calculated quantities, validity, decision reasons and provenance alongside its score.

[Korean README](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/README.ko.md) ·
[User guide](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/USER_GUIDE.md) ·
[API reference](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/API_REFERENCE.md) ·
[Model equations](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/MODEL_GUIDE.md)

**Research alpha.** Software verification is separate from measured fault validation.
An alarm is neither a fault probability nor a confirmed root cause. The latest weak
heat-pump detection gain depends on a 0.3 K condensing-temperature difference between
sessions; its specificity to evaporator flow reduction remains unproven.

| Item | Value |
| --- | --- |
| Distribution | `monitoring-diagnostics-toolkit` |
| Python import / CLI | `equipment_diagnostics` / `equipment-diagnose` |
| Python / core dependency | Python 3.11+ / NumPy |
| Release | 0.17.1: English README and release-documentation update; no diagnostic-logic change |
| Latest measured development study | 0.16.0; reused evaluation, with limitations retained below |
| Original code and documentation | [MIT](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/LICENSE); external materials keep [separate rights](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/THIRD_PARTY_NOTICES.md) |
| Complete signatures and defaults | [API_REFERENCE.md](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/API_REFERENCE.md) / [API_CATALOG.json](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/API_CATALOG.json) |

## Equipment modules: purpose, inputs, parameters and outputs

Names below are **semantic sensor roles**, mapped to actual column names using
`channels={role: column_name}`. A question mark marks an optional sensor. All diagnostics
return the common `DiagnosticResult` described below. Consult the API reference for exact
constructor names, defaults and conditional sensor requirements.

| Kind / Python class | Purpose and deviation monitored | Sensor inputs and units | Main parameters | Calculated outputs and limits |
| --- | --- | --- | --- | --- |
| `mass_balance` / `MassBalanceDiagnostic` | Unexplained tank mass loss | `inventory_mass` kg; `inflow`, `outflow` kg/s; `known_loss`? kg/s | `loss_limit_kg_s`, `window_s`, inventory/flow error bounds | Window-average loss, mean net flow and inventory-change rate in kg/s; optional loss bounds. No leak localization or cause identification |
| `boiler_mass_balance` / `BoilerBalanceDiagnostic` | Boiler feed, discharge and total-inventory accounting | **Total steam plus water inventory** kg; feed/steam kg/s; known blowdown? kg/s | Same balance/window/error parameters as the tank model | Unexplained loss kg/s. Drum level alone cannot replace total inventory |
| `heat_exchanger` / `HeatExchangerDiagnostic` | Heat-transfer performance decline | `hot_in`, `hot_out`, `cold_in`, `cold_out` K; `hot_flow`, `cold_flow` kg/s | `cp_hot_j_kg_k`, `cp_cold_j_kg_k`, degradation limit, constant or flow-resistance normal reference | Duties W, heat imbalance, LMTD K, UA W/K. Single-phase, quasi-steady counterflow with declared cp |
| `hydraulic_resistance` / `HydraulicResistanceDiagnostic` | Increased filter/piping resistance | `pressure_drop` Pa; `volume_flow` m3/s or `flow_ratio` 1; `density`? kg/m3, `viscosity`? Pa*s | Reference flow/density, declared exponents or mixed viscous/inertial normalization, growth limit | Normalized pressure drop Pa and resistance indication. Fixed geometry, single phase; zero flow cannot be normalized |
| `vaporizer` / `VaporizerDiagnostic` | Low outlet temperature or prediction shortfall | `outlet_temperature` K, `mass_flow` kg/s; `predicted_temperature` K in prediction mode; optional enthalpies J/kg | `shortfall_limit_k`, `minimum_outlet_k`, `prediction_mode` | Temperature shortfall K, low-limit indication, optional duty W. Does not identify frost or establish outlet dryness |
| `ro_membrane` / `ROMembraneDiagnostic` | Reference-temperature permeability decline | `permeate_flow` m3/s, `net_driving_pressure` Pa, `temperature_correction` 1; alternatively raw pressure/osmotic-pressure/temperature roles | `membrane_area_m2`, decline limit, qualified temperature-correction parameters/range | Permeability m/(Pa*s). Pressure order and TCF convention matter; no foulant classification |
| `valve_tracking` / `ValveTrackingDiagnostic` | Command-to-position tracking error | `command`, `position`: fractions 0–1, unit `1` | `error_limit_fraction`, `delay_s`, optional first-order response time | Expected position and tracking error. Does not infer unmeasured position or prove stiction |
| `column_hydraulics` / `ColumnHydraulicsDiagnostic` | Column pressure rise relative to internal load | `pressure_drop` Pa; internal `vapor_flow`, `liquid_flow` kg/s | Reference internal flows, declared/learned power exponents, growth limit | Load-normalized pressure drop Pa. Feed flow is not a substitute for internal circulation; no validated flooding forecast |
| `steam_trap` / `SteamTrapDiagnostic` | Cold/quiet or hot/loud patterns while supply is on | `steam_temperature`, `trap_temperature` K; `acoustic_level`, `supply_on` 1 | Site acoustic thresholds, temperature margins K, startup exclusion s | Temperature deficit K and pattern scores. Condensate discharge versus live steam loss is not independently qualified |
| `chiller_performance` / `ChillerPerformanceDiagnostic` | Cooling performance and condition-dependent residuals | `chilled_in`, `chilled_out`, `cooling_out`, `evaporating_temperature`, `condensing_temperature` K; `chilled_flow` kg/s, `electric_power` W; additional sensors for conditioned/staged modes | cp, reference mode, regression/residual settings; staged oil/refrigerant/condenser inputs | Cooling duty W, cooling COP, approaches K and residuals. Additional stages were rejected as default alarms because of high false-alarm rates |
| `heat_pump_performance` / `HeatPumpPerformanceDiagnostic` | Refrigerant-side heating deviations | `condenser_duty`, `electric_power`, `heat_demand` W; `evaporating_temperature`, `condensing_temperature`, `liquid_line_temperature`, `discharge_temperature` K; `refrigerant_mass_flow` kg/s, `compressor_speed` 1/s | Load-conditioned reference, cycle/extended features, separate normal calibration | Heating COP, subcooling/discharge superheat K, mass per revolution kg and residuals. Separate from the water-side chiller model |

Common alarm options are `persistence_s`, `max_gap_s` and `allowed_modes`.
An optional `operating` role, unit `1`, restricts decisions to observations equal to 1.
Default thresholds are not site qualification. Models requiring a reference must be fitted
on caller-confirmed normal data or restored with `set_reference`.

### Conditional sensor paths

| Mode | Additional exact roles and units |
| --- | --- |
| RO `input_mode="pressures_temperature"` | `permeate_flow` m3/s; `feed_pressure`, `concentrate_pressure`, `permeate_pressure`, `feed_osmotic_pressure`, `concentrate_osmotic_pressure`, `permeate_osmotic_pressure` Pa; `membrane_temperature` K. Declare activation energy, reference temperature and qualified temperature range |
| Chiller `reference_mode="conditioned"` | Base chiller roles plus `cooling_in` K |
| Chiller nonzero `diagnostic_stage` | `oil_sump_temperature`, `oil_feed_temperature` K; `oil_feed_pressure`, `oil_net_pressure` Pa; `subcooling`, `suction_superheat`, `discharge_superheat` K |
| Chiller stage 3 | Above roles plus `cooling_flow` kg/s |

Oil feed pressure and net oil differential pressure have different meanings. Acoustic
normalization, nominal heat demand, fluid properties and sensor calibration must have
an explicit basis; the toolkit does not invent missing measurements.

## Additional Python modules

These APIs are available from `equipment_diagnostics`; they are **not automatically
registered among the 11 CLI kinds**. Training the supervised filter models requires the
optional `learning` dependencies. No corpus-trained model is distributed.

| API | Purpose | Inputs and fitting information | Outputs and applicability |
| --- | --- | --- | --- |
| `LoadConditionedPressureDiagnostic` | Engine-filter pressure corrected for load/speed | `pressure_drop` Pa, `shaft_power` W, `engine_speed` 1/s; normal fit/calibration | Expected/excess pressure and score. Not measured-airflow resistance or RUL |
| `WetCoilAirsideDiagnostic` | Wet/frosting-coil air-side monitoring | DP Pa, volume flow m3/s, dry-air flow kg/s, inlet/outlet K and humidity ratio 1 | Duty W, moisture removal kg/s, density and normalized DP. Measured fouling detection remained weak |
| `FilterServiceRiskModel` | Regression toward a future service endpoint | DP Pa, flow ratio 1, separate remaining-life labels s | Estimated service life and risk; not present-clog truth |
| `FilterRiskClassifier` | Classify proximity to service limit | Above inputs plus optional dust-feed ratio/material code 1 and life labels s | Tree votes and calibrated risk |
| `FilterBoostedRiskClassifier`, `FilterBoostedLifeModel`, `FilterRiskEnsemble` | Boosting/ensemble research candidates | Corresponding filter inputs, labels and model settings | Risk/life and prediction disagreement. Latest comparison candidates were not adopted |
| `TemporalEvidenceDiagnostic` | EWMA/CUSUM accumulation | `indication_score` 1, `heat_demand` W; normal fit/calibration | Load-specific accumulated evidence; upstream score provenance remains necessary |
| `ResidualCoherenceDiagnostic` | Joint residual changes | `evaporator_residual`, `power_residual`, `speed_residual`, `cop_residual` 1; `heat_demand` W | Directional distance from normal covariance, not root-cause classification |
| `SignedResidualCUSUM` | Accumulate small positive signed deviations | `signal` 1, `context` 1 or W | Time-weighted CUSUM, empirical normal-block limit, optional AR1 prediction error |
| `ConditionalResidualDiagnostic` | Predict normal responses from operating features | Explicit feature/target units, log transforms, target directions/scale floors and fixed order | Expected responses, standardized residuals and trailing means. With logs, observed/expected metrics are in transformed space |
| `WindowChangeDiagnostic` | Growth between past residual windows | `signal` 1; mean window/lags s and minimum change | Causal change score. Constant offsets cancel; faster engine candidates raised false alarms and were rejected |
| `HysteresisAlarmDiagnostic` | Confirmation and delayed alarm release | Upstream score 1, on/off ratios, confirmation/release s | Alarm state. Holding an alarm is not improved raw detection |
| `StreamingDiagnostic` | Causal replay of successive chunks | Diagnostic object, nonoverlapping batches, history-sample limit | `push(batch)` returns a diagnostic result. Full-history models fail explicitly at the cap |
| `calibrated_level` | Convert calibrated voltage to level | Voltage V, slope m/V, offset m, qualified voltage range | Batch with level m; out-of-range observations are invalid |
| `causal_asof` | Align different sampling intervals | Batches with compatible asset/origin/clock/episode/mode, maximum age s | Latest observation at or before the target time; no future samples |
| `moist_air_exchange` | Moist-air heat/moisture balance | Dry-air kg/s, inlet/outlet K and humidity ratios 1 | Duty W, moisture kg/s and validity |
| `horizontal_cylinder_liquid_volume` | Part-filled horizontal cylinder | Level, radius and length m; flat ends | Liquid volume m3 |
| `SaturatedBoilerInventory` | Inventory from declared geometry/state | Geometry m/m3, absolute pressure Pa, geometric level m, external circuit void fractions 1; CoolProp | Total water plus steam kg. No void-fraction or shrink/swell observer |
| `PiecewiseVaporizer` | Steady preheat/boil/superheat prediction | Mass flow kg/s, relative enthalpy J/kg, source K; saturation K, latent heat J/kg, cp, UA W/K and basis ID | Outlet K, enthalpy J/kg, duty W and modeled vapor fraction; fixed pressure/properties/source |
| `evaporator_conductance_proxy` | Approximate evaporator heat-transfer indication | Condenser duty/power W, evaporating/source-inlet K | `(Qcond-W)/(Tsource,in-Tevap)` W/K; not measured UA or inferred water flow |

## Installation and quick start

```bash
python -m pip install monitoring-diagnostics-toolkit
equipment-diagnose list --details
```

From a source checkout:

```bash
python -m pip install -e ".[dev]"
# Install only the optional groups you need:
python -m pip install -e ".[learning,physics,public-data]"
```

The distribution was renamed for public release. The import namespace, CLI and
`equipment-diagnostics.*` JSON identifiers retain their existing compatibility names.
External datasets and related project checkouts are not included in the installation.

### Minimal Python example: vaporizer outlet low limit

```python
import numpy as np
from equipment_diagnostics import SensorBatch, VaporizerDiagnostic

batch = SensorBatch(
    time_s=np.arange(5.0),
    values=np.column_stack((np.full(5, 270.0), np.full(5, 0.1))),
    channels=("gas_out_k", "flow"), units=("K", "kg/s"),
    clock_id="logger_elapsed_s", asset_id="vaporizer_01", origin="synthetic",
)
monitor = VaporizerDiagnostic(
    {"outlet_temperature": "gas_out_k", "mass_flow": "flow"},
    shortfall_limit_k=5.0, minimum_outlet_k=280.0,
    prediction_mode="minimum_only", persistence_s=2.0,
)
result = monitor.score(batch)
print(list(result.states))
print(result.to_dict()["summary"])
```

### Complete CSV/JSON example without external data

Run from the source checkout. This deterministic synthetic example connects ten
diagnostics; it is not a coupled physical plant or measured validation of all eleven kinds.

```bash
python examples/generate_demo.py --output outputs/demo
equipment-diagnose fit --config outputs/demo/config.json --data outputs/demo/normal.csv --output outputs/demo/reference.json
equipment-diagnose run --config outputs/demo/config.json --data outputs/demo/operation.csv --reference outputs/demo/reference.json --output outputs/demo/report.json
```

`fit` uses data that **the caller has confirmed as normal**. Where a Python API exposes
`calibrate`, use a separate normal calibration batch. The CLI neither verifies health
automatically nor removes fault observations on the caller's behalf.

## Common input and output contract

| `SensorBatch` input | Meaning |
| --- | --- |
| `time_s[n]` | Finite seconds, strictly increasing, one declared clock |
| `values[n,d]`, `channels[d]`, `units[d]` | Measurements, unique column names and explicit units |
| `clock_id`, `asset_id`, `origin` | Clock, equipment and source identity; distinguish measured from synthetic/predicted inputs |
| `valid[n,d]` | Measurement validity; NaN is not healthy operation |
| `episodes[n]`, `modes[n]` | Trial/operating segments; boundaries reset windows and alarm persistence |
| `metadata` | Calibration, enthalpy basis, transformations and other measurement contracts |

Unit strings must match exactly: `K`, `Pa`, `kg/s`, `m3/s`, `W`, `1/s`, `1`, etc.
Convert Celsius to K, kPa to Pa and rpm to 1/s explicitly. Absolute, gauge and
differential pressures are different quantities. Relative humidity is not humidity ratio.

| `DiagnosticResult` output | Meaning |
| --- | --- |
| `scores[n]` | Default decision threshold 1; not a probability. Inspect `score_semantics` |
| `valid[n]`, `states[n]` | Decision validity and `NORMAL`, `PENDING`, `ALARM`, `UNKNOWN` states |
| `alarms[n]` | Alarm after elapsed-time policy; a release-delay model may remain active after its input score falls |
| `reasons[n]` | Missing data, physical bounds, warmup, outside-reference-domain and other decision reasons |
| `metrics` | Model-specific physical quantities and residual arrays |
| `metadata` | Clock/asset/origin, fitted reference, configuration signature, score meaning and `root_cause_confirmed=False` |

`UNKNOWN` is not a healthy negative decision. `PENDING` is valid but has not completed
the configured persistence. Report decision coverage alongside accuracy. Do not relabel
incompatible clocks, assets or origins merely to make an integration accept them.

## Evidence and current applicability

These are recorded development observations, not new validation created by publishing
the package. Detailed denominators, partitions, candidates and limitations are in the
[latest two-target study](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/TWO_TARGET_IMPROVEMENT.md).

| Module | Measured equipment/experiment evidence | Simulation/calculation evidence and remaining problem |
| --- | --- | --- |
| Valve | New factory background: 34 asset-days; alarm segments 362→2, sample FPR 0.000170%; reused 6/6 fault events detected, 14–18 s delay | New independent faults/another factory remain necessary; background is not maintenance-certified healthy |
| Engine filter | Reused single-engine evaluation: accuracy 94.7758%, recall 90.0889%, FPR 0.0294%, coverage 100%, maximum delay 2314 s | Faster candidates raised false alarms and were rejected; independent normal variation/another engine needed |
| Heat pump | Reused new response branch: accuracy 99.7229%, recall 99.6973%, 0 false positives/490 normal samples; eligible coverage 100%, raw coverage 90.16%; weak EF10.1 recall 98.16%, observed delay 30 s | Gain depends on a 0.3 K condensing-temperature session difference. Synthetic ±0.3 K offsets on normal records caused 99.28% alarms. **Flow-fault specificity unvalidated** |
| HSE filter risk | Original Test recall 68.90%, FPR 2.14%; reused later suffix recall 100%, FPR 21.58% | Label means reaching the service endpoint within 30 s, not present blockage or general life assurance |
| Dry exchanger / generic hydraulic resistance | No qualifying measured fouling/blockage truth | Flow compensation and boundary checks; simulated performance is not measured accuracy |
| Wet coil | Recall 5.88%, 0 false positives/75 valid normal samples, coverage 54.96% | Automatic fouling diagnosis not adopted; frost conditions confound interpretation |
| Tank | Measured level calibration reproduced; qualified leak/flow truth insufficient | Error bounds suppress false alarms but reduce small-leak sensitivity |
| RO | Data acquired; pressure-order checks fail and qualifying fault truth is absent | Normalization verified. Pressure tags are not silently swapped or offset to pass checks |
| Vaporizer | No measured fault validation | Low-limit and idealized predictor calculations verified; temperature alone cannot establish two-phase dryness |
| Chiller | Single RP-1043 apparatus, stage 0 recall 34.56%, FPR 0.28% | Auxiliary monitoring only; additional-stage false alarms remain high |
| Column / steam trap / boiler | Applicable independent fault truth not secured | Empirical load correction, trap rules and declared-inventory calculations checked; no completed field fault qualification |

Accuracy=(TP+TN)/(valid labeled samples); recall=TP/(TP+FN); FPR=FP/(FP+TN);
decision coverage=(valid decisions)/(declared target observations). Report raw-data coverage
separately when startup is excluded. Fault-only subsets have no estimable FPR. Time-series
rows are not independent fault events. Delay must name its starting point: the weak-EF
delay above starts at the first eligible positive observation after a fixed exclusion,
not an independently measured physical onset.

Even with disjoint fitting and calibration rows, redesigning a model after inspecting
evaluation outcomes makes the resulting study **reused development evaluation**.
Longer alarm holding and improved raw detection are reported separately.

## Verification and related projects

```bash
python -m pytest
python -m pytest -o addopts="" -m "not integration"
python scripts/verify_physics.py
python scripts/verify_stages.py
```

The second command needs the optional physical-verification dependencies. External
integration checks require separate, pinned project checkouts. The public release records
286 software/physics tests, seven scoped object integrations and Windows/Linux Python 3.11/3.12
CI. Passing tests do not establish universal fault accuracy or certified safety operation.

`equipment_diagnostics.adapters` connects explicit contracts from process-monitoring-toolkit,
h2physics and pipeline-safety-toolkit. See
[pinned revisions](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/UPSTREAM_REVISIONS.json)
and `examples/project_bridge.py`. Object/serialization checks are separate from native-solver
or plant validation. rotorvibe was inspected; no tested adapter to it is claimed here.

## Development history, reproduction and continuation

| Document | What it preserves |
| --- | --- |
| [USER_GUIDE](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/USER_GUIDE.md) | Configuration JSON, CSV, fitting/calibration, reference restoration, streaming and troubleshooting |
| [MODEL_GUIDE](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/MODEL_GUIDE.md) | Equations, assumptions, outputs, references and omitted parts of cited methods |
| [API_REFERENCE](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/API_REFERENCE.md) | Public signatures, defaults, sensor-role declarations and source definitions |
| [DEVELOPMENT_HISTORY](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/DEVELOPMENT_HISTORY.md) | Retrospective milestones, changes, rejected candidates and why decisions were made |
| [DATA_PROVENANCE](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/DATA_PROVENANCE.md) | Dataset origins, labels/units, acquisition scripts, rights and reasons data were unusable |
| [REPRODUCIBILITY](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/REPRODUCIBILITY.md) | Software tests, historical pipelines, split/freeze rules, source-hash constraints and output locations |
| [RESEARCH_HANDOFF](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/RESEARCH_HANDOFF.md) | Selected profiles, unresolved confounding, needed independent data and next priorities |
| [INDEX](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/docs/INDEX.md) | Current documentation and preserved stage-by-stage research reports |

Historical hash audits require the matching source snapshot, data and environment.
Do not overwrite old results with current code while presenting them as an unchanged
historical run. The v0.16 original-code snapshot and selected aggregate audit/protocol
records are preserved in `evidence/`. Excluded local artifacts have a hash-only inventory;
that inventory is not a public raw-data mirror or a complete reproduction bundle.

## Rights and citation

Original code and original documentation are MIT. Raw datasets, downloaded papers,
external source checkouts and fitted corpus profiles are excluded. External materials and
optional dependencies retain their own terms. Scientific model names, equations, citations
and required licence notices remain visible. Rewording text is not copyright clearance.
See [THIRD_PARTY_NOTICES](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/THIRD_PARTY_NOTICES.md)
and [CITATION.cff](https://github.com/lyullee/monitoring-diagnostics-toolkit/blob/main/CITATION.cff).

This is original screening software inspired by identified physical/statistical principles,
not a claim to reproduce every cited paper or a proprietary vendor classifier. Continue
development from the documented failed candidates and evidence gaps, keeping measured
validation, simulation, raw detection and alarm-policy effects distinct.
