"""Fit the existing standard-site server to the shared product persona and BM25 owner.

Prepare a deployment artifact only; no deployment, second server source or index build.
The existing site deployer keeps its index.json and authentication/rate-limit routes.
"""
import argparse
import ast
from pathlib import Path
import shutil


def prepare(server, out):
    source = server.read_text(encoding='utf-8')
    lines = source.splitlines(keepends=True)
    removed = []
    for node in ast.parse(source).body:
        if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in ('words', 'Index', 'answer') or
                isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VOICE' for t in node.targets)):
            removed.append((node.lineno, node.end_lineno))
    if len(removed) != 4:
        raise ValueError('Existing site server contract changed; inspect before preparing')
    for start, end in reversed(removed):
        lines[start - 1:end] = []
    app = Path(__file__).resolve().parents[2] / '01.APP' / 'nodelang'
    package = out / 'nodelang'
    (package / 'data' / 'baboom').mkdir(parents=True, exist_ok=True)
    (package / '__init__.py').write_text('', encoding='utf-8')
    for name in ('baboom_standard.py', 'baboom_persona.py'):
        shutil.copyfile(app / name, package / name)
    shutil.copyfile(app / 'data' / 'baboom' / 'persona.json', package / 'data' / 'baboom' / 'persona.json')
    header = ('from functools import partial\n'
              'from nodelang.baboom_standard import Index, answer\n'
              'from nodelang.baboom_persona import persona_instructions\n'
              'VOICE = persona_instructions()\n'
              'answer = partial(answer, complete=lambda *args, **kwargs: complete(*args, **kwargs))\n')
    (out / 'server.py').write_text(header + ''.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.server, args.out)


if __name__ == '__main__':
    main()
