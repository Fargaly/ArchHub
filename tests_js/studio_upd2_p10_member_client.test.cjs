/* The two real Studio transport clients share one remove-member implementation. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const plain = value => JSON.parse(JSON.stringify(value));
function context() {
  const ctx = vm.createContext({TextEncoder, URLSearchParams,
    crypto:{randomUUID:() => 'command-p10'}});
  for (const file of ['studio-authority.js', 'studio-existing-workshop.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../nodelang/studio', file), 'utf8'), ctx);
  }
  return ctx;
}
function canvas(rev = 7, removed = false) {
  return {ok:true, application_root:'application', graph_id:'application', root:'scope', revision:rev,
    scope:{current:'scope'}, authorization:{subject:'owner', session:'browser'},
    nodes:[{id:'group', label:'Group', composition:true, x:0, y:0, ports:[], properties:[],
      member_count:removed ? 1 : 2, members:removed ? [{id:'b'}] : [{id:'a'}, {id:'b'}]},
      ...(removed ? [{id:'a', label:'A', x:100, y:100, ports:[], properties:[], group:''}] : [])],
    wires:[], catalog:[], workshops:[], configuration:{},
    interaction_projection:{revision:rev, bindings:[{
      control:'app:control:canvas:remove-member', interaction:'remove', event:'drop',
      acknowledgement_mode:'receipt-v1', projection_mode:'topology-delta-v1'}]}};
}
function fixture(client, post, get) {
  const ctx = context(), posts = [];
  const api = (client === 'existing' ? ctx.ArchHubExistingWorkshop : ctx.ArchHubStudioAuthority).create({
    uuid:() => 'command-p10', projectCanvas:value => ({nodes:value.nodes, wires:value.wires}),
    get:async () => get(), post:async (url, body) => {posts.push({url, body:plain(body)}); return post(url, body);}});
  return {api, posts};
}
for (const client of ['existing', 'authority']) {
  test(`p10 ${client}: inner member absent from canvas.nodes posts once and projects one remaining member`, async () => {
    let held = canvas();
    const {api, posts} = fixture(client, async () => {
      held = canvas(8, true); return {ok:true, committed_revision:8};
    }, () => held);
    if (client === 'existing') api.setTopologyCanvas(held); else await api.load();
    const result = await api.moveMember('a', 'group', '', {x:100, y:100});
    assert.ok(result);
    assert.equal(posts.length, 1);
    assert.equal(posts[0].url, '/api/universal/interaction');
    assert.equal(posts[0].body.projection_mode, 'receipt-v1');
    assert.equal(posts[0].body.revision, 7);
    assert.deepEqual(posts[0].body.membership,
      {member:'a', from_group:'group', to_group:'', position:{x:100, y:100}});
    const saved = client === 'existing' ? api.getSnapshot().topology.canvas : api.getSnapshot().canvas;
    assert.equal(saved.revision, 8);
    assert.equal(saved.nodes.find(node => node.id === 'group').member_count, 1);
    assert.ok(saved.nodes.some(node => node.id === 'a'));
  });
  test(`p10 ${client}: invalid inner member refuses visibly without posting`, async () => {
    const {api, posts} = fixture(client, async () => assert.fail('refusal must not POST'), () => canvas());
    if (client === 'existing') api.setTopologyCanvas(canvas()); else await api.load();
    await assert.rejects(api.moveMember('missing', 'group', ''), /no longer in the displayed group/);
    assert.equal(posts.length, 0);
    const snapshot = api.getSnapshot();
    assert.match(client === 'existing' ? snapshot.topology.error : snapshot.error, /no longer in the displayed group/);
  });
  test(`p10 ${client}: explicit server refusal remains rejected and visible`, async () => {
    const {api, posts} = fixture(client, async () => ({ok:false, error:'membership denied'}), () => canvas());
    if (client === 'existing') api.setTopologyCanvas(canvas()); else await api.load();
    await assert.rejects(api.moveMember('a', 'group', ''), /membership denied/);
    assert.equal(posts.length, 1);
    const snapshot = api.getSnapshot();
    assert.match(client === 'existing' ? snapshot.topology.error : snapshot.error, /membership denied/);
  });
  test(`p10 ${client}: successful receipt with unchanged membership is a visible refusal`, async () => {
    let held = canvas();
    const {api, posts} = fixture(client, async () => {
      held = canvas(8); return {ok:true, committed_revision:8};
    }, () => held);
    if (client === 'existing') api.setTopologyCanvas(held); else await api.load();
    await assert.rejects(api.moveMember('a', 'group', ''), /removed member is not visible/);
    assert.equal(posts.length, 1);
    const snapshot = api.getSnapshot();
    assert.match(client === 'existing' ? snapshot.topology.error : snapshot.error, /removed member is not visible/);
  });
  test(`p10 ${client}: advanced receipt cannot replace the remaining member with a foreign root`, async () => {
    let held = canvas();
    const {api, posts} = fixture(client, async () => {
      held = canvas(8, true);
      held.nodes[0].members = [{id:'foreign'}];
      return {ok:true, committed_revision:8};
    }, () => held);
    if (client === 'existing') api.setTopologyCanvas(held); else await api.load();
    await assert.rejects(api.moveMember('a', 'group', ''), /removed member is not visible/);
    assert.equal(posts.length, 1, 'refused readback must not retry the accepted removal');
    const snapshot = api.getSnapshot();
    assert.match(client === 'existing' ? snapshot.topology.error : snapshot.error, /removed member is not visible/);
  });
  test(`p10 ${client}: exact empty selection queues after a node selection and survives fresh read`, async () => {
    let held = {...canvas(7, true), selected:'group', selection:['group']};
    let releaseFirst, markFirst;
    const firstStarted = new Promise(resolve => { markFirst = resolve; });
    const firstRelease = new Promise(resolve => { releaseFirst = resolve; });
    const {api, posts} = fixture(client, async (url, body) => {
      const clearing = url === '/api/universal/gesture' && body.focus === null;
      if (clearing) {
        assert.deepEqual(plain(body), {roots:[], focus:null, expected_scope:'scope'});
        held = {...held, revision:9, selection:[], interaction_projection:{...held.interaction_projection, revision:9}};
        return held;
      }
      assert.equal(url, client === 'existing' ? '/api/universal/gesture' : '/api/universal/focus');
      held = {...held, revision:8, selected:'a', selection:['a'], interaction_projection:{...held.interaction_projection, revision:8}};
      markFirst(); await firstRelease; return held;
    }, () => held);
    if (client === 'existing') api.setTopologyCanvas(held); else await api.load();
    const select = (...args) => client === 'existing' ? api.selectTopology(...args) : api.select(...args);
    const first = select('a', ['a']);
    await firstStarted;
    const clearing = select(null, []);
    assert.equal(posts.length, 1, 'clear waits for the prior node selection');
    releaseFirst(); await first; await clearing;
    assert.equal(posts.length, 2);
    if (client === 'existing') await api.refreshTopologyCanvas(); else await api.load();
    const saved = client === 'existing' ? api.getSnapshot().topology.canvas : api.getSnapshot().canvas;
    assert.deepEqual(plain(saved.selection), []);
    assert.equal(saved.selected, 'a', 'raw graph-held primary remains intact after empty selection');
  });
  test(`p10 ${client}: arbitrary missing nonnull selection is refused without posting`, async () => {
    const {api, posts} = fixture(client, async () => assert.fail('invalid selection must not POST'), () => canvas());
    if (client === 'existing') api.setTopologyCanvas(canvas()); else await api.load();
    const operation = client === 'existing' ? api.selectTopology('missing', []) : api.select('missing', []);
    await assert.rejects(operation, /current canvas scope|no longer in the current scope/);
    assert.equal(posts.length, 0);
  });
  test(`p10 ${client}: clear refuses a server readback that retains the selection`, async () => {
    const held = {...canvas(), selected:'group', selection:['group']};
    const {api, posts} = fixture(client, async () => held, () => held);
    if (client === 'existing') api.setTopologyCanvas(held); else await api.load();
    const operation = client === 'existing' ? api.selectTopology(null, []) : api.select(null, []);
    await assert.rejects(operation, /needs reconciliation/);
    assert.equal(posts.length, 1);
    const snapshot = api.getSnapshot();
    assert.match(client === 'existing' ? snapshot.topology.error : snapshot.error, /needs reconciliation/);
  });
}
