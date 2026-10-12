const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {transformSync} = require('esbuild');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(match => [match[1], match[2]]));
const clone = value => JSON.parse(JSON.stringify(value));
const scope = () => ({graph_id:'graph-a', root:'scope-a', revision:7,
  workshops:[{root:'room-a', label:'General Workshop', is_general:true}]});

async function mountStudio() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53923/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const intervals = [];
  const nativeSetInterval = win.setInterval.bind(win);
  win.setInterval = (fn, ms, ...args) => {
    intervals.push({fn, ms});
    return nativeSetInterval(fn, ms, ...args);
  };
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const toolRows = [
    {id:'studio', label:'Studio', state:'running', state_word:'RUNNING', description:'Canvas, chats and graph sessions.', stat_line:'1 session.', off_sentence:'Switched off.', wire_summary:'Studio'},
    {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING', description:'Projects, tasks and governed work.', stat_line:'1 project.', off_sentence:'Switched off.', wire_summary:'Workshop'},
  ];
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/model-a'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:clone(toolRows)})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[{id:'tool-a', title:'Tool node', cat:'ai', x:40, y:40, w:220, h:120, params:[], outs:[]}], wires:[]};
  let snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization},
    workshops:[{root:'room-a', label:'General Workshop', is_general:true}],
    workshop:{graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:7,
      owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false, messages:[], participants:[]},
    nativeWork:{root:'room-a', scope:'scope-a', owner:'owner-a', view:'view-a', state:'idle', work:'work-a', title:'Layer selection', mode:'project'},
    theme:{configuration:{baboom_startup:{value:'on', source:'graph', available:true, revision:12}}, pending:false, error:''},
    applicationUpdate:{state:'ready', current_build:'20261010-a', available_build:'20261010-b', restart_supported:true},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const listeners = new Set();
  const owner = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    watchApplicationUpdate:() => () => {},
  };
  const publish = next => { snapshot = next; for (const listener of [...listeners]) listener(); };
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner, {get:(target, key) =>
    key in target || typeof key !== 'string' || key === 'then' ? target[key] : () => new Promise(() => {})});
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'Mine', state:'idle', file:'mine.graph', owner:'mine'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.ARCHHUB_TOOL_HUB = {ok:true, tools:clone(toolRows), waiting:[]};
  win.ARCHHUB_LOAD_HOSTS = () => Promise.resolve({hosts:[{id:'r25', name:'Revit 2025', state:'connected', file:'Tower.rvt'}]});

  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of ['tokens.jsx', 'design-canvas.jsx', 'shared-data.jsx', 'studio-suite.jsx',
    'param-types.jsx', 'studio-params.jsx', 'studio-mobile.jsx', 'studio-account.jsx',
    'node-registry.jsx', 'brain-model.jsx', 'workshop-board.jsx', 'studio-workshop.jsx', 'studio-lm.jsx']) {
    win.eval(transformSync(read('nodelang/studio/' + file), {loader:'jsx', target:'es2020'}).code);
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = async () => { await new Promise(resolve => win.setTimeout(resolve, 30)); for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
  await settle();
  const settings = win.document.querySelector('[title="Settings"]');
  assert.ok(settings, 'Settings button exists');
  win.ReactDOM.flushSync(() => settings.click());
  await settle();
  const card = win.document.querySelector('[data-tool-card="workshop"]');
  assert.ok(card, 'Workshop card exists');
  win.ReactDOM.flushSync(() => card.click());
  await settle();
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, doc:win.document, publish, snapshot:() => snapshot, settle, intervals, close};
}

test('identical Workshop polls do not rebuild the Studio header or Workshop header, and changed text updates in place', async () => {
  const studio = await mountStudio();
  try {
    const studioHeader = studio.doc.querySelector('section[aria-label="Application release updates"]');
    const workshopHeader = studio.doc.querySelector('[data-workshop-head]');
    assert.ok(studioHeader, 'Studio header update control is mounted');
    assert.ok(workshopHeader, 'Workshop header status line is mounted');
    assert.match(workshopHeader.textContent, /Tower\.rvt/);

    const records = [];
    const observer = new studio.win.MutationObserver(list => records.push(...list.filter(row => row.type === 'childList')));
    observer.observe(studioHeader.parentElement, {childList:true, subtree:true});
    observer.observe(workshopHeader.parentElement, {childList:true, subtree:true});

    const hubPoll = studio.intervals.find(row => row.ms === 5000);
    assert.ok(hubPoll, 'tool-hub poller is subscribed');
    await hubPoll.fn();
    await studio.settle();
    const hubAfterFirstPoll = studio.win.ARCHHUB_TOOL_HUB;
    await hubPoll.fn();
    await studio.settle();
    assert.strictEqual(studio.win.ARCHHUB_TOOL_HUB, hubAfterFirstPoll,
      'same-value /tools and /waiting poll keeps the previous tool-hub projection object');

    studio.win.ReactDOM.flushSync(() => studio.publish(clone(studio.snapshot())));
    await studio.settle();
    assert.equal(records.length, 0, 'same-value poll does not add or remove header DOM nodes');
    assert.strictEqual(studio.doc.querySelector('section[aria-label="Application release updates"]'), studioHeader);
    assert.strictEqual(studio.doc.querySelector('[data-workshop-head]'), workshopHeader);

    const changed = clone(studio.snapshot());
    changed.nativeWork = {...changed.nativeWork, work:'Door review'};
    studio.win.ReactDOM.flushSync(() => studio.publish(changed));
    await studio.settle();
    assert.strictEqual(studio.doc.querySelector('[data-workshop-head]'), workshopHeader,
      'changed value keeps the Workshop header node and updates its text in place');
    assert.match(workshopHeader.textContent, /Door review/);
  } finally { studio.close(); }
});

test('the Workshop projection does not publish when a poll repeats the same scope values', () => {
  const vm = require('node:vm');
  const context = vm.createContext({URLSearchParams, TextEncoder});
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), context);
  const api = context.ArchHubExistingWorkshop.create({get:async () => ({}), post:async () => ({})});
  let publishes = 0;
  api.subscribe(() => { publishes += 1; });
  api.setCanvas(scope());
  assert.equal(publishes, 1, 'first scope poll publishes the visible projection');
  api.setCanvas(scope());
  assert.equal(publishes, 1, 'same-value scope poll is not a new projection');
});
