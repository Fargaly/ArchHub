"""Aggregate primitives — AgDR-0040 slice 2.

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

import json

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


# ── data.dedupe ──────────────────────────────────────────────────────
#
# Distinct from data.group_by: group_by PARTITIONS every row into buckets
# keyed by the field; dedupe DROPS duplicate rows, keeping exactly one per
# identity. The reconcile-pipeline twin of fs.list's "one row per file" —
# it collapses a list with repeats (a doubled submittal log, a re-imported
# parameter dump) down to its distinct rows in stable first-seen order, so
# a parity gate over the output is byte-stable.

_DEDUPE_KEEPS = ("first", "last")


def _dedupe_identity(row, key):
    """A stable, hashable identity for one row.

    - key set AND row is a dict  → the value at `key` (its repr if that
      value is itself unhashable, mirroring relate._key_of).
    - otherwise (no key, or a non-dict row even when key is set) → a
      stable repr of the WHOLE row via json.dumps(sort_keys, default=str)
      so dicts/lists are hashable + key-order-independent and a non-dict
      row never crashes the cell.
    """
    if key and isinstance(row, dict):
        k = row.get(key)
        try:
            hash(k)
            return k
        except TypeError:
            return json.dumps(k, sort_keys=True, default=str)
    return json.dumps(row, sort_keys=True, default=str)


def _dedupe_executor(config: dict, inputs: dict, ctx) -> dict:
    raw = (inputs or {}).get("rows")
    if not isinstance(raw, (list, tuple)):
        return {"status": "error", "rows": [], "removed": 0, "count": 0,
                "error": f"dedupe: rows must be a list, got "
                         f"{type(raw).__name__}"}
    rows = list(raw)

    cfg = config or {}
    # Wired input beats config (data.join "wired key wins" parity): a
    # `key` arriving on the input port overrides the config default.
    wired_key = (inputs or {}).get("key")
    key = (wired_key if wired_key not in (None, "") else cfg.get("key")) or ""
    keep = str(cfg.get("keep", "first") or "first").lower()
    if keep not in _DEDUPE_KEEPS:
        return {"status": "error", "rows": [], "removed": 0, "count": 0,
                "error": f"dedupe: unknown keep {keep!r} — want one of "
                         f"{', '.join(_DEDUPE_KEEPS)}"}

    # ONE pass, first-seen order preserved throughout — deterministic.
    #   keep=first → the FIRST row of each identity is kept in its slot;
    #                later duplicates are dropped.
    #   keep=last  → the LAST row's VALUE wins, but it occupies the
    #                FIRST-SEEN POSITION (we overwrite the stored row in
    #                place rather than re-appending), so output order is
    #                identical to keep=first and stays byte-stable.
    order: list = []                 # identities in first-seen order
    chosen: dict = {}                # identity -> the row we keep
    removed = 0
    try:
        for row in rows:
            ident = _dedupe_identity(row, key)
            if ident not in chosen:
                order.append(ident)
                chosen[ident] = row
            else:
                removed += 1
                if keep == "last":
                    chosen[ident] = row   # later value wins, position held
    except Exception as ex:
        return {"status": "error", "rows": [], "removed": 0, "count": 0,
                "error": f"{type(ex).__name__}: {ex}"}

    out_rows = [chosen[ident] for ident in order]
    return {"status": "ok", "rows": out_rows,
            "removed": removed, "count": len(out_rows)}


register(NodeSpec(
    type="data.dedupe", category="data", display_name="Dedupe",
    description="Remove duplicate rows from a list, keeping one per "
                "identity in stable first-seen order. `key` dedupes on "
                "that field (empty = whole-row equality); `keep` = first "
                "(default) keeps the earliest, last lets the later value "
                "win in the same position. `removed` counts the dropped "
                "rows. Distinct from group_by, which partitions instead.",
    inputs=[Port(name="rows", type=PortType.LIST, required=True),
            Port(name="key",  type=PortType.STRING)],
    outputs=[Port(name="rows",    type=PortType.LIST),
             Port(name="removed", type=PortType.NUMBER),
             Port(name="count",   type=PortType.NUMBER)],
    config_schema={
        "key":  {"type": "string", "default": "",
                 "description": "Field to dedupe on; empty = whole-row "
                                "equality."},
        "keep": {"type": "string", "default": "first",
                 "options": list(_DEDUPE_KEEPS),
                 "description": "Which duplicate to retain — first or last."},
    },
    icon="≣"), _dedupe_executor)
