"""The base universal catalogue: the typed stem nodes every canvas starts with.

The 1.4 application shipped a palette -- Input, Output, Watch, Trigger,
Logic, Shape, AI, Note, Reroute, Skill (docs/NODE_GRAMMAR.md, the ✓ rows)
-- and the founder composed from it. The one-graph application lost it: the
catalogue held only the host operations, so the library read "List walls"
sixty-seven times and nothing a person builds a workflow from.

This publishes that palette into the one catalogue as ordinary
definitions: parameters are the node's config, interfaces are its typed
ports, presentation carries the category the library groups by. No node
classes, no dispatch -- a stem node is a definition like any other, and
placing one is the same instantiate the catalogue already offers. What a
node DOES when run is the operation catalogue's business (rules.operation);
the ones with no engine behind them yet say so ("engine": "pending") and
still compose and wire.
"""
from __future__ import annotations

import json
import uuid
from typing import Mapping

from .clean_runtime_bootstrap import BOOTSTRAP_NAMESPACE
from .unified_authority import (
    CallerCommandCapability,
    UnifiedAuthority,
    declare_definition,
    promote_definition,
    published_definition_named,
)

PROVENANCE = {
    "source": "docs/NODE_GRAMMAR.md (1.4 palette, ✓ rows)",
    "installed_by": "nodelang.base_universal_catalogue",
}


def _in(type_name: str, *, required: bool = False, multiple: bool = False):
    return {"direction": "input", "type": type_name, "required": required, "multiple": multiple}


def _out(type_name: str, *, multiple: bool = False):
    return {"direction": "output", "type": type_name, "multiple": multiple}


def _text(default: str = "", *, multiline: bool = False):
    return {"type": "text", "editor": "multiline" if multiline else "text", "default": default}


def _choice(options, default):
    return {"type": "text", "editor": "choice", "options": list(options), "default": default}


