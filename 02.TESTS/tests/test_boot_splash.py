"""The splash goes when sign-in, the commands and the first file are in; the Library catalogue loads after it.

Founder build 20261118-1419: the first cold start held "Starting ArchHub" for 17 s while the app was drawn under it from 2 s;
the splash waited for the Library catalogue, which reads every saved session file. Here a profile holds 200 real session
files and the catalogue answers only after the page has shown the Library's loading state.
"""
import json
import os
from pathlib import Path
import subprocess
import threading

from test_task_session_roundtrip import _isolate, _Studio

SESSIONS = 200


def test_the_splash_never_waits_for_the_library(tmp_path, monkeypatch):
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang import session_files
    from nodelang.nograph_server import NoGraphServer

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    # The catalogue answers only once the page says the Library is loading (or after the bound, so a hang still ends).
    release, catalogue = threading.Event(), session_files.catalogue
    monkeypatch.setattr(session_files, 'catalogue', lambda: (release.wait(120), catalogue())[1])
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        first = None
        for index in range(SESSIONS):
            task = client.workshop('createTask', 'Sheet check %03d for the issue set' % index)['taskId']
            first = first or task
        assert len(list(session_files.sessions_directory().glob('*.archhub'))) >= SESSIONS
        node = subprocess.Popen(['node', '02.TESTS/tests_js/boot_splash.cjs'], cwd=Path(__file__).resolve().parents[2],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        node.stdin.write(json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                                     'shots': os.environ.get('ARCHHUB_HOME_SHOTS', '')}))
        node.stdin.close()
        said = []
        for line in node.stdout:
            said.append(line)
            if line.startswith('LIBRARY LOADING SHOWN'):
                release.set()
        error = node.stderr.read()
        assert node.wait(240) == 0, ''.join(said) + error
        assert any(line.startswith('OK') for line in said), ''.join(said)
    finally:
        release.set()
        client.close()
        server.close()
