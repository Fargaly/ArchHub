"""Minimal Ollama HTTP client for the departments.

Separate from `app/llm_providers/ollama_client.py` because:

  * Departments don't need streaming — they batch a prompt, wait for
    the full reply, write it to disk, move on. Streaming adds noise
    when the agents run unattended in a daemon.
  * Departments don't use tool-calling. The output is plain text
    (Markdown / code / YAML) parsed by the dispatcher.
  * Keeping department code separate from the desktop-app provider
    layer means changes here can't break the user-facing chat path.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


OLLAMA_BASE = "http://localhost:11434"
DEFAULT_TIMEOUT_SECONDS = 600   # generous; some models on CPU take time


@dataclass
class OllamaCompletion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0
    error: Optional[str] = None


def list_models() -> list[str]:
    """Return the names of every model currently pulled in Ollama."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def is_running() -> bool:
    """Cheap probe — returns True if Ollama responds within 1.5s."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=1.5) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def complete(
    model: str,
    system: str,
    prompt: str,
    *,
    temperature: float = 0.2,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> OllamaCompletion:
    """One non-streaming completion. Returns an OllamaCompletion with
    the full reply or an `error` field set on failure."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": float(temperature)},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as ex:
        return OllamaCompletion(
            text="", model=model,
            elapsed_ms=int((time.time() - t0) * 1000),
            error=f"Ollama unreachable: {ex}",
        )
    except Exception as ex:
        return OllamaCompletion(
            text="", model=model,
            elapsed_ms=int((time.time() - t0) * 1000),
            error=f"{type(ex).__name__}: {ex}",
        )

    text = ((data.get("message") or {}).get("content")) or ""
    return OllamaCompletion(
        text=text,
        model=model,
        prompt_tokens=int(data.get("prompt_eval_count") or 0),
        completion_tokens=int(data.get("eval_count") or 0),
        elapsed_ms=int((time.time() - t0) * 1000),
    )
