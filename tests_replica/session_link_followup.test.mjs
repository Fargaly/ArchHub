import test from 'node:test';
import assert from 'node:assert/strict';
import {PeerEndpoint} from '../nodelang/session_link/vendor/src/peer-protocol.mjs';

// No peer.start(), sockets, registry writes or native app calls. The real
// pending/queue machinery runs; only the socket write is injected and logged.
function fixture(){
 const peer=new PeerEndpoint({name:'followup-fixture',cwd:'fixture'});
 const log=[];
 peer.send=async(socket,text,{msgId})=>{log.push({socket,text,msgId});return msgId;};
 return {peer,log};
}

test('an informational report creates no pending reply and never blocks the next send',{timeout:5000},async()=>{
 const {peer,log}=fixture();
 const report=await peer.sendAndWait('s','status: build green',{timeoutMs:0,kind:'report'});
 assert.equal(report.reply,null);
 assert.equal(peer.pendingMessages.size,0);
 assert.equal(peer.unconfirmedReplies.size,0);
 assert.equal(peer.readDelivery(report.msgId).status,'sent_unconfirmed');
 const request=await peer.sendAndWait('s','question',{timeoutMs:0});
 assert.ok(peer.pendingMessages.has(request.msgId));
 assert.equal(log.length,2);
});

test('a report is allowed while a request is pending and still adds no pending entry',{timeout:5000},async()=>{
 const {peer,log}=fixture();
 const request=await peer.sendAndWait('s','question',{timeoutMs:0});
 await peer.sendAndWait('s','fyi',{timeoutMs:0,kind:'report'});
 assert.deepEqual([...peer.pendingMessages.keys()],[request.msgId]);
 assert.equal(peer.unconfirmedReplies.get('s'),1);
 assert.equal(log.length,2);
});

test('reports are rate bounded: one in flight per socket',{timeout:5000},async()=>{
 const peer=new PeerEndpoint({name:'rate-fixture',cwd:'fixture'});
 let release;const gate=new Promise(r=>{release=r;});let sends=0;
 peer.send=async(socket,text,{msgId})=>{sends++;await gate;return msgId;};
 const first=peer.sendAndWait('s','report one',{timeoutMs:0,kind:'report'});
 const second=peer.sendAndWait('s','report two',{timeoutMs:0,kind:'report'});
 release();
 await assert.rejects(second,{code:'PEER_REPORT_IN_FLIGHT'});
 await first;
 await peer.sendAndWait('s','report three',{timeoutMs:0,kind:'report'});
 assert.equal(sends,2);
});

test('a status follow-up tied to the pending id passes; an unrelated second request is still refused',{timeout:5000},async()=>{
 const {peer,log}=fixture();
 const request=await peer.sendAndWait('s','ORIGINAL-EFFECT: write file X',{timeoutMs:0});
 const follow=await peer.sendAndWait('s','still waiting on step 2',{timeoutMs:0,kind:'followup',followupOf:request.msgId});
 assert.equal(follow.followupOf,request.msgId);
 assert.equal(follow.reply,null);
 assert.deepEqual([...peer.pendingMessages.keys()],[request.msgId]);
 await assert.rejects(peer.sendAndWait('s','new unrelated request',{timeoutMs:0}),{code:'PEER_REPLY_PENDING'});
 await assert.rejects(peer.sendAndWait('s','x',{timeoutMs:0,kind:'followup',followupOf:'not-a-pending-id'}),{code:'PEER_FOLLOWUP_NO_PENDING_ORIGINAL'});
 assert.equal(log.length,2);
 assert.ok(log[1].text.includes(request.msgId));
});

test('a duplicate follow-up for the same original id is refused until the original resolves',{timeout:5000},async()=>{
 const {peer,log}=fixture();
 const request=await peer.sendAndWait('s','question',{timeoutMs:0});
 await peer.sendAndWait('s','status 1',{timeoutMs:0,kind:'followup',followupOf:request.msgId});
 await assert.rejects(peer.sendAndWait('s','status 2',{timeoutMs:0,kind:'followup',followupOf:request.msgId}),{code:'PEER_FOLLOWUP_DUPLICATE'});
 assert.equal(log.length,2);
});

