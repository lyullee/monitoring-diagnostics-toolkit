"""Actual public upstream objects; no imitation of foreign classes."""
import os
from pathlib import Path
import sys
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch, MassBalanceDiagnostic, VaporizerDiagnostic
from equipment_diagnostics.adapters import (from_process_monitoring, to_process_monitoring,
    to_detection_result, residual_signal_batch, from_h2physics_timeseries,
    from_h2physics_observations, to_pipeline_calculation)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def upstream_paths(monkeypatch):
    root = Path(os.environ.get("EQUIPMENT_UPSTREAM_ROOT", Path(__file__).parents[1]/".upstream"))
    for name in ("process-monitoring-toolkit", "h2physics", "pipeline-safety-toolkit"):
        folder = root/name/"src"
        if not folder.is_dir():
            pytest.skip(f"explicit upstream checkout missing: {folder}")
        monkeypatch.syspath_prepend(str(folder))


def source_batch():
    from process_monitoring.contracts import SignalBatch
    t = np.arange(30, dtype=float)
    values = np.column_stack((np.full(30, 275.0), np.full(30, 290.0), np.ones(30)))
    mask = np.ones(values.shape, dtype=bool); mask[5, 0] = False
    return SignalBatch(t, values, ("out", "pred", "flow"), ("K", "K", "kg/s"), mask,
                       np.array(["a"]*15+["b"]*15), np.array(["steady"]*30), "synthetic")


def result():
    b = from_process_monitoring(source_batch(), clock_id="simulation_s", asset_id="vaporizer1")
    return VaporizerDiagnostic({"outlet_temperature": "out", "predicted_temperature": "pred",
                                "mass_flow": "flow"}, shortfall_limit_k=5).score(b)


def test_actual_process_monitoring_contracts_roundtrip():
    original = source_batch()
    b = from_process_monitoring(original, clock_id="simulation_s", asset_id="vaporizer1")
    restored = to_process_monitoring(b)
    np.testing.assert_array_equal(restored.valid, original.valid)
    np.testing.assert_array_equal(restored.episodes, original.episodes)
    np.testing.assert_array_equal(restored.modes, original.modes)
    assert restored.units == original.units
    assert restored.metadata["clock_id"] == "simulation_s"
    r = result()
    foreign = to_detection_result(r)
    assert foreign.to_dict()["schema"] == "process-monitoring.detection.v1"
    assert foreign.to_dict()["scores"][5] is None
    assert not foreign.valid[5] and not foreign.alarms[5]


def test_adapter_rejects_source_identity_override():
    original = source_batch()
    original.metadata["clock_id"] = "original_clock"
    original.metadata["asset_id"] = "original_asset"
    with pytest.raises(ValueError, match="clock_id"):
        from_process_monitoring(original, clock_id="other_clock", asset_id="original_asset")
    with pytest.raises(ValueError, match="asset_id"):
        from_process_monitoring(original, clock_id="original_clock", asset_id="other_asset")


def test_existing_monitor_consumes_residual_signal_batch():
    from process_monitoring import Monitor, create_detector, WindowFeatures
    b = residual_signal_batch(result())
    m = Monitor(create_detector("bounds", upper=1.0), WindowFeatures(window=1))
    m.fit(b)
    out = m.score(b)
    assert out.alarms[out.valid].all()
    assert not out.valid[5]
    assert b.metadata["score_semantics"] == "ratio_to_engineering_limit"


def test_actual_h2physics_timeseries():
    from h2physics.core import TimeSeries, Origin
    src = source_batch()
    series = TimeSeries(src.time_s, src.values, src.channels, src.units, src.valid,
                        "simulation_s", Origin.SYNTHETIC, "object-test",
                        ("temperature", "temperature", "mass_flow"))
    b = from_h2physics_timeseries(series, asset_id="vaporizer1")
    assert b.clock_id == series.clock_id and b.origin == "synthetic"
    np.testing.assert_array_equal(b.valid, src.valid)
    assert b.metadata["source_id"] == "object-test"


def test_actual_h2physics_observation_table_requires_supplied_clock():
    from h2physics.observations import ObservationTable, Variable
    from h2physics.core import Origin
    table = ObservationTable(np.array([[280., 1.], [281., 2.]]),
        (Variable("T", "temperature", "K"), Variable("F", "mass_flow", "kg/s")),
        np.array([[True, True], [False, True]]), ("row1", "row2"), ("exp1", "exp2"),
        (Origin.MEASURED, Origin.MEASURED), "source-object")
    b = from_h2physics_observations(table, time_s=[0, 1], clock_id="historian", asset_id="A",
                                    channels=["F", "T"])
    assert b.channels == ("F", "T") and b.units == ("kg/s", "K")
    assert b.origin == "historian_measured" and not b.valid[1, 1]
    assert b.episodes.tolist() == ["exp1", "exp2"]


def test_actual_pipeline_calculation_preserves_unknown_and_context():
    from pipeline_integrity.contracts import RunContext
    context = RunContext(asset_id="vaporizer1", scenario_id="test", clock_id="simulation_s", origin="synthetic")
    r = result()
    good = to_pipeline_calculation(r, index=0, context=context)
    assert good.status == "computed" and good.values["alarm"]
    unknown = to_pipeline_calculation(r, index=5, context=context)
    assert unknown.status == "needs_data" and unknown.values["score"] is None
    assert unknown.model_dump(mode="json")["values"]["root_cause_confirmed"] is False
    wrong = RunContext(asset_id="other", scenario_id="test", clock_id="simulation_s", origin="synthetic")
    with pytest.raises(ValueError, match="mismatch"):
        to_pipeline_calculation(r, index=0, context=wrong)


def test_mass_balance_agrees_with_upstream_interval_sign():
    from process_monitoring.thermo import mass_inventory_residual
    t = np.arange(0, 101, 10, dtype=float)
    mass = 100+0.3*t
    inc, out = t*0+1, t*0+0.5
    b = SensorBatch(t, np.column_stack((mass, inc, out)), ("m", "i", "o"),
                     ("kg", "kg/s", "kg/s"), "clock", "tank", "synthetic")
    r = MassBalanceDiagnostic({"inventory_mass": "m", "inflow": "i", "outflow": "o"},
                              loss_limit_kg_s=0.1, window_s=10).score(b)
    upstream = mass_inventory_residual(t, mass, inc, out)
    np.testing.assert_allclose(r.metrics["unaccounted_loss_kg_s"][1:], -upstream[1:]/10)
