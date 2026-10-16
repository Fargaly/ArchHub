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

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

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
  'history': canvas('history', 'History Graph', [
    {id:'node-h', label:'Target node', x:70, y:90},
    {id:'history-node', label:'History', x:330, y:90, engine:'app:history', kind:'history', history_node:true},
    {id:'history-title-only', label:'History', x:590, y:90},
  ], 21, {action_history:{root:'history-root', can_undo:true, can_redo:false, transactions:[
    {root:'tx-6', timestamp:new Date(new Date().setHours(10,5,0,0)).toISOString(), actor:'agent:codex', operation:'Move member', target_root:'node-h', target_label:'Target node', state:'applied'},
    {root:'tx-5', timestamp:new Date(new Date().setHours(10,4,0,0)).toISOString(), actor:'founder', operation:'Place node', target_root:'node-h', target_label:'Target node', state:'undone'},
    {root:'tx-4', timestamp:new Date(new Date().setHours(10,3,0,0)).toISOString(), actor:'agent:claude', operation:'Move', target_root:'node-h', target_label:'Target node', state:'applied'},
    {root:'tx-3', timestamp:new Date(new Date().setHours(10,2,0,0)).toISOString(), actor:'agent:opencode', operation:'Wire', target_root:'node-h', target_label:'Target node', state:'discarded'},
    {root:'tx-2', timestamp:new Date(new Date().setHours(10,1,0,0)).toISOString(), actor:'founder', operation:'Undo', target_root:'node-h', target_label:'Target node', state:'undo'},
    {root:'tx-1', timestamp:new Date(new Date().setHours(10,0,0,0)).toISOString(), actor:'agent:codex', operation:'Place node', target_root:'node-h', target_label:'Target node', state:'applied'},
  ]}}),
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
  'history': {id:'history', title:'History Graph', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'2 nodes', model:''},
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
      history_node:n.history_node === true,
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
  const calls = {open:[], create:[], nodeCreate:[], history:[], canvas:0, refresh:0, alerts:[], agent:[]};
  let current = options.current || 'graph-a';
  const extraCanvases = options.canvases || {};
  const extraRows = options.graphRows || {};
  const allCanvases = {...canvases, ...extraCanvases};
  const allRows = {...graphRows, ...extraRows};
  let failRead = false;
  let deferredCanvasRead = null;
  let nodeCreated = false;
  const currentCanvas = () => nodeCreated && current === 'graph-a'
    ? canvas('graph-a', 'Graph Alpha', [
      {id:'node-a', label:'Alpha node', x:40, y:60},
      {id:'node-created', label:'Created node', x:920, y:640},
    ], 14)
    : allCanvases[current];
  const sessions = options.sessions || [allRows['graph-a'], allRows['graph-b']];
  const mountedReceiptCanvas = id => allCanvases[id];
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
    get:async url => {
      if (url === '/api/universal/node-library?templates=1') return {ok:true,templates:[]};
      calls.canvas += 1;
      if (deferredCanvasRead) {
        const held = deferredCanvasRead;
        deferredCanvasRead = null;
        await held.promise;
      }
      if (failRead) throw new Error('The canvas could not be read.');
      return currentCanvas();
    },
    post:async () => { throw new Error('unexpected post'); },
    projectCanvas:projectStudioCanvas,
  });
  win.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(currentCanvas());
  win.ARCHHUB_GET_CANVAS = async () => {
    calls.canvas += 1;
    if (deferredCanvasRead) {
      const held = deferredCanvasRead;
      deferredCanvasRead = null;
      await held.promise;
    }
    return currentCanvas();
  };
  let initializingCanvas = true;
  win.ARCHHUB_GRAPH_OPEN = async id => {
    calls.open.push(id);
    if (!initializingCanvas && typeof options.openGraph === 'function') {
      return options.openGraph(id, {
        setCurrent:value => { current = value; },
        sessions, graphRows:allRows, receiptCanvas:mountedReceiptCanvas,
      });
    }
    if (options.openDeferred) await options.openDeferred.promise;
    current = id;
    return {ok:true, graphs:[...sessions, allRows[id]].filter((row, index, rows) =>
      rows.findIndex(other => other.id === row.id) === index), current_graph:id, canvas:mountedReceiptCanvas(id)};
  };
  win.ARCHHUB_GRAPH_CREATE = async title => {
    calls.create.push(title);
    if (options.createDeferred) await options.createDeferred.promise;
    if (typeof options.createGraph === 'function') {
      const created = await options.createGraph(title, {
        setCurrent:value => { current = value; },
        sessions, graphRows:allRows, receiptCanvas:mountedReceiptCanvas,
      });
      return created;
    }
    current = 'graph-c';
    return {ok:true, graphs:[...sessions, allRows['graph-c']], current_graph:'graph-c',
      graph:allRows['graph-c'], canvas:mountedReceiptCanvas('graph-c')};
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
      if (typeof options.agentResult === 'function') return options.agentResult(url, body);
      return options.agentResult || {ok:true, answer:'bridge ok', applied:[], delivery:{state:'replied', request_id:body.request_id}};
    };
    win.eval('const jpost = window.jpost;\n' + bridgeSource.slice(start, end));
  }
  if (Number.isFinite(options.agentTimeoutMs)) win.ARCHHUB_AGENT_TURN_TIMEOUT_MS = options.agentTimeoutMs;
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node,
    conversation_root:String(node).startsWith('graph:') ? 'graph-room' : (node === 'session-a' ? 'room-a' : null),
    rows:node === 'session-a' ? [{id:'m1', who:'Agent', text:'Session conversation lives here.', time:'2026-10-10T10:00:00Z', kind:'message'}] : [],
    has_older:false});
  win.ARCHHUB_HISTORY = async operation => { calls.history.push(operation); return {ok:true}; };
  win.AH_LIBRARY = [{cat:'logic', items:[{id:'test-node', title:'Test node', sub:'Noop node', engine:'engine:noop'}]}];
  win.ARCHHUB_LIVE = {sessions, currentGraph:current, hosts:[], connectors:[],
    graph:win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.graph, memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  // This court exercises Canvas; boot now opens the distinct SCREENS1 Library.
  win.ReactDOM.flushSync(() => win.document.querySelector('[data-app-rail] [data-rail-panel="Canvas"]').click());
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 80));
  await settle();
  calls.open.length = 0; calls.canvas = 0;
  initializingCanvas = false;
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const button = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const buttonIncludes = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.includes(label));
  const sessionMenu=()=>{
    const toggle=win.document.querySelector('[data-session-header] button[title^="Sessions"]');
    if(toggle?.getAttribute('aria-expanded')!=='true')win.ReactDOM.flushSync(()=>toggle.click());
    return win.document.querySelector('[data-session-menu]');
  };
  const byTitle = title => title==='New session' ? [...sessionMenu().querySelectorAll('button')].find(node=>node.textContent.trim()==='New session') : [...win.document.querySelectorAll('button')].find(node => node.title === title);
  const click = node => win.ReactDOM.flushSync(() => node.click());
  const tabCount=()=>{const menu=sessionMenu(),count=menu.querySelectorAll('button[aria-label^="Close "]').length;win.ReactDOM.flushSync(()=>win.document.querySelector('[data-session-header] button[title^="Sessions"]').click());return count;};
  const transform = () => [...(win.document.querySelector('[role="region"][aria-label="Workflow canvas"]')?.children || [])].find(node=>node.style.transform.startsWith('translate3d('))?.style.transform || '';
  const byTitleStarts = title => [...win.document.querySelectorAll('button')].find(node => String(node.title || '').startsWith(title));
  const type = (input, value) => {
    const set = Object.getOwnPropertyDescriptor(input.tagName==='TEXTAREA'?win.HTMLTextAreaElement.prototype:win.HTMLInputElement.prototype, 'value').set;
    win.ReactDOM.flushSync(() => { set.call(input, value); input.dispatchEvent(new win.Event('input', {bubbles:true})); });
  };
  return {win, doc:win.document, calls, navigationErrors, button, buttonIncludes, byTitle, byTitleStarts, click, type, settle, close,
    failNextRead:() => { failRead = true; }, deferNextCanvasRead:promise => { deferredCanvasRead = promise; },
    tabCount, transform, sessionMenu};
}

