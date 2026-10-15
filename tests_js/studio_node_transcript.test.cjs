/* Canvas live-node conversation rail: a node with has_conversation shows its Workshop
   transcript READ-ONLY (GET /api/universal/workshop-transcript, rows {id,who,is_me,time,text,kind}),
   for ANY live bound node (a workflow Workshop room has a `conversation` and no `model`),
   re-reads on open, serializes polls, rejects stale responses, and offers "Continue in the Workshop".
   Real browser-owner callbacks in memory; no provider, app or database. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const lmPath = process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-lm.jsx');
const dir = path.dirname(lmPath);
const source = fs.readFileSync(lmPath, 'utf8');
const paramsSource = fs.readFileSync(path.join(dir, 'studio-params.jsx'), 'utf8');
const html = fs.readFileSync(path.join(dir, 'studio.html'), 'utf8');
const authority = fs.readFileSync(path.join(dir, 'studio-authority.js'), 'utf8');

const slice = (from, to) => {
  const start = source.indexOf(from), end = source.indexOf(to, start);
  assert.ok(start > 0 && end > start, from + ' is a slice of the shipped studio-lm.jsx');
  return source.slice(start, end);
};
// Conversation component + transcript row support. Stop before the composer stack; the VM
// supplies a stub InlineAsk so these tests stay focused on transcript binding.
const conversationSlice = () => slice('const NodeModelConversation =', '// One chat, two parts of one panel') +
  "\nconst CHAT_TURN_EVENT = 'archhub:chat-turn';\n";
// Add the real rail gate and its nearby dependencies when a test mounts NodeRail.
const railSlice = () => slice('const NodeModelConversation =', '\nconst ConversationRail =');
const canvasSlice = () => slice('const SOCKET_TOP =', '\nconst NodeStateDot =') + require('./workshop72_node_helpers.cjs').nodePreviewSource(source);
const refreshSlice = () => slice('const studioRefreshCanvasInPlace =', '\nconst StudioLM =');
const shortcutSlice = () => slice('const studioShortcut =', '\n// An ordinary canvas edit');

// The real helpers this slice actually depends on, so the model gate is exercised without
// compiling the unrelated generation-default helper block into every VM mount.
const REAL_HELPERS = [
  source.match(/const modelRoute = [^\n]+/)[0],
  source.slice(source.indexOf('const nodeModelRow ='), source.indexOf('const modelDisplayName ='))
].join('\n');
const RAIL_HELPERS = [
  source.match(/const modelRoute = [^\n]+/)[0],
  source.slice(source.indexOf('const nodeModelRow ='), source.indexOf('// ─── Chat lane data seam ───'))
].join('\n');

const testTokens = () => new Proxy({}, {get:(_, k) => {
  if (k === 'rad') return {chip:3, xs:3, control:5, sm:5, node:6, md:6, panel:8, lg:8, dialog:10, xl:10, pill:999};
  if (k === 'sp') return {xs:4, sm:8, md:12, lg:16, xl:24};
  if (k === 'fs') return {bodySm:{sz:13, ln:18, wt:400}, bodySmStrong:{sz:13, ln:18, wt:500}, caption:{sz:12, ln:16}, label:{sz:11, ln:14, wt:500, letter:'.04em'}, data:{sz:12, ln:16, wt:400}, dataSm:{sz:11, ln:14, wt:400}};
  if (k === 'icon') return {ui:{size:16, box:20}, category:{size:12, box:20}};
  if (k === 'shadow') return {flat:'none'};
  if (k === 'dur') return {fast:120, med:180};
  return 'token-' + String(k);
}});

async function mountEnv(fn, opts = {}) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window;
  global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const LM = testTokens();
  const studioCategory = () => ({col:'#E0794A', icon:'A', label:'AI', role:''});
  const InlineAsk = () => React.createElement('textarea', {'data-stub':'inlineask'});
  const HoverBtn = ({onClick, disabled, children}) => React.createElement('button', {onClick, disabled}, children);
  win.NodeInspector = () => React.createElement('div', {'data-stub':'inspector'});
  const ConversationRail = () => React.createElement('div', {'data-stub':'convrail'});
  const context = vm.createContext({React, LM, studioCategory, InlineAsk, HoverBtn, ConversationRail,
    modelRoute: m => String((m && (m.routed || m.route)) || ''),
    modelDisplayName: m => String((m && (m.name || m.routed || m.route)) || ''),
    routeReadiness: () => null,
    generationRequestOptions: () => ({}),
    agentAnswerText: answer => typeof answer === 'string' ? answer : String(answer?.answer || answer?.text || ''),
    agentDeliveryState: result => result?.delivery?.state || null,
    window:win, document:win.document, setInterval, clearInterval, setTimeout, clearTimeout});
  const componentSlice = opts.withRail ? railSlice() : conversationSlice();
  const exports = opts.withRail ? '\nglobalThis.Conv = NodeModelConversation; globalThis.Rail = NodeRail;'
    : '\nglobalThis.Conv = NodeModelConversation;';
  const helpers = opts.withRail ? RAIL_HELPERS : REAL_HELPERS;
  vm.runInContext(transformSync(helpers + componentSlice + exports,
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  try { await fn({React, win, root, context}); }
  finally {
    await React.act(async () => root.unmount());
    win.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
}
const tick = async React => { await React.act(async () => { await new Promise(r => setTimeout(r, 0)); }); };

async function mountForkRail(kind, createResult) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53915/'});
  for (const [name, value] of [['offsetWidth', 210], ['offsetHeight', 110]]) {
    Object.defineProperty(dom.window.HTMLElement.prototype, name, {configurable:true, get() { return value; }});
  }
  dom.window.HTMLElement.prototype.getBoundingClientRect = () => ({left:0, top:0, width:1200, height:800, right:1200, bottom:800});
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window; global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const created = []; let refreshes = 0;
  const node = {id:'node-a', title:'Alpha', engine:'calc', live:true, cat:'ai', x:50, y:70, w:210, h:110, sub:'', ins:[], outs:[], messages:[],
    has_conversation:true, conversation_root:'conv-a', params:[{k:'value', v:'7'}, {k:'seed', v:'skip'}]};
  let snapshot = {graph:{nodes:[node], wires:[]}, canvas:{revision:3,
    scope:{current:'scope-a', trail:[{root:'scope-a'}]}, authorization:{subject:'founder', session:'s'}}};
  win.ARCHHUB_NODE_CREATE = async spec => {
    created.push(JSON.parse(JSON.stringify(spec)));
    const result = typeof createResult === 'function' ? createResult(spec) : createResult;
    if (result && result.ok !== false) {
      const createdId = result?.node?.id || result?.id || result?.node_id || result?.root;
      if (createdId) snapshot = {...snapshot, graph:{...snapshot.graph,
        nodes:[...snapshot.graph.nodes.filter(held => held.id !== createdId), {...node, id:createdId, title:spec.title, x:spec.x, y:spec.y}]}};
    }
    return result;
  };
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({topology:snapshot}),
    refreshTopologyCanvas:async () => { refreshes += 1; return snapshot; },
  };
  win.PM_TYPES = {text:{label:'Text', wire:false}, number:{label:'Number', wire:false}};
  win.pmType = type => win.PM_TYPES[type] || win.PM_TYPES.text;
  win.PM_WIRE = {};
  win.Socket = () => React.createElement('span', {'data-stub':'socket'});
  const LM = testTokens();
  const InlineAsk = () => React.createElement('textarea', {'data-stub':'inlineask'});
  const HoverBtn = ({onClick, disabled, children}) => React.createElement('button', {onClick, disabled}, children);
  const PM = new Proxy({}, {get:(_, k) => k === 'rad' ? new Proxy({}, {get:()=>4}) : 'pm-' + String(k)});
  win.PM = PM; win.AH = PM;
  const context = vm.createContext({React, LM, PM, InlineAsk, HoverBtn, window:win, document:win.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, WIRE:{}, CANVAS_VIEWS:new Map(), LM_SESSIONS:[],
    CAT:{ai:{col:'#E0794A', icon:'A', label:'AI'}},
    studioCategory:() => ({col:'#E0794A', icon:'A', label:'AI', role:''}),
    modelRoute: m => String((m && (m.routed || m.route)) || ''),
    modelDisplayName: m => String((m && (m.name || m.routed || m.route)) || ''),
    routeReadiness: () => null, generationRequestOptions: () => ({}),
    agentAnswerText: answer => typeof answer === 'string' ? answer : String(answer?.answer || answer?.text || ''),
    agentDeliveryState: result => result?.delivery?.state || null,
    NodeBody:() => null,
    CanvasToolbar:() => null, FloatingComposer:() => null, CanvasAddBox:() => null, MiniMap:() => null,
    smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({}), studioCanvasScope:() => 'scope-a',
    setInterval, clearInterval, setTimeout:win.setTimeout.bind(win), clearTimeout:win.clearTimeout.bind(win),
    ResizeObserver:undefined});
  const inspectorStart = paramsSource.indexOf('function NodeInspector(');
  const paramDeps = paramsSource.slice(0, inspectorStart);
  const inspector = paramsSource.slice(inspectorStart, paramsSource.indexOf('Object.assign(window', inspectorStart));
  const rails = slice('const NodeModelConversation =', '// ──────────────────────── SETTINGS');
  vm.runInContext(transformSync(paramDeps + inspector + '\nglobalThis.NodeInspector = NodeInspector;',
    {loader:'jsx', format:'cjs'}).code, context);
  win.NodeInspector = context.NodeInspector;
  const freeSlot = slice('const studioFreeSlot =', 'const studioRefreshCanvasInPlace =');
  vm.runInContext(transformSync(refreshSlice() + shortcutSlice() + freeSlot + canvasSlice() + '\nglobalThis.NodeCanvas = NodeCanvas;',
    {loader:'jsx', format:'cjs'}).code, context);
  vm.runInContext(transformSync(RAIL_HELPERS + rails + '\nglobalThis.NodeRail = NodeRail; globalThis.ConversationRail = ConversationRail;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  const Component = kind === 'conversation' ? context.ConversationRail : context.NodeRail;
  const render = async ({canvas = true} = {}) => React.act(async () => root.render(React.createElement(React.Fragment, null,
    canvas && React.createElement(context.NodeCanvas, {focusId:'node-a', setFocusId:() => {}, setLibraryOpen:() => {},
      userNodes:[], addNodeFromLibrary:() => {}, model:null}),
    React.createElement(Component, {node, scope:'scope-a', openConversation:()=>{}}))));
  await render();
  const clickFork = async () => {
    let button = [...win.document.querySelectorAll('button')].find(b => b.getAttribute('title') === 'Fork this node onto the canvas' || b.textContent === '⑂');
    if (!button) {
      const properties = [...win.document.querySelectorAll('button')].find(b => b.textContent === 'Properties');
      if (properties) await React.act(async () => { properties.click(); await new Promise(r => setTimeout(r, 0)); });
      button = [...win.document.querySelectorAll('button')].find(b => b.getAttribute('title') === 'Fork this node onto the canvas' || b.textContent === '⑂');
    }
    assert.ok(button, kind + ' renders the real Fork control: ' + [...win.document.querySelectorAll('button')].map(b => (b.getAttribute('title') || '') + ':' + b.textContent).join('|'));
    await React.act(async () => { button.click(); await new Promise(r => setTimeout(r, 0)); });
  };
  const close = async () => {
    await React.act(async () => root.unmount());
    win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT;
  };
  return {win, created, get refreshes() { return refreshes; }, clickFork, render, close,
    selectedCard:id => win.document.querySelector('.lm-node[data-node-id="' + id + '"][data-selected="true"]')};
}

test('NodeRail and ConversationRail Fork use the canvas duplicate operation and select the confirmed node', async () => {
  for (const kind of ['node', 'conversation']) {
    const view = await mountForkRail(kind, {ok:true, id:'node-copy'});
    try {
      await view.clickFork();
      assert.equal(view.created.length, 1, kind + ' creates once');
      assert.equal(view.refreshes, 1, kind + ' refreshes the canvas once');
      assert.ok(view.selectedCard('node-copy'), kind + ' selects the confirmed node');
      const box = card => ({x:parseFloat(card.style.left), y:parseFloat(card.style.top), w:card.offsetWidth, h:card.offsetHeight});
      const copy = box(view.selectedCard('node-copy'));
      const original = box(view.win.document.querySelector('.lm-node[data-node-id="node-a"]'));
      assert.equal(copy.x < original.x + original.w && original.x < copy.x + copy.w &&
        copy.y < original.y + original.h && original.y < copy.y + copy.h, false, kind + ' Fork clears the drawn source card');
      assert.match(view.win.document.body.textContent, /Fork placed\./);
    } finally { await view.close(); }
  }
});

test('NodeRail Fork refusal shows one-line error and selects nothing', async () => {
  const view = await mountForkRail('node', {ok:false, error:'refused by policy\nstack'});
  try {
    await view.clickFork();
    assert.equal(view.created.length, 1);
    assert.equal(view.refreshes, 0);
    assert.equal(view.selectedCard('node-copy'), null);
    assert.match(view.win.document.body.textContent, /refused by policy/);
    assert.doesNotMatch(view.win.document.body.textContent, /stack/);
  } finally { await view.close(); }
});

test('ConversationRail Fork treats a null create as unconfirmed without retry', async () => {
  const view = await mountForkRail('conversation', null);
  try {
    await view.clickFork();
    assert.equal(view.created.length, 1);
    assert.equal(view.refreshes, 0);
    assert.equal(view.selectedCard('node-copy'), null);
    assert.match(view.win.document.body.textContent, /Fork not confirmed/);
  } finally { await view.close(); }
});

test('NodeRail Fork reports unavailable after NodeCanvas unmounts', async () => {
  const view = await mountForkRail('node', {ok:true, id:'node-copy'});
  try {
    assert.equal(typeof view.win.__archhubDuplicateNode, 'function');
    await view.render({canvas:false});
    assert.equal(view.win.__archhubDuplicateNode, undefined);
    await view.clickFork();
    assert.equal(view.created.length, 0);
    assert.equal(view.refreshes, 0);
    assert.match(view.win.document.body.textContent, /Fork is unavailable in this view\./);
  } finally { await view.close(); }
});

// ── projection fields reach the client node (studio-authority.js map) ──
test('the clean canvas node carries conversation_root and has_conversation', () => {
  const anchor = authority.indexOf('node.category');
  const map = authority.slice(authority.lastIndexOf('return {', anchor), authority.indexOf('};', anchor));
  assert.match(map, /conversation_root:\s*node\.conversation_root/);
  assert.match(map, /has_conversation:\s*node\.has_conversation\s*===\s*true/);
});

// ── the read-only transcript reader exists and hits the agreed route ──
test('studio.html exposes a read-only node-transcript reader on the agreed route', () => {
  assert.match(html, /ARCHHUB_WORKSHOP_TRANSCRIPT\s*=/);
  const reader = html.slice(html.indexOf('ARCHHUB_WORKSHOP_TRANSCRIPT'),
    html.indexOf(';', html.indexOf('ARCHHUB_WORKSHOP_TRANSCRIPT')) + 1);
  assert.match(reader, /\/api\/universal\/workshop-transcript\?node=/);
  assert.match(reader, /scope=/);
  assert.match(reader, /jget\(/);
});

// ── the rail is wired with the scope and a continue-in-Workshop opener, gated for ANY bound node ──
test('the Workspace threads scope + opener, and NodeRail admits every live conversation target', () => {
  const workspace = slice('const Workspace =', '// The string the server');
  assert.match(workspace, /<NodeRail[\s\S]*?scope=\{/);
  assert.match(workspace, /<NodeRail[\s\S]*?openConversation=\{/);
  // Every live target can receive a composer turn, including model-less rooms
  // and model nodes whose short canvas summary omits their model parameter.
  const rail = slice('const NodeRail =', '\nconst ConversationRail =');
  assert.match(rail, /\{inspectedNode\.live \?\s*<NodeModelConversation/,
    'NodeRail must render the conversation component for every live target, including model-less rooms');
});

// ── FINDING 1: a real NodeRail mount with a model-less Workshop room node ──
test('NodeRail shows the transcript + Continue for a model-less room node', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    const calls = [];
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node, scope) => {
      calls.push({node, scope});
      return {ok:true, node, conversation_root:'app:workshop', revision:4, has_older:true, next_before:'b1',
        rows:[{id:'m1', who:'You', is_me:true, time:'2026-10-01T18:51:32.468877+00:00', text:'PROPOSE a workflow.', kind:'message'},
              {id:'m2', who:'acceptance-claude', is_me:false, time:'2026-10-01T18:51:34.031545+00:00', text:'Here is my proposal.', kind:'reply'}]};
    };
    // The real bound node: a Workshop room — conversation param, NO model.
    const room = {id:'assembly-instance:room', title:'This Workshop', live:true, cat:'ai',
      has_conversation:true, conversation_root:'app:workshop', params:[{k:'conversation', v:'app:workshop'}]};
    const opened = [];
    await React.act(async () => root.render(React.createElement(context.Rail,
      {node:room, scope:'app:workshop', openConversation:r => opened.push(r)})));
    await tick(React);
    const text = win.document.getElementById('root').textContent;
    assert.ok(calls.length >= 1 && calls[0].node === 'assembly-instance:room', 'the room node transcript is read');
    assert.match(text, /PROPOSE a workflow\./, 'the transcript renders for a model-less node');
    assert.match(text, /Here is my proposal\./);
    assert.match(text, /Latest messages only/, 'has_older shows the honest history hint');
    assert.equal(win.document.querySelector('#root textarea'), null, 'a model-less node shows no model composer');
    const cont = [...win.document.querySelectorAll('button')].find(b => /full history in the workshop/i.test(b.textContent));
    assert.ok(cont, 'with older history, a labelled full-history link is present');
    await React.act(async () => cont.click());
    assert.deepEqual(opened, ['app:workshop']);
  }, {withRail:true});
});

// ── a model-bearing node keeps the model composer AND can show a transcript ──
test('a model node keeps its composer; honest-empty when no rows', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    let transcriptReads = 0;
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node) => {
      transcriptReads += 1;
      assert.ok(transcriptReads <= 4, 'transcript read loop: ' + transcriptReads);
      return {ok:true, node, conversation_root:'conv-a',
        revision:4, has_older:false, next_before:null, rows:[]};
    };
    const modelNode = {id:'node-m', title:'Agent', live:true, cat:'ai', has_conversation:true,
      conversation_root:'conv-a', params:[{k:'model', v:'openrouter/model-a'}]};
    await React.act(async () => root.render(React.createElement(context.Conv,
      {node:modelNode, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    // 2cc408f6: exactly one chat input, the panel's own composer; the conversation section draws none.
    assert.equal(win.document.querySelector('#root textarea[data-stub="inlineask"]'), null, 'no second composer inside the conversation section');
    assert.match(win.document.getElementById('root').textContent, /No conversation yet/, 'empty bound transcript is honest');
    const text = win.document.getElementById('root').textContent;
    assert.match(text, /No conversation yet · ask below to start one\./, 'the empty state starts the chat here');
    assert.equal(transcriptReads, 1, 'empty transcript is read once on mount');
    assert.equal([...win.document.querySelectorAll('button')].some(b => /workshop/i.test(b.textContent)), false,
      'an empty chat offers no second destination (no Workshop link)');
  });
});

// ── FINDING 2a: populated rows do NOT survive a scope switch; the stale response is dropped ──
test('rows clear on a scope switch and the stale response never lands', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    const held = {};
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = (node, scope) => new Promise(res => {
      held[scope] = () => res({ok:true, node, conversation_root:'conv-a', revision:4, has_older:false, next_before:null,
        rows:[{id:scope, who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'rows-of-' + scope, kind:'message'}]});
    });
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a',
      params:[{k:'model', v:'openrouter/model-a'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await React.act(async () => { held['scope-a'](); await new Promise(r => setTimeout(r, 0)); });
    assert.match(win.document.getElementById('root').textContent, /rows-of-scope-a/, 'scope-a rows are shown first');
    // switch scope; old rows must clear immediately (not linger under the new binding)
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-b', openConversation:()=>{}})));
    await tick(React);
    const mid = win.document.getElementById('root').textContent;
    assert.ok(!/rows-of-scope-a/.test(mid), 'stale scope-a rows must not linger under scope-b');
    assert.match(mid, /Reading the conversation/, 'the new binding shows loading, not stale rows');
    await React.act(async () => { held['scope-b'](); await new Promise(r => setTimeout(r, 0)); });
    assert.match(win.document.getElementById('root').textContent, /rows-of-scope-b/, 'scope-b rows land');
  });
});

// ── FINDING 2c: a response whose node/conversation does not match the current binding is rejected ──
test('a response for the wrong node is not shown', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async () => ({ok:true, node:'some-other-node', conversation_root:'conv-a',
      revision:4, has_older:false, next_before:null,
      rows:[{id:'x', who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'WRONG-NODE-ROWS', kind:'message'}]});
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a',
      params:[{k:'model', v:'openrouter/model-a'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    assert.ok(!/WRONG-NODE-ROWS/.test(win.document.getElementById('root').textContent),
      'a mismatched-node response must be rejected, never rendered');
  });
});

// ── FINDING 2b: polls are serialized — a new read never starts while one is in flight ──
test('an 8s poll does not overlap an in-flight read', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window; global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  let poll = null; const fakeSetInterval = fn => { poll = fn; return 1; }; const fakeClearInterval = () => { poll = null; };
  let calls = 0, release = null;
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = (node) => { calls += 1; return new Promise(res => { release = () => res({ok:true, node,
    conversation_root:'conv-a', revision:4, has_older:false, next_before:null, rows:[]}); }); };
  const LM = testTokens();
  const studioCategory = () => ({col:'#E0794A', icon:'A', label:'AI'});
  const InlineAsk = () => React.createElement('textarea', {}); const HoverBtn = ({children}) => React.createElement('button', {}, children);
  win.NodeInspector = () => null; const ConversationRail = () => null;
  const context = vm.createContext({React, LM, studioCategory, InlineAsk, HoverBtn, ConversationRail,
    window:win, document:win.document, setInterval:fakeSetInterval, clearInterval:fakeClearInterval, setTimeout, clearTimeout});
  vm.runInContext(transformSync(REAL_HELPERS + conversationSlice() + '\nglobalThis.Conv = NodeModelConversation;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  try {
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a', params:[{k:'model', v:'m'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await React.act(async () => { await new Promise(r => setTimeout(r, 0)); });
    assert.equal(calls, 1, 'the open read fired once');
    // fire the poll twice WHILE the first read is still in flight
    await React.act(async () => { if (poll) { poll(); poll(); } await new Promise(r => setTimeout(r, 0)); });
    assert.equal(calls, 1, 'a poll must not start a new read while one is in flight');
    await React.act(async () => { release(); await new Promise(r => setTimeout(r, 0)); });
    await React.act(async () => { if (poll) poll(); await new Promise(r => setTimeout(r, 0)); });
    assert.equal(calls, 2, 'once the in-flight read settles, the next poll may read');
  } finally {
    await React.act(async () => root.unmount());
    win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});

// ── FOLLOW-UP 1: a same-node conversation_root rebind drops the old read that resolves after the new ──
test('a conversation_root rebind drops the old read that resolves after the new one', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    const pending = [];
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = () => new Promise(res => pending.push(res));
    const base = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, params:[{k:'model', v:'m'}]};
    // open on conversation_root conv-a (read A starts, unresolved)
    await React.act(async () => root.render(React.createElement(context.Conv, {node:{...base, conversation_root:'conv-a'}, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    // rebind the SAME node to conv-b (read B starts); A is still unresolved
    await React.act(async () => root.render(React.createElement(context.Conv, {node:{...base, conversation_root:'conv-b'}, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    assert.equal(pending.length, 2, 'both the old and the new read are in flight');
    // the NEW read (B) resolves first, then the OLD read (A) resolves late
    await React.act(async () => { pending[1]({ok:true, node:'node-a', conversation_root:'conv-b', revision:4, has_older:false, next_before:null, rows:[{id:'b', who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'rows-conv-b', kind:'message'}]}); await new Promise(r => setTimeout(r, 0)); });
    await React.act(async () => { pending[0]({ok:true, node:'node-a', conversation_root:'conv-a', revision:4, has_older:false, next_before:null, rows:[{id:'a', who:'You', is_me:true, time:'2026-10-01T18:51:30Z', text:'rows-conv-a', kind:'message'}]}); await new Promise(r => setTimeout(r, 0)); });
    const text = win.document.getElementById('root').textContent;
    assert.match(text, /rows-conv-b/, 'the rebound conversation shows');
    assert.ok(!/rows-conv-a/.test(text), 'the old conversation_root read must never render after a rebind');
  });
});

// ── FOLLOW-UP 2a: a null/missing conversation_root response is refused while the node is bound ──
test('a response with null conversation_root is refused for a bound node', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node) => ({ok:true, node, conversation_root:null,
      revision:4, has_older:false, next_before:null,
      rows:[{id:'x', who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'NULL-ROOT-ROWS', kind:'message'}]});
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a', params:[{k:'model', v:'m'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    assert.ok(!/NULL-ROOT-ROWS/.test(win.document.getElementById('root').textContent),
      'a bound node must refuse a response whose conversation_root is null/missing');
  });
});

// ── FOLLOW-UP 2b: an unbound node is explicitly empty — no read, no loading, no error ──
test('an unbound node renders empty, never loading or stale rows', async () => {
  await mountEnv(async ({React, win, root, context}) => {
    let calls = 0; win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node) => { calls += 1; return {ok:true, node, conversation_root:'conv-a', rows:[], has_older:false}; };
    // a model node that is NOT conversation-bound: composer only, no transcript
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:false, conversation_root:null, params:[{k:'model', v:'m'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await tick(React);
    const text = win.document.getElementById('root').textContent;
    assert.equal(calls, 0, 'an unbound node issues no transcript read');
    assert.ok(!/Reading the conversation/.test(text), 'an unbound node never shows the loading state');
    assert.ok(!/could not be read/.test(text), 'an unbound node shows no error');
    assert.ok(win.document.querySelector('#root textarea'), 'the model composer is still shown');
  });
});

// ── FINDING 2: unmount mid-flight does not set state after teardown ──
test('a read that resolves after unmount throws nothing and sets no state', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window; global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const errors = []; const origErr = console.error; console.error = (...a) => errors.push(a.join(' '));
  let release;
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = (node) => new Promise(res => { release = () => res({ok:true, node,
    conversation_root:'conv-a', revision:4, has_older:false, next_before:null, rows:[{id:'m', who:'You', is_me:true, time:'2026-10-01T18:51:32Z', text:'late', kind:'message'}]}); });
  const LM = testTokens();
  const studioCategory = () => ({col:'#E0794A', icon:'A', label:'AI'});
  const InlineAsk = () => React.createElement('textarea', {});
  const HoverBtn = ({onClick, disabled, children}) => React.createElement('button', {onClick, disabled}, children);
  win.NodeInspector = () => null; const ConversationRail = () => null;
  const context = vm.createContext({React, LM, studioCategory, InlineAsk, HoverBtn, ConversationRail,
    window:win, document:win.document, setInterval, clearInterval, setTimeout, clearTimeout});
  vm.runInContext(transformSync(REAL_HELPERS + conversationSlice() + '\nglobalThis.Conv = NodeModelConversation;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  try {
    const node = {id:'node-a', title:'Agent', live:true, cat:'ai', has_conversation:true, conversation_root:'conv-a', params:[{k:'model', v:'m'}]};
    await React.act(async () => root.render(React.createElement(context.Conv, {node, scope:'scope-a', openConversation:()=>{}})));
    await React.act(async () => root.unmount());
    await React.act(async () => { release(); await new Promise(r => setTimeout(r, 0)); });
    assert.ok(!errors.some(e => /unmounted|not wrapped in act|memory leak/i.test(e)),
      'no set-state-after-unmount warning: ' + errors.join(' | '));
  } finally {
    console.error = origErr; win.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});
