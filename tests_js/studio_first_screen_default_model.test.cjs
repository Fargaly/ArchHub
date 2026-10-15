const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
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

async function mountStudio({models, selectedTitleLeak = '', modelReadTimeoutMs, modelRetryDelaysMs,
  home = false, graphOpen = null, systemView = false, selectionTransport = null} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx', 'studio-suite.jsx']) {
    const held = manifest.files.find(file => file.source === source);
    const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(held && held.source_sha256, live, 'Studio build is stale for ' + source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53933/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  if (modelReadTimeoutMs) win.__ARCHHUB_MODEL_READ_TIMEOUT_MS = modelReadTimeoutMs;
  if (modelRetryDelaysMs) win.__ARCHHUB_MODEL_RETRY_DELAYS_MS = modelRetryDelaysMs;
  const defaultModels = {ok:true, selected_route:'',
      default_route:ROUTE, default_source:'free · OpenRouter',
      default_model:{name:MODEL, route:ROUTE, routed:ROUTE, vendor:'OpenRouter', tag:'FREE', ctx:'', col:'#3a6acc', latency:null},
      readiness:{state:'ready', route:ROUTE, actions:[], families:{
        openrouter:{state:'ready', message:'', actions:[]}, cloud:{state:'no_key', message:'', actions:[]},
        nvidia:{state:'no_key', message:'', actions:[]}, lmstudio:{state:'ready', message:'', actions:[]},
        ollama:{state:'ready', message:'', actions:[]}}, messages:{}}, groups:[]};
  win.fetch = url => {
    if (!String(url).startsWith('/api/universal/models')) return new Promise(() => {});
    const answer = typeof models === 'function' ? models() : (models || defaultModels);
    if (answer == null) return Promise.resolve({ok:true, status:200, json:async () => defaultModels});
    if (answer && answer.never) return new Promise(() => {});
    return Promise.resolve(answer).then(payload => {
      if (payload && payload.http) return {ok:payload.ok, status:payload.status || 500, json:async () => payload.body || {}};
      return {ok:true, status:200, json:async () => payload};
    });
  };
  const agentCalls = [];
  const startCalls = [];
  win.ARCHHUB_AGENT = async (text, route, context) => {
    agentCalls.push({text, route, context});
    return {answer:'PONG'};
  };
  win.ARCHHUB_AGENT_SELECT = async route => route;
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const graph = projected();
  if (selectionTransport) graph.nodes.push({...graph.nodes[0], id:'work-b', title:'Second task', x:420});
  if (systemView && graph.nodes[0]) graph.nodes = graph.nodes.concat({
    ...graph.nodes[0], id:'app-node', title:'Application node', application:true, x:320, y:60,
  });
  const listeners = new Set();
  const authorization = {subject:'owner-a', session:'view-a', ...(systemView ? {system_view:true} : {})};
  const canvas = {graph_id:'graph-a', root:'scope-a', revision:7, authorization};
  if (selectedTitleLeak) canvas.selected_title = selectedTitleLeak;
  const snapshot = {canvas,
    workshops:[], applicationUpdate:{state:'idle', current_build:'b1'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, selected_title:selectedTitleLeak,
      authorization, revision:7}, graph, selected:null}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    selectTopology:async id => { snapshot.topology.selected = id; listeners.forEach(listener => listener()); },
    refreshTopologyCanvas:async () => {}, refreshConversationCatalog:async () => {},
    startSession:async details => {
      startCalls.push(details);
      snapshot.workshops = [{root:'root-a', label:'Started session'}];
      snapshot.canvas = {...snapshot.canvas, graph_id:'graph-a', root:'root-a'};
      snapshot.topology.canvas = {...snapshot.topology.canvas, root:'root-a', scope:{current:'root-a'}};
      listeners.forEach(listener => listener());
      return {graph_id:'graph-a', root:'root-a', scope_path:'scope-a'};
    },
    watchApplicationUpdate:() => () => {}, refreshApplicationUpdate:async () => {},
  };
  const selectionPosts = [];
  if (selectionTransport) {
    win.eval(read('nodelang/studio/studio-existing-workshop.js'));
    let durable = {ok:true, application_root:'graph-a', root:'scope-a', scope:{current:'scope-a'},
      authorization, revision:7, nodes:graph.nodes, wires:graph.wires,
      workshop_scope:{graph_id:'graph-a', root:'scope-a', revision:7, authorization, workshops:[]},
      interaction_projection:{revision:7, bindings:[]}};
    const real = win.ArchHubExistingWorkshop.create({get:async () => structuredClone(durable),
      post:async (url, body) => {
        selectionPosts.push({url, body:JSON.parse(JSON.stringify(body))});
        if (selectionTransport.beforeReply) await selectionTransport.beforeReply(selectionPosts.length);
        durable = {...durable, revision:durable.revision + 1, selected:body.focus, selection:[...body.roots],
          interaction_projection:{revision:durable.revision + 1, bindings:[]},
          workshop_scope:{...durable.workshop_scope, revision:durable.revision + 1},
          nodes:durable.nodes.map(node => ({...node, selected:body.roots.includes(node.id)}))};
        return structuredClone(durable);
      }, projectCanvas:value => ({nodes:value.nodes, wires:value.wires})});
    real.setTopologyCanvas(durable);
    win.ARCHHUB_EXISTING_WORKSHOP = real;
  }
  win.ARCHHUB_SCOPE_OPEN = async () => {};
  if (graphOpen) win.ARCHHUB_GRAPH_OPEN = graphOpen;
  win.ARCHHUB_LIVE = {sessions:[{id:'graph-a', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'graph-a', hosts:[], connectors:[], graph, memory:[], skills:[]};
  if (!home) win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
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
    const proto = input instanceof win.HTMLTextAreaElement ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(input, text);
    input.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  return {win, doc:win.document, settle, flush, type, agentCalls, startCalls, selectionPosts,
    close:() => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } }};
}

