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

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const workshop = () => fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-workshop.jsx'), 'utf8');

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
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, CustomEvent:win.CustomEvent, URL, Blob, TextEncoder});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/shared-data.jsx'), {loader:'jsx'}).code, context);
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
  gate_spec:{path:'02.TESTS/tests_replica/test_cell_cde_authority.py'}, tier:'T1'}, description:'proposed by an agent', inputs:{}, priority:100,
  purpose:'general', requirements:{}, title, write_grants:[{operations:['apply_patch'], path:'10.PRODUCT/11.ARCHHUB-APP/nodelang/work_proposals.py', scope:'exact'}]});
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

const {mounted,plain}=require('./workshop72_regression_helpers.cjs');

test('agent tile/footer uses exact participant identities instead of grouping runtime sessions into an address',async()=>{
  const fx=fixture();fx.state.workshop.assignments=[{work:fx.ids.W1,agent_session:fx.ids.codex}];
  const ui=await mounted(fx.state,fx.authority);
  try{const head=ui.doc.querySelector('[data-workshop-head]').parentElement;
    assert.match(text(head),/Layer selection/);assert.match(text(head),/Codex/);
    assert.doesNotMatch(text(head),/app:agent-session|Runtime-/);
    assert.equal(ui.doc.querySelector('[aria-label="Workshop agents"]'),null);
    assert.equal(ui.doc.querySelectorAll('textarea').length,1);
  }finally{await ui.close();}
});
test('header and status use the real assigned agents and connected host projection',async()=>{
  const fx=fixture();fx.state.hosts=[{name:'Revit 2025',state:'connected',file:'Tower.rvt'}];
  fx.state.workshop.assignments=[{work:fx.ids.W1,agent_session:fx.ids.codex},{work:fx.ids.W1,agent_session:fx.ids.claude}];
  const ui=await mounted(fx.state,fx.authority);
  try{const header=text(ui.doc.querySelector('[data-workshop-head]').parentElement);
    assert.match(header,/Layer selection/);assert.match(header,/Codex/);assert.match(header,/Claude/);
    assert.match(text(ui.doc.querySelector('[data-workshop-s1-status]')),/Revit 2025.*Tower.rvt/);
    const waiting=ui.win.ARCHHUB_WORKSHOP_MODEL({state:fx.state,descriptor:fx.state.workshops[0]}).viewSections[0].rows.length;
    assert.match(text(ui.doc.querySelector('[data-workshop-s1-status]')),new RegExp(waiting+' need you'));
  }finally{await ui.close();}
});
test('no retained approval action means no inline card; the real submitted board review still counts',async()=>{
  const fx=fixture();fx.state.nativeWork=null;fx.state.workshop.workflows=[];const ui=await mounted(fx.state,fx.authority);
  try{assert.equal(ui.doc.querySelector('[data-workshop-approval-card]'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-utility="Approvals"]'),null);
    const waiting=ui.win.ARCHHUB_WORKSHOP_MODEL({state:fx.state,descriptor:fx.state.workshops[0]}).viewSections[0].rows.length;
    assert.match(text(ui.doc.querySelector('[data-workshop-s1-status]')),new RegExp(waiting+' need you'));
  }finally{await ui.close();}
});
test('proposal selection exposes its real inline approval only and never an assignment inspector',async()=>{
  const fx=fixture();withProposal(fx);fx.state.nativeWork=null;
  const ui=await mounted(fx.state,fx.authority,{sel:{agent:null,task:'proposal:p1'}});
  try{const card=ui.doc.querySelector('[data-workshop-approval-card]');assert.ok(card);
    assert.match(text(card),/Tighten the CDE check/);assert.deepEqual([...card.querySelectorAll('button')].map(text),['Approve','Decline']);
    assert.equal(ui.doc.querySelector('[aria-label="Workshop context"]'),null);
    assert.doesNotMatch(text(card),/Open as graph|assignment/i);
  }finally{await ui.close();}
});
test('latest workflow approval state is reviewed inline and reapproval binds the current workflow digest',async()=>{
  const D='d'.repeat(64);
  for(const approval of [null,{digest:D,current:false,revoked:true},{digest:'e'.repeat(64),current:false,revoked:false}]){
    const fx=fixture();fx.state.nativeWork=null;fx.state.workshop.workflows=[{root:'wf-1',title:'Release note',proposed_by:fx.ids.codex,digest:D,approval,
      nodes:[{root:'n1',title:'Conversation'},{root:'n2',title:'Build the note'},{root:'n3',title:'Review'}]}];
    fx.authority.workshopWorkflow=async(...args)=>{fx.calls.push(['workshopWorkflow',...args]);return{ok:true};};
    const ui=await mounted(fx.state,fx.authority,{sel:{agent:null,task:'wf-1'}});
    try{assert.equal(ui.doc.querySelectorAll('[data-workshop-plan-step]').length,3);
      await ui.click(ui.button('Approve'));assert.deepEqual(plain(fx.calls.filter(row=>row[0]==='workshopWorkflow')),
        [['workshopWorkflow','room-a','workflow-approve',{workflow:'wf-1',digest:D}]]);
      assert.equal(ui.button('Run'),undefined);assert.equal(ui.doc.querySelector('[data-workshop-workflow="wf-1"]'),null);
    }finally{await ui.close();}
  }
});
test('a selected task header uses its exact assignment ahead of an unrelated last speaker',async()=>{
  const fx=fixture();fx.state.workshop.assignments=[{assignment:'as-1',work:fx.ids.W2,agent_session:fx.ids.codex}];
  const ui=await mounted(fx.state,fx.authority,{sel:{agent:null,task:fx.ids.W2}});
  try{const header=text(ui.doc.querySelector('[data-workshop-head]').parentElement);
    assert.match(header,/Wall creation/);assert.match(header,/Codex/);
    assert.doesNotMatch(header,/Claude/);
    const row=ui.doc.querySelector('[data-workshop-task-row="'+fx.ids.W2+'"]');
    assert.equal(text(row.children[0]),'X','task row uses the exact assigned Codex tile ahead of its unrelated Claude speaker');
    assert.equal(ui.doc.querySelector('[aria-label="Workshop context"]'),null);
  }finally{await ui.close();}
});
test('server: the participant host comes from the runtime catalog; revoke is a workflow action of the one route', () => {
  const conversation = read('01.APP/nodelang/existing_workshop_conversation.py');
  assert.match(conversation, /row\["host"\] = workshop_runtime_host\(row\.get\("runtime"\)\)/);
  assert.match(conversation, /from \.universal_application import _HARNESS_AGENT_RUNTIMES/);
  const flow = read('01.APP/nodelang/workshop_workflow.py');
  assert.match(flow, /ACTIONS = frozenset\(\{[^}]*"workflow-revoke"/);
  assert.match(flow, /"workflow-revoke": revoke_workflow/);
  assert.match(read('01.APP/nodelang/studio/studio-existing-workshop.js'), /\['workflow-draft', 'workflow-approve', 'workflow-revoke', 'workflow-execute', 'artifact-review'\]/);
});
