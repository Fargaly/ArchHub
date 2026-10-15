const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {VirtualConsole} = require('jsdom');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function canvas(grouped = false) {
  return {ok:true, revision:21, graph_id:'graph-a', root:'graph-a', application_root:'app:archhub', canvas_root:'app:canvas',
    selected:null, selection:[], selected_title:'Graph Alpha',
    scope:{current:'graph-a', current_label:'Graph Alpha', trail:[{root:'app:canvas', label:'Canvas'}, {root:'graph-a', label:'Graph Alpha'}]},
    authorization:{subject:'owner-a', session:'view-a', system_view:true}, configuration:{theme:{...seed}},
    nodes:grouped ? [{id:'group-a', label:'Workshop', composition:true, engine:'engine:composition',
      x:350, y:60, member_count:2, members:[{id:'a', title:'Sketch Lines'}, {id:'b', title:'Line Watcher'}]}]
      : [{id:'a', label:'Sketch Lines', engine:'vision.sketch_lines', x:40, y:60},
        {id:'b', label:'Line Watcher', engine:'lines.watch', x:400, y:60}],
    wires:[], catalog:[], workshops:[], action_history:{can_undo:false, can_redo:false},
    interaction_projection:{revision:21, lifecycle:'wip', bindings:[{control:'app:control:canvas:remove-member',
      interaction:'remove-action', event:'drop', acknowledgement_mode:'receipt-v1', projection_mode:'topology-delta-v1'}]},
    workshop_scope:{graph_id:'app:archhub', root:'graph-a', revision:21, workshops:[], unavailable:'No Workshop is attached to this graph.'}};
}
function projectCanvas(held) {
  return {nodes:held.nodes.map(n => ({...n, title:n.label || n.title || n.id, cat:n.composition ? 'group' : 'logic',
    sub:n.engine || 'Graph node', kind:n.composition ? 'group' : '', live:true, group:n.group || '',
    memberCount:n.member_count, w:n.composition ? 260 : 210, h:120, params:[], ins:[], outs:[], messages:[],
    ports:{ins:[], outs:[]}})), wires:held.wires};
}

