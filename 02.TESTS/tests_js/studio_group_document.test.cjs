// Group is one concept (SPEC 4.4): Ctrl+G makes one node from several through the document's own group owner
// (node children / parent, groups). The file keeps the real member wires; the group's sockets are a projection.
'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const structuredClone = globalThis.structuredClone;
const ports = {source: [{id: 'value', type: 'number'}], target: [{id: 'a', type: 'number'}]};
const step = (id, x, y) => ({id, type: 'script.python', title: id, params: {kind: 'pure', code: ''}, ports: structuredClone(ports), position: {x, y}});
const wire = (id, from, to) => ({id, from: {node: from, socket: 'value'}, to: {node: to, socket: 'a'}});
const file = () => ({
  format: 'archhub', version: 1, id: 'doc-group', title: 'Group',
  nodes: [step('N1', 40, 900), step('M1', 1000, 900), step('M2', 1000, 500), step('M3', 400, 120), step('N2', 40, 40)],
  wires: [wire('w1', 'N1', 'M1'), wire('w2', 'M1', 'M2'), wire('w3', 'M2', 'M3'), wire('w4', 'M3', 'N2')],
  groups: [], notes: [], viewport: {x: 0, y: 0, zoom: 1}, properties: {revision: 1},
});

async function open() {
  let made = 0;
  const context = {
    console, structuredClone, URLSearchParams, AbortSignal, setTimeout, clearTimeout,
    setInterval: () => 0, clearInterval() {},
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options && options.detail; } },
    document: {hidden: true, addEventListener() {}},
    crypto: {randomUUID: () => 'made-' + (++made)},
    sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    ARCHHUB_BOOT: {token: 'fixture', csrf: 'fixture'},
    addEventListener() {}, dispatchEvent() {},
    fetch: async (url, init = {}) => {
      const body = init.body ? JSON.parse(init.body) : null;
      let data = {ok: true, result: [], items: [], recent: [], directory: 'mem', sessions: [], messages: [], agents: [], providers: [], commands: []};
      // COMMANDREGISTRY: api.js loads the owner catalogue before the first session file.
      if (url === '/api/commands') data = {commands: []};
      else if (url === '/api/universal/settings-action' && body?.function === 'readLibraryCollapsed') data = {ok: true, result: {libraryCollapsed: []}};
      else if (url === '/api/session-files' && body?.action === 'initial') data = {ok: true, document: file(), path: 'C:/isolated/group.archhub'};
      else if (url === '/api/session-files' && body?.action === 'autosave') data = {ok: true, path: body.path, revision: (body.document.properties?.revision || 0) + 1, document: body.document};
      else if (url === '/api/session-files' && body?.action === 'solve') data = {ok: true, results: {}, solved: [], stale: [], ms: 0};
      else if (url === '/api/universal/workshop' && body?.function === 'listWorkshopMessages') data = {ok: true, result: {messages: []}};
      return {ok: true, status: 200, headers: {get: () => null}, json: async () => data};
    },
  };
  context.window = context;
  vm.createContext(context);
  for (const name of ['studio-authority.js', 'api.js']) vm.runInContext(fs.readFileSync(path.join(studio, name), 'utf8'), context, {filename: name});
  await context.ArchHubAPI.ready;
  return context.ArchHubAPI;
}
const plain = value => JSON.parse(JSON.stringify(value));  // Studio state lives in the page's own realm
// What the author made: no run results, no save counter.
const authored = document => plain({nodes: document.nodes.map(({result, ...node}) => node), wires: document.wires, groups: document.groups, notes: document.notes});
const shown = (api, id) => api.getSnapshot().graph.wires.find(row => row.id === id);
const members = ['M1', 'M2', 'M3'];

