"""Build an inspectable API appendix from original source; never ingest raw corpora.

This is documentation generation, not scientific validation. AST extraction
preserves parameter names/defaults and points readers to dynamic role logic.
"""
import ast
import inspect
import json
from pathlib import Path

import equipment_diagnostics as ed

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ["# Python API reference", "",
              "Generated from the shipped source by `python scripts/prepare_public_documentation.py`.",
              "Constructor signatures are authoritative for names and defaults. Common `**kwargs` are",
              "`persistence_s=0.0`, `max_gap_s=60.0`, `allowed_modes=None` for Diagnostic subclasses.",
              "`channels` maps semantic roles to SensorBatch column names; a role is not a CSV column position.",
              "Role declarations below are source expressions: conditional branches must also be read.",
              "All scoring methods return DiagnosticResult unless a helper explicitly returns arrays/dicts.", ""]
    records = []
    for name in ed.__all__:
        obj = getattr(ed, name)
        if not (inspect.isclass(obj) or inspect.isfunction(obj)):
            continue
        path = Path(inspect.getsourcefile(obj))
        source, lineno = inspect.getsourcelines(obj)
        signature = str(inspect.signature(obj))
        entry = dict(name=name, signature=signature, source=str(path.relative_to(ROOT)).replace('\\', '/'),
                     line=lineno, doc=inspect.getdoc(obj) or "See module guide and source.")
        records.append(entry)
        output += [f"## `{name}`", "", f"```python\n{name}{signature}\n```", "",
                   f"Source: [{entry['source']}](../{entry['source']}) (definition line {lineno}).", "",
                   entry['doc'], ""]
        tree = ast.parse(''.join(source))
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == '_columns':
                calls.append(ast.unparse(node))
        if calls:
            output += ["Sensor role and unit declarations (conditional alternatives may apply):", "",
                       "```python\n"+'\n'.join(calls)+"\n```", ""]
        if inspect.isclass(obj):
            for method in ('fit', 'calibrate', 'score', 'set_reference', 'transform', 'predict', 'push', 'reset'):
                value = getattr(obj, method, None)
                if value is not None:
                    output += [f"- `{method}{inspect.signature(value)}`"]
            output += [""]
    (ROOT/'docs/API_REFERENCE.md').write_text('\n'.join(output)+'\n', encoding='utf-8')
    (ROOT/'docs/API_CATALOG.json').write_text(json.dumps(records, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
