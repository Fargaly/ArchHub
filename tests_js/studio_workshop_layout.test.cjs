/* The Workshop is the design bundle's studio-workshop.jsx, shipped as nodelang/studio/studio-workshop.jsx:
   the rail swap, the 34px Workshop bar with its three layout presets, task cards as the container of their
   own thread, the task board, the live graph and the context panel, all drawn from the live projections
   (transcript participants, messages that name a Work, native Work status, projected topology). */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const source = fs.readFileSync(process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
const workshopPath = path.join(root, 'nodelang/studio/studio-workshop.jsx');
const workshop = () => fs.readFileSync(workshopPath, 'utf8');

function modeHarness() {
  const start = source.indexOf('const workshopModeRoom =');
  const end = source.indexOf('const WsHeader =', start);
  assert.ok(start > 0 && end > start, 'the mode switch helpers are a slice of the shipped studio-lm.jsx');
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end) +
    '\nglobalThis.segments = workshopModeSegments; globalThis.choose = chooseWorkshopMode;', context);
  return context;
}
const rooms = [{root:'child-a', label:'Child', is_general:false}, {root:'general-a', label:'General', is_general:true}];

test('Workshop is Chat with the held room, else the general room, else the first; no room disables the segment', () => {
  const {segments, choose} = modeHarness();
  const labels = view => segments(view).map(row => `${row.label}${row.active ? '*' : ''}${row.disabled ? '!' : ''}`).join(' ');
  assert.equal(labels({mode:'chat', conversationRoot:'', workshops:rooms}), 'Chat* Workshop Canvas');
  assert.equal(labels({mode:'chat', conversationRoot:'child-a', workshops:rooms}), 'Chat Workshop* Canvas');
  assert.equal(labels({mode:'canvas', conversationRoot:'child-a', workshops:rooms}), 'Chat Workshop Canvas*');
  assert.equal(labels({mode:'chat', conversationRoot:'', workshops:[]}), 'Chat* Workshop! Canvas');
  assert.equal(segments({mode:'chat', conversationRoot:'', workshops:[]})[1].title, 'No Workshop conversation in this scope');
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
});

test('studio-workshop.jsx ships as its own Studio source, loaded after brain-model.jsx and before studio-lm.jsx everywhere', () => {
  assert.ok(fs.existsSync(workshopPath), 'nodelang/studio/studio-workshop.jsx is shipped');
  const names = read('packaging/compile_studio.cjs').match(/const names = \[([\s\S]*?)\];/)[1];
  assert.match(names, /'brain-model\.jsx', 'studio-workshop\.jsx', 'studio-lm\.jsx', 'mount\.jsx'/);
  assert.match(read('nodelang/studio/studio.html'), /'brain-model\.jsx','studio-workshop\.jsx','studio-lm\.jsx','mount\.jsx'\]/);
  const server = read('nodelang/application_server.py');
  const admitted = server.slice(server.indexOf('def _clean_studio_asset'), server.indexOf('if name not in admitted'));
  assert.match(admitted, /"studio-workshop\.jsx"/);
  assert.match(admitted, /"compiled\/studio-workshop\.js"/);
  const installer = read('installer/build_release.ps1');
  assert.match(installer, /'selected\/nodelang\/studio\/studio-workshop\.jsx'/);
  assert.match(installer, /'brain-model\.js', 'studio-workshop\.js', 'studio-lm\.js', 'mount\.js'\)/);
  assert.match(installer, /\$entries\.Count -ne 14\) \{ throw 'Studio compiler did not produce exactly thirteen scripts and one manifest\.'/);
  assert.match(installer, /\$manifest\.files\.Count -ne 13\) \{ throw 'Unsupported Studio compiler manifest\.'/);
});

test('studio-lm.jsx reads the Workshop from the module: the rail takes the sidebar panel, the view takes the workspace', () => {
  const sidebar = source.slice(source.indexOf('const Sidebar ='), source.indexOf('const IconRail ='));
  assert.match(sidebar, /workshopContext && window\.WorkshopAgentsRail\s*\? <window\.WorkshopAgentsRail [^]*?sel=\{wsSel\.agent\} onAddAgent=\{onAddAgent\}/);
  const workspace = source.slice(source.indexOf('const Workspace ='), source.indexOf('const modelRoute ='));
  assert.match(workspace, /workshop && window\.WorkshopView \? <window\.WorkshopView key=[^]*?state=\{workshopState\} descriptor=\{workshop\} target=\{target\}[^]*?onLeave=\{\(\) => updateView\(\{conversationRoot:'', mode:'chat', target:''\}\)\}\s*sel=\{wsSel\} setSel=\{setWsSel\} externalRail\/>/);
  assert.match(source, /onAddAgent=\{\(\) => setLibraryOpen\(true\)\}/);
  for (const retired of ['const WorkshopConversation =', 'const WorkshopAgentsPanel =', 'const WorkshopTaskCard =',
    'const WorkshopTaskBoard =', 'const WorkshopLayoutPane =', 'const workshopTaskItems =']) {
    assert.equal(source.includes(retired), false, 'studio-lm.jsx no longer defines ' + retired);
  }
  const module = workshop();
  assert.match(module, /window\.WorkshopView = WorkshopView;\nwindow\.WorkshopAgentsRail = AgentsRail;/);
  // The design's authored scene is not shipped: every value on the surface comes from a projection.
  for (const seeded of ['Atlas', 'CAD Reader', 'Revit Builder', 'Rhino Bridge', 'BABOOM', 'Tower-A_central', 'L03-base',
    'seedTasks', 'WS_RUN', 'WS_AGENTS', 'window.wsNode', '09:47', 'Spend cap']) {
    assert.equal(module.includes(seeded), false, 'studio-workshop.jsx carries no ' + JSON.stringify(seeded));
  }
});

test('task cards fold every event of one named Work into one card whose state is its latest verb', () => {
  const module = workshop();
  const context = vm.createContext({});
  vm.runInContext(module.slice(module.indexOf('const WORKSHOP_WORK_REF ='), module.indexOf('// One participant tone')) +
    '\nglobalThis.items = workshopTaskItems;', context);
  const note = (root, sender, body) => ({root, sender_root:sender, body, state:'recorded', category:'note', recipient_roots:[]});
  const rows = [
    note('m1', 'agent-a', 'Claimed Work assembly-instance:aaaaaaaa11112222.'),
    note('m2', 'agent-b', 'Please look at the export when you can.'),
    note('m3', 'agent-a', 'Submitted Work assembly-instance:aaaaaaaa11112222.'),
    note('m4', 'agent-b', 'Claimed Work assembly-instance:bbbbbbbb33334444.'),
    note('m5', 'agent-a', 'Claimed Work work:repair-export'),
    note('m6', 'agent-a', 'Gate failed for Work work:repair-export: pytest exit 1'),
  ];
  const items = context.items(rows, [{id:'work:repair-export', title:'Repair export', status:'OPEN'}]);
  assert.deepEqual(Array.from(items, item => item.kind === 'task' ? `${item.title}|${item.state}|${item.events.map(e => e.root).join(',')}` : item.message.root), [
    'assembly-instance · aaaaaaaa|review|m1,m3', 'm2', 'assembly-instance · bbbbbbbb|run|m4', 'Repair export|block|m5,m6']);
  assert.equal(context.items([], []).length, 0);
});

// A live-shaped fixture: studio-existing-workshop.js snapshot, projectStudioCanvas nodes and wires.
function fixture() {
  const now = Date.now() / 1000;
  const W1 = 'assembly-instance:3f9a1c7e5b2d4f60', W2 = 'assembly-instance:8b41d0e27c93a5f1', W3 = 'assembly-instance:c5e2a9f4180d7b36';
  const codex = 'app:agent-session:runtime:codex-a1', claude = 'app:agent-session:runtime:claude-b2', gone = 'app:agent-session:runtime:gone-c3';
  const participants = [
    {root:'owner-a', label:'Owner', attached:true, is_agent:false, connection_status:'unknown'},
    {root:gone, label:'Gone agent', attached:true, is_agent:true, connection_status:'disconnected', observed_at:now - 360, runtime:'antigravity-ide'},
    {root:codex, label:'Codex', attached:true, is_agent:true, connection_status:'connected', connection_basis:'authenticated-request',
      observed_at:now - 30, expires_at:now + 3600, runtime:'codex · local', session_link:'attached'},
    {root:claude, label:'Claude Code', attached:true, is_agent:true, connection_status:'connected', connection_basis:'authenticated-request',
      observed_at:now - 10, expires_at:now + 3600, runtime:'claude · local', session_link:'none'},
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
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, URL, Blob, TextEncoder});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
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

test('the Workshop view draws the design surfaces from the live projections and keeps every live action', async () => {
  const {state, authority, calls, ids} = fixture();
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = authority;
    let sel = {agent:null, task:null}, mode = '', left = 0, target = 'model:model-a';
    const props = () => ({state, descriptor:state.workshops[0], target, setTarget:value => { target = value; },
      setMode:value => { mode = value; }, setFocusId:() => {}, onLeave:() => { left += 1; },
      sel, setSel:value => { sel = value; }, externalRail:true});
    await ui.render('WorkshopView', props());
    const doc = ui.doc;
    // Bar: WORKSHOP chip, the Workshop's label, live counts, LAYOUT strip and leave.
    const main = doc.querySelector('main');
    assert.equal(main.style.gridTemplateColumns, 'minmax(0,1fr) 320px');
    assert.match(text(main.firstElementChild), /^WORKSHOP L03 wall take-off 1 needs you · 1 running · 1 submitted · 0 delivered LAYOUT/);
    const strip = [...doc.querySelectorAll('[role="group"][aria-label="Workshop layout"] button')];
    assert.deepEqual(strip.map(b => b.getAttribute('aria-label')), ['Conversation', 'Task board', 'Chat + live graph']);
    assert.deepEqual(strip.map(b => b.getAttribute('aria-pressed')), ['true', 'false', 'false']);
    // Conversation: the owner's ask, the canvas workflow with its approval row, then one card per named Work.
    const stream = doc.querySelector('[aria-label="Workshop conversation"]');
    assert.match(text(stream), /Here is the workflow on this canvas\. 4 nodes, 1 of them yours to confirm\./);
    assert.match(text(stream), /AWAITING YOUR APPROVAL · LAYER SELECTION/);
    assert.deepEqual([...stream.querySelectorAll('[data-workshop-task]')].map(card => card.getAttribute('data-workshop-task')), [ids.W1, ids.W2, ids.W3]);
    const first = stream.querySelector('[data-workshop-task]');
    assert.match(text(first), /^3f9a1c7e Layer selection C NEEDS YOU C Codex · Gate failed/);
    assert.deepEqual([...first.querySelectorAll('button')].map(text), ['Approve this repair', 'Generate repair artifact']);
    // Context panel: the design's sections for the first agent in the rail order.
    const context = () => doc.querySelector('[aria-label="Workshop context"]');
    assert.match(text(context()), /^SELECTED · AGENT/);
    for (const section of ['CURRENT TASK', 'PERMISSIONS', 'CONNECTED TOOLS', 'ACTIVITY · TOOL RECORDS']) assert.ok(text(context()).includes(section), section);
    // Send, approve: the live actions.
    const input = doc.querySelector('input[aria-label="Workshop message"]');
    await ui.act(() => { Object.getOwnPropertyDescriptor(ui.win.HTMLInputElement.prototype, 'value').set.call(input, 'Check the joins');
      input.dispatchEvent(new ui.win.Event('input', {bubbles:true})); });
    await ui.act(() => input.dispatchEvent(new ui.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    assert.deepEqual(calls.filter(c => c[0] === 'sendModelConversation').map(c => [c[1], c[2].root, c[3]]), [['room-a', 'model-a', 'Check the joins']]);
    await ui.click([...first.querySelectorAll('button')][0]);
    assert.equal(calls.filter(c => c[0] === 'approveNativeWork').length, 1);
    // Select a task card: the context panel reads that Work.
    await ui.click(first);
    assert.deepEqual(JSON.parse(JSON.stringify(sel)), {agent:null, task:ids.W1});
    await ui.render('WorkshopView', props());
    assert.match(text(context()), /^SELECTED · TASK 3f9a1c7e/);
    assert.match(text(context()), /intent Pick the source wall layers criteria — blocks Wall creation state NEEDS YOU/);
    // Relocated controls sit behind the context panel's ⋯.
    await ui.click(doc.querySelector('button[aria-label^="Workshop controls"]'));
    assert.ok(doc.querySelector('[aria-label="Native Workshop review"]'), 'Work on a project is behind ⋯');
    await ui.click([...doc.querySelectorAll('[aria-label="Workshop feed"] [role="button"]')].find(b => text(b) === 'Tool activity'));
    assert.deepEqual(calls.filter(c => c[0] === 'showWorkshopFeed').map(c => c[2]), ['activity']);
    // Task board: the design's three columns.
    await ui.click(strip[1]);
    const board = doc.querySelector('[aria-label="Workshop task board"]');
    assert.deepEqual([...board.querySelectorAll('h3')].map(text), ['NEEDS YOU', 'RUNNING', 'DELIVERED']);
    assert.equal(doc.querySelector('main').style.gridTemplateColumns, 'minmax(0,1fr) 300px');
    // Chat + live graph: projected nodes and the design's arrange / chain controls.
    await ui.click(doc.querySelector('button[aria-label="Chat + live graph"]'));
    const graph = doc.querySelector('[aria-label="Workshop live graph"]');
    assert.deepEqual([...graph.querySelectorAll('[data-node]')].map(n => n.getAttribute('data-node')).sort(), [ids.W1, ids.W2, ids.W3, 'read-dwg'].sort());
    assert.match(text(graph), /Wires carry behaviour\. Removing the wire into Layer selection stops what it receives;/);
    await ui.click(graph.querySelector('button[aria-label^="Select the whole connected chain"]'));
    assert.equal(graph.querySelectorAll('[data-node][aria-current="true"]').length, 4);
    await ui.click(graph.querySelector('button[aria-label="Open as nodes"]'));
    assert.equal(mode, 'canvas');
    await ui.click(doc.querySelector('button[aria-label^="Leave Workshop"]'));
    assert.equal(left, 1);
  } finally { await ui.close(); }
});

test('the agents rail is the transcript participants with verified connection facts, and selecting one addresses it', async () => {
  const {state, authority, ids} = fixture();
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = authority;
    const picked = [];
    const context = {descriptor:state.workshops[0], graphId:'graph-a', scopeRoot:'scope-a', transcript:state.workshop, state};
    await ui.render('WorkshopAgentsRail', {context, sel:null, onSelect:(id, addressable) => picked.push([id, addressable]), onAddAgent:() => picked.push(['library'])});
    const rail = ui.doc.querySelector('[aria-label="Workshop agents"]');
    assert.match(text(rail), /^CONNECTED AGENTS/);
    const rows = [...rail.querySelectorAll('[data-workshop-agent]')];
    assert.deepEqual(rows.map(r => r.getAttribute('data-workshop-agent')), [ids.codex, ids.claude, ids.gone], 'verified agents first; the owner is not an agent row');
    assert.deepEqual(rows.map(r => r.getAttribute('aria-pressed')), ['true', 'false', 'false']);
    assert.match(text(rows[0]), /^C Codex AGENT codex · local WAITING FOR INPUT/);
    assert.match(text(rows[1]), /^C Claude Code AGENT claude · local WORKING/);
    assert.match(text(rows[2]), /^G Gone agent AGENT antigravity-ide DISCONNECTED · 6m Disconnected from this app\./);
    assert.match(text(rail), /SCOPE Write access: not projected for these agents\. Recent activity is not a running task\.$/);
    await ui.click(rows[1]);
    await ui.click(rail.querySelector('button[aria-label^="Connect another agent"]'));
    assert.deepEqual(picked, [[ids.claude, true], ['library']]);
  } finally { await ui.close(); }
});