// This mounts the compiled, unmodified Studio tree, including the real composer,
// conversation listener, inspector, canvas, member chips, and keyboard handler.
// Only the host responses are fake; no installed application or service is used.
async function mountStudio({grouped = false, delayedSelection = false, realAuthority = false, retainedFocus = false, normalTransport = false, agent, transcriptRows, modelCatalogue} = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  for (const source of ['studio-lm.jsx']) {
    const entry = manifest.files.find(file => file.source === source);
    const hash = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio', source))).digest('hex');
    assert.equal(entry?.source_sha256, hash, 'Studio build is stale: run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => {
    if (!/Not implemented: navigation/.test(String(error?.message || error))) throw error;
  });
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only',
    pretendToBeVisual:true, virtualConsole});
  const win = dom.window, doc = win.document;
  Object.defineProperty(win.HTMLElement.prototype, 'offsetWidth', {configurable:true, get() { return 240; }});
  Object.defineProperty(win.HTMLElement.prototype, 'offsetHeight', {configurable:true, get() { return 120; }});
  win.HTMLElement.prototype.getBoundingClientRect = function() {
    return this.getAttribute('role') === 'region' && this.getAttribute('aria-label') === 'Workflow canvas'
      ? {width:1000, height:760, left:0, top:0, right:1000, bottom:760}
      : {width:240, height:120, left:0, top:0, right:240, bottom:120};
  };
  let durable = canvas(grouped), removed = false;
  if (retainedFocus) durable = {...durable, selected:'b', selection:[]};
  const readHostCanvas = () => plain({...durable,
    interaction_projection:{...durable.interaction_projection, revision:durable.revision},
    workshop_scope:{...durable.workshop_scope, revision:durable.revision}});
  const original = plain(durable), calls = {agent:[], posts:[], history:[], selection:[]};
  win.fetch = async url => ({ok:true, json:async () => String(url).includes('/api/universal/models')
    ? modelCatalogue || {ok:true, groups:[], selected_route:'openrouter/free', readiness:{state:'ready'}}
    : String(url) === '/tools' ? {ok:true, tools:[]} : String(url) === '/waiting' ? {ok:true, items:[]} : {ok:true}});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.alert = () => {};
  win.eval(read('nodelang/studio/studio-authority.js'));
  win.eval(read('nodelang/studio/studio-existing-workshop.js'));
  const hostHistory = operation => {
    calls.history.push(operation);
    assert.equal(operation, removed ? 'undo' : 'redo');
    const revision = durable.revision + 1;
    if (operation === 'undo') {
      durable = {...plain(original), revision, action_history:{can_undo:false, can_redo:true}};
      removed = false;
    } else {
      durable = {...durable, revision, action_history:{can_undo:true, can_redo:false}, nodes:[
        {...original.nodes[0], member_count:1, members:[{id:'a', title:'Sketch Lines'}]},
        {id:'b', label:'Line Watcher', engine:'lines.watch', x:700, y:300, group:''}]};
      removed = true;
    }
    return readHostCanvas();
  };
  const post = async (url, body) => {
    calls.posts.push({url, body:plain(body)});
    if (url === '/api/universal/focus') {
      durable = {...durable, revision:durable.revision + 1, selected:body.primary_root, selection:[...body.selected_roots]};
      return readHostCanvas();
    }
    if (url === '/api/universal/gesture') {
      if (body.undo || body.redo) {
        assert.equal(body.expected_scope, 'graph-a');
        return hostHistory(body.redo ? 'redo' : 'undo');
      }
      durable = {...durable, revision:durable.revision + 1, selected:body.focus || durable.selected || null, selection:body.roots || []};
      return readHostCanvas();
    }
    assert.equal(url, '/api/universal/interaction');
    assert.deepEqual(body.membership && {member:body.membership.member, from_group:body.membership.from_group,
      to_group:body.membership.to_group}, {member:'b', from_group:'group-a', to_group:''});
    const base = durable.revision;
    removed = true;
    durable = {...durable, revision:base + 1, action_history:{can_undo:true, can_redo:false}, nodes:[
      {...durable.nodes.find(n => n.id === 'group-a'), member_count:1, members:[{id:'a', title:'Sketch Lines'}]},
      {id:'b', label:'Line Watcher', engine:'lines.watch', group:'', ...body.membership.position}]};
    return {ok:true, projection_mode:'receipt-v1', base_revision:base, committed_revision:durable.revision};
  };
  const existing = win.ARCHHUB_EXISTING_WORKSHOP = win.ArchHubExistingWorkshop.create({
    get:async () => readHostCanvas(), post, projectCanvas});
  existing.setTopologyCanvas(readHostCanvas());
  const signedListeners = new Set(), selectionGates = [];
  let signedOverride = null;
  const signedSnapshot = () => signedOverride || {...readHostCanvas(), canvas:readHostCanvas(), graph:projectCanvas(durable), pending:false, workshops:[]};
  const publishSigned = value => {
    signedOverride = value;
    win.ReactDOM.flushSync(() => { for (const listener of [...signedListeners]) listener(); });
  };
  if (realAuthority) {
    win.ARCHHUB_STUDIO_AUTHORITY = win.ArchHubStudioAuthority.create({get:async () => readHostCanvas(), post});
    await win.ARCHHUB_STUDIO_AUTHORITY.load();
  } else if (!grouped && !normalTransport) win.ARCHHUB_STUDIO_AUTHORITY = {
    getSnapshot:signedSnapshot,
    subscribe:listener => { signedListeners.add(listener); return () => signedListeners.delete(listener); },
    load:async () => signedSnapshot(),
    select:async (id, roots) => {
      calls.selection.push({id, roots:roots ? [...roots] : roots});
      if (delayedSelection && id) {
        const gate = deferred(); selectionGates.push(gate);
        await gate.promise;
      }
      durable = {...durable, revision:durable.revision + 1, selected:id || null, selection:id ? (roots || [id]) : []};
      signedOverride = null;
      for (const listener of [...signedListeners]) listener();
      return signedSnapshot();
    },
  };
  win.ARCHHUB_HISTORY = async operation => ({ok:true, canvas:hostHistory(operation)});
  win.ARCHHUB_GET_CANVAS = async () => readHostCanvas();
  win.ARCHHUB_AGENT_SELECT = async route => route;
  win.ARCHHUB_WORKSHOP_TRANSCRIPT = async node => ({ok:true, node, rows:plain(transcriptRows?.current || []), has_older:false});
  win.ARCHHUB_AGENT = async (prompt, model, context) => {
    const call = {prompt, model, context:plain(context)};
    calls.agent.push(call);
    return agent ? agent(call, calls.agent.length) : {ok:true, answer:'Reply', delivery:{state:'replied'}};
  };
  const graphRow = {id:'graph-a', title:'Graph Alpha', state:'idle', host:'archhub', when:'saved', file:'Graph composition', last:'2 nodes', model:''};
  win.ARCHHUB_LIVE = {sessions:[graphRow], currentGraph:'graph-a', hosts:[], connectors:[],
    graph:projectCanvas(durable), memory:[], skills:[]};
  win.ARCHHUB_BOOT = {...(win.ARCHHUB_BOOT || {}), open_graph:'graph-a'};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const flush = fn => win.ReactDOM.flushSync(fn);
  const settle = async (ms = 80) => { await new Promise(done => win.setTimeout(done, ms)); };
  const click = node => { assert.ok(node, 'mounted click target exists'); flush(() => node.click()); };
  const input = () => doc.querySelector('input[placeholder="whole graph · @ agent or session"]');
  const type = (node, text) => {
    assert.ok(node, 'actual composer input exists');
    flush(() => { Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set.call(node, text);
      node.dispatchEvent(new win.Event('input', {bubbles:true})); });
  };
  const key = (node, init) => flush(() => node.dispatchEvent(new win.KeyboardEvent('keydown', {bubbles:true, cancelable:true, ...init})));
  const send = text => { type(input(), text); key(input(), {key:'Enter'}); };
  const region = () => doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
  const card = id => doc.querySelector('.lm-node[data-node-id="' + id + '"]');
  const inspector = () => doc.querySelector('aside[aria-label="Selection inspector"]');
  const pointer = (node, type, init) => flush(() => {
    assert.ok(node, 'member drag target exists');
    const event = new win.MouseEvent(type, {bubbles:true, cancelable:true, button:0,
      buttons:type === 'pointerup' ? 0 : 1, ...init});
    for (const [name, value] of Object.entries({pointerId:7, pointerType:'mouse', isPrimary:true}))
      if (!(name in event)) Object.defineProperty(event, name, {value});
    node.dispatchEvent(event);
  });
  const clearBackground = () => {
    const event = type => new win.MouseEvent(type, {button:0, clientX:900, clientY:700, bubbles:true, cancelable:true});
    flush(() => region().dispatchEvent(event('mousedown')));
    flush(() => win.dispatchEvent(event('mouseup')));
    flush(() => region().dispatchEvent(event('click')));
  };
  return {win, doc, calls, input, send, click, type, key, settle, region, card, inspector, pointer, existing, selectionGates, clearBackground,
    staleEmpty:() => {
      const snap = signedSnapshot();
      publishSigned({...snap, selected:'b', pending:false, canvas:{...snap.canvas, selected:'b', selection:[], selection_hidden:false}});
    },
    close:() => { try { flush(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } }};
}

