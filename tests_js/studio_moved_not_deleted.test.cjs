const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {VirtualConsole} = require('jsdom');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));
const freeRoute = 'qwen/qwen3.8-27b:free';

const aiNode = () => ({
  id:'ai_intent', cat:'ai', title:'Conversation', sub:'Qwen', x:40, y:60, w:260, h:160,
  live:true, application:false, has_conversation:true,
  params:[
    {k:'model', label:'model', v:freeRoute, type:'text', page:'Model'},
  ],
  ins:[], outs:[], ports:{ins:[], outs:[]}, messages:[],
});
const systemNode = {id:'system-registry', cat:'logic', title:'System registry', x:80, y:80, w:220, h:120,
  live:true, application:true, params:[], ins:[], outs:[], ports:{ins:[], outs:[]}};

async function mountStudio({home = false, systemAllowed = true,
  workshopSystemAllowed = systemAllowed, signedAuthority = true} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const virtualConsole = new VirtualConsole();
  const navigationErrors = [];
  virtualConsole.on('jsdomError', error => {
    if (/Not implemented: navigation/.test(String(error?.message || error))) navigationErrors.push(String(error.message || error));
  });
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53921/', runScripts:'outside-only',
    pretendToBeVisual:true, virtualConsole});
  const win = dom.window;
  const calls = {agent:[], modelSelect:[], setModel:[], setProp:[], open:[], refresh:0};
  const auth = {subject:'owner-a', session:'view-a', system_view:systemAllowed};
  const workshopAuth = {subject:'owner-a', session:'view-a', system_view:workshopSystemAllowed};
  let graph = {nodes:[aiNode(), systemNode], wires:[]};
  let topologyCanvas = {application_root:'app:archhub', revision:7, authorization:auth,
    scope:{current:'scope-a', current_label:'Workspace', trail:[{root:'scope-a', label:'Workspace'}]},
    interaction_projection:{revision:7, bindings:[]}, nodes:[], wires:[]};
  const snapshot = {
    canvas:{graph_id:'app:archhub', application_root:'app:archhub', root:'scope-a', revision:7, authorization:workshopAuth,
      configuration:{model_defaults:{temperature:0.7, 'top-p':0.95, 'max tokens':4096}}},
    workshops:[], applicationUpdate:{state:'idle', current_build:'b1'},
    selected:'ai_intent',
    topology:{canvas:topologyCanvas, graph, selected:'ai_intent'},
  };
  const listeners = new Set();
  const notify = () => listeners.forEach(listener => listener());
  win.fetch = url => String(url).startsWith('/api/universal/models')
    ? Promise.resolve({ok:true, json:async () => ({ok:true, selected_route:freeRoute, groups:[{name:'BYO', items:[
      {name:'Qwen free', route:freeRoute, routed:freeRoute, vendor:'qwen', tag:'BYO', cost:'$0 / $0 per M'},
    ]}]})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:async () => ({ok:true, tools:[]})})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:async () => ({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const signedSnapshot = () => ({...snapshot, graph, topology:{...snapshot.topology, graph}});
  if (signedAuthority) win.ARCHHUB_STUDIO_AUTHORITY = {getSnapshot:signedSnapshot, subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); }, load:async () => {
    calls.refresh += 1;
    snapshot.topology = {...snapshot.topology, graph};
    notify();
    return signedSnapshot();
  }};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    setComposerModel:async (route, generation) => {
      calls.setModel.push([route, generation]);
      snapshot.canvas.configuration.model_defaults = generation;
      return {configuration_state:{composer_model:{value:route}, model_defaults:generation}};
    },
    refreshTopologyCanvas:async () => { calls.refresh += 1; snapshot.topology = {...snapshot.topology, graph}; notify(); return topologyCanvas; },
    refreshConversationCatalog:async () => {}, selectTopology:async id => { snapshot.topology.selected = id; notify(); },
    watchApplicationUpdate:() => () => {},
  };
  win.ARCHHUB_SET_NODE_PROP = async (root, label, value) => {
    calls.setProp.push([root, label, value]);
    graph = {...graph, nodes:graph.nodes.map(node => node.id === root
      ? {...node, params:node.params.map(row => row.k === label || row.label === label ? {...row, v:value} : row)}
      : node)};
    win.ARCHHUB_LIVE.graph = graph;
    if (typeof win.__archhubRefreshCanvasInPlace === 'function') await win.__archhubRefreshCanvasInPlace();
    return {ok:true};
  };
  win.ARCHHUB_AGENT = (promptArg, route, options) => { calls.agent.push([promptArg, route, options]); return new Promise(() => {}); };
  win.ARCHHUB_AGENT_SELECT = async route => { calls.modelSelect.push(route); return route; };
  win.ARCHHUB_GRAPH_OPEN = async id => {
    calls.open.push(id);
    // Like the server: only admitted graphs open; the application root is not one.
    if (id !== 'app:canvas' && id !== 'app:archhub') throw new Error('graph is outside the admitted graph list');
    if (home && id !== 'app:canvas') throw new Error('graph is outside the admitted graph list');
    // Like the server: graph_id is the application root; opening a graph moves the scope root.
    if (id === 'app:canvas') snapshot.canvas.root = id; else snapshot.canvas.graph_id = id;
    topologyCanvas = {...topologyCanvas, application_root:snapshot.canvas.graph_id,
      scope:{...(topologyCanvas.scope || {}), current:snapshot.canvas.root}};
    snapshot.topology = {...snapshot.topology, graph, canvas:topologyCanvas};
    return {ok:true, current_graph:id, graphs:[{id, title:'System', state:'idle', host:'archhub', when:'saved',
      file:'Application graph', last:'2 nodes', model:''}]};
  };
  win.ARCHHUB_LIVE = {sessions:home ? [{id:'app:canvas', title:'ArchHub', state:'idle', file:'Graph composition'}] : [{id:'app:archhub', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:home ? null : 'app:archhub', hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = async () => { for (let i = 0; i < 8; i += 1) { await new Promise(resolve => win.setTimeout(resolve, 5)); win.ReactDOM.flushSync(() => {}); } };
  const flush = action => win.ReactDOM.flushSync(action);
  const close = () => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const button = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const exact = text => [...win.document.querySelectorAll('*')].filter(node => node.textContent === text &&
    ![...node.children].some(child => child.textContent === text));
  const typeInput = (input, text) => flush(() => {
    Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set.call(input, text);
    input.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  const typeTextArea = (textarea, text) => flush(() => {
    Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value').set.call(textarea, text);
    textarea.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  return {win, doc:win.document, calls, navigationErrors, settle, flush, close, button, exact, typeInput, typeTextArea,
    get graph() { return graph; }};
}

test('Settings Models generation values persist through the model owner and reach the next Chat send', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    studio.flush(() => studio.doc.querySelector('[title="Settings"]').click());
    await studio.settle();
    studio.flush(() => [...studio.doc.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Models').click());
    await studio.settle();
    const temperature = studio.doc.querySelector('input[type="range"][aria-label="temperature"]');
    assert.ok(temperature, 'Settings > Models owns the temperature control');
    studio.flush(() => {
      Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set.call(temperature, '0.35');
      temperature.dispatchEvent(new studio.win.Event('input', {bubbles:true}));
    });
    await studio.settle();
    assert.equal(JSON.stringify(studio.calls.setModel.at(-1)), JSON.stringify([freeRoute, {temperature:0.35, 'top-p':0.95, 'max tokens':4096}]),
      'generation defaults persist beside the selected composer model');
    studio.flush(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    await studio.settle();
    const reply = studio.doc.querySelector('input[aria-label="Ask selection"]');
    assert.ok(reply, 'the moved selection composer is available after Settings closes');
    studio.typeInput(reply, 'Use the settings defaults.');
    studio.flush(() => reply.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    const sent = studio.calls.agent.at(-1);
    assert.equal(sent[0], 'Use the settings defaults.');
    assert.equal(sent[1], freeRoute);
    assert.equal(sent[2].node, 'ai_intent');
    assert.equal(typeof sent[2].request_id, 'string');
    assert.ok(sent[2].request_id);
    assert.equal(JSON.stringify(sent[2].generation), JSON.stringify({temperature:0.35, top_p:0.95, max_tokens:4096}));
  } finally { studio.close(); }
});

test('Chat has no SYSTEM PROMPT card; Settings Profile owns the Standing instruction editor', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle();
    assert.equal(studio.exact('SYSTEM PROMPT').length, 0, 'Chat does not render the old decorative SYSTEM PROMPT card');
    studio.flush(() => studio.doc.querySelector('[title="Settings"]').click());
    await studio.settle();
    studio.flush(() => [...studio.doc.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Profile').click());
    await studio.settle();
    assert.ok(studio.exact('STANDING INSTRUCTION').length > 0, 'Settings > Profile shows the Standing instruction editor');
    assert.ok([...studio.doc.querySelectorAll('button')].some(button => button.textContent.trim() === 'edit raw prompt'),
      'Profile editor writes the standing instruction brain fact');
  } finally { studio.close(); }
});

test('Home System follows the old systemAllowed gate, opens in place, and renders the system view', async () => {
  const studio = await mountStudio({home:true, systemAllowed:true, workshopSystemAllowed:false, signedAuthority:false});
  try {
    await studio.settle();
    const home = [...studio.doc.querySelectorAll('button')].find(node => node.title === 'All sessions');
    if (home) { studio.flush(() => home.click()); await studio.settle(); }
    const system = [...studio.doc.querySelectorAll('button')].find(node => node.textContent.includes('System') && node.textContent.includes('Application graph'));
    assert.ok(system, 'System is a Home session row');
    studio.flush(() => system.click());
    await studio.settle();
    assert.deepEqual(studio.calls.open, ['app:canvas'], 'System opens the admitted root graph, never the application root');
    assert.equal(studio.doc.body.textContent.includes('outside the admitted graph list'), false, 'no refusal on the Home card');
    assert.equal(studio.navigationErrors.length, 0, 'System opening does not reload the page');
    assert.ok(studio.doc.querySelector('.lm-node[data-node-id="system-registry"]'), 'the System view renders application nodes');
    assert.equal(!!studio.doc.querySelector('.lm-node[data-node-id="ai_intent"]'), false, 'the System view hides user nodes');
  } finally { studio.close(); }
});

test('Home hides the System session when the old systemAllowed gate is false', async () => {
  const studio = await mountStudio({home:true, systemAllowed:false});
  try {
    await studio.settle();
    const system = [...studio.doc.querySelectorAll('button')].find(node => node.textContent.includes('System'));
    assert.equal(!!system, false, 'System is not a Home session row');
  } finally { studio.close(); }
});
