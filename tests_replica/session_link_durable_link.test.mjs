import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

// Courts for durable link reuse and Codex app-tool failures. Isolated: temp
// HOME and state, private LOCAL pipes. The existing link is a real runtime and
// binding on disk answered by a mock bridge control endpoint; ask() runs the
// real connect(). Claude delivery is intercepted, so nothing is ever sent.
const BS=String.fromCharCode(92),NL=String.fromCharCode(10);
const pipe=name=>BS+BS+'.'+BS+'pipe'+BS+'LOCAL'+BS+name+'-'+crypto.randomUUID();
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-reuse-'));
process.env.HOME=home;
process.env.SESSION_LINK_STATE_DIR=path.join(home,'state');
const connections=path.join(process.env.SESSION_LINK_STATE_DIR,'connections'),sessions=path.join(home,'.claude','sessions');
fs.mkdirSync(connections,{recursive:true});fs.mkdirSync(sessions,{recursive:true});
for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','SESSION_LINK_PRODUCT_WORKER'])delete process.env[k];
const lib=path.join(import.meta.dirname,'..','nodelang','session_link');
const load=file=>import(pathToFileURL(path.join(lib,file)).href);
const {catalog}=await load('bridge.mjs');
const {ask}=await load('ask.mjs');
const {PeerEndpoint}=await load('vendor/src/peer-protocol.mjs');
test.after(()=>fs.rmSync(home,{recursive:true,force:true}));

const CALLER='01a0cafe-0000-7000-8000-000000000001',OTHER='01a0dead-0000-7000-8000-000000000002',CLAUDE='c4c4c4c4-0000-4000-8000-000000000004';
const ID=crypto.createHash('sha256').update(CLAUDE+'|'+CALLER).digest('hex').slice(0,16);
// list_threads row shape: Codex 26.924 app.asar (schemaVersion 4).
const row=(id,title)=>({id,kind:'codex',projectId:null,hostId:null,status:{type:'active',activeFlags:[]},cwd:'C:/fixture',updatedAt:1790000000000,title,summary:null,isUnread:false});
// Mock Codex app tools pipe (Codex 26.924 framing and refusal shape).
function mockCodexApp(threads,{refuse=false}={}){
 const name=pipe('sl-reuse-app');
 const server=net.createServer(sock=>{let buf=Buffer.alloc(0);sock.on('error',()=>{});sock.on('data',chunk=>{
  buf=Buffer.concat([buf,chunk]);
  while(buf.length>=4){
   const n=buf.readUInt32LE(0);if(buf.length<n+4)return;
   const msg=JSON.parse(buf.subarray(4,n+4).toString('utf8'));buf=buf.subarray(n+4);
   const reply=refuse||msg.params?.callerSource!=='codex'?{error:{code:-32602,message:'Invalid app tool request'},id:msg.id,jsonrpc:'2.0'}:
    {id:msg.id,jsonrpc:'2.0',result:{contentItems:[{type:'inputText',text:JSON.stringify({schemaVersion:4,pinnedThreads:[],threads,unavailableHosts:[],unavailableSources:[]})}],success:true}};
   const body=Buffer.from(JSON.stringify(reply)),head=Buffer.alloc(4);head.writeUInt32LE(body.length);sock.write(Buffer.concat([head,body]));
  }
 });});
 return new Promise(resolve=>server.listen(name,()=>resolve({name,close:()=>new Promise(done=>server.close(done))})));
}
const inCodexTask=async(pipeName,body)=>{process.env.CODEX_APP_TOOLS_PIPE_PATH=pipeName;process.env.CODEX_THREAD_ID=CALLER;
 try{return await body();}finally{delete process.env.CODEX_APP_TOOLS_PIPE_PATH;delete process.env.CODEX_THREAD_ID;}};

// A live existing link: runtime + binding on disk and a control endpoint that
// answers status the way a running bridge does.
const goodBinding=()=>({id:ID,claude:{id:CLAUDE,title:'Claude fixture',cwd:'C:/fixture',pid:process.ppid,app:'claude'},codex:{id:CALLER,title:'Caller',cwd:'C:/fixture',app:'codex'},executor:CALLER,permissionMode:'prompting'});
const goodStatus=()=>({id:ID,pid:process.pid,remoteApp:'claude',remoteId:CLAUDE,claude:CLAUDE,codex:CALLER,codexTitle:'Caller',peer:'codex-01a0cafe-'+ID.slice(0,4),permissionMode:'prompting',sent:0,forwarded:0,lastError:null});
async function scenario({binding,status}){
 const app=await mockCodexApp([row(CALLER,'Caller')]);
 const token=crypto.randomBytes(16).toString('hex'),keyPath=path.join(home,'link.key'),control=pipe('sl-reuse-link');
 fs.writeFileSync(keyPath,JSON.stringify({peerToken:token}));
 const server=net.createServer(sock=>{let d='';sock.setEncoding('utf8');sock.on('error',()=>{});sock.on('data',c=>{d+=c;if(!d.includes(NL))return;
  const r=JSON.parse(d.slice(0,d.indexOf(NL)));
  sock.end(JSON.stringify(r.token===token&&r.operation==='status'?{ok:true,result:status}:{ok:false,error:'refused'})+NL);});});
 await new Promise(resolve=>server.listen(control,resolve));
 const runtimeFile=path.join(connections,ID+'.runtime.json'),bindingFile=path.join(connections,ID+'.binding.json');
 fs.writeFileSync(runtimeFile,JSON.stringify({...goodStatus(),control,keyPath}));
 if(binding)fs.writeFileSync(bindingFile,JSON.stringify(binding));
 const entry=path.join(sessions,process.ppid+'.json');
 fs.writeFileSync(entry,JSON.stringify({pid:process.ppid,sessionId:CLAUDE,cwd:'C:/fixture',name:'Claude fixture',messagingSocketPath:pipe('cc-msg-fixture'),startedAt:Date.now()}));
 const original=PeerEndpoint.prototype.sendAndWait,sent=[];
 PeerEndpoint.prototype.sendAndWait=async function(socket,text,options){sent.push({text,mode:options.permissionMode});return {msgId:'m1',delivery:null,reply:{msgId:'r1',text:'ack'}};};
 try{
  let result,error;
  try{result=await inCodexTask(app.name,()=>ask('claude',CLAUDE,'hello Claude','prompting'));}catch(e){error=e;}
  return {result,error,sent};
 }finally{
  PeerEndpoint.prototype.sendAndWait=original;
  for(const f of [runtimeFile,bindingFile,entry])fs.rmSync(f,{force:true});
  await new Promise(done=>server.close(done));await app.close();
 }
}

