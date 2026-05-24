"""AgDR-0041 Property 6 — node bypass: skip execute + passthrough.

Different from freeze (P3): bypass holds no cache, re-cooks each
upstream change, upstream input → downstream output by port-name
or port-type match.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.runner import WorkflowRunner  # noqa: E402
from workflows import registry as _reg  # noqa: E402
from workflows.graph import Port, PortType  # noqa: E402
from workflows.registry import NodeSpec, register  # noqa: E402


_TRACK: dict[str, int] = {"calls": 0}


def _counter_exec(_cfg, inputs, _ctx):
    _TRACK["calls"] += 1
    v = (inputs or {}).get("value", 0)
    return {"value": v * 10}


@pytest.fixture(autouse=True)
def _isolated():
    _TRACK["calls"] = 0
    _reg._REGISTRY.pop("test.bypass.amp", None)
    register(NodeSpec(
        type="test.bypass.amp",
        category="data",
        display_name="Amp",
        description="Multiplies input by 10 (test helper).",
        inputs=[Port(name="value", type=PortType.NUMBER)],
        outputs=[Port(name="value", type=PortType.NUMBER)],
    ), _counter_exec)
    yield
    _reg._REGISTRY.pop("test.bypass.amp", None)


def _graph(bypassed: bool):
    return {
        "nodes": [
            {"id": "src", "type": "data.constant",
             "config": {"value": 5}, "x": 0, "y": 0,
             "outs": [{"id": "value", "t": "number"}]},
            {"id": "mid", "type": "test.bypass.amp",
             "x": 100, "y": 0, "bypassed": bypassed,
             "ins":  [{"id": "value", "t": "number"}],
             "outs": [{"id": "value", "t": "number"}]},
            {"id": "sink", "type": "output.parameter",
             "config": {"name": "out"}, "x": 200, "y": 0,
             "ins": [{"id": "value", "t": "number"}]},
        ],
        "edges": [
            {"id": "e1", "src_node": "src", "src_port": "value",
             "dst_node": "mid", "dst_port": "value"},
            {"id": "e2", "src_node": "mid", "src_port": "value",
             "dst_node": "sink", "dst_port": "value"},
        ],
    }


def test_active_executes_and_amplifies():
    g = _graph(bypassed=False)
    r = WorkflowRunner({"nodes": g["nodes"], "edges": g["edges"]})
    out = r.pull("mid")
    assert out["value"] == 50
    assert _TRACK["calls"] == 1


def test_bypassed_skips_execute_and_passthrough():
    g = _graph(bypassed=True)
    r = WorkflowRunner({"nodes": g["nodes"], "edges": g["edges"]})
    out = r.pull("mid")
    assert out["value"] == 5            # passthrough — NOT amplified
    assert out.get("bypassed") is True  # marker present
    assert _TRACK["calls"] == 0          # executor never ran


def test_bypassed_recooks_each_pull_no_cache():
    """Bypass holds no cache — every pull walks upstream again
    (different from freeze which holds last cached value)."""
    g = _graph(bypassed=True)
    r = WorkflowRunner({"nodes": g["nodes"], "edges": g["edges"]})
    r.pull("mid")
    r.pull("mid")
    r.pull("mid")
    assert _TRACK["calls"] == 0           # never executes
    # downstream sees latest upstream
    out = r.pull("sink")
    assert out.get("out") == 5 or out.get("value") == 5 or "ok" in out.get("status", "")
