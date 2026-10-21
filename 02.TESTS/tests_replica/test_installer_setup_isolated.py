"""Compile/run production PrepareToInstall backup code in an isolated Inno app.

The harness omits connectors, real payload, shortcuts, registry and post-install
launch. Only the profile constant and FindPython are redirected to fixture paths.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

import pytest

from tests_replica.test_installer_clean_close import journal, mcp_holder


ROOT = Path(__file__).resolve().parents[2]
ISCC = Path(r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe')


def snapshot(paths):
    result = {}
    for path in paths:
        digest, count = hashlib.sha256(), 0
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            for ident, value in db.execute('SELECT * FROM work ORDER BY id'):
                raw = value if isinstance(value, bytes) else value.encode()
                digest.update(str(ident).encode() + b'\0' + len(raw).to_bytes(8, 'big') + raw)
                count += 1
        result[str(path)] = dict(count=count, rows_sha256=digest.hexdigest())
    return result


def crash_wal(path, blob_bytes):
    code = """
import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('INSERT INTO work VALUES (99,zeroblob(?))',(int(sys.argv[2]),));c.commit();os._exit(0)
"""
    subprocess.run([sys.executable, '-B', '-c', code, str(path), str(blob_bytes)], check=True)


def compile_setup(folder, profile, modules, iss_text):
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / 'payload.txt'
    marker.write_text('INSTALLFIX isolated payload\n', encoding='ascii')
    start = iss_text.index("  if Result = '' then\n  begin\n    ExtractTemporaryFile('application_recovery_files.py');")
    end = iss_text.index("  if Result <> '' then", start)
    block = iss_text[start:end].replace("ExpandConstant('{localappdata}')", "'" + str(profile).replace("'", "''") + "'")
    callback_start = iss_text.index('procedure OnBackupLog(')
    callback_end = iss_text.index('procedure OnConnectorLog(', callback_start)
    callback = iss_text[callback_start:callback_end]
    files = '\n'.join('Source: "%s"; Flags: dontcopy' % (modules / name) for name in
        ('application_recovery_files.py', 'installer_closed_profile.py', 'backup_retention.py', 'conversation_trace_shapes.py')
        if (modules / name).is_file())
    script = '''#define BuildId "same-build"
[Setup]
AppName=INSTALLFIX isolated proof
AppVersion=1
AppId=INSTALLFIX-ISOLATED
DefaultDirName=%s
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
CloseApplications=no
RestartApplications=no
OutputDir=%s
OutputBaseFilename=setup
Compression=none
[Files]
%s
Source: "%s"; DestDir: "{app}"; Flags: ignoreversion
[Code]
var BackupProgress: TOutputMarqueeProgressWizardPage;
    BackupFailure: String;
%s
function FindPython(): String;
begin Result := '%s'; end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var BackupCode: Integer;
begin
  Result := '';
%s
  if Result <> '' then Log('ArchHub Setup refused: ' + Result);
end;
''' % (folder / 'installed', folder, files, marker, callback, str(sys.executable).replace("'", "''"), block)
    path = folder / 'proof.iss'
    path.write_text(script, encoding='utf-8-sig')
    result = subprocess.run([str(ISCC), '/Qp', str(path)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return folder / 'setup.exe'


def run_setup(executable, log, temp):
    temp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCLOSEAPPLICATIONS',
                             '/NORESTARTAPPLICATIONS', '/LOG=' + str(log)], env=env, capture_output=True, timeout=180)
    return result.returncode


@pytest.mark.skipif(os.name != 'nt' or not ISCC.is_file(), reason='Requires actual Windows Inno compiler')
def test_production_prepare_installs_and_same_build_installs_again(tmp_path):
    profile = tmp_path / 'profile'
    graph = journal(profile / 'ArchHub-Test/archhub-test.universal.sqlite3')
    content = journal(Path(str(graph) + '.conversations.sqlite3'))
    graph_cache = journal(Path(str(graph) + '.accelerators'))
    legacy = journal(profile / 'ArchHub/node-native-wip.json.gz.universal.sqlite3')
    generation = str(uuid.uuid4())
    authority = journal(profile / ('ArchHub/unified-authority/generations/' + generation + '/authority.sqlite3'))
    (profile / 'ArchHub/unified-authority/CURRENT').write_text(generation, encoding='ascii')
    cache = journal(Path(str(authority) + '.accelerators'))
    crash_wal(authority, 73 * 1024**2)
    crash_wal(cache, 8192)
    crash_wal(content, 32768)
    crash_wal(graph_cache, 4096)
    Path(str(legacy) + '-wal').touch()
    child = mcp_holder(profile, graph)
    paths = [graph, content, graph_cache, legacy, authority, cache]
    before = snapshot(paths)
    shape = {str(path): Path(str(path) + '-wal').stat().st_size for path in paths}
    assert shape[str(authority)] >= 73 * 1024**2 and shape[str(legacy)] == 0
    try:
        # The baseline runs the real old PrepareToInstall block and old backup
        # owner on the same synthetic profile: expected installer exit 7.
        baseline = tmp_path / 'baseline-modules'
        baseline.mkdir()
        for name in ('application_recovery_files.py', 'backup_retention.py', 'conversation_trace_shapes.py'):
            raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', '298ea7e4:01.APP/nodelang/' + name])
            (baseline / name).write_bytes(raw)
        old_iss = subprocess.check_output(['git', '-C', str(ROOT), 'show', '298ea7e4:01.APP/installer/ArchHub.iss']).decode('utf-8')
        old = compile_setup(tmp_path / 'baseline', profile, baseline, old_iss)
        assert run_setup(old, tmp_path / 'setup-baseline.log', tmp_path / 'setup-temp') == 7
        assert child.poll() is None
        assert not (tmp_path / 'baseline/installed/payload.txt').exists()
        current = compile_setup(tmp_path / 'current', profile, ROOT / '01.APP/nodelang', (ROOT / '01.APP/installer/ArchHub.iss').read_text(encoding='utf-8'))
        assert run_setup(current, tmp_path / 'setup-first.log', tmp_path / 'setup-temp') == 0
        child.wait(10)
        assert (tmp_path / 'current/installed/payload.txt').read_bytes() == (tmp_path / 'current/payload.txt').read_bytes()
        after_first = snapshot(paths)
        assert after_first == before
        copies = sorted(profile.rglob('*-closed/closed-files.json'))
        assert len(copies) == 3
        first_receipts = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in copies}
        assert run_setup(current, tmp_path / 'setup-second.log', tmp_path / 'setup-temp') == 0
        assert snapshot(paths) == before
        assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in profile.rglob('*-closed/closed-files.json')} == first_receipts
        backup_rows = {}
        for receipt in copies:
            record = json.loads(receipt.read_text(encoding='utf-8'))
            for item in record['files']:
                copied = receipt.parent / item['name']
                original = next(p for p in paths if p.name == item['name'])
                copied_identity = snapshot([copied])[str(copied)]
                assert copied_identity == before[str(original)]
                backup_rows[str(copied)] = copied_identity
        evidence = dict(baseline_exit=7, first_exit=0, second_exit=0, shape_wal_bytes=shape,
            before=before, after_first=after_first, after_second=snapshot(paths), backup_rows=backup_rows,
            production_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                ('01.APP/installer/ArchHub.iss','01.APP/nodelang/application_recovery_files.py','01.APP/nodelang/installer_closed_profile.py')})
        (tmp_path / 'setup-proof.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print('SETUP BASELINE exit=7; FIRST exit=0; SAME BUILD RETRY exit=0; all row counts/hashes preserved')
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(10)
