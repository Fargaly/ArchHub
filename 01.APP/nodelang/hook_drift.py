"""Hook-drift check: hash every hook every agent will run; flag change since approval.

Covers Claude Code (settings.json, settings.local.json, every plugin's hooks.json and
plugin.json hooks), Codex (hooks.json), Gemini CLI (settings.json), Antigravity
(config/hooks.json), Cursor (hooks.json) and OpenCode (plugin files). Each hook is
hashed with its event, matcher and handler, plus the bytes of any script its command
names, so an edited script is drift too. A new SessionStart hook is the Mini
Shai-Hulud pattern and is marked ``risk: high``. Reads only; ``approve`` records the
current inventory as the approved state.

    state     clean | drift | no-baseline
    hooks     count inventoried
    added / removed / changed   [{id, source, event, matcher, command, risk}]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

_JSON_SOURCES = (".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json",
                 ".gemini/settings.json", ".gemini/config/hooks.json", ".cursor/hooks.json")
_PLUGIN_GLOBS = (".claude/plugins/**/hooks/hooks.json", ".claude/plugins/**/.claude-plugin/plugin.json",
                 ".claude/plugins/**/plugin.json")
_OPENCODE = (".config/opencode/plugin", ".config/opencode/plugins")
_HIGH = {"SessionStart", "session_start", "UserPromptSubmit", "Setup", "PreCompact"}
_SCRIPT = re.compile(r"""["']?([A-Za-z]:[\\/][^"'\s]+?\.(?:py|js|mjs|cjs|ts|ps1|sh|cmd|bat))["']?""")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scripts(command: str) -> dict:
    out = {}
    for path in _SCRIPT.findall(command or ""):
        p = Path(path)
        try:
            out[str(p)] = _sha(p.read_bytes()) if p.is_file() else "absent"
        except OSError:
            out[str(p)] = "unreadable"
    return out


def _events(data):
    """The hook-event mapping in any of the agents' shapes."""
    if not isinstance(data, dict):
        return {}
    for key in ("hooks", "archhub-governance"):
        if isinstance(data.get(key), dict):
            return data[key]
    return {}


def _hooks_in(source: str, data) -> list[dict]:
    found = []
    for event, groups in _events(data).items():
        groups = groups if isinstance(groups, list) else [groups]
        for group in groups:
            matcher = group.get("matcher") if isinstance(group, dict) else None
            hooks = group["hooks"] if isinstance(group, dict) and isinstance(group.get("hooks"), list) else [group]
            for hook in hooks:
                command = hook.get("command") if isinstance(hook, dict) else str(hook)
                command = " ".join(command) if isinstance(command, list) else str(command or "")
                identity = {"source": source, "event": event, "matcher": matcher, "hook": hook,
                            "scripts": _scripts(command)}
                canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
                found.append({"id": "%s|%s|%s|%s" % (source, event, matcher, command), "source": source,
                              "event": event, "matcher": matcher, "command": command,
                              "sha256": _sha(canonical.encode("utf-8"))})
    return found


def inventory(home, *, codex_home=None) -> list[dict]:
    home = Path(home)
    files = [home / rel for rel in _JSON_SOURCES]
    if codex_home:
        files.append(Path(codex_home) / "hooks.json")
    for pattern in _PLUGIN_GLOBS:
        files += sorted(home.glob(pattern))
    hooks, seen = [], set()
    for path in files:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, UnicodeError):
            hooks.append({"id": "%s|unreadable" % path, "source": str(path), "event": "?", "matcher": None,
                          "command": "", "sha256": "unreadable"})
            continue
        hooks += _hooks_in(str(path), data)
    for rel in _OPENCODE:
        folder = home / rel
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix in (".js", ".mjs", ".ts", ".cjs"):
                    hooks.append({"id": "%s|plugin" % path, "source": str(path), "event": "plugin",
                                  "matcher": None, "command": path.name, "sha256": _sha(path.read_bytes())})
    return hooks


def _risk(hook):
    return "high" if hook["event"] in _HIGH else "normal"


def check(home, state_file, *, codex_home=None) -> dict:
    current = inventory(home, codex_home=codex_home)
    try:
        approved = json.loads(Path(state_file).read_text(encoding="utf-8"))["hooks"]
    except (OSError, ValueError, KeyError):
        return {"state": "no-baseline", "hooks": len(current), "added": [], "removed": [], "changed": []}
    old = {h["id"]: h for h in approved}
    new = {h["id"]: h for h in current}
    view = lambda h: {k: h[k] for k in ("id", "source", "event", "matcher", "command")} | {"risk": _risk(h)}
    added = [view(h) for i, h in new.items() if i not in old]
    removed = [view(h) for i, h in old.items() if i not in new]
    changed = [view(h) for i, h in new.items() if i in old and old[i]["sha256"] != h["sha256"]]
    drift = bool(added or removed or changed)
    return {"state": "drift" if drift else "clean", "hooks": len(current),
            "added": added, "removed": removed, "changed": changed}


def approve(home, state_file, *, codex_home=None) -> dict:
    hooks = inventory(home, codex_home=codex_home)
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    Path(state_file).write_text(json.dumps({"hooks": hooks}, indent=1), encoding="utf-8")
    return {"state": "approved", "hooks": len(hooks)}


def default_state_file(environment=None) -> Path:
    environment = os.environ if environment is None else environment
    base = environment.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ArchHub" / "runtime-context" / "hook-drift" / "approved.json"


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "approve", "inventory"))
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME"))
    parser.add_argument("--state", default=None)
    args = parser.parse_args(argv)
    state = args.state or default_state_file()
    if args.command == "inventory":
        result = {"hooks": inventory(args.home, codex_home=args.codex_home)}
    elif args.command == "approve":
        result = approve(args.home, state, codex_home=args.codex_home)
    else:
        result = check(args.home, state, codex_home=args.codex_home)
    sys.stdout.write(json.dumps(result, indent=1) + "\n")
    return 1 if result.get("state") == "drift" else 0


if __name__ == "__main__":
    raise SystemExit(main())
