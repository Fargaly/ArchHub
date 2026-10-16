const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..');
const lmPath = path.join(root, 'nodelang/studio/studio-lm.jsx');
const authorityPath = path.join(root, 'nodelang/studio/studio-authority.js');
const lmSource = fs.readFileSync(lmPath, 'utf8');

const LM = new Proxy({}, {get:(_, key) => {
  if (key === 'rad') return {xs:3, sm:5, md:6, lg:8, xl:10};
  if (key === 'sp') return {xs:4, sm:8, md:12, lg:16};
  return 'token-' + String(key);
}});

function shortcutSlice() {
  const start = lmSource.indexOf('const studioShortcut =');
  const end = lmSource.indexOf('// An ordinary canvas edit', start);
  assert.ok(start > 0 && end > start);
  return lmSource.slice(start, end);
}

function canvasSlice() {
  const start = lmSource.indexOf('const SOCKET_TOP =');
  const end = lmSource.indexOf('const NodeStateDot =', start);
  assert.ok(start > 0 && end > start);
  return lmSource.slice(start, end) + require('./workshop72_node_helpers.cjs').nodePreviewSource(lmSource);
}

async function mountGroupCanvas() {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/'});
  Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetWidth', {configurable:true, get() { return 220; }});
  Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetHeight', {configurable:true, get() { return 110; }});
  dom.window.HTMLElement.prototype.getBoundingClientRect = function() {
    return this.getAttribute('role') === 'region'
      ? {width:1000, height:760, left:0, top:0, right:1000, bottom:760}
      : {width:220, height:110, left:0, top:0, right:220, bottom:110};
  };
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const ports = {ins:[{id:'in', t:'any', label:'in'}], outs:[{id:'out', t:'any', label:'out'}]};
  let snapshot = {graph:{nodes:[
    {id:'G', cat:'group', kind:'group', live:true, x:300, y:40, w:224, h:120, title:'Workshop', sub:'group · 2 agents · 1 task',
      params:[], composition:true, openable:true, memberCount:2, members:[{id:'m1', title:'One'}, {id:'m2', title:'Two'}], ...ports},
    {id:'m1', cat:'logic', live:true, x:40, y:60, w:220, h:110, title:'One', sub:'node', params:[], group:'G', ...ports},
    {id:'m2', cat:'logic', live:true, x:40, y:150, w:220, h:110, title:'Two', sub:'node', params:[], group:'G', ...ports},
    {id:'out', cat:'logic', live:true, x:420, y:150, w:220, h:110, title:'Outside', sub:'node', params:[], ...ports},
    {id:'S', cat:'session', kind:'session', live:true, x:700, y:80, w:260, h:150, title:'Tag doors', sub:'session · 3 nodes',
      params:[], openable:true, ...ports},
  ], wires:[
    {id:'w-in', from:['m1', 'out'], to:['m2', 'in']},
    {id:'w-out', from:['m2', 'out'], to:['out', 'in']},
  ]}, canvas:{revision:1, scope:{current:'scope', trail:[{root:'parent', label:'Parent'}, {root:'G', label:'Workshop'}]}, authorization:{subject:'owner', session:'s'}}};
  const openCalls = [];
  const membershipHistory = [];
  const memberWrites = [];
  const layoutWrites = [];
  const authority = {
    getSnapshot:() => ({...snapshot, canvas:snapshot.canvas}),
    moveMember:async (member, fromGroup, toGroup) => {
      membershipHistory.push({member, fromGroup, toGroup});
      if (fromGroup && !toGroup) memberWrites.push({url:'/api/universal/interaction',
        body:{membership:{member, from_group:fromGroup, to_group:toGroup}}});
      snapshot = {...snapshot, canvas:{...snapshot.canvas, revision:snapshot.canvas.revision + 1},
        graph:{...snapshot.graph, nodes:snapshot.graph.nodes.map(node => {
          if (node.id === member) return {...node, group:toGroup || ''};
          if (node.id === fromGroup) {
            const members = (node.members || []).filter(row => row.id !== member);
            return {...node, members, memberCount:members.length};
          }
          if (node.id === toGroup) {
            const leaving = snapshot.graph.nodes.find(row => row.id === member);
            const members = [...(node.members || []), {id:member, title:leaving?.title || member}];
            return {...node, members, memberCount:members.length};
          }
          return node;
        })}};
      return snapshot;
    },
    moveMany:async positions => {
      layoutWrites.push(positions);
      snapshot = {...snapshot, graph:{...snapshot.graph, nodes:snapshot.graph.nodes.map(node =>
        positions[node.id] ? {...node, ...positions[node.id]} : node)}};
      return snapshot;
    },
    undo:async () => {
      const last = membershipHistory.pop();
      if (last) snapshot = {...snapshot, canvas:{...snapshot.canvas, revision:snapshot.canvas.revision + 1},
        graph:{...snapshot.graph, nodes:snapshot.graph.nodes.map(node => {
          if (node.id === last.member) return {...node, group:last.fromGroup || ''};
          if (node.id === last.fromGroup) {
            const leaving = snapshot.graph.nodes.find(row => row.id === last.member);
            const members = [...(node.members || []), {id:last.member, title:leaving?.title || last.member}];
            return {...node, members, memberCount:members.length};
          }
          if (node.id === last.toGroup) {
            const members = (node.members || []).filter(row => row.id !== last.member);
            return {...node, members, memberCount:members.length};
          }
          return node;
        })}};
      return snapshot;
    },
    open:id => { openCalls.push(['authority', id]); return Promise.resolve(snapshot); },
  };
  dom.window.ARCHHUB_STUDIO_AUTHORITY = authority;
  dom.window.ARCHHUB_SCOPE_OPEN = route => { openCalls.push(route); };
  const context = vm.createContext({React, LM, window:dom.window, document:dom.window.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope',
    isSessionInspectorNode:node => /^session$/i.test(String(node?.kind || node?.assembly || node?.cat || '')),
    studioCategory:cat => ({col:'token-cat', icon:'+', label:String(cat).toUpperCase()}), WIRE:{any:'token-wire'},
    NodeBody:() => null, CanvasToolbar, FloatingComposer:() => null, CanvasAddBox:() => null, MiniMap:() => null, Socket:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({}),
    setTimeout:dom.window.setTimeout.bind(dom.window), clearTimeout:dom.window.clearTimeout.bind(dom.window)});
  function CanvasToolbar(props) {
    return React.createElement('button', {type:'button', 'aria-label':'Undo', disabled:props.undo.disabled, onClick:props.undo.run}, 'Undo');
  }
  vm.runInContext(transformSync(shortcutSlice() + canvasSlice() + '\nglobalThis.NodeCanvas = NodeCanvas;',
    {loader:'jsx', format:'cjs'}).code, context);
  const rootNode = createRoot(dom.window.document.getElementById('root'));
  await React.act(async () => rootNode.render(React.createElement(context.NodeCanvas,
    {focusId:null, setFocusId:() => {}, setLibraryOpen:() => {}, userNodes:[], addNodeFromLibrary:() => {}, model:null})));
  const fire = (target, type, init) => target.dispatchEvent(new dom.window.MouseEvent(type, {bubbles:true, cancelable:true, ...init}));
  const pointer = (target, type, init = {}) => {
    const done = type === 'pointerup' || type === 'pointercancel';
    const event = new dom.window.MouseEvent(type, {bubbles:true, cancelable:true,
      button:0, buttons:done ? 0 : 1, clientX:0, clientY:0, ...init});
    for (const [key, value] of Object.entries({
      pointerId:init.pointerId ?? 7,
      pointerType:init.pointerType ?? 'mouse',
      isPrimary:init.isPrimary ?? true,
    })) {
      if (!(key in event)) Object.defineProperty(event, key, {value});
    }
    return target.dispatchEvent(event);
  };
  const key = (target, type, init) => target.dispatchEvent(new dom.window.KeyboardEvent(type, {bubbles:true, cancelable:true, ...init}));
  const card = id => dom.window.document.querySelector('.lm-node[data-node-id="' + id + '"]');
  const canvas = () => dom.window.document.querySelector('[role="region"]') || dom.window.document;
  return {doc:dom.window.document, card, wireCount:() => dom.window.document.querySelectorAll('.lm-wires g').length,
    drag:async (id, dx, dy) => {
      await React.act(async () => fire(card(id).children[0], 'mousedown', {button:0, clientX:0, clientY:0}));
      await React.act(async () => fire(dom.window.document, 'mousemove', {clientX:dx, clientY:dy}));
      await React.act(async () => fire(dom.window.document, 'mouseup', {}));
    },
    chipDrag:async (group, member, dx, dy) => {
      const chip = card(group).querySelector('[data-member-chip="' + member + '"]');
      await React.act(async () => pointer(chip, 'pointerdown', {clientX:0, clientY:0}));
      await React.act(async () => pointer(canvas(), 'pointermove', {clientX:dx, clientY:dy}));
      await React.act(async () => pointer(dom.window, 'pointerup', {clientX:dx, clientY:dy}));
    },
    chipCancel:async (group, member, dx, dy) => {
      const chip = card(group).querySelector('[data-member-chip="' + member + '"]');
      await React.act(async () => pointer(chip, 'pointerdown', {clientX:0, clientY:0}));
      await React.act(async () => pointer(canvas(), 'pointermove', {clientX:dx, clientY:dy}));
      await React.act(async () => pointer(dom.window, 'pointercancel', {clientX:dx, clientY:dy}));
    },
    key:async (target, event, init) => React.act(async () => key(target, event, init)),
    click:async target => React.act(async () => target.click()),
    act:React.act,
    openCalls, membershipHistory, memberWrites, layoutWrites, authority,
    undo:async () => React.act(async () => dom.window.document.querySelector('button[aria-label="Undo"]').click()),
    close:async () => { await React.act(async () => rootNode.unmount()); dom.window.close();
      global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; },
  };
}

