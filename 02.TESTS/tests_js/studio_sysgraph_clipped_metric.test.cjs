// Coordinator 2026-10-13 (rig shot sysgraph5-shots-012730): the System chip said "11 clipped"
// while every card was fully on screen, because the canvas rect had the inspector width
// subtracted a second time. The clipped count must agree with what the user sees.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const studio = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/studio-lm.jsx'), 'utf8');

const summaryFn = () => {
  const bands = studio.match(/const CANVAS_FIT_TOP = \d+, CANVAS_FIT_BOTTOM = \d+;/);
  assert.ok(bands, 'the fit bands are declared once');
  const start = studio.indexOf('const computeLayoutSummary =');
  assert.ok(start >= 0, 'computeLayoutSummary exists');
  const end = studio.indexOf('\n};', start);
  const context = vm.createContext({});
  vm.runInContext(bands[0] + '\n' + studio.slice(start, end + 3) + '\nglobalThis.summary = computeLayoutSummary;', context);
  return context.summary;
};

test('System chip: cards fully inside the canvas are never counted as clipped', () => {
  const summary = summaryFn();
  // A 1100 x 840 canvas rect (the inspector is outside it). Four columns, the right one ending at 1070.
  const ids = ['a', 'b', 'c', 'd'];
  const positions = {a:{x:30, y:130}, b:{x:300, y:130}, c:{x:570, y:130}, d:{x:920, y:130}};
  const sizes = Object.fromEntries(ids.map(id => [id, {w:150, h:80}]));
  const result = summary(ids, positions, sizes, [], {width:1100, height:840}, 1, {x:0, y:0});
  assert.equal(result.clipped, 0, 'the right column is on screen, so nothing is clipped');
});

test('System chip: a card past the canvas edge or under the toolbar band is counted', () => {
  const summary = summaryFn();
  const ids = ['right', 'top', 'ok'];
  const positions = {right:{x:1000, y:200}, top:{x:200, y:40}, ok:{x:200, y:300}};
  const sizes = Object.fromEntries(ids.map(id => [id, {w:150, h:80}]));
  const result = summary(ids, positions, sizes, [], {width:1100, height:840}, 1, {x:0, y:0});
  assert.equal(result.clipped, 2, 'the card past the right edge and the one under the toolbar are clipped');
});
