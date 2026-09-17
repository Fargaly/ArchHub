/* Canvas node cards: port rows sit below the title block, every wire ends on the socket that is drawn, and the card keeps
   its type budget: one-line title and summary, socket labels capped to their row's real gap with 0 overlaps. */
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

const STEP = 19, RADIUS = 5, CARD_BORDER_TOP = 2;
// The card from the founder window (2026-09-17): a Work title that wraps over eleven input ports and a "Graph node" summary.
const workPorts = ['dependencies', 'description', 'external-key', 'inputs', 'outputs', 'plan', 'priority',
  'required-capabilities', 'requirements', 'scope', 'title'];
const nodes = [
  {id:'work', cat:'logic', live:true, x:40, y:60, w:210, h:110,
    title:'Claude717 landing: reviewed source patches for the design release', sub:'Graph node', params:[],
    ins:workPorts.map(name => ({id:'in-' + name, label:name, t:'any', connectable:true})),
    outs:[{id:'out-result', label:'result', t:'any', connectable:true}]},
  {id:'sink', cat:'read', live:true, x:420, y:300, w:210, h:110, title:'Sketch Lines', sub:'vision.sketch_lines',
    params:[], ins:[{id:'in-a', label:'a', t:'any', connectable:true}, {id:'in-b', label:'b', t:'any', connectable:true}],
    outs:[]},
];
const wires = [{id:'wire-1', from:['work', 'out-result'], to:['sink', 'in-b']}];

