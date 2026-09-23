/* Court (fix 2): with no saved pick the Studio shows the model the founder configured
   (default_route = settings default_model) and sends with it; with none, no model is chosen for
   him: Send is not offered, a visible "Choose a model" opens the picker and nothing is sent
   (founder report 2026-09-23; coordination review). Only the model listing is answered.
   No application, provider, network or graph file is touched. */const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function mountStudio({workshops = [], unavailable, models, agent} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  // Only the model listing may answer; every other request stays pending, as an unanswered server would.
  win.fetch = url => String(url).includes('/api/universal/models') && models
    ? Promise.resolve({ok:true, json:() => Promise.resolve(models)}) : new Promise(() => {});
  if (agent) win.ARCHHUB_AGENT = agent;
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[], wires:[]};
  const listeners = new Set();
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization,
      ...(unavailable === undefined ? {} : {unavailable})}, workshops,
    applicationUpdate:{state:'idle', current_build:'20260923-r8'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const owner = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    watchApplicationUpdate:() => () => {},
  };
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
  const segment = label => [...doc.querySelectorAll('button[aria-pressed]')].find(button => button.textContent.trim() === label);
  const spoken = () => [...doc.querySelectorAll('[role="alert"], [role="status"]')].map(node => node.textContent.trim()).join(' | ');
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {doc, win, flush, segment, spoken, close};
}
const settle = win => new Promise(resolve => win.setTimeout(resolve, 60));
const button = (doc, label) => [...doc.querySelectorAll('button')].find(node => node.textContent.trim() === label);

test('no saved pick: the header names the configured default model', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'',
    default_route:'openrouter/vendor/configured', default_source:'settings default_model'}});
  try {
    await settle(studio.win); await settle(studio.win);
    const text = studio.doc.body.textContent;
    assert.ok(text.includes('openrouter/vendor/configured'), 'the configured default is shown');
    assert.ok(button(studio.doc, 'Send ↵'), 'Send is offered with a configured model');
  } finally { studio.close(); }
});

test('no pick and no configured model: nothing is sent, "Choose a model" opens the picker', async () => {
  const asked = [];
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:''},
    agent:(text, route) => { asked.push([text, route]); return Promise.resolve('answer'); }});
  try {
    await settle(studio.win); await settle(studio.win);
    assert.equal(button(studio.doc, 'Send ↵'), undefined, 'Send is not offered without a model');
    const choose = button(studio.doc, 'Choose a model');
    assert.ok(choose, 'a visible "Choose a model" stands where Send would be');
    const reply = studio.doc.querySelector('input[aria-label="Reply"]');
    studio.flush(() => { const set = Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set;
      set.call(reply, 'hello'); reply.dispatchEvent(new studio.win.Event('input', {bubbles:true})); });
    studio.flush(() => reply.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await settle(studio.win);
    assert.ok(studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]'), 'Enter opens the picker');
    assert.deepEqual(asked, [], 'no model was chosen and nothing was sent');
  } finally { studio.close(); }
});

test('a saved pick still wins over the configured default', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'openrouter/vendor/picked',
    default_route:'openrouter/vendor/configured'}});
  try {
    await settle(studio.win); await settle(studio.win);
    const text = studio.doc.body.textContent;
    assert.ok(text.includes('openrouter/vendor/picked'), 'the saved pick is shown');
    assert.equal(text.includes('openrouter/vendor/configured'), false, 'the default does not replace a pick');
  } finally { studio.close(); }
});