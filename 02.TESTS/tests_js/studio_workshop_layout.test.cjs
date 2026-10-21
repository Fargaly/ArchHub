/* The Workshop is the design bundle's studio-workshop.jsx, shipped as 01.APP/nodelang/studio/studio-workshop.jsx:
   the rail swap, the 34px Workshop bar with its three layout presets, task cards as the container of their
   own thread, the task board, the live graph and the context panel, all drawn from the live projections
   (transcript participants, messages that name a Work, native Work status, projected topology). */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const source = fs.readFileSync(process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'), 'utf8');
const workshopPath = path.join(root, '01.APP/nodelang/studio/studio-workshop.jsx');
const workshop = () => fs.readFileSync(workshopPath, 'utf8');

function modeHarness() {
  const start = source.indexOf('const workshopModeRoom =');
  const end = source.indexOf('const WsHeader =', start);
  assert.ok(start > 0 && end > start, 'the mode switch helpers are a slice of the shipped studio-lm.jsx');
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end) +
    '\nglobalThis.room = workshopModeRoom; globalThis.choose = chooseWorkshopMode;', context);
  return context;
}
const rooms = [{root:'child-a', label:'Child', is_general:false}, {root:'general-a', label:'General', is_general:true}];

test('Workshop handoff uses the held room, else the general room, else the first; no session-level Chat segment remains', () => {
  const {room, choose} = modeHarness();
  assert.equal(room(rooms, ''), 'general-a');
  assert.equal(room(rooms, 'child-a'), 'child-a');
  assert.equal(room([{root:'only-a', label:'Only'}], ''), 'only-a');
  assert.equal(room([], ''), '');
  const calls = [];
  const view = (mode, conversationRoot, workshops = rooms) => ({mode, conversationRoot, workshops,
    setMode:value => calls.push(['mode', value]), setConversationRoot:value => calls.push(['root', value])});
  choose('workshop', view('chat', ''));
  choose('workshop', view('canvas', 'child-a'));
  choose('workshop', view('chat', 'child-a'));
  choose('chat', view('chat', 'child-a'));
  choose('chat', view('chat', ''));
  choose('canvas', view('chat', 'child-a'));
  choose('workshop', view('chat', '', []));
  choose('workshop', view('chat', '', [{root:'only-a', label:'Only'}]));
  assert.deepEqual(calls, [['root', 'general-a'], ['root', 'child-a'], ['root', ''], ['mode', 'canvas'], ['root', 'only-a']]);
  assert.equal(/workshopModeSegments/.test(source), false, 'the old Chat|Workshop|Canvas segment helper is gone');
});

test('the System graph is its own session, not a header tab; the system mode still opens it', () => {
  modeHarness();
  const headerStart = source.indexOf('const WsHeader =');
  const headerEnd = source.indexOf('const WsTab =', headerStart);
  const header = source.slice(headerStart, headerEnd);
  const tabLoop = header.slice(header.indexOf('openTabs.map'), header.indexOf('New session after the tabs'));
  assert.doesNotMatch(tabLoop, /System|system:/,
    'System is not rendered by the Studio session tab loop');
  assert.doesNotMatch(header, /workshopModeSegments|WorkshopConversationMenu/,
    'the old Chat|Workshop|Canvas switch is not a header tab');
  assert.doesNotMatch(source, /sessionRowsWithSystem|systemSessionRow/,
    'System is opened from Settings as the application node, never injected as a session row');
});

test('Workshop ships compiled and admitted but its source/output are deferred until first open',()=>{
  const names=read('01.APP/packaging/compile_studio.cjs').match(/const names = \[([\s\S]*?)\];/)[1];assert.match(names,/'workshop-board\.jsx', 'studio-workshop\.jsx'/);
  const html=read('01.APP/nodelang/studio/studio.html');assert.match(html,/workshopSources/);assert.match(html,/ARCHHUB_LOAD_WORKSHOP/);
  assert.match(html,/manifest\.files\.filter\(file => !workshopSources\.has\(file\.source\)\)/);
  const server=read('01.APP/nodelang/application_server.py');const admitted=server.slice(server.indexOf('def _clean_studio_asset'),server.indexOf('if name not in admitted'));
  assert.match(admitted,/"studio-workshop\.jsx"/);assert.match(admitted,/"compiled\/studio-workshop\.js"/);
  const installer=read('01.APP/installer/build_release.ps1');assert.match(installer,/'selected\/nodelang\/studio\/studio-workshop\.jsx'/);
  assert.match(installer,/'workshop-board\.js', 'studio-workshop\.js'/);
});

