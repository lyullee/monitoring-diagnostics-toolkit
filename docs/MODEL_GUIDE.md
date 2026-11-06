# Models, physical assumptions and output interpretation

This companion explains the equations behind the original implementation. A cited
paper supplies context, not automatic equivalence to its full method. Constructor
names/defaults, role declarations and methods are in [API_REFERENCE](API_REFERENCE.md).
Source files contain causal-window, numerical-limit and provenance comments; this
guide supplies the cross-module physical interpretation without hiding the API.

## Balance models

Tank loss over a declared window T is the trapezoidal mean of inflow minus outflow
minus known loss, less the observed inventory change divided by T. The reported
`unaccounted_loss_kg_s` has units kg/s. A positive loss is unexplained material leaving
the boundary, including sensor error. It is not automatically a physical leak.
The bound is `2*inventory_bound/T + inflow_bound + outflow_bound + known_loss_bound`.
The one-sided score uses the lower loss bound divided by the declared loss limit.
More conservative bounds reduce false alarms and can suppress small leaks.

The partial window boundary integrates a piecewise-linear flow and assumes constant
unresolved loss inside an observed interval. Invalid observations, mode/episode changes
and excessive gaps restart the window. Startup is UNKNOWN until a complete window exists.
The boiler model uses the same accounting with **total steam/water inventory**, not
drum level alone. `SaturatedBoilerInventory` combines horizontal-drum geometry and
external circuit void fractions with CoolProp saturation densities. Unknown void fraction
or shrink/swell dynamics are not inferred by the helper.

