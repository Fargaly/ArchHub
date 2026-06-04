"""Connector health daemon — single source of truth for 'is the listener actually up'.

Replaces the lie surface where ConnectorEntry.state == ACTIVE meant
'registry/manifest written' instead of 'listener responding'. Now:

  ConnectorHealth.state(family)
    -> 'live'           — listener responded within the last probe.
    -> 'loaded_dead'    — registry active but listener dead. Self-
                           heal triggered for AutoCAD / Revit if the
                           host process is alive.
    -> 'host_offline'   — registry active, host process not running.
    -> 'inactive'       — registry not active.
    -> 'unknown'        — never probed yet.

Probes every PROBE_INTERVAL_SECONDS in a single background thread.
Status bar / connector panel / Reality Check / chat all read from
this one source.

Self-heal logic per family:
  autocad  — when host alive + listener dead, fire COM NETLOAD via
             SendStringToExecute. Backoff: 5s, 30s, 5min, then give
             up + emit 'manual_netload_required'.
  revit    — restart Revit OR re-toggle connector are the only
             options; we don't auto-do either. Surface clean status.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


PROBE_INTERVAL_SECONDS = 5.0
PROBE_TIMEOUT_SECONDS = 0.6


# Family → loopback MCP listener URL.
#
# IMPORTANT: these are pinned to 127.0.0.1, NOT "localhost". On Windows
# "localhost" resolves to BOTH ::1 (IPv6, first) and 127.0.0.1 (IPv4), and
# urllib's create_connection applies the socket timeout PER resolved address
# sequentially — so a probe of a dead port via "localhost" blocks for
# 2 × PROBE_TIMEOUT_SECONDS (the ::1 attempt times out, THEN the 127.0.0.1
# attempt times out) instead of one. That doubled, unbounded-feeling stall is
# what wedged the poll thread mid-probe so stop()'s join() timed out and the
# daemon leaked into the next test's teardown (see _probe_listener + stop()).
# Pinning to a single IPv4 loopback makes every probe cost ≤ one timeout.
LISTENER_URL = {
    "revit":   "http://127.0.0.1:48884/ping",
    "autocad": "http://127.0.0.1:48885/ping",
    "max":     "http://127.0.0.1:48886/ping",
    "blender": "http://127.0.0.1:9876/ping",
}

# Family → host process name (for 'is the host even running?').
HOST_PROCESS = {
    "revit":   "Revit.exe",
    "autocad": "acad.exe",
    "max":     "3dsmax.exe",
    "blender": "blender.exe",
}


@dataclass
class _FamilyState:
    last_listener_ok: Optional[bool] = None     # None = never probed
    last_probe_ts: float = 0.0
    last_listener_ok_ts: float = 0.0
    netload_attempts: int = 0
    next_netload_ts: float = 0.0
    last_error: str = ""
    # Multi-session families (revit since v0.27.5): how many sessions
    # are currently alive. 0 means none; 1+ means live.
    sessions: int = 0


def _hidden_run(args: list[str], **kw):
    """Run subprocess without flashing a console window."""
    if sys.platform == "win32":
        kw.setdefault("creationflags",
                      getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kw.setdefault("startupinfo", si)
    return subprocess.run(args, **kw)


def _process_running(name: str) -> bool:
    try:
        r = _hidden_run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=2,
        )
        return name.lower() in (r.stdout or "").lower()
    except Exception:
        return False


def _port_open(host: str, port: int, timeout: float) -> bool:
    """Hard-bounded TCP connect. Returns True iff something is listening.

    `socket.create_connection` with an explicit timeout bounds the connect at
    the OS level — a refused port returns in ~ms (ConnectionRefused), and an
    unreachable/filtered one can NEVER exceed `timeout`. This is the guarantee
    `urllib.request.urlopen` did not give us: urlopen's timeout is per resolved
    address, so a dual-stack hostname (localhost → ::1 then 127.0.0.1) doubled
    the wait and could wedge the poll thread past stop()'s join. We connect to
    a single pinned IPv4 loopback here so the upper bound is exactly `timeout`.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_listener(family: str) -> tuple[bool, str]:
    """Single-port probe (used for autocad/max/blender).

    Two-stage + hard-bounded so a single probe can NEVER block longer than
    PROBE_TIMEOUT_SECONDS: (1) a bounded TCP connect to the pinned 127.0.0.1
    loopback — a dead port refuses instantly, an unreachable one is capped by
    the connect timeout; (2) only if the port is open do we pay for the HTTP
    GET (also bounded). Bounding the probe is the root fix for the leaked
    poll thread: the loop now always returns to its stop-event check within
    one timeout, so stop()'s join reliably wins and the daemon cannot survive
    teardown."""
    url = LISTENER_URL.get(family)
    if not url:
        return False, "no listener url"
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
    except Exception:
        return False, "bad listener url"
    # Stage 1: bounded TCP pre-connect. Closed port → instant, honest 'down'
    # with no HTTP cost and no chance of a multi-address stall.
    if not _port_open(host, port, PROBE_TIMEOUT_SECONDS):
        return False, "closed"
    # Stage 2: port is open — confirm it actually speaks HTTP / 2xx.
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as r:
            return (200 <= r.status < 300, "")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (socket.timeout, TimeoutError):
        return False, "timeout"
    except OSError as e:
        return False, str(e.__class__.__name__)
    except Exception as e:
        return False, str(e)[:80]


