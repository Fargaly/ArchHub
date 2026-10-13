/* Design port courts: the workspace header, the sidebar account chip, the canvas chrome and the
   selection-panel composer, measured against the founder design bundle (archhub/project/studio-lm.jsx:
   WsHeader 1099-1150, NodesPanel footer 644-654, CanvasHint 1504-1517, CanvasToolbar 2042-2061,
   FloatingComposer 2069-2087, MiniMap 2090-2114; DECISIONS.md "Disabled controls use a dashed border,
   never alpha" and "Draw or omit"). The whole compiled Studio is mounted in an in-memory DOM over an
   existing-graph shape: raw canvas rows as the server emits them (a Work node with a long title and
   twelve property ports, an engine node, a second Work node) projected by the shipped
   projectStudioCanvas slice of studio.html, with the transport methods the installed build exposes.
   Everything shown must come from that projection or the account record, never a design seed.
   No application, provider, network or graph file is touched. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));
const ARROW = '\u2192', DOT = '\u00b7';
const WORK_TITLE = 'Claude717 landing: reviewed source patches for the design release';
const PROPERTIES = ['acceptance-criteria', 'blocked-by', 'context', 'dependencies', 'description', 'external-key',
  'inputs', 'outputs', 'plan', 'priority', 'required-capabilities', 'requirements'];
const port = (owner, name, index, side) => ({id:owner + ':rel-' + index, name, side, mode:'connection',
  connectable:true, read_only:false, editable:false, interface_root:'if-' + owner + '-' + index,
  direction:side === 'source' ? 'output' : 'input', multiple:false, selected:false, context:false});
const rawCanvas = {nodes:[
  {id:'work-a', label:WORK_TITLE, x:520, y:40, status:'',
    params:[{label:'priority', value:'high', relation:'rel-priority', editable:true}],
    ports:PROPERTIES.map((name, index) => port('work-a', name, index, 'target'))},
  {id:'sketch-a', label:'Sketch Lines', engine:'vision.sketch_lines', x:40, y:60, status:'10 lines from sample-plan.png',
    params:[{label:'engine', value:'vision.sketch_lines'}, {label:'seed', value:'sketch-lines', relation:'rel-seed', editable:true}],
    ports:[port('sketch-a', 'lines', 0, 'source')]},
  {id:'work-b', label:'Website lane: remove live prices, rebuild the canonical site, export and package it', x:40, y:420,
    params:[], ports:PROPERTIES.slice(0, 5).map((name, index) => port('work-b', name, index, 'target'))},
], wires:[{id:'wire-a', source:'sketch-a', source_interface:'sketch-a:rel-0', target:'work-a',
  target_interface:'work-a:rel-3', params:[]}]};

function projected() {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  assert.ok(specs.length > 100 && fn.length > 100, 'the projection is a slice of the shipped studio.html');
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(rawCanvas) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio({account = null, workshops = [{root:'room-a', label:'Wall conversion', is_general:false}], transcript = null} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {}); // court sandbox: the server never answers, so no model is selected
  if (transcript) win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node, conversation_root:'graph-chat', revision:1, ...transcript});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  if (account) win.localStorage.setItem('archhub.account.v1', JSON.stringify(account));
  const graph = projected();
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a'};
  let snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', authorization}, workshops,
    applicationUpdate:{state:'idle', current_build:'20260916-2130-e733a13'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const notify = () => listeners.forEach(listener => listener());
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    selectTopology:async id => { snapshot = {...snapshot, topology:{...snapshot.topology, selected:id}}; notify(); },
    refreshTopologyCanvas:async () => {},
    refreshConversationCatalog:async () => {},
    watchApplicationUpdate:() => () => {},
    refreshApplicationUpdate:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const buttons = (text, scope = doc) => [...scope.querySelectorAll('button')].filter(button => button.textContent.trim() === text);
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, buttons, close};
}
const px = value => { const n = parseFloat(value); assert.ok(Number.isFinite(n), 'a declared pixel size, got ' + JSON.stringify(value)); return n; };
const segmentedControl = studio => {
  const canvas = studio.buttons('Canvas').find(button => button.hasAttribute('aria-pressed'));
  assert.ok(canvas, 'the header offers the Canvas segment');
  return canvas.parentElement;
};
const openCanvas = studio => {
  assert.ok(studio.doc.querySelector('.lm-node[data-node-id="work-a"]'), 'the canvas draws the projected Work node');
};

test('header: Studio owns session tabs only; Chat, Workshop and System moved out of the header', async () => {
  const studio = await mountStudio();
  try {
    const header = studio.doc.querySelector('main > div');
    assert.ok(header, 'the workspace header exists');
    const exactHeaderButtons = [...header.querySelectorAll('button')].map(button => button.textContent.trim());
    for (const moved of ['Chat', 'Workshop', 'System']) {
      assert.equal(exactHeaderButtons.includes(moved), false, moved + ' is not a Studio session-header tab');
    }
    assert.equal(header.querySelector('[aria-label="Conversations"]') === null, true,
      'conversation picking moved out of the Studio session header');
    // Founder, 2026-09-18: the update icons belong in the header, where he sees them.
    assert.ok(header.querySelector('section[aria-label="Application release updates"]'),
      'the release update icons close the header row');
    assert.equal([...header.querySelectorAll('button')].some(button => button.textContent.trim() === 'save as skill'), false,
      'save as skill is not drawn without a binding');
    assert.equal([...header.querySelectorAll('button')].some(button => button.textContent.trim() === 'fork'), false,
      'fork is not drawn without a binding');

    const tab = [...header.querySelectorAll('span')].find(span => span.textContent === 'ArchHub');
    assert.ok(tab, 'the open graph tab is drawn from the projected session list');
    const fresh = header.querySelector('button[title="New session"]');
    assert.ok(fresh, 'New session is drawn (design studio-lm.jsx:1123-1129)');
    const strip = tab.parentElement.parentElement;
    assert.equal(fresh.parentElement, strip, 'New session sits in the tab strip');
    assert.ok(tab.parentElement.compareDocumentPosition(fresh) & studio.win.Node.DOCUMENT_POSITION_FOLLOWING, 'after the tabs');

    const chip = [...header.querySelectorAll('button')].find(button => button.textContent.includes('Choose a model'));
    assert.equal(chip, undefined, 'the duplicate header model chip is not drawn');

    const jsx = read('nodelang/studio/studio-lm.jsx');
    const wsHeader = jsx.slice(jsx.indexOf('\nconst WsHeader = '), jsx.indexOf('\nconst WsTab = '));
    assert.doesNotMatch(wsHeader, /WorkshopConversationMenu|workshopModeSegments/,
      'the old Chat/Workshop/Canvas switch and conversation menu are not in the header');

    // New session creates the graph in place (CORE-A, founder G2); All sessions is the way back to Home.
    studio.flush(() => studio.doc.querySelector('button[title="All sessions"]').click());
    assert.ok(studio.doc.querySelector('textarea[aria-label="Start a new session"]'), 'All sessions opens Home, where a session starts');
    assert.equal(studio.buttons('Canvas').filter(button => button.hasAttribute('aria-pressed')).length, 0, 'the workspace header is gone');
  } finally { studio.close(); }

  const empty = await mountStudio({workshops:[]});
  try {
    assert.equal([...empty.doc.querySelectorAll('main > div button')].some(button => button.textContent.trim() === 'Workshop'), false,
      'a missing Workshop is not represented by a disabled Studio header segment');
  } finally { empty.close(); }
});

test('sidebar account chip reads the account record, never a seeded person', async () => {
  const signed = await mountStudio({account:{signedIn:true, email:'ana@studio.example', name:'', graphTier:'founder'}});
  try {
    const chip = signed.doc.querySelector('aside [aria-label="Account"]');
    assert.ok(chip, 'the Nodes panel footer is the account chip');
    assert.ok(chip.textContent.includes('ana'), 'the name comes from the signed-in email: ' + chip.textContent);
    assert.ok(chip.textContent.includes('FOUNDER'), 'the tier comes from the account record: ' + chip.textContent);
    for (const seeded of ['Fargaly', 'BYO ' + DOT + ' CLOUD']) {
      assert.equal(signed.doc.body.textContent.includes(seeded), false, 'no seeded ' + seeded + ' on screen');
    }
    signed.flush(() => chip.click());
    assert.ok([...signed.doc.querySelectorAll('span')].some(span => span.textContent === 'Settings'), 'the chip opens Settings on Account');
    assert.equal(signed.doc.querySelectorAll('[data-tool-card]').length, 0, 'the chip lands on Account, not the Hub');
    signed.flush(() => [...signed.doc.querySelectorAll('button')].find(button => button.textContent.trim() === '✕').click());
    signed.flush(() => signed.doc.querySelector('[title="Settings"]').click());
    assert.equal(signed.doc.querySelectorAll('[data-tool-card]').length, 6, 'after an Account visit, the rail Settings opens on the Hub again');
  } finally { signed.close(); }
  const out = await mountStudio();
  try {
    const chip = out.doc.querySelector('aside [aria-label="Account"]');
    assert.ok(chip && chip.textContent.includes('Sign in'), 'signed out, the chip is the way in');
    out.flush(() => chip.click());
    assert.ok([...out.doc.querySelectorAll('span')].some(span => span.textContent === 'Settings'), 'signed out, the chip opens Settings');
    assert.equal(out.doc.querySelectorAll('[data-tool-card]').length, 0, 'signed out, the chip lands on Account to sign in, not the Hub');
    assert.equal(out.doc.body.textContent.includes('Fargaly'), false, 'no seeded person when signed out');
  } finally { out.close(); }
});

test('canvas chrome: no status chip idle or selected, the minimap at its design place, the toolbar and hint carry the design labels', async () => {
  const studio = await mountStudio();
  try {
    openCanvas(studio);
    const mapLabel = [...studio.doc.querySelectorAll('div')].find(node => node.textContent === 'MAP' && !node.children.length);
    assert.ok(mapLabel, 'the minimap is drawn');
    const map = mapLabel.parentElement;
    assert.equal([...studio.doc.querySelectorAll('[role="status"]')].some(node => node.textContent === 'Canvas'), false,
      'an idle canvas draws no status chip (design studio-lm.jsx NodeCanvas draws none)');
    const node = studio.doc.querySelector('.lm-node');
    assert.ok(node, 'a node card is drawn');
    studio.flush(() => node.click());
    assert.equal([...studio.doc.querySelectorAll('[role="status"]')].some(row => /selected$/.test(row.textContent.trim())), false,
      'a selection draws no status chip: the design canvas draws none, the card carries its own focus');
    assert.deepEqual(['right', 'top', 'width', 'height'].map(key => px(map.style[key])), [14, 14, 170, 96],
      'the minimap sits where the design puts it (design studio-lm.jsx:2090-2114)');
    const add = studio.doc.querySelector('button[aria-label="Add node"]');
    assert.ok(add, 'the toolbar add action exists');
    assert.equal(add.textContent.trim(), '\uff0b add node', 'the toolbar names its add action (design studio-lm.jsx:2055-2059)');
    const first = [...studio.doc.querySelectorAll('span')].find(node => node.textContent === 'scroll ' + ARROW + ' zoom');
    assert.ok(first, 'the hint strip is drawn');
    assert.deepEqual([...first.parentElement.children].map(node => node.textContent),
      ['scroll ' + ARROW + ' zoom', DOT, 'drag ' + ARROW + ' pan', DOT, 'right-click ' + ARROW + ' menu'],
      'the hint strip carries exactly the design affordances (design studio-lm.jsx:1504-1517)');
  } finally { studio.close(); }
});

test('C1: the canvas bottom / box adds nodes and opens the library only; it is not a chat', async () => {
  const studio = await mountStudio();
  try {
    openCanvas(studio);
    const box = studio.doc.querySelector('[data-canvas-add]');
    assert.ok(box, 'the canvas draws the bottom add-node box');
    const field = box.querySelector('input[aria-label="Add a node"]');
    assert.ok(field, 'the box has one add-node field');
    assert.equal(box.querySelector('[data-model-indicator]'), null, 'no model in the box');
    assert.deepEqual([...box.querySelectorAll('button')].map(b => b.textContent.trim()), ['library'], 'its only button is library');
    assert.equal(studio.doc.querySelectorAll('input[aria-label="Ask selection"]').length, 1, 'still exactly one chat input');
    const sent = [];
    studio.win.fetch = (url, init) => { sent.push([String(url), init && init.method]); return new Promise(() => {}); };
    const setValue = Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set;
    studio.flush(() => { setValue.call(field, '/wall'); field.dispatchEvent(new studio.win.Event('input', {bubbles:true})); });
    studio.flush(() => field.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true, cancelable:true})));
    const search = [...studio.doc.querySelectorAll('input')].find(input => /Search… \(e\.g\./.test(input.placeholder));
    assert.ok(search, 'Enter opens the Node library');
    assert.equal(search.value, 'wall', 'the library opens on what was typed, without the slash');
    assert.deepEqual(sent.filter(([, method]) => method && method !== 'GET'), [], 'the box sends nothing');
    const close = [...studio.doc.querySelectorAll('button')].find(button => button.textContent === '✕' && button.closest('[style*="grid-template-columns: 180px"]'));
    if (close) studio.flush(() => close.click());
    studio.flush(() => box.querySelector('button').click());
    assert.ok([...studio.doc.querySelectorAll('span')].some(node => node.textContent === 'Node library'), 'library opens the Node library');
  } finally { studio.close(); }
});

// Ping E1 review: an empty chat has ONE destination — the composer right below — and no Workshop link.
test('E1: an empty graph chat says ask below, offers no Workshop link, and the composer below is usable', async () => {
  const studio = await mountStudio({transcript:{rows:[], has_older:false, next_before:null}});
  try {
    openCanvas(studio);
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    const chatTab = [...panel.querySelectorAll('[role="tab"]')].find(tab => tab.textContent.trim() === 'Chat');
    if (chatTab && chatTab.getAttribute('aria-selected') !== 'true') studio.flush(() => chatTab.click());
    for (let i = 0; i < 20 && !/ask below to start one/.test(panel.textContent); i += 1) {
      await new Promise(resolve => studio.win.setTimeout(resolve, 10)); studio.flush(() => {});
    }
    assert.match(panel.textContent, /No conversation yet · ask below to start one\./, 'the empty state starts the chat here');
    assert.equal([...panel.querySelectorAll('button')].some(button => /workshop/i.test(button.textContent)), false,
      'no Continue / Workshop button competes with the composer');
    const input = panel.querySelector('input[aria-label="Ask selection"]');
    assert.ok(input && !input.disabled && !input.readOnly, 'the composer right below is present and usable');
  } finally { studio.close(); }
});

test('D-FIX1: the right panel is one 320px column; long chips and rows cannot push it past the window edge', async () => {
  const studio = await mountStudio();
  try {
    openCanvas(studio);
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel, 'the selection inspector is mounted');
    assert.equal(panel.style.gridTemplateColumns, 'minmax(0, 1fr)', 'one column that can shrink to the track');
    assert.equal(panel.style.minWidth, '0px', 'the panel itself may shrink');
    const main = panel.parentElement;
    assert.equal(main.style.gridTemplateColumns, 'minmax(0, 1fr) 320px', 'the canvas track shrinks; the panel track is 320px');
    const chip = panel.querySelector('[data-model-indicator]');
    assert.ok(chip && chip.style.maxWidth === '100%' && chip.style.minWidth === '0px', 'the model chip ellipsizes inside the panel');
    assert.ok(chip.getAttribute('title'), 'the full chip text stays readable on hover');
    assert.equal(panel.firstElementChild.style.overflowX, 'hidden', 'nothing scrolls sideways inside the panel');
  } finally { studio.close(); }
});

test('composer: the one Studio ask field is scoped in the right selection panel', async () => {
  const studio = await mountStudio();
  try {
    openCanvas(studio);
    const inputs = [...studio.doc.querySelectorAll('input[aria-label="Ask selection"]')];
    assert.equal(inputs.length, 1, 'there is exactly one Studio ask/reply/message input');
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel && panel.contains(inputs[0]), 'the composer lives in the right selection panel');
    assert.match(inputs[0].placeholder, /whole graph|ask about this node|reply in this session/i);
    const chip = panel.querySelector('[data-model-indicator]');
    assert.ok(chip, 'the scope chip reuses the model indicator marker');
    assert.match(chip.textContent, /ArchHub|graph|Claude717|openrouter|Choose a model/i);
    assert.equal(studio.doc.querySelectorAll('[data-no-pan] input[aria-label="Ask selection"]').length, 0,
      'the old floating canvas composer is not drawn');
  } finally { studio.close(); }
});
