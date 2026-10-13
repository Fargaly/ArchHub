const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

async function mountStudio({currentGraph = 'graph-a'} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53924/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const graph = {nodes:[
    {id:'studio', title:'Studio', application:true, cat:'ai', x:20, y:20, w:180, h:110, params:[], outs:[]},
    {id:'brain', title:'Brain', application:true, cat:'ai', x:240, y:20, w:180, h:110, params:[], outs:[]},
  ], wires:[]};
  const authorization = {subject:'owner-a', session:'view-a', system_view:true};
  const snapshot = {canvas:{graph_id:'graph-a', application_root:'graph-a', root:'scope-a', revision:7, authorization},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null},
    graph, workshops:[], theme:{configuration:{}, pending:false, error:''}, applicationUpdate:{state:'idle'}};
  const tools = [
    {id:'studio', label:'Studio', state:'running', state_word:'RUNNING', description:'Studio.', stat_line:'1 session.', wire_summary:'Studio'},
    {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING', description:'Workshop.', stat_line:'1 task.', wire_summary:'Workshop'},
    {id:'brain', label:'Brain', state:'off', state_word:'OFF', description:'Brain.', stat_line:'1 fact.', wire_summary:'Brain'},
    {id:'baboom', label:'BABOOM', state:'running', state_word:'RUNNING', description:'BABOOM.', stat_line:'Ready.', wire_summary:'BABOOM'},
    {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING', description:'Connectors.', stat_line:'1 host.', wire_summary:'Connectors'},
    {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING', description:'Cloud.', stat_line:'Local.', wire_summary:'Cloud'},
  ];
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/test:free'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_EXISTING_WORKSHOP = {getSnapshot:() => snapshot, subscribe:() => () => {}, watchApplicationUpdate:() => () => {}};
  win.ARCHHUB_TOOL_HUB = {ok:true, tools, waiting:[]};
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'Mine', state:'idle', file:'mine.graph'}], currentGraph,
    hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const flush = action => win.ReactDOM.flushSync(action);
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 40));
  const buttons = text => [...win.document.querySelectorAll('button')].filter(button => button.textContent.trim() === text);
  const clickText = text => {
    const button = buttons(text)[0];
    assert.ok(button, text + ' button exists');
    flush(() => button.click());
  };
  return {win, doc:win.document, flush, settle, buttons, clickText,
    close:() => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } }};
}

test('rail panels, docs and settings expose labelled navigation controls', async () => {
  const ui = await mountStudio();
  try {
    await ui.settle();
    const mine = ui.buttons('Mine')[0];
    if (mine) ui.flush(() => mine.click());
    await ui.settle();
    for (const title of ['Chats', 'Nodes', 'Skills', 'Search']) {
      const icon = ui.doc.querySelector(`[title="${title}"]`);
      assert.ok(icon, title + ' rail icon exists');
      ui.flush(() => icon.click());
      assert.ok(ui.buttons('Home').some(button => button.hasAttribute('data-home-button')), title + ' panel has labelled Home');
    }
    const docs = ui.doc.querySelector('[title="Documentation . Command+/"]') || ui.doc.querySelector('[title^="Documentation"]');
    assert.ok(docs, 'Docs rail icon exists');
    ui.flush(() => docs.click());
    assert.equal(ui.buttons('Home').filter(button => button.hasAttribute('data-home-button')).length, 1, 'Docs has exactly one labelled Home');
    ui.clickText('Home');
    await ui.settle();
    const settings = ui.doc.querySelector('[title="Settings"]');
    assert.ok(settings, 'Settings rail icon exists');
    ui.flush(() => settings.click());
    await ui.settle();
    assert.ok(ui.buttons('Close').some(button => button.hasAttribute('data-close-button')), 'Hub settings section has labelled Close');
    for (const section of ['Account', 'Brain']) {
      const tab = [...ui.doc.querySelectorAll('button')].find(button =>
        button.textContent.trim() === section || button.textContent.trim().startsWith(section));
      assert.ok(tab, section + ' settings tab exists');
      ui.flush(() => tab.click());
      assert.ok(ui.buttons('Close').some(button => button.hasAttribute('data-close-button')), section + ' settings section has labelled Close');
    }
  } finally { ui.close(); }
});

test('Home from an open rail panel clears the active graph and panel', async () => {
  const ui = await mountStudio();
  try {
    await ui.settle();
    assert.ok(ui.doc.querySelector('[data-ws-tab][aria-current="page"]'), 'session view opened');
    const search = ui.doc.querySelector('[title="Search"]');
    assert.ok(search, 'Search rail icon exists');
    ui.flush(() => search.click());
    await ui.settle();
    assert.ok(ui.buttons('Home').some(button => button.hasAttribute('data-home-button')), 'Search panel Home exists');
    ui.clickText('Home');
    await ui.settle();
    assert.ok(ui.doc.querySelector('form'), 'sessions/home view renders');
    assert.equal(ui.doc.querySelector('[data-ws-tab].active'), null, 'no session tab remains active');
    assert.equal(ui.doc.querySelector('[data-system-graph]'), null, 'system mode is closed');
    assert.equal(ui.doc.querySelector('[data-rail-panel="Search"][aria-current="true"]'), null, 'Search rail panel is closed');
    assert.equal(ui.doc.querySelector('[data-tool-view]'), null, 'tool view is closed');
  } finally { ui.close(); }
});

test('Home from system mode returns to the sessions view', async () => {
  const ui = await mountStudio({currentGraph:'system:graph-a'});
  try {
    await ui.settle();
    assert.ok(ui.doc.querySelector('[data-system-graph]'), 'system graph header renders');
    ui.clickText('Home');
    await ui.settle();
    assert.equal(ui.doc.querySelector('[data-system-graph]'), null, 'system graph header is gone');
    assert.ok(ui.doc.querySelector('form'), 'sessions/home view renders');
  } finally { ui.close(); }
});
