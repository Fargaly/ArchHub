#!/usr/bin/env python
"""Install and audit ArchHub governed agent sessions.

This is the non-technical bootstrap for "new sessions are governed by
default":

* repair native Brain hooks through personal_brain.installer;
* add PowerShell profile functions so typing codex/claude/gemini/etc. routes
  through brainwrap launch --governed-strict;
* create cmd.exe shims for commands that can be resolved now; and
* audit currently running agent sessions and report which must be restarted.

Already-running processes cannot be hot-patched into a new environment block.
They are audited and recorded; future processes are launched governed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional


PROFILE_BEGIN = "# >>> ARCHHUB GOVERNED SESSIONS >>>"
PROFILE_END = "# <<< ARCHHUB GOVERNED SESSIONS <<<"
DEFAULT_COMMANDS = (
    "codex",
    "claude",
    "claude-code",
    "gemini",
    "aider",
    "cursor",
    "windsurf",
    "antigravity",
)
PRIMARY_DESKTOP_APP_NAMES = {
    "codex.exe",
    "claude.exe",
    "antigravity.exe",
}
PRIMARY_DESKTOP_APP_LABELS = {
    "codex.exe": "Codex",
    "claude.exe": "Claude",
    "antigravity.exe": "Antigravity",
}
IFEO_UNSAFE_MULTIPROCESS_APPS = {"Codex", "Claude", "Antigravity"}
WATCHDOG_TASK_NAME = "ArchHub-Governed-Agent-Watchdog"
WATCHDOG_STARTUP_FILE = f"{WATCHDOG_TASK_NAME}.vbs"
WATCHDOG_INTERVAL_SEC = 30
OS_BROKER_TASK_NAME = "ArchHub-Governed-OS-Broker"
OS_BROKER_URL = "http://127.0.0.1:8476"
HARD_ENFORCEMENT_CONFIG = "hard-enforcement.json"
WORKSHOP_AUTHORITY_REQUIRED = True


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def workspace_root() -> Path:
    return repo_root().parents[1]


def brainwrap_path() -> Path:
    return repo_root() / "tools" / "brainwrap.py"


def default_shim_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArchHub" / "governed-bin"
    return Path.home() / ".archhub" / "governed-bin"


def user_startup_folder() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def user_start_menu_programs() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def user_desktop() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def pythonw_path() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        sibling = exe.with_name("pythonw.exe")
        if sibling.exists():
            return sibling
    return exe


def desktop_watchdog_path() -> Path:
    return repo_root() / "tools" / "agent_desktop_watchdog.py"


def os_gate_path() -> Path:
    return repo_root() / "tools" / "agent_os_gate.py"


def os_broker_path() -> Path:
    return repo_root() / "tools" / "agent_os_broker.py"


def hard_enforcement_package_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArchHub" / "governed-desktop" / "hard-enforcement"
    return Path.home() / ".archhub" / "governed-desktop" / "hard-enforcement"


def _ps_quote(value: str | os.PathLike[str]) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _cmd_quote(value: str | os.PathLike[str]) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _argv_path(value: str | os.PathLike[str]) -> str:
    return str(value).replace("\\", "/")


def _win_path(value: str | os.PathLike[str]) -> str:
    return str(value).replace("/", "\\")


def _hidden_subprocess_kwargs() -> dict[str, int]:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _latest_existing(paths: Iterable[Path]) -> Optional[Path]:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def discover_desktop_apps() -> dict[str, Path]:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    candidates: dict[str, list[Path]] = {
        "Codex": list(Path("C:/Program Files/WindowsApps").glob("OpenAI.Codex_*/*/Codex.exe"))
        + list(Path("C:/Program Files/WindowsApps").glob("OpenAI.Codex_*/app/Codex.exe")),
        "Claude": list(Path("C:/Program Files/WindowsApps").glob("Claude_*/app/Claude.exe")),
        "Antigravity": [
            local / "Programs" / "Antigravity" / "Antigravity.exe",
        ],
    }
    out: dict[str, Path] = {}
    for name, paths in candidates.items():
        found = _latest_existing(paths)
        if found is not None:
            out[name] = found
    try:
        out.update(desktop_apps_from_sessions(summarize_running_sessions(audit_running_sessions())))
    except Exception:
        pass
    return out


def desktop_apps_from_sessions(status_report: dict[str, Any]) -> dict[str, Path]:
    apps: dict[str, Path] = {}
    sessions = list(status_report.get("sessions") or [])
    agent_pids = {
        pid
        for pid in (_maybe_int(session.get("pid")) for session in sessions)
        if pid is not None
    }
    for session in sessions:
        if _maybe_int(session.get("parent_pid")) in agent_pids:
            continue
        process_name = str(session.get("name", "")).lower()
        label = PRIMARY_DESKTOP_APP_LABELS.get(process_name)
        if not label:
            continue
        argv = _command_line_to_argv(str(session.get("command_line", "")))
        if not argv:
            continue
        app = Path(argv[0])
        if app.name.lower() != process_name:
            continue
        if app.parent.name.lower() == "resources":
            continue
        apps[label] = app
    return apps


def default_governed_shortcut_paths(apps: dict[str, Path]) -> dict[str, list[Path]]:
    return {
        name: [
            user_start_menu_programs() / f"{name}.lnk",
            user_desktop() / f"{name}.lnk",
        ]
        for name in apps
    }


def powershell_profile_paths(home: Optional[Path] = None) -> list[Path]:
    home = home or Path.home()
    return [
        home / "Documents" / "PowerShell" / "profile.ps1",
        home / "Documents" / "WindowsPowerShell" / "profile.ps1",
    ]


def powershell_profile_block(
    *,
    python_exe: Path,
    brainwrap: Path,
    workspace_root: Path,
    shim_dir: Path,
    commands: Iterable[str] = DEFAULT_COMMANDS,
) -> str:
    command_lines = []
    for name in commands:
        safe = name.replace("'", "''")
        command_lines.append(
            f"function {name} {{ Invoke-ArchHubGovernedAgent -Name '{safe}' "
            "-AgentArgs $args }"
        )
    joined = "\n".join(command_lines)
    return (
        f"{PROFILE_BEGIN}\n"
        "$script:ArchHubGovernedShimDir = "
        f"{_ps_quote(shim_dir)}\n"
        "$script:ArchHubGovernedPython = "
        f"{_ps_quote(python_exe)}\n"
        "$script:ArchHubGovernedBrainwrap = "
        f"{_ps_quote(brainwrap)}\n"
        "$script:ArchHubGovernedWorkspace = "
        f"{_ps_quote(workspace_root)}\n"
        "function Invoke-ArchHubGovernedAgent {\n"
        "  param([string]$Name, [object[]]$AgentArgs)\n"
        "  $resolved = Get-Command $Name -All -ErrorAction SilentlyContinue |\n"
        "    Where-Object { $_.CommandType -ne 'Function' -and "
        "$_.Source -notlike \"$script:ArchHubGovernedShimDir*\" } |\n"
        "    Sort-Object @{ Expression = { if ($_.CommandType -eq "
        "'Application') { 0 } elseif ($_.CommandType -eq 'ExternalScript') "
        "{ 1 } else { 2 } } } |\n"
        "    Select-Object -First 1\n"
        "  $target = if ($resolved.Path) { $resolved.Path } elseif "
        "($resolved) { $resolved.Source } else { $Name }\n"
        "  & $script:ArchHubGovernedPython $script:ArchHubGovernedBrainwrap "
        "launch --governed-strict --cwd $script:ArchHubGovernedWorkspace -- "
        "$target @AgentArgs\n"
        "}\n"
        f"{joined}\n"
        f"{PROFILE_END}\n"
    )


def upsert_managed_block(
    path: Path,
    block: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if PROFILE_BEGIN not in block:
        block = f"{PROFILE_BEGIN}\n{block.rstrip()}\n{PROFILE_END}\n"
    old = path.read_bytes().decode("utf-8") if path.exists() else ""
    start = old.find(PROFILE_BEGIN)
    end = old.find(PROFILE_END)
    if start != -1 and end != -1 and end > start:
        end += len(PROFILE_END)
        before = old[:start].rstrip()
        after = old[end:].lstrip()
        new = ""
        if before:
            new += before + "\n\n"
        new += block.rstrip() + "\n"
        if after:
            new += "\n" + after
    else:
        prefix = old.rstrip() + "\n\n" if old.strip() else ""
        new = prefix + block.rstrip() + "\n"
    changed = new != old
    result = {
        "path": str(path),
        "changed": changed,
        "dry_run": dry_run,
        "backup_path": "",
    }
    if not changed or dry_run:
        return result
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + f".archhub-bak.{int(time.time())}")
        shutil.copy2(path, backup)
        result["backup_path"] = str(backup)
    path.write_text(new, encoding="utf-8", newline="")
    return result


def _path_without(path_text: str, remove: Path) -> str:
    target = str(remove).rstrip("\\/").lower()
    kept = []
    for item in path_text.split(os.pathsep):
        if item.rstrip("\\/").lower() != target:
            kept.append(item)
    return os.pathsep.join(kept)


def resolve_command(command: str, *, shim_dir: Path) -> Optional[Path]:
    search_path = _path_without(os.environ.get("PATH", ""), shim_dir)
    found = shutil.which(command, path=search_path)
    return Path(found) if found else None


def cmd_shim_text(
    *,
    command: str,
    target: Path,
    python_exe: Path,
    brainwrap: Path,
    workspace_root: Path,
) -> str:
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        "set ARCHHUB_GOVERNED_SHIM_ACTIVE=1\r\n"
        f"{_cmd_quote(python_exe)} {_cmd_quote(brainwrap)} launch "
        f"--governed-strict --cwd {_cmd_quote(workspace_root)} -- "
        f"{_cmd_quote(target)} %*\r\n"
    )


def install_cmd_shims(
    *,
    shim_dir: Path,
    commands: Iterable[str] = DEFAULT_COMMANDS,
    python_exe: Path = Path(sys.executable),
    brainwrap: Path = brainwrap_path(),
    workspace_root: Path = workspace_root(),
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    out = []
    for command in commands:
        target = resolve_command(command, shim_dir=shim_dir)
        if target is None:
            out.append({
                "command": command,
                "changed": False,
                "skipped": True,
                "reason": "command not found on PATH",
            })
            continue
        path = shim_dir / f"{command}.cmd"
        text = cmd_shim_text(
            command=command,
            target=target,
            python_exe=python_exe,
            brainwrap=brainwrap,
            workspace_root=workspace_root,
        )
        old = path.read_bytes().decode("utf-8") if path.exists() else ""
        changed = old != text
        if changed and not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
        out.append({
            "command": command,
            "path": str(path),
            "target": str(target),
            "changed": changed,
            "skipped": False,
            "dry_run": dry_run,
        })
    return out


def _user_path_value() -> str:
    if os.name != "nt":
        return os.environ.get("PATH", "")
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _typ = winreg.QueryValueEx(key, "Path")
            return str(value)
    except FileNotFoundError:
        return ""
    except Exception:
        return os.environ.get("PATH", "")


def ensure_user_path_contains(path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    current = _user_path_value()
    entries = [p for p in current.split(os.pathsep) if p]
    wanted = str(path)
    exists = any(p.rstrip("\\/").lower() == wanted.rstrip("\\/").lower()
                 for p in entries)
    result = {"path": wanted, "changed": False, "dry_run": dry_run}
    if exists:
        return result
    result["changed"] = True
    if dry_run:
        return result
    if os.name == "nt":
        import winreg  # type: ignore
        new_value = wanted + (os.pathsep + current if current else "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_value)
        result["broadcast"] = _broadcast_environment_change()
    return result


def _broadcast_environment_change() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        timeout_ms = 5000
        result = wintypes.DWORD()
        sent = ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            timeout_ms,
            ctypes.byref(result),
        )
        return bool(sent)
    except Exception:
        return False


def _load_governance_broker():
    hooks = workspace_root() / "00.GOVERNANCE" / "hooks"
    if str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))
    import governed_write_broker  # type: ignore
    return governed_write_broker


def audit_running_sessions() -> dict[str, Any]:
    broker = _load_governance_broker()
    return broker.audit_agent_sessions()


def summarize_running_sessions(audit: dict[str, Any]) -> dict[str, Any]:
    sessions = list(audit.get("sessions") or [])
    actions = list(audit.get("actions") or [])
    governed = sum(1 for s in sessions if s.get("status") == "governed")
    need_restart = sum(1 for s in sessions if s.get("status") == "needs_restart")
    return {
        "ok": bool(audit.get("ok", True)),
        "can_hot_attach": False,
        "reason": (
            "Running processes already have their environment and hook state; "
            "restart ungoverned sessions under the governed launcher."
        ),
        "current_sessions_total": len(sessions),
        "current_sessions_governed": governed,
        "current_sessions_need_restart": need_restart,
        "sessions": sessions,
        "actions": actions,
    }


def quarantine_state_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ArchHub" / "governed-desktop" / "quarantine.json"
    return Path.home() / ".archhub" / "governed-desktop" / "quarantine.json"


def quarantine_ungoverned_sessions(
    status_report: dict[str, Any] | None = None,
    *,
    quarantine_path: Path = quarantine_state_path(),
) -> dict[str, Any]:
    status_report = status_report or summarize_running_sessions(audit_running_sessions())
    quarantined = []
    for session in status_report.get("sessions") or []:
        if session.get("status") != "needs_restart":
            continue
        item = dict(session)
        item["original_status"] = session.get("status")
        item["status"] = "quarantined_untrusted"
        item["required_resolution"] = "restart_under_governed_launcher_or_retroactive_audit"
        quarantined.append(item)

    payload = {
        "schema": "archhub-session-quarantine/v1",
        "mode": "no_restart_quarantine",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "tools/governed_sessions.py",
        "policy": {
            "claim": (
                "Already-running external app sessions cannot be called fully "
                "governed unless their process ancestry is governed."
            ),
            "effect": (
                "No mid-flight restart is performed. Quarantined session outputs "
                "must pass retroactive audit and cannot be promoted as trusted "
                "governed work merely because the session remained open."
            ),
        },
        "counts": {
            "total": status_report.get("current_sessions_total", 0),
            "governed": status_report.get("current_sessions_governed", 0),
            "quarantined_untrusted": len(quarantined),
        },
        "sessions": quarantined,
    }
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "mode": "no_restart_quarantine",
        "path": str(quarantine_path),
        "quarantined_count": len(quarantined),
        "governed_count": status_report.get("current_sessions_governed", 0),
        "total": status_report.get("current_sessions_total", 0),
    }


def _command_line_to_argv(command_line: str) -> list[str]:
    command_line = command_line.strip()
    if not command_line:
        return []
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            argc = ctypes.c_int()
            ctypes.windll.shell32.CommandLineToArgvW.restype = (
                ctypes.POINTER(wintypes.LPWSTR)
            )
            ptr = ctypes.windll.shell32.CommandLineToArgvW(
                command_line, ctypes.byref(argc)
            )
            if ptr:
                try:
                    return [ptr[i] for i in range(argc.value)]
                finally:
                    ctypes.windll.kernel32.LocalFree(ptr)
        except Exception:
            pass
    return shlex.split(command_line, posix=False)


def _maybe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def desktop_watchdog_plan(
    status_report: dict[str, Any],
    *,
    pythonw: Path = pythonw_path(),
    brainwrap: Path = brainwrap_path(),
    workspace_root: Path = workspace_root(),
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    sessions = list(status_report.get("sessions") or [])
    agent_pids = {
        pid
        for pid in (_maybe_int(session.get("pid")) for session in sessions)
        if pid is not None
    }
    for session in sessions:
        if session.get("status") != "needs_restart":
            continue
        if _maybe_int(session.get("parent_pid")) in agent_pids:
            continue
        name = str(session.get("name", "")).lower()
        if name not in PRIMARY_DESKTOP_APP_NAMES:
            continue
        child_argv = _command_line_to_argv(str(session.get("command_line", "")))
        if not child_argv:
            continue
        launch_argv = [
            _argv_path(pythonw),
            _argv_path(brainwrap),
            "launch",
            "--governed-strict",
            "--cwd",
            _argv_path(workspace_root),
            "--",
            *child_argv,
        ]
        actions.append({
            "pid": session.get("pid"),
            "name": session.get("name", ""),
            "action": "restart_desktop_app_governed",
            "kill_tree": True,
            "argv": launch_argv,
        })
    return actions


def watchdog_startup_task_spec(
    *,
    pythonw: Path = pythonw_path(),
    watchdog: Path = desktop_watchdog_path(),
    interval_sec: int = WATCHDOG_INTERVAL_SEC,
    dry_run: bool = False,
) -> dict[str, Any]:
    argv = [
        _argv_path(pythonw),
        _argv_path(watchdog),
        "--interval-sec",
        str(interval_sec),
    ]
    return {
        "task_name": WATCHDOG_TASK_NAME,
        "trigger": "AtLogOn",
        "dry_run": dry_run,
        "argv": argv,
        "command": subprocess.list2cmdline(argv),
    }


def _vbs_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def watchdog_startup_launcher_spec(
    *,
    launcher_path: Path | None = None,
    pythonw: Path = pythonw_path(),
    watchdog: Path = desktop_watchdog_path(),
    interval_sec: int = WATCHDOG_INTERVAL_SEC,
    dry_run: bool = False,
) -> dict[str, Any]:
    task = watchdog_startup_task_spec(
        pythonw=pythonw,
        watchdog=watchdog,
        interval_sec=interval_sec,
        dry_run=dry_run,
    )
    path = launcher_path or (user_startup_folder() / WATCHDOG_STARTUP_FILE)
    script = (
        "' Generated by ArchHub governed sessions. Edit tools/governed_sessions.py.\r\n"
        "CreateObject(\"WScript.Shell\").Run "
        f"{_vbs_string(task['command'])}, 0, False\r\n"
    )
    return {
        "method": "startup_folder",
        "trigger": "UserStartupFolder",
        "dry_run": dry_run,
        "path": str(path),
        "argv": task["argv"],
        "command": task["command"],
        "script": script,
    }


def governed_shortcut_spec(
    *,
    name: str,
    app: Path,
    shortcut_path: Path,
    pythonw: Path = pythonw_path(),
    brainwrap: Path = brainwrap_path(),
    workspace_root: Path = workspace_root(),
) -> dict[str, Any]:
    arguments = subprocess.list2cmdline([
        _argv_path(brainwrap),
        "launch",
        "--governed-strict",
        "--cwd",
        _argv_path(workspace_root),
        "--",
        str(app),
    ])
    return {
        "name": name,
        "path": str(shortcut_path),
        "target": _argv_path(pythonw),
        "arguments": arguments,
        "working_directory": str(workspace_root),
        "icon_location": f"{app},0",
        "app": str(app),
    }


def _write_windows_shortcut(spec: dict[str, Any]) -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "changed": False, "error": "Windows shortcuts require Windows"}
    script = r"""
