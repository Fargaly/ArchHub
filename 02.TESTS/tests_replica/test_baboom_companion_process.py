"""Founder: "BABOOM, why isn't it running outside the program?" The companion is its own process: the app starts it,
answers it through one door on its local server, restarts it when it dies, and is unaffected when it is off or dead."""
import json
import sys
import threading
import time
import urllib.request

import psutil

# The companion stand-in: asks the app's door for a frame the way the real host does, then keeps running.
CHILD = (
    "import json,os,time,urllib.request;"
    "r=urllib.request.Request(os.environ['ARCHHUB_COMPANION_URL']+'/baboom/companion',"
    "data=json.dumps({'op':'frame'}).encode(),method='POST',"
    "headers={'Content-Type':'application/json','X-ArchHub-Companion':os.environ['ARCHHUB_COMPANION_TOKEN']});"
    "assert json.load(urllib.request.urlopen(r,timeout=10))['ok'];"
    "open(os.environ['MARK'],'a').write('%d\\n'%os.getpid());"
    "time.sleep(600)"
)


def _server(tmp_path):
    from nodelang.nograph_server import NoGraphServer
    server = NoGraphServer(tmp_path / 'server')
    server.thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    server.thread.start()
    return server


def _post(server, body, token):
    request = urllib.request.Request(server.public_url + '/baboom/companion', data=json.dumps(body).encode(),
                                     method='POST', headers={'Content-Type': 'application/json', 'X-ArchHub-Companion': token})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def _alive(server):
    """The app answering on its own: its liveness route, timed."""
    started = time.monotonic()
    with urllib.request.urlopen(server.public_url + '/api/alive', timeout=10) as response:
        assert response.status == 204
    return time.monotonic() - started


def test_the_door_answers_only_its_own_companion_and_hands_clicks_to_the_app(tmp_path):
    from nodelang.baboom_companion_process import CompanionLink
    server = _server(tmp_path)
    asked = []
    link = CompanionLink(tmp_path / 'server', tmp_path, server.public_url, pin=server.files['companion'], ui=asked.append)
    try:
        assert _post(server, {'op': 'frame'}, 'wrong')['ok'] is False
        frame = _post(server, {'op': 'frame'}, link.token)
        assert frame['ok'] and frame['frame']['directive']['motion'] in ('idle', 'working')
        assert _post(server, {'op': 'ui', 'do': 'task', 'task_id': 't-1'}, link.token)['ok']
        assert asked == [{'do': 'task', 'task_id': 't-1'}]
        assert _post(server, {'op': 'ui', 'do': 'format the disk'}, link.token)['ok'] is False
        assert _post(server, {'op': 'ui', 'do': 'task', 'task_id': 'x"));alert(1)//'}, link.token)['ok'] is False
        assert asked == [{'do': 'task', 'task_id': 't-1'}]          # a bad task id never reaches the app window
        assert _post(server, {'op': 'pin', 'write': {'pinned': True}}, link.token)['result']['pinned'] is True
        assert server.files['companion'].read()['pinned'] is True   # the app's own setting file holds it
        from nodelang.baboom_companion_placement import Rect
        replies = []
        waiter = threading.Thread(target=lambda: replies.append(_post(server, {'op': 'home', 'after': link.revision}, link.token)))
        waiter.start()
        time.sleep(0.2)
        link.follow_app(Rect(10, 20, 800, 600), Rect(30, 500, 400, 60), (), [Rect(0, 0, 1920, 1080)])
        link.tell('open')
        waiter.join(10)
        assert replies[0]['home']['app'] == [10, 20, 800, 600] and replies[0]['commands'] == ['open']
    finally:
        link.close()
        server.close()


