// Design v63 C1-C2: inside a session the composer's "All agents" is that session's agents; BABOOM only by a pick.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const React = require('react');
const {transformSync} = require('esbuild');

const source = path.resolve(__dirname, '../../01.APP/nodelang/studio/ds_workshop3.jsx');

test('All agents names only the joined agents of this session, and a send @mentions each of them', t => {
  const page = new (require('jsdom').JSDOM)('<!doctype html><html></html>');
  t.after(() => page.window.close());
  const ui = {D: {}, useData() { return {}; }, useApp() { return {}; }, Btn() { return null; }, Av() { return null; }, useAskBaboom() {}};
  Object.assign(page.window, {UI: ui, ArchHubAPI: {executeAction() {}}, AHIcon() { return null; }, registerActions() {}});
  vm.runInNewContext(transformSync(fs.readFileSync(source, 'utf8'), {loader: 'jsx', jsx: 'transform'}).code, {window: page.window, document: page.window.document, React, console});
  const choices = [
    {key: 'everyone', handle: 'everyone', name: 'Everyone'},
    {key: 'h-cad', handle: 'cad-lead', name: 'CAD lead'},          // joined, on this session
    {key: 'h-rev', handle: 'reviewer', name: 'Reviewer'},          // joined, on another session
    {key: 'Planner', handle: undefined, name: 'Planner'},          // assigned here, not joined
    {key: 'baboom', handle: '', name: 'BABOOM'},
    {key: 'start:codex', handle: 'start:codex', start: 'codex', name: 'Codex'}];
  const all = ui.sessionAll(choices, ['CAD lead', 'Planner']);
  assert.deepStrictEqual([...all.handles], ['cad-lead'], 'only a joined agent of this session receives');
  assert.strictEqual(all.name, 'All agents');
  assert.strictEqual(all.handle, 'session');
  assert.deepStrictEqual({...ui.sessionTurn(all, 'Check the sheet index')}, {prompt: '@cad-lead Check the sheet index', agent: 'BABOOM', resume: false});
  const none = ui.sessionAll(choices, ['Planner']);
  assert.strictEqual(none.handles.length, 0);
  assert.match(none.detail, /No agent of this session has joined yet/);
});
