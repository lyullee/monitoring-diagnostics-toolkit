"""Explicit clocks, SI measurements, quality and equipment evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any
import hashlib
import json
import numpy as np


def frozen_array(value, dtype=None):
    a = np.ascontiguousarray(value, dtype=dtype)
    return np.frombuffer(a.tobytes(), dtype=a.dtype).reshape(a.shape)


def json_value(value):
    if isinstance(value, np.ndarray):
        return json_value(value.tolist())
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


@dataclass(frozen=True)
class SensorBatch:
    time_s: np.ndarray
    values: np.ndarray
    channels: tuple[str, ...]
    units: tuple[str, ...]
    clock_id: str
    asset_id: str
    origin: str
    valid: np.ndarray | None = None
    episodes: np.ndarray | None = None
    modes: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if np.asarray(self.time_s).dtype.kind in "bc" or np.asarray(self.values).dtype.kind in "bc":
            raise ValueError("times and measurements must be real numbers, not booleans or complex values")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dictionary")
        t = np.asarray(self.time_s, dtype=float)
        x = np.asarray(self.values, dtype=float)
        if t.ndim != 1 or not len(t) or x.ndim != 2 or x.shape[0] != len(t):
            raise ValueError("nonempty time_s[n] and values[n, d] required")
        if not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
            raise ValueError("time_s must be finite and strictly increasing")
        names, units = tuple(self.channels), tuple(self.units)
        if (len(names) != x.shape[1] or len(set(names)) != len(names)
                or not names or any(not isinstance(n, str) or not n.strip() for n in names)
                or len(units) != len(names) or any(not isinstance(u, str) or not u.strip() for u in units)):
            raise ValueError("unique channel names and explicit units must match columns")
        if any(not isinstance(v, str) or not v.strip()
               for v in (self.clock_id, self.asset_id, self.origin)):
            raise ValueError("clock_id, asset_id and origin must be explicit")
        if self.valid is None:
            valid = np.isfinite(x)
        else:
            raw = np.asarray(self.valid)
            if raw.shape != x.shape or raw.dtype.kind not in "bifu" or not np.isin(raw, [0, 1]).all():
                raise ValueError("valid must contain boolean or 0/1 flags matching values")
            valid = raw.astype(bool) & np.isfinite(x)
        ep = np.zeros(len(t), dtype=int) if self.episodes is None else np.asarray(self.episodes)
        modes = None if self.modes is None else np.asarray(self.modes)
        if ep.shape != t.shape or (modes is not None and modes.shape != t.shape):
            raise ValueError("episode and mode vectors must match timestamps")
        if ep.dtype.kind not in "iuUS" or (modes is not None and modes.dtype.kind not in "iuUS"):
            raise ValueError("episodes/modes must be integer or string identifiers")
        for identifiers in (ep, modes):
            if identifiers is not None and identifiers.dtype.kind in "US":
                if any(not str(v).strip() for v in identifiers):
                    raise ValueError("episode/mode identifiers must not be empty")
        for key, val in {"time_s": frozen_array(t), "values": frozen_array(x),
                         "valid": frozen_array(valid), "episodes": frozen_array(ep),
                         "modes": None if modes is None else frozen_array(modes),
                         "channels": names, "units": units,
                         "metadata": deepcopy(self.metadata)}.items():
            object.__setattr__(self, key, val)

    def column(self, name, unit):
        try:
            j = self.channels.index(name)
        except ValueError as exc:
            raise ValueError(f"missing channel: {name}") from exc
        if self.units[j] != unit:
            raise ValueError(f"{name}: expected {unit}, received {self.units[j]}")
        return self.values[:, j], self.valid[:, j]

    def subset(self, selection):
        return SensorBatch(self.time_s[selection], self.values[selection], self.channels,
                           self.units, self.clock_id, self.asset_id, self.origin,
                           self.valid[selection], self.episodes[selection],
                           None if self.modes is None else self.modes[selection], self.metadata)

    @property
    def fingerprint(self):
        h = hashlib.sha256()
        for a in (self.time_s, self.values, self.valid, self.episodes):
            h.update(str(a.dtype).encode()); h.update(str(a.shape).encode()); h.update(a.tobytes())
        if self.modes is not None:
            h.update(self.modes.tobytes())
        h.update(json.dumps([self.channels, self.units, self.clock_id, self.asset_id,
                             self.origin, json_value(self.metadata)], ensure_ascii=False,
                            sort_keys=True, allow_nan=False).encode())
        return h.hexdigest()


@dataclass(frozen=True)
class DiagnosticResult:
    detector: str
    time_s: np.ndarray
    scores: np.ndarray
    valid: np.ndarray
    alarms: np.ndarray
    states: tuple[str, ...]
    reasons: tuple[str, ...]
    metrics: dict[str, np.ndarray]
    metadata: dict[str, Any]

    def summary(self):
        n = int(np.count_nonzero(self.valid))
        return {"detector": self.detector, "samples": len(self.time_s), "valid_samples": n,
                "alarm_samples": int(np.count_nonzero(self.alarms & self.valid)),
                "latest_state": self.states[-1],
                "status": "suspected_anomaly" if np.any(self.alarms & self.valid) else
                          "insufficient_data" if n == 0 else
                          "pending" if "PENDING" in self.states else "no_alarm",
                "has_invalid_samples": n < len(self.time_s)}

    def to_dict(self):
        return json_value({"schema": "equipment-diagnostics.result.v1", "threshold": 1.0,
                           "detector": self.detector, "time_s": self.time_s,
                           "scores": self.scores, "valid": self.valid, "alarms": self.alarms,
                           "states": self.states, "reasons": self.reasons,
                           "metrics": self.metrics, "metadata": self.metadata,
                           "summary": self.summary()})
