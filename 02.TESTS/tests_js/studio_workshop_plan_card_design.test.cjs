const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const text = el => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');

function fixture() {
  const now = Date.now() / 1000;
  const work = 'assembly-instance:plan-card-01';
  const agent = 'app:agent-session:runtime:codex-plan';
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:4,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, storage:'conversation-content',
    content_cursor:'c4', page_before:null, next_before:null, total:2, has_older:false, feed:'messages',
    model_agent:{root:'model-a', model:'qwen/qwen3.8-27b:free', route:'auto', binding_digest:'b'.repeat(64)},
    participants:[
      {root:'owner-a', label:'Owner', attached:true, is_agent:false},
      {root:agent, label:'Codex', attached:true, is_agent:true, connection_status:'connected',
        connection_basis:'authenticated-request', observed_at:now - 10, expires_at:now + 600,
        runtime:'codex', host:'Codex', session_link:'attached'},
    ],
    messages:[
      {root:'m1', sequence:1, sender_root:'owner-a', recipient_roots:[], body:'Draft the door tagging plan.',
        category:'note', state:'recorded', created_at:now - 60},
      {root:'m2', sequence:2, sender_root:agent, recipient_roots:['owner-a'],
        body:`Claimed Work ${work}. Plan: read doors, place tags, rerun schedule.`,
        facts_used:[{label:'door tags use level prefix', root:'fact:door-prefix'}],
        category:'note', state:'acted', created_at:now - 30},
    ]};
  const state = {canvas:{graph_id:'graph-a', root:'scope-a', revision:4,
      authorization:{subject:'owner-a', session:'view-a'}},
    workshops:[{root:'room-a', label:'Plan room', is_general:true, native_work_available:true}],
    workshop:transcript, workshopPage:{root:'room-a', before:null, feed:'messages', feedInitialized:true},
    workshopNotice:'',
    nativeWork:{owner:'owner-a', view:'view-a', root:'room-a', scope:'scope-a', state:'awaiting_approval',
      mode:'project', work, approved:false, review_text:'input', input_digest:'a'.repeat(64),
      review_expires_at:now + 600, available_work:[work], artifacts_work:work, selected_work_mode:'project'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'},
      authorization:{subject:'owner-a', session:'view-a'}, revision:4}, graph:{nodes:[
      {id:work, title:'Door tagging plan', sub:'Graph node', status:'Revit write', x:200, y:160,
        params:[{k:'description', v:'3 steps · write approval'}]},
    ], wires:[]}, selected:null}};
  const calls = [];
  const authority = {getSnapshot:() => state, subscribe:() => () => {},
    refreshWorkshop:async() => transcript, refreshNativeWork:async() => state.nativeWork,
    showWorkshopFeed:async() => transcript, nativeAgents:async() => ({status:'ok', contacts:[]}),
    sendModelConversation:async() => ({accepted:true}), approveNativeWork:async(...args) => { calls.push(args); return {}; },
    selectTopology:async() => null, refreshTopologyCanvas:async() => state.topology.canvas};
  return {state, authority, work};
}

async function mountModule() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const win = dom.window;
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, CustomEvent:win.CustomEvent, URL, Blob, TextEncoder,
    AbortController:win.AbortController, fetch:(...args) => win.fetch(...args)});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/shared-data.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
  const reactRoot = createRoot(win.document.getElementById('root'));
  const act = async fn => { await React.act(async () => { await fn(); }); };
  return {win, doc:win.document, act,
    render:(component, props) => act(() => reactRoot.render(React.createElement(win[component], props))),
    close:async () => { await act(() => reactRoot.unmount()); win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}


test('Workshop lifecycle plan enters the sans Run card and the inline decision has only Approve and Decline',async()=>{
  const fx=fixture();const ui=await mountModule();
  try{ui.win.ARCHHUB_EXISTING_WORKSHOP=fx.authority;await ui.render('WorkshopView',{state:fx.state,descriptor:fx.state.workshops[0],target:'',setTarget:()=>{},setMode:()=>{},setFocusId:()=>{},sel:{agent:null,task:null},setSel:()=>{}});
    assert.equal(ui.doc.querySelector('[data-workshop-message="m2"]'),null,'lifecycle text is not an agent reply');
    const plan=ui.doc.querySelector('[data-workshop-plan]');assert.ok(plan);assert.match(text(plan),/Door tagging plan/);
    assert.equal([...plan.querySelectorAll('*')].some(el=>/mono/i.test(el.style.fontFamily||'')),false);
    assert.equal(ui.doc.querySelector('[data-workshop-save-skill]'),null);assert.doesNotMatch(text(ui.doc.body),/After it runs/);
    assert.deepEqual([...ui.doc.querySelectorAll('[data-workshop-approval-card] button')].map(text),['Approve','Decline']);
  }finally{await ui.close();}
});
