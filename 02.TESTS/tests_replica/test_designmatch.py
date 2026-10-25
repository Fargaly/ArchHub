"""Workshop UI reads the same app-produced declarations as the mailbox."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

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
        sent = server.shared_agent_mail('declare', {'context': {'threadId': 'designmatch-court'},
            'task': 'Inspect the synthetic sheet', 'paths': [str(tmp_path / 'SHEET.txt')],
            'status': 'working', 'request_id': 'DESIGNMATCH-COURT'})
        assert sent['declaration']['pid'] == os.getpid()
        assert [row['request_id'] for row in declarations(server)] == ['DESIGNMATCH-COURT']
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
                    'scope': server.universal_registry.canvas_root, 'request_id': function}).encode())
            with urlopen(request, timeout=60) as response:
                return json.load(response)['result']
        agents = call('listAgentsWorking')
        assert any(row['id'] == 'codex' and row['sessions'][0]['request_id'] == 'DESIGNMATCH-COURT' for row in agents)
        tasks = call('listTasks')
        assert any(row['id'] == work and row['owner'] == 'codex' and row['status'] == 'WIP' for row in tasks)
        assert len(declarations(server, include_archived=True)) == 1
        server.shared_agent_mail('declare', {'context': {'threadId': 'designmatch-court'},
            'task': 'Inspect the synthetic sheet', 'paths': [str(tmp_path / 'SHEET.txt')],
            'status': 'done', 'request_id': 'DESIGNMATCH-COURT'})
        assert declarations(server) == []
        assert declarations(server, include_archived=True)[0]['status'] == 'done'
        connection, lock = server.universal_store.sqlite_storage()
        with lock:
            assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='workshop_declarations'").fetchone()
    finally:
        server.close()
