const {test}=require('node:test');
const assert=require('node:assert/strict');
const {fixture}=require('./workshop72_fixture.cjs');
const {mounted,transport,plain,text,read}=require('./workshop72_regression_helpers.cjs');

test('PASS3 New task opens the authority draft and empty composer in one click; Send creates exact Work',async()=>{
  const f=fixture(),ui=await mounted(f.state,f.authority);
  try{
    await ui.click(ui.button('New task'));
    assert.equal(f.calls.filter(c=>c[0]==='beginWorkshopTask').length,1);
    assert.ok(ui.doc.querySelector('[data-workshop-empty]'));
    assert.equal(ui.doc.querySelector('[data-workshop-plan],[data-workshop-approval-card]'),null);
    assert.equal(ui.doc.querySelectorAll('textarea').length,1);
    await ui.input('@Codex Inspect the current selection');await ui.click(ui.button('Send'));
    assert.deepEqual(plain(f.calls.find(c=>c[0]==='createWorkshopTask')),['createWorkshopTask','room-a',{message:'Inspect the current selection',target:'agent-b'}]);
    assert.equal(ui.selection().task,'work:newtask01');
    assert.equal(f.state.workshopTaskDraft,null);
    assert.match(text(ui.doc.querySelector('[data-workshop-head]')),/Inspect the current selection/);
    assert.ok(ui.doc.querySelector('[data-workshop-message="new-task-message"]'));
  }finally{await ui.close();}
});

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

test('PASS3 lifecycle events become Run state while agent-owned reply text stays in chat',async()=>{
  const f=fixture();
  f.state.workshop.messages.push({root:'lifecycle-only',sender_root:'agent-a',body:'Claimed Work '+f.work+'.',category:'lifecycle',created_at:Date.now()/1000});
  const ui=await mounted(f.state,f.authority);
  try{
    assert.equal(ui.doc.querySelector('[data-workshop-message="lifecycle-only"]'),null);
    assert.doesNotMatch(text(ui.doc.querySelector('[data-workshop72-thread]')),/Claimed|work:/);
    assert.match(text(ui.doc.querySelector('[data-workshop-message="reply-a"]')),/Read the selection\./);
    assert.ok(ui.doc.querySelector('[data-workshop-plan]'));
  }finally{await ui.close();}
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

test('PASS3 task references isolate real threads and the registered Work composer preserves the task identity',async()=>{
  const f=fixture();
  f.state.topology.graph.nodes.find(n=>n.id===f.work).engine='work';
  f.state.workshop.planned_items=[{id:'work:other0001',title:'Other task',state:'PLANNED'}];
  f.state.workshop.messages.push({root:'foreign-ref',sender_root:'agent-b',body:'Different task reply',reference_roots:['work:other0001']});
  const ui=await mounted(f.state,f.authority);
  try{
    assert.equal(ui.doc.querySelector('[data-workshop-message="foreign-ref"]'),null);
    await ui.input('Continue the same task');await ui.click(ui.button('Send'));
    assert.equal(f.calls.filter(c=>c[0]==='workshopAction').at(-1)[4].work,f.work);
  }finally{await ui.close();}
});

test('PASS3 planned status is its start condition in inkSoft and working progress stays real',async()=>{
  const f=fixture();f.state.workshop.planned_items=[{id:'planned-new',title:'Next selection',state:'PLANNED',depends_on:[f.work]}];
  const ui=await mounted(f.state,f.authority);
  try{
    const row=ui.doc.querySelector('[data-workshop-task-row="planned-new"]');
    assert.match(text(row),/starts after Label selected elements/);assert.doesNotMatch(text(row),/\bopen\b|error|Claimed/);
    assert.equal(row.querySelector('span').style.color,ui.doc.querySelector('[data-workshop-task-row="flow-a"] span').style.color);
  }finally{await ui.close();}
});

test('PASS3 user initials and colour come from current account; clock and elapsed metadata stay distinct',async()=>{
  const f=fixture();f.state.account={name:'Alex Farid',colour:'#ac9361'};
  f.state.workshop.messages[1].elapsed='38 s';f.state.workshop.messages[1].cost_label='free';
  f.state.models={items:[{id:'test-model',name:'Live model label'}]};f.state.workshop.participants[1].model='test-model';
  const ui=await mounted(f.state,f.authority);
  try{
    const avatar=ui.doc.querySelector('[data-workshop-account-avatar]');assert.equal(avatar.textContent,'AF');assert.equal(avatar.style.background,'rgb(172, 147, 97)');
    const message=ui.doc.querySelector('[data-workshop-message="reply-a"]');
    assert.match(message.querySelector('time').textContent,/^\d{2}:\d{2}$/);
    assert.match(text(message),/Live model label · 38 s · free/);
    assert.match(ui.doc.querySelector('[data-user-bubble] time').textContent,/^\d{2}:\d{2}$/);
    assert.doesNotMatch(read('nodelang/studio/studio-workshop.jsx'),/Sonnet 4\.6|GPT-5\.5|border-style:dashed/);
    assert.match(read('nodelang/studio/studio-lm.jsx'),/descriptor=\{workshop\} account=\{account\}/);
  }finally{await ui.close();}
});

test('PASS3 proposal preview binds actual elements/new labels and summary fallback preserves Approve',async()=>{
  const f=fixture();f.state.nativeWork=null;f.state.workshop.workflows=[];
  const payload={title:'Label proposal',description:'Change only the selected labels.',purpose:'general',priority:0,
    container:{container_id:'wip'},write_grants:[{path:'model',scope:'selected',operations:['write']}],
    preview:{elements:[{id:'e1',label:'Door A',now:'—'}],new_labels:['L-01']}};
  f.state.workshop.messages=[{root:'proposal-real',sender_root:'agent-a',body:'ArchHub work proposal v1\n'+JSON.stringify(payload)}];
  f.authority.bindWorkProposals=async()=>{};f.authority.declineWorkProposals=async()=>{};
  const ui=await mounted(f.state,f.authority);
  try{
    assert.match(text(ui.doc.querySelector('[data-workshop-change-row]')),/Door A.*L-01/);
    delete payload.preview;f.state.workshop.messages[0].body='ArchHub work proposal v1\n'+JSON.stringify(payload);await ui.render();
    assert.equal(ui.doc.querySelector('[data-approval-diff]'),null);
    assert.equal(text(ui.doc.querySelector('[data-approval-summary]')),payload.description);
    assert.equal(ui.button('Approve').disabled,false);
  }finally{await ui.close();}
});
