"""APPTIDY: real temporary profiles, byte-preserving moves and boot rollback."""
import ctypes
import json
import os
from pathlib import Path

import pytest

from nodelang import quiet_update, session_files


@pytest.fixture
def profile(tmp_path, monkeypatch):
    state = tmp_path / 'Local' / 'ArchHub'
    state.mkdir(parents=True)
    monkeypatch.setenv('LOCALAPPDATA', str(state.parent))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'User'))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    return state


def seed(state):
    junk = ['candidate-20.log', 'live-20.stdout.log', 'settings.json.bak_old',
            'version.json.bak_old', 'node-native-wip.next-25.json.gz',
            'authority-bridge-headless.json.gz.universal.sqlite3', 'node-native-wip.json.gz.universal.sqlite3']
    for name in junk:
        (state / name).write_bytes(b'old build')
    for name in ['_syncrung_backup', '_deploy_backup', '.retired-v1-docs', 'preflight', 'packages', 'cache']:
        (state / name).mkdir()
        (state / name / 'old').write_bytes(b'retired')
    kept = {'settings/preferences.json': b'{"theme":"dark"}',
            'workshop/messages.sqlite3': b'workshop bytes',
            'sessions/broker.json': b'broker bytes',
            'sessions-files/unknown-user-data.txt': b'user data',
            'sessions-files/skills/unknown.txt': b'user workflow bytes'}
    for name, raw in kept.items():
        path = state / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return kept


def test_first_run_deletes_only_staged_after_health_and_keeps_manifest(profile):
    kept = seed(profile)
    staged = quiet_update.stage_app_folder(profile)
    assert staged['staged'] and not staged['skipped']
    assert not (profile / 'candidate-20.log').exists()
    assert (profile / '_cleanup-staging' / 'candidate-20.log').read_bytes() == b'old build'
    result = quiet_update.finish_app_folder(profile, healthy=True)
    assert {row['path'] for row in result['removed']} == {row['path'] for row in staged['staged']}
    assert not result['pending']
    assert set(path.name for path in profile.iterdir()) <= quiet_update.APP_FOLDER_OWNERS.keys()
    for name, raw in kept.items():
        assert (profile / name).read_bytes() == raw
    rows = [json.loads(line) for line in (profile / 'logs/removals.jsonl').read_text().splitlines()]
    assert all(row['size'] > 0 for row in rows)
    assert {row['path'] for row in rows if row['status'] == 'removed'} == {row['path'] for row in result['removed']}
    assert quiet_update.stage_app_folder(profile)['staged'] == []


def test_unknown_files_folders_and_credentials_survive_cleanup(profile):
    kept = seed(profile)
    for name in ('report.pdf', 'budget.xlsx', 'unknown.json', 'Incoming/report.pdf',
                 'Incoming/table.xlsx', 'Incoming/config.json', 'credentials.json',
                 'secrets/token', '.env', 'keys/private.pem'):
        path = profile / name
        path.parent.mkdir(parents=True, exist_ok=True)
        kept[name] = b'untouched user bytes'
        path.write_bytes(kept[name])
    quiet_update.stage_app_folder(profile)
    quiet_update.finish_app_folder(profile, healthy=True)
    for name, raw in kept.items():
        assert (profile / name).read_bytes() == raw
    assert not (profile / 'candidate-20.log').exists()


def test_bound_task_reopens_same_document_after_autosave_rename(profile):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        session = workshop_tasks.create_session(history, 'A real workflow')
        document = session_files.read_document(session['path'])
        document['title'] = 'Renamed workflow'
        saved = session_files.SessionFiles().dispatch({'action': 'autosave', 'path': session['path'],
                                                     'document': document})
        opened = workshop_tasks.open_session(history, session['taskId'])
        assert opened['id'] == session['id'] and opened['path'] == saved['path']
        assert not Path(session['path']).exists()
        assert history._db.execute('SELECT count(*) FROM workshop_tasks').fetchone()[0] == 1