const modelIndicators = doc => [...doc.querySelectorAll('[data-model-indicator]')];
const button = (doc, label) => [...doc.querySelectorAll('button')].find(node => node.textContent.trim() === label);
const noModelCard = doc => doc.querySelector('[data-chat-no-model]');

for (const pending of [false, true]) {
  test('UPD2 p9 full Studio: click A then Shift B preserves the selected pair and Group ' +
      (pending ? 'while A is pending' : 'after A commits'), async () => {
    let releaseFirst;
    const firstReply = new Promise(resolve => { releaseFirst = resolve; });
    const studio = await mountStudio({selectionTransport:{
      beforeReply:count => pending && count === 1 ? firstReply : undefined,
    }});
    const card = id => studio.doc.querySelector('.lm-node[data-node-id="' + id + '"]');
    const selected = () => [...studio.doc.querySelectorAll('.lm-node[data-selected="true"]')].map(node => node.dataset.nodeId).sort();
    try {
      await studio.settle(() => card('work-a') && card('work-b'), 'both cards drawn');
      const click = (id, shiftKey = false) => studio.flush(() => card(id).dispatchEvent(
        new studio.win.MouseEvent('click', {bubbles:true, shiftKey})));
      click('work-a');
      await studio.settle(() => studio.selectionPosts.length === 1, 'first selection submitted');
      if (!pending) await studio.settle(() => !studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.pending, 'first selection committed');
      assert.deepEqual(selected(), ['work-a']);
      click('work-b', true);
      if (pending) releaseFirst();
      await studio.settle(() => studio.selectionPosts.length === 2 &&
        !studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.pending, 'second selection committed');
      assert.deepEqual(studio.selectionPosts.map(row => row.body.roots), [['work-a'], ['work-a','work-b']]);
      assert.deepEqual(selected(), ['work-a','work-b']);
      assert.match(studio.doc.querySelector('[data-selection-bar] button')?.textContent || '', /Group 2 nodes/);
      assert.equal(studio.doc.querySelector('[data-selection-bar] button').disabled, false);
      assert.equal(studio.win.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.requires_refresh, false);
    } finally { releaseFirst(); studio.close(); }
  });
}
const homeComposer = doc => doc.querySelector('textarea[aria-label="Start a new session"]');
const homeText = doc => doc.querySelector('[data-home-page]')?.textContent || '';
const rail = (doc, title) => doc.querySelector(`[data-rail-panel="${title}"]`);
const homeButtons = doc => [...doc.querySelectorAll('[data-home-button], [data-rail-home], button[aria-label="Home"]')];
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};

