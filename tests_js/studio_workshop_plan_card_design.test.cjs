const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
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
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, URL, Blob, TextEncoder,
    AbortController:win.AbortController, fetch:(...args) => win.fetch(...args)});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
  const reactRoot = createRoot(win.document.getElementById('root'));
  const act = async fn => { await React.act(async () => { await fn(); }); };
  return {win, doc:win.document, act,
    render:(component, props) => act(() => reactRoot.render(React.createElement(win[component], props))),
    close:async () => { await act(() => reactRoot.unmount()); win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}

test('Workshop plan turn uses sans copy and exposes disabled Save as skill with reason', async () => {
  const fx = fixture();
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {},
      sel:{agent:null, task:null}, setSel:() => {}});
    await ui.act(async () => {});

    const plan = ui.doc.querySelector('[data-workshop-plan-copy]');
    assert.ok(plan, 'plan copy is rendered with a stable selector');
    assert.equal(plan.style.fontFamily, '"Inter", system-ui, sans-serif');
    assert.match(text(plan), /Here(?:'|’)s the plan: read doors, place tags, rerun schedule\./);

    const task = ui.doc.querySelector('[data-workshop-task]');
    const save = ui.doc.querySelector('[data-workshop-save-skill]');
    assert.equal(save, null, 'Save as skill button is absent without a route');
    assert.match(text(task), /After it runs: "Save as skill" keeps this as a graph you can run again from Studio or Player\./);
    assert.deepEqual([...task.querySelectorAll('button')].map(button => button.textContent.trim()), ['Approve', 'Open as graph']);
  } finally {
    await ui.close();
  }
});