BASE_CATALOGUE: tuple[dict, ...] = (
    # INPUT — typed value sources
    {"name": "Number", "category": "Input", "description": "A number the graph holds; bound upstream when wired.",
     "parameters": {"value": _text("0"), "min": _text(""), "max": _text(""), "step": _text("1")},
     "interfaces": {"value": _out("number")}, "engine": "data.constant"},
    {"name": "Text", "category": "Input", "description": "A text the graph holds; bound upstream when wired.",
     "parameters": {"value": _text("", multiline=True)}, "interfaces": {"value": _out("string")}, "engine": "data.constant"},
    {"name": "List", "category": "Input", "description": "A list the graph holds, as JSON or comma-separated.",
     "parameters": {"value": _text("[1, 2, 3]", multiline=True)},
     "interfaces": {"value": _out("list")}, "engine": "data.list"},
    {"name": "Boolean", "category": "Input", "description": "True or false.",
     "parameters": {"value": _choice(("true", "false"), "false")}, "interfaces": {"value": _out("boolean")}, "engine": "data.constant"},
    {"name": "File", "category": "Input", "description": "A file the graph points at.",
     "parameters": {"value": _text(""), "extensions": _text("")}, "interfaces": {"value": _out("file")}, "engine": "data.constant"},
    {"name": "Color", "category": "Input", "description": "A colour, as hex.",
     "parameters": {"value": _text("#d97757")}, "interfaces": {"value": _out("color")}, "engine": "data.constant"},
    {"name": "Parameter", "category": "Input", "description": "Bound at run time by whoever runs this graph.",
     "parameters": {"name": _text("parameter"), "type": _choice(("any", "number", "string", "boolean", "file", "list"), "any"), "description": _text(""), "default": _text("")},
     "interfaces": {"value": _out("any")}, "engine": "input.parameter"},
    # OUTPUT — typed sinks
    {"name": "Result", "category": "Output", "description": "What this graph returns, under a name.",
     "parameters": {"name": _text("result")}, "interfaces": {"value": _in("any", required=True)}, "engine": "output.parameter"},
    # WATCH — passthrough viewers
    {"name": "Table view", "category": "Watch", "description": "See what flows through, as a table.",
     "parameters": {}, "interfaces": {"in": _in("any", required=True), "out": _out("any")}, "engine": "watch.preview"},
    {"name": "List view", "category": "Watch", "description": "See what flows through, as a list.",
     "parameters": {}, "interfaces": {"in": _in("any", required=True), "out": _out("any")}, "engine": "watch.preview"},
    {"name": "JSON view", "category": "Watch", "description": "See what flows through, as JSON.",
     "parameters": {}, "interfaces": {"in": _in("any", required=True), "out": _out("any")}, "engine": "watch.preview"},
    {"name": "Image view", "category": "Watch", "description": "See an image that flows through.",
     "parameters": {}, "interfaces": {"in": _in("file", required=True), "out": _out("file")}, "engine": "watch.preview"},
    # TRIGGER
    {"name": "Manual run", "category": "Trigger", "description": "Starts the graph when you press Run.",
     "parameters": {}, "interfaces": {"out": _out("trigger")}, "engine": "trigger.emit"},
    # LOGIC — control flow
    {"name": "If / Else", "category": "Logic", "description": "Routes a value by a condition.",
     "parameters": {"condition": _text("count > 0")},
     "interfaces": {"value": _in("any", required=True), "condition": _in("boolean"), "true": _out("any"), "false": _out("any")}, "engine": "control.if"},
    {"name": "For each", "category": "Logic", "description": "Runs the body once per item.",
     "parameters": {}, "interfaces": {"items": _in("list", required=True), "each": _out("any"), "results": _out("list")}, "engine": "control.foreach"},
    {"name": "Switch", "category": "Logic", "description": "Routes a value by a key.",
     "parameters": {"cases": _text("a, b, c")},
     "interfaces": {"value": _in("any", required=True), "key": _in("string"), "a": _out("any"), "b": _out("any"), "c": _out("any")}, "engine": "control.switch"},
    {"name": "Merge", "category": "Logic", "description": "The first value that arrives.",
     "parameters": {}, "interfaces": {"a": _in("any"), "b": _in("any"), "value": _out("any")}, "engine": "control.merge"},
    # SHAPE — typed data transforms
    {"name": "Filter", "category": "Shape", "description": "Keep or drop items by a predicate.",
     "parameters": {"predicate": _text("item.value > 0"), "mode": _choice(("keep", "drop"), "keep")},
     "interfaces": {"items": _in("list", required=True), "items_out": _out("list")}, "engine": "shape.filter"},
    {"name": "Map", "category": "Shape", "description": "Transform each item by an expression.",
     "parameters": {"expression": _text("item")}, "interfaces": {"items": _in("list", required=True), "items_out": _out("list")}, "engine": "shape.map"},
    {"name": "Sort", "category": "Shape", "description": "Order items by a field.",
     "parameters": {"by": _text("name"), "direction": _choice(("asc", "desc"), "asc")},
     "interfaces": {"items": _in("list", required=True), "items_out": _out("list")}, "engine": "shape.sort"},
    {"name": "Group by", "category": "Shape", "description": "Group items by a field.",
     "parameters": {"by": _text("category")}, "interfaces": {"items": _in("list", required=True), "groups": _out("list")}, "engine": "shape.group"},
    {"name": "Unique", "category": "Shape", "description": "Drop duplicates.",
     "parameters": {}, "interfaces": {"items": _in("list", required=True), "items_out": _out("list")}, "engine": "shape.unique"},
    {"name": "Pluck", "category": "Shape", "description": "Take one field from each item.",
     "parameters": {"field": _text("name")}, "interfaces": {"items": _in("list", required=True), "values": _out("list")}, "engine": "shape.pluck"},
    {"name": "Count", "category": "Shape", "description": "How many items.",
     "parameters": {}, "interfaces": {"items": _in("list", required=True), "count": _out("number")}, "engine": "shape.count"},
    {"name": "Slice", "category": "Shape", "description": "The first or last N items.",
     "parameters": {"count": _text("10"), "from": _choice(("start", "end"), "start")},
     "interfaces": {"items": _in("list", required=True), "items_out": _out("list")}, "engine": "shape.slice"},
    {"name": "Flatten", "category": "Shape", "description": "Nested lists into one.",
     "parameters": {}, "interfaces": {"items": _in("list", required=True), "items_out": _out("list")}, "engine": "shape.flatten"},
    {"name": "Concat", "category": "Shape", "description": "Join lists end to end.",
     "parameters": {}, "interfaces": {"a": _in("list", required=True), "b": _in("list", required=True), "items_out": _out("list")}, "engine": "shape.concat"},
    # AI — the one master with an action picker
    {"name": "AI", "category": "AI", "description": "Ask a model: converse, think, see, match, embed.",
     "parameters": {"action": _choice(("converse", "think", "vision", "match", "embed"), "think"), "model": _text("provider-selected"), "prompt": _text("", multiline=True)},
     "interfaces": {"context": _in("any", multiple=True), "response": _out("completion"), "intent": _out("intent")}, "engine": "ai.master"},
    # NOTE / REROUTE / SKILL
    {"name": "Note", "category": "Note", "description": "Words on the canvas. Nothing flows through.",
     "parameters": {"text": _text("", multiline=True)}, "interfaces": {}, "engine": "note"},
    {"name": "Reroute", "category": "Note", "description": "A dot a wire passes through.",
     "parameters": {}, "interfaces": {"in": _in("any", required=True), "out": _out("any")}, "engine": "reroute"},
    {"name": "Skill", "category": "Skill", "description": "A graph you built, as one node.",
     "parameters": {"name": _text("untitled skill")}, "interfaces": {"trace": _in("trace"), "result": _out("any")}, "engine": "skill.wrap"},
)


