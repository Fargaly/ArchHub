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


# ── Secret resolution at launch (2026-06-03) ────────────────────────
# Secrets are stored as op:// REFERENCES, never inline plaintext (a live
# DASHSCOPE_API_KEY was found inlined in .claude.json). The dashscope
# connector reads os.environ["DASHSCOPE_API_KEY"] raw, so we resolve any
# op:// env reference to its real value HERE, once, before the stdio loop
# serves any tool call. Resolution mirrors the repo's canonical resolver
# (personal_brain.secret_resolver): 1Password CLI -> Windows Credential
# Manager (keyring) -> OP_<VAULT>_<ITEM>_<FIELD> env fallback. A non-op://
# value passes through unchanged (plaintext still works during migration).
# Values are NEVER logged.
_SECRET_ENV_KEYS = ("DASHSCOPE_API_KEY",)


def _resolve_secret_env() -> None:
    """Resolve op:// references in known secret env vars in place."""
    resolve = None
    try:
        _src = os.path.abspath(
            os.path.join(_APP_DIR, os.pardir, "personal-brain-mcp", "src"))
        if os.path.isdir(_src) and _src not in sys.path:
            sys.path.append(_src)
        from personal_brain.secret_resolver import resolve_secret as resolve
    except Exception:
        resolve = None
    if resolve is None:
        import shutil as _sh
        import subprocess as _sp

        def resolve(ref):  # self-contained equivalent of secret_resolver
            if not ref or not ref.startswith("op://"):
                return ref
            parts = ref[len("op://"):].split("/")
            if len(parts) < 3 or not all(parts[:3]):
                return ref
            vault, item, field = parts[0], parts[1], parts[2]
            if _sh.which("op"):
                try:
                    p = _sp.run(["op", "read", ref], capture_output=True,
                                text=True, timeout=5.0)
                    if p.returncode == 0 and (p.stdout or "").strip():
                        return p.stdout.strip()
                except (OSError, _sp.SubprocessError):
                    pass
            try:
                import keyring  # Windows Credential Manager backend
                v = keyring.get_password(vault + "/" + item, field)
                if v and v.strip():
                    return v.strip()
            except Exception:
                pass

            def _n(s):
                return s.upper().replace("/", "_").replace("-", "_")

            return os.environ.get(
                "OP_%s_%s_%s" % (_n(vault), _n(item), _n(field)))

    for _k in _SECRET_ENV_KEYS:
        _cur = os.environ.get(_k)
        if not _cur or not _cur.startswith("op://"):
            continue
        try:
            _val = resolve(_cur)
        except Exception:
            _val = None
        if _val and _val != _cur:
            os.environ[_k] = _val  # resolved real value (never logged)
        # If unresolvable, leave the op:// ref; the connector then reports
        # "DASHSCOPE_API_KEY not set" rather than using a bogus literal.


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

def _build_server(ops):
    """Build the MCP Server (list_tools + call_tool) over the loaded ops —
    transport-agnostic so the stdio path and the persistent HTTP/SSE path share
    exactly the same tool surface."""
    from connectors.base import run_op
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

    return server


async def _serve() -> None:
    """stdio transport — the historical per-turn spawn path (default)."""
    server = _build_server(_load_ops())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream,
                          server.create_initialization_options())


def _serve_http(host: str, port: int) -> None:
    """Persistent HTTP/SSE transport. The app starts ONE of these on launch so
    the tool surface is ALWAYS ready; the chat brain (claude --transport sse)
    connects to the ready URL instead of spawning a COLD stdio server per turn —
    whose 'pending'/0-tools startup race left the brain tool-less and made it
    fabricate host calls (founder 2026-06-09 'why is it not working')."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    import uvicorn

    server = _build_server(_load_ops())
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
                request.scope, request.receive, request._send) as (r, w):
            await server.run(r, w, server.create_initialization_options())

    app = Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ])
    uvicorn.run(app, host=host, port=int(port), log_level="warning")


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
    _resolve_secret_env()  # op:// env refs -> real values before serving
    import os as _os
    _http_port = _os.environ.get("ARCHHUB_MCP_HTTP_PORT", "")
    if "--http" in sys.argv or _http_port:
        # Persistent HTTP/SSE mode — the app starts one of these on launch.
        _serve_http(_os.environ.get("ARCHHUB_MCP_HTTP_HOST", "127.0.0.1"),
                    int(_http_port or "48700"))
    else:
        try:
            asyncio.run(_serve())
        except KeyboardInterrupt:
            pass