test('nothing is replayed: a follow-up never re-sends the original text or id',{timeout:5000},async()=>{
 const {peer,log}=fixture();
 const request=await peer.sendAndWait('s','ORIGINAL-EFFECT: write file X',{timeoutMs:0});
 await peer.sendAndWait('s','status only',{timeoutMs:0,kind:'followup',followupOf:request.msgId});
 const ids=log.map(e=>e.msgId);
 assert.equal(new Set(ids).size,ids.length);
 assert.equal(log.filter(e=>e.text.includes('ORIGINAL-EFFECT')).length,1);
 assert.equal(log.filter(e=>e.msgId===request.msgId).length,1);
});
// ---- Real receive path: two started endpoints on real local sockets. The
// recipient's frames are written to the sender's socket exactly as a native
// peer writes them (auth line, then the frame). HOME is a temp dir so no live
// session registry is touched.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {buildFrame} from '../nodelang/session_link/vendor/src/peer-protocol.mjs';

async function pair(){
 const home=fs.mkdtempSync(path.join(os.tmpdir(),'sl-followup-'));
 const saved={HOME:process.env.HOME,USERPROFILE:process.env.USERPROFILE};
 process.env.HOME=home;process.env.USERPROFILE=home;
 const sender=new PeerEndpoint({name:'fixture-sender',cwd:home,log:()=>{}});
 const recipient=new PeerEndpoint({name:'fixture-recipient',cwd:home,log:()=>{}});
 await sender.start();await recipient.start();
 const inject=(frame)=>new Promise((resolve,reject)=>{
  const socket=net.connect(sender.socketPath,()=>{
   socket.end(JSON.stringify({type:'auth',token:sender.peerToken})+'\n'+JSON.stringify(frame)+'\n',resolve);
  });
  socket.on('error',reject);
 });
 const from=buildFrame({fromSocket:recipient.socketPath,text:''}).from;
 const status=(orig,s)=>inject({type:'control',action:'peer_message_status',orig_msg_id:orig,from,status:s,reason:'fixture'});
 const reply=(text)=>inject(buildFrame({fromSocket:recipient.socketPath,text}));
 const close=()=>{sender.stop();recipient.stop();process.env.HOME=saved.HOME;process.env.USERPROFILE=saved.USERPROFILE;
  if(saved.HOME===undefined)delete process.env.HOME;if(saved.USERPROFILE===undefined)delete process.env.USERPROFILE;
  try{fs.rmSync(home,{recursive:true,force:true});}catch{}};
 return {sender,recipient,status,reply,close};
}
async function until(cond,ms=2000){const end=Date.now()+ms;while(!cond()){if(Date.now()>end)throw new Error('condition not reached');await new Promise(r=>setTimeout(r,20));}}

test('real receive path: held/refused receipts are recorded for a report and a follow-up; the original is untouched',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const a=await f.sender.sendAndWait(f.recipient.socketPath,'question A',{timeoutMs:0});
  const b=await f.sender.sendAndWait(f.recipient.socketPath,'fyi B',{timeoutMs:0,kind:'report'});
  const c=await f.sender.sendAndWait(f.recipient.socketPath,'status on A',{timeoutMs:0,kind:'followup',followupOf:a.msgId});
  await f.status(b.msgId,'held');await f.status(c.msgId,'refused');
  await until(()=>f.sender.readDelivery(b.msgId)?.status==='held'&&f.sender.readDelivery(c.msgId)?.status==='refused');
  assert.equal(f.sender.readDelivery(b.msgId).reason,'fixture');
  assert.ok(f.sender.pendingMessages.has(a.msgId));
  assert.equal(f.sender.deliveryReceipts.has(a.msgId),false);
  assert.equal(f.sender.unconfirmedReplies.get(f.recipient.socketPath),1);
 }finally{f.close();}
});

