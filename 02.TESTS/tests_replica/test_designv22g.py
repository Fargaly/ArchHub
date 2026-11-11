"""DESIGNV22G: real owners and targets, disposable profiles only."""
import copy
from pathlib import Path

import pytest

from nodelang import canvas_documents, session_files, workshop_tasks
from nodelang.workshop_mailbox import application_history, attach_meeting_notes


def test_script_uses_timed_python_and_pure_classification():
    from nodelang.host_exec import script_is_pure
    document = session_files.new_document('Script proof')
    document['nodes'] = [{'id': 'script', 'type': 'script.python', 'item': 'script_python',
                          'params': {'code': 'def run(a):\n    return {"result": a + 2}', 'a': 3, 'kind': 'pure', 'timeout': 2},
                          'position': {'x': 0, 'y': 0}}]
    assert canvas_documents.is_pure('script.python', document['nodes'][0]['params'])
    result = session_files.run_document(document)
    assert result['results']['script']['output'] == {'result': 5}
    for code in ('import os\ndef run(a):\n    return {"result": os.getcwd()}',
                 'def run(a):\n    return {"result": open(a).read()}',
                 'def run(a):\n    return {"result": a.__class__}',
                 'def run(a):\n    while True: pass',
                 'def run(a):\n    return {"result": run(a)}'):
        assert not script_is_pure(code)
    document['nodes'][0]['params']['kind'] = 'effect'
    assert not canvas_documents.is_pure('script.python', document['nodes'][0]['params'])


def test_effect_script_waits_for_one_approval_without_running(monkeypatch):
    from nodelang import agent_work, host_exec
    asked = []
    monkeypatch.setattr(agent_work, 'request_approval', lambda *a, **k: asked.append(a) or {'id': 'approval-proof'})
    monkeypatch.setattr(host_exec, '_python', lambda *a: pytest.fail('effect ran before approval'))
    document = session_files.new_document('Held script')
    document['nodes'] = [{'id': 'script', 'type': 'script.python', 'params': {'code': 'def run():\n    return {}', 'kind': 'effect'}, 'position': {'x': 0, 'y': 0}}]
    result = session_files.run_document(document)
    assert result['approvalId'] == 'approval-proof'
    assert result['results']['script']['status'] == 'Waiting for approval'
    assert len(asked) == 1
    document['nodes'][0]['params'].update(kind='pure', code='def run(a):\n    return {"result": a}')
    document['nodes'].append({'id': 'code', 'type': 'param.value', 'params': {'type': 'text', 'value': 'import os\ndef run(a):\n    return {}'}, 'position': {'x': 0, 'y': 0}})
    document['wires'] = [{'id': 'code-wire', 'from': {'node': 'code', 'socket': 'value'}, 'to': {'node': 'script', 'socket': 'param:code'}}]
    document['nodes'][0]['paramDefs'] = [{'id': 'code', 'name': 'Code', 'type': 'text'}]
    asked.clear()
    solved = canvas_documents.solve(document, ['code'])
    assert solved['results']['script']['status'] == 'Out of date'
    assert asked == []


def test_pure_saved_script_solves_without_writing_its_definition():
    document = session_files.new_document('Pure reusable script')
    document['nodes'] = [{'id': 'script', 'type': 'script.python', 'params': {'code': 'def run(a):\n    return {"result": a + 1}', 'kind': 'pure', 'a': 4, 'timeout': 2}, 'position': {'x': 0, 'y': 0}}]
    saved = session_files.node_type_document(document, ['script'], 'Pure add')
    path = session_files.document_path(session_files.sessions_directory(), saved)
    session_files.write_document(path, saved)
    before = path.read_bytes()
    parent = session_files.new_document('Caller')
    node = session_files.insert_session(parent, str(path))
    assert node['pure'] is True
    solved = canvas_documents.solve(parent, [node['id']])
    assert solved['results'][node['id']]['output']['out:script:result'] == 5
    assert path.read_bytes() == before
    saved['properties']['nodeType']['kind'] = 'effect'
    session_files.write_document(path, saved)
    assert canvas_documents.is_pure('skill', {'skill': saved['id'], 'session_file': str(path)}) is False


