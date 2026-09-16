"""Register ArchHub's installed native MCP owner with a person's own Claude Code.

Setup offers this in its window and acts only on the person's yes. The entry
goes in through Claude Code's own command, `claude mcp add-json --scope user`;
this module never edits ~/.claude.json, which Claude Code rewrites while it
runs. A same-name entry that differs from ours is reported and left alone.

Nothing here starts the MCP server, because starting it enrolls a graph actor.
A registered entry proves the entry exists, not that Claude Code connected or
that any host action works. Claude Desktop chat has no verified native-session
identity mapping, so it is detected and reported, never configured.

Claude Code prefers a project's own entry of the same name (a local entry in
~/.claude.json or a project .mcp.json) over the user entry. Differing local
entries are counted and reported; project .mcp.json files are not searched.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from .native_workshop_profile import SERVER_NAME

LOADER = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
          "runpy.run_module('nodelang.native_agent_mcp',run_name='__main__')")
# Development-era entries on some machines. They are never an ArchHub
# connection; their migration has its own owners.
LEGACY_NAMES = ("archhub-agent-coordination", "archhub-hosts")
_LAUNCHERS = ("claude.exe", "claude.cmd", "claude.bat", "claude.ps1")
_MAX_CONFIG_BYTES = 64 * 1024 * 1024
_REPARSE_POINT = 0x400
# The one inspection seam, so courts can present a reparse point where the
# platform will not create one for them.
_lstat = os.lstat


class RegistrationRefused(ValueError):
    """A path a truthful entry needs is absent, redirected or of the wrong type."""


def _require_plain(path: Path, kind: str, *, may_be_absent: bool = False):
    """Check the uncollapsed chain: the path and every ancestor real, unredirected, typed.

    Returns the leaf's [device, inode, size, mtime] identity, or None for an
    allowed leaf that does not exist yet.
    """
    if not path.is_absolute() or ".." in path.parts:
        raise RegistrationRefused("path must be absolute without '..': %s" % path)
    identity, absent = None, may_be_absent
    for current in (path, *path.parents):
        try:
            info = _lstat(current)
        except FileNotFoundError:
            if absent:
                continue
            raise RegistrationRefused("path is missing: %s" % current) from None
        except OSError:
            raise RegistrationRefused("path cannot be inspected: %s" % current) from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
            raise RegistrationRefused("path is redirected: %s" % current)
        wanted = kind if current == path else "directory"
        if not (stat.S_ISREG(info.st_mode) if wanted == "file" else stat.S_ISDIR(info.st_mode)):
            raise RegistrationRefused("path is not a %s: %s" % (wanted, current))
        if current == path:
            identity = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
        absent = False
    return identity


def managed_entry(install_root, state_root) -> dict:
    """The one user-scope entry for this installation; no session or actor identity."""
    root, state = Path(install_root), Path(state_root)
    python = root / ".venv" / "Scripts" / "python.exe"
    node = root / "runtime" / "node.exe"
    _require_plain(python, "file")
    _require_plain(root / "nodelang" / "native_agent_mcp.py", "file")
    _require_plain(node, "file")
    _require_plain(state / "session-link", "directory", may_be_absent=True)
    return {
        "type": "stdio",
        "command": str(python),
        "args": ["-I", "-B", "-c", LOADER, str(root)],
        # Claude Code supplies the session identity to its own MCP processes.
        "env": {"ARCHHUB_COORDINATION_VENDOR": "claude",
                "SESSION_LINK_STATE_DIR": str(state / "session-link"),
                "SESSION_LINK_NODE": str(node)},
    }


def find_claude_code(environment=None) -> dict:
    """Resolve the claude command a person runs, without running it.

    The first launcher on PATH wins, as in their own terminal. Only a real,
    unredirected claude.exe is used: a .cmd or .ps1 wrapper re-parses the JSON
    argument and may point Claude Code at another configuration, and a link can
    be swapped for another program.
    """
    env = os.environ if environment is None else environment
    candidates = []
    for entry in str(env.get("PATH", "")).split(os.pathsep):
        folder = entry.strip().strip('"')
        if folder and os.path.isabs(folder):
            candidates.extend(Path(folder) / name for name in _LAUNCHERS)
    if env.get("USERPROFILE"):
        candidates.append(Path(env["USERPROFILE"]) / ".local" / "bin" / "claude.exe")
    for candidate in candidates:
        try:
            _lstat(candidate)
        except OSError:
            continue
        if candidate.name != "claude.exe":
            return {"state": "unsupported_launcher", "executable": str(candidate), "identity": None}
        try:
            identity = _require_plain(candidate, "file")
        except RegistrationRefused as exc:
            return {"state": "launcher_untrusted", "executable": str(candidate), "identity": None,
                    "reason": str(exc)}
        return {"state": "found", "executable": str(candidate), "identity": identity}
    return {"state": "not_installed", "executable": None, "identity": None}


def _user_config(env):
    # Whether CLAUDE_CONFIG_DIR moves .claude.json is unverified: never guess.
    if env.get("CLAUDE_CONFIG_DIR") or not env.get("USERPROFILE"):
        return None, "config_location_unverified"
    path = Path(env["USERPROFILE"]) / ".claude.json"
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            return None, "config_unreadable"
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (OSError, UnicodeError, ValueError):
        return None, "config_unreadable"
    return (data, None) if type(data) is dict else (None, "config_unreadable")


def _claude_desktop_state(env) -> str:
    found = False
    if env.get("APPDATA"):
        found = (Path(env["APPDATA"]) / "Claude" / "claude_desktop_config.json").is_file()
    if not found and env.get("LOCALAPPDATA"):
        try:
            found = any((Path(env["LOCALAPPDATA"]) / "Packages").glob("Claude_*"))
        except OSError:
            found = False
    if not found:
        return "not_detected"
    return "detected: not supported yet (no verified native-session identity); nothing written"


def readiness(install_root, state_root, *, environment=None) -> dict:
    """What is true for this Windows user now. Reads files only; starts nothing."""
    env = os.environ if environment is None else environment
    report = {"server_name": SERVER_NAME, "claude_code": None, "legacy_migration_needed": [],
              "project_overrides": 0, "project_mcp_json": "not_inspected",
              "claude_desktop": _claude_desktop_state(env),
              "connection": "not_checked: starting the server would enroll an actor",
              "host_execution": "not_verified"}
    try:
        report["entry"] = entry = managed_entry(install_root, state_root)
    except RegistrationRefused as exc:
        report.update(claude_code="install_incomplete", reason=str(exc))
        return report
    report["launcher"] = launcher = find_claude_code(env)
    report["executable"] = launcher["executable"]
    if launcher["state"] != "found":
        report["claude_code"] = launcher["state"]
        if launcher.get("reason"):
            report["reason"] = launcher["reason"]
        return report
    config, problem = _user_config(env)
    servers = None if config is None else config.get("mcpServers", {})
    if problem or type(servers) is not dict:
        report["claude_code"] = problem or "config_unreadable"
        return report
    report["legacy_migration_needed"] = [name for name in LEGACY_NAMES if name in servers]
    projects = config.get("projects", {})
    # A project's local entry replaces the user entry there, whole. Only a
    # different one changes what runs in that project.
    report["project_overrides"] = sum(
        1 for value in (projects.values() if type(projects) is dict else ())
        if type(value) is dict and type(value.get("mcpServers")) is dict
        and SERVER_NAME in value["mcpServers"] and value["mcpServers"][SERVER_NAME] != entry)
    if SERVER_NAME in servers and servers[SERVER_NAME] != entry:
        # Semantic equality of the parsed entry, not file bytes.
        report["claude_code"] = "conflict"
    elif SERVER_NAME in servers:
        report["claude_code"] = ("registered_with_project_overrides"
                                 if report["project_overrides"] else "registered")
    elif report["legacy_migration_needed"]:
        report["claude_code"] = "legacy_migration_required"
    elif report["project_overrides"]:
        report["claude_code"] = "project_override"
    else:
        report["claude_code"] = "ready_to_register"
    return report


def register_claude_code(install_root, state_root, *, consent, environment=None,
                         run=subprocess.run) -> dict:
    """Add the entry through Claude Code's own command, only on consent; then re-read.

    The command's output is never captured, because it can echo configuration.
    A failure is a fixed reason and the exit code.
    """
    env = os.environ if environment is None else environment
    before = readiness(install_root, state_root, environment=env)
    if consent is not True or before["claude_code"] != "ready_to_register":
        return before
    argv = [before["executable"], "mcp", "add-json", SERVER_NAME,
            json.dumps(before["entry"], separators=(",", ":")), "--scope", "user"]
    child = {key: value for key, value in env.items()
             if key.upper() not in ("PYTHONPATH", "PYTHONHOME")}
    # Custody and identity of the launcher are checked again just before it runs.
    if find_claude_code(env) != before["launcher"]:
        before.update(claude_code="registration_unconfirmed",
                      reason="launcher_changed_before_run", exit_code=None)
        return before
    exit_code, reason = None, "entry_not_found_after_command"
    try:
        completed = run(argv, env=child, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=60, shell=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        exit_code = completed.returncode
        if exit_code:
            reason = "claude_mcp_add_refused"
    except subprocess.TimeoutExpired:
        reason = "claude_mcp_add_timed_out"
    except (OSError, subprocess.SubprocessError):
        reason = "claude_mcp_add_unavailable"
    # The command's exit code is not the evidence; the configuration is.
    after = readiness(install_root, state_root, environment=env)
    if after["claude_code"] != "registered":
        after.update(claude_code="registration_unconfirmed", reason=reason, exit_code=exit_code)
    return after


__all__ = [
    "LEGACY_NAMES",
    "LOADER",
    "RegistrationRefused",
    "find_claude_code",
    "managed_entry",
    "readiness",
    "register_claude_code",
]
