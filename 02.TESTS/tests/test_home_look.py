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


def test_the_companion_never_waits_for_the_reaction_read(monkeypatch):
    """latest() reads the Workshop file and every transcript tail (over a second with 19 writing sessions): the
    companion asks through latest_soon(), which answers at once and reads in one worker thread."""
    import threading
    from nodelang import baboom_reactions
    started, release, reads = threading.Event(), threading.Event(), []

    def slow_read():
        reads.append(1)
        started.set()
        release.wait(10)
        return 'read %d' % len(reads)
    monkeypatch.setattr(baboom_reactions, 'latest', slow_read)
    monkeypatch.setitem(baboom_reactions._SOON, 'value', None)
    assert baboom_reactions.latest_soon() is None and started.wait(10)
    assert baboom_reactions.latest_soon() is None and len(reads) == 1, 'a second ask does not start a second read'
    release.set()
    for _ in range(500):
        if baboom_reactions._SOON['value'] is not None:
            break
        threading.Event().wait(.01)
    assert str(baboom_reactions.latest_soon()).startswith('read ')
    # A raising read is logged and answered as "no reaction" by the same worker; the app's close ends that worker.
    worker = baboom_reactions._SOON['worker']
    monkeypatch.setattr(baboom_reactions, 'latest', lambda: 1 / 0)
    for _ in range(500):
        if baboom_reactions.latest_soon() is None:
            break
        threading.Event().wait(.01)
    assert baboom_reactions.latest_soon() is None and 'ZeroDivisionError' in baboom_reactions._SOON['failure']
    assert baboom_reactions._SOON['worker'] is worker and worker.is_alive(), 'a raising read does not start a new thread'
    baboom_reactions.stop_soon()
    worker.join(10)
    assert not worker.is_alive(), 'the worker stops when the app closes'


def test_reopening_keeps_a_maximised_window_maximised():
    """The tray's Open, a second launch, BABOOM and a task link bring the window back as he left it."""
    from types import SimpleNamespace
    from PyQt6.QtCore import Qt
    from nodelang.window_commands import show_again
    calls = []
    state = Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized
    window = SimpleNamespace(isMinimized=lambda: True, windowState=lambda: state, setWindowState=calls.append, show=lambda: calls.append('show'))
    show_again(window)
    assert calls == [Qt.WindowState.WindowMaximized, 'show'], 'a minimised window comes back maximised if it was'
    calls.clear()
    show_again(SimpleNamespace(isMinimized=lambda: False, show=lambda: calls.append('show')))
    assert calls == ['show'], 'a window in the tray is shown as it was hidden: never showNormal()'


def test_home_look_rendered(tmp_path, monkeypatch):
    """1009, 1440 and 1920: Home is the map of the work between the docks; its values are parameters; the header acts."""
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
        source_task = client.workshop('createTask', 'Sheet index check')['taskId']
        # The echo session: its one plan step is named like the session itself.
        view = client.workshop('openTaskGraph', echo_task)
        document = client.files('read', path=view['path'])['document']
        document['properties'].setdefault('taskContext', {})['plan'] = [echo]
        write_document(view['path'], document)
        # A real input link: the echo session takes the sheet index session's output, so the map draws one wire.
        source = client.workshop('openTaskGraph', source_task)
        source_id = client.files('read', path=source['path'])['document']['id']
        status, body = _post(client.connection, '/api/session-model', {'action': 'set', 'path': view['path'], 'values': {'inputLinks': [
            {'source': {'path': Path(source['path']).name, 'id': source_id}, 'output': 'index.value', 'input': 'sheets'}]}}, client.headers)
        assert status == 200 and body['ok'], body
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
                              'echo': echo, 'echoTask': echo_task, 'other': 'Sheet index check', 'shots': os.environ.get('ARCHHUB_HOME_SHOTS', '')}),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=240,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        # The map's parameters were written through the Home owner into the one settings file.
        saved = json.loads((state / 'settings' / 'settings.json').read_text(encoding='utf8'))
        assert set(saved['homeLayout']['map']) <= {'group', 'order', 'card', 'density', 'done', 'filter', 'collapsed'} and saved['homeLayout']['map']
    finally:
        client.close()
        server.close()