def _probe_revit_multi() -> tuple[bool, str, int]:
    """Multi-session probe — Revit since v0.27.5 binds one port per
    instance and publishes a session file. We're 'live' if at least
    one session responds. Returns (ok, error_or_count_label, count).

    MUST stay hard-bounded: this runs on the 5s poll thread, and a probe
    that blocks longer than ConnectorHealth.stop()'s join makes the daemon
    leak past teardown. We therefore use revit_broker.live_session_count()
    — a bounded session-file read + one 127.0.0.1 TCP connect per known
    port — NOT list_sessions(prune=True), whose cold parallel 16-port
    range scan over dual-stack `localhost` measured ~2.4s and was the root
    of the leaked-poll-thread regression. Full discovery + prune still runs
    in the UI's explicit session enumeration (off this thread).
    """
    try:
        import revit_broker
        alive = revit_broker.live_session_count(timeout=PROBE_TIMEOUT_SECONDS)
        if alive >= 1:
            return True, "", alive
        # No live session file — fall back to the bounded legacy single-port
        # probe so an old DLL (no session file) still surfaces correctly.
        ok, err = _probe_listener("revit")
        return ok, err, 1 if ok else 0
    except Exception:
        # Broker import / read failed — fall back to single-port probe.
        ok, err = _probe_listener("revit")
        return ok, err, 1 if ok else 0


