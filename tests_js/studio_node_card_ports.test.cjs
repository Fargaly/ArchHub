/* Canvas node cards as the founder design bundle draws them (archhub/project/studio-lm.jsx: NodeCanvas wires
   1403-1427, NodeRenderer 1575-1635, Socket 1651-1674): the title and summary sit in the card body as drawn. The
   sockets sit in a port band BELOW that content (d649e84f: fixed offsets drew port labels over the title and
   summary), one 19px row per port index, on the card's own edges; every wire ends at its row in the band the card
   reports. The live graph keeps its handles: a connectable port is a button that starts or finishes a
   wire through the application's topology transport; a port the server marks not connectable stays inert. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const tokens = fs.readFileSync(path.join(__dirname, '../nodelang/studio/tokens.jsx'), 'utf8');

// The canvas may read only palette names the shipped tokens.jsx defines; an unknown token throws.
const palette = tokens.slice(tokens.indexOf('window.AH = {'), tokens.indexOf('window.ArchHubTheme ='));
const LM = new Proxy(Object.fromEntries([...palette.matchAll(/^ {2}(\w+):/gm)].map(match => [match[1], 'token-' + match[1]])), {
  get:(held, key) => {
    if (key === 'rad') return {xs:3, sm:5, md:6, lg:8, xl:10, pill:999};
    if (key === 'sp') return {xs:4, sm:8, md:12, lg:16, xl:24};
    if (typeof key === 'string' && !(key in held)) throw new Error('studio-lm.jsx reads an undefined token: ' + key);
    return held[key];
  }});

// The socket geometry: one 19px row per port, radius 5, the band padded 4px (studio-lm.jsx PORT_BAND_PAD).
const STEP = 19, RADIUS = 5, PAD = 4;
const rowCentre = index => PAD + index * STEP + STEP / 2;
// jsdom has no layout: the band's offsetTop is what the card reports, so the court sets it.
let bandTop = 0;
const connection = {mode:'connection', connect_control:'control-a', connect_choices:[{id:'in-a'}]};
// The card from the founder window (2026-09-17): a Work title that wraps, eleven input ports and a "Graph node" summary.
const workPorts = ['dependencies', 'description', 'external-key', 'inputs', 'outputs', 'plan', 'priority',
  'required-capabilities', 'requirements', 'scope', 'title'];
const nodes = [
  {id:'work', cat:'logic', live:true, x:40, y:60, w:210, h:263,
    title:'Claude717 landing: reviewed source patches for the design release', sub:'Graph node', params:[],
    ins:workPorts.map(name => ({id:'in-' + name, label:name, t:'any', connectable:true, ...connection})),
    outs:[{id:'out-result', label:'result', t:'any', connectable:true, ...connection}]},
  {id:'sink', cat:'read', live:true, x:420, y:300, w:210, h:110, title:'Sketch Lines', sub:'vision.sketch_lines',
    params:[], ins:[{id:'in-a', label:'a', t:'any', connectable:true, ...connection},
      {id:'in-b', label:'b', t:'any', connectable:true, ...connection}],
    outs:[]},
  {id:'policy', cat:'logic', live:true, x:40, y:420, w:210, h:110, title:'Governed Work', sub:'Graph node', params:[],
    ins:[{id:'in-policy', label:'applicable-policy', t:'any', connectable:false, mode:'connection'}], outs:[]},
];
const wires = [{id:'wire-1', from:['work', 'out-result'], to:['sink', 'in-b']}];

async function mount() {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const start = source.indexOf('const SOCKET_TOP =');
  const end = source.indexOf('const NodeStateDot =', start);
  const socketStart = source.indexOf('const Socket = (', end);
  const socketEnd = source.indexOf('const ModelInWindow =', socketStart);
  assert.ok(start > 0 && end > start && socketStart > end && socketEnd > socketStart,
    'the canvas, node card and socket are slices of the shipped studio-lm.jsx');
  const dom = new JSDOM('<div id="root"></div>');
  Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetTop', {configurable:true,
    get() { return this.hasAttribute('data-port-band') ? bandTop : 0; }});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const connected = [];
  dom.window.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => ({topology:{canvas:snapshot.canvas}}),
    connectTopology:async (...args) => { connected.push(args); },
  };
  let snapshot = {graph:{nodes, wires}, canvas:{revision:3, scope:{current:'scope'}}};
  const context = vm.createContext({React, LM, window:dom.window, document:dom.window.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope',
    studioCategory:cat => ({col:'token-cat', icon:'+', label:String(cat).toUpperCase()}), WIRE:{},
    NodeBody:() => null, CanvasToolbar:() => null, FloatingComposer:() => null, MiniMap:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({}), kbd:() => ({})});
  vm.runInContext(transformSync(source.slice(start, end) + '\n' + source.slice(socketStart, socketEnd) +
    '\nglobalThis.NodeCanvas = NodeCanvas;', {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(dom.window.document.getElementById('root'));
  const props = {focusId:null, setFocusId:() => {}, setLibraryOpen:() => {}, userNodes:[], addNodeFromLibrary:() => {}, model:null};
  return {
    connected,
    draw: async (changed = null) => {
      if (changed) snapshot = {...snapshot, graph:{...snapshot.graph, nodes:changed}};
      await React.act(async () => root.render(React.createElement(context.NodeCanvas, props)));
      return dom.window.document;
    },
    click: async element => { await React.act(async () => element.click()); },
    close: async () => {
      await React.act(async () => root.unmount());
      dom.window.close(); global.window = oldWindow; global.document = oldDocument;
      delete global.IS_REACT_ACT_ENVIRONMENT;
    },
  };
}

const card = (doc, id) => doc.querySelector('.lm-node[data-node-id="' + id + '"]');
const socket = (doc, id, label) => card(doc, id).querySelector('button[aria-label="' + label + '"]');
function wireEnd(doc) {
  const paths = [...doc.querySelectorAll('svg.lm-wires path[stroke="transparent"]')];
  assert.equal(paths.length, 1, 'the one wire is drawn');
  const match = /^M([-\d.]+),([-\d.]+) C.* ([-\d.]+),([-\d.]+)$/.exec(paths[0].getAttribute('d'));
  assert.ok(match, 'wire path shape: ' + paths[0].getAttribute('d'));
  return {x1:+match[1], y1:+match[2], x2:+match[3], y2:+match[4]};
}

test('sockets sit in a port band below the title and summary, one row per port, on the card edges', async () => {
  const view = await mount();
  try {
    const doc = await view.draw();
    for (const node of nodes) {
      const element = card(doc, node.id);
      assert.ok(element, 'the card is drawn: ' + node.id);
      const band = element.querySelector('[data-port-band]');
      assert.ok(band && band.parentElement === element, 'the card has its own port band: ' + node.id);
      assert.equal(band, element.lastElementChild, 'the band comes after the title bar and body');
      const rows = Math.max(node.ins.length, node.outs.length);
      assert.equal(band.style.height, (PAD * 2 + rows * STEP) + 'px', 'one row per port pair: ' + node.id);
      const sides = [['in', node.ins, 'left'], ['out', node.outs, 'right']];
      for (const [side, ports, edge] of sides) {
        ports.forEach((port, index) => {
          const button = socket(doc, node.id, (side === 'in' ? 'Connect input ' : 'Connect output ') + port.label);
          assert.ok(button, 'the socket is drawn: ' + node.id + ' ' + port.label);
          const holder = button.parentElement;
          assert.ok(holder.parentElement === band, 'the socket lives in the band, never over the content: ' + port.label);
          assert.equal(holder.style.position, 'absolute');
          assert.equal(holder.style.top, (rowCentre(index) - RADIUS - 1) + 'px', 'row ' + index + ' of ' + node.id);
          assert.equal(holder.style[edge], (-RADIUS - 1) + 'px', 'on the ' + edge + ' edge: ' + port.label);
          assert.equal(button.style.width, 2 * RADIUS + 'px');
          assert.equal(button.style.borderRadius, '50%');
        });
      }
    }
  } finally { await view.close(); }
});

test('each wire ends at its row in the band the card reports, and follows the band when the content grows', async () => {
  for (const top of [96, 140]) {
    bandTop = top;
    const view = await mount();
    try {
      const doc = await view.draw();
      assert.deepEqual(wireEnd(doc), {x1:40 + 210, y1:60 + top + rowCentre(0), x2:420, y2:300 + top + rowCentre(1)},
        'output row 0 of work to input row 1 of sink, below a band starting at ' + top + 'px');
    } finally { await view.close(); bandTop = 0; }
  }
});

test('title and summary sit in the card body as drawn, never clamped to one line', async () => {
  const view = await mount();
  try {
    const doc = await view.draw();
    for (const node of nodes) {
      const rows = [...card(doc, node.id).querySelectorAll('div')];
      const title = rows.find(row => row.textContent === node.title && !row.children.length);
      const sub = rows.find(row => row.textContent === node.sub && !row.children.length);
      assert.ok(title && sub, 'the card draws its title and summary: ' + node.id);
      assert.ok(title.parentElement === sub.parentElement, 'title and summary share the body');
      assert.equal(title.parentElement.style.padding, '9px 12px 11px', 'the design body padding');
      assert.equal(title.style.fontSize, '13px');
      assert.equal(sub.style.fontSize, '10px');
      for (const [element, what] of [[title, 'title'], [sub, 'summary']]) {
        assert.notEqual(element.style.whiteSpace, 'nowrap', 'the ' + what + ' of ' + node.id + ' is not clamped');
        assert.equal(element.style.textOverflow, '', 'the ' + what + ' of ' + node.id + ' is not ellipsized');
      }
      assert.equal(title.getAttribute('title'), node.title, 'the full title stays reachable as the tooltip');
    }
  } finally { await view.close(); }
});

test('socket labels keep the design type; a connectable port wires through the transport, an unconnectable one is inert', async () => {
  const view = await mount();
  try {
    const doc = await view.draw();
    const label = socket(doc, 'work', 'Connect input required-capabilities').nextElementSibling;
    assert.equal(label.textContent, 'required-capabilities');
    assert.equal(label.style.fontSize, '8.5px');
    assert.equal(label.style.whiteSpace, 'nowrap');
    assert.equal(label.style.padding, '0px 4px');
    // An input's and an output's label share one row: each is held to half the card, ellipsized, whole in its tooltip.
    assert.ok(parseFloat(label.style.maxWidth) > 0 && parseFloat(label.style.maxWidth) <= 105, 'a label keeps to its half of the card');
    assert.equal(label.style.overflow, 'hidden');
    assert.equal(label.style.textOverflow, 'ellipsis');
    assert.equal(label.getAttribute('title'), 'required-capabilities', 'the whole name stays reachable');
    assert.equal(label.style.opacity, '0.85');
    const policy = socket(doc, 'policy', 'Connect input applicable-policy');
    assert.equal(policy.disabled, true, 'a port the server marks not connectable cannot be used');
    assert.equal(policy.parentElement.style.pointerEvents, 'none', 'and stays inert');
    const output = socket(doc, 'work', 'Connect output result'), input = socket(doc, 'sink', 'Connect input a');
    assert.equal(output.disabled, false);
    assert.equal(output.parentElement.style.pointerEvents, 'auto');
    await view.click(output);
    await view.click(input);
    assert.deepEqual(view.connected, [['work', 'out-result', 'sink', 'in-a']], 'output then input asks the transport to connect them');
  } finally { await view.close(); }
});

test('a wire can start at either end: input then output connects the same way, an incompatible output says so', async () => {
  const view = await mount();
  try {
    const doc = await view.draw();
    await view.click(socket(doc, 'sink', 'Connect input a'));
    assert.match(doc.querySelector('[role="status"]').textContent, /Choose an output for a/);
    await view.click(socket(doc, 'work', 'Connect output result'));
    assert.deepEqual(view.connected, [['work', 'out-result', 'sink', 'in-a']], 'input then output asks the transport for the same wire');
    await view.click(socket(doc, 'sink', 'Connect input b'));
    await view.click(socket(doc, 'work', 'Connect output result'));
    assert.equal(view.connected.length, 1, 'an input the output does not offer is never sent');
    assert.match(doc.querySelector('[role="alert"]').textContent, /This output cannot feed b/);
  } finally { await view.close(); }
});
