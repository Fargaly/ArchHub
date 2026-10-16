/* UI audit 2026-09-28 (work/ui-audit): the installed canvas against the accepted design.
     M1  a node's right-click menu holds the design's node actions (atlas-cockpit.jsx ContextMenu,
         node branch) in order; each runs an existing route, or is dashed and says why;
     M2  Delete asks first, then retracts through ARCHHUB_RETRACT; Cancel sends nothing;
     M3  Disconnect all and a wire's "Cut this wire" go through the existing unwire route;
     M4  Duplicate places the same engine card with its rows through ARCHHUB_NODE_CREATE;
     M5  Clear all is live, asks first, and removes every card through the same retract route;
     V1  leaving the canvas (Chat tab) and coming back keeps its pan and zoom;
     V2  wheel zoom stops at 30% and one notch is a gentle step;
     V3  nothing focused dims nothing; a focus lights its neighbours and dims the rest;
     K1  F fits, arrows nudge the selection through the layout save, middle-drag pans;
     U1  Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y, the menu and the toolbar run the graph's own Undo / Redo
         (ARCHHUB_HISTORY -> the canvas history Interaction) and say in plain words what changed;
     U2  with nothing to undo or redo the items are disabled and say so;
     R1  (canvas-perf) pan and zoom are one transform on one layer and the grid does not shift;
         a drag re-renders the moving card only; nothing is dimmed and no wire glows by default. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
const tokens = fs.readFileSync(path.join(root, 'nodelang/studio/tokens.jsx'), 'utf8');
const palette = tokens.slice(tokens.indexOf('window.AH = {'), tokens.indexOf('window.ArchHubTheme ='));
const LM = new Proxy(Object.fromEntries([...palette.matchAll(/^ {2}(\w+):/gm)].map(m => [m[1], 'token-' + m[1]])), {
  get:(held, key) => {
    if (key === 'rad') return {chip:3, xs:3, control:5, sm:5, node:6, md:6, panel:8, lg:8, dialog:10, xl:10, pill:999};
    if (key === 'sp') return {xs:4, sm:8, md:12, lg:16, xl:24};
    if (key === 'fs') return {bodySm:{sz:13, ln:18, wt:400}, bodySmStrong:{sz:13, ln:18, wt:500}, caption:{sz:12, ln:16}, label:{sz:11, ln:14, wt:500, letter:'.04em'}, data:{sz:12, ln:16, wt:400}, dataSm:{sz:11, ln:14, wt:400}};
    if (key === 'icon') return {ui:{size:16, box:20}, category:{size:12, box:20}};
    if (key === 'shadow') return {flat:'none'};
    if (key === 'elev') return {e1:'none',e2:'none'};
    if (key === 'glow') return {warn:'none',accent:'none'};
    if (key === 'dur') return {fast:120, med:180};
    if (typeof key === 'string' && !(key in held)) throw new Error('studio-lm.jsx reads an undefined token: ' + key);
    return held[key];
  }});
const slice = () => {
  const start = source.indexOf('const SOCKET_TOP =');
  const end = source.indexOf('const NodeStateDot =', start);
  assert.ok(start > 0 && end > start);
  return source.slice(start, end) + require('./workshop72_node_helpers.cjs').nodePreviewSource(source);
};
const shortcutSlice = () => {
  const start = source.indexOf('const studioShortcut =');
  const end = source.indexOf('// An ordinary canvas edit', start);
  assert.ok(start > 0 && end > start);
  return source.slice(start, end);
};
const helpers = () => {
  const context = vm.createContext({});
  vm.runInContext(slice().replace(/const NodeCanvas = [^]*$/, '') +
    '\nglobalThis.h = {canvasWheelZoom: typeof canvasWheelZoom === "function" ? canvasWheelZoom : null,' +
    ' canvasDimmedIds: typeof canvasDimmedIds === "function" ? canvasDimmedIds : null};', context);
  return context.h;
};
const parseCanvasTransform = value => {
  const match = String(value || '').match(/translate3d\(([-0-9.]+)px,\s*([-0-9.]+)px,\s*0\)\s*scale\(([-0-9.]+)\)/);
  return match ? {x:+match[1], y:+match[2], zoom:+match[3]} : null;
};

const createdNodeIdHelper = () => {
  const start = source.indexOf('const studioCreatedNodeId =');
  const end = source.indexOf('let LM_SESSIONS =', start);
  assert.ok(start > 0 && end > start);
  const context = vm.createContext({window:{}});
  vm.runInContext(source.slice(start, end) +
    '\nglobalThis.studioCreatedNodeId = studioCreatedNodeId;', context);
  return context.studioCreatedNodeId;
};

const port = (id, side) => ({id, t:'any', label:id, connectable:true, mode:'connection', side});
const NODES = () => [
  {id:'a', cat:'logic', live:true, x:40, y:60, w:210, h:110, title:'Sketch Lines', sub:'vision.sketch_lines',
    engine:'vision.sketch_lines', params:[{k:'seed', v:'sketch-lines'}, {k:'threshold', v:'60'}],
    ins:[], outs:[port('a-out', 'source')], group:'', pinned:false, application:false},
  {id:'b', cat:'logic', live:true, x:400, y:60, w:210, h:110, title:'Line Watcher', sub:'lines.watch',
    engine:'lines.watch', params:[], ins:[port('b-in', 'target')], outs:[port('b-out', 'source')], group:'', pinned:false, application:false},
  {id:'c', cat:'logic', live:true, x:760, y:60, w:210, h:110, title:'Revit Walls', sub:'revit.build_walls',
    engine:'revit.build_walls', params:[], ins:[port('c-in', 'target')], outs:[], group:'', pinned:false, application:false},
  {id:'d', cat:'logic', live:true, x:40, y:400, w:210, h:110, title:'Loner', sub:'', params:[], ins:[], outs:[],
    group:'', pinned:false, application:false},
];
const WIRES = () => [
  {id:'w-ab', from:['a', 'a-out'], to:['b', 'b-in']},
  {id:'w-bc', from:['b', 'b-out'], to:['c', 'c-in']},
];

test('library create reveal uses the created node id from the projection, not the canvas root', () => {
  const createdNodeId = createdNodeIdHelper();
  const before = new Set(['old-node']);
  const refreshed = {
    root:'canvas-root',
    selected:'created-node',
    nodes:[{id:'old-node'}, {id:'created-node'}],
  };
  assert.equal(createdNodeId({
    ok:true,
    root:'canvas-root',
    node:'created-node',
    selected:'created-node',
  }, refreshed, before), 'created-node');
  assert.equal(createdNodeId({ok:true, root:'canvas-root'}, refreshed, before),
    'created-node');
});

async function mount({focusId = null, history = null, nodes = NODES(), wires = WIRES(), authority = false, lateMoveMember = false, selectionTransport = null, topologyTransport = null} = {}) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53915/'});
  for (const [name, value] of [['offsetWidth', 210], ['offsetHeight', 110]]) {
    Object.defineProperty(dom.window.HTMLElement.prototype, name, {configurable:true, get() { return value; }});
  }
  dom.window.HTMLElement.prototype.getBoundingClientRect = () => ({left:0, top:0, width:1200, height:800, right:1200, bottom:800});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const calls = [];
  let snapshot = {graph:{nodes, wires}, canvas:{revision:3,
    scope:{current:'scope', trail:[{root:'scope'}]}, authorization:{subject:'founder', session:'s'},
    ...(history ? {action_history:history.state} : {})}};
  if (history) {
    dom.window.ARCHHUB_HISTORY = async operation => { calls.push(['history', operation]); history.pending = operation; return {ok:true}; };
  }
  const topologyApi = {
    getSnapshot:() => ({topology:snapshot}),
    moveTopologyNodes:async (positions, expectedRevision, expectedPositions, placement) => {
      calls.push(['move', JSON.parse(JSON.stringify(positions))]);
      snapshot = {...snapshot, canvas:{...snapshot.canvas, revision:snapshot.canvas.revision + 1},
        graph:{...snapshot.graph, nodes:snapshot.graph.nodes.map(node => positions[node.id] ? {...node, ...positions[node.id]} : node)}};
      return {ok:true};
    },
    disconnectTopology:async rootId => { calls.push(['unwire', rootId]); return {ok:true}; },
    composeTopology:async (operation, roots) => { calls.push(['compose', operation, [...roots]]); return {ok:true}; },
    refreshTopologyCanvas:async () => {
      if (history?.pending) {
        const graph = history.after(history.pending, snapshot.graph);
        history.pending = null;
        snapshot = {...snapshot, graph, canvas:{...snapshot.canvas, revision:snapshot.canvas.revision + 1, action_history:history.state}};
      }
      return snapshot;
    },
  };
  if (authority) {
    const moveMember = async (member, fromGroup, toGroup, position) => {
      calls.push(['member', member, fromGroup, toGroup, JSON.parse(JSON.stringify(position))]);
      return snapshot;
    };
    dom.window.ARCHHUB_STUDIO_AUTHORITY = {
      getSnapshot:() => snapshot,
      moveMany:topologyApi.moveTopologyNodes,
      load:async () => snapshot,
      open:async root => { calls.push(['open', root]); return {ok:true}; },
      composition:async (operation, roots) => {
        calls.push(['gesture', [...roots]]);
        calls.push(['interaction', operation]);
        snapshot = {...snapshot, canvas:{...snapshot.canvas, revision:snapshot.canvas.revision + 1}, selected:'group-node'};
        return snapshot;
      },
    };
    if (!lateMoveMember) dom.window.ARCHHUB_STUDIO_AUTHORITY.moveMember = moveMember;
    else dom.window.__attachMoveMember = () => { dom.window.ARCHHUB_STUDIO_AUTHORITY.moveMember = moveMember; };
  } else {
    dom.window.ARCHHUB_EXISTING_WORKSHOP = topologyApi;
  }
  let selectionApi = null;
  if (selectionTransport || topologyTransport) {
    const adapterContext = vm.createContext({URLSearchParams});
    vm.runInContext(fs.readFileSync(path.join(root, 'nodelang/studio/studio-authority.js'), 'utf8'), adapterContext);
    vm.runInContext(fs.readFileSync(path.join(root, 'nodelang/studio/studio-existing-workshop.js'), 'utf8'), adapterContext);
    let durable = {ok:true, application_root:'app', revision:3,
      authorization:{subject:'founder', session:'s'}, scope:{current:'scope', trail:[{root:'scope'}]},
      nodes, wires, interaction_projection:{revision:3, bindings:[]}};
    const controls = () => {
      durable.configuration = {design_system:{control_catalog:{controls:[{owner:'group-control', applicable:true,
        activation:{arguments:{operation:'group'}}}]}}};
      durable.interaction_projection = {revision:durable.revision, bindings:[
        {control:'group-control', interaction:'group-action', event:'activate', acknowledgement_mode:'receipt-v1'},
        {control:'app:control:canvas:remove-member', interaction:'remove-action', event:'activate', acknowledgement_mode:'receipt-v1'},
      ]};
    };
    if (topologyTransport) controls();
    selectionApi = adapterContext.ArchHubExistingWorkshop.create({
      uuid:() => 'member-command',
      get:async () => structuredClone(durable),
      post:async (url, body) => {
        calls.push(['post', url, JSON.parse(JSON.stringify(body))]);
        if (selectionTransport?.beforeReply) await selectionTransport.beforeReply(calls.filter(call => call[0] === 'post').length);
        if (topologyTransport?.beforeReply) await topologyTransport.beforeReply(url, body);
        if (topologyTransport?.refuse) {
          const error = topologyTransport.refuse(url, body);
          if (error) return {ok:false, error};
        }
        if (topologyTransport && url === '/api/universal/interaction') {
          const base = durable.revision;
          if (body.membership) {
            const {member, from_group, to_group} = body.membership;
            assert.equal(to_group, '');
            const group = {...durable.nodes.find(node => node.id === from_group)};
            group.members = group.members.filter(row => (typeof row === 'string' ? row : row.id) !== member);
            group.member_count = group.members.length;
            const released = {...NODES().find(node => node.id === member), group:'', ...body.membership.position};
            durable.nodes = durable.nodes.map(node => node.id === from_group ? {...group} : node);
            if (!durable.nodes.some(node => node.id === member)) durable.nodes.push(released);
          } else if (!topologyTransport.missingGroup) {
            const members = durable.selection.map(id => ({id, title:durable.nodes.find(node => node.id === id).title}));
            const group = {id:'group-node', cat:'logic', live:true, composition:true, title:'Group',
              sub:'', x:40, y:60, w:300, h:160, params:[], ins:[], outs:[], group:'', members, member_count:members.length};
            durable.nodes = [...durable.nodes.filter(node => !durable.selection.includes(node.id)), group];
            durable.selection = ['group-node']; durable.selected = 'group-node';
          }
          durable.revision += 1; controls();
          if (!body.membership) return {...structuredClone(durable), ok:true, created_root:'group-node'};
          return {ok:true, projection_mode:'receipt-v1', base_revision:base, committed_revision:durable.revision,
            created_root:body.membership ? undefined : 'group-node'};
        }
        durable = {...durable, selected:body.focus, revision:durable.revision + 1,
          interaction_projection:{revision:durable.revision + 1, bindings:[]},
          nodes:durable.nodes.map(node => ({...node, selected:body.roots.includes(node.id)})),
          selection:[...body.roots]};
        if (topologyTransport) controls();
        return structuredClone(durable);
      }, projectCanvas:value => ({nodes:value.nodes, wires:value.wires}),
    });
    selectionApi.setTopologyCanvas(structuredClone(durable));
    dom.window.ARCHHUB_EXISTING_WORKSHOP = selectionApi;
  }
  dom.window.ARCHHUB_RETRACT = async rootId => { calls.push(['retract', rootId]); return {ok:true}; };
  dom.window.ARCHHUB_RUN = async () => { calls.push(['run']); return {ok:true, display:{}, pending:{}}; };
  dom.window.ARCHHUB_NODE_CREATE = async spec => { calls.push(['create', JSON.parse(JSON.stringify(spec))]); return {ok:true, id:'created-node'}; };
  const context = vm.createContext({React, LM, window:dom.window, document:dom.window.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope',
    studioCategory:cat => ({col:'token-cat', icon:'+', label:String(cat).toUpperCase()}), WIRE:{},
    NodeBody:() => null,
    // The toolbar's Undo / Redo buttons as the real CanvasToolbar draws them from these props.
    CanvasToolbar:({undo, redo}) => React.createElement('div', null, [['Undo', undo], ['Redo', redo]].map(([label, held]) =>
      React.createElement('button', {key:label, 'aria-label':label, disabled:held.disabled, title:held.disabled ? held.why : label,
        onClick:() => held.run()}, label))), FloatingComposer:() => null, CanvasAddBox:() => null, MiniMap:() => null, Socket:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({}),
    setTimeout:dom.window.setTimeout.bind(dom.window), clearTimeout:dom.window.clearTimeout.bind(dom.window)});
  if (selectionApi) {
    const start = source.indexOf('const useStudioProjection =');
    const end = source.indexOf('// ─', start);
    vm.runInContext(source.slice(start, end), context);
  }
  const freeSlot = source.slice(source.indexOf('const studioFreeSlot ='), source.indexOf('const studioRefreshCanvasInPlace ='));
  vm.runInContext(transformSync(shortcutSlice() + freeSlot + slice() + '\nglobalThis.NodeCanvas = NodeCanvas;',
    {loader:'jsx', format:'cjs'}).code, context);
  const reactRoot = createRoot(dom.window.document.getElementById('root'));
  const props = {focusId, setFocusId:selectionApi ? (id, roots) => {
    calls.push(['focus', id, [...roots]]);
    selectionApi.selectTopology(id, roots).catch(() => {});
  } : () => {}, setLibraryOpen:() => {}, userNodes:[], addNodeFromLibrary:() => {}, model:null};
  const act = fn => React.act(async () => { await fn(); });
  const draw = () => act(() => reactRoot.render(React.createElement(context.NodeCanvas, props)));
  await draw();
  const doc = dom.window.document;
  const region = () => doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
  const card = id => doc.querySelector('.lm-node[data-node-id="' + id + '"]');
  const mouse = (target, type, init = {}) => target.dispatchEvent(new dom.window.MouseEvent(type, {bubbles:true, cancelable:true, ...init}));
  const key = (target, init) => { const e = new dom.window.KeyboardEvent('keydown', {bubbles:true, cancelable:true, ...init}); target.dispatchEvent(e); return e; };
  const menu = () => doc.querySelector('[role="menu"]');
  const rows = () => [...(menu()?.querySelectorAll('button[role^="menuitem"]') || [])];
  const row = label => rows().find(button => button.getAttribute('aria-label') === label.replace(/…$/, ''));
  const transform = () => region().children[0].style.transform;
  return {
    doc, calls, draw, act, region, card, menu, rows, row, transform, win:dom.window, selectionApi,
    rightClick:async el => act(() => { mouse(el, 'contextmenu', {clientX:100, clientY:100}); }),
    click:async el => act(() => { el.dispatchEvent(new dom.window.MouseEvent('click', {bubbles:true})); }),
    mouse:async (el, type, init) => act(() => { mouse(el, type, init); }),
    key:async (el, init) => { let e; await act(() => { e = key(el, init); }); return e; },
    wheel:async deltaY => act(() => { region().dispatchEvent(new dom.window.WheelEvent('wheel', {deltaY, clientX:300, clientY:300, bubbles:true, cancelable:true})); }),
    wheelAt:async (deltaY, clientX, clientY) => act(() => { region().dispatchEvent(new dom.window.WheelEvent('wheel', {deltaY, clientX, clientY, bubbles:true, cancelable:true})); }),
    settle:async ms => act(() => new Promise(done => dom.window.setTimeout(done, ms))),
    toast:() => [...dom.window.document.querySelectorAll('[role="status"],[role="alert"]')].map(n => n.textContent).join(' | '),
    groupButton:() => doc.querySelector('[data-selection-bar] button'),
    remount:async () => { await act(() => reactRoot.render(null)); await draw(); },
    close:async () => {
      await act(() => reactRoot.unmount());
      dom.window.close(); global.window = oldWindow; global.document = oldDocument;
      delete global.IS_REACT_ACT_ENVIRONMENT;
    },
  };
}

test('M1: the node menu holds the design node actions in order; unbuilt ones are dashed and say why', async () => {
  const view = await mount();
  try {
    await view.rightClick(view.card('b'));
    const labels = view.rows().map(button => button.getAttribute('aria-label'));
    const design = ['Run graph', 'Add watcher', 'Open pipeline', 'Freeze node', 'Duplicate', 'Disconnect all wires', 'Delete node'];
    assert.deepEqual(labels.slice(0, design.length), design, 'design node actions first: ' + JSON.stringify(labels));
    for (const label of ['Add watcher', 'Freeze node']) {
      const button = view.row(label);
      assert.equal(button.disabled, true, label + ' has no route in this build');
      assert.match(button.title, /not available in this build/, label + ' says why in plain words');
    }
    assert.match(view.row('Open pipeline').title, /nothing inside/, 'a plain card has nothing to open, and says so');
    for (const label of ['Run graph', 'Duplicate', 'Disconnect all wires', 'Delete node…']) {
      assert.equal(view.row(label).disabled, false, label + ' runs an existing route');
    }
    await view.click(view.row('Run graph'));
    await view.settle(5);
    assert.deepEqual(view.calls.filter(call => call[0] === 'run'), [['run']], 'Run goes through ARCHHUB_RUN (/api/universal/run-graph)');
  } finally { await view.close(); }
});

test('M2: Delete asks first; Cancel sends nothing; Delete retracts the node', async () => {
  const view = await mount();
  try {
    await view.rightClick(view.card('b'));
    await view.click(view.row('Delete node…'));
    const ask = view.doc.querySelector('[role="alertdialog"]');
    assert.ok(ask, 'a confirmation is drawn before anything is removed');
    assert.match(ask.textContent, /Line Watcher/);
    assert.match(ask.textContent, /2 wires/);
    assert.equal(view.calls.length, 0, 'nothing sent while asking');
    await view.click([...ask.querySelectorAll('button')].find(button => button.textContent === 'Cancel'));
    assert.equal(view.doc.querySelector('[role="alertdialog"]'), null);
    assert.equal(view.calls.length, 0, 'Cancel sends nothing');
    await view.rightClick(view.card('b'));
    await view.click(view.row('Delete node…'));
    await view.click([...view.doc.querySelectorAll('[role="alertdialog"] button')].find(button => button.textContent === 'Delete'));
    await view.settle(5);
    assert.deepEqual(view.calls, [['retract', 'b']], 'the existing retract route removes it');
  } finally { await view.close(); }
});

test('M3: Disconnect all and a wire right-click cut through the existing unwire route', async () => {
  const view = await mount();
  try {
    await view.rightClick(view.card('b'));
    await view.click(view.row('Disconnect all wires'));
    await view.settle(5);
    assert.deepEqual(view.calls, [['unwire', 'w-ab'], ['unwire', 'w-bc']]);
    view.calls.length = 0;
    await view.rightClick(view.card('d'));
    assert.equal(view.row('Disconnect all wires').disabled, true);
    assert.match(view.row('Disconnect all wires').title, /no wires/);
    await view.act(() => { view.win.document.body.click(); });
    const wire = view.doc.querySelector('path[data-wire-id="w-bc"]');
    assert.ok(wire, 'each wire has a pick path that names its root');
    await view.rightClick(wire);
    assert.equal(view.menu()?.getAttribute('aria-label'), 'Wire actions');
    assert.deepEqual(view.rows().map(button => button.getAttribute('aria-label')), ['Cut this wire']);
    await view.click(view.row('Cut this wire'));
    await view.settle(5);
    assert.deepEqual(view.calls, [['unwire', 'w-bc']]);
  } finally { await view.close(); }
});

test('M3b: a picked wire is cut with Delete or Backspace through the same unwire route', async () => {
  for (const key of ['Delete', 'Backspace']) {
    const view = await mount({focusId:'w-bc'});
    try {
      const wire = view.doc.querySelector('path[data-wire-id="w-bc"]');
      await view.click(wire);
      const pressed = await view.key(view.region(), {key});
      assert.equal(pressed.defaultPrevented, true, key + ' is taken by the canvas');
      await view.settle(5);
      assert.deepEqual(view.calls.filter(call => call[0] === 'unwire'), [['unwire', 'w-bc']], key + ' cuts the picked wire');
    } finally { await view.close(); }
  }
  const idle = await mount();
  try {
    await idle.key(idle.region(), {key:'Delete'});
    await idle.settle(5);
    assert.deepEqual(idle.calls.filter(call => call[0] === 'unwire'), [], 'with no wire picked, Delete cuts nothing');
  } finally { await idle.close(); }
});

test('M3d: Delete right after the click cuts the clicked wire, before the graph confirms the selection', async () => {
  // Founder smoke 2026-10-01: the click sends the selection gesture; the canvas's selection follows only
  // when the graph answers. A Delete pressed in between was dropped without a word.
  const view = await mount();
  try {
    const wire = view.doc.querySelector('path[data-wire-id="w-bc"]');
    await view.click(wire);
    const pressed = await view.key(view.region(), {key:'Delete'});
    assert.equal(pressed.defaultPrevented, true, 'Delete is taken by the canvas');
    await view.settle(5);
    assert.deepEqual(view.calls.filter(call => call[0] === 'unwire'), [['unwire', 'w-bc']], 'the clicked wire is cut');
  } finally { await view.close(); }
});

test('M3c: with two or more cards selected the node menu leads with the design Group selection, which runs the graph Group', async () => {
  const view = await mount();
  try {
    await view.rightClick(view.card('b'));
    assert.equal(view.row('Group selection → grand node'), undefined, 'one selected card offers no grouping');
    await view.act(() => { view.win.document.body.click(); });
    await view.click(view.card('a'));
    await view.mouse(view.card('b'), 'click', {shiftKey:true});
    await view.rightClick(view.card('b'));
    assert.equal(view.rows()[0].getAttribute('aria-label'), 'Group selection → grand node', 'the design puts grouping first');
    await view.click(view.row('Group selection → grand node'));
    await view.settle(5);
    assert.deepEqual(view.calls.filter(call => call[0] === 'compose'), [['compose', 'group', ['a', 'b']]]);
    assert.match(view.toast(), /Grouped 2 nodes into one node/);
  } finally { await view.close(); }
});

test('M3e: the visible Group button sends the current two-card selection after a re-render', async () => {
  const view = await mount({authority:true});
  try {
    await view.click(view.card('a'));
    await view.mouse(view.card('b'), 'click', {shiftKey:true});
    await view.draw();
    assert.equal(view.groupButton().textContent.includes('Group 2 nodes'), true);
    await view.click(view.groupButton());
    assert.deepEqual(view.calls.filter(call => call[0] === 'gesture'), [['gesture', ['a', 'b']]]);
  } finally { await view.close(); }
});

test('GROUP3 Ctrl+G uses the visible Group owner and leaves editing fields alone', async () => {
  const view = await mount({nodes:NODES().slice(0,2), wires:[], topologyTransport:{}});
  try {
    await view.click(view.card('a')); await view.mouse(view.card('b'), 'click', {shiftKey:true});
    const field=view.doc.createElement('input'); view.region().appendChild(field);
    const editing=await view.key(field,{key:'g',ctrlKey:true});
    assert.equal(editing.defaultPrevented,false);
    assert.equal(view.calls.filter(call=>call[0]==='post'&&call[1].endsWith('/interaction')).length,0);
    const pressed=await view.key(view.region(),{key:'g',ctrlKey:true}); await view.settle(120);
    assert.equal(pressed.defaultPrevented,true);
    assert.equal(view.calls.filter(call=>call[0]==='post'&&call[1].endsWith('/interaction')).length,1);
    assert.equal(view.card('group-node').querySelectorAll('[data-member-chip]').length,2);
  } finally {await view.close();}
});

test('UPD2 p9: click A then Shift B keeps two drawn selections and Group with the real gesture selection response', async () => {
    const view = await mount({selectionTransport:{}});
    try {
      await view.mouse(view.card('a'), 'mousedown', {clientX:60, clientY:70});
      await view.mouse(view.card('a'), 'mouseup', {clientX:60, clientY:70});
      await view.click(view.card('a'));
      await view.settle(5);
      assert.equal(view.card('a').getAttribute('data-selected'), 'true');
      await view.mouse(view.card('b'), 'mousedown', {shiftKey:true, clientX:420, clientY:70});
      await view.mouse(view.card('b'), 'mouseup', {shiftKey:true, clientX:420, clientY:70});
      await view.mouse(view.card('b'), 'click', {shiftKey:true});
      await view.settle(5);
      assert.deepEqual(view.calls.filter(call => call[0] === 'focus'),
        [['focus', 'a', ['a']], ['focus', 'b', ['a', 'b']]]);
      assert.deepEqual(view.calls.filter(call => call[0] === 'post').map(call => call[2].roots), [['a'], ['a','b']]);
      assert.deepEqual(['a','b'].map(id => view.card(id).getAttribute('data-selected')), ['true','true']);
      assert.match(view.groupButton()?.textContent || '', /Group 2 nodes/);
      assert.equal(view.groupButton().disabled, false);
      assert.equal(view.selectionApi.getSnapshot().topology.requires_refresh, false);
    } finally { await view.close(); }
});

test('UPD2 p9: Shift B while click A is pending sends and renders the two-root gesture', async () => {
  let releaseFirst;
  const firstReply = new Promise(resolve => { releaseFirst = resolve; });
  const view = await mount({selectionTransport:{beforeReply:count => count === 1 ? firstReply : undefined}});
  try {
    await view.click(view.card('a'));
    await view.settle(0);
    await view.mouse(view.card('b'), 'click', {shiftKey:true});
    await view.act(() => { releaseFirst(); });
    await view.settle(5);
    assert.deepEqual(view.calls.filter(call => call[0] === 'focus'),
      [['focus', 'a', ['a']], ['focus', 'b', ['a', 'b']]]);
    assert.deepEqual(view.calls.filter(call => call[0] === 'post').map(call => call[2].roots), [['a'], ['a','b']]);
    assert.deepEqual(['a','b'].map(id => view.card(id).getAttribute('data-selected')), ['true','true']);
    assert.match(view.groupButton()?.textContent || '', /Group 2 nodes/);
    assert.equal(view.groupButton().disabled, false);
    assert.equal(view.selectionApi.getSnapshot().topology.requires_refresh, false);
  } finally { releaseFirst(); await view.close(); }
});

test('UPD2 p9: click A and Shift B in one React batch preserve the immediate selection intent', async () => {
  const view = await mount({selectionTransport:{}});
  try {
    await view.act(() => {
      view.card('a').dispatchEvent(new view.win.MouseEvent('click', {bubbles:true}));
      view.card('b').dispatchEvent(new view.win.MouseEvent('click', {bubbles:true, shiftKey:true}));
    });
    await view.settle(5);
    assert.deepEqual(view.calls.filter(call => call[0] === 'focus'),
      [['focus', 'a', ['a']], ['focus', 'b', ['a','b']]]);
    assert.deepEqual(view.calls.filter(call => call[0] === 'post').map(call => call[2].roots), [['a'], ['a','b']]);
    assert.deepEqual(['a','b'].map(id => view.card(id).getAttribute('data-selected')), ['true','true']);
    assert.match(view.groupButton()?.textContent || '', /Group 2 nodes/);
    assert.equal(view.groupButton().disabled, false);
  } finally { await view.close(); }
});

test('M3f: member drag-out posts the inverse-transformed canvas point under pan and 150% zoom', async () => {
  const nodes = [
    {id:'group-node', cat:'logic', live:true, x:200, y:200, w:300, h:160, title:'Group', sub:'',
      params:[], ins:[], outs:[], group:'', pinned:false, application:false, composition:true,
      memberCount:2, members:[{id:'a', title:'Sketch Lines'}, {id:'b', title:'Line Watcher'}]},
    {id:'a', cat:'logic', live:true, x:220, y:220, w:210, h:110, title:'Sketch Lines', sub:'',
      params:[], ins:[], outs:[], group:'group-node', pinned:false, application:false},
    {id:'b', cat:'logic', live:true, x:440, y:220, w:210, h:110, title:'Line Watcher', sub:'',
      params:[], ins:[], outs:[], group:'group-node', pinned:false, application:false},
  ];
  const view = await mount({authority:true, nodes, wires:[]});
  try {
    await view.wheelAt(-Math.log(1.5 / 0.66) / 0.001, 0, 0);
    await view.mouse(view.card('group-node'), 'mousedown', {button:1, clientX:0, clientY:0});
    await view.mouse(view.doc, 'mousemove', {clientX:120, clientY:80});
    await view.mouse(view.doc, 'mouseup', {});
    const transform = parseCanvasTransform(view.transform());
    assert.equal(transform.zoom, 1.5);
    view.card('group-node').getBoundingClientRect = () => ({left:420, top:380, right:720, bottom:600, width:300, height:220});
    const chip = view.doc.querySelector('[data-member-chip="a"]');
    await view.mouse(chip, 'mousedown', {button:0, clientX:450, clientY:410});
    await view.mouse(view.doc, 'mousemove', {clientX:795, clientY:635});
    await view.mouse(view.doc, 'mouseup', {clientX:795, clientY:635});
    const posted = view.calls.filter(call => call[0] === 'member');
    assert.equal(posted.length, 1);
    assert.equal(posted[0][1], 'a');
    assert.equal(posted[0][2], 'group-node');
    assert.equal(posted[0][3], '');
    assert.equal(Math.round(posted[0][4].x * 1000) / 1000, Math.round(((795 - transform.x) / transform.zoom) * 1000) / 1000);
    assert.equal(Math.round(posted[0][4].y * 1000) / 1000, Math.round(((635 - transform.y) / transform.zoom) * 1000) / 1000);
  } finally { await view.close(); }
});

test('M3g: member drag-out works with window pointer events and a late moveMember authority', async () => {
  const nodes = [
    {id:'group-node', cat:'logic', live:true, x:200, y:200, w:300, h:160, title:'Group', sub:'',
      params:[], ins:[], outs:[], group:'', pinned:false, application:false, composition:true,
      memberCount:2, members:[{id:'a', title:'Sketch Lines'}, {id:'b', title:'Line Watcher'}]},
    {id:'a', cat:'logic', live:true, x:220, y:220, w:210, h:110, title:'Sketch Lines', sub:'',
      params:[], ins:[], outs:[], group:'group-node', pinned:false, application:false},
    {id:'b', cat:'logic', live:true, x:440, y:220, w:210, h:110, title:'Line Watcher', sub:'',
      params:[], ins:[], outs:[], group:'group-node', pinned:false, application:false},
  ];
  const view = await mount({authority:true, lateMoveMember:true, nodes, wires:[]});
  try {
    view.win.__attachMoveMember();
    view.card('group-node').getBoundingClientRect = () => ({left:420, top:380, right:720, bottom:600, width:300, height:220});
    const chip = view.doc.querySelector('[data-member-chip="a"]');
    await view.mouse(chip, 'pointerdown', {button:0, clientX:450, clientY:410});
    assert.equal(chip.getAttribute('data-member-drag'), 'armed');
    await view.mouse(view.win, 'pointermove', {clientX:795, clientY:635});
    assert.equal(chip.getAttribute('data-member-drag'), 'left');
    await view.mouse(view.region(), 'pointerup', {clientX:795, clientY:635});
    assert.equal(chip.getAttribute('data-member-drag'), 'posted');
    const posted = view.calls.filter(call => call[0] === 'member');
    assert.equal(posted.length, 1);
    assert.equal(posted[0][1], 'a');
    assert.equal(posted[0][2], 'group-node');
    assert.equal(posted[0][3], '');
  } finally { await view.close(); }
});

test('M4: Duplicate places the same engine card with its rows beside it', async () => {
  const view = await mount();
  try {
    await view.rightClick(view.card('a'));
    await view.click(view.row('Duplicate'));
    await view.settle(5);
    const {x, y} = view.calls[0][1];
    assert.deepEqual(view.calls, [['create', {title:'Sketch Lines copy', engine:'vision.sketch_lines', x, y,
      params:{threshold:'60'}}]], 'node-create with the engine and the rows, never the seed marker');
    assert.ok(Number.isFinite(x) && Number.isFinite(y), 'copy has confirmed canvas coordinates');
    for (const node of NODES()) assert.equal(x < node.x + 210 && node.x < x + 210 && y < node.y + 110 && node.y < y + 110,
      false, 'copy clears ' + node.id);
    view.calls.length = 0;
    await view.rightClick(view.card('d'));
    assert.equal(view.row('Duplicate').disabled, true, 'a card with no engine cannot be copied');
    assert.match(view.row('Duplicate').title, /no engine/);
  } finally { await view.close(); }
});

test('M4b: Duplicate refuses an unconfirmed create without retrying', async () => {
  const view = await mount();
  try {
    view.win.ARCHHUB_NODE_CREATE = async spec => { view.calls.push(['create-null', JSON.parse(JSON.stringify(spec))]); return null; };
    await view.rightClick(view.card('a'));
    await view.click(view.row('Duplicate'));
    await view.settle(5);
    assert.equal(view.calls.filter(call => call[0] === 'create-null').length, 1);
    assert.match(view.toast(), /Fork not confirmed/);
  } finally { await view.close(); }
});

test('M5: Clear all is live, asks first, and retracts every card', async () => {
  const view = await mount();
  try {
    await view.rightClick(view.region());
    const clear = view.row('Clear all nodes');
    assert.ok(clear, 'the canvas menu still has Clear all');
    assert.equal(clear.disabled, false);
    await view.click(clear);
    assert.match(view.doc.querySelector('[role="alertdialog"]').textContent, /4 nodes/);
    assert.equal(view.calls.length, 0);
    await view.click([...view.doc.querySelectorAll('[role="alertdialog"] button')].find(button => button.textContent === 'Delete'));
    await view.settle(5);
    assert.deepEqual(view.calls.map(call => call.join(':')), ['retract:a', 'retract:b', 'retract:c', 'retract:d']);
    await view.rightClick(view.region());
    assert.match(view.row('Paste').title, /not available in this build/, 'Paste has no route and says so');
  } finally { await view.close(); }
});

test('V1: leaving the canvas and coming back keeps its pan and zoom', async () => {
  const view = await mount();
  try {
    await view.wheel(-400);
    const zoomed = view.transform();
    assert.notEqual(zoomed, 'scale(0.66)', 'the wheel zoomed');
    await view.remount();
    assert.equal(view.transform(), zoomed, 'the remounted canvas keeps the zoom it was left at');
  } finally { await view.close(); }
});

test('V2: wheel zoom stops at 30% and one notch is a gentle step', () => {
  const {canvasWheelZoom} = helpers();
  assert.equal(typeof canvasWheelZoom, 'function');
  let zoom = 1;
  for (let i = 0; i < 200; i += 1) zoom = canvasWheelZoom(zoom, 100);
  assert.equal(zoom, 0.3, 'the floor is 30%');
  const step = canvasWheelZoom(1, 100);
  assert.ok(step >= 0.88 && step < 1, 'one notch changes zoom by about a tenth: ' + step);
  assert.ok(canvasWheelZoom(2, -100) <= 2);
});

test('V3: nothing focused dims nothing; a focus lights its neighbours and dims the rest', async () => {
  const {canvasDimmedIds} = helpers();
  assert.equal(typeof canvasDimmedIds, 'function');
  const ids = ['a', 'b', 'c', 'd'];
  assert.deepEqual([...canvasDimmedIds(ids, WIRES(), null, [])], []);
  assert.deepEqual([...canvasDimmedIds(ids, WIRES(), 'not-on-canvas', [])], []);
  assert.deepEqual([...canvasDimmedIds(ids, WIRES(), 'a', [])].sort(), ['c', 'd']);
  assert.deepEqual([...canvasDimmedIds(ids, WIRES(), 'w-bc', [])].sort(), ['a', 'd'], 'a focused wire lights its two ends');
  // A selection the owner restored at start (focusId) is not a pick: nothing dims until the person clicks.
  const view = await mount({focusId:'w-ab'});
  try {
    const opacities = () => ['a', 'b', 'c', 'd'].map(id => view.card(id).style.opacity);
    assert.deepEqual(opacities(), ['1', '1', '1', '1'], 'an unpicked canvas is drawn at full strength');
    await view.click(view.card('a'));
    assert.deepEqual(opacities(), ['1', '1', '0.42', '0.42'], 'a pick lights its neighbours and dims the rest at once');
    await view.mouse(view.region(), 'mousedown', {button:0, clientX:5, clientY:5});
    await view.mouse(view.doc, 'mouseup', {});
    assert.deepEqual(opacities(), ['1', '1', '1', '1'], 'a click on empty canvas clears the dim');
  } finally { await view.close(); }
});

test('K1: F fits, arrows nudge the selection through the layout save, middle-drag pans', async () => {
  const view = await mount();
  try {
    const before = view.transform();
    const selected = await view.key(view.region(), {key:'a', ctrlKey:true});
    assert.equal(selected.defaultPrevented, true, 'Ctrl+A is taken by the canvas');
    assert.deepEqual(['a', 'b', 'c', 'd'].map(id => view.card(id).getAttribute('data-selected')), ['true', 'true', 'true', 'true']);
    const fittedAll = await view.key(view.region(), {key:'0', ctrlKey:true});
    assert.equal(fittedAll.defaultPrevented, true, 'Ctrl+0 is taken by the canvas');
    assert.notEqual(view.transform(), before, 'Ctrl+0 fits the graph');
    const allFit = view.transform();
    await view.mouse(view.region(), 'mousedown', {button:0, clientX:5, clientY:5});
    await view.mouse(view.doc, 'mouseup', {});
    await view.click(view.card('b'));
    const fittedSelection = await view.key(view.region(), {key:'f'});
    assert.equal(fittedSelection.defaultPrevented, true, 'F is taken by the canvas');
    assert.notEqual(view.transform(), allFit, 'F fits the selection');
    const nudged = await view.key(view.card('b'), {key:'ArrowRight'});
    assert.equal(nudged.defaultPrevented, true);
    assert.equal(view.card('b').style.left, '420px', 'one grid step right');
    await view.settle(700);
    assert.deepEqual(view.calls.filter(call => call[0] === 'move'), [['move', {b:{x:420, y:60}}]], 'saved like a drag');
    const layer = view.transform();
    await view.mouse(view.card('a'), 'mousedown', {button:1, clientX:10, clientY:10});
    await view.mouse(view.doc, 'mousemove', {clientX:60, clientY:40});
    await view.mouse(view.doc, 'mouseup', {});
    assert.notEqual(view.transform(), layer, 'middle-drag over a card pans the canvas');
  } finally { await view.close(); }
});

test('U1: Ctrl+Z, Ctrl+Shift+Z / Ctrl+Y, the menu and the toolbar run the graph Undo / Redo and say what changed', async () => {
  // The graph as the history route leaves it: undo brings "Revit Walls" back, redo takes it away again.
  const walls = NODES().find(node => node.id === 'c');
  const history = {state:{can_undo:true, can_redo:false}, pending:null,
    after:(operation, graph) => operation === 'undo'
      ? (history.state = {can_undo:true, can_redo:true}, {...graph, nodes:[...graph.nodes.filter(n => n.id !== 'c'), walls]})
      : (history.state = {can_undo:true, can_redo:false}, {...graph, nodes:graph.nodes.filter(n => n.id !== 'c')})};
  const view = await mount({history, nodes:NODES().filter(node => node.id !== 'c'), wires:WIRES().slice(0, 1)});
  try {
    await view.key(view.region(), {key:'z', ctrlKey:true});
    await view.settle(10);
    assert.deepEqual(view.calls, [['history', 'undo']], 'Ctrl+Z asks the history route');
    assert.match(view.toast(), /Undid: deleted \u2018Revit Walls\u2019/);
    await view.draw();
    await view.key(view.region(), {key:'Z', ctrlKey:true, shiftKey:true});
    await view.settle(10);
    assert.deepEqual(view.calls.at(-1), ['history', 'redo'], 'Ctrl+Shift+Z redoes');
    assert.match(view.toast(), /Redid: deleted \u2018Revit Walls\u2019/);
    await view.draw();
    const undoButton = view.doc.querySelector('button[aria-label="Undo"]');
    assert.ok(undoButton, 'the toolbar has Undo');
    await view.click(undoButton);
    await view.settle(10);
    assert.deepEqual(view.calls.at(-1), ['history', 'undo'], 'the toolbar Undo runs the same route');
    await view.draw();
    await view.key(view.region(), {key:'y', ctrlKey:true});
    await view.settle(10);
    assert.deepEqual(view.calls.at(-1), ['history', 'redo'], 'Ctrl+Y redoes');
    await view.draw();
    await view.rightClick(view.region());
    assert.equal(view.row('Undo').disabled, false);
    assert.equal(view.row('Reset positions'), undefined, 'the positions-only reset is replaced');
  } finally { await view.close(); }
});

test('U2: nothing to undo or redo: the items are disabled and say so in plain words', async () => {
  const history = {state:{can_undo:false, can_redo:false}, pending:null, after:(op, graph) => graph};
  const view = await mount({history});
  try {
    await view.rightClick(view.region());
    for (const [label, why] of [['Undo', 'Nothing to undo'], ['Redo', 'Nothing to redo']]) {
      assert.equal(view.row(label).disabled, true, label + ' is disabled');
      assert.equal(view.row(label).title, why);
      const tool = view.doc.querySelector('button[aria-label="' + label + '"]');
      assert.equal(tool.disabled, true); assert.equal(tool.title, why);
    }
    await view.act(() => { view.win.document.body.click(); });
    await view.key(view.region(), {key:'z', ctrlKey:true});
    assert.deepEqual(view.calls, [], 'Ctrl+Z sends nothing when there is nothing to undo');
  } finally { await view.close(); }
});

test('R1: pan and zoom are one layer transform, the grid is fixed, and a drag re-renders the moving card only', async () => {
  const view = await mount();
  try {
    const layer = view.region().children[0];
    assert.match(layer.style.transform, /^translate3d\(/, 'one translate3d + scale transform');
    assert.equal(layer.style.left, '0px'); assert.equal(layer.style.top, '0px');
    assert.equal(view.region().style.backgroundPosition, '', 'the dot grid does not shift on pan');
    const handle = view.card('b').children[0];
    await view.mouse(handle, 'mousedown', {button:0, clientX:0, clientY:0});
    // Picking b up selects it (its focus and the others' dim change once); the moves are what is counted.
    view.win.__archhubCardRenders = {};
    for (let i = 1; i <= 40; i += 1) await view.mouse(view.doc, 'mousemove', {clientX:i * 5, clientY:i * 2});
    await view.mouse(view.doc, 'mouseup', {});
    const renders = view.win.__archhubCardRenders;
    for (const still of ['a', 'c', 'd']) assert.equal(renders[still] || 0, 0, still + ' did not move and did not re-render: ' + JSON.stringify(renders));
    assert.ok(renders.b > 0 && renders.b <= 45, 'the moving card re-renders once per move at most: ' + renders.b);
    assert.equal(view.doc.querySelector('#lm-wire-glow'), null, 'no wire glow filter');
  } finally { await view.close(); }
});

const P10_GROUP_NODES = () => [{id:'group-node', cat:'logic', live:true, composition:true, title:'Group',
  sub:'', x:40, y:60, w:300, h:160, params:[], ins:[], outs:[], group:'',
  members:[{id:'a', title:'Sketch Lines'}, {id:'b', title:'Line Watcher'}], member_count:2}];
async function p10Drop(view, member = 'a') {
  view.card('group-node').getBoundingClientRect = () => ({left:40, top:60, right:340, bottom:220, width:300, height:160});
  const chip = view.doc.querySelector('[data-member-chip="' + member + '"]');
  assert.equal(!!chip, true);
  await view.mouse(chip, 'pointerdown', {clientX:100, clientY:100});
  await view.mouse(view.win, 'pointermove', {clientX:800, clientY:400});
  await view.mouse(view.win, 'pointerup', {clientX:800, clientY:400});
  await view.settle(5);
  return chip;
}

test('UPD2 p10 GR: ordinary installed topology drag-off sends exactly one membership POST and re-renders 2 to 1', async () => {
  const view = await mount({nodes:P10_GROUP_NODES(), wires:[], topologyTransport:{}});
  try {
    const revision = view.selectionApi.getSnapshot().topology.canvas.revision;
    const chip = await p10Drop(view);
    const posts = view.calls.filter(call => call[0] === 'post');
    assert.equal(posts.length, 1);
    assert.equal(posts[0][1], '/api/universal/interaction');
    assert.equal(posts[0][2].membership.member, 'a');
    assert.equal(posts[0][2].membership.from_group, 'group-node');
    assert.equal(posts[0][2].membership.to_group, '');
    assert.equal(view.selectionApi.getSnapshot().topology.canvas.revision, revision + 1);
    assert.equal(view.card('group-node').querySelectorAll('[data-member-chip]').length, 1);
    assert.equal(view.card('group-node').querySelector('[data-member-chip="b"]') !== null, true);
    assert.equal(view.card('a') !== null, true);
    assert.equal(chip.getAttribute('data-member-drag'), 'posted');
  } finally { await view.close(); }
});

test('UPD2 p10 Group: two selected cards create a real card in five mounts, including a held selection reply', async () => {
  for (let round = 0; round < 5; round += 1) {
    let release;
    const held = new Promise(resolve => { release = resolve; });
    let gesture = 0;
    const view = await mount({nodes:NODES().slice(0,2), wires:[], topologyTransport:{
      beforeReply:(url) => url.endsWith('/gesture') && ++gesture === 2 ? held : undefined,
    }});
    try {
      await view.click(view.card('a'));
      await view.mouse(view.card('b'), 'click', {shiftKey:true});
      assert.deepEqual(['a','b'].map(id => view.card(id).getAttribute('data-selected')), ['true','true']);
      assert.equal(view.selectionApi.getSnapshot().topology.pending, true);
      assert.equal(view.groupButton().disabled, false, 'an in-flight selection must not silently discard the Group click');
      await view.click(view.groupButton());
      assert.equal(view.calls.filter(call => call[0] === 'post' && call[1].endsWith('/interaction')).length, 0);
      await view.act(() => release());
      await view.settle(120);
      const interactions = view.calls.filter(call => call[0] === 'post' && call[1].endsWith('/interaction'));
      assert.equal(interactions.length, 1, 'round ' + round + ': exactly one admitted Group action');
      assert.equal(view.card('group-node') !== null, true, 'round ' + round + ': created card renders');
      assert.equal(view.card('group-node').querySelectorAll('[data-member-chip]').length, 2);
      assert.match(view.toast(), /Grouped 2 nodes/);
      // The new card mounted while menuBusy=true; its later drop must use current admission.
      const beforeDrop = view.selectionApi.getSnapshot().topology.canvas.revision;
      await p10Drop(view);
      const removes = view.calls.filter(call => call[0] === 'post' && call[2].membership);
      assert.equal(removes.length, 1, 'round ' + round + ': drag after Group still posts');
      assert.equal(view.selectionApi.getSnapshot().topology.canvas.revision, beforeDrop + 1);
      assert.equal(view.card('group-node').querySelectorAll('[data-member-chip]').length, 1);
    } finally { release(); await view.close(); }
  }
});

test('UPD2 p10 refusals: no remove transport is visible and never traced as posted', async () => {
  const view = await mount({nodes:P10_GROUP_NODES(), wires:[]});
  try {
    const chip = await p10Drop(view);
    assert.match(chip.getAttribute('data-member-drag'), /^refused: .*unavailable/);
    assert.match(view.toast(), /Removing a member is unavailable/);
    assert.equal(view.card('group-node').querySelectorAll('[data-member-chip]').length, 2);
    assert.equal(view.calls.filter(call => call[0] === 'post').length, 0);
  } finally { await view.close(); }
});

test('UPD2 p10 refusals: Group ok:false and drag server refusal are visible without a success notice', async () => {
  const group = await mount({nodes:NODES().slice(0,2), wires:[], topologyTransport:{
    refuse:url => url.endsWith('/interaction') ? 'Group owner refused these nodes.' : '',
  }});
  try {
    await group.click(group.card('a'));
    await group.mouse(group.card('b'), 'click', {shiftKey:true});
    await group.click(group.groupButton()); await group.settle(5);
    assert.equal(group.card('group-node'), null);
    assert.match(group.toast(), /Group owner refused these nodes/);
    assert.doesNotMatch(group.toast(), /Grouped 2 nodes/);
  } finally { await group.close(); }
  const drag = await mount({nodes:P10_GROUP_NODES(), wires:[], topologyTransport:{
    refuse:url => url.endsWith('/interaction') ? 'Member owner refused this drop.' : '',
  }});
  try {
    const chip = await p10Drop(drag);
    assert.match(chip.getAttribute('data-member-drag'), /^refused: .*Member owner refused/);
    assert.match(drag.toast(), /Member owner refused this drop/);
    assert.equal(drag.card('group-node').querySelectorAll('[data-member-chip]').length, 2);
    assert.equal(drag.calls.filter(call => call[0] === 'post').length, 1);
  } finally { await drag.close(); }
});

test('UPD2 p10 trace: pending drop is never posted before the transport answers; a second busy drop is visibly refused', async () => {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const view = await mount({nodes:P10_GROUP_NODES(), wires:[], topologyTransport:{beforeReply:() => held}});
  try {
    const first = await p10Drop(view, 'a');
    assert.equal(first.getAttribute('data-member-drag'), 'pending');
    const second = await p10Drop(view, 'b');
    assert.match(second.getAttribute('data-member-drag'), /^refused: .*current action/);
    assert.match(view.toast(), /Wait for the current action/);
    assert.equal(view.calls.filter(call => call[0] === 'post').length, 1);
    await view.act(() => release()); await view.settle(5);
    assert.equal(first.getAttribute('data-member-drag'), 'posted');
    assert.equal(view.card('group-node').querySelectorAll('[data-member-chip]').length, 1);
  } finally { release(); await view.close(); }
});

test('UPD2 p10 refusals: a Group receipt without its refreshed card is visibly refused', async () => {
  const view = await mount({nodes:NODES().slice(0,2), wires:[], topologyTransport:{missingGroup:true}});
  try {
    await view.click(view.card('a'));
    await view.mouse(view.card('b'), 'click', {shiftKey:true});
    await view.click(view.groupButton()); await view.settle(5);
    assert.equal(view.calls.filter(call => call[0] === 'post' && call[1].endsWith('/interaction')).length, 1);
    assert.equal(view.card('group-node'), null);
    assert.match(view.toast(), /created group card is not visible/);
    assert.doesNotMatch(view.toast(), /Grouped 2 nodes/);
  } finally { await view.close(); }
});
