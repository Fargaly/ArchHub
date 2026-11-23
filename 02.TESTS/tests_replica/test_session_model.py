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


def test_home_keeps_project_and_members_after_an_archived_null_lease(profile):
    from nodelang.session_files import list_sessions, read_document, write_document
    workshop, history_store = tasks()
    with history_store() as history:
        tower = workshop.create_session(history, 'Tower work', select=False, workspace='tower')
        east = workshop.create_session(history, 'East work', select=False)
        west = workshop.create_session(history, 'West work', select=False)
        workshop.claim(history, tower['taskId'], 'architect', 'Architect')
        workshop.archive(history, west['taskId'])
        history._db.executemany('UPDATE workshop_tasks SET project=? WHERE id=?',
                                [('East wing', east['taskId']), ('West wing', west['taskId'])])
        history._db.execute("UPDATE workshop_tasks SET status='claimed', lease_until=NULL, members=? WHERE id=?",
                            (json.dumps([{'owner': 'former', 'lease_until': 'invalid'}]), west['taskId']))
        row = workshop.rows(history, west['taskId'], settle=False)[0]
        assert row['lease_expired'] and not workshop._holds(row, 'former')
    document = read_document(east['path'])
    document['properties']['taskContext'].update(task={}, project=['malformed'])
    write_document(east['path'], document)
    originals = {Path(v['path']): Path(v['path']).read_bytes() for v in (tower, east, west)}
    groups = {g['project']['label']: g for g in list_sessions()['groups']}
    assert set(groups) == {'Tower', 'East wing', 'West wing'}
    assert groups['Tower']['project']['id'] == 'tower'
    assert groups['East wing']['project']['id'] == groups['West wing']['project']['id'] == ''
    assert groups['East wing']['sessions'][0]['task'] == east['taskId']
    assert groups['Tower']['sessions'][0]['members'] == [{'name': 'Architect', 'live': True}]
    assert groups['West wing']['sessions'][0]['members'] == [{'name': 'former', 'live': False}]
    assert all(path.read_bytes() == contents for path, contents in originals.items())


def test_home_resumes_only_a_recent_listed_nonarchived_task(profile):
    from nodelang.session_files import SessionFiles, list_sessions
    workshop, history_store = tasks()
    with history_store() as history:
        first = workshop.create_session(history, 'Current task', select=False)
        second = workshop.create_session(history, 'Earlier task', select=False)
        archived = workshop.create_session(history, 'Archived task', select=False)
        workshop.archive(history, archived['taskId'])
    loose, _ = session('Canvas only')
    files = SessionFiles()
    metadata = files.metadata / 'recent.json'
    metadata.unlink(missing_ok=True)
    assert list_sessions()['recentTask'] is None
    records = [None, {'path': []}, {'path': str(profile / 'absent.archhub')},
               {'path': archived['path']}, {'path': loose}, {'path': Path(first['path']).as_posix()},
               {'path': second['path']}]
    metadata.write_text(json.dumps(records), encoding='utf-8')
    assert list_sessions()['recentTask'] == first['taskId']
    for contents in (json.dumps(records[:5]), 'invalid json'):
        metadata.write_text(contents, encoding='utf-8')
        result = list_sessions()
        assert result['recentTask'] is None and result['count'] == 4
        assert metadata.read_text(encoding='utf-8') == contents


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
        from nodelang.session_files import write_document
        document = read_document(path)
        document['nodes'].append({'id': 'ok', 'item': 'n_text', 'type': 'data.constant', 'title': 'Text',
                                  'params': {'value': 'ok'}, 'position': {'x': 900, 'y': 0}})
        write_document(path, document)
        set_session_fields(path, {'doneCheck': {'node': 'ok'}})
        workshop_tasks.claim(history, task, 'agent-a', 'Agent A')
        assert workshop_tasks.complete(history, task, 'agent-a', 'finished')
        assert workshop_tasks.get(history, task)['status'] == 'done'
    assert model(path)['state'] == 'done' and model(path)['doneCheck']['tries'] == 0


def test_done_check_command_from_a_session_file_never_runs(profile):
    """A shared .archhub file can carry any command: completing a task must not execute it."""
    import sys
    workshop_tasks, application_history = tasks()
    from nodelang.session_files import set_session_fields
    marker = profile / 'ran.txt'
    with application_history() as history:
        view = workshop_tasks.create_session(history, 'Shared work', select=False, workspace='tower')
        task, path = view['taskId'], view['path']
        set_session_fields(path, {'doneCheck': {
            'command': '"%s" -c "open(r\'%s\', \'w\').close()"' % (sys.executable, marker)}})
        workshop_tasks.claim(history, task, 'agent-a', 'Agent A')
        with pytest.raises(workshop_tasks.TaskCheckFailed):
            workshop_tasks.complete(history, task, 'agent-a', 'finished')
        assert not marker.exists()
        check = model(path)['doneCheck']
        assert check['tries'] == 1 and 'cannot run without approval' in check['lastError']
        assert workshop_tasks.get(history, task)['status'] != 'done'