test('collapsed group card renders stacked edges and member chips', async () => {
  const view = await mountGroupCanvas();
  try {
    const group = view.card('G');
    assert.equal(group.getAttribute('data-group-card'), 'true');
    assert.equal(group.querySelectorAll('[data-stacked-edge]').length, 2);
    assert.equal(group.querySelectorAll('[data-member-chip]').length, 2);
    assert.ok(group.querySelector('[data-boundary-sockets]').textContent.includes('1 in'));
  } finally { await view.close(); }
});

test('chip drag-off writes authority membership and undo restores it', async () => {
  const view = await mountGroupCanvas();
  try {
    assert.equal(view.card('m2').getAttribute('data-group'), 'G');
    assert.equal(view.wireCount(), 2);
    await view.chipDrag('G', 'm2', 80, -40);
    assert.deepEqual(view.membershipHistory.at(-1), {member:'m2', fromGroup:'G', toGroup:''});
    assert.equal(view.memberWrites.filter(row => row.url === '/api/universal/interaction').length, 1);
    assert.equal(view.card('G').querySelectorAll('[data-member-chip]').length, 1);
    assert.equal(view.card('m2').getAttribute('data-group'), null);
    assert.equal(view.wireCount(), 2);
    await view.act(async () => view.authority.getSnapshot());
    assert.equal(view.card('m2').getAttribute('data-group'), null);
    await view.undo();
    assert.equal(view.card('G').querySelectorAll('[data-member-chip]').length, 2);
    assert.equal(view.card('m2').getAttribute('data-group'), 'G');
    assert.equal(view.wireCount(), 2);
  } finally { await view.close(); }
});

