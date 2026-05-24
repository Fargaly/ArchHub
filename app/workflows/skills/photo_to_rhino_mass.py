"""Built-in Skill — Photo → Rhino mass model.

Use case B from the founder's 2026-05-24 research. 6-step composite:

    input.image (drag-drop) → vision.describe (Qwen-VL anchor)
       → mesh.from_image (Hunyuan3D via ComfyUI)
       → host.import_mesh (rhino target)

Cost: ~$0.05/mass (Qwen-VL ~$0.002 + Hunyuan local $0).
Time: ~30s.
"""
from __future__ import annotations


def _build_spec() -> dict:
    return {
        "type": "skill.photo_to_rhino_mass",
        "display_name": "Photo → Rhino mass",
        "category": "skill",
        "description": (
            "Snap a precedent photo, get a clean mass block dropped into "
            "Rhino. Qwen-VL classifies the subject so Hunyuan3D produces "
            "on-target geometry; simplify trims poly count; Rhino imports "
            "as a Block. Variant: swap host param to revit/3dsmax/blender "
            "to land in a different app."
        ),
        "inputs": [
            {"name": "image_url", "port_type": "string",
              "description": "URL or path of the precedent photo."},
        ],
        "outputs": [
            {"name": "block_name", "port_type": "string",
              "description": "Name of the Block created in the host."},
        ],
        "config_schema": {
            "host": {"type": "string", "default": "rhino",
                     "options": ["rhino", "revit", "3dsmax", "blender"]},
            "mesh_model": {"type": "string", "default": "hunyuan3d-2.0",
                            "options": ["hunyuan3d-2.0", "stable_fast_3d",
                                        "triposr", "instantmesh"]},
            "poly_target": {"type": "number", "default": 8000},
        },
        "side_effects": "host_write",
        "examples": [
            {
                "input": {"image_url": "https://example.com/villa.jpg"},
                "output": {"block_name": "precedent_villa_v1"},
                "note": "happy-path: dashscope key + rhino live + ComfyUI live",
            },
            {
                "input": {"image_url": "C:/photos/mass_ref.jpg"},
                "output": {"error": "Rhino not running — open Rhino first"},
                "note": "edge case: host missing; runner stops before mesh upload",
            },
        ],
        "impl": {
            "kind": "graph",
            "graph": {
                "nodes": [
                    {"id": "vl",   "type": "vision.describe",
                      "config": {"model": "qwen-vl-plus",
                                 "prompt": "Describe the building's style, "
                                           "story count, key features, "
                                           "estimated dimensions."},
                      "x": 0, "y": 0},
                    {"id": "mesh", "type": "mesh.from_image",
                      "config": {"model": "hunyuan3d-2.0",
                                 "poly_target": 8000},
                      "x": 220, "y": 0},
                    {"id": "imp",  "type": "host.import_mesh",
                      "config": {"host": "rhino", "layer": "AI Mass · ref"},
                      "x": 440, "y": 0},
                    {"id": "out",  "type": "output.parameter",
                      "config": {"name": "block_name"},
                      "x": 660, "y": 0},
                ],
                "wires": [
                    {"id": "w_v_m", "src_node": "vl",   "src_port": "value",
                      "dst_node": "mesh", "dst_port": "prompt"},
                    {"id": "w_m_i", "src_node": "mesh", "src_port": "value",
                      "dst_node": "imp",  "dst_port": "mesh"},
                    {"id": "w_i_o", "src_node": "imp",  "src_port": "value",
                      "dst_node": "out",  "dst_port": "value"},
                ],
            },
            "inner_inputs":  [
                {"port": "image_url", "inner_node": "vl",
                  "inner_port": "image_url", "type": "string"},
            ],
            "inner_outputs": [
                {"port": "block_name", "inner_node": "out",
                  "inner_port": "value", "type": "string"},
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