test('ArchHub opens on the Home page, not inside the current graph', async () => {
  const studio = await mountStudio({home:true});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'the first screen is the Home page');
    assert.equal(studio.doc.querySelectorAll('[data-node-id]').length, 0, 'no graph canvas is open at boot');
    const tab = [...studio.doc.querySelectorAll('button, [role="tab"]')].find(node => /ArchHub/.test(node.textContent));
    assert.ok(tab, 'the current graph stays one click away');
    studio.flush(() => tab.click());
    await studio.settle(() => studio.doc.querySelector('[data-node-id]'), 'the retained graph opens from Home');
    assert.ok(studio.doc.querySelector('[data-ws-tab="graph-a"]'), 'the graph session header is shown');
  } finally { studio.close(); }
});

test('Home boot shows the default free router with its friendly name', async () => {
  const studio = await mountStudio({home:true});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-home-page]') && homeText(studio.doc).includes(MODEL),
      'Home shows the default free router label');
    assert.ok(homeComposer(studio.doc), 'the real Home composer is mounted');
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null, 'Home is not in the no-model state');
    assert.doesNotMatch(homeText(studio.doc), /openrouter\/free/);
  } finally { studio.close(); }
});

test('Home Library tabs open beside Home and Home collapses the frame left panel', async () => {
  const studio = await mountStudio({home:true});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home is visible');
    assert.equal(studio.doc.querySelector('[data-left-panel]'), null, 'Home mounts with no empty left panel');
    assert.equal(rail(studio.doc, 'Skills'), null, 'Skills moved from the rail into Library');
    assert.equal(rail(studio.doc, 'Search'), null, 'Search moved from the rail into Library');
    for (const [title, visible] of [
      ['Library', () => studio.doc.querySelector('input[placeholder^="Search"]')],
      ['Skills', () => studio.doc.body.textContent.includes('Search saved skills')],
      ['Search', () => studio.doc.body.textContent.includes('Search everything')],
    ]) {
      studio.flush(() => rail(studio.doc, 'Library').click());
      if (title !== 'Library') studio.flush(() => studio.doc.querySelector('[data-library-tab="' + title.toLowerCase() + '"]').click());
      await studio.settle(() => studio.doc.querySelector('[data-home-page]') &&
        visible(), title + ' panel opens beside Home');
      assert.equal(studio.doc.querySelectorAll('[data-node-id]').length, 0, title + ' does not open a graph');
      assert.ok(studio.doc.querySelector('[data-left-panel]'), title + ' occupies the one left panel');
      const panelHome = homeButtons(studio.doc).find(node => node.textContent.trim() === 'Home') || studio.doc.querySelector('[data-rail-home]');
      assert.ok(panelHome, title + ' panel exposes Home');
      studio.flush(() => panelHome.click());
      await studio.settle(() => studio.doc.querySelector('[data-home-page]') &&
        !visible() && !studio.doc.querySelector('[data-left-panel]'), title + ' panel closes back to Home');
    }
  } finally { studio.close(); }
});

test('Home wins over a deferred graph open started from the Home session list', async () => {
  const graphOpen = deferred();
  const studio = await mountStudio({home:true, graphOpen:async () => graphOpen.promise});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home is visible');
    const tab = [...studio.doc.querySelectorAll('button, [role="tab"]')].find(node => /ArchHub/.test(node.textContent));
    studio.flush(() => tab.click());
    studio.flush(() => rail(studio.doc, 'Library').click());
    await studio.settle(() => studio.doc.querySelector('input[placeholder^="Search"]'),
      'Library panel opens while graph waits');
    const panelHome = homeButtons(studio.doc).find(node => node.textContent.trim() === 'Home') || studio.doc.querySelector('[data-rail-home]');
    studio.flush(() => panelHome.click());
    graphOpen.resolve({ok:true, current_graph:'graph-a'});
    await new Promise(resolve => studio.win.setTimeout(resolve, 0));
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home remains visible after graph-open resolves');
    assert.notEqual(studio.doc.querySelector('[data-ws-tab="graph-a"]')?.getAttribute('aria-current'), 'true',
      'the graph session tab is not active');
    assert.equal(studio.doc.querySelectorAll('[data-node-id]').length, 0, 'no graph nodes render');
  } finally { studio.close(); }
});

