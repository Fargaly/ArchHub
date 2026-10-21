/* Court: draft protection reads its conversation without moving the visible Workshop page.
 *
 * Seen on the installed app (real_app_check): the composer showed "Refresh this conversation before
 * changing draft protection. Retry". First on a fresh Workshop open (a canvas refresh superseded the
 * editor's read), then persistently after a reload when a saved room was chosen from its row: the
 * editors of the room just left close while the new room's editors open, and both read through the
 * visible page (refreshWorkshop), so each read moved the shared page target and superseded the other's.
 * Draft protection now reads owner, view and revision on its own, leaving the visible page alone.
 *
 * RED-first: on source that reads through the visible page, the row-choose case fails with that message.
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
const ROOMS = [{root:'workshop', label:'Workshop', is_general:true}, {root:'saved-room', label:'Saved room', is_general:false}];

// move(n): how the canvas moves while the n-th Workshop read is in flight ('page', 'scope' or null).
function workshopWith(move = () => null, answerFor = room => room) {
  const sandbox = {TextEncoder, URLSearchParams, crypto:webcrypto, setTimeout};
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  let revision = 1, reads = 0, api = null, pages = 0;
  const posts = [];
  const canvas = scope => ({graph_id:'graph', root:scope, revision, workshops:ROOMS});
  api = sandbox.ArchHubExistingWorkshop.create({
    pendingStorage:{getItem:() => null},
    get:async url => {
      assert.ok(url.startsWith('/api/universal/workshop?'), url);
      const room = new URLSearchParams(url.slice(url.indexOf('?') + 1)).get('root');
      reads += 1;
      const change = move(reads);
      if (change) { revision += 1; api.setCanvas(canvas(change === 'scope' ? 'other-scope' : 'scope')); }
      await new Promise(resolve => setTimeout(resolve, 0));   // a real request: other reads interleave
      return {ok:true, graph_id:'graph', root:answerFor(room), scope_root:'scope', revision, feed:'all',
        storage:'conversation-content', content_cursor:'cursor-' + revision, page_before:null, next_before:null,
        has_older:false, total:0, participants:[], messages:[], owner:'founder', view:'view'};
    },
    post:async (url, request) => {
      assert.equal(url, '/api/universal/workshop');
      posts.push(plain(request));
      await new Promise(resolve => setTimeout(resolve, 0));
      const base = {ok:true, graph_id:'graph', root:request.root, scope_root:'scope', request_revision:request.revision,
        revision:request.revision, owner:'founder', view:'view'};
      if (request.action === 'page-open') {
        pages += 1;
        return {...base, page:{page_id:'page-' + request.root + '-' + pages, page_revision:1, state:'open',
          draft_state:'unknown', resolution_kind:'none'}};
      }
      return {...base, page:{page_id:request.page_id, page_revision:request.page_revision + 1,
        state:request.change === 'close' ? 'closed' : 'open', draft_state:'clear',
        resolution_kind:request.change === 'close' ? 'none' : request.change}};
    },
  });
  api.setCanvas(canvas('scope'));
  return {api, posts, reads:() => reads};
}

test('after a reload, choosing a saved room: the old room\'s editor closes while the new one opens', async () => {
  const {api, posts} = workshopWith();
  const left = await api.openConversationEditor('workshop', 'key-old', 'message');
  // The row choose: the room just left closes its editor while the chosen room opens its own.
  const [closed, opened] = await Promise.all([left.close(), api.openConversationEditor('saved-room', 'key-new', 'message')]);
  assert.equal(closed.state, 'closed');
  assert.ok(opened, 'the chosen room\'s editor opened');
  assert.deepEqual(posts.filter(row => row.root === 'saved-room').map(row => row.action), ['page-open', 'page-change']);
  assert.equal(api.getSnapshot().workshopPage, null);           // the visible page was never moved
});

test('a canvas refresh during the editor\'s read does not refuse it', async () => {
  const {api, posts} = workshopWith(n => n === 1 ? 'page' : null);
  assert.ok(await api.openConversationEditor('workshop', 'key-1', 'message'));
  assert.deepEqual(posts.map(row => row.action), ['page-open', 'page-change']);
  assert.equal(posts[1].change, 'initial-empty');
});

test('a conversation that really changed scope still refuses, and nothing is posted', async () => {
  const {api, posts} = workshopWith(n => n === 1 ? 'scope' : null);
  await assert.rejects(api.openConversationEditor('workshop', 'key-2', 'message'), error =>
    error.message === ALERT || error.message === 'Return to this conversation to reconcile its draft.');
  assert.deepEqual(posts, []);
});

test('a projection answered for another conversation is refused, and nothing is posted', async () => {
  const {api, posts} = workshopWith(() => null, room => room === 'saved-room' ? 'workshop' : room);
  await assert.rejects(api.openConversationEditor('saved-room', 'key-3', 'message'), {message:ALERT});
  assert.deepEqual(posts, []);
});
