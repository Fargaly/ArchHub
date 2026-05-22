"""LM Studio (local OpenAI-compatible) backend for departments.

Selected via env `ARCHHUB_AGENTS_BACKEND=lmstudio`.

Use when: you want zero per-token cost + privacy-bound work. The
local LM Studio server runs whatever model the user has loaded —
typically a quantised Qwen, Llama, or DeepSeek build sized to fit
the host's GPU.

Default URL is `http://localhost:1234/v1`. In the cloud deploy this
doesn't fire (no LM Studio on Fly.io) — set
`ARCHHUB_AGENTS_BACKEND=anthropic` for the cloud container.

OpenAI-compatible wire format → very thin client.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx


DEFAULT_LMSTUDIO_BASE = "http://localhost:1234/v1"
DEFAULT_TIMEOUT_SECONDS = 600

# Ollama model id -> LM Studio model id. LM Studio resolves any model
# string against whatever the user has loaded, so "auto" means
# "whichever is currently active". Departments that want a specific
# model can override via `ARCHHUB_AGENTS_BACKEND_<DEPT>_MODEL`.
MODEL_MAP: dict[str, str] = {
    "qwen2.5-coder:7b":  "auto",
    "qwen2.5-coder:14b": "auto",
    "llama3.2:3b":       "auto",
    "llama3.1:latest":   "auto",
    "llama3.1:8b":       "auto",
    "command-r7b":       "auto",
    "command-r:latest":  "auto",
    "deepseek-r1:8b":    "auto",
    "deepseek-r1:14b":   "auto",
}
DEFAULT_LMSTUDIO_MODEL = "auto"


@dataclass
class LMStudioCompletion:
    """Shape-compatible with agents.ollama.OllamaCompletion."""
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _base_url() -> str:
    return os.environ.get("LMSTUDIO_BASE_URL", DEFAULT_LMSTUDIO_BASE).rstrip("/")


def complete(*, model: str, system: str, user: str,
              temperature: float = 0.2,
              max_tokens: int = 4096,
              timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> LMStudioCompletion:
    mapped = MODEL_MAP.get(model, DEFAULT_LMSTUDIO_MODEL)
    body = {
        "model": mapped,
        "messages": [
            {"role": "system", "content": system or "You are a helpful agent."},
            {"role": "user",   "content": user},
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    with httpx.Client(timeout=timeout_seconds) as cx:
        try:
            resp = cx.post(
                f"{_base_url()}/chat/completions",
                headers={"Content-Type": "application/json"},
                json=body,
            )
        except httpx.HTTPError as ex:
            raise RuntimeError(
                f"LM Studio unreachable at {_base_url()}. "
                f"Start the LM Studio server + load a model. ({ex})"
            )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"LMStudio {resp.status_code}: {resp.text[:300]}"
        )
    payload = resp.json()
    text = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    usage = payload.get("usage") or {}
    return LMStudioCompletion(
        text=text.strip(),
        model=payload.get("model") or mapped,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )


def list_models() -> list[str]:
    """Hit GET /models on the local server to inventory what's loaded.
    Falls back to [] if the server isn't running."""
    try:
        with httpx.Client(timeout=1.5) as cx:
            r = cx.get(f"{_base_url()}/models")
        if r.status_code != 200:
            return []
        data = r.json().get("data") or []
        return [m.get("id") for m in data if m.get("id")]
    except Exception:
        return []


def is_configured() -> bool:
    """LM Studio doesn't need a key — but it does need to be running."""
    try:
        with httpx.Client(timeout=0.5) as cx:
            r = cx.get(f"{_base_url()}/models")
        return r.status_code == 200
    except Exception:
        return False
