"""Test the built wheel outside the checkout, including the actual README example."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    wheel, = (ROOT/'dist').glob('*.whl')
    example = re.findall(r'```python\n(.*?)\n```', (ROOT/'README.md').read_text(encoding='utf-8'), re.S)[0]
    with tempfile.TemporaryDirectory(prefix='monitoring_diagnostics_public_') as folder:
        target = Path(folder)/'installed'
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--target', str(target), str(wheel)],
                       check=True, capture_output=True)
        prelude = 'import sys,pathlib; sys.path.insert(0,sys.argv[1]); import equipment_diagnostics as e; '
        prelude += 'assert pathlib.Path(e.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve()); '
        prelude += 'assert e.__version__=="0.17.0"; assert len(e.list_diagnostics())==11; '
        subprocess.run([sys.executable, '-I', '-c', prelude+'\n'+example, str(target)],
                       cwd=folder, check=True, capture_output=True)
        demo = Path(folder)/'demo'
        subprocess.run([sys.executable, str(ROOT/'examples/generate_demo.py'), '--output', str(demo)],
                       check=True, capture_output=True)
        invoke = prelude+'\nfrom equipment_diagnostics.cli import main; raise SystemExit(main(sys.argv[2:]))'
        for args in [
            ['list', '--details'],
            ['fit', '--config', str(demo/'config.json'), '--data', str(demo/'normal.csv'), '--output', str(demo/'reference.json')],
            ['run', '--config', str(demo/'config.json'), '--data', str(demo/'operation.csv'), '--reference', str(demo/'reference.json'), '--output', str(demo/'report.json')]]:
            subprocess.run([sys.executable, '-I', '-c', invoke, str(target), *args], cwd=folder,
                           check=True, capture_output=True)
        result = json.loads((demo/'report.json').read_text(encoding='utf-8'))
        assert len(result['summaries']) == 10
        assert all(v['alarm_samples'] > 0 for v in result['summaries'].values())
        payload = dict(passed=True, package=wheel.name, outside_checkout=True, isolated_python=True,
            readme_example=True, catalog_kinds=11, cli_demo_diagnostics=10,
            summaries=result['summaries'], scope='installed software smoke; synthetic inputs, not measured fault qualification')
        (ROOT/'outputs/public_release/install_smoke.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
        print('Installed-wheel README example, 11-kind catalog, and 10-diagnostic CLI fit/run passed.')


if __name__ == '__main__':
    main()
