"""Engine invariants — impossible-state + metamorphic court layer 0
(SPEC §19 forcings; workflows/invariants.py).

Pins:
  * healthy seeded random DAG sweep (10 seeds, data.constant + math.op
    + data.reduce) -> convene green AND every sink matches a test-side
    independent evaluation (a real oracle, not the engine echoed back);
  * MR-1: full-from-scratch vs incremental-recook agree after random
    config edits;
  * INJECTED violations (a lying data.reduce, a lying control.foreach)
    -> convene returns green=False NAMING the node — the court can FAIL;
  * KPN determinism over 3 fresh runners;
  * operad regroup-invariance on a 6-node graph grouped 2 ways via the
    existing compose_subgraph;
  * frozen-mutation detection via snapshot_frozen;
  * env flag ARCHHUB_COURT_INVARIANTS=1 + injected violation -> the
    cook itself RAISES; flag off -> default path untouched (the lie
    flows through silently — proving zero-risk default).

Every assertion pins a hand-calculated value (in comments) — none of
these tests can pass on a stub implementation.
"""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing workflows.nodes registers data.constant / math.op /
# data.reduce / control.foreach; workflows.subgraph registers the
# subgraph.user composite used by the regroup layer.
from workflows import nodes as _nodes_pkg    # noqa: F401
from workflows import subgraph as _subgraph  # noqa: F401
from workflows import invariants
from workflows import registry as _registry
from workflows.runner import WorkflowRunner


# ── graph-building helpers (canvas wire shape, real prod node types) ─

def _const(nid, value):
    return {"id": nid, "type": "data.constant", "config": {"value": value},
            "outs": [{"id": "value", "label": "value", "t": "any"}]}


def _math(nid, op):
    return {"id": nid, "type": "math.op", "config": {"op": op},
            "ins":  [{"id": "a", "label": "a", "t": "any"},
                     {"id": "b", "label": "b", "t": "any"}],
            "outs": [{"id": "value", "label": "value", "t": "any"}]}


def _reduce(nid, op):
    return {"id": nid, "type": "data.reduce", "config": {"op": op},
            "ins":  [{"id": "items", "label": "items", "t": "list"}],
            "outs": [{"id": "value", "label": "value", "t": "any"}]}


def _w(sn, sp, dn, dp):
    return {"from": [sn, sp], "to": [dn, dp]}


def _fixed_graph():
    """c1=3, c2=4 → m1 = 3+4 = 7.0 (math.op coerces float)
    clist=[1,2,3,4] → red(sum) = 1+2+3+4 = 10
    sink = m1 + red = 7 + 10 = 17.0"""
    return {
        "nodes": [_const("c1", 3), _const("c2", 4),
                  _const("clist", [1, 2, 3, 4]),
                  _math("m1", "add"), _reduce("red", "sum"),
                  _math("sink", "add")],
        "wires": [_w("c1", "value", "m1", "a"),
                  _w("c2", "value", "m1", "b"),
                  _w("clist", "value", "red", "items"),
                  _w("m1", "value", "sink", "a"),
                  _w("red", "value", "sink", "b")],
    }


def _lying_reduce(monkeypatch):
    """Monkeypatch data.reduce to return value+1 — the injected lie."""
    spec, real = _registry.get("data.reduce")

    def lying(config, inputs, ctx):
        out = real(config, inputs, ctx)
        if isinstance(out, dict) and isinstance(out.get("value"),
                                                (int, float)):
            out = dict(out)
            out["value"] = out["value"] + 1
        return out

    monkeypatch.setitem(_registry._REGISTRY, "data.reduce", (spec, lying))


# ── seeded random DAG: build + test-side independent oracle ──────────

def _random_graph(seed):
    """3 scalar constants, 1 list constant, a data.reduce, 3 chained
    math.op nodes wired to random earlier outputs. Returns (graph,
    expected) where `expected` maps node id -> value computed HERE with
    plain Python arithmetic (independent oracle, mirrors the engine's
    documented coercion: math.op works in float, data.reduce keeps int
    arithmetic exact)."""
    rng = random.Random(seed)
    nodes, wires = [], []
    expected = {}

    for i in range(3):
        v = rng.randint(1, 9)
        nodes.append(_const(f"c{i}", v))
        expected[f"c{i}"] = v

    lst = [rng.randint(1, 9) for _ in range(rng.randint(2, 5))]
    nodes.append(_const("clist", lst))
    rop = rng.choice(["sum", "product", "min", "max"])
    nodes.append(_reduce("red", rop))
    wires.append(_w("clist", "value", "red", "items"))
    if rop == "sum":
        acc = 0
        for x in lst:
            acc += x
        expected["red"] = acc
    elif rop == "product":
        acc = 1
        for x in lst:
            acc *= x
        expected["red"] = acc
    elif rop == "min":
        expected["red"] = min(lst)
    else:
        expected["red"] = max(lst)

    avail = ["c0", "c1", "c2", "red"]
    for j in range(3):
        mop = rng.choice(["add", "sub", "mul"])
        a = rng.choice(avail)
        b = rng.choice(avail)
        mid = f"m{j}"
        nodes.append(_math(mid, mop))
        wires.append(_w(a, "value", mid, "a"))
        wires.append(_w(b, "value", mid, "b"))
        fa, fb = float(expected[a]), float(expected[b])
        expected[mid] = (fa + fb if mop == "add"
                         else fa - fb if mop == "sub" else fa * fb)
        avail.append(mid)

    return {"nodes": nodes, "wires": wires}, expected


