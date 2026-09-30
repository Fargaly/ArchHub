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
* OpenCode: no MCP entry. OpenCode gives MCP servers no session identity, and
  the native owner requires the real ``ses_...`` hook identity; OpenCode
  attaches through the Session Link plugin instead. On consent one portable
  plugin file is written to the OpenCode config folder: it imports this
  install's opencode-plugin.mjs pinned by its sha256 and names this install's
  Session Link state folder, and no session.

A differing entry of the same name, an unreadable config or a legacy entry
(client_mcp_installation.LEGACY_NAMES) is reported and left untouched, except
ArchHub's verified development-era coordination entry, which Replace retires. Nothing
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


# ArchHub's own development-era launch of this same server name: the source-tree
# start (python -m nodelang.clean_coordination_mcp, PYTHONPATH) with no env_vars.
# Codex then hands the server no CODEX_THREAD_ID, so it exits before the MCP
# handshake. Only this exact shape is replaced, and only on consent; any other
# same-name entry stays a conflict and is never touched.
_DEV_ERA_ARGS = ["-m", "nodelang.clean_coordination_mcp"]
_DEV_ERA_ENV = {"PYTHONPATH", "ARCHHUB_COORDINATION_VENDOR"}


def _dev_era_codex_entry(entry) -> bool:
    import ntpath
    if type(entry) is not dict or set(entry) != {"command", "args", "env"}:
        return False
    command, env = entry["command"], entry["env"]
    return (entry["args"] == _DEV_ERA_ARGS
            and type(command) is str and ntpath.basename(command).casefold() == "python.exe"
            and type(env) is dict and set(env) == _DEV_ERA_ENV
            and env["ARCHHUB_COORDINATION_VENDOR"] == "codex"
            and type(env["PYTHONPATH"]) is str and ntpath.isabs(env["PYTHONPATH"]))


def _replace_codex_table(text: str, block: str) -> str:
    """Swap the one [mcp_servers.SERVER_NAME] table (with its sub-tables) in place.

    Every line outside that table is kept, including comments around it; a
    comment directly above the next table belongs to that table and stays.
    """
    lines = text.splitlines(keepends=True)
    head, sub = "[mcp_servers.%s]" % SERVER_NAME, "[mcp_servers.%s." % SERVER_NAME
    starts = [i for i, line in enumerate(lines) if line.strip() == head]
    if len(starts) != 1:
        raise ValueError("the server table is not in one recognisable place")
    start, end = starts[0], starts[0] + 1
    while end < len(lines):
        stripped = lines[end].strip()
        if stripped.startswith("[") and not stripped.startswith(sub):
            break
        end += 1
    while end > start + 1 and lines[end - 1].strip().startswith("#"):
        end -= 1
    if any(line.strip().startswith(sub) for line in lines[:start] + lines[end:]):
        raise ValueError("the server table is split across the file")
    replacement = block.lstrip("\n")
    if end < len(lines):
        replacement += "\n"
    return "".join(lines[:start]) + replacement + "".join(lines[end:])


def _others(data: dict) -> dict:
    servers = data.get("mcp_servers", {})
    return {**data, "mcp_servers": {k: v for k, v in servers.items() if k != SERVER_NAME}}


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
        if servers[SERVER_NAME] == entry:
            return dict(report, state="registered")
        if _dev_era_codex_entry(servers[SERVER_NAME]):
            return dict(report, state="migration_available",
                        reason="ArchHub's development-era start of this server gives it no "
                               "CODEX_THREAD_ID, so Codex cannot start it; Replace writes this install's entry")
        return dict(report, state="conflict")
    if report["legacy_migration_needed"]:
        return dict(report, state="legacy_migration_required")
    return dict(report, state="ready_to_register", config_exists=True)


