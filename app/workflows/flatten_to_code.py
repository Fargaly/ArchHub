"""SLICE L — flatten chain to code (AgDR-0020 follow-up).

Pure-Python utility: convert a chain of math/text/constant/passthrough
nodes into a single `code.expression` node. Bridge slot + JSX action
call into here. Logic stays out of JSX so it's testable + reusable.

Algorithm:
  1. Validate: every selected node is FLATTENABLE
     (math.op | text.op | data.constant | data.passthrough).
  2. Find chain head (node with no incoming wire FROM another selected
     node) and chain tail (node with no outgoing wire TO another
     selected node).
  3. Recursively build a Python expression by walking back from the
     tail, substituting external-input ports with `a`/`b`/`c`/...
     symbols on the new code node.
  4. Return a rewritten graph with:
     - Selected nodes removed.
     - One new code.expression node inserted at the tail's position
       carrying the generated expression.
     - External wires re-pointed to the new code node.
"""
from __future__ import annotations

from typing import Any


# ── op → Python expression template ──────────────────────────────────
#
# Templates use `{a}` / `{b}` placeholders for the operand expressions
# (sub-expressions are inserted recursively). Parentheses keep
# precedence correct for nested templates.

_MATH_TEMPLATES: dict[str, str] = {
    "add":   "({a} + {b})",
    "sub":   "({a} - {b})",
    "mul":   "({a} * {b})",
    "div":   "({a} / {b})",
    "mod":   "({a} % {b})",
    "pow":   "({a} ** {b})",
    "round": "round({a})",
    "floor": "int(({a}) // 1)",
    "ceil":  "(-int(-({a}) // 1))",
    "abs":   "abs({a})",
    "neg":   "(-({a}))",
    "eq":    "({a} == {b})",
    "neq":   "({a} != {b})",
    "gt":    "({a} > {b})",
    "lt":    "({a} < {b})",
    "gte":   "({a} >= {b})",
    "lte":   "({a} <= {b})",
    "and":   "({a} and {b})",
    "or":    "({a} or {b})",
    "xor":   "(bool({a}) != bool({b}))",
    "not":   "(not {a})",
}

_TEXT_TEMPLATES: dict[str, str] = {
    "concat": "(str({a}) + str({b}))",
    "upper":  "str({a}).upper()",
    "lower":  "str({a}).lower()",
    "trim":   "str({a}).strip()",
    "length": "len(str({a}))",
}


FLATTENABLE_TYPES = {
    "math.op", "text.op", "data.constant", "data.passthrough",
}


class _ChainError(Exception):
    """Raised when the chain can't be flattened — wrapped into the
    public API as a typed dict error."""


# ── helpers — wire / node lookup ────────────────────────────────────


def _wire_src(w: dict) -> tuple:
    f = w.get("from") or [w.get("src_node"), w.get("src_port")]
    f = list(f) + [None, None]
    return (f[0], f[1])


def _wire_dst(w: dict) -> tuple:
    t = w.get("to") or [w.get("dst_node"), w.get("dst_port")]
    t = list(t) + [None, None]
    return (t[0], t[1])


