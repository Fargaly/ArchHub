/* WORKSHOP-61 p3 S1 audit batch 2: old workflow cards/panels are gone. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const text = el => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
const WORK = 'assembly-instance:3f9a1c7e5b2d4f60';
const AGENT = 'app:agent-session:runtime:codex-a1';
const DIGEST = 'd'.repeat(64);

const addWorkflow = (state, root, title, approval) => {
  state.workshop.workflows = [...(state.workshop.workflows || []), {
    root, title, proposed_by:AGENT, digest:DIGEST, approval,
    nodes:[{root:root + ':step', title:'Step', engine:'agent.session', params:{agent:AGENT}}],
  }];
};

function fixture(waiting=true, setup = () => {}) {
  const now = Date.now() / 1000;
  const read = 'node:read-wall-layer';
  const watch = 'node:watch-walls';
  const state = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization:{subject:'owner-a', session:'view-a'}},
    workshops:[{root:'room-a', label:'Wall conversion', is_general:true, native_work_available:true}],
    workshopNotice:'', workshopPage:{root:'room-a', before:null, feed:'messages', feedInitialized:true},
    nativeWork: waiting ? {owner:'owner-a', view:'view-a', root:'room-a', scope:'scope-a', state:'awaiting_approval',
      mode:'project', work:WORK, approved:false, review_text:'input', input_digest:'a'.repeat(64), document:'Tower.rvt',
      review_expires_at:now + 600, available_work:[WORK], artifacts_work:WORK, selected_work_mode:'project'} : null,
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:{subject:'owner-a', session:'view-a'}, revision:7},
      graph:{nodes:[
        {id:read, title:'Read wall layer', status:'ready', engine:'host.read', x:80, y:120,
          outs:[{id:'walls', label:'walls', t:'elements', list:true}]},
        {id:WORK, title:'Wall creation', status:'awaiting approval', x:330, y:160,
          ins:[{id:'walls', label:'walls', t:'elements', list:true}], outs:[{id:'created', label:'created', t:'elements', list:true}],
          params:[{k:'description', v:'step 2 of 3'}]},
        {id:watch, title:'Watch wall result', status:'idle', engine:'watch.preview', x:580, y:190,
          ins:[{id:'created', label:'created', t:'elements', list:true}], result:JSON.stringify([{Wall:'W-01', State:'pending'}])},
      ], wires:[
        {id:'wire-read-work', from:[read, 'walls'], to:[WORK, 'walls']},
        {id:'wire-work-watch', from:[WORK, 'created'], to:[watch, 'created']},
      ]}, selected:null}};
  state.workshop = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:7,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true,
    model_agent:{root:'model-a', model:'Sonnet', route:'auto'},
    participants:[{root:'owner-a', label:'Owner', attached:true},
      {root:AGENT, label:'Codex', attached:true, is_agent:true, connection_status:'connected',
        connection_basis:'authenticated-request', observed_at:now - 30, expires_at:now + 600, host:'Codex'}],
    messages:[
      {root:'m1', sequence:1, sender_root:'owner-a', recipient_roots:[], body:'Turn the wall layer into walls.', category:'note', state:'recorded', created_at:now - 40},
      {root:'m2', sequence:2, sender_root:AGENT, recipient_roots:['owner-a'], body:`Claimed Work ${WORK}. Plan: read 29 walls, create walls, refresh view.`, category:'note', state:'acted', created_at:now - 20},
    ]};
  const calls = [];
  const authority = {getSnapshot:() => state, subscribe:() => () => {}, refreshWorkshop:async() => state.workshop,
    refreshNativeWork:async() => state.nativeWork, showWorkshopFeed:async() => state.workshop,
    nativeAgents:async() => ({status:'ok', contacts:[]}), sendModelConversation:async() => ({accepted:true}),
    approveNativeWork:async(...args) => { calls.push(['approveNativeWork', ...args]); return {}; },
    sendWorkshopMessage:async(...args) => { calls.push(['sendWorkshopMessage', ...args]); return {}; }};
  setup({state, authority, calls});
  return {state, authority, calls};
}

async function mount(waiting=true, setup = () => {}) {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const context = vm.createContext({React, window:dom.window, document:dom.window.document, setTimeout, clearTimeout, console, CustomEvent:dom.window.CustomEvent, URL, Blob, TextEncoder});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/shared-data.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
  const fx = fixture(waiting, setup);
  dom.window.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
  const rootEl = createRoot(dom.window.document.getElementById('root'));
  const act = async fn => { await React.act(async () => { await fn(); }); };
  await act(() => rootEl.render(React.createElement(dom.window.WorkshopView, {state:fx.state, descriptor:fx.state.workshops[0],
    target:'', setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {},
    sel:{agent:null, task:null}, setSel:() => {}, externalRail:true})));
  return {...fx, doc:dom.window.document, click:el => act(() => el.dispatchEvent(new dom.window.MouseEvent('click', {bubbles:true}))),
    close:async () => { await act(() => rootEl.unmount()); dom.window.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}

const {mountWorkshopNode}=require('./workshop72_node_helpers.cjs');

test('typed list ports move from embedded Workshop canvas to the real graph Workshop node',async()=>{
  const fx=fixture();const node={id:'room-a',cat:'workshop',title:'Workshop',x:0,y:0,
    ins:[{id:'walls',label:'walls',t:'elements',list:true,connectable:true}],outs:[{id:'created',label:'created',t:'elements',list:true,connectable:true}]};
  fx.state.topology.graph.nodes.push(node);const ui=await mountWorkshopNode({state:fx.state,node});
  try {assert.deepEqual([...ui.doc.querySelectorAll('[data-socket-port]')].map(el=>[el.dataset.socketPort,el.dataset.socketType,el.dataset.socketShape]),
    [['walls','elements','diamond'],['created','elements','diamond']]);
    assert.equal(ui.doc.querySelector('[data-workshop-s1-canvas]'),null);
  }finally{await ui.close();}
});
test('gap8 real workflow steps are one inline plan while the window contains no duplicate graph',async()=>{
  const view=await mount(false,({state})=>addWorkflow(state,'wf-review','Review workflow',null));
  try {assert.match(text(view.doc.querySelector('[data-workshop-plan]')),/Step/);
    assert.equal(view.doc.querySelectorAll('[data-workshop-plan-step]').length,1);
    assert.equal(view.doc.querySelector('[data-workshop-s1-canvas]'),null);
  }finally{await view.close();}
});
test('summary state migrates to the selected inline decision and real status bar without summary panels',async()=>{
  const view=await mount();try{assert.ok(view.doc.querySelector('[data-workshop-approval-card]'));
    assert.match(text(view.doc.querySelector('[data-workshop-s1-status]')),/1 need you/);
    assert.equal(view.doc.querySelector('[data-workshop-summary]'),null);
  }finally{await view.close();}
});
test('gap11 changed workflow approval remains selectable in the real list and inline review',async()=>{
  const view=await mount(false,({state})=>addWorkflow(state,'wf-old','Older workflow',{digest:'e'.repeat(64),current:false,revoked:false}));
  try{const row=view.doc.querySelector('[data-workshop-task-row="wf-old"]');assert.ok(row);await view.click(row);
    assert.equal(view.doc.querySelector('[data-workshop-approval-card]').getAttribute('data-workshop-approval-card'),'wf-old');
  }finally{await view.close();}
});
test('gap9 revoked approval retains a real review decision and never claims to stop a started run',async()=>{
  const view=await mount(false,({state})=>{state.workshop.messages=[];addWorkflow(state,'wf-revoked','Revoked workflow',{digest:DIGEST,current:false,revoked:true});});
  try{const row=view.doc.querySelector('[data-workshop-task-row="wf-revoked"]');assert.ok(row);await view.click(row);
    assert.ok(view.doc.querySelector('[data-workshop-approval-card]'));
    assert.doesNotMatch(text(view.doc.body),/\b(stopp?ed|halted|paused|cancel(?:l)?ed)\b/i);
  }finally{await view.close();}
});
test('gap11 every awaiting changed and revoked workflow remains visible and selects its exact decision',async()=>{
  const view=await mount(false,({state})=>{
    state.workshop.messages=[];
    addWorkflow(state,'wf-awaiting','Awaiting workflow',null);
    addWorkflow(state,'wf-changed','Changed workflow',{digest:'e'.repeat(64),current:false});
    addWorkflow(state,'wf-revoked','Revoked workflow',{digest:DIGEST,current:false,revoked:true});
    addWorkflow(state,'wf-approved','Approved workflow',{digest:DIGEST,current:true});
  });
  try {for(const id of ['wf-awaiting','wf-changed','wf-revoked']){
    const row=view.doc.querySelector('[data-workshop-task-row="'+id+'"]');assert.ok(row,id);await view.click(row);
    assert.equal(view.doc.querySelector('[data-workshop-approval-card]').getAttribute('data-workshop-approval-card'),id);
    assert.equal(view.doc.querySelectorAll('[data-workshop-approval-card]').length,1);
  }
  await view.click(view.doc.querySelector('[data-workshop-task-row="wf-approved"]'));
  assert.equal(view.doc.querySelector('[data-workshop-approval-card]'),null);
  }finally{await view.close();}
});
test('gap11 approved workflow and calm claimed task never invent motion or completion',async()=>{
  const view=await mount(false,({state})=>{state.workshop.messages=[];addWorkflow(state,'wf-approved','Approved workflow',{digest:DIGEST,current:true});});
  try{assert.equal(view.doc.querySelector('[data-workshop-approval-card]'),null);
    assert.doesNotMatch(text(view.doc.querySelector('[data-workshop-s1-status]')),/running|moving|done|delivered/i);
  }finally{await view.close();}
});
test('no waiting work omits the inline approval when native review and workflows are absent',async()=>{
  const view=await mount(false);try{assert.equal(view.doc.querySelector('[data-workshop-approval-card]'),null);
    assert.equal(view.doc.querySelector('[data-workshop-summary]'),null);
  }finally{await view.close();}
});
test('avatars use a whole emoji first character without a lone surrogate',async()=>{
  const face=String.fromCodePoint(0x1f600);
  const view=await mount(false,({state})=>{
    state.workshop.participants=[{root:'owner-a',label:'Owner',attached:true},{root:AGENT,label:face+face+' Codex',attached:true,is_agent:true,connected:true}];
    state.workshop.messages=[{root:'emoji-reply',sequence:4,sender_root:AGENT,body:'The emoji avatar should be whole.',created_at:Date.now()/1000}];
  });
  try{const avatar=view.doc.querySelector('[data-workshop-message="emoji-reply"] [data-workshop-avatar] i');assert.equal(avatar.textContent,face);
    assert.equal(avatar.textContent.length,face.length);
  }finally{await view.close();}
});
