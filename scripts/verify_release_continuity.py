"""Prove public 0.17 core differs from evaluated 0.16 only in docs/version.

AST equivalence is scoped to source files archived in the original research
snapshot. It does not independently validate the historical measured results.
"""
import ast
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class Normalize(ast.NodeTransformer):
    def generic_visit(self, node):
        super().generic_visit(node)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                node.body = node.body[1:]
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets):
            node.value = ast.Constant(value='VERSION')
        return node


def main():
    entries = []
    with zipfile.ZipFile(ROOT/'evidence/v016_evaluated_source_snapshot.zip') as archive:
        for name in archive.namelist():
            if not name.startswith('src/') or not name.endswith('.py'):
                continue
            old = archive.read(name)
            new = (ROOT/name).read_bytes()
            assert ast.dump(Normalize().visit(ast.parse(old))) == ast.dump(Normalize().visit(ast.parse(new))), name
            entries.append(dict(path=name, archived_sha256=hashlib.sha256(old).hexdigest(),
                                release_sha256=hashlib.sha256(new).hexdigest(), byte_identical=old==new))
    payload = dict(passed=True, scope='core AST equality after removing docstrings and version assignment', files=entries)
    (ROOT/'evidence/release_source_continuity.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
    print(f'{len(entries)} core files equivalent after docstrings/version normalization.')


if __name__ == '__main__':
    main()
