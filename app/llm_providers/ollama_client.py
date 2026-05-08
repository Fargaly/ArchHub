"""Ollama client — runs local models via http://localhost:11434.

Why this file is more complex than a thin HTTP wrapper: many open-weight
models (llama3.1, mistral, qwen3) only *partially* honour the OpenAI-style
tool-calling protocol. They sometimes emit the tool call as a JSON object
inside the assistant's text content instead of in the structured
`message.tool_calls` field. This module includes a salvage path that detects
and extracts those text-embedded tool calls so ArchHub can still run them
as real tool invocations rather than dumping the JSON into the chat.
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from typing import Callable, Optional

OLLAMA_BASE = "http://localhost:11434"


# Matches a JSON object that looks like a tool call (top-level "name" + "arguments"
# OR "tool_use" wrapper). Greedy enough to capture nested braces in arguments.
_TOOL_CALL_TEXT_RE = re.compile(
    r'\{(?:[^{}]|\{[^{}]*\})*?"(?:name|tool_name)"\s*:\s*"[^"]+"'
    r'(?:[^{}]|\{[^{}]*\})*?\}',
    re.DOTALL,
)


def _split_think(delta: str, state: dict):
    """Split a streaming chunk into (kind, piece) tuples where kind is
    'text' (goes to on_chunk) or 'reason' (goes to on_reasoning).
    Handles <think>...</think> tags that may straddle multiple chunks
    via the persistent `state` dict (keys: in_think:bool, buf:str)."""
    OPEN, CLOSE = "<think>", "</think>"
    text = (state.get("buf") or "") + (delta or "")
    state["buf"] = ""
    while text:
        if state["in_think"]:
            i = text.find(CLOSE)
            if i < 0:
                if text.endswith("<") or text.endswith("</") or text.endswith("</think")[:len(text)]:
                    state["buf"] = text
                    return
                yield "reason", text
                return
            yield "reason", text[:i]
            text = text[i + len(CLOSE):]
            state["in_think"] = False
        else:
            i = text.find(OPEN)
            if i < 0:
                # Could be a partial '<' / '<t' / '<th'... at end —
                # buffer to avoid emitting raw tag characters.
                tail = text[-len(OPEN):]
                if any(OPEN.startswith(text[k:]) for k in
                       range(max(0, len(text) - len(OPEN)), len(text))) and "<" in tail:
                    cut = text.rfind("<")
                    if cut >= 0 and cut > len(text) - len(OPEN):
                        if text[:cut]:
                            yield "text", text[:cut]
                        state["buf"] = text[cut:]
                        return
                yield "text", text
                return
            if i > 0:
                yield "text", text[:i]
            text = text[i + len(OPEN):]
            state["in_think"] = True


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
        on_reasoning: Callable[[str], None] | None = None,
    ) -> tuple[str, list[dict]]:
        on_reasoning = on_reasoning or (lambda _: None)
        # Reasoning splitter state — kept across chunks so a <think>
        # straddling two delta packets is still parsed correctly.
        _think_state = {"in_think": False, "buf": ""}
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
                        # Split <think>...</think> reasoning tags out of
                        # the answer stream — DeepSeek R1 / qwen3-think
                        # / etc. emit chain-of-thought inside these
                        # tags. Route those to on_reasoning so the UI
                        # renders them in the dim italic Reasoning
                        # block instead of the answer body.
                        for kind, piece in _split_think(delta, _think_state):
                            if kind == "text":
                                full_text += piece
                                on_chunk(piece)
                            else:
                                try:
                                    on_reasoning(piece)
                                except Exception:
                                    pass

                    # Tool calls (Ollama format — the well-behaved path)
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

        # Salvage path — many open models emit the tool call as JSON inside
        # the assistant's text content. If structured tool_calls didn't fire
        # but the text smells like a tool call, parse it out and treat it
        # as a real invocation. Strip the JSON from the displayed text so
        # the user never sees raw machine-protocol fragments.
        if tools and not tool_calls:
            salvaged, cleaned_text = _salvage_text_tool_calls(full_text, tools)
            if salvaged:
                tool_calls.extend(salvaged)
                full_text = cleaned_text

        return full_text, tool_calls


def _salvage_text_tool_calls(
    text: str, tool_schemas: list[dict],
) -> tuple[list[dict], str]:
    """Find tool-call-looking JSON inside `text`, return (calls, cleaned_text).

    Recognises three common emission shapes used by open-weight models:

      {"name": "tool_x", "arguments": {...}}                      — OpenAI style
      {"tool_name": "tool_x", "arguments": {...}}                 — variant
      {"tool_use": {"name": "tool_x", "input": {...}}}            — Anthropic style

    Only call names that match a tool the model was actually offered are
    accepted; anything else is left in the text so chat-relevant JSON the
    model wanted to display (rare) is preserved.
    """
    if not text or not text.strip():
        return [], text

    valid_names = {
        (t.get("name") or t.get("function", {}).get("name") or "")
        for t in (tool_schemas or [])
    }
    valid_names.discard("")
    if not valid_names:
        return [], text

    salvaged: list[dict] = []
    spans_to_strip: list[tuple[int, int]] = []

    # Pass 1: brace-balanced scan to find candidate JSON objects.
    candidates = list(_iter_balanced_braces(text))
    for start, end in candidates:
        blob = text[start:end]
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        call = _extract_tool_call(obj, valid_names)
        if call is None:
            continue
        salvaged.append({
            "id": f"ollama_text_{len(salvaged)}",
            "name": call["name"],
            "input": call.get("input") or call.get("arguments") or {},
        })
        spans_to_strip.append((start, end))

    if not salvaged:
        return [], text

    # Strip salvaged JSON from displayed text, in reverse so indices stay valid.
    cleaned = text
    for start, end in sorted(spans_to_strip, reverse=True):
        cleaned = cleaned[:start] + cleaned[end:]
    return salvaged, cleaned.strip()


def _iter_balanced_braces(text: str):
    """Yield (start, end) of every balanced top-level {...} object in text."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                yield start, i + 1
                start = -1


def _extract_tool_call(obj, valid_names: set[str]) -> Optional[dict]:
    """Map a parsed JSON object onto {name, input/arguments} if it is a
    recognised tool-call shape AND its name is in valid_names. Else None."""
    if not isinstance(obj, dict):
        return None

    # Anthropic-style wrapper: {"tool_use": {"name": ..., "input": {...}}}
    inner = obj.get("tool_use")
    if isinstance(inner, dict):
        name = inner.get("name") or inner.get("tool_name")
        if name in valid_names:
            return {"name": name, "input": inner.get("input") or inner.get("arguments") or {}}

    name = obj.get("name") or obj.get("tool_name")
    if name in valid_names:
        return {"name": name, "input": obj.get("arguments") or obj.get("input") or {}}

    # Some models nest under "function": {"name": ..., "arguments": ...}
    fn = obj.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        if name in valid_names:
            args = fn.get("arguments") or {}
            # arguments sometimes arrive as a JSON-encoded string
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            return {"name": name, "input": args}
    return None
