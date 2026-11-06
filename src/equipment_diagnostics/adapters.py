"""Optional, explicit boundaries to the user's independent Python projects."""
from __future__ import annotations
import numpy as np
from .contracts import SensorBatch


def from_process_monitoring(batch, *, clock_id, asset_id):
    """Consume process_monitoring.SignalBatch; never invent its clock identity."""
    for key, supplied in (("clock_id", clock_id), ("asset_id", asset_id)):
        if key in batch.metadata and batch.metadata[key] != supplied:
            raise ValueError(f"source {key} conflicts with supplied identity")
    return SensorBatch(batch.time_s, batch.values, tuple(batch.channels), tuple(batch.units),
                       clock_id, asset_id, batch.origin, batch.valid, batch.episodes,
                       batch.modes, {**dict(batch.metadata), "adapter": "process_monitoring.SignalBatch"})


def to_process_monitoring(batch):
    from process_monitoring.contracts import SignalBatch
    return SignalBatch(batch.time_s, batch.values, batch.channels, batch.units, batch.valid,
                       batch.episodes, batch.modes, batch.origin,
                       {**batch.metadata, "clock_id": batch.clock_id, "asset_id": batch.asset_id})


def to_detection_result(result):
    from process_monitoring.contracts import DetectionResult
    payload = result.to_dict()
    return DetectionResult(result.time_s, result.scores, result.alarms, result.valid,
                           1.0, result.detector,
                           {**payload["metadata"], "states": payload["states"],
                            "reasons": payload["reasons"], "equipment_metrics": payload["metrics"]})


def residual_signal_batch(result):
    """Feed dimensionless equipment scores into the existing Monitor API."""
    from process_monitoring.contracts import SignalBatch
    meta = result.metadata
    return SignalBatch(result.time_s, result.scores[:, None], (result.detector+"_score",),
                       ("1",), result.valid[:, None], np.asarray(meta["episodes"]),
                       None if meta["modes"] is None else np.asarray(meta["modes"]),
                       meta["origin"], {"clock_id": meta["clock_id"], "asset_id": meta["asset_id"],
                                        "score_semantics": meta.get('score_semantics','ratio_to_engineering_limit'),
                                        "root_cause_confirmed": False})


_ORIGIN = {"measured": "historian_measured", "predicted": "model_prediction",
           "reconstructed": "reconstructed", "synthetic": "synthetic", "unresolved": "unspecified"}


def from_h2physics_timeseries(series, *, asset_id, episodes=None, modes=None):
    origin = getattr(series.origin, "value", series.origin)
    if origin not in _ORIGIN:
        raise ValueError("unsupported h2physics origin")
    metadata = {"adapter": "h2physics.core.TimeSeries", "source_id": series.source_id,
                "source_origin": origin, "quantities": list(series.quantities),
                "basis_ids": list(series.basis_ids)}
    enthalpy_bases = {b for q, b in zip(series.quantities, series.basis_ids)
                      if q in {"specific_enthalpy", "enthalpy"}}
    if enthalpy_bases and len(enthalpy_bases) == 1 and "" not in enthalpy_bases:
        metadata["enthalpy_basis_id"] = next(iter(enthalpy_bases))
    return SensorBatch(series.time_s, series.values, tuple(series.channels), tuple(series.units),
                       series.clock_id, asset_id, _ORIGIN[origin], series.valid, episodes, modes,
                       metadata)


def from_h2physics_observations(table, *, time_s, clock_id, asset_id, channels):
    """The current ObservationTable has no clock. Caller must supply row-aligned time."""
    if not channels or len(set(channels)) != len(channels):
        raise ValueError("explicit unique observation channels required")
    names = [v.name for v in table.variables]
    try:
        ix = [names.index(c) for c in channels]
    except ValueError as exc:
        raise ValueError("observation channel not found") from exc
    origins = [getattr(table.origins[j], "value", table.origins[j]) for j in ix]
    if any(o not in _ORIGIN for o in origins):
        raise ValueError("unsupported observation origin")
    origin = _ORIGIN[origins[0]] if len(set(origins)) == 1 else "mixed"
    return SensorBatch(time_s, table.values[:, ix], tuple(channels),
                       tuple(table.variables[j].unit for j in ix), clock_id, asset_id, origin,
                       table.valid[:, ix], np.asarray(table.experiment_ids),
                       metadata={"adapter": "h2physics.observations.ObservationTable",
                                 "source_id": table.source_id, "row_ids": list(table.row_ids),
                                 "channel_origins": origins,
                                 "basis_ids": [table.variables[j].basis_id for j in ix]})


def to_pipeline_calculation(result, *, index, context):
    """Export evidence only, not leak probability, damage state or a risk frequency."""
    from pipeline_integrity.contracts import Calculation
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(result.time_s):
        raise ValueError("valid sample index required")
    if context.clock_id != result.metadata["clock_id"] or context.asset_id != result.metadata["asset_id"]:
        raise ValueError("pipeline context asset/clock mismatch")
    expected = {"historian_measured": {"measured"}, "synthetic": {"synthetic"},
                "model_prediction": {"simulation", "user_declared"},
                "reconstructed": {"user_declared"}}
    if context.origin not in expected.get(result.metadata["origin"], set()):
        raise ValueError("pipeline context origin incompatible with diagnostic evidence")
    data = result.to_dict()
    values = {"schema": "equipment-diagnostics.evidence.v1", "detector": result.detector,
              "time_s": float(result.time_s[index]), "asset_id": context.asset_id,
              "clock_id": context.clock_id, "origin": result.metadata["origin"],
              "state": result.states[index], "valid": bool(result.valid[index]),
              "score": data["scores"][index], "alarm": bool(result.alarms[index]),
              "reason": result.reasons[index], "root_cause_confirmed": False,
              "metrics": {k: v[index] for k, v in data["metrics"].items()},
              "input_fingerprint": result.metadata["input_fingerprint"]}
    return Calculation(values=values, status="computed" if result.valid[index] else "needs_data",
                       notes=("Equipment screening evidence; not a failure probability or confirmed release.",))
