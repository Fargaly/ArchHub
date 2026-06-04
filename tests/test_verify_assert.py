"""stem-rebuild Phase-0 — `verify.assert`, the per-node verify gate + branch.

`assert` runs a predicate over an input and emits a typed
`{passed: bool, report: str, value}` so a workflow can branch on `passed` AND
the ROMA court can gate a leaf on a real predicate. `value` is a pass-through
(unchanged on pass AND fail) so the cell sits transparently mid-pipeline.

What's pinned here:
  * expression mode evaluates a Python predicate with `value`/`subject`/`a`
    in scope, REUSING the existing code.expression executor (sandbox + typed
    errors inherited);
  * compare mode tests {op, expected} via the EXISTING math_text._COMPARE
    table (eq/neq/gt/lt/gte/lte) — no re-defined comparators;
  * a clean false is `passed=false` + `status="ok"` (branchable), NOT an
    error — the load-bearing status policy;
  * a MALFORMED predicate (empty/forbidden expr, unknown op, no predicate,
    comparator that raised) is a typed `status="error"`, never a fabricated
    pass/fail;
  * the input `value` flows out UNCHANGED on pass and on fail (mid-pipeline
    pass-through), even when a separate `subject` is what's tested;
  * a wired `expected` input beats config (data.join "wired key wins" parity);
  * `report` is always non-empty and names the verdict + the subject on fail;
  * the cell cooks end-to-end through a real WorkflowRunner and its typed
    outputs (passed / report / value) are read off the registered output
    ports — the canvas cook path, not just the executor.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.verify import _assert_executor  # noqa: E402


# ─── expression mode — pass ─────────────────────────────────────────


def test_expression_pass_is_status_ok_passed_true():
    out = _assert_executor(
        {"mode": "expression", "expr": "value > 0"}, {"value": 6}, None)
    assert out["status"] == "ok"
    assert out["passed"] is True
    assert "PASS" in out["report"]
    assert out["value"] == 6   # pass-through unchanged


def test_expression_pass_via_subject_name_and_a_name():
    # The subject is bound under `value`, `subject`, AND `a` (code.expression
    # native) — any of the three names works in the predicate.
    assert _assert_executor(
        {"expr": "subject == 'ok'"}, {"value": "ok"}, None)["passed"] is True
    assert _assert_executor(
        {"expr": "a == 'ok'"}, {"value": "ok"}, None)["passed"] is True


def test_expression_uses_len_over_list_subject():
    out = _assert_executor(
        {"expr": "len(value) > 0"}, {"value": [1, 2, 3]}, None)
    assert out["passed"] is True
    assert out["value"] == [1, 2, 3]


# ─── expression mode — fail is a CLEAN false, not an error ──────────


def test_expression_clean_false_is_ok_not_error():
    out = _assert_executor(
        {"expr": "len(value) > 0"}, {"value": []}, None)
    # The whole point: a refuted predicate is branchable, not broken.
    assert out["status"] == "ok"
    assert out["passed"] is False
    assert "FAIL" in out["report"]
    # The subject is shown in the report so the court/canvas sees WHY.
    assert "[]" in out["report"]
    # Pass-through still flows on fail.
    assert out["value"] == []


def test_falsy_truthy_value_is_coerced_to_real_bool():
    # `value` alone as the predicate → truthiness, coerced to a real bool.
    assert _assert_executor({"expr": "value"}, {"value": 0}, None)["passed"] is False
    assert _assert_executor({"expr": "value"}, {"value": 5}, None)["passed"] is True


# ─── compare mode — _COMPARE reuse ──────────────────────────────────


def test_compare_gt_pass():
    out = _assert_executor(
        {"mode": "compare", "op": "gt", "expected": 0}, {"value": 6}, None)
    assert out["status"] == "ok"
    assert out["passed"] is True
    assert "6" in out["report"] and "gt" in out["report"]
    assert out["value"] == 6


def test_compare_lte_fail_is_clean_false():
    out = _assert_executor(
        {"mode": "compare", "op": "lte", "expected": 0}, {"value": 6}, None)
    assert out["status"] == "ok"
    assert out["passed"] is False
    assert out["value"] == 6


def test_compare_eq_uses_raw_equality_for_non_numbers():
    # _COMPARE['eq'] is raw == (not _num-coerced) → strings compare directly.
    assert _assert_executor(
        {"op": "eq", "expected": "ARC"}, {"value": "ARC"}, None)["passed"] is True
    assert _assert_executor(
        {"op": "eq", "expected": "ARC"}, {"value": "STR"}, None)["passed"] is False


def test_compare_all_six_operators_resolve():
    for op in ("eq", "neq", "gt", "lt", "gte", "lte"):
        out = _assert_executor({"op": op, "expected": 1}, {"value": 1}, None)
        assert out["status"] == "ok", op
        assert isinstance(out["passed"], bool), op


# ─── wired `expected` beats config (data.join parity) ───────────────


def test_wired_expected_overrides_config():
    # config says expected=999 (would fail) but the wired input says 0 → pass.
    out = _assert_executor(
        {"op": "gt", "expected": 999},
        {"value": 6, "expected": 0}, None)
    assert out["passed"] is True


def test_wired_expected_none_is_honoured_not_treated_as_missing():
    # A wired expected of None is a legitimate RHS (op=eq, assert value is None).
    out = _assert_executor(
        {"op": "eq"}, {"value": None, "expected": None}, None)
    assert out["passed"] is True


# ─── subject override — test a derived fact, pass the original through ──


def test_subject_overrides_what_is_tested_value_still_flows():
    walls = [{"id": 1}, {"id": 2}, {"id": 3}]
    out = _assert_executor(
        {"mode": "compare", "op": "gte", "expected": 1},
        {"value": walls, "subject": len(walls)}, None)
    assert out["passed"] is True          # tested on the count (3 >= 1)
    assert out["value"] == walls          # but the LIST flows downstream


def test_subject_defaults_to_value_when_absent():
    out = _assert_executor({"expr": "subject == value"}, {"value": 42}, None)
    assert out["passed"] is True


# ─── malformed predicate → typed error, never fabricated ────────────


def test_no_predicate_is_typed_error():
    out = _assert_executor({}, {"value": 1}, None)
    assert out["status"] == "error"
    assert out["passed"] is False
    assert "no predicate" in out["report"]
    # Even on error, the pass-through value is preserved.
    assert out["value"] == 1


def test_unknown_op_is_typed_error():
    out = _assert_executor(
        {"mode": "compare", "op": "telepathy", "expected": 0},
        {"value": 6}, None)
    assert out["status"] == "error"
    assert out["passed"] is False
    assert "unknown op" in out["report"]


def test_empty_expr_in_expression_mode_is_typed_error():
    out = _assert_executor({"mode": "expression", "expr": "   "}, {"value": 1}, None)
    assert out["status"] == "error"
    assert "no predicate" in out["report"]


def test_forbidden_token_expression_is_typed_error_via_sandbox():
    # The sandbox is INHERITED from code.expression — `__import__` is rejected.
    out = _assert_executor(
        {"expr": "__import__('os')"}, {"value": 1}, None)
    assert out["status"] == "error"
    assert "ERROR" in out["report"]
    # forbidden-token rejection comes straight from the code.expression engine
    assert "forbidden" in out["report"].lower()


def test_raising_expression_is_typed_error_not_fabricated_pass():
    # 1/0 raises inside eval → code.expression returns status=error → assert
    # surfaces a typed error (NOT a fabricated passed value).
    out = _assert_executor({"expr": "1/0"}, {"value": 1}, None)
    assert out["status"] == "error"
    assert out["passed"] is False


# ─── mode inference (no `mode` set) ─────────────────────────────────


def test_mode_inferred_compare_when_op_present():
    out = _assert_executor({"op": "gt", "expected": 0}, {"value": 5}, None)
    assert out["status"] == "ok"
    assert out["passed"] is True


def test_mode_inferred_expression_when_expr_present():
    out = _assert_executor({"expr": "value == 5"}, {"value": 5}, None)
    assert out["status"] == "ok"
    assert out["passed"] is True


def test_mode_inferred_compare_when_only_expected_wired():
    # An expected wired with no op → compare mode, but no op → malformed.
    out = _assert_executor({}, {"value": 5, "expected": 0}, None)
    assert out["status"] == "error"
    assert "no predicate" in out["report"]


# ─── message prefix ─────────────────────────────────────────────────


def test_message_is_prefixed_to_report():
    out = _assert_executor(
        {"expr": "value > 0", "message": "walls must exist"},
        {"value": 6}, None)
    assert out["report"].startswith("walls must exist: ")
    assert "PASS" in out["report"]


def test_report_is_never_empty_on_any_path():
    for cfg, ins in (
        ({"expr": "value > 0"}, {"value": 6}),       # pass
        ({"expr": "value > 0"}, {"value": -1}),      # fail
        ({}, {"value": 1}),                          # malformed
    ):
        out = _assert_executor(cfg, ins, None)
        assert out["report"]


# ─── registration ───────────────────────────────────────────────────


def test_assert_registered():
    import workflows.nodes.verify  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("verify.assert") is not None


def test_assert_ports_are_typed():
    import workflows.nodes.verify  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("verify.assert")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"passed": "boolean", "report": "string", "value": "any"}
    in_ports = {p.name for p in spec.inputs}
    assert {"value", "subject", "expected"} <= in_ports
    # `value` is the only required input.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"value"}


def test_assert_category_is_control():
    import workflows.nodes.verify  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("verify.assert")
    assert spec.category == "control"


def test_assert_in_grammar_resolves_to_engine_type():
    import workflows  # noqa: F401  registers built-ins
    from workflows import node_grammar as ng
    assert ng.engine_type("assert") == "verify.assert"


# ─── end-to-end: cook the cell through a real WorkflowRunner ────────


def test_assert_cooks_through_real_runner_and_reads_typed_outputs():
    """value source → verify.assert → assert passed / report / value come
    off the registered output ports, driven through a real outer
    WorkflowRunner (the canvas cook path)."""
    import workflows.nodes.verify  # noqa: F401  registers verify.assert
    from workflows.runner import WorkflowRunner
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType

    walls = [{"id": "W1"}, {"id": "W2"}, {"id": "W3"}]

    # Minimal const source node (registered once, idempotent).
    if _get_spec("_test.const_walls") is None:
        register(NodeSpec(
            type="_test.const_walls", category="_test",
            display_name="Test Const Walls",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.LIST)],
            config_schema={}, icon="["),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})

    graph = {
        "nodes": [
            {"id": "src", "type": "_test.const_walls",
             "config": {"value": walls},
             "outs": [{"id": "value", "t": "list"}]},
            {"id": "a", "type": "verify.assert",
             "config": {"expr": "len(value) > 0",
                        "message": "walls must exist"},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "passed", "t": "boolean"},
                      {"id": "report", "t": "string"},
                      {"id": "value",  "t": "any"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["a", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("a")

    assert out.get("status") == "ok"
    assert out["passed"] is True
    assert out["report"].startswith("walls must exist: PASS")
    # The pass-through carries the original list to whatever is wired next.
    assert out["value"] == walls


def test_assert_cooks_compare_fail_branch_through_real_runner():
    """A failing compare assertion cooks to passed=false + status ok (so a
    downstream If can branch), driven through the real runner."""
    import workflows.nodes.verify  # noqa: F401
    from workflows.runner import WorkflowRunner
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType

    if _get_spec("_test.const_num") is None:
        register(NodeSpec(
            type="_test.const_num", category="_test",
            display_name="Test Const Num",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.NUMBER)],
            config_schema={}, icon="#"),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})

    graph = {
        "nodes": [
            {"id": "src", "type": "_test.const_num",
             "config": {"value": 0},
             "outs": [{"id": "value", "t": "number"}]},
            {"id": "a", "type": "verify.assert",
             "config": {"mode": "compare", "op": "gt", "expected": 0},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "passed", "t": "boolean"},
                      {"id": "report", "t": "string"},
                      {"id": "value",  "t": "any"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["a", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("a")

    assert out.get("status") == "ok"   # a clean false is OK, branchable
    assert out["passed"] is False
    assert "FAIL" in out["report"]
    assert out["value"] == 0
