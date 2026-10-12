/* Court (fix 1): Workshop opens, or says why (founder report 2026-09-23: "the Workshop does not
   open ... I click here and nothing opens"). The compiled Studio is mounted in an in-memory DOM
   over the owner snapshot shape studio-existing-workshop.js publishes (canvas.unavailable is the
   owner reason from workshop_scope.unavailable). The header switch is the design's Chat / Canvas
   (UI audit 2026-09-28), so the Workshop opens from Chat's Workshop button. Clicking it with no
   room must draw that reason as visible text, never a silent no-op; with a room the same click opens it.
   No application, provider, network or graph file is touched. */const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));
const msg = (root, sequence, body) => ({root, message_id:root, sequence, body, sender_root:'owner-a',
  created_at:'2026-10-12T00:00:00Z', category:'note', state:'sent'});

async function mountStudio({workshops = [], unavailable, models, canvasGraphId = 'graph-a',
  sessions = [{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}], currentGraph = 'graph-a',
  workshop = null} = {}) {
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
  win.requestAnimationFrame = cb => win.setTimeout(() => cb(win.performance.now()), 0);
  win.cancelAnimationFrame = id => win.clearTimeout(id);
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[], wires:[]};
  const listeners = new Set();
  const canvas = {root:'scope-a', revision:7, authorization, ...(unavailable === undefined ? {} : {unavailable})};
  if (canvasGraphId) canvas.graph_id = canvasGraphId;
  let snapshot = {canvas, workshops, ...(workshop ? {workshop} : {}),
    applicationUpdate:{state:'idle', current_build:'20260923-r8'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const notify = () => listeners.forEach(listener => listener());
  const owner = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    watchApplicationUpdate:() => () => {},
  };
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner, {get:(target, key) => key in target || typeof key !== 'string' ||
    key === 'then' ? target[key] : () => new Promise(() => {})});
  win.ARCHHUB_LIVE = {sessions, currentGraph, hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const segment = label => label === 'Workshop' ? doc.querySelector('button[data-tool-rail="workshop"]') :
    [...doc.querySelectorAll('button[aria-pressed]')].find(button => button.textContent.trim() === label);
  const fullWorkshopTabs = () => [...doc.querySelectorAll('[role="tablist"][aria-label="Workshop tabs"] [role="tab"]')];
  const inWorkshop = () => fullWorkshopTabs().length > 0 || !!doc.querySelector('main[data-tool-view="workshop"]') ||
    /Workshop projects|No Workshop project/.test(doc.body.textContent);
  const spoken = () => [...doc.querySelectorAll('[role="alert"], [role="status"]')].map(node => node.textContent.trim()).join(' | ');
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const setWorkshop = value => { snapshot = value ? {...snapshot, workshop:value} :
    Object.fromEntries(Object.entries(snapshot).filter(([key]) => key !== 'workshop')); notify(); };
  return {doc, win, flush, segment, spoken, close, inWorkshop, fullWorkshopTabs, setWorkshop};
}
test('Workshop opens from the rail view, not from a Studio header Chat segment', async () => {
  const reason = 'This account has no read access to the Workshop.';
  const refused = await mountStudio({workshops:[], unavailable:reason});
  try {
    const workshop = refused.segment('Workshop');
    assert.ok(workshop, 'the rail offers Workshop');
    assert.equal([...refused.doc.querySelectorAll('main > div button')].some(button => button.textContent.trim() === 'Workshop'), false,
      'the Studio header does not offer a Workshop tab');
    refused.flush(() => workshop.click());
    assert.equal(refused.inWorkshop(), true,
      'the Workshop rail opens the Workshop view even with no room: ' + refused.doc.body.textContent.slice(0, 240));
  } finally { refused.close(); }

  const silent = await mountStudio({workshops:[], canvasGraphId:''});
  try {
    silent.flush(() => silent.segment('Workshop').click());
    assert.equal(silent.doc.querySelector('main[data-tool-view="workshop"]'), null,
      'fresh profile Workshop rail does not fall back to the Studio Home tool page');
    assert.deepEqual(silent.fullWorkshopTabs().map(tab => tab.getAttribute('aria-label')),
      ['Chat', 'Tasks', 'Router', 'Relay', 'Prompts', 'Agents', 'Approvals'],
      'fresh profile with no owner rows still opens the full Workshop tab bar');
    assert.ok(silent.fullWorkshopTabs().some(tab => tab.getAttribute('aria-label') === 'Router'));
    assert.ok(silent.fullWorkshopTabs().some(tab => tab.getAttribute('aria-label') === 'Relay'));
    assert.ok(silent.fullWorkshopTabs().some(tab => tab.getAttribute('aria-label') === 'Tasks'));
  } finally { silent.close(); }

  const open = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}]});
  try {
    assert.equal(open.inWorkshop(), false, 'the Studio opens on the canvas, not inside Workshop');
    open.flush(() => open.segment('Workshop').click());
    assert.equal(open.inWorkshop(), true, 'the rail opens the Workshop view');
    assert.deepEqual(open.fullWorkshopTabs().map(tab => tab.getAttribute('aria-label')),
      ['Chat', 'Tasks', 'Router', 'Relay', 'Prompts', 'Agents', 'Approvals'],
      'rail Workshop opens the full Workshop tab bar');
    assert.equal(open.fullWorkshopTabs().find(tab => tab.getAttribute('aria-label') === 'Tasks')?.getAttribute('aria-selected'), 'true',
      'rail Workshop lands on the Tasks tab');
    assert.equal([...open.doc.querySelectorAll('main > div button')].some(button => button.textContent.trim() === 'Workshop'), false,
      'the open Workshop is not represented as a Studio header segment');
    open.flush(() => open.doc.querySelector('button[aria-label^="Leave Workshop"]').click());
    assert.ok(open.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), 'leaving Workshop returns to Canvas');
    assert.equal(open.doc.querySelectorAll('input[aria-label="Ask selection"]').length, 1,
      'Canvas selection panel has one composer after leaving Workshop');
    assert.equal(open.doc.querySelectorAll('[data-model-indicator]').length, 1,
      'Canvas selection panel has one model indicator after leaving Workshop');
    assert.equal(open.doc.querySelector('input[aria-label="Reply"]'), null,
      'legacy ChatView reply input is not mounted after leaving Workshop');
  } finally { open.close(); }
});

