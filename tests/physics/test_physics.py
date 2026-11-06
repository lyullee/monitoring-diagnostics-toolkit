"""Independent forward models and limiting cases; no measured plant data.

All library imports are inside tests so core-only installs can collect the suite.
Run with: python -m pytest -m physics tests/physics
"""
import numpy as np
import pytest
from equipment_diagnostics import (SensorBatch, MassBalanceDiagnostic, BoilerBalanceDiagnostic,
    HeatExchangerDiagnostic, HydraulicResistanceDiagnostic, VaporizerDiagnostic,
    ROMembraneDiagnostic, ValveTrackingDiagnostic, ColumnHydraulicsDiagnostic,
    SteamTrapDiagnostic, ChillerPerformanceDiagnostic)

pytestmark = pytest.mark.physics


def batch(t, values, units, **kwargs):
    arrays = [np.broadcast_to(x, (len(t),)) for x in values.values()]
    return SensorBatch(np.asarray(t, dtype=float), np.column_stack(arrays), tuple(values),
                       tuple(units), "physics-clock", "physics-asset", "simulation", **kwargs)


def error(record_property, key, actual, expected, *, atol=0, rtol=1e-10):
    actual, expected = np.broadcast_arrays(actual, expected)
    assert np.isfinite(actual).all() and actual.size
    absolute = float(np.max(np.abs(actual-expected)))
    relative = float(np.max(np.abs(actual-expected)/np.maximum(np.abs(expected), 1e-300)))
    record_property(key+"_max_absolute_error", absolute)
    record_property(key+"_max_relative_error", relative)
    np.testing.assert_allclose(actual, expected, atol=atol, rtol=rtol)


@pytest.mark.parametrize("cls", [MassBalanceDiagnostic, BoilerBalanceDiagnostic])
@pytest.mark.parametrize("loss", [0., 0.03, 0.3])
def test_inventory_analytic_irregular_ramp(cls, loss, record_property):
    # Integrated dM/dt = (2+.1t) - .4 - .2 - leak, independent closed solution.
    t = np.array([0., 3, 8, 12, 17, 23, 28, 34, 39, 44, 49, 55])
    m = 100+(1.4-loss)*t+.05*t*t
    b = batch(t, {"M": m, "in": 2+.1*t, "out": .4, "known": .2},
              ["kg", "kg/s", "kg/s", "kg/s"])
    model = cls({"inventory_mass": "M", "inflow": "in", "outflow": "out",
                 "known_loss": "known"}, loss_limit_kg_s=.05, window_s=10, max_gap_s=10)
    r = model.score(b)
    assert r.valid.sum() == 9
    error(record_property, "loss_kg_s", r.metrics["unaccounted_loss_kg_s"][r.valid], loss,
          atol=2e-13)
    assert bool(r.alarms[r.valid].all()) == (loss > .05)


def test_inventory_nonlinear_flow_sampling_convergence(record_property):
    errors = []
    for dt in (1., .5, .25):
        t = np.arange(0, 60+dt/2, dt)
        # Exponential inflow has an exact accumulation integral; trapezoids aren't exact.
        b = batch(t, {"M": 100+20*np.expm1(t/20), "in": np.exp(t/20), "out": 0},
                  ["kg", "kg/s", "kg/s"])
        r = MassBalanceDiagnostic({"inventory_mass": "M", "inflow": "in", "outflow": "out"},
            loss_limit_kg_s=.05, window_s=10).score(b)
        errors.append(float(np.max(np.abs(r.metrics["unaccounted_loss_kg_s"][r.valid]))))
    record_property("sampling_errors_kg_s", str(errors))
    assert 3.9 < errors[0]/errors[1] < 4.1
    assert 3.9 < errors[1]/errors[2] < 4.1


@pytest.mark.parametrize("ratio", [0.25, 1., 4.])
@pytest.mark.parametrize("ntu", [.1, 1., 4.])
def test_heat_exchanger_independent_ntu(ratio, ntu, record_property):
    from ht import effectiveness_from_NTU
    ch, cc = 4000., 4000.*ratio
    cmin, cmax = min(ch, cc), max(ch, cc)
    ua = ntu*cmin
    efficiency = effectiveness_from_NTU(NTU=ntu, Cr=cmin/cmax, subtype="counterflow")
    duty = efficiency*cmin*(370.-290.)
    b = batch(np.arange(20.), {"hi": 370., "ho": 370.-duty/ch, "ci": 290.,
        "co": 290.+duty/cc, "hf": ch/4000, "cf": cc/4000},
        ["K"]*4+["kg/s"]*2)
    m = HeatExchangerDiagnostic({"hot_in": "hi", "hot_out": "ho", "cold_in": "ci",
        "cold_out": "co", "hot_flow": "hf", "cold_flow": "cf"},
        cp_hot_j_kg_k=4000, cp_cold_j_kg_k=4000, min_lmtd_k=.0001).fit(b)
    r = m.score(b)
    assert r.valid.sum() == 19 and not r.alarms.any()
    error(record_property, "ua_w_k", r.metrics["ua_w_k"][r.valid], ua, rtol=3e-12)
    error(record_property, "duty_w", r.metrics["hot_duty_w"][r.valid], duty, rtol=3e-12)


