"""Social Works are reachable by the agent that holds them: the native MCP offers the
two Work-root social tools, and nothing else about a social effect is an argument.

register_social_tools was defined and called nowhere (trace 2026-09-28), so no agent
could prepare or execute a social Work.
"""
import asyncio
import threading
from contextlib import contextmanager
from types import SimpleNamespace

from nodelang import native_agent_mcp as native


def _server(monkeypatch):
    client = SimpleNamespace(_request_lock=threading.RLock(), agent_session_root="app:agent-session:runtime:one")

    class Owner:
        def connect(self):
            return client

        def require_client(self):
            return client

        @contextmanager
        def bound_client(self):
            with client._request_lock:
                yield client

    # Only the coordination transport is replaced; FastMCP registration and schemas are real.
    monkeypatch.setattr(native.InstalledWorkshopCoordinationClient, "__init__",
                        lambda self, actual: setattr(self, "_client", actual))
    return native.build_server(session=Owner())


def test_the_native_owner_offers_the_two_social_work_tools(monkeypatch):
    schemas = {tool.name: tool.inputSchema for tool in asyncio.run(_server(monkeypatch).list_tools())}
    assert "social.work_prepare" in schemas and "social.work_execute" in schemas
    assert set(schemas["social.work_prepare"]["properties"]) == {"work_root", "note"}
    assert set(schemas["social.work_execute"]["properties"]) == {"work_root"}
    for name in ("social.work_prepare", "social.work_execute"):
        assert schemas[name].get("additionalProperties") is False, name