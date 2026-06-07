"""Normalization primitives — stem-rebuild Phase-0 (NORMALIZATION INFRASTRUCTURE).

The two reusable NORMALIZE cells the messy composites (aec.*, adapter.*,
control.switch) hand-rolled inline and so could not be rebuilt byte-identically.
Their bespoke impls leant on three patterns the subgraph mechanism does NOT give
for free: (1) config-fallback `inputs.get(x) or config.get(x)`; (2) type-guards
that return `status: "error"`; (3) falsy/None coalesce. This module mints the
two STEM CELLS that make those patterns composable — so a rebuild wires a
`data.coalesce` / `data.ensure` cell into its subgraph instead of re-writing a
bespoke `code.expression` each time.

  • `data.coalesce` — the reusable `x or default` / `x if x is not None else y`
    pattern. `mode: none` → `value if value is not None else fallback`;
    `mode: falsy` → `value if value else fallback`. ALWAYS `status: ok` (pure —
    a coalesce never fails; an absent value is the whole point).

  • `data.ensure` — the reusable TYPE-GUARD. Checks `value` against `type`
    (list/dict/number/string/bool/any) and, per `on_fail`, either errors
    (`status: "error"` — the guard the subgraph PROPAGATES via subgraph.py:537),
    coerces (best-effort), or passes through. Emits `{value, ok}`.

ONE-SYSTEM — these cells mint NO new comparison engine and NO new type system.
The type check is plain `isinstance` over Python types (the same stance
`sense._is_empty` / `serialize` take); the numeric reading REUSES `math_text._num`
(so non-list→number coercion never drifts from math.op's coercion). No new
sandbox, no new registry, no new runner. Pure + side-effect-free; no host, no
LLM. Lives alongside serialize.py (data.json), relate.py (data.join),
aggregate.py (reduce / group_by / sort) and verify.py (verify.assert) in the
data/control stem family.

Status policy (load-bearing, mirrors the family):
  • `data.coalesce` is ALWAYS `status: ok` — it is total by construction.
  • `data.ensure` is `status: ok` on a match, on `coerce`, and on `passthrough`
    (a clean `ok: false` is NOT an error — it is the branchable "didn't match"
    fact, exactly as `sense`/`verify` treat a clean false). It is `status:
    "error"` ONLY under `on_fail: error` on a type miss — that error is the
    type-guard the subgraph propagates so a malformed inner value fails the
    composite, NEVER a fabricated value.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register

# ONE-SYSTEM reuse — the existing numeric coercion from math.op, so a
# number-type coerce never drifts from the math engine's `_num`. Imported at
# module top so the dependency is explicit and compile-checked (math_text is a
# pure registry-leaf module with no back-dependency on this one, so there is no
# import cycle), exactly as verify.py / sense.py import from it.
from .math_text import _num


# ── data.coalesce ─────────────────────────────────────────────────────

# The two coalesce strategies, surfaced as the `mode` config options.
#   none  → first non-None  (`value if value is not None else fallback`)
#   falsy → first truthy    (`value if value else fallback`)
_COALESCE_MODES = ("none", "falsy")

# Sentinel so an explicitly-wired `value: None` is distinguished from "no value
# input wired at all" — under mode `none` a wired None still defers to fallback
# (that IS the point of coalesce), but the sentinel lets the cell read config
# `value` only when NOTHING was wired.
_MISSING = object()


def _coalesce_executor(config: dict, inputs: dict, ctx) -> dict:
    """First-present-of-two → `{value}`. The reusable `x or default` cell.

    `mode: none` returns `value` unless it is None, else `fallback`. `mode:
    falsy` returns `value` unless it is falsy (None/0/""/[]/{}/False), else
    `fallback`. A wired input beats config (the data.join "wired key wins"
    rule); a sentinel honours a wired None. ALWAYS `status: ok` — a coalesce is
    total by construction (see module docstring)."""
    cfg = config or {}
    ins = inputs or {}

    # A wired input beats config; sentinels honour a wired/config None as a
    # real value (load-bearing for mode `none`, where None is the trigger).
    wired_value = ins["value"] if "value" in ins else _MISSING
    value = wired_value if wired_value is not _MISSING else cfg.get("value")

    wired_fb = ins["fallback"] if "fallback" in ins else _MISSING
    fallback = wired_fb if wired_fb is not _MISSING else cfg.get("fallback")

    mode = str(cfg.get("mode", "none") or "none").strip().lower()
    # An unknown mode degrades to `none` (the safe default) rather than erroring
    # — coalesce is total; a typo must never strand a pipeline. (mode is a
    # closed enum in the schema, so this is belt-and-braces.)
    if mode == "falsy":
        out = value if value else fallback
    else:  # "none" (default) + any unknown value
        out = value if value is not None else fallback

    return {"status": "ok", "value": out}


register(NodeSpec(
    type="data.coalesce", category="data", display_name="Coalesce",
    description="First-present-of-two: emit `value`, falling back to `fallback` "
                "when `value` is missing. The reusable `x or default` / `x if x "
                "is not None else y` cell — so a graph stops hand-rolling a "
                "code.expression for the config-fallback pattern. `mode: none` "
                "falls back only on None; `mode: falsy` falls back on any falsy "
                "value (None/0/\"\"/[]/{}/False). A wired input overrides "
                "config. Pure — always succeeds, no host, no network.",
    inputs=[Port(name="value",    type=PortType.ANY),
            Port(name="fallback", type=PortType.ANY)],
    outputs=[Port(name="value", type=PortType.ANY)],
    config_schema={
        "mode":     {"type": "string", "default": "none",
                     "options": list(_COALESCE_MODES),
                     "description": "Fallback trigger: 'none' (fall back only "
                                    "when value is None) or 'falsy' (fall back "
                                    "on any falsy value)."},
        "value":    {"description": "The primary value (config; a wired "
                                    "`value` input overrides)."},
        "fallback": {"description": "Used when `value` is missing per `mode` "
                                    "(config; a wired `fallback` input "
                                    "overrides)."},
    },
    icon="??"), _coalesce_executor)


# ── data.ensure ───────────────────────────────────────────────────────

# The types `data.ensure` guards on, surfaced as the `type` config options.
# `any` always matches (a no-op guard / pure passthrough of the truth).
_ENSURE_TYPES = ("list", "dict", "number", "string", "bool", "any")

# What to do on a type miss, surfaced as the `on_fail` config options.
#   error       → {value: None, ok: false, status: "error"} (the subgraph-
#                 propagated guard, subgraph.py:537)
#   coerce      → best-effort coerce → {value: coerced, ok: false, status: ok}
#   passthrough → emit the value untouched → {value, ok: false, status: ok}
_ENSURE_ON_FAIL = ("error", "coerce", "passthrough")

# bool is a subclass of int in Python — for the `number` guard a bool must NOT
# count as a number (and for the `bool` guard an int must NOT count as a bool),
# else `True`/`1` blur. `_matches` special-cases this, matching `math_text._num`'s
# own `isinstance(x, bool)` discipline.


def _matches(value, type_name: str) -> bool:
    """True iff `value` is of `type_name` (list/dict/number/string/bool/any).

    `any` always matches. `number` accepts int|float but NOT bool (bool is an
    int subclass — kept distinct so `True` is not "a number", mirroring
    `_num`'s `isinstance(x, bool)` guard). `bool` accepts only real bools."""
    if type_name == "any":
        return True
    if type_name == "list":
        return isinstance(value, list)
    if type_name == "dict":
        return isinstance(value, dict)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "bool":
        return isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _coerce(value, type_name: str):
    """Best-effort coercion of `value` toward `type_name` — total-tolerant.

    list   → `value` if already a list, else `[value]` (wrap a scalar; None →
             `[]`, the empty list, never `[None]`).
    dict   → `value` if already a dict, else `{}` (no meaningful scalar→dict).
    string → `str(value)` (None → "").
    bool   → Python truthiness `bool(value)`.
    number → `math_text._num(value)` (the SHARED coercion; non-numeric → 0.0).
    any    → `value` unchanged.
    Never raises — coercion is the total branch."""
    if type_name == "any":
        return value
    if type_name == "list":
        if isinstance(value, list):
            return value
        return [] if value is None else [value]
    if type_name == "dict":
        return value if isinstance(value, dict) else {}
    if type_name == "string":
        return "" if value is None else str(value)
    if type_name == "bool":
        return bool(value)
    if type_name == "number":
        return _num(value)        # ONE-SYSTEM — math.op's coercion, no drift.
    return value


def _ensure_executor(config: dict, inputs: dict, ctx) -> dict:
    """Type-guard `value` against `type` → `{value, ok}` (+ status per on_fail).

    A match → `{value, ok: true, status: ok}` (value passes through unchanged).
    A miss, per `on_fail`:
      • error       → `{value: None, ok: false, status: "error", error: ...}` —
        the guard the subgraph PROPAGATES (subgraph.py:537) so a malformed inner
        value fails the composite, never a fabricated value;
      • coerce      → `{value: <coerced>, ok: false, status: ok}` — best-effort;
      • passthrough → `{value: <original>, ok: false, status: ok}` — untouched.
    See module docstring for the status policy (a clean `ok: false` is NOT an
    error; only `on_fail: error` on a miss is `status: error`)."""
    cfg = config or {}
    ins = inputs or {}

    value = ins.get("value")

    type_name = str(cfg.get("type", "any") or "any").strip().lower()
    on_fail = str(cfg.get("on_fail", "error") or "error").strip().lower()

    # A malformed config (unknown type / on_fail) is a typed error — the
    # needs-root case, never a fabricated verdict (mirrors sense/verify).
    if type_name not in _ENSURE_TYPES:
        return {"status": "error", "value": None, "ok": False,
                "error": f"data.ensure: unknown type {type_name!r} — want one "
                         f"of {', '.join(_ENSURE_TYPES)}"}
    if on_fail not in _ENSURE_ON_FAIL:
        return {"status": "error", "value": None, "ok": False,
                "error": f"data.ensure: unknown on_fail {on_fail!r} — want one "
                         f"of {', '.join(_ENSURE_ON_FAIL)}"}

    # 1. A match — pass the value through, ok=true.
    if _matches(value, type_name):
        return {"status": "ok", "value": value, "ok": True}

    # 2. A miss — branch on on_fail.
    if on_fail == "error":
        # The type-guard the subgraph propagates (subgraph.py:537): value is
        # blanked so no malformed value leaks downstream.
        return {"status": "error", "value": None, "ok": False,
                "error": f"expected {type_name}"}
    if on_fail == "coerce":
        return {"status": "ok", "value": _coerce(value, type_name), "ok": False}
    # passthrough — emit the original value untouched, just flag ok=false.
    return {"status": "ok", "value": value, "ok": False}


register(NodeSpec(
    type="data.ensure", category="data", display_name="Ensure",
    description="Type-guard `value` against `type` "
                "(list/dict/number/string/bool/any) → `value` + an `ok` bool. "
                "The reusable type-guard the composites hand-rolled: a match "
                "passes `value` through with `ok=true`; a miss is handled by "
                "`on_fail` — 'error' emits status:error (propagated by a "
                "subgraph so the composite fails, never fabricates), 'coerce' "
                "best-effort coerces (e.g. scalar→[scalar], str(), _num()), "
                "'passthrough' emits the value untouched with `ok=false`. A "
                "clean `ok=false` (coerce/passthrough) is branchable, not an "
                "error. Pure — no host, no network.",
    inputs=[Port(name="value", type=PortType.ANY, required=True)],
    outputs=[Port(name="value", type=PortType.ANY),
             Port(name="ok",    type=PortType.BOOLEAN)],
    config_schema={
        "type":    {"type": "string", "default": "any",
                    "options": list(_ENSURE_TYPES),
                    "description": "The type `value` must be. 'any' always "
                                   "matches (no-op guard)."},
        "on_fail": {"type": "string", "default": "error",
                    "options": list(_ENSURE_ON_FAIL),
                    "description": "On a type miss: 'error' (status:error, "
                                   "subgraph-propagated), 'coerce' (best-effort "
                                   "coerce), or 'passthrough' (emit untouched, "
                                   "ok=false)."},
    },
    icon="?:"), _ensure_executor)
