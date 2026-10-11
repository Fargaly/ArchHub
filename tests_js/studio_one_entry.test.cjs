const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})/g)].map(m => [m[1], m[2]]));
const MODEL = 'Free Models Router';

const port = (owner, name, index, side) => ({id:owner + ':rel-' + index, name, side, mode:'connection',
  connectable:true, read_only:false, editable:false, interface_root:'if-' + owner + '-' + index,
  direction:side === 'source' ? 'output' : 'input', multiple:false, selected:false, context:false});
const rawCanvas = {nodes:[{id:'work-a', label:'Coordination task', x:40, y:60, status:'',
  params:[{label:'priority', value:'high', relation:'rel-priority', editable:true}],
  ports:[port('work-a', 'input', 0, 'target')]}], wires:[]};

function projected() {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(rawCanvas) + '));', context);
  return JSON.parse(context.graph);
}

async function mountStudio() {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-suite.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, 'Studio build is stale for ' + source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53912/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const route = 'openrouter/free';
  win.fetch = url => String(url).startsWith('/api/universal/models')
    ? Promise.resolve({ok:true, status:200, json:async () => ({ok:true, selected_route:route,
      groups:[{name:'BYO · OpenRouter', items:[{name:MODEL, route, routed:route, vendor:'OpenRouter', tag:'FREE', col:'#3a6acc'}]}]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const graph = projected();
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a'};
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', authorization},
    workshops:[], applicationUpdate:{state:'idle', current_build:'20261011-one-entry'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    selectTopology:async id => { snapshot.topology.selected = id; listeners.forEach(listener => listener()); },
    refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {},
    watchApplicationUpdate:() => () => {}, refreshApplicationUpdate:async () => {},
  };
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = async (done, what) => {
    for (let i = 0; i < 120 && !done(); i += 1) await new Promise(resolve => win.setTimeout(resolve, 5));
    assert.ok(done(), what);
  };
  const flush = action => win.ReactDOM.flushSync(action);
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc:win.document, settle, flush, close};
}

const leafText = (doc, text) => [...doc.querySelectorAll('button,span,div')]
  .filter(node => node.textContent.includes(text) && ![...node.children].some(child => child.textContent.includes(text)));
const settingsEntryControls = doc => [...doc.querySelectorAll('button')]
  .filter(button => button.getAttribute('title') === 'Settings' || button.textContent.trim() === 'Settings panel' || button.textContent.trim() === 'settings');
const modelIndicators = doc => [...doc.querySelectorAll('[data-model-indicator]')];
const openCanvas = studio => {
  const canvas = [...studio.doc.querySelectorAll('button[aria-pressed]')].find(button => button.textContent.trim() === 'Canvas');
  assert.ok(canvas, 'the header offers Canvas');
  studio.flush(() => canvas.click());
  assert.ok(studio.doc.querySelector('.lm-node[data-node-id="work-a"]'), 'canvas opens');
};
const openHome = studio => {
  const home = studio.doc.querySelector('button[title="All sessions"]');
  assert.ok(home, 'the header offers Home');
  studio.flush(() => home.click());
  assert.ok(studio.doc.querySelector('textarea[aria-label="Start a new session"]'), 'Home opens');
};

test('Settings has one visible entry point plus Ctrl+, and the model has one picker indicator on app surfaces', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(() => studio.doc.body.textContent.includes(MODEL), 'the selected model is visible once the catalogue answers');
    assert.equal(settingsEntryControls(studio.doc).length, 1, 'only the rail Settings control is visible');
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {bubbles:true, ctrlKey:true, key:','})));
    await studio.settle(() => [...studio.doc.querySelectorAll('button')].some(button => button.firstElementChild?.textContent === 'Hub'),
      'Ctrl+, opens Settings');
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {bubbles:true, key:'Escape'})));

    assert.ok(studio.doc.querySelector('[data-chat-view]'), 'Chat is the default session view');
    assert.equal(modelIndicators(studio.doc).length, 1, 'Chat has exactly one model indicator');
    assert.match(modelIndicators(studio.doc)[0].textContent, /Free Models Router/, 'the Chat indicator is the full picker label');
    openCanvas(studio);
    assert.ok(modelIndicators(studio.doc).length <= 1, 'Canvas has at most one model indicator');
    openHome(studio);
    assert.ok(modelIndicators(studio.doc).length <= 1, 'Home has at most one model indicator');
    // First-run onboarding has provider choices, not model indicators, and is intentionally outside this count.
  } finally { studio.close(); }
});
