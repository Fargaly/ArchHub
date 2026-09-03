# Delta — current → target

**Inputs:** `.telemetry/product.md` + `.telemetry/current-state.yaml` + `.telemetry/tracking-plan.yaml`.

**Headline:** 5 events live today, 45 events in the target plan. Every existing event gets renamed (`object.action` convention) and four of the five get shape changes. The JSX surface, the landing site, and the cloud backend all gain instrumentation that does not exist today. Identity management gets `identify` + `group` + `alias` + `reset` wired for the first time.

---

## Numbers

| Bucket  | Count | Notes                                                                    |
|---------|-------|--------------------------------------------------------------------------|
| **ADD** | 40    | Net-new events not tracked today                                         |
| **RENAME** | 5  | All 5 existing events change name (`object.action_snake_case` convention) |
| **KEEP** | 0    | No event survives unchanged                                              |
| **REMOVE** | 0  | Nothing in the current state is noise — there is just less of it than needed |
| **CHANGE (shape)** | 4 of the 5 RENAMEs | property shape changes on `app.launched`, `provider.blocked`, `skill.run`, `feedback.submitted` |
| **Target total** | 45 | ADD (40) + RENAME (5) + KEEP (0) = 45 ✓ |

---

## Rename + change (the 5 existing events)

| Current name           | Target name                    | Shape change                                                                                                                                  |
|------------------------|--------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `app_started`          | `app.launched`                 | Keep `silent`. Add `is_first_launch`, `app_version`, `os`, `os_version`, `python_version`, `install_age_days`, `launch_reason`.                |
| `provider_blocked`     | `provider.blocked`             | **DROP** free-form `reason[:120]` (PII surface). Add bounded `reason_class` enum + `cooldown_seconds`.                                       |
| `telemetry_opted_in`   | `telemetry.opted_in`           | No shape change. `source` stays — extended enum (`first_run_dialog | settings_dialog | privacy_panel`).                                       |
| `skill_run`            | `skill.run`                    | Rename `error_kind` → `error_class` (categorical, never raw message). Add `invoked_via` enum.                                                  |
| `user_feedback`        | `feedback.submitted`           | **DROP** the raw `comment` string (free-form text). Replace with `has_comment` bool + `comment_length_bucket` enum. Keep `direction`, `message_id`, `skill_id`. |

---

## Add — net-new events (40)

Grouped by category and rollout priority. Priority lens: P0 = blocks any meaningful analysis (identity + activation funnel + reliability), P1 = required for the v1.0 launch dashboard, P2 = nice-to-have on top.

### Lifecycle (8 add — desktop + cloud + landing)

| Event                       | Priority | Why                                                                                                |
|-----------------------------|----------|----------------------------------------------------------------------------------------------------|
| `app.shutdown`              | P1       | Pairs with `app.launched` for session-duration; flushes pending events via atexit.                 |
| `user.signed_up`            | **P0**   | Cloud-side signup is the conversion endpoint of the entire landing funnel.                         |
| `user.signed_in`            | **P0**   | Triggers `posthog.identify(user_id)` — the install-UUID → user_id alias step that is missing today. |
| `activation.first_skill_run`| **P0**   | The activation metric. Single-shot per user_id, drives the activation funnel.                       |
| `update.applied`            | P2       | Rollout cohort visibility — answers "what version are users actually on?"                          |
| `landing.signup_started`    | **P0**   | Joins to `user.signed_up` for landing → signup conversion.                                         |
| `landing.waitlist_joined`   | P1       | Studio + Enterprise demand signal.                                                                  |
| (Note: `telemetry.opted_in` is RENAME, not ADD.)                                                                                                       |

### Core value (15 add — canvas, composer, run, skill, host, vision, marketplace)

