"""BABOOM's companion window in its own process, started, watched and restarted by the app.

Founder: "BABOOM, why isn't it running outside the program?" The pet window, its timers and its reaction
reads ran on the app launcher's own Qt thread, so its work slowed and could freeze the ArchHub window.
Now the app keeps only its brain (Goose, the Workshop turn door) and one small door on its local server
(/baboom/companion, per-boot token, like /baboom/turn). The companion process asks that door for its
frames and turns, waits there for where the ArchHub window and its composer are, and hands clicks back.
Its crash or hang never reaches the app; with it off the app works the same.

Prior art: mcp_supervisor.Supervisor (hidden child, restarted when it ends) and the /baboom/turn door.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from urllib import error as url_error, parse as url_parse, request as url_request
from pathlib import Path

# Declared parameters of the companion's own process (the repo gate: no timing literals in code).
PROCESS_NODE = {'id': 'baboom.companion.process',
                'params': {'restart_seconds': 1, 'restart_cap_seconds': 30, 'home_wait_seconds': 20,
                           'door_seconds': 30, 'stop_seconds': 3}}
HEADER = 'X-ArchHub-Companion'
_LINK = {'current': None}


def _params():
    return PROCESS_NODE['params']


# ----------------------------------------------------------------------------- app side

class CompanionLink:
    """The app's side: the door's answers, where ArchHub is, and the child process it keeps alive.

    It also stands in for the companion window where the app's CompanionFollows talks to one.
    """

    def __init__(self, state_dir, app_root, url, *, pin=None, ui=None, command=None, environment=None):
        from .baboom_nograph import NoGraphTransport
        self.state_dir, self.app_root, self.url = Path(state_dir), Path(app_root), url
        self.token = secrets.token_urlsafe(32)
        self.transport = NoGraphTransport()
        self.pin = pin  # the app's own companion setting file (server.files['companion'])
        self.ui = ui or (lambda request: None)
        self.command = command
        self.environment = environment
        self.changed = threading.Condition()
        self.revision, self.home, self.commands = 0, None, []
        self.process, self.starts = None, 0
        self.closed = threading.Event()
        self.watcher = None
        _LINK['current'] = self

    # what CompanionFollows calls on a companion window
    def follow_app(self, app, composer=None, busy=(), screens=(), *more, **fields):
        """Where ArchHub is. Further values (needs, listening...) ride along to the companion unchanged."""
        box = lambda rect: [rect.x, rect.y, rect.width, rect.height] if rect is not None else None
        with self.changed:
            self.home = {'app': box(app), 'composer': box(composer), 'busy': [box(r) for r in busy],
                         'screens': [box(r) for r in screens], 'more': list(more), 'fields': fields}
            self.revision += 1
            self.changed.notify_all()

    def isVisible(self):
        return True

    def _disown(self):
        """The ArchHub window was rebuilt: nothing to do, the companion is owned by no app window."""

    def tell(self, name):
        """A command for the companion window (a second launch with --baboom opens its box)."""
        with self.changed:
            self.commands.append(name)
            self.revision += 1
            self.changed.notify_all()

    def running(self):
        return self.process is not None and self.process.poll() is None

    # the door
    def answer(self, body):
        op = body.get('op')
        transport = self.transport
        if op == 'frame':
            return {'ok': True, 'frame': transport.baboom_native_frame()}
        if op == 'bind':
            return {'ok': True, 'result': transport.bind_agent_session(runtime='baboom', external_session_id='',
                                                                       device_credential_provider=None)}
        if op == 'presence':
            return {'ok': True, 'result': transport.renew_runtime_presence()}
        if op in ('respond', 'execute', 'resolve'):
            utterance = body.get('utterance')
            if not isinstance(utterance, str) or len(utterance) > 4000:
                raise ValueError('utterance must be short text')
            method = {'respond': transport.respond_baboom_command, 'execute': transport.execute_baboom_command,
                      'resolve': transport.resolve_baboom_command}[op]
            return {'ok': True, 'result': method(utterance=utterance)}
        if op == 'activity':
            return {'ok': True, 'result': transport.record_baboom_activity(app=str(body.get('app') or '')[:200])}
        if op == 'pin':
            if self.pin is None:
                return {'ok': True, 'result': {}}
            if isinstance(body.get('write'), dict):
                self.pin.update({'pinned': body['write'].get('pinned') is True})
            return {'ok': True, 'result': self.pin.read()}
        if op == 'home':
            after = body.get('after')
            after = after if type(after) is int else -1
            with self.changed:
                self.changed.wait_for(lambda: self.revision != after or self.closed.is_set(), _params()['home_wait_seconds'])
                commands, self.commands = self.commands, []
                return {'ok': True, 'revision': self.revision, 'home': self.home, 'commands': commands,
                        'closed': self.closed.is_set()}
        if op == 'ui':
            # Other fields of a click (words for "ask") pass through to the app's handler unchanged.
            request = {**{key: value for key, value in body.items() if key != 'op'}, 'do': body.get('do'),
                       'task_id': body.get('task_id')}
            if request['do'] not in ('home', 'ask', 'task', 'stopped'):
                raise ValueError('unknown companion request')
            if request['do'] == 'task' and not (type(request['task_id']) is str
                                                 and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request['task_id'])):
                raise ValueError('task_id must be a Workshop task id')
            self.ui(request)
            return {'ok': True}
        raise ValueError('unknown companion operation')

    # the child process
    def spawn(self):
        environment = dict(os.environ if self.environment is None else self.environment)
        environment.update(ARCHHUB_COMPANION_URL=self.url, ARCHHUB_COMPANION_TOKEN=self.token,
                           ARCHHUB_COMPANION_STATE=str(self.state_dir), ARCHHUB_COMPANION_PARENT=str(os.getpid()))
        command = self.command or [sys.executable, '-I', '-B', '-c',
            "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
            "runpy.run_module('nodelang.baboom_companion_process',run_name='__main__')", str(self.app_root)]
        self.process = subprocess.Popen(command, env=environment, cwd=str(self.app_root), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.starts += 1
        return self.process

    def supervise(self):
        """Keep one companion process alive; a crash is restarted after a back-off, never in a tight loop."""
        def watch():
            delay = _params()['restart_seconds']
            while not self.closed.is_set():
                try:
                    started = time.monotonic()
                    with self.changed:  # close() and a restart never cross: a closed link starts nothing
                        if self.closed.is_set():
                            return
                        process = self.spawn()
                    while process.poll() is None and not self.closed.wait(_params()['restart_seconds']):
                        pass
                    if self.closed.is_set():
                        return
                    # A companion that ran a while is restarted promptly; one that keeps dying backs off.
                    delay = (_params()['restart_seconds'] if time.monotonic() - started > _params()['restart_cap_seconds']
                             else min(delay * 2, _params()['restart_cap_seconds']))
                    print('  BABOOM     : companion process ended (%s); restarting' % process.returncode, flush=True)
                except OSError as refused:
                    print('  BABOOM     : companion process could not start (%s)' % refused, flush=True)
                    delay = min(delay * 2, _params()['restart_cap_seconds'])
                self.closed.wait(delay)
        self.watcher = threading.Thread(target=watch, name='archhub-baboom-companion', daemon=True)
        self.watcher.start()
        return self

    def close(self):
        """The app quits: the companion window goes with it."""
        with self.changed:
            self.closed.set()
            self.changed.notify_all()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(_params()['stop_seconds'])
            except subprocess.TimeoutExpired:
                process.kill()
        if _LINK['current'] is self:
            _LINK['current'] = None


def settings_changed():
    """A BABOOM setting was written (Settings): the companion re-reads it now, not at the window's next move."""
    link = _LINK['current']
    if link is not None:
        link.tell('settings')


