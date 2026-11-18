"""Design v63: the Canvas Library is in its dock by default and one click shows or hides it (compiled Studio, fresh temporary profile)."""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio


def test_library_open_by_default_and_one_click_rendered(tmp_path, monkeypatch):
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
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/library_reach_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'shots': os.environ.get('ARCHHUB_LIBRARY_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        client.close()
        server.close()
