"""Render compiled Studio against real task files in a temporary profile."""
import json
import os
from pathlib import Path
import subprocess
import pytest

from test_task_session_roundtrip import _isolate, _Studio


@pytest.mark.parametrize("board", ["home", "workshop"])
def test_designbuild_board(tmp_path, monkeypatch, board):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer

    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        task = client.workshop('createTask', 'Drawing set review')
        client.workshop('setTaskSession', task['taskId'], {
            'scope': 'Review and export the drawing set', 'rules': ['Review before export'],
            'agents': ['Drawing coordinator'], 'folders': ['Dated issue folder'],
            'references': ['Drawing index'], 'plan': ['Read sheet index', 'Review drawings', 'Export PDF'],
            'progress': {'Read sheet index': 'done', 'Review drawings': 'done'},
            'messages': [{'id':'review-complete','who':'Drawing coordinator','text':'Review is complete. The drawing index matches the reviewed set.'},{'id':'ask-export','who':'You','text':'What is holding up the export?'}],
        })
        for title in ['Sheet index check', 'Export issue package', 'Update drawing references', 'Model view audit']:
            client.workshop('createTask', title)
        client.workshop('openTaskGraph', task['taskId'])
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/designbuild.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token,
                              'browserCache': browser_cache, 'board': board}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
            encoding='utf-8', timeout=120,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        reopened = client.workshop('openTaskGraph', task['taskId'])
        assert reopened['scope'] == 'Review the current issue'
        assert reopened['rules'] == ['Review every sheet before export']
        assert reopened['references'] == ['Current drawing index']
        assert reopened['folders'] == ['Dated issue folder renamed']
        if board == 'home':
            assert json.loads((state / 'settings' / 'settings.json').read_text(encoding='utf8'))['homeLayout']['inner']['params'] == 30
    finally:
        client.close()
        server.close()
