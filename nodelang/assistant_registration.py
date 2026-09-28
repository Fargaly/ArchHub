"""Connect a person's own assistants to the installed ArchHub MCP server, on consent.

One server, the installed native owner (nodelang/native_agent_mcp.py, entry
name SERVER_NAME). It carries the Work, Workshop and host tools (``hosts.status``
and the host tools of native_host_tools; host effects need a claimed Work).
Settings -> Hosts shows each client's state and writes an entry only after the
person presses Connect for that client. ``mcp_server_spec`` is what any
installer writes and removes for a client.

* Claude Code: through its own command (client_mcp_installation, unchanged).
* Codex: one ``[mcp_servers.SERVER_NAME]`` table appended to
  %USERPROFILE%\\.codex\\config.toml (or $CODEX_HOME), bytes before it kept.
  Codex hands CODEX_THREAD_ID to the server through ``env_vars``.
* OpenCode: reported, never written. OpenCode gives MCP servers no session
  identity, and the native owner requires the real ``ses_...`` hook identity;
  OpenCode attaches through the Session Link plugin instead.

A differing entry of the same name, an unreadable config or a legacy entry
(client_mcp_installation.LEGACY_NAMES) is reported and left untouched. Nothing
here starts the server, so nothing here proves a connection or a host action.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .client_mcp_installation import (
    LEGACY_NAMES,
    RegistrationRefused,
    managed_entry,
    readiness as claude_readiness,
    register_claude_code,
    confirm_entries,
    stale_entries,
)
from .native_workshop_profile import SERVER_NAME

CLIENTS = ("claude-code", "codex", "opencode")
_MAX_CONFIG_BYTES = 4 * 1024 * 1024


def install_roots(environment=None) -> tuple[Path, Path]:
    """This installation and the launcher's state folder (launch_archhub_test.py owns it)."""
    env = os.environ if environment is None else environment
    root = Path(os.path.abspath(Path(__file__).resolve().parent.parent))
    state = Path(env.get("ARCHHUB_TEST_STATE_DIR")
                 or Path(env.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub-Test")
    return root, state


def codex_entry(install_root, state_root) -> dict:
    entry = managed_entry(install_root, state_root)
    env = dict(entry["env"], ARCHHUB_COORDINATION_VENDOR="codex")
    return {"command": entry["command"], "args": list(entry["args"]),
            "env_vars": ["CODEX_THREAD_ID"], "env": env}


def mcp_server_spec(client: str, *, existing=None, environment=None) -> dict:
    """What an installer writes and removes for one client; reads nothing, writes nothing.

    ``add`` holds exactly one entry, the shipped native owner of this install.
    ``remove`` names the existing entries (``existing`` is the client's current
    server table) that are verified ArchHub development-era entries; ``ask``
    names those to remove only on the person's word. Each carries its reason.
    """
    env = os.environ if environment is None else environment
    root, state = install_roots(env)
    if client == "claude-code":
        entry = managed_entry(root, state)
    elif client == "codex":
        entry = codex_entry(root, state)
    else:
        raise ValueError("no MCP server spec for %r" % client)
    return {"client": client, "server_name": SERVER_NAME, "add": {SERVER_NAME: entry},
            "remove": stale_entries(existing or {}), "ask": confirm_entries(existing or {})}


def _codex_config(env) -> Path | None:
    home = env.get("CODEX_HOME") or (Path(env["USERPROFILE"]) / ".codex" if env.get("USERPROFILE") else None)
    return Path(home) / "config.toml" if home else None


def _toml_string(value: str) -> str:
    # A JSON string of printable text is a valid TOML basic string.
    return json.dumps(value, ensure_ascii=False)


def _codex_block(entry: dict) -> str:
    lines = ["", "[mcp_servers.%s]" % SERVER_NAME,
             "command = %s" % _toml_string(entry["command"]),
             "args = [%s]" % ", ".join(_toml_string(a) for a in entry["args"]),
             "env_vars = [%s]" % ", ".join(_toml_string(a) for a in entry["env_vars"]),
             "", "[mcp_servers.%s.env]" % SERVER_NAME]
    lines += ["%s = %s" % (key, _toml_string(value)) for key, value in entry["env"].items()]
    return "\n".join(lines) + "\n"


def codex_readiness(install_root, state_root, environment=None) -> dict:
    env = os.environ if environment is None else environment
    report = {"client": "codex", "server_name": SERVER_NAME, "legacy_migration_needed": []}
    try:
        report["entry"] = entry = codex_entry(install_root, state_root)
    except RegistrationRefused as exc:
        return dict(report, state="install_incomplete", reason=str(exc))
    path = _codex_config(env)
    if path is None:
        return dict(report, state="config_location_unverified")
    report["config"] = str(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return dict(report, state="ready_to_register", config_exists=False)
    except OSError:
        return dict(report, state="config_unreadable")
    if len(raw) > _MAX_CONFIG_BYTES:
        return dict(report, state="config_unreadable")
    import tomllib
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError):
        return dict(report, state="config_unreadable")
    servers = data.get("mcp_servers", {})
    if type(servers) is not dict:
        return dict(report, state="config_unreadable")
    report["legacy_migration_needed"] = [name for name in LEGACY_NAMES if name in servers]
    if SERVER_NAME in servers:
        return dict(report, state="registered" if servers[SERVER_NAME] == entry else "conflict")
    if report["legacy_migration_needed"]:
        return dict(report, state="legacy_migration_required")
    return dict(report, state="ready_to_register", config_exists=True)


def register_codex(install_root, state_root, *, consent, environment=None) -> dict:
    """Append our table only on consent and only where no same-name entry exists; re-read."""
    env = os.environ if environment is None else environment
    before = codex_readiness(install_root, state_root, env)
    if consent is not True or before["state"] != "ready_to_register":
        return before
    path = Path(before["config"])
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_bytes() if before["config_exists"] else b""
    separator = b"" if not original or original.endswith(b"\n") else b"\n"
    payload = original + separator + _codex_block(before["entry"]).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".config.toml.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Refuse to replace a file another writer changed since it was read.
        if (path.read_bytes() if path.exists() else b"") != original:
            return dict(before, state="registration_unconfirmed", reason="config_changed_during_write")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    after = codex_readiness(install_root, state_root, env)
    if after["state"] != "registered":
        after.update(state="registration_unconfirmed", reason="entry_not_found_after_write")
    return after


def opencode_readiness(install_root, state_root, environment=None) -> dict:
    return {"client": "opencode", "server_name": SERVER_NAME, "state": "unsupported",
            "reason": ("OpenCode passes no session identity to MCP servers and the ArchHub owner "
                       "requires its real ses_ hook identity; OpenCode connects through the "
                       "Session Link plugin (nodelang/session_link/opencode-plugin.mjs)")}


def _claude(install_root, state_root, env) -> dict:
    report = claude_readiness(install_root, state_root, environment=env)
    state = report.pop("claude_code")
    return dict(report, client="claude-code", state=state)


def _gemini_state(hooks, env) -> str:
    """Gemini CLI has no connection entry here; say only what its folder and hooks show."""
    profile = env.get("USERPROFILE")
    if not profile or not (Path(profile) / ".gemini").is_dir():
        return "not_installed"
    return "hook_only" if hooks.get("state") == "configured" else "unsupported"


def readiness(environment=None) -> dict:
    """Every client's state for this Windows user; reads files only."""
    env = os.environ if environment is None else environment
    root, state = install_roots(env)
    clients = [_claude(root, state, env), codex_readiness(root, state, env),
               opencode_readiness(root, state, env), {"client": "gemini-cli"}]
    for client in clients:
        client["hooks"] = hook_readiness(client["client"], environment=env)
    clients[-1]["state"] = _gemini_state(clients[-1]["hooks"], env)
    return {"server_name": SERVER_NAME, "clients": clients}


def register(client: str, *, consent, environment=None) -> dict:
    """Write one client's entry on this explicit consent, then report what is true."""
    env = os.environ if environment is None else environment
    if client not in CLIENTS:
        raise ValueError("unknown assistant client")
    if consent is not True:
        raise ValueError("registration needs the person's explicit consent")
    root, state = install_roots(env)
    if client == "claude-code":
        report = register_claude_code(root, state, consent=True, environment=env)
        state_name = report.pop("claude_code")
        return dict(report, client=client, state=state_name)
    if client == "codex":
        return register_codex(root, state, consent=True, environment=env)
    return opencode_readiness(root, state, env)


__all__ = ["CLIENTS", "codex_entry", "codex_readiness", "install_roots", "mcp_server_spec",
           "readiness", "register", "register_codex"]



def preview_hooks(client, *, environment=None):
    """Owner-facing preview; disclose neither the full config nor secret backup bytes."""
    from .session_link_config import (observed_client_hook_binding, plan_client_hook_install,
                                      SessionLinkConfigRefused)
    env = os.environ if environment is None else environment
    root, state = install_roots(env)
    if not env.get("USERPROFILE"):
        raise SessionLinkConfigRefused("client home directory is unavailable")
    home = Path(env["USERPROFILE"])
    executable, gate = observed_client_hook_binding(client, home=home)
    plan = plan_client_hook_install(client, home=home, install_root=root,
                                   python_executable=executable, gate_script=gate)
    return {"client": client, "plan_digest": plan["plan_digest"], "changed": plan["changed"],
            "events": plan["managed_events"], "activation": plan["activation"],
            "description": "Repair ArchHub safety settings while keeping your other settings. "
                           "Keep an encrypted backup of your current settings. "
                           "The assistant may still need to approve and load the changes."}


def _repair_hooks(client, *, consent, plan_digest, environment=None):
    from .session_link_config import (observed_client_hook_binding, plan_client_hook_install,
                                      apply_client_hook_install, SessionLinkConfigRefused)
    if consent is not True:
        raise SessionLinkConfigRefused("hook repair requires the reviewed user's consent")
    env = os.environ if environment is None else environment
    root, state = install_roots(env)
    if not env.get("USERPROFILE"):
        raise SessionLinkConfigRefused("client home directory is unavailable")
    home = Path(env["USERPROFILE"])
    executable, gate = observed_client_hook_binding(client, home=home)
    plan = plan_client_hook_install(client, home=home, install_root=root,
                                   python_executable=executable, gate_script=gate)
    if plan["plan_digest"] != plan_digest:
        raise SessionLinkConfigRefused("settings changed; review the current hook preview")
    backup_dir = state / "private-client-backups"
    from .client_mcp_installation import _require_plain
    _require_plain(backup_dir, "directory", may_be_absent=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    result = apply_client_hook_install(plan, expected_digest=plan_digest, backup_dir=backup_dir)
    return {"client": client, "changed": result["changed"], "state": "configured",
            "activation_pending": True,
            "reason": "Settings are saved. We have not yet checked that the assistant is using them."}


import threading as _hook_threading
_HOOK_REPAIR_LOCK = _hook_threading.RLock()


def repair_hooks(client, *, consent, plan_digest, environment=None):
    with _HOOK_REPAIR_LOCK:
        return _repair_hooks(client, consent=consent, plan_digest=plan_digest, environment=environment)


def hook_readiness(client, *, environment=None):
    from .session_link_config import SessionLinkConfigRefused
    if client not in ("claude-code", "codex", "gemini-cli"):
        return {"available": False, "state": "unsupported", "reason": "Manage this assistant through its own connection settings."}
    try:
        plan = preview_hooks(client, environment=environment)
        return {"available": True, "state": "repair_available" if plan["changed"] else "configured",
                "reason": "Safety settings can be reviewed here. We have not yet checked that the assistant is using them."}
    except (SessionLinkConfigRefused, RegistrationRefused, OSError, ValueError):
        return {"available": False, "state": "install_incomplete",
                "reason": "The installed safety settings could not be identified. Repair the assistant installation first."}
