import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {test,after} from 'node:test';
import {fileURLToPath} from 'node:url';
import {spawn,spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {once} from 'node:events';

const fixture=process.env.SESSIONLINK2_FIXTURE;
assert.ok(fixture&&path.isAbsolute(fixture),'an isolated fixture root is required');
const state=path.join(fixture,'STATE');
await fs.mkdir(state,{recursive:true});
process.env.SESSION_LINK_STATE_DIR=state;
Object.assign(process.env,{HOME:fixture,USERPROFILE:fixture,
 LOCALAPPDATA:path.join(fixture,'LOCAL'),APPDATA:path.join(fixture,'ROAMING'),
 CODEX_HOME:path.join(fixture,'CODEX_CONFIG'),CLAUDE_CONFIG_DIR:path.join(fixture,'CLAUDE_CONFIG'),
 CODEX_BIN:process.execPath});
for(const name of Object.keys(process.env))if(/^(?:CODEX_APP_TOOLS_|CODEX_THREAD_ID$|CLAUDE_CODE_MESSAGING_SOCKET$|SESSION_LINK_.*ATTACH)/.test(name))delete process.env[name];
const source=await import('../../01.APP/nodelang/session_link/ask.mjs');
const {catalog}=await import('../../01.APP/nodelang/session_link/bridge.mjs');
const session='11111111-1111-4111-8111-111111111111';
const other='22222222-2222-4222-8222-222222222222';
const roots={claude:[path.join(fixture,'CLAUDE')],codex:[path.join(fixture,'CODEX')]};
const claude=path.join(roots.claude[0],'PROJECT',session+'.jsonl');
const codex=path.join(roots.codex[0],'2026','rollout-2026-10-24-'+other+'.jsonl');
await fs.mkdir(path.dirname(claude),{recursive:true});
await fs.mkdir(path.dirname(codex),{recursive:true});
await fs.writeFile(claude,JSON.stringify({type:'assistant',message:{role:'assistant',content:[{type:'text',text:'Door clearance was fixed at the hinge.'}]}})+'\n');
await fs.writeFile(codex,[{type:'session_meta',payload:{id:other,cwd:fixture}},
 {type:'response_item',payload:{type:'message',role:'assistant',content:[{type:'output_text',text:'Door schedule was checked.'}]}}].map(JSON.stringify).join('\n')+'\n');
const discover=async()=>({claude:[],codex:[]});
const localModel=async()=>new Response(JSON.stringify({models:[{name:'fixture:1b',size:1024,details:{format:'gguf'}}]}),{status:200});
const options={roots,discover,fetcher:localModel};
const ask=(app,id,text,extra={})=>{
 assert.equal(typeof source.askDormant,'function','main lacks dormant-session ask');
 return source.askDormant(app,id,text,{...options,...extra});
};

test('L1 searches both saved providers without executing or creating a mailbox',async()=>{
 let runs=0;
 const result=await ask(undefined,undefined,'door',{level:'search',run:async()=>{runs++;}});
 assert.equal(result.status,'evidence');assert.equal(result.level,'L1');
 assert.deepEqual(new Set(result.hits.map(hit=>hit.app)),new Set(['claude','codex']));
 assert.ok(result.hits.every(hit=>hit.file&&hit.line>0&&hit.role==='assistant'));
 assert.equal(runs,0);assert.equal(result.complete,true);
});
test('L2 reads the exact JSONL and returns cited text; missing is named',async()=>{
 const result=await ask('claude',session,'door',{level:'read'});
 assert.equal(result.status,'evidence');assert.equal(result.level,'L2');
 assert.equal(result.hits.length,1);assert.equal(result.hits[0].session,session);
 assert.equal(result.hits[0].text,'Door clearance was fixed at the hinge.');
 const missing=await ask('claude',other,'door',{level:'read'});
 assert.equal(missing.status,'failed');assert.equal(missing.reason,'session_not_found');
});
test('L2 refuses ambiguous IDs and malformed transcripts rather than empty success',async()=>{
 const duplicate=path.join(roots.claude[0],'DUPLICATE',session+'.jsonl');
 await fs.mkdir(path.dirname(duplicate),{recursive:true});await fs.copyFile(claude,duplicate);
 try{assert.equal((await ask('claude',session,'door',{level:'read'})).reason,'session_ambiguous');}
 finally{await fs.unlink(duplicate);}
 const malformed=path.join(roots.claude[0],other+'.jsonl');await fs.writeFile(malformed,'{broken\n');
 try{assert.equal((await ask('claude',other,'door',{level:'read'})).reason,'transcript_invalid');}
 finally{await fs.unlink(malformed);}
});
test('L3 resumes each exact session once with a free local model and bounded stdin question',async()=>{
 for(const [app,id] of [['claude',session],['codex',other]]){
  let calls=0;
  const result=await ask(app,id,'What fixed the door?',{level:'wake',model:'fixture:1b',run:async request=>{
   calls++;assert.ok(request.args.includes(id));assert.ok(request.args.includes('fixture:1b'));
   assert.equal(request.text,'What fixed the door?');assert.ok(request.timeoutMs>0&&request.timeoutMs<=180000);
   assert.equal(request.env.OLLAMA_HOST,'http://127.0.0.1:11434');
   if(app==='codex'){
    assert.ok(request.args.includes('--oss'));assert.ok(request.args.includes('--local-provider'));
    assert.equal(request.args[request.args.indexOf('--local-provider')+1],'ollama');
    assert.ok(request.args.includes('model_provider="ollama"'));
    assert.ok(request.args.includes('model_providers.ollama.base_url="http://127.0.0.1:11434/v1"'));
    assert.ok(request.args.includes('model_providers.ollama.requires_openai_auth=false'));
    assert.ok(request.args.includes('--ignore-user-config'));
    assert.equal(request.args[request.args.indexOf('--sandbox')+1],'read-only');
   }else{
    assert.equal(request.env.ANTHROPIC_BASE_URL,'http://127.0.0.1:11434');
    assert.equal(request.env.ANTHROPIC_API_KEY,'');assert.equal(request.env.ANTHROPIC_AUTH_TOKEN,'ollama');
    for(const name of ['HAIKU','SONNET','OPUS'])assert.equal(request.env['ANTHROPIC_DEFAULT_'+name+'_MODEL'],'fixture:1b');
    assert.equal(request.args[request.args.indexOf('--tools')+1],'');
    assert.equal(JSON.parse(request.args[request.args.indexOf('--settings')+1]).env.ANTHROPIC_BASE_URL,'http://127.0.0.1:11434');
   }
   const stdout=app==='claude'?JSON.stringify({result:'The hinge clearance.',is_error:false}):
    JSON.stringify({type:'item.completed',item:{type:'agent_message',text:'The hinge clearance.'}});
   return {code:0,stdout};
  }});
  assert.equal(calls,1);assert.equal(result.status,'replied');assert.equal(result.text,'The hinge clearance.');
  assert.equal(result.execution_verified,false);
 }
});
test('L3 timeout, nonzero, empty, provider error and missing runtime are named failures',async()=>{
 const outcomes=[
  [{timedOut:true,code:null,stdout:''},'wake_timeout'],
  [{code:7,stdout:'not an answer'},'wake_exit_nonzero'],
  [{code:0,stdout:''},'wake_empty_answer'],
  [{code:0,stdout:JSON.stringify({type:'turn.failed',error:{message:'fixture refusal'}})},'wake_provider_failed'],
  [{code:null,reason:'wake_runtime_unavailable',stdout:''},'wake_runtime_unavailable']
 ];
 for(const [outcome,reason] of outcomes){
  const result=await ask('codex',other,'door',{level:'wake',model:'fixture:1b',run:async()=>outcome});
  assert.equal(result.status,'failed');assert.equal(result.reason,reason);assert.equal(result.text,undefined);
 }
});
test('wake refuses live targets, paid/default/cloud models and option-like IDs before executing',async()=>{
 let runs=0;const run=async()=>{runs++;return {code:0,stdout:'wrong'};};
 for(const model of [undefined,'gpt-paid','fixture:cloud']){
  const fetcher=model==='fixture:cloud'?async()=>new Response(JSON.stringify({models:[
   {name:model,size:1024,details:{format:'gguf'}}]}),{status:200}):localModel;
  const result=await ask('codex',other,'door',{level:'wake',model,run,fetcher});
  assert.equal(result.status,'failed');assert.equal(result.reason,'wake_free_model_unavailable');
 }
 for(const remote of [{remote_host:'https://cloud.example.invalid'},{remote_model:'remote-alias'}]){
  const result=await ask('codex',other,'door',{level:'wake',model:'fixture:1b',run,
   fetcher:async()=>new Response(JSON.stringify({models:[{name:'fixture:1b',size:1024,details:{format:'gguf'},...remote}]}),{status:200})});
  assert.equal(result.status,'failed');assert.equal(result.reason,'wake_free_model_unavailable');
 }
 assert.equal((await ask('codex','--last','door',{level:'wake',model:'fixture:1b',run})).reason,'session_id_invalid');
 assert.equal((await ask('codex',other,'door',{level:'wake',model:'fixture:1b',run,
  discover:async()=>({codex:[{id:other}]})})).reason,'session_live');
 assert.equal(runs,0);
});
test('one deadline bounds a stalled preflight and cannot be extended above 180 seconds',async()=>{
 const start=Date.now();
 const result=await ask('codex',other,'door',{level:'wake',model:'fixture:1b',timeoutMs:80,
  discover:async()=>new Promise(()=>{})});
 assert.equal(result.reason,'wake_timeout');assert.ok(Date.now()-start<1000);
 assert.equal((await ask('codex',other,'door',{timeoutMs:180001})).reason,'timeout_invalid');
});
test('real owned process runner reports nonzero, timeout and output overflow; kills parent and descendants',async()=>{
 assert.equal(typeof source.runDormantCommand,'function','main lacks bounded owned wake runner');
 const python=process.env.ARCHHUB_PYTHON;
 const base={command:process.execPath,env:{},timeoutMs:10000,text:'one question'};
 let result=await source.runDormantCommand({...base,args:['-e','process.stdin.resume();process.stdin.on("end",()=>process.exit(9))']});
 assert.equal(result.code,9);assert.equal(result.timedOut,false);
 const child=path.join(fixture,'CHILD.pid');
 await fs.rm(child,{force:true});
 const pending=source.runDormantCommand({...base,args:['-e',
  'const fs=require("fs"),cp=require("child_process");process.stdin.resume();process.stdin.on("end",()=>{const c=cp.spawn(process.execPath,["-e","setInterval(()=>{},1000)"],{stdio:"ignore",windowsHide:true});fs.writeFileSync(process.argv[1],JSON.stringify({parent:process.pid,child:c.pid}));setInterval(()=>{},1000)});',child]});
 const readyBy=Date.now()+8000;
 while(!existsSync(child)&&Date.now()<readyBy)await new Promise(resolve=>setTimeout(resolve,50));
 result=await pending;
 assert.ok(existsSync(child),'the timeout court must reach child startup');
 assert.equal(result.timedOut,true);assert.equal(result.code,null);
 const pids=JSON.parse(await fs.readFile(child,'utf8'));
 await new Promise(resolve=>setTimeout(resolve,100));
 for(const [role,pid] of Object.entries(pids))assert.throws(()=>process.kill(pid,0),'owned '+role+' must exit with the timed-out wake');
 result=await source.runDormantCommand({...base,args:['-e','process.stdout.write("X".repeat(2000000));setInterval(()=>{},1000)']});
 assert.equal(result.reason,'wake_output_limit');
 assert.ok(python,'the court uses the repository venv explicitly');
});

test('short Windows startup timeout leaves no fixture native process before child Job assignment',async()=>{
 assert.equal(typeof source.runDormantCommand,'function','main lacks bounded owned wake runner');
 const marker='SESSIONLINK2-GUARD-'+process.pid+'-'+Date.now();
 const result=await source.runDormantCommand({command:process.execPath,env:{},timeoutMs:450,text:'one question',args:['-e',
  'const cp=require("child_process");process.stdin.resume();process.stdin.on("end",()=>{cp.spawn(process.execPath,["-e","setInterval(()=>{},1000)",process.argv[1]],{stdio:"ignore",windowsHide:true});setInterval(()=>{},1000)});',marker]});
 assert.equal(result.timedOut,true);assert.equal(result.code,null);
 if(process.platform==='win32'){
  await new Promise(resolve=>setTimeout(resolve,100));
  const powershell=path.join(process.env.SystemRoot,'System32','WindowsPowerShell','v1.0','powershell.exe');
  const observed=spawnSync(powershell,['-NoProfile','-NonInteractive','-Command',
   `@(Get-CimInstance Win32_Process -Filter "Name='node.exe' AND CommandLine LIKE '%${marker}%'").Count`],
   {encoding:'utf8',windowsHide:true,timeout:30000});
  assert.equal(observed.status,0,observed.stderr);assert.equal(observed.stdout.trim(),'0','only this fixture marker is queried');
 }
});
for(const app of ['codex','opencode'])test('live ask '+app+' default native wake reaches its fixture API',async()=>{
 const transcript=path.join(state,'TURNS.jsonl');await fs.rm(transcript,{force:true});
 const entry=fileURLToPath(new URL('./session_link_wsinject.mjs',import.meta.url));
 const child=spawn(process.execPath,[entry,state,app,other],{stdio:['pipe','pipe','pipe'],windowsHide:true});
 let error='';child.stderr.on('data',chunk=>{error+=chunk;});
 try{
  const [ready]=await once(child.stdout,'data');assert.equal(ready.toString().trim(),'READY',error);
  const all=await catalog({apps:[app],workshopInjection:true});
  assert.equal(all[app].length,1);const target={...all[app][0],pid:123};
  let sends=0,writes=0;
  const declarations=[{app,native_session_id:target.id,process_alive:true,
   process_lineage:[{pid:123,created_at:1}],agent:'Target',session:'fixture'}];
  const result=await source.ask(app,other,'Please answer','prompting',{
   discover:async()=>({[app]:[target]}),onDispatch:()=>{writes++;},
   mailboxCall:(method,body)=>{
    if(method==='send'){
     sends++;assert.deepEqual(body.native_control,{app,id:other});
     return {message_id:'existing-note',sequence:1,sender_label:'caller'};
    }
    return {declarations,declarations_more:false,next_since:1,messages:body.since===0||!existsSync(transcript)?[]:
     [{id:'answer',reply_to:'existing-note',author:'Target [fixture]',category:'app:workshop:category:note',content:'To caller:\nAnswered'}]};
   }});
  assert.equal(result.status,'replied');assert.equal(result.text,'Answered');
  assert.equal(result.mailbox_message,'existing-note');assert.equal(sends,1);assert.equal(writes,1);
  const turns=(await fs.readFile(transcript,'utf8')).trim().split('\n').map(row=>JSON.parse(row));
  assert.equal(turns.length,1);assert.match(turns[0].text,/existing-note/);
 }finally{
  child.stdin.end();await once(child,'exit');
 }
});

test('CLI ask-dormant exposes L1/L2 without a live account',async()=>{
 const entry=fileURLToPath(new URL('../../01.APP/nodelang/session_link/ask.mjs',import.meta.url));
 const input=path.join(fixture,'QUESTION.txt');await fs.writeFile(input,'door');
 const config=path.join(fixture,'CLAUDE_CONFIG');
 const saved=path.join(config,process.platform==='win32'?'PROJECTS':'projects','PROJECT',session+'.jsonl');
 await fs.mkdir(path.dirname(saved),{recursive:true});await fs.copyFile(claude,saved);
 for(const selection of [[],['--session',session]]){
  const preload='data:text/javascript,'+encodeURIComponent('setInterval(()=>{},1000);');
  const result=spawnSync(process.execPath,['--import',preload,entry,'ask-dormant','--app','claude',...selection,'--file',input],{
   env:{...process.env,CLAUDE_CONFIG_DIR:config,CODEX_HOME:path.join(fixture,'CODEX_CONFIG'),
    USERPROFILE:fixture,HOME:fixture},encoding:'utf8',timeout:10000});
  // Provider root conventions are exercised by the real CLI, never a test-only path flag.
  assert.notEqual(result.status,null);assert.equal(result.status,0,result.stderr);
  const answer=JSON.parse(result.stdout);
  assert.equal(answer.status,'evidence');assert.equal(answer.level,selection.length?'L2':'L1');
  assert.equal(answer.complete,true);assert.equal(answer.hits.length,1);
  assert.equal(answer.hits[0].session,session);assert.equal(answer.hits[0].line,1);
  assert.equal(answer.hits[0].text,'Door clearance was fixed at the hinge.');
  const compared=value=>process.platform==='win32'?path.resolve(value).toLowerCase():path.resolve(value);
  assert.equal(compared(answer.hits[0].file),compared(saved));
 }
});
after(async()=>{await fs.rm(fixture,{recursive:true,force:true});});
