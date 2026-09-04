"""Autostart service wrapper — Windows Service / launchd / systemd.

Per AgDR-0044 §"How brain ships" — ArchHub installer registers the brain
daemon so it autostarts on user login. This module ships the cross-platform
registration logic so the ArchHub installer (or the user) can run:

    python -m personal_brain.service install
    python -m personal_brain.service uninstall
    python -m personal_brain.service status
    python -m personal_brain.service start
    python -m personal_brain.service stop

Mechanism per OS:

  Windows  — schtasks /create /tn "ArchHub Brain" /sc onlogon /rl HIGHEST
             (uses pythonw to avoid console; falls back to sc.exe + nssm
             if --service-mode requested for full Windows Service)
  macOS    — ~/Library/LaunchAgents/io.archhub.brain.plist (launchctl load)
  Linux    — ~/.config/systemd/user/archhub-brain.service (systemctl --user)

Daemon command: `personal-brain --http 8473` (or whatever port the
installer recorded in the brain config).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional


SERVICE_NAME = "ArchHub Brain"
SERVICE_ID = "io.archhub.brain"  # macOS launchd ID
SYSTEMD_UNIT = "archhub-brain.service"
SCHTASKS_NAME = "ArchHub Brain"
DEFAULT_PORT = 8473

# ─────────────────────── supervisor liveness knobs ─────────────────────
# How often the supervisor probes the daemon on :PORT, how many consecutive
# probe failures force a restart, and how long any single probe may block.
# These bound the recovery window. The default keeps the supervisor's
# liveness budget aligned with the bounded BABOOM local Brain read and remains
# overridable via environment when an operator has measured a different host.
HEALTH_INTERVAL_S = float(os.environ.get("BRAIN_SUPERVISE_INTERVAL", "10"))
HEALTH_FAIL_THRESHOLD = int(os.environ.get("BRAIN_SUPERVISE_FAILS", "3"))
HEALTH_TIMEOUT_S = float(os.environ.get("BRAIN_SUPERVISE_TIMEOUT", "12"))
# A respawn after a kill needs a grace period before probing counts again
# (the fresh daemon binds the socket + warms the store).
RESPAWN_GRACE_S = float(os.environ.get("BRAIN_SUPERVISE_GRACE", "12"))


def _supervisor_log_dir() -> Path:
    """Per-OS, user-writable dir for the supervisor's rotating log + the
    watchdog heartbeat file. pythonw has no console, so this file is the
    ONLY window into a wedged supervisor."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ArchHub" / "brain"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "archhub"


def _supervisor_log_path() -> Path:
    return _supervisor_log_dir() / "brain-supervisor.log"


def _heartbeat_path() -> Path:
    return _supervisor_log_dir() / "brain-supervisor.heartbeat"


def _supervisor_state_path() -> Path:
    return _supervisor_log_dir() / "brain-supervisor.state.json"


def _write_supervisor_state(
    *,
    port: int,
    mode: str,
    listener: str,
    child_pid: int | None = None,
    consecutive_failures: int = 0,
) -> None:
    """Persist a bounded local receipt for the supervisor's role.

    This is operational observation, not Brain authority and not a source of
    user context. It lets desktop projections distinguish an adopted listener
    from an owned child without inspecting process command lines.
    """
    if mode not in {"adopting", "waiting", "starting", "owning", "recovering"}:
        return
    if listener not in {"healthy", "occupied", "available"}:
        return
    payload = {
        "schema": "archhub.personal-brain-supervisor/v1",
        "pid": os.getpid(),
        "port": int(port),
        "mode": mode,
        "listener": listener,
        "child_pid": int(child_pid) if isinstance(child_pid, int) and child_pid > 0 else None,
        "consecutive_failures": max(0, int(consecutive_failures)),
        "observed_at": time.time(),
    }
    try:
        path = _supervisor_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(".%s.%s.tmp" % (path.name, os.getpid()))
        temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temp.replace(path)
    except (OSError, TypeError, ValueError):
        return


