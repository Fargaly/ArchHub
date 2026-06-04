"""Google Gemini provider — direct REST, no SDK dependency.

Implements the same surface the LLMRouter expects:
  stream_completion(model, system, messages, tools, on_chunk) -> dict
returning either:
  {"type": "final",     "text": "..."}
  {"type": "tool_use",  "text": "...", "tool_calls": [...]}

Uses Gemini's `generateContent` (non-streaming) for simplicity. on_chunk
is called once with the full text so the UI typing indicator clears the
same way it does for streamed providers.

Tool format: Gemini requires `function_declarations` wrapping the schema.
The tool_engine emits the unwrapped form for "google"; we wrap here and
re-fetch full input_schema from tool_engine.TOOLS so the tool definitions
include parameters Gemini needs.

Free tier: 60 req/min, 1M tokens/day for Gemini 2.5 Flash.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional


_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def _encode_image_part(path: str) -> Optional[dict]:
    try:
        data = Path(path).read_bytes()
    except Exception:
        return None
    mime, _ = mimetypes.guess_type(path)
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    return {
        "inlineData": {
            "mimeType": mime,
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


class GoogleClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

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
        on_reasoning = on_reasoning or (lambda _: None)
        gemini_contents = self._adapt_messages(messages)
        gen_cfg: dict[str, Any] = {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
        }
        # Caller-supplied sampling params (node.config) override the
        # defaults above; None keeps them so the chat path is unchanged.
        if temperature is not None:
            try:
                gen_cfg["temperature"] = max(0.0, min(2.0, float(temperature)))
            except (TypeError, ValueError):
                pass
        if max_tokens is not None:
            try:
                gen_cfg["maxOutputTokens"] = max(16, int(max_tokens))
            except (TypeError, ValueError):
                pass
        # Extended thinking — Gemini 2.5 series supports
        # thinkingConfig.thinkingBudget. Budget from Settings.
        try:
            from ai_behaviour import thinking_budget_tokens
            budget = thinking_budget_tokens()
        except Exception:
            budget = 0
        if budget > 0 and "2.5" in (model or ""):
            gen_cfg["thinkingConfig"] = {"thinkingBudget": int(budget)}
            # Thinking needs headroom above the budget; respect a larger
            # caller maxOutputTokens if one was supplied.
            gen_cfg["maxOutputTokens"] = max(8192, budget + 2048,
                                              int(gen_cfg["maxOutputTokens"]))
        body: dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": gen_cfg,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"function_declarations": _adapt_tools(tools)}]

        url = _API.format(model=model, key=self.api_key)
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:600]
            # Hand the error to LLMRouter's auth/quota detector by raising.
            raise RuntimeError(f"Gemini HTTP {e.code}: {err_body}") from e

        text, tool_calls = _parse_response(payload)
        if text:
            on_chunk(text)
        if tool_calls:
            return {"type": "tool_use", "text": text, "tool_calls": tool_calls}
        return {"type": "final", "text": text}

    def _adapt_messages(self, messages: list[dict]) -> list[dict]:
        """Adapt ArchHub message shape → Gemini contents.

        ArchHub uses TWO formats for tool round-tripping:
          (a) assistant message with `_tool_calls`
          (b) separate {"role":"tool","tool_results":[...]}
        Gemini wants assistant functionCall parts and `user`-role
        functionResponse parts (no separate "tool" role).
        """
        out = []
        for m in messages:
            mrole = m.get("role")
            if mrole == "tool":
                # Convert tool_results into a user-role message of
                # functionResponse parts. Gemini reads function results
                # as if they came from "user".
                parts: list[dict] = []
                for tr in (m.get("tool_results") or []):
                    content = tr.get("content")
                    # Gemini wants the response as a JSON-ish object;
                    # stringify dicts/lists, leave strings alone.
                    if isinstance(content, (dict, list)):
                        resp_value = content
                    else:
                        resp_value = {"result": str(content) if content is not None else ""}
                    parts.append({
                        "functionResponse": {
                            "name": tr.get("name") or "",
                            "response": resp_value if isinstance(resp_value, dict) else {"result": resp_value},
                        },
                    })
                if parts:
                    out.append({"role": "user", "parts": parts})
                continue

            role = "model" if mrole == "assistant" else "user"
            parts = []
            content = m.get("content") or ""
            if content:
                parts.append({"text": content})
            for img in (m.get("images") or []):
                p = _encode_image_part(img)
                if p:
                    parts.append(p)
            for tc in (m.get("_tool_calls") or []):
                parts.append({
                    "functionCall": {
                        "name": tc.get("name") or "",
                        "args": tc.get("input") or {},
                    },
                })
            if not parts:
                continue
            out.append({"role": role, "parts": parts})
        return out


def _adapt_tools(tools: list[dict]) -> list[dict]:
    from tool_engine import TOOLS as _TOOLS
    by_name = {t["name"]: t for t in _TOOLS}
    out = []
    for t in tools:
        spec = by_name.get(t.get("name"), {})
        params = spec.get("input_schema") or t.get("parameters") or {
            "type": "object", "properties": {}, "required": [],
        }
        params = _strip_for_gemini(params)
        out.append({
            "name": t.get("name") or spec.get("name") or "",
            "description": (t.get("description") or spec.get("description") or "")[:1024],
            "parameters": params,
        })
    return out


def _strip_for_gemini(schema: Any) -> Any:
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k in ("additionalProperties", "$schema", "definitions", "$defs",
                     "examples", "default"):
                continue
            out[k] = _strip_for_gemini(v)
        return out
    if isinstance(schema, list):
        return [_strip_for_gemini(x) for x in schema]
    return schema


def _parse_response(payload: dict) -> tuple[str, list[dict]]:
    import uuid as _u
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for cand in (payload.get("candidates") or []):
        content = cand.get("content") or {}
        for part in (content.get("parts") or []):
            if "text" in part:
                text_parts.append(part["text"] or "")
            fc = part.get("functionCall")
            if fc:
                tool_calls.append({
                    "id": _u.uuid4().hex[:16],
                    "name": fc.get("name") or "",
                    "input": fc.get("args") or {},
                })
    return ("".join(text_parts), tool_calls)
