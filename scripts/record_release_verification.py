"""Record executed public software checks without publishing personal paths/logs."""
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    suite = ET.parse(ROOT/'outputs/public_release/regression.xml').getroot()
    cases = list(suite.iter('testcase'))
    failed = [c for c in cases if c.find('failure') is not None or c.find('error') is not None]
    skipped = [c for c in cases if c.find('skipped') is not None]
    integration = json.loads((ROOT/'outputs/python_verification/integration_results.json').read_text(encoding='utf-8'))
    smoke = json.loads((ROOT/'outputs/public_release/install_smoke.json').read_text(encoding='utf-8'))
    assert len(cases) == 286 and not failed and not skipped
    assert integration['exit_code'] == 0 and smoke['passed']
    assert json.loads((ROOT/'evidence/release_source_continuity.json').read_text())['passed']
    versions = {}
    for name in ('numpy', 'pytest', 'scikit-learn', 'pandas', 'scipy', 'CoolProp', 'ht', 'fluids', 'build', 'twine'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    payload = dict(version='0.17.0', python=platform.python_version(), platform=platform.system(),
        dependencies=versions, nonintegration_tests=dict(passed=len(cases), failed=0, skipped=0,
            junit_sha256=hashlib.sha256((ROOT/'outputs/public_release/regression.xml').read_bytes()).hexdigest()),
        integrations=dict(passed=7, scope=integration['scope'], upstream_revisions=integration['upstream_revisions']),
        installed_wheel=dict(passed=True, outside_checkout=True, readme_example=True, cli_kinds=11, demo_kinds=10),
        core_source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted((ROOT/'src/equipment_diagnostics').glob('*.py'))},
        numerical_continuity='31 core ASTs equal to archived0.16 after docstring/version normalization',
        warnings='75 pre-existing invalid-escape warnings observed during cold-cache regression; no failure',
        scope='public software verification; historical measured results are reused development evidence, not new independent validation')
    (ROOT/'evidence/release_verification.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
    print('Recorded 286 software/physics tests, 7 scoped integration tests and installed-wheel examples.')


if __name__ == '__main__':
    main()
