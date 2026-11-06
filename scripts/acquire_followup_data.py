"""Small public follow-up artifacts, without altering the original acquisitions."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'research_support/public_data/gap_analysis_20261105';OUT=ROOT/'outputs/diagnostic_gap_analysis'
FILES=[
    ('r290_receiver/README.md','https://zenodo.org/api/records/22097811/files/README.md/content','03f0c95ee71ef22f2cbdec0b295aea25'),
    ('r290_receiver/data_mapping.csv','https://zenodo.org/api/records/22097811/files/data_mapping.csv/content','b672a31eb78d87295280a21db5240e2e'),
    ('r290_receiver/operating_points.csv','https://zenodo.org/api/records/22097811/files/operating_points.csv/content','59aa221a3991c7d5e6b79dd874ab11c8'),
    ('r290_receiver/thermodynamic.zip','https://zenodo.org/api/records/22097811/files/thermodynamic.zip/content','e8357dd17325ec11c82a6db058b4db88'),
    ('ro/process-flow-diagram.png','https://mhkdr.openei.org/files/649/process-flow-diagram.png',None),
    ('ro/wec_sim.zip','https://mhkdr.openei.org/files/649/wec_sim%20%281%29.zip',None)]

def main():
    result=[]
    for rel,url,expected in FILES:
        p=DATA/rel
        if not p.exists():
            p.parent.mkdir(parents=True,exist_ok=True)
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Equipment-Diagnostics-Research'}),timeout=25) as response:
                raw=response.read(10_000_001)
            if len(raw)>10_000_000:raise ValueError('unexpected size')
            if expected and hashlib.md5(raw).hexdigest()!=expected:raise ValueError('publisher MD5 mismatch')
            p.write_bytes(raw)
        raw=p.read_bytes()
        if expected:assert hashlib.md5(raw).hexdigest()==expected
        if p.suffix=='.zip':
            with zipfile.ZipFile(p) as z:assert z.testzip() is None
        result.append(dict(file=str(p.relative_to(ROOT)),source_url=url,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),publisher_md5=expected,publisher_md5_verified=bool(expected)))
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/'followup_download_manifest.json').write_text(json.dumps(dict(files=result,scope='Independent R290 charge-sweep corpus plus previously unused RO waveform experiments on the original apparatus'),indent=2),encoding='utf-8')
    print(json.dumps(dict(files=len(result),bytes=sum(r['bytes'] for r in result))))
if __name__=='__main__':main()
