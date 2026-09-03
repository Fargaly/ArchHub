// verify_precompiled.cjs — proves the boot-lag fix end to end.
//
// Founder, 2026-06-01 ("FIX THE BOOT LAG ROOT"): the loader now prefers a
// precompiled on-disk artifact (studio-lm.compiled.js) and loads it DIRECTLY
// via <script>/eval — no in-browser Babel. This harness proves that artifact
// is valid and the no-Babel load path actually works, the way the prior
// render-count harness proved the runtime fix.
//
// It reproduces the loader's FAST PATH faithfully:
//   - vendored react.production.min.js + react-dom.production.min.js as globals
//   - read app/web_ui/studio-lm.compiled.js (the on-disk artifact)
//   - eval it as a <script> in a jsdom window (globals, NOT a module) — same
//     TDZ-bearing global scope the loader's evalGlobal() uses. NO Babel here.
//   - mount <StudioLM/> → assert no throw + window.StudioLM is a function +
//     at least one render landed (window.__archhub_render_count ticked).
//
// It also runs:
//   (A) a TIMING comparison: precompiled eval vs the in-browser Babel.transform
//       of the same .jsx (using the vendored babel.min.js, same opts the app
//       uses) — to show the ~10-50ms vs ~1900ms delta.
//   (B) a TDZ POSITIVE CONTROL: eval a snippet with a forward const reference
//       (the white-screen class) and assert the harness CATCHES the throw — so
//       a genuinely-broken compile could not pass silently.
//
// Exit 0 = all proofs pass. Non-zero = a specific proof failed (message says
// which). Prints a machine-readable VERIFY_RESULT {...} line.
//
// Usage: node verify_precompiled.cjs
//   (optional) node verify_precompiled.cjs <compiled.js> <source.jsx>

const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const WEB_UI = path.join(REPO, 'app', 'web_ui');
const VENDOR = path.join(WEB_UI, 'vendor');

const COMPILED = process.argv[2] || path.join(WEB_UI, 'studio-lm.compiled.js');
const SOURCE = process.argv[3] || path.join(WEB_UI, 'studio-lm.jsx');

// jsdom comes from the prior agent's harness dir (already installed there).
let JSDOM;
for (const base of [
  path.join(REPO, '.lagfix_harness', 'node_modules'),
  path.join(REPO, 'node_modules'),
]) {
  try { JSDOM = require(path.join(base, 'jsdom')).JSDOM; break; } catch (e) {}
}
if (!JSDOM) {
  console.error('VERIFY_FAIL: jsdom not found (looked in .lagfix_harness/node_modules + node_modules)');
  process.exit(2);
}

function fail(msg) { console.error('VERIFY_FAIL: ' + msg); process.exit(1); }

