// AgDR-0026 Phase 3 — JSX boot loader: precompiled-first, Babel-fallback.
//
// THE BOOT-LAG ROOT (founder, 2026-06-01 "FIX THE BOOT LAG ROOT"):
//   Phase 2 hashed studio-lm.jsx (~708 KB) and cached the Babel transpile in
//   localStorage. But EVERY first-boot-after-an-edit still paid a full ~1.9 s
//   in-browser Babel recompile, AND the 3 MB vendored babel.min.js was loaded
//   synchronously on EVERY launch (even cache hits, where it goes unused).
//
//   Phase 3 precompiles the JSX to disk ahead of time (tools/build_jsx.py runs
//   the EXACT same vendored Babel in Node at launch, a fast no-op when nothing
//   changed). This loader now prefers that on-disk artifact:
//
//     FAST PATH (precompiled, ~10-50 ms):
//       fetch studio-lm.jsx  → sha256(src)
//       fetch studio-lm.compiled.js → read its embedded ARCHHUB_JSX_SRC_SHA256
//       if embedded sha === live src sha  → eval the compiled JS directly.
//       NO Babel. NO localStorage. NO 3 MB parse.
//
//     FALLBACK PATH (in-browser Babel, ~1.9 s — only on a precompiled miss):
//       lazily inject vendor/babel.min.js (once), then the Phase-2 path:
//       localStorage cache check → Babel.transform → eval + cache write.
//
//   babel.min.js is NO LONGER in index.html. It loads ONLY when the fallback
//   path actually needs it — so a normal launch never reads/parses 3 MB.
//
// Cache key (fallback only): 'jsx_cache_v1_' + file + '_' + sha256(srcText)
//
// Resilience (unchanged + extended):
//   - precompiled fetch 404 / sha mismatch  → fallback to Babel (never white).
//   - localStorage quota exceeded → clear old entries + retry, then no-cache.
//   - Babel fails to parse → console.error; the boot error panel shows.
//   - Any exception in the fast path → fall through to Babel.

