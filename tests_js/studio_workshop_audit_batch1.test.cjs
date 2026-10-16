/* WORKSHOP-61 p3: legacy workflow/task cards were removed. These courts keep the
   behavior checks on the S1 Workshop surface: plain transcript, one approval
   card, no raw ids, no JSON dump, and live workflow run route. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const text = el => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
const CONTACT = 'app:wip-cell:ece542c574ae470bbbd962ac8c5ff39a';
const WORK = 'assembly-instance:3f9a1c7e5b2d4f60';
const WF = 'wf-1';
const DIGEST = 'd'.repeat(64);

function fixture({workflow=false, approval=null, notice='', deliveryState=null, parameterEdit=false} = {}) {
  const now = Date.now() / 1000;
  const plan = 'Here is my proposal.\n```json\n' + JSON.stringify({title:'Release note workflow', actions:[
    {op:'node', ref:'room', engine:'workshop.conversation', title:'This Workshop'},
    {op:'node', ref:'builder', engine:'agent.session', title:'Claude drafts the release note'},
  ]}) + '\n```';
  const state = {canvas:{graph_id:'graph-a', root:'scope-a', revision:4, authorization:{subject:'owner-a', session:'view-a'}},
    workshops:[{root:'room-a', label:'Release notes', is_general:true, native_work_available:true}],
    workshopNotice:notice, workshopPage:{root:'room-a', before:null, feed:'messages', feedInitialized:true},
    nativeWork:{owner:'owner-a', view:'view-a', root:'room-a', scope:'scope-a', state:'awaiting_approval',
      mode:'project', work:WORK, approved:false, review_text:'input', input_digest:'a'.repeat(64), document:'Tower.rvt',
      review_expires_at:now + 600, available_work:[WORK], artifacts_work:WORK, selected_work_mode:'project'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:{subject:'owner-a', session:'view-a'}, revision:4},
      graph:{nodes:[{id:WORK, title:'Layer selection', status:'Revit write', params:[{k:'description', v:'29 walls · step 2 of 3'}]}], wires:[]}, selected:null}};
  state.workshop = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:4,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, participants:[
      {root:'owner-a', label:'Owner', attached:true},
      {root:CONTACT, label:'acceptance-claude', attached:true, is_agent:true, connection_status:'connected',
        connection_basis:'authenticated-request', observed_at:now - 20, expires_at:now + 600, host:'Claude'}],
    model_agent:{root:'model-a', model:'Sonnet', route:'auto'},
    messages:[
      {root:'ask-1', message_id:'ask-1', sequence:1, sender_root:'owner-a', recipient_roots:[CONTACT], body:'PROPOSE a workflow.', category:'note', state:'recorded', created_at:now - 20},
      {root:'reply-1', message_id:'reply-1', sequence:2, sender_root:'owner-a', recipient_roots:['owner-a'], reply_to_root:'ask-1',
        body:'Session Link relayed reply from acceptance-claude.\n\n' + plan, relayed_from:CONTACT, relayed_label:'acceptance-claude',
        agent_text:plan, category:'tool', state:'recorded', created_at:now - 10},
    ]};
  if (deliveryState) state.workshop.messages[0].delivery = [{recipient:CONTACT, state:deliveryState, via:'session-link'}];
  if (workflow) state.workshop.workflows = [{root:WF, title:'Release note workflow', proposed_by:CONTACT,
    source_message:'reply-1', digest:DIGEST, approval,
    nodes:[{root:'n1', title:'This Workshop', engine:'workshop.conversation', params:{}},
      {root:'n2', title:'Claude drafts the release note', engine:'agent.session', params:{agent:CONTACT}}]}];
  const calls = [];
  if (parameterEdit) {
    const other = 'app:wip-cell:second-agent';
    state.workshop.messages.push({root:'reply-other', message_id:'reply-other', sequence:3, sender_root:'owner-a',
      recipient_roots:['owner-a'], category:'tool', state:'recorded', created_at:now - 1,
      body:'Session Link relayed reply from codex-helper.\n\nConnected.',
      relayed_from:other, relayed_label:'codex-helper', agent_text:'Connected.'});
    state.workshop.workflows[0].nodes[1].params.agent = {relation:'r-agent', value:CONTACT, editable:true};
  }
  const authority = {getSnapshot:() => state, subscribe:() => () => {}, refreshWorkshop:async() => state.workshop,
    refreshNativeWork:async() => state.nativeWork, showWorkshopFeed:async() => state.workshop,
    nativeAgents:async() => ({status:'ok', contacts:[]}), sendModelConversation:async() => ({accepted:true}),
    approveNativeWork:async(...args) => { calls.push(['approveNativeWork', ...args]); return {}; },
    workshopAction:async(...args) => { calls.push(['workshopAction', ...args]); return {}; },
    workshopWorkflow:async(...args) => { calls.push(['workshopWorkflow', ...args]); return {ok:true}; }};
  if (parameterEdit) authority.workshopWorkflowParam = async (...args) => {
    calls.push(['workshopWorkflowParam', ...args]);
    // This is the server's changed behavior projection, not a local UI approval flag.
    const wf = state.workshop.workflows[0];
    wf.nodes[1].params.agent = {...wf.nodes[1].params.agent, value:args[2]};
    wf.digest = 'e'.repeat(64);
    wf.approval = {...wf.approval, current:false};
    return {ok:true};
  };
  return {state, authority, calls};
}

async function mount(options) {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const context = vm.createContext({React, window:dom.window, document:dom.window.document, setTimeout, clearTimeout, console, CustomEvent:dom.window.CustomEvent, URL, Blob, TextEncoder});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('nodelang/studio/shared-data.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
  const fx = fixture(options);
  dom.window.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
  const rootEl = createRoot(dom.window.document.getElementById('root'));
  const act = async fn => { await React.act(async () => { await fn(); }); };
  await act(() => rootEl.render(React.createElement(dom.window.WorkshopView, {state:fx.state, descriptor:fx.state.workshops[0],
    target:'', setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {},
    sel:{agent:null, task:null}, setSel:() => {}, externalRail:true})));
  return {...fx, doc:dom.window.document, win:dom.window, act, click:el => act(() => el.dispatchEvent(new dom.window.MouseEvent('click', {bubbles:true}))),
    close:async () => { await act(() => rootEl.unmount()); dom.window.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}

const {transport, plain, mounted} = require('./workshop72_regression_helpers.cjs');

test('DSYS077 transcript renders an agent proposal as plain chat without JSON or raw ids',async()=>{
  const view=await mount();
  try {const stream=view.doc.querySelector('[aria-label="Workshop conversation"]');
    assert.match(text(stream),/PROPOSE a workflow/); assert.match(text(stream),/Here is my proposal/);
    assert.doesNotMatch(text(stream),/```|assembly-instance:|app:/);
    assert.equal(stream.querySelector('[data-workshop-workflow]'),null);
  }finally{await view.close();}
});
test('gap1 plan reply migrates step pills and raw JSON into one bordered real-step list',async()=>{
  const view=await mount({workflow:true});
  try {const plan=view.doc.querySelector('[data-workshop-plan]');assert.ok(plan);
    const steps=[...plan.querySelectorAll('[data-workshop-plan-step]')];
    assert.deepEqual(steps.map(el=>text(el.querySelector('[data-workshop-step-title]') || el.children[1])),['This Workshop','Claude drafts the release note']);
    assert.deepEqual(steps.map(el=>text(el.querySelector('[data-workshop-step-result]') || el.lastElementChild)),['next','next']);
    assert.equal(view.doc.querySelector('[data-workshop-plan-json]'),null);
    assert.equal(view.doc.querySelector('[data-workshop-step-pill]'),null);
  }finally{await view.close();}
});
test('gap2 proposal reply and plan precede exactly one inline approval',async()=>{
  const view=await mount({workflow:true});
  try {const ask=view.doc.querySelector('[data-workshop-message="ask-1"]');
    const reply=view.doc.querySelector('[data-workshop-message="reply-1"]');const card=view.doc.querySelector('[data-workshop-approval-card]');
    assert.ok(ask.compareDocumentPosition(reply)&view.win.Node.DOCUMENT_POSITION_FOLLOWING);
    assert.ok(reply.compareDocumentPosition(card)&view.win.Node.DOCUMENT_POSITION_FOLLOWING);
    assert.equal(view.doc.querySelectorAll('[data-workshop-approval-card]').length,1);
  }finally{await view.close();}
});
test('gap3 revoked workflow remains a real decision requiring renewed digest approval',async()=>{
  const fx=fixture({workflow:true,approval:{digest:DIGEST,current:false,revoked:true}});fx.state.nativeWork=null;
  const ui=await mounted(fx.state,fx.authority,{sel:{agent:null,task:WF}});
  try {const card=ui.doc.querySelector('[data-workshop-approval-card]');assert.ok(card);
    await ui.click([...card.querySelectorAll('button')].find(el=>text(el)==='Approve'));
    assert.deepEqual(plain(fx.calls.filter(row=>row[0]==='workshopWorkflow')),
      [['workshopWorkflow','room-a','workflow-approve',{workflow:WF,digest:DIGEST}]]);
    assert.equal(ui.button('Run'),undefined);
  }finally{await ui.close();}
});
test('gap2 regression Ping: a proposal naming its Work keeps exactly one inline review',async()=>{
  const view=await mount({workflow:true});
  try {assert.equal(view.doc.querySelectorAll('[data-workshop-approval-card]').length,1);
    assert.equal(view.doc.querySelector('[data-workshop-approval-card] button').textContent.trim(),'Approve');
  }finally{await view.close();}
});
test('gap5 named agents remain readable and opaque roots are never parameter editors in the thread',async()=>{
  const view=await mount({workflow:true});
  try {assert.match(text(view.doc.body),/acceptance-claude/);assert.doesNotMatch(text(view.doc.body),/app:wip-cell:/);
    assert.equal([...view.doc.querySelectorAll('input,select:not([data-workshop-agent-picker])')].some(el=>String(el.value||'').startsWith('app:wip-cell:')),false);
  }finally{await view.close();}
});
test('inline Approve binds the shown native digest once; ask-why uses the single composer',async()=>{
  const fx=fixture({workflow:true});fx.state.workshop.participants=[];
  fx.authority.sendModelConversation=async(...args)=>{fx.calls.push(['sendModelConversation',...args]);return{accepted:true};};
  fx.state.workshopPresentation={subject:'owner-a',graph_id:'graph-a',models:{groups:[{items:[{id:'Sonnet',name:'Sonnet'}]}]}};
  const ui=await mounted(fx.state,fx.authority,{target:'model:'+fx.state.workshop.model_agent.root});
  try {const card=ui.doc.querySelector('[data-workshop-approval-card]');
    assert.deepEqual([...card.querySelectorAll('button')].map(text),['Approve','Decline']);
    await ui.input('@Sonnet Why this step?');await ui.click(ui.button('Send'));
    assert.deepEqual(plain(fx.calls.filter(row=>row[0]==='sendModelConversation')),[['sendModelConversation','room-a',fx.state.workshop.model_agent,'Why this step?']]);
    await ui.click(ui.button('Approve'));
    assert.deepEqual(plain(fx.calls.filter(row=>row[0]==='approveNativeWork')),[['approveNativeWork','room-a','a'.repeat(64)]]);
  }finally{await ui.close();}
});
test('gap6 retained transport reports started only for the exact pending delivery projection',async()=>{
  for(const [state,word] of [['started','delivery started'],['replied','replied']]){
    const fx=transport({post:(_url,body)=>({ok:true,workshop:body.root,root:'entry-a',idempotency_key:body.idempotency_key,revision:5,
      native_delivery:[{recipient:'agent-a',state}]})});
    await fx.api.refreshWorkshop('room-a');await fx.api.workshopAction('room-a','send',null,{target:'',message:'Review the result'});
    assert.match(fx.api.getSnapshot().workshopNotice,new RegExp(word));
    if(state==='replied')assert.doesNotMatch(fx.api.getSnapshot().workshopNotice,/delivery started/);
    assert.equal(fx.posts.length,1);
  }
});
test('gap7 waiting review is visible without a board or an empty-group contradiction',async()=>{
  const view=await mount();try{assert.ok(view.doc.querySelector('[data-workshop-approval-card]'));
    assert.doesNotMatch(text(view.doc.body),/nothing to group/i);assert.equal(view.doc.querySelector('[aria-label="Workshop tasks"]'),null);
  }finally{await view.close();}
});
test('projected workflow execution remains on the exact existing canvas authority route',async()=>{
  const fx=transport();await fx.api.refreshWorkshop('room-a');
  await fx.api.workshopWorkflow('room-a','workflow-execute',{workflow:WF});
  assert.equal(fx.posts.length,1);assert.equal(fx.posts[0].url,'/api/universal/workshop');
  assert.equal(fx.posts[0].body.action,'workflow-execute');assert.equal(fx.posts[0].body.workflow,WF);
  assert.equal(fx.posts[0].body.root,'room-a');assert.equal(fx.posts[0].body.scope,'scope-a');
});
test('OWNER parameter edit retains its exact governed relation and contact root after Properties removal',async()=>{
  const fx=transport();await fx.api.refreshWorkshop('room-a');await fx.api.workshopWorkflowParam('room-a','r-agent','app:wip-cell:second-agent');
  assert.deepEqual(fx.posts,[{url:'/api/universal/set-property',body:{relation:'r-agent',value:'app:wip-cell:second-agent'}}]);
});
test('changed agent parameter projection requires approval of the changed digest, never prior digest execution',async()=>{
  const changed='e'.repeat(64);let edited=false;
  const fx=transport({get:(_url,held)=>({...held,workflows:[{root:WF,digest:edited?changed:DIGEST,
    approval:{digest:DIGEST,current:!edited},nodes:[]}]}),post:(_url)=>{edited=true;return{ok:true};}});
  await fx.api.refreshWorkshop('room-a');await fx.api.workshopWorkflowParam('room-a','r-agent','app:wip-cell:second-agent');
  assert.equal(fx.api.getSnapshot().workshop.workflows[0].approval.current,false);
  await fx.api.workshopWorkflow('room-a','workflow-approve',{workflow:WF,digest:fx.api.getSnapshot().workshop.workflows[0].digest});
  assert.equal(fx.posts[1].body.digest,changed);assert.equal(fx.posts[1].body.action,'workflow-approve');
  assert.equal(fx.posts.some(post=>post.body.action==='workflow-execute'),false);
});
