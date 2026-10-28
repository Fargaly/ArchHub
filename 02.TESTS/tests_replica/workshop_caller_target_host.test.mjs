import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

// Courts for the Workshop caller-host / target-host contract. Isolated:
// temp HOME and WORKSHOP_STATE_DIR, private LOCAL pipes, a mock app pipe.
//
// Receiver, Codex 26.928 resources/app.asar: tools/call params are
// {arguments, callerSource in codex|chatgpt, callId, hostId (optional, the
// CALLER's host; the app injects CODEX_APP_TOOLS_CALLER_HOST_ID into its own
// tools server), namespace, threadId (caller thread), tool, turnId}; and
// send_message_to_thread's inputSchema is {threadId, hostId ("Optional host id
// returned by create_thread or list_threads" -- the TARGET's host), prompt,
// model, thinking}, additionalProperties false.
const BS=String.fromCharCode(92);
const pipe=name=>BS+BS+'.'+BS+'pipe'+BS+'LOCAL'+BS+name+'-'+crypto.randomUUID();
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-hosts-'));
process.env.HOME=home;
process.env.WORKSHOP_STATE_DIR=path.join(home,'state');
fs.mkdirSync(path.join(process.env.WORKSHOP_STATE_DIR,'connections'),{recursive:true});
for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','CODEX_APP_TOOLS_CALLER_HOST_ID','WORKSHOP_PRODUCT_WORKER'])delete process.env[k];
const lib=path.join(import.meta.dirname,'..','..','01.APP','nodelang','workshop');
const load=file=>import(pathToFileURL(path.join(lib,file)).href);
const native=await load('native.mjs');
const bridge=await load('bridge.mjs');
test.after(()=>{fs.rmSync(home,{recursive:true,force:true});
 // On code without this contract an ask can stay pending (its reply never comes);
 // every result is already reported by now, so do not let it hold the file open.
 setTimeout(()=>process.exit(process.exitCode??0),5000).unref();});

const CALLER='01a0cafe-0000-7000-8000-000000000001',TARGET='01a07b65-f0c4-7040-a218-d703384679a0';
const CALLER_HOST='host-caller-durable',TARGET_HOST='host-target-local';
const row=(id,hostId)=>({id,kind:'codex',projectId:null,hostId,status:{type:'active',activeFlags:[]},cwd:'C:/fixture',updatedAt:1790000000000,title:'T',summary:null,isUnread:false});