def _read_supervisor_state() -> dict[str, Any]:
    """Read a validated, non-sensitive supervisor receipt if it is fresh."""
    try:
        raw = json.loads(_supervisor_state_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"state": "unavailable"}
    if not isinstance(raw, dict):
        return {"state": "unavailable"}
    modes = {"adopting", "waiting", "starting", "owning", "recovering"}
    listeners = {"healthy", "occupied", "available"}
    observed_at = raw.get("observed_at")
    if (
        raw.get("schema") != "archhub.personal-brain-supervisor/v1"
        or raw.get("mode") not in modes
        or raw.get("listener") not in listeners
        or not isinstance(observed_at, (int, float))
    ):
        return {"state": "unavailable"}
    return {
        "state": "fresh" if time.time() - float(observed_at) <= max(HEALTH_INTERVAL_S * 2, HEALTH_TIMEOUT_S * 2) else "stale",
        "mode": raw["mode"],
        "listener": raw["listener"],
        "age_seconds": round(max(0.0, time.time() - float(observed_at)), 1),
    }


def _build_supervisor_logger() -> logging.Logger:
    """Rotating file logger so a wedged supervisor is debuggable even under
    pythonw (no stdout/stderr). 1 MB x 3 files. Never raises — falls back to
    a null logger if the dir is unwritable."""
    logger = logging.getLogger("personal_brain.supervisor")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:  # idempotent (re-entry / tests)
        return logger
    try:
        d = _supervisor_log_dir()
        d.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            str(_supervisor_log_path()),
            maxBytes=1_000_000, backupCount=3, encoding="utf-8",
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _touch_heartbeat() -> None:
    """Write a fresh timestamp so an OUTER watchdog (or the founder) can tell
    a live supervisor from a wedged one. Best-effort; never raises."""
    try:
        p = _heartbeat_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _probe_daemon_details(
    port: int,
    timeout: float = HEALTH_TIMEOUT_S,
) -> dict[str, Any] | None:
    """Read a PID-bound liveness reply from the listener, if available.

    A response from another Brain process is operational evidence, not proof
    that this supervisor's child owns the listener. The supervision loop uses
    it to adopt a peer instead of multiplying Brain engines.
    """
    url = f"http://127.0.0.1:{port}/mcp"
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "brain.liveness", "arguments": {}},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = resp.read(8192).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    for line in body.splitlines():
        if not line.lstrip().startswith("data:"):
            continue
        try:
            envelope = json.loads(line.split("data:", 1)[1].strip())
        except (TypeError, ValueError):
            continue
        result = envelope.get("result") if isinstance(envelope, dict) else None
        if not isinstance(result, dict):
            continue
        value = result.get("structuredContent")
        if not isinstance(value, dict):
            for item in result.get("content") or []:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                try:
                    candidate = json.loads(str(item.get("text") or ""))
                except (TypeError, ValueError):
                    continue
                if isinstance(candidate, dict):
                    value = candidate
                    break
        if (
            isinstance(value, dict)
            and value.get("ok") is True
            and isinstance(value.get("server_pid"), int)
            and value["server_pid"] > 0
        ):
            return value
    return None


def _probe_daemon(port: int, timeout: float = HEALTH_TIMEOUT_S) -> bool:
    """REAL liveness check: POST a JSON-RPC `brain.health` to the daemon's
    only HTTP route (`/mcp`, streamable-HTTP SSE) and confirm it answers with
    a 200 and a non-error body. This is strictly stronger than 'is the child
    PID alive' — it catches a daemon that is HUNG (process up, socket bound,
    but not serving), which the old `proc.wait()`-only loop could never see.

    The brain HTTP server exposes ONLY `POST /mcp` (no /healthz GET), so the
    probe speaks the same wire shape ArchHub's BrainClient uses. The urlopen
    timeout bounds how long a wedged daemon can stall the probe, so the
    supervisor loop itself can never hang on a stuck socket."""
    url = f"http://127.0.0.1:{port}/mcp"
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "brain.health", "arguments": {}},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = resp.read(8192).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return False
    # SSE/JSON envelope: a real health answer carries the tool result; a
    # JSON-RPC error frame ("error":) means the daemon answered but the call
    # failed — treat as not-healthy so we restart toward a clean daemon.
    if '"error"' in body and '"result"' not in body:
        return False
    return True


