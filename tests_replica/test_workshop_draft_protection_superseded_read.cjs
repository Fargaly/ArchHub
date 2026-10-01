/* Court: a Workshop read that another refresh superseded is not a draft-protection refusal.
 *
 * Seen on the installed app (real_app_check, fresh graph, first Workshop open): the composer showed
 * "Refresh this conversation before changing draft protection. Retry" until Retry was pressed. The
 * editor's request read the Workshop while the canvas refresh moved the page epoch; readWorkshop then
 * answers null (its isCurrent check) and the request refused on that null. It now reads again while
 * the same conversation is still current, a bounded number of times; a real change still refuses.
 *
 * RED-first: on source that refuses a superseded read, the first case fails with that message.
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'nodelang/studio/studio-existing-workshop.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const ALERT = 'Refresh this conversation before changing draft protection.';

// supersede(n): how the canvas moves while the n-th Workshop read is in flight ('page', 'scope' or null).
function workshopWith(supersede) {
  const sandbox = {TextEncoder, URLSearchParams, crypto:webcrypto};
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  let revision = 1, reads = 0, api = null;
  const posts = [];
  const canvas = scope => ({graph_id:'graph', root:scope, revision, workshops:[{root:'workshop', label:'Workshop', is_general:true}]});
  api = sandbox.ArchHubExistingWorkshop.create({
    pendingStorage:{getItem:() => null},
    get:async url => {
      assert.ok(url.startsWith('/api/universal/workshop?'), url);
      reads += 1;
      if (reads > 20) throw new Error('unbounded re-reads');   // an unbounded loop fails, never hangs
      const move = supersede(reads);
      if (move) { revision += 1; api.setCanvas(canvas(move === 'scope' ? 'other-scope' : 'scope')); }
      return {ok:true, graph_id:'graph', root:'workshop', scope_root:'scope', revision, feed:'all',
        storage:'conversation-content', content_cursor:'cursor-' + revision, page_before:null, next_before:null,
        has_older:false, total:0, participants:[], messages:[], owner:'founder', view:'view'};
    },
    post:async (url, request) => {
      assert.equal(url, '/api/universal/workshop');
      posts.push(plain(request));
      const opened = request.action === 'page-open';
      return {ok:true, graph_id:'graph', root:'workshop', scope_root:'scope', request_revision:request.revision,
        revision:request.revision, owner:'founder', view:'view',
        page:opened ? {page_id:'page-1', page_revision:1, state:'open', draft_state:'unknown', resolution_kind:'none'}
          : {page_id:'page-1', page_revision:request.page_revision + 1, state:'open', draft_state:'clear',
            resolution_kind:request.change}};
    },
  });
  api.setCanvas(canvas('scope'));
  return {api, posts, reads:() => reads};
}

test('a read superseded by the canvas refresh is read again and the editor opens', async () => {
  const {api, posts} = workshopWith(n => n === 1 ? 'page' : null);
  const editor = await api.openConversationEditor('workshop', 'key-1', 'message');
  assert.ok(editor, 'the editor opened');
  assert.deepEqual(posts.map(row => row.action), ['page-open', 'page-change']);
  assert.equal(posts[1].change, 'initial-empty');
});

test('a conversation that really changed scope still refuses, and nothing is posted', async () => {
  const {api, posts} = workshopWith(n => n === 1 ? 'scope' : null);
  await assert.rejects(api.openConversationEditor('workshop', 'key-2', 'message'), error =>
    error.message === ALERT || error.message === 'Return to this conversation to reconcile its draft.');
  assert.deepEqual(posts, []);
});

test('reading again is bounded: a read superseded every time refuses after a few reads', async () => {
  const {api, posts, reads} = workshopWith(() => 'page');
  await assert.rejects(api.openConversationEditor('workshop', 'key-3', 'message'), {message:ALERT});
  assert.ok(reads() <= 4, 'reads: ' + reads());
  assert.deepEqual(posts, []);
});
