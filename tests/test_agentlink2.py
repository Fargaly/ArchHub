"""Fresh MCP connector and shared Workshop mailbox courts (synthetic profiles only)."""
import asyncio
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_fresh_process_has_send_read_without_binding(tmp_path):
    async def court():
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ARCHHUB_", "CODEX_", "CLAUDE_", "SESSION_LINK_", "OPENCODE_", "GEMINI_"))}
        for key in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "HOME", "USERPROFILE"):
            env[key] = str(tmp_path)
        env["ARCHHUB_NATIVE_MCP_LAUNCHER"] = "1"
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "nodelang.native_agent_mcp"], cwd=str(Path(__file__).resolve().parents[1]), env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                assert "send" in tools and "read" in tools
                assert set(tools["send"].inputSchema["properties"]) == {"to", "text", "reply_to"}
                assert set(tools["read"].inputSchema["properties"]) == {"since", "declarations_after", "include_archived"}
                assert not any("recover" in name or "rebind" in name or "owner_" in name for name in tools)
    asyncio.run(court())


def test_two_process_exchange_public_workshop_and_sender_integrity(tmp_path, monkeypatch):
    import json
    from time import perf_counter
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    from nodelang.application_machine_transport import UniversalRuntimeClient

    for key in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(tmp_path))
    local = tmp_path / "ArchHub"
    provider = WindowsDpapiSigningKeyProvider(local / "keys" / "authority-signing-v1.dpapi.json")
    provider.current("archhub.local.universal-runtime-pipe")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = ApplicationServer(enable_machine_transport=True,
        machine_descriptor_path=local / "active-universal-runtime.json",
        machine_key_provider=provider, universal_workspace_root=workspace,
        universal_state_path=tmp_path / "graph.sqlite3").start()

    async def court():
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            from agentlink2_client import start_agent
            peers = []
            for _ in range(2):
                env = {k: v for k, v in os.environ.items() if not k.startswith(("ARCHHUB_", "CODEX_", "CLAUDE_", "SESSION_LINK_", "OPENCODE_", "GEMINI_"))}
                peers.append(await stack.enter_async_context(start_agent(env)))
            assert peers[0].process.pid != peers[1].process.pid
            async def call(peer, name, arguments):
                result = await peer.call_tool(name, arguments)
                assert not result.isError, result
                return result.structuredContent or json.loads(result.content[0].text)
            # Each independently launched MCP process gets its own server-recorded name.
            one = await call(peers[0], "read", {"since": 0})
            two = await call(peers[1], "read", {"since": 0})
            assert one["sender"] != two["sender"]
            # Codex and OpenCode multiplex sessions over one MCP process. The
            # host's protocol metadata distinguishes them without enrollment.
            identities = []
            for metadata in ({"threadId": "thread-one"}, {"threadId": "thread-two"},
                             {"ai.opencode/sessionID": "ses_one"}, {"ai.opencode/sessionID": "ses_two"}):
                result = await peers[0].call_tool("read", {"since": 0}, meta=metadata)
                assert not result.isError, result
                identities.append(result.structuredContent["sender"])
            assert len(set(identities)) == 4
            for operation, arguments in (("native.work_task_attach", {"work_root": "assembly-instance:court"}),
                                         ("native.work_task_detach", {})):
                refused = await peers[0].call_tool(operation, arguments, meta={"threadId": "thread-two"})
                assert refused.isError
                assert "dedicated Work profile" in refused.content[0].text
            same = await peers[0].call_tool("read", {"since": 0}, meta={"threadId": "thread-one", "itemId": "rotated"})
            assert same.structuredContent["sender"] == identities[0]
            forbidden = await peers[0].call_tool("send", {"to": "*", "text": "forged", "context": {"threadId": "thread-two"}})
            assert forbidden.isError
            from_other_process = await peers[1].call_tool("read", {"since": 0}, meta={"threadId": "thread-one"})
            assert from_other_process.structuredContent["sender"] != identities[0]
            before = app.universal_store.revision
            started = perf_counter()
            sent = await call(peers[0], "send", {"to": two["sender"], "text": "peer one to peer two"})
            inbox = await call(peers[1], "read", {"since": sent["sequence"] - 1})
            assert inbox["messages"][-1]["author"] == one["sender"]
            assert inbox["messages"][-1]["content"].endswith("peer one to peer two")
            reply = await call(peers[1], "send", {"to": one["sender"], "text": "peer two to peer one"})
            ack = await call(peers[0], "read", {"since": sent["sequence"]})
            elapsed = perf_counter() - started
            assert ack["messages"][-1]["author"] == two["sender"]
            assert ack["messages"][-1]["content"].endswith("peer two to peer one")
            assert elapsed < 2, elapsed
            assert app.universal_store.revision == before
            forged = await peers[0].call_tool("send", {"to": "*", "text": "forged", "sender": two["sender"]})
            assert forged.isError
            direct = UniversalRuntimeClient(local / "active-universal-runtime.json", provider)
            try:
                direct.request("POST", "/api/universal/agent-mail/send", {"to": "*", "text": "forged", "author": two["sender"]})
            except Exception as exc:
                assert "arguments are invalid" in str(exc)
            else:
                raise AssertionError("transport accepted a forged author")
            projection = app.dispatch_universal_machine_route({"method": "GET",
                "path": "/api/universal/workshop", "body": {}})
            ids = {entry["message_id"] for entry in projection["entries"]}
            assert {sent["message_id"], reply["message_id"]} <= ids
            # The real default Messages feed must include both rows, not merely
            # the broad machine projection (its category filter uses a root ID).
            from nodelang.existing_workshop_conversation import read_browser_workshop
            token = app.browser_session_token
            browser = app._resolve_browser_session(token)
            registry = app.universal_registry
            from nodelang.universal_application import _view_session_for_context, _session_canvas_roots
            view, _ = _view_session_for_context(registry, browser.context)
            _visible, _relations, _properties, trail = _session_canvas_roots(
                app.universal_store.snapshot(), registry, view, include_trail=True)
            page = read_browser_workshop(app, browser, root=registry.workshop_root,
                scope=trail[-1], session_token=token, feed="messages")
            visible = {row["root"] for row in page["messages"]}
            assert {sent["message_id"], reply["message_id"]} <= visible
            for tool, arguments in [("read", {"since": -1}), ("read", {"since": True}),
                                    ("send", {"to": "*", "text": ""})]:
                invalid = await peers[0].call_tool(tool, arguments)
                assert invalid.isError
            # Addressed room notes remain public; existing private messages stay
            # private and an incremental reader never skips a backlog.
            from nodelang.conversation_content import read_content_binding
            with app.mutation_lock:
                binding = read_content_binding(app.universal_store.snapshot(), registry.deliberation_protocol,
                    application_root=registry.application_root, space_root=registry.workshop_root)
                history = app.conversation_content._history_for(binding)
                history.append(registry.workshop_root, author=registry.authorization.subject_root,
                    content="PRIVATE MUST NOT LEAK", category=registry.workshop_category_roots["note"],
                    recipients=(registry.authorization.subject_root,), idempotency_key="mailbox-private-fixture")
                for index in range(105):
                    history.append(registry.workshop_root, author="fixture:public", content="backlog %d" % index,
                        category=registry.workshop_category_roots["note"], idempotency_key="mailbox-backlog-%d" % index)
            first = await call(peers[0], "read", {"since": reply["sequence"]})
            second = await call(peers[0], "read", {"since": first["next_since"]})
            assert len(first["messages"]) == 100 and first["more"] is True
            assert len(second["messages"]) == 5 and second["more"] is False
            rows = first["messages"] + second["messages"]
            assert [row["content"] for row in rows] == ["backlog %d" % index for index in range(105)]
            assert app.universal_store.revision == before
            # BABOOM runs while holding the owner's mutation lock; its same-store
            # adapter must not call its own pipe and wait on that lock.
            with app.mutation_lock:
                from nodelang import baboom_agent_link
                builtin = baboom_agent_link.send_message(one["sender"], "builtin same mailbox",
                    mailbox=app.shared_agent_mail)
            builtin_page = await call(peers[0], "read", {"since": second["next_since"]})
            assert builtin["message_id"] in {row["id"] for row in builtin_page["messages"]}
            assert app.universal_store.revision == before
            return {"measurement": {"metric": "agent_exchange", "unit": "s", "observed": elapsed}, "senders": [one["sender"], two["sender"]], "agent_processes": [peer.process.pid for peer in peers],
                    "message_ids": [sent["message_id"], reply["message_id"]],
                    "existing_workshop_projection": True, "workshop_feed_observed": True,
                    "private_rows_excluded": True, "builtin_same_sink": True, "multiplex_session_names": len(set(identities)), "backlog_rows": len(rows), "graph_revision_unchanged": True}
    try:
        receipt = asyncio.run(court())
        print(json.dumps(receipt))
        (tmp_path / "exchange.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    finally:
        app.close()
