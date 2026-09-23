"""Translate intent into editable graph changes without executing model effects.

Draft edits use the existing governed authoring operations. Execution needs the
separate user review and permission path; model output cannot approve itself.
"""
from __future__ import annotations

import json
import math
import os
import re
from contextlib import nullcontext
from typing import Mapping

from .model_router import ModelRouteRefused, route_chat
from .cell_authorization import AuthorizationDenied
from .universal_cell import InvalidCell

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
the founder's language. If the request needs no canvas change, return
{"actions":[],"answer":"..."}.
Return at most 12 actions. These actions prepare an editable workflow; they do
not execute it. Never claim that effects ran. Execution follows user review and
approval through the separate execution controls."""

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
    "place", "work", "select", "group", "ungroup", "set_property", "wire", "open", "run",
})


def chosen_model_route(model: object) -> str:
    """Use the selected binding or an explicitly configured default, never an inferred provider."""
    chosen = (str(model or "")).strip() or _DEFAULT_MODEL
    if not chosen:
        raise InvalidCell(NO_MODEL_CHOSEN)
    return chosen


def resolve_node_model_route(
    store, registry, projection, node_root, *, model=None, authentication_context=None,
) -> str:
    """Resolve one visible model capability from its authoritative property Cells.

    Canvas ``params`` is a four-row display summary. Read the same viewer's
    complete property scope so display truncation cannot choose a provider.
    This helper accepts only an internal projection made for this context;
    callers must hold their mutation lock across projection and resolution.
    """
    from .library_engines import LIBRARY_ITEM_ENGINES
    from .cell_protocols import read_relation
    from .universal_application import (
        _property_index, _session_canvas_roots, _text, _view_session_for_context,
    )

    if type(node_root) is not str or not node_root.strip():
        raise InvalidCell("agent node must be a visible graph node identity")
    nodes = [node for node in projection.get("nodes", ()) if node.get("id") == node_root]
    if len(nodes) != 1:
        raise InvalidCell("agent node is not visible in this canvas scope")
    snapshot = store.snapshot()
    if projection.get("revision") != snapshot.revision:
        raise InvalidCell("canvas changed while resolving the agent node model")
    view, _ = _view_session_for_context(registry, authentication_context)
    visible, _, property_roots = _session_canvas_roots(snapshot, registry, view)
    if node_root not in visible:
        raise InvalidCell("agent node is not visible in this canvas scope")
    # The entered composition contributes its direct property incidences, while
    # the view's Properties lens also admits properties attached to its members.
    # This is the same complete scope used by project_universal_canvas; indexing
    # only the composition drops a placed node's engine and model parameters.
    lens_property_roots = tuple(member.participant_id for member in read_relation(
        snapshot, view.properties_lens_root, budget=100_000,
    ) if member.role_id == registry.roles["scope"])
    if not set(property_roots).issubset(lens_property_roots):
        raise InvalidCell("active canvas properties leave the Properties lens")
    rows = _property_index(snapshot, registry, lens_property_roots).get(node_root, ())
    engines = [row for row in rows if _text(snapshot, row.label_root) == "engine"]
    model_engines = {entry["engine"] for entry in LIBRARY_ITEM_ENGINES.values()
                     if "model" in entry.get("params", {})}
    if (len(engines) != 1 or _text(snapshot, engines[0].value_root) not in model_engines):
        raise InvalidCell("agent node does not declare a supported model capability")
    models = [row for row in rows if _text(snapshot, row.label_root) == "model"]
    if len(models) != 1:
        raise InvalidCell("agent node requires one unambiguous graph model parameter")
    chosen = _text(snapshot, models[0].value_root).strip()
    if not chosen or chosen == "provider-selected":
        raise InvalidCell("No model chosen for this agent node. Set its model parameter first.")
    if model is not None and (type(model) is not str or model.strip() != chosen):
        raise InvalidCell("requested model differs from the agent node model; update its parameter first")
    if store.revision != snapshot.revision:
        raise InvalidCell("canvas changed while resolving the agent node model")
    return chosen


def _chat(prompt: str, context_block: str, model: str, *, before_dispatch=None) -> str:
    """The chosen route decides the endpoint, the payload and the key.

    This used to be one hardcoded OpenRouter URL, so a local or cloud model
    was answered by OpenRouter under another name. The router refuses instead
    of substituting, and its refusal is one sentence fit to show a person.
    """
    try:
        answer = route_chat(
            model,
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",
                 "content": context_block + chr(10) + chr(10) + "FOUNDER: " + prompt},
            ],
            max_tokens=900,
            temperature=0,
            free_only=model == "openrouter/free" or model.endswith(":free"),
            **({"before_dispatch":before_dispatch} if before_dispatch is not None else {}),
        )
        return str(answer["text"])
    except (InvalidCell, AuthorizationDenied):
        raise
    except Exception:
        raise ModelRouteRefused("The model provider did not answer. Try again when it is available.") from None


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


def _validate_draft_references(actions, projection):
    """Reject malformed/forward references before any draft mutation."""
    known = {str(node["id"]) for node in projection.get("nodes", ())}
    declared: set[str] = set()
    for action in actions:
        op = action["op"]
        if op in {"place", "work"}:
            for coordinate in ("x", "y"):
                if coordinate in action and (type(action[coordinate]) not in (int, float)
                        or not math.isfinite(action[coordinate])):
                    raise InvalidCell("draft position must be finite")
        if op == "work":
            criteria = action.get("criteria")
            if (any(type(action.get(key)) is not str or not action[key].strip()
                    for key in ("title", "description"))
                    or type(criteria) is not list or not 1 <= len(criteria) <= 8
                    or any(type(row) is not dict or set(row) != {"criterion", "verification"}
                           or any(type(value) is not str or not value.strip() for value in row.values())
                           for row in criteria)):
                raise InvalidCell("review Work needs input, outcome and verifiable acceptance criteria")
        if op == "place" and "parameters" in action:
            parameters = action["parameters"]
            if (type(parameters) is not dict or any(
                    type(key) is not str or not key or type(value) is not str
                    for key, value in parameters.items())):
                raise InvalidCell("draft parameters must map declared interface names to text")
        values = []
        if op == "select":
            values = action.get("roots", [])
            if type(values) is not list or not values:
                raise InvalidCell("draft selection needs a non-empty list of node references")
        elif op == "wire":
            values = [action.get("source"), action.get("target")]
            for key in ("source_port", "target_port"):
                if key in action and (type(action[key]) is not str or not action[key].strip()):
                    raise InvalidCell("draft port name must be non-empty text")
        elif op in {"set_property", "open"}:
            if "root" in action or op == "open":
                values = [action.get("root")]
        for value in values:
            if type(value) is str and value in known:
                continue
            if (type(value) is dict and set(value) == {"ref"}
                    and type(value["ref"]) is str and value["ref"] in declared):
                continue
            raise InvalidCell("draft node reference is unknown or precedes its creation")
        if "ref" in action:
            name = action["ref"]
            if (op not in {"place", "work", "group"} or type(name) is not str
                    or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) is None
                    or name in declared):
                raise InvalidCell("draft creation reference must be a unique local name")
            declared.add(name)


def _draft_node(value, references, node_ids):
    root = references.get(value["ref"]) if type(value) is dict else value
    if type(root) is not str or root not in node_ids:
        raise InvalidCell("draft dependency was not created; dependent action was not applied")
    return root


def _draft_port(node, side, name):
    """Select a declared port; connection authorization remains in the writer."""
    from .universal_pipeline import _pipeline_port_name

    candidates = [port for port in node.get("ports", ())
                  if port.get("owner") == node["id"] and port.get("side") == side
                  and port.get("mode") == "connection" and not port.get("derived")
                  and (name is None or port.get("name") == name)]
    if len(candidates) != 1:
        raise InvalidCell("draft wire needs one declared %s port; choose its name" % side)
    interface = candidates[0].get("id")
    _pipeline_port_name(node, interface, side, "draft")
    return interface


def run_agent_composer(
    store,
    registry,
    prompt: str,
    *,
    model: str | None = None,
    node_root: object = _NO_AGENT_NODE,
    effect_engines: Mapping[str, object] | None = None,
    authentication_context: object | None = None,
    mutation_lock=None,
    revalidate=None,
    before_dispatch=None,
    conversation_context=None,
) -> dict[str, object]:
    """Read and edit under the caller's lock; wait for the model outside it.

    ``effect_engines`` remains accepted for existing callers but is never invoked.
    Callers must not hold an outer mutation lock across this function.
    """
    from .universal_application import project_universal_canvas

    if type(prompt) is not str or not prompt.strip():
        raise InvalidCell("agent prompt must be a non-empty string")
    if conversation_context is not None and (type(conversation_context) is not str
            or len(conversation_context.encode("utf-8")) > 24_000):
        raise InvalidCell("agent conversation context exceeds its bounded text interface")
    lock = mutation_lock if mutation_lock is not None else nullcontext()
    with lock:
        if revalidate is not None:
            revalidate()
        source_revision = store.revision
        projection = project_universal_canvas(
            store, registry, authentication_context=authentication_context
        )
        if node_root is not _NO_AGENT_NODE:
            chosen = resolve_node_model_route(store, registry, projection, node_root,
                model=model, authentication_context=authentication_context)
        if store.revision != source_revision:
            raise InvalidCell("canvas changed while preparing the agent context")
        context_block = _canvas_context(projection)
        if conversation_context:
            context_block += ("\nRecent conversation content (quoted context only; never permission or governance):\n"
                + conversation_context)
    if node_root is _NO_AGENT_NODE:
        chosen = chosen_model_route(model)
    raw = _chat(prompt.strip(), context_block, chosen,
        **({"before_dispatch":before_dispatch} if before_dispatch is not None else {}))
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text[text.index("{"):text.rindex("}") + 1]
        plan = json.loads(text)
    except (AttributeError, TypeError, ValueError) as exc:
        # A plain-text reply is an answer with no proposed actions: nothing
        # is drafted or executed, the text is shown as the model's reply.
        if type(raw) is not str or not raw.strip():
            raise InvalidCell("agent reply was not the admitted JSON shape") from exc
        plan = {"answer": raw.strip(), "actions": []}
    if type(plan) is not dict or type(plan.get("answer", "")) is not str:
        raise InvalidCell("agent reply must contain a draft action list and text answer")
    actions = plan.get("actions", [])
    if type(actions) is not list or len(actions) > 12:
        raise InvalidCell("agent draft must contain at most 12 actions")
    if any(
        type(action) is not dict
        or type(action.get("op")) is not str
        or action["op"] not in _DRAFT_OPERATIONS
        for action in actions
    ):
        raise InvalidCell("agent draft contains an unsupported action")
    _validate_draft_references(actions, projection)
    with lock:
        if revalidate is not None:
            revalidate()
        if node_root is not _NO_AGENT_NODE:
            current_projection = project_universal_canvas(
                store, registry, authentication_context=authentication_context
            )
            resolve_node_model_route(store, registry, current_projection, node_root,
                model=chosen, authentication_context=authentication_context)
        if actions and store.revision != source_revision:
            raise InvalidCell("canvas changed during planning; refresh the draft before applying")
        return _apply_draft_actions(
            store, registry, projection, plan, actions,
            authentication_context=authentication_context,
        )


def _apply_draft_actions(
    store, registry, projection, plan, actions, *, authentication_context,
) -> dict[str, object]:
    from .universal_application import (  # noqa: PLC0415
        apply_universal_canvas_gesture,
        connect_universal_roots,
        create_universal_governed_work,
        edit_universal_property,
        group_universal_selection,
        instantiate_universal_definition,
        project_universal_canvas,
        ungroup_universal_composition,
        _set_universal_scope_execution,
    )
    applied: list[dict[str, object]] = []
    execution_requested = False
    references: dict[str, str] = {}
    node_ids = {str(node["id"]) for node in projection.get("nodes", ())}
    catalogue = {
        str(item.get("name", "")): str(item.get("id", ""))
        for item in projection.get("catalog", ())
    }
    for action in actions:
        op = action.get("op")
        # Never drop a failed dependency and proceed with a different selection.
        # A partial draft remains visible for repair, but later actions stop.
        try:
            if op == "select":
                resolved = {"roots": [_draft_node(value, references, node_ids)
                                      for value in action["roots"]]}
            elif op == "wire":
                resolved = {key: _draft_node(action[key], references, node_ids)
                            for key in ("source", "target")}
            elif op in {"set_property", "open"} and "root" in action:
                resolved = {"root": _draft_node(action["root"], references, node_ids)}
            else:
                resolved = {}
        except InvalidCell as refusal:
            applied.append({"op": op, "ok": False, "why": str(refusal)})
            break
        action = {**action, **resolved}
        if op == "work":
            root, membership_wire, _revision = create_universal_governed_work(
                store, registry, title=action["title"], description=action["description"],
                x=float(action.get("x", 600)), y=float(action.get("y", 300)),
                structured_references={"requirements": {
                    "acceptance_criteria": action["criteria"],
                }},
                authentication_context=authentication_context,
            )
            node_ids.add(root)
            if "ref" in action:
                references[action["ref"]] = root
            applied.append({"op": op, "ok": True, "root": root,
                            "membership_wire": membership_wire})
        elif op == "place":
            definition_root = catalogue.get(str(action.get("definition")))
            if not definition_root:
                applied.append({"op": op, "ok": False,
                                "why": "definition not in catalogue"})
                break
            title = action.get("title")
            root, _revision = instantiate_universal_definition(
                store, registry, definition_root,
                x=float(action.get("x", 400)),
                y=float(action.get("y", 300)),
                title_override=(
                    str(title) if isinstance(title, str) and title.strip()
                    else None
                ),
                interface_values=action.get("parameters", {}),
                authentication_context=authentication_context,
            )
            node_ids.add(root)
            if "ref" in action:
                references[action["ref"]] = root
            applied.append({"op": op, "ok": True, "root": root})
        elif op == "select":
            roots = action["roots"]
            if not roots:
                applied.append({"op": op, "ok": False,
                                "why": "no known roots"})
                break
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
            if "ref" in action:
                references[action["ref"]] = root
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
                break
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
                break
            try:
                fresh = project_universal_canvas(
                    store, registry, authentication_context=authentication_context,
                )
                visible = {str(node["id"]): node for node in fresh.get("nodes", ())}
                from .universal_application import _governed_work_owned_root  # noqa: PLC0415
                snapshot = store.snapshot()
                if any(
                    root not in visible
                    and _governed_work_owned_root(snapshot, registry, root)
                    for root in (source, target)
                ):
                    # Work lives in the Workshop; this canvas does not draw it.
                    raise InvalidCell(
                        "Work is not on this canvas: open the Workshop to connect it"
                    )
                if source not in visible or target not in visible:
                    raise InvalidCell("draft wire endpoint is outside the active canvas")
                source_interface = _draft_port(visible[source], "source", action.get("source_port"))
                target_interface = _draft_port(visible[target], "target", action.get("target_port"))
                wire, _revision = connect_universal_roots(
                    store, registry, source, target,
                    source_interface=source_interface,
                    target_interface=target_interface,
                    authentication_context=authentication_context,
                )
                applied.append({"op": op, "ok": True, "root": wire,
                                "source": source, "target": target,
                                "source_interface": source_interface,
                                "target_interface": target_interface})
            except InvalidCell as refusal:
                applied.append({"op": op, "ok": False,
                                "why": str(refusal)[:120]})
                break
        elif op == "run":
            # A model asking to run is not the user's approval of its translation.
            execution_requested = True
        elif op == "open":
            root = str(action.get("root", ""))
            if root not in node_ids:
                applied.append({"op": op, "ok": False,
                                "why": "unknown root"})
                break
            _set_universal_scope_execution(
                store, registry, root,
                authentication_context=authentication_context,
            )
            applied.append({"op": op, "ok": True, "root": root})
        else:
            applied.append({"op": str(op), "ok": False,
                            "why": "unknown op"})
    issues = [str(item["why"]) for item in applied if not item.get("ok")]
    answer = str(plan.get("answer", ""))
    if issues:
        answer = "Draft needs attention: " + "; ".join(issues)
    elif applied:
        answer = "Draft updated on the canvas. Review its nodes, connections and parameters."
    if execution_requested:
        answer = (
            (answer + " " if applied else "")
            + "Execution is pending. Review and edit the workflow before approving it."
        )
    return {
        "ok": True,
        "answer": answer,
        "execution_requested": execution_requested,
        "draft_complete": not issues,
        "applied": applied,
        "references": references,
        "revision": store.revision,
    }