def _content_key(defaults, parameters, entry, rules) -> str:
    """One short key for exactly this definition content."""
    import hashlib

    payload = json.dumps(
        [defaults, parameters, entry["interfaces"], rules, entry["category"],
         entry["description"]],
        sort_keys=True, default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _command_key(name: str, step: str) -> str:
    return str(uuid.uuid5(
        BOOTSTRAP_NAMESPACE, "base-universal-catalogue:v1:%s:%s" % (name, step)
    ))


def install_base_universal_catalogue(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> Mapping[str, str]:
    """Publish every base definition the catalogue does not already hold.

    Idempotent by presence: a definition already PUBLISHED under its name is
    left as it is (its root is returned); anything else is declared, shared
    and published under command ids derived from its name, so a retried
    install replays instead of duplicating.
    """
    roots: dict[str, str] = {}
    for entry in BASE_CATALOGUE:
        name = entry["name"]
        # Every engined stem declares a status parameter: the channel a
        # Run answer lands in (rules.state_parameter names it, the card
        # shows it). Undeclared writes are refused by design, so the
        # catalogue declares the landing strip rather than the runner
        # inventing one.
        entry_parameters = dict(entry["parameters"])
        entry_rules = {"engine": entry["engine"]}
        if entry["engine"] not in (None, "note"):
            # A plain declared parameter, NOT rules.state_parameter:
            # state_parameter demands a transitions state machine, and
            # a run answer is a value, not a lifecycle.
            entry_parameters.setdefault(
                "status", {"editor": "text", "default": ""}
            )
        held = published_definition_named(authority, name, caller=caller)
        if held is not None:
            roots[name] = held
            _reconcile_status_parameter(
                authority, held, name, entry_parameters, entry_rules,
                entry, caller=caller,
            )
            continue
        defaults = {
            parameter: spec.get("default", "")
            for parameter, spec in entry_parameters.items()
        }
        parameters = {
            parameter: {k: v for k, v in spec.items() if k != "default"}
            for parameter, spec in entry_parameters.items()
        }
        declared = declare_definition(
            authority,
            name,
            defaults,
            parameters=parameters,
            interfaces=dict(entry["interfaces"]),
            rules=entry_rules,
            presentation={
                "label": name,
                "category": entry["category"],
                "description": entry["description"],
                "icon": "play",
                # Lands as a card, ports unbound; wired afterwards.
                "placement": "card",
                # The rail edits what the definition declares; without
                # this panel a placed stem has no way to take a value.
                "panels": ("Properties",),
            },
            provenance=PROVENANCE,
            caller=caller,
            command_id=_command_key(name, "declare"),
        )
        shared = promote_definition(
            authority, declared.root_id, target_lifecycle="shared",
            version="1-shared", evidence_roots=(declared.receipt_root,),
            caller=caller, command_id=_command_key(name, "share"),
        )
        promote_definition(
            authority, declared.root_id, target_lifecycle="published",
            version="1-published", evidence_roots=(shared.receipt_root,),
            caller=caller, command_id=_command_key(name, "publish"),
        )
        roots[name] = declared.root_id
    return roots


def _reconcile_status_parameter(
    authority,
    definition_root,
    name,
    entry_parameters,
    entry_rules,
    entry,
    *,
    caller,
):
    """Give an already-published stem the status channel it now declares.

    Presence-first install leaves a published definition alone, which is
    right for identity and wrong for drift: a graph whose stems were
    published before the status parameter existed can never land a Run
    answer. One WIP revision + promotion per stale definition, under
    derived command ids, so a retried boot replays instead of stacking
    revisions.
    """
    from .unified_authority import read_definition, revise_definition

    definition = read_definition(authority, definition_root, caller=caller)
    held_parameters = definition.contracts.get("parameters") or {}
    held_presentation = definition.contracts.get("presentation") or {}
    held_panels = held_presentation.get("panels") or ()
    needs_status = (
        "status" in entry_parameters
        and "status" not in held_parameters
    )
    needs_panel = "Properties" not in tuple(held_panels)
    # A definition published before its operation had a name still carries the
    # old engine; the catalogue is the authority, so the graph is brought to
    # what it now declares rather than left running yesterday's behaviour.
    held_rules = definition.contracts.get("rules") or {}
    needs_engine = held_rules.get("engine") != entry_rules.get("engine")
    if not needs_status and not needs_panel and not needs_engine:
        return
    defaults = {
        parameter: spec.get("default", "")
        for parameter, spec in entry_parameters.items()
    }
    parameters = {
        parameter: {k: v for k, v in spec.items() if k != "default"}
        for parameter, spec in entry_parameters.items()
    }
    revised = revise_definition(
        authority,
        definition_root,
        name,
        defaults,
        parameters=parameters,
        interfaces=dict(entry["interfaces"]),
        rules=entry_rules,
        presentation={
            "label": name,
            "category": entry["category"],
            "description": entry["description"],
            "icon": "play",
            "placement": "card",
            "panels": ("Properties",),
        },
        provenance=PROVENANCE,
        caller=caller,
        command_id=_command_key(name, "revise:" + _content_key(
            defaults, parameters, entry, entry_rules)),
        version="3",
    )
    shared = promote_definition(
        authority, definition_root, target_lifecycle="shared",
        version="3-shared", evidence_roots=(revised.receipt_root,),
        caller=caller, command_id=_command_key(
            name, "share:" + _content_key(defaults, parameters, entry, entry_rules)),
    )
    promote_definition(
        authority, definition_root, target_lifecycle="published",
        version="3-published", evidence_roots=(shared.receipt_root,),
        caller=caller, command_id=_command_key(
            name, "publish:" + _content_key(defaults, parameters, entry, entry_rules)),
    )


# What each stem operation MEANS, as a released expression over its declared
# inputs -- not as a Python branch on its engine name (SPEC 4.1). The shape is
# (view-template operation, input interface read from the projection). One
# entry here becomes expression cells in the graph at install time, and the
# runner evaluates those cells with the interpreter the views already use.
# Only operations the RELEASED vocabulary can already say. Adding an
# operation to that vocabulary is a protocol change with its own court, not
# something this table may assume.
GRAPH_EXPRESSIONS = {
    "shape.count": ("length", "items", "count"),
}


def install_stem_expressions(
    authority,
    roots,
    *,
    caller,
):
    """Give every operation that declares one its graph-held expression."""
    from .cell_protocols import CellBatch
    from .cell_view_template import ViewTemplateBuilder
    from .clean_visual_authority import open_clean_visual_system

    visual = open_clean_visual_system(authority, caller=caller)
    snapshot = authority.store.snapshot()
    built: dict[str, str] = {}
    batch = CellBatch(authority.store)
    builder = ViewTemplateBuilder(batch, visual.protocol)
    pending = []
    for entry in BASE_CATALOGUE:
        held = GRAPH_EXPRESSIONS.get(entry["engine"])
        if held is None:
            continue
        operation, source, output = held
        prefix = "app:stem-expression:%s" % entry["engine"]
        if ("%s:expression" % prefix) in snapshot.cells:
            built[entry["engine"]] = "%s:expression" % prefix
            continue
        segment = builder.atom("%s:segment" % prefix, source)
        root = builder.expression("%s:root" % prefix, "root")
        argument = builder.expression("%s:input" % prefix, "path", (root, segment))
        built[entry["engine"]] = builder.expression(
            "%s:expression" % prefix, operation, (argument,)
        )
        pending.append(entry["engine"])
    if pending:
        batch.commit()
    return built


__all__ = ["BASE_CATALOGUE", "install_base_universal_catalogue", "install_stem_expressions",
           "GRAPH_EXPRESSIONS"]
