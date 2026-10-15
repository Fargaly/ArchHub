const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Execute the actual component's selection block, including functional state updates.
const source = fs.readFileSync(process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
// Work selection and the Work revision editor ship with the Workshop view in studio-workshop.jsx.
const workshopSource = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-workshop.jsx'), 'utf8');
const start = source.indexOf('  const viewScope =', source.indexOf('const StudioLM ='));
const end = source.indexOf('  const selectedWorkshop =', start);
assert.ok(start > 0 && end > start);
// The hooks the block really uses, as React runs them: one state slot per useState call in call
// order, and useEffect run after the render when its dependencies changed (cleanup first). The
// block listens on window for 'archhub:reach-conversation'; the stub window delivers those events.
function harness() {
  const slots = [], effects = [], listeners = new Map(), workshopSelections=[];
  const window = {
    addEventListener:(name, listen) => { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(listen); },
    removeEventListener:(name, listen) => { listeners.get(name)?.delete(listen); },
  };
  const render = (projection, sessionId = 'session-a') => {
    let stateIndex = 0, effectIndex = 0;
    const commit = [];
    const React = {
      useState:initial => {
        const index = stateIndex++;
        if (!(index in slots)) slots[index] = initial;
        return [slots[index], update => { slots[index] = typeof update === 'function' ? update(slots[index]) : update; }];
      },
      useEffect:(effect, deps) => {
        const index = effectIndex++, previous = effects[index];
        if (previous && deps && deps.length === previous.deps.length && deps.every((value, at) => Object.is(value, previous.deps[at]))) return;
        commit.push(() => {
          if (typeof previous?.cleanup === 'function') previous.cleanup();
          effects[index] = {deps:deps || [], cleanup:effect()};
        });
      },
    };
    const context = {session:{id:sessionId}, workshopState:projection, React, window,
      setWorkshopSelection:value=>workshopSelections.push(value)};
    vm.createContext(context);
    vm.runInContext(source.slice(start, end) +
      '\nglobalThis.result = {view:workspaceView, update:updateWorkspaceView};', context);
    commit.forEach(run => run());
    return context.result;
  };
  render.workshopSelections=workshopSelections;
  render.dispatch = (name, detail) => [...(listeners.get(name) || [])].forEach(listen => listen({detail}));
  return render;
}
const projection = (subject = 'owner-a') => ({canvas:{graph_id:'graph-a',root:'scope-a'},
  topology:{canvas:{application_root:'graph-a',scope:{current:'scope-a'},authorization:{subject,session:'view-a'}}},
  workshops:[{root:'general-a',is_general:true},{root:'child-a',is_general:false}]});

function workSelectionHarness() {
  const shared=fs.readFileSync(path.join(__dirname,'../nodelang/studio/shared-data.jsx'),'utf8');
  const context=vm.createContext({window:{}});
  vm.runInContext(shared.slice(0,shared.indexOf('window.ARCHHUB_WORKSHOP_MODEL =')),context);
  return (state,root='general-a',nodes)=>context.window.ARCHHUB_WORKSHOP_TASK_SOURCE.selected(state,root,nodes);
}
const workProjection = () => {
  const state = projection();
  state.topology.graph = {nodes:[{id:'work-a'}, {id:'work-b'}]};
  return {...state,nativeWork:{owner:'owner-a',view:'view-a',
    root:'general-a',scope:'scope-a',state:'idle',available_work:['work-a','work-b']}};
};

test('Work selection restores from fresh admitted graph projection without browser storage', () => {
  const state = workProjection(); state.topology.selected = 'work-b';
  assert.equal(workSelectionHarness()(null), '');
  assert.equal(workSelectionHarness()({...state,nativeWork:null}), '');
  assert.equal(workSelectionHarness()(state), 'work-b');
  state.topology.selected = 'work-a';
  assert.equal(workSelectionHarness()(state), 'work-a');
  state.topology.selected = 'ordinary-node';
  assert.equal(workSelectionHarness()(state), '');
});

test('shared Work selection rejects incoherent scope and foreign owner or view', () => {
  for (const change of [
    row => { row.topology.canvas.authorization.subject = 'other'; },
    row => { row.topology.canvas.authorization.session = 'other'; },
    row => { row.canvas.graph_id = 'other'; },
    row => { row.canvas.root = 'other'; },
    row => { row.nativeWork.root = 'other'; },
    row => { row.nativeWork.scope = 'other'; },
  ]) {
    const state = workProjection(); state.topology.selected = 'work-a'; change(state);
    assert.equal(workSelectionHarness()(state), '');
  }
});

test('new and scope-switched Work selection uses the refreshed graph inventory', () => {
  const select = workSelectionHarness(), state = workProjection();
  state.topology.selected = 'new-work';
  state.nativeWork.available_work = ['new-work'];
  assert.equal(select(state), '');
  state.topology.graph.nodes = [{id:'new-work',title:'Newly exposed Work'}];
  assert.equal(select(state), 'new-work');
  state.canvas.root = state.topology.canvas.scope.current = state.nativeWork.scope = 'next-scope';
  state.topology.selected = 'next-work';state.nativeWork.available_work = ['next-work'];
  state.topology.graph.nodes = [{id:'next-work',title:'Other scope Work'}];
  assert.equal(select(state), 'next-work');
  state.topology.graph.nodes = [];
  assert.equal(select(state), '');
});

test('exact active Work stays visible while idle available choices are empty', () => {
  const state = workProjection(); state.topology.selected = 'work-b';
  Object.assign(state.nativeWork, {state:'local_delivery_abandoned',work:'work-a',available_work:[]});
  assert.equal(workSelectionHarness()(state), 'work-a');
  assert.equal(workSelectionHarness()(state, 'general-a', []), '');
  state.nativeWork.state = 'unavailable';
  assert.equal(workSelectionHarness()(state), '');
});

test('saved local revision reads the exact immutable submission and refuses a foreign decision after editor removal',async()=>{
  const {transport,plain}=require('./workshop72_regression_helpers.cjs');
  const pending={revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),input_digest:'d'.repeat(64),result:'grant:project-result',resolution:'grant:project-local-resolution',
    inputs:{model:'openrouter/free',artifact_name:'pinned.patch',data_class:'public-text',files:[{path:'saved.js',content:'saved immutable text',sha256:'e'.repeat(64)}]},
    requirements:{acceptance_criteria:[{criterion:'Saved criterion',verification:'Saved verification'}]}};
  const status={ok:true,root:'room-a',scope:'scope-a',owner:'owner-a',view:'view-a',work:'work-a',artifacts_work:'work-a',artifacts:[],failures:[],
    state:'local_delivery_abandoned',mode:'project',approved:false,request_id:'attempt-a',available_work:['work-a'],worker:'worker-a',
    local_deliveries:[{work:'work-a',grant:'grant',result:pending.result,input_digest:'d'.repeat(64),worker:'worker-a',provider_outcome:'unknown',output_bytes:0,
      state:'local_delivery_abandoned',resolution:pending.resolution}],
    local_resolution:{decision:'abandon_local_delivery',provider_outcome:'unknown',grant:'grant',result:pending.result,input_digest:'d'.repeat(64),work:'work-a',worker:'worker-a',
      actor:'owner-a',view:'view-a',scope:'scope-a',claim:'claim-a',grant_revision:20,created_at:1,resolution:pending.resolution}};
  for(const foreign of [false,true]){
    const fx=transport({get:()=>status,post:(_url,body)=>({...status,request_id:body.request_id,state:'draft',draft:{title:'Keep title',description:'Keep description',
      revision:10,input_digest:pending.base_digest,inputs:pending.inputs,requirements:pending.requirements,pending_revision:{...pending,...(foreign?{resolution:'other-decision'}:{})}}})});
    await fx.api.refreshNativeWork('room-a','work-a');const operation=fx.api.nativeWorkAction('room-a','read_project','work-a');
    if(foreign)await assert.rejects(operation,/saved revision/);
    else{const draft=(await operation).draft;assert.deepEqual(plain(draft.pending_revision),pending);
      assert.equal(draft.inputs.files[0].content,'saved immutable text');assert.equal(draft.requirements.acceptance_criteria[0].criterion,'Saved criterion');assert.equal(draft.title,'Keep title');}
    assert.equal(fx.posts.length,1);assert.equal(fx.posts[0].body.action,'read_project');assert.equal(fx.posts[0].body.work,'work-a');
    assert.equal(fx.api.getSnapshot().nativeWork.draft,undefined,'source text never persists in the status projection');
  }
});

