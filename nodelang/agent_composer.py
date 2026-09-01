"""The agent composer: intent in, signed graph gestures out.

The application was built for this: every mechanism the agent uses is an
existing governed entry point (instantiate, gesture, group, property edit).
The model proposes; the graph's own authorities dispose. Nothing here can do
anything a founder's click could not.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping

from .universal_cell import InvalidCell

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = os.environ.get(
    "ARCHHUB_AGENT_MODEL", "anthropic/claude-sonnet-4.5"
)
_FALLBACK_MODEL = "openai/gpt-4o"

_SYSTEM = """You operate the ArchHub node canvas. Reply with ONE JSON object:
{"actions":[...], "answer":"<one short sentence to the founder>"}
Each action is one of:
 {"op":"place","definition":"<catalogue name>","x":<num>,"y":<num>,"title":"<optional name>"}
 {"op":"select","roots":["<node id>", ...]}
 {"op":"group"}
 {"op":"ungroup"}
 {"op":"set_property","root":"<node id>","label":"<label>","value":"<text>"}
 {"op":"wire","source":"<node id>","target":"<node id>"}
 {"op":"run"}
 {"op":"open","root":"<openable node id>"}
Only use node ids and definition names that appear in the context. Answer in
the founder's language. If the request needs no canvas change, return
{"actions":[],"answer":"..."}."""


def _load_openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    # No machine-bound literal path: the production sibling is discovered
    # relative to this repository, overridable by environment.
    configured = os.environ.get("ARCHHUB_PRODUCTION_ROOT")
    production = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2] / "12.PRODUCTION"
    )
    if str(production) not in sys.path:
        sys.path.insert(0, str(production))
    from app import secrets_store  # noqa: PLC0415
    key = secrets_store.load_api_key("openrouter") or ""
    if len(key) < 20:
        raise InvalidCell("no usable OpenRouter key for the agent composer")
    return key


def _chat(prompt: str, context_block: str, model: str) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 900,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",
             "content": context_block + chr(10) + chr(10) + "FOUNDER: " + prompt},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        _OPENROUTER_URL, data=body, method="POST",
        headers={
            "Authorization": "Bearer " + _load_openrouter_key(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())
    return payload["choices"][0]["message"]["content"]


def _canvas_context(projection: Mapping[str, object]) -> str:
    nodes = [
        {"id": node["id"], "label": node.get("label", ""),
         "x": node.get("x"), "y": node.get("y"),
         "openable": bool(node.get("openable"))}
        for node in projection.get("nodes", ())
    ]
    catalog = [
        str(item.get("name", ""))
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


def run_agent_composer(
    store,
    registry,
    prompt: str,
    *,
    effect_engines: Mapping[str, object] | None = None,
    authentication_context: object | None = None,
) -> dict[str, object]:
    """One agent turn: read the canvas, ask the model, apply its actions."""
    from .universal_application import (  # noqa: PLC0415
        apply_universal_canvas_gesture,
        connect_universal_roots,
        edit_universal_property,
        group_universal_selection,
        instantiate_universal_definition,
        project_universal_canvas,
        ungroup_universal_composition,
        _set_universal_scope_execution,
    )
    if type(prompt) is not str or not prompt.strip():
        raise InvalidCell("agent prompt must be a non-empty string")
    projection = project_universal_canvas(
        store, registry, authentication_context=authentication_context
    )
    context_block = _canvas_context(projection)
    try:
        raw = _chat(prompt.strip(), context_block, _DEFAULT_MODEL)
    except urllib.error.HTTPError:
        raw = _chat(prompt.strip(), context_block, _FALLBACK_MODEL)
    text = raw.strip()
    if text.startswith("```"):
        text = text[text.index("{"):text.rindex("}") + 1]
    try:
        plan = json.loads(text)
    except ValueError as exc:
        raise InvalidCell(
            "agent reply was not the admitted JSON shape"
        ) from exc
    actions = plan.get("actions") or ()
    applied: list[dict[str, object]] = []
    node_ids = {str(node["id"]) for node in projection.get("nodes", ())}
    catalogue = {
        str(item.get("name", "")): str(item.get("id", ""))
        for item in projection.get("catalog", ())
    }
    for action in tuple(actions)[:12]:
        op = action.get("op")
        if op == "place":
            definition_root = catalogue.get(str(action.get("definition")))
            if not definition_root:
                applied.append({"op": op, "ok": False,
                                "why": "definition not in catalogue"})
                continue
            title = action.get("title")
            root, _revision = instantiate_universal_definition(
                store, registry, definition_root,
                x=float(action.get("x", 400)),
                y=float(action.get("y", 300)),
                title_override=(
                    str(title) if isinstance(title, str) and title.strip()
                    else None
                ),
                authentication_context=authentication_context,
            )
            node_ids.add(root)
            applied.append({"op": op, "ok": True, "root": root})
        elif op == "select":
            roots = [r for r in action.get("roots", ()) if r in node_ids]
            if not roots:
                applied.append({"op": op, "ok": False,
                                "why": "no known roots"})
                continue
            apply_universal_canvas_gesture(
                store, registry, roots=roots, focus_root=roots[-1],
                authentication_context=authentication_context,
            )
            applied.append({"op": op, "ok": True, "roots": roots})
        elif op == "group":
            root, _revision = group_universal_selection(
                store, registry,
                authentication_context=authentication_context,
            )
            node_ids.add(root)
            applied.append({"op": op, "ok": True, "root": root})
        elif op == "ungroup":
            fresh = project_universal_canvas(
                store, registry,
                authentication_context=authentication_context,
            )
            ungroup_universal_composition(
                store, registry, str(fresh.get("selected") or ""),
                authentication_context=authentication_context,
            )
            applied.append({"op": op, "ok": True})
        elif op == "set_property":
            fresh = project_universal_canvas(
                store, registry,
                authentication_context=authentication_context,
            )
            wanted = str(action.get("root") or fresh.get("selected"))
            if str(fresh.get("selected")) != wanted:
                apply_universal_canvas_gesture(
                    store, registry, roots=[wanted], focus_root=wanted,
                    authentication_context=authentication_context,
                )
                fresh = project_universal_canvas(
                    store, registry,
                    authentication_context=authentication_context,
                )
            row = next((
                item for item in fresh.get("properties", ())
                if item.get("editable")
                and str(item.get("label")) == str(action.get("label"))
            ), None)
            if row is None:
                applied.append({"op": op, "ok": False,
                                "why": "no editable property by that label"})
                continue
            edit_universal_property(
                store, registry, str(row["relation"]),
                str(action.get("value", "")),
                authentication_context=authentication_context,
            )
            applied.append({"op": op, "ok": True,
                            "label": action.get("label")})
        elif op == "wire":
            source = str(action.get("source", ""))
            target = str(action.get("target", ""))
            if source not in node_ids or target not in node_ids:
                applied.append({"op": op, "ok": False,
                                "why": "unknown endpoint"})
                continue
            try:
                from .universal_pipeline import (
                    _ensure_pipeline_node_interfaces,
                )
                for endpoint in (source, target):
                    _ensure_pipeline_node_interfaces(
                        store, registry, endpoint
                    )
                connect_universal_roots(
                    store, registry, source, target,
                    source_interface=(
                        "app:pipeline-interface:%s:source"
                        % source.rsplit(":", 1)[-1]
                    ),
                    target_interface=(
                        "app:pipeline-interface:%s:target"
                        % target.rsplit(":", 1)[-1]
                    ),
                    authentication_context=authentication_context,
                )
                applied.append({"op": op, "ok": True})
            except InvalidCell as refusal:
                applied.append({"op": op, "ok": False,
                                "why": str(refusal)[:120]})
        elif op == "run":
            from .universal_pipeline import run_universal_pipeline
            outcome = run_universal_pipeline(
                store, registry,
                effect_engines=dict(effect_engines or {}),
                authentication_context=authentication_context,
            )
            applied.append({
                "op": op, "ok": True,
                "ran": outcome["ran"],
                "answers": list(outcome["display"].values())[:6],
            })
        elif op == "open":
            root = str(action.get("root", ""))
            if root not in node_ids:
                applied.append({"op": op, "ok": False,
                                "why": "unknown root"})
                continue
            _set_universal_scope_execution(
                store, registry, root,
                authentication_context=authentication_context,
            )
            applied.append({"op": op, "ok": True, "root": root})
        else:
            applied.append({"op": str(op), "ok": False,
                            "why": "unknown op"})
    return {
        "ok": True,
        "answer": str(plan.get("answer", "")),
        "applied": applied,
        "revision": store.revision,
    }
