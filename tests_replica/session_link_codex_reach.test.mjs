import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

// Courts for Session Link reaching Codex tasks. Isolated: temp HOME (Claude
// session registry), temp SESSION_LINK_STATE_DIR, private LOCAL pipes. No live
// app, session, bridge or message is touched.
const BS=String.fromCharCode(92),NL=String.fromCharCode(10);
const pipe=name=>BS+BS+'.'+BS+'pipe'+BS+'LOCAL'+BS+name+'-'+crypto.randomUUID();
const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-court-'));
process.env.HOME=home;
process.env.SESSION_LINK_STATE_DIR=path.join(home,'state');
const connections=path.join(process.env.SESSION_LINK_STATE_DIR,'connections');
const sessions=path.join(home,'.claude','sessions');
fs.mkdirSync(connections,{recursive:true});fs.mkdirSync(sessions,{recursive:true});
for(const k of ['CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','SESSION_LINK_PRODUCT_WORKER'])delete process.env[k];
const lib=path.join(import.meta.dirname,'..','nodelang','session_link');
const load=file=>import(pathToFileURL(path.join(lib,file)).href);
const {catalog}=await load('bridge.mjs');
const {ask}=await load('ask.mjs');
const {PeerEndpoint}=await load('vendor/src/peer-protocol.mjs');
const {setAttachment}=await load('native.mjs');
test.after(()=>fs.rmSync(home,{recursive:true,force:true}));

const PING='01a07b65-f0c4-7040-a218-d703384679a0',CALLER='01a0cafe-0000-7000-8000-000000000001',CLAUDE='c4c4c4c4-0000-4000-8000-000000000004';
// Row shape: Codex 26.924 app.asar list_threads builder (schemaVersion 4;
// rows {id,kind:'codex',projectId,hostId,status,cwd,updatedAt,title,summary,isUnread};
// status {type:'active',activeFlags}).
const row=(id,title)=>({id,kind:'codex',projectId:null,hostId:null,status:{type:'active',activeFlags:[]},cwd:'C:/fixture',updatedAt:1790000000000,title,summary:null,isUnread:false});

// Mock of the Codex Desktop dynamic app tools pipe. Request contract from
// Codex 26.924: app.asar tools/call schema (arguments, callerSource in
// codex|chatgpt, callId, namespace, threadId, tool, turnId, each a non-empty
// string except arguments) and the bundled plugins/openai-bundled/plugins/
// codex-app-tools/server.mjs NativePipeClient (4-byte LE length frames).
// Refusal code and text verbatim from app.asar; success result
// {contentItems:[{type:'inputText',text}],success} from server.mjs.
function mockCodexApp(threads){
 const calls=[],name=pipe('sl-court-app');
 const server=net.createServer(sock=>{let buf=Buffer.alloc(0);sock.on('error',()=>{});sock.on('data',chunk=>{
  buf=Buffer.concat([buf,chunk]);
  while(buf.length>=4){
   const n=buf.readUInt32LE(0);if(buf.length<n+4)return;
   const msg=JSON.parse(buf.subarray(4,n+4).toString('utf8'));buf=buf.subarray(n+4);calls.push(msg);
   const p=msg.params,str=v=>typeof v==='string'&&v.trim().length>0;
   const valid=msg.jsonrpc==='2.0'&&msg.method==='tools/call'&&p&&typeof p==='object'&&('arguments' in p)&&
    ['codex','chatgpt'].includes(p.callerSource)&&str(p.callId)&&str(p.namespace)&&str(p.threadId)&&str(p.tool)&&str(p.turnId);
   let reply;
   if(!valid)reply={error:{code:-32602,message:'Invalid app tool request'},id:msg.id,jsonrpc:'2.0'};
   else if(p.tool==='list_threads')reply={id:msg.id,jsonrpc:'2.0',result:{contentItems:[{type:'inputText',text:JSON.stringify({schemaVersion:4,pinnedThreads:[],threads,unavailableHosts:[],unavailableSources:[]})}],success:true}};
   else reply={id:msg.id,jsonrpc:'2.0',result:{contentItems:[{type:'inputText',text:'{}'}],success:true}};
   const body=Buffer.from(JSON.stringify(reply)),head=Buffer.alloc(4);head.writeUInt32LE(body.length);sock.write(Buffer.concat([head,body]));
  }
 });});
 return new Promise(resolve=>server.listen(name,()=>resolve({name,calls,close:()=>new Promise(done=>server.close(done))})));
}
const inCodexTask=async(app,body)=>{process.env.CODEX_APP_TOOLS_PIPE_PATH=app.name;process.env.CODEX_THREAD_ID=CALLER;
 try{return await body();}finally{delete process.env.CODEX_APP_TOOLS_PIPE_PATH;delete process.env.CODEX_THREAD_ID;}};

