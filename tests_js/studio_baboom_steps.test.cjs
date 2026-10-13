const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const studio = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');

test('BABOOM step rows render tool name, status, and collapsible details', () => {
  const start = studio.indexOf('const BaboomToolSteps =');
  const end = studio.indexOf('// The wired pipeline', start);
  const body = studio.slice(start, end);
  assert.ok(start > 0 && end > start, 'BABOOM step renderer exists near chat components');
  assert.match(body, /<details[^>]+data-baboom-step/);
  assert.match(body, /data-status=\{step\.status\}/);
  assert.match(body, /<summary/);
  assert.match(body, /\{step\.tool\}/);
  assert.match(body, /\{step\.status\}/);
});

test('BABOOM steps flow from agent replies into visible chat turns', () => {
  assert.match(studio, /steps:agentAnswerSteps\(answer\)/);
  assert.match(studio, /steps:agentAnswerSteps\(result\)/);
  assert.match(studio, /<BaboomToolSteps steps=\{m\.steps\}\/>/);
  assert.match(studio, /<BaboomToolSteps steps=\{row\.steps\}\/>/);
});
