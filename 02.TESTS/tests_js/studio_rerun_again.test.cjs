// F10: Rerun is Run again — node menu, Properties (same nodeCommand owner), and Inspector
// appShell.Rerun.60 pass again=true; Run to here stays a fresh root run.
// Court loads compiled Studio when present, else babel-transforms the full source file
// (no absolute user paths; no source-text regex / snippet eval).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const studio = path.join(root, '01.APP/nodelang/studio');

const REGISTRY = {
  contexts: ['node'],
  palette_order: ['trigger'],
  commands: [
    {id: 'menu.rerun', label: 'Rerun', group: 'trigger', contexts: ['node'], action: {client: 'api.runNode', binding: 'menu.rerun'}, effect: true, approve: true, agent_callable: false, read_only: false, operation: 'write', enabled_when: {}, icon: 'refresh', shortcut: 'R', danger: false, order: 39},
    {id: 'menu.run.to.here', label: 'Run to here', group: 'trigger', contexts: ['node'], action: {client: 'api.runToHere', binding: 'menu.run.to.here'}, effect: true, approve: true, agent_callable: false, read_only: false, operation: 'write', enabled_when: {}, icon: 'play', shortcut: '', danger: false, order: 40},
    {id: 'menu.fork', label: 'Fork', group: 'transform', contexts: ['node'], action: {client: 'api.forkNode', binding: 'menu.fork'}, effect: false, approve: false, agent_callable: false, read_only: false, operation: 'write', enabled_when: {}, icon: 'canvas', shortcut: '', danger: false, order: 77},
  ],
};

function compileClassic(sourceName, {presets = ['react', 'env'], preferCompiled = true} = {}) {
  const compiledName = sourceName.replace(/\.jsx$/, '.js');
  const compiledPath = path.join(studio, 'compiled', compiledName);
  // Prefer compiled Studio when present; else full-file babel of tip source (never regex-slice).
  if (preferCompiled && fs.existsSync(compiledPath)) {
    return fs.readFileSync(compiledPath, 'utf8');
  }
  const sourcePath = path.join(studio, sourceName);
  assert.ok(fs.existsSync(sourcePath), sourceName + ' missing');
  const babelPath = path.join(studio, 'vendor/babel.js');
  assert.ok(fs.existsSync(babelPath), 'vendor/babel.js missing for Studio compile');
  const compiler = {};
  vm.createContext(compiler);
  vm.runInContext(fs.readFileSync(babelPath, 'utf8'), compiler);
  const raw = fs.readFileSync(sourcePath, 'utf8');
  return compiler.Babel.transform(raw, {presets, sourceMaps: false}).code;
}

function recordingApi() {
  const calls = [];
  const api = {
    runNode: (id, again) => { calls.push(['runNode', id, again]); return {ok: true}; },
    runToHere: (id, again) => { calls.push(['runToHere', id, again]); return {ok: true}; },
    forkNode: (id) => { calls.push(['forkNode', id]); return {ok: true}; },
    setNodeFlags: (id, flags) => { calls.push(['setNodeFlags', id, flags]); return {ok: true}; },
  };
  return {api, calls};
}

function loadContextMenus(api) {
  const calls = [];
  const record = (owner, name) => (...args) => {
    calls.push([owner + '.' + String(name), ...args.filter((x) => typeof x !== 'function')]);
    return {ok: true};
  };
  const state = {
    graph: {nodes: [{id: 'node-1', title: 'middle', type: 'data.constant', inputs: [], outputs: [], parameterSchema: []}], wires: []},
    tasks: [],
  };
  const u = new Proxy({
    canvasTabs: {tabs: []},
    act: (fn) => fn(),
    show: record('u', 'show'),
    setSelectedNodeId: record('u', 'setSelectedNodeId'),
    setTaskFace: record('u', 'setTaskFace'),
    schedule: record('u', 'schedule'),
    trace: record('u', 'trace'),
    go: record('u', 'go'),
  }, {get: (target, key) => target[key] || record('u', key)});
  const actionState = {run: (fn) => fn()};
  const sandbox = {
    window: {
      innerWidth: 1400,
      innerHeight: 900,
      UI: {api},
      ArchHubCommandRegistry: REGISTRY,
      registerActions() {},
      executeAction() {},
    },
    api,
    navigator: {clipboard: {writeText: async () => {}}},
    React: {
      useRef: () => ({current: null}),
      useState: (v) => [v, () => {}],
      useLayoutEffect: () => {},
      createElement: (type, props, ...children) => ({type, props: props || {}, children}),
    },
    console,
    Reflect,
  };
  sandbox.window.UI.useAction = () => actionState;
  sandbox.window.UI.useData = () => state;
  sandbox.window.UI.useApp = () => u;
  sandbox.window.UI.bindActions = () => (_id, fn, event) => fn(event);
  sandbox.window.UI.shortcutFor = () => '';
  sandbox.window.UI.ActionStatus = () => null;
  sandbox.window.AHIcon = () => null;
  vm.createContext(sandbox);
  // Tip source (full-file babel): compiled/ is gitignored and may lag again=true on disk.
  vm.runInContext(compileClassic('context-menus.jsx', {preferCompiled: false}), sandbox);
  assert.equal(typeof sandbox.window.UI.nodeCommand, 'function');
  assert.equal(typeof sandbox.window.UI.contextCommandGroups, 'function');
  return {sandbox, state, u, actionState, calls};
}

