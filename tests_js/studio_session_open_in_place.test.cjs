const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {VirtualConsole} = require('jsdom');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

const auth = {subject:'owner-a', session:'view-a', system_view:true};
const workshopScope = (id, title, revision) => ({
  graph_id:'app:archhub', root:id, revision,
  workshops:[], unavailable:'No Workshop is attached to this graph.',
});
const canvas = (id, title, node, revision, extra = {}) => {
  const nodes = Array.isArray(node) ? node : [node];
  return ({
  ok:true,
  revision,
  application_root:'app:archhub',
  canvas_root:'app:canvas',
  properties_lens_root:'app:properties-lens',
  selected:null,
  selection:[],
  selected_title:title,
  scope:{current:id, current_label:title, trail:[
    {root:'app:canvas', label:'Canvas'},
    ...(id === 'app:canvas' ? [] : [{root:id, label:title}]),
  ]},
  ...extra,
  authorization:auth,
  configuration:{theme:{...seed}},
  nodes:nodes.map(node => ({
    id:node.id, label:node.label, engine:node.engine || 'engine:noop',
    assembly:node.assembly || 'Domain composition',
    params:node.params || [], ports:node.ports || [],
    x:node.x, y:node.y, status:'',
    has_conversation:node.has_conversation, conversation_root:node.conversation_root,
  })),
  wires:[],
  catalog:[],
  workshops:extra.workshops || [],
  interaction_projection:{revision, lifecycle:'wip', bindings:[]},
  workshop_scope:workshopScope(id, title, revision),
  });
};
const canvases = {
  'graph-a': canvas('graph-a', 'Graph Alpha', [
    {id:'node-a', label:'Alpha node', x:40, y:60, has_conversation:true,
      conversation_root:'room-node-a', params:[{label:'level', value:'L03'}]},
    {id:'session-a', label:'Door tags L3', x:320, y:120, assembly:'Session',
      has_conversation:true, conversation_root:'room-a', params:[{label:'messages', value:'6'}]},
  ], 11, {description:'Graph Alpha description'}),
  'graph-b': canvas('graph-b', 'Graph Beta', {id:'node-b', label:'Beta node', x:80, y:90}, 12),
  'graph-c': canvas('graph-c', 'Created Graph', {id:'node-c', label:'Created node', x:120, y:130}, 13),
  'fresh': canvas('fresh', 'Fresh Profile Graph', [
    {id:'sketch-lines', label:'Sketch Lines', x:40, y:60},
    {id:'line-watcher', label:'Line Watcher', x:300, y:60},
    {id:'revit-walls', label:'Revit Walls', x:560, y:60},
    {id:'cad-lines', label:'CAD Lines', x:40, y:260},
    {id:'revit-sessions', label:'Revit Sessions', x:300, y:260, assembly:'Session',
      has_conversation:true, conversation_root:'room-fresh'},
  ], 15, {description:'No AI nodes'}),
};
// The receipt carries the server's own canvas projection (universal_graphs.project_graph_index).
// The Studio does not apply it; it re-reads the canvas once in place, so the receipt is passed as is.
const receiptCanvas = id => canvases[id];
const graphRows = {
  'graph-a': {id:'graph-a', title:'Graph Alpha', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'1 node', model:''},
  'graph-b': {id:'graph-b', title:'Graph Beta', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'1 node', model:''},
  'graph-c': {id:'graph-c', title:'Created Graph', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'1 node', model:''},
  'fresh': {id:'fresh', title:'Fresh Profile Graph', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'5 nodes', model:''},
};