def test_heat_exchanger_added_thermal_resistance(record_property):
    from ht import effectiveness_from_NTU
    def forward(ua):
        q = effectiveness_from_NTU(NTU=ua/4000, Cr=.5, subtype="counterflow")*4000*80
        return batch(np.arange(20.), {"hi": 370., "ho": 370.-q/8000, "ci": 290.,
            "co": 290.+q/4000, "hf": 2., "cf": 1.}, ["K"]*4+["kg/s"]*2)
    clean = 5000.
    fouled = 1/(1/clean+1e-4)  # series thermal resistance [K/W], not area-normalized Rf.
    m = HeatExchangerDiagnostic({"hot_in": "hi", "hot_out": "ho", "cold_in": "ci",
        "cold_out": "co", "hot_flow": "hf", "cold_flow": "cf"},
        cp_hot_j_kg_k=4000, cp_cold_j_kg_k=4000).fit(forward(clean))
    r = m.score(forward(fouled))
    error(record_property, "fouled_ua_w_k", r.metrics["ua_w_k"][r.valid], fouled)
    assert r.alarms[r.valid].all()


@pytest.mark.parametrize("regime,n,density_n", [("laminar", 1., 0.), ("inertial", 2., 1.),
                                               ("blasius", 1.75, .75)])
def test_hydraulic_independent_darcy(regime, n, density_n, record_property):
    from fluids.friction import friction_factor, Blasius
    diameter, length, viscosity = .05, 5., .001
    q0 = 1e-5 if regime == "laminar" else .002
    q = q0*np.linspace(.9, 1.1, 30)
    rho = np.linspace(800., 1200., 30)
    velocity = q/(np.pi*diameter**2/4)
    re = rho*velocity*diameter/viscosity
    if regime == "inertial":
        f = np.full(30, .03)  # constant friction factor / inertial limit
    else:
        f = np.array([friction_factor(Re=x) if regime == "laminar" else Blasius(x) for x in re])
    dp = f*(length/diameter)*rho*velocity**2/2
    b = batch(np.arange(30.), {"dp": dp, "q": q, "rho": rho}, ["Pa", "m3/s", "kg/m3"])
    m = HydraulicResistanceDiagnostic({"pressure_drop": "dp", "volume_flow": "q", "density": "rho"},
        reference_flow_m3_s=q0, reference_density_kg_m3=1000, flow_exponent=n,
        density_exponent=density_n).fit(b)
    v0 = q0/(np.pi*diameter**2/4)
    re0 = 1000*v0*diameter/viscosity
    f0 = (.03 if regime == "inertial" else friction_factor(Re=re0) if regime == "laminar"
          else Blasius(re0))
    expected = f0*(length/diameter)*1000*v0*v0/2
    r = m.score(b)
    assert r.valid.all() and not r.alarms.any()
    error(record_property, "normalized_dp_pa", r.metrics["normalized_pressure_drop_pa"], expected)


@pytest.mark.parametrize("fluid,pressure", [("Water", 101325.), ("Nitrogen", 3e5), ("Methane", 5e5)])
def test_vaporizer_latent_heat_and_reference_basis(fluid, pressure, record_property):
    from CoolProp.CoolProp import PropsSI
    tsat = PropsSI("T", "P", pressure, "Q", 1, fluid)
    hl = PropsSI("H", "P", pressure, "Q", 0, fluid)
    hv = PropsSI("H", "P", pressure, "Q", 1, fluid)
    model = VaporizerDiagnostic({"outlet_temperature": "T", "predicted_temperature": "pred",
        "mass_flow": "m", "inlet_enthalpy": "hi", "outlet_enthalpy": "ho"}, shortfall_limit_k=5)
    results = []
    for offset in (0., -1e7):
        b = batch(np.arange(20.), {"T": tsat, "pred": tsat, "m": .2, "hi": hl+offset,
            "ho": hv+offset}, ["K", "K", "kg/s", "J/kg", "J/kg"],
            metadata={"enthalpy_basis_id": fluid+str(offset)})
        r = model.score(b)
        assert r.valid.all() and not r.alarms.any()
        results.append(r.metrics["absorbed_duty_w"])
    error(record_property, "latent_duty_w", results[0], .2*(hv-hl))
    error(record_property, "reference_offset_invariance_w", results[1], results[0], rtol=1e-12)
    record_property("latent_heat_j_kg", hv-hl)