function loadAppShell(api) {
  const handlers = {};
  let actionMap = null;
  class Component {}
  const rootHost = {render() {}};
  const sandbox = {
    window: {
      UI: {},
      ReactDOM: {createRoot: () => rootHost},
      registerActions(map, fns) {
        actionMap = map;
        Object.assign(handlers, fns);
        sandbox.window.executeAction = (id, ctx, event) => {
          const name = actionMap[id];
          assert.ok(name && handlers[name], 'missing appShell action ' + id);
          return handlers[name](ctx, event);
        };
      },
      executeAction(...args) {
        return sandbox.window.executeAction(...args);
      },
      addEventListener() {},
      removeEventListener() {},
    },
    document: {getElementById: () => ({})},
    api,
    console,
    Reflect,
    React: {
      Component,
      PureComponent: Component,
      useRef: () => ({current: null}),
      useState: (v) => [v, () => {}],
      useEffect: () => {},
      useLayoutEffect: () => {},
      useMemo: (fn) => fn(),
      useCallback: (fn) => fn,
      createElement: (type, props, ...children) => ({type, props: props || {}, children}),
      Fragment: 'Fragment',
    },
    ReactDOM: {createRoot: () => rootHost},
  };
  sandbox.window.document = sandbox.document;
  vm.createContext(sandbox);
  // Tip source, react-only preset: registerActions runs; no env class rewrite needed.
  vm.runInContext(compileClassic('app.jsx', {presets: ['react'], preferCompiled: false}), sandbox);
  assert.ok(actionMap && actionMap['appShell.Rerun.60'], 'appShell.Rerun.60 registered');
  return sandbox;
}

function findAction(groups, commandId) {
  for (const rows of groups) {
    for (const row of rows) {
      if (row.command?.id === commandId || row[0] && REGISTRY.commands.find((c) => c.label === row[0])?.id === commandId) {
        return row[3];
      }
      if (Array.isArray(row) && row.command?.id === commandId) return row[3];
    }
  }
  return null;
}

test('NODE_COMMANDS menu.rerun calls runNode with again=true', () => {
  const {api, calls} = recordingApi();
  const {sandbox} = loadContextMenus(api);
  sandbox.window.UI.nodeCommand('menu.rerun', {id: 'node-1'});
  assert.deepEqual(calls, [['runNode', 'node-1', true]]);
});

test('node menu Rerun path executes nodeCommand(menu.rerun) with again=true', async () => {
  const {api, calls} = recordingApi();
  const {sandbox, state, u, actionState} = loadContextMenus(api);
  const groups = sandbox.window.UI.contextCommandGroups(
    {kind: 'Node menu', nodeId: 'node-1', selected: ['node-1'], close: () => {}},
    state, u, actionState, false,
  );
  const action = findAction(groups, 'menu.rerun');
  assert.ok(typeof action === 'function', 'Node menu Rerun action present');
  await action();
  assert.deepEqual(calls, [['runNode', 'node-1', true]]);
});

test('Inspector Rerun (appShell.Rerun.60) calls runNode with again=true', () => {
  const {api, calls} = recordingApi();
  const sandbox = loadAppShell(api);
  sandbox.window.executeAction('appShell.Rerun.60', {
    api,
    n: {id: 'node-1'},
    saved: (fn) => fn(),
  });
  assert.deepEqual(calls, [['runNode', 'node-1', true]]);
});

test('Run to here stays a fresh root run without forcing again', async () => {
  const {api, calls} = recordingApi();
  const {sandbox, state, u, actionState} = loadContextMenus(api);
  const groups = sandbox.window.UI.contextCommandGroups(
    {kind: 'Node menu', nodeId: 'node-1', selected: ['node-1'], close: () => {}},
    state, u, actionState, false,
  );
  const action = findAction(groups, 'menu.run.to.here');
  assert.ok(typeof action === 'function', 'Node menu Run to here action present');
  await action();
  assert.deepEqual(calls, [['runToHere', 'node-1', undefined]]);
});