def migrate_codex(install_root, state_root, *, consent, environment=None) -> dict:
    """Replace only ArchHub's development-era table, on consent; every other setting keeps its meaning.

    The whole prior file is kept, DPAPI-protected, in the private backup folder.
    The rewrite must parse to this install's entry with every other setting
    unchanged before it is written, and is read back after; otherwise nothing
    is claimed.
    """
    import hashlib
    import tomllib
    from .session_link_config import SessionLinkConfigRefused, write_with_backup
    env = os.environ if environment is None else environment
    before = codex_readiness(install_root, state_root, env)
    if consent is not True or before["state"] != "migration_available":
        return before
    path = Path(before["config"])
    raw = path.read_bytes()
    # Eligibility is decided again on these exact bytes, the ones that are hashed
    # and rewritten: another writer may have changed the entry since readiness.
    try:
        old = tomllib.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        return dict(before, state="config_unreadable")
    current = old.get("mcp_servers", {}).get(SERVER_NAME) if type(old.get("mcp_servers")) is dict else None
    if not _dev_era_codex_entry(current):
        return dict(before, state="registered" if current == before["entry"] else "conflict",
                    reason="the entry changed after it was checked; nothing was written")
    try:
        text = _replace_codex_table(raw.decode("utf-8"), _codex_block(before["entry"]))
        new = tomllib.loads(text)
    except (ValueError, UnicodeError) as exc:
        return dict(before, state="migration_unconfirmed", reason=str(exc))
    if _others(old) != _others(new) or new.get("mcp_servers", {}).get(SERVER_NAME) != before["entry"]:
        return dict(before, state="migration_unconfirmed",
                    reason="the rewrite would change more than this server's entry")
    backup_dir = Path(state_root) / "private-client-backups"
    from .client_mcp_installation import _require_plain
    _require_plain(backup_dir, "directory", may_be_absent=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    from .cell_secret_keys import protect_current_user_data
    try:
        result = write_with_backup(
            path, text, backup_dir, expected_digest=hashlib.sha256(raw).hexdigest(),
            protect_backup=lambda data: protect_current_user_data(
                data, purpose="archhub.client-hook-backup/v1"))
    except SessionLinkConfigRefused as exc:
        return dict(before, state="migration_unconfirmed", reason=str(exc))
    after = codex_readiness(install_root, state_root, env)
    if after["state"] != "registered":
        return dict(after, state="migration_unconfirmed", reason="entry_not_found_after_write")
    return dict(after, backup=result.get("backup"))


def register_codex(install_root, state_root, *, consent, environment=None) -> dict:
    """Append our table only on consent and only where no same-name entry exists; re-read.

    ArchHub's own development-era entry of the same name is replaced instead
    (migrate_codex), on the same consent; any other same-name entry is left.
    """
    env = os.environ if environment is None else environment
    before = codex_readiness(install_root, state_root, env)
    if consent is True and before["state"] == "migration_available":
        return migrate_codex(install_root, state_root, consent=True, environment=env)
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


OPENCODE_PLUGIN_NAME = "session-link.js"
OPENCODE_GOVERNANCE_BLOCKER = (
    "OpenCode's tool governance loader is not written: its write gate "
    "(opencode_native_gate.py with pretooluse_validate and governed_write_broker) lives only "
    "in the ArchHub workspace's 00.GOVERNANCE/hooks, and the installed app ships no gate")


def _opencode_config_dir(env) -> Path | None:
    """OpenCode's global config folder: $XDG_CONFIG_HOME/opencode, else ~/.config/opencode."""
    base = env.get("XDG_CONFIG_HOME") or (
        str(Path(env["USERPROFILE"]) / ".config") if env.get("USERPROFILE") else None)
    return Path(base) / "opencode" if base else None


def _opencode_installed(env) -> bool:
    from .model_router import find_assistant
    folder = _opencode_config_dir(env)
    return bool((folder is not None and folder.is_dir()) or find_assistant("opencode", env))


def render_opencode_plugin(install_root, state_root) -> str:
    """The portable Session Link plugin for OpenCode; the same for every user of one install."""
    import hashlib
    module = Path(install_root) / "nodelang" / "session_link" / "opencode-plugin.mjs"
    if not module.is_file():
        raise RegistrationRefused("installed Session Link module missing")
    revision = hashlib.sha256(module.read_bytes()).hexdigest()
    state = str(Path(state_root) / "session-link").replace("\\", "/")
    literal = lambda value: json.dumps(value, ensure_ascii=True)
    return ("// ArchHub Session Link for OpenCode, written by ArchHub on your consent.\n"
            "import {createSessionLinkPlugin} from %s;\n"
            "export const SessionLink = createSessionLinkPlugin({stateDirectory:%s});\n"
            % (literal(module.as_uri() + "?revision=" + revision), literal(state)))


def _archhub_session_link_loader(raw: bytes) -> bool:
    text = raw.decode("utf-8", "replace")
    return ("createSessionLinkPlugin" in text
            and "/nodelang/session_link/opencode-plugin.mjs" in text and len(raw) < 4096)


def opencode_readiness(install_root, state_root, environment=None) -> dict:
    env = os.environ if environment is None else environment
    report = {"client": "opencode", "server_name": SERVER_NAME,
              "governance": "blocked", "governance_reason": OPENCODE_GOVERNANCE_BLOCKER}
    if not _opencode_installed(env):
        return dict(report, state="not_installed")
    folder = _opencode_config_dir(env)
    if folder is None:
        return dict(report, state="config_location_unverified")
    target = folder / "plugins" / OPENCODE_PLUGIN_NAME
    report["config"] = str(target)
    if not (Path(install_root) / "BUILD_METADATA.json").is_file():
        # session_link_config.installed_stop_hook: assistant hooks come only from the installed ArchHub.
        return dict(report, state="install_required",
                    reason="assistant plugins are installed only from the installed ArchHub")
    try:
        report["plugin"] = render_opencode_plugin(install_root, state_root)
    except RegistrationRefused as exc:
        return dict(report, state="install_incomplete", reason=str(exc))
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return dict(report, state="ready_to_register", config_exists=False)
    except OSError:
        return dict(report, state="config_unreadable")
    if raw.replace(b"\r\n", b"\n") == report["plugin"].encode("utf-8"):
        return dict(report, state="registered")
    if _archhub_session_link_loader(raw):
        return dict(report, state="ready_to_register", config_exists=True,
                    reason="an older ArchHub Session Link plugin is replaced")
    return dict(report, state="conflict",
                reason="another %s is in the OpenCode plugins folder; left unchanged" % OPENCODE_PLUGIN_NAME)


def register_opencode(install_root, state_root, *, consent, environment=None) -> dict:
    """Write the portable plugin only on consent, keep a backup of what it replaces, re-read."""
    from .session_link_config import write_with_backup, SessionLinkConfigRefused
    env = os.environ if environment is None else environment
    before = opencode_readiness(install_root, state_root, env)
    if consent is not True or before["state"] != "ready_to_register":
        return before
    target = Path(before["config"])
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(state_root) / "private-client-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    expected = (hashlib.sha256(target.read_bytes()).hexdigest()
                if before["config_exists"] else "absent")
    try:
        result = write_with_backup(target, before["plugin"], backup_dir, expected_digest=expected)
    except SessionLinkConfigRefused as exc:
        return dict(before, state="registration_unconfirmed", reason=str(exc))
    if result.get("sha256"):
        receipts = _read_hook_receipts(state_root)
        receipts["opencode"] = {"target": str(target), "after": result["sha256"],
                                "backup": result.get("backup")}
        _write_hook_receipts(state_root, receipts)
    after = opencode_readiness(install_root, state_root, env)
    if after["state"] != "registered":
        after.update(state="registration_unconfirmed", reason="plugin_not_found_after_write")
    return after


