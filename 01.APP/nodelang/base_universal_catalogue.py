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




from .enforce import catalogue_entry as _enforce_catalogue_entry

from .clean_office_adapter import coordination_catalogue

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

     "parameters": {"action": _choice(("converse", "think", "vision", "match", "embed"), "think"), "model": _text(""), "prompt": _text("", multiline=True)},

     "interfaces": {"context": _in("any", multiple=True), "response": _out("completion"), "intent": _out("intent")}, "engine": "ai.master"},

    # NOTE / REROUTE / SKILL

    {"name": "Note", "category": "Note", "description": "Words on the canvas. Nothing flows through.",

     "parameters": {"text": _text("", multiline=True)}, "interfaces": {}, "engine": "note"},

    {"name": "Reroute", "category": "Note", "description": "A dot a wire passes through.",

     "parameters": {}, "interfaces": {"in": _in("any", required=True), "out": _out("any")}, "engine": "reroute"},

    {"name": "Skill", "category": "Skill", "description": "A graph you built, as one node.",

     "parameters": {"name": _text("untitled skill")}, "interfaces": {"trace": _in("trace"), "result": _out("any")}, "engine": "skill.wrap"},

    _enforce_catalogue_entry(),

) + coordination_catalogue()

__all__ = ['BASE_CATALOGUE']
