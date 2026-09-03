// select_all_logic.fixture.mjs — headless behavioral check of the Home
// session multi-select "select all" logic.
//
// This reproduces, in plain JS, the EXACT mechanism that broke select-all in
// studio-lm.jsx: a module-level sessions array (LM_SESSIONS) that is MUTATED
// IN PLACE via .splice — so its reference never changes. A memo keyed on that
// reference therefore never recomputes and goes stale (empty). The fix is to
// recompute the visible/filtered ids FRESH at click time from the live array.
//
// Run: node tests/select_all_logic.fixture.mjs   (exit 0 = all pass)

let failures = 0;
function assert(cond, msg) {
  if (!cond) { failures++; console.error('FAIL: ' + msg); }
  else { console.log('ok: ' + msg); }
}
function eqSet(a, b) {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

// ── The live, splice-mutated module array (mirrors LM_SESSIONS) ──────
const LM_SESSIONS = [];
function spliceInPlace(next) {
  // EXACT mirror of studio-lm.jsx refreshSessions / Home effect:
  //   LM_SESSIONS.splice(0, LM_SESSIONS.length, ...fetched)
  LM_SESSIONS.splice(0, LM_SESSIONS.length, ...next);
}

// ── The pure filter (mirror of filterSessions in studio-lm.jsx) ─────
function filterSessions(src, f) {
  const list = src || [];
  if (f === 'mine') {
    const withAuthor = list.filter(s => s.author);
    if (withAuthor.length === 0) return list;
    return withAuthor.filter(s => s.author === 'me' || s.author === 'me');
  }
  if (f === 'workflows') {
    return list.filter(s => {
      const n = (s.graph && Array.isArray(s.graph.nodes) ? s.graph.nodes.length : null)
             || s.node_count || 0;
      return n >= 3;
    });
  }
  return list;
}

// ── The FIXED handler: recompute fresh from the LIVE array ──────────
function currentVisibleIds(filter) {
  return filterSessions(LM_SESSIONS, filter).map(s => s.id).filter(Boolean);
}
function toggleSelectAll_FIXED(prevSelected, filter) {
  const vis = currentVisibleIds(filter);                 // FRESH at call time
  if (vis.length > 0 && vis.every(id => prevSelected.has(id))) return new Set();
  return new Set(vis);
}

// ── The OLD broken handler: reads a memo captured by reference ──────
// staleVisibleIds simulates a useMemo([sessions]) that captured the array
// content at the time `sessions` first had a stable reference. Because
// LM_SESSIONS is spliced in place, the reference never changes, so the memo
// never recomputes — it stays whatever it was at first render (here: empty,
// the pre-hydration state).
function toggleSelectAll_OLD(prevSelected, staleVisibleIds) {
  if (staleVisibleIds.length > 0 && staleVisibleIds.every(id => prevSelected.has(id)))
    return new Set();
  return new Set(staleVisibleIds);
}

// ════════════════════════════════════════════════════════════════════
// 1. The regression: first render sees an EMPTY list (hydration race), the
//    memo captures []. Then sessions hydrate via in-place splice.
const staleMemo = currentVisibleIds('all');             // captured at empty → []
assert(staleMemo.length === 0, 'precondition: memo captured empty pre-hydration');

spliceInPlace([
  { id: 'a', title: 'A' },
  { id: 'b', title: 'B' },
  { id: 'c', title: 'C' },
]);

// OLD path: select-all over the stale memo selects NOTHING (the court bug).
const oldResult = toggleSelectAll_OLD(new Set(), staleMemo);
assert(oldResult.size === 0,
  'OLD reference-keyed select-all selects nothing after in-place splice (the bug)');

// FIXED path: select-all recomputes fresh → selects EVERY visible card.
const fixed = toggleSelectAll_FIXED(new Set(), 'all');
assert(eqSet(fixed, new Set(['a', 'b', 'c'])),
  'FIXED select-all yields the full visible set even after in-place mutation');

// ════════════════════════════════════════════════════════════════════
// 2. Select-all is a real toggle: all-selected → clear.
const cleared = toggleSelectAll_FIXED(new Set(['a', 'b', 'c']), 'all');
assert(cleared.size === 0, 'select-all toggles to clear when all already selected');

// Partial selection → select-all completes the set (not a clear).
const completed = toggleSelectAll_FIXED(new Set(['a']), 'all');
assert(eqSet(completed, new Set(['a', 'b', 'c'])),
  'select-all from a partial selection selects all remaining');

// ════════════════════════════════════════════════════════════════════
// 3. Select-all respects the ACTIVE filter (never selects hidden cards).
spliceInPlace([
  { id: 'p', title: 'plain', node_count: 1 },
  { id: 'w1', title: 'wf1', node_count: 5 },
  { id: 'w2', title: 'wf2', graph: { nodes: [1, 2, 3, 4] } },
]);
const wfSel = toggleSelectAll_FIXED(new Set(), 'workflows');
assert(eqSet(wfSel, new Set(['w1', 'w2'])),
  "select-all under 'workflows' selects only 3+-node graphs, not the plain card");
const allSel = toggleSelectAll_FIXED(new Set(), 'all');
assert(eqSet(allSel, new Set(['p', 'w1', 'w2'])),
  "select-all under 'all' selects every card");

// 'mine' falls back to all when no authors are tracked (single-user app).
const mineSel = toggleSelectAll_FIXED(new Set(), 'mine');
assert(eqSet(mineSel, new Set(['p', 'w1', 'w2'])),
  "select-all under 'mine' falls back to all when no authors tracked");

// ════════════════════════════════════════════════════════════════════
// 4. Select-all keeps working across SUCCESSIVE in-place refreshes (the
//    reference is identical every time; only contents change).
const beforeRef = LM_SESSIONS;
spliceInPlace([{ id: 'x' }, { id: 'y' }]);
assert(LM_SESSIONS === beforeRef,
  'precondition: splice keeps the SAME array reference across refreshes');
const afterRefresh = toggleSelectAll_FIXED(new Set(), 'all');
assert(eqSet(afterRefresh, new Set(['x', 'y'])),
  'select-all reflects the latest contents after a same-reference refresh');

// ════════════════════════════════════════════════════════════════════
// 5. Shift-range over the FRESH visible order (mirror of toggleSelect range).
spliceInPlace([{ id: 'r1' }, { id: 'r2' }, { id: 'r3' }, { id: 'r4' }]);
function toggleSelectRange_FIXED(prevSelected, anchorId, id, filter) {
  const vis = currentVisibleIds(filter);
  const next = new Set(prevSelected);
  const a = vis.indexOf(anchorId), b = vis.indexOf(id);
  const [lo, hi] = a < b ? [a, b] : [b, a];
  const turnOn = !prevSelected.has(id);
  for (let i = lo; i <= hi; i++) { if (turnOn) next.add(vis[i]); else next.delete(vis[i]); }
  return next;
}
const range = toggleSelectRange_FIXED(new Set(['r2']), 'r2', 'r4', 'all');
assert(eqSet(range, new Set(['r2', 'r3', 'r4'])),
  'shift-range selects the contiguous span over the fresh visible order');

// ════════════════════════════════════════════════════════════════════
if (failures) { console.error(`\n${failures} assertion(s) FAILED`); process.exit(1); }
console.log('\nALL PASS');
process.exit(0);