test('Settings System open respects a labelled Home click while graph open is pending', async () => {
  const graphOpen = deferred();
  const studio = await mountStudio({systemView:true});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-node-id]'), 'graph starts open');
    studio.win.ARCHHUB_GRAPH_OPEN = async () => graphOpen.promise;
    studio.flush(() => rail(studio.doc, 'Settings').click());
    await studio.settle(() => studio.doc.querySelector('[aria-label="Settings"]'), 'Settings opens');
    const nav = settingsNavigator({doc:studio.doc, flush:studio.flush, settle:async () => { await new Promise(resolve => studio.win.setTimeout(resolve, 0)); }});
    const systemTab = await nav.capability('System');
    assert.ok(systemTab, 'the gated System graph action is still mounted for Settings behavior');
    studio.flush(() => systemTab.click());
    await studio.settle(() => button(studio.doc, 'Open the System graph'), 'System tab opens');
    studio.flush(() => button(studio.doc, 'Open the System graph').click());
    await studio.settle(() => studio.doc.querySelector('[aria-label="Settings"]') &&
      homeButtons(studio.doc).some(node => node.textContent.trim() === 'Home'), 'Settings stays open while pending and labelled Home is reachable');
    const labelledHome = homeButtons(studio.doc).find(node => node.textContent.trim() === 'Home');
    studio.flush(() => labelledHome.click());
    graphOpen.resolve({ok:true, current_graph:'graph-a'});
    await new Promise(resolve => studio.win.setTimeout(resolve, 0));
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home remains visible');
    assert.notEqual(studio.doc.querySelector('[data-ws-tab="graph-a"]')?.getAttribute('aria-current'), 'true',
      'no session tab is active after Home wins');
    assert.equal(studio.doc.querySelectorAll('[data-node-id]').length, 0, 'the graph canvas stays closed');
  } finally { studio.close(); }
});

test('Settings System labelled Home lands on Home with no active session tab', async () => {
  const studio = await mountStudio({systemView:true});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-node-id]'), 'graph starts open');
    studio.flush(() => rail(studio.doc, 'Settings').click());
    await studio.settle(() => studio.doc.querySelector('[aria-label="Settings"]'), 'Settings opens');
    const nav = settingsNavigator({doc:studio.doc, flush:studio.flush, settle:async () => { await new Promise(resolve => studio.win.setTimeout(resolve, 0)); }});
    const systemTab = await nav.capability('System');
    assert.ok(systemTab, 'the gated System graph action is still mounted for Settings behavior');
    studio.flush(() => systemTab.click());
    await studio.settle(() => button(studio.doc, 'Open the System graph'), 'System tab opens');
    studio.flush(() => button(studio.doc, 'Open the System graph').click());
    await studio.settle(() => studio.doc.querySelector('[data-system-header]'), 'System graph header is visible');
    const labelledHome = [...studio.doc.querySelectorAll('[data-system-header] button')]
      .find(node => node.getAttribute('aria-label') === 'Home' && node.textContent.trim() === 'Home');
    assert.ok(labelledHome, 'System graph exposes the labelled Home control');
    studio.flush(() => labelledHome.click());
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'Home page is visible');
    assert.equal(studio.doc.querySelector('[data-ws-tab][aria-current="true"]'), null, 'no session tab is active');
    assert.equal(studio.doc.querySelector('[data-system-header]'), null, 'System graph is closed');
  } finally { studio.close(); }
});

test('Home boot auto-retries a rejected model read and clears without a click', async () => {
  let reads = 0;
  const studio = await mountStudio({home:true, models:() => {
    reads += 1;
    if (reads === 1) return Promise.reject(new Error('network down'));
    return undefined;
  }, modelRetryDelaysMs:[10, 20, 30]});
  try {
    await studio.settle(() => homeText(studio.doc).includes('Models unavailable · retrying…'),
      'Home shows the rejected read as retrying');
    await studio.settle(() => homeText(studio.doc).includes(MODEL),
      'Home automatic retry reads the model list again');
    assert.ok(reads >= 2, 'the model read was retried without a click');
    assert.doesNotMatch(homeText(studio.doc), /Models unavailable · retrying…/);
  } finally { studio.close(); }
});

