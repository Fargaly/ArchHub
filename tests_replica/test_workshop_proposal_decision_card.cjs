/* Court: an agent Work proposal is a task card with an inline decision (2026-10-01).
 *
 * The founder's design (handoff studio-workshop.jsx:221-223, :404-410): a decision sits
 * inline on the task card, first choice primary; Approve leads "Approved: …", Reject
 * leads "Declined: …" with a persisted graph record. The app showed a proposal as
 * raw "ArchHub work proposal v1 {json}" and hid the bind behind an unlabeled toggle; the
 * founder could not find it. Now each proposal message is the design's TaskCard with
 * [Approve, Reject]; Approve binds exactly that proposal through the existing bind.
 *
 * RED-first: on source without PROPOSAL_MARKER/wsProposalTask/approveWorkProposal and the
 * stream wiring, every case fails.
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

const MARKER = read('nodelang/work_proposals.py').match(/^MARKER = "([^"]+)"$/m)[1];
const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
const proposal = (title, extra = {}) => ({title, description:'proposed by an agent', priority:100,
  purpose:'general', inputs:{}, requirements:{},
  container:{container_id:'GM.nodes.cde-authority', source_requirement:'court:proposals', domain:'nodes',
    tier:'T1', suitability_status:'S0', revision:'P01', owner:'founder', checker:'court', gate_kind:'pytest',
    gate_spec:{path:'10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py'}},
  write_grants:[{path:'10.PRODUCT/13.NODE-LANGUAGE/nodelang/work_proposals.py', scope:'exact', operations:['apply_patch']}], ...extra});
const message = payload => MARKER + '\n' + JSON.stringify(sorted(payload));
const PROPOSER = 'app:agent-session:runtime:proposer', REVIEWER = 'app:agent-session:runtime:reviewer';
const A = message(proposal('Proposal A'));
const B = message(proposal('Proposal B', {requirements:{artifact_reviewers:[REVIEWER]}}));
const MESSAGES = [
  {root:'m-1', message_id:'m-1', sequence:1, sender_root:'founder', body:'An ordinary note', category:'note'},
  {root:'m-2', message_id:'m-2', sequence:2, sender_root:PROPOSER, body:A, category:'note'},
  {root:'m-3', message_id:'m-3', sequence:3, sender_root:PROPOSER, body:B, category:'note'},
];

function application(request, bound) {
  if (request.action === 'read_work_proposals') {
    return {ok:true, root:request.root, scope:request.scope, request_id:request.request_id, owner:'founder',
      revision:2,
      bound:Object.fromEntries(request.message_ids.map(id => [id, bound[id] || null])),
      declined:Object.fromEntries(request.message_ids.map(id => [id, null]))};
  }
  if (request.action === 'decline_work_proposals') {
    return {ok:true, root:request.root, scope:request.scope, request_id:request.request_id, owner:'founder', revision:3,
      declined:request.proposals.map(item => ({state:'declined', message_id:item.message_id, sequence:item.sequence,
        digest:item.digest, actor:'founder', proposer:PROPOSER, declined_at:'2026-10-09T00:00:00Z'}))};
  }
  assert.equal(request.action, 'bind_work_proposals');
  return {ok:true, root:request.root, scope:request.scope, request_id:request.request_id, owner:'founder', revision:3,
    bound:request.proposals.map(item => {
      bound[item.message_id] = 'work-' + item.message_id;
      return {message_id:item.message_id, proposer:PROPOSER, digest:item.digest, work_root:'work-' + item.message_id,
        external_key:'proposal:' + item.message_id, authorization:'record-' + item.message_id + ':authorization'};
    })};
}

async function founder(bound = {}, messages = MESSAGES) {
  const sandbox = {TextEncoder, URLSearchParams, crypto:webcrypto};
  vm.createContext(sandbox);
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), sandbox);
  const posts = [];
  const api = sandbox.ArchHubExistingWorkshop.create({
    pendingStorage:{getItem:() => null},
    get:async url => url.startsWith('/api/universal/workshop-native?') ?
      {ok:true, root:'workshop', scope:'scope', owner:'founder', view:'view', state:'idle'} :
      {ok:true, graph_id:'graph', root:'workshop', scope_root:'scope', revision:1, feed:'all',
        storage:'conversation-content', content_cursor:'cursor', page_before:null, next_before:null,
        has_older:false, total:messages.length, participants:[], messages},
    post:async (url, request) => { posts.push(plain(request)); return application(plain(request), bound); },
  });
  api.setCanvas({graph_id:'graph', root:'scope', revision:1, workshops:[{root:'workshop', label:'Workshop'}]});
  await api.refreshWorkshop('workshop');
  return {api, posts};
}

const SOURCE = () => read('nodelang/studio/studio-workshop.jsx');
const slice = (from, to) => {
  const source = SOURCE(), start = source.indexOf(from), end = source.indexOf(to);
  assert.ok(start >= 0 && end > start, 'studio-workshop.jsx has ' + from + ' before ' + to);
  return source.slice(start, end);
};
const helpers = () => {
  const {transformSync} = require('esbuild');
  const context = vm.createContext({});
  vm.runInContext(transformSync(slice('const PROPOSAL_MARKER = ', 'const wsTasks = (') +
    '\nglobalThis.out={isWorkProposal, wsProposalTask, approveWorkProposal, declineWorkProposal};', {loader:'jsx', format:'cjs'}).code, context);
  return context.out;
};

test('a proposal message becomes a queued task card with [Approve, Reject] and the design leads', () => {
  const {isWorkProposal, wsProposalTask} = helpers();
  assert.equal(isWorkProposal(MESSAGES[2]), true);
  assert.equal(isWorkProposal(MESSAGES[0]), false);
  const open = plain(wsProposalTask(MESSAGES[2]));
  assert.equal(open.title, 'Proposal B');
  assert.equal(open.state, 'block', 'a proposal waiting on the founder reads NEEDS YOU (design T-01)');
  assert.equal(open.owner, PROPOSER, 'the proposing agent owns the card');
  assert.deepEqual(open.decision.map(d => [d.label, d.action, d.message]),
    [['Approve', 'approve-proposal', 'm-3'], ['Reject', 'decline-proposal', 'm-3']]);
  assert.match(open.lead, /^Proposes this Work: proposed by an agent\. Reviewers: app:agent-session:runtime:reviewer\. Nothing exists or is granted until you approve\.$/);
  assert.equal(open.tools.list, '10.PRODUCT/13.NODE-LANGUAGE/nodelang/work_proposals.py · exact · apply_patch');
  assert.equal(open.tools.t, 'CDE GM.nodes.cde-authority · T1');

  const approved = plain(wsProposalTask(MESSAGES[2], {work_root:'work-m-3'}));
  assert.equal(approved.decision, null);
  assert.equal(approved.state, 'open');
  assert.equal(approved.lead, 'Approved: Proposal B. Work work-m-3 is created; nothing runs until it is claimed.');

  const declined = plain(wsProposalTask(MESSAGES[2], {declined:{state:'declined', actor:'founder', declined_at:'2026-10-09T00:00:00Z'}}));
  assert.equal(declined.decision, null);
  assert.equal(declined.lead, 'Declined: Proposal B. Nothing exists or is granted.');

  const pending = plain(wsProposalTask(MESSAGES[2], {pending:true}));
  assert.ok(pending.decision.every(d => d.disabled === true), 'no second press while one is in flight');

  const failed = plain(wsProposalTask(MESSAGES[2], {error:'The bind was not confirmed.'}));
  assert.match(failed.lead, /^The bind was not confirmed\. Proposes this Work/);
  assert.equal(failed.decision.length, 2, 'a failed approval can be retried');

  const unreadable = plain(wsProposalTask({root:'m-9', message_id:'m-9', sender_root:PROPOSER, body:MARKER + '\n{not json'}));
  assert.equal(unreadable.decision, null);
  assert.equal(unreadable.lead, 'This proposal cannot be read; it cannot be approved.');
});

// Ping review 2026-10-01: an agent's malformed proposal (operations:'apply_patch' or {}) threw a
// TypeError in the card and the rail BEFORE the bind's own shape check ran. Display now applies the
// bind's exact shape; whatever the bind refuses is an unreadable card with no decision.
const MALFORMED = {
  'operations is a string':(p) => { p.write_grants[0].operations = 'apply_patch'; },
  'operations is an object':(p) => { p.write_grants[0].operations = {}; },
  'operations is empty':(p) => { p.write_grants[0].operations = []; },
  'an operation is not text':(p) => { p.write_grants[0].operations = [1]; },
  'grant scope missing':(p) => { delete p.write_grants[0].scope; },
  'grant is null':(p) => { p.write_grants = [null]; },
  'grants is an object':(p) => { p.write_grants = {}; },
  'no grants':(p) => { p.write_grants = []; },
  'reviewers is a string':(p) => { p.requirements = {artifact_reviewers:'app:agent-session:runtime:reviewer'}; },
  'a reviewer is null':(p) => { p.requirements = {artifact_reviewers:[null]}; },
  'container is null':(p) => { p.container = null; },
  'container is text':(p) => { p.container = 'GM.nodes.cde-authority'; },
  'container id is an object':(p) => { p.container.container_id = {}; },
    'description is null':(p) => { p.description = null; },
  'priority is text':(p) => { p.priority = '100'; },
  'purpose is unknown':(p) => { p.purpose = 'anything'; },
  'title is a number':(p) => { p.title = 7; },
  'document is an array':'array',
};
const malformedMessage = (name, change, index) => {
  const payload = JSON.parse(JSON.stringify(proposal('Malformed ' + name)));
  if (change === 'array') return {root:'bad-' + index, message_id:'bad-' + index, sequence:10 + index, sender_root:PROPOSER, body:MARKER + '\n[1,2]', category:'note'};
  change(payload);
  return {root:'bad-' + index, message_id:'bad-' + index, sequence:10 + index, sender_root:PROPOSER, body:message(payload), category:'note'};
};

test('malformed agent proposals render as unreadable cards with no decision, as the bind refuses them', async () => {
  const {wsProposalTask} = helpers();
  const cases = Object.entries(MALFORMED).filter(([, change]) => change);
  const messages = cases.map(([name, change], index) => malformedMessage(name, change, index));
  for (const [index, [name]] of cases.entries()) {
    let card;
    assert.doesNotThrow(() => { card = plain(wsProposalTask(messages[index])); }, name);
    assert.equal(card.decision, null, name + ': no Approve is offered');
    assert.equal(card.lead, 'This proposal cannot be read; it cannot be approved.', name);
    assert.equal(card.title, 'Unreadable proposal', name);
    assert.equal(card.tools.list, 'no write grants', name);
  }
  // The bind's own validation is unchanged and agrees case for case.
  const {api} = await founder({}, messages);
  await api.refreshNativeWork('workshop', null);
  const rows = (await api.readWorkProposals('workshop')).rows;
  assert.deepEqual(plain(rows.map(row => [row.message_id, !!row.problem])), messages.map(item => [item.message_id, true]));
});

test('a well-formed proposal whose tier is not text still renders, without the tier', () => {
  const {wsProposalTask} = helpers();
  const payload = JSON.parse(JSON.stringify(proposal('Tier as object')));
  payload.container.tier = {};
  const card = plain(wsProposalTask({root:'t-1', message_id:'t-1', sender_root:PROPOSER, body:message(payload)}));
  assert.equal(card.tools.t, 'CDE GM.nodes.cde-authority');
  assert.equal(card.decision.length, 2);
});

test('rendered: a malformed proposal is an unreadable card in the thread, not a crash', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const W = new Proxy({}, {get:(_, key) => key === 'mono' || key === 'sans' || key === 'serif' ? 'monospace' : '#888888'});
  const context = vm.createContext({React, W, window:{}});
  const code = slice('const CHIP = derive(', '// ── agents rail') + '\n' + slice('const PROPOSAL_MARKER = ', 'const wsTasks = (') +
    '\nglobalThis.out={TaskCard, wsProposalTask};';
  vm.runInContext('const derive = build => build(W);\n' + transformSync(code, {loader:'jsx', format:'cjs'}).code, context);
  const rootNode = createRoot(dom.window.document.getElementById('root'));
  try {
    const t = context.out.wsProposalTask(malformedMessage('operations is a string', MALFORMED['operations is a string'], 0));
    await React.act(async () => rootNode.render(React.createElement(context.out.TaskCard, {t, sel:false, onSelect:() => {},
      onDecide:() => { throw new Error('no decision on an unreadable proposal'); }, compact:false, busy:false,
      agent:() => ({name:'Runtime-proposer', ini:'R', col:'#336699'})})));
    const card = dom.window.document.querySelector('[data-workshop-task="proposal:bad-0"]');
    assert.ok(card && card.textContent.includes('Unreadable proposal'));
    assert.ok(card.textContent.includes('This proposal cannot be read; it cannot be approved.'));
    assert.deepEqual([...card.querySelectorAll('button')].map(button => button.textContent).filter(label => ['Approve', 'Reject'].includes(label)), []);
  } finally {
    await React.act(async () => rootNode.unmount());
    dom.window.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});

test('Approve binds exactly that proposal, reading the operation status first when it is not held', async () => {
  const {approveWorkProposal} = helpers();
  const {api, posts} = await founder();
  const done = await approveWorkProposal(api, 'workshop', 'm-3');
  assert.deepEqual(plain(done), {work_root:'work-m-3'});
  assert.deepEqual(posts.map(request => request.action), ['read_work_proposals', 'bind_work_proposals']);
  assert.deepEqual(posts[1].proposals.map(item => item.message_id), ['m-3'], 'only the approved proposal is bound');
});

test('an already bound proposal is reported with its Work and never bound twice', async () => {
  const {approveWorkProposal} = helpers();
  const {api, posts} = await founder({'m-3':'work-earlier'});
  assert.deepEqual(plain(await approveWorkProposal(api, 'workshop', 'm-3')), {work_root:'work-earlier'});
  assert.deepEqual(posts.map(request => request.action), ['read_work_proposals']);
  await assert.rejects(approveWorkProposal(api, 'workshop', 'm-404'), /not in the loaded messages/);
});

test('Reject declines exactly that proposal through the persisted decline route', async () => {
  const {declineWorkProposal} = helpers();
  const {api, posts} = await founder();
  const done = await declineWorkProposal(api, 'workshop', 'm-3');
  assert.equal(done.declined.state, 'declined');
  assert.equal(done.declined.message_id, 'm-3');
  assert.deepEqual(posts.map(request => request.action), ['read_work_proposals', 'decline_work_proposals']);
  assert.deepEqual(posts[1].proposals.map(item => item.message_id), ['m-3'], 'only the rejected proposal is declined');
});

test('a status read racing the proposals read is read again, not shown as a failure (real-app run)', async () => {
  // Installed-app run 2026-10-01: Approve refused "Workshop changed while reading the proposals."
  // because the view's own status read replaced the held status mid-read.
  const {approveWorkProposal} = helpers();
  const calls = [];
  let reads = 0;
  const authority = {
    readWorkProposals:async () => { calls.push('read'); reads += 1;
      if (reads === 1) throw new Error('Read this Workshop operation status first.');
      if (reads === 2) throw new Error('Workshop changed while reading the proposals.');
      return {rows:[{message_id:'m-3', sequence:3, digest:'a'.repeat(64), work_root:null}]}; },
    refreshNativeWork:async () => { calls.push('status'); },
    bindWorkProposals:async (root, rows) => { calls.push('bind:' + rows.map(row => row.message_id).join()); return {bound:[{work_root:'work-m-3'}]}; },
  };
  assert.deepEqual(plain(await approveWorkProposal(authority, 'workshop', 'm-3')), {work_root:'work-m-3'});
  assert.deepEqual(calls, ['read', 'status', 'read', 'read', 'bind:m-3']);
  reads = -100;
  authority.readWorkProposals = async () => { throw new Error('Workshop changed while reading the proposals.'); };
  await assert.rejects(approveWorkProposal(authority, 'workshop', 'm-3'), /changed while reading/, 'retries are bounded');
});

test('the agents rail never shows the raw proposal document as what the agent is doing', () => {
  assert.match(SOURCE(), /latest \? \(isWorkProposal\(latest\) \? wsLine\('Proposed: ' \+ wsProposalTask\(latest\)\.title, 90\) : wsLine\(latest\.body, 90\)\)/);
});

test('rendered: the proposal is the design TaskCard; Approve is primary and decides this proposal', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const W = new Proxy({}, {get:(_, key) => key === 'mono' || key === 'sans' || key === 'serif' ? 'monospace' : '#888888'});
  const context = vm.createContext({React, W, window:{}});
  const code = slice('const CHIP = derive(', '// ── agents rail') + '\n' + slice('const PROPOSAL_MARKER = ', 'const wsTasks = (') +
    '\nglobalThis.out={TaskCard, wsProposalTask};';
  vm.runInContext('const derive = build => build(W);\n' + transformSync(code, {loader:'jsx', format:'cjs'}).code, context);
  const decided = [];
  const rootNode = createRoot(dom.window.document.getElementById('root'));
  try {
    const t = context.out.wsProposalTask(MESSAGES[2]);
    await React.act(async () => rootNode.render(React.createElement(context.out.TaskCard, {t, sel:false, onSelect:() => {},
      onDecide:(work, choice) => decided.push([work, choice.action, choice.message]), compact:false, busy:false,
      agent:() => ({name:'Runtime-proposer', ini:'R', col:'#336699'})})));
    const card = dom.window.document.querySelector('[data-workshop-task="proposal:m-3"]');
    assert.ok(card, 'the proposal renders as a task card');
    assert.ok(card.textContent.includes('Proposal B') && card.textContent.includes('NEEDS YOU'));
    assert.ok(card.textContent.includes('Runtime-proposer · Proposes this Work'));
    assert.ok(!card.textContent.includes('{"container"'), 'the raw proposal document is not shown');
    const buttons = [...card.querySelectorAll('button')].map(button => button.textContent);
    assert.deepEqual(buttons.filter(text => ['Approve', 'Reject'].includes(text)), ['Approve', 'Reject'], 'Approve first, then Reject');
    await React.act(async () => { [...card.querySelectorAll('button')].find(button => button.textContent === 'Approve').click(); });
    assert.deepEqual(decided, [['proposal:m-3', 'approve-proposal', 'm-3']]);
  } finally {
    await React.act(async () => rootNode.unmount());
    dom.window.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});

test('the Workshop stream and decide are wired to the proposal card', () => {
  const source = SOURCE();
  assert.match(source, /if \(!isWorkProposal\(item\.message\)\) return msgRow\(item\.message\);/,
    'a proposal message is not rendered as raw text');
  assert.match(source, /const proposal = wsProposalTask\(item\.message, proposalHeld\[item\.message\.message_id \|\| item\.message\.root\]\);/);
  assert.match(source, /return <TaskCard key=\{proposal\.work\} t=\{proposal\}.*onDecide=\{decide\}/);
  assert.match(source, /if \(choice && \['approve-proposal', 'decline-proposal'\]\.includes\(choice\.action\)\) return decideProposal\(choice\);/);
  assert.match(source, /const done = await approveWorkProposal\(authority, descriptor\.root, id\);/);
  assert.match(source, /const done = await declineWorkProposal\(authority, descriptor\.root, id\);/);
});
