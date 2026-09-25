"""Evaluate one scope's stem graph: values flow along declared wires.

The base catalogue publishes definitions whose rules name an engine --
data.constant, output.parameter, watch.preview and the rest. Placing and
wiring them draws a dataflow graph; this walks that graph and answers
what every declared output carries.

Three rules hold it together:

Pure over what the graph says. Inputs are the nodes (engine, parameter
values, declared interfaces) and the wires (source root and interface to
target root and interface). No store handle, no host, no clock: the same
graph always evaluates to the same values.

Honest about what it cannot run. An engine neither built in here nor
injected as an effect engine (the Run paths inject pipeline_engines,
which carries ai.master and skill.wrap) marks its node "pending" and
everything downstream of it "blocked" -- never a guess, never a crash.

A cycle is an answer, not a hang. Nodes on a cycle are reported as
blocked with the reason "cycle"; everything reachable without them still
evaluates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class StemNode:
    """One placed node, as the evaluator needs it."""

    root_id: str
    engine: str | None
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class StemWire:
    """One wire between declared interfaces, with its governed rows.

    ``condition`` gates what the wire carries (the If/Else rule grammar),
    ``on_fail`` says what the target receives when it blocks ("block" or
    "pass empty"), and ``tree`` restructures a list on the way through
    ("none", "flatten", "graft", "simplify").
    """

    source: str
    source_interface: str
    target: str
    target_interface: str
    condition: str = ""
    on_fail: str = "block"
    tree: str = "none"


@dataclass(frozen=True)
class StemEvaluation:
    """What one evaluation pass produced."""

    display: Mapping[str, str]
    results: Mapping[str, object]
    pending: Mapping[str, str]
    node_outputs: Mapping[str, Mapping[str, object]] = None


def _coerce(text: object) -> object:
    """A parameter's typed value, from the text the graph holds."""
    if type(text) is not str:
        return text
    stripped = text.strip()
    if stripped in ("true", "false"):
        return stripped == "true"
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    return text


def _display(value: object) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


_PASS_THROUGH = {"watch.preview": ("in", "out"), "reroute": ("in", "out")}

# The comparisons a rule may use, longest first so ">=" is never read as ">".
_OPERATORS = (
    (">=", lambda left, right: left >= right),
    ("<=", lambda left, right: left <= right),
    ("!=", lambda left, right: left != right),
    ("==", lambda left, right: left == right),
    (">", lambda left, right: left > right),
    ("<", lambda left, right: left < right),
)


class _Refusal:
    """Why a wire delivered nothing; the target node reports it."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


def rule_holds(rule: str, value: object) -> "bool | None":
    """Whether a declared comparison holds for one value, or None when the
    rule is not one this version evaluates.

    The left side names what is compared: ``count`` is how many items the
    value carries, ``value`` / ``item`` (or nothing) is the value itself,
    and any other name is that field of the value. The right side is a
    literal. This is the comparison grammar the Filter card honours.
    """
    text = str(rule or "").strip()
    for operator, test in _OPERATORS:
        if operator not in text:
            continue
        left_text, right_text = text.split(operator, 1)
        name = left_text.strip()
        wanted = _coerce(right_text.strip().strip("'" + chr(34)))
        if name == "count":
            held = len(_as_list(value))
        elif name in ("", "value", "item"):
            held = value
        else:
            for prefix in ("item.", "value."):
                if name.startswith(prefix):
                    name = name[len(prefix):]
            held = _field(value, name)
        try:
            return bool(test(held, wanted))
        except TypeError:
            return False
    return None


def _restructure(tree: str, value: object) -> object:
    """A list reshaped the way the wire's data-tree row asks."""
    if tree in ("", "none"):
        return value
    items = _as_list(value)
    if tree == "flatten":
        flat: list = []
        stack = list(reversed(items))
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(reversed(item))
            else:
                flat.append(item)
        return flat
    if tree == "graft":
        return [[item] for item in items]
    if tree == "simplify":
        def simplify(item):
            if not isinstance(item, list):
                return item
            kept = [simplify(child) for child in item]
            kept = [child for child in kept if child != []]
            while len(kept) == 1 and isinstance(kept[0], list):
                kept = kept[0]
            return kept
        return simplify(items)
    return _Refusal("wire data tree %r is not one this version applies" % tree)