test('Studio reads one lazy Workshop module whose window owns the complete frame',()=>{
  const workspace=source.slice(source.indexOf('const Workspace ='),source.indexOf('const modelRoute ='));
  assert.match(workspace,/<LazyWorkshopWindow/);assert.doesNotMatch(workspace,/<ChatView key=|<InferenceInspector model=/);
  assert.match(source,/window\.ARCHHUB_LOAD_WORKSHOP/);
  assert.match(workshop(),/window\.WorkshopView = WorkshopView/);
  for(const retired of ['const WorkshopConversation =','const WorkshopTaskCard =','const WorkshopTaskBoard =','const WorkshopLayoutPane ='])assert.equal(source.includes(retired),false,retired);
  for(const seeded of ['Atlas','CAD Reader','Revit Builder','Rhino Bridge','BABOOM','Tower-A_central','L03-base','seedTasks','WS_RUN','WS_AGENTS','window.wsNode','09:47','Spend cap'])assert.equal(workshop().includes(seeded),false,seeded);
});

test('task grouping preserves one Work id and latest event verb through the shared source',()=>{
  const shared=read('01.APP/nodelang/studio/shared-data.jsx');const context=vm.createContext({window:{}});
  vm.runInContext(shared.slice(0,shared.indexOf('window.ARCHHUB_WORKSHOP_MODEL =')),context);
  const note=(root,sender,body)=>({root,sender_root:sender,body,state:'recorded',category:'note',recipient_roots:[]});
  const items=context.window.ARCHHUB_WORKSHOP_TASK_SOURCE.items([
    note('m1','agent-a','Claimed Work assembly-instance:aaaaaaaa11112222.'),note('m2','agent-b','Please review the export.'),
    note('m3','agent-a','Submitted Work assembly-instance:aaaaaaaa11112222.'),
    note('m4','agent-a','Claimed Work work:repair-export'),note('m5','agent-a','Gate failed for Work work:repair-export: court exit 1')],
    [{id:'work:repair-export',title:'Repair export',status:'OPEN'}]);
  assert.deepEqual(Array.from(items,item=>item.kind==='task'?`${item.work}|${item.state}|${item.events.map(e=>e.root).join(',')}`:item.message.root),
    ['assembly-instance:aaaaaaaa11112222|review|m1,m3','m2','work:repair-export|block|m4,m5']);
  assert.equal(context.window.ARCHHUB_WORKSHOP_TASK_SOURCE.items([],[]).length,0);
});

