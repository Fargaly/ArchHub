"""Synthetic OpenCode hooks and native owner custody; no live enrollment."""
import json
import os
import sys
from pathlib import Path
import importlib.util
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
def test_persistent_native_gate_child_is_reused_and_actorless_failures_stay_quarantined(tmp_path,mode):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    log=tmp_path/"fixture-frames.jsonl"
    worker=tmp_path/"worker.mjs"
    marker=tmp_path/"first-failed"
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const actor='app:agent-session:runtime:'+'a'.repeat(32);let last=null;
const mode=MODE,marker=MARKER;
const failOnce=mode!=='good'&&!fs.existsSync(marker);
if(failOnce)fs.writeFileSync(marker,'1');
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line);
 if(r.command==='release'){
  console.log(JSON.stringify({kind:'released',released:true,last_request_id:last,agent_session:actor,release_id:'a'.repeat(32),session_id:r.session_id}));
  process.exit(0);return;
 }
 last=r.request_id;
 fs.appendFileSync(LOG,JSON.stringify({pid:process.pid,session:r.event.session_id})+'\\n');
 if(failOnce&&mode==='nonzero'){process.stderr.write('accepted\\n');process.exit(3);return;}
 if(failOnce&&mode==='malformed'){console.log('bad-json');process.exit(0);return;}
 console.log(JSON.stringify({agent_session:actor,continued:true,request_id:r.request_id,
  session_id:failOnce&&mode==='foreign'?'ses_wrong':r.event.session_id,tool_use_id:r.event.tool_use_id,decision:'allow'}));
 if(failOnce&&mode==='foreign')process.exit(0);
});'''.replace('MODE',json.dumps(mode)).replace('MARKER',json.dumps(str(marker))).replace('LOG',json.dumps(str(log))), encoding="utf-8")
    code=("import assert from 'node:assert/strict';import {createNativeGateRunner} from "+json.dumps(module)+";"+
        "const run=createNativeGateRunner(process.execPath,["+json.dumps(str(worker))+"]);"+
        "const event={cwd:process.cwd(),session_id:'ses_real123',tool_use_id:'call1'};"+
        ("assert.equal((await run(event)).allow,true);assert.equal((await run({...event,tool_use_id:'call2'})).allow,true);await run.close();" if mode=="good" else
         "await assert.rejects(run(event));await new Promise(r=>setTimeout(r,50));assert.throws(()=>run({...event,tool_use_id:'call2'}),/quarantined; no duplicate enrollment/);await run.close().catch(()=>{});"))
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


def test_actorless_owner_close_without_positive_no_enrollment_stays_quarantined(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'crash-then-allow-worker.mjs'
    marker=tmp_path/'first-done'
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const actor='app:agent-session:runtime:'+'a'.repeat(32);
if(!fs.existsSync(MARKER)){
 fs.writeFileSync(MARKER,'1');
 process.exit(3);
}else{
 let last=null;
 readline.createInterface({input:process.stdin}).on('line',line=>{
  const r=JSON.parse(line),e=r.event;
  if(r.command==='release'){
   console.log(JSON.stringify({kind:'released',released:true,last_request_id:last,
    session_id:r.session_id,agent_session:actor,release_id:'a'.repeat(32)}));
   process.exit(0);return;
  }
  last=r.request_id;
  console.log(JSON.stringify({request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
   decision:'allow',agent_session:actor,continued:true}));
 });
}'''.replace('MARKER',json.dumps(str(marker))),encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
const event={session_id:'ses_crash',cwd:process.cwd(),tool_use_id:'a'};
await assert.rejects(run(event),/retained outcome requires reconciliation|native release uncertain|prior native request unresolved/);
await new Promise(resolve=>setTimeout(resolve,30));
assert.throws(()=>run({...event,tool_use_id:'fresh'}),/quarantined; no duplicate enrollment/);
await run.close().catch(()=>{});
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_actorless_pre_admission_refusal_without_never_bound_stays_quarantined(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'refuse-then-allow-worker.mjs'
    marker=tmp_path/'refused'
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
const actor='app:agent-session:runtime:'+'a'.repeat(32);
let last=null;
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line),e=r.event;
 if(r.command==='release'){
  console.log(JSON.stringify({kind:'released',released:true,last_request_id:last,
   session_id:r.session_id,agent_session:actor,release_id:'a'.repeat(32)}));
  process.exit(0);return;
 }
 if(!fs.existsSync(MARKER)){
  fs.writeFileSync(MARKER,'1');
  console.log(JSON.stringify({request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
   admitted:false,decision:'deny',error:'active persistent installed owner is required (stopped)'}));
  setTimeout(()=>process.exit(3),20);return;
 }
 last=r.request_id;
 console.log(JSON.stringify({request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
  decision:'allow',agent_session:actor,continued:true}));
});'''.replace('MARKER',json.dumps(str(marker))),encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
const event={session_id:'ses_denied',cwd:process.cwd(),tool_use_id:'a'};
await assert.rejects(run(event),/native reply identity or outcome unavailable|retained outcome requires reconciliation|native release uncertain/);
await new Promise(resolve=>setTimeout(resolve,80));
assert.throws(()=>run({...event,tool_use_id:'fresh'}),/quarantined; no duplicate enrollment/);
await run.close().catch(()=>{});
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_never_bound_pre_admission_refusal_can_reenroll_only_once(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'refuse-twice-worker.mjs'
    marker=tmp_path/'count.txt'
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
let count=Number(fs.existsSync(MARKER)?fs.readFileSync(MARKER,'utf8'):'0');
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line),e=r.event;
  if(count<2){
   count++;fs.writeFileSync(MARKER,String(count));
   console.log(JSON.stringify({request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
   admitted:false,decision:'deny',never_bound:true,error:'active persistent installed owner is required (stopped)'}));
  setTimeout(()=>process.exit(3),20);return;
 }
 const actor='app:agent-session:runtime:'+'a'.repeat(32);
 console.log(JSON.stringify({request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
  decision:'allow',agent_session:actor,continued:true}));
});'''.replace('MARKER',json.dumps(str(marker))),encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
const event={session_id:'ses_once',cwd:process.cwd(),tool_use_id:'a'};
assert.equal((await run(event)).allow,false);
await new Promise(resolve=>setTimeout(resolve,80));
assert.equal((await run({...event,tool_use_id:'b'})).allow,false);
await new Promise(resolve=>setTimeout(resolve,80));
assert.throws(()=>run({...event,tool_use_id:'c'}),/quarantined; no duplicate enrollment/);
await run.close().catch(()=>{});
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_expected_actor_pre_admission_refusal_reconciles_not_fresh(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'expected-refusal-worker.mjs'
    log=tmp_path/'spawns.jsonl'
    actor='app:agent-session:runtime:'+'a'*32
    worker.write_text('''import fs from 'node:fs';import readline from 'node:readline';
fs.appendFileSync(LOG,JSON.stringify({argv:process.argv.slice(2),expected:process.env.ARCHHUB_EXPECTED_AGENT_SESSION||''})+'\\n');
if(process.argv.includes('--reconcile')){
 console.log(JSON.stringify({kind:'reconciled',session_id:process.env.OPENCODE_SESSION_ID,
  agent_session:process.env.ARCHHUB_EXPECTED_AGENT_SESSION,outcome:'unknown',reason:'owner binding still retained'}));
 process.exit(0);
}
readline.createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line),e=r.event;
 console.log(JSON.stringify({request_id:r.request_id,session_id:e.session_id,tool_use_id:e.tool_use_id,
  admitted:false,decision:'deny',error:'active persistent installed owner is required (stopped)'}));
 setTimeout(()=>process.exit(3),20);
});'''.replace('LOG',json.dumps(str(log))),encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER],{expectedSessions:{ses_existing:ACTOR}});
const event={session_id:'ses_existing',cwd:process.cwd(),tool_use_id:'a'};
assert.equal((await run(event)).allow,false);
await new Promise(resolve=>setTimeout(resolve,100));
await assert.rejects(run({...event,tool_use_id:'fresh'}),/native session quarantined; no duplicate enrollment; reconcile owner binding still retained/);
await run.close().catch(()=>{});
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker))).replace('ACTOR',json.dumps(actor))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    spawns=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert ['--reconcile' in s['argv'] for s in spawns] == [False, True]
    assert all(s['expected'] == actor for s in spawns)