# ---------------------------------------------------------------------------
class ConnectorHealth:
    """Singleton-style health monitor. One thread, polls every 5s."""

    def __init__(self, *, manager=None):
        self.manager = manager
        self._state: dict[str, _FamilyState] = {
            f: _FamilyState() for f in LISTENER_URL.keys()
        }
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.on_state_change: Optional[Callable[[str, str], None]] = None

    # ---- public API ------------------------------------------------------
    def state(self, family: str) -> str:
        s = self._state.get(family)
        if s is None or s.last_listener_ok is None:
            return "unknown"
        if s.last_listener_ok:
            return "live"
        # Listener dead — diagnose deeper.
        host = HOST_PROCESS.get(family)
        if host and _process_running(host):
            return "loaded_dead"
        return "host_offline"

    def info(self, family: str) -> dict:
        s = self._state.get(family)
        if s is None:
            return {"family": family, "state": "unknown"}
        return {
            "family": family,
            "state": self.state(family),
            "last_probe_ts": s.last_probe_ts,
            "last_listener_ok_ts": s.last_listener_ok_ts,
            "netload_attempts": s.netload_attempts,
            "last_error": s.last_error[:120],
            "sessions": s.sessions,
        }

    def snapshot(self) -> dict[str, dict]:
        return {f: self.info(f) for f in self._state.keys()}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        t = threading.Thread(target=self._loop, daemon=True,
                             name="ConnectorHealth")
        t.start()
        self._thread = t

    def stop(self, *, join_timeout: float = 2.0) -> None:
        """Signal the poll loop to exit AND wait for the thread to die.

        Joining matters: without it the daemon can still service one more
        `urllib.request.urlopen` probe before noticing the stop event,
        which is exactly how a leaked monitor inflated an unrelated test's
        urlopen mock. Callers (real shutdown OR test teardown) get a thread
        that is provably no longer polling once `stop()` returns.

        Why the join now RELIABLY wins (the leak that c98fd35 didn't fully
        close): c98fd35 added this join, but assumed the thread would notice
        the stop event quickly. It didn't — a tick was wedged in an unbounded
        dual-stack `localhost` connect (::1 then 127.0.0.1, each up to the
        timeout), so a single tick could outlast a 2s join and the daemon
        survived teardown. Now every probe is hard-bounded to one
        PROBE_TIMEOUT_SECONDS (pinned IPv4 + bounded TCP pre-connect) AND
        `_tick_once` re-checks the stop event before each family — so once
        `_stop` is set the thread returns to the loop's wait within a single
        bounded probe, comfortably inside `join_timeout`.
        """
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=join_timeout)
        self._thread = None

    # ---- inner loop ------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.wait(PROBE_INTERVAL_SECONDS):
            try:
                self._tick_once()
            except Exception:
                pass

    def _tick_once(self) -> None:
        now = time.time()
        for family in self._state.keys():
            # Bail out the instant a stop is requested. Each probe is now
            # hard-bounded (see _probe_listener), so the longest a stop can
            # wait is one probe — well inside stop()'s join timeout. This is
            # what makes the daemon un-leakable: it always returns to the
            # stop-event check promptly, never wedged across teardown.
            if self._stop.is_set():
                return
            if family == "revit":
                ok, err, sessions = _probe_revit_multi()
            else:
                ok, err = _probe_listener(family)
                sessions = 1 if ok else 0
            with self._lock:
                s = self._state[family]
                prev = s.last_listener_ok
                s.last_listener_ok = ok
                s.last_probe_ts = now
                s.sessions = sessions
                if ok:
                    s.last_listener_ok_ts = now
                    s.netload_attempts = 0
                    s.next_netload_ts = 0.0
                    s.last_error = ""
                else:
                    s.last_error = err
            # Self-heal hooks (outside lock).
            if not ok:
                self._maybe_self_heal(family, now)
            # Persist a state tick so the Reality Check sparkline has
            # data to draw — edge-only inside health_history.record so
            # flat runs don't bloat the buffer.
            try:
                from health_history import record as _hh_record
                _hh_record(family, self.state(family))
            except Exception:
                pass
            if self.on_state_change and prev != ok:
                try:
                    self.on_state_change(family, "live" if ok else "down")
                except Exception:
                    pass

    def _maybe_self_heal(self, family: str, now: float) -> None:
        """For AutoCAD: try NETLOAD via COM with backoff (5s, 30s, 5min)."""
        if family != "autocad":
            return
        host = HOST_PROCESS.get(family)
        if not host or not _process_running(host):
            return
        with self._lock:
            s = self._state[family]
            if now < s.next_netload_ts:
                return
            attempts = s.netload_attempts
            if attempts >= 3:
                # Give up; user must NETLOAD manually or restart AutoCAD.
                return
            s.netload_attempts += 1
            # Exponential-ish backoff: 5s, 30s, 5min after each attempt.
            backoff = (5.0, 30.0, 300.0)[min(attempts, 2)]
            s.next_netload_ts = now + backoff
        # Fire NETLOAD attempt off the lock so we don't hold the
        # health thread on a slow COM dispatch.
        threading.Thread(
            target=self._try_acad_netload,
            args=(attempts + 1,),
            daemon=True,
            name=f"AcadNetload-{attempts + 1}",
        ).start()

    def _try_acad_netload(self, attempt: int) -> None:
        """Single COM NETLOAD attempt. Logs result, never raises.

        CRITICAL: every thread that dispatches COM MUST call
        pythoncom.CoInitialize() first and CoUninitialize at the end.
        Skipping either side crashes Qt6Core (0xc0000409) the next
        time the main thread services its event loop. Learned the
        hard way."""
        dll = (Path(__file__).resolve().parent.parent
               / "AutoCAD" / "2026" / "AcadMCP.dll")
        import os as _os
        local_app = Path(_os.environ.get("LOCALAPPDATA", str(Path.home())))
        installed_dll = local_app / "ArchHub" / "AutoCAD" / "2026" / "AcadMCP.dll"
        if installed_dll.exists():
            dll = installed_dll
        if not dll.exists():
            return
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            return
        try:
            import win32com.client as w
            acad = w.GetActiveObject("AutoCAD.Application")
            doc = acad.ActiveDocument
            lisp_path = str(dll).replace("\\", "/")
            cmd = '(command "_NETLOAD" "' + lisp_path + '") '
            sender = getattr(doc, "SendCommand", None)
            if sender is None:
                return
            sender(cmd)
            time.sleep(2.0)
            ok, _ = _probe_listener("autocad")
            if ok:
                with self._lock:
                    s = self._state["autocad"]
                    s.last_listener_ok = True
                    s.last_listener_ok_ts = time.time()
                    s.netload_attempts = 0
                    s.last_error = ""
        except Exception as ex:
            with self._lock:
                self._state["autocad"].last_error = (
                    f"netload attempt {attempt}: {type(ex).__name__}"
                )
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass


# Module-level singleton — built lazily so import-time stays cheap.
_INSTANCE: Optional[ConnectorHealth] = None


def instance() -> ConnectorHealth:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ConnectorHealth()
        _INSTANCE.start()
    return _INSTANCE


def shutdown() -> None:
    """Stop + join the singleton's poll thread and drop the instance.

    The monitor is a process-global daemon thread that polls the shared
    `urllib.request.urlopen`. Anything that spins it up (the app on close,
    a test that constructs a UI surface) MUST be able to halt it cleanly so
    it cannot keep ticking into later work — e.g. a subsequent test's
    urlopen mock. Safe to call when no instance exists (no-op).
    """
    global _INSTANCE
    inst = _INSTANCE
    if inst is not None:
        inst.stop()
    _INSTANCE = None
