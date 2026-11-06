"""Task-owned workflow creation and automatic agent steps, with disposable state only."""
import pytest


@pytest.fixture
def history(tmp_path, monkeypatch):
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(name, str(directory))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    from nodelang.workshop_mailbox import application_history
    with application_history(database=tmp_path / 'messages.sqlite3') as held:
        yield held


def test_create_has_start_and_does_not_select_file(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import SessionFiles, read_document
    row = tasks.create(history, 'Review drawings', 'founder')
    document = read_document(row['session_path'])
    assert document['nodes'][0]['title'] == 'Start \u00b7 Review drawings'
    assert document['properties']['taskContext']['task'] == row['id']
    assert not SessionFiles().current_path()
    assert tasks.open_session(history, row['id'], select=False)['path'] == row['session_path']


def test_backfill_all_94_preserves_data_and_is_idempotent(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    for i in range(94):
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at,result) "
                     "VALUES(?,?,'open','founder','then','then','retained')", (str(i), 'Task ' + str(i)))
    before = [tuple(row) for row in history._db.execute('SELECT id,title,status,result,created_at FROM workshop_tasks')]
    assert tasks.backfill_sessions(history) == 94
    rows = tasks.rows(history)
    contents = {r['session_path']: read_document(r['session_path']) for r in rows}
    assert len(contents) == 94
    assert tasks.backfill_sessions(history) == 0
    assert before == [tuple(row) for row in history._db.execute('SELECT id,title,status,result,created_at FROM workshop_tasks')]
    assert contents == {p: read_document(p) for p in contents}


def test_failed_backfill_rolls_back_bindings_and_reuses_written_file(history, monkeypatch):
    from nodelang import workshop_tasks as tasks, canvas_documents
    from nodelang.session_files import sessions_directory
    for key in ('a', 'b'):
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
                     "VALUES(?,?,'open','founder','then','then')", (key, key))
    edit = canvas_documents.edit
    def fail(path, *args, **kwargs):
        if path.stem == 'b':
            raise OSError('simulated disk failure')
        return edit(path, *args, **kwargs)
    monkeypatch.setattr(canvas_documents, 'edit', fail)
    with pytest.raises(OSError, match='simulated disk failure'):
        tasks.backfill_sessions(history)
    assert all(row['session_path'] is None for row in tasks.rows(history))
    path = sessions_directory() / 'a.archhub'
    written = path.read_bytes()
    monkeypatch.setattr(canvas_documents, 'edit', edit)
    assert tasks.backfill_sessions(history) == 2
    assert path.read_bytes() == written


def test_file_writes_do_not_hold_mailbox_transaction(history, monkeypatch):
    from nodelang import workshop_tasks as tasks, canvas_documents
    edit = canvas_documents.edit
    def unlocked(*args, **kwargs):
        assert not history._db.in_transaction
        return edit(*args, **kwargs)
    monkeypatch.setattr(canvas_documents, 'edit', unlocked)
    tasks.create(history, 'New task', 'founder')
    tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
                 "VALUES('old','Old task','open','founder','then','then')", ())
    assert tasks.backfill_sessions(history) == 1


def test_migration_only_on_first_writable_open(history, monkeypatch):
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox
    path = history._database_path if hasattr(history, '_database_path') else history._db.execute('PRAGMA database_list').fetchone()[2]
    mailbox._SESSION_MIGRATED.discard(str(__import__('pathlib').Path(path).resolve()))
    calls = []
    monkeypatch.setattr(tasks, 'backfill_sessions', lambda held: calls.append(held) or 0)
    with mailbox.application_history(database=path, read_only=True):
        pass
    assert calls == []
    for _ in range(2):
        with mailbox.application_history(database=path):
            pass
    assert len(calls) == 1


def test_declare_and_complete_write_ordered_steps_without_canvas_calls(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    task = tasks.create(history, 'Coordinate drawings', 'founder')
    for owner, label in [('codex-session', 'Codex'), ('claude-session', 'Claude Code')]:
        assert tasks.declared(history, 'root-' + owner, task['id'], 'Review drawings', 'working', owner, label)
        assert tasks.release(history, task['id'], owner)
    assert tasks.declared(history, 'root-codex-session', task['id'], 'Export drawings', 'working', 'codex-session', 'Codex')
    document = read_document(task['session_path'])
    steps = [n for n in document['nodes'] if n['type'] == 'thing.agent']
    assert len(steps) == 2
    assert steps[0]['title'] == 'Export drawings'
    assert steps[0]['params']['status'] == 'working'
    assert [(w['from']['node'], w['to']['node']) for w in document['wires']] == [
        ('start', steps[0]['id']), (steps[0]['id'], steps[1]['id'])]
    assert tasks.complete(history, task['id'], 'codex-session', 'commit 12345678')
    updated = read_document(task['session_path'])
    step = next(n for n in updated['nodes'] if n['id'] == steps[0]['id'])
    assert step['params']['status'] == 'done'
    assert step['params']['result'] == 'commit 12345678'
    assert len(updated['nodes']) == 3


def test_legacy_open_creates_start_once(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
                 "VALUES('legacy','Legacy task','open','founder','then','then')", ())
    first = tasks.open_session(history, 'legacy', select=False)
    second = tasks.open_session(history, 'legacy', select=False)
    assert first['path'] == second['path']
    assert read_document(first['path'])['nodes'][0]['params'] == {'type': 'text', 'value': 'Legacy task'}


def test_failed_claim_does_not_write_steps(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    task = tasks.create(history, 'Held task', 'founder')
    tasks.claim(history, task['id'], 'first', 'First')
    assert not tasks.declared(history, 'second-root', task['id'], 'Wrong holder', 'working', 'second', 'Second')
    assert len(read_document(task['session_path'])['nodes']) == 1


def test_declared_task_and_archived_purpose_have_files(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    for request in ('FIRST', 'SECOND'):
        assert tasks.declared(history, 'root', request, 'Declared work', 'working', 'agent', 'Agent')
    rows = tasks.rows(history)
    assert len(rows) == 2
    assert all(read_document(row['session_path']) for row in rows)


def test_completion_file_failure_reconciles_on_retry(history, monkeypatch):
    from nodelang import workshop_tasks as tasks, canvas_documents
    from nodelang.session_files import read_document
    row = tasks.create(history, 'Finish task', 'founder')
    tasks.claim(history, row['id'], 'agent', 'Agent')
    edit = canvas_documents.edit
    def fail(*args, **kwargs):
        raise OSError('disk unavailable')
    monkeypatch.setattr(canvas_documents, 'edit', fail)
    with pytest.raises(OSError, match='disk unavailable'):
        tasks.complete(history, row['id'], 'agent', 'commit 12345678')
    monkeypatch.setattr(canvas_documents, 'edit', edit)
    tasks.complete(history, row['id'], 'agent', 'commit 12345678')
    step = read_document(row['session_path'])['nodes'][-1]
    assert step['params']['result'] == 'commit 12345678'
    assert step['params']['status'] == 'done'
