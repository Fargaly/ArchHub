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

# Text ops whose Python form needs a config value (separator / pattern /
# replacement) baked in as a literal. These ARE flattenable — the value is a
# config constant, not a second wired operand — but they can't use the simple
# `{a}/{b}` template path because the literal is interpolated from config.
# Handled specially in `_build_expr` (`_text_config_op`). Each entry maps the
# op to the config keys it consumes (in `text.op`'s executor semantics).
_TEXT_CONFIG_OPS: dict[str, tuple[str, ...]] = {
    "replace": ("pattern", "replacement"),
    "split":   ("separator",),
}

# Ops the engine supports but that CANNOT be expressed as a single sandbox-safe
# (`safe_mode=True`) Python expression on the flattened code node — so flatten
# returns a TYPED, structured "not-flattenable" reason instead of a bare error.
# The flattened code node ships with safe_mode=True, whose sandbox blocks
# `import` and exposes no `re` module, so the regex family + `match` can't run
# there; `format` needs a wired `args` mapping + kwargs the single-output code
# node has no port for. The reason carries a machine code + a plain-English
# explanation the UI shows verbatim (no opaque toast).
_TEXT_NOT_FLATTENABLE: dict[str, str] = {
    "match":          "needs the `re` module, which the flattened code "
                      "node's sandbox does not allow",
    "format":         "needs a wired `args` mapping the single-output code "
                      "node can't carry",
    "regex_findall":  "needs the `re` module, which the flattened code "
                      "node's sandbox does not allow",
    "regex_match":    "needs the `re` module, which the flattened code "
                      "node's sandbox does not allow",
    "regex_replace":  "needs the `re` module, which the flattened code "
                      "node's sandbox does not allow",
    "regex_split":    "needs the `re` module, which the flattened code "
                      "node's sandbox does not allow",
}


FLATTENABLE_TYPES = {
    "math.op", "text.op", "data.constant", "data.passthrough",
}

# Reason codes the public API attaches to a typed "not-flattenable" result so
# the UI can branch on a machine value rather than parse a string.
REASON_UNFLATTENABLE_TYPE = "unflattenable_type"
REASON_UNSUPPORTED_OP = "unsupported_op"
REASON_OP_NOT_EXPRESSIBLE = "op_not_expressible"
REASON_CYCLE = "cycle"
REASON_STRUCTURE = "structure"


class _ChainError(Exception):
    """Raised when the chain can't be flattened — wrapped into the
    public API as a typed dict error.

    Carries a machine-readable `reason` code + optional structured fields
    (`op`, `node`, `supported`, `node_type`) so the public API surfaces a
    TYPED "not-flattenable" result the UI can explain — never an opaque
    string. `flattenable` is False on every _ChainError by construction."""

    def __init__(self, message: str, *, reason: str = REASON_STRUCTURE,
                 **fields: Any):
        super().__init__(message)
        self.reason = reason
        self.fields = fields

    def as_result(self) -> dict:
        out: dict = {
            "error": str(self),
            "reason": self.reason,
            "flattenable": False,
        }
        out.update({k: v for k, v in self.fields.items() if v is not None})
        return out


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
            f"(flattenable: {sorted(FLATTENABLE_TYPES)})",
            reason=REASON_UNFLATTENABLE_TYPE,
            node=node.get("id"), node_type=t,
            supported=sorted(FLATTENABLE_TYPES))
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
        raise _ChainError(f"cycle detected at node {node_id!r}",
                          reason=REASON_CYCLE, node=node_id)
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

    # Text ops with a config-baked literal (replace / split) — flattenable,
    # but the literal is interpolated from config, not a wired operand.
    if t == "text.op" and op in _TEXT_CONFIG_OPS:
        return _text_config_op(op, _resolve("a"), cfg)

    # Engine ops that genuinely can't be a single sandbox-safe expression
    # (regex family / match / format) → TYPED not-flattenable reason, never a
    # bare error. coverage == op count is satisfied by classifying EVERY op:
    # expressible → code; inexpressible → typed reason.
    if t == "text.op" and op in _TEXT_NOT_FLATTENABLE:
        raise _ChainError(
            f"text op {op!r} on node {node_id!r} can't be flattened: "
            f"{_TEXT_NOT_FLATTENABLE[op]}",
            reason=REASON_OP_NOT_EXPRESSIBLE, op=op, node=node_id,
            node_type=t, detail=_TEXT_NOT_FLATTENABLE[op])

    template = _MATH_TEMPLATES.get(op) if t == "math.op" \
        else _TEXT_TEMPLATES.get(op)
    if not template:
        # Op the engine doesn't define at all (typo / future op) → typed
        # unsupported-op reason carrying the full supported set.
        raise _ChainError(
            f"op {op!r} on node {node_id!r} not supported for flatten "
            f"(supported math: {sorted(_MATH_TEMPLATES)}; "
            f"text: {sorted(_TEXT_TEMPLATES) + sorted(_TEXT_CONFIG_OPS)})",
            reason=REASON_UNSUPPORTED_OP, op=op, node=node_id, node_type=t,
            supported_math=sorted(_MATH_TEMPLATES),
            supported_text=sorted(_TEXT_TEMPLATES) + sorted(_TEXT_CONFIG_OPS))

    a_expr = _resolve("a")
    needs_b = "{b}" in template
    b_expr = _resolve("b") if needs_b else ""
    return template.format(a=a_expr, b=b_expr)


