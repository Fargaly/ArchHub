const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');

const app = fs.readFileSync(path.join(root, '01.APP/nodelang/universal_application.py'), 'utf8');

test('SYSGRAPH4: System graph source admits tool nodes without duplicating connector and cloud domains', () => {
  assert.match(app, /_SYSTEM_TOOL_CANVAS_NODES/);
  for (const id of ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']) {
    assert.match(app, new RegExp('"tool_' + id + '"'));
  }
  assert.match(app, /_ensure_system_tool_canvas_nodes/);
  assert.match(app, /if tool_id in \{"tool_connectors", "tool_cloud"\}/);
  assert.match(app, /target_root = map_registry\.domains\[domain_key\]/);
});
