const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const runtime = fs.readFileSync(path.join(__dirname, '../nodelang/ui_runtime.py'), 'utf8');
const start = runtime.indexOf('  let signingIn=null;');
const end = runtime.indexOf('\n  async function performUniversalRequest', start);
assert.ok(start > 0 && end > start, 'performUniversalFetch is a slice of ui_runtime.py');

function contextForFetch(fetch) {
  const storage = {};
  const meta = {content:'old-csrf'};
  const context = vm.createContext({
    fetch,
    sessionStorage:{
      setItem:(key, value) => { storage[key] = value; },
      getItem:key => storage[key] || null,
    },
    document:{querySelector:selector => selector === 'meta[name="archhub-csrf"]' ? meta : null},
    window:{__archhubSession:{token:'old-token', csrf:'old-csrf'}},
  });
  vm.runInContext(runtime.slice(start, end) + '\nglobalThis.performUniversalFetch=performUniversalFetch;', context);
  return {context, storage, meta};
}

test('a refused non-canvas universal POST renews but is not replayed', async () => {
  const calls = [];
  const {context, meta} = contextForFetch(async (url, init = {}) => {
    calls.push({url, method:init.method, body:init.body});
    if (url === '/api/universal/session') return {ok:true, json:async () => ({token:'new-token', csrf:'new-csrf'})};
    if (calls.filter(call => call.url === '/api/universal/interaction').length > 1) {
      return {ok:true, json:async () => ({ok:true, replayed:true})};
    }
    return {ok:false, status:403, json:async () => ({ok:false, error:'browser session expired or not yet valid'})};
  });
  await assert.rejects(
    context.performUniversalFetch('/api/universal/interaction', {kind:'drag'}),
    error => error.status === 403 && /browser session expired/.test(error.message)
  );
  assert.deepEqual(calls.map(call => call.url), ['/api/universal/interaction', '/api/universal/session']);
  assert.equal(meta.content, 'new-csrf');
  assert.equal(context.window.__archhubSession.token, 'new-token');
});

test('a refused universal canvas read renews and retries once', async () => {
  const calls = [];
  const {context} = contextForFetch(async (url, init = {}) => {
    calls.push({url, method:init.method});
    if (url === '/api/universal/session') return {ok:true, json:async () => ({token:'new-token', csrf:'new-csrf'})};
    const readCount = calls.filter(call => call.url === '/api/universal/canvas').length;
    if (readCount === 1) {
      return {ok:false, status:403, json:async () => ({ok:false, error:'browser session expired or not yet valid'})};
    }
    return {ok:true, json:async () => ({ok:true, revision:2})};
  });
  const result = await context.performUniversalFetch('/api/universal/canvas');
  assert.equal(result.revision, 2);
  assert.deepEqual(calls.map(call => [call.url, call.method]), [
    ['/api/universal/canvas', 'GET'],
    ['/api/universal/session', 'POST'],
    ['/api/universal/canvas', 'GET'],
  ]);
});