(function () {
  'use strict';

  // ── Dev-mode detection (founder 2026-05-26). In dev mode the precompiled
  //    fast path AND the localStorage read path are bypassed, so an in-flight
  //    .jsx edit is always recompiled fresh. (Writes still occur so the next
  //    non-dev launch warm-starts.) Triggers: ?dev=1, localStorage flag, or a
  //    127.0.0.1/localhost host. ArchHub runs file://, so usually false.
  function detectDevMode() {
    try {
      const href = (typeof location !== 'undefined' && location.href) || '';
      if (href.indexOf('?dev=1') !== -1 || href.indexOf('&dev=1') !== -1) {
        return true;
      }
    } catch (e) {}
    try {
      if (localStorage.getItem('archhub.dev_mode') === 'true') return true;
    } catch (e) {}
    try {
      const h = (typeof location !== 'undefined' && location.hostname) || '';
      if (h === '127.0.0.1' || h === 'localhost') return true;
    } catch (e) {}
    return false;
  }
  const __archhubDevMode = detectDevMode();

  // Settings UI helper: a future toggle can flip dev mode without knowing the
  // key string.
  window.__archhubSetDevMode = function (on) {
    try { localStorage.setItem('archhub.dev_mode', String(!!on)); }
    catch (e) { console.warn('[jsx-boot] could not persist dev_mode:', e); }
  };
  window.__archhubGetDevMode = function () { return !!__archhubDevMode; };

  // Global escape hatch: wipe every jsx_cache_v1_* key. Hookable from a
  // Settings -> Clear cache button.
  window.__archhubClearJsxCache = function () {
    let cleared = 0;
    try {
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.indexOf('jsx_cache_v1_') === 0) keys.push(key);
      }
      keys.forEach(function (key) {
        try { localStorage.removeItem(key); cleared++; } catch (e) {}
      });
    } catch (e) {
      console.warn('[jsx-boot] clear cache failed:', e);
    }
    console.log('[jsx-boot] cleared ' + cleared + ' jsx_cache_v1_* entries');
    return cleared;
  };

  if (__archhubDevMode) {
    console.log('[jsx-boot] dev mode active — precompiled + cache reads bypassed (writes still occur)');
  }

  // SHA-256 via WebCrypto. Returns a lowercase hex string. Async.
  // MUST match tools/build_jsx.py's hashlib.sha256(raw bytes): both files are
  // BOM-free UTF-8, so TextEncoder(text-from-fetch) === the source bytes.
  async function sha256(text) {
    const enc = new TextEncoder();
    const buf = await crypto.subtle.digest('SHA-256', enc.encode(text));
    const arr = new Uint8Array(buf);
    let hex = '';
    for (let i = 0; i < arr.length; i++) {
      hex += arr[i].toString(16).padStart(2, '0');
    }
    return hex;
  }

  async function fetchText(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('fetch ' + url + ' ' + r.status);
    return await r.text();
  }

  // Same marker tools/build_jsx.py writes into the artifact header.
  const SHA_HEADER_RE = /ARCHHUB_JSX_SRC_SHA256:\s*([0-9a-f]{64})/;
  function readEmbeddedSha(compiledText) {
    const m = SHA_HEADER_RE.exec(compiledText.slice(0, 4096));
    return m ? m[1] : null;
  }
  function compiledUrlFor(file) {
    // 'studio-lm.jsx' -> 'studio-lm.compiled.js'
    return file.replace(/\.jsx$/, '.compiled.js');
  }

  function evalGlobal(jsText, sourceUrl) {
    // Inject as a <script> so dev-tools shows a real source file name and the
    // code runs at global scope (matching the prior <script type="text/babel">
    // semantics — top-level const/let land on the same TDZ-bearing scope).
    const blob = new Blob(
      [jsText + (sourceUrl ? '\n//# sourceURL=' + sourceUrl : '')],
      { type: 'application/javascript' });
    return new Promise(function (resolve, reject) {
      const url = URL.createObjectURL(blob);
      const s = document.createElement('script');
      s.src = url;
      s.onload = function () { URL.revokeObjectURL(url); resolve(); };
      s.onerror = function () { URL.revokeObjectURL(url); reject(new Error('script error')); };
      document.head.appendChild(s);
    });
  }

  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) {
    try { localStorage.setItem(k, v); return true; }
    catch (e) {
      // Quota or other error — wipe our cache + retry once.
      try {
        const keys = [];
        for (let i = 0; i < localStorage.length; i++) {
          const key = localStorage.key(i);
          if (key && key.indexOf('jsx_cache_v1_') === 0) keys.push(key);
        }
        keys.forEach(function (key) { try { localStorage.removeItem(key); } catch (e2) {} });
        localStorage.setItem(k, v);
        return true;
      } catch (e3) { return false; }
    }
  }

  // ── Lazy Babel loader — injects vendor/babel.min.js exactly ONCE, only when
  //    a fallback path needs it. Cached promise so concurrent fallbacks share
  //    one 3 MB load. This is the single change that takes 3 MB off every
  //    normal (precompiled-hit) launch.
  let __babelPromise = null;
  function ensureBabel() {
    if (typeof window.Babel !== 'undefined') return Promise.resolve(window.Babel);
    if (__babelPromise) return __babelPromise;
    __babelPromise = new Promise(function (resolve, reject) {
      const t0 = performance.now();
      const s = document.createElement('script');
      s.src = 'vendor/babel.min.js';
      s.onload = function () {
        if (typeof window.Babel === 'undefined') {
          reject(new Error('babel.min.js loaded but window.Babel undefined'));
          return;
        }
        console.log('[jsx-boot] babel.min.js lazily loaded in ' +
                    Math.round(performance.now() - t0) + ' ms (fallback path)');
        resolve(window.Babel);
      };
      s.onerror = function () { reject(new Error('failed to load vendor/babel.min.js')); };
      document.head.appendChild(s);
    });
    return __babelPromise;
  }

  // Order matters — studio-lm.jsx defines the LM_* arrays + StudioLM,
  // app-boot.jsx fills LM_* from the bridge (pullAll) + mounts StudioLM.
  const FILES = ['studio-lm.jsx', 'app-boot.jsx'];

  // ── Fast path: precompiled artifact whose embedded sha matches live source.
  //    Returns the compiled JS string, or null on any miss (caller falls back).
  async function tryPrecompiled(file, srcText) {
    if (__archhubDevMode) return null;  // dev: always recompile fresh
    try {
      const srcSha = await sha256(srcText);
      const compiledText = await fetchText(compiledUrlFor(file));
      const embedded = readEmbeddedSha(compiledText);
      if (embedded && embedded === srcSha) {
        return compiledText;            // HIT — sha gate passed
      }
      // Miss: artifact stale (sha mismatch) — fall back, don't eval stale code.
      return null;
    } catch (e) {
      // 404 (no artifact yet) / fetch error — fall back to Babel.
      return null;
    }
  }

  // ── Fallback path: the Phase-2 in-browser Babel + localStorage cache.
  //    Only reached on a precompiled miss; lazily ensures Babel is loaded.
  async function compileWithBabel(file, srcText) {
    const hash = await sha256(srcText);
    const cacheKey = 'jsx_cache_v1_' + file.replace(/\W/g, '_') + '_' + hash;
    const cached = __archhubDevMode ? null : lsGet(cacheKey);
    if (cached) {
      return { compiled: cached, cacheHit: true };
    }
    if (__archhubDevMode) {
      console.log('[jsx-boot] dev mode — bypassing cache for ' + file);
    }
    const Babel = await ensureBabel();
    const out = Babel.transform(srcText, {
      presets: ['env', 'react'],
      sourceType: 'script',
    });
    const compiled = out.code || '';
    lsSet(cacheKey, compiled);
    return { compiled: compiled, cacheHit: false };
  }

  // Fetch + resolve the compiled JS for one file (no eval here — eval order is
  // sequential, controlled by boot()). Records which path served it.
  async function prepareOne(file) {
    const t0 = performance.now();
    const src = await fetchText(file);

    const pre = await tryPrecompiled(file, src);
    if (pre != null) {
      return {
        file: file, compiled: pre,
        ms: Math.round(performance.now() - t0),
        path: 'precompiled',
      };
    }

    const { compiled, cacheHit } = await compileWithBabel(file, src);
    return {
      file: file, compiled: compiled,
      ms: Math.round(performance.now() - t0),
      path: cacheHit ? 'babel-cache' : 'babel-compile',
    };
  }

  async function loadOne(prepared) {
    await evalGlobal(prepared.compiled, prepared.file);
    console.log('[jsx-boot] ' + prepared.file + ' loaded in ' +
                prepared.ms + ' ms · path=' + prepared.path);
    return { file: prepared.file, ms: prepared.ms, path: prepared.path };
  }

  async function boot() {
    const t0 = performance.now();
    try {
      // Parallel fetch + sha + (precompiled-check | babel-compile), then
      // sequential eval in declaration order. The precompiled fast path adds
      // no Babel and no 3 MB load for either file when artifacts are current.
      const prepared = await Promise.all(FILES.map(prepareOne));
      const results = [];
      for (const p of prepared) {
        results.push(await loadOne(p));
      }
      const usedPrecompiled = results.every(function (r) { return r.path === 'precompiled'; });
      window.__archhub_jsx_boot = {
        total_ms: Math.round(performance.now() - t0),
        results: results,
        precompiled: usedPrecompiled,
        babel_loaded: typeof window.Babel !== 'undefined',
      };
      console.log('[jsx-boot] all JSX loaded in ' +
                  window.__archhub_jsx_boot.total_ms + ' ms · precompiled=' +
                  usedPrecompiled + ' · babelLoaded=' +
                  window.__archhub_jsx_boot.babel_loaded);
    } catch (err) {
      console.error('[jsx-boot] failed:', err);
      document.body.innerHTML =
        '<div style="padding:24px;font-family:monospace;color:#e08">' +
        'ArchHub failed to load JSX: ' + (err && err.message || err) +
        '</div>';
    }
  }

  boot();
})();