def door(token, body, *, require_access=None):
    """/baboom/companion on the app's local server: the running link's answer, token-checked."""
    import hmac
    link = _LINK['current']
    if link is None or not hmac.compare_digest(str(token or ''), link.token):
        return {'ok': False, 'error': 'BABOOM companion refused: wrong token.'}
    if not isinstance(body, dict):
        return {'ok': False, 'error': 'BABOOM companion request must be an object.'}
    if require_access is not None:
        require_access()
    if body.get('op') == 'desktop-access':
        return {'ok': True}
    try:
        return link.answer(body)
    except (ValueError, TypeError, KeyError) as refused:
        return {'ok': False, 'error': str(refused)}


# ----------------------------------------------------------------------------- companion side

_OPENER = []


def _door_opener():
    """Loopback only, never a proxy, never a redirect: urllib copies headers (the per-boot credential) to a
    redirect target and sends them through any proxy in the environment.

    Built once and with plain HTTP only: build_opener() adds an HTTPS handler whose SSL context reloads the
    Windows certificate store on every call (27% of a core in the companion, two calls every two seconds)."""

    class Refuse(url_request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, target):
            raise url_error.HTTPError(request.full_url, code, 'BABOOM companion door refuses redirects', headers, None)
    if not _OPENER:
        opener = url_request.OpenerDirector()
        for handler in (url_request.ProxyHandler({}), url_request.HTTPHandler(), url_request.HTTPDefaultErrorHandler(),
                        Refuse(), url_request.HTTPErrorProcessor()):
            opener.add_handler(handler)
        _OPENER.append(opener)
    return _OPENER[0]


