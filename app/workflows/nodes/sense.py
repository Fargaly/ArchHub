"""Sense primitive — stem-rebuild Phase-0 (in-place plan cell-matrix).

The PROPERTY-checker. `sense.extract` reads a PROPERTY of an input — its
length / type / keys / existence / emptiness / membership / numeric bounds /
shape — and emits a typed `{value, passed, report}`. `value` is the EXTRACTED
property (the list length, the type name, the key list, the bool); `passed` is
the boolean verdict of the same check (so a workflow can BRANCH on a property
just as it branches on `verify.assert`); `report` names the verdict.

It is the sibling of `verify.assert`: assert runs a PREDICATE (a compare or an
expression — "is `value` > 0?") and passes its subject through unchanged; sense
EXTRACTS a property ("how long IS `value`?") and emits that property as the
primary output. assert tests a relation; sense reads an attribute. Together
they are the read-half of the control family — sense surfaces a fact, assert
gates on one.

ONE-SYSTEM — this cell mints NO new evaluator and NO new comparison engine. The
optional `in_bounds` op REUSES the existing comparison table from `math_text`
(`math_text._COMPARE`: gte/lte, with `_num` coercion already inside the
lambdas) for the low/high fences, exactly as `verify.assert` reuses it for
compare mode. No new sandbox, no new comparison table, no new registry, no new
runner. Pure + side-effect-free; no host, no LLM. Lives alongside relate.py
(data.join), aggregate.py (reduce / group_by / sort) and verify.py
(verify.assert) as a keep-as-cell stem.

Status policy (load-bearing, mirrors verify.assert): `passed=false` is NOT an
error. A property that is read cleanly and simply does not hold (an empty list
under `is_empty=expect-false`, an out-of-range number under `in_bounds`)
returns `status: "ok"`, `passed: false`, the extracted `value`, and a FAIL
report — so a workflow can branch on it and the ROMA court can distinguish "the
property was read and it refutes the check" (red, actionable) from "the check
itself is malformed" (the needs-root case). Only a malformed check — an unknown
`op`, or `in_bounds` with neither fence — is a `status: "error"`.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register

# ONE-SYSTEM reuse — the existing comparison table for the in_bounds fences.
# Imported at module top so the dependency is explicit and compile-checked
# (math_text is a pure registry-leaf module with no back-dependency on this
# one, so there is no import cycle), exactly as verify.py imports it.
from .math_text import _COMPARE


# ── sense.extract ─────────────────────────────────────────────────────

# The properties sense can read. Each maps to a `_PROP[op]` reader returning
# `(value, passed, detail)`. Surfaced as the `op` config options.
_OPS = (
    "length",     # len(value)              → value=int,  passed = >0 (non-empty)
    "type",       # type(value).__name__    → value=str,  passed = value is not None
    "keys",       # sorted dict keys        → value=list, passed = has any key
    "exists",     # value is not None       → value=bool, passed = same
    "is_empty",   # emptiness               → value=bool, passed = same
    "in_bounds",  # low <= n <= high        → value=bool, passed = same
    "contains",   # `needle` in value       → value=bool, passed = same
    "shape",      # (rows, cols) of a table → value=list, passed = rows>0
)

# Sentinel so an explicitly-wired `needle: None` (a legitimate membership
# target, e.g. "is None in this list?") is distinguished from "no needle given".
_MISSING = object()


def _is_empty(value) -> bool:
    """Emptiness across the shapes a graph carries. None is empty; anything
    with a `len` is empty when that len is 0; a 0/`""`/`False` scalar is NOT
    empty (it is a present value) — only the container-empty + None cases are.
    """
    if value is None:
        return True
    try:
        return len(value) == 0
    except TypeError:
        return False


def _length(value):
    """len(value) → (int, passed=non-empty, detail). A value with no length
    (an int, None) reads as length 0 — total-tolerant, never a raise (the same
    stance as relate._key_of / aggregate._sortable)."""
    try:
        n = len(value)
    except TypeError:
        n = 0
    return n, n > 0, f"length = {n}"


def _type(value):
    name = type(value).__name__
    return name, value is not None, f"type = {name}"


def _keys(value):
    """sorted(dict keys) → (list, passed=has-any, detail). A non-dict has no
    keys → empty list, passed False (total-tolerant)."""
    if isinstance(value, dict):
        try:
            ks = sorted(value.keys())
        except TypeError:                       # unsortable mixed keys
            ks = [str(k) for k in value.keys()]
        return ks, len(ks) > 0, f"keys = {ks}"
    return [], False, f"keys = [] (not a dict: {type(value).__name__})"


def _exists(value):
    ok = value is not None
    return ok, ok, f"exists = {ok}"


def _is_empty_op(value):
    ok = _is_empty(value)
    return ok, ok, f"is_empty = {ok}"


def _contains(value, needle):
    """`needle in value` → (bool, passed, detail). A value that does not
    support membership (an int, None) reads as not-containing — total-tolerant,
    never a raise."""
    try:
        ok = needle in value
    except TypeError:
        ok = False
    return ok, ok, f"contains {needle!r} = {ok}"


def _shape(value):
    """(rows, cols) of a tabular value → ([rows, cols], passed=rows>0, detail).

    rows  = len(value); cols = len(value[0]) when the first row has a length
    (a list-of-rows / list-of-dicts table), else 0 (a flat list). Total-
    tolerant: a value with no length reads as [0, 0]."""
    try:
        rows = len(value)
    except TypeError:
        return [0, 0], False, "shape = [0, 0]"
    cols = 0
    if rows:
        try:
            first = value[0]
        except (TypeError, KeyError, IndexError):
            first = None
        try:
            cols = len(first)
        except TypeError:
            cols = 0
    return [rows, cols], rows > 0, f"shape = [{rows}, {cols}]"


def _in_bounds(value, low, high):
    """low <= _num(value) <= high → (value, passed, detail, error), REUSING the
    math_text._COMPARE gte/lte comparators (so the `_num` coercion + the
    numeric semantics never drift from math.op). An absent fence is open on
    that side. `error` is non-None when BOTH fences are absent (nothing to
    check) OR a comparator raised (a non-numeric value against a numeric
    fence)."""
    if low is None and high is None:
        return None, None, None, "in_bounds: no bound — set `low` and/or `high`"
    gte = _COMPARE["gte"]                        # _num-coercing >= from math.op
    lte = _COMPARE["lte"]                        # _num-coercing <= from math.op
    try:
        ok = True
        if low is not None:
            ok = ok and gte(value, low)
        if high is not None:
            ok = ok and lte(value, high)
    except Exception as ex:                      # a comparator raising IS broken
        return None, None, None, f"{type(ex).__name__}: {ex}"
    lo = "-inf" if low is None else low
    hi = "+inf" if high is None else high
    return bool(ok), bool(ok), f"in_bounds [{lo}, {hi}] = {ok}", None


def _extract_executor(config: dict, inputs: dict, ctx) -> dict:
    """Read a PROPERTY of `value` → `{value, passed, report}`.

    `value` (the OUTPUT) is the extracted property (length int / type name /
    keys list / bool / shape); `passed` is the boolean verdict of the same
    check (branchable); `report` names the verdict. See module docstring for
    the status policy (a clean false is `status: ok`; only a malformed check
    — unknown op, or in_bounds with no fence — is `status: error`)."""
    cfg = config or {}
    ins = inputs or {}

    subject = ins.get("value")

    message = str(cfg.get("message") or "").strip()
    prefix = f"{message}: " if message else ""

    op = str(cfg.get("op") or "length").strip().lower()

    # 1. Malformed check → typed error (the needs-root case), NEVER a
    #    fabricated property/verdict.
    if op not in _OPS:
        return {"status": "error", "value": None, "passed": False,
                "report": f"{prefix}sense: unknown op {op!r} — want one of "
                          f"{', '.join(_OPS)}"}

    # 2. Read the property → (value, passed, detail). in_bounds + contains take
    #    extra config/wired params; the rest read `value` alone.
    if op == "in_bounds":
        # A wired fence beats config (data.join "wired key wins" parity).
        low = ins["low"] if "low" in ins else cfg.get("low")
        high = ins["high"] if "high" in ins else cfg.get("high")
        out_value, passed_raw, detail, err = _in_bounds(subject, low, high)
        if err is not None:
            return {"status": "error", "value": None, "passed": False,
                    "report": f"{prefix}ERROR — {err}"}
    elif op == "contains":
        # `needle`: a wired input beats config; a sentinel honours a wired None.
        wired = ins["needle"] if "needle" in ins else _MISSING
        needle = wired if wired is not _MISSING else cfg.get("needle")
        out_value, passed_raw, detail = _contains(subject, needle)
    else:
        out_value, passed_raw, detail = _PROP[op](subject)

    # 3. A clean read: passed is a real bool; false is OK (branchable).
    passed = bool(passed_raw)
    verdict = "PASS" if passed else "FAIL"
    report = f"{prefix}{verdict} — {detail}"
    if not passed:
        # Show the actual subject so the court/canvas sees WHY it failed.
        report = f"{report} (got {subject!r})"
    if len(report) > 240:
        report = report[:237] + "..."

    return {"status": "ok", "value": out_value, "passed": passed,
            "report": report}


# op → reader for the no-extra-param ops. in_bounds + contains are dispatched
# inline in the executor because they read extra params; the rest read `value`
# alone and live here so the dispatch is a flat table (no if-ladder).
_PROP = {
    "length":   _length,
    "type":     _type,
    "keys":     _keys,
    "exists":   _exists,
    "is_empty": _is_empty_op,
    "shape":    _shape,
}


register(NodeSpec(
    type="sense.extract", category="control", display_name="Sense",
    description="Read a PROPERTY of `value` — its length / type / keys / "
                "existence / emptiness / numeric bounds / membership / shape — "
                "and emit it on `value`, plus a `passed` (bool) verdict + a "
                "`report` string. The PROPERTY-checker sibling of Assert: "
                "Assert runs a predicate (a compare / expression); Sense reads "
                "an attribute. Branch on `passed` (wire into If/Switch) or feed "
                "the extracted `value` (e.g. a row count) downstream. `op` "
                "picks the property; `in_bounds` takes `low`/`high`, `contains` "
                "takes `needle`. A clean false is `passed=false` (branchable); "
                "only a malformed check (unknown op, in_bounds with no fence) "
                "is an error.",
    inputs=[Port(name="value",  type=PortType.ANY, required=True),
            Port(name="low",    type=PortType.ANY),
            Port(name="high",   type=PortType.ANY),
            Port(name="needle", type=PortType.ANY)],
    outputs=[Port(name="value",  type=PortType.ANY),
             Port(name="passed", type=PortType.BOOLEAN),
             Port(name="report", type=PortType.STRING)],
    config_schema={
        "op":      {"type": "string", "default": "length",
                    "options": list(_OPS),
                    "description": "Which property to read off `value`."},
        "low":     {"description": "in_bounds lower fence (config; a wired "
                                   "`low` input overrides). Absent = open."},
        "high":    {"description": "in_bounds upper fence (config; a wired "
                                   "`high` input overrides). Absent = open."},
        "needle":  {"description": "contains membership target (config; a "
                                   "wired `needle` input overrides)."},
        "message": {"type": "string",
                    "description": "Optional label prefixed to `report` "
                                   "(e.g. 'walls present?')."},
    },
    icon="?"), _extract_executor)