def test_populated_task_migration_and_folder_change_rollback(profile, tmp_path, monkeypatch):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    from nodelang.nograph_server import JsonFile
    legacy = profile / 'sessions-files'
    legacy.mkdir()
    document = session_files.new_document('Populated task')
    document['notes'].append({'id': 'note', 'text': 'keep task content'})
    old = legacy / (document['id'] + '.archhub')
    session_files.write_document(old, document)
    with application_history() as history:
        task = workshop_tasks.create(history, 'Populated task', 'founder')['id']
        original = workshop_tasks.open_session(history, task, str(old))
        session_files.migrate_sessions(profile)
        migrated = workshop_tasks.open_session(history, task)
        assert migrated['id'] == original['id'] and migrated['path'] != str(old)
        raw = Path(migrated['path']).read_bytes()
        target = tmp_path / 'Moved sessions'
        session_files.set_sessions_directory(target)
        changed = workshop_tasks.open_session(history, task)
        assert Path(changed['path']).parent == target
        assert Path(changed['path']).read_bytes() == raw
        write = JsonFile.write
        failed = []
        def fail_once(owner, value):
            if owner.path.name == 'current.json' and not failed:
                failed.append(True)
                raise OSError('rollback test')
            return write(owner, value)
        monkeypatch.setattr(JsonFile, 'write', fail_once)
        with pytest.raises(OSError, match='rollback test'):
            session_files.set_sessions_directory(tmp_path / 'Failed move')
        reopened = workshop_tasks.open_session(history, task)
        assert reopened['id'] == original['id'] and reopened['path'] == changed['path']
        assert Path(reopened['path']).read_bytes() == raw
        assert history._db.execute('SELECT count(*) FROM workshop_tasks').fetchone()[0] == 1


def test_interrupted_task_binding_relocation_recovers_before_reopen(profile, monkeypatch):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        session = workshop_tasks.create_session(history, 'Interrupted workflow')
        document = session_files.read_document(session['path'])
        document['title'] = 'Recovered workflow'
        session_files.write_document(session['path'], document)
        with monkeypatch.context() as patch:
            patch.setattr(workshop_tasks, 'relocate_sessions', lambda *args: (_ for _ in ()).throw(SystemExit('interrupted')))
            with pytest.raises(SystemExit, match='interrupted'):
                session_files.move_session(session['path'], Path(session['path']).parent)
        opened = workshop_tasks.open_session(history, session['taskId'])
        assert opened['id'] == session['id'] and Path(opened['path']).stem == 'Recovered workflow'
        assert not (profile / 'data/sessions/file-move.json').exists()


def test_binding_failure_restores_file_before_returning_error(profile, monkeypatch):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        session = workshop_tasks.create_session(history, 'Rename failure')
        old = Path(session['path'])
        with monkeypatch.context() as patch:
            patch.setattr(workshop_tasks, 'relocate_sessions', lambda *args: (_ for _ in ()).throw(OSError('binding unavailable')))
            with pytest.raises(OSError, match='binding unavailable'):
                session_files.move_session(old, old.parent)
        assert old.exists()
        opened = workshop_tasks.open_session(history, session['taskId'])
        assert opened['id'] == session['id'] and opened['path'] == str(old)


def test_recovery_does_not_bind_task_to_a_reused_old_filename(profile, monkeypatch):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        session = workshop_tasks.create_session(history, 'Original workflow')
        old = Path(session['path'])
        with monkeypatch.context() as patch:
            patch.setattr(workshop_tasks, 'relocate_sessions', lambda *args: (_ for _ in ()).throw(SystemExit('crashed')))
            with pytest.raises(SystemExit):
                session_files.move_session(old, old.parent)
        unrelated = session_files.new_document('Unrelated document')
        session_files.write_document(old, unrelated)
        opened = workshop_tasks.open_session(history, session['taskId'])
        assert opened['id'] == session['id'] and opened['path'] != str(old)
        assert session_files.read_document(old) == unrelated


def test_task_owner_sqlite_failure_rolls_back_folder_move(profile, tmp_path):
    import sqlite3
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        session = workshop_tasks.create_session(history, 'A workflow')
        raw = Path(session['path']).read_bytes()
        history._db.execute("CREATE TRIGGER refuse_relocation BEFORE UPDATE OF session_path ON workshop_tasks "
                            "WHEN new.session_path LIKE '%Refused%' BEGIN SELECT RAISE(ABORT, 'relocate failed'); END")
        with pytest.raises(sqlite3.IntegrityError, match='relocate failed'):
            session_files.set_sessions_directory(tmp_path / 'Refused')
        opened = workshop_tasks.open_session(history, session['taskId'])
        assert opened['id'] == session['id'] and opened['path'] == session['path']
        assert Path(opened['path']).read_bytes() == raw
        assert not list((tmp_path / 'Refused').glob('*.archhub'))


