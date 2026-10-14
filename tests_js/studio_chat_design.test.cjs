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
const native = {status:'ok', revision:4, readiness:[], rows:[{kind:'native-agent', app:'codex', session_id:'native-a',
  title:'Codex', connected:true, selectable:true, live_session_count:1, session_count:1,
  children:[{kind:'native-session', app:'codex', session_id:'native-a', title:'Existing session', connected:true, selectable:true}]}]};

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

async function mountStudio({raw = wiredCanvas, account = {signedIn:true, email:'ana@studio.example', name:'Ana', graphTier:'founder'}, reducedMotion = false, beforeRender = null} = {}) {
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
  const mediaListeners = new Set();
  const reducedMedia = {
    matches:!!reducedMotion,
    media:'(prefers-reduced-motion: reduce)',
    addEventListener(type, listener) { if (type === 'change') mediaListeners.add(listener); },
    removeEventListener(type, listener) { if (type === 'change') mediaListeners.delete(listener); },
  };
  win.matchMedia = query => query === '(prefers-reduced-motion: reduce)' ? reducedMedia :
    ({matches:false, addEventListener() {}, removeEventListener() {}});
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
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  if (beforeRender) beforeRender({win, getSnapshot:() => snapshot});
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
  const setReducedMotion = matches => {
    reducedMedia.matches = !!matches;
    for (const listener of [...mediaListeners]) listener({matches:reducedMedia.matches, media:reducedMedia.media});
  };
  return {win, doc, flush, settle, buttons, exact, close, type, reply, requests, agent, openPicker, setReducedMotion, answer:text => answer(text)};
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

// UX-CHAT1 (installed 2111, shots 29/35): the answer landed as a loose line above the chip while the
// Conversation section above still said "No conversation yet". A sent turn is a turn in that section.
test('UX-CHAT1: a sent question and its answer appear as a turn in the Conversation section, not as a loose line', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const input = studio.reply();
    studio.type(input, 'ping');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    studio.type(input, 'ping');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const conversation = () => panel.querySelector('section[aria-label^="Conversation with"]');
    assert.ok(conversation(), 'the graph chat shows its Conversation section');
    assert.ok(conversation().querySelector('[data-chat-turn="question"]')?.textContent.includes('ping'), 'the question shows at once as a turn');
    assert.match(conversation().querySelector('[data-chat-turn="waiting"]')?.textContent || '', /Waiting for/, 'the answer slot says it is waiting');
    assert.doesNotMatch(conversation().textContent, /No conversation yet/, 'no "No conversation yet" above a turn');
    studio.answer({answer:'PONG'});
    await studio.settle();
    const answer = conversation().querySelector('[data-chat-turn="message"]');
    assert.ok(answer && answer.textContent.includes('PONG'), 'the answer is the turn\'s reply inside the Conversation section');
    const composer = input.closest('div').parentElement;
    assert.equal(composer.textContent.includes('PONG'), false, 'no loose answer line above the chip');
    assert.equal(input.value, '', 'the field clears after a delivered answer');
  } finally { studio.close(); }
});

