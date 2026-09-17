/* Work the product canvas does not draw: the rail points to the Workshop and the Workshop still reads it. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const adapter = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-existing-workshop.js'), 'utf8');
const workshopSource = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-workshop.jsx'), 'utf8');
const runtime = fs.readFileSync(path.join(__dirname, '../nodelang/ui_runtime.py'), 'utf8');
const tokens = fs.readFileSync(path.join(__dirname, '../nodelang/studio/tokens.jsx'), 'utf8');
const palette = tokens.slice(tokens.indexOf('window.AH = {'), tokens.indexOf('window.ArchHubTheme ='));
const LM = Object.fromEntries([...palette.matchAll(/^ {2}(\w+):/gm)].map(match => [match[1], 'token-' + match[1]]));

const slice = (from, to) => {
  const start = source.indexOf(from), end = source.indexOf(to, start);
  assert.ok(start > 0 && end > start, from + ' is a slice of the shipped studio-lm.jsx');
  return source.slice(start, end);
};

test('the rail button opens the Workshop from the explicit Chat state, through the held-root path', () => {
  const workspace = slice('const Workspace =', '// The string the server');
  assert.match(workspace, /<NodeRail node=\{focusNode\} hiddenWork=\{!focusNode && authorityState\?\.canvas\?\.selection_hidden === true\}/);
  assert.match(workspace, /workshopRoom=\{workshopModeRoom\(workshops, workshop\?\.root \|\| ''\)\}/);
  assert.match(workspace, /onOpenWorkshop=\{\(\) => chooseWorkshopMode\('workshop', \{mode, conversationRoot:workshop\?\.root \|\| '', workshops, setMode,\s*setConversationRoot:root => updateView\(\{conversationRoot:root, mode:'chat', target:''\}\)\}\)\}/);
  const context = vm.createContext({});
  vm.runInContext(slice('const workshopModeRoom =', 'const WsHeader =') +
    '\nglobalThis.segments = workshopModeSegments; globalThis.choose = chooseWorkshopMode; globalThis.room = workshopModeRoom;', context);
  const workshops = [{root:'child-a', is_general:false}, {root:'general-a', is_general:true}];
  // The founder chose Chat (root cleared), then Canvas; the notice shows there.
  let view = {mode:'canvas', conversationRoot:''};
  const updateView = patch => { view = {...view, ...patch}; };
  const open = () => context.choose('workshop', {mode:view.mode, conversationRoot:view.conversationRoot, workshops,
    setMode:mode => updateView({mode}), setConversationRoot:root => updateView({conversationRoot:root, mode:'chat', target:''})});
  assert.equal(context.room(workshops, ''), 'general-a');
  open();
  assert.deepEqual({...view}, {mode:'chat', conversationRoot:'general-a', target:''});
  assert.equal(context.segments({...view, workshops}).find(segment => segment.active).key, 'workshop');
  // A held child room stays the room the button opens.
  view = {mode:'canvas', conversationRoot:'child-a'};
  open();
  assert.equal(view.conversationRoot, 'child-a');
  assert.equal(context.room([], ''), '');
});

test('the rail says where hidden Work lives and disables the button without a Workshop', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const HoverBtn = ({onClick, disabled, children}) => React.createElement('button', {onClick, disabled}, children);
  const context = vm.createContext({React, LM, HoverBtn});
  vm.runInContext(transformSync(slice('const NodeRail =', '\nconst ') + '\nglobalThis.Rail = NodeRail;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(dom.window.document.getElementById('root'));
  const opened = [];
  try {
    await React.act(async () => root.render(React.createElement(context.Rail,
      {node:null, hiddenWork:true, workshopRoom:'general-a', onOpenWorkshop:() => opened.push('open')})));
    const aside = dom.window.document.querySelector('aside[role="status"]');
    assert.match(aside.textContent, /Selected Work is in the Workshop/);
    const button = aside.querySelector('button');
    assert.equal(button.textContent, 'Open the Workshop');
    await React.act(async () => { button.click(); });
    assert.deepEqual(opened, ['open']);
    await React.act(async () => root.render(React.createElement(context.Rail,
      {node:null, hiddenWork:true, workshopRoom:'', onOpenWorkshop:() => opened.push('none')})));
    assert.equal(dom.window.document.querySelector('aside button').disabled, true);
    assert.match(dom.window.document.querySelector('aside').textContent, /No Workshop conversation is in this scope/);
    await React.act(async () => root.render(React.createElement(context.Rail, {node:null, hiddenWork:false})));
    assert.equal(dom.window.document.querySelector('aside[role="status"]'), null);
  } finally {
    await React.act(async () => root.unmount());
    dom.window.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});

test('the Workshop still admits and titles Work the canvas does not draw', () => {
  const context = vm.createContext({window:{}});
  const start = workshopSource.indexOf('const workshopSelectionId =');
  const end = workshopSource.indexOf('// One participant tone for the agents rail', start);
  assert.ok(start > 0 && end > start, 'the Workshop helpers are a slice of the shipped studio-workshop.jsx');
  vm.runInContext(workshopSource.slice(start, end) +
    '\nglobalThis.nodes = workshopProjectedNodes; globalThis.select = selectedWorkshopWork; globalThis.items = workshopTaskItems;', context);
  const state = {canvas:{graph_id:'graph-a', root:'scope-a'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:{subject:'owner-a', session:'view-a'},
      nodes:[{id:'node-a'}], hidden_work:[{id:'assembly-instance:work000a', title:'Website lane'}]},
      graph:{nodes:[{id:'node-a', title:'Node A'}]}, selected:'assembly-instance:work000a'},
    workshops:[{root:'general-a', is_general:true}],
    nativeWork:{owner:'owner-a', view:'view-a', root:'general-a', scope:'scope-a', state:'idle',
      available_work:['assembly-instance:work000a']}};
  assert.equal(context.nodes(state).map(node => node.id).join(' '), 'node-a assembly-instance:work000a');
  assert.equal(context.select(state, 'general-a'), 'assembly-instance:work000a');
  const [card] = context.items([{body:'claimed assembly-instance:work000a', sender_root:'agent-a'}], context.nodes(state));
  assert.equal(card.title, 'Website lane');
  delete state.topology.canvas.hidden_work;
  assert.equal(context.select(state, 'general-a'), '');
});

test('selecting hidden Work for review goes through the existing gesture', async () => {
  const ctx = vm.createContext({URLSearchParams, TextEncoder});
  vm.runInContext(adapter, ctx);
  const canvas = selected => ({application_root:'application-a', revision:1, selected,
    authorization:{subject:'owner-a', session:'view-a'}, scope:{current:'scope-a'},
    nodes:[{id:'node-a'}], wires:[], hidden_work:[{id:'work-a', title:'Work A'}],
    interaction_projection:{revision:1, bindings:[]}});
  const posts = [];
  const api = ctx.ArchHubExistingWorkshop.create({
    uuid:() => 'id', pendingStorage:{getItem:() => null, setItem:() => {}},
    get:async () => canvas('node-a'),
    post:async (url, body) => { posts.push({url, body}); return canvas(body.roots[0]); }});
  api.setTopologyCanvas(canvas('node-a'));
  const result = await api.selectTopology('work-a');
  assert.equal(result.selected, 'work-a');
  assert.deepEqual(JSON.parse(JSON.stringify(posts)), [{url:'/api/universal/gesture',
    body:{roots:['work-a'], focus:'work-a', expected_scope:'scope-a'}}]);
  await assert.rejects(api.selectTopology('work-b'), /Choose a node in the current canvas scope/);
});

test('an interaction delta holds the lens scalars when absent and never carries the list', () => {
  const start = runtime.indexOf('  const interactionDeltaMode=');
  const end = runtime.indexOf('\n  function scheduleRedraw(', start);
  assert.ok(start > 0 && end > start);
  const context = vm.createContext({lastProjection:null});
  vm.runInContext(runtime.slice(start, end) + '\nglobalThis.merge = mergeProjectionDelta;', context);
  const base = {revision:4, selected:'work-a', selection:[], selection_hidden:true, hidden_work_count:1,
    hidden_work:[{id:'work-a', title:'Work A'}], nodes:[], wires:[], configuration:{design_system:{}}};
  const delta = extra => ({projection_mode:'interaction-delta-v1', base_revision:4, revision:5, selected:'node-a',
    selection:['node-a'], control_state:{controls:[]}, configuration_state:{}, node_count:0, wire_count:0,
    node_states:[], wire_states:[], ...extra});
  const held = context.merge(delta({}), base);
  assert.equal(held.selection_hidden, true);
  assert.equal(held.hidden_work_count, 1);
  assert.deepEqual(held.hidden_work, [{id:'work-a', title:'Work A'}]);
  const changed = context.merge(delta({selection_hidden:false, hidden_work_count:2}), base);
  assert.equal(changed.selection_hidden, false);
  assert.equal(changed.hidden_work_count, 2);
  assert.ok(!/'hidden_work'/.test(runtime.slice(runtime.indexOf('const interactionDeltaFields='),
    runtime.indexOf('];', runtime.indexOf('const interactionDeltaFields=')))));
});