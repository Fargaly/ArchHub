/* Workshop design audit, batch 1 (board 2026-10-01, ranked by what the founder sees first):
   gap 1  an agent's workflow plan is shown as its steps, never a JSON dump;
   gap 2  a drafted workflow is drawn at the agent reply it came from, not at the top of the thread;
   gap 3  one status per workflow: the panel says REVOKED when the card does (a real bug);
   gap 5  a workflow's agent / reviewer parameter is a name, never an opaque contact root;
   gap 6  "delivery started" does not outlive the delivery;
   gap 7  the board's NEEDS YOU column does not say "nothing to group" beside a NEEDS YOU card. */
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
  vm.runInContext(transformSync(fs.readFileSync(path.join(root, 'nodelang/studio/workshop-board.jsx'), 'utf8'), {loader:'jsx'}).code, context);
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
const PLAN_JSON = JSON.stringify({answer:'Proposed a two-step workflow.', title:'Release note workflow', actions:[
  {op:'node', ref:'room', engine:'workshop.conversation', title:'This Workshop', params:{conversation:'this'}},
  {op:'node', ref:'builder', engine:'agent.session', title:'Claude drafts the release note', params:{agent:'claude', message:'BUILD'}},
  {op:'wire', source:{ref:'room'}, target:{ref:'builder'}}]});
const PLAN_TEXT = 'Here is my proposal.\n```json\n' + PLAN_JSON + '\n```';
const conversation = (fx, delivery = 'replied') => {
  const now = Date.now() / 1000;
  fx.state.workshop.messages.push(
    {root:'ask-1', message_id:'ask-1', sequence:60, sender_root:'owner-a', recipient_roots:['owner-a'], reference_roots:[CONTACT],
     body:'PROPOSE a workflow.', category:'note', state:delivery, created_at:now - 20,
     delivery:[{recipient:CONTACT, state:delivery, via:'session-link', ...(delivery === 'replied' ? {reply_message_id:'reply-1'} : {})}]},
    ...(delivery === 'replied' ? [{root:'reply-1', message_id:'reply-1', sequence:62, sender_root:'owner-a', recipient_roots:['owner-a'],
     reference_roots:[CONTACT], reply_to_root:'ask-1', category:'tool', state:'recorded', created_at:now - 10,
     body:'Session Link relayed reply from acceptance-claude (claude native session). The application relays that agent\'s own text; it is not Work completion or execution evidence.\n\n' + PLAN_TEXT,
     relayed_from:CONTACT, relayed_label:'acceptance-claude', agent_text:PLAN_TEXT, artifact_digest:'f'.repeat(64)}] : []));
  fx.authority.workshopWorkflow = (...args) => { fx.calls.push(['workshopWorkflow', ...args]); return Promise.resolve({ok:true}); };
};
const drafted = approval => fx => {
  conversation(fx);
  fx.state.workshop.workflows = [{root:'wf-1', title:'Release note workflow', proposed_by:CONTACT, source_message:'reply-1',
    digest:'d'.repeat(64), approval,
    nodes:[{root:'n1', title:'This Workshop', engine:'workshop.conversation', params:{}},
      {root:'n2', title:'Claude drafts the release note', engine:'agent.session',
       params:{agent:{relation:'r-agent', value:CONTACT, editable:true}, message:{relation:'r-message', value:'BUILD', editable:true}}}]}];
};
const mountView = async (setup = () => {}, extra = {}) => {
  const fx = fixture();
  setup(fx);
  Object.assign(fx.state, extra);
  const ui = await mountModule();
  ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
  const props = () => ({state:fx.state, descriptor:fx.state.workshops[0], target:'', setTarget:() => {}, setMode:() => {},
    setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}, externalRail:true});
  return {...fx, ui, render:() => ui.render('WorkshopView', props())};
};
const visible = el => {   // text a reader sees: closed <details> bodies are not visible
  const out = [];
  const walk = node => node.childNodes.forEach(child => {
    if (child.nodeType === 3) { if (child.nodeValue.trim()) out.push(child.nodeValue.trim()); return; }
    if (child.tagName === 'DETAILS' && !child.open) { const s = child.querySelector('summary'); if (s) out.push(text(s)); return; }
    walk(child);
  });
  walk(el);
  return out.join(' ').replace(/\s+/g, ' ');
};

