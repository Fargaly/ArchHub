// F10: Rerun is Run again — the Inspector and node menu pass again=true so cached results do not stick.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const source = name => fs.readFileSync(path.join(studio, name), 'utf8');
const compiled = name => fs.readFileSync(path.join(studio, 'compiled', name), 'utf8');

test('Inspector Rerun calls runNode with again=true', () => {
  const text = source('app.jsx');
  assert.match(text, /function appShellRerun60[\s\S]*?api\.runNode\(n\.id,\s*true\)/);
  assert.match(compiled('app.js'), /api\.runNode\(n\.id,\s*true\)/);
});

test('node context-menu Rerun calls runNode with again=true', () => {
  const text = source('context-menus.jsx');
  assert.match(text, /menu\.rerun[\s\S]*?api\.runNode\(n\.id,\s*true\)/);
  assert.match(compiled('context-menus.js'), /api\.runNode\(n\.id,\s*true\)/);
});

test('Run to here stays a fresh root run without forcing again', () => {
  // Run to here selects a root; it must not silently become Run-all-again.
  assert.match(source('app.jsx'), /function appShellRunToHere58[\s\S]*?api\.runToHere\(n\.id\)/);
  assert.doesNotMatch(source('context-menus.jsx'), /menu\.run\.to\.here[\s\S]*?runToHere\(n\.id,\s*true\)/);
});
