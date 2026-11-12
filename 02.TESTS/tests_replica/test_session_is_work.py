"""F337 SESSION-IS-THE-WORK: one session per piece of work, joined by every agent of any vendor.

Real Workshop SQLite mailbox, real task owner and real session files, in a disposable profile only.
Two vendors' start paths are their own declare calls: a Claude context and a Codex context.
"""
from pathlib import Path
from types import SimpleNamespace
import time

import psutil
import pytest

CLAUDE = lambda name: {'claude/sessionID': 'sessionwork-claude-' + name}
CODEX = lambda name: {'threadId': 'sessionwork-codex-' + name}


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setenv(name, str(directory))
    monkeypatch.delenv('ARCHHUB_AGENT_PROFILE', raising=False)
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKSHOP_STATE_DIR', str(tmp_path / 'transport'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    folder = tmp_path / 'Work' / 'Tower'
    other = tmp_path / 'Work' / 'Villa'
    folder.mkdir(parents=True)
    other.mkdir(parents=True)
    from nodelang.nograph_server import JsonFile
    from nodelang.user_paths import state_directory
    JsonFile(state_directory() / 'settings/workspaces.json', {}).update({'roots': [
        {'root_id': 'tower', 'label': 'Tower', 'path': str(folder)},
        {'root_id': 'villa', 'label': 'Villa', 'path': str(other)}]})
    return folder


def declare(context, folder, request, status='working', task='Coordinate the tower drawings', path=None, kind=None):
    from nodelang import workshop_mailbox as mailbox
    process = psutil.Process()
    peer = SimpleNamespace(pid=process.pid, created_at=process.create_time(), cwd=str(folder))
    body = {'task': task, 'paths': [str(path or folder)], 'status': status, 'request_id': request}
    return mailbox.call('declare', {**body, 'kind': kind} if kind else body, context, peer=peer)


def sessions():
    from nodelang.session_files import sessions_directory
    return sorted(sessions_directory().glob('*.archhub'))


def work_rows():
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        return [row for row in tasks.rows(history) if not row['id'].startswith('declared-')]


def steps(path):
    from nodelang.session_files import read_document
    return [n for n in read_document(path)['nodes'] if n.get('params', {}).get('workshop_step')]


def test_two_vendors_on_the_same_request_in_one_project_join_one_session(project):
    first = declare(CLAUDE('a'), project, 'F337')['declaration']
    second = declare(CODEX('b'), project, 'F337', task='Review the tower sheets')['declaration']
    rows = work_rows()
    assert len(rows) == 1 and first['work'] == second['work'] == rows[0]['id']
    assert len(sessions()) == 1
    assert sorted(m['owner'] for m in rows[0]['members']) == sorted([first['session'], second['session']])
    agents = sorted(step['params']['agent'] for step in steps(rows[0]['session_path']))
    assert len(agents) == 2 and agents[0] != agents[1]
    assert first['runtime'] != second['runtime']


def test_two_agents_on_different_requests_in_one_project_get_two_sessions(project):
    first = declare(CLAUDE('a'), project, 'APP-BUILD', path=project / 'app.txt')['declaration']
    second = declare(CODEX('b'), project, 'REVIT-RIBBON', path=project / 'ribbon.txt')['declaration']
    assert first['work'] != second['work']
    assert len(work_rows()) == 2 and len(sessions()) == 2


