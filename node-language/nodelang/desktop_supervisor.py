"""Crash-recovering owner for the visible ArchHub desktop worker."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from .persistence import default_state_path


def supervisor_lock_path() -> Path:
    return default_state_path().with_name("desktop-supervisor.lock")


def lifecycle_path() -> Path:
    return default_state_path().with_name("desktop-lifecycle.json")


def crash_history_path() -> Path:
    return default_state_path().with_name("desktop-crashes.jsonl")


def write_lifecycle(status: str, *, attempt: str = "", exit_code=None,
                    detail: str = "") -> dict:
    payload = {
        "attempt": attempt or os.environ.get("ARCHHUB_DESKTOP_ATTEMPT", ""),
        "status": status,
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if exit_code is not None:
        payload["exit_code"] = int(exit_code)
    if detail:
        payload["detail"] = str(detail)[:500]
    path = lifecycle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    return payload


def read_lifecycle() -> dict:
    try:
        value = json.loads(lifecycle_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def classify_worker_exit(receipt: dict, attempt: str, exit_code: int) -> str:
    """Return stop only for a clean, matching worker receipt."""
    if receipt.get("attempt") != attempt:
        return "restart"
    if receipt.get("status") in {"clean", "already-running"} and exit_code == 0:
        return "stop"
    return "restart"


def _runtime_state(url: str) -> dict:
    try:
        value = json.loads(urllib.request.urlopen(
            url.rstrip("/") + "/api/state", timeout=2.0).read())
        return {
            "runtime_ok": value.get("ok") is True,
            "graph_valid": value.get("valid") is True,
            "schema_version": value.get("schema_version"),
            "node_count": value.get("node_count"),
        }
    except Exception as exc:
        return {"runtime_ok": False, "graph_valid": False,
                "runtime_error": type(exc).__name__}


def _append_crash(attempt: str, exit_code: int, restart_count: int,
                  runtime_url: str) -> None:
    payload = {
        "attempt": attempt,
        "exit_code": int(exit_code),
        "restart_count": int(restart_count),
        "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **_runtime_state(runtime_url),
    }
    path = crash_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--desktop-worker"]
    return [sys.executable, "-m", "nodelang.desktop"]


def supervise(*, runtime_url: str = "http://127.0.0.1:8482",
              max_crashes: int = 5, crash_window_seconds: float = 60.0,
              restart_delay: float = 0.75) -> int:
    from PyQt6.QtCore import QLockFile

    lock_path = supervisor_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        return 0

    crash_times: list[float] = []
    restart_count = 0
    try:
        while True:
            attempt = uuid.uuid4().hex
            environment = dict(os.environ)
            environment["ARCHHUB_DESKTOP_ATTEMPT"] = attempt
            write_lifecycle("starting", attempt=attempt)
            worker = subprocess.Popen(_worker_command(), env=environment)
            exit_code = worker.wait()
            receipt = read_lifecycle()
            if classify_worker_exit(receipt, attempt, exit_code) == "stop":
                return exit_code

            restart_count += 1
            _append_crash(attempt, exit_code, restart_count, runtime_url)
            now = time.monotonic()
            crash_times = [stamp for stamp in crash_times
                           if now - stamp <= crash_window_seconds]
            crash_times.append(now)
            if len(crash_times) >= max_crashes:
                write_lifecycle("recovery-paused", attempt=attempt,
                                exit_code=exit_code,
                                detail="desktop crash-loop court closed")
                return exit_code or 1
            time.sleep(restart_delay)
    finally:
        lock.unlock()
