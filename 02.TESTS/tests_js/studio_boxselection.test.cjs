// SPEC 7.4: a selection window dragged left to right is a containing window, right to left a crossing window.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const React = require('react');
const {transformSync} = require('esbuild');

const screens = path.resolve(__dirname, '../../01.APP/nodelang/studio/ds_screens.jsx');

test('the Canvas selection window contains left to right and crosses right to left, at any zoom', t => {
  const page = new (require('jsdom').JSDOM)('<!doctype html><html></html>');
  t.after(() => page.window.close());
  const ui = {
    taskRowReason: () => '',
    A: {ok: '#3a3', warn: '#a80', err: '#a33', ink: '#111', inkSoft: '#666', inkDim: '#888', accent: '#d97757', purple: '#86f', cyan: '#5cc', bgCanvas: '#101015', bgPanel: '#15151a', bgSoft: '#1a1a20', bgHover: '#222', line: '#26262e', lineSoft: '#333', accentDim: '#2a1812', rad: {xs: 3, sm: 5, md: 6, lg: 8, xl: 10, pill: 999}},
    D: {}, api: {}, useData() { return {}; }, useApp() { return {}; }, Btn() { return null; }, Chip() { return null; },
  };
  Object.assign(page.window, {UI: ui, ReactResizablePanels: require('react-resizable-panels'), executeAction() {}, registerActions() {}});
  vm.runInNewContext(transformSync(fs.readFileSync(screens, 'utf8'), {loader: 'jsx', jsx: 'transform'}).code, {
    window: page.window, document: page.window.document, React, console,
  });
  const pick = ui.boxSelection;
  // inside: wholly in the window; edge: half in; far: outside it.
  const boxes = [{id: 'inside', x: 100, y: 100, w: 200, h: 100}, {id: 'edge', x: 380, y: 100, w: 200, h: 100}, {id: 'far', x: 900, y: 100, w: 200, h: 100}];
  const a = {x: 50, y: 50}, b = {x: 450, y: 300};
  assert.deepEqual(pick(boxes, a, b, false), ['inside'], 'left to right keeps only nodes wholly inside');
  assert.deepEqual(pick(boxes, b, a, true), ['inside', 'edge'], 'right to left takes every node it touches');
  assert.deepEqual(pick(boxes, b, a, false), ['inside'], 'the corners may arrive in either order');
  assert.deepEqual(pick(boxes, {x: 700, y: 400}, {x: 800, y: 500}, true), [], 'an empty window selects nothing');
  assert.deepEqual(pick(boxes, {x: 300, y: 200}, {x: 380, y: 260}, true), [], 'touching edges alone do not cross');
});