function assertGraph(studio) {
  assert.ok(studio.input(), 'inspector remains GRAPH with its actual whole-graph input');
  assert.match(studio.inspector().textContent, /Graph/);
}
function assertSelectedWithFork(studio) {
  assert.match(studio.inspector().textContent, /Line Watcher/);
  assert.ok([...studio.inspector().querySelectorAll('button')].some(button => /\bfork\b/i.test(button.textContent + ' ' + button.getAttribute('aria-label'))),
    'selected node inspector offers its real Fork button');
  assert.equal(studio.input(), null, 'GRAPH composer has given way to the selected node composer');
}

test('UPD3 TS: mounted GRAPH composer queues the second send at 1 s and replies FIFO without losing either message', async () => {
  const replies = [deferred(), deferred()];
  const studio = await mountStudio({agent:(_call, index) => replies[index - 1].promise});
  try {
    await studio.settle(); assertGraph(studio);
    studio.send('TS first message 51c2');
    await studio.settle(1000);
    assert.equal(studio.calls.agent.length, 1);
    studio.send('TS second message 9e07');
    await studio.settle();
    assert.equal(studio.calls.agent.length, 1, 'second request waits until first reply');
    assert.match(studio.inspector().textContent, /TS first message 51c2/);
    assert.match(studio.inspector().textContent, /TS second message 9e07/);
    const queued = studio.inspector().querySelector('[data-chat-pending="queued"]');
    assert.ok(queued, 'second message has an immediate pending row');
    assert.match(queued.textContent, /pending/i);
    replies[0].resolve({ok:true, answer:'TS first reply 51c2', delivery:{state:'replied'}});
    await studio.settle(160);
    assert.deepEqual(studio.calls.agent.map(call => call.prompt), ['TS first message 51c2', 'TS second message 9e07']);
    assert.equal(studio.calls.agent[0].context.graph, true);
    assert.equal(studio.calls.agent[1].context.graph_id, 'graph-a');
    assert.notEqual(studio.calls.agent[0].context.request_id, studio.calls.agent[1].context.request_id);
    replies[1].resolve({ok:true, answer:'TS second reply 9e07', delivery:{state:'replied'}});
    await studio.settle(160);
    const rows = [...studio.inspector().querySelectorAll('[data-chat-local]')].map(row => row.textContent).join('\n');
    assert.match(rows, /TS first message 51c2[\s\S]*TS first reply 51c2[\s\S]*TS second message 9e07[\s\S]*TS second reply 9e07/,
      'question/answer order remains stable as pending rows are replaced');
    assert.equal(studio.input().value, '');
    assert.equal(studio.calls.agent.length, 2);
  } finally { studio.close(); }
});

test('UPD3 TS: explicit send refusal restores the exact draft and shows the reason in mounted GRAPH', async () => {
  const studio = await mountStudio({agent:async () => ({ok:false, error:'Policy refused this turn'})});
  try {
    await studio.settle(); assertGraph(studio);
    studio.send('  refused original draft 3e71  ');
    await studio.settle(160);
    assert.equal(studio.calls.agent.length, 1);
    assert.equal(studio.input().value, '  refused original draft 3e71  ');
    assert.match(studio.inspector().textContent, /Policy refused this turn/);
    assert.ok([...studio.inspector().querySelectorAll('[role="status"],[role="alert"]')]
      .some(row => row.textContent.includes('Policy refused this turn')), 'refusal reason is visibly announced');
  } finally { studio.close(); }
});

