/* Workshop parity item 4 + C (717 order 2026-10-01): task cards read as the design's T-xx cards whose
   threads are the agents talking about that Work. An agent's relayed reply that names a Work is that
   agent's event on the card (owner, thread sender and text are the agent's, never the relay's header
   or author); thread recipients are named as the rail names them; the task id is derived from the Work
   id (never a counter); no progress bar is drawn because no real progress is projected. C: the agent-
   proposed workflow is approved, revoked and run on its workflow card only, not on a second panel. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

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
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, CustomEvent:win.CustomEvent, URL, Blob, TextEncoder});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('nodelang/studio/shared-data.jsx'), {loader:'jsx'}).code, context);
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


const CONTACT = 'app:wip-cell:ece542c574ae470bbbd962ac8c5ff39a';
const relayed = (root, sequence, reply_to, agentText) => ({root, message_id:root, sequence, sender_root:'owner-a',
  recipient_roots:['owner-a'], reply_to_root:reply_to, category:'tool', state:'recorded', created_at:Date.now() / 1000 - 5,
  body:'Session Link relayed reply from acceptance-claude (claude native session). The application relays that agent\'s own text; it is not Work completion or execution evidence.\n\n' + agentText,
  relayed_from:CONTACT, relayed_label:'acceptance-claude', agent_text:agentText, artifact_digest:'f'.repeat(64)});
const mountView = async (setup = () => {}) => {
  const fx = fixture();
  setup(fx);
  const ui = await mountModule();
  ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
  const props = () => ({state:fx.state, descriptor:fx.state.workshops[0], target:'', setTarget:() => {}, setMode:() => {},
    setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}, externalRail:true});
  return {...fx, ui, render:() => ui.render('WorkshopView', props())};
};

const {mounted,transport,plain}=require('./workshop72_regression_helpers.cjs');

test('task rows preserve exact Work identity and never invent a progress bar',async()=>{
  const view=await mountView();try{await view.render();
    const row=view.ui.doc.querySelector('[data-workshop-task-row="'+view.ids.W1+'"]');assert.ok(row);
    assert.equal(row.getAttribute('data-workshop-task-row'),view.ids.W1);
    assert.equal(row.querySelector('[role="progressbar"]'),null,'a task without projected progress has no fabricated progress; the live run card is independent');assert.equal(view.ui.doc.querySelector('[data-workshop-task]'),null);
    assert.ok(view.ui.doc.querySelector('[data-workshop-approval-card]'));
  }finally{await view.ui.close();}
});
test('an agent reply naming a Work is a plain message by that exact relay name in the selected task thread',async()=>{
  const fx=fixture();const W2=fx.ids.W2;
  fx.state.workshop.messages.push(relayed('reply-w2',71,'ask-w2',`Claimed ${W2}: exterior walls are under way.`));
  const ui=await mounted(fx.state,fx.authority,{sel:{agent:null,task:W2}});
  try{const reply=ui.doc.querySelector('[data-workshop-message="reply-w2"]');assert.ok(reply);
    assert.match(text(reply),/exterior walls are under way/);assert.match(text(reply),/acceptance-claude/);
    assert.doesNotMatch(text(reply),/Session Link relayed reply|app:wip-cell:/);
    assert.equal(ui.doc.querySelector('[data-workshop-head]').textContent,'Wall creation');
  }finally{await ui.close();}
});
test('workflow approval revoke and execution retain their exact existing authority route after rich-card removal',async()=>{
  const fx=transport(),D='d'.repeat(64);await fx.api.refreshWorkshop('room-a');
  await fx.api.workshopWorkflow('room-a','workflow-approve',{workflow:'wf-1',digest:D});
  await fx.api.workshopWorkflow('room-a','workflow-revoke',{workflow:'wf-1'});
  await fx.api.workshopWorkflow('room-a','workflow-execute',{workflow:'wf-1'});
  assert.deepEqual(fx.posts.map(post=>[post.url,post.body.root,post.body.action,post.body.workflow]),[
    ['/api/universal/workshop','room-a','workflow-approve','wf-1'],['/api/universal/workshop','room-a','workflow-revoke','wf-1'],
    ['/api/universal/workshop','room-a','workflow-execute','wf-1']]);
  assert.equal(fx.posts[0].body.digest,D);
});
