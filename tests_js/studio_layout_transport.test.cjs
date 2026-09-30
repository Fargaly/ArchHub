/* Real adapter callbacks with isolated responses; no browser or live owner. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({URLSearchParams});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-existing-workshop.js'), 'utf8'), context);
const create = context.ArchHubExistingWorkshop.create;
const plain = value => JSON.parse(JSON.stringify(value));
function fixture(change = {}) {
  return {ok:true, application_root:'app', revision:4,
    authorization:{subject:'founder', session:'view'}, scope:{current:'scope'},
    nodes:[{id:'a',x:0,y:0},{id:'b',x:1,y:1}], wires:[],
    interaction_projection:{revision:4,bindings:[]}, ...change};
}
function setup({post, get}={}) {
  let canvas=fixture(); const posts=[];
  const api=create({get:async()=>get ? get(canvas) : structuredClone(canvas),
    post:async(url,body)=>{
      posts.push({url,body:plain(body)});
      if(post) return post(url,body);
      canvas=fixture({revision:5,interaction_projection:{revision:5,bindings:[]},
        nodes:canvas.nodes.map(node=>({...node,...body.positions[node.id]}))});
      return {ok:true,projection_mode:'receipt-v1',base_revision:4,committed_revision:5};
    }, projectCanvas:value=>({nodes:value.nodes,wires:value.wires})});
  api.setTopologyCanvas(canvas);
  return {api,posts};
}
test('group move saves one map and adopts confirmed owner positions',async()=>{
  const {api,posts}=setup(); const positions={a:{x:120,y:70},b:{x:430,y:70}};
  await api.moveTopologyNodes(positions,4);
  assert.equal(posts.length,1);
  assert.equal(posts[0].url,'/api/universal/gesture');
  assert.deepEqual(posts[0].body,{expected_scope:'scope',positions,expected_positions:{a:{x:0,y:0},b:{x:1,y:1}},
    projection_mode:'receipt-v1',projection_revision:4});
  assert.equal(api.getSnapshot().topology.canvas.revision,5);
  assert.deepEqual(plain(api.getSnapshot().topology.graph.nodes),[{id:'a',...positions.a,pinned:true},{id:'b',...positions.b,pinned:true}]);
});
test('changed moved-node positions and absent nodes never submit a write',async()=>{
  // The save checks the canvas this client HOLDS (one request per drag); the owner
  // re-checks the same facts under its lock, so nothing is taken on trust.
  const stale=setup();
  stale.api.setTopologyCanvas(fixture({revision:5,interaction_projection:{revision:5,bindings:[]},
    nodes:[{id:'a',x:50,y:0},{id:'b',x:1,y:1}]}));
  await assert.rejects(stale.api.moveTopologyNodes({a:{x:1,y:2}},4,{a:{x:0,y:0}}),/changed position/);
  assert.equal(stale.posts.length,0);
  const hidden=setup();
  await assert.rejects(hidden.api.moveTopologyNodes({hidden:{x:1,y:2}},4),/no longer/);
  assert.equal(hidden.posts.length,0);
});

test('unrelated revisions before read and locked save preserve the layout position comparison',async()=>{
  let durable=fixture({revision:5,interaction_projection:{revision:5,bindings:[]}});
  const {api,posts}=setup({get:()=>durable,post:(_url,body)=>{
    assert.equal(body.projection_revision,5);
    assert.equal(posts.length,1,'one request per drag: the save is the only call');
    assert.deepEqual(plain(body.expected_positions),{a:{x:0,y:0}});
    durable=fixture({revision:7,interaction_projection:{revision:7,bindings:[]},nodes:[{id:'a',x:80,y:90},{id:'b',x:1,y:1}]});
    return {ok:true,projection_mode:'receipt-v1',base_revision:6,committed_revision:7};
  }});
  api.setTopologyCanvas(durable);
  await api.moveTopologyNodes({a:{x:80,y:90}},4,{a:{x:0,y:0}});
  assert.equal(posts.length,1);assert.equal(api.getSnapshot().topology.canvas.revision,7);
});

test('the save carries the scope and principal it was drawn under, and an owner refusal adopts nothing',async()=>{
  // The scope and principal are no longer re-read before the write: they travel WITH it
  // (expected_scope, and the session the command is signed under), and the owner refuses
  // under its lock if either moved. A refusal must leave the held canvas untouched.
  const {api,posts}=setup({post:()=>({ok:false, error:'scope changed under the save'})});
  const before=plain(api.getSnapshot().topology.canvas);
  await assert.rejects(api.moveTopologyNodes({a:{x:10,y:20}},4),/reconcil|scope|changed/i);
  assert.equal(posts.length,1);
  assert.equal(posts[0].body.expected_scope,'scope');
  assert.deepEqual(plain(api.getSnapshot().topology.canvas),before,'a refused save changes nothing here');
});

const signedContext=vm.createContext({URLSearchParams});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../nodelang/studio/studio-authority.js'),'utf8'),signedContext);
const signedCreate=signedContext.ArchHubStudioAuthority.create;
const signedCanvas=(revision=4,extra={})=>({ok:true,graph_id:'app',root:'scope',revision,
  nodes:[{id:'a',x:0,y:0},{id:'b',x:1,y:1}],wires:[],...extra});

test('signed layout accepts unrelated graph advance and sends exact gesture base positions',async()=>{
  let durable=signedCanvas(),posts=[];
  const api=signedCreate({get:async()=>durable,post:async(_url,body)=>{
    posts.push(plain(body));
    return signedCanvas(7,{nodes:[{id:'a',x:30,y:40},{id:'b',x:1,y:1}]});
  }});
  await api.load();durable=signedCanvas(6);await api.load();
  await api.moveMany({a:{x:30,y:40}},4,{a:{x:0,y:0}});
  assert.deepEqual(posts,[{expected_scope:'scope',positions:{a:{x:30,y:40}},
    expected_positions:{a:{x:0,y:0}},projection_revision:6}]);
  assert.equal(api.getSnapshot().canvas.revision,7);
});

test('signed layout refuses changed node bases or queued cross-scope move without posting',async()=>{
  let durable=signedCanvas(),posts=[];
  const api=signedCreate({uuid:()=> 'command-a',get:async()=>durable,
    post:async(url,body)=>{posts.push({url,body});return signedCanvas(6,{root:'other'});}});
  await api.load();durable=signedCanvas(5,{nodes:[{id:'a',x:99,y:0}],
    interaction_projection:{bindings:[{control:'open-other'}]}});await api.load();
  await assert.rejects(api.moveMany({a:{x:30,y:40}},4,{a:{x:0,y:0}}),/changed position/);
  const navigation=api.open('open-other');const moving=api.moveMany({a:{x:30,y:40}},5);
  await navigation;
  await assert.rejects(moving,/scope/);
  assert.equal(posts.length,1);
  assert.equal(posts[0].url,'/api/universal/interaction');
});
test('uncertain save blocks another write until explicit refresh',async()=>{
  const {api,posts}=setup({post:()=>{throw Error('response lost');}});
  await assert.rejects(api.moveTopologyNodes({a:{x:1,y:2}},4),/response lost/);
  assert.equal(posts.length,1);
  assert.equal(api.getSnapshot().topology.requires_refresh,true);
  await assert.rejects(api.moveTopologyNodes({a:{x:1,y:2}},4),/Read the canvas/);
  assert.equal(posts.length,1);
});

test('shared node selection commits only selection and restores through a fresh graph read', async()=>{
  let durable=fixture();
  const first=setup({get:()=>durable,post:(url,body)=>{
    assert.equal(url,'/api/universal/gesture');
    assert.deepEqual(plain(body),{roots:['b'],focus:'b',expected_scope:'scope'});
    durable=fixture({selected:'b',revision:5,interaction_projection:{revision:5,bindings:[]}});
    return durable;
  }});
  await first.api.selectTopology('b');
  assert.equal(first.api.getSnapshot().topology.selected,'b');
  assert.equal(first.posts.length,1);
  const fresh=setup({get:()=>durable});
  await fresh.api.refreshTopologyCanvas();
  assert.equal(fresh.api.getSnapshot().topology.selected,'b');
  assert.equal(fresh.posts.length,0);
});

test('selection refuses hidden nodes and foreign or unconfirmed responses',async()=>{
  const hidden=setup();
  await assert.rejects(hidden.api.selectTopology('hidden'),/current canvas/);
  assert.equal(hidden.posts.length,0);
  for(const change of [{selected:'a'},{scope:{current:'other'}},
      {authorization:{subject:'other',session:'view'}},{authorization:{subject:'founder',session:'other'}}]) {
    const row=setup({post:()=>fixture({selected:'b',revision:5,
      interaction_projection:{revision:5,bindings:[]},...change})});
    await assert.rejects(row.api.selectTopology('b'),/reconciliation/);
    assert.equal(row.api.getSnapshot().topology.selected,undefined);
    assert.equal(row.api.getSnapshot().topology.requires_refresh,true);
  }
});

test('selection response loss allows read reconciliation without another selection write',async()=>{
  let durable=fixture();
  const row=setup({get:()=>durable,post:()=>{
    durable=fixture({selected:'b',revision:5,interaction_projection:{revision:5,bindings:[]}});
    throw Error('response lost');
  }});
  await assert.rejects(row.api.selectTopology('b'),/response lost/);
  await row.api.refreshTopologyCanvas();
  assert.equal(row.api.getSnapshot().topology.selected,'b');
  assert.equal(row.posts.length,1);
});
