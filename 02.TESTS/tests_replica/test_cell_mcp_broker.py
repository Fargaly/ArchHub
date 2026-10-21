"""Courts for fingerprint-only MCP broker admission records."""
from __future__ import annotations

import hashlib
import time

import pytest

from nodelang.cell_mcp_broker import (
    bootstrap_mcp_broker_protocol,
    read_mcp_tool,
    record_mcp_negotiation,
    register_mcp_server,
    register_mcp_tool,
    require_active_mcp_tool,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _terminal(store: CellStore, root: str, value: str) -> None:
    snapshot = store.snapshot()
    store.commit(
        snapshot.revision,
        create=(Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8")),),
    )


def test_mcp_tool_admission_is_fingerprint_only_and_bound_to_one_negotiation():
    store = CellStore()
    protocol = bootstrap_mcp_broker_protocol(store, prefix="court:mcp-broker")
    for root in ("court:adapter", "court:internal-text", "court:session", "court:work", "court:provider"):
        _terminal(store, root, root)
    server = register_mcp_server(
        store,
        protocol,
        server_id="court:mcp-server",
        adapter_root="court:adapter",
        transport="stdio",
        config_digest=_digest(b"private-command-and-environment"),
        datatype_roots=("court:internal-text",),
    )
    negotiation = record_mcp_negotiation(
        store,
        protocol,
        negotiation_id="court:mcp-negotiation",
        server_root=server.root_id,
        session_root="court:session",
        work_root="court:work",
        protocol_version="2025-06-18",
        capabilities_digest=_digest(b"tools"),
        manifest_digest=_digest(b"private-tool-manifest"),
        expires_at=time.time() + 120.0,
    )
    raw_tool_name = b"private_internal_tool_name"
    raw_schema = b'{"private": "schema"}'
    tool = register_mcp_tool(
        store,
        protocol,
        tool_id="court:mcp-tool",
        negotiation_root=negotiation.root_id,
        name_digest=_digest(raw_tool_name),
        schema_digest=_digest(raw_schema),
        datatype_root="court:internal-text",
        provider_root="court:provider",
    )

    assert require_active_mcp_tool(
        store.snapshot(), protocol, tool.root_id
    ) == tool
    assert read_mcp_tool(store.snapshot(), protocol, tool.root_id) == tool
    stored = repr(store.snapshot().cells)
    assert raw_tool_name.decode("ascii") not in stored
    assert raw_schema.decode("ascii") not in stored

    with pytest.raises(InvalidCell, match="identity is already registered"):
        register_mcp_tool(
            store,
            protocol,
            tool_id="court:mcp-tool-replay",
            negotiation_root=negotiation.root_id,
            name_digest=_digest(raw_tool_name),
            schema_digest=_digest(b"different-schema"),
            datatype_root="court:internal-text",
            provider_root="court:provider",
        )


def test_mcp_tool_rejects_an_expired_negotiation():
    store = CellStore()
    protocol = bootstrap_mcp_broker_protocol(store, prefix="court:mcp-expiry")
    for root in ("court:adapter", "court:internal-text", "court:session", "court:work", "court:provider"):
        _terminal(store, root, root)
    server = register_mcp_server(
        store,
        protocol,
        server_id="court:mcp-server-expiry",
        adapter_root="court:adapter",
        transport="https",
        config_digest=_digest(b"https-fingerprint"),
        datatype_roots=("court:internal-text",),
    )
    observed = time.time() - 120.0
    negotiation = record_mcp_negotiation(
        store,
        protocol,
        negotiation_id="court:mcp-negotiation-expiry",
        server_root=server.root_id,
        session_root="court:session",
        work_root="court:work",
        protocol_version="2025-06-18",
        capabilities_digest=_digest(b"capabilities"),
        manifest_digest=_digest(b"manifest"),
        observed_at=observed,
        expires_at=observed + 60.0,
    )
    with pytest.raises(InvalidCell, match="negotiation has expired"):
        register_mcp_tool(
            store,
            protocol,
            tool_id="court:mcp-tool-expiry",
            negotiation_root=negotiation.root_id,
            name_digest=_digest(b"tool"),
            schema_digest=_digest(b"schema"),
            datatype_root="court:internal-text",
            provider_root="court:provider",
        )