test('Home boot sends through the free default route while the model read is unknown', async () => {
  const studio = await mountStudio({home:true, models:() => Promise.reject(new Error('network down')), modelRetryDelaysMs:[5000]});
  try {
    await studio.settle(() => homeText(studio.doc).includes('Models unavailable · retrying…'),
      'Home shows the rejected read as retrying');
    const input = homeComposer(studio.doc);
    studio.type(input, 'ping while checking');
    studio.flush(() => button(studio.doc, 'Send').click());
    await studio.settle(() => studio.startCalls.length === 1, 'Home sends while the model read is unknown');
    assert.deepEqual(studio.startCalls.map(call => [call.prompt, call.model]), [['ping while checking', ROUTE]]);
    assert.equal(studio.doc.querySelector('[data-picker-options]'), null, 'Send does not open the picker while unknown');
  } finally { studio.close(); }
});

test('Home boot shows one Models unavailable retry line while the model read is unknown', async () => {
  const studio = await mountStudio({home:true, models:() => Promise.reject(new Error('network down')), modelRetryDelaysMs:[5000]});
  try {
    await studio.settle(() => homeText(studio.doc).includes('Models unavailable · retrying…'),
      'Home shows the rejected read as retrying');
    const count = (homeText(studio.doc).match(/Models unavailable · retrying…/g) || []).length;
    assert.equal(count, 1);
    assert.equal(button(studio.doc, 'Retry')?.textContent.trim(), 'Retry');
    assert.doesNotMatch(homeText(studio.doc), /Model unknown|Models could not be read|UNKNOWN/);
  } finally { studio.close(); }
});

test('Home boot bounds a non-OK model read as unknown', async () => {
  const studio = await mountStudio({home:true, models:{http:true, ok:false, status:503, body:{ok:false}}});
  try {
    await studio.settle(() => homeText(studio.doc).includes('Models unavailable · retrying…'),
      'Home bounds the non-OK read as unknown');
    assert.equal(button(studio.doc, 'Retry')?.textContent.trim(), 'Retry');
    assert.equal(button(studio.doc, 'Sign in'), undefined);
    assert.equal(button(studio.doc, 'Choose a model'), undefined);
  } finally { studio.close(); }
});

test('Home boot bounds a timed-out model read as unknown', async () => {
  const studio = await mountStudio({home:true, models:{never:true}, modelReadTimeoutMs:20});
  try {
    await studio.settle(() => homeText(studio.doc).includes('Models unavailable · retrying…'),
      'Home bounds the timed-out read as unknown');
    assert.equal(button(studio.doc, 'Retry')?.textContent.trim(), 'Retry');
    assert.equal(button(studio.doc, 'Sign in'), undefined);
    assert.equal(button(studio.doc, 'Choose a model'), undefined);
  } finally { studio.close(); }
});

test('Home boot shows Choose a model only after a real negative answer', async () => {
  const studio = await mountStudio({home:true, models:{ok:true, groups:[], selected_route:'', default_route:'',
    readiness:{state:'no_model', route:'', actions:['sign_in', 'choose_model'],
      message:'No model yet. Sign in to ArchHub, or choose a model.',
      families:{}, messages:{no_model:'No model yet. Sign in to ArchHub, or choose a model.'}}}});
  try {
    await studio.settle(() => homeText(studio.doc).includes('Choose a model'), 'Home shows the no-model answer');
    assert.match(homeText(studio.doc), /No model yet/);
    assert.ok(homeComposer(studio.doc), 'the real Home composer remains mounted');
  } finally { studio.close(); }
});

test('graph composer auto-retries a rejected model read and clears without a click', async () => {
  let reads = 0;
  const studio = await mountStudio({models:() => {
    reads += 1;
    if (reads === 1) return Promise.reject(new Error('network down'));
    return undefined;
  }, modelRetryDelaysMs:[10, 20, 30]});
  try {
    await studio.settle(() => studio.doc.body.textContent.includes('Models unavailable · retrying…'),
      'the rejected read is shown as retrying');
    await studio.settle(() => modelIndicators(studio.doc).some(node => node.textContent.includes(MODEL)),
      'the automatic retry reads the model list again');
    assert.ok(reads >= 2, 'the model read was retried without a click');
    assert.equal(noModelCard(studio.doc), null);
  } finally { studio.close(); }
});

