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
const ROUTE = 'openrouter/free';
const MODEL = 'Free Models Router';

function projected() {
  const html = read('nodelang/studio/studio.html');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  const raw = {nodes:[{id:'work-a', label:'Coordination task', x:40, y:60, status:'',
    params:[{label:'priority', value:'high', relation:'rel-priority', editable:true}], ports:[]}], wires:[]};
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(raw) + '));', context);
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
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53933/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.fetch = url => String(url).startsWith('/api/universal/models')
    ? Promise.resolve({ok:true, status:200, json:async () => ({ok:true, selected_route:'',
      default_route:ROUTE, default_source:'free · OpenRouter',
      default_model:{name:MODEL, route:ROUTE, routed:ROUTE, vendor:'OpenRouter', tag:'FREE', ctx:'', col:'#3a6acc', latency:null},
      readiness:{state:'ready', route:ROUTE, actions:[], families:{
        openrouter:{state:'ready', message:'', actions:[]}, cloud:{state:'no_key', message:'', actions:[]},
        nvidia:{state:'no_key', message:'', actions:[]}, lmstudio:{state:'ready', message:'', actions:[]},
        ollama:{state:'ready', message:'', actions:[]}}, messages:{}}, groups:[]})})
    : new Promise(() => {});
  win.ARCHHUB_AGENT = async () => ({answer:'PONG'});
  win.ARCHHUB_AGENT_SELECT = async route => route;
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const graph = projected();
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a'};
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization},
    workshops:[], applicationUpdate:{state:'idle', current_build:'b1'},
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
  const type = (input, text) => flush(() => {
    Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set.call(input, text);
    input.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  return {win, doc:win.document, settle, flush, type,
    close:() => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } }};
}

const modelIndicators = doc => [...doc.querySelectorAll('[data-model-indicator]')];
const button = (doc, label) => [...doc.querySelectorAll('button')].find(node => node.textContent.trim() === label);

test('fresh signed-out first screen preselects the free router with its friendly name', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(() => modelIndicators(studio.doc).some(node => node.textContent.includes(MODEL)),
      'the first screen shows the default free router label');
    assert.equal(modelIndicators(studio.doc).length, 1, 'the first screen has one model indicator');
    assert.match(modelIndicators(studio.doc)[0].textContent, /Free Models Router/);
    assert.doesNotMatch(modelIndicators(studio.doc)[0].textContent, /openrouter\/free/);
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null, 'the default free route is selected, not the no-model state');
    const input = [...studio.doc.querySelectorAll('input')].find(node => /Reply/.test(node.placeholder || ''));
    assert.ok(input, 'the chat composer is visible');
    studio.type(input, 'ping');
    studio.flush(() => button(studio.doc, 'Send \u21b5').click());
    await studio.settle(() => studio.doc.body.textContent.includes('PONG'), 'the chat answer is drawn');
    assert.ok([...studio.doc.querySelectorAll('span')].some(node => node.textContent === MODEL),
      'the answer turn is signed with the friendly model label');
  } finally { studio.close(); }
});
