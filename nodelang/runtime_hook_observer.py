"""Native runtime-compliance observer: does this client run the landed gates?

Replaces the retired personal Brain's ``personal_brain.hook_coverage``, which
counted a client as compliant only while its config still named the Brain MCP
server and the brainwrap hooks. Here a client is compliant when its own config
binds the governance hooks that actually enforce work in this workspace:

* scope-gate      -- its pre-tool event runs ``00.GOVERNANCE/hooks/agent_scope_gate.py``
                     (or the vendor gate) for that vendor, and the hook's tool
                     matcher covers every file-writing tool of the vendor;
* required-hooks  -- scope-gate, plus the post-tool settle hook (same coverage)
                     where the vendor has a post-tool event;
* brain-connected -- the session-start hook runs the application's
                     ``native_start_hook.py`` (the application's own Brain), where
                     that hook supports the vendor;
* workshop-authority -- the completion hook runs ``native_stop_hook.py`` where
                     that hook supports the vendor;
* runtime-detected / schema-valid -- the client's config exists and parses.

``disableAllHooks`` turns every hook check off. A gate that does not see the
vendor's shell tool is reported as partial coverage (shell writes are not
gated) in the notes. Codex runs a hook only once it is trusted: the observer
computes the hook's identity hash the way Codex does (codex-rs hooks
``hook_hash``: canonical JSON of event, matcher and normalised handler) and a
bound Codex hook whose recorded ``trusted_hash`` is missing or different is
reported "needs approval in Codex /hooks" in the notes.
The Brain MCP entry and brainwrap are never required and never enough. A vendor
with no hook mechanism is reported ``not-enforceable``: it does not pass.
The six check names are the released court's names (universal_application).
This module reads files only; it grants nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any, Optional

CHECKS = (
    "runtime-detected",
    "required-hooks",
    "schema-valid",
    "brain-connected",
    "scope-gate",
    "workshop-authority",
)
GATES = ("00.GOVERNANCE/hooks/agent_scope_gate.py", "00.GOVERNANCE/hooks/pretooluse_validate.py")
OPENCODE_GATE = "00.GOVERNANCE/hooks/opencode_native_gate.py"
START_HOOK = "native_start_hook.py"
STOP_HOOK = "native_stop_hook.py"

# Per vendor: config file (under the user's home), the key holding its hook
# events, the pre/post tool events, the vendor flag the gate must carry, the
# file-writing tools the gate must see, the shell tools (partial when unseen),
# and the start/stop events where native_start_hook / native_stop_hook support
# the vendor (native_start_hook: claude, codex; native_stop_hook: claude).
VENDORS: dict[str, dict[str, Any]] = {
    "claude-code": {"config": ".claude/settings.json", "root": "hooks", "pre": ("PreToolUse",),
                    "post": ("PostToolUse",), "flag": "--vendor claude",
                    "write_tools": ("Write", "Edit", "MultiEdit", "NotebookEdit"), "shell_tools": ("Bash",),
                    "start": ("SessionStart",), "stop": ("Stop",)},
    "codex": {"config": ".codex/hooks.json", "root": "hooks", "pre": ("PreToolUse",),
              "post": ("PostToolUse",), "flag": "--vendor codex",
              "write_tools": ("apply_patch",), "shell_tools": ("shell", "exec_command"),
              "start": ("SessionStart", "UserPromptSubmit"), "stop": None, "trust": ".codex/config.toml"},
    "gemini-cli": {"config": ".gemini/settings.json", "root": "hooks", "pre": ("BeforeTool",),
                   "post": ("AfterTool",), "flag": "--vendor gemini",
                   "write_tools": ("write_file", "replace"), "shell_tools": ("run_shell_command",),
                   "start": None, "stop": None},
    "antigravity": {"config": ".gemini/config/hooks.json", "root": "archhub-governance",
                    "pre": ("PreToolUse",), "post": None, "flag": "--vendor antigravity",
                    "write_tools": (), "shell_tools": (), "start": None, "stop": None},
    "cursor": {"config": ".cursor/hooks.json", "root": "hooks", "pre": ("preToolUse",),
               "post": None, "flag": None, "write_tools": (), "shell_tools": (),
               "start": None, "stop": None},
    "opencode": {"plugins": (".config/opencode/plugin", ".config/opencode/plugins")},
}
ALIASES = {"claude": "claude-code", "claude-code": "claude-code", "codex": "codex",
           "codex-desktop": "codex", "gemini": "gemini-cli", "gemini-cli": "gemini-cli",
           "antigravity": "antigravity", "cursor": "cursor", "opencode": "opencode"}
_SNAKE = {"PreToolUse": "pre_tool_use", "PostToolUse": "post_tool_use", "SessionStart": "session_start",
          "UserPromptSubmit": "user_prompt_submit", "Stop": "stop"}


def runtime_client(runtime: str) -> str:
    key = (runtime or "").strip().lower().replace("_", "-")
    return ALIASES.get(key, key)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _norm(text: str) -> str:
    return text.replace("\\\\", "/").replace("\\", "/")


def _entries(events: dict, names: Optional[tuple]) -> list[dict]:
    """Every hook bound to the named events: event, position, matcher, command."""
    found = []
    for name in names or ():
        value = events.get(name)
        groups = value if isinstance(value, list) else ([value] if isinstance(value, (dict, str)) else [])
        for gi, group in enumerate(groups):
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                matcher = group.get("matcher")
                hooks = group["hooks"]
            else:
                matcher, hooks = None, [group]
            for hi, hook in enumerate(hooks):
                if isinstance(hook, dict) and hook.get("enabled") is False:
                    continue
                found.append({"event": name, "group": gi, "hook": hi, "matcher": matcher,
                              "command": _norm(" ".join(_strings(hook)))})
    return found


def _covers(matcher: Any, tool: str) -> bool:
    if matcher in (None, "", "*"):
        return True
    try:
        return re.fullmatch("(?:%s)" % matcher, tool) is not None
    except (re.error, TypeError):
        return False


def _gate_entries(entries, markers, flag):
    return [e for e in entries if any(m in e["command"] for m in markers)
            and (flag is None or flag in e["command"])]


def _coverage(gates, tools):
    return [tool for tool in tools if not any(_covers(e["matcher"], tool) for e in gates)]


def _result(client: str, status: str, checks: dict, notes: dict) -> dict:
    return {"client": client, "status": status, "checks": checks,
            "issue_count": sum(1 for ok in checks.values() if not ok), "notes": notes}


def codex_hook_hash(event: str, matcher: Any, hook: dict) -> str:
    """Codex's trust identity of one command hook (hook_hash + version_for_toml)."""
    handler = {"type": "command", "command": str(hook.get("command") or ""),
               "timeout": max(1, int(hook.get("timeout") or 600)), "async": bool(hook.get("async", False))}
    if hook.get("statusMessage") is not None:
        handler["statusMessage"] = hook["statusMessage"]
    identity = {"event_name": _SNAKE.get(event, event), "hooks": [handler]}
    if matcher is not None:
        identity["matcher"] = matcher
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _codex_trust(home: Path, spec: dict, hooks_path: Path, events: dict, bound: list[dict], notes: dict) -> None:
    try:
        state = tomllib.loads((home / spec["trust"]).read_text(encoding="utf-8")).get("hooks", {}).get("state", {})
    except (OSError, UnicodeError, ValueError):
        state = {}
    prefix = str(hooks_path).casefold()
    recorded = {":".join(key.rsplit(":", 3)[1:]): value.get("trusted_hash")
                for key, value in state.items()
                if isinstance(value, dict) and key.casefold().startswith(prefix)}
    for entry in bound:
        position = "%s:%d:%d" % (_SNAKE.get(entry["event"], entry["event"]), entry["group"], entry["hook"])
        group = events[entry["event"]][entry["group"]]
        hook = group["hooks"][entry["hook"]] if isinstance(group, dict) and "hooks" in group else group
        current = codex_hook_hash(entry["event"], group.get("matcher") if isinstance(group, dict) else None,
                                  hook if isinstance(hook, dict) else {"command": str(hook)})
        trusted = recorded.get(position)
        if trusted != current:
            notes["trust:" + position] = (
                "needs approval in Codex /hooks: " + ("no trust record for this hook" if trusted is None
                                                      else "the trusted hash is for a different hook definition"))


