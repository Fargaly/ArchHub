const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const studio = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
const html = fs.readFileSync(path.join(root, 'nodelang/studio/studio.html'), 'utf8');

function section(name, close) {
  const start = studio.indexOf(name);
  const end = studio.indexOf(close, start + name.length);
  assert.ok(start >= 0 && end > start, name + ' section exists');
  return studio.slice(start, end);
}

test('mods use existing endpoints and library chip, not a second nav route', () => {
  const lib = section('const NodeLibrary = ', 'const LibCatBtn = ');
  assert.match(html, /ARCHHUB_MODS/);
  assert.match(html, /ARCHHUB_REFRESH_NODE_LIBRARY/);
  assert.match(lib, /From mods · \$\{modCount\}/);
  assert.match(lib, /filter === 'mods'/);
  assert.doesNotMatch(studio, /\['mods',\s*'Mods'/);
});

test('mods settings controls are live and counters are real-or-hidden', () => {
  const mods = section('const SettingsMods = ', '// -- Brain:');
  assert.match(mods, /onClick=\{\(\) => toggle\(row\)\}/);
  assert.match(mods, /action:'param'/);
  assert.match(mods, /catch\(error => setToast/);
  assert.match(mods, /row\.fired_today > 0/);
  assert.match(mods, /data-mod-row=\{row\.status\}/);
  assert.match(mods, /role="switch"/);
  assert.match(mods, /action:'enable'/);
  assert.doesNotMatch(mods, /Review folder\.\.\./);
  assert.doesNotMatch(mods, /installBrowse/);
  assert.doesNotMatch(mods, /data-mod-review/);
  assert.doesNotMatch(mods, /action:'install'/);
  assert.doesNotMatch(mods, /action:'review'/);
  assert.doesNotMatch(mods, /Make me a mod/);
  assert.doesNotMatch(mods, /BABOOM wrote/);
  assert.doesNotMatch(mods, /opened for editing/);
  assert.doesNotMatch(mods, /ready to share with firm/);
  assert.doesNotMatch(mods, /every write asks you first/);
});