test('graph composer sends through the free default route while the model read is unknown', async () => {
  const studio = await mountStudio({models:() => Promise.reject(new Error('network down')), modelRetryDelaysMs:[5000]});
  try {
    await studio.settle(() => studio.doc.body.textContent.includes('Models unavailable · retrying…'),
      'the rejected read is shown as retrying');
    const input = studio.doc.querySelector('input[aria-label="Ask selection"]');
    studio.type(input, 'ping while checking');
    studio.flush(() => button(studio.doc, 'Send').click());
    await studio.settle(() => studio.agentCalls.length === 1, 'the message is sent while the model read is unknown');
    assert.deepEqual(studio.agentCalls.map(call => [call.text, call.route]), [['ping while checking', ROUTE]]);
    assert.equal(studio.doc.querySelector('[data-picker-options]'), null, 'Send does not open the picker while unknown');
  } finally { studio.close(); }
});

test('graph composer shows one Models unavailable retry line while the model read is unknown', async () => {
  const studio = await mountStudio({models:() => Promise.reject(new Error('network down')), modelRetryDelaysMs:[5000]});
  try {
    await studio.settle(() => studio.doc.body.textContent.includes('Models unavailable · retrying…'),
      'the rejected read is shown as retrying');
    const count = (studio.doc.body.textContent.match(/Models unavailable · retrying…/g) || []).length;
    assert.equal(count, 1);
    assert.doesNotMatch(studio.doc.body.textContent, /Model unknown|Models could not be read|UNKNOWN/);
  } finally { studio.close(); }
});

test('graph composer bounds a non-OK model read as unknown', async () => {
  const studio = await mountStudio({models:{http:true, ok:false, status:503, body:{ok:false}}});
  try {
    await studio.settle(() => studio.doc.body.textContent.includes('Models unavailable · retrying…'),
      'the non-OK read is bounded as unknown');
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.equal(button(card, 'Retry')?.textContent.trim(), 'Retry');
    assert.equal(button(card, 'Sign in'), undefined);
    assert.equal(button(card, 'Choose a model'), undefined);
  } finally { studio.close(); }
});

test('graph composer bounds a timed-out model read as unknown', async () => {
  const studio = await mountStudio({models:{never:true}, modelReadTimeoutMs:20});
  try {
    await studio.settle(() => studio.doc.body.textContent.includes('Models unavailable · retrying…'),
      'the timed-out read is bounded as unknown');
    const card = studio.doc.querySelector('[data-chat-no-model]');
    assert.equal(button(card, 'Retry')?.textContent.trim(), 'Retry');
    assert.equal(button(card, 'Sign in'), undefined);
    assert.equal(button(card, 'Choose a model'), undefined);
  } finally { studio.close(); }
});

test('graph composer keeps model and readiness quiet until the first server answer', async () => {
  const models = deferred();
  const studio = await mountStudio({models:() => models.promise, selectedTitleLeak:'out \u2192 in'});
  try {
    const pendingHadNoCard = studio.doc.querySelector('[data-chat-no-model]') === null;
    const pendingHadNoChoose = button(studio.doc, 'Choose a model') === undefined;
    const pendingHadNoLeak = modelIndicators(studio.doc)
      .every(indicator => !/Choose a model|\bout\b|\bin\b/.test(indicator.textContent));
    models.resolve({ok:true, selected_route:'', default_route:ROUTE, default_source:'free · OpenRouter',
      default_model:{name:MODEL, route:ROUTE, routed:ROUTE, vendor:'OpenRouter', tag:'FREE', ctx:'', col:'#3a6acc', latency:null},
      readiness:{state:'ready', route:ROUTE, actions:[], families:{openrouter:{state:'ready', message:'', actions:[]}}, messages:{}},
      groups:[]});
    await studio.settle(() => modelIndicators(studio.doc).some(node => node.textContent.includes(MODEL)),
      'the default model label appears after the server answer');
    assert.equal(pendingHadNoCard, true, 'no no-model card is drawn before readiness answers');
    assert.equal(pendingHadNoChoose, true, 'no model CTA is drawn before readiness answers');
    assert.equal(pendingHadNoLeak, true, 'the pending chip has no Choose a model or out/in labels');
    assert.doesNotMatch(modelIndicators(studio.doc)[0].textContent, /\bout\b|\bin\b/);
  } finally { studio.close(); }
});

