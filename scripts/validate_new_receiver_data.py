"""New independent measured data: physical indicator checks, not fault accuracy."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd
from equipment_diagnostics.heat_pump import heating_temperature_metrics

ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'research_support/public_data/gap_analysis_20261105/r290_receiver';OUT=ROOT/'outputs/diagnostic_gap_analysis'
EXPECTED={'README.md':'03f0c95ee71ef22f2cbdec0b295aea25','data_mapping.csv':'b672a31eb78d87295280a21db5240e2e','operating_points.csv':'59aa221a3991c7d5e6b79dd874ab11c8','thermodynamic.zip':'e8357dd17325ec11c82a6db058b4db88'}

def main():
    manifest=[]
    for name,md5 in EXPECTED.items():
        raw=(DATA/name).read_bytes();assert hashlib.md5(raw).hexdigest()==md5
        manifest.append(dict(file=str((DATA/name).relative_to(ROOT)),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),publisher_md5_verified=True))
    with zipfile.ZipFile(DATA/'thermodynamic.zip') as z:
        assert z.testzip() is None
        d=pd.read_csv(io.BytesIO(z.read('thermodynamic/thermodynamic_averaged_with_uncertainty.csv')))
    num=lambda k:d[k].to_numpy(float)
    q=num('Q_flow_con_hyd_kW')*1000;p=num('P_el_com_kW')*1000;te=num('T_e_C')+273.15;tc=num('T_c_C')+273.15;tl=num('T_con_out_C')+273.15;td=num('T_com_out_C')+273.15
    physical=(q>0)&(p>0)&(te>0)&(tc>te)&np.isfinite(np.column_stack((q,p,te,tc,tl,td))).all(axis=1)
    m=heating_temperature_metrics(q,p,te,tc,tl,td);checks={}
    for name,provider,uncertainty in [('heating_cop','COP_hyd','U_COP_hyd'),('subcooling_k','dT_sc_con_out_K','U_dT_sc_con_out_K')]:
        v=physical&np.isfinite(m[name])&np.isfinite(num(provider));error=abs(m[name][v]-num(provider)[v]);u=num(uncertainty)[v]
        checks[name]=dict(compared_rows=int(v.sum()),max_absolute_difference=float(error.max()),median_absolute_difference=float(np.median(error)),
            rows_within_publisher_expanded_uncertainty=int((error<=u).sum()),note='Provider-derived identity consistency, not independent sensor accuracy or fault validation.')
    result=dict(source='https://zenodo.org/records/22097811',independent_corpus=True,previously_used_for_model_development=False,
        rows=len(d),columns=len(d.columns),sessions=int(d.measurement_id.nunique()),physical_valid_rows=int(physical.sum()),
        files=manifest,checks=checks,fault_accuracy=None,fault_recall=None,false_positive_rate=None,
        qualification='New measured physical-indicator consistency only. No training, calibration or threshold selection from this dataset.',
        unavailable=['No evaporator-water-flow-reduction truth','Averaged sessions, no chronological sample clock for temporal alarms',
            'No declared nominal heat-demand input for the existing conditioned reference','Electrical compressor Hz not assumed to be shaft revolutions/s'],
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'src/equipment_diagnostics/heat_pump.py']})
    OUT.mkdir(exist_ok=True,parents=True);(OUT/'new_independent_physical_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['rows','sessions','physical_valid_rows','checks']},indent=2))
if __name__=='__main__':main()
