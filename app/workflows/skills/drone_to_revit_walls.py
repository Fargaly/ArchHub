"""Built-in Skill — Drone photos → Revit walls.

Use case D (refined per founder 2026-05-24 — Revit only, skip topo).
5-step composite. Photogrammetry from a folder of drone shots, VL
classifies the facade, Revit gets walls + openings.

Cost: ~$0.08 (VL only — 3DGS local).
Time: ~12 min (3DGS dominates).
"""
from __future__ import annotations


def _build_spec() -> dict:
    return {
        "type": "skill.drone_to_revit_walls",
        "display_name": "Drone photos → Revit walls",
        "category": "skill",
        "description": (
            "Process a folder of drone images into 3DGS, reconstruct a "
            "watertight mesh, ask Qwen-VL to label facade regions "
            "(walls / windows / doors / roof), then drop typed Revit "
            "walls + opening families into the active document. Saves "
            "the 3-week family modelling pass for existing-conditions "
            "captures."
        ),
        "inputs": [
            {"name": "image_set_path", "port_type": "string",
              "description": "Folder of drone source images."},
        ],
        "outputs": [
            {"name": "wall_count", "port_type": "number",
              "description": "Number of Revit walls created."},
        ],
        "config_schema": {
            "wall_type":  {"type": "string", "default": "Generic 200mm"},
            "level":      {"type": "string", "default": "Level 0"},
            "iterations": {"type": "number", "default": 7000},
        },
        "side_effects": "host_write",
        "examples": [
            {
                "input": {"image_set_path": "C:/scan/drone/"},
                "output": {"wall_count": 4},
                "note": "happy-path: ComfyUI 3D-Pack live + Revit live + dashscope",
            },
            {
                "input": {"image_set_path": "C:/scan/drone-empty/"},
                "output": {"error": "0 images found; need ≥20 for 3DGS"},
                "note": "edge case: empty folder; runner aborts before paid call",
            },
        ],
        "impl": {
            "kind": "graph",
            "graph": {
                "nodes": [
                    {"id": "splat", "type": "render.comfyui",
                      "config": {"poll_seconds": 900},  # 15 min for 3DGS
                      "x": 0, "y": 0},
                    {"id": "vl",    "type": "vision.describe",
                      "config": {"prompt": "Label facade regions: walls, "
                                            "windows, doors, roof. Estimate "
                                            "wall heights + opening dims."},
                      "x": 220, "y": 0},
                    {"id": "create_walls", "type": "host.run_script",
                      "config": {"host": "revit"},
                      "x": 440, "y": 0},
                    {"id": "out", "type": "output.parameter",
                      "config": {"name": "wall_count"},
                      "x": 660, "y": 0},
                ],
                "wires": [
                    {"id": "w_s_v", "src_node": "splat", "src_port": "value",
                      "dst_node": "vl",    "dst_port": "image_url"},
                    {"id": "w_v_c", "src_node": "vl",    "src_port": "value",
                      "dst_node": "create_walls", "dst_port": "code"},
                    {"id": "w_c_o", "src_node": "create_walls", "src_port": "value",
                      "dst_node": "out", "dst_port": "value"},
                ],
            },
            "inner_inputs":  [
                {"port": "image_set_path", "inner_node": "splat",
                  "inner_port": "workflow", "type": "string"},
            ],
            "inner_outputs": [
                {"port": "wall_count", "inner_node": "out",
                  "inner_port": "value", "type": "number"},
            ],
        },
        "source": "shipped_skill",
    }


def _try_register() -> None:
    try:
        import library as _lib
        _lib.create_node_type(_build_spec())
    except Exception:
        pass


_try_register()
