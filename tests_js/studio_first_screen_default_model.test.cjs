const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})/g)].map(m => [m[1], m[2]]));
const ROUTE = 'openrouter/free';
const MODEL = 'Free Models Router';

function projected() {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  const raw = {nodes:[{id:'work-a', label:'Coordination task', x:40, y:60, status:'',
    params:[{label:'priority', value:'high', relation:'rel-priority', editable:true}], ports:[]}], wires:[]};
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(raw) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio({models, selectedTitleLeak = '', modelReadTimeoutMs} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-suite.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, 'Studio build is stale for ' + source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53933/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  if (modelReadTimeoutMs) win.__ARCHHUB_MODEL_READ_TIMEOUT_MS = modelReadTimeoutMs;
  const defaultModels = {ok:true, selected_route:'',
      default_route:ROUTE, default_source:'free · OpenRouter',
      default_model:{name:MODEL, route:ROUTE, routed:ROUTE, vendor:'OpenRouter', tag:'FREE', ctx:'', col:'#3a6acc', latency:null},
      readiness:{state:'ready', route:ROUTE, actions:[], families:{
        openrouter:{state:'ready', message:'', actions:[]}, cloud:{state:'no_key', message:'', actions:[]},
        nvidia:{state:'no_key', message:'', actions:[]}, lmstudio:{state:'ready', message:'', actions:[]},
        ollama:{state:'ready', message:'', actions:[]}}, messages:{}}, groups:[]};
  win.fetch = url => {
    if (!String(url).startsWith('/api/universal/models')) return new Promise(() => {});
    const answer = typeof models === 'function' ? models() : (models || defaultModels);
    if (answer == null) return Promise.resolve({ok:true, status:200, json:async () => defaultModels});
    if (answer && answer.never) return new Promise(() => {});
    return Promise.resolve(answer).then(payload => {
      if (payload && payload.http) return {ok:payload.ok, status:payload.status || 500, json:async () => payload.body || {}};
      return {ok:true, status:200, json:async () => payload};
    });
  };
  const agentCalls = [];
  win.ARCHHUB_AGENT = async (text, route, context) => {
    agentCalls.push({text, route, context});
    return {answer:'PONG'};
  };
  win.ARCHHUB_AGENT_SELECT = async route => route;
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const graph = projected();
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a'};
  const canvas = {graph_id:'graph-a', root:'scope-a', revision:7, authorization};
  if (selectedTitleLeak) canvas.selected_title = selectedTitleLeak;
  const snapshot = {canvas,
    workshops:[], applicationUpdate:{state:'idle', current_build:'b1'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, selected_title:selectedTitleLeak,
      authorization, revision:7}, graph, selected:null}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    selectTopology:async id => { snapshot.topology.selected = id; listeners.forEach(listener => listener()); },
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
  const settle = async (done, what) => {
    for (let i = 0; i < 120 && !done(); i += 1) await new Promise(resolve => win.setTimeout(resolve, 5));
    assert.ok(done(), what);
  };
  const flush = action => win.ReactDOM.flushSync(action);
  const type = (input, text) => flush(() => {
    Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set.call(input, text);
    input.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  return {win, doc:win.document, settle, flush, type, agentCalls,
    close:() => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } }};
}

const modelIndicators = doc => [...doc.querySelectorAll('[data-model-indicator]')];
const button = (doc, label) => [...doc.querySelectorAll('button')].find(node => node.textContent.trim() === label);
const noModelCard = doc => doc.querySelector('[data-chat-no-model]');
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};

test('first screen bounds a rejected model read as unknown and Retry reads again', async () => {
  let reads = 0;
  const studio = await mountStudio({models:() => {
    reads += 1;
    if (reads === 1) return Promise.reject(new Error('network down'));
    return undefined;
  }});
  try {
    await studio.settle(() => noModelCard(studio.doc)?.textContent.includes('Models could not be read. Retry'),
      'the rejected read is bounded as unknown');
    const card = noModelCard(studio.doc);
    assert.match(card.textContent, /Models could not be read\. Retry/);
    assert.equal(button(card, 'Sign in'), undefined, 'unknown does not show a sign-in warning');
    assert.equal(button(card, 'Choose a model'), undefined, 'unknown does not offer a stale picker');
    studio.flush(() => button(card, 'Retry').click());
    await studio.settle(() => modelIndicators(studio.doc).some(node => node.textContent.includes(MODEL)),
      'Retry reads the model list again');
    assert.equal(noModelCard(studio.doc), null);
  } finally { studio.close(); }
});

