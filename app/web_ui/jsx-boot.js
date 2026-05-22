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

  async function loadOne(file) {
    const t0 = performance.now();
    const src = await fetchText(file);
    const hash = await sha256(src);
    const cacheKey = 'jsx_cache_v1_' + file.replace(/\W/g, '_') + '_' + hash;
    const cached = lsGet(cacheKey);
    let compiled, fromCache;

    if (cached) {
      compiled = cached;
      fromCache = true;
    } else {
      fromCache = false;
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
    await evalGlobal(compiled, file);
    const dt = Math.round(performance.now() - t0);
    console.log('[jsx-boot] ' + file + ' loaded in ' + dt +
                ' ms · cache=' + (fromCache ? 'HIT' : 'MISS'));
    return { file: file, ms: dt, cacheHit: fromCache };
  }

  async function boot() {
    const t0 = performance.now();
    try {
      const results = [];
      for (const f of FILES) {
        results.push(await loadOne(f));
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