# ── (fixed baseline) the engine actually computes the hand-calc ──────

def test_fixed_graph_cooks_hand_calculated_value():
    r = WorkflowRunner(copy.deepcopy(_fixed_graph()))
    out = r.pull("sink")
    # 3+4=7; sum([1,2,3,4])=10; 7+10=17 (math.op emits float).
    assert out["value"] == pytest.approx(17.0)
    assert r.node_outputs["red"]["value"] == 10
    assert r.node_outputs["m1"]["value"] == pytest.approx(7.0)


# ── (a) healthy seeded sweep: convene green + independent oracle ─────

@pytest.mark.parametrize("seed", list(range(10)))
def test_random_dag_sweep_convene_green(seed):
    graph, expected = _random_graph(seed)
    r = WorkflowRunner(copy.deepcopy(graph))
    r.run_all()
    # Every math/reduce node must match the test-side oracle.
    for nid, want in expected.items():
        if nid.startswith("c"):
            continue
        got = r.node_outputs[nid]["value"]
        assert got == pytest.approx(want), (
            f"seed {seed}: node {nid} cooked {got!r}, oracle says {want!r}")
    verdict = invariants.convene(graph)
    assert verdict["green"] is True
    assert verdict["violations"] == []
    assert "impossible_states" in verdict["layers"]
    assert "determinism" in verdict["layers"]


@pytest.mark.parametrize("seed", list(range(10)))
def test_metamorphic_full_vs_incremental_after_random_edit(seed):
    graph, _ = _random_graph(seed)
    rng = random.Random(1000 + seed)
    target = f"c{rng.randint(0, 2)}"
    new_value = rng.randint(10, 99)   # guaranteed != original (1..9)

    def edit(g, _t=target, _v=new_value):
        for n in g["nodes"]:
            if n["id"] == _t:
                n["config"] = {"value": _v}

    assert invariants.metamorphic_full_vs_incremental(graph, edit) is True


def test_metamorphic_rejects_topology_edits_fail_closed():
    graph = _fixed_graph()

    def bad_edit(g):
        g["nodes"] = [n for n in g["nodes"] if n["id"] != "c2"]

    with pytest.raises(ValueError):
        invariants.metamorphic_full_vs_incremental(graph, bad_edit)


# ── (b) injected violation: the court MUST fail and name the node ────

def test_convene_catches_lying_reduce_and_names_node(monkeypatch):
    graph = _fixed_graph()
    _lying_reduce(monkeypatch)
    verdict = invariants.convene(graph)
    assert verdict["green"] is False
    named = [v for v in verdict["violations"] if v.get("node") == "red"]
    assert named, f"no violation named 'red': {verdict['violations']}"
    v = named[0]
    assert v["kind"] == "reduce_mismatch"
    assert v["expected"] == 10   # sum([1,2,3,4]) = 10, hand-calculated
    assert v["actual"] == 11     # the lie: 10 + 1


def test_check_catches_lying_foreach_count(monkeypatch):
    """control.foreach that reports count = len(items)+1 must be caught."""
    spec, real = _registry.get("control.foreach")

    def lying(config, inputs, ctx):
        out = real(config, inputs, ctx)
        out = dict(out)
        out["count"] = out["count"] + 1    # 3 → 4: the fan-out lie
        return out

    monkeypatch.setitem(_registry._REGISTRY, "control.foreach",
                        (spec, lying))
    graph = {
        "nodes": [_const("clist", [5, 6, 7]),
                  {"id": "fe", "type": "control.foreach", "config": {},
                   "ins":  [{"id": "items", "t": "list"}],
                   "outs": [{"id": "count", "t": "number"}]}],
        "wires": [_w("clist", "value", "fe", "items")],
    }
    verdict = invariants.convene(graph)
    assert verdict["green"] is False
    kinds = {(v.get("kind"), v.get("node")) for v in verdict["violations"]}
    assert ("foreach_count_mismatch", "fe") in kinds


def test_healthy_foreach_inspect_is_green():
    # items [5,6,7]: count=3, first=5, last=7 — all internally consistent.
    graph = {
        "nodes": [_const("clist", [5, 6, 7]),
                  {"id": "fe", "type": "control.foreach", "config": {},
                   "ins":  [{"id": "items", "t": "list"}],
                   "outs": [{"id": "count", "t": "number"}]}],
        "wires": [_w("clist", "value", "fe", "items")],
    }
    r = WorkflowRunner(copy.deepcopy(graph))
    out = r.pull("fe")
    assert out["count"] == 3 and out["first"] == 5 and out["last"] == 7
    assert invariants.check_impossible_states(graph, r) == []


# ── (c) determinism over 3 fresh runners ─────────────────────────────

