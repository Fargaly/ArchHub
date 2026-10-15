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
    extractFunction(source, 'hostRunningState'),
    extractFunction(source, 'isOfficeHost'),
    extractFunction(source, 'hostConnectorRows'),
    extractFunction(source, 'hostTally'),
    extractFunction(source, 'HostEnableSwitch'),
    extractFunction(source, 'hostPanelStateWord'),
    extractFunction(source, 'hostPanelStateTone'),
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
      rad: {chip:3, xs:3, control:5, sm:5, node:6, md:6, panel:8, lg:8, dialog:10, xl:10, pill:999},
      sp: {xs:4, sm:8, md:12, lg:16, xl:24},
      fs: {bodySm:{sz:13, ln:18, wt:400}, bodySmStrong:{sz:13, ln:18, wt:500}, caption:{sz:12, ln:16}, label:{sz:11, ln:14, wt:500, letter:'.04em'}, dataSm:{sz:11, ln:14}},
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
    toolHubFetchOptions: () => ({headers: {'X-ArchHub-Session':'t', 'X-ArchHub-CSRF':'c'}}),
    toolHubSnapshot: null,
    toolHubSnapshotSignature: '',
    _objectSpread: (target, ...sources) => Object.assign(target, ...sources),
    _toConsumableArray: value => Array.from(value),
    LM_HOSTS: [{id: 'revit', name: 'Revit', enabled: true}],
    window: global.window,
    ...overrides,
  };
  return {
    Component: vm.runInNewContext(code + '\nSettingsHosts;', context),
    context,
  };
}

