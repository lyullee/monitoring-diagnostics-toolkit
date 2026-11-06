"""Inventory real downloaded observations without fitting models or manufacturing labels.

Original archives remain unchanged. CSV copies are byte-exact; Excel exports are
separate convenience tables. Strict OOXML is read directly, without rewriting it.
"""
import csv
import hashlib
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'research_support'/'public_data'/'acquisition_20261105'
OUT=ROOT/'outputs'/'actual_data_acquisition'
TABLES=BASE/'tables'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def file_record(path):
    raw=path.read_bytes();return dict(path=str(path.relative_to(ROOT)),bytes=len(raw),sha256=sha(raw))
def frame_record(d):
    return dict(rows=len(d),columns=[str(c) for c in d.columns],missing_by_column={str(k):int(v) for k,v in d.isna().sum().items()})
def write_copy(raw,path):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);assert path.read_bytes()==raw
def strict_rows(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('{*}si')]
        sheet=next(n for n in z.namelist() if n.startswith('xl/worksheets/') and n.endswith('.xml'))
        root=ET.fromstring(z.read(sheet));rows=[]
        for row in root.findall('.//{*}row'):
            values={}
            for c in row.findall('{*}c'):
                letters=''.join(x for x in c.get('r','A1') if x.isalpha());index=0
                for letter in letters:index=index*26+ord(letter)-64
                v=c.find('{*}v');inline=c.find('{*}is')
                value=v.text if v is not None else ''.join(inline.itertext()) if inline is not None else ''
                if c.get('t')=='s':value=strings[int(value)]
                values[index-1]=value
            rows.append([values.get(i,'') for i in range(max(values,default=-1)+1)])
        return rows,root.tag.split('}')[0].lstrip('{')

def main():
    OUT.mkdir(parents=True,exist_ok=True);TABLES.mkdir(exist_ok=True)
    records=[];originals=[];derived=[]
    # HSE original train/test names and trial IDs are retained; no random split.
    path=BASE/'filter_hse'/'filter.zip';originals.append(file_record(path));frames={};info=[]
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        for name in ['Train_Data_CSV.csv','Test_Data_CSV.csv']:
            raw=z.read(name);dst=TABLES/'filter_hse'/name;write_copy(raw,dst);d=pd.read_csv(io.BytesIO(raw));frames[name]=d
            item=frame_record(d);item.update(file=name,source_split='train' if name.startswith('Train') else 'test',
                trial_records=int(d.Data_No.nunique()),zero_flow_rows=int((d.Flow_rate<=0).sum()),
                nonmonotonic_time_steps=sum(int((np.diff(g.Time)<=0).sum()) for _,g in d.groupby('Data_No')),
                original_member_sha256=sha(raw),copy=file_record(dst))
            info.append(item);derived.append(file_record(dst))
        write_copy(z.read('Preventive to Predictive Maintenance dataset.pdf'),BASE/'filter_hse'/'description.pdf')
    a,b=frames.values();same=[]
    cols=['Differential_pressure','Flow_rate','Time','Dust_feed']
    for ident,g in a.groupby('Data_No'):
        h=b[b.Data_No==ident];n=min(len(g),len(h))
        if np.array_equal(g[cols].values[:n],h[cols].values[:n]):same.append(int(ident))
    records.append(dict(id='filter_hse',title='HSE actual air-filter loading tests',
        source='https://www.kaggle.com/datasets/prognosticshse/preventive-to-predicitve-maintenance',version=8,
        evidence='laboratory_measured',license='CC BY 4.0',tables=info,trial_records=100,
        split_key='source_split + Data_No; IDs restart at 1 in each split',same_id_exact_equal_prefixes=same,
        relevant_modules=['hydraulic_resistance'],application_status='highest_priority_measured_degradation_candidate',
        limitations=['Provider failure criterion is DP>600Pa; RUL/failure targets are not independent clogging-onset labels.',
            'Both splits are right-censored; test RUL must not be an input feature or threshold-selection target.',
            'Pressure unit Pa and Time unit seconds verified; absolute Flow_rate unit is not yet established from the distributed description. No guessed SI conversion performed.',
            'Initial zero-flow samples retained and counted; no automatic interpolation or silent deletion.',
            'Train_Data_Uncensored.mat is preserved but not used to reconstruct hidden test targets.']))
    # Real membrane experiments; WEC-Sim-driven waveforms intentionally not downloaded.
    info=[];total=0
    for name in ['steady_state.zip','ramp.zip','sine.zip']:
        path=BASE/'ro_nrel'/name;originals.append(file_record(path))
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for member in z.namelist():
                if not member.endswith('.csv') or member.startswith('__MACOSX/'):continue
                raw=z.read(member);dst=TABLES/'ro_nrel'/member;write_copy(raw,dst)
                d=pd.read_csv(io.BytesIO(raw));item=frame_record(d);item.update(file=member,archive=name,
                    runtime_backward_steps=int((np.diff(d['Runtime (min)'])<0).sum()),copy=file_record(dst))
                info.append(item);total+=len(d);derived.append(file_record(dst))
    originals.append(file_record(BASE/'ro_nrel'/'README.rtf'))
    records.append(dict(id='ro_nrel',title='NREL actual dynamic reverse-osmosis membrane tests',
        source='https://mhkdr.openei.org/submissions/649',evidence='laboratory_measured',license='CC BY 4.0',
        tables=info,csv_files=len(info),rows=total,membrane='DuPont FilmTec SW30-4040',membrane_area_m2=7.4,
        documented_sampling_s=.25,relevant_modules=['ro_membrane'],application_status='normal_and_dynamic_response_validation_candidate',
        limitations=['No independently labeled membrane-fouling or damage events; pressure changes are commanded experiments, not faults.',
            'Osmotic pressure/temperature correction and permeate pressure require qualified calculation or documented boundary assumptions.',
            'Use experiment settings to segment concatenated tests and keep train/calibration/evaluation groups separate.',
            'Original water flux is calculated from permeate flow and area; it is not an independent flow sensor.',
            'WEC-Sim-driven records were not obtained or counted in this acquisition.']))
    # Wet/frosting coil, not a dry single-phase counterflow heat exchanger.
    path=BASE/'coil_frost'/'Supplemental data.xlsx';originals.append(file_record(path));info=[];total=0
    assert sha(path.read_bytes())=='fa935be6e8c81c917b61aecbcf2ecf1f076e2da012f77d27035b408cd740a0c5'
    x=pd.ExcelFile(path)
    for sheet in x.sheet_names:
        d=pd.read_excel(x,sheet_name=sheet,header=None);dst=TABLES/'coil_frost'/f'{sheet}.csv';dst.parent.mkdir(parents=True,exist_ok=True)
        d.to_csv(dst,index=False,header=False);n=int(d.iloc[2:,0].notna().sum());total+=n
        info.append(dict(sheet=sheet,data_rows=n,raw_rows=len(d),headers=d.iloc[0].fillna('').tolist(),
            units=d.iloc[1].fillna('').tolist(),export=file_record(dst)));derived.append(file_record(dst))
    records.append(dict(id='coil_frost',title='Microchannel coil fouling and frost experiments',
        source='https://data.mendeley.com/datasets/s6d23g2m2w/1',evidence='laboratory_measured',license='CC BY-NC 3.0',
        sheets=info,sheet_count=len(info),data_rows=total,publisher_sha256_verified=True,
        relevant_modules=['heat_exchanger','hydraulic_resistance'],application_status='wet_coil_extension_candidate_not_direct_current_UA_benchmark',
        limitations=['Air-side moisture/latent heat and frost violate current dry single-phase UA assumptions.',
            'm_w is frost formation rate and m_t is accumulated frost mass; neither is measured brine flow.',
            'Time is stored as Excel clock-time objects although the unit row says min; no guessed elapsed-time conversion performed.',
            'RH_1 unit row is inconsistent with its relative-humidity meaning; preserve and flag instead of silently fixing.',
            'Eight sheets are eight conditions, not eight independent replicated fault trials.']))
    # Actual three-tank observations pinned to a repository commit.
    path=BASE/'tank_three'/'repository.zip';originals.append(file_record(path));info=[];total=0
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        for member in z.namelist():
            if not member.endswith(('.xlsx','.csv')):continue
            name=Path(member).name;raw=z.read(member);dst=TABLES/'tank_three'/(name+'.csv' if name.endswith('.xlsx') else name)
            dst.parent.mkdir(parents=True,exist_ok=True)
            if name.endswith('.xlsx'):
                rows,namespace=strict_rows(raw)
                with dst.open('w',encoding='utf-8',newline='') as f:csv.writer(f).writerows(rows)
                item=dict(source_file=name,format='Strict OOXML' if 'purl.oclc.org' in namespace else 'OOXML',
                    raw_rows=len(rows),data_rows=max(0,len(rows)-2),header_rows=rows[:2],source_member_sha256=sha(raw))
            else:
                write_copy(raw,dst)
                with io.StringIO(raw.decode('utf-8-sig')) as f:rows=list(csv.reader(f))
                item=dict(source_file=name,format='CSV',raw_rows=len(rows),data_rows=max(0,len(rows)-2),
                    header_rows=rows[:2],source_member_sha256=sha(raw))
            total+=item['data_rows'];item['export']=file_record(dst);info.append(item);derived.append(file_record(dst))
    commit=json.loads((BASE/'tank_repo_commit.json').read_text(encoding='utf-8'))['sha']
    records.append(dict(id='tank_three',title='Actual three-tank liquid-level fault experiments',
        source='https://github.com/iraptis/Liquid-Level-Control-System-Fault-Diagnosis-Data',git_commit=commit,
        evidence='laboratory_measured',license='No explicit repository license located; raw observations retained locally, not redistributed in catalog bundle',
        tables=info,sensor_files=len(info),data_rows_across_sensor_files=total,experiment_prefixes=['unprefixed','2_','3_'],
        relevant_modules=['mass_balance'],application_status='leak_timing_and_level_model_candidate_not_yet_quantitative_mass_balance',
        limitations=['Authors explicitly report inaccurate flow-meter measurements; leak timing can still be identified.',
            'Pressure signals are voltages and flow signals are pulses; sensor calibration and per-sensor timestamps must be resolved.',
            'Strict OOXML worksheets were read directly with XML; original Excel files were not rewritten.',
            'Do not substitute pump PWM for measured flow or derive both boundary flows and inventory from the same level signal.']))
    # Different physical machine/refrigerant, with explicit induced-fault codes.
    path=BASE/'heatpump_propane'/'H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx';originals.append(file_record(path))
    metadata=json.loads((BASE/'heatpump_propane'/'metadata.json').read_text(encoding='utf-8'))
    expected=metadata['files'][0]['checksum'];assert expected.startswith('md5:')
    assert hashlib.md5(path.read_bytes()).hexdigest()==expected.split(':')[1]
    x=pd.ExcelFile(path);info=[];total=0
    for sheet in x.sheet_names:
        if sheet=='Information':continue
        d=pd.read_excel(x,sheet_name=sheet,header=None)
        main_count=int(pd.to_datetime(d.iloc[2:,0],errors='coerce').notna().sum())
        sh_count=int(pd.to_datetime(d.iloc[2:,14],errors='coerce').notna().sum());total+=main_count
        outputs=[]
        for part,cols in [('main',slice(0,13)),('superheat',slice(14,18))]:
            dst=TABLES/'heatpump_propane'/f'{sheet}_{part}.csv';dst.parent.mkdir(parents=True,exist_ok=True)
            d.iloc[:,cols].to_csv(dst,header=False,index=False);outputs.append(file_record(dst));derived.append(file_record(dst))
        info.append(dict(sheet=sheet,main_rows=main_count,superheat_rows=sh_count,
            headers=d.iloc[0].fillna('').tolist(),units=d.iloc[1].fillna('').tolist(),exports=outputs))
    records.append(dict(id='heatpump_propane',title='TRI-HP propane heat-pump induced-fault experiments',
        source='https://zenodo.org/records/5155136',evidence='laboratory_measured',
        license=metadata['metadata'].get('license',{}).get('id','see publisher metadata'),sheets=info,
        data_sheets=len(info),main_rows=total,publisher_md5_verified=True,
        relevant_modules=['chiller_performance'],application_status='new_machine_fault_candidate_requires_refrigerant_side_adapter',
        limitations=['Propane water-to-water heat pump in heating mode, not the RP1043 R134a cooling chiller.',
            'NF10/NF12 are no-fault runs; EF/CVL/LL/OC are induced faults at two load demands.',
            'Main data and superheat have different timestamps in adjacent columns; rows must not be joined by index.',
            'Existing chiller water-in/out/flow requirements are not all present; no fake channels reconstructed from reported COP.',
            'Fault intensity and test code are labels/metadata only and must not enter diagnostic features.']))
    report=dict(schema='equipment-diagnostics.actual-data-acquisition.v1',date_local='2026-11-05',
        datasets=records,original_files=originals,table_exports=derived,
        no_model_fitting_or_accuracy_evaluation=True,
        preserves_provider_train_test_split=True,
        note='Acquisition and compatibility audit only. No diagnostic accuracy, recall or false-positive claims from these datasets yet.')
    (OUT/'inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'id':r['id'],'status':r['application_status']} for r in records],indent=2))
if __name__=='__main__':main()
