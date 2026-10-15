"""Shared bounded model/tool loop for BABOOM and native Workshop turns."""
from __future__ import annotations

import ast
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
import re
from typing import Callable, Mapping, Sequence


NO_TOOLS_MESSAGE = "this model can't use tools; pick one marked tools"
_STEP_OBSERVER = ContextVar("agentic_step_observer", default=None)


@contextmanager
def observe_steps(callback):
    """Disposable display subscription; no authority, queue or semantic store."""
    token = _STEP_OBSERVER.set(callback)
    try:
        yield
    finally:
        _STEP_OBSERVER.reset(token)


def publish_step(step):
    observer = _STEP_OBSERVER.get()
    if observer is not None:
        observer(dict(step))
_TEXT_CALL_ALIASES = {
    "check_programs": "host.ping",
}


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


def _available(tools: Mapping[str, object]) -> str:
    return ", ".join(sorted(tools))


def _tool_guidance(tools: Mapping[str, object]) -> str:
    return (
        "Available tools: %s\n"
        'When a tool is needed, write exactly one JSON object on one line: {"tool":"<name>","arguments":{}}\n'
        'Also accept native tool_calls when supported. Use exact tool names only. '
        "For host/program visibility, use host.ping; answer normally when no tool is needed; "
        "do not print a JSON tool call as visible chat text."
    ) % _available(tools)


def _with_tool_guidance(
    messages: Sequence[Mapping[str, object]], tools: Mapping[str, object],
) -> list[dict[str, object]]:
    transcript = [dict(row) for row in messages]
    guidance = _tool_guidance(tools)
    for row in transcript:
        if row.get("role") == "system":
            row["content"] = str(row.get("content") or "").rstrip() + "\n\n" + guidance
            return transcript
    return [{"role": "system", "content": guidance}, *transcript]


def _failed_result(value: object) -> bool:
    if value is False or value is None:
        return True
    if not isinstance(value, Mapping):
        return False
    status = str(value.get("status") or "").casefold()
    return (
        value.get("ok") is False
        or value.get("uncertain") is True
        or status in {"failed", "refused", "denied", "error", "unavailable"}
    )


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


def _json_objects(text: str):
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, Mapping):
            yield value, start, start + end


_SPECIAL_TOKEN_CALL = re.compile(
    r"<\|tool_call_start\|>\s*(\[[\s\S]*?\])\s*<\|tool_call_end\|>"
)


def _literal(node: ast.AST) -> object:
    return ast.literal_eval(node)


def _python_call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _python_call_name(node.value)
        return ("%s.%s" % (parent, node.attr)) if parent else node.attr
    return None


def _special_token_calls(text: str):
    for match in _SPECIAL_TOKEN_CALL.finditer(text):
        try:
            parsed = ast.parse(match.group(1), mode="eval")
        except SyntaxError:
            continue
        if not isinstance(parsed.body, ast.List):
            continue
        for item in parsed.body.elts:
            if not isinstance(item, ast.Call):
                continue
            raw_name = _python_call_name(item.func)
            if not raw_name:
                continue
            try:
                args: dict[str, object] = {}
                if len(item.args) == 1:
                    value = _literal(item.args[0])
                    args = dict(value) if isinstance(value, Mapping) else {"value": value}
                elif item.args:
                    args = {"args": [_literal(arg) for arg in item.args]}
                for keyword in item.keywords:
                    if not keyword.arg:
                        raise ValueError("expanded kwargs are not accepted")
                    args[keyword.arg] = _literal(keyword.value)
            except (ValueError, TypeError):
                continue
            yield raw_name, args, match.start(), match.end()


def _normalize_name(name: str, tools: Mapping[str, object]) -> str:
    if name in tools:
        return name
    alias = _TEXT_CALL_ALIASES.get(name)
    if alias in tools:
        return alias
    return name


