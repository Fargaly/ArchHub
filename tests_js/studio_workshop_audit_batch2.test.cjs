/* Workshop design audit, batch 2 (board 2026-10-01): gap 4 an agent that answered through the relay is
   in CONNECTED AGENTS; gap 8 the live graph draws the proposed workflow's own steps and wiring; gap 9 a
   revoked workflow leaves a truthful line (no stop claimed: none is recorded); gap 11 the summary line closes
   the thread with what on this page needs you, workflow decisions included, and infers no motion or completion. */
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
const PLAN = 'Here is my proposal.\n```json\n' + JSON.stringify({actions:[{op:'node', ref:'r', engine:'workshop.conversation', title:'This Workshop'}]}) + '\n```';
const withReply = fx => fx.state.workshop.messages.push({root:'reply-1', message_id:'reply-1', sequence:62, sender_root:'owner-a',
  recipient_roots:['owner-a'], reference_roots:[CONTACT], category:'tool', state:'recorded', created_at:Date.now() / 1000,
  body:"Session Link relayed reply from acceptance-claude (claude native session). The application relays that agent's own text; it is not Work completion or execution evidence.\n\n" + PLAN,
  relayed_from:CONTACT, relayed_label:'acceptance-claude', agent_text:PLAN, artifact_digest:'f'.repeat(64)});
const withWorkflow = approval => fx => {
  withReply(fx);
  fx.state.workshop.workflows = [{root:'wf-1', title:'Release note workflow', proposed_by:CONTACT, source_message:'reply-1',
    digest:'d'.repeat(64), approval, edges:[['n1', 'n2']],
    nodes:[{root:'n1', title:'This Workshop', engine:'workshop.conversation', params:{}},
      {root:'n2', title:'Claude drafts the release note', engine:'agent.session', params:{}}]}];
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

test('gap 4: an agent that answered through the relay is in CONNECTED AGENTS, by name, unverified', async () => {
  const fx = fixture();
  withReply(fx);
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    const context = {descriptor:fx.state.workshops[0], graphId:'graph-a', scopeRoot:'scope-a', transcript:fx.state.workshop, state:fx.state};
    await ui.render('WorkshopAgentsRail', {context, sel:null, onSelect:() => {}});
    const row = ui.doc.querySelector(`[data-workshop-agent="${CONTACT}"]`);
    assert.ok(row, 'the replying agent has a rail row');
    assert.match(text(row), /^A acceptance-claude AGENT Session Link · claude session CONNECTION UNVERIFIED Proposed a workflow\./);
    assert.ok(!text(ui.doc.querySelector('[aria-label="Workshop agents"]')).includes('app:wip-cell:'));
  } finally { await ui.close(); }
});

test('gap 8: with a proposed workflow the live graph draws its steps and its wire, not the canvas', async () => {
  const view = await mountView(withWorkflow(null));
  try {
    await view.render();
    assert.ok(view.ui.doc.querySelector('[role="tab"][aria-label="Router"]'));
    assert.equal(view.ui.doc.querySelector('[aria-label="Workshop live graph"]'), null);
    assert.match(text(view.ui.doc.querySelector('[data-workshop-workflow]')), /Claude drafts the release note/);
  } finally { await view.ui.close(); }
  const plain = await mountView();
  try {
    await plain.render();
    assert.ok(plain.ui.doc.querySelector('[role="tab"][aria-label="Router"]'));
    assert.equal(plain.ui.doc.querySelector('[aria-label="Workshop live graph"]'), null);
  } finally { await plain.ui.close(); }
});

// No stop is claimed: revoke_workflow writes no stop receipt; started runs are not undone, the next run is refused.
const STOP_CLAIM = /\b(stopp?ed|halted|paused|cancel(?:l)?ed)\b/i;
test('gap 9: a revoked workflow leaves a truthful line in the thread and claims no stop', async () => {
  // Revoked before any run (the approval never ran): still no stop claim.
  const revoked = await mountView(withWorkflow({digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:false, revoked:true}));
  try {
    await revoked.render();
    const line = text(revoked.ui.doc.querySelector('[data-workshop-revoked]'));
    assert.equal(line, 'Approval revoked. Runs already started are not undone; approve again before another run.');
    assert.doesNotMatch(line, STOP_CLAIM);
    assert.doesNotMatch(text(revoked.ui.doc.querySelector('[data-workshop-workflow]')), STOP_CLAIM);
  } finally { await revoked.ui.close(); }
  const approved = await mountView(withWorkflow({digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:true, revoked:false}));
  try { await approved.render(); assert.equal(approved.ui.doc.querySelector('[data-workshop-revoked]'), null); }
  finally { await approved.ui.close(); }
});