// UX-CHAT1 v2 (Ping P1): turns reconcile with the transcript store by message identity, never by text.
test('UX-CHAT1 v2: identical prompts keep both turns, a saved question keeps its pending reply, readback has no duplicates, and the store survives a re-open', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    // The transcript store the server keeps (rows carry message ids; the agent reply names them).
    const store = [];
    let revision = 1;
    studio.win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node, conversation_root:'graph-chat', revision:++revision,
      has_older:false, next_before:null, rows:store.map(row => ({...row}))});
    const input = studio.reply();
    const send = async text => {
      studio.type(input, text);
      studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
      await studio.settle();
    };
    await send('ping');
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const conversation = () => panel.querySelector('section[aria-label^="Conversation with"]');
    const texts = () => [...conversation().querySelectorAll('div[style*="pre-wrap"]')].map(node => node.textContent);
    const count = text => texts().filter(t => t === text).length;
    const reply = async (q, r, answer) => {
      store.push({id:r, who:'DeepSeek R1', is_me:false, text:answer, time:'', kind:'reply'});
      studio.answer({answer, delivery:{state:'replied', request_id:'x', message_id:q, reply_message_id:r}});
      await studio.settle(); await studio.settle();
    };
    // Turn 1: question saved with the send, answer arrives with its ids, readback replaces the local turn.
    await send('ping');
    store.push({id:'m1', who:'You', is_me:true, text:'ping', time:'', kind:'message'});
    await reply('m1', 'r1', 'PONG');
    assert.deepEqual([count('ping'), count('PONG')], [1, 1], 'reply then readback: one question, one answer, no duplicates');
    // Turn 2: the SAME prompt again. The old "ping" row must not swallow the new turn.
    await send('ping');
    assert.equal(count('ping'), 2, 'an identical prompt keeps both turns');
    assert.ok(conversation().querySelector('[data-chat-turn="waiting"]'), 'the new turn waits for its reply');
    store.push({id:'m2', who:'You', is_me:true, text:'ping', time:'', kind:'message'});
    await reply('m2', 'r2', 'PONG');
    assert.deepEqual([count('ping'), count('PONG')], [2, 2], 'both turns read back once each');
    // Turn 3: the store saves the question with the send (read back before the answer): the pending reply stays.
    studio.type(input, 'ping');
    store.push({id:'m3', who:'You', is_me:true, text:'ping', time:'', kind:'message'});
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle(); await studio.settle();
    assert.equal(count('ping'), 3, 'the saved question shows once (from the store), not twice');
    assert.ok(conversation().querySelector('[data-chat-turn="waiting"]'), 'question saved, answer pending: the pending reply stays');
    await reply('m3', 'r3', 'PONG');
    assert.deepEqual([count('ping'), count('PONG')], [3, 3], 'three turns, each read back once');
    assert.equal(conversation().querySelector('[data-chat-local]'), null, 'no local copy left once the store holds every turn');
    assert.equal(conversation().querySelectorAll('[data-chat-turn="answer"]').length, 3, 'stored answers keep their turn marker (PM gate x)');
    const props = [...panel.querySelectorAll('[role="tab"]')].find(tab => tab.textContent.trim() === 'Properties');
    const chat = () => [...panel.querySelectorAll('[role="tab"]')].find(tab => tab.textContent.trim() === 'Chat');
    // Leave and come back: the answers come from the store, not a component cache.
    assert.ok(props && chat(), 'the graph inspector has Properties and Chat tabs');
    studio.flush(() => props.click()); await studio.settle();
    assert.equal(conversation(), null, 'the Conversation section unmounted (its local turns are gone)');
    studio.flush(() => chat().click()); await studio.settle(); await studio.settle();
    assert.deepEqual([count('ping'), count('PONG')], [3, 3], 'after leaving and returning, the same turns are read from the store');
  } finally { studio.close(); }
});

// UX-CHAT1 v3 (Ping): the ordinary first send. The server returns the reply row's id with the answer
// (tests/test_universal_agent_plain_send.py courts the real handler); the stored answer and the local answer
// must not both render.
test('UX-CHAT1 v3: an ordinary first send reads back one question and one answer', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const store = [];
    let revision = 1;
    studio.win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node, conversation_root:'graph-chat', revision:++revision,
      has_older:false, next_before:null, rows:store.map(row => ({...row}))});
    const input = studio.reply();
    const send = async text => {
      studio.type(input, text);
      studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
      await studio.settle();
    };
    await send('hello');
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const conversation = () => panel.querySelector('section[aria-label^="Conversation with"]');
    const count = text => [...conversation().querySelectorAll('div[style*="pre-wrap"]')].filter(n => n.textContent === text).length;
    await send('hello');
    // The server wrote both rows before it answered (application_server: ordinary admitted delivery).
    store.push({id:'u-1', who:'You', is_me:true, text:'hello', time:'', kind:'message'});
    store.push({id:'a-1', who:'DeepSeek R1', is_me:false, text:'Hi there.', time:'', kind:'reply'});
    studio.answer({answer:'Hi there.', delivery:{state:'replied', request_id:'x', message_id:'u-1', reply_message_id:'a-1'}});
    await studio.settle(); await studio.settle();
    assert.deepEqual([count('hello'), count('Hi there.')], [1, 1], 'one question and one answer after the readback');
    assert.equal(conversation().querySelector('[data-chat-local]'), null, 'the stored turn replaces the local copy');
    assert.equal(conversation().querySelectorAll('[data-chat-turn="question"]').length, 1, 'the stored question is a marked turn');
    assert.equal(conversation().querySelectorAll('[data-chat-turn="answer"]').length, 1, 'the stored answer is a marked turn');
  } finally { studio.close(); }
});

