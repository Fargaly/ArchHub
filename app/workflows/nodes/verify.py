"""Verify primitive — stem-rebuild Phase-0 (in-place plan cell-matrix).

The per-node verify gate AND the branch primitive. `verify.assert` runs a
predicate over an input and emits a typed `{passed: bool, report: str, value}`
so a workflow can BRANCH on `passed` (wire it into control.if / control.switch)
AND the ROMA court can gate a leaf on a real predicate. `value` is a
pass-through (unchanged on pass AND on fail) so `assert` sits transparently
mid-pipeline — assert a derived fact, pass the original payload downstream.

ONE-SYSTEM — this cell mints NO new evaluator. It REUSES the two predicate
engines already shipped:
  • expression predicate → the existing `code.expression` executor
    (`code._code_expression_executor`) — inherits its sandbox (forbidden-token
    pre-check + restricted builtins, safe_mode default True) and its typed
    error contract for free.
  • comparison predicate {op, expected} → the existing comparison table from
    `math_text` (`math_text._COMPARE`: eq/neq/gt/lt/gte/lte, with `_num`
    coercion already inside the gt/lt/gte/lte lambdas).

No new sandbox, no new comparison table, no new registry, no new runner. Pure
+ side-effect-free; no host, no LLM. Lives alongside relate.py (data.join) and
aggregate.py (reduce / group_by / sort) as a keep-as-cell stem.

Status policy (load-bearing): `passed=false` is NOT an error. A predicate that
evaluates cleanly to false returns `status: "ok"`, `passed: false`, a FAIL
report, and the pass-through `value` — so a workflow can branch on a false
assertion and the ROMA court can distinguish "the predicate ran and refuted
it" (red, actionable) from "the predicate itself is broken" (a MALFORMED
predicate → `status: "error"`, the needs-root case). Only a broken predicate
— empty/forbidden expression, unknown op, no predicate at all, or a comparator
that raised — is a `status: "error"`.
"""
from __future__ import annotations

from ..graph import Port, PortType
from ..registry import NodeSpec, register

# ONE-SYSTEM reuse — the existing expression executor + comparison table.
# Imported at module top so the dependency is explicit and compile-checked
# (both modules are pure registry-leaf modules with no back-dependency on
# this one, so there is no import cycle).
from .code import _code_expression_executor
from .math_text import _COMPARE


# ── verify.assert ─────────────────────────────────────────────────────

# The shared comparison operators, surfaced as the `op` config options. Read
# from `_COMPARE` so this never drifts from the math.op vocabulary.
_COMPARE_OPS = tuple(_COMPARE.keys())   # ("eq", "neq", "gt", "lt", "gte", "lte")

_MODES = ("expression", "compare")

# Sentinel so an explicitly-wired `expected: None` (a legitimate RHS, e.g.
# `assert value is None` via op=eq) is distinguished from "no expected given".
_MISSING = object()


def _infer_mode(cfg: dict, has_wired_expected: bool) -> str:
    """Pick the predicate mode when `mode` is unset.

    compare when an `op` is configured (or an `expected` is wired — the
    comparison RHS only makes sense in compare mode); else expression when an
    `expr` is configured; else default "expression" (the no-predicate case is
    caught downstream as a malformed-predicate error)."""
    mode = str(cfg.get("mode") or "").strip().lower()
    if mode in _MODES:
        return mode
    if cfg.get("op") or has_wired_expected:
        return "compare"
    if str(cfg.get("expr") or "").strip():
        return "expression"
    return "expression"


def _eval_expression(expr: str, safe_mode: bool, subject):
    """Run the predicate via the EXISTING code.expression executor.

    Binds the subject under three names so the expression can use `value`
    (the canonical pass-through name), `subject` (the explicit test-subject
    name), or `a` (code.expression's native first input). Returns
    `(passed_raw, error)` — `error` non-None means a MALFORMED predicate
    (empty / forbidden-token / raised during eval), surfaced verbatim from
    the code.expression typed-error contract."""
    res = _code_expression_executor(
        {"expr": expr, "safe_mode": safe_mode},
        {"value": subject, "subject": subject, "a": subject},
        None,
    )
    if res.get("status") == "error":
        return None, res.get("error") or "expression error"
    return res.get("value"), None


def _eval_compare(op: str, subject, expected):
    """Run the predicate via the EXISTING math_text._COMPARE table.

    Returns `(passed_raw, error)` — `error` non-None means a MALFORMED
    predicate (unknown op, or a comparator that raised, mirroring math.op's
    own try/except stance)."""
    fn = _COMPARE.get(op)
    if fn is None:
        return None, (f"assert: unknown op {op!r} — want one of "
                      f"{', '.join(_COMPARE_OPS)}")
    try:
        return fn(subject, expected), None
    except Exception as ex:   # a comparator raising IS a broken predicate
        return None, f"{type(ex).__name__}: {ex}"


