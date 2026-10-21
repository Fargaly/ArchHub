const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const studio = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/studio-lm.jsx'), 'utf8');
const app = fs.readFileSync(path.join(root, '01.APP/nodelang/universal_application.py'), 'utf8');

const slice = (source, startNeedle, endNeedle) => {
  const start = source.indexOf(startNeedle);
  const end = source.indexOf(endNeedle, start + startNeedle.length);
  assert.ok(start >= 0, startNeedle + ' exists');
  assert.ok(end > start, endNeedle + ' follows ' + startNeedle);
  return source.slice(start, end);
};

test('SYSGRAPH4: System header reports live post-arrange metrics, never the design mock string', () => {
  const header = slice(studio, 'const WsHeader =', 'const crumbBtn =');
  assert.doesNotMatch(header, /arranged · 24 nodes · 0 overlaps/);
  assert.match(header, /systemArrangeSummary/);
  assert.match(header, /systemArrangeSummary\.cards/);
  assert.match(header, /systemArrangeSummary\.overlaps/);
  assert.match(header, /systemArrangeSummary\.clipped/);
  assert.match(header, /systemArrangeSummary\.crossings/);
});

test('SYSGRAPH4: System canvas toolbar exposes Arrange between fit and add node', () => {
  const toolbar = slice(studio, 'const CanvasToolbar =', 'const MiniMap =');
  assert.match(toolbar, /onArrange/);
  assert.match(toolbar, />Arrange</);
  assert.ok(toolbar.indexOf('onFit') < toolbar.indexOf('onArrange'), 'Arrange follows fit');
  assert.ok(toolbar.indexOf('onArrange') < toolbar.indexOf('add node'), 'Arrange precedes add node');
});

test('SYSGRAPH4: System graph auto-arranges and fits once when opened', () => {
  const canvas = slice(studio, 'const NodeCanvas =', 'const CanvasContextHint =');
  assert.match(canvas, /systemAutoArrangeKey/);
  assert.match(canvas, /arrangeIds\(allIds,\s*\{[^}]*fitAfter/);
  assert.match(canvas, /computeLayoutSummary/);
  assert.match(canvas, /setSystemArrangeSummary/);
});

test('SYSGRAPH4: System graph source admits tool nodes without duplicating connector and cloud domains', () => {
  assert.match(app, /_SYSTEM_TOOL_CANVAS_NODES/);
  for (const id of ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']) {
    assert.match(app, new RegExp('"tool_' + id + '"'));
  }
  assert.match(app, /_ensure_system_tool_canvas_nodes/);
  assert.match(app, /if tool_id in \{"tool_connectors", "tool_cloud"\}/);
  assert.match(app, /target_root = map_registry\.domains\[domain_key\]/);
});
