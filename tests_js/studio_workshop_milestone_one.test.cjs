/* Milestone 1 in the shipped Workshop view: each message shows its delivery state per agent, a relayed
   reply is drawn as that agent's own message with Draft-as-workflow and Review-with actions, and an
   agent-proposed workflow shows its approval state, editable parameters, Approve and Run approved.
   Everything drawn comes from the live-shaped transcript (workshop_workflow.py projections). */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

const OPENCODE = 'app:wip-cell:opencode', CLAUDE = 'app:wip-cell:claude', WF = 'app:wip-cell:workflow';
const DIGEST = 'd'.repeat(64);

function fixture({approval = null} = {}) {
  const now = Date.now() / 1000;
  let n = 0;
  const msg = extra => ({root:'m' + (++n), message_id:'m' + n, sequence:n, sender_root:'owner-a', recipient_roots:['owner-a'],
    category:'note', created_at:now - 600 + n * 30, ...extra});
  const messages = [
    msg({body:'Hello both agents.', state:'replied', delivery:[
      {recipient:OPENCODE, state:'replied', via:'session-link', reply_message_id:'m2'},
      {recipient:CLAUDE, state:'uncertain', via:'session-link', reason:'dispatched without a recorded outcome'}]}),
    msg({category:'tool', state:'recorded', body:'Session Link relayed reply from OpenCode fixture (opencode native session).\n\nProposal {"actions": []}',
      relayed_from:OPENCODE, agent_text:'Proposal {"actions": []}', artifact_digest:'a'.repeat(64)}),
    msg({body:'A note to myself.', state:'stored', delivery:[]}),
  ];
  const workflows = [{root:WF, title:'Release note', conversation:'room-a', members:['n1', 'n2'], wires:1, digest:DIGEST,
    reason:null, approval, proposed_by:OPENCODE, source_message:'m2', nodes:[
      {root:'n1', title:'OpenCode builds', engine:'agent.session', params:{
        agent:{value:OPENCODE, relation:'r-agent', editable:true}, message:{value:'BUILD it', relation:'r-message', editable:true},
        engine:{value:'agent.session', relation:'r-engine', editable:false}}},
      {root:'n2', title:'Claude reviews', engine:'workshop.review', params:{
        reviewer:{value:CLAUDE, relation:'r-reviewer', editable:true}, status:{value:'started · Claude', relation:'r-status', editable:false}}}]}];
  const reviews = [{review:'rv1', artifact_message:'m2', artifact_digest:'a'.repeat(64), claimed_by:OPENCODE, judged_by:CLAUDE,
    request_message:'m9', state:'replied', verdict:'pass', review_message:'m10', workflow:WF}];
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:9, owner:'owner-a', view:'view-a',
    self:'owner-a', can_send:true, participants:[{root:'owner-a', label:'Owner', attached:true, is_agent:false, connection_status:'unknown'}],
    messages, workflows, reviews, storage:'conversation-content', content_cursor:'c9', page_before:null, next_before:null, total:3,
    has_older:false, feed:'all', model_agent:null};
  const auth = {subject:'owner-a', session:'view-a'};
  const state = {canvas:{graph_id:'graph-a', root:'scope-a', revision:9, authorization:auth},
    workshops:[{root:'room-a', label:'Release room', is_general:false}], workshop:transcript,
    workshopPage:{root:'room-a', before:null, feed:'all', feedInitialized:true}, workshopNotice:'',
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:auth, revision:9}, graph:{nodes:[], wires:[]}, selected:null}};
  const calls = [];
  const spy = (name, value) => (...args) => { calls.push([name, ...args]); return Promise.resolve(value); };
  const contacts = [
    {root:OPENCODE, label:'OpenCode fixture', app:'opencode', session_id:'s1', binding_digest:'1'.repeat(64), connected:true},
    {root:CLAUDE, label:'Claude fixture', app:'claude', session_id:'s2', binding_digest:'2'.repeat(64), connected:true}];
  const authority = {getSnapshot:() => state, subscribe:() => () => {},
    refreshWorkshop:spy('refreshWorkshop', transcript), refreshNativeWork:spy('refreshNativeWork', {state:'unavailable'}), showWorkshopFeed:spy('showWorkshopFeed', transcript),
    nativeAgents:spy('nativeAgents', {status:'ok', rows:[], contacts}),
    workshopWorkflow:spy('workshopWorkflow', {ok:true}), workshopWorkflowParam:spy('workshopWorkflowParam', {ok:true}),
    selectTopology:spy('selectTopology', null)};
  return {state, authority, calls};
}