async function overlapped(f){
 const seen=[];f.sender.onMessage(r=>seen.push(r));
 const a=await f.sender.sendAndWait(f.recipient.socketPath,'question A',{timeoutMs:0});
 const b=await f.sender.sendAndWait(f.recipient.socketPath,'fyi B',{timeoutMs:0,kind:'report'});
 return {a,b,seen};
}
const stillPending=(f,a)=>{assert.ok(f.sender.pendingMessages.has(a.msgId));assert.notEqual(f.sender.readDelivery(a.msgId).status,'reply_received');};

test('real receive path: B delivered, then an uncited reply leaves A pending and is surfaced',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const {a,b,seen}=await overlapped(f);
  await f.status(b.msgId,'delivered');
  await until(()=>f.sender.readDelivery(b.msgId)?.status==='delivered');
  await f.reply('thanks for the report');
  await until(()=>seen.length===1);
  stillPending(f,a);
  assert.equal(seen[0].unattributed,true);
  assert.ok(f.sender.inbox.includes(seen[0]));
 }finally{f.close();}
});

test('real receive path: a delayed reply to B leaves A pending',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const {a,seen}=await overlapped(f);
  await new Promise(r=>setTimeout(r,400));
  await f.reply('late answer about the report');
  await until(()=>seen.length===1);
  stillPending(f,a);
 }finally{f.close();}
});

test('real receive path: two uncited replies and an incidental id mention leave A pending',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const {a,seen}=await overlapped(f);
  await f.reply('first uncited');await f.reply('second uncited');
  await f.reply('I saw '+a.msgId+' earlier');
  await until(()=>seen.length===3);
  stillPending(f,a);
  assert.ok(seen.every(r=>r.unattributed===true));
 }finally{f.close();}
});

test('real receive path: a leading [re:A] marker clears exactly A',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const {a,seen}=await overlapped(f);
  await f.reply('[re:'+a.msgId+'] done');
  await until(()=>seen.length===1);
  assert.equal(f.sender.pendingMessages.size,0);
  assert.equal(f.sender.unconfirmedReplies.size,0);
  assert.equal(f.sender.readDelivery(a.msgId).status,'reply_received');
  assert.equal(seen[0].inReplyTo,a.msgId);
 }finally{f.close();}
});

test('settle clears only the caller own pending msgId on its own connection, sends nothing',{timeout:8000},async()=>{
 const {peer,log}=fixture();
 const a=await peer.sendAndWait('s','question A',{timeoutMs:0});
 await peer.sendAndWait('s','status',{timeoutMs:0,kind:'followup',followupOf:a.msgId});
 const sends=log.length;
 assert.throws(()=>peer.settle(a.msgId,'answered',{targetSocket:'other-connection'}),/not pending on this connection/);
 assert.throws(()=>peer.settle('unknown-id','answered',{targetSocket:'s'}),/not pending/);
 assert.throws(()=>peer.settle(a.msgId,'whatever',{targetSocket:'s'}),/answered\|abandoned/);
 assert.ok(peer.pendingMessages.has(a.msgId));
 assert.deepEqual(peer.settle(a.msgId,'abandoned',{targetSocket:'s'}),{msgId:a.msgId,settled:'abandoned'});
 assert.equal(peer.pendingMessages.size,0);
 assert.equal(peer.unconfirmedReplies.size,0);
 assert.equal(peer.activeFollowups.size,0);
 assert.equal(peer.readDelivery(a.msgId).status,'settled_abandoned');
 assert.equal(log.length,sends);
 await peer.sendAndWait('s','next request',{timeoutMs:0});
});
test('real receive path: report, then request A (carries its [re:A] instruction), then an uncited reply leaves A pending',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const got=[];f.recipient.onMessage(r=>got.push(r));
  const seen=[];f.sender.onMessage(r=>seen.push(r));
  await f.sender.sendAndWait(f.recipient.socketPath,'fyi first',{timeoutMs:0,kind:'report'});
  const a=await f.sender.sendAndWait(f.recipient.socketPath,'question A',{timeoutMs:0});
  await until(()=>got.length===2);
  assert.ok(got[1].text.includes('[re:'+a.msgId+']'));
  await f.reply('uncited answer');
  await until(()=>seen.length===1);
  stillPending(f,a);
  assert.equal(seen[0].unattributed,true);
 }finally{f.close();}
});

