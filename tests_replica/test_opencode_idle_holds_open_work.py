"""No idle turn end in OpenCode: a session that goes idle with open Work is prompted once.

OpenCode has no blocking Stop. On session.idle the plugin asks the session's LIVE
native owner (the gate worker) for its Work verdict; on a block it re-prompts once,
and the next idle passes. It never spawns, enrolls or renews an owner to ask.
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
GATE_HOOKS = GATE.parent
MODULE = (ROOT / "nodelang/session_link/opencode-governance.mjs").as_uri()


def _node(code):
    result = subprocess.run([shutil.which("node"), "--input-type=module"], input=code.replace("MODULE", json.dumps(MODULE)),
                            text=True, encoding="utf-8", capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr[-3000:]


def test_an_idle_session_with_open_work_is_prompted_once_per_turn():
    _node(r"""import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
let verdict={decision:'block',reason:'Work W-12 is open: submit its evidence.'};
const asked=[],prompts=[];
const runner=async()=>({allow:true,toolOutput:'{}'});
runner.idle=async(session,cwd)=>{asked.push([session,cwd]);return verdict;};
const client={session:{prompt:async request=>{prompts.push(request);return {};}}};
const hooks=await createOpenCodeGovernance({gateRunner:runner})({directory:process.cwd(),client});
assert.equal(typeof hooks.event,'function','the plugin has no event hook');
const idle={event:{type:'session.idle',properties:{sessionID:'ses_writer'}}};
await hooks.event({event:{type:'session.status',properties:{sessionID:'ses_writer'}}});
assert.equal(asked.length,0,'only session.idle is handled');
await hooks.event(idle);
assert.equal(prompts.length,1);
assert.equal(prompts[0].path.id,'ses_writer');
assert.match(prompts[0].body.parts[0].text,/Work W-12 is open/);
await hooks.event(idle);
assert.equal(prompts.length,1,'the idle after the reminder passes');
await hooks.event(idle);
assert.equal(prompts.length,2,'the next turn is held again');
verdict=null;await hooks.event({event:{type:'session.idle',properties:{sessionID:'ses_other'}}});
assert.equal(prompts.length,2,'no open Work, no prompt');
""")


def test_the_idle_check_never_spawns_an_owner():
    _node(r"""import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {createNativeGateRunner} from MODULE;
const mark=path.join(os.tmpdir(),'archhub-idle-spawn-'+process.pid);
const run=createNativeGateRunner(process.execPath,['-e','require("fs").writeFileSync('+JSON.stringify(mark)+',"x")'],
 {selectedWorks:{ses_writer:'assembly-instance:1'},sessionLink:{node:process.execPath,stateDirectory:os.tmpdir(),connections:{ses_writer:['0123456789abcdef']}}});
