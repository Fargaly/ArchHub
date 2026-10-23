/* Render the real Connections component with safe Settings output; no browser or network. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const root = path.resolve(__dirname, '../..');

test('Connections renders OS names, keeps social rows, and opens credential details', () => {
  const context = vm.createContext({React, console});
  vm.runInContext(fs.readFileSync(path.join(root, '01.APP/nodelang/studio/vendor/babel.js'), 'utf8'), context);
  const shown = [];
  let actions;
  const state = {connections:[{id:'linkedin', name:'LinkedIn', connected:true}],
    secrets:[{id:'notion-mcp', name:'notion-mcp', disconnectable:false},
             {id:'openai', name:'openai', disconnectable:false}]};
  const wrap = tag => ({children}) => React.createElement(tag, null, children);
  context.window = {UI:{A:{}, D:{}, useData:() => state,
    useApp:() => ({show:(...args) => shown.push(args)}),
    Btn:wrap('button'), Card:wrap('section'), RegisteredActionStatus:() => null,
    useRegisteredActions:(_wire, handlers) => {
      actions = handlers;
      return {runAction:() => {}, actionState:null, retryAction:() => {}};
    }}};
  const source = fs.readFileSync(path.join(root, '01.APP/nodelang/studio/ds_settings3.jsx'), 'utf8');
  vm.runInContext(context.Babel.transform(source, {presets:['react']}).code, context);
  const html = renderToStaticMarkup(React.createElement(context.window.UI.Connections));
  assert.match(html, /notion-mcp/);
  assert.match(html, /openai/);
  assert.match(html, /LinkedIn/);
  assert.match(html, /Saved in Windows Credential Manager/);
  assert.match(html, /Details/);
  actions.ConnectionsAction1({credential:true}, {});
  assert.equal(shown[0][0], 'My secrets');
  actions.ConnectionsAction1(state.connections[0], {});
  assert.equal(shown[1][0], 'Connection');
});