def _text_config_op(op: str, a_expr: str, cfg: dict) -> str:
    """Build the Python expression for a text.op whose argument is a config
    literal (replace / split). Mirrors `text.op`'s executor semantics so the
    flattened code cooks to the SAME value as the original node:

      replace → str(a).replace(<pattern>, <replacement>)
      split   → str(a).split(<sep>)   (no-arg split on whitespace if sep falsy)
    """
    if op == "replace":
        pat = _python_literal(cfg.get("pattern") or "")
        rep = _python_literal(cfg.get("replacement") or "")
        return f"str({a_expr}).replace({pat}, {rep})"
    if op == "split":
        sep = cfg.get("separator")
        # text.op: `a.split(sep) if sep else a.split()` — empty/falsy sep
        # splits on runs of whitespace.
        if sep:
            return f"str({a_expr}).split({_python_literal(sep)})"
        return f"str({a_expr}).split()"
    # Unreachable — guarded by the caller's membership check.
    raise _ChainError(f"config op {op!r} has no expression form",
                      reason=REASON_OP_NOT_EXPRESSIBLE, op=op)


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
        return {"error": "no nodes selected", "reason": REASON_STRUCTURE,
                "flattenable": False}
    for nid in node_ids:
        if nid not in nodes_by_id:
            return {"error": f"selected node {nid!r} not in graph",
                    "reason": REASON_STRUCTURE, "flattenable": False,
                    "node": nid}

    # Validate every node is flattenable up front (better error).
    try:
        for nid in node_ids:
            _classify_flattenable(nodes_by_id[nid])
    except _ChainError as ex:
        return ex.as_result()

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
                          "feeds another selected node (cycle?)",
                "reason": REASON_CYCLE, "flattenable": False}
    if len(tails) > 1:
        return {"error": f"multiple chain tails ({len(tails)}); "
                          "flatten only handles single-output chains "
                          "today",
                "reason": REASON_STRUCTURE, "flattenable": False,
                "tails": tails}
    tail_id = tails[0]

    external_vars: dict = {}
    try:
        expr = _build_expr(tail_id, node_set, nodes_by_id, wires,
                            external_vars)
    except _ChainError as ex:
        return ex.as_result()

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
        # Propagate the FULL typed result (error + reason + structured
        # fields), not just the string — the UI branches on `reason`.
        return flat

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


def op_coverage(engine_type: str) -> dict:
    """Classify EVERY op the given engine type (`math.op` / `text.op`)
    supports into one of three buckets, proving coverage == op count:

      expressible    — ops flatten produces code for (template or config-op)
      not_expressible — ops flatten classifies with a TYPED not-flattenable
                        reason (genuinely can't be a sandbox-safe expression)
      unknown        — ops flatten neither emits code for NOR has a typed
                        reason for (this set MUST be empty — its emptiness is
                        the coverage gate)

    Sources the engine's authoritative op set from the registered NodeSpec's
    `config_schema["op"]["enum"]`, so a new engine op that flatten forgets to
    classify shows up in `unknown` and fails the gate.
    """
    engine_ops = _engine_ops(engine_type)
    if engine_type == "math.op":
        expressible = set(_MATH_TEMPLATES)
        not_expressible: set[str] = set()
    elif engine_type == "text.op":
        expressible = set(_TEXT_TEMPLATES) | set(_TEXT_CONFIG_OPS)
        not_expressible = set(_TEXT_NOT_FLATTENABLE)
    else:
        expressible = set()
        not_expressible = set()
    classified = expressible | not_expressible
    unknown = engine_ops - classified
    return {
        "engine_type": engine_type,
        "engine_ops": sorted(engine_ops),
        "expressible": sorted(expressible & engine_ops),
        "not_expressible": sorted(not_expressible & engine_ops),
        "unknown": sorted(unknown),
        "covered": not unknown,
        "op_count": len(engine_ops),
        "coverage_count": len(classified & engine_ops),
    }


def _engine_ops(engine_type: str) -> set[str]:
    """The authoritative op set for an engine type, read from its registered
    NodeSpec config_schema enum. Empty set if the type isn't registered."""
    try:
        from .registry import get as _reg_get
        tup = _reg_get(engine_type)
    except Exception:
        tup = None
    if not tup:
        return set()
    schema = getattr(tup[0], "config_schema", None) or {}
    op_field = schema.get("op") or {}
    return set(op_field.get("enum") or [])


__all__ = [
    "chain_to_expression",
    "flatten_chain",
    "FLATTENABLE_TYPES",
    "op_coverage",
    "REASON_UNFLATTENABLE_TYPE",
    "REASON_UNSUPPORTED_OP",
    "REASON_OP_NOT_EXPRESSIBLE",
    "REASON_CYCLE",
    "REASON_STRUCTURE",
]