test('UPD3 TS: a queued turn refused after the first reply returns to the mounted input with its reason', async () => {
  const first = deferred();
  const studio = await mountStudio({agent:(_call, index) => index === 1 ? first.promise : Promise.reject(new Error('Queued send refused by host'))});
  try {
    await studio.settle();
    studio.send('successful first turn'); await studio.settle(1000);
    studio.send('  queued draft to preserve 9fa1  '); await studio.settle();
    assert.equal(studio.calls.agent.length, 1);
    assert.match(studio.inspector().textContent, /queued draft to preserve 9fa1/);
    first.resolve({ok:true, answer:'First reply delivered', delivery:{state:'replied'}});
    await studio.settle(200);
    assert.deepEqual(studio.calls.agent.map(call => call.prompt), ['successful first turn', 'queued draft to preserve 9fa1']);
    assert.equal(studio.input().value, '  queued draft to preserve 9fa1  ');
    assert.match(studio.inspector().textContent, /First reply delivered/);
    assert.match(studio.inspector().textContent, /Queued send refused by host/);
    assert.equal(studio.calls.agent.length, 2, 'refusal does not silently retry');
  } finally { studio.close(); }
});

test('UPD3 TS: identical queued prompts reconcile with saved transcript ids exactly once and keep chronological order', async () => {
  const gates = [deferred(), deferred()], transcriptRows = {current:[]};
  const phrase = 'identical queued prompt 42ae';
  const row = (id, text, is_me) => ({id, text, is_me, who:is_me ? 'You' : 'Fake model', kind:is_me ? 'message' : 'reply', time:''});
  const studio = await mountStudio({transcriptRows, agent:(_call, index) => {
    transcriptRows.current.push(row('saved-question-' + index, phrase, true));
    return gates[index - 1].promise;
  }});
  const questions = () => [...studio.inspector().querySelectorAll('[data-chat-turn="question"]')]
    .filter(node => node.textContent.includes(phrase));
  try {
    await studio.settle(); studio.send(phrase); await studio.settle(1000);
    assert.equal(questions().length, 1, 'first question is read back without a local duplicate');
    studio.send(phrase); await studio.settle(160);
    assert.equal(studio.calls.agent.length, 1);
    assert.equal(questions().length, 2, 'saved first question cannot absorb the identical queued question');
    assert.ok(studio.inspector().querySelector('[data-chat-pending="queued"]'));
    transcriptRows.current.push(row('saved-answer-1', 'Saved first reply 5bc1', false));
    gates[0].resolve({ok:true, answer:'Saved first reply 5bc1', delivery:{state:'replied',
      message_id:'saved-question-1', reply_message_id:'saved-answer-1'}});
    await studio.settle(200);
    assert.equal(studio.calls.agent.length, 2);
    assert.equal(questions().length, 2, 'saved first turn and pending second remain two questions');
    transcriptRows.current.push(row('saved-answer-2', 'Saved second reply 7fd8', false));
    gates[1].resolve({ok:true, answer:'Saved second reply 7fd8', delivery:{state:'replied',
      message_id:'saved-question-2', reply_message_id:'saved-answer-2'}});
    await studio.settle(200);
    assert.equal(questions().length, 2);
    const visible = [...studio.inspector().querySelectorAll('[data-chat-turn="question"],[data-chat-turn="answer"]')]
      .map(node => node.textContent);
    assert.equal(visible.filter(text => text.includes('Saved first reply 5bc1')).length, 1);
    assert.equal(visible.filter(text => text.includes('Saved second reply 7fd8')).length, 1);
    const relevant = visible.filter(text => text.includes(phrase) || text.includes('Saved first reply 5bc1') || text.includes('Saved second reply 7fd8'));
    assert.equal(relevant.length, 4);
    assert.ok(relevant[0].includes(phrase));
    assert.ok(relevant[1].includes('Saved first reply 5bc1'));
    assert.ok(relevant[2].includes(phrase));
    assert.ok(relevant[3].includes('Saved second reply 7fd8'));
  } finally { studio.close(); }
});

test('UPD3 TS: late reply preserves the fresh unsent draft typed while its first turn was running', async () => {
  const gate = deferred(), studio = await mountStudio({agent:() => gate.promise});
  try {
    await studio.settle(); studio.send('sent question 81a3'); await studio.settle();
    studio.type(studio.input(), 'fresh unsent draft 6c24');
    gate.resolve({ok:true, answer:'First turn reply', delivery:{state:'replied'}});
    await studio.settle(160);
    assert.equal(studio.input().value, 'fresh unsent draft 6c24');
    assert.equal(studio.calls.agent.length, 1, 'typing a draft does not submit it');
    assert.match(studio.inspector().textContent, /First turn reply/);
  } finally { studio.close(); }
});

test('UPD3 TS: refusal restores exact text and parks the newer unsent draft visibly for recovery', async () => {
  const gate = deferred(), studio = await mountStudio({agent:() => gate.promise});
  try {
    await studio.settle(); studio.send('refused original 319b'); await studio.settle();
    studio.type(studio.input(), 'fresh unsent draft f823');
    gate.resolve({ok:false, error:'Refused while a new draft was typed'});
    await studio.settle(160);
    assert.equal(studio.input().value, 'refused original 319b');
    assert.match(studio.inspector().textContent, /fresh unsent draft f823/);
    assert.equal(studio.calls.agent.length, 1);
    assert.match(studio.inspector().textContent, /Refused while a new draft was typed/);
    const restore = [...studio.inspector().querySelectorAll('button')].find(button => /Restore draft/i.test(button.textContent));
    assert.ok(restore, 'newer unsent text has a visible recovery action');
    studio.click(restore);
    assert.equal(studio.input().value, 'fresh unsent draft f823');
    assert.equal(studio.calls.agent.length, 1, 'restoring the draft does not send it');
  } finally { studio.close(); }
});

