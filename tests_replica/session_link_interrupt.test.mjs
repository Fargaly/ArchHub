import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {pathToFileURL} from 'node:url';

// Courts for the Session Link interrupt. A Claude Code session aborts its
// running turn when a peer frame arrives with priority "now"; Session Link
// sends that only through the explicit interrupt, never for ordinary sends.
// Isolated: temp HOME (Claude session registry), temp SESSION_LINK_STATE_DIR.
// The receiving "Claude" is a raw local pipe that records the frame bytes; no
// live app, session, bridge or message is touched.
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-interrupt-'));
process.env.HOME=home;process.env.USERPROFILE=home;
process.env.SESSION_LINK_STATE_DIR=path.join(home,'state');
for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','SESSION_LINK_PRODUCT_WORKER'])delete process.env[k];
const lib=path.join(import.meta.dirname,'..','nodelang','session_link');
const load=file=>import(pathToFileURL(path.join(lib,file)).href);
const {interrupt,interruptBound,stopText,CODEX_INTERRUPT_REFUSAL}=await load('interrupt.mjs');
const {PeerEndpoint}=await load('vendor/src/peer-protocol.mjs');
test.after(()=>fs.rmSync(home,{recursive:true,force:true}));

const CLAUDE='c4c4c4c4-0000-4000-8000-000000000004';

// A registered inbox whose pipe is replaced by a recorder of raw frames.
async function recorder(){
 const inbox=new PeerEndpoint({name:'fixture-claude',cwd:home,log:()=>{}});
 await inbox.start();
 await new Promise(r=>inbox.server.close(r));
 const frames=[];
 const server=net.createServer(socket=>{let buf='';socket.setEncoding('utf8');socket.on('data',d=>{buf+=d;let i;while((i=buf.indexOf('\n'))>=0){const line=buf.slice(0,i);buf=buf.slice(i+1);const f=JSON.parse(line);if(f.type!=='auth')frames.push(f);}});});
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(inbox.socketPath,resolve);});
 const close=()=>{server.close();inbox.stop();};
 return {socket:inbox.socketPath,frames,close};
}
async function until(cond,ms=3000){const end=Date.now()+ms;while(!cond()){if(Date.now()>end)throw new Error('condition not reached');await new Promise(r=>setTimeout(r,20));}}

// Every endpoint in one process shares the registry file sessions/<pid>.json,
// so a second started endpoint would overwrite (and on stop, delete) the
// recipient's entry. Senders here are never registered: sending needs only the
// recipient's registration and key.
const unregistered=name=>{const peer=new PeerEndpoint({name,cwd:home,log:()=>{}});peer.start=async()=>{};peer.stop=()=>{};return peer;};

// Counting deps: the interrupt may only look a target up and send once.
function deps(socket,{rows=[{id:CLAUDE,app:'claude'}]}={}){
 const calls={catalog:0,endpoints:0,sends:[]};
 return {calls,options:{
  catalogFn:async()=>{calls.catalog++;return {claude:rows};},
  sessionsFn:()=>socket?[{sessionId:CLAUDE,socket}]:[],
  endpointFn:()=>{calls.endpoints++;const peer=unregistered('fixture-interrupter');
   const send=peer.send.bind(peer);peer.send=async(s,t,o)=>{calls.sends.push({socket:s,text:t,priority:o?.priority});return await send(s,t,o);};return peer;},
 }};
}

test('an interrupt frame carries priority "now" and the stop text; an ordinary send stays "next"',{timeout:20000,skip:process.platform!=='win32'},async()=>{
 const r=await recorder();
 try{
  const {calls,options}=deps(r.socket);
  const result=await interrupt('claude',CLAUDE,'the founder asked to stop this build',options);
  await until(()=>r.frames.length===1);
  assert.equal(r.frames[0].priority,'now');
  assert.ok(r.frames[0].message.content.includes('\nStop: the founder asked to stop this build\n'));
  assert.equal(result.priority,'now');assert.equal(result.messageId,r.frames[0].msg_id);
  assert.equal(calls.sends.length,1);

  const ordinary=unregistered('fixture-ordinary');
  await ordinary.sendAndWait(r.socket,'ordinary request',{timeoutMs:0});
  await ordinary.sendAndWait(r.socket,'ordinary report',{timeoutMs:0,kind:'report'});
  await until(()=>r.frames.length===3);
  assert.deepEqual(r.frames.slice(1).map(f=>f.priority),['next','next']);
 }finally{r.close();}
});

test('a Codex target is refused with the exact reason and nothing is looked up or sent',{timeout:10000},async()=>{
 const {calls,options}=deps('unused');
 await assert.rejects(interrupt('codex','01a07b65-f0c4-7040-a218-d703384679a0','stop',options),{message:CODEX_INTERRUPT_REFUSAL});
 assert.equal(CODEX_INTERRUPT_REFUSAL,'Codex Desktop does not expose interrupt to other apps; nothing sent');
 assert.deepEqual(calls,{catalog:0,endpoints:0,sends:[]});
});

test('an untargeted, unresolved or non-Claude interrupt is refused and nothing is sent',{timeout:10000},async()=>{
 for(const session of [undefined,'','   ']){
  const {calls,options}=deps('unused');
  await assert.rejects(interrupt('claude',session,'stop',options),/exact target session; nothing sent/);
  assert.deepEqual(calls,{catalog:0,endpoints:0,sends:[]});
 }
 {const {calls,options}=deps('unused',{rows:[]});
  await assert.rejects(interrupt('claude','no-such-session','stop',options),/exactly one live Claude Code session; nothing sent/);
  assert.equal(calls.endpoints,0);assert.equal(calls.sends.length,0);}
 {const {calls,options}=deps(null);
  await assert.rejects(interrupt('claude',CLAUDE,'stop',options),/offline; nothing sent/);
  assert.equal(calls.endpoints,0);assert.equal(calls.sends.length,0);}
 for(const app of ['opencode','antigravity','antigravity-ide',undefined]){
  const {calls,options}=deps('unused');
  await assert.rejects(interrupt(app,CLAUDE,'stop',options),/Claude Code sessions only; nothing sent/);
  assert.deepEqual(calls,{catalog:0,endpoints:0,sends:[]});
 }
 for(const reason of [undefined,'','  ','x'.repeat(2001)]){
  const {calls,options}=deps('unused');
  await assert.rejects(interrupt('claude',CLAUDE,reason,options),/Stop reason/);
  assert.deepEqual(calls,{catalog:0,endpoints:0,sends:[]});
 }
});

test('a bound-link interrupt reaches only a bound Claude Code session; other remotes are refused unsent',{timeout:10000},async()=>{
 const sends=[];const peer={send:async(s,t,o)=>{sends.push({s,t,o});return 'id-1';},permissionMode:'prompting'};
 for(const app of ['opencode','antigravity','antigravity-ide']){
  await assert.rejects(interruptBound({claude:{app}},()=>({socket:'x'}),peer,{reason:'stop'}),/Claude Code sessions only; nothing sent/);
 }
 await assert.rejects(interruptBound({claude:{app:'claude'}},()=>{throw new Error('Bound Claude session is offline or changed workspace');},peer,{reason:'stop'}),/offline/);
 assert.equal(sends.length,0);
 const result=await interruptBound({claude:{app:'claude'}},()=>({socket:'bound-socket'}),peer,{reason:'wrong file',permissionMode:'bypass'});
 assert.deepEqual(sends,[{s:'bound-socket',t:stopText('wrong file'),o:{priority:'now',permissionMode:'bypass'}}]);
 assert.equal(result.priority,'now');
});
