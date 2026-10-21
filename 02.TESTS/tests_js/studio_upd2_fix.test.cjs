const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {VirtualConsole} = require('jsdom');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

const auth = {subject:'owner-a', session:'view-a', system_view:true};
const graphRows = {
  'graph-a': {id:'graph-a', title:'Graph Alpha', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'3 nodes', model:''},
};

const canvas = (id, title) => ({
  ok:true,
  revision:21,
  graph_id:id,
  root:id,
  application_root:'app:archhub',
  canvas_root:'app:canvas',
  selected:null,
  selection:[],
  selected_title:title,
  scope:{current:id, current_label:title, trail:[{root:'app:canvas', label:'Canvas'}, {root:id, label:title}]},
  authorization:auth,
  configuration:{theme:{...seed}},
  nodes:[
    {id:'app-router', label:'Application router', application:true, engine:'engine:system', assembly:'System', x:40, y:60},
    {id:'app-settings', label:'Settings system', application:true, engine:'engine:system', assembly:'System', x:300, y:60},
    {id:'ai-node', label:'BABOOM PM', engine:'engine:ai', assembly:'AI Worker', x:80, y:260,
      has_conversation:true, conversation_root:'room-ai', params:[{label:'model', value:'openrouter/free'}]},
  ],
  wires:[],
  catalog:[],
  workshops:[],
  interaction_projection:{revision:21, lifecycle:'wip', bindings:[]},
  workshop_scope:{graph_id:'app:archhub', root:id, revision:21, workshops:[], unavailable:'No Workshop is attached to this graph.'},
});
const canvases = {'graph-a': canvas('graph-a', 'Graph Alpha')};

function projectStudioCanvas(held) {
  const nodes = (held.nodes || []).map(n => ({
    id:n.id,
    cat:String(n.engine || '').includes('ai') ? 'ai' : 'logic',
    title:n.label || n.id,
    sub:n.engine || 'Graph node',
    engine:n.engine || '',
    assembly:n.assembly || '',
    kind:n.kind || n.assembly || '',
    application:n.application === true,
    has_conversation:n.has_conversation === true,
    conversation_root:n.conversation_root || '',
    x:Number.isFinite(n.x) ? n.x : 200,
    y:Number.isFinite(n.y) ? n.y : 200,
    w:210,
    h:120,
    ins:[],
    outs:[],
    messages:[],
    live:true,
    params:(n.params || []).map(r => ({k:r.label, v:r.value, rel:r.relation, editable:false, owner:n.id})),
    ports:{ins:[], outs:[]},
    status:'',
  }));
  return {nodes, wires:[]};
}

async function mountStudio(options = {}) {
  const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => {
    if (!/Not implemented: navigation/.test(String(error?.message || error))) throw error;
  });
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only',
    pretendToBeVisual:true, virtualConsole});
  const win = dom.window;
  Object.defineProperty(win.HTMLElement.prototype, 'offsetWidth', {configurable:true, get() { return 240; }});
  Object.defineProperty(win.HTMLElement.prototype, 'offsetHeight', {configurable:true, get() { return 120; }});
  win.HTMLElement.prototype.getBoundingClientRect = function() {
    return this.getAttribute('role') === 'region' && this.getAttribute('aria-label') === 'Workflow canvas'
      ? {width:1000, height:760, left:0, top:0, right:1000, bottom:760}
      : {width:240, height:120, left:0, top:0, right:240, bottom:120};
  };
  const calls = {open:[], agent:[]};
  let current = 'graph-a';
  let selected = null;
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/free'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:[]})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : Promise.resolve({ok:true, json:() => Promise.resolve({ok:true})});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.alert = () => {};
  win.eval(read('01.APP/nodelang/studio/studio-existing-workshop.js'));
  win.ARCHHUB_EXISTING_WORKSHOP = win.ArchHubExistingWorkshop.create({
    get:async () => canvases[current],
    post:async () => { throw new Error('unexpected post'); },
    projectCanvas:projectStudioCanvas,
  });
  win.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvases[current]);
  const signedSnapshot = () => ({...canvases[current], selected, canvas:{...canvases[current], selected},
    graph:projectStudioCanvas(canvases[current]), pending:false, workshops:[]});
  win.ARCHHUB_STUDIO_AUTHORITY = {
    getSnapshot:signedSnapshot,
    subscribe:() => () => {},
    load:async () => signedSnapshot(),
    select:async root => { selected = root || null; return signedSnapshot(); },
  };
  win.ARCHHUB_GET_CANVAS = async () => canvases[current];
  win.ARCHHUB_GRAPH_OPEN = async id => {
    calls.open.push(id);
    if (options.openDeferred) await options.openDeferred.promise;
    if (options.openReject) throw options.openReject;
    current = id;
    return {ok:true, graphs:[graphRows['graph-a']], current_graph:id, canvas:canvases[id]};
  };
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node, conversation_root:'room-ai', rows:[], has_older:false});
  win.ARCHHUB_AGENT = async (prompt, model, context) => {
    calls.agent.push({prompt, model, context});
    return options.agentResult || {ok:true, answer:'Done after tool.', delivery:{state:'replied'},
      steps:[{id:'tool-1', tool:'pm_update', status:'ok', args:{task:'draw'}, summary:'tool requested'}]};
  };
  win.ARCHHUB_LIVE = {sessions:[graphRows['graph-a']], currentGraph:current, hosts:[], connectors:[],
    graph:projectStudioCanvas(canvases[current]), memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:current};
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('01.APP/nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = async (count = 1) => {
    for (let i = 0; i < count; i += 1) await new Promise(resolve => win.setTimeout(resolve, 80));
  };
  const click = node => {
    assert.ok(node, 'click target exists');
    win.ReactDOM.flushSync(() => node.click());
  };
  const buttonIncludes = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.includes(label));
  const byTitle = title => [...win.document.querySelectorAll('button')].find(node => node.title === title);
  const type = (input, value) => {
    const set = Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
    win.ReactDOM.flushSync(() => { set.call(input, value); input.dispatchEvent(new win.Event('input', {bubbles:true})); });
  };
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc:win.document, calls, click, buttonIncludes, byTitle, type, settle, close};
}

