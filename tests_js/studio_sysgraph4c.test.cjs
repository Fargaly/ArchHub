const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const studio = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');

const slice = (source, startNeedle, endNeedle) => {
  const start = source.indexOf(startNeedle);
  const end = source.indexOf(endNeedle, start + startNeedle.length);
  assert.ok(start >= 0, startNeedle + ' exists');
  assert.ok(end > start, endNeedle + ' follows ' + startNeedle);
  return source.slice(start, end);
};

const layoutFns = () => {
  const context = vm.createContext({});
  const code = slice(studio, 'const CANVAS_FIT_TOP =', 'const CANVAS_LAYOUT_COALESCE_MS') +
    '\nglobalThis.fit = canvasFitBounds; globalThis.arrange = canvasArrangePositions;';
  vm.runInContext(code, context);
  return context;
};

test('SYSGRAPH4c: Arrange+Fit fits all visible cards, including pinned cards kept in place', () => {
  const canvas = slice(studio, 'const NodeCanvas =', 'const CanvasContextHint =');
  assert.doesNotMatch(canvas, /canvasFitBounds\(movable,/);
  assert.match(canvas, /canvasFitBounds\(allIds,/);
  assert.match(canvas, /\{\.\.\.positions,\s*\.\.\.next\}/);
});

test('SYSGRAPH4c: System auto-arrange marks done only after confirmed arrange success', () => {
  const canvas = slice(studio, 'const NodeCanvas =', 'const CanvasContextHint =');
  const effect = slice(canvas, 'const systemAutoArrangeDone =', '// Undo / Redo');
  assert.doesNotMatch(effect, /systemAutoArrangeDone\.current = systemAutoArrangeKey;\s*arrangeIds/);
  assert.match(effect, /arrangeIds\(allIds,\s*\{[^}]*fitAfter:true[^}]*\}\)\.then\(arranged =>/);
  assert.match(effect, /if \(arranged\) systemAutoArrangeDone\.current = systemAutoArrangeKey/);
});

test('SYSGRAPH4c: crossings metric is not presented as exact while using an estimate', () => {
  const header = slice(studio, 'const WsHeader =', 'const crumbBtn =');
  assert.match(header, /≈ crossings/);
  assert.doesNotMatch(header, /\{systemArrangeSummary\.crossings\}\s*crossings/);
});

test('SYSGRAPH4c: Settings System preview uses the shared mini graph, not an indexed summary grid', () => {
  const panel = slice(studio, 'const SystemMiniGraph =', 'const SettingsHub =');
  assert.match(panel, /<SystemMiniGraph[\s\S]*graph=\{graph\}/);
  assert.match(panel, /data-system-mini-graph/);
  assert.match(panel, /data-system-mini-wire/);
  assert.match(panel, /member_count|memberCount|group boundary/i);
  assert.doesNotMatch(panel, /slice\(0,\s*24\)/);
  assert.doesNotMatch(panel, /Math\.floor\(index \/ 4\)/);
});

test('SYSGRAPH4c: System graph states are real, visible when selected, and have working actions', () => {
  const states = slice(studio, 'const SystemGraphStates =', 'const SettingsHub =');
  assert.doesNotMatch(states, /hidden = false/);
  assert.doesNotMatch(states, /3 cards|other 21|Unpin 3/);
  assert.match(states, /state === 'error'/);
  assert.match(states, /onReadAgain/);
  assert.match(states, /onBackToSettings/);
  assert.match(states, /onAddNode/);
  assert.match(states, /pinnedCount/);
});

test('SYSGRAPH4c: oversized dependency layers wrap so the first fit remains readable', () => {
  const {arrange, fit} = layoutFns();
  const ids = Array.from({length:20}, (_, i) => 'n' + i);
  const positions = Object.fromEntries(ids.map((id, i) => [id, {x:(i % 5) * 20, y:Math.floor(i / 5) * 20}]));
  const sizes = Object.fromEntries(ids.map(id => [id, {w:220, h:110}]));
  const wires = [];
  for (let i = 1; i < 16; i += 1) wires.push({from:['n0'], to:['n' + i]});
  for (let i = 1; i < 16; i += 1) wires.push({from:['n' + i], to:['n16']});
  wires.push({from:['n16'], to:['n17']}, {from:['n17'], to:['n18']}, {from:['n18'], to:['n19']});
  const next = arrange(ids, positions, sizes, ids, wires);
  const fitted = fit(ids, next, sizes, {width:1440, height:900});
  assert.ok(fitted.zoom >= 0.6, 'fit zoom is readable: ' + fitted.zoom);
  const maxColumnHeight = Math.max(...Object.values(Object.groupBy(ids, id => next[id].x)).map(column => {
    const tops = column.map(id => next[id].y);
    return Math.max(...column.map(id => next[id].y + sizes[id].h)) - Math.min(...tops);
  }));
  assert.ok(maxColumnHeight <= (900 - 158) / 0.6, 'no wrapped column is taller than the readable viewport');
});
