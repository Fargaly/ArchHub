const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..', '..');

const authorityPath = path.join(root, '01.APP/nodelang/studio/studio-authority.js');

test('authority projection creates a session node whose params and tab settings share one source', async () => {
  const source = fs.readFileSync(authorityPath, 'utf8');
  let canvas = {ok:true, root:'session-root', graph_id:'graph-root', revision:1,
    scope:{current_label:'MASTER-001'}, authorization:{browser_sessions:[{root:'session-root'}]},
    configuration:{composer_model:{value:'openrouter/free', available:true, control:'model-control', event_fact_input:'submitted-value'}, relay_mode:'local'},
    interaction_projection:{bindings:[{control:'model-control', interaction:'i', event:'e', event_facts:[]}]},
    nodes:[{id:'workshop', label:'Workshop', category:'group', kind:'group', x:0, y:0, ports:[], properties:[], composition:true}],
    wires:[], workshops:[{root:'workshop', label:'Workshop'}], catalog:[]};
  const context = vm.createContext({URLSearchParams, sessionStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
    crypto:{randomUUID:() => 'cmd', subtle:{digest:async () => new Uint8Array([1])}}, TextEncoder});
  vm.runInContext(source, context);
  const writes = [];
  const api = context.ArchHubStudioAuthority.create({get:async () => canvas, post:async (url, body) => {
    writes.push({url, body});
    canvas = {...canvas, revision:canvas.revision + 1,
      configuration:{...canvas.configuration, composer_model:{...canvas.configuration.composer_model, value:body.event_facts[0].value}}};
    return {ok:true, revision:canvas.revision};
  }});
  await api.load();
  const snapshot = api.getSnapshot();
  const sessionNode = snapshot.graph.nodes.find(node => node.kind === 'session');
  assert.ok(sessionNode, 'new session is projected as a real node');
  assert.ok(sessionNode.contains.includes('workshop'), 'session node contains the Workshop group');
  await api.setProperty(sessionNode.id, 'model', 'lmstudio/local-free');
  assert.equal(writes.at(-1).url, '/api/universal/interaction');
  assert.equal(JSON.stringify(writes.at(-1).body.event_facts), JSON.stringify([{input:'submitted-value', value:'lmstudio/local-free'}]));
  assert.equal(api.getSnapshot().sessions[0].model, 'lmstudio/local-free');
  assert.equal(api.getSnapshot().graph.nodes.find(node => node.kind === 'session').params.find(row => row.k === 'name').editable, false);
  assert.equal(api.getSnapshot().graph.nodes.find(node => node.kind === 'session').params.find(row => row.k === 'relay mode').editable, false);
});
