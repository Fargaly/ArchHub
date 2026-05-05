"""Ollama client — runs local models via http://localhost:11434."""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Callable, Optional

OLLAMA_BASE = "http://localhost:11434"


def list_local_models() -> list[str]:
    """Return model names currently pulled in Ollama. Empty list if Ollama not running."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=2) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


class OllamaClient:
    """Thin wrapper around Ollama's /api/chat endpoint."""

    def __init__(self):
        pass  # No API key needed

    def complete(
        self,
        system: str,
        history: list[dict],
        model: str,
        tools: list[dict],
        on_chunk: Callable[[str], None],
    ) -> tuple[str, list[dict]]:
        """
        Call Ollama chat API. Returns (full_text, tool_calls).
        tool_calls is a list of dicts with keys: id, name, input.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        for m in history:
            role = m.get("role", "user")

            # Tool result message — Ollama wants one message per result, content = JSON string
            if role == "tool":
                for tr in m.get("tool_results", []):
                    content_val = tr.get("content") or {}
                    messages.append({
                        "role": "tool",
                        "content": json.dumps(content_val) if not isinstance(content_val, str) else content_val,
                    })
                continue

            content = m.get("content", "")
            if isinstance(content, list):
                # Flatten multi-part content to text
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )

            # Assistant message that made tool calls — include tool_calls for Ollama
            if role == "assistant" and m.get("_tool_calls"):
                raw_calls = m["_tool_calls"]
                tool_calls_ollama = [
                    {"function": {"name": tc.get("name", ""), "arguments": tc.get("input") or {}}}
                    for tc in raw_calls
                ]
                messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls_ollama})
                continue

            messages.append({"role": role, "content": content})

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        # Ollama supports tools for some models (llama3.1+, mistral-nemo, etc.)
        if tools:
            payload["tools"] = tools

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        full_text = ""
        tool_calls: list[dict] = []

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = chunk.get("message", {})
                    delta = msg.get("content", "")
                    if delta:
                        full_text += delta
                        on_chunk(delta)

                    # Tool calls (Ollama format)
                    for tc in msg.get("tool_calls", []):
                        fn = tc.get("function", {})
                        tool_calls.append({
                            "id": f"ollama_{len(tool_calls)}",
                            "name": fn.get("name", ""),
                            "input": fn.get("arguments", {}),
                        })

                    if chunk.get("done"):
                        break
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Ollama not reachable at {OLLAMA_BASE}. Is Ollama running? ({e})"
            )

        return full_text, tool_calls
