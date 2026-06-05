"""stem-rebuild Phase-0 — `sense.extract`, the PROPERTY-checker sibling of assert.

`sense.extract` reads a PROPERTY of an input — length / type / keys / exists /
is_empty / in_bounds / contains / shape — and emits a typed
`{value, passed, report}`. `value` is the EXTRACTED property; `passed` is the
boolean verdict of the same check (so a workflow can BRANCH on a property), and
`report` names the verdict.

What's pinned here:
  * each op reads its property over a REAL value (len of a list, type name of a
    value, keys of a dict, in_bounds true/false, contains, shape, is_empty);
  * `value` (the output) carries the extracted property (int / str / list /
    bool), distinct from assert which passes its subject through unchanged;
  * `in_bounds` REUSES the existing math_text._COMPARE gte/lte comparators (the
    `_num` coercion is inherited) for the low/high fences — no re-defined
    comparator;
  * a wired `low`/`high`/`needle` input beats config (data.join "wired key wins"
    parity);
  * a clean false is `passed=false` + `status="ok"` (branchable), NOT an error;
  * a MALFORMED check (unknown op, or in_bounds with no fence) is a typed
    `status="error"`, never a fabricated property/verdict;
  * `report` is always non-empty and names the verdict + the subject on fail;
  * the cell is registered (`registry.get('sense.extract') is not None`), its
    ports are typed, it resolves in the node grammar, and it cooks end-to-end
    through a real WorkflowRunner (the canvas cook path, not just the executor).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.sense import _extract_executor  # noqa: E402


# ─── op=length — real len() over a list ─────────────────────────────


def test_length_of_a_list_extracts_the_count():
    out = _extract_executor(
        {"op": "length"}, {"value": [10, 20, 30]}, None)
    assert out["status"] == "ok"
    assert out["value"] == 3          # the EXTRACTED property is the count
    assert out["passed"] is True      # non-empty
    assert "PASS" in out["report"]


def test_length_of_empty_list_is_clean_false_not_error():
    out = _extract_executor({"op": "length"}, {"value": []}, None)
    # A read that simply does not hold is branchable, not broken.
    assert out["status"] == "ok"
    assert out["value"] == 0
    assert out["passed"] is False
    assert "FAIL" in out["report"]
    # The subject is shown in the report so the court/canvas sees WHY.
    assert "[]" in out["report"]


def test_length_of_a_string_counts_chars():
    out = _extract_executor({"op": "length"}, {"value": "ARC"}, None)
    assert out["value"] == 3
    assert out["passed"] is True


def test_length_of_a_non_sized_value_reads_zero_not_raise():
    # An int has no len() — total-tolerant, reads 0 (never a raise).
    out = _extract_executor({"op": "length"}, {"value": 42}, None)
    assert out["status"] == "ok"
    assert out["value"] == 0
    assert out["passed"] is False


# ─── op=type — type name of a value ─────────────────────────────────


def test_type_of_a_value_extracts_the_type_name():
    assert _extract_executor(
        {"op": "type"}, {"value": [1, 2]}, None)["value"] == "list"
    assert _extract_executor(
        {"op": "type"}, {"value": "x"}, None)["value"] == "str"
    assert _extract_executor(
        {"op": "type"}, {"value": 3}, None)["value"] == "int"
    assert _extract_executor(
        {"op": "type"}, {"value": {"a": 1}}, None)["value"] == "dict"


def test_type_of_none_is_NoneType_and_passed_false():
    out = _extract_executor({"op": "type"}, {"value": None}, None)
    assert out["value"] == "NoneType"
    assert out["passed"] is False     # passed = value is not None


# ─── op=keys — sorted dict keys ─────────────────────────────────────


def test_keys_of_a_dict_extracts_sorted_keys():
    out = _extract_executor(
        {"op": "keys"}, {"value": {"b": 2, "a": 1, "c": 3}}, None)
    assert out["status"] == "ok"
    assert out["value"] == ["a", "b", "c"]   # sorted
    assert out["passed"] is True


def test_keys_of_empty_dict_is_clean_false():
    out = _extract_executor({"op": "keys"}, {"value": {}}, None)
    assert out["value"] == []
    assert out["passed"] is False


def test_keys_of_a_non_dict_is_empty_not_raise():
    out = _extract_executor({"op": "keys"}, {"value": [1, 2, 3]}, None)
    assert out["status"] == "ok"
    assert out["value"] == []
    assert out["passed"] is False


# ─── op=in_bounds — true AND false, reusing math_text._COMPARE ───────


def test_in_bounds_true_within_low_and_high():
    out = _extract_executor(
        {"op": "in_bounds", "low": 0, "high": 10}, {"value": 5}, None)
    assert out["status"] == "ok"
    assert out["value"] is True
    assert out["passed"] is True


def test_in_bounds_false_above_high_is_clean_false():
    out = _extract_executor(
        {"op": "in_bounds", "low": 0, "high": 10}, {"value": 99}, None)
    assert out["status"] == "ok"      # a clean false, branchable
    assert out["value"] is False
    assert out["passed"] is False
    assert "FAIL" in out["report"]


def test_in_bounds_false_below_low():
    out = _extract_executor(
        {"op": "in_bounds", "low": 0, "high": 10}, {"value": -5}, None)
    assert out["value"] is False
    assert out["passed"] is False


def test_in_bounds_open_high_fence_only_low():
    # Only a low fence → open above; 100 >= 0 passes.
    out = _extract_executor(
        {"op": "in_bounds", "low": 0}, {"value": 100}, None)
    assert out["status"] == "ok"
    assert out["value"] is True


def test_in_bounds_reuses_num_coercion_on_string_numbers():
    # _COMPARE gte/lte carry math.op's _num coercion → "5" coerces to 5.
    out = _extract_executor(
        {"op": "in_bounds", "low": 0, "high": 10}, {"value": "5"}, None)
    assert out["status"] == "ok"
    assert out["value"] is True


# ─── op=exists / op=is_empty — presence + emptiness ─────────────────


def test_exists_true_for_present_value():
    out = _extract_executor({"op": "exists"}, {"value": 0}, None)
    # 0 is a PRESENT value (not None) → exists True (distinct from truthiness).
    assert out["value"] is True
    assert out["passed"] is True


def test_exists_false_for_none():
    out = _extract_executor({"op": "exists"}, {"value": None}, None)
    assert out["value"] is False
    assert out["passed"] is False


def test_is_empty_true_for_empty_list_and_none():
    assert _extract_executor({"op": "is_empty"}, {"value": []}, None)["value"] is True
    assert _extract_executor({"op": "is_empty"}, {"value": None}, None)["value"] is True


def test_is_empty_false_for_zero_scalar():
    # A 0 scalar is a present value, NOT empty.
    out = _extract_executor({"op": "is_empty"}, {"value": 0}, None)
    assert out["value"] is False


# ─── op=contains — membership ───────────────────────────────────────


def test_contains_true_when_needle_in_list():
    out = _extract_executor(
        {"op": "contains", "needle": "ARC"}, {"value": ["ARC", "STR"]}, None)
    assert out["status"] == "ok"
    assert out["value"] is True
    assert out["passed"] is True


def test_contains_false_when_needle_absent():
    out = _extract_executor(
        {"op": "contains", "needle": "CIV"}, {"value": ["ARC", "STR"]}, None)
    assert out["value"] is False
    assert out["passed"] is False


# ─── op=shape — (rows, cols) of a table ─────────────────────────────


def test_shape_of_a_table_extracts_rows_and_cols():
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5, "b": 6}]
    out = _extract_executor({"op": "shape"}, {"value": rows}, None)
    assert out["status"] == "ok"
    assert out["value"] == [3, 2]     # 3 rows, 2 cols
    assert out["passed"] is True


def test_shape_of_empty_is_zero_zero():
    out = _extract_executor({"op": "shape"}, {"value": []}, None)
    assert out["value"] == [0, 0]
    assert out["passed"] is False


# ─── wired param beats config (data.join parity) ────────────────────


def test_wired_high_overrides_config_high():
    # config says high=1 (5 would fail) but wired high=10 → pass.
    out = _extract_executor(
        {"op": "in_bounds", "low": 0, "high": 1},
        {"value": 5, "high": 10}, None)
    assert out["passed"] is True


def test_wired_needle_overrides_config_needle():
    out = _extract_executor(
        {"op": "contains", "needle": "MISS"},
        {"value": ["ARC"], "needle": "ARC"}, None)
    assert out["value"] is True


# ─── default op + report ────────────────────────────────────────────


def test_op_defaults_to_length():
    # No op set → defaults to length.
    out = _extract_executor({}, {"value": [1, 2]}, None)
    assert out["status"] == "ok"
    assert out["value"] == 2


def test_message_is_prefixed_to_report():
    out = _extract_executor(
        {"op": "length", "message": "walls present?"},
        {"value": [1]}, None)
    assert out["report"].startswith("walls present?: ")
    assert "PASS" in out["report"]


def test_report_is_never_empty_on_any_path():
    for cfg, ins in (
        ({"op": "length"}, {"value": [1]}),          # pass
        ({"op": "length"}, {"value": []}),           # fail
        ({"op": "bogus"}, {"value": 1}),             # malformed
        ({"op": "in_bounds"}, {"value": 1}),         # malformed (no fence)
    ):
        out = _extract_executor(cfg, ins, None)
        assert out["report"]


# ─── malformed check → typed error, never fabricated ────────────────


def test_unknown_op_is_typed_error():
    out = _extract_executor({"op": "telepathy"}, {"value": 1}, None)
    assert out["status"] == "error"
    assert out["passed"] is False
    assert out["value"] is None
    assert "unknown op" in out["report"]


def test_in_bounds_with_no_fence_is_typed_error():
    out = _extract_executor({"op": "in_bounds"}, {"value": 5}, None)
    assert out["status"] == "error"
    assert out["passed"] is False
    assert "no bound" in out["report"]


def test_in_bounds_non_numeric_inherits_math_op_zero_coercion():
    # ONE-SYSTEM: in_bounds reuses _COMPARE, whose `_num` coerces an
    # un-parseable value to 0.0 (it never raises) — so "not-a-number" reads as
    # 0, which is within [0, 10]. This is math.op's semantics inherited, NOT a
    # fabricated verdict: a clean read, status ok.
    out = _extract_executor(
        {"op": "in_bounds", "low": 0, "high": 10}, {"value": "not-a-number"},
        None)
    assert out["status"] == "ok"
    assert out["value"] is True       # 0 (coerced) is in [0, 10]


# ─── registration + typed ports + grammar ───────────────────────────


def test_sense_registered():
    import workflows.nodes.sense  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("sense.extract") is not None


def test_sense_ports_are_typed():
    import workflows.nodes.sense  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("sense.extract")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"value": "any", "passed": "boolean", "report": "string"}
    in_ports = {p.name for p in spec.inputs}
    assert {"value", "low", "high", "needle"} <= in_ports
    # `value` is the only required input.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"value"}


def test_sense_category_is_control():
    import workflows.nodes.sense  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("sense.extract")
    assert spec.category == "control"


def test_sense_config_schema_has_op_enum():
    import workflows.nodes.sense  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("sense.extract")
    op_schema = spec.config_schema["op"]
    # The op enum surfaces the property vocabulary to the library/UI.
    assert "length" in op_schema["options"]
    assert "in_bounds" in op_schema["options"]
    assert "keys" in op_schema["options"]


def test_sense_in_grammar_resolves_to_engine_type():
    import workflows  # noqa: F401  registers built-ins
    from workflows import node_grammar as ng
    assert ng.engine_type("sense") == "sense.extract"


# ─── end-to-end: cook the cell through a real WorkflowRunner ────────


def test_sense_cooks_length_through_real_runner_and_reads_typed_outputs():
    """value source → sense.extract(length) → value(count) / passed / report
    come off the registered output ports, driven through a real outer
    WorkflowRunner (the canvas cook path)."""
    import workflows.nodes.sense  # noqa: F401  registers sense.extract
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
            {"id": "s", "type": "sense.extract",
             "config": {"op": "length", "message": "walls present?"},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "value",  "t": "any"},
                      {"id": "passed", "t": "boolean"},
                      {"id": "report", "t": "string"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["s", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("s")

    assert out.get("status") == "ok"
    assert out["value"] == 3          # the extracted count flows downstream
    assert out["passed"] is True
    assert out["report"].startswith("walls present?: PASS")


def test_sense_cooks_in_bounds_fail_branch_through_real_runner():
    """A failing in_bounds read cooks to passed=false + status ok (so a
    downstream If can branch), driven through the real runner."""
    import workflows.nodes.sense  # noqa: F401
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
             "config": {"value": 99},
             "outs": [{"id": "value", "t": "number"}]},
            {"id": "s", "type": "sense.extract",
             "config": {"op": "in_bounds", "low": 0, "high": 10},
             "ins":  [{"id": "value", "t": "any"}],
             "outs": [{"id": "value",  "t": "any"},
                      {"id": "passed", "t": "boolean"},
                      {"id": "report", "t": "string"}]},
        ],
        "wires": [
            {"from": ["src", "value"], "to": ["s", "value"]},
        ],
    }
    out = WorkflowRunner(graph).pull("s")

    assert out.get("status") == "ok"   # a clean false is OK, branchable
    assert out["value"] is False
    assert out["passed"] is False
    assert "FAIL" in out["report"]
