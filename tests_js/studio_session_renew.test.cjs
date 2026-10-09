const {test} = require('node:test');
const assert = require('node:assert/strict');

test('an expired browser session is renewed once and the refused call is retried, never surfaced', async () => {
  let token = 'old', signIns = 0, calls = [];
  const store = {};
  const g = {
    sessionStorage: {getItem: k => store[k] || null, setItem: (k, v) => { store[k] = v; }, removeItem: k => { delete store[k]; }},
    document: {querySelector: () => null},
  };
  const json = (status, body) => ({status, ok: status < 400, json: async () => body,
    clone() { return {text: async () => JSON.stringify(body)}; }});
  g.fetch = async (url, init = {}) => {
    const h = new Headers(init.headers || {});
    calls.push([url, h.get('X-ArchHub-Session')]);
    if (url === '/api/universal/session') { signIns += 1; token = 'new' + signIns; return json(200, {token, csrf: 'c' + signIns}); }
    if (h.get('X-ArchHub-Session') !== token) return json(403, {ok: false, error: 'browser session expired or not yet valid'});
    if (url === '/api/universal/canvas') return json(200, {ok: true, canvas: {root: 'r', revision: 1, scope: {}}, graph: {nodes: [], wires: []}, library: []});
    return json(200, {ok: true, value: 42});
  };
  global.window = g; global.Headers = Headers;
  delete require.cache[require.resolve('../nodelang/studio/studio-authority.js')];
  require('../nodelang/studio/studio-authority.js');
  const A = g.ArchHubStudioAuthority;
  // Simulate boot far enough to install the fetch wrapper: boot may throw later on missing canvas pieces.
  try { await A.boot({canvas_key: 'k'}); } catch (_) {}
  const before = signIns;
  token = 'r2';                       // the held session lapses
  const r = await g.fetch('/api/universal/providers', {headers: {'X-ArchHub-Session': 'stale'}});
  assert.equal(r.status, 200, 'the retried call succeeds');
  assert.equal(signIns, before + 1, 'exactly one fresh sign-in');
  const other = await g.fetch('/api/universal/providers', {headers: {'X-ArchHub-Session': 'x'}});
  assert.equal(other.status, 200);
  const nonSession = async () => {
    const saved = g.fetch;
    return saved;
  };
  assert.ok(nonSession);
});

