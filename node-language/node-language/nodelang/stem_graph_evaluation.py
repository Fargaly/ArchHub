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

Honest about what it cannot run. An engine this version does not carry
(ai.master, skill.wrap, expression-driven shapes) marks its node
"pending" and everything downstream of it "blocked" -- never a guess,
never a crash.

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
    """One wire between declared interfaces."""

    source: str
    source_interface: str
    target: str
    target_interface: str


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


def evaluate_stem_graph(
    nodes: Sequence[StemNode],
    wires: Sequence[StemWire],
    graph_expressions: "Mapping[str, object] | None" = None,
    effect_engines: "Mapping[str, object] | None" = None,
) -> StemEvaluation:
    """Every declared output's value, walked from constants to results."""
    by_root = {node.root_id: node for node in nodes}
    incoming: dict[str, dict[str, tuple[str, str]]] = {}
    for wire in wires:
        if wire.source not in by_root or wire.target not in by_root:
            continue
        incoming.setdefault(wire.target, {})[wire.target_interface] = (
            wire.source, wire.source_interface
        )

    outputs: dict[str, dict[str, object]] = {}
    display: dict[str, str] = {}
    results: dict[str, object] = {}
    pending: dict[str, str] = {}
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
            for name, (src, src_if) in (incoming.get(root) or {}).items():
                upstream = resolve(src)
                if upstream is None:
                    pending.setdefault(root, "blocked by %s" % src)
                    return None
                if src_if not in upstream:
                    pending[root] = "no value on %s.%s" % (src, src_if)
                    return None
                feeds[name] = upstream[src_if]
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
        condition = feeds.get("condition", bool(value))
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
        key = str(feeds.get("key") or "a").strip().lower()
        branch = key if key in ("a", "b", "c") else "a"
        display[root] = branch
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
