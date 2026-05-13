"""Codex CLI backend — shells out to `codex.exe exec` locally.

Why this exists: the OpenAI REST API quota (`OPENAI_API_KEY`) on this
account is 429 quota-exceeded. The Codex CLI uses a SEPARATE auth path
(ChatGPT account token in `~/.codex/auth.json` `tokens` field) so it
can still run.

Selected via env `ARCHHUB_AGENTS_BACKEND=codex_cli`. Local-only — won't
work on the Fly.io cloud daemon (binary is Windows-only + needs the
user's auth.json file).

Default model: `gpt-5.3-codex` because the installed CLI v0.119.0-
alpha.28 rejects `gpt-5.5` ("requires a newer version of Codex").
Bump DEFAULT_CODEX_CLI_MODEL when the alpha CLI is upgraded.

Token overhead is ~20k per call due to the sandboxed code-agent
runtime — not cheap but bypasses the API quota wall.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Resolve the bundled codex binary path. The CLI installs at
# `%USERPROFILE%/.codex/.sandbox-bin/codex.exe` by default.
CODEX_HOME = Path(os.environ.get(
    "CODEX_HOME",
    str(Path.home() / ".codex"),
))
CODEX_EXE = CODEX_HOME / ".sandbox-bin" / "codex.exe"

DEFAULT_CODEX_CLI_MODEL = os.environ.get(
    "ARCHHUB_CODEX_CLI_MODEL", "gpt-5.3-codex",
)
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get(
    "ARCHHUB_CODEX_CLI_TIMEOUT", "300",
))


# Ollama-model-id -> Codex CLI model. Codex CLI is a single binary so
# model selection is a CLI flag (-m). Bigger Ollama models route to
# heavier Codex variants.
MODEL_MAP: dict[str, str] = {
    "qwen2.5-coder:7b":  "gpt-5.3-codex",
    "qwen2.5-coder:14b": "gpt-5.3-codex",
    "llama3.2:3b":       "gpt-5.1-codex-mini",
    "llama3.1:latest":   "gpt-5.1-codex",
    "llama3.1:8b":       "gpt-5.1-codex",
    "command-r7b":       "gpt-5.1-codex-mini",
    "command-r:latest":  "gpt-5.1-codex-mini",
    "deepseek-r1:8b":    "gpt-5.1-codex-max",
    "deepseek-r1:14b":   "gpt-5.1-codex-max",
}


@dataclass
class CodexCliCompletion:
    """Shape-compatible with agents.ollama.OllamaCompletion."""
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def is_configured() -> bool:
    """True when the binary exists + auth.json shows a logged-in state."""
    if not CODEX_EXE.exists():
        return False
    auth = CODEX_HOME / "auth.json"
    return auth.exists()


def is_running() -> bool:
    """Alias of is_configured() — kept for parity with ollama.is_running."""
    return is_configured()


def list_models() -> list[str]:
    return list(set(MODEL_MAP.values())) + [DEFAULT_CODEX_CLI_MODEL]


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _parse_codex_output(raw: str) -> tuple[str, int]:
    """Pull the final assistant message + token count out of the CLI's
    line-stream output.

    Codex exec writes a banner, then `user`/`codex` blocks, then
    `tokens used\\n<N>`. We extract the LAST `codex` block as the
    answer and the integer following `tokens used` for usage tracking.
    """
    text = _strip_ansi(raw)
    # Token count.
    total = 0
    m = re.search(r"tokens used\s*\n\s*([\d,]+)", text, re.IGNORECASE)
    if m:
        try:
            total = int(m.group(1).replace(",", ""))
        except ValueError:
            total = 0
    # Last 'codex' block. The lines after `codex` until the next
    # divider / `tokens used` are the assistant reply.
    blocks = re.split(r"^codex\s*$", text, flags=re.MULTILINE)
    if len(blocks) >= 2:
        body = blocks[-1]
        # Stop at the tokens marker or any all-caps section header.
        body = re.split(r"(?:^tokens used\b|^--------\s*$)", body,
                          maxsplit=1, flags=re.MULTILINE)[0]
        return body.strip(), total
    # Fallback — return everything stripped.
    return text.strip(), total


def complete(*, model: str, system: str, user: str,
              temperature: float = 0.1,
              max_tokens: int = 4096,
              timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> CodexCliCompletion:
    """Shell out to `codex.exe exec` with the prompt.

    `system` is folded into the prompt as a leading instruction —
    Codex CLI doesn't have a separate system-prompt flag.
    """
    if not CODEX_EXE.exists():
        raise RuntimeError(
            f"Codex CLI binary not found at {CODEX_EXE}. "
            f"Install via the OpenAI Codex installer or set CODEX_HOME."
        )
    mapped = MODEL_MAP.get(model, DEFAULT_CODEX_CLI_MODEL)
    prompt = user
    if system:
        prompt = f"[System instruction]\n{system}\n\n[Task]\n{user}"

    started = time.time()
    proc = subprocess.run(
        [
            str(CODEX_EXE), "exec",
            "--skip-git-repo-check",
            "-m", mapped,
            prompt,
        ],
        capture_output=True, text=True, timeout=timeout_seconds,
        # Inherit env — Codex reads ~/.codex/auth.json + OPENAI_API_KEY.
        env=os.environ.copy(),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Codex CLI exited {proc.returncode}. "
            f"stdout: {proc.stdout[:400]} | stderr: {proc.stderr[:400]}"
        )
    text, total_tokens = _parse_codex_output(proc.stdout)
    return CodexCliCompletion(
        text=text or proc.stdout.strip()[-1000:],
        model=mapped,
        prompt_tokens=0,            # CLI doesn't split prompt vs completion
        completion_tokens=total_tokens,
    )
