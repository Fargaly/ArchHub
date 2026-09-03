# Composer lag — root-cause diagnosis · 2026-05-26

## Executive summary

- **`studio-lm.jsx` is 12,930 lines (~620 KB).** Babel-standalone re-parses the file every cache miss; even on a cache hit the entire monolith is `eval`'d into one global scope, a single `React.createElement` tree, and every re-render walks dozens of cousin components. The on-disk shape — one file, ~120 component-likes, ~1,033 reads of the `LM` Proxy getter, 64 `useEffect`s — is the dominant cost.
- **Boot waterfall is silent-failure-friendly.** `jsx-boot.js:209-214` swallows the *only* explicit error path with `document.body.innerHTML = "ArchHub failed to load JSX: …"`. Two other layers (`evalGlobal` script-tag onerror, `Babel.transform` throws) are caught but report a bare message — no stack, no offending line. Result: a 22k-char DOM with 569-char `innerText` is exactly what a silent-error-during-render produces (`ErrorBoundary` at `app-boot.jsx:27-54` renders, then its own children re-render and one throws again → see Hat 4 below).
- **Five always-on polling intervals + ~6 mount-time bridge calls fan out from first paint.** They are uncoordinated (each component owns its `setInterval`) and each call is a QWebChannel async round-trip. The 4-second `BrainChip` + `BrainSection` pollers alone produce ≥30 round-trips/min before the user clicks anything; `RailMiniMap` polls every 500 ms even with no canvas open.

## Boot path audit

| Phase | File | Lines | What runs |
|-------|------|-------|-----------|
| 1. QApp + theme | `app/main.py` | 276-380 | `QApplication(sys.argv)`, Fusion style, palette, QSS, single-instance lock |
| 2. Core services | `app/main.py` | 390-405 | `ConnectorManager().refresh()` (sync), `ToolEngine`, `LLMRouter`, `connector_health.instance()` |
| 3. WebShell ctor | `app/main.py` | 455-470 | `WebShell(...)` → instantiates `ArchHubBridge` |
| 4. Bridge ctor (deferred boot) | `app/bridge.py` | 472-552 | `_deferred_boot` daemon thread loads custom nodes + 16 connector modules + memory extractors; emits `hosts_changed` |
| 5. Bridge ctor (sync) | `app/bridge.py` | 553-575 | `GraphTriggerScheduler(tick=10s).start()` — runs immediately on main bridge ctor |
| 6. Window show | `app/main.py` | 567-578 | `surface.show_centered()` (QtWebEngineView paints) |
| 7. `index.html` `<script>` order | `app/web_ui/index.html` | 78-133 | qwebchannel.js → inline QWebChannel handshake (sets `window.archhub`) → `react.production.min.js` (124) → `react-dom.production.min.js` (125) → `babel.min.js` (126) → `jsx-boot.js` (133) |
| 8. `jsx-boot.js` | `app/web_ui/jsx-boot.js` | 192-216 | parallel fetch+hash+compile of 3 files, sequential `evalGlobal` into `<script>` blobs |

**Silent failure points in jsx-boot.js:**
- `evalGlobal` (lines 107-122): `s.onerror` resolves to `new Error('script error')` — no stack trace.
- `boot()` catch (lines 209-214): writes `document.body.innerHTML = '<div…>JSX: ' + err.message`. If `err.stack` exists it is dropped.
- `lsSet` (lines 124-140): quota-exceeded silently degrades. A corrupted cached transpile would be `eval`'d as-is on next launch with no integrity check beyond the SHA-256 of *source* (not output).

The implication for the 22k-DOM / 569-text symptom: a render-time exception inside `<StudioLM/>` triggers the `ErrorBoundary` at `app-boot.jsx:23` which renders a small stack-display tree (~600 chars of visible text). The huge `innerHTML` would be the boundary's `<pre>` plus the stale React commit before the throw. Reproduce by checking the QtWebEngine devtools console (`localhost:9223`) for `[archhub] render crash:` from `app-boot.jsx:21`.

## On-mount bridge call inventory

These fire from `useEffect(…, [])` or equivalent at first mount of the StudioLM tree. Each row is one async QWebChannel round-trip.

