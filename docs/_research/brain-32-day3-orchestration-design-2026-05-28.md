> Design reference — not the roadmap. See docs/ROADMAP.md.

# Brain #32 · Day-3 orchestration design — export→archive worker + contributor gate

**Date**: 2026-05-28
**Track**: Brain #32 (dataset export → cloud archive)
**Status**: DESIGN ONLY — no worker code written. Pending founder review of the 4 open decisions below.
**Depends on (already shipped this track)**:
- `dataset_export.export_fragments(...)` → MCP tool `brain.dataset_export` (server.py ~979)
- `cloud_archive.upload_dataset(...)` → MCP tool `brain.cloud_archive` (server.py, registered day-2 gap-close 2026-05-28)
- `secret_resolver.resolve_secret(...)` — `op://` refs resolve via 1Password CLI → Credential Manager → `OP_*` env

---

## 1. Goal

Two distinct flows. They share the export→upload mechanics but differ entirely in privacy posture and gating.

### Flow A — user's-own-bucket backup (day-3 ships this)
Chain `export_fragments` → `upload_dataset` automatically, on a schedule and on-demand, so a
user's brain dataset backs up to **THEIR OWN** S3-compatible bucket (R2 / AWS / Hetzner / MinIO).
The data never touches an ArchHub-controlled endpoint; the bucket + creds are the user's. This is a
backup/portability feature, not a sharing feature — default scope stays USER-only (the privacy
default `export_fragments` already enforces).