def _carry(wire: StemWire, value: object) -> object:
    """What one wire delivers: restructured, then gated by its condition."""
    shaped = _restructure(str(wire.tree or "none").strip(), value)
    if isinstance(shaped, _Refusal):
        return shaped
    condition = str(wire.condition or "").strip()
    if not condition:
        return shaped
    holds = rule_holds(condition, shaped)
    if holds is None:
        return _Refusal(
            "wire condition %r is not one this version evaluates" % condition
        )
    if holds:
        return shaped
    on_fail = str(wire.on_fail or "block").strip()
    if on_fail == "pass empty":
        return []
    if on_fail == "block":
        return _Refusal("blocked by wire condition %r" % condition)
    return _Refusal("wire on-block %r is not one this version applies" % on_fail)


def _file_name(text: str) -> str:
    return text.replace(chr(92), "/").rsplit("/", 1)[-1]


def _constant_refusal(params: Mapping[str, object], value: object) -> "str | None":
    """Why a Number or File card's value breaks its own declared limits."""
    import math

    def number(name):
        held = params.get(name)
        if held in ("", None):
            return None
        if isinstance(held, bool) or not isinstance(held, (int, float)):
            raise ValueError("%s %r is not a number" % (name, held))
        return float(held)

    if any(name in params for name in ("min", "max", "step")):
        try:
            low, high, step = number("min"), number("max"), number("step")
        except ValueError as refusal:
            return str(refusal)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "value %r is not a number" % (value,)
        if low is not None and value < low:
            return "value %s is below min %s" % (_display(value), _display(low))
        if high is not None and value > high:
            return "value %s is above max %s" % (_display(value), _display(high))
        if step is not None:
            if step <= 0:
                return "step %s must be greater than 0" % _display(step)
            steps = (value - (low or 0.0)) / step
            if not math.isclose(steps, round(steps), abs_tol=1e-9):
                return "value %s is not on a step of %s from %s" % (
                    _display(value), _display(step), _display(low or 0))
    if "extensions" in params:
        allowed = []
        for part in str(params.get("extensions") or "").split(","):
            part = part.strip().lower().lstrip("*")
            if part:
                allowed.append(part if part.startswith(".") else "." + part)
        name = _file_name(str(value or "").strip())
        if allowed and name:
            suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if suffix not in allowed:
                return "file %r is not one of %s" % (name, ", ".join(allowed))
    return None