test('UPD2 p9: a provider refusal is a visible error turn and retains the graph-chat text', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const input = studio.reply();
    const send = async () => {
      studio.type(input, 'p9 chat probe');
      studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
      await studio.settle();
    };
    await send();
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    await send();
    assert.equal(studio.agent.length, 1, 'the main graph composer actually dispatched the turn');
    studio.answer({ok:false, error:'p9 fake provider unavailable'});
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const errors = [...panel.querySelectorAll('[data-chat-turn="error"]')];
    assert.ok(errors.some(row => row.textContent.includes('p9 fake provider unavailable')),
      'provider refusal is visible beside the composer as an error turn');
    assert.equal(input.value, 'p9 chat probe', 'the refused text remains for retry');
    assert.equal(!!panel.querySelector('button:disabled')?.textContent.includes('Waiting'), false,
      'the refusal ends the waiting state');
  } finally { studio.close(); }
});

test('UPD2 p9: send from graph Properties reveals Chat and preserves a reply through tab changes', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const input = studio.reply();
    await studio.openPicker();
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const tab = label => [...panel.querySelectorAll('[role="tab"]')].find(row => row.textContent === label);
    studio.flush(() => tab('Properties').click());
    await studio.settle();
    studio.type(input, 'p9 reply while inspecting properties');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.equal(studio.agent.length, 1, 'the main graph composer dispatched the turn from Properties');
    studio.answer({answer:'p9 visible reply'});
    await studio.settle();
    assert.equal(tab('Chat').getAttribute('aria-selected'), 'true', 'Send opens the reply surface');
    assert.ok(studio.exact('p9 visible reply', panel).length, 'the successful reply is a visible turn');
    studio.flush(() => tab('Properties').click());
    await studio.settle();
    studio.flush(() => tab('Chat').click());
    await studio.settle();
    assert.ok(studio.exact('p9 visible reply', panel).length, 'tab changes retain the admitted reply');
  } finally { studio.close(); }
});

