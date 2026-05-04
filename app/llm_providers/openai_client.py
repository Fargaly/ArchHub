"""OpenAI provider client.

Same interface as AnthropicClient: stream_completion(...) → dict.
Translates between OpenAI's tool-use format and ArchHub's internal shape.
"""
from __future__ import annotations

import json
from typing import Any, Callable


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
    ) -> dict:
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
            oa_messages.append({"role": role, "content": m.get("content", "")})

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
