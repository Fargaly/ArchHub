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


def _codex_home(env) -> Path | None:
    """The one effective Codex home: CODEX_HOME, else %USERPROFILE%\\.codex. Connection
    entry, hooks, readiness and uninstall all use this."""
    home = env.get("CODEX_HOME") or (Path(env["USERPROFILE"]) / ".codex" if env.get("USERPROFILE") else None)
    return Path(home) if home else None


def _codex_config(env) -> Path | None:
    home = _codex_home(env)
    return home / "config.toml" if home else None


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



_HOOK_FOLDERS = {"claude-code": ".claude", "codex": ".codex", "gemini-cli": ".gemini"}


def _client_folder(client, env):
    """The folder whose presence means this assistant is installed for this user."""
    if client == "codex":
        return _codex_home(env)
    profile = env.get("USERPROFILE")
    return Path(profile) / _HOOK_FOLDERS[client] if profile else None


def _hook_homes(client, env):
    from .session_link_config import SessionLinkConfigRefused
    if not env.get("USERPROFILE"):
        raise SessionLinkConfigRefused("client home directory is unavailable")
    codex_home = _codex_home(env) if client == "codex" else None
    if codex_home is not None and not codex_home.is_absolute():
        raise SessionLinkConfigRefused("CODEX_HOME must be an absolute folder")
    return Path(env["USERPROFILE"]), codex_home


def _hook_plan(client, env, *, include_gate, migrate):
    """One private plan: ArchHub's installed end-of-turn check, plus (Settings only) the
    in-place spelling repair of an existing workspace gate. The gate is never added.
    migrate (Settings only, reviewed) moves another or stale ArchHub copy's check here."""
    from .session_link_config import (observed_client_hook_binding, plan_client_hook_install,
                                      SessionLinkConfigRefused)
    if client not in _HOOK_FOLDERS:
        raise SessionLinkConfigRefused("unsupported hook client")
    root, state = install_roots(env)
    home, codex_home = _hook_homes(client, env)
    binding = (observed_client_hook_binding(client, home=home, optional=True, codex_home=codex_home)
               if include_gate else None)
    executable, gate = binding or (None, None)
    plan = plan_client_hook_install(client, home=home, install_root=root, python_executable=executable,
                                    gate_script=gate, stop_root=root, migrate=migrate,
                                    codex_home=codex_home)
    return plan, state


_MIGRATION_WORDS = {
    "mixed": ("This install's end-of-turn check is set, and so is another or an old one. "
              "Repair moves it to this install and leaves only this install's."),
    "other_copy": "Another ArchHub copy's end-of-turn check is set here. Repair moves it to this install.",
    "stale": ("The end-of-turn check here points at a file that no longer exists (or a drive that is "
              "not connected). Repair moves it to this install."),
}


def _migration_words(plan):
    return _MIGRATION_WORDS["mixed" if "ours" in plan["stop_roles"] else plan["stop_binding"]]


def preview_hooks(client, *, environment=None, include_gate=True, migrate=True):
    """Owner-facing preview; disclose neither the full config nor secret backup bytes."""
    env = os.environ if environment is None else environment
    plan, _ = _hook_plan(client, env, include_gate=include_gate, migrate=migrate)
    preview = {"client": client, "plan_digest": plan["plan_digest"], "changed": plan["changed"],
               "events": plan["managed_events"], "activation": plan["activation"],
               "stop_binding": plan["stop_binding"], "stop_roles": plan["stop_roles"],
               "migration": plan["migration"],
               "description": "Add ArchHub's end-of-turn check while keeping your other settings. "
                              "Keep an encrypted backup of your current settings. "
                              "The assistant may still need to approve and load the changes."}
    if plan["migration"]:
        preview["description"] = _migration_words(plan) + " " + preview["description"]
    return preview


