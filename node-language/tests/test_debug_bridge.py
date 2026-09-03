"""Tests for the in-app debug bridge (app/debug_bridge.py).

The debug bridge is a founder-approved, COMPLEMENTARY zero-DevTools proof
path: a tiny loopback HTTP server that lets an external verifier observe the
live QtWebEngine UI with curl alone — no remote-debugging port needed. (It
is NOT a CDP replacement: CDP works on this Qt build — see
tests/test_ui_cdp_smoke.py — once --remote-allow-origins is set and the ws
client runs off the GUI thread; the old "CDP handshake stalls on this build"
claim was a misdiagnosis.)

These tests pin the load-bearing contracts:
  * flag OFF  -> maybe_start returns None and opens no port (normal launches
    are unaffected).
  * token gate -> a request with a wrong/absent token is rejected 401 before
    any Qt work; the right token passes.
  * /dom_query JSON shape -> {exists,count,text} via a STUB page (no real
    QtWebEngine needed; the stub's runJavaScript invokes the callback like
    the real one does).
  * /health + /screenshot smoke -> right shape / PNG bytes.
  * the GUI-thread marshaling actually crosses threads: requests run on a
    helper thread while the main thread pumps the Qt event loop, so the
    BlockingQueuedConnection path is genuinely exercised.

No network exposure: everything binds 127.0.0.1 on an ephemeral-ish port.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

import debug_bridge  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def qapp():
    """Single offscreen QApplication for the suite (mirrors the shell smoke
    tests). Needed so _GuiProxy slots can be invoked on the GUI thread."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


class _StubPage:
    """Stand-in for QWebEnginePage. ``runJavaScript`` mirrors the real
    callback contract: it invokes the callback synchronously with a JSON
    string shaped like the bridge's fixed DOM-query expression returns."""

    def __init__(self, *, exists=True, count=2, text="hello world",
                 url="file:///index.html", title="ArchHub"):
        self._payload = {"exists": exists, "count": count, "text": text}
        self._url = url
        self._title = title
        self.last_js = None

    def runJavaScript(self, js, callback):  # noqa: N802 (Qt name)
        self.last_js = js
        callback(json.dumps(self._payload))

    def url(self):
        class _U:
            def __init__(self, s):
                self._s = s

            def toString(self):
                return self._s
        return _U(self._url)

    def title(self):
        return self._title


class _AsyncStubPage(_StubPage):
    """Like ``_StubPage`` but fires the runJavaScript callback ASYNCHRONOUSLY
    via a GUI-thread QTimer — exactly as the real QWebEnginePage does. In the
    NON-BLOCKING design the GUI slot calls ``runJavaScript`` and returns at
    once; this callback then lands LATER on the GUI thread and delivers the
    result to the waiting worker's Event. Concurrency against this stub is the
    regression surface that, under the OLD nested-``QEventLoop`` design, stacked
    two loops on the single GUI thread and wedged it; under the new design the
    requests run truly concurrently with no GUI-thread blocking at all."""

    def __init__(self, *, delay_ms=40, **kw):
        super().__init__(**kw)
        self._delay_ms = delay_ms
        self._timers = []

    def runJavaScript(self, js, callback):  # noqa: N802 (Qt name)
        from PyQt6.QtCore import QTimer
        self.last_js = js
        payload = json.dumps(self._payload)
        # singleShot schedules the callback on the GUI event loop — it lands
        # AFTER the GUI slot has already returned, exactly like the real page.
        QTimer.singleShot(self._delay_ms, lambda: callback(payload))


class _NeverStubPage(_StubPage):
    """A page whose ``runJavaScript`` NEVER calls its callback — the
    about:blank / navigation-in-flight / dead-page case. Under the OLD design
    this drove the GUI-thread nested ``QEventLoop`` until the 5s watchdog; while
    it waited, that loop contended with normal GUI work (the "GUI call lock
    timeout" + "(Not Responding)" ghost the founder hit under probe load).
    Under the NEW design the GUI slot still returns immediately — only the
    WORKER thread waits — so this stub proves the GUI thread keeps running
    while a never-answering query is outstanding."""

    def runJavaScript(self, js, callback):  # noqa: N802 (Qt name)
        self.last_js = js  # capture, then drop the callback on the floor.