def test_thirty_bound_workflows_move_without_new_tasks_or_documents(profile, tmp_path):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        sessions = [workshop_tasks.create_session(history, 'Workflow %d' % index) for index in range(30)]
        target = tmp_path / 'Thirty workflows'
        session_files.set_sessions_directory(target)
        for session in sessions:
            opened = workshop_tasks.open_session(history, session['taskId'])
            assert opened['id'] == session['id'] and Path(opened['path']).parent == target
            assert not Path(session['path']).exists()
        assert len(list(target.glob('*.archhub'))) == 30
        assert history._db.execute('SELECT count(*) FROM workshop_tasks').fetchone()[0] == 30


def test_failed_health_and_interrupted_boot_restore_everything(profile):
    seed(profile)
    before = {path.relative_to(profile): path.read_bytes() for path in profile.rglob('*') if path.is_file()}
    quiet_update.stage_app_folder(profile)
    assert not quiet_update.finish_app_folder(profile, healthy=False)['pending']
    for name, raw in before.items():
        assert (profile / name).read_bytes() == raw
    quiet_update.stage_app_folder(profile)
    quiet_update.stage_app_folder(profile)  # interrupted prior boot is restored before retry
    quiet_update.finish_app_folder(profile, healthy=False)
    for name, raw in before.items():
        assert (profile / name).read_bytes() == raw


@pytest.mark.skipif(os.name != 'nt', reason='real Windows sharing violation')
def test_file_held_by_live_process_is_skipped(profile):
    path = profile / 'candidate-locked.log'
    path.write_bytes(b'held open')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        result = quiet_update.stage_app_folder(profile)
        assert any(row['path'] == path.name for row in result['skipped'])
        assert path.exists()
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))
    assert path.read_bytes() == b'held open'


def test_one_folder_migration_preserves_bytes_and_readable_names(profile):
    legacy = profile / 'sessions-files'
    (legacy / 'skills').mkdir(parents=True)
    documents = [session_files.new_document('Door schedule'), session_files.new_document('Door schedule'),
                 session_files.new_document('My Canvas')]
    originals = {}
    for index, document in enumerate(documents):
        path = (legacy / 'skills' if index < 2 else legacy) / (document['id'] + '.archhub')
        session_files.write_document(path, document)
        originals[document['id']] = path.read_bytes()
    test_file = legacy / 'verification.archhub'
    session_files.write_document(test_file, session_files.new_document('UI verification'))
    moved = session_files.migrate_sessions(profile)
    assert len(moved) == 3
    assert not (legacy / 'skills').exists()
    folder = session_files.sessions_directory()
    assert folder == Path(os.environ['USERPROFILE']) / 'ArchHub/Sessions'
    assert {path.name for path in folder.iterdir()} == {'Door schedule.archhub', 'Door schedule (2).archhub', 'My Canvas.archhub'}
    for path in folder.iterdir():
        assert path.read_bytes() == originals[session_files.read_document(path)['id']]
    assert session_files.migrate_sessions(profile) == []
    quiet_update.stage_app_folder(profile)
    quiet_update.finish_app_folder(profile, healthy=True)
    assert not test_file.exists()
    assert len(session_files.load_skills()) == 3


def test_save_open_save_as_and_library_use_same_files(profile, tmp_path):
    owner = session_files.SessionFiles()
    document = session_files.new_document('Facade study')
    saved = owner.dispatch({'action': 'save', 'document': document})
    assert Path(saved['path']).name == 'Facade study.archhub'
    assert session_files.load_skills()[0]['path'] == Path(saved['path'])
    opened = owner.dispatch({'action': 'open', 'path': saved['path']})
    assert opened['document'] == document
    document['notes'].append({'text': 'Edited on Canvas'})
    owner.dispatch({'action': 'save', 'path': saved['path'], 'document': document})
    assert session_files.read_document(saved['path']) == document
    elsewhere = tmp_path / 'Shared file.archhub'
    result = owner.dispatch({'action': 'save', 'save_as': True, 'document': document},
                            save_picker=lambda *args: str(elsewhere))
    assert Path(result['path']) == elsewhere
    assert session_files.read_document(elsewhere) == {**document, 'title': elsewhere.stem}
    assert owner.current_path() == str(elsewhere)