def _call(op, **fields):
    url = os.environ['ARCHHUB_COMPANION_URL'].rstrip('/') + '/baboom/companion'
    parsed = url_parse.urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('BABOOM companion door must be the app on this computer')
    request = url_request.Request(url, data=json.dumps({'op': op, **fields}).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json',
                                              HEADER: os.environ['ARCHHUB_COMPANION_TOKEN']})
    with _door_opener().open(request, timeout=_params()['door_seconds']) as response:
        result = json.loads(response.read().decode('utf-8'))
    if not result.get('ok'):
        raise RuntimeError(result.get('error') or 'BABOOM companion request refused')
    return result


class DoorTransport:
    """The companion's transport: every answer comes from the app's door (the app owns the brain)."""

    def __init__(self):
        self.agent_session_root = ''

    def bind_agent_session(self, *, runtime, external_session_id, device_credential_provider):
        result = _call('bind')['result']
        self.agent_session_root = result.get('agent_session', '')
        return result

    def renew_runtime_presence(self):
        return _call('presence')['result']

    def baboom_native_frame(self, *, response_timeout_seconds=None):
        return _call('frame')['frame']

    def respond_baboom_command(self, *, utterance, on_progress=None):
        return _call('respond', utterance=utterance)['result']

    def require_desktop_access(self):
        _call('desktop-access')

    def execute_baboom_command(self, *, utterance):
        return _call('execute', utterance=utterance)['result']

    def resolve_baboom_command(self, *, utterance):
        return _call('resolve', utterance=utterance)['result']

    def record_baboom_activity(self, *, app):
        return _call('activity', app=app)['result']

    def record_baboom_steward_signal(self, *, fingerprint, source, summary):
        return {'signal': 'app:baboom-signal:' + fingerprint}


class _Pin:
    """The companion setting (pinned spot), read and written through the app, which owns the file.

    Kept between reads: BABOOM asks on every redraw. A write here updates it; each word from the app about where
    ArchHub is (the home wait) forgets it, so a change made in Settings is seen at the next move of the window."""

    def __init__(self):
        self.held = None

    def read(self):
        if self.held is None:
            self.held = _call('pin')['result']
        return self.held

    def update(self, values):
        self.held = _call('pin', write=values)['result']
        return self.held

    def forget(self):
        self.held = None


class _NoOwner:
    """No window of another process owns BABOOM: an owner across processes shares input and could freeze ArchHub."""

    def windowHandle(self):
        return None

    def winId(self):
        return 0


def _parent_alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001 - unknown is alive; the door's refusal ends the companion instead
        return True