def test_a_new_request_moves_the_agent_and_ends_its_old_membership(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    first = declare(CLAUDE('a'), project, 'REQ-1')['declaration']
    with application_history() as history:
        old_path = Path(tasks.get(history, first['work'])['session_path'])
    before = old_path.read_bytes()
    moved = declare(CLAUDE('a'), project, 'REQ-2', task='Next step')['declaration']['work']
    assert moved != first['work']
    with application_history() as history:
        old = tasks.get(history, first['work'])
        assert old['status'] == 'open' and not old['archived']              # left as it is, never archived
        assert [m['lease_until'] for m in old['members'] if m['owner'] == first['session']] == [None]
        assert tasks.get(history, moved)['status'] == 'claimed'
    assert old_path.read_bytes() == before                                 # the old file is untouched
    assert declare(CLAUDE('a'), project, 'REQ-1')['declaration']['work'] == first['work']   # back to that work


def test_without_a_request_never_guess_and_never_wake_a_30_hour_old_session(project):
    from datetime import datetime, timedelta, timezone
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        quiet = tasks.create_session(history, 'Quiet tower work', select=False, workspace='tower')['taskId']
        assert tasks.declared(history, 'root-a', '', 'Tower work', 'working', 'agent-a', 'Agent A', 'Tower', kind='start') == quiet
        assert tasks.declared(history, 'root-b', '', 'More tower work', 'working', 'agent-b', 'Agent B', 'Tower', kind='start') == quiet
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        history._db.execute("UPDATE workshop_tasks SET updated_at=?, lease_until=0, "
                            "members=json('[{\"owner\":\"agent-a\",\"lease_until\":0},{\"owner\":\"agent-b\",\"lease_until\":0}]') "
                            "WHERE id=?", (old, quiet))
        tasks.rows(history)                                                 # an app restart settles the lapsed lease
        assert tasks.get(history, quiet)['updated_at'] == old              # settling never refreshes activity
        assert tasks.declared(history, 'root-c', '', 'Tower again', 'working', 'agent-c', 'Agent C', 'Tower', kind='start') != quiet
        # A session that carries a request is never joined by a declare without one.
        asked = tasks.declared(history, 'root-d', 'F337', 'Request work', 'working', 'agent-d', 'Agent D', 'Villa')
        assert tasks.declared(history, 'root-e', '', 'Villa work', 'working', 'agent-e', 'Agent E', 'Villa', kind='start') != asked


def test_two_open_sessions_mean_a_new_one_never_a_guess(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        one = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
        two = tasks.create_session(history, 'Tower core', select=False, workspace='tower')['taskId']
    third = declare(CODEX('c'), project, 'F337')['declaration']['work']
    assert third not in (one, two)
    assert len(work_rows()) == 3 and len(sessions()) == 3


def test_explicit_session_id_always_wins(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        villa = tasks.create_session(history, 'Villa roof', select=False, workspace='villa')['taskId']
    declare(CLAUDE('a'), project, 'tower-work')
    joined = declare(CODEX('b'), project, villa)['declaration']['work']
    assert joined == villa


def test_old_per_run_rows_and_files_are_never_joined_or_rewritten(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    old = tasks._declared_id('old-agent')
    with application_history() as history:
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,owner,created_by,created_at,updated_at,purpose,project) "
                     "VALUES(?,'Old run','open','old-agent','Old agent',?,?,'OLD','Tower')", (old, tasks._now(), tasks._now()))
        tasks.backfill_sessions(history)
        path = Path(tasks.get(history, old)['session_path'])
        before_row = tasks.get(history, old)
    before = path.read_bytes()
    work = declare(CLAUDE('a'), project, 'F337')['declaration']['work']
    declare(CODEX('b'), project, 'F337')
    assert work != old and path.read_bytes() == before
    with application_history() as history:
        assert tasks.get(history, old) == before_row


def test_ten_agent_starts_on_ten_requests_make_ten_sessions(project):
    for number in range(10):
        declare((CLAUDE, CODEX)[number % 2]('agent-%d' % number), project, 'request-%d' % number,
                path=project / ('part-%d.txt' % number))
    assert len(sessions()) == 10 and len(work_rows()) == 10


def test_ten_agent_starts_on_one_request_make_one_session_file(project, capsys):
    vendors = (CLAUDE, CODEX)
    timings = []
    for number in range(10):
        started = time.perf_counter()
        declare(vendors[number % 2]('agent-%d' % number), project, 'F337')
        timings.append(time.perf_counter() - started)
    files = sessions()
    with capsys.disabled():
        print('\nSESSIONWORK measured: session files after 10 agent starts = %d; join seconds first=%.3f '
              'median of joins=%.3f max=%.3f' % (len(files), timings[0], sorted(timings[1:])[4], max(timings[1:])))
    assert len(files) == 1 and len(work_rows()) == 1


def test_two_members_write_steps_at_once_and_none_is_lost(project):
    from concurrent.futures import ThreadPoolExecutor
    work = declare(CLAUDE('a'), project, 'F337', path=project / 'a.txt')['declaration']['work']
    # Separate paths: the overlap notice is not under test here, only the one file both write.
    with ThreadPoolExecutor(2) as pool:
        joined = list(pool.map(lambda pair: declare(pair[0], project, work, task=pair[1],
                                                    path=project / (pair[1] + '.txt'))['declaration']['work'],
                               [(CODEX('b'), 'Check the sheets'), (CLAUDE('c'), 'Tag the doors')]))
    assert joined == [work, work]
    row = next(row for row in work_rows() if row['id'] == work)
    assert len(row['members']) == 3 and len(steps(row['session_path'])) == 3


def test_agent_started_by_another_agent_inherits_only_the_same_work(project):
    import subprocess
    import sys
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        facade = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
        tasks.create_session(history, 'Tower core', select=False, workspace='tower')
    # The starter (Claude) works in the facade session; this test process is its connector.
    assert declare(CLAUDE('starter'), project, facade, path=project / 'facade.txt')['declaration']['work'] == facade
    # A sub-agent of another vendor runs as a child process of the starter's connector and passes no session.
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        peer = SimpleNamespace(pid=child.pid, created_at=psutil.Process(child.pid).create_time(), cwd=str(project))
        inherited = mailbox.call('declare', {'task': 'Check the facade panels', 'paths': [str(project / 'panels.txt')],
                                             'status': 'working', 'request_id': 'unassigned', 'kind': 'start'}, CODEX('sub'), peer=peer)
        other = mailbox.call('declare', {'task': 'Another request', 'paths': [str(project / 'other-request.txt')],
                                         'status': 'working', 'request_id': 'panel-check'}, CLAUDE('sub2'), peer=peer)
    finally:
        child.kill()
        child.wait(timeout=10)
    assert inherited['declaration']['work'] == facade                       # no request: the starter's work
    assert other['declaration']['work'] != facade                           # a different request is different work
    # A sibling with no starter above it never inherits: two open sessions means a new one.
    sibling = declare(CODEX('sibling'), project, 'other-work', path=project / 'other.txt')['declaration']['work']
    assert sibling != facade


def test_interrupted_session_stays_open_and_another_vendor_continues_with_plan_and_handover(project):
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox
    from nodelang.workshop_mailbox import application_history
    first = declare(CLAUDE('a'), project, 'F337', path=project / 'a.txt')
    work, me = first['declaration']['work'], CLAUDE('a')
    mailbox.call('task_set_session', {'id': work, 'plan': ['Check sheets', 'Tag doors', 'Publish set'],
                                      'handover': {'done': 'Sheets checked', 'next': 'Tag the doors',
                                                   'results': 'Tower/sheets-checked.pdf'}}, me)
    with application_history() as history:
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (work,))
        lapsed = tasks.get(history, work)
        path = lapsed['session_path']
    assert lapsed['status'] == 'open' and lapsed['outcome'] == 'interrupted' and not lapsed['archived']
    taken = declare(CODEX('b'), project, 'F337', path=project / 'b.txt')
    assert taken['declaration']['work'] == work                             # the same session, file and thread
    assert taken['session']['path'] == path
    assert taken['session']['plan'] == ['Check sheets', 'Tag doors', 'Publish set']
    assert taken['session']['handover'] == {'done': 'Sheets checked', 'next': 'Tag the doors',
                                            'results': 'Tower/sheets-checked.pdf'}
    assert len(sessions()) == 1
    shown = next(row for row in tasks_column() if row['id'] == work)
    assert shown['handover']['next'] == 'Tag the doors'
    assert shown['status'] == 'WIP' and not shown['stale']
    # Only done or archive ends it.
    declare(CODEX('b'), project, 'F337', status='done', path=project / 'b.txt')
    with application_history() as history:
        assert tasks.get(history, work)['status'] == 'done'
    assert declare(CLAUDE('c'), project, 'new-work', path=project / 'c.txt')['declaration']['work'] != work


def test_archive_ends_a_session(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    work = declare(CLAUDE('a'), project, 'F337', path=project / 'a.txt')['declaration']['work']
    with application_history() as history:
        tasks.archive(history, work)
    assert declare(CODEX('b'), project, 'F337', path=project / 'b.txt')['declaration']['work'] != work


def tasks_column():
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        return tasks.column(history)


def test_rendered_home_rows_are_pieces_of_work():
    import subprocess
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(['node', '--test', str(root / '02.TESTS/tests_js/studio_sessionwork.test.cjs')],
                            cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=180,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr


def test_two_starters_at_the_same_depth_mean_no_inheritance(project):
    import subprocess
    import sys
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        facade = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
        core = tasks.create_session(history, 'Tower core', select=False, workspace='tower')['taskId']
    # Two starters of different vendors share this test process as their connector: same depth above the child.
    declare(CLAUDE('one'), project, facade, path=project / 'facade.txt')
    declare(CODEX('two'), project, core, path=project / 'core.txt')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        peer = SimpleNamespace(pid=child.pid, created_at=psutil.Process(child.pid).create_time(), cwd=str(project))
        work = mailbox.call('declare', {'task': 'Which one?', 'paths': [str(project / 'which.txt')], 'status': 'working',
                                        'request_id': 'unassigned', 'kind': 'start'}, CODEX('child'), peer=peer)['declaration'].get('work')
    finally:
        child.kill()
        child.wait(timeout=10)
    assert work is None                                                      # no guess: no work at all


def test_dead_session_leaves_the_open_list_but_one_waiting_for_the_founder_stays(project):
    from datetime import datetime, timedelta, timezone
    from nodelang.workshop_mailbox import application_history
    dead = declare(CLAUDE('a'), project, 'DEAD', path=project / 'dead.txt')['declaration']['work']
    held = declare(CODEX('b'), project, 'HELD', status='blocked', path=project / 'held.txt')['declaration']['work']
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    with application_history() as history:
        history._db.execute("UPDATE workshop_tasks SET updated_at=?, lease_until=0 WHERE id IN (?,?)", (old, dead, held))
    shown = {row['id']: row for row in tasks_column()}
    assert shown[dead]['stale'] and shown[dead]['status'] == 'stale'       # Older; never deleted or archived
    assert not shown[held]['stale'] and shown[held]['status'] == 'IN REVIEW'
    assert declare(CLAUDE('c'), project, 'DEAD', path=project / 'dead2.txt')['declaration']['work'] == dead   # Continue


def test_handover_note_drops_user_paths_environment_values_and_secrets(project, monkeypatch):
    import os
    from nodelang import workshop_mailbox as mailbox
    monkeypatch.setenv('SESSIONWORK_FIXTURE_VALUE', 'fixture-environment-value-123')
    work = declare(CLAUDE('a'), project, 'F337', path=project / 'a.txt')['declaration']['work']
    private = os.path.join(os.environ['USERPROFILE'], 'Desktop', 'notes.txt')
    inside = str(project / 'sheets' / 'checked.pdf')
    token = 'ghp_' + 'A1b2C3d4E5f6G7h8I9j0K1l2'
    spaced = 'D:\\Office Share\\Tower Drawings\\set.pdf'
    unc = '\\\\server\\share\\Tower set\\a.dwg'
    long_path = 'Z:\\' + '\\'.join(['folder%03d' % n for n in range(90)]) + '\\end.txt'   # 1100+ chars before cleaning
    written = mailbox.call('task_set_session', {'id': work, 'handover': {
        'done': 'Checked ' + inside + ' and ' + private + ', ' + spaced + ' and ' + unc,
        'next': 'Use token=' + token + ' and fixture-environment-value-123',
        'results': 'In ' + inside + ' and ' + long_path}}, CLAUDE('a'))['session']
    note = written['handover']
    assert len('In ' + inside + ' and ' + long_path) > 1000                 # the limit applies after cleaning
    assert note['results'] == 'In sheets/checked.pdf and [path removed]'
    assert note['done'] == 'Checked sheets/checked.pdf and [path removed], [path removed] and [path removed]'
    assert token not in note['next'] and 'fixture-environment-value-123' not in note['next']
    again = mailbox.call('task_set_session', {'id': work, 'handover': {
        'results': 'Saw C:/Users/John Smith/x.txt and /c/Users/John Smith/y.txt and/or later'}}, CLAUDE('a'))['session']
    assert again['handover']['results'] == 'Saw [path removed] and [path removed] and/or later'
    assert 'Smith' not in str(again['handover'])
    folders = mailbox.call('task_set_session', {'id': work, 'handover': {
        'done': 'A C:/Users/John Smith, B C:/Users/John Smith/ and C',
        'next': 'D C:\\Users\\John Smith'}}, CLAUDE('a'))['session']['handover']
    assert folders == {'done': 'A [path removed], B [path removed]/ and C', 'next': 'D [path removed]'}
    sentences = mailbox.call('task_set_session', {'id': work, 'handover': {
        'done': 'C:/Users/John Smith/x.txt. Next',
        'next': 'C:\\x\\file.txt; then ran tests'}}, CLAUDE('a'))['session']['handover']
    assert sentences == {'done': '[path removed]. Next', 'next': '[path removed]; then ran tests'}
    assert os.environ['USERPROFILE'] not in str(note)


def test_upgrade_a_live_agents_old_row_is_one_working_row(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    me = CLAUDE('live')
    owner = declare(me, project, 'unassigned', path=project / 'live.txt')['declaration']['session']
    old = tasks._declared_id(owner)
    with application_history() as history:   # the row an older build gave this running agent, lease still live
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,owner,owner_label,lease_until,created_by,"
                     "created_at,updated_at,purpose,project) VALUES(?,'Old build work','claimed',?,'Live agent',?,"
                     "'Live agent',?,?,'OLD','Tower')", (old, owner, time.time() + 600, tasks._now(), tasks._now()))
        before = tasks.get(history, old)
    work = declare(me, project, 'F337', path=project / 'live.txt')['declaration']['work']
    with application_history() as history:
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (old,))   # its old lease lapses
        tasks.rows(history)
        kept = tasks.get(history, old)
    assert kept['status'] == 'claimed' and kept['outcome'] is None          # not marked interrupted while alive
    # members is a view the owner derives from the lease for a row from before members; the stored row is unchanged.
    derived = ('lease_until', 'lease_expired', 'members')
    assert {k: v for k, v in kept.items() if k not in derived} == {k: v for k, v in before.items() if k not in derived}
    with application_history() as history:
        assert history._db.execute("SELECT members FROM workshop_tasks WHERE id=?", (old,)).fetchone()[0] is None
    mine = [row for row in tasks_column() if row['id'] in (old, work)]
    assert [(row['id'], row['status']) for row in mine] == [(work, 'WIP')]


def test_two_processes_opening_an_old_database_together_both_succeed(tmp_path):
    import sqlite3
    import threading
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    database = tmp_path / 'old.sqlite3'
    with application_history(database=database) as history:                  # a real Workshop mailbox file
        history._db.execute("DROP TABLE IF EXISTS workshop_tasks")
        history._db.execute("CREATE TABLE workshop_tasks(id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL, owner TEXT, "
                    "owner_label TEXT, lease_until REAL, result TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, "
                            "updated_at TEXT NOT NULL) STRICT")                 # the task table as an older build left it
    gate, errors = threading.Barrier(2), []

    def open_it():
        try:
            with application_history(database=database, busy_timeout_seconds=2.0) as history:
                gate.wait()
                tasks.rows(history)                                         # the owner's own open path adds the columns
                with history._transaction(write=True):
                    tasks._add_column(history, 'members TEXT')              # a second add of the same column is tolerated
        except Exception as error:   # pragma: no cover - the assertion below reports it
            errors.append(error)
    runners = [threading.Thread(target=open_it) for _ in range(2)]
    [runner.start() for runner in runners]
    [runner.join() for runner in runners]
    assert errors == [], [repr(error) for error in errors]
    with sqlite3.connect(database) as done:
        assert 'members' in {row[1] for row in done.execute('PRAGMA table_info(workshop_tasks)')}


def test_real_starts_without_a_request_create_nothing_when_no_work_is_open(project):
    # Both vendors' start paths declare request id "unassigned"; no session exists yet: no row, no file.
    first = declare(CLAUDE('start'), project, 'unassigned', task='Session start', path=project / 'start-a.txt', kind='start')
    second = declare(CODEX('start'), project, 'unassigned', task='Session start', path=project / 'start-b.txt', kind='start')
    assert 'work' not in first['declaration'] and 'work' not in second['declaration']
    assert sessions() == [] and work_rows() == []


def test_real_starts_without_a_request_join_a_session_started_from_home(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        home = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
    assert declare(CLAUDE('home'), project, 'unassigned', path=project / 'h1.txt', kind='start')['declaration']['work'] == home
    assert declare(CODEX('home'), project, 'n/a', path=project / 'h2.txt', kind='start')['declaration']['work'] == home   # placeholder id


def test_same_request_in_an_unregistered_folder_never_joins(project, tmp_path):
    loose = tmp_path / 'Loose'
    loose.mkdir()
    first = declare(CLAUDE('loose'), loose, 'F337', path=loose / 'a.txt')['declaration']
    second = declare(CODEX('loose'), loose, 'F337', path=loose / 'b.txt')['declaration']
    assert first['project'] == '' and first['work'] != second['work']
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (first['work'],))
    rows, files = len(work_rows()), len(sessions())                        # the lease lapsed (settled on read)
    assert declare(CLAUDE('loose'), loose, 'F337', path=loose / 'a.txt')['declaration']['work'] == first['work']
    assert len(work_rows()) == rows and len(sessions()) == files


def test_stop_declare_keeps_the_current_work_and_never_returns_to_an_old_one(project):
    agent = CLAUDE('stop')
    old = declare(agent, project, 'B-WORK', path=project / 'b.txt')['declaration']['work']
    current = declare(agent, project, 'A-WORK', path=project / 'a.txt')['declaration']['work']
    assert current != old
    declare(CODEX('other'), project, 'B-WORK', path=project / 'b2.txt')          # touches the old session later
    stop = declare(agent, project, 'unassigned', task='Session start', path=project / 'a.txt')['declaration']
    assert stop['work'] == current


def test_child_with_its_own_request_stays_in_its_own_session_on_stop(project):
    import subprocess
    import sys
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        facade = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
    declare(CLAUDE('starter'), project, facade, path=project / 'facade.txt')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        peer = SimpleNamespace(pid=child.pid, created_at=psutil.Process(child.pid).create_time(), cwd=str(project))
        body = {'task': 'Panel check', 'paths': [str(project / 'panels.txt')], 'status': 'working', 'request_id': 'panel-check'}
        own = mailbox.call('declare', body, CODEX('child'), peer=peer)['declaration']['work']
        stop = mailbox.call('declare', {**body, 'task': 'Session start', 'request_id': 'unassigned'}, CODEX('child'), peer=peer)
    finally:
        child.kill()
        child.wait(timeout=10)
    assert own != facade and stop['declaration']['work'] == own


def test_parent_in_another_project_is_not_inherited(project, tmp_path):
    import subprocess
    import sys
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox
    from nodelang.workshop_mailbox import application_history
    villa_folder = tmp_path / 'Work' / 'Villa'
    with application_history() as history:
        villa = tasks.create_session(history, 'Villa roof', select=False, workspace='villa')['taskId']
        tower = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
    assert declare(CLAUDE('villa-starter'), villa_folder, villa, path=villa_folder / 'roof.txt')['declaration']['work'] == villa
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        peer = SimpleNamespace(pid=child.pid, created_at=psutil.Process(child.pid).create_time(), cwd=str(project))
        work = mailbox.call('declare', {'task': 'Session start', 'paths': [str(project / 'x.txt')], 'status': 'working',
                                        'request_id': 'unassigned', 'kind': 'start'}, CODEX('villa-child'), peer=peer)['declaration']['work']
    finally:
        child.kill()
        child.wait(timeout=10)
    assert work == tower                                                     # its own project's work, not the parent's


def test_startup_alias_pair_changes_nothing(project):
    from nodelang import workshop_tasks as tasks, workshop_mailbox as mailbox
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        home = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
    before = sessions()
    process = psutil.Process()
    peer = SimpleNamespace(pid=process.pid, created_at=process.create_time(), cwd=str(project))
    with application_history() as history:
        untouched = tasks.get(history, home)
    for status in ('working', 'done'):                                       # native_agent_mcp.py start alias
        mailbox.call('declare', {'task': 'Starting; task details pending', 'paths': [str(project)], 'status': status,
                                 'request_id': 'unassigned', 'kind': 'alias'}, {}, peer=peer)
    with application_history() as history:
        after = tasks.get(history, home)
    assert after['members'] == untouched['members'] == [] and after['status'] == untouched['status']
    assert sessions() == before and steps(before[0]) == []
    real = CLAUDE('real')
    assert declare(real, project, home, path=project / 'real.txt')['declaration']['work'] == home
    declare(real, project, home, status='done', path=project / 'real.txt')
    with application_history() as history:
        assert tasks.get(history, home)['status'] == 'done'                # no ghost member keeps it open


def test_request_from_another_project_never_stays_in_this_projects_session(project, tmp_path):
    villa_folder = tmp_path / 'Work' / 'Villa'
    agent = CLAUDE('mover')
    tower = declare(agent, project, 'F337', path=project / 'a.txt')['declaration']['work']
    villa = declare(agent, villa_folder, 'F337', path=villa_folder / 'a.txt')['declaration']['work']
    assert villa != tower


def test_no_request_starts_spray_no_files(project, tmp_path):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    loose = tmp_path / 'Loose'
    loose.mkdir()
    for number in range(10):
        declare((CLAUDE, CODEX)[number % 2]('loose-%d' % number), loose, 'unassigned', task='Session start',
                path=loose / ('l%d.txt' % number), kind='start')
    assert sessions() == [] and work_rows() == []
    with application_history() as history:
        tasks.create_session(history, 'Tower facade', select=False, workspace='tower')
        tasks.create_session(history, 'Tower core', select=False, workspace='tower')
    before = sessions()
    for number in range(10):
        declare((CLAUDE, CODEX)[number % 2]('reg-%d' % number), project, 'unassigned', task='Session start',
                path=project / ('r%d.txt' % number), kind='start')
    assert sessions() == before and len(work_rows()) == 2


def test_two_first_steps_at_once_share_the_one_file(project):
    import threading
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        tasks._write(history, "INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at,purpose,project) "
                     "VALUES('session-race','Race work','open','founder',?,?,'RACE','Tower')", (tasks._now(), tasks._now()))
    gate, results, errors = threading.Barrier(2), {}, []

    def start(name):
        try:
            with application_history(busy_timeout_seconds=2.0) as history:
                gate.wait()
                results[name] = tasks.declared(history, 'root-' + name, 'session-race', 'Step ' + name, 'working',
                                               name, name.title(), 'Tower')
        except Exception:   # reported by the assertion below
            import traceback
            errors.append(traceback.format_exc())
    runners = [threading.Thread(target=start, args=(name,)) for name in ('agent-a', 'agent-b')]
    [runner.start() for runner in runners]
    [runner.join() for runner in runners]
    assert errors == [] and results == {'agent-a': 'session-race', 'agent-b': 'session-race'}
    with application_history() as history:
        path = tasks.get(history, 'session-race')['session_path']
    assert sorted(step['params']['agent'] for step in steps(path)) == ['Agent-A', 'Agent-B']


def test_no_change_stop_declare_with_500_rows_is_fast(project, capsys):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history, history._transaction(write=True):
        tasks._ensure(history)
        for number in range(500):
            history._db.execute("INSERT INTO workshop_tasks(id,title,status,created_by,created_at,updated_at,purpose,project) "
                                "VALUES(?,?,'open','founder',?,?,?,?)", ('session-bulk-%d' % number, 'Bulk %d' % number,
                                tasks._now(), tasks._now(), 'BULK-%d' % number, ('Tower', 'Villa', None)[number % 3]))
    agent = CLAUDE('timed')
    work = declare(agent, project, 'F337', path=project / 'timed.txt')['declaration']['work']
    declare(agent, project, 'unassigned', task='Session start', path=project / 'timed.txt')
    started = time.perf_counter()
    stop = declare(agent, project, 'unassigned', task='Session start', path=project / 'timed.txt')['declaration']
    seconds = time.perf_counter() - started
    with capsys.disabled():
        print('\nSESSIONWORK measured: no-change Stop declare with 500 task rows = %.3f s' % seconds)
    assert stop['work'] == work and seconds < 0.5
    held = steps(next(row for row in work_rows() if row['id'] == work)['session_path'])
    assert [step['title'] for step in held] == ['Coordinate the tower drawings']   # a Stop never renames the step


def test_stop_after_a_lapsed_lease_renews_its_own_work_and_joins_nothing_else(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        home = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
    agent = CLAUDE('lapsed')
    work = declare(agent, project, 'F337', path=project / 'f.txt')['declaration']['work']
    with application_history() as history:
        history._db.execute("UPDATE workshop_tasks SET lease_until=0 WHERE id=?", (work,))
        tasks.rows(history)                                                  # the lease lapses: interrupted
    stop = declare(agent, project, 'unassigned', task='Session start', path=project / 'f.txt')['declaration']
    assert stop['work'] == work
    with application_history() as history:
        assert tasks.get(history, home)['members'] == []                    # no ghost in any other session
        assert tasks.get(history, work)['status'] == 'claimed'


def test_refresh_with_no_work_and_no_request_joins_nothing(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        home = tasks.create_session(history, 'Tower facade', select=False, workspace='tower')['taskId']
    for context in (CLAUDE('refresh'), CODEX('refresh')):
        assert 'work' not in declare(context, project, 'unassigned', task='Session start', path=project / 's.txt')['declaration']
    with application_history() as history:
        assert tasks.get(history, home)['members'] == []


def test_each_real_caller_states_its_declare_kind(project, monkeypatch, capsys):
    """The body each caller sends: Stop = refresh, session-start = start, connector alias = alias, repeat = refresh."""
    import io
    import json
    import sys
    import threading
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session
    from nodelang import workshop_mailbox, baboom_reactions, native_stop_hook, native_agent_mcp as native
    sent = []
    monkeypatch.setattr(workshop_mailbox, 'call', lambda method, body, context, **kwargs: sent.append(body) or {})
    monkeypatch.setattr(baboom_reactions, 'emit', lambda *args, **kwargs: None)
    payload = {'session_id': 'kind-session', 'cwd': str(project)}
    native_stop_hook.query_stop(payload, vendor='claude-code')
    assert [body['kind'] for body in sent] == ['refresh']                    # native_stop_hook.query_stop
    sent.clear()
    monkeypatch.setattr(sys, 'argv', ['native_stop_hook', '--session-start', '--vendor', 'claude-code'])
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode())))
    native_stop_hook.main()
    capsys.readouterr()
    assert [body['kind'] for body in sent] == ['start']                      # --session-start
    # The connector: startup alias (done and working) and the repeat of a real declaration.
    bodies, hold, released = [], threading.Event(), threading.Event()

    def mailbox(method, body, context, **kwargs):
        if method == 'pending':
            return {'pending': [], 'more': False}
        if method == 'read':
            return {'messages': [], 'declarations': [], 'sender_key': 'kind-connector', 'next_since': 0}
        if method == 'declare':
            bodies.append(dict(body))
            if body.get('kind') == 'alias' and body['status'] == 'working' and not hold.is_set():
                hold.set()
                released.wait(10)                                            # a real declare lands meanwhile
        return {'ok': True}
    monkeypatch.setattr(native, '_default_context', lambda: {})
    monkeypatch.setattr(native, '_caller_context', lambda ctx: {'threadId': 'kind-connector'})
    server = native.build_server(mailbox_call=mailbox)
    real = {'task': 'Real work', 'paths': [str(project)], 'status': 'working', 'request_id': 'F337'}

    async def run():
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            await session.call_tool('read', {'since': 0})
            for _ in range(200):
                if hold.is_set():
                    break
                await anyio.sleep(0.02)
            await session.call_tool('declare', real)
            released.set()
            for _ in range(200):
                if any(body.get('kind') == 'refresh' for body in bodies):
                    break
                await anyio.sleep(0.02)
    try:
        anyio.run(run)
    finally:
        released.set()
        server._mailbox_stop()
    kinds = [(body['status'], body.get('kind')) for body in bodies]
    assert ('done', 'alias') in kinds and ('working', 'alias') in kinds     # retire_bootstrap and the startup alias
    assert any(body.get('kind') == 'refresh' and body['request_id'] == 'F337' for body in bodies)   # the repeat
