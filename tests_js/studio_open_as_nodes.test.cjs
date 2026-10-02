/* "Open as nodes" on a workflow card must walk the workflow's own scope (where its step
   nodes draw) through the existing scope-open path, then focus and switch to the canvas.
   A workflow whose scope_path does not end at its scope is refused with a message and the
   mode never switches. Pure helper; no React, no app, no network. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const file = process.env.ARCHHUB_WORKSHOP_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-workshop.jsx');
const source = fs.readFileSync(file, 'utf8');

function loadHelper() {
  const from = 'async function openWorkflowAsNodes', to = '\nconst WorkshopView =';
  const start = source.indexOf(from), end = source.indexOf(to, start);
  assert.ok(start >= 0 && end > start, 'openWorkflowAsNodes is a slice of the shipped studio-workshop.jsx');
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end) + '\nglobalThis.open = openWorkflowAsNodes;', context);
  return context.open;
}

const WORKFLOW = {root:'assembly-instance:wf', scope:'app:workshop-workbench', members:['assembly-instance:wf'],
  scope_path:['app:map-domain', 'app:workshop-workbench']};

// ── source: openAsNodes routes through the helper (not a bare focus+mode) ──
test('openAsNodes delegates to the scope-walking helper', () => {
  const body = source.slice(source.indexOf('const openAsNodes ='), source.indexOf('const openAsNodes =') + 600);
  assert.match(body, /openWorkflowAsNodes\(/, 'openAsNodes must call openWorkflowAsNodes');
  assert.match(body, /scope_path|workflow/, 'openAsNodes must resolve the focused workflow');
});

// ── walk: a workflow with a valid scope_path is walked, then focus + canvas ──
test('a workflow scope_path is walked through authority.open, then focus and switch', async () => {
  const open = loadHelper();
  const opened = []; let focused = null, mode = null, err = null;
  const authority = { load: async () => ({scope:{current:'app:root', trail:[{root:'app:root'}]}}),
    open: async step => { opened.push(step); return {scope:{current:step, trail:[{root:'app:root'}]}}; } };
  const ok = await open({focus:'assembly-instance:wf', workflow:WORKFLOW, authority,
    scopeOpen:null, setFocusId:id => focused = id, setMode:m => mode = m, setError:e => err = e});
  assert.equal(ok, true);
  assert.deepEqual(opened, ['app:map-domain', 'app:workshop-workbench'], 'each scope step is opened in order');
  assert.equal(focused, 'assembly-instance:wf');
  assert.equal(mode, 'canvas');
  assert.equal(err, null);
});

// ── walk: with no signed authority, it uses ARCHHUB_SCOPE_OPEN (the only other path) ──
test('without a signed authority the walk uses scopeOpen(path)', async () => {
  const open = loadHelper();
  let walked = null, mode = null;
  const ok = await open({focus:'assembly-instance:wf', workflow:WORKFLOW, authority:null,
    scopeOpen:async p => { walked = p; }, setFocusId:()=>{}, setMode:m => mode = m, setError:()=>{}});
  assert.equal(ok, true);
  assert.deepEqual(walked, ['app:map-domain', 'app:workshop-workbench']);
  assert.equal(mode, 'canvas');
});

// ── refuse: a scope_path that does not end at the workflow scope → message, no switch ──
test('a scope_path not ending at the workflow scope is refused without switching mode', async () => {
  const open = loadHelper();
  let mode = null, err = null, walked = false;
  const ok = await open({focus:'assembly-instance:wf',
    workflow:{...WORKFLOW, scope_path:['app:somewhere-else']}, authority:null,
    scopeOpen:async () => { walked = true; }, setFocusId:()=>{}, setMode:m => mode = m, setError:e => err = e});
  assert.equal(ok, false);
  assert.equal(walked, false, 'the wrong scope is never opened');
  assert.equal(mode, null, 'the mode never switches on refusal');
  assert.match(err, /cannot be opened from here/);
});

// ── refuse: a null scope_path (server omitted it) → message, no switch ──
test('a missing scope_path is refused without switching mode', async () => {
  const open = loadHelper();
  let mode = null, err = null;
  const ok = await open({focus:'assembly-instance:wf', workflow:{...WORKFLOW, scope_path:null},
    authority:null, scopeOpen:async () => {}, setFocusId:()=>{}, setMode:m => mode = m, setError:e => err = e});
  assert.equal(ok, false);
  assert.equal(mode, null);
  assert.match(err, /cannot be opened/);
});

// ── failure: an open that throws → message, no switch ──
test('a failing scope open shows its message and does not switch mode', async () => {
  const open = loadHelper();
  let mode = null, err = null;
  const ok = await open({focus:'assembly-instance:wf', workflow:WORKFLOW, authority:null,
    scopeOpen:async () => { throw new Error('scope walk refused'); },
    setFocusId:()=>{}, setMode:m => mode = m, setError:e => err = e});
  assert.equal(ok, false);
  assert.equal(mode, null);
  assert.match(err, /scope walk refused/);
});

// ── no workflow: a plain focus (e.g. a session Agent node) just focuses and switches ──
test('a focus with no workflow focuses and switches with no scope walk', async () => {
  const open = loadHelper();
  let walked = false, focused = null, mode = null;
  const ok = await open({focus:'node-agent', workflow:null, authority:null,
    scopeOpen:async () => { walked = true; }, setFocusId:id => focused = id, setMode:m => mode = m, setError:()=>{}});
  assert.equal(ok, true);
  assert.equal(walked, false, 'no scope walk without a workflow');
  assert.equal(focused, 'node-agent');
  assert.equal(mode, 'canvas');
});

// The real card handler: slices BOTH functions and returns the one the workflow card calls.
function loadCard() {
  const from = 'async function openWorkflowAsNodes', to = '\nconst WorkshopView =';
  const start = source.indexOf(from), end = source.indexOf(to, start);
  assert.ok(start >= 0 && end > start, 'the open helpers are a slice of the shipped studio-workshop.jsx');
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end) + '\nglobalThis.card = openShownWorkflowAsNodes;', context);
  assert.equal(typeof context.card, 'function', 'openShownWorkflowAsNodes is a slice of studio-workshop.jsx');
  return context.card;
}

// ── caller: the workflow card opens ITS workflow (a member focus), walking that scope ──
test('the workflow-card handler opens its own workflow with a member focus', async () => {
  const card = loadCard();
  const opened = [], reveals = []; let focused = null, mode = null, err = null;
  const ok = await card(WORKFLOW, { authority:null, scopeOpen:async p => opened.push(...p),
    requestCanvasReveal:ids => reveals.push(ids), setFocusId:id => focused = id, setMode:m => mode = m, setError:e => err = e });
  assert.equal(ok, true);
  assert.deepEqual(opened, ['app:map-domain', 'app:workshop-workbench'], 'the workflow scope is walked');
  assert.deepEqual(reveals, [['assembly-instance:wf']], 'Open as nodes emits exactly one reveal request with workflow members');
  assert.equal(focused, 'assembly-instance:wf', 'a workflow member is focused, not a selection');
  assert.equal(mode, 'canvas');
  assert.equal(err, null);
});

// ── caller: the card walks ITS workflow's scope, never a selection; a null workflow just switches ──
test('the workflow-card handler walks its own workflow scope and ignores selection', async () => {
  const card = loadCard();
  let mode = null, walked = false;
  // No shown workflow: no card is rendered in this case, and calling with null just switches
  // (focus '' -> canvas) and walks nothing. (It does not and need not "refuse".)
  const ok = await card(null, { authority:null, scopeOpen:async () => { walked = true; },
    setFocusId:()=>{}, setMode:m => mode = m, setError:()=>{} });
  assert.equal(ok, true); // no workflow -> focus '' -> switches (same as a plain open)
  assert.equal(walked, false, 'no scope is walked without a shown workflow');
  // With a shown workflow, the walked scope is THAT workflow's, regardless of any ambient selection.
  const other = {root:'assembly-instance:other', scope:'app:workshop-workbench',
    members:['assembly-instance:other'], scope_path:['app:map-domain', 'app:workshop-workbench']};
  const steps = [];
  await card(other, { authority:null, scopeOpen:async p => steps.push(...p), setFocusId:()=>{}, setMode:()=>{}, setError:()=>{} });
  assert.deepEqual(steps, other.scope_path, 'the card walks the shown workflow scope, never a selection');
});

// ── wfAct refreshes the topology after an accepted mutation (stale-snapshot root cause) ──
test('wfAct refreshes topology after an accepted workflow mutation', () => {
  const start = source.indexOf('const wfAct = async');
  const body = source.slice(start, source.indexOf('};', start));
  assert.ok(start > 0, 'wfAct is in studio-workshop.jsx');
  assert.match(body, /workshopWorkflow\(descriptor\.root, action, fields\)/, 'it still performs the mutation');
  assert.match(body, /refreshTopologyCanvas\(\)/, 'it refreshes topology after the accepted mutation');
});

// ── refresh+verify: after the walk the member must be in the fresh snapshot before switching ──
test('a refreshed snapshot missing the member is refused without switching', async () => {
  const open = loadHelper();
  let mode = null, err = null;
  const ok = await open({focus:'assembly-instance:wf', workflow:WORKFLOW, authority:null,
    scopeOpen:async () => ({scope:{current:'app:workshop-workbench'}, nodes:[]}),
    refreshTopology:async () => ({scope:{current:'app:workshop-workbench'}, nodes:[{id:'someone-else'}]}),
    currentScope:() => 'app:workshop-workbench',
    setFocusId:()=>{}, setMode:m => mode = m, setError:e => err = e});
  assert.equal(ok, false);
  assert.equal(mode, null, 'no switch when the member is absent after refresh');
  assert.match(err, /not on this canvas yet/);
});

// ── epoch: a refresh that resolves after the view moved never overwrites it ──
test('a stale refresh resolving after a view change is ignored', async () => {
  const open = loadHelper();
  let mode = null;
  const ok = await open({focus:'assembly-instance:wf', workflow:WORKFLOW, authority:null,
    scopeOpen:async () => ({scope:{current:'app:workshop-workbench'}, nodes:[{id:'assembly-instance:wf'}]}),
    refreshTopology:async () => ({scope:{current:'app:workshop-workbench'}, nodes:[{id:'assembly-instance:wf'}]}),
    currentScope:() => 'app:moved-elsewhere',   // the person navigated away during the async refresh
    setFocusId:()=>{}, setMode:m => mode = m, setError:()=>{}});
  assert.equal(ok, false);
  assert.equal(mode, null, 'the stale refresh does not switch a changed view');
});

// ── MOUNTED regression: a real WorkshopView render; clicking the drawn card ⌗ walks ITS workflow ──
const WF_SCOPE_PATH = ['gm:domain:brain', 'app:workshop-workbench'];
const WORKFLOW_STATE = () => {
  const room = 'app:workshop:conversation:room';
  const wf = {root:'assembly-instance:wf', scope:'app:workshop-workbench', members:['assembly-instance:m1'],
    scope_path:WF_SCOPE_PATH, nodes:[{root:'assembly-instance:m1', title:'Step one', engine:'library.think', params:{}}],
    wires:0, edges:[], digest:'dg', approval:null, proposed_by:'agent-a', source_message:'no-such-message',
    title:'My Workflow', conversation:room};
  return {state:{workshop:{root:room, workflows:[wf], messages:[], participants:[], self:'owner', can_send:true,
      can_manage_history:false, has_older:false, next_before:null, total:0, activity:[]},
      canvas:{root:'app:workshop-workbench', graph_id:'graph-a'}, nativeWork:null},
    descriptor:{root:room, label:'Room', native_work_available:false}};
};

async function mountWorkshop(sel) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window;
  global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const openCalls = [], modes = [], focuses = [], reveals = [];
  win.AH = new Proxy({onFill:'#000'}, {get:(t,k)=> k in t ? t[k] : 'token-' + String(k)});
  win.ArchHubTheme = undefined;
  // The fresh topology snapshot the card verifies after the scope walk: the workflow member
  // drawn at the workflow's own scope.
  const FRESH = {scope:{current:'app:workshop-workbench', trail:[{root:'app:root'}]},
    nodes:[{id:'assembly-instance:m1'}], authorization:{}};
  let refreshes = 0;
  win.ARCHHUB_STUDIO_AUTHORITY = new Proxy({
    open: async step => { openCalls.push(step); return {scope:{current:step, trail:[{root:'app:root'}]}, nodes:[{id:'assembly-instance:m1'}]}; },
    load: async () => ({scope:{current:'app:root', trail:[{root:'app:root'}]}, nodes:[]}),
    refreshTopologyCanvas: async () => { refreshes += 1; return FRESH; },
    // The REAL owner shape (studio-existing-workshop.js publish): snapshot.canvas is the Workshop
    // DESCRIPTOR; the universal projection with scope.current is at snapshot.topology.canvas.
    getSnapshot: () => ({canvas: {root:'app:workshop:conversation:room', graph_id:'graph-a'}, topology: {canvas: FRESH}}),
  }, {get(t,k){ if (k in t) return t[k]; if (typeof k === 'string') return async () => ({}); return undefined; }});
  win.ARCHHUB_SCOPE_OPEN = async p => { for (const s of p) openCalls.push(s); };
  win.ARCHHUB_LOAD_HOSTS = async () => ({hosts:[]});
  win.ARCHHUB_CONVERSATION_RETENTION = async () => ({});
  const context = vm.createContext({React, window:win, document:win.document, globalThis:win,
    setTimeout, clearTimeout, setInterval, clearInterval, console, JSON, Date, Math, Object, Array, String, Number, Boolean});
  vm.runInContext(transformSync(source, {loader:'jsx'}).code, context);
  const WorkshopView = win.WorkshopView;
  assert.equal(typeof WorkshopView, 'function', 'window.WorkshopView is defined by the shipped module');
  const root = createRoot(win.document.getElementById('root'));
  const {state, descriptor} = WORKFLOW_STATE();
  try {
    await React.act(async () => root.render(React.createElement(WorkshopView, {
      state, descriptor, target:'', setTarget(){}, setMode:m => modes.push(m),
      setFocusId:id => focuses.push(id), requestCanvasReveal:ids => reveals.push(ids), onLeave(){}, sel, setSel(){}, externalRail:false})));
    await React.act(async () => { await new Promise(r => setTimeout(r, 0)); });
    const card = win.document.querySelector('[data-workshop-workflow]');
    assert.ok(card, 'the workflow card is drawn');
    const btn = [...card.querySelectorAll('button')].find(b =>
      /open as nodes/i.test((b.getAttribute('title') || '') + ' ' + (b.getAttribute('aria-label') || '') + ' ' + b.textContent));
    assert.ok(btn, 'the card has an Open-as-nodes control');
    await React.act(async () => { btn.click(); await new Promise(r => setTimeout(r, 0)); });
    return {openCalls, modes, focuses, reveals, refreshes};
  } finally {
    await React.act(async () => root.unmount());
    win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT;
  }
}

test('MOUNTED: the drawn card ⌗ walks the shown workflow, refreshes topology, then focuses', async () => {
  const {openCalls, modes, focuses, reveals, refreshes} = await mountWorkshop({agent:null, task:null});
  assert.deepEqual(openCalls, WF_SCOPE_PATH, 'the card walked the workflow scope path');
  assert.ok(refreshes >= 1, 'it refreshed the topology before focus (so the member is in the snapshot)');
  assert.deepEqual(reveals, [['assembly-instance:m1']], 'the mounted card emits exactly one reveal request carrying member ids');
  assert.ok(modes.includes('canvas'), 'it switched to the canvas');
  assert.ok(focuses.includes('assembly-instance:m1'), 'it focused a workflow member');
});

test('MOUNTED: the drawn card ⌗ walks the shown workflow even with an unrelated Work selected', async () => {
  const {openCalls, modes, refreshes} = await mountWorkshop({agent:null, task:'assembly-instance:unrelated-work'});
  assert.deepEqual(openCalls, WF_SCOPE_PATH, 'an unrelated selection never redirects the card');
  assert.ok(refreshes >= 1);
  assert.ok(modes.includes('canvas'));
});

// ── OWNER: a stale topology read must not publish across navigation, incl. away-and-back / identity ──
function ownerUnderTest(held) {
  const adapter = fs.readFileSync(path.join(path.dirname(file), 'studio-existing-workshop.js'), 'utf8');
  const ctx = vm.createContext({URLSearchParams, TextEncoder, JSON, Math, Object, Array, String, Number, Boolean, Promise});
  vm.runInContext(adapter, ctx);
  const ref = {release: null};
  const api = ctx.ArchHubExistingWorkshop.create({
    uuid:() => 'id', pendingStorage:{getItem:() => null, setItem:() => {}},
    get:async () => new Promise(res => { ref.release = () => res(held); }),
    post:async () => ({})});
  return {api, ref};
}
const CANVAS_AT = (scope, rev, subject = 'owner', session = 'view') => ({ok:true, application_root:'app',
  revision:rev, authorization:{subject, session}, scope:{current:scope, trail:[{root:'app:canvas'}]},
  nodes:[], wires:[], interaction_projection:{revision:rev, bindings:[]}});

test('OWNER a stale read does not publish across an away-and-back navigation', async () => {
  // Away-and-back returns to the starting scope, so scope/revision comparison is fooled.
  const {api, ref} = ownerUnderTest(CANVAS_AT('app:canvas', 3));   // the OLD read, held
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 2));   // start at the workbench
  const reading = api.refreshTopologyCanvas();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(typeof ref.release, 'function', 'the read reached get()');
  api.setTopologyCanvas(CANVAS_AT('app:other-scope', 3));          // away ...
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 3));   // ... and back, same revision
  ref.release();                                                   // old app:canvas read resolves now
  await reading.catch(() => {});
  assert.equal(api.getSnapshot().topology.canvas.scope.current, 'app:workshop-workbench',
    'away-and-back: the stale read must not overwrite the view');  // RED (pristine and the scope-guard): 'app:canvas'
});

test('OWNER a stale read does not publish across a same-scope identity change', async () => {
  const {api, ref} = ownerUnderTest(CANVAS_AT('app:workshop-workbench', 3, 'owner-a'));
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 2, 'owner-a'));
  const reading = api.refreshTopologyCanvas();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(typeof ref.release, 'function');
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 3, 'owner-b'));  // same scope, new identity
  ref.release();
  await reading.catch(() => {});
  assert.equal(api.getSnapshot().topology.canvas.authorization.subject, 'owner-b',
    'the read from the old identity must not overwrite the new one');
});

test('OWNER a fresher same-view read still publishes (liveness: the new member must appear)', async () => {
  // The refresh after an accepted draft returns a higher revision of the SAME view carrying the new
  // member node; it must publish, not be dropped as if it were a navigation.
  const fresh = CANVAS_AT('app:workshop-workbench', 4);
  fresh.nodes = [{id:'assembly-instance:new-member'}];
  const {api, ref} = ownerUnderTest(fresh);                        // fresh rev4 with the new node, held
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 2));   // start
  const reading = api.refreshTopologyCanvas();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(typeof ref.release, 'function');
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 3));   // same view, newer revision (NOT a navigation)
  ref.release();                                                   // the fresh rev4 read resolves
  await reading.catch(() => {});
  const snap = api.getSnapshot();
  assert.equal(snap.topology.canvas.revision, 4, 'the fresher same-view read must publish');
  assert.ok(snap.topology.canvas.nodes.some(n => n.id === 'assembly-instance:new-member'),
    'the new member node is present after the refresh');
});

test('OWNER a same-identity older read is dropped (revision ordering)', async () => {
  const {api, ref} = ownerUnderTest(CANVAS_AT('app:workshop-workbench', 3));   // older rev3, same identity
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 5));               // held rev5
  const reading = api.refreshTopologyCanvas();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(typeof ref.release, 'function');
  ref.release();
  await reading.catch(() => {});
  assert.equal(api.getSnapshot().topology.canvas.revision, 5, 'the older same-identity read is dropped');
});

test('OWNER a different-identity response is accepted even at a lower revision', async () => {
  // A refresh-driven identity transition: no local navigation, the response is another identity at a
  // LOWER revision. Revisions across identities are not comparable, so it must still publish.
  const {api, ref} = ownerUnderTest(CANVAS_AT('app:workshop-workbench', 1, 'owner-b', 'session-b'));
  api.setTopologyCanvas(CANVAS_AT('app:workshop-workbench', 100, 'owner-a', 'session-a'));   // held, high rev
  const reading = api.refreshTopologyCanvas();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(typeof ref.release, 'function');
  ref.release();   // no setTopologyCanvas between: no local navigation
  await reading.catch(() => {});
  assert.equal(api.getSnapshot().topology.canvas.authorization.subject, 'owner-b',
    'the identity transition published despite a lower revision');   // RED against the unconditional drop
});

// ── RUNTIME: an accepted workflow action with a failed refresh keeps the receipt, no second POST ──
async function mountForApprove() {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  const win = dom.window;
  global.window = win; global.document = win.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const posts = []; const errors = [];
  win.AH = new Proxy({onFill:'#000'}, {get:(t,k)=> k in t ? t[k] : 'token-' + String(k)});
  win.ArchHubTheme = undefined; win.ARCHHUB_LOAD_HOSTS = async () => ({hosts:[]});
  win.ARCHHUB_CONVERSATION_RETENTION = async () => ({});
  win.ARCHHUB_STUDIO_AUTHORITY = new Proxy({
    workshopWorkflow: async (root, action) => { posts.push(action); return {ok:true}; },  // the one accepted POST
    refreshTopologyCanvas: async () => { throw new Error('refresh boom'); },              // the refresh fails
    getSnapshot: () => ({canvas:{root:'r'}, topology:{canvas:{scope:{current:'app:workshop-workbench'}, nodes:[]}}}),
  }, {get(t,k){ if (k in t) return t[k]; if (typeof k === 'string') return async () => ({}); return undefined; }});
  const context = vm.createContext({React, window:win, document:win.document, globalThis:win,
    setTimeout, clearTimeout, setInterval, clearInterval, console, JSON, Date, Math, Object, Array, String, Number, Boolean});
  vm.runInContext(transformSync(source, {loader:'jsx'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  const {state, descriptor} = WORKFLOW_STATE();
  try {
    await React.act(async () => root.render(React.createElement(win.WorkshopView, {
      state, descriptor, target:'', setTarget(){}, setMode(){}, setFocusId(){}, onLeave(){},
      sel:{agent:null, task:null}, setSel(){}, externalRail:false})));
    await React.act(async () => { await new Promise(r => setTimeout(r, 0)); });
    const btn = [...win.document.querySelectorAll('[data-workshop-workflow] button')]
      .find(b => /approve/i.test(b.textContent));
    assert.ok(btn, 'the awaiting workflow card shows an Approve button');
    await React.act(async () => { btn.click(); await new Promise(r => setTimeout(r, 0)); });
    const alert = win.document.querySelector('[role="alert"]');
    if (alert) errors.push(alert.textContent);
    return {posts, errors};
  } finally {
    await React.act(async () => root.unmount());
    win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT;
  }
}

test('RUNTIME an accepted workflow action with a failed refresh keeps the receipt and never re-POSTs', async () => {
  const {posts, errors} = await mountForApprove();
  assert.deepEqual(posts, ['workflow-approve'], 'exactly one accepted mutation POST, no replay after the failed refresh');
  assert.deepEqual(errors, [], 'the accepted action is not reported as failed when only the refresh threw');
});

async function mountCanvasReveal(options = {}) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const lmSource = fs.readFileSync(path.join(path.dirname(file), 'studio-lm.jsx'), 'utf8');
  const start = lmSource.indexOf('const SOCKET_TOP =');
  const end = lmSource.indexOf('const NodeStateDot =', start);
  assert.ok(start > 0 && end > start, 'NodeCanvas is a slice of shipped studio-lm.jsx');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53913/'});
  let measurable = options.measurable !== false;
  Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetWidth', {configurable:true, get() { return measurable ? 220 : 0; }});
  Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetHeight', {configurable:true, get() { return measurable ? 110 : 0; }});
  dom.window.HTMLElement.prototype.getBoundingClientRect = function() {
    return this.getAttribute('role') === 'region'
      ? {width:1000, height:760, left:0, top:0, right:1000, bottom:760}
      : {width:220, height:110, left:0, top:0, right:220, bottom:110};
  };
  const pendingFrames = new Set();
  dom.window.requestAnimationFrame = fn => {
    const id = dom.window.setTimeout(() => { pendingFrames.delete(id); fn(); }, 0);
    pendingFrames.add(id);
    return id;
  };
  dom.window.cancelAnimationFrame = id => { pendingFrames.delete(id); dom.window.clearTimeout(id); };
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const nodes = [
    {id:'m1', cat:'logic', live:true, x:40, y:60, w:220, h:110, title:'One', sub:'node', params:[], ins:[], outs:[], group:'G'},
    {id:'m2', cat:'logic', live:true, x:40, y:520, w:220, h:110, title:'Two', sub:'node', params:[], ins:[], outs:[], group:'G'},
  ];
  const snapshot = {graph:{nodes, wires:[]}, canvas:{revision:1, scope:{current:options.scope || 'scope'}, authorization:{subject:'owner', session:'s'}}};
  const LM = new Proxy({}, {get:(_, key) => key === 'rad' ? {xs:3, sm:5, md:6, lg:8} :
    key === 'sp' ? {xs:4, sm:8, md:12, lg:16} : 'token-' + String(key)});
  const studioCanvasScopeMock = canvas => canvas?.scope?.current || 'scope';
  const context = vm.createContext({React, LM, window:dom.window, document:dom.window.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope',
    studioCategory:cat => ({col:'token-cat', icon:'+', label:String(cat).toUpperCase()}), WIRE:{},
    NodeBody:() => null, CanvasToolbar:() => null, FloatingComposer:() => null, MiniMap:() => null, Socket:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({}),
    setTimeout:dom.window.setTimeout.bind(dom.window), clearTimeout:dom.window.clearTimeout.bind(dom.window)});
  vm.runInContext(transformSync(lmSource.slice(start, end) + '\nglobalThis.NodeCanvas = NodeCanvas;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(dom.window.document.getElementById('root'));
  let props = {focusId:null, setFocusId:() => {}, pendingReveal:null, clearPendingReveal:() => {},
    setLibraryOpen:() => {}, userNodes:[], addNodeFromLibrary:() => {}, model:null};
  const render = async change => {
    props = {...props, ...change};
    await React.act(async () => root.render(React.createElement(context.NodeCanvas, {...props, key:studioCanvasScopeMock(snapshot.canvas)})));
  };
  const setScope = async scope => { snapshot.canvas = {...snapshot.canvas, scope:{current:scope}}; await render(); };
  const setMeasurable = value => { measurable = value; };
  const settle = async () => { await React.act(async () => { await new Promise(r => dom.window.setTimeout(r, 5)); }); };
  await render();
  return {doc:dom.window.document, render, settle, setScope, setMeasurable, pendingFrames, close:async () => {
    await React.act(async () => root.unmount());
    dom.window.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT;
  }};
}

test('NodeCanvas consumes a pending reveal once; plain focus does not fit', async () => {
  const view = await mountCanvasReveal();
  try {
    const region = view.doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
    const layer = () => region.firstElementChild.style.transform;
    const baseline = layer();
    await view.render({focusId:'m1'});
    await view.settle();
    assert.equal(layer(), baseline, 'plain focus change does not fit or pan');
    let clears = 0;
    await view.render({pendingReveal:{ids:['m1', 'm2'], at:1}, clearPendingReveal:() => { clears += 1; }});
    await view.settle();
    assert.equal(clears, 1, 'pending reveal clears once after fitting');
    const fitted = layer();
    assert.notEqual(fitted, baseline, 'pending reveal uses the fit path');
    await view.render({focusId:'m2'});
    await view.settle();
    assert.equal(clears, 1, 'later focus changes do not consume another reveal');
    assert.equal(layer(), fitted, 'later focus changes do not move the viewport');
  } finally {
    await view.close();
  }
});

test('NodeCanvas clears a stale pending reveal across a scope remount without panning', async () => {
  const view = await mountCanvasReveal({scope:'scope-a', measurable:false});
  let closed = false;
  try {
    const region = view.doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
    const layer = () => region.firstElementChild.style.transform;
    let clears = 0;
    await view.render({pendingReveal:{ids:['m1', 'm2'], at:2}, clearPendingReveal:() => { clears += 1; }});
    await view.setScope('scope-b');
    const scopeBaseline = layer();
    for (let i = 0; i < 12; i += 1) await view.settle();
    assert.equal(layer(), scopeBaseline, 'scope B does not pan for the stale reveal');
    assert.equal(clears, 1, 'the stale reveal request is cleared by timeout');
    await view.close();
    closed = true;
    assert.equal(view.pendingFrames.size, 0, 'unmount leaves no reveal animation frame running');
  } finally {
    if (!closed) await view.close();
  }
});

// ── wiring: the workflow card's ⌗ binds openShownWorkflowAsNodes(shownWorkflow), not openAsNodes ──
test('the workflow card button is wired to its own workflow, not the generic handler', () => {
  const card = source.slice(source.indexOf('const workflowProposalCard'), source.indexOf('// The proposed workflow answers'));
  assert.ok(card.length > 0, 'the workflow card is a slice of studio-workshop.jsx');
  const openBtn = card.slice(card.indexOf('data-workshop-workflow-chip'));
  assert.match(openBtn, /openShownWorkflowAsNodes\(shownWorkflow/, 'the card ⌗ opens its own shownWorkflow');
  assert.ok(!/onClick=\{openAsNodes\}/.test(openBtn), 'the card ⌗ must not use the generic openAsNodes');
});
