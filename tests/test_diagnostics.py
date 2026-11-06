import json
import numpy as np
import pytest
from equipment_diagnostics import (SensorBatch, MassBalanceDiagnostic, BoilerBalanceDiagnostic,
    HydraulicResistanceDiagnostic, HeatExchangerDiagnostic, VaporizerDiagnostic,
    ROMembraneDiagnostic, ValveTrackingDiagnostic)


def batch(t, data, units, *, mask=None, episodes=None, modes=None, asset="A", origin="synthetic"):
    return SensorBatch(np.array(t, float), np.column_stack(list(data.values())), tuple(data),
                       tuple(units), "clock", asset, origin, mask, episodes, modes)


def test_mass_balance_exact_partial_trapezoid_and_leak():
    t = np.array([0, 3, 8, 12, 17, 23, 28], float)
    # Integral of q(t)=2+0.1t, with a separately known 0.2 kg/s vent.
    mass = 100+1.8*t+0.05*t*t
    data = {"m": mass, "inc": 2+0.1*t, "out": t*0, "vent": t*0+0.2}
    model = MassBalanceDiagnostic({"inventory_mass": "m", "inflow": "inc", "outflow": "out",
                                   "known_loss": "vent"}, loss_limit_kg_s=0.1, window_s=10)
    good = model.score(batch(t, data, ["kg", "kg/s", "kg/s", "kg/s"]))
    # Balance-consistent interpolation is exact for linear flow and constant loss.
    assert np.max(np.abs(good.metrics["unaccounted_loss_kg_s"][good.valid])) < 1e-12
    data["m"] = 100+1.8*t+0.05*t*t-0.3*t
    bad = model.score(batch(t, data, ["kg", "kg/s", "kg/s", "kg/s"]))
    assert bad.alarms[bad.valid].all()
    assert np.allclose(bad.metrics["unaccounted_loss_kg_s"][bad.valid], 0.3, atol=1e-12)


@pytest.mark.parametrize("model_class", [MassBalanceDiagnostic, BoilerBalanceDiagnostic])
def test_inventory_accumulation_prevents_false_leak(model_class):
    t = np.arange(0, 121, 10)
    b = batch(t, {"m": 100+0.5*t, "i": t*0+1, "o": t*0+0.5}, ["kg", "kg/s", "kg/s"])
    m = model_class({"inventory_mass": "m", "inflow": "i", "outflow": "o"},
                    loss_limit_kg_s=0.01, window_s=30)
    r = m.score(b)
    assert not r.alarms.any()
    assert not r.valid[:3].any()
    assert np.max(r.scores[r.valid]) < 1e-10


def test_mass_window_does_not_bridge_missing_data_gap_or_episode():
    t = np.array([0, 10, 20, 30, 40, 50, 100, 110, 120, 130])
    b = batch(t, {"m": t*0+100, "i": t*0+1, "o": t*0}, ["kg", "kg/s", "kg/s"],
              episodes=np.array(["a"]*8+["b"]*2))
    valid = b.valid.copy(); valid[3, 0] = False
    b = SensorBatch(b.time_s, b.values, b.channels, b.units, b.clock_id, b.asset_id, b.origin,
                    valid, b.episodes)
    r = MassBalanceDiagnostic({"inventory_mass": "m", "inflow": "i", "outflow": "o"},
                              loss_limit_kg_s=0.1, window_s=20, max_gap_s=15).score(b)
    assert r.valid[2]
    assert not r.valid[3:].any()


def hydraulic(t, multiplier=1):
    q = 0.01*(1+0.3*np.sin(np.asarray(t)/10))
    return batch(t, {"dp": multiplier*100*(q/0.01)**2, "q": q}, ["Pa", "m3/s"])


