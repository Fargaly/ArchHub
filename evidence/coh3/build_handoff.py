"""Write cumulative and current-main patches, hashes and disposable-index proofs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
BASE = '09d36d7b6f341914f8a82354792947eefce58704'
MAIN = 'bdbc3f893349d2b5fcc82d471fcbf43e0af1d236'
PATHS = ['.gitattributes', 'AUTHORITY.md', 'CLAUDE.md', 'COHERENCE-TABLE.md', 'README.md',
         'GAPS.md', 'INTERACTION-LOCALITY-AUTHORITY-PLAN.md', 'NODE-LANGUAGE-100-LAYER-ARCHITECTURE.md',
         'NODE-LANGUAGE-VISUAL-GUIDE.md', 'SETUP.bat', 'SETUP.txt', 'docs',
         'evidence/grandmap_bindings.json', 'installer', 'launch_archhub_test.py', 'nodelang',
         'packaging', 'public_site', 'tests', 'tests_replica', 'tests_js', 'NOTICE', 'STEP0-GOOSE.md',
         'tools/ratchet.py', 'evidence/ratchet.json', 'evidence/dsport-ratchet-before.json']
proofs = []
for name, base in [('COH3.patch', BASE), ('COH3-current-main.patch', MAIN)]:
    patch = subprocess.check_output(['git', 'diff', '--binary', '--find-renames', base, '--', *PATHS])
    (ROOT / name).write_bytes(patch)
    digest = hashlib.sha256(patch).hexdigest()
    (ROOT / (name + '.sha256')).write_text(digest + ' *' + name + '\n')
    handle, index = tempfile.mkstemp(prefix='coh3-apply-', dir=ROOT / '.git')
    os.close(handle)
    Path(index).unlink()
    env = {**os.environ, 'GIT_INDEX_FILE': index}
    try:
        subprocess.run(['git', 'read-tree', base], env=env, check=True, capture_output=True)
        checked = subprocess.run(['git', 'apply', '--cached', '--check', '--binary', '--whitespace=nowarn', name],
                                 env=env, capture_output=True, text=True)
        assert checked.returncode == 0, checked.stderr
        proofs.append({'patch': name, 'base': base, 'sha256': digest,
                       'apply_cached_check_exit': checked.returncode, 'bytes': len(patch)})
    finally:
        Path(index).unlink(missing_ok=True)
        Path(index + '.lock').unlink(missing_ok=True)
(ROOT / 'evidence/coh3/patch-apply-check.json').write_text(json.dumps(proofs, indent=2) + '\n')
print(json.dumps(proofs))