def test_stdin_error_before_write_clears_for_fresh_enrollment():
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    code='''import assert from 'node:assert/strict';import fs from 'node:fs';import {EventEmitter} from 'node:events';
let spawns=0,writes=0;
globalThis.__fakeSpawn=()=>{
 spawns++;
 const child=new EventEmitter();
 child.stdout=new EventEmitter();child.stderr=new EventEmitter();child.stdin=new EventEmitter();
 if(spawns===1){
  child.stdin.writable=false;
  child.stdin.write=()=>{writes++;throw new Error('closed before write');};
  setTimeout(()=>child.emit('close',3),20);
 }else{
  child.stdin.writable=true;
  child.stdin.write=payload=>{
   writes++;
   const r=JSON.parse(String(payload).trim());
   const actor='app:agent-session:runtime:'+'a'.repeat(32);
   if(r.command==='release'){
    child.stdout.emit('data',Buffer.from(JSON.stringify({kind:'released',released:true,last_request_id:'2',
     session_id:r.session_id,agent_session:actor,release_id:'a'.repeat(32)})+'\\n'));
    setTimeout(()=>child.emit('close',0),0);return;
   }
   const e=r.event;
   child.stdout.emit('data',Buffer.from(JSON.stringify({request_id:r.request_id,session_id:e.session_id,
    tool_use_id:e.tool_use_id,decision:'allow',agent_session:actor,continued:true})+'\\n'));
  };
 }
 return child;
};
const source=fs.readFileSync(new URL(MODULE),'utf8').replace("import {spawn} from 'node:child_process';","const spawn=globalThis.__fakeSpawn;");
const {createNativeGateRunner}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const run=createNativeGateRunner(process.execPath,[]);
const event={session_id:'ses_stdin',cwd:process.cwd(),tool_use_id:'a'};
await assert.rejects(run(event),/native gate input failed|retained outcome requires reconciliation|native release uncertain/);
await new Promise(resolve=>setTimeout(resolve,80));
assert.equal((await run({...event,tool_use_id:'fresh'})).allow,true);
assert.equal(spawns,2);assert.equal(writes,1);
await run.close().catch(()=>{});
'''.replace('MODULE',json.dumps(module))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_silent_consume_then_exit_stays_quarantined(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'silent-consume-worker.mjs'
    worker.write_text("process.stdin.once('data',()=>process.exit(3));",encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
const event={session_id:'ses_silent',cwd:process.cwd(),tool_use_id:'a'};
await assert.rejects(run(event),/retained outcome requires reconciliation|prior native request unresolved/);
await new Promise(resolve=>setTimeout(resolve,80));
assert.throws(()=>run({...event,tool_use_id:'fresh'}),/quarantined; no duplicate enrollment/);
await run.close().catch(()=>{});
'''.replace('MODULE',json.dumps(module)).replace('WORKER',json.dumps(str(worker)))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr


def test_late_output_after_failure_does_not_clear_quarantine(tmp_path):
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    worker=tmp_path/'late-output-worker.mjs'
    worker.write_text('''process.stdin.once('data',()=>{
 process.stdout.write('bad-json\\n');
 setTimeout(()=>{
  process.stdout.write(JSON.stringify({request_id:'1',session_id:'ses_late',tool_use_id:'a',decision:'allow',agent_session:'app:agent-session:runtime:'+'a'.repeat(32),continued:true})+'\\n');
  process.exit(3);
 },60);
});
''',encoding='utf-8')
    code='''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(process.execPath,[WORKER]);
const event={session_id:'ses_late',cwd:process.cwd(),tool_use_id:'a'};
const first=run(event);
await assert.rejects(first,/invalid native UTF-8 JSON|retained outcome requires reconciliation|prior native request unresolved/);
await new Promise(resolve=>setTimeout(resolve,300));
assert.throws(()=>run({...event,tool_use_id:'fresh'}),/quarantined; no duplicate enrollment/);
await run.close().catch(()=>{});
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


def test_archhub_mcp_tools_map_to_the_shared_hook_classifications():
    module = (Path(__file__).resolve().parents[1] / 'nodelang/session_link/opencode-governance.mjs').as_uri()
    code = '''import assert from 'node:assert/strict';import {createOpenCodeGovernance} from MODULE;
const events=[];
const runner=async e=>{
 events.push(e);
 if(e.tool_name==='mcp__archhub-hosts__revit_execute_csharp')return {allow:false,reason:'host effect denied by shared gate'};
 if(e.tool_name==='mcp__archhub_agent_coordination__native_work_claim')return {allow:false,reason:'native claim denied by shared gate'};
 if(e.tool_name==='mcp__archhub_agent_coordination__native_work_publish_artifact')return {allow:false,reason:'native publish denied by shared gate'};
 if(e.tool_name==='mcp__archhub_agent_coordination__coordination_send_message')return {allow:false,reason:'coordination send denied by shared gate'};
 return {allow:true};
};
const hooks=await createOpenCodeGovernance({gateRunner:runner})({directory:process.cwd()});
const readHost={sessionID:'ses_mcp',callID:'hosts',tool:'archhub-hosts_hosts_state'};
await hooks['tool.execute.before'](readHost,{args:{}});
await hooks['tool.execute.after']({...readHost,args:{}},{});
assert.equal(events.at(-2).tool_name,'mcp__archhub-hosts__hosts_state');
const readCoord={sessionID:'ses_mcp',callID:'messages',tool:'archhub_agent_coordination_coordination_read_messages'};
await hooks['tool.execute.before'](readCoord,{args:{limit:10}});
await hooks['tool.execute.after']({...readCoord,args:{limit:10}},{});
assert.equal(events.at(-2).tool_name,'mcp__archhub_agent_coordination__coordination_read_messages');
const hostPing={sessionID:'ses_mcp',callID:'revit-ping',tool:'archhub-hosts_revit_ping'};
await hooks['tool.execute.before'](hostPing,{args:{}});
await hooks['tool.execute.after']({...hostPing,args:{}},{});
assert.equal(events.at(-2).tool_name,'mcp__archhub-hosts__revit_ping');
const hostInfo={sessionID:'ses_mcp',callID:'revit-info',tool:'archhub-hosts_revit_info'};
await hooks['tool.execute.before'](hostInfo,{args:{port:48884}});
await hooks['tool.execute.after']({...hostInfo,args:{port:48884}},{});
assert.equal(events.at(-2).tool_name,'mcp__archhub-hosts__revit_info');
const workRead={sessionID:'ses_mcp',callID:'work-read',tool:'archhub_agent_coordination_native_work_assignment'};
await hooks['tool.execute.before'](workRead,{args:{}});
await hooks['tool.execute.after']({...workRead,args:{}},{});
assert.equal(events.at(-2).tool_name,'mcp__archhub_agent_coordination__native_work_assignment');
await assert.rejects(
 hooks['tool.execute.before']({sessionID:'ses_mcp',callID:'host-effect',tool:'archhub-hosts_revit_execute_csharp'},{args:{code:'result = 1;'}}),
 /prewrite admission denied: host effect denied by shared gate/);
await assert.rejects(
 hooks['tool.execute.before']({sessionID:'ses_mcp',callID:'claim',tool:'archhub_agent_coordination_native_work_claim'},{args:{}}),
 /prewrite admission denied: native claim denied by shared gate/);
await assert.rejects(
 hooks['tool.execute.before']({sessionID:'ses_mcp',callID:'publish',tool:'archhub_agent_coordination_native_work_publish_artifact'},{args:{work:'w',material_digest:'d',idempotency_key:'k',patch:'p',summary:'s'}}),
 /prewrite admission denied: native publish denied by shared gate/);
await assert.rejects(
 hooks['tool.execute.before']({sessionID:'ses_mcp',callID:'send',tool:'archhub_agent_coordination_coordination_send_message'},{args:{target:'a',message:'b'}}),
 /prewrite admission denied: coordination send denied by shared gate/);
await assert.rejects(
 hooks['tool.execute.before']({sessionID:'ses_mcp',callID:'unknown',tool:'archhub-hosts_delete_everything'},{args:{}}),
 /no verified governance mapping: archhub-hosts_delete_everything/);
'''.replace('MODULE', json.dumps(module))
    _run_node(code)


def test_opencode_shell_allows_read_only_diagnostics_inside_workspace(tmp_path, monkeypatch):
    hooks = Path(__file__).resolve().parents[1] / '_gov/hooks/pretooluse_validate.py'
    spec = importlib.util.spec_from_file_location('pretooluse_validate_oc_read_shapes', hooks)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workspace = tmp_path / '00.ARCHUB'
    product = workspace / '10.PRODUCT' / '13.NODE-LANGUAGE'
    private = workspace / '20.CLIENTS'
    product.mkdir(parents=True)
    private.mkdir(parents=True)
    (product / 'README.md').write_text('ArchHub\n', encoding='utf-8')
    (product / 'cloud.json').write_text('{"secret":true}\n', encoding='utf-8')
    (product / '.env.local').write_text('TOKEN=x\n', encoding='utf-8')
    (product / '.git').mkdir()
    monkeypatch.setattr(module, '_WS_RAW', str(workspace))
    monkeypatch.setattr(module, '_WORKSPACE', module._real(str(workspace)))
    monkeypatch.setattr(module, '_PRODUCT_ROOT', module._real(str(product)))
    monkeypatch.setattr(module, '_PRODUCT_AREA', module._real(str(workspace / '10.PRODUCT')))
    monkeypatch.setattr(module, '_PUBLIC_CHECKOUT', module._real(str(workspace / 'ArchHub')))
    monkeypatch.setattr(module, '_PRIVATE_ROOTS', (module._real(str(private)), module._real(str(workspace / '60.PERSONAL'))))
    monkeypatch.setattr(module, '_CANONICAL_CHECKOUTS', (module._real(str(product)),))
    monkeypatch.setattr(module, '_HANDOFFS', module._real(str(workspace / '70.HANDOFFS')))
    monkeypatch.setattr(module, '_private_registered_root', lambda path: False)
    allowed = [
        'dir .',
        'ls .',
        'Get-ChildItem .',
        'type README.md',
        'cat README.md',
        'Get-Content README.md',
        'where git',
        'Get-Command git',
        'rg -n -i -- ArchHub README.md',
        'findstr /n /c:ArchHub README.md',
        'ping 127.0.0.1 -n 1',
        'Test-NetConnection localhost',
        'git status',
    ]
    for command in allowed:
        verdict = module.shell_admission(command, cwd=str(product), runtime='opencode')
        assert verdict['allow'], (command, verdict)
    refused = {
        'Get-Content ..\\..\\20.CLIENTS\\secret.txt': '20.CLIENTS',
        'Get-Content cloud.json': 'secret files',
        'Get-Content .env.local': 'secret files',
        'Get-ChildItem -Recurse': 'option -Recurse',
        'Get-ChildItem /s': 'option /s',
        'rg -- ArchHub .': 'secret descendant',
        'findstr /s /c:ArchHub .': 'secret descendant',
        'ping 8.8.8.8': 'localhost',
        'node -e "console.log(1)"': 'SHELL-3',
        'rg ArchHub .': 'pattern must follow --',
        'rg --pre=calc -- ArchHub .': 'option --pre',
        'rg --pre calc -- ArchHub .': 'option --pre',
        'rg --config ripgreprc -- ArchHub .': 'option --config',
        'rg -L -- ArchHub README.md': 'option -L',
        'rg --follow -- ArchHub README.md': 'option --follow',
        'rg -z -- ArchHub .': 'option -z',
        'rg --search-zip -- ArchHub .': 'option --search-zip',
        'rg --glob !*.pem -- ArchHub .': 'glob must be non-negated',
        'rg -- ArchHub C:\\Windows': 'inside the public product root',
        'rg -- ArchHub ..\\..': 'protected tree',
        'rg -- ArchHub ..\\..\\20.CLIENTS': '20.CLIENTS',
        'findstr /n -- ArchHub README.md': 'option --',
        'findstr /s ArchHub README.md': 'pattern must use /c:',
        'findstr /g:patterns.txt -- ArchHub README.md': 'option /g',
        'git status': 'product repo',
    }
    for command, reason in refused.items():
        cwd = str(tmp_path) if reason == 'product repo' else str(product)
        verdict = module.shell_admission(command, cwd=cwd, runtime='opencode')
        assert not verdict['allow'], (command, verdict)
        assert reason in verdict['reason'], verdict
    monkeypatch.setenv('RIPGREP_CONFIG_PATH', str(product / 'ripgreprc'))
    verdict = module.shell_admission('rg -- ArchHub .', cwd=str(product), runtime='opencode')
    assert not verdict['allow'], verdict
    assert 'RIPGREP_CONFIG_PATH' in verdict['reason'], verdict


def test_opencode_shell_denies_recursive_search_through_private_junction(tmp_path, monkeypatch):
    hooks = Path(__file__).resolve().parents[1] / '_gov/hooks/pretooluse_validate.py'
    spec = importlib.util.spec_from_file_location('pretooluse_validate_oc_junctions', hooks)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workspace = tmp_path / '00.ARCHUB'
    product = workspace / '10.PRODUCT' / '13.NODE-LANGUAGE'
    private = workspace / '20.CLIENTS'
    product.mkdir(parents=True)
    private.mkdir(parents=True)
    link = product / 'client-link'
    monkeypatch.setattr(module, '_WS_RAW', str(workspace))
    monkeypatch.setattr(module, '_WORKSPACE', module._real(str(workspace)))
    monkeypatch.setattr(module, '_PRODUCT_ROOT', module._real(str(product)))
    monkeypatch.setattr(module, '_PRODUCT_AREA', module._real(str(workspace / '10.PRODUCT')))
    monkeypatch.setattr(module, '_PUBLIC_CHECKOUT', module._real(str(workspace / 'ArchHub')))
    monkeypatch.setattr(module, '_PRIVATE_ROOTS', (module._real(str(private)),))
    monkeypatch.setattr(module, '_CANONICAL_CHECKOUTS', (module._real(str(product)),))
    monkeypatch.setattr(module, '_HANDOFFS', module._real(str(workspace / '70.HANDOFFS')))
    monkeypatch.setattr(module, '_private_registered_root', lambda path: False)
    created = False
    try:
        os.symlink(private, link, target_is_directory=True)
        created = True
    except OSError:
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(private)], text=True, capture_output=True)
        created = result.returncode == 0
    if not created:
        pytest.skip('junction creation unavailable')
    verdict = module.shell_admission('rg -- ArchHub .', cwd=str(product), runtime='opencode')
    assert not verdict['allow'], verdict
    assert 'protected descendant' in verdict['reason'], verdict


