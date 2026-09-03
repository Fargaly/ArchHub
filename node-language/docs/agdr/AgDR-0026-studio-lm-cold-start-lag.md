---
id: AgDR-0026
timestamp: 2026-05-21T13:00:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — "you should fix this and the lag issue"
trigger: Founder demand 2026-05-21 — app slow + lagging; profile + fix the cold-start path
status: executed
category: architecture
projects: [archhub]
extends:
  - none (perf is cross-cutting, no prior AgDR locks the loader path)
---

# Studio-LM cold-start lag — vendor libs + flip to production React + pre-compile JSX

> Founder pain: "the application is very slow and lagging."
> Root cause (from `app/web_ui/index.html` lines 81-87):
> 1. React 18.3.1 **development** build is fetched from unpkg.com on
>    every launch (~230 KB for react + ~1.1 MB for react-dom; the
>    development builds run 2-3× slower than `.production.min.js`).
> 2. `@babel/standalone` 7.29.0 (~3 MB) is fetched from unpkg.com
>    every launch.
> 3. Babel parses + transpiles the 9 675-line `studio-lm.jsx` on
>    every cold start — 1-3 s on a fast machine, longer on the
>    founder's daily.
> 4. QtWebEngine offline → CDN hangs → app freezes until time-out.
>
> Founder mandate: never block >60 s. The cold-start currently
> blocks indefinitely on CDN-down → unacceptable.

## Constraints

1. **No CDN at runtime.** React + ReactDOM + Babel ship inside the
   ArchHub repo. Zero network calls during boot.
2. **Production React.** `.production.min.js` for both react +
   react-dom — 2-3× faster render + 4× smaller payload.
3. **Babel runtime fallback only.** Pre-compile `studio-lm.jsx` +
   `shared-data.jsx` to plain JS at build time. Babel-standalone
   stays bundled as a fallback for dev iterations + AI-minted
   patches, but is NOT loaded on the hot path.
4. **JSX cache key = source sha256.** Cache hit at
   `%LOCALAPPDATA%\ArchHub\jsx-cache\<hash>.js` skips the Babel
   re-parse on subsequent launches.
5. **No build pipeline regression.** Existing dev loop (edit JSX,
   refresh app) still works — the cache simply misses + falls back
   to Babel on a fresh hash.
6. **Offline-correct.** If network is down on first launch + no
   cache yet, fall back to bundled Babel-standalone + show a
   "transpiling…" splash while parsing.

## Options Considered

### Fork 1 — Library hosting

| Option | Picked | Why |
|---|---|---|
| CDN (today) | no | Network round-trip on every launch; blocks app on offline |
| Vendor inside repo (`app/web_ui/vendor/*.min.js`) | **YES** | Zero network · works offline · founder sees no lag on bad WiFi |
| npm + bundler | no | Adds Node toolchain dep · overkill for 3 files |

### Fork 2 — Build variant

| Option | Picked | Why |
|---|---|---|
| `react.development.js` (today) | no | 2-3× slower render · 230 KB · noisy console warnings |
| **`react.production.min.js`** | **YES** | Production-grade speed · smaller payload · same API |

### Fork 3 — JSX transpilation

| Option | Picked | Why |
|---|---|---|
| Runtime Babel-standalone on every launch (today) | no | 9 675 lines × Babel = 1-3 s every cold start |
| **Pre-compile at first launch + cache by sha256** | **YES** | First launch parses ONCE · subsequent launches load cached `.js` · cache invalidates automatically when source changes |
| Node + Babel-CLI build step | no | Adds Node dep · breaks the "edit + refresh" dev loop |
| Switch to ESBuild / SWC | no | Heavier tooling change · revisit if cache approach doesn't move the needle enough |

## Decision

### Phase 1 (THIS commit) — Vendor + production React

1. Add `app/web_ui/vendor/react.production.min.js` (UMD, 18.3.1).
2. Add `app/web_ui/vendor/react-dom.production.min.js` (UMD, 18.3.1).
3. Add `app/web_ui/vendor/babel.min.js` (Babel-standalone 7.29.0).
4. Rewrite `index.html` `<script>` tags to point at `vendor/*.js`
   instead of `https://unpkg.com/...`.
5. Tests pin: vendored files exist + index.html no longer has
   `unpkg.com` URLs.

Estimated impact: **−1.5 to −3 s cold start** (no CDN round-trip,
production React).

### Phase 2 (next commit) — JSX pre-compile cache

1. New: `app/web_ui/jsx-runtime.js` — boot loader.
   - Computes sha256(studio-lm.jsx + shared-data.jsx).
   - Looks up `%LOCALAPPDATA%\ArchHub\jsx-cache\<hash>.js`.
   - Cache hit → inject `<script>` with the cached JS, skip Babel.
   - Cache miss → run Babel-standalone, write the compiled JS to
     cache, then inject.
2. `index.html` drops the two `<script type="text/babel" src="…">`
   tags and instead boots `jsx-runtime.js`.
3. Tests pin: cache write happens on miss · cache hit skips Babel
   work · sha256 mismatch invalidates.

Estimated impact: **−1 to −3 s on warm boots** (no Babel parse).

### Phase 3 (deferred) — bundle splitting

`studio-lm.jsx` at 9 675 lines is itself the long pole even after
Babel is amortised. Split into logical chunks:
- `studio-canvas.jsx` (NodeCanvas + wires)
- `studio-rails.jsx` (sidebar + ConnectorRail + ParamRail)
- `studio-modals.jsx` (NodeLibrary, GroupDialog, SaveSkillDialog…)
- `studio-host-node-v2.jsx` (HostNodeV2Body family — AgDR-0024)

Mount the canvas first, lazy-mount the rails + modals on first
need. Defer to a later AgDR if Phase 1+2 don't bring the founder
into the green.

## What ships in THIS commit (Phase 1)

- `app/web_ui/vendor/react.production.min.js` (vendored UMD).
- `app/web_ui/vendor/react-dom.production.min.js` (vendored UMD).
- `app/web_ui/vendor/babel.min.js` (vendored Babel-standalone).
- `app/web_ui/index.html` — script src rewrites + brief offline-safe
  fallback note.
- `tests/test_studio_lm_lag_fix.py` — pins all of the above.

## What does NOT ship in THIS commit

- JSX cache (Phase 2 — next AgDR sub-slice).
- Bundle splitting (Phase 3).

## Acceptance

1. `index.html` contains zero `https://unpkg.com/` references.
2. Cold start without network → app still boots fully.
3. CDP `performance.timing.loadEventEnd - navigationStart` ≤ 2 s on
   the founder's box (vs ~5-7 s today).
4. JSX Babel-parse clean. Suite green. Founder confirms.

## Artifacts

- This AgDR.
- Pending: the 3 vendored files + index.html edit + tests.