def test_bypass_and_disabled_wire_change_real_run():
    document = session_files.new_document('Bypass')
    document['nodes'] = [
        {'id': 'a', 'type': 'math.expression', 'item': 'math_expression', 'params': {'expression': '7', 'a': 0, 'b': 0}, 'position': {'x': 0, 'y': 0}},
        {'id': 'b', 'type': 'math.expression', 'item': 'math_expression', 'params': {'expression': 'a * 10', 'a': 2, 'b': 0}, 'bypassed': True, 'position': {'x': 300, 'y': 0}}]
    document['wires'] = [{'id': 'ab', 'from': {'node': 'a', 'socket': 'value'}, 'to': {'node': 'b', 'socket': 'a'}}]
    invoke = lambda _engine, effect, params, feeds: effect(params, feeds)
    assert session_files.run_document(document, invoke=invoke)['results']['b']['output'] == {'value': 7, 'out': 7}
    document['nodes'][1]['bypassed'] = False
    document['wires'][0]['enabled'] = False
    assert session_files.run_document(document, invoke=invoke)['results']['b']['output'] == {'value': 20, 'out': 20}
    document['wires'][0]['enabled'] = 'false'
    with pytest.raises(ValueError, match='Boolean'):
        session_files.validate(document)
    assert session_files.wire_rule(document, 'ab', 'value > 0') == 'value > 0'
    assert session_files.wire_rule(document, 'ab', '') == ''
    with pytest.raises(ValueError, match='comparison'):
        session_files.wire_rule(document, 'ab', 'not a comparison')


def test_saved_node_type_keeps_source_and_public_parameter_round_trip():
    document = session_files.new_document('Private task')
    document['properties'] = {'taskContext': {'task': 'private task'}}
    document['nodes'] = [{'id': 'calc', 'type': 'math.expression', 'item': 'math_expression', 'params': {'expression': 'a + 1', 'a': 2, 'b': 0},
                          'paramDefs': [{'id': 'a', 'name': 'Amount', 'type': 'number'}], 'result': {'status': 'Done', 'output': {'value': 3}}, 'position': {'x': 0, 'y': 0}}]
    before = copy.deepcopy(document)
    saved = session_files.node_type_document(document, ['calc'], 'Add one', 'Checks', [{'node': 'calc', 'key': 'a'}])
    assert document == before
    assert saved['id'] != document['id']
    assert 'taskContext' not in saved['properties'] and 'result' not in saved['nodes'][0]
    session_files.write_document(session_files.document_path(session_files.sessions_directory(), saved), saved)
    result, _ = session_files.run_skill({'skill': saved['id'], 'public_0': 9}, feeds={}, depth=0, invoke=lambda _engine, effect, params, feeds: effect(params, feeds), stopped=None)
    assert result['out:calc:value'] == 10
    document['nodes'][0]['params']['expression'] = 'api_key="example-sensitive-value"'
    with pytest.raises(ValueError, match='credentials'):
        session_files.node_type_document(document, ['calc'], 'Refused')


def test_open_tabs_round_trip_and_refuse_invalid_view_state():
    from nodelang.settings_owner import canvas_tabs
    state = {'tabs': [{'id': 'one', 'kept': True}, {'id': 'two', 'kept': False}],
             'active': 'one', 'split': 'two', 'collapsed': True}
    assert canvas_tabs('setCanvasTabs', [state])['canvasTabs'] == state
    assert canvas_tabs()['canvasTabs'] == state
    for invalid in ({**state, 'active': 'absent'}, {**state, 'split': 'one'},
                    {**state, 'tabs': state['tabs'] * 2}):
        with pytest.raises(ValueError):
            canvas_tabs('setCanvasTabs', [invalid])
    assert canvas_tabs()['canvasTabs'] == state


