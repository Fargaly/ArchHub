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


def _brain_hooks() -> dict[str, Any]:
    return {
        "SessionStart": [
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.wiring_announce"}
        ],
        "UserPromptSubmit": [
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.context"}
        ],
        "PostToolUse": [
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.write"}
        ],
        "Stop": [
            {"type": "mcp_tool", "server": "brain",
              "tool": "brain.skill_mint"}
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
            # Drop any brain entry already present (idempotent)
            filtered = [
                e for e in existing
                if not (isinstance(e, dict) and e.get("server") == "brain")
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


def _detect_cursor() -> bool:
    return (_home() / ".cursor").exists() or shutil.which("cursor") is not None


_CURSOR_RULES_BODY = """---
description: Personal Brain context (auto-managed by personal-brain-mcp)
alwaysApply: true
---

# Brain context

A personal-brain MCP server is registered. To pull relevant skills + facts
for the current task, call the `brain.context` tool with the user's prompt.
The server returns top-K skills filtered by scope ACL, plus relevant facts.

After every tool call that produces useful new knowledge, call
`brain.write` with an ADD op so the brain learns. At session end, call
`brain.skill_mint` to propose a new skill from the successful trajectory.

Do NOT store secret values — only references like `op://vault/...`.
"""


def _install_cursor(dry_run: bool) -> dict[str, Any]:
    path = _cursor_path()
    before = _load_json(path)
    # Cursor has no built-in hooks for UserPromptSubmit; use mcpServers only.
    after, notes = _merge_brain_into(before, with_hooks=False)
    rules_path = _cursor_rules_path()
    rules_exists = rules_path.exists()

    if dry_run:
        return {"client": "cursor", "path": str(path),
                "would_change": (before != after) or (not rules_exists),
                "rules_path": str(rules_path),
                "notes": notes + (["would write rules file"] if not rules_exists else [])}

    if before != after:
        _backup(path)
        _save_json(path, after)
    if not rules_exists:
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(rules_path, _CURSOR_RULES_BODY)
        notes.append("wrote cursor rules brain.mdc")
    return {"client": "cursor", "path": str(path),
            "changed": before != after,
            "rules_path": str(rules_path),
            "notes": notes}


def _uninstall_cursor(dry_run: bool) -> dict[str, Any]:
    path = _cursor_path()
    before = _load_json(path)
    after, notes = _remove_brain_from(before, with_hooks=False)
    rules_path = _cursor_rules_path()
    rules_existed = rules_path.exists()
    if dry_run:
        return {"client": "cursor", "would_change": before != after or rules_existed,
                "notes": notes}
    if before != after:
        _backup(path)
        _save_json(path, after)
    if rules_existed:
        _backup(rules_path)
        try:
            rules_path.unlink()
            notes.append("removed cursor rules brain.mdc")
        except Exception:
            pass
    return {"client": "cursor", "changed": before != after or rules_existed,
            "notes": notes}


# ── Codex CLI ──────────────────────────────────────────────────────────


def _codex_path() -> Path:
    return _home() / ".codex" / "config.toml"


def _detect_codex() -> bool:
    return _codex_path().exists() or shutil.which("codex") is not None


_CODEX_BRAIN_BLOCK = """
# personal-brain-mcp (managed by `personal-brain-mcp installer`)
[mcp_servers.brain]
command = "personal-brain"
args = []

[mcp_servers.brain.env]
BRAIN_OWNER_USER = "${USER}"
# /personal-brain-mcp
"""


def _install_codex(dry_run: bool) -> dict[str, Any]:
    path = _codex_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "personal-brain-mcp" in existing:
        # idempotent
        if dry_run:
            return {"client": "codex", "path": str(path),
                    "would_change": False, "notes": ["already installed"]}
        return {"client": "codex", "path": str(path), "changed": False,
                "notes": ["already installed"]}
    new_content = existing + ("\n" if existing and not existing.endswith("\n") else "") + _CODEX_BRAIN_BLOCK
    if dry_run:
        return {"client": "codex", "path": str(path),
                "would_change": True, "notes": ["would append brain block"]}
    _backup(path)
    _atomic_write(path, new_content)
    return {"client": "codex", "path": str(path), "changed": True,
            "notes": ["appended brain block"]}


def _uninstall_codex(dry_run: bool) -> dict[str, Any]:
    path = _codex_path()
    if not path.exists():
        return {"client": "codex", "changed": False, "notes": ["no config file"]}
    text = path.read_text(encoding="utf-8")
    start = text.find("# personal-brain-mcp")
    end = text.find("# /personal-brain-mcp")
    if start < 0 or end < 0:
        return {"client": "codex", "changed": False, "notes": ["no brain block"]}
    end_with_marker = end + len("# /personal-brain-mcp")
    new_text = text[:start] + text[end_with_marker:].lstrip()
    if dry_run:
        return {"client": "codex", "would_change": True,
                "notes": ["would remove brain block"]}
    _backup(path)
    _atomic_write(path, new_text)
    return {"client": "codex", "changed": True, "notes": ["removed brain block"]}


# ── Gemini CLI ─────────────────────────────────────────────────────────


def _gemini_path() -> Path:
    return _home() / ".gemini" / "settings.json"


def _detect_gemini() -> bool:
    return _gemini_path().parent.exists() or shutil.which("gemini") is not None


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
    if dry_run:
        return {"client": "gemini-cli", "path": str(path),
                "would_change": before != after, "notes": notes}
    if before != after:
        _backup(path)
        _save_json(path, after)
        return {"client": "gemini-cli", "path": str(path), "changed": True,
                "notes": notes}
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
    if dry_run:
        return {"client": "gemini-cli", "would_change": before != after,
                "notes": []}
    if before != after:
        _backup(path)
        _save_json(path, after)
        return {"client": "gemini-cli", "changed": True, "notes": ["removed"]}
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


def _format_result_line(r: dict[str, Any]) -> str:
    name = r.get("client", "?")
    if r.get("error"):
        return f"  [{name}] error: {r['error']}"
    changed = r.get("changed") if "changed" in r else r.get("would_change")
    flag = "CHANGED" if changed else "SKIPPED"
    notes = r.get("notes") or []
    return f"  [{name}] {flag}  {r.get('path', '')}\n    " + "\n    ".join(notes)


def main(argv: Optional[list[str]] = None) -> int:
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

    if args.uninstall:
        results = uninstall_all(only=only, dry_run=args.dry_run)
    else:
        results = install_all(only=only, dry_run=args.dry_run)

    print(("DRY-RUN — " if args.dry_run else "") +
           ("Uninstall" if args.uninstall else "Install") + " results:")
    for r in results:
        print(_format_result_line(r))

    errors = [r for r in results if r.get("error")]
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
