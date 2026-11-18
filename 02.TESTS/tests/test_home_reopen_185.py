"""React error 185 (installed 20261118-1419 and 1857): a session opening with its thread while the Library is hidden.

The compiled Studio on a fresh, unseeded temporary profile (so the rail's Canvas is the standalone Canvas with its bar's
Library button). Both reproducers end in "Could not open this view" on the old Home code.
"""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio


def test_a_session_opens_with_its_thread_without_the_error_screen(tmp_path, monkeypatch):
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
            ['node', '02.TESTS/tests_js/home_reopen_185.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'shots': os.environ.get('ARCHHUB_HOME_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        client.close()
        server.close()
