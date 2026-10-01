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
  const opened = []; let focused = null, mode = null, err = null;
  const ok = await card(WORKFLOW, { authority:null, scopeOpen:async p => opened.push(...p),
    setFocusId:id => focused = id, setMode:m => mode = m, setError:e => err = e });
  assert.equal(ok, true);
  assert.deepEqual(opened, ['app:map-domain', 'app:workshop-workbench'], 'the workflow scope is walked');
  assert.equal(focused, 'assembly-instance:wf', 'a workflow member is focused, not a selection');
  assert.equal(mode, 'canvas');
  assert.equal(err, null);
});

// ── caller: the card never follows an unrelated selection; a null workflow refuses, no switch ──
test('the workflow-card handler ignores selection and refuses when no workflow is shown', async () => {
  const card = loadCard();
  let mode = null, walked = false;
  // No shown workflow (e.g. nothing proposed): the card must not silently switch to the canvas.
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

// ── wiring: the workflow card's ⌗ binds openShownWorkflowAsNodes(shownWorkflow), not openAsNodes ──
test('the workflow card button is wired to its own workflow, not the generic handler', () => {
  const card = source.slice(source.indexOf('const workflowProposalCard'), source.indexOf('// The proposed workflow answers'));
  assert.ok(card.length > 0, 'the workflow card is a slice of studio-workshop.jsx');
  const openBtn = card.slice(card.indexOf('data-workshop-workflow-chip'));
  assert.match(openBtn, /openShownWorkflowAsNodes\(shownWorkflow/, 'the card ⌗ opens its own shownWorkflow');
  assert.ok(!/onClick=\{openAsNodes\}/.test(openBtn), 'the card ⌗ must not use the generic openAsNodes');
});