function projectStudioCanvas(canvas) {
  const held = {};
  const CATS = e => held[e] || 'logic';
  const nodes = [];
  for (const n of (canvas.nodes || [])) {
    const params = Object.fromEntries((n.params || []).map(r => [r.label, r.value]));
    const engine = String(n.engine || params.engine || '');
    const ins = [], outs = [];
    for (const p of (n.ports || [])) {
      if (p.side === 'target') ins.push({...p, label:p.name || '', t:p.type || p.value_type || 'any'});
      else if (p.side === 'source') outs.push({...p, label:p.name || '', t:p.type || p.value_type || 'any'});
    }
    nodes.push({
      id:n.id, cat:CATS(engine), title:n.label || n.id, sub:engine || 'Graph node',
      engine, assembly:n.assembly || '', kind:n.kind || n.assembly || '',
      openable:n.openable === true, composition:n.composition === true,
      has_conversation:n.has_conversation === true, conversation_root:n.conversation_root || '',
      memberCount:Number.isSafeInteger(n.member_count) ? n.member_count : null,
      x:Number.isFinite(n.x) ? n.x : 200, y:Number.isFinite(n.y) ? n.y : 200,
      w:210, h:Math.max(110, 54 + Math.max(ins.length, outs.length) * 19),
      ins, outs, messages:[], live:true,
      params:(n.params || []).filter(r => r.label !== 'engine' && r.label !== 'status')
        .map(r => ({k:r.label, v:r.value, rel:r.relation, editable:r.editable !== false && !!r.relation, owner:n.id})),
      ports:{ins:ins.map(x => ({id:x.id, t:x.t})), outs:outs.map(x => ({id:x.id, t:x.t}))},
      status:n.status || params.status || '',
    });
  }
  const nodeIndex = new Map(nodes.map(node => [node.id, node]));
  const wires = [];
  for (const w of (canvas.wires || [])) {
    const sourcePort = nodeIndex.get(w.source)?.outs.find(port => port.id === w.source_interface);
    wires.push({...w, id:String(w.id || ''), from:[w.source, w.source_interface],
      to:[w.target, w.target_interface], t:sourcePort?.t || '',
      params:(w.params || []).map(r => ({k:r.label, v:r.value, rel:r.relation}))});
  }
  return {nodes, wires};
}