$spec = $env:ARCHHUB_SHORTCUT_SPEC | ConvertFrom-Json
$path = [string]$spec.path
$target = [string]$spec.target
$arguments = [string]$spec.arguments
$workdir = [string]$spec.working_directory
$icon = [string]$spec.icon_location
$shell = New-Object -ComObject WScript.Shell
$changed = $true
$backup = ""
if (Test-Path $path) {
  $old = $shell.CreateShortcut($path)
  $changed = (($old.TargetPath -ne $target) -or ($old.Arguments -ne $arguments) -or ($old.WorkingDirectory -ne $workdir))
  if ($changed) {
    $backup = "$path.archhub-raw-bak.$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()).lnk"
    Copy-Item -LiteralPath $path -Destination $backup -Force
  }
}
if ($changed) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null
  $shortcut = $shell.CreateShortcut($path)
  $shortcut.TargetPath = $target
  $shortcut.Arguments = $arguments
  $shortcut.WorkingDirectory = $workdir
  if ($icon) { $shortcut.IconLocation = $icon }
  $shortcut.Save()
}
[pscustomobject]@{ok=$true; changed=$changed; path=$path; backup_path=$backup} | ConvertTo-Json
"""
    env = os.environ.copy()
    env["ARCHHUB_SHORTCUT_SPEC"] = json.dumps(spec)
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        **_hidden_subprocess_kwargs(),
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "changed": False,
            "path": spec.get("path", ""),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {
            "ok": False,
            "changed": False,
            "path": spec.get("path", ""),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "error": "could not parse shortcut writer output",
        }


def install_governed_desktop_shortcuts(
    *,
    apps: dict[str, Path] | None = None,
    shortcut_paths: dict[str, list[Path]] | None = None,
    pythonw: Path = pythonw_path(),
    brainwrap: Path = brainwrap_path(),
    workspace_root: Path = workspace_root(),
    shortcut_writer=_write_windows_shortcut,
    dry_run: bool = False,
) -> dict[str, Any]:
    apps = apps or discover_desktop_apps()
    shortcut_paths = shortcut_paths or default_governed_shortcut_paths(apps)
    shortcuts: list[dict[str, Any]] = []
    for name, app in apps.items():
        for shortcut_path in shortcut_paths.get(name, []):
            spec = governed_shortcut_spec(
                name=name,
                app=app,
                shortcut_path=shortcut_path,
                pythonw=pythonw,
                brainwrap=brainwrap,
                workspace_root=workspace_root,
            )
            if dry_run:
                result = {"ok": True, "changed": False, "dry_run": True, "path": spec["path"]}
            else:
                result = shortcut_writer(spec)
            shortcuts.append({**spec, **result})
    return {
        "ok": all(item.get("ok") for item in shortcuts),
        "changed": any(item.get("changed") for item in shortcuts),
        "shortcut_count": len(shortcuts),
        "apps": {name: str(path) for name, path in apps.items()},
        "shortcuts": shortcuts,
    }


def _hard_enforcement_install_script(config_path: Path) -> str:
    return rf"""# Generated by ArchHub governed sessions. Edit tools/governed_sessions.py.