def test_new_task_has_four_wireable_fixed_nodes_and_open_never_runs(monkeypatch):
    with application_history() as history:
        view = workshop_tasks.create_session(history, 'A real task', agent='BABOOM', zoom=.9)
        path = Path(view['path'])
        document = session_files.read_document(path)
        assert len(document['nodes']) == 4
        assert len(document['wires']) == 3
        assert {node['type'] for node in document['nodes']} == {'thing.session', 'thing.agent', 'thing.you', 'thing.workshop'}
        assert all(node['fixed'] for node in document['nodes'])
        assert document['viewport']['zoom'] == .9
        before = path.read_bytes()
        monkeypatch.setattr(session_files, 'run_document', lambda *a, **k: pytest.fail('Opening executed a document'))
        monkeypatch.setattr(canvas_documents, 'solve', lambda *a, **k: pytest.fail('Opening solved a document'))
        workshop_tasks.open_session(history, view['taskId'])
        session_files.SessionFiles().dispatch({'action': 'open', 'path': str(path)})
        assert path.read_bytes() == before
        with pytest.raises(ValueError, match='fixed nodes'):
            canvas_documents.edit(path, 'You', 'delete', lambda doc: doc['nodes'].pop())
        assert path.read_bytes() == before
        with pytest.raises(ValueError, match='registered'):
            workshop_tasks.create_session(history, 'Invalid workspace', workspace='not-registered')


def test_notes_attach_without_send_and_pins_reference_only_the_task(monkeypatch):
    from nodelang import workshop_mailbox
    monkeypatch.setattr(workshop_mailbox, '_send', lambda *a, **k: pytest.fail('Attaching sent to an agent'))
    with application_history() as history:
        task = workshop_tasks.create_session(history, 'Meeting')
        other = workshop_tasks.create_session(history, 'Other task')
        note = attach_meeting_notes(history, task['taskId'], 'Decided to keep the north entrance.')
        assert workshop_tasks._bound_messages(history, task['taskId'])[-1]['text'] == 'Decided to keep the north entrance.'
        pinned = workshop_tasks.pin_message(history, task['taskId'], note['id'], True)
        assert pinned['pinnedMessages'] == [note['id']]
        with pytest.raises(ValueError, match='does not belong'):
            workshop_tasks.pin_message(history, other['taskId'], note['id'], True)
        assert workshop_tasks.pin_message(history, task['taskId'], note['id'], False)['pinnedMessages'] == []


def test_fixed_agent_binding_solves_without_sending(monkeypatch):
    from nodelang import workshop_mailbox
    monkeypatch.setattr(workshop_mailbox, 'call', lambda *a, **k: pytest.fail('Solving invoked the mailbox'))
    with application_history() as history:
        task = workshop_tasks.create_session(history, 'Binding only', agent='BABOOM')
        document = session_files.read_document(task['path'])
        agent = next(node for node in document['nodes'] if node['type'] == 'thing.agent')
        agent['params']['agent'] = 'Codex'
        solved = canvas_documents.solve(document, [agent['id']])
        assert solved['results'][agent['id']]['output']['agent'] == 'Codex'
        assert solved['results']['start']['output']['agent'] == 'Codex'
        assert canvas_documents.is_pure('thing.agent', agent['params'])
        agent['params']['reference'] = False
        stale = canvas_documents.solve(document, [agent['id']])
        assert agent['id'] in stale['stale']


def test_task_rename_updates_its_bound_file_and_refuses_partial_failure(monkeypatch):
    with application_history() as history:
        task = workshop_tasks.create_session(history, 'Original task')
        before = session_files.read_document(task['path'])
        workshop_tasks.rename(history, task['taskId'], 'Renamed task')
        renamed = session_files.read_document(task['path'])
        assert renamed['title'] == workshop_tasks.get(history, task['taskId'])['title'] == 'Renamed task'
        assert renamed['id'] == before['id']
        assert renamed['nodes'] == before['nodes']
        with monkeypatch.context() as patch:
            def refused(*args, **kwargs):
                raise OSError('Target file write refused')
            patch.setattr(canvas_documents, 'edit', refused)
            with pytest.raises(OSError, match='Target file write refused'):
                workshop_tasks.rename(history, task['taskId'], 'Must not persist')
        assert workshop_tasks.get(history, task['taskId'])['title'] == 'Renamed task'
        assert session_files.read_document(task['path']) == renamed


