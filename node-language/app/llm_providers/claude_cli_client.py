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
    -> {"type": "final", "text": str, "tool_calls": [],
        "tool_calls_log": [{"name","input","result"}], "usage": {...}}
    raises RuntimeError on failure (router fallback chain re-routes).

Reasoning + tool-call surfacing (founder demand 2026-06-01 — "see
everything in nodes: REASONING, tool-calls"): we drive the CLI with
`--output-format stream-json --verbose` so it emits a JSONL event
stream instead of a single final blob. We parse it and:
  • stream every assistant `text` block through `on_chunk` (token-ish);
  • forward every `thinking` block AND the `post_turn_summary` line
    through `on_reasoning` so the Conversation / ai.plan node renders a
    REAL reasoning trace (not the old mocked block);
  • capture every MCP `tool_use` + its matching `tool_result` into
    `tool_calls_log` so the turn persists the tools the local Claude
    actually ran on the user's hosts. (Headless `claude -p` EXECUTES its
    MCP tools itself, so we don't re-run them in the router loop —
    `tool_calls` stays empty; the executed calls live in
    `tool_calls_log` for the plan record + a reasoning line each.)
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
# minute.
#
# 2026-06-23 — DEAD/HUNG CLI MUST NEVER BLOCK THE USER. The founder has the
# `claude` binary installed but SIGNED OUT. A 401 returns fast, but a hung
# subprocess (network stall, stuck MCP spawn, half-broken auth) must NOT hold
# the user for minutes before the router reaches the working archhub_cloud free
# model. So the ceiling is bounded to ~12 s: a hung/dead CLI fails within ~12 s
# and the router's 7-round fallback chain routes onward to the next provider in
# the SAME call. A clean conversational answer returns well under 12 s; the
# tool-loop work that benefited from the old 300 s ceiling is the rare case and
# is better served by a metered provider than by stalling the user behind a CLI
# that may never return.
_TIMEOUT_S = 12

# ArchHub MCP server — app/archhub_mcp_server.py (sibling of this
# package's parent). Exposes the connector ops as MCP tools.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MCP_SERVER = os.path.join(_APP_DIR, "archhub_mcp_server.py")

# Persistent HTTP/SSE MCP — the app starts ONE archhub_mcp_server on this port at
# launch (always ready), so the chat brain connects to a READY url instead of
# racing a COLD per-turn stdio spawn (the 'pending'/0-tools bug that left the
# brain tool-less). If it isn't up we fall back to the historical stdio spawn —
# zero regression. Founder 2026-06-09 "why is it not working".
def _mcp_http_port(default: int = 48700) -> int:
    """Persistent-MCP port from env, falling back to the default if the env var
    is unset or not a valid integer — a user-set bogus value must never crash
    importing this provider module."""
    try:
        return int(os.environ.get("ARCHHUB_MCP_HTTP_PORT", "") or default)
    except (TypeError, ValueError):
        return default


_MCP_HTTP_PORT = _mcp_http_port()


