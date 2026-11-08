"""ONETASK: linked files, isolated task work and reversible session partitioning."""
import inspect
from pathlib import Path

import pytest
import test_agentcanvas


@pytest.fixture
def history(tmp_path, monkeypatch):
    yield from inspect.unwrap(test_agentcanvas.history)(tmp_path, monkeypatch)


def test_new_purpose_keeps_old_file_and_gets_its_own(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import read_document
    tasks.declared(history, 'root', 'FIRST', 'First task', 'working', 'agent', 'Agent')
    first = tasks.get(history, tasks._declared_id('agent'))
    before = read_document(first['session_path'])
    tasks.declared(history, 'root', 'SECOND', 'Second task', 'working', 'agent', 'Agent')
    current = tasks.get(history, tasks._declared_id('agent'))
    assert current['session_path'] != first['session_path']
    assert read_document(first['session_path'])['nodes'] == before['nodes']
    assert all(n.get('title') != 'First task' for n in read_document(current['session_path'])['nodes'])


def test_insert_references_file_and_refuses_cycles(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import SessionFiles, new_document, read_document, write_document
    task = tasks.create(history, 'Session alone', 'founder')
    files = SessionFiles()
    parent = new_document('Parent')
    placed = files.dispatch({'action': 'insert-session', 'document': parent, 'session': task['session_path']})
    group = placed['document']['nodes'][0]
    assert len(placed['document']['nodes']) == 1
    assert group['type'] == 'skill' and group['children'] == []
    assert group['params']['session_file'] == task['session_path']
    assert group['ports']['target'][0]['id'] == 'in:start'
    parent_path = files.directory / 'parent.archhub'
    write_document(parent_path, placed['document'])
    with pytest.raises(ValueError, match='[Cc]ycle'):
        files.dispatch({'action': 'insert-session', 'document': read_document(task['session_path']), 'session': str(parent_path)})


def test_automation_changes_only_selected_task(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import SessionFiles, read_document
    a, b = [tasks.create(history, name, 'founder') for name in ('First', 'Second')]
    before = Path(b['session_path']).read_bytes()
    result = SessionFiles().dispatch({'action': 'add-automation', 'path': a['session_path'], 'trigger': 'manual'})
    document = read_document(a['session_path'])
    assert result['ok'] and len(document['nodes']) == 5 and document['wires']
    assert sum(node.get('fixed') is True for node in document['nodes']) == 4
    assert Path(b['session_path']).read_bytes() == before


def test_linked_run_reads_current_values_and_records_child_history(history):
    from nodelang.session_files import SessionFiles, new_document, write_document, read_document, run_document
    files = SessionFiles()
    child = new_document('Reusable task')
    child['nodes'] = [{'id': 'input', 'type': 'param.value', 'params': {'type': 'number', 'value': 5}, 'position': {'x': 0, 'y': 0}}]
    path = files.directory / 'child.archhub'
    write_document(path, child)
    parent = files.dispatch({'action': 'insert-session', 'document': new_document('Parent call'), 'session': str(path)})['document']
    child['nodes'][0]['params']['value'] = 42
    write_document(path, child)
    result = run_document(parent)
    assert result['succeeded'] and result['results'][parent['nodes'][0]['id']]['output']['out'] == {'value': 42}
    reread = read_document(path)
    assert reread['nodes'][0]['result']['output'] == {'value': 42}
    assert reread['properties']['history'][-1]['op'] == 'called by Parent call'
    count = len(reread['properties']['history'])
    assert run_document(parent)['succeeded']
    assert len(read_document(path)['properties']['history']) == count + 1


def test_run_refuses_post_placement_cycle_before_effect(history):
    from nodelang.session_files import SessionFiles, new_document, write_document, run_document
    files = SessionFiles()
    a, b = new_document('A'), new_document('B')
    pa, pb = files.directory / 'a.archhub', files.directory / 'b.archhub'
    write_document(pb, b)
    a = files.dispatch({'action': 'insert-session', 'document': a, 'session': str(pb)})['document']
    write_document(pa, a)
    b['nodes'] = [{'id': 'cycle', 'type': 'skill', 'params': {'skill': a['id'], 'session_file': str(pa)}, 'position': {'x': 0, 'y': 0}}]
    write_document(pb, b)
    effects = []
    with pytest.raises(ValueError, match='Cycle'):
        run_document(a, invoke=lambda *args: effects.append(args))
    assert effects == []


def test_missing_reference_can_open_for_repair_but_cannot_run(history):
    from nodelang.session_files import SessionFiles, new_document, write_document, run_document
    files = SessionFiles()
    document = new_document('Repairable composition')
    document['nodes'] = [{'id': 'linked', 'type': 'skill', 'params': {'skill': 'missing', 'session_file': str(files.directory / 'missing.archhub')},
                          'position': {'x': 0, 'y': 0}, 'children': []}]
    path = files.directory / 'repair.archhub'
    write_document(path, document)
    assert 'result' not in files.dispatch({'action': 'open', 'path': str(path)})['document']['nodes'][0]
    with pytest.raises(ValueError, match='missing'):
        run_document(document)


def test_saved_workflow_and_skill_touch_only_task_file(history):
    from nodelang import workshop_tasks as tasks
    from nodelang.session_files import SessionFiles, read_document
    a, b = [tasks.create(history, title, 'founder') for title in ('Workflow task', 'Unrelated task')]
    before = Path(b['session_path']).read_bytes()
    files = SessionFiles()
    for action in ('save', 'save-skill'):
        result = files.dispatch({'action': action, 'path': a['session_path'], 'document': read_document(a['session_path'])})
        assert result['path'] == a['session_path']
        assert Path(b['session_path']).read_bytes() == before


def test_link_survives_rename_and_refuses_replaced_identity(history):
    from nodelang.session_files import SessionFiles, new_document, write_document, linked_session, insert_session
    files = SessionFiles()
    child = new_document('Original')
    old, renamed = files.directory / 'original.archhub', files.directory / 'renamed.archhub'
    write_document(old, child)
    group = insert_session(new_document('Parent'), str(old))
    old.rename(renamed)
    assert linked_session(group['params'])[0] == str(renamed)
    write_document(old, new_document('Unrelated replacement'))
    with pytest.raises(ValueError, match='identity changed'):
        linked_session(group['params'])


def test_native_steps_are_scoped_to_declared_task(history, monkeypatch):
    from nodelang import workshop_tasks as tasks, agent_status
    from nodelang.session_files import read_document
    calls = []
    for request in ('FIRST', 'SECOND'):
        calls.extend([
            {'id': request, 'tool': 'declare', 'input': {'request_id': request, 'task': request + ' step'}, 'turn': request},
            {'id': request + '-shell', 'tool': 'Bash', 'input': {'command': 'echo ' + request}, 'turn': request}])
    monkeypatch.setattr(agent_status, 'read_transcript', lambda *args: {'calls': calls})
    for request in ('FIRST', 'SECOND'):
        tasks.declared(history, 'root', request, request + ' task', 'working', 'agent', 'Agent')
        row = tasks.get(history, tasks._declared_id('agent'))
        nodes = read_document(row['session_path'])['nodes']
        steps = [n['title'] for n in nodes if n.get('agentWork', {}).get('role') == 'step']
        assert steps == [request + ' step']


def test_repeated_purpose_creates_new_occurrence_without_changing_archive(history):
    from nodelang import workshop_tasks as tasks
    paths = []
    for purpose in ('A', 'B', 'A'):
        tasks.declared(history, 'root', purpose, purpose + ' task', 'working', 'agent', 'Agent')
        paths.append(tasks.get(history, tasks._declared_id('agent'))['session_path'])
        if len(paths) == 2:
            archived = Path(paths[0]).read_bytes()
    assert len(set(paths)) == 3
    assert Path(paths[0]).read_bytes() == archived


def test_markerless_transcript_cannot_project_and_legacy_steps_are_recoverable(history, monkeypatch):
    from nodelang import workshop_tasks as tasks, agent_status, canvas_documents
    from nodelang.session_files import read_document, restore_checkpoint
    tasks.declared(history, 'root', 'TASK', 'Only this task', 'working', 'agent', 'Agent')
    row = tasks.get(history, tasks._declared_id('agent'))
    agent = next(n for n in read_document(row['session_path'])['nodes'] if n['type'] == 'thing.agent' and not n.get('fixed'))
    def contaminate(document):
        document['nodes'].append({'id': 'foreign', 'type': 'note', 'title': 'Foreign step', 'params': {},
            'position': {'x': 0, 'y': 0}, 'agentWork': {'role': 'step', 'owner': agent['id']}})
        return []
    canvas_documents.edit(row['session_path'], 'Legacy', 'fixture', contaminate)
    monkeypatch.setattr(agent_status, 'read_transcript', lambda *args: {'calls': [
        {'id': 'unknown', 'tool': 'Bash', 'input': {'command': 'echo unrelated'}, 'turn': 'unknown'}]})
    tasks.record_step(history, row['id'], 'agent', 'Agent', 'Only this task', 'working')
    document = read_document(row['session_path'])
    assert not any(n.get('agentWork', {}).get('role') == 'step' for n in document['nodes'])
    restored = restore_checkpoint(row['session_path'], document['properties']['checkpoints'][-1]['id'])
    assert any(n['id'] == 'foreign' for n in restored['nodes'])


def test_linked_parent_and_child_share_one_approval(history, monkeypatch):
    from nodelang.session_files import SessionFiles, new_document, write_document, read_document, insert_session, run_document
    from nodelang import agent_work
    files = SessionFiles()
    child = new_document('Approved task')
    child['nodes'] = [{'id': 'write', 'type': 'thing.file.write', 'params': {'path': str(files.directory / 'output.txt'), 'content': 'approved'},
                      'approvalRequired': True, 'position': {'x': 0, 'y': 0}}]
    path = files.directory / 'approval.archhub'
    write_document(path, child)
    parent = new_document('Caller')
    insert_session(parent, str(path))
    calls = []
    def approve(*args, **kwargs):
        calls.append(args)
        return {'id': 'shared-approval'}
    monkeypatch.setattr(agent_work, 'request_approval', approve)
    result = run_document(parent)
    assert result['approvalId'] == 'shared-approval' and len(calls) == 1
    assert read_document(path)['nodes'][0]['result']['output']['approvalId'] == result['approvalId']
    assert not (files.directory / 'output.txt').exists()


def test_detach_copies_only_explicitly_and_leaves_source_unchanged(history):
    from nodelang.session_files import SessionFiles, new_document, write_document, read_document, insert_session
    files = SessionFiles()
    child = new_document('Linked original')
    child['nodes'] = [{'id': 'step', 'type': 'note', 'params': {}, 'position': {'x': 0, 'y': 0}}]
    path = files.directory / 'linked.archhub'
    write_document(path, child)
    before = path.read_bytes()
    parent = new_document('Parent')
    node = insert_session(parent, str(path))
    result = files.dispatch({'action': 'detach-session', 'document': parent, 'node': node['id']})
    detached = read_document(result['path'])
    assert detached['id'] != child['id'] and detached['nodes'] == child['nodes']
    assert path.read_bytes() == before
    assert len(result['document']['nodes']) == 1


def test_migration_crossing_wires_execute_and_checkpoint_restores_all(history):
    from nodelang.session_files import SessionFiles, new_document, write_document, read_document, run_document, restore_checkpoint, skill_ports
    files = SessionFiles()
    document = new_document('Crossing sessions')
    for key, value in (('a', 20), ('b', 7)):
        document['nodes'].extend([
            {'id': key, 'type': 'thing.agent', 'params': {'session': key}, 'agentWork': {'role': 'session'}, 'position': {'x': 0, 'y': 0}},
            {'id': key + '-step', 'type': 'param.value', 'params': {'type': 'number', 'value': value},
             'agentWork': {'role': 'step', 'owner': key}, 'position': {'x': 300, 'y': 0}}])
    document['wires'] = [{'id': 'cross', 'from': {'node': 'a-step', 'socket': 'value'}, 'to': {'node': 'b-step', 'socket': 'value'}}]
    document['notes'] = [{'id': 'note', 'text': 'Keep this annotation'}]
    path = files.directory / 'crossing.archhub'
    write_document(path, document)
    result = files.dispatch({'action': 'split-sessions', 'path': str(path)})
    migrated = read_document(path)
    assert run_document(migrated)['results']['b']['output']['out:b-step:value'] == 20
    b = next(read_document(p) for p in result['sessions'] if any(n['id'] == 'b' for n in read_document(p)['nodes']))
    assert any(p['id'] == 'in:b-step:value' for p in skill_ports(b)['target'])
    restored = restore_checkpoint(path, migrated['properties']['checkpoints'][-1]['id'])
    for key in ('nodes', 'wires', 'groups', 'notes'):
        assert restored[key] == document[key]


def test_split_shared_sessions_retains_all_nodes_and_undo(history):
    from nodelang.session_files import SessionFiles, new_document, write_document, read_document
    from nodelang.canvas_documents import undo_last
    files = SessionFiles()
    document = new_document('Legacy agents')
    for key in ('a', 'b'):
        document['nodes'].extend([
            {'id': key, 'type': 'thing.agent', 'title': key, 'params': {'session': key},
             'agentWork': {'role': 'session'}, 'position': {'x': 0, 'y': 0}},
            {'id': key + '-step', 'type': 'note', 'params': {}, 'agentWork': {'role': 'step', 'owner': key},
             'position': {'x': 300, 'y': 0}}])
        document['wires'].append({'id': key + '-wire', 'from': {'node': key, 'socket': 'result'},
                                  'to': {'node': key + '-step', 'socket': 'in'}})
    path = files.directory / 'legacy.archhub'
    document['groups'] = [{'id': 'frame', 'nodes': ['a-step', 'b-step']}]
    write_document(path, document)
    result = files.dispatch({'action': 'split-sessions', 'path': str(path)})
    split = [read_document(p) for p in result['sessions']]
    assert {n['id'] for d in split for n in d['nodes']} == {n['id'] for n in document['nodes']}
    assert all(len(d['nodes']) == 2 for d in split)
    assert len(read_document(path)['nodes']) == 2
    assert files.dispatch({'action': 'split-sessions', 'path': str(path)})['sessions'] == []
    undo_last(path, 'Test')
    restored = read_document(path)
    originals = {n['id']: n for n in document['nodes']}
    assert set(originals) == {n['id'] for n in restored['nodes']}
    for node in restored['nodes']:
        assert {key: value for key, value in node.items() if key != 'result'} == originals[node['id']]
        if node['type'] == 'thing.agent':
            assert node['result']['status'] == 'Out of date'
    assert {w['id']: w for w in restored['wires']} == {w['id']: w for w in document['wires']}
    assert restored['groups'] == document['groups']
