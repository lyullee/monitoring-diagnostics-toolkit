"""Actual object bridge; install process-monitoring-toolkit separately first."""
import numpy as np
from process_monitoring import SignalBatch, Monitor, WindowFeatures, create_detector
from equipment_diagnostics import VaporizerDiagnostic
from equipment_diagnostics.adapters import (
    from_process_monitoring, to_detection_result, residual_signal_batch,
)

time = np.arange(30, dtype=float)
signals = SignalBatch(time, np.column_stack((time*0+275, time*0+290, time*0+0.1)),
                      ("TT_OUT", "TT_EXPECTED", "FT_GAS"), ("K", "K", "kg/s"),
                      origin="synthetic")
batch = from_process_monitoring(signals, clock_id="demo_clock", asset_id="vaporizer_01")
diagnostic = VaporizerDiagnostic(
    {"outlet_temperature": "TT_OUT", "predicted_temperature": "TT_EXPECTED", "mass_flow": "FT_GAS"},
    shortfall_limit_k=5.0,
)
result = diagnostic.score(batch)
print(result.summary())
print(to_detection_result(result).to_dict()["schema"])

# Engineering bound demonstration, not learned threshold calibration.
features = residual_signal_batch(result)
monitor = Monitor(create_detector("bounds", upper=1.0), WindowFeatures(window=1))
monitor.fit(features)
print("Existing Monitor alarms:", int(monitor.score(features).alarms.sum()))