def test_title_collisions_and_windows_reserved_names(profile):
    owner = session_files.SessionFiles()
    first = owner.dispatch({'action': 'autosave', 'document': session_files.new_document('Same')})
    second = owner.dispatch({'action': 'autosave', 'document': session_files.new_document('Same')})
    assert Path(first['path']).name == 'Same.archhub'
    assert Path(second['path']).name == 'Same (2).archhub'
    assert session_files.document_path(owner.directory, session_files.new_document('CON')).name == '_CON.archhub'


def test_user_documents_and_credentials_in_unknown_folders_are_retained(profile):
    other = profile / 'user-folder'
    other.mkdir()
    session_files.write_document(other / 'My work.archhub', session_files.new_document('My work'))
    key = profile / 'device.key'
    key.write_bytes(b'user credential')
    before = (other / 'My work.archhub').read_bytes()
    result = quiet_update.stage_app_folder(profile)
    assert result == {'staged': [], 'skipped': []}
    quiet_update.finish_app_folder(profile, healthy=True)
    assert (other / 'My work.archhub').read_bytes() == before
    assert key.read_bytes() == b'user credential'


@pytest.mark.parametrize('name', ['New work.archhub', 'report.pdf', 'budget.xlsx', 'config.json', '.env', 'device.pfx'])
def test_data_added_after_staging_is_not_deleted(profile, name):
    junk = profile / '_deploy_backup'
    junk.mkdir()
    (junk / 'old.log').write_bytes(b'old')
    quiet_update.stage_app_folder(profile)
    staged = profile / '_cleanup-staging/_deploy_backup'
    if name.endswith('.archhub'):
        session_files.write_document(staged / name, session_files.new_document('New work'))
    else:
        (staged / name).write_bytes(b'user data')
    result = quiet_update.finish_app_folder(profile, healthy=True)
    assert result['pending'] and (staged / name).exists()
    quiet_update.finish_app_folder(profile, healthy=False)
    assert (junk / name).exists()


def test_migration_updates_current_and_recent_without_changing_documents(profile):
    source = profile / 'sessions-files'
    source.mkdir()
    document = session_files.new_document('Real session')
    old = source / (document['id'] + '.archhub')
    session_files.write_document(old, document)
    raw = old.read_bytes()
    (source / 'current.json').write_text(json.dumps({'id': document['id']}), encoding='utf-8')
    (source / 'recent.json').write_text(json.dumps([{'path': str(old)}]), encoding='utf-8')
    session_files.migrate_sessions(profile)
    owner = session_files.SessionFiles()
    assert Path(owner.current_path()).read_bytes() == raw
    assert owner.recent()[0]['path'] == owner.current_path()
    assert not source.exists()


def test_migration_to_legacy_directory_never_unlinks_its_only_copy(profile):
    folder = profile / 'sessions-files'
    folder.mkdir()
    path = folder / 'My work.archhub'
    session_files.write_document(path, session_files.new_document('My work'))
    before = path.read_bytes()
    settings = profile / 'settings/settings.json'
    settings.parent.mkdir()
    settings.write_text(json.dumps({'sessionsFolder': str(folder)}), encoding='utf-8')
    assert session_files.migrate_sessions(profile) == []
    assert path.read_bytes() == before


def test_changing_folder_moves_files_and_current_pointer_byte_for_byte(profile, tmp_path):
    owner = session_files.SessionFiles()
    document = session_files.new_document('My work')
    old = Path(owner.dispatch({'action': 'save', 'document': document})['path'])
    before = old.read_bytes()
    target = tmp_path / 'Chosen folder'
    moved = session_files.set_sessions_directory(target)
    assert moved == [(str(old), str(target / old.name))]
    assert not old.exists()
    assert (target / old.name).read_bytes() == before
    assert session_files.SessionFiles().current_path() == str(target / old.name)
    assert session_files.load_skills()[0]['path'] == target / old.name


def test_folder_change_restores_files_and_pointers_when_pointer_write_fails(profile, tmp_path, monkeypatch):
    from nodelang.nograph_server import JsonFile
    owner = session_files.SessionFiles()
    old = Path(owner.dispatch({'action': 'save', 'document': session_files.new_document('My work')})['path'])
    before = old.read_bytes()
    target = tmp_path / 'Chosen folder'
    write = JsonFile.write
    failed = []
    def fail_once(file, value):
        if file.path.name == 'current.json' and not failed:
            failed.append(True)
            raise OSError('pointer write failed')
        return write(file, value)
    monkeypatch.setattr(JsonFile, 'write', fail_once)
    with pytest.raises(OSError, match='pointer write failed'):
        session_files.set_sessions_directory(target)
    assert old.read_bytes() == before and not list(target.glob('*.archhub'))
    assert session_files.SessionFiles().current_path() == str(old)
    assert session_files.sessions_directory() == old.parent
    assert not (profile / 'data/sessions/folder-move.json').exists()


