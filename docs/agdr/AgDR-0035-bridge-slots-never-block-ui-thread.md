---
id: AgDR-0035
timestamp: 2026-05-22T00:00:00Z
agent: claude-code (Sonnet)
session: founder gripe 2026-05-21 — "THE LAGGING STILL PERSISTS... WRITING IN THE COMPOSER LAGS THE ENTIRE PC... WHY IS THAT?"
trigger: CDP CPU profile proved the renderer is 99% IDLE during the lag — the freeze is the Qt main thread blocked by synchronous bridge slots, not JavaScript.
status: executed
category: architecture
projects: [archhub]
extends:
  - CLAUDE.md "Hard-won root causes" — "Slow work in a @pyqtSlot must
    run on a background thread"
---

# Bridge slots must never block the Qt main thread

## The smoking gun

Founder: typing in the composer lags the WHOLE PC; slow to restore
from minimize; right-click laggy; node drag-drop doesn't work.

A CDP CPU profile of the QtWebEngine renderer during composer typing
came back **99.3% idle** — zero JavaScript hot path.  The page is
light (339 DOM nodes, 4 ms for 20 forced repaints, no backdrop-filter
/ blur).  The renderer was idle because it was **waiting on a frozen
Qt main thread**.

Timing every bridge slot from CDP found it:

```
   67 ms  get_models
 3678 ms  get_all_hosts      <<< BLOCKS THE QT MAIN THREAD
 2194 ms  get_local_llms     <<< BLOCKS THE QT MAIN THREAD
    4 ms  get_hosts
    8 ms  get_sessions
   (every other slot < 10 ms)
```

`get_all_hosts` runs `host_detector.detect_all_hosts()` — filesystem
walks + a `tasklist` subprocess + port probes.  `get_local_llms`
runs `local_llm_detector.detect_all_local_llms()` — Ollama + LM Studio
HTTP probes.  Both are `@pyqtSlot`s that ran SYNCHRONOUSLY on the Qt
main thread.

While a slot runs, QtWebEngine cannot pump input events or repaint.
A 3.7 s slot = a 3.7 s total freeze of ArchHub: no keystrokes, no
drag events (so drag-drop silently "doesn't work"), no context menu
(right-click "laggy"), no repaint (restore-from-minimize stalls).
The host-pill row + settings call these slots on mount and on the
`hosts_changed` signal, so the freeze recurs.

This is the exact failure CLAUDE.md's "Hard-won root causes" already
names: *"Slow work in a @pyqtSlot must run on a background thread."*
`get_all_hosts` / `get_local_llms` were the two that slipped the net.

## Decision

A reusable `_cached_async(cache_key, fn_name, module_name, ttl)`
helper on the bridge:

- The slot returns the **cached** detector result **instantly** —
  it never calls the slow detector inline.
- If the cache is stale / empty, it starts ONE background thread
  that runs the detector, updates the cache, and emits
  `hosts_changed` so the JS side re-pulls the now-fresh data.
- A `*_busy` flag guards against spawning duplicate refreshers.
- TTL 30 s — detection is at most twice a minute even under a
  signal storm.
- Empty fallback matches the detector's real shape (both return
  `dict`) so the JS side never sees a list-vs-dict flip on the
  first (pre-warm) call.

`get_all_hosts` and `get_local_llms` are rewritten to one-line
through `_cached_async`.  Worst case is now a sub-millisecond slot
return; the slow work is fully off the Qt main thread.

## Consequences

- ArchHub UI never freezes on host / local-LLM detection.
- Typing, drag-drop, right-click, minimize-restore all stay
  responsive — they were starved of main-thread time, not broken.
- Host pills may show stale-by-≤30 s status; acceptable — the
  background refresh + `hosts_changed` re-pull closes the gap in
  ~3 s after first paint.

## Still deferred (tracked, ROADMAP + daily-audit bot)

`probe_connector` (per-host COM/HTTP probe) and
`list_host_sessions` / `list_host_documents` also run blocking work
in their slots.  They are shorter per call (one host) but the same
CLASS.  The `maintenance_audit.py` `blocking-in-pyqtslot` detector
flags them; they get the same `_cached_async` (per-host-keyed)
treatment in a follow-up.  This AgDR fixes the two multi-second
offenders that caused the founder-visible whole-PC freeze.

## Acceptance

1. CDP timing: `get_all_hosts` and `get_local_llms` both return in
   < 50 ms.
2. ArchHub stays interactive (typing, drag, right-click) with no
   multi-second freeze.
3. Host pills still populate (via the background refresh +
   `hosts_changed`).
4. Suite green.  CDP-verified live.

## Artifacts

- This AgDR.
- `app/bridge.py` — `_cached_async` helper + `get_all_hosts` /
  `get_local_llms` rewrite.
- `tests/test_bridge_nonblocking.py`.