def observe_runtime_compliance(runtime: str, *, home: Optional[Path] = None) -> dict[str, Any]:
    client = runtime_client(runtime)
    home = Path(home) if home is not None else Path.home()
    spec = VENDORS.get(client)
    failed = {name: False for name in CHECKS}
    if spec is None:
        return _result(client, "not-enforceable", failed,
                       {"reason": "no hook mechanism is known for this runtime; nothing can enforce its writes"})
    if "plugins" in spec:
        folders = [home / rel for rel in spec["plugins"]]
        texts = []
        for folder in folders:
            if folder.is_dir():
                for path in sorted(folder.iterdir()):
                    if path.suffix in (".js", ".ts", ".mjs") and path.is_file():
                        try:
                            texts.append(_norm(path.read_text(encoding="utf-8")))
                        except (OSError, UnicodeError):
                            pass
        present = any(folder.is_dir() for folder in folders)
        gate = any(OPENCODE_GATE in text for text in texts)
        checks = {"runtime-detected": present, "schema-valid": present, "scope-gate": gate,
                  "required-hooks": gate, "brain-connected": True, "workshop-authority": True}
        notes = {"start": "vendor has no supported native start hook",
                 "stop": "vendor has no supported native completion hook"}
        if not gate:
            notes["scope-gate"] = "no plugin in %s runs %s" % (" or ".join(spec["plugins"]), OPENCODE_GATE)
        return _result(client, "green" if all(checks.values()) else "red", checks, notes)
    path = home / spec["config"]
    checks = dict(failed)
    notes: dict[str, str] = {}
    if not path.is_file():
        notes["config"] = "%s is missing" % spec["config"]
        return _result(client, "red", checks, notes)
    checks["runtime-detected"] = True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        notes["config"] = "%s does not parse" % spec["config"]
        return _result(client, "red", checks, notes)
    events = data.get(spec["root"]) if isinstance(data, dict) else None
    if not isinstance(events, dict):
        notes["config"] = "%s has no %s object" % (spec["config"], spec["root"])
        return _result(client, "red", checks, notes)
    checks["schema-valid"] = True
    if data.get("disableAllHooks") is True:
        notes["hooks"] = "disableAllHooks is set: no hook runs"
        return _result(client, "red", checks, notes)
    bound = []
    pre = _gate_entries(_entries(events, spec["pre"]), GATES, spec["flag"])
    missing = _coverage(pre, spec["write_tools"])
    checks["scope-gate"] = bool(pre) and not missing
    bound += pre
    if not pre:
        notes["scope-gate"] = "%s does not run the landed gate" % "/".join(spec["pre"])
    elif missing:
        notes["scope-gate"] = "the gate matcher misses write tools: %s" % ", ".join(missing)
    shell = _coverage(pre, spec["shell_tools"]) if pre else list(spec["shell_tools"])
    if shell:
        notes["coverage"] = "partial: the gate does not see %s, so shell writes are not gated" % ", ".join(shell)
    post_ok = True
    if spec["post"]:
        post = _gate_entries(_entries(events, spec["post"]), GATES, spec["flag"])
        post_missing = _coverage(post, spec["write_tools"])
        post_ok = bool(post) and not post_missing
        bound += post
        if not post_ok:
            notes["required-hooks"] = ("%s does not settle through the landed gate" % "/".join(spec["post"])
                                       if not post else "the settle matcher misses: %s" % ", ".join(post_missing))
    checks["required-hooks"] = checks["scope-gate"] and post_ok
    if spec["start"]:
        start = [e for e in _entries(events, spec["start"]) if START_HOOK in e["command"]]
        checks["brain-connected"] = bool(start)
        bound += start
        if not start:
            notes["brain-connected"] = "%s does not run %s" % ("/".join(spec["start"]), START_HOOK)
    else:
        checks["brain-connected"] = True
        notes["brain-connected"] = "vendor has no supported native start hook"
    if spec["stop"]:
        stop = [e for e in _entries(events, spec["stop"]) if STOP_HOOK in e["command"]]
        checks["workshop-authority"] = bool(stop)
        bound += stop
        if not stop:
            notes["workshop-authority"] = "%s does not run %s" % ("/".join(spec["stop"]), STOP_HOOK)
    else:
        checks["workshop-authority"] = True
        notes["workshop-authority"] = "vendor has no supported native completion hook"
    if spec.get("trust"):
        _codex_trust(home, spec, path, events, bound, notes)
    return _result(client, "green" if all(checks.values()) else "red", checks, notes)


__all__ = ["CHECKS", "observe_runtime_compliance", "runtime_client"]