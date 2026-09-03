/* ArchHub web auth client — talks to the EXISTING cloud backend.
 *
 * ONE-SYSTEM: this adds NO new auth. It is a thin browser client over the
 * auth endpoints already live in cloud_backend/main.py:
 *   POST {API}/v1/auth/register   (magic-link, empty PKCE for browser flow)
 *   POST {API}/v1/auth/exchange   (code -> {token, expires_at, plan})
 *   GET  {API}/v1/auth/google/start  (-> {auth_url})
 *   GET  {API}/v1/me              (Bearer -> {email, plan, remaining_messages})
 *
 * The site is static (Astro), so all of this runs client-side. CORS for
 * https://archhub.io is already whitelisted in the backend's CORSMiddleware,
 * so these fetches work from the browser.
 *
 * The session token is stored in localStorage under TOKEN_KEY. It is never
 * logged. No secret is inlined — the Google client_id lives server-side and
 * the public consent URL is handed back by /v1/auth/google/start.
 */
(function (global) {
  'use strict';

  // Live cloud backend (archhub-cloud.fly.dev). Allow an override for local
  // dev via window.ARCHHUB_API before this script loads.
  var API = (global.ARCHHUB_API || 'https://archhub-cloud.fly.dev').replace(/\/+$/, '');
  var TOKEN_KEY = 'archhub_session_token';
  var APP_URL = 'https://github.com/Fargaly/ArchHub/releases/latest';

  function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
  }
  function setToken(t) {
    try { if (t) localStorage.setItem(TOKEN_KEY, t); } catch (e) {}
  }
  function clearToken() {
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
  }
  function isSignedIn() { return !!getToken(); }

  // Pull a one-time code out of whatever the user pasted: a full magic-link
  // URL (…/auth/return?code=XXXX&…), a bare ?code=XXXX query, or the raw code.
  function extractCode(raw) {
    if (!raw) return '';
    var s = String(raw).trim();
    // URL or query-string form
    var m = s.match(/[?&]code=([^&\s]+)/);
    if (m) { try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; } }
    // Otherwise assume the user pasted the bare code itself.
    return s;
  }

  // The WEBSITE's own sign-in return target. We pass our origin's /signin so
  // the cloud /auth/return bounces the one-time code BACK to archhub.io
  // (?code=…), where auth.js auto-finishes it — instead of finishing on the
  // cloud domain. The backend only honours this when `origin` exactly matches
  // its FIXED website-origin allowlist, so it is not an open redirect.
  function websiteReturn() {
    try { return global.location.origin + '/signin'; } catch (e) { return ''; }
  }

  // Step 1 — send the magic-link email. Browser flow: empty PKCE challenge +
  // a WEBSITE redirect, so the backend issues a code AND remembers to bounce
  // the magic-link's /auth/return back to THIS website's /signin (?code=…),
  // which the browser exchanges with an empty verifier.
  function sendMagicLink(email) {
    return fetch(API + '/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, code_challenge: '',
                             redirect: websiteReturn() })
    }).then(function (r) {
      if (r.status === 202 || r.ok) return { ok: true };
      return r.json().catch(function () { return {}; }).then(function (d) {
        return { ok: false, detail: (d && d.detail) || ('HTTP ' + r.status) };
      });
    });
  }

  // Step 2 — exchange the code from the email for a session token.
  function exchangeCode(rawCode) {
    var code = extractCode(rawCode);
    if (!code) return Promise.resolve({ ok: false, detail: 'No code found in what you pasted.' });
    return fetch(API + '/v1/auth/exchange', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code, code_verifier: '' })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.ok && d && d.token) {
          setToken(d.token);
          return { ok: true, plan: d.plan || 'trial' };
        }
        var msg = d && d.detail;
        if (msg && typeof msg === 'object') msg = JSON.stringify(msg);
        return { ok: false, detail: msg || ('HTTP ' + r.status) };
      });
    });
  }

  // Continue with Google — ask the backend for the consent URL, then go there.
  // We thread the WEBSITE return (origin/signin) through the SAME `redirect`
  // the backend packs into its signed Google state, so after consent the
  // google callback -> /auth/return -> 302 back to THIS website's /signin
  // (?code=…) and auth.js finishes there. The backend only honours an
  // allowlisted website origin, so this is not an open redirect.
  // The backend returns 503 {error:"google_login_unconfigured"} until the
  // founder supplies OAuth creds; surface that cleanly instead of a dead button.
  function googleStart() {
    var url = API + '/v1/auth/google/start?redirect='
      + encodeURIComponent(websiteReturn());
    return fetch(url).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.ok && d && d.auth_url) {
          global.location.href = d.auth_url;
          return { ok: true };
        }
        var err = (d && d.detail && d.detail.error) || (d && d.error) || ('HTTP ' + r.status);
        return { ok: false, detail: err };
      });
    });
  }

  // Authenticated account fetch. Returns null (and clears a dead token) on 401.
  function me() {
    var t = getToken();
    if (!t) return Promise.resolve(null);
    return fetch(API + '/v1/me', { headers: { 'Authorization': 'Bearer ' + t } })
      .then(function (r) {
        if (r.status === 401) { clearToken(); return null; }
        if (!r.ok) return null;
        return r.json();
      }).catch(function () { return null; });
  }

  // Best-effort server-side revoke, then drop the local token.
  function signOut() {
    var t = getToken();
    var done = function () { clearToken(); };
    if (!t) { done(); return Promise.resolve(); }
    return fetch(API + '/v1/auth/logout', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
      body: '{}'
    }).catch(function () {}).then(done);
  }

  global.ArchHubAuth = {
    API: API,
    TOKEN_KEY: TOKEN_KEY,
    APP_URL: APP_URL,
    getToken: getToken,
    isSignedIn: isSignedIn,
    sendMagicLink: sendMagicLink,
    exchangeCode: exchangeCode,
    extractCode: extractCode,
    googleStart: googleStart,
    me: me,
    signOut: signOut
  };
})(window);