test('UPD3 TS: a timed-out raw request holds queued sends until its late reply settles, then drains in order', async () => {
  const late = deferred();
  const studio = await mountStudio({agent:(_call, index) => index === 1 ? late.promise
    : {ok:true, answer:'Queued reply after late first reply', delivery:{state:'replied'}}});
  try {
    await studio.settle();
    studio.win.ARCHHUB_AGENT_TURN_TIMEOUT_MS = 25;
    studio.send('slow first request 8f0c');
    studio.send('queued behind slow request ae31');
    await studio.settle(160);
    assert.equal(studio.calls.agent.length, 1, 'timeout is not evidence that the original provider turn stopped');
    assert.match(studio.inspector().textContent, /reply did not arrive|timed out|timeout/i);
    assert.match(studio.inspector().textContent, /queued behind slow request ae31/);
    late.resolve({ok:true, answer:'Late first reply accepted', delivery:{state:'replied'}});
    await studio.settle(200);
    assert.deepEqual(studio.calls.agent.map(call => call.prompt), ['slow first request 8f0c', 'queued behind slow request ae31']);
    const text = studio.inspector().textContent;
    assert.match(text, /Late first reply accepted[\s\S]*queued behind slow request ae31[\s\S]*Queued reply after late first reply/);
    assert.equal(studio.calls.agent.length, 2, 'late reconciliation does not repeat either request');
  } finally { studio.close(); }
});

test('UPD3 TS: an unconfirmed turn remains retryable after another draft queues and retries its original envelope first', async () => {
  const studio = await mountStudio({agent:(_call, index) => index === 1
    ? {ok:true, answer:'Original delivery is unconfirmed', delivery:{state:'sent_unconfirmed'}}
    : {ok:true, answer:index === 2 ? 'Original retry confirmed' : 'Queued second confirmed', delivery:{state:'replied'}}});
  try {
    await studio.settle(); studio.send('original unconfirmed turn 014e'); await studio.settle(160);
    assert.equal(studio.input().value, 'original unconfirmed turn 014e');
    const original = plain(studio.calls.agent[0]);
    studio.send('edited second queued turn e19d'); await studio.settle(160);
    assert.equal(studio.calls.agent.length, 1, 'unconfirmed original blocks the different queued request');
    assert.match(studio.inspector().textContent, /edited second queued turn e19d/);
    const retry = [...studio.inspector().querySelectorAll('button')].find(button => button.textContent.trim() === 'Retry');
    assert.ok(retry, 'original remains visibly retryable after edit and queue');
    studio.click(retry); await studio.settle(200);
    assert.deepEqual(studio.calls.agent.map(call => call.prompt), [original.prompt, original.prompt, 'edited second queued turn e19d']);
    assert.deepEqual(studio.calls.agent[1], original, 'Retry preserves the original prompt, model, generation, target, and request id');
    assert.notEqual(studio.calls.agent[2].context.request_id, original.context.request_id);
    assert.match(studio.inspector().textContent, /Original retry confirmed[\s\S]*edited second queued turn e19d[\s\S]*Queued second confirmed/);
  } finally { studio.close(); }
});

test('UPD3 TS: retry after choosing a different model and generation settings reuses the original captured envelope', async () => {
  const changedRoute = 'lmstudio/court-changed-model';
  const modelCatalogue = {ok:true, selected_route:'openrouter/free', readiness:{state:'ready'}, groups:[{name:'LOCAL court', items:[
    {name:'Court changed model', route:changedRoute, routed:changedRoute, vendor:'Fake local host', tag:'LOCAL', cost:'free', col:'#3fb950'}]}]};
  const studio = await mountStudio({normalTransport:true, modelCatalogue, agent:(_call, index) => index === 1
    ? {ok:false, error:'Refused original model turn'} : {ok:true, answer:'Original envelope retry delivered', delivery:{state:'replied'}}});
  try {
    await studio.settle();
    studio.win.ARCHHUB_MODEL_DEFAULTS = {temperature:0.15, 'top-p':0.8, 'max tokens':512};
    studio.send('retry captured envelope 991e'); await studio.settle(160);
    const original = plain(studio.calls.agent[0]);
    assert.deepEqual(original.context.generation, {temperature:0.15, top_p:0.8, max_tokens:512});
    studio.click(studio.inspector().querySelector('[data-model-indicator]')); await studio.settle(160);
    const picker = studio.doc.querySelector('[role="dialog"][aria-label="Choose a model"]');
    assert.ok(picker, 'real model picker is mounted');
    const changed = [...picker.querySelectorAll('div')].find(node => !node.childElementCount && node.textContent === 'Court changed model');
    assert.ok(changed, 'different model is offered by the fake live catalogue');
    studio.click(changed.parentElement); await studio.settle(160);
    assert.match(studio.inspector().querySelector('[data-model-indicator]').textContent, /lmstudio\/court-changed-model/);
    studio.win.ARCHHUB_MODEL_DEFAULTS = {temperature:1.5, 'top-p':0.3, 'max tokens':2048};
    const retry = [...studio.inspector().querySelectorAll('button')].find(button => button.textContent.trim() === 'Retry');
    assert.ok(retry, 'refused turn still offers Retry after settings changed');
    studio.click(retry); await studio.settle(160);
    assert.equal(studio.calls.agent.length, 2);
    assert.deepEqual(studio.calls.agent[1], original, 'Retry is the same request envelope even though the selected defaults changed');
    assert.match(studio.inspector().textContent, /Original envelope retry delivered/);
  } finally { studio.close(); }
});

