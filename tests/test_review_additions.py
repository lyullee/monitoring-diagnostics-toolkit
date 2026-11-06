import json
import numpy as np
import pytest
from equipment_diagnostics import (SensorBatch, MassBalanceDiagnostic, VaporizerDiagnostic,
    HydraulicResistanceDiagnostic, ColumnHydraulicsDiagnostic, SteamTrapDiagnostic,
    ChillerPerformanceDiagnostic, StreamingDiagnostic, list_diagnostics, DIAGNOSTICS)
from equipment_diagnostics.catalog import CATALOG


def make(t, values, units, **kwargs):
    return SensorBatch(np.asarray(t), np.column_stack(list(values.values())), tuple(values),
                       tuple(units), "clock", "A", "synthetic", **kwargs)


def hydro(n=30):
    return make(np.arange(n), {"dp": np.full(n, 100.), "q": np.full(n, 0.01)}, ["Pa", "m3/s"])


def test_failed_refit_invalidates_old_reference():
    m = HydraulicResistanceDiagnostic({"pressure_drop": "dp", "volume_flow": "q"},
                                      reference_flow_m3_s=0.01, flow_exponent=2).fit(hydro())
    with pytest.raises(ValueError, match="insufficient"):
        m.fit(hydro(2))
    assert m.reference is None
    with pytest.raises(ValueError, match="fit"):
        m.score(hydro())


def test_changed_mapping_cannot_silently_reuse_reference():
    m = HydraulicResistanceDiagnostic({"pressure_drop": "dp", "volume_flow": "q"},
                                      reference_flow_m3_s=0.01, flow_exponent=2).fit(hydro())
    m.params["flow_exponent"] = 1.5
    with pytest.raises(ValueError, match="refit"):
        m.score(hydro())


def test_reused_sensor_role_rejected():
    with pytest.raises(ValueError, match="reuse"):
        VaporizerDiagnostic({"outlet_temperature": "T", "predicted_temperature": "T",
                             "mass_flow": "F"}, shortfall_limit_k=5)


def test_nonfinite_secondary_metric_invalidates_decision():
    b = make(np.arange(3), {"out": [280]*3, "pred": [290]*3,
        "flow": [1e308]*3, "hi": [0]*3, "ho": [1e308]*3},
        ["K", "K", "kg/s", "J/kg", "J/kg"], metadata={"enthalpy_basis_id": "shared"})
    m = VaporizerDiagnostic({"outlet_temperature": "out", "predicted_temperature": "pred",
        "mass_flow": "flow", "inlet_enthalpy": "hi", "outlet_enthalpy": "ho"}, shortfall_limit_k=5)
    with np.errstate(over="ignore"):
        r = m.score(b)
    assert not r.valid.any() and not r.alarms.any()
    assert set(r.reasons) == {"nonfinite_derived_metric"}


@pytest.mark.parametrize("values", [np.ones((2, 1), dtype=bool), np.ones((2, 1), dtype=complex)])
def test_boolean_complex_measurements_rejected(values):
    with pytest.raises(ValueError, match="real numbers"):
        SensorBatch(np.arange(2), values, ("x",), ("1",), "c", "a", "synthetic")


def test_empty_context_and_basis_fingerprint():
    with pytest.raises(ValueError, match="empty"):
        make(np.arange(2), {"x": [1, 2]}, ["1"], episodes=np.array(["a", ""]))
    a = make(np.arange(2), {"x": [1, 2]}, ["1"], metadata={"basis": "one"})
    b = make(np.arange(2), {"x": [1, 2]}, ["1"], metadata={"basis": "two"})
    assert a.fingerprint != b.fingerprint


def column(multiplier=1, outside=False):
    t = np.arange(40)
    v = 2+0.1*np.sin(t)
    liquid = 3+0.1*np.cos(t)
    dp = multiplier*1000*(v/2)**2*(liquid/3)**0.5
    if outside:
        v *= 2
    return make(t, {"dp": dp, "v": v, "l": liquid}, ["Pa", "kg/s", "kg/s"])


def test_column_loading_correction_and_scope():
    m = ColumnHydraulicsDiagnostic({"pressure_drop": "dp", "vapor_flow": "v", "liquid_flow": "l"},
        reference_vapor_flow_kg_s=2, reference_liquid_flow_kg_s=3,
        vapor_exponent=2, liquid_exponent=0.5).fit(column())
    assert not m.score(column()).alarms.any()
    assert m.score(column(1.7)).alarms.all()
    assert not m.score(column(outside=True)).valid.any()
    assert m.score(column(1.7)).metadata["root_cause_confirmed"] is False


@pytest.mark.parametrize("trap,sound,expected", [(340, 0.1, True), (397, 3., True),
                                                (390, 0.5, False)])