async function mountModule() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const win = dom.window;
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, URL, Blob, TextEncoder});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
  const reactRoot = createRoot(win.document.getElementById('root'));
  const act = async fn => { await React.act(async () => { await fn(); }); };
  return {win, doc:win.document, act,
    click:el => act(() => el.dispatchEvent(new win.MouseEvent('click', {bubbles:true}))),
    render:(component, props) => act(() => reactRoot.render(React.createElement(win[component], props))),
    close:async () => { await act(() => reactRoot.unmount()); win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}
const text = el => {
  const out = [];
  const walk = node => node.childNodes.forEach(child => {
    if (child.nodeType === 3) { if (child.nodeValue.trim()) out.push(child.nodeValue.trim()); } else walk(child);
  });
  if (el) walk(el);
  return out.join(' ').replace(/\s+/g, ' ');
};

async function view(options) {
  const {state, authority, calls} = fixture(options);
  const ui = await mountModule();
  ui.win.ARCHHUB_EXISTING_WORKSHOP = authority;
  let target = '';
  const props = {state, descriptor:state.workshops[0], target, setTarget:value => { target = value; }, setMode:() => {},
    setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}, externalRail:true};
  await ui.render('WorkshopView', props);
  await ui.act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  await ui.render('WorkshopView', props);
  return {ui, calls, stream:ui.doc.querySelector('[aria-label="Workshop conversation"]')};
}

test('each message shows its delivery state per agent; a relayed reply is that agent speaking', async () => {
  const {ui, stream} = await view();
  try {
    const rows = [...stream.querySelectorAll('[data-workshop-message]')];
    assert.match(text(rows[0].querySelector('[aria-label="Delivery state"]')),
      /^OpenCode fixture · REPLIED Claude fixture · UNCERTAIN$/);
    assert.match(text(rows[2].querySelector('[aria-label="Delivery state"]')), /^STORED$/);
    assert.match(text(rows[1]), /^O OpenCode fixture to Owner Proposal \{"actions": \[\]\} sha256 aaaaaaaaaaaa Draft as workflow Review with Claude fixture$/);
    assert.ok(!text(rows[1]).includes('Session Link relayed reply'), 'the relay header is not drawn as the agent text');
  } finally { await ui.close(); }
});

test('a proposal is drafted, reviewed by another agent, and nothing runs until the user approves', async () => {
  const {ui, calls, stream} = await view();
  try {
    const reply = stream.querySelector('[data-workshop-message="m2"]');
    const buttons = [...reply.querySelectorAll('button')];
    await ui.click(buttons.find(b => text(b) === 'Draft as workflow'));
    await ui.click(buttons.find(b => text(b) === 'Review with Claude fixture'));
    const panel = stream.querySelector('[aria-label="Agent-proposed workflows and reviews"]');
    assert.match(text(panel), /^Release note proposed by OpenCode fixture AWAITING YOUR APPROVAL OpenCode builds agent\.session agent Save message Save Claude reviews workshop\.review reviewer Save status started · Claude behavior dddddddddddd Approve Run approved/);
    assert.match(text(panel), /Independent review of aaaaaaaaaaaa judged by Claude fixture produced by OpenCode fixture REPLIED VERDICT PASS$/);
    const run = [...panel.querySelectorAll('button')].find(b => text(b) === 'Run approved');
    assert.equal(run.disabled, true, 'a proposal is not approval');
    await ui.click([...panel.querySelectorAll('button')].find(b => text(b) === 'Approve'));
    const save = [...panel.querySelectorAll('button')].filter(b => text(b) === 'Save')[1];
    await ui.click(save);
    assert.deepEqual(JSON.parse(JSON.stringify(calls.filter(c => c[0].startsWith('workshopWorkflow')))), [
      ['workshopWorkflow', 'room-a', 'workflow-draft', {message:'m2'}],
      ['workshopWorkflow', 'room-a', 'artifact-review', {artifact:'m2', reviewer:CLAUDE}],
      ['workshopWorkflow', 'room-a', 'workflow-approve', {workflow:WF, digest:DIGEST}],
      ['workshopWorkflowParam', 'room-a', 'r-message', 'BUILD it']]);
  } finally { await ui.close(); }
});

test('an approved workflow runs; a changed one says so and cannot run', async () => {
  const approved = await view({approval:{digest:DIGEST, current:true, approved_by:'owner-a', revision:9, relation:'r-approval'}});
  try {
    const panel = approved.stream.querySelector('[aria-label="Agent-proposed workflows and reviews"]');
    assert.match(text(panel), /APPROVED · READY TO RUN/);
    const run = [...panel.querySelectorAll('button')].find(b => text(b) === 'Run approved');
    assert.equal(run.disabled, false);
    await approved.ui.click(run);
    assert.deepEqual(JSON.parse(JSON.stringify(approved.calls.filter(c => c[0] === 'workshopWorkflow'))),
      [['workshopWorkflow', 'room-a', 'workflow-execute', {workflow:WF}]]);
  } finally { await approved.ui.close(); }
  const stale = await view({approval:{digest:'e'.repeat(64), current:false, approved_by:'owner-a', revision:8, relation:'r-approval'}});
  try {
    const panel = stale.stream.querySelector('[aria-label="Agent-proposed workflows and reviews"]');
    assert.match(text(panel), /CHANGED SINCE APPROVAL/);
    assert.equal([...panel.querySelectorAll('button')].find(b => text(b) === 'Run approved').disabled, true);
  } finally { await stale.ui.close(); }
});