def _python_literal(value: Any) -> str:
    """Render a Python literal — for `data.constant` collapse."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (list, tuple, dict)):
        return repr(value)
    return repr(str(value))


# ── chain validation ────────────────────────────────────────────────


def _classify_flattenable(node: dict) -> str:
    """Return the engine type if node is flattenable, else raise."""
    t = node.get("type")
    if not t:
        # Try resolution via grammar.
        kind = node.get("kind") or node.get("cat") or ""
        try:
            from .node_grammar import engine_type
            cfg = node.get("config") if isinstance(node.get("config"),
                                                     dict) else {}
            t = engine_type(kind, cfg)
        except Exception:
            t = None
    if t not in FLATTENABLE_TYPES:
        raise _ChainError(
            f"node {node.get('id')!r} type {t!r} is not flattenable "
            f"(flattenable: {sorted(FLATTENABLE_TYPES)})")
    return t


# ── expression building ─────────────────────────────────────────────


def _build_expr(node_id: str,
                 node_set: set,
                 nodes_by_id: dict,
                 wires: list,
                 external_vars: dict,
                 _stack: set | None = None) -> str:
    """Recursively build a Python expression for `node_id`.

    `external_vars` is keyed by (upstream_node_id, port_name) →
    variable symbol on the new code node (`a`, `b`, `c`, ...). New
    upstream connections allocate symbols on the fly.

    Raises `_ChainError` for cycles / unflattenable nodes / unknown ops.
    """
    if _stack is None:
        _stack = set()
    if node_id in _stack:
        raise _ChainError(f"cycle detected at node {node_id!r}")
    if node_id not in node_set:
        # Reached an EXTERNAL upstream — allocate a symbol.
        return _alloc_external(node_id, "", external_vars)
    _stack = _stack | {node_id}
    node = nodes_by_id.get(node_id)
    if not node:
        raise _ChainError(f"unknown node id {node_id!r}")
    t = _classify_flattenable(node)
    cfg = node.get("config") if isinstance(node.get("config"), dict) \
        else {}

    if t == "data.constant":
        return _python_literal(cfg.get("value"))

    if t == "data.passthrough":
        # Pass through whatever's on the `value` input. If no wire
        # feeds it, return None.
        src = _find_upstream(node_id, "value", wires)
        if src is None:
            return "None"
        src_id, src_port = src
        if src_id in node_set:
            return _build_expr(src_id, node_set, nodes_by_id, wires,
                                external_vars, _stack)
        return _alloc_external(src_id, src_port, external_vars)

    # Math + text dispatch on op.
    op = (cfg.get("op") or "").strip()
    template = _MATH_TEMPLATES.get(op) if t == "math.op" \
        else _TEXT_TEMPLATES.get(op)
    if not template:
        raise _ChainError(
            f"op {op!r} on node {node_id!r} not supported for flatten "
            f"(supported math: {sorted(_MATH_TEMPLATES)}; "
            f"text: {sorted(_TEXT_TEMPLATES)})")

    def _resolve(port: str) -> str:
        src = _find_upstream(node_id, port, wires)
        if src is None:
            # No wire on this port — emit None.
            return "None"
        src_id, src_port = src
        if src_id in node_set:
            return _build_expr(src_id, node_set, nodes_by_id, wires,
                                external_vars, _stack)
        return _alloc_external(src_id, src_port, external_vars)

    a_expr = _resolve("a")
    needs_b = "{b}" in template
    b_expr = _resolve("b") if needs_b else ""
    return template.format(a=a_expr, b=b_expr)


def _find_upstream(node_id: str, port: str, wires: list) -> tuple | None:
    """Return (src_id, src_port) for the wire whose destination is
    `(node_id, port)`. None if no wire."""
    for w in wires:
        d_id, d_port = _wire_dst(w)
        if d_id == node_id and (d_port == port or port == "*"):
            return _wire_src(w)
    return None


def _alloc_external(upstream_id: str, upstream_port: str,
                     external_vars: dict) -> str:
    """Return the variable symbol for an external upstream port.
    Allocates new symbols `a`, `b`, `c`, … on first encounter."""
    key = (upstream_id, upstream_port)
    if key not in external_vars:
        used = len(external_vars)
        # Symbols a, b, c, d, e, f, g, h.
        sym = chr(ord("a") + used) if used < 8 else f"v{used}"
        external_vars[key] = sym
    return external_vars[key]


# ── public API ──────────────────────────────────────────────────────


def chain_to_expression(graph: dict, node_ids: list) -> dict:
    """Build a Python expression that's semantically equivalent to
    the chain formed by `node_ids` inside `graph`.

    Returns `{expression, external_inputs, tail_id, tail_node,
    error?}`.

    `external_inputs` is a list of `{symbol, src_node, src_port}`
    in stable iteration order — the new code node's wires use these
    to attach to upstream sources.

    `tail_id` is the chain's output (the node whose output goes
    outside the chain). The new code node replaces it.
    """
    nodes_by_id = {n.get("id"): n for n in (graph.get("nodes") or [])}
    wires = graph.get("wires") or []
    node_set = set(node_ids)

    if not node_ids:
        return {"error": "no nodes selected"}
    for nid in node_ids:
        if nid not in nodes_by_id:
            return {"error": f"selected node {nid!r} not in graph"}

    # Validate every node is flattenable up front (better error).
    try:
        for nid in node_ids:
            _classify_flattenable(nodes_by_id[nid])
    except _ChainError as ex:
        return {"error": str(ex)}

    # Find tail: a selected node with no outgoing wire to ANOTHER
    # selected node (its output goes to the outside world OR nowhere).
    tails: list[str] = []
    for nid in node_ids:
        outgoing = [w for w in wires if _wire_src(w)[0] == nid]
        if not outgoing or all(
                _wire_dst(w)[0] not in node_set for w in outgoing):
            tails.append(nid)
    if not tails:
        return {"error": "no chain tail — every selected node "
                          "feeds another selected node (cycle?)"}
    if len(tails) > 1:
        return {"error": f"multiple chain tails ({len(tails)}); "
                          "flatten only handles single-output chains "
                          "today"}
    tail_id = tails[0]

    external_vars: dict = {}
    try:
        expr = _build_expr(tail_id, node_set, nodes_by_id, wires,
                            external_vars)
    except _ChainError as ex:
        return {"error": str(ex)}

    # Order external inputs by allocation order (a, b, c, ...).
    inputs_in_order = sorted(external_vars.items(),
                              key=lambda kv: kv[1])
    external_inputs = [
        {"symbol": sym, "src_node": src_id, "src_port": src_port}
        for (src_id, src_port), sym in inputs_in_order
    ]
    return {
        "expression":      expr,
        "external_inputs": external_inputs,
        "tail_id":         tail_id,
        "tail_node":       nodes_by_id[tail_id],
    }


def flatten_chain(graph: dict, node_ids: list,
                   new_node_id: str | None = None) -> dict:
    """Rewrite `graph` replacing the chain `node_ids` with one
    `code.expression` node carrying the flattened expression.

    Returns `{graph, error?}`. The `graph` field is a NEW dict —
    the input is not mutated.

    Wires rewriting:
      - External upstream wires → new code node, port = allocated symbol.
      - Downstream wires whose source was the chain tail → new code
        node, port = `value` (the code node's output).
      - Wires fully INTERNAL to the chain → dropped.
    """
    flat = chain_to_expression(graph, node_ids)
    if "error" in flat:
        return {"error": flat["error"]}

    expr = flat["expression"]
    externals = flat["external_inputs"]
    tail_id = flat["tail_id"]
    tail_node = flat["tail_node"]
    node_set = set(node_ids)

    new_id = new_node_id or f"code_{tail_id}"
    new_node: dict = {
        "id":   new_id,
        "type": "code.expression",
        "kind": "code",
        "cat":  "code",
        "config": {"expr": expr, "mode": "expression",
                    "safe_mode": True},
        "params": [
            {"k": "mode", "v": "expression", "type": "text"},
            {"k": "expr", "v": expr, "type": "text"},
            {"k": "safe_mode", "v": True, "type": "boolean"},
        ],
        "x": tail_node.get("x", 0),
        "y": tail_node.get("y", 0),
        "w": tail_node.get("w", 240),
        "h": tail_node.get("h", 112),
        "_user": True,
        "ins":  [{"id": e["symbol"], "label": e["symbol"], "t": "any"}
                  for e in externals],
        "outs": [{"id": "value", "label": "value", "t": "any"}],
    }

    # Remove the chain nodes; keep everything else.
    remaining_nodes = [n for n in (graph.get("nodes") or [])
                       if n.get("id") not in node_set]
    remaining_nodes.append(new_node)

    # Rewrite wires.
    # 1. Drop wires whose endpoints are BOTH inside the chain (purely internal).
    # 2. External-upstream wires get retargeted: from (upstream, upstream_port)
    #    to (new_id, allocated_symbol).
    # 3. Downstream wires sourced at tail_id get retargeted: from
    #    (new_id, "value") to (downstream, downstream_port).
    # 4. Other downstream wires sourced at a non-tail chain node — these
    #    are silently lost (the chain's intermediate outputs go away).
    sym_for_external = {(e["src_node"], e["src_port"]): e["symbol"]
                         for e in externals}
    new_wires: list = []
    for w in (graph.get("wires") or []):
        s_id, s_port = _wire_src(w)
        d_id, d_port = _wire_dst(w)
        s_in = s_id in node_set
        d_in = d_id in node_set
        if s_in and d_in:
            continue  # purely internal — dropped.
        if not s_in and d_in:
            # External feeds chain — map to (new_id, symbol).
            sym = sym_for_external.get((s_id, s_port))
            if sym is None:
                # Not in our allocated set (port wasn't referenced by
                # the expression — e.g. dangling input) — drop.
                continue
            nw = dict(w)
            nw["from"] = [s_id, s_port]
            nw["to"] = [new_id, sym]
            new_wires.append(nw)
            continue
        if s_in and not d_in:
            # Chain feeds external. Only the tail's outputs are useful.
            if s_id != tail_id:
                continue
            nw = dict(w)
            nw["from"] = [new_id, "value"]
            nw["to"] = [d_id, d_port]
            new_wires.append(nw)
            continue
        # both external — keep as-is
        new_wires.append(dict(w))

    return {
        "graph": {
            **graph,
            "nodes": remaining_nodes,
            "wires": new_wires,
        },
        "new_node_id": new_id,
        "expression": expr,
    }


__all__ = [
    "chain_to_expression",
    "flatten_chain",
    "FLATTENABLE_TYPES",
]
