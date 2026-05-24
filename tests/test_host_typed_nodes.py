"""AgDR-0041 Property 1 — typed host nodes (host swap).

Same wire, different host. Verify the 4 typed nodes are registered,
the host param resolves the right op-id, the 3dsmax→max alias works,
and missing host gives a clear error (not a silent crash).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows import registry as _reg  # noqa: E402
from workflows.nodes import host_typed   # noqa: E402,F401


# ── registration ───────────────────────────────────────────────────


@pytest.mark.parametrize("node_type", [
    "host.import_mesh",
    "host.read_walls",
    "host.export_viewport",
    "host.run_script",
])
def test_typed_host_node_registered(node_type):
    spec_tup = _reg.get(node_type)
    assert spec_tup is not None, f"{node_type} not registered"


def test_typed_host_node_specs_carry_host_options():
    spec, _exec = _reg.get("host.import_mesh")
    cfg = spec.config_schema or {}
    assert "host" in cfg
    opts = set(cfg["host"].get("options") or [])
    assert opts == {"revit", "rhino", "3dsmax", "blender"}


# ── op-id resolution ───────────────────────────────────────────────


@pytest.mark.parametrize("host,expected", [
    ("revit",   "revit.import_mesh"),
    ("rhino",   "rhino.import_mesh"),
    ("blender", "blender.import_mesh"),
    ("3dsmax",  "max.import_mesh"),       # alias
])
def test_resolve_op_id_per_host(host, expected):
    assert host_typed._resolve_op_id(host, "import_mesh") == expected


def test_resolve_op_id_empty_inputs():
    assert host_typed._resolve_op_id("", "import_mesh") == ""
    assert host_typed._resolve_op_id("revit", "") == ""


# ── executor behaviour ─────────────────────────────────────────────


def test_missing_host_returns_clear_error():
    """No silent crash — Composer / user gets actionable message."""
    spec, exec_fn = _reg.get("host.import_mesh")
    out = exec_fn({}, {"mesh": object()}, None)
    assert out["status"] == "error"
    assert "host" in out["error"].lower()


def test_unknown_op_id_resolution_fails_gracefully(monkeypatch):
    """If connectors.base.run_op rejects, executor surfaces it
    honestly (never fabricates a value)."""
    spec, exec_fn = _reg.get("host.import_mesh")

    class _StubResult:
        ok = False
        error = "no such op"

    def _stub_run_op(op_id, **_):
        return _StubResult()

    # Patch the import inside the executor's closure
    import sys as _sys
    cb = _sys.modules.get("connectors.base")
    if cb is None:
        import connectors.base as cb  # type: ignore  # noqa
    monkeypatch.setattr("connectors.base.run_op", _stub_run_op)

    out = exec_fn({"host": "rhino"}, {"mesh": object()}, None)
    assert out["status"] == "error"
    assert "rhino.import_mesh" in out["op_id"]


def test_host_swap_preserves_op_semantics(monkeypatch):
    """Same wire, swap host param — op-id changes but contract stays."""
    spec, exec_fn = _reg.get("host.read_walls")

    captured = {"calls": []}

    class _OK:
        ok = True
        value = [{"id": "w1"}, {"id": "w2"}]
        value_preview = "[2 walls]"

    def _stub(op_id, **kw):
        captured["calls"].append((op_id, kw))
        return _OK()

    monkeypatch.setattr("connectors.base.run_op", _stub)

    out_a = exec_fn({"host": "revit", "scope": "view"}, {}, None)
    out_b = exec_fn({"host": "rhino", "scope": "view"}, {}, None)
    assert out_a["value"] == out_b["value"]
    assert captured["calls"][0][0] == "revit.read_walls"
    assert captured["calls"][1][0] == "rhino.read_walls"
