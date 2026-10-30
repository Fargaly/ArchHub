// CANVASXY: the Studio canvas runs on xyflow (@xyflow/react, pinned exactly), bundled by the Studio
// build into compiled/, never committed as a minified copy; one renderer only.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const studio = path.join(root, '01.APP/nodelang/studio');
const read = name => fs.readFileSync(path.join(studio, name), 'utf8');
const built = fs.existsSync(path.join(studio, 'compiled/xyflow.js'));

test('package.json and the lock pin @xyflow/react exactly, and the build pins the same version', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8'));
  assert.strictEqual(pkg.devDependencies['@xyflow/react'], '12.11.2');
  assert.strictEqual(lock.packages['node_modules/@xyflow/react'].version, '12.11.2');
  assert.match(fs.readFileSync(path.join(root, '03.TOOLS/packaging/compile_studio.cjs'), 'utf8'), /version:'12\.11\.2'/);
});

test('the bundled xyflow loads on the Studio React and exposes the canvas pieces', {skip: !built && 'compiled/ is built per release'}, () => {
  const manifest = JSON.parse(read('compiled/manifest.json'));
  assert.deepStrictEqual(manifest.vendor.map(v => [v.output, v.package, v.version, v.license]),
    [['xyflow.js', '@xyflow/react', '12.11.2', 'MIT'], ['xyflow.css', '@xyflow/react', '12.11.2', 'MIT']]);
  const window = {};
  window.self = window; window.window = window;
  const context = vm.createContext(window);
  vm.runInContext(read('vendor/react.js'), context);
  vm.runInContext('var React=this.React;' + read('compiled/xyflow.js'), context);
  const RF = window.ReactFlow;
  for (const name of ['ReactFlow', 'Handle', 'Position', 'applyNodeChanges']) assert.ok(RF[name], name);
  const moved = RF.applyNodeChanges([{type: 'position', id: 'a', position: {x: 5, y: 6}}], [{id: 'a', position: {x: 0, y: 0}, data: {}}]);
  assert.deepStrictEqual(moved[0].position, {x: 5, y: 6});
});

test('the loader verifies the vendor bundle and the canvas keeps no second renderer', () => {
  assert.ok(!fs.existsSync(path.join(studio, 'vendor/xyflow.js')));
  const page = read('studio.html');
  assert.ok(page.includes('manifest.vendor') && page.includes('tag.integrity=v.integrity'));
  const canvas = read('ds_screens.jsx').split('function Canvas(')[1].split('function SystemGraph(')[0];
  assert.ok(canvas.includes('<RF.ReactFlow'));
  for (const gone of ['setPointerCapture', 'measureWires', "kind: 'marquee'", 'clipPath', '<NodeRenderer']) assert.ok(!canvas.includes(gone), gone);
});
