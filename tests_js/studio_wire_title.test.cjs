// UX-INS1 (installed 2248, PM shot 02): a picked wire was titled "out → in" / "connection · any", the same
// for every wire. The inspector title names the two nodes it joins; the ports and the type move to the sub line.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-params.jsx'), 'utf8');
const begin = source.indexOf('const WIRE_SPECS =');
const fnStart = source.indexOf('function wireAsNode(');
const end = source.indexOf('\n}\n', fnStart) + 3;
const context = {window: {WIRE_PARAMS: []}, PM_OPTS: {}, PM_META: {}};
vm.createContext(context);
vm.runInContext(source.slice(begin, end) + '\nglobalThis.wireAsNode = wireAsNode;', context);

test('first catalogue refresh restores the original served wire defaults, options, labels and parameter rows', () => {
  const specs = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c',
    'import json; from nodelang.wire_parameters import WIRE_PARAMETER_SPECS; print(json.dumps(WIRE_PARAMETER_SPECS))'],
    {cwd:path.resolve(__dirname, '..'), encoding:'utf8'}));
  let refresh;
  const window = {WIRE_PARAMS:[], addEventListener:(name, listener) => {
    assert.equal(name, 'archhub:library-refresh'); refresh = listener;
  }};
  const lazy = vm.createContext({window, PM_OPTS:{}, PM_META:{}});
  vm.runInContext(source.slice(begin, end) + '\nglobalThis.wireAsNode = wireAsNode;', lazy);
  assert.equal(lazy.wireAsNode({id:'w', from:['watch','out'], to:['walls','in']}, 0, NODES).params.length, 0);
  const held = window.WIRE_PARAMS;
  held.splice(0, held.length, ...specs);
  refresh();
  const answer = lazy.wireAsNode({id:'w', from:['watch','out'], to:['walls','in']}, 0, NODES);
  assert.equal(window.WIRE_PARAMS, held, 'the mounted inspector retains the original array identity');
  assert.deepEqual(JSON.parse(JSON.stringify(answer.params.map(row => [row.k, row.v]))), specs.map(row => [row.k, row.def]));
  for (const spec of specs) {
    assert.equal(lazy.PM_META[spec.k].label, spec.label);
    assert.equal(lazy.PM_META[spec.k].help, spec.help);
    if (spec.opts) assert.deepEqual(JSON.parse(JSON.stringify(lazy.PM_OPTS[spec.k])), spec.opts);
  }
});

const NODES = [
  {id: 'watch', title: 'Line Watcher', outs: [{id: 'out', label: 'out', t: 'any'}], ins: []},
  {id: 'walls', title: 'Revit Walls', ins: [{id: 'in', label: 'in', t: 'any'}], outs: []},
];

test('UX-INS1: a picked wire is titled by the nodes it joins, with its ports and type on the sub line', () => {
  const wire = context.wireAsNode({id: 'w1', from: ['watch', 'out'], to: ['walls', 'in']}, 0, NODES);
  assert.equal(wire.title, 'Line Watcher → Revit Walls');
  assert.equal(wire.sub, 'wire · out → in · any');
});

test('UX-INS1: a wire whose port is missing still names its nodes and says the endpoint is unavailable', () => {
  const wire = context.wireAsNode({id: 'w2', from: ['watch', 'gone'], to: ['walls', 'in']}, 0, NODES);
  assert.equal(wire.title, 'Line Watcher → Revit Walls');
  assert.equal(wire.sub, 'wire · endpoint projection unavailable');
  assert.match(wire.endpointError, /Source interface gone is unavailable/);
});

test('UX-INS1: a type mismatch stays visible on the sub line', () => {
  const nodes = [{...NODES[0], outs: [{id: 'out', label: 'out', t: 'text'}]}, {...NODES[1], ins: [{id: 'in', label: 'in', t: 'number'}]}];
  const wire = context.wireAsNode({id: 'w3', from: ['watch', 'out'], to: ['walls', 'in']}, 0, nodes);
  assert.equal(wire.sub, 'wire · out → in · text ✕ number');
});