test('gap 1: an agent reply carrying a workflow plan shows the plan as steps, its JSON one click away', async () => {
  const view = await mountView(conversation);
  try {
    await view.render();
    const reply = view.ui.doc.querySelector('[data-workshop-message="reply-1"]');
    const seen = visible(reply);
    assert.match(seen, /^A acceptance-claude to Owner Here is my proposal\. This Workshop workshop\.conversation Claude drafts the release note agent\.session PROPOSED WORKFLOW · RELEASE NOTE WORKFLOW · 2 STEPS · NOT A WORKFLOW UNTIL DRAFTED show the plan's JSON/);
    assert.ok(!seen.includes('"actions"') && !seen.includes('```'), 'no JSON dump in what the founder reads');
    assert.ok([...reply.querySelectorAll('button')].some(b => text(b) === 'Draft as workflow'));
  } finally { await view.ui.close(); }
});

test('gap 2: a drafted workflow is drawn at the reply it came from, after the ask, never on top', async () => {
  const view = await mountView(drafted(null));
  try {
    await view.render();
    const stream = view.ui.doc.querySelector('[aria-label="Workshop conversation"]');
    const order = [...stream.querySelectorAll('[data-workshop-message], [data-workshop-workflow]')]
      .map(el => el.getAttribute('data-workshop-workflow') ? 'card' : el.getAttribute('data-workshop-message'));
    const ask = order.indexOf('ask-1'), card = order.indexOf('card');
    assert.ok(ask >= 0 && card > ask, 'the card answers the ask: ' + order.join(','));
    assert.equal(order.filter(x => x === 'card').length, 1, 'one card, in place');
    const reply = stream.querySelector('[data-workshop-message="reply-1"]');
    assert.ok(reply.querySelector('[data-workshop-workflow="wf-1"]'), 'the reply IS the card');
    assert.ok(!visible(reply).includes('"actions"'), 'its JSON is not drawn');
    assert.ok(![...reply.querySelectorAll('button')].some(b => text(b) === 'Draft as workflow'), 'not offered for drafting twice');
  } finally { await view.ui.close(); }
});

test('gap 3: the panel and the card agree when the approval is revoked', async () => {
  const view = await mountView(drafted({digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:false, revoked:true, revoked_by:'owner-a'}));
  try {
    await view.render();
    const doc = view.ui.doc;
    assert.equal(text(doc.querySelector('[data-workshop-workflow="wf-1"] [data-workshop-workflow-chip]')), 'REVOKED · NOTHING FURTHER RUNS');
    const panel = text(doc.querySelector('[aria-label="Agent-proposed workflows and reviews"]'));
    assert.match(panel, /REVOKED · NOTHING FURTHER RUNS/);
    assert.ok(!panel.includes('CHANGED SINCE APPROVAL'), 'never a second, contradicting status');
  } finally { await view.ui.close(); }
});

test('gap 2 regression (Ping): a proposal reply that names its Work keeps exactly one approvable card', async () => {
  const view = await mountView(fx => {
    drafted(null)(fx);
    const reply = fx.state.workshop.messages.find(m => m.root === 'reply-1');
    reply.agent_text += ' Work assembly-instance:3f9a1c7e5b2d4f60.';
    reply.body += ' Work assembly-instance:3f9a1c7e5b2d4f60.';
  });
  try {
    await view.render();
    const cards = [...view.ui.doc.querySelectorAll('[data-workshop-workflow="wf-1"]')];
    assert.equal(cards.length, 1, 'the approval surface is never lost');
    assert.ok([...cards[0].querySelectorAll('button')].some(b => text(b) === 'Approve'));
  } finally { await view.ui.close(); }
});

test('gap 5 (Ping): the agent stays editable as a named contact; changing it saves the root and asks for re-approval', async () => {
  const OTHER = 'app:wip-cell:0000aaaa1111bbbb2222cccc3333dddd';
  const second = fx => {
    fx.state.workshop.messages.push({root:'reply-2', message_id:'reply-2', sequence:64, sender_root:'owner-a', recipient_roots:['owner-a'],
      reference_roots:[OTHER], reply_to_root:'ask-1', category:'tool', state:'recorded', created_at:Date.now() / 1000,
      body:"Session Link relayed reply from codex-helper (codex native session). The application relays that agent's own text; it is not Work completion or execution evidence.\n\nOK.",
      relayed_from:OTHER, relayed_label:'codex-helper', agent_text:'OK.', artifact_digest:'e'.repeat(64)});
    fx.authority.workshopWorkflowParam = (...args) => { fx.calls.push(['workshopWorkflowParam', ...args]); return Promise.resolve({ok:true}); };
  };
  const approved = {digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:true, revoked:false};
  const view = await mountView(fx => { drafted(approved)(fx); second(fx); });
  try {
    await view.render();
    const panel = view.ui.doc.querySelector('[aria-label="Agent-proposed workflows and reviews"]');
    const select = panel.querySelector('select[aria-label="agent"]');
    assert.ok(select, 'an editable named-contact control');
    assert.deepEqual([...select.options].map(o => [o.value, o.textContent]), [[CONTACT, 'acceptance-claude'], [OTHER, 'codex-helper']]);
    assert.ok(![...panel.querySelectorAll('input')].some(input => input.value.startsWith('app:wip-cell:')), 'no opaque root typed in');
    await view.ui.act(() => { select.value = OTHER; select.dispatchEvent(new view.ui.win.Event('change', {bubbles:true})); });
    await view.ui.click([...select.form.querySelectorAll('button')].find(b => text(b) === 'Save'));
    assert.deepEqual(JSON.parse(JSON.stringify(view.calls.filter(c => c[0] === 'workshopWorkflowParam'))),
      [['workshopWorkflowParam', 'room-a', 'r-agent', OTHER]]);
  } finally { await view.ui.close(); }
  // The server re-projects the workflow with the new agent: its approval is no longer current.
  const after = await mountView(fx => { drafted({...approved, current:false})(fx); second(fx); });
  try {
    await after.render();
    const card = after.ui.doc.querySelector('[data-workshop-workflow="wf-1"]');
    assert.equal(text(card.querySelector('[data-workshop-workflow-chip]')), 'CHANGED SINCE APPROVAL · REVIEW AND APPROVE AGAIN');
    assert.ok([...card.querySelectorAll('button')].some(b => text(b) === 'Re-approve'));
  } finally { await after.ui.close(); }
});

test('gap 5: the workflow agent parameter is a name, the contact root only in its title', async () => {
  const view = await mountView(drafted(null));
  try {
    await view.render();
    const panel = view.ui.doc.querySelector('[aria-label="Agent-proposed workflows and reviews"]');
    assert.ok(![...panel.querySelectorAll('input')].some(input => input.value.startsWith('app:wip-cell:')), 'no opaque root in an input');
    assert.match(text(panel), /agent acceptance-claude Save message/);
    assert.ok(panel.querySelector(`[title="${CONTACT}"]`));
  } finally { await view.ui.close(); }
});

test('gap 6: "delivery started" is shown only while a delivery on the page is still started', async () => {
  const notice = 'Message saved and delivery started. The agent reply will appear here.';
  for (const [delivery, shown] of [['started', true], ['replied', false]]) {
    const view = await mountView(fx => conversation(fx, delivery), {workshopNotice:notice});
    try {
      await view.render();
      assert.equal(text(view.ui.doc.body).includes(notice), shown, delivery);
    } finally { await view.ui.close(); }
  }
  const other = 'Message saved. Check its delivery outcome in this conversation.';
  const view = await mountView(fx => conversation(fx, 'replied'), {workshopNotice:other});
  try { await view.render(); assert.ok(text(view.ui.doc.body).includes(other), 'other notices are untouched'); }
  finally { await view.ui.close(); }
});

test('gap 7: the board does not say "nothing to group" beside a NEEDS YOU card', async () => {
  const proposal = 'ArchHub work proposal v1\n' + JSON.stringify({container:{container_id:'GM.nodes.cde-authority'}, description:'d', inputs:{},
    priority:100, purpose:'general', requirements:{}, title:'Tighten the check', write_grants:[{operations:['apply_patch'], path:'x/y.py', scope:'exact'}]});
  const view = await mountView(fx => {
    fx.state.workshop.messages = [{root:'p1', message_id:'p1', sequence:5, sender_root:fx.ids.codex, recipient_roots:[], body:proposal,
      category:'note', state:'recorded'}];
    fx.state.nativeWork = null;
  });
  try {
    await view.render();
    await view.ui.click([...view.ui.doc.querySelectorAll('[role="tab"]')].find(t => t.textContent.trim() === 'Board'));
    const board = view.ui.doc.querySelector('[aria-label="Workshop board"]');
    assert.ok(board.querySelector('[data-workshop-board-card="proposal:p1"]'), 'the proposal is on the board');
    assert.ok(!text(board).includes('nothing to group'), text(board));
  } finally { await view.ui.close(); }
});
