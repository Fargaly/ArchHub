/* Workshop design parity, items 1/3/5/6 (717 order 2026-10-01): the agents rail names an agent by
   its host and says what is not reported; a proposal waiting on the founder reads NEEDS YOU and
   counts; the header carries the Work title and the probed host; the workflow card is the latest
   agent-proposed workflow with its approval chip, Revoke and Re-approve; the context panel shows a
   proposal's requested permissions and an agent's assigned Work. Real projections only. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const workshop = () => fs.readFileSync(path.join(root, 'nodelang/studio/studio-workshop.jsx'), 'utf8');

// A live-shaped fixture: studio-existing-workshop.js snapshot, projectStudioCanvas nodes and wires.
function fixture() {
  const now = Date.now() / 1000;
  const W1 = 'assembly-instance:3f9a1c7e5b2d4f60', W2 = 'assembly-instance:8b41d0e27c93a5f1', W3 = 'assembly-instance:c5e2a9f4180d7b36';
  const codex = 'app:agent-session:runtime:codex-a1', claude = 'app:agent-session:runtime:claude-b2', gone = 'app:agent-session:runtime:gone-c3';
  const participants = [
    {root:'owner-a', label:'Owner', attached:true, is_agent:false, connection_status:'unknown'},
    {root:gone, label:'Gone agent', attached:true, is_agent:true, connection_status:'disconnected', observed_at:now - 360, runtime:'antigravity-ide'},
    {root:codex, label:'Codex', attached:true, is_agent:true, connection_status:'connected', connection_basis:'authenticated-request',
      observed_at:now - 30, expires_at:now + 3600, runtime:'codex', host:'Codex', session_link:'attached'},
    {root:claude, label:'Claude Code', attached:true, is_agent:true, connection_status:'connected', connection_basis:'authenticated-request',
      observed_at:now - 10, expires_at:now + 3600, runtime:'claude', host:'Claude', session_link:'none'},
  ];
  let n = 0;
  const msg = (sender, body, category = 'note') => ({root:'m' + (++n), sequence:n, sender_root:sender, recipient_roots:[], body, category, state:'recorded', created_at:now - 600 + n * 30});
  const messages = [
    msg('owner-a', 'Turn the wall layer into walls.'),
    msg(codex, `Claimed Work ${W1}.`),
    msg(codex, `Gate failed for Work ${W1}: the layer choice needs you.`),
    msg(claude, `Claimed Work ${W2}. Exterior walls first.`),
    msg(codex, `Submitted Work ${W3}: 29 walls created.`),
  ];
  const nodes = [
    {id:'read-dwg', title:'Read DWG', sub:'cad.read_lines', status:'824 lines', x:40, y:80, params:[]},
    {id:W1, title:'Layer selection', sub:'Graph node', status:'OPEN', x:320, y:220, params:[{k:'description', v:'Pick the source wall layers'}]},
    {id:W2, title:'Wall creation', sub:'Graph node', status:'CLAIMED', x:620, y:120, params:[]},
    {id:W3, title:'Verification', sub:'Graph node', status:'SUBMITTED', x:900, y:320, params:[]},
  ];
  const wires = [{id:'w1', from:['read-dwg', 'a'], to:[W1, 'b']}, {id:'w2', from:[W1, 'c'], to:[W2, 'd']}, {id:'w3', from:[W2, 'e'], to:[W3, 'f']}];
  const auth = {subject:'owner-a', session:'view-a'};
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:9, owner:'owner-a', view:'view-a', self:'owner-a',
    can_send:true, participants, messages, storage:'conversation-content', content_cursor:'c9', page_before:null, next_before:null, total:5,
    has_older:false, feed:'messages', model_agent:{root:'model-a', model:'openrouter/model-a', binding_digest:'b'.repeat(64)}};
  const state = {canvas:{graph_id:'graph-a', root:'scope-a', revision:9, authorization:auth}, workshops:[{root:'room-a', label:'L03 wall take-off', is_general:true}],
    workshop:transcript, workshopPage:{root:'room-a', before:null, feed:'messages', feedInitialized:true}, workshopNotice:'',
    nativeWork:{owner:'owner-a', view:'view-a', root:'room-a', scope:'scope-a', state:'awaiting_approval', mode:'project', work:W1, approved:false,
      review_text:'input', input_digest:'a'.repeat(64), review_expires_at:now + 3600, available_work:[W1, W2, W3], artifacts_work:W1, selected_work_mode:'project'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization:auth, revision:9}, graph:{nodes, wires}, selected:null}};
  const calls = [];
  const spy = (name, value) => (...args) => { calls.push([name, ...args]); return Promise.resolve(typeof value === 'function' ? value(...args) : value); };
  const authority = {getSnapshot:() => state, subscribe:() => () => {},
    refreshWorkshop:spy('refreshWorkshop', transcript), refreshNativeWork:spy('refreshNativeWork', state.nativeWork),
    showWorkshopFeed:spy('showWorkshopFeed', transcript), nativeAgents:spy('nativeAgents', {status:'ok', contacts:[]}),
    sendModelConversation:spy('sendModelConversation', {accepted:true}), approveNativeWork:spy('approveNativeWork', {}),
    disconnectAgent:spy('disconnectAgent', {outcome:'revoked'}), selectTopology:spy('selectTopology', null)};
  return {state, authority, calls, ids:{W1, W2, W3, codex, claude, gone}};
}

async function mountModule() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  // The DOM exists before react-dom loads, so React uses the real input event instead of its legacy polyfill.
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const win = dom.window;
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, URL, Blob, TextEncoder});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(workshop(), {loader:'jsx'}).code, context);
  const container = win.document.getElementById('root');
  const reactRoot = createRoot(container);
  const act = async fn => { await React.act(async () => { await fn(); }); };
  const click = el => act(() => el.dispatchEvent(new win.MouseEvent('click', {bubbles:true})));
  return {React, win, doc:win.document, container, act, click,
    render:(component, props) => act(() => reactRoot.render(React.createElement(win[component], props))),
    close:async () => { await act(() => reactRoot.unmount()); win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}
// Visible text as a reader meets it: every text node, in order, separated by one space.
const text = el => {
  if (!el) return '';
  const out = [];
  const walk = node => node.childNodes.forEach(child => {
    if (child.nodeType === 3) { if (child.nodeValue.trim()) out.push(child.nodeValue.trim()); } else walk(child);
  });
  walk(el);
  return out.join(' ').replace(/\s+/g, ' ');
};


const MARKER = 'ArchHub work proposal v1\n';
const proposalBody = title => MARKER + JSON.stringify({container:{container_id:'GM.nodes.cde-authority', gate_kind:'pytest',
  gate_spec:{path:'tests_replica/test_cell_cde_authority.py'}, tier:'T1'}, description:'proposed by an agent', inputs:{}, priority:100,
  purpose:'general', requirements:{}, title, write_grants:[{operations:['apply_patch'], path:'10.PRODUCT/13.NODE-LANGUAGE/nodelang/work_proposals.py', scope:'exact'}]});
const withProposal = fx => fx.state.workshop.messages.push({root:'p1', message_id:'p1', sequence:50,
  sender_root:fx.ids.codex, recipient_roots:[], body:proposalBody('Tighten the CDE check'), category:'note', state:'recorded'});
const mountView = async (setup = () => {}) => {
  const fx = fixture();
  setup(fx);
  const ui = await mountModule();
  ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
  let sel = {agent:null, task:null};
  const props = () => ({state:fx.state, descriptor:fx.state.workshops[0], target:'', setTarget:() => {}, setMode:() => {},
    setFocusId:() => {}, onLeave:() => {}, sel, setSel:value => { sel = value; }, externalRail:true});
  return {...fx, ui, props, sel:() => sel, render:() => ui.render('WorkshopView', props())};
};

test('rail: an agent is named by its host; two sessions of one host get the session id; the model is not invented', async () => {
  const fx = fixture();
  const second = 'app:agent-session:runtime:codexb7f2e1';
  const now = Date.now() / 1000;
  fx.state.workshop.participants.push({root:second, label:'Runtime-b7f2e1', attached:true, is_agent:true, connection_status:'connected',
    connection_basis:'authenticated-request', observed_at:now - 5, expires_at:now + 3600, runtime:'codex', host:'Codex', session_link:'none'});
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    const context = {descriptor:fx.state.workshops[0], graphId:'graph-a', scopeRoot:'scope-a', transcript:fx.state.workshop, state:fx.state};
    await ui.render('WorkshopAgentsRail', {context, sel:null, onSelect:() => {}});
    const rows = [...ui.doc.querySelectorAll('[data-workshop-agent]')].map(text);
    assert.ok(rows.some(row => /^C Codex · codex- AGENT local · Codex session/.test(row)), rows.join(' | '));
    assert.ok(rows.some(row => /^C Codex · codexb AGENT local · Codex session/.test(row)), rows.join(' | '));
    assert.ok(rows.some(row => /^C Claude AGENT local · Claude session/.test(row)), 'a host shared by no other session is the plain name');
    assert.ok(!rows.some(row => /Runtime-/.test(row)), 'the opaque runtime label is never the name when a host is known');
  } finally { await ui.close(); }
  const view = await mountView();
  try {
    await view.render();
    const panel = view.ui.doc.querySelector('[aria-label="Workshop context"]');
    assert.match(text(panel), /SELECTED · AGENT ⋯ C Codex agent · model not reported/);
  } finally { await view.ui.close(); }
});

test('header: Workshop · Work title · the probed host; counts include a proposal waiting on you', async () => {
  for (const [hosts, expected] of [
    [[{id:'r25', name:'Revit 2025', state:'connected', file:'Tower.rvt · 47 walls'}], 'L03 wall take-off · Layer selection · Revit 2025 · Tower.rvt · 47 walls'],
    [[{id:'a', name:'Revit 2025', state:'connected', file:'x'}, {id:'b', name:'Rhino 8', state:'connected', file:'y'}], 'L03 wall take-off · Layer selection · 2 hosts connected'],
    [[{id:'a', name:'Revit 2025', state:'listening', file:''}], 'L03 wall take-off · Layer selection · no host connected'],
  ]) {
    const view = await mountView(withProposal);
    try {
      view.ui.win.ARCHHUB_LOAD_HOSTS = async () => ({hosts, connectors:[]});
      await view.render();
      await view.ui.act(async () => {});
      assert.equal(text(view.ui.doc.querySelector('[data-workshop-head]')), expected);
      assert.match(text(view.ui.doc.querySelector('main').firstElementChild), /2 needs you · 1 running/);
    } finally { await view.ui.close(); }
  }
});

test('a proposal is a NEEDS YOU card; selecting it shows the permissions it asks for and offers no assignment', async () => {
  const view = await mountView(withProposal);
  try {
    view.authority.assignWork = async () => ({});
    await view.render();
    const card = view.ui.doc.querySelector('[data-workshop-task="proposal:p1"]');
    assert.match(text(card), /^PROPOSAL Tighten the CDE check C NEEDS YOU/);
    assert.equal(card.style.borderStyle, 'solid');
    await view.ui.click(card);
    assert.equal(view.sel().task, 'proposal:p1');
    await view.render();
    const panel = text(view.ui.doc.querySelector('[aria-label="Workshop context"]'));
    assert.match(panel, /^SELECTED · TASK PROPOSAL/);
    assert.match(panel, /intent proposed by an agent criteria pytest · tests_replica\/test_cell_cde_authority\.py blocks — state NEEDS YOU/);
    assert.match(panel, /write 10\.PRODUCT\/13\.NODE-LANGUAGE\/nodelang\/work_proposals\.py \(apply_patch\) gate your approval before any Work exists/);
    assert.ok(!/ASSIGN/.test(panel), 'no Work exists to assign before approval');
  } finally { await view.ui.close(); }
});

test('workflow card: the latest proposed workflow, its steps, its approval chip, Revoke and Re-approve', async () => {
  const workflow = approval => fx => {
    fx.state.workshop.workflows = [{root:'wf-1', title:'Release note', proposed_by:fx.ids.codex, digest:'d'.repeat(64), approval,
      nodes:[{root:'n1', title:'Conversation', engine:'workshop.conversation', params:{}}, {root:'n2', title:'Build the note', engine:'agent.session', params:{}},
        {root:'n3', title:'Review', engine:'workshop.review', params:{}}]}];
    fx.authority.workshopWorkflow = (...args) => { fx.calls.push(['workshopWorkflow', ...args]); return Promise.resolve({ok:true}); };
  };
  const D = 'd'.repeat(64);
  const cases = [
    [{digest:D, approved_by:'owner-a', revision:12, current:true, revoked:false}, 'APPROVED · REV 12 · SCOPE: 3 STEPS ON THIS CANVAS',
      'button[aria-label^="Revoke approval"]', ['room-a', 'workflow-revoke', {workflow:'wf-1'}]],
    [{digest:D, approved_by:'owner-a', revision:13, current:false, revoked:true, revoked_by:'owner-a'}, 'REVOKED · NOTHING FURTHER RUNS',
      'Re-approve', ['room-a', 'workflow-approve', {workflow:'wf-1', digest:D}]],
    [{digest:'e'.repeat(64), approved_by:'owner-a', revision:11, current:false, revoked:false}, 'CHANGED SINCE APPROVAL · REVIEW AND APPROVE AGAIN',
      'Re-approve', ['room-a', 'workflow-approve', {workflow:'wf-1', digest:D}]],
    [null, 'AWAITING YOUR APPROVAL', 'Approve', ['room-a', 'workflow-approve', {workflow:'wf-1', digest:D}]],
  ];
  for (const [approval, chip, control, call] of cases) {
    const view = await mountView(workflow(approval));
    try {
      await view.render();
      const card = view.ui.doc.querySelector('[data-workshop-workflow="wf-1"]');
      assert.ok(card, 'the proposed workflow is the workflow card');
      assert.match(text(card), /^C Codex proposed Here is the workflow Codex proposes: Release note\. 3 steps;/);
      assert.match(text(card), /Conversation workshop\.conversation Build the note agent\.session Review workshop\.review/);
      assert.equal(text(card.querySelector('[data-workshop-workflow-chip]')), chip);
      const button = control.startsWith('button') ? card.querySelector(control) :
        [...card.querySelectorAll('button')].find(b => text(b) === control);
      assert.ok(button, chip + ': ' + control);
      await view.ui.click(button);
      assert.deepEqual(JSON.parse(JSON.stringify(view.calls.filter(c => c[0] === 'workshopWorkflow').map(c => c.slice(1)))), [call]);
      assert.ok(!/Here is the workflow on this canvas/.test(text(view.ui.doc.body)), 'the canvas-chain card gives way to the proposed workflow');
    } finally { await view.ui.close(); }
  }
});

test('an agent current task is the Work it is assigned here, before the last card it spoke on', async () => {
  const view = await mountView(fx => { fx.state.workshop.assignments = [{assignment:'as-1', work:fx.ids.W2, agent_session:fx.ids.codex}]; });
  try {
    await view.render();
    const panel = text(view.ui.doc.querySelector('[aria-label="Workshop context"]'));
    assert.match(panel, /SELECTED · AGENT ⋯ C Codex agent/);
    assert.match(panel, /CURRENT TASK intent Wall creation criteria — blocks Verification state RUNNING/);
  } finally { await view.ui.close(); }
});

test('server: the participant host comes from the runtime catalog; revoke is a workflow action of the one route', () => {
  const conversation = read('nodelang/existing_workshop_conversation.py');
  assert.match(conversation, /row\["host"\] = workshop_runtime_host\(row\.get\("runtime"\)\)/);
  assert.match(conversation, /from \.universal_application import _HARNESS_AGENT_RUNTIMES/);
  const flow = read('nodelang/workshop_workflow.py');
  assert.match(flow, /ACTIONS = frozenset\(\{[^}]*"workflow-revoke"/);
  assert.match(flow, /"workflow-revoke": revoke_workflow/);
  assert.match(read('nodelang/studio/studio-existing-workshop.js'), /\['workflow-draft', 'workflow-approve', 'workflow-revoke', 'workflow-execute', 'artifact-review'\]/);
});