test('graphless profile Workshop rail opens Workshop content, never Home', async () => {
  const studio = await mountStudio({workshops:[], canvasGraphId:'', sessions:[], currentGraph:null});
  try {
    studio.flush(() => studio.segment('Workshop').click());
    assert.equal(studio.doc.querySelector('main[data-tool-view="workshop"]') !== null || studio.fullWorkshopTabs().length > 0, true,
      'Workshop content is visible with no session and no graph id');
    assert.equal(/New graph|Open a saved graph|Recent sessions/.test(studio.doc.body.textContent), false,
      'Workshop rail did not fall through to Home');
  } finally { studio.close(); }
});

test('first Workshop rail switch stays under the synchronous render budget', async () => {
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}]});
  try {
    const started = studio.win.performance.now();
    studio.flush(() => studio.segment('Workshop').click());
    const elapsed = studio.win.performance.now() - started;
    assert.equal(studio.inWorkshop(), true, 'Workshop opened from rail');
    assert.ok(elapsed < 300, 'first Workshop switch took ' + elapsed.toFixed(1) + ' ms');
    console.log('first Workshop rail switch ms=' + elapsed.toFixed(1));
    const chat = studio.fullWorkshopTabs().find(tab => tab.getAttribute('aria-label') === 'Chat');
    assert.ok(chat, 'Workshop Chat tab exists');
    const chatStarted = studio.win.performance.now();
    studio.flush(() => chat.click());
    const chatElapsed = studio.win.performance.now() - chatStarted;
    assert.equal(studio.fullWorkshopTabs().find(tab => tab.getAttribute('aria-label') === 'Chat')?.getAttribute('aria-selected'), 'true',
      'Chat tab selected');
    assert.ok(chatElapsed < 300, 'first Workshop Chat tab switch took ' + chatElapsed.toFixed(1) + ' ms');
    console.log('first Workshop Chat tab switch ms=' + chatElapsed.toFixed(1));
  } finally { studio.close(); }
});

// Ping P2 (ST1 review): a rail entry that opens Settings must leave the Workshop chat as it was.
test('a Settings rail entry opened from Workshop chat keeps the same chat when Settings closes', async () => {
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:7,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false,
    participants:[{root:'owner-a', label:'Owner', attached:true}], messages:[msg('m1', 1, 'Cached transcript row')]};
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}], workshop:transcript});
  try {
    studio.flush(() => studio.segment('Workshop').click());
    const chat = studio.fullWorkshopTabs().find(tab => tab.getAttribute('aria-label') === 'Chat');
    studio.flush(() => chat.click());
    // Wait for the cached row rather than a fixed delay: under suite load 20 ms is not always enough.
    for (let i = 0; i < 200 && !/Cached transcript row/.test(studio.doc.querySelector('[aria-label="Workshop conversation"]')?.textContent || ''); i += 1) {
      await new Promise(resolve => studio.win.setTimeout(resolve, 10)); studio.flush(() => {});
    }
    const before = studio.doc.querySelector('[aria-label="Workshop conversation"]');
    assert.match(before.textContent, /Cached transcript row/, 'the Workshop chat is open');
    // The hub says these tools are on (an off tool takes the off route, which CP1 covers).
    studio.win.ARCHHUB_TOOL_HUB = {ok:true, waiting:[], tools:['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']
      .map(id => ({id, label:id, state:'running', state_word:'RUNNING', description:'', stat_line:''}))};
    for (const id of ['brain', 'connectors', 'baboom', 'cloud']) {
      const rail = studio.doc.querySelector(`[data-tool-rail="${id}"]`);
      assert.ok(rail, id + ' rail entry exists');
      studio.flush(() => rail.click());
      await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
      assert.ok([...studio.doc.querySelectorAll('button')].some(b => b.firstElementChild?.textContent === 'Theme'), id + ' opened Settings');
      studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
      await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
      assert.equal([...studio.doc.querySelectorAll('button')].some(b => b.firstElementChild?.textContent === 'Theme'), false, 'Settings closed');
      const after = studio.doc.querySelector('[aria-label="Workshop conversation"]');
      assert.ok(after, id + ': the Workshop chat is still the view after Settings closes');
      assert.match(after.textContent, /Cached transcript row/, id + ': same conversation');
      assert.equal(studio.fullWorkshopTabs().find(tab => tab.getAttribute('aria-label') === 'Chat')?.getAttribute('aria-selected'), 'true',
        id + ': Chat is still the selected Workshop tab');
    }
  } finally { studio.close(); }
});