// jsdom performs no layout. `layout` is what a browser measures for each card: the offset of the in-flow block
// that holds its sockets, below a title block of whatever height the title wrapped to.
async function mount(layout) {
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
  // The CSS box model for the two element kinds the card uses: a positioned element sits at its `top`;
  // the in-flow card child holding the sockets sits where the browser measured it (layout[card]).
  Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetTop', {configurable:true, get() {
    if (this.style.position === 'absolute') return parseFloat(this.style.top) || 0;
    const card = this.closest('.lm-node');
    return card && this.parentElement === card && this.querySelector('button[aria-label^="Connect "]')
      ? layout[card.getAttribute('data-node-id')] : 0;
  }});
  Object.defineProperty(dom.window.HTMLElement.prototype, 'clientTop', {configurable:true, get() {
    return this.classList.contains('lm-node') ? CARD_BORDER_TOP : 0;
  }});
  let snapshot = {graph:{nodes, wires}, canvas:{revision:3, scope:{current:'scope'}}};
  const context = vm.createContext({React, LM, window:dom.window, document:dom.window.document,
    useStudioProjection:() => snapshot, LM_GRAPH:{nodes:[], wires:[]}, studioCanvasScope:() => 'scope',
    studioCategory:cat => ({col:'token-cat', icon:'+', label:String(cat).toUpperCase()}), WIRE:{},
    NodeBody:() => null, CanvasToolbar:() => null, FloatingComposer:() => null, MiniMap:() => null,
    nodeModelRow:() => null, smallBtn:() => ({}), toolBtn:() => ({})});
  vm.runInContext(transformSync(source.slice(start, end) + '\n' + source.slice(socketStart, socketEnd) +
    '\nglobalThis.NodeCanvas = NodeCanvas;', {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(dom.window.document.getElementById('root'));
  const props = {focusId:null, setFocusId:() => {}, setLibraryOpen:() => {}, userNodes:[], addNodeFromLibrary:() => {}, model:null};
  return {
    draw: async (changed = null) => {
      if (changed) snapshot = {...snapshot, graph:{...snapshot.graph, nodes:changed}};
      await React.act(async () => root.render(React.createElement(context.NodeCanvas, props)));
      return dom.window.document;
    },
    close: async () => {
      await React.act(async () => root.unmount());
      dom.window.close(); global.window = oldWindow; global.document = oldDocument;
      delete global.IS_REACT_ACT_ENVIRONMENT;
    },
  };
}

const card = (doc, id) => doc.querySelector('.lm-node[data-node-id="' + id + '"]');
const socket = (doc, id, label) => card(doc, id).querySelector('button[aria-label="' + label + '"]');
// Socket centre in canvas space from the box chain a browser uses: card top and top border, each in-flow
// container between the card and the socket, the socket row offset inside its container, then its radius.
function drawnSocketCentre(doc, id, button) {
  const element = card(doc, id), holder = button.parentElement;
  let offset = 0;
  for (let container = holder.parentElement; container !== element; container = container.parentElement) {
    assert.notEqual(container.style.position, 'absolute', 'a socket container left the card flow');
    offset += container.offsetTop;
  }
  return element.offsetTop + element.clientTop + offset + holder.offsetTop + RADIUS;
}
function wireEnd(doc) {
  const paths = [...doc.querySelectorAll('svg.lm-wires path[stroke="transparent"]')];
  assert.equal(paths.length, 1, 'the one wire is drawn');
  const match = /^M([-\d.]+),([-\d.]+) C.* ([-\d.]+),([-\d.]+)$/.exec(paths[0].getAttribute('d'));
  assert.ok(match, 'wire path shape: ' + paths[0].getAttribute('d'));
  return {y1:+match[2], y2:+match[4]};
}

test('port rows sit after the title in normal flow, one reserved row per port index', async () => {
  const view = await mount({work:92, sink:52});
  try {
    const doc = await view.draw();
    for (const node of nodes) {
      const element = card(doc, node.id);
      const title = [...element.querySelectorAll('div')].find(row => row.textContent === node.title);
      assert.ok(title, 'the card draws its title: ' + node.id);
      const buttons = [...element.querySelectorAll('button[aria-label^="Connect "]')];
      assert.equal(buttons.length, node.ins.length + node.outs.length);
      const band = buttons[0].parentElement.parentElement;
      assert.notEqual(band, element,
        'sockets are pinned over the whole card at fixed offsets, so a wrapped title draws over them: ' + node.id);
      assert.equal(band.parentElement, element);
      assert.notEqual(band.style.position, 'absolute');
      assert.ok(buttons.every(button => button.parentElement.parentElement === band), 'every socket shares the band');
      assert.ok(!band.contains(title) && (title.compareDocumentPosition(band) & doc.defaultView.Node.DOCUMENT_POSITION_FOLLOWING),
        'the port band follows the title block, so a wrapped title pushes it down: ' + node.id);
      assert.equal(band.style.height, Math.max(node.ins.length, node.outs.length) * STEP + 'px',
        'the band reserves a row for every port index: ' + node.id);
    }
  } finally { await view.close(); }
});

test('each wire ends on the drawn socket centre, and moves with the ports when the title re-wraps', async () => {
  const layout = {work:92, sink:52};
  const view = await mount(layout);
  try {
    let doc = await view.draw();
    const before = wireEnd(doc);
    // One more wrapped line (16px): the card re-measures, and the socket and its wire move down together.
    layout.work = 108;
    doc = await view.draw(nodes.map(node => node.id === 'work' ? {...node, title:node.title + ' and its installer notes'} : node));
    const after = wireEnd(doc);
    assert.equal(after.y1 - before.y1, 16, 'the wire follows the port rows down when the title wraps to another line');
    assert.equal(after.y2, before.y2, 'the other card did not change');
    assert.equal(after.y1, drawnSocketCentre(doc, 'work', socket(doc, 'work', 'Connect output result')),
      'the wire leaves the drawn output socket');
    assert.equal(after.y2, drawnSocketCentre(doc, 'sink', socket(doc, 'sink', 'Connect input b')),
      'the wire enters the drawn input socket');
    assert.deepEqual(after, {y1:60 + CARD_BORDER_TOP + 108 + STEP / 2, y2:300 + CARD_BORDER_TOP + 52 + STEP / 2 + STEP});
  } finally { await view.close(); }
});
// Design DECISIONS.md "Card type is a budget" and "The label rule": nothing on a card asks for more room than the
// card has. A long name is shortened with an ellipsis and keeps its full text as a tooltip, never wrapped or shrunk.
const oneLine = (element, what) => {
  assert.equal(element.style.whiteSpace, 'nowrap', what + ' stays on one line');
  assert.equal(element.style.overflow, 'hidden', what + ' is clipped to its box');
  assert.equal(element.style.textOverflow, 'ellipsis', what + ' is shortened with an ellipsis');
};

// A Governed Work card (cell_domain_catalog.py): twelve target ports, a title that needs two lines at the card
// width, two evidence outputs sharing rows 0 and 1, and a policy port the server marks connectable:false.
const targets = ['dependencies', 'description', 'external-key', 'inputs', 'outputs', 'plan', 'priority',
  'required-capabilities', 'requirements', 'scope', 'title', 'applicable-policy'];
const governed = {id:'governed', cat:'logic', live:true, x:40, y:420, w:210, h:282,
  title:'Governed Work: card budget for the node canvas', sub:'Graph node', params:[],
  ins:targets.map(name => ({id:'in-' + name, label:name, t:'any', connectable:name !== 'applicable-policy'})),
  outs:['artifact-proof', 'independent-court-receipt'].map(name => ({id:'out-' + name, label:name, t:'any', connectable:true}))};
const cards = [...nodes, governed];

test('title and summary take one line each; the full text stays as the tooltip', async () => {
  const view = await mount({work:92, sink:52, governed:92});
  try {
    const doc = await view.draw(cards);
    for (const node of cards) {
      const rows = [...card(doc, node.id).querySelectorAll('div')];
      const title = rows.find(row => row.textContent === node.title && !row.children.length);
      const sub = rows.find(row => row.textContent === node.sub && !row.children.length);
      assert.ok(title && sub, 'the card draws its title and summary: ' + node.id);
      oneLine(title, 'the title of ' + node.id);
      oneLine(sub, 'the summary of ' + node.id);
      assert.equal(title.getAttribute('title'), node.title, 'the full title is the tooltip: ' + node.id);
      assert.equal(sub.getAttribute('title'), node.sub, 'the full summary is the tooltip: ' + node.id);
    }
  } finally { await view.close(); }
});

// The layout arithmetic a browser does for each card, from the styles the card draws: a mono character advances
// 0.6em plus its letter spacing, an Inter character about 0.55em; a one-line box is clipped to its max width.
const px = value => parseFloat(value) || 0;
const em = (value, size) => String(value || '').endsWith('em') ? px(value) * size : px(value);
const padX = element => { const parts = String(element.style.padding).split(' '); return px(parts[1] ?? parts[0]); };
const monoWidth = element => {
  const size = px(element.style.fontSize);
  return element.textContent.length * (0.6 * size + em(element.style.letterSpacing, size)) + 2 * padX(element);
};
const hit = (a, b) => a.left < b.right - 0.01 && b.left < a.right - 0.01 && a.top < b.bottom - 0.01 && b.top < a.bottom - 0.01;
const clipped = element => element.style.whiteSpace === 'nowrap' && element.style.overflow === 'hidden';
const HEADER = 7 + 14 + 7 + 1; // title bar: top padding, 14px icon row, bottom padding, hairline

function cardLayout(doc, node) {
  const element = card(doc, node.id);
  const inner = px(element.style.width) - px(element.style.borderLeftWidth) - px(element.style.borderRightWidth);
  const buttons = [...element.querySelectorAll('button[aria-label^="Connect "]')];
  const band = buttons[0].parentElement.parentElement;
  const head = band.previousElementSibling;
  const [title, sub] = [...head.children];
  const [padTop, padSide] = String(head.style.padding).split(' ').map(px);
  const content = inner - 2 * padSide;
  const titleSize = px(title.style.fontSize), titleNatural = title.textContent.length * 0.55 * titleSize;
  const titleLines = clipped(title) ? 1 : Math.ceil(titleNatural / content);
  let y = HEADER + padTop;
  const texts = [{name:'title', left:padSide, right:padSide + Math.min(titleNatural, content), top:y,
    bottom:y += titleLines * titleSize * px(title.style.lineHeight)}];
  y += px(title.style.marginBottom);
  texts.push({name:'sub', left:padSide, right:padSide + Math.min(monoWidth(sub), content), top:y, bottom:y += px(sub.style.fontSize) * 1.2});
  const bandTop = y + px(band.style.marginTop);
  const labels = buttons.map(button => {
    const holder = button.parentElement, label = button.nextElementSibling;
    const side = button.getAttribute('aria-label').startsWith('Connect input ') ? 'in' : 'out';
    const row = Math.round((px(holder.style.top) + RADIUS - STEP / 2) / STEP);
    const edge = px(side === 'in' ? holder.style.left : holder.style.right);
    const lead = edge + px(button.style.width) + px(holder.style.gap);
    const natural = monoWidth(label), cap = label.style.maxWidth ? px(label.style.maxWidth) : Infinity;
    const used = clipped(label) ? Math.min(natural, cap) : natural;
    const centre = bandTop + row * STEP + STEP / 2, half = px(label.style.fontSize) * 0.6;
    const span = (from, width) => side === 'in' ? {left:from, right:from + width} : {left:inner - from - width, right:inner - from};
    return {name:button.getAttribute('aria-label'), port:button.getAttribute('aria-label').replace(/^Connect (input|output) /, ''),
      side, row, lead, button, holder, label, natural, used,
      box:{...span(lead, used), top:centre - half, bottom:centre + half},
      full:{...span(lead, natural), top:centre - half, bottom:centre + half},
      socket:{...span(edge, px(button.style.width)), top:centre - RADIUS, bottom:centre + RADIUS}};
  });
  return {inner, titleNatural, content, texts, labels};
}

test('layout arithmetic: a twelve-port card with a two-line title draws every row of labels with 0 overlaps', async () => {
  const view = await mount({work:92, sink:52, governed:92});
  try {
    const doc = await view.draw(cards);
    const {titleNatural, content, labels:ports} = cardLayout(doc, governed);
    assert.equal(Math.ceil(titleNatural / content), 2, 'the court card has a title that needs two lines at its width');
    assert.equal(ports.filter(row => row.side === 'in').length, 12, 'the court card has twelve target ports');
    // 0 overlaps: no label meets the title or summary, a label or socket of the other column, or the card edge.
    const overlaps = [];
    for (const node of cards) {
      const {inner, texts, labels} = cardLayout(doc, node);
      for (const a of labels) {
        for (const text of texts) if (hit(a.box, text)) overlaps.push(node.id + ': ' + a.name + ' x ' + text.name);
        if (a.box.left < -0.01 || a.box.right > inner + 0.01) overlaps.push(node.id + ': ' + a.name + ' x card edge');
        for (const b of labels) {
          if (b.side === a.side) continue;
          if (a.side === 'in' && hit(a.box, b.box)) overlaps.push(node.id + ': ' + a.name + ' x ' + b.name + ' (' + a.used.toFixed(1) + '+' + b.used.toFixed(1) + ' in ' + inner + ')');
          if (hit(a.box, b.socket)) overlaps.push(node.id + ': ' + a.name + ' x socket of ' + b.name);
        }
      }
    }
    assert.deepEqual(overlaps, [], 'overlapping boxes in the card layout');
    for (const node of cards) {
      const {inner, labels} = cardLayout(doc, node);
      for (const a of labels) {
        // Capped to the real gap, not a fixed ceiling: a label is shortened only where its full width would meet
        // something, and on a shared row it keeps at least half of the gap between the two sockets.
        const b = labels.find(other => other.side !== a.side && other.row === a.row);
        if (a.used < a.natural - 0.01) {
          const meets = a.full.left < -0.01 || a.full.right > inner + 0.01 || Boolean(b && (hit(a.full, b.box) || hit(a.full, b.socket)));
          assert.ok(meets, node.id + ': ' + a.name + ' is shortened to ' + a.used.toFixed(1) + ' of ' + a.natural.toFixed(1) + ' although its row has room');
          if (b) assert.ok(a.used >= Math.min(a.natural, (inner - a.lead - b.lead) / 2) - 1, node.id + ': ' + a.name + ' keeps half its row gap');
        }
        oneLine(a.label, node.id + ' label ' + a.port);
        assert.equal(a.button.style.flexShrink, '0', 'the socket never shrinks for a long label: ' + a.port);
        // The full name is reachable on hover even where the port cannot be connected.
        assert.equal(a.label.getAttribute('title'), a.port, 'a shortened label keeps its full name as the tooltip: ' + a.port);
        assert.equal(a.label.style.pointerEvents, 'auto', 'the label takes hover for its tooltip: ' + a.port);
      }
    }
    const policy = cardLayout(doc, governed).labels.find(row => row.port === 'applicable-policy');
    assert.equal(policy.holder.style.pointerEvents, 'none', 'the non-connectable port stays inert');
    assert.equal(policy.button.disabled, true, 'the non-connectable socket cannot be used');
  } finally { await view.close(); }
});