test('first screen bounds a non-OK model read as unknown', async () => {
  const studio = await mountStudio({models:{http:true, ok:false, status:503, body:{ok:false}}});
  try {
    await studio.settle(() => noModelCard(studio.doc)?.textContent.includes('Models could not be read. Retry'),
      'the non-OK read is bounded as unknown');
    const card = noModelCard(studio.doc);
    assert.equal(button(card, 'Retry')?.textContent.trim(), 'Retry');
    assert.equal(button(card, 'Sign in'), undefined);
    assert.equal(button(card, 'Choose a model'), undefined);
  } finally { studio.close(); }
});

test('first screen bounds a timed-out model read as unknown', async () => {
  const studio = await mountStudio({models:{never:true}, modelReadTimeoutMs:20});
  try {
    await studio.settle(() => noModelCard(studio.doc)?.textContent.includes('Models could not be read. Retry'),
      'the timed-out read is bounded as unknown');
    const card = noModelCard(studio.doc);
    assert.equal(button(card, 'Retry')?.textContent.trim(), 'Retry');
    assert.equal(button(card, 'Sign in'), undefined);
    assert.equal(button(card, 'Choose a model'), undefined);
  } finally { studio.close(); }
});

test('first screen keeps model and readiness quiet until the first server answer', async () => {
  const models = deferred();
  const studio = await mountStudio({models:() => models.promise, selectedTitleLeak:'out \u2192 in'});
  try {
    const pendingHadNoCard = studio.doc.querySelector('[data-chat-no-model]') === null;
    const pendingHadNoChoose = button(studio.doc, 'Choose a model') === undefined;
    const pendingHadNoLeak = modelIndicators(studio.doc)
      .every(indicator => !/Choose a model|\bout\b|\bin\b/.test(indicator.textContent));
    models.resolve({ok:true, selected_route:'', default_route:ROUTE, default_source:'free · OpenRouter',
      default_model:{name:MODEL, route:ROUTE, routed:ROUTE, vendor:'OpenRouter', tag:'FREE', ctx:'', col:'#3a6acc', latency:null},
      readiness:{state:'ready', route:ROUTE, actions:[], families:{openrouter:{state:'ready', message:'', actions:[]}}, messages:{}},
      groups:[]});
    await studio.settle(() => modelIndicators(studio.doc).some(node => node.textContent.includes(MODEL)),
      'the default model label appears after the server answer');
    assert.equal(pendingHadNoCard, true, 'no no-model card is drawn before readiness answers');
    assert.equal(pendingHadNoChoose, true, 'no model CTA is drawn before readiness answers');
    assert.equal(pendingHadNoLeak, true, 'the pending chip has no Choose a model or out/in labels');
    assert.doesNotMatch(modelIndicators(studio.doc)[0].textContent, /\bout\b|\bin\b/);
  } finally { studio.close(); }
});

test('first screen shows the no-model line only after a real negative answer', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:'',
    readiness:{state:'no_model', route:'', actions:['sign_in', 'choose_model'],
      message:'No model yet. Sign in to ArchHub, or choose a model.',
      families:{}, messages:{no_model:'No model yet. Sign in to ArchHub, or choose a model.'}}}});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-chat-no-model]'), 'the negative answer is shown');
    assert.match(studio.doc.querySelector('[data-chat-no-model]').textContent, /No model yet/);
  } finally { studio.close(); }
});

test('fresh signed-out first screen preselects the free router with its friendly name', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(() => modelIndicators(studio.doc).some(node => node.textContent.includes(MODEL)),
      'the first screen shows the default free router label');
    assert.equal(modelIndicators(studio.doc).length, 1, 'the first screen has one model indicator');
    assert.match(modelIndicators(studio.doc)[0].textContent, /Free Models Router/);
    assert.doesNotMatch(modelIndicators(studio.doc)[0].textContent, /openrouter\/free/);
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null, 'the default free route is selected, not the no-model state');
    const inputs = [...studio.doc.querySelectorAll('input[aria-label="Ask selection"]')];
    assert.equal(inputs.length, 1,
      'CORE-C moved the first-screen composer into the right selection panel; exactly one real composer is mounted');
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel && panel.contains(inputs[0]), 'the real single composer lives in the selection panel');
    const input = inputs[0];
    studio.type(input, 'ping');
    studio.flush(() => button(studio.doc, 'Send').click());
    await studio.settle(() => studio.doc.body.textContent.includes('PONG'), 'the chat answer is drawn');
    assert.deepEqual(studio.agentCalls.map(call => [call.text, call.route]), [['ping', ROUTE]]);
    assert.ok([...studio.doc.querySelectorAll('[role="status"] span')].some(node => node.textContent === MODEL),
      'the answer turn is signed with the friendly model label');
  } finally { studio.close(); }
});