test('chip drag-off pointercancel cleans up without authority or layout writes', async () => {
  const view = await mountGroupCanvas();
  try {
    assert.equal(view.card('m2').getAttribute('data-group'), 'G');
    assert.equal(view.wireCount(), 2);
    await view.chipCancel('G', 'm2', 80, -40);
    assert.equal(view.membershipHistory.length, 0);
    assert.equal(view.memberWrites.length, 0);
    assert.equal(view.layoutWrites.length, 0);
    assert.equal(view.card('G').querySelectorAll('[data-member-chip]').length, 2);
    assert.equal(view.card('m2').getAttribute('data-group'), 'G');
    assert.equal(view.wireCount(), 2);
  } finally { await view.close(); }
});

test('dropping a node on a collapsed group card joins through authority', async () => {
  const view = await mountGroupCanvas();
  try {
    assert.equal(view.card('out').getAttribute('data-group'), null);
    await view.drag('out', -20, -60);
    assert.deepEqual(view.membershipHistory.at(-1), {member:'out', fromGroup:'', toGroup:'G'});
    assert.equal(view.card('out').getAttribute('data-group'), 'G');
    assert.equal(view.wireCount(), 2);
  } finally { await view.close(); }
});

test('opened group scope exposes a top drop band and no frame element while dragging', async () => {
  const view = await mountGroupCanvas();
  try {
    await view.act(async () => view.card('m2').children[0].dispatchEvent(new view.doc.defaultView.MouseEvent('mousedown', {bubbles:true, cancelable:true, button:0, clientX:0, clientY:0})));
    assert.ok(view.doc.querySelector('[data-group-drop-band]'));
    assert.equal(view.doc.querySelector('[data-group-frame]'), null);
    await view.act(async () => view.doc.dispatchEvent(new view.doc.defaultView.MouseEvent('mouseup', {bubbles:true, cancelable:true})));
  } finally { await view.close(); }
});

