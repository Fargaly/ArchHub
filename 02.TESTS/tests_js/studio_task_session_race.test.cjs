'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const structuredClone = globalThis.structuredClone;

test('a canvas edit during an in-flight task save keeps the edited nodes and viewport', async () => {
  const file = {
    format: 'archhub', version: 1, id: 'doc-alpha', title: 'Alpha',
    nodes: [{id: 'wall', type: 'note', title: 'Wall', params: {}, position: {x: 10, y: 20}}],
    wires: [], groups: [], notes: [], viewport: {x: 0, y: 0, zoom: 1}, properties: {revision: 1},
  };
  const stale = {
    ...file,
    nodes: [{id: 'wall', type: 'note', title: 'Wall', params: {}, position: {x: 1, y: 1}}],
    viewport: {x: 0, y: 0, zoom: 1},
    properties: {revision: 4},
  };
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let workshopStarted = false;
  const calls = [];
  const context = {
    console, structuredClone, URLSearchParams, AbortSignal, setTimeout, clearTimeout,
    setInterval: () => 0, clearInterval() {},
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options && options.detail; } },
    document: {hidden: true, addEventListener() {}},
    crypto: {randomUUID: () => 'req-' + calls.length},
    sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    ARCHHUB_BOOT: {token: 'fixture', csrf: 'fixture'},
    addEventListener() {}, dispatchEvent() {},
    fetch: async (url, init = {}) => {
      const body = init.body ? JSON.parse(init.body) : null;
      calls.push({url, body});
      let data = {ok: true, result: [], items: [], recent: [], directory: 'mem', messages: [], agents: [], providers: []};
      if (url === '/api/universal/settings-action' && body?.function === 'readLibraryCollapsed') data = {ok: true, result: {libraryCollapsed: []}};
      else if (url === '/api/session-files' && body?.action === 'initial') data = {ok: true, document: structuredClone(file), path: 'C:/isolated/alpha.archhub'};
      else if (url === '/api/session-files' && body?.action === 'autosave') data = {ok: true, path: body.path, revision: (body.document.properties?.revision || 0) + 1, document: body.document};
      else if (url === '/api/session-files' && body?.action === 'read') data = {ok: true, path: body.path, revision: 9, document: structuredClone(stale)};
      else if (url === '/api/universal/workshop' && body?.function === 'listWorkshopMessages') data = {ok: true, result: {messages: []}};
      else if (url === '/api/universal/workshop' && body?.function === 'setTaskSession') {
        workshopStarted = true;
        await gate;
        data = {ok: true, result: {
          id: file.id, path: 'C:/isolated/alpha.archhub', taskId: 'task-1', scope: 'during',
          rules: [], agents: [], plan: [], progress: {}, workflow: [], parameters: [], activity: [],
          folders: [], references: [], messages: [],
        }};
      }
      return {ok: true, status: 200, json: async () => data};
    },
  };
  context.window = context;
  vm.createContext(context);
  for (const name of ['studio-authority.js', 'api.js']) {
    vm.runInContext(fs.readFileSync(path.join(studio, name), 'utf8'), context, {filename: name});
  }
  await context.ArchHubAPI.ready;
  const pending = context.ArchHubAPI.setTaskSession('task-1', {scope: 'during'});
  const started = Date.now();
  while (!workshopStarted) {
    if (Date.now() - started > 3000) throw new Error('task save did not reach the workshop');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  await context.ArchHubAPI.moveNodes({wall: {x: 48, y: 64}});
  context.ArchHubAPI.setSessionViewport({x: 12, y: 24, zoom: 2});
  release();
  await pending;
  const kept = context.ArchHubAPI.getSessionDocument();
  assert.deepEqual(kept.nodes.find(node => node.id === 'wall').position, {x: 48, y: 64});
  assert.deepEqual(kept.viewport, {x: 12, y: 24, zoom: 2});
  assert.equal(calls.some(call => call.body?.action === 'read'), false);
});

test('a refused or slow library-collapse read still opens the initial session expanded', async () => {
  const file = {
    format: 'archhub', version: 1, id: 'doc-alpha', title: 'Alpha',
    nodes: [{id: 'wall', type: 'note', title: 'Wall', params: {}, position: {x: 10, y: 20}}],
    wires: [], groups: [], notes: [], viewport: {x: 0, y: 0, zoom: 1}, properties: {revision: 1},
  };
  let releaseSettings;
  const settingsGate = new Promise(resolve => { releaseSettings = resolve; });
  let initialSeen = false;
  const notices = [];
  const context = {
    console, structuredClone, URLSearchParams, AbortSignal, setTimeout, clearTimeout,
    setInterval: () => 0, clearInterval() {},
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options && options.detail; } },
    document: {hidden: true, addEventListener() {}},
    crypto: {randomUUID: () => 'req-collapse'},
    sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    ARCHHUB_BOOT: {token: 'fixture', csrf: 'fixture'},
    addEventListener() {}, dispatchEvent(event) { notices.push(event.detail && event.detail.message); },
    fetch: async (url, init = {}) => {
      const body = init.body ? JSON.parse(init.body) : null;
      if (url === '/api/universal/settings-action' && body?.function === 'readLibraryCollapsed') {
        await settingsGate;
        return {ok: true, status: 200, json: async () => ({ok: true, result: []})};
      }
      let data = {ok: true, result: [], items: [], recent: [], directory: 'mem', messages: [], agents: [], providers: []};
      if (url === '/api/session-files' && body?.action === 'initial') {
        initialSeen = true;
        data = {ok: true, document: structuredClone(file), path: 'C:/isolated/alpha.archhub'};
      }
      return {ok: true, status: 200, json: async () => data};
    },
  };
  context.window = context;
  vm.createContext(context);
  for (const name of ['studio-authority.js', 'api.js']) {
    vm.runInContext(fs.readFileSync(path.join(studio, name), 'utf8'), context, {filename: name});
  }
  const ready = context.ArchHubAPI.ready;
  const started = Date.now();
  while (!initialSeen) {
    if (Date.now() - started > 3000) throw new Error('initial session waited on library collapse');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  await ready;
  await context.ArchHubAPI.moveNodes({wall: {x: 48, y: 64}});
  assert.deepEqual(context.ArchHubAPI.getSessionDocument().nodes.find(node => node.id === 'wall').position, {x: 48, y: 64});
  releaseSettings();
  const noticed = Date.now();
  while (!notices.includes('Settings owner did not confirm the action. Refresh and retry.')) {
    if (Date.now() - noticed > 3000) throw new Error('settings validation did not refuse the array result');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  const collapsed = context.ArchHubAPI.getSnapshot().libraryCollapsed;
  assert.ok(Array.isArray(collapsed) && collapsed.length === 0);
  assert.deepEqual(context.ArchHubAPI.getSessionDocument().nodes.find(node => node.id === 'wall').position, {x: 48, y: 64});
});
