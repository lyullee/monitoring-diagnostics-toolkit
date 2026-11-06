"""Common reference fitting, causal segmentation and elapsed-time alarm policy."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import numpy as np
from .contracts import DiagnosticResult, frozen_array


def number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"{name} must be numeric")
    if not np.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError(f"invalid {name}")
    return float(value)


class Diagnostic:
    kind = "abstract"
    references: tuple[str, ...] = ()
    reference_metric: str | None = None
    envelope_roles: tuple[str, ...] = ()
    score_semantics = 'ratio_to_engineering_limit'

    def __init__(self, channels, *, persistence_s=0.0, max_gap_s=60.0, allowed_modes=None):
        if not isinstance(channels, dict) or not channels or any(
                not isinstance(k, str) or not isinstance(v, str) or not v for k, v in channels.items()):
            raise ValueError("explicit role-to-channel mapping required")
        self.channels = deepcopy(channels)
        if len(set(channels.values())) != len(channels):
            raise ValueError("different sensor roles must not reuse the same channel")
        self.persistence_s = number(persistence_s, "persistence_s", nonnegative=True)
        self.max_gap_s = number(max_gap_s, "max_gap_s", positive=True)
        if allowed_modes is not None and (isinstance(allowed_modes, str) or not allowed_modes):
            raise ValueError("allowed_modes must be a nonempty list")
        self.allowed_modes = None if allowed_modes is None else tuple(allowed_modes)
        self.reference = None
        self.params = {}

    def _columns(self, batch, required, optional=None):
        optional = optional or {}
        unknown = set(self.channels) - set(required) - set(optional) - {"operating"}
        if unknown:
            raise ValueError(f"{self.kind}: unknown channel roles: {sorted(unknown)}")
        missing = set(required) - set(self.channels)
        if missing:
            raise ValueError(f"{self.kind}: missing channel roles: {sorted(missing)}")
        cols, mask = {}, np.ones(len(batch.time_s), dtype=bool)
        for role, unit in {**required, **optional}.items():
            if role in self.channels:
                values, good = batch.column(self.channels[role], unit)
                cols[role] = values
                mask &= good
        if "operating" in self.channels:
            op, good = batch.column(self.channels["operating"], "1")
            mask &= good & (op == 1)
        if self.allowed_modes is not None:
            if batch.modes is None:
                raise ValueError("allowed_modes requires observed mode labels")
            mask &= np.isin(batch.modes, self.allowed_modes)
        return cols, mask

    def _break(self, batch, i, mask):
        return (i == 0 or not mask[i-1] or not mask[i]
                or batch.time_s[i] - batch.time_s[i-1] > self.max_gap_s
                or batch.episodes[i] != batch.episodes[i-1]
                or (batch.modes is not None and batch.modes[i] != batch.modes[i-1]))

    def _raw(self, batch):
        raise NotImplementedError

    def _alarm_break(self,batch,i,valid,metrics):
        """Allow temporal diagnostics to reset persistence on an observed context switch."""
        return self._break(batch,i,valid)

    def _score(self, metrics):
        raise NotImplementedError

    @property
    def signature(self):
        return hashlib.sha256(json.dumps({"kind": self.kind, "channels": self.channels,
                                         "params": self.params, "max_gap_s": self.max_gap_s,
                                         "allowed_modes": self.allowed_modes},
                                        sort_keys=True).encode()).hexdigest()

    def fit(self, normal_batch, *, minimum_samples=10):
        """Fit expected performance from caller-selected normal operation only.

        Thresholds are explicit engineering limits, not fitted false-alarm probabilities.
        """
        # A failed replacement fit must not silently leave a stale model usable.
        if self.reference_metric is not None:
            self.reference = None
        if not isinstance(minimum_samples, int) or isinstance(minimum_samples, bool) or minimum_samples < 2:
            raise ValueError("minimum_samples must be an integer >= 2")
        metrics, valid, _ = self._raw(normal_batch)
        if self.reference_metric is None:
            return self
        valid &= np.logical_and.reduce([np.isfinite(v) for v in metrics.values()])
        if np.count_nonzero(valid) < minimum_samples:
            raise ValueError(f"{self.kind}: insufficient eligible normal reference samples")
        center = float(np.median(metrics[self.reference_metric][valid]))
        if not np.isfinite(center) or center <= 0:
            raise ValueError("reference performance must be finite and positive")
        envelope = {}
        for role in self.envelope_roles:
            values = metrics[role][valid]
            low, high = float(values.min()), float(values.max())
            padding = max(abs(low), abs(high)) * 0.1
            envelope[role] = [low-padding, high+padding]
        self.reference = {"schema": "equipment-diagnostics.reference.v1", "kind": self.kind,
                          "signature": self.signature, "center": center, "envelope": envelope,
                          "asset_id": normal_batch.asset_id,
                          "origin": normal_batch.origin, "clock_id": normal_batch.clock_id,
                          "training_fingerprint": normal_batch.fingerprint,
                          "accepted_samples": int(valid.sum()),
                          "rejected_samples": int((~valid).sum())}
        return self

    def set_reference(self, reference):
        if (reference.get("schema") != "equipment-diagnostics.reference.v1"
                or reference.get("kind") != self.kind or reference.get("signature") != self.signature):
            raise ValueError("reference schema/kind/configuration mismatch")
        number(reference.get("center"), "reference.center", positive=True)
        if set(reference.get("envelope", {})) != set(self.envelope_roles):
            raise ValueError("reference operating envelope is incomplete")
        for bounds in reference["envelope"].values():
            if len(bounds) != 2 or not np.isfinite(bounds).all() or bounds[0] > bounds[1]:
                raise ValueError("invalid reference envelope")
        if not reference.get("asset_id") or not reference.get("origin"):
            raise ValueError("reference provenance missing")
        self.reference = deepcopy(reference)
        return self

    def score(self, batch):
        metrics, valid, reasons = self._raw(batch)
        if self.reference_metric is not None:
            if self.reference is None:
                raise ValueError(f"{self.kind}: fit a normal reference before scoring")
            if self.reference["signature"] != self.signature:
                raise ValueError("reference configuration changed; refit before scoring")
            if self.reference["asset_id"] != batch.asset_id:
                raise ValueError("reference asset differs from operation asset")
            if self.reference["origin"] != batch.origin:
                raise ValueError("reference origin differs; cross-origin transfer needs separate qualification")
            for role, (low, high) in self.reference["envelope"].items():
                outside = valid & ((metrics[role] < low) | (metrics[role] > high))
                reasons[outside] = "outside_reference_operating_envelope"
                valid[outside] = False
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            scores = np.asarray(self._score(metrics), dtype=float)
        finite_metrics = np.logical_and.reduce([np.isfinite(v) for v in metrics.values()])
        bad_metrics = valid & ~finite_metrics
        reasons[bad_metrics] = "nonfinite_derived_metric"
        valid &= finite_metrics
        nonfinite = valid & ~np.isfinite(scores)
        reasons[nonfinite] = "nonfinite_derived_score"
        valid &= np.isfinite(scores)
        scores = np.where(valid, scores, np.nan)
        alarms, states = np.zeros(len(scores), bool), []
        since = None
        for i, score in enumerate(scores):
            if self._alarm_break(batch, i, valid, metrics):
                since = None
            if not valid[i]:
                states.append("UNKNOWN"); since = None
            elif score > 1.0:
                since = float(batch.time_s[i]) if since is None else since
                alarms[i] = batch.time_s[i] - since >= self.persistence_s
                states.append("ALARM" if alarms[i] else "PENDING")
            else:
                states.append("NORMAL"); since = None
        cleaned = {k: frozen_array(np.where(valid, v, np.nan)) for k, v in metrics.items()}
        return DiagnosticResult(self.kind, batch.time_s, frozen_array(scores), frozen_array(valid),
                                frozen_array(alarms), tuple(states), tuple(map(str, reasons)), cleaned,
                                {"asset_id": batch.asset_id, "clock_id": batch.clock_id,
                                 "origin": batch.origin, "input_fingerprint": batch.fingerprint,
                                 "configuration_signature": self.signature,
                                 "episodes": batch.episodes.tolist(),
                                 "modes": None if batch.modes is None else batch.modes.tolist(),
                                 "qualification": "engineering_screening",
                                 "score_semantics": self.score_semantics,
                                 "root_cause_confirmed": False, "references": list(self.references),
                                 "input_metadata": deepcopy(batch.metadata),
                                 "reference": deepcopy(self.reference),
                                 "persistence_s": self.persistence_s, "max_gap_s": self.max_gap_s})


def finish(metrics, valid, *, physical=None, reason="outside_physical_domain"):
    reasons = np.full(len(valid), "ok", dtype=object)
    reasons[~valid] = "missing_invalid_or_inactive_input"
    if physical is not None:
        reasons[valid & ~physical] = reason
        valid = valid & physical
    return metrics, valid, reasons
