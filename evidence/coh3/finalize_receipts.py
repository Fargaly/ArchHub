"""Bind complete court footers to unchanged source inputs and the final report."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'evidence/coh3'
REQUIRED = (
    'test_application_persistence', 'test_clean_server_visual_projection',
    'test_done_needs_docs', 'test_node_native_application', 'test_node_native_website',
    'test_the_launcher_starts_no_brain', 'test_website_docs_pages',
    'test_website_live_findings', 'test_website_package_docs', 'test_website_public_routes',
    'test_website_site_script', 'test_website_truth',
)
EXTRA = ('test_website_definition_revision', 'test_goose_brain', 'zero-idle',
         'ds-port-assets', 'ds-port-ratchet')
GATE_LOG = Path('C:/Users/fargaly/00.ARCHUB/70.HANDOFFS/'
                'archhub-integrated-repair-20260909/tools/queue.log')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


frozen = json.loads((OUT / 'frozen-source.json').read_text())
assert all(sha(ROOT / name) == digest for name, digest in frozen['files'].items())
earlier = json.loads((OUT / 'frozen-source-b16.json').read_text())
common = frozen['files'].keys() & earlier['files'].keys()
changed = sorted(name for name in common
                 if frozen['files'][name] != earlier['files'][name])
main_changes = set(subprocess.check_output(
    ['git', 'diff', '--name-only', '--no-renames', earlier['main_base'], frozen['main_base']],
    cwd=ROOT, text=True).splitlines())
normalization = json.loads((OUT / 'rebase-byte-equivalence.json').read_text())
assert normalization['file'] == 'tests_replica/test_website_truth.py'
assert normalization['before_git_blob_sha256'] == normalization['after_worktree_sha256'] == sha(ROOT / normalization['file'])
assert normalization['before_worktree_sha256'] == earlier['files'][normalization['file']]
assert set(changed) <= main_changes | {'tests_js/studio_foundations_tokens.test.cjs', normalization['file']}, changed
unchanged_runtime_owners = (
    'nodelang/universal_application.py', 'nodelang/universal_cell.py',
    'nodelang/cell_website.py', 'nodelang/site_export.py', 'nodelang/persistence.py',
    'nodelang/migration.py', 'nodelang/universal_pipeline.py', 'nodelang/library_engines.py',
)
runtime_sha256 = {
    name: earlier['files'].get(name) or hashlib.sha256(subprocess.check_output(
        ['git', 'show', earlier['main_base'] + ':' + name], cwd=ROOT)).hexdigest()
    for name in unchanged_runtime_owners
}
assert all(sha(ROOT / name) == digest for name, digest in runtime_sha256.items())
server = (ROOT / 'nodelang/application_server.py').read_bytes()
for asset in (b'"ds/index.jsx", ', b'"compiled/ds-index.js", '):
    assert server.count(asset) == 1
    server = server.replace(asset, b'', 1)
assert hashlib.sha256(server).hexdigest() == earlier['files']['nodelang/application_server.py']
equivalence = {
    'earlier_court_source': earlier['source_commit'],
    'final_court_source': frozen['source_commit'],
    'unchanged_previously_frozen_files': len(common) - len(changed),
    'changed_files_since_earlier_courts': changed,
    'rebase_line_ending_equivalence': normalization,
    'newly_frozen_files': sorted(frozen['files'].keys() - earlier['files'].keys()),
    'unchanged_runtime_owners': unchanged_runtime_owners,
    'unchanged_runtime_sha256': runtime_sha256,
    'server_equivalence': 'Removing exactly two new DS asset whitelist entries reproduces the accepted b16 server SHA-256.',
    'prior_complete_court_receipts': 'court-receipts-b16.json',
    'archived_overwritten_outputs': {name + '.out': name + '-b16.out' for name in
                                   ('studio-targeted', 'export', 'test_node_native_website', 'ratchet')},
    'files': frozen['files'],
}
rows = []
gate_lines = GATE_LOG.read_text(encoding='utf-8-sig').splitlines()


def gate_receipt(label):
    pattern = re.compile(r'\[(\d+)\] (WAIT\s+|RUN\s+|DONE\s+|TIMEOUT\s+)'
                         + re.escape('COH3-' + label) + r'(?:\s|$)')
    events = [(number, line, pattern.search(line))
              for number, line in enumerate(gate_lines, 1) if pattern.search(line)]
    assert events, 'No gate events: ' + label
    number, last, match = events[-1]
    assert match.group(2).strip() == 'DONE' and 'exit=0 ' in last and 'job empty' in last, last
    runs = [(n, line) for n, line, found in events
            if found.group(1) == match.group(1) and found.group(2).strip() == 'RUN']
    assert runs, 'No matching gate start: ' + label
    return {'source': str(GATE_LOG), 'run_line': runs[-1][0], 'run': runs[-1][1],
            'done_line': number, 'done': last}


for name in REQUIRED + EXTRA:
    path = OUT / (name + '.out')
    content = path.read_text(encoding='utf-8-sig')
    # Match the repository's LF contract before binding committed evidence bytes.
    path.write_bytes(content.encode('utf-8'))
    footers = [line for line in content.splitlines()
               if re.match(r'^=+ .*\b\d+ passed\b.*=+$', line)]
    assert footers, 'No complete passing footer: ' + name
    footer = footers[-1]
    assert not re.search(r'\b\d+ failed\b|\bdeselected\b', footer), footer
    passed = int(re.search(r'\b(\d+) passed\b', footer).group(1))
    xfail = re.search(r'\b(\d+) xfailed\b', footer)
    if name in ('zero-idle', 'ds-port-assets', 'ds-port-ratchet'):
        assert passed == {'zero-idle': 2, 'ds-port-assets': 6, 'ds-port-ratchet': 4}[name] and not xfail, footer
    rows.append({'file': name + '.out', 'verbatim_footer': footer,
                 'summary': footer.strip('= '), 'passed': passed,
                 'xfailed': int(xfail.group(1)) if xfail else 0,
                 'sha256': sha(path), 'requested': name in REQUIRED,
                 'gate': gate_receipt(name if name in ('zero-idle', 'ds-port-assets', 'ds-port-ratchet') else name + '.py')})

requested = [row for row in rows if row['requested']]
counts = {'requested_files': len(requested),
          'requested_passed': sum(row['passed'] for row in requested),
          'requested_xfailed': sum(row['xfailed'] for row in requested)}
(OUT / 'court-receipts.json').write_text(
    json.dumps({'counts': counts, 'receipts': rows, 'source_equivalence': equivalence,
                'evidence_line_endings': 'LF per repository attributes; verbatim line content retained',
                'other_gate_receipts': {label: gate_receipt(label) for label in
                                        ('DS-studio-build', 'studio-targeted', 'export', 'ratchet')}},
               indent=2) + '\n')
lines = ['Required 12 Python files:', '', '| File | Verbatim summary |', '| --- | --- |']
for row in requested:
    lines.append('| `tests_replica/%s.py` | `%s` |' %
                 (row['file'].removesuffix('.out'), row['summary']))
lines += ['', 'Additional current-main and release gates:', '',
          '| File | Verbatim summary |', '| --- | --- |']
for row in rows[len(requested):]:
    test_file = {'zero-idle.out': 'tests/test_zero_idle_growth.py',
                 'ds-port-assets.out': 'tests/test_ds_port_assets.py',
                 'ds-port-ratchet.out': 'tests/test_ds_port_ratchet.py'}.get(
                     row['file'], 'tests_replica/' + row['file'].removesuffix('.out') + '.py')
    lines.append('| `%s` | `%s` |' % (test_file, row['summary']))
lines += ['', 'Requested set: **%d passed, %d xfailed, zero failed**. '
          'The zero-idle court completed **2/2**. Full footers, file hashes and unchanged-input '
          'equivalence are in `evidence/coh3/court-receipts.json`.' %
          (counts['requested_passed'], counts['requested_xfailed'])]
report = ROOT / 'RESULT-COH3.md'
text = report.read_text(encoding='utf-8-sig')
marker = '<!-- FINAL_COURT_RECEIPTS -->'
assert marker in text, 'Report receipts already finalized'
report.write_text(text.replace(marker, '\n'.join(lines)), encoding='utf-8')
print(json.dumps(counts))