function openHome(studio) {
  const home = studio.byTitle('All sessions') || studio.doc.querySelector('[data-workshop72-rail] [role="link"][aria-label="Home"]');
  assert.ok(home, 'Home button exists');
  studio.click(home);
}

function openWorkshopFromHub(studio) {
  const settings = studio.doc.querySelector('[data-app-rail] [aria-label="Settings"]') || studio.byTitle('Settings');
  assert.ok(settings, 'Settings rail control exists');
  studio.click(settings);
  const shell = studio.doc.querySelector('[data-settings54-shell]');
  assert.ok(shell, 'Settings opens for Workshop Hub entry');
  const group = [...shell.querySelectorAll('[data-settings54-group-title]')].find(node => node.textContent.trim() === 'Connections');
  assert.ok(group, 'Connections owns Hub');
  studio.click(group.closest('button'));
  const hub = [...shell.querySelectorAll('[data-settings54-capability-nav] button')].find(node => node.textContent.trim() === 'Hub');
  assert.ok(hub, 'Hub is visible under Connections');
  studio.click(hub);
  const workshop = shell.querySelector('[data-tool-card="workshop"]');
  assert.ok(workshop, 'Hub exposes Workshop tool card');
  studio.click(workshop);
}

function assertHomeView(studio, detail) {
  assert.ok(studio.doc.querySelector('[data-home-design="082"]'), detail + ': replacement Home is visible');
  assert.equal(studio.doc.querySelectorAll('[role="region"][aria-label="Workflow canvas"]').length, 0,
    detail + ': canvas is not visible');
}

