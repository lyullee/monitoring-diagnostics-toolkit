"""Six-stage acceptance checks with explicit inputs and expected answers."""
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from equipment_diagnostics import SensorBatch, create_diagnostic, StreamingDiagnostic
from equipment_diagnostics.io import read_json, write_json


def sample(t, values, units, **kw):
    return SensorBatch(np.asarray(t, float), np.column_stack([np.broadcast_to(v, (len(t),))
        for v in values.values()]), tuple(values), tuple(units), "clock", "asset", "synthetic", **kw)


def example(kind):
    # role: (constant SI input, unit); the oracle answers below are handwritten.
    definitions = {
        "mass_balance": ({"inventory_mass": (0,"kg"), "inflow": (1,"kg/s"), "outflow": (.5,"kg/s")},
                         {"loss_limit_kg_s": .1, "window_s": 10}, "unaccounted_loss_kg_s", .2),
        "boiler_mass_balance": ({"inventory_mass": (0,"kg"), "inflow": (1,"kg/s"), "outflow": (.5,"kg/s")},
                         {"loss_limit_kg_s": .1, "window_s": 10}, "unaccounted_loss_kg_s", .2),
        "heat_exchanger": ({"hot_in": (360,"K"), "hot_out": (340,"K"), "cold_in": (290,"K"),
            "cold_out": (310,"K"), "hot_flow": (2,"kg/s"), "cold_flow": (2,"kg/s")},
            {"cp_hot_j_kg_k":4180, "cp_cold_j_kg_k":4180}, "ua_w_k", 3344.),
        "hydraulic_resistance": ({"pressure_drop": (400,"Pa"), "volume_flow": (.02,"m3/s")},
            {"reference_flow_m3_s":.01,"flow_exponent":2}, "normalized_pressure_drop_pa", 100.),
        "vaporizer": ({"outlet_temperature": (270,"K"), "predicted_temperature": (290,"K"),
            "mass_flow": (2,"kg/s"), "inlet_enthalpy": (100,"J/kg"), "outlet_enthalpy": (500,"J/kg")},
            {"shortfall_limit_k":5}, "absorbed_duty_w", 800.),
        "ro_membrane": ({"permeate_flow":(1e-4,"m3/s"), "net_driving_pressure":(1e6,"Pa"),
            "temperature_correction":(1,"1")}, {"membrane_area_m2":10}, "normalized_permeability_m_pa_s",1e-11),
        "valve_tracking": ({"command":(.5,"1"),"position":(.6,"1")},
            {"error_limit_fraction":.05}, "tracking_error_fraction",.1),
        "column_hydraulics": ({"pressure_drop":(400,"Pa"),"vapor_flow":(2,"kg/s"),"liquid_flow":(1,"kg/s")},
            {"reference_vapor_flow_kg_s":1,"reference_liquid_flow_kg_s":1,"vapor_exponent":2,
             "liquid_exponent":0}, "normalized_pressure_drop_pa",100.),
        "steam_trap": ({"steam_temperature":(400,"K"),"trap_temperature":(340,"K"),
            "acoustic_level":(.1,"1"),"supply_on":(1,"1")}, {"acoustic_quiet_max":.2,
            "acoustic_loud_min":2,"cold_margin_k":40,"hot_margin_k":10}, "cold_quiet_score",1.5),
        "chiller_performance": ({"chilled_in":(285,"K"),"chilled_out":(280,"K"),"cooling_out":(308,"K"),
            "evaporating_temperature":(275,"K"),"condensing_temperature":(313,"K"),
            "chilled_flow":(2,"kg/s"),"electric_power":(20000,"W")}, {}, "cop",2.09),
    }
    d, params, metric, answer = definitions[kind]
    t = np.arange(30.)
    vals = {k:v for k,(v,u) in d.items()}
    if "inventory_mass" in vals:
        vals["inventory_mass"] = 100+.3*t
    b = sample(t, vals, [u for v,u in d.values()], metadata={"enthalpy_basis_id":"shared"})
    m = create_diagnostic(kind, channels={k:k for k in d}, **params)
    if m.reference_metric:
        m.fit(b)
    return m, b, metric, answer


KINDS = ["mass_balance", "boiler_mass_balance", "heat_exchanger", "hydraulic_resistance", "vaporizer",
         "ro_membrane", "valve_tracking", "column_hydraulics", "steam_trap", "chiller_performance"]


def changed(b, column, value, **kw):
    x = b.values.copy(); x[:, b.channels.index(column)] = value
    fields = dict(time_s=b.time_s, values=x, channels=b.channels, units=b.units, clock_id=b.clock_id,
                  asset_id=b.asset_id, origin=b.origin, metadata=b.metadata)
    fields.update(kw)
    return SensorBatch(**fields)


@pytest.mark.parametrize("kind", KINDS)
def test_input_missing_unit_each_module(kind, record_property):
    m,b,_,_ = example(kind)
    u = list(b.units); u[0] = ""
    record_property("input", "first selected sensor has no unit")
    record_property("expected", "ValueError; no result")
    with pytest.raises(ValueError, match="units"):
        changed(b, b.channels[0], b.values[:,0], units=tuple(u))


