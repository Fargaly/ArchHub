"""In-app debug bridge — verify ArchHub's live UI state WITHOUT DevTools.

Why this exists (founder-approved, 2026-06-01)
-----------------------------------------------
ArchHub's UI is a React tree rendered inside QtWebEngine (see
``app/web_shell.py`` + ``app/bridge.py``). The canonical "is this real on
the running app" proof path is the Chromium remote-debugging endpoint
(CDP / DevTools websocket at ``http://localhost:9223``), and it WORKS on
this QtWebEngine build — see ``tests/test_ui_cdp_smoke.py``. (The old claim
that "the DevTools websocket handshake stalls on this build" was wrong: the
real causes were (a) a missing ``--remote-allow-origins`` Chromium flag —
Chromium 111+ 403s the ws upgrade when an ``Origin`` header is present and
the origin isn't allow-listed — now appended in ``app/main.py`` when remote
debugging is opt-in; and (b) a verifier that called urlopen/ws ON the Qt GUI
thread, blocking the very service it was probing — verifiers now run the
HTTP/ws client off-thread / out-of-process. Neither was a Qt bug.)

This module ships a tiny, in-process HTTP server with a DELIBERATELY NARROW
surface as a COMPLEMENTARY, zero-DevTools proof path (founder-approved): it
needs no remote-debugging port and lets an external verifier (curl / a test
/ an agent) observe the live window directly:

    GET  /health?token=...                  -> {ok, url, title}
    GET  /screenshot?token=...              -> image/png bytes of the window
    POST /dom_query   {selector, token}     -> {exists, count, text}

There is intentionally NO arbitrary-eval route. The DOM query runs ONE
fixed JS expression (a ``querySelectorAll`` + a few read-only fields);
the selector is the only caller-supplied input and it is passed as a
JSON-encoded string literal into that fixed expression, never
concatenated as code. This keeps the attack surface to "read three
properties of a selector you already could see in the window".

Security (load-bearing — see SECURITY_MODEL below)
--------------------------------------------------
* Binds ``127.0.0.1`` ONLY (never ``0.0.0.0``). Remote hosts cannot reach it.
* Requires a per-launch random token. The token is written to two files
  readable only by the local user; a request without the exact token is
  rejected ``401`` before any Qt work happens.
* Starts ONLY when ``ARCHHUB_DEBUG_BRIDGE=1``. Off by default, so a normal
  launch never opens a port and is completely unaffected.

Threading (load-bearing — GUI thread NEVER blocks)
--------------------------------------------------
``QWebEnginePage.runJavaScript`` and ``QWidget.grab()`` MUST run on the Qt
GUI thread. The HTTP request handler runs on a worker thread (stdlib
``ThreadingHTTPServer``). It therefore NEVER touches a Qt widget directly.

The design is deliberately NON-BLOCKING on the GUI thread. For every request
the worker thread:

1. allocates a small ``_Pending`` record (a ``threading.Event`` + a result
   holder) and registers it under a unique integer request id;
2. fires the work onto the GUI thread with
   ``QMetaObject.invokeMethod(_GuiProxy, slot, Qt.QueuedConnection,
   Q_ARG(str, payload))`` — a *queued* (fire-and-forget) dispatch, NOT a
   blocking one. ``invokeMethod`` returns to the worker immediately; the slot
   is appended to the GUI thread's event queue;
3. blocks the WORKER thread on ``event.wait(timeout)`` — the GUI thread is
   free the entire time.

On the GUI thread the slot does only cheap, synchronous dispatch work and
RETURNS IMMEDIATELY — it never spins a nested ``QEventLoop``:

* ``dom_query`` calls ``page.runJavaScript(js, callback)`` and returns. The
  ``runJavaScript`` callback fires LATER, still on the GUI thread; it writes
  the result into the pending record and ``set()``s the Event, waking the
  worker. A GUI-thread ``QTimer`` (the watchdog) fires the same delivery with
  a ``timeout`` marker if the page never calls back, so the worker's
  ``wait()`` is always released even without the timeout fallback.
* ``grab_png_b64`` and ``health`` run their (synchronous) widget work inline
  and deliver the result + ``set()`` the Event before returning — same
  one-shot delivery path, no event loop.

Because nothing on the GUI thread ever waits on the worker (or on another
GUI-thread call), concurrent requests cannot stack nested loops and cannot
wedge the GUI thread. Each request owns its own Event/holder, so there is no
process-wide GUI serialization lock and no re-entrancy hazard — requests run
truly concurrently, each blocking only its own worker thread. The worker's
``wait(timeout)`` is the single bound; a slow or dead page yields a clean
``"timeout"`` answer, never a hung GUI thread or a Windows "(Not Responding)"
ghost. See ``_GuiProxy`` + ``_invoke_via_event`` for the details.

GPU flags vs. runJavaScript callbacks (isolation-tested 2026-06-01)
-------------------------------------------------------------------
``/dom_query`` depends on a ``page.runJavaScript`` *callback* firing (now
delivered to the worker via a ``threading.Event`` — see ``_GuiProxy.dom_query``).
An earlier worry was that ArchHub's production Chromium GPU flags
(``--ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy``, set
in ``app/main.py``) might wedge that callback. An isolation study on the app's
exact PyQt6/Qt build DISPROVED it: with the full production flag set ON,
``page.runJavaScript`` callbacks fired 40/40 (zero timeouts) across all 8 flag
combinations. So ``/dom_query`` is reliable WITH the production GPU flags —
there is no flag-induced wedge, and the shipped flags are correct and
unchanged.

If a verification run nonetheless wants to remove the GPU/compositor as a
variable (defense in depth, not a known fix), launch the app with
``ARCHHUB_VERIFY_NO_GPU=1``: ``app/main.py`` then appends ``--disable-gpu``
for that run ONLY, never touching the production flags. ``/screenshot`` and
the CDP/remote-debugging path (``tests/test_ui_cdp_smoke.py``) are additional
proof paths whose reliability does not depend on the GPU flags at all.
"""
from __future__ import annotations

