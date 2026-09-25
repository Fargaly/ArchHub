/* Founder order 2026-09-24: "why is nothing organised or grouped?" -- cards stacked on
   each other, hard to move, Arrange that moved what he had placed by hand. These courts
   bind the canvas side of the answer:
     T1  Arrange writes with placement 'arrange' and never sends a hand-placed card;
     T2  Arrange clicked while a save is in flight runs ONCE, after that save answers;
     T3  Arrange over hand-placed cards only writes nothing and says why;
     T4  the arranged layout overlaps no card, hand-placed obstacles included;
     T5  every frame (group) is packed as its own block, so frames never interleave;
   plus: a hand drag is a plain move (the owner pins it), frames are drawn per group,
   the canvas draws only the user's cards, and the application's own cards are the
   founder's System view, framed by domain. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
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

function arrange() {
  const context = vm.createContext({});
  const text = slice();
  const start = text.indexOf('const canvasArrangePositions =');
  const end = text.indexOf('const CANVAS_LAYOUT_COALESCE_MS', start);
  assert.ok(start > 0 && end > start, 'Arrange is a module-level function');
  vm.runInContext(text.slice(start, end) + '\nglobalThis.arrange = canvasArrangePositions;', context);
  return context.arrange;
}

const SIZE = {w:220, h:110};
const overlaps = (a, b) => a.x < b.x + SIZE.w && a.x + SIZE.w > b.x && a.y < b.y + SIZE.h && a.y + SIZE.h > b.y;

test('T4: the arranged layout overlaps no card, and hand-placed obstacles are avoided', () => {
  const place = arrange();
  // Nine cards stacked on one point, the way the old default grid drew them, and one
  // hand-placed card sitting right where the block would start.
  const positions = Object.fromEntries([...Array(9)].map((_, i) => ['c' + i, {x:60, y:92}]));
  positions.pinned = {x:60, y:92};
  const ids = Object.keys(positions).filter(id => id !== 'pinned');
  const sizes = Object.fromEntries(Object.keys(positions).map(id => [id, SIZE]));
  const next = place(ids, positions, sizes, Object.keys(positions), [], id => (id < 'c5' ? 'Ordered List' : 'Cells'));
  assert.deepEqual(Object.keys(next).sort(), ids.sort(), 'only the chosen cards are moved; the pinned one is not');
  const all = {...next, pinned:positions.pinned};
  const names = Object.keys(all);
  for (let i = 0; i < names.length; i += 1) for (let j = i + 1; j < names.length; j += 1) {
    assert.equal(overlaps(all[names[i]], all[names[j]]), false, names[i] + ' overlaps ' + names[j]);
  }
});

test('T5: every frame is packed as its own block, so two frames never interleave', () => {
  const place = arrange();
  const frameOf = id => id.startsWith('a') ? 'A' : id.startsWith('b') ? 'B' : 'C';
  // Interleaved on purpose: A and B cards alternate in reading order.
  const ids = ['a1', 'b1', 'a2', 'b2', 'c1', 'a3', 'b3'];
  const positions = Object.fromEntries(ids.map((id, i) => [id, {x:i * 30, y:0}]));
  const sizes = Object.fromEntries(ids.map(id => [id, SIZE]));
  const wires = [{from:['a1'], to:['b1']}];  // a wire across frames does not merge them
  const next = place(ids, positions, sizes, ids, wires, frameOf);
  const box = frame => {
    const members = ids.filter(id => frameOf(id) === frame).map(id => next[id]);
    return {top:Math.min(...members.map(p => p.y)), bottom:Math.max(...members.map(p => p.y + SIZE.h))};
  };
  const [A, B, C] = ['A', 'B', 'C'].map(box);
  assert.ok(A.bottom < B.top && B.bottom < C.top, 'frame blocks are stacked, not interleaved: ' + JSON.stringify({A, B, C}));
  assert.ok(B.top - A.bottom >= 96 && C.top - B.bottom >= 96, 'room for a frame border and title between frames');
});

const NODES = () => [
  {id:'one', cat:'logic', live:true, x:40, y:60, w:220, h:110, title:'One', sub:'node', params:[], ins:[], outs:[],
    group:'Ordered List', pinned:false},
  {id:'two', cat:'logic', live:true, x:40, y:60, w:220, h:110, title:'Two', sub:'node', params:[], ins:[], outs:[],
    group:'Ordered List', pinned:false},
  {id:'three', cat:'logic', live:true, x:40, y:60, w:220, h:110, title:'Three', sub:'node', params:[], ins:[], outs:[],
    group:'Ordered List', pinned:false},
  {id:'mine', cat:'logic', live:true, x:900, y:500, w:220, h:110, title:'Mine', sub:'node', params:[], ins:[], outs:[],
    group:'Cells', pinned:true},
];
// What the application placed on the top level: the owner marks it, the canvas keeps it
// for the founder's System view. A wire between two of them is theirs too.
const INTERNALS = [
  {id:'gm:domain:ui', cat:'logic', live:true, x:60, y:92, w:220, h:110, title:'UI & Design System', sub:'domain',
    params:[], ins:[], outs:[{id:'o', t:'any'}], group:'UI & Design System', pinned:false, application:true},
  {id:'app:agent-session:a', cat:'logic', live:true, x:60, y:92, w:220, h:110, title:'Runtime-a', sub:'agent',
    params:[], ins:[{id:'i', t:'any'}], outs:[], group:'Models & Agents', pinned:false, application:true},
];
const MARKED = () => [...NODES().map(node => ({...node, application:false})), ...INTERNALS];

async function mount({hold = null, systemView = false, nodes = NODES(), wires = []} = {}) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53913/'});
  // jsdom lays nothing out; Arrange measures the drawn cards.
  for (const [name, value] of [['offsetWidth', SIZE.w], ['offsetHeight', SIZE.h]]) {
    Object.defineProperty(dom.window.HTMLElement.prototype, name, {configurable:true, get() { return value; }});
  }
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const saves = [];
  let snapshot = {graph:{nodes, wires}, canvas:{revision:3, scope:{current:'scope'},
    authorization:{subject:'founder', session:'s', system_view:systemView}}};
  dom.window.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({topology:snapshot}),
    moveTopologyNodes:async (positions, expectedRevision, expectedPositions, placement) => {
      saves.push({positions:JSON.parse(JSON.stringify(positions)), expectedRevision, placement: placement ?? null});
      if (hold && saves.length === 1) await hold.promise;
      snapshot = {...snapshot, canvas:{...snapshot.canvas, revision:snapshot.canvas.revision + 1},
        graph:{...snapshot.graph, nodes:snapshot.graph.nodes.map(node => positions[node.id]
          ? {...node, ...positions[node.id], pinned:node.pinned || placement !== 'arrange'} : node)}};
      return {ok:true};
    },
    refreshTopologyCanvas:async () => snapshot,
  };
  const context = vm.createContext({React, LM, window:dom.window, document:dom.window.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope',
    studioCategory:cat => ({col:'token-cat', icon:'+', label:String(cat).toUpperCase()}), WIRE:{},
    NodeBody:() => null, CanvasToolbar:() => null, FloatingComposer:() => null, MiniMap:() => null, Socket:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({}),
    setTimeout:dom.window.setTimeout.bind(dom.window), clearTimeout:dom.window.clearTimeout.bind(dom.window)});
  vm.runInContext(transformSync(slice() + '\nglobalThis.NodeCanvas = NodeCanvas;',
    {loader:'jsx', format:'cjs'}).code, context);
  const reactRoot = createRoot(dom.window.document.getElementById('root'));
  const props = {focusId:null, setFocusId:() => {}, setLibraryOpen:() => {}, userNodes:[],
    addNodeFromLibrary:() => {}, model:null};
  const draw = async () => { await React.act(async () => reactRoot.render(React.createElement(context.NodeCanvas, props))); };
  await draw();
  const doc = dom.window.document;
  const card = id => doc.querySelector('.lm-node[data-node-id="' + id + '"]');
  const point = id => ({x:parseFloat(card(id).style.left), y:parseFloat(card(id).style.top)});
  const fire = (target, type, init) => target.dispatchEvent(new dom.window.MouseEvent(type, {bubbles:true, cancelable:true, ...init}));
  const region = () => doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
  return {
    saves, doc, point, draw,
    chip: () => { const s = doc.querySelector('[role="status"],[role="alert"]'); return s ? s.textContent : ''; },
    arrange: async () => { await React.act(async () => { region().dispatchEvent(new dom.window.KeyboardEvent('keydown',
      {key:'L', ctrlKey:true, shiftKey:true, bubbles:true, cancelable:true})); }); },
    undo: async () => { await React.act(async () => { region().dispatchEvent(new dom.window.KeyboardEvent('keydown',
      {key:'R', ctrlKey:true, shiftKey:true, bubbles:true, cancelable:true})); }); },
    drag: async (id, dx, dy) => {
      const handle = card(id).children[0];
      await React.act(async () => { fire(handle, 'mousedown', {button:0, clientX:0, clientY:0}); });
      await React.act(async () => { fire(doc, 'mousemove', {clientX:dx, clientY:dy}); });
      await React.act(async () => { fire(doc, 'mouseup', {}); });
    },
    // A click on empty canvas clears the selection, as it does for the user.
    clearSelection: async () => {
      await React.act(async () => { fire(region(), 'mousedown', {button:0, clientX:5, clientY:5}); });
      await React.act(async () => { fire(doc, 'mouseup', {}); });
    },
    click: async el => { await React.act(async () => { el.dispatchEvent(new dom.window.MouseEvent('click', {bubbles:true})); }); },
    settle: async ms => { await React.act(async () => { await new Promise(done => dom.window.setTimeout(done, ms)); }); },
    close: async () => {
      await React.act(async () => reactRoot.unmount());
      dom.window.close(); global.window = oldWindow; global.document = oldDocument;
      delete global.IS_REACT_ACT_ENVIRONMENT;
    },
  };
}

test('T1: Arrange writes with placement arrange and never sends a hand-placed card', async () => {
  const view = await mount();
  try {
    const mine = view.point('mine');
    await view.arrange();
    await view.settle(20);
    assert.equal(view.saves.length, 1, 'one Arrange is one write');
    assert.equal(view.saves[0].placement, 'arrange');
    const sent = Object.keys(view.saves[0].positions);
    assert.ok(sent.length >= 2 && !sent.includes('mine'), 'the hand-placed card is not sent: ' + sent);
    await view.draw();
    assert.deepEqual(view.point('mine'), mine, 'the hand-placed card did not move');
    const cards = ['one', 'two', 'three', 'mine'];
    for (let i = 0; i < cards.length; i += 1) for (let j = i + 1; j < cards.length; j += 1) {
      assert.equal(overlaps(view.point(cards[i]), view.point(cards[j])), false, cards[i] + ' overlaps ' + cards[j]);
    }
  } finally { await view.close(); }
});

test('undoing Arrange moves the cards back as an arrange, so none of them is pinned', async () => {
  const view = await mount();
  try {
    await view.arrange();
    await view.settle(20);
    assert.equal(view.saves.length, 1);
    await view.draw();
    await view.undo();
    await view.settle(20);
    assert.equal(view.saves.length, 2, 'chip: ' + view.chip());
    assert.equal(view.saves[1].placement, 'arrange', 'the undo of an Arrange is not a hand move');
    assert.deepEqual(Object.keys(view.saves[1].positions).sort(), Object.keys(view.saves[0].positions).sort());
  } finally { await view.close(); }
});

test('a hand drag is a plain move: the owner pins it, Arrange never moves it afterwards', async () => {
  const view = await mount();
  try {
    await view.drag('one', 400, 0);
    await view.settle(1200);
    assert.equal(view.saves.length, 1);
    assert.equal(view.saves[0].placement, null, 'a drag carries no arrange placement');
    await view.draw();
    await view.clearSelection();
    await view.arrange();
    await view.settle(20);
    assert.equal(view.saves.length, 2, 'chip: ' + view.chip());
    const sent = Object.keys(view.saves[1].positions);
    assert.ok(sent.length && !sent.includes('one') && !sent.includes('mine'), 'the dragged card is pinned now: ' + sent);
  } finally { await view.close(); }
});

test('T2: Arrange clicked while a save is in flight runs once, after that save answers', async () => {
  const hold = {}; hold.promise = new Promise(resolve => { hold.release = resolve; });
  const view = await mount({hold});
  try {
    await view.drag('one', 400, 0);
    await view.settle(1200);
    assert.equal(view.saves.length, 1, 'the drag is out and held open');
    await view.clearSelection();
    await view.arrange();
    await view.arrange();
    assert.equal(view.saves.length, 1, 'nothing else is written while the save is in flight');
    assert.match(view.chip(), /Arrange will run after the current save finishes\./);
    hold.release();
    await view.settle(50);
    await view.draw();
    await view.settle(50);
    assert.equal(view.saves.length, 2, 'the remembered Arrange ran exactly once');
    assert.equal(view.saves[1].placement, 'arrange');
    const sent = Object.keys(view.saves[1].positions);
    assert.ok(sent.length && !sent.includes('one'), 'it skips the card the drag just pinned: ' + sent);
  } finally { await view.close(); }
});

test('T3: Arrange over hand-placed cards only writes nothing and says why', async () => {
  const nodes = NODES().map(node => ({...node, pinned:true}));
  const view = await mount({nodes});
  try {
    await view.arrange();
    await view.settle(20);
    assert.equal(view.saves.length, 0);
    assert.match(view.chip(), /Every chosen card was placed by hand\./);
  } finally { await view.close(); }
});

test('frames are drawn per group around their cards', async () => {
  const view = await mount();
  try {
    const frames = [...view.doc.querySelectorAll('[data-canvas-frame]')];
    assert.deepEqual(frames.map(frame => frame.getAttribute('data-canvas-frame')).sort(), ['Cells', 'Ordered List']);
    const list = frames.find(frame => frame.getAttribute('data-canvas-frame') === 'Ordered List');
    assert.match(list.textContent, /ORDERED LIST · 3/);
  } finally { await view.close(); }
});

test('the canvas draws the user\'s cards; the application\'s are the founder\'s System view, by domain', async () => {
  const wires = [{id:'w1', from:['gm:domain:ui', 'o'], to:['app:agent-session:a', 'i']}];
  const member = await mount({systemView:false, nodes:MARKED(), wires});
  try {
    const drawn = [...member.doc.querySelectorAll('.lm-node[data-node-id]')].map(c => c.getAttribute('data-node-id'));
    assert.deepEqual(drawn.sort(), ['mine', 'one', 'three', 'two']);
    assert.equal([...member.doc.querySelectorAll('button')].some(b => b.textContent === 'System view'), false,
      'nobody but the founder is offered the System view');
    assert.equal(member.doc.querySelector('details[data-no-pan] summary'), null,
      'a wire between hidden cards is not reported as undrawable');
  } finally { await member.close(); }
  const founder = await mount({systemView:true, nodes:MARKED(), wires});
  try {
    const cards = () => [...founder.doc.querySelectorAll('.lm-node[data-node-id]')].map(c => c.getAttribute('data-node-id')).sort();
    assert.deepEqual(cards(), ['mine', 'one', 'three', 'two'], 'the founder\'s canvas opens on his own cards');
    const button = [...founder.doc.querySelectorAll('button')].find(b => b.textContent === 'System view');
    assert.ok(button, 'the founder is offered the System view');
    await founder.click(button);
    assert.deepEqual(cards(), ['app:agent-session:a', 'gm:domain:ui']);
    assert.deepEqual([...founder.doc.querySelectorAll('[data-canvas-frame]')].map(f => f.getAttribute('data-canvas-frame')).sort(),
      ['Models & Agents', 'UI & Design System'], 'framed by domain');
    assert.equal(founder.doc.querySelectorAll('.lm-wires path[stroke="transparent"]').length, 1, 'their wire is drawn with them');
    const back = [...founder.doc.querySelectorAll('button')].find(b => b.textContent === 'My canvas');
    await founder.click(back);
    assert.deepEqual(cards(), ['mine', 'one', 'three', 'two']);
  } finally { await founder.close(); }
});

test('an empty canvas says it holds only what the user places', async () => {
  const view = await mount({nodes:INTERNALS, systemView:true});
  try {
    const note = view.doc.querySelector('[role="note"]');
    assert.match(note.textContent, /This canvas holds only what you place on it\./);
    assert.match(note.textContent, /System view/);
  } finally { await view.close(); }
});