def _repair_hooks(client, *, consent, plan_digest, environment=None, include_gate=True, migrate=True):
    from .session_link_config import apply_client_hook_install, SessionLinkConfigRefused
    if consent is not True:
        raise SessionLinkConfigRefused("hook repair requires the reviewed user's consent")
    env = os.environ if environment is None else environment
    plan, state = _hook_plan(client, env, include_gate=include_gate, migrate=migrate)
    if plan["plan_digest"] != plan_digest:
        raise SessionLinkConfigRefused("settings changed; review the current hook preview")
    backup_dir = state / "private-client-backups"
    from .client_mcp_installation import _require_plain
    _require_plain(backup_dir, "directory", may_be_absent=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    result = apply_client_hook_install(plan, expected_digest=plan_digest, backup_dir=backup_dir)
    if result["changed"]:
        _record_hook_write(state, client, plan, result)
    return {"client": client, "changed": result["changed"], "state": "configured",
            "activation_pending": True,
            "reason": "Settings are saved. We have not yet checked that the assistant is using them."}


import threading as _hook_threading
_HOOK_REPAIR_LOCK = _hook_threading.RLock()


def repair_hooks(client, *, consent, plan_digest, environment=None):
    with _HOOK_REPAIR_LOCK:
        return _repair_hooks(client, consent=consent, plan_digest=plan_digest, environment=environment)


def connect_hooks_on_setup(*, consent, environment=None) -> list:
    """The installer's "Connect my AI assistants to ArchHub" choice, through the same consent
    path as Settings > Repair: ArchHub's end-of-turn check for each assistant that is
    installed. An existing workspace gate is left exactly as it is."""
    from .session_link_config import SessionLinkConfigRefused
    from .client_mcp_installation import RegistrationRefused
    if consent is not True:
        raise ValueError("connecting assistants needs the person's explicit consent")
    env = os.environ if environment is None else environment
    results = []
    with _HOOK_REPAIR_LOCK:
        for client in _HOOK_FOLDERS:
            folder = _client_folder(client, env)
            if folder is None or not folder.is_dir():
                results.append({"client": client, "state": "not_installed"})
                continue
            try:
                plan = preview_hooks(client, environment=env, include_gate=False, migrate=False)
                if plan["stop_binding"] in ("other_copy", "stale"):
                    # Never overwritten at setup, never called configured, even beside ours:
                    # reviewed in Settings. Only a lone stale entry is reported as stale.
                    lone_stale = plan["stop_binding"] == "stale" and "ours" not in plan["stop_roles"]
                    results.append({"client": client, "changed": False,
                                    "state": "stale" if lone_stale else "conflict",
                                    "roles": plan["stop_roles"], "reason": _migration_words(plan)})
                    continue
                done = _repair_hooks(client, consent=True, plan_digest=plan["plan_digest"],
                                     environment=env, include_gate=False, migrate=False)
                results.append({"client": client, "state": "configured", "changed": done["changed"]})
            except (SessionLinkConfigRefused, RegistrationRefused, OSError, ValueError):
                results.append({"client": client, "state": "not_connected"})
    return results


_HOOK_RECEIPTS = "assistant-hooks.json"


def _read_hook_receipts(state):
    try:
        value = json.loads((Path(state) / _HOOK_RECEIPTS).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    return value if type(value) is dict else {}


def _write_hook_receipts(state, receipts):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".assistant-hooks-", dir=state)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(receipts, stream, indent=2, sort_keys=True)
        os.replace(name, state / _HOOK_RECEIPTS)
    finally:
        Path(name).unlink(missing_ok=True)


def _record_hook_write(state, client, plan, result):
    """What uninstall needs to put the file back exactly: the first write's prior bytes.
    A later write on top keeps only the path-matched removal (no stale restore)."""
    receipts = _read_hook_receipts(state)
    receipts[client] = ({"target": plan["target"], "before": plan["before_digest"],
                         "after": result.get("sha256"), "backup": result.get("backup")}
                        if client not in receipts else
                        {"target": plan["target"], "before": None, "after": None, "backup": None})
    _write_hook_receipts(state, receipts)


def disconnect_hooks_on_uninstall(environment=None) -> list:
    """Uninstall: take out exactly the end-of-turn entries this install wrote; nothing else."""
    from .session_link_config import remove_stop_hook, SessionLinkConfigRefused
    from .client_mcp_installation import RegistrationRefused
    env = os.environ if environment is None else environment
    root, state = install_roots(env)
    receipts = _read_hook_receipts(state)
    results = []
    with _HOOK_REPAIR_LOCK:
        for client in _HOOK_FOLDERS:
            try:
                home, codex_home = _hook_homes(client, env)
                backup_dir = state / "private-client-backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                results.append(remove_stop_hook(client, home=home, install_root=root,
                                                receipt=receipts.get(client), backup_dir=backup_dir,
                                                codex_home=codex_home))
                receipts.pop(client, None)
            except (SessionLinkConfigRefused, RegistrationRefused, OSError, ValueError):
                results.append({"vendor": client, "changed": False, "method": "refused"})
        _write_hook_receipts(state, receipts)
    return results


