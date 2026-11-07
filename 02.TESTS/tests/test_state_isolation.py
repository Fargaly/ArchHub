"""TESTISO: the test-state override owns every application write destination."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sqlite3
import shutil
import tempfile
import time
from datetime import datetime
from contextlib import closing
from uuid import uuid4

import pytest


def test_state_override_isolates_owners(tmp_path):
    sentinel = tmp_path / 'sentinel'
    sentinel.mkdir()
    state = tmp_path / 'state'
    state.mkdir(exist_ok=True)
    env = dict(os.environ, ARCHHUB_TEST_STATE_DIR=str(state),
               ARCHHUB_STATE_DIR=str(sentinel / 'wrong-state'),
               USERPROFILE=str(sentinel), HOME=str(sentinel),
               LOCALAPPDATA=str(sentinel), APPDATA=str(sentinel),
               PYTHONDONTWRITEBYTECODE='1')
    # Fail before any owner can create a file outside the selected state.
    probe = r'''
import os, sys
from pathlib import Path
sys.path[:0] = ['01.APP', '03.TOOLS']
from tools.real_app_check.profile_guard import install
state = Path(os.environ['ARCHHUB_TEST_STATE_DIR'])
install(state / 'guard.jsonl', protected=[os.environ['USERPROFILE']])
from nodelang import session_files, agent_budget, settings_owner, workshop_mailbox
assert session_files._default_sessions_directory().is_relative_to(state), 'sessions escape test state'
assert agent_budget.router_database().is_relative_to(state), 'router database escapes test state'
assert settings_owner.router_settings_path().is_relative_to(state), 'router settings escape test state'
assert workshop_mailbox.profile_database().is_relative_to(state), 'workshop escapes test state'
sessions = session_files.sessions_directory()
assert sessions.is_relative_to(state)
with agent_budget.connect() as db:
    assert db.execute('SELECT count(*) FROM requests').fetchone() == (0,)
from nodelang.model_router import _application_state_dir
assert _application_state_dir() == state
from nodelang import brain_files, workshop_config
from nodelang.runtime_credentials import BrowserCredentialVault
from nodelang.user_paths import state_directory
for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA'):
    os.environ.pop(name, None)
for path in (brain_files._path(), workshop_config.app_state_dir(),
             BrowserCredentialVault.default_path(), session_files.SessionFiles().metadata):
    assert path.is_relative_to(state), str(path)
from nodelang.quiet_update import _profile_instance
lock = _profile_instance(state)
try:
    assert lock.handle is not None, 'isolated recovery selected an existing profile mutex'
finally:
    lock.close()
for invalid in ('relative-state', '', '~'):
    os.environ['ARCHHUB_TEST_STATE_DIR'] = invalid
    try:
        state_directory()
    except ValueError:
        pass
    else:
        raise AssertionError('invalid test state was accepted: ' + repr(invalid))
'''
    before = _snapshot(sentinel)
    result = subprocess.run([sys.executable, '-B', '-c', probe], env=env,
                            capture_output=True, text=True, timeout=90,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert _snapshot(sentinel) == before
    assert result.returncode == 0, result.stdout + result.stderr


def _snapshot(root):
    """Read metadata only; never create, repair, or remove profile contents."""
    if not root.exists():
        return None
    result = {}
    def walk(directory):
        with os.scandir(directory) as entries:
            for entry in entries:
                stat = entry.stat(follow_symlinks=False)
                result[os.path.relpath(entry.path, root)] = [stat.st_mtime_ns, stat.st_size]
                if entry.is_dir(follow_symlinks=False) and not os.path.isjunction(entry.path):
                    walk(entry.path)
    stat = root.stat()
    result['.'] = [stat.st_mtime_ns, stat.st_size]
    walk(root)
    return result


# These files belong to live agent hooks/app telemetry, not verifier owners.
# Their writes can overlap every test run; never infer test leakage from them.
_LIVE_HOOK_FILES = {'governance/ledger.jsonl', 'last_gate_decision.json', 'spans.jsonl'}


def _profile_files(root):
    if not root.exists():
        return
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_symlink() or entry.is_junction():
                continue
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                yield from _profile_files(path)
            elif entry.is_file(follow_symlinks=False):
                # GRAPHOUT: historical journals and sidecars are outside the run's ownership.
                if '.universal.sqlite3' not in entry.name.casefold():
                    yield path


def _sessions_snapshot(root):
    # Only the created .archhub set is stable evidence here, never settings or hook mtimes.
    return sorted(str(p.relative_to(root)) for p in _profile_files(root / 'Sessions')
                  if p.suffix.casefold() == '.archhub')


def _created_at(value, fallback):
    try:
        if isinstance(value, (int, float)):
            return value / 1000 if value > 1e11 else value
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return fallback


def _owned_record(value, run, end, fallback):
    if isinstance(value, list):
        return any(_owned_record(row, run, end, fallback) for row in value)
    if not isinstance(value, dict):
        return False
    created = _created_at(value.get('created_at', value.get('ts')), fallback)
    ours = (str(value.get('writer_pid', value.get('pid', ''))) in run['pids'] or
            str(value.get('writer_session', value.get('session_id', ''))) in run['sessions'])
    if ours and run['started'] <= created <= end:
        return True
    return any(_owned_record(row, run, end, fallback) for row in value.values())


def _marked_files(root, marker, *, since=None):
    patterns = [marker.encode(encoding) for encoding in ('utf-8', 'utf-16-le', 'utf-16-be')]
    # Retain enough bytes for the longest encoded marker crossing a read boundary.
    overlap = max(map(len, patterns)) - 1
    marked = set()
    for path in _profile_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith('runtime-context/') or relative in _LIVE_HOOK_FILES:
            continue
        if marker in relative:
            marked.add(str(path))
            continue
        try:
            if since is not None and path.stat().st_mtime < since:
                continue  # A fresh run marker cannot predate this run; writes are also audit-guarded.
            with path.open('rb') as stream:
                tail = b''
                while chunk := stream.read(1024 * 1024):
                    chunk = tail + chunk
                    if any(pattern in chunk for pattern in patterns):
                        marked.add(str(path))
                        break
                    tail = chunk[-overlap:] if overlap else b''
        except FileNotFoundError:
            # Live owners may atomically replace files between enumeration and read.
            continue
    return marked


def _sqlite_records(path):
    # SQLite may create -shm even with mode=ro. Only open a disposable DB+WAL copy.
    # Never copy an entire profile, and bound temporary disk use on the founder's machine.
    sources = (path, Path(str(path) + '-wal'))
    def versions():
        return [(p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None for p in sources]
    with tempfile.TemporaryDirectory(prefix='testiso-scan-') as temporary:
        target = Path(temporary) / path.name
        for _ in range(5):
            before = versions()
            if sum(item[0] for item in before if item) > 128 * 1024 * 1024:
                raise ValueError('Owner database exceeds the 128 MiB read-only scan budget')
            for source, version in zip(sources, before):
                destination = Path(temporary) / source.name
                if version is not None:
                    shutil.copyfile(source, destination)
                else:
                    destination.unlink(missing_ok=True)
            if before == versions():
                break
        else:
            raise ValueError('Owner database changed throughout snapshot retries')
        with closing(sqlite3.connect(target)) as db:
            db.execute('PRAGMA query_only=ON')
            db.row_factory = sqlite3.Row
            tables = [row[0] for row in db.execute('SELECT name FROM sqlite_master WHERE type="table"')]
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                for row in db.execute('SELECT * FROM ' + quoted):
                    record = dict(row)
                    for key, value in list(record.items()):
                        if isinstance(value, str) and value[:1] in ('{', '['):
                            try:
                                record[key] = json.loads(value)
                            except ValueError:
                                pass
                    yield table, record


def _profile_leaks(before, run, end):
    leaks = []
    marker = run['marker']
    for name, snapshot in before.items():
        root = Path(name)
        if not root.exists():
            continue
        marked = _marked_files(root, marker, since=run['started'])
        new_sessions = set(_sessions_snapshot(root)) - set(snapshot)
        for path in _profile_files(root):
            relative = path.relative_to(root).as_posix()
            if relative.startswith('runtime-context/') or relative in _LIVE_HOOK_FILES:
                continue
            try:
                if marker in relative or str(path) in marked:
                    leaks.append(str(path) + ': test run marker')
                    continue
                parts = {part.casefold() for part in path.relative_to(root).parts}
                owner_file = (path.suffix.casefold() == '.archhub' or 'settings' in parts or
                              'router' in path.name.casefold() or
                              relative in ('data/sessions/current.json', 'data/sessions/recent.json'))
                if not owner_file:
                    continue
                stat = path.stat()
                born = getattr(stat, 'st_birthtime', stat.st_ctime)
                if stat.st_mtime < run['started'] and born < run['started']:
                    continue
                if path.suffix.casefold() in ('.sqlite', '.sqlite3', '.db'):
                    for table, record in _sqlite_records(path):
                        if _owned_record(record, run, end, born):
                            leaks.append(str(path) + ': test writer row in ' + table)
                            break
                elif path.suffix.casefold() in ('.json', '.jsonl', '.archhub'):
                    # Existing documents may be updated, so still inspect their writer records.
                    if relative in new_sessions or stat.st_mtime >= run['started'] or born >= run['started']:
                        raw = path.read_text(encoding='utf-8-sig')
                        rows = [json.loads(line) for line in raw.splitlines() if line] if path.suffix == '.jsonl' else json.loads(raw)
                        if _owned_record(rows, run, end, born):
                            leaks.append(str(path) + ': test writer record')
            except FileNotFoundError:
                # A live owner may atomically replace/remove a file between enumeration and read.
                continue
            except (OSError, ValueError, sqlite3.Error) as error:
                leaks.append(str(path) + ': scan incomplete (' + type(error).__name__ + ')')
    return leaks


def _assert_profiles_clean(before, run, end):
    leaks = _profile_leaks(before, run, end)
    assert not leaks, 'Test writes reached real profiles: ' + json.dumps(leaks)


def _run_context():
    context = json.loads(Path(os.environ['ARCHHUB_TEST_PROFILE_SNAPSHOT']).read_text(encoding='utf-8'))
    run = context['run']
    registry = Path(os.environ['ARCHHUB_TEST_PROCESS_DIR'])
    for path in registry.glob('*.json'):
        writer = json.loads(path.read_text(encoding='utf-8'))
        if writer['test_run_id'] == run['marker']:
            run['pids'].append(str(writer['writer_pid']))
            run['sessions'].append(writer['writer_session'])
    return context


def test_release_profiles_unchanged(testiso_run):
    """The session fixture scans after every test and session fixture has finished."""
    context = _run_context()
    assert context['before'] == testiso_run['before']
    assert context['run']['started'] == testiso_run['run']['started']
    assert context['run']['marker'] == os.environ['ARCHHUB_TEST_RUN_ID']
    writer = Path(os.environ['ARCHHUB_TEST_PROCESS_DIR']) / (str(os.getpid()) + '.json')
    assert json.loads(writer.read_text(encoding='utf-8')) == {
        'test_run_id': context['run']['marker'], 'writer_pid': os.getpid(),
        'writer_session': context['run']['marker'] + ':' + str(os.getpid()),
    }


def test_installed_guard_refuses_mixed_case_environment_root(tmp_path):
    protected = tmp_path / 'Protected'
    protected.mkdir()
    log = tmp_path / 'guard.jsonl'
    probe = '''
import sys
from pathlib import Path
sys.path.insert(0, '03.TOOLS')
from tools.real_app_check.profile_guard import install
install()
try:
    Path(sys.argv[1]).write_text('refused')
except AssertionError:
    pass
'''
    target = protected / 'leak.txt'
    env = dict(os.environ, ARCHHUB_PROFILE_GUARD_ROOTS=json.dumps([str(protected).upper()]),
               ARCHHUB_PROFILE_GUARD_LOG=str(log))
    done = subprocess.run([sys.executable, '-B', '-c', probe, str(target)], env=env,
                          capture_output=True, text=True, timeout=30,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert done.returncode == 3, done.stdout + done.stderr
    assert not target.exists()
    assert json.loads(log.read_text(encoding='utf-8'))[0] == 'open'


def _fixture_run():
    return {'marker': str(uuid4()), 'started': time.time(),
            'pids': [str(os.getpid())], 'sessions': ['test-session']}


def test_owners_persist_marker_without_changing_values(tmp_path):
    from nodelang import agent_budget, model_router, session_files, settings_owner, workshop_tasks
    from nodelang.nograph_server import JsonFile
    from nodelang.workshop_mailbox import application_history
    marker = os.environ['ARCHHUB_TEST_RUN_ID']
    document = session_files.new_document('TESTISO owner probe')
    path = tmp_path / 'probe.archhub'
    session_files.write_document(path, document)
    assert json.loads(path.read_text())['properties']['_test_writer']['test_run_id'] == marker
    assert session_files.read_document(path) == document
    with_properties = {**document, 'properties': {}}
    session_files.write_document(path, with_properties)
    assert session_files.read_document(path) == with_properties
    owner = JsonFile(tmp_path / 'settings.json', {})
    owner.write({'theme': 'light'})
    assert owner.read() == {'theme': 'light'}
    assert json.loads(owner.path.read_text())['_test_writer']['test_run_id'] == marker
    owner.write([{'path': 'example.archhub'}])
    assert owner.read() == [{'path': 'example.archhub'}]
    assert json.loads(owner.path.read_text())[0]['_test_writer']['test_run_id'] == marker
    sessions = session_files.SessionFiles(tmp_path / 'metadata')
    sessions.remember(path, document)
    sessions._current(document['id'], str(path))
    assert marker in (sessions.metadata / 'recent.json').read_text()
    assert marker in (sessions.metadata / 'current.json').read_text()
    account = settings_owner.AccountFiles(tmp_path / 'account.json')
    account.write('account:test', {'theme': 'light'})
    assert account.read('account:test') == {'theme': 'light'}
    assert json.loads(account.path.read_text())['_test_writer']['test_run_id'] == marker
    model_router.request_profiles({'id': 'probe', 'ts': time.time(), 'agent': 'test',
                                  'model': 'test', 'provider': 'test', 'tokens': 0, 'ms': 0, 'outcome': 'ok'})
    with agent_budget.connect() as db:
        assert marker in db.execute('SELECT writer FROM test_write_provenance WHERE row_id="probe"').fetchone()[0]
    with application_history() as history:
        task = workshop_tasks.create(history, 'TESTISO task', 'test')
        assert marker in history._db.execute('SELECT writer FROM test_write_provenance WHERE row_id=?',
                                            (task['id'],)).fetchone()[0]


def test_child_with_explicit_environment_keeps_marker():
    grandchild = 'import os; print(os.environ["ARCHHUB_TEST_RUN_ID"])'
    child = ('import subprocess,sys; subprocess.run([sys.executable,"-B","-c",' +
             repr(grandchild) + '],env={})')
    done = subprocess.run([sys.executable, '-B', '-c', child],
                          env={'PATH': os.environ.get('PATH', '')}, capture_output=True, text=True,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == os.environ['ARCHHUB_TEST_RUN_ID']
    version = subprocess.run([sys.executable, '--version'], capture_output=True, text=True,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith('Python ')


def test_concurrent_live_writers_are_not_test_leaks(tmp_path):
    root = tmp_path / 'real'
    root.mkdir()
    before = {str(root): _sessions_snapshot(root)}
    run = _fixture_run()
    for name in ('runtime-context/other-session.json', 'governance/ledger.jsonl',
                 'last_gate_decision.json', 'spans.jsonl', 'settings/account.json',
                 'Sessions/live.archhub'):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'writer_pid': -1, 'created_at': time.time()}))
    _assert_profiles_clean(before, run, time.time())


def test_wal_scan_preserves_real_root_bytes_and_mtimes(tmp_path):
    root = tmp_path / 'real'
    root.mkdir()
    run = _fixture_run()
    path = root / 'router.sqlite'
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE requests (writer_pid INTEGER, ts REAL)')
        writer.execute('INSERT INTO requests VALUES (?, ?)', (os.getpid(), time.time()))
        writer.commit()
        before = _snapshot(root)
        contents = {p.name: p.read_bytes() for p in root.iterdir()}
        with pytest.raises(AssertionError, match='test writer row'):
            _assert_profiles_clean({str(root): []}, run, time.time())
        assert _snapshot(root) == before
        assert {p.name: p.read_bytes() for p in root.iterdir()} == contents


@pytest.mark.parametrize('kind', ['filename', 'content', 'utf16', 'boundary', 'session', 'settings', 'router'])
def test_deliberate_leak_is_refused(tmp_path, kind):
    root = tmp_path / 'real'
    root.mkdir()
    before = {str(root): _sessions_snapshot(root)}
    run = _fixture_run()
    if kind == 'filename':
        (root / (run['marker'] + '.txt')).write_text('leaked')
    elif kind in ('content', 'utf16', 'boundary'):
        raw = ('x' * (1024 * 1024 - 3) if kind == 'boundary' else '') + run['marker']
        (root / 'leak.txt').write_text(raw, encoding='utf-16' if kind == 'utf16' else 'utf-8')
    elif kind == 'router':
        with sqlite3.connect(root / 'router.sqlite') as db:
            db.execute('CREATE TABLE requests (writer_pid INTEGER, ts REAL)')
            db.execute('INSERT INTO requests VALUES (?, ?)', (os.getpid(), time.time()))
    else:
        path = root / ('Sessions/leak.archhub' if kind == 'session' else 'settings/account.json')
        path.parent.mkdir()
        path.write_text(json.dumps({'writer_session': 'test-session', 'created_at': time.time()}))
    with pytest.raises(AssertionError, match='Test writes reached real profiles'):
        _assert_profiles_clean(before, run, time.time())


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16-le', 'utf-16-be'])
@pytest.mark.parametrize('bom', [False, True])
def test_marker_scan_is_read_only_across_chunk_boundary(tmp_path, encoding, bom):
    root = tmp_path / 'real'
    root.mkdir()
    marker = str(uuid4())
    encoded = marker.encode(encoding)
    prefix = (b'\xff\xfe' if encoding == 'utf-16-le' else b'\xfe\xff') if bom and encoding.startswith('utf-16') else b''
    target = root / 'content.bin'
    target.write_bytes(prefix + b'x' * (1024 * 1024 - len(prefix) - 1) + encoded)
    named = root / (marker + '.txt')
    named.write_bytes(b'filename only')
    excluded = ['runtime-context/nested/leak.txt', *_LIVE_HOOK_FILES]
    for name in excluded:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
    contents = {str(path): path.read_bytes() for path in _profile_files(root)}
    # Enumerate the completed fixture before recording Windows directory metadata.
    _snapshot(root)
    before = _snapshot(root)
    assert _marked_files(root, marker) == {str(target), str(named)}
    assert _snapshot(root) == before
    assert {str(path): path.read_bytes() for path in _profile_files(root)} == contents
