const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');

test('Studio JSX remains syntactically valid', () => {
  require('esbuild').transformSync(source, {loader:'jsx', target:'es2020'});
});

test('new graph sends once and keeps an uncertain receipt from replaying', async () => {
  const start = source.indexOf('  const createGraph = async event =>');
  const end = source.indexOf('  const shown =', start);
  assert.ok(start > 0 && end > start);
  const calls = [], errors = [];
  let reloads = 0;
  const context = {title:'  My graph  ', submitted:{current:false},
    setCreating() {}, setCreateError: value => errors.push(value),
    window:{ARCHHUB_GRAPH_CREATE: async title => {calls.push(title); throw new Error('Receipt lost');},
      location:{reload() {reloads++;}}}};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nthis.create = createGraph;', context);
  await context.create({preventDefault() {}});
  await context.create({preventDefault() {}});
  assert.deepEqual(calls, ['My graph']);
  assert.equal(reloads, 0);
  assert.match(errors.at(-1), /Receipt lost.*Refresh the graph list/);
  assert.equal(context.title, '  My graph  ');
});

test('graph card reload follows the admitted scope response and refuses failed opens', async () => {
  const start = source.indexOf('  const openSession = async (id) =>');
  const end = source.indexOf('  const closeTab =', start);
  const events = [];
  const context = {openTabs:[], setOpenTabs() {}, setOpenId() {},
    window:{ARCHHUB_GRAPH_OPEN: async root => {events.push(root);},
      location:{reload() {events.push('reload');}}, alert: value => events.push(value)}};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nthis.open = openSession;', context);
  await context.open('visible-composition');
  assert.deepEqual(events, ['visible-composition', 'reload']);
  context.window.ARCHHUB_GRAPH_OPEN = async () => {throw new Error('Not admitted');};
  await context.open('hidden-composition');
  assert.deepEqual(events, ['visible-composition', 'reload', 'Not admitted']);
});

test('native selection uses its callback, blocks ambiguous endpoints and never sets a model', async () => {
  const start = source.indexOf('  const chooseNative = async row =>');
  const end = source.indexOf('  const choose = async value =>', start);
  assert.ok(start > 0 && end > start);
  const selected = [];
  let closed = 0;
  const context = {saving:false, setSaving() {}, setSelectionError() {},
    onNativeSelect: async row => selected.push(row.session_id), onClose() {closed++;},
    setModel() {throw new Error('Native sessions must not become model API routes');}};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nthis.chooseNative = chooseNative;', context);
  for (const row of [
    {kind:'native-session',session_id:'offline',connected:false},
    {kind:'native-session',session_id:'ambiguous',connected:true,reason:'ambiguous_endpoint'},
    {kind:'native-session',session_id:'withheld',connected:true,selectable:false},
    {kind:'native-session',session_id:'open-unbound',connected:true,selectable:true},
  ]) await context.chooseNative(row);
  assert.deepEqual(selected, ['open-unbound']);
  assert.equal(closed, 1);
});

test('scope paths use a fresh admitted binding at every level', async () => {
  const html = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio.html'), 'utf8');
  const start = html.indexOf('    window.ARCHHUB_SCOPE_OPEN = async targets =>');
  const end = html.indexOf('    // The first edit', start);
  assert.ok(start > 0 && end > start);
  const canvas = (current, next, revision) => ({revision, scope:{current,trail:[{root:'root'}]},
    nodes:next ? [{id:next,openable:true}] : [],
    interaction_projection:{bindings:(next ? [next] : []).concat(current === 'root' ? [] : ['root'])
      .map(control => ({control,interaction:'open-'+control,event:'click'}))}});
  const projections = [canvas('draft','node',1),canvas('root','brain',2),canvas('brain','workbench',3),canvas('workbench',null,4)];
  const requests = [];
  const context = {window:{}, jget:async () => projections.shift(),
    jpost:async (path, body) => {requests.push({...body});}};
  vm.createContext(context);
  vm.runInContext(html.slice(start, end), context);
  const result = await context.window.ARCHHUB_SCOPE_OPEN(['brain','workbench']);
  assert.equal(result.scope.current, 'workbench');
  assert.deepEqual(requests.map(row => [row.control,row.revision]), [['root',1],['brain',2],['workbench',3]]);
  projections.push(canvas('root','brain',5));
  await assert.rejects(context.window.ARCHHUB_SCOPE_OPEN(['hidden']), /outside this view/);
  assert.equal(requests.length, 3);
});