# Broker script: agent_os_broker.py
$ErrorActionPreference = "Stop"

function Test-IsAdmin {{
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}}

if (-not (Test-IsAdmin)) {{
  throw "Administrator rights required to install ArchHub OS hard enforcement."
}}

$configPath = {_ps_quote(config_path)}
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

function Remove-ArchHubIfeoEntry($entry) {{
  $root = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$($entry.image_name)"
  $sub = Join-Path $root $entry.subkey_name
  if (Test-Path $sub) {{
    Remove-Item -Path $sub -Recurse -Force
  }}
  if (Test-Path $root) {{
    $children = @(Get-ChildItem -Path $root -ErrorAction SilentlyContinue)
    if ($children.Count -eq 0) {{
      Remove-ItemProperty -Path $root -Name UseFilter -ErrorAction SilentlyContinue
    }}
  }}
}}

$cleanupEntries = @($config.ifeo_entries)
if ($config.PSObject.Properties.Name -contains "ifeo_cleanup_entries") {{
  $cleanupEntries = @($config.ifeo_cleanup_entries)
}}

foreach ($entry in $cleanupEntries) {{
  Remove-ArchHubIfeoEntry $entry
}}

foreach ($entry in $config.ifeo_entries) {{
  $root = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$($entry.image_name)"
  $sub = Join-Path $root $entry.subkey_name
  New-Item -Path $root -Force | Out-Null
  New-ItemProperty -Path $root -Name UseFilter -PropertyType DWord -Value 1 -Force | Out-Null
  New-Item -Path $sub -Force | Out-Null
  New-ItemProperty -Path $sub -Name FilterFullPath -PropertyType String -Value $entry.filter_full_path -Force | Out-Null
  New-ItemProperty -Path $sub -Name Debugger -PropertyType String -Value $entry.debugger -Force | Out-Null
}}