def evaluate_stem_graph(
    nodes: Sequence[StemNode],
    wires: Sequence[StemWire],
    graph_expressions: "Mapping[str, object] | None" = None,
    effect_engines: "Mapping[str, object] | None" = None,
) -> StemEvaluation:
    """Every declared output's value, walked from constants to results."""
    by_root = {node.root_id: node for node in nodes}
    incoming: dict[str, dict[str, tuple[str, str]]] = {}
    conflicts: dict[str, set[str]] = {}
    for wire in wires:
        if wire.source not in by_root or wire.target not in by_root:
            continue
        feeds = incoming.setdefault(wire.target, {})
        if wire.target_interface in feeds:
            conflicts.setdefault(wire.target, set()).add(wire.target_interface)
        else:
            feeds[wire.target_interface] = wire

    outputs: dict[str, dict[str, object]] = {}
    display: dict[str, str] = {}
    results: dict[str, object] = {}
    # A scalar input has no implicit last-writer or list-reduction rule.
    # Reject ambiguity before invoking any engine on the affected node.
    pending: dict[str, str] = {
        root: "multiple connections on input(s): " + ", ".join(sorted(names))
        for root, names in conflicts.items()
    }
    visiting: set[str] = set()

    def resolve(root: str) -> dict[str, object] | None:
        if root in outputs:
            return outputs[root]
        if root in pending:
            return None
        if root in visiting:
            pending[root] = "cycle"
            return None
        node = by_root[root]
        visiting.add(root)
        try:
            feeds: dict[str, object] = {}
            for name, wire in (incoming.get(root) or {}).items():
                src, src_if = wire.source, wire.source_interface
                upstream = resolve(src)
                if upstream is None:
                    pending.setdefault(root, "blocked by %s" % src)
                    return None
                if src_if not in upstream:
                    pending[root] = "no value on %s.%s" % (src, src_if)
                    return None
                carried = _carry(wire, upstream[src_if])
                if isinstance(carried, _Refusal):
                    pending[root] = carried.reason
                    return None
                feeds[name] = carried
            # An operation whose definition holds an expression computes from
            # that expression: the graph says what the node means (SPEC 4.1).
            # The Python engines below remain only where no released
            # expression exists yet, and only as an unproven fast path.
            effect = (effect_engines or {}).get(node.engine)
            if effect is not None:
                # An injected effect engine is the entry point's declared
                # bridge to a host or a file -- the evaluator stays pure by
                # default, and an effect that fails answers per node.
                try:
                    produced, shown = effect(dict(node.parameters), feeds)
                except Exception as refusal:
                    pending[root] = str(refusal)
                    return None
                display[root] = shown
                outputs[root] = dict(produced)
                return outputs[root]
            held = (graph_expressions or {}).get(node.engine)
            if held is not None:
                produced = _run_graph_expression(
                    node, held, feeds, display, results, pending
                )
            else:
                produced = _run_engine(node, feeds, display, results, pending)
            if produced is None:
                return None
            outputs[root] = produced
            return produced
        finally:
            visiting.discard(root)

    for node in nodes:
        if node.engine:
            resolve(node.root_id)
    return StemEvaluation(display, results, pending, dict(outputs))


def _run_engine(
    node: StemNode,
    feeds: Mapping[str, object],
    display: dict[str, str],
    results: dict[str, object],
    pending: dict[str, str],
) -> dict[str, object] | None:
    engine = node.engine
    root = node.root_id
    params = {key: _coerce(value) for key, value in node.parameters.items()}
    if engine in (None, "note"):
        return {}
    if engine in ("data.constant", "input.parameter"):
        value = params.get("value", "")
        # The Parameter card declares "default", not "value"; a run with
        # nothing bound reads the declared default instead of nothing.
        if engine == "input.parameter" and value in ("", None):
            value = params.get("default", "")
        # Number declares min/max/step and File declares extensions: the
        # card's own limits are enforced, never decoration.
        if engine == "data.constant":
            refusal = _constant_refusal(params, value)
            if refusal is not None:
                pending[root] = refusal
                return None
        display[root] = _display(value)
        return {"value": value}
    if engine == "output.parameter":
        if "value" not in feeds:
            pending[root] = "input value is not wired"
            return None
        value = feeds["value"]
        name = params.get("name") or "result"
        results[str(name)] = value
        display[root] = _display(value)
        return {}
    if engine in _PASS_THROUGH:
        source_name, out_name = _PASS_THROUGH[engine]
        if source_name not in feeds:
            pending[root] = "input %s is not wired" % source_name
            return None
        value = feeds[source_name]
        display[root] = _display(value)
        return {out_name: value}
    if engine == "control.if":
        if "value" not in feeds:
            pending[root] = "input value is not wired"
            return None
        value = feeds["value"]
        # A wired condition decides; otherwise the card's own condition
        # rule does; a card with no rule routes on the value's truth.
        if "condition" in feeds:
            condition = feeds["condition"]
        else:
            rule = str(node.parameters.get("condition") or "").strip()
            condition = bool(value) if not rule else rule_holds(rule, value)
            if condition is None:
                pending[root] = (
                    "condition %r is not one this version evaluates" % rule
                )
                return None
        taken = "true" if condition else "false"
        display[root] = taken
        return {taken: value}
    if engine == "control.merge":
        for name in ("a", "b"):
            if name in feeds and feeds[name] is not None:
                display[root] = _display(feeds[name])
                return {"value": feeds[name]}
        pending[root] = "no wired input carries a value"
        return None
    if engine == "trigger.emit":
        display[root] = "ready"
        return {"out": True}
    if engine == "data.list":
        items = _as_list(params.get("value", ""))
        display[root] = "%d items" % len(items)
        return {"value": items}
    if engine.startswith("shape."):
        return _run_shape(engine, node, feeds, params, display, pending)
    if engine == "control.foreach":
        if "items" not in feeds:
            pending[root] = "input items is not wired"
            return None
        items = _as_list(feeds["items"])
        display[root] = "%d items" % len(items)
        return {"each": items[0] if items else None, "results": items}
    if engine == "control.switch":
        if "value" not in feeds:
            pending[root] = "input value is not wired"
            return None
        # The card's cases name the key of each of its three outputs, in
        # order: cases "wall, door, window" routes key "door" to output b.
        cases = [
            part.strip().casefold()
            for part in str(node.parameters.get("cases") or "a, b, c").split(",")
            if part.strip()
        ]
        if not cases or len(cases) > 3:
            pending[root] = (
                "Switch has three outputs (a, b, c); cases must name one to three keys"
            )
            return None
        held_key = feeds.get("key")
        key = str(cases[0] if held_key is None else held_key).strip()
        if key.casefold() not in cases:
            pending[root] = "key %r matches no case (%s)" % (key, ", ".join(cases))
            return None
        branch = ("a", "b", "c")[cases.index(key.casefold())]
        display[root] = branch if key.casefold() == branch else "%s -> %s" % (key, branch)
        return {branch: feeds["value"]}
    pending[root] = "engine %s is pending" % engine
    return None


