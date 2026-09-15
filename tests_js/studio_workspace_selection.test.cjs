const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Execute the actual component's selection block, including functional state updates.
const source = fs.readFileSync(process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const start = source.indexOf('  const viewScope =', source.indexOf('const StudioLM ='));
const end = source.indexOf('  const selectedWorkshop =', start);
assert.ok(start > 0 && end > start);
function harness() {
  let held = null;
  return (projection, sessionId = 'session-a') => {
    const context = {session:{id:sessionId}, workshopState:projection,
      React:{useState:() => [held, update => { held = update(held); }]}};
    vm.createContext(context);
    vm.runInContext(source.slice(start, end) +
      '\nglobalThis.result = {view:workspaceView, update:updateWorkspaceView};', context);
    return context.result;
  };
}
const projection = (subject = 'owner-a') => ({canvas:{graph_id:'graph-a',root:'scope-a'},
  topology:{canvas:{application_root:'graph-a',scope:{current:'scope-a'},authorization:{subject,session:'view-a'}}},
  workshops:[{root:'general-a',is_general:true},{root:'child-a',is_general:false}]});

function workSelectionHarness() {
  const context = {};
  vm.createContext(context);
  const from = source.indexOf('const workshopSelectionId =');
  const to = source.indexOf('const LM_SESSIONS =', from);
  assert.ok(from > 0 && to > from);
  vm.runInContext(source.slice(from, to) + '\nglobalThis.select = selectedWorkshopWork;', context);
  return (state, root = 'general-a', nodes) =>
    context.select(state, root, nodes);
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

test('cold local revision editor restores exact saved submission and refuses foreign decision', async () => {
  const pending = {revision_id:'c'.repeat(32),base_digest:'a'.repeat(64),input_digest:'d'.repeat(64),
    result:'grant:project-result',resolution:'grant:project-local-resolution',
    inputs:{model:'openrouter/free',artifact_name:'pinned.patch',data_class:'public-text',
      files:[{path:'saved.js',content:'saved immutable text',sha256:'e'.repeat(64)}]},
    requirements:{acceptance_criteria:[{criterion:'Saved criterion',verification:'Saved verification'}]}};
  for (const foreign of [false, true]) {
    let base, repair, file, error;
    const submission = {current:null};
    const context = {TextEncoder,busyRef:{current:false},editorsReady:true,revisionBase:null,
      native:{state:'idle',owner:'owner-a',view:'view-a'},protectedEditors:false,
      state:{canvas:{graph_id:'graph-a',root:'scope-a'}},descriptor:{root:'workshop-a'},
      mounted:{current:true},scopeCurrent:() => true,revisionSubmission:submission,
      setBusy:() => {},setActionError:value => {error=value;},
      setRevisionBase:value => {base=value;},setRepair:value => {repair=value;},setSourceFile:value => {file=value;},
      authority:{nativeWorkAction:async (_root, action, work) => {
        assert.equal(action,'read_project');assert.equal(work,'work-a');
        return {work,owner:'owner-a',view:'view-a',draft:{title:'Keep title',description:'Keep description',
          input_digest:'a'.repeat(64),inputs:{files:[]},requirements:{},pending_revision:pending}};
      }}};
    vm.createContext(context);
    const from = source.indexOf('  const beginWorkRevision =');
    const to = source.indexOf('  React.useEffect(', from);
    assert.ok(from > 0 && to > from);
    vm.runInContext(source.slice(from,to) + '\nglobalThis.openRevision = beginWorkRevision;', context);
    await context.openRevision({work:'work-a',result:pending.result,
      resolution:foreign ? 'other-decision' : pending.resolution});
    if (foreign) {
      assert.match(error,/exact local delivery/);assert.equal(base,undefined);assert.equal(submission.current,null);
    } else {
      assert.equal(base.local_source.result,pending.result);assert.equal(base.request_id,null);
      assert.equal(submission.current.revision_id,pending.revision_id);
      assert.equal(submission.current.base_digest,pending.base_digest);
      assert.equal(submission.current.inputs,pending.inputs);
      assert.equal(submission.current.requirements,pending.requirements);
      assert.equal(file.content,'saved immutable text');assert.equal(repair.criterion,'Saved criterion');
      assert.equal(repair.title,'Keep title');
    }
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

test('initial admitted Workshop opens after asynchronous discovery', () => {
  const render = harness();
  render(null);
  assert.equal(render(projection()).view.conversationRoot, 'general-a');
});
test('explicit Chat survives later projection refreshes', () => {
  const render = harness();
  render(projection()).update({conversationRoot:'',mode:'chat',target:''});
  assert.equal(render(projection()).view.conversationRoot, '');
});
test('Canvas keeps the selected Workshop and returns to it', () => {
  const render = harness();
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
  assert.equal(changed.conversationRoot, 'general-a');
  assert.equal(changed.target, '');
});
test('removed conversation falls back to admitted general with an explanation', () => {
  const render = harness();
  render(projection()).update({conversationRoot:'child-a',target:'agent-a'});
  const next = projection(); next.workshops.pop();
  const result = render(next).view;
  assert.equal(result.conversationRoot, 'general-a');
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
  assert.equal(ready.conversationRoot, 'general-a');
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
  assert.equal(next.conversationRoot, 'general-a');
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