def _listener_is_owned_by_child(
    probe: dict[str, Any] | None,
    child_pid: int,
) -> bool:
    """Return whether a PID-bound liveness reply proves child ownership."""
    return (
        isinstance(probe, dict)
        and isinstance(probe.get("server_pid"), int)
        and probe["server_pid"] == child_pid
    )


def _port_is_bound(port: int) -> bool:
    """Return whether another process may own the Brain listener port.

    This is deliberately an exclusive bind probe rather than a client
    connection. A saturated or wedged listener can stop accepting connections
    while still owning the port. On Windows, a normal bind can appear to work
    alongside a listener that permits address reuse, only for the real daemon
    bind to fail later with WinError 10048. Ask Windows for exclusive address
    use before probing so that ambiguity is treated as occupied. When we
    cannot prove the port is available, we do not compete with the existing
    process.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            exclusive_address_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive_address_use is not None:
                probe.setsockopt(socket.SOL_SOCKET, exclusive_address_use, 1)
        probe.bind(("127.0.0.1", port))
        return False
    except OSError:
        # Safety over a speculative respawn: any bind failure means a
        # competing daemon is not permitted.
        return True
    finally:
        probe.close()


def _existing_daemon_state(port: int) -> str:
    """Classify an already-bound daemon without competing for its socket."""
    if _probe_daemon(port):
        return "healthy"
    return "occupied" if _port_is_bound(port) else "available"


def _supervisor_heartbeat_age_s() -> Optional[float]:
    """Return the supervisor heartbeat age without assuming it owns the daemon."""
    try:
        return max(0.0, time.time() - _heartbeat_path().stat().st_mtime)
    except OSError:
        return None


def _runtime_status(port: int) -> dict[str, Any]:
    """Read-only transport health for operators and assistant projections.

    A fresh supervisor heartbeat proves only that the supervisor loop is
    awake. It does not imply that it owns the live daemon, so lineage is never
    overstated here. Recovery remains an explicit operator action.
    """
    # Prefer the transport-safe identity proof. A legacy daemon can still
    # answer the full diagnostic, but it has not proven its serving process or
    # loaded the current lightweight continuity contract.
    liveness = _probe_daemon_details(port)
    listener = _existing_daemon_state(port)
    if liveness is not None:
        liveness_mode = "pid-bound"
    elif listener == "healthy":
        liveness_mode = "legacy-health"
    else:
        liveness_mode = "unavailable"
    heartbeat_age = _supervisor_heartbeat_age_s()
    heartbeat_fresh = (
        heartbeat_age is not None
        and heartbeat_age <= max(HEALTH_INTERVAL_S * 2, HEALTH_TIMEOUT_S * 2)
    )
    if listener == "healthy" and liveness_mode == "pid-bound":
        health, next_action = "healthy", "none"
    elif listener == "healthy":
        health, next_action = "degraded", "controlled_rollover_required"
    elif listener == "occupied":
        health, next_action = "unresponsive", "controlled_handoff_required"
    else:
        health, next_action = "offline", "start_supervisor_required"
    return {
        "port": port,
        "listener": listener,
        "liveness": liveness_mode,
        "health": health,
        "supervisor_heartbeat": (
            "fresh" if heartbeat_fresh else "stale" if heartbeat_age is not None else "missing"
        ),
        "supervisor_heartbeat_age_s": (
            round(heartbeat_age, 1) if heartbeat_age is not None else None
        ),
        "recovery_action": next_action,
        "supervisor": _read_supervisor_state(),
    }


def _brain_command() -> str:
    """Locate the personal-brain entrypoint. Prefer the entry script
    installed by pip; fall back to `python -m personal_brain.server`."""
    cmd = shutil.which("personal-brain")
    if cmd:
        return cmd
    # Fallback — uses current python interpreter
    return f'"{sys.executable}" -m personal_brain.server'


def _build_daemon_argv(port: int = DEFAULT_PORT, db: Optional[str] = None) -> list[str]:
    """argv (list, no shell) for the brain daemon child process."""
    exe = shutil.which("personal-brain")
    argv = [exe] if exe else [sys.executable, "-m", "personal_brain.server"]
    argv += ["--http", str(port)]
    if db:
        argv += ["--db", db]
    return argv


def _kill_proc(proc: "subprocess.Popen") -> None:
    """Terminate a daemon child, escalating to kill if it ignores SIGTERM.
    Best-effort; never raises."""
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    except Exception:
        pass


def _supervise(port: int = DEFAULT_PORT, db: Optional[str] = None) -> dict[str, Any]:
    """Foreground self-healing supervisor — Windows parity with launchd
    `KeepAlive` and systemd `Restart=on-failure`, but with a REAL liveness
    check the OS supervisors don't give us for free.

    The old loop only did `proc.wait()` — it respawned the daemon when the
    child PID EXITED, but was blind to a daemon that HANGS (process up, socket
    bound, not serving). When that happened on the founder's machine nothing
    restarted it and, because the autostart runs under pythonw with no console
    and no log, there was no way to see why. This rewrite fixes both:

      • LIVENESS — every HEALTH_INTERVAL_S it POSTs `brain.health` to
        127.0.0.1:PORT (the daemon's real `/mcp` route). After
        HEALTH_FAIL_THRESHOLD consecutive failures it KILLS the wedged child
        and respawns a clean one. A crash (PID gone) is also caught and
        respawned immediately.
      • OBSERVABILITY — a rotating log file (pythonw has no stdout) records
        every spawn / probe-failure / kill / respawn / backoff with timestamps,
        so a wedged supervisor is debuggable after the fact.
      • WATCHDOG TIMESTAMP — a heartbeat file is rewritten each loop tick, so
        an OUTER watcher (or the founder) can distinguish a live supervisor
        from a wedged one, and the bounded probe timeout means the loop itself
        can never hang on a stuck socket.

    Runs until killed (founder 2026-06-02: "the brain should be ALWAYS
    ALIVE"). Exponential backoff still guards against a fork-bomb when the
    daemon dies fast on every start."""
    log = _build_supervisor_logger()
    argv = _build_daemon_argv(port, db)
    # CREATE_NO_WINDOW so each respawn doesn't flash a console.
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    log.info("supervisor start: port=%s argv=%s pid=%s log=%s",
             port, argv, os.getpid(), _supervisor_log_path())

    backoff = 2
    while True:
        # A prior direct launch or an older service can legitimately own this
        # endpoint. Adopt a healthy peer; never create a second full Brain
        # engine only to lose the bind race after it has consumed resources.
        existing = _existing_daemon_state(port)
        if existing != "available":
            if existing == "healthy":
                _write_supervisor_state(
                    port=port,
                    mode="adopting",
                    listener=existing,
                )
                log.info(
                    "healthy existing Brain detected on port=%s; "
                    "supervising without a competing child",
                    port,
                )
            else:
                _write_supervisor_state(
                    port=port,
                    mode="waiting",
                    listener=existing,
                )
                log.error(
                    "unhealthy listener already owns port=%s; "
                    "waiting for release instead of spawning a conflicting child",
                    port,
                )
            _touch_heartbeat()
            time.sleep(HEALTH_INTERVAL_S)
            continue
        started = time.monotonic()
        _write_supervisor_state(
            port=port,
            mode="starting",
            listener=existing,
        )
        # ROOT FIX (founder 2026-06-21 — brain "down": daemon died rc=1 ~12s in,
        # over and over). The supervisor runs windowless (pythonw, no console),
        # so a child spawned with no stdout/stderr inherited a None/closed handle;
        # the daemon's first worker print() (the sync worker, ~12s in) then crashed
        # the whole process. Redirect the child's stdout+stderr to a daemon log
        # file (fixes the None-stdout crash AND gives observability); fall back to
        # DEVNULL if the file can't open. stdin=DEVNULL so it never blocks on input.
        try:
            _dlog = open(
                os.path.join(os.path.dirname(_supervisor_log_path()), "brain-daemon.log"),
                "a", buffering=1, encoding="utf-8", errors="replace")
        except Exception:
            _dlog = subprocess.DEVNULL
        try:
            proc = subprocess.Popen(
                argv, creationflags=creationflags,
                stdout=_dlog, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        except Exception as ex:
            wait = min(backoff, 30)
            log.error("spawn failed: %s: %s — backoff %ss",
                      type(ex).__name__, ex, wait)
            _touch_heartbeat()
            time.sleep(wait)
            backoff = min(backoff * 2, 30)
            continue
        log.info("daemon spawned: child_pid=%s", proc.pid)
        _write_supervisor_state(
            port=port,
            mode="starting",
            listener="available",
            child_pid=proc.pid,
        )

        # Give the fresh daemon time to bind the socket + warm up before the
        # first probe counts against it.
        time.sleep(min(RESPAWN_GRACE_S, 30))

        # ── inner liveness loop: probe until the daemon dies or hangs ──────
        consecutive_fail = 0
        died = False
        hung = False
        foreign_listener = False
        while True:
            _touch_heartbeat()
            rc = proc.poll()
            if rc is not None:
                _write_supervisor_state(
                    port=port,
                    mode="recovering",
                    listener=_existing_daemon_state(port),
                    child_pid=proc.pid,
                    consecutive_failures=consecutive_fail,
                )
                log.warning("daemon exited: child_pid=%s rc=%s", proc.pid, rc)
                died = True
                break
            probe = _probe_daemon_details(port)
            if _listener_is_owned_by_child(probe, proc.pid):
                _write_supervisor_state(
                    port=port,
                    mode="owning",
                    listener="healthy",
                    child_pid=proc.pid,
                )
                if consecutive_fail:
                    log.info("daemon healthy again after %s miss(es)",
                             consecutive_fail)
                consecutive_fail = 0
            elif probe:
                listener_pid = probe["server_pid"]
                _write_supervisor_state(
                    port=port,
                    mode="adopting",
                    listener="healthy",
                    child_pid=proc.pid,
                    consecutive_failures=consecutive_fail,
                )
                log.warning(
                    "foreign Brain listener pid=%s answered while child_pid=%s "
                    "was being supervised; stopping duplicate child and adopting peer",
                    listener_pid, proc.pid,
                )
                foreign_listener = True
                break
            else:
                consecutive_fail += 1
                _write_supervisor_state(
                    port=port,
                    mode="recovering",
                    listener="occupied" if _port_is_bound(port) else "available",
                    child_pid=proc.pid,
                    consecutive_failures=consecutive_fail,
                )
                log.warning("health probe miss %s/%s (child_pid=%s)",
                            consecutive_fail, HEALTH_FAIL_THRESHOLD, proc.pid)
                if consecutive_fail >= HEALTH_FAIL_THRESHOLD:
                    log.error("daemon WEDGED (no health for %s probes) — "
                              "killing child_pid=%s and respawning",
                              consecutive_fail, proc.pid)
                    _kill_proc(proc)
                    hung = True
                    break
            time.sleep(HEALTH_INTERVAL_S)

        # Ensure no orphan if we broke out without killing.
        if proc.poll() is None:
            _kill_proc(proc)

        # If it ran a healthy while, reset backoff; if it died/hung fast,
        # back off to avoid a respawn storm.
        ran_for = time.monotonic() - started
        if ran_for > 30:
            backoff = 2
        else:
            backoff = min(backoff * 2, 30)
        wait = min(backoff, 30)
        log.info("respawning in %ss (ran %.1fs, reason=%s)", wait, ran_for,
                 "foreign-listener" if foreign_listener else "hung" if hung else "died" if died else "loop-exit")
        _touch_heartbeat()
        time.sleep(wait)


# ─────────────────────── Windows (Task Scheduler) ──────────────────────


def _windows_install(
    port: int = DEFAULT_PORT,
    db: Optional[str] = None,
    *,
    elevated: bool = False,
) -> dict[str, Any]:
    """Register brain daemon to autostart at user logon.

    Default registers at USER privilege (no admin prompt). Pass
    `elevated=True` to attempt `/rl HIGHEST` — that requires running
    PowerShell as Administrator and will fail with "Access denied"
    otherwise. User-level install survives a normal login + works for
    everything the brain needs (it binds 127.0.0.1, no privileged ports).
    """
    # Autostart the SUPERVISOR (KeepAlive loop), not the bare daemon, so a
    # daemon crash respawns immediately instead of waiting for the next logon.
    args = f'supervise --port {port}' + (f' --db "{db}"' if db else '')
    # Use the WINDOWLESS interpreter (pythonw.exe) for the logon autostart so no
    # console window appears — python.exe always allocates a console; its
    # pythonw.exe sibling does not. Both the schtasks /tr command and the .vbs
    # fallback are built from full_cmd, so deriving it here fixes the whole
    # autostart path. Falls back to sys.executable if pythonw.exe isn't present.
    _pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    _launch_exe = _pyw if os.path.exists(_pyw) else sys.executable
    full_cmd = f'"{_launch_exe}" -m personal_brain.service {args}'

    cmd = [
        "schtasks", "/create",
        "/tn", SCHTASKS_NAME,
        "/tr", full_cmd,
        "/sc", "onlogon",
        "/f",  # force overwrite
    ]
    if elevated:
        cmd.extend(["/rl", "HIGHEST"])

    create = subprocess.run(cmd, capture_output=True, text=True)
    if create.returncode == 0:
        return {
            "platform": "windows-schtasks",
            "ok": True,
            "elevated": elevated,
            "command": full_cmd,
            "stdout": create.stdout.strip(),
            "stderr": create.stderr.strip(),
        }

    # Fallback — drop a Startup-folder shortcut (zero admin needed).
    fallback = _windows_install_startup_folder(full_cmd)
    if fallback.get("ok"):
        return fallback
    return {
        "platform": "windows-schtasks",
        "ok": False,
        "elevated": elevated,
        "command": full_cmd,
        "stdout": create.stdout.strip(),
        "stderr": create.stderr.strip(),
        "fallback_attempted": "startup-folder",
        "fallback_error": fallback.get("error"),
    }


def _startup_folder_path() -> Path:
    """%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"""
    appdata = Path(os.environ.get("APPDATA",
                                    str(Path.home() / "AppData/Roaming")))
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_vbs_path() -> Path:
    return _startup_folder_path() / "ArchHub-Brain.vbs"


def _windows_install_startup_folder(full_cmd: str) -> dict[str, Any]:
    """Write a .vbs shim that launches the brain daemon hidden at logon.
    No admin required. Survives reboots."""
    try:
        folder = _startup_folder_path()
        folder.mkdir(parents=True, exist_ok=True)
        # VBScript escapes a literal " by DOUBLING it (""). full_cmd already
        # wraps the exe path in quotes (needed for schtasks /tr), so it must be
        # escaped before being embedded in the VBScript string literal —
        # otherwise the .vbs emits `oShell.Run ""C:\...python.exe" ...` which
        # VBScript reads as an empty string followed by a bare path → compile
        # error 800A0401 "Expected end of statement" in a logon popup, and the
        # brain never autostarts. Doubling yields the valid
        # `oShell.Run """C:\...python.exe"" ..."`.
        vbs_cmd = full_cmd.replace('"', '""')
        vbs = (
            'Dim oShell\n'
            'Set oShell = WScript.CreateObject("WScript.Shell")\n'
            f'oShell.Run "{vbs_cmd}", 0, False\n'
        )
        path = _startup_vbs_path()
        path.write_text(vbs, encoding="utf-8")
        return {
            "platform": "windows-startup-folder",
            "ok": True,
            "elevated": False,
            "command": full_cmd,
            "path": str(path),
            "note": "ArchHub Brain registered via Startup folder .vbs (no admin needed)",
        }
    except OSError as ex:
        return {"ok": False, "error": str(ex)}


def _windows_uninstall() -> dict[str, Any]:
    # Remove both possible install paths (schtasks + Startup folder).
    r = subprocess.run(
        ["schtasks", "/delete", "/tn", SCHTASKS_NAME, "/f"],
        capture_output=True, text=True,
    )
    startup_removed = False
    try:
        p = _startup_vbs_path()
        if p.exists():
            p.unlink()
            startup_removed = True
    except OSError:
        pass
    return {
        "platform": "windows", "ok": r.returncode == 0 or startup_removed,
        "schtasks_removed": r.returncode == 0,
        "startup_folder_removed": startup_removed,
        "stdout": r.stdout.strip(), "stderr": r.stderr.strip(),
    }


def _windows_status() -> dict[str, Any]:
    r = subprocess.run(
        ["schtasks", "/query", "/tn", SCHTASKS_NAME, "/fo", "LIST"],
        capture_output=True, text=True,
    )
    startup_present = _startup_vbs_path().exists()
    return {
        "platform": "windows",
        "installed": r.returncode == 0 or startup_present,
        "schtasks_present": r.returncode == 0,
        "startup_folder_present": startup_present,
        "startup_folder_path": str(_startup_vbs_path()),
        "details": r.stdout.strip() if r.returncode == 0 else r.stderr.strip(),
    }


def _windows_start() -> dict[str, Any]:
    r = subprocess.run(
        ["schtasks", "/run", "/tn", SCHTASKS_NAME],
        capture_output=True, text=True,
    )
    return {"platform": "windows-schtasks", "ok": r.returncode == 0,
            "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}


def _windows_stop() -> dict[str, Any]:
    r = subprocess.run(
        ["schtasks", "/end", "/tn", SCHTASKS_NAME],
        capture_output=True, text=True,
    )
    return {"platform": "windows-schtasks", "ok": r.returncode == 0,
            "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}


# ─────────────────────── macOS (launchd) ───────────────────────────────


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_ID}.plist"


def _macos_install(port: int = DEFAULT_PORT, db: Optional[str] = None) -> dict[str, Any]:
    brain = _brain_command()
    args = ["--http", str(port)] + (["--db", db] if db else [])
    program_args = "".join(
        f"        <string>{a}</string>\n"
        for a in [brain.strip('"')] + args
    )
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{SERVICE_ID}</string>
    <key>ProgramArguments</key>
    <array>
{program_args}    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/Library/Logs/archhub-brain.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/Library/Logs/archhub-brain.err.log</string>
</dict>
</plist>
"""
    path = _macos_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")

    r = subprocess.run(
        ["launchctl", "load", "-w", str(path)],
        capture_output=True, text=True,
    )
    return {
        "platform": "macos-launchd",
        "ok": r.returncode == 0,
        "plist_path": str(path),
        "stdout": r.stdout.strip(), "stderr": r.stderr.strip(),
    }


def _macos_uninstall() -> dict[str, Any]:
    path = _macos_plist_path()
    r = subprocess.run(
        ["launchctl", "unload", "-w", str(path)],
        capture_output=True, text=True,
    )
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    return {
        "platform": "macos-launchd",
        "ok": r.returncode == 0 or not path.exists(),
        "stdout": r.stdout.strip(), "stderr": r.stderr.strip(),
    }


def _macos_status() -> dict[str, Any]:
    r = subprocess.run(
        ["launchctl", "list", SERVICE_ID],
        capture_output=True, text=True,
    )
    return {
        "platform": "macos-launchd",
        "installed": r.returncode == 0,
        "details": r.stdout.strip(),
    }


def _macos_start() -> dict[str, Any]:
    r = subprocess.run(
        ["launchctl", "start", SERVICE_ID],
        capture_output=True, text=True,
    )
    return {"platform": "macos-launchd", "ok": r.returncode == 0}


def _macos_stop() -> dict[str, Any]:
    r = subprocess.run(
        ["launchctl", "stop", SERVICE_ID],
        capture_output=True, text=True,
    )
    return {"platform": "macos-launchd", "ok": r.returncode == 0}


# ─────────────────────── Linux (systemd --user) ────────────────────────


def _linux_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT


def _linux_install(port: int = DEFAULT_PORT, db: Optional[str] = None) -> dict[str, Any]:
    brain = _brain_command()
    args = f"--http {port}" + (f" --db {db}" if db else "")
    unit = f"""[Unit]
Description=ArchHub Personal Brain MCP daemon
After=default.target

[Service]
Type=simple
ExecStart={brain} {args}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    path = _linux_unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit, encoding="utf-8")

    daemon = subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True, text=True,
    )
    enable = subprocess.run(
        ["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT],
        capture_output=True, text=True,
    )
    return {
        "platform": "linux-systemd",
        "ok": enable.returncode == 0,
        "unit_path": str(path),
        "daemon_reload": daemon.returncode == 0,
        "stdout": enable.stdout.strip(), "stderr": enable.stderr.strip(),
    }


def _linux_uninstall() -> dict[str, Any]:
    r = subprocess.run(
        ["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT],
        capture_output=True, text=True,
    )
    path = _linux_unit_path()
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    subprocess.run(["systemctl", "--user", "daemon-reload"],
                    capture_output=True, text=True)
    return {
        "platform": "linux-systemd",
        "ok": r.returncode == 0 or not path.exists(),
        "stdout": r.stdout.strip(), "stderr": r.stderr.strip(),
    }


def _linux_status() -> dict[str, Any]:
    r = subprocess.run(
        ["systemctl", "--user", "status", SYSTEMD_UNIT, "--no-pager"],
        capture_output=True, text=True,
    )
    return {
        "platform": "linux-systemd",
        # systemctl exit code 0=active, 3=inactive, 4=not found
        "installed": r.returncode in (0, 3),
        "active": r.returncode == 0,
        "details": r.stdout.strip()[-400:],
    }


def _linux_start() -> dict[str, Any]:
    r = subprocess.run(
        ["systemctl", "--user", "start", SYSTEMD_UNIT],
        capture_output=True, text=True,
    )
    return {"platform": "linux-systemd", "ok": r.returncode == 0,
            "stderr": r.stderr.strip()}


def _linux_stop() -> dict[str, Any]:
    r = subprocess.run(
        ["systemctl", "--user", "stop", SYSTEMD_UNIT],
        capture_output=True, text=True,
    )
    return {"platform": "linux-systemd", "ok": r.returncode == 0,
            "stderr": r.stderr.strip()}


# ─────────────────────── dispatcher ────────────────────────────────────


def _platform() -> str:
    s = platform.system().lower()
    if "windows" in s:
        return "windows"
    if "darwin" in s:
        return "macos"
    return "linux"


_DISPATCH = {
    ("windows", "install"):   _windows_install,
    ("windows", "uninstall"): _windows_uninstall,
    ("windows", "status"):    _windows_status,
    ("windows", "start"):     _windows_start,
    ("windows", "stop"):      _windows_stop,
    ("macos",   "install"):   _macos_install,
    ("macos",   "uninstall"): _macos_uninstall,
    ("macos",   "status"):    _macos_status,
    ("macos",   "start"):     _macos_start,
    ("macos",   "stop"):      _macos_stop,
    ("linux",   "install"):   _linux_install,
    ("linux",   "uninstall"): _linux_uninstall,
    ("linux",   "status"):    _linux_status,
    ("linux",   "start"):     _linux_start,
    ("linux",   "stop"):      _linux_stop,
}


def run(
    action: str,
    *,
    port: int = DEFAULT_PORT,
    db: Optional[str] = None,
    elevated: bool = False,
) -> dict[str, Any]:
    # `supervise` is platform-agnostic + BLOCKS (runs the KeepAlive loop until
    # killed). Handle before the platform dispatch.
    if action == "supervise":
        return _supervise(port=port, db=db)
    plat = _platform()
    fn = _DISPATCH.get((plat, action))
    if fn is None:
        return {"ok": False, "error": f"unsupported action '{action}' on {plat}"}
    try:
        if action == "install":
            if plat == "windows":
                return fn(port=port, db=db, elevated=elevated)
            return fn(port=port, db=db)
        result = fn()
        if action == "status":
            result["runtime"] = _runtime_status(port)
        return result
    except FileNotFoundError as ex:
        return {"ok": False, "error": f"required binary not found: {ex}"}


# ─────────────────────── CLI ───────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="personal-brain service")
    parser.add_argument("action",
                         choices=["install", "uninstall", "status",
                                  "start", "stop", "supervise"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=str, default=None)
    parser.add_argument("--elevated", action="store_true",
                         help="Windows: request /rl HIGHEST (needs admin)")
    args = parser.parse_args(argv)

    result = run(args.action, port=args.port, db=args.db,
                  elevated=args.elevated)
    import json as _json
    print(_json.dumps(result, indent=2))
    return 0 if result.get("ok") or result.get("installed") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
