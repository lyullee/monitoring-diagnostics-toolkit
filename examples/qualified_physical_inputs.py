"""Run with Python; explicit illustrative properties, NOT a real plant configuration."""
import json
import numpy as np
from equipment_diagnostics import SensorBatch,PiecewiseVaporizer,VaporizerDiagnostic

n=10
b=SensorBatch(np.arange(n)*10.,np.column_stack((np.ones(n),np.full(n,-40000.),
    np.full(n,350.),np.full(n,300.))),('flow','hin','source','out'),('kg/s','J/kg','K','K'),
    'example_clock','example_vaporizer','simulation',metadata={'enthalpy_basis_id':'example:fixed-pressure'})
normal=PiecewiseVaporizer(saturation_temperature_k=300,latent_heat_j_kg=100000,
    liquid_cp_j_kg_k=2000,vapor_cp_j_kg_k=1000,ua_w_k=5000,property_basis_id='example:fixed-pressure')
x=normal.transform(b,mass_flow_channel='flow',inlet_enthalpy_channel='hin',source_temperature_channel='source')
r=VaporizerDiagnostic(dict(outlet_temperature='out',mass_flow='flow',predicted_temperature='predicted_outlet_k'),
    shortfall_limit_k=5).score(x)
print(json.dumps(r.to_dict(),indent=2,allow_nan=False))
