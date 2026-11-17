"""The Canvas dock: its layout owner over the real route, and the compiled Studio on a seeded temporary Workshop."""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio, _post

LAYOUT = {
    'left': {'w': 268, 'c': False, 'st': [
        {'p': ['workshop'], 'a': 'workshop', 'h': 1.15, 'c': False},
        {'p': ['library'], 'a': 'library', 'h': 1, 'c': True}]},
    'right': {'c': False, 'st': [
        {'p': ['map'], 'a': 'map', 'h': 1, 'c': False},
        {'p': ['insp'], 'a': 'insp', 'h': 1, 'c': False}]},
}


def test_dock_layout_owner_over_the_settings_route(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    owner = state / 'settings' / 'settings.json'
    try:
        def setting(function, *args):
            return _post(client.connection, '/api/universal/settings-action', {'function': function, 'args': list(args)}, client.headers)
        status, body = setting('readDockLayout')
        assert status == 200 and body['result']['dockLayout'] == {'sessions': {}, 'projects': {}}
        status, body = setting('setDockLayout', 'task-a', 'studio', LAYOUT)
        assert status == 200 and body['ok']
        assert body['result']['dockLayout'] == {'sessions': {'task-a': LAYOUT}, 'projects': {'studio': LAYOUT}}
        assert json.loads(owner.read_text(encoding='utf8'))['dockLayout']['sessions']['task-a'] == LAYOUT
        # A second session of the same project starts from the project's last layout; a session without a project keeps its own.
        other = {**LAYOUT, 'left': {**LAYOUT['left'], 'w': 300}}
        assert setting('setDockLayout', 'task-b', '', other)[1]['result']['dockLayout']['projects'] == {'studio': LAYOUT}
        # The boot read carries the same record, so a reload restores the layout.
        assert setting('readControls')[1]['result']['dockLayout']['sessions'] == {'task-a': LAYOUT, 'task-b': other}
        before = owner.read_bytes()
        slot = LAYOUT['right']['st'][0]
        for bad in (
                {'left': LAYOUT['left']},
                {**LAYOUT, 'left': {**LAYOUT['left'], 'w': 199}},
                {**LAYOUT, 'left': {**LAYOUT['left'], 'w': True}},
                {**LAYOUT, 'right': {**LAYOUT['right'], 'w': 320}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'p': ['map', 'workshop']}]}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'p': ['chat'], 'a': 'chat'}]}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'a': 'insp'}]}},
                {**LAYOUT, 'right': {'c': False, 'st': [{**slot, 'h': 0}]}},
                {**LAYOUT, 'right': {'c': 'yes', 'st': []}}):
            status, body = setting('setDockLayout', 'task-a', 'studio', bad)
            assert status >= 400 or body.get('ok') is False, bad
            assert owner.read_bytes() == before
        status, body = setting('setDockLayout', '../outside', '', LAYOUT)
        assert (status >= 400 or body.get('ok') is False) and owner.read_bytes() == before
        # Reset: the session and its project go back to the default (no stored record).
        status, body = setting('setDockLayout', 'task-a', 'studio', None)
        assert status == 200 and body['result']['dockLayout'] == {'sessions': {'task-b': other}, 'projects': {}}
    finally:
        client.close()
        server.close()


def test_dock_live_rendered(tmp_path, monkeypatch):
    """Compiled Studio on a seeded temporary Workshop: default dock, stack by drag, tab move, collapse, reload, Approve."""
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    import copy
    from nodelang import workshop_tasks
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import catalogue, new_document, write_document
    from nodelang.workshop_mailbox import application_history

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        opened_task = client.workshop('createTask', 'Drawing set review')['taskId']
        waiting_task = client.workshop('createTask', 'Export issue package')['taskId']
        failed_task = client.workshop('createTask', 'Sheet index check')['taskId']
        working_task = client.workshop('createTask', 'Model view audit')['taskId']
        # Waiting for you: a real held run of an approval gate, on another session than the open one.
        view = client.workshop('openTaskGraph', waiting_task)
        original = client.files('read', path=view['path'])['document']
        document = new_document('Export issue package')
        document.update(id=original['id'], properties=original['properties'])
        document['nodes'] = [{'id': 'held', 'type': 'param.value', 'params': {'type': 'number', 'value': 1}, 'position': {'x': 0, 'y': 0}},
                             {'id': 'start', 'type': 'approval.gate', 'params': {}, 'position': {'x': 300, 'y': 0}}]
        client.files('save', path=view['path'], document=document)
        held = client.files('run', path=view['path'], document=document)
        assert held['approvalId']
        # Failed: a step of a third session whose stored run result is an error.
        view = client.workshop('openTaskGraph', failed_task)
        document = client.files('read', path=view['path'])['document']
        document['nodes'].append({'id': 'index', 'type': 'param.value', 'title': 'Read sheet index', 'params': {'type': 'number', 'value': 1},
                                  'position': {'x': 0, 'y': 300}, 'result': {'status': 'Error', 'error': 'The sheet index file was not found.'}})
        write_document(view['path'], document)
        # Working now: a fourth session claimed by an agent.
        with application_history() as history:
            workshop_tasks.claim(history, working_task, 'dock-test-agent', 'Drawing coordinator', lease_seconds=3600)
        # The open canvas: three wired steps.
        items = {row['id']: row for row in catalogue()}
        nodes = [{'id': key, 'item': item, 'type': items[item]['engine'], 'title': items[item]['title'],
                  'params': copy.deepcopy(items[item]['params']), 'position': {'x': x, 'y': 0}}
                 for key, item, x in [('list', 'n_list', 800), ('slice', 's_slice', 1140), ('count', 's_count', 1480)]]
        nodes[0]['params']['value'] = '[10, 20, 30, 40, 50]'
        nodes[1]['params']['count'] = '3'
        view = client.workshop('openTaskGraph', opened_task)
        opened = client.files('read', path=view['path'], id=view['id'])
        opened['document']['nodes'] = [*opened['document']['nodes'], *nodes]
        opened['document']['wires'] = [
            {'id': 'first', 'from': {'node': 'list', 'socket': 'value'}, 'to': {'node': 'slice', 'socket': 'items'}},
            {'id': 'second', 'from': {'node': 'slice', 'socket': 'items_out'}, 'to': {'node': 'count', 'socket': 'items'}}]
        client.files('save', path=view['path'], document=opened['document'])
        client.workshop('openTaskGraph', opened_task)
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/dock_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'shots': os.environ.get('ARCHHUB_DOCK_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        # The decision reached the approval owner, and the last layout change (Reset) reached the Settings owner file.
        card = next(row for row in client.workshop('listApprovals') if row['id'] == held['approvalId'])
        assert card['status'] == 'approved'
        saved = json.loads((state / 'settings' / 'settings.json').read_text(encoding='utf8'))
        assert opened_task not in saved['dockLayout']['sessions']
    finally:
        client.close()
        server.close()
