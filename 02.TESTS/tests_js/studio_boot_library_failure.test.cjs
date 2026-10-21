/* Home mounts before the catalogue is requested. The first library open keeps
   the original success/refusal behavior through the real studio.html loader. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const studio = path.join(__dirname, '../../01.APP/nodelang/studio');
const html = fs.readFileSync(path.join(studio, 'studio.html'), 'utf8');
const start = html.indexOf('    let nodeLibrary = {};');
const end = html.indexOf('    function projectStudioCanvas', start);
const block = html.slice(start, end);

async function runBlock(jget) {
  const window = {dispatchEvent() {}, addEventListener() {}};
  const context = vm.createContext({window, jget, String, CustomEvent:class {constructor(type) {this.type = type;}}});
  await vm.runInContext('(async () => {' + block + '})()', context);
  return window;
}

test('a refused library read leaves an empty library and the reason, and boot goes on', async () => {
  assert.ok(start > 0 && end > start, 'the library block is where Studio boots');
  const window = await runBlock(async () => { throw new Error('the node library is not installed in this graph yet'); });
  assert.equal(window.AH_LIBRARY_ERROR, '', 'Home has not requested the library');
  await assert.rejects(window.AH_LOAD_LIBRARY(), /the node library is not installed/);
  assert.equal(JSON.stringify(window.AH_LIBRARY), '[]');
  assert.equal(JSON.stringify(window.WIRE_PARAMS), '[]');
  assert.equal(window.AH_LIBRARY_ERROR, 'the node library is not installed in this graph yet');
  assert.equal(window.WIRE_PARAMS_ERROR, 'the node library is not installed in this graph yet');
  const rest = html.slice(end);
  const mount = rest.indexOf('await mountStudio();');
  assert.ok(mount > 0, 'boot still mounts Studio after the library block');
  assert.doesNotMatch(rest.slice(0, mount), /\n\s*(throw |return;)/, 'nothing between the library and the mount stops the boot');
});

test('a served library is used and no error is kept', async () => {
  const groups = [{cat: 'logic', items: [{id: 'l_if', engine: 'library.if'}]}];
  const window = await runBlock(async () => ({groups, categories: {'library.if': 'logic'}, wire_parameters: [{k: 'enabled'}]}));
  await window.AH_LOAD_LIBRARY();
  assert.equal(JSON.stringify(window.AH_LIBRARY), JSON.stringify(groups));
  assert.equal(window.AH_LIBRARY_ERROR, '');
  assert.equal(window.WIRE_PARAMS.length, 1);
});

test('Home issues no library request; concurrent first opens share one and later opens reuse it', async () => {
  let reads = 0, answer;
  const window = await runBlock(() => { reads += 1; return new Promise(resolve => {answer = resolve;}); });
  assert.equal(reads, 0);
  const first = window.AH_LOAD_LIBRARY();
  const second = window.AH_LOAD_LIBRARY();
  assert.equal(first, second);
  assert.equal(reads, 1);
  answer({groups:[], categories:{}, wire_parameters:[]});
  await first;
  await window.AH_LOAD_LIBRARY();
  assert.equal(reads, 1, 'a successful empty catalogue is still a completed read');
  assert.equal(window.AH_LIBRARY_LOADED, true);
  assert.equal(window.AH_LIBRARY_LOADING, false);
});

test('a failed first read can retry, and MODS refresh updates all catalogue indexes', async () => {
  let reads = 0;
  const window = await runBlock(async () => {
    if (++reads === 1) throw new Error('library unavailable');
    return {groups:[{cat:'logic', items:[{id:'mod' + reads}]}],
      categories:{['mod' + reads]:'logic'}, wire_parameters:[{k:'wire' + reads}]};
  });
  await assert.rejects(window.AH_LOAD_LIBRARY(), /library unavailable/);
  await window.AH_LOAD_LIBRARY();
  assert.equal(window.AH_LIBRARY_ERROR, '');
  assert.equal(window.WIRE_PARAMS_ERROR, '');
  await window.ARCHHUB_REFRESH_NODE_LIBRARY();
  assert.equal(reads, 3);
  assert.equal(window.AH_LIBRARY[0].items[0].id, 'mod3');
  assert.equal(window.AH_ENGINE_CATEGORIES.mod3, 'logic');
  assert.equal(window.WIRE_PARAMS[0].k, 'wire3');
});

test('the Nodes panel says why the library is empty', () => {
  const lm = fs.readFileSync(path.join(studio, 'studio-lm.jsx'), 'utf8');
  const panel = lm.slice(lm.indexOf('const NodesPanel = '), lm.indexOf('{library.map(group => {', lm.indexOf('const NodesPanel = ')));
  assert.match(panel, /libraryRead\.loading \|\| libraryRead\.error \|\| !library\.length/);
  assert.match(panel, /detail=\{libraryRead\.error\}[\s\S]*onRetry=\{libraryRead\.error \|\| !library\.length \? libraryRead\.retry/);
});