// ── Build a jsdom window pre-seeded the way the app/harness expects ──────────
function makeWindow() {
  const dom = new JSDOM(
    '<!doctype html><html><head></head><body><div id="root"></div></body></html>',
    { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://localhost/' }
  );
  const { window } = dom;
  let _rafQ = [];
  window.requestAnimationFrame = (cb) => { _rafQ.push(cb); return _rafQ.length; };
  window.cancelAnimationFrame = () => {};
  window.__flushRaf = function () {
    for (let i = 0; i < 50 && _rafQ.length; i++) {
      const q = _rafQ; _rafQ = [];
      q.forEach((cb) => { try { cb(window.performance.now()); } catch (e) {} });
    }
  };
  window.matchMedia = window.matchMedia || (() => ({
    matches: false, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {},
  }));
  window.ResizeObserver = window.ResizeObserver || class { observe() {} unobserve() {} disconnect() {} };
  window.Element.prototype.getBoundingClientRect = function () {
    return { x: 0, y: 0, top: 0, left: 0, right: 1200, bottom: 760, width: 1200, height: 760, toJSON() {} };
  };
  window.scrollTo = () => {};
  if (!window.performance) window.performance = { now: () => Date.now() };

  // Minimal fake bridge — studio-lm tolerates missing slots/signals, but the
  // mount effects touch a few. Provide no-op signals + slots.
  function makeSignal() {
    const fns = new Set();
    return { connect(f) { fns.add(f); }, disconnect(f) { fns.delete(f); },
             emit() {}, _count() { return fns.size; } };
  }
  const archhub = {};
  for (const s of ['chat_chunk', 'chat_reasoning', 'chat_done', 'chat_error',
    'sessions_changed', 'hosts_changed', 'memory_changed', 'skills_changed',
    'trigger_fired', 'node_created', 'workflow_done', 'param_options_ready']) {
    archhub[s] = makeSignal();
  }
  const slot = () => (...a) => {
    const cb = a[a.length - 1];
    if (typeof cb === 'function') { try { cb('{}'); } catch (e) {} }
  };
  for (const n of ['get_profile', 'save_graph', 'send_chat', 'load_session',
    'get_saved_skills', 'run_workflow', 'run_node', 'get_token_usage',
    'get_brain_stats', 'can_wire', 'would_create_cycle']) {
    archhub[n] = slot();
  }
  window.archhub = archhub;

  // Pre-seed a tiny graph so a real canvas render is exercised on mount.
  window.__archhub_LM_GRAPH = {
    nodes: [{ id: 'ai1', cat: 'ai', x: 120, y: 120, w: 300, h: 180,
      title: 'Conversation', sub: 'auto',
      ins: [{ id: 'ctx', label: 'context', t: 'view' }],
      outs: [{ id: 'intent', label: 'intent', t: 'intent' }],
      messages: [{ me: true, text: 'hi', time: '10:00', ts: '2026-06-01T10:00:00Z' }] }],
    wires: [], groups: [],
  };
  window.__archhub_LM_SESSIONS = [
    { id: 's1', title: 'Test', state: 'idle', host: '', file: '', model: 'auto', when: 'now', last: '' },
  ];
  return window;
}

function loadVendorGlobals(window) {
  const react = fs.readFileSync(path.join(VENDOR, 'react.production.min.js'), 'utf8');
  const reactDom = fs.readFileSync(path.join(VENDOR, 'react-dom.production.min.js'), 'utf8');
  window.eval(react);
  window.eval(reactDom);
  if (typeof window.React === 'undefined' || typeof window.ReactDOM === 'undefined') {
    fail('React/ReactDOM not global after vendor load');
  }
}

// ════════════════════════════════════════════════════════════════════════════
// PROOF 1 — load the PRECOMPILED artifact directly (NO Babel) + mount.
// ════════════════════════════════════════════════════════════════════════════
function proofLoadPrecompiledAndMount() {
  if (!fs.existsSync(COMPILED)) fail('precompiled artifact missing: ' + COMPILED);
  const compiledText = fs.readFileSync(COMPILED, 'utf8');

  // Confirm it carries the build_jsx sha header (so we know we're loading the
  // real artifact, not something else) and that the sha matches the source —
  // i.e. the loader's gate would choose this fast path.
  const m = /ARCHHUB_JSX_SRC_SHA256:\s*([0-9a-f]{64})/.exec(compiledText.slice(0, 4096));
  if (!m) fail('artifact has no ARCHHUB_JSX_SRC_SHA256 header');
  const embeddedSha = m[1];
  const crypto = require('crypto');
  const srcSha = crypto.createHash('sha256')
    .update(fs.readFileSync(SOURCE)).digest('hex');
  const shaMatch = embeddedSha === srcSha;

  const window = makeWindow();
  loadVendorGlobals(window);

  // Eval the compiled artifact AS-IS, as a script (global scope) — exactly the
  // loader's evalGlobal() path. NO Babel touched. A bad compile (e.g. TDZ
  // forward-ref) would throw here, just like the in-browser white-screen.
  const t0 = window.performance.now();
  let threw = null;
  try { window.eval(compiledText); } catch (e) { threw = e; }
  const evalMs = window.performance.now() - t0;
  if (threw) fail('precompiled eval threw (white-screen class): ' + (threw && threw.message || threw));
  if (typeof window.StudioLM !== 'function') fail('window.StudioLM not a function after eval');

  // Mount it.
  const React = window.React, ReactDOM = window.ReactDOM;
  const root = ReactDOM.createRoot(window.document.getElementById('root'));
  let renderThrew = null;
  window.addEventListener('error', (ev) => { renderThrew = ev.error || ev.message; });
  const mt0 = window.performance.now();
  try {
    if (ReactDOM.flushSync) {
      ReactDOM.flushSync(() => { root.render(React.createElement(window.StudioLM)); });
    } else {
      root.render(React.createElement(window.StudioLM));
    }
  } catch (e) { renderThrew = e; }
  window.__flushRaf();
  const mountMs = window.performance.now() - mt0;
  if (renderThrew) fail('mount/render threw: ' + (renderThrew && renderThrew.message || renderThrew));

  const rendered = (window.__archhub_render_count || 0) > 0;
  const html = window.document.getElementById('root').innerHTML || '';
  // A successful mount produces a substantial DOM tree. (render_count only
  // ticks once a NodeCanvas — i.e. an OPEN session — renders; the Home screen
  // mounts plenty of real DOM without it, so DOM size is the mount proof.)
  const producedDom = html.length > 200;
  if (!rendered && !producedDom) {
    fail('StudioLM mounted but produced no render (render_count=0, empty #root)');
  }
  // Guard against a "renders, but it's the ErrorBoundary" false pass: the
  // ErrorBoundary headline is the literal "ArchHub render crash" string.
  if (/ArchHub render crash/.test(html)) {
    fail('StudioLM mounted into the ErrorBoundary (render crash), not the real UI');
  }
  return {
    embeddedSha: embeddedSha.slice(0, 16), srcSha: srcSha.slice(0, 16), shaMatch,
    evalMs: +evalMs.toFixed(1), mountMs: +mountMs.toFixed(1),
    rendered, renderCount: window.__archhub_render_count || 0,
    domBytes: html.length, errorBoundary: /ArchHub render crash/.test(html),
  };
}

// ════════════════════════════════════════════════════════════════════════════
// PROOF 2 — TDZ POSITIVE CONTROL. Prove the eval harness catches the
// white-screen class so a broken compile can't pass silently.
// ════════════════════════════════════════════════════════════════════════════
function proofTdzControl() {
  const window = makeWindow();
  // Forward reference to a `const` before its declaration — the exact TDZ
  // ReferenceError that const-preserving (modern target) output can produce.
  const bad = '(function(){ TDZ_CTRL; const TDZ_CTRL = 1; })();';
  let threw = null;
  try { window.eval(bad); } catch (e) { threw = e; }
  if (!threw) fail('TDZ control did NOT throw — harness cannot catch bad compiles');
  const isTdz = /before initialization|is not defined/i.test(threw.message || '');
  return { caught: true, message: (threw && threw.message || '').slice(0, 80), isTdz };
}

// ════════════════════════════════════════════════════════════════════════════
// PROOF 3 — TIMING. precompiled eval vs in-browser Babel.transform of the SAME
// source, with the SAME vendored babel + opts the app uses. Shows the delta.
// ════════════════════════════════════════════════════════════════════════════
function proofTiming() {
  const compiledText = fs.readFileSync(COMPILED, 'utf8');
  const srcText = fs.readFileSync(SOURCE, 'utf8');

  // Precompiled load path: just eval the artifact (what the fast path does).
  const w1 = makeWindow();
  loadVendorGlobals(w1);
  const p0 = w1.performance.now();
  w1.eval(compiledText);
  const precompiledMs = w1.performance.now() - p0;

  // In-browser fallback path: load babel (3 MB) + transform the .jsx — the
  // ~1.9 s cost the founder measured on every cache-miss boot.
  const w2 = makeWindow();
  loadVendorGlobals(w2);
  const babelSrc = fs.readFileSync(path.join(VENDOR, 'babel.min.js'), 'utf8');
  const bl0 = w2.performance.now();
  w2.eval(babelSrc);
  const babelLoadMs = w2.performance.now() - bl0;
  if (typeof w2.Babel === 'undefined') fail('Babel not global after eval (timing)');
  const bt0 = w2.performance.now();
  // chrome 140 → preserves const, matching QtWebEngine + the on-disk artifact.
  const out = w2.Babel.transform(srcText, {
    presets: [['env', { targets: { chrome: '140' } }], 'react'],
    sourceType: 'script',
  });
  const transformMs = w2.performance.now() - bt0;
  void out;
  // Total in-browser cost on a cache miss = load babel + transform.
  const inBrowserTotalMs = babelLoadMs + transformMs;

  return {
    precompiledMs: +precompiledMs.toFixed(1),
    babelLoadMs: +babelLoadMs.toFixed(1),
    transformMs: +transformMs.toFixed(1),
    inBrowserTotalMs: +inBrowserTotalMs.toFixed(1),
    speedupVsTransform: +(transformMs / Math.max(precompiledMs, 0.01)).toFixed(1),
  };
}

// ════════════════════════════════════════════════════════════════════════════
// PROOF 4 — SHA GATE. The loader chooses the fast path ONLY when the artifact's
// embedded sha matches the live source sha. This reproduces that exact gate and
// proves: (a) matching sha → precompiled chosen; (b) tampered sha → fallback.
// Mirrors jsx-boot.js readEmbeddedSha() + the (embedded === srcSha) check.
// ════════════════════════════════════════════════════════════════════════════
function proofShaGate() {
  const crypto = require('crypto');
  const SHA_HEADER_RE = /ARCHHUB_JSX_SRC_SHA256:\s*([0-9a-f]{64})/;
  function readEmbeddedSha(text) {
    const m = SHA_HEADER_RE.exec(text.slice(0, 4096));
    return m ? m[1] : null;
  }
  // The actual gate: returns true iff the precompiled fast path would be taken.
  function gateChoosesPrecompiled(compiledText, srcText) {
    const srcSha = crypto.createHash('sha256').update(srcText, 'utf8').digest('hex');
    const embedded = readEmbeddedSha(compiledText);
    return !!(embedded && embedded === srcSha);
  }

  const compiledText = fs.readFileSync(COMPILED, 'utf8');
  const srcText = fs.readFileSync(SOURCE, 'utf8');

  // (a) Matching sha → fast path chosen.
  const matchChooses = gateChoosesPrecompiled(compiledText, srcText);
  if (!matchChooses) fail('sha gate did NOT choose precompiled on a matching sha');

  // (b) Tamper the embedded sha → gate must reject → loader falls back to Babel.
  const tampered = compiledText.replace(SHA_HEADER_RE,
    'ARCHHUB_JSX_SRC_SHA256: ' + 'deadbeef'.repeat(8));
  const tamperChooses = gateChoosesPrecompiled(tampered, srcText);
  if (tamperChooses) fail('sha gate STILL chose precompiled after sha tamper (fallback broken)');

  // (c) Tamper the SOURCE (simulating an unbuilt .jsx edit) → gate must reject.
  const editedSrc = srcText + '\n// an edit that has not been recompiled yet\n';
  const editChooses = gateChoosesPrecompiled(compiledText, editedSrc);
  if (editChooses) fail('sha gate chose stale precompiled after a source edit (fallback broken)');

  return { matchChoosesPrecompiled: matchChooses,
           tamperedShaFallsBack: !tamperChooses,
           editedSourceFallsBack: !editChooses };
}

// ── Run all proofs ───────────────────────────────────────────────────────────
const p1 = proofLoadPrecompiledAndMount();
const p2 = proofTdzControl();
const p3 = proofTiming();
const p4 = proofShaGate();

const result = {
  proof1_load_and_mount: p1,
  proof2_tdz_control: p2,
  proof3_timing: p3,
  proof4_sha_gate: p4,
};
console.log('VERIFY_RESULT ' + JSON.stringify(result, null, 2));
console.log('');
console.log('PROOF 1 (load precompiled + mount, NO Babel): ' +
  'sha_match=' + p1.shaMatch + ' rendered=' + p1.rendered +
  ' renderCount=' + p1.renderCount + ' evalMs=' + p1.evalMs + ' mountMs=' + p1.mountMs);
console.log('PROOF 2 (TDZ positive control): harness caught the bad-compile throw' +
  (p2.isTdz ? ' (TDZ ReferenceError)' : ''));
console.log('PROOF 3 (timing): precompiled eval=' + p3.precompiledMs + 'ms' +
  ' vs in-browser babel.transform=' + p3.transformMs + 'ms' +
  ' (+' + p3.babelLoadMs + 'ms to even load babel) — ' +
  p3.speedupVsTransform + 'x faster');
console.log('PROOF 4 (sha gate): match->precompiled=' + p4.matchChoosesPrecompiled +
  ' · tampered-sha->fallback=' + p4.tamperedShaFallsBack +
  ' · edited-source->fallback=' + p4.editedSourceFallsBack);
console.log('');
console.log('ALL PROOFS PASSED');
process.exit(0);