@pytest.mark.parametrize("kind", KINDS)
def test_input_incompatible_unit_each_module(kind):
    m,b,_,_ = example(kind)
    u = list(b.units); u[0] = "wrong_unit"
    with pytest.raises(ValueError, match="expected"):
        m.score(changed(b,b.channels[0],b.values[:,0],units=tuple(u)))


@pytest.mark.parametrize("issue", ["shape", "duplicate_channel", "mask", "clock", "asset", "blank_unit"])
def test_input_inconsistent_contract(issue):
    args = dict(time_s=[0,1], values=[[1],[2]], channels=("x",), units=("1",),
                clock_id="c", asset_id="a", origin="synthetic")
    if issue == "shape": args["values"] = [[1]]
    if issue == "duplicate_channel": args.update(values=[[1,2],[2,3]],channels=("x","x"),units=("1","1"))
    if issue == "mask": args["valid"] = [[1],[2]]
    if issue == "clock": args["time_s"] = [1,1]
    if issue == "asset": args["asset_id"] = " "
    if issue == "blank_unit": args["units"] = (" ",)
    with pytest.raises(ValueError): SensorBatch(**args)


@pytest.mark.parametrize("value", [-1,0,float("nan"),float("inf"),True])
def test_input_bad_parameter(value):
    with pytest.raises(ValueError):
        create_diagnostic("vaporizer", channels={"outlet_temperature":"t","predicted_temperature":"p",
            "mass_flow":"f"}, shortfall_limit_k=value)


@pytest.mark.parametrize("kind", KINDS)
def test_input_nonfinite_measurement_becomes_unknown(kind):
    m,b,_,_ = example(kind)
    r = m.score(changed(b,b.channels[0],np.nan))
    assert not r.valid.any() and not r.alarms.any() and set(r.states)=={"UNKNOWN"}
    json.dumps(r.to_dict(),allow_nan=False)


@pytest.mark.parametrize("kind", KINDS)
def test_formula_hand_calculation(kind, record_property):
    m,b,metric,answer = example(kind)
    r = m.score(b)
    assert r.valid.any()
    values = r.metrics[metric][r.valid]
    record_property("input", json.dumps({"first_row": b.values[0].tolist(), "units": b.units,
                                        "parameters":m.params}))
    record_property("expected", f"{metric} = {answer}")
    record_property("observed", float(values[-1]))
    record_property("maximum_absolute_error", float(np.max(np.abs(values-answer))))
    np.testing.assert_allclose(values,answer,rtol=1e-12,atol=0)


@pytest.mark.parametrize("kind", KINDS)
def test_extreme_invalid_or_overflow_is_unknown(kind, record_property):
    m,b,_,_ = example(kind)
    role, value = {
        "mass_balance": ("inflow",1e308), "boiler_mass_balance": ("inflow",1e308),
        "heat_exchanger": ("hot_flow",1e308), "hydraulic_resistance": ("pressure_drop",1e308),
        "vaporizer": ("outlet_enthalpy",1e308), "ro_membrane": ("temperature_correction",1e308),
        "valve_tracking": ("position",np.nextafter(1.,2.)), "column_hydraulics": ("pressure_drop",1e308),
        "steam_trap": ("steam_temperature",1e308), "chiller_performance": ("chilled_flow",1e308),
    }[kind]
    if kind == "hydraulic_resistance": b = changed(b,"volume_flow",1e-200)
    if kind == "column_hydraulics": b = changed(b,"vapor_flow",1e-200)
    if kind == "ro_membrane": b = changed(b,"permeate_flow",1e308)
    if kind == "steam_trap":
        m = create_diagnostic(kind,channels=m.channels,acoustic_quiet_max=.2,acoustic_loud_min=2,
                              cold_margin_k=1e-100,hot_margin_k=0)
    record_property("input", f"{role}={value}; extreme scaling / outside domain")
    record_property("expected", "UNKNOWN, no alarm, JSON null for invalid scores")
    with np.errstate(all="ignore"):
        r = m.score(changed(b,role,value))
    assert not r.valid.any() and not r.alarms.any()
    assert set(r.states)=={"UNKNOWN"}
    assert all(s is None for s in r.to_dict()["scores"])
    json.dumps(r.to_dict(),allow_nan=False)


