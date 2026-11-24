"""Projects > tasks > subtasks on the one Workshop task owner (parent_id on the task row), in a disposable profile only."""
from types import SimpleNamespace

import psutil
import pytest


@pytest.fixture
def profile(tmp_path, monkeypatch):
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.delenv('ARCHHUB_AGENT_PROFILE', raising=False)
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKSHOP_STATE_DIR', str(tmp_path / 'transport'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    folder = tmp_path / 'Work' / 'Tower'
    folder.mkdir(parents=True)
    from nodelang.nograph_server import JsonFile
    from nodelang.user_paths import state_directory
    JsonFile(state_directory() / 'settings/workspaces.json', {}).update({'roots': [
        {'root_id': 'tower', 'label': 'Tower', 'path': str(folder)}]})
    return folder


def test_a_subtask_names_its_parent_and_sits_in_its_project(profile):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        top = tasks.create_session(history, 'Tower drawings', select=False, workspace='tower')['taskId']
        sub = tasks.create_session(history, 'Ground floor plan', select=False, parent=top)['taskId']
        leaf = tasks.create_session(history, 'Door tags', select=False, parent=sub)['taskId']
        alone = tasks.create_session(history, 'Loose note', select=False)['taskId']
        rows = {row['id']: row for row in tasks.column(history)}
        stored = {row['id']: row for row in tasks.rows(history)}
    assert [rows[top]['parent'], rows[sub]['parent'], rows[leaf]['parent'], rows[alone]['parent']] == ['', top, sub, '']
    assert [rows[t]['project'] for t in (top, sub, leaf)] == ['Tower', 'Tower', 'Tower'], 'a subtask inherits its parent project'
    assert rows[alone]['project'] == ''
    # Each level has its own task id on the chosen canvas.
    paths = [stored[t]['session_path'] for t in (top, sub, leaf)]
    assert all(paths) and len(set(paths)) == 1
    assert stored[alone]['session_path'] != paths[0]


def test_a_missing_parent_is_refused_and_writes_nothing(profile):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        before = len(tasks.rows(history))
        with pytest.raises(ValueError):
            tasks.create_session(history, 'Orphan', select=False, parent='no-such-task')
        assert len(tasks.rows(history)) == before


def test_an_agent_creates_a_subtask_through_the_workshop(profile):
    from nodelang import workshop_mailbox as mailbox
    from nodelang import workshop_tasks as tasks
    process = psutil.Process()
    peer = SimpleNamespace(pid=process.pid, created_at=process.create_time(), cwd=str(profile))
    context = {'claude/sessionID': 'hierarchy-claude-a'}
    top = mailbox.call('task_create', {'title': 'Tower drawings'}, context, peer=peer)
    top_id = (top.get('result') or top)['task']['id']
    sub = mailbox.call('task_create', {'title': 'Sections', 'parent': top_id}, context, peer=peer)
    sub_row = (sub.get('result') or sub)['task']
    assert sub_row['parent_id'] == top_id
    with mailbox.application_history() as history:
        assert next(row for row in tasks.column(history) if row['id'] == sub_row['id'])['parent'] == top_id


def test_a_subtask_file_carries_its_parent_workspace_from_the_ui_and_from_an_agent(profile):
    from nodelang import workshop_mailbox as mailbox
    from nodelang.nograph_server import _create_task
    from nodelang.session_files import list_sessions, read_document
    studio = SimpleNamespace(files={'settings': SimpleNamespace(read=lambda: {})})
    top = _create_task(studio, 'Tower drawings', '', 'tower')['taskId']
    # The Studio's Add subtask names no workspace; the parent is the one source of it.
    from_ui = _create_task(studio, 'Ground floor plan', '', '', top)['taskId']
    process = psutil.Process()
    peer = SimpleNamespace(pid=process.pid, created_at=process.create_time(), cwd=str(profile))
    made = mailbox.call('task_create', {'title': 'Sections', 'parent': top}, {'claude/sessionID': 'hierarchy-claude-b'}, peer=peer)
    from_agent = (made.get('result') or made)['task']['id']
    from nodelang import workshop_tasks as tasks
    with mailbox.application_history() as history:
        files = {task: tasks.get(history, task)['session_path'] for task in (top, from_ui, from_agent)}
    for task in (from_ui, from_agent):
        assert read_document(files[task])['properties']['taskContext']['workspace'] == 'tower', task
    listed = {session['path']: session for group in list_sessions()['groups'] for session in group['sessions']}
    assert [listed[files[task]]['project']['label'] for task in (top, from_ui, from_agent)] == ['Tower', 'Tower', 'Tower']


def test_an_old_task_table_gains_parent_id_and_keeps_its_rows(profile):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        history._db.execute("DROP TABLE IF EXISTS workshop_tasks")
        history._db.execute(tasks.SCHEMA.replace(", parent_id TEXT", ""))
        history._db.execute("INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at) "
                            "VALUES('old1','Old work','open','founder','2026-01-01','2026-01-01')")
        found = tasks.rows(history)
        names = {row[1] for row in history._db.execute("PRAGMA table_info(workshop_tasks)")}
    assert 'parent_id' in names
    assert [(row['id'], row['title'], row['parent_id']) for row in found] == [('old1', 'Old work', None)]


