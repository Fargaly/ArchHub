"""Connect a person's own assistants to the installed ArchHub MCP server, on consent.

One server, the installed native owner (nodelang/native_agent_mcp.py, entry
name SERVER_NAME). It carries the Work, Workshop and host tools, including
``hosts.status``; host operations themselves run only as graph nodes inside
admitted Work. Settings -> Hosts shows each client's state and writes an entry
only after the person presses Connect for that client.

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


def readiness(environment=None) -> dict:
    """Every client's state for this Windows user; reads files only."""
    env = os.environ if environment is None else environment
    root, state = install_roots(env)
    return {"server_name": SERVER_NAME, "clients": [
        _claude(root, state, env),
        codex_readiness(root, state, env),
        opencode_readiness(root, state, env),
    ]}


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


__all__ = ["CLIENTS", "codex_entry", "codex_readiness", "install_roots", "readiness",
           "register", "register_codex"]