@pytest.mark.parametrize('code', [5, 32, 33, 13])
@pytest.mark.parametrize('kind', ['account', 'json'])
def test_canvas_settings_preserve_data_through_windows_reader_conflicts(tmp_path, monkeypatch, code, kind):
    import os
    from nodelang.settings_owner import AccountFiles
    from nodelang.nograph_server import JsonFile
    owner = AccountFiles(tmp_path / 'settings.json') if kind == 'account' else JsonFile(tmp_path / 'settings.json', {})
    write = owner.write if kind == 'account' else lambda key, value: owner.update({key: value})
    read = owner.read if kind == 'account' else lambda key: owner.read()[key]
    write('other-page', {'preserved': True})
    before = owner.path.read_bytes()
    replace, attempts = os.replace, []
    def busy_reader(source, target):
        if Path(target) == owner.path:
            attempts.append(target)
            if len(attempts) <= 2:
                error = PermissionError('Fixture reader has the previous settings open')
                error.winerror = code
                raise error
        return replace(source, target)
    monkeypatch.setattr(os, 'replace', busy_reader)
    if code == 13:
        with pytest.raises(PermissionError):
            write('canvasTabs', {'active': 'task'})
        assert owner.path.read_bytes() == before
        assert len(attempts) == 1
    else:
        write('canvasTabs', {'active': 'task'})
        assert read('canvasTabs') == {'active': 'task'}
        assert read('other-page') == {'preserved': True}
        assert len(attempts) == 3


def test_settings_instances_preserve_concurrent_page_updates(tmp_path, monkeypatch):
    import concurrent.futures
    import threading
    from nodelang.nograph_server import JsonFile
    path = tmp_path / 'settings.json'
    one, two = JsonFile(path, {}), JsonFile(path, {})
    one.write({})
    entered, release, competing, second_read = (threading.Event() for _ in range(4))
    original, reads = Path.read_text, []
    def paused_read(target, *args, **kwargs):
        value = original(target, *args, **kwargs)
        if target == path:
            reads.append(value)
            if len(reads) == 1:
                entered.set()
                assert release.wait(5)
            else:
                second_read.set()
        return value
    monkeypatch.setattr(Path, 'read_text', paused_read)
    def update_other_page():
        competing.set()
        return two.update({'notifications': ['message:one']})
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(one.update, {'canvasTabs': {'active': 'task'}})
        try:
            assert entered.wait(5)
            second = pool.submit(update_other_page)
            assert competing.wait(5)
            assert not second_read.wait(.1)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert one.read() == {'canvasTabs': {'active': 'task'}, 'notifications': ['message:one']}


def approval_document(tmp_path):
    document = session_files.new_document('Approval and resume')
    document['nodes'] = [
        {'id': 'gate', 'type': 'approval.gate', 'params': {}, 'position': {'x': 0, 'y': 0}},
        {'id': 'write', 'type': 'thing.file.write', 'params': {'path': str(tmp_path / 'target.txt'), 'content': 'Approved content'}, 'position': {'x': 300, 'y': 0}},
    ]
    path = tmp_path / 'run.archhub'
    session_files.write_document(path, document)
    return document, path


