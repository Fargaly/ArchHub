'use strict';
// Court: the hosted Studio boots on the canvas the clean server actually sends (live 717, 2026-10-01).
//
// /studio?key= (the page the desktop prints for a browser) runs studio-authority.js.
// It mapped every wire's properties as labelled rows, but the clean canvas has sent
// them as an object since 50c6c6ba (clean_visual_projection.py: "properties":
// dict(relation["properties"])), so the page refused to boot with
// "(wire.properties || []).map is not a function" whenever a wire carried any.
// The fixture is the projection captured from a fresh clean runtime over HTTP, as
// the page reads it; it is not hand-written.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-authority.js'), 'utf8');
const captured = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/clean-canvas-fresh-runtime.json'), 'utf8'));

async function load(canvas) {
  const context = vm.createContext({URLSearchParams});
  vm.runInContext(source, context);
  const api = context.ArchHubStudioAuthority.create({
    get: async url => {
      assert.equal(url, '/api/universal/canvas');
      return canvas;
    },
    post: async () => { throw new Error('Booting the canvas writes nothing.'); },
  });
  await api.load();
  // The snapshot is built inside the vm context; compare it as plain data.
  return JSON.parse(JSON.stringify(api.getSnapshot()));
}

test('the hosted Studio boots on the fresh clean canvas and shows its wire properties', async () => {
  const [wire] = captured.wires;
  assert.equal(Array.isArray(wire.properties), false);          // the shape the server sends
  const snapshot = await load(captured);
  assert.equal(snapshot.graph.nodes.length, captured.nodes.length);
  const [shown] = snapshot.graph.wires;
  assert.equal(shown.id, wire.id);
  assert.deepEqual(shown.params.map(row => [row.k, row.v]), Object.entries(wire.properties));
});

test('labelled property rows still render as before', async () => {
  const rows = [{label: 'connection', value: 'requirement-link', relation: 'wire-property'}];
  const snapshot = await load({...captured, wires: captured.wires.map(wire => ({...wire, properties: rows}))});
  assert.deepEqual(snapshot.graph.wires[0].params, [{k: 'connection', v: 'requirement-link', rel: 'wire-property'}]);
});

test('a wire without properties renders none', async () => {
  const snapshot = await load({...captured, wires: captured.wires.map(({properties, ...wire}) => wire)});
  assert.deepEqual(snapshot.graph.wires[0].params, []);
});

test('the hosted session is one the Chats panel can show', async () => {
  // Chats reads LM_STATE_META[session.state].col; the hosted boot said 'ready',
  // which that map does not hold, and opening Chats blanked the whole Studio.
  const jsx = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
  const begin = jsx.indexOf('const LM_STATE_META');
  const states = [...jsx.slice(begin, jsx.indexOf('}));', begin)).matchAll(/^\s+(\w+):\s*\{/gm)].map(m => m[1]);
  assert.ok(states.includes('idle') && states.includes('running'));
  const held = new Map([['archhub.studio.session', JSON.stringify({token: 'held-token', csrf: 'held-csrf'})]]);
  const context = vm.createContext({URLSearchParams,
    sessionStorage: {getItem: key => held.get(key) ?? null, setItem: (key, value) => held.set(key, value),
      removeItem: key => held.delete(key)},
    fetch: async url => ({ok: true, json: async () => {
      assert.equal(url, '/api/universal/canvas');
      return captured;
    }})});
  vm.runInContext(source, context);
  await context.ArchHubStudioAuthority.boot({canvas_key: 'fixture'});
  const sessions = JSON.parse(JSON.stringify(context.ARCHHUB_LIVE.sessions));
  assert.equal(sessions.length, 1);
  assert.ok(sessions.every(session => states.includes(session.state)), JSON.stringify(sessions));
});

test('the hosted workspace is ready: its own browser session is the Studio session', async () => {
  // studio-lm.jsx opens a Workshop only when workspaceReady; that needs
  // authorization.session, which the clean canvas names as its one browser session.
  const [own] = captured.authorization.browser_sessions;
  assert.equal(captured.authorization.session, undefined);
  const snapshot = await load(captured);
  assert.equal(snapshot.canvas.authorization.session, own.root);
  const jsx = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
  const begin = jsx.indexOf('  const projectedAuthorization =');
  const end = jsx.indexOf('  const availableWorkshops', begin);
  assert.ok(begin > 0 && end > begin);
  const context = vm.createContext({session: {id: snapshot.canvas.root}, workshopState: snapshot});
  vm.runInContext(jsx.slice(begin, end) + '\nglobalThis.ready = workspaceReady;', context);
  assert.equal(context.ready, true);
});