// A live-shaped fixture: studio-existing-workshop.js snapshot, projectStudioCanvas nodes and wires.
function fixture() {
  const now = Date.now() / 1000;
  const W1 = 'assembly-instance:3f9a1c7e5b2d4f60', W2 = 'assembly-instance:8b41d0e27c93a5f1', W3 = 'assembly-instance:c5e2a9f4180d7b36';
  const codex = 'app:agent-session:runtime:codex-a1', claude = 'app:agent-session:runtime:claude-b2', gone = 'app:agent-session:runtime:gone-c3';
  const participants = [
    {root:'owner-a', label:'Owner', attached:true, is_agent:false, connection_status:'unknown'},
    {root:gone, label:'Runtime-e2a3923f', attached:true, is_agent:true, connection_status:'disconnected', observed_at:now - 360, runtime:'antigravity-ide', host:'Antigravity', session_link:'attached'},
    {root:codex, label:'Codex', attached:true, is_agent:true, connection_status:'connected', connection_basis:'authenticated-request',
      observed_at:now - 30, expires_at:now + 3600, runtime:'codex', host:'Codex', model:'gpt-5.5', session_link:'attached'},
    {root:claude, label:'Claude Code', attached:true, is_agent:true, connection_status:'connected', connection_basis:'authenticated-request',
      observed_at:now - 10, expires_at:now + 3600, runtime:'claude', host:'Claude', session_link:'none'},
  ];
  let n = 0;
  const msg = (sender, body, category = 'note') => ({root:'m' + (++n), sequence:n, sender_root:sender, recipient_roots:[], body, category, state:'recorded', created_at:now - 600 + n * 30});
  const messages = [
    msg('owner-a', 'Turn the wall layer into walls.'),
    msg(codex, `Claimed Work ${W1}.`),
    msg(codex, `Gate failed for Work ${W1}: the layer choice needs you.`),
    msg(claude, `Claimed Work ${W2}. Exterior walls first.`),
    msg(codex, `Submitted Work ${W3}: 29 walls created.`),
  ];
  const nodes = [
    {id:'read-dwg', title:'Read DWG', sub:'cad.read_lines', status:'824 lines', x:40, y:80, params:[]},
    {id:W1, title:'Layer selection', sub:'Graph node', status:'OPEN', x:320, y:220, params:[{k:'description', v:'Pick the source wall layers'}]},
    {id:W2, title:'Wall creation', sub:'Graph node', status:'CLAIMED', x:620, y:120, params:[]},
    {id:W3, title:'Verification', sub:'Graph node', status:'SUBMITTED', x:900, y:320, params:[]},
  ];
  const wires = [{id:'w1', from:['read-dwg', 'a'], to:[W1, 'b']}, {id:'w2', from:[W1, 'c'], to:[W2, 'd']}, {id:'w3', from:[W2, 'e'], to:[W3, 'f']}];
  const auth = {subject:'owner-a', session:'view-a'};
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:9, owner:'owner-a', view:'view-a', self:'owner-a',
    can_send:true, participants, messages, storage:'conversation-content', content_cursor:'c9', page_before:null, next_before:null, total:5,
    has_older:false, feed:'messages', model_agent:{root:'model-a', model:'openrouter/model-a', binding_digest:'b'.repeat(64)}};
  const state = {canvas:{graph_id:'graph-a', root:'scope-a', revision:9, authorization:auth}, workshops:[{root:'room-a', label:'L03 wall take-off', is_general:true}],
    workshop:transcript, workshopPage:{root:'room-a', before:null, feed:'messages', feedInitialized:true}, workshopNotice:'',
    nativeWork:{owner:'owner-a', view:'view-a', root:'room-a', scope:'scope-a', state:'awaiting_approval', mode:'project', work:W1, approved:false,
      review_text:'input', input_digest:'a'.repeat(64), review_expires_at:now + 3600, available_work:[W1, W2, W3], artifacts_work:W1, selected_work_mode:'project'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:auth, revision:9}, graph:{nodes, wires}, selected:null}};
  const calls = [];
  const spy = (name, value) => (...args) => { calls.push([name, ...args]); return Promise.resolve(typeof value === 'function' ? value(...args) : value); };
  const authority = {getSnapshot:() => state, subscribe:() => () => {},
    refreshWorkshop:spy('refreshWorkshop', transcript), refreshNativeWork:spy('refreshNativeWork', state.nativeWork),
    showWorkshopFeed:spy('showWorkshopFeed', transcript), nativeAgents:spy('nativeAgents', {status:'ok', contacts:[]}),
    sendModelConversation:spy('sendModelConversation', {accepted:true}), approveNativeWork:spy('approveNativeWork', {}),
    disconnectAgent:spy('disconnectAgent', {outcome:'revoked'}), selectTopology:spy('selectTopology', null)};
  return {state, authority, calls, ids:{W1, W2, W3, codex, claude, gone}};
}

