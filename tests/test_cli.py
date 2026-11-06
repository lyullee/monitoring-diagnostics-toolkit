import importlib.util
import json
from pathlib import Path
from equipment_diagnostics.cli import main


def make_demo(path):
    script = Path(__file__).parents[1]/"examples"/"generate_demo.py"
    spec = importlib.util.spec_from_file_location("demo", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate(path)


def test_demo_cli_all_detectors_and_references(tmp_path):
    make_demo(tmp_path)
    cfg = str(tmp_path/"config.json")
    ref = str(tmp_path/"reference.json")
    assert main(["fit", "--config", cfg, "--data", str(tmp_path/"normal.csv"), "--output", ref]) == 0
    report = tmp_path/"report.json"
    assert main(["run", "--config", cfg, "--data", str(tmp_path/"operation.csv"),
                 "--reference", ref, "--output", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert len(data["summaries"]) == 10
    assert all(s["status"] == "suspected_anomaly" for s in data["summaries"].values())
    for r in data["diagnostics"].values():
        assert not any(alarm for t, alarm in zip(r["time_s"], r["alarms"]) if t < 900)
    filt = data["diagnostics"]["filter"]
    i = filt["time_s"].index(840)
    assert filt["valid"][i] is False and filt["states"][i] == "UNKNOWN"


def test_input_collision_and_missing_reference_fail(tmp_path):
    make_demo(tmp_path)
    cfg, normal = str(tmp_path/"config.json"), str(tmp_path/"normal.csv")
    original = Path(normal).read_bytes()
    assert main(["fit", "--config", cfg, "--data", normal, "--output", normal]) == 2
    assert Path(normal).read_bytes() == original
    out = tmp_path/"failure.json"
    assert main(["run", "--config", cfg, "--data", normal, "--output", str(out)]) == 2
    assert not out.exists()


def test_duplicate_json_keys_rejected(tmp_path):
    from equipment_diagnostics.io import read_json
    import pytest
    file = tmp_path/"duplicate.json"
    file.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        read_json(file)


def test_cli_lists_descriptions(capsys):
    assert main(["list", "--details"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert len(catalog) == 11
    assert all(row["name_ko"] and row["description"] for row in catalog)