@pytest.fixture
def window(qapp):
    """A real QLabel as the grab target so /screenshot produces real PNG
    bytes. It also serves as the QObject parent for the proxy (GUI thread)."""
    from PyQt6.QtWidgets import QLabel
    w = QLabel("debug-bridge-test-window")
    w.resize(160, 48)
    yield w
    w.deleteLater()


def _pump_until(qapp, predicate, timeout=5.0):
    """Process Qt events on the main thread until ``predicate()`` is true or
    the timeout elapses. This lets the worker thread's
    BlockingQueuedConnection slot actually run on the GUI thread."""
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        qapp.processEvents()
        time.sleep(0.005)
    return predicate()


def _request_on_thread(fn):
    """Run a blocking HTTP request on a helper thread; return a dict that
    fills in with 'done'=True plus 'result' / 'error' when it completes.

    The 'done' flag (not box-truthiness) is the completion signal, so a
    response of ``{}`` or a falsy result can't be mistaken for "not yet"."""
    box: dict = {}

    def _go():
        try:
            box["result"] = fn()
        except Exception as ex:  # capture HTTPError etc.
            box["error"] = ex
        finally:
            box["done"] = True
    t = threading.Thread(target=_go, daemon=True)
    t.start()
    return box, t


def _await_request(qapp, fn, timeout=5.0):
    """Fire ``fn`` on a helper thread while pumping the GUI event loop until
    it completes. Returns the box (with 'result' or 'error')."""
    box, t = _request_on_thread(fn)
    _pump_until(qapp, lambda: box.get("done"), timeout=timeout)
    t.join(timeout=2.0)
    return box


@pytest.fixture
def server(qapp, window):
    """A started DebugBridgeServer with a stub page + known token."""
    page = _StubPage()
    token = "test-token-abc123"
    # Port 0 lets the OS choose a free port; read it back from the socket.
    srv = debug_bridge.DebugBridgeServer(
        view=None, page=page, window=window, port=0, token=token)
    # Re-create the httpd on an OS-chosen port so parallel runs don't clash.
    srv.start()
    srv._page_stub = page  # for assertions
    srv._token = token
    yield srv
    srv.stop()


def _server_port(srv) -> int:
    return srv._httpd.server_address[1]


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------
def test_flag_off_returns_none(qapp, window, monkeypatch):
    """ARCHHUB_DEBUG_BRIDGE unset/0 => maybe_start opens nothing."""
    monkeypatch.delenv("ARCHHUB_DEBUG_BRIDGE", raising=False)
    assert debug_bridge.is_enabled() is False
    srv = debug_bridge.maybe_start(view=None, page=_StubPage(), window=window)
    assert srv is None


def test_flag_explicit_zero_returns_none(qapp, window, monkeypatch):
    monkeypatch.setenv("ARCHHUB_DEBUG_BRIDGE", "0")
    assert debug_bridge.is_enabled() is False
    assert debug_bridge.maybe_start(
        view=None, page=_StubPage(), window=window) is None


def test_flag_on_starts_and_writes_token(qapp, window, monkeypatch, tmp_path):
    """ARCHHUB_DEBUG_BRIDGE=1 => server starts + token file written under the
    isolated LOCALAPPDATA (conftest pins it to tmp)."""
    monkeypatch.setenv("ARCHHUB_DEBUG_BRIDGE", "1")
    monkeypatch.setenv("ARCHHUB_DEBUG_BRIDGE_PORT", "0")
    srv = debug_bridge.maybe_start(
        view=None, page=_StubPage(), window=window)
    assert srv is not None
    try:
        tok_path = Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / ".debug_bridge_token"
        assert tok_path.exists()
        assert tok_path.read_text(encoding="utf-8") == srv.token
        assert len(srv.token) >= 20
    finally:
        srv.stop()


