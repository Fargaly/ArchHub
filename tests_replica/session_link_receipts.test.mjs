import test from 'node:test';
import assert from 'node:assert/strict';
import {PeerEndpoint,publicDeliveryReceipt} from '../nodelang/session_link/vendor/src/peer-protocol.mjs';

// No peer.start(), sockets, registry writes or native app calls. Exercise the
// actual pending/receipt/wait machinery with one injected write completion.
for(const status of ['held','refused','rejected'])test('registered receipt ends wait: '+status,async()=>{
 const peer=new PeerEndpoint({name:'receipt-fixture',cwd:'fixture'});
 let sends=0;
 peer.send=async(socket,text,{msgId})=>{
  sends++;
  assert.equal(peer.pendingMessages.get(msgId)?.targetSocket,socket);
  peer.deliveryReceipts.set(msgId,{status,fromSocket:socket,reason:'fixture'});
  return msgId;
 };
 const started=Date.now();
 const result=await peer.sendAndWait('fixture-socket','fixture',{timeoutMs:1500});
 assert.equal(result.delivery.status,status);
 assert.equal(result.reply,null);
 assert.ok(Date.now()-started<1000);
 assert.equal(sends,1);
 if(status==='held'){
  await assert.rejects(peer.sendAndWait('fixture-socket','no retry',{timeoutMs:10}),/earlier message/);
  assert.equal(sends,1);
 }
});

test('public receipt retains bounded reason and never the auth envelope',()=>{
 const result=publicDeliveryReceipt({status:'held',reason:'Exact diagnostic\nreason',token:'secret',fromSocket:'private-pipe'});
 assert.deepEqual(result,{delivery_status:'held',delivery_reason:'Exact diagnostic reason'});
 assert.equal(publicDeliveryReceipt({status:'held',reason:'x'.repeat(600)}).delivery_reason.length,512);
 const hidden=publicDeliveryReceipt({status:'held',reason:'token=secret-value'});
 assert.ok(!hidden.delivery_reason.includes('secret-value'));
});