test('collapsed session card selects on click and opens on double click and Enter', async () => {
  const view = await mountGroupCanvas();
  try {
    const session = view.card('S');
    assert.equal(session.getAttribute('data-session-card'), 'true');
    assert.match(session.querySelector('[data-session-ports]').textContent, /Accepts/i);
    assert.match(session.querySelector('[data-session-ports]').textContent, /Emits/i);
    await view.click(session);
    assert.equal(view.openCalls.length, 0);
    assert.equal(session.getAttribute('data-selected'), 'true');
    await view.act(async () => session.dispatchEvent(new view.doc.defaultView.MouseEvent('dblclick', {bubbles:true, cancelable:true})));
    assert.deepEqual(view.openCalls.at(-1), ['authority', 'S']);
    await view.key(session, 'keydown', {key:'Enter'});
    assert.deepEqual(view.openCalls.at(-1), ['authority', 'S']);
  } finally { await view.close(); }
});

test('authority projection creates a session node whose params and tab settings share one source', async () => {
  const source = fs.readFileSync(authorityPath, 'utf8');
  let canvas = {ok:true, root:'session-root', graph_id:'graph-root', revision:1,
    scope:{current_label:'MASTER-001'}, authorization:{browser_sessions:[{root:'session-root'}]},
    configuration:{composer_model:{value:'openrouter/free', available:true, control:'model-control', event_fact_input:'submitted-value'}, relay_mode:'local'},
    interaction_projection:{bindings:[{control:'model-control', interaction:'i', event:'e', event_facts:[]}]},
    nodes:[{id:'workshop', label:'Workshop', category:'group', kind:'group', x:0, y:0, ports:[], properties:[], composition:true}],
    wires:[], workshops:[{root:'workshop', label:'Workshop'}], catalog:[]};
  const context = vm.createContext({URLSearchParams, sessionStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
    crypto:{randomUUID:() => 'cmd', subtle:{digest:async () => new Uint8Array([1])}}, TextEncoder});
  vm.runInContext(source, context);
  const writes = [];
  const api = context.ArchHubStudioAuthority.create({get:async () => canvas, post:async (url, body) => {
    writes.push({url, body});
    canvas = {...canvas, revision:canvas.revision + 1,
      configuration:{...canvas.configuration, composer_model:{...canvas.configuration.composer_model, value:body.event_facts[0].value}}};
    return {ok:true, revision:canvas.revision};
  }});
  await api.load();
  const snapshot = api.getSnapshot();
  const sessionNode = snapshot.graph.nodes.find(node => node.kind === 'session');
  assert.ok(sessionNode, 'new session is projected as a real node');
  assert.ok(sessionNode.contains.includes('workshop'), 'session node contains the Workshop group');
  await api.setProperty(sessionNode.id, 'model', 'lmstudio/local-free');
  assert.equal(writes.at(-1).url, '/api/universal/interaction');
  assert.equal(JSON.stringify(writes.at(-1).body.event_facts), JSON.stringify([{input:'submitted-value', value:'lmstudio/local-free'}]));
  assert.equal(api.getSnapshot().sessions[0].model, 'lmstudio/local-free');
  assert.equal(api.getSnapshot().graph.nodes.find(node => node.kind === 'session').params.find(row => row.k === 'name').editable, false);
  assert.equal(api.getSnapshot().graph.nodes.find(node => node.kind === 'session').params.find(row => row.k === 'relay mode').editable, false);
});
