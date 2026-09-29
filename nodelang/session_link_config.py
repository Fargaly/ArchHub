"""The installed application owns Session Link's entry, state and agent configuration.

One source: the entry script and the transport ship inside the install
(nodelang/session_link); state lives where the application composes it
(ARCHHUB_TEST_STATE_DIR or %LOCALAPPDATA%/ArchHub-Test, then session-link).
Agent-side files (the session-link skill for Claude, Codex and OpenCode, and
the OpenCode governance loader) are rendered from this module, never written
by hand or from a handoff folder.

Nothing here starts a bridge, resumes a connection, creates a session or
reloads a host. `migrate` copies existing connection records once, keeping
their ids, one connection whole or not at all: if any of its files differs at
the destination, none are copied and it is reported. Nothing is overwritten
and the source is never deleted.
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parents[1]
SKILL_TEMPLATE = Path(__file__).resolve().with_name("session_link") / "agent-skill.md"
_RECORD = re.compile(r"^[a-f0-9]{16}\.(binding\.json|runtime\.json|events\.jsonl|stderr\.log)$")
_SESSION = re.compile(r"^ses_[A-Za-z0-9]+$")
_CONNECTION = re.compile(r"^[a-f0-9]{16}$")
_ACTOR = re.compile(r"^app:agent-session:runtime:[a-f0-9]{32}$")
_WORK = re.compile(r"^assembly-instance:[a-f0-9]{32}$")
_PLAIN = re.compile(r"^[A-Za-z0-9 _:./\-]+$")
# A lane is one absolute 70.HANDOFFS/<lane>/work/<name> folder; shell writes stay inside it.
_LANE = re.compile(r"^[A-Za-z]:/(?:[A-Za-z0-9 _.\-]+/)*70\.HANDOFFS/[A-Za-z0-9_.\-]+/work/[A-Za-z0-9_.\-]+$")


class SessionLinkConfigRefused(ValueError):
    """An input needed for a truthful render or migration is absent or unsafe."""


def app_state_dir(environment=None) -> Path:
    """The Session Link state folder the application composes (desktop.py, launcher)."""
    env = os.environ if environment is None else environment
    root = env.get("ARCHHUB_TEST_STATE_DIR")
    if not root:
        if not env.get("LOCALAPPDATA"):
            raise SessionLinkConfigRefused("application state directory unavailable")
        root = str(Path(env["LOCALAPPDATA"]) / "ArchHub-Test")
    state = Path(root) / "session-link"
    if not state.is_absolute():
        raise SessionLinkConfigRefused("application state directory must be absolute")
    return state


def entry_script(install_root=None) -> Path:
    return Path(install_root or INSTALL_ROOT) / "nodelang" / "session_link" / "session-link.ps1"


def _alive(pid) -> bool:
    """Existence only; never signals. A reused pid reads as alive (fail closed)."""
    if type(pid) is not int or pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: the process exists
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def migrate_connections(source, target) -> dict:
    """Copy saved connection records once, ids unchanged. Never deletes or overwrites."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise SessionLinkConfigRefused("source and target are the same state directory")
    src = source / "connections"
    if not src.is_dir():
        raise SessionLinkConfigRefused("source has no connections folder: %s" % src)
    names = sorted(p.name for p in src.iterdir() if p.is_file() and _RECORD.match(p.name))
    live = []
    for name in names:
        if name.endswith(".runtime.json"):
            try:
                pid = json.loads((src / name).read_text(encoding="utf-8")).get("pid")
            except (OSError, ValueError):
                raise SessionLinkConfigRefused("unreadable runtime record: %s" % name) from None
            if _alive(pid):
                live.append(name[:16])
    if live:
        # A live bridge keeps writing to its own state; moving its records
        # would split one connection across two folders.
        raise SessionLinkConfigRefused("live connection owners in source: %s" % ",".join(live))
    dst = target / "connections"
    dst.mkdir(parents=True, exist_ok=True)
    receipt = {"source": str(source), "target": str(target), "copied": [], "identical": [],
               "conflicts": {}, "connections": sorted({n[:16] for n in names})}
    # One connection moves whole or not at all: a single differing file at the
    # destination skips every file of that connection, and it is reported.
    for connection in receipt["connections"]:
        group = [n for n in names if n[:16] == connection]
        differing = [n for n in group if (dst / n).exists()
                     and not filecmp.cmp(src / n, dst / n, shallow=False)]
        if differing:
            receipt["conflicts"][connection] = differing
            continue
        for name in group:
            if (dst / name).exists():
                receipt["identical"].append(name)
            else:
                shutil.copy2(src / name, dst / name)
                receipt["copied"].append(name)
    return receipt


