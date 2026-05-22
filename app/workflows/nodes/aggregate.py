"""Aggregate primitives — AgDR-0039 slice 2.

Four list-aggregate operators that round out the logic vocabulary, so a
node's logic can be COMPOSED from primitives instead of an opaque code
blob (the founder's modular-logic mandate):

  data.reduce      — fold a list to a single value (sum/product/min/max/…)
  data.accumulate  — running fold → the list of intermediate results
  data.sort        — sort a list, optionally by an item key
  data.group_by    — partition a list of records by a key field

Pure + side-effect-free. No host, no LLM.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ── shared helpers ───────────────────────────────────────────────────

def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _num(x):
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)):
        return x
    try:
        return float(x)
    except Exception:
        return 0


def _sortable(v):
    """A total-order key — mixed-type lists never raise a TypeError."""
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (1, int(v))
    if isinstance(v, (int, float)):
        return (1, v)
    return (2, str(v))


# Identity per op — what `reduce` of an EMPTY list returns (no `init`).
# min / max have no identity → None for an empty list.
_REDUCE_IDENTITY = {
    "sum": 0, "product": 1, "count": 0, "concat": "",
    "and": True, "or": False,
}

_REDUCE_OPS = {
    "sum":     lambda acc, x: (0 if acc is None else acc) + _num(x),
    "product": lambda acc, x: (1 if acc is None else acc) * _num(x),
    "min":     lambda acc, x: _num(x) if acc is None else min(acc, _num(x)),
    "max":     lambda acc, x: _num(x) if acc is None else max(acc, _num(x)),
    "count":   lambda acc, x: (0 if acc is None else acc) + 1,
    "concat":  lambda acc, x: ("" if acc is None else str(acc)) + str(x),
    "and":     lambda acc, x: bool(x) if acc is None else (acc and bool(x)),
    "or":      lambda acc, x: bool(x) if acc is None else (acc or bool(x)),
}


# ── data.reduce ──────────────────────────────────────────────────────

def _reduce_executor(config: dict, inputs: dict, ctx) -> dict:
    items = _as_list((inputs or {}).get("items"))
    op = str((config or {}).get("op", "sum") or "sum")
    fn = _REDUCE_OPS.get(op)
    if fn is None:
        return {"status": "error", "value": None,
                "error": f"reduce: unknown op {op!r} — want one of "
                         f"{', '.join(_REDUCE_OPS)}"}
    acc = (inputs or {}).get("init")
    if acc is None:
        acc = _REDUCE_IDENTITY.get(op)   # empty list -> the op's identity
    try:
        for x in items:
            acc = fn(acc, x)
    except Exception as ex:
        return {"status": "error", "value": None,
                "error": f"{type(ex).__name__}: {ex}"}
    return {"status": "ok", "value": acc}


register(NodeSpec(
    type="data.reduce", category="data", display_name="Reduce",
    description="Fold a list to one value — sum / product / min / max / "
                "count / concat / and / or. Optional `init` seed.",
    inputs=[Port(name="items", type=PortType.LIST, required=True),
            Port(name="init",  type=PortType.ANY)],
    outputs=[Port(name="value", type=PortType.ANY)],
    config_schema={"op": {"type": "string", "default": "sum",
                          "options": list(_REDUCE_OPS)}},
    icon="Σ"), _reduce_executor)


# ── data.accumulate ──────────────────────────────────────────────────

def _accumulate_executor(config: dict, inputs: dict, ctx) -> dict:
    items = _as_list((inputs or {}).get("items"))
    op = str((config or {}).get("op", "sum") or "sum")
    fn = _REDUCE_OPS.get(op)
    if fn is None:
        return {"status": "error", "series": [],
                "error": f"accumulate: unknown op {op!r}"}
    acc = (inputs or {}).get("init")
    if acc is None:
        acc = _REDUCE_IDENTITY.get(op)
    series: list = []
    try:
        for x in items:
            acc = fn(acc, x)
            series.append(acc)
    except Exception as ex:
        return {"status": "error", "series": [],
                "error": f"{type(ex).__name__}: {ex}"}
    return {"status": "ok", "series": series, "value": acc}


register(NodeSpec(
    type="data.accumulate", category="data", display_name="Accumulate",
    description="Running fold over a list — emit `series`, the list of "
                "intermediate results, plus the final `value`.",
    inputs=[Port(name="items", type=PortType.LIST, required=True),
            Port(name="init",  type=PortType.ANY)],
    outputs=[Port(name="series", type=PortType.LIST),
             Port(name="value",  type=PortType.ANY)],
    config_schema={"op": {"type": "string", "default": "sum",
                          "options": list(_REDUCE_OPS)}},
    icon="∫"), _accumulate_executor)


# ── data.sort ────────────────────────────────────────────────────────

def _sort_executor(config: dict, inputs: dict, ctx) -> dict:
    items = list(_as_list((inputs or {}).get("items")))
    cfg = config or {}
    key = cfg.get("key") or (inputs or {}).get("key")
    desc = str(cfg.get("order", "asc")).lower() in ("desc", "descending")

    def _k(it):
        if key and isinstance(it, dict):
            return _sortable(it.get(key))
        return _sortable(it)

    try:
        items.sort(key=_k, reverse=desc)
    except Exception as ex:
        return {"status": "error", "items": [],
                "error": f"{type(ex).__name__}: {ex}"}
    return {"status": "ok", "items": items}


register(NodeSpec(
    type="data.sort", category="data", display_name="Sort",
    description="Sort a list. `key` sorts records by that field; `order` "
                "is asc (default) or desc. Mixed types never error.",
    inputs=[Port(name="items", type=PortType.LIST, required=True),
            Port(name="key",   type=PortType.STRING)],
    outputs=[Port(name="items", type=PortType.LIST)],
    config_schema={"key":   {"type": "string"},
                   "order": {"type": "string", "default": "asc",
                             "options": ["asc", "desc"]}},
    icon="↕"), _sort_executor)


# ── data.group_by ────────────────────────────────────────────────────

def _group_by_executor(config: dict, inputs: dict, ctx) -> dict:
    items = _as_list((inputs or {}).get("items"))
    key = (config or {}).get("key") or (inputs or {}).get("key")
    groups: dict = {}
    for it in items:
        if isinstance(it, dict) and key:
            k = it.get(key)
        else:
            k = it
        groups.setdefault(str(k), []).append(it)
    return {"status": "ok", "groups": groups, "keys": list(groups.keys())}


register(NodeSpec(
    type="data.group_by", category="data", display_name="Group by",
    description="Partition a list of records into `groups` — an object "
                "keyed by each record's `key` field. `keys` lists the "
                "distinct group keys.",
    inputs=[Port(name="items", type=PortType.LIST, required=True),
            Port(name="key",   type=PortType.STRING)],
    outputs=[Port(name="groups", type=PortType.OBJECT),
             Port(name="keys",   type=PortType.LIST)],
    config_schema={"key": {"type": "string"}},
    icon="⊞"), _group_by_executor)
