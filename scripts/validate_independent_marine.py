"""New independent physical apparatus, distinct target from HSE near-end-of-life risk.

All AF fault files remain evaluation only. The separate reference file is split
within each operating-load band with purged chronological blocks, before fits.
"""
import csv,hashlib,io,json,zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from equipment_diagnostics import SensorBatch,LoadConditionedPressureDiagnostic,__version__
from equipment_diagnostics.evaluation import binary_metrics

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/completion_7_13/independent_marine'
RAW=ROOT/'research_support/public_data/completion_20261106/19857425/Marine_Engine_Fault_Data_v1.zip'
CHANNELS=dict(pressure_drop='dp',shaft_power='power',engine_speed='speed')
def make(d,name,reference=False,episodes=None):
    return SensorBatch(d['Time' if reference else 'Time_rel'].to_numpy(float),
        np.column_stack((d['Compressor Filter Loss'],d['Shaft Power']*1000,d['Engine Speed']/60)),
        ('dp','power','speed'),('Pa','W','1/s'),'publisher_elapsed_clock','Matsui_MU323DGSC','Zenodo:19857425',
        episodes=episodes,metadata={'file':name,'target':'provider injected compressor-filter covering state; not HSE RUL'})
def metrics(rows):return binary_metrics(*[np.concatenate([r[k] for r in rows]) for k in ('label','alarm','valid','eligible')])

def main():
    OUT.mkdir(parents=True,exist_ok=True);z=zipfile.ZipFile(RAW)
    refname=next(n for n in z.namelist() if n.endswith('Reference_Data.csv'))
    d=pd.read_csv(io.BytesIO(z.read(refname)),skiprows=[1,2]);t=d.Time.to_numpy(float)
    assert np.all(np.diff(t)>0)
    # Fixed10kW bins use operating power, never pressure or fault outcomes.
    bands=np.floor(d['Shaft Power'].to_numpy()/10).astype(int)
    masks={k:np.zeros(len(d),bool) for k in ('train','calibration','normal_evaluation')}
    for band in np.unique(bands):
        ix=np.flatnonzero(bands==band);n=len(ix)
        if n<100:continue
        masks['train'][ix[:int(.4*n)]]=True
        masks['calibration'][ix[int(.5*n):int(.7*n)]]=True
        masks['normal_evaluation'][ix[int(.8*n):]]=True
    # Bin jitter can put neighbouring moments into different partitions. Enforce
    # an additional GLOBAL20s purge, including across adjacent load bins.
    def far_from(mask,reference):
        known=t[reference];j=np.searchsorted(known,t)
        distance=np.minimum(abs(t-known[np.clip(j,0,len(known)-1)]),abs(t-known[np.clip(j-1,0,len(known)-1)]))
        return mask&(distance>20)
    masks['calibration']=far_from(masks['calibration'],masks['train'])
    masks['normal_evaluation']=far_from(masks['normal_evaluation'],masks['train']|masks['calibration'])
    assert not any(np.any(masks[a]&masks[b]) for a,b in [('train','calibration'),('train','normal_evaluation'),('calibration','normal_evaluation')])
    bs={}
    for k,mask in masks.items():
        ix=np.flatnonzero(mask)
        # Artificial subset jumps cannot accumulate alarm persistence.
        ep=np.cumsum(np.r_[True,np.diff(ix)>1])
        bs[k]=make(d.iloc[ix],refname,True,ep)
    models={}
    for name,conditioned in [('constant_pressure',False),('load_conditioned_pressure',True)]:
        m=LoadConditionedPressureDiagnostic(CHANNELS,conditioned=conditioned,persistence_s=10,max_gap_s=5)
        m.fit(bs['train']).calibrate(bs['calibration'],quantile=.99);models[name]=m
    specs=sorted(n for n in z.namelist() if '/AF_Clogging/' in n and n.endswith('.csv'))
    frozen=dict(version=__version__,source='https://zenodo.org/records/19857425',raw_sha256=hashlib.sha256(RAW.read_bytes()).hexdigest(),
        split_indices={k:np.flatnonzero(mask).tolist() for k,mask in masks.items()},
        fingerprints={k:b.fingerprint for k,b in bs.items()},test_files=specs,
        policy='Fixed degree2/ridge.001, physical power/rpm context, q99 independent normal calibration; no test selection. Global20s partition purge after within-bin10% purges.',
        revision='Global purge strengthened after first run showed adjacent-bin timestamps. Original run archived. Same evaluation files reused for this integrity correction; not a second independent dataset.',
        models={k:dict(params=m.params,reference=m.reference) for k,m in models.items()},
        label_provenance='publisher Anomaly State from induced filter covering; not independently maintenance-confirmed field diagnoses',
        independence='Independent of HSE filtration apparatus; same marine engine within this new benchmark, not a cross-engine transfer test')
    fp=OUT/'frozen.json';fp.write_text(json.dumps(frozen,indent=2),encoding='utf-8');fsha=hashlib.sha256(fp.read_bytes()).hexdigest()
    rows={k:[] for k in models};files=[]
    with (OUT/'predictions.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['file','time_s','label',*[k+'_'+a for k in models for a in ('valid','alarm','score')]])
        for name in [refname,*specs]:
            if name==refname:b=bs['normal_evaluation'];label=np.zeros(len(b.time_s),bool)
            else:
                frame=pd.read_csv(io.BytesIO(z.read(name)),skiprows=[1,2]);b=make(frame,name);label=frame['Anomaly State'].to_numpy()
                assert np.isin(label,[0,1]).all();label=label.astype(bool)
            rr={k:m.score(b) for k,m in models.items()}
            for k,r in rr.items():rows[k].append(dict(label=label,alarm=r.alarms,valid=r.valid,eligible=np.ones(len(label),bool)))
            files.append(dict(file=name,rows=len(label),metrics={k:metrics([rows[k][-1]]) for k in models}))
            for i,t in enumerate(b.time_s):w.writerow([name,t,int(label[i]),*[x for r in rr.values() for x in (int(r.valid[i]),int(r.alarms[i]),r.scores[i] if r.valid[i] else '')]])
    assert hashlib.sha256(fp.read_bytes()).hexdigest()==fsha
    result=dict(version=__version__,evidence='new measured controlled experiment dataset',frozen_sha256=fsha,
        comparison={k:metrics(r) for k,r in rows.items()},files=files,
        limitations=['Pressure excess conditioned by engine state, not hydraulic resistance: air flow was not measured.',
            'Cannot compare these detection rates as improvements to HSE RUL<=30s: different targets and apparatus.',
            'Reference file splits share one experiment; whole fault files were excluded from fit/calibration.',
            'Anomaly onset supplied by publisher; progressive covering may be physically weak immediately after onset.'])
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result['comparison'],indent=2))
if __name__=='__main__':main()
