'use strict';
// Real Workshop transport, fake HTTP only: confirmed proposal decisions belong to
// the existing admitted snapshot, shared by the canvas node and open window.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/studio-existing-workshop.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
const proposal = {title:'Authority fixture', description:'Bound by the existing proposal path', priority:1,
  purpose:'general', inputs:{}, requirements:{}, container:{container_id:'court-container', tier:'T1'},
  write_grants:[{path:'10.PRODUCT/court.txt', scope:'exact', operations:['apply_patch']}]};
const messages = ['proposal-a','proposal-b'].map((id,index) => ({root:id, message_id:id, sequence:index + 1,
  sender_root:'app:agent-session:runtime:proposer', body:'ArchHub work proposal v1\n' + JSON.stringify(proposal), category:'note'}));

async function harness() {
  const context = vm.createContext({TextEncoder, URLSearchParams, crypto:webcrypto});
  vm.runInContext(source, context);
  let replyHook = null, historyHook = null, refreshFails = false, calls = 0;
  const decisions = {};
  const api = context.ArchHubExistingWorkshop.create({pendingStorage:{getItem:() => null},
    get:async url => {
      if (url.startsWith('/api/universal/workshop-native?')) return {ok:true, root:'room', scope:'scope',
        owner:'founder', view:'view', state:'idle'};
      if (refreshFails) throw new Error('Fixture history unavailable');
      const result = {ok:true, graph_id:'graph', root:'room', scope_root:'scope', revision:1,
        owner:'founder', view:'view', self:'founder', participants:[], messages,
        storage:'conversation-content', content_cursor:'cursor', page_before:null, next_before:null,
        feed:'all', has_older:false, total:messages.length};
      return historyHook ? historyHook(result) : result;
    },
    post:async (_url, body) => {
      calls += 1;
      const common = {ok:true, root:body.root, scope:body.scope, request_id:body.request_id, owner:'founder', revision:2};
      let result;
      if (body.action === 'read_work_proposals') result = {...common,
        bound:Object.fromEntries(body.message_ids.map(id => [id, decisions[id]?.work_root || null])),
        declined:Object.fromEntries(body.message_ids.map(id => [id, decisions[id]?.declined || null]))};
      else if (body.action === 'bind_work_proposals') result = {...common, bound:body.proposals.map(row => ({
        ...row, proposer:'app:agent-session:runtime:proposer', work_root:'work:' + row.message_id,
        external_key:'proposal:' + row.message_id, authorization:'authorization:' + row.message_id}))};
      else if (body.action === 'decline_work_proposals') result = {...common, declined:body.proposals.map(row => ({
        ...row, state:'declined', actor:'founder', declined_at:'2026-10-14T00:00:00Z'}))};
      else throw new Error('Unexpected fixture action ' + body.action);
      return replyHook ? replyHook(result, body) : result;
    }});
  const setScope = (scope = 'scope', authorization = {subject:'founder', session:'view'}) => api.setCanvas({
    graph_id:'graph', root:scope, revision:1, authorization, workshops:[{root:'room',label:'Workshop'}]});
  setScope();
  await api.refreshWorkshop('room');
  await api.refreshNativeWork('room');
  return {api, setScope, decisions, setReply:fn => { replyHook = fn; }, failRefresh:() => { refreshFails = true; },
    setHistory:fn => { historyHook = fn; },
    get calls() { return calls; }};
}

test('read reconciles persisted bind and decline into the admitted Workshop snapshot', async () => {
  const h = await harness();
  const first = await h.api.readWorkProposals('room');
  h.decisions['proposal-a'] = {work_root:'work:existing'};
  h.decisions['proposal-b'] = {declined:{message_id:'proposal-b', state:'declined', digest:first.rows[1].digest,
    actor:'founder', declined_at:'2026-10-14T00:00:00Z'}};
  const seen = [];
  h.api.subscribe(() => seen.push(plain(h.api.getSnapshot().workshop.proposal_decisions)));
  const result = await h.api.readWorkProposals('room');
  const projected = h.api.getSnapshot().workshop.proposal_decisions;
  assert.equal(projected['proposal-a'].work_root, result.rows[0].work_root);
  assert.deepEqual(plain(projected['proposal-b'].declined), plain(result.rows[1].declined));
  assert.equal(seen.length, 1);
  assert.equal(h.api.getSnapshot().workshop.root, 'room');
  assert.equal(h.api.getSnapshot().workshop.graph_id, 'graph');
  assert.equal(h.api.getSnapshot().workshop.scope_root, 'scope');
});

