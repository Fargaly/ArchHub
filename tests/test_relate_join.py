"""stem-rebuild Phase-0 — `data.join`, the reconcile core.

`join` matches two lists on a key (or key pair) and partitions the result
into matched / left_only / right_only — the relational match that turns a
bespoke reconcile code-blob into a composable stem cell.

What's pinned:
  * inner / left / right / outer `how` shapes the `matched` rows;
  * left_only + right_only are ALWAYS the complete diff regardless of how;
  * per-side keys (left_key / right_key) join differently-named id fields;
  * input ports beat config for the key (a wired key wins);
  * duplicate keys yield the cartesian pairing (standard join semantics);
  * flat-list join (no key) keys on the item itself;
  * unhashable / exotic rows never raise (repr fallback);
  * an unknown `how` is a typed error, never a fabricated result;
  * the cell cooks end-to-end through a real WorkflowRunner and its typed
    outputs (matched / left_only / right_only / match_count) are read off
    the registered output ports — the canvas cook path, not just the
    executor.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.relate import _join_executor  # noqa: E402


# ─── inner join (default) ───────────────────────────────────────────


def test_inner_join_matches_on_key():
    left = [{"id": "A", "v": 1}, {"id": "B", "v": 2}]
    right = [{"id": "B", "w": 9}, {"id": "C", "w": 8}]
    out = _join_executor({"key": "id"}, {"left": left, "right": right}, None)
    assert out["status"] == "ok"
    assert out["match_count"] == 1
    assert out["matched"] == [
        {"key": "B", "left": {"id": "B", "v": 2}, "right": {"id": "B", "w": 9}},
    ]
    assert out["left_only"] == [{"id": "A", "v": 1}]
    assert out["right_only"] == [{"id": "C", "w": 8}]


def test_inner_join_default_how_when_unset():
    # No `how` in config → inner.
    left = [{"id": 1}, {"id": 2}]
    right = [{"id": 2}, {"id": 3}]
    out = _join_executor({"key": "id"}, {"left": left, "right": right}, None)
    assert [m["key"] for m in out["matched"]] == [2]


# ─── left / right / outer reshape `matched`, diffs stay complete ────


def test_left_join_reintroduces_unmatched_lefts_as_half_rows():
    left = [{"id": "A"}, {"id": "B"}]
    right = [{"id": "B"}]
    out = _join_executor({"key": "id", "how": "left"},
                         {"left": left, "right": right}, None)
    # B is paired; A comes back with right=None.
    by_key = {m["key"]: m for m in out["matched"]}
    assert by_key["B"]["right"] == {"id": "B"}
    assert by_key["A"]["right"] is None
    assert by_key["A"]["left"] == {"id": "A"}
    # left_only is still the complete diff.
    assert out["left_only"] == [{"id": "A"}]
    assert out["right_only"] == []


def test_right_join_reintroduces_unmatched_rights_as_half_rows():
    left = [{"id": "B"}]
    right = [{"id": "B"}, {"id": "C"}]
    out = _join_executor({"key": "id", "how": "right"},
                         {"left": left, "right": right}, None)
    by_key = {m["key"]: m for m in out["matched"]}
    assert by_key["C"]["left"] is None
    assert by_key["C"]["right"] == {"id": "C"}
    assert out["right_only"] == [{"id": "C"}]
    assert out["left_only"] == []


def test_outer_join_includes_both_unmatched_sides():
    left = [{"id": "A"}, {"id": "B"}]
    right = [{"id": "B"}, {"id": "C"}]
    out = _join_executor({"key": "id", "how": "outer"},
                         {"left": left, "right": right}, None)
    keys = sorted(m["key"] for m in out["matched"])
    assert keys == ["A", "B", "C"]
    assert out["left_only"] == [{"id": "A"}]
    assert out["right_only"] == [{"id": "C"}]


# ─── per-side keys ──────────────────────────────────────────────────


def test_per_side_keys_join_differently_named_id_fields():
    left = [{"ElementId": "W1", "h": 3}, {"ElementId": "W2", "h": 4}]
    right = [{"id": "W2", "fire": "2hr"}]
    out = _join_executor(
        {"left_key": "ElementId", "right_key": "id"},
        {"left": left, "right": right}, None)
    assert out["match_count"] == 1
    m = out["matched"][0]
    assert m["key"] == "W2"
    assert m["left"]["h"] == 4
    assert m["right"]["fire"] == "2hr"
    assert out["left_only"] == [{"ElementId": "W1", "h": 3}]


# ─── input ports beat config (a wired key wins) ─────────────────────


def test_wired_key_input_overrides_absent_config():
    left = [{"k": "x", "v": 1}]
    right = [{"k": "x", "w": 2}]
    # key arrives on the input port, not config.
    out = _join_executor({}, {"left": left, "right": right, "key": "k"}, None)
    assert out["match_count"] == 1
    assert out["matched"][0]["key"] == "x"


# ─── duplicate keys → cartesian pairing ─────────────────────────────


def test_duplicate_keys_yield_cartesian_pairing():
    left = [{"id": "A", "v": 1}, {"id": "A", "v": 2}]
    right = [{"id": "A", "w": 10}, {"id": "A", "w": 20}]
    out = _join_executor({"key": "id"}, {"left": left, "right": right}, None)
    # 2 lefts × 2 rights = 4 matched rows.
    assert out["match_count"] == 4
    pairs = {(m["left"]["v"], m["right"]["w"]) for m in out["matched"]}
    assert pairs == {(1, 10), (1, 20), (2, 10), (2, 20)}
    # Nothing unmatched.
    assert out["left_only"] == []
    assert out["right_only"] == []


# ─── flat-list join (no key) keys on the item itself ────────────────


def test_flat_list_join_keys_on_item_identity():
    out = _join_executor(
        {}, {"left": [1, 2, 3], "right": [2, 3, 4]}, None)
    assert sorted(m["key"] for m in out["matched"]) == [2, 3]
    assert out["left_only"] == [1]
    assert out["right_only"] == [4]


# ─── total tolerance: exotic rows never raise ───────────────────────


def test_unhashable_rows_never_raise_repr_fallback():
    # Lists as rows are unhashable → keyed by repr; identical reprs match.
    out = _join_executor(
        {}, {"left": [[1, 2], [3]], "right": [[3], [9]]}, None)
    assert out["status"] == "ok"
    assert out["match_count"] == 1
    assert out["matched"][0]["left"] == [3]


def test_empty_inputs_are_empty_partitions():
    out = _join_executor({"key": "id"}, {"left": [], "right": []}, None)
    assert out["status"] == "ok"
    assert out["matched"] == []
    assert out["left_only"] == []
    assert out["right_only"] == []
    assert out["match_count"] == 0


def test_non_list_inputs_coerced_to_single_element():
    # A scalar is wrapped to a one-item list (aggregate._as_list parity).
    out = _join_executor({}, {"left": "X", "right": "X"}, None)
    assert out["match_count"] == 1
    assert out["matched"][0]["key"] == "X"


# ─── unknown how → typed error, never fabricated ────────────────────


def test_unknown_how_is_typed_error():
    out = _join_executor(
        {"key": "id", "how": "telepathy"},
        {"left": [{"id": 1}], "right": [{"id": 1}]}, None)
    assert out["status"] == "error"
    assert "unknown how" in out["error"]
    # No fabricated matches on the error path.
    assert out["matched"] == []
    assert out["match_count"] == 0


# ─── registration ───────────────────────────────────────────────────


def test_join_registered():
    import workflows.nodes.relate  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("data.join") is not None


def test_join_output_ports_are_typed():
    import workflows.nodes.relate  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("data.join")
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {
        "matched": "list", "left_only": "list",
        "right_only": "list", "match_count": "number",
    }
    in_ports = {p.name for p in spec.inputs}
    assert {"left", "right", "key", "left_key", "right_key"} <= in_ports
    # left + right are the required inputs.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"left", "right"}


# ─── end-to-end: cook the cell through a real WorkflowRunner ────────


def _const(node_id: str, port_type: str, value):
    """A throwaway const node feeding one typed output port."""
    return {"id": node_id, "type": f"_test.const_{node_id}", "config": {},
            "outs": [{"id": "value", "t": port_type}]}, value


def test_join_cooks_through_real_runner_and_reads_typed_outputs():
    """left list + right list → data.join → assert matched / left_only /
    right_only / match_count come off the registered output ports, driven
    through a real outer WorkflowRunner (the canvas cook path)."""
    import workflows.nodes.relate  # noqa: F401  registers data.join
    from workflows.runner import WorkflowRunner
    from workflows.registry import register, NodeSpec, get as _get_spec
    from workflows.graph import Port, PortType

    left = [{"id": "A", "v": 1}, {"id": "B", "v": 2}, {"id": "C", "v": 3}]
    right = [{"id": "B", "w": 20}, {"id": "C", "w": 30}, {"id": "D", "w": 40}]

    # Minimal const source nodes (registered once, idempotent).
    if _get_spec("_test.const_left") is None:
        register(NodeSpec(
            type="_test.const_left", category="_test",
            display_name="Test Const Left",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.LIST)],
            config_schema={}, icon="["),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})
    if _get_spec("_test.const_right") is None:
        register(NodeSpec(
            type="_test.const_right", category="_test",
            display_name="Test Const Right",
            description="Emits config.value on `value`.",
            inputs=[], outputs=[Port(name="value", type=PortType.LIST)],
            config_schema={}, icon="]"),
            lambda c, i, x: {"status": "ok", "value": c.get("value")})

    graph = {
        "nodes": [
            {"id": "lsrc", "type": "_test.const_left",
             "config": {"value": left},
             "outs": [{"id": "value", "t": "list"}]},
            {"id": "rsrc", "type": "_test.const_right",
             "config": {"value": right},
             "outs": [{"id": "value", "t": "list"}]},
            {"id": "j", "type": "data.join", "config": {"key": "id"},
             "ins":  [{"id": "left", "t": "list"},
                      {"id": "right", "t": "list"}],
             "outs": [{"id": "matched", "t": "list"},
                      {"id": "left_only", "t": "list"},
                      {"id": "right_only", "t": "list"},
                      {"id": "match_count", "t": "number"}]},
        ],
        "wires": [
            {"from": ["lsrc", "value"], "to": ["j", "left"]},
            {"from": ["rsrc", "value"], "to": ["j", "right"]},
        ],
    }
    out = WorkflowRunner(graph).pull("j")

    assert out.get("status") == "ok"
    # B + C match on id.
    assert out["match_count"] == 2
    assert sorted(m["key"] for m in out["matched"]) == ["B", "C"]
    # A is left-only; D is right-only — the reconcile diff.
    assert out["left_only"] == [{"id": "A", "v": 1}]
    assert out["right_only"] == [{"id": "D", "w": 40}]
