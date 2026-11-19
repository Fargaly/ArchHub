"""DESIGNCANVAS: the Flow view's owner, and the Canvas rows of the approved design in the compiled Studio."""
import copy
import json
import os
from pathlib import Path
import subprocess

import psutil
import pytest

from test_task_session_roundtrip import _isolate, _Studio


class _Held:
    """The Settings owner file, in memory."""
    def __init__(self):
        self.values = {}

    def read(self):
        return copy.deepcopy(self.values)

    def update(self, values):
        self.values.update(copy.deepcopy(values))


def test_flow_view_is_kept_on_its_open_tab_and_refuses_a_value_that_is_not_on_or_off():
    from nodelang.settings_owner import canvas_tabs
    held = _Held()
    plain = {'tabs': [{'id': 'one', 'kept': True}, {'id': 'two', 'kept': False}], 'active': 'one', 'split': '', 'collapsed': False}
    assert canvas_tabs('setCanvasTabs', [plain], settings=held)['canvasTabs'] == plain, 'a tab without the Flow view is unchanged'
    flow = {**plain, 'tabs': [{'id': 'one', 'kept': True, 'flow': True}, {'id': 'two', 'kept': False}]}
    assert canvas_tabs('setCanvasTabs', [flow], settings=held)['canvasTabs'] == flow
    assert canvas_tabs(settings=held)['canvasTabs']['tabs'][0]['flow'] is True
    for bad in ({**plain, 'tabs': [{'id': 'one', 'kept': True, 'flow': 'yes'}]},
                {**plain, 'tabs': [{'id': 'one', 'kept': True, 'view': 'flow'}]}):
        with pytest.raises(ValueError):
            canvas_tabs('setCanvasTabs', [bad], settings=held)
    assert canvas_tabs(settings=held)['canvasTabs'] == flow, 'a refused write changes nothing'


def test_design_canvas_rows_rendered(tmp_path, monkeypatch):
    """Compiled Studio on a seeded temporary Workshop at 1009, 1440 and 1920."""
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import workshop_tasks
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import catalogue
    from nodelang.workshop_mailbox import application_history

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        opened_task = client.workshop('createTask', 'Drawing set review')['taskId']
        working_task = client.workshop('createTask', 'Model view audit')['taskId']
        with application_history() as history:
            workshop_tasks.claim(history, working_task, 'canvas-test-agent', 'Drawing coordinator', lease_seconds=3600)
            # Row 12: an agent declared working on the other task right now (a live process: this one), so the toolbar pill must show it.
            with history._transaction(write=True):
                history._db.execute('CREATE TABLE IF NOT EXISTS workshop_declarations(root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT')
                history._db.execute('INSERT INTO workshop_declarations VALUES(?,?)', ('canvas-test-root', json.dumps({
                    'root': 'canvas-test-root', 'agent': 'Wall checker', 'display_name': 'Wall checker', 'session': 'canvas-test-session',
                    'status': 'working', 'runtime': 'codex', 'request_id': working_task, 'pid': os.getpid(), 'created_at': psutil.Process().create_time()})))
        items = {row['id']: row for row in catalogue()}
        nodes = [{'id': key, 'item': item, 'type': items[item]['engine'], 'title': items[item]['title'],
                  'params': copy.deepcopy(items[item]['params']), 'position': {'x': x, 'y': 0}}
                 for key, item, x in [('list', 'n_list', 800), ('slice', 's_slice', 1140), ('count', 's_count', 1480)]]
        nodes[0]['params']['value'] = '[10, 20, 30, 40, 50]'
        nodes[1]['params']['count'] = '3'
        # Row 11: a step really running for the session's named agent carries that agent's presence chip.
        nodes[1]['result'] = {'status': 'Running'}
        view = client.workshop('openTaskGraph', opened_task)
        opened = client.files('read', path=view['path'], id=view['id'])
        for node in opened['document']['nodes']:
            if node['type'] == 'thing.agent':
                node['params']['agent'] = 'Drawing coordinator'
        opened['document']['nodes'] = [*opened['document']['nodes'], *nodes]
        opened['document']['wires'] = [
            {'id': 'first', 'from': {'node': 'list', 'socket': 'value'}, 'to': {'node': 'slice', 'socket': 'items'}},
            {'id': 'second', 'from': {'node': 'slice', 'socket': 'items_out'}, 'to': {'node': 'count', 'socket': 'items'}}]
        client.files('save', path=view['path'], document=opened['document'])
        # Row 11: the other session has one step waiting for approval, on the same named agent.
        other = client.workshop('openTaskGraph', working_task)
        held = client.files('read', path=other['path'], id=other['id'])
        for node in held['document']['nodes']:
            if node['type'] == 'thing.agent':
                node['params']['agent'] = 'Drawing coordinator'
        waiting = copy.deepcopy(nodes[2])
        waiting['result'] = {'status': 'Waiting for approval'}
        held['document']['nodes'] = [*held['document']['nodes'], waiting]
        client.files('save', path=other['path'], document=held['document'])
        client.workshop('openTaskGraph', opened_task)
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/design_canvas_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'shots': os.environ.get('ARCHHUB_DESIGN_CANVAS_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=300,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        # What the screen changed is in the owner's own file: the Flow view on the open tab, switched off again.
        saved = json.loads((state / 'settings' / 'settings.json').read_text(encoding='utf8'))
        tab = next(row for row in saved['canvasTabs']['tabs'] if row['id'] == opened_task)
        assert tab.get('flow', False) is False, 'the test left the Flow view off'
    finally:
        client.close()
        server.close()