import base64
import itertools
import json
import logging
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from PyQt6.QtCore import (
    QObject,
    pyqtSlot,
    QMetaObject,
    Qt,
    Q_ARG,
    QByteArray,
    QBuffer,
    QIODevice,
    QTimer,
)

_log = logging.getLogger("archhub.debug_bridge")

# Default loopback port; override with ARCHHUB_DEBUG_BRIDGE_PORT.
DEFAULT_PORT = 9237

# DOM-query bound. The GUI-thread watchdog (_DOM_TIMEOUT_MS) and the worker's
# own Event.wait timeout (_DOM_WAIT_S, slightly longer so the in-band watchdog
# normally wins and produces the clean "timeout" JSON) both release a request
# that the page never answers — neither ever blocks the GUI thread.
_DOM_TIMEOUT_MS = 5000
_DOM_WAIT_S = (_DOM_TIMEOUT_MS / 1000.0) + 2.0

# Sentinel marking "the GUI-thread watchdog fired" — turned into the timeout
# JSON on the worker side. A distinct object so it can't collide with any real
# runJavaScript payload (which is always a str/dict/None).
_DOM_TIMEOUT_SENTINEL = object()

# Pre-serialised "no page" answer (page is None on the GUI side).
_DOM_NO_PAGE = json.dumps(
    {"exists": False, "count": 0, "text": "", "error": "no page"})