// The summary is page-scoped, counts workflow decisions that wait on you, and infers no running/finished state.
const OVERREACH = /moving|everything else|running|done|delivered|last change/i;
const summaryOf = view => text(view.ui.doc.querySelector('[data-workshop-summary]'));
test('gap 11: the summary closes the thread with what on this page needs you', async () => {
  const view = await mountView();
  try {
    await view.render();
    const stream = view.ui.doc.querySelector('[aria-label="Workshop conversation"]');
    const summary = stream.querySelector('[data-workshop-summary]');
    assert.ok(summary && summary === [...stream.querySelectorAll('[data-workshop-message], [data-workshop-task], [data-workshop-summary]')].pop(),
      'the last thing in the thread');
    // Blocked + open (claimed) + review on the page: the blocked one needs you; nothing else is asserted.
    assert.match(summaryOf(view), /summary On this page, one thing needs you: T-3f9a1c Layer selection\.$/);
    assert.doesNotMatch(summaryOf(view), OVERREACH);
  } finally { await view.ui.close(); }
});

test('gap 11 (Ping repro): an awaiting workflow with only the ask and its reply is waiting on you', async () => {
  for (const [approval, reason] of [[null, 'awaiting your approval'],
    [{digest:'e'.repeat(64), approved_by:'owner-a', revision:12, current:false, revoked:false}, 'changed since approval'],
    [{digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:false, revoked:true}, 'approval revoked']]) {
    const view = await mountView(fx => {
      fx.state.workshop.messages = fx.state.workshop.messages.slice(0, 1); fx.state.nativeWork = null;
      withWorkflow(approval)(fx);
    });
    try {
      await view.render();
      const said = summaryOf(view);
      assert.doesNotMatch(said, /nothing is waiting/i, reason);
      assert.ok(said.endsWith(`On this page, one thing needs you: Release note workflow (${reason}).`), said);
    } finally { await view.ui.close(); }
  }
  const approved = await mountView(fx => { fx.state.workshop.messages = fx.state.workshop.messages.slice(0, 1); fx.state.nativeWork = null;
    withWorkflow({digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:true, revoked:false})(fx); });
  try { await approved.render(); assert.match(summaryOf(approved), /On this page, nothing is waiting on you\.$/); }
  finally { await approved.ui.close(); }
});

const APPROVED = {digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:true, revoked:false};
const appendWorkflow = (fx, root, title, approval) => fx.state.workshop.workflows.push(
  {...fx.state.workshop.workflows[0], root, title, approval, source_message:'reply-1'});
const quietPage = approval => fx => { fx.state.workshop.messages = fx.state.workshop.messages.slice(0, 1); fx.state.nativeWork = null;
  withWorkflow(approval)(fx); };

test('gap 11 (Ping repro v2): an older awaiting workflow under a newer approved one is still waiting on you', async () => {
  const view = await mountView(fx => { quietPage(null)(fx); appendWorkflow(fx, 'wf-new', 'New approved workflow', APPROVED); });
  try {
    await view.render();
    const panel = view.ui.doc.querySelector('[aria-label="Agent-proposed workflows and reviews"]');
    assert.ok([...panel.querySelectorAll('button')].some(b => text(b) === 'Approve' && !b.disabled), 'the panel offers Approve');
    const said = summaryOf(view);
    assert.doesNotMatch(said, /nothing is waiting/i);
    assert.ok(said.endsWith('On this page, one thing needs you: Release note workflow (awaiting your approval).'), said);
  } finally { await view.ui.close(); }
});

