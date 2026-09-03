"""Codex CLI provider — completions on the user's ChatGPT
**subscription**, not the metered OpenAI API.

Founder demand 2026-05-17: "bypass api and quota also since I have codex
on this machine." `codex exec` (the Codex CLI headless mode) runs on the
logged-in Codex / ChatGPT subscription — it KEEPS WORKING when the
OpenAI `ANTHROPIC`/`OPENAI_API_KEY` is out of quota (429
insufficient_quota). Same idea as claude_cli_client, for Codex.

Phase 1: plain completions. `codex exec --sandbox read-only -o <file>`
runs the agent in a no-write sandbox and writes ONLY the final message
to <file>; we read that back. No ArchHub connector tools yet (bridging
them needs a Codex MCP-server registration — a later iteration).

Interface contract (matches the other provider clients):
    stream_completion(model, system, messages, tools, on_chunk,
                      on_reasoning=None) -> dict
    -> {"type": "final", "text": str}
    raises RuntimeError on failure (router fallback chain re-routes).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Callable, Optional

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Codex `exec` spins up an agent and is ONE-SHOT (no token streaming — the
# whole answer lands at once when it finishes). For INTERACTIVE CHAT a long
# ceiling means the user stares at nothing for minutes, then a dump — the
# founder's "every time I write I get nothing" on tool-ish prompts (2026-06-20:
# "summarize my notion notes" sat for 5 min). Bound it tightly: a normal
# conversational codex answer returns well under this, and a slow/stuck turn
# trips the router's SOFT timeout → fast-provider fallback → the no-empty
# guarantee streams a real answer instead of stalling.
#
# 2026-06-23 — DEAD/HUNG CLI MUST NEVER BLOCK THE USER. The founder has codex
# installed but SIGNED OUT: `codex exec` does NOT fail fast — it HANGS, burning
# the whole ceiling before the router can reach the working archhub_cloud free
# model. So the ceiling is bounded to ~12 s: a hung/dead CLI now fails within
# ~12 s and the router's 7-round fallback chain routes onward to the next
# provider in the SAME call. A legitimate codex answer (no-tool conversational
# turn) lands well under 12 s; tool-heavy work is not codex_cli's job here
# (read-only sandbox, no ArchHub tools bridged).
_TIMEOUT_S = 12


def codex_cli_path() -> Optional[str]:
    """Absolute path to the `codex` binary, or None if not installed."""
    return shutil.which("codex") or shutil.which("codex.cmd")


class CodexCliClient:
    """Headless `codex exec` provider client."""

    def __init__(self) -> None:
        self._exe = codex_cli_path()
        if not self._exe:
            raise RuntimeError("`codex` CLI not found on PATH")

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

        # Codex exec is one-shot. Fold system + conversation into a
        # single prompt — Codex has no separate system-prompt flag.
        lines: list[str] = []
        if system and system.strip():
            lines.append(system.strip())
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
            raise RuntimeError("codex CLI: empty prompt")

        # `-o <file>` writes ONLY the final agent message; clean to read
        # back (stdout also carries agent/session noise we ignore).
        out_path = os.path.join(tempfile.gettempdir(),
                                 f"archhub_codex_{uuid.uuid4().hex}.txt")
        # `-` → read the prompt from stdin. read-only sandbox so the
        # agent can't write/execute anything — it just answers.
        cmd = [self._exe, "exec",
               "--skip-git-repo-check",
               "--sandbox", "read-only",
               "--ephemeral",
               "-o", out_path,
               "-"]

        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=_TIMEOUT_S, check=False, creationflags=_NO_WINDOW,
                cwd=tempfile.gettempdir(),
            )
        except subprocess.TimeoutExpired as ex:
            self._cleanup(out_path)
            raise RuntimeError(
                f"codex CLI timed out after {_TIMEOUT_S}s") from ex
        except Exception as ex:
            self._cleanup(out_path)
            raise RuntimeError(f"codex CLI invocation failed: {ex}") from ex

        text = ""
        try:
            if os.path.exists(out_path):
                with open(out_path, "r", encoding="utf-8",
                           errors="replace") as fh:
                    text = fh.read().strip()
        finally:
            self._cleanup(out_path)

        if not text:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                "codex CLI produced no answer"
                + (f" — {err[:300]}" if err else ""))

        on_chunk(text)
        return {"type": "final", "text": text}

    @staticmethod
    def _cleanup(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
