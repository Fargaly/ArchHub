"""Full-stack owner propagation courts for Items #2, #7, #8, #9, and #10."""
from __future__ import annotations

import json
from pathlib import Path

from tests.test_task_session_roundtrip import _Studio, _isolate, _post


def _start_isolated_server(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    return server, _Studio(server), state


def test_read_operations_preserves_probed_dependencies(tmp_path, monkeypatch):
    """Item #2: readOperations omits unprobed dependencies and returns cached rows once checked."""
    from nodelang.managed_dependencies import ManagedDependencies
    probed = [
        {'id': 'ifcopenshell', 'name': 'IfcOpenShell', 'state': 'Ready', 'installedVersion': '0.8.0'},
        {'id': 'ezdxf', 'name': 'ezdxf', 'state': 'Not installed', 'installedVersion': ''},
    ]
    monkeypatch.setattr(ManagedDependencies, 'check', lambda self: list(probed))
    server, client, _state = _start_isolated_server(tmp_path, monkeypatch)
    try:
        status, before = _post(client.connection, '/api/universal/settings-action',
                               {'function': 'readOperations', 'args': ['app:system']}, client.headers)
        assert status == 200 and before['ok'] is True
        assert 'dependencies' not in before['result']

        status, checked = _post(client.connection, '/api/universal/settings-action',
                                {'function': 'checkDependencies', 'args': []}, client.headers)
        assert status == 200 and checked['result']['dependencies'] == probed

        status, after = _post(client.connection, '/api/universal/settings-action',
                              {'function': 'readOperations', 'args': ['app:system']}, client.headers)
        assert status == 200 and after['result']['dependencies'] == probed
    finally:
        client.close()
        server.close()


def test_dock_layout_owner_admits_thread_extended_fields_and_named_layouts(tmp_path, monkeypatch):
    """Item #7: settings_owner.dock_layout is the single owner for thread, presets, closed, float, bottom, focus, and saved layouts."""
    server, client, state = _start_isolated_server(tmp_path, monkeypatch)
    owner_file = state / 'settings' / 'settings.json'
    try:
        def setting(fn, *args):
            return _post(client.connection, '/api/universal/settings-action',
                         {'function': fn, 'args': list(args)}, client.headers)

        extended = {
            'left': {'w': 280, 'c': False, 'st': [{'p': ['workshop'], 'a': 'workshop', 'h': 1.0, 'c': False}]},
            'right': {'c': False, 'st': [
                {'p': ['thread'], 'a': 'thread', 'h': 1.0, 'c': False},
                {'p': ['insp', 'people'], 'a': 'people', 'h': 1.0, 'c': False},
            ]},
            'bottom': {'h': 220, 'c': False, 'st': [{'p': ['map'], 'a': 'map', 'h': 1.0, 'c': False}]},
            'float': [{'id': 'library', 'x': 180, 'y': 72, 'w': 320, 'h': 380}],
            'focus': True,
            'preset': 'Review',
        }
        status, body = setting('setDockLayout', extended)
        assert status == 200 and body['result']['dockLayout'] == {'layout': extended}
        assert json.loads(owner_file.read_text(encoding='utf-8'))['dockLayout'] == {'layout': extended}

        # 1-arg save with savedName (and no savedChanged) persists into dockLayout.saved automatically.
        named = {
            'left': {'w': 268, 'c': False, 'st': [{'p': ['workshop'], 'a': 'workshop', 'h': 1.0, 'c': False}]},
            'right': {'c': False, 'st': [{'p': ['people', 'thread'], 'a': 'thread', 'h': 1.0, 'c': False}]},
            'closed': ['library', 'map', 'insp'],
            'savedName': 'Coordination review',
        }
        status, body = setting('setDockLayout', named)
        assert status == 200
        assert body['result']['dockLayout']['layout'] == named
        assert body['result']['dockLayout']['saved'] == {'Coordination review': named}

        # Subsequent active layout change and Reset keep saved layouts intact in the one Settings owner.
        changed = {**named, 'savedChanged': True, 'left': {**named['left'], 'w': 312}}
        status, body = setting('setDockLayout', changed)
        assert status == 200
        assert body['result']['dockLayout']['layout'] == changed
        assert body['result']['dockLayout']['saved'] == {'Coordination review': named}

        status, body = setting('setDockLayout', None)
        assert status == 200
        assert body['result']['dockLayout'] == {'layout': None, 'saved': {'Coordination review': named}}
        assert setting('readControls')[1]['result']['dockLayout'] == {'layout': None, 'saved': {'Coordination review': named}}

        # Reject invalid placed+closed overlap and unknown preset.
        for invalid in (
            {**named, 'closed': ['workshop']},
            {**extended, 'preset': 'UnknownPreset'},
        ):
            bad_status, bad_body = setting('setDockLayout', invalid)
            assert bad_status >= 400 or bad_body.get('ok') is False
    finally:
        client.close()
        server.close()


def test_router_free_first_toggle_persists_both_false_and_true(tmp_path, monkeypatch):
    """Item #8: Prefer free models toggle saves both False and True in router.json while rejecting non-bools."""
    server, client, state = _start_isolated_server(tmp_path, monkeypatch)
    router_file = state / 'settings' / 'router.json'
    try:
        status, off = _post(client.connection, '/api/router/settings', {'free_first': False}, client.headers)
        assert status == 200 and off['ok'] is True and off['free_first'] is False
        assert json.loads(router_file.read_text(encoding='utf-8'))['free_first'] is False

        status, on = _post(client.connection, '/api/router/settings', {'free_first': True}, client.headers)
        assert status == 200 and on['ok'] is True and on['free_first'] is True
        assert json.loads(router_file.read_text(encoding='utf-8'))['free_first'] is True

        bad_status, bad_body = _post(client.connection, '/api/router/settings', {'free_first': 'false'}, client.headers)
        assert bad_status == 400 and bad_body['ok'] is False
    finally:
        client.close()
        server.close()


def test_all_six_automation_triggers_validate_and_execute_on_session_files(tmp_path, monkeypatch):
    """Item #9: All six Trigger items validate, save to .archhub, and run cleanly."""
    server, client, _state = _start_isolated_server(tmp_path, monkeypatch)
    try:
        cat = client.files('catalogue')
        items = {row['id']: row for row in cat['items']}
        expected = {
            'tr_manual': 'trigger.emit',
            'tr_schedule': 'trigger.schedule',
            'tr_file': 'trigger.file',
            'tr_host': 'trigger.host',
            'tr_approval': 'trigger.approval',
            'tr_webhook': 'trigger.webhook',
        }
        nodes = []
        for idx, (item_id, engine) in enumerate(expected.items()):
            assert items[item_id]['engine'] == engine
            assert not items[item_id].get('noEngine')
            nodes.append({
                'id': 'trig-' + item_id,
                'type': engine,
                'item': item_id,
                'title': items[item_id]['title'],
                'params': {**items[item_id]['params'], 'armed': False},
                'position': {'x': 80, 'y': 80 + idx * 120},
            })
        doc = {
            'format': 'archhub', 'version': 1, 'id': 'triggers-session', 'title': 'Triggers session',
            'nodes': nodes, 'wires': [], 'groups': [], 'notes': [],
            'viewport': {'x': 0, 'y': 0, 'zoom': 1}, 'properties': {},
        }
        saved = client.files('save', document=doc)
        assert Path(saved['path']).is_file()
        ran = client.files('run', path=saved['path'], document=saved['document'])
        assert ran['succeeded'] is True
        for node in nodes:
            assert ran['results'][node['id']]['status'] == 'Done'
    finally:
        client.close()
        server.close()


def test_canvas_and_workshop_session_actions_run_end_to_end(tmp_path, monkeypatch):
    """Item #10: trace_node, set_node_flags, run_to_here, graph versions/update/remove, and Workshop task actions."""
    server, client, _state = _start_isolated_server(tmp_path, monkeypatch)
    try:
        def canvas_op(op, *args):
            status, body = _post(client.connection, '/api/universal/canvas-op',
                                 {'op': op, 'args': list(args)}, client.headers)
            assert status == 200, body
            return body['result']

        cat = {row['id']: row for row in client.files('catalogue')['items']}
        doc = {
            'format': 'archhub', 'version': 1, 'id': 'prop-flow', 'title': 'Propagation flow',
            'nodes': [
                {'id': 'n1', 'type': cat['n_list']['engine'], 'item': 'n_list', 'title': 'Rooms',
                 'params': {'value': '[1, 2, 3, 4]'}, 'position': {'x': 80, 'y': 80}},
                {'id': 'n2', 'type': cat['s_slice']['engine'], 'item': 's_slice', 'title': 'First two',
                 'params': {'count': '2'}, 'position': {'x': 380, 'y': 80}},
                {'id': 'n3', 'type': cat['s_count']['engine'], 'item': 's_count', 'title': 'Count rooms',
                 'params': {}, 'position': {'x': 680, 'y': 80}},
            ],
            'wires': [
                {'id': 'w1', 'from': {'node': 'n1', 'socket': 'value'}, 'to': {'node': 'n2', 'socket': 'items'}},
                {'id': 'w2', 'from': {'node': 'n2', 'socket': 'items_out'}, 'to': {'node': 'n3', 'socket': 'items'}},
            ],
            'groups': [], 'notes': [], 'viewport': {'x': 0, 'y': 0, 'zoom': 1}, 'properties': {},
        }
        saved = client.files('save', document=doc)
        flow_path = saved['path']

        # trace_node forward and back
        fwd = canvas_op('trace_node', 'n1', 'forward')
        assert [r['id'] for r in fwd] == ['n2', 'n3']
        assert all(r['direction'] == 'forward' and '→' in r['relation'] for r in fwd)
        back = canvas_op('trace_node', 'n3', 'back')
        assert [r['id'] for r in back] == ['n2', 'n1']

        # set_node_flags & run_to_here
        flagged = canvas_op('set_node_flags', 'n2', True, True)
        assert flagged == {'id': 'n2', 'frozen': True, 'pinned': True, 'document': flagged['document']}
        ran_partial = canvas_op('run_to_here', 'n2')
        assert ran_partial['roots'] == ['n2']
        assert set(ran_partial['results']) == {'n1', 'n2'}

        # save_graph_version, update_graph, restore_graph_version, remove_graph
        ver = canvas_op('save_graph_version', 'Baseline 3 nodes', flow_path)
        assert ver['version']['name'] == 'Baseline 3 nodes'
        assert len(ver['versions']) == 1 and len(ver['versions'][0]['nodes']) == 3

        updated_meta = canvas_op('update_graph', flow_path, 'Renamed flow', True)
        assert updated_meta == {'id': flow_path, 'name': 'Renamed flow', 'pinned': True}
        listed = next(s for s in client.files('catalogue')['sessions'] if s['path'] == flow_path)
        assert listed['title'] == 'Renamed flow' and listed['pinned'] is True and len(listed['nodes']) == 3

        restored = canvas_op('restore_graph_version', ver['version']['id'], flow_path)
        assert restored['document']['title'] == 'Propagation flow'

        removed = canvas_op('remove_graph', flow_path)
        assert removed['ok'] is True and not Path(flow_path).exists()

        # Workshop task actions: delegate, agent access (edit/read-only/remove), queue/settle message, steer, planMode, review, reassign
        created = client.workshop('createTask', 'Coordinate facade mullions')
        tid = created['taskId']
        original_session_path = created['path']

        delegated = client.workshop('setTaskDelegate', tid, 'codex')
        assert delegated['owner'] == 'codex'
        assert 'Codex' in delegated['agents']
        assert delegated['sessionPath'] == original_session_path
        assert any('Assigned to continue task' in m['text'] for m in delegated['agentLog'])

        ro_grant = client.workshop('setTaskAgentAccess', tid, 'gemini-cli', 'read-only')
        assert 'Gemini CLI' in ro_grant['readOnlyAgents']
        assert ro_grant['agentAccess']['Gemini CLI'] == 'read-only'
        assert ro_grant['agentAccess']['Codex'] == 'edit'
        saved_task_doc = client.files('read', path=original_session_path)['document']
        start_node = next(n for n in saved_task_doc['nodes'] if n['id'] == 'start')
        assert 'Gemini CLI' in start_node['params']['read_only_agents']

        edit_grant = client.workshop('setTaskAgentAccess', tid, 'gemini-cli', 'edit')
        assert 'Gemini CLI' not in edit_grant['readOnlyAgents']
        assert edit_grant['agentAccess']['Gemini CLI'] == 'edit'

        revoked = client.workshop('setTaskAgentAccess', tid, 'gemini-cli', 'remove')
        assert 'Gemini CLI' not in revoked['agents']
        assert 'Gemini CLI' not in revoked['readOnlyAgents']

        queued = client.workshop('queueTaskMessage', tid, 'Verify curtain wall grid first')
        assert queued['state'] == 'queued'
        settled = client.workshop('settleQueuedMessage', tid, queued['id'], True)
        assert settled['ok'] is True and settled['state'] == 'sent'

        queued2 = client.workshop('queueTaskMessage', tid, 'Obsolete note')
        withdrawn = client.workshop('settleQueuedMessage', tid, queued2['id'], False)
        assert withdrawn['withdrawn'] is True

        steered = client.workshop('steerTask', tid, 'Pause')
        assert steered['control']['request'] == 'Pause'

        mode = client.workshop('setTaskPlanMode', tid, 'Run on its own')
        assert mode['planMode'] == 'Run on its own'

        rev = client.workshop('addTaskReview', tid, 'All changes', 'Check thermal break detail')
        assert rev['resolved'] is False
        resolved = client.workshop('resolveTaskReview', tid, 0, True)
        assert resolved['resolved'] is True

        reassigned = client.workshop('reassignTask', tid, 'Claude Code')
        assert reassigned['status'] == 'PLANNED'
        assert reassigned['sessionPath'] == original_session_path
        assert 'Claude Code' in reassigned['agents']
        assert reassigned['reviews'][0]['resolved'] is True
        assert reassigned['planMode'] == 'Run on its own'
        assert reassigned['control']['request'] == 'Pause'
        assert len(reassigned['queuedMessages']) == 1 and reassigned['queuedMessages'][0]['state'] == 'sent'
        assert any('Verify curtain wall grid first' in m['text'] for m in reassigned['agentLog'])
        assert any('Continue task ' + tid in m['text'] for m in reassigned['agentLog'])
    finally:
        client.close()
        server.close()
