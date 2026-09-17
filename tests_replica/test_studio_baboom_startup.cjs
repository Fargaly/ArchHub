/* Court C: Studio changes BABOOM startup only through the Personal Settings write path.
 *
 * RED-first: on source without api.setBaboomStartup, the 'baboom-startup' kind of
 * changeTheme, BaboomStartupRow and a regenerated compiled Studio, every case fails.
 * The design (archhub/project studio-lm.jsx:2441-2454) has no BABOOM tab, so the startup choice is
 * a row in the design's own Settings > Hosts list; the tab table stays the design's twelve.
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)]
  .map(match => [match[1], match[2]]));
const CONTROL = 'app:appearance-control:0123456789abcdef0123456789abcdef';
const SUBMITTED = 'app:event-fact:submitted-value:v1';
const SWITCH = '[aria-label="Start BABOOM when ArchHub opens"]';
const TAKES_EFFECT = /Takes effect next time ArchHub opens\./;
const startup = (changes = {}) => ({value:'on', source:'default', revision:null, actor:null, available:true,
  control:CONTROL, event_fact_input:SUBMITTED, effect:'next-launch', error:null, ...changes});
const unavailable = {available:false, control:null, event_fact_input:null};
const unreadable = {...unavailable, value:null, source:'unreadable', error:'InvalidCell'};
const committedDelta = value => ({ok:true, committed_revision:11, revision:11, base_revision:10,
  projection_mode:'interaction-delta-v1', control_state:{controls:[{owner:'app:control:canvas:undo'}]},
  configuration_state:{baboom_startup:startup({value, source:'graph', revision:'revision:startup:1', actor:'owner'})},
  interaction_projection:{revision:11, bindings:[]}});
const refusal = (message, status) => Object.assign(new Error(message), status ? {status} : {});
const disabled = element => element.disabled === true || element.getAttribute('aria-disabled') === 'true';

function transport({post, setting = startup(), heads = ['draft']}) {
  const context = vm.createContext({window:{}, TextEncoder});
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), context);
  const fields = Object.entries(seed).map(([key, value]) => ({key, value, control:'control:'+key,
    event_fact_input:'input:'+key, token_root:'token:'+key}));
  const binding = (control, input, maximum) => ({control, interaction:'interaction:'+control,
    event:'app:interaction-event:change', projection_mode:'interaction-delta-v1', acknowledgement_mode:'receipt-v1',
    event_facts:[{input, value_kind:'text', maximum_bytes:maximum}]});
  const bindings = fields.map(field => binding(field.control, field.event_fact_input, 7));
  if (setting.control) bindings.push(binding(setting.control, SUBMITTED, 65536));
  const canvas = {revision:10, application_root:'app', authorization:{subject:'owner', session:'view'},
    scope:{current:'scope'}, interaction_projection:{revision:10, bindings},
    configuration:{theme:seed, theme_fields:fields, history:[], personal_wip_heads:heads, baboom_startup:setting}};
  const posts = [];
  let reads = 0;
  const api = context.window.ArchHubExistingWorkshop.create({
    get:async url => { assert.equal(url, '/api/universal/canvas'); reads++; return canvas; },
    post:async (url, body) => { posts.push({url, body:plain(body)}); return post(url, body); },
  });
  assert.ok(api.setThemeCanvas(canvas), 'fixture canvas is an accepted Personal Settings projection');
  return {api, posts, reads:() => reads};
}

test('turning startup off sends exactly one admitted interaction and confirms it from the delta', async () => {
  const fixture = transport({post:async () => committedDelta('off')});
  const result = await fixture.api.setBaboomStartup('off');
  assert.equal(result.committed_revision, 11);
  assert.deepEqual(fixture.posts, [{url:'/api/universal/interaction', body:{interaction:'interaction:'+CONTROL,
    control:CONTROL, event:'app:interaction-event:change', revision:10, projection_mode:'interaction-delta-v1',
    event_facts:[{input:SUBMITTED, value:'off'}]}}]);
  assert.equal(fixture.reads(), 1, 'one fresh read before the write and none after');
  const theme = fixture.api.getSnapshot().theme;
  assert.equal(theme.configuration.baboom_startup.value, 'off');
  assert.equal(theme.error, '');
  assert.equal(theme.pending, false);
});

test('a committed write whose delta does not show the new value is reported saved and never retried', async () => {
  const fixture = transport({post:async () => committedDelta('on')});
  await assert.rejects(async () => fixture.api.setBaboomStartup('off'), /Saved in Personal Settings; refresh/);
  assert.equal(fixture.posts.length, 1);
  assert.equal(fixture.api.getSnapshot().theme.configuration, null);
});

test('a lost response stays unknown and is never resubmitted', async () => {
  const fixture = transport({post:async () => { throw refusal('connection lost'); }});
  await assert.rejects(async () => fixture.api.setBaboomStartup('off'), /Save outcome unknown/);
  assert.equal(fixture.posts.length, 1);
  assert.equal(fixture.reads(), 1);
  assert.equal(fixture.api.getSnapshot().theme.configuration, null);
});

for (const status of [400, 409]) {
  test(`a definite ${status} refusal refreshes once and never resubmits`, async () => {
    const fixture = transport({post:async () => { throw refusal('expected revision 10, current revision is 12', status); }});
    await assert.rejects(async () => fixture.api.setBaboomStartup('off'),
      /BABOOM startup was not changed\. Review the refreshed setting and try again\./);
    assert.equal(fixture.posts.length, 1);
    assert.equal(fixture.reads(), 2, 'the fresh read, then exactly one refresh');
    assert.ok(fixture.api.getSnapshot().theme.configuration, 'the refreshed setting is shown');
  });
}

test('two theme drafts do not block the BABOOM startup change', async () => {
  const fixture = transport({heads:['one', 'two'], post:async () => committedDelta('off')});
  await fixture.api.setBaboomStartup('off');
  assert.equal(fixture.posts.length, 1);
});

for (const [name, setting] of [['another subject', startup(unavailable)], ['an unreadable setting', startup(unreadable)]]) {
  test(`${name} is refused locally with no write`, async () => {
    const fixture = transport({setting, post:async () => assert.fail('write sent for an unavailable setting')});
    await assert.rejects(async () => fixture.api.setBaboomStartup('off'), /BABOOM startup cannot be changed from this view\./);
    assert.equal(fixture.posts.length, 0);
  });
}

test('values other than on/off and the current value are refused before any write', async () => {
  const fixture = transport({post:async () => assert.fail('write sent for a refused value')});
  await assert.rejects(async () => fixture.api.setBaboomStartup('enabled'), /BABOOM startup must be on or off\./);
  assert.equal(fixture.reads(), 0, 'the value is checked before any read');
  await assert.rejects(async () => fixture.api.setBaboomStartup('on'), /BABOOM startup is already on\./);
  assert.equal(fixture.posts.length, 0);
});

test('a second change while one is in flight is refused and only one write is sent', async () => {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const fixture = transport({post:() => held});
  const first = fixture.api.setBaboomStartup('off');
  await assert.rejects(async () => fixture.api.setBaboomStartup('off'), /Wait for the current theme save to finish\./);
  release(committedDelta('off'));
  await first;
  assert.equal(fixture.posts.length, 1);
});

function loadTokens(theme) {
  const window = {ARCHHUB_THEME:theme};
  vm.runInContext(read('nodelang/studio/tokens.jsx'), vm.createContext({window}));
  return window;
}

async function withSettingsBaboom(state, api, check) {
  const source = read('nodelang/studio/studio-lm.jsx');
  const start = source.indexOf('const BaboomStartupRow = ({ first }) =>');
  const end = source.indexOf('// ── Theme / Shortcuts / Storage / About (lighter, but real)');
  assert.ok(start >= 0 && end > start, 'studio-lm.jsx declares BaboomStartupRow immediately before the Theme panel');
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const window = loadTokens(seed);
  window.ARCHHUB_EXISTING_WORKSHOP = api;
  const context = vm.createContext({window, React, LM:window.AH, usePersonalTheme:() => state,
    SHead:({title}) => React.createElement('h3', null, title)});
  vm.runInContext(transformSync(source.slice(start, end)+'\nglobalThis.Component=BaboomStartupRow;',
    {loader:'jsx', format:'cjs'}).code, context);
  const rootNode = createRoot(dom.window.document.getElementById('root'));
  try {
    await React.act(async () => rootNode.render(React.createElement(context.Component)));
    await check(dom.window.document, React.act);
  } finally {
    await React.act(async () => rootNode.unmount());
    dom.window.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
}

test('rendered BABOOM Settings flips the shown value with one call and says when it takes effect', async () => {
  for (const [setting, source, next] of [
    [startup(), /Default \(on\)/, 'off'],
    [startup({value:'off', source:'graph', revision:'revision:startup:1', actor:'owner'}), /Saved/, 'on'],
  ]) {
    const calls = [];
    await withSettingsBaboom({configuration:{baboom_startup:setting}, pending:false},
      {setBaboomStartup:async value => { calls.push(value); }}, async (document, act) => {
        const toggle = document.querySelector(SWITCH);
        assert.ok(toggle, 'the startup switch is rendered');
        assert.equal(disabled(toggle), false);
        assert.match(document.body.textContent, source);
        assert.match(document.body.textContent, TAKES_EFFECT);
        await act(async () => { toggle.click(); });
        assert.deepEqual(calls, [next]);
      });
  }
});

test('rendered BABOOM Settings is disabled and says why when the setting cannot be changed', async () => {
  const refuse = {setBaboomStartup:async () => assert.fail('write from a disabled switch')};
  for (const [state, api, reasons] of [
    [{configuration:{baboom_startup:startup(unreadable)}}, refuse, [/Setting unreadable/, /will not start/, /InvalidCell/]],
    [{configuration:{baboom_startup:startup(unavailable)}}, refuse, [/Only the owner of this ArchHub can change this\./]],
    [{configuration:{}}, refuse, [/Settings not read/]],
    [{configuration:{baboom_startup:startup()}, pending:true}, refuse, []],
    [{configuration:{baboom_startup:startup()}, pending:false}, undefined, []],
  ]) {
    await withSettingsBaboom(state, api, async document => {
      const toggle = document.querySelector(SWITCH);
      assert.ok(toggle, 'the startup switch is rendered');
      assert.equal(disabled(toggle), true);
      for (const reason of reasons) assert.match(document.body.textContent, reason);
      assert.match(document.body.textContent, TAKES_EFFECT);
    });
  }
});

test('shipped Studio tree carries the BABOOM startup switch as a row of Settings > Hosts, with no BABOOM tab', async () => {
  assert.ok(read('nodelang/studio/compiled/studio-lm.js').includes('Start BABOOM when ArchHub opens'),
    'compiled Studio was regenerated from studio-lm.jsx');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener(){}, removeEventListener(){}});
  win.fetch = () => new Promise(() => {}); // court sandbox: the mounted Studio talks to a server that never answers
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  try {
    for (const file of manifest.files) {
      if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/'+file.output));
    }
    win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
    const settings = win.document.querySelector('[title="Settings"]');
    assert.ok(settings, 'actual Studio Settings control exists');
    win.ReactDOM.flushSync(() => settings.click());
    const tabs = [...win.document.querySelectorAll('button')].filter(button => button.firstElementChild?.textContent);
    assert.equal(tabs.some(button => button.firstElementChild.textContent === 'BABOOM'), false, 'the design draws no BABOOM tab');
    const hosts = tabs.find(button => button.firstElementChild.textContent === 'Hosts');
    assert.ok(hosts, 'actual Settings Hosts tab exists');
    win.ReactDOM.flushSync(() => hosts.click());
    const toggle = win.document.querySelector(SWITCH);
    assert.ok(toggle, 'actual BABOOM startup switch exists in the Hosts list');
    assert.equal(toggle.parentElement.querySelector(':scope > div > div').textContent, 'BABOOM', 'the row is named like a host row');
    assert.equal(disabled(toggle), true, 'no Workshop API and no read setting means no write');
    assert.match(win.document.body.textContent, TAKES_EFFECT);
  } finally {
    if (win.__studioRoot) win.ReactDOM.flushSync(() => win.__studioRoot.unmount());
    dom.window.close();
  }
});
