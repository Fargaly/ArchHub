'use strict';
/* The installed Studio projects canvas rows through the shipped projectStudioCanvas slice of
   studio.html (not studio-authority.js). A node's Workshop conversation and its latest run must
   survive that projection, or NodeRail never shows them on the ordinary Canvas (installed
   cf218ae/a964379: the member's rail had no CONVERSATION section). */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

function project(raw) {
  const html = fs.readFileSync(path.join(root, 'nodelang/studio/studio.html'), 'utf8');
  const specs = html.slice(html.indexOf('    const PARAM_SPECS = {'), html.indexOf('    const canvas = await jget('));
  const fn = html.slice(html.indexOf('    function projectStudioCanvas(canvas) {'),
    html.indexOf('    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);'));
  assert.ok(specs.length > 100 && fn.length > 100, 'the projection is a slice of the shipped studio.html');
  const context = vm.createContext({});
  vm.runInContext(specs + fn + '\nglobalThis.graph = JSON.stringify(projectStudioCanvas(' + JSON.stringify(raw) + '));', context);
  return JSON.parse(context.graph);
}

const row = (id, extra) => ({id, label:id, engine:'workshop.conversation', x:10, y:20, params:[], ports:[], ...extra});

test('a bound Workshop member keeps its conversation through the ordinary projection', () => {
  const {nodes} = project({nodes:[row('assembly-instance:room', {conversation_root:'app:workshop', has_conversation:true})], wires:[]});
  assert.equal(nodes[0].has_conversation, true);
  assert.equal(nodes[0].conversation_root, 'app:workshop');
});

test('an unbound node projects no conversation', () => {
  const {nodes} = project({nodes:[row('plain')], wires:[]});
  assert.equal(nodes[0].has_conversation, false);
  assert.equal(nodes[0].conversation_root, null);
});

test('a node keeps its latest run result and mutation flag', () => {
  const {nodes} = project({nodes:[row('runner', {result:'3 walls built', mutates:true}), row('reader')], wires:[]});
  assert.equal(nodes[0].result, '3 walls built');
  assert.equal(nodes[0].mutates, true);
  assert.equal(nodes[1].result, '');
  assert.equal(nodes[1].mutates, false);
});