| Event                          | Priority | Why                                                                                              |
|--------------------------------|----------|--------------------------------------------------------------------------------------------------|
| `node.placed`                  | **P0**   | The category-adoption signal across the 12-category palette. JSX-side, doesn't exist today.       |
| `workflow.run_started`         | **P0**   | Open the run window. Joins downstream `run_completed` / `run_failed` via `workflow_run_id`.       |
| `workflow.run_completed`       | **P0**   | Primary value action measurement. Pair with `run_started` for completion %.                       |
| `workflow.run_failed`          | **P0**   | Reliability signal. `error_class` enum bounded; never carries raw error text.                     |
| `node.error`                   | P1       | Per-node failure attribution within a run.                                                        |
| `composer.turn_completed`      | **P0**   | The chat-driving-graph signal — VISION.md primary path. Token buckets, tool-call counts.          |
| `composer.tool_call`           | **P0**   | Approval-gate visibility for Plan/Auto/YOLO modes.                                                |
| `host.op_executed`             | **P0**   | Per-connector adoption across 116 ops × 18 hosts. The connector ROI signal.                       |
| `skill.saved`                  | P1       | Skill-creation funnel; pairs with `skill.loaded` for save→reuse rate.                              |
| `skill.loaded`                 | P1       | Reuse signal.                                                                                       |
| `skill.promoted_to_shared`     | P1       | Account-level Skill maturity signal (private → firm-shared promotion).                            |
| `vision.image_pasted`          | P1       | Vision-input is a headline differentiator; measure adoption.                                       |
| `marketplace.pack_installed`   | P1       | Marketplace traction.                                                                              |
| `marketplace.pack_uninstalled` | P2       | Negative signal counterpart.                                                                       |

### Configuration (6 add)

| Event                       | Priority | Why                                                                                       |
|-----------------------------|----------|-------------------------------------------------------------------------------------------|
| `provider.key_configured`   | P1       | First-provider-attached funnel + provider-mix breakdown.                                  |
| `provider.key_removed`      | P2       | Negative-signal counterpart; flags credential rotation.                                   |
| `host.toggled`              | P1       | Host adoption tied to user intent (on) vs detection (auto_probe).                          |
| `connector.installed`       | P1       | Add-in deployment health. Pairs with Sentry crash data on broker startup failures.        |
| `setting.changed`           | P2       | Single consolidated event — `setting_key` enum bounded.                                    |
| `onboarding.step_completed` | **P0**   | First-run activation funnel. The reason we can answer "where do users drop off?"          |

### Billing (9 add)

| Event                     | Priority | Why                                                                            |
|---------------------------|----------|--------------------------------------------------------------------------------|
| `trial.started`           | **P0**   | Trial cohort kickoff.                                                          |
| `trial.expired`           | **P0**   | Trial→paid conversion %.                                                       |
| `plan.changed`            | **P0**   | Single event for upgrade/downgrade/reactivation. Revenue tracking.              |
| `subscription.cancelled`  | **P0**   | Churn signal + reason_class.                                                   |
| `seat.invited`            | P1       | Account growth funnel.                                                         |
| `seat.accepted`           | P1       | Pairs with seat.invited; invite → acceptance %.                                |
| `seat.removed`            | P1       | Account contraction signal.                                                    |
| `quota.warning`           | P1       | Pre-block UX signal (`used_percent_bucket` ∈ {80, 90, 95}).                    |
| `quota.exhausted`         | **P0**   | Hard-block UX signal — drives upgrade decisions.                                |

### Landing (4 add — page_viewed is the fifth landing event, but listed in Lifecycle above via signup_started)

| Event                       | Priority | Why                                                                                                 |
|-----------------------------|----------|-----------------------------------------------------------------------------------------------------|
| `landing.page_viewed`       | **P0**   | The landing acquisition funnel does not exist today. One event for all pages, `page` enum bounded.   |
| `landing.cta_clicked`       | **P0**   | Per-CTA conversion. `cta_id` and `destination` enums bounded by the actual landing HTML.             |
| `landing.download_started`  | **P0**   | Where the funnel ends for users who pick "Direct download" over `winget`.                            |

### Quality (1 add)

| Event           | Priority | Why                                                                              |
|-----------------|----------|----------------------------------------------------------------------------------|
| `error.surfaced`| P1       | User-perceived-error volume — the complement to Sentry's exception count.          |

---

## Identity management — net-new wiring

This is the biggest structural delta. Today: zero `identify()`, zero `group()`, zero `alias()`, zero `reset()`. Target:

| Call            | Trigger                                                                                  | Where                                            |
|-----------------|------------------------------------------------------------------------------------------|--------------------------------------------------|
| `posthog.identify(user_id, traits)` | On every `user.signed_in`. The first call after a fresh install auto-aliases the install UUID. | `app/sign_in.py` + `cloud_backend/auth.py`       |
| `posthog.group("account", account_id, traits)` | On account creation, on every account-trait change, and on scheduled snapshot ticks. | `cloud_backend/companies.py` + a daily snapshot job |
| `posthog.alias(distinct_id, user_id)` | Implicit via `identify` first call — no separate call needed.                          | Same as `identify`                                |
| `posthog.reset()` | On `user.signed_out` (rare in desktop — only when a different user signs in on the same machine). | `app/sign_in.py` sign-out handler                |

**Trait inventory** (full schema in `tracking-plan.yaml`):

- **User:** `email`, `name`, `created_at`, `first_value_action_at`, `last_active_at`, `install_first_seen_at`, `plan`, `role`, `account_id`, `is_internal`, plus 6 scheduled snapshot metrics (skill counts, workflow counts, composer counts, hosts/providers active, install_count).
- **Account:** `name`, `created_at`, `plan`, `billing_provider`, `seat_limit`, `trial_status`, `trial_ends_at`, `first_value_account_at`, `relay_managed`, `self_hosted_relay`, `is_internal`, plus 5 daily snapshots (active_users_30d, skill_runs_30d, workflows_run_30d, hosts_active_30d, seats_pending_invite) and 2 hourly snapshots (`mrr_usd`, `seats_used`).

---

## Surface delta — where the code lands

| Surface                                | Today              | Target                                                                                                          |
|----------------------------------------|--------------------|-----------------------------------------------------------------------------------------------------------------|
| `app/telemetry.py`                     | 1 wrapper, 5 callers | Same wrapper. Add `identify()`, `group()`, `reset()`, `is_internal_guard()`. Add `EVENT_SCHEMA_VERSION = 1`.    |
| `app/web_ui/studio-lm.jsx`             | 0 events           | ~10 events fired via a new `bridge.track_event(name, props_json)` slot — keeps the PII chokepoint Python-side. |
| `app/bridge.py`                        | No tracking slot   | Add `track_event(name, props_json)` + `identify(user_id, traits_json)` + `reset()` slots.                       |
| `cloud_backend/main.py` and siblings   | 0 events           | Billing, seat, signup, signin, quota events. A second PostHog wrapper for the FastAPI process (separate distinct_id pool — uses cloud user_id). |
| `cloud_backend/proxy.py`               | 0 events           | (Optional v2) Per-request relay events for Studio/Enterprise.                                                  |
| `web/src/layouts/Base.astro` (Astro site, track-A; supersedes static `landing/index.html`) | 0 events  | PostHog JS snippet in the shared layout `<head>` (covers all 6 pages), `posthog.capture('landing.page_viewed', ...)` on load, delegated CTA click handler. |
| `pii_redactor.py`                      | Already gates ✓    | Unchanged — already the chokepoint.                                                                            |

---

## Naming convention migration

Today's 5 events use mixed grammar (`app_started`, `provider_blocked`, `telemetry_opted_in`, `skill_run`, `user_feedback`). Target is uniform `object.action_snake_case`. This is a one-shot rename — there are no production dashboards built on these names (verified zero JSX hits, zero landing hits, zero cloud hits — every existing consumer is the PostHog default dashboard, which we own).

**Mitigation:** None required. The 5 events fire low-frequency enough that a single deploy that emits both old and new names for ~48 hours is unnecessary overhead. Rip the bandaid in one PR.

---

## Property-shape migration risks

| Risk                                                                                          | Mitigation                                                                                                             |
|-----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| `provider_blocked.reason` is free-form text. Any alert that greps for substrings (e.g. "401") breaks once it becomes `reason_class`. | Map the existing free-form `reason` strings to the new enum at the call site in `llm_router.py:_block_provider`. Document the mapping. Drop the raw string. |
| `user_feedback.comment` carries the user's literal typed feedback. Removing it loses qualitative texture. | Comments stay locally in the existing `feedback.json` sidecar. Anything that needs the body reads it there. The telemetry event becomes the volume + sentiment signal only. |
| `app_started.silent=true` events that get queued before consent will reach PostHog under the renamed `app.launched` once consent flips — looks like a backfill. | Document the queue behaviour in `current-implementation.md` (now done). Accept it: the event already had this property today, the rename does not change semantics. |

