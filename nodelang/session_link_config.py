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


def write_with_backup(target, text, backup_dir) -> dict:
    """Replace one agent file; the prior bytes go to backup_dir first. Keeps CRLF if the file had it."""
    target, backup_dir = Path(target), Path(backup_dir)
    if not backup_dir.is_dir():
        raise SessionLinkConfigRefused("backup directory must exist: %s" % backup_dir)
    data = text.encode("utf-8")
    backup = None
    if target.exists():
        before = target.read_bytes()
        if b"\r\n" in before:
            data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        if before == data:
            return {"target": str(target), "changed": False, "backup": None}
        # Same-named files of different agents share one backup folder.
        tag = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()[:8]
        backup = backup_dir / (target.name + ".bak-" + time.strftime("%Y%m%dT%H%M%S") + "-" + tag)
        if backup.exists():
            raise SessionLinkConfigRefused("backup already exists: %s" % backup)
        shutil.copy2(target, backup)
    target.write_bytes(data)
    return {"target": str(target), "changed": True, "backup": str(backup) if backup else None,
            "sha256": hashlib.sha256(data).hexdigest()}


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
    except SessionLinkConfigRefused as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
