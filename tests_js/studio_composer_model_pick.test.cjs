/* The model picker saves a composer pick as the owner's graph-held setting before the header shows it.
   2026-09-17 the founder's header read "Choose a model / No provider selected" after an update with
   provider keys on the machine: a pick only set page state until a Send reached the server.
   The shipped picker wiring, the shipped studio.html bridge and the shipped Workshop transport run here
   against fixtures; no application, provider or network. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const jsx = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio.html'), 'utf8');
const workshopSource = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-existing-workshop.js'), 'utf8');
const LM = new Proxy({rad:{xs:3, sm:5, md:6, lg:8, xl:10}, sp:{xs:4, sm:8, md:12}}, {get:(held, key) => key in held ? held[key] : 'token'});
const ROW = {name:'Model A', route:'vendor/model-a', routed:'openrouter/vendor/model-a', vendor:'vendor', tag:'BYO', ctx:'8k', cost:'$0 / $0 per M', col:'#3a6acc'};
const DOCS = '// ' + '\u2500'.repeat(24) + ' DOCS';

function slice(open, close, source = jsx) {
  const start = source.indexOf(open), end = source.indexOf(close, start + open.length);
  assert.ok(start >= 0 && end > start, 'a slice of the shipped source: ' + open);
  return source.slice(start, end);
}
function wiring(scope) {
  const {transformSync} = require('esbuild');
  const helpers = slice('const modelRoute = ', 'const nodeModelRow = ');
  const open = '{pickerOpen && <ModelPicker setModel={';
  const arrow = slice(open, '} onClose={() => setPickerOpen(false)}').slice(open.length);
  const context = vm.createContext({LM, Promise, Error, String, ...scope});
  vm.runInContext(transformSync(helpers + '\nglobalThis.choose = ' + arrow + ';', {loader:'jsx', format:'cjs'}).code, context);
  return context;
}
function spies(select) {
  const log = [];
  return {log, window:{ARCHHUB_AGENT_SELECT:async route => { log.push(['select', route]); return select(route); }},
    setModel:value => log.push(['model', value]), setHomeNative:value => log.push(['native', value])};
}
function themeCanvas(composer, revision = 7) {
  const fields = Array.from({length:35}, (_, index) => ({key:'k' + index, value:'#000000', control:'c' + index,
    event_fact_input:'app:event-fact:submitted-value:v1', token_root:'t' + index}));
  return {revision, application_root:'app:root', authorization:{subject:'owner', session:'session'}, scope:{current:'scope'},
    interaction_projection:{revision, bindings:[{control:'app:appearance-control:composer', interaction:'app:interaction:composer',
      event:'app:interaction-event:change', projection_mode:'interaction-delta-v1', acknowledgement_mode:'receipt-v1',
      event_facts:[{input:'app:event-fact:submitted-value:v1', value_kind:'text', maximum_bytes:65536}]}]},
    configuration:{theme:Object.fromEntries(fields.map(field => [field.key, field.value])), theme_fields:fields,
      history:[], personal_wip_heads:['wip'], composer_model:composer}};
}
const SETTING = {value:'', source:'default', revision:null, available:true, control:'app:appearance-control:composer',
  event_fact_input:'app:event-fact:submitted-value:v1', effect:'next-send', error:null};
function server(initial = {...SETTING}) {
  const state = {current:initial, revision:7, gets:0, posts:[]};
  const refusal = message => Object.assign(new Error(message), {status:400});
  state.transport = {
    get:async url => { assert.equal(url, '/api/universal/canvas'); state.gets += 1; return themeCanvas(state.current, state.revision); },
    post:async (url, body) => {
      assert.equal(url, '/api/universal/interaction');
      state.posts.push(JSON.parse(JSON.stringify(body)));
      if (body.revision !== state.revision) throw refusal('expected revision ' + body.revision + ', current revision is ' + state.revision);
      const value = body.event_facts[0].value;
      if (value === 'no-provider-route') throw refusal('Model route ' + JSON.stringify(value) + ' names no provider');
      if (state.current.source === 'graph' && state.current.value === value) throw refusal('composer model is already ' + JSON.stringify(value));
      state.current = {...state.current, value, source:'graph', revision:'rev-' + state.posts.length};
      state.revision += 1;
      return {ok:true, projection_mode:'interaction-delta-v1', base_revision:state.revision - 1, committed_revision:state.revision,
        revision:state.revision, control_state:{controls:[{}]}, configuration_state:{composer_model:state.current},
        interaction_projection:{revision:state.revision, bindings:themeCanvas(state.current, state.revision).interaction_projection.bindings}};
    },
    projectCanvas:value => value};
  return state;
}
function workshopFor(state) {
  const context = vm.createContext({URLSearchParams, TextEncoder});
  vm.runInContext(workshopSource, context);
  const workshop = context.ArchHubExistingWorkshop.create(state.transport);
  workshop.setThemeCanvas(themeCanvas(state.current, state.revision));
  return workshop;
}

test('studio.html saves the pick through the Workshop transport, beside the composer bridge', async () => {
  const bridge = html.indexOf('window.ARCHHUB_AGENT_SELECT');
  assert.ok(bridge > html.indexOf('window.ARCHHUB_AGENT ='), 'defined beside the composer bridge');
  const source = slice('window.ARCHHUB_AGENT_SELECT = ', '\n    };\n', html) + '\n    };';
  const calls = [];
  const context = vm.createContext({window:{ARCHHUB_EXISTING_WORKSHOP:{setComposerModel:async value => {
    calls.push(value); return {configuration_state:{composer_model:{value}}}; }}}, Error});
  vm.runInContext(source, context);
  assert.equal(await context.window.ARCHHUB_AGENT_SELECT('openrouter/free'), 'openrouter/free');
  assert.deepEqual(calls, ['openrouter/free']);
  context.window.ARCHHUB_EXISTING_WORKSHOP = null;
  await assert.rejects(context.window.ARCHHUB_AGENT_SELECT('openrouter/free'), /cannot save a model selection/);
});

test('the Workshop transport posts one owner interaction and a pick the graph holds posts nothing', async () => {
  const state = server();
  const workshop = workshopFor(state);
  const saved = await workshop.setComposerModel('openrouter/vendor/model-a');
  assert.equal(saved.configuration_state.composer_model.value, 'openrouter/vendor/model-a');
  assert.equal(state.posts.length, 1);
  assert.deepEqual(state.posts[0].event_facts, [{input:'app:event-fact:submitted-value:v1', value:'openrouter/vendor/model-a'}]);
  assert.equal(state.posts[0].control, 'app:appearance-control:composer');
  const again = await workshop.setComposerModel('openrouter/vendor/model-a');
  assert.equal(again.unchanged, true);
  assert.equal(state.posts.length, 1, 'a pick equal to the graph-held one writes nothing');
  await assert.rejects(async () => workshop.setComposerModel('two words'), /model route is invalid/);
  assert.equal(state.posts.length, 1);
});

test('a clear posts while only an older build holds a pick, and is unchanged once the graph holds none', async () => {
  const state = server({...SETTING, value:'', source:'default'});
  const workshop = workshopFor(state);
  const cleared = await workshop.setComposerModel('');
  assert.equal(cleared.unchanged, undefined, 'the graph had no binding, so the clear is written');
  assert.equal(state.posts.length, 1);
  assert.deepEqual(state.posts[0].event_facts, [{input:'app:event-fact:submitted-value:v1', value:''}]);
  assert.deepEqual([state.current.source, state.current.value], ['graph', '']);
  const again = await workshop.setComposerModel('');
  assert.equal(again.unchanged, true);
  assert.equal(state.posts.length, 1);
});

test('a pick saves on the held view without a canvas read; a stale view is read once, then saved', async () => {
  const state = server();
  const workshop = workshopFor(state);
  await workshop.setComposerModel('openrouter/vendor/model-a');
  await workshop.setComposerModel('openrouter/vendor/model-b');
  assert.deepEqual([state.gets, state.posts.length, state.current.value], [0, 2, 'openrouter/vendor/model-b'],
    'back-to-back picks commit on the revision each save returned');
  state.revision += 1;
  const saved = await workshop.setComposerModel('openrouter/vendor/model-c');
  assert.equal(saved.configuration_state.composer_model.value, 'openrouter/vendor/model-c');
  assert.deepEqual([state.gets, state.posts.length], [1, 4], 'a revision the graph moved past is refused, read once and saved');
  assert.deepEqual(state.posts.slice(2).map(body => body.revision), [9, 10]);
  const again = await workshop.setComposerModel('openrouter/vendor/model-c');
  assert.equal(again.unchanged, true);
  assert.deepEqual([state.gets, state.posts.length], [2, 4], 'unchanged is only answered from a fresh read');
  await assert.rejects(async () => workshop.setComposerModel('no-provider-route'), /names no provider/);
  assert.deepEqual([state.gets, state.posts.length], [2, 5], 'a refusal that is not a stale revision is shown, not retried');
  assert.equal(state.current.value, 'openrouter/vendor/model-c');
});

test('a canvas or Home pick is saved before the header changes; a refusal changes nothing', async () => {
  for (const scope of [{session:{id:'graph-a'}}, {session:null}]) {
    const ok = spies(route => route);
    const picked = wiring({...scope, modelTarget:null, window:ok.window, setModel:ok.setModel, setHomeNative:ok.setHomeNative});
    await picked.choose(ROW);
    assert.deepEqual(ok.log[0], ['select', 'openrouter/vendor/model-a'], 'the routable string is saved first');
    assert.deepEqual(ok.log.filter(row => row[0] === 'model').map(row => row[1].routed), ['openrouter/vendor/model-a']);
    const refused = spies(() => { throw new Error('The model selection changed before this save. Pick the model again.'); });
    const denied = wiring({...scope, modelTarget:null, window:refused.window, setModel:refused.setModel, setHomeNative:refused.setHomeNative});
    await assert.rejects(Promise.resolve().then(() => denied.choose(ROW)), /Pick the model again/);
    assert.deepEqual(refused.log.map(row => row[0]), ['select'], 'no header change without the graph holding it');
  }
  const cleared = spies(route => route);
  const clear = wiring({session:{id:'graph-a'}, modelTarget:null, window:cleared.window, setModel:cleared.setModel, setHomeNative:cleared.setHomeNative});
  await clear.choose({name:'Choose a model', route:'', routed:''});
  assert.deepEqual(cleared.log[0], ['select', '']);
  const shown = cleared.log.find(row => row[0] === 'model')[1];
  assert.equal(shown.vendor, 'No model selected', 'an empty pick never claims there is no provider');
});

test('the signed clean engine keeps a Home pick as page state instead of failing', async () => {
  const log = [];
  const home = wiring({session:null, modelTarget:null, window:{ARCHHUB_STUDIO_AUTHORITY:{}},
    setModel:value => log.push(['model', value]), setHomeNative:value => log.push(['native', value])});
  await home.choose(ROW);
  assert.deepEqual(log.map(row => row[0]), ['native', 'model']);
  assert.equal(log[1][1].routed, 'openrouter/vendor/model-a');
  const canvas = wiring({session:{id:'graph-a'}, modelTarget:null, window:{ARCHHUB_STUDIO_AUTHORITY:{}},
    setModel:() => assert.fail('no page state for a canvas pick without a node'), setHomeNative:() => {}});
  await assert.rejects(Promise.resolve().then(() => canvas.choose(ROW)), /Select an AI node/);
  const bare = wiring({session:null, modelTarget:null, window:{}, setModel:() => assert.fail('not saved'), setHomeNative:() => {}});
  await assert.rejects(Promise.resolve().then(() => bare.choose(ROW)), /cannot save a model selection/);
});

test('the rendered picker saves the clicked row and shows a refusal in place', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const root = createRoot(dom.window.document.getElementById('root'));
  try {
    for (const refuse of [false, true]) {
      const log = spies(route => { if (refuse) throw new Error('The model selection cannot be saved from this view.'); return route; });
      const picked = wiring({session:{id:'graph-a'}, modelTarget:null, window:log.window, setModel:log.setModel, setHomeNative:log.setHomeNative});
      const fetch = async url => ({ok:true, json:async () => String(url).startsWith('/api/universal/models')
        ? {ok:true, live:true, count:1, groups:[{name:'BYO', items:[ROW]}], selected_route:''} : {ok:false}});
      // The picker now keeps a discovery deadline, so its sandbox owns a clock.
      const context = vm.createContext({React, LM, window:{__archhubSession:{}, AH:{}}, fetch, AbortController,
        kbd:() => ({}), console, Promise, JSON, String, Error, Math, Object,
        setTimeout, clearTimeout});
      vm.runInContext(transformSync(slice('const modelRoute = ', 'const nodeModelRow = ') +
        slice('const pickerSwatch = ', DOCS) + '\nglobalThis.ModelPicker = ModelPicker;',
        {loader:'jsx', format:'cjs'}).code, context);
      let closed = 0;
      await React.act(async () => root.render(React.createElement(context.ModelPicker, {
        setModel:picked.choose, onClose:() => { closed += 1; }, model:{name:'Choose a model', route:'', routed:''}})));
      const settle = async done => {
        for (let turn = 0; turn < 100 && !done(); turn += 1) {
          await React.act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
        }
      };
      const drawn = () => [...dom.window.document.querySelectorAll('div')].filter(node =>
        node.style.cursor === 'pointer' && node.textContent.startsWith('MModel A'));
      await settle(() => drawn().length > 0);
      const rows = drawn();
      assert.equal(rows.length, 1, 'the live row is drawn once');
      await React.act(async () => { rows[0].click(); });
      await settle(() => refuse ? !!dom.window.document.querySelector('[role="alert"]') : closed > 0);
      assert.deepEqual(log.log[0], ['select', 'openrouter/vendor/model-a']);
      if (refuse) {
        assert.equal(closed, 0);
        assert.match(dom.window.document.querySelector('[role="alert"]').textContent, /cannot be saved from this view/);
      } else {
        assert.equal(closed, 1);
        assert.equal(log.log.filter(entry => entry[0] === 'model').length, 1);
      }
      await React.act(async () => root.render(null));
    }
  } finally {
    await React.act(async () => root.unmount());
    dom.window.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});
