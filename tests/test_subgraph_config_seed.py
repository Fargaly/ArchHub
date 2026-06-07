"""Config-sourced inner seeds in the subgraph executor (Part A of the
normalization-infra wave).

WHY this exists
---------------
The messy composites the stem-cell rebuild still has to absorb (``aec.*``,
``adapter.*``, ``control.switch``) all share a config-fallback idiom in their
bespoke Python bodies:

    value = inputs.get("x") or config.get("x")

A rebuilt ``impl.kind=graph`` node cannot reproduce that byte-identically,
because the subgraph executor (``app/workflows/subgraph.py`` ``_subgraph_executor``)
only ever threads the FACADE node's *inputs* into the inner graph — never the
node's *config*. So the inner ``code.expression`` coalesce cell can see ``x``
(the wired input) but has no way to see ``config.get("x")``.

THE EXTENSION (gap A closed)
----------------------------
An ``inner_inputs`` entry MAY now carry ``"source": "config"`` +
``"config_key": k``. That inner port is then seeded from ``config.get(k)`` (the
facade node's own config) instead of from ``inputs.get(port_id)``. An entry with
``source`` absent or any other value keeps the historical input-seed behaviour,
unchanged — so control.if / control.merge (which rely on the current behaviour)
cook byte-identically. This is the ONE-SYSTEM extension: the SAME ``subgraph._seed``
mechanism, just sourcing the value from config for flagged entries.

These tests build a tiny real ``subgraph.user`` facade whose inner graph is a
real ``code.expression`` coalesce cell, set the facade node's config, cook the
whole thing through the REAL ``WorkflowRunner``, and assert the inner cell
observed the config value — and, separately, that an input-sourced seed still
works unchanged and that the two compose into a real ``a or b`` fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

# Importing these registers code.expression + subgraph.user + subgraph._seed.
from workflows import nodes as _nodes_pkg  # noqa: F401
from workflows import subgraph  # noqa: F401  triggers register_subgraph_executor
from workflows.runner import WorkflowRunner


# ── helpers ──────────────────────────────────────────────────────────────────
def _facade_node(node_id: str, inner_inputs, inner_outputs, inner_graph,
                 config_extra=None):
    """Build a real `subgraph.user` facade node. `config_extra` merges
    additional keys into the node's config — these are exactly the keys a
    config-sourced seed reads via `source: "config"` / `config_key`."""
    cfg = {
        "inner_graph":   inner_graph,
        "inner_inputs":  inner_inputs,
        "inner_outputs": inner_outputs,
        "title":         "test-facade",
    }
    if config_extra:
        cfg.update(config_extra)
    # Declare the facade's outer ports in canvas shape so the runner can
    # see them (the executor reads inner_inputs/outputs off config, but the
    # node still carries ins/outs for completeness).
    outs = [{"id": fp["port"], "label": fp["port"], "t": fp.get("type", "any")}
            for fp in inner_outputs]
    ins = [{"id": fp["port"], "label": fp["port"], "t": fp.get("type", "any")}
           for fp in inner_inputs if fp.get("source") != "config"]
    return {
        "id": node_id,
        "type": "subgraph.user",
        "config": cfg,
        "ins": ins,
        "outs": outs,
    }


def _coalesce_inner_graph():
    """A single real `code.expression` cell computing `a or b` on inner ports
    `a` and `b` — the exact coalesce shape a config-fallback rebuild uses to
    reproduce `inputs.get(x) or config.get(x)`."""
    return {
        "nodes": [
            {"id": "coalesce", "type": "code.expression",
             "config": {"expr": "a or b"},
             "ins":  [{"id": "a", "t": "any"}, {"id": "b", "t": "any"}],
             "outs": [{"id": "value", "t": "any"}]},
        ],
        "wires": [],
    }


# ── 1. config-sourced seed: the inner cell sees the facade config ────────────
def test_config_sourced_seed_threads_facade_config_into_inner_cell():
    """An `inner_inputs` entry with `source: "config"` seeds its inner port
    from `config.get(config_key)` — NOT from the outer inputs. With no wired
    input at all, the inner coalesce cell still observes the config value."""
    inner = _coalesce_inner_graph()
    inner_inputs = [
        # `a` is wired from the outer input (none supplied here → None).
        {"port": "x", "inner_node": "coalesce", "inner_port": "a"},
        # `b` is sourced from the facade node's config["fallback_x"].
        {"port": "x_cfg", "inner_node": "coalesce", "inner_port": "b",
         "source": "config", "config_key": "fallback_x"},
    ]
    inner_outputs = [
        {"port": "out", "inner_node": "coalesce", "inner_port": "value"},
    ]
    node = _facade_node(
        "facade", inner_inputs, inner_outputs, inner,
        config_extra={"fallback_x": "from-config"},
    )
    runner = WorkflowRunner({"nodes": [node], "wires": []})
    out = runner.pull("facade")

    assert out.get("status") == "ok", out
    # `a` was None (no wire), so `a or b` coalesced to the config value.
    assert out.get("out") == "from-config"


def test_config_seed_missing_key_seeds_none_total_tolerant():
    """A config-sourced seed whose `config_key` is absent from config seeds
    None — never raises. Here the input-seed wins the coalesce."""
    inner = _coalesce_inner_graph()
    inner_inputs = [
        {"port": "x", "inner_node": "coalesce", "inner_port": "a"},
        {"port": "x_cfg", "inner_node": "coalesce", "inner_port": "b",
         "source": "config", "config_key": "does_not_exist"},
    ]
    inner_outputs = [
        {"port": "out", "inner_node": "coalesce", "inner_port": "value"},
    ]
    node = _facade_node("facade", inner_inputs, inner_outputs, inner)
    # Feed the wired input so `a` is truthy.
    src = {"id": "src", "type": "code.expression",
           "config": {"expr": "'from-input'"},
           "outs": [{"id": "value", "t": "any"}]}
    graph = {
        "nodes": [src, node],
        "wires": [{"from": ["src", "value"], "to": ["facade", "x"]}],
    }
    out = WorkflowRunner(graph).pull("facade")
    assert out.get("status") == "ok", out
    # config_key missing → b is None → `a or b` == 'from-input'.
    assert out.get("out") == "from-input"


# ── 2. input-sourced seed still works unchanged (regression of behaviour) ────
def test_input_sourced_seed_unchanged():
    """An entry with NO `source` (the historical default) seeds from the outer
    inputs exactly as before — proving the change is backward-compatible."""
    inner = _coalesce_inner_graph()
    inner_inputs = [
        {"port": "x", "inner_node": "coalesce", "inner_port": "a"},
        {"port": "y", "inner_node": "coalesce", "inner_port": "b"},
    ]
    inner_outputs = [
        {"port": "out", "inner_node": "coalesce", "inner_port": "value"},
    ]
    node = _facade_node("facade", inner_inputs, inner_outputs, inner)
    # Wire a real upstream producing 'from-input' into facade.x.
    src = {"id": "src", "type": "code.expression",
           "config": {"expr": "'from-input'"},
           "outs": [{"id": "value", "t": "any"}]}
    graph = {
        "nodes": [src, node],
        "wires": [{"from": ["src", "value"], "to": ["facade", "x"]}],
    }
    out = WorkflowRunner(graph).pull("facade")
    assert out.get("status") == "ok", out
    assert out.get("out") == "from-input"


# ── 3. the full config-fallback idiom: input wins, else config ───────────────
def test_input_overrides_config_then_config_fallback():
    """The reproduced `inputs.get(x) or config.get(x)` truth table:
    when the input is truthy it WINS; when it is falsy the config fills in.
    Both readings flow through the SAME facade — only the wired value differs."""
    inner = _coalesce_inner_graph()
    inner_inputs = [
        {"port": "x", "inner_node": "coalesce", "inner_port": "a"},
        {"port": "x_cfg", "inner_node": "coalesce", "inner_port": "b",
         "source": "config", "config_key": "fallback_x"},
    ]
    inner_outputs = [
        {"port": "out", "inner_node": "coalesce", "inner_port": "value"},
    ]

    # (a) input present + truthy → input wins over config.
    node = _facade_node("facade", inner_inputs, inner_outputs, inner,
                        config_extra={"fallback_x": "cfg-val"})
    src = {"id": "src", "type": "code.expression",
           "config": {"expr": "'live-input'"},
           "outs": [{"id": "value", "t": "any"}]}
    graph = {
        "nodes": [src, node],
        "wires": [{"from": ["src", "value"], "to": ["facade", "x"]}],
    }
    out = WorkflowRunner(graph).pull("facade")
    assert out.get("status") == "ok", out
    assert out.get("out") == "live-input"

    # (b) input falsy (no wire) → config fills in.
    node2 = _facade_node("facade2", inner_inputs, inner_outputs, inner,
                         config_extra={"fallback_x": "cfg-val"})
    out2 = WorkflowRunner({"nodes": [node2], "wires": []}).pull("facade2")
    assert out2.get("status") == "ok", out2
    assert out2.get("out") == "cfg-val"