test('C1 Codex task discovery sends the callerSource the Codex 26.924 app requires',async()=>{
 const app=await mockCodexApp([row(PING,'Ping')]);
 try{
  const all=await inCodexTask(app,()=>catalog({apps:['codex']}));
  assert.deepEqual(all.codex.map(t=>t.id),[PING]);
  assert.equal(app.calls[0].params.callerSource,'codex');
  assert.equal(app.calls[0].params.tool,'list_threads');
 }finally{await app.close();}
});

test('C2 without Codex app context the empty list says why, and ask names that reason',async()=>{
 const all=await catalog({apps:['codex']});
 assert.deepEqual(all.codex,[]);
 assert.equal(all.adapterStatus?.codex?.status,'unavailable');
 assert.match(all.adapterStatus.codex.reason,/Codex Desktop task/);
 await assert.rejects(ask('codex',PING,'hello'),/Codex tasks unavailable: No live Session Link bridge/);
});

test('C3 Claude asks a Codex task by exact id through a live bridge and receives its answer',async()=>{
 const token=crypto.randomBytes(16).toString('hex'),keyPath=path.join(home,'bridge.key'),control=pipe('sl-court-bridge');
 fs.writeFileSync(keyPath,JSON.stringify({peerToken:token}));
 const posted=[],answered=[];
 const answerAsPing=async text=>{
  const id=/Session Link request ([0-9a-f-]{36})/.exec(text)[1];
  const req=JSON.parse(fs.readFileSync(path.join(process.env.SESSION_LINK_STATE_DIR,'requests',id+'.json'),'utf8'));
  const peerToken=JSON.parse(fs.readFileSync(req.keyPath,'utf8')).peerToken;
  answered.push(await new Promise((resolve,reject)=>{const s=net.connect(req.control);let d='';s.setEncoding('utf8');s.on('error',reject);
   s.on('connect',()=>s.write(JSON.stringify({token:peerToken,session:PING,text:'pong from Ping'})+NL));
   s.on('data',c=>{d+=c;if(d.includes(NL)){s.destroy();resolve(JSON.parse(d));}});}));
 };
 const server=net.createServer(sock=>{let d='';sock.setEncoding('utf8');sock.on('error',()=>{});sock.on('data',c=>{d+=c;if(!d.includes(NL))return;
  const r=JSON.parse(d.slice(0,d.indexOf(NL)));let result;
  if(r.token!==token){sock.end(JSON.stringify({ok:false,error:'Unauthenticated request'})+NL);return;}
  if(r.operation==='list')result={claude:[],codex:[{id:PING,title:'Ping',cwd:'C:/fixture',app:'codex'}]};
  else if(r.operation==='capabilities')result={postCodex:true,ask:true,scopedAttachment:true};
  else if(r.operation==='post-codex'){posted.push(r);result={submitted:true};setTimeout(()=>answerAsPing(r.text),20);}
  sock.end(JSON.stringify({ok:true,result})+NL);
 });});
 await new Promise(resolve=>server.listen(control,resolve));
 const runtime=path.join(connections,'c3c3c3c3c3c3c3c3.runtime.json');
 fs.writeFileSync(runtime,JSON.stringify({id:'c3c3c3c3c3c3c3c3',pid:process.pid,control,keyPath}));
 try{
  const result=await ask('codex',PING,'ping from Claude');
  assert.equal(result.text,'pong from Ping');
  assert.equal(posted.length,1);assert.equal(posted[0].threadId,PING);
  for(let i=0;i<50&&!answered.length;i++)await new Promise(r=>setTimeout(r,20));
  assert.deepEqual(answered,[{ok:true}]);
 }finally{fs.rmSync(runtime,{force:true});await new Promise(done=>server.close(done));}
});

