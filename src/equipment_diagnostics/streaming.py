"""Bounded causal replay for chunked equipment signals.

All diagnostic models are stateless at score-time. Retaining the physical window,
alarm persistence and boundary context makes chunk results agree with batch results.
"""
from __future__ import annotations
from copy import deepcopy
import json
import numpy as np
from .contracts import SensorBatch, DiagnosticResult, json_value


class StreamingDiagnostic:
    def __init__(self, diagnostic, *, max_history_samples=10000):
        if isinstance(max_history_samples, bool) or not isinstance(max_history_samples, int) or max_history_samples < 2:
            raise ValueError("max_history_samples must be an integer >= 2")
        self.diagnostic = diagnostic
        self.max_history_samples = max_history_samples
        self.reset()

    def _model_identity(self):
        return json.dumps([self.diagnostic.signature, self.diagnostic.reference,
                           self.diagnostic.persistence_s], sort_keys=True, allow_nan=False)

    def reset(self):
        self._history = None
        self._identity = self._model_identity()

    @property
    def history_samples(self):
        return 0 if self._history is None else len(self._history.time_s)

    def push(self, batch):
        if self._identity != self._model_identity():
            raise ValueError("diagnostic/reference changed; reset stream explicitly")
        previous = self._history
        offset = 0
        if previous is None:
            combined = batch
        else:
            contract_a = (previous.channels, previous.units, previous.clock_id, previous.asset_id, previous.origin)
            contract_b = (batch.channels, batch.units, batch.clock_id, batch.asset_id, batch.origin)
            if contract_a != contract_b or ((previous.modes is None) != (batch.modes is None)):
                raise ValueError("stream channel/unit/clock/asset/origin/context contract changed")
            if batch.time_s[0] <= previous.time_s[-1]:
                raise ValueError("stream chunks must not overlap or arrive out of order")
            if json.dumps(json_value(previous.metadata), sort_keys=True) != json.dumps(json_value(batch.metadata), sort_keys=True):
                raise ValueError("stream metadata changed; reset for a new measurement basis")
            offset = len(previous.time_s)
            combined = SensorBatch(np.concatenate((previous.time_s, batch.time_s)),
                np.concatenate((previous.values, batch.values)), batch.channels, batch.units,
                batch.clock_id, batch.asset_id, batch.origin,
                np.concatenate((previous.valid, batch.valid)),
                np.concatenate((previous.episodes, batch.episodes)),
                None if batch.modes is None else np.concatenate((previous.modes, batch.modes)),
                batch.metadata)
        physical_window = max(getattr(self.diagnostic, "window", 0), getattr(self.diagnostic, "delay", 0))
        horizon = physical_window + self.diagnostic.persistence_s + 2*self.diagnostic.max_gap_s
        first = max(0, int(np.searchsorted(combined.time_s, combined.time_s[-1]-horizon))-1)
        if getattr(self.diagnostic,'requires_full_history',False):
            first=0
        if len(combined.time_s)-first > self.max_history_samples:
            raise ValueError("required replay history exceeds max_history_samples; state was not advanced")
        scored = self.diagnostic.score(combined)
        selection = slice(offset, None)
        metadata = deepcopy(scored.metadata)
        metadata["episodes"] = batch.episodes.tolist()
        metadata["modes"] = None if batch.modes is None else batch.modes.tolist()
        metadata["replay_context_samples"] = offset
        metadata["streaming"] = True
        out = DiagnosticResult(scored.detector, scored.time_s[selection], scored.scores[selection],
            scored.valid[selection], scored.alarms[selection], scored.states[selection],
            scored.reasons[selection], {k: v[selection] for k, v in scored.metrics.items()}, metadata)
        self._history = combined.subset(slice(first, None))
        return out
