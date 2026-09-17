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
  pending = '', answer = null} = {}) {
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
  const server = [...studio.doc.querySelectorAll('button')].find(button => button.textContent.includes('server 127.0.0.1:53912'));
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

test('status bar: the model slot names the picked model, and is not drawn while nothing is picked', async () => {
  const unpicked = await mountStudio();
  try {
    const strip = serverStrip(unpicked);
    assert.equal(/choose[- ]a[- ]model/i.test(strip.textContent), false, 'no placeholder slug in the status bar: ' + strip.textContent);
    assert.ok(strip.textContent.includes('Graph composition'), 'the open session file is still named');
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
    assert.ok(strip.textContent.includes(name), 'the status bar names the picked model as the catalogue names it: ' + strip.textContent);
    assert.equal(/choose[- ]a[- ]model/i.test(strip.textContent), false, 'no placeholder beside the picked model');
  } finally { picked.close(); }
});

test('icon rail: every drawn rail control has an action, so the unbound Share icon is gone', async () => {
  const studio = await mountStudio();
  try {
    const rail = studio.doc.querySelector('aside').firstElementChild;
    const buttons = [...rail.querySelectorAll('button')];
    assert.ok(buttons.length >= 6, 'the rail is drawn: ' + buttons.length + ' controls');
    const dead = buttons.filter(button => typeof reactProps(button).onClick !== 'function').map(button => button.title);
    assert.deepEqual(dead, [], 'rail controls with no action: ' + dead.join(', '));
    assert.equal(buttons.some(button => button.title === 'Share'), false, 'no Share icon without a share action');
    for (const title of ['Home', 'Settings']) assert.ok(buttons.some(button => button.title === title), title + ' stays on the rail');
  } finally { studio.close(); }
});

test('canvas menu: disabled actions are dashed and say why, never alpha', async () => {
  const studio = await mountStudio();
  try {
    openCanvas(studio);
    const region = studio.doc.querySelector('[aria-label="Workflow canvas"]');
    studio.flush(() => region.dispatchEvent(new studio.win.MouseEvent('contextmenu', {bubbles:true, cancelable:true, clientX:120, clientY:120})));
    const menu = studio.doc.querySelector('[role="menu"][aria-label="Canvas actions"]');
    assert.ok(menu, 'right-click opens the canvas menu');
    const items = [...menu.querySelectorAll('button[role="menuitem"]')];
    const disabled = items.filter(item => item.disabled);
    assert.ok(disabled.some(item => item.getAttribute('aria-label') === 'Clear selection'), 'with nothing selected, Clear selection is disabled');
    for (const item of disabled) assertDisabledStyle(item, 'menu item ' + item.getAttribute('aria-label'));
    const clear = disabled.find(item => item.getAttribute('aria-label') === 'Clear selection');
    assert.match(clear.title, /nothing is selected/i, 'Clear selection names its reason');
    for (const item of items.filter(item => !item.disabled)) {
      assert.notEqual(item.style.borderStyle, 'dashed', 'enabled item ' + item.getAttribute('aria-label') + ' is not dashed');
      assert.equal(item.style.opacity, '', 'enabled item ' + item.getAttribute('aria-label') + ' carries no alpha');
    }
  } finally { studio.close(); }
});

test('update controls: a pending request and an unavailable restart are dashed and say why, never alpha', async () => {
  const header = studio => studio.doc.querySelector('section[aria-label="Application release updates"]');
  const busy = await mountStudio({pending:'check'});
  try {
    const check = header(busy).querySelector('button[aria-label="Check and download"]');
    assert.ok(check, 'the header update control is drawn');
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

test('onboarding: not mounted, and the recorded reason still matches the code that keeps it out', async () => {
  const studio = await mountStudio();
  try {
    for (const artboard of ['FIRST RUN', 'Pick a brain', 'Birth a connector']) {
      assert.equal(studio.doc.body.textContent.includes(artboard), false, 'the onboarding artboard is not on screen: ' + artboard);
    }
  } finally { studio.close(); }
  const suite = read('nodelang/studio/studio-suite.jsx');
  const start = suite.indexOf('const StudioOnboarding = () => (');
  const end = suite.indexOf('const OnbStep = ', start);
  assert.ok(start > 0 && end > start, 'StudioOnboarding is still in studio-suite.jsx');
  const record = suite.slice(suite.lastIndexOf('ONBOARDING', start), start);
  assert.match(record, /not mounted/i, 'studio-suite.jsx records, beside the component, that the onboarding is not mounted and why');
  assert.match(record, /first_boot/, 'the record names the launcher first-run signal');
  assert.match(record, /ARCHHUB_BOOT/, 'the record names the Studio boot payload that does not carry it');
  assert.match(record, /no action/i, 'the record names the unbound buttons');
  // The facts the record states. When one changes, mount the onboarding or rewrite the record.
  const component = suite.slice(start, end);
  const buttons = component.match(/<button\b[^>]*>/g) || [];
  assert.ok(buttons.length >= 3, 'the artboard still draws its buttons');
  assert.deepEqual(buttons.filter(tag => /onClick/.test(tag)), [], 'an onboarding button gained an action: revisit the record');
  const launcher = read('launch_archhub_test.py');
  assert.match(launcher, /^first_boot = not _saved_graph_exists\(/m, 'the launcher still computes first_boot');
  const server = read('nodelang/application_server.py');
  const at = server.indexOf("b'/*__ARCHHUB_BOOT__*/ null'");
  assert.ok(at > 0, 'the server still injects the Studio boot payload');
  assert.match(server.slice(at, at + 400), /json\.dumps\(\{\s*'token': \(studio_session_token\),\s*'csrf': studio_binding\.csrf_token,\s*\}\)/,
    'the Studio boot payload still carries only token and csrf');
  for (const file of ['nodelang/application_server.py', 'nodelang/studio/studio.html', 'nodelang/studio/studio-lm.jsx',
    'nodelang/studio/studio-existing-workshop.js', 'nodelang/studio/mount.jsx']) {
    assert.equal(/first_boot|firstBoot|ARCHHUB_FIRST/.test(read(file)), false, file + ' now carries a first-run signal: revisit the record');
  }
});
