"""OpenAI provider client.

Same interface as AnthropicClient: stream_completion(...) → dict.
Translates between OpenAI's tool-use format and ArchHub's internal shape.
Supports multimodal input via OpenAI's image_url content blocks: any
message with a non-empty `images` list is sent as a content array so
GPT-4o (and any OpenRouter route to Claude / Gemini) can see attached
sketches and screenshots.
"""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable, Optional


def _encode_image_url(path: str) -> Optional[dict]:
    """Read an image file and return an OpenAI-shape image_url block."""
    try:
        data = Path(path).read_bytes()
    except Exception:
        return None
    media_type, _ = mimetypes.guess_type(path)
    if not media_type or not media_type.startswith("image/"):
        media_type = "image/png"
    b64 = base64.b64encode(data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64}"},
    }


class OpenAIClient:
    def __init__(self, api_key: str):
        try:
            from openai import OpenAI
        except ImportError as ex:
            raise RuntimeError(
                "The 'openai' package isn't installed. Run: pip install openai"
            ) from ex
        self._client = OpenAI(api_key=api_key)

    def stream_completion(
        self,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        on_chunk: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
    ) -> dict:
        on_reasoning = on_reasoning or (lambda _: None)
        oa_messages: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "tool":
                for tr in m.get("tool_results", []):
                    oa_messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": json.dumps(tr["content"]),
                    })
                continue
            if role == "assistant" and m.get("_tool_calls"):
                oa_messages.append({
                    "role": "assistant",
                    "content": m.get("content", "") or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("input") or {}),
                            },
                        } for tc in m["_tool_calls"]
                    ],
                })
                continue

            content = m.get("content", "")
            images = m.get("images") or []
            if images:
                # Multimodal content array: text first, then any images.
                # OpenAI accepts either order but text-first matches what
                # the model is trained to expect for "given this prompt,
                # look at these images" framing.
                parts: list[dict] = []
                if isinstance(content, str) and content:
                    parts.append({"type": "text", "text": content})
                for path in images:
                    block = _encode_image_url(path)
                    if block is not None:
                        parts.append(block)
                if parts:
                    oa_messages.append({"role": role, "content": parts})
                    continue

            oa_messages.append({"role": role, "content": content})

        kwargs: dict[str, Any] = dict(model=model, messages=oa_messages, stream=True)
        if tools:
            kwargs["tools"] = tools

        text_accum: list[str] = []
        tool_calls: dict[int, dict] = {}     # index -> partial tool call
        finish_reason = "stop"

        for chunk in self._client.chat.completions.create(**kwargs):
            if not chunk.choices: continue
            choice = chunk.choices[0]
            delta = choice.delta

            if delta and delta.content:
                text_accum.append(delta.content)
                on_chunk(delta.content)
            # OpenAI o1/o3/GPT-5 emit reasoning summaries on a separate
            # delta field. Stream those to on_reasoning so the chat
            # surface shows model thinking without polluting the answer.
            if delta:
                reasoning = getattr(delta, "reasoning", None)
                if reasoning:
                    try:
                        on_reasoning(reasoning if isinstance(reasoning, str)
                                     else getattr(reasoning, "content", "") or "")
                    except Exception:
                        pass

            if delta and getattr(delta, "tool_calls", None):
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    bucket = tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc_delta.id:
                        bucket["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            bucket["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            bucket["args"] += tc_delta.function.arguments

            if choice.finish_reason:
                finish_reason = choice.finish_reason

        text = "".join(text_accum)
        if finish_reason == "tool_calls" and tool_calls:
            calls = []
            for tc in tool_calls.values():
                try:
                    parsed = json.loads(tc["args"] or "{}")
                except json.JSONDecodeError:
                    parsed = {}
                calls.append({"id": tc["id"], "name": tc["name"], "input": parsed})
            return {"type": "tool_use", "text": text, "tool_calls": calls}
        return {"type": "final", "text": text}
