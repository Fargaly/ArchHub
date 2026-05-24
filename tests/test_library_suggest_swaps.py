"""AgDR-0041 P2 — type-compatible swap suggestions.

Composer can list registered alternatives whose ports match a
target node's signature. Powers the right-click 'swap with…' menu.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from tool_engine import ToolEngine  # noqa: E402
from workflows import registry as _reg  # noqa: E402
from workflows.registry import NodeSpec, register  # noqa: E402
from workflows.graph import Port, PortType  # noqa: E402


class _StubMgr:
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # Register 3 mesh-gen nodes to swap between.
    for t in ("mesh.alpha", "mesh.beta", "mesh.gamma"):
        _reg._REGISTRY.pop(t, None)
        register(NodeSpec(
            type=t, category="mesh", display_name=t,
            description="Test mesh gen.",
            inputs=[Port(name="image", type=PortType.IMAGE)],
            outputs=[Port(name="value", type=PortType.GEOMETRY)],
        ), lambda c, i, x: {"value": None})
    # Register an unrelated text node to verify filtering.
    _reg._REGISTRY.pop("text.alpha", None)
    register(NodeSpec(
        type="text.alpha", category="text", display_name="Text",
        description="Test text.",
        inputs=[Port(name="prompt", type=PortType.STRING)],
        outputs=[Port(name="value", type=PortType.STRING)],
    ), lambda c, i, x: {"value": ""})
    yield ToolEngine(manager=_StubMgr())
    for t in ("mesh.alpha", "mesh.beta", "mesh.gamma", "text.alpha"):
        _reg._REGISTRY.pop(t, None)


def _call(engine, **args):
    return engine._invoke_library_handler("library_suggest_swaps", args)


def test_lift_io_from_target_type(engine):
    out = _call(engine, type="mesh.alpha", limit=10)
    assert out["status"] == "ok"
    types = {r["type"] for r in out["results"]}
    assert "mesh.beta" in types and "mesh.gamma" in types
    # excludes target itself
    assert "mesh.alpha" not in types
    # excludes text node (different I/O)
    assert "text.alpha" not in types


def test_explicit_in_out_types(engine):
    # Bigger limit so the 3 explicit mesh-gen nodes aren't crowded
    # out by ANY-port matches like control.merge.
    out = _call(engine, in_types=["image"], out_types=["geometry"], limit=50)
    types = {r["type"] for r in out["results"]}
    assert {"mesh.alpha", "mesh.beta", "mesh.gamma"}.issubset(types)
    # text.alpha has STRING in / STRING out — not compatible with
    # image/geometry signature even when ANY-fallback is lenient.
    assert "text.alpha" not in types


def test_unknown_target_errors(engine):
    out = _call(engine, type="does.not.exist")
    assert out["status"] == "error"


def test_results_sorted_by_score(engine):
    out = _call(engine, type="mesh.alpha")
    scores = [r["score"] for r in out["results"]]
    assert scores == sorted(scores, reverse=True)


def test_any_is_universal(engine):
    """A node with ANY ports should match against typed neighbours.
    Many existing nodes have ANY ports (control.merge, etc) so we
    just verify our test fixture passes — not that it's in top N."""
    _reg._REGISTRY.pop("mesh.universal", None)
    register(NodeSpec(
        type="mesh.universal", category="mesh", display_name="U",
        description="Test universal.",
        inputs=[Port(name="x", type=PortType.ANY)],
        outputs=[Port(name="y", type=PortType.ANY)],
    ), lambda c, i, x: {"y": None})
    try:
        out = _call(engine, in_types=["image"], out_types=["geometry"],
                     limit=200)
        types = {r["type"] for r in out["results"]}
        assert "mesh.universal" in types
    finally:
        _reg._REGISTRY.pop("mesh.universal", None)
