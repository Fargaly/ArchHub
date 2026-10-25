const test = require('node:test');
const assert = require('node:assert/strict');

const path = require('node:path');

const { execFileSync } = require('node:child_process');

const root = path.join(__dirname, '..');

test('LIBRARY-64 p4 row ports equal the served canonical interface for every row', () => {
  const expected = JSON.parse(execFileSync(process.env.PYTHON || 'python', [
    '-c',
    [
      'import json',
      'from nodelang.library_engines import library_catalogue, library_item_ports',
      'rows=[[item["id"], item["ports"], library_item_ports(item["id"], item["engine"], item.get("title", ""))] for group in library_catalogue() for item in group.get("items", [])]',
      'print(json.dumps(rows))',
    ].join('; '),
  ], {cwd: root, encoding: 'utf8'}));
  for (const [id, served, canonical] of expected) {
    assert.deepEqual(served, canonical, id + ' ports come from canonical interface projection');
  }
});
