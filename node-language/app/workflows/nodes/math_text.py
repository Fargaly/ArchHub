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
#   value  — result string OR boolean (for `match`) OR list/dict (regex ops)
#
# Ops supported:
#   concat · split · replace · format · match · upper · lower · trim · length
#   regex_findall · regex_match · regex_replace · regex_split


def _str(x: Any) -> str:
    if x is None:
        return ""
    return str(x)


# Ops that operate on a regular-expression `pattern` over the subject `a`.
_REGEX_OPS = ("regex_findall", "regex_match", "regex_replace", "regex_split")


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
        if op in _REGEX_OPS:
            return _text_regex(op, a, inputs, config)
        return {"value": None, "error": f"unknown text op: {op!r}"}
    except Exception as ex:
        return {"value": None, "error": f"{type(ex).__name__}: {ex}"}


def _text_regex(op: str, a: str, inputs: dict, config: dict) -> dict:
    """Regex family for text.op — findall / match / replace / split.

    The subject is the same `a` string text.op already reads (already
    coerced to str by the caller). `pattern` and `repl` come from config,
    but a wired `pattern` / `repl` input wins (matching how the cell lets
    wired input beat config). `ignore_case` maps to re.IGNORECASE.

    TOTAL-TOLERANT: a missing pattern, a non-string subject, or an invalid
    regex (re.error) returns the SAME {"value": None, "error": ...} typed
    shape every other text.op op returns — never a raise.
    """
    # Wired input beats config for pattern + repl.
    raw_pat = inputs.get("pattern")
    pattern = raw_pat if raw_pat is not None else config.get("pattern")
    raw_rep = inputs.get("repl")
    repl = raw_rep if raw_rep is not None else config.get("repl")

    # The subject must be a string. `a` is already _str()-coerced, but a
    # non-string wired subject is a typed error, not a silent stringify.
    subject = inputs.get("a")
    if subject is not None and not isinstance(subject, str):
        return {"value": None,
                "error": f"regex subject must be a string, "
                         f"got {type(subject).__name__}"}

    if pattern is None or not isinstance(pattern, str) or pattern == "":
        return {"value": None, "error": "regex op requires a pattern"}

    flags = re.IGNORECASE if config.get("ignore_case") else 0
    try:
        if op == "regex_findall":
            return {"value": re.findall(pattern, a, flags=flags)}
        if op == "regex_match":
            m = re.search(pattern, a, flags=flags)
            if m is None:
                return {"value": {"matched": False, "groups": [],
                                  "group0": ""}}
            return {"value": {"matched": True,
                              "groups": list(m.groups()),
                              "group0": m.group(0)}}
        if op == "regex_replace":
            return {"value": re.sub(pattern, _str(repl), a, flags=flags)}
        if op == "regex_split":
            return {"value": re.split(pattern, a, flags=flags)}
    except re.error as ex:
        return {"value": None, "error": f"invalid regex: {ex}"}
    return {"value": None, "error": f"unknown text op: {op!r}"}


register(
    NodeSpec(
        type="text.op",
        category="text",
        display_name="Text",
        description="String operations — concat / split / replace / format / "
                    "match / upper / lower / trim / length, plus regex: "
                    "regex_findall / regex_match / regex_replace / regex_split.",
        inputs=[
            Port(name="a", type=PortType.ANY, required=True),
            Port(name="b", type=PortType.ANY),
        ],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "op": {
                "type": "string",
                "enum": ["concat", "split", "replace", "format", "match",
                          "upper", "lower", "trim", "length",
                          "regex_findall", "regex_match", "regex_replace",
                          "regex_split"],
                "required": True,
            },
            "separator":   {"type": "string"},
            "pattern":     {"type": "string",
                            "description": "Regex pattern for match + the "
                                           "regex_* ops (also the literal "
                                           "for replace). Wired `pattern` "
                                           "input wins over this."},
            "replacement": {"type": "string"},
            "repl":        {"type": "string",
                            "description": "Replacement for regex_replace "
                                           "(may use regex backreferences "
                                           "like \\1). Wired `repl` input "
                                           "wins over this."},
            "ignore_case": {"type": "boolean",
                            "description": "Case-insensitive (re.IGNORECASE) "
                                           "for the regex_* ops."},
            "template":    {"type": "string"},
        },
        icon="¶",
    ),
    _text_executor,
)
