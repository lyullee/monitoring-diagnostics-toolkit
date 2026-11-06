"""Curate original-code/audit evidence, excluding external observations and models.

Run in the original research workspace. A public checkout need not contain the
excluded historical outputs. No reconstruction or invented results are performed.
"""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'evidence'


def main():
    OUT.mkdir(exist_ok=True)
    index = []
    for folder in ('outputs', 'research_support'):
        for path in sorted((ROOT/folder).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or 'node_modules' in path.parts:
                continue
            # Raw archives already have provider/local hashes in acquisition
            # manifests. Hash local research outputs and metadata here only.
            if folder == 'research_support' and path.suffix != '.json':
                continue
            index.append(dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size,
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (OUT/'artifact_index.json').write_text(json.dumps(dict(
        scope='hash-only inventory at public-release preparation; entries are not all shipped', files=index),
        indent=2)+'\n', encoding='utf-8')
    latest = ROOT/'outputs/two_target_improvement'
    with zipfile.ZipFile(latest/'evaluated_source_snapshot.zip') as z:
        assert all(Path(n).suffix in ('.py', '.json') for n in z.namelist())
    shutil.copyfile(latest/'evaluated_source_snapshot.zip', OUT/'v016_evaluated_source_snapshot.zip')
    for filename in ('protocol.json', 'independent_audit.json', 'adoption.json'):
        shutil.copyfile(latest/filename, OUT/('v016_'+filename))
    results = json.loads((latest/'results.json').read_text(encoding='utf-8'))
    aggregate = dict(version=results['version'], source_sha256=results['source_sha256'],
        reused_evaluation=True, new_independent_fault_metrics=None,
        marine=results['marine']['comparison'], heatpump=results['heatpump']['comparison'],
        scope='aggregate metrics only; no row-level observations, predictions or trained profiles')
    (OUT/'v016_aggregate_metrics.json').write_text(json.dumps(aggregate, indent=2)+'\n', encoding='utf-8')
    print(f'Indexed {len(index)} local artifacts; curated v0.16 code/protocol/audit/aggregate metrics.')


if __name__ == '__main__':
    main()
