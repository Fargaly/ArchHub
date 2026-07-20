"""WorkflowRunner — wires-as-real-data-bridges (v1.4).

Pins:
  - Topo-sort via lazy pull walks upstream
  - Dirty mark cascades to all descendants
  - cache_key changes when params or upstream cache_keys change
  - Cache hit on second pull (no upstream change) skips re-execution
  - Cycle detection refuses src→dst when a path dst→src exists
  - WireBus stores values in-process, not persisted
  - on_wire_state callback fires for every state transition
  - Errors propagate as upstream_error on downstream edges

Workflow registry must be importable (registers AEC + io_data + control
nodes). The tests don't need PyQt — runner.py is pure Python.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes triggers registration; do it once.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows.runner import WorkflowRunner, CycleDetected
from workflows.registry import register, NodeSpec, get as _get_spec
from workflows.graph import Port, PortType


# ── Test-only nodes ─────────────────────────────────────────────────
# We register a tiny adder + a no-op for unit testing the runner
# without depending on AEC executors that may have side effects.

def _adder_exec(config, inputs, ctx):
    a = float(inputs.get("a", 0) or 0)
    b = float(inputs.get("b", 0) or 0)
    return {"status": "ok", "sum": a + b}


def _constant_exec(config, inputs, ctx):
    return {"status": "ok", "value": config.get("value", 0)}


def _error_exec(config, inputs, ctx):
    return {"status": "error", "error": "boom"}


# Register only once per test session (re-register raises).
def _ensure_test_nodes():
    if _get_spec("_test.adder") is None:
        register(NodeSpec(
            type="_test.adder", category="_test",
            display_name="Test Adder", description="Adds a + b",
            inputs=[Port(name="a", type=PortType.NUMBER),
                     Port(name="b", type=PortType.NUMBER)],
            outputs=[Port(name="sum", type=PortType.NUMBER)],
            config_schema={}, icon="+",
        ), _adder_exec)
    if _get_spec("_test.constant") is None:
        register(NodeSpec(
            type="_test.constant", category="_test",
            display_name="Test Constant", description="Emits a constant",
            inputs=[],
            outputs=[Port(name="value", type=PortType.NUMBER)],
            config_schema={"value": {"type": "number"}}, icon="·",
        ), _constant_exec)
    if _get_spec("_test.error") is None:
        register(NodeSpec(
            type="_test.error", category="_test",
            display_name="Always Errors", description="error",
            inputs=[],
            outputs=[Port(name="out", type=PortType.NUMBER)],
            config_schema={}, icon="!",
        ), _error_exec)


@pytest.fixture(autouse=True)
def _setup():
    _ensure_test_nodes()


def _g(nodes, wires):
    """Helper to build a graph dict."""
    return {"nodes": nodes, "wires": wires}


def _const(node_id, value):
    return {"id": node_id, "type": "_test.constant",
            "config": {"value": value}, "ins": [],
            "outs": [{"id": "value", "t": "number"}]}


def _add(node_id):
    return {"id": node_id, "type": "_test.adder",
            "config": {},
            "ins":  [{"id": "a", "t": "number"},
                      {"id": "b", "t": "number"}],
            "outs": [{"id": "sum", "t": "number"}]}


def _wire(from_node, from_port, to_node, to_port):
    return {"from": [from_node, from_port],
            "to":   [to_node, to_port]}


# ── Topology ────────────────────────────────────────────────────────
class TestTopology:
    def test_pull_walks_upstream(self):
        """5 + 7 should land at the adder via two upstream pulls."""
        graph = _g(
            [_const("a", 5), _const("b", 7), _add("sum")],
            [_wire("a", "value", "sum", "a"),
             _wire("b", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        out = r.pull("sum")
        assert out["status"] == "ok"
        assert out["sum"] == 12

    def test_pull_for_leaf_node_with_no_upstream(self):
        graph = _g([_const("a", 99)], [])
        r = WorkflowRunner(graph)
        out = r.pull("a")
        assert out["value"] == 99

    def test_unknown_node_returns_error(self):
        graph = _g([_const("a", 1)], [])
        r = WorkflowRunner(graph)
        out = r.pull("nope")
        assert out["status"] == "error"

    def test_unknown_node_type_returns_error(self):
        graph = _g([{"id": "x", "type": "_does_not_exist",
                       "config": {}, "ins": [], "outs": []}], [])
        r = WorkflowRunner(graph)
        out = r.pull("x")
        assert out["status"] == "error"
        assert "executor" in out["error"]


# ── Caching ─────────────────────────────────────────────────────────
class TestCaching:
    def test_second_pull_hits_cache(self):
        graph = _g(
            [_const("a", 2), _const("b", 3), _add("sum")],
            [_wire("a", "value", "sum", "a"),
             _wire("b", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        # Replace the executor with a flag to detect re-cook.
        called = {"n": 0}
        _, original = _get_spec("_test.adder")
        def spy(c, i, x):
            called["n"] += 1
            return original(c, i, x)
        from workflows import registry as _reg
        _reg._REGISTRY["_test.adder"] = (
            _reg._REGISTRY["_test.adder"][0], spy)
        try:
            r.pull("sum")
            assert called["n"] == 0, "should hit cache, not re-cook"
        finally:
            _reg._REGISTRY["_test.adder"] = (
                _reg._REGISTRY["_test.adder"][0], original)

    def test_mark_dirty_invalidates_cache(self):
        graph = _g(
            [_const("a", 2), _const("b", 3), _add("sum")],
            [_wire("a", "value", "sum", "a"),
             _wire("b", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        r.mark_dirty("sum")
        # After dirty, pull must re-run.
        called = {"n": 0}
        _, original = _get_spec("_test.adder")
        def spy(c, i, x):
            called["n"] += 1
            return original(c, i, x)
        from workflows import registry as _reg
        _reg._REGISTRY["_test.adder"] = (
            _reg._REGISTRY["_test.adder"][0], spy)
        try:
            r.pull("sum")
            assert called["n"] == 1
        finally:
            _reg._REGISTRY["_test.adder"] = (
                _reg._REGISTRY["_test.adder"][0], original)

    def test_mark_dirty_cascades_downstream(self):
        # Chain: a → mid → sum. Dirtying `a` should also dirty `mid` + `sum`.
        graph = _g(
            [_const("a", 1), _const("b", 2),
             _add("mid"), _const("c", 0), _add("sum")],
            [_wire("a", "value", "mid", "a"),
             _wire("b", "value", "mid", "b"),
             _wire("mid", "sum", "sum", "a"),
             _wire("c", "value", "sum", "b")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        touched = r.mark_dirty("a")
        assert "a" in touched
        assert "mid" in touched
        assert "sum" in touched


# ── Cycle detection ─────────────────────────────────────────────────
class TestWireBehaviorLayer:
    def _output(self):
        return {
            "id": "out",
            "type": "output.parameter",
            "config": {"name": "result"},
            "ins": [{"id": "value", "t": "any"}],
            "outs": [{"id": "value", "t": "any"}],
        }

    def _second_pull_source_calls(self, behavior):
        graph = _g(
            [_const("src", 5), self._output()],
            [{"id": "behavior-wire", "from": ["src", "value"],
              "to": ["out", "value"], "behavior": behavior}],
        )
        r = WorkflowRunner(graph)
        assert r.pull("out")["value"] == 5
        called = {"n": 0}
        _, original = _get_spec("_test.constant")

        def spy(c, i, x):
            called["n"] += 1
            return original(c, i, x)

        from workflows import registry as _reg
        _reg._REGISTRY["_test.constant"] = (
            _reg._REGISTRY["_test.constant"][0], spy)
        try:
            assert r.pull("out")["value"] == 5
            return called["n"]
        finally:
            _reg._REGISTRY["_test.constant"] = (
                _reg._REGISTRY["_test.constant"][0], original)

    def test_pull_on_demand_wire_behavior_uses_cached_source(self):
        assert self._second_pull_source_calls("pull-on-demand") == 0

    def test_force_recook_wire_behavior_makes_source_live_not_cached(self):
        assert self._second_pull_source_calls("force-recook") == 1


class TestNodeNativeWireAuthority:
    def _node_native_graph(self, *, layer_value: str | None = None,
                           presentation: str = ""):
        nodes = [
            {"id": "src", "kind": "constant",
             "params": [{"k": "value", "v": 42}],
             "outs": [{"id": "value", "t": "number"}]},
            {"id": "out", "kind": "output",
             "params": [{"k": "name", "v": "result"}],
             "ins": [{"id": "value", "t": "number"}],
             "outs": [{"id": "value", "t": "number"}]},
            {"id": "wire:src-out", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_id": "edge:src-out",
                "source_owner": "src",
                "target_owner": "out",
                "from_node": "src",
                "from_port": "value",
                "to_node": "out",
                "to_port": "value",
                "gate_policy": "type-compatible-and-enabled",
            }},
        ]
        if presentation:
            nodes[2]["data"]["presentation"] = presentation
        if layer_value is not None:
            nodes[2]["data"]["layer_nodes"] = {
                "gate": "wire:src-out:layer:gate"
            }
            nodes.append({"id": "wire:src-out:layer:gate",
                          "kind": "group",
                          "data": {
                              "role": "wire_layer",
                              "wire_family": "workflow_wire",
                              "owner": "wire:src-out",
                              "layer": "gate",
                              "value_key": "gate_policy",
                              "value": layer_value,
                          }})
        return {"nodes": nodes, "wires": []}

    def test_runner_executes_from_wire_node_without_raw_edge(self):
        r = WorkflowRunner(self._node_native_graph())

        assert set(r.nodes_by_id) == {"src", "out"}
        assert r.relations is r.edges
        assert r.edges == [{
            "id": "edge:src-out",
            "src_node": "src",
            "src_port": "value",
            "dst_node": "out",
            "dst_port": "value",
            "cache_key": "",
            "state": "idle",
            "src_field": "",
            "dst_field": "",
            "wire_node": "wire:src-out",
            "gate_policy": "type-compatible-and-enabled",
        }]
        out = r.pull("out")

        assert out["value"] == 42
        assert r.wire_value("edge:src-out") == 42

    def test_runtime_relations_override_legacy_wire_projection(self):
        graph = {
            "nodes": [
                {"id": "src", "type": "data.constant",
                 "config": {"value": 42}},
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"}},
            ],
            "relations": [{
                "id": "relation-projection",
                "src_node": "src", "src_port": "value",
                "dst_node": "out", "dst_port": "value",
                "wire_node": "relation:src-out",
            }],
            "wires": [{
                "id": "stale-compatibility-wire",
                "src_node": "missing", "src_port": "value",
                "dst_node": "out", "dst_port": "value",
            }],
        }

        runner = WorkflowRunner(graph)

        assert [relation["id"] for relation in runner.relations] == [
            "relation-projection"
        ]
        assert runner.relations[0]["wire_node"] == "relation:src-out"
        assert runner.pull("out")["value"] == 42

    def test_runner_uses_wire_layer_node_as_gate_authority(self):
        r = WorkflowRunner(self._node_native_graph(layer_value="deny"))
        out = r.pull("out")

        assert out.get("value") is None
        assert r.wire_state("edge:src-out") == "blocked"
        assert r.wire_value("edge:src-out") is None

    def test_parent_junction_wire_layer_controls_branch_wire(self):
        graph = self._node_native_graph()
        graph["nodes"].extend([
            {"id": "wire:junction:src-value", "kind": "wire", "data": {
                "role": "wire",
                "wire_family": "workflow_wire",
                "wire_topology": "fanout",
                "wire_id": "junction:src-value",
                "from_node": "src",
                "from_port": "value",
                "member_wire_node_ids": ["wire:src-out"],
                "layer_nodes": {
                    "gate": "wire:junction:src-value:layer:gate"
                },
            }},
            {"id": "wire:junction:src-value:layer:gate",
             "kind": "group",
             "data": {
                 "role": "wire_layer",
                 "wire_family": "workflow_wire",
                 "owner": "wire:junction:src-value",
                 "layer": "gate",
                 "value_key": "gate_policy",
                 "value": "deny",
             }},
        ])
        branch = next(n for n in graph["nodes"] if n["id"] == "wire:src-out")
        branch["data"]["junction_node"] = "wire:junction:src-value"

        r = WorkflowRunner(graph)
        out = r.pull("out")

        assert r.edges[0]["junction_node"] == "wire:junction:src-value"
        assert r.edges[0]["gate_policy"] == "deny"
        assert out.get("value") is None
        assert r.wire_state("edge:src-out") == "blocked"

    def test_run_all_does_not_cook_wire_plumbing_nodes(self):
        r = WorkflowRunner(self._node_native_graph())
        result = r.run_all()

        assert set(result["results"]) == {"out"}
        assert "wire:src-out" not in r.nodes_by_id
        assert result["results"]["out"]["value"] == 42

    def test_direct_runner_uses_parameter_node_config_authority(self):
        graph = {
            "nodes": [
                {"id": "src", "kind": "constant",
                 "params": [{"k": "value", "v": 1}]},
                {"id": "param:src:value", "kind": "param",
                 "data": {"role": "parameter",
                          "owner": "src",
                          "key": "value",
                          "value": 77}},
            ],
            "wires": [],
        }
        r = WorkflowRunner(graph)

        assert set(r.nodes_by_id) == {"src"}
        assert r.pull("src")["value"] == 77

    def test_edges_state_reports_runtime_wire_node_layers(self):
        r = WorkflowRunner(self._node_native_graph(presentation="hidden"))
        result = r.run_all()

        edge_state = result["edges_state"][0]
        assert edge_state["id"] == "edge:src-out"
        assert edge_state["wire_node"] == "wire:src-out"
        assert edge_state["gate_policy"] == "type-compatible-and-enabled"
        assert edge_state["presentation"] == "hidden"
        assert edge_state["presentation_state"] == "hidden"
        assert edge_state["preview"] == "42"


class TestNodeBehaviorFlags:
    @pytest.mark.parametrize("flag_payload", [
        {"bypass": True},
        {"bypassed": True},
        {"config": {"bypass": True}},
    ])
    def test_runner_accepts_canonical_and_legacy_bypass_flags(self, flag_payload):
        bypassed = _add("mid")
        bypassed.update(flag_payload)
        graph = _g(
            [_const("a", 5), _const("b", 7), bypassed],
            [_wire("a", "value", "mid", "a"),
             _wire("b", "value", "mid", "b")],
        )

        out = WorkflowRunner(graph).pull("mid")

        assert out["status"] == "ok"
        assert out["bypassed"] is True
        assert out["sum"] == 5

    def test_runner_accepts_config_frozen_flag(self):
        frozen = _add("frozen")
        frozen["config"] = {"frozen": True}
        graph = _g([frozen], [])

        out = WorkflowRunner(graph).pull("frozen")

        assert out == {"status": "ok", "frozen": True}


class TestCycleDetection:
    def test_no_cycle_for_simple_chain(self):
        graph = _g(
            [_const("a", 1), _const("b", 2), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        assert r.would_create_cycle("b", "sum") is False

    def test_cycle_detected_through_back_edge(self):
        # a → b → c; adding c → a would loop.
        graph = _g(
            [_const("a", 1), _const("b", 2), _const("c", 3)],
            [_wire("a", "value", "b", "a"),
             _wire("b", "value", "c", "a")],
        )
        r = WorkflowRunner(graph)
        assert r.would_create_cycle("c", "a") is True

    def test_self_loop_refused(self):
        graph = _g([_const("a", 1)], [])
        r = WorkflowRunner(graph)
        assert r.would_create_cycle("a", "a") is True


# ── Wire state callbacks ────────────────────────────────────────────
class TestWireStateCallbacks:
    def test_on_wire_state_fires_for_each_transition(self):
        graph = _g(
            [_const("a", 7), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        seen: list = []
        r.on_wire_state(lambda eid, st, prev:
                          seen.append((eid, st)))
        r.pull("sum")
        # Should see at least: flowing then cached for the edge.
        states = [s for _, s in seen]
        assert "flowing" in states
        assert "cached" in states

    def test_wire_value_lives_in_bus(self):
        graph = _g(
            [_const("a", 42), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        # The edge id is derived from from/to nodes + ports.
        eid = "a.value-sum.a"
        assert r.wire_value(eid) == 42

    def test_persistable_state_drops_values(self):
        graph = _g(
            [_const("a", 9), _add("sum")],
            [_wire("a", "value", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        r.pull("sum")
        snap = r.persistable_state()
        # Only metadata is serialized.
        assert "edges" in snap
        assert "node_cache_keys" in snap
        # Values are NOT in the snapshot — they live only in wire_bus.
        for e in snap["edges"]:
            assert "value" not in e


# ── Error propagation ──────────────────────────────────────────────
class TestErrorPropagation:
    def test_upstream_error_marks_downstream_state(self):
        graph = _g(
            [{"id": "boom", "type": "_test.error",
              "config": {}, "ins": [],
              "outs": [{"id": "out", "t": "number"}]},
             _add("sum")],
            [_wire("boom", "out", "sum", "a")],
        )
        r = WorkflowRunner(graph)
        out = r.pull("sum")
        assert out["status"] == "upstream_error"
        # The edge state should reflect this.
        e = next(e for e in r.edges if e["src_node"] == "boom")
        assert e["state"] == "upstream_error"


class TestWireGatePolicy:
    def test_gate_policy_deny_blocks_flow_but_keeps_wire_observable(self):
        graph = _g(
            [_const("a", 5), _const("b", 7), _add("sum")],
            [
                {"id": "blocked-wire", "from": ["a", "value"],
                 "to": ["sum", "a"], "gate_policy": "deny"},
                {"id": "open-wire", "from": ["b", "value"],
                 "to": ["sum", "b"]},
            ],
        )
        r = WorkflowRunner(graph)
        out = r.pull("sum")

        assert out["status"] == "ok"
        assert out["sum"] == 7
        assert r.wire_state("blocked-wire") == "blocked"
        assert r.wire_value("blocked-wire") is None
        assert r.wire_state("open-wire") == "flowing"

    def test_type_compatible_gate_blocks_port_type_mismatch(self):
        src = _const("geom", 5)
        src["outs"] = [{"id": "value", "t": "geometry"}]
        graph = _g(
            [src, _const("b", 7), _add("sum")],
            [
                {"id": "typed-wire", "from": ["geom", "value"],
                 "to": ["sum", "a"],
                 "gate_policy": "type-compatible-and-enabled"},
                {"id": "open-wire", "from": ["b", "value"],
                 "to": ["sum", "b"]},
            ],
        )
        r = WorkflowRunner(graph)
        out = r.pull("sum")

        assert out["status"] == "ok"
        assert out["sum"] == 7
        assert r.wire_state("typed-wire") == "blocked"
        typed_edge = next(e for e in r.edges if e["id"] == "typed-wire")
        assert typed_edge["value_preview"] == "type_mismatch:geometry->number"

    def test_custom_port_type_identity_flows_without_enum_registration(self):
        custom = "founder.geometry.facade-panel"
        src = _const("panel", 5)
        src["outs"] = [{"id": "value", "t": custom}]
        sink = _add("sum")
        sink["ins"][0]["t"] = custom
        graph = _g(
            [src, _const("b", 7), sink],
            [
                {"id": "custom-wire", "from": ["panel", "value"],
                 "to": ["sum", "a"],
                 "gate_policy": "type-compatible-and-enabled"},
                {"id": "open-wire", "from": ["b", "value"],
                 "to": ["sum", "b"]},
            ],
        )
        r = WorkflowRunner(graph)

        assert r.pull("sum")["sum"] == 12
        assert r.wire_state("custom-wire") == "flowing"

    def test_custom_port_type_mismatch_retains_exact_names(self):
        src = _const("panel", 5)
        src["outs"] = [
            {"id": "value", "t": "founder.geometry.facade-panel"}]
        sink = _add("sum")
        sink["ins"][0]["t"] = "founder.image.material"
        graph = _g(
            [src, _const("b", 7), sink],
            [
                {"id": "custom-wire", "from": ["panel", "value"],
                 "to": ["sum", "a"],
                 "gate_policy": "type-compatible-and-enabled"},
                {"id": "open-wire", "from": ["b", "value"],
                 "to": ["sum", "b"]},
            ],
        )
        r = WorkflowRunner(graph)

        assert r.pull("sum")["sum"] == 7
        assert r.wire_state("custom-wire") == "blocked"
        edge = next(e for e in r.edges if e["id"] == "custom-wire")
        assert edge["value_preview"] == (
            "type_mismatch:founder.geometry.facade-panel"
            "->founder.image.material")

    def test_require_schema_gate_blocks_wire_without_schema_ref(self):
        graph = _g(
            [
                _const("src", {"mesh": "facade"}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "schema-wire", "from": ["src", "value"],
              "to": ["out", "value"], "gate_policy": "require-schema"}],
        )
        r = WorkflowRunner(graph)
        out = r.pull("out")

        assert out.get("value") is None
        assert r.wire_state("schema-wire") == "blocked"
        edge = next(e for e in r.edges if e["id"] == "schema-wire")
        assert edge["value_preview"] == "schema_required"

    def test_require_schema_gate_allows_wire_with_schema_ref(self):
        graph = _g(
            [
                _const("src", {"mesh": "facade"}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "schema-wire", "from": ["src", "value"],
              "to": ["out", "value"], "gate_policy": "require-schema",
              "schema_ref": "archhub.geometry.mesh"}],
        )
        r = WorkflowRunner(graph)
        result = r.run_all()

        assert result["results"]["out"]["value"] == {"mesh": "facade"}
        edge_state = result["edges_state"][0]
        assert edge_state["schema_ref"] == "archhub.geometry.mesh"
        assert edge_state["gate_policy"] == "require-schema"


class TestWireTransportLayers:
    def test_edges_state_exposes_safe_image_uri_transport_payload(self):
        data_uri = (
            "data:image/svg+xml;utf8,"
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'>"
            "<rect width='8' height='8' fill='red'/></svg>"
        )
        graph = _g(
            [
                _const("src", data_uri),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "image-wire", "from": ["src", "value"],
              "to": ["out", "value"], "codec": "image-uri",
              "value_type": "image", "presentation": "image-preview"}],
        )

        result = WorkflowRunner(graph).run_all()
        edge_state = result["edges_state"][0]

        assert result["results"]["out"]["value"] == data_uri
        assert edge_state["transport_value"] == data_uri
        assert edge_state["value_type"] == "image"
        assert edge_state["codec"] == "image-uri"
        assert edge_state["presentation"] == "image-preview"

    def test_edges_state_exposes_safe_geometry_transport_payload(self):
        geometry = {
            "type": "geometry",
            "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0],
            "faces": [[0, 1, 2]],
        }
        graph = _g(
            [
                _const("src", geometry),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "geometry-wire", "from": ["src", "value"],
              "to": ["out", "value"], "codec": "geometry-json",
              "value_type": "geometry", "presentation": "geometry-preview"}],
        )

        result = WorkflowRunner(graph).run_all()
        edge_state = result["edges_state"][0]

        assert result["results"]["out"]["value"] == geometry
        assert edge_state["transport_value"] == {
            "codec": "geometry-json:v1",
            "payload": geometry,
        }
        assert edge_state["value_type"] == "geometry"
        assert edge_state["codec"] == "geometry-json"
        assert edge_state["presentation"] == "geometry-preview"

    def test_edges_state_redacted_transport_payload_does_not_leak_value(self):
        secret_value = {"secret": "wall schedule"}
        graph = _g(
            [
                _const("src", secret_value),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "redacted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "encryption": "redacted"}],
        )

        result = WorkflowRunner(graph).run_all()
        edge_state = result["edges_state"][0]

        assert result["results"]["out"]["value"] == secret_value
        assert edge_state["transport_value"] == {
            "redacted": True,
            "scheme": "redacted:v1",
            "codec": "json",
            "value_type": "dict",
        }
        assert "wall schedule" not in repr(edge_state["transport_value"])

    def test_json_codec_stores_encoded_wire_payload_but_delivers_value(self):
        graph = _g(
            [
                _const("src", {"b": 2, "a": 1}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "json-wire", "from": ["src", "value"],
              "to": ["out", "value"], "codec": "json"}],
        )
        r = WorkflowRunner(graph)
        out = r.pull("out")

        assert out["value"] == {"a": 1, "b": 2}
        assert r.wire_value("json-wire") == '{"a": 1, "b": 2}'

    def test_base64_codec_stores_encoded_wire_payload_but_delivers_value(self):
        graph = _g(
            [
                _const("src", {"secret": "wall schedule"}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "base64-wire", "from": ["src", "value"],
              "to": ["out", "value"], "codec": "base64"}],
        )
        r = WorkflowRunner(graph)
        out = r.pull("out")
        carried = r.wire_value("base64-wire")

        assert out["value"] == {"secret": "wall schedule"}
        assert carried["codec"] == "base64:v1"
        assert carried["media_type"] == "application/json"
        assert "wall schedule" not in carried["data"]

    def test_fernet_encryption_stores_ciphertext_not_plaintext(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        graph = _g(
            [
                _const("src", {"secret": "wall schedule"}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "encrypted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "codec": "json",
              "encryption": "fernet"}],
        )
        r = WorkflowRunner(graph, ctx=SimpleNamespace(wire_fernet_key=key))
        out = r.pull("out")
        carried = r.wire_value("encrypted-wire")

        assert out["value"] == {"secret": "wall schedule"}
        assert carried["encrypted"] is True
        assert carried["scheme"] == "fernet:v1"
        assert "wall schedule" not in carried["token"]
        decrypted = Fernet(key).decrypt(carried["token"].encode("ascii"))
        assert decrypted.decode("utf-8") == '{"secret": "wall schedule"}'

    def test_local_key_encryption_uses_scoped_context_key(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        graph = _g(
            [
                _const("src", {"secret": "wall schedule"}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "encrypted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "codec": "json",
              "encryption": "local-key"}],
        )
        r = WorkflowRunner(graph, ctx=SimpleNamespace(local_wire_fernet_key=key))
        out = r.pull("out")
        carried = r.wire_value("encrypted-wire")

        assert out["value"] == {"secret": "wall schedule"}
        assert carried["encrypted"] is True
        assert carried["scheme"] == "fernet:v1"

    def test_encryption_key_reference_resolves_only_at_runtime(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        requested = []

        def resolve_secret_ref(ref):
            requested.append(ref)
            return key

        graph = _g(
            [
                _const("src", {"secret": "wall schedule"}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "encrypted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "codec": "json",
              "encryption": "fernet",
              "encryption_key_ref": "op://ArchHub/wires/workspace"}],
        )
        ctx = SimpleNamespace(resolve_secret_ref=resolve_secret_ref)
        r = WorkflowRunner(graph, ctx=ctx)

        out = r.pull("out")
        carried = r.wire_value("encrypted-wire")

        assert requested == ["op://ArchHub/wires/workspace"]
        assert out["value"] == {"secret": "wall schedule"}
        assert carried["encrypted"] is True
        assert "wall schedule" not in carried["token"]

    def test_raw_encryption_key_on_relation_is_rejected(self):
        from cryptography.fernet import Fernet

        graph = _g(
            [
                _const("src", "secret"),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "encrypted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "encryption": "fernet",
              "encryption_key": Fernet.generate_key().decode("ascii")}],
        )

        out = WorkflowRunner(graph).pull("out")

        assert out["status"] == "wire_error"
        assert out["error"] == "raw_encryption_key_forbidden"

    def test_encryption_key_reference_must_be_op_reference(self):
        graph = _g(
            [
                _const("src", "secret"),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "encrypted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "encryption": "fernet",
              "encryption_key_ref": "plain-text-key"}],
        )

        out = WorkflowRunner(graph).pull("out")

        assert out["status"] == "wire_error"
        assert out["error"] == "encryption_key_ref_must_be_op_reference"

    def test_redacted_encryption_hides_wire_bus_but_delivers_value(self):
        graph = _g(
            [
                _const("src", {"secret": "wall schedule"}),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "redacted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "encryption": "redacted"}],
        )
        r = WorkflowRunner(graph)
        out = r.pull("out")
        carried = r.wire_value("redacted-wire")

        assert out["value"] == {"secret": "wall schedule"}
        assert carried == {
            "redacted": True,
            "scheme": "redacted:v1",
            "codec": "json",
            "value_type": "dict",
        }

    def test_secret_ref_encryption_requires_secret_reference(self):
        graph = _g(
            [
                _const("src", "not-a-secret-ref"),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "secret-ref-wire", "from": ["src", "value"],
              "to": ["out", "value"], "encryption": "secret-ref"}],
        )
        r = WorkflowRunner(graph)
        out = r.pull("out")

        assert out["status"] == "wire_error"
        assert "secret_ref_required" in out["error"]
        assert r.wire_state("secret-ref-wire") == "error"

    def test_fernet_encryption_without_key_is_wire_error(self):
        graph = _g(
            [
                _const("src", "secret"),
                {"id": "out", "type": "output.parameter",
                 "config": {"name": "result"},
                 "ins": [{"id": "value", "t": "any"}],
                 "outs": [{"id": "value", "t": "any"}]},
            ],
            [{"id": "encrypted-wire", "from": ["src", "value"],
              "to": ["out", "value"], "encryption": "fernet"}],
        )
        r = WorkflowRunner(graph)
        out = r.pull("out")

        assert out["status"] == "wire_error"
        assert out["edge"] == "encrypted-wire"
        assert "encryption_key_missing" in out["error"]
        assert r.wire_state("encrypted-wire") == "error"

    def test_type_gate_uses_wire_value_type_layer_over_source_port(self):
        src = _const("src", 5)
        src["outs"] = [{"id": "value", "t": "any"}]
        graph = _g(
            [src, _const("b", 7), _add("sum")],
            [
                {"id": "typed-wire", "from": ["src", "value"],
                 "to": ["sum", "a"],
                 "gate_policy": "type-compatible-and-enabled",
                 "value_type": "image"},
                {"id": "open-wire", "from": ["b", "value"],
                 "to": ["sum", "b"]},
            ],
        )
        r = WorkflowRunner(graph)
        out = r.pull("sum")

        assert out["sum"] == 7
        assert r.wire_state("typed-wire") == "blocked"