test('UPD3 TS: two identical refused turns retain distinct request ids through parked-draft recovery', async () => {
  const first = deferred(), phrase = 'identical refused turn 1c9f';
  const studio = await mountStudio({agent:(_call, index) => index === 1 ? first.promise : index === 2
    ? {ok:false, error:'Second identical turn refused'} : {ok:true, answer:'Recovered turn ' + index, delivery:{state:'replied'}}});
  try {
    await studio.settle(); studio.send(phrase); await studio.settle(); studio.send(phrase);
    first.resolve({ok:false, error:'First identical turn refused'}); await studio.settle(200);
    assert.equal(studio.calls.agent.length, 2);
    const originals = studio.calls.agent.slice(0, 2).map(plain);
    assert.notEqual(originals[0].context.request_id, originals[1].context.request_id);
    for (const original of originals) {
      const saved = [...studio.inspector().querySelectorAll('[data-saved-draft]')].find(node => node.textContent.includes(phrase));
      assert.ok(saved, 'identical refused text still has a separate recoverable request tuple');
      studio.click([...saved.querySelectorAll('button')].find(button => /Restore draft/.test(button.textContent)));
      assert.equal(studio.input().value, phrase);
      studio.key(studio.input(), {key:'Enter'}); await studio.settle(160);
      assert.deepEqual(studio.calls.agent.at(-1), original, 'restoring identical text preserves that turn request id');
    }
    assert.equal(studio.calls.agent.length, 4);
  } finally { studio.close(); }
});

test('UPD3 FK: node click immediately after mount survives a stale empty selection publication and exposes Fork', async () => {
  const studio = await mountStudio({delayedSelection:true});
  try {
    studio.click(studio.card('b'));
    await studio.settle();
    assertSelectedWithFork(studio);
    studio.staleEmpty(); await studio.settle();
    assertSelectedWithFork(studio);
    assert.equal(studio.selectionGates.length, 1);
    studio.selectionGates[0].resolve(); await studio.settle();
    assertSelectedWithFork(studio);
  } finally { studio.close(); }
});

test('UPD3 FK: node click immediately after a background clear survives the late empty acknowledgement', async () => {
  const studio = await mountStudio({delayedSelection:true});
  try {
    studio.click(studio.card('b'));
    studio.selectionGates[0].resolve(); await studio.settle();
    assertSelectedWithFork(studio);
    studio.clearBackground(); await studio.settle();
    assertGraph(studio);
    studio.click(studio.card('b'));
    await studio.settle();
    assertSelectedWithFork(studio);
    studio.staleEmpty(); await studio.settle();
    assertSelectedWithFork(studio);
    assert.equal(studio.selectionGates.length, 2);
    studio.selectionGates[1].resolve(); await studio.settle();
    assertSelectedWithFork(studio);
  } finally { studio.close(); }
});

for (const connection of ['normal', 'signed']) {
test(`UPD3 FK: real ${connection} authority restores retained primary to a nonempty selection after mount and background clear`, async () => {
  const studio = await mountStudio({realAuthority:connection === 'signed', normalTransport:connection === 'normal', retainedFocus:true});
  const snapshot = () => connection === 'signed' ? studio.win.ARCHHUB_STUDIO_AUTHORITY.getSnapshot()
    : studio.existing.getSnapshot().topology;
  const focusPosts = () => studio.calls.posts.filter(call => connection === 'signed'
    ? call.url === '/api/universal/focus' : call.url === '/api/universal/gesture' && call.body.focus === 'b');
  try {
    await studio.settle(); assertGraph(studio);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (attempt) {
        studio.clearBackground(); await studio.settle();
        assertGraph(studio);
        const cleared = snapshot();
        assert.equal(cleared.canvas.selected, 'b', 'host keeps its navigation primary after clear');
        assert.deepEqual(plain(cleared.canvas.selection), [], 'cleared roots are genuinely empty');
      }
      const before = focusPosts().length;
      studio.click(studio.card('b')); await studio.settle(160);
      assertSelectedWithFork(studio);
      const posted = focusPosts();
      assert.equal(posted.length, before + 1, 'same retained primary with empty roots still POSTs focus');
      assert.deepEqual(posted.at(-1).body.selected_roots || posted.at(-1).body.roots, ['b']);
      assert.deepEqual(plain(snapshot().canvas.selection), ['b']);
    }
  } finally { studio.close(); }
});
}