@pytest.mark.parametrize("remaining", [1., .6, 0.])
def test_ro_solution_diffusion_and_zero_flux(remaining, record_property):
    # J_mass = rho*A(T)*(deltaP-deltaPi); A(T)=A_ref*exp[k*(T-Tref)].
    p = np.linspace(7e5, 9e5, 30)
    temp = np.linspace(288., 308., 30)
    factor = np.exp(.025*(temp-298.))
    area, a0, rho = 40., 2e-12, 1000.
    def forward(mult):
        j_mass = rho*a0*mult*factor*p
        return batch(np.arange(30.), {"q": area*j_mass/rho, "p": p, "tcf": 1/factor},
                     ["m3/s", "Pa", "1"])
    m = ROMembraneDiagnostic({"permeate_flow": "q", "net_driving_pressure": "p",
        "temperature_correction": "tcf"}, membrane_area_m2=area).fit(forward(1.))
    r = m.score(forward(remaining))
    assert r.valid.all()
    error(record_property, "permeability_m_pa_s", r.metrics["normalized_permeability_m_pa_s"],
          a0*remaining, atol=1e-26)
    assert bool(r.alarms.all()) == (remaining < .85)


@pytest.mark.parametrize("bias", [0., .08])
def test_valve_analytic_transport_delay(bias, record_property):
    t = np.arange(100.)+np.sin(np.arange(100.))*.1
    delay = 3.7
    b = batch(t, {"u": .2+.003*t, "x": .2+.003*(t-delay)+bias}, ["1", "1"])
    m = ValveTrackingDiagnostic({"command": "u", "position": "x"},
                               delay_s=delay, error_limit_fraction=.04)
    r = m.score(b)
    error(record_property, "tracking_fraction", r.metrics["tracking_error_fraction"][r.valid], bias,
          atol=2e-16)
    assert bool(r.alarms[r.valid].all()) == (bias > .04)


def test_valve_first_order_response_exposes_model_limit(record_property):
    # A healthy first-order actuator is not a pure delay. Document the mismatch.
    t = np.arange(30.)*.2
    b = batch(t, {"u": .8, "x": .8-.6*np.exp(-t/2)}, ["1", "1"])
    r = ValveTrackingDiagnostic({"command": "u", "position": "x"},
                                error_limit_fraction=.04).score(b)
    record_property("healthy_first_order_samples_flagged", int(r.alarms.sum()))
    assert r.alarms[:10].all()  # expected model limitation, not diagnostic accuracy.


@pytest.mark.parametrize("power", [1., 2.])
def test_column_single_phase_pressure_loss_limit(power, record_property):
    # Dry gas limit: linear viscous or quadratic inertial resistance in fixed packing.
    # The wet-loading exponent and flooding thresholds are NOT validated here.
    mass = np.linspace(.8, 1.2, 30)
    rho, area = 2., .2
    velocity = mass/(rho*area)
    dp = 50*velocity if power == 1 else 3*rho*velocity**2/2
    b = batch(np.arange(30.), {"v": mass, "l": 1., "dp": dp}, ["kg/s", "kg/s", "Pa"])
    m = ColumnHydraulicsDiagnostic({"pressure_drop": "dp", "vapor_flow": "v", "liquid_flow": "l"},
        reference_vapor_flow_kg_s=1., reference_liquid_flow_kg_s=1., vapor_exponent=power,
        liquid_exponent=0).fit(b)
    r = m.score(b)
    expected = 50/(rho*area) if power == 1 else 3*rho/(2*(rho*area)**2)
    error(record_property, "dry_normalized_dp_pa", r.metrics["normalized_pressure_drop_pa"], expected)
    assert r.valid.all() and not r.alarms.any()


def trap_model():
    return SteamTrapDiagnostic({"steam_temperature": "steam", "trap_temperature": "trap",
        "acoustic_level": "sound", "supply_on": "on"}, acoustic_quiet_max=.2,
        acoustic_loud_min=2., cold_margin_k=40, hot_margin_k=10)


def test_steam_trap_newton_cooling_counterexample(record_property):
    # Newton heating of a healthy cold body. Without startup mode gating it alarms.
    t = np.arange(300.)
    body = 400.-100*np.exp(-t/60)
    r = trap_model().score(batch(t, {"steam": 400., "trap": body, "sound": .1, "on": 1},
                                  ["K", "K", "1", "1"]))
    error(record_property, "deficit_k", r.metrics["temperature_deficit_k"], 100*np.exp(-t/60),
          atol=1e-13)
    assert r.alarms[:30].all() and not r.alarms[-30:].any()
    record_property("startup_false_alarm_samples_without_mode_gate", int(r.alarms.sum()))


