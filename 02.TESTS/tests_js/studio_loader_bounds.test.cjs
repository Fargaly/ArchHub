'use strict';
// The runtime loader (studio.html) and the precompiler (compile_studio.cjs) each bound Studio sources.
// They drifted once: the compiler accepted a 524 KB studio-lm.jsx the loader then refused, so the
// installed Studio showed "Studio build file metadata is invalid." These checks keep the two in step
// and run the loader's per-file and aggregate predicates against the real compiled manifest.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const read = rel => fs.readFileSync(path.join(root, rel), 'utf8');
const num = text => Function('"use strict"; return (' + text + ');')();

const loader = read('01.APP/nodelang/studio/studio.html');
const compiler = read('01.APP/packaging/compile_studio.cjs');

const loaderSourceBound = num(loader.match(/file\.source_bytes > (\d+)/)[1]);
const loaderAssetBound = num(loader.match(/await asset\(file\.source, (\d+)\)/)[1]);
const loaderOutputBound = num(loader.match(/file\.bytes > (\d+)/)[1]);
const [, loaderSourceTotal, loaderOutputTotal] = loader.match(/sourceBytes > (\d+) \|\| outputBytes > (\d+)/).map(Number);
const compilerSourceBound = num(compiler.match(/readFile\(path\.join\(studio, source\), ([0-9 *]+)\)/)[1]);
const compilerSourceTotal = num(compiler.match(/sum \+ file\.source_bytes, 0\) <= ([0-9 *]+),/)[1]);
const compilerOutputBound = num(compiler.match(/readFile\(path\.join\(output, source\.output\), ([0-9 *]+)\)/)[1]);

test('the loader accepts every source size the precompiler accepts', () => {
  assert.equal(loaderSourceBound, compilerSourceBound, 'per-file source bound');
  assert.equal(loaderAssetBound, compilerSourceBound, 'per-file source read bound');
  assert.equal(loaderSourceTotal, compilerSourceTotal, 'aggregate source bound');
  assert.equal(loaderOutputBound, compilerOutputBound, 'per-file compiled bound');
});

test('the real compiled manifest passes the loader bounds', { skip: !fs.existsSync(path.join(root, '01.APP/nodelang/studio/compiled/manifest.json')) && 'compiled/ is built per release' }, () => {
  const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  let sourceBytes = 0, outputBytes = 0;
  for (const file of manifest.files) {
    const actual = fs.statSync(path.join(root, '01.APP/nodelang/studio', file.source)).size;
    assert.equal(file.source_bytes, actual, file.source + ' manifest size matches the source on disk');
    assert.ok(Number.isSafeInteger(file.source_bytes) && file.source_bytes >= 0 && file.source_bytes <= loaderSourceBound,
      file.source + ' (' + file.source_bytes + ' bytes) is within the loader bound ' + loaderSourceBound);
    assert.ok(Number.isSafeInteger(file.bytes) && file.bytes >= 1 && file.bytes <= loaderOutputBound, file.output + ' compiled size');
    sourceBytes += file.source_bytes; outputBytes += file.bytes;
  }
  assert.ok(sourceBytes <= loaderSourceTotal && outputBytes <= loaderOutputTotal, 'aggregate within the loader bounds');
});