def test_steam_trap_patterns(trap, sound, expected):
    t = np.arange(10)
    b = make(t, {"steam": t*0+400, "trap": t*0+trap, "sound": t*0+sound,
                 "supply": t*0+1}, ["K", "K", "1", "1"])
    m = SteamTrapDiagnostic({"steam_temperature": "steam", "trap_temperature": "trap",
        "acoustic_level": "sound", "supply_on": "supply"}, acoustic_quiet_max=0.2,
        acoustic_loud_min=2, cold_margin_k=40, hot_margin_k=10)
    assert bool(m.score(b).alarms.all()) == expected
    off = make(t, {"steam": t*0+400, "trap": t*0+trap, "sound": t*0+sound,
                   "supply": t*0}, ["K", "K", "1", "1"])
    assert m.score(off).summary()["status"] == "insufficient_data"


def chiller(power=20000, condensing=313, evaporating=275):
    t = np.arange(30)
    return make(t, {"i": t*0+285, "o": t*0+280, "cool": t*0+308,
        "evap": t*0+evaporating, "cond": t*0+condensing, "f": t*0+2, "power": t*0+power},
        ["K", "K", "K", "K", "K", "kg/s", "W"])


def chiller_model():
    return ChillerPerformanceDiagnostic({"chilled_in": "i", "chilled_out": "o",
        "cooling_out": "cool", "evaporating_temperature": "evap", "condensing_temperature": "cond",
        "chilled_flow": "f", "electric_power": "power"})


def test_chiller_cop_and_both_approaches_and_reload():
    m = chiller_model().fit(chiller())
    assert m.reference["center"] == pytest.approx(2.09)
    assert not m.score(chiller()).alarms.any()
    assert m.score(chiller(power=30000)).alarms.all()
    assert m.score(chiller(condensing=320)).alarms.all()
    assert m.score(chiller(evaporating=268)).alarms.all()
    clone = chiller_model().set_reference(json.loads(json.dumps(m.reference)))
    np.testing.assert_allclose(clone.score(chiller()).scores, m.score(chiller()).scores)
    damaged = dict(m.reference); del damaged["evaporator_approach_k"]
    with pytest.raises(ValueError):
        chiller_model().set_reference(damaged)


def test_streaming_batch_equivalence_and_bounded_history():
    t = np.arange(0, 1000, 2.)
    m = MassBalanceDiagnostic({"inventory_mass": "mass", "inflow": "in", "outflow": "out"},
        loss_limit_kg_s=0.05, window_s=25, persistence_s=13, max_gap_s=5)
    b = make(t, {"mass": 1000-0.2*np.maximum(t-100, 0), "in": t*0, "out": t*0},
             ["kg", "kg/s", "kg/s"])
    expected = m.score(b)
    stream = StreamingDiagnostic(m, max_history_samples=100)
    pieces = [stream.push(b.subset(slice(start, start+7))) for start in range(0, len(t), 7)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in pieces]), expected.scores, equal_nan=True)
    np.testing.assert_array_equal(np.concatenate([p.alarms for p in pieces]), expected.alarms)
    np.testing.assert_array_equal(np.concatenate([p.valid for p in pieces]), expected.valid)
    assert stream.history_samples < 30


def test_stream_rollback_on_overlap_context_and_history_overflow():
    m = VaporizerDiagnostic({"outlet_temperature": "t", "predicted_temperature": "p",
                             "mass_flow": "f"}, shortfall_limit_k=5)
    b = make(np.arange(10), {"t": np.full(10, 275.), "p": np.full(10, 290.), "f": np.ones(10)},
             ["K", "K", "kg/s"])
    s = StreamingDiagnostic(m)
    s.push(b.subset(slice(0, 5)))
    with pytest.raises(ValueError, match="overlap"):
        s.push(b.subset(slice(4, 8)))
    assert s.history_samples == 5
    with pytest.raises(ValueError, match="exceeds"):
        StreamingDiagnostic(m, max_history_samples=2).push(b)
    assert len(s.push(b.subset(slice(5, None))).time_s) == 5


def test_stream_heat_boundary_and_valve_delay_match_batch():
    from test_diagnostics import heat_model, exchanger
    m = heat_model().fit(exchanger())
    data = exchanger(12)
    stream = StreamingDiagnostic(m)
    pieces = [stream.push(data.subset(slice(i, i+3))) for i in range(0, 30, 3)]
    np.testing.assert_allclose(np.concatenate([p.scores for p in pieces]), m.score(data).scores, equal_nan=True)


def test_catalog_is_complete_and_not_shared_mutable_data():
    assert set(CATALOG) == set(DIAGNOSTICS)
    entries = list_diagnostics()
    assert len(entries) == 11 and all(e["description"] for e in entries)
    entries[0]["description"] = "modified"
    assert list_diagnostics()[0]["description"] != "modified"
