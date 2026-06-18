// cull_probe.cjs — executes the REAL viewport-cull functions extracted from
// app/web_ui/studio-lm.jsx and prints a JSON verdict. Driven by
// tests/test_canvas_ux_fin.py so the cull is gated on the ACTUAL function
// text (ROMA: gate on the real artifact, not a re-implementation). Pure Node,
// no React/DOM needed — worldViewport/bboxInViewport/cullToViewport are pure.
//
// Usage:  node cull_probe.cjs <path-to-studio-lm.jsx>
// Prints: one JSON object {ok, ...metrics} to stdout. Exit 0 on success.
'use strict';
const fs = require('fs');

const jsxPath = process.argv[2];
if (!jsxPath) { console.error('usage: node cull_probe.cjs <studio-lm.jsx>'); process.exit(2); }
const src = fs.readFileSync(jsxPath, 'utf8');

// Brace-balanced extraction of a module-scope `const NAME = (...) => { ... }`.
function extractArrow(name) {
  const re = new RegExp('const\\s+' + name + '\\s*=\\s*\\([^)]*\\)\\s*=>\\s*\\{');
  const m = re.exec(src);
  if (!m) throw new Error('function not found in source: ' + name);
  const open = src.indexOf('{', m.index + m[0].length - 1);
  let depth = 0, i = open;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { i++; break; } }
  }
  return src.slice(m.index, i) + ';';
}

let worldViewport, bboxInViewport, cullToViewport;
try {
  const code = [
    extractArrow('worldViewport'),
    extractArrow('bboxInViewport'),
    extractArrow('cullToViewport'),
  ].join('\n');
  const factory = new Function(
    code + '\nreturn { worldViewport, bboxInViewport, cullToViewport };');
  ({ worldViewport, bboxInViewport, cullToViewport } = factory());
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: String(e && e.message || e) }));
  process.exit(0);
}

const getBox = (n) => ({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h });

// 400 nodes on a 20-wide grid spread far across world space.
const N = 400;
const nodes = [];
for (let i = 0; i < N; i++) {
  nodes.push({ id: 'n' + i, x: (i % 20) * 400, y: Math.floor(i / 20) * 300, w: 220, h: 110 });
}

// A viewport showing roughly the world rect (0..1200, 0..800) at zoom 1.
const vp = worldViewport({ x: 0, y: 0 }, 1, 1200, 800);
const visible = cullToViewport(nodes, getBox, vp, 280);

// A zoomed/panned viewport elsewhere (bottom-right corner of the world).
const vp2 = worldViewport({ x: -6000, y: -2400 }, 1, 1200, 800);
const visible2 = cullToViewport(nodes, getBox, vp2, 280);

const verdict = {
  ok: true,
  total: N,
  // viewport computed (non-null) from valid pan/zoom/size
  viewport_nonnull: !!vp,
  // null viewport (unknown size) returns the FULL list unchanged (never hides)
  nullvp_returns_all: cullToViewport(nodes, getBox, null, 280).length === N,
  zero_size_viewport_null: worldViewport({ x: 0, y: 0 }, 1, 0, 0) === null,
  bad_zoom_viewport_null: worldViewport({ x: 0, y: 0 }, 0, 1200, 800) === null,
  // The headline perf invariant: a 400-node graph renders far fewer on screen.
  visible_count: visible.length,
  visible_lt_total: visible.length < N,
  visible_small: visible.length <= 60,
  // The on-screen node is kept; a far corner node is culled.
  near_kept: visible.some(n => n.id === 'n0'),
  far_culled: !visible.some(n => n.id === 'n399'),
  // Panning to another region shows a DIFFERENT, also-small subset.
  region2_count: visible2.length,
  region2_small: visible2.length <= 60,
  region2_disjoint_ish: visible2.every(n => !visible.some(m => m.id === n.id)) || visible2.length === 0,
  // A node straddling the margin edge stays mounted (no pop-in).
  margin_keeps_edge: bboxInViewport(1300, 0, 1420, 110, vp, 280) === true,
  // A node well beyond the margin is dropped.
  beyond_margin_dropped: bboxInViewport(2000, 0, 2120, 110, vp, 280) === false,
};
console.log(JSON.stringify(verdict));
