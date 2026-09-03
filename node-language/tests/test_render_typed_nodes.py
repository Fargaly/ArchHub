"""Tier 2 typed primitives — render/vision/mesh/anim.

Verify each primitive is registered, its ports are correctly typed
(drives validator + swap-suggestions), and the executor routes to
the right connector op.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows import registry as _reg  # noqa: E402
from workflows.nodes import render_typed  # noqa: E402,F401


@pytest.mark.parametrize("node_type,expected_op", [
    ("vision.describe",      "dashscope.vision_describe"),
    ("llm.qwen",             "dashscope.complete"),
    ("render.image_edit",    "dashscope.image_edit"),
    ("anim.wan_i2v",         "dashscope.wan_i2v_async"),
    ("render.task_poll",     "dashscope.task_poll"),
    ("render.comfyui",       "comfyui.run_workflow"),
    ("mesh.from_image",      "comfyui.run_workflow"),
])
def test_primitive_registered_and_routes_to_op(node_type, expected_op,
                                                  monkeypatch):
    spec_tup = _reg.get(node_type)
    assert spec_tup is not None, f"{node_type} not registered"
    spec, exec_fn = spec_tup

    seen = {}

    class _OK:
        ok = True
        value = "test_value"
        value_preview = "preview"

    def _stub_run_op(op_id, **kw):
        seen["op_id"] = op_id
        seen["kw"] = kw
        return _OK()

    monkeypatch.setattr("connectors.base.run_op", _stub_run_op)
    out = exec_fn({"model": "x"}, {}, None)
    assert seen["op_id"] == expected_op
    assert out["value"] == "test_value"


def test_vision_describe_port_types():
    spec, _ = _reg.get("vision.describe")
    in_types = [p.type.value for p in spec.inputs]
    out_types = [p.type.value for p in spec.outputs]
    assert "string" in in_types  # image_url
    assert "string" in out_types


def test_mesh_from_image_outputs_geometry():
    """Geometry output type drives the swap-suggester so the user
    sees mesh.from_image as a candidate when they need Geometry."""
    spec, _ = _reg.get("mesh.from_image")
    out_types = [p.type.value for p in spec.outputs]
    assert "geometry" in out_types


def test_swap_suggestions_find_compatible_mesh_alternatives():
    """The Tier 2 mesh.from_image should be a valid swap target for
    any node accepting Image-in / Geometry-out signature."""
    from tool_engine import ToolEngine

    class _StubMgr:
        entries: list = []
        def active_families(self): return set()

    eng = ToolEngine(manager=_StubMgr())
    out = eng._invoke_library_handler("library_suggest_swaps",
        {"in_types": ["image"], "out_types": ["geometry"], "limit": 50})
    types = {r["type"] for r in out["results"]}
    assert "mesh.from_image" in types


def test_connector_error_surfaces_honestly(monkeypatch):
    spec, exec_fn = _reg.get("vision.describe")

    class _Fail:
        ok = False
        error = "rate limited"

    monkeypatch.setattr("connectors.base.run_op",
                         lambda *a, **kw: _Fail())
    out = exec_fn({}, {"image_url": "x"}, None)
    assert out["status"] == "error"
    assert "rate limited" in out["error"]


def test_wan_i2v_options_carry_three_models():
    spec, _ = _reg.get("anim.wan_i2v")
    model_opts = set(spec.config_schema["model"]["options"])
    assert {"wan2.5-i2v-plus", "wan2.6-i2v-plus",
            "wan2.7-i2v-plus"}.issubset(model_opts)
