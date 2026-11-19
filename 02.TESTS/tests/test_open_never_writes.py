"""Opening a saved workflow on the Canvas changes nothing on disk; only his own edit, Tidy up or Save writes it, and an
edit never writes an arrangement over his saved places."""
import copy
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio


def test_opening_the_canvas_keeps_the_file_and_his_tidy_up_saves(tmp_path, monkeypatch):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import catalogue

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        task = client.workshop('createTask', 'Drawing set review')['taskId']
        items = {row['id']: row for row in catalogue()}
        nodes = [{'id': key, 'item': item, 'type': items[item]['engine'], 'title': items[item]['title'],
                  'params': copy.deepcopy(items[item]['params']), 'position': {'x': x, 'y': 0}}
                 # Cards close together and no canvasLayout: still shown and kept exactly where they were saved.
                 for key, item, x in [('list', 'n_list', 800), ('slice', 's_slice', 860), ('count', 's_count', 920)]]
        view = client.workshop('openTaskGraph', task)
        opened = client.files('read', path=view['path'], id=view['id'])
        opened['document']['nodes'] = [*opened['document']['nodes'], *nodes]
        opened['document']['wires'] = [
            {'id': 'first', 'from': {'node': 'list', 'socket': 'value'}, 'to': {'node': 'slice', 'socket': 'items'}},
            {'id': 'second', 'from': {'node': 'slice', 'socket': 'items_out'}, 'to': {'node': 'count', 'socket': 'items'}}]
        client.files('save', path=view['path'], document=opened['document'])
        client.workshop('openTaskGraph', task)
        path = Path(view['path'])
        before, stamp = path.read_bytes(), path.stat().st_mtime_ns
        assert 'canvasLayout' not in json.loads(before)['properties']

        def studio(step):
            result = subprocess.run(
                ['node', '02.TESTS/tests_js/open_never_writes.cjs'],
                input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache, 'step': step}),
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=120,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            print(result.stdout)
            assert result.returncode == 0, result.stdout + result.stderr

        studio('open')
        assert path.read_bytes() == before and path.stat().st_mtime_ns == stamp, 'opening the Canvas wrote the saved workflow'
        places = {node['id']: node['position'] for node in json.loads(before)['nodes']}
        studio('edit')
        edited = json.loads(path.read_bytes())
        assert {node['id']: node['position'] for node in edited['nodes']} == places, 'an edit moved saved places'
        assert 'canvasLayout' not in edited['properties'], 'an edit wrote an arrangement'
        assert next(node for node in edited['nodes'] if node['id'] == 'slice')['params']['count'] == 3, 'the edit reached the file'
        studio('arrange')
        saved = json.loads(path.read_bytes())
        assert saved['properties']['canvasLayout'] == 'v48'
        placed = {node['id']: node['position'] for node in saved['nodes']}
        assert placed['list'] != {'x': 800, 'y': 0}, 'his Tidy up reached the file'
    finally:
        client.close()
        server.close()
