"""Anthropic provider client.

Uses the official `anthropic` SDK. Streams text deltas and surfaces tool-use
blocks in the format LLMRouter expects. Supports multimodal input: any
message with a non-empty `images` list (file paths) is sent as a content
array containing image blocks plus the text, so Claude can see sketches
and screenshots the architect attaches in chat.
"""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable, Optional


def _encode_image_block(path: str) -> Optional[dict]:
    """Read an image file and return an Anthropic content block, or None
    if the file is unreadable. Falls back to image/png for unknown types."""
    try:
        data = Path(path).read_bytes()
    except Exception:
        return None
    media_type, _ = mimetypes.guess_type(path)
    if not media_type or not media_type.startswith("image/"):
        media_type = "image/png"
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


class AnthropicClient:
    def __init__(self, api_key: str):
        # Lazy-import so the app starts even if anthropic isn't installed yet.
        try:
            from anthropic import Anthropic
        except ImportError as ex:
            raise RuntimeError(
                "The 'anthropic' package isn't installed. "
                "Run: pip install anthropic"
            ) from ex
        self._client = Anthropic(api_key=api_key)

    def stream_completion(
        self,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        on_chunk: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Run one streaming turn.

        Returns:
            { "type": "final", "text": "..." }
            or
            { "type": "tool_use", "text": "...", "tool_calls": [...] }

        on_reasoning fires when the model emits an extended-thinking
        block — Anthropic surfaces these as content_block_delta events
        with delta.type == "thinking_delta". Models that don't have
        thinking enabled never call this.
        """
        on_reasoning = on_reasoning or (lambda _: None)

        # Translate ArchHub-shape messages → Anthropic shape
        anth_messages = self._adapt_messages(messages)

        # Enable extended thinking on models that support it. Detection
        # is conservative: only opus-4 / sonnet-4 lineage. Budget pulled
        # from Settings → AI Behaviour → thinking_effort. 0 = off,
        # caller disabled it.
        thinking_models = ("opus-4", "sonnet-4", "claude-4")
        thinking_capable = any(t in (model or "").lower()
                                for t in thinking_models)
        thinking_budget = 0
        if thinking_capable:
            try:
                from ai_behaviour import thinking_budget_tokens
                thinking_budget = thinking_budget_tokens()
            except Exception:
                thinking_budget = 0

        # Caller-supplied max_tokens (node.config) overrides the 4096
        # default; None keeps it. Clamped to a sane floor so a stray 0
        # can't produce an empty completion.
        _max_tokens = 4096
        if max_tokens is not None:
            try:
                _max_tokens = max(16, int(max_tokens))
            except (TypeError, ValueError):
                _max_tokens = 4096
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=_max_tokens,
            system=system,
            messages=anth_messages,
        )
        # Caller-supplied sampling temperature (node.config). Anthropic
        # accepts 0.0–1.0; clamp + skip on None so the chat default path
        # is byte-for-byte unchanged.
        if temperature is not None:
            try:
                kwargs["temperature"] = max(0.0, min(1.0, float(temperature)))
            except (TypeError, ValueError):
                pass
        if thinking_budget > 0:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
            # Server requires max_tokens > thinking budget. Respect a
            # larger caller max_tokens if they asked for one.
            kwargs["max_tokens"] = max(8192, thinking_budget + 2048,
                                        _max_tokens)
            # Extended thinking requires temperature unset (API rejects
            # temperature with thinking enabled) — drop any caller value.
            kwargs.pop("temperature", None)
        if tools:
            kwargs["tools"] = tools

        text_accum: list[str] = []
        tool_calls: list[dict] = []
        current_tool: Optional[dict] = None
        current_tool_json: list[str] = []
        stop_reason = "end_turn"
        # REAL token usage. Anthropic streams it: message_start carries
        # usage.input_tokens (prompt), message_delta carries the running
        # usage.output_tokens (completion). Captured here and returned so
        # LLMRouter folds the real numbers into its accumulator.
        prompt_tokens = 0
        completion_tokens = 0

        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                etype = getattr(event, "type", None)

                if etype == "message_start":
                    msg = getattr(event, "message", None)
                    u = getattr(msg, "usage", None) if msg else None
                    if u is not None:
                        prompt_tokens = int(getattr(u, "input_tokens", 0) or 0)
                        completion_tokens = int(getattr(u, "output_tokens", 0) or 0)

                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block is not None and getattr(block, "type", "") == "tool_use":
                        current_tool = {
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "input": {},
                        }
                        current_tool_json = []

                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    dtype = getattr(delta, "type", "") if delta else ""
                    if dtype == "text_delta":
                        text = getattr(delta, "text", "") or ""
                        text_accum.append(text)
                        on_chunk(text)
                    elif dtype == "thinking_delta":
                        # Extended-thinking content. Surface separately so
                        # the UI can render it dim-italic above the answer.
                        thought = getattr(delta, "thinking", "") or ""
                        if thought:
                            try:
                                on_reasoning(thought)
                            except Exception:
                                pass
                    elif dtype == "input_json_delta":
                        partial = getattr(delta, "partial_json", "") or ""
                        current_tool_json.append(partial)

                elif etype == "content_block_stop":
                    if current_tool is not None:
                        try:
                            current_tool["input"] = json.loads("".join(current_tool_json) or "{}")
                        except json.JSONDecodeError:
                            current_tool["input"] = {}
                        tool_calls.append(current_tool)
                        current_tool = None
                        current_tool_json = []

                elif etype == "message_delta":
                    delta = getattr(event, "delta", None)
                    sr = getattr(delta, "stop_reason", None) if delta else None
                    if sr:
                        stop_reason = sr
                    # Running output-token count lands on message_delta.usage.
                    u = getattr(event, "usage", None)
                    if u is not None:
                        ot = getattr(u, "output_tokens", None)
                        if ot is not None:
                            completion_tokens = int(ot or 0)

        text = "".join(text_accum)
        usage = {"prompt_tokens": prompt_tokens,
                 "completion_tokens": completion_tokens}
        if stop_reason == "tool_use" and tool_calls:
            return {"type": "tool_use", "text": text,
                    "tool_calls": tool_calls, "usage": usage}
        return {"type": "final", "text": text, "usage": usage}

    # ---- shape adapter ----------------------------------------------------

    def _adapt_messages(self, messages: list[dict]) -> list[dict]:
        out = []
        for m in messages:
            role = m["role"]
            if role == "tool":
                out.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": tr["tool_use_id"],
                         "content": json.dumps(tr["content"])}
                        for tr in m.get("tool_results", [])
                    ],
                })
                continue

            if role == "assistant" and m.get("_tool_calls"):
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["_tool_calls"]:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": tc.get("name"),
                        "input": tc.get("input") or {},
                    })
                out.append({"role": "assistant", "content": blocks})
                continue

            content = m.get("content", "")
            images = m.get("images") or []

            if images:
                # Multimodal: blocks of image(s) followed by the text. Image
                # blocks come first by Anthropic convention so Claude
                # acknowledges them before answering the prompt.
                blocks: list[dict] = []
                for path in images:
                    block = _encode_image_block(path)
                    if block is not None:
                        blocks.append(block)
                if isinstance(content, str) and content:
                    blocks.append({"type": "text", "text": content})
                if blocks:
                    out.append({"role": role, "content": blocks})
                    continue

            if isinstance(content, str):
                out.append({"role": role, "content": content})
            else:
                out.append({"role": role, "content": content})
        return out
