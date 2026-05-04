"""Tool nodes — auto-generated from the existing ToolEngine catalogue.

For every entry in `tool_engine.TOOLS`, we create a node type
`tool.<tool_name>` whose inputs come from the tool's input_schema and whose
outputs are the standard tool result shape.

This means the same revit_execute_csharp / acad_execute_csharp /
speckle_list_projects tools the chat already uses are also available as
graph nodes, with no duplication.
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


def _make_executor(tool_name: str):
    def execute(config: dict, inputs: dict, ctx) -> dict:
        # Combine config defaults and live inputs (inputs win)
        args = dict(config.get("args") or {})
        for k, v in inputs.items():
            if v is not None:
                args[k] = v
        result = ctx.tool_engine.invoke(tool_name, args)
        return {
            "result": result,
            "ok": (result or {}).get("status") != "error",
        }
    return execute


def _ports_from_schema(schema: dict) -> list[Port]:
    """Translate JSON schema 'properties' to Port objects."""
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    type_map = {
        "string":  PortType.STRING,
        "integer": PortType.NUMBER,
        "number":  PortType.NUMBER,
        "boolean": PortType.BOOLEAN,
        "object":  PortType.OBJECT,
        "array":   PortType.LIST,
    }
    out: list[Port] = []
    for name, p in props.items():
        ptype = type_map.get((p or {}).get("type", ""), PortType.ANY)
        out.append(Port(
            name=name,
            type=ptype,
            description=(p or {}).get("description", ""),
            required=name in required,
            default=(p or {}).get("default"),
        ))
    return out


def register_tool_nodes() -> int:
    """Register one node type per tool in tool_engine.TOOLS. Idempotent."""
    from tool_engine import TOOLS  # local import to avoid circular deps

    count = 0
    for t in TOOLS:
        node_type = f"tool.{t['name']}"
        # Skip if already registered (e.g. when test harness calls twice)
        from ..registry import get as _get
        if _get(node_type) is not None:
            continue

        category = "tool" if t["family"] != "speckle" else "speckle"
        spec = NodeSpec(
            type=node_type,
            category=category,
            display_name=t["name"],
            description=t["description"],
            inputs=_ports_from_schema(t.get("input_schema") or {}),
            outputs=[
                Port(name="result", type=PortType.TOOL_RESULT,
                     description="Raw tool result dict (status, error, data)"),
                Port(name="ok",     type=PortType.BOOLEAN,
                     description="True if the tool returned without error"),
            ],
            config_schema={"args": {"type": "object",
                                    "description": "Default arguments (inputs override)"}},
            icon=t["family"][:1].upper() if t["family"] != "_local" else "·",
        )
        register(spec, _make_executor(t["name"]))
        count += 1
    return count
