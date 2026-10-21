/* Court (retention, SPEC 3.6): only a person's navigation is an "open". The
   Studio refreshes an open Workshop every 2.5 s and, after a failed read, the
   next refresh goes out without cursors; neither may be counted as activity.
   Production callbacks in memory only: no browser, network or database. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');

const source = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/studio-existing-workshop.js'), 'utf8');
const context = vm.createContext({URLSearchParams, TextEncoder});
vm.runInContext(source, context);
const create = context.ArchHubExistingWorkshop.create;
const storage = () => { const data = new Map(); return {getItem:key => data.get(key) || null,
  setItem:(key, value) => data.set(key, value), removeItem:key => data.delete(key)}; };
const transcript = () => ({graph_id:'graph-a', root:'workshop-a', scope_root:'scope-a', revision:4,
  owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false, messages:[],
  participants:[{root:'owner-a', label:'Owner', attached:true}]});
const row = (root, sequence, body) => ({root, message_id:root, sequence, body, sender_root:'owner-a',
  created_at:'2026-10-12T00:00:00Z', category:'note', state:'sent'});

function setup(answers, options = {}) {
  const gets = [];
  const api = create({pendingStorage:storage(), uuid:() => 'u',
    hash:async value => createHash('sha256').update(value).digest('hex'),
    get:async url => { gets.push(url); const next = answers.shift(); if (next instanceof Error) throw next;
      return next || transcript(); },
    post:async (url, body) => options.post ? options.post(url, body) : ({ok:true})});
  api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:4,
    workshops:[{root:'workshop-a', label:'Workshop', send_category:'declared-message'}]});
  return {api, gets, answers};
}
const opens = gets => gets.filter(url => new URLSearchParams(url.split('?')[1]).get('open') === '1').length;

test('navigation is an explicit open (open=1); a refresh poll never is', async () => {
  const fixture = setup([]);
  assert.equal(typeof fixture.api.openWorkshop, 'function', 'the Studio can say "a person opened this"');
  await fixture.api.openWorkshop('workshop-a');
  await fixture.api.refreshWorkshop('workshop-a');
  await fixture.api.refreshWorkshop('workshop-a');
  assert.equal(opens(fixture.gets), 1);
  assert.equal(new URLSearchParams(fixture.gets[0].split('?')[1]).get('open'), '1');
});

test('a refresh after a failed read goes out without cursors but is still not an open', async () => {
  const fixture = setup([new Error('timeout'), {ok:false, error:'Workshop changed; full refresh needed'}]);
  await fixture.api.refreshWorkshop('workshop-a').catch(() => {});
  await fixture.api.refreshWorkshop('workshop-a').catch(() => {});
  await fixture.api.refreshWorkshop('workshop-a');
  const cursorless = fixture.gets.filter(url => !/[?&](after|content_after)=/.test(url));
  assert.ok(cursorless.length >= 2, 'the reads after an error carry no cursor');
  assert.equal(opens(fixture.gets), 0);
});

test('Workshop transcript cache paints before the reconcile fetch resolves and never paints another room', async () => {
  let release;
  const first = {...transcript(), messages:[row('m1', 1, 'Cached row')]};
  const pending = new Promise(resolve => { release = () => resolve({...first, revision:5}); });
  const fixture = setup([first, pending]);
  await fixture.api.openWorkshop('workshop-a');
  assert.deepEqual(fixture.api.getSnapshot().workshop.messages.map(m => m.root), ['m1'], 'first visit shows fetched rows');
  fixture.api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:5,
    workshops:[{root:'workshop-a', label:'Workshop', send_category:'declared-message'}]});
  assert.equal(fixture.api.getSnapshot().workshop, null, 'leaving the read page can clear the visible projection');
  const read = fixture.api.refreshWorkshop('workshop-a');
  assert.deepEqual(fixture.api.getSnapshot().workshop.messages.map(m => m.root), ['m1'],
    'cached rows are visible before the pending fetch settles');
  release(); await read;
  fixture.api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:5,
    workshops:[{root:'workshop-a', label:'Workshop'}, {root:'workshop-b', label:'Other'}]});
  let roomBRelease;
  const roomBPending = new Promise(resolve => { roomBRelease = () => resolve({...transcript(), root:'workshop-b', revision:5, messages:[row('b1', 1, 'Other')]}); });
  fixture.answers.push(roomBPending);
  fixture.gets.length = 0;
  const roomBRead = fixture.api.refreshWorkshop('workshop-b').catch(() => {});
  assert.equal(fixture.api.getSnapshot().workshop, null, 'switching rooms does not show the previous room rows');
  roomBRelease(); await roomBRead;
});

const topology = (subject, session = 'view-a') => ({ok:true, application_root:'graph-a', revision:5,
  authorization:{subject, session}, scope:{current:'scope-a'}, nodes:[], wires:[],
  interaction_projection:{revision:5, bindings:[]}});

test('Workshop transcript cache is cleared before an authenticated subject switch can repaint it', async () => {
  let release;
  const first = {...transcript(), messages:[row('a1', 1, 'owner-a row')]};
  const pending = new Promise(resolve => { release = () => resolve({...transcript(), revision:5,
    owner:'owner-b', view:'view-b', self:'owner-b', messages:[row('b1', 1, 'owner-b row')]}); });
  const fixture = setup([first, pending]);
  fixture.api.setTopologyCanvas(topology('owner-a'));
  await fixture.api.refreshWorkshop('workshop-a');
  fixture.api.setTopologyCanvas(topology('owner-b', 'view-b'));
  const read = fixture.api.refreshWorkshop('workshop-a');
  assert.equal(fixture.api.getSnapshot().workshop, null, 'auth switch does not repaint owner-a cached rows');
  release(); await read;
});

test('Workshop transcript cache is cleared when the Workshop scope loses its signed-in authorization', async () => {
  let release;
  const pending = new Promise(resolve => { release = () => resolve({...transcript(), revision:6}); });
  const fixture = setup([{...transcript(), messages:[row('a1', 1, 'signed-in row')]}, pending]);
  fixture.api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:4,
    authorization:{subject:'owner-a', session:'view-a'},
    workshops:[{root:'workshop-a', label:'Workshop', send_category:'declared-message'}]});
  fixture.api.setTopologyCanvas(topology('owner-a'));
  await fixture.api.refreshWorkshop('workshop-a');
  fixture.api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:5, unavailable:'Not signed in.',
    workshops:[{root:'workshop-a', label:'Workshop', send_category:'declared-message'}]});
  const read = fixture.api.refreshWorkshop('workshop-a');
  assert.equal(fixture.api.getSnapshot().workshop, null, 'signed-out scope does not repaint signed-in cached rows');
  release(); await read;
});

test('Workshop transcript cache evicts the oldest entry beyond the cache bound', async () => {
  let release;
  const roots = Array.from({length:17}, (_, i) => 'workshop-' + i);
  const fixture = setup(roots.map((root, i) => ({...transcript(), root, revision:20 + i,
    messages:[row('m' + i, 1, 'cached ' + i)]})));
  fixture.api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:20,
    authorization:{subject:'owner-a', session:'view-a'},
    workshops:roots.map(root => ({root, label:root}))});
  for (const root of roots) await fixture.api.refreshWorkshop(root);
  fixture.answers.push(new Promise(resolve => { release = () => resolve({...transcript(), root:'workshop-0',
    revision:21, messages:[row('fresh', 1, 'fresh row')]}); }));
  const read = fixture.api.refreshWorkshop('workshop-0');
  assert.equal(fixture.api.getSnapshot().workshop, null, 'oldest cached room was evicted before fetch resolves');
  release(); await read;
});

test('Workshop transcript reconcile is a no-op for identical rows and appends new rows in place', async () => {
  const first = {...transcript(), messages:[row('m1', 1, 'One')]};
  const same = {...first, messages:[row('m1', 1, 'One')]};
  const appended = {...transcript(), revision:5, messages:[row('m1', 1, 'One'), row('m2', 2, 'Two')]};
  const fixture = setup([first, same, appended]);
  let publishes = 0;
  fixture.api.subscribe(() => { publishes += 1; });
  await fixture.api.openWorkshop('workshop-a');
  const held = fixture.api.getSnapshot().workshop;
  const afterFirst = publishes;
  await fixture.api.refreshWorkshop('workshop-a');
  assert.equal(publishes, afterFirst, 'identical refetch publishes no new projection');
  await fixture.api.refreshWorkshop('workshop-a');
  const next = fixture.api.getSnapshot().workshop;
  assert.equal(next.messages[0], held.messages[0], 'unchanged row object is reused');
  assert.deepEqual(next.messages.map(m => m.root), ['m1', 'm2'], 'new row appends after existing rows');
});

test('accepted send stays visible while cached transcript reconcile is pending and merges once', async () => {
  let release;
  const first = {...transcript(), messages:[row('m1', 1, 'Cached row')]};
  const pending = new Promise(resolve => { release = () => resolve({...transcript(), revision:5,
    messages:[row('m1', 1, 'Cached row'), row('entry-a', 2, 'Sent task')]}); });
  const fixture = setup([first, pending], {post:(_url, body) => ({ok:true, workshop:'workshop-a',
    root:'entry-a', idempotency_key:body.idempotency_key, revision:5,
    native_delivery:[{recipient:'worker-a', state:'started'}]})});
  await fixture.api.openWorkshop('workshop-a');
  const sending = fixture.api.sendWorkshopMessage('workshop-a', {target:'', message:'Sent task'});
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(JSON.parse(JSON.stringify(fixture.api.getSnapshot().workshop.messages.map(m => [m.root, m.body]))),
    [['m1', 'Cached row'], ['entry-a', 'Sent task']], 'accepted send remains visible before reconcile fetch resolves');
  assert.match(fixture.api.getSnapshot().workshopNotice, /Message saved.*delivery started/);
  release(); await sending;
  assert.deepEqual(JSON.parse(JSON.stringify(fixture.api.getSnapshot().workshop.messages.map(m => [m.root, m.body]))),
    [['m1', 'Cached row'], ['entry-a', 'Sent task']], 'reconcile keeps exactly one accepted send row');
});
