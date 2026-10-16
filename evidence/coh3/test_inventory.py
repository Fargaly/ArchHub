"""Static changed-file declarations; never substitutes for pytest collection."""
import ast
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASES = {
    'requested_base': '09d36d7b6f341914f8a82354792947eefce58704',
    'current_main': 'bdbc3f893349d2b5fcc82d471fcbf43e0af1d236',
}


def declarations(source):
    return sorted(node.name for node in ast.walk(ast.parse(source))
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name.startswith('test_'))


inventories = {}
for label, base in BASES.items():
    paths = subprocess.check_output(
        ['git', 'diff', '--name-only', base, '--', 'tests', 'tests_replica'],
        cwd=ROOT, text=True).splitlines()
    files = []
    for name in paths:
        if not name.endswith('.py'):
            continue
        old = subprocess.run(['git', 'show', base + ':' + name], cwd=ROOT,
                             capture_output=True, text=True)
        before = declarations(old.stdout) if old.returncode == 0 else []
        path = ROOT / name
        after = declarations(path.read_text(encoding='utf-8-sig')) if path.exists() else []
        files.append({'file': name, 'before': len(before), 'after': len(after),
                      'removed': sorted(set(before) - set(after)),
                      'added': sorted(set(after) - set(before)),
                      'before_names': before, 'after_names': after})
    inventories[label] = {'base': base, 'files': files,
                          'before': sum(row['before'] for row in files),
                          'after': sum(row['after'] for row in files)}
output = {'metric': 'static changed-file Python test declarations, not executable or full-suite count',
          'full_suite': 'Not collected/run: lane CPU rule reserves one full release suite to 717.',
          'inventories': inventories}
(ROOT / 'evidence/coh3/test-retention.json').write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps({label: {'before': row['before'], 'after': row['after']}
                  for label, row in inventories.items()}))
