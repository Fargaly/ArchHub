"""Start the existing Brain supervisor when nothing answers on the Brain port.

Founder report 2026-09-23: the Brain stopped answering on 127.0.0.1:8473 on
09-21 and nothing started it again. The launcher asks once per start, off the
boot path. This module only ever starts the existing supervisor
(``personal_brain.service supervise``); it never stops, kills or replaces a
Brain, and it never deletes or releases the ambient suspension marker. The
supervisor adopts a healthy Brain itself. The Brain server keeps its ambient
services paused while ``LOCALAPPDATA/ArchHub/brain/ambient-runtime.suspended``
exists and still serves ``/mcp`` (``brain.health`` and its tools).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BRAIN_PORT = 8473
SUPERVISOR_MODULE = "personal_brain.service"
SUSPENSION_MARKER = "ambient-runtime.suspended"
HEARTBEAT_FILE = "brain-supervisor.heartbeat"
# The supervisor rewrites its heartbeat every 10 s; two misses and a margin.
HEARTBEAT_FRESH_SECONDS = 30.0


def brain_answers(port: int = BRAIN_PORT, timeout: float = 3.0) -> bool:
    """The Brain's health question, asked the way its supervisor asks it.

    The Brain HTTP server exposes only POST /mcp, so health is the JSON-RPC
    tools/call ``brain.health`` answered with a result, not a GET.
    """
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "brain.health", "arguments": {}}}).encode("utf-8")
    request = urllib.request.Request("http://127.0.0.1:%d/mcp" % int(port), data=payload,
        method="POST", headers={"Content-Type": "application/json",
                                "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            body = response.read(8192).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return not ('"error"' in body and '"result"' not in body)


def brain_directory(local_appdata: str | os.PathLike | None = None) -> Path:
    root = local_appdata if local_appdata is not None else os.environ.get("LOCALAPPDATA", "")
    return Path(root) / "ArchHub" / "brain"


def _heartbeat_fresh(directory: Path, now: float) -> bool:
    try:
        beat = float((directory / HEARTBEAT_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return 0 <= now - beat <= HEARTBEAT_FRESH_SECONDS


def _windowless_python() -> str:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.is_file() else sys.executable


def _spawn(argv: list[str], cwd: Path) -> subprocess.Popen:
    # The launcher's own directory ships a thin personal_brain package; the
    # supervisor must resolve the installed Brain, so it runs from the Brain
    # directory with this process's import path left behind.
    environment = {key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"}
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return subprocess.Popen(argv, cwd=str(cwd), env=environment, close_fds=True, creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_brain_supervisor(*, port: int = BRAIN_PORT, probe=brain_answers, spawn=_spawn,
                            local_appdata=None, python: str | None = None, now=time.time,
                            settle_seconds: float = 3.0, sleep=time.sleep) -> dict:
    """Start the supervisor if the Brain is silent and no supervisor is alive.

    Returns what was done and why, for one status line. ``ambient_suspended``
    reports the marker; it is read, never changed.
    """
    directory = brain_directory(local_appdata)
    suspended = (directory / SUSPENSION_MARKER).is_file()
    outcome = {"ambient_suspended": suspended, "port": int(port)}
    if probe(port):
        return {**outcome, "action": "none", "reason": "the Brain answers brain.health"}
    if _heartbeat_fresh(directory, now()):
        return {**outcome, "action": "none", "reason": "a Brain supervisor is already running"}
    directory.mkdir(parents=True, exist_ok=True)
    argv = [python or _windowless_python(), "-m", SUPERVISOR_MODULE, "supervise", "--port", str(int(port))]
    process = spawn(argv, directory)
    outcome.update(argv=argv, pid=getattr(process, "pid", None))
    if settle_seconds > 0:
        sleep(settle_seconds)
    code = process.poll() if hasattr(process, "poll") else None
    if code is not None:
        return {**outcome, "action": "not started",
                "reason": "the Brain supervisor exited with code %s (is personal_brain installed?)" % code}
    return {**outcome, "action": "started", "reason": "the Brain was silent; its supervisor is starting it"}
