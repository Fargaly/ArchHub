"""Google Gemini backend for cloud-deployed departments.

Drop-in alongside `anthropic_client.py` + `openai_client.py`. Selected
via env `ARCHHUB_AGENTS_BACKEND=gemini`.

Strengths: huge context window (2M tokens for 2.5 Pro), strong
multimodal, very cheap Flash tier (~$0.10/M input). Good fit for
the docs + telemetry departments that summarise long log files.

REST-only via httpx — no `google-generativeai` SDK install (keeps the
container slim).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT_SECONDS = 600

# Ollama model id -> Gemini model id. Flash for grunt work; Pro for
# anything that touches a large file or needs strong reasoning.
MODEL_MAP: dict[str, str] = {
    "qwen2.5-coder:7b":  "gemini-2.5-flash",
    "qwen2.5-coder:14b": "gemini-2.5-pro",
    "llama3.2:3b":       "gemini-2.5-flash",
    "llama3.1:latest":   "gemini-2.5-flash",
    "llama3.1:8b":       "gemini-2.5-flash",
    "command-r7b":       "gemini-2.5-flash",
    "command-r:latest":  "gemini-2.5-flash",
    "deepseek-r1:8b":    "gemini-2.5-pro",
    "deepseek-r1:14b":   "gemini-2.5-pro",
}
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


@dataclass
class GeminiCompletion:
    """Shape-compatible with agents.ollama.OllamaCompletion."""
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _api_key() -> Optional[str]:
    return (
        os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or None
    )


def complete(*, model: str, system: str, user: str,
              temperature: float = 0.2,
              max_tokens: int = 4096,
              timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> GeminiCompletion:
    key = _api_key()
    if not key:
        raise RuntimeError(
            "GOOGLE_API_KEY / GEMINI_API_KEY not set; "
            "cannot run Gemini backend."
        )
    mapped = MODEL_MAP.get(model, DEFAULT_GEMINI_MODEL)

    body: dict = {
        "contents": [
            {"role": "user", "parts": [{"text": user}]}
        ],
        "generationConfig": {
            "temperature": float(temperature),
            "maxOutputTokens": int(max_tokens),
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    url = f"{GEMINI_BASE}/models/{mapped}:generateContent?key={key}"
    started = time.time()
    with httpx.Client(timeout=timeout_seconds) as cx:
        resp = cx.post(url, headers={"Content-Type": "application/json"},
                        json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"Gemini {resp.status_code}: {resp.text[:300]}")
    payload = resp.json()
    cands = payload.get("candidates") or []
    parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
    text = "".join(p.get("text", "") for p in parts).strip()
    usage = payload.get("usageMetadata") or {}
    return GeminiCompletion(
        text=text,
        model=mapped,
        prompt_tokens=int(usage.get("promptTokenCount") or 0),
        completion_tokens=int(usage.get("candidatesTokenCount") or 0),
    )


def list_models() -> list[str]:
    return list(set(MODEL_MAP.values())) + [DEFAULT_GEMINI_MODEL]


def is_configured() -> bool:
    return bool(_api_key())
