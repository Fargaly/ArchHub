/* Court: the founder binds agent Work proposals from one list, in one action (2026-09-30).
 *
 * Founder decision: an agent proposes Work; only the founder binds it, and "the bind
 * must be a single action that can bind several pending drafts at once. Show each
 * draft's grants plus reviewer in one list; one confirm binds the checked ones."
 * The list reads proposals from the founder's own loaded Workshop messages, asks the
 * application which are already bound, and sends exactly the checked ones as shown.
 *
 * RED-first: on source without readWorkProposals, bindWorkProposals and the
 * WorkProposals list, every case fails.
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash, webcrypto} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

// The message form nodelang/work_proposals.py renders: its marker line, then the
// canonical document (sorted keys, no spaces).
const MARKER = read('nodelang/work_proposals.py').match(/^MARKER = "([^"]+)"$/m)[1];
const sorted = value => Array.isArray(value) ? value.map(sorted) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
const proposal = (title, extra = {}) => ({title, description:'proposed by an agent', priority:100,
  purpose:'general', inputs:{}, requirements:{},
  container:{container_id:'GM.nodes.cde-authority', source_requirement:'court:proposals', domain:'nodes',
    tier:'T1', suitability_status:'S0', revision:'P01', owner:'founder', checker:'court', gate_kind:'pytest',
    gate_spec:{path:'10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py'}},
  write_grants:[{path:'10.PRODUCT/13.NODE-LANGUAGE/nodelang/work_proposals.py', scope:'exact', operations:['apply_patch']},
    {path:'70.HANDOFFS/court-proposals', scope:'descendants', operations:['apply_patch']}], ...extra});
const message = payload => MARKER + '\n' + JSON.stringify(sorted(payload));
const digest = text => createHash('sha256').update(text.slice(MARKER.length + 1)).digest('hex');
const PROPOSER = 'app:agent-session:runtime:proposer', REVIEWER = 'app:agent-session:runtime:reviewer';
const A = message(proposal('Proposal A'));
const B = message(proposal('Proposal B', {purpose:'artifact-publication', requirements:{artifact_reviewers:[REVIEWER]}}));
const MESSAGES = [
  {root:'m-1', message_id:'m-1', sequence:1, sender_root:'founder', body:'An ordinary note', category:'note'},
  {root:'m-2', message_id:'m-2', sequence:2, sender_root:PROPOSER, body:A, category:'note'},
  {root:'m-3', message_id:'m-3', sequence:3, sender_root:PROPOSER, body:B, category:'note'},
  {root:'m-4', message_id:'m-4', sequence:4, sender_root:PROPOSER, body:MARKER + '\n{not json', category:'note'},
];

// The application's answers, as nodelang/work_proposals.py gives them.
function application(request, bound) {
  if (request.action === 'read_work_proposals') {
    return {ok:true, root:request.root, scope:request.scope, request_id:request.request_id, owner:'founder',
      revision:2,
      bound:Object.fromEntries(request.message_ids.map(id => [id, bound[id] || null])),
      declined:Object.fromEntries(request.message_ids.map(id => [id, null]))};
  }
  assert.equal(request.action, 'bind_work_proposals');
  return {ok:true, root:request.root, scope:request.scope, request_id:request.request_id, owner:'founder', revision:3,
    bound:request.proposals.map(item => {
      bound[item.message_id] = 'work-' + item.message_id;
      return {message_id:item.message_id, proposer:PROPOSER, digest:item.digest, work_root:'work-' + item.message_id,
        external_key:'proposal:' + item.message_id, authorization:'record-' + item.message_id + ':authorization'};
    })};
}

async function founder(respond = application) {
  const sandbox = {TextEncoder, URLSearchParams, crypto:webcrypto};
  vm.createContext(sandbox);
  vm.runInContext(read('nodelang/studio/studio-existing-workshop.js'), sandbox);
  const posts = [], bound = {};
  const api = sandbox.ArchHubExistingWorkshop.create({
    pendingStorage:{getItem:() => null},
    get:async url => url.startsWith('/api/universal/workshop-native?') ?
      {ok:true, root:'workshop', scope:'scope', owner:'founder', view:'view', state:'idle'} :
      {ok:true, graph_id:'graph', root:'workshop', scope_root:'scope', revision:1, feed:'all',
        storage:'conversation-content', content_cursor:'cursor', page_before:null, next_before:null,
        has_older:false, total:MESSAGES.length, participants:[], messages:MESSAGES},
    post:async (url, request) => {
      assert.equal(url, '/api/universal/workshop-native');
      posts.push(plain(request));
      return respond(plain(request), bound);
    },
  });
  api.setCanvas({graph_id:'graph', root:'scope', revision:1, workshops:[{root:'workshop', label:'Workshop'}]});
  await api.refreshWorkshop('workshop');
  return {api, posts};
}

test('the founder sees every proposal with its grants per governed root and its reviewers', async () => {
  const {api, posts} = await founder();
  await assert.rejects(api.readWorkProposals('workshop'), /operation status first/);
  assert.equal(posts.length, 0);
  await api.refreshNativeWork('workshop');
  const {rows} = await api.readWorkProposals('workshop');
  assert.deepEqual(plain(rows.map(row => [row.message_id, row.title, row.work_root])),
    [['m-2', 'Proposal A', null], ['m-3', 'Proposal B', null], ['m-4', 'Unreadable proposal', null]]);
  const [a, b, unreadable] = rows;
  assert.equal(a.digest, digest(A), 'the digest is of the exact document the application re-reads');
  assert.equal(a.proposer, PROPOSER);
  assert.deepEqual(plain(a.grants), {
    '10.PRODUCT':[{path:'10.PRODUCT/13.NODE-LANGUAGE/nodelang/work_proposals.py', scope:'exact', operations:['apply_patch']}],
    '70.HANDOFFS':[{path:'70.HANDOFFS/court-proposals', scope:'descendants', operations:['apply_patch']}]});
  assert.deepEqual(plain(a.reviewers), []);
  assert.deepEqual(plain(b.reviewers), [REVIEWER]);
  assert.match(unreadable.problem, /cannot be bound/);
  // Only the bound state is asked; the proposals come from the founder's own page.
  assert.deepEqual(posts.map(request => [request.action, request.message_ids]),
    [['read_work_proposals', ['m-2', 'm-3', 'm-4']]]);
});

test('one action binds exactly the checked proposals; the unchecked stays unbound', async () => {
  const {api, posts} = await founder();
  await api.refreshNativeWork('workshop');
  const [a, b] = (await api.readWorkProposals('workshop')).rows;
  const result = await api.bindWorkProposals('workshop', [a, b]);
  assert.deepEqual(posts.at(-1).proposals, [{message_id:'m-2', sequence:2, digest:digest(A)},
    {message_id:'m-3', sequence:3, digest:digest(B)}]);
  assert.deepEqual(plain(result.bound.map(row => row.work_root)), ['work-m-2', 'work-m-3']);
  const again = await api.readWorkProposals('workshop');
  assert.deepEqual(plain(again.rows.map(row => row.work_root)), ['work-m-2', 'work-m-3', null]);
  // A bound or unreadable proposal is refused before any request.
  const sent = posts.length;
  await assert.rejects(api.bindWorkProposals('workshop', [again.rows[0]]), /unbound proposals/);
  await assert.rejects(api.bindWorkProposals('workshop', [again.rows[2]]), /unbound proposals/);
  await assert.rejects(api.bindWorkProposals('workshop', []), /unbound proposals/);
  assert.equal(posts.length, sent);
});

test('an answer that does not confirm the request is never shown as bound', async () => {
  for (const [name, change, pattern] of [
    ['another owner', (request, answer) => ({...answer, owner:'someone-else'}), /could not be verified|not confirmed/],
    ['another request', (request, answer) => ({...answer, request_id:'other'}), /could not be verified|not confirmed/],
    ['a changed digest', (request, answer) => request.action === 'bind_work_proposals' ?
      {...answer, bound:answer.bound.map(row => ({...row, digest:'0'.repeat(64)}))} : answer, /not confirmed/],
    ['a Work without its proposal key', (request, answer) => request.action === 'bind_work_proposals' ?
      {...answer, bound:answer.bound.map(row => ({...row, external_key:'unset'}))} : answer, /not confirmed/],
    ['a missing proposal', (request, answer) => request.action === 'read_work_proposals' ?
      {...answer, bound:{'m-2':null}} : answer, /could not be verified/],
  ]) {
    const {api} = await founder((request, bound) => change(request, application(request, bound)));
    await api.refreshNativeWork('workshop');
    const attempt = async () => {
      const [a] = (await api.readWorkProposals('workshop')).rows;
      await api.bindWorkProposals('workshop', [a]);
    };
    await assert.rejects(attempt, pattern, name);
  }
});

async function renderList(authority, check) {
  const source = read('nodelang/studio/studio-workshop.jsx');
  const start = source.indexOf('const WorkProposals = (');
  const end = source.indexOf('const ContextPanel = (');
  assert.ok(start >= 0 && end > start, 'studio-workshop.jsx declares WorkProposals before ContextPanel');
  assert.match(source, /\{native && <WorkProposals authority=\{authority\} root=\{descriptor\.root\}/,
    'the Workshop mounts the list in its native review once the operation status is read');
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const W = {inkSoft:'#555', inkMuted:'#777', err:'#c00', line:'#ccc', mono:'monospace'};
  const context = vm.createContext({React, W, Lbl:({children}) => React.createElement('span', null, children)});
  vm.runInContext(transformSync(source.slice(start, end) + '\nglobalThis.Component=WorkProposals;',
    {loader:'jsx', format:'cjs'}).code, context);
  const rootNode = createRoot(dom.window.document.getElementById('root'));
  const refreshed = [];
  try {
    await React.act(async () => rootNode.render(React.createElement(context.Component, {authority, root:'workshop',
      disabled:false, isCurrent:() => true, onBound:async () => { refreshed.push('canvas'); }})));
    await check(dom.window.document, React.act, refreshed);
  } finally {
    await React.act(async () => rootNode.unmount());
    dom.window.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
}

test('rendered list: grants per root and reviewers shown, one confirm binds only the checked', async () => {
  const {api, posts} = await founder();
  await api.refreshNativeWork('workshop');
  await renderList(api, async (document, act, refreshed) => {
    const button = text => [...document.querySelectorAll('button')].find(item => item.textContent.includes(text));
    // The read hashes each document with SubtleCrypto: wait for the rendered answer, not a tick.
    const until = async (done, what) => {
      for (let tries = 0; tries < 100 && !done(); tries++) await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
      assert.ok(done(), what);
    };
    await act(async () => { button('Read proposals').click(); });
    await until(() => document.querySelectorAll('fieldset').length, 'the proposals are listed');
    const sets = [...document.querySelectorAll('fieldset')];
    assert.deepEqual(sets.map(set => set.getAttribute('aria-label')),
      ['Work proposal Proposal A', 'Work proposal Proposal B', 'Work proposal Unreadable proposal']);
    const box = label => document.querySelector(`input[aria-label="Bind ${label}"]`);
    assert.ok(sets[0].querySelector('[aria-label="Grants in 10.PRODUCT"]').textContent.includes('work_proposals.py · exact · apply_patch'));
    assert.ok(sets[0].querySelector('[aria-label="Grants in 70.HANDOFFS"]').textContent.includes('court-proposals · descendants'));
    assert.match(sets[0].textContent, /Reviewers: none/);
    assert.match(sets[1].textContent, new RegExp('Reviewers: ' + REVIEWER));
    assert.equal(box('Unreadable proposal').disabled, true, 'an unreadable proposal cannot be checked');
    const submit = document.querySelector('form[aria-label="Bind agent Work proposals"] button[type="submit"]');
    assert.equal(submit.disabled, true, 'nothing is bound until a proposal is checked');
    await act(async () => { box('Proposal A').click(); });
    assert.equal(submit.textContent, 'Bind 1 checked proposal');
    await act(async () => { submit.click(); });
    await until(() => /Bound 1 Work/.test(document.body.textContent), 'the bind is confirmed');
    const binds = posts.filter(request => request.action === 'bind_work_proposals');
    assert.deepEqual(binds.map(request => request.proposals), [[{message_id:'m-2', sequence:2, digest:digest(A)}]]);
    assert.match(document.body.textContent, /Bound 1 Work: work-m-2\./);
    assert.match(sets[0].textContent, /Bound · work-m-2/);
    assert.equal(box('Proposal A').disabled, true, 'a bound proposal is not offered again');
    assert.equal(box('Proposal B').checked, false);
    assert.match(sets[1].textContent, /Proposed by /, 'the unchecked proposal stays a proposal');
    assert.deepEqual(refreshed, ['canvas']);
  });
});