| # | Component | File:line | Slot | Notes |
|---|-----------|-----------|------|-------|
| 1 | `App` (pullAll) | `app-boot.jsx:69-84` | `get_sessions`, `get_hosts`, `get_models`, `get_memory_stats`, `get_saved_skills`, `get_permissions`, `get_providers`, `list_memory_facts`, `get_connectors`, `get_node_grammar`, `get_custom_nodes` | **11 sequential `await`s** in a single `useEffect`. Worst offender. |
| 2 | `App` signal wiring | `app-boot.jsx:120-134` | `sessions_changed`, `hosts_changed`, `memory_changed`, `skills_changed` | Re-fires the full `pullAll` (11 slots) on any signal |
| 3 | `StudioLM` | `studio-lm.jsx:1053-1062` | `get_profile` | First-run profile gate |
| 4 | `BrainChip` | `studio-lm.jsx:4828-4856` | `get_brain_stats` | Then polls every 4 s |
| 5 | `Home` (sessions) | `studio-lm.jsx:4220-4231` | `get_sessions` | Duplicates `pullAll`'s first call |
| 6 | `BrainSection` | `studio-lm.jsx:12080-12085` | `brain_firm_list`, `brain_seat_list` (via `refresh()`) | Polls every 4 s |
| 7 | `MemoryStripItem` | `studio-lm.jsx:12685-12694` | `memory_stats` | Polls every 30 s |
| 8 | `HealthStripItem` | `studio-lm.jsx:12798-12811` | `graph_validate` | Debounced 800 ms after `lm-graph-bump` |
| 9 | `GraphHealthBadge` | `studio-lm.jsx:6986-7005` | `graph_validate` | Debounced 200 ms after `graphBump` |

Mount-time round-trip count: **≈18** before the user does anything. With the 1.5 s timeout race (`bridgeAsync` at `studio-lm.jsx:318`) any failed slot pins the wait for the full 1.5 s.

## Polling loops

| Line | Component | Interval (ms) | What it calls | Severity |
|------|-----------|---------------|---------------|----------|
| 3749 | `RailMiniMap` | **500** | Local re-render only (reads `window.__archhub_canvas_state`) | High — fires forever even without canvas |
| 4854 | `BrainChip` | 4000 | `b.get_brain_stats(done)` (bridge slot, async) | High — bridge round-trip |
| 7606 | (toast) | 6000 once | `setToast(null)` | Low |
| 10207 | `NodeLibrary` loading | 4000 once | timeout, no slot | Low |
| 12083 | `BrainSection` | **4000** | `brain_firm_list` + `brain_seat_list` round-trips via `refresh()` | High — duplicated by polling AND signal-wire |
| 12643 | `PerfHud` | 1000 | local state only | Medium (only when HUD open) |
| 12692 | `MemoryStripItem` | 30000 | `memory_stats` bridge slot | Low |
| 3989 | search debounce | 200 once | search bridge | Low |
| 6988 | `GraphHealthBadge` | 200 once | `graph_validate` | Re-fires on every `graphBump` |
| 12800 | `HealthStripItem` | 800 once | `graph_validate` | Same; second listener — **duplicate work** |

Plus the always-on `useTypewriter` in `shared-data.jsx:112-118` (per AI message) and `useSelfHealingHosts` 4200 ms `setInterval` (`shared-data.jsx:127`).

## Render-body offenders

**Forced-reflow reads (`getBoundingClientRect` / scroll height) in render bodies, not inside `useEffect`:**

- `studio-lm.jsx:5084` and `5100` — `NodeCanvas` inside `useEffect` (OK).
- `studio-lm.jsx:9827` — `MiniMap` reads `wrapRef.current.getBoundingClientRect()` directly inside the function body (not in `useEffect`). Fires on every render of the minimap.
- `studio-lm.jsx:11499` — `ConversationRail` mutates `scrollRef.current.scrollTop = scrollRef.current.scrollHeight` in a `useEffect` keyed on `node.messages.length` — OK, but reads `scrollHeight` so every new message forces a layout.

Lines 5171, 5216, 5292, 5320, 5364-5378, 5429, 5716, 5731, 6044 are all inside `NodeCanvas` event handlers (mouse-move / context-menu / drag) — acceptable.

**Proxy abuse (LM.* getter reads):**

