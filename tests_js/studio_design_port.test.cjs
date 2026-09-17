/* Design port courts: the workspace header, the sidebar account chip, the canvas chrome and the
   canvas composer, measured against the founder design bundle (archhub/project/studio-lm.jsx:
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

async function mountStudio({account = null, workshops = [{root:'room-a', label:'Wall conversion', is_general:false}]} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {}); // court sandbox: the server never answers, so no model is selected
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
  const segmented = segmentedControl(studio);
  studio.flush(() => [...segmented.children].find(child => child.textContent.trim() === 'Canvas').click());
  assert.ok(studio.doc.querySelector('.lm-node[data-node-id="work-a"]'), 'the canvas draws the projected Work node');
};

test('header: the design row ends at save as skill; three-segment switch, New session after the tabs, a model chip that draws only what it holds, unbound actions dashed', async () => {
  const studio = await mountStudio();
  try {
    const segmented = segmentedControl(studio);
    assert.deepEqual([...segmented.children].map(child => child.textContent.trim()), ['Chat', 'Workshop', 'Canvas'],
      'the segmented control holds only Chat, Workshop and Canvas (design studio-lm.jsx:1132-1144)');
    const header = segmented.parentElement;
    assert.equal(header.querySelector('[aria-label="Conversations"]') === null, true,
      'Chat draws the design row: no conversation menu beside the switch (design studio-lm.jsx:1099-1150)');
    assert.equal(header.querySelector('section[aria-label="Application release updates"]') === null, true,
      'no release update controls in the header: Settings > About and the status strip hold them');
    assert.equal(header.lastElementChild.textContent.trim(), 'save as skill', 'save as skill closes the header row as designed');

    const tab = [...header.querySelectorAll('span')].find(span => span.textContent === 'ArchHub');
    assert.ok(tab, 'the open graph tab is drawn from the projected session list');
    const fresh = header.querySelector('button[title="Start a new session from Home"]');
    assert.ok(fresh, 'New session is drawn (design studio-lm.jsx:1123-1129)');
    const strip = tab.parentElement.parentElement;
    assert.equal(fresh.parentElement, strip, 'New session sits in the tab strip');
    assert.ok(tab.parentElement.compareDocumentPosition(fresh) & studio.win.Node.DOCUMENT_POSITION_FOLLOWING, 'after the tabs');

    const chip = [...header.querySelectorAll('button')].find(button => button.textContent.includes('Choose a model'));
    assert.ok(chip, 'the model chip is drawn');
    assert.equal(/ctx\s*(\u00b7|$)/.test(chip.textContent), false, 'no empty ctx field: ' + chip.textContent);
    assert.equal(chip.textContent.includes('\u25cf'), false, 'no latency dot without a measured latency: ' + chip.textContent);
    assert.equal(/\u00b7\s*(\u00b7|\u25be|$)/.test(chip.textContent), false, 'no dangling separator: ' + chip.textContent);
    assert.match(chip.textContent, /No (provider|model) selected/, 'the vendor line keeps what the chip does hold');

    for (const label of ['fork', 'save as skill']) {
      const [button] = studio.buttons(label, header);
      assert.ok(button, label + ' is drawn with its design label (design studio-lm.jsx:1147-1148)');
      assert.equal(button.disabled, true, label + ' has no binding in this build, so it is disabled');
      assert.match(button.title || '', /not available/i, label + ' says why');
      assert.equal(button.style.borderStyle, 'dashed', label + ' is disabled with a dashed border');
      assert.equal(button.style.opacity, '', label + ' is disabled without alpha');
      assert.equal(button.style.backgroundColor, 'transparent', label + ' is not drawn as a filled primary while disabled');
    }

    // The conversation menu is drawn only while a Workshop conversation is open, beside the switch, never inside it.
    const jsx = read('nodelang/studio/studio-lm.jsx');
    const wsHeader = jsx.slice(jsx.indexOf('\nconst WsHeader = '), jsx.indexOf('\nconst WsTab = '));
    assert.match(wsHeader, /workshops\.length > 0 && mode === 'chat' && conversationRoot && \(window\.ARCHHUB_EXISTING_WORKSHOP\?\.refreshConversationCatalog \?\s*<WorkshopConversationMenu/,
      'the Workshop conversation menu is gated on an open Workshop conversation');
    assert.ok(wsHeader.indexOf('<WorkshopConversationMenu') < wsHeader.indexOf('workshopModeSegments('), 'and sits before the switch, outside it');

    studio.flush(() => studio.doc.querySelector('button[title="Start a new session from Home"]').click());
    assert.ok(studio.doc.querySelector('textarea[aria-label="Start a new session"]'), 'New session opens Home, where a session starts');
    assert.equal(studio.buttons('Canvas').filter(button => button.hasAttribute('aria-pressed')).length, 0, 'the workspace header is gone');
  } finally { studio.close(); }

  const empty = await mountStudio({workshops:[]});
  try {
    const workshop = [...segmentedControl(empty).children].find(child => child.textContent.trim() === 'Workshop');
    assert.equal(workshop.disabled, true, 'no room in scope disables Workshop');
    assert.equal(workshop.style.opacity, '', 'the disabled segment carries no alpha');
    assert.match(workshop.style.outline, /dashed/, 'the disabled segment is dashed');
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
  } finally { signed.close(); }
  const out = await mountStudio();
  try {
    const chip = out.doc.querySelector('aside [aria-label="Account"]');
    assert.ok(chip && chip.textContent.includes('Sign in'), 'signed out, the chip is the way in');
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

test('composer: one design row (slash, caret, field, library, Send), no route line, a drawn caret that yields to the real one', async () => {
  const studio = await mountStudio();
  try {
    openCanvas(studio);
    const input = [...studio.doc.querySelectorAll('input')].find(node => (node.placeholder || '').includes('type / to add a node'));
    assert.ok(input, 'the composer field is drawn');
    const composer = input.closest('[data-no-pan]');
    const row = input.parentElement;
    assert.equal(row.parentElement, composer, 'the field sits in the composer row');
    assert.equal(composer.children.length, 1, 'one row and nothing under it (design studio-lm.jsx:2069-2087): ' + composer.children.length + ' children');
    assert.equal([...composer.querySelectorAll('div')].some(node => node.textContent.startsWith(ARROW + ' ')), false, 'no second route line');
    assert.equal([...row.querySelectorAll('span')].some(node => /no model picked/.test(node.textContent)), false,
      'the design row names no route: the header model chip names the model that answers');
    const [library] = studio.buttons('library', row), [send] = studio.buttons('Send \u21b5', row);
    assert.ok(library && send, 'library and Send stay in the row');
    assert.deepEqual([...row.children].map(child => child.tagName.toLowerCase()), ['span', 'span', 'input', 'button', 'button'],
      'slash, caret, field, library, then Send as the rightmost control (design studio-lm.jsx:2069-2087)');
    assert.ok(library.compareDocumentPosition(send) & studio.win.Node.DOCUMENT_POSITION_FOLLOWING, 'library sits before Send');
    const caret = [...row.querySelectorAll('span')].find(node => (node.style.animation || '').includes('lmCaret'));
    assert.ok(caret, 'the drawn caret is there while the field is idle');
    assert.notEqual(caret.style.visibility, 'hidden', 'idle: the drawn caret shows');
    studio.flush(() => input.focus());
    assert.equal(caret.style.visibility, 'hidden', 'focused: the field caret is the only caret');
    studio.flush(() => input.blur());
    assert.notEqual(caret.style.visibility, 'hidden', 'blurred: the drawn caret returns');
  } finally { studio.close(); }
});