def test_token_rewrite_over_locked_file(qapp, window, monkeypatch):
    """Regression: a second launch must overwrite a token left behind (and
    locked down) by a first launch.

    The original bug: `_lock_down_file` granted the user only `:R`, so the
    NEXT launch's `write_text` hit PermissionError on Windows and
    `_write_token_files` returned [] -> "could not write token file anywhere;
    not starting" -> the bridge never started a second time. The fix grants
    RX,W and `_unlock_for_write` restores write on a stale file. This test
    drives two write cycles through the real `_write_token_files` (incl. the
    icacls lock-down on Windows) and asserts the second one wins."""
    monkeypatch.setenv("ARCHHUB_DEBUG_BRIDGE", "1")
    monkeypatch.setenv("ARCHHUB_DEBUG_BRIDGE_PORT", "0")

    first = debug_bridge._write_token_files("token-AAAA-first")
    assert first, "first token write should land somewhere"
    tok_path = Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / ".debug_bridge_token"
    assert tok_path.read_text(encoding="utf-8") == "token-AAAA-first"

    # Second cycle must overwrite — this is the path that used to fail.
    second = debug_bridge._write_token_files("token-BBBB-second")
    assert second, "second token write must succeed over the locked file"
    assert tok_path.read_text(encoding="utf-8") == "token-BBBB-second"

    # And the public entry point must therefore start cleanly a second time
    # even though a locked token already exists on disk.
    srv = debug_bridge.maybe_start(view=None, page=_StubPage(), window=window)
    assert srv is not None, "maybe_start must start despite a pre-existing token"
    try:
        assert tok_path.read_text(encoding="utf-8") == srv.token
    finally:
        srv.stop()


def test_resolve_port_default_and_override(monkeypatch):
    monkeypatch.delenv("ARCHHUB_DEBUG_BRIDGE_PORT", raising=False)
    assert debug_bridge.resolve_port() == debug_bridge.DEFAULT_PORT
    monkeypatch.setenv("ARCHHUB_DEBUG_BRIDGE_PORT", "12345")
    assert debug_bridge.resolve_port() == 12345
    monkeypatch.setenv("ARCHHUB_DEBUG_BRIDGE_PORT", "not-a-number")
    assert debug_bridge.resolve_port() == debug_bridge.DEFAULT_PORT


# ---------------------------------------------------------------------------
# Security model statement
# ---------------------------------------------------------------------------
def test_security_model_is_loopback_and_flagged():
    sm = debug_bridge.SECURITY_MODEL
    assert sm["bind"] == "127.0.0.1"
    assert "ARCHHUB_DEBUG_BRIDGE=1" in sm["flag"]
    assert "none" in sm["eval"].lower()


def test_server_binds_loopback_only(server):
    """The listening socket is bound to 127.0.0.1, never 0.0.0.0."""
    host, _port = server._httpd.server_address
    assert host == "127.0.0.1"


# ---------------------------------------------------------------------------
# Token gate
# ---------------------------------------------------------------------------
def test_health_rejects_missing_token(qapp, server):
    port = _server_port(server)

    def _call():
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        return urllib.request.urlopen(req, timeout=5)
    box = _await_request(qapp, _call)
    err = box.get("error")
    assert err is not None and getattr(err, "code", None) == 401


def test_health_rejects_wrong_token(qapp, server):
    port = _server_port(server)

    def _call():
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health?token=WRONG")
        return urllib.request.urlopen(req, timeout=5)
    box = _await_request(qapp, _call)
    err = box.get("error")
    assert err is not None and getattr(err, "code", None) == 401


