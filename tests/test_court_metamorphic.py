# -*- coding: utf-8 -*-
"""COURT layer 1+2 — metamorphic + operad forcings on the REAL WorkflowRunner.

SPEC §16 (layered fail-closed court) + §19 formal foundations, made executable:

  MR-1  METAMORPHIC (Thread 1, the native oracle-free check): after an edit,
        INCREMENTAL recook == FULL from-scratch cook of the edited graph.
        Run over a SWEEP of seeded random DAGs + random edits, not one toy.
  MR-2  DETERMINISM (KPN, Kahn 1974): same graph cooked twice → identical
        values. The graph's value is a fixed point, schedule-independent.
  MR-3  FUNCTOR LAW (§4, algebra over the operad): eval(group) ==
        compose(eval(inner)) — cooking a graph with a subgraph composite
        yields the same sink values as the flat graph.
  MR-4  REGROUP-INVARIANCE (§3, operad associativity): grouping the same
        nodes DIFFERENT ways must yield the same downstream values.
  MR-5  COMPOSE∘EXPAND = id (§3 unit): collapsing then expanding restores
        a graph that cooks identically.
  IMP-1 IMPOSSIBLE-STATE (court stack layer 0): data.reduce(sum) equals the
        plain Python sum of its consumed list — an execution that violates
        this is rejected with certainty (no score to game).

These are machine facts on the production engine — no LLM judgment anywhere.
"""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from workflows import nodes as _nodes_pkg  # noqa: F401,E402  (registers node types)
from workflows.runner import WorkflowRunner  # noqa: E402
from workflows.subgraph import (  # noqa: E402
    compose_subgraph,
    expand_subgraph,
    register_subgraph_executor,
)

register_subgraph_executor()


# ── graph builders ───────────────────────────────────────────────────
def _const(nid, value):
    return {"id": nid, "type": "data.constant", "config": {"value": value},
            "ins": [], "outs": [{"id": "value", "t": "number"}]}


def _math(nid, op="add"):
    return {"id": nid, "type": "math.op", "config": {"op": op},
            "ins": [{"id": "a", "t": "number"}, {"id": "b", "t": "number"}],
            "outs": [{"id": "value", "t": "number"}]}


def _reduce(nid, op="sum"):
    return {"id": nid, "type": "data.reduce", "config": {"op": op},
            "ins": [{"id": "items", "t": "list"}],
            "outs": [{"id": "value", "t": "number"}]}


def _wire(fn, fp, tn, tp):
    return {"from": [fn, fp], "to": [tn, tp]}


def random_dag(seed: int):
    """A seeded random layered DAG of constants feeding math.op nodes.

    Returns (graph, sink_ids). Deterministic per seed so failures replay."""
    rng = random.Random(seed)
    nodes, wires = [], []
    n_consts = rng.randint(2, 5)
    for i in range(n_consts):
        nodes.append(_const(f"c{i}", rng.randint(-20, 20)))
    prev_layer = [f"c{i}" for i in range(n_consts)]
    n_layers = rng.randint(1, 3)
    for layer in range(n_layers):
        n_ops = rng.randint(1, 3)
        this_layer = []
        for j in range(n_ops):
            nid = f"m{layer}_{j}"
            # avoid div: rounding/NaN edge-cases are a separate suite —
            # the metamorphic relation itself must not be flaky.
            op = rng.choice(["add", "sub", "mul", "max", "min"])
            nodes.append(_math(nid, op))
            a = rng.choice(prev_layer)
            b = rng.choice(prev_layer)
            wires.append(_wire(a, "value", nid, "a"))
            wires.append(_wire(b, "value", nid, "b"))
            this_layer.append(nid)
        prev_layer = this_layer
    return {"nodes": nodes, "wires": wires}, list(prev_layer)


def cook(graph, sinks):
    r = WorkflowRunner(copy.deepcopy(graph))
    return {s: r.pull(s).get("value") for s in sinks}


