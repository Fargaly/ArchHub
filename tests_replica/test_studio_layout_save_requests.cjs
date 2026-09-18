/* One drag is one request. The Studio used to read the whole canvas before the
   save and again after it, so a drag on the founder graph cost three full
   projections for one 0.38 s write. The receipt already names the committed
   revision and the client already holds the points it sent, so the held canvas
   carries the save forward and the two reads are gone. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
// The client runs in its own vm context, so its objects carry that other
// Object prototype: compare the facts, not the prototype chain.
const same = (value, expected) => assert.equal(JSON.stringify(value), JSON.stringify(expected));

function transport(receipt) {
  const sandbox = {TextEncoder, URLSearchParams, crypto: webcrypto};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname,
    '../nodelang/studio/studio-existing-workshop.js'), 'utf8'), sandbox);
  const gets = [], posts = [];
  const api = sandbox.ArchHubExistingWorkshop.create({
    pendingStorage: {getItem: () => null},
    get: async url => {
      gets.push(url);
      throw Error('the drag must not read the whole canvas');
    },
    post: async (url, body) => {
      posts.push({url, body});
      return receipt(body, posts.length);
    },
  });
  const canvas = {
    ok: true, revision: 40, application_root: 'app',
    authorization: {subject: 'subject', session: 'session'},
    scope: {current: 'scope'},
    nodes: [{id: 'one', x: 10, y: 20}, {id: 'two', x: 30, y: 40}],
    wires: [], selected: null,
    interaction_projection: {revision: 40, bindings: []},
  };
  api.setTopologyCanvas(canvas);
  return {api, canvas, gets, posts};
}

const accepted = body => ({
  ok: true, projection_mode: 'receipt-v1',
  base_revision: body.projection_revision,
  committed_revision: body.projection_revision + 1,
});

test('one drag sends one request and reads the canvas no times', async () => {
  const {api, gets, posts} = transport(accepted);
  await api.moveTopologyNodes({one: {x: 11, y: 21}}, 40, {one: {x: 10, y: 20}});
  assert.equal(gets.length, 0);
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/api/universal/gesture');
  same(posts[0].body, {
    expected_scope: 'scope', positions: {one: {x: 11, y: 21}},
    expected_positions: {one: {x: 10, y: 20}},
    projection_mode: 'receipt-v1', projection_revision: 40,
  });
  const held = api.getSnapshot().topology.canvas;
  assert.equal(held.revision, 41);
  assert.equal(held.interaction_projection.revision, 41);
  same(held.nodes.find(node => node.id === 'one'), {id: 'one', x: 11, y: 21});
  same(held.nodes.find(node => node.id === 'two'), {id: 'two', x: 30, y: 40});
});

test('the next drag runs straight off the carried canvas, still one request', async () => {
  const {api, gets, posts} = transport(accepted);
  await api.moveTopologyNodes({one: {x: 11, y: 21}}, 40, {one: {x: 10, y: 20}});
  await api.moveTopologyNodes({two: {x: 31, y: 41}}, 41, {two: {x: 30, y: 40}});
  assert.equal(gets.length, 0);
  assert.equal(posts.length, 2);
  assert.equal(posts[1].body.projection_revision, 41);
  same(posts[1].body.expected_positions, {two: {x: 30, y: 40}});
  assert.equal(api.getSnapshot().topology.canvas.revision, 42);
});

test('a base the held canvas disagrees with never reaches the owner', async () => {
  const {api, posts} = transport(accepted);
  await assert.rejects(
    api.moveTopologyNodes({one: {x: 11, y: 21}}, 40, {one: {x: 999, y: 999}}),
    /changed position/);
  assert.equal(posts.length, 0);
  assert.equal(api.getSnapshot().topology.canvas.revision, 40);
});

test('a root the held canvas does not hold never reaches the owner', async () => {
  const {api, posts} = transport(accepted);
  await assert.rejects(
    api.moveTopologyNodes({ghost: {x: 1, y: 2}}, 40, {ghost: {x: 0, y: 0}}),
    /no longer on this canvas/);
  assert.equal(posts.length, 0);
});

test('a receipt that does not name a committed revision is not accepted', async () => {
  const {api, posts} = transport(body => ({
    ok: true, projection_mode: 'receipt-v1',
    base_revision: body.projection_revision, committed_revision: 39,
  }));
  await assert.rejects(
    api.moveTopologyNodes({one: {x: 11, y: 21}}, 40, {one: {x: 10, y: 20}}),
    /reconciliation/);
  assert.equal(posts.length, 1);
  assert.equal(api.getSnapshot().topology.canvas.revision, 40);
  assert.equal(api.getSnapshot().topology.requires_refresh, true);
});
