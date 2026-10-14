const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {VirtualConsole} = require('jsdom');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));
const freeRoute = 'qwen/qwen3.8-27b:free';

const aiNode = () => ({
  id:'ai_intent', cat:'ai', title:'Conversation', sub:'Qwen', x:40, y:60, w:260, h:160,
  live:true, application:false, has_conversation:true,
  params:[{k:'model', label:'model', v:freeRoute, type:'text', page:'Model'}],
  ins:[], outs:[], ports:{ins:[], outs:[]}, messages:[],
});

async function mountStudio(agent) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => {
    if (!/Not implemented: navigation/.test(String(error?.message || error))) throw error;
  });
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53931/', runScripts:'outside-only',
    pretendToBeVisual:true, virtualConsole});
  const win = dom.window;
  const graph = {nodes:[aiNode()], wires:[]};
  const topologyCanvas = {application_root:'app:archhub', revision:7,
    authorization:{subject:'owner-a', session:'view-a', system_view:true},
    scope:{current:'scope-a', current_label:'Workspace', trail:[{root:'scope-a', label:'Workspace'}]},
    interaction_projection:{revision:7, bindings:[]}, nodes:[], wires:[]};
  const snapshot = {
    canvas:{graph_id:'app:archhub', application_root:'app:archhub', root:'scope-a', revision:7,
      authorization:{subject:'owner-a', session:'view-a', system_view:true}},
    workshops:[], applicationUpdate:{state:'idle', current_build:'b1'}, selected:'ai_intent',
    topology:{canvas:topologyCanvas, graph, selected:'ai_intent'},
  };
  const listeners = new Set();
  win.fetch = url => String(url).startsWith('/api/universal/models')
    ? Promise.resolve({ok:true, json:async () => ({ok:true, selected_route:freeRoute, groups:[{name:'BYO', items:[
      {name:'Qwen free', route:freeRoute, routed:freeRoute, vendor:'qwen', tag:'BYO', cost:'$0 / $0 per M'},
    ]}]})})
    : String(url) === '/tools' ? Promise.resolve({ok:true, json:async () => ({ok:true, tools:[]})})
    : String(url) === '/waiting' ? Promise.resolve({ok:true, json:async () => ({ok:true, items:[]})})
    : new Promise(() => {});
  Object.defineProperty(win, 'crypto', {configurable:true, value:{randomUUID:(() => {
    const ids = ['id-X', 'id-Y', 'id-Z'];
    return () => ids.shift() || 'id-extra';
  })()}});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_STUDIO_AUTHORITY = {getSnapshot:() => snapshot, subscribe:listener => {
    listeners.add(listener); return () => listeners.delete(listener);
  }, load:async () => snapshot, select:async id => {
    snapshot.selected = id; snapshot.topology.selected = id; listeners.forEach(listener => listener());
  }};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot, subscribe:listener => { listeners.add(listener); return () => listeners.delete(listener); },
    refreshTopologyCanvas:async () => topologyCanvas, refreshConversationCatalog:async () => {},
    selectTopology:async id => { snapshot.topology.selected = id; listeners.forEach(listener => listener()); },
    watchApplicationUpdate:() => () => {},
  };
  win.ARCHHUB_AGENT = agent;
  win.ARCHHUB_AGENT_SELECT = async route => route;
  win.ARCHHUB_LIVE = {sessions:[{id:'app:archhub', title:'ArchHub', state:'idle', file:'Graph composition'}],
    currentGraph:'app:archhub', hosts:[], connectors:[], graph, memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:win.ARCHHUB_LIVE.currentGraph};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = async () => { for (let i = 0; i < 8; i += 1) { await new Promise(resolve => win.setTimeout(resolve, 5)); win.ReactDOM.flushSync(() => {}); } };
  const flush = action => win.ReactDOM.flushSync(action);
  const type = (input, text) => flush(() => {
    Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set.call(input, text);
    input.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  const button = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const composer = () => win.document.querySelector('input[aria-label="Ask selection"]');
  return {win, doc:win.document, settle, flush, type, button, composer,
    close:() => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } }};
}

test('a retry after a lost node reply reuses the same request_id until a confirmed reply', async () => {
  const calls = [];
  let mode = 'lost';
  const studio = await mountStudio(async (prompt, route, options) => {
    calls.push({prompt, route, options});
    if (mode === 'lost') return {ok:true, answer:'reply not confirmed - check before sending again',
      delivery:{state:'reply_not_confirmed', request_id:options.request_id, message_id:'message-a'}};
    return {ok:true, answer:'confirmed reply',
      delivery:{state:'replied', request_id:options.request_id, message_id:'message-a', reply_message_id:'reply-a'}};
  });
  try {
    await studio.settle();
    const canvas = studio.button('Canvas');
    if (canvas) studio.flush(() => canvas.click());
    await studio.settle();
    const input = studio.composer();
    assert.ok(input, 'the selected AI node owns the selection ask field');
    studio.type(input, 'still-present text');
    studio.flush(() => studio.button('Send').click());
    await studio.settle();
    assert.equal(studio.composer().value, 'still-present text', 'lost replies leave the typed text present');
    assert.ok(studio.doc.body.textContent.includes('reply not confirmed - check before sending again'),
      'lost replies show the plain not-confirmed line');
    studio.flush(() => studio.button('Send').click());
    await studio.settle();
    mode = 'ok';
    studio.flush(() => studio.button('Send').click());
    await studio.settle();
    const next = studio.composer();
    studio.type(next, 'next send');
    studio.flush(() => studio.button('Send').click());
    await studio.settle();
    assert.deepEqual(calls.map(call => call.options.request_id), ['id-X', 'id-X', 'id-X', 'id-Y']);
  } finally { studio.close(); }
});

test('inspector composer renders ok false as an error turn with retry and same request_id', async () => {
  const calls = [];
  let mode = 'refused';
  const studio = await mountStudio(async (prompt, route, options) => {
    calls.push({prompt, route, options});
    if (mode === 'refused') return {ok:false, error:'OpenRouter refused this request: HTTP 429'};
    return {ok:true, answer:'confirmed reply',
      delivery:{state:'replied', request_id:options.request_id, message_id:'message-a', reply_message_id:'reply-a'}};
  });
  try {
    await studio.settle();
    const canvas = studio.button('Canvas');
    if (canvas) studio.flush(() => canvas.click());
    await studio.settle();
    const input = studio.composer();
    studio.type(input, 'will fail once');
    studio.flush(() => studio.button('Send').click());
    await studio.settle();
    const turns = [...studio.doc.querySelectorAll('[data-chat-turn]')];
    assert.ok(turns.some(turn => turn.textContent.includes('The reply did not arrive: OpenRouter refused this request: HTTP 429')),
      'ok false is visible in the inspector transcript');
    assert.ok(studio.doc.body.textContent.includes('Retry'), 'visible retry is offered');
    assert.equal(studio.composer().value, 'will fail once');
    mode = 'ok';
    studio.flush(() => studio.button('Retry').click());
    await studio.settle();
    assert.deepEqual(calls.map(call => call.options.request_id), ['id-X', 'id-X']);
  } finally { studio.close(); }
});