function graphButton(studio, title) {
  if (studio.doc.querySelector('[data-app-rail] [data-rail-panel="Chats"]')?.getAttribute('aria-current') !== 'true') {
    studio.click(studio.doc.querySelector('[data-app-rail] [data-rail-panel="Chats"]'));
  }
  const found = [...studio.doc.querySelectorAll('[data-left-panel] button')].find(node => node.textContent.includes(title));
  assert.ok(found, 'Chats exposes the authenticated graph: ' + title);
  return found;
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
  assert.equal(studio.doc.querySelectorAll('textarea[aria-label="Ask selection"]').length, 1,
    detail + ': one selection composer is mounted');
  assert.equal(studio.doc.querySelectorAll('[data-model-indicator]').length, 1,
    detail + ': one model indicator is mounted');
}

function showChat(studio) {
  const chat = [...studio.doc.querySelectorAll('button')].find(node => node.textContent.trim() === 'Chat');
  if (chat) studio.click(chat);
  assert.ok(studio.doc.querySelector('textarea[aria-label="Ask selection"]'), 'selection-panel chat composer exists');
}

test('opening a session from Home applies the graph-open receipt in place: one canvas re-read, no reload', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    openHome(studio);
    await studio.settle();
    studio.calls.canvas = 0;
    studio.click(graphButton(studio, 'Graph Beta'));
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

test('History node projects action history rows, filters, jumps, and uses existing undo', async () => {
  const studio = await mountStudio({current:'history', sessions:[graphRows.history]});
  try {
    showCanvas(studio);
    await studio.settle();
    studio.click(studio.doc.querySelector('[data-canvas-add] button[aria-label="Open node library"]'));
    await studio.settle();
    assert.match(studio.doc.body.textContent, /App/);
    assert.match(studio.doc.body.textContent, /History/);
    studio.click(studio.doc.querySelector('button[aria-label="Close library"]'));
    await studio.settle();
    const historyCard = studio.doc.querySelector('.lm-node[data-node-id="history-node"]');
    assert.ok(historyCard, 'History is a real canvas node');
    assert.equal(historyCard.querySelectorAll('[data-history-row]').length, 5, 'card shows latest five rows');
    const cardRows = [...historyCard.querySelectorAll('[data-history-row]')];
    assert.ok(cardRows.every(row => Number.parseFloat(row.style.fontSize) >= 11), 'History card rows stay at least 11px');
    assert.ok(cardRows.every(row => row.style.fontFamily), 'History card rows use mono sizing tokens');
    assert.ok(cardRows.every(row => !/inkMuted/i.test(row.getAttribute('style') || '')), 'History card rows do not use inkMuted');
    assert.doesNotMatch(historyCard.textContent, /node-h/, 'History card never renders raw target_root ids');
    assert.doesNotMatch(historyCard.textContent, /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/, 'History card uses short timestamps');
    assert.match(historyCard.textContent, /\d{2}:\d{2} · today/, 'History card shows today timestamps as short local time');
    const moreButton = [...historyCard.querySelectorAll('button')].find(button => button.textContent.trim() === '+1 more');
    assert.ok(moreButton, '+N more is an inspector-opening button');
    studio.click(moreButton);
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-history-inspector="true"]'), '+N more opens the History inspector');
    assert.equal(studio.doc.querySelector('.lm-node[data-node-id="history-node"]')?.getAttribute('data-selected'), 'true');
    studio.click(historyCard);
    await studio.settle();
    let inspector = studio.doc.querySelector('[data-history-inspector="true"]');
    assert.ok(inspector, 'inspector shows the full History list');
    assert.equal(inspector.querySelectorAll('[data-history-row]').length, 6);
    assert.ok(studio.doc.querySelector('[data-node-inspector] [data-fork-button]'), 'History preserves the existing node Properties and actions');
    assert.ok([...inspector.querySelectorAll('[data-history-row]')].every(row => Number.parseFloat(row.style.fontSize) >= 11), 'History inspector rows stay at least 11px');
    assert.doesNotMatch(inspector.textContent, /node-h/, 'History inspector never renders raw target_root ids');
    assert.doesNotMatch(inspector.textContent, /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/, 'History inspector uses short timestamps');
    assert.match(inspector.textContent, /\d{2}:\d{2} · today/, 'History inspector shows today timestamps as short local time');
    const undoButtons = [...inspector.querySelectorAll('button')].filter(button => button.textContent.trim() === 'Undo last');
    assert.equal(undoButtons.length, 1, 'only newest applied transaction exposes Undo last');
    studio.click([...inspector.querySelectorAll('button')].find(button => button.textContent === 'Agents'));
    await studio.settle();
    inspector = studio.doc.querySelector('[data-history-inspector="true"]');
    assert.equal(inspector.querySelectorAll('[data-history-row]').length, 4);
    studio.click([...inspector.querySelectorAll('button')].find(button => button.textContent === 'Undo last'));
    await studio.settle();
    assert.deepEqual(studio.calls.history, ['undo']);
    studio.click([...studio.doc.querySelectorAll('[data-history-inspector="true"] button')].find(button => button.textContent === 'Jump to'));
    await studio.settle();
    assert.equal(studio.doc.querySelector('.lm-node[data-node-id="node-h"]')?.getAttribute('data-selected'), 'true');
    const titleOnly = studio.doc.querySelector('.lm-node[data-node-id="history-title-only"]');
    assert.ok(titleOnly, 'fixture includes a user node titled History');
    assert.equal(titleOnly.querySelector('[data-history-card="true"]'), null, 'user node titled History is not app History');
  } finally { studio.close(); }
});

