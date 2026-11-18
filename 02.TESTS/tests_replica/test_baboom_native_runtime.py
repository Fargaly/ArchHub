"""Courts for dormant packaged BABOOM runtime assembly."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import socket
import subprocess
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from nodelang.baboom_native_runtime import (
    create_baboom_native_projection,
    create_baboom_native_runtime,
    default_baboom_sprite_atlas_path,
)
from nodelang.nograph_launcher import _open_launch


class _Transport:
    def __init__(self) -> None:
        self.agent_session_root = ""
        self.bind_calls = 0

    def bind_agent_session(self, **kwargs):
        self.bind_calls += 1
        raise AssertionError("dormant BABOOM assembly must not bind a session")


def test_packaged_baboom_runtime_uses_the_product_atlas_and_does_not_start():
    app = QApplication.instance() or QApplication([])
    atlas = default_baboom_sprite_atlas_path()
    assert atlas.name == "spritesheet.png"
    transport = _Transport()

    host, window = create_baboom_native_runtime(
        transport,
        external_session_id="baboom-runtime-assembly-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )
    try:
        assert host.running is False
        assert transport.bind_calls == 0
        assert not window.isVisible()
        app.processEvents()
    finally:
        window.close()


def test_projection_passes_open_callback_to_existing_companion(tmp_path):
    from nodelang.baboom_native_runtime import create_baboom_native_host
    app = QApplication.instance() or QApplication([])
    opened = []
    host = create_baboom_native_host(_Transport(), external_session_id='open-court',
        device_credential_provider=lambda challenge: {'proof': 'approved'})
    window = create_baboom_native_projection(host, position_path=tmp_path / 'position.json',
        on_open=lambda: opened.append('home'), on_open_task=opened.append)
    try:
        window._open_archhub()
        app.processEvents()
        assert opened == ['home']
        presence = window._work_presence
        window._work_presence = SimpleNamespace(task_id='task-123')
        window._open_work_task()
        window._work_presence = presence
        assert opened == ['home', 'task-123']
        assert not host.running
    finally:
        window.close()

def _launch_functions():
    source = Path(__file__).resolve().parents[2] / '01.APP/nodelang/launcher.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


def test_second_launch_opens_existing_companion_and_plain_launch_opens_home(tmp_path):
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    told = []    # BABOOM runs in its own process: a second launch with --baboom tells it to open its box
    link = SimpleNamespace(state_dir=tmp_path, running=lambda: True, tell=told.append)
    home, errors = [], []
    class Launch(QObject):
        requested = pyqtSignal(list)
    launch = Launch()
    launch.requested.connect(lambda args: _open_launch(args, {'link': link},
        lambda: home.append('home'), errors.append))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(10)
    worker = threading.Thread(target=_launch_functions()['_serve_launch_requests'],
        args=(listener, launch.requested.emit))
    worker.start()
    script = (
        "import ast,pathlib,sys,psutil; "
        "p=pathlib.Path(sys.argv[1]); "
        "t=ast.parse(p.read_text(encoding='utf-8')); f={}; "
        "exec(compile(ast.Module(body=[n for n in t.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),str(p),'exec'),f); "
        "f['_verified_launch_owner']=lambda port: psutil.Process(int(sys.argv[3])); "
        "assert f['_forward_launch_arguments'](int(sys.argv[2]),sys.argv[4:])"
    )
    try:
        for arguments in (['--baboom'], []):
            child = subprocess.run([sys.executable, '-c', script,
                str(Path(__file__).resolve().parents[2] / '01.APP/nodelang/launcher.py'),
                str(listener.getsockname()[1]), str(os.getpid()), *arguments],
                capture_output=True, timeout=10,
                env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)},
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert child.returncode == 0, child.stderr.decode()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                app.processEvents()
                if (home if not arguments else told):
                    break
                time.sleep(.01)
            assert told == ['open']
        assert home == ['home']
        assert errors == []
    finally:
        listener.close()
        worker.join(timeout=4)
    assert not worker.is_alive()


def test_unavailable_companion_reports_reason_and_plain_launch_still_opens_home(tmp_path):
    home, errors = [], []
    hidden = tmp_path / 'hidden'
    (hidden / 'settings').mkdir(parents=True)
    (hidden / 'settings' / 'baboom.json').write_text('{"shows_as": "Hidden"}', encoding='utf-8')
    link = lambda state, running=True: SimpleNamespace(state_dir=state, running=lambda: running, tell=lambda name: None)
    for companion, reason in (({'error': 'turned off'}, 'turned off'),
                              ({'link': link(tmp_path), 'stopped': True}, 'BABOOM is stopped for this launch.'),
                              ({'link': link(hidden)}, 'BABOOM is hidden in Settings.'),
                              ({'link': link(tmp_path, running=False)}, 'BABOOM is starting.')):
        result = _open_launch(['--baboom'], companion, lambda: home.append('home'), errors.append)
        assert result == 'BABOOM unavailable: ' + reason
        assert errors[-1] == result
    _open_launch([], {}, lambda: home.append('home'), errors.append)
    assert home == ['home']


def test_task_callback_focuses_same_window_and_dispatches_one_id():
    from nodelang.nograph_launcher import _open_task
    calls, scripts = [], []
    window = SimpleNamespace(isMinimized=lambda: False, show=lambda: calls.append('show'),
        raise_=lambda: calls.append('raise'), activateWindow=lambda: calls.append('activate'))
    view = SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=scripts.append))
    task_id = 'task-";\\\n\u2028'
    _open_task(window, view, task_id)
    assert calls == ['show', 'raise', 'activate']
    assert len(scripts) == 1
    result = subprocess.run(['node', '-e', "const window = new EventTarget(); const events = [];"
        "window.addEventListener('archhub:open-task', e => events.push(e.detail));"
        "window.addEventListener('archhub:open-home', () => {throw Error('unexpected Home event')});"
        + scripts[0] + ";process.stdout.write(JSON.stringify(events));"],
        capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [{'task_id': task_id}]
    for invalid in ('', ' ', None, 123):
        import pytest
        with pytest.raises(ValueError, match='No such Workshop task'):
            _open_task(window, view, invalid)
    assert calls == ['show', 'raise', 'activate']
    assert len(scripts) == 1


def test_declared_codex_agents_without_a_transcript_do_not_walk_the_sessions_folder_every_tick(tmp_path, monkeypatch):
    # The installed launcher burned ~96% of a core: BABOOM asks ten times a second, and every ask walked all of
    # ~/.codex/sessions (rglob) for each declared Codex agent that has no transcript yet; a miss was never kept.
    import json, sqlite3, time
    from datetime import datetime, timezone
    from pathlib import Path
    from nodelang import agent_status, baboom_reactions
    from nodelang.user_paths import state_directory
    monkeypatch.setenv('ARCHHUB_AGENT_PROFILE', str(tmp_path / 'home'))
    sessions = tmp_path / 'home' / '.codex' / 'sessions' / '2026' / '11' / '18'
    sessions.mkdir(parents=True)
    for index in range(200):                                    # other agents' rollouts the walk has to pass
        (sessions / ('rollout-other-%d.jsonl' % index)).write_text('{}\n', encoding='utf-8')
    state = state_directory() / 'workshop'
    state.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state / 'messages.sqlite3') as db:
        db.execute('CREATE TABLE workshop_declarations(record TEXT)')
        for index in range(6):
            db.execute('INSERT INTO workshop_declarations VALUES(?)',
                       (json.dumps({'runtime': 'codex', 'native_session_id': 'no-transcript-%d' % index}),))
    walks = []
    real = Path.rglob
    monkeypatch.setattr(Path, 'rglob', lambda self, pattern: walks.append(pattern) or real(self, pattern))
    agent_status._REACTION_FILES.clear()
    agent_status._TRANSCRIPT_INDEX.clear()
    baboom_reactions.latest()
    first = len(walks)
    started = time.process_time()
    for _ in range(50):                                         # five seconds of BABOOM polls
        baboom_reactions.latest()
    print('\nBABOOM transcript walks: first tick %d, next 50 ticks %d; CPU %.3f s'
          % (first, len(walks) - first, time.process_time() - started))
    assert first == 1 and len(walks) == first                   # one walk serves all six; it was 6 more on every tick
    log = sessions / 'rollout-2026-11-18T19-00-00-no-transcript-0.jsonl'
    log.write_text(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started'},
                               'timestamp': datetime.now(timezone.utc).isoformat()}) + '\n', encoding='utf-8')
    later = time.monotonic() - baboom_reactions.REACTION_NODE['params']['active_seconds'] - 1
    agent_status._TRANSCRIPT_INDEX.update({key: (later, files) for key, (_at, files) in agent_status._TRANSCRIPT_INDEX.items()})
    baboom_reactions.latest()                                   # the active window has passed: one walk again
    assert len(walks) == first + 1
    assert any(value[0] == log for value in agent_status._REACTION_FILES.values())   # a transcript that appears is found
    assert agent_status.indexed_transcript('codex', 'no-transcript-0') == log        # the Workshop's status reads it too