def test_dom_query_rejects_wrong_token(qapp, server):
    port = _server_port(server)

    def _call():
        body = json.dumps({"selector": ".x", "token": "WRONG"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/dom_query", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(req, timeout=5)
    box = _await_request(qapp, _call)
    err = box.get("error")
    assert err is not None and getattr(err, "code", None) == 401
    # And the stub page's JS must NOT have run (rejected before Qt work).
    assert server._page_stub.last_js is None


# ---------------------------------------------------------------------------
# Happy-path routes (token correct) — these exercise the GUI-thread marshal.
# ---------------------------------------------------------------------------
def test_health_ok_shape(qapp, server):
    port = _server_port(server)
    tok = server._token

    def _call():
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health?token={tok}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    box = _await_request(qapp, _call)
    assert "result" in box, box.get("error")
    status, raw = box["result"]
    assert status == 200
    obj = json.loads(raw)
    assert obj["ok"] is True
    assert obj["url"] == "file:///index.html"
    assert obj["title"] == "ArchHub"


def test_dom_query_json_shape(qapp, server):
    """POST /dom_query with the right token returns {exists,count,text}
    via the stub page (the contract the founder named)."""
    port = _server_port(server)
    tok = server._token

    def _call():
        body = json.dumps({"selector": ".node-card", "token": tok}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/dom_query", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    box = _await_request(qapp, _call)
    assert "result" in box, box.get("error")
    status, raw = box["result"]
    assert status == 200
    obj = json.loads(raw)
    assert set(obj.keys()) >= {"exists", "count", "text"}
    assert obj["exists"] is True
    assert obj["count"] == 2
    assert obj["text"] == "hello world"
    # The selector was passed as a JSON string literal into the fixed JS —
    # never concatenated as code (the anti-eval guarantee).
    assert server._page_stub.last_js is not None
    assert '".node-card"' in server._page_stub.last_js
    assert "querySelectorAll" in server._page_stub.last_js


def test_dom_query_requires_selector(qapp, server):
    port = _server_port(server)
    tok = server._token

    def _call():
        body = json.dumps({"token": tok}).encode()  # no selector
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/dom_query", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(req, timeout=5)
    box = _await_request(qapp, _call)
    err = box.get("error")
    assert err is not None and getattr(err, "code", None) == 400


def test_screenshot_returns_png(qapp, server):
    port = _server_port(server)
    tok = server._token

    def _call():
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/screenshot?token={tok}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    box = _await_request(qapp, _call)
    assert "result" in box, box.get("error")
    status, ctype, data = box["result"]
    assert status == 200
    assert ctype == "image/png"
    # PNG magic number.
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_dom_query_selector_is_json_escaped(qapp, server):
    """A selector containing quotes is JSON-escaped, so it cannot break out
    of the string literal into executable JS."""
    port = _server_port(server)
    tok = server._token

    def _call():
        body = json.dumps(
            {"selector": '"];alert(1);//', "token": tok}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/dom_query", data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    box = _await_request(qapp, _call)
    assert "result" in box, box.get("error")
    status, _raw = box["result"]
    assert status == 200
    js = server._page_stub.last_js
    # The injected payload appears only as an escaped JSON string literal.
    assert '\\"];alert(1);//' in js or json.dumps('"];alert(1);//') in js


# ---------------------------------------------------------------------------
# Concurrency — the GUI-thread serialization lock
# ---------------------------------------------------------------------------
def test_concurrent_dom_queries_do_not_wedge(qapp, window):
    """Regression: many simultaneous /dom_query requests must ALL succeed and
    must not wedge the GUI thread.

    The bug: dom_query spins a nested QEventLoop on the GUI thread and the
    server is threaded, so two concurrent requests issued
    BlockingQueuedConnection slots that stacked two nested loops on the one
    GUI thread; a quit() crossed loops (LIFO) and the GUI thread wedged
    PERMANENTLY — after which even /health hung. `_GUI_CALL_LOCK` serializes
    GUI-thread calls on the worker side so at most one nested loop exists.

    This drives an ASYNC stub (callback via GUI-thread QTimer, like the real
    page) so every request takes the nested-loop path, fires 6 of them at
    once, pumps the GUI loop, and asserts all 6 return 200 + correct shape —
    then asserts a follow-up /health still answers (proves no wedge)."""
    page = _AsyncStubPage(delay_ms=30, count=3, text="brain")
    token = "concurrency-token"
    srv = debug_bridge.DebugBridgeServer(
        view=None, page=page, window=window, port=0, token=token).start()
    try:
        port = srv._httpd.server_address[1]

        def _dom():
            body = json.dumps({"selector": ".x", "token": token}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/dom_query", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()

        # Fire several at once; collect each result in its own box.
        boxes = []
        threads = []
        for _ in range(6):
            b, t = _request_on_thread(_dom)
            boxes.append(b)
            threads.append(t)
        # Pump the GUI loop until every worker reports done (or timeout).
        _pump_until(qapp, lambda: all(b.get("done") for b in boxes),
                    timeout=20.0)
        for t in threads:
            t.join(timeout=2.0)

        # Every concurrent request succeeded with the right shape.
        for b in boxes:
            assert "result" in b, b.get("error")
            status, raw = b["result"]
            assert status == 200
            obj = json.loads(raw)
            assert obj["count"] == 3
            assert obj["text"] == "brain"

        # And the GUI thread is NOT wedged: /health still answers.
        def _health():
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/health?token={token}")
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        hb = _await_request(qapp, _health, timeout=12.0)
        assert "result" in hb, hb.get("error")
        assert hb["result"][0] == 200
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# Non-blocking design — the GUI thread never blocks, even on a dead page
# ---------------------------------------------------------------------------
@pytest.fixture
def _fast_dom_timeout(monkeypatch):
    """Shrink the DOM-query bound so the 'page never calls back' tests resolve
    in well under a second instead of the production 5s+ watchdog."""
    monkeypatch.setattr(debug_bridge, "_DOM_TIMEOUT_MS", 120)
    monkeypatch.setattr(debug_bridge, "_DOM_WAIT_S", 0.6)


def test_dom_query_dead_page_times_out_clean(qapp, window, _fast_dom_timeout):
    """A page whose runJavaScript NEVER calls back returns a clean
    {exists:false,...,error:'timeout'} (HTTP 200) — bounded, never hung. This
    is the about:blank / navigation case that drove the old nested QEventLoop
    to its watchdog; here the GUI slot returned at once and only the worker
    waited."""
    page = _NeverStubPage()
    token = "dead-page-token"
    srv = debug_bridge.DebugBridgeServer(
        view=None, page=page, window=window, port=0, token=token).start()
    try:
        port = srv._httpd.server_address[1]

        def _dom():
            body = json.dumps({"selector": ".x", "token": token}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/dom_query", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        box = _await_request(qapp, _dom, timeout=5.0)
        assert "result" in box, box.get("error")
        status, raw = box["result"]
        assert status == 200
        obj = json.loads(raw)
        assert obj["exists"] is False
        assert obj["count"] == 0
        assert obj["error"] == "timeout"
        # The JS WAS dispatched (proves we reached runJavaScript, didn't just
        # short-circuit) — it simply never called back.
        assert page.last_js is not None
    finally:
        srv.stop()


def test_gui_thread_keeps_running_during_outstanding_dom_query(
        qapp, window, monkeypatch):
    """The load-bearing proof: while a never-returning /dom_query is in flight,
    the GUI thread is NOT blocked — a GUI-thread QTimer keeps firing and
    /health still answers promptly.

    Under the OLD blocking design the in-flight dom_query held a nested
    QEventLoop (and the process-wide GUI lock) on the single GUI thread, so a
    concurrent /health serialized behind it. Under the NEW design the GUI slot
    returned immediately; only the dom_query's worker thread is parked on its
    Event, leaving the GUI thread free.

    Timing is set so the WORKER wait (0.5s) is the resolver and the GUI-thread
    watchdog is parked high (won't fire) — giving a stable ~0.5s window in
    which the query is outstanding while we observe the GUI loop still ticking.
    """
    from PyQt6.QtCore import QTimer
    monkeypatch.setattr(debug_bridge, "_DOM_TIMEOUT_MS", 5000)  # watchdog won't fire
    monkeypatch.setattr(debug_bridge, "_DOM_WAIT_S", 0.5)       # worker wait resolves

    page = _NeverStubPage()
    token = "gui-free-token"
    srv = debug_bridge.DebugBridgeServer(
        view=None, page=page, window=window, port=0, token=token).start()
    try:
        port = srv._httpd.server_address[1]

        # A GUI-thread heartbeat: increments only if the GUI event loop is
        # actually processing timers (i.e. is NOT blocked).
        ticks = {"n": 0}
        beat = QTimer()
        beat.timeout.connect(lambda: ticks.__setitem__("n", ticks["n"] + 1))
        beat.start(10)

        # Start a dom_query that will never get its callback (worker parks on
        # its Event for the full _DOM_WAIT_S). Don't await it yet.
        def _dom():
            body = json.dumps({"selector": ".x", "token": token}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/dom_query", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        dom_box, dom_t = _request_on_thread(_dom)

        # While the dom_query is outstanding, the GUI heartbeat must advance —
        # impossible if the in-flight query were holding the GUI thread. Pump
        # the loop (bounded) until it ticks; the dom_query worker stays parked
        # on its Event the whole time.
        ticks_at_start = ticks["n"]
        advanced = _pump_until(
            qapp, lambda: ticks["n"] > ticks_at_start, timeout=2.0)
        assert advanced, "GUI event loop did not tick (blocked by dom_query)"
        assert not dom_box.get("done"), (
            "dom_query resolved too early — it should still be parked on its "
            "worker Event, proving the GUI thread ran independently of it")

        # And /health still answers promptly while the query is outstanding.
        def _health():
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/health?token={token}")
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, r.read()
        hb = _await_request(qapp, _health, timeout=3.0)
        assert "result" in hb, hb.get("error")
        assert hb["result"][0] == 200, "health blocked behind in-flight dom_query"

        # The dom_query still resolves cleanly (timeout JSON) once its worker
        # wait elapses — pump until it lands.
        _pump_until(qapp, lambda: dom_box.get("done"), timeout=3.0)
        dom_t.join(timeout=2.0)
        assert "result" in dom_box, dom_box.get("error")
        assert dom_box["result"][0] == 200
        assert json.loads(dom_box["result"][1])["error"] == "timeout"
    finally:
        beat.stop()
        srv.stop()


def test_no_gui_call_lock_symbol(_unused=None):
    """The process-wide GUI serialization lock is GONE — the non-blocking
    design needs no such lock (each request owns its own Event/holder). Guards
    against a silent reintroduction of the nested-loop serialization."""
    assert not hasattr(debug_bridge, "_GUI_CALL_LOCK")


def test_dom_query_path_has_no_nested_qeventloop():
    """STRUCTURAL guard (the heart of the redesign): the GUI-thread dom_query
    path must NOT spin a nested QEventLoop.

    The old wedge was a ``QEventLoop`` created + ``.exec()``-ed *inside*
    ``_GuiProxy.dom_query`` on the single GUI thread, awaiting the async
    runJavaScript callback. Two concurrent BlockingQueuedConnection calls then
    stacked two nested loops and a cross-loop ``quit()`` wedged the GUI thread.

    This inspects the actual EXECUTABLE source (docstrings + comments stripped,
    so the word ``QEventLoop`` appearing in a "what we deliberately do NOT do"
    docstring is not a false positive) of the GUI-thread slot and the
    worker-side driver, and asserts the nested-loop machinery is gone while the
    fire-and-forget callback machinery is present. It fails LOUDLY if a future
    edit reintroduces ``QEventLoop`` / ``loop.exec`` into the dom_query path —
    a behavioural test can pass by luck of timing; this cannot."""
    import ast
    import inspect
    import textwrap

    def _code_only(fn) -> str:
        """Return the function's source with docstrings + comments removed, so
        the structural scan sees only executable code (the prose in docstrings
        legitimately mentions the banned primitives to explain their absence)."""
        src = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(src)
        # Drop the leading string-expression (docstring) of every def/class.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(getattr(body[0], "value", None),
                                       ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    body.pop(0)
        # ast.unparse drops comments entirely + emits only real code.
        return ast.unparse(tree)

    gui_code = _code_only(debug_bridge._GuiProxy.dom_query)
    worker_code = _code_only(debug_bridge._dom_query)
    invoke_code = _code_only(debug_bridge._invoke_via_event)
    dispatch_code = _code_only(debug_bridge._dispatch)

    combined = gui_code + worker_code + invoke_code + dispatch_code

    # The banned nested-loop primitives must appear NOWHERE in the real code of
    # the path (docstrings/comments already stripped above).
    for banned in ("QEventLoop", "exec("):
        assert banned not in combined, (
            f"dom_query path must not use {banned!r} — the nested GUI-thread "
            f"loop was the wedge the redesign removed")

    # The GUI slot must hand work to runJavaScript with a callback and RETURN —
    # it must not block-wait for the result itself.
    assert "runJavaScript" in gui_code
    assert "_deliver" in gui_code, (
        "GUI slot must deliver out-of-band via _deliver, not return a value")

    # The cross-thread dispatch is a *queued* (fire-and-forget) connection, not
    # a blocking one — invokeMethod returns to the worker immediately.
    assert "QueuedConnection" in dispatch_code
    assert "BlockingQueuedConnection" not in dispatch_code, (
        "dispatch must be fire-and-forget; a blocking connection on the single "
        "GUI thread is exactly what re-entrantly stacked nested loops")

    # The only wait is the WORKER thread's Event.wait(timeout) — the bound that
    # never touches the GUI thread.
    assert "wait" in invoke_code and "ev" in invoke_code
    assert "wait" in worker_code  # worker-side bounded wait in the driver too


def test_dom_query_uses_event_holder_structure():
    """The non-blocking contract's data structures exist + are wired: each
    in-flight request owns a _Pending (threading.Event + result holder), keyed
    in the _PENDING registry, woken by first-writer-wins _deliver."""
    import threading as _t

    pend = debug_bridge._Pending()
    assert isinstance(pend.ev, _t.Event)
    assert hasattr(pend, "result")
    assert hasattr(pend, "delivered")

    # Allocate -> register -> deliver -> the Event fires + value lands.
    rid, rec = debug_bridge._pending_new()
    assert debug_bridge._pending_get(rid) is rec
    assert rec.ev.is_set() is False
    debug_bridge._deliver(rid, {"exists": True})
    assert rec.ev.is_set() is True
    assert rec.result == {"exists": True}
    assert rec.delivered is True

    # First-writer-wins: a second deliver is a harmless no-op (the callback vs
    # watchdog race relies on this).
    debug_bridge._deliver(rid, {"exists": False})
    assert rec.result == {"exists": True}

    # Worker pops it in finally; the registry drains.
    popped = debug_bridge._pending_pop(rid)
    assert popped is rec
    assert debug_bridge._pending_get(rid) is None


def test_pending_registry_drains(qapp, server):
    """Every request pops its pending record — no leak across many calls.
    After a batch of /health round-trips the _PENDING dict is empty again."""
    port = _server_port(server)
    tok = server._token

    def _health():
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health?token={tok}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    for _ in range(8):
        box = _await_request(qapp, _health, timeout=5.0)
        assert "result" in box, box.get("error")
        assert box["result"][0] == 200
    # All records detached once delivered + popped.
    assert debug_bridge._PENDING == {}
