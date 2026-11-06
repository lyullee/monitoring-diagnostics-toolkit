"""Ranks9/12: actual channel/label availability, including unusable acquisitions."""
import hashlib,io,json,zipfile
from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/completion_7_13'
NEW=ROOT/'research_support/public_data/completion_20261106'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    e=NEW/'21987832/Extruder Parameters.zip';z=zipfile.ZipFile(e);files=[]
    for name in z.namelist():
        if not name.endswith('.csv'):continue
        d=pd.read_csv(io.BytesIO(z.read(name)));files.append(dict(file=name,rows=len(d),columns=list(d),member_sha256=hashlib.sha256(z.read(name)).hexdigest()))
    p=NEW/'20582921/DataSet Temperatue-Pressure.xlsx';d=pd.read_excel(p,header=None)
    time=pd.to_numeric(d.iloc[:,0],errors='coerce');mask=time.notna()&(time>=0)&(time<=900)
    profiles=[]
    for j in range(1,21,2):
        t=pd.to_numeric(d.iloc[:,j],errors='coerce');pressure=pd.to_numeric(d.iloc[:,j+1],errors='coerce')
        good=mask&t.notna()&pressure.notna()
        profiles.append(dict(temperature_column=j,pressure_column=j+1,rows=int(good.sum()),
            temperature_c=[float(t[good].min()),float(t[good].max())],pressure_gauge_pa=[float(pressure[good].min()),float(pressure[good].max())]))
    column=ROOT/'research_support/public_data/column/data.zip';cz=zipfile.ZipFile(column)
    metadata=[]
    for n in cz.namelist():
        if not n.endswith('.yaml'):continue
        text=cz.read(n).decode();metadata.append(dict(file=n,member_sha256=hashlib.sha256(cz.read(n)).hexdigest(),
            mentions_flooding='flood' in text.lower(),perturbations=[l.strip() for l in text.splitlines() if 'Perturbation:' in l]))
    result=dict(new_measured_acquisition=json.loads((NEW/'download_manifest.json').read_text()),
        extruder=dict(source='https://zenodo.org/records/21987832',archive_sha256=sha(e),run_files=len(files),rows=sum(r['rows'] for r in files),files=files,
            labels_file_in_downloaded_parameter_archive=any('label' in n.lower() for n in z.namelist()),
            use_status='not applicable to current pressure-flow model: no differential pressure or flow; described Labels.csv absent from published file list/parameter archive',
            fault_metrics=None,optional_not_downloaded='101MB high-frequency current archive, not required by current pressure-flow interfaces'),
        pipe_leak=dict(source='https://zenodo.org/records/20582921',raw_sha256=sha(p),profiles=profiles,
            workbook_scope='10 capillary-defect P/T profiles visible in first21columns; metadata describes a reference state but a separately identified healthy reference is not in these columns',
            use_status='cannot establish absolute inventory kg or FPR: absolute reference pressure, effective volume and qualified healthy records required',fault_metrics=None),
        column=dict(source='https://zenodo.org/records/17628963',archive_sha256=sha(column),experiments=len(metadata),metadata=metadata,
            use_status='real process-anomaly data, but no qualified internal vapor/liquid mass-flow mapping for existing hydraulic model and no flooding truth',
            generic_anomaly_label_not_equal_to_flooding=True,flooding_metrics=None),
        steam_trap=dict(fault_metrics=None,status='no downloadable, independently labelled raw T/acoustic corpus secured',
            checked_primary_sources=[
                dict(url='https://www.mdpi.com/1424-8220/26/21/6763',finding='6354 engineering-rule pseudo-labelled windows; confidential raw data; public code is not raw data or independent fault truth'),
                dict(url='https://www.sciencedirect.com/science/article/pii/S2772569325000374',finding='Background noise from nearby plant equipment; data used not specified by authors'),
                dict(url='https://www.mdpi.com/2079-9292/14/5/1010',finding='Field study exists; no raw downloadable corpus acquired in this search')]),
        vaporizer_related=dict(url='https://data.mendeley.com/datasets/93mr76p6c4/1',
            finding='Provider explicitly describes calculation results of frost model; not an actual measured fault dataset. Not recategorised as measured validation.'),
        boiler=dict(actual_fault_metrics=None,status='configured equilibrium inventory plus physical/simulation verification; geometry/void measurements unavailable for actual qualification'))
    (OUT/'scope_availability.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(new_corpora=3,extruder_runs=len(files),extruder_rows=result['extruder']['rows'],pipe_profiles=len(profiles),column_experiments=len(metadata),steam_raw_secured=False),indent=2))
if __name__=='__main__':main()
