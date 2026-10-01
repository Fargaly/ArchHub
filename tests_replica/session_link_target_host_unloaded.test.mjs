import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

// Courts for targets on a host whose task manager does not hold the
// conversation. With an explicit target hostId the app skips its cross-host
// lookup and starts the turn from that host's in-memory record; for an unloaded
// "durable" task the workspace falls back to "/" and the app-server rejects the
// turn after the post was submitted. Such a target is refused BEFORE any post.
// Isolated: temp HOME and state dir, a private mock app pipe; nothing live.
const BS=String.fromCharCode(92);
const pipe=name=>BS+BS+'.'+BS+'pipe'+BS+'LOCAL'+BS+name+'-'+crypto.randomUUID();
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-unloaded-'));
process.env.HOME=home;
process.env.SESSION_LINK_STATE_DIR=path.join(home,'state');
fs.mkdirSync(path.join(process.env.SESSION_LINK_STATE_DIR,'connections'),{recursive:true});
for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','CODEX_APP_TOOLS_CALLER_HOST_ID','SESSION_LINK_PRODUCT_WORKER'])delete process.env[k];
const lib=path.join(import.meta.dirname,'..','nodelang','session_link');
const load=file=>import(pathToFileURL(path.join(lib,file)).href);
const native=await load('native.mjs');
const bridge=await load('bridge.mjs');
test.after(()=>fs.rmSync(home,{recursive:true,force:true}));

const CALLER='01a0cafe-0000-7000-8000-000000000001',TARGET='01a0f223-0000-7000-8000-000000000002';
const row=hostId=>({id:TARGET,kind:'codex',projectId:null,...(hostId===undefined?{}:{hostId}),status:{type:'active',activeFlags:[]},cwd:'C:/fixture',updatedAt:1790000000000,title:'T'});
const bound=executorHostId=>({id:'0123456789abcdef',codex:{id:TARGET},executor:CALLER,...(executorHostId===undefined?{}:{executorHostId})});

function mockCodexApp(threads){
 const calls=[],name=pipe('sl-unloaded-app');
 const server=net.createServer(sock=>{let buf=Buffer.alloc(0);sock.on('error',()=>{});sock.on('data',chunk=>{
  buf=Buffer.concat([buf,chunk]);
  while(buf.length>=4){
   const n=buf.readUInt32LE(0);if(buf.length<n+4)return;
   const msg=JSON.parse(buf.subarray(4,n+4).toString('utf8'));buf=buf.subarray(n+4);calls.push(msg.params?.tool);
   const reply=msg.params?.tool==='list_threads'
    ?{id:msg.id,jsonrpc:'2.0',result:{contentItems:[{type:'inputText',text:JSON.stringify({schemaVersion:4,pinnedThreads:[],threads,unavailableHosts:[],unavailableSources:[]})}],success:true}}
    :{id:msg.id,jsonrpc:'2.0',result:{contentItems:[{type:'inputText',text:'{}'}],success:true}};
   const body=Buffer.from(JSON.stringify(reply)),head=Buffer.alloc(4);head.writeUInt32LE(body.length);sock.write(Buffer.concat([head,body]));
  }
 });});
 return new Promise(resolve=>server.listen(name,()=>resolve({name,calls,close:()=>new Promise(done=>server.close(done))})));
}
const inCodexTask=async(app,body,callerHost)=>{
 process.env.CODEX_APP_TOOLS_PIPE_PATH=app.name;process.env.CODEX_THREAD_ID=CALLER;
 if(callerHost)process.env.CODEX_APP_TOOLS_CALLER_HOST_ID=callerHost;
 try{return await body();}finally{for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','CODEX_APP_TOOLS_CALLER_HOST_ID'])delete process.env[k];}
};
const unloaded=e=>e.code==='SESSION_LINK_TARGET_HOST_UNLOADED'&&/host "durable"/.test(e.message)&&/not sent/.test(e.message);

test('bound send: a durable target from another caller host is refused before the call is built',()=>{
 for(const caller of [undefined,'local','host-caller-a'])
  assert.throws(()=>bridge.boundSendCall(bound(caller),row('durable'),'hello','m1'),unloaded,String(caller));
});

test('bound send: same-host, local and host-less targets are unchanged',()=>{
 const cases=[[undefined,undefined,{}],['durable','durable',{hostId:'durable'}],['local','local',{hostId:'local'}],['host-caller-a','host-target-b',{hostId:'host-target-b'}]];
 for(const [caller,target,hostArg] of cases){
  const [tool,args,executor,ctx]=bridge.boundSendCall(bound(caller),row(target),'hello','m2');
  assert.equal(tool,'send_message_to_thread');
  assert.deepEqual(args,{threadId:TARGET,prompt:'hello',...hostArg});
  assert.equal(executor,CALLER);assert.equal(ctx.requestId,'m2');
 }
});

test('direct post from a Codex task: durable cross-host target makes zero posts',async()=>{
 for(const caller of [undefined,'host-caller-a']){
  const app=await mockCodexApp([row('durable')]);
  try{
   await assert.rejects(inCodexTask(app,()=>native.postCodex(TARGET,'hello',{requestId:'r1'}),caller),unloaded);
   assert.deepEqual(app.calls,['list_threads'],'only the read; no send_message_to_thread');
  }finally{await app.close();}
 }
});

test('direct post from a Codex task: same-host durable and local targets post exactly once',async()=>{
 for(const [caller,target] of [['durable','durable'],[undefined,'local'],[undefined,undefined]]){
  const app=await mockCodexApp([row(target)]);
  try{
   await inCodexTask(app,()=>native.postCodex(TARGET,'hello',{requestId:'r2'}),caller);
   assert.deepEqual(app.calls,['list_threads','send_message_to_thread']);
  }finally{await app.close();}
 }
});