// CP1: an off tool opens Settings > Hub over the view, so the Workshop chat survives it too.
test('an off tool opened from Workshop chat opens Settings > Hub and keeps the same chat when it closes', async () => {
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:7,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false,
    participants:[{root:'owner-a', label:'Owner', attached:true}], messages:[msg('m1', 1, 'Cached transcript row')]};
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}], workshop:transcript});
  try {
    studio.flush(() => studio.segment('Workshop').click());
    const chat = studio.fullWorkshopTabs().find(tab => tab.getAttribute('aria-label') === 'Chat');
    studio.flush(() => chat.click());
    // Wait for the cached row rather than a fixed delay: under suite load 20 ms is not always enough.
    for (let i = 0; i < 200 && !/Cached transcript row/.test(studio.doc.querySelector('[aria-label="Workshop conversation"]')?.textContent || ''); i += 1) {
      await new Promise(resolve => studio.win.setTimeout(resolve, 10)); studio.flush(() => {});
    }
    studio.win.ARCHHUB_TOOL_HUB = {ok:true, waiting:[], tools:['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']
      .map(id => ({id, label:id, state:id === 'brain' ? 'off' : 'running', state_word:id === 'brain' ? 'OFF' : 'RUNNING', description:'', stat_line:''}))};
    studio.flush(() => studio.doc.querySelector('[data-tool-rail="brain"]').click());
    await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
    const hub = [...studio.doc.querySelectorAll('button')].find(b => b.firstElementChild?.textContent === 'Hub');
    assert.ok(hub, 'the off Brain opened Settings');
    assert.equal(studio.doc.querySelector('main[data-tool-view]'), null, 'no full-window off page');
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
    const after = studio.doc.querySelector('[aria-label="Workshop conversation"]');
    assert.ok(after, 'the Workshop chat is still the view after Settings closes');
    assert.match(after.textContent, /Cached transcript row/, 'same conversation');
  } finally { studio.close(); }
});

test('Workshop Chat mounts already-read transcript rows from the owner projection', async () => {
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:7,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false,
    participants:[{root:'owner-a', label:'Owner', attached:true}], messages:[msg('m1', 1, 'Cached transcript row')]};
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}], workshop:transcript});
  try {
    studio.flush(() => studio.segment('Workshop').click());
    const chat = studio.fullWorkshopTabs().find(tab => tab.getAttribute('aria-label') === 'Chat');
    studio.flush(() => chat.click());
    await new Promise(resolve => studio.win.setTimeout(resolve, 20));
    studio.flush(() => {});
    const stream = studio.doc.querySelector('[aria-label="Workshop conversation"]');
    assert.match(stream.textContent, /Cached transcript row/, 'cached row is visible without waiting for fetch');
    const seen = [];
    const observer = new studio.win.MutationObserver(records => seen.push(...records));
    observer.observe(stream, {childList:true, subtree:true});
    studio.flush(() => studio.setWorkshop({...transcript, messages:[msg('m1', 1, 'Cached transcript row')]}));
    await Promise.resolve(); studio.flush(() => {});
    assert.equal(seen.filter(r => r.type === 'childList').length, 0, 'identical projection causes no childList mutations');
    studio.flush(() => studio.setWorkshop({...transcript, revision:8,
      messages:[transcript.messages[0], msg('m2', 2, 'Appended transcript row')]}));
    await Promise.resolve(); studio.flush(() => {});
    assert.deepEqual([...stream.querySelectorAll('[data-workshop-message]')].map(row => row.getAttribute('data-workshop-message')),
      ['m1', 'm2']);
    assert.equal(seen.flatMap(r => [...r.removedNodes]).some(node => node.nodeType === 1 &&
      node.matches?.('[data-workshop-message]')), false, 'append did not remove an existing message row');
    observer.disconnect();
  } finally { studio.close(); }
});
