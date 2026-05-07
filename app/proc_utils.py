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
"""
from __future__ import annotations

import subprocess
import sys


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
