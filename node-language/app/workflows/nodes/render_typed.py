"""Tier 2 typed primitives — render / vision / mesh / anim.

Thin typed wrappers over the Tier 0 connectors (comfyui.* and
dashscope.*). Each primitive declares precise port types so:
  - The canvas swap-suggestions (AgDR-0041 P2) lists them as
    drop-in alternatives.
  - The Composer's node_search ranks them above the generic
    connector.run for matching intent.
  - Validator P5 colours wires correctly.

These are deliberately tiny — almost-pure routing — so the
substrate they sit on (the connector ops) carries the weight.
Heavier composite "Skills" (render.archviz multi-stage pipeline)
live in workflows/skills/ once the user has installed them.
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


def _connector_call(op_id: str):
    """Closure factory — each primitive's executor calls one
    connectors.base op with its merged config + inputs."""
    def _exec(config: dict, inputs: dict, _ctx) -> dict:
        cfg = config or {}
        try:
            from connectors.base import run_op
        except Exception as ex:
            return {"status": "error",
                    "error": f"connectors unavailable: {ex}"}
        params: dict[str, Any] = dict(cfg)
        if inputs:
            params.update(inputs)
        res = run_op(op_id, **params)
        if not getattr(res, "ok", False):
            return {"status": "error", "op_id": op_id,
                    "error": getattr(res, "error", "") or f"{op_id} failed"}
        return {"value": getattr(res, "value", None),
                "op_id": op_id,
                "preview": getattr(res, "value_preview", "")}
    return _exec


# ── vision.describe ────────────────────────────────────────────────

register(NodeSpec(
    type="vision.describe",
    category="vision",
    display_name="Describe image (Qwen-VL)",
    description=("Take an image URL, get back a text description "
                  "via Alibaba Qwen-VL-Plus. ~$0.002 per call — "
                  "3-5× cheaper than GPT-4o vision. Use this as the "
                  "semantic anchor before image-to-mesh / image-to-3D."),
    inputs=[
        Port(name="image_url", type=PortType.STRING, required=True),
        Port(name="prompt",    type=PortType.STRING),
    ],
    outputs=[
        Port(name="value", type=PortType.STRING),
    ],
    config_schema={
        "model":  {"type": "string", "default": "qwen-vl-plus",
                    "options": ["qwen-vl-plus", "qwen-vl-max"]},
        "prompt": {"type": "string",
                    "default": "Describe this image."},
    },
    icon="👁",
), _connector_call("dashscope.vision_describe"))


# ── llm.qwen ───────────────────────────────────────────────────────

register(NodeSpec(
    type="llm.qwen",
    category="ai",
    display_name="Qwen text (DashScope)",
    description=("Cheap text completion via Alibaba Qwen3. "
                  "qwen-turbo ~$0.01/M, qwen-plus $0.33/M, "
                  "qwen-max $0.78/M — 5-30× cheaper than Claude Sonnet "
                  "for routine code / summarise / classify turns."),
    inputs=[
        Port(name="prompt", type=PortType.STRING, required=True),
    ],
    outputs=[
        Port(name="value", type=PortType.STRING),
    ],
    config_schema={
        "model":       {"type": "string", "default": "qwen-plus",
                         "options": ["qwen-turbo", "qwen-plus",
                                     "qwen-max", "qwen3-max"]},
        "max_tokens":  {"type": "number", "default": 1024},
        "temperature": {"type": "number", "default": 0.7},
    },
    icon="💬",
), _connector_call("dashscope.complete"))


# ── render.image_edit ─────────────────────────────────────────────

register(NodeSpec(
    type="render.image_edit",
    category="render",
    display_name="Image edit (Qwen-Image)",
    description=("Image-to-image edit via Qwen-Image-Edit. Prompt + "
                  "source image → modified image. Async — returns a "
                  "task_id; poll with render.task_poll."),
    inputs=[
        Port(name="prompt",    type=PortType.STRING, required=True),
        Port(name="image_url", type=PortType.STRING, required=True),
    ],
    outputs=[
        Port(name="value", type=PortType.OBJECT),  # {task_id, raw}
    ],
    config_schema={
        "model": {"type": "string", "default": "qwen-image-edit"},
        "n":     {"type": "number", "default": 1},
    },
    icon="✦",
), _connector_call("dashscope.image_edit"))


# ── anim.wan_i2v ───────────────────────────────────────────────────

register(NodeSpec(
    type="anim.wan_i2v",
    category="anim",
    display_name="Image → Video (Wan)",
    description=("Cheapest i2v on the market. Wan 2.5 $0.035/clip · "
                  "Wan 2.6 $0.07 · Wan 2.7 $0.10. Async — returns a "
                  "task_id; poll with render.task_poll."),
    inputs=[
        Port(name="image_url", type=PortType.STRING, required=True),
        Port(name="prompt",    type=PortType.STRING),
    ],
    outputs=[
        Port(name="value", type=PortType.OBJECT),
    ],
    config_schema={
        "model":      {"type": "string", "default": "wan2.5-i2v-plus",
                        "options": ["wan2.5-i2v-plus",
                                    "wan2.6-i2v-plus",
                                    "wan2.7-i2v-plus"]},
        "duration_s": {"type": "number", "default": 5},
    },
    icon="▶",
), _connector_call("dashscope.wan_i2v_async"))


# ── render.task_poll ──────────────────────────────────────────────

register(NodeSpec(
    type="render.task_poll",
    category="render",
    display_name="Poll async task",
    description=("Poll any DashScope async task (image_edit / wan_i2v) "
                  "and return its current status + result on completion."),
    inputs=[
        Port(name="task_id", type=PortType.STRING, required=True),
    ],
    outputs=[
        Port(name="value", type=PortType.OBJECT),
    ],
    config_schema={},
    icon="◷",
), _connector_call("dashscope.task_poll"))


# ── render.comfyui ────────────────────────────────────────────────

register(NodeSpec(
    type="render.comfyui",
    category="render",
    display_name="Run ComfyUI workflow",
    description=("Queue a ComfyUI workflow JSON + poll until done. "
                  "Returns the first output image URL. The Tier 1 "
                  "library_import_comfyui_workflow tool wraps this "
                  "with typed inputs per workflow. `inputs` port "
                  "(AgDR-0041 D3·B) overrides workflow node params "
                  "at cook time — feed an image, a prompt, etc. "
                  "from upstream typed nodes."),
    inputs=[
        Port(name="workflow", type=PortType.OBJECT, required=True),
        # D3·B (2026-05-25) — override node params inside the workflow
        # at cook time. Shape: {"<node_id>": {"<param>": <value>, …}}.
        # Connector merges these on top of the workflow before queue.
        Port(name="inputs", type=PortType.OBJECT),
    ],
    outputs=[
        Port(name="value", type=PortType.OBJECT),
    ],
    config_schema={
        "client_id":    {"type": "string", "default": "archhub"},
        "poll_seconds": {"type": "number", "default": 120},
    },
    icon="◍",
), _connector_call("comfyui.run_workflow"))


# ── mesh.from_image ───────────────────────────────────────────────
# 3D mesh from a single image. Today this routes through ComfyUI
# (the Hunyuan3D-2 / StableFast3D / TripoSR nodes from the
# ComfyUI-3D-Pack are wired via a workflow JSON the user installs).
# Tier 2 stub exposes the typed contract; the executor delegates
# to comfyui.run_workflow with a per-model workflow loaded from
# config.workflow. Users install workflows once + reuse the node.

register(NodeSpec(
    type="mesh.from_image",
    category="mesh",
    display_name="Image → 3D mesh",
    description=("Single image → textured 3D mesh (.glb). Routes "
                  "through a ComfyUI workflow (Hunyuan3D-2 / "
                  "StableFast3D / TripoSR / InstantMesh per config "
                  "choice). Output suitable for host.import_mesh."),
    inputs=[
        Port(name="image", type=PortType.IMAGE, required=True),
        Port(name="prompt", type=PortType.STRING),
    ],
    outputs=[
        Port(name="value", type=PortType.GEOMETRY),
    ],
    config_schema={
        "model":     {"type": "string", "default": "hunyuan3d-2.0",
                       "options": ["hunyuan3d-2.0", "stable_fast_3d",
                                   "triposr", "instantmesh"]},
        "workflow":  {"type": "string",
                       "description": "Path to the ComfyUI workflow JSON "
                                       "wired for the chosen model."},
        "poly_target": {"type": "number", "default": 8000},
    },
    icon="⌖",
), _connector_call("comfyui.run_workflow"))
