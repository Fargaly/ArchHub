/* The model picker saves a composer pick as the owner's graph-held setting before the header shows it.
   2026-09-17 the founder's header read "Choose a model / No provider selected" after an update with
   provider keys on the machine: a pick only set page state until a Send reached the server.
   The shipped picker wiring, the shipped studio.html bridge and the shipped Workshop transport run here
   against fixtures; no application, provider or network. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const workshopSource = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/studio-existing-workshop.js'), 'utf8');

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
