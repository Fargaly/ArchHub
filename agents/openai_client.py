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

# Ollama model id -> OpenAI model id. v1.3.2 bumps to the GPT-5
# family (Apr 2026 release window). Codex variants get the code-
# oriented depts; gpt-5.4-mini covers cheap general work; gpt-5.5
# does heavier reasoning. The catch-all default is gpt-5.4-mini —
# meaningful gains over gpt-4o-mini at similar cost.
MODEL_MAP: dict[str, str] = {
    "qwen2.5-coder:7b":  "gpt-5.3-codex",       # newest dedicated codex
    "qwen2.5-coder:14b": "gpt-5.3-codex",
    "llama3.2:3b":       "gpt-5.4-mini",        # fast + cheap general
    "llama3.1:latest":   "gpt-5.4-mini",
    "llama3.1:8b":       "gpt-5.4-mini",
    "command-r7b":       "gpt-5.4-mini",
    "command-r:latest":  "gpt-5.4-mini",
    "deepseek-r1:8b":    "gpt-5.5",             # reasoning-heavy work
    "deepseek-r1:14b":   "gpt-5.5",
    # Direct GPT-5 family identity mappings — used when an Agent
    # subclass names a GPT model directly.
    "gpt-5.5":           "gpt-5.5",
    "gpt-5.5-pro":       "gpt-5.5-pro",
    "gpt-5.3-codex":     "gpt-5.3-codex",
}
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"


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

    # GPT-5+ Pro models use `max_completion_tokens` not `max_tokens`.
    # The non-reasoning models accept `temperature`; Pro / o-series do
    # not. Codex variants accept temperature but reward low values.
    is_pro = mapped.endswith("-pro") or "pro" in mapped.split("-")
    is_codex = "codex" in mapped
    is_gpt5_family = mapped.startswith("gpt-5")
    body: dict = {
        "model": mapped,
        "messages": [
            {"role": "system", "content": system or "You are a helpful agent."},
            {"role": "user",   "content": user},
        ],
    }
    if is_reasoning or is_pro:
        # o-series + GPT-5 Pro — no temperature param; reasoning_effort
        # optional. `max_completion_tokens` is the GPT-5 spelling.
        body["reasoning_effort"] = "low"
        body["max_completion_tokens"] = int(max_tokens)
    else:
        body["temperature"] = (0.1 if is_codex else float(temperature))
        if is_gpt5_family:
            body["max_completion_tokens"] = int(max_tokens)
        else:
            body["max_tokens"] = int(max_tokens)

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
