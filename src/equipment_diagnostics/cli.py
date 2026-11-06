"""Command line entry point for normal-reference fitting and diagnostic scoring."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .diagnostics import DIAGNOSTICS
from .io import read_config, read_json, load_csv, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Equipment sensor diagnostics (SI units)")
    subs = parser.add_subparsers(dest="command", required=True)
    listing = subs.add_parser("list", help="list implemented diagnostic models")
    listing.add_argument("--details", action="store_true", help="include descriptions and reference requirements")
    for name in ("fit", "run"):
        p = subs.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--data", required=True)
        p.add_argument("--output", required=True)
        if name == "run":
            p.add_argument("--reference")
    args = parser.parse_args(argv)
    if args.command == "list":
        from .catalog import list_diagnostics
        print(json.dumps(list_diagnostics() if args.details else sorted(DIAGNOSTICS), indent=2,
                         ensure_ascii=True))
        return 0
    try:
        inputs = [args.config, args.data]+([args.reference] if getattr(args, "reference", None) else [])
        if Path(args.output).resolve() in {Path(p).resolve() for p in inputs}:
            raise ValueError("output must not overwrite input data/configuration/reference")
        cfg, models = read_config(args.config)
        batch = load_csv(args.data, cfg)
        if args.command == "fit":
            refs = {}
            for ident, model in models.items():
                model.fit(batch)
                refs[ident] = model.reference
            payload = {"schema": "equipment-diagnostics.references.v1", "references": refs,
                       "normal_reference_is_caller_declared": True,
                       "training_fingerprint": batch.fingerprint}
        else:
            references = {}
            if args.reference:
                saved = read_json(args.reference)
                if saved.get("schema") != "equipment-diagnostics.references.v1":
                    raise ValueError("unsupported reference bundle schema")
                references = saved["references"]
                if set(references) != set(models):
                    raise ValueError("reference bundle and diagnostic IDs differ")
            results = {}
            for ident, model in models.items():
                if references.get(ident) is not None:
                    model.set_reference(references[ident])
                results[ident] = model.score(batch).to_dict()
            payload = {"schema": "equipment-diagnostics.report.v1", "asset_id": batch.asset_id,
                       "clock_id": batch.clock_id, "origin": batch.origin,
                       "summaries": {key: val["summary"] for key, val in results.items()},
                       "diagnostics": results}
        write_json(args.output, payload)
        print(json.dumps({"output": str(Path(args.output).resolve()),
                          "summaries": payload.get("summaries", {}),
                          "input_samples": len(batch.time_s)}, ensure_ascii=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"equipment-diagnose: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
