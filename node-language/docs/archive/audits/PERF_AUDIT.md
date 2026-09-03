# Performance audit — 2026-05-06

Top-5 bottlenecks ranked by user-perceived impact × ease of fix.
Source: read-only sweep of the desktop-app code by an Explore agent
on 2026-05-06.

---

## 1. LLM tool-use loop cap = 12 iterations

**Where:** `app/llm_router.py` `LLMRouter.complete`, `for _iteration in range(12):`

**What:** Hard cap on tool-use loop iterations. A six-stage skill
(`sketch-to-production`) running ~2 iterations per stage hits the cap
around stage 3–4 and falls out silently with whatever text it has so
far.

**Why slow:** Apparent "stall" forces the user to restart, which
re-runs every prior stage. Each restart = full re-execution + extra
network round-trips. User perceives it as the app dying mid-pipeline.

**Fix:** Raise to 24 (or model-aware: Sonnet/Haiku get 24, Opus gets
32). One line.

**Effort:** S · **Impact:** Highest.

---

## 2. `list_skills()` re-scans filesystem on every call

**Where:** `app/skills/library.py` `list_skills()` lines 75-117.

**What:** Globs three library directories and parses every JSON file
on every call. The chat calls this on every keystroke (matcher), every
sidebar refresh, every welcome-card render.

**Why slow:** 50–200 files × `Workflow.from_json` ≈ 200–500 ms per
call. Multiply by 5–10 calls/min = visible UI lag the user attributes
to "the app is slow".

**Fix:** Wrap with `@functools.lru_cache(maxsize=1)` keyed off a
mtime-summary of the library dirs, OR maintain an in-memory list
invalidated explicitly by `save_skill` / `delete_skill`. Latter is
cleaner.

**Effort:** S · **Impact:** High (every UI surface touching skills
gets faster).

---

## 3. Sequential workflow execution

**Where:** `app/workflows/executor.py` `WorkflowExecutor.run` lines
93-131. Single for-loop walks topo order, runs each node serially.

**What:** Independent branches don't run in parallel. A skill that
fetches reference + fetches style + then merges runs them one after
another even though the first two are independent.

**Why slow:** Sum of all node durations instead of critical-path.
For a 6-stage skill where 2 pairs of stages are independent: ~30%
wall-clock saving.

**Fix:** Worklist-based dispatch with `concurrent.futures.ThreadPoolExecutor(max_workers=3)`.
Track `pending_inputs` per node; when all upstream nodes finish,
push downstream into the ready queue. State mutations need a lock
(per-node-id) to keep `ctx.state` consistent.

**Effort:** M · **Impact:** Medium-high for complex skills.

---

## 4. Connector reachability pings on the chat thread

**Where:** `app/chat_window.py` `_block_if_required_connector_inactive`
calls `_host_reachable` which does a synchronous urllib HTTP GET with
a 1 s timeout, on the UI thread, **for every prompt that mentions
a host keyword**.

**What:** A user typing "dimension all walls" stalls the UI for up
to 1 s while the Revit ping resolves.

**Why slow:** Worst case: 1 s/prompt + extra during typing if the
user invokes pre-flight via slash-command tab-completion (future).
Network blips push toward the timeout.

**Fix:** Cache the reachability result for 30 s, OR move the probe
to a worker thread and treat the prompt as "may still need to gate"
until it returns. Cache is simpler and good enough for the typical
case where the user is asking the same host repeatedly.

**Effort:** M · **Impact:** High (kills perceived UI freezes).

---

## 5. Cloud-sync bootstrap blocks first launch on slow networks

**Where:** `app/main.py` lines 50-57. Spawns a daemon thread that
calls `cloud_sync.bootstrap()` then `pull()`. The thread runs at
launch unconditionally.

**What:** First-time launch on a new device: `git clone` of the
private `<owner>/ArchHub-data` repo + initial pull. 2-5 s on average,
longer on slow networks. The chat window appears, but the Skill
library is empty until the pull finishes.

**Why slow:** A user who launches the app and immediately tries to
run a Skill sees an empty library or a stale local cache. Recovery
requires a manual "Refresh" click.

**Fix:** Defer the entire bootstrap until the user explicitly turns
on cloud sync (or skip if already initialised). Add a 3 s soft
timeout on `pull()`; on timeout, surface a status-bar line
"Cloud sync still catching up…" and let the matcher use whatever
local cache it has. Refresh skill list when pull completes.

**Effort:** M · **Impact:** Medium (first-launch UX, less repeat
pain).

---

## TL;DR — ship first

1. Raise tool-use loop cap from 12 → 24. One line. Eliminates 6-stage
   workflow truncation.
2. Cache `list_skills()` with explicit invalidation on save/delete.
   ~10 lines. Removes 200-500 ms lag on every chat keystroke.
3. Cache or background-thread the reachability probe so the UI never
   stalls 1 s on prompt entry. ~20 lines.

All three together: roughly half a sprint of work, takes the app from
"too slow" to genuinely responsive.
