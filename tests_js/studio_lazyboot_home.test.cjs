'use strict';
/* Current Studio source in the existing JSDOM mount pattern. The graph metadata
   is an exported boot-court projection when supplied, otherwise the captured
   server projection; catalogue rows come from the real Python
   catalogue. Requests are fakes: no host, browser, app or network is launched. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const html = read('nodelang/studio/studio.html');
const start = html.indexOf('    let nodeLibrary = {};');
const end = html.indexOf('    function projectStudioCanvas', start);
const loader = html.slice(start, end);
const projectionEnd = html.indexOf('    const {nodes, wires} = window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph;', end);
assert.ok(projectionEnd > end, 'canvas loader declarations end before the authenticated owner read');
const bootstrap = html.slice(start, projectionEnd);
const frameStart = html.indexOf("    const canvas = await jget('/api/universal/canvas?screen=home');");
const frameEnd = html.indexOf('    let hosts = [], connectors = [];', frameStart);
assert.ok(frameStart > 0 && frameEnd > frameStart, 'Home uses the lightweight authenticated selector');
const frameBootstrap = html.slice(frameStart, frameEnd);
const indexStart = html.indexOf("    const graphIndex = await jget('/api/universal/graphs?screen=home');", projectionEnd);
const indexEnd = html.indexOf('    await mountStudio();', indexStart);
assert.ok(indexStart > 0 && indexEnd > indexStart);
const indexBootstrap = html.slice(indexStart, indexEnd);
const canvasReport = process.env.LAZYBOOT_CANVAS_REPORT;
const canvasBytes = canvasReport
  ? fs.readFileSync(path.resolve(root, canvasReport), 'utf8')
  : read('tests_js/fixtures/clean-canvas-fresh-runtime.json');
const captured = JSON.parse(canvasBytes);
const workspaceReport = process.env.LAZYBOOT_WORKSPACE_REPORT;
const workspaceBytes = workspaceReport ? fs.readFileSync(path.resolve(root, workspaceReport), 'utf8') : canvasBytes;
const workspaceCaptured = JSON.parse(workspaceBytes);
const graphReport = process.env.LAZYBOOT_GRAPH_REPORT;
const graphBytes = graphReport ? fs.readFileSync(path.resolve(root, graphReport), 'utf8') : null;
const homeGraphs = graphBytes ? JSON.parse(graphBytes) : {
  graphs:[{id:captured.canvas_root || captured.graph_id, title:'Captured graph', state:'idle'}],
  current_graph:captured.canvas_root || captured.graph_id};
assert.ok(Array.isArray(homeGraphs.graphs) && homeGraphs.graphs.length > 0 && homeGraphs.current_graph,
  'the authenticated Home graph metadata offers its current graph');
if (canvasReport) {
  assert.ok(Number.isInteger(captured.revision), 'exported boot projection has a revision');
  assert.ok(captured.application_root && captured.canvas_root && captured.scope?.current,
    'exported boot projection retains its application, canvas and scope identities');
  assert.ok(Array.isArray(captured.nodes) && Array.isArray(captured.wires),
    'exported boot projection has actual node and wire rows');
  assert.equal(captured.canvas_deferred, true, 'the exported Home frame defers its canvas');
  assert.equal(captured.nodes.length, 0);
  assert.equal(captured.wires.length, 0);
  assert.ok(workspaceReport, 'a Home-frame bridge must also supply the original first-Workspace projection');
  assert.ok(graphReport, 'a Home-frame bridge must supply the actual metadata-only graph index');
  assert.equal(workspaceCaptured.application_root, captured.application_root);
  assert.equal(workspaceCaptured.scope.current, captured.scope.current, 'first Workspace preserves the saved scope');
  assert.ok(Array.isArray(workspaceCaptured.nodes) && Array.isArray(workspaceCaptured.wires));
  assert.notEqual(workspaceCaptured.canvas_deferred, true);
}
const Babel = {};
vm.runInNewContext(read('nodelang/studio/vendor/babel.js'), {exports:Babel, module:{exports:Babel}});
const lmCode = Babel.transform(read('nodelang/studio/studio-lm.jsx'), {
  presets:['react','env'], plugins:['transform-class-properties','transform-object-rest-spread','transform-flow-strip-types'],
  targets:{}, sourceMaps:false, filename:'/studio/studio-lm.jsx'}).code;
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(row => [row[1], row[2]]));
const served = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
  'import json; from nodelang.library_engines import library_catalogue, engine_categories; from nodelang.universal_pipeline import wire_parameter_specs; groups = library_catalogue(); print(json.dumps({"groups":groups,"categories":engine_categories(groups),"wire_parameters":wire_parameter_specs()}))'],
  {cwd:root, encoding:'utf8'}));
const groups = served.groups.map(group => ({...group, items:group.items.filter(item => item.hidden !== true)})).filter(group => group.items.length);
console.info('LAZYONREL_CATALOGUE_VISIBILITY ' + JSON.stringify({raw_ids:served.groups.flatMap(group => group.items.map(item => item.id)), visible_ids:groups.flatMap(group => group.items.map(item => item.id)), excluded:served.groups.flatMap(group => group.items.filter(item => item.hidden === true).map(item => ({id:item.id, reason:'hidden:true'})))}));
const visibleCount = groups.reduce((count, group) => count + group.items.length, 0);
assert.ok(visibleCount > 0, 'main has a nonempty verified catalogue');

async function mountStudio({rawCanvas = captured, fullCanvas = rawCanvas.canvas_deferred ? workspaceCaptured : rawCanvas, holdCanvas = false, coldWorkshop = false} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const libraryReads = [];
  const canvasReads = [];
  const requestUrls = [];
  let skillReads = 0;
  win.__libraryGet = url => {
    requestUrls.push(url);
    if (url === '/api/universal/canvas?screen=home') return Promise.resolve(canvas);
    if (url === '/api/universal/graphs?screen=home') return Promise.resolve(homeGraphs);
    if (url === '/api/universal/node-library?templates=1') return Promise.resolve({ok:true,templates:[]});
    if (url === '/api/universal/application-update') return new Promise(() => {});
    if (url === '/api/universal/canvas') {
      if (holdCanvas) return new Promise((resolve, reject) => canvasReads.push({
        resolve:value => resolve(canvasReport || !value ? value : adaptCleanCanvas(value)), reject}));
      canvasReads.push({});
      return Promise.resolve(canvasReport ? fullCanvas : adaptCleanCanvas(fullCanvas));
    }
    assert.equal(url, '/api/universal/node-library');
    return new Promise((resolve, reject) => libraryReads.push({resolve, reject}));
  };
  win.eval('(function(){ const jget = window.__libraryGet; const PARAM_SPECS = {};\n' + bootstrap +
    '\nwindow.__projectStudioCanvas = projectStudioCanvas; })();');
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:async () => ({ok:true, groups:[], selected_route:'', readiness:{state:'no_model'}})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:async () => ({ok:true, tools:[], stopped:false})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:async () => ({ok:true, items:[]})})
    : new Promise(() => {});
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_LOAD_SKILLS = async () => {skillReads += 1; return [];};
  const adaptCleanCanvas = value => ({...value,
    application_root:value.application_root || value.graph_id,
    authorization:{...value.authorization, session:value.authorization?.session || value.authorization?.browser_sessions?.[0]?.root}});
  // This existing clean-canvas test adapter names application/scope identities
  // graph_id/root. Add those aliases for the universal projection; retain every
  // original field and row from the boot court's JSON.
  const transportCanvas = {...rawCanvas,
    graph_id:rawCanvas.graph_id || rawCanvas.application_root,
    root:rawCanvas.root || rawCanvas.scope?.current || rawCanvas.canvas_root};
  const canvas = {...(canvasReport ? transportCanvas : adaptCleanCanvas(transportCanvas)),
    application_root:rawCanvas.application_root || transportCanvas.graph_id};
  assert.equal(canvas.revision, rawCanvas.revision, 'the bootstrap keeps the actual projection revision');
  assert.equal(canvas.nodes, rawCanvas.nodes, 'the bootstrap preserves the actual node rows');
  assert.equal(canvas.wires, rawCanvas.wires, 'the bootstrap preserves the actual wire rows');
  let topology = {canvas, graph:win.__projectStudioCanvas(canvas)};
  const listeners = new Set();
  const fakeOwner = {
    getSnapshot:() => ({canvas:topology.canvas, topology, workshops:[],
      theme:{configuration:topology.canvas.configuration},
      applicationUpdate:{state:'idle', current_build:'fixture'}}),
    subscribe:listener => {listeners.add(listener); return () => listeners.delete(listener);},
    watchApplicationUpdate:() => () => {},
    setTopologyCanvas:canvas => {
      assert.ok(canvas && Number.isInteger(canvas.revision) && Array.isArray(canvas.nodes) && Array.isArray(canvas.wires),
        'the canvas did not return its current graph interaction authority');
      topology = {...topology, canvas, graph:win.__projectStudioCanvas(canvas)};
      for (const listener of listeners) listener();
      return canvas;
    },
    setThemeCanvas:value => value,
  };
  if (canvasReport) win.eval(read('nodelang/studio/studio-existing-workshop.js'));
  else win.ArchHubExistingWorkshop = {create:() => fakeOwner};
  await win.eval('(async function(){ const jget = window.__libraryGet; const jpost = async()=>{throw new Error("Home mounting writes nothing.");}; const projectStudioCanvas=window.__projectStudioCanvas;\n' +
    frameBootstrap + '\nwindow.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas); })();');
  if (!canvasReport) win.ARCHHUB_THEME = {...seed};
  await win.eval('(async function(){ const jget=window.__libraryGet; const hosts=[], connectors=[]; const {nodes,wires}=window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph;\n' + indexBootstrap + '\n})();');
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) if (file.source !== 'mount.jsx' && (!coldWorkshop || !['workshop-board.jsx', 'studio-workshop.jsx'].includes(file.source))) win.eval(file.source === 'studio-lm.jsx' ? lmCode : read('nodelang/studio/compiled/' + file.output));
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async (predicate = () => true, note = 'settled') => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise(resolve => win.setTimeout(resolve, 5));
      if (predicate()) return;
    }
    assert.ok(predicate(), note);
  };
  const close = () => {try {flush(() => win.__studioRoot.unmount());} finally {dom.window.close();}};
  return {win, doc:win.document, libraryReads, canvasReads, requestUrls, skillReads:() => skillReads, flush, settle, close};
}

const button = (doc, text) => [...doc.querySelectorAll('button')].find(row => row.textContent.trim() === text);
const graphButton = doc => {
  doc.defaultView.ReactDOM.flushSync(() => doc.querySelector('[data-app-rail] [data-rail-panel="Chats"]').click());
  const graph = homeGraphs.graphs.find(row => row.id === homeGraphs.current_graph) || homeGraphs.graphs[0];
  assert.ok(graph.title, 'the graph index carries the existing graph title');
  const found = [...doc.querySelectorAll('[data-left-panel] button')].find(row => row.textContent.includes(graph.title));
  assert.ok(found, 'Chats renders the current graph from the authenticated metadata index');
  return found;
};

test('Home renders and its Nodes control responds before the first catalogue request finishes', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home rendered');
    assert.equal(studio.libraryReads.length, 0);
    assert.equal(studio.canvasReads.length, 0, 'Home does not request the original full canvas');
    assert.equal(studio.requestUrls.filter(url => url === '/api/universal/canvas?screen=home').length, 1);
    assert.equal(studio.requestUrls.filter(url => url === '/api/universal/graphs?screen=home').length, 1);
    assert.equal(studio.requestUrls.filter(url => url === '/api/universal/graphs').length, 0, 'Home never requests the full graph index');
    assert.equal(studio.skillReads(), 0);
    assert.ok(studio.doc.querySelector('[data-home-page] form'), 'Home composer is mounted');
    studio.flush(() => studio.doc.querySelector('[data-rail-panel="Library"]').click());
    await studio.settle(() => studio.libraryReads.length === 1, 'first Nodes open requests the catalogue');
    let panel = studio.doc.querySelector('[data-left-panel]');
    assert.match(panel.textContent, /(?:Loading|Reading) nodes/, 'first open shows pending state');
    studio.flush(() => studio.doc.querySelector('[data-app-rail] [data-rail-panel="Home"]').click());
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home responds while the catalogue remains unresolved');
    assert.equal(studio.libraryReads.length, 1, 'returning Home does not restart the pending read');
    studio.flush(() => studio.doc.querySelector('[data-rail-panel="Library"]').click());
    await studio.settle(() => {
      panel = studio.doc.querySelector('[data-left-panel]');
      return panel && /(?:Loading|Reading) nodes/.test(panel.textContent);
    }, 'Library reopens on the same pending catalogue');
    assert.equal(studio.libraryReads.length, 1, 'Library reopening reuses the pending read');
    studio.libraryReads[0].resolve(served);
    await studio.settle(() => !/(?:Loading|Reading) nodes/.test(panel.textContent), 'Nodes catalogue loaded');
    const input = panel.querySelector('input');
    assert.equal(input.placeholder, 'Search ' + visibleCount + ' nodes');
    studio.flush(() => {
      Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set.call(input, ' ');
      input.dispatchEvent(new studio.win.Event('input', {bubbles:true}));
    });
    await studio.settle(() => panel.querySelectorAll('[draggable="true"]').length === visibleCount, 'all real catalogue rows render');
    assert.equal(studio.libraryReads.length, 1);
    console.log('LAZYBOOT_HOME_RENDERED library_requests_at_home=0 first_nodes_requests=1 visible_catalogue_rows=' + visibleCount);
    console.log('LAZYBOOT_HOME_PROJECTION source=' + (canvasReport ? 'synthetic-boot-court' : 'captured-server') +
      ' sha256=' + createHash('sha256').update(canvasBytes).digest('hex') +
      ' revision=' + captured.revision + ' nodes=' + captured.nodes.length + ' wires=' + captured.wires.length);
    if (graphBytes) console.log('LAZYBOOT_HOME_GRAPHS source=synthetic-boot-court sha256=' +
      createHash('sha256').update(graphBytes).digest('hex') + ' full_graph_index_reads=0');
  } finally {studio.close();}
});

test('first Workspace opens the saved original canvas once after Home becomes interactive', async () => {
  const frame = {...captured, nodes:[], wires:[], canvas_deferred:true};
  const studio = await mountStudio({rawCanvas:frame, fullCanvas:workspaceCaptured, holdCanvas:true});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home rendered from frame');
    assert.equal(studio.canvasReads.length, 0);
    assert.equal(studio.libraryReads.length, 0);
    const session = graphButton(studio.doc);
    assert.ok(session, 'Home exposes the authenticated graph index');
    studio.flush(() => session.click());
    await studio.settle(() => studio.canvasReads.length === 1, 'Workspace requests the original projection');
    assert.ok(studio.doc.querySelector('[data-workspace-canvas-loading] [role="status"]'));
    const first = studio.win.ARCHHUB_LOAD_CANVAS();
    assert.equal(first, studio.win.ARCHHUB_LOAD_CANVAS(), 'concurrent first uses share the read');
    assert.equal(studio.libraryReads.length, 0, 'node/action catalogue waits for original canvas controls');
    studio.canvasReads[0].resolve(workspaceCaptured);
    await first;
    await studio.settle(() => studio.doc.querySelector('main:not([data-home-page]):not([data-workspace-canvas-loading])') && studio.libraryReads.length === 1, 'the original Workspace and catalogue mount');
    studio.libraryReads[0].resolve(served);
    const opened = studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.canvas;
    assert.equal(opened.revision, workspaceCaptured.revision);
    assert.equal(opened.nodes, workspaceCaptured.nodes, 'original full node rows remain intact');
    assert.equal(opened.wires, workspaceCaptured.wires, 'original full wire rows remain intact');
    assert.deepEqual(opened.scope, workspaceCaptured.scope, 'the stored scope remains unchanged');
    await studio.win.ARCHHUB_LOAD_CANVAS();
    assert.equal(studio.canvasReads.length, 1, 'later opens reuse the accepted full projection');
    console.log('LAZYBOOT_WORKSPACE_PROJECTION source=' + (workspaceReport ? 'synthetic-boot-court' : 'captured-server') +
      ' sha256=' + createHash('sha256').update(workspaceBytes).digest('hex') + ' full_canvas_reads=1');
  } finally {studio.close();}
});

for (const failure of ['refused', 'missing']) test('first Workspace ' + failure + ' projection remains a visible failure and Retry reads again', async () => {
  const studio = await mountStudio({rawCanvas:{...captured, nodes:[], wires:[], canvas_deferred:true}, fullCanvas:workspaceCaptured, holdCanvas:true});
  try {
    const session = graphButton(studio.doc);
    studio.flush(() => session.click());
    await studio.settle(() => studio.canvasReads.length === 1, 'first original canvas request');
    if (failure === 'refused') studio.canvasReads[0].reject(new Error('scope read refused'));
    else studio.canvasReads[0].resolve({revision:workspaceCaptured.revision, nodes:[]});
    await studio.settle(() => studio.doc.querySelector('[data-workspace-canvas-loading] [role="alert"]'), 'the refusal is visible');
    assert.equal(studio.doc.querySelector('main:not([data-home-page]):not([data-workspace-canvas-loading])'), null);
    const refusal = studio.doc.querySelector('[data-workspace-canvas-loading]');
    assert.match(refusal.textContent, /(?:The canvas could not be loaded:|Canvas unavailable)/);
    if (failure === 'refused') assert.ok(refusal.textContent.includes('scope read refused'));
    studio.flush(() => button(refusal, 'Retry').click());
    await studio.settle(() => studio.canvasReads.length === 2, 'Retry performs a fresh verified read');
    studio.canvasReads[1].resolve(workspaceCaptured);
    await studio.settle(() => studio.doc.querySelector('main:not([data-home-page]):not([data-workspace-canvas-loading])'), 'Retry restores the original Workspace');
    assert.deepEqual(studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.canvas.scope, workspaceCaptured.scope);
    const libraryRetry = studio.win.AH_LOAD_LIBRARY();
    await studio.settle(() => studio.libraryReads.length === 1, 'catalogue first use reuses the successfully retried canvas');
    studio.libraryReads[0].resolve(served);
    await libraryRetry;
  } finally {studio.close();}
});

test('Settings waits for original canvas controls before mounting its existing appearance and action panels', async () => {
  const studio = await mountStudio({rawCanvas:{...captured, nodes:[], wires:[], canvas_deferred:true}, fullCanvas:workspaceCaptured, holdCanvas:true});
  try {
    assert.equal(studio.canvasReads.length, 0);
    studio.flush(() => studio.doc.querySelector('[data-rail-panel="Settings"]').click());
    await studio.settle(() => studio.canvasReads.length === 1 && studio.doc.querySelector('[data-settings-canvas-loading]'), 'Settings first open reads its original controls');
    assert.equal(studio.doc.querySelector('[role="dialog"][aria-label="Settings"]'), null, 'Settings actions do not mount with the action-free Home frame');
    studio.canvasReads[0].resolve(workspaceCaptured);
    await studio.settle(() => studio.doc.querySelector('[role="dialog"][aria-label="Settings"]'), 'the unchanged Settings body mounts after the full projection');
    assert.equal(studio.canvasReads.length, 1);
  } finally {studio.close();}
});

test('Home graph creation, node placement, Run and model selection wait for the original shared canvas read', async () => {
  let answer;
  const ready = new Promise(resolve => {answer = resolve;});
  const posts = [];
  const window = {ARCHHUB_LOAD_CANVAS:() => ready,
    ARCHHUB_EXISTING_WORKSHOP:{setComposerModel:async model => {
      posts.push(['composer', model]); return {configuration_state:{composer_model:{value:model}}};}}};
  const pieces = [
    ['    window.ARCHHUB_AGENT_SELECT =', '    let graphRunPromise ='],
    ['    let graphRunPromise =', '    window.ARCHHUB_SET_PROP ='],
    ['    window.ARCHHUB_GRAPH_CREATE =', '    window.ARCHHUB_GRAPH_OPEN ='],
    ['    window.ARCHHUB_NODE_CREATE =', '    window.ARCHHUB_RETRACT ='],
  ].map(([from, to]) => {
    const a = html.indexOf(from), b = html.indexOf(to, a);
    assert.ok(a > 0 && b > a);
    return html.slice(a, b);
  }).join('\n');
  vm.runInNewContext(pieces, {window, jpost:async (url, body) => {posts.push([url, body]); return {ok:true};}});
  const actions = [window.ARCHHUB_GRAPH_CREATE('New graph'), window.ARCHHUB_NODE_CREATE({engine:'data.constant'}),
    window.ARCHHUB_RUN(), window.ARCHHUB_AGENT_SELECT('fixture-model')];
  assert.equal(posts.length, 0, 'the Home frame supplies no callable projection controls');
  answer(workspaceCaptured);
  const results = await Promise.all(actions);
  assert.equal(posts.length, 4);
  assert.equal(results[3], 'fixture-model');
  assert.deepEqual(posts.map(row => row[0]).sort(), ['/api/universal/graph-create','/api/universal/node-create','/api/universal/run-graph','composer']);
});

test('Home node overlay preserves refusal, Retry, complete catalogue rows, and catalogue refresh', async () => {
  const studio = await mountStudio();
  try {
    studio.flush(() => button(studio.doc, '/ node').click());
    await studio.settle(() => studio.libraryReads.length === 1, 'overlay first open requests the catalogue');
    studio.libraryReads[0].reject(new Error('library endpoint refused'));
    await studio.settle(() => [...studio.doc.querySelectorAll('[role="alert"]')].find(row => row.textContent.includes('library endpoint refused')), 'refusal is visible');
    const overlay = [...studio.doc.querySelectorAll('[role="dialog"]')].find(row => row.querySelector('input[placeholder^="Search"]'));
    assert.match(overlay.textContent, /(?:The node library could not be loaded:|Library unavailable)/);
    assert.ok(overlay.textContent.includes('library endpoint refused'));
    studio.flush(() => button(overlay, 'Retry').click());
    await studio.settle(() => studio.libraryReads.length === 2, 'Retry requests the same verified endpoint');
    studio.libraryReads[1].resolve(served);
    await studio.settle(() => overlay.querySelectorAll('[data-library-row]').length === visibleCount, 'overlay renders the entire admitted real catalogue');
    const dragged = [];
    for (const row of overlay.querySelectorAll('[data-library-row]')) {
      const event = new studio.win.Event('dragstart', {bubbles:true});
      Object.defineProperty(event, 'dataTransfer', {value:{setData:(type,value) => {if (type === 'application/x-lm-node') dragged.push(JSON.parse(value).id);}}});
      studio.flush(() => row.dispatchEvent(event));
      studio.flush(() => row.dispatchEvent(new studio.win.Event('dragend', {bubbles:true})));
    }
    assert.deepEqual(dragged.sort(), groups.flatMap(group => group.items.map(item => item.id)).sort(), 'each admitted catalogue ID is a real draggable row, regardless of humanized title');
    assert.equal(overlay.querySelector('[role="alert"]'), null);
    const canvasReadsBeforeRefresh = studio.canvasReads.length;
    const refreshed = studio.win.ARCHHUB_REFRESH_NODE_LIBRARY();
    await studio.settle(() => studio.libraryReads.length === 3, 'Catalogue refresh passes the shared canvas-read barrier and requests the catalogue');
    assert.equal(studio.libraryReads.length, 3);
    assert.equal(studio.canvasReads.length, canvasReadsBeforeRefresh, 'Catalogue refresh reuses the accepted original canvas');
    const mod = {id:'fixture-mod', title:'Fixture mod', engine:'data.constant', mod:true};
    studio.libraryReads[2].resolve({...served, groups:[...groups, {cat:'fixture', items:[mod]}]});
    await refreshed;
    await studio.settle(() => overlay.textContent.includes('Fixture mod'), 'Catalogue refresh reaches the mounted overlay');
    assert.ok(overlay.textContent.includes('Fixture mod'), 'the refreshed main catalogue contains the new row');
  } finally {studio.close();}
});

test('main Ctrl+K catalogue and Skills each load only on their first open', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    assert.equal(studio.libraryReads.length, 0);
    assert.equal(studio.skillReads(), 0);
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'k', ctrlKey:true, bubbles:true})));
    await studio.settle(() => studio.libraryReads.length === 1, 'main Ctrl+K opens the existing node catalogue');
    assert.equal(studio.skillReads(), 1, 'command bar reads the saved skills it offers');
    studio.libraryReads[0].resolve(served);
    await studio.settle(() => studio.doc.body.textContent.includes(groups[0].items[0].title), 'node suggestions render');
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    studio.flush(() => studio.doc.querySelector('[data-rail-panel="Library"]').click());
    await studio.settle(() => studio.doc.querySelector('[data-library-tab="skills"]'));
    studio.flush(() => studio.doc.querySelector('[data-library-tab="skills"]').click());
    await studio.settle(() => studio.skillReads() === 1, 'first Skills open loads its catalogue');
    studio.flush(() => studio.doc.querySelector('[data-library-tab="search"]').click());
    await studio.settle();
    assert.equal(studio.skillReads(), 1, 'Search reuses the shared skill catalogue');
  } finally {studio.close();}
});

test('first Workspace open loads verified categories and wire metadata without changing declared socket types', async () => {
  const group = groups.find(row => row.cat !== 'logic' && row.items.some(item => item.engine && item.hidden !== true));
  const item = group.items.find(row => row.engine && row.hidden !== true);
  const rawCanvas = {...workspaceCaptured, canvas_deferred:false, nodes:[
    {id:'source-fixture', label:item.title, engine:item.engine, params:[], ports:[{id:'out', name:'out', side:'source', type:'text'}]},
    {id:'target-fixture', label:'Declared target', category:'output', params:[], ports:[{id:'in', name:'in', side:'target', type:'text'}]},
  ], wires:[{id:'typed-fixture-wire', source:'source-fixture', source_interface:'out', target:'target-fixture', target_interface:'in', params:[]} ]};
  const studio = await mountStudio({rawCanvas});
  try {
    const before = studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph;
    assert.equal(before.nodes[1].cat, 'output', 'the raw authoritative category survives before the catalogue');
    const session = graphButton(studio.doc);
    assert.ok(session, 'Home offers its captured graph');
    studio.flush(() => session.click());
    await studio.settle(() => studio.doc.querySelector('main:not([data-home-page]):not([data-workspace-canvas-loading])') && studio.libraryReads.length === 1, 'first Workspace open requests its catalogue');
    const pending = studio.win.AH_LOAD_LIBRARY();
    studio.libraryReads[0].resolve(served);
    await pending;
    const after = studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph;
    assert.equal(after.nodes[0].cat, served.categories[item.engine], 'the original verified engine category reaches the canvas');
    assert.deepEqual(JSON.parse(JSON.stringify(after.nodes.map(node => [node.ins, node.outs]))),
      JSON.parse(JSON.stringify(before.nodes.map(node => [node.ins, node.outs]))));
    assert.equal(after.wires[0].t, 'text');
    assert.equal(studio.libraryReads.length, 1);
  } finally {studio.close();}
});

 test('RELGATEFIX cold Home mounts the shared rail without loading Workshop', async () => {
  const ui = await mountStudio({coldWorkshop:true});
  try {
    await ui.settle(() => ui.doc.querySelector('[data-home-page]'), 'cold Home mounts');
    assert.equal(ui.win.WorkshopView, undefined, 'Workshop stays unloaded');
    assert.deepEqual([...ui.doc.querySelectorAll('[data-app-rail] button[aria-label]')].map(el => el.getAttribute('aria-label')), ['Home','Chats','Workshop','Canvas','Library','Docs','Settings','Account']);
    assert.equal(ui.doc.querySelectorAll('[data-app-rail]').length, 1);
    ui.flush(() => ui.doc.querySelector('[data-rail-panel="Chats"]').click());
    await ui.settle(() => ui.doc.querySelector('[data-left-panel]')?.textContent.includes('Chats'), 'one rail click opens the real conversations panel');
    assert.equal(ui.doc.querySelector('[data-rail-panel="Chats"]').getAttribute('aria-current'), 'true');
    ui.flush(() => ui.doc.querySelector('[data-rail-panel="Home"]').click());
    ui.flush(() => ui.win.dispatchEvent(new ui.win.KeyboardEvent('keydown', {key:'k',ctrlKey:true,bubbles:true})));
    await ui.settle(() => ui.doc.querySelector('[data-command-bar]')?.textContent.includes('Conversations'), 'the existing palette exposes Chats');
    const chats = [...ui.doc.querySelectorAll('[data-command-bar] button')].find(row => row.textContent.includes('Conversations'));
    ui.flush(() => chats.click());
    await ui.settle(() => !ui.doc.querySelector('[data-command-bar]') && ui.doc.querySelector('[data-left-panel]')?.textContent.includes('Chats'), 'palette opens the real conversations destination');
  } finally { ui.close(); }
});
