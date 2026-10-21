"""End-to-end courts for BABOOM's graph-governed MCP broker."""
from __future__ import annotations

import hashlib
import time

from nodelang.cell_adapters import UserConsentBroker
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    approve_universal_baboom_connector_execution,
    begin_universal_runtime_agent_session,
    build_universal_application,
    claim_universal_governed_work,
    create_universal_governed_work,
    issue_universal_baboom_connector_execution_grant,
    negotiate_universal_mcp_server,
    project_universal_founder_baboom_capability_report,
    project_universal_mcp_broker,
    register_universal_mcp_server,
    request_universal_baboom_mcp_tool_execution,
    settle_universal_baboom_connector_execution,
)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_mcp_broker_tool_uses_the_existing_approved_connector_receipt_path():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    founder, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root="app:agent-session:runtime:mcp-broker-founder-court",
        runtime="*",
        external_session_fingerprint=_digest(b"mcp-broker-founder-court"),
        catalog_entry_root="app:agent-body-catalog:entry:founder-runtime",
        authentication_context=context,
    )
    server, _ = register_universal_mcp_server(
        store,
        registry,
        founder_agent_session_root=founder.root_id,
        transport="stdio",
        config_digest=_digest(b"local-mcp-config"),
        data_classes=["internal-text"],
        authentication_context=context,
    )
    execution, _ = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root="app:agent-session:runtime:mcp-broker-court",
        runtime="baboom-execution",
        external_session_fingerprint=_digest(b"mcp-broker-court"),
        catalog_entry_root="app:agent-body-catalog:entry:baboom-execution",
        authentication_context=context,
    )
    work_root, _, _ = create_universal_governed_work(
        store,
        registry,
        title="Review a governed MCP tool capability",
        description="Prepare one bounded tool request without importing its raw payload.",
        priority=55,
        external_key="court:mcp-broker-tool",
        x=560.0,
        y=340.0,
        authentication_context=context,
    )
    claim_universal_governed_work(
        store,
        registry,
        agent_session_root=execution.root_id,
        work_root=work_root,
        authentication_context=context,
    )
    negotiation, tools, _ = negotiate_universal_mcp_server(
        store,
        registry,
        agent_session_root=execution.root_id,
        work_root=work_root,
        server_root=server.root_id,
        protocol_version="2025-06-18",
        capabilities_digest=_digest(b"tools-capability"),
        manifest_digest=_digest(b"private-manifest"),
        tools=(
            {
                "name_digest": _digest(b"private-tool-name"),
                "schema_digest": _digest(b'{"type":"object"}'),
                "data_class": "internal-text",
            },
        ),
        authentication_context=context,
    )
    assert len(tools) == 1
    raw_input = b'{"scope":"private-work"}'
    delegation, bound_negotiation, _ = request_universal_baboom_mcp_tool_execution(
        store,
        registry,
        agent_session_root=execution.root_id,
        work_root=work_root,
        tool_root=tools[0].root_id,
        input_digest=_digest(raw_input),
        input_bytes=len(raw_input),
        authentication_context=context,
    )
    assert bound_negotiation.root_id == negotiation.root_id
    assert delegation.provider_root == tools[0].provider_root

    consent = UserConsentBroker()
    approve_universal_baboom_connector_execution(
        store,
        registry,
        founder_agent_session_root=founder.root_id,
        delegation_root=delegation.root_id,
        consent_broker=consent,
        authentication_context=context,
    )
    _, grant_expiry, _ = issue_universal_baboom_connector_execution_grant(
        store,
        registry,
        agent_session_root=execution.root_id,
        delegation_root=delegation.root_id,
        grant_id="app:baboom-connector-grant:mcp-broker-court",
        token_digest=_digest(b"one-use-token"),
        expires_at=time.time() + 60.0,
        authentication_context=context,
    )
    receipt, history_root, _ = settle_universal_baboom_connector_execution(
        store,
        registry,
        agent_session_root=execution.root_id,
        delegation_root=delegation.root_id,
        grant_root="app:baboom-connector-grant:mcp-broker-court",
        output_digest=_digest(b""),
        output_bytes=0,
        outcome="failed",
        error_code="local.transport-unavailable",
        authentication_context=context,
    )
    assert grant_expiry > time.time()
    assert receipt.provider_root == tools[0].provider_root
    assert receipt.outcome == "failed"
    assert history_root == ""

    projection = project_universal_mcp_broker(store, registry)
    assert projection["released_transports"] == ["https", "stdio"]
    assert projection["registered_servers"] == 1
    assert projection["active_negotiations"] == 1
    assert projection["admitted_tools"] == 1
    assert "private-tool-name" not in repr(store.snapshot().cells)
    report = project_universal_founder_baboom_capability_report(store, registry)
    assert report["mcp_broker"] == projection