def _persistent_mcp_url() -> Optional[str]:
    """SSE URL if a persistent archhub MCP is already serving on the configured
    port, else None (→ caller spawns the stdio server). Fast loopback TCP probe."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", _MCP_HTTP_PORT), timeout=0.4):
            return f"http://127.0.0.1:{_MCP_HTTP_PORT}/sse"
    except Exception:
        return None


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
        """Write the --mcp-config JSON. PREFERS the persistent HTTP/SSE server
        (always-ready → no per-turn startup race) when it's up; otherwise FALLS
        BACK to spawning the stdio server per turn (historical behaviour). Returns
        the path, or None if neither is available."""
        url = _persistent_mcp_url()
        if url:
            cfg = {"mcpServers": {"archhub": {"type": "sse", "url": url}}}
        elif os.path.exists(_MCP_SERVER):
            cfg = {"mcpServers": {"archhub": {
                "command": _server_python(),
                "args": [_MCP_SERVER],
            }}}
        else:
            return None
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

        # `--output-format stream-json --verbose` → a JSONL event stream
        # we parse for text + thinking + tool_use + the final result.
        # `--include-partial-messages` would give finer token deltas but
        # also balloons the event count; block-level streaming is plenty
        # for the in-node trace and keeps the parser simple.
        cmd = [self._exe, "-p",
               "--output-format", "stream-json",
               "--verbose",
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

        return self._parse_stream(raw, on_chunk, on_reasoning)

    # ── stream-json event parser ──────────────────────────────────────
    def _parse_stream(
        self,
        raw: str,
        on_chunk: Callable[[str], None],
        on_reasoning: Optional[Callable[[str], None]],
    ) -> dict:
        """Parse the `--output-format stream-json` JSONL into the client
        contract. Streams text via on_chunk, reasoning via on_reasoning,
        and records the MCP tools the CLI executed in tool_calls_log."""
        on_reasoning = on_reasoning or (lambda _x: None)

        streamed_parts: list[str] = []   # assistant text blocks (chunked)
        final_text = ""
        usage: Optional[dict] = None
        is_error = False
        err_detail = ""
        # tool_use blocks keyed by id so we can attach the matching
        # tool_result that arrives in a later `user` event.
        tool_calls_log: list[dict] = []
        _by_id: dict[str, dict] = {}
        # Avoid double-emitting the same text both as a streamed block AND
        # again as the final `result` blob.
        any_text_streamed = False

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            if not isinstance(evt, dict):
                continue
            etype = evt.get("type")
            esub = evt.get("subtype")

            if etype == "assistant":
                msg = evt.get("message") or {}
                for blk in (msg.get("content") or []):
                    if not isinstance(blk, dict):
                        continue
                    bt = blk.get("type")
                    if bt == "text":
                        piece = blk.get("text") or ""
                        if piece:
                            streamed_parts.append(piece)
                            any_text_streamed = True
                            on_chunk(piece)
                    elif bt == "thinking":
                        # Extended-thinking — the model's real reasoning.
                        think = (blk.get("thinking") or "").strip()
                        if think:
                            on_reasoning(think)
                    elif bt == "tool_use":
                        name = blk.get("name") or "tool"
                        tu_id = blk.get("id") or ""
                        rec = {"name": name,
                                "input": blk.get("input") or {},
                                "result": None}
                        tool_calls_log.append(rec)
                        if tu_id:
                            _by_id[tu_id] = rec
                        # Surface the call itself as a reasoning frame so
                        # the node shows WHICH host op the local Claude
                        # ran (e.g. `revit__list_documents`).
                        pretty = name.replace("mcp__archhub__", "") \
                                     .replace("__", ".")
                        on_reasoning(f"→ called tool {pretty}")

            elif etype == "user":
                # tool_result blocks ride back on a synthetic user turn.
                msg = evt.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list):
                    for blk in content:
                        if (isinstance(blk, dict)
                                and blk.get("type") == "tool_result"):
                            tu_id = blk.get("tool_use_id") or ""
                            rec = _by_id.get(tu_id)
                            if rec is not None:
                                rec["result"] = blk.get("content")

            elif etype == "system" and esub == "post_turn_summary":
                # A concise model-authored summary of what it did — a
                # great single reasoning line for the node header.
                detail = (evt.get("status_detail") or "").strip()
                if detail:
                    on_reasoning(detail)

            elif etype == "result":
                is_error = bool(evt.get("is_error"))
                final_text = str(evt.get("result") or "")
                u = evt.get("usage")
                if isinstance(u, dict):
                    usage = {
                        "prompt_tokens": u.get("input_tokens"),
                        "completion_tokens": u.get("output_tokens"),
                    }
                if is_error:
                    err_detail = str(evt.get("result")
                                     or evt.get("subtype") or "unknown")

        if is_error:
            raise RuntimeError("claude CLI error: " + (err_detail or "unknown"))

        text = "".join(streamed_parts) or final_text
        # If we streamed text blocks already, don't re-emit the final blob
        # (would duplicate the whole message in the node). If we streamed
        # nothing but the result has text (e.g. a pure tool turn that ended
        # with a short summary), emit it once.
        if final_text and not any_text_streamed:
            on_chunk(final_text)
            text = final_text

        out: dict = {"type": "final", "text": text,
                     "tool_calls": [], "tool_calls_log": tool_calls_log}
        if usage:
            out["usage"] = usage
        return out
