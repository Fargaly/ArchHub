"""Settings › Account, Connections and Projects on the compiled Studio and a real isolated server: no row is held."""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate


def test_settings_account_connections_projects_have_no_coming_soon(tmp_path, monkeypatch):
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
    try:
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/settings_areas_live.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'shots': os.environ.get('ARCHHUB_SETTINGS_SHOTS', ''), 'probe': bool(os.environ.get('ARCHHUB_SETTINGS_PROBE'))}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=600,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        if not os.environ.get('ARCHHUB_SETTINGS_PROBE'):
            saved = json.loads((state / 'settings' / 'settings.json').read_text(encoding='utf-8'))
            assert saved['sound'] is True and saved['surveyE'] == '1250.5', 'the clicks reached the one owner file'
    finally:
        server.close()
