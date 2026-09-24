"""Synthetic OpenCode hooks and native owner custody; no live enrollment."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from dataclasses import replace

import pytest


def test_selected_work_custom_tool_pairs_native_execution_and_receipt():
    module=(Path(__file__).resolve().parents[1]/'nodelang/session_link/opencode-governance.mjs').as_uri()
    code='''import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const schema={string:()=>({optional(){return this;}}),object:()=>({passthrough(){return this;}})};
const factory=definition=>definition;factory.schema=schema;
const events=[];
const hooks=await createOpenCodeGovernance({selectedWorks:{ses_one:'assembly-instance:task'},workToolFactory:factory,gateRunner:async event=>{
 events.push(event);return {allow:true,toolOutput:'{"ok":true}'};
}})({directory:process.cwd()});
const input={sessionID:'ses_one',callID:'actual-native-call',tool:'archhub_work'};
const output={args:{operation:'native.work_assignment',arguments:{}}};
await hooks['tool.execute.before'](input,output);
assert.equal(typeof output.args._archhub_call,'string');
await assert.rejects(hooks.tool.archhub_work.execute(output.args,{sessionID:'ses_other',directory:process.cwd()}),/matching native admission/);
assert.equal(await hooks.tool.archhub_work.execute(output.args,{sessionID:'ses_one',directory:process.cwd()}),'{"ok":true}');
await assert.rejects(hooks.tool.archhub_work.execute(output.args,{sessionID:'ses_one',directory:process.cwd()}),/matching native admission/);
await hooks['tool.execute.after']({...input,args:output.args},{});
assert.deepEqual(events.map(e=>e.hook_event_name),['PreToolUse','NativeToolExecute','PostToolUse']);
assert.ok(events.every(e=>e.tool_use_id==='actual-native-call' && !('_archhub_call' in e.tool_input)));
const skipped={...input,callID:'native-skipped'},skippedArgs={args:{operation:'native.work_claim',arguments:{}}};
await hooks['tool.execute.before'](skipped,skippedArgs);
await hooks['tool.execute.after']({...skipped,args:skippedArgs.args},{});
assert.equal(events.at(-1).tool_response.status,'skipped');
await assert.rejects(hooks.tool.archhub_work.execute(skippedArgs.args,{sessionID:'ses_one',directory:process.cwd()}),/matching native admission/);
await assert.rejects(hooks['tool.execute.before']({...input,sessionID:'ses_unassigned'},{args:{operation:'native.work_claim',arguments:{}}}),/no configured Work/);
await hooks.dispose();
'''.replace('MODULE',json.dumps(module))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_selected_work_lost_execution_blocks_replay_and_dispose():
    module=(Path(__file__).resolve().parents[1]/'nodelang/session_link/opencode-governance.mjs').as_uri()
    code='''import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const factory=d=>d;factory.schema={string:()=>({optional(){return this;}}),object:()=>({passthrough(){return this;}})};
let executions=0;
const hooks=await createOpenCodeGovernance({selectedWorks:{ses_one:'assembly-instance:task'},workToolFactory:factory,gateRunner:async e=>{
 if(e.hook_event_name==='NativeToolExecute'){executions++;throw Error('reply lost');}return {allow:true};
}})({directory:process.cwd()});
const input={sessionID:'ses_one',callID:'one',tool:'archhub_work'},output={args:{operation:'native.work_claim',arguments:{}}};
await hooks['tool.execute.before'](input,output);
await assert.rejects(hooks.tool.archhub_work.execute(output.args,{sessionID:'ses_one',directory:process.cwd()}),/reply lost/);
await assert.rejects(hooks.tool.archhub_work.execute(output.args,{sessionID:'ses_one',directory:process.cwd()}),/matching native admission/);
await assert.rejects(hooks['tool.execute.before']({...input,callID:'two'},{args:{operation:'native.work_claim',arguments:{}}}),/unresolved/);
await assert.rejects(hooks.dispose(),/unresolved/);assert.equal(executions,1);
'''.replace('MODULE',json.dumps(module))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_unresolved_diagnostics_identify_call_without_blocking_other_sessions():
    module=(Path(__file__).resolve().parents[1]/'nodelang/session_link/opencode-governance.mjs').as_uri()
    code='''import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const events=[];
const hooks=await createOpenCodeGovernance({gateRunner:async e=>{
 events.push(e);
 if(e.session_id==='ses_blocked' && e.hook_event_name==='PostToolUse')throw Error('receipt lost');
 return {allow:true};
}})({directory:process.cwd()});
const args={filePath:'private-filename',content:'private-content'};
const a={sessionID:'ses_blocked',callID:'original',tool:'write'};
await hooks['tool.execute.before'](a,{args});
await assert.rejects(hooks['tool.execute.after']({...a,args},{}),/receipt lost/);
await assert.rejects(hooks['tool.execute.before']({...a,callID:'next'},{args}),e=>{
 assert.match(e.message,/"call":"original"/);
 assert.match(e.message,/"phase":"PostToolUse"/);
 assert.match(e.message,/"state":"uncertain"/);
 assert.doesNotMatch(e.message,/private-filename|private-content/);
 return true;
});
const b={sessionID:'ses_independent',callID:'original',tool:'write'};
await hooks['tool.execute.before'](b,{args});
await hooks['tool.execute.after']({...b,args},{});
assert.equal(events.length,4);
await assert.rejects(hooks.dispose(),/unresolved/);
'''.replace('MODULE',json.dumps(module))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr

from nodelang.native_agent_session import resolve_native_agent_identity
from nodelang.opencode_native_custody import OpenCodeProcessCustody, Process


def test_oversized_first_request_does_not_spawn_or_retain_child(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    marker=tmp_path/'spawned';worker=tmp_path/'must-not-start.mjs'
    worker.write_text("import fs from 'node:fs';fs.writeFileSync("+json.dumps(str(marker))+",'started');",encoding='utf-8')
    code='''import assert from 'node:assert/strict';import fs from 'node:fs';
import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
assert.throws(()=>run({session_id:'ses_large',cwd:process.cwd(),data:'x'.repeat(1024*1024)}),/input byte limit.*not delivered/);
assert.throws(()=>run({session_id:'invalid',cwd:process.cwd(),tool_use_id:'x'}),/input identity.*not delivered/);
await run.close();
await new Promise(r=>setTimeout(r,100));
assert.equal(fs.existsSync(MARKER),false);
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker))).replace('MARKER',json.dumps(str(marker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=5)
    assert result.returncode==0,result.stderr


def test_plugin_local_release_window_refusal_does_not_poison_next_pre_call(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'release-window.mjs'
    log=tmp_path/'calls.jsonl'
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const actor='app:agent-session:runtime:'+'a'.repeat(32);let sealed=false;
readline.createInterface({input:process.stdin}).on('line',line=>{
 if(sealed)return;
 const r=JSON.parse(line),e=r.event;
 fs.appendFileSync(LOG,JSON.stringify(e.tool_use_id)+'\\n');
 const reply={request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
  decision:'allow',agent_session:actor,continued:true};
 let output=JSON.stringify(reply)+'\\n';
 if(e.hook_event_name==='PostToolUse'){
  sealed=true;output+=JSON.stringify({kind:'released',released:true,
   last_request_id:r.request_id,session_id:e.session_id,agent_session:actor,release_id:'a'.repeat(32)})+'\\n';
  setTimeout(()=>process.exit(0),150);
 }
 process.stdout.write(output);
});'''.replace('LOG',json.dumps(str(log))),encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createOpenCodeGovernance} from MODULE;
const hooks=await createOpenCodeGovernance({gateCommand:process.execPath,gateArgs:[WORKER]})({directory:process.cwd()});
const call=id=>({sessionID:'ses_window',callID:id,tool:'read',args:{filePath:'fixture'}});
await hooks['tool.execute.before'](call('first'),{args:call('first').args});
await hooks['tool.execute.after'](call('first'),{});
await assert.rejects(()=>hooks['tool.execute.before'](call('local'),{args:call('local').args}),/tool not delivered/);
await new Promise(r=>setTimeout(r,250));
await hooks['tool.execute.before'](call('fresh'),{args:call('fresh').args});
await hooks['tool.execute.after'](call('fresh'),{});
await hooks.dispose();
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert [json.loads(s) for s in log.read_text().splitlines()]==['first','first','fresh','fresh']


def test_real_opencode_identity_required_not_runtime_alias():
    assert resolve_native_agent_identity({"OPENCODE_SESSION_ID":"ses_real123"}).runtime == "opencode"
    with pytest.raises(ValueError):
        resolve_native_agent_identity({"ARCHHUB_AGENT_RUNTIME":"opencode", "ARCHHUB_EXTERNAL_SESSION_ID":"ses_real123"})
    with pytest.raises(ValueError):
        resolve_native_agent_identity({"OPENCODE_SESSION_ID":"synthetic-user"})
    with pytest.raises(ValueError):
        resolve_native_agent_identity({"OPENCODE_SESSION_ID":"ses_real123", "ARCHHUB_AGENT_RUNTIME":"opencode", "ARCHHUB_EXTERNAL_SESSION_ID":"ses_other"})


def test_custody_retains_exact_native_parent_and_checks_session(tmp_path):
    expected=tmp_path / "Programs/@opencode-aidesktop/OpenCode.exe"
    own=Process(os.getpid(),1,987,str(tmp_path/"python.exe"),str(tmp_path),"ses_real123")
    parent=Process(987,2,986,str(expected.resolve()),str(tmp_path),"")
    rows={own.pid:own,parent.pid:parent};seen=[]
    custody=OpenCodeProcessCustody("ses_real123", environment={"LOCALAPPDATA":str(tmp_path)},
        process_reader=rows.__getitem__, session_reader=lambda *args:seen.append(args))
    assert seen==[(parent,"ses_real123",str(tmp_path))]
    rows[parent.pid]=replace(parent,created=3)
    with pytest.raises(RuntimeError,match="custody changed"):custody.check()
    rows[parent.pid]=replace(parent,executable=str(tmp_path/"foreign.exe"))
    with pytest.raises(RuntimeError,match="observed installed parent"):
        OpenCodeProcessCustody("ses_real123", environment={"LOCALAPPDATA":str(tmp_path)},
            process_reader=rows.__getitem__,session_reader=lambda *args:pytest.fail("foreign parent reached session read"))


@pytest.mark.parametrize("case",["success","deny","uncertain","receipt-deny","mismatch","unknown-tool"])
def test_hook_pairing_and_fail_closed(case):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    code=r'''import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const scenario=CASE,events=[];
const runner=async event=>{
 events.push(structuredClone(event));
 if(scenario==='uncertain')throw Error('uncertain');
 return {allow: !(scenario==='deny'||scenario==='receipt-deny'&&event.hook_event_name==='PostToolUse')};
};
const hooks=await createOpenCodeGovernance({gateRunner:runner})({directory:process.cwd()});
const input={sessionID:'ses_real123',callID:'call1',tool:'edit'};
const args={filePath:'test.txt',oldString:'old',newString:'\u2019\u0639\u{1f600}'};
if(scenario==='unknown-tool'){
 await assert.rejects(hooks['tool.execute.before']({...input,tool:'webfetch'},{args:{url:'https://example.com'}}),/no verified governance mapping: webfetch/);
 assert.equal(events.length,0);
}else if(scenario==='deny'||scenario==='uncertain'){
 await assert.rejects(hooks['tool.execute.before'](input,{args}));
 if(scenario==='uncertain')await assert.rejects(hooks['tool.execute.before']({...input,callID:'call2'},{args}),/unresolved/);
}else{
 await hooks['tool.execute.before'](input,{args});
 await assert.rejects(hooks['tool.execute.before']({...input,callID:'call2'},{args}),/unresolved/);
 if(scenario==='mismatch')await assert.rejects(hooks['tool.execute.after']({...input,args:{...args,newString:'different'}},{}),/differ/);
 else if(scenario==='receipt-deny'){
  await assert.rejects(hooks['tool.execute.after']({...input,args},{}),/receipt denied/);
  await assert.rejects(hooks.dispose(),/unresolved/);
 }else{
  await hooks['tool.execute.after']({...input,args},{});
  assert.equal(events.length,2);
  assert.deepEqual(events[0].tool_input,events[1].tool_input);
  assert.equal(events[0].tool_input.new_string,args.newString);
  assert.equal(events[0].session_id,input.sessionID);assert.equal(events[0].tool_use_id,input.callID);
  assert.equal(events[1].hook_event_name,'PostToolUse');
  await hooks.dispose();
 }
}
'''.replace("MODULE",json.dumps(module)).replace("CASE",json.dumps(case))
    result=subprocess.run([shutil.which("node"),"--input-type=module"],input=code,text=True,encoding="utf-8",capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize("mode",["good","nonzero","malformed","foreign"])
def test_persistent_native_gate_child_is_reused_and_never_retried(tmp_path,mode):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    log=tmp_path/"fixture-frames.jsonl"
    worker=tmp_path/"worker.mjs"
    worker.write_text("import fs from 'node:fs';import readline from 'node:readline';"+
        "const actor='app:agent-session:runtime:'+'a'.repeat(32);let last=null;"+
        "readline.createInterface({input:process.stdin}).on('line',line=>{"+
        "const r=JSON.parse(line);if(r.command==='release'){console.log(JSON.stringify({kind:'released',released:true,last_request_id:last,agent_session:actor,release_id:'a'.repeat(32),session_id:r.session_id}));process.exit(0);return;}last=r.request_id;"+
        "fs.appendFileSync("+json.dumps(str(log))+",JSON.stringify({pid:process.pid,session:r.event.session_id})+'\\n');"+
        ("process.exit(3);" if mode=="nonzero" else "console.log('bad-json');process.exit(0);" if mode=="malformed" else
         "console.log(JSON.stringify({agent_session:actor,continued:true,request_id:r.request_id,session_id:"+("'ses_wrong'" if mode=="foreign" else "r.event.session_id")+",tool_use_id:r.event.tool_use_id,decision:'allow'}));"+("process.exit(0);" if mode=="foreign" else ""))+"});",encoding="utf-8")
    code=("import assert from 'node:assert/strict';import {createNativeGateRunner} from "+json.dumps(module)+";"+
        "const run=createNativeGateRunner(process.execPath,["+json.dumps(str(worker))+"]);"+
        "const event={cwd:process.cwd(),session_id:'ses_real123',tool_use_id:'call1'};"+
        ("assert.equal((await run(event)).allow,true);assert.equal((await run({...event,tool_use_id:'call2'})).allow,true);await run.close();" if mode=="good" else
         "await assert.rejects(run(event));await new Promise(r=>setTimeout(r,50));assert.throws(()=>run({...event,tool_use_id:'call2'}),/no duplicate enrollment/);await run.close();"))
    result=subprocess.run([shutil.which("node"),"--input-type=module"],input=code,text=True,encoding="utf-8",capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    rows=[json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows)==(2 if mode=="good" else 1)
    assert len({row["pid"] for row in rows})==1


def test_parallel_read_hooks_complete_without_waiting_for_all_afters():
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    code='''import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const events=[],runner=async e=>{events.push(e);return {allow:true}};
const hooks=await createOpenCodeGovernance({gateRunner:runner})({directory:process.cwd()});
const a={sessionID:'ses_reads',callID:'a',tool:'read'},b={...a,callID:'b'},w={...a,callID:'w',tool:'write'};
const args={filePath:'fixture.txt'};
await Promise.all([hooks['tool.execute.before'](a,{args}),hooks['tool.execute.before'](b,{args})]);
assert.equal(events.length,2);
await assert.rejects(hooks['tool.execute.before'](w,{args:{...args,content:'x'}}),/unresolved/);
await hooks['tool.execute.after']({...b,args},{});
await assert.rejects(hooks['tool.execute.before'](w,{args:{...args,content:'x'}}),/unresolved/);
await hooks['tool.execute.after']({...a,args},{});
await hooks['tool.execute.before'](w,{args:{...args,content:'x'}});
await assert.rejects(hooks['tool.execute.before']({...a,callID:'c'},{args}),/unresolved/);
await hooks['tool.execute.after']({...w,args:{...args,content:'x'}},{});
await hooks.dispose();
'''.replace('MODULE',json.dumps(module))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_clean_release_reclaims_slots_and_same_session_continues(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'release-worker.mjs'
    worker.write_text('''import readline from 'node:readline';
const actor='app:agent-session:runtime:'+'a'.repeat(32);let last=null;
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line);
 if(r.command==='release'){
  console.log(JSON.stringify({kind:'released',released:true,last_request_id:last,agent_session:actor,release_id:'a'.repeat(32),session_id:r.session_id}));
  process.exit(0);
 }
 last=r.request_id;console.log(JSON.stringify({request_id:r.request_id,session_id:r.event.session_id,tool_use_id:r.event.tool_use_id,
  decision:'allow',agent_session:actor,continued:true}));
});''',encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
for(let cycle=0;cycle<2;cycle++){
 for(let i=0;i<4;i++){
  const event={session_id:'ses_'+i,cwd:process.cwd(),tool_use_id:'a'};
  const replies=await Promise.all([run(event),run({...event,tool_use_id:'b'})]);
  assert(replies.every(r=>r.allow));
 }
 assert.throws(()=>run({session_id:'ses_extra',cwd:process.cwd(),tool_use_id:'x'}),/capacity/);
 await run.close();
}
assert((await run({session_id:'ses_extra',cwd:process.cwd(),tool_use_id:'x'})).allow);
await run.close();
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_confirmed_crashes_free_live_slots_but_quarantine_exact_sessions(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'crash-worker.mjs'
    worker.write_text("process.stdin.once('data',()=>process.exit(3));",encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
for(let i=0;i<6;i++){
 const event={session_id:'ses_crash'+i,cwd:process.cwd(),tool_use_id:'a'};
 await assert.rejects(run(event));
 await new Promise(resolve=>setTimeout(resolve,30));
 // No graph actor was ever confirmed: nothing to reconcile, no probe, no re-enrollment.
 assert.throws(()=>run(event),/quarantined; no duplicate enrollment; reconcile no recorded graph actor.*tool not delivered/);
}
await run.close();
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_release_watermark_proves_racing_request_not_delivered_without_replay(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    log=tmp_path/'evaluated.jsonl';worker=tmp_path/'idle-race-worker.mjs'
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const actor='app:agent-session:runtime:'+'a'.repeat(32);let last=null,sid=null;
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line);
 if(last!==null){
  console.log(JSON.stringify({kind:'released',released:true,last_request_id:last,session_id:sid,
   agent_session:actor,release_id:'a'.repeat(32)}));process.exit(0);return;
 }
 last=r.request_id;sid=r.event.session_id;
 fs.appendFileSync(LOG,JSON.stringify(r.event.tool_use_id)+'\\n');
 console.log(JSON.stringify({request_id:last,session_id:sid,tool_use_id:r.event.tool_use_id,
  decision:'allow',agent_session:actor,continued:true}));
});'''.replace('LOG',json.dumps(str(log))),encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
const event={session_id:'ses_race',cwd:process.cwd(),tool_use_id:'first'};
assert((await run(event)).allow);
assert.deepEqual(await run({...event,tool_use_id:'racing'}),{allow:false,notDelivered:true});
assert((await run({...event,tool_use_id:'fresh'})).allow);
await run.close();
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert [json.loads(s) for s in log.read_text().splitlines()]==['first','fresh']

@pytest.mark.parametrize('changed_actor', [False, True])
def test_recovery_pins_original_actor_in_worker_and_reply(tmp_path, changed_actor):
    module=(Path(__file__).resolve().parents[1]/'nodelang/session_link/opencode-governance.mjs').as_uri()
    worker=tmp_path/'conditional-owner.mjs'
    actor='app:agent-session:runtime:'+'a'*32
    worker.write_text('''import assert from 'node:assert/strict';import readline from 'node:readline';
assert.equal(process.env.ARCHHUB_EXPECTED_AGENT_SESSION,ACTOR);
let last=null;
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line);
 if(r.command==='release'){
  console.log(JSON.stringify({kind:'released',released:true,last_request_id:last,agent_session:ACTOR,release_id:'a'.repeat(32),session_id:r.session_id}));process.exit(0);return;
 }
 last=r.request_id;
 console.log(JSON.stringify({request_id:r.request_id,session_id:r.event.session_id,tool_use_id:r.event.tool_use_id,
 agent_session:REPLY_ACTOR,continued:true,decision:'allow'}));
 if(CHANGED)setTimeout(()=>process.exit(2),20);
});'''.replace('REPLY_ACTOR',json.dumps('app:agent-session:runtime:'+'b'*32 if changed_actor else actor)).replace('ACTOR',json.dumps(actor)).replace('CHANGED',json.dumps(changed_actor)),encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER],{expectedSessions:{ses_existing:ACTOR}});
const request={session_id:'ses_existing',cwd:process.cwd(),tool_use_id:'call1'};
if(CHANGED){await assert.rejects(run(request),/identity changed/);await new Promise(r=>setTimeout(r,80));}
else {assert.equal((await run(request)).allow,true);await run.close();}
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker))).replace('ACTOR',json.dumps(actor)).replace('CHANGED',json.dumps(changed_actor))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr

def test_skill_uses_read_admission_and_retains_native_name_validation():
    module=(Path(__file__).resolve().parents[1]/'nodelang/session_link/opencode-governance.mjs').as_uri()
    code='''import assert from 'node:assert/strict';import {createOpenCodeGovernance} from MODULE;
const events=[];
const hooks=await createOpenCodeGovernance({gateRunner:async e=>{events.push(e);return {allow:true};}})({directory:process.cwd()});
const input={sessionID:'ses_skill',callID:'load',tool:'skill'},args={name:'session-link'};
await hooks['tool.execute.before'](input,{args});
await hooks['tool.execute.after']({...input,args},{});
assert.equal(events.length,2);assert.equal(events[0].tool_name,'skill');
assert.deepEqual(events[0].tool_input,args);
for(const bad of [{name:''},{name:'x',command:'run'},{name:123}])
 await assert.rejects(hooks['tool.execute.before']({...input,callID:'invalid'},{args:bad}),/skill arguments/);
assert.equal(events.length,2);
await hooks.dispose();
'''.replace('MODULE',json.dumps(module))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


# --- Courts: quarantine reconciliation without restart; shell mapping ---
_ACTOR = 'app:agent-session:runtime:' + 'a' * 32
_LANE = 'C:/lanes/70.HANDOFFS/repair/work/opencode-governance'


def _reconcile_worker(tmp_path, outcome, *, ack=False):
    """A native gate stand-in: serves requests, crashes after 'crash', answers --reconcile."""
    log = tmp_path / 'spawns.jsonl'
    worker = tmp_path / 'reconcile-worker.mjs'
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const actor=ACTOR;
fs.appendFileSync(LOG,JSON.stringify({argv:process.argv.slice(2),expected:process.env.ARCHHUB_EXPECTED_AGENT_SESSION||'',
 lane:process.env.ARCHHUB_ADMITTED_LANE||''})+'\\n');
if(process.argv.includes('--reconcile')){
 console.log(JSON.stringify({kind:'reconciled',session_id:process.env.OPENCODE_SESSION_ID,
  agent_session:process.env.ARCHHUB_EXPECTED_AGENT_SESSION,outcome:OUTCOME,reason:REASON}));
 process.exit(0);
}
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line),e=r.event;
 let out=JSON.stringify({request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
  decision:'allow',agent_session:actor,continued:true})+'\\n';
 if(e.tool_use_id==='crash'){
  if(ACK)out+=JSON.stringify({kind:'released',released:true,last_request_id:r.request_id,session_id:e.session_id,
   agent_session:actor,release_id:'c'.repeat(32)})+'\\n';
  setTimeout(()=>process.exit(3),40);
 }
 process.stdout.write(out);
});'''.replace('ACTOR', json.dumps(_ACTOR)).replace('LOG', json.dumps(str(log)))
       .replace('OUTCOME', json.dumps(outcome)).replace('ACK', 'true' if ack else 'false')
       .replace('REASON', json.dumps('owner holds no binding' if outcome == 'released'
                                     else 'owner binding still retained; reconcile after its lease or release')),
       encoding='utf-8')
    return worker, log


def _run_node(code, timeout=15):
    result = subprocess.run([shutil.which('node'), '--input-type=module'], input=code, text=True,
                            capture_output=True, timeout=timeout)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('outcome', ['released', 'unknown'])
def test_uncertain_release_reconciles_only_when_owner_confirms(tmp_path, outcome):
    module = (Path(__file__).resolve().parents[1] / 'nodelang/session_link/opencode-governance.mjs').as_uri()
    worker, log = _reconcile_worker(tmp_path, outcome)
    code = '''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER],{expectedSessions:{ses_q:ACTOR},laneFolders:{ses_q:LANE}});
const call=id=>({session_id:'ses_q',cwd:process.cwd(),tool_use_id:id});
assert((await run(call('crash'))).allow);
await new Promise(r=>setTimeout(r,300));
if(OUTCOME==='released'){
 assert((await run(call('after'))).allow);
 assert((await run(call('again'))).allow);
}else{
 for(const id of ['after','again'])await assert.rejects(run(call(id)),e=>{
  assert.match(e.message,/native session quarantined; no duplicate enrollment; reconcile owner binding still retained/);
  assert.match(e.message,/coordinator: .* --reconcile-status ses_q app:agent-session:runtime:a{32}/);
  assert.match(e.message,/tool not delivered/);return true;});
}
await run.close().catch(()=>{});
'''.replace('MODULE', json.dumps(module)).replace('WORKER', json.dumps(str(worker))) \
   .replace('ACTOR', json.dumps(_ACTOR)).replace('LANE', json.dumps(_LANE)).replace('OUTCOME', json.dumps(outcome))
    _run_node(code)
    spawns = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    kinds = ['probe' if '--reconcile' in s['argv'] else 'worker' for s in spawns]
    # Every spawn pins the recorded actor: continuation, never a fresh enrollment.
    assert all(s['expected'] == _ACTOR for s in spawns)
    assert all(s['lane'] == _LANE for s in spawns if '--reconcile' not in s['argv'])
    if outcome == 'released':
        assert kinds == ['worker', 'probe', 'worker']
    else:
        assert kinds == ['worker', 'probe']  # second refusal reuses the verdict; no respawn


def test_release_ack_reconciles_without_probe(tmp_path):
    module = (Path(__file__).resolve().parents[1] / 'nodelang/session_link/opencode-governance.mjs').as_uri()
    worker, log = _reconcile_worker(tmp_path, 'unknown', ack=True)
    code = '''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER],{expectedSessions:{ses_q:ACTOR}});
const call=id=>({session_id:'ses_q',cwd:process.cwd(),tool_use_id:id});
assert((await run(call('crash'))).allow);
await new Promise(r=>setTimeout(r,300));
assert((await run(call('after'))).allow);
await run.close().catch(()=>{});
'''.replace('MODULE', json.dumps(module)).replace('WORKER', json.dumps(str(worker))).replace('ACTOR', json.dumps(_ACTOR))
    _run_node(code)
    spawns = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert ['--reconcile' in s['argv'] for s in spawns] == [False, False]


def test_lane_folders_must_be_trusted_absolute_paths():
    module = (Path(__file__).resolve().parents[1] / 'nodelang/session_link/opencode-governance.mjs').as_uri()
    code = '''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
assert.throws(()=>createNativeGateRunner(process.execPath,[],{laneFolders:{ses_q:'relative/lane'}}),/trusted lane folders required/);
assert.throws(()=>createNativeGateRunner(process.execPath,[],{laneFolders:{bad:'C:/lane'}}),/trusted lane folders required/);
'''.replace('MODULE', json.dumps(module))
    _run_node(code)


def test_plugin_uncertain_records_settle_on_owner_verdict_and_shell_maps_to_gate():
    module = (Path(__file__).resolve().parents[1] / 'nodelang/session_link/opencode-governance.mjs').as_uri()
    code = '''import assert from 'node:assert/strict';import {createOpenCodeGovernance} from MODULE;
const factory=d=>d;factory.schema={string:()=>({optional(){return this;}}),object:()=>({passthrough(){return this;}})};
const events=[],reconciles=[];
let verdict={outcome:'unknown',reason:'1 unreceipted permit(s) need settlement',command:'py gate.py --reconcile-status ses_u actor'};
const runner=async e=>{
 events.push(e);
 if(e.tool_use_id==='lost'||e.tool_use_id==='work-lost')throw Error('reply lost');
 if(e.tool_input?.command==='rm x')return {allow:false,reason:'ArchHub shell gate DENIED: [SHELL-0] only allowlisted commands run'};
 return {allow:true};
};
runner.reconcile=async s=>{reconciles.push(s);return verdict;};
const hooks=await createOpenCodeGovernance({gateRunner:runner,selectedWorks:{ses_w:'assembly-instance:task'},workToolFactory:factory})({directory:process.cwd()});
const read=(s,id)=>[{sessionID:s,callID:id,tool:'read'},{args:{filePath:'fixture'}}];
await assert.rejects(hooks['tool.execute.before'](...read('ses_u','lost')),/reply lost/);
await assert.rejects(hooks['tool.execute.before'](...read('ses_u','next')),
 /earlier tool outcome unresolved; reconcile 1 unreceipted permit\\(s\\) need settlement; coordinator: py gate.py --reconcile-status/);
verdict={outcome:'released',reason:'owner holds no binding',command:'x'};
await hooks['tool.execute.before'](...read('ses_u','next2'));
await hooks['tool.execute.after']({sessionID:'ses_u',callID:'next2',tool:'read',args:{filePath:'fixture'}},{});
assert.deepEqual(reconciles,['ses_u','ses_u']);
// Work execution effects are outside the permit ledger: never reconciled away.
await assert.rejects(hooks['tool.execute.before']({sessionID:'ses_w',callID:'work-lost',tool:'archhub_work'},{args:{operation:'native.work_claim',arguments:{}}}),/reply lost/);
await assert.rejects(hooks['tool.execute.before'](...read('ses_w','r')),/earlier tool admission or receipt unresolved/);
assert.deepEqual(reconciles,['ses_u','ses_u']);
// Shell maps to the governed Bash admission; refusals carry the quoted rule.
const bash={sessionID:'ses_s',callID:'sh1',tool:'bash'},bashArgs={command:'git status',workdir:'C:/w',description:'status',timeout:1000};
await hooks['tool.execute.before'](bash,{args:bashArgs});
assert.deepEqual(events.at(-1).tool_name,'Bash');
assert.deepEqual(events.at(-1).tool_input,{command:'git status',workdir:'C:/w'});
await hooks['tool.execute.after']({...bash,args:bashArgs},{});
assert.equal(events.at(-1).hook_event_name,'PostToolUse');
await assert.rejects(hooks['tool.execute.before']({sessionID:'ses_s',callID:'sh2',tool:'powershell'},{args:{command:'rm x'}}),
 /prewrite admission denied: ArchHub shell gate DENIED: \\[SHELL-0\\] only allowlisted commands run/);
await assert.rejects(hooks['tool.execute.before']({sessionID:'ses_s',callID:'sh3',tool:'bash'},{args:{command:''}}),/native shell arguments unavailable/);
await assert.rejects(hooks['tool.execute.before']({sessionID:'ses_s',callID:'wf',tool:'webfetch'},{args:{url:'x'}}),/no verified governance mapping: webfetch/);
'''.replace('MODULE', json.dumps(module))
    _run_node(code)


@pytest.mark.parametrize('tool,args', [
    ('bash', {'command': 'git status'}),
    ('powershell', {'command': 'git status'}),
])
def test_uncertain_shell_call_stays_refused_after_owner_reports_released(tool, args):
    # Shell carries no graph permit: a released owner with zero unreceipted
    # permits proves nothing about it, so the record is never settled away.
    module = (Path(__file__).resolve().parents[1] / 'nodelang/session_link/opencode-governance.mjs').as_uri()
    code = '''import assert from 'node:assert/strict';import {createOpenCodeGovernance} from MODULE;
const reconciles=[];
const runner=async e=>{if(e.tool_use_id==='lost-shell'&&e.hook_event_name==='PostToolUse'||e.tool_use_id==='lost-write')throw Error('reply lost');return {allow:true};};
runner.reconcile=async s=>{reconciles.push(s);return {outcome:'released',reason:'owner holds no binding',command:'x'};};
const hooks=await createOpenCodeGovernance({gateRunner:runner})({directory:process.cwd()});
const shell={sessionID:'ses_sh',callID:'lost-shell',tool:TOOL};
await hooks['tool.execute.before'](shell,{args:ARGS});
await assert.rejects(hooks['tool.execute.after']({...shell,args:ARGS},{}),/reply lost/);
const read=id=>[{sessionID:'ses_sh',callID:id,tool:'read'},{args:{filePath:'fixture'}}];
for(const id of ['r1','r2'])await assert.rejects(hooks['tool.execute.before'](...read(id)),e=>{
 assert.match(e.message,/earlier tool admission or receipt unresolved/);
 assert.match(e.message,/"call":"lost-shell"/);assert.match(e.message,/"state":"uncertain"/);return true;});
assert.deepEqual(reconciles,[]);
// The ledger settles an uncertain write on the same verdict; a later uncertain
// shell call in that session still stays retained.
const write={sessionID:'ses_sh2',callID:'lost-write',tool:'write'},wargs={filePath:'f',content:'c'};
await assert.rejects(hooks['tool.execute.before'](write,{args:wargs}),/reply lost/);
const shell2={sessionID:'ses_sh2',callID:'lost-shell',tool:TOOL};
await hooks['tool.execute.before'](shell2,{args:ARGS});
assert.deepEqual(reconciles,['ses_sh2']);
await assert.rejects(hooks['tool.execute.after']({...shell2,args:ARGS},{}),/reply lost/);
await assert.rejects(hooks['tool.execute.before']({...shell2,callID:'next'},{args:ARGS}),/"call":"lost-shell"/);
assert.deepEqual(reconciles,['ses_sh2']);
await assert.rejects(hooks.dispose(),/unresolved/);
'''.replace('MODULE', json.dumps(module)).replace('TOOL', json.dumps(tool)).replace('ARGS', json.dumps(args))
    _run_node(code)