def test_flow_normalization_and_reference_transfer_guards():
    t = np.arange(100)
    m = HydraulicResistanceDiagnostic({"pressure_drop": "dp", "volume_flow": "q"},
        reference_flow_m3_s=0.01, flow_exponent=2, growth_limit_fraction=0.2)
    m.fit(hydraulic(t))
    r = m.score(hydraulic(t))
    assert np.max(r.scores) < 1e-12
    assert m.score(hydraulic(t, 1.5)).alarms.all()
    wrong = batch(t, {"dp": t*0+100, "q": t*0+0.1}, ["Pa", "m3/s"])
    assert not m.score(wrong).valid.any()
    b = hydraulic(t)
    with pytest.raises(ValueError, match="asset"):
        m.score(SensorBatch(b.time_s, b.values, b.channels, b.units, b.clock_id, "B", b.origin))
    with pytest.raises(ValueError, match="origin"):
        m.score(SensorBatch(b.time_s, b.values, b.channels, b.units, b.clock_id, "A", "historian_measured"))


def exchanger(transfer=20, imbalance=0):
    t = np.arange(30)
    return batch(t, {"hi": t*0+360, "ho": t*0+360-transfer, "ci": t*0+290,
                     "co": t*0+290+transfer+imbalance, "hf": t*0+2, "cf": t*0+2},
                 ["K", "K", "K", "K", "kg/s", "kg/s"])


def heat_model():
    return HeatExchangerDiagnostic({"hot_in": "hi", "hot_out": "ho", "cold_in": "ci",
        "cold_out": "co", "hot_flow": "hf", "cold_flow": "cf"},
        cp_hot_j_kg_k=4180, cp_cold_j_kg_k=4180)


def test_equal_lmtd_heat_transfer_and_energy_closure():
    m = heat_model().fit(exchanger())
    r = m.score(exchanger())
    assert r.metrics["ua_w_k"][1] == pytest.approx(3344)
    assert not r.alarms.any()
    assert m.score(exchanger(12)).alarms[1:].all()
    wrong = m.score(exchanger(20, imbalance=10))
    assert not wrong.valid.any()
    assert wrong.summary()["status"] == "insufficient_data"


def test_temperature_crossover_not_fouling_alarm():
    m = heat_model().fit(exchanger())
    r = m.score(exchanger(80))
    assert not r.valid.any()
    assert not r.alarms.any()


def test_vaporizer_duty_uses_enthalpy_and_shared_basis():
    t = np.arange(4)
    b = batch(t, {"t": t*0+270, "pred": t*0+290, "flow": t*0+2,
                  "hi": t*0+100, "ho": t*0+500}, ["K", "K", "kg/s", "J/kg", "J/kg"])
    model = VaporizerDiagnostic({"outlet_temperature": "t", "predicted_temperature": "pred",
        "mass_flow": "flow", "inlet_enthalpy": "hi", "outlet_enthalpy": "ho"}, shortfall_limit_k=5)
    with pytest.raises(ValueError, match="basis"):
        model.score(b)
    b = SensorBatch(b.time_s, b.values, b.channels, b.units, b.clock_id, b.asset_id, b.origin,
                    metadata={"enthalpy_basis_id": "caller-qualified-reference"})
    r = model.score(b)
    assert np.all(r.metrics["absorbed_duty_w"] == 800)


def test_ro_pressure_and_temperature_normalization():
    t = np.arange(20)
    factor = 0.8+0.02*t
    p = t*0+1e6
    q = 1e-4/factor
    b = batch(t, {"q": q, "p": p, "factor": factor}, ["m3/s", "Pa", "1"])
    model = ROMembraneDiagnostic({"permeate_flow": "q", "net_driving_pressure": "p",
                                 "temperature_correction": "factor"}, membrane_area_m2=10).fit(b)
    assert np.max(model.score(b).scores) < 1e-12
    bad = batch(t, {"q": q*0.7, "p": p, "factor": factor}, ["m3/s", "Pa", "1"])
    assert model.score(bad).alarms.all()