test('real receive path: A+B, exact reply to A, request C, late [re:B] reply leaves C pending',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const {a,b,seen}=await overlapped(f);
  await f.reply('[re:'+a.msgId+'] done');
  await until(()=>seen.length===1);
  assert.equal(f.sender.readDelivery(a.msgId).status,'reply_received');
  const c=await f.sender.sendAndWait(f.recipient.socketPath,'question C',{timeoutMs:0});
  await f.reply('[re:'+b.msgId+'] late note on the report');
  await until(()=>seen.length===2);
  stillPending(f,c);
  assert.equal(seen[1].informationalFor,b.msgId);
  assert.equal(f.sender.sentMessages.get(b.msgId).informational.length,1);
  assert.notEqual(f.sender.readDelivery(b.msgId).status,'reply_received');
 }finally{f.close();}
});

test('real receive path: an unmatched [re:X] never clears A',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const {a,seen}=await overlapped(f);
  await f.reply('[re:00000000-0000-4000-8000-000000000000] stray');
  await f.reply('[re:'+a.msgId+'x] near miss');
  await until(()=>seen.length===2);
  stillPending(f,a);
  assert.ok(seen.every(r=>r.unattributed===true));
 }finally{f.close();}
});

test('reload: a delivered report and follow-up do not block export/import; explicit mode persists',{timeout:8000},async()=>{
 const f=await pair();
 try{
  const seen=[];f.sender.onMessage(r=>seen.push(r));
  const a=await f.sender.sendAndWait(f.recipient.socketPath,'question A',{timeoutMs:0});
  const b=await f.sender.sendAndWait(f.recipient.socketPath,'fyi B',{timeoutMs:0,kind:'report'});
  const c=await f.sender.sendAndWait(f.recipient.socketPath,'status on A',{timeoutMs:0,kind:'followup',followupOf:a.msgId});
  await f.status(b.msgId,'delivered');await f.status(c.msgId,'delivered');
  await f.reply('[re:'+a.msgId+'] done');
  await until(()=>seen.length===1&&f.sender.readDelivery(c.msgId)?.status==='delivered');
  assert.equal(f.sender.readDelivery(b.msgId).status,'delivered');
  await until(()=>f.sender.connections.size===0);
  assert.equal(f.sender.reloadReason(),null);
  await f.sender.quiesce();
  const state=f.sender.exportReloadState();
  const next=new PeerEndpoint({name:'fixture-next',cwd:'fixture',log:()=>{}});
  next.restoreReloadState(state);
  assert.equal(next.reloadReason(),null);
  assert.ok(next.explicitSockets.has(f.recipient.socketPath));
  assert.equal(next.readDelivery(b.msgId).status,'delivered');
  assert.equal(next.readDelivery(a.msgId).status,'reply_received');
 }finally{f.close();}
});
// Both fixture endpoints live in this one process. The key check for this
// process must not spawn a fresh identity probe per send: under load the probe
// times out, returns '', and a live inbox was refused as "key missing or
// invalid". Here the probe is made unreachable after start() to force that.
test('real receive path: an unavailable process-identity probe does not refuse delivery to an inbox owned by this process',{timeout:8000,skip:process.platform!=='win32'},async()=>{
 const f=await pair();
 const savedRoot=process.env.SystemRoot;
 try{
  process.env.SystemRoot=path.join(os.tmpdir(),'sl-followup-no-such-root');
  const got=[];f.recipient.onMessage(r=>got.push(r));
  await f.sender.sendAndWait(f.recipient.socketPath,'fyi under load',{timeoutMs:0,kind:'report'});
  await until(()=>got.length===1);
 }finally{process.env.SystemRoot=savedRoot;f.close();}
});