def _follow_home(window, where):
    from .baboom_companion_placement import Rect

    rect = lambda box: Rect(*box) if box else None
    window.follow_app(rect(where['app']), rect(where['composer']), [rect(b) for b in where['busy'] if b],
                      [rect(b) for b in where['screens'] if b], *where.get('more', ()), **where.get('fields', {}))


def on_screen():
    """Settings › Agents › BABOOM: Shows as Screen and a presence other than Hidden put him on screen."""
    from .settings_owner import agent_setting
    return agent_setting('bbShowsAs') == 'Screen' and agent_setting('bbPresence') != 'Hidden'


def main():
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from .baboom_native_companion import foreground_application_windows
    from .baboom_native_host import BaboomNativeHost
    from .baboom_native_runtime import create_baboom_native_projection, prepare_baboom_native_atlas

    parent = int(os.environ.get('ARCHHUB_COMPANION_PARENT') or 0)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    atlas = prepare_baboom_native_atlas()
    host = BaboomNativeHost(DoorTransport(), external_session_id='founder-desktop-baboom',
                            device_credential_provider=lambda _request: {}, emit_steward_signals=False,
                            activity_provider=foreground_application_windows)
    host.connect()
    def ask(do, task_id=None, **fields):
        threading.Thread(target=_call, args=('ui',), kwargs={'do': do, 'task_id': task_id, **fields}, daemon=True).start()
    state = Path(os.environ['ARCHHUB_COMPANION_STATE'])
    window = create_baboom_native_projection(host, atlas=atlas, position_path=state / 'baboom-position.json',
                                             on_stop=lambda: (host.request_stop(), ask('stopped')),
                                             on_open=lambda: ask('home'),
                                             on_open_task=lambda task_id: ask('task', task_id))
    pin = _Pin()
    window.stand_with(_NoOwner(), pin, lambda words='': ask('ask', words=words))

    class Home(QObject):
        arrived = pyqtSignal(object)
    home = Home()

    def place(reply):
        if reply.get('closed'):
            app.quit()
            return
        where = reply.get('home')
        pin.forget()
        if where is not None:
            _follow_home(window, where)
            if where['app'] is not None and window.isVisible():
                _raise_without_focus(int(window.winId()))
        for command in reply.get('commands') or ():
            if command == 'settings':
                window.refresh()   # the pinned setting was forgotten above; this redraw reads it again
                if not on_screen():
                    window.hide()
                elif not window._stopped and not window.isVisible():
                    window.show()
            if command == 'open' and not window._stopped:
                window.start_projection()
                window._open_interaction()
                window.show()
                window.raise_()
    home.arrived.connect(place)

    def wait_for_home():
        revision = -1
        while True:
            if parent and not _parent_alive(parent):
                home.arrived.emit({'closed': True})
                return
            try:
                reply = _call('home', after=revision)
            except Exception:  # noqa: BLE001 - the app is gone or restarting: this companion ends
                home.arrived.emit({'closed': True})
                return
            revision = reply['revision']
            home.arrived.emit(reply)
            if reply.get('closed'):
                return
    threading.Thread(target=wait_for_home, name='baboom-home', daemon=True).start()
    if on_screen():  # Tray waits for Open (tray or a second launch); Hidden stays out of sight
        window.show()
    window.start_projection()
    host.start()
    code = app.exec()
    from .baboom_reactions import stop_soon
    stop_soon()
    host.request_stop()
    return code


def _raise_without_focus(handle):
    """Above ArchHub, which may just have come to the front, without taking the keyboard."""
    try:
        import ctypes
        HWND_TOP, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0, 0x0001, 0x0002, 0x0010
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(handle), ctypes.c_void_p(HWND_TOP), 0, 0, 0, 0,
                                          SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    except Exception as refused:  # noqa: BLE001 - placement is a courtesy; BABOOM stays where it is
        import logging
        logging.getLogger(__name__).warning("BABOOM could not come forward beside ArchHub: %s", refused)


if __name__ == '__main__':
    raise SystemExit(main())