def render_skill(install_root=None, state_dir=None) -> str:
    """The session-link skill for every agent; names the installed entry and the app's state."""
    text = SKILL_TEMPLATE.read_text(encoding="utf-8")
    if text.count("{{SESSION_LINK_ENTRY}}") == 0 or text.count("{{SESSION_LINK_ENTRY}}") != text.count("{{SESSION_LINK_STATE}}"):
        raise SessionLinkConfigRefused("skill template placeholders are incomplete")
    state = str(Path(state_dir) if state_dir else app_state_dir())
    return (text.replace("{{SESSION_LINK_ENTRY}}", str(entry_script(install_root)))
                .replace("{{SESSION_LINK_STATE}}", state))


def _plain(value, what):
    if type(value) is not str or not _PLAIN.match(value):
        raise SessionLinkConfigRefused("unsafe %s" % what)
    return value


def _mapping(values, key_rule, value_rule, what):
    if type(values) is not dict or not values or len(values) > 128:
        raise SessionLinkConfigRefused("%s required" % what)
    for key, value in values.items():
        items = value if type(value) is list else [value]
        if not key_rule.match(key) or not items or any(type(v) is not str or not value_rule.match(v) for v in items):
            raise SessionLinkConfigRefused("invalid %s entry" % what)
    return values


def _json(value):
    # Every value enters the module as a JSON literal (valid JavaScript). The
    # identity and _PLAIN checks run first; this is the second line, not the only one.
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def render_governance_loader(spec, *, install_root=None, state_dir=None) -> str:
    """The OpenCode governance loader for this install; same fields as the 2026-09-22 activation."""
    root = Path(install_root or INSTALL_ROOT)
    module = root / "nodelang" / "session_link" / "opencode-governance.mjs"
    node = root / "runtime" / "node.exe"
    if not module.is_file() or not node.is_file():
        raise SessionLinkConfigRefused("installed governance module or node runtime missing")
    state = Path(state_dir) if state_dir else app_state_dir()
    connections = _mapping(spec.get("connections"), _SESSION, _CONNECTION, "connections")
    expected = _mapping(spec.get("expectedSessions"), _SESSION, _ACTOR, "expectedSessions")
    works = _mapping(spec.get("selectedWorks"), _SESSION, _WORK, "selectedWorks")
    if set(works) - set(connections):
        raise SessionLinkConfigRefused("selected Work requires its Session Link connection")
    lanes = spec.get("laneFolders")
    if lanes is not None:
        lanes = _mapping(lanes, _SESSION, _LANE, "laneFolders")
        if set(lanes) - set(connections):
            raise SessionLinkConfigRefused("lane folder requires its Session Link connection")
    gate_command = _plain(spec.get("gateCommand"), "gateCommand")
    gate_args = spec.get("gateArgs")
    if type(gate_args) is not list or not gate_args:
        raise SessionLinkConfigRefused("gateArgs required")
    gate_args = [_plain(a, "gateArgs") for a in gate_args]
    revision = hashlib.sha256(module.read_bytes()).hexdigest()
    slash = lambda p: _plain(str(p).replace("\\", "/"), "path")
    fields = [
        ("sessionLink", {"node": slash(node), "stateDirectory": slash(state), "connections": connections}),
        ("expectedSessions", expected),
        ("selectedWorks", works),
        ("gateCommand", gate_command),
        ("gateArgs", gate_args),
    ] + ([("laneFolders", lanes)] if lanes is not None else [])
    return ("import {tool} from '@opencode-ai/plugin/tool';\n"
            "import {createOpenCodeGovernance} from " + _json(module.as_uri() + "?revision=" + revision) + ";\n"
            "export const ArchHubGovernance = createOpenCodeGovernance({\n"
            " workToolFactory:tool,\n"
            + "".join(" %s:%s,\n" % (key, _json(value)) for key, value in fields)
            + "});\n")


def spec_from_loader(text) -> dict:
    """Read the identities an existing loader carries (either quoting), so a re-render keeps them."""
    def one(pattern):
        found = re.findall(pattern, text)
        if len(found) != 1:
            raise SessionLinkConfigRefused("loader field not found exactly once: %s" % pattern)
        return found[0]
    def literal(raw):
        if "\\" in raw or ("'" in raw and '"' in raw):
            raise SessionLinkConfigRefused("unexpected characters in loader literal")
        try:
            return json.loads(raw.replace("'", '"'))
        except ValueError:
            raise SessionLinkConfigRefused("unreadable loader literal") from None
    key = lambda name: r"""["']?%s["']?:""" % name
    return {"connections": literal(one(key("connections") + r"(\{[^{}]*\})")),
            "expectedSessions": literal(one(key("expectedSessions") + r"(\{[^{}]*\})")),
            "selectedWorks": literal(one(key("selectedWorks") + r"(\{[^{}]*\})")),
            "gateCommand": literal(one(key("gateCommand") + r"""(['"][^'"]*['"])""")),
            "gateArgs": literal(one(key("gateArgs") + r"(\[[^\[\]]*\])")),
            **({"laneFolders": literal(one(key("laneFolders") + r"(\{[^{}]*\})"))}
               if re.search(key("laneFolders"), text) else {})}


