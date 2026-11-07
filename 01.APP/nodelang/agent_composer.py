"""Translate intent into editable graph changes without executing model effects.

Draft edits use the existing governed authoring operations. Execution needs the
separate user review and permission path; model output cannot approve itself.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Callable, Mapping

from .model_router import ModelRouteRefused, route_chat

# There is no built-in default model. One was hidden here for months
# ("anthropic/claude-sonnet-4.5"), so a question with no picked model was
# answered by a model nobody chose, on OpenRouter, for money. A default is
# DECLARED (ARCHHUB_AGENT_MODEL) or it does not exist; without one and without
# a pick, the composer says what to pick instead of guessing.
_DEFAULT_MODEL = os.environ.get("ARCHHUB_AGENT_MODEL", "").strip()
_NO_AGENT_NODE = object()
NO_MODEL_CHOSEN = (
    "No model chosen. Pick one in the studio header (the picker), or set "
    "ARCHHUB_AGENT_MODEL to a route such as openrouter/free."
)

_SYSTEM = """You operate the ArchHub node canvas. Reply with ONE JSON object:
{"actions":[...], "answer":"<one short sentence to the founder>"}
Each action is one of:
 {"op":"place","definition":"<catalogue name>","ref":"<local name>","x":<num>,"y":<num>,"title":"<optional name>","parameters":{"<declared interface name>":"<text>"}}
 {"op":"node","engine":"<pipeline engine name>","ref":"<local name>","title":"<name>","params":{"<parameter>":"<text>"},"x":<num>,"y":<num>}
 {"op":"work","ref":"<local name>","title":"<review task>","description":"<self-contained review input and requested outcome>","criteria":[{"criterion":"<observable result>","verification":"<how to check it>"}],"x":<num>,"y":<num>}
 {"op":"select","roots":[<node reference>, ...]}
 {"op":"group","ref":"<optional local name>"}
 {"op":"ungroup"}
 {"op":"set_property","root":<node reference>,"label":"<label>","value":"<text>"}
 {"op":"wire","source":<node reference>,"target":<node reference>,"source_port":"<declared name>","target_port":"<declared name>"}
 {"op":"open","root":<openable node reference>}
