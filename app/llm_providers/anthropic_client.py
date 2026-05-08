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
        # is conservative: only opus-4 / sonnet-4 lineage. The thinking
        # budget is small so latency stays reasonable for simple turns;
        # the SDK + server allow more when needed.
        thinking_models = ("opus-4", "sonnet-4", "claude-4")
        thinking_enabled = any(t in (model or "").lower()
                                for t in thinking_models)

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=4096,
            system=system,
            messages=anth_messages,
        )
        if thinking_enabled:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}
            # Server requires max_tokens > thinking budget.
            kwargs["max_tokens"] = 8192
        if tools:
            kwargs["tools"] = tools

        text_accum: list[str] = []
        tool_calls: list[dict] = []
        current_tool: Optional[dict] = None
        current_tool_json: list[str] = []
        stop_reason = "end_turn"

        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                etype = getattr(event, "type", None)

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

        text = "".join(text_accum)
        if stop_reason == "tool_use" and tool_calls:
            return {"type": "tool_use", "text": text, "tool_calls": tool_calls}
        return {"type": "final", "text": text}

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
