"""Shared bounded model/tool loop for BABOOM and native Workshop turns."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Mapping, Sequence


NO_TOOLS_MESSAGE = "this model can't use tools; pick one marked tools"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    run: Callable[[str, Mapping[str, object]], object]
    mutates: bool = False
    verify: Callable[[str, Mapping[str, object], object], object] | None = None


def _tool_schema(name: str) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "ArchHub admitted tool: " + name,
            "parameters": {"type": "object", "additionalProperties": True},
        },
    }


def _jsonable(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _summary(value: object, limit: int = 220) -> str:
    text = value if isinstance(value, str) else _jsonable(value)
    text = " ".join(str(text).split())
    return text[:limit]


def _calls(answer: object) -> list[dict[str, object]]:
    if not isinstance(answer, Mapping):
        return []
    calls = answer.get("tool_calls")
    if not isinstance(calls, (list, tuple)):
        return []
    cleaned = []
    for index, call in enumerate(calls):
        if not isinstance(call, Mapping):
            continue
        name = call.get("name")
        args = call.get("arguments", {})
        if not isinstance(name, str) or not name:
            continue
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"_raw": args}
        if not isinstance(args, Mapping):
            args = {"value": args}
        ident = call.get("id")
        cleaned.append({"id": ident if isinstance(ident, str) and ident else "call_%d" % index,
                        "name": name, "arguments": dict(args)})
    return cleaned


def _text(answer: object) -> str:
    if isinstance(answer, Mapping):
        for key in ("answer", "text", "content"):
            value = answer.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(answer, str):
        return answer.strip()
    return ""


def _tool_message(call_id: str, payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": _jsonable(payload),
    }


def run_agentic_tool_loop(
    model_turn: Callable[[Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]], object],
    tools: Mapping[str, ToolSpec],
    messages: Sequence[Mapping[str, object]],
    *,
    max_steps: int = 12,
    model_supports_tools: bool = True,
    grant_checker: Callable[[str, Mapping[str, object]], bool] | None = None,
) -> dict[str, object]:
    if type(max_steps) is not int or not 1 <= max_steps <= 32:
        raise ValueError("agentic loop step cap must be 1..32")
    if not model_supports_tools:
        return {"answer": NO_TOOLS_MESSAGE, "steps": [], "model_turns": 0, "stopped": False}
    transcript = [dict(row) for row in messages]
    schemas = [_tool_schema(name) for name in sorted(tools)]
    steps: list[dict[str, object]] = []
    for turn in range(1, max_steps + 1):
        answer = model_turn(tuple(transcript), tuple(schemas))
        calls = _calls(answer)
        if not calls:
            return {"answer": _text(answer), "steps": steps, "model_turns": turn, "stopped": False}
        transcript.append({"role": "assistant", "content": _text(answer), "tool_calls": calls})
        for call in calls:
            name = str(call["name"])
            args = dict(call["arguments"])
            spec = tools.get(name)
            if spec is None:
                payload = {"ok": False, "status": "refused", "error": "tool is not allowed"}
                step = {"tool": name, "args": args, "status": "refused", "ok": False,
                        "summary": payload["error"]}
            elif spec.mutates and (grant_checker is None or grant_checker(name, args) is not True):
                payload = {"ok": False, "status": "refused", "error": "approval grant required"}
                step = {"tool": name, "args": args, "status": "refused", "ok": False,
                        "summary": payload["error"]}
            else:
                try:
                    result = spec.run(name, args)
                    payload = {"ok": True, "status": "ok", "result": result}
                    step = {"tool": name, "args": args, "status": "ok", "ok": True,
                            "summary": _summary(result)}
                    if spec.mutates and spec.verify is not None:
                        readback = spec.verify(name, args, result)
                        payload["readback"] = readback
                        step["readback"] = _summary(readback)
                except Exception as exc:  # noqa: BLE001 - model receives refusal text, not traceback
                    payload = {"ok": False, "status": "refused", "error": str(exc)}
                    step = {"tool": name, "args": args, "status": "refused", "ok": False,
                            "summary": str(exc)[:220]}
            steps.append(step)
            transcript.append(_tool_message(str(call["id"]), payload))
    return {"answer": "stopped after %d steps" % max_steps, "steps": steps,
            "model_turns": max_steps, "stopped": True}


__all__ = ["NO_TOOLS_MESSAGE", "ToolSpec", "run_agentic_tool_loop"]