test('projection hooks subscribe before rereading a publication missed after render', () => {
  for (const hook of ['useStudioProjection','useWorkshopProjection']) {
    let snapshot = {revision:1}, held, effect, listener, unsubscribed = false;
    const transport = {getSnapshot:() => snapshot, subscribe:callback => {
      listener = callback; snapshot = {revision:3};
      return () => { unsubscribed = true; };
    }};
    const context = {window:{ARCHHUB_STUDIO_AUTHORITY:transport}, React:{
      useState:read => { held = read(); return [held, value => { held = value; }]; },
      useEffect:callback => { effect = callback; },
    }};
    vm.createContext(context);
    const from = source.indexOf('const useStudioProjection =');
    const to = source.indexOf('const studioCanvasScope =', from);
    vm.runInContext(source.slice(from, to) + '\n' + hook + '();', context);
    assert.equal(held.revision, 1);
    snapshot = {revision:2};
    const cleanup = effect();
    assert.equal(held.revision, 3);
    snapshot = {revision:4}; listener();
    assert.equal(held.revision, 4);
    cleanup(); assert.equal(unsubscribed, true);
  }
});

test('the Studio opens on Canvas after asynchronous discovery, never inside a Workshop room', () => {
  const render = harness();
  render(null);
  const view = render(projection()).view;
  assert.equal(view.conversationRoot, '');
  assert.equal(view.mode, 'canvas');
});
test('explicit Chat survives later projection refreshes', () => {
  const render = harness();
  render(projection()).update({conversationRoot:'',mode:'chat',target:''});
  assert.equal(render(projection()).view.conversationRoot, '');
});
test('Canvas keeps the selected Workshop and returns to it', () => {
  const render = harness();
  render(projection()).update({conversationRoot:'general-a'});
  render(projection()).update({mode:'canvas'});
  const canvas = render(projection());
  assert.equal(canvas.view.mode, 'canvas');
  assert.equal(canvas.view.conversationRoot, 'general-a');
  canvas.update({mode:'chat'});
  assert.equal(render(projection()).view.conversationRoot, 'general-a');
});
test('new authenticated owner cannot inherit another owners conversation target', () => {
  const render = harness();
  render(projection()).update({conversationRoot:'child-a',target:'agent-a'});
  const changed = render(projection('owner-b')).view;
  assert.equal(changed.conversationRoot, '');
  assert.equal(changed.target, '');
});
test('removed conversation falls back to plain Chat with an explanation', () => {
  const render = harness();
  render(projection()).update({conversationRoot:'child-a',target:'agent-a'});
  const next = projection(); next.workshops.pop();
  const result = render(next).view;
  assert.equal(result.conversationRoot, '');
  assert.equal(result.target, '');
  assert.match(result.notice, /no longer available/i);
});
test('ambiguous or absent general Workshop does not choose an arbitrary room', () => {
  const next = projection(); next.workshops[1].is_general = true;
  assert.equal(harness()(next).view.conversationRoot, '');
  next.workshops = [];
  assert.equal(harness()(next).view.conversationRoot, '');
});
test('temporary projection loss shows loading and preserves explicit Canvas selection', () => {
  const render = harness();
  render(projection()).update({mode:'canvas',conversationRoot:'child-a'});
  const missing = render(null);
  assert.equal(missing.view.pending, true);
  assert.equal(missing.view.mode, 'canvas');
  missing.update({mode:'chat'});
  assert.equal(render(projection()).view.mode, 'canvas');
  assert.equal(render(projection()).view.conversationRoot, 'child-a');
});
test('partial discovery cannot select a room before authenticated identity arrives', () => {
  const render = harness();
  const partial = projection(); delete partial.topology;
  const before = render(partial);
  assert.equal(before.view.pending, true);
  before.update({conversationRoot:'child-a',target:'agent-a'});
  const ready = render(projection()).view;
  assert.equal(ready.pending, false);
  assert.equal(ready.conversationRoot, '');
  assert.equal(ready.target, '');
});
test('direct signed canvas projection uses its authenticated owner and view', () => {
  const render = harness();
  const signed = projection();
  signed.canvas.authorization = signed.topology.canvas.authorization;
  delete signed.topology;
  assert.equal(render(signed).view.pending, false);
  render(signed).update({conversationRoot:'child-a',target:'agent-a'});
  signed.canvas.authorization = {...signed.canvas.authorization,subject:'owner-b'};
  const next = render(signed).view;
  assert.equal(next.conversationRoot, '');
  assert.equal(next.target, '');
});
test('mixed topology and Workshop scope wait for a coherent projection', () => {
  const render = harness();
  const next = projection(); next.canvas.root = 'scope-b';
  assert.equal(render(next).view.pending, true);
  next.topology.canvas.scope.current = 'scope-b';
  assert.equal(render(next).view.pending, false);
  next.canvas.graph_id = 'graph-b';
  assert.equal(render(next).view.pending, true);
});
test('a Conversations row that walked to the Workshop canvas opens its room once the new scope lists it', () => {
  const render = harness();
  render(projection()).update({conversationRoot:'general-a'});      // the room held before the walk
  render.dispatch('archhub:reach-conversation', 'child-b');        // the walk is still landing
  assert.equal(render(projection()).view.conversationRoot, 'general-a');   // nothing is replaced yet
  // The walk lands on the Workshop canvas: a new scope that lists the saved room.
  const landed = projection(); landed.canvas.root = landed.topology.canvas.scope.current = 'scope-b';
  landed.workshops.push({root:'child-b', is_general:false});
  render(landed);                                                    // the render that lists it commits the room
  const opened = render(landed).view;
  assert.equal(opened.conversationRoot, 'child-b');
  assert.equal(render.workshopSelections.length,1);
  assert.equal(render.workshopSelections[0].root,'child-b');
  assert.equal(render.workshopSelections[0].task,null);
  assert.equal(opened.mode, 'chat');
  assert.equal(opened.scope, JSON.stringify(['session-a', 'graph-a', 'scope-b', 'owner-a', 'view-a']));
});