def test_a_dead_companion_is_restarted_and_the_app_never_waits_on_it(tmp_path):
    from nodelang.baboom_companion_process import CompanionLink, PROCESS_NODE
    server = _server(tmp_path)
    mark = tmp_path / 'started.txt'
    link = CompanionLink(tmp_path / 'server', tmp_path, server.public_url, pin=server.files['companion'],
                         command=[sys.executable, '-c', CHILD], environment={**__import__('os').environ, 'MARK': str(mark)})
    try:
        link.supervise()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (mark.is_file() and mark.read_text().split()):
            time.sleep(0.1)
        first = int(mark.read_text().split()[0])
        assert psutil.pid_exists(first)
        psutil.Process(first).kill()                        # BABOOM crashes
        assert _alive(server) < 1                           # the app answers at once, as before
        deadline = time.monotonic() + PROCESS_NODE['params']['restart_cap_seconds'] + 20
        while time.monotonic() < deadline and len(mark.read_text().split()) < 2:
            assert _alive(server) < 1
            time.sleep(0.2)
        second = int(mark.read_text().split()[1])
        assert second != first and psutil.pid_exists(second)   # the app started it again
        frozen = psutil.Process(second)
        frozen.suspend()                                    # BABOOM hangs
        try:
            for _ in range(5):
                assert _alive(server) < 1                   # the app does not wait on it
        finally:
            frozen.resume()
    finally:
        link.close()
        server.close()
    time.sleep(0.5)
    assert not psutil.pid_exists(second) or psutil.Process(second).status() == psutil.STATUS_ZOMBIE   # it ends with the app


def test_the_companion_never_sends_its_credential_to_a_redirect_or_a_proxy_or_off_this_computer(monkeypatch):
    # Review finding: urllib follows 301/302/303 (as a GET) and copies custom headers, the per-boot credential among
    # them, to the new target; it also sends them through any proxy named in the environment.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import pytest
    from nodelang import baboom_companion_process as process
    seen = []

    class Recorder(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(dict(self.headers))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok": true, "frame": {}}')
        do_GET = do_POST

        def log_message(self, *args):
            pass
    elsewhere = ThreadingHTTPServer(('127.0.0.1', 0), Recorder)
    status = {'code': 302}

    class Redirects(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(status['code'])
            self.send_header('Location', 'http://127.0.0.1:%d/baboom/companion' % elsewhere.server_port)
            self.end_headers()
        do_GET = do_POST

        def log_message(self, *args):
            pass
    door = ThreadingHTTPServer(('127.0.0.1', 0), Redirects)
    for server in (elsewhere, door):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv('ARCHHUB_COMPANION_TOKEN', 'per-boot-secret')
        for name in ('NO_PROXY', 'no_proxy', 'HTTP_PROXY', 'http_proxy'):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv('ARCHHUB_COMPANION_URL', 'http://127.0.0.1:%d' % door.server_port)
        for code in (301, 302, 303, 307, 308):
            status['code'] = code
            with pytest.raises(Exception):
                process._call('frame')                      # fails closed
            assert seen == [], code                         # nothing, and no credential, reached the redirect target
        # A proxy in the environment: the door is called directly, never through it.
        monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:%d' % elsewhere.server_port)
        monkeypatch.setenv('ARCHHUB_COMPANION_URL', 'http://127.0.0.1:%d' % door.server_port)
        status['code'] = 302
        with pytest.raises(Exception):
            process._call('frame')
        assert seen == []                                   # the recording proxy got nothing
        monkeypatch.setenv('ARCHHUB_COMPANION_URL', 'http://example.com')
        with pytest.raises(RuntimeError, match='this computer'):
            process._call('frame')
    finally:
        for server in (elsewhere, door):
            server.shutdown()
            server.server_close()


def test_a_click_into_archhub_tells_baboom_to_come_back_above_it():
    # BABOOM runs in its own process and no ArchHub window owns it: activating ArchHub (a click into it, Alt+Tab)
    # must tell it where ArchHub is again, so it raises itself above the window without taking the keyboard.
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from types import SimpleNamespace
    from PyQt6.QtCore import QEvent, QObject, QUrl
    from PyQt6.QtWidgets import QApplication, QWidget
    from nodelang.window_commands import CompanionFollows, WindowCommands
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setGeometry(100, 100, 800, 600)
    window.show()
    app.processEvents()
    page = QObject()
    view = SimpleNamespace(page=lambda: page, url=lambda: QUrl('http://127.0.0.1:1234/studio'),
                           urlChanged=SimpleNamespace(connect=lambda _f: None), mapToGlobal=window.mapToGlobal,
                           zoomFactor=lambda: 1.0)
    told = []
    companion = SimpleNamespace(follow_app=lambda *state: told.append(state), isVisible=lambda: False)
    follows = CompanionFollows(window, view, WindowCommands(view, window, lambda: None, 'http://127.0.0.1:1234'), companion)
    try:
        before = len(told)
        app.sendEvent(window, QEvent(QEvent.Type.WindowActivate))
        assert len(told) == before + 1 and told[-1][0] is not None   # told again, with the window's place
    finally:
        del follows
        window.close()
