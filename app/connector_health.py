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
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


PROBE_INTERVAL_SECONDS = 5.0
PROBE_TIMEOUT_SECONDS = 0.6


# Family → localhost MCP listener URL.
LISTENER_URL = {
    "revit":   "http://localhost:48884/ping",
    "autocad": "http://localhost:48885/ping",
    "max":     "http://localhost:48886/ping",
    "blender": "http://localhost:9876/ping",
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


def _probe_listener(family: str) -> tuple[bool, str]:
    """Single-port probe (used for autocad/max/blender)."""
    url = LISTENER_URL.get(family)
    if not url:
        return False, "no listener url"
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
    """
    try:
        import revit_broker
        sessions = revit_broker.list_sessions(prune=True)
        alive = sum(1 for s in sessions if s.healthy)
        if alive >= 1:
            return True, "", alive
        if sessions:
            return False, "all sessions stale", 0
        # No session files — fall back to legacy single-port probe so
        # an old DLL still surfaces correctly.
        ok, err = _probe_listener("revit")
        return ok, err, 1 if ok else 0
    except Exception as e:
        # Broker import / scan failed — fall back to single-port probe.
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

    def stop(self) -> None:
        self._stop.set()

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
