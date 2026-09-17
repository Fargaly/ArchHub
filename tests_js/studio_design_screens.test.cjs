/* Design parity, docs-boot-onboarding lane: Docs search and Docs > Brain, the boot splash, and the design's
   full-bleed screens that open inside the Studio (Skill split view, connector diagnostic), measured on the
   whole compiled Studio mounted in an in-memory DOM over an existing-graph shape. Design contract:
   ArchHub App.html artboards "Studio · Settings · Docs", "Loading", "Skill JSON · split view" and
   "Self-healing inspector"; HANDOVER.md section 2 (docs search over 90 entries, 16 derived from
   brain-model.jsx). Seeded artboard values (ratings, installs, PIDs, uptimes, heal history) must not ship;
   live rows replace them and an unmeasured cell draws the design's '—'.
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
const BUILD = '20260916-2130-e733a13';
const rawCanvas = {nodes:[
  {id:'sketch-a', label:'Sketch Lines', engine:'vision.sketch_lines', x:40, y:60, status:'',
    params:[{label:'engine', value:'vision.sketch_lines'}, {label:'threshold', value:120, relation:'rel-threshold', editable:true}],
    ports:[{id:'sketch-a:rel-0', name:'lines', side:'source', mode:'connection', connectable:true}]},
], wires:[]};
// probe_connectors rows exactly as /api/universal/hosts returns them (pipeline_engines.py, host_brokers.py).
const HOSTS = [
  {id:'revit', name:'Revit', drive:'revit.build_walls', state:'absent', detail:'no session listening on 48884-48899'},
  {id:'blender', name:'Blender', drive:'blender.exec', state:'installed', detail:'enable the ArchHub Blender add-on (listens on :9876)'},
  {id:'speckle', name:'Speckle', drive:'', state:'installed', detail:'Manager installed · no wire in this build'},
];
// skills_catalogue row and the skill_read text (pipeline_engines.py).
const SKILL = {name:'ship-discipline', source:'claude', description:'Prior art before code; never stop before the deliverable ships.',
  path:'C:\\Users\\someone\\.claude\\skills\\ship-discipline\\SKILL.md'};
const SKILL_TEXT = '---\nname: ship-discipline\ndescription: Prior art before code.\n---\n\n# Ship discipline\n\n## Prior art\nSearch first.\n\n## Ship\nDeliver.\n';

function projected() {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(rawCanvas) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio({update = {state:'idle', current_build:BUILD}, prepare = () => {}} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-suite.jsx', 'studio-account.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, 'Studio build is stale for ' + source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = () => new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const graph = projected();
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a'};
  let snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', authorization}, workshops:[], applicationUpdate:update,
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    selectTopology:async () => {}, refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {},
    watchApplicationUpdate:() => () => {}, refreshApplicationUpdate:async () => {}, applicationUpdateAction:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'Wall conversion', state:'idle', file:'Graph composition'}],
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
    for (let tick = 0; tick < 300 && !done(); tick += 1) await new Promise(resolve => win.setTimeout(resolve, 5));
    assert.ok(done(), what);
  };
  const close = () => { try { if (win.__studioRoot) flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc, flush, settle, close};
}
const reactProps = element => element[Object.keys(element).find(key => key.startsWith('__reactProps'))] || {};
const buttonsIn = element => [...element.querySelectorAll('button')];
const screen = studio => studio.doc.querySelector('[data-studio-screen]');
const key = (studio, init) => studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {bubbles:true, ...init})));

test('docs: the version slot names the running build; search and Docs > Brain are the design, derived from brain-model.jsx', async () => {
  const studio = await mountStudio();
  try {
    key(studio, {key:'/', ctrlKey:true});
    const title = [...studio.doc.querySelectorAll('span')].find(node => node.textContent === 'Documentation');
    assert.ok(title, 'ctrl+/ opens the Documentation overlay');
    const header = title.parentElement;
    assert.equal(title.nextElementSibling.textContent, 'STUDIO \u00b7 ' + BUILD, 'the design slot "STUDIO \u00b7 v1.4" names the running build');
    const input = header.querySelector('input[placeholder="Search the docs\u2026"]');
    assert.ok(input, 'the docs search box is drawn');
    const setter = Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set;
    studio.flush(() => { setter.call(input, 'brain'); input.dispatchEvent(new studio.win.Event('input', {bubbles:true})); });
    const panel = input.parentElement;
    assert.match(panel.textContent, /\u2191\u2193 MOVE \u00b7 \u21b5 OPEN \u00b7 ESC CLEAR \u00b7 \d OF 90 ENTRIES/, 'search runs over 90 entries: 74 static + 16 derived from brain-model.jsx');
    const hits = [...panel.querySelectorAll('button')].map(button => button.textContent);
    assert.ok(hits.some(text => text.startsWith('PAGEThe Brain')), 'the derived brain page is a hit: ' + hits.join(' | '));
    studio.flush(() => { setter.call(input, ''); input.dispatchEvent(new studio.win.Event('input', {bubbles:true})); });
    const nav = [...studio.doc.querySelectorAll('button')].find(button => button.textContent === 'Brain4 strata');
    assert.ok(nav, 'the Docs nav carries the design Brain row');
    studio.flush(() => nav.click());
    const body = nav.parentElement.nextElementSibling;
    for (const heading of ['FOUR STRATA', 'THREE LAKES, NOT ONE CASCADE', 'GATES', 'YOUR KEY']) {
      assert.ok(body.textContent.includes(heading), 'Docs > Brain draws ' + heading);
    }
    for (const stratum of studio.win.BRAIN_STRATA) {
      assert.ok(body.textContent.includes(stratum.n + ' \u00b7 ' + stratum.one), 'Docs > Brain reads the stratum ' + stratum.n + ' from brain-model.jsx');
    }
  } finally { studio.close(); }
  const unversioned = await mountStudio({update:null});
  try {
    key(unversioned, {key:'/', ctrlKey:true});
    const title = [...unversioned.doc.querySelectorAll('span')].find(node => node.textContent === 'Documentation');
    assert.equal(title.nextElementSibling.textContent, 'STUDIO', 'with no release report the slot is the label alone, never a typed version');
  } finally { unversioned.close(); }
});

test('boot: the splash is the design held moment, and its line reads what answered', async () => {
  const studio = await mountStudio({prepare:win => { win.ARCHHUB_LIVE.connectors.push({id:'rhino', name:'Rhino', state:'connected'}); }});
  try {
    const hub = [...studio.doc.querySelectorAll('span')].find(node => node.textContent === 'Hub' && node.parentElement.textContent === 'ArchHub');
    assert.ok(hub, 'the boot mark and wordmark are drawn');
    const splash = hub.parentElement.parentElement.parentElement.parentElement;
    assert.equal(splash.style.zIndex, '200', 'the splash covers the Studio while it boots');
    const skip = buttonsIn(splash).find(button => button.textContent === 'TAKING TOO LONG?');
    assert.ok(skip && typeof reactProps(skip).onClick === 'function', 'the design escape is drawn and works');
    const line = hub.parentElement.nextElementSibling;
    await studio.settle(() => /Rhino/.test(line.textContent), 'the hosts line names the connector that answered, not a seeded list: ' + line.textContent);
    assert.doesNotMatch(splash.textContent, /34 colours|8 facts|Revit \u00b7 Rhino \u00b7 Speckle|6 saved|11 nodes restored/, 'no seeded boot detail');
  } finally { studio.close(); }
  // The catalogues load with their panels: before they answer, boot claims no count and no absence.
  const context = vm.createContext({window:{AH:{}, ARCHHUB_LIVE:{connectors:[], skills:[], memory:[], graph:{nodes:[{id:'a'}]}}}});
  vm.runInContext(read('nodelang/studio/compiled/studio-account.js') + '\nglobalThis.detail = _bootDetail;', context);
  assert.equal(context.detail('hosts'), '\u2014', 'an unscanned machine is not reported as none listening');
  assert.equal(context.detail('skills'), '\u2014', 'an unread skills catalogue is not reported as 0 on this machine');
  assert.equal(context.detail('canvas'), '1 nodes restored', 'the canvas line counts the projected graph');
  context.window.ARCHHUB_LIVE.connectors.push({id:'max', name:'3ds Max', state:'installed'});
  assert.equal(context.detail('hosts'), 'none listening', 'a scan that answered with nothing listening says so');
});

test('skill split view: a catalogue row opens its own file, measured, with no seeded rating and no dead control', async () => {
  const asked = [];
  const studio = await mountStudio({prepare:win => {
    win.ARCHHUB_READ_SKILL = async name => { asked.push(name); return SKILL_TEXT; };
    win.navigator.clipboard = {writeText:async text => { win.__copied = text; }};
  }});
  try {
    assert.equal(typeof studio.win.ArchHubStudioScreens?.open, 'function', 'the Studio exposes its design screens to their owning surfaces');
    studio.flush(() => studio.win.ArchHubStudioScreens.open('skill', SKILL));
    const lines = SKILL_TEXT.split('\n').length, bytes = Buffer.byteLength(SKILL_TEXT);
    await studio.settle(() => screen(studio)?.textContent.includes(bytes + ' bytes \u00b7 ' + lines + ' lines'), 'the source pane measures the file it read');
    const view = screen(studio);
    assert.equal(view.getAttribute('data-studio-screen'), 'skill');
    assert.deepEqual(asked, ['ship-discipline'], 'the view reads the row it was opened with');
    assert.equal(view.querySelector('h1').textContent, SKILL.name);
    for (const text of ['SKILL \u00b7 OPEN', 'WHAT IT DOES', SKILL.description, 'SOURCE \u00b7 SKILL.md', 'YOU OWN THIS', 'Prior art', 'Ship']) {
      assert.ok(view.textContent.includes(text), 'the split view draws ' + text);
    }
    assert.doesNotMatch(view.textContent, /\u2605|installs|Fork|Open in chat|Sketch to production|EXPOSED PARAMETERS|mass_height/, 'no seeded artboard value or unbound control');
    const buttons = buttonsIn(view);
    assert.deepEqual(buttons.filter(button => typeof reactProps(button).onClick !== 'function').map(button => button.textContent), [], 'every drawn control acts');
    const copy = buttons.find(button => button.textContent.includes('Copy SKILL.md'));
    assert.equal(copy.disabled, false, 'Copy is live once the file is read');
    assert.equal(copy.style.borderTopStyle, 'solid', 'Copy draws its solid border again after the read (got "' + copy.style.border + '")');
    studio.flush(() => copy.click());
    await studio.settle(() => studio.win.__copied === SKILL_TEXT, 'Copy writes the skill file text');
    key(studio, {key:'Escape'});
    assert.equal(screen(studio), null, 'Esc returns to the Studio');
  } finally { studio.close(); }
});

test('connector diagnostic: the chain is the host scan state, Check now scans again, and nothing unmeasured is invented', async () => {
  let scans = 0;
  const studio = await mountStudio({prepare:win => {
    win.ARCHHUB_LOAD_HOSTS = async () => { scans += 1;
      return {hosts:[], connectors:HOSTS.map(row => row.id === 'blender' ? {...row, state:'connected', detail:'add-on on :9876'} : row)}; };
  }});
  try {
    studio.flush(() => studio.win.ArchHubStudioScreens.open('connector', HOSTS[1]));
    const view = screen(studio);
    assert.equal(view.getAttribute('data-studio-screen'), 'connector');
    assert.equal(view.querySelector('h1').textContent, 'Blender installed \u2014 not live.');
    for (const text of ['CONNECTOR \u00b7 DIAGNOSTIC', 'Installed on this machine', 'host scan \u00b7 installed', 'Process running',
      HOSTS[1].detail, 'Port reachable', 'Handshake', 'Wired to the graph', 'blender.exec', 'SUGGESTED FIX', 'CONTEXT', 'RECENT HEALS', 'last check \u00b7 \u2014']) {
      assert.ok(view.textContent.includes(text), 'the diagnostic draws ' + text);
    }
    assert.doesNotMatch(view.textContent, /PID|14728|4h 12m|auto-healed|2\.1s|handshake timeout|DLL locked|attempt 2\/3|Pause|Show diff|Apply fix|Revit 2025/, 'no seeded artboard value or unbound control');
    const buttons = buttonsIn(view);
    assert.deepEqual(buttons.filter(button => typeof reactProps(button).onClick !== 'function').map(button => button.textContent), [], 'every drawn control acts');
    const check = buttons.find(button => button.textContent === 'Check now \u21bb');
    studio.flush(() => check.click());
    await studio.settle(() => screen(studio)?.querySelector('h1').textContent === 'Blender connected \u2014 live.', 'Check now reads the scan again');
    assert.equal(scans, 1, 'one scan per Check now');
    assert.doesNotMatch(screen(studio).textContent, /SUGGESTED FIX|last check \u00b7 \u2014/, 'a live connector draws no fix, and the check time is measured');
    studio.flush(() => buttonsIn(screen(studio)).find(button => button.textContent === 'Close').click());
    assert.equal(screen(studio), null, 'Close returns to the Studio');
    assert.throws(() => studio.win.ArchHubStudioScreens.open('pricing', {name:'Studio'}), /skill or connector/, 'only the design screens open');
  } finally { studio.close(); }
});