@pytest.mark.parametrize("kind", ["hydraulic_resistance","ro_membrane","column_hydraulics","chiller_performance"])
def test_extreme_positive_result_underflow_is_unknown(kind, record_property):
    m,b,_,_ = example(kind)
    if kind == "hydraulic_resistance":
        b = changed(b,"pressure_drop",np.nextafter(0.,1.))  # positive DP * .25 rounds to zero
    elif kind == "ro_membrane":
        b = changed(changed(b,"permeate_flow",1e-300),"temperature_correction",1e-100)
    elif kind == "column_hydraulics":
        b = changed(b,"pressure_drop",np.nextafter(0.,1.))
    else:
        b = changed(changed(b,"chilled_flow",1e-300),"electric_power",2e-296)
        m.fit(b)  # a finite normal COP at the same tiny load, so load gating doesn't conceal the issue
        b = changed(b,"electric_power",1e300)
    record_property("input", "positive factors with a product/ratio below float64 range")
    record_property("expected", "UNKNOWN; distinguish arithmetic zero from measured zero")
    with np.errstate(all="ignore"): r = m.score(b)
    assert not r.valid.any() and not r.alarms.any()


def test_extreme_window_below_clock_resolution():
    t = 1e16+np.arange(20.)*2
    b = sample(t,{"m":100.,"i":1.,"o":0.},["kg","kg/s","kg/s"])
    m = create_diagnostic("mass_balance",channels={"inventory_mass":"m","inflow":"i","outflow":"o"},
                          loss_limit_kg_s=.1,window_s=.1)
    r = m.score(b)
    assert not r.valid.any() and not r.alarms.any()
    assert set(r.reasons)=={"inventory_window_below_clock_resolution"}


@pytest.mark.parametrize("score,alarm", [(1.,False),(np.nextafter(1.,2.),True)])
def test_extreme_alarm_threshold_boundary(score,alarm):
    b = sample(np.arange(3.),{"u":0.,"x":score*.25},["1","1"])
    m = create_diagnostic("valve_tracking",channels={"command":"u","position":"x"},error_limit_fraction=.25)
    assert m.score(b).alarms.tolist()==[alarm]*3


@pytest.mark.parametrize("kind", KINDS)
def test_connection_reference_json_and_chunked_result(kind, tmp_path):
    m,b,_,_ = example(kind)
    if m.reference_metric:
        path = tmp_path/"reference.json"; write_json(path,m.reference)
        m.set_reference(read_json(path))
    expected = m.score(b)
    stream = StreamingDiagnostic(m)
    pieces = [stream.push(b.subset(slice(i,i+7))) for i in range(0,len(b.time_s),7)]
    for field in ("scores","valid","alarms"):
        np.testing.assert_allclose(np.concatenate([getattr(p,field) for p in pieces]),
                                   getattr(expected,field),equal_nan=True)
    for p in pieces:
        assert p.metadata["asset_id"]==b.asset_id and p.metadata["clock_id"]==b.clock_id
        assert p.metadata["origin"]==b.origin
    path = tmp_path/"result.json"; write_json(path,expected.to_dict())
    assert read_json(path)["metadata"]["input_fingerprint"]==b.fingerprint


def generate(directory):
    path = Path(__file__).parents[1]/"examples"/"generate_demo.py"
    spec = importlib.util.spec_from_file_location("acceptance_demo",path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.generate(directory)


@pytest.mark.parametrize("variant", ["normal","fault","all_missing","wrong_unit"])
def test_end_to_end_fresh_processes(variant,tmp_path,record_property):
    generate(tmp_path)
    cfg = tmp_path/"config.json"; ref = tmp_path/"ref.json"; out = tmp_path/"report.json"
    def run(command,data,output,*extra):
        return subprocess.run([sys.executable,"-m","equipment_diagnostics",command,"--config",str(cfg),
            "--data",str(data),"--output",str(output),*extra],capture_output=True,text=True)
    fit = run("fit",tmp_path/"normal.csv",ref)
    assert fit.returncode==0,fit.stderr
    data = tmp_path/("normal.csv" if variant=="normal" else "operation.csv")
    if variant=="all_missing":
        config = read_json(cfg)
        with data.open(encoding="utf-8",newline="") as f:
            reader=csv.DictReader(f); fields=reader.fieldnames; rows=list(reader)
        for row in rows:
            for k in config["units"]: row[k]=""
        with data.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    if variant=="wrong_unit":
        config=read_json(cfg); config["units"]["inventory_kg"]="g"; write_json(cfg,config)
    result = run("run",data,out,"--reference",str(ref))
    record_property("input", f"CSV + JSON config + separately fitted normal reference; {variant}")
    record_property("observed", f"fit exit={fit.returncode}; run exit={result.returncode}")
    if variant=="wrong_unit":
        assert result.returncode==2 and not out.exists()
        return
    assert result.returncode==0,result.stderr
    report=read_json(out)
    assert len(report["diagnostics"])==10
    expected = {"normal":"no_alarm","fault":"suspected_anomaly","all_missing":"insufficient_data"}[variant]
    assert {v["status"] for v in report["summaries"].values()}=={expected}
    for r in report["diagnostics"].values():
        assert r["metadata"]["asset_id"]==report["asset_id"]
        assert r["metadata"]["clock_id"]==report["clock_id"]
        if variant=="fault":
            assert not any(a for t,a in zip(r["time_s"],r["alarms"]) if t<900)
        if variant=="all_missing": assert set(r["states"])=={"UNKNOWN"}