`LM` (`studio-lm.jsx:77-174`) is a plain object with **23 `get` accessors** for theme colours that re-read `_currentTheme`. Grep across the file counts **1,033 LM.* color reads** (e.g. `LM.bg`, `LM.accent`, `LM.ink`, `LM.line`, `LM.ok`, `LM.warn`, `LM.err`, `LM.cyan`, `LM.purple`, `LM.blue`, `LM.bgPanel`, `LM.bgSoft`, `LM.bgHover`, `LM.bgDeep`, `LM.bgCanvas`, `LM.bgInk`, `LM.inkSoft`, `LM.inkMuted`, `LM.inkDim`, `LM.lineSoft`, `LM.lineHair`, `LM.accentSoft`, `LM.accentDim`, `LM.accentHi`). Each appears in an inline `style={…}` object built fresh per render. With ~120 components and a multi-hundred-node canvas, this is tens of thousands of getter invocations per re-render. Compared to a literal string lookup, getters skip JIT inlining heuristics and add a function-call frame each.

`CAT` (`studio-lm.jsx:177-190`) is computed once at module-load by reading `LM.cyan`/`LM.inkSoft`/etc. — frozen at that moment. So `CAT.host.col` is the color from whatever theme was active at boot, and never updates on theme switch unless `CAT` is rebuilt. Bug, separate from perf.

## Component-size ranking (by line span)

Top 10 by LoC; depth estimated from nested JSX in body.

| # | Component | Start | End | LoC | Notes |
|---|-----------|-------|-----|-----|-------|
| 1 | `NodeCanvas` | 5052 | 6862 | **1810** | Canvas substrate. ~30 `useState`/`useRef`, 15 `getBoundingClientRect` sites. Single biggest re-render target. |
| 2 | `StudioLM` | 1022 | 2279 | **1257** | Root. Owns openId/tabs/picker/settings/library/userNodes/graphBump. |
| 3 | `FloatingComposer` | 9485 | 9816 | 331 | Chat composer with bridge calls. |
| 4 | `ConnectorRail` | 10382 | 10652 | 270 | Right-rail for connector nodes. |
| 5 | `ConversationRail` | 11492 | 11684 | 192 | AI-node chat scrollback + composer. Re-renders on every streaming chunk. |
| 6 | `NodeLibrary` modal | 9915 | 10163 | 248 | Modal — only when open. |
| 7 | `BrainSection` | 12043 | 12263 | 220 | Settings inside-section, polls every 4 s. |
| 8 | `_NodeRenderer_inner` + memo | 7712 | 7963 | 251 | Per-node renderer — already `React.memo`'d (line 7944). |
| 9 | `Settings` | 12264 | 12451 | 187 | Modal — only when open. |
| 10 | `Workspace` | 4575 | 4621 | 46 | Thin wrapper, but unmounts on session change due to grid columns swap. |

JSX-depth-wise `NodeCanvas` is the deep one — it nests the wire SVG, group SVG, per-node `NodeRenderer`s, ctx menus, drag preview, minimap, toast, broken-wire dialog inside one positioned div. Every `bumpGraph` (rAF-coalesced at line 1083) re-renders this whole subtree, and `NodeCanvas`'s `useMemo([userNodes, graphBump])` rebuilds `allNodes` on every bump.

## Recommendations — minimal-intervention fix (no rewrite)

1. **Stop polling slot-bound counters when nothing changed.** `BrainChip` (4 s, line 4854) + `BrainSection` (4 s, line 12083) + `RailMiniMap` (500 ms, line 3749) burn bridge round-trips while idle. Replace with bridge-emitted signals — `brain_changed` exists already on the bridge side (memory_changed signal pattern at `bridge.py:451`); add a `brain_stats_changed` signal and have these chips re-pull only on emit. Saves ≥30 round-trips/min idle.
2. **Coalesce graph_validate.** `GraphHealthBadge` (line 6988) and `HealthStripItem` (line 12800) both call `graph_validate` independently on every `graphBump`. Two listeners doing the same work. Hoist into one Context provider or one window-cached promise.
3. **Memoise inline `style={…}` objects in `NodeCanvas`.** The wire SVG + grid background + minimap viewport rectangle rebuild thousands of `{stroke: LM.line, fill: LM.bg, …}` per render. `React.useMemo([])` on the static ones halves the LM-getter call count.
4. **Surface the silent error.** `jsx-boot.js:213` should `console.error(err)` AND keep the partial `body.innerHTML`. Today the catch overwrites the body, hiding the React render crash if it happened mid-mount. Adding `console.error('[jsx-boot] err', err && err.stack)` is one line.
5. **Fix `CAT`/`WIRE` static capture.** Lines 177-239 read `LM.*` getters at module-eval; if theme changes, these stay stale. Turn `CAT.host.col` into a getter the same way `LM` does, or rebuild on `_currentTheme` change.