function Stop-ArchHubBrokerListener {{
  $uri = [Uri]$config.broker_url
  $listeners = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $uri.Port -State Listen -ErrorAction SilentlyContinue)
  foreach ($listener in $listeners) {{
    if ($listener.OwningProcess -and $listener.OwningProcess -ne $PID) {{
      Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }}
  }}
}}

$taskArgs = @($config.broker, "serve", "--config", $configPath)
$taskArgLine = ($taskArgs | ForEach-Object {{ '"' + ($_ -replace '"','\"') + '"' }}) -join ' '
$action = New-ScheduledTaskAction -Execute $config.pythonw -Argument $taskArgLine
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $config.task_name -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Stop-ArchHubBrokerListener
Start-Process -WindowStyle Hidden -FilePath $config.pythonw -ArgumentList $taskArgs
Write-Host "ArchHub OS hard enforcement installed."
"""


def _hard_enforcement_uninstall_script(config_path: Path) -> str:
    return rf"""# Generated by ArchHub governed sessions. Edit tools/governed_sessions.py.
# Task: ArchHub-Governed-OS-Broker
$ErrorActionPreference = "Stop"

function Test-IsAdmin {{
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}}

if (-not (Test-IsAdmin)) {{
  throw "Administrator rights required to uninstall ArchHub OS hard enforcement."
}}

