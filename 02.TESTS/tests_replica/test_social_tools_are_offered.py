"""Social Works are reachable by the agent that holds them: the native MCP offers the
two Work-root social tools, and nothing else about a social effect is an argument.

register_social_tools was defined and called nowhere (trace 2026-09-28), so no agent
could prepare or execute a social Work.
"""
import asyncio
import json

from nodelang import native_agent_mcp as native


def _server():
    # NOGRAPH (9afdeaa4): the native server talks to the Workshop through its mailbox call; only that transport is
    # replaced here. FastMCP registration, schemas and the social owner (SocialSurface) are real.
    return native.build_server(mailbox_call=lambda *args, **kwargs: {})


def test_the_native_owner_offers_the_two_social_work_tools():
    server = _server()
    schemas = {tool.name: tool.inputSchema for tool in asyncio.run(server.list_tools())}
    assert "social.work_prepare" in schemas and "social.work_execute" in schemas
    assert set(schemas["social.work_prepare"]["properties"]) == {"work_root", "note"}
    assert set(schemas["social.work_execute"]["properties"]) == {"work_root"}
    for name in ("social.work_prepare", "social.work_execute"):
        assert schemas[name].get("additionalProperties") is False, name
    # Reachable by the agent: executing a draft that was never prepared posts nothing and says what to do first.
    answer = asyncio.run(server.call_tool("social.work_execute", {"work_root": "draft-never-prepared"}))
    body = answer[1] if isinstance(answer, tuple) else json.loads(answer[0].text)
    assert body["ok"] is False and body["state"] == "refused" and "social.work_prepare" in body["reason"]