test('opening a session from the Home rail applies the receipt; the chat composer lives in the selection panel', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    studio.click(studio.byTitle('All sessions'));
    await studio.settle();
    studio.calls.canvas = 0;
    studio.click(graphButton(studio, 'Graph Beta'));
    await studio.settle();
    showChat(studio);
    await studio.settle();
    assert.deepEqual(studio.calls.open, ['graph-b']);
    assert.equal(studio.calls.canvas, 1, 'the same page re-reads its canvas once; the receipt canvas is not applied');
    assert.equal(studio.navigationErrors.length, 0, 'no reload/assign/replace navigation');
    assert.match(studio.doc.body.textContent, /Graph Beta/);
    assert.equal(studio.doc.querySelectorAll('textarea[aria-label="Ask selection"]').length, 1,
      'the moved chat composer is the one selection-panel input');
  } finally { studio.close(); }
});

test('creating a new session opens the graph-create receipt in place without reloading or re-posting', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    studio.calls.canvas = 0;
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    assert.deepEqual(studio.calls.create, ['New session']);
    assert.deepEqual(studio.calls.open, [], 'create receipt is not re-posted as graph-open');
    assert.equal(studio.calls.canvas, 1, 'one in-place canvas re-read after create');
    assert.equal(studio.navigationErrors.length, 0, 'no reload/assign/replace navigation');
    assert.match(studio.doc.body.textContent, /Created Graph/);
    assert.match(studio.doc.body.textContent, /Created node/);
  } finally { studio.close(); }
});

test('Sessions menu New session creates a second graph tab in place and keeps the first tab', async () => {
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
    assert.match(studio.sessionMenu().textContent, /Graph Alpha/);
    assert.match(studio.sessionMenu().textContent, /Created Graph/);
  } finally { studio.close(); }
});

