/* Assertions compare booleans and strings, never DOM nodes: a failing node diff inspects the whole window.
   Chat lane courts: Chat mode (ChatView, its plain composer, InferenceInspector with the live
   parametric chain), the Chats panel and the model picker overlay, held to the founder design bundle
   (archhub/project/studio-lm.jsx: ChatsPanel 510-576, ChatView 939-1020, InferenceInspector 1023-1080,
   CalmRow 1091-1096, ModelPicker 3145-3208; DECISIONS.md "Disabled controls use a dashed border, never
   alpha"). The whole compiled Studio is mounted in an in-memory DOM over an existing-graph shape: raw
   canvas rows projected by the shipped projectStudioCanvas slice of studio.html, a model catalogue in
   the shape /api/universal/models answers, native-agent discovery rows, and the transport methods the
   installed build exposes. What is drawn comes from those answers or the account record, never a
   design seed. No application, provider, network or graph file is touched. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));
const DOT = '\u00b7', ELLIPSIS = '\u2026';
const port = (owner, name, index, side) => ({id:owner + ':rel-' + index, name, side, mode:'connection',
  connectable:true, read_only:false, editable:false, interface_root:'if-' + owner + '-' + index,
  direction:side === 'source' ? 'output' : 'input', multiple:false, selected:false, context:false});
const wiredCanvas = {nodes:[
  {id:'sketch-a', label:'Sketch Lines', engine:'vision.sketch_lines', x:40, y:60, status:'',
    params:[{label:'engine', value:'vision.sketch_lines'}, {label:'image_path', value:'sample-plan.png', relation:'rel-image', editable:true},
      {label:'threshold', value:80, relation:'rel-threshold', editable:true}],
    ports:[port('sketch-a', 'lines', 0, 'source')]},
  {id:'walls-a', label:'Build Walls', engine:'revit.build_walls', x:360, y:60, status:'',
    params:[{label:'engine', value:'revit.build_walls'}, {label:'height_mm', value:3000, relation:'rel-height', editable:true},
      {label:'level', value:'L03', relation:'rel-level', editable:true}],
    ports:[port('walls-a', 'lines', 0, 'target')]},
], wires:[{id:'wire-a', source:'sketch-a', source_interface:'sketch-a:rel-0', target:'walls-a', target_interface:'walls-a:rel-0', params:[]}]};
const unwiredCanvas = {nodes:[wiredCanvas.nodes[0]], wires:[]};
// The shape nodelang/model_catalogue.live_model_groups answers (tests_replica/test_model_picker_reads_live.py).
const catalogue = {ok:true, count:4, source_errors:{}, groups:[
  {name:'CLOUD ' + DOT + ' subscription', items:[{name:'anthropic/claude-sonnet-5', route:'anthropic/claude-sonnet-5', vendor:'anthropic', tag:'CLOUD', ctx:'200k', cost:'subscription', col:'#cc785c'}]},
  {name:'BYO ' + DOT + ' OpenRouter', items:[
    {name:'DeepSeek R1', route:'deepseek/deepseek-r1', vendor:'deepseek', tag:'BYO', ctx:'131k', cost:'$0.55 / $2.20 per M', col:'#3a6acc'},
    {name:'Llama 3.3 70B', route:'meta-llama/llama-3.3-70b-instruct', vendor:'meta-llama', tag:'BYO', ctx:'131k', cost:'$0.12 / $0.30 per M', col:'#3a6acc'}]},
  {name:'LOCAL ' + DOT + ' this machine', items:[{name:'qwen2.5-coder-7b', route:'lmstudio/qwen2.5-coder-7b', vendor:'LM Studio', tag:'LOCAL', ctx:'', cost:'free ' + DOT + ' local', col:'#3fb950'}]},
]};
const native = {status:'ok', revision:4, readiness:[], rows:[{kind:'native-session', app:'codex', session_id:'native-a',
  title:'Existing session', connected:true, selectable:true}]};

function projected(raw) {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  assert.ok(specs.length > 100 && fn.length > 100, 'the projection is a slice of the shipped studio.html');
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(raw) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio({raw = wiredCanvas, account = {signedIn:true, email:'ana@studio.example', name:'Ana', graphTier:'founder'}} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53913/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const requests = [], agent = [];
  win.fetch = url => {
    url = String(url); requests.push(url);
    const body = url.startsWith('/api/universal/models') ? catalogue : url.startsWith('/api/universal/native-agents') ? native : null;
    return Promise.resolve(body ? {ok:true, status:200, json:async () => body} : {ok:false, status:404, json:async () => ({ok:false})});
  };
  let answer = null;
  win.ARCHHUB_AGENT = (prompt, route, options) => { agent.push([prompt, route, options]); return new Promise(resolve => { answer = resolve; }); };
  win.ARCHHUB_REMEMBER = async () => ({ok:true});
  // studio.html's graph-held composer pick bridge: the save is confirmed with the route it was given.
  win.ARCHHUB_AGENT_SELECT = async model => model;
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  if (account) win.localStorage.setItem('archhub.account.v1', JSON.stringify(account));
  const graph = projected(raw);
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a'};
  let snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', authorization},
    workshops:[{root:'room-a', label:'Wall conversion', is_general:false}],
    applicationUpdate:{state:'idle', current_build:'20260917-court'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const notify = () => listeners.forEach(listener => listener());
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    selectTopology:async id => { snapshot = {...snapshot, topology:{...snapshot.topology, selected:id}}; notify(); },
    refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {},
    watchApplicationUpdate:() => () => {}, refreshApplicationUpdate:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async () => { for (let i = 0; i < 6; i += 1) { await new Promise(resolve => win.setTimeout(resolve, 5)); flush(() => {}); } };
  const buttons = (text, scope = doc) => [...scope.querySelectorAll('button')].filter(button => button.textContent.trim() === text);
  const exact = (text, scope = doc) => [...scope.querySelectorAll('*')].filter(node => node.textContent === text && ![...node.children].some(child => child.textContent === text));
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const type = (input, text) => flush(() => {
    Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set.call(input, text);
    input.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  const reply = () => doc.querySelector('input[aria-label="Ask selection"]');
  const openPicker = async () => {
    const button = doc.querySelector('[data-model-indicator]');
    assert.ok(button, 'the selection-panel scope chip draws the model button');
    flush(() => button.click());
    await settle();
    const search = [...doc.querySelectorAll('input')].find(input => /^Search (models|available models)/.test(input.placeholder || ''));
    assert.ok(search, 'the picker opens with its search field');
    return search;
  };
  return {win, doc, flush, settle, buttons, exact, close, type, reply, requests, agent, openPicker, answer:text => answer(text)};
}

test('Chat with no conversation: the moved selection panel has no system prompt card or generation controls, and one ask field', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    assert.equal(studio.doc.body.textContent.includes('SYSTEM PROMPT'), false, 'the system prompt card moved out of Chat');
    assert.equal(studio.doc.querySelectorAll('section[data-chat-view] input[type="range"]').length, 0,
      'generation controls moved out of ChatView');
    assert.equal(studio.doc.body.textContent.includes('temperature'), false, 'temperature is not in Chat');
    assert.equal(studio.doc.body.textContent.includes('top-p'), false, 'top-p is not in Chat');
    assert.equal(studio.doc.body.textContent.includes('max tokens'), false, 'max tokens is not in Chat');
    assert.equal(studio.doc.body.textContent.includes('Ask for a change on the canvas'), false, 'no old status paragraph under the card');
    for (const seeded of ['312 tok', 'Revit 2025', 'Fargaly']) {
      assert.equal(studio.doc.body.textContent.includes(seeded), false, 'no seeded ' + seeded + ' in Chat');
    }

    const input = studio.reply();
    assert.ok(input, 'the ask field moved into the selection panel');
    assert.ok(studio.doc.querySelector('aside[aria-label="Selection inspector"]').contains(input),
      'the chat input moved into the right selection panel');
    assert.match(input.placeholder, /whole graph|ask about this node|reply in this session/i);
    assert.equal(input.style.fontSize, '13px');
    assert.equal(input.style.fontStyle, 'italic');
  } finally { studio.close(); }
});

test('Selection-panel composer: no model opens the picker; a picked model sends graph-scoped chat', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const input = studio.reply();
    studio.type(input, 'Dimension all walls in active view at 1:50.');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    // Founder 2026-09-23: no model is ever chosen for him. Unrouted, nothing is sent; the picker opens.
    assert.deepEqual(studio.agent, [], 'no model picked: nothing is sent');
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    assert.ok(dialog, 'Send without a model opens the picker');
    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    studio.type(input, 'Dimension all walls in active view at 1:50.');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.equal(JSON.stringify(studio.agent), JSON.stringify([[
      'Dimension all walls in active view at 1:50.',
      'deepseek/deepseek-r1',
      {graph:true, graph_id:'scope-a', request_id:studio.agent[0][2].request_id,
        generation:{temperature:0.7, top_p:0.95, max_tokens:4096}},
    ]]), 'the typed text goes to the agent route with the chosen route and generation defaults');
    const send = studio.doc.querySelector('aside[aria-label="Selection inspector"] button:disabled');
    assert.ok(send && /Waiting|Send/.test(send.textContent), 'Send is disabled while the answer is out');
    studio.answer({answer:'Prepared an editable change on the canvas for review.'});
    await studio.settle();
    assert.equal(!!studio.doc.querySelector('aside[aria-label="Selection inspector"] button:disabled')?.textContent.includes('Waiting'), false,
      'the answer leaves the busy state');
    assert.ok(studio.exact('Prepared an editable change on the canvas for review.').length,
      'the answer is drawn above the moved selection-panel composer');
  } finally { studio.close(); }
});

test('Inspector: empty selection shows the graph as a node with graph properties instead of the old Chat rail chain', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel, 'the right selection inspector is drawn');
    assert.match(panel.textContent, /GRAPH|ArchHub/);
    assert.ok(panel.textContent.indexOf('Chat') < panel.textContent.indexOf('Properties'),
      'empty selection shows graph chat before graph properties');
  } finally { studio.close(); }
  const unwired = await mountStudio({raw:unwiredCanvas});
  try {
    await unwired.settle();
    const panel = unwired.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel && /GRAPH|ArchHub/.test(panel.textContent), 'an unwired canvas still shows the graph inspector');
  } finally { unwired.close(); }
});

test('Chats panel: the design header names New chat, and it still starts a session from Home', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const rail = studio.doc.querySelector('button[title="Chats"]');
    assert.ok(rail, 'the rail offers Chats');
    studio.flush(() => rail.click());
    assert.equal(!!studio.doc.querySelector('button[title="New graph"]'), false, 'no renamed header action');
    const fresh = studio.doc.querySelector('button[title="New chat"]');
    assert.ok(fresh, 'the Chats header draws New chat (design studio-lm.jsx:519)');
    assert.ok(studio.exact('ArchHub').length, 'the projected graph is listed');
    studio.flush(() => fresh.click());
    assert.ok(studio.doc.querySelector('textarea[aria-label="Start a new session"]'), 'New chat opens Home, where a session starts');
  } finally { studio.close(); }
});

test('Model picker: the design header, live groups without prices, then native sessions, Refresh and Clear selection in the same rows', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const search = await studio.openPicker();
    assert.equal(search.placeholder, 'Search models or paste an OpenRouter id' + ELLIPSIS, 'the design search copy (design studio-lm.jsx:3169)');
    const header = search.parentElement;
    assert.deepEqual([...header.children].map(node => node.tagName), ['SPAN', 'INPUT', 'KBD'], 'the header holds search and esc only');
    const dialog = header.parentElement;
    for (const absent of ['LIVE ' + DOT, 'DISCOVERING', '$']) {
      assert.equal(dialog.textContent.includes(absent), false, 'the picker draws no ' + absent);
    }
    const labels = ['CLOUD ' + DOT + ' subscription', 'BYO ' + DOT + ' OpenRouter', 'LOCAL ' + DOT + ' this machine', 'NATIVE AGENT SESSIONS', 'OPTIONS']
      .map(text => studio.exact(text, dialog)[0]);
    labels.forEach((node, index) => assert.ok(node, 'group ' + index + ' is drawn'));
    for (let index = 1; index < labels.length; index += 1) {
      assert.ok(labels[index - 1].compareDocumentPosition(labels[index]) & studio.win.Node.DOCUMENT_POSITION_FOLLOWING,
        'the design model groups come first; what the design has no place for follows them');
    }
    const [row] = studio.exact('DeepSeek R1', dialog);
    assert.equal(row.nextElementSibling.textContent, 'deepseek ' + DOT + ' ctx 131k', 'a row reads vendor and context, no price');
    const [session] = studio.exact('Existing session', dialog);
    const sessionRow = session.closest('button');
    assert.ok(sessionRow && sessionRow.style.display === 'flex' && sessionRow.style.padding === '8px 10px', 'a native session is a design row');
    const modelsBefore = studio.requests.filter(url => url.startsWith('/api/universal/models')).length;
    const [refresh] = studio.exact('Refresh', dialog);
    studio.flush(() => refresh.closest('button').click());
    await studio.settle();
    assert.equal(studio.requests.filter(url => url.startsWith('/api/universal/models')).length, modelsBefore + 1, 'Refresh reads the catalogue again');
    assert.equal(!!dialog.querySelector('[aria-label="Clear this model selection"]'), false, 'nothing is selected, so there is nothing to clear');

    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    assert.equal(!!studio.doc.querySelector('[aria-label="Clear this model selection"]'), false, 'choosing a row closes the picker');
    assert.ok(studio.doc.querySelector('[data-model-indicator]').textContent.includes('deepseek/deepseek-r1'),
      'the selection-panel scope chip reads the chosen model route');
    await studio.openPicker();
    const clear = studio.doc.querySelector('[aria-label="Clear this model selection"]');
    assert.ok(clear && clear.textContent.includes('deepseek/deepseek-r1'), 'Clear selection names the held route');
    studio.flush(() => clear.click());
    await studio.settle();
    assert.ok(studio.exact('Choose a model').length, 'clearing returns the inspector to Choose a model');
  } finally { studio.close(); }
});