test('R1 the exact live prompting link is reused and advertised',async()=>{
 const {result,error,sent}=await scenario({binding:goodBinding(),status:goodStatus()});
 assert.equal(error,undefined);
 assert.equal(sent.length,1);
 assert.match(sent[0].text,new RegExp('use native SendMessage to peer '+goodStatus().peer+' '));
 assert.deepEqual(result.durable_reply,{connection:ID,peer:goodStatus().peer});
});

const refusals={
 'R2 running link reports another destination task':{status:{...goodStatus(),codex:OTHER}},
 'R3 runtime record without a saved binding':{binding:null},
 'R4 running link reports bypass while the binding says prompting':{status:{...goodStatus(),permissionMode:'bypass'}},
 'R6 saved and running link are bypass':{binding:{...goodBinding(),permissionMode:'bypass'},status:{...goodStatus(),permissionMode:'bypass'}},
 'R7 saved binding is for another workspace':{binding:{...goodBinding(),codex:{...goodBinding().codex,cwd:'C:/elsewhere'}}},
 'R8 runtime record answers as another connection':{status:{...goodStatus(),id:'0123456789abcdef'}},
 'R9 running link reports another remote session':{status:{...goodStatus(),remoteId:'c9c9c9c9-0000-4000-8000-000000000009'}},
};
test('R10 an older bridge that does not report its mode gets the plain reconnect message; nothing sent',async()=>{
 const {error,sent}=await scenario({binding:goodBinding(),status:(({permissionMode,...rest})=>rest)(goodStatus())});
 assert.equal(sent.length,0);
 assert.equal(error?.message,'This connection was made by an older version of Session Link. Reconnect it once (disconnect, then connect) and try again.');
});

test('N3 app pipe paths are redacted: the live value, forward slashes and names with spaces',async()=>{
 const tag=crypto.randomUUID();
 for(const stale of [BS+BS+'.'+BS+'pipe'+BS+'LOCAL'+BS+'sl stale '+tag,'//./pipe/sl-fwd-'+tag,'//./pipe/sl fwd space '+tag]){
  const all=await inCodexTask(stale,()=>catalog({apps:['codex']}));
  const reason=all.adapterStatus?.codex?.reason;
  assert.equal(all.adapterStatus?.codex?.status,'unavailable');
  assert.ok(typeof reason==='string'&&!reason.includes(tag)&&!/pipe[\\/]/i.test(reason),reason);
 }
});

for(const [name,change] of Object.entries(refusals))test(name+': refused and nothing is sent',async()=>{
 const {error,sent}=await scenario({binding:'binding' in change?change.binding:goodBinding(),status:change.status||goodStatus()});
 assert.equal(sent.length,0,'a message was sent');
 assert.ok(error,'ask did not refuse');
 assert.match(error.message,/nothing sent/);
});

test('N1 a Codex app-tool refusal becomes adapterStatus unavailable with a plain reason',async()=>{
 const app=await mockCodexApp([],{refuse:true});
 try{
  const all=await inCodexTask(app.name,()=>catalog({apps:['codex']}));
  assert.deepEqual(all.codex,[]);
  assert.equal(all.adapterStatus?.codex?.status,'unavailable');
  assert.match(all.adapterStatus.codex.reason,/Invalid app tool request/);
 }finally{await app.close();}
});

test('N2 a stale app pipe becomes unavailable without exposing the pipe path',async()=>{
 const stale=pipe('sl-reuse-stale');
 const all=await inCodexTask(stale,()=>catalog({apps:['codex']}));
 assert.equal(all.adapterStatus?.codex?.status,'unavailable');
 assert.equal(typeof all.adapterStatus.codex.reason,'string');
 assert.ok(!all.adapterStatus.codex.reason.includes('sl-reuse-stale'),all.adapterStatus.codex.reason);
 assert.ok(!all.adapterStatus.codex.reason.toLowerCase().includes(BS+'pipe'+BS),all.adapterStatus.codex.reason);
});