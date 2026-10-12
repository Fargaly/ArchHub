// UX-INS1 (installed 2248, PM shot 02): a picked wire was titled "out → in" / "connection · any", the same
// for every wire. The inspector title names the two nodes it joins; the ports and the type move to the sub line.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-params.jsx'), 'utf8');
const begin = source.indexOf('const WIRE_SPECS =');
const fnStart = source.indexOf('function wireAsNode(');
const end = source.indexOf('\n}\n', fnStart) + 3;
const context = {window: {WIRE_PARAMS: []}, PM_OPTS: {}, PM_META: {}};
vm.createContext(context);
vm.runInContext(source.slice(begin, end) + '\nglobalThis.wireAsNode = wireAsNode;', context);

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