def test_valve_delay_and_episode_boundary():
    t = np.arange(20)
    command = 0.2+0.01*t
    b = batch(t, {"c": command, "p": 0.2+0.01*(t-2)}, ["1", "1"],
              episodes=np.array(["a"]*10+["b"]*10))
    m = ValveTrackingDiagnostic({"command": "c", "position": "p"}, error_limit_fraction=0.02, delay_s=2)
    r = m.score(b)
    assert not r.alarms.any()
    assert not r.valid[[0, 1, 10, 11]].any()


def test_persistence_is_elapsed_time_and_invalid_resets():
    t = [0, 2, 5, 6, 10, 16]
    b = batch(t, {"c": np.zeros(6), "p": np.ones(6)}, ["1", "1"])
    m = ValveTrackingDiagnostic({"command": "c", "position": "p"}, error_limit_fraction=0.1,
                                persistence_s=5, max_gap_s=7)
    r = m.score(b)
    assert r.states[:3] == ("PENDING", "PENDING", "ALARM")
    mask = b.valid.copy(); mask[3, 0] = False
    bad = SensorBatch(b.time_s, b.values, b.channels, b.units, b.clock_id, b.asset_id, b.origin, mask)
    r2 = m.score(bad)
    assert r2.states[3:] == ("UNKNOWN", "PENDING", "ALARM")


def test_causal_prefix_and_input_immutability():
    t = np.arange(30)
    b = batch(t, {"m": 100-t*0.2, "i": t*0, "o": t*0}, ["kg", "kg/s", "kg/s"])
    m = MassBalanceDiagnostic({"inventory_mass": "m", "inflow": "i", "outflow": "o"},
                              loss_limit_kg_s=0.05, window_s=10)
    r = m.score(b)
    prefix = m.score(b.subset(slice(0, 20)))
    np.testing.assert_allclose(prefix.scores, r.scores[:20], equal_nan=True)
    with pytest.raises(ValueError):
        b.values.setflags(write=True)


def test_units_missing_values_and_strict_json():
    t = np.arange(3)
    model = VaporizerDiagnostic({"outlet_temperature": "t", "predicted_temperature": "p",
                                 "mass_flow": "f"}, shortfall_limit_k=5)
    with pytest.raises(ValueError, match="expected K"):
        model.score(batch(t, {"t": t*0+20, "p": t*0+30, "f": t*0+1}, ["degC", "K", "kg/s"]))
    b = batch(t, {"t": [np.nan]*3, "p": t*0+290, "f": t*0+1}, ["K", "K", "kg/s"])
    r = model.score(b)
    assert r.summary()["status"] == "insufficient_data"
    assert json.loads(json.dumps(r.to_dict(), allow_nan=False))["scores"] == [None]*3


@pytest.mark.parametrize("times", [[0, 0], [1, 0], [0, float("nan")]])
def test_clock_errors(times):
    with pytest.raises(ValueError):
        batch(times, {"x": [1, 2]}, ["1"])


def test_calibration_rejects_too_few_samples_and_config_mismatch():
    m = HydraulicResistanceDiagnostic({"pressure_drop": "dp", "volume_flow": "q"},
                                      reference_flow_m3_s=0.01, flow_exponent=2)
    with pytest.raises(ValueError, match="insufficient"):
        m.fit(hydraulic(np.arange(3)))
    m.fit(hydraulic(np.arange(20)))
    different = HydraulicResistanceDiagnostic(m.channels, reference_flow_m3_s=0.02, flow_exponent=2)
    with pytest.raises(ValueError, match="mismatch"):
        different.set_reference(m.reference)


def test_stopped_mode_is_unknown_not_normal():
    t = np.arange(10)
    b = batch(t, {"c": t*0, "p": t*0}, ["1", "1"], modes=np.array(["off"]*10))
    r = ValveTrackingDiagnostic({"command": "c", "position": "p"}, error_limit_fraction=0.1,
                                 allowed_modes=["steady"]).score(b)
    assert set(r.states) == {"UNKNOWN"}
