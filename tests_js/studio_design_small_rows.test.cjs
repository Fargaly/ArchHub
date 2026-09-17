/* Design gap small rows (design-gap-table.md rows 1, 4, 11 and 15), measured on the whole compiled
   Studio mounted in an in-memory DOM over an existing-graph shape: raw canvas rows as the server
   emits them, projected by the shipped projectStudioCanvas slice of studio.html, with the transport
   methods the installed build exposes. Design rules: DECISIONS.md "Disabled controls use a dashed
   border, never alpha" and "Draw or omit"; a control with no action is not drawn.
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
const DOT = '\u00b7';
const PROPERTIES = ['acceptance-criteria', 'blocked-by', 'context', 'dependencies', 'description', 'external-key'];
const port = (owner, name, index, side) => ({id:owner + ':rel-' + index, name, side, mode:'connection',
  connectable:true, read_only:false, editable:false, interface_root:'if-' + owner + '-' + index,
  direction:side === 'source' ? 'output' : 'input', multiple:false, selected:false, context:false});
// An existing graph laid out by its owner: one node far past the old fixed 2400 x 1400 map, one left of and above the origin.
const existingCanvas = {nodes:[
  {id:'work-a', label:'Claude717 landing: reviewed source patches for the design release', x:520, y:40, status:'',
    params:[{label:'priority', value:'high', relation:'rel-priority', editable:true}],
    ports:PROPERTIES.map((name, index) => port('work-a', name, index, 'target'))},
  {id:'sketch-a', label:'Sketch Lines', engine:'vision.sketch_lines', x:-640, y:-180, status:'10 lines from sample-plan.png',
    params:[{label:'engine', value:'vision.sketch_lines'}], ports:[port('sketch-a', 'lines', 0, 'source')]},
  {id:'work-far', label:'Website lane: remove live prices, rebuild the canonical site', x:5200, y:3100,
    params:[], ports:PROPERTIES.slice(0, 3).map((name, index) => port('work-far', name, index, 'target'))},
], wires:[{id:'wire-a', source:'sketch-a', source_interface:'sketch-a:rel-0', target:'work-a',
  target_interface:'work-a:rel-3', params:[]}]};
const compactCanvas = {nodes:existingCanvas.nodes.map((node, index) => ({...node, x:40 + index * 260, y:60 + index * 30})),
  wires:existingCanvas.wires};

function projected(rawCanvas) {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  assert.ok(specs.length > 100 && fn.length > 100, 'the projection is a slice of the shipped studio.html');
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(rawCanvas) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio({rawCanvas = existingCanvas, update = {state:'idle', current_build:'20260916-2130-e733a13'},
  pending = '', answer = null, prepare = () => {}} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-suite.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, 'Studio build is stale for ' + source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  // Court sandbox: only the routes a case answers resolve; every other request stays pending.
  win.fetch = url => answer && answer[String(url)] ? Promise.resolve({ok:true, status:200,
    json:async () => JSON.parse(JSON.stringify(answer[String(url)]))}) : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const graph = projected(rawCanvas);
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a'};
  let snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', authorization},
    workshops:[{root:'room-a', label:'Wall conversion', is_general:false}],
    applicationUpdate:update, applicationUpdatePending:pending,
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
    applicationUpdateAction:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  prepare(win);
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const doc = win.document;
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = async (done, what) => {
    for (let tick = 0; tick < 200 && !done(); tick += 1) await new Promise(resolve => win.setTimeout(resolve, 5));
    assert.ok(done(), what);
  };
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const change = patch => flush(() => { snapshot = {...snapshot, ...patch}; notify(); });
  return {win, doc, flush, settle, close, change};
}
const reactProps = element => element[Object.keys(element).find(key => key.startsWith('__reactProps'))] || {};
const openCanvas = studio => {
  const canvas = [...studio.doc.querySelectorAll('button[aria-pressed]')].find(button => button.textContent.trim() === 'Canvas');
  assert.ok(canvas, 'the header offers the Canvas segment');
  studio.flush(() => canvas.click());
  assert.ok(studio.doc.querySelector('.lm-node[data-node-id="work-a"]'), 'the canvas draws the projected Work node');
};
const serverStrip = studio => {
  const server = [...studio.doc.querySelectorAll('button')].find(button => button.textContent.includes('server :53912'));
  assert.ok(server, 'the status bar is drawn');
  return server.parentElement;
};
const assertDisabledStyle = (button, label) => {
  assert.equal(button.disabled, true, label + ' is disabled');
  assert.equal(button.style.opacity, '', label + ' is disabled without alpha (got opacity ' + button.style.opacity + ')');
  assert.equal(button.style.borderStyle, 'dashed', label + ' is disabled with a dashed border');
  assert.ok((button.title || '').trim().length > 0, label + ' carries a title');
  assert.notEqual(button.title, button.getAttribute('aria-label'), label + ' says why it is disabled, not only its name: ' + button.title);
};

test('status bar: the design strip with live values; the model slot is the picked model slug, absent while nothing is picked', async () => {
  const unpicked = await mountStudio();
  try {
    const strip = serverStrip(unpicked);
    assert.equal(/choose[- ]a[- ]model/i.test(strip.textContent), false, 'no placeholder slug in the status bar: ' + strip.textContent);
    assert.ok(strip.textContent.includes('Graph composition'), 'the open session file is still named');
    assert.equal(/sign in|@/i.test(strip.textContent), false, 'no account item: the account chip and Settings hold the account');
    assert.ok(strip.textContent.trim().endsWith('20260916-2130-e733a13'),
      'the running build closes the strip where the design names its version (design studio-lm.jsx:3625): ' + strip.textContent);
    assert.match(strip.textContent, /server :53912 \u00b7 0\/0 hosts/, 'server port and live/total hosts in the design format');
    const kinds = [...strip.children].map(child => child.tagName === 'SPAN' && child.textContent.trim() === DOT ? 'sep' :
      child.tagName === 'DIV' && !child.textContent ? 'spacer' : 'item');
    assert.equal(kinds.join(' ').includes('sep sep'), false, 'no doubled separator: ' + kinds.join(' '));
    assert.equal(kinds.join(' ').includes('sep spacer'), false, 'no dangling separator before the spacer: ' + kinds.join(' '));
  } finally { unpicked.close(); }

  const name = 'Anthropic: Claude Sonnet 4.5', route = 'openrouter/anthropic/claude-sonnet-4.5';
  const picked = await mountStudio({answer:{'/api/universal/models':{ok:true, count:1, selected_route:route,
    groups:[{name:'BYO ' + DOT + ' OpenRouter', items:[{name, route:'anthropic/claude-sonnet-4.5', routed:route,
      vendor:'anthropic', tag:'BYO', col:'#3a6acc'}]}]}}});
  try {
    const chip = () => [...picked.doc.querySelectorAll('button')].find(button => button.textContent.includes(name) &&
      !serverStrip(picked).contains(button));
    await picked.settle(() => !!chip(), 'the saved model selection reaches the header model chip');
    const strip = serverStrip(picked);
    assert.ok(strip.textContent.includes(name.toLowerCase().replace(/\s+/g, '-')),
      'the status bar names the picked model as the design slug of its catalogue name: ' + strip.textContent);
    assert.equal(/choose[- ]a[- ]model/i.test(strip.textContent), false, 'no placeholder beside the picked model');
  } finally { picked.close(); }
});

test('icon rail: the design icons in order; Share has no action in this build, so it is disabled and says so', async () => {
  const studio = await mountStudio();
  try {
    const rail = studio.doc.querySelector('aside').firstElementChild;
    const buttons = [...rail.querySelectorAll('button')];
    assert.deepEqual(buttons.map(button => button.title.split(' \u00b7 ')[0]),
      ['Home', 'Chats', 'Nodes', 'Skills', 'Search', 'Share', 'Documentation', 'Settings'], 'the design rail (design studio-lm.jsx:454-494)');
    const dead = buttons.filter(button => !button.disabled && typeof reactProps(button).onClick !== 'function').map(button => button.title);
    assert.deepEqual(dead, [], 'enabled rail controls with no action: ' + dead.join(', '));
    const share = buttons.find(button => button.title.startsWith('Share'));
    assert.equal(share.disabled, true, 'Share is disabled');
    assert.match(share.title, /not available/i, 'Share says why');
    assert.equal(share.style.opacity, '', 'Share is disabled without alpha');
  } finally { studio.close(); }
});

test('canvas menu: the design rows in order with their shortcuts; rows without an action are dashed and say why; a node menu holds selection', async () => {
  const studio = await mountStudio();
  try {
    openCanvas(studio);
    const region = studio.doc.querySelector('[aria-label="Workflow canvas"]');
    const open = () => studio.flush(() => region.dispatchEvent(new studio.win.MouseEvent('contextmenu', {bubbles:true, cancelable:true, clientX:120, clientY:120})));
    open();
    let menu = studio.doc.querySelector('[role="menu"][aria-label="Canvas actions"]');
    assert.ok(menu, 'right-click opens the canvas menu');
    assert.deepEqual([...menu.children].map(child => child.tagName === 'BUTTON' ? child.children[1].textContent : '-'),
      ['Add node\u2026', 'Paste', '-', 'Fit graph to view', 'Zoom to 100%', '-', 'Snap to grid', 'Auto-layout', '-', 'Reset positions', 'Clear all nodes'],
      'the design rows (design studio-lm.jsx:1526-1537)');
    assert.deepEqual([...menu.querySelectorAll('kbd')].map(key => key.textContent),
      ['\u2318L', '\u2318V', '\u23180', '\u23181', '\u2318\u21e7L', '\u2318\u21e7R'], 'the design shortcuts');
    const items = [...menu.querySelectorAll('button[role^="menuitem"]')];
    const disabled = items.filter(item => item.disabled);
    for (const label of ['Paste', 'Clear all nodes', 'Reset positions']) {
      assert.ok(disabled.some(item => item.getAttribute('aria-label') === label), label + ' has no action here and is disabled');
    }
    for (const item of disabled) {
      assert.match(item.style.outline, /dashed/, item.getAttribute('aria-label') + ' is dashed');
      assert.equal(item.style.opacity, '', item.getAttribute('aria-label') + ' carries no alpha');
      assert.ok(item.title && item.title !== item.getAttribute('aria-label'), item.getAttribute('aria-label') + ' says why: ' + item.title);
    }
    for (const item of items.filter(item => !item.disabled)) {
      assert.doesNotMatch(item.style.outline || '', /dashed/, 'enabled row ' + item.getAttribute('aria-label') + ' is not dashed');
      assert.equal(item.style.opacity, '', 'enabled row ' + item.getAttribute('aria-label') + ' carries no alpha');
    }
    const snap = items.find(item => item.getAttribute('aria-label') === 'Snap to grid');
    assert.equal(snap.getAttribute('role'), 'menuitemcheckbox');
    assert.equal(snap.getAttribute('aria-checked'), 'true', 'Snap to grid is on, as drawn');
    studio.flush(() => snap.click());
    assert.equal(studio.doc.querySelector('[role="menu"]') === null, true, 'choosing a row closes the menu');
    open();
    menu = studio.doc.querySelector('[role="menu"][aria-label="Canvas actions"]');
    assert.equal(menu.querySelector('[aria-label="Snap to grid"]').getAttribute('aria-checked'), 'false', 'the toggle holds its new state');
    studio.flush(() => menu.querySelector('[aria-label="Zoom to 100%"]').click());
    assert.ok([...studio.doc.querySelectorAll('div')].some(node => node.textContent === '100%' && !node.children.length), 'Zoom to 100% sets the zoom');

    const card = studio.doc.querySelector('.lm-node[data-node-id="work-a"]');
    studio.flush(() => card.dispatchEvent(new studio.win.MouseEvent('contextmenu', {bubbles:true, cancelable:true, clientX:200, clientY:140})));
    const nodeMenu = studio.doc.querySelector('[role="menu"][aria-label="Node actions"]');
    assert.ok(nodeMenu, 'right-click on a card opens its node menu');
    const nodeRows = [...nodeMenu.querySelectorAll('button[role="menuitem"]')];
    assert.deepEqual(nodeRows.map(item => item.getAttribute('aria-label')), ['Select direct neighbours', 'Select connected group',
      'Select all nodes', 'Clear selection', 'Fit selection', 'Auto-layout selection', 'Refresh canvas'],
      'the selection, fit and refresh actions the design canvas menu has no row for');
    assert.equal(nodeRows.find(item => item.getAttribute('aria-label') === 'Clear selection').disabled, false, 'the right-clicked card is selected');
  } finally { studio.close(); }
});

test('update controls: not in the Workspace header; in Settings > About a pending request and an unavailable restart are dashed and say why', async () => {
  const header = studio => {
    const canvas = [...studio.doc.querySelectorAll('button[aria-pressed]')].find(button => button.textContent.trim() === 'Canvas');
    assert.equal(canvas.parentElement.parentElement.querySelector('section[aria-label="Application release updates"]') === null, true,
      'the Workspace header draws no update controls (design studio-lm.jsx:1146-1148)');
    if (!studio.doc.querySelector('section[aria-label="Application release updates"]')) {
      studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:',', ctrlKey:true, bubbles:true})));
      const about = [...studio.doc.querySelectorAll('button')].find(button => button.textContent.trim().startsWith('About'));
      assert.ok(about, 'Settings offers About');
      studio.flush(() => about.click());
      // The design's About card keeps the controls behind its own "updates →" row.
      const more = [...studio.doc.querySelectorAll('[role="button"]')].find(row => row.textContent.trim().startsWith('updates'));
      if (more) studio.flush(() => more.click());
    }
    const section = studio.doc.querySelector('section[aria-label="Application release updates"]');
    assert.ok(section, 'Settings > About holds the release update controls');
    return section;
  };
  const busy = await mountStudio({pending:'check'});
  try {
    const check = header(busy).querySelector('button[aria-label="Check and download"]');
    assert.ok(check, 'the About update control is drawn');
    assertDisabledStyle(check, 'Check and download while a request is pending');
    assert.match(check.title, /wait/i, 'the pending control says it is waiting: ' + check.title);
  } finally { busy.close(); }
  const idle = await mountStudio();
  try {
    const check = header(idle).querySelector('button[aria-label="Check and download"]');
    assert.equal(check.disabled, false, 'with nothing pending the control is live');
    assert.notEqual(check.style.borderStyle, 'dashed', 'a live control is not dashed');
    assert.equal(check.style.opacity, '', 'a live control carries no alpha');
  } finally { idle.close(); }
  const ready = await mountStudio({update:{state:'ready', current_build:'20260916-2130-e733a13',
    available_build:'20260917-0900-abc1234', restart_supported:false}});
  try {
    const reload = header(ready).querySelector('button[aria-label="Update and reload"]');
    assert.ok(reload, 'the ready release offers Update and reload');
    assertDisabledStyle(reload, 'Update and reload without a desktop restart');
    assert.match(reload.title, /restart/i, 'the control names the missing restart: ' + reload.title);
  } finally { ready.close(); }
  // Re-enabled in place: the dashed style must hand the border back whole, not leave the browser's outset border.
  const reading = await mountStudio({update:null});
  try {
    const check = () => header(reading).querySelector('button[aria-label="Check and download"]');
    assertDisabledStyle(check(), 'Check and download before the release status is read');
    for (const [patch, when] of [[{applicationUpdate:{state:'idle', current_build:'20260916-2130-e733a13'}}, 'once the release status is read'],
      [{applicationUpdatePending:'check'}, ''], [{applicationUpdatePending:''}, 'once the pending request finishes']]) {
      reading.change(patch);
      if (!when) { assertDisabledStyle(check(), 'Check and download while a request is pending'); continue; }
      assert.equal(check().disabled, false, 'Check and download is live ' + when);
      assert.equal(check().style.borderTopStyle, 'solid', 'Check and download draws its solid border again ' + when +
        ' (got "' + check().style.borderTopStyle + '", border "' + check().style.border + '")');
    }
  } finally { reading.close(); }
});

test('minimap: the map frames the real nodes of an existing graph, wherever they sit', async () => {
  for (const [shape, rawCanvas] of [['spread past 2400 x 1400 and left of the origin', existingCanvas], ['compact', compactCanvas]]) {
    const studio = await mountStudio({rawCanvas});
    try {
      openCanvas(studio);
      const label = [...studio.doc.querySelectorAll('div')].find(node => node.textContent === 'MAP' && !node.children.length);
      assert.ok(label, 'the minimap is drawn');
      const svg = label.parentElement.querySelector('svg');
      const [left, top, width, height] = svg.getAttribute('viewBox').split(/\s+/).map(Number);
      assert.ok([left, top, width, height].every(Number.isFinite) && width > 0 && height > 0, shape + ': a finite viewBox');
      const rects = [...svg.querySelectorAll('rect')].map(rect => ['x', 'y', 'width', 'height'].map(key => Number(rect.getAttribute(key))));
      assert.equal(rects.length, rawCanvas.nodes.length, shape + ': one rectangle per projected node');
      for (const [x, y, w, h] of rects) {
        assert.ok(x >= left && y >= top && x + w <= left + width && y + h <= top + height,
          shape + ': node box ' + [x, y, w, h].join(',') + ' lies inside the map ' + [left, top, width, height].join(','));
      }
      const spanX = Math.max(...rects.map(([x, , w]) => x + w)) - Math.min(...rects.map(([x]) => x));
      const spanY = Math.max(...rects.map(([, y, , h]) => y + h)) - Math.min(...rects.map(([, y]) => y));
      assert.ok(width <= spanX * 1.25 + 80 && height <= spanY * 1.25 + 80,
        shape + ': the map is fitted to the nodes (' + width + 'x' + height + ' for a ' + spanX + 'x' + spanY + ' graph)');
    } finally { studio.close(); }
  }
});

test('onboarding: mounted on the first run the launcher measured, from live rows, with every control bound', async () => {
  const returning = await mountStudio();
  try {
    assert.equal(returning.doc.querySelector('[data-studio-screen]'), null, 'no onboarding without ARCHHUB_BOOT.first_run');
    assert.equal(returning.doc.body.textContent.includes('FIRST RUN'), false, 'a saved graph opens straight into the Studio');
  } finally { returning.close(); }
  // Rows in the shapes the routes answer: /api/universal/hosts (probe_connectors) and /api/universal/providers (provider_rows).
  const connectors = [
    {id:'revit', name:'Revit', drive:'revit.build_walls', state:'connected', detail:'1 session(s)'},
    {id:'autocad', name:'AutoCAD', drive:'cad.host_lines', state:'absent', detail:'no session listening'},
    {id:'blender', name:'Blender', drive:'blender.exec', state:'installed', detail:'enable the ArchHub Blender add-on (listens on :9876)'},
    {id:'notion', name:'Notion', drive:'notion.search', state:'needs-key', detail:'add a Notion integration token'},
  ];
  const providers = [
    {id:'openrouter', name:'OpenRouter', state:'keyed', source:'secrets store', sets:'OPENROUTER_API_KEY'},
    {id:'cloud', name:'ArchHub cloud', state:'no key', source:'', sets:''},
    {id:'anthropic', name:'Anthropic', state:'no key', source:'', sets:'ANTHROPIC_API_KEY'},
    {id:'ollama', name:'Ollama', state:'not running', source:'127.0.0.1:11434', sets:''},
  ];
  const writes = [];
  const rawCanvas = {nodes:[...existingCanvas.nodes, {id:'sketch-b', label:'Sketch Lines', engine:'vision.sketch_lines', x:0, y:0, status:'',
    params:[{label:'threshold', value:120, relation:'rel-threshold', editable:true}], ports:[]}], wires:existingCanvas.wires};
  const first = await mountStudio({rawCanvas, prepare:win => {
    win.ARCHHUB_BOOT = {token:'t', csrf:'c', first_run:true};
    win.ARCHHUB_LOAD_HOSTS = async () => ({hosts:[], connectors});
    win.ARCHHUB_EXISTING_WORKSHOP.readProviders = async () => providers;
    win.ARCHHUB_SET_PROP = async (relation, value) => { writes.push([relation, value]); return {ok:true}; };
  }});
  try {
    const view = () => first.doc.querySelector('[data-studio-screen="onboarding"]');
    assert.ok(view(), 'ARCHHUB_BOOT.first_run mounts the design onboarding inside the Studio');
    await first.settle(() => view().textContent.includes('\u00b7 detected: Revit, Blender') && view().textContent.includes('OpenRouter'),
      'the steps read the host scan and provider rows');
    const text = view().textContent;
    for (const design of ['FIRST RUN \u00b7 60 SECONDS \u00b7 4 STEPS', 'Welcome.', 'Pick a brain', 'YOUR KEY (BYO)', 'Birth a connector',
      'WHY THIS MATTERS', 'Your first skill', '\u00b7 not detected: AutoCAD', 'secrets store', 'Local Ollama', 'NOT RUNNING', 'Use OpenRouter',
      '\u2713 revit \u00b7 connected', 'threshold', 'drives Sketch Lines']) {
      assert.ok(text.includes(design), 'the onboarding draws ' + design);
    }
    assert.doesNotMatch(text, /Revit 2025|Blender 4\.0|sk-ant|AIza|Google|Cloud Relay|STUDIO|analyze blender SDK|Sketch to production|12s e2e|roof_pitch|chain re-running|Notion/,
      'no seeded artboard value, plan name or undrivable service row');
    const buttons = [...view().querySelectorAll('button')];
    assert.equal(buttons.length, 3, 'Continue, the model choice and Open Studio');
    assert.deepEqual(buttons.filter(button => typeof reactProps(button).onClick !== 'function').map(button => button.textContent), [], 'every onboarding button acts');
    first.flush(() => buttons.find(button => button.textContent === 'Continue').click());
    assert.ok(view().querySelector('[aria-label="Step 1 done"]'), 'Continue completes step 1 on the rail');
    assert.ok(view().querySelector('[aria-label="Step 2 current"]'), 'with no model chosen, step 2 is current');
    const slider = view().querySelector('input[type="range"][aria-label="threshold"]');
    first.flush(() => slider.dispatchEvent(new first.win.KeyboardEvent('keyup', {bubbles:true, key:'ArrowRight'})));
    await first.settle(() => writes.length === 1, 'the slider writes its graph relation when the drag ends');
    assert.deepEqual(writes[0], ['rel-threshold', 120]);
    const line = [...view().querySelectorAll('[role="button"]')].find(node => node.textContent === '\u00b7 blender \u00b7 installed');
    first.flush(() => line.click());
    assert.equal(first.doc.querySelector('[data-studio-screen]').getAttribute('data-studio-screen'), 'connector', 'a host line opens its diagnostic');
    first.flush(() => first.win.ArchHubStudioScreens.close());
    first.flush(() => [...view().querySelectorAll('button')].find(button => button.textContent === 'Open Studio').click());
    assert.equal(first.doc.querySelector('[data-studio-screen]'), null, 'Open Studio returns to the Studio');
    assert.equal(first.win.sessionStorage.getItem('archhub.onboarding.closed.v1'), '1', 'and it stays closed for this page session');
  } finally { first.close(); }
  // The signal is the launcher's saved-graph check, carried by the server's Studio boot payload.
  const launcher = read('launch_archhub_test.py');
  assert.match(launcher, /^first_boot = not _saved_graph_exists\(/m, 'the launcher still computes first_boot');
  assert.match(launcher, /^server\.studio_first_run = first_boot is True$/m, 'the launcher hands first_boot to the server');
  assert.ok(launcher.indexOf('server.studio_first_run = first_boot') < launcher.indexOf('view.load(QUrl(server.bootstrap_url))'),
    'before the window loads the Studio');
  const server = read('nodelang/application_server.py');
  const at = server.indexOf("b'/*__ARCHHUB_BOOT__*/ null'");
  assert.ok(at > 0, 'the server still injects the Studio boot payload');
  assert.match(server.slice(at, at + 600), /'first_run': owner\.studio_first_run is True,/, 'the Studio boot payload carries first_run');
  assert.match(server, /self\.studio_first_run = False/, 'a server without the launcher never claims a first run');
});