def _as_list(value: object) -> list:
    """A list from what the graph holds: JSON, comma-separated, or one value."""
    import json

    if isinstance(value, list):
        return list(value)
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            held = json.loads(text)
        except ValueError:
            return [text]
        return held if isinstance(held, list) else [held]
    if "," in text:
        return [_coerce(part.strip()) for part in text.split(",") if part.strip()]
    return [_coerce(text)]


def _field(item: object, name: str) -> object:
    """One field of an item, however the item carries it."""
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, item)


def _sortable(value: object) -> tuple:
    """Order numbers before text, and never raise on a mixed list."""
    if isinstance(value, bool):
        return (1, str(value))
    if isinstance(value, (int, float)):
        return (0, value)
    return (1, str(value))


def _run_shape(engine, node, feeds, params, display, pending):
    """The Shape family: one engine name, one list operation."""
    root = node.root_id
    if engine == "shape.concat":
        if "a" not in feeds or "b" not in feeds:
            pending[root] = "both lists must be wired"
            return None
        joined = _as_list(feeds["a"]) + _as_list(feeds["b"])
        display[root] = "%d items" % len(joined)
        return {"items_out": joined}
    if "items" not in feeds:
        pending[root] = "input items is not wired"
        return None
    items = _as_list(feeds["items"])
    if engine == "shape.count":
        display[root] = str(len(items))
        return {"count": len(items)}
    if engine == "shape.unique":
        seen, kept = set(), []
        for item in items:
            token = repr(item)
            if token in seen:
                continue
            seen.add(token)
            kept.append(item)
        display[root] = "%d items" % len(kept)
        return {"items_out": kept}
    if engine == "shape.flatten":
        flat = []
        for item in items:
            flat.extend(item if isinstance(item, list) else [item])
        display[root] = "%d items" % len(flat)
        return {"items_out": flat}
    if engine == "shape.sort":
        by = str(params.get("by") or "").strip()
        ordered = sorted(
            items,
            key=lambda item: _sortable(_field(item, by) if by else item),
            reverse=str(params.get("direction") or "asc") == "desc",
        )
        display[root] = "%d items" % len(ordered)
        return {"items_out": ordered}
    if engine == "shape.slice":
        count = params.get("count")
        count = count if isinstance(count, int) else 10
        taken = (
            items[-count:] if str(params.get("from") or "start") == "end"
            else items[:count]
        )
        display[root] = "%d items" % len(taken)
        return {"items_out": taken}
    if engine == "shape.pluck":
        field = str(params.get("field") or "").strip()
        values = [_field(item, field) for item in items]
        display[root] = "%d values" % len(values)
        return {"values": values}
    if engine == "shape.group":
        by = str(params.get("by") or "").strip()
        groups: dict = {}
        for item in items:
            groups.setdefault(str(_field(item, by)), []).append(item)
        display[root] = "%d groups" % len(groups)
        return {"groups": [
            {"key": key, "items": held} for key, held in groups.items()
        ]}
    if engine in ("shape.filter", "shape.map"):
        # The predicate and the expression are founder text, and this version
        # does not evaluate founder text -- an interpreter that ran it would
        # be a language nobody courted. The comparisons the catalogue already
        # declares are honoured; anything else says so instead of guessing.
        rule = str(
            params.get("predicate") if engine == "shape.filter"
            else params.get("expression") or ""
        ).strip()
        if engine == "shape.map" and rule in ("", "item"):
            display[root] = "%d items" % len(items)
            return {"items_out": list(items)}
        kept = _filtered(items, rule)
        if kept is None:
            pending[root] = "rule %r is not one this version evaluates" % rule
            return None
        if str(params.get("mode") or "keep") == "drop":
            kept = [item for item in items if item not in kept]
        display[root] = "%d items" % len(kept)
        return {"items_out": kept}
    pending[root] = "engine %s is pending" % engine
    return None


