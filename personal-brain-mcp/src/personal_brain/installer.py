"""Installer — detects each MCP client on this device and writes the
right brain config without clobbering existing user settings.

Per AgDR-0044 Slice 3 + AUTOMATION MANDATE: "Anything doable from the
machine — DO IT. Never hand the founder a checklist of manual steps."

Supported clients (May 2026):
  - Claude Code    ~/.claude/settings.json
  - Cursor         ~/.cursor/mcp.json + ~/.cursor/rules/brain.mdc
  - Codex CLI      ~/.codex/config.toml
  - Gemini CLI     ~/.gemini/settings.json
  - Cline          (VS Code / JetBrains) — settings.json
  - Continue       ~/.continue/config.yaml

Run:
    python -m personal_brain.installer            # auto-detect + install
    python -m personal_brain.installer --dry-run  # show what would change
    python -m personal_brain.installer --only claude-code,cursor
    python -m personal_brain.installer --uninstall

Behaviour:
  - merge-not-clobber: existing keys preserved; conflicting keys reported.
  - founder consent: prints diff before writing (skipped via --yes).
  - reversible: each write creates a `.brain-bak.<ts>` snapshot.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ─────────────────────── client detectors + writers ────────────────────


@dataclass
class ClientPlan:
    """What a client needs to install brain."""

    name: str
    config_path: Path
    detect: Callable[[], bool]
    install: Callable[[bool], dict[str, Any]]  # (dry_run) → result dict
    uninstall: Callable[[bool], dict[str, Any]]


def _home() -> Path:
    return Path.home()


def _backup(path: Path) -> Optional[Path]:
    if not path.exists():
        return None
    bak = path.with_suffix(path.suffix + f".brain-bak.{int(time.time())}")
    shutil.copy2(path, bak)
    return bak


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _brain_command() -> dict[str, Any]:
    """The MCP server entry every client writes.

    Resolution priority:
      1. `personal-brain.exe` on PATH (works after `pip install` if
         Python's Scripts dir is on PATH).
      2. Discovered `personal-brain.exe` in Python's `sysconfig` scripts dir
         even when that dir is not on PATH (very common on Windows).
      3. Fallback to `<current_python> -m personal_brain.server` — always
         works as long as the package is importable.
    """
    import shutil
    import sys
    import sysconfig

    on_path = shutil.which("personal-brain")
    if on_path:
        return {
            "command": on_path,
            "args": [],
            "env": {"BRAIN_OWNER_USER": "${USER}"},
        }

    scripts_dir = sysconfig.get_path("scripts")
    if scripts_dir:
        for candidate in ("personal-brain.exe", "personal-brain"):
            p = Path(scripts_dir) / candidate
            if p.exists():
                return {
                    "command": str(p),
                    "args": [],
                    "env": {"BRAIN_OWNER_USER": "${USER}"},
                }

    # Final fallback: invoke via the running interpreter
    return {
        "command": sys.executable,
        "args": ["-m", "personal_brain.server"],
        "env": {"BRAIN_OWNER_USER": "${USER}"},
    }


def _repo_root() -> Path:
    """Repo root. installer.py is at
    <repo>/personal-brain-mcp/src/personal_brain/installer.py → parents[3]."""
    return Path(__file__).resolve().parents[3]


def _gate_command() -> str:
    """Command string for the anti-laziness Stop gate.

    The gate lives at <repo>/tools/anti_laziness_gate.py. Forward slashes
    work for Python on Windows.
    """
    gate = _repo_root() / "tools" / "anti_laziness_gate.py"
    py = sys.executable or "python"
    return f'"{py}" "{gate.as_posix()}"'


def _brainwrap_path() -> Path:
    """The universal hook adapter (<repo>/tools/brainwrap.py).

    Pointed at by every vendor hook whose runner spawns an *executable* over
    stdio (Cursor, Codex, Gemini CLI) rather than calling MCP tools directly,
    and the documented manual fallback for any hookless vendor.
    """
    return _repo_root() / "tools" / "brainwrap.py"


def _brainwrap_command(subcmd: str, vendor: str) -> str:
    """`"<python>" "<…/brainwrap.py>" <subcmd> --vendor <vendor>`."""
    py = sys.executable or "python"
    return (f'"{py}" "{_brainwrap_path().as_posix()}" '
            f'{subcmd} --vendor {vendor}')


# Documentation URLs proving each vendor's hook surface is REAL. A vendor
# only gets a real hook written if it appears here with a verified URL.
HOOK_DOC_URLS: dict[str, str] = {
    "claude-code": "https://docs.claude.com/en/docs/claude-code/hooks",
    "cursor": "https://cursor.com/docs/hooks",
    # Codex CLI exposes a real hook surface: a hooks.json (or inline [hooks]
    # tables in config.toml) with UserPromptSubmit + Stop events that run
    # `command` hooks over stdin/stdout. Confirmed verbatim from the page.
    "codex": "https://developers.openai.com/codex/hooks",
    # Gemini CLI exposes settings.json `hooks` with per-turn BeforeAgent
    # (injects context via hookSpecificOutput.additionalContext) + per-turn
    # AfterAgent (fires after the model's final response). Confirmed verbatim.
    "gemini-cli": "https://geminicli.com/docs/hooks/reference/",
}


def _is_gate_entry(e: Any) -> bool:
    return (
        isinstance(e, dict)
        and e.get("type") == "command"
        and "anti_laziness_gate" in str(e.get("command", ""))
    )


def _brain_hooks() -> dict[str, Any]:
    # Each mcp_tool hook points at a HOOK-SHAPED WRAPPER tool (server.py
    # brain.hook_*/brain.observe) and carries an `arguments` map built from
    # the hook event's scalar fields. WHY wrappers + arguments: Claude Code
    # calls the hook tool with this `arguments` object; the canonical tools
    # (brain.context / brain.write / brain.skill_mint / brain.wiring_announce)
    # need a TYPED positional (prompt / ops:LIST / trace:dict / device_id)
    # that `${...}` interpolation can't synthesize from scalar fields — so a
    # bare hook with NO arguments fired every tool with the wrong/empty shape
    # and FAILED (no recall, no learning, no mint, no announce). The wrappers
    # accept the raw payload (+ any extra kwargs) and build the real call.
    # Field names are the ones Claude Code emits per event (UserPromptSubmit:
    # prompt/session_id/cwd · PostToolUse: tool_name/tool_input/tool_response ·
    # Stop: session_id/transcript_path · SessionStart: session_id/cwd).
    return {
        "SessionStart": [
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.hook_session_start",
              "arguments": {
                  "session_id": "${session_id}",
                  "cwd": "${cwd}",
              }}
        ],
        "UserPromptSubmit": [
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.hook_context",
              "arguments": {
                  "prompt": "${prompt}",
                  "session_id": "${session_id}",
                  "cwd": "${cwd}",
              }}
        ],
        "PostToolUse": [
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.observe",
              "arguments": {
                  "tool_name": "${tool_name}",
                  "tool_input": "${tool_input}",
                  "tool_response": "${tool_response}",
                  "session_id": "${session_id}",
                  "cwd": "${cwd}",
              }}
        ],
        # Stop: the anti-laziness gate runs FIRST (it can BLOCK and force
        # the agent to keep working), then skill_mint records the trace.
        "Stop": [
            {"type": "command", "command": _gate_command(), "timeout": 30},
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.hook_skill_mint",
              "arguments": {
                  "session_id": "${session_id}",
                  "transcript_path": "${transcript_path}",
                  "cwd": "${cwd}",
              }},
        ],
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(data, indent=2, sort_keys=True))


def _merge_brain_into(
    config: dict[str, Any], *, with_hooks: bool = True
) -> tuple[dict[str, Any], list[str]]:
    """Merge brain MCP entry into a generic client config dict.

    Returns (new_config, notes). Existing entries preserved; brain entry
    upserts.
    """
    notes: list[str] = []
    out = dict(config)
    servers = dict(out.get("mcpServers") or {})
    if "brain" in servers:
        notes.append("mcpServers.brain already present — replaced with current")
    servers["brain"] = _brain_command()
    out["mcpServers"] = servers

    if with_hooks:
        hooks = dict(out.get("hooks") or {})
        for hook_name, entries in _brain_hooks().items():
            existing = list(hooks.get(hook_name) or [])
            # Drop any brain entry already present (idempotent) — both the
            # mcp_tool entries (server == "brain") and our command gate.
            filtered = [
                e for e in existing
                if not (isinstance(e, dict) and e.get("server") == "brain")
                and not _is_gate_entry(e)
            ]
            if len(filtered) != len(existing):
                notes.append(
                    f"hooks.{hook_name} had previous brain entries — replaced"
                )
            filtered.extend(entries)
            hooks[hook_name] = filtered
        out["hooks"] = hooks

    return out, notes


def _remove_brain_from(
    config: dict[str, Any], *, with_hooks: bool = True
) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    out = dict(config)
    servers = dict(out.get("mcpServers") or {})
    if "brain" in servers:
        del servers["brain"]
        notes.append("removed mcpServers.brain")
        out["mcpServers"] = servers

    if with_hooks:
        hooks = dict(out.get("hooks") or {})
        for hook_name in list(hooks.keys()):
            entries = hooks.get(hook_name) or []
            filtered = [
                e for e in entries
                if not (isinstance(e, dict) and e.get("server") == "brain")
                and not _is_gate_entry(e)
            ]
            if len(filtered) != len(entries):
                notes.append(f"removed brain entries from hooks.{hook_name}")
            if filtered:
                hooks[hook_name] = filtered
            else:
                # leave empty key only if previously had non-brain entries;
                # we already preserved them above. If nothing left, drop key.
                del hooks[hook_name]
        out["hooks"] = hooks

    return out, notes


# ── Claude Code ────────────────────────────────────────────────────────


def _claude_code_path() -> Path:
    return _home() / ".claude" / "settings.json"


def _detect_claude_code() -> bool:
    """Treat the presence of ~/.claude as the detection signal — Claude Code
    creates this on first run. Even when settings.json doesn't yet exist."""
    return (_home() / ".claude").exists() or shutil.which("claude") is not None


def _install_claude_code(dry_run: bool) -> dict[str, Any]:
    path = _claude_code_path()
    before = _load_json(path)
    after, notes = _merge_brain_into(before, with_hooks=True)
    if dry_run:
        return {"client": "claude-code", "path": str(path),
                "would_change": before != after, "notes": notes}
    if before != after:
        bak = _backup(path)
        _save_json(path, after)
        return {"client": "claude-code", "path": str(path),
                "changed": True, "backup": str(bak) if bak else None,
                "notes": notes}
    return {"client": "claude-code", "path": str(path), "changed": False,
            "notes": notes or ["already up to date"]}


def _uninstall_claude_code(dry_run: bool) -> dict[str, Any]:
    path = _claude_code_path()
    before = _load_json(path)
    after, notes = _remove_brain_from(before, with_hooks=True)
    if dry_run:
        return {"client": "claude-code", "path": str(path),
                "would_change": before != after, "notes": notes}
    if before != after:
        bak = _backup(path)
        _save_json(path, after)
        return {"client": "claude-code", "path": str(path),
                "changed": True, "backup": str(bak) if bak else None,
                "notes": notes}
    return {"client": "claude-code", "path": str(path), "changed": False,
            "notes": ["nothing to remove"]}


# ── Cursor ─────────────────────────────────────────────────────────────


def _cursor_path() -> Path:
    return _home() / ".cursor" / "mcp.json"


def _cursor_rules_path() -> Path:
    return _home() / ".cursor" / "rules" / "brain.mdc"


def _cursor_hooks_path() -> Path:
    return _home() / ".cursor" / "hooks.json"


def _detect_cursor() -> bool:
    return (_home() / ".cursor").exists() or shutil.which("cursor") is not None


def _cursor_hooks_block() -> dict[str, Any]:
    """Cursor Agent Hooks (https://cursor.com/docs/hooks) — VERIFIED real.

    `beforeSubmitPrompt` fires after send / before the backend request and
    can block; `stop` fires when the agent loop ends and can loop back via
    `followup_message`. Both spawn an executable over stdio JSON, so we point
    them at brainwrap, which adapts Cursor's contract to the brain daemon:
      pre-prompt → brain.context     stop → brain.enforce_diligence
    """
    return {
        "beforeSubmitPrompt": [
            {"command": _brainwrap_command("context", "cursor")}
        ],
        "stop": [
            {"command": _brainwrap_command("stop", "cursor")}
        ],
    }


def _merge_cursor_hooks(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Upsert the brain hooks into Cursor's hooks.json (version 1 schema),
    preserving any non-brain hook commands the user already has."""
    notes: list[str] = []
    out = dict(config)
    out.setdefault("version", 1)
    hooks = dict(out.get("hooks") or {})
    for hook_name, entries in _cursor_hooks_block().items():
        existing = list(hooks.get(hook_name) or [])
        filtered = [
            e for e in existing
            if not (isinstance(e, dict)
                    and "brainwrap" in str(e.get("command", "")))
        ]
        if len(filtered) != len(existing):
            notes.append(
                f"hooks.{hook_name} had a previous brainwrap entry — replaced")
        filtered.extend(entries)
        hooks[hook_name] = filtered
    out["hooks"] = hooks
    return out, notes


def _remove_cursor_hooks(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    out = dict(config)
    hooks = dict(out.get("hooks") or {})
    for hook_name in list(hooks.keys()):
        entries = hooks.get(hook_name) or []
        filtered = [
            e for e in entries
            if not (isinstance(e, dict)
                    and "brainwrap" in str(e.get("command", "")))
        ]
        if len(filtered) != len(entries):
            notes.append(f"removed brainwrap entry from hooks.{hook_name}")
        if filtered:
            hooks[hook_name] = filtered
        else:
            del hooks[hook_name]
    out["hooks"] = hooks
    return out, notes


_CURSOR_RULES_BODY = """---
description: Personal Brain context (auto-managed by personal-brain-mcp)
alwaysApply: true
---

# Brain context

A personal-brain MCP server is registered, and Cursor Agent Hooks
(`~/.cursor/hooks.json`) auto-fire the brain on `beforeSubmitPrompt` (context
inject) and `stop` (anti-laziness gate) via the brainwrap adapter. These
rules are the belt-and-suspenders nudge in case hooks are disabled.

To pull relevant skills + facts for the current task, call the
`brain.context` tool with the user's prompt. The server returns top-K skills
filtered by scope ACL, plus relevant facts.

After every tool call that produces useful new knowledge, call
`brain.write` with an ADD op so the brain learns. At session end, call
`brain.skill_mint` to propose a new skill from the successful trajectory.

Do NOT store secret values — only references like `op://vault/...`.
"""


def _install_cursor(dry_run: bool) -> dict[str, Any]:
    path = _cursor_path()
    before = _load_json(path)
    # mcpServers registers the brain MCP. Cursor cannot call MCP tools from a
    # hook (its hook runner spawns an executable over stdio), so hooks live in
    # a separate hooks.json — written below — not merged into mcp.json.
    after, notes = _merge_brain_into(before, with_hooks=False)

    # Cursor shipped Agent Hooks in v1.7 (Oct 2025). beforeSubmitPrompt + stop
    # are VERIFIED real (https://cursor.com/docs/hooks) → write them.
    hooks_path = _cursor_hooks_path()
    hooks_before = _load_json(hooks_path)
    hooks_after, hook_notes = _merge_cursor_hooks(hooks_before)
    notes += hook_notes

    rules_path = _cursor_rules_path()
    rules_exists = rules_path.exists()

    mcp_change = before != after
    hooks_change = hooks_before != hooks_after

    if dry_run:
        return {"client": "cursor", "path": str(path),
                "hooks_path": str(hooks_path), "rules_path": str(rules_path),
                "would_change": mcp_change or hooks_change or not rules_exists,
                "notes": notes
                + (["would write hooks.json (beforeSubmitPrompt + stop)"]
                   if hooks_change else [])
                + (["would write rules file"] if not rules_exists else [])}

    if mcp_change:
        _backup(path)
        _save_json(path, after)
    if hooks_change:
        _backup(hooks_path)
        _save_json(hooks_path, hooks_after)
        notes.append("wrote hooks.json (beforeSubmitPrompt + stop → brainwrap)")
    if not rules_exists:
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(rules_path, _CURSOR_RULES_BODY)
        notes.append("wrote cursor rules brain.mdc")
    return {"client": "cursor", "path": str(path),
            "hooks_path": str(hooks_path), "rules_path": str(rules_path),
            "changed": mcp_change or hooks_change or not rules_exists,
            "notes": notes}


def _uninstall_cursor(dry_run: bool) -> dict[str, Any]:
    path = _cursor_path()
    before = _load_json(path)
    after, notes = _remove_brain_from(before, with_hooks=False)

    hooks_path = _cursor_hooks_path()
    hooks_before = _load_json(hooks_path)
    hooks_after, hook_notes = _remove_cursor_hooks(hooks_before)
    notes += hook_notes

    rules_path = _cursor_rules_path()
    rules_existed = rules_path.exists()
    mcp_change = before != after
    hooks_change = hooks_before != hooks_after

    if dry_run:
        return {"client": "cursor",
                "would_change": mcp_change or hooks_change or rules_existed,
                "notes": notes}
    if mcp_change:
        _backup(path)
        _save_json(path, after)
    if hooks_change:
        _backup(hooks_path)
        _save_json(hooks_path, hooks_after)
    if rules_existed:
        _backup(rules_path)
        try:
            rules_path.unlink()
            notes.append("removed cursor rules brain.mdc")
        except Exception:
            pass
    return {"client": "cursor",
            "changed": mcp_change or hooks_change or rules_existed,
            "notes": notes}


# ── Codex CLI ──────────────────────────────────────────────────────────


def _codex_path() -> Path:
    return _home() / ".codex" / "config.toml"


def _codex_hooks_path() -> Path:
    return _home() / ".codex" / "hooks.json"


def _detect_codex() -> bool:
    return _codex_path().exists() or shutil.which("codex") is not None


# Codex CLI DOES expose a real hook surface (Confirmed verbatim from
# https://developers.openai.com/codex/hooks): a `hooks.json` next to the
# active config layer, with `UserPromptSubmit` + `Stop` events that run
# `command` hooks receiving one JSON object on stdin. (The `matcher` field is
# ignored for both events; `timeout` is in SECONDS, default 600.) So we point
# both at the EXISTING brainwrap launcher — same adapter Cursor uses:
#   UserPromptSubmit → brainwrap context   Stop → brainwrap stop
# The MCP server is still registered in config.toml so Codex can call brain
# tools directly; the hooks.json is what auto-fires context + the stop-gate.
_CODEX_BRAIN_BLOCK = """
# personal-brain-mcp (managed by `personal-brain-mcp installer`)
[mcp_servers.brain]
command = "personal-brain"
args = []

[mcp_servers.brain.env]
BRAIN_OWNER_USER = "${USER}"

# Pre-prompt context inject + stop-gate are AUTO-FIRED by ~/.codex/hooks.json
# (UserPromptSubmit + Stop → brainwrap). If you ever disable that file, the
# manual fallback is:
#   pre-prompt context inject:  python tools/brainwrap.py context --vendor generic
#   stop / anti-laziness gate:  python tools/brainwrap.py stop --vendor generic
# /personal-brain-mcp
"""


def _codex_hooks_block() -> dict[str, Any]:
    """Codex hooks.json (Confirmed: https://developers.openai.com/codex/hooks).

    Schema is `{"hooks": {"<Event>": [ {"hooks": [ {"type":"command",
    "command":"…", "timeout":N} ]} ]}}`. matcher is unsupported/ignored for
    UserPromptSubmit + Stop. timeout is in SECONDS (default 600); we set 30 on
    Stop to match the Claude Code gate's 30s budget. Both point at brainwrap:
      UserPromptSubmit → brainwrap context     Stop → brainwrap stop
    """
    return {
        "UserPromptSubmit": [
            {"hooks": [
                {"type": "command",
                 "command": _brainwrap_command("context", "generic")}
            ]}
        ],
        "Stop": [
            {"hooks": [
                {"type": "command",
                 "command": _brainwrap_command("stop", "generic"),
                 "timeout": 30}
            ]}
        ],
    }


def _codex_hook_is_brain(entry: Any) -> bool:
    """A Codex hook *group* entry that contains a brainwrap command hook."""
    if not isinstance(entry, dict):
        return False
    for h in entry.get("hooks") or []:
        if isinstance(h, dict) and "brainwrap" in str(h.get("command", "")):
            return True
    return False


def _merge_codex_hooks(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Upsert the brain hook groups into Codex's hooks.json, preserving any
    non-brain hook groups the user already has (idempotent)."""
    notes: list[str] = []
    out = dict(config)
    hooks = dict(out.get("hooks") or {})
    for event, groups in _codex_hooks_block().items():
        existing = list(hooks.get(event) or [])
        filtered = [g for g in existing if not _codex_hook_is_brain(g)]
        if len(filtered) != len(existing):
            notes.append(
                f"hooks.{event} had a previous brainwrap entry — replaced")
        filtered.extend(groups)
        hooks[event] = filtered
    out["hooks"] = hooks
    return out, notes


def _remove_codex_hooks(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    out = dict(config)
    hooks = dict(out.get("hooks") or {})
    for event in list(hooks.keys()):
        groups = hooks.get(event) or []
        filtered = [g for g in groups if not _codex_hook_is_brain(g)]
        if len(filtered) != len(groups):
            notes.append(f"removed brainwrap entry from hooks.{event}")
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]
    out["hooks"] = hooks
    return out, notes


def _install_codex(dry_run: bool) -> dict[str, Any]:
    path = _codex_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    mcp_present = "personal-brain-mcp" in existing
    if not mcp_present:
        new_content = existing + (
            "\n" if existing and not existing.endswith("\n") else ""
        ) + _CODEX_BRAIN_BLOCK
    else:
        new_content = existing

    # Codex hooks.json — UserPromptSubmit + Stop → brainwrap (Confirmed real).
    hooks_path = _codex_hooks_path()
    hooks_before = _load_json(hooks_path)
    hooks_after, hook_notes = _merge_codex_hooks(hooks_before)
    hooks_change = hooks_before != hooks_after

    notes: list[str] = []
    if mcp_present:
        notes.append("mcp_servers.brain already present")
    notes += hook_notes

    if dry_run:
        return {"client": "codex", "path": str(path),
                "hooks_path": str(hooks_path),
                "would_change": (not mcp_present) or hooks_change,
                "notes": (notes or [])
                + (["would append brain block"] if not mcp_present else [])
                + (["would write hooks.json (UserPromptSubmit + Stop)"]
                   if hooks_change else ["hooks.json already up to date"])}

    if not mcp_present:
        _backup(path)
        _atomic_write(path, new_content)
        notes.append("appended brain block to config.toml")
    if hooks_change:
        _backup(hooks_path)
        _save_json(hooks_path, hooks_after)
        notes.append("wrote hooks.json (UserPromptSubmit + Stop → brainwrap)")
    changed = (not mcp_present) or hooks_change
    return {"client": "codex", "path": str(path),
            "hooks_path": str(hooks_path), "changed": changed,
            "notes": notes or ["already up to date"]}


def _uninstall_codex(dry_run: bool) -> dict[str, Any]:
    path = _codex_path()
    notes: list[str] = []
    mcp_change = False
    new_text = ""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        start = text.find("# personal-brain-mcp")
        end = text.find("# /personal-brain-mcp")
        if start >= 0 and end >= 0:
            end_with_marker = end + len("# /personal-brain-mcp")
            new_text = text[:start] + text[end_with_marker:].lstrip()
            mcp_change = True
            notes.append("removed brain block from config.toml")
        else:
            notes.append("no brain block in config.toml")
    else:
        notes.append("no config.toml")

    hooks_path = _codex_hooks_path()
    hooks_before = _load_json(hooks_path)
    hooks_after, hook_notes = _remove_codex_hooks(hooks_before)
    hooks_change = hooks_before != hooks_after
    notes += hook_notes

    if dry_run:
        return {"client": "codex",
                "would_change": mcp_change or hooks_change, "notes": notes}
    if mcp_change:
        _backup(path)
        _atomic_write(path, new_text)
    if hooks_change:
        _backup(hooks_path)
        _save_json(hooks_path, hooks_after)
    return {"client": "codex", "changed": mcp_change or hooks_change,
            "notes": notes}


# ── Gemini CLI ─────────────────────────────────────────────────────────


def _gemini_path() -> Path:
    return _home() / ".gemini" / "settings.json"


def _detect_gemini() -> bool:
    return _gemini_path().parent.exists() or shutil.which("gemini") is not None


# Gemini CLI DOES expose a real hook surface (Confirmed verbatim from
# https://geminicli.com/docs/hooks/reference/): settings.json `hooks` with a
# PER-TURN `BeforeAgent` event (fires after a prompt is submitted, before the
# agent plans, and INJECTS context via `hookSpecificOutput.additionalContext`)
# and a PER-TURN `AfterAgent` event (fires after the model's final response).
# Each event maps to an array of groups `{matcher, hooks:[{type:"command",
# command, timeout}]}` (timeout in MILLISECONDS, default 60000). We point both
# at the EXISTING brainwrap launcher — no SessionEnd fallback needed since the
# per-turn AfterAgent is the real Stop equivalent:
#   BeforeAgent → brainwrap context     AfterAgent → brainwrap stop


def _gemini_hooks_block() -> dict[str, Any]:
    return {
        "BeforeAgent": [
            {"matcher": ".*",
             "hooks": [
                 {"type": "command",
                  "command": _brainwrap_command("context", "generic"),
                  "name": "brain-context",
                  "timeout": 30000}
             ]}
        ],
        "AfterAgent": [
            {"matcher": ".*",
             "hooks": [
                 {"type": "command",
                  "command": _brainwrap_command("stop", "generic"),
                  "name": "brain-stop-gate",
                  "timeout": 30000}
             ]}
        ],
    }


def _gemini_hook_is_brain(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    for h in entry.get("hooks") or []:
        if isinstance(h, dict) and "brainwrap" in str(h.get("command", "")):
            return True
    return False


def _merge_gemini_hooks(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Upsert the brain hook groups into Gemini's settings.json `hooks`,
    preserving any non-brain hook groups (idempotent)."""
    notes: list[str] = []
    out = dict(config)
    hooks = dict(out.get("hooks") or {})
    for event, groups in _gemini_hooks_block().items():
        existing = list(hooks.get(event) or [])
        filtered = [g for g in existing if not _gemini_hook_is_brain(g)]
        if len(filtered) != len(existing):
            notes.append(
                f"hooks.{event} had a previous brainwrap entry — replaced")
        filtered.extend(groups)
        hooks[event] = filtered
    out["hooks"] = hooks
    return out, notes


def _remove_gemini_hooks(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    out = dict(config)
    hooks = dict(out.get("hooks") or {})
    for event in list(hooks.keys()):
        groups = hooks.get(event) or []
        filtered = [g for g in groups if not _gemini_hook_is_brain(g)]
        if len(filtered) != len(groups):
            notes.append(f"removed brainwrap entry from hooks.{event}")
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]
    if hooks:
        out["hooks"] = hooks
    elif "hooks" in out:
        del out["hooks"]
    return out, notes


def _install_gemini(dry_run: bool) -> dict[str, Any]:
    path = _gemini_path()
    before = _load_json(path)
    after = dict(before)
    servers = dict(after.get("mcpServers") or {})
    notes: list[str] = []
    if "brain" in servers:
        notes.append("brain already registered — replaced")
    servers["brain"] = _brain_command()
    after["mcpServers"] = servers
    # Real hooks (Confirmed): BeforeAgent (context inject) + AfterAgent (stop).
    after, hook_notes = _merge_gemini_hooks(after)
    notes += hook_notes
    if dry_run:
        return {"client": "gemini-cli", "path": str(path),
                "would_change": before != after, "notes": notes}
    if before != after:
        _backup(path)
        _save_json(path, after)
        return {"client": "gemini-cli", "path": str(path), "changed": True,
                "notes": notes
                + ["wrote hooks (BeforeAgent + AfterAgent → brainwrap)"]}
    return {"client": "gemini-cli", "path": str(path), "changed": False,
            "notes": notes or ["already up to date"]}


def _uninstall_gemini(dry_run: bool) -> dict[str, Any]:
    path = _gemini_path()
    before = _load_json(path)
    after = dict(before)
    servers = dict(after.get("mcpServers") or {})
    if "brain" in servers:
        del servers["brain"]
    after["mcpServers"] = servers
    after, hook_notes = _remove_gemini_hooks(after)
    if dry_run:
        return {"client": "gemini-cli", "would_change": before != after,
                "notes": hook_notes}
    if before != after:
        _backup(path)
        _save_json(path, after)
        return {"client": "gemini-cli", "changed": True,
                "notes": (hook_notes or []) + ["removed"]}
    return {"client": "gemini-cli", "changed": False,
            "notes": ["nothing to remove"]}


# ─────────────────────── plan registry ─────────────────────────────────


ALL_PLANS: dict[str, ClientPlan] = {
    "claude-code": ClientPlan(
        name="claude-code",
        config_path=_claude_code_path(),
        detect=_detect_claude_code,
        install=_install_claude_code,
        uninstall=_uninstall_claude_code,
    ),
    "cursor": ClientPlan(
        name="cursor",
        config_path=_cursor_path(),
        detect=_detect_cursor,
        install=_install_cursor,
        uninstall=_uninstall_cursor,
    ),
    "codex": ClientPlan(
        name="codex",
        config_path=_codex_path(),
        detect=_detect_codex,
        install=_install_codex,
        uninstall=_uninstall_codex,
    ),
    "gemini-cli": ClientPlan(
        name="gemini-cli",
        config_path=_gemini_path(),
        detect=_detect_gemini,
        install=_install_gemini,
        uninstall=_uninstall_gemini,
    ),
}


# ─────────────────────── coverage matrix ───────────────────────────────
#
# Honest record of HOW each of the three brain touchpoints is wired per
# vendor. FOUR states — and the distinction between the two "enforced" kinds
# is load-bearing, NOT cosmetic: it is the one place the matrix could quietly
# lie about parity with Claude Code, so it gets its own honest label.
#
#   enforced-by-hook        — a REAL, Verify-confirmed vendor hook auto-fires
#                            it, PER-TOOL / per-event, with NO batching. Claude
#                            Code's PostToolUse→brain.write is this: the brain
#                            learns after EVERY tool call. (cite HOOK_DOC_URLS)
#   enforced-per-turn-flush — a REAL vendor hook auto-fires it, but ONCE PER
#                            TURN (on the stop/after-agent hook), not per tool.
#                            This is how foreign vendors (Codex/Gemini/Cursor)
#                            write the brain: brainwrap's stop hook flushes the
#                            turn's salient memory in ONE brain.write. Zero
#                            agent cooperation, BUT coarser granularity than
#                            Claude's per-tool write — so it is NOT marked the
#                            same. Honest parity, not false parity.
#   covered-by-brainwrap    — the brainwrap launcher is the registered/
#                            documented path for it, but NO vendor hook
#                            auto-fires it; the agent (or a script) must invoke.
#   docs-only               — only a rules/prompt nudge asks the agent to do
#                            it; no executable is wired at all.
#
# The three touchpoints:
#   pre_prompt_inject  → brain.context
#   post_tool_write    → brain.write
#   stop_gate          → brain.enforce_diligence / anti_laziness_gate
#
# This table is the SINGLE SOURCE the printed matrix reads — it must reflect
# only what install() actually writes. Do NOT upgrade a cell to
# "enforced-by-hook" without a verified hook in HOOK_DOC_URLS + a writer; do
# NOT mark a cell "enforced-per-turn-flush" unless the stop/after-agent hook is
# wired to brainwrap AND brainwrap.flush_turn_memory writes brain.write there.

ENFORCED = "enforced-by-hook"
PER_TURN = "enforced-per-turn-flush"
WRAPPER = "covered-by-brainwrap"
DOCS = "docs-only"

TOUCHPOINTS = ("pre_prompt_inject", "post_tool_write", "stop_gate")

COVERAGE_MATRIX: dict[str, dict[str, str]] = {
    # Claude Code: native mcp_tool hooks for all three (with_hooks=True).
    "claude-code": {
        "pre_prompt_inject": ENFORCED,   # UserPromptSubmit → brain.context
        "post_tool_write": ENFORCED,     # PostToolUse → brain.write
        "stop_gate": ENFORCED,           # Stop → anti_laziness_gate + skill_mint
    },
    # Cursor: REAL Agent Hooks (https://cursor.com/docs/hooks) auto-fire
    # brainwrap pre-prompt + stop. Cursor exposes NO per-tool hook, so the brain
    # can't learn per-tool — but the `stop` hook → brainwrap now flushes the
    # turn's memory to brain.write ONCE per turn (PER_TURN, not per-tool).
    "cursor": {
        "pre_prompt_inject": ENFORCED,   # beforeSubmitPrompt → brainwrap
        "post_tool_write": PER_TURN,     # stop → brainwrap flush (1×/turn)
        "stop_gate": ENFORCED,           # stop → brainwrap
    },
    # Codex CLI: REAL hooks.json (Confirmed: developers.openai.com/codex/hooks)
    # auto-fires brainwrap on UserPromptSubmit (context) + Stop (gate). No
    # per-tool hook exists — but the Stop hook → brainwrap now flushes the
    # turn's memory to brain.write ONCE per turn (PER_TURN, not per-tool).
    "codex": {
        "pre_prompt_inject": ENFORCED,   # UserPromptSubmit → brainwrap context
        "post_tool_write": PER_TURN,     # Stop → brainwrap flush (1×/turn)
        "stop_gate": ENFORCED,           # Stop → brainwrap stop
    },
    # Gemini CLI: REAL settings.json hooks (Confirmed: geminicli.com/docs/
    # hooks/reference). Per-turn BeforeAgent injects context + per-turn
    # AfterAgent fires after the final response → both brainwrap. No per-tool
    # hook exists — but AfterAgent → brainwrap now flushes the turn's memory to
    # brain.write ONCE per turn (PER_TURN, not per-tool).
    "gemini-cli": {
        "pre_prompt_inject": ENFORCED,   # BeforeAgent → brainwrap context
        "post_tool_write": PER_TURN,     # AfterAgent → brainwrap flush (1×/turn)
        "stop_gate": ENFORCED,           # AfterAgent → brainwrap stop
    },
}


def coverage_matrix(only: Optional[list[str]] = None) -> dict[str, dict[str, str]]:
    """Return the per-vendor coverage map (optionally filtered to `only`)."""
    names = only or list(COVERAGE_MATRIX.keys())
    return {n: dict(COVERAGE_MATRIX[n]) for n in names if n in COVERAGE_MATRIX}


def _coverage_note(vendor: str, touchpoint: str, state: str) -> str:
    if state == ENFORCED:
        url = HOOK_DOC_URLS.get(vendor, "")
        return f"real hook, per-tool ({url})" if url else "real hook, per-tool"
    if state == PER_TURN:
        url = HOOK_DOC_URLS.get(vendor, "")
        base = "real hook, ONCE per turn (stop-hook flush, not per-tool)"
        return f"{base} ({url})" if url else base
    if state == WRAPPER:
        return "brainwrap launcher (no vendor hook fires it)"
    return "rules/prompt nudge only"


def print_coverage_matrix(
    only: Optional[list[str]] = None,
    stream: Any = None,
) -> dict[str, dict[str, str]]:
    """Print an HONEST per-vendor coverage matrix and return it.

    Never prints a blanket "all wired" — every cell shows its real state
    (enforced-by-hook / enforced-per-turn-flush / covered-by-brainwrap /
    docs-only), and the legend discloses that the per-turn flush is COARSER
    than Claude Code's per-tool write so no reader infers false parity.
    """
    out = stream or sys.stdout
    matrix = coverage_matrix(only)
    headers = ("pre-prompt inject", "post-tool write", "stop-gate")
    name_w = max([len("vendor")] + [len(n) for n in matrix]) if matrix else 6
    col_w = max(len(WRAPPER), len(ENFORCED), len(PER_TURN), len(DOCS),
                *(len(h) for h in headers))
    lbl_w = max(len(ENFORCED), len(PER_TURN), len(WRAPPER), len(DOCS)) + 1

    out.write("\nBrain wiring coverage (honest — not all cells are hooks):\n")
    header = (f"  {'vendor'.ljust(name_w)}  "
              + "  ".join(h.ljust(col_w) for h in headers))
    out.write(header + "\n")
    out.write("  " + "-" * (len(header) - 2) + "\n")
    for vendor, cells in matrix.items():
        row = "  " + vendor.ljust(name_w) + "  " + "  ".join(
            cells[tp].ljust(col_w) for tp in TOUCHPOINTS)
        out.write(row + "\n")

    # Legend so no reader mistakes a wrapper/docs cell for a real hook, OR a
    # per-turn flush for Claude's per-tool write.
    out.write("\n  legend:\n")
    out.write(f"    {ENFORCED:<{lbl_w}}= a verified vendor hook auto-fires it, "
              "PER TOOL CALL (Claude Code's brain.write)\n")
    out.write(f"    {PER_TURN:<{lbl_w}}= a verified vendor hook auto-fires it, "
              "but ONCE PER TURN on the stop hook (brainwrap flush) —\n")
    out.write(f"    {'':<{lbl_w}}  coarser than per-tool; foreign vendors "
              "(Codex/Gemini/Cursor) learn the turn's gist, not every step\n")
    out.write(f"    {WRAPPER:<{lbl_w}}= brainwrap launcher; agent/script must "
              "invoke\n")
    out.write(f"    {DOCS:<{lbl_w}}= rules/prompt nudge only; nothing executes "
              "it\n")
    # Per-vendor proof line (a vendor with ANY real-hook cell — per-tool OR
    # per-turn-flush — cites its hook docs).
    for vendor, cells in matrix.items():
        url = HOOK_DOC_URLS.get(vendor)
        if any(s in (ENFORCED, PER_TURN) for s in cells.values()) and url:
            out.write(f"    {vendor}: real-hook docs {url}\n")
    return matrix


# ─────────────────────── orchestrator ──────────────────────────────────


def detect_clients() -> list[str]:
    """Names of detected MCP-capable clients on this device."""
    return [n for n, p in ALL_PLANS.items() if p.detect()]


def install_all(
    *,
    only: Optional[list[str]] = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Install brain into all detected clients (or `only`).
    Returns one result dict per client touched."""
    targets = only or detect_clients()
    results: list[dict[str, Any]] = []
    for name in targets:
        plan = ALL_PLANS.get(name)
        if plan is None:
            results.append({"client": name, "error": "unknown client"})
            continue
        try:
            results.append(plan.install(dry_run))
        except Exception as ex:
            results.append({"client": name, "error": str(ex)})
    return results


def uninstall_all(
    *,
    only: Optional[list[str]] = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    targets = only or list(ALL_PLANS.keys())
    results: list[dict[str, Any]] = []
    for name in targets:
        plan = ALL_PLANS.get(name)
        if plan is None:
            continue
        try:
            results.append(plan.uninstall(dry_run))
        except Exception as ex:
            results.append({"client": name, "error": str(ex)})
    return results


# ─────────────────────── CLI ───────────────────────────────────────────


def _force_utf8_console() -> None:
    """Make the matrix + notes render on any console.

    The honest coverage matrix and the per-vendor notes use Unicode (the
    `→` fallback arrow, the `—` em-dash in "already present — replaced", the
    box-drawing rules). On a stock Windows console (cp1252) `print()` raises
    UnicodeEncodeError and the founder sees a traceback instead of the
    matrix. Reconfigure std streams to UTF-8 with a safe error handler so the
    output never crashes on the very characters that make it readable.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            try:
                reconfig(encoding="utf-8", errors="backslashreplace")
            except Exception:
                pass


def _format_result_line(r: dict[str, Any]) -> str:
    name = r.get("client", "?")
    if r.get("error"):
        return f"  [{name}] error: {r['error']}"
    changed = r.get("changed") if "changed" in r else r.get("would_change")
    flag = "CHANGED" if changed else "SKIPPED"
    notes = r.get("notes") or []
    return f"  [{name}] {flag}  {r.get('path', '')}\n    " + "\n    ".join(notes)


def main(argv: Optional[list[str]] = None) -> int:
    _force_utf8_console()
    parser = argparse.ArgumentParser(
        prog="personal-brain installer",
        description="Detect MCP clients and wire the brain into each.",
    )
    parser.add_argument("--only", type=str, default=None,
                         help="Comma-separated client names.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Show diff without writing.")
    parser.add_argument("--uninstall", action="store_true",
                         help="Remove brain entries from configs.")
    parser.add_argument("--list", action="store_true",
                         help="Just list detected clients.")
    parser.add_argument("--matrix", action="store_true",
                         help="Print the per-vendor brain coverage matrix.")
    args = parser.parse_args(argv)

    only = [s.strip() for s in args.only.split(",")] if args.only else None

    if args.list:
        detected = detect_clients()
        if detected:
            print("Detected MCP clients:")
            for c in detected:
                print(f"  - {c}  ({ALL_PLANS[c].config_path})")
        else:
            print("No MCP clients detected.")
        return 0

    if args.matrix:
        print_coverage_matrix(only)
        return 0

    if args.uninstall:
        results = uninstall_all(only=only, dry_run=args.dry_run)
    else:
        results = install_all(only=only, dry_run=args.dry_run)

    print(("DRY-RUN — " if args.dry_run else "") +
           ("Uninstall" if args.uninstall else "Install") + " results:")
    for r in results:
        print(_format_result_line(r))

    # Always print the honest coverage matrix after an install so the founder
    # sees exactly which touchpoints are real hooks vs wrapper vs docs-only —
    # never a false "all wired."
    if not args.uninstall:
        print_coverage_matrix(only)

    errors = [r for r in results if r.get("error")]
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
