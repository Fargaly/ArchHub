"""One client, one canvas: an edit made while an autosave is in flight is saved with no "changed elsewhere" conflict."""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio


def test_edit_during_inflight_autosave_saves_without_conflict_rendered(tmp_path, monkeypatch):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        task = client.workshop('createTask', 'Save race')['taskId']
        view = client.workshop('openTaskGraph', task)
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/canvas_save_race_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache, 'task': task}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=180,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        # The file on disk holds the edit made during the first save.
        node = next(line for line in result.stdout.splitlines() if line.startswith('SAVED_NODE='))[len('SAVED_NODE='):]
        saved = client.files('read', path=view['path'])['document']
        assert next(row for row in saved['nodes'] if row['id'] == node)['position'] == {'x': 520, 'y': 260}
    finally:
        client.close()
        server.close()