def _require_single_link(target):
    """A hard-linked file cannot be replaced atomically: its twin would keep the old bytes."""
    try:
        links = os.stat(target).st_nlink
    except FileNotFoundError:
        return
    if links > 1:
        raise SessionLinkConfigRefused(
            "this settings file is shared with another file (hard link); left unchanged. "
            "Make it a normal file, then try again")


def write_with_backup(target, text, backup_dir, *, expected_digest=None, protect_backup=None) -> dict:
    """Back up prior bytes, check drift, atomically replace, and verify readback."""
    import tempfile
    from .client_mcp_installation import _require_plain
    target, backup_dir = Path(target), Path(backup_dir)
    _require_plain(target, "file", may_be_absent=True)
    _require_single_link(target)
    _require_plain(backup_dir, "directory")
    before = target.read_bytes() if target.exists() else None
    observed = hashlib.sha256(before).hexdigest() if before is not None else "absent"
    if expected_digest is not None and observed != expected_digest:
        raise SessionLinkConfigRefused("client settings changed since preview")
    if before is not None and b"\r\n" in before:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    data = text.encode("utf-8")
    if before == data:
        return {"target": str(target), "changed": False, "backup": None}
    backup = None
    if before is not None:
        tag = hashlib.sha256(str(target).encode()).hexdigest()[:12]
        payload = protect_backup(before) if protect_backup else before
        with tempfile.NamedTemporaryFile(prefix=target.name + "." + tag + ".",
                                         suffix=".dpapi" if protect_backup else ".bak",
                                         dir=backup_dir, delete=False) as saved:
            backup = Path(saved.name)
            saved.write(payload)
            saved.flush()
            os.fsync(saved.fileno())
    temporary = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile(prefix="." + target.name + ".", suffix=".tmp",
                                         dir=target.parent, delete=False) as staged:
            temporary = Path(staged.name)
            staged.write(data)
            staged.flush()
            os.fsync(staged.fileno())
        _require_plain(target, "file", may_be_absent=True)
        _require_single_link(target)
        latest = target.read_bytes() if target.exists() else None
        if latest != before:
            raise SessionLinkConfigRefused("client settings changed during preparation")
        os.replace(temporary, target)
        temporary = None
        replaced = True
        if target.read_bytes() != data:
            raise SessionLinkConfigRefused("client settings readback changed; reconcile before retrying")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if not replaced and backup is not None:
            # Nothing was replaced: an orphan backup would only confuse the next restore.
            backup.unlink(missing_ok=True)
    return {"target": str(target), "changed": True,
            "backup": str(backup) if backup else None,
            "sha256": hashlib.sha256(data).hexdigest()}



# Managed tool hooks only. Lifecycle remains bound to each native launch.
_HOOK_CLIENTS = {
    "claude-code": (".claude/settings.json", "claude", "PreToolUse", "PostToolUse", 30),
    "codex": (".codex/hooks.json", "codex", "PreToolUse", "PostToolUse", 30),
    "gemini-cli": (".gemini/settings.json", "gemini", "BeforeTool", "AfterTool", 30000),
}

# ArchHub's own product hook: the end-of-turn check, run by the INSTALLED copy with
# its own Python. The scope gate above is workspace governance and is never installed.
_STOP_HOOKS = {
    "claude-code": ("Stop", "claude-code", 30),
    "codex": ("Stop", "codex", 30),
    "gemini-cli": ("AfterAgent", "gemini", 30000),
}
_SHELL_META = ["\r", "\n", "&", "|", "<", ">", "^", "%", "$", "`", ";", "\"", "(", ")"]


def installed_stop_hook(install_root):
    """The installed interpreter and stop script; refuses a source checkout."""
    from .client_mcp_installation import _require_plain
    root = Path(install_root)
    if not (root / "BUILD_METADATA.json").is_file():
        raise SessionLinkConfigRefused("assistant hooks are installed only from the installed ArchHub")
    python = root / ".venv" / "Scripts" / "python.exe"
    script = root / "nodelang" / "native_stop_hook.py"
    for path in (python, script):
        if any(character in str(path) for character in _SHELL_META):
            raise SessionLinkConfigRefused("hook path contains shell metacharacters")
        _require_plain(path, "file")
    return python, script


def _render_hook_command(vendor, python, script, flag):
    """Quoted forward-slash paths survive Claude Code's Git Bash on Windows. Codex runs
    hook commands through PowerShell, where a leading quoted string is an expression,
    not a command: the call operator makes any path, spaces included, run."""
    quote = lambda value: '"' + str(value).replace("\\", "/") + '"'
    command = quote(python) + " " + quote(script) + " --vendor " + flag
    return "& " + command if vendor == "codex" else command