assert.equal(await run.idle('ses_writer',process.cwd()),null);
assert.equal(await run.idle('ses_unconfigured',process.cwd()),null);
await assert.rejects(async()=>run({session_id:'ses_writer',cwd:process.cwd(),tool_use_id:'idle-1',vendor:'opencode',hook_event_name:'Stop'}),/no live native owner/);
await new Promise(r=>setTimeout(r,300));
assert.equal(fs.existsSync(mark),false,'an idle check spawned an owner');
""")


class _Owner:
    def __init__(self):
        self._identity = SimpleNamespace(external_session_id="ses_writer")

    def _check_identity(self):
        return None


def test_the_gate_answers_stop_with_the_owners_work_verdict(monkeypatch):
    if not GATE.is_file() or not (GATE_HOOKS / "pretooluse_validate.py").is_file():
        pytest.skip("the private OpenCode native gate is not on this machine")
    monkeypatch.syspath_prepend(str(GATE_HOOKS))
    spec = importlib.util.spec_from_file_location("opencode_native_gate_idle", GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    import nodelang.native_agent_hooks as hooks
    open_work = {"decision": "block", "reason": "Work W-12 is open."}
    monkeypatch.setattr(hooks, "idle_verdict", lambda owner: open_work, raising=False)
    event = {"vendor": "opencode", "session_id": "ses_writer", "tool_use_id": "idle-1",
             "hook_event_name": "Stop", "cwd": os.getcwd()}
    answer = gate.evaluate(event, _Owner())
    assert answer["decision"] == "allow" and json.loads(answer["tool_output"]) == open_work


def test_idle_verdict_reads_the_bound_work_index_and_never_invents_a_block(monkeypatch):
    import nodelang.native_agent_hooks as hooks
    seen = []

    class Client:
        def request(self, method, path, query, response_timeout_seconds):
            seen.append((method, path, query))
            return {"index": True}

    class Control:
        @contextlib.contextmanager
        def bound_client(self):
            yield Client()

    class Gone:
        @contextlib.contextmanager
        def bound_client(self):
            raise RuntimeError("lease expired")
            yield

    monkeypatch.setattr(hooks, "stop_verdict", lambda status, client: {"decision": "block", "reason": "open"})
    assert hooks.idle_verdict(Control()) == {"decision": "block", "reason": "open"}
    # The bound Work index with each submitted Work's court step (stop-gate).
    assert seen == [("GET", "/api/universal/work", {"projection": "stop-gate"})]
    assert hooks.idle_verdict(Gone()) == {}


GATE_JS = r"""
const readline=require('readline');
const actor='app:agent-session:runtime:'+'a'.repeat(32);
readline.createInterface({input:process.stdin}).on('line',line=>{
 const frame=JSON.parse(line),event=frame.event;
 const base={request_id:frame.request_id,session_id:event.session_id,tool_use_id:event.tool_use_id};
 if(event.hook_event_name==='Stop')process.stdout.write(JSON.stringify({...base,decision:'deny',error:'boom'})+'\n');
 else process.stdout.write(JSON.stringify({...base,decision:'allow',agent_session:actor,continued:false})+'\n');
});
"""


def test_a_failing_idle_check_never_poisons_the_session(tmp_path):
    gate = tmp_path / "gate.cjs"
    gate.write_text(GATE_JS, encoding="utf-8")
    _node(r"""import assert from 'node:assert/strict';import os from 'node:os';
import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[GATE],
 {selectedWorks:{ses_writer:'assembly-instance:1'},sessionLink:{node:process.execPath,stateDirectory:os.tmpdir(),connections:{ses_writer:['0123456789abcdef']}}});
const call=id=>run({session_id:'ses_writer',cwd:process.cwd(),tool_use_id:id,vendor:'opencode',hook_event_name:'PreToolUse',tool_name:'read',tool_input:{}});
assert.equal((await call('t-1')).allow,true);
assert.equal(await run.idle('ses_writer',process.cwd()),null,'a failed idle check reads as no open Work');
assert.equal((await call('t-2')).allow,true,'the next tool call is still allowed');
process.exit(0);
""".replace("GATE", json.dumps(str(gate))))


def test_concurrent_idles_of_one_session_send_a_single_prompt():
    _node(r"""import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const prompts=[];
const runner=async()=>({allow:true,toolOutput:'{}'});
runner.idle=()=>new Promise(r=>setTimeout(()=>r({decision:'block',reason:'Work W-12 is open.'}),100));
const client={session:{prompt:async request=>{prompts.push(request);return {};}}};
const hooks=await createOpenCodeGovernance({gateRunner:runner})({directory:process.cwd(),client});
const idle={event:{type:'session.idle',properties:{sessionID:'ses_writer'}}};
await Promise.all([hooks.event(idle),hooks.event(idle),hooks.event(idle)]);
assert.equal(prompts.length,1);
""")


def test_the_gate_answers_a_failing_stop_with_no_open_work(monkeypatch):
    if not GATE.is_file() or not (GATE_HOOKS / "pretooluse_validate.py").is_file():
        pytest.skip("the private OpenCode native gate is not on this machine")
    monkeypatch.syspath_prepend(str(GATE_HOOKS))
    spec = importlib.util.spec_from_file_location("opencode_native_gate_idle_fail", GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)

    class Broken(_Owner):
        def _check_identity(self):
            raise RuntimeError("owner identity unavailable")

    event = {"vendor": "opencode", "session_id": "ses_writer", "tool_use_id": "idle-1",
             "hook_event_name": "Stop", "cwd": os.getcwd()}
    assert gate.stop_answer(event, Broken()) == {"decision": "allow", "tool_output": "{}"}
