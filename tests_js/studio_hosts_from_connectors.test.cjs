/* Court: the hosts the Settings > Hosts panel shows come from the SAME probe the
   footer and Chat connectors read. The server's host_projection answers {connectors,
   operations} with NO "hosts" field; the loader must feed connectors into the hosts
   list, or the panel reads an always-empty field and says "No host has answered a
   probe yet" forever while 8 connectors answered.
   RED before the fix: the loader returned hosts: scan.hosts (undefined -> []). */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '..', 'nodelang', 'studio', 'studio.html'), 'utf8');

// Extract the ARCHHUB_LOAD_HOSTS arrow function source from studio.html.
function loader() {
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
  // host_projection answers connectors + operations, NEVER a "hosts" field.
  const scan = { ok: true, operations: [{ op_id: 'revit.list_walls' }],
    connectors: [
      { id: 'revit', name: 'Revit', state: 'connected', drive: 'revit.exec', detail: 'add-in on :48884' },
      { id: 'rhino', name: 'Rhino', state: 'installed', drive: 'rhino.exec', detail: 'say "open Rhino"' },
    ] };
  const jget = async () => scan;
  const fn = new Function('jget', 'window', 'return (async () => {' + body + '})();');
  return { run: () => fn(jget, win), scan, win };
}

test('the hosts list is fed from the connectors the probe answered, not an empty field', async () => {
  const { run, scan } = loader();
  const live = await run();
  assert.equal(live.connectors.length, 2, 'connectors must carry the probe rows');
  assert.equal(live.hosts.length, 2, 'the hosts list must NOT be empty when connectors answered');
  assert.deepEqual(live.hosts, scan.connectors, 'the hosts list IS the connectors (one source)');
});

test('no connectors answered means an honestly empty hosts list', async () => {
  const start = html.indexOf('window.ARCHHUB_LOAD_HOSTS = async () => {');
  const open = html.indexOf('{', start);
  let depth = 0, end = -1;
  for (let i = open; i < html.length; i++) { if (html[i] === '{') depth++; else if (html[i] === '}') { depth--; if (!depth) { end = i; break; } } }
  const body = html.slice(open + 1, end);
  const fn = new Function('jget', 'window', 'return (async () => {' + body + '})();');
  const live = await fn(async () => ({ ok: true, operations: [], connectors: [] }), {});
  assert.equal(live.hosts.length, 0);
  assert.equal(live.connectors.length, 0);
});
