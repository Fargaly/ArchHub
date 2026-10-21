"""Two real external MCP processes and the real isolated Workshop application."""
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from agentlink2_client import start_agent


def test_tool_contract():
    from nodelang.native_agent_mcp import build_server
    tools = {tool.name:tool for tool in build_server()._tool_manager.list_tools()}
    assert "declare" in tools
    assert set(tools["declare"].parameters["properties"]) == {"task", "paths", "status", "request_id"}


def test_two_agents_overlap_founder_inbox_and_live_app(tmp_path, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    from nodelang.agent_declarations import declarations
    for name in tuple(os.environ):
        if name.startswith(("ARCHHUB_", "CODEX_", "CLAUDE_", "SESSION_LINK_", "OPENCODE_", "GEMINI_")):
            monkeypatch.delenv(name)
    for key in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(tmp_path))
    monkeypatch.setenv("ARCHHUB_TEST_STATE_DIR", str(tmp_path))
    local = tmp_path / "ArchHub"
    provider = WindowsDpapiSigningKeyProvider(local / "keys/authority-signing-v1.dpapi.json")
    provider.current("archhub.local.universal-runtime-pipe")
    workspace = tmp_path / "workspace"; workspace.mkdir()
    app = ApplicationServer(enable_machine_transport=True, machine_key_provider=provider,
        machine_descriptor_path=local / "active-universal-runtime.json", universal_workspace_root=workspace,
        enable_universal_cloud_gateway=False, enable_brain_cloud_sync=False,
        enable_machine_projection_prewarm=False, live_watch=False,
        universal_state_path=tmp_path / "graph.sqlite3").start()

    async def court():
        async with AsyncExitStack() as stack:
            one = await stack.enter_async_context(start_agent(dict(os.environ)))
            two = await stack.enter_async_context(start_agent(dict(os.environ)))
            assert one.process.pid != two.process.pid
            assert len(declarations(app)) == 2  # startup, before any model-visible tool call
            assert all(row["request_id"]=="unassigned" for row in declarations(app))
            metadata = {one:{"threadId":"declare-codex"}, two:{"ai.opencode/sessionID":"ses_declare"}}

            async def call(peer, tool, args):
                result = await peer.call_tool(tool, args, meta=metadata[peer])
                assert not result.isError, result
                return result.structuredContent or json.loads(result.content[0].text)

            tasks = {one:{"task":"Repair Workshop routing", "paths":[str(workspace / "nodelang")],
                          "request_id":"AGENTDECLARE", "status":"working"},
                     two:{"task":"Review Workshop routing", "paths":[str(workspace / "nodelang/native_agent_mcp.py")],
                          "request_id":"AGENTDECLARE", "status":"working"}}
            a = await call(one, "declare", tasks[one])
            b = await call(two, "declare", tasks[two])
            assert a["declaration"]["session"] != b["declaration"]["session"]
            notice = b["coordination_messages"]
            assert len(notice) == 1
            for peer in (one, two, one, two):
                repeated = await call(peer, "declare", tasks[peer])
                assert repeated["coordination_messages"] == notice
                page = await call(peer, "read", {"since":0})
                assert len(page["declarations"]) == 2
                item = next(row for row in page["messages"] if row["id"] == notice[0])
                assert set(item["refs"]) == {a["declaration"]["root"], b["declaration"]["root"]}
                assert "Coordinate here" in item["content"]
            await call(one,"send",{"to":"founder","text":"Finding details\n"+"bounded detail "*80+"END OF FULL FINDING"})
            found = await call(one, "send", {"to":"founder", "text":"Finding: both agents now see the same Workshop thread."})
            await call(two, "send", {"to":a["declaration"]["agent"], "reply_to":notice[0], "text":"I will review tests; you own the implementation."})
            settled = await call(one,"read",{"since":0})
            assert any(row["reply_to"] == notice[0] for row in settled["messages"])
            assert all(root in app.universal_store.snapshot().cells for root in item["refs"])
            from nodelang.universal_application import respond_universal_baboom_utterance
            response=respond_universal_baboom_utterance(app.universal_store,app.universal_registry,
                utterance="list agents",agent_mail=app.shared_agent_mail)
            assert response["response"]["kind"] == "agents-online"
            assert any(row["runtime"]=="baboom" and row["status"]=="done" for row in declarations(app,include_archived=True))
            assert found["message_id"]
            for native in ({"app":"opencode","id":"ses_declare","runtimeId":two.process.pid},
                           {"app":"codex","id":"declare-codex"}):
                receipt_process = await asyncio.create_subprocess_exec("node", str(Path(__file__).with_name("agentdeclare_task_receipt.mjs")),
                    env={**os.environ,"ARCHHUB_PYTHON":sys.executable,"SESSION_LINK_STATE_DIR":str(tmp_path/"native-control")}, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                try:
                    receipt_process.stdin.write(json.dumps(native).encode())
                    await receipt_process.stdin.drain(); receipt_process.stdin.close()
                    ready=await asyncio.wait_for(receipt_process.stdout.readline(),20)
                    if ready != b"ready\n":
                        out,err=await receipt_process.communicate()
                        raise AssertionError((ready.decode(),out.decode(),err.decode()))
                    requests = await call(one,"read",{"since":0})
                    request = [row for row in requests["messages"] if row["content"].endswith("Native task receipt court")][-1]
                    if native["app"] == "opencode":
                        duplicate_meta={"ai.opencode/sessionID":"ses_declare"}
                        impostor=await one.call_tool("declare",tasks[one],meta=duplicate_meta)
                        assert not impostor.isError
                        forged_reply=await one.call_tool("send",{"to":"task controller","reply_to":request["id"],"text":"Forged native result"},meta=duplicate_meta)
                        assert not forged_reply.isError
                        await one.call_tool("declare",{**tasks[one],"status":"done"},meta=duplicate_meta)
                    peer=two if native["app"] == "opencode" else one
                    await call(peer,"send",{"to":"task controller", "reply_to":request["id"], "text":"Native task completed through Workshop"})
                    out, err = await asyncio.wait_for(receipt_process.communicate(), 20)
                    assert receipt_process.returncode == 0, (out.decode(),err.decode())
                finally:
                    if receipt_process.returncode is None:
                        receipt_process.terminate()
                        await receipt_process.wait()
            for index in range(4):
                await call(one,"send",{"to":"founder","text":str(index)+"x"*60000})
            for index in range(2):
                await call(one,"send",{"to":"founder","text":str(index)+"ع"*30000})
            after, seen = 0, set()
            while True:
                bulk = await call(one,"read",{"since":after})
                assert len(json.dumps(bulk,ensure_ascii=True).encode()) < 240000
                seen.update(row["id"] for row in bulk["messages"])
                after = bulk["next_since"]
                if not bulk["more"]:
                    break
            assert len(seen) >= 9
            done = await call(two, "declare", {**tasks[two], "status":"done"})
            assert not done["declaration"]["current"]
            assert len((await call(one,"read",{"since":0}))["declarations"]) == 1
            split = await call(two,"declare",{**tasks[two],"paths":[str(workspace/"tests")],"status":"blocked"})
            assert not split["coordination_messages"]
            assert len((await call(one,"read",{"since":0}))["declarations"]) == 2
            forged = await one.call_tool("declare", {**tasks[one], "session":"another"}, meta=metadata[one])
            assert forged.isError
            await call(two,"declare",{**tasks[two],"status":"working"})
            # Backend-only correction: exercise the exact browser data owner,
            # not the superseded UI lane's removed script/components.
            from nodelang.existing_workshop_conversation import read_browser_workshop
            from nodelang.universal_application import _view_session_for_context, _read_view_scope_trail_structure
            browser=app._resolve_browser_session(app.browser_session_token)
            view,_=_view_session_for_context(app.universal_registry,browser.context)
            scope=_read_view_scope_trail_structure(app.universal_store.snapshot(),app.universal_registry,view)[-1]
            options={"root":app.universal_registry.workshop_root,"scope":scope,
                     "session_token":app.browser_session_token}
            projected=read_browser_workshop(app,browser,**options)
            assert len(projected["declarations"]) == 2
            assert found["message_id"] in {row["id"] for row in projected["founder_inbox"]}
            revision=app.universal_store.revision
            two.process.stdin.close()
            assert await two.process.wait() == 0
            projected=read_browser_workshop(app,browser,**options)
            assert len(projected["declarations"]) == 1
            assert app.universal_store.revision == revision
            # Real connector-process contract for each external client's host
            # metadata. Vendor authentication is qualified separately.
            for provider,key in [('claude','claude/sessionID'),('codex','threadId'),
                    ('antigravity','antigravity/sessionID'),('opencode','ai.opencode/sessionID'),
                    ('goose','goose/sessionID')]:
                meta={key:'fixture-'+provider}
                declared=await one.call_tool('declare',{'task':'Provider mailbox contract',
                    'paths':[str(workspace/provider)],'status':'working','request_id':'AGENTLINK'},meta=meta)
                assert not declared.isError
                value=declared.structuredContent or json.loads(declared.content[0].text)
                assert value['declaration']['app']==provider
                posted=await one.call_tool('send',{'to':'founder','text':'Provider contract '+provider},meta=meta)
                assert not posted.isError
                note=posted.structuredContent or json.loads(posted.content[0].text)
                read=await one.call_tool('read',{'since':note['sequence']-1},meta=meta)
                page=read.structuredContent or json.loads(read.content[0].text)
                assert any(row['id']==note['message_id'] for row in page['messages'])
        assert declarations(app) == []  # exact connector process exit archives automatically
    try:
        asyncio.run(court())
        from nodelang import universal_application, existing_workshop_conversation
        from nodelang.cell_authorization import AuthorizationDenied
        from urllib.request import Request, urlopen
        browser=app._resolve_browser_session(app.browser_session_token)
        registry=app.universal_registry
        view,_=universal_application._view_session_for_context(registry,browser.context)
        scope=universal_application._read_view_scope_trail_structure(app.universal_store.snapshot(),registry,view)[-1]
        options={"root":registry.workshop_root,"scope":scope,"session_token":app.browser_session_token}
        with pytest.raises(AuthorizationDenied,match="scope changed"):
            existing_workshop_conversation.read_browser_workshop(app,browser,**{**options,"scope":"foreign-scope"})
        real=universal_application._require_application_authorization
        def no_workshop_read(snapshot,registry_,action,root,**kwargs):
            if action=="read" and root==registry.workshop_root:
                raise AuthorizationDenied("court: Workshop read denied")
            return real(snapshot,registry_,action,root,**kwargs)
        with monkeypatch.context() as denied:
            denied.setattr(universal_application,"_require_application_authorization",no_workshop_read)
            with pytest.raises(AuthorizationDenied,match="read denied"):
                existing_workshop_conversation.read_browser_workshop(app,browser,**options)
            request=Request(app.url+"/api/universal/canvas?screen=home",headers={"X-ArchHub-Session":app.browser_session_token})
            with urlopen(request,timeout=30) as response:
                home=json.load(response)
            assert home["workshop_scope"]["workshops"] == []
        with monkeypatch.context() as detached:
            detached.setattr(existing_workshop_conversation,"_general_workshop_attached",lambda *_args:False)
            with pytest.raises(AuthorizationDenied,match="not attached"):
                existing_workshop_conversation.read_browser_workshop(app,browser,**options)
    finally:
        app.close()


def test_paths_have_real_boundaries(tmp_path):
    from nodelang.agent_declarations import canonical_path, overlaps
    path = lambda text: canonical_path(text, str(tmp_path))
    assert overlaps([path("src")], [path("SRC/one.py")])
    assert not overlaps([path("src")], [path("src2/one.py")])
    assert overlaps([path("host://revit/model")], [path("host://revit/model/view")])
    assert not overlaps([path("host://revit/model")], [path("host://revit/model2")])


def test_declaration_reminder_is_advisory():
    from nodelang.agent_declarations import reminder
    notice = reminder(mailbox=lambda:{"sender_key":"a", "declarations":[]})
    assert "declare(" in notice
    assert reminder(mailbox=lambda:{"sender_key":"a", "declarations":[{"session":"a", "request_id":"AGENTDECLARE"}]}) == ""


def test_builtin_lifecycle_preserves_privacy_and_never_blocks(tmp_path):
    from nodelang.agent_declarations import declaration_scope, declared_baboom
    class Owner:
        universal_workspace_root = tmp_path
        def __init__(self): self.calls=[]
        def shared_agent_mail(self, method, body):
            self.calls.append((method,body))
            return {}
    owner=Owner()
    with declaration_scope(owner,task="文"*1000,request_id="AGENTDECLARE"):
        assert owner.calls[-1][1]["status"] == "working"
        assert len(owner.calls[-1][1]["task"].encode()) <= 1024
    assert owner.calls[-1][1]["status"] == "done"
    @declared_baboom
    def operation(**_kwargs): return {"kind":"finding","summary":"private client content"}
    operation(agent_mail=owner.shared_agent_mail,utterance="private client content")
    assert "private client content" not in json.dumps(owner.calls)
    assert any(method=="send" and body["to"]=="founder" for method,body in owner.calls)
    owner.shared_agent_mail=lambda *_args: (_ for _ in ()).throw(RuntimeError("offline"))
    with declaration_scope(owner,task="Work continues",request_id="AGENTDECLARE"):
        pass