async function mountModule() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  // The DOM exists before react-dom loads, so React uses the real input event instead of its legacy polyfill.
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const win = dom.window;
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, CustomEvent:win.CustomEvent, URL, Blob, TextEncoder});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/shared-data.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(workshop(), {loader:'jsx'}).code, context);
  const container = win.document.getElementById('root');
  const reactRoot = createRoot(container);
  const act = async fn => { await React.act(async () => { await fn(); }); };
  const click = el => act(() => el.dispatchEvent(new win.MouseEvent('click', {bubbles:true})));
  return {React, win, doc:win.document, container, act, click,
    render:(component, props) => act(() => reactRoot.render(React.createElement(win[component], props))),
    close:async () => { await act(() => reactRoot.unmount()); win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}
// Visible text as a reader meets it: every text node, in order, separated by one space.
const text = el => {
  if (!el) return '';
  const out = [];
  const walk = node => node.childNodes.forEach(child => {
    if (child.nodeType === 3) { if (child.nodeValue.trim()) out.push(child.nodeValue.trim()); } else walk(child);
  });
  walk(el);
  return out.join(' ').replace(/\s+/g, ' ');
};

const {mounted,plain}=require('./workshop72_regression_helpers.cjs');

test('Workshop view draws the exact DSYS077 frame with real send approval and canvas handoff',async()=>{
  const fx=fixture(), modes=[],focus=[];fx.state.workshop.participants=[];
  const ui=await mounted(fx.state,fx.authority,{target:'model:'+fx.state.workshop.model_agent.root,setMode:value=>modes.push(value),setFocusId:value=>focus.push(value)});
  try{const main=ui.doc.querySelector('[data-workshop72]');assert.equal(main.style.gridTemplateRows,'1fr 28px');
    assert.equal(ui.doc.querySelector('[data-workshop72-rail]').style.width,'64px');
    assert.equal(ui.doc.querySelector('[data-workshop72-list]').style.width,'340px');
    assert.equal(ui.doc.querySelector('[data-workshop72-thread]').style.width,'780px');
    assert.equal(ui.doc.querySelector('[role="tablist"]'),null);assert.equal(ui.doc.querySelector('[data-workshop-s1-inspector]'),null);
    const card=ui.doc.querySelector('[data-workshop-approval-card]');assert.deepEqual([...card.querySelectorAll('button')].map(text),['Approve','Decline']);
    await ui.input('Check the joins');await ui.click(ui.button('Send'));
    assert.deepEqual(plain(fx.calls.filter(row=>row[0]==='sendModelConversation').map(row=>[row[1],row[2].root,row[3]])),[['room-a','model-a','Check the joins']]);
    await ui.click(ui.button('Approve'));assert.equal(fx.calls.filter(row=>row[0]==='approveNativeWork').length,1);
    await ui.click(ui.button('Open on canvas'));assert.ok(modes.includes('canvas'));assert.ok(focus.includes(fx.ids.W1));
  }finally{await ui.close();}
});
test('WS022 Board and Projects presets now select the same real thread without hidden duplicate views',async()=>{
  const fx=fixture();const ui=await mounted(fx.state,fx.authority,{sel:{agent:null,task:fx.ids.W2,tab:'board'}});
  try{assert.ok(ui.doc.querySelector('[aria-label="Workshop conversation"]'));
    assert.equal(ui.doc.querySelector('[data-workshop-s1-canvas]'),null);assert.equal(ui.doc.querySelector('[aria-label="Workshop tasks"]'),null);
    assert.equal(ui.doc.querySelector('[aria-label="Workshop projects"]'),null);assert.equal(ui.doc.querySelector('[data-workshop-utility]'),null);
    await ui.click(ui.doc.querySelector('[data-workshop-task-row="'+fx.ids.W1+'"]'));
    assert.ok(ui.doc.querySelector('[data-workshop-approval-card]'));
  }finally{await ui.close();}
});
test('agent addressing uses exact attached participant ids through @ rather than the removed agents rail',async()=>{
  const fx=fixture();fx.authority.sendWorkshopMessage=async(...args)=>{fx.calls.push(['sendWorkshopMessage',...args]);return{ok:true};};
  const ui=await mounted(fx.state,fx.authority);
  try{await ui.input('@Claude Code Check the selected wall');await ui.click(ui.button('Send'));
    assert.deepEqual(plain(fx.calls.filter(row=>row[0]==='sendWorkshopMessage')),[['sendWorkshopMessage','room-a',{target:fx.ids.claude,message:'Check the selected wall'}]]);
    assert.equal(ui.doc.querySelector('[aria-label="Workshop agents"]'),null);assert.equal(ui.doc.querySelectorAll('select').length,0);assert.ok(ui.doc.querySelector('button[data-workshop-agent-picker]'));assert.doesNotMatch(text(ui.doc.querySelector('[data-workshop-agent-picker]')),/Workshop \(everyone\)/);
  }finally{await ui.close();}
});
