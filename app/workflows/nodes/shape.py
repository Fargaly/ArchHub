"""Shape + observe primitives — filter, transform, watch.

Node-system redesign slices 6-7 (docs/NODE_GRAMMAR.md). Three small,
pure, dependency-free executors so the `filter` / `transform` / `watch`
grammar primitives flip from NEEDS_EXECUTOR to READY.

  filter.apply     — keep/drop list items by a field/op/match predicate
  transform.apply  — map/reshape data (count, pick, first, unique, ...)
  watch.preview    — pass data through + emit a short text preview
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


def _as_list(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [] if value is None else [value]


def _num(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _preview(value: Any, limit: int = 280) -> str:
    try:
        s = repr(value)
    except Exception:
        s = f"<{type(value).__name__}>"
    return s if len(s) <= limit else s[:limit] + "…"


# ── filter.apply ──────────────────────────────────────────────────────
_FILTER_OPS = {
    "eq":       lambda a, b: a == b,
    "ne":       lambda a, b: a != b,
    "gt":       lambda a, b: _num(a) > _num(b),
    "lt":       lambda a, b: _num(a) < _num(b),
    "ge":       lambda a, b: _num(a) >= _num(b),
    "le":       lambda a, b: _num(a) <= _num(b),
    "contains": lambda a, b: str(b) in str(a),
    "truthy":   lambda a, b: bool(a),
}


def _filter_executor(config: dict, inputs: dict, ctx) -> dict:
    items = _as_list(inputs.get("value"))
    config = config or {}
    field = config.get("field") or ""
    op = config.get("op") or "truthy"
    match = config.get("match")
    test = _FILTER_OPS.get(op)
    if test is None:
        return {"status": "error",
                "error": f"unknown filter op {op!r} "
                         f"(want one of {sorted(_FILTER_OPS)})"}
    kept = []
    for it in items:
        v = it.get(field) if (field and isinstance(it, dict)) else it
        try:
            if test(v, match):
                kept.append(it)
        except Exception:
            pass  # an item that cannot be compared is dropped, not fatal
    return {"value": kept, "count": len(kept)}


register(
    NodeSpec(
        type="filter.apply", category="data", display_name="Filter",
        description="Keep list items matching a field/op/match predicate.",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY),
                 Port(name="count", type=PortType.ANY)],
        config_schema={
            "field": {"type": "string"},
            "op":    {"type": "string", "enum": sorted(_FILTER_OPS)},
            "match": {},
        },
        icon="⧩",
    ),
    _filter_executor,
)


# ── transform.apply ───────────────────────────────────────────────────
def _transform_executor(config: dict, inputs: dict, ctx) -> dict:
    value = inputs.get("value")
    config = config or {}
    op = config.get("op") or "identity"
    field = config.get("field") or ""
    items = _as_list(value)
    if op == "identity":
        return {"value": value}
    if op == "count":
        return {"value": len(items)}
    if op == "first":
        return {"value": items[0] if items else None}
    if op == "last":
        return {"value": items[-1] if items else None}
    if op == "pick":
        return {"value": [it.get(field) if isinstance(it, dict) else it
                          for it in items]}
    if op == "unique":
        out: list = []
        for it in items:
            if it not in out:
                out.append(it)
        return {"value": out}
    if op == "sort":
        try:
            key = (lambda it: it.get(field)) if field else None
            return {"value": sorted(items, key=key)}
        except Exception:
            return {"value": items}
    if op == "flatten":
        out = []
        for it in items:
            out.extend(it) if isinstance(it, (list, tuple)) else out.append(it)
        return {"value": out}
    return {"status": "error", "error": f"unknown transform op {op!r}"}


register(
    NodeSpec(
        type="transform.apply", category="data", display_name="Transform",
        description="Map / reshape data: count, pick, first, last, "
                    "unique, sort, flatten, identity.",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY)],
        config_schema={
            "op":    {"type": "string",
                      "enum": ["identity", "count", "first", "last",
                               "pick", "unique", "sort", "flatten"]},
            "field": {"type": "string"},
        },
        icon="⤳",
    ),
    _transform_executor,
)


# ── watch.preview ─────────────────────────────────────────────────────
def _watch_executor(config: dict, inputs: dict, ctx) -> dict:
    """Pure passthrough that also emits a short preview. `as` is a
    render hint the JSX watch node reads (list/table/json/...); the
    executor never alters the data."""
    value = inputs.get("value")
    return {"value": value, "preview": _preview(value)}


register(
    NodeSpec(
        type="watch.preview", category="data", display_name="Watch",
        description="Watcher — passes data through unchanged and emits "
                    "a preview for inline display.",
        inputs=[Port(name="value", type=PortType.ANY, required=True)],
        outputs=[Port(name="value", type=PortType.ANY),
                 Port(name="preview", type=PortType.STRING)],
        config_schema={"as": {"type": "string",
                              "enum": ["list", "table", "json",
                                       "view", "model", "image"]}},
        icon="◉",
    ),
    _watch_executor,
)