def test_interrupted_folder_change_is_restored_before_next_reader(profile, tmp_path, monkeypatch):
    owner = session_files.SessionFiles()
    old = Path(owner.dispatch({'action': 'save', 'document': session_files.new_document('My work')})['path'])
    before = old.read_bytes()
    target = tmp_path / 'Chosen folder'
    move = session_files.move_session
    class Interrupted(BaseException):
        pass
    def interrupted(*args, **kwargs):
        move(*args, **kwargs)
        raise Interrupted()
    monkeypatch.setattr(session_files, 'move_session', interrupted)
    with pytest.raises(Interrupted):
        session_files.set_sessions_directory(target)
    assert not old.exists() and (profile / 'data/sessions/folder-move.json').exists()
    assert session_files.sessions_directory() == old.parent
    assert old.read_bytes() == before and not list(target.glob('*.archhub'))
    assert session_files.SessionFiles().current_path() == str(old)


def test_renaming_a_session_renames_the_file_without_a_guid_or_duplicate(profile):
    owner = session_files.SessionFiles()
    document = session_files.new_document('Untitled')
    saved = owner.dispatch({'action': 'autosave', 'document': document})
    document = saved['document']
    document['title'] = 'Facade study'
    renamed = owner.dispatch({'action': 'autosave', 'document': document, 'path': saved['path'],
                              'base_revision': saved['revision']})
    assert Path(renamed['path']).name == 'Facade study.archhub'
    assert not Path(saved['path']).exists()
    assert [path.name for path in owner.directory.glob('*.archhub')] == ['Facade study.archhub']
    assert owner.current_path() == renamed['path']


@pytest.mark.skipif(os.name != 'nt', reason='Windows cross-volume write exclusion')
def test_cross_volume_fallback_excludes_writers_and_preserves_bytes(profile, monkeypatch, tmp_path):
    import errno
    source = session_files.sessions_directory() / 'Original.archhub'
    session_files.write_document(source, session_files.new_document('Original'))
    raw = source.read_bytes()
    target = tmp_path / 'Destination'
    target.mkdir()
    rename = Path.rename
    def cross_volume(path, destination):
        if path == source:
            raise OSError(errno.EXDEV, 'different volume')
        return rename(path, destination)
    fsync = os.fsync
    def verify_exclusion(fd):
        with pytest.raises(PermissionError):
            source.write_bytes(b'concurrent writer')
        return fsync(fd)
    monkeypatch.setattr(Path, 'rename', cross_volume)
    monkeypatch.setattr(os, 'fsync', verify_exclusion)
    moved = session_files.move_session(source, target)
    assert not source.exists() and Path(moved).read_bytes() == raw