def _remove_opencode_plugin(receipt) -> dict:
    """Uninstall: delete the plugin only while it still holds exactly the bytes ArchHub wrote."""
    import hashlib
    row = {"vendor": "opencode", "changed": False, "method": "absent"}
    if not receipt or not receipt.get("target") or not receipt.get("after"):
        return row
    target = Path(receipt["target"])
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return row
    if hashlib.sha256(raw).hexdigest() != receipt["after"]:
        return dict(row, method="kept_changed")
    target.unlink()
    return dict(row, changed=True, method="removed")


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
    return register_opencode(root, state, consent=True, environment=env)


__all__ = ["CLIENTS", "codex_entry", "codex_readiness", "install_roots", "mcp_server_spec",
           "migrate_codex", "opencode_readiness", "readiness", "register", "register_codex",
           "register_opencode", "render_opencode_plugin"]



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
        # OpenCode has no end-of-turn hook here; it connects through the Session Link plugin.
        root, state = install_roots(env)
        try:
            done = register_opencode(root, state, consent=True, environment=env)
            said = done["state"] if done["state"] in ("registered", "not_installed", "conflict") \
                else "not_connected"
            results.append({"client": "opencode", "state": said,
                            **({"reason": done["reason"]} if said == "conflict" else {})})
        except (SessionLinkConfigRefused, RegistrationRefused, OSError, ValueError):
            results.append({"client": "opencode", "state": "not_connected"})
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
        try:
            results.append(_remove_opencode_plugin(receipts.get("opencode")))
            receipts.pop("opencode", None)
        except OSError:
            results.append({"vendor": "opencode", "changed": False, "method": "refused"})
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
