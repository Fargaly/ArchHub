"""Relational primitives — stem-rebuild Phase-0 (in-place plan cell-matrix).

The reconcile core. `data.join` matches two lists on a key (or key pair)
and partitions the result into matched / left_only / right_only — the
relational match that turns a bespoke reconcile code-blob (BBC4 submittal
QC, Excel<->Revit param sync, DD model<->DWG match) into a composable
stem cell.

Pure + side-effect-free. No host, no LLM. Sits alongside aggregate.py
(reduce / group_by / sort) as a keep-as-cell stem.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ── shared helpers (match aggregate.py conventions) ───────────────────

def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _key_of(item, key):
    """The join key for one item.

    - key == "" / None  → the item itself is the key (flat-list join).
    - item is a dict     → item.get(key).
    - otherwise          → the item itself (non-dict rows can't be
                           field-keyed; they key on identity).

    Returns a hashable key. Unhashable values (dict / list) fall back to
    their `repr` so the join never raises on exotic rows — the same
    total-tolerance stance as aggregate._sortable.
    """
    if key and isinstance(item, dict):
        k = item.get(key)
    else:
        k = item
    try:
        hash(k)
        return k
    except TypeError:
        return repr(k)


# Join "how" — which side(s) must have a match to appear in `matched`.
# All four ALWAYS populate left_only + right_only too (the reconcile
# audit trail); `how` only governs which rows land in `matched`.
_JOIN_HOWS = ("inner", "left", "right", "outer")


# ── data.join ─────────────────────────────────────────────────────────

def _join_executor(config: dict, inputs: dict, ctx) -> dict:
    cfg = config or {}
    left = _as_list((inputs or {}).get("left"))
    right = _as_list((inputs or {}).get("right"))

    # key: single `key` applies to both sides; `left_key`/`right_key`
    # override per-side (join records with differently-named id fields,
    # e.g. left "ElementId" vs right "id"). Input ports beat config so a
    # wired key wins, mirroring aggregate._sort_executor's key handling.
    key = cfg.get("key")
    if key is None:
        key = (inputs or {}).get("key")
    lkey = cfg.get("left_key") or (inputs or {}).get("left_key") or key or ""
    rkey = cfg.get("right_key") or (inputs or {}).get("right_key") or key or ""

    how = str(cfg.get("how", "inner") or "inner").lower()
    if how not in _JOIN_HOWS:
        return {"status": "error", "matched": [], "left_only": [],
                "right_only": [], "match_count": 0,
                "error": f"join: unknown how {how!r} — want one of "
                         f"{', '.join(_JOIN_HOWS)}"}

    # Index the right side by key → list of rows (keys need not be unique;
    # a duplicate key yields the cartesian pairing for that key, the
    # standard relational-join semantics).
    right_index: dict = {}
    for r in right:
        right_index.setdefault(_key_of(r, rkey), []).append(r)

    matched: list = []
    left_only: list = []
    matched_right_keys: set = set()

    for l in left:
        k = _key_of(l, lkey)
        rights = right_index.get(k)
        if rights:
            matched_right_keys.add(k)
            for r in rights:
                matched.append({"key": k, "left": l, "right": r})
        else:
            left_only.append(l)

    right_only = [r for r in right
                  if _key_of(r, rkey) not in matched_right_keys]

    # `how` shapes `matched`: left/outer re-introduce unmatched lefts as
    # half-rows (right=None); right/outer do the same for unmatched
    # rights. left_only / right_only stay complete regardless — they ARE
    # the reconcile diff.
    if how in ("left", "outer"):
        for l in left_only:
            matched.append({"key": _key_of(l, lkey), "left": l, "right": None})
    if how in ("right", "outer"):
        for r in right_only:
            matched.append({"key": _key_of(r, rkey), "left": None, "right": r})

    return {"status": "ok", "matched": matched,
            "left_only": left_only, "right_only": right_only,
            "match_count": len(matched)}


register(NodeSpec(
    type="data.join", category="data", display_name="Join",
    description="Match two lists on a key and partition into matched / "
                "left_only / right_only — the reconcile core. `key` joins "
                "both sides on the same field; `left_key`/`right_key` "
                "override per side. `how` = inner (default) / left / right "
                "/ outer shapes the matched rows.",
    inputs=[Port(name="left",      type=PortType.LIST, required=True),
            Port(name="right",     type=PortType.LIST, required=True),
            Port(name="key",       type=PortType.STRING),
            Port(name="left_key",  type=PortType.STRING),
            Port(name="right_key", type=PortType.STRING)],
    outputs=[Port(name="matched",     type=PortType.LIST),
             Port(name="left_only",   type=PortType.LIST),
             Port(name="right_only",  type=PortType.LIST),
             Port(name="match_count", type=PortType.NUMBER)],
    config_schema={
        "key":       {"type": "string"},
        "left_key":  {"type": "string"},
        "right_key": {"type": "string"},
        "how":       {"type": "string", "default": "inner",
                      "options": list(_JOIN_HOWS)},
    },
    icon="⋈"), _join_executor)