# ── MR-1 + MR-2: metamorphic sweep over random DAGs ─────────────────
class TestMetamorphicSweep:
    SEEDS = range(20)

    def test_incremental_equals_scratch_across_random_graphs(self):
        """The single most valuable MR: for 20 random DAGs, edit a random
        const, incremental recook == from-scratch cook. Bit-identical."""
        for seed in self.SEEDS:
            g, sinks = random_dag(seed)
            rng = random.Random(1000 + seed)

            r = WorkflowRunner(copy.deepcopy(g))
            for s in sinks:
                r.pull(s)                      # prime the cache (worst case)

            # random edit, like a slider drag
            consts = [n["id"] for n in g["nodes"] if n["type"] == "data.constant"]
            target = rng.choice(consts)
            new_val = rng.randint(-20, 20)
            r.nodes_by_id[target]["config"]["value"] = new_val
            r.recook_from(target)
            incremental = {s: r.pull(s).get("value") for s in sinks}

            g2 = copy.deepcopy(g)
            for n in g2["nodes"]:
                if n["id"] == target:
                    n["config"]["value"] = new_val
            scratch = cook(g2, sinks)

            assert incremental == scratch, (
                f"seed {seed}: incremental {incremental} != scratch {scratch} "
                f"after editing {target}={new_val} — engine incrementality UNSOUND")

    def test_determinism_same_graph_twice(self):
        for seed in self.SEEDS:
            g, sinks = random_dag(seed)
            assert cook(g, sinks) == cook(g, sinks), f"seed {seed}: nondeterministic cook"

    def test_incremental_equals_scratch_with_reduce_sinks(self):
        """Same MR through data.reduce: random list constants → reduce sinks,
        edit the list, incremental recook == from-scratch."""
        for seed in range(10):
            rng = random.Random(2000 + seed)
            lst = [rng.randint(-30, 30) for _ in range(rng.randint(1, 6))]
            op = rng.choice(["sum", "count", "max", "min"])
            g = {"nodes": [_const("L", list(lst)), _reduce("TOT", op)],
                 "wires": [_wire("L", "value", "TOT", "items")]}
            r = WorkflowRunner(copy.deepcopy(g))
            r.pull("TOT")
            new_lst = [rng.randint(-30, 30) for _ in range(rng.randint(1, 6))]
            r.nodes_by_id["L"]["config"]["value"] = new_lst
            r.recook_from("L")
            incr = r.pull("TOT").get("value")
            g2 = copy.deepcopy(g)
            g2["nodes"][0]["config"]["value"] = list(new_lst)
            scratch = cook(g2, ["TOT"])["TOT"]
            assert incr == scratch, (
                f"seed {seed} op={op}: incremental {incr} != scratch {scratch}")


# ── MR-3/4/5: operad forcings on the production subgraph mechanism ──
def _chain_graph():
    """A=6, B=7 → SUM(add) ; TWO=2 → PROD(mul) ← SUM.  (6+7)*2 = 26."""
    nodes = [_const("A", 6), _const("B", 7), _math("SUM", "add"),
             _const("TWO", 2), _math("PROD", "mul")]
    wires = [_wire("A", "value", "SUM", "a"), _wire("B", "value", "SUM", "b"),
             _wire("SUM", "value", "PROD", "a"), _wire("TWO", "value", "PROD", "b")]
    return {"nodes": nodes, "wires": wires}