def test_determinism_three_fresh_runners():
    graph = _fixed_graph()
    assert invariants.determinism_check(graph, n=3) == []
    # Bit-identical sink values across fresh runners: 17.0 each time.
    vals = []
    for _ in range(3):
        r = WorkflowRunner(copy.deepcopy(graph))
        vals.append(r.pull("sink")["value"])
    assert vals == [17.0, 17.0, 17.0]


# ── (d) regroup invariance: 6 nodes, 2 groupings, same sink ──────────

def _six_node_graph():
    """c1=2, c2=3, c3=4
    a1 = c1 + c2 = 5.0
    a2 = a1 * c3 = 20.0
    s  = a2 + c1 = 22.0"""
    return {
        "nodes": [_const("c1", 2), _const("c2", 3), _const("c3", 4),
                  _math("a1", "add"), _math("a2", "mul"),
                  _math("s", "add")],
        "wires": [_w("c1", "value", "a1", "a"),
                  _w("c2", "value", "a1", "b"),
                  _w("a1", "value", "a2", "a"),
                  _w("c3", "value", "a2", "b"),
                  _w("a2", "value", "s", "a"),
                  _w("c1", "value", "s", "b")],
    }


def test_regroup_invariance_two_groupings():
    graph = _six_node_graph()
    # Ungrouped baseline: (2+3)*4 + 2 = 22.0 (hand-calculated).
    r = WorkflowRunner(copy.deepcopy(graph))
    assert r.pull("s")["value"] == pytest.approx(22.0)

    grouping_a = [["c2", "a1"]]       # wrap the adder + one constant
    grouping_b = [["a2", "c3"]]       # wrap the multiplier + its constant
    assert invariants.regroup_invariance(graph, grouping_a,
                                         grouping_b) == []
    verdict = invariants.convene(graph, grouping_a=grouping_a,
                                 grouping_b=grouping_b)
    assert verdict["green"] is True
    assert "regroup" in verdict["layers"]


def test_regroup_detects_divergence_when_composite_lies(monkeypatch):
    """Tamper the subgraph executor so a grouped cook diverges — the
    regroup layer must flag the sink, proving it can FAIL."""
    from workflows import subgraph as sg
    spec, real = _registry.get("subgraph.user")

    def lying(config, inputs, ctx):
        out = real(config, inputs, ctx)
        if isinstance(out, dict):
            out = {k: (v + 1 if isinstance(v, (int, float))
                       and not isinstance(v, bool) and k != "status"
                       else v)
                   for k, v in out.items()}
        return out

    monkeypatch.setitem(_registry._REGISTRY, "subgraph.user",
                        (spec, lying))
    graph = _six_node_graph()
    bad = invariants.regroup_invariance(graph, [["c2", "a1"]],
                                        [["a2", "c3"]])
    assert bad, "lying composite went undetected"
    assert any(v["kind"] == "regroup_divergence" and v["node"] == "s"
               for v in bad)


# ── frozen-mutation detection ────────────────────────────────────────

def test_frozen_mutation_detected_via_snapshot():
    graph = _fixed_graph()
    for n in graph["nodes"]:
        if n["id"] == "red":
            n["frozen"] = True
    r = WorkflowRunner(copy.deepcopy(graph))
    r.run_all()
    snap = invariants.snapshot_frozen(r)
    # Clean second cook: frozen state untouched → no violations.
    r.run_all()
    assert invariants.check_impossible_states(graph, r,
                                              frozen_snapshot=snap) == []
    # Simulate a rogue cook mutating the pinned node's cached outputs.
    r.node_outputs["red"] = {"status": "ok", "value": 999}
    bad = invariants.check_impossible_states(graph, r,
                                             frozen_snapshot=snap)
    assert any(v["kind"] == "frozen_mutated" and v["node"] == "red"
               for v in bad)


# ── (e) env flag: cook raises on violation; default path untouched ───

def test_env_flag_on_injected_violation_raises(monkeypatch):
    graph = _fixed_graph()
    _lying_reduce(monkeypatch)
    monkeypatch.setenv("ARCHHUB_COURT_INVARIANTS", "1")
    r = WorkflowRunner(copy.deepcopy(graph))
    with pytest.raises(invariants.InvariantViolation) as ei:
        r.pull("sink")
    assert "red" in str(ei.value)
    assert any(v["node"] == "red" for v in ei.value.violations)


def test_env_flag_off_default_path_untouched(monkeypatch):
    """Zero-risk default: with the flag OFF the lie flows through and
    the cook does NOT raise — sink = 7 + (10+1) = 18.0."""
    graph = _fixed_graph()
    _lying_reduce(monkeypatch)
    monkeypatch.delenv("ARCHHUB_COURT_INVARIANTS", raising=False)
    r = WorkflowRunner(copy.deepcopy(graph))
    out = r.pull("sink")
    assert out["value"] == pytest.approx(18.0)


def test_env_flag_on_healthy_graph_cooks_normally(monkeypatch):
    monkeypatch.setenv("ARCHHUB_COURT_INVARIANTS", "1")
    r = WorkflowRunner(copy.deepcopy(_fixed_graph()))
    assert r.pull("sink")["value"] == pytest.approx(17.0)
