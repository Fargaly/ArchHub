"""Only a PROVEN-unadmitted refusal is a clean denial; every other error keeps custody.

The native owner is a real child process scripted per spawn. The gate marks a reply
admitted:false only when its owner never sent an enrollment request (no client), so no
permit or effect can exist. Such a refusal denies with its reason; a continuation whose
worker never bound retires through the existing custody reconciliation and a fresh
worker continues the actor. Any error from a bound owner, an execution or receipt
error, a missing decision, or a reply naming another actor still aborts (retained).

Known gap, stated not hidden: the real gate never reconnects a worker whose first
connect failed, so a brand-new session (no recorded actor) keeps being denied with the
reason until that worker ends. It is no longer quarantined, but it does not recover.
"""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "nodelang/session_link/opencode-governance.mjs").as_uri()
ACTOR = "app:agent-session:runtime:" + "a" * 32

GATE = r"""
const fs=require('fs'),readline=require('readline');
const args=process.argv.slice(2).filter(a=>a!=='--reconcile');
const [scriptPath,counter]=args;
const actor='app:agent-session:runtime:'+'a'.repeat(32);
if(process.argv.includes('--reconcile')){
 process.stdout.write(JSON.stringify({kind:'reconciled',session_id:process.env.OPENCODE_SESSION_ID,
  agent_session:process.env.ARCHHUB_EXPECTED_AGENT_SESSION,outcome:'released',reason:'owner holds no binding'})+'\n');
 process.exit(0);
}
const spawn=fs.existsSync(counter)?Number(fs.readFileSync(counter,'utf8')):0;fs.writeFileSync(counter,String(spawn+1));
const plan=JSON.parse(fs.readFileSync(scriptPath,'utf8'))[spawn]||[];
let frame=0;
readline.createInterface({input:process.stdin}).on('line',line=>{
 const f=JSON.parse(line),event=f.event,kind=plan[frame++]||'allow';
 const base={request_id:f.request_id,session_id:event.session_id,tool_use_id:event.tool_use_id};
 const bound={agent_session:actor,continued:true};
 const error={decision:'deny',error:'native admission or receipt unavailable; no retry',
  reason:'MachineTransportError: an active persistent installed owner is required'};
 const other='app:agent-session:runtime:'+'b'.repeat(32);
 const reply={allow:{...base,decision:'allow',...bound},
  unbound:{...base,...error,admitted:false},
  error:{...base,...error},
  nodecision:{...base,admitted:false,error:'x'},
  wrongactor:{...base,decision:'allow',agent_session:other,continued:true},
  unboundwrongactor:{...base,...error,admitted:false,agent_session:other}}[kind];
 process.stdout.write(JSON.stringify(reply)+'\n');
}).on('close',()=>process.exit(0));
"""

HEAD = r"""import assert from 'node:assert/strict';
import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[GATE,PLAN,COUNTER],{expectedSessions:LINEAGE});
const call=(id,phase='PreToolUse')=>run({session_id:'ses_writer',cwd:process.cwd(),tool_use_id:id,vendor:'opencode',
  hook_event_name:phase,tool_name:'archhub_work',tool_input:{operation:'native.work_current',arguments:{}}});
const settle=()=>new Promise(r=>setTimeout(r,500));
"""


def _run(tmp_path, spawns, lineage, body):
    gate = tmp_path / "gate.cjs"
    gate.write_text(GATE, encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(spawns), encoding="utf-8")
    script = (HEAD + body + "\nprocess.exit(0);\n")
    script = (script.replace("MODULE", json.dumps(MODULE)).replace("GATE", json.dumps(str(gate)))
              .replace("PLAN", json.dumps(str(plan))).replace("COUNTER", json.dumps(str(tmp_path / "spawns")))
              .replace("LINEAGE", json.dumps({"ses_writer": ACTOR} if lineage else {})))
    result = subprocess.run([shutil.which("node"), "--input-type=module"], input=script, text=True,
                            encoding="utf-8", capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr[-3000:]


def test_a_proven_unbound_refusal_denies_with_its_reason_and_the_continuation_recovers(tmp_path):
    _run(tmp_path, [["unbound"], ["allow"]], True, r"""
const first=await call('c-1');
assert.equal(first.allow,false);
assert.match(first.reason,/native owner could not decide: .*active persistent installed owner is required/);
await settle();
assert.equal((await call('c-2')).allow,true,'custody reconciled, then a fresh worker continues the actor');
""")


def test_a_brand_new_session_is_denied_with_its_reason_not_quarantined(tmp_path):
    _run(tmp_path, [["unbound", "unbound"]], False, r"""
assert.match((await call('c-1')).reason,/active persistent installed owner is required/);
const again=await call('c-2');
assert.equal(again.allow,false,'the real gate never reconnects this worker: still denied (known gap)');
assert.match(again.reason,/native owner could not decide/);
""")


def test_a_bound_owner_that_fails_after_admission_keeps_custody(tmp_path):
    _run(tmp_path, [["allow", "error"]], True, r"""
assert.equal((await call('c-1')).allow,true);
await assert.rejects(call('c-2'),/native reply identity or outcome unavailable/);
""")


def test_an_execution_error_stays_uncertain(tmp_path):
    _run(tmp_path, [["allow", "error"]], True, r"""
assert.equal((await call('c-1')).allow,true);
await assert.rejects(call('c-1','NativeToolExecute'),/native reply identity or outcome unavailable/);
""")


def test_a_reply_naming_another_actor_aborts_even_as_an_unbound_refusal(tmp_path):
    _run(tmp_path, [["wrongactor"]], True, r"""
await assert.rejects(call('c-1'),/native graph identity changed/);
""")
    fresh = tmp_path / "second"
    fresh.mkdir()
    _run(fresh, [["unboundwrongactor"]], True, r"""
await assert.rejects(call('c-1'),/native graph identity changed/);
""")


def test_a_missing_decision_is_a_protocol_failure_not_a_denial(tmp_path):
    _run(tmp_path, [["nodecision"]], True, r"""
await assert.rejects(call('c-1'),/native reply identity or outcome unavailable/);
""")