def test_rendered_library_opens_the_real_session_and_exports_archhub(profile):
    import subprocess
    from nodelang.nograph_server import NoGraphServer
    root = Path(__file__).resolve().parents[2]
    subprocess.run(['node', '--max-old-space-size=512', str(root / '03.TOOLS/packaging/compile_studio.cjs')],
                   cwd=root, check=True, capture_output=True, text=True, timeout=180)
    owner = session_files.SessionFiles()
    saved = owner.dispatch({'action': 'save', 'document': session_files.new_document('Facade study')})
    server = NoGraphServer(profile)
    save_as = profile.parent / "Shared study.archhub"
    def delayed_save_picker(title, name_filter="", default_path=""):
        import time
        time.sleep(1)  # An edit can arrive while the native Save As dialog is open.
        return str(save_as)
    server.native_save_file_picker = delayed_save_picker
    server._hosts.get = lambda: []
    server._local.get = lambda: []
    server.start()
    try:
        result = subprocess.run(['node', '02.TESTS/tests_js/apptidy_sessions.test.mjs'],
                                input=json.dumps({'url': server.public_url + '/studio/?bootstrap=' + server.browser_bootstrap_token,
                                                  'path': saved['path'], 'saveAs': str(save_as)}),
                                cwd=root, text=True, encoding='utf-8', capture_output=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'APPTIDY rendered Library open, Run, Save As and .archhub export PASS' in result.stdout
        assert json.loads(save_as.read_text(encoding='utf-8'))['title'] == 'Shared study'
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()
        server.thread.join(timeout=5)


def test_router_trace_is_rotated_under_logs_without_a_root_writer(profile, monkeypatch):
    from nodelang import model_router
    monkeypatch.setattr(model_router, '_FREE_CHAT_TRACE_BYTES', 64)
    for index in range(20):
        model_router._append_free_chat_trace_line({'ARCHHUB_STATE_DIR': str(profile)}, {'step': str(index) * 8})
    assert not (profile / 'free-chat-trace.jsonl').exists()
    logs = list((profile / 'logs').glob('free-chat-trace.jsonl*'))
    assert 1 < len(logs) <= 4
    assert all(path.stat().st_size <= 128 for path in logs)


@pytest.mark.skipif(os.name != 'nt', reason='Windows directory junction')
def test_linked_staging_is_refused_without_touching_target(profile, tmp_path):
    import subprocess
    external = tmp_path / 'External'
    external.mkdir()
    retained = external / 'keep.txt'
    retained.write_bytes(b'kept')
    stage = profile / '_cleanup-staging'
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(stage), str(external)], check=True, capture_output=True)
    try:
        with pytest.raises(ValueError, match='plain application folder'):
            quiet_update.stage_app_folder(profile)
        with pytest.raises(ValueError, match='links or reparse'):
            quiet_update.finish_app_folder(profile, healthy=True)
        assert retained.read_bytes() == b'kept'
    finally:
        stage.rmdir()


@pytest.mark.skipif(os.name != 'nt', reason='Windows Known Folder Move registry')
def test_redirected_documents_are_detected_but_never_used_by_default(profile, tmp_path, monkeypatch, caplog):
    import winreg
    redirected = tmp_path / 'OneDrive' / 'Documents'
    calls = []
    query = winreg.QueryValueEx
    def redirected_documents(key, name):
        if name == 'Personal':
            calls.append(name)
            return str(redirected), winreg.REG_EXPAND_SZ
        return query(key, name)
    monkeypatch.setattr(winreg, 'QueryValueEx', redirected_documents)
    resolve = Path.resolve
    def no_redirected_probe(path, *args, **kwargs):
        if path == redirected:
            raise AssertionError('Default selection must not probe redirected Documents')
        return resolve(path, *args, **kwargs)
    with monkeypatch.context() as patch, caplog.at_level('INFO', logger='nodelang.session_files'):
        patch.setattr(Path, 'resolve', no_redirected_probe)
        folder = session_files.sessions_directory()
    assert calls and 'Documents is redirected' in caplog.text
    assert folder == Path(os.environ['USERPROFILE']) / 'ArchHub/Sessions'
    assert not redirected.exists()
    session_files.set_sessions_directory(redirected)
    assert session_files.sessions_directory() == redirected


@pytest.mark.skipif(os.name != 'nt', reason='Windows reader handle excludes replacement')
def test_background_metadata_reader_does_not_break_current_file_replace(profile, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    owner = session_files.SessionFiles()
    saved = owner.dispatch({'action': 'save', 'document': session_files.new_document('Original')})
    current = owner.metadata / 'current.json'
    entered, release, writing = threading.Event(), threading.Event(), threading.Event()
    read_text = Path.read_text
    def held_read(path, *args, **kwargs):
        if path == current and threading.current_thread().name.startswith('metadata-reader'):
            with path.open('r', encoding='utf-8') as stream:
                entered.set()
                assert release.wait(3)
                return stream.read()
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', held_read)
    def write_current():
        writing.set()
        owner._current('updated', saved['path'])
    with ThreadPoolExecutor(1, thread_name_prefix='metadata-reader') as readers, ThreadPoolExecutor(1) as writers:
        reader = readers.submit(session_files.SessionFiles().open_files)
        try:
            assert entered.wait(1)
            writer = writers.submit(write_current)
            assert writing.wait(1)
            with pytest.raises(TimeoutError):
                writer.result(timeout=.05)
        finally:
            release.set()
        assert reader.result(timeout=2)[0]['path'] == saved['path']
        writer.result(timeout=2)
    assert json.loads(current.read_text(encoding='utf-8'))['id'] == 'updated'
