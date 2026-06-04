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
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional


SERVICE_NAME = "ArchHub Brain"
SERVICE_ID = "io.archhub.brain"  # macOS launchd ID
SYSTEMD_UNIT = "archhub-brain.service"
SCHTASKS_NAME = "ArchHub Brain"
DEFAULT_PORT = 8473


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


def _supervise(port: int = DEFAULT_PORT, db: Optional[str] = None) -> dict[str, Any]:
    """Foreground KeepAlive loop — Windows parity with launchd `KeepAlive`
    and systemd `Restart=on-failure`. Spawns the brain daemon as a child and
    RESPAWNS it whenever it exits, with exponential backoff on repeated fast
    failures. Runs until killed; this is the autostart target on Windows so
    the brain stays ALWAYS alive across daemon crashes, not just relaunching
    at logon (founder 2026-06-02: "the brain should be ALWAYS ALIVE")."""
    argv = _build_daemon_argv(port, db)
    # CREATE_NO_WINDOW so each respawn doesn't flash a console.
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    backoff = 2
    while True:
        started = time.monotonic()
        try:
            proc = subprocess.Popen(argv, creationflags=creationflags)
        except Exception:
            time.sleep(min(backoff, 30)); backoff = min(backoff * 2, 30); continue
        proc.wait()  # block until the daemon exits / crashes
        # If it ran a healthy while, reset backoff; if it died fast, back off.
        backoff = 2 if (time.monotonic() - started) > 30 else min(backoff * 2, 30)
        time.sleep(min(backoff, 30))


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
    full_cmd = f'"{sys.executable}" -m personal_brain.service {args}'

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
        vbs = (
            'Dim oShell\n'
            'Set oShell = WScript.CreateObject("WScript.Shell")\n'
            f'oShell.Run "{full_cmd}", 0, False\n'
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
        return fn()
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
