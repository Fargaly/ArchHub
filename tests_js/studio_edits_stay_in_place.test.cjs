/* An ordinary canvas edit never reloads the Studio page (founder, 2026-09-30: "the node library doesn't
   work"). Placing a library node, copying a node and deleting nodes used to call window.location.reload(),
   which re-ran the whole page boot; on a large graph that looked like the app breaking after every edit.
   Each now re-reads the canvas in place. Navigations (opening another graph or scope) may still reload. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const body = (start, end) => {
  const from = source.indexOf(start);
  assert.ok(from > 0, 'found: ' + start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(to > from, 'found the end of: ' + start);
  return source.slice(from, to);
};

test('the in-place refresh re-reads the canvas and never reloads the page under the user', () => {
  const helper = body('const studioRefreshCanvasInPlace = () => {', '\n};');
  assert.match(helper, /refreshTopologyCanvas\(\)/);
  assert.doesNotMatch(helper, /location\.reload\(/, 'no full-page reload fallback');
});

for (const [name, start, end] of [
  ['placing a library node', 'const addNodeFromLibrary = (libItem', '\n  };'],
  ['copying a node', 'const menuDuplicate = node => menuTask(', '\n  });'],
  ['deleting nodes', 'const confirmRemoval = () => {', '\n  };'],
]) {
  test(name + ' re-reads the canvas in place, never reloading the page', () => {
    const code = body(start, end);
    assert.doesNotMatch(code, /location\.reload\(|location\.href\s*=|location\.assign\(|location\.replace\(/,
      name + ' must not navigate');
    assert.match(code, /studioRefreshCanvasInPlace\(\)/, name + ' refreshes the canvas in place');
  });
}
