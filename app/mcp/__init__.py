"""ArchHub node-as-MCP-server package.

Every node on the canvas is its own MCP server: it carries a unique
`node_id`, advertises a typed tool surface derived from the node's
type + config, and answers MCP messages (initialize / tools/list /
tools/call) via an in-process JSON-RPC 2.0 envelope.

Public surface:
    NodeMCPServer  — wraps a single node instance.
    MCPRegistry    — keyed by node_id; cross-node lookup.
    REGISTRY       — module-level singleton.
"""
from __future__ import annotations

from .node_mcp import (  # noqa: F401
    NodeMCPServer,
    MCPRegistry,
    REGISTRY,
    MCPTool,
    MCPError,
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
)
