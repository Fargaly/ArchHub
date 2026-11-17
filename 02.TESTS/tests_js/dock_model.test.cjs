// The Canvas dock's layout rules, run as the Studio runs them (studio/dock.jsx loaded without a page).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {transformSync} = require('esbuild');

const source = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/dock.jsx'), 'utf8');
const context = vm.createContext({window: {UI: {}}});
vm.runInContext(transformSync(source, {loader: 'jsx'}).code, context);
const dock = context.window.UI.dockModel;
const plain = value => JSON.parse(JSON.stringify(value));
const tabs = (layout, side) => Array.from(layout[side].st, sl => sl.p.join('|'));

test('default layout: Workshop over Library|Map on the left, Inspector on the right', () => {
  const wide = dock.defaultLayout(1920);
  assert.deepEqual(tabs(wide, 'left'), ['workshop', 'library|map']);
  assert.deepEqual(tabs(wide, 'right'), ['insp']);
  assert.equal(wide.right.c, false);
  assert.equal(dock.defaultLayout(1366).right.c, false, 'the Inspector stays open where it is open today');
  assert.equal(dock.defaultLayout(1009).right.c, true, 'the right dock starts folded to icons on a narrow window');
  assert.equal(dock.defaultLayout(1009).left.c, false);
});

test('dropping on the upper half stacks above, the lower half stacks below', () => {
  const start = dock.defaultLayout(1920);
  const above = dock.place(start, 'map', 'right', 0, 'above');
  assert.deepEqual(tabs(above, 'right'), ['map', 'insp'], 'Map above Inspector');
  assert.deepEqual(tabs(above, 'left'), ['workshop', 'library']);
  assert.deepEqual(tabs(dock.place(start, 'map', 'right', 0, 'below'), 'right'), ['insp', 'map']);
  assert.deepEqual(plain(start), plain(dock.defaultLayout(1920)), 'the layout it started from is not changed');
});

test('dropping on a header tabs the panel with that slot and opens it', () => {
  const folded = dock.toggleSlot(dock.defaultLayout(1920), 'left', 0);
  const tabbed = dock.place(folded, 'map', 'left', 0, 'tab');
  assert.deepEqual(tabs(tabbed, 'left'), ['workshop|map', 'library']);
  assert.equal(tabbed.left.st[0].a, 'map');
  assert.equal(tabbed.left.st[0].c, false);
  assert.equal(tabbed.left.st[1].a, 'library', 'the slot it left shows its remaining tab');
});

test('a slot emptied by a move goes away and the target is still found', () => {
  const start = dock.place(dock.defaultLayout(1920), 'map', 'left', 0, 'above');  // map / workshop / library
  assert.deepEqual(tabs(start, 'left'), ['map', 'workshop', 'library']);
  const moved = dock.place(start, 'map', 'left', 2, 'below');  // its own slot (above the target) disappears first
  assert.deepEqual(tabs(moved, 'left'), ['workshop', 'library', 'map']);
  assert.equal(dock.place(moved, 'map', 'left', 2, 'tab'), moved, 'dropping a lone panel on itself changes nothing');
});

test('an emptied dock takes a panel back from its edge', () => {
  const emptied = dock.place(dock.defaultLayout(1920), 'insp', 'left', 0, 'tab');
  assert.deepEqual(tabs(emptied, 'right'), []);
  const back = dock.place(emptied, 'insp', 'right', 0, 'dock');
  assert.deepEqual(tabs(back, 'right'), ['insp']);
  assert.deepEqual(tabs(dock.place(back, 'map', 'right', 0, 'dock'), 'right'), ['insp|map'], 'an edge drop joins the last slot');
});

test('collapse to the header, fold the dock, show and hide', () => {
  const start = dock.defaultLayout(1009);
  assert.equal(dock.visible(start, 'insp'), false);
  const shown = dock.show(start, 'insp');
  assert.equal(shown.right.c, false);
  assert.equal(dock.visible(shown, 'insp'), true);
  assert.equal(dock.show(shown, 'insp'), shown, 'showing a visible panel changes nothing');
  const map = dock.show(shown, 'map');
  assert.equal(map.left.st[1].a, 'map');
  assert.equal(dock.visible(map, 'library'), false);
  const hidden = dock.hide(map, 'map');
  assert.equal(hidden.left.st[1].c, true);
  assert.equal(dock.toggleSlot(hidden, 'left', 1).left.st[1].c, false);
  assert.equal(dock.toggleDock(start, 'left').left.c, true);
});

test('stack splitter shares the two neighbours and leaves the others alone', () => {
  const three = dock.place(dock.defaultLayout(1920), 'map', 'left', 1, 'below');  // workshop 1.15 / library 1 / map 1
  const sized = dock.resizeSlots(three, 'left', 0, 300, 100);
  assert.equal(sized.left.st[2].h, 1);
  assert.ok(Math.abs(sized.left.st[0].h + sized.left.st[1].h - 2.15) < .002);
  assert.ok(Math.abs(sized.left.st[0].h / sized.left.st[1].h - 3) < .02);
  const pinned = dock.resizeSlots(three, 'left', 0, 395, 5);
  assert.ok(pinned.left.st[1].h >= .05 && pinned.left.st[1].h < .25, 'the lower panel keeps its header');
  assert.equal(dock.setLeftWidth(three, 9999).left.w, 360);
  assert.equal(dock.setLeftWidth(three, 10).left.w, 200);
});

test('a stored record is repaired: unknown and repeated panels go, missing ones return to their home dock', () => {
  const repaired = dock.normalize({left: {w: 5000, c: false, st: [{p: ['workshop', 'chat', 'workshop'], a: 'chat', h: -4, c: false}]},
    right: {c: true, st: [{p: ['workshop'], a: 'workshop', h: 1, c: false}]}}, 1920);
  assert.deepEqual(tabs(repaired, 'left'), ['workshop|library|map']);
  assert.deepEqual(tabs(repaired, 'right'), ['insp']);
  assert.equal(repaired.left.w, 360);
  assert.equal(repaired.left.st[0].a, 'workshop');
  assert.equal(repaired.left.st[0].h, 1);
  assert.deepEqual(plain(dock.normalize(null, 1009)), plain(dock.defaultLayout(1009)));
  const kept = dock.place(dock.defaultLayout(1920), 'map', 'right', 0, 'above');
  assert.deepEqual(plain(dock.normalize(plain(kept), 1920)), plain(kept), 'a valid record comes back as it was saved');
});