for (const connection of ['normal', 'signed']) {
test(`UPD3 GR ${connection}: mounted member drag-out then Ctrl+Z and redo repaint membership and hide/release the node`, async () => {
  const studio = await mountStudio({grouped:true, realAuthority:connection === 'signed'});
  try {
    await studio.settle();
    const chips = () => studio.card('group-a').querySelectorAll('[data-member-chip]');
    assert.equal(chips().length, 2);
    assert.equal(studio.card('b'), null, 'collapsed member starts hidden');
    const chip = studio.card('group-a').querySelector('[data-member-chip="b"]');
    studio.pointer(chip, 'pointerdown', {clientX:120, clientY:100});
    studio.pointer(studio.region(), 'pointermove', {clientX:700, clientY:400});
    studio.pointer(studio.win, 'pointerup', {clientX:700, clientY:400});
    await studio.settle(200);
    assert.equal(studio.calls.posts.filter(call => call.url === '/api/universal/interaction').length, 1);
    assert.equal(chips().length, 1, 'group card repaints to one member');
    assert.ok(studio.card('b'), 'dragged member is released onto the canvas');
    assert.ok(studio.doc.activeElement === studio.region(), 'successful member drop restores canvas focus; active=' + studio.doc.activeElement?.outerHTML?.slice(0, 160));
    studio.click(studio.card('group-a')); await studio.settle(200);
    assert.ok(studio.doc.activeElement === studio.region(), 'group selection restores canvas focus; active=' + studio.doc.activeElement?.outerHTML?.slice(0, 160));
    studio.doc.activeElement.blur();
    assert.ok(studio.doc.activeElement === studio.doc.body, 'reported body focus is reproduced');
    assert.equal(studio.key(studio.doc.body, {key:'z', ctrlKey:true}), false, 'document shortcut consumes Undo');
    await studio.settle(200);
    assert.deepEqual(studio.calls.history, ['undo'], 'body keyboard handler reaches host history exactly once');
    assert.equal(chips().length, 2, 'Undo repaints both members');
    assert.equal(studio.card('b'), null, 'Undo hides the released card inside its group again');
    assert.ok(studio.region().textContent.includes('Undid: removed \u2018Line Watcher\u2019 from the group'), 'Undo describes the removal it undid');
    studio.key(studio.doc.body, {key:'Z', ctrlKey:true, shiftKey:true}); await studio.settle(200);
    assert.deepEqual(studio.calls.history, ['undo', 'redo']);
    if (connection === 'signed') {
      const historyPosts = studio.calls.posts.filter(call => call.url === '/api/universal/gesture' && (call.body.undo || call.body.redo));
      assert.equal(historyPosts.length, 2, 'signed keyboard path sends both history gestures');
      assert.equal(historyPosts[0].body.undo, true);
      assert.equal(historyPosts[1].body.redo, true);
    }
    assert.equal(chips().length, 1, 'Redo repaints the reduced membership');
    assert.ok(studio.card('b'), 'Redo releases the member again');
    assert.ok(studio.region().textContent.includes('Redid: removed \u2018Line Watcher\u2019 from the group'), 'Redo describes the removal it repeated');
    const undo = [...studio.region().querySelectorAll('button')].find(button => button.getAttribute('aria-label') === 'Undo');
    studio.click(undo); await studio.settle(200);
    assert.equal(chips().length, 2, 'toolbar Undo uses the same graph history');
    assert.equal(studio.card('b'), null, 'toolbar Undo hides the released node');
    studio.key(studio.region(), {key:'y', ctrlKey:true}); await studio.settle(200);
    assert.deepEqual(studio.calls.history, ['undo', 'redo', 'undo', 'redo'], 'canvas bubbling and Ctrl+Y each send exactly once');
    assert.equal(chips().length, 1, 'Ctrl+Y restores the reduced membership');
    assert.ok(studio.card('b'));
    studio.key(studio.region(), {key:'z', ctrlKey:true}); await studio.settle(200);
    assert.equal(chips().length, 2, 'focused canvas Undo still works exactly once');
    assert.deepEqual(studio.calls.history, ['undo', 'redo', 'undo', 'redo', 'undo']);
    studio.key(studio.doc.body, {key:'z', metaKey:true, shiftKey:true}); await studio.settle(200);
    assert.equal(chips().length, 1, 'Cmd+Shift+Z remains supported');
    assert.deepEqual(studio.calls.history, ['undo', 'redo', 'undo', 'redo', 'undo', 'redo']);
  } finally { studio.close(); }
});
}

test('UNDOKEYS toast: genuine grouped member deletion is not described as a release onto the canvas', () => {
  const source = read('nodelang/studio/studio-lm.jsx');
  const begin = source.indexOf('const canvasHistoryToast = '), end = source.indexOf('// Wheel zoom:', begin);
  const toast = new Function(source.slice(begin, end) + '; return canvasHistoryToast;')();
  const grouped = {nodes:[{id:'g', title:'Group', members:[{id:'b', title:'Member'}]}], wires:[]};
  const deleted = {nodes:[{id:'g', title:'Group', members:[]}], wires:[]};
  assert.equal(toast('redo', grouped, deleted), 'Redid the last change');
  assert.equal(toast('undo', deleted, grouped), 'Undid the last change');
});