References: Sun et al., [mass-balance context](https://doi.org/10.1016/S0098-1354(02)00147-3);
Åström and Bell, [drum boiler dynamics](https://doi.org/10.1016/S0005-1098(99)00171-5).
The paper's time-varying estimator and a full boiler observer are not implemented here.

## Heat exchanger, wet coil and vaporizer

Dry counterflow heat exchanger: `Qh=mh*cph*(Thi-Tho)`, `Qc=mc*cpc*(Tco-Tci)`.
`dT1=Thi-Tco`, `dT2=Tho-Tci`; `LMTD=(dT1-dT2)/log(dT1/dT2)`, with a continuous
equal-temperature-difference limit. `UA=(Qh+Qc)/(2*LMTD)` in W/K. Heat imbalance is
`abs(Qh-Qc)/max(abs(Qh),abs(Qc))`. Invalid approach temperatures and excessive imbalance
prevent unsupported UA decisions. Constant cp, single phases and quasi-steady flow
are required. Flow-resistance conditioning fits a nonnegative normal resistance model;
it does not identify fouling chemistry. [Apio et al.](https://doi.org/10.1080/00986445.2023.2202316)
motivates monitoring; the paper's exchanger-network EKF is not reproduced.

Wet coils instead use dry-air moist enthalpy `h=1006*T_C+w*(2501000+1860*T_C)` J/kg dry air.
Air-side duty is dry-air mass flow times inlet-minus-outlet enthalpy; moisture removal
is dry-air flow times humidity-ratio difference. Moist-air density is estimated from
dry-air mass flow, outlet humidity and volume flow. A normalized air-side pressure drop
is monitored. This is not a dry-coil UA or a measured brine-side energy balance.
All reviewed foul/clean runs also involved frost, limiting causal attribution.

Vaporizer diagnosis compares measured outlet temperature with an external prediction
or an explicit minimum. Optional `m*(hout-hin)` needs a common enthalpy basis. The
`PiecewiseVaporizer` helper resolves preheating, boiling and superheat under declared
constant pressure, properties, UA and heat-source temperature. It returns modeled
temperature/enthalpy/duty/vapor fraction. Saturation temperature alone cannot establish
dryness in a two-phase outlet. An ODE comparison checks this idealized model, not
real-fluid plant performance. [Implementation scope](IMPLEMENTATION.md) distinguishes
the cited vaporizer papers from a full HYSYS or frost model.

## Hydraulic resistance and membrane permeability

Power normalization is `dp_ref=dp*(Qref/Q)^n*(rho_ref/rho)^r`. The user declares exponents:
laminar fixed geometry may use n=1,r=0; inertial constant-friction behavior n=2,r=1.
These are assumptions, not automatic Reynolds-regime identification. The mixed option
fits normal viscous and inertial contributions using declared viscosity/density.
Fixed geometry and single-phase flow are required. Zero flow is not normalizable;
zero pressure drop does not imply increased resistance. Leakage/bypass causing a
decrease is outside this one-sided increase detector.

Engine `LoadConditionedPressureDiagnostic` fits quadratic log pressure to log power
and log shaft speed, then tests excess above normal with engineering floors and normal
calibration. There is no measured air flow; this is not pressure/flow resistance or RUL.
Recent ambient-context and window-change candidates were rejected for false alarms.
[Pressure-flow modeling context](https://doi.org/10.5220/0010405401020109) is not a claim
to reproduce every model-selection step in that paper.

RO reference permeability is `Lp_ref=Qp*TCF/(area*NDP)`, units m/(Pa*s).
**TCF=A_ref/A(T)**, the inverse of the ratio used in some other conventions. The optional
raw-input path uses mean feed/concentrate hydraulic and osmotic pressure minus permeate
terms plus explicitly configured temperature correction. Sensor ordering, positive NDP,
membrane-qualified temperature range and parameter basis are checked. Concentration
polarization and foulant type are not independently identified.
[Sanawar et al.](https://doi.org/10.3390/membranes9090117) supplies normalization context.
Measured corpora failed pressure-order quality checks; their availability does not validate
the diagnostic, and pressure tags were not silently swapped.

## Valve, column and steam trap

Valve expected position is a causally delayed command or a configured first-order normal
response. The score is absolute tracking error divided by an engineering fraction limit.
Elapsed-time persistence suppresses short excursions and adds delay. Both command and
position must be normalized 0–1. This does not establish stiction causality or estimate
unmeasured position. [Valve literature](https://doi.org/10.1016/j.jprocont.2009.10.004).

Column normal pressure is an empirical power relation in internal vapor and liquid mass
flow. Declared exponents or normal learned exponents compensate load. Increased pressure
relative to that relation is evidence of a deviation, not a validated flooding forecast.
[Flooding research](https://doi.org/10.1016/j.dche.2023.100098) uses a different full method.

Steam-trap rules combine steam/trap temperature difference and site-normalized acoustic
thresholds while steam supply is on. Startup exclusion reduces decisions during warmup
and also delays fault decisions there. Temperature and acoustic signatures alone were not
shown to distinguish normal condensate discharge from live steam loss in independent data.
No proprietary vendor decision rule or acoustic calibration is supplied.

## Chiller and heat pump

Water-side chiller cooling duty is `m*cp*(Tin-Tout)`, cooling COP is duty/electric power.
Approach temperatures compare refrigerant evaporation/condensation temperatures with
water-side outlets. Normal regressions condition on load and measured water temperatures.
Additional oil/refrigerant stages require their own explicit sensors, including correct
absolute versus differential oil pressures. Their high observed false-alarm rates made
them unsuitable as default alarms. Isothermal Carnot COP `Te/(Tc-Te)` is a proxy under
its stated assumptions; its optional upper-bound gate is not a universal bound on cycles
with glide, storage or different temperature definitions.

Heat-pump heating COP is `Qcond/W`; the isothermal heating Carnot proxy is `Tc/(Tc-Te)`.
Normal load-conditioned residuals include log COP/Carnot, subcooling `Tc-Tliquid`,
discharge superheat `Tdischarge-Tc`, and log refrigerant mass per shaft revolution.
Extended features add temperatures, log power/speed/COP. Nominal demand is a measured
or documented operating-condition input, not a fault label.
[Bellanco et al.](https://doi.org/10.1016/j.ijrefrig.2021.10.017) describes the original
propane experiment; these monitoring paths are our own implementation.

The latest response branch treats condensing temperature as a response rather than
an exclusion context. Its large weak-EF gain is carried by a 0.3K session difference.
Ablating that response removes the improvement; synthetic ±0.3K normal offsets trigger
almost all accepted normal samples. Therefore it is labeled **state deviation**, not
flow-fault-specific diagnosis. No new blind fault test was obtained.

`evaporator_conductance_proxy=(Qcond-W)/(Tsource,in-Te)` neglects losses/storage and
uses inlet temperature instead of unknown LMTD. Units W/K do not make it a measured UA.
An assumed 10°C source value from documentation remains an assumption.

## Statistical modules and alarm policy

`ConditionalResidualDiagnostic` fits linear/quadratic ridge normal response models.
Each feature/target declares unit and log transform; targets also declare direction
and a positive scale floor. Explicit feature/target order survives sorted JSON. Normal
residual center/MAD scale, context envelopes and independent normal calibration are
saved. A time-delimited trailing **sample mean** is used when configured; it is not a
continuous time-weighted integral. Its observed/expected metrics are transformed values.

`TemporalEvidenceDiagnostic` and `SignedResidualCUSUM` implement normal-referenced
EWMA/CUSUM ideas with causal resets. The signed path supports empirical fixed-length
normal block calibration and optional AR1 prediction residuals. This is not an exact
stationary-bootstrap or AR-sieve reproduction. `ResidualCoherenceDiagnostic` uses
normal covariance shrinkage and a positive directional projection of signed residuals.
[NIST CUSUM](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm),
[EWMA](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc324.htm).

`WindowChangeDiagnostic` compares trailing signed log-residual means with earlier
causal windows. No evaluation baseline is learned. Constant offsets cancel; gaps and
episodes restart history. Shortening the lag improved speed but increased observed
false alarms, so the engine baseline remains selected.

Filter supervised APIs use provider service-life labels and causal pressure/flow/dust
features. scikit-learn ExtraTrees/boosting is used at training; exported numeric trees
support NumPy inference without pickle. The target is proximity to the provider's
600Pa service limit, not a universal present-clog label. No trained corpus model is shipped.

Hysteresis/confirmation/release-delay is a policy layer. A held alarm may stay active
after the score drops. Increased alarm-state occupancy is not improved sensor detection;
evaluate first new alarm, pre-onset alarms and recovery false alarms separately.
All scores need `valid`, `reasons`, `score_semantics` and provenance alongside the number.
