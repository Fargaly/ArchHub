/* Work the product canvas does not draw: the rail points to the Workshop and the Workshop still reads it. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const adapter = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/studio-existing-workshop.js'), 'utf8');
const runtime = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/ui_runtime.py'), 'utf8');

test('selecting hidden Work for review goes through the existing gesture', async () => {
  const ctx = vm.createContext({URLSearchParams, TextEncoder});
  vm.runInContext(adapter, ctx);
  const canvas = selected => ({application_root:'application-a', revision:1, selected,
    authorization:{subject:'owner-a', session:'view-a'}, scope:{current:'scope-a'},
    nodes:[{id:'node-a'}], wires:[], hidden_work:[{id:'work-a', title:'Work A'}],
    interaction_projection:{revision:1, bindings:[]}});
  const posts = [];
  const api = ctx.ArchHubExistingWorkshop.create({
    uuid:() => 'id', pendingStorage:{getItem:() => null, setItem:() => {}},
    get:async () => canvas('node-a'),
    post:async (url, body) => { posts.push({url, body}); return canvas(body.roots[0]); }});
  api.setTopologyCanvas(canvas('node-a'));
  const result = await api.selectTopology('work-a');
  assert.equal(result.selected, 'work-a');
  assert.deepEqual(JSON.parse(JSON.stringify(posts)), [{url:'/api/universal/gesture',
    body:{roots:['work-a'], focus:'work-a', expected_scope:'scope-a'}}]);
  await assert.rejects(api.selectTopology('work-b'), /Choose a node in the current canvas scope/);
});

test('an interaction delta holds the lens scalars when absent and never carries the list', () => {
  const start = runtime.indexOf('  const interactionDeltaMode=');
  const end = runtime.indexOf('\n  function scheduleRedraw(', start);
  assert.ok(start > 0 && end > start);
  const context = vm.createContext({lastProjection:null});
  vm.runInContext(runtime.slice(start, end) + '\nglobalThis.merge = mergeProjectionDelta;', context);
  const base = {revision:4, selected:'work-a', selection:[], selection_hidden:true, hidden_work_count:1,
    hidden_work:[{id:'work-a', title:'Work A'}], nodes:[], wires:[], configuration:{design_system:{}}};
  const delta = extra => ({projection_mode:'interaction-delta-v1', base_revision:4, revision:5, selected:'node-a',
    selection:['node-a'], control_state:{controls:[]}, configuration_state:{}, node_count:0, wire_count:0,
    node_states:[], wire_states:[], ...extra});
  const held = context.merge(delta({}), base);
  assert.equal(held.selection_hidden, true);
  assert.equal(held.hidden_work_count, 1);
  assert.deepEqual(held.hidden_work, [{id:'work-a', title:'Work A'}]);
  const changed = context.merge(delta({selection_hidden:false, hidden_work_count:2}), base);
  assert.equal(changed.selection_hidden, false);
  assert.equal(changed.hidden_work_count, 2);
  assert.ok(!/'hidden_work'/.test(runtime.slice(runtime.indexOf('const interactionDeltaFields='),
    runtime.indexOf('];', runtime.indexOf('const interactionDeltaFields=')))));
});
