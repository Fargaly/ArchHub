const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, 'nodelang/studio', file), 'utf8');

test('atlas geometry polls pause while the document is hidden', () => {
  for (const file of ['atlas-engine.jsx', 'atlas-cockpit.jsx']) {
    const source = read(file);
    assert.match(source, /document\.addEventListener\('visibilitychange', onVisibility\)/,
      file + ' listens for tab visibility changes');
    assert.match(source, /if \(!poll && !document\.hidden\) poll = setInterval/,
      file + ' starts its geometry poll only while visible');
    assert.match(source, /if \(document\.hidden\) stopPoll\(\)/,
      file + ' stops its geometry poll when hidden');
  }
  assert.match(read('atlas-engine.jsx'),
    /if \(!rafAlive && !document\.hidden\) animFb\.current = setInterval/,
    'atlas-engine does not start the 16 ms animation fallback in a hidden document');
});

test('atlas reload skips identical model replacement on idle refresh', () => {
  const source = read('atlas-cockpit.jsx');
  assert.match(source, /const atlasModelFingerprint = value =>/,
    'atlas-cockpit owns a model fingerprint helper');
  assert.match(source, /const mRef = React\.useRef\(null\)/,
    'atlas-cockpit keeps the current model identity outside async reload callbacks');
  assert.match(source, /const changed = !atlasSameModel\(mRef\.current, next\)/,
    'unchanged reload is detected');
  assert.match(source, /if \(changed\) \{ mRef\.current = next; setM\(next\); \}/,
    'unchanged reload does not call setM');
  assert.match(source, /if \(changed\) flash\('Map refreshed from your app'\)/,
    'unchanged idle reload is silent and does not look like a graph replacement');
});