def test_canvas_approval_resumes_without_approving_the_next_effect(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    document, path = approval_document(tmp_path)
    run = session_files.run_document(document, path=path)
    assert run['results']['gate']['status'] == 'Waiting for approval'
    assert run['results']['write']['status'] == 'Waiting'
    assert not (tmp_path / 'target.txt').exists()
    card = next(card for card in ask_reviews() if card['id'] == run['approvalId'])
    assert card['approvalKind'] == 'canvas'
    assert ask_apply(card['id'], card['input_digest'], 'approve')['status'] == 'approved'
    held = session_files.read_document(path)
    assert held['nodes'][0]['result']['status'] == 'Done'
    assert held['nodes'][1]['result']['status'] == 'Waiting for approval'
    assert not (tmp_path / 'target.txt').exists()
    next_card = next(card for card in ask_reviews() if card['status'] == 'pending')
    assert ask_apply(next_card['id'], next_card['input_digest'], 'approve')['status'] == 'approved'
    assert (tmp_path / 'target.txt').read_text() == 'Approved content'
    assert all(row['result']['status'] == 'Done' for row in session_files.read_document(path)['nodes'])
    stamp = (tmp_path / 'target.txt').stat().st_mtime_ns
    ask_apply(next_card['id'], next_card['input_digest'], 'approve')
    assert (tmp_path / 'target.txt').stat().st_mtime_ns == stamp


def test_canvas_approval_refuses_changed_inputs(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    document, path = approval_document(tmp_path)
    result = session_files.run_document(document, path=path)
    card = next(card for card in ask_reviews() if card['id'] == result['approvalId'])
    changed = copy.deepcopy(document)
    changed['nodes'][1]['params']['content'] = 'Changed after approval request'
    session_files.write_document(path, changed)
    with pytest.raises(ValueError, match='canvas changed'):
        ask_apply(card['id'], card['input_digest'], 'approve')
    assert not (tmp_path / 'target.txt').exists()


def test_foreach_approves_one_item_at_a_time_without_replaying(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    catalogue = {row['id']: row for row in session_files.catalogue()}
    def card(item, identity):
        entry = catalogue[item]
        return {'id': identity, 'type': entry['engine'], 'item': item, 'params': copy.deepcopy(entry['params']), 'position': {'x': 0, 'y': 0}}
    document = session_files.new_document('Each file approval')
    listing, batch = card('param.value', 'list'), card('l_foreach', 'each')
    listing['params'] = {'type': 'list', 'value': ['first', 'second']}
    target = tmp_path / 'each.txt'
    write = {'id': 'write', 'type': 'thing.file.write', 'params': {'path': str(target), 'content': ''}, 'paramDefs': [{'id': 'content', 'name': 'Content', 'type': 'text'}], 'position': {'x': 300, 'y': 0}}
    document['nodes'] = [listing, batch, write]
    document['wires'] = [
        {'id': 'list-each', 'from': {'node': 'list', 'socket': 'value'}, 'to': {'node': 'each', 'socket': 'items'}},
        {'id': 'each-write', 'from': {'node': 'each', 'socket': 'each'}, 'to': {'node': 'write', 'socket': 'param:content'}},
    ]
    path = tmp_path / 'each.archhub'
    session_files.write_document(path, document)
    result = session_files.run_document(document, path=path)
    assert result['results']['write']['status'] == 'Waiting for approval'
    assert not target.exists()
    for content in ('first', 'second'):
        pending = [card for card in ask_reviews() if card['status'] == 'pending']
        assert len(pending) == 1
        ask_apply(pending[0]['id'], pending[0]['input_digest'], 'approve')
        assert target.read_text() == content
    assert session_files.read_document(path)['nodes'][-1]['result']['status'] == 'Done'


def test_canvas_reject_stops_without_target_effect(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    document, path = approval_document(tmp_path)
    result = session_files.run_document(document, path=path)
    for row in document['nodes']:
        row['result'] = result['results'][row['id']]
    session_files.write_document(path, document)
    card = next(card for card in ask_reviews() if card['id'] == result['approvalId'])
    assert ask_apply(card['id'], card['input_digest'], 'deny')['status'] == 'declined'
    assert not (tmp_path / 'target.txt').exists()
    assert session_files.read_document(path)['nodes'][0]['result']['status'] == 'Declined'


def linked_approval_document(tmp_path):
    child = session_files.new_document('Linked writer')
    child['nodes'] = [{'id': 'write', 'type': 'thing.file.write', 'params': {'path': str(tmp_path / 'child.txt'), 'content': 'Child approved'}, 'position': {'x': 0, 'y': 0}}]
    child_path = tmp_path / 'child.archhub'
    session_files.write_document(child_path, child)
    caller = session_files.new_document('Calling canvas')
    linked = session_files.insert_session(caller, str(child_path))
    caller['nodes'].append({'id': 'tail', 'type': 'thing.file.write', 'params': {'path': str(tmp_path / 'caller.txt'), 'content': 'Caller approved'}, 'position': {'x': 300, 'y': 0}})
    path = tmp_path / 'caller.archhub'
    session_files.write_document(path, caller)
    return caller, path, child_path, linked['id']


def test_linked_approval_resumes_caller_without_replaying_child(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    caller, path, child_path, linked = linked_approval_document(tmp_path)
    result = session_files.run_document(caller, path=path)
    assert result['results'][linked]['status'] == 'Waiting for approval'
    first = next(card for card in ask_reviews() if card['id'] == result['approvalId'])
    assert ask_apply(first['id'], first['input_digest'], 'approve')['status'] == 'approved'
    assert (tmp_path / 'child.txt').read_text() == 'Child approved'
    assert not (tmp_path / 'caller.txt').exists()
    held = session_files.read_document(path)
    assert held['nodes'][0]['result']['status'] == 'Done'
    assert held['nodes'][1]['result']['status'] == 'Waiting for approval'
    stamp = (tmp_path / 'child.txt').stat().st_mtime_ns
    second = next(card for card in ask_reviews() if card['status'] == 'pending')
    ask_apply(second['id'], second['input_digest'], 'approve')
    assert (tmp_path / 'caller.txt').read_text() == 'Caller approved'
    assert (tmp_path / 'child.txt').stat().st_mtime_ns == stamp
    assert session_files.read_document(child_path)['nodes'][0]['result']['status'] == 'Done'
    assert all(node['result']['status'] == 'Done' for node in session_files.read_document(path)['nodes'])


def test_linked_approval_refuses_changed_caller_before_child_write(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    caller, path, _, _ = linked_approval_document(tmp_path)
    result = session_files.run_document(caller, path=path)
    caller['nodes'][-1]['params']['content'] = 'Changed after request'
    session_files.write_document(path, caller)
    card = next(card for card in ask_reviews() if card['id'] == result['approvalId'])
    with pytest.raises(ValueError, match='calling canvas changed'):
        ask_apply(card['id'], card['input_digest'], 'approve')
    assert not (tmp_path / 'child.txt').exists()
    assert not (tmp_path / 'caller.txt').exists()


def test_linked_rejection_stops_both_documents(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    caller, path, child_path, _ = linked_approval_document(tmp_path)
    result = session_files.run_document(caller, path=path)
    card = next(card for card in ask_reviews() if card['id'] == result['approvalId'])
    ask_apply(card['id'], card['input_digest'], 'deny')
    assert session_files.read_document(child_path)['nodes'][0]['result']['status'] == 'Declined'
    assert session_files.read_document(path)['nodes'][0]['result']['status'] == 'Declined'
    assert not (tmp_path / 'child.txt').exists()
    assert not (tmp_path / 'caller.txt').exists()


def test_failed_linked_target_marks_caller_error_and_blocks_its_downstream(tmp_path):
    from nodelang.hook_decision import ask_apply, ask_reviews
    caller, path, child_path, linked = linked_approval_document(tmp_path)
    child = session_files.read_document(child_path)
    child['nodes'][0]['params']['path'] = str(tmp_path)
    session_files.write_document(child_path, child)
    caller['nodes'][-1]['paramDefs'] = [{'id': 'content', 'name': 'Content', 'type': 'text'}]
    caller['wires'] = [{'id': 'child-tail', 'from': {'node': linked, 'socket': 'out'}, 'to': {'node': 'tail', 'socket': 'param:content'}}]
    session_files.write_document(path, caller)
    result = session_files.run_document(caller, path=path)
    card = next(card for card in ask_reviews() if card['id'] == result['approvalId'])
    ask_apply(card['id'], card['input_digest'], 'approve')
    assert session_files.read_document(child_path)['nodes'][0]['result']['status'] == 'Error'
    held = session_files.read_document(path)
    assert held['nodes'][0]['result']['status'] == 'Error'
    assert held['nodes'][1]['result']['status'] == 'Blocked'
    assert not (tmp_path / 'caller.txt').exists()
