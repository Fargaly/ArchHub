"""Exercise the installed launcher's exact close path with fake Qt objects."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import time


ROOT = Path(__file__).resolve().parents[2]


def test_window_close_requests_quit_and_arms_a_bounded_watchdog(monkeypatch):
    source = ast.parse((ROOT / '01.APP/nodelang/launcher.py').read_text(encoding='utf-8'))
    definitions = [next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == '_quit_from_window'),
        next(n for n in ast.walk(source) if isinstance(n, ast.ClassDef) and n.name == '_ArchHubWindow')]
    definitions += [node for node in source.body if isinstance(node, ast.FunctionDef)
                    and node.name in ('_launcher_parameter', '_launcher_seconds')]
    callbacks, timers, sleeps, exits = [], [], [], []
    class FakeThread:
        def __init__(self, *, target, daemon):
            assert daemon is True
            callbacks.append(target)
        def start(self):
            pass
    class FakeWindow:
        deleted = 0
        def hide(self):
            raise AssertionError('window close must never hide to tray')
        def deleteLater(self):
            self.deleted += 1
    class FakeApp:
        closes = quits = 0
        def closeAllWindows(self):
            self.closes += 1
        def topLevelWidgets(self):
            return [window]
        def quit(self):
            self.quits += 1
    app = FakeApp()
    namespace = dict(QMainWindow=FakeWindow, app=app, _hide_in_tray_if_enabled=lambda widget: False,
        QTimer=SimpleNamespace(singleShot=lambda delay, callback: timers.append((delay, callback))),
        os=SimpleNamespace(_exit=lambda code: exits.append(code)), _window_quit_started={'value': False})
    monkeypatch.setattr(threading, 'Thread', FakeThread)
    monkeypatch.setattr(time, 'sleep', lambda duration: sleeps.append(duration))
    exec(compile(ast.Module(body=definitions, type_ignores=[]), 'installed-close-path', 'exec'), namespace)
    window = namespace['_ArchHubWindow']()
    events = []
    window.closeEvent(SimpleNamespace(accept=lambda: events.append('accepted')))
    assert events == ['accepted'] and window.quitting is True
    assert app.closes == 1 and window.deleted == 1
    assert len(timers) == 1 and timers[0][0] == 0
    timers[0][1]()
    assert app.quits == 1 and len(callbacks) == 1
    namespace['_launcher_seconds'] = lambda key: (_ for _ in ()).throw(AssertionError('shutdown reread a closed store'))
    callbacks[0]()
    assert sleeps == [3.0] and exits == [0]
    window.closeEvent(SimpleNamespace(accept=lambda: events.append('accepted')))
    assert app.closes == 1 and len(callbacks) == 1
