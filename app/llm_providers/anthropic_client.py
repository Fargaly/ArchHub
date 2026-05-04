"""Anthropic provider client.

Uses the official `anthropic` SDK. Streams text deltas and surfaces tool-use
blocks in the format LLMRouter expects.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional


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
    ) -> dict:
        """Run one streaming turn.

        Returns:
            { "type": "final", "text": "..." }
            or
            { "type": "tool_use", "text": "...", "tool_calls": [...] }
        """
        # Translate ArchHub-shape messages → Anthropic shape
        anth_messages = self._adapt_messages(messages)

        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=4096,
            system=system,
            messages=anth_messages,
        )
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
            if isinstance(content, str):
                out.append({"role": role, "content": content})
            else:
                out.append({"role": role, "content": content})
        return out
