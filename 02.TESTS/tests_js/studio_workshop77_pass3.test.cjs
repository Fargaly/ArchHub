const {test}=require('node:test');
const assert=require('node:assert/strict');

const {transport}=require('./workshop72_regression_helpers.cjs');

test('PASS3 task transport reuses admitted Work route, exact task refs and original retry identity',async()=>{
  let create=0,send=0,failSend=true;
  const t=transport({post:async(url,body)=>{
    if(url==='/api/universal/work') {create++;return {ok:true,created_root:'work:newtask01',membership_wire:'wire-new',revision:5,workshop_root:'room-a',workshop_scope:'scope-a'};}
    if(url==='/api/universal/workshop') {send++;if(failSend){failSend=false;throw new Error('fixture lost reply');}return {ok:true,workshop:'room-a',root:'sent-task',revision:6,idempotency_key:body.idempotency_key};}
    throw new Error('Unexpected route '+url);
  }});
  t.transcript.send_category='declared-message';t.transcript.participants[1].is_agent=true;
  await t.api.refreshWorkshop('room-a');t.api.beginWorkshopTask('room-a');
  await assert.rejects(t.api.createWorkshopTask('room-a',{message:'Read the selected objects',target:'agent-a'}),/lost reply/);
  await assert.rejects(t.api.createWorkshopTask('room-a',{message:'Different task',target:'agent-a'}),/Finish the accepted task/);
  await t.api.createWorkshopTask('room-a',{message:'Read the selected objects',target:'agent-a'});
  assert.equal(create,1);assert.equal(send,2);
  const created=t.posts.find(p=>p.url==='/api/universal/work').body;
  assert.equal(created.workshop_root,'room-a');assert.equal(created.description,'Read the selected objects');
  assert.match(created.external_key,/^workshop:task:\d+$/);
  assert.equal(created.structured_references,undefined,'a plain task grants no execution or write permits');
  const attempts=t.posts.filter(p=>p.body.text==='Read the selected objects');
  assert.deepEqual(attempts.map(p=>p.body.refs),[['work:newtask01'],['work:newtask01']]);
  assert.equal(attempts[0].body.idempotency_key,attempts[1].body.idempotency_key);
});

test('PASS3 an uncertain task-create reply retries one external key and never sends before reconciliation',async()=>{
  const keys=[];let first=true;
  const t=transport({post:async(url,body)=>{
    if(url==='/api/universal/work') {keys.push(body.external_key);if(first){first=false;throw new Error('fixture create reply lost');}
      return {ok:true,created_root:'work:retained01',existing:true,revision:5,workshop_root:'room-a',workshop_scope:'scope-a'};}
    return {ok:true,workshop:'room-a',root:'sent-retained',revision:6,idempotency_key:body.idempotency_key};
  }});
  t.transcript.send_category='declared-message';t.transcript.participants[1].is_agent=true;
  await t.api.refreshWorkshop('room-a');t.api.beginWorkshopTask('room-a');
  await assert.rejects(t.api.createWorkshopTask('room-a',{message:'Read this task',target:'agent-a'}),/create reply lost/);
  assert.equal(t.posts.filter(p=>p.body.text).length,0);
  await t.api.createWorkshopTask('room-a',{message:'Read this task',target:'agent-a'});
  assert.equal(keys.length,2);assert.equal(keys[0],keys[1]);
  assert.equal(t.posts.find(p=>p.body.text).body.refs[0],'work:retained01');
});
