"""Rank9 independent measured corpora; provider MD5 plus local SHA256; no relabeling."""
import hashlib,json
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'research_support/public_data/completion_20261106'
RECORDS=('19857425','20582921','21987832')
def main():
    OUT.mkdir(parents=True,exist_ok=True); manifest=[]
    for record in RECORDS:
        meta=OUT/(record+'_metadata.json')
        if not meta.exists():meta.write_bytes(urlopen(Request('https://zenodo.org/api/records/'+record,headers={'User-Agent':'equipment-diagnostics-research'}),timeout=30).read())
        d=json.loads(meta.read_bytes())
        for f in d['files']:
            if f['key']=='Extruder Current.zip':continue # 101MB optional electrical waveform; not needed by pressure-flow API
            dest=OUT/record/f['key'];dest.parent.mkdir(exist_ok=True)
            if not dest.exists():dest.write_bytes(urlopen(Request(f['links']['self'],headers={'User-Agent':'equipment-diagnostics-research'}),timeout=60).read())
            raw=dest.read_bytes()
            assert 'md5:'+hashlib.md5(raw).hexdigest()==f['checksum']
            manifest.append(dict(record=record,file=str(dest.relative_to(ROOT)),bytes=len(raw),publisher_md5=f['checksum'],
                md5_verified=True,sha256=hashlib.sha256(raw).hexdigest(),url=f['links']['self']))
            print(record,f['key'],len(raw),flush=True)
    (OUT/'download_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
if __name__=='__main__':main()
