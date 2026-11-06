"""Run the optional actual-object tests and record the exact upstream revisions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import platform
import importlib.metadata
import hashlib

root = Path(__file__).resolve().parents[1]
upstream = Path(os.environ.get("EQUIPMENT_UPSTREAM_ROOT", root/".upstream"))
revisions = {}
for name in ("process-monitoring-toolkit", "h2physics", "pipeline-safety-toolkit", "rotorvibe"):
    folder = upstream/name
    if not folder.is_dir():
        raise SystemExit(f"Missing read-only upstream checkout: {folder}")
    revisions[name] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder, text=True).strip()
run = subprocess.run([sys.executable, "-m", "pytest", "tests/test_integrations.py", "-m", "integration", "-q"],
                     cwd=root, capture_output=True, text=True)
print(run.stdout)
if run.stderr:
    print(run.stderr, file=sys.stderr)
versions = {}
for name in ("numpy", "scipy", "pandas", "scikit-learn", "pytest", "pydantic", "pint"):
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = "unavailable"
files = sorted((root/"src"/"equipment_diagnostics").glob("*.py"))
source_hash = hashlib.sha256(b"".join(f.name.encode()+f.read_bytes() for f in files)).hexdigest()
report = {"schema": "equipment-diagnostics.integration-verification.v1", "python": platform.python_version(),
          "platform": platform.system(), "source_sha256": source_hash, "upstream_revisions": revisions,
          "dependencies": versions, "exit_code": run.returncode, "pytest_output": run.stdout.strip(),
          "scope": "Actual object/serialization and one Monitor path; no native solver/field qualification.",
          "rotorvibe": "Inspected only; no adapter test claimed."}
folder = root/"outputs"/"python_verification"
folder.mkdir(parents=True, exist_ok=True)
(folder/"integration_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
raise SystemExit(run.returncode or (1 if "skipped" in run.stdout else 0))