A node reference is an existing node id from the context or {"ref":"local name"}
declared by an earlier place/work/group action in THIS reply. Use unique local names
(letter followed by up to 63 letters, digits, underscores or hyphens). Never guess
the ids of nodes you are about to create. For example, place with ref "reader",
then wire source {"ref":"reader"} to another previously declared reference.
Use only declared connection ports. Port names may be omitted only when that
side has one port. Missing or ambiguous ports need user refinement, not invented
generic inputs or outputs. Only use definition names in the context. Answer in
the founder's language. Propose actions ONLY when the user asks to change the canvas.
A remark, question, note or anything to remember gets {"actions":[],"answer":"..."}.
If the request needs no canvas change, return
{"actions":[],"answer":"..."}.
Return at most 12 actions. These actions prepare an editable workflow; they do
not execute it. Never claim that effects ran. Execution follows user review and
approval through the separate execution controls."""

_SYSTEM += """
If the founder asks to use a tool, check what ArchHub can see, inspect the graph,
or verify host/program visibility, call an admitted tool before answering. Do not
turn a tool request into a canvas draft.
"""

_SYSTEM += """
Read the supplied authorised context before planning. For host visibility use
archhub-hosts hosts_state; it is read-only. No direct Brain, host, filesystem,
plan or Skill writes are available here. Prepare editable Work through JSON
actions and the existing shared Approve card instead."""

_SYSTEM += """
For a requested text review, analysis or planning task, use work: it creates
registered Work with an editable, wired requirements node that the Workshop can
prepare for model review. Include the actual input and requested result in its
description and explicit acceptance criteria with verification methods. Do not
use a generic catalogue card as a substitute for registered Work. Work is not an
implementation of arbitrary CAD, filesystem or other tools; do not claim those
operations exist or ran. If the needed input or intent is unclear, ask for it
instead of preparing execution. The user still reviews and approves the draft.
"""

_DRAFT_OPERATIONS = frozenset({
    "place", "node", "work", "select", "group", "ungroup", "set_property", "wire", "open", "run",
})

_CANVAS_OBJECT_RE = re.compile(
    r"\b(canvas|card|cards|graph|node|nodes|root|roots|selection|workflow|work|wire|wires)\b",
    re.IGNORECASE,
)
_CANVAS_IMPERATIVE_RE = re.compile(
    r"^\s*(?:please\s+|kindly\s+)?"
    r"(add|append|build|change|connect|create|delete|disconnect|draft|draw|edit|group|insert|"
    r"link|make|move|open|place|prepare|remove|rename|select|set|ungroup|unlink|wire)\b",
    re.IGNORECASE,
)


def _current_user_prompt(prompt: str) -> str:
    marker = "\n\nFounder says: "
    if marker in prompt:
        return prompt.rsplit(marker, 1)[1]
    return prompt


def _prompt_requests_canvas_change(prompt: str) -> bool:
    current = _current_user_prompt(prompt).strip()
    if not current or "?" in current:
        return False
    return bool(_CANVAS_IMPERATIVE_RE.search(current) and _CANVAS_OBJECT_RE.search(current))


def chosen_model_route(model: object) -> str:
    """Use the selected binding or an explicitly configured default, never an inferred provider."""
    chosen = (str(model or "")).strip() or _DEFAULT_MODEL
    if not chosen:
        raise ValueError(NO_MODEL_CHOSEN)
    return chosen




def _generation_options(generation: object) -> dict[str, object]:
    if generation is None:
        return {}
    if not isinstance(generation, Mapping):
        raise ValueError("agent generation options are invalid")
    options: dict[str, object] = {}
    if "max_tokens" in generation:
        max_tokens = int(generation["max_tokens"])
        if max_tokens < 1 or max_tokens > 32000:
            raise ValueError("agent max_tokens is outside the allowed range")
        options["max_tokens"] = max_tokens
    if "temperature" in generation:
        temperature = float(generation["temperature"])
        if not math.isfinite(temperature) or temperature < 0 or temperature > 2:
            raise ValueError("agent temperature is outside the allowed range")
        options["temperature"] = temperature
    if "top_p" in generation:
        top_p = float(generation["top_p"])
        if not math.isfinite(top_p) or top_p < 0 or top_p > 1:
            raise ValueError("agent top_p is outside the allowed range")
        options["top_p"] = top_p
    return options


def _answer_via(answer: Mapping[str, object]) -> dict[str, str]:
    family = str(answer.get("family") or "")
    model = str(answer.get("actual_model") or answer.get("model") or "")
    provider = str(answer.get("provider") or family)
    return {"family": family, "model": model, "provider": provider}


def _chat(
    prompt: str,
    context_block: str,
    model: str,
    *,
    before_dispatch=None,
    generation=None,
    host_reader=None,
    grant_checker=None,
    is_halted: Callable[[], bool] | None = None,
    halt_generation: Callable[[], object] | None = None,
) -> dict[str, object]:
    """The chosen route decides the endpoint, the payload and the key.

    This used to be one hardcoded OpenRouter URL, so a local or cloud model
    was answered by OpenRouter under another name. The router refuses instead
    of substituting, and its refusal is one sentence fit to show a person.
    """
    try:
        options = {"max_tokens": 900, "temperature": 0}
        options.update(_generation_options(generation))
        answer = route_chat(model, [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": context_block + "\n\nUser: " + prompt},
        ], free_only=model == "openrouter/free" or model.endswith(":free"),
            **options, **({"before_dispatch": before_dispatch} if before_dispatch else {}))
        return {"text": str(answer.get("text") or ""), "steps": [], "via": _answer_via(answer)}
    except (ValueError, PermissionError, ModelRouteRefused):
        raise
    except Exception:
        raise ModelRouteRefused("The model provider did not answer. Try again when it is available.") from None


def _answer_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    if isinstance(parsed, Mapping) and isinstance(parsed.get("answer"), str):
        return parsed["answer"].strip()
    return text


def _canvas_context(projection: Mapping[str, object]) -> str:
    nodes = [
        {"id": node["id"], "label": node.get("label", ""),
         "x": node.get("x"), "y": node.get("y"),
         "openable": bool(node.get("openable")),
         "ports": [
             {"name": port.get("name"), "side": port.get("side")}
             for port in node.get("ports", ())
             if port.get("owner") == node["id"]
             and port.get("mode") == "connection" and not port.get("derived")
         ]}
        for node in projection.get("nodes", ())
    ]
    catalog = [
        {"name": str(item["name"]), "description": str(item.get("description", ""))[:240]}
        for item in projection.get("catalog", ())
        if item.get("name")
    ]
    properties = [
        {"label": row.get("label"), "value": row.get("value"),
         "editable": bool(row.get("editable"))}
        for row in projection.get("properties", ())
    ]
    return "CANVAS CONTEXT" + chr(10) + json.dumps({
        "scope": (projection.get("scope") or {}).get("current"),
        "selection": projection.get("selection", ()),
        "selected": projection.get("selected"),
        "nodes": nodes,
        "catalogue": catalog,
        "selected_properties": properties,
    }, ensure_ascii=False)
