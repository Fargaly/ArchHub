"""Workshop UI reads the same app-produced declarations as the mailbox."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from nodelang.agent_declarations import declarations
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider


def test_split_conversation_store_declarations_reach_workshop_http(tmp_path, monkeypatch):
    from nodelang import pipeline_engines
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH', str(
        Path(pipeline_engines.__file__).parent / 'data/public_runtime_map.json'))
    monkeypatch.setattr(ApplicationServer, '_probe_hosts', staticmethod(lambda: []))
    monkeypatch.setattr(ApplicationServer, '_probe_brain', staticmethod(lambda: {'ok': False}))
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority', b'd' * 32)
    keys.add_key('archhub.local.court-attestation', b'e' * 32)
    server = ApplicationServer(universal_state_path=tmp_path / 'APP.sqlite3',
        conversation_history_path=tmp_path / 'APP.conversations.sqlite3',
        universal_key_provider=keys, universal_workspace_root=tmp_path,
        enable_machine_transport=False, enable_universal_cloud_gateway=False,
        enable_brain_cloud_sync=False, enable_machine_projection_prewarm=False,
        live_watch=False).start()
    try:
        from nodelang import commit_intent, universal_application as app
        context = server._resolve_browser_session(server.browser_session_token).context
        with server.mutation_lock, commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='synthetic Workshop Work'):
            work, _, _ = app.create_universal_governed_work(server.universal_store, server.universal_registry,
                title='Inspect the synthetic sheet', description='Synthetic fixture', external_key='DESIGNMATCH-COURT',
                references={'scope': server.universal_registry.workshop_root}, compact_references=True,
                select_created=False, authentication_context=context)
        import pytest
        for name in ('You', ' y O u ', 'BABOOM', ' b a b o o m ', 'Workshop coordination',
                     ' WORKSHOP  COORDINATION ', 'ArchHub', ' a R c H h U b ',
                     '\uff39\uff2f\uff35', '\u0423ou', 'Y\u200bou', '\u0412\u0410\u0412\u041e\u041e\u041c', 'Arch\u200bHub'):
            with pytest.raises(ValueError, match='reserved'):
                server.shared_agent_mail('declare', {'context': {'threadId': 'spoof-court'},
                    'task': 'Synthetic impersonation attempt', 'paths': [str(tmp_path / 'SHEET.txt')],
                    'status': 'working', 'request_id': 'DESIGNMATCH-COURT', 'display_name': name})
        for normal in ('Codex', 'Claude Code', 'أحمد', 'محمّد', "Ahmed's helper", 'وكيل', 'Yours', 'ArchHub Bot', 'Youssef', 'Bob', 'José', 'Łukasz'):
            accepted = server.shared_agent_mail('declare', {'context': {'threadId': 'designmatch-court'},
                'task': 'Inspect the synthetic sheet', 'paths': [str(tmp_path / 'SHEET.txt')],
                'status': 'working', 'request_id': 'DESIGNMATCH-COURT', 'display_name': normal})
            assert accepted['declaration']['display_name'] == normal
        sent = server.shared_agent_mail('declare', {'context': {'threadId': 'designmatch-court'},
            'task': 'Inspect the synthetic sheet', 'paths': [str(tmp_path / 'SHEET.txt')],
            'status': 'working', 'request_id': 'DESIGNMATCH-COURT',
            'display_name': 'Sheet reviewer', 'model': 'fixture-model'})
        assert sent['declaration']['pid'] == os.getpid()
        assert [row['request_id'] for row in declarations(server)] == ['DESIGNMATCH-COURT']
        server.shared_agent_mail('send', {'context': {'threadId': 'designmatch-court'},
            'to': '*', 'text': 'Review started', 'idempotency_key': 'designmatch-display'})
        from tests_replica.test_agenttrail import codex, write
        monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'CODEX'))
        (tmp_path / 'SHEET.txt').write_text('Synthetic sheet', encoding='utf-8')
        write(tmp_path / 'CODEX/sessions/COURT.jsonl',
            *codex(tmp_path, session='designmatch-court', file='SHEET.txt'))
        headers = {'Content-Type': 'application/json', 'Origin': server.url,
            'Cookie': 'ArchHub-Session=' + server.browser_session_token,
            'X-ArchHub-CSRF': server.browser_csrf_token}
        def call(function):
            request = Request(server.url + '/api/universal/workshop', headers=headers,
                data=json.dumps({'action': 'data-api', 'function': function, 'args': [],
                    'root': server.universal_registry.workshop_root,
                    'scope': app.project_universal_canvas(server.universal_store, server.universal_registry,
                        authentication_context=context)['scope']['current'], 'request_id': function}).encode())
            try:
                with urlopen(request, timeout=60) as response:
                    return json.load(response)['result']
            except HTTPError as exc:
                raise AssertionError(json.load(exc)) from exc
        agents = call('listAgentsWorking')
        assert any(row['runtime'] == 'codex' and row['sessions'][0]['request_id'] == 'DESIGNMATCH-COURT' for row in agents)
        tasks = call('listTasks')
        assert any(row['id'] == work and row['owner'] == 'codex' and row['status'] == 'WIP' for row in tasks)
        assert any(row['root'] == work for row in app.project_universal_governed_work(
            server.universal_store, server.universal_registry, authentication_context=context))
        with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='group existing room Work'):
            companion, _, _ = app.create_universal_governed_work(server.universal_store, server.universal_registry,
                title='Grouped companion', description='Synthetic fixture', external_key='DESIGNMATCH-GROUP',
                references={'scope': server.universal_registry.workshop_root}, compact_references=True,
                select_created=False, authentication_context=context)
            from nodelang.workshop_conversation_catalog import workshop_workbench_path
            for step in workshop_workbench_path(server.universal_store.snapshot(), server.universal_registry):
                app.set_universal_scope(server.universal_store, server.universal_registry,
                    step, authentication_context=context)
            app.set_universal_selection(server.universal_store, server.universal_registry,
                [work, companion], authentication_context=context)
            work_group, _ = app.group_universal_selection(server.universal_store, server.universal_registry,
                title='Grouped room Work', authentication_context=context)
        top = app._visibility_scope_projection(server.universal_store.snapshot(), server.universal_registry,
            app._view_session_for_context(server.universal_registry, context)[0])[0]
        grouped_canvas = app.project_universal_canvas(server.universal_store, server.universal_registry, authentication_context=context)
        assert work not in {node['id'] for node in grouped_canvas['nodes']}
        assert work_group in {node['id'] for node in grouped_canvas['nodes']}
        print('Grouped Work in top visibility:', work in top)
        assert {work, companion} <= {row['id'] for row in call('listTasks')}, 'Grouped Work must remain in Workshop'
        from nodelang.universal_graphs import create_graph
        with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='select a project with existing room Work'):
            create_graph(server.universal_store, server.universal_registry, 'Another project', authentication_context=context)
        assert any(row['id'] == work for row in call('listTasks')), 'Changing Canvas must not hide the room Work'
        assert not any(row['root'] == work for row in app.project_universal_governed_work(
            server.universal_store, server.universal_registry, authentication_context=context))
        print('Same Work fixture: canvas projection canonical=1/project=0; Workshop room canonical=1/project=1')
        messages = call('listWorkshopMessages')['messages']
        assert any(row['who'] == 'Sheet reviewer' and row['model'] == 'fixture-model'
                   and '[agent:session:' in row['author'] for row in messages)
        from nodelang.workshop_api import _message_identity
        forged = _message_identity('Agent [agent:session:spoof]', [dict(session='agent:session:spoof',
            display_name='You', app='codex', agent='Codex')], server.universal_registry.authorization.subject_root)
        assert forged['sender_key'] != forged['viewer_key']
        own = _message_identity(server.universal_registry.authorization.subject_root, [],
            server.universal_registry.authorization.subject_root)
        assert own['sender_key'] == own['viewer_key']
        assert len(declarations(server, include_archived=True)) == 1
        server.shared_agent_mail('declare', {'context': {'threadId': 'designmatch-court'},
            'task': 'Inspect the synthetic sheet', 'paths': [str(tmp_path / 'SHEET.txt')],
            'status': 'done', 'request_id': 'DESIGNMATCH-COURT'})
        assert declarations(server) == []
        assert declarations(server, include_archived=True)[0]['status'] == 'done'
        assert declarations(server, include_archived=True)[0]['model'] == 'fixture-model'
        from tests_replica.test_home3_templates import install_template
        from nodelang.universal_pipeline import create_engine_template
        from nodelang.canvas_graph_owner import CanvasOwner
        with commit_intent.declare(commit_intent.USER_ACTION, actor='court', reason='schedule a real stored group inside a project'):
            install_template(server, 'Nested schedule fixture')
            group = create_engine_template(server.universal_store, server.universal_registry,
                'Nested schedule fixture', authentication_context=context)
            parent = app.project_universal_canvas(server.universal_store, server.universal_registry,
                authentication_context=context)['scope']['current']
            app.set_universal_scope(server.universal_store, server.universal_registry,
                group['root'], authentication_context=context)
            owner = CanvasOwner(server.universal_store, server.universal_registry, context)
            snapshot = server.universal_store.snapshot()
            child_ports = {port['id'] for port in app._registered_canvas_interfaces(snapshot, server.universal_registry)
                           if port['owner'] in group['children']}
            assert child_ports
            admitted = app._scope_canvas_interface_roots(snapshot, server.universal_registry,
                tuple(group['children']), (), group['children'][0])
            assert child_ports <= admitted, 'Entering a group must retain its members free registered sockets'
            outside_ports = {port['id'] for port in app._registered_canvas_interfaces(snapshot, server.universal_registry)
                             if port['owner'] not in group['children']}
            assert not admitted.intersection(outside_ports), 'A member scope must not expose other owners sockets'
            projected_ports = {port['id'] for node in owner.canvas()['nodes'] for port in node['ports']}
            assert child_ports <= projected_ports, 'The real member cards must project every registered engine socket'
            scheduled = owner.add_schedule(group['root'], '10:30')
            canvas = owner.canvas()
            assert {wire['target'] for wire in canvas['wires'] if wire['source'] == scheduled['id']} == set(group['children'])
            app.set_universal_scope(server.universal_store, server.universal_registry, parent,
                authentication_context=context)
            retained = next(node for node in owner.canvas()['nodes'] if node['id'] == group['root'])
            assert len(retained['members']) == 3, 'The original group identity and its new trigger remain readable'
            app.set_universal_scope(server.universal_store, server.universal_registry,
                group['root'], authentication_context=context)
            owner.remove_schedule(scheduled['id'])
            app.set_universal_scope(server.universal_store, server.universal_registry, parent,
                authentication_context=context)
            retained = next(node for node in owner.canvas()['nodes'] if node['id'] == group['root'])
            assert {member['id'] for member in retained['members']} == set(group['children'])
        connection, lock = server.universal_store.sqlite_storage()
        with lock:
            assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_declarations'").fetchone()
    finally:
        server.close()


import pytest
from types import SimpleNamespace


@pytest.mark.parametrize('name', ['\uff39\uff2f\uff35', '\u0423ou', 'Y\u200bou', '\u0412\u0410\u0412\u041e\u041e\u041c', 'Arch\u200bHub',
    *['Y'+c+'ou' for c in ('\u034f','\ufe0f','\u3164','\u115f','\u1160','\uffa0')],
    'Y\u0585\u057d', 'Y\u0585u', '\u13aa r\u13dfhHub'.replace(' ',''), 'Wor\u13e6shop coordination',
    '\u028fou', 'Y\u1d0fu', '\u0299aboom', '\u03a5ou', 'ArchHu\u0185', 'Y\u0275u'])
def test_reserved_unicode_declaration(name, tmp_path):
    from nodelang.workshop_mailbox import _declare
    for spelling in ({name, name.lower()} if any(c in name for c in "ᎪᏟᏦ") else {name}):
        with pytest.raises(ValueError, match='reserved'):
            _declare(None, dict(task='Synthetic', request_id='DESIGNMATCH', paths=[str(tmp_path)],
                status='working', display_name=spelling), {}, {}, 'codex', SimpleNamespace(cwd=str(tmp_path)), 'spoof')
