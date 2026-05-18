"""ArchHub MCP server — exposes every connector operation as an MCP tool.

Founder demand 2026-05-16: route ArchHub's LLM calls through the local
`claude` CLI (the Claude subscription — no metered API credit). But the
local Claude must still be able to ACT on the user's hosts (Revit,
AutoCAD, Excel, Outlook…). It can't see ArchHub's in-process connector
registry — so we bridge it the standard way: a stdio MCP server.

`claude -p --mcp-config <cfg>` launches this script. It speaks MCP over
stdin/stdout, advertises all ~117 connector ops via `tools/list`, and
routes every `tools/call` to `connectors.base.run_op`. The local Claude
now has the full host tool surface AND runs free on the subscription.

Run standalone for a smoke test:
    python app/archhub_mcp_server.py            (waits on stdio)
    python app/archhub_mcp_server.py --selftest (lists ops, exits)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# ── Import hygiene ───────────────────────────────────────────────────
# This script lives in app/, and app/ contains a LOCAL package named
# `mcp` (app/mcp/ — ArchHub's node-MCP helpers). Python auto-puts a
# script's own directory on sys.path[0], so a naive `import mcp` would
# resolve to app/mcp/ and shadow the real MCP SDK — `ModuleNotFoundError:
# No module named 'mcp.server'`. Fix: drop app/ from sys.path, import the
# real MCP SDK (which then caches in sys.modules), THEN append app/ back
# so `connectors` still imports.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or ".") != _APP_DIR]
from mcp.server import Server                 # noqa: E402
from mcp.server.stdio import stdio_server     # noqa: E402
import mcp.types as mcp_types                 # noqa: E402
sys.path.append(_APP_DIR)


# ── connector op → MCP tool translation ─────────────────────────────

# JSON-Schema type for each ArchHub ParamSpec.type.
_TYPE_MAP = {
    "text": "string", "number": "number", "bool": "boolean",
    "choice": "string", "multi": "array", "list": "array",
    "range": "number", "file": "string",
}


def _safe_name(op_id: str) -> str:
    """MCP tool name from an op_id. `excel.read_range` → `excel__read_range`
    (dots aren't valid in MCP tool names). Reversed via a lookup map, not
    string surgery, so an op_id is never mis-parsed."""
    return op_id.replace(".", "__")


def _input_schema(inputs: list) -> dict:
    """Build a JSON-Schema object from an op's ParamSpec list."""
    props: dict = {}
    required: list = []
    for p in inputs or []:
        jtype = _TYPE_MAP.get(getattr(p, "type", "text"), "string")
        spec: dict = {"type": jtype}
        if jtype == "array":
            spec["items"] = {"type": "string"}
        if getattr(p, "help", ""):
            spec["description"] = p.help
        if getattr(p, "options", None) and p.type in ("choice", "multi"):
            spec["enum"] = list(p.options)
        if getattr(p, "default", None) is not None:
            spec["default"] = p.default
        props[p.id] = spec
        if getattr(p, "required", False):
            required.append(p.id)
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def _load_ops() -> dict:
    """Load every connector, return {safe_tool_name: ConnectorOp}."""
    from connectors.base import load_all_connectors, all_ops
    load_all_connectors()
    out: dict = {}
    for op in all_ops():
        out[_safe_name(op.op_id)] = op
    return out


# ── MCP server ───────────────────────────────────────────────────────

async def _serve() -> None:
    from connectors.base import run_op

    ops = _load_ops()
    server = Server("archhub")

    @server.list_tools()
    async def list_tools() -> list:
        tools = []
        for name, op in ops.items():
            desc = (op.description or op.label or op.op_id)
            if op.destructive:
                desc += "  [DESTRUCTIVE — mutates the host]"
            tools.append(mcp_types.Tool(
                name=name,
                description=f"{op.host}: {desc}",
                inputSchema=_input_schema(op.inputs),
            ))
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        op = ops.get(name)
        if op is None:
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps({"ok": False,
                                  "error": f"unknown tool: {name}"}))]
        # run_op is blocking (TCP to a host broker) — keep the asyncio
        # event loop free.
        result = await asyncio.to_thread(run_op, op.op_id,
                                          **(arguments or {}))
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        return [mcp_types.TextContent(type="text",
                                       text=json.dumps(payload, default=str))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream,
                          server.create_initialization_options())


def _selftest() -> int:
    """List the ops that would be advertised, then exit. No stdio loop."""
    ops = _load_ops()
    print(f"archhub-mcp: {len(ops)} connector ops")
    for name, op in sorted(ops.items())[:12]:
        req = [p.id for p in (op.inputs or []) if getattr(p, "required", False)]
        print(f"  {name}  ({op.host}/{op.kind})  required={req}")
    if len(ops) > 12:
        print(f"  ... +{len(ops) - 12} more")
    return 0 if ops else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass
