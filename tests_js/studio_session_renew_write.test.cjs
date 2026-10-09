const {test} = require('node:test');
const assert = require('node:assert/strict');

test('a refused write is never replayed; the session is renewed for the next attempt', async () => {
  let token = 'a', signIns = 0, posts = 0;
  const store = {};
  const g = {sessionStorage: {getItem: k => store[k] || null, setItem: (k, v) => { store[k] = v; }, removeItem: k => { delete store[k]; }},
    document: {querySelector: () => null}};
  const json = (status, body) => ({status, ok: status < 400, json: async () => body, clone() { return {text: async () => JSON.stringify(body)}; }});
  g.fetch = async (url, init = {}) => {
    const h = init.headers || {};
    if (url === '/api/universal/session') { signIns += 1; token = 't' + signIns; return json(200, {token, csrf: 'c'}); }
    if ((init.method || 'GET') === 'POST') posts += 1;
    if (h['X-ArchHub-Session'] !== token) return json(403, {ok: false, error: 'browser session expired or not yet valid'});
    if (url === '/api/universal/canvas') return json(200, {ok: true, canvas: {root: 'r', revision: 1, scope: {}}, graph: {nodes: [], wires: []}, library: []});
    return json(200, {ok: true});
  };
  global.window = g;
  delete require.cache[require.resolve('../nodelang/studio/studio-authority.js')];
  require('../nodelang/studio/studio-authority.js');
  try { await g.ArchHubStudioAuthority.boot({canvas_key: 'k'}); } catch (_) {}
  token = 'lapsed'; posts = 0; const before = signIns;
  const r = await g.fetch('/api/universal/run-graph', {method: 'POST', headers: {'X-ArchHub-Session': 'stale'}, body: '{}'});
  assert.equal(r.status, 403, 'the refused write is returned, not replayed');
  assert.equal(posts, 1, 'exactly one POST was sent');
  assert.equal(signIns, before + 1, 'the session was renewed for the next attempt');
});