def render_stop_hook(vendor, *, install_root):
    """One end-of-turn entry for this client, pointing at the installed copy."""
    if vendor not in _STOP_HOOKS:
        raise SessionLinkConfigRefused("unsupported hook client")
    python, script = installed_stop_hook(install_root)
    event, flag, timeout = _STOP_HOOKS[vendor]
    hook = {"type": "command", "command": _render_hook_command(vendor, python, script, flag),
            "timeout": timeout}
    if vendor == "gemini-cli":
        hook["name"] = "archhub-end-of-turn-check"
    return {event: [{"hooks": [hook]}]}


def settings_target(vendor, *, home, codex_home=None):
    """The client's hook settings file. Codex honours CODEX_HOME (as _codex_config does)."""
    if vendor == "codex" and codex_home is not None:
        return Path(codex_home) / "hooks.json"
    return Path(home) / _HOOK_CLIENTS[vendor][0]


def _stop_hook_role(hook, vendor, script):
    """'ours' for this install's stop script; for another ArchHub stop script,
    'other_copy' when its file exists and 'stale' when it does not."""
    parts = _hook_command_parts(hook)
    if parts is None or parts[2] != ("--vendor", _STOP_HOOKS[vendor][1]):
        return None
    if Path(parts[1]).name.casefold() != "native_stop_hook.py":
        return None
    if os.path.normcase(os.path.normpath(parts[1])) == os.path.normcase(os.path.normpath(str(script))):
        return "ours"
    return "other_copy" if Path(parts[1]).is_file() else "stale"


def merge_stop_hook(existing, managed, *, vendor, install_root, migrate=False):
    """Add the installed stop entry once; keep every other hook, group and matcher.

    Returns (settings, binding, observed): observed is every role the file held
    before (ours, other_copy, stale); binding is the one that decides, and any
    foreign entry wins over ours: other_copy, then stale, then ours, else absent.
    Another copy's entry (live or stale) is never overwritten silently, even beside
    ours: without migrate nothing changes; a reviewed migrate leaves exactly one."""
    import copy
    if type(existing) is not dict or vendor not in _STOP_HOOKS:
        raise SessionLinkConfigRefused("invalid client settings")
    _, script = installed_stop_hook(install_root)
    result = copy.deepcopy(existing)
    events = result.setdefault("hooks", {})
    if type(events) is not dict:
        raise SessionLinkConfigRefused("client hooks are not an object")
    binding, observed = "absent", set()
    for event, additions in managed.items():
        groups = events.get(event, [])
        if type(groups) is not list:
            raise SessionLinkConfigRefused("client hook event is not an array")
        desired = additions[0]["hooks"][0]
        roles = []
        for group in groups:
            if type(group) is not dict or type(group.get("hooks")) is not list:
                raise SessionLinkConfigRefused("unrecognized hook group")
            roles += [_stop_hook_role(hook, vendor, script) for hook in group["hooks"]]
        observed.update(role for role in roles if role)
        for role in ("other_copy", "stale", "ours"):
            if role in observed:
                binding = role
                break
        if binding in ("other_copy", "stale") and not migrate:
            events[event] = groups
            continue
        placed = False
        eligible = ("ours", "other_copy", "stale") if migrate else ("ours",)
        kept = []
        for group in groups:
            hooks = []
            for hook in group["hooks"]:
                role = _stop_hook_role(hook, vendor, script)
                if role in eligible:
                    if placed:
                        continue  # exactly one end-of-turn check remains
                    placed = True
                    if (role != "ours" or _hook_command_identity(hook) != _hook_command_identity(desired)
                            or _runner_broken(hook, vendor)):
                        # Our own script under another spelling, or a reviewed migration.
                        hook = {**hook, "command": desired["command"]}
                hooks.append(hook)
            if group["hooks"] and not hooks:
                continue  # a group left empty by the migration goes with it
            group["hooks"] = hooks
            kept.append(group)
        groups = kept
        if not placed:
            groups.extend(copy.deepcopy(additions))
        events[event] = groups
    return result, binding, sorted(observed)


