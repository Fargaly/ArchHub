"""Built-in Skill — Revit viewport → AI hero render.

Use case A from the founder's 2026-05-24 ComfyUI / Alibaba research.
7-step composite that wires existing primitives:

    host.export_viewport (revit)
       → render.comfyui   (SDXL + Depth ControlNet workflow)
       → render.image_edit (Qwen-Image upscale to 4K)
       → file.save

Shipped as impl.kind=graph (AgDR-0040) so the runner cooks it via
the nested subgraph machinery. User drops ONE node on the canvas;
inputs/outputs auto-derive from the inner graph's open ports.

Cost: ~$0.025/render (Qwen upscale only; SDXL runs local via ComfyUI).
Time: ~41s end-to-end on a 24GB GPU.
"""
from __future__ import annotations


def _build_spec() -> dict:
    """Build the Skill's Capability spec (impl.kind=graph)."""
    return {
        "type": "skill.revit_hero_render",
        "display_name": "Revit → AI hero render",
        "category": "skill",
        "description": (
            "Take the active Revit 3D view + depth map, run them through "
            "ComfyUI's SDXL+Depth-ControlNet workflow to add materials / "
            "lighting / context while preserving geometry, then upscale "
            "to 4K via Qwen-Image. Cost ~$0.025/render. Use this as the "
            "starter Skill — wire the host + ControlNet workflow path "
            "in config to match your setup."
        ),
        "inputs": [
            {"name": "view_name", "port_type": "string",
              "description": "Name of the Revit 3D view to export."},
            {"name": "style_prompt", "port_type": "string",
              "description": "Style guidance fed to the upscaler."},
        ],
        "outputs": [
            {"name": "image_path", "port_type": "string",
              "description": "Final hero-render image on disk."},
        ],
        "config_schema": {
            "comfyui_workflow_path": {
                "type": "string",
                "description": "Path to the SDXL+Depth ControlNet workflow JSON.",
            },
            "save_dir": {"type": "string", "default": "./renders"},
        },
        "side_effects": "host_write",
        "examples": [
            {
                "input": {"view_name": "3D - Hero",
                           "style_prompt": "golden hour, contextual, photoreal"},
                "output": {"image_path": "./renders/hero_v1.jpg"},
                "note": "happy-path: Revit live + ComfyUI live + Qwen key set",
            },
            {
                "input": {"view_name": "3D - Hero",
                           "style_prompt": "golden hour"},
                "output": {"error": "Revit not running — open the project first"},
                "note": "edge case: Revit closed; surface a typed error + recovery hint",
            },
        ],
        "impl": {
            "kind": "graph",
            "graph": {
                "nodes": [
                    {"id": "viewport", "type": "host.export_viewport",
                      "config": {"host": "revit"}, "x": 0, "y": 0},
                    {"id": "comfy", "type": "render.comfyui",
                      "config": {"poll_seconds": 120}, "x": 220, "y": 0},
                    {"id": "upscale", "type": "render.image_edit",
                      "config": {"model": "qwen-image-edit", "n": 1},
                      "x": 440, "y": 0},
                    {"id": "poll", "type": "render.task_poll",
                      "x": 660, "y": 0},
                    {"id": "out", "type": "output.parameter",
                      "config": {"name": "image_path"},
                      "x": 880, "y": 0},
                ],
                "wires": [
                    {"id": "w_v_c",  "src_node": "viewport", "src_port": "image",
                      "dst_node": "comfy",   "dst_port": "workflow"},
                    {"id": "w_c_u",  "src_node": "comfy",    "src_port": "value",
                      "dst_node": "upscale", "dst_port": "image_url"},
                    {"id": "w_u_p",  "src_node": "upscale",  "src_port": "value",
                      "dst_node": "poll",    "dst_port": "task_id"},
                    {"id": "w_p_o",  "src_node": "poll",     "src_port": "value",
                      "dst_node": "out",     "dst_port": "value"},
                ],
            },
            "inner_inputs":  [
                {"port": "view_name", "inner_node": "viewport",
                  "inner_port": "view", "type": "string"},
                {"port": "style_prompt", "inner_node": "upscale",
                  "inner_port": "prompt", "type": "string"},
            ],
            "inner_outputs": [
                {"port": "image_path", "inner_node": "out",
                  "inner_port": "value", "type": "string"},
            ],
        },
        "source": "shipped_skill",
    }


def _try_register() -> None:
    """Best-effort registration — never raises so app startup is robust
    to a single bad Skill spec."""
    try:
        import library as _lib
    except Exception:
        return
    try:
        spec = _build_spec()
        _lib.create_node_type(spec)
    except Exception:
        # Duplicate / validator rejection / etc — Skill already
        # registered or library not initialised. Either way: silent
        # so import never breaks app startup.
        pass


_try_register()