async function mountStudio(options = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const navigationErrors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => {
    if (/Not implemented: navigation/.test(String(error?.message || error))) navigationErrors.push(String(error.message || error));
  });
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only',
    pretendToBeVisual:true, virtualConsole});
  const win = dom.window;
  Object.defineProperty(win.HTMLElement.prototype, 'offsetWidth', {configurable:true, get() { return 220; }});
  Object.defineProperty(win.HTMLElement.prototype, 'offsetHeight', {configurable:true, get() { return 110; }});
  win.HTMLElement.prototype.getBoundingClientRect = function() {
    return this.getAttribute('role') === 'region' && this.getAttribute('aria-label') === 'Workflow canvas'
      ? {width:1000, height:760, left:0, top:0, right:1000, bottom:760}
      : {width:220, height:110, left:0, top:0, right:220, bottom:110};
  };
  const calls = {open:[], create:[], nodeCreate:[], canvas:0, refresh:0, alerts:[], agent:[]};
  let current = options.current || 'graph-a';
  let failRead = false;
  let nodeCreated = false;
  const currentCanvas = () => nodeCreated && current === 'graph-a'
    ? canvas('graph-a', 'Graph Alpha', [
      {id:'node-a', label:'Alpha node', x:40, y:60},
      {id:'node-created', label:'Created node', x:920, y:640},
    ], 14)
    : canvases[current];
  const sessions = options.sessions || [graphRows['graph-a'], graphRows['graph-b']];
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/free'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:[]})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.alert = message => calls.alerts.push(String(message));
  win.eval(read('nodelang/studio/studio-existing-workshop.js'));
  win.ARCHHUB_EXISTING_WORKSHOP = win.ArchHubExistingWorkshop.create({
    get:async () => { calls.canvas += 1; if (failRead) throw new Error('The canvas could not be read.'); return currentCanvas(); },
    post:async () => { throw new Error('unexpected post'); },
    projectCanvas:projectStudioCanvas,
  });
  win.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(currentCanvas());
  win.ARCHHUB_GET_CANVAS = async () => {
    calls.canvas += 1;
    return currentCanvas();
  };
  win.ARCHHUB_GRAPH_OPEN = async id => {
    calls.open.push(id);
    current = id;
    return {ok:true, graphs:[...sessions, graphRows[id]].filter((row, index, rows) =>
      rows.findIndex(other => other.id === row.id) === index), current_graph:id, canvas:receiptCanvas(id)};
  };
  win.ARCHHUB_GRAPH_CREATE = async title => {
    calls.create.push(title);
    current = 'graph-c';
    return {ok:true, graphs:[...sessions, graphRows['graph-c']], current_graph:'graph-c',
      graph:graphRows['graph-c'], canvas:receiptCanvas('graph-c')};
  };
  win.ARCHHUB_NODE_CREATE = async spec => {
    calls.nodeCreate.push(JSON.parse(JSON.stringify(spec)));
    nodeCreated = true;
    return {ok:true, node:'node-created', selected:'node-created'};
  };
  if (options.realAgentBridge) {
    const bridgeSource = read('nodelang/studio/studio.html');
    const start = bridgeSource.indexOf('    window.ARCHHUB_AGENT = async');
    const end = bridgeSource.indexOf('    // The composer pick is', start);
    assert.ok(start > 0 && end > start, 'the real studio.html ARCHHUB_AGENT bridge is present');
    win.jpost = async (url, body) => {
      calls.agent.push([url, JSON.parse(JSON.stringify(body))]);
      return options.agentResult || {ok:true, answer:'bridge ok', applied:[], delivery:{state:'replied', request_id:body.request_id}};
    };
    win.eval('const jpost = window.jpost;\n' + bridgeSource.slice(start, end));
  }
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node,
    conversation_root:String(node).startsWith('graph:') ? 'graph-room' : (node === 'session-a' ? 'room-a' : null),
    rows:node === 'session-a' ? [{id:'m1', who:'Agent', text:'Session conversation lives here.', time:'2026-10-10T10:00:00Z', kind:'message'}] : [],
    has_older:false});
  win.AH_LIBRARY = [{cat:'logic', items:[{id:'test-node', title:'Test node', sub:'Noop node', engine:'engine:noop'}]}];
  win.ARCHHUB_LIVE = {sessions, currentGraph:current, hosts:[], connectors:[],
    graph:win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 80));
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const button = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const buttonIncludes = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.includes(label));
  const byTitle = title => [...win.document.querySelectorAll('button')].find(node => node.title === title);
  const click = node => win.ReactDOM.flushSync(() => node.click());
  const tabCount = () => win.document.querySelectorAll('button[title="Close tab"]').length;
  const transform = () => win.document.querySelector('[role="region"][aria-label="Workflow canvas"]')?.firstElementChild?.style.transform || '';
  const byTitleStarts = title => [...win.document.querySelectorAll('button')].find(node => String(node.title || '').startsWith(title));
  const type = (input, value) => {
    const set = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
    win.ReactDOM.flushSync(() => { set.call(input, value); input.dispatchEvent(new win.Event('input', {bubbles:true})); });
  };
  return {win, doc:win.document, calls, navigationErrors, button, buttonIncludes, byTitle, byTitleStarts, click, type, settle, close,
    failNextRead:() => { failRead = true; }, tabCount, transform};
}

function openHome(studio) {
  const home = studio.byTitle('All sessions');
  assert.ok(home, 'Home button exists');
  studio.click(home);
}

function openWorkshopFromHome(studio) {
  openHome(studio);
  const workshop = studio.doc.querySelector('[data-home-tools] [data-tool-card="workshop"]');
  assert.ok(workshop, 'Home exposes Workshop tool card');
  studio.click(workshop);
}

function showCanvas(studio) {
  const canvas = [...studio.doc.querySelectorAll('button')].find(node => node.textContent.trim() === 'Canvas');
  if (canvas) studio.click(canvas);
  assert.ok(studio.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), 'Studio canvas view exists');
}