def _arguments(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = {"_raw": value}
    if not isinstance(value, Mapping):
        value = {"value": value}
    return dict(value)


def _text_call(
    answer: object, tools: Mapping[str, object],
) -> tuple[dict[str, object] | None, str, str | None]:
    text = _text(answer)
    if not text:
        return None, "", None
    for requested, args, start, end in _special_token_calls(text):
        name = _normalize_name(requested.strip(), tools)
        stripped = (text[:start] + text[end:]).strip()
        if name not in tools:
            return None, stripped, requested
        return {"id": "text_call_0", "name": name, "arguments": args}, stripped, None
    for obj, start, end in _json_objects(text):
        has_named_parameters = "name" in obj and ("parameters" in obj or "arguments" in obj)
        raw_name = obj.get("tool") if isinstance(obj.get("tool"), str) else (
            obj.get("name") if has_named_parameters else None
        )
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        requested = raw_name.strip()
        name = _normalize_name(requested, tools)
        args = _arguments(obj.get("arguments", obj.get("parameters", {})))
        if requested == "check_programs" and not args:
            args = {"probe": "programs"}
        stripped = (text[:start] + text[end:]).strip()
        if name not in tools:
            return None, stripped, requested
        return {"id": "text_call_0", "name": name, "arguments": args}, stripped, None
    return None, text, None


def _strip_text_call_blocks(text: str) -> str:
    cleaned = str(text or "")
    for match in reversed(list(_SPECIAL_TOKEN_CALL.finditer(cleaned))):
        cleaned = cleaned[:match.start()] + cleaned[match.end():]
    for obj, start, end in reversed(list(_json_objects(cleaned))):
        has_named_parameters = "name" in obj and ("parameters" in obj or "arguments" in obj)
        if isinstance(obj.get("tool"), str) or (has_named_parameters and isinstance(obj.get("name"), str)):
            cleaned = cleaned[:start] + cleaned[end:]
    return cleaned.strip()


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


def _stopped_by_user(steps: Sequence[Mapping[str, object]], model_turns: int) -> dict[str, object]:
    return {"answer": "Stopped by you", "steps": list(steps),
            "model_turns": model_turns, "stopped": True}


def run_agentic_tool_loop(
    model_turn: Callable[[Sequence[Mapping[str, object]], Sequence[Mapping[str, object]]], object],
    tools: Mapping[str, ToolSpec],
    messages: Sequence[Mapping[str, object]],
    *,
    max_steps: int = 12,
    model_supports_tools: bool = True,
    grant_checker: Callable[[str, Mapping[str, object]], bool] | None = None,
    is_halted: Callable[[], bool] | None = None,
    halt_generation: Callable[[], object] | None = None,
) -> dict[str, object]:
    if type(max_steps) is not int or not 1 <= max_steps <= 32:
        raise ValueError("agentic loop step cap must be 1..32")
    if not model_supports_tools:
        return {"answer": NO_TOOLS_MESSAGE, "steps": [], "model_turns": 0, "stopped": False}
    transcript = _with_tool_guidance(messages, tools)
    schemas = [_tool_schema(name) for name in sorted(tools)]
    steps: list[dict[str, object]] = []
    halted = is_halted or (lambda: False)
    generation = halt_generation or (lambda: None)
    unknown_retry_used = False
    for turn in range(1, max_steps + 1):
        turn_generation = generation()
        if halted():
            return _stopped_by_user(steps, turn - 1)
        answer = model_turn(tuple(transcript), tuple(schemas))
        if halted() or generation() != turn_generation:
            return _stopped_by_user(steps, turn)
        calls = _calls(answer)
        assistant_text = _strip_text_call_blocks(_text(answer))
        if not calls:
            text_call, assistant_text, unknown_tool = _text_call(answer, tools)
            if unknown_tool is not None:
                if unknown_retry_used:
                    transcript.append({
                        "role": "system",
                        "content": "answer in plain words; do not print a JSON tool call",
                    })
                else:
                    transcript.append({
                        "role": "system",
                        "content": "unknown tool %s; available: %s" % (unknown_tool, _available(tools)),
                    })
                    unknown_retry_used = True
                continue
            if text_call is not None:
                calls = [text_call]
        if not calls:
            return {"answer": assistant_text, "steps": steps, "model_turns": turn, "stopped": False}
        transcript.append({"role": "assistant", "content": assistant_text, "tool_calls": calls})
        for call in calls:
            if halted():
                return _stopped_by_user(steps, turn)
            name = str(call["name"])
            args = dict(call["arguments"])
            publish_step({"tool": name, "status": "running", "summary": ""})
            spec = tools.get(name)
            if spec is None:
                payload = {"ok": False, "status": "refused", "error": "tool is not allowed"}
                step = {"tool": name, "args": args, "status": "refused", "ok": False,
                        "summary": payload["error"]}
            elif spec.mutates and (grant_checker is None or grant_checker(name, args) is not True):
                payload = {"ok": False, "status": "refused", "error": "approval grant required. Retry."}
                step = {"tool": name, "args": args, "status": "refused", "ok": False,
                        "summary": payload["error"]}
            else:
                try:
                    result = spec.run(name, args)
                    failed_status = (
                        isinstance(result, Mapping)
                        and str(result.get("status") or "").casefold() in {"failed", "refused", "uncertain"}
                    )
                    if isinstance(result, Mapping) and (
                        result.get("ok") is False or result.get("uncertain") is True or failed_status
                    ):
                        payload = dict(result)
                        payload.setdefault("status", "failed")
                        step = {"tool": name, "args": args, "status": str(payload["status"]),
                                "ok": False,
                                "summary": str(payload.get("error") or payload.get("status"))[:220]}
                    else:
                        payload = {"ok": True, "status": "ok", "result": result}
                        step = {"tool": name, "args": args, "status": "ok", "ok": True,
                                "summary": _summary(result)}
                    if step["ok"] is True and spec.mutates and spec.verify is not None:
                        readback = spec.verify(name, args, result)
                        payload["readback"] = readback
                        step["readback"] = _summary(readback)
                        if _failed_result(readback):
                            payload["ok"] = False
                            payload["status"] = "failed"
                            payload["error"] = "verification failed: " + _summary(readback)
                            step["ok"] = False
                            step["status"] = "failed"
                            step["summary"] = payload["error"][:220]
                except Exception as exc:  # noqa: BLE001 - model receives refusal text, not traceback
                    payload = {"ok": False, "status": "refused", "error": str(exc)}
                    step = {"tool": name, "args": args, "status": "refused", "ok": False,
                            "summary": str(exc)[:220]}
            steps.append(step)
            # Only founder-safe display fields cross the companion boundary.
            publish_step({key: step[key] for key in ("tool", "status", "summary")})
            if step["ok"] is True and (halted() or generation() != turn_generation):
                return _stopped_by_user(steps, turn)
            transcript.append(_tool_message(str(call["id"]), payload))
    return {"answer": "stopped after %d steps" % max_steps, "steps": steps,
            "model_turns": max_steps, "stopped": True}


__all__ = ["NO_TOOLS_MESSAGE", "ToolSpec", "run_agentic_tool_loop"]
