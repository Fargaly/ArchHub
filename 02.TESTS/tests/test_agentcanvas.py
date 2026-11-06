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
    assert len([tasks.open_session(history, row['id'], select=False) for row in rows]) == 94
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


def test_bound_open_reuses_workflow_even_with_another_path(history, tmp_path):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import new_document, read_document, write_document
    row = tasks.create(history, 'Bound workflow', 'founder')
    other = tmp_path / 'other.archhub'
    write_document(other, new_document('Other workflow'))
    before = other.read_bytes()
    opened = tasks.open_session(history, row['id'], str(other), select=False)
    assert opened['path'] == row['session_path']
    assert opened['id'] == read_document(row['session_path'])['id']
    assert other.read_bytes() == before
    assert tasks.get(history, row['id'])['revision'] == row['revision']


def test_step_reads_its_own_mailbox_not_profile_database(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import ROOM, CATEGORY
    from nodelang.session_files import read_document
    row = tasks.create(history, 'Mailbox owner', 'founder')
    message = history.append(ROOM, author='Agent [agent]', content='Own mailbox message', category=CATEGORY,
                             idempotency_key='own-mailbox-message')
    tasks.record_step(history, row['id'], 'agent', 'Agent', 'Work', 'working')
    step = read_document(row['session_path'])['nodes'][-1]
    assert step['params']['message_id'] == message['id']
    assert step['params']['last_message'] == 'Own mailbox message'


def test_declaration_records_own_step_without_taking_another_agents_lease(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    task = tasks.create(history, 'Held task', 'founder')
    tasks.claim(history, task['id'], 'first', 'First')
    assert not tasks.declared(history, 'second-root', task['id'], 'Wrong holder', 'working', 'second', 'Second')
    steps = read_document(task['session_path'])['nodes']
    assert len(steps) == 2 and steps[-1]['params']['agent'] == 'Second'
    assert tasks.get(history, task['id'])['owner'] == 'first'
    assert not tasks.complete(history, task['id'], 'second', 'not the holder')
    assert read_document(task['session_path'])['nodes'][-1]['params']['status'] == 'working'


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
    assert tasks.complete(history, row['id'], 'agent', 'commit 12345678')
    step = read_document(row['session_path'])['nodes'][-1]
    assert step['params']['result'] == 'commit 12345678'
    assert step['params']['status'] == 'done'


def test_done_declaration_never_copies_another_agents_result(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    row = tasks.create(history, 'Shared task', 'founder')
    tasks.claim(history, row['id'], 'first', 'First')
    tasks.complete(history, row['id'], 'first', 'commit first-agent')
    tasks.declared(history, 'second-root', row['id'], 'My step finished', 'done', 'second', 'Second')
    steps = read_document(row['session_path'])['nodes']
    assert steps[-1]['params']['result'] == ''
    assert steps[-1]['params']['status'] == 'done'
    assert tasks.get(history, row['id'])['result'] == 'commit first-agent'


@pytest.mark.parametrize('identity', ['../escape', 'app:workshop:declaration:legacy', 'CON', 'a/b'])
def test_legacy_task_ids_stay_inside_sessions_directory(history, identity):
    from pathlib import Path
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import sessions_directory, read_document
    tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
                 "VALUES(?,'Legacy task','open','founder','then','then')", (identity,))
    assert tasks.backfill_sessions(history) == 1
    row = tasks.get(history, identity)
    assert Path(row['session_path']).parent == sessions_directory()
    assert read_document(row['session_path'])['properties']['taskContext']['task'] == identity
    assert tasks.backfill_sessions(history) == 0


def test_native_transcripts_are_bounded_and_provider_scoped(history, monkeypatch, tmp_path):
    import json
    from nodelang.agent_status import read_transcript, transcript_path
    monkeypatch.setenv('ARCHHUB_AGENT_PROFILE', str(tmp_path))
    codex = tmp_path / '.codex/sessions/fixture/rollout-date-native-id.jsonl'
    claude = tmp_path / '.claude/projects/fixture/native-id.jsonl'
    for path in (codex, claude):
        path.parent.mkdir(parents=True, exist_ok=True)
    codex.write_text('\n'.join(json.dumps(row) for row in [None, [], {'type': 'response_item', 'payload': None},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Codex answer'}]}}]), encoding='utf-8')
    claude.write_text(json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Claude answer'}]}}), encoding='utf-8')
    assert read_transcript('codex', 'native-id')['messages'][0]['text'] == 'Codex answer'
    assert read_transcript('claude', 'native-id')['messages'][0]['text'] == 'Claude answer'
    assert transcript_path('codex', '../native-id') is None
    assert transcript_path('codex', '*') is None
    assert transcript_path('unsupported', 'native-id') is None
    with pytest.raises(ValueError, match='No native transcript'):
        read_transcript('claude', 'missing-id')


def test_agents_view_does_not_create_or_change_workflows(history, monkeypatch):
    import json
    import os
    import psutil
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox, nograph_server as server, canvas_documents
    task = tasks.create(history, 'Read only workflow', 'founder')
    before = __import__('pathlib').Path(task['session_path']).read_bytes()
    history._db.execute('CREATE TABLE workshop_declarations(root TEXT PRIMARY KEY,record TEXT NOT NULL)')
    declaration = {'root': 'root', 'agent': 'Agent', 'session': 'session', 'status': 'working', 'runtime': 'codex',
                   'request_id': task['id'], 'pid': os.getpid(), 'created_at': psutil.Process().create_time()}
    history._db.execute('INSERT INTO workshop_declarations VALUES(?,?)', ('root', json.dumps(declaration)))
    monkeypatch.setattr(mailbox, 'profile_database', lambda: __import__('pathlib').Path(history._db.execute('PRAGMA database_list').fetchone()[2]))
    monkeypatch.setattr(server, '_list_agents', lambda: [])
    def never(*args, **kwargs):
        raise AssertionError('A derived Agents view wrote a workflow')
    monkeypatch.setattr(canvas_documents, 'edit', never)
    graph = server.r_agents_canvas(None, None)
    assert len(graph['sessions']) == 1 and len(graph['wires']) == 1
    assert graph['tasks'][0]['id'] == task['id']
    assert __import__('pathlib').Path(task['session_path']).read_bytes() == before
    assert tasks.get(history, task['id'])['revision'] == task['revision']


def test_backfill_binding_failure_is_atomic(history):
    import sqlite3
    from nodelang import workshop_tasks as tasks
    for key in ('a', 'b'):
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
                     "VALUES(?,?,'open','founder','then','then')", (key, key))
    history._db.execute("CREATE TRIGGER fail_binding BEFORE UPDATE OF session_path ON workshop_tasks "
                        "WHEN NEW.id='b' BEGIN SELECT RAISE(ABORT,'simulated binding failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='simulated binding failure'):
        tasks.backfill_sessions(history)
    assert all(row['session_path'] is None for row in tasks.rows(history))
    history._db.execute('DROP TRIGGER fail_binding')
    assert tasks.backfill_sessions(history) == 2


def test_migration_does_not_block_other_mailbox_opens(history, monkeypatch):
    import threading
    from nodelang import workshop_mailbox as mailbox
    path = history._db.execute('PRAGMA database_list').fetchone()[2]
    lock, finished, errors = threading.Lock(), threading.Event(), []
    monkeypatch.setattr(mailbox, '_SESSION_MIGRATION_LOCK', lock)
    def open_mailbox():
        try:
            with mailbox.application_history(database=path):
                pass
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()
    with lock:
        worker = threading.Thread(target=open_mailbox)
        worker.start()
        completed = finished.wait(1.5)
    worker.join(3)
    assert completed and not errors


def test_rendered_agents_and_task_steps():
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or subprocess.check_output(
        ['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"],
        text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    for command in (['node', '--max-old-space-size=512', '03.TOOLS/packaging/compile_studio.cjs'],
                    ['node', '02.TESTS/tests_js/agentcanvas.cjs']):
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=240,
                                env={**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': browser_cache, 'ARCHHUB_COURT_PYTHON': sys.executable},
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