function assertCanvasSelectionOnly(studio, detail) {
  assert.ok(studio.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), detail + ': canvas is visible');
  assert.equal(studio.doc.querySelectorAll('[role="tablist"][aria-label="Workshop tabs"]').length, 0,
    detail + ': Workshop tabs are gone');
  assert.equal(studio.doc.querySelectorAll('input[aria-label="Ask selection"]').length, 1,
    detail + ': one selection composer is mounted');
  assert.equal(studio.doc.querySelectorAll('[data-model-indicator]').length, 1,
    detail + ': one model indicator is mounted');
}

function showChat(studio) {
  const chat = [...studio.doc.querySelectorAll('button')].find(node => node.textContent.trim() === 'Chat');
  if (chat) studio.click(chat);
  assert.ok(studio.doc.querySelector('input[aria-label="Ask selection"]'), 'selection-panel chat composer exists');
}

test('opening a session from Home applies the graph-open receipt in place: one canvas re-read, no reload', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    openHome(studio);
    await studio.settle();
    studio.calls.canvas = 0;
    studio.click([...studio.doc.querySelectorAll('button')].find(node => node.textContent.includes('Graph Beta')));
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    assert.deepEqual(studio.calls.open, ['graph-b']);
    assert.equal(studio.calls.canvas, 1, 'the same page re-reads its canvas once; the receipt canvas is not applied');
    assert.equal(studio.navigationErrors.length, 0, 'no reload/assign/replace navigation');
    assert.match(studio.doc.body.textContent, /Graph Beta/);
    assert.match(studio.doc.body.textContent, /Beta node/);
  } finally { studio.close(); }
});

test('opening a session from the Chats rail applies the receipt; the chat composer lives in the selection panel', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    studio.click(studio.byTitle('Chats'));
    await studio.settle();
    studio.calls.canvas = 0;
    studio.click([...studio.doc.querySelectorAll('button')].find(node => node.textContent.includes('Graph Beta')));
    await studio.settle();
    showChat(studio);
    await studio.settle();
    assert.deepEqual(studio.calls.open, ['graph-b']);
    assert.equal(studio.calls.canvas, 1, 'the same page re-reads its canvas once; the receipt canvas is not applied');
    assert.equal(studio.navigationErrors.length, 0, 'no reload/assign/replace navigation');
    assert.match(studio.doc.body.textContent, /Graph Beta/);
    assert.equal(studio.doc.querySelectorAll('input[aria-label="Ask selection"]').length, 1,
      'the moved chat composer is the one selection-panel input');
  } finally { studio.close(); }
});

test('creating a new session opens the graph-create receipt in place without reloading or re-posting', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    openHome(studio);
    await studio.settle();
    studio.click(studio.button('+ new graph'));
    const input = studio.doc.querySelector('input[aria-label="New graph name"]');
    const set = Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set;
    studio.win.ReactDOM.flushSync(() => { set.call(input, 'Created Graph'); input.dispatchEvent(new studio.win.Event('input', {bubbles:true})); });
    studio.calls.canvas = 0;
    studio.click(studio.button('Create'));
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    assert.deepEqual(studio.calls.create, ['Created Graph']);
    assert.deepEqual(studio.calls.open, [], 'create receipt is not re-posted as graph-open');
    assert.equal(studio.calls.canvas, 1, 'one in-place canvas re-read after create');
    assert.equal(studio.navigationErrors.length, 0, 'no reload/assign/replace navigation');
    assert.match(studio.doc.body.textContent, /Created Graph/);
    assert.match(studio.doc.body.textContent, /Created node/);
  } finally { studio.close(); }
});

test('clicking the workspace + creates a second graph tab in place and keeps the first tab', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    assert.equal(studio.tabCount(), 1, 'one graph tab is open before creation');
    studio.calls.canvas = 0;
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    assert.deepEqual(studio.calls.create, ['New session']);
    assert.deepEqual(studio.calls.open, [], 'the create receipt is opened directly, not re-posted as graph-open');
    assert.equal(studio.calls.canvas, 1, 'one in-place canvas re-read after create');
    assert.equal(studio.tabCount(), 2, 'the first graph tab remains and the created graph opens as a second tab');
    assert.equal(studio.navigationErrors.length, 0, 'no reload/assign/replace navigation');
    assert.match(studio.doc.body.textContent, /Graph Alpha/);
    assert.match(studio.doc.body.textContent, /Created Graph/);
  } finally { studio.close(); }
});