# The single fixed DOM-query expression. The selector is substituted as a
# JSON string literal (json.dumps) so it is always a quoted string value,
# never executable code — there is no arbitrary eval here. innerText is
# capped at 2000 chars to keep responses small.
_DOM_QUERY_JS = (
    "(()=>{try{"
    "const els=document.querySelectorAll(%s);"
    "return JSON.stringify({"
    "exists:els.length>0,"
    "count:els.length,"
    "text:(els[0]&&els[0].innerText?els[0].innerText:'').slice(0,2000)"
    "});"
    "}catch(e){return JSON.stringify({exists:false,count:0,text:'',error:String(e)});}"
    "})()"
)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
def _appdata_token_path() -> Path:
    """%LOCALAPPDATA%/ArchHub/.debug_bridge_token (Windows) or the
    home-dir fallback. Mirrors secrets_store.APP_DIR resolution so tests
    that pin LOCALAPPDATA also pin this."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "ArchHub" / ".debug_bridge_token"


def _run_dir_token_path() -> Path:
    """A second copy in the repo run dir (repo root) so a verifier launched
    from the checkout can read the token without knowing the AppData path.
    Repo root = two levels up from this file (app/ -> ArchHub/)."""
    return Path(__file__).resolve().parent.parent / ".debug_bridge_token"


def _icacls_user(user: str) -> str:
    """The icacls principal for the running user. Prefer DOMAIN\\USER so the
    grant matches the account exactly (USERDOMAIN is the local machine name
    for a local account, the AD domain otherwise)."""
    dom = os.environ.get("USERDOMAIN") or ""
    return f"{dom}\\{user}" if dom else user


def _lock_down_file(path: Path) -> None:
    """Best-effort: restrict the token file to the current user only.

    On Windows we use icacls to remove inherited ACLs and grant the running
    user read AND write — so another local user account cannot read the
    token, while THIS user can still rotate it on the next launch. Granting
    only ``:R`` was a self-inflicted bug: once written, the read-only ACE
    blocked the next launch from overwriting the token, so the bridge could
    never restart (PermissionError -> "could not write token file anywhere").
    The security property ("no OTHER user can read it") comes from
    ``/inheritance:r`` + granting solely this user; the owner having write is
    correct and required. Failure is non-fatal: the loopback bind + random
    token are the primary guards; tight ACLs are defence in depth.
    """
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)  # rw for owner only
        except Exception:
            pass
        return
    try:
        import subprocess
        user = os.environ.get("USERNAME") or ""
        if not user:
            return
        # /inheritance:r drops inherited ACEs; then grant ONLY this user, with
        # read+write (RX,W) so the token can be overwritten next launch.
        subprocess.run(
            ["icacls", str(path), "/inheritance:r",
             "/grant:r", f"{_icacls_user(user)}:(RX,W)"],
            capture_output=True, timeout=10, check=False,
        )
    except Exception:
        # ACL hardening is best-effort; never block the bridge on it.
        pass


def _unlock_for_write(path: Path) -> None:
    """Ensure ``path`` can be (re)written even if a prior launch locked it
    down read-only. Restores write access via icacls; if that fails, deletes
    the stale file outright. Without this, a token file left read-only by an
    older build (or an older grant) would block every future launch."""
    if not path.exists():
        return
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return
    try:
        import subprocess
        user = os.environ.get("USERNAME") or ""
        if user:
            subprocess.run(
                ["icacls", str(path), "/grant", f"{_icacls_user(user)}:(F)"],
                capture_output=True, timeout=10, check=False,
            )
    except Exception:
        pass
    # Belt and braces: if it's still not writable, drop it so write_text can
    # recreate it fresh.
    if not os.access(path, os.W_OK):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _write_token_files(token: str) -> list[Path]:
    """Write the token to every location, locking down perms. Returns the
    paths written successfully.

    Paths are de-duplicated by resolved target: in an *installed* copy
    ``%LOCALAPPDATA%/ArchHub`` and the repo run dir collapse to the same
    file, and processing it twice (write -> lock RX,W -> write again) is
    wasted work. A stale read-only token from a prior launch is unlocked
    first so the write always succeeds — the bug that kept the bridge from
    ever starting a second time.
    """
    written: list[Path] = []
    seen: set[str] = set()
    for path in (_appdata_token_path(), _run_dir_token_path()):
        try:
            key = str(path.resolve()).lower()
        except Exception:
            key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _unlock_for_write(path)
            path.write_text(token, encoding="utf-8")
            _lock_down_file(path)
            written.append(path)
        except Exception:
            # One location failing (e.g. read-only install) is fine as long
            # as another succeeds; the verifier reads whichever it can.
            continue
    return written


# ---------------------------------------------------------------------------
# Pending-request registry — the bridge between the GUI thread and the worker
# threads. Each in-flight request owns a ``_Pending`` (a threading.Event + a
# result holder). The worker creates it, hands its integer id to the GUI-thread
# slot, then blocks on ``ev.wait(timeout)``. The GUI-thread slot (or, for
# dom_query, the later runJavaScript callback / watchdog) writes the result and
# ``set()``s the Event, waking the worker. Nothing on the GUI thread ever waits
# on the worker, so the GUI thread cannot block or wedge.
#
# A process-wide dict keyed by a monotonic id lets the (string-only) queued
# slot signature carry just the id across the thread boundary — no custom Qt
# meta-type registration, and no per-request QObject lifetime to manage.
# ---------------------------------------------------------------------------
class _Pending:
    """One in-flight GUI call: an Event the worker waits on + the result the
    GUI side fills in. ``delivered`` guards against a double delivery (e.g. the
    runJavaScript callback AND the watchdog both firing) so the first writer
    wins and the second is a harmless no-op."""

    __slots__ = ("ev", "result", "delivered", "_selector")

    def __init__(self) -> None:
        self.ev = threading.Event()
        self.result: object = None
        self.delivered = False
        self._selector = ""


_PENDING: dict[int, _Pending] = {}
_PENDING_LOCK = threading.Lock()
_REQ_IDS = itertools.count(1)


def _pending_new() -> tuple[int, _Pending]:
    """Allocate + register a pending record; return (id, record)."""
    rid = next(_REQ_IDS)
    pend = _Pending()
    with _PENDING_LOCK:
        _PENDING[rid] = pend
    return rid, pend


def _pending_pop(rid: int) -> Optional[_Pending]:
    """Detach a pending record by id (so its memory is freed once delivered /
    timed out). Returns None if already removed."""
    with _PENDING_LOCK:
        return _PENDING.pop(rid, None)


def _pending_get(rid: int) -> Optional[_Pending]:
    """Look up a pending record by id WITHOUT removing it (the GUI side uses
    this; the worker side pops in ``finally`` after wait() returns)."""
    with _PENDING_LOCK:
        return _PENDING.get(rid)


def _deliver(rid: int, value: object) -> None:
    """Deliver ``value`` to the pending request ``rid`` and wake its worker.
    First writer wins; later callers (watchdog vs. callback race) are no-ops.
    Safe to call from the GUI thread — it only touches Python state + sets an
    Event, never blocks."""
    pend = _pending_get(rid)
    if pend is None:
        return  # worker already gave up + popped it; nothing to wake.
    if pend.delivered:
        return
    pend.delivered = True
    pend.result = value
    pend.ev.set()


# ---------------------------------------------------------------------------
# GUI-thread proxy — the ONLY object that touches Qt widgets. It lives on the
# GUI thread (parented to the main window) and is invoked from the HTTP worker
# threads via a QueuedConnection (fire-and-forget): the slot is appended to the
# GUI thread's event queue and runs there, while invokeMethod returns to the
# worker IMMEDIATELY. Each slot does only cheap synchronous dispatch and
# RETURNS at once — it never spins a nested QEventLoop and never blocks. Results
# travel back to the waiting worker through the _PENDING registry above.
# ---------------------------------------------------------------------------
class _GuiProxy(QObject):
    """Touches Qt widgets on the GUI thread, then hands results back to the
    waiting worker via the ``_PENDING`` registry.

    Every slot takes a single ``str`` request id (so the QueuedConnection
    marshal needs no custom meta-type registration — plain ``str`` args
    cross cleanly in PyQt6) and returns nothing: the result is delivered out
    of band through ``_deliver(rid, value)``. Critically, each slot does only
    cheap synchronous dispatch and RETURNS IMMEDIATELY — none spins a nested
    ``QEventLoop`` or waits on a worker, so the GUI thread never blocks and
    concurrent requests can never wedge it.

    The DOM-query result and the PNG both travel back as plain Python objects
    (a JSON string / a base64 ascii string), decoded by the HTTP handler.
    """

    def __init__(self, *, view, page, window, parent=None):
        super().__init__(parent)
        self._view = view
        self._page = page
        self._window = window

    # ---- screenshot -------------------------------------------------------
    @pyqtSlot(str)
    def grab_png_b64(self, rid_s: str) -> None:
        """Grab the window (or web view) as a base64 PNG, deliver to ``rid``.

        Runs on the GUI thread. ``widget.grab()`` is synchronous, so this
        does its work inline and delivers before returning — but it still
        returns at once (no event loop, no waiting). Delivers "" on any
        failure so the HTTP handler can answer 500 without raising across the
        thread boundary.
        """
        rid = int(rid_s)
        try:
            target = self._window or self._view
            if target is None:
                _deliver(rid, "")
                return
            pixmap = target.grab()
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            ok = pixmap.save(buf, "PNG")
            buf.close()
            _deliver(rid, base64.b64encode(bytes(ba)).decode("ascii") if ok else "")
        except Exception as ex:  # pragma: no cover - defensive
            _log.debug("grab_png_b64 failed: %s", ex)
            _deliver(rid, "")

    # ---- dom query --------------------------------------------------------
    @pyqtSlot(str)
    def dom_query(self, rid_s: str) -> None:
        """Dispatch the fixed DOM-query JS, then RETURN IMMEDIATELY.

        ``runJavaScript`` is asynchronous (callback-based) on the real
        QWebEnginePage. The whole point of the redesign is that we do NOT spin
        a nested ``QEventLoop`` here to wait for it — that nested loop on the
        single GUI thread was what contended with normal GUI work and produced
        the "GUI call lock timeout" + transient "(Not Responding)" ghost under
        concurrent load.

        Instead this slot:

        * looks up the request's pending record (which carries the selector),
        * calls ``page.runJavaScript(js, callback)`` and returns — the GUI
          thread is immediately free again,
        * the ``callback`` fires LATER on the GUI thread and ``_deliver``s the
          raw result to the waiting worker (waking its ``Event``),
        * a single-shot ``QTimer`` watchdog (parented to this proxy, so it
          lives on the GUI thread) ``_deliver``s a ``timeout`` marker if the
          page never calls back. ``_deliver`` is first-writer-wins, so the
          callback and the watchdog race harmlessly; whichever lands first
          wins and the other is a no-op.

        Result NORMALISATION (JSON-string -> {exists,count,text}) happens on
        the worker side in ``_dom_query`` so this slot stays a pure dispatch.
        """
        rid = int(rid_s)
        pend = _pending_get(rid)
        if pend is None:
            return  # worker already timed out + popped; nothing to do.
        selector = getattr(pend, "_selector", "")
        if self._page is None:
            _deliver(rid, _DOM_NO_PAGE)
            return
        # Substitute the selector as a JSON string literal — quoted value,
        # never code. This is the whole anti-eval guarantee.
        js = _DOM_QUERY_JS % json.dumps(selector or "")

        def _on_result(value, _rid=rid):
            # Fires later on the GUI thread; just hand the raw value back.
            _deliver(_rid, value)

        try:
            self._page.runJavaScript(js, _on_result)
        except Exception as ex:
            _deliver(rid, json.dumps(
                {"exists": False, "count": 0, "text": "",
                 "error": f"runJavaScript: {ex}"}))
            return

        # Arm a GUI-thread watchdog so a page that never calls back still
        # releases the worker. singleShot keeps no object to clean up; the
        # first-writer-wins _deliver makes a late callback-vs-watchdog race
        # harmless. The worker's own wait() timeout is a second, independent
        # bound (see _DOM_TIMEOUT_MS / _invoke_via_event).
        QTimer.singleShot(
            _DOM_TIMEOUT_MS,
            lambda _rid=rid: _deliver(_rid, _DOM_TIMEOUT_SENTINEL),
        )

    # ---- health -----------------------------------------------------------
    @pyqtSlot(str)
    def health(self, rid_s: str) -> None:
        """Deliver {ok, url, title} for the live view. GUI thread only, and
        synchronous — runs inline + delivers, but returns at once."""
        rid = int(rid_s)
        try:
            url = ""
            title = ""
            if self._page is not None:
                try:
                    url = self._page.url().toString()
                except Exception:
                    url = ""
                try:
                    title = self._page.title()
                except Exception:
                    title = ""
            if not title and self._window is not None:
                try:
                    title = self._window.windowTitle()
                except Exception:
                    title = ""
            _deliver(rid, json.dumps({"ok": True, "url": url, "title": title}))
        except Exception as ex:  # pragma: no cover - defensive
            _deliver(rid, json.dumps({"ok": False, "error": str(ex)}))


# Cross-thread invokers ------------------------------------------------------
# The GUI thread is NEVER blocked and there is NO process-wide serialization
# lock. Each worker allocates its own _Pending (Event + holder), fires the slot
# onto the GUI thread with a *queued* (fire-and-forget) invokeMethod, then
# blocks ITS OWN worker thread on Event.wait(timeout). Because the slot returns
# immediately and never waits on a worker, two concurrent requests cannot stack
# nested loops on the single GUI thread — the wedge the old _GUI_CALL_LOCK +
# nested QEventLoop existed to prevent simply cannot occur, so both are gone.
def _dispatch(proxy: _GuiProxy, slot: str, rid: int) -> bool:
    """Queue ``slot(str(rid))`` onto the GUI thread (fire-and-forget). Returns
    False if the marshal itself failed (so the caller can answer immediately
    instead of waiting on an Event that will never be set)."""
    try:
        ok = QMetaObject.invokeMethod(
            proxy, slot,
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, str(rid)),
        )
        # invokeMethod returns False if the slot/signature wasn't found.
        return bool(ok) if ok is not None else True
    except Exception as ex:  # pragma: no cover - defensive
        _log.debug("invoke %s failed: %s", slot, ex)
        return False


def _invoke_via_event(proxy: _GuiProxy, slot: str, timeout: float) -> object:
    """Run a GUI-thread ``slot`` and wait (on THIS worker thread only) for its
    delivered result. The GUI thread does cheap dispatch and returns at once;
    the result arrives through ``_deliver`` and wakes our Event. On marshal
    failure or timeout, returns ``None`` so the caller can map it to a clean
    error/empty answer. Always pops the pending record so it can't leak."""
    rid, pend = _pending_new()
    try:
        if not _dispatch(proxy, slot, rid):
            return None
        if not pend.ev.wait(timeout):
            _log.warning("debug_bridge: %s timed out after %.1fs", slot, timeout)
            return None
        return pend.result
    finally:
        _pending_pop(rid)


