/* Court: Settings > Hosts is never a live-probe catalogue. The catalogue is
   static; the live probe only overlays status. A live empty, partial or
   unreachable coordination read must still draw every catalogue host. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'nodelang', 'studio', 'studio.html'), 'utf8');

// Extract the ARCHHUB_LOAD_HOSTS arrow function source from studio.html.
function loader(scanOrError) {
  const start = html.indexOf('window.ARCHHUB_LOAD_HOSTS = async () => {');
  assert.notEqual(start, -1, 'ARCHHUB_LOAD_HOSTS not found in studio.html');
  const open = html.indexOf('{', start);
  let depth = 0, end = -1;
  for (let i = open; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}') { depth--; if (depth === 0) { end = i; break; } }
  }
  const body = html.slice(open + 1, end);
  const win = { ARCHHUB_HOST_OPERATIONS: undefined };
  const scan = scanOrError || { ok: true, operations: [{ op_id: 'revit.list_walls' }],
    connectors: [
      { id: 'revit', name: 'Revit', state: 'connected', drive: 'revit.exec', detail: 'add-in on :48884' },
      { id: 'rhino', name: 'Rhino', state: 'installed', drive: 'rhino.exec', detail: 'say "open Rhino"' },
    ] };
  const jget = async () => {
    if (scan instanceof Error) throw scan;
    return scan;
  };
  const fn = new Function('jget', 'window', 'return (async () => {' + body + '})();');
  return { run: () => fn(jget, win), scan, win };
}

test('the hosts list comes only from the server connector catalogue', async () => {
  const { run, scan } = loader();
  const live = await run();
  assert.equal(live.hosts.length, scan.connectors.length, 'no page-local catalogue pads the server rows');
  assert.equal(live.hosts.find(row => row.id === 'revit').state, 'connected');
  assert.equal(live.hosts.find(row => row.id === 'rhino').state, 'installed');
  assert.equal(live.hosts.find(row => row.id === 'autocad'), undefined);
  assert.deepEqual(live.connectors, live.hosts, 'connectors and Settings use the same merged rows');
});

test('live empty coordination returns an empty server catalogue', async () => {
  const { run } = loader({ ok: true, operations: [], connectors: [] });
  const live = await run();
  assert.deepEqual(live.hosts, []);
  assert.deepEqual(live.connectors, []);
});

test('unreachable coordination rejects instead of inventing a healthy catalogue', async () => {
  const { run } = loader(new Error('coordination unavailable'));
  await assert.rejects(run(), /coordination unavailable/);
});
