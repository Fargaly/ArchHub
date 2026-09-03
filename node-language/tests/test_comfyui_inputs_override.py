"""D3·B (2026-05-25) — render.comfyui `inputs` override port.

Lets typed upstream nodes feed workflow params dynamically without
the Skill author having to bake them into the workflow JSON.

Shape of the override:
    {"<node_id>": {"<param>": <value>, ...}, ...}

Connector merges these on top of the workflow before queue.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from connectors.comfyui_connector import _merge_inputs_into_workflow  # noqa: E402
from workflows import registry as _reg  # noqa: E402
from workflows.nodes import render_typed  # noqa: E402,F401


# ── merge helper — covers the merge contract ──────────────────────


def _wf():
    """Tiny but realistic ComfyUI workflow shape."""
    return {
        "5": {"class_type": "LoadImage",
               "inputs": {"image": "default.png"}},
        "6": {"class_type": "CLIPTextEncode",
               "inputs": {"text": "default prompt", "clip": ["1", 0]}},
        "9": {"class_type": "SaveImage",
               "inputs": {"images": ["8", 0], "filename_prefix": "out"}},
    }


def test_merge_none_inputs_returns_workflow_unchanged():
    wf = _wf()
    out = _merge_inputs_into_workflow(wf, None)
    assert out == wf


def test_merge_empty_dict_returns_workflow_unchanged():
    wf = _wf()
    out = _merge_inputs_into_workflow(wf, {})
    assert out == wf


def test_merge_overrides_single_node_single_param():
    wf = _wf()
    out = _merge_inputs_into_workflow(
        wf, {"5": {"image": "viewport_hero.png"}})
    assert out["5"]["inputs"]["image"] == "viewport_hero.png"
    # Unrelated nodes intact.
    assert out["6"] == wf["6"]
    assert out["9"] == wf["9"]


def test_merge_overrides_multiple_nodes_multiple_params():
    wf = _wf()
    out = _merge_inputs_into_workflow(wf, {
        "5": {"image": "in.png"},
        "6": {"text": "golden hour, photoreal"},
    })
    assert out["5"]["inputs"]["image"] == "in.png"
    assert out["6"]["inputs"]["text"] == "golden hour, photoreal"
    # Other params on touched nodes intact (CLIPTextEncode.clip).
    assert out["6"]["inputs"]["clip"] == ["1", 0]


def test_merge_does_not_mutate_caller_workflow():
    wf = _wf()
    wf_snapshot = {k: {kk: dict(vv) if isinstance(vv, dict) else vv
                        for kk, vv in v.items()}
                   for k, v in wf.items()}
    _merge_inputs_into_workflow(wf, {"5": {"image": "mutated.png"}})
    # Caller's workflow unchanged — Skills cache workflow JSON.
    assert wf == wf_snapshot
    assert wf["5"]["inputs"]["image"] == "default.png"


def test_merge_unknown_node_id_silently_skipped():
    """Override for a node that isn't in the workflow is a no-op —
    we don't error, since workflows may be edited and the override
    still passes through cleanly. The Skill author owns wiring."""
    wf = _wf()
    out = _merge_inputs_into_workflow(wf, {
        "999": {"image": "ghost.png"},
        "5":   {"image": "real.png"},
    })
    assert out["5"]["inputs"]["image"] == "real.png"
    assert "999" not in out


def test_merge_non_dict_workflow_returns_unchanged():
    """Defensive: callers pass weird shapes (legacy / fallback) —
    we don't blow up."""
    assert _merge_inputs_into_workflow(None, {"5": {"image": "x"}}) is None
    assert _merge_inputs_into_workflow("not a dict",
                                         {"5": {"image": "x"}}) == "not a dict"


def test_merge_non_dict_override_value_silently_skipped():
    """An override value that isn't a dict can't be a {param: value}
    map. Skip without erroring."""
    wf = _wf()
    out = _merge_inputs_into_workflow(wf, {"5": "not a dict"})
    # `5` untouched, no crash.
    assert out["5"] == wf["5"]


# ── render.comfyui registration carries the new input port ────────


def test_render_comfyui_has_inputs_override_port():
    spec_tup = _reg.get("render.comfyui")
    assert spec_tup, "render.comfyui unregistered"
    spec = spec_tup[0]
    in_names = {p.name for p in spec.inputs}
    assert "workflow" in in_names
    assert "inputs" in in_names, (
        "render.comfyui missing the `inputs` override port (D3·B)")


def test_render_comfyui_inputs_port_is_object_and_not_required():
    """The override port is optional — a workflow with hardcoded values
    must still cook without anything wired to `inputs`."""
    spec = _reg.get("render.comfyui")[0]
    inputs_port = next(p for p in spec.inputs if p.name == "inputs")
    assert inputs_port.type.name == "OBJECT"
    assert not inputs_port.required


# ── end-to-end via the typed executor ──────────────────────────────


def test_typed_executor_passes_inputs_to_run_workflow(monkeypatch):
    """The typed-render executor merges config + inputs as kwargs to
    `comfyui.run_workflow`. Verify the `inputs` override flows through."""
    captured = {}

    class _OK:
        ok = True
        value = {"first_url": "http://x/y.png"}
        value_preview = "ok"

    def _fake_run_op(op_id, **kwargs):
        captured["op_id"] = op_id
        captured["kwargs"] = kwargs
        return _OK()

    import connectors.base as _base
    monkeypatch.setattr(_base, "run_op", _fake_run_op)

    spec, exec_fn = _reg.get("render.comfyui")
    result = exec_fn(
        {"client_id": "test", "poll_seconds": 5},
        {"workflow": _wf(),
         "inputs": {"5": {"image": "viewport_hero.png"}}},
        None,
    )
    assert result.get("op_id") == "comfyui.run_workflow"
    assert captured["op_id"] == "comfyui.run_workflow"
    assert captured["kwargs"].get("client_id") == "test"
    assert "workflow" in captured["kwargs"]
    # The `inputs` override flows through.
    assert captured["kwargs"].get("inputs") == {
        "5": {"image": "viewport_hero.png"}}
