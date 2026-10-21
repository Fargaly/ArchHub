/* Court (fresh machine, 2026-09-28): with no usable model route the Studio is never silent.
   Chat shows one explicit "No model" state with both ways out (sign in to the ArchHub cloud,
   choose a model), and the Brain line on the boot screen says the same instead of
   "connecting". The state is the server's readiness answer on /api/universal/models.
   Only the model listing is answered; no application, provider, network or graph file. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

const vm = require('node:vm');
// The shipped studio.html canvas projection, so a node on the canvas is the node the Studio draws.
function projected(raw) {
  const html = read('01.APP/nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(raw) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio({models, signin, select, raw, selected = null, home = false, authority, hub} = {}) {
  const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-account.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, '01.APP/nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, 'Studio build is stale for ' + source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  // models may be a function: each listing read gets the answer it returns (count from 1).
  let reads = 0;
  win.fetch = url => String(url).includes('/api/universal/models') && models
    ? (reads += 1, Promise.resolve({ok:true, json:() => Promise.resolve(typeof models === 'function' ? models(reads) : models)}))
    : new Promise(() => {});
  if (signin) win.ARCHHUB_CLOUD_SIGNIN = signin;
  if (select) win.ARCHHUB_AGENT_SELECT = select;
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = raw ? projected(raw) : {nodes:[], wires:[]};
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization}, workshops:[],
    applicationUpdate:{state:'idle', current_build:'20260928-r1'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected}};
  const owner = {getSnapshot:() => snapshot, subscribe:() => () => {}, watchApplicationUpdate:() => () => {}};
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner, {get:(target, key) => key in target || typeof key !== 'string' ||
    key === 'then' ? target[key] : () => new Promise(() => {})});
  if (authority) win.ARCHHUB_STUDIO_AUTHORITY = authority;
  if (hub) win.ARCHHUB_TOOL_HUB = hub;
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  if (!home) win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  win.addEventListener('archhub-home-ready', () => {
    win.__homeReadyHasDOM = !!win.document.querySelector('[data-home-page]');
  });
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('01.APP/nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {doc, win, flush, close};
}
const settle = win => new Promise(resolve => win.setTimeout(resolve, 60));
const buttonIn = (node, label) => [...node.querySelectorAll('button')].find(b => b.textContent.trim() === label);
const homeText = doc => doc.querySelector('[data-home-page]')?.textContent || '';
// The server's copy (model_router.composer_readiness); the Studio shows it as it stands.
const COPY = {
  no_model:'No model yet. Sign in to ArchHub, or choose a model.',
  invalid:'ArchHub cannot reach this model. Choose another model.',
  openrouter:'This model needs an OpenRouter key. Sign in to ArchHub, or add your own AI key in Settings \u2192 Providers.',
  cloud:'This model runs on the ArchHub cloud. Sign in to use it.',
};
const fam = (openrouter = 'no_key', cloud = 'no_key') => ({
  openrouter:{state:openrouter, message:openrouter === 'ready' ? '' : COPY.openrouter, actions:['sign_in', 'choose_model']},
  cloud:{state:cloud, message:cloud === 'ready' ? '' : COPY.cloud, actions:['sign_in', 'choose_model']},
  lmstudio:{state:'ready', message:'', actions:[]}, ollama:{state:'ready', message:'', actions:[]}});
const answer = (state, route, families) => ({state, route, actions:state === 'ready' ? [] : ['sign_in', 'choose_model'],
  message:state === 'ready' ? '' : state === 'no_model' ? COPY.no_model : state === 'invalid' ? COPY.invalid
    : route.startsWith('cloud/') ? COPY.cloud : COPY.openrouter,
  families, messages:{no_model:COPY.no_model, invalid:COPY.invalid}});
const NO_MODEL = answer('no_model', '', fam());
const JARGON = /OPENROUTER_API_KEY|ARCHHUB_CLOUD_TOKEN|secrets store/;
const click = (studio, node) => studio.flush(() => node.dispatchEvent(new studio.win.MouseEvent('click', {bubbles:true})));

test('BOOT2 Home accepts clicks while graph warm-up remains pending', async () => {
  let loads = 0;
  const snapshot = {canvas:{projection:'home', graph_id:'graph-a', root:'scope-a', revision:7,
    authorization:{subject:'owner-a',session:'view-a'}, scope:{current:'scope-a'}, nodes:[],
    warmup:{state:'almost_ready'}}, graph:{nodes:[],wires:[]}, library:[], workshops:[]};
  const authority = {getSnapshot:() => snapshot, subscribe:() => () => {},
    load:() => {loads += 1; return new Promise(() => {});}};
  const studio = await mountStudio({home:true, authority,
    models:{ok:true, groups:[], selected_route:'', default_route:'', readiness:NO_MODEL}});
  try {
    await settle(studio.win);
    assert.ok(studio.doc.querySelector('[data-home-page]'));
    assert.equal(studio.win.__homeReadyHasDOM, true, 'Home-ready is emitted after Home commits to the DOM');
    assert.equal([...studio.doc.querySelectorAll('div')].some(node => node.style.zIndex === '200' &&
      node.style.inset === '0'), false, 'no decorative boot overlay blocks the committed Home');
    const choose = buttonIn(studio.doc.querySelector('[data-home-page]'), 'Choose a model');
    assert.ok(choose && !choose.disabled);
    click(studio, choose);
    await settle(studio.win);
    assert.ok(studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]'), 'Home click opens the model picker');
    assert.equal(loads, 0, 'Home controls do not wait for the graph projection');
  } finally {studio.close();}
});

test('BOOT2 Settings Studio card loads the deferred graph before showing its canvas', async () => {
  const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
  const captured = JSON.parse(read('02.TESTS/tests_js/fixtures/clean-canvas-fresh-runtime.json'));
  const node = captured.nodes[0];
  const shown = {id:node.id, title:node.label, cat:node.category || 'Definitions',
    x:0, y:0, w:220, h:110, ins:[], outs:[], params:[], live:true};
  let calls = 0;
  let snapshot = {canvas:{projection:'home', graph_id:'graph-a', root:'scope-a', revision:7,
    authorization:{subject:'owner-a',session:'view-a'}, scope:{current:'scope-a'}, nodes:[]},
    graph:{nodes:[],wires:[]}, library:[], workshops:[]};
  const listeners = new Set();
  const authority = {getSnapshot:() => snapshot, subscribe:fn => {listeners.add(fn);return () => listeners.delete(fn);},
    load:async () => {
      calls += 1;
      snapshot = {...snapshot, canvas:{...snapshot.canvas, projection:undefined, nodes:[node]},
        graph:{nodes:[shown],wires:[]}};
      listeners.forEach(fn => fn());
      return snapshot.canvas;
    }};
  const studio = await mountStudio({home:true, authority, hub:{ok:true,waiting:[],tools:[
    {id:'studio',label:'Studio',state:'running',description:'Canvas, chats and graph sessions.'},
  ]}, models:{ok:true,groups:[],selected_route:'',default_route:'',readiness:NO_MODEL}});
  try {
    await settle(studio.win);
    click(studio, studio.doc.querySelector('[title="Settings"]'));
    await settle(studio.win);
    const nav = settingsNavigator({doc:studio.doc, flush:studio.flush, settle:() => settle(studio.win)});
    const hub = await nav.tab('Hub');
    click(studio, hub.querySelector('[data-tool-card="studio"]'));
    await settle(studio.win); await settle(studio.win);
    assert.equal(calls, 1, 'Studio tool path reads the real graph once');
    assert.equal(studio.doc.querySelector('[data-home-page]'), null);
    assert.ok(studio.doc.body.textContent.includes(node.label), 'the loaded graph node is visible');
  } finally {studio.close();}
});

test('BOOT2 cold Home opens Docs lazily with refusal, Retry, and source tutorials', async () => {
  let calls = 0, rejectRead;
  let snapshot = {canvas:{projection:'home', graph_id:'graph-a', root:'scope-a', revision:7,
    authorization:{subject:'owner-a',session:'view-a'}, scope:{current:'scope-a'}, nodes:[]},
    graph:{nodes:[],wires:[]}, library:[], workshops:[]};
  const listeners = new Set();
  const authority = {getSnapshot:() => snapshot, subscribe:fn => {listeners.add(fn);return () => listeners.delete(fn);},
    load:() => {
      calls += 1;
      if (calls === 1) return new Promise((resolve, reject) => {rejectRead = reject;});
      snapshot = {...snapshot, canvas:{...snapshot.canvas, projection:undefined, documentation:{tutorials:[
        {id:'getting-started', title:'Fixture source tutorial', text:'Returned by the authority reader.'},
      ]}}};
      listeners.forEach(fn => fn());
      return Promise.resolve(snapshot.canvas);
    }};
  const studio = await mountStudio({home:true, authority,
    models:{ok:true,groups:[],selected_route:'',default_route:'',readiness:NO_MODEL}});
  try {
    await settle(studio.win);
    assert.equal(calls, 0, 'Home does not prefetch Docs or the full graph');
    click(studio, studio.doc.querySelector('[data-rail-panel="Docs"]'));
    await settle(studio.win);
    assert.equal(calls, 1, 'Docs opens the existing clean authority reader');
    const dialog = () => studio.doc.querySelector('[role="dialog"][aria-label="Documentation"]');
    assert.match(dialog().textContent, /Reading documentation/);
    rejectRead(new Error('Fixture documentation read refused.'));
    await settle(studio.win);
    assert.match(dialog().textContent, /Fixture documentation read refused/);
    click(studio, buttonIn(dialog(), 'Retry'));
    await settle(studio.win); await settle(studio.win);
    assert.equal(calls, 2, 'Retry performs one fresh read');
    assert.match(dialog().textContent, /Fixture source tutorial/);
    assert.match(dialog().textContent, /Returned by the authority reader/);
    assert.doesNotMatch(dialog().textContent, /Documentation is loading/);
  } finally {studio.close();}
});

test('Home boot with no route shows an explicit No model state and boot detail', async () => {
  const studio = await mountStudio({home:true,
    models:{ok:true, groups:[], selected_route:'', default_route:'', readiness:NO_MODEL}});
  try {
    await settle(studio.win); await settle(studio.win);
    assert.ok(studio.doc.querySelector('[data-home-page]'), 'Home is the boot screen');
    assert.equal(studio.doc.querySelectorAll('[data-node-id]').length, 0, 'no graph canvas is open at boot');
    assert.match(homeText(studio.doc), /No model yet/);
    assert.ok(buttonIn(studio.doc.querySelector('[data-home-page]'), 'Choose a model'));
    const line = studio.win.acBootDetail('brain');
    assert.match(line, /no model/i);
    assert.match(line, /sign in/i);
    assert.doesNotMatch(line, /connecting/);
  } finally { studio.close(); }
});

test('graph composer with no route shows an explicit No model state with Sign in and Choose a model', async () => {
  const started = [];
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:'', readiness:NO_MODEL},
    signin:method => { started.push(method); return Promise.resolve({phase:'waiting'}); }});
  try {
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'an explicit no-model state stands in Chat');
    assert.equal(card.getAttribute('role'), 'status');
    assert.match(card.textContent, /No model yet/);
    assert.ok(buttonIn(card, 'Choose a model'), 'Choose a model is offered in the state');
    const signIn = buttonIn(card, 'Sign in');
    assert.ok(signIn, 'Sign in is offered in the state');
    click(studio, signIn);
    await settle(studio.win);
    assert.equal(buttonIn(studio.doc.querySelector('[data-chat-no-model]'), 'Continue with Google'), undefined,
      'Chat does not render a second account sign-in block');
    assert.ok([...studio.doc.querySelectorAll('[data-settings54-capability-nav="account"] button')].some(button => button.textContent.trim() === 'Account'),
      'Sign in opens the existing Account settings surface');
    assert.deepEqual(started, []);
  } finally { studio.close(); }
});

test('graph deep-link with no route makes the Brain boot detail say no model, never "connecting"', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:'', readiness:NO_MODEL}});
  try {
    await settle(studio.win); await settle(studio.win);
    const line = studio.win.acBootDetail('brain');
    assert.match(line, /no model/i);
    assert.match(line, /sign in/i);
    assert.doesNotMatch(line, /connecting/);
  } finally { studio.close(); }
});

test('graph composer with a picked route without its key says what to do, in plain words', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'openrouter/vendor/m', default_route:'',
    readiness:answer('no_key', 'openrouter/vendor/m', fam())}});
  try {
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'the no-key state stands in Chat');
    assert.match(card.textContent, /Settings \u2192 Providers/);
    assert.doesNotMatch(card.textContent, JARGON);
  } finally { studio.close(); }
});

test('graph composer keeps an unsupported route on screen as its own state, never vanishes', async () => {
  const route = 'anthropic/claude-sonnet-5';
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:route, default_route:'',
    readiness:answer('invalid', route, fam('ready', 'ready'))}});
  try {
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'an unsupported route is said, not hidden');
    assert.match(card.textContent, /UNSUPPORTED MODEL/);
    assert.match(card.textContent, /Choose another model/);
    assert.ok(buttonIn(card, 'Choose a model'));
    assert.equal(buttonIn(card, 'Sign in'), undefined, 'signing in does not make this route reachable');
  } finally { studio.close(); }
});

test('graph composer sign-in uses the Account settings surface instead of a duplicate cloud block', async () => {
  const studio = await mountStudio({
    models:reads => ({ok:true, groups:[], selected_route:'cloud/archhub-free', default_route:'',
      readiness:reads === 1 ? answer('no_key', 'cloud/archhub-free', fam()) : answer('ready', 'cloud/archhub-free', fam('no_key', 'ready'))}),
    signin:() => Promise.resolve({phase:'done', email:'new@example.com'})});
  try {
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'sign-in-needed state stands before sign-in');
    click(studio, buttonIn(card, 'Sign in'));
    await settle(studio.win);
    assert.equal(buttonIn(studio.doc.querySelector('[data-chat-no-model]'), 'Continue with Google'), undefined);
    assert.ok(studio.doc.body.textContent.includes('Account'), 'the existing Account surface is open');
  } finally { studio.close(); }
});

test('graph composer judges the state for a newly picked route', async () => {
  const ROW = {name:'Model A', route:'vendor/model-a', routed:'openrouter/vendor/model-a', vendor:'vendor', tag:'BYO', ctx:'8k', cost:'$0 / $0 per M', col:'#3a6acc'};
  const studio = await mountStudio({
    models:{ok:true, live:true, count:1, groups:[{name:'BYO', items:[ROW]}], selected_route:'', default_route:'', readiness:NO_MODEL},
    select:route => Promise.resolve(route)});
  try {
    await settle(studio.win); await settle(studio.win);
    assert.match(studio.doc.querySelector('[data-chat-no-model]').textContent, /No model yet/);
    click(studio, buttonIn(studio.doc.querySelector('[data-chat-no-model]'), 'Choose a model'));
    await settle(studio.win); await settle(studio.win);
    const row = [...studio.doc.querySelectorAll('div')].find(node => node.style.cursor === 'pointer' && node.textContent.startsWith('MModel A'));
    assert.ok(row, 'the picker draws the row');
    click(studio, row);
    await settle(studio.win); await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'the picked route is judged');
    assert.match(card.textContent, /needs an OpenRouter key/, 'the state is the new route answer, not the stale one');
  } finally { studio.close(); }
});

// A canvas with one agent node whose model parameter the node holds (not the composer pick).
const nodeCanvas = route => ({nodes:[{id:'ask-a', label:'Ask', engine:'ai.agent', x:40, y:60, status:'',
  params:[{label:'engine', value:'ai.agent'}, {label:'model', value:route, relation:'rel-model', editable:true}], ports:[]}], wires:[]});

test('graph composer judges a selected node by its own model: a node model without its key warns', async () => {
  const studio = await mountStudio({raw:nodeCanvas('openrouter/vendor/node-model'), selected:'ask-a',
    models:{ok:true, groups:[], selected_route:'cloud/archhub-free', default_route:'',
      readiness:answer('ready', 'cloud/archhub-free', fam('no_key', 'ready'))}});
  try {
    await settle(studio.win); await settle(studio.win);
    click(studio, buttonIn(studio.doc.querySelector('[aria-label="Selection inspector"]'), 'Chat'));
    assert.equal(buttonIn(studio.doc.querySelector('[aria-label="Selection inspector"]'), 'Chat').getAttribute('aria-selected'), 'true');
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'the composer pick is ready, but the node shown asks OpenRouter without a key');
    assert.match(card.textContent, /needs an OpenRouter key/);
  } finally { studio.close(); }
});

test('graph composer with a selected node with no model says no model, never the composer route warning', async () => {
  const studio = await mountStudio({raw:nodeCanvas(''), selected:'ask-a',
    models:{ok:true, groups:[], selected_route:'cloud/archhub-free', default_route:'',
      readiness:answer('no_key', 'cloud/archhub-free', fam('ready', 'no_key'))}});
  try {
    await settle(studio.win); await settle(studio.win);
    click(studio, buttonIn(studio.doc.querySelector('[aria-label="Selection inspector"]'), 'Chat'));
    assert.equal(buttonIn(studio.doc.querySelector('[aria-label="Selection inspector"]'), 'Chat').getAttribute('aria-selected'), 'true');
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'a blank node model is said');
    assert.match(card.textContent, /NO MODEL/);
    assert.doesNotMatch(card.textContent, /ArchHub cloud/, 'the composer route warning does not stand for the node');
  } finally { studio.close(); }
});

test('graph composer with a ready route shows no no-model state', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:'openrouter/vendor/m',
    default_source:'settings default_model', readiness:answer('ready', 'openrouter/vendor/m', fam('ready', 'no_key'))}});
  try {
    await settle(studio.win); await settle(studio.win);
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null);
    assert.doesNotMatch(studio.win.acBootDetail('brain'), /no model/i);
  } finally { studio.close(); }
});
test('graph composer labels a :free model by its own family: lmstudio stays lmstudio, a bare one is OpenRouter', async () => {
  // Verifier 2026-09-28: lmstudio/<model>:free was read as OpenRouter's legacy free form and
  // shown the OpenRouter key state; model_router._legacy_free_route excludes family prefixes.
  const local = 'lmstudio/qwen3-8b:free';
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:local, default_route:'',
    readiness:answer('ready', local, fam())}});
  try {
    await settle(studio.win); await settle(studio.win);
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null, 'a ready LM Studio route is not blocked');
  } finally { studio.close(); }
  const bare = 'vendor/m:free';
  const legacy = await mountStudio({models:{ok:true, groups:[], selected_route:bare, default_route:'',
    readiness:answer('no_key', bare, fam())}});
  try {
    await settle(legacy.win); await settle(legacy.win);
    const card = legacy.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'a bare vendor/model:free route is OpenRouter and needs its key');
    assert.match(card.textContent, /Settings → Providers/);
  } finally { legacy.close(); }
});
