"""Claude Code (`claude` CLI) provider — completions on the user's
Claude **subscription**, not the metered Anthropic API.

Founder demand 2026-05-16: "having claude installed on the PC should
bypass the credit / API issue." `claude -p` (Claude Code headless print
mode) authenticates with the logged-in Claude Code session — Pro/Max
OAuth — so it KEEPS WORKING when `ANTHROPIC_API_KEY` is out of credit.
That is the credit bypass: route LLM calls through the local `claude`
binary instead of a per-token API.

Tool surface: every call attaches the ArchHub MCP server
(`archhub_mcp_server.py`) via `--mcp-config`, and disables Claude
Code's own built-in tools with `--tools ""`. The local Claude can
therefore call ArchHub's ~117 connector ops (revit / autocad / excel /
outlook …) — and ONLY those — so it acts on the user's hosts for real
instead of fabricating, and it can't wander off into Bash.

Interface contract (matches the other provider clients):
    stream_completion(model, system, messages, tools, on_chunk,
                      on_reasoning=None) -> dict
    -> {"type": "final", "text": str}
    raises RuntimeError on failure (router fallback chain re-routes).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, Optional

# Windows: don't flash a console window for the subprocess.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Hard ceiling on a single headless call. Claude Code has ~5s startup
# overhead, plus the MCP server spawn; a real answer rarely exceeds a
# minute. 300s is generous so a slow tool turn isn't killed mid-stream.
_TIMEOUT_S = 300

# ArchHub MCP server — app/archhub_mcp_server.py (sibling of this
# package's parent). Exposes the connector ops as MCP tools.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MCP_SERVER = os.path.join(_APP_DIR, "archhub_mcp_server.py")


def claude_cli_path() -> Optional[str]:
    """Absolute path to the `claude` binary, or None if not installed."""
    return shutil.which("claude") or shutil.which("claude.cmd")


def _server_python() -> str:
    """Console Python to run the MCP server. Prefer `python.exe` over
    `pythonw.exe` (the app runs under pythonw, but a stdio MCP server
    wants a normal console interpreter)."""
    exe = sys.executable or "python"
    if exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            return cand
    return exe


def _model_arg(model: str) -> str:
    """Map an ArchHub model id / alias to a `claude --model` value.
    Claude Code accepts `sonnet` / `opus` / `haiku` and full ids."""
    m = (model or "").lower().strip()
    if not m or m in ("auto", "default", "router picks"):
        return "sonnet"
    if "opus" in m:
        return "opus"
    if "haiku" in m:
        return "haiku"
    if "sonnet" in m:
        return "sonnet"
    return model  # full model id — passed straight through


class ClaudeCliClient:
    """Headless `claude` CLI provider client, tool-capable via MCP."""

    def __init__(self) -> None:
        self._exe = claude_cli_path()
        if not self._exe:
            raise RuntimeError("`claude` CLI not found on PATH")
        self._mcp_config = self._write_mcp_config()

    def _write_mcp_config(self) -> Optional[str]:
        """Write the --mcp-config JSON pointing at the ArchHub MCP
        server. Returns the path, or None if the server file is
        missing (the client then runs completion-only)."""
        if not os.path.exists(_MCP_SERVER):
            return None
        cfg = {"mcpServers": {"archhub": {
            "command": _server_python(),
            "args": [_MCP_SERVER],
        }}}
        path = os.path.join(tempfile.gettempdir(), "archhub_claude_mcp.json")
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
            return path
        except Exception:
            return None

    def stream_completion(
        self,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        on_chunk: Callable[[str], None],
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> dict:
        on_chunk = on_chunk or (lambda _x: None)

        # Claude Code print mode is one-shot. Fold the conversation into
        # a single prompt transcript so prior turns still give context.
        lines: list[str] = []
        for m in messages:
            content = m.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            role = m.get("role")
            if role == "tool":
                continue
            speaker = "Assistant" if role == "assistant" else "User"
            lines.append(f"{speaker}: {content.strip()}")
        prompt = "\n\n".join(lines)
        if not prompt:
            raise RuntimeError("claude CLI: empty prompt")

        cmd = [self._exe, "-p",
               "--output-format", "json",
               "--model", _model_arg(model)]
        if system and system.strip():
            cmd += ["--append-system-prompt", system.strip()]
        # Tool surface: ArchHub MCP server only. `--tools ""` kills
        # Claude Code's built-ins (Bash/Edit/…) so it can't escape the
        # connector sandbox; `--mcp-config` + `--strict-mcp-config` add
        # exactly ArchHub's ops; `--allowedTools mcp__archhub`
        # pre-approves them (headless mode can't prompt for permission).
        if self._mcp_config:
            cmd += ["--mcp-config", self._mcp_config,
                    "--strict-mcp-config",
                    "--tools", "",
                    "--allowedTools", "mcp__archhub"]
        else:
            cmd += ["--tools", ""]

        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                # Force UTF-8 both ways — `claude` emits UTF-8 JSON; on
                # Windows text=True would decode with cp1252 and mangle
                # em-dashes / smart quotes (â€" mojibake).
                encoding="utf-8", errors="replace",
                timeout=_TIMEOUT_S, check=False, creationflags=_NO_WINDOW,
                # Neutral cwd — Claude Code must not pick up ArchHub's
                # repo as a workspace or auto-load its CLAUDE.md.
                cwd=tempfile.gettempdir(),
            )
        except subprocess.TimeoutExpired as ex:
            raise RuntimeError(
                f"claude CLI timed out after {_TIMEOUT_S}s") from ex
        except Exception as ex:
            raise RuntimeError(f"claude CLI invocation failed: {ex}") from ex

        raw = (proc.stdout or "").strip()
        if not raw:
            err = (proc.stderr or "").strip()
            raise RuntimeError(
                "claude CLI returned no output"
                + (f" — {err[:300]}" if err else ""))

        # `--output-format json` → one JSON object with `result`.
        try:
            data = json.loads(raw)
        except Exception:
            on_chunk(raw)
            return {"type": "final", "text": raw}

        if isinstance(data, dict) and data.get("is_error"):
            raise RuntimeError(
                "claude CLI error: "
                + str(data.get("result")
                      or data.get("subtype") or "unknown"))

        text = ""
        if isinstance(data, dict):
            text = str(data.get("result") or "")
        if text:
            on_chunk(text)
        return {"type": "final", "text": text}