### Flow B — collective contributor opt-in (BLOCKED — design names it, does NOT ship it)
A SEPARATE, explicit CONTRIBUTOR opt-in path that contributes a **privacy-filtered subset** to the
collective training corpus (Brain #33 north star). This is gated on the Q10 privacy layer
(DP noise + the 4-scope visibility model), which is **research-only so far** (task #30 completed as
research; no runtime). Until Q10 lands, Flow B is BLOCKED. Day-3 ships Flow A only.

The two MUST stay visibly separate in the UI and config so a user can never accidentally turn a
private backup into a public contribution.

---

## 2. Worker model — mirror the EXISTING idiom (no APScheduler)

The codebase already has two background-worker exemplars. The orchestrator copies them 1:1. **No new
scheduler dependency** (no APScheduler, no Celery) — that would violate the LIBRARY-FIRST / minimal-dep
posture and diverge from the proven pattern.

### Cited exemplar 1 — `publish_worker.PublishWorker` (`personal-brain-mcp/src/personal_brain/publish_worker.py`)
- `interval_s: float = 6 * 3600.0` constructor arg, floored: `self.interval_s = max(60.0, interval_s)` (line 133).
- `self._stop_event = threading.Event()` (line 136); `self._thread: Optional[threading.Thread]` (137); `self._lock` (138).
- `start()` (150) guards against double-start, clears the event, spawns `threading.Thread(target=self._loop, name=..., daemon=True)`.
- `stop(timeout_s=5.0)` (159) sets the event + joins.
- `_loop()` (164): initial `_stop_event.wait(timeout=5.0)` warm-up, then `while not self._stop_event.is_set():` calls `tick()` inside try/except, then an **interruptible sleep** — `while slept < self.interval_s and not self._stop_event.is_set(): time.sleep(min(1.0, ...)); slept += 1.0` (1-second granularity so `stop()` is responsive).
- `tick()` (180) does exactly one cycle under `self._lock`, returns a `@dataclass` result, persists status via `store.set_meta(...)`.
- `status()` (235) returns `{running, interval_s, cycle_count, last_result, ...}`.

### Cited exemplar 2 — `community.CommunityPoller` (`personal-brain-mcp/src/personal_brain/community.py:274`)
- Identical shape: `interval_s` floored at `max(30.0, ...)` (287), `_stop_event` (289), daemon `_thread` (302–303), `_loop` with the same interruptible-sleep loop (312–321), `tick()` (323), `status()` (341).
- **Lazy-singleton wiring** in `server.py:1127–1154`: `_COMMUNITY_POLLERS: dict[int, Any]` keyed by `id(store)`; `_get_or_create_community_poller(store)` builds-on-first-use so the daemon pays no cost until someone hits `brain.community_poll_now`. The on-demand MCP tool `brain.community_poll_now` (server.py:838) calls `poller.tick()` directly.

### Proposed `ArchiveWorker` (NOT WRITTEN — shape only)
```
class ArchiveWorker:                       # mirrors PublishWorker exactly
    def __init__(self, store, *, interval_s=24*3600.0, archive_config): ...
        self.interval_s = max(60.0, interval_s)   # floor like the exemplars
        self._stop_event = threading.Event()
        self._thread = None; self._lock = threading.Lock()
    def start(self): ...      # daemon thread, name="brain-archive-worker"
    def stop(self, timeout_s=5.0): ...
    def _loop(self): ...      # warm-up wait, then tick + interruptible sleep
    def tick(self) -> ArchiveCycleResult:
        # 1. export_fragments(store, tmp_out, scope_filter=[USER], ...)
        # 2. upload_dataset(tmp_out/<name>, bucket=cfg.bucket,
        #       access_key_ref=cfg.access_key_ref, ...)   # op:// refs
        # 3. persist last-result + last-ts via store.set_meta(...)
    def status(self) -> dict: ...
```
On-demand surface mirrors `brain.community_poll_now`: a new MCP tool `brain.archive_now` calls
`ArchiveWorker.tick()` once. Scheduled surface: lazy-singleton `_get_or_create_archive_worker(store)`
keyed by `id(store)`, `.start()`-ed when the user has enabled scheduled backup (see decision 2).

---

## 3. Open design decisions — NEED FOUNDER INPUT (not decided here)

These are genuine forks (UX direction / privacy authority), so per NEVER-ASK-PICK-ONE they are
surfaced for the founder's eye rather than decided silently.

1. **Default cadence.** Daily? On app close? Manual-only first? — Recommendation to discuss: ship
   **manual-only first** (`brain.archive_now` + a Brain-tab button), add scheduled cadence once the
   manual path is verified live. Founder picks the first-ship cadence.

2. **CONTRIBUTOR opt-in — where the flag lives + its default.** Candidates: app Settings, per-firm
   config, or brain config (`store.set_meta` / a11y-prefs-style per-user key). **Default MUST be OFF.**
   This governs Flow B only; Flow A (own-bucket backup) is also opt-in but is a separate toggle.
   Founder decides the home for the flag.

3. **Collective contribution requires the Q10 privacy layer (DP noise + 4-scope), which is NOT built.**
   Therefore collective contribution (Flow B) is **BLOCKED** until Q10 lands. Day-3 ships **only the
   user's-own-bucket backup path (Flow A)**. No code path may upload to a shared/collective endpoint
   until Q10's DP + scope filter is a runtime, not research.

4. **Secret storage for the bucket creds.** Use `op://vault/item/field` references resolved at call
   time by the new `secret_resolver` (1Password CLI → Windows Credential Manager → `OP_*` env). The
   bucket access/secret keys are **never** stored plaintext in brain memory or config — only the
   reference travels. (This follows the existing `cloud_archive` credential contract; confirming, not
   re-deciding.)

---

## 4. Cross-mandate check (CONSOLIDATE-WITH-ALL-MANDATES)

- **DEFINITION-OF-SHIPPED**: an `ArchiveWorker` thread + a `brain.archive_now` tool are *runtime*, but
  NOT "shipped" until there is a **UI affordance** (a Brain-tab "Back up my brain" button → bridge →
  tool) a user finds in ≤60s. Day-3 worker+tool = "runtime pending UI"; the UI affordance is the
  gating deliverable before the word "shipped" is allowed.
- **ANTI-LIE**: this doc claims nothing built. The worker is explicitly NOT written. No BANNED word
  ("shipped/done/wired") is used for day-3 code that doesn't exist yet.
- **BRAIN-FIRST**: backup operates on the brain store; creds are op:// references, never resolved in
  memory — consistent with the mandate's "secrets — references only."
- **Privacy gate (Q10)**: Flow B blocked until DP+4-scope is a runtime. Flow A stays USER-scope
  (the `export_fragments` privacy default), so no scope escalation happens without explicit opt-in.
- **ENGINEERING (root, not patch)**: reuses the proven worker mechanism rather than inventing a new
  scheduler — the whole class of "background cadence" already has one correct implementation.
- **NEVER-ASK-PICK-ONE**: §3 surfaces genuine forks (cadence, flag home, privacy authority) — these
  are UX/authority judgement calls, not a "do task A or B" menu.
- **AGDR**: if the founder locks the worker's interface/config shape, that lock is architecture-shaped
  and gets an AgDR BEFORE the worker code — per AGDR + NO-NEW-AGDR-UNTIL-LAST-ONE-LIVES (the prior
  day-2 tool surface is live + tested, so a new AgDR is unblocked once this design is reviewed).

---

## 5. Proposed slice order (day-3 .. day-5)

- **Day-3 (Flow A, own-bucket backup):**
  - `ArchiveWorker` (export→upload chain) modelled on `PublishWorker`.
  - `brain.archive_now` MCP tool (on-demand `tick()`), mirroring `brain.community_poll_now`.
  - Brain-tab UI affordance: "Back up my brain to my cloud" + bucket/endpoint/op-ref config form →
    bridge → tool. **This is the deliverable that lets day-3 be called "shipped."**
  - Verify live (CDP screenshot of the button + an observed `ok:True` result on a MinIO/local target).
- **Day-4:** scheduled cadence (founder-chosen interval), lazy-singleton `_get_or_create_archive_worker`,
  `.start()` on enable; status surface in the Brain tab. CONTRIBUTOR opt-in flag added (default OFF),
  wired but Flow B still blocked.
- **Day-5 (blocked on Q10):** Flow B collective contribution — only after the Q10 DP+4-scope privacy
  layer is a runtime. Until then this slice stays `- [ ]` and does NOT ship.

---

## 6. Status note

The orchestrator worker code (`ArchiveWorker`, `brain.archive_now`, the Brain-tab affordance) is
**NOT written yet** — it is pending review of this design and founder input on the 4 decisions in §3.
Day-2's `upload_dataset` is now reachable via `brain.cloud_archive` (gap closed 2026-05-28), which is
the primitive this orchestration will chain. Nothing here is claimed shipped.