test('C4 a Codex task asking Claude gets a durable reply peer on the persistent bridge',async()=>{
 const app=await mockCodexApp([row(CALLER,'Caller')]);
 const entry=path.join(sessions,process.ppid+'.json');
 fs.writeFileSync(entry,JSON.stringify({pid:process.ppid,sessionId:CLAUDE,cwd:'C:/fixture',name:'Claude fixture',messagingSocketPath:pipe('cc-msg-fixture'),startedAt:Date.now()}));
 const original=PeerEndpoint.prototype.sendAndWait,sent=[],links=[];
 PeerEndpoint.prototype.sendAndWait=async function(socket,text){sent.push({socket,text});return {msgId:'m1',delivery:null,reply:{msgId:'r1',text:'ack'}};};
 const connectLink=async(request,{observedCatalog})=>{links.push({request,observedCatalog});return {id:'d4d4d4d4d4d4d4d4',peer:'codex-01a0cafe-d4d4'};};
 try{
  const result=await inCodexTask(app,()=>ask('claude',CLAUDE,'hello Claude','prompting',{connectLink}));
  assert.equal(links.length,1);
  assert.deepEqual(links[0].request,{app:'claude',claude:CLAUDE,codex:CALLER,permissionMode:'prompting'});
  assert.ok(links[0].observedCatalog.codex.some(t=>t.id===CALLER));
  assert.ok(links[0].observedCatalog.claude.some(s=>s.id===CLAUDE));
  assert.equal(sent.length,1);
  assert.match(sent[0].text,/use native SendMessage to peer codex-01a0cafe-d4d4 /);
  assert.equal(result.text,'ack');
  assert.deepEqual(result.durable_reply,{connection:'d4d4d4d4d4d4d4d4',peer:'codex-01a0cafe-d4d4'});
 }finally{PeerEndpoint.prototype.sendAndWait=original;fs.rmSync(entry,{force:true});await app.close();}
});
test('C5 a one-off bypass ask never creates a bypass durable link',async()=>{
 const app=await mockCodexApp([row(CALLER,'Caller')]);
 const entry=path.join(sessions,process.ppid+'.json');
 fs.writeFileSync(entry,JSON.stringify({pid:process.ppid,sessionId:CLAUDE,cwd:'C:/fixture',name:'Claude fixture',messagingSocketPath:pipe('cc-msg-fixture'),startedAt:Date.now()}));
 const original=PeerEndpoint.prototype.sendAndWait,modes=[],links=[];
 PeerEndpoint.prototype.sendAndWait=async function(socket,text,options){modes.push(options.permissionMode);return {msgId:'m1',delivery:null,reply:{msgId:'r1',text:'ack'}};};
 const connectLink=async request=>{links.push(request);return {id:'d5d5d5d5d5d5d5d5',peer:'codex-01a0cafe-d5d5'};};
 try{
  await inCodexTask(app,()=>ask('claude',CLAUDE,'one-off','bypass',{connectLink}));
  assert.equal(links.length,1);
  assert.equal(links[0].permissionMode,'prompting');
  assert.deepEqual(modes,['bypass']);
 }finally{PeerEndpoint.prototype.sendAndWait=original;fs.rmSync(entry,{force:true});await app.close();}
});

test('C6 a failed Codex attachment reports a reason, never undefined',async()=>{
 setAttachment({control:pipe('sl-court-gone'),destination:PING,expires_at:Date.now()-1000});
 try{
  const all=await catalog({apps:['codex']});
  assert.equal(all.adapterStatus.codex.status,'unavailable');
  assert.equal(typeof all.adapterStatus.codex.reason,'string');
  assert.ok(all.adapterStatus.codex.reason.length>0);
  await assert.rejects(ask('codex',PING,'hello'),err=>/^Codex tasks unavailable: /.test(err.message)&&!/undefined/.test(err.message));
 }finally{setAttachment(null);}
});