"""Independent CSV counts and source-row split audit; no library metric calls."""
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'acquired_modules_validation'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def count(c,y,a,v,e):
    c['total']+=1;c['eligible' if e else 'excluded']+=1
    if not e:return
    c['fault_eligible' if y else 'normal_eligible']+=1
    if not v:c['unknown']+=1;return
    c['valid']+=1;c['TP' if y and a else 'FN' if y else 'FP' if a else 'TN']+=1
def check(c,m):
    for k in ('total','eligible','excluded','valid','unknown','TP','FN','FP','TN'):assert c[k]==m[k],(k,c[k],m[k])
    for k,n,d in [('accuracy_valid',c['TP']+c['TN'],c['valid']),('recall_valid',c['TP'],c['TP']+c['FN']),
        ('false_positive_rate_valid',c['FP'],c['FP']+c['TN']),('coverage',c['valid'],c['eligible']),
        ('coverage_all_rows',c['valid'],c['total']),('fault_detection_all_eligible',c['TP'],c['fault_eligible'])]:
        assert m[k]==(n/d if d else None),(k,n,d,m[k])
def main():
    r=json.loads((OUT/'results.json').read_text(encoding='utf-8'));protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
    assert digest(OUT/'protocol.json')==r['protocol_sha256']
    for p,h in r['source_sha256'].items():assert digest(ROOT/p)==h,p
    for p,h in protocol['data_sha256'].items():assert digest(ROOT/p)==h,p
    counts={};file_counts={};csv_hashes={};eval_keys={}
    for kind in ('filter','heatpump'):
        totals={p:Counter() for p in ('before','after')};common={p:Counter() for p in totals};groups={};keys=set()
        with (OUT/f'{kind}_predictions.csv').open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                group=row['trial'] if kind=='filter' else row['sheet'];key=(group,row['source_row'])
                assert key not in keys;keys.add(key)
                e=row['eligible']=='1';y=(row['label_risk30'] if kind=='filter' else row['label'])=='1'
                if kind=='filter':assert y==(float(row['rul_s'])<=30)
                vs=[row[p+'_valid']=='1' for p in totals]
                for i,p in enumerate(totals):
                    a=row[p+'_alarm']=='1';assert not a or vs[i]
                    assert bool(row[p+'_score'])==vs[i]
                    count(totals[p],y,a,vs[i],e);count(common[p],y,a,all(vs),e)
                    count(groups.setdefault((group,p),Counter()),y,a,vs[i],e)
        result=r['modules'][kind]
        for p in totals:
            check(totals[p],result['comparison'][p]['metrics']);check(common[p],result['comparison'][p]['common_valid_metrics'])
        for file in result['files']:
            group=str(file['trial']) if kind=='filter' else file['sheet']
            for p in totals:check(groups[group,p],file['policies'][p]['metrics'])
        counts[kind]={p:dict(v) for p,v in totals.items()};eval_keys[kind]=keys
        csv_hashes[kind]=digest(OUT/f'{kind}_predictions.csv')
    f=json.loads((OUT/'filter_frozen.json').read_text(encoding='utf-8'))
    assert digest(OUT/'filter_frozen.json')==r['modules']['filter']['frozen_sha256']
    assert not set(f['training_keys'])&set(f['calibration_keys'])
    assert not set(f['split']['training_ids'])&set(f['split']['calibration_ids'])
    assert set(f['split']['training_ids'])|set(f['split']['calibration_ids'])==set(range(1,51))
    assert f['train_fingerprint']!=f['calibration_fingerprint']
    # Labels independently tied to original Test CSV; never inferred from output scores.
    archive=ROOT/'research_support/public_data/acquisition_20261105/filter_hse/filter.zip'
    with zipfile.ZipFile(archive) as z:
        original=list(csv.DictReader(io.StringIO(z.read('Test_Data_CSV.csv').decode('utf-8'))))
    with (OUT/'filter_predictions.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            gold=original[int(row['source_row'])]
            assert int(float(gold['Data_No']))==int(row['trial']) and float(gold['RUL'])==float(row['rul_s'])
            assert float(gold['Time'])==float(row['time_s'])
    h=json.loads((OUT/'heatpump_frozen.json').read_text(encoding='utf-8'))
    assert digest(OUT/'heatpump_frozen.json')==r['modules']['heatpump']['frozen_sha256']
    for sheet,split in h['normal_split'].items():
        sets={k:set(v) for k,v in split.items()}
        for i,a in enumerate(sets):
            for b in list(sets)[i+1:]:assert not sets[a]&sets[b]
        observed={int(row) for group,row in eval_keys['heatpump'] if group==sheet}
        assert observed==sets['evaluation']
        assert max(sets['train'])<min(sets['calibration'])<max(sets['calibration'])<min(sets['evaluation'])
    for p in ('before','after'):
        ref=h['policies'][p]['reference'];assert ref['training_fingerprint']==h['train_fingerprint']
        assert ref['score_calibration']['fingerprint']==h['calibration_fingerprint']
    # Check heat-pump labels against untouched workbook, including true experiment intensity.
    import pandas as pd
    book=ROOT/'research_support/public_data/acquisition_20261105/heatpump_propane/H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx'
    sheets=pd.read_excel(book,sheet_name=None,header=0)
    with (OUT/'heatpump_predictions.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            raw=sheets[row['sheet']].loc[int(row['source_row'])]
            label=not row['sheet'].startswith('NF') and float(raw['Fault intensity'])!=0
            assert label==(row['label']=='1')
            assert str(raw['Test code'])==row['experiment']
            assert abs(pd.Timestamp(raw['Date']).value/1e9-float(row['time_s']))<1e-5
    rf=json.loads((OUT/'ro_frozen.json').read_text(encoding='utf-8'))
    assert digest(OUT/'ro_frozen.json')==r['modules']['ro']['frozen_sha256']
    sets={k:set(v) for k,v in rf['split'].items()}
    for i,a in enumerate(sets):
        for b in list(sets)[i+1:]:assert not sets[a]&sets[b]
    ro_counts={p:Counter() for p in ('before','after')};ro_files={};ro_keys=set();order_pass=0;steady_test=set()
    with (OUT/'ro_predictions.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            key=(row['source'],row['source_row']);assert key not in ro_keys;ro_keys.add(key)
            assert float(row['time_s'])==int(row['source_row'])*.25
            if row['source']=='steady_state/steady_state.csv':steady_test.add(int(row['source_row']))
            order_pass+=row['pressure_order_ok']=='1'
            for p,c in ro_counts.items():
                c['total']+=1;v=row[p+'_valid']=='1';a=row[p+'_alarm']=='1';assert not a or v
                c['valid']+=v;c['alarms']+=a
                fc=ro_files.setdefault((row['source'],p),Counter());fc['total']+=1;fc['valid']+=v;fc['alarms']+=a
    assert steady_test==sets['evaluation']
    for p,c in ro_counts.items():
        m=r['modules']['ro']['comparison'][p]
        assert c['total']==m['total'] and c['valid']==m['valid'] and c['valid']/c['total']==m['coverage']
        assert c['alarms']/c['valid']==m['observed_alarm_fraction']
        assert all(m[k] is None for k in ('accuracy_valid','recall_valid','false_positive_rate_valid'))
    for file in r['modules']['ro']['files']:
        for p,m in file['policies'].items():
            c=ro_files[file['file'],p];assert c['total']==m['total'] and c['valid']==m['valid']
    assert order_pass/len(ro_keys)==r['modules']['ro']['strict_evaluation_pressure_order_fraction']
    assert r['modules']['ro']['strict_training_pressure_order_valid_rows']==0
    csv_hashes['ro']=digest(OUT/'ro_predictions.csv')
    audit=dict(successful=True,independent_counts=counts,ro_counts={k:dict(v) for k,v in ro_counts.items()},
        split_and_source_row_disjointness_verified=True,source_gold_labels_verified=True,
        missing_ro_fault_metrics_remain_null=True,source_data_and_frozen_hashes_verified=True,
        results_sha256=digest(OUT/'results.json'),prediction_sha256=csv_hashes)
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
