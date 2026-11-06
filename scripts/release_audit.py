"""Inspect actual release archives, without reading excluded external corpora.

This checks distribution membership and common accidental credential/path leaks.
It is not a copyright clearance or a generic security scanner. Numerical and
empirical validity are documented and tested separately.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = {'.upstream', '.venv', 'research_support', 'outputs', '__pycache__', '.git'}
RAW_SUFFIXES = {'.pdf', '.xlsx', '.xls', '.mat', '.csv', '.7z', '.pem', '.key'}
PATTERNS = [re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
            re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
            re.compile(rb'github_pat_[A-Za-z0-9_]{50,}'),
            re.compile(rb'pypi-AgEI[A-Za-z0-9_-]{30,}'),
            re.compile(rb'C:[/\\]Users[/\\][^/\\\s]+', re.I)]


def inspect_members(members, wheel=False):
    count = 0
    for name, raw in members:
        path = PurePosixPath(name)
        assert not (set(path.parts) & BLOCKED), f'excluded path: {name}'
        assert path.suffix.lower() not in RAW_SUFFIXES, f'external-data format: {name}'
        # Only this original-code snapshot is an intentional nested archive.
        if path.suffix.lower() == '.zip':
            assert path.name == 'v016_evaluated_source_snapshot.zip', name
            import io
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                inspect_members(((n, z.read(n)) for n in z.namelist() if not n.endswith('/')))
        if path.suffix.lower() in {'.py', '.md', '.json', '.toml', '.txt', '.yml', '.cff'} or path.name in {'METADATA', 'LICENSE'}:
            assert not any(p.search(raw) for p in PATTERNS), f'potential credential/personal path: {name}'
        if wheel:
            assert path.parts[0] == 'equipment_diagnostics' or '.dist-info' in path.parts[0], name
        count += 1
    return count


def main():
    paths = sorted((ROOT/'dist').glob('*.whl')) + sorted((ROOT/'dist').glob('*.tar.gz'))
    assert len(paths) == 2, 'dist must contain exactly one wheel and one source distribution'
    reports = []
    for path in paths:
        if path.suffix == '.whl':
            with zipfile.ZipFile(path) as z:
                count = inspect_members(((n, z.read(n)) for n in z.namelist() if not n.endswith('/')), wheel=True)
                metadata = z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))).decode()
                assert 'Name: monitoring-diagnostics-toolkit' in metadata
                assert 'License-Expression: MIT' in metadata
        else:
            with tarfile.open(path) as t:
                count = inspect_members(((m.name, t.extractfile(m).read()) for m in t.getmembers() if m.isfile()))
        reports.append(dict(file=path.name, bytes=path.stat().st_size,
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), members=count))
    out = ROOT/'outputs/public_release'
    out.mkdir(parents=True, exist_ok=True)
    payload = dict(passed=True, distributions=reports, scope='archive membership and common accidental-leak patterns; not legal clearance')
    (out/'distribution_audit.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(payload, indent=2))


if __name__ == '__main__':
    main()
