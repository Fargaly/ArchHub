"""Tier 1 — ComfyUI workflow → ArchHub Capability spec import.

Verifies the analyzer extracts inputs/outputs correctly + the
to_capability_spec returns a registrable spec.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.comfyui_import import (  # noqa: E402
    analyze_workflow, to_capability_spec,
)


# Minimal SDXL text-to-image workflow shape (trimmed for tests).
_WORKFLOW = {
    "1": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
    "2": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "an architectural render"},
          "_meta": {"title": "Positive prompt"}},
    "3": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "blurry"},
          "_meta": {"title": "Negative prompt"}},
    "4": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 1024, "height": 1024}},
    "5": {"class_type": "KSampler",
          "inputs": {"seed": 42}},
    "6": {"class_type": "VAEDecode",
          "inputs": {}},
    "7": {"class_type": "SaveImage",
          "inputs": {"filename_prefix": "out"},
          "_meta": {"title": "Hero render"}},
}


# ── analyze ────────────────────────────────────────────────────────


def test_analyze_extracts_inputs():
    s = analyze_workflow(_WORKFLOW)
    in_node_ids = {i["node_id"] for i in s["inputs"]}
    # Both CLIPTextEncode nodes are input candidates
    assert "2" in in_node_ids and "3" in in_node_ids


def test_analyze_extracts_outputs():
    s = analyze_workflow(_WORKFLOW)
    out_node_ids = {o["node_id"] for o in s["outputs"]}
    assert "7" in out_node_ids
    assert s["outputs"][0]["port_type"] == "image"


def test_analyze_extracts_model_refs():
    s = analyze_workflow(_WORKFLOW)
    assert "sd_xl_base_1.0.safetensors" in s["models"]


def test_analyze_rejects_non_dict():
    with pytest.raises(ValueError):
        analyze_workflow(42)


def test_analyze_accepts_json_string():
    import json as _json
    s = analyze_workflow(_json.dumps(_WORKFLOW))
    assert s["node_count"] == 7


# ── to_capability_spec ─────────────────────────────────────────────


def test_to_capability_spec_basic_shape():
    spec = to_capability_spec(workflow=_WORKFLOW,
                                type_name="comfy.test_render")
    assert spec["type"] == "comfy.test_render"
    assert spec["impl"]["kind"] == "connector"
    assert spec["impl"]["op_id"] == "comfyui.run_workflow"
    # Inputs from the 2 CLIPTextEncode nodes
    in_names = [p["name"] for p in spec["inputs"]]
    assert any("positive" in n for n in in_names)
    assert any("negative" in n for n in in_names)
    # Output from SaveImage
    out_names = [p["name"] for p in spec["outputs"]]
    assert any("hero_render" in n for n in out_names)


def test_to_capability_spec_requires_type_name():
    with pytest.raises(ValueError):
        to_capability_spec(workflow=_WORKFLOW, type_name="")


def test_to_capability_spec_carries_workflow_json():
    spec = to_capability_spec(workflow=_WORKFLOW,
                                type_name="comfy.test_render")
    assert "workflow" in spec["impl"]["params"]
    # workflow stored as string
    assert isinstance(spec["impl"]["params"]["workflow"], str)


def test_to_capability_spec_default_output_when_no_sink():
    minimal = {"1": {"class_type": "Foo", "inputs": {}}}
    spec = to_capability_spec(workflow=minimal,
                                type_name="comfy.no_sink")
    assert len(spec["outputs"]) == 1
    assert spec["outputs"][0]["name"] == "value"