@pytest.mark.parametrize('upstream', [False, True])
def test_done_check_cannot_run_a_host_node(profile, upstream):
    from nodelang.hook_decision import ask_reviews
    from nodelang.session_files import read_document, set_session_fields, write_document
    workshop_tasks, application_history = tasks()
    marker = profile / 'host-ran.txt'
    code = 'from pathlib import Path\nPath(%r).write_text("ran")\nresult = True' % str(marker)
    with application_history() as history:
        view = workshop_tasks.create_session(history, 'Shared work', select=False, workspace='tower')
        path, task = view['path'], view['taskId']
        document = read_document(path)
        document['nodes'].append({'id': 'host', 'item': 'host_exec', 'type': 'host.exec', 'title': 'Host',
                                  'params': {'host': 'python', 'code': code}, 'position': {'x': 300, 'y': 0}})
        if upstream:
            document['nodes'].append(convert('check', x=650))
            document['wires'].append({'id': 'w', 'from': {'node': 'host', 'socket': 'result'},
                                      'to': {'node': 'check', 'socket': 'in'}})
        write_document(path, document)
        set_session_fields(path, {'doneCheck': {'node': 'check' if upstream else 'host'}})
        workshop_tasks.claim(history, task, 'agent-a', 'Agent A')
        with pytest.raises(workshop_tasks.TaskCheckFailed):
            workshop_tasks.complete(history, task, 'agent-a', 'finished')
        assert not marker.exists()
        assert not ask_reviews()
        assert model(path)['doneCheck']['tries'] == 1
        assert workshop_tasks.get(history, task)['status'] != 'done'


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


def test_direct_trigger_fire_asks_before_running_the_engine(profile, monkeypatch):
    from nodelang import session_files
    from nodelang.canvas_triggers import TriggerService
    path = trigger_session()
    attempted = []
    original = session_files.run_document
    def tracked(*args, **kwargs):
        attempted.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(session_files, 'run_document', tracked)
    service = TriggerService()
    monkeypatch.setattr(service, '_post', lambda *_args: {})
    try:
        service.fire((path, 't'), 'trigger.schedule')
        assert not attempted
        assert session_files.read_runs(path)[-1]['state'] == 'asking'
        assert 'canvasRun' not in session_files.read_document(path)['properties']
    finally:
        service.close()


def test_schedule_actions_persist_and_paused_schedule_can_resume(profile, monkeypatch):
    from nodelang import nograph_server
    from nodelang.canvas_triggers import TriggerService
    from nodelang.session_files import SessionFiles, read_document

    path, document = session('Repeat work', nodes=[convert('target')])
    files = SessionFiles()
    files.remember(path, document)
    files._current(document['id'], path)
    service = TriggerService(files)
    server = SimpleNamespace(triggers=service, is_halted=lambda: False)
    monkeypatch.setattr(nograph_server, '_SERVER', server)

    def action(op, *args):
        return nograph_server.r_canvas_op(server, SimpleNamespace(body={'op': op, 'args': list(args)}))['result']

    try:
        before = Path(path).read_bytes()
        with pytest.raises(ValueError, match='HH:MM'):
            action('add_schedule', 'target', '25:00', path)
        assert Path(path).read_bytes() == before
        made = action('add_schedule', 'target', '23:59', path)
        saved = read_document(path)
        trigger = next(node for node in saved['nodes'] if node['type'] == 'trigger.schedule')
        key = (path, trigger['id'])
        assert trigger['params']['ask_before_running'] is True
        assert saved['wires'][0]['to']['node'] == 'target'
        assert key in service.timers
        timer = service.timers[key]

        action('set_schedule_time', made['id'], '22:59')
        assert service.timers[key] is not timer
        action('set_schedule_enabled', made['id'], False)
        assert key not in service.timers
        assert read_document(path)['nodes'][-1]['params']['armed'] is False
        assert [(row['id'], row['time'], row['enabled']) for row in action('project_schedules')] == [
            (made['id'], '22:59', False),
        ]
        action('set_schedule_enabled', made['id'], True)
        assert key in service.timers and action('project_schedules')[0]['enabled']
        action('remove_schedule', made['id'])
        assert key not in service.timers
        assert action('project_schedules') == []
        saved = read_document(path)
        assert [node['id'] for node in saved['nodes']] == ['target']
        assert saved['wires'] == []
    finally:
        service.close()


def test_registration_history_uses_authored_content_and_keeps_source_files(profile):
    from nodelang.session_files import read_document, session_fields, write_document
    step = 'step-' + 'a'*24
    def node(identity, kind, params, **extra):
        return {'id':identity,'type':kind,'params':params,'title':identity,'position':{'x':0,'y':0},**extra}
    nodes = [node('start','param.value',{'type':'text','value':'Legacy'}),
             node(step,'thing.agent',{'workshop_step':True},agentWork={'role':'session'})]
    nodes.extend(node('note'+str(i),'note',{},agentWork={'role':'step','kind':'tool','tool':'wait' if i<13 else 'sleep',
                                                       'runnable':False}) for i in range(16))
    path, original = session('Legacy',nodes,[{'id':'wire-'+step,'from':{'node':'start','socket':'value'},
        'to':{'node':step,'socket':'task'}}],{'taskContext':{'task':'declared-case'}})
    def projection(doc):
        write_document(path,doc)
        before = Path(path).read_bytes()
        fields = session_fields(read_document(path),path)
        assert fields['path'] == path and Path(path).read_bytes() == before
        return fields['authoredRegistration']
    assert not projection(original)
    edited = copy.deepcopy(original)
    edited['wires'][0]['id'] = 'user-wire'
    assert projection(edited)
    edited = copy.deepcopy(original)
    edited['nodes'].append(node('annotation','note',{'text':'Clear width'}))
    assert projection(edited)
    edited = copy.deepcopy(original)
    edited['nodes'] = [node('v0','param.value',{'type':'number','value':1}),
                       node('v1','param.value',{'type':'number','value':900})]
    edited['wires'] = [{'id':'width','from':{'node':'v0','socket':'value'},'to':{'node':'v1','socket':'param:value'}}]
    assert projection(edited)
    edited = copy.deepcopy(original)
    edited['notes'] = [{'text':'Clear width at entrance'}]
    assert projection(edited)