test('after a create whose canvas refresh fails, the workspace + never posts a second create', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    studio.failNextRead();
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    assert.deepEqual(studio.calls.create, ['New session'], 'one create was posted');
    assert.match(studio.doc.body.textContent, /Refresh the graph list before creating again/);
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    assert.deepEqual(studio.calls.create, ['New session'], 'a lost receipt is never replayed as a second create');
    assert.equal(studio.navigationErrors.length, 0, 'no automatic reload');
  } finally { studio.close(); }
});

test('creating a node pans it into view without zooming in past the current viewport zoom', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const region = studio.doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
    const before = studio.transform();
    const beforeZoom = Number(before.match(/scale\(([^)]+)\)/)?.[1]);
    assert.ok(Number.isFinite(beforeZoom), 'canvas zoom is readable before node create: ' + before);
    studio.click(studio.byTitle('Add node'));
    await studio.settle();
    studio.click(studio.buttonIncludes('Test node'));
    for (let i = 0; i < 12; i += 1) await studio.settle();
    const after = studio.transform();
    const match = after.match(/translate3d\(([-0-9.]+)px,\s*([-0-9.]+)px,\s*0\) scale\(([^)]+)\)/);
    assert.ok(match, 'canvas transform is readable after node create: ' + after);
    const [, panXText, panYText, zoomText] = match;
    const panX = Number(panXText), panY = Number(panYText), zoom = Number(zoomText);
    assert.ok(zoom <= beforeZoom, 'new-node reveal does not zoom in: before ' + beforeZoom + ', after ' + zoom);
    const card = studio.doc.querySelector('.lm-node[data-node-id="node-created"]');
    assert.ok(card, 'created node card exists');
    const x = parseFloat(card.style.left), y = parseFloat(card.style.top);
    const left = panX + x * zoom, right = panX + (x + 220) * zoom;
    const top = panY + y * zoom, bottom = panY + (y + 110) * zoom;
    assert.ok(left >= 24 && right <= region.getBoundingClientRect().width - 24 &&
      top >= 72 && bottom <= region.getBoundingClientRect().height - 80,
      'created node is inside the viewport: ' + JSON.stringify({left, right, top, bottom, zoom}));
    assert.deepEqual(studio.calls.nodeCreate.map(call => call.item), ['test-node']);
  } finally { studio.close(); }
});

test('a failed canvas re-read after graph-open shows refresh control and does not reload or re-post', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    openHome(studio);
    await studio.settle();
    studio.failNextRead();
    studio.calls.canvas = 0;
    studio.click([...studio.doc.querySelectorAll('button')].find(node => node.textContent.includes('Graph Beta')));
    await studio.settle();
    assert.deepEqual(studio.calls.open, ['graph-b']);
    assert.equal(studio.calls.canvas, 1, 'one re-read attempt, never retried');
    assert.equal(studio.navigationErrors.length, 0, 'no reload/assign/replace navigation');
    assert.match(studio.doc.body.textContent, /Refresh graphs/);
    assert.match(studio.doc.body.textContent, /could not be read/);
    assert.equal(studio.doc.body.textContent.includes('Beta node'), false);
  } finally { studio.close(); }
});