for (const action of ['bind', 'decline']) test(`${action} publishes one confirmed receipt despite a failed history refresh`, async () => {
  const h = await harness();
  const {rows} = await h.api.readWorkProposals('room');
  const before = h.api.getSnapshot().workshop;
  let publishes = 0;
  h.api.subscribe(() => { publishes += 1; });
  const result = await h.api[action === 'bind' ? 'bindWorkProposals' : 'declineWorkProposals']('room', [rows[0]]);
  const page = h.api.getSnapshot().workshop;
  assert.notEqual(page, before);
  assert.equal(publishes, 1);
  const receipt = page.proposal_decisions['proposal-a'];
  assert.equal(receipt.digest, rows[0].digest);
  if (action === 'bind') assert.equal(receipt.work_root, result.bound[0].work_root);
  else assert.deepEqual(plain(receipt.declined), plain(result.declined[0]));
  h.failRefresh();
  await assert.rejects(h.api.refreshWorkshop('room'), /Fixture history unavailable/);
  assert.deepEqual(plain(h.api.getSnapshot().workshop.proposal_decisions['proposal-a']), plain(receipt));
});

test('same-scope history refresh preserves confirmed proposal decisions', async () => {
  const h = await harness(), {rows} = await h.api.readWorkProposals('room');
  await h.api.bindWorkProposals('room', [rows[0]]);
  const receipt = plain(h.api.getSnapshot().workshop.proposal_decisions['proposal-a']);
  await h.api.refreshWorkshop('room');
  assert.deepEqual(plain(h.api.getSnapshot().workshop.proposal_decisions['proposal-a']), receipt);
});

test('an unchanged history read started before approval preserves the newer confirmed receipt', async () => {
  const h = await harness(), {rows} = await h.api.readWorkProposals('room');
  const wait = deferred(), started = deferred();
  h.setHistory(async result => { started.resolve(); await wait.promise;
    return {...result, unchanged:true, revision:2}; });
  const history = h.api.refreshWorkshop('room');
  await started.promise;
  await h.api.bindWorkProposals('room', [rows[0]]);
  const receipt = plain(h.api.getSnapshot().workshop.proposal_decisions['proposal-a']);
  wait.resolve(); await history;
  assert.deepEqual(plain(h.api.getSnapshot().workshop.proposal_decisions['proposal-a']), receipt);
});

for (const action of ['read', 'bind', 'decline']) test(`${action} late response cannot publish into another scope`, async () => {
  const h = await harness(), {rows} = await h.api.readWorkProposals('room');
  const wait = deferred(), started = deferred();
  h.setReply(async result => { started.resolve(); await wait.promise; return result; });
  const call = action === 'read' ? h.api.readWorkProposals('room') :
    h.api[action === 'bind' ? 'bindWorkProposals' : 'declineWorkProposals']('room', [rows[0]]);
  await started.promise;
  h.setScope('another-scope');
  let publishes = 0; h.api.subscribe(() => { publishes += 1; });
  wait.resolve();
  if (action === 'read') await assert.rejects(call, /Workshop changed while reading/);
  else await call; // A confirmed write stays confirmed, but cannot contaminate the new projection.
  assert.equal(h.api.getSnapshot().workshop, null);
  assert.equal(publishes, 0);
});

test('away-and-back authentication change cannot publish a confirmed receipt under a replacement view', async () => {
  const h = await harness(), {rows} = await h.api.readWorkProposals('room');
  const wait = deferred(), started = deferred();
  h.setReply(async result => { started.resolve(); await wait.promise; return result; });
  const call = h.api.bindWorkProposals('room', [rows[0]]);
  await started.promise;
  h.setScope('scope', {subject:'another-owner', session:'another-view'});
  h.setScope();
  wait.resolve(); await call;
  assert.equal(h.api.getSnapshot().workshop, null);
});

test('wrong-root receipt is rejected without changing shared decisions', async () => {
  const h = await harness(), {rows} = await h.api.readWorkProposals('room');
  const before = plain(h.api.getSnapshot().workshop.proposal_decisions);
  h.setReply(result => ({...result, root:'different-room'}));
  await assert.rejects(h.api.bindWorkProposals('room', [rows[0]]), /bind was not confirmed/);
  assert.deepEqual(plain(h.api.getSnapshot().workshop.proposal_decisions), before);
});
