/* Court (fix 1): Workshop opens, or says why (founder report 2026-09-23: "the Workshop does not
   open ... I click here and nothing opens"). The compiled Studio is mounted in an in-memory DOM
   over the owner snapshot shape studio-existing-workshop.js publishes (canvas.unavailable is the
   owner reason from workshop_scope.unavailable). Clicking Workshop with no room must draw that
   reason as visible text, never a silent no-op; with a room the same click opens it.
   No application, provider, network or graph file is touched. */const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function mountStudio({workshops = [], unavailable, models} = {}) {
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
test('Workshop with no room answers the click with the owner reason as visible text; with a room it opens', async () => {
  const reason = 'This account has no read access to the Workshop.';
  const refused = await mountStudio({workshops:[], unavailable:reason});
  try {
    const workshop = refused.segment('Workshop');
    assert.ok(workshop, 'the header offers the Workshop segment');
    assert.equal(refused.spoken().includes(reason), false, 'nothing is claimed before the click');
    refused.flush(() => workshop.click());
    assert.ok(refused.spoken().includes(reason), 'the click draws why, got: ' + JSON.stringify(refused.spoken()));
    assert.equal(workshop.disabled, false, 'Workshop stays clickable so it can answer');
    assert.equal(workshop.getAttribute('aria-disabled'), 'true', 'and states that no room is available');
    assert.match(workshop.style.outline, /dashed/, 'drawn dashed, never alpha');
    assert.equal(refused.segment('Chat').getAttribute('aria-pressed'), 'true', 'no conversation was opened');
  } finally { refused.close(); }

  const silent = await mountStudio({workshops:[]});
  try {
    silent.flush(() => silent.segment('Workshop').click());
    assert.ok(silent.spoken().includes('No Workshop conversation in this scope'),
      'without an owner reason the click still says why, got: ' + JSON.stringify(silent.spoken()));
  } finally { silent.close(); }

  const open = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}]});
  try {
    assert.equal(open.segment('Workshop').getAttribute('aria-pressed'), 'false');
    open.flush(() => open.segment('Workshop').click());
    assert.equal(open.segment('Workshop').getAttribute('aria-pressed'), 'true', 'the room opens as the Workshop conversation');
    assert.equal(open.spoken().includes('No Workshop conversation'), false, 'no refusal is drawn beside an open room');
  } finally { open.close(); }
});