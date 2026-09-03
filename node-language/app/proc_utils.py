"""Subprocess helpers — never flash a console window.

Windows console-attached child processes (cmd.exe, python.exe spawned
by subprocess.Popen) flash a black box even with `pythonw.exe` as the
parent. Callers must pass `creationflags=CREATE_NO_WINDOW` (and
optionally a STARTUPINFO with hidden window) on every Popen / run,
or the box flashes.

This module wraps the noisy boilerplate:

    from proc_utils import run_hidden, popen_hidden
    run_hidden(["git", "status"], capture_output=True)
    popen_hidden([sys.executable, "-m", "agents.run", "--cycle", "300"])

Falls back gracefully on non-Windows.

Also home of the shared process-name snapshot (process_names /
any_process_running): ONE TTL-cached enumeration serves every
"is <host>.exe running?" caller, instead of one ~620ms `tasklist /FI`
subprocess per check.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time


def _hidden_kwargs() -> dict:
    """Return Windows-specific kwargs that suppress the console window."""
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0           # SW_HIDE
    return {"creationflags": flags, "startupinfo": si}


def run_hidden(args, **kwargs):
    """`subprocess.run` with no console window. Caller sets timeout/text/etc."""
    kwargs.setdefault("text", True)
    kwargs.update(_hidden_kwargs())
    return subprocess.run(args, **kwargs)


def popen_hidden(args, **kwargs):
    """`subprocess.Popen` with no console window."""
    kwargs.update(_hidden_kwargs())
    return subprocess.Popen(args, **kwargs)


# ---------------------------------------------------------------------------
# Shared process-name snapshot.
#
# Measured 2026-06-11 (Windows 11, loaded box): one `tasklist /FI` spawn costs
# ~620ms, so five per-name checks inside a single health tick burned ~3.1s.
# One enumeration of ALL processes (~1.2s tasklist, faster via warm psutil)
# cached for a short TTL serves every caller in that window.
_PROC_TTL_S = 2.0

_proc_lock = threading.Lock()
_proc_names: frozenset[str] = frozenset()
_proc_fetched_at: float = float("-inf")     # time.monotonic; -inf = never


def _enumerate_process_names(timeout: float) -> frozenset[str]:
    """One uncached enumeration pass — lower-cased image names.

    Preference: psutil (warm-fast, no console flash) → tasklist (Windows) /
    ps (POSIX) via run_hidden → frozenset() on any failure (callers treat
    unknown as not-running).
    """
    try:
        import psutil
        return frozenset(
            (p.info.get("name") or "").lower()
            for p in psutil.process_iter(["name"])
        )
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            r = run_hidden(["tasklist", "/FO", "CSV", "/NH"],
                           capture_output=True, timeout=timeout)
            return frozenset(
                line.split(",", 1)[0].strip().strip('"').lower()
                for line in (r.stdout or "").splitlines()
                if line.strip()
            )
        r = run_hidden(["ps", "-eo", "comm="],
                       capture_output=True, timeout=timeout)
        return frozenset(
            line.strip().rsplit("/", 1)[-1].lower()
            for line in (r.stdout or "").splitlines()
            if line.strip()
        )
    except Exception:
        return frozenset()


def process_names(*, ttl: float = _PROC_TTL_S, timeout: float = 2.0) -> frozenset[str]:
    """Lower-cased image names of every running process, TTL-cached.

    The lock is held across the fetch (single-flight): a stampede of callers
    costs ONE enumeration, not N — late arrivals block briefly, then read the
    fresh snapshot. An enumeration failure returns frozenset() and is cached
    for the TTL too, so a broken enumerator cannot turn into a spawn storm.
    """
    global _proc_names, _proc_fetched_at
    with _proc_lock:
        if time.monotonic() - _proc_fetched_at >= ttl:
            _proc_names = _enumerate_process_names(timeout)
            _proc_fetched_at = time.monotonic()
        return _proc_names


def any_process_running(*needles: str, ttl: float = _PROC_TTL_S) -> bool:
    """True iff any lower-cased needle is a substring of a running process name."""
    names = process_names(ttl=ttl)
    wanted = tuple(n.lower() for n in needles if n)
    return any(w in name for name in names for w in wanted)


def _reset_process_snapshot_for_tests() -> None:
    """Zero the TTL cache so tests control freshness."""
    global _proc_names, _proc_fetched_at
    with _proc_lock:
        _proc_names = frozenset()
        _proc_fetched_at = float("-inf")
