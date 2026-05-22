---
id: AgDR-0036
timestamp: 2026-05-22T02:00:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-22 — "for god's sake why is it not stable? do a deeeeeeeep audit and solve this from the fucking roots... I don't want to point this out again"
trigger: AgDR-0035 fixed 2 blocking slots; a deep audit found 5+ MORE blocking the Qt main thread one helper-hop down.  The founder wants the whole CLASS killed + a guard so it can't recur.
status: approved
category: architecture
projects: [archhub]
extends:
  - AgDR-0035 — first 2 non-blocking slot fixes; this AgDR generalises
    the mechanism + closes the whole class + adds the guard
---

# Non-blocking-slot mechanism — kill the UI-freeze class at the root + guard it

## The class

A deep audit (parallel agents over `bridge.py` + 4 brokers + `main.py`
+ `runner.py`) found the founder's recurring instability is ONE class:
a `@pyqtSlot` doing blocking I/O on the Qt main thread.  AgDR-0035's
detector caught only the 2 slots that blocked DIRECTLY
(`detect_all_*`).  Five more block one or two helper-hops down, so
they looked clean:

| Slot | Hidden blocking call | Measured |
|---|---|---|
| `probe_connector` | `c.probe()` → broker `/ping` + 16-port scan / COM | 1-6 s **per host pill** |
| `list_host_sessions` | `_impl` → broker probes + port scan + COM MAPI walk | multi-second per dropdown |
| `list_host_documents` | `_impl` → `broker.forward('/list_docs')` (2 s HTTP) | up to 2 s |
| `get_memory_stats` / `list_memory_facts` | `cloud_client._request` (cloud HTTP) | full HTTP timeout |
| `get_storage_stats` | recursive `glob('**/*')` + per-file `stat()` | seconds on a big account |
| `_startup_self_test` (boot) | broker probes + COM + fs walks, inline before first paint | seconds of boot-splash hang |

Each freezes the ENTIRE ArchHub UI for its full duration — no
keystrokes, no drag, no right-click, no repaint.  That is exactly
what the founder felt as "lag", "typing lags the PC", "no drag-drop",
"slow to restore from minimize".

## Decision — the MECHANISM

One generic helper, `ArchHubBridge._cached_async(key, work, *, ttl,
empty, signal_name)`:

- The slot returns a **cached value instantly** — it never calls the
  slow `work` callable inline.
- `work` is a zero-arg callable doing the slow I/O.  It runs on a
  **bounded `ThreadPoolExecutor`** (`max_workers=6`) — never the Qt
  main thread, and capped so rapid UI actions can't exhaust OS
  threads.
- When `work` finishes the cache updates and `signal_name` fires
  (`hosts_changed` / `memory_changed`) so the JS side re-pulls.
- **Thread-safe**: the cache dict + the busy check-then-set are
  guarded by one `threading.Lock` — fixes the unlocked-cache race
  AgDR-0035 introduced.
- Per-key cache — `probe:revit`, `probe:autocad`, `hsess:revit` …
  each isolated, 30 s TTL.

Every blocking slot in the table above is rewritten to one-line
through `_cached_async`.  `_startup_self_test` moves onto a daemon
thread (it only writes `boot.log`; nothing in the UI depends on it).

## Decision — the GUARD (so it never recurs)

The founder: *"I don't want to point this out again."*  A fix
without a guard is not a root fix.

1. `maintenance_audit.py`'s `blocking-in-pyqtslot` detector is
   upgraded to catch the helper-hop patterns — `.forward(`,
   `.probe()`, `_request(`, `detect_all_*`, `list_sessions(`,
   `com_thread(`, recursive `glob('**`).  It treats `_cached_async` /
   `_async_state` / `.submit(` / `Thread(` / `singleShot` as the
   off-thread markers that clear a slot.
2. `tests/test_no_blocking_slots.py` runs that detector over
   `bridge.py` on every test run / CI.  It **FAILS** if any
   `@pyqtSlot` blocks — except a 2-entry documented allowlist
   (`export_all`, `clear_model_cache` — explicit Settings-button
   actions where a brief stall is expected UX, roadmapped for async
   conversion).
3. The daily-audit bot (AgDR-0034) runs the same detector.

Add a blocking slot → the guard test goes red.  The class cannot
silently come back.

## Consequences

- Host pills, host dropdowns, the memory panel, the storage badge,
  and boot never freeze the UI again.
- Pills / lists may show ≤30 s stale data; the background refresh +
  signal closes the gap within ~3 s of first paint.
- `export_all` / `clear_model_cache` still stall briefly on an
  explicit click — allowlisted + roadmapped.
- The leak-class findings (GraphTrigger double-start, uncapped raw
  `Thread` spawns, runner cache growth, DevTools view leak) are
  separate — appended to `docs/ROADMAP.md`, flagged by the audit bot.

## Acceptance

1. CDP timing: `probe_connector`, `list_host_sessions`,
   `list_host_documents`, `get_memory_stats`, `get_storage_stats`
   all return < 50 ms.
2. `test_no_blocking_slots.py` green — no un-allowlisted blocking slot.
3. Boot splash no longer hangs on the self-test.
4. Suite green.  CDP-verified live.

## Artifacts

- This AgDR.
- `app/bridge.py` — `_async_state` + rewritten `_cached_async` +
  6 slots routed through it.
- `app/main.py` — `_startup_self_test` on a daemon thread.
- `scripts/maintenance_audit.py` — upgraded detector.
- `tests/test_no_blocking_slots.py` (guard) + `test_bridge_nonblocking.py`.
- `docs/ROADMAP.md` — leak-class follow-ups.
