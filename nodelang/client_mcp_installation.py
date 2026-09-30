"""Register ArchHub's installed native MCP owner with a person's own Claude Code.

Setup offers this in its window and acts only on the person's yes. The entry
goes in through Claude Code's own command, `claude mcp add-json --scope user`;
this module never edits ~/.claude.json, which Claude Code rewrites while it
runs. A same-name entry that differs from ours is reported and left alone.

Nothing here starts the MCP server, because starting it enrolls a graph actor.
A registered entry proves the entry exists, not that Claude Code connected or
that any host action works. The desktop app's Code tab is Claude Code and reads
the same user entry; Claude Desktop chat has no verified native-session identity
mapping, so it is detected and reported, never configured.

ArchHub's development-era coordination launch (the source checkout, never this
install) is retired on the same consent that registers this install, through
`claude mcp remove`, only in its exact shape. The retired host server is kept.

Claude Code prefers a project's own entry of the same name (a local entry in
~/.claude.json or a project .mcp.json) over the user entry. Differing local
entries are counted and reported; project .mcp.json files are not searched.
"""
from __future__ import annotations

import json
import os
import re
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


# Development-era ArchHub entries, recognised only by name AND exact launch
# shape. The brain name counts only at its retired loopback URL; the host
# server only when its one argument is the retired source file, matched on
# whole path segments (case-insensitive, either separator); the coordination
# entry only in its "-m nodelang.clean_coordination_mcp" development launch.
DEAD_BRAIN_PORTS = (8473,)
_BRAIN_NAME = "brain"
_BRAIN_HOSTS = ("127.0.0.1", "localhost")
_RETIRED_HOST_SERVER = ("10.product", "12.production", "payload", "bridge", "server.py")
_RETIRED_COORDINATION_ARGS = ["-m", "nodelang.clean_coordination_mcp"]


def _path_segments(value) -> tuple:
    return tuple(part.casefold() for part in str(value).replace("\\", "/").split("/") if part)


def _retired_brain(entry) -> bool:
    from urllib.parse import urlsplit
    try:
        url = urlsplit(str(entry.get("url") or ""))
        return (url.scheme == "http" and url.hostname in _BRAIN_HOSTS
                and url.port in DEAD_BRAIN_PORTS and url.path.rstrip("/") == "/mcp"
                and not url.query and not url.fragment and not entry.get("command"))
    except ValueError:
        return False


def _retired_host_server(entry) -> bool:
    args = entry.get("args")
    if type(args) is not list or len(args) != 1 or entry.get("url"):
        return False
    segments = _path_segments(args[0])
    return segments[-len(_RETIRED_HOST_SERVER):] == _RETIRED_HOST_SERVER


def _retired_coordination(entry) -> bool:
    return entry.get("args") == _RETIRED_COORDINATION_ARGS and not entry.get("url")


_RETIRED_SHAPES = {
    "archhub-hosts": (_retired_host_server,
                      "development-era host server from the retired 12.PRODUCTION source, not shipped"),
    "archhub-agent-coordination": (_retired_coordination,
                                   "development-era coordination launch; the shipped server is %s" % SERVER_NAME),
}


def stale_entries(servers) -> dict:
    """Existing MCP entries an install or repair removes, with the reason for each.

    Only a verified ArchHub development-era entry: its known name AND its exact
    retired launch shape. Any other entry, on any port or path, is kept.
    """
    stale = {}
    for name, entry in (servers.items() if isinstance(servers, dict) else ()):
        shape = _RETIRED_SHAPES.get(name)
        if shape is not None and isinstance(entry, dict) and shape[0](entry):
            stale[name] = shape[1]
    return stale


def confirm_entries(servers) -> dict:
    """Entries to show the person and remove only on their word, with the reason.

    ArchHub's retired brain entry was only a URL (http://127.0.0.1:8473/mcp),
    which a person's own server of the same name could also carry: it cannot be
    told apart, so it is asked about, never removed automatically.
    """
    entry = servers.get(_BRAIN_NAME) if isinstance(servers, dict) else None
    if isinstance(entry, dict) and _retired_brain(entry):
        return {_BRAIN_NAME: "matches ArchHub's retired personal brain (127.0.0.1:8473), which no "
                             "longer runs; remove it only if it is not your own server"}
    return {}


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


# ArchHub's own governed shim (governed-bin\claude.cmd on the founder's PATH): it
# sets one marker and has brainwrap launch the named claude.exe with the person's
# own configuration (no CLAUDE_CONFIG_DIR). Only this exact form is followed, and
# only to a real, unredirected claude.exe; every other wrapper stays unsupported.
_GOVERNED_FOLDER = "governed-bin"
_GOVERNED_SHIM = re.compile(
    r'@echo off\r?\nsetlocal\r?\nset ARCHHUB_GOVERNED_SHIM_ACTIVE=1\r?\n'
    r'"[^"\r\n]+\.exe" "[^"\r\n]+\.py" launch --governed-strict --cwd "[^"\r\n]+" '
    r'-- "(?P<target>[^"\r\n]+)" %\*(?:\r?\n)?')