test('Sessions menu New session opens a graph-create rows-only receipt as the active New session tab', async () => {
  const newId = 'app:composition:new-session';
  const row = {id:newId, title:'New session', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'0 nodes', model:''};
  const studio = await mountStudio({
    graphRows:{[newId]:row},
    canvases:{[newId]:canvas(newId, 'New session', {id:'created-empty', label:'Created empty node', x:120, y:130}, 19)},
    createGraph:async (_title, helpers) => {
      helpers.setCurrent(newId);
      return {ok:true, graphs:[...helpers.sessions, row], current_graph:newId,
        canvas:helpers.receiptCanvas(newId), reason:'Visible scope changed'};
    },
  });
  try {
    await studio.settle();
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    assert.deepEqual(studio.calls.create, ['New session']);
    assert.equal(studio.tabCount(), 2, 'the created graph opens as a second tab');
    const tab=studio.sessionMenu().querySelector('button[aria-label="Close New session"]')?.parentElement.querySelector('button');
    assert.ok(tab,'created graph is present in the Sessions menu');
    assert.equal(studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.canvas.scope.current,newId,'created graph is the active owner scope');
    assert.equal(studio.doc.querySelector('[data-session-header] button[title^="Sessions"]').textContent.trim(),'New session','breadcrumb names the active graph');
    assert.match(tab.textContent,/New session/);
  } finally { studio.close(); }
});

test('after a create whose canvas refresh fails, the Sessions menu New session never posts a second create', async () => {
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

test('New session create cannot overwrite Home after the graph-create bridge resolves', async () => {
  const createGate = deferred();
  const studio = await mountStudio({createDeferred:createGate});
  try {
    await studio.settle();
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    openHome(studio);
    await studio.settle();
    createGate.resolve();
    await studio.settle();
    await studio.settle();
    assertHomeView(studio, 'Home clicked while New session create was pending');
    assert.deepEqual(studio.calls.create, ['New session'], 'New session create posts exactly once');
    assert.deepEqual(studio.calls.open, [], 'created graph is not re-posted as graph-open');
  } finally { studio.close(); }
});

test('New session create cannot overwrite Home after the create canvas refresh resolves', async () => {
  const refreshGate = deferred();
  const studio = await mountStudio();
  try {
    await studio.settle();
    studio.deferNextCanvasRead(refreshGate);
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    openHome(studio);
    await studio.settle();
    refreshGate.resolve();
    await studio.settle();
    await studio.settle();
    assertHomeView(studio, 'Home clicked while New session refresh was pending');
    assert.deepEqual(studio.calls.create, ['New session'], 'New session create posts exactly once');
    assert.deepEqual(studio.calls.open, [], 'created graph is not re-posted as graph-open');
  } finally { studio.close(); }
});

test('Sessions-menu graph creation cannot overwrite a session opened through Chats before graph-create resolves', async () => {
  const createGate = deferred();
  const studio = await mountStudio({createDeferred:createGate});
  try {
    await studio.settle();
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    studio.click(graphButton(studio, 'Graph Beta'));
    await studio.settle();
    createGate.resolve();
    await studio.settle();
    await studio.settle();
    showCanvas(studio);
    assert.deepEqual(studio.calls.create, ['New session'], 'Workspace create posts exactly once');
    assert.deepEqual(studio.calls.open, ['graph-b'], 'the clicked session is opened once');
    assert.match(studio.doc.body.textContent, /Graph Beta/);
    assert.match(studio.doc.body.textContent, /Beta node/);
    assert.doesNotMatch(studio.doc.body.textContent, /Created node/);
  } finally { studio.close(); }
});

test('Workshop tool wins over an earlier pending session open', async () => {
  const openGate = deferred();
  const studio = await mountStudio({openDeferred:openGate, workshops:[{root:'room-a', label:'Wall room', is_general:false}]});
  try {
    await studio.settle();
    openHome(studio);
    await studio.settle();
    studio.click(graphButton(studio, 'Graph Beta'));
    await studio.settle();
    openWorkshopFromHub(studio);
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-workshop-s1]'), 'Workshop opens while graph-open is pending');
    openGate.resolve();
    await studio.settle();
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-workshop-s1]'), 'Workshop stays after graph-open resolves');
    assert.deepEqual(studio.calls.open, ['graph-b'], 'the earlier session open resolves once');
  } finally { studio.close(); }
});