async function mountSettings(fetchImpl, hosts, overrides = {}) {
  const dom = new JSDOM('<!doctype html><div id="root"></div>', {url: 'http://127.0.0.1/'});
  global.window = dom.window;
  global.document = dom.window.document;
  global.navigator = dom.window.navigator;
  window.__archhubSession = {token: 't', csrf: 'c'};
  window.ARCHHUB_LIVE = {connectors: hosts};
  window.ARCHHUB_LOAD_HOSTS = async () => ({hosts: window.ARCHHUB_LIVE.connectors, connectors: window.ARCHHUB_LIVE.connectors});
  window.fetch = fetchImpl;
  const loaded = loadSettingsHosts({LM_HOSTS: hosts, ...overrides});
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

test('Settings Connectors Office aggregate is display-only and child switches keep owner state separate', async () => {
  const calls = [];
  const hosts = [
    {id: 'excel', name: 'Excel', state: 'running', detail: 'workbook open', enabled: true, enabled_state: 'confirmed'},
    {id: 'word', name: 'Word', state: 'running', detail: 'document open', enabled: true, enabled_state: 'confirmed'},
    {id: 'powerpoint', name: 'PowerPoint', state: 'running', detail: 'deck open', enabled: true, enabled_state: 'confirmed'},
    {id: 'revit', name: 'Revit', state: 'connected', detail: 'fake session', enabled: true, enabled_state: 'confirmed'},
  ];
  await mountSettings(async (url, options = {}) => {
    calls.push(String(url));
    if (String(url) === '/api/universal/host-enabled') {
      const body = JSON.parse(options.body);
      assert.deepEqual(body, {host_id: 'word', enabled: false});
      return {ok: true, json: async () => ({ok: true, host: {id: 'word', name: 'Word', enabled: false, enabled_state: 'confirmed'}})};
    }
    if (String(url) === '/tools') {
      return {ok: true, json: async () => ({ok: true, tools: [{id: 'connectors', hosts}]})};
    }
    return {ok: true, json: async () => ({ok: true, items: []})};
  }, hosts);
  const aggregate = [...document.querySelectorAll('[data-connector-row]')]
    .find(row => row.textContent.includes('Excel') && row.textContent.includes('PowerPoint') && !row.hasAttribute('data-office-child'));
  assert.ok(aggregate, 'Office aggregate row is present');
  assert.equal(aggregate.querySelector('[role="switch"]'), null, 'Office aggregate has no switch');
  assert.match(aggregate.textContent, /3 of 3 on/);
  const childRows = [...document.querySelectorAll('[data-office-child]')];
  assert.deepEqual(childRows.map(row => row.querySelector('[role="switch"]').getAttribute('aria-label').match(/^Turn ([^ ]+)/)[1]),
    ['Excel', 'Word', 'PowerPoint']);
  const wordSwitch = childRows[1].querySelector('[role="switch"]');
  await React.act(async () => {
    wordSwitch.click();
    await new Promise(resolve => setTimeout(resolve, 80));
  });
  assert.deepEqual(calls.slice(0, 2), ['/api/universal/host-enabled', '/tools']);
  assert.equal(hosts.find(host => host.id === 'word').enabled, false);
  assert.equal(hosts.find(host => host.id === 'excel').enabled, true);
  assert.equal(hosts.find(host => host.id === 'powerpoint').enabled, true);
  assert.equal(hosts.find(host => host.id === 'revit').enabled, true);
  assert.equal(childRows[1].querySelector('[role="switch"]').getAttribute('aria-checked'), 'false');
  assert.equal(document.querySelector('[data-office-child] [aria-label^="Turn Excel"]').getAttribute('aria-checked'), 'true');
  assert.match(aggregate.textContent, /2 of 3 on/);
});

test('Settings Connectors renders in-flight unknown authority state as checking and disabled', async () => {
  const reason = "Can't change this right now: ArchHub's graph service is unavailable.";
  const calls = [];
  const hosts = [
    {id: 'revit', name: 'Revit', state: 'connected', detail: 'fake session', enabled: false, enabled_state: 'unknown', enable_disabled_reason: reason},
    {id: 'autocad', name: 'AutoCAD', state: 'connected', detail: 'fake session', enabled: false, enabled_state: 'unknown', enable_disabled_reason: reason},
  ];
  await mountSettings(async url => {
    calls.push(String(url));
    return {ok: true, json: async () => ({ok: true})};
  }, hosts, {useLiveCatalogue: () => ({loading: true, error: '', retry() {}})});
  const rows = [...document.querySelectorAll('[data-connector-row]:not([data-not-built])')];
  const switches = [...document.querySelectorAll('[role="switch"]')];
  assert.equal(rows.length, 2);
  assert.equal(switches.length, 2);
  assert.equal(switches.filter(sw => sw.disabled).length, 2);
  assert.deepEqual(switches.map(sw => sw.getAttribute('aria-checked')), ['false', 'false']);
  assert.match(document.body.textContent, /Checking…/);
  assert.doesNotMatch(document.body.textContent, /ArchHub's graph service is unavailable\./);
  assert.doesNotMatch(document.body.textContent, /turned off in Settings/);
  await React.act(async () => {
    switches[0].click();
    await new Promise(resolve => setTimeout(resolve, 20));
  });
  assert.deepEqual(calls, []);
});

test('Settings Connectors renders settled unknown authority failure with reason and Retry', async () => {
  const reason = "Can't change this right now: ArchHub's graph service is unavailable.";
  const calls = [];
  const hosts = [
    {id: 'revit', name: 'Revit', state: 'connected', detail: 'fake session', enabled: false, enabled_state: 'unknown', enable_disabled_reason: reason},
  ];
  const mounted = await mountSettings(async url => {
    calls.push(String(url));
    return {ok: true, json: async () => ({ok: true, tools: []})};
  }, hosts);
  const sw = document.querySelector('[role="switch"]');
  assert.equal(sw.disabled, true);
  assert.match(sw.getAttribute('aria-label'), /graph service is unavailable/);
  assert.match(sw.getAttribute('title'), /graph service is unavailable/);
  assert.doesNotMatch(document.body.textContent, /Checking…/);
  assert.match(document.body.textContent, /Unavailable\./);
  assert.match(document.body.textContent, /ArchHub's graph service is unavailable\./);
  const retry = [...document.querySelectorAll('button')].find(button => button.textContent === 'Retry');
  assert.ok(retry, 'settled failure offers Retry');
  await React.act(async () => {
    retry.click();
    await new Promise(resolve => setTimeout(resolve, 20));
  });
  assert.deepEqual(calls, ['/tools']);
  assert.equal(mounted.context.loadCatalogueCalls, 1);
});

test('Settings Connectors renders settled unknown authority failure with fallback reason and Retry', async () => {
  const calls = [];
  const hosts = [
    {id: 'revit', name: 'Revit', state: 'connected', detail: 'fake session', enabled_state: 'unknown'},
  ];
  await mountSettings(async url => {
    calls.push(String(url));
    return {ok: true, json: async () => ({ok: true, tools: []})};
  }, hosts);
  const sw = document.querySelector('[role="switch"]');
  assert.equal(sw.disabled, true);
  assert.match(sw.getAttribute('aria-label'), /Could not read this host's state\./);
  assert.doesNotMatch(document.body.textContent, /Checking…/);
  assert.match(document.body.textContent, /Unavailable\. Could not read this host's state\./);
  const retry = [...document.querySelectorAll('button')].find(button => button.textContent === 'Retry');
  assert.ok(retry, 'settled failure without backend reason offers Retry');
  await React.act(async () => {
    retry.click();
    await new Promise(resolve => setTimeout(resolve, 20));
  });
  assert.deepEqual(calls, ['/tools']);
});

test('Settings Connectors refused mutation leaves the displayed state unchanged', async () => {
  const calls = [];
  const hosts = [
    {id: 'revit', name: 'Revit', state: 'connected', detail: 'fake session', enabled: true, enabled_state: 'confirmed'},
  ];
  await mountSettings(async url => {
    calls.push(String(url));
    return {ok: false, json: async () => ({ok: false, error: 'owner refused'})};
  }, hosts);
  const sw = document.querySelector('[role="switch"]');
  assert.equal(sw.getAttribute('aria-checked'), 'true');
  await React.act(async () => {
    sw.click();
    await new Promise(resolve => setTimeout(resolve, 80));
  });
  assert.deepEqual(calls, ['/api/universal/host-enabled']);
  assert.equal(hosts[0].enabled, true);
  assert.equal(document.querySelector('[role="switch"]').getAttribute('aria-checked'), 'true');
  assert.match(document.body.textContent, /owner refused/);
});
