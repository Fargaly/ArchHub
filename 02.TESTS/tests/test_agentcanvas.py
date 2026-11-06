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