## Recommendations — medium-intervention (split-file lazy load)

1. **Split `studio-lm.jsx` into logical chunks.**
   - `studio-lm-core.jsx` — `LM`, `CAT`, `WIRE`, `bridgeAsync`, `StudioLM`, `Workspace`, `Sidebar`, `WsHeader` (~2k lines).
   - `studio-lm-canvas.jsx` — `NodeCanvas`, `NodeRenderer`, all `*Body` components, `MiniMap`, menus (~3.5k lines).
   - `studio-lm-rails.jsx` — `NodeRail`, `ConversationRail`, `ConnectorRail`, `BrainSection`, all `*Section` (~3k lines).
   - `studio-lm-modals.jsx` — `Settings`, `ModelPicker`, `NodeLibrary`, `CreateNodeModal`, `AINodeModal`, `MemoryExplorerModal`, `AiPlanHistoryModal`, `CommandPalette`, `FirstRunProfile`, `SaveSkillDialog`, `GroupDialog`, `WirePromotePalette`, `BrokenWireDialog` (~3k lines).
   - `studio-lm-footer.jsx` — `PerfHud`, `MemoryStripItem`, `ServerStrip`, `HealthStripItem`, `MinimapToggleStripItem`, `GlobalToast` (~1k lines).
2. **Lazy-load modals.** Settings/NodeLibrary/MemoryExplorer/AiPlanHistory/CommandPalette are mounted only when their `*Open` state flips true. Wrap each in a dynamic `Suspense` boundary that fetches the chunk on demand. Cuts Babel cold-transpile time roughly in half because the modal cluster is ~3k lines.
3. **Move the boot-time `pullAll` to streaming.** `app-boot.jsx:67-100` does 11 sequential `await` round-trips. Either fire all 11 in parallel `Promise.all`, or — better — add one `get_initial_state()` slot that returns the whole bag in a single QWebChannel call. Cuts mount latency by ≥10× on this path.

## Recommendations — heavy (replace Babel-standalone with a real bundle)

1. **Vite (esbuild) build → `bundle.js`.** Add a `app/web_ui/build/` step that runs `npm run build` (Vite + React + esbuild) and emits a single pre-transpiled `bundle.js`. `index.html` loads that one file; Babel-standalone and `jsx-boot.js`'s hash/cache/eval gymnastics disappear. Cold-start drops from "Babel parses 620 KB" to "QtWebEngine parses 200 KB compiled JS." Add a watch mode for dev (`npm run dev` → outputs to the same path) so the founder can iterate without changing the launch command.
2. **Splash sequencing the right way.** Once the bundle is pre-built, the splash fader in `app-boot.jsx:151-166` can be removed — `bundle.js` mounts in <100 ms and the splash floor (350 ms) becomes a delay, not a hide-the-lag mechanism.
3. **`window.archhub` typed surface.** Generate a TypeScript `.d.ts` from `bridge.py` slot signatures (script-emitted at build time). `bridgeAsync` becomes type-checked at compile, the 1.5 s timeout race can be tuned per-slot, and the silent-null degradation pattern (`bridgeAsync … return null`) can be replaced with typed Result types so the React tree stops swallowing failures.
4. **Server-driven theme tokens, not getters.** Replace the `LM` Proxy/getter object with a CSS variables system: `:root { --lm-bg: #0e0e11; --lm-accent: #e8743a; … }`. Inline styles become `var(--lm-bg)`, which the browser handles in C++ rather than JS getter call frames. Eliminates the 1,033 getter reads as a class.
5. **Canvas → ReactFlow.** AgDR-0007 already names ReactFlow as the substrate. `NodeCanvas` (1,810 LoC) is its hand-rolled equivalent. ReactFlow's diff is per-node, not per-canvas, and its renderer is `React.memo` + key-stable by design. This is the largest single perf cliff and the existing AgDR sanctions the move.