def _restore_bytes(target, data, *, expected_digest):
    """Put back the exact pre-install bytes (or drop a file ArchHub created), atomically."""
    import tempfile
    from .client_mcp_installation import _require_plain
    _require_plain(target, "file")
    _require_single_link(target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest:
        raise SessionLinkConfigRefused("client settings changed since ArchHub wrote them")
    if data is None:
        target.unlink()
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix="." + target.name + ".", suffix=".tmp",
                                         dir=target.parent, delete=False) as staged:
            temporary = Path(staged.name)
            staged.write(data)
            staged.flush()
            os.fsync(staged.fileno())
        _require_single_link(target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest:
            raise SessionLinkConfigRefused("client settings changed since ArchHub wrote them")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def remove_stop_hook(vendor, *, home, install_root, receipt=None, backup_dir, codex_home=None):
    """Uninstall: take out exactly the end-of-turn entries of THIS install (matched by the
    installed script path) and nothing else. Untouched since install: the exact prior
    bytes come back from the protected backup. Changed since: only our entries go."""
    from .client_mcp_installation import _require_plain
    if vendor not in _STOP_HOOKS:
        raise SessionLinkConfigRefused("unsupported hook client")
    target = settings_target(vendor, home=home, codex_home=codex_home)
    _require_plain(target, "file", may_be_absent=True)
    if not target.exists():
        return {"vendor": vendor, "changed": False, "method": "none"}
    current = target.read_bytes()
    digest = hashlib.sha256(current).hexdigest()
    if (type(receipt) is dict and receipt.get("target") == str(target)
            and receipt.get("after") == digest):
        before = receipt.get("before")
        if before == "absent":
            _restore_bytes(target, None, expected_digest=digest)
            return {"vendor": vendor, "changed": True, "method": "restored"}
        if type(receipt.get("backup")) is str:
            from .cell_secret_keys import unprotect_current_user_data
            backup = Path(receipt["backup"])
            _require_plain(backup, "file")
            data = unprotect_current_user_data(backup.read_bytes(),
                                               purpose="archhub.client-hook-backup/v1")
            if hashlib.sha256(data).hexdigest() == before:
                _restore_bytes(target, data, expected_digest=digest)
                return {"vendor": vendor, "changed": True, "method": "restored"}
    _, script = installed_stop_hook(install_root)
    try:
        existing = json.loads(current.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise SessionLinkConfigRefused("client settings are unreadable") from None
    events = existing.get("hooks") if type(existing) is dict else None
    event = _STOP_HOOKS[vendor][0]
    groups = events.get(event) if type(events) is dict else None
    if type(groups) is not list:
        return {"vendor": vendor, "changed": False, "method": "none"}
    import copy
    result = copy.deepcopy(existing)
    kept = []
    for group in groups:
        if type(group) is not dict or type(group.get("hooks")) is not list:
            kept.append(group)
            continue
        hooks = [h for h in group["hooks"] if _stop_hook_role(h, vendor, script) != "ours"]
        if hooks or len(hooks) == len(group["hooks"]):
            kept.append({**group, "hooks": hooks})
    if kept == groups:
        return {"vendor": vendor, "changed": False, "method": "none"}
    if kept:
        result["hooks"][event] = kept
    else:
        result["hooks"].pop(event)
    indent = 2
    found = re.search(rb"\n([ \t]+)\S", current)
    if found and found.group(1).startswith(b"\t"):
        indent = "\t"
    elif found and len(found.group(1)) == 4:
        indent = 4
    text = json.dumps(result, ensure_ascii=False, indent=indent) + "\n"
    if current.startswith(b"\xef\xbb\xbf"):
        text = "\ufeff" + text
    from .cell_secret_keys import protect_current_user_data
    write_with_backup(target, text, backup_dir, expected_digest=digest,
                      protect_backup=lambda data: protect_current_user_data(
                          data, purpose="archhub.client-hook-backup/v1"))
    return {"vendor": vendor, "changed": True, "method": "taken_out"}


def hook_event_states(vendor, *, home, install_root, codex_home=None):
    """Per event, what this client's settings file says now; reads only."""
    from .client_mcp_installation import _require_plain
    if vendor not in _STOP_HOOKS:
        raise SessionLinkConfigRefused("unsupported hook client")
    target = settings_target(vendor, home=home, codex_home=codex_home)
    _require_plain(target, "file", may_be_absent=True)
    config = {}
    if target.exists():
        if target.stat().st_size > 4 * 1024 * 1024:
            raise SessionLinkConfigRefused("client settings exceed the supported size")
        try:
            config = json.loads(target.read_text(encoding="utf-8-sig"))
        except (UnicodeError, ValueError):
            raise SessionLinkConfigRefused("client settings are unreadable") from None
    events = config.get("hooks", {}) if type(config) is dict else None
    if type(events) is not dict:
        raise SessionLinkConfigRefused("client hook configuration is invalid")
    _, script = installed_stop_hook(install_root)
    event = _STOP_HOOKS[vendor][0]
    groups = events.get(event, [])
    roles = set()
    for group in groups if type(groups) is list else []:
        hooks = group.get("hooks") if type(group) is dict else None
        for hook in hooks if type(hooks) is list else []:
            role = _stop_hook_role(hook, vendor, script)
            if role:
                roles.add(role)
    # Every observed role is kept; "on" never masks a foreign or stale entry beside it.
    foreign = "other_copy" if "other_copy" in roles else "stale" if "stale" in roles else None
    if foreign and "ours" in roles:
        state = "on_with_" + foreign
    else:
        state = foreign or ("on" if "ours" in roles else "off")
    return [{"event": event, "purpose": "end_of_turn_check", "state": state, "roles": sorted(roles)}]


def render_client_hooks(vendor, *, python_executable, gate_script, install_root):
    """Render only the admitted adapter's tool events; no lifecycle or trust edits."""
    import subprocess
    from .client_mcp_installation import _require_plain
    if vendor not in _HOOK_CLIENTS:
        raise SessionLinkConfigRefused("unsupported hook client")
    python, gate = Path(python_executable), Path(gate_script)
    for path in (python, gate):
        if any(character in str(path) for character in ["\r","\n","&","|","<",">","^","%","$","`",";","\"","(",")"]):
            raise SessionLinkConfigRefused("hook path contains shell metacharacters")
        _require_plain(path, "file")
    if python.name.casefold() not in ("python.exe", "pythonw.exe", "python", "python3"):
        raise SessionLinkConfigRefused("hook interpreter is not an admitted Python executable")
    if gate.name != "agent_scope_gate.py":
        raise SessionLinkConfigRefused("hook adapter is not the existing scope adapter")
    _, flag, before, after, timeout = _HOOK_CLIENTS[vendor]
    command = _render_hook_command(vendor, python, gate, flag)
    result = {}
    for event, label in ((before, "archhub-scope-gate"), (after, "archhub-write-receipt")):
        hook = {"type": "command", "command": command, "timeout": timeout}
        group = {"hooks": [hook]}
        if vendor == "gemini-cli":
            hook["name"] = label
            group["matcher"] = ".*"
        result[event] = [group]
    return result


def _hook_command_parts(hook):
    """Read a simple command without discarding the user's original path spelling."""
    if not isinstance(hook, dict) or hook.get("type") != "command":
        return None
    command = hook.get("command")
    if isinstance(command, str):
        # One leading PowerShell call operator (the Codex spelling) names the same command.
        command = re.sub(r"^\s*&\s+", "", command, count=1)
    if not isinstance(command, str) or any(c in command for c in "\n\r&|><" + chr(96)):
        return None
    pattern = r'''"[^"]*"|'[^']*'|[^\s"']+'''
    found = list(re.finditer(pattern, command))
    end, tokens = 0, []
    for match in found:
        if command[end:match.start()].strip():
            return None
        token = match.group()
        tokens.append(token[1:-1] if token[:1] in ('"', "'") else token)
        end = match.end()
    if command[end:].strip() or len(tokens) not in (2, 4):
        return None
    python, script = Path(tokens[0]), Path(tokens[1])
    if not python.is_absolute() or not script.is_absolute():
        return None
    if python.name.casefold() not in ("python.exe", "pythonw.exe", "python", "python3"):
        return None
    return tokens[0], tokens[1], tuple(tokens[2:])


def _hook_command_identity(hook):
    parts = _hook_command_parts(hook)
    if parts is None:
        return None
    python, script, args = parts
    return (os.path.normcase(os.path.normpath(python)),
            os.path.normcase(os.path.normpath(script)), args)


def _claude_bash_broken(hook, vendor):
    """Claude Code runs hooks through Git Bash on Windows, where an unquoted backslash
    path is an escape sequence (rc 127); such a command is never a working equivalent."""
    if vendor != "claude-code" or not isinstance(hook, dict):
        return False
    command = hook.get("command")
    if not isinstance(command, str):
        return False
    tokens = re.findall(r'''"[^"]*"|'[^']*'|[^\s"']+''', command)
    return tokens[:1] == ["&"] or any(token[:1] not in ('"', "'") and "\\" in token for token in tokens)


def _codex_powershell_broken(hook, vendor):
    """Codex runs hooks through PowerShell, where a command that starts with a quoted
    path is a ParserError; such a command is never a working equivalent."""
    if vendor != "codex" or not isinstance(hook, dict):
        return False
    command = hook.get("command")
    return isinstance(command, str) and command.lstrip()[:1] in ('"', "'")


def _runner_broken(hook, vendor):
    return _claude_bash_broken(hook, vendor) or _codex_powershell_broken(hook, vendor)


def merge_client_hooks(existing, managed, *, vendor, known_owned_commands):
    """Leave equivalent commands byte-identical; keep existing groups and matchers."""
    import copy
    if type(existing) is not dict or vendor not in _HOOK_CLIENTS:
        raise SessionLinkConfigRefused("invalid client settings")
    result = copy.deepcopy(existing)
    events = result.setdefault("hooks", {})
    if type(events) is not dict:
        raise SessionLinkConfigRefused("client hooks are not an object")
    owned = set(known_owned_commands)
    for event, additions in managed.items():
        groups = events.get(event, [])
        if type(groups) is not list:
            raise SessionLinkConfigRefused("client hook event is not an array")
        desired = additions[0]["hooks"][0]
        identity = _hook_command_identity(desired)
        for group in groups:
            if type(group) is not dict or type(group.get("hooks")) is not list:
                raise SessionLinkConfigRefused("unrecognized hook group")
        equivalent = any(_hook_command_identity(h) == identity and not _runner_broken(h, vendor)
                         for g in groups for h in g["hooks"])
        replaced = False
        for group in groups:
            hooks = []
            for hook in group["hooks"]:
                current = _hook_command_identity(hook)
                if current == identity and _runner_broken(hook, vendor):
                    # Same adapter, spelling broken under the client's shell: rewrite the command only.
                    hooks.append({**hook, "command": desired["command"]})
                    replaced = True
                elif current == identity:
                    hooks.append(hook)
                elif current in owned:
                    if equivalent:
                        # Retire only the duplicate; preserve the surviving command.
                        if Path(current[1]).name.casefold() != "pretooluse_validate.py":
                            hooks.append(hook)
                    else:
                        # Preserve matcher, group, timeout and other user metadata.
                        hooks.append({**hook, "command": desired["command"]})
                        replaced = True
                else:
                    hooks.append(hook)
            group["hooks"] = hooks
        if not equivalent and not replaced:
            groups.extend(copy.deepcopy(additions))
        events[event] = groups
    return result


def plan_client_hook_install(vendor, *, home, install_root, python_executable=None, gate_script=None,
                             stop_root=None, migrate=False, codex_home=None):
    """Private plan; callers expose only hook deltas and digest, never raw settings."""
    from .client_mcp_installation import _require_plain
    if vendor not in _HOOK_CLIENTS:
        raise SessionLinkConfigRefused("unsupported hook client")
    target = settings_target(vendor, home=home, codex_home=codex_home)
    _require_plain(target, "file", may_be_absent=True)
    if not target.parent.is_dir():
        raise SessionLinkConfigRefused("client configuration directory is absent")
    before = target.read_bytes() if target.exists() else None
    if before is not None and len(before) > 4 * 1024 * 1024:
        raise SessionLinkConfigRefused("client settings exceed the supported size")
    try:
        existing = json.loads(before.decode("utf-8-sig")) if before is not None else {}
    except (ValueError, UnicodeError):
        raise SessionLinkConfigRefused("client settings are unreadable") from None
    if type(existing) is not dict:
        raise SessionLinkConfigRefused("invalid client settings")
    managed, merged = {}, existing
    gate = Path(gate_script) if gate_script is not None else None
    interpreter = Path(python_executable) if python_executable is not None else None
    if gate is not None:
        # An existing workspace gate only (never installed here): repair its spelling in place.
        managed = render_client_hooks(vendor, python_executable=python_executable,
                                      gate_script=gate_script, install_root=install_root)
        # Only the exact configured adapter and its sibling legacy validator.
        # A different interpreter/binding is not silently removed.
        owned = []
        for executable in (interpreter, interpreter.with_name("pythonw.exe")):
            owned.append((os.path.normcase(os.path.normpath(str(executable))), os.path.normcase(os.path.normpath(str(gate))),
                          ("--vendor", _HOOK_CLIENTS[vendor][1])))
            if vendor == "codex":
                owned.append((os.path.normcase(os.path.normpath(str(executable))),
                              os.path.normcase(os.path.normpath(str(gate.with_name("pretooluse_validate.py")))), ()))
        merged = merge_client_hooks(merged, managed, vendor=vendor, known_owned_commands=owned)
    stop_binding, stop_roles = None, []
    if stop_root is not None:
        stop = render_stop_hook(vendor, install_root=stop_root)
        merged, stop_binding, stop_roles = merge_stop_hook(merged, stop, vendor=vendor,
                                                           install_root=stop_root, migrate=migrate)
        managed = {**managed, **stop}
    changed = existing != merged
    indent = 2  # Keep the file's own indent unit: 2 or 4 spaces, or a tab.
    found = re.search(rb"\n([ \t]+)\S", before) if before is not None else None
    if found and found.group(1).startswith(b"\t"):
        indent = "\t"
    elif found and len(found.group(1)) == 4:
        indent = 4
    text = json.dumps(merged, ensure_ascii=False, indent=indent) + "\n"
    if before is not None and b"\r\n" in before:
        text = text.replace("\n", "\r\n")
    if before is not None and before.startswith(b"\xef\xbb\xbf"):
        text = "\ufeff" + text
    after = text.encode("utf-8") if changed else before
    def digest(data):
        return hashlib.sha256(data).hexdigest() if data is not None else "absent"
    before_digest, after_digest = digest(before), digest(after)
    plan_digest = hashlib.sha256(json.dumps(
        [vendor, str(target), before_digest, after_digest, str(gate), str(interpreter),
         str(stop_root), bool(migrate)],
        ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    return {"vendor": vendor, "target": str(target), "before_digest": before_digest,
            "after_digest": after_digest, "plan_digest": plan_digest, "changed": changed,
            "text": text, "managed_events": list(managed), "stop_binding": stop_binding,
            "stop_roles": stop_roles,
            "migration": bool(migrate) and stop_binding in ("other_copy", "stale"),
            "activation": "Settings are saved separately from checking that the assistant is using them."}


def apply_client_hook_install(plan, *, expected_digest, backup_dir):
    """Apply only a server-recomputed private plan, never a browser-supplied plan."""
    if not isinstance(plan, dict) or plan.get("plan_digest") != expected_digest:
        raise SessionLinkConfigRefused("hook plan changed; review the current preview")
    target = Path(plan["target"])
    if not plan["changed"]:
        current = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else "absent"
        if current != plan["before_digest"]:
            raise SessionLinkConfigRefused("client settings changed since preview")
        return {"changed": False, "activation_pending": True}
    from .cell_secret_keys import protect_current_user_data
    result = write_with_backup(
        target, plan["text"], backup_dir, expected_digest=plan["before_digest"],
        protect_backup=lambda data: protect_current_user_data(
            data, purpose="archhub.client-hook-backup/v1"))
    return {**result, "activation_pending": True}



def observed_client_hook_binding(vendor, *, home, optional=False, codex_home=None):
    """Reuse this client's exact existing adapter; absence is not installation proof.

    optional=True answers None when the client has no workspace gate at all."""
    from .runtime_hook_observer import VENDORS, GATES
    from .client_mcp_installation import _require_plain
    if vendor not in _HOOK_CLIENTS or vendor not in VENDORS:
        raise SessionLinkConfigRefused("unsupported hook client")
    spec = VENDORS[vendor]
    path = settings_target(vendor, home=home, codex_home=codex_home)
    if optional and not path.exists():
        return None
    _require_plain(path, "file")
    if path.stat().st_size > 4 * 1024 * 1024:
        raise SessionLinkConfigRefused("client settings exceed the supported size")
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError):
        raise SessionLinkConfigRefused("client settings are unreadable") from None
    if not isinstance(config, dict) or config.get("disableAllHooks") is True:
        raise SessionLinkConfigRefused("hooks are disabled or configuration is invalid")
    events = config.get("hooks", {})
    if not isinstance(events, dict):
        raise SessionLinkConfigRefused("client hook configuration is invalid")
    bindings = {}
    for event in (*spec["pre"], *spec["post"]):
        groups = events.get(event, [])
        if not isinstance(groups, list):
            raise SessionLinkConfigRefused("client hook event is invalid")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise SessionLinkConfigRefused("client hook group is invalid")
            for hook in group["hooks"]:
                identity = _hook_command_identity(hook)
                if identity is None:
                    continue
                executable, script, args = _hook_command_parts(hook)
                normalized = script.replace("\\", "/").casefold()
                known = any(normalized.endswith(marker.casefold()) for marker in GATES)
                if known and Path(script).name.casefold() == "agent_scope_gate.py" and args == ("--vendor", _HOOK_CLIENTS[vendor][1]):
                    _require_plain(Path(executable), "file")
                    _require_plain(Path(script), "file")
                    bindings.setdefault(identity[:2], (executable, script))
    if optional and not bindings:
        return None
    if len(bindings) != 1:
        raise SessionLinkConfigRefused("one existing admitted hook binding is required; installed adapter unavailable")
    return next(iter(bindings.values()))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nodelang.session_link_config")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("state-dir")
    sub.add_parser("entry")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--from", dest="source", required=True)
    migrate.add_argument("--to", dest="target")
    for name in ("skill", "governance"):
        render = sub.add_parser(name)
        render.add_argument("--install-root")
        render.add_argument("--write")
        render.add_argument("--backup-dir")
        render.add_argument("--state-dir")
        if name == "governance":
            render.add_argument("--from-loader", required=True)
    args = parser.parse_args(argv)
    from .client_mcp_installation import RegistrationRefused
    try:
        if args.command == "state-dir":
            print(app_state_dir())
        elif args.command == "entry":
            print(entry_script())
        elif args.command == "migrate":
            print(json.dumps(migrate_connections(args.source, args.target or app_state_dir()), indent=2))
        else:
            if args.command == "skill":
                text = render_skill(args.install_root, args.state_dir)
            else:
                spec = spec_from_loader(Path(args.from_loader).read_text(encoding="utf-8"))
                text = render_governance_loader(spec, install_root=args.install_root, state_dir=args.state_dir)
            if args.write:
                if not args.backup_dir:
                    raise SessionLinkConfigRefused("--write requires --backup-dir")
                print(json.dumps(write_with_backup(args.write, text, args.backup_dir), indent=2))
            else:
                sys.stdout.write(text)
    except (SessionLinkConfigRefused, RegistrationRefused) as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
