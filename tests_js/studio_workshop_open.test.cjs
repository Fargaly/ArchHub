const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
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
  const openHome = () => {
    const home = doc.querySelector('[title="All sessions"]');
    if (home) flush(() => home.click());
  };
  const hubTool = id => {
    const settings = doc.querySelector('[data-app-rail] [aria-label="Settings"]') || doc.querySelector('[title="Settings"]');
    assert.ok(settings, 'Settings rail control exists');
    flush(() => settings.click());
    const shell = doc.querySelector('[data-settings54-shell]');
    assert.ok(shell, 'Settings opens for the Hub card');
    const group = [...shell.querySelectorAll('[data-settings54-group-title]')].find(node => node.textContent.trim() === 'Connections');
    assert.ok(group, 'Connections owns Hub');
    flush(() => group.closest('button').click());
    const hub = [...shell.querySelectorAll('[data-settings54-capability-nav] button')].find(node => node.textContent.trim() === 'Hub');
    assert.ok(hub, 'Hub is a visible Connections capability');
    flush(() => hub.click());
    return shell.querySelector(`[data-tool-card="${id}"]`);
  };
  const settingsButton = () => doc.querySelector('[data-workshop72-rail] [aria-label="Settings"]') || doc.querySelector('[title="Settings"]');
  const segment = label => label === 'Workshop' ? hubTool('workshop') :
    [...doc.querySelectorAll('button[aria-pressed]')].find(button => button.textContent.trim() === label);
  const workshopUtilities = () => {
    return [...doc.querySelectorAll('button[data-workshop-utility]')];
  };
  const inWorkshop = () => workshopUtilities().length > 0 || !!doc.querySelector('[data-workshop-s1]') || !!doc.querySelector('main[data-tool-view="workshop"]') ||
    /Workshop projects|No Workshop project/.test(doc.body.textContent);
  const spoken = () => [...doc.querySelectorAll('[role="alert"], [role="status"]')].map(node => node.textContent.trim()).join(' | ');
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const setWorkshop = value => { snapshot = value ? {...snapshot, workshop:value} :
    Object.fromEntries(Object.entries(snapshot).filter(([key]) => key !== 'workshop')); notify(); };
  return {doc, win, flush, segment, hubTool, openHome, settingsButton, spoken, close, inWorkshop, workshopUtilities, setWorkshop};
}

test('Workshop Hub and Settings routes open one DSYS077 thread even without an admitted room',async()=>{
  for(const options of [{workshops:[],unavailable:'This account has no read access to the Workshop.'},
    {workshops:[],canvasGraphId:'',sessions:[],currentGraph:null},
    {workshops:[{root:'room-a',label:'Wall conversion',is_general:false}]}]){
    const ui=await mountStudio(options);
    try{const card=ui.segment('Workshop');assert.ok(card);ui.flush(()=>card.click());
      assert.equal(ui.inWorkshop(),true);assert.ok(ui.doc.querySelector('[data-workshop72]'));
      assert.equal(ui.doc.querySelector('[role="tablist"][aria-label="Workshop tabs"]'),null);
      assert.equal(ui.doc.querySelector('[data-workshop-utility]'),null);
      assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Workshop message"]').length,1);
      assert.equal(ui.doc.querySelector('[data-workshop-s1-inspector]'),null);
      assert.ok(ui.doc.querySelector('[data-workshop-empty]'),'zero tasks/messages has the DSYS074 empty composer');
      const open=ui.doc.querySelector('[data-workshop72-rail] [aria-label="Canvas"]');
      if(options.workshops.length){ui.flush(()=>open.click());
        assert.ok(ui.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'));
        assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Workshop message"]').length,0);
        assert.equal(ui.doc.querySelector('input[aria-label="Reply"]'),null);
      }
    }finally{ui.close();}
  }
});

test('graphless profile Workshop Hub card opens Workshop content, never Home', async () => {
  const studio = await mountStudio({workshops:[], canvasGraphId:'', sessions:[], currentGraph:null});
  try {
    const workshop = studio.segment('Workshop');
    studio.flush(() => workshop.click());
    assert.equal(studio.doc.querySelector('[data-workshop72]') !== null, true,
      'Workshop content is visible with no session and no graph id');
    assert.equal(/New graph|Open a saved graph|Recent sessions/.test(studio.doc.body.textContent), false,
      'Workshop card did not fall through to Home');
  } finally { studio.close(); }
});


test('first Workshop Hub-card switch stays under the synchronous render budget and opens directly to the empty composer',async()=>{
  const ui=await mountStudio({workshops:[{root:'room-a',label:'Wall conversion',is_general:false}]});
  try{const card=ui.segment('Workshop'),started=ui.win.performance.now();ui.flush(()=>card.click());
    const elapsed=ui.win.performance.now()-started;assert.equal(ui.inWorkshop(),true);assert.ok(elapsed<300,'Workshop switch '+elapsed.toFixed(1)+' ms');
    console.log('first Workshop Hub-card switch ms='+elapsed.toFixed(1));
    assert.ok(ui.doc.querySelector('[data-workshop-empty]'));
    assert.match(ui.doc.querySelector('[data-workshop-empty]').textContent,/What should the agents do\?/);
    assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Workshop message"]').length,1);assert.equal(ui.doc.querySelector('[data-workshop-utility]'),null);
  }finally{ui.close();}
});

// Ping P2 (ST1 review): a rail entry that opens Settings must leave the Workshop chat as it was.
test('a Settings Hub card opened from Workshop chat keeps the same chat when Settings closes', async () => {
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:7,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false,
    participants:[{root:'owner-a', label:'Owner', attached:true}], messages:[msg('m1', 1, 'Cached transcript row')]};
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}], workshop:transcript});
  try {
    const workshop = studio.segment('Workshop');
    studio.flush(() => workshop.click());
    assert.ok(studio.doc.querySelector('[aria-label="Workshop conversation"]'));
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
      studio.flush(() => studio.settingsButton().click());
      await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
      const nav = settingsNavigator({doc:studio.doc, flush:studio.flush,
        settle:async () => { await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {}); }});
      const hub = await nav.capability('Hub');
      assert.ok(hub, 'Settings Hub behavior tab exists');
      await nav.tab('Hub');
      const card = studio.doc.querySelector(`[data-tool-card="${id}"]`);
      assert.ok(card, id + ' Hub card exists');
      studio.flush(() => card.click());
      await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
      assert.ok(studio.doc.querySelector('[data-settings54-shell]'), id + ' opened Settings');
      studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
      await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
      assert.equal(!!studio.doc.querySelector('[data-settings54-shell]'), false, 'Settings closed');
      const after = studio.doc.querySelector('[aria-label="Workshop conversation"]');
      assert.ok(after, id + ': the Workshop chat is still the view after Settings closes');
      assert.match(after.textContent, /Cached transcript row/, id + ': same conversation');
      assert.ok(studio.doc.querySelector('[data-workshop72]'), id + ': same single Workshop thread stays open');
    }
  } finally { studio.close(); }
});