for (const connection of ['normal', 'signed']) {
test(`UNDOKEYS ${connection}: document history skips composer, editors, overlays and inactive Studio`, async () => {
  const studio = await mountStudio({grouped:true, realAuthority:connection === 'signed'});
  try {
    await studio.settle();
    const chip = studio.card('group-a').querySelector('[data-member-chip="b"]');
    studio.pointer(chip, 'pointerdown', {clientX:120, clientY:100});
    studio.pointer(studio.region(), 'pointermove', {clientX:700, clientY:400});
    studio.pointer(studio.win, 'pointerup', {clientX:700, clientY:400});
    await studio.settle(250);
    studio.clearBackground(); await studio.settle(200);
    const shortcuts = [{key:'z', ctrlKey:true}, {key:'Z', ctrlKey:true, shiftKey:true}, {key:'y', ctrlKey:true}];
    const skip = target => {
      target.focus();
      const posts = studio.calls.posts.length;
      for (const shortcut of shortcuts) assert.equal(studio.key(target, shortcut), true, 'editor/overlay retains native keyboard behavior');
      assert.equal(studio.calls.posts.length, posts, 'excluded shortcuts send no request');
      assert.deepEqual(studio.calls.history, []);
    };
    studio.type(studio.input(), 'keep this composer draft'); skip(studio.input());
    assert.equal(studio.input().value, 'keep this composer draft');
    for (const tag of ['input', 'textarea', 'select']) {
      const field = studio.doc.createElement(tag); studio.doc.body.append(field); skip(field); field.remove();
    }
    for (const editable of ['', 'true', 'plaintext-only']) {
      const editor = studio.doc.createElement('div'); editor.setAttribute('contenteditable', editable);
      const child = studio.doc.createElement('span'); child.tabIndex = 0; editor.append(child);
      studio.doc.body.append(editor); skip(child); editor.remove();
    }
    for (const role of ['dialog', 'menu']) {
      const overlay = studio.doc.createElement('div'); overlay.setAttribute('role', role); studio.doc.body.append(overlay);
      studio.doc.activeElement.blur(); skip(studio.doc.body); overlay.remove();
    }
    const dialog = studio.doc.createElement('dialog'); dialog.setAttribute('open', ''); studio.doc.body.append(dialog);
    skip(studio.doc.body); dialog.remove();
    studio.doc.activeElement.blur();
    studio.key(studio.doc.body, {key:'k', ctrlKey:true}); await studio.settle();
    assert.ok(studio.doc.querySelector('[role="dialog"][aria-label="Node library"]'), 'real library is an open modal');
    studio.doc.activeElement.blur(); skip(studio.doc.body);
    studio.key(studio.doc.body, {key:'Escape'}); await studio.settle();
    assert.equal(studio.doc.querySelector('[role="dialog"][aria-label="Node library"]'), null);
    studio.key(studio.doc.body, {key:'/', ctrlKey:true}); await studio.settle();
    assert.ok(studio.doc.querySelector('[role="dialog"][aria-label="Documentation"]'), 'real Documentation is an open modal');
    studio.doc.activeElement.blur(); skip(studio.doc.body);
    studio.key(studio.doc.body, {key:'Escape'}); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.region().dispatchEvent(new studio.win.MouseEvent('contextmenu',
      {bubbles:true, cancelable:true, clientX:900, clientY:700})));
    await studio.settle();
    assert.ok(studio.doc.querySelector('[role="menu"]'), 'real canvas menu is open');
    studio.doc.activeElement.blur(); skip(studio.doc.body);
    studio.key(studio.doc.body, {key:'Escape'}); await studio.settle();
    assert.equal(studio.doc.querySelector('[role="menu"]'), null);
    studio.doc.activeElement.blur();
    assert.equal(studio.key(studio.doc.body, {key:'z', ctrlKey:true, altKey:true}), true);
    assert.deepEqual(studio.calls.history, [], 'Alt-modified chord does not invoke history');
    studio.key(studio.doc.body, {key:'z', ctrlKey:true}); await studio.settle(200);
    assert.deepEqual(studio.calls.history, ['undo'], 'listener remains active after exclusions');
    const home = [...studio.doc.querySelectorAll('button')].find(button => button.getAttribute('aria-label') === 'Home');
    studio.click(home); await studio.settle(200);
    assert.equal(studio.region(), null, 'Home unmounts the active Studio canvas');
    studio.doc.activeElement.blur();
    const posts = studio.calls.posts.length;
    assert.equal(studio.key(studio.doc.body, {key:'y', ctrlKey:true}), true);
    assert.equal(studio.calls.posts.length, posts, 'inactive view sends no history request');
    assert.deepEqual(studio.calls.history, ['undo'], 'document listener is removed on view exit');
  } finally { studio.close(); }
});
}