async function openSettingsSystem(studio) {
  studio.click(studio.byTitle('Settings'));
  await studio.settle();
  const buttons = [...studio.doc.querySelectorAll('[role="dialog"][aria-label="Settings"] button')];
  const system = buttons.find(node => node.textContent.trim().startsWith('System'));
  assert.ok(system, 'System tab exists among: ' + buttons.map(node => node.textContent.trim()).join(' | '));
  studio.click(system);
  await studio.settle();
}

test('UPD2 SX: Settings closes only after the admitted System graph is shown', async () => {
  const gate = deferred();
  const studio = await mountStudio({openDeferred:gate});
  try {
    await openSettingsSystem(studio);
    studio.click(studio.buttonIncludes('Open the System graph'));
    await studio.settle();
    assert.ok(studio.doc.querySelector('[role="dialog"][aria-label="Settings"]'), 'Settings remains open while GRAPH_OPEN is pending');
    assert.equal(studio.doc.querySelector('[data-system-header]'), null, 'System graph is not shown before admission');
    gate.resolve();
    await studio.settle(3);
    assert.equal(studio.doc.querySelector('[role="dialog"][aria-label="Settings"]'), null, 'Settings closes after admission');
    assert.ok(studio.doc.querySelector('[data-system-header]'), 'System header is shown');
    assert.ok(studio.doc.querySelector('[data-node-id="app-router"]'), 'application node is visible');
    assert.ok(studio.doc.querySelector('[data-node-id="app-settings"]'), 'second application node is visible');
  } finally {
    studio.close();
  }
});

test('UPD2 SX: refused System graph keeps Settings open with the reason', async () => {
  const studio = await mountStudio({openReject:new Error('System graph refused by policy')});
  try {
    await openSettingsSystem(studio);
    studio.click(studio.buttonIncludes('Open the System graph'));
    await studio.settle(2);
    assert.ok(studio.doc.querySelector('[role="dialog"][aria-label="Settings"]'), 'Settings stays open on refusal');
    assert.match(studio.doc.body.textContent, /System graph refused by policy/);
    assert.equal(studio.doc.querySelector('[data-system-header]'), null, 'refused graph is not shown');
  } finally {
    studio.close();
  }
});

test('UPD2 SX: Home chosen while System open is pending wins over late admission', async () => {
  const gate = deferred();
  const studio = await mountStudio({openDeferred:gate});
  try {
    await openSettingsSystem(studio);
    studio.click(studio.buttonIncludes('Open the System graph'));
    await studio.settle();
    studio.click(studio.byTitle('All sessions'));
    gate.resolve();
    await studio.settle(3);
    assert.equal(studio.doc.querySelector('[data-system-header]'), null, 'late System admission does not replay');
    assert.equal(studio.doc.querySelector('[data-node-id="app-router"]'), null, 'late System graph nodes are not shown');
    assert.ok(studio.buttonIncludes('Graph Alpha'), 'Home remains visible');
  } finally {
    studio.close();
  }
});

test('UPD2 BB: real composer render shows BABOOM tool steps and final answer', async () => {
  const studio = await mountStudio();
  try {
    studio.click(studio.buttonIncludes('Graph Alpha'));
    await studio.settle(3);
    studio.click(studio.doc.querySelector('[data-node-id="ai-node"]'));
    await studio.settle(2);
    studio.click([...studio.doc.querySelectorAll('aside[aria-label="Selection inspector"] button')]
      .find(node => node.textContent.trim() === 'Chat'));
    await studio.settle();
    const input = studio.doc.querySelector('input[aria-label="Ask selection"]');
    studio.type(input, 'request the PM tool');
    studio.click([...studio.doc.querySelectorAll('button')].find(node => node.textContent.trim() === 'Send'));
    await studio.settle(3);
    assert.equal(studio.calls.agent.length, 1, 'composer called the fake model once');
    assert.ok(studio.doc.querySelector('[data-baboom-step]'), 'BABOOM step row rendered');
    assert.match(studio.doc.body.textContent, /Done after tool\./);
  } finally {
    studio.close();
  }
});
