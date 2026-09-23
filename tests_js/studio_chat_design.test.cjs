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
  win.ARCHHUB_AGENT = (prompt, route) => { agent.push([prompt, route]); return new Promise(resolve => { answer = resolve; }); };
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
  const reply = () => [...doc.querySelectorAll('input')].find(input => (input.placeholder || '') === 'Reply, or ask for another step' + ELLIPSIS);
  const openPicker = async () => {
    const [label] = exact('MODEL');
    assert.ok(label && label.nextElementSibling, 'the inspector draws its MODEL button');
    flush(() => label.nextElementSibling.click());
    await settle();
    const search = [...doc.querySelectorAll('input')].find(input => /^Search (models|available models)/.test(input.placeholder || ''));
    assert.ok(search, 'the picker opens with its search field');
    return search;
  };
  return {win, doc, flush, settle, buttons, exact, close, type, reply, requests, agent, openPicker, answer:text => answer(text)};
}

test('Chat with no conversation: the design column holds the system prompt card and nothing else, and the reply field is the design line', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const [label] = studio.exact('SYSTEM PROMPT');
    assert.ok(label, 'the system prompt card is drawn');
    const card = label.parentElement.parentElement;
    assert.equal(card.parentElement.children.length, 1,
      'no turns: the column holds the card only, as the design draws an empty conversation (design studio-lm.jsx:947-990)');
    assert.equal(studio.doc.body.textContent.includes('Ask for a change on the canvas'), false, 'no old status paragraph under the card');
    const [edit] = studio.buttons('edit', label.parentElement);
    assert.ok(edit, 'the header keeps the design edit affordance (design studio-lm.jsx:960)');
    assert.equal(edit.disabled, true, 'nothing edits the system prompt in this build, so edit is disabled');
    assert.match(edit.title || '', /not available/i, 'edit says why');
    assert.equal(edit.style.borderBottomStyle, 'dashed', 'disabled with a dashed line');
    assert.equal(edit.style.opacity, '', 'disabled without alpha');
    for (const seeded of ['312 tok', 'Revit 2025', 'Fargaly']) {
      assert.equal(studio.doc.body.textContent.includes(seeded), false, 'no seeded ' + seeded + ' in Chat');
    }

    const input = studio.reply();
    assert.ok(input, 'the reply field carries the design prompt as its placeholder');
    assert.equal(input.style.display, 'block', 'the field is a block line like the design prompt, no inline strut');
    assert.equal(input.style.fontSize, '17px');
    assert.equal(input.style.fontStyle, 'italic');
    assert.equal(input.style.lineHeight, '1.5', 'the field holds the design line height');
    assert.equal(input.style.padding, '2px 0px 8px');
    assert.ok(input.classList.contains('lm-chat-draft'), 'the field is styled by its placeholder rule');
    const rule = [...studio.doc.querySelectorAll('style')].map(node => node.textContent).find(text => text.includes('.lm-chat-draft::placeholder'));
    assert.ok(rule && rule.includes(studio.win.AH.inkMuted) && /opacity:\s*1/.test(rule), 'the placeholder is drawn in inkMuted, as the design prompt is');

    const row = input.nextElementSibling;
    assert.deepEqual([...row.children].map(node => node.textContent.trim()).slice(0, 4),
      ['@ skill', '\uff0b sketch', '\u25c6 workshop', '\u2317 open as nodes'], 'the design chips in the design order');
    assert.equal([...row.children].some(node => node.tagName === 'DIV' && !node.textContent), false,
      'the model label is the flexible part of the row, so a long live route cannot wrap the chips');
    const route = row.children[4];
    assert.equal(route.style.minWidth, '0px', 'the model label can shrink');
    assert.equal(route.style.textOverflow, 'ellipsis', 'and ellipsizes instead');
    assert.equal(route.style.textAlign, 'right', 'it still sits against Send');
  } finally { studio.close(); }
});

test('Chat with a conversation: Send asks the agent route, turns carry the account and the answerer, and a busy Send is dashed without alpha', async () => {
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
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.deepEqual(studio.agent, [['Dimension all walls in active view at 1:50.', 'deepseek/deepseek-r1']], 'the typed text goes to the agent route with the chosen route');
    const [send] = studio.buttons('Send \u21b5');
    assert.ok(send && send.disabled, 'Send is disabled while the answer is out');
    assert.equal(send.style.opacity, '', 'disabled without alpha');
    assert.equal(send.style.borderStyle, 'dashed', 'disabled with a dashed border');
    assert.equal(send.style.backgroundColor, 'transparent', 'not drawn as a filled primary while disabled');
    studio.answer('Prepared an editable change on the canvas for review.');
    await studio.settle();
    assert.equal(send.disabled, false, 'the answer re-enables Send');
    assert.notEqual(send.style.borderStyle, 'dashed', 'and it returns to the design primary');
    const names = studio.exact('Ana').filter(node => node.tagName === 'SPAN');
    assert.ok(names.length >= 1, 'the question is signed with the account name');
    assert.ok(studio.exact('DeepSeek R1').some(node => node.tagName === 'SPAN' && node.nextElementSibling),
      'the answer is signed by the chosen model');
    assert.ok(studio.exact('Prepared an editable change on the canvas for review.').length, 'the answer is drawn as a turn');
  } finally { studio.close(); }
});

test('Inspector: the parametric chain is the design stage track with CalmRows, and an unwired canvas is simply 0 stages', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const [title] = studio.exact('PARAMETRIC CHAIN ' + DOT + ' 2 STAGES');
    assert.ok(title, 'two wired nodes are two stages');
    const section = title.parentElement;
    assert.equal([...section.querySelectorAll('*')].some(node => /^\d+ \u00b7 /.test(node.textContent) && !node.children.length), false,
      'no per-node title lines: the design draws the track and its rows only (design studio-lm.jsx:1054-1065)');
    assert.equal([...section.querySelectorAll('div')].some(node => node.style.borderBottomStyle === 'dashed'), false, 'no dashed leader rows');
    for (const [k, v] of [['image_path', 'sample-plan.png'], ['threshold', '80'], ['height_mm', '3000'], ['level', 'L03']]) {
      const [key] = studio.exact(k, section);
      assert.ok(key, 'the chain draws ' + k);
      assert.equal(key.style.flexGrow, '1', k + ' is a CalmRow key (design studio-lm.jsx:1091-1096)');
      assert.equal(key.nextElementSibling && key.nextElementSibling.textContent, v, k + ' shows its projected value');
    }
  } finally { studio.close(); }
  const unwired = await mountStudio({raw:unwiredCanvas});
  try {
    await unwired.settle();
    assert.ok(unwired.exact('PARAMETRIC CHAIN ' + DOT + ' 0 STAGES').length, 'an unwired canvas is 0 stages');
    assert.equal(unwired.doc.body.textContent.includes('No wired nodes on this canvas yet.'), false, 'the count says it; no extra status line');
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
    assert.ok(studio.exact('DeepSeek R1').length, 'the inspector reads the chosen model');
    await studio.openPicker();
    const clear = studio.doc.querySelector('[aria-label="Clear this model selection"]');
    assert.ok(clear && clear.textContent.includes('deepseek/deepseek-r1'), 'Clear selection names the held route');
    studio.flush(() => clear.click());
    await studio.settle();
    assert.ok(studio.exact('Choose a model').length, 'clearing returns the inspector to Choose a model');
  } finally { studio.close(); }
});