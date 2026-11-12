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


def declare(context, folder, request, status='working', task='Coordinate the tower drawings', path=None):
    from nodelang import workshop_mailbox as mailbox
    process = psutil.Process()
    peer = SimpleNamespace(pid=process.pid, created_at=process.create_time(), cwd=str(folder))
    return mailbox.call('declare', {'task': task, 'paths': [str(path or folder)], 'status': status,
                                    'request_id': request}, context, peer=peer)


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


def test_two_vendors_in_one_project_join_one_session(project):
    first = declare(CLAUDE('a'), project, 'F337')['declaration']
    second = declare(CODEX('b'), project, 'review-drawings', task='Review the tower sheets')['declaration']
    rows = work_rows()
    assert len(rows) == 1 and first['work'] == second['work'] == rows[0]['id']
    assert len(sessions()) == 1
    assert sorted(m['owner'] for m in rows[0]['members']) == sorted([first['session'], second['session']])
    agents = sorted(step['params']['agent'] for step in steps(rows[0]['session_path']))
    assert len(agents) == 2 and agents[0] != agents[1]
    assert first['runtime'] != second['runtime']


def test_new_purpose_stays_in_the_same_session(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    first = declare(CLAUDE('a'), project, 'REQ-1')['declaration']['work']
    again = declare(CLAUDE('a'), project, 'REQ-2', task='Next step')['declaration']['work']
    assert again == first
    with application_history() as history:
        assert [row['status'] for row in tasks.rows(history)] == ['claimed']
    assert len(sessions()) == 1


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


def test_ten_agent_starts_in_one_project_make_one_session_file(project, capsys):
    vendors = (CLAUDE, CODEX)
    timings = []
    for number in range(10):
        started = time.perf_counter()
        declare(vendors[number % 2]('agent-%d' % number), project, 'start-%d' % number)
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


def test_agent_started_by_another_agent_inherits_its_session(project):
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
                                             'status': 'working', 'request_id': 'panel-check'}, CODEX('sub'), peer=peer)
    finally:
        child.kill()
        child.wait(timeout=10)
    assert inherited['declaration']['work'] == facade
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
    taken = declare(CODEX('b'), project, 'continue', path=project / 'b.txt')
    assert taken['declaration']['work'] == work                             # the same session, file and thread
    assert taken['session']['path'] == path
    assert taken['session']['plan'] == ['Check sheets', 'Tag doors', 'Publish set']
    assert taken['session']['handover'] == {'done': 'Sheets checked', 'next': 'Tag the doors',
                                            'results': 'Tower/sheets-checked.pdf'}
    assert len(sessions()) == 1
    shown = next(row for row in tasks_column() if row['id'] == work)
    assert shown['handover']['next'] == 'Tag the doors'
    # Only done or archive ends it.
    declare(CODEX('b'), project, 'continue', status='done', path=project / 'b.txt')
    with application_history() as history:
        assert tasks.get(history, work)['status'] == 'done'
    assert declare(CLAUDE('c'), project, 'new-work', path=project / 'c.txt')['declaration']['work'] != work


def test_archive_ends_a_session(project):
    from nodelang import workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history
    work = declare(CLAUDE('a'), project, 'F337', path=project / 'a.txt')['declaration']['work']
    with application_history() as history:
        tasks.archive(history, work)
    assert declare(CODEX('b'), project, 'next', path=project / 'b.txt')['declaration']['work'] != work


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
