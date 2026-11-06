"""Generate deterministic synthetic normal/operation data; no plant accuracy claim."""
import csv
import json
import math
from pathlib import Path


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    units = {"inventory_kg": "kg", "in_kg_s": "kg/s", "out_kg_s": "kg/s", "vent_kg_s": "kg/s",
             "hi_k": "K", "ho_k": "K", "ci_k": "K", "co_k": "K", "hf_kg_s": "kg/s",
             "cf_kg_s": "kg/s", "dp_pa": "Pa", "q_m3_s": "m3/s", "rho_kg_m3": "kg/m3",
             "gas_out_k": "K", "gas_expected_k": "K", "gas_flow_kg_s": "kg/s",
             "ro_flow_m3_s": "m3/s", "ndp_pa": "Pa", "tcf": "1", "command": "1",
             "position": "1", "operating": "1", "column_dp_pa": "Pa",
             "vapor_flow_kg_s": "kg/s", "liquid_flow_kg_s": "kg/s",
             "steam_k": "K", "trap_k": "K", "acoustic": "1", "supply_on": "1",
             "chilled_in_k": "K", "chilled_out_k": "K", "cooling_out_k": "K",
             "evap_k": "K", "cond_k": "K", "chilled_flow_kg_s": "kg/s", "electric_power_w": "W"}
    alarm = {"persistence_s": 20.0, "max_gap_s": 15.0, "allowed_modes": ["steady"]}
    specs = []
    def spec(ident, kind, channels, parameters):
        specs.append({"id": ident, "kind": kind, "channels": {**channels, "operating": "operating"},
                      "parameters": parameters, "alarm": alarm})
    mapping = {"inventory_mass": "inventory_kg", "inflow": "in_kg_s", "outflow": "out_kg_s",
               "known_loss": "vent_kg_s"}
    spec("tank", "mass_balance", mapping, {"loss_limit_kg_s": 0.05, "window_s": 60.0})
    spec("boiler", "boiler_mass_balance", mapping, {"loss_limit_kg_s": 0.05, "window_s": 60.0})
    spec("exchanger", "heat_exchanger", {"hot_in": "hi_k", "hot_out": "ho_k", "cold_in": "ci_k",
         "cold_out": "co_k", "hot_flow": "hf_kg_s", "cold_flow": "cf_kg_s"},
         {"cp_hot_j_kg_k": 4180.0, "cp_cold_j_kg_k": 4180.0})
    spec("filter", "hydraulic_resistance", {"pressure_drop": "dp_pa", "volume_flow": "q_m3_s",
         "density": "rho_kg_m3"}, {"reference_flow_m3_s": 0.01, "flow_exponent": 2.0})
    spec("vaporizer", "vaporizer", {"outlet_temperature": "gas_out_k",
         "predicted_temperature": "gas_expected_k", "mass_flow": "gas_flow_kg_s"},
         {"shortfall_limit_k": 5.0, "minimum_outlet_k": 270.0})
    spec("membrane", "ro_membrane", {"permeate_flow": "ro_flow_m3_s", "net_driving_pressure": "ndp_pa",
         "temperature_correction": "tcf"}, {"membrane_area_m2": 20.0})
    spec("valve", "valve_tracking", {"command": "command", "position": "position"},
         {"error_limit_fraction": 0.04})
    spec("column", "column_hydraulics", {"pressure_drop": "column_dp_pa",
         "vapor_flow": "vapor_flow_kg_s", "liquid_flow": "liquid_flow_kg_s"},
         {"reference_vapor_flow_kg_s": 2.0, "reference_liquid_flow_kg_s": 3.0,
          "vapor_exponent": 2.0, "liquid_exponent": 0.5})
    spec("steam_trap", "steam_trap", {"steam_temperature": "steam_k", "trap_temperature": "trap_k",
         "acoustic_level": "acoustic", "supply_on": "supply_on"},
         {"acoustic_quiet_max": 0.2, "acoustic_loud_min": 2.0, "cold_margin_k": 40, "hot_margin_k": 10})
    spec("chiller", "chiller_performance", {"chilled_in": "chilled_in_k", "chilled_out": "chilled_out_k",
         "cooling_out": "cooling_out_k", "evaporating_temperature": "evap_k", "condensing_temperature": "cond_k",
         "chilled_flow": "chilled_flow_kg_s", "electric_power": "electric_power_w"}, {})
    config = {"schema": "equipment-diagnostics.config.v1", "time_column": "time_s",
              "episode_column": "episode", "mode_column": "mode", "clock_id": "demo_elapsed_s",
              "asset_id": "synthetic_facility", "origin": "synthetic", "units": units,
              "diagnostics": specs,
              "metadata": {"note": "Synthetic combined signals, not a coupled plant simulation."}}
    (directory/"config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    for name, start in (("normal", 0), ("operation", 600)):
        with (directory/(name+".csv")).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["time_s", *units, "episode", "mode"])
            writer.writeheader()
            for t in range(start, start+600, 5):
                fault = name == "operation" and t >= 900
                q = 0.01*(1+0.15*math.sin(t/100))
                hi = 360+0.2*math.sin(t/100)
                transfer = 12 if fault else 20+0.1*math.sin(t/80)
                command = 0.5+0.1*math.sin(t/50)
                expected = 285+0.1*math.sin(t/25)
                vapor_flow = 2+0.1*math.sin(t/100)
                liquid_flow = 3+0.1*math.cos(t/100)
                row = {"time_s": t, "inventory_kg": 1000+0.15*t-0.15*max(t-900, 0),
                       "in_kg_s": 1, "out_kg_s": 0.8, "vent_kg_s": 0.05,
                       "hi_k": hi, "ho_k": hi-transfer, "ci_k": 290, "co_k": 290+transfer,
                       "hf_kg_s": 2, "cf_kg_s": 2, "q_m3_s": q, "rho_kg_m3": 1000,
                       "dp_pa": 10000*(q/0.01)**2*(1.6 if fault else 1),
                       "gas_out_k": expected-(12 if fault else 0), "gas_expected_k": expected,
                       "gas_flow_kg_s": 0.1, "ro_flow_m3_s": 1e-4*(0.65 if fault else 1),
                       "ndp_pa": 8e5, "tcf": 1, "command": command,
                       "position": 0.3 if fault else command, "operating": 1,
                       "column_dp_pa": 1000*(vapor_flow/2)**2*(liquid_flow/3)**0.5*(1.7 if fault else 1),
                       "vapor_flow_kg_s": vapor_flow, "liquid_flow_kg_s": liquid_flow,
                       "steam_k": 400, "trap_k": 340 if fault else 390,
                       "acoustic": 0.1 if fault else 0.5, "supply_on": 1,
                       "chilled_in_k": 285, "chilled_out_k": 280, "cooling_out_k": 308,
                       "evap_k": 275, "cond_k": 313, "chilled_flow_kg_s": 2,
                       "electric_power_w": 30000 if fault else 20000,
                       "episode": "demo", "mode": "steady"}
                if t == 840:
                    row["dp_pa"] = ""  # one missing measurement must stay UNKNOWN
                writer.writerow(row)
    (directory/"truth.json").write_text(json.dumps({"origin": "synthetic", "fault_start_s": 900,
        "expected_alarm_ids": [s["id"] for s in specs], "missing_filter_sample_s": 840}, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="outputs/python_demo")
    generate(p.parse_args().output)
