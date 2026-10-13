const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const React = require('react');
const ReactDOMClient = require('react-dom/client');
const {JSDOM} = require('jsdom');

global.IS_REACT_ACT_ENVIRONMENT = true;

function extractFunction(source, name) {
  const found = new RegExp('var ' + name + '\\s*=\\s*function').exec(source);
  const start = found ? found.index : -1;
  assert.notEqual(start, -1, name + ' not found in compiled Studio');
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) {
        const semi = source.indexOf(';', i);
        return source.slice(start, semi + 1);
      }
    }
  }
  throw new Error('could not extract ' + name);
}

function extractSettings(source) {
  return [
    extractFunction(source, 'HostEnableSwitch'),
    extractFunction(source, 'SettingsHosts'),
  ].join('\n');
}

function loadSettingsHosts(overrides = {}) {
  const compiled = path.join(__dirname, '..', 'nodelang', 'studio', 'compiled', 'studio-lm.js');
  const source = fs.readFileSync(compiled, 'utf8');
  const code = extractSettings(source);
  const context = {
    React,
    LM: {
      bg: '#fff', bgPanel: '#f8f8f8', line: '#ddd', ink: '#111',
      inkMuted: '#777', err: '#b00020', ok: '#178a42', warn: '#a66a00',
      inkSoft: '#555', bgHover: '#eee', mono: 'monospace', sans: 'Arial',
      rad: {xs: 4, md: 6, lg: 8},
    },
    smallBtn: () => ({}),
    hostDisplayName: host => host?.name || host?.id || 'Host',
    hostStateWord: host => host?.state === 'connected' ? 'Connected' : 'Absent',
    hostStateTone: host => host?.state === 'connected' ? '#178a42' : '#777',
    hostDetail: host => host?.detail || '',
    hostOpenPhrase: () => '',
    useLiveCatalogue: () => ({loading: false, error: '', retry() {}}),
    SettingsEmpty: ({children}) => React.createElement('div', null, children),
    SettingsAssistants: () => null,
    SettingsOperations: () => null,
    CONNECTORS_NOT_BUILT: [],
    requestToolHubRefresh: () => Promise.resolve(),
    loadCatalogue: () => {
      context.loadCatalogueCalls += 1;
      return Promise.resolve();
    },
    loadCatalogueCalls: 0,
    catalogueStates: new Map([['ARCHHUB_LOAD_HOSTS', {read: true}]]),
    catalogueChanged: () => {},
    notifyToolHubSubscribers: () => {},
    toolHubSnapshot: null,
    toolHubSnapshotSignature: '',
    _objectSpread: (target, ...sources) => Object.assign(target, ...sources),
    LM_HOSTS: [{id: 'revit', name: 'Revit', enabled: true}],
    window: global.window,
    ...overrides,
  };
  return {
    Component: vm.runInNewContext(code + '\nSettingsHosts;', context),
    context,
  };
}

async function mountSettings(fetchImpl, hosts) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', {url: 'http://127.0.0.1/'});
  global.window = dom.window;
  global.document = dom.window.document;
  global.navigator = dom.window.navigator;
  window.__archhubSession = {token: 't', csrf: 'c'};
  window.ARCHHUB_LIVE = {connectors: hosts};
  window.ARCHHUB_LOAD_HOSTS = async () => ({hosts: window.ARCHHUB_LIVE.connectors, connectors: window.ARCHHUB_LIVE.connectors});
  window.fetch = fetchImpl;
  const loaded = loadSettingsHosts({LM_HOSTS: hosts});
  const root = ReactDOMClient.createRoot(document.getElementById('root'));
  await React.act(async () => {
    root.render(React.createElement(loaded.Component));
  });
  return {dom, root, context: loaded.context};
}

test('Settings Connectors renders one host-enable switch per program row', async () => {
  await mountSettings(async () => {
    throw new Error('no fetch expected before click');
  }, [
    {id: 'revit', name: 'Revit', state: 'connected', detail: 'fake session', enabled: true},
    {id: 'blender', name: 'Blender', state: 'absent', detail: 'fake absent', enabled: false},
  ]);
  const rows = [...document.querySelectorAll('[data-connector-row]:not([data-not-built])')];
  const switches = [...document.querySelectorAll('[role="switch"]')];
  assert.equal(rows.length, 2);
  assert.equal(switches.length, rows.length);
  assert.deepEqual(switches.map(sw => sw.getAttribute('aria-checked')), ['true', 'false']);
  assert.match(document.body.textContent, /Blender is turned off in Settings . Connectors\./);
});

test('Settings Connectors switch posts the toggle and re-reads host/tool state', async () => {
  const calls = [];
  const hosts = [
    {id: 'revit', name: 'Revit', state: 'connected', detail: 'fake session', enabled: true},
    {id: 'blender', name: 'Blender', state: 'absent', detail: 'fake absent', enabled: false},
  ];
  const mounted = await mountSettings(async (url, options = {}) => {
    calls.push(String(url));
    if (String(url) === '/api/universal/host-enabled') {
      const body = JSON.parse(options.body);
      assert.deepEqual(body, {host_id: 'blender', enabled: true});
      assert.equal(options.headers['X-ArchHub-Session'], 't');
      assert.equal(options.headers['X-ArchHub-CSRF'], 'c');
      return {ok: true, json: async () => ({ok: true, host: {id: 'blender', name: 'Blender', enabled: true}})};
    }
    if (String(url) === '/tools') {
      return {ok: true, json: async () => ({ok: true, tools: [{id: 'connectors', hosts: [{id: 'blender', enabled: true}]}]})};
    }
    return {ok: true, json: async () => ({ok: true, items: []})};
  }, hosts);
  await React.act(async () => {
    document.querySelectorAll('[role="switch"]')[1].click();
    await new Promise(resolve => setTimeout(resolve, 80));
  });
  assert.deepEqual(calls.slice(0, 2), ['/api/universal/host-enabled', '/tools']);
  assert.equal(mounted.context.loadCatalogueCalls, 1);
  assert.equal(hosts[1].enabled, true);
});