function mockCodexApp(threads){
 const calls=[],name=pipe('sl-hosts-app');
 const server=net.createServer(sock=>{let buf=Buffer.alloc(0);sock.on('error',()=>{});sock.on('data',chunk=>{
  buf=Buffer.concat([buf,chunk]);
  while(buf.length>=4){
   const n=buf.readUInt32LE(0);if(buf.length<n+4)return;
   const msg=JSON.parse(buf.subarray(4,n+4).toString('utf8'));buf=buf.subarray(n+4);calls.push(msg);
   const p=msg.params,str=v=>typeof v==='string'&&v.trim().length>0;
   const valid=msg.jsonrpc==='2.0'&&msg.method==='tools/call'&&p&&('arguments' in p)&&
    ['codex','chatgpt'].includes(p.callerSource)&&str(p.callId)&&str(p.namespace)&&str(p.threadId)&&
    str(p.tool)&&str(p.turnId)&&(!('hostId' in p)||str(p.hostId))&&
    (p.tool!=='send_message_to_thread'||Object.keys(p.arguments).every(k=>['threadId','hostId','prompt','model','thinking'].includes(k)));
   const reply=!valid?{error:{code:-32602,message:'Invalid app tool request'},id:msg.id,jsonrpc:'2.0'}
    :p.tool==='list_threads'?{id:msg.id,jsonrpc:'2.0',result:{contentItems:[{type:'inputText',text:JSON.stringify({schemaVersion:4,pinnedThreads:[],threads,unavailableHosts:[],unavailableSources:[]})}],success:true}}
    :{id:msg.id,jsonrpc:'2.0',result:{contentItems:[{type:'inputText',text:'{}'}],success:true}};
   const body=Buffer.from(JSON.stringify(reply)),head=Buffer.alloc(4);head.writeUInt32LE(body.length);sock.write(Buffer.concat([head,body]));
  }
 });});
 return new Promise(resolve=>server.listen(name,()=>resolve({name,calls,close:()=>new Promise(done=>server.close(done))})));
}
const inCodexTask=async(app,body,callerHost)=>{
 process.env.CODEX_APP_TOOLS_PIPE_PATH=app.name;process.env.CODEX_THREAD_ID=CALLER;
 if(callerHost)process.env.CODEX_APP_TOOLS_CALLER_HOST_ID=callerHost;
 try{return await body();}finally{for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','CODEX_APP_TOOLS_CALLER_HOST_ID'])delete process.env[k];}};

test('H1 a call from a Codex task names the caller host the app gave that task',async()=>{
 const app=await mockCodexApp([row(TARGET,TARGET_HOST)]);
 try{
  await inCodexTask(app,()=>native.nativeCall('list_threads',{limit:1}),CALLER_HOST);
  assert.equal(app.calls[0].params.hostId,CALLER_HOST);
  assert.equal(app.calls[0].params.threadId,CALLER);
 }finally{await app.close();}
});

test('H2 without a caller host from the app, none is invented',async()=>{
 const app=await mockCodexApp([row(TARGET,TARGET_HOST)]);
 try{
  await inCodexTask(app,()=>native.nativeCall('list_threads',{limit:1}));
  assert.equal('hostId' in app.calls[0].params,false);
 }finally{await app.close();}
});

test('H3 one pending message keeps one request identity across a resend',async()=>{
 assert.equal(typeof native.nativeCallParams,'function','no request-identity builder');
 const first=native.nativeCallParams('send_message_to_thread',{threadId:TARGET,prompt:'x'},CALLER,{requestId:'msg-1'});
 const again=native.nativeCallParams('send_message_to_thread',{threadId:TARGET,prompt:'x'},CALLER,{requestId:'msg-1'});
 const other=native.nativeCallParams('send_message_to_thread',{threadId:TARGET,prompt:'x'},CALLER,{requestId:'msg-2'});
 assert.equal(first.callId,'workshop-msg-1');
 assert.equal(first.turnId,'workshop-turn-msg-1');
 assert.deepEqual([again.callId,again.turnId],[first.callId,first.turnId]);
 assert.notEqual(other.callId,first.callId);
});

test('H4 discovery keeps each task row\'s own host (the target host)',async()=>{
 const app=await mockCodexApp([row(TARGET,TARGET_HOST),row('01a0beef-0000-7000-8000-000000000002',null)]);
 try{
  const all=await inCodexTask(app,()=>bridge.catalog({apps:['codex']}));
  const byId=Object.fromEntries(all.codex.map(t=>[t.id,t]));
  assert.equal(byId[TARGET].hostId,TARGET_HOST);
  assert.equal('hostId' in byId['01a0beef-0000-7000-8000-000000000002'],false);
 }finally{await app.close();}
});

test('H5 a saved link keeps the caller host and never the target host',()=>{
 assert.equal(typeof bridge.bindingRecord,'function','no binding record builder');
 process.env.CODEX_THREAD_ID=CALLER;process.env.CODEX_APP_TOOLS_CALLER_HOST_ID=CALLER_HOST;
 try{
  const saved=bridge.bindingRecord({id:'0123456789abcdef',claude:{id:'c'},codex:{id:TARGET,cwd:'C:/fixture',app:'codex',hostId:TARGET_HOST},permissionMode:'prompting'});
  assert.equal(saved.executor,CALLER);
  assert.equal(saved.executorHostId,CALLER_HOST);
  assert.equal('hostId' in saved.codex,false);
 }finally{delete process.env.CODEX_THREAD_ID;delete process.env.CODEX_APP_TOOLS_CALLER_HOST_ID;}
 const bare=bridge.bindingRecord({id:'0123456789abcdef',claude:{id:'c'},codex:{id:TARGET},permissionMode:'prompting'});
 assert.equal('executorHostId' in bare,false);
});

test('H6 a send carries the caller host in the call and the live target host in the arguments',async()=>{
 assert.equal(typeof bridge.boundSendCall,'function','no bound send builder');
 const app=await mockCodexApp([row(TARGET,TARGET_HOST)]);
 const b={id:'0123456789abcdef',codex:{id:TARGET},executor:CALLER,executorHostId:CALLER_HOST};
 try{
  process.env.CODEX_APP_TOOLS_PIPE_PATH=app.name;
  await native.nativeCall(...bridge.boundSendCall(b,row(TARGET,TARGET_HOST),'hello','msg-7'));
  await native.nativeCall(...bridge.boundSendCall({...b,executorHostId:undefined},row(TARGET,null),'hello','msg-8'));
 }finally{delete process.env.CODEX_APP_TOOLS_PIPE_PATH;await app.close();}
 const [withHosts,without]=app.calls.map(c=>c.params);
 assert.equal(withHosts.hostId,CALLER_HOST);
 assert.equal(withHosts.threadId,CALLER);
 assert.equal(withHosts.arguments.hostId,TARGET_HOST);
 assert.equal(withHosts.arguments.threadId,TARGET);
 assert.equal(withHosts.callId,'workshop-msg-7');
 assert.equal('hostId' in without,false);
 assert.equal('hostId' in without.arguments,false);
 assert.ok(app.calls.every(c=>!c.error));
});

// ---- Real caller -> real bridge -> app pipe. Nothing hand-supplied: every id
// below is the one the ORIGIN minted (ask's request id, the reply CLI's id, a
// caller's own request id), read back from the wire the mock app received.
import {spawn} from 'node:child_process';
// Children run asynchronously: the mock app and the ask control endpoint live in
// THIS process, and a blocking spawnSync would starve them (the bridge's call to
// the app then times out and reads as "no such task").
const run=(args,input,env)=>new Promise(resolve=>{const child=spawn(process.execPath,args,{env,windowsHide:true});
 let stdout='',stderr='';child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
 child.stdout.on('data',d=>{stdout+=d;});child.stderr.on('data',d=>{stderr+=d;});
 child.on('close',status=>resolve({status,stdout,stderr}));child.stdin.end(input);});
const bridgeFile=path.join(lib,'bridge.mjs');
const sendsTo=app=>app.calls.filter(c=>c.params?.tool==='send_message_to_thread').map(c=>c.params);
const until=async(check,ms=15000)=>{const end=Date.now()+ms;while(Date.now()<end){const v=check();if(v)return v;await new Promise(r=>setTimeout(r,100));}throw new Error('timed out waiting');};

const assertHosts=(params,requestId)=>{
 assert.equal(params.hostId,CALLER_HOST,'caller host in the call');
 assert.equal(params.threadId,CALLER,'caller thread in the call');
 assert.equal(params.arguments.hostId,TARGET_HOST,'target host in the arguments');
 assert.equal(params.arguments.threadId,TARGET,'target thread in the arguments');
 assert.equal(params.callId,'workshop-'+requestId);
 assert.equal(params.turnId,'workshop-turn-'+requestId);
};

test('B1 retired shell reply cannot create a peer reply or bridge',async()=>{
 const app=await mockCodexApp([row(TARGET,TARGET_HOST)]);
 try{
  const done=await run([bridgeFile,'serve','unused-binding'],'',{...process.env});
  assert.equal(done.status,0,done.stderr);
  assert.deepEqual(JSON.parse(done.stdout).channel,'Workshop');
  assert.equal(JSON.parse(done.stdout).retired,true);
  assert.equal(sendsTo(app).length,0);
 }finally{await app.close();}
});

test('B2 native app control preserves caller and target hosts without creating a peer channel',async()=>{
 const app=await mockCodexApp([row(TARGET,TARGET_HOST)]);
 try{
  const request=crypto.randomUUID();
  process.env.CODEX_APP_TOOLS_CALLER_HOST_ID=CALLER_HOST;
  const receipt=await inCodexTask(app,()=>native.postCodex(TARGET,'Workshop task pointer',{requestId:request}),CALLER_HOST);
  assert.equal(receipt.success,true);assertHosts(sendsTo(app).at(-1),request);
  assert.equal(sendsTo(app).length,1);
 }finally{delete process.env.CODEX_APP_TOOLS_CALLER_HOST_ID;await app.close();}
});

test('D1 native ask carries the Workshop id and reports missing Codex process identity',async()=>{
 const app=await mockCodexApp([row(TARGET,TARGET_HOST)]);
 let sent=false,delivered=false;
 const message=crypto.randomUUID();
 const mailboxCall=(method)=>{
  if(method==='send'){sent=true;return {message_id:message,sequence:1,sender_label:'founder'};}
  return {declarations:[],messages:sent&&delivered?[{id:'reply',reply_to:message,author:'unverified',content:'four'}]:[],next_since:2};
 };
 try{
  process.env.CODEX_APP_TOOLS_CALLER_HOST_ID=CALLER_HOST;
  const result=await inCodexTask(app,()=>(load('ask.mjs').then(module=>module.ask('codex',TARGET,'what is two plus two','prompting',{mailboxCall,dispatchControl:async(target,pointer)=>{await native.postCodex(target.id,pointer,{requestId:message});delivered=true;}}))),CALLER_HOST);
  assert.equal(result.status,'uncertain');assert.equal(result.reason,'recipient_identity_unverified');
  const wire=await until(()=>sendsTo(app).at(-1));assertHosts(wire,message);
  assert.match(wire.arguments.prompt,/Reply ONLY with MCP send/);
  assert.doesNotMatch(wire.arguments.prompt,/what is two plus two/);
 }finally{delete process.env.CODEX_APP_TOOLS_CALLER_HOST_ID;await app.close();}
});