test('UPD2 p10 G3: saved empty-selection graph turns survive actual graph reopen and a fresh component mount', async () => {
  // This is the installed existing-workshop topology shape: the raw canvas has
  // scope.current, not root. Durable rows live outside React and are keyed by
  // the graph-as-node identity the server uses, never by a component cache.
  const stored = new Map();
  const reads = [], opens = [], selectionWrites = [];
  // /gesture's primary focus is retained when roots are cleared. Selection,
  // not the old primary, decides whether the inspector targets the graph.
  let savedPrimary = 'sketch-a', savedSelection = [];
  const beforeRender = ({win, getSnapshot}) => {
    getSnapshot().topology.selected = savedPrimary;
    getSnapshot().topology.canvas.selected = savedPrimary;
    getSnapshot().topology.canvas.selection = [...savedSelection];
    const select = win.ARCHHUB_EXISTING_WORKSHOP.selectTopology;
    win.ARCHHUB_EXISTING_WORKSHOP.selectTopology = async (id, roots) => {
      const requested = Array.isArray(roots) ? Array.from(roots) : id ? [id] : [];
      selectionWrites.push({id, roots:requested});
      if (id) savedPrimary = id;
      savedSelection = requested;
      getSnapshot().topology.canvas.selected = savedPrimary;
      getSnapshot().topology.canvas.selection = [...savedSelection];
      // Publish through the original owner callback, preserving its listeners.
      return select(savedPrimary);
    };
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node, scope) => {
      reads.push({node, scope});
      const current = getSnapshot().topology.canvas.scope.current;
      if (scope !== current || node !== 'graph:' + current) {
        return {ok:false, error:'That graph is not the current canvas'};
      }
      return {ok:true, node, conversation_root:'durable-graph-conversation:' + current,
        revision:7, has_older:false, next_before:null,
        rows:(stored.get(current) || []).map(row => ({...row}))};
    };
    win.ARCHHUB_GRAPH_OPEN = async root => {
      opens.push(root);
      return {ok:true, current_graph:root, graphs:[{id:root, title:'ArchHub', state:'idle', file:'Graph composition'}]};
    };
  };
  let studio = await mountStudio({beforeRender});
  try {
    await studio.settle();
    assert.ok(reads.length, 'the initial graph panel reads the durable transcript');
    assert.deepEqual(reads[0], {node:'graph:scope-a', scope:'scope-a'}, 'the read names the current graph identity and scope');
    await studio.openPicker();
    const picker = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    studio.flush(() => studio.exact('DeepSeek R1', picker)[0].closest('[style]').parentElement.click());
    await studio.settle();
    const input = studio.reply();
    studio.type(input, 'p10 saved graph message');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.equal(studio.agent.length, 1, 'the empty-selection panel sends exactly one turn');
    assert.equal(studio.agent[0][2].graph, true);
    assert.equal(studio.agent[0][2].graph_id, 'scope-a', 'send and transcript target the same graph root');
    stored.set('scope-a', [
      {id:'p10-graph-question', who:'You', is_me:true, text:'p10 saved graph message', time:'', kind:'message'},
      {id:'p10-graph-answer', who:'DeepSeek R1', is_me:false, text:'p10 durable graph answer', time:'', kind:'reply'},
    ]);
    // Simulate the save receipt after the durable store has committed both rows.
    studio.answer({answer:'p10 durable graph answer', delivery:{state:'replied',
      message_id:'p10-graph-question', reply_message_id:'p10-graph-answer'}});
    await studio.settle(); await studio.settle();
    const assertStoredTurn = () => {
      const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
      assert.ok(panel, 'empty selection opens the graph panel');
      assert.equal(panel.querySelector('[data-chat-local]'), null, 'every visible row comes from durable transcript readback');
      assert.equal(studio.exact('p10 saved graph message', panel).length, 1, 'saved graph question renders once');
      assert.equal(studio.exact('p10 durable graph answer', panel).length, 1, 'saved graph answer renders once');
      assert.equal(panel.querySelectorAll('[data-chat-turn="question"]').length, 1, 'question turn marker survives reopen');
      assert.equal(panel.querySelectorAll('[data-chat-turn="answer"]').length, 1, 'p9 x answer turn marker survives reopen');
    };
    assertStoredTurn();
    studio.flush(() => studio.doc.querySelector('button[title="Chats"]').click());
    const home = studio.doc.querySelector('button[aria-label="Home"]');
    assert.ok(home, 'Chats offers Home to leave the current graph');
    studio.flush(() => home.click()); await studio.settle();
    assert.equal(studio.doc.querySelector('aside[aria-label="Selection inspector"]'), null, 'Home unmounts the graph panel and all local turns');
    const row = studio.exact('ArchHub').map(node => node.closest('button')).find(Boolean);
    assert.ok(row, 'the saved graph remains in the Chats list');
    studio.flush(() => row.click()); await studio.settle(); await studio.settle();
    assert.deepEqual(opens, ['graph-a'], 'reopen uses the graph-open owner callback once');
    assertStoredTurn();
    // PM's reopened graph had been reselected. Exercise node -> empty graph
    // selection as well: the inspector must reread the graph history after the
    // node's conversation component has replaced its old graph component.
    const card = studio.doc.querySelector('.lm-node[data-node-id="sketch-a"]');
    assert.ok(card, 'the reopened canvas has an ordinary node to reselect');
    studio.flush(() => card.dispatchEvent(new studio.win.MouseEvent('click', {bubbles:true, cancelable:true})));
    await studio.settle();
    assert.match(studio.doc.querySelector('aside[aria-label="Selection inspector"]').textContent, /Sketch Lines/, 'reselection actually switches the inspector to the node');
    const canvas = studio.doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
    studio.flush(() => canvas.dispatchEvent(new studio.win.MouseEvent('mousedown', {button:0, bubbles:true, cancelable:true})));
    studio.flush(() => studio.win.dispatchEvent(new studio.win.MouseEvent('mouseup', {button:0, bubbles:true})));
    await studio.settle(); await studio.settle();
    assert.ok(selectionWrites.some(write => write.id === null && write.roots.length === 0),
      'clearing the canvas sends an explicit empty selection through the owner');
    assert.equal(savedPrimary, 'sketch-a', 'the server retains the selected node as primary focus');
    assert.deepEqual(savedSelection, [], 'the server durably holds an explicit empty selection');
    assert.equal(studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.selected, 'sketch-a',
      'the mounted inspector receives the retained primary and must still draw the graph');
    assertStoredTurn();
    assert.equal(studio.agent.length, 1, 'reopening or reselection never resends the saved message');
    const readCount = reads.length;
    studio.close();
    studio = await mountStudio({beforeRender});
    await studio.settle(); await studio.settle();
    assert.ok(reads.length > readCount, 'a fresh Studio mount rereads the durable graph transcript');
    const restored = studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology;
    assert.equal(restored.selected, 'sketch-a', 'fresh mount restores the retained primary from the server');
    assert.deepEqual(Array.from(restored.canvas.selection), [], 'fresh mount restores the durable empty selection');
    assertStoredTurn();
    assert.equal(studio.agent.length, 0, 'fresh mount reads history without any send');
    assert.ok(reads.every(read => read.node === 'graph:scope-a' && read.scope === 'scope-a'), 'every reopened read preserves the graph root identity');
  } finally { studio.close(); }
});

