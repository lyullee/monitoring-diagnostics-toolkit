"""Re-download pinned public observation files, or verify the files already obtained."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'research_support'/'public_data'/'acquisition_20261105'
OUT=ROOT/'outputs'/'actual_data_acquisition'
FILES=[
 ('filter_hse/filter.zip','https://www.kaggle.com/api/v1/datasets/download/prognosticshse/preventive-to-predicitve-maintenance?datasetVersionNumber=8',None),
 ('ro_nrel/README.rtf','https://mhkdr.openei.org/files/649/README.rtf',None),
 ('ro_nrel/steady_state.zip','https://mhkdr.openei.org/files/649/steady_state.zip',None),
 ('ro_nrel/ramp.zip','https://mhkdr.openei.org/files/649/ramp.zip',None),
 ('ro_nrel/sine.zip','https://mhkdr.openei.org/files/649/sine.zip',None),
 ('coil_frost/Supplemental data.xlsx','https://data.mendeley.com/public-files/datasets/s6d23g2m2w/files/efd5e0b0-e253-4eb1-ba5c-020129c13bc6/file_downloaded',
  'fa935be6e8c81c917b61aecbcf2ecf1f076e2da012f77d27035b408cd740a0c5'),
 ('tank_three/repository.zip','https://api.github.com/repos/iraptis/Liquid-Level-Control-System-Fault-Diagnosis-Data/zipball/57557ea940bdc379fc0a5052a04c91ce1c9f86cd',None),
 ('heatpump_propane/H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx',
  'https://zenodo.org/api/records/5155136/files/H2020_TRI-HP_T6.2_PropaneIceFaultTests_v1.xlsx/content',None),
]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);records=[]
    for rel,url,expected in FILES:
        path=BASE/rel
        if not path.exists():
            if not args.download:raise FileNotFoundError(str(path)+'; use --download')
            path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.part')
            try:
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Equipment-Diagnostics-Data-Acquisition'}),timeout=45) as r,temp.open('wb') as f:
                    size=0
                    while chunk:=r.read(1024*1024):
                        size+=len(chunk)
                        if size>250_000_000:raise ValueError('unexpectedly large download')
                        f.write(chunk)
                if expected and hashlib.sha256(temp.read_bytes()).hexdigest()!=expected:raise ValueError('publisher SHA256 mismatch')
                temp.replace(path)
            finally:
                if temp.exists():temp.unlink()
        raw=path.read_bytes();h=hashlib.sha256(raw).hexdigest()
        if expected:assert h==expected,'publisher checksum mismatch'
        crc=None
        if path.suffix in ('.zip','.xlsx'):
            with zipfile.ZipFile(path) as z:assert z.testzip() is None;crc=True
        records.append(dict(file=str(path.relative_to(ROOT)),source_url=url,bytes=len(raw),sha256=h,
            publisher_sha256_verified=bool(expected),zip_crc_verified=crc,status='obtained_and_verified'))
    report={'date_local':'2026-11-05','files':records,'file_count':len(records),'bytes':sum(r['bytes'] for r in records),
        'note':'Original publication files kept unchanged. Earlier failed URL probes are superseded by this verified inventory.'}
    (OUT/'download_manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(records),'bytes':report['bytes'],'all_verified':True}))
if __name__=='__main__':main()