test('graph composer shows the no-model line only after a real negative answer', async () => {
  const studio = await mountStudio({models:{ok:true, groups:[], selected_route:'', default_route:'',
    readiness:{state:'no_model', route:'', actions:['sign_in', 'choose_model'],
      message:'No model yet. Sign in to ArchHub, or choose a model.',
      families:{}, messages:{no_model:'No model yet. Sign in to ArchHub, or choose a model.'}}}});
  try {
    await studio.settle(() => studio.doc.querySelector('[data-chat-no-model]'), 'the negative answer is shown');
    assert.match(studio.doc.querySelector('[data-chat-no-model]').textContent, /No model yet/);
  } finally { studio.close(); }
});

test('graph composer preselects the free router with its friendly name', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(() => modelIndicators(studio.doc).some(node => node.textContent.includes(MODEL)),
      'the first screen shows the default free router label');
    assert.equal(modelIndicators(studio.doc).length, 1, 'the first screen has one model indicator');
    assert.match(modelIndicators(studio.doc)[0].textContent, /Free Models Router/);
    assert.doesNotMatch(modelIndicators(studio.doc)[0].textContent, /openrouter\/free/);
    assert.equal(studio.doc.querySelector('[data-chat-no-model]'), null, 'the default free route is selected, not the no-model state');
    const inputs = [...studio.doc.querySelectorAll('input[aria-label="Ask selection"]')];
    assert.equal(inputs.length, 1,
      'CORE-C moved the first-screen composer into the right selection panel; exactly one real composer is mounted');
    const panel = studio.doc.querySelector('aside[aria-label="Selection inspector"]');
    assert.ok(panel && panel.contains(inputs[0]), 'the real single composer lives in the selection panel');
    const input = inputs[0];
    studio.type(input, 'ping');
    studio.flush(() => button(studio.doc, 'Send').click());
    await studio.settle(() => studio.doc.body.textContent.includes('PONG'), 'the chat answer is drawn');
    assert.deepEqual(studio.agentCalls.map(call => [call.text, call.route]), [['ping', ROUTE]]);
    assert.ok([...studio.doc.querySelectorAll('[data-chat-turn="message"] span')].some(node => node.textContent === MODEL),
      'the answer turn (UX-CHAT1: in the Conversation section) is signed with the friendly model label');
  } finally { studio.close(); }
});

 test('RELGATEFIX Workshop Settings System opens its graph and labelled Home returns in one click', async () => {
  const studio = await mountStudio({systemView:true});
  try {
    await studio.settle(() => rail(studio.doc, 'Workshop'), 'current rail mounts');
    studio.flush(() => rail(studio.doc, 'Workshop').click());
    await studio.settle(() => studio.doc.querySelector('[data-workshop72-rail]'), 'Workshop opens');
    studio.flush(() => studio.doc.querySelector('[data-workshop72-rail] [aria-label="Settings"]').click());
    await studio.settle(() => button(studio.doc, 'Open the System graph'), 'Settings System action is visible');
    assert.equal(button(studio.doc, 'Open the System graph').disabled, false);
    studio.flush(() => button(studio.doc, 'Open the System graph').click());
    await studio.settle(() => studio.doc.querySelector('[data-system-header]'), 'real System graph opens');
    const home = studio.doc.querySelector('[data-system-header] button[aria-label="Home"]');
    assert.equal(home.textContent.trim(), 'Home');
    studio.flush(() => home.click());
    await studio.settle(() => studio.doc.querySelector('[data-home-page]'), 'labelled Home returns in one click');
    assert.equal(studio.doc.querySelector('[data-system-header]'), null);
    assert.equal(studio.doc.querySelectorAll('[data-app-rail]').length, 1);
  } finally { studio.close(); }
});