test('Ctrl+G makes one collapsed node whose sockets are every member socket; crossing wires land on it and the file keeps the member wires', async () => {
  const api = await open(), before = authored(api.getSessionDocument());
  const group = await api.groupNodes(members);
  assert.equal(group.collapsed, true, 'the group starts as one node');
  assert.deepEqual(plain(group.inputs).map(port => port.id), members.map(id => 'in:' + id + ':a'));
  assert.deepEqual(plain(group.outputs).map(port => port.id), members.map(id => 'out:' + id + ':value'));
  assert.deepEqual([shown(api, 'w1').to, shown(api, 'w1').toPort], [group.id, 'in:M1:a'], 'the wire that crosses in ends on the group socket');
  assert.deepEqual([shown(api, 'w4').from, shown(api, 'w4').fromPort], [group.id, 'out:M3:value'], 'the wire that crosses out starts on the group socket');
  assert.deepEqual([shown(api, 'w2').from, shown(api, 'w2').to], ['M1', 'M2'], 'a wire inside the group stays inside');
  const held = api.getSessionDocument();
  assert.deepEqual(authored(held).wires, before.wires, 'the file keeps the real member wires, so what is solved does not change');
  assert.deepEqual(held.groups, [{id: group.id, nodes: members}]);
  assert.deepEqual(held.nodes.filter(node => members.includes(node.id)).map(({parent, ...node}) => [parent, node.params, node.ports]),
    members.map(() => [group.id, {kind: 'pure', code: ''}, ports]), 'members keep their identity and gain only their group');
  assert.deepEqual(held.nodes.find(node => node.id === group.id).position, {x: 400 - 24, y: 120 - 44}, 'the group sits at the top left of its members');
});

test('group, collapse, expand and ungroup are one undo step each; ungroup returns the identical document', async () => {
  const api = await open(), before = authored(api.getSessionDocument());
  const group = await api.groupNodes(members), grouped = authored(api.getSessionDocument());
  await api.undo();
  assert.deepEqual(authored(api.getSessionDocument()), before, 'one undo removes the group');
  await api.redo();
  assert.deepEqual(authored(api.getSessionDocument()), grouped, 'one redo brings it back');

  await api.setGroupCollapsed(group.id, false);
  const expanded = api.getSnapshot().graph.nodes.find(node => node.id === group.id);
  assert.equal(expanded.collapsed, false);
  assert.deepEqual([shown(api, 'w1').to, shown(api, 'w1').toPort], ['M1', 'a'], 'expanded: the crossing wire is drawn to the member as it was saved');
  assert.deepEqual([shown(api, 'w4').from, shown(api, 'w4').fromPort], ['M3', 'value']);
  assert.deepEqual(plain(expanded.inputs).find(port => port.id === 'in:M1:a').member, {node: 'M1', port: 'a'}, 'the expanded group still names every member socket');
  await api.undo();
  assert.deepEqual(authored(api.getSessionDocument()), grouped, 'one undo collapses it again');
  await api.redo();

  await api.ungroupNode(group.id);
  assert.deepEqual(authored(api.getSessionDocument()), before, 'ungroup restores every node, wire and group list');
  await api.undo();
  assert.equal(api.getSessionDocument().groups.length, 1, 'one undo brings the group back');
});

test('a group made on a first, on-screen arrangement sits around its members, and Tidy up moves the members with it', async () => {
  const api = await open();
  await api.arrangeGraph(true);  // the first view: arranged on screen only, the file is not written
  const seen = Object.fromEntries(api.getSnapshot().graph.nodes.map(node => [node.id, {x: node.x, y: node.y}]));
  assert.notDeepEqual(seen.M1, {x: 1000, y: 900}, 'the first view moved the nodes on screen');
  const group = await api.groupNodes(members), held = api.getSessionDocument(), at = id => held.nodes.find(node => node.id === id).position;
  assert.deepEqual(members.map(at), members.map(id => seen[id]), 'the first edit keeps what he sees');
  assert.deepEqual(at(group.id), {x: Math.min(...members.map(id => seen[id].x)) - 24, y: Math.min(...members.map(id => seen[id].y)) - 44},
    'the group is measured from where its members are drawn');

  const offsets = document => members.map(id => { const node = document.nodes.find(row => row.id === id).position, origin = document.nodes.find(row => row.id === group.id).position; return [node.x - origin.x, node.y - origin.y]; });
  const inside = offsets(held);
  await api.moveNodes({[group.id]: {x: 2000, y: 2000}});
  await api.arrangeGraph();
  const tidied = api.getSessionDocument();
  assert.notDeepEqual(tidied.nodes.find(node => node.id === group.id).position, {x: 2000, y: 2000}, 'Tidy up moved the group');
  assert.deepEqual(offsets(tidied), inside, 'its members moved with it');
});
