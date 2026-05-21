"""MATH + TEXT engine nodes — slice J.

Reference: docs/NODE_GRAMMAR.md MATH + TEXT categories.

Two engines, dispatch on `op`:

  math.op  — arithmetic + comparison + boolean logic
  text.op  — string concat / split / replace / format / match

The grammar primitives (Add / Subtract / Multiply / … and Concat /
Split / …) each pre-set `op` so the user sees a typed, specific node.
Engines stay slim — one dispatcher per family.
"""
from __future__ import annotations

import re
from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ---------------------------------------------------------------------------
# math.op
#
# Inputs:
#   a, b   — operands (b unused for unary / logic_not)
# Output:
#   value  — result
#
# Ops supported:
#   binary numeric : add · sub · mul · div · mod · pow
#   unary numeric  : round · floor · ceil · abs · neg
#   compare        : eq · neq · gt · lt · gte · lte
#   logic          : and · or · not · xor


def _num(x: Any) -> float:
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return False
    if isinstance(x, (int, float)):
        return x != 0
    if isinstance(x, str):
        return x.lower() not in ("", "false", "no", "0", "off")
    if isinstance(x, (list, tuple, dict)):
        return bool(x)
    return bool(x)


_BINARY_NUMERIC = {
    "add": lambda a, b: _num(a) + _num(b),
    "sub": lambda a, b: _num(a) - _num(b),
    "mul": lambda a, b: _num(a) * _num(b),
    "div": lambda a, b: (_num(a) / _num(b)) if _num(b) != 0 else float("nan"),
    "mod": lambda a, b: (_num(a) % _num(b)) if _num(b) != 0 else float("nan"),
    "pow": lambda a, b: _num(a) ** _num(b),
}

_UNARY_NUMERIC = {
    "round": lambda a, b: round(_num(a)),
    "floor": lambda a, b: int(_num(a) // 1) if _num(a) >= 0 else -int(-_num(a) // 1) - 1,
    "ceil":  lambda a, b: -int(-_num(a) // 1),
    "abs":   lambda a, b: abs(_num(a)),
    "neg":   lambda a, b: -_num(a),
}

_COMPARE = {
    "eq":  lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt":  lambda a, b: _num(a) > _num(b),
    "lt":  lambda a, b: _num(a) < _num(b),
    "gte": lambda a, b: _num(a) >= _num(b),
    "lte": lambda a, b: _num(a) <= _num(b),
}

_LOGIC = {
    "and": lambda a, b: _bool(a) and _bool(b),
    "or":  lambda a, b: _bool(a) or _bool(b),
    "xor": lambda a, b: _bool(a) != _bool(b),
    "not": lambda a, b: not _bool(a),
}


def _math_executor(config: dict, inputs: dict, ctx) -> dict:
    op = (config.get("op") or "add").strip()
    a = inputs.get("a")
    b = inputs.get("b")
    for table in (_BINARY_NUMERIC, _UNARY_NUMERIC, _COMPARE, _LOGIC):
        if op in table:
            try:
                return {"value": table[op](a, b)}
            except Exception as ex:
                return {"value": None, "error": f"{type(ex).__name__}: {ex}"}
    return {"value": None, "error": f"unknown math op: {op!r}"}


register(
    NodeSpec(
        type="math.op",
        category="math",
        display_name="Math",
        description="Arithmetic + comparison + boolean logic. `op` config picks the operation.",
        inputs=[
            Port(name="a", type=PortType.ANY, required=True),
            Port(name="b", type=PortType.ANY),
        ],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "op": {
                "type": "string",
                "enum": (list(_BINARY_NUMERIC.keys())
                         + list(_UNARY_NUMERIC.keys())
                         + list(_COMPARE.keys())
                         + list(_LOGIC.keys())),
                "description": "Operation to apply",
                "required": True,
            },
        },
        icon="∑",
    ),
    _math_executor,
)


# ---------------------------------------------------------------------------
# text.op
#
# Inputs:
#   a, b   — strings (b unused for unary ops)
# Output:
#   value  — result string OR boolean (for `match`)
#
# Ops supported:
#   concat · split · replace · format · match · upper · lower · trim · length


def _str(x: Any) -> str:
    if x is None:
        return ""
    return str(x)


def _text_executor(config: dict, inputs: dict, ctx) -> dict:
    op = (config.get("op") or "concat").strip()
    a = _str(inputs.get("a"))
    b = _str(inputs.get("b"))
    sep = config.get("separator")
    pat = config.get("pattern")
    rep = config.get("replacement")
    fmt = config.get("template")
    try:
        if op == "concat":
            join = sep if sep is not None else ""
            return {"value": a + join + b}
        if op == "split":
            return {"value": a.split(sep) if sep else a.split()}
        if op == "replace":
            return {"value": a.replace(pat or "", rep or "")}
        if op == "format":
            template = fmt or a
            args = inputs.get("args") or {}
            if not isinstance(args, dict):
                args = {"value": args}
            return {"value": template.format(**args, a=a, b=b)}
        if op == "match":
            return {"value": bool(re.search(pat or "", a))}
        if op == "upper":
            return {"value": a.upper()}
        if op == "lower":
            return {"value": a.lower()}
        if op == "trim":
            return {"value": a.strip()}
        if op == "length":
            return {"value": len(a)}
        return {"value": None, "error": f"unknown text op: {op!r}"}
    except Exception as ex:
        return {"value": None, "error": f"{type(ex).__name__}: {ex}"}


register(
    NodeSpec(
        type="text.op",
        category="text",
        display_name="Text",
        description="String operations — concat / split / replace / format / match / upper / lower / trim / length.",
        inputs=[
            Port(name="a", type=PortType.ANY, required=True),
            Port(name="b", type=PortType.ANY),
        ],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "op": {
                "type": "string",
                "enum": ["concat", "split", "replace", "format", "match",
                          "upper", "lower", "trim", "length"],
                "required": True,
            },
            "separator":   {"type": "string"},
            "pattern":     {"type": "string"},
            "replacement": {"type": "string"},
            "template":    {"type": "string"},
        },
        icon="¶",
    ),
    _text_executor,
)