def test_session_contexts_survive_a_restart_without_reopening_unchanged_files(tmp_path, monkeypatch):
    """e988 e7bad9c9: the first Home/History read after a start reopened and validated every session file (1 s / 3 s
    for 47 / 200 canvases). The disposable cache file skips unchanged files; a changed file is read again."""
    import os, time
    from nodelang import session_files, workshop_tasks
    monkeypatch.setattr(workshop_tasks, '_contexts_file', lambda: tmp_path / 'cache' / 'session-contexts.json')
    monkeypatch.setattr(workshop_tasks, '_SESSION_CONTEXTS', {})
    monkeypatch.setattr(workshop_tasks, '_CONTEXTS_LOADED', set())
    document = tmp_path / 'one.archhub'
    session_files.write_document(document, session_files.new_document('Cached title'))
    old = time.time() - 60
    os.utime(document, (old, old))
    first = workshop_tasks._session_context(str(document), roots={})
    assert first['sessionTitle'] == 'Cached title'
    workshop_tasks._save_session_contexts()
    assert (tmp_path / 'cache' / 'session-contexts.json').is_file()
    # A new process: empty memory, and reading the file would fail the test.
    monkeypatch.setattr(workshop_tasks, '_SESSION_CONTEXTS', {})
    monkeypatch.setattr(workshop_tasks, '_CONTEXTS_LOADED', set())
    monkeypatch.setattr(session_files, 'read_document', lambda path: (_ for _ in ()).throw(AssertionError('reopened')))
    assert workshop_tasks._session_context(str(document), roots={})['sessionTitle'] == 'Cached title'
    # A changed file is read again.
    monkeypatch.undo()
    monkeypatch.setattr(workshop_tasks, '_contexts_file', lambda: tmp_path / 'cache' / 'session-contexts.json')
    changed = session_files.new_document('Renamed title')
    session_files.write_document(document, changed)
    os.utime(document, (old + 5, old + 5))
    assert workshop_tasks._session_context(str(document), roots={})['sessionTitle'] == 'Renamed title'


def test_tasks_sharing_one_canvas_read_it_once(tmp_path, monkeypatch):
    """e988 af92e1e1: 24 tasks on one .archhub made Home open that file 18 times."""
    import os, time
    from nodelang import session_files, workshop_tasks
    monkeypatch.setattr(workshop_tasks, '_contexts_file', lambda: tmp_path / 'cache' / 'session-contexts.json')
    monkeypatch.setattr(workshop_tasks, '_SESSION_CONTEXTS', {})
    monkeypatch.setattr(workshop_tasks, '_CONTEXTS_LOADED', set())
    shared = tmp_path / 'shared.archhub'
    canvas = session_files.new_document('Shared canvas')
    for i in range(18):
        canvas['nodes'].append({'id': 'task-%d' % i, 'type': 'note', 'title': 'Child %d' % i, 'params': {},
                                'position': {'x': i * 10, 'y': 0}, 'workshopTask': 'task-%d' % i,
                                'taskContext': {'task': 'task-%d' % i}})
    session_files.write_document(shared, canvas)
    old = time.time() - 60
    os.utime(shared, (old, old))
    real, reads = session_files.read_document, []
    monkeypatch.setattr(session_files, 'read_document', lambda path: reads.append(path) or real(path))
    home, history = {}, {}   # two overlapping lists, each with its own memo (e988 8bd3702f)
    first = workshop_tasks._session_context(str(shared), roots={}, task_row={'id': 'task-0'}, documents=home)
    others = [workshop_tasks._session_context(str(shared), roots={}, task_row={'id': 'task-%d' % i}, documents=history)
              for i in range(18)]
    titles = [first.get('sessionTitle')] + [workshop_tasks._session_context(
        str(shared), roots={}, task_row={'id': 'task-%d' % i}, documents=home).get('sessionTitle') for i in range(1, 18)]
    assert titles == ['Child %d' % i for i in range(18)] and [o.get('sessionTitle') for o in others] == titles
    assert len(reads) == 2   # one read per list, even when the lists overlap


def test_a_same_tick_atomic_save_is_never_served_from_the_cache(tmp_path, monkeypatch):
    """e988 9ecccd2b: 'Zone A' -> 'Zone B' saved atomically within one coarse timestamp tick (same size, same mtime)
    was served as A from the cache, even by a fresh process."""
    import os, time
    from nodelang import session_files, workshop_tasks
    monkeypatch.setattr(workshop_tasks, '_contexts_file', lambda: tmp_path / 'cache' / 'session-contexts.json')
    monkeypatch.setattr(workshop_tasks, '_SESSION_CONTEXTS', {})
    monkeypatch.setattr(workshop_tasks, '_CONTEXTS_LOADED', set())
    canvas = tmp_path / 'zone.archhub'
    session_files.write_document(canvas, session_files.new_document('Zone A'))
    old = time.time() - 60
    os.utime(canvas, ns=(int(old * 1e9), int(old * 1e9)))
    assert workshop_tasks._session_context(str(canvas), roots={})['sessionTitle'] == 'Zone A'
    workshop_tasks._save_session_contexts()
    session_files.write_document(canvas, session_files.new_document('Zone B'))        # atomic replace, same size
    os.utime(canvas, ns=(int(old * 1e9), int(old * 1e9)))                             # the coarse tick hides it
    assert workshop_tasks._session_context(str(canvas), roots={})['sessionTitle'] == 'Zone B'
    monkeypatch.setattr(workshop_tasks, '_SESSION_CONTEXTS', {})                       # a fresh process
    monkeypatch.setattr(workshop_tasks, '_CONTEXTS_LOADED', set())
    assert workshop_tasks._session_context(str(canvas), roots={})['sessionTitle'] == 'Zone B'
    # A file still settling (written under 2 s ago) is read but never kept.
    fresh = tmp_path / 'fresh.archhub'
    session_files.write_document(fresh, session_files.new_document('Just saved'))
    assert workshop_tasks._session_context(str(fresh), roots={})['sessionTitle'] == 'Just saved'
    assert not any(key[0] == str(fresh) for key in workshop_tasks._SESSION_CONTEXTS)
