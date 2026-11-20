"""Fit the existing standard-site server to the shared product persona and BM25 owner.

Prepare a deployment artifact only. The standards index stays with its existing publisher.
The existing site deployer keeps its index.json and authentication/rate-limit routes.
"""
import argparse
import ast
import json
from pathlib import Path
import shutil
import sys


def prepare(server, out, *, catalogue=None):
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
    sys.path.insert(0, str(app.parent))
    try:
        from nodelang.baboom_standard import public_doc_chunks, public_node_chunks
        product_docs = list(public_doc_chunks(app / 'site_export.py'))
        if catalogue is not None:
            product_docs.extend(public_node_chunks(json.loads(catalogue.read_text(encoding='utf-8'))))
    finally:
        sys.path.pop(0)
    package = out / 'nodelang'
    (package / 'data' / 'baboom').mkdir(parents=True, exist_ok=True)
    (package / '__init__.py').write_text('', encoding='utf-8')
    for name in ('baboom_standard.py', 'baboom_persona.py'):
        shutil.copyfile(app / name, package / name)
    shutil.copyfile(app / 'data' / 'baboom' / 'persona.json', package / 'data' / 'baboom' / 'persona.json')
    (out / 'product-docs.json').write_text(json.dumps({'chunks': product_docs}, ensure_ascii=False), encoding='utf-8')
    header = ('from functools import partial\n'
              'from pathlib import Path\n'
              'from nodelang.baboom_standard import Index, answer\n'
              'from nodelang.baboom_persona import persona_instructions\n'
              'VOICE = persona_instructions()\n'
              "Index = partial(Index, public_docs=Path(__file__).with_name('product-docs.json'))\n"
              'answer = partial(answer, complete=lambda *args, **kwargs: complete(*args, **kwargs))\n')
    (out / 'server.py').write_text(header + ''.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--catalogue', type=Path, help='the existing public website catalogue export')
    args = parser.parse_args()
    prepare(args.server, args.out, catalogue=args.catalogue)


if __name__ == '__main__':
    main()
