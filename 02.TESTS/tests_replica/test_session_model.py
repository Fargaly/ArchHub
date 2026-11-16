"""ONE BUILD workstream 1: one .archhub session holds everything about one piece of work.

Founder 2026-11-16: "كل حاجة بتصب في بعضها" (everything feeds into everything). Fields: project, state + pinned,
done check, trigger armed + ask before running, run history beside the file, settings scope, input links (D-038),
context. Real session files, task table and trigger service in a disposable profile only.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def profile(tmp_path, monkeypatch):
    for name in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKSHOP_STATE_DIR', str(tmp_path / 'transport'))
    tower = tmp_path / 'Work' / 'Tower'
    tower.mkdir(parents=True)
    from nodelang.nograph_server import JsonFile
    from nodelang.user_paths import state_directory
    JsonFile(state_directory() / 'settings/workspaces.json', {}).update(
        {'roots': [{'root_id': 'tower', 'label': 'Tower', 'path': str(tower)}]})
    return tower


def session(title='Work', nodes=(), wires=(), properties=None):
    from nodelang.session_files import new_document, sessions_directory, write_document, document_path
    doc = new_document(title)
    doc['nodes'], doc['wires'] = list(nodes), list(wires)
    if properties:
        doc['properties'].update(properties)
    path = document_path(sessions_directory(), doc)
    write_document(path, doc)
    return str(path), doc


def convert(node_id, x=0):
    return {'id': node_id, 'item': 'data.convert', 'type': 'data.convert', 'title': 'Convert',
            'params': {'target_type': 'text'}, 'position': {'x': x, 'y': 0}}


def model(path):
    from nodelang.session_files import read_document, session_fields
    return session_fields(read_document(path), path)


def test_old_file_reads_defaults_and_opening_never_writes(profile):
    path, _ = session('Old work')
    before = Path(path).read_bytes()
    fields = model(path)
    assert fields['project'] == {'id': '', 'label': ''}
    assert fields['state'] == 'open' and fields['pinned'] is False and fields['onHome'] is True
    assert fields['doneCheck'] is None and fields['automation'] == [] and fields['settings'] == {}
    assert fields['inputLinks'] == [] and fields['context'] == {'plan': [], 'handover': {}}
    assert Path(path).read_bytes() == before


def test_project_comes_from_registered_workspaces_and_home_groups_by_it(profile):
    from nodelang.session_files import list_sessions, set_session_fields
    path, _ = session('Tower drawings')
    session('Loose idea')
    set_session_fields(path, {'project': 'tower'})
    assert model(path)['project'] == {'id': 'tower', 'label': 'Tower'}
    with pytest.raises(ValueError, match='registered'):
        set_session_fields(path, {'project': 'nowhere'})
    groups = {group['project']['label']: [row['title'] for row in group['sessions']] for group in list_sessions()['groups']}
    assert groups == {'Tower': ['Tower drawings'], '': ['Loose idea']}


def test_state_and_pinned_decide_home(profile):
    from nodelang.session_files import set_session_fields
    path, _ = session('Finish me')
    set_session_fields(path, {'state': 'done'})
    assert model(path)['onHome'] is False
    set_session_fields(path, {'pinned': True})
    assert model(path)['onHome'] is True
    with pytest.raises(ValueError):
        set_session_fields(path, {'state': 'finished'})


def tasks():
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    return workshop_tasks, application_history


def test_task_archive_and_pin_land_in_the_one_file_field(profile):
    workshop_tasks, application_history = tasks()
    with application_history() as history:
        view = workshop_tasks.create_session(history, 'Pinned work', select=False)
        task = view['taskId']
        workshop_tasks.update_session(history, task, {'homePinned': True})
        assert model(view['path'])['pinned'] is True
        assert 'homePinned' not in json.loads(Path(view['path']).read_text(encoding='utf-8'))['properties']['taskContext']
        workshop_tasks.archive(history, task)
    assert model(view['path'])['state'] == 'archived'


def test_done_check_fails_three_times_then_blocks_and_a_pass_finishes(profile):
    workshop_tasks, application_history = tasks()
    from nodelang.session_files import read_document, set_session_fields
    with application_history() as history:
        view = workshop_tasks.create_session(history, 'Checked work', select=False, workspace='tower')
        task, path = view['taskId'], view['path']
        set_session_fields(path, {'doneCheck': {'command': 'exit 1'}})
        for attempt in (1, 2, 3):
            workshop_tasks.claim(history, task, 'agent-a', 'Agent A')
            with pytest.raises(workshop_tasks.TaskCheckFailed):
                workshop_tasks.complete(history, task, 'agent-a', 'finished')
            check = model(path)['doneCheck']
            assert check['tries'] == attempt
        assert check['blocked'] is True
        step = next(n for n in read_document(path)['nodes'] if n['id'] == 'done-check')
        assert step['result']['status'] == 'Error'
        assert workshop_tasks.get(history, task)['status'] != 'done'
        set_session_fields(path, {'doneCheck': {'command': 'exit 0'}})
        workshop_tasks.claim(history, task, 'agent-a', 'Agent A')
        assert workshop_tasks.complete(history, task, 'agent-a', 'finished')
        assert workshop_tasks.get(history, task)['status'] == 'done'
    assert model(path)['state'] == 'done' and model(path)['doneCheck']['tries'] == 0


def test_no_done_check_keeps_todays_completion(profile):
    workshop_tasks, application_history = tasks()
    with application_history() as history:
        view = workshop_tasks.create_session(history, 'Plain work', select=False)
        workshop_tasks.claim(history, view['taskId'], 'agent-a', 'Agent A')
        assert workshop_tasks.complete(history, view['taskId'], 'agent-a', 'ok')
    assert model(view['path'])['state'] == 'done'


def trigger_session(params=None):
    from nodelang.session_files import SessionFiles, catalogue
    item = next(row for row in catalogue() if row['id'] == 'tr_schedule')
    trigger = {'id': 't', 'item': 'tr_schedule', 'type': item['engine'], 'title': 'Daily',
               'params': {**copy.deepcopy(item['params']), 'every_seconds': '600', **(params or {})},
               'position': {'x': -300, 'y': 0}}
    path, doc = session('Automated', [trigger, convert('c')],
                        [{'id': 'w', 'from': {'node': 't', 'socket': 'payload'}, 'to': {'node': 'c', 'socket': 'in'}}])
    SessionFiles().remember(path, doc)
    return path


def test_trigger_defaults_to_ask_before_running_and_waits(profile):
    from nodelang.canvas_triggers import TriggerService
    from nodelang.session_files import read_document, read_runs
    path = trigger_session()
    assert model(path)['automation'] == [{'node': 't', 'kind': 'trigger.schedule', 'title': 'Daily',
                                          'armed': True, 'askBeforeRunning': True}]
    service = TriggerService()
    try:
        service.refresh()
        service.dispatch((path, 't'), 'trigger.schedule', {})
        assert 'result' not in next(n for n in read_document(path)['nodes'] if n['id'] == 'c')
        waiting = read_runs(path)[-1]
        assert waiting['state'] == 'asking' and waiting['trigger'] == 't'
        service.approve(path, waiting['id'])
        assert next(n for n in read_document(path)['nodes'] if n['id'] == 'c')['result']['status'] == 'Done'
    finally:
        service.close()
    runs = read_runs(path)                       # a new reader after "restart" sees the same history
    assert [run['state'] for run in runs] == ['approved', 'succeeded']
    assert runs[-1]['end'] >= runs[-1]['start']


def test_unarmed_trigger_is_not_timed_and_the_list_says_so(profile):
    from nodelang.canvas_triggers import TriggerService
    from nodelang.session_files import set_session_fields
    path = trigger_session({'ask_before_running': False})
    set_session_fields(path, {'automation': [{'node': 't', 'armed': False}]})
    service = TriggerService()
    try:
        assert service.refresh() == []
        assert not service.timers
    finally:
        service.close()
    assert model(path)['automation'][0]['armed'] is False


def test_run_history_is_append_only_beside_the_file_and_records_the_failed_node(profile):
    from nodelang.session_files import SessionFiles, read_runs, runs_path
    bad = {'id': 'bad', 'type': 'thing.setting', 'title': 'Gone row', 'params': {'setting': 'No such row'},
           'position': {'x': 0, 'y': 0}}
    path, doc = session('Runs', [bad])
    SessionFiles().dispatch({'action': 'run', 'document': doc, 'path': path})
    assert runs_path(path).parent == Path(path).parent
    runs = read_runs(path)
    assert runs[-1]['state'] == 'failed' and runs[-1]['failedNode'] == 'bad' and runs[-1]['trigger'] == 'manual'
    lines = runs_path(path).read_text(encoding='utf-8').splitlines()
    SessionFiles().dispatch({'action': 'run', 'document': doc, 'path': path})
    assert runs_path(path).read_text(encoding='utf-8').splitlines()[:len(lines)] == lines


def test_session_settings_sit_above_global_and_copy_nothing(profile):
    from nodelang.session_files import read_document, resolve_setting, set_session_fields
    path, _ = session('Zoomed')
    assert resolve_setting(read_document(path), 'Appearance.Default zoom') == {'value': 100, 'scope': 'global'}
    set_session_fields(path, {'settings': {'Appearance.Default zoom': 150}})
    assert resolve_setting(read_document(path), 'Appearance.Default zoom') == {'value': 150, 'scope': 'session'}
    assert model(path)['settings'] == {'Appearance.Default zoom': 150}
    with pytest.raises(ValueError):
        set_session_fields(path, {'settings': {'Appearance.Default zoom': 'big'}})
    with pytest.raises(ValueError):
        set_session_fields(path, {'settings': {'No such row': 1}})
    set_session_fields(path, {'settings': {'Appearance.Default zoom': None}})
    assert resolve_setting(read_document(path), 'Appearance.Default zoom')['scope'] == 'global'


def test_input_links_store_a_reference_and_read_state_live(profile):
    from nodelang.session_files import link_states, read_document, set_session_fields, write_document
    source_path, source = session('Source', [convert('out')])
    target_path, _ = session('Target')
    set_session_fields(source_path, {'project': 'tower'})
    set_session_fields(target_path, {'project': 'tower'})
    link = {'source': {'path': 'Source.archhub', 'id': source['id']}, 'output': 'out', 'input': 'brief', 'rule': ''}
    set_session_fields(target_path, {'inputLinks': [link]})
    stored = read_document(target_path)['properties']['inputLinks']
    assert stored == [link]                       # a reference only, no value or hash
    assert link_states(read_document(target_path), target_path)[0]['state'] == 'waiting'
    held = read_document(source_path)
    held['nodes'][0]['result'] = {'status': 'Done', 'output': {'out': 'x'}}
    write_document(source_path, held)
    assert link_states(read_document(target_path), target_path)[0]['state'] == 'ready'
    Path(source_path).unlink()
    assert link_states(read_document(target_path), target_path)[0]['state'] == 'source missing'
    with pytest.raises(ValueError):
        set_session_fields(target_path, {'inputLinks': [{**link, 'source': {'path': 'C:/abs/Source.archhub', 'id': 'x'}}]})
    with pytest.raises(ValueError):
        set_session_fields(target_path, {'inputLinks': [{**link, 'value': 'copied'}]})


def test_input_link_cycle_is_refused(profile):
    from nodelang.session_files import set_session_fields
    a_path, a = session('A')
    b_path, b = session('B')
    set_session_fields(a_path, {'inputLinks': [{'source': {'path': 'B.archhub', 'id': b['id']}, 'output': 'x', 'input': 'y'}]})
    with pytest.raises(ValueError, match='[Cc]ycle'):
        set_session_fields(b_path, {'inputLinks': [{'source': {'path': 'A.archhub', 'id': a['id']}, 'output': 'x', 'input': 'y'}]})


def test_context_and_members_live_with_the_session(profile):
    workshop_tasks, application_history = tasks()
    from nodelang.session_files import list_sessions
    with application_history() as history:
        view = workshop_tasks.create_session(history, 'Handed over', select=False)
        workshop_tasks.claim(history, view['taskId'], 'agent-a', 'Agent A')
        workshop_tasks.update_session(history, view['taskId'], {'plan': ['Draw', 'Check'],
                                                               'handover': {'done': 'Drew', 'next': 'Check'}})
    fields = model(view['path'])
    assert fields['context'] == {'plan': ['Draw', 'Check'], 'handover': {'done': 'Drew', 'next': 'Check'}}
    row = next(r for g in list_sessions()['groups'] for r in g['sessions'] if r['path'] == view['path'])
    assert row['members'] == [{'name': 'Agent A', 'live': True}] and row['task'] == view['taskId']


def test_route_reads_and_sets_every_field(profile):
    from nodelang import nograph_server
    path, _ = session('Routed')
    call = lambda body: nograph_server.r_session_model(SimpleNamespace(triggers=None, is_halted=lambda: False),
                                                       SimpleNamespace(body=body, method='POST'))
    assert call({'action': 'set', 'path': path, 'values': {'pinned': True, 'project': 'tower'}})['session']['pinned'] is True
    assert call({'action': 'get', 'path': path})['session']['project']['label'] == 'Tower'
    assert any(r['path'] == path for g in call({'action': 'list'})['groups'] for r in g['sessions'])
    assert call({'action': 'runs', 'path': path})['runs'] == []
    assert call({'action': 'links', 'path': path})['links'] == []
    assert call({'action': 'setting', 'path': path, 'id': 'Appearance.Theme'})['scope'] == 'global'