def test_opencode_shell_denies_search_through_private_file_symlink(tmp_path, monkeypatch):
    hooks = Path(__file__).resolve().parents[1] / '_gov/hooks/pretooluse_validate.py'
    spec = importlib.util.spec_from_file_location('pretooluse_validate_oc_file_links', hooks)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workspace = tmp_path / '00.ARCHUB'
    product = workspace / '10.PRODUCT' / '13.NODE-LANGUAGE'
    private = workspace / '20.CLIENTS'
    product.mkdir(parents=True)
    private.mkdir(parents=True)
    target = private / 'README.md'
    target.write_text('private ArchHub\n', encoding='utf-8')
    link = product / 'public-name.md'
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip('file symlink creation unavailable')
    monkeypatch.setattr(module, '_WS_RAW', str(workspace))
    monkeypatch.setattr(module, '_WORKSPACE', module._real(str(workspace)))
    monkeypatch.setattr(module, '_PRODUCT_ROOT', module._real(str(product)))
    monkeypatch.setattr(module, '_PRODUCT_AREA', module._real(str(workspace / '10.PRODUCT')))
    monkeypatch.setattr(module, '_PUBLIC_CHECKOUT', module._real(str(workspace / 'ArchHub')))
    monkeypatch.setattr(module, '_PRIVATE_ROOTS', (module._real(str(private)),))
    monkeypatch.setattr(module, '_CANONICAL_CHECKOUTS', (module._real(str(product)),))
    monkeypatch.setattr(module, '_HANDOFFS', module._real(str(workspace / '70.HANDOFFS')))
    monkeypatch.setattr(module, '_private_registered_root', lambda path: False)
    verdict = module.shell_admission('rg -- ArchHub .', cwd=str(product), runtime='opencode')
    assert not verdict['allow'], verdict
    assert 'protected descendant' in verdict['reason'], verdict