def _invoke_str(proxy: _GuiProxy, slot: str, _arg: str = "") -> str:
    """Call a GUI-thread slot whose delivered result is a string (``health``,
    ``grab_png_b64``). Worker-side bounded wait; returns "" on timeout/failure
    so the HTTP handler can answer 500/error JSON without raising across the
    thread boundary. The GUI thread never blocks."""
    out = _invoke_via_event(proxy, slot, timeout=_DOM_WAIT_S)
    return out if isinstance(out, str) else ""


def _dom_query(proxy: _GuiProxy, selector: str) -> str:
    """Worker-side driver for /dom_query. Stashes the selector on the pending
    record (so the GUI slot can read it without a second marshalled arg), fires
    the dispatch, waits on this worker thread, and NORMALISES the raw
    runJavaScript value into the fixed ``{exists,count,text}`` JSON contract.
    The GUI thread only runs ``page.runJavaScript`` + the callback store."""
    rid, pend = _pending_new()
    pend._selector = selector  # read by _GuiProxy.dom_query on the GUI thread
    try:
        if not _dispatch(proxy, "dom_query", rid):
            return json.dumps({"exists": False, "count": 0, "text": "",
                               "error": "dispatch failed"})
        # Worker-thread wait. The GUI-thread watchdog normally fires first
        # (_DOM_TIMEOUT_MS) and delivers the timeout sentinel; this slightly
        # longer wait is the backstop if even that never lands.
        if not pend.ev.wait(_DOM_WAIT_S):
            return json.dumps({"exists": False, "count": 0, "text": "",
                               "error": "timeout"})
        raw = pend.result
    finally:
        _pending_pop(rid)

    if raw is _DOM_TIMEOUT_SENTINEL or raw is None:
        return json.dumps({"exists": False, "count": 0, "text": "",
                           "error": "timeout"})
    # The JS returns a JSON string; pass a dict straight through.
    if isinstance(raw, dict):
        return json.dumps(raw)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            parsed = {"exists": False, "count": 0, "text": "",
                      "error": "bad shape"}
        return json.dumps(parsed)
    except Exception:
        return json.dumps({"exists": False, "count": 0, "text": "",
                           "error": "unparseable result"})


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    # Set per-server (see start()).
    proxy: Optional[_GuiProxy] = None
    token: str = ""

    # HTTP/1.0 => connection closes after each response. No keep-alive means
    # the client never holds the socket open waiting for more, which avoids a
    # Windows-only WinError 10053 socket-abort race when the client closes
    # the moment it has read the body. Each request is one short round-trip.
    protocol_version = "HTTP/1.0"

    # Silence the default stderr request logging — this is a debug aid, not
    # a public server, and we don't want it spamming the console.
    def log_message(self, fmt, *args):  # noqa: N802
        _log.debug("debug_bridge %s - %s", self.address_string(), fmt % args)

    # -- helpers ------------------------------------------------------------
    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self, supplied: Optional[str]) -> bool:
        """Constant-time token comparison. Empty server token => always
        reject (defensive — start() never sets an empty token)."""
        if not self.token or not supplied:
            return False
        return secrets.compare_digest(str(supplied), self.token)

    def _reject(self) -> None:
        self._send_json(401, {"error": "unauthorized"})

    # -- routes -------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        token = (qs.get("token") or [None])[0]

        if not self._token_ok(token):
            self._reject()
            return

        if route == "/health":
            raw = _invoke_str(self.proxy, "health", "") if self.proxy else ""
            try:
                obj = json.loads(raw) if raw else {"ok": False, "error": "no proxy"}
            except Exception:
                obj = {"ok": False, "error": "bad health payload"}
            self._send_json(200, obj)
            return

        if route == "/screenshot":
            b64 = _invoke_str(self.proxy, "grab_png_b64", "") if self.proxy else ""
            if not b64:
                self._send_json(500, {"error": "grab failed"})
                return
            try:
                png = base64.b64decode(b64)
            except Exception:
                self._send_json(500, {"error": "decode failed"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(png)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        raw_body = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        token = payload.get("token")
        if not self._token_ok(token):
            self._reject()
            return

        if route == "/dom_query":
            selector = payload.get("selector")
            if not isinstance(selector, str) or not selector:
                self._send_json(400, {"error": "selector required"})
                return
            raw = _dom_query(self.proxy, selector) if self.proxy else ""
            try:
                obj = json.loads(raw) if raw else {
                    "exists": False, "count": 0, "text": "", "error": "no proxy"}
            except Exception:
                obj = {"exists": False, "count": 0, "text": "",
                       "error": "bad dom payload"}
            self._send_json(200, obj)
            return

        self._send_json(404, {"error": "not found"})


class DebugBridgeServer:
    """Owns the GUI proxy + the worker-thread HTTP server."""

    def __init__(self, *, view, page, window, port: int, token: str):
        self.port = port
        self.token = token
        # Proxy is parented to the window so it lives + dies on the GUI thread.
        self.proxy = _GuiProxy(view=view, page=page, window=window,
                               parent=window)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "DebugBridgeServer":
        # A per-server Handler subclass carries the proxy + token without a
        # module global (so two servers in a test process never collide).
        proxy = self.proxy
        token = self.token

        class _BoundHandler(_Handler):
            pass
        _BoundHandler.proxy = proxy
        _BoundHandler.token = token

        # 127.0.0.1 ONLY — never 0.0.0.0. This is the network guard.
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port),
                                          _BoundHandler)
        # daemon thread: dies with the process, like the app's other pollers.
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="archhub-debug-bridge", daemon=True,
        )
        self._thread.start()
        _log.info("debug bridge listening on http://127.0.0.1:%d "
                  "(routes: /health /screenshot /dom_query)", self.port)
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None


