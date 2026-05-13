"""OpenAI (ChatGPT / Codex / o-series) backend for cloud-deployed departments.

Drop-in alongside `anthropic_client.py`. Same `OllamaCompletion`-shape
envelope so callers stay unchanged. Selected via env
`ARCHHUB_AGENTS_BACKEND=openai`.

Why OpenAI as an alternate backend: GPT-4o-mini is cheaper than Haiku
for batch grunt work (~$0.15/M input vs $1/M for Haiku 4.5), and the
`o4-mini` reasoning model is strictly better than Haiku for code
patches when latency isn't a concern. Per-department override via
`ARCHHUB_AGENTS_BACKEND_<DEPT>` env var.

Codex note: OpenAI's old "Codex" is deprecated. Modern equivalent is
`gpt-4o-mini` for cheap completion + `o4-mini` for code reasoning.
We map "qwen2.5-coder" → `gpt-4o-mini` so cost stays low.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx


OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_TIMEOUT_SECONDS = 600

# Ollama model id -> OpenAI model id. Bumps:
#   - Code-oriented dept work goes to gpt-4o-mini (cheap + fast)
#   - Reasoning-heavy work goes to o4-mini (paid, slower, smarter)
MODEL_MAP: dict[str, str] = {
    "qwen2.5-coder:7b":  "gpt-4o-mini",
    "qwen2.5-coder:14b": "gpt-4o-mini",
    "llama3.2:3b":       "gpt-4o-mini",
    "llama3.1:latest":   "gpt-4o-mini",
    "llama3.1:8b":       "gpt-4o-mini",
    "command-r7b":       "gpt-4o-mini",
    "command-r:latest":  "gpt-4o-mini",
    "deepseek-r1:8b":    "o4-mini",
    "deepseek-r1:14b":   "o4-mini",
}
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


@dataclass
class OpenAICompletion:
    """Shape-compatible with agents.ollama.OllamaCompletion."""
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _api_key() -> Optional[str]:
    return os.environ.get("OPENAI_API_KEY") or None


def complete(*, model: str, system: str, user: str,
              temperature: float = 0.2,
              max_tokens: int = 4096,
              timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> OpenAICompletion:
    """Single non-streaming chat completion. Errors raise httpx.HTTPError
    or RuntimeError — callers in agents.base handle these."""
    key = _api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set; cannot run OpenAI backend.")
    mapped = MODEL_MAP.get(model, DEFAULT_OPENAI_MODEL)
    is_reasoning = mapped.startswith("o3") or mapped.startswith("o4")

    body: dict = {
        "model": mapped,
        "messages": [
            {"role": "system", "content": system or "You are a helpful agent."},
            {"role": "user",   "content": user},
        ],
    }
    if is_reasoning:
        # o-series — no temperature param; reasoning_effort optional.
        body["reasoning_effort"] = "low"
    else:
        body["temperature"] = float(temperature)
        body["max_tokens"]  = int(max_tokens)

    started = time.time()
    with httpx.Client(timeout=timeout_seconds) as cx:
        resp = cx.post(
            f"{OPENAI_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
            },
            json=body,
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"OpenAI {resp.status_code}: {resp.text[:300]}"
        )
    payload = resp.json()
    text = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    usage = payload.get("usage") or {}
    return OpenAICompletion(
        text=text.strip(),
        model=mapped,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )


def list_models() -> list[str]:
    """Return models the user is configured to call. Used by the
    selector + dashboard. No live API call (avoid spend on import)."""
    return list(set(MODEL_MAP.values())) + [DEFAULT_OPENAI_MODEL]


def is_configured() -> bool:
    return bool(_api_key())