test('right panel follows node selection with Properties first and one scoped composer chip', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    assert.equal(studio.doc.querySelectorAll('input[aria-label="Ask selection"]').length, 1,
      'the Studio session view has exactly one ask/reply/message composer');
    studio.click(studio.doc.querySelector('.lm-node[data-node-id="node-a"]'));
    await studio.settle();
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel, 'selection inspector exists');
    assert.match(panel.textContent, /Alpha node/);
    assert.ok(panel.textContent.indexOf('Properties') < panel.textContent.indexOf('Chat'),
      'ordinary node shows Properties before Chat');
    assert.equal(panel.querySelector('[role="tab"][aria-selected="true"]')?.textContent.trim(), 'Properties');
    assert.deepEqual([...panel.querySelectorAll('section[aria-label="Properties"], section[aria-label="Chat"], section[aria-label="Runs"]')]
      .map(section => section.getAttribute('aria-label')), ['Properties']);
    studio.click([...panel.querySelectorAll('[role="tab"]')].find(tab => tab.textContent.trim() === 'Chat'));
    await studio.settle();
    assert.equal(panel.querySelector('[role="tab"][aria-selected="true"]')?.textContent.trim(), 'Chat');
    assert.deepEqual([...panel.querySelectorAll('section[aria-label="Properties"], section[aria-label="Chat"], section[aria-label="Runs"]')]
      .map(section => section.getAttribute('aria-label')), ['Chat']);
    assert.match(panel.querySelector('[data-model-indicator]')?.textContent || '', /Alpha node/);
    assert.match(studio.doc.querySelector('input[aria-label="Ask selection"]').placeholder, /ask about this node/i);
  } finally { studio.close(); }
});

test('empty selection sends graph target through the real bridge, and node selection sends that node', async () => {
  const studio = await mountStudio({current:'fresh', sessions:[graphRows.fresh], realAgentBridge:true});
  try {
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const panel = () => studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.match(panel().textContent, /GRAPH/i);
    assert.match(panel().textContent, /Fresh Profile Graph/);
    assert.equal(studio.doc.querySelectorAll('input[aria-label="Ask selection"]').length, 1,
      'exactly one composer is mounted');
    let input = studio.doc.querySelector('input[aria-label="Ask selection"]');
    studio.type(input, 'graph hello');
    studio.flush = callback => studio.win.ReactDOM.flushSync(callback);
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.deepEqual(studio.calls.agent.map(call => call[0]), ['/api/universal/agent']);
    assert.deepEqual(studio.calls.agent[0][1], {
      prompt:'graph hello', model:'openrouter/free',
      generation:{temperature:0.7, top_p:0.95, max_tokens:4096},
      request_id:studio.calls.agent[0][1].request_id,
      graph:true, graph_id:'fresh',
    });
    assert.equal(typeof studio.calls.agent[0][1].request_id, 'string');
    assert.ok(studio.calls.agent[0][1].request_id);
    studio.click(studio.doc.querySelector('.lm-node[data-node-id="line-watcher"]'));
    await studio.settle();
    assert.match(panel().textContent, /Line Watcher/);
    assert.match(panel().querySelector('[data-model-indicator]')?.textContent || '', /Line Watcher.*openrouter\/free/);
    input = studio.doc.querySelector('input[aria-label="Ask selection"]');
    studio.type(input, 'node hello');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.equal(studio.calls.agent[1][0], '/api/universal/agent');
    assert.equal(studio.calls.agent[1][1].node, 'line-watcher');
    assert.equal(studio.calls.agent[1][1].graph, undefined);
    assert.equal(studio.calls.agent[1][1].model, 'openrouter/free');
  } finally { studio.close(); }
});

