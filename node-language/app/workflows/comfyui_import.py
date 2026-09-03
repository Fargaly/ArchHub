"""ComfyUI workflow → ArchHub Capability spec (Tier 1).

Take a ComfyUI workflow JSON (the standard API export shape) and
auto-derive an ArchHub Capability-Node spec. Open input ports
(unconnected node inputs) become the Capability's inputs; the
SaveImage / PreviewImage / output sink nodes become its outputs.

The result is a spec that can be passed to `library.create_node_type`
or `node_create`. The minted Capability node uses the `connector`
impl kind under the hood — its executor calls
`connectors.base.run_op('comfyui.run_workflow', workflow=<json>, ...)`
with the user's input values bound to the right open ports.

This is the wedge that makes 2000+ community ComfyUI workflows
available to the Composer as one-click Skills — paste a JSON URL,
get a typed Capability Node.
"""
from __future__ import annotations

import json
import re
from typing import Any


# Heuristic: which ComfyUI node class_types are "open input" ports
# (user-facing seed values) vs. internal wiring.
_INPUT_NODE_TYPES = {
    "CLIPTextEncode",     # text prompt
    "PrimitiveString",
    "PrimitiveText",
    "PrimitiveInteger",
    "PrimitiveFloat",
    "PrimitiveBoolean",
    "LoadImage",          # source image
    "LoadImageMask",
    "ImagePath",
    "Image",
    "VHS_LoadVideo",
    "ImpactStringSelector",
}

# Output sink node types — these decide the Capability's outputs.
_OUTPUT_NODE_TYPES = {
    "SaveImage", "SaveImageWebsocket", "PreviewImage",
    "SaveAnimatedWEBP", "SaveAnimatedPNG",
    "VHS_VideoCombine", "SaveVideo",
    "PreviewAudio", "SaveAudio",
}


def _slugify(name: str) -> str:
    """Lowercase + replace non-alnum with underscores."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "unnamed"


def _output_port_type(class_type: str) -> str:
    """Map a ComfyUI output node class to an ArchHub PortType value."""
    if not class_type:
        return "any"
    ct = class_type.lower()
    if "image" in ct or "preview" in ct:
        return "image"
    if "video" in ct or "animated" in ct:
        return "any"
    if "audio" in ct:
        return "any"
    return "any"


def _input_port_type(class_type: str) -> str:
    """Map a ComfyUI input node class to an ArchHub PortType value."""
    if not class_type:
        return "any"
    ct = class_type.lower()
    if "text" in ct or "prompt" in ct or "string" in ct:
        return "string"
    if "integer" in ct:
        return "number"
    if "float" in ct:
        return "number"
    if "boolean" in ct:
        return "boolean"
    if "image" in ct:
        return "image"
    if "video" in ct:
        return "any"
    return "any"


def analyze_workflow(workflow: Any) -> dict:
    """Return a structured summary of a ComfyUI workflow's I/O.

    Output shape:
      {
        "node_count": int,
        "inputs":  [{"node_id", "class_type", "label", "port_type"}],
        "outputs": [{"node_id", "class_type", "label", "port_type"}],
        "models":  [str]  # checkpoints/loras/controlnets referenced
      }
    """
    if isinstance(workflow, str):
        workflow = json.loads(workflow)
    if not isinstance(workflow, dict):
        raise ValueError("workflow must be a JSON object or string")

    # ComfyUI API format: {"<node_id>": {"class_type": ..., "inputs": {...}}}
    inputs: list[dict] = []
    outputs: list[dict] = []
    models: list[str] = []

    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type") or ""
        params = node.get("inputs") or {}
        meta = node.get("_meta") or {}
        label = meta.get("title") or ct or nid

        if ct in _INPUT_NODE_TYPES:
            inputs.append({
                "node_id":  nid,
                "class_type": ct,
                "label":    label,
                "port_type": _input_port_type(ct),
            })
        if ct in _OUTPUT_NODE_TYPES:
            outputs.append({
                "node_id":  nid,
                "class_type": ct,
                "label":    label,
                "port_type": _output_port_type(ct),
            })
        # Model references
        for k in ("ckpt_name", "lora_name", "control_net_name"):
            v = params.get(k)
            if isinstance(v, str) and v:
                models.append(v)

    return {
        "node_count": len(workflow),
        "inputs":  inputs,
        "outputs": outputs,
        "models":  sorted(set(models)),
    }


def to_capability_spec(*, workflow: Any, type_name: str,
                        display_name: str = "",
                        description: str = "",
                        category: str = "render") -> dict:
    """Convert a ComfyUI workflow JSON into an ArchHub Capability spec.

    The spec uses `impl.kind=connector` calling comfyui.run_workflow.
    Open input ports of the workflow become the Capability's inputs;
    SaveImage / output sink nodes become its outputs.

    Returns a dict ready for `library.create_node_type` or
    `node_create`."""
    if not type_name:
        raise ValueError("type_name required")

    summary = analyze_workflow(workflow)
    workflow_json = (workflow if isinstance(workflow, str)
                     else json.dumps(workflow))

    in_ports: list[dict] = []
    for inp in summary["inputs"]:
        in_ports.append({
            "name": _slugify(inp["label"]) + "_" + inp["node_id"],
            "type": inp["port_type"],
            "required": False,
        })

    out_ports: list[dict] = []
    for outp in summary["outputs"]:
        out_ports.append({
            "name": _slugify(outp["label"]) + "_" + outp["node_id"],
            "type": outp["port_type"],
        })
    if not out_ports:
        out_ports = [{"name": "value", "type": "any"}]

    blurb = description or (
        f"ComfyUI workflow with {summary['node_count']} nodes, "
        f"{len(summary['inputs'])} open input(s), "
        f"{len(summary['outputs'])} output sink(s). Auto-imported "
        f"by ArchHub (Tier 1, 2026-05-24)."
    )
    if summary["models"]:
        blurb += " Models: " + ", ".join(summary["models"][:4])
        if len(summary["models"]) > 4:
            blurb += f" (+{len(summary['models']) - 4} more)"

    spec = {
        "type":         type_name,
        "display_name": display_name or type_name,
        "description":  blurb,
        "category":     category,
        "inputs":       in_ports,
        "outputs":      out_ports,
        "config_schema": {
            "poll_seconds": {"type": "number", "default": 120},
        },
        "impl": {
            "kind": "connector",
            "op_id":   "comfyui.run_workflow",
            "params":  {"workflow": workflow_json},
        },
        # Source tag — tells the library where this came from.
        "source": "comfyui_import",
        "examples": [{
            "input": {p["name"]: None for p in in_ports},
            "output": {p["name"]: None for p in out_ports},
            "note": "auto-generated; replace with a real run",
        }],
    }
    return spec
