const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {transformSync} = require('esbuild');
const read = name => fs.readFileSync('nodelang/studio/' + name, 'utf8');

test('UIFIX: persistent rail and status survive every destination and a delayed Workshop load', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react'), {createRoot} = require('react-dom/client');
  const dom = new JSDOM('<div id="root"></div>', {pretendToBeVisual:true});
  const previous = {window:global.window, document:global.document};
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const context = vm.createContext({React, window:dom.window, document:dom.window.document,
    useWorkshopProjection:() => ({}), workshopWaitingItems:() => []});
  vm.runInContext(read('tokens.jsx'), context);
  context.LM = dom.window.AH;
  vm.runInContext(transformSync(read('shared-data.jsx'), {loader:'jsx'}).code, context);
  const source = read('studio-lm.jsx');
  vm.runInContext(transformSync(source.slice(source.indexOf('// DSYS-060 app frame parts.'), source.indexOf('const CommandBar = (')) +
    source.slice(source.indexOf('const LazyWorkshopWindow ='), source.indexOf('const Workspace =')) +
    '\nglobalThis.Frame=Frame; globalThis.LazyWorkshopWindow=LazyWorkshopWindow;', {loader:'jsx'}).code, context);
  let release;
  dom.window.ARCHHUB_LOAD_WORKSHOP = () => new Promise(resolve => { release = resolve; });
  const root = createRoot(dom.window.document.getElementById('root'));
  const render = (rail, workshopWindow=false, child=null) => React.act(async () => root.render(React.createElement(context.Frame,
    {rail, workshopWindow, status:React.createElement('span', {'data-test-status':''}, 'Connected')}, child)));
  try {
    await render('Home');
    const rail = dom.window.document.querySelector('[data-app-rail]');
    const status = dom.window.document.querySelector('[data-test-status]');
    for (const destination of ['Workshop','Canvas','Library','Settings','Home']) {
      await render(destination, destination === 'Workshop', destination === 'Workshop' ? React.createElement(context.LazyWorkshopWindow) : null);
      assert.equal(dom.window.document.querySelector('[data-app-rail]'), rail, destination + ' retains the same rail DOM node');
      assert.equal(dom.window.document.querySelector('[data-test-status]'), status, destination + ' retains status DOM node');
      if (destination === 'Workshop') {
        assert.ok(dom.window.document.querySelector('[data-workspace-frame] [data-workshop-loading]'));
        await React.act(async () => release(() => React.createElement('main', {'data-loaded-workshop':''}, 'Workshop')));
        assert.equal(dom.window.document.querySelector('[data-app-rail]'), rail);
      }
    }
  } finally {
    await React.act(async () => root.unmount()); dom.window.close(); Object.assign(global, previous);
  }
});

test('UIFIX: mounted Workshop shows one named live agent from 1 live and 30 dead runtimes', async () => {
  const {fixture} = require('./workshop72_fixture.cjs');
  const {mounted} = require('./workshop72_regression_helpers.cjs');
  const f = fixture(), now = Date.now() / 1000;
  f.state.workshop.participants = [{root:'live',label:'Runtime-aabbccdd',is_agent:true,attached:true,
    runtime:'claude-code', connection_status:'connected', connection_basis:'authenticated-request',observed_at:now,expires_at:now+60},
    ...Array.from({length:30}, (_, i) => ({root:'dead-'+i,label:'Runtime-'+i,is_agent:true,attached:true,
      runtime:'codex',connection_status:'disconnected',observed_at:now-1000,expires_at:now-500}))];
  const ui = await mounted(f.state, f.authority);
  try {
    const rows = [...ui.doc.querySelector('[data-workshop-agents]').children];
    assert.equal(rows.length, 1);
    assert.match(rows[0].textContent, /Claude Code/);
    assert.doesNotMatch(ui.doc.querySelector('[data-workshop-agents]').textContent, /Runtime-|disconnected/);
  } finally {await ui.close();}
});

test('UIFIX: existing store retires dead roster rows on full and unchanged pages without losing history', async () => {
  const {transport} = require('./workshop72_regression_helpers.cjs');
  const f = transport();
  const now = Date.now() / 1000;
  const live = {root:'live', label:'Codex', attached:true, is_agent:true, runtime:'codex',
    connection_status:'connected', connection_basis:'authenticated-request', observed_at:now, expires_at:now+60};
  f.transcript.participants = [live, ...Array.from({length:30}, (_, i) => ({...live, root:'dead-'+i,
    label:'Runtime-'+i, connection_status:'disconnected', expires_at:now-1}))];
  f.transcript.messages = [{root:'historic', sender_root:'dead-1', body:'Retained history'}];
  await f.api.openWorkshop('room-a');
  assert.equal(f.api.getSnapshot().workshop.participants.length, 1);
  assert.equal(f.api.getSnapshot().workshop.messages[0].sender_root, 'dead-1');
  f.transcript.unchanged = true;
  f.transcript.participants = [{...live, connected:true, expires_at:now-1}];
  await f.api.refreshWorkshop('room-a');
  assert.equal(f.api.getSnapshot().workshop.participants.length, 0);
  assert.equal(f.api.getSnapshot().workshop.messages[0].body, 'Retained history');
});

test('UIFIX: actual Studio rail clicks retain DOM identity while canvas and Workshop are deliberately delayed', async () => {
  // Reuse the existing app harness without registering its courts a second time.
  const Module = require('node:module'), path = require('node:path');
  const filename = path.join(__dirname, 'studio_workshop_open.test.cjs');
  const harness = new Module(filename, module); harness.filename = filename; harness.paths = module.paths;
  const source = fs.readFileSync(filename, 'utf8');
  harness._compile(source.slice(0, source.indexOf("\ntest('")) + '\nmodule.exports={mountStudio};', filename);
  const ui = await harness.exports.mountStudio({workshops:[{root:'room-a',label:'Workshop',is_general:true}]});
  const rail = ui.doc.querySelector('[data-app-rail]'), status = ui.doc.querySelector('[data-app-status]');
  const originalWorkshop = ui.win.WorkshopView;
  let releaseCanvas, releaseWorkshop;
  ui.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.canvas.canvas_deferred = true;
  ui.win.ARCHHUB_LOAD_CANVAS = () => new Promise(resolve => {releaseCanvas = resolve;});
  ui.win.WorkshopView = undefined;
  ui.win.ARCHHUB_LOAD_WORKSHOP = () => new Promise(resolve => {releaseWorkshop = resolve;});
  const settle = async () => {for(let i=0;i<8;i++) await new Promise(resolve => ui.win.setTimeout(resolve,0));};
  const click = async name => {ui.flush(() => rail.querySelector(`[aria-label="${name}"]`).click()); await settle();
    assert.equal(ui.doc.querySelector('[data-app-rail]'),rail,name);
    assert.equal(ui.doc.querySelector('[data-app-status]'),status,name);
    assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length,1,name);};
  try {
    await click('Canvas');
    assert.ok(ui.doc.querySelector('[data-workspace-canvas-loading]'));
    ui.flush(() => releaseCanvas()); await settle();
    await click('Workshop');
    assert.ok(ui.doc.querySelector('[data-workspace-frame] [data-workshop-loading]'));
    ui.flush(() => releaseWorkshop(originalWorkshop)); await settle();
    assert.ok(ui.doc.querySelector('[data-workshop72]'));
    for(const name of ['Settings','Library','Canvas','Home','Workshop','Settings','Home']) await click(name);
    assert.equal(ui.doc.querySelectorAll('[data-app-status]').length,1);
  } finally {ui.close();}
});
