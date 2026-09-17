/* Canvas node cards as the founder design bundle draws them (archhub/project/studio-lm.jsx: NodeCanvas wires
   1403-1427, NodeRenderer 1575-1635, Socket 1651-1674): the title and summary sit in the card body as drawn, the
   sockets sit on the card's own edge at fixed offsets from its top (42 + 19 per port index, radius 5), and every wire
   ends at that same offset. The live graph keeps its handles: a connectable port is a button that starts or finishes a
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

// The design's socket geometry (design studio-lm.jsx:1249-1253).
const TOP = 42, STEP = 19, RADIUS = 5;
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

test('sockets sit on the card edge at the design offsets: 42 from the card top, 19 per port index', async () => {
  const view = await mount();
  try {
    const doc = await view.draw();
    for (const node of nodes) {
      const element = card(doc, node.id);
      assert.ok(element, 'the card is drawn: ' + node.id);
      const sides = [['in', node.ins, 'left'], ['out', node.outs, 'right']];
      for (const [side, ports, edge] of sides) {
        ports.forEach((port, index) => {
          const button = socket(doc, node.id, (side === 'in' ? 'Connect input ' : 'Connect output ') + port.label);
          assert.ok(button, 'the socket is drawn: ' + node.id + ' ' + port.label);
          const holder = button.parentElement;
          assert.ok(holder.parentElement === element, 'the socket is pinned to the card itself, not a port band: ' + port.label);
          assert.equal(holder.style.position, 'absolute');
          assert.equal(holder.style.top, (TOP + index * STEP - RADIUS) + 'px', 'row ' + index + ' of ' + node.id);
          assert.equal(holder.style[edge], -RADIUS + 'px', 'on the ' + edge + ' edge: ' + port.label);
          assert.equal(button.style.width, 2 * RADIUS + 'px');
          assert.equal(button.style.borderRadius, '50%');
        });
      }
    }
  } finally { await view.close(); }
});

test('each wire ends at its socket offset, and a longer title moves neither end', async () => {
  const view = await mount();
  try {
    let doc = await view.draw();
    const expected = {x1:40 + 210, y1:60 + TOP, x2:420, y2:300 + TOP + STEP};
    assert.deepEqual(wireEnd(doc), expected, 'the wire leaves output row 0 of work and enters input row 1 of sink');
    doc = await view.draw(nodes.map(node => node.id === 'work' ? {...node, title:node.title + ' and its installer notes'} : node));
    assert.deepEqual(wireEnd(doc), expected, 'the sockets do not follow the title: they sit at fixed offsets as designed');
  } finally { await view.close(); }
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
    assert.equal(label.style.maxWidth, '', 'a label is not capped: the design draws it whole');
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