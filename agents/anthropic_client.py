"""Anthropic API client for cloud-deployed departments.

Drop-in replacement for `agents/ollama.py`. Same `complete()` signature,
same `OllamaCompletion`-shaped envelope (re-exported here under the
alias `AnthropicCompletion` so callers that imported `OllamaCompletion`
keep working with a one-line swap).

Why not the official `anthropic` SDK? The departments only ever batch
one non-streaming completion at a time, then write the reply to disk.
Pulling in the SDK plus its deps adds ~15MB to the Fly container for
no win. Raw httpx against the JSON API is fewer moving parts.

Model-id mapping: each department in `departments.py` names an Ollama
model (qwen2.5-coder:7b, llama3.2:3b, ...). For the cloud daemon we
remap every department to a cost-friendly Anthropic model. Haiku is
plenty for these tightly-scoped role-based tasks and keeps the monthly
spend predictable. Edit MODEL_MAP to bump a specific dept up.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx


ANTHROPIC_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT_SECONDS = 600

# Map Ollama-style model ids (declared on Agent subclasses) onto Anthropic
# model ids. All defaults to Haiku for cost; bump a specific entry to
# Sonnet/Opus if a department needs heavier reasoning.
MODEL_MAP: dict[str, str] = {
    # Coding-oriented Ollama models → Haiku is fine for our patch-sized output
    "qwen2.5-coder:7b": "claude-haiku-4-5-20251001",
    "qwen2.5-coder:14b": "claude-haiku-4-5-20251001",
    # General reasoning small models
    "llama3.2:3b": "claude-haiku-4-5-20251001",
    "llama3.1:latest": "claude-haiku-4-5-20251001",
    "llama3.1:8b": "claude-haiku-4-5-20251001",
    # Command-R variants — used by some Ops tasks elsewhere
    "command-r7b": "claude-haiku-4-5-20251001",
    "command-r:latest": "claude-haiku-4-5-20251001",
    # Reasoning models — same downgrade (Haiku 4.5 already does decent CoT)
    "deepseek-r1:8b": "claude-haiku-4-5-20251001",
    "deepseek-r1:14b": "claude-haiku-4-5-20251001",
}
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class AnthropicCompletion:
    """Shape-compatible with `agents.ollama.OllamaCompletion`."""
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0
    error: Optional[str] = None


# Alias so `from agents.anthropic_client import OllamaCompletion` works
# for code that wants to swap the import path one line at a time.
OllamaCompletion = AnthropicCompletion


def map_model(ollama_model: str) -> str:
    """Resolve a department-declared Ollama model id to an Anthropic one."""
    return MODEL_MAP.get(ollama_model, DEFAULT_ANTHROPIC_MODEL)


def list_models() -> list[str]:
    """Return the set of Anthropic model ids we route to. Not a live API
    call — Anthropic doesn't expose a public listing endpoint, and the
    daemon doesn't need one. Used by --status output."""
    return sorted({DEFAULT_ANTHROPIC_MODEL, *MODEL_MAP.values()})


def is_running() -> bool:
    """The 'service' is reachable if we have an API key. We deliberately
    don't ping Anthropic on every cycle — that wastes a request per
    minute. The daemon learns about an invalid key when a real call
    returns 401, which is logged like any other model error."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def complete(
    model: str,
    system: str,
    prompt: str,
    *,
    temperature: float = 0.2,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_tokens: int = 4096,
) -> AnthropicCompletion:
    """One non-streaming completion against Anthropic's /messages API.

    Returns an AnthropicCompletion with the full reply, or an envelope
    with `error` set on any failure (network, bad key, rate limit,
    bad response shape). Never raises — the daemon must keep running.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return AnthropicCompletion(
            text="", model=model,
            error="ANTHROPIC_API_KEY not set",
        )

    resolved = map_model(model)
    payload = {
        "model": resolved,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }

    t0 = time.time()
    try:
        resp = httpx.post(
            f"{ANTHROPIC_BASE}/messages",
            content=json.dumps(payload).encode("utf-8"),
            headers=headers,
            timeout=timeout,
        )
    except httpx.HTTPError as ex:
        return AnthropicCompletion(
            text="", model=resolved,
            elapsed_ms=int((time.time() - t0) * 1000),
            error=f"Anthropic unreachable: {ex}",
        )
    except Exception as ex:
        return AnthropicCompletion(
            text="", model=resolved,
            elapsed_ms=int((time.time() - t0) * 1000),
            error=f"{type(ex).__name__}: {ex}",
        )

    elapsed = int((time.time() - t0) * 1000)
    if resp.status_code >= 400:
        body = (resp.text or "")[:500]
        return AnthropicCompletion(
            text="", model=resolved, elapsed_ms=elapsed,
            error=f"HTTP {resp.status_code}: {body}",
        )

    try:
        data = resp.json()
    except Exception as ex:
        return AnthropicCompletion(
            text="", model=resolved, elapsed_ms=elapsed,
            error=f"bad json: {ex}",
        )

    # Anthropic returns content as a list of blocks. Concatenate every
    # text block (we don't use tools here so there's normally exactly one).
    blocks = data.get("content") or []
    text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    text = "".join(text_parts)

    usage = data.get("usage") or {}
    return AnthropicCompletion(
        text=text,
        model=resolved,
        prompt_tokens=int(usage.get("input_tokens") or 0),
        completion_tokens=int(usage.get("output_tokens") or 0),
        elapsed_ms=elapsed,
    )
