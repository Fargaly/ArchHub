const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

const studio = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/studio-lm.jsx'), 'utf8');

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

test('BABOOM composer turn shows a step without raw JSON text', () => {
  const start = studio.indexOf('const BaboomToolSteps =');
  const end = studio.indexOf('// The wired pipeline', start);
  const body = studio.slice(start, end);
  assert.doesNotMatch(body, /JSON\.stringify\(\{args:step\.args/);
  assert.match(body, /formatBaboomStepDetail\(step\)/);

  const dom = new JSDOM('<!doctype html><section data-baboom-turn=""></section>');
  const turn = dom.window.document.querySelector('[data-baboom-turn]');
  const text = dom.window.document.createElement('p');
  text.textContent = 'ArchHub can see the host probe.';
  const step = dom.window.document.createElement('details');
  step.setAttribute('data-baboom-step', '');
  const summary = dom.window.document.createElement('summary');
  summary.textContent = 'host.ping ok programs visible';
  step.appendChild(summary);
  turn.append(text, step);

  assert.ok(turn.querySelector('[data-baboom-step]'));
  assert.equal(turn.textContent.includes('{'), false);
});