test('a stale rejected graph open cannot clear a later successful graph open', async () => {
  const staleOpen = deferred();
  const studio = await mountStudio({openGraph:async (id, api) => {
    if (id === 'graph-a') await staleOpen.promise;
    api.setCurrent(id);
    return {ok:true, graphs:[api.sessions[0], api.graphRows[id]].filter((row, index, rows) =>
      rows.findIndex(other => other.id === row.id) === index), current_graph:id, canvas:api.receiptCanvas(id)};
  }});
  try {
    await studio.settle();
    openHome(studio);
    await studio.settle();
    studio.click(graphButton(studio, 'Graph Alpha'));
    await studio.settle();
    studio.click(graphButton(studio, 'Graph Beta'));
    await studio.settle();
    showCanvas(studio);
    assert.match(studio.doc.body.textContent, /Graph Beta/);
    staleOpen.reject(new Error('old graph refused'));
    await studio.settle();
    showCanvas(studio);
    assert.match(studio.doc.body.textContent, /Graph Beta/);
    assert.doesNotMatch(studio.doc.body.textContent, /old graph refused|Refresh graphs/);
    assert.deepEqual(studio.calls.open, ['graph-a', 'graph-b']);
  } finally { studio.close(); }
});

test('a stale rejected graph open cannot clear Workshop', async () => {
  const openGate = deferred();
  const studio = await mountStudio({openDeferred:openGate, workshops:[{root:'room-a', label:'Wall room', is_general:false}]});
  try {
    await studio.settle();
    openHome(studio);
    await studio.settle();
    studio.click(graphButton(studio, 'Graph Beta'));
    await studio.settle();
    openWorkshopFromHub(studio);
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-workshop-s1]'), 'Workshop opens while graph-open is pending');
    openGate.reject(new Error('old graph refused'));
    await studio.settle();
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-workshop-s1]'), 'Workshop stays after graph-open rejects');
    assert.doesNotMatch(studio.doc.body.textContent, /old graph refused|Refresh graphs/);
  } finally { studio.close(); }
});