---

## Internal-user exclusion

Per the `internal_user_policy: by_flag` decision in the plan:

1. On `user.signed_up`, set the `is_internal` trait based on email-domain match. The domain list lives in a single constant in `app/telemetry.py` (or the cloud-backend equivalent for cloud-side events) — `@archhub.io`, `@anthropic.com`, plus a hand-curated test-account list.
2. Add an `is_internal_guard()` early-return inside `track_event` that consults the most recent `identify()` payload. When the trait is true, the event drops at the wrapper — never reaches PostHog ingest.
3. The cloud-backend wrapper applies the same guard at FastAPI middleware level.
4. The landing site has no concept of internal user — landing events are unaffected (and acceptable as they will not pollute downstream account analytics).

This mirrors `app/sentry_init.py:_before_send` dropping events when `PYTEST_CURRENT_TEST` is set. The PostHog wrapper inherits the same pattern.

---

## Rollout phasing — implementation backlog (prioritised)

| Phase | Scope                                                                                                          | Estimated PR count |
|-------|----------------------------------------------------------------------------------------------------------------|---------------------|
| **0 — schema floor** | Add `EVENT_SCHEMA_VERSION = 1` constant in `app/telemetry.py`. Document the version flow.            | 1                   |
| **1 — identify + group + reset wiring** | `app/bridge.py` slots + `app/sign_in.py` calls + cloud-backend `companies.py` group calls. | 2                   |
| **2 — rename + change the 5 existing events** | One PR each (5 PRs) so each rename is independently revertable.                          | 5                   |
| **3 — P0 ADDs (desktop + cloud)** | `user.signed_up`, `user.signed_in`, `activation.first_skill_run`, `node.placed`, `workflow.run_*`, `composer.turn_completed`, `composer.tool_call`, `host.op_executed`, `onboarding.step_completed`. | 4–6                 |
| **4 — P0 ADDs (billing)** | `trial.*`, `plan.changed`, `subscription.cancelled`, `quota.exhausted`. All cloud-side.                      | 2                   |
| **5 — P0 ADDs (landing)** | PostHog JS snippet + `page_viewed` + `cta_clicked` + `download_started`.                                    | 1                   |
| **6 — Snapshot sync** | Daily + hourly jobs that write trait snapshots back to PostHog `group()` and `identify()`.                       | 1                   |
| **7 — P1 ADDs** | Skill, vision, marketplace, host toggle, connector install, error.surfaced, seat events.                              | 3                   |
| **8 — P2 ADDs + cleanup** | Remaining events + delete dead branches in the audit's `current-implementation.md`.                          | 1                   |

Total: ~20 PRs across 8 phases. Phase 1 + 2 are blocking for everything else.

---

## Open questions / decisions outside this skill's scope

Listed for the founder, not pre-decided here:

- **`account_id` on desktop-only users.** Desktop-only users (no cloud sign-in) have no account. They currently appear in PostHog as anonymous installs. Decide whether to synthesise a `solo_<distinct_id>` account or accept the missing-group rows.
- **Marketplace install events for free vs paid packs.** Today `marketplace.pack_installed.price_tier` differentiates; consider whether paid installs need a separate revenue event in `cloud_backend/marketplace.py` that joins to Stripe.
- **Cloud relay request-volume event (`relay.request`).** Mentioned in `tracking-plan.yaml` `coverage_check.observability_holes`. Deferred to v2 until the relay's volume is high enough that a per-request event becomes worth its PostHog cost.
- **Brain (personal-brain-mcp) usage events.** Skill mints / context injections / write counts are not in v1. Brain has its own observability via its DB. Decide if a thin event channel is wanted later.
- **`error.surfaced.source_module` cardinality.** "Bounded categorical" needs a curated list; the implementation guide should produce one.

These belong in the next phase (`product-tracking-generate-implementation-guide`) or as `docs/ROADMAP.md` items (per ROADMAP-MANDATE), not in a parallel plan doc.
