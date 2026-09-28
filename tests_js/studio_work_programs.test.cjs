/* A task names the programs it may use: the Workshop editor and the create form
   both write requirements.hosts through the existing paths, never a default-all. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

function programs() {
  const {transformSync} = require('esbuild');
  const window = {};
  const context = vm.createContext({React:{createElement:() => null, useState:() => [null, () => {}]},
    window, document:{}, console, setTimeout, clearTimeout});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
  return context.window.WorkshopPrograms;
}

test('the five programs are offered by name and none is chosen by default', () => {
  const p = programs();
  assert.ok(p, 'WorkshopPrograms is exported');
  const plain = value => JSON.parse(JSON.stringify(value));
  assert.deepEqual(plain(p.LIST.map(item => [item.id, item.label])),
    [['revit', 'Revit'], ['acad', 'AutoCAD'], ['max', '3ds Max'], ['rhino', 'Rhino'], ['blender', 'Blender']]);
  assert.deepEqual(plain(p.from(null)), []);
  assert.deepEqual(plain(p.from({artifact_reviewers:['a']})), []);
  assert.deepEqual(plain(p.from({hosts:['max', 'paint', 'revit']})), ['revit', 'max']);
});

test('a change keeps every other requirement and only writes when the programs differ', () => {
  const p = programs();
  const current = {gate:{kind:'pytest'}, artifact_reviewers:['r1'], hosts:['revit']};
  assert.equal(p.change(current, ['revit']), null);
  assert.deepEqual(JSON.parse(JSON.stringify(p.change(current, ['max', 'revit']))),
    {gate:{kind:'pytest'}, artifact_reviewers:['r1'], hosts:['revit', 'max']});
  assert.deepEqual(JSON.parse(JSON.stringify(p.change(current, []))),
    {gate:{kind:'pytest'}, artifact_reviewers:['r1']});
  assert.deepEqual(JSON.parse(JSON.stringify(p.change(null, ['blender']))), {hosts:['blender']});
});

test('the editor and the create form both carry the selector and write through the existing paths', () => {
  const jsx = read('nodelang/studio/studio-workshop.jsx');
  assert.equal(jsx.split('Programs this task may use').length - 1, 2);
  assert.match(jsx, /WorkshopPrograms\.change\(/);
  assert.match(jsx, /programs:WorkshopPrograms\.from\(requirements\)/);
  assert.match(jsx, /hosts:repair\.programs/);
  const authority = read('nodelang/studio/studio-existing-workshop.js');
  assert.match(authority, /requirements:\{acceptance_criteria:\[\{[\s\S]*?\}\]\s*,\s*\.\.\.\(hosts\.length \? \{hosts\} : \{\}\)\}/);
});
