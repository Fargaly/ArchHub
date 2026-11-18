"""Home as the founder saw it wrong (installed 20261117-2144): the compiled Studio on a seeded temporary Workshop."""
import json
import os
from pathlib import Path
import subprocess

from test_task_session_roundtrip import _isolate, _Studio, _post


def test_baboom_reaction_lines_are_whole_sentences():
    """A bubble says who is doing what; one word ("Testing.") reads as a debug label."""
    from nodelang.baboom_persona import safe_speech
    from nodelang.baboom_reactions import REACTIONS
    for kind, (_motion, text) in REACTIONS.items():
        assert safe_speech(text), kind
        assert text.startswith('An agent ') and text.endswith('.') and len(text.split()) >= 4, (kind, text)


def test_home_look_rendered(tmp_path, monkeypatch):
    """1009, 1440 and 1920: full width, composer in the work column, no raw id or cut word, a title once, one update state."""
    browser_cache = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')
    if not browser_cache:
        browser_cache = subprocess.check_output(['node', '-p', "require('node:path').join(require('node:os').userInfo().homedir,'AppData/Local/ms-playwright')"], text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    _isolate(monkeypatch, tmp_path / 'desk')
    from nodelang.nograph_server import NoGraphServer
    from nodelang.session_files import new_document, write_document

    monkeypatch.setattr(NoGraphServer, '_probe_hosts', staticmethod(lambda: []))
    state = tmp_path / 'desk' / 'LOCALAPPDATA' / 'ArchHub'
    state.mkdir()
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(state))
    server = NoGraphServer(state).start()
    client = _Studio(server)
    try:
        echo = 'Check the model against the office standard'
        echo_task = client.workshop('createTask', echo)['taskId']
        waiting_task = client.workshop('createTask', 'Export issue package')['taskId']
        client.workshop('createTask', 'Sheet index check')
        # The echo session: its one plan step is named like the session itself.
        view = client.workshop('openTaskGraph', echo_task)
        document = client.files('read', path=view['path'])['document']
        document['properties'].setdefault('taskContext', {})['plan'] = [echo]
        write_document(view['path'], document)
        # Needs you: a real held run of an approval gate on another session.
        view = client.workshop('openTaskGraph', waiting_task)
        original = client.files('read', path=view['path'])['document']
        document = new_document('Export issue package')
        document.update(id=original['id'], properties=original['properties'])
        document['nodes'] = [{'id': 'held', 'type': 'param.value', 'params': {'type': 'number', 'value': 1}, 'position': {'x': 0, 'y': 0}},
                             {'id': 'start', 'type': 'approval.gate', 'params': {}, 'position': {'x': 300, 'y': 0}}]
        client.files('save', path=view['path'], document=document)
        assert client.files('run', path=view['path'], document=document)['approvalId']
        # The Home owner's record selects the echo session at every width (the list folds to avatars below 1100).
        status, body = _post(client.connection, '/api/universal/settings-action', {'function': 'setHomeLayout', 'args': [
            {'width': 300, 'collapsed': False, 'resume': echo_task, 'order': [], 'hidden': []}]}, client.headers)
        assert status == 200 and body['ok'], body
        result = subprocess.run(
            ['node', '02.TESTS/tests_js/home_look.cjs'],
            input=json.dumps({'url': server.public_url, 'cookie': server._cookie_token, 'browserCache': browser_cache,
                              'echo': echo, 'echoTask': echo_task, 'shots': os.environ.get('ARCHHUB_HOME_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        client.close()
        server.close()
