"""Rank10 real wet-coil experiments: whole sheet train/cal/eval, fixed physics."""
import csv,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import SensorBatch,WetCoilAirsideDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/completion_7_13/wet_coil'
RAW=ROOT/'research_support/public_data/acquisition_20261105/coil_frost/Supplemental data.xlsx'
CHANNELS=dict(pressure_drop='dp',volume_flow='q',dry_air_flow='m',inlet_temperature='ti',
    outlet_temperature='to',inlet_humidity='wi',outlet_humidity='wo')
def load(sheet):
    d=pd.read_excel(RAW,sheet_name=sheet).iloc[1:].reset_index(drop=True)
    for k in d.columns[1:]:d[k]=pd.to_numeric(d[k],errors='raise')
    q=d.Flow.to_numpy(float)*.0004719474432
    b=SensorBatch(np.arange(len(d))*60.,np.column_stack((d.P1,q,d.m_a,d.T_a_i_DB+273.15,d.T_a_o+273.15,d.W_i/1000,d.W_o/1000)),
        ('dp','q','m','ti','to','wi','wo'),('Pa','m3/s','kg/s','K','K','1','1'),
        'elapsed_minutes','microchannel_lab_coil','Mendeley:s6d23g2m2w.1',
        metadata={'run':sheet,'dry_air_flow':'provider-derived Flow/specific_volume','humidity':'provider-derived psychrometrics'})
    return b,d
def aggregate(rows): return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm','valid','eligible')])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    train,_=load('Baseline');cal,_=load('RH85');models={}
    # No fault run is inspected for model or threshold selection.
    for name,exponent in [('uncompensated',0.),('flow_density_corrected',2.)]:
        m=WetCoilAirsideDiagnostic(CHANNELS,reference_volume_flow_m3_s=.1,flow_exponent=exponent,
            persistence_s=60,max_gap_s=120)
        m.fit(train).calibrate(cal,quantile=.99);models[name]=m
    protocol=dict(version=__version__,evidence='measured controlled experiments, one coil',
        train='Baseline',calibration='RH85',evaluation=['V1','V2','F1','F2','F3','F4'],
        normal_target='clean surface despite ongoing frosting; V1/V2 different face velocities',
        fault_target='provider controlled surface fouling F1..F4; severity-specific quantitative fouling mass unknown',
        models={k:dict(params=m.params,reference=m.reference) for k,m in models.items()},
        raw_sha256=hashlib.sha256(RAW.read_bytes()).hexdigest(),
        newness='New application/evaluation of a previously acquired workbook, not newly independent asset data')
    fp=OUT/'frozen.json';fp.write_text(json.dumps(protocol,indent=2),encoding='utf-8');frozen_hash=hashlib.sha256(fp.read_bytes()).hexdigest()
    rows={k:[] for k in models};audit=[];files=[]
    with (OUT/'predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['run','time_s','label',*[k+'_'+a for k in models for a in ('valid','alarm','score')]])
        for s in protocol['evaluation']:
            b,d=load(s);rr={k:m.score(b) for k,m in models.items()};fault=s.startswith('F')
            for k,r in rr.items():rows[k].append(dict(label=np.full(len(b.time_s),fault),alarm=r.alarms,valid=r.valid,eligible=np.ones(len(b.time_s),bool)))
            for i,t in enumerate(b.time_s):w.writerow([s,t,int(fault),*[v for r in rr.values() for v in (int(r.valid[i]),int(r.alarms[i]),r.scores[i] if r.valid[i] else '')]])
            files.append(dict(run=s,rows=len(d),metrics={k:aggregate([rows[k][-1]]) for k in models}))
        for s in ['Baseline','RH85',*protocol['evaluation']]:
            b,d=load(s);r=models['flow_density_corrected']._raw(b)[0]
            # Independently test producer-derived columns, not diagnostic labels.
            q=d.m_a.to_numpy()*(d.H_i.to_numpy()-d.H_o.to_numpy())*1000
            removal=d.m_a.to_numpy()*(d.W_i.to_numpy()-d.W_o.to_numpy()) # g/s
            audit.append(dict(run=s,rows=len(d),provider_heat_identity_max_abs_w=float(np.max(abs(q-d.Q_a.to_numpy()*1000))),
                m_w_vs_g_per_min_max_abs=float(np.max(abs(d.m_w.to_numpy()-removal*60))),
                cumulative_m_t_vs_sum_m_w_max_abs_g=float(np.max(abs(d.m_t.to_numpy()-np.cumsum(d.m_w.to_numpy())))),
                enthalpy_formula_vs_provider_heat_max_abs_w=float(np.max(abs(r['air_side_heat_w']-q)))))
    assert hashlib.sha256(fp.read_bytes()).hexdigest()==frozen_hash
    result=dict(version=__version__,frozen_sha256=frozen_hash,comparison={k:aggregate(r) for k,r in rows.items()},files=files,
        arithmetic_audit=audit,new_independent_asset_fault_metrics=None,
        limitations=['Only one clean training run and one humidity calibration run; no replicate coil/field qualification.',
            'Flow^2 correction is an explicit inertial approximation, not a frost porous-medium model.',
            'Provider m_w label says g/s but values follow g/min; m_t follows sum(m_w). Never treat m_w as measured g/s.',
            'Heat/airflow/humidity columns are partly provider-derived; identities do not establish sensor accuracy.',
            'No brine mass flow: no two-sided energy balance or UA validated. Restriction detection is not thermal degradation isolation.',
            'No automatic replacement of existing dry heat exchanger model.'])
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result['comparison'],indent=2))
if __name__=='__main__':main()