test('gap 11: every displayed workflow decision counts, read by the panel\'s own rule', async () => {
  const view = await mountView(fx => {
    quietPage(null)(fx);
    appendWorkflow(fx, 'wf-changed', 'Changed workflow', {digest:'e'.repeat(64), approved_by:'owner-a', revision:12, current:false, revoked:false});
    appendWorkflow(fx, 'wf-revoked', 'Revoked workflow', {digest:'d'.repeat(64), approved_by:'owner-a', revision:12, current:false, revoked:true});
    appendWorkflow(fx, 'wf-new', 'New approved workflow', APPROVED);
  });
  try {
    await view.render();
    const chips = text(view.ui.doc.querySelector('[aria-label="Agent-proposed workflows and reviews"]'));
    for (const chip of ['AWAITING YOUR APPROVAL', 'CHANGED SINCE APPROVAL', 'REVOKED · NOTHING FURTHER RUNS', 'APPROVED · READY TO RUN'])
      assert.ok(chips.includes(chip), chip);
    assert.ok(summaryOf(view).endsWith('On this page, 3 things need you: Release note workflow (awaiting your approval); ' +
      'Changed workflow (changed since approval); Revoked workflow (approval revoked).'), summaryOf(view));
  } finally { await view.ui.close(); }
});

// An emoji-led agent name (a real Session Link title, installed 20261001-2310-2d6dc02) gives each avatar a
// whole first character: charAt(0) split it into a lone surrogate, drawn as a broken glyph.
const LONE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
test('avatars: an emoji-led agent name gives a whole first character, never a lone surrogate', async () => {
  const FACE = String.fromCodePoint(0x1f600), NAME = FACE + FACE + ' acceptance-claude';
  const named = fx => { withWorkflow(null)(fx); const reply = fx.state.workshop.messages.find(m => m.root === 'reply-1');
    reply.relayed_label = NAME; reply.body = reply.body.replace('acceptance-claude', NAME); };
  // An avatar's initial is the first non-empty text node it draws.
  const initialOf = el => el ? [...el.querySelectorAll('*')].map(n => [...n.childNodes].filter(c => c.nodeType === 3)
    .map(c => c.nodeValue).join('')).find(t => t.trim()) : undefined;
  const view = await mountView(named);
  try {
    await view.render();
    const doc = view.ui.doc;
    const card = doc.querySelector('[data-workshop-workflow]');
    assert.ok(card, 'the proposal card from the named agent');
    assert.equal(initialOf(card), FACE, 'the proposer avatar is the whole emoji');
    const stream = doc.querySelector('[aria-label="Workshop conversation"]');
    const all = [...stream.querySelectorAll('*')].flatMap(n => [...n.childNodes].filter(c => c.nodeType === 3).map(c => c.nodeValue)).join('|');
    assert.ok(!LONE.test(all), 'no lone surrogate is drawn in the conversation');
  } finally { await view.ui.close(); }
  // The CONNECTED AGENTS rail (its own component, as the Studio mounts it).
  const fx = fixture(); named(fx);
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    const context = {descriptor:fx.state.workshops[0], graphId:'graph-a', scopeRoot:'scope-a', transcript:fx.state.workshop, state:fx.state};
    await ui.render('WorkshopAgentsRail', {context, sel:null, onSelect:() => {}});
    const rail = ui.doc.querySelector('[data-workshop-agent="' + CONTACT + '"]');
    assert.ok(rail, 'the named agent is in the rail');
    assert.equal(initialOf(rail), FACE, 'the rail avatar is the whole emoji');
    const all = [...rail.querySelectorAll('*')].flatMap(n => [...n.childNodes].filter(c => c.nodeType === 3).map(c => c.nodeValue)).join('|');
    assert.ok(!LONE.test(all), 'no lone surrogate is drawn in the rail');
  } finally { await ui.close(); }
});

test('gap 11: review and claimed tasks with nothing blocked claim no motion or completion', async () => {
  const calm = await mountView(fx => { fx.state.workshop.messages = fx.state.workshop.messages.filter(m => !/Gate failed|Claimed Work assembly-instance:3f9a/.test(m.body)); fx.state.nativeWork = null; });
  try {
    await calm.render();
    assert.match(summaryOf(calm), /On this page, nothing is waiting on you\.$/);
    assert.doesNotMatch(summaryOf(calm), OVERREACH);
  } finally { await calm.ui.close(); }
});
