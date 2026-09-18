/* The founder asked why a card position takes so long to save and why anything is
   saved after every movement at all. It was: every mouseup published its own signed
   revision. A drag is a gesture now -- the canvas draws it at once and the burst is
   written ONCE, after the canvas has been still for CANVAS_LAYOUT_COALESCE_MS, against
   the points the burst started from. These courts bind that: one write per burst and
   not per drag, a flush when the canvas is left or the window closes, a refusal that
   restores the last confirmed layout and says so, a pending write that is visible, and
   an undo of a burst that lands on the pre-burst layout. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const sourcePath = process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(root, 'nodelang/studio/studio-lm.jsx');
const source = fs.readFileSync(sourcePath, 'utf8');
const tokens = fs.readFileSync(path.join(root, 'nodelang/studio/tokens.jsx'), 'utf8');

const palette = tokens.slice(tokens.indexOf('window.AH = {'), tokens.indexOf('window.ArchHubTheme ='));
const LM = new Proxy(Object.fromEntries([...palette.matchAll(/^ {2}(\w+):/gm)].map(m => [m[1], 'token-' + m[1]])), {
  get:(held, key) => {
    if (key === 'rad') return {xs:3, sm:5, md:6, lg:8, xl:10, pill:999};
    if (key === 'sp') return {xs:4, sm:8, md:12, lg:16, xl:24};
    if (typeof key === 'string' && !(key in held)) throw new Error('studio-lm.jsx reads an undefined token: ' + key);
    return held[key];
  }});

const slice = () => {
  const start = source.indexOf('const SOCKET_TOP =');
  const end = source.indexOf('const NodeStateDot =', start);
  assert.ok(start > 0 && end > start, 'the canvas is a slice of the shipped studio-lm.jsx');
  return source.slice(start, end);
};

// The window this build coalesces a burst over, read from the shipped constant.
function coalesceWindow() {
  const match = /const CANVAS_LAYOUT_COALESCE_MS = (\d+);/.exec(source);
  assert.ok(match, 'studio-lm.jsx names one coalescing window constant');
  const value = Number(match[1]);
  assert.ok(value >= 400 && value <= 600, 'the coalescing window is 400-600 ms, is ' + value);
  return value;
}

function pureHarness() {
  const context = vm.createContext({});
  const text = slice();
  const start = text.indexOf('const CANVAS_LAYOUT_COALESCE_MS =');
  const end = text.indexOf('const NodeCanvas = (', start);
  assert.ok(start > 0 && end > start, 'the burst helpers are module-level in studio-lm.jsx');
  vm.runInContext(text.slice(start, end) +
    '\nglobalThis.merge = mergeCanvasLayoutBurst; globalThis.moves = canvasLayoutBurstMoves;', context);
  return context;
}

test('a burst keeps the point every node started the BURST at, and the latest point it reached', () => {
  const {merge, moves} = pureHarness();
  let burst = merge(null, {next:{a:{x:20, y:20}}, before:{a:{x:0, y:0}}, revision:7});
  burst = merge(burst, {next:{a:{x:40, y:40}}, before:{a:{x:20, y:20}}, revision:8});
  burst = merge(burst, {next:{b:{x:60, y:0}}, before:{b:{x:0, y:0}}, revision:8});
  assert.deepEqual(JSON.parse(JSON.stringify(burst)), {
    next:{a:{x:40, y:40}, b:{x:60, y:0}},
    before:{a:{x:0, y:0}, b:{x:0, y:0}},
    revision:7,
  });
  assert.equal(moves(burst).map(([id]) => id).join(','), 'a,b');
  // A node the burst put back where it started writes nothing at all.
  const returned = merge(merge(null, {next:{a:{x:20, y:20}}, before:{a:{x:0, y:0}}, revision:7}),
    {next:{a:{x:0, y:0}}, before:{a:{x:20, y:20}}, revision:7});
  assert.equal(moves(returned).length, 0);
});

const NODES = [
  {id:'one', cat:'logic', live:true, x:40, y:60, w:200, h:90, title:'One', sub:'node', params:[], ins:[], outs:[]},
  {id:'two', cat:'logic', live:true, x:400, y:60, w:200, h:90, title:'Two', sub:'node', params:[], ins:[], outs:[]},
];

async function mount({refuse = null, hold = null} = {}) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const saves = [];
  let snapshot = {graph:{nodes:NODES, wires:[]}, canvas:{revision:3, scope:{current:'scope'}}};
  let refreshes = 0;
  dom.window.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({topology:{canvas:{revision:snapshot.canvas.revision, scope:snapshot.canvas.scope,
      nodes:snapshot.graph.nodes, wires:[]}}}),
    moveTopologyNodes:async (positions, expectedRevision, expectedPositions) => {
      saves.push({positions:JSON.parse(JSON.stringify(positions)), expectedRevision,
        expectedPositions:JSON.parse(JSON.stringify(expectedPositions))});
      // A save the court can hold open, so a burst can be armed while one is in flight.
      if (hold && saves.length === 1) await hold.promise;
      if (refuse) throw new Error(refuse);
      snapshot = {...snapshot, canvas:{...snapshot.canvas, revision:snapshot.canvas.revision + 1},
        graph:{...snapshot.graph, nodes:snapshot.graph.nodes.map(node =>
          positions[node.id] ? {...node, ...positions[node.id]} : node)}};
      return {ok:true};
    },
    refreshTopologyCanvas:async () => { refreshes += 1; return snapshot; },
  };
  const context = vm.createContext({React, LM, window:dom.window, document:dom.window.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope',
    studioCategory:cat => ({col:'token-cat', icon:'+', label:String(cat).toUpperCase()}), WIRE:{},
    NodeBody:() => null, CanvasToolbar:() => null, FloatingComposer:() => null, MiniMap:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({}),
    setTimeout:dom.window.setTimeout.bind(dom.window), clearTimeout:dom.window.clearTimeout.bind(dom.window)});
  vm.runInContext(transformSync(slice() + '\nglobalThis.NodeCanvas = NodeCanvas;',
    {loader:'jsx', format:'cjs'}).code, context);
  const reactRoot = createRoot(dom.window.document.getElementById('root'));
  const props = {focusId:null, setFocusId:() => {}, setLibraryOpen:() => {}, userNodes:[],
    addNodeFromLibrary:() => {}, model:null};
  const draw = async () => {
    await React.act(async () => reactRoot.render(React.createElement(context.NodeCanvas, props)));
    return dom.window.document;
  };
  await draw();
  const card = id => dom.window.document.querySelector('.lm-node[data-node-id="' + id + '"]');
  const point = id => ({x:parseFloat(card(id).style.left), y:parseFloat(card(id).style.top)});
  const fire = (target, type, init) => target.dispatchEvent(
    new dom.window.MouseEvent(type, {bubbles:true, cancelable:true, ...init}));
  return {
    saves, point, card, draw,
    refreshCount: () => refreshes,
    chip: () => {
      const status = dom.window.document.querySelector('[role="status"],[role="alert"]');
      return status ? status.textContent : '';
    },
    drag: async (id, dx, dy) => {
      const handle = card(id).children[0];
      await React.act(async () => {
        fire(handle, 'mousedown', {button:0, clientX:0, clientY:0});
      });
      await React.act(async () => {
        fire(dom.window.document, 'mousemove', {clientX:dx, clientY:dy});
      });
      await React.act(async () => { fire(dom.window.document, 'mouseup', {}); });
    },
    settle: async ms => { await React.act(async () => {
      await new Promise(done => dom.window.setTimeout(done, ms)); }); },
    leave: async () => { await React.act(async () => {
      dom.window.dispatchEvent(new dom.window.Event('beforeunload')); }); },
    reset: async () => {
      const region = dom.window.document.querySelector('[role="region"][aria-label="Workflow canvas"]');
      assert.ok(region, 'the canvas region is drawn');
      await React.act(async () => {
        region.dispatchEvent(new dom.window.KeyboardEvent('keydown',
          {key:'R', ctrlKey:true, shiftKey:true, bubbles:true, cancelable:true}));
      });
    },
    close: async () => {
      await React.act(async () => reactRoot.unmount());
      dom.window.close(); global.window = oldWindow; global.document = oldDocument;
      delete global.IS_REACT_ACT_ENVIRONMENT;
    },
  };
}

test('ten drags inside one window are ONE write, against the pre-burst points', async () => {
  const wait = coalesceWindow();
  const view = await mount();
  try {
    const started = {one:view.point('one'), two:view.point('two')};
    for (let step = 1; step <= 5; step += 1) {
      await view.drag('one', step * 40, step * 40);
      await view.drag('two', step * 40, 0);
      await view.settle(Math.max(1, Math.floor(wait / 4)));
    }
    assert.equal(view.saves.length, 0, 'not one write while the canvas is still being dragged');
    const preview = {one:view.point('one'), two:view.point('two')};
    assert.notDeepEqual(preview.one, started.one, 'the canvas shows the new place at once');
    await view.settle(wait * 2);
    assert.equal(view.saves.length, 1, 'the whole burst is one write');
    const [save] = view.saves;
    assert.deepEqual(Object.keys(save.positions).sort(), ['one', 'two']);
    assert.deepEqual(save.positions.one, preview.one);
    assert.deepEqual(save.positions.two, preview.two);
    assert.deepEqual(save.expectedPositions.one, started.one, 'the burst base, not the last drag base');
    assert.deepEqual(save.expectedPositions.two, started.two);
    assert.equal(save.expectedRevision, 3, 'the revision the burst started on');
  } finally { await view.close(); }
});

test('a drag after the window closes is its own write; the canvas is interactive throughout', async () => {
  const wait = coalesceWindow();
  const view = await mount();
  try {
    await view.drag('one', 40, 40);
    await view.settle(wait * 2);
    assert.equal(view.saves.length, 1);
    await view.drag('one', 80, 80);
    await view.settle(wait * 2);
    assert.equal(view.saves.length, 2, 'a later burst is a later write');
    assert.equal(view.saves[1].expectedRevision, 4, 'it starts from the revision the first write produced');
  } finally { await view.close(); }
});

test('a pending write is visible and says so before it goes out', async () => {
  const wait = coalesceWindow();
  const view = await mount();
  try {
    await view.drag('one', 40, 40);
    assert.equal(view.saves.length, 0);
    assert.match(view.chip(), /Saving positions/, 'the chip shows the write that has not gone out yet');
    await view.settle(wait * 2);
    assert.equal(view.saves.length, 1);
  } finally { await view.close(); }
});

test('closing the window writes the pending burst before anything is lost', async () => {
  const view = await mount();
  try {
    await view.drag('one', 40, 40);
    assert.equal(view.saves.length, 0);
    await view.leave();
    assert.equal(view.saves.length, 1, 'beforeunload flushes the burst');
  } finally { await view.close(); }
});

test('the held save answers and the canvas goes quiet', async () => {
  const wait = coalesceWindow();
  const hold = {}; hold.promise = new Promise(resolve => { hold.release = resolve; });
  const view = await mount({hold});
  await view.drag('one', 40, 40);
  await view.settle(wait * 2);
  assert.equal(view.saves.length, 1);
  hold.release();
  await view.settle(wait * 2);
  assert.equal(view.chip(), '', 'the save answered, so nothing is pending');
  await view.close();
});

test('leaving the canvas writes the pending burst', async () => {
  const view = await mount();
  await view.drag('one', 40, 40);
  assert.equal(view.saves.length, 0);
  await view.close();
  assert.equal(view.saves.length, 1, 'unmount flushes the burst');
});

test('a refused burst restores the last confirmed layout and says it did', async () => {
  const wait = coalesceWindow();
  const view = await mount({refuse:'The layout save needs reconciliation.'});
  try {
    const started = {one:view.point('one')};
    await view.drag('one', 40, 40);
    await view.drag('one', 120, 120);
    await view.settle(wait * 3);
    assert.equal(view.saves.length, 1, 'the refused burst was one write, not two');
    assert.deepEqual(view.saves[0].expectedPositions.one, started.one);
    assert.deepEqual(view.point('one'), started.one, 'the last confirmed layout is back on the canvas');
    assert.match(view.chip(), /The last confirmed layout was restored\./);
  } finally { await view.close(); }
});

test('the shipped source arms a burst on mouseup and never writes from the drag itself', () => {
  coalesceWindow();
  const text = slice();
  assert.match(text, /if \(drag\?\.mode === 'nodes' && drag\.last\) \{\s*armLayoutRef\.current\(/);
  assert.equal(/drag\.mode === 'nodes' && drag\.last\) \{\s*saveRef\.current\(/.test(text), false,
    'a mouseup no longer publishes its own revision');
  assert.match(text, /window\.addEventListener\('beforeunload', leave\)/);
  assert.match(text, /window\.addEventListener\('pagehide', leave\)/);
  assert.match(text, /return \(\) => \{ flushRef\.current\(true\); alive\.current = false;/,
    'leaving the canvas forces the flush, so a burst behind an in-flight save is not dropped');
});
test('one undo of a burst lands on the pre-burst layout', async () => {
  const wait = coalesceWindow();
  const view = await mount();
  try {
    const started = {one:view.point('one'), two:view.point('two')};
    await view.drag('one', 40, 40);
    await view.drag('two', 80, 0);
    await view.drag('one', 160, 160);
    await view.settle(wait * 2);
    assert.equal(view.saves.length, 1, 'the burst was one write');
    await view.draw();
    await view.reset();
    await view.settle(wait * 2);
    assert.equal(view.saves.length, 2, 'the undo is its own act');
    assert.deepEqual(view.saves[1].positions.one, started.one, 'one is back where the burst started');
    assert.deepEqual(view.saves[1].positions.two, started.two, 'two is back where the burst started');
  } finally { await view.close(); }
});