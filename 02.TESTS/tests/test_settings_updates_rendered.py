"""Settings -> System -> Updates in the compiled Studio on an isolated server (installed 20261118-1857 showed no button)."""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate


class _StubUpdate:
    """Stands in for ApplicationUpdate: the route is real, the release feed is never contacted."""

    def __init__(self):
        self.checks = 0

    def status(self):
        return {"ok": True, "current_build": "isolated-build", "state": "idle", "available_build": None,
                "detail": "Stub feed: up to date (%d checks)" % self.checks, "restart_refusal": None,
                "restart_supported": False, "updated_from": None, "updated_to": None}

    def check(self):
        self.checks += 1
        return self.status()


def test_settings_updates_check_reaches_the_update_route(tmp_path, monkeypatch):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    monkeypatch.setenv('WORKSHOP_STATE_DIR', str(tmp_path / 'desk' / 'workshop'))
    from nodelang.nograph_server import NoGraphServer

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    server = NoGraphServer(state).start()
    stub = _StubUpdate()
    try:
        assert server.application_update is None, 'an isolated server has no update lifecycle'
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/settings_updates.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'shots': os.environ.get('ARCHHUB_SETTINGS_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.close()

    # Second pass with the stub owner: each width's click reaches update.check() once.
    server = NoGraphServer(state).start()
    server.application_update = stub
    try:
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/settings_updates.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'stub': True, 'shots': os.environ.get('ARCHHUB_SETTINGS_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        assert stub.checks == 2, 'one check per width reached the update route'
    finally:
        server.close()
