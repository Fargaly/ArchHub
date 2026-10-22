"""Local coordination delegates to the desktop; no signed-session protocol."""
import asyncio
from types import SimpleNamespace

import pytest

from nodelang import cloud_session
from nodelang.clean_coordination_host import CleanCoordinationHost
from nodelang.native_agent_mcp import build_server
from nodelang.runtime_activity import RuntimeClosing
from nodelang.universal_cell import InvalidCell


def test_host_delegates_an_exact_request_and_trusts_only_application_account(monkeypatch):
    calls = []
    store = object()
    owner = SimpleNamespace(universal_store=store,
        universal_registry=SimpleNamespace(authorization=SimpleNamespace(subject_root='owner-root')),
        dispatch_universal_machine_route=lambda request: calls.append(request) or {'ok': True})
    monkeypatch.setattr(cloud_session, 'signed_in_cloud_account', lambda: 'account@example.test')
    host = CleanCoordinationHost(owner)
    request = {'method': 'GET', 'path': '/api/universal/canvas', 'body': {}}
    assert host.store is store
    assert host.dispatch(request) == {'ok': True, 'account': 'account@example.test'}
    assert calls == [request]
    with pytest.raises(InvalidCell):
        host.dispatch({**request, 'account': 'forged@example.test'})
    host.begin_shutdown()
    with pytest.raises(RuntimeClosing):
        host.dispatch(request)


def test_mcp_schema_has_only_two_message_tools_and_no_sender():
    server = build_server()
    tools = asyncio.run(server.list_tools())
    schemas = {tool.name: tool.inputSchema for tool in tools}
    assert {"send", "read"} <= set(schemas)
    assert not any(name.startswith("coordination.") for name in schemas)
    for name in ("send", "read"):
        assert not {"sender", "vendor", "session_id", "context"} & schemas[name]["properties"].keys()
