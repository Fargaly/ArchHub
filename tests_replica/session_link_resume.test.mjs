import test from 'node:test';
import assert from 'node:assert/strict';
import {resumeSaved,confirmsSavedChild} from '../nodelang/session_link/resume.mjs';
const binding={id:'a'.repeat(16),claude:{id:'remote',cwd:'workspace',app:'claude'},codex:{id:'thread',cwd:'workspace'},permissionMode:'prompting'};
test('late successful child is recognized only by exact saved identities',()=>{
 const lock={id:binding.id,spawned:true,childPid:123};
 const runtime={id:binding.id,pid:123};
 const observed={...runtime,codex:'thread',claude:'remote',remoteApp:'claude'};
 assert.equal(confirmsSavedChild(binding,lock,runtime,observed),true);
 for(const changed of [{pid:124},{codex:'other'},{claude:'other'},{remoteApp:'opencode'}])
  assert.equal(confirmsSavedChild(binding,lock,runtime,{...observed,...changed}),false);
 assert.equal(confirmsSavedChild(binding,{...lock,childPid:null},runtime,observed),false);
});
test('live link stays untouched',async()=>{
 const result=await resumeSaved(binding,{probe:async()=>({status:'live'}),discover:async()=>({claude:[binding.claude],codex:[binding.codex]}),connect:()=>assert.fail()});
 assert.equal(result.status,'already_connected');
 assert.equal(result.endpoints_observed,true);
});
test('dead link restores exact identities without message replay',async()=>{
 let calls=[];
 const result=await resumeSaved(binding,{probe:async()=>({status:'offline'}),
  discover:async()=>({claude:[binding.claude],codex:[binding.codex]}),connect:async request=>{calls.push(request);return {id:binding.id};}});
 assert.equal(result.status,'restored');assert.equal(result.dispatch_attempted,false);
 assert.deepEqual(calls,[{app:'claude',claude:'remote',codex:'thread',permissionMode:'prompting'}]);
});
test('missing or changed workspace never substitutes a session',async()=>{
 const result=await resumeSaved(binding,{probe:async()=>({status:'offline'}),
  discover:async()=>({claude:[{...binding.claude,cwd:'other'}],codex:[binding.codex]}),connect:()=>assert.fail()});
 assert.equal(result.status,'recovery_required');
});
test('unreachable live owner is never replaced',async()=>{
 const result=await resumeSaved(binding,{probe:async()=>({status:'recovery_required'}),discover:()=>assert.fail(),connect:()=>assert.fail()});
 assert.equal(result.status,'recovery_required');
});
test('bypass permission is not inherited by another or absent origin',async()=>{
 for(const currentExecutor of ['different',undefined]){
  const result=await resumeSaved({...binding,permissionMode:'bypass',executor:'original'},
   {currentExecutor,probe:async()=>({status:'offline'}),discover:()=>assert.fail(),connect:()=>assert.fail()});
  assert.equal(result.reason,'saved_sender_permission_origin_changed');
 }
});

test('live bridge without its exact endpoints is not recovered',async()=>{
 const result=await resumeSaved(binding,{probe:async()=>({status:'live'}),
 discover:async()=>({claude:[],codex:[binding.codex]}),connect:()=>assert.fail()});
 assert.equal(result.status,'recovery_required');
});

// Exercise the actual CLI boundary. A wrong-role match must never enter
// resume(), even when its bare ID occurs in a saved binding.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
test('resume CLI rejects wrong role before any saved-state change',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'session-link-role-'));
 try{
  const dir=path.join(root,'connections');fs.mkdirSync(dir);
  const id=crypto.createHash('sha256').update('shared|codex-only').digest('hex').slice(0,16);
  const saved={id,claude:{id:'shared',app:'claude',cwd:'workspace'},codex:{id:'codex-only',cwd:'workspace'}};
  const target=path.join(dir,id+'.binding.json');fs.writeFileSync(target,JSON.stringify(saved));
  const before=fs.readFileSync(target);
  for(const env of [
   {ARCHHUB_AGENT_RUNTIME:'codex',CODEX_THREAD_ID:'shared'},
   {ARCHHUB_AGENT_RUNTIME:'claude',CLAUDE_CODE_SESSION_ID:'codex-only'},
   {ARCHHUB_AGENT_RUNTIME:'opencode',OPENCODE_SESSION_ID:'shared'}]){
   const result=spawnSync(process.execPath,[fileURLToPath(new URL('../nodelang/session_link/bridge.mjs',import.meta.url)),
     'resume','--current','--connections',id],{env:{...process.env,...env,SESSION_LINK_STATE_DIR:root},encoding:'utf8',timeout:5000,windowsHide:true});
   assert.equal(result.status,1,result.stderr);
   assert.match(result.stderr,/not bound to this exact session/);
   assert.deepEqual(fs.readdirSync(dir),[id+'.binding.json']);
   assert.deepEqual(fs.readFileSync(target),before);
  }
 }finally{assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});}
});
