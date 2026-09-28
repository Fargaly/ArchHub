"""OpenCode messages other agents through its own hook session, never a guessed one.

OpenCode starts MCP servers once per app, so the archhub-agent-coordination MCP in its
configuration died at start: "actual OpenCode hook session identity is required"
(nodelang/native_agent_session.py). That refusal is right and stays. Messages go
through the governance plugin's per-session native owner instead: the plugin tool
archhub_message, executed once by the direct child that holds the caller's session.
"""
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GATE = Path(os.environ.get("ARCHHUB_OPENCODE_GATE")
            or ROOT.parents[1] / "00.GOVERNANCE" / "hooks" / "opencode_native_gate.py")
GATE_HOOKS = Path(os.environ.get("ARCHHUB_OPENCODE_GATE_HOOKS")
                  or ROOT.parents[1] / "00.GOVERNANCE" / "hooks")


def test_the_per_app_server_still_refuses_to_guess_an_opencode_identity():
    from nodelang.native_agent_session import resolve_native_agent_identity
    with pytest.raises(ValueError, match="actual OpenCode hook session identity is required"):
        resolve_native_agent_identity({"ARCHHUB_COORDINATION_VENDOR": "opencode",
                                       "ARCHHUB_COORDINATION_SESSION": "opencode-fargaly"})
    identity = resolve_native_agent_identity({"ARCHHUB_COORDINATION_VENDOR": "opencode",
                                              "OPENCODE_SESSION_ID": "ses_abc123"})
    assert (identity.runtime, identity.external_session_id) == ("opencode", "ses_abc123")


def test_the_plugin_offers_archhub_message_executed_once_by_the_callers_own_session():
    module = (ROOT / "nodelang/session_link/opencode-governance.mjs").as_uri()
    code = r"""import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const factory=d=>d;factory.schema={string:()=>({optional(){return this;}}),object:()=>({passthrough(){return this;}})};
const events=[];
const hooks=await createOpenCodeGovernance({workToolFactory:factory,gateRunner:async event=>{
 events.push(event);return {allow:true,toolOutput:'{"sent":true}'};
}})({directory:process.cwd()});
assert.equal(typeof hooks.tool?.archhub_message?.execute,'function','the plugin offers no agent message tool');
const input={sessionID:'ses_writer',callID:'msg-1',tool:'archhub_message'};
const output={args:{operation:'coordination.send_message',arguments:{target:'coordinator',message:'hello',idempotency_key:'k-1'}}};
await hooks['tool.execute.before'](input,output);
await assert.rejects(hooks.tool.archhub_message.execute(output.args,{sessionID:'ses_other',directory:process.cwd()}),/matching native admission/);
assert.equal(await hooks.tool.archhub_message.execute(output.args,{sessionID:'ses_writer',directory:process.cwd()}),'{"sent":true}');
await assert.rejects(hooks.tool.archhub_message.execute(output.args,{sessionID:'ses_writer',directory:process.cwd()}),/matching native admission/);
await hooks['tool.execute.after']({...input,args:output.args},{});
assert.deepEqual(events.map(e=>e.hook_event_name),['PreToolUse','NativeToolExecute','PostToolUse']);
assert.ok(events.every(e=>e.session_id==='ses_writer'&&e.tool_name==='archhub_message'&&e.tool_use_id==='msg-1'&&!('_archhub_call' in e.tool_input)));
await assert.rejects(hooks['tool.execute.before']({...input,callID:'msg-2'},{args:{operation:'coordination.send_message'}}),/arguments unavailable/);
await hooks.dispose();
""".replace("MODULE", json.dumps(module))
    result = subprocess.run([shutil.which("node"), "--input-type=module"], input=code, text=True,
                            encoding="utf-8", capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr[-3000:]


class _Owner:
    def __init__(self):
        self._identity = SimpleNamespace(external_session_id="ses_writer")
        self.bound = 0

    @contextlib.contextmanager
    def bound_client(self):
        self.bound += 1
        yield "client"

    def _check_identity(self):
        return None


def _event(phase, **extra):
    return {"vendor": "opencode", "session_id": "ses_writer", "tool_name": "archhub_message",
            "tool_use_id": "msg-1", "hook_event_name": phase, "cwd": os.getcwd(),
            "tool_input": {"operation": "coordination.send_message",
                           "arguments": {"target": "coordinator", "message": "hi", "idempotency_key": "k"}},
            **extra}


def test_the_worker_serves_only_message_operations_under_its_owner_and_never_replays(monkeypatch):
    import nodelang.opencode_coordination_tools as tools
    built, calls = [], []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        return {"ok": True}

    monkeypatch.setattr(tools, "_OwnedWorkshopClient", lambda owner, client: ("owned", client))
    monkeypatch.setattr(tools, "build_coordination_server",
                        lambda client: built.append(client) or SimpleNamespace(call_tool=call_tool))
    owner = _Owner()
    adapter = tools.OpenCodeCoordinationTools(owner)
    assert built == [("owned", "client")], "the server is built on this owner's bound client"
    assert adapter.dispatch(_event("PreToolUse")) == {"decision": "allow"}
    executed = adapter.dispatch(_event("NativeToolExecute"))
    assert executed["decision"] == "allow" and json.loads(executed["tool_output"])["isError"] is False
    assert calls == [("coordination.send_message", {"target": "coordinator", "message": "hi", "idempotency_key": "k"})]
    with pytest.raises(ValueError):
        adapter.dispatch(_event("NativeToolExecute"))
    assert len(calls) == 1, "a message is never sent twice"
    assert adapter.dispatch(_event("PostToolUse")) == {"decision": "allow"}
    with pytest.raises(ValueError):
        adapter.dispatch(_event("PreToolUse", session_id="ses_other"))
    with pytest.raises(ValueError):
        adapter.dispatch(_event("PreToolUse", tool_name="archhub_work"))
    assert adapter.dispatch(_event("PreToolUse", tool_use_id="w", tool_input={
        "operation": "native.work_claim", "arguments": {}})) == {"decision": "deny"}


def test_the_native_gate_hands_archhub_message_to_the_owner_adapter(monkeypatch):
    if not GATE.is_file() or not (GATE_HOOKS / "pretooluse_validate.py").is_file():
        pytest.skip("the private OpenCode native gate is not on this machine")
    monkeypatch.syspath_prepend(str(GATE_HOOKS))
    spec = importlib.util.spec_from_file_location("opencode_native_gate_under_test", GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    made = []

    class Adapter:
        def __init__(self, owner):
            made.append(owner)

        def dispatch(self, event):
            return {"decision": "allow", "routed": event["tool_use_id"]}

    monkeypatch.setitem(sys.modules, "nodelang.opencode_coordination_tools",
                        SimpleNamespace(OpenCodeCoordinationTools=Adapter))
    owner = _Owner()
    for call in ("msg-1", "msg-2"):
        try:
            answer = gate.evaluate(_event("PreToolUse", tool_use_id=call), owner)
        except Exception as error:
            pytest.fail("the gate has no archhub_message route: %s: %s" % (type(error).__name__, error))
        assert answer == {"decision": "allow", "routed": call}
    assert made == [owner], "one adapter is retained per owner"
