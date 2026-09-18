/* The shipped picker mounted over two independent discoveries.
   2026-09-18: the founder's picker showed "Discovering models from connected providers..."
   and "Discovering open agent sessions..." and never filled in, with an expired cloud
   sign-in drawing nothing at all. Whichever source answers first is drawn; whatever has
   not answered by the deadline says so in its own place; a stale list says it is stale.
   The shipped studio-lm.jsx runs here. No application, provider, network or graph. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const jsx = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const LM = new Proxy({rad:{xs:3, sm:5, md:6, lg:8, xl:10}, sp:{xs:4, sm:8, md:12}},
  {get:(held, key) => key in held ? held[key] : 'token'});
const DOCS = '// ' + '─'.repeat(24) + ' DOCS';
const CLOUD = 'CLOUD · subscription';
const BYO = 'BYO · OpenRouter';
const SIGN_IN = "The cloud refused this machine's sign-in: it expired or was revoked. " +
  'Sign in again under Settings, Account.';
const ROW = {name:'Model A', route:'vendor/model-a', routed:'openrouter/vendor/model-a',
  vendor:'vendor', tag:'BYO', ctx:'8k', cost:'', col:'#3a6acc'};
const CATALOGUE = {ok:true, live:true, count:1, groups:[{name:BYO, items:[ROW]}], selected_route:''};
const AGENTS = {ok:true, status:'ok', rows:[]};

function slice(open, close) {
  const start = jsx.indexOf(open), end = jsx.indexOf(close, start + open.length);
  assert.ok(start >= 0 && end > start, 'a slice of the shipped source: ' + open);
  return jsx.slice(start, end);
}

async function picker({models = 'pending', agents = 'pending'} = {}) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const timers = [];
  const answer = value => value === 'pending' ? new Promise(() => {})
    : Promise.resolve({ok:true, status:200, json:async () => JSON.parse(JSON.stringify(value))});
  const fetch = url => String(url).startsWith('/api/universal/models') ? answer(models) : answer(agents);
  const context = vm.createContext({React, LM, window:{__archhubSession:{}, AH:{}}, fetch,
    AbortController, kbd:() => ({}), console, Promise, JSON, String, Error, Math, Object, Array,
    setTimeout:(fn, ms) => timers.push({fn, ms}), clearTimeout:id => { if (timers[id - 1]) timers[id - 1].done = true; }});
  vm.runInContext(transformSync(slice('const modelRoute = ', 'const nodeModelRow = ') +
    slice('const pickerSwatch = ', DOCS) + '\nglobalThis.ModelPicker = ModelPicker;',
    {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(dom.window.document.getElementById('root'));
  const settle = async () => {
    for (let turn = 0; turn < 12; turn += 1) {
      await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 2)); });
    }
  };
  await React.act(async () => root.render(React.createElement(context.ModelPicker, {
    setModel:async () => {}, onClose:() => {}, onNativeSelect:async () => {},
    model:{name:'Choose a model', route:'', routed:''}})));
  await settle();
  const body = () => dom.window.document.body.textContent;
  const held = selector => [...dom.window.document.querySelectorAll(selector)];
  const expire = async () => {
    const armed = timers.filter(timer => !timer.done && timer.ms === 8000);
    assert.equal(armed.length, 1, 'exactly one discovery deadline is armed');
    await React.act(async () => { armed[0].fn(); });
    await settle();
  };
  return {body, held, expire, settle, timers};
}

test('the models answer draws while native discovery is still out, and the deadline names it', async () => {
  const panel = await picker({models:CATALOGUE, agents:'pending'});
  assert.match(panel.body(), /Model A/, 'the answered source is drawn without waiting for the other');
  assert.match(panel.body(), /Discovering open agent sessions/);
  await panel.expire();
  assert.match(panel.body(), /Model A/, 'the rows already drawn stay drawn');
  assert.match(panel.body(), /Native session discovery did not answer within 8 seconds/);
  assert.doesNotMatch(panel.body(), /Discovering open agent sessions/,
    'the panel still says it is discovering after the deadline');
});

test('neither discovery leaves the panel discovering for ever', async () => {
  const panel = await picker();
  assert.match(panel.body(), /Discovering models from connected providers/);
  await panel.expire();
  assert.match(panel.body(), /Model discovery did not answer within 8 seconds/);
  assert.match(panel.body(), /Native session discovery did not answer within 8 seconds/);
});

test('a source that gave no rows says so where its rows would have been', async () => {
  const panel = await picker({models:{...CATALOGUE, source_notes:{[CLOUD]:SIGN_IN}}, agents:AGENTS});
  const drawn = panel.held('[data-picker-source-note]');
  assert.equal(drawn.length, 1, 'the silent source has a place of its own in the list');
  assert.equal(drawn[0].getAttribute('data-picker-source-note'), CLOUD);
  assert.match(drawn[0].textContent, /CLOUD/);
  assert.match(drawn[0].textContent, /Sign in again under Settings, Account\./);
  assert.match(panel.body(), /Model A/, 'the sources that did answer are still drawn');
});

test('a stale list says it is stale rather than passing for new', async () => {
  const panel = await picker({models:{...CATALOGUE, stale:true, age_seconds:97.4, refreshing:true}, agents:AGENTS});
  const mark = panel.held('[data-picker-stale]');
  assert.equal(mark.length, 1, 'the stale answer is marked on screen');
  assert.match(mark[0].textContent, /Showing the list last discovered/);
  assert.match(mark[0].textContent, /97s old/);
  assert.match(mark[0].textContent, /refreshing now/);
  assert.match(panel.body(), /Model A/, 'the stale rows are usable while the refresh runs');
  assert.ok(panel.timers.some(timer => timer.ms === 2500 && !timer.done),
    'nothing collects the refresh running behind the stale answer');
});
