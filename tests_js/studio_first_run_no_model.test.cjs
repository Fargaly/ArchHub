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
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

const vm = require('node:vm');
// The shipped studio.html canvas projection, so a node on the canvas is the node the Studio draws.
function projected(raw) {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(raw) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio({models, signin, select, raw, selected = null} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-account.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
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
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {doc, win, flush, close};
}
const settle = win => new Promise(resolve => win.setTimeout(resolve, 60));
const buttonIn = (node, label) => [...node.querySelectorAll('button')].find(b => b.textContent.trim() === label);
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

test('no route: Chat shows an explicit No model state with Sign in and Choose a model', async () => {
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
    const google = buttonIn(studio.doc.querySelector('[data-chat-no-model]'), 'Continue with Google');
    assert.ok(google, 'Sign in leads straight into the cloud sign-in');
    click(studio, google);
    await settle(studio.win);
    assert.deepEqual(started, ['google']);
  } finally { studio.close(); }
});

test('no route: the Brain line on the boot screen says no model, never "connecting"', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:'', readiness:NO_MODEL}});
  try {
    await settle(studio.win); await settle(studio.win);
    const line = studio.win.acBootDetail('brain');
    assert.match(line, /no model/i);
    assert.match(line, /sign in/i);
    assert.doesNotMatch(line, /connecting/);
  } finally { studio.close(); }
});

test('a picked route without its key says what to do, in plain words', async () => {
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

test('an unsupported route stays on screen as its own state, never vanishes', async () => {
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

test('after sign-in the readiness is read again, so a stale NO KEY state does not stay up', async () => {
  const studio = await mountStudio({
    models:reads => ({ok:true, groups:[], selected_route:'cloud/archhub-free', default_route:'',
      readiness:reads === 1 ? answer('no_key', 'cloud/archhub-free', fam()) : answer('ready', 'cloud/archhub-free', fam('no_key', 'ready'))}),
    signin:() => Promise.resolve({phase:'done', email:'new@example.com'})});
  try {
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'NO KEY stands before sign-in');
    click(studio, buttonIn(card, 'Sign in'));
    await settle(studio.win);
    click(studio, buttonIn(studio.doc.querySelector('[data-chat-no-model]'), 'Continue with Google'));
    await settle(studio.win); await settle(studio.win); await settle(studio.win);
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null, 'signed in: the state is read again and clears');
  } finally { studio.close(); }
});

test('after a model pick the state is judged for the new route', async () => {
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

test('a selected node is judged by its own model: a node model without its key warns', async () => {
  const studio = await mountStudio({raw:nodeCanvas('openrouter/vendor/node-model'), selected:'ask-a',
    models:{ok:true, groups:[], selected_route:'cloud/archhub-free', default_route:'',
      readiness:answer('ready', 'cloud/archhub-free', fam('no_key', 'ready'))}});
  try {
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'the composer pick is ready, but the node shown asks OpenRouter without a key');
    assert.match(card.textContent, /needs an OpenRouter key/);
  } finally { studio.close(); }
});

test('a selected node with no model says no model, never the composer route warning', async () => {
  const studio = await mountStudio({raw:nodeCanvas(''), selected:'ask-a',
    models:{ok:true, groups:[], selected_route:'cloud/archhub-free', default_route:'',
      readiness:answer('no_key', 'cloud/archhub-free', fam('ready', 'no_key'))}});
  try {
    await settle(studio.win); await settle(studio.win);
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.ok(card, 'a blank node model is said');
    assert.match(card.textContent, /NO MODEL/);
    assert.doesNotMatch(card.textContent, /ArchHub cloud/, 'the composer route warning does not stand for the node');
  } finally { studio.close(); }
});

test('a ready route shows no no-model state', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:'openrouter/vendor/m',
    default_source:'settings default_model', readiness:answer('ready', 'openrouter/vendor/m', fam('ready', 'no_key'))}});
  try {
    await settle(studio.win); await settle(studio.win);
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null);
    assert.doesNotMatch(studio.win.acBootDetail('brain'), /no model/i);
  } finally { studio.close(); }
});
test('a :free model is labelled by its own family: lmstudio stays lmstudio, a bare one is OpenRouter', async () => {
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
