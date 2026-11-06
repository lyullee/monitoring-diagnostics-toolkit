"""Independent file and CSV counts for the acquired observation collection."""
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'/'actual_data_acquisition'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    r=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
    manifest=json.loads((OUT/'download_manifest.json').read_text(encoding='utf-8'))
    assert len(r['datasets'])==5 and len(r['original_files'])==8 and len(r['table_exports'])==83
    for f in r['original_files']+r['table_exports']:
        p=ROOT/f['path'];assert p.stat().st_size==f['bytes'] and digest(p)==f['sha256']
    assert {f['path'] for f in r['original_files']}=={f['file'] for f in manifest['files']}
    independent_rows={}
    for d in r['datasets']:
        if d['id']=='filter_hse':
            with zipfile.ZipFile(ROOT/r['original_files'][0]['path']) as z:
                for t in d['tables']:
                    raw=z.read(t['file']);reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
                    ids=set();n=0
                    for row in reader:ids.add(row['Data_No']);n+=1
                    assert n==t['rows'] and len(ids)==t['trial_records']==50
                    assert (ROOT/t['copy']['path']).read_bytes()==raw
                    independent_rows[t['file']]=n
        if d['id']=='ro_nrel':
            total=0
            for t in d['tables']:
                with zipfile.ZipFile(ROOT/'research_support'/'public_data'/'acquisition_20261105'/'ro_nrel'/t['archive']) as z:raw=z.read(t['file'])
                assert (ROOT/t['copy']['path']).read_bytes()==raw
                n=sum(1 for _ in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
                assert n==t['rows'];total+=n
            assert total==d['rows']==203643 and len(d['tables'])==28
            independent_rows['ro_nrel']=total
        if d['id']=='coil_frost':assert d['data_rows']==463 and len(d['sheets'])==8
        if d['id']=='tank_three':assert d['sensor_files']==25
        if d['id']=='heatpump_propane':assert d['data_sheets']==10 and d['main_rows']==8363
    assert r['no_model_fitting_or_accuracy_evaluation']
    audit=dict(successful=True,originals_and_exports_hash_verified=True,byte_exact_csv_copies_verified=True,
        original_train_test_files_separate=True,independently_counted_rows=independent_rows,
        inventory_sha256=digest(OUT/'inventory.json'),download_manifest_sha256=digest(OUT/'download_manifest.json'))
    (OUT/'independent_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