for (const gesture of ['empty canvas click', 'Esc']) {
  test(`UPD2 p11 G3: wire -> reopen -> ${gesture} restores GRAPH and its saved message`, async () => {
    let primary = 'wire-a', selection = [];
    const writes = [], opens = [], reads = [];
    const beforeRender = ({win, getSnapshot}) => {
      const canvas = getSnapshot().topology.canvas;
      canvas.selected = primary; canvas.selection = [...selection];
      getSnapshot().topology.selected = primary;
      const publish = win.ARCHHUB_EXISTING_WORKSHOP.selectTopology;
      win.ARCHHUB_EXISTING_WORKSHOP.selectTopology = async (id, roots) => {
        selection = Array.isArray(roots) ? Array.from(roots) : id ? [id] : [];
        writes.push({id, roots:[...selection]});
        if (id) primary = id; // The real owner retains primary after an explicit clear.
        canvas.selected = primary; canvas.selection = [...selection];
        return publish(primary);
      };
      win.ARCHHUB_EXISTING_WORKSHOP.refreshTopologyCanvas = async () => publish(primary);
      win.ARCHHUB_GRAPH_OPEN = async id => {
        opens.push(id);
        return {ok:true, current_graph:id, graphs:[{id, title:'ArchHub', state:'idle', file:'Graph composition'}]};
      };
      win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node, scope) => {
        reads.push({node, scope});
        return {ok:true, node, conversation_root:'saved:' + node, has_older:false,
          rows:node === 'graph:scope-a' ? [{id:'p11-saved', who:'You', is_me:true,
            text:'p11 saved graph message', kind:'message'}] : []};
      };
    };
    let studio = await mountStudio({beforeRender});
    const panel = () => studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const assertGraph = (expectedPrimary = 'wire-a') => {
      assert.equal(studio.exact('GRAPH', panel()).length, 1, 'the inspector targets GRAPH');
      assert.equal(studio.exact('p11 saved graph message', panel()).length, 1, 'saved graph history is visible');
      assert.equal(panel().querySelector('[data-chat-local]'), null, 'history is owner readback');
      assert.deepEqual(selection, [], 'the owner holds an empty selection');
      assert.equal(primary, expectedPrimary, 'retained primary cannot override empty selection');
      assert.equal(studio.agent.length, 0, 'history readback sends no message');
    };
    const selectWire = async () => {
      const wire = studio.doc.querySelector('[data-wire-id="wire-a"]');
      assert.ok(wire, 'the actual wire hit target is mounted');
      studio.flush(() => wire.dispatchEvent(new studio.win.MouseEvent('click', {bubbles:true, cancelable:true})));
      await studio.settle();
      assert.match(panel().textContent, /CONNECTION/, 'explicit wire reselection still opens CONNECTION');
      assert.deepEqual(selection, ['wire-a'], 'explicit reselection reaches the owner');
    };
    const clear = async (expectedPrimary = 'wire-a') => {
      const canvas = studio.doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
      assert.ok(canvas, 'the reopened canvas is mounted');
      const before = writes.length;
      if (gesture === 'Esc') {
        studio.flush(() => canvas.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true})));
      } else {
        studio.flush(() => canvas.dispatchEvent(new studio.win.MouseEvent('mousedown', {button:0, bubbles:true, cancelable:true})));
        studio.flush(() => studio.win.dispatchEvent(new studio.win.MouseEvent('mouseup', {button:0, bubbles:true})));
        studio.flush(() => canvas.dispatchEvent(new studio.win.MouseEvent('click', {button:0, bubbles:true, cancelable:true})));
      }
      await studio.settle(); await studio.settle();
      assert.equal(writes.length, before + 1, 'the clear posts exactly once');
      assert.deepEqual(writes.at(-1), {id:null, roots:[]}, 'the gesture explicitly clears the owner selection');
      assertGraph(expectedPrimary);
    };
    try {
      await studio.settle();
      assertGraph(); // Fresh restore of an empty selection with retained WIRE primary.
      await selectWire();
      studio.flush(() => studio.doc.querySelector('button[title="Chats"]').click());
      studio.flush(() => studio.doc.querySelector('button[aria-label="Home"]').click());
      await studio.settle();
      assert.equal(panel(), null, 'Home unmounts the inspector');
      const row = studio.exact('ArchHub').map(node => node.closest('button')).find(Boolean);
      assert.ok(row, 'the saved graph can be reopened');
      studio.flush(() => row.click());
      await studio.settle(); await studio.settle();
      assert.deepEqual(opens, ['graph-a'], 'the graph is actually reopened through its owner');
      assertGraph(); // The retained nonempty relation selection is cleared on reopen.
      await clear();
      await selectWire(); // Explicit reselection after reopen must remain available.
      await clear(); // Clear the wire, not just the already-empty reopened canvas.
      const card = studio.doc.querySelector('.lm-node[data-node-id="sketch-a"]');
      studio.flush(() => card.dispatchEvent(new studio.win.MouseEvent('click', {bubbles:true, cancelable:true})));
      await studio.settle();
      assert.match(panel().textContent, /Sketch Lines/, 'ordinary node selection still opens its inspector');
      await clear('sketch-a');
      await selectWire();
      await clear();
      const beforeMount = reads.length;
      studio.close();
      studio = await mountStudio({beforeRender});
      await studio.settle(); await studio.settle();
      assertGraph();
      assert.ok(reads.length > beforeMount, 'a fresh mount rereads the saved graph message');
      selection = ['wire-a']; // Simulate closing the app while the relation was selected.
      studio.close();
      const beforeRestore = writes.length;
      studio = await mountStudio({beforeRender});
      await studio.settle(); await studio.settle();
      assertGraph();
      assert.deepEqual(writes.slice(beforeRestore), [{id:null, roots:[]}],
        'fresh mount clears a persisted nonempty relation selection through the owner');
      await selectWire();
      await clear();
    } finally { studio.close(); }
  });
}

