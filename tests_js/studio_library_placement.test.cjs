/* A library card added by double-click lands clear of every card on the canvas (founder smoke
   2026-10-01: list_walls landed on Sketch Lines at a fixed 200,200, "2 cards overlap", and the new card
   swallowed clicks meant for the card under it). A drop still lands where it was dropped. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const slice = (from, to) => {
  const start = source.indexOf(from), end = source.indexOf(to, start);
  assert.ok(start > 0 && end > start, from + ' is a slice of the shipped studio-lm.jsx');
  return source.slice(start, end);
};
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test('the free slot meets no drawn card, starting at the canvas top-left card', () => {
  const ctx = vm.createContext({});
  vm.runInContext(slice('const studioFreeSlot =', 'const studioRefreshCanvasInPlace =') + '\nglobalThis.slot = studioFreeSlot;', ctx);
  // The sample canvas as the founder sees it: two rows of cards under the frame.
  const nodes = [
    {id:'sketch', x:200, y:200, w:210, h:200}, {id:'watcher', x:480, y:200, w:210, h:140},
    {id:'walls', x:760, y:200, w:210, h:200}, {id:'cad', x:200, y:420, w:210, h:180},
    {id:'sessions', x:760, y:420, w:210, h:140},
  ];
  const at = ctx.slot(nodes);
  const card = {x:at.x, y:at.y, w:210, h:230};
  for (const node of nodes) assert.ok(!overlaps(card, node), 'the new card meets ' + node.id + ' at ' + JSON.stringify(at));
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.slot([]))), {x:60, y:92}, 'an empty canvas starts at the first card point');
});

test('a double-click takes the free slot; only a drop names its own point', () => {
  const add = slice('const addNodeFromLibrary = (', '\n  };');
  assert.doesNotMatch(add, /=\s*200\s*,\s*y\s*=\s*200/, 'no fixed default point');
  assert.match(add, /studioFreeSlot\(/, 'the free slot answers when nothing was dropped');
});
