/* A collapsed group lists its members' own ports. A wire started or dropped on one joins that member
   (the port's owner) through the ordinary connect route; the group card draws it and keeps its identity. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const adapter = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-existing-workshop.js'), 'utf8');
const page = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio.html'), 'utf8');
const studio = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');

const memberOut = {id:'member-out', name:'out', owner:'member-a', owner_label:'Member', side:'source', mode:'connection',
  connectable:true, connect_control:'control-member', connect_event_fact_input:'fact-index',
  connect_choices:[{id:'outer-in', owner:'outer', label:'Outer / in'}]};
const memberIn = {id:'member-in', name:'in', owner:'member-a', owner_label:'Member', side:'target', mode:'connection', connectable:true};
const canvas = (rev, wires = []) => ({application_root:'application-a', revision:rev,
  authorization:{subject:'owner-a', session:'view-a'}, scope:{current:'scope-a'},
  nodes:[
    {id:'group-a', label:'Ordered List', composition:true, member_count:2, ports:[], member_ports:[memberOut, memberIn]},
    {id:'outer', label:'Outer', ports:[{id:'outer-in', name:'in', side:'target', mode:'connection', connectable:true}]},
  ],
  wires,
  interaction_projection:{revision:rev, bindings:[{control:'control-member', interaction:'interaction-a', event:'event-a',
    acknowledgement_mode:'receipt-v1', projection_mode:'topology-delta-v1',
    event_facts:[{input:'fact-index', value_kind:'number', minimum:0, maximum:0}]}]}});

test('the adapter wires a member port through its owner and confirms the wire the group draws', async () => {
  const ctx = vm.createContext({URLSearchParams, TextEncoder});
  vm.runInContext(adapter, ctx);
  let current = canvas(1);
  const posts = [];
  const api = ctx.ArchHubExistingWorkshop.create({
    uuid:() => 'id', pendingStorage:{getItem:() => null, setItem:() => {}},
    get:async () => current,
    post:async (url, body) => {
      posts.push({url, body:JSON.parse(JSON.stringify(body))});
      // The group draws the new wire on its derived boundary port, not on the member's own interface.
      current = canvas(2, [{id:'wire-new', source:'group-a', source_interface:'group-a:boundary:0', target:'outer', target_interface:'outer-in', nary:false}]);
      return {ok:true, projection_mode:'receipt-v1', base_revision:1, committed_revision:2, created_root:'wire-new'};
    }});
  api.setTopologyCanvas(current);
  const result = await api.connectTopology('member-a', 'member-out', 'outer', 'outer-in');
  assert.equal(result.created_root, 'wire-new');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/api/universal/interaction');
  assert.equal(posts[0].body.control, 'control-member', 'the member port\'s own connect control');
  assert.deepEqual(posts[0].body.event_facts, [{input:'fact-index', value:0}]);
  assert.equal(api.getSnapshot().topology.error || '', '', 'the confirmed wire leaves the canvas editable');
});

test('the Studio projection lists member ports on the group card, labelled by member, owned by the member', () => {
  const start = page.indexOf('function projectStudioCanvas(canvas) {');
  const end = page.indexOf('\n    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);', start);
  assert.ok(start > 0 && end > start, 'projectStudioCanvas is a slice of the shipped studio.html');
  const ctx = vm.createContext({window:{}, PARAM_SPECS:{}});
  vm.runInContext(page.slice(start, end) + '\nglobalThis.project = projectStudioCanvas;', ctx);
  const drawn = canvas(2, [{id:'wire-new', source:'group-a', source_interface:'member-out', target:'outer', target_interface:'outer-in'}]);
  // The wire already added a plain row for the member interface; the member port takes that row.
  drawn.nodes[0].ports = [{id:'member-out', name:'out', side:'source', mode:'relation', connectable:true}];
  const {nodes} = JSON.parse(JSON.stringify(ctx.project(drawn)));
  const group = nodes.find(node => node.id === 'group-a');
  assert.deepEqual(group.outs.map(port => [port.id, port.label, port.owner, port.mode]), [['member-out', 'Member · out', 'member-a', 'connection']]);
  assert.deepEqual(group.ins.map(port => [port.id, port.label, port.owner]), [['member-in', 'Member · in', 'member-a']]);
});

test('the canvas joins a member port\'s owner, in either order, never the group card', () => {
  const start = studio.indexOf('const useSocket = async (root, port, side) => {');
  const end = studio.indexOf('const allNodes = React.useMemo(', start);
  assert.ok(start > 0 && end > start, 'the socket handler is a slice of the shipped studio-lm.jsx');
  const connected = [], errors = [];
  let wireStart = null;
  const ctx = vm.createContext({
    authority:null, authorityState:null, saving:{current:false}, layoutNeedsRefresh:false,
    normal:{connectTopology:async (...args) => { connected.push(args); }},
    setWireError:text => { if (text) errors.push(text); }, setWireStart:value => { wireStart = value; },
  });
  Object.defineProperty(ctx, 'wireStart', {get:() => wireStart});
  vm.runInContext(studio.slice(start, end) + '\nglobalThis.useSocket = useSocket;', ctx);
  const outerOut = {id:'outer-out', label:'out', mode:'connection', connect_control:'control-outer',
    connect_choices:[{id:'member-in', owner:'member-a'}]};
  const outerIn = {id:'outer-in', label:'in', mode:'connection'};
  return (async () => {
    await ctx.useSocket('group-a', memberOut, 'out');
    await ctx.useSocket('outer', outerIn, 'in');
    await ctx.useSocket('group-a', memberIn, 'in');
    await ctx.useSocket('outer', outerOut, 'out');
    assert.deepEqual(errors, []);
    assert.deepEqual(connected, [['member-a', 'member-out', 'outer', 'outer-in'], ['outer', 'outer-out', 'member-a', 'member-in']]);
  })();
});