_MAX_SHIM_BYTES = 4096


def _governed_target(candidate: Path):
    """(claude.exe the governed shim launches, the shim's identity), or None for any other wrapper."""
    if candidate.name.casefold() != "claude.cmd" or candidate.parent.name.casefold() != _GOVERNED_FOLDER:
        return None
    try:
        shim = _require_plain(candidate, "file")
        raw = candidate.read_bytes()
        match = _GOVERNED_SHIM.fullmatch(raw.decode("ascii")) if len(raw) <= _MAX_SHIM_BYTES else None
    except (RegistrationRefused, OSError, UnicodeError):
        return None
    target = Path(match.group("target")) if match else None
    if target is None or not target.is_absolute() or target.name.casefold() != "claude.exe":
        return None
    return target, shim


def find_claude_code(environment=None) -> dict:
    """Resolve the claude command a person runs, without running it.

    The first launcher on PATH wins, as in their own terminal. Only a real,
    unredirected claude.exe is used: a .cmd or .ps1 wrapper re-parses the JSON
    argument and may point Claude Code at another configuration, and a link can
    be swapped for another program. ArchHub's own governed shim is the one
    wrapper followed: its exact form names the claude.exe it runs, which is
    then checked like any other.
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
        via = {}
        if candidate.name != "claude.exe":
            governed = _governed_target(candidate)
            if governed is None:
                return {"state": "unsupported_launcher", "executable": str(candidate), "identity": None}
            via = {"via": str(candidate), "via_identity": governed[1]}
            candidate = governed[0]
        try:
            identity = _require_plain(candidate, "file")
        except RegistrationRefused as exc:
            return {"state": "launcher_untrusted", "executable": str(candidate), "identity": None,
                    "reason": str(exc), **via}
        return {"state": "found", "executable": str(candidate), "identity": identity, **via}
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
    # The desktop app's Code tab runs Claude Code: it reads the same user-scope
    # entry (it gives MCP servers CLAUDE_CODE_SESSION_ID, with
    # CLAUDE_CODE_ENTRYPOINT=claude-desktop), so registering for Claude Code
    # covers it. Its chat has no native-session identity and is never configured.
    return ("detected: its Code tab uses the Claude Code user entry; its chat is not supported "
            "(no verified native-session identity); nothing written")


# What Replace retires: only the development-era coordination launch, which runs
# the source checkout instead of this install. The retired host server is never
# offered: a person's live Revit, AutoCAD and Max sessions still use its direct
# tools, so it stays until they ask (founder decision 2026-09-30).
RETIRED_ON_REPLACE = ("archhub-agent-coordination",)


def _retired_legacy(servers) -> dict:
    """The entries Replace retires that are present in their verified development-era shape."""
    return stale_entries({name: servers[name] for name in RETIRED_ON_REPLACE if name in servers})


def readiness(install_root, state_root, *, environment=None) -> dict:
    """What is true for this Windows user now. Reads files only; starts nothing."""
    env = os.environ if environment is None else environment
    report = {"server_name": SERVER_NAME, "claude_code": None, "legacy_migration_needed": [],
              "legacy_retire": {}, "project_overrides": 0, "project_mcp_json": "not_inspected",
              "claude_desktop": _claude_desktop_state(env),
              "connection": "not_checked: starting the server would enroll an actor",
              "host_execution": "not_verified"}
    try:
        report["entry"] = entry = managed_entry(install_root, state_root)
    except RegistrationRefused as exc:
        report.update(claude_code="install_incomplete", reason=str(exc))
        return report
    # The configuration is read before the launcher decides, so a development-era
    # entry is reported even where the launcher cannot be used.
    config, problem = _user_config(env)
    servers = None if config is None else config.get("mcpServers", {})
    if not problem and type(servers) is dict:
        report["legacy_migration_needed"] = [name for name in LEGACY_NAMES if name in servers]
        report["legacy_retire"] = _retired_legacy(servers)
        projects = config.get("projects", {})
        # A project's local entry replaces the user entry there, whole. Only a
        # different one changes what runs in that project.
        report["project_overrides"] = sum(
            1 for value in (projects.values() if type(projects) is dict else ())
            if type(value) is dict and type(value.get("mcpServers")) is dict
            and SERVER_NAME in value["mcpServers"] and value["mcpServers"][SERVER_NAME] != entry)
    report["launcher"] = launcher = find_claude_code(env)
    report["executable"] = launcher["executable"]
    if launcher["state"] != "found":
        report["claude_code"] = launcher["state"]
        if launcher.get("reason"):
            report["reason"] = launcher["reason"]
        return report
    if problem or type(servers) is not dict:
        report["claude_code"] = problem or "config_unreadable"
        return report
    legacy = report["legacy_migration_needed"]
    if SERVER_NAME in servers and servers[SERVER_NAME] != entry:
        # Semantic equality of the parsed entry, not file bytes.
        report["claude_code"] = "conflict"
    elif report["legacy_retire"]:
        # ArchHub's own verified development-era coordination launch: on consent
        # this install's entry is added and that one entry is retired. Any
        # other legacy entry is kept exactly as it is.
        report["claude_code"] = "migration_available"
        report["reason"] = ("ArchHub's development-era coordination entry runs the source checkout, "
                            "not this install; Replace registers this install and retires only that entry")
    elif SERVER_NAME in servers:
        report["claude_code"] = ("registered_with_project_overrides"
                                 if report["project_overrides"] else "registered")
    elif legacy:
        report["claude_code"] = "legacy_migration_required"
    elif report["project_overrides"]:
        report["claude_code"] = "project_override"
    else:
        report["claude_code"] = "ready_to_register"
    return report


def _run_claude(run, argv, env) -> tuple:
    """(exit code or None, failure suffix or None); output is never captured."""
    child = {key: value for key, value in env.items()
             if key.upper() not in ("PYTHONPATH", "PYTHONHOME")}
    try:
        completed = run(argv, env=child, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=60, shell=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return None, "timed_out"
    except (OSError, subprocess.SubprocessError):
        return None, "unavailable"
    return completed.returncode, ("refused" if completed.returncode else None)


def register_claude_code(install_root, state_root, *, consent, environment=None,
                         run=subprocess.run) -> dict:
    """Add the entry through Claude Code's own command, only on consent; then re-read.

    Where the only legacy entries are ArchHub's verified development-era
    launches, the same consent adds this install's entry and then retires each
    of them through `claude mcp remove`, each re-verified on the configuration
    just before it is removed. The retired entries are returned, so they can be
    restored exactly. The command's output is never captured, because it can
    echo configuration. A failure is a fixed reason and the exit code.
    """
    env = os.environ if environment is None else environment
    before = readiness(install_root, state_root, environment=env)
    if consent is not True or before["claude_code"] not in ("ready_to_register", "migration_available"):
        return before
    # Custody and identity of the launcher are checked again just before it runs.
    if find_claude_code(env) != before["launcher"]:
        before.update(claude_code="registration_unconfirmed",
                      reason="launcher_changed_before_run", exit_code=None)
        return before
    exe = before["executable"]
    exit_code, reason = None, "entry_not_found_after_command"
    config, _problem = _user_config(env)
    servers = (config or {}).get("mcpServers", {})
    if type(servers) is not dict or servers.get(SERVER_NAME) != before["entry"]:
        exit_code, failure = _run_claude(run, [exe, "mcp", "add-json", SERVER_NAME,
            json.dumps(before["entry"], separators=(",", ":")), "--scope", "user"], env)
        if failure:
            reason = "claude_mcp_add_" + failure
    retired, stopped = {}, None
    config, _problem = _user_config(env)
    servers = (config or {}).get("mcpServers", {})
    # A development-era entry is retired only once this install's entry is there.
    if before["claude_code"] == "migration_available" and type(servers) is dict \
            and servers.get(SERVER_NAME) == before["entry"]:
        for name in before["legacy_retire"]:
            config, _problem = _user_config(env)
            servers = (config or {}).get("mcpServers", {})
            if type(servers) is not dict or name not in _retired_legacy(servers):
                stopped = "legacy_entry_changed_before_removal"
                break
            exit_code, failure = _run_claude(run, [exe, "mcp", "remove", name, "--scope", "user"], env)
            if failure:
                stopped = "claude_mcp_remove_" + failure
                break
            retired[name] = servers[name]
    # The command's exit code is not the evidence; the configuration is.
    after = readiness(install_root, state_root, environment=env)
    if retired:
        after["retired"] = retired
    if stopped:
        after.update(claude_code="migration_unconfirmed", reason=stopped, exit_code=exit_code)
    elif after["claude_code"] != "registered":
        after.update(claude_code="registration_unconfirmed", reason=reason, exit_code=exit_code)
    return after


__all__ = [
    "DEAD_BRAIN_PORTS",
    "LEGACY_NAMES",
    "LOADER",
    "RegistrationRefused",
    "confirm_entries",
    "find_claude_code",
    "managed_entry",
    "readiness",
    "register_claude_code",
    "stale_entries",
]