test('right panel treats a session node as chat first, and empty selection as the graph', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const panel = () => studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel(), 'empty-selection graph inspector exists');
    assert.match(panel().textContent, /GRAPH/i);
    assert.match(panel().textContent, /Graph Alpha/);
    assert.equal(panel().querySelector('[role="tab"][aria-selected="true"]')?.textContent.trim(), 'Chat',
      'graph inspector opens Chat first');
    assert.deepEqual([...panel().querySelectorAll('section[aria-label="Properties"], section[aria-label="Chat"], section[aria-label="Runs"]')]
      .map(section => section.getAttribute('aria-label')), ['Chat']);
    studio.click([...panel().querySelectorAll('[role="tab"]')].find(tab => tab.textContent.trim() === 'Properties'));
    await studio.settle();
    assert.deepEqual([...panel().querySelectorAll('section[aria-label="Properties"], section[aria-label="Chat"], section[aria-label="Runs"]')]
      .map(section => section.getAttribute('aria-label')), ['Properties']);
    assert.match(panel().querySelector('[data-model-indicator]')?.textContent || '', /Graph Alpha|ArchHub/i);
    studio.click(studio.doc.querySelector('.lm-node[data-node-id="session-a"]'));
    await studio.settle();
    assert.match(panel().textContent, /Door tags L3/);
    assert.ok(panel().textContent.indexOf('Chat') < panel().textContent.indexOf('Properties'),
      'session node shows Chat before Properties');
    assert.equal(panel().querySelector('[role="tab"][aria-selected="true"]')?.textContent.trim(), 'Chat');
    assert.deepEqual([...panel().querySelectorAll('section[aria-label="Properties"], section[aria-label="Chat"], section[aria-label="Runs"]')]
      .map(section => section.getAttribute('aria-label')), ['Chat']);
    assert.match(studio.doc.querySelector('input[aria-label="Ask selection"]').placeholder, /reply in this session/i);
  } finally { studio.close(); }
});

test('ordinary conversation-bound nodes open Properties first while keeping a Chat tab', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const panel = () => studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    studio.click(studio.doc.querySelector('.lm-node[data-node-id="node-a"]'));
    await studio.settle();
    assert.match(panel().textContent, /Alpha node/);
    assert.equal(panel().querySelector('[role="tab"][aria-selected="true"]')?.textContent.trim(), 'Properties');
    assert.deepEqual([...panel().querySelectorAll('[role="tab"]')].map(tab => tab.textContent.trim()).slice(0, 2),
      ['Properties', 'Chat']);
  } finally { studio.close(); }
});

test('Studio header has no Chat Workshop System tabs, selection resets per session, and Home Workshop card still opens', async () => {
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall room', is_general:false}]});
  try {
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const headerText = studio.doc.querySelector('main > div')?.textContent || '';
    for (const forbidden of ['Chat', 'Workshop', 'System']) {
      assert.equal(new RegExp('(^|\\s)' + forbidden + '(\\s|$)').test(headerText), false,
        forbidden + ' is not a Studio session-header tab');
    }
    studio.click(studio.doc.querySelector('.lm-node[data-node-id="node-a"]'));
    await studio.settle();
    assert.match(studio.doc.querySelector('aside[aria-label="Selection inspector"]').textContent, /Alpha node/);
    openHome(studio);
    await studio.settle();
    studio.click([...studio.doc.querySelectorAll('button')].find(node => node.textContent.includes('Graph Beta')));
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const panelText = studio.doc.querySelector('aside[aria-label="Selection inspector"]').textContent;
    assert.match(panelText, /GRAPH|Graph Beta/);
    assert.equal(/Alpha node/.test(panelText), false, 'node selection from Graph Alpha did not leak into Graph Beta');
    openWorkshopFromHome(studio);
    await studio.settle();
    assert.match(studio.doc.body.textContent, /Workshop|Wall room/, 'Home Workshop card path still opens');
  } finally { studio.close(); }
});

test('leaving Workshop through Studio, session reopen, or New session restores canvas selection mode', async () => {
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall room', is_general:false}]});
  try {
    await studio.settle();
    openWorkshopFromHome(studio);
    await studio.settle();
    assert.ok(studio.doc.querySelector('[role="tablist"][aria-label="Workshop tabs"]'), 'Workshop is open');

    openHome(studio);
    studio.click([...studio.doc.querySelectorAll('button')].find(node => node.textContent.includes('Graph Alpha')));
    await studio.settle();
    assertCanvasSelectionOnly(studio, 'same session reopen from Workshop');

    openWorkshopFromHome(studio);
    await studio.settle();
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    assertCanvasSelectionOnly(studio, 'New session from Workshop');
  } finally { studio.close(); }
});
