"""CSV with explicit units and versioned JSON configuration/reference files."""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import tempfile
import numpy as np
from .contracts import SensorBatch
from .diagnostics import create_diagnostic


def read_json(path):
    def no_duplicates(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f"duplicate JSON key: {k}")
            out[k] = v
        return out
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f, object_pairs_hook=no_duplicates,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"nonfinite JSON: {x}")))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as f:
            name = f.name
            f.write(text)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def read_config(path):
    cfg = read_json(path)
    required = {"schema", "clock_id", "asset_id", "origin", "units", "diagnostics"}
    if not isinstance(cfg, dict) or not required <= set(cfg):
        raise ValueError("configuration requires schema, clock_id, asset_id, origin, units, diagnostics")
    unknown = set(cfg)-required-{"time_column", "episode_column", "mode_column", "metadata"}
    if unknown or cfg["schema"] != "equipment-diagnostics.config.v1":
        raise ValueError(f"unknown configuration schema or keys: {sorted(unknown)}")
    if not isinstance(cfg["units"], dict) or not cfg["units"]:
        raise ValueError("units must explicitly map selected measurement columns")
    if not isinstance(cfg["diagnostics"], list) or not cfg["diagnostics"]:
        raise ValueError("nonempty diagnostic list required")
    ids = set()
    models = {}
    for spec in cfg["diagnostics"]:
        if set(spec)-{"id", "kind", "channels", "parameters", "alarm"}:
            raise ValueError("unknown diagnostic specification key")
        ident = spec["id"]
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError("diagnostic IDs must be nonempty and unique")
        ids.add(ident)
        parameters, alarm = spec.get("parameters", {}), spec.get("alarm", {})
        if set(alarm)-{"persistence_s", "max_gap_s", "allowed_modes"} or set(parameters) & set(alarm):
            raise ValueError("invalid or duplicated alarm options")
        if not set(spec["channels"].values()) <= set(cfg["units"]):
            raise ValueError("diagnostic channels must have declared units")
        models[ident] = create_diagnostic(spec["kind"], channels=spec["channels"], **parameters, **alarm)
    return cfg, models


def load_csv(path, cfg):
    names = tuple(cfg["units"])
    time_col = cfg.get("time_column", "time_s")
    special = [cfg[k] for k in ("episode_column", "mode_column") if k in cfg]
    if time_col in names or set(special) & set(names):
        raise ValueError("clock/context columns cannot be measurement features")
    rows, times, episodes, modes = [], [], [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if len(set(fields)) != len(fields) or not set(names+(time_col,)+tuple(special)) <= set(fields):
            raise ValueError("CSV headers are duplicated or selected columns are missing")
        for i, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"CSV row {i} has the wrong number of fields")
            try:
                times.append(float(row[time_col]))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"CSV row {i}: numeric elapsed time in seconds required") from exc
            values = []
            for name in names:
                try:
                    values.append(float(row[name]))
                except (ValueError, TypeError):
                    values.append(float("nan"))
            rows.append(values)
            episodes.append(row[cfg["episode_column"]] if "episode_column" in cfg else "default")
            modes.append(row[cfg["mode_column"]] if "mode_column" in cfg else "UNSPECIFIED")
    return SensorBatch(np.asarray(times), np.asarray(rows), names, tuple(cfg["units"].values()),
                       cfg["clock_id"], cfg["asset_id"], cfg["origin"],
                       episodes=np.asarray(episodes), modes=np.asarray(modes),
                       metadata=cfg.get("metadata", {}))