def test_real_native_gate_never_bound_reply_is_consumed_by_recovery_logic(tmp_path, monkeypatch):
    gate = Path(__file__).resolve().parents[1] / '_gov/hooks/opencode_native_gate.py'
    installed = tmp_path / 'ArchHub'
    package = installed / 'nodelang'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'native_agent_session.py').write_text('''
import os

class Identity:
    runtime = "opencode"
    external_session_id = os.environ["OPENCODE_SESSION_ID"]

class NativeAgentSession:
    def __init__(self, expected_agent_session=None):
        self._identity = Identity()
        self._state = "unbound"
        self._client = None
        self._session_root = None
        self._continued = False
        self._descriptor = object()
    def _check_identity(self):
        return None
    def connect(self):
        raise RuntimeError("an active persistent installed owner is required")
    def _read_owner(self):
        return self._descriptor
    def _lease_expired(self):
        return False
    def close(self):
        return {"released": True, "release_id": "a" * 32, "agent_session": None}
''', encoding='utf-8')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    module = (Path(__file__).resolve().parents[1] / 'nodelang/session_link/opencode-governance.mjs').as_uri()
    code = '''import assert from 'node:assert/strict';import {createNativeGateRunner} from MODULE;
const run=createNativeGateRunner(PYTHON,[GATE]);
const event={session_id:'ses_gate',cwd:process.cwd(),tool_use_id:'a',vendor:'opencode',
 hook_event_name:'PreToolUse',tool_name:'read',tool_input:{filePath:'README.md'}};
const first=await run(event);
assert.equal(first.allow,false);
assert.match(first.reason,/active persistent installed owner is required/);
await run.close().catch(()=>{});
'''.replace('MODULE',json.dumps(module)).replace('GATE',json.dumps(str(gate))).replace('PYTHON',json.dumps(sys.executable))
    result = subprocess.run([shutil.which('node'), '--input-type=module'], input=code, text=True,
                            encoding='utf-8', capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr + result.stdout


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


def test_an_aborted_read_stops_blocking_the_session_once_stale():
    """Live 717, 2026-10-07: OpenCode aborted a glob, never ran tool.execute.after,
    and every later edit was refused 'earlier tool admission or receipt unresolved'."""
    module=(Path(__file__).resolve().parents[1]/"nodelang/session_link/opencode-governance.mjs").as_uri()
    code='''import assert from 'node:assert/strict';
import {createOpenCodeGovernance} from MODULE;
const hooks=await createOpenCodeGovernance({gateRunner:async()=>({allow:true}),readStaleMs:200})({directory:process.cwd()});
const r={sessionID:'ses_abort',callID:'r',tool:'glob'},w={sessionID:'ses_abort',callID:'w',tool:'write'};
const args={filePath:'fixture.txt',content:'x'};
await hooks['tool.execute.before'](r,{args:{pattern:'*'}});
await assert.rejects(hooks['tool.execute.before'](w,{args}),/unresolved/);   // still running: wait
await new Promise(done=>setTimeout(done,300));
await hooks['tool.execute.before'](w,{args});                                 // aborted read ended
await hooks['tool.execute.after']({...w,args},{});
const u={sessionID:'ses_abort',callID:'u',tool:'write'};
await hooks['tool.execute.before'](u,{args});
await assert.rejects(hooks['tool.execute.before']({...u,callID:'v'},{args}),/unresolved/); // writes never expire
await hooks['tool.execute.after']({...u,args},{});
await hooks.dispose();
'''.replace('MODULE',json.dumps(module))
    result=subprocess.run([shutil.which('node'),'--input-type=module'],input=code,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