test('UPD2 p10 G3: a mixed projection reads saved graph history using scope.current before application root, including a fresh reopen', async () => {
  // Canonical raw topology has no root. This separate supported-shape regression
  // holds both identities so graphInspectorNode's scope.current target cannot
  // be paired with a transcript read authorized against a different root.
  const stored = [
    {id:'mixed-question', who:'You', is_me:true, text:'Saved graph question', kind:'message'},
    {id:'mixed-answer', who:'DeepSeek R1', is_me:false, text:'Saved graph answer', kind:'reply'},
  ];
  const reads = [];
  const beforeRender = ({win, getSnapshot}) => {
    getSnapshot().topology.canvas.root = 'application-root';
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async (node, scope) => {
      reads.push({node, scope});
      if (node !== 'graph:scope-a' || scope !== 'scope-a') {
        return {ok:false, error:'Canvas scope changed; refresh the canvas'};
      }
      return {ok:true, node, conversation_root:'durable-scope-a', has_older:false,
        rows:stored.map(row => ({...row}))};
    };
  };
  let studio = await mountStudio({beforeRender});
  const assertStored = () => {
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel, 'the empty-selection graph inspector mounts');
    assert.equal(panel.querySelector('[role="alert"]'), null, 'matching scope.current authorizes the transcript');
    assert.equal(panel.querySelector('[data-chat-local]'), null, 'history came from the durable transcript only');
    assert.equal(studio.exact('Saved graph question', panel).length, 1, 'the saved graph question renders');
    assert.equal(studio.exact('Saved graph answer', panel).length, 1, 'the saved graph answer renders');
    assert.equal(panel.querySelectorAll('[data-chat-turn="answer"]').length, 1, 'the p9 answer marker remains intact');
    assert.equal(studio.agent.length, 0, 'reading saved history never sends a turn');
  };
  try {
    await studio.settle();
    assertStored();
    assert.ok(reads.length, 'the first mount reads the transcript');
    const beforeReopen = reads.length;
    studio.close();
    studio = await mountStudio({beforeRender});
    await studio.settle();
    assertStored();
    assert.ok(reads.length > beforeReopen, 'a fresh reopen rereads the durable history');
    assert.ok(reads.every(read => read.node === 'graph:scope-a' && read.scope === 'scope-a'),
      'both mounts use the scope.current graph identity despite a different application root');
  } finally { studio.close(); }
});

