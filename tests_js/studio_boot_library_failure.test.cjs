/* Studio boot survives a node library it cannot read. The real studio.html block runs with a jget that
   refuses (the 503 of a graph whose library is not installed yet, or any fault): the library and wire
   rows become empty, the reason is kept for the Nodes panel, and the boot still reaches mountStudio. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const studio = path.join(__dirname, '../nodelang/studio');
const html = fs.readFileSync(path.join(studio, 'studio.html'), 'utf8');
const start = html.indexOf('    let nodeLibrary = {};');
const end = html.indexOf("window.WIRE_PARAMS = nodeLibrary.wire_parameters || [];", start);
const block = html.slice(start, html.indexOf('\n', end));

async function runBlock(jget) {
  const window = {};
  const context = vm.createContext({window, jget, String});
  await vm.runInContext('(async () => {' + block + '})()', context);
  return window;
}

test('a refused library read leaves an empty library and the reason, and boot goes on', async () => {
  assert.ok(start > 0 && end > start, 'the library block is where Studio boots');
  const window = await runBlock(async () => { throw new Error('the node library is not installed in this graph yet'); });
  assert.equal(JSON.stringify(window.AH_LIBRARY), '[]');
  assert.equal(JSON.stringify(window.WIRE_PARAMS), '[]');
  assert.equal(window.AH_LIBRARY_ERROR, 'the node library is not installed in this graph yet');
  assert.equal(window.WIRE_PARAMS_ERROR, 'the node library is not installed in this graph yet');
  const rest = html.slice(html.indexOf('\n', end));
  const mount = rest.indexOf('await mountStudio();');
  assert.ok(mount > 0, 'boot still mounts Studio after the library block');
  assert.doesNotMatch(rest.slice(0, mount), /\n\s*(throw |return;)/, 'nothing between the library and the mount stops the boot');
});

test('a served library is used and no error is kept', async () => {
  const groups = [{cat: 'logic', items: [{id: 'l_if', engine: 'library.if'}]}];
  const window = await runBlock(async () => ({groups, categories: {'library.if': 'logic'}, wire_parameters: [{k: 'enabled'}]}));
  assert.equal(JSON.stringify(window.AH_LIBRARY), JSON.stringify(groups));
  assert.equal(window.AH_LIBRARY_ERROR, '');
  assert.equal(window.WIRE_PARAMS.length, 1);
});

test('the Nodes panel says why the library is empty', () => {
  const lm = fs.readFileSync(path.join(studio, 'studio-lm.jsx'), 'utf8');
  const panel = lm.slice(lm.indexOf('const NodesPanel = '), lm.indexOf('{library.map(group => {', lm.indexOf('const NodesPanel = ')));
  assert.match(panel, /!library\.length && window\.AH_LIBRARY_ERROR/);
  assert.match(panel, /The node library could not be loaded: /);
});