class TestOperadForcings:
    def test_functor_law_group_cooks_like_flat(self):
        """eval(group) == compose(eval(inner)) — §4's theorem, on the real
        compose_subgraph + nested-runner executor."""
        flat = cook(_chain_graph(), ["PROD"])
        grouped = compose_subgraph(_chain_graph(), ["A", "B", "SUM"])
        assert flat == cook(grouped, ["PROD"]), (
            f"functor law FAILS: flat {flat} != grouped {cook(grouped, ['PROD'])}")
        assert flat["PROD"] == 26.0

    def test_regroup_invariance(self):
        """§3 associativity forcing: grouping the same chain DIFFERENT ways
        must not change the sink value. Includes the group-swallows-the-sink
        case (no wire crosses out), which requires the composite to expose its
        inner sink as an output — the SPEC §3 'group carries its live result'
        law (was RED 2026-07-01; fixed in compose_subgraph)."""
        flat = cook(_chain_graph(), ["PROD"])
        for selection in (["A", "B", "SUM"], ["A", "B"], ["SUM", "PROD", "TWO"]):
            g = compose_subgraph(_chain_graph(), selection)
            if any(n["id"] == "PROD" for n in g["nodes"]):
                got = cook(g, ["PROD"])["PROD"]
            else:
                # sink swallowed → read the composite's exposed facade output
                comp = next(n for n in g["nodes"] if n["type"] == "subgraph.user")
                outs = comp["config"]["inner_outputs"]
                assert outs, (f"regroup {selection}: composite exposes NO "
                              f"outputs — a group with no value violates §3")
                r = WorkflowRunner(copy.deepcopy(g))
                res = r.pull(comp["id"])
                got = res.get(outs[0]["port"])
            assert got == flat["PROD"], (
                f"regroup {selection}: {got} != {flat['PROD']} — operad associativity FAILS")

    def test_compose_expand_is_identity(self):
        """§3 unit forcing: collapse then expand cooks identically to never
        having grouped."""
        g = compose_subgraph(_chain_graph(), ["A", "B", "SUM"])
        sub_id = next(n["id"] for n in g["nodes"] if n["type"] == "subgraph.user")
        restored = expand_subgraph(g, sub_id)
        assert cook(restored, ["PROD"]) == cook(_chain_graph(), ["PROD"]), (
            "compose∘expand is NOT identity — §3 unit law fails")

    def test_nested_group_of_groups(self):
        """§3 operad NESTING: group inside a group. Collapse [A,B,SUM] into a
        composite, then collapse [composite, TWO, PROD] into an outer
        composite — the doubly-nested graph must still cook to 26 through two
        levels of nested runners (operadic composition is associative across
        depth, not just breadth)."""
        flat = cook(_chain_graph(), ["PROD"])["PROD"]
        g1 = compose_subgraph(_chain_graph(), ["A", "B", "SUM"])
        inner_comp = next(n["id"] for n in g1["nodes"] if n["type"] == "subgraph.user")
        g2 = compose_subgraph(g1, [inner_comp, "TWO", "PROD"])
        outer = next(n for n in g2["nodes"] if n["type"] == "subgraph.user")
        outs = outer["config"]["inner_outputs"]
        assert outs, "outer group exposes no output — §3 violated at depth 2"
        r = WorkflowRunner(copy.deepcopy(g2))
        got = r.pull(outer["id"]).get(outs[0]["port"])
        assert got == flat, (
            f"nested group-of-groups: {got} != {flat} — operad nesting FAILS")

    def test_group_recomputes_after_inner_edit(self):
        """Editing a value FEEDING a group recomputes through it (live group)."""
        grouped = compose_subgraph(_chain_graph(), ["A", "B", "SUM"])
        r = WorkflowRunner(copy.deepcopy(grouped))
        assert r.pull("PROD")["value"] == 26.0
        # TWO: 2 -> 10 → (6+7)*10 = 130
        r.nodes_by_id["TWO"]["config"]["value"] = 10
        r.recook_from("TWO")
        assert r.pull("PROD")["value"] == 130.0, "group did not recompute live"


# ── IMP-1: impossible-state assertion ────────────────────────────────
class TestImpossibleState:
    def test_reduce_sum_equals_python_sum(self):
        """Layer-0 certainty check: reduce(sum) == sum(consumed list). A run
        violating this is rejected outright — nothing to score or judge."""
        for seed in range(10):
            rng = random.Random(seed)
            lst = [rng.randint(-50, 50) for _ in range(rng.randint(0, 8))]
            g = {"nodes": [_const("L", list(lst)), _reduce("TOT", "sum")],
                 "wires": [_wire("L", "value", "TOT", "items")]}
            got = cook(g, ["TOT"])["TOT"]
            assert got == sum(lst), (
                f"IMPOSSIBLE STATE: reduce(sum)={got} != consumed sum {sum(lst)}")