test('UPD2 p10 G3: transcript identity refusal is visible and never leaves another graph history or an endless reading state', async () => {
  const studio = await mountStudio({beforeRender:({win}) => {
    win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node:'graph:other-scope',
      conversation_root:'other-history', rows:[{id:'foreign', who:'You', is_me:true,
        text:'Foreign graph message', kind:'message'}], has_older:false});
  }});
  try {
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const alert = panel.querySelector('[role="alert"]');
    assert.ok(alert, 'a mismatched graph transcript gives a visible refusal');
    assert.match(alert.textContent, /changed|match|another|refus|refresh/i, 'the refusal explains the wrong transcript binding');
    assert.doesNotMatch(panel.textContent, /Foreign graph message/, 'another graph history is never rendered');
    assert.doesNotMatch(panel.textContent, /Reading the conversation/, 'a refused read cannot remain pending forever');
  } finally { studio.close(); }
});

test('UPD2 p9: a live model node without model in its summary still shows its accepted first reply', async () => {
  // The server resolves model from the complete property lens, not this
  // four-row canvas summary (agent_composer._resolve_node_model_route).
  const raw = {nodes:[{id:'think-a', label:'Think', engine:'library.think', x:40, y:60,
    params:[{label:'engine', value:'library.think'}, {label:'prompt', value:'summarize'}], ports:[]}], wires:[]};
  const studio = await mountStudio({raw});
  try {
    await studio.settle();
    await studio.openPicker();
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click());
    await studio.settle();
    const card = studio.doc.querySelector('.lm-node[data-node-id="think-a"]');
    studio.flush(() => card.dispatchEvent(new studio.win.MouseEvent('click', {bubbles:true, cancelable:true})));
    await studio.settle();
    const input = studio.reply();
    studio.type(input, 'p9 first node reply');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.equal(studio.agent.length, 1, 'the selected live node dispatched the turn');
    assert.equal(studio.agent[0][2].node, 'think-a', 'the accepted turn belongs to the selected node');
    studio.answer({answer:'p9 visible first node reply', delivery:{state:'replied'}});
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(studio.exact('p9 visible first node reply', panel).length,
      'an accepted first reply renders before a conversation binding appears in the canvas');
    assert.equal([...panel.querySelectorAll('[role="tab"]')].find(row => row.textContent === 'Chat')?.getAttribute('aria-selected'),
      'true', 'the successful node send reveals Chat');
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

test('Model picker: the design header, live groups without prices, then native agents, Refresh and Clear selection in the same rows', async () => {
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
    const labels = ['CLOUD ' + DOT + ' subscription', 'BYO ' + DOT + ' OpenRouter', 'LOCAL ' + DOT + ' this machine', 'NATIVE AGENTS', 'OPTIONS']
      .map(text => studio.exact(text, dialog)[0]);
    labels.forEach((node, index) => assert.ok(node, 'group ' + index + ' is drawn'));
    for (let index = 1; index < labels.length; index += 1) {
      assert.ok(labels[index - 1].compareDocumentPosition(labels[index]) & studio.win.Node.DOCUMENT_POSITION_FOLLOWING,
        'the design model groups come first; what the design has no place for follows them');
    }
    const [row] = studio.exact('DeepSeek R1', dialog);
    assert.equal(row.nextElementSibling.textContent, 'deepseek ' + DOT + ' ctx 131k', 'a row reads vendor and context, no price');
    const [session] = studio.exact('Codex', dialog);
    const sessionRow = session.closest('button');
    assert.ok(sessionRow && sessionRow.style.display === 'flex' && sessionRow.style.padding === '8px 12px', 'a native agent is a tokenized design row');
    assert.match(sessionRow.textContent, /Selectable · 1 live session/, 'the native row label names selectable sessions, not idle state');
    assert.equal(sessionRow.textContent.includes('Idle ·'), false, 'selectable discovery is not labelled idle');
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

test('Theme update redraws focused node outline from the live accent', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const card = studio.doc.querySelector('.lm-node[data-node-id="sketch-a"]');
    assert.ok(card, 'a canvas node is mounted');
    studio.flush(() => card.dispatchEvent(new studio.win.MouseEvent('click', {bubbles:true, cancelable:true})));
    await studio.settle();
    assert.equal(studio.doc.querySelector('.lm-node[data-focused="true"]')?.getAttribute('data-node-id'), 'sketch-a',
      'the rendered node is focused before testing outline colour');
    const next = Object.fromEntries(studio.win.ArchHubTheme.keys.map(key => [key, seed[key]]));
    next.accent = '#55aaee';
    studio.flush(() => studio.win.ArchHubTheme.apply(next));
    await studio.settle();
    const updated = studio.doc.querySelector('.lm-node[data-node-id="sketch-a"]');
    assert.equal(studio.win.getComputedStyle(updated).outlineColor, 'rgb(85, 170, 238)',
      'the focused node outline follows the updated accent');
  } finally { studio.close(); }
});

test('Reduced-motion preference zeroes transitions and live changes redraw', async () => {
  const studio = await mountStudio({reducedMotion:true});
  try {
    await studio.settle();
    const card = studio.doc.querySelector('.lm-node[data-node-id="sketch-a"]');
    assert.ok(card, 'a canvas node is mounted');
    assert.doesNotMatch(card.style.transition, /[1-9]\d*ms/, 'reduced motion starts with zero transition durations');
    studio.flush(() => studio.setReducedMotion(false));
    await studio.settle();
    assert.match(card.style.transition, /120ms/, 'leaving reduced motion restores token durations');
    studio.flush(() => studio.setReducedMotion(true));
    await studio.settle();
    assert.doesNotMatch(card.style.transition, /[1-9]\d*ms/, 'returning to reduced motion redraws zero durations');
  } finally { studio.close(); }
});

// PM gate 2026-10-13: after several sends the newest answer must be on screen (pin to bottom),
// unless the user scrolled up to read history.
test('UX-CHAT1 v3b: a new turn scrolls the conversation to the newest answer unless the user scrolled up', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    const store = [];
    studio.win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node, conversation_root:'graph-chat', revision:store.length + 1,
      has_older:false, next_before:null, rows:store.map(row => ({...row}))});
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const box = () => panel.querySelector('[data-chat-scroll]');
    const input = studio.reply();
    const send = async text => {
      studio.type(input, text);
      studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
      await studio.settle();
    };
    await send('hello');
    const dialog = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    if (dialog) { studio.flush(() => studio.exact('DeepSeek R1', dialog)[0].closest('[style]').parentElement.click()); await studio.settle(); }
    const el = box();
    assert.ok(el, 'the conversation has its scroll box');
    // JSDOM has no layout: give the scroll box a real geometry so pinning is observable.
    let top = 0;
    Object.defineProperty(el, 'clientHeight', {configurable:true, get: () => 100});
    Object.defineProperty(el, 'scrollHeight', {configurable:true, get: () => 100 + store.length * 60});
    Object.defineProperty(el, 'scrollTop', {configurable:true, get: () => top, set: v => { top = v; }});
    for (let i = 1; i <= 5; i += 1) {
      await send('ping ' + i);
      store.push({id:'u-' + i, who:'You', is_me:true, text:'ping ' + i, time:'', kind:'message'});
      store.push({id:'a-' + i, who:'DeepSeek R1', is_me:false, text:'PONG' + i, time:'', kind:'reply'});
      studio.answer({answer:'PONG' + i, delivery:{state:'replied', request_id:'r' + i, message_id:'u-' + i, reply_message_id:'a-' + i}});
      await studio.settle(); await studio.settle();
    }
    assert.equal(panel.querySelectorAll('[data-chat-turn="answer"]').length, 5, 'five stored answers are marked turns');
    assert.equal(top, el.scrollHeight, 'pinned to the newest answer after each turn');
    top = 0;
    studio.flush(() => el.dispatchEvent(new studio.win.Event('scroll')));
    await send('ping 6');
    store.push({id:'u-6', who:'You', is_me:true, text:'ping 6', time:'', kind:'message'});
    store.push({id:'a-6', who:'DeepSeek R1', is_me:false, text:'PONG6', time:'', kind:'reply'});
    studio.answer({answer:'PONG6', delivery:{state:'replied', request_id:'r6', message_id:'u-6', reply_message_id:'a-6'}});
    await studio.settle(); await studio.settle();
    assert.equal(top, 0, 'a reader who scrolled up keeps their place');
  } finally { studio.close(); }
});
