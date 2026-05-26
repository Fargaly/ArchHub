// AgDR-0026 Phase 2 — JSX boot loader with localStorage cache.
//
// Cold-start was 17 s because Babel-standalone re-parsed the
// 9 675-line studio-lm.jsx on every launch.  This loader hashes
// the JSX source, checks localStorage for a cached transpile, and
// only invokes Babel on a cache miss.  Subsequent launches skip
// Babel entirely.
//
// Cache key: 'jsx_cache_v1_' + sha256(srcText)
// Cache hit: eval transpiled JS directly.
// Cache miss: fall back to Babel.transform + write cache back.
//
// Resilience:
//   - localStorage quota exceeded → clear old entries + retry once,
//     then degrade silently to no caching.
//   - Babel fails to parse → console.error + skip; React mount runs
//     in a degraded state (the inline boot script in index.html will
//     show ErrorBoundary).
//   - Any exception in the cache path → fall through to Babel.

(function () {
  'use strict';

  // Dev-mode detection (founder 2026-05-26 — after the
  // brainsection-cache-prototype-perf-triple-failure: launching
  // ArchHub appeared to load a stale JSX bundle because the running
  // process had pinned the prior transpile in memory before the file
  // edit landed. The hash-keyed cache should miss correctly on new
  // hashes, but the founder must NEVER have to clear localStorage
  // manually. Dev mode bypasses the read path entirely while still
  // writing the new transpile back so the next non-dev launch
  // warm-starts.
  //
  // Triggers (any one is sufficient):
  //   1) URL contains ?dev=1
  //   2) localStorage['archhub.dev_mode'] === 'true'
  //   3) hostname is 127.0.0.1 / localhost (ArchHub runs file:// so
  //      this is usually false — present for browser-served dev).
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

  // Settings UI helper: future toggle in Settings dialog can call this
  // without remembering the key string.
  window.__archhubSetDevMode = function (on) {
    try { localStorage.setItem('archhub.dev_mode', String(!!on)); }
    catch (e) { console.warn('[jsx-boot] could not persist dev_mode:', e); }
  };
  window.__archhubGetDevMode = function () { return !!__archhubDevMode; };

  // Global escape hatch: wipe every jsx_cache_v1_* key. Hookable from
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
    console.log('[jsx-boot] dev mode active — cache reads bypassed (writes still occur)');
  }

  // SHA-256 via WebCrypto.  Returns a hex string.  Async.
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

  function evalGlobal(jsText, sourceUrl) {
    // Inject as a <script> so the browser dev-tools shows a real
    // source file name + the code runs at global scope (matching the
    // previous `<script type="text/babel">` semantics).
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

  // Order matters — shared-data.jsx defines LM_*, studio-lm.jsx
  // consumes them + defines StudioLM, app-boot.jsx mounts it.
  const FILES = ['shared-data.jsx', 'studio-lm.jsx', 'app-boot.jsx'];

  // PERF FIX (founder 2026-05-25 — "fix the fucking lag problem"):
  // Hat 3 audit Fix #6 — fetch + sha256 + cache-check were serialized
  // across files. They have no inter-dep; only eval order is
  // sequential. Now: fetch+hash+compile run in parallel via Promise.all,
  // then eval in declaration order. Saves 50-150ms on cold start.

  async function fetchHashCompile(file) {
    const t0 = performance.now();
    const src = await fetchText(file);
    const hash = await sha256(src);
    const cacheKey = 'jsx_cache_v1_' + file.replace(/\W/g, '_') + '_' + hash;
    // Dev mode: skip the read path entirely, but still write back so
    // the next non-dev launch warm-starts.
    const cached = __archhubDevMode ? null : lsGet(cacheKey);
    let compiled, fromCache;
    if (cached) {
      compiled = cached;
      fromCache = true;
    } else {
      fromCache = false;
      if (__archhubDevMode) {
        console.log('[jsx-boot] dev mode — bypassing cache for ' + file);
      }
      if (typeof window.Babel === 'undefined') {
        throw new Error('Babel-standalone not loaded');
      }
      const out = window.Babel.transform(src, {
        presets: ['env', 'react'],
        sourceType: 'script',
      });
      compiled = out.code || '';
      lsSet(cacheKey, compiled);
    }
    const dt = Math.round(performance.now() - t0);
    return { file: file, compiled: compiled, ms: dt, cacheHit: fromCache };
  }

  async function loadOne(prepared) {
    // Eval phase only — fetch/compile already done by fetchHashCompile.
    await evalGlobal(prepared.compiled, prepared.file);
    console.log('[jsx-boot] ' + prepared.file + ' loaded in ' +
                prepared.ms + ' ms · cache=' +
                (prepared.cacheHit ? 'HIT' : 'MISS'));
    return { file: prepared.file, ms: prepared.ms, cacheHit: prepared.cacheHit };
  }

  async function boot() {
    const t0 = performance.now();
    try {
      // PERF: parallel fetch + hash + compile, then sequential eval.
      const prepared = await Promise.all(FILES.map(fetchHashCompile));
      const results = [];
      for (const p of prepared) {
        results.push(await loadOne(p));
      }
      window.__archhub_jsx_boot = {
        total_ms: Math.round(performance.now() - t0),
        results: results,
      };
      console.log('[jsx-boot] all JSX loaded in ' +
                  window.__archhub_jsx_boot.total_ms + ' ms');
      // Signal the inline boot script that JSX is ready.
      window.dispatchEvent(new Event('archhub-jsx-ready'));
    } catch (err) {
      console.error('[jsx-boot] failed:', err);
      document.body.innerHTML =
        '<div style="padding:24px;font-family:monospace;color:#e08">' +
        'ArchHub failed to load JSX: ' + (err && err.message || err) +
        '</div>';
    }
  }

  // The inline `<script type="text/babel" data-presets="env,react">`
  // tag in index.html holds the React mount + ErrorBoundary.  We need
  // to BLOCK that until JSX is loaded — but the inline tag runs as
  // soon as Babel processes it.  Solution: the inline tag was
  // changed to listen for `archhub-jsx-ready` before mounting.
  boot();
})();