test('a stale rejected New session create cannot attach an error to Home', async () => {
  const createGate = deferred();
  const studio = await mountStudio({createDeferred:createGate});
  try {
    await studio.settle();
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    openHome(studio);
    await studio.settle();
    createGate.reject(new Error('old create refused'));
    await studio.settle();
    await studio.settle();
    assertHomeView(studio, 'Home clicked while New session create was pending');
    assert.doesNotMatch(studio.doc.body.textContent, /old create refused|Refresh the graph list before creating again/);
    assert.deepEqual(studio.calls.create, ['New session'], 'New session create posts exactly once');
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
    studio.click(studio.doc.querySelector('[data-canvas-add] button[aria-label="Open node library"]'));
    await studio.settle();
    const search = studio.doc.querySelector('[data-node-library-overlay] input[placeholder^="Search"]');
    assert.ok(search, 'current Library search field is mounted');
    studio.type(search, 'Test node');
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
    studio.click(graphButton(studio, 'Graph Beta'));
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
    assert.equal(studio.doc.querySelectorAll('textarea[aria-label="Ask selection"]').length, 1,
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
    assert.match(studio.doc.querySelector('textarea[aria-label="Ask selection"]').placeholder, /ask about this node/i);
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
    assert.equal(studio.doc.querySelectorAll('textarea[aria-label="Ask selection"]').length, 1,
      'exactly one composer is mounted');
    let input = studio.doc.querySelector('textarea[aria-label="Ask selection"]');
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
    studio.click([...panel().querySelectorAll('[role="tab"]')].find(tab=>tab.textContent.trim()==='Chat'));
    await studio.settle();
    assert.match(panel().querySelector('[data-model-indicator]')?.textContent || '', /Line Watcher/);
    input = studio.doc.querySelector('textarea[aria-label="Ask selection"]');
    studio.type(input, 'node hello');
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.equal(studio.calls.agent[1][0], '/api/universal/agent');
    assert.equal(studio.calls.agent[1][1].node, 'line-watcher');
    assert.equal(studio.calls.agent[1][1].graph, undefined);
    assert.equal(studio.calls.agent[1][1].model, 'openrouter/free');
  } finally { studio.close(); }
});

test('real agent bridge bounds unresolved turns and surfaces ok false', async () => {
  const timeoutStudio = await mountStudio({current:'fresh', sessions:[graphRows.fresh], realAgentBridge:true,
    agentResult:() => new Promise(() => {})});
  try {
    await assert.rejects(
      () => timeoutStudio.win.ARCHHUB_AGENT('hello', 'openrouter/free', {graph:true, graph_id:'fresh', turn_timeout_ms:5}),
      /did not answer within 45 seconds/
    );
  } finally { timeoutStudio.close(); }

  const refusedStudio = await mountStudio({current:'fresh', sessions:[graphRows.fresh], realAgentBridge:true,
    agentResult:() => ({ok:false, error:'No free model answered right now. Try again shortly.'})});
  try {
    await assert.rejects(
      () => refusedStudio.win.ARCHHUB_AGENT('hello', 'openrouter/free', {graph:true, graph_id:'fresh', turn_timeout_ms:5}),
      /No free model answered right now/
    );
  } finally { refusedStudio.close(); }
});

test('composer timeout renders an error line with retry', async () => {
  const studio = await mountStudio({current:'fresh', sessions:[graphRows.fresh], realAgentBridge:true,
    agentTimeoutMs:5, agentResult:() => new Promise(() => {})});
  try {
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const input = studio.doc.querySelector('textarea[aria-label="Ask selection"]');
    studio.type(input, 'graph hello');
    studio.flush = callback => studio.win.ReactDOM.flushSync(callback);
    studio.flush(() => input.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.match(studio.doc.body.textContent, /did not answer within 45 seconds/);
    assert.ok([...studio.doc.querySelectorAll('button')].some(button => button.textContent.trim() === 'Retry'));
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
    assert.equal(panel().querySelector('[data-model-indicator]'),null,'Properties does not mount the Chat-only composer');
    assert.match(panel().textContent,/Graph Alpha/);
    studio.click(studio.doc.querySelector('.lm-node[data-node-id="session-a"]'));
    await studio.settle();
    assert.match(panel().textContent, /Door tags L3/);
    assert.ok(panel().textContent.indexOf('Chat') < panel().textContent.indexOf('Properties'),
      'session node shows Chat before Properties');
    assert.equal(panel().querySelector('[role="tab"][aria-selected="true"]')?.textContent.trim(), 'Chat');
    assert.deepEqual([...panel().querySelectorAll('section[aria-label="Properties"], section[aria-label="Chat"], section[aria-label="Runs"]')]
      .map(section => section.getAttribute('aria-label')), ['Chat']);
    assert.match(studio.doc.querySelector('textarea[aria-label="Ask selection"]').placeholder, /reply in this session/i);
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

test('Studio header has no Chat Workshop System tabs, selection resets per session, and Hub Workshop card still opens', async () => {
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
    studio.click(graphButton(studio, 'Graph Beta'));
    await studio.settle();
    showCanvas(studio);
    await studio.settle();
    const panelText = studio.doc.querySelector('aside[aria-label="Selection inspector"]').textContent;
    assert.match(panelText, /GRAPH|Graph Beta/);
    assert.equal(/Alpha node/.test(panelText), false, 'node selection from Graph Alpha did not leak into Graph Beta');
    openWorkshopFromHub(studio);
    await studio.settle();
    assert.match(studio.doc.body.textContent, /Workshop|Wall room/, 'Hub Workshop card path still opens');
  } finally { studio.close(); }
});

test('leaving Workshop through Studio, session reopen, or New session restores canvas selection mode', async () => {
  const studio = await mountStudio({workshops:[{root:'room-a', label:'Wall room', is_general:false}]});
  try {
    await studio.settle();
    openWorkshopFromHub(studio);
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-workshop-s1]'), 'Workshop is open');

    openHome(studio);
    studio.click(graphButton(studio, 'Graph Alpha'));
    await studio.settle();
    assertCanvasSelectionOnly(studio, 'same session reopen from Workshop');

    openWorkshopFromHub(studio);
    await studio.settle();
    const canvasRoute = studio.doc.querySelector('[data-workshop72-rail] [role="link"][aria-label="Canvas"]');
    assert.ok(canvasRoute, 'Workshop exposes its Canvas navigation route');
    studio.click(canvasRoute);
    await studio.settle();
    studio.click(studio.byTitle('New session'));
    await studio.settle();
    assertCanvasSelectionOnly(studio, 'New session from Workshop');
  } finally { studio.close(); }
});