// CP1: an off tool opens Settings > Hub over the view, so the Workshop chat survives it too.
test('an off tool opened from Workshop chat through Settings Hub keeps the same chat when it closes', async () => {
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:7,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false,
    participants:[{root:'owner-a', label:'Owner', attached:true}], messages:[msg('m1', 1, 'Cached transcript row')]};
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall conversion', is_general:false}], workshop:transcript});
  try {
    const workshop = studio.segment('Workshop');
    studio.flush(() => workshop.click());
    assert.ok(studio.doc.querySelector('[aria-label="Workshop conversation"]'));
    // Wait for the cached row rather than a fixed delay: under suite load 20 ms is not always enough.
    for (let i = 0; i < 200 && !/Cached transcript row/.test(studio.doc.querySelector('[aria-label="Workshop conversation"]')?.textContent || ''); i += 1) {
      await new Promise(resolve => studio.win.setTimeout(resolve, 10)); studio.flush(() => {});
    }
    studio.win.ARCHHUB_TOOL_HUB = {ok:true, waiting:[], tools:['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']
      .map(id => ({id, label:id, state:id === 'brain' ? 'off' : 'running', state_word:id === 'brain' ? 'OFF' : 'RUNNING', description:'', stat_line:''}))};
    studio.flush(() => studio.settingsButton().click());
    await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
    const navigator = settingsNavigator({doc:studio.doc, flush:studio.flush,
      settle:async () => { await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {}); }});
    const hubPanel = await navigator.tab('Hub');
    assert.ok(hubPanel.querySelector('[data-tool-card="brain"]'), 'Settings Hub behavior owner exists');
    studio.flush(() => studio.doc.querySelector('[data-tool-card="brain"]').click());
    await new Promise(resolve => studio.win.setTimeout(resolve, 0)); studio.flush(() => {});
    const shell = studio.doc.querySelector('[data-settings54-shell]');
    assert.ok(shell, 'the off Brain opened Settings');
    assert.match(shell.querySelector('main > div:first-child').textContent, /Settings\s*›\s*Hub/,
      'the off Brain lands on the actual Hub owner');
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
    const workshop = studio.segment('Workshop');
    studio.flush(() => workshop.click());
    assert.ok(studio.doc.querySelector('[aria-label="Workshop conversation"]'));
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
    const currentStream = studio.doc.querySelector('[aria-label="Workshop conversation"]');
    assert.match(currentStream.textContent, /Cached transcript row/);
    assert.match(currentStream.textContent, /Appended transcript row/);
    assert.equal(seen.flatMap(r => [...r.removedNodes]).some(node => node.nodeType === 1 &&
      node.matches?.('[data-workshop-message]')), false, 'append did not remove an existing message row');
    observer.disconnect();
  } finally { studio.close(); }
});