# ---------------------------------------------------------------------------
# Public entry point — called from web_shell after the view/page exist.
# ---------------------------------------------------------------------------
def is_enabled() -> bool:
    """The flag gate. Off by default => normal launches open no port."""
    return os.environ.get("ARCHHUB_DEBUG_BRIDGE") == "1"


def resolve_port() -> int:
    raw = os.environ.get("ARCHHUB_DEBUG_BRIDGE_PORT")
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def maybe_start(*, view, page, window) -> Optional[DebugBridgeServer]:
    """Start the debug bridge IFF ``ARCHHUB_DEBUG_BRIDGE=1``.

    Returns the running server (so the caller can keep a ref / stop it), or
    ``None`` when the flag is off or startup fails. NEVER raises — a debug
    aid must not be able to break the app launch.
    """
    if not is_enabled():
        return None
    try:
        token = secrets.token_urlsafe(32)
        written = _write_token_files(token)
        if not written:
            _log.warning("debug bridge: could not write token file anywhere; "
                         "not starting")
            return None
        port = resolve_port()
        server = DebugBridgeServer(view=view, page=page, window=window,
                                   port=port, token=token).start()
        _log.info("debug bridge token written to: %s",
                  ", ".join(str(p) for p in written))
        return server
    except Exception as ex:
        # Bind failure (port in use), etc. Log + swallow.
        _log.warning("debug bridge failed to start: %s", ex)
        return None


# Short, machine-readable statement of the security posture, surfaced in the
# module so reviewers / tests can assert on it.
SECURITY_MODEL = {
    "bind": "127.0.0.1",            # loopback only, never 0.0.0.0
    "token": "per-launch random (secrets.token_urlsafe(32))",
    "token_files": [".debug_bridge_token in %LOCALAPPDATA%/ArchHub and repo run dir",
                    "locked to current user (icacls / chmod 600)"],
    "flag": "ARCHHUB_DEBUG_BRIDGE=1 (off by default)",
    "eval": "none — fixed JS expression, selector passed as JSON string literal",
}