def _filtered(items, rule):
    """Items matching a declared comparison, or None when the rule is not one."""
    for operator, test in (
        (">=", lambda left, right: left >= right),
        ("<=", lambda left, right: left <= right),
        ("!=", lambda left, right: left != right),
        ("==", lambda left, right: left == right),
        (">", lambda left, right: left > right),
        ("<", lambda left, right: left < right),
    ):
        if operator not in rule:
            continue
        left_text, right_text = rule.split(operator, 1)
        field = left_text.strip().removeprefix("item").lstrip(".")
        wanted = _coerce(right_text.strip().strip("'" + chr(34)))
        kept = []
        for item in items:
            held = _field(item, field) if field else item
            try:
                if test(held, wanted):
                    kept.append(item)
            except TypeError:
                continue
        return kept
    return None


def _run_graph_expression(node, held, feeds, display, results, pending):
    """Evaluate one released expression over this node's wired inputs."""
    evaluate, expression_root, output_name, source_name = held
    if source_name not in feeds:
        pending[node.root_id] = "input %s is not wired" % source_name
        return None
    value = evaluate(expression_root, {source_name: feeds[source_name]})
    display[node.root_id] = _display(value)
    return {output_name: value}


def run_stem_operation(
    engine: str,
    parameters: Mapping[str, object],
    feeds: Mapping[str, object],
) -> tuple[dict, str]:
    """One stem engine's answer in the effect shape: (outputs, display line).

    The node library and a wired graph must not disagree about what an
    operation means. A second Python copy of "sort by" or "where" would
    drift from this one the first time either is fixed, so the library's
    engines reach this instead of restating the rules.

    Raises ValueError carrying the evaluator's own refusal when the engine
    cannot answer, so the caller reports the same reason the canvas would.
    """
    root = "stem"
    node = StemNode(root_id=root, engine=str(engine), parameters=dict(parameters))
    display: dict[str, str] = {}
    results: dict[str, object] = {}
    pending: dict[str, str] = {}
    produced = _run_engine(node, feeds, display, results, pending)
    if produced is None:
        raise ValueError(pending.get(root) or "engine %s produced nothing" % engine)
    return dict(produced), display.get(root, "")


# The library's engines read the graph's values with the evaluator's own
# rules; these names are the supported way in, so the private helpers stay
# free to change shape without a second module breaking.
coerce_parameter = _coerce
as_list = _as_list
item_field = _field
display_value = _display