def test_steam_trap_acoustics_not_unique_fault_evidence(record_property):
    b = batch(np.arange(20.), {"steam": 400., "trap": 397., "sound": 3., "on": 1},
              ["K", "K", "1", "1"])
    r = trap_model().score(b)
    assert r.alarms.all() and r.metadata["root_cause_confirmed"] is False
    record_property("scope", "Rule test only: condensate flow and steam leakage can both be loud.")


def test_steam_trap_startup_mode_gate():
    t = np.arange(300.)
    b = batch(t, {"steam": 400., "trap": 400.-100*np.exp(-t/60), "sound": .1, "on": 1},
              ["K", "K", "1", "1"], modes=np.where(t < 60, "startup", "steady"))
    m = trap_model()
    m.allowed_modes = ("steady",)
    r = m.score(b)
    assert not r.valid[:60].any() and r.valid[60:].all() and not r.alarms.any()


def test_hydraulic_zero_pressure_drop_is_not_high_resistance():
    m = HydraulicResistanceDiagnostic({"pressure_drop": "dp", "volume_flow": "q"},
        reference_flow_m3_s=.01, flow_exponent=2).fit(
        batch(np.arange(20.), {"dp": 100., "q": .01}, ["Pa", "m3/s"]))
    r = m.score(batch(np.arange(20.), {"dp": 0., "q": .01}, ["Pa", "m3/s"]))
    assert r.valid.all() and not r.alarms.any()
    # A bypass or failed DP transmitter is outside this one-sided high-resistance screen.


def test_heat_exchanger_energy_nonclosure_rejected():
    b = batch(np.arange(20.), {"hi": 370., "ho": 350., "ci": 290., "co": 310.,
        "hf": 1., "cf": 1.}, ["K"]*4+["kg/s"]*2)
    m = HeatExchangerDiagnostic({"hot_in": "hi", "hot_out": "ho", "cold_in": "ci",
        "cold_out": "co", "hot_flow": "hf", "cold_flow": "cf"},
        cp_hot_j_kg_k=4000, cp_cold_j_kg_k=4000).fit(b)
    bad = batch(np.arange(20.), {"hi": 370., "ho": 350., "ci": 290., "co": 300.,
        "hf": 1., "cf": 1.}, ["K"]*4+["kg/s"]*2)
    r = m.score(bad)
    assert not r.valid.any() and not r.alarms.any()


def chiller_batch(evap, cond, cop):
    q = 2*4180*5
    return batch(np.arange(20.), {"i": evap+10, "o": evap+5, "cool": cond-5,
        "evap": evap, "cond": cond, "f": 2., "p": q/cop},
        ["K"]*5+["kg/s", "W"])


def chiller_model(**kwargs):
    return ChillerPerformanceDiagnostic({"chilled_in": "i", "chilled_out": "o", "cooling_out": "cool",
        "evaporating_temperature": "evap", "condensing_temperature": "cond",
        "chilled_flow": "f", "electric_power": "p"}, **kwargs)


@pytest.mark.parametrize("evap,cond", [(270., 310.), (280., 320.), (285., 300.)])
def test_chiller_independent_refrigerant_cycle(evap, cond, record_property):
    from CoolProp.CoolProp import PropsSI
    fluid = "R134a"
    pe = PropsSI("P", "T", evap, "Q", 1, fluid)
    pc = PropsSI("P", "T", cond, "Q", 0, fluid)
    h1 = PropsSI("H", "P", pe, "Q", 1, fluid)
    s1 = PropsSI("S", "P", pe, "Q", 1, fluid)
    h2s = PropsSI("H", "P", pc, "S", s1, fluid)
    h2 = h1+(h2s-h1)/.75  # compressor isentropic efficiency
    h3 = PropsSI("H", "P", pc, "Q", 0, fluid)
    # Isenthalpic expansion h4=h3; motor efficiency .9.
    cop = (h1-h3)/((h2-h1)/.9)
    b = chiller_batch(evap, cond, cop)
    m = chiller_model(enforce_isothermal_carnot_bound=True).fit(b)
    r = m.score(b)
    assert r.valid.all() and not r.alarms.any()
    error(record_property, "cycle_cop", r.metrics["cop"], cop)
    record_property("cycle_cop_reference", cop)
    assert cop < evap/(cond-evap)


def test_chiller_optional_second_law_gate(record_property):
    m = chiller_model(enforce_isothermal_carnot_bound=True).fit(chiller_batch(275., 313., 3.))
    limit = 275/(313-275)
    r = m.score(chiller_batch(275., 313., 1.2*limit))
    assert not r.valid.any() and not r.alarms.any()
    record_property("isothermal_carnot_cop", limit)
    r = m.score(chiller_batch(275., 313., limit))
    assert r.valid.all()  # reversible limiting case, not a real plant claim.
