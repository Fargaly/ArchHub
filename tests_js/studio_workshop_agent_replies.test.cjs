/* An agent's relayed reply in the Workshop thread (founder-blocking, 2026-10-01): on the default
   messages feed the reply was invisible and the founder's message stayed STARTED. The reply is now
   an agent row named by the relay's own header (never the contact root), its message reads
   REPLIED, "Draft as workflow" is on it, and the workflow card names its proposer the same way. */
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


const PLAN = 'Here is my proposal.\n```json\n' + JSON.stringify({answer:'Proposed a two-step workflow.', actions:[{op:'node', ref:'room', engine:'workshop.conversation', params:{conversation:'this'}}]}) + '\n```';
const withReply = fx => {
  const now = Date.now() / 1000, contact = 'app:wip-cell:ece542c574ae470bbbd962ac8c5ff39a';
  fx.ids.contact = contact;
  fx.state.workshop.messages.push(
    {root:'ask-1', message_id:'ask-1', sequence:60, sender_root:'owner-a', recipient_roots:['owner-a'], reference_roots:[contact],
     body:'PROPOSE a workflow: you draft the release note.', category:'note', state:'replied', created_at:now - 20,
     delivery:[{recipient:contact, state:'replied', via:'session-link', reply_message_id:'reply-1'}]},
    {root:'reply-1', message_id:'reply-1', sequence:62, sender_root:'owner-a', recipient_roots:['owner-a'], reference_roots:[contact],
     reply_to_root:'ask-1', category:'tool', state:'recorded', created_at:now - 10,
     body:'Session Link relayed reply from acceptance-claude (claude native session). The application relays that agent\'s own text; it is not Work completion or execution evidence.\n\n' + PLAN,
     relayed_from:contact, relayed_label:'acceptance-claude', agent_text:PLAN, artifact_digest:'f'.repeat(64)});
  fx.authority.workshopWorkflow = (...args) => { fx.calls.push(['workshopWorkflow', ...args]); return Promise.resolve({ok:true}); };
};
const mountView = async (setup = () => {}) => {
  const fx = fixture();
  setup(fx);
  const ui = await mountModule();
  ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
  const props = () => ({state:fx.state, descriptor:fx.state.workshops[0], target:'', setTarget:() => {}, setMode:() => {},
    setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}, externalRail:true});
  return {...fx, ui, render:() => ui.render('WorkshopView', props())};
};

test('an agent relayed reply is an agent row named by the relay, with its delivery and Draft as workflow', async () => {
  const view = await mountView(withReply);
  try {
    await view.render();
    const stream = view.ui.doc.querySelector('[aria-label="Workshop conversation"]');
    const reply = stream.querySelector('[data-workshop-message="reply-1"]');
    assert.ok(reply, 'the relayed reply is in the thread');
    assert.match(text(reply), /^A acceptance-claude/, 'named by the relay header, not the contact root');
    assert.ok(!text(stream).includes('app:wip-cell:'), 'no contact root is shown anywhere in the thread');
    assert.match(text(stream.querySelector('[data-workshop-message="ask-1"]')), /acceptance-claude · REPLIED/);
    const draft = [...reply.querySelectorAll('button')].find(b => text(b) === 'Draft as workflow');
    assert.ok(draft, 'the founder can draft the proposal from the reply');
    await view.ui.click(draft);
    assert.deepEqual(JSON.parse(JSON.stringify(view.calls.filter(c => c[0] === 'workshopWorkflow').map(c => c.slice(1)))),
      [['room-a', 'workflow-draft', {message:'reply-1'}]]);
    const panel = text(view.ui.doc.querySelector('[aria-label="Workshop context"]'));
    assert.ok(!panel.includes('Session Link relayed reply'), 'an agent reply is not listed as tool activity');
  } finally { await view.ui.close(); }
});

test('the workflow card names its proposer by the relay label', async () => {
  const view = await mountView(fx => {
    withReply(fx);
    fx.state.workshop.workflows = [{root:'wf-1', title:'Release note', proposed_by:fx.ids.contact, digest:'d'.repeat(64), approval:null,
      nodes:[{root:'n1', title:'This Workshop', engine:'workshop.conversation', params:{}}]}];
  });
  try {
    await view.render();
    const card = view.ui.doc.querySelector('[data-workshop-workflow="wf-1"]');
    assert.match(text(card), /^A acceptance-claude proposed Here is the workflow acceptance-claude proposes: Release note\./);
  } finally { await view.ui.close(); }
});