def main(argv=None) -> int:
    import sys
    args = sys.argv[1:] if argv is None else argv
    if args != ["disconnect-hooks"]:
        print("usage: python -m nodelang.assistant_registration disconnect-hooks", file=sys.stderr)
        return 2
    for row in disconnect_hooks_on_uninstall():
        print("%s: %s" % (row["vendor"], row["method"]))
    return 0


_EVENT_WORDS = {
    "on": "On",
    "off": "Off",
    "other_copy": "Set by another ArchHub copy; left unchanged until you Repair",
    "stale": "Points at a missing file; left unchanged until you Repair",
    "on_with_other_copy": "On, but another ArchHub copy's check is also set; Repair leaves only this install's",
    "on_with_stale": "On, but an old check pointing at a missing file is also set; Repair leaves only this install's",
}


def hook_readiness(client, *, environment=None):
    """Per event, in plain words, whether ArchHub's own hook is set for this assistant."""
    from .session_link_config import SessionLinkConfigRefused, hook_event_states
    env = os.environ if environment is None else environment
    if client == "opencode":
        return {"available": False, "state": "per_session", "events": [],
                "reason": "Connects when you open a session"}
    if client not in _HOOK_FOLDERS:
        return {"available": False, "state": "unsupported", "events": [],
                "reason": "Not supported yet"}
    root, _ = install_roots(env)
    folder = _client_folder(client, env)
    if folder is None or not folder.is_dir():
        return {"available": False, "state": "not_installed", "events": [],
                "reason": "This assistant is not installed for this Windows user."}
    if not (root / "BUILD_METADATA.json").is_file():
        return {"available": False, "state": "install_required", "events": [],
                "reason": "Open the installed ArchHub to connect this assistant."}
    try:
        home, codex_home = _hook_homes(client, env)
        events = hook_event_states(client, home=home, install_root=root, codex_home=codex_home)
        plan = preview_hooks(client, environment=env)
    except (SessionLinkConfigRefused, RegistrationRefused, OSError, ValueError):
        return {"available": False, "state": "install_incomplete", "events": [],
                "reason": "The assistant's settings could not be read. Repair the assistant installation first."}
    for row in events:
        row["said"] = "When a reply ends, ArchHub checks for open work: " + _EVENT_WORDS[row["state"]]
    state = ("migration_available" if plan["migration"] else
             "repair_available" if plan["changed"] or any(e["state"] != "on" for e in events) else "configured")
    report = {"available": True, "state": state,
              "events": events,
              "reason": "Settings are saved separately from checking that the assistant is using them."}
    if client == "codex":
        report["approval"] = "Approve in Codex"
    return report


if __name__ == "__main__":
    raise SystemExit(main())