$configPath = {_ps_quote(config_path)}
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

function Remove-ArchHubIfeoEntry($entry) {{
  $root = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\$($entry.image_name)"
  $sub = Join-Path $root $entry.subkey_name
  if (Test-Path $sub) {{
    Remove-Item -Path $sub -Recurse -Force
  }}
  if (Test-Path $root) {{
    $children = @(Get-ChildItem -Path $root -ErrorAction SilentlyContinue)
    if ($children.Count -eq 0) {{
      Remove-ItemProperty -Path $root -Name UseFilter -ErrorAction SilentlyContinue
    }}
  }}
}}

$cleanupEntries = @($config.ifeo_entries)
if ($config.PSObject.Properties.Name -contains "ifeo_cleanup_entries") {{
  $cleanupEntries = @($config.ifeo_cleanup_entries)
}}

foreach ($entry in $cleanupEntries) {{
  Remove-ArchHubIfeoEntry $entry
}}

schtasks /Delete /TN $config.task_name /F 2>$null | Out-Null
Write-Host "ArchHub OS hard enforcement removed."
"""


def ifeo_supported_app(name: str, _app: Path) -> bool:
    return name not in IFEO_UNSAFE_MULTIPROCESS_APPS


def hard_enforcement_spec(
    *,
    apps: dict[str, Path] | None = None,
    package_dir: Path = hard_enforcement_package_dir(),
    pythonw: Path = pythonw_path(),
    workspace_root: Path = workspace_root(),
    brainwrap: Path = brainwrap_path(),
    gate: Path = os_gate_path(),
    broker: Path = os_broker_path(),
) -> dict[str, Any]:
    apps = apps or discover_desktop_apps()
    config_path = package_dir / HARD_ENFORCEMENT_CONFIG
    ifeo_entries: list[dict[str, Any]] = []
    ifeo_cleanup_entries: list[dict[str, Any]] = []
    app_config: dict[str, dict[str, Any]] = {}
    for name, app in apps.items():
        image_name = app.name
        subkey_name = f"ArchHub-{name}"
        debugger = subprocess.list2cmdline([
            _win_path(pythonw),
            _win_path(gate),
            "ifeo",
            "--config",
            _win_path(config_path),
            "--app",
            name,
            "--",
        ])
        registry_path = (
            "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\"
            f"Image File Execution Options\\{image_name}\\{subkey_name}"
        )
        entry = {
            "app": name,
            "image_name": image_name,
            "subkey_name": subkey_name,
            "filter_full_path": _win_path(app),
            "debugger": debugger,
            "registry_path": registry_path,
        }
        supported = ifeo_supported_app(name, app)
        cleanup_entry = {
            **entry,
            "ifeo_supported": supported,
        }
        if supported:
            ifeo_entries.append({**entry, "ifeo_supported": True})
        else:
            cleanup_entry["reason"] = (
                "IFEO is unsafe for this multi-process desktop app because it "
                "also intercepts Chromium/Electron child launches."
            )
        ifeo_cleanup_entries.append(cleanup_entry)
        app_config[name] = {
            "path": _win_path(app),
            "image_name": image_name,
            "ifeo_subkey": subkey_name,
            "ifeo_supported": supported,
        }
    config = {
        "schema": "archhub-os-hard-enforcement/v1",
        "mode": "ifeo_broker",
        "admin_required": True,
        "task_name": OS_BROKER_TASK_NAME,
        "package_dir": _win_path(package_dir),
        "config_path": _win_path(config_path),
        "pythonw": _win_path(pythonw),
        "workspace_root": _win_path(workspace_root),
        "brainwrap": _win_path(brainwrap),
        "gate": _win_path(gate),
        "broker": _win_path(broker),
        "broker_url": OS_BROKER_URL,
        "workshop_authority_required": WORKSHOP_AUTHORITY_REQUIRED,
        "apps": app_config,
        "ifeo_entries": ifeo_entries,
        "ifeo_cleanup_entries": ifeo_cleanup_entries,
    }
    return {
        **config,
        "config": config,
        "install_script": _hard_enforcement_install_script(config_path),
        "uninstall_script": _hard_enforcement_uninstall_script(config_path),
    }


def write_hard_enforcement_package(
    *,
    apps: dict[str, Path] | None = None,
    package_dir: Path = hard_enforcement_package_dir(),
    pythonw: Path = pythonw_path(),
    workspace_root: Path = workspace_root(),
    brainwrap: Path = brainwrap_path(),
    gate: Path = os_gate_path(),
    broker: Path = os_broker_path(),
    dry_run: bool = False,
) -> dict[str, Any]:
    spec = hard_enforcement_spec(
        apps=apps,
        package_dir=package_dir,
        pythonw=pythonw,
        workspace_root=workspace_root,
        brainwrap=brainwrap,
        gate=gate,
        broker=broker,
    )
    files = {
        package_dir / HARD_ENFORCEMENT_CONFIG: json.dumps(spec["config"], indent=2) + "\n",
        package_dir / "install-hard-enforcement.ps1": spec["install_script"],
        package_dir / "uninstall-hard-enforcement.ps1": spec["uninstall_script"],
    }
    changed_files = []
    for path, text in files.items():
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        changed = old != text
        if changed:
            changed_files.append(str(path))
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="")
    return {
        "ok": True,
        "mode": spec["mode"],
        "admin_required": True,
        "dry_run": dry_run,
        "changed": bool(changed_files),
        "package_dir": str(package_dir),
        "config_path": str(package_dir / HARD_ENFORCEMENT_CONFIG),
        "install_script_path": str(package_dir / "install-hard-enforcement.ps1"),
        "uninstall_script_path": str(package_dir / "uninstall-hard-enforcement.ps1"),
        "changed_files": changed_files,
        "apps": spec["apps"],
        "ifeo_entries": spec["ifeo_entries"],
        "ifeo_cleanup_entries": spec["ifeo_cleanup_entries"],
    }


def _taskkill_tree(pid: int) -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "error": "taskkill is Windows-only"}
    proc = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=30,
        **_hidden_subprocess_kwargs(),
    )
    ok = _taskkill_success(pid=pid, returncode=proc.returncode)
    warning = ""
    if ok and proc.returncode != 0:
        warning = (
            "taskkill returned stale child-process errors, but the root "
            "process is no longer running"
        )
    return {
        "ok": ok,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        **({"warning": warning} if warning else {}),
    }


def _pid_exists(pid: int) -> bool:
    if os.name != "nt":
        return False
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "$p = Get-CimInstance Win32_Process -Filter "
            f"\"ProcessId={int(pid)}\" -ErrorAction SilentlyContinue; "
            "if ($p) { '1' } else { '0' }"
        ),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return True
    return proc.stdout.strip() == "1"


def _taskkill_success(
    *,
    pid: int,
    returncode: int,
    pid_exists_fn=_pid_exists,
) -> bool:
    if returncode == 0:
        return True
    return not pid_exists_fn(pid)


def _start_detached(argv: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(workspace_root()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            **_hidden_subprocess_kwargs(),
        )
        return {"ok": True, "pid": proc.pid}
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


def apply_desktop_watchdog_actions(
    actions: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    kill_tree_fn=_taskkill_tree,
    start_fn=_start_detached,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for action in actions:
        if action.get("action") != "restart_desktop_app_governed":
            continue
        old_pid = action.get("pid")
        argv = list(action.get("argv") or [])
        result = {
            "ok": False,
            "dry_run": dry_run,
            "old_pid": old_pid,
            "name": action.get("name", ""),
            "argv": argv,
        }
        if dry_run:
            result["ok"] = True
            results.append(result)
            continue
        killed = kill_tree_fn(int(old_pid))
        result["kill"] = killed
        if not killed.get("ok"):
            results.append(result)
            continue
        launched = start_fn(argv)
        result["launch"] = launched
        result["ok"] = bool(launched.get("ok"))
        if launched.get("pid") is not None:
            result["new_pid"] = launched.get("pid")
        results.append(result)
    return results


def install_watchdog_startup_task(
    *,
    dry_run: bool = False,
    interval_sec: int = WATCHDOG_INTERVAL_SEC,
) -> dict[str, Any]:
    spec = watchdog_startup_task_spec(interval_sec=interval_sec, dry_run=dry_run)
    result = {
        "ok": True,
        "dry_run": dry_run,
        "changed": False,
        "spec": spec,
    }
    if dry_run:
        return result
    if os.name != "nt":
        return {**result, "ok": False, "error": "scheduled task install is Windows-only"}
    proc = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            WATCHDOG_TASK_NAME,
            "/TR",
            spec["command"],
            "/SC",
            "ONLOGON",
            "/F",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        **_hidden_subprocess_kwargs(),
    )
    result.update({
        "ok": proc.returncode == 0,
        "changed": proc.returncode == 0,
        "method": "scheduled_task",
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    })
    return result


def install_watchdog_startup_launcher(
    *,
    launcher_path: Path | None = None,
    pythonw: Path = pythonw_path(),
    watchdog: Path = desktop_watchdog_path(),
    interval_sec: int = WATCHDOG_INTERVAL_SEC,
    dry_run: bool = False,
) -> dict[str, Any]:
    spec = watchdog_startup_launcher_spec(
        launcher_path=launcher_path,
        pythonw=pythonw,
        watchdog=watchdog,
        interval_sec=interval_sec,
        dry_run=dry_run,
    )
    path = Path(spec["path"])
    old = path.read_bytes().decode("utf-8") if path.exists() else ""
    changed = old != spec["script"]
    result = {
        "ok": True,
        "method": "startup_folder",
        "dry_run": dry_run,
        "changed": changed,
        "spec": {k: v for k, v in spec.items() if k != "script"},
    }
    if changed and not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(spec["script"], encoding="utf-8", newline="")
    return result


def install_desktop_watchdog(
    *,
    dry_run: bool = False,
    interval_sec: int = WATCHDOG_INTERVAL_SEC,
    task_installer=install_watchdog_startup_task,
    launcher_installer=install_watchdog_startup_launcher,
) -> dict[str, Any]:
    task = task_installer(dry_run=dry_run, interval_sec=interval_sec)
    if task.get("ok"):
        return {
            **task,
            "method": task.get("method", "scheduled_task"),
            "task": task,
        }

    launcher = launcher_installer(dry_run=dry_run, interval_sec=interval_sec)
    return {
        "ok": bool(launcher.get("ok")),
        "method": launcher.get("method", "startup_folder"),
        "dry_run": dry_run,
        "changed": bool(launcher.get("changed")),
        "task": task,
        "launcher": launcher,
    }


def install_native_hooks(*, dry_run: bool = False) -> dict[str, Any]:
    product = repo_root()
    brain_src = product / "personal-brain-mcp" / "src"
    if str(brain_src) not in sys.path:
        sys.path.insert(0, str(brain_src))
    try:
        from personal_brain import installer
        return {
            "ok": True,
            "results": installer.install_all(dry_run=dry_run),
        }
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


def install_bootstrap(
    *,
    dry_run: bool = False,
    install_path: bool = True,
    install_hooks: bool = True,
    install_watchdog: bool = True,
    install_shortcuts: bool = True,
    install_hard_enforcement: bool = True,
    commands: Iterable[str] = DEFAULT_COMMANDS,
) -> dict[str, Any]:
    shim_dir = default_shim_dir()
    block = powershell_profile_block(
        python_exe=Path(sys.executable),
        brainwrap=brainwrap_path(),
        workspace_root=workspace_root(),
        shim_dir=shim_dir,
        commands=commands,
    )
    profiles = [
        upsert_managed_block(path, block, dry_run=dry_run)
        for path in powershell_profile_paths()
    ]
    shims = install_cmd_shims(
        shim_dir=shim_dir,
        commands=commands,
        dry_run=dry_run,
    )
    path_result = (
        ensure_user_path_contains(shim_dir, dry_run=dry_run)
        if install_path else {"changed": False, "disabled": True}
    )
    hooks = (
        install_native_hooks(dry_run=dry_run)
        if install_hooks else {"ok": True, "disabled": True}
    )
    watchdog = (
        install_desktop_watchdog(dry_run=dry_run)
        if install_watchdog else {"ok": True, "disabled": True}
    )
    shortcuts = (
        install_governed_desktop_shortcuts(dry_run=dry_run)
        if install_shortcuts else {"ok": True, "disabled": True}
    )
    hard_enforcement = (
        write_hard_enforcement_package(dry_run=dry_run)
        if install_hard_enforcement else {"ok": True, "disabled": True}
    )
    current = summarize_running_sessions(audit_running_sessions())
    return {
        "ok": True,
        "dry_run": dry_run,
        "profiles": profiles,
        "shims": shims,
        "path": path_result,
        "native_hooks": hooks,
        "desktop_watchdog": watchdog,
        "desktop_shortcuts": shortcuts,
        "os_hard_enforcement": hard_enforcement,
        "current_sessions": current,
    }


def _print_human(report: dict[str, Any]) -> None:
    current = report.get("current_sessions", {})
    print("ArchHub governed sessions bootstrap")
    print(f"- PowerShell profiles touched: {sum(1 for p in report.get('profiles', []) if p.get('changed'))}")
    print(f"- command shims touched: {sum(1 for s in report.get('shims', []) if s.get('changed'))}")
    print(f"- user PATH changed: {bool((report.get('path') or {}).get('changed'))}")
    print(f"- desktop watchdog changed: {bool((report.get('desktop_watchdog') or {}).get('changed'))}")
    print(f"- desktop shortcuts changed: {bool((report.get('desktop_shortcuts') or {}).get('changed'))}")
    print(f"- OS hard-enforcement package changed: {bool((report.get('os_hard_enforcement') or {}).get('changed'))}")
    print(f"- current sessions governed: {current.get('current_sessions_governed', 0)}")
    print(f"- current sessions need restart: {current.get('current_sessions_need_restart', 0)}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install/audit governed agent sessions.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    install = sub.add_parser("install")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--json", action="store_true")
    install.add_argument("--no-path", action="store_true")
    install.add_argument("--no-hooks", action="store_true")
    install.add_argument("--no-watchdog", action="store_true")
    install.add_argument("--no-shortcuts", action="store_true")
    install.add_argument("--no-hard-enforcement", action="store_true")

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")

    quarantine = sub.add_parser("quarantine")
    quarantine.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "install":
        report = install_bootstrap(
            dry_run=args.dry_run,
            install_path=not args.no_path,
            install_hooks=not args.no_hooks,
            install_watchdog=not args.no_watchdog,
            install_shortcuts=not args.no_shortcuts,
            install_hard_enforcement=not args.no_hard_enforcement,
        )
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            _print_human(report)
        return 0 if report.get("ok") else 1
    if args.cmd == "status":
        report = summarize_running_sessions(audit_running_sessions())
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            _print_human({"current_sessions": report, "profiles": [], "shims": [], "path": {}})
        return 0
    if args.cmd == "quarantine":
        report = quarantine_ungoverned_sessions()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(
                f"Quarantined {report['quarantined_count']} ungoverned "
                f"sessions without restarting them."
            )
            print(f"State: {report['path']}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