def _detail_compare(op: str, subject, expected) -> str:
    return f"{subject!r} {op} {expected!r}"


def _assert_executor(config: dict, inputs: dict, ctx) -> dict:
    """Predicate over an input → `{passed, report, value}`.

    `value` is the subject AND the pass-through payload; an optional
    `subject` input overrides WHAT is tested while `value` still flows out
    unchanged. See module docstring for the status policy (a clean false is
    `status: ok`; only a broken predicate is `status: error`)."""
    cfg = config or {}
    ins = inputs or {}

    # 1. Resolve subject + the fixed pass-through value.
    value = ins.get("value")
    subject = ins["subject"] if "subject" in ins else value
    out_value = value   # the pass-through — fixed now, never mutated.

    message = str(cfg.get("message") or "").strip()
    prefix = f"{message}: " if message else ""

    # `expected`: a wired input beats config (mirrors data.join's "wired key
    # beats config"). Use a sentinel so a wired/config None is honoured.
    wired_expected = ins["expected"] if "expected" in ins else _MISSING
    has_wired_expected = wired_expected is not _MISSING

    mode = _infer_mode(cfg, has_wired_expected)

    # 2. Evaluate the predicate → (passed_raw, eval_error, detail).
    expr = str(cfg.get("expr") or "").strip()
    op = str(cfg.get("op") or "").strip()

    if mode == "compare":
        if not op:
            return {"status": "error", "passed": False,
                    "report": f"{prefix}assert: no predicate — set `op` "
                              f"(compare mode) or `expr`",
                    "value": out_value}
        expected = wired_expected if has_wired_expected else cfg.get("expected")
        passed_raw, eval_error = _eval_compare(op, subject, expected)
        detail = _detail_compare(op, subject, expected)
    else:  # expression
        if not expr:
            return {"status": "error", "passed": False,
                    "report": f"{prefix}assert: no predicate — set `expr` "
                              f"or `op`",
                    "value": out_value}
        safe_mode = bool(cfg.get("safe_mode", True))
        passed_raw, eval_error = _eval_expression(expr, safe_mode, subject)
        detail = expr

    # 3. A broken predicate is a typed error (the needs-root case), NEVER a
    #    fabricated pass/fail.
    if eval_error is not None:
        return {"status": "error", "passed": False,
                "report": f"{prefix}ERROR — {eval_error}",
                "value": out_value}

    # 4. A clean evaluation: passed is a real bool; false is OK (branchable).
    passed = bool(passed_raw)
    if passed:
        report = f"{prefix}PASS — {detail}"
    else:
        # Show the actual subject so the court/canvas sees WHY it failed.
        report = f"{prefix}FAIL — {detail} (got {subject!r})"
        if len(report) > 240:
            report = report[:237] + "..."

    return {"status": "ok", "passed": passed, "report": report,
            "value": out_value}


register(NodeSpec(
    type="verify.assert", category="control", display_name="Assert",
    description="Run a predicate over `value` and emit `passed` (bool) + a "
                "`report` string, passing `value` through unchanged. The "
                "per-node verify gate + the branch primitive: wire `passed` "
                "into If/Switch, or let the ROMA court gate a leaf on it. "
                "`expr` mode evaluates a Python predicate (`value`/`subject` "
                "in scope); `op`+`expected` mode compares "
                "(eq/neq/gt/lt/gte/lte). A clean false is `passed=false` "
                "(branchable); only a broken predicate is an error.",
    inputs=[Port(name="value",    type=PortType.ANY, required=True),
            Port(name="subject",  type=PortType.ANY),
            Port(name="expected", type=PortType.ANY)],
    outputs=[Port(name="passed", type=PortType.BOOLEAN),
             Port(name="report", type=PortType.STRING),
             Port(name="value",  type=PortType.ANY)],
    config_schema={
        "mode":      {"type": "string", "default": "expression",
                      "options": list(_MODES)},
        "expr":      {"type": "string",
                      "description": "Predicate expression; `value`/`subject` "
                                     "are in scope. Truthy → passed."},
        "safe_mode": {"type": "boolean", "default": True,
                      "description": "Sandbox the expression (forbidden-token "
                                     "pre-check + restricted builtins)."},
        "op":        {"type": "string", "options": list(_COMPARE_OPS),
                      "description": "Comparison operator for {op, expected}."},
        "expected":  {"description": "Comparison RHS (config; a wired "
                                     "`expected` input overrides)."},
        "message":   {"type": "string",
                      "description": "Optional label prefixed to `report` "
                                     "(e.g. 'walls must exist')."},
    },
    icon="✓"), _assert_executor)
