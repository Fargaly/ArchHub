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
const canvas = (id, title, node, revision) => ({
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
  authorization:auth,
  configuration:{theme:{...seed}},
  nodes:[{
    id:node.id, label:node.label, engine:'engine:noop',
    assembly:'Domain composition', params:[], ports:[],
    x:node.x, y:node.y, status:'',
  }],
  wires:[],
  catalog:[],
  workshops:[],
  interaction_projection:{revision, lifecycle:'wip', bindings:[]},
  workshop_scope:workshopScope(id, title, revision),
});
const canvases = {
  'graph-a': canvas('graph-a', 'Graph Alpha', {id:'node-a', label:'Alpha node', x:40, y:60}, 11),
  'graph-b': canvas('graph-b', 'Graph Beta', {id:'node-b', label:'Beta node', x:80, y:90}, 12),
  'graph-c': canvas('graph-c', 'Created Graph', {id:'node-c', label:'Created node', x:120, y:130}, 13),
};
// The receipt carries the server's own canvas projection (universal_graphs.project_graph_index).
// The Studio does not apply it; it re-reads the canvas once in place, so the receipt is passed as is.
const receiptCanvas = id => canvases[id];
const graphRows = {
  'graph-a': {id:'graph-a', title:'Graph Alpha', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'1 node', model:''},
  'graph-b': {id:'graph-b', title:'Graph Beta', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'1 node', model:''},
  'graph-c': {id:'graph-c', title:'Created Graph', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'1 node', model:''},
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
      engine, openable:n.openable === true, composition:n.composition === true,
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
  const calls = {open:[], create:[], canvas:0, refresh:0, alerts:[]};
  let current = options.current || 'graph-a';
  let failRead = false;
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
    get:async () => { calls.canvas += 1; if (failRead) throw new Error('The canvas could not be read.'); return canvases[current]; },
    post:async () => { throw new Error('unexpected post'); },
    projectCanvas:projectStudioCanvas,
  });
  win.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvases[current]);
  win.ARCHHUB_GET_CANVAS = async () => {
    calls.canvas += 1;
    return canvases[current];
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
  const byTitle = title => [...win.document.querySelectorAll('button')].find(node => node.title === title);
  const click = node => win.ReactDOM.flushSync(() => node.click());
  return {win, doc:win.document, calls, navigationErrors, button, byTitle, click, settle, close,
    failNextRead:() => { failRead = true; }};
}

function openHome(studio) {
  const home = studio.byTitle('All sessions');
  assert.ok(home, 'Home button exists');
  studio.click(home);
}

function showCanvas(studio) {
  const canvas = [...studio.doc.querySelectorAll('button')].find(node => node.textContent.trim() === 'Canvas');
  assert.ok(canvas, 'Canvas segment exists');
  studio.click(canvas);
}

function showChat(studio) {
  const chat = [...studio.doc.querySelectorAll('button')].find(node => node.textContent.trim() === 'Chat');
  assert.ok(chat, 'Chat segment exists');
  studio.click(chat);
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

test('opening a session from the Chats panel applies the receipt and remounts graph-local chat state', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    showChat(studio);
    await studio.settle();
    const draft = studio.doc.querySelector('input[aria-label="Reply"]');
    assert.ok(draft, 'Chat draft exists');
    const set = Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set;
    studio.win.ReactDOM.flushSync(() => { set.call(draft, 'old graph draft'); draft.dispatchEvent(new studio.win.Event('input', {bubbles:true})); });
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
    assert.equal(studio.doc.querySelector('input[aria-label="Reply"]').value, '', 'chat draft is graph-local');
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
