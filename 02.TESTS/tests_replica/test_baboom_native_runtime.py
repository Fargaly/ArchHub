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
        _open_launch(['--baboom'], {'window': window}, lambda: opened.append('unexpected'), opened.append)
        assert window.isVisible()
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
    from PyQt6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    class Companion(QWidget):
        _stopped = False
        _shows_as = 'Tray'
        def start_projection(self):
            pass
        def _open_interaction(self):
            pass
    window = Companion()
    home, errors = [], []
    class Launch(QObject):
        requested = pyqtSignal(list)
    launch = Launch()
    launch.requested.connect(lambda args: _open_launch(args, {'window': window},
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
                if (home if not arguments else window.isVisible()):
                    break
                time.sleep(.01)
            assert window.isVisible()
        assert home == ['home']
        assert errors == []
    finally:
        listener.close()
        worker.join(timeout=4)
        window.close()
    assert not worker.is_alive()


def test_unavailable_companion_reports_reason_and_plain_launch_still_opens_home():
    home, errors = [], []
    for companion, reason in (({'error': 'turned off'}, 'turned off'),
                              ({'window': RuntimeError('atlas missing')}, 'atlas missing'),
                              ({'window': SimpleNamespace(_stopped=True)}, 'BABOOM is stopped for this launch.'),
                              ({'window': SimpleNamespace(_stopped=False, _shows_as='Hidden')}, 'BABOOM is hidden in Settings.')):
        result = _open_launch(['--baboom'], companion, lambda: home.append('home'), errors.append)
        assert result == 'BABOOM unavailable: ' + reason
        assert errors[-1] == result
    _open_launch([], {}, lambda: home.append('home'), errors.append)
    assert home == ['home']


def test_task_callback_focuses_same_window_and_dispatches_one_id():
    from nodelang.nograph_launcher import _open_task
    calls, scripts = [], []
    window = SimpleNamespace(showNormal=lambda: calls.append('show'),
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
