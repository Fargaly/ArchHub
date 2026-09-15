/* Production callbacks in memory only: no browser, transport, database or agent. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-existing-workshop.js'), 'utf8');
const jsx = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const context = vm.createContext({URLSearchParams, TextEncoder});
vm.runInContext(source, context);
const create = context.ArchHubExistingWorkshop.create;
const plain = value => JSON.parse(JSON.stringify(value));
const digest = value => createHash('sha256').update(value).digest('hex');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return {promise, resolve, reject};
};
const turn = () => new Promise(resolve => setImmediate(resolve));
const storage = () => {
  const data = new Map();
  return {data, getItem:key => data.get(key) || null, setItem:(key, value) => data.set(key, value),
    removeItem:key => data.delete(key)};
};
const scope = (root = 'scope-a') => ({graph_id:'graph-a', root, revision:4,
  workshops:[{root:'workshop-a', label:'Workshop', send_category:'declared-message'}]});
const transcript = () => ({graph_id:'graph-a', root:'workshop-a', scope_root:'scope-a', revision:4,
  owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false, messages:[],
  participants:[{root:'owner-a', label:'Owner', attached:true}]});
const selection = {app:'claude', session_id:'native-a'};
const contact = {root:'contact-a', binding_digest:'a'.repeat(64), connected:true};
const discovered = () => ({status:'ok', revision:4,
  workshop:{root:'workshop-a', scope:'scope-a', scope_path:['brain-a', 'scope-a']},
  rows:[{...selection, title:'Existing session', connected:true, selectable:true}], contacts:[contact]});
const bound = () => ({ok:true, contact:contact.root, binding_digest:contact.binding_digest,
  ...selection, root:'workshop-a', scope:'scope-a', scope_path:['brain-a', 'scope-a'], revision:5,
  execution_authority:false});
const accepted = body => ({ok:true, root:body.root, contact:body.contact, message_id:'content-a',
  idempotency_key:body.idempotency_key, revision:5, storage:'conversation-content',
  delivery:{state:'started'}, execution_authority:false});
function setup(options = {}) {
  const posts = [], gets = [], pendingStorage = options.pendingStorage || storage();
  let next = 0;
  const api = create({pendingStorage, uuid:options.uuid || (() => `message-${++next}`),
    hash:options.hash || (async value => digest(value)),
    get:async url => { gets.push(url); return options.get ? options.get(url) :
      url.startsWith('/api/universal/native-agents?') ? discovered() : transcript(); },
    post:async (url, body) => { posts.push({url, body}); return options.post ? options.post(url, body) :
      body.action === 'bind' ? bound() : accepted(body); }});
  api.setCanvas(scope());
  return {api, posts, gets, pendingStorage};
}
const send = (api, selected = contact) => api.sendNativeContact('workshop-a', selected, 'Actual task text');
const pending = fixture => JSON.parse(fixture.pendingStorage.getItem('archhub.existing-workshop.pending.v1') || '{}');

test('native selection binds a primitive contact without sending or creating a chat', async () => {
  const fixture = setup();
  const result = await fixture.api.bindNativeContact(selection);
  assert.equal(result.contact, contact.root);
  assert.deepEqual(plain(fixture.posts), [{url:'/api/universal/native-contact', body:{action:'bind',
    root:'workshop-a', scope:'scope-a', node:null, ...selection, revision:4}}]);
  assert.equal(fixture.gets.length, 1);
  assert.deepEqual(pending(fixture), {});
});

test('saved-contact discovery checks every supported app rather than marking unqueried contacts offline', async () => {
  const fixture = setup();
  await fixture.api.nativeAgents('workshop-a');
  const query = new URLSearchParams(fixture.gets[0].split('?')[1]);
  assert.deepEqual(query.get('apps').split(',').sort(),
    ['antigravity', 'antigravity-ide', 'claude', 'codex', 'opencode']);
  assert.equal(query.get('root'), 'workshop-a');
  assert.equal(query.get('scope'), 'scope-a');
  assert.equal(fixture.posts.length, 0);
});

test('unavailable, duplicate, offline or unselectable native sessions refuse before binding', async () => {
  for (const change of [row => { row.status = 'unavailable'; },
    row => { row.rows.push({...row.rows[0]}); }, row => { row.rows[0].connected = false; },
    row => { row.rows[0].selectable = false; }]) {
    const discovery = discovered(); change(discovery);
    const fixture = setup({get:() => discovery});
    await assert.rejects(fixture.api.bindNativeContact(selection), /no longer uniquely available/);
    assert.equal(fixture.posts.length, 0);
  }
});

test('binding and scoped discovery refuse a graph changed during discovery', async () => {
  for (const bind of [true, false]) {
    const held = deferred(), fixture = setup({get:() => held.promise});
    const operation = bind ? fixture.api.bindNativeContact(selection) : fixture.api.nativeAgents('workshop-a');
    fixture.api.setCanvas(scope('scope-b'));
    held.resolve(discovered());
    await assert.rejects(operation, /changed/);
    assert.equal(fixture.posts.length, 0);
  }
});

test('binding rejects missing Workshop metadata and mismatched accepted identity', async () => {
  const missing = discovered(); delete missing.workshop;
  const fixture = setup({get:() => missing});
  await assert.rejects(fixture.api.bindNativeContact(selection), /Workshop connection/);
  assert.equal(fixture.posts.length, 0);
  for (const field of ['contact', 'binding_digest', 'app', 'session_id', 'root', 'scope', 'revision']) {
    const result = bound(); delete result[field];
    const second = setup({post:() => result});
    await assert.rejects(second.api.bindNativeContact(selection), /unconfirmed/);
    assert.equal(second.posts.length, 1);
  }
});

test('binding keeps a confirmed receipt while marking post-response navigation stale', async () => {
  const held = deferred(), fixture = setup({post:() => held.promise});
  const operation = fixture.api.bindNativeContact(selection);
  await turn();
  assert.equal(fixture.posts.length, 1);
  fixture.api.setCanvas(scope('scope-b'));
  held.resolve(bound());
  const result = await operation;
  assert.equal(result.contact, contact.root);
  assert.equal(result.navigation_current, false);
  assert.equal(fixture.api.getSnapshot().canvas.root, 'scope-b');
  assert.equal(fixture.posts.length, 1);
});

test('contact send needs an admitted conversation and protected editor provenance', async () => {
  const fixture = setup();
  await assert.rejects(send(fixture.api), /Refresh the conversation/);
  await fixture.api.refreshWorkshop('workshop-a');
  await assert.rejects(fixture.api.sendNativeContact('workshop-a', contact, 'Text',
    {root:'workshop-a', stageMessage:async () => { throw new Error('must not run'); }}), /editor belongs/);
  assert.equal(fixture.posts.length, 0);
});

test('send uses existing content endpoint with one durable id and no automatic second send', async () => {
  const fixture = setup();
  await fixture.api.refreshWorkshop('workshop-a');
  const result = await send(fixture.api);
  await turn();
  assert.equal(result.accepted, true);
  assert.deepEqual(plain(fixture.posts), [{url:'/api/universal/native-contact', body:{action:'send',
    root:'workshop-a', scope:'scope-a', contact:'contact-a', binding_digest:contact.binding_digest,
    text:'Actual task text', idempotency_key:'message-1'}}]);
  assert.deepEqual(pending(fixture), {});
});

test('concurrent duplicate clicks share one pending send', async () => {
  const held = deferred(), fixture = setup({post:() => held.promise});
  await fixture.api.refreshWorkshop('workshop-a');
  const first = send(fixture.api), second = send(fixture.api);
  await turn();
  assert.equal(fixture.posts.length, 1);
  held.resolve(accepted(fixture.posts[0].body));
  assert.equal((await first).message_id, (await second).message_id);
  assert.deepEqual(pending(fixture), {});
});

test('lost send receipt retains identity across adapter reload and requires explicit retry', async () => {
  const shared = storage();
  const first = setup({pendingStorage:shared, post:() => { throw new Error('Lost receipt'); }});
  await first.api.refreshWorkshop('workshop-a');
  await assert.rejects(send(first.api), /Lost receipt/);
  assert.equal(first.posts.length, 1);
  const originalId = first.posts[0].body.idempotency_key;
  assert.deepEqual(Object.values(pending(first)), [originalId]);
  const second = setup({pendingStorage:shared, uuid:() => { throw new Error('Must reuse pending identity'); }});
  await second.api.refreshWorkshop('workshop-a');
  await turn();
  assert.equal(second.posts.length, 0);
  await send(second.api);
  assert.equal(second.posts[0].body.idempotency_key, originalId);
  assert.deepEqual(pending(second), {});
});

test('missing or foreign send receipts retain the exact pending identity', async () => {
  for (const field of ['ok', 'root', 'contact', 'message_id', 'idempotency_key', 'revision']) {
    const fixture = setup({post:(_url, body) => { const value = accepted(body); delete value[field]; return value; }});
    await fixture.api.refreshWorkshop('workshop-a');
    await assert.rejects(send(fixture.api), /unconfirmed/);
    assert.deepEqual(Object.values(pending(fixture)), [fixture.posts[0].body.idempotency_key]);
    assert.equal(fixture.posts.length, 1);
  }
});

test('a changed contact binding cannot reuse the previous delivery identity', async () => {
  const fixture = setup({post:() => { throw new Error('Lost receipt'); }});
  await fixture.api.refreshWorkshop('workshop-a');
  await assert.rejects(send(fixture.api), /Lost receipt/);
  await assert.rejects(send(fixture.api, {...contact, binding_digest:'b'.repeat(64)}), /Lost receipt/);
  assert.notEqual(fixture.posts[0].body.idempotency_key, fixture.posts[1].body.idempotency_key);
  assert.equal(Object.keys(pending(fixture)).length, 2);
});

test('scope changes while hashing refuse before storing or posting', async () => {
  const held = deferred(), fixture = setup({hash:() => held.promise});
  await fixture.api.refreshWorkshop('workshop-a');
  const operation = send(fixture.api);
  fixture.api.setCanvas(scope('scope-b'));
  held.resolve('f'.repeat(64));
  await assert.rejects(operation, /changed before sending/);
  assert.equal(fixture.posts.length, 0);
  assert.deepEqual(pending(fixture), {});
});

test('unwritable pending storage refuses before external delivery', async () => {
  const fixture = setup({pendingStorage:{getItem:() => null, setItem:() => { throw new Error('Storage denied'); }}});
  await fixture.api.refreshWorkshop('workshop-a');
  await assert.rejects(send(fixture.api), /Storage denied/);
  assert.equal(fixture.posts.length, 0);
});

function connectionHarness(options = {}) {
  const start = jsx.indexOf('  const nativeConnection =', jsx.indexOf('const StudioLM ='));
  const end = jsx.indexOf('\n  };', jsx.indexOf('  const connectNativeSession =', start)) + '\n  };'.length;
  assert.ok(start > 0 && end > start);
  const calls = [], selected = storage(), projection = {canvas:{graph_id:'graph-a', root:'scope-a'}};
  const owner = {getSnapshot:() => projection, bindNativeContact:async row => {
    calls.push(['bind', row]); return options.bind ? options.bind(row) : bound(); }};
  const window = {ARCHHUB_EXISTING_WORKSHOP:owner, sessionStorage:selected,
    ARCHHUB_SCOPE_OPEN:async trail => { calls.push(['open', plain(trail)]); if (options.open) await options.open(trail); },
    location:{reload:() => calls.push(['reload'])}};
  const context = vm.createContext({window, workshopState:projection, React:{useRef:initial => ({current:initial})}});
  vm.runInContext(jsx.slice(start, end) + '\nglobalThis.connect = connectNativeSession;', context);
  return {connect:context.connect, calls, selected, projection};
}

test('picker connection opens the saved Workshop without sending a message', async () => {
  const fixture = connectionHarness();
  await fixture.connect(selection);
  assert.deepEqual(fixture.calls.map(row => row[0]), ['bind', 'open', 'reload']);
  assert.deepEqual(JSON.parse(fixture.selected.getItem('archhub.native-contact.selection.v1')),
    {graph:'graph-a', root:'workshop-a', contact:'contact-a'});
});

test('failed navigation retries the already confirmed contact instead of binding again', async () => {
  let attempts = 0;
  const fixture = connectionHarness({open:async () => { if (++attempts === 1) throw new Error('Navigation unavailable'); }});
  await assert.rejects(fixture.connect(selection), /connection is saved/);
  assert.deepEqual(fixture.calls.map(row => row[0]), ['bind', 'open']);
  await fixture.connect(selection);
  assert.deepEqual(fixture.calls.map(row => row[0]), ['bind', 'open', 'open', 'reload']);
});

test('unconfirmed bind cannot open, reload, select a recipient or send automatically', async () => {
  const fixture = connectionHarness({bind:async () => { throw new Error('Lost bind receipt'); }});
  await assert.rejects(fixture.connect(selection), /Lost bind receipt/);
  await turn();
  assert.deepEqual(fixture.calls.map(row => row[0]), ['bind']);
  assert.equal(fixture.selected.data.size, 0);
});

test('a saved bind receipt after a view change never navigates the newly selected graph', async () => {
  const held = deferred(), fixture = connectionHarness({bind:() => held.promise});
  const operation = fixture.connect(selection);
  fixture.projection.canvas = {graph_id:'graph-a', root:'scope-b'};
  held.resolve(bound());
  await assert.rejects(operation, /saved.*(?:view|graph|scope).*changed/i);
  assert.deepEqual(fixture.calls.map(row => row[0]), ['bind']);
  assert.equal(fixture.selected.data.size, 0);
  // An explicit retry after returning may open the known saved contact.
  fixture.projection.canvas = {graph_id:'graph-a', root:'scope-a'};
  await fixture.connect(selection);
  assert.deepEqual(fixture.calls.map(row => row[0]), ['bind', 'open', 'reload']);
});

test('an authorization change during binding cannot navigate under the earlier browser identity', async () => {
  const held = deferred(), fixture = connectionHarness({bind:() => held.promise});
  fixture.projection.canvas.authorization = {subject:'owner-a', session:'view-a'};
  const operation = fixture.connect(selection);
  fixture.projection.canvas = {...fixture.projection.canvas,
    authorization:{subject:'owner-b', session:'view-b'}};
  held.resolve(bound());
  await assert.rejects(operation, /saved.*(?:access|view).*changed/i);
  assert.deepEqual(fixture.calls.map(row => row[0]), ['bind']);
  assert.equal(fixture.selected.data.size, 0);
});
