---
id: AgDR-0049
title: track-G telemetry instrumentation — wiring the 45-event plan into live surfaces
timestamp: 2026-05-31
status: executed
category: instrumentation
supersedes: null
superseded_by: null
predecessor_verified: "Phase 0 shipped + verified — commit 3a9b82d, 14/14 telemetry tests green, 8-point behaviour check passed"
---

## Context

`.telemetry/tracking-plan.yaml` defines a 45-event target (up from 5 live). Phase 0
(commit `3a9b82d`, branch `track-g-telemetry-phase0`) landed the **foundation** in
`app/telemetry.py` — `EVENT_SCHEMA_VERSION`, `identify()` / `group_account()` /
`reset()`, the internal-user guard, and `redact_dict_traits()` — all verified live and
non-breaking. Phase 0 was a single-file additive extension of an existing contract, so
it needed no AgDR.

Phase 1+ is different. Emitting the 45 events touches **three surfaces at once** —
`app/web_ui/studio-lm.jsx` (canvas/composer events), `app/bridge.py` (a new JS→Python
telemetry slot), and `cloud_backend/` (billing/seat/signup events). That is a
cross-surface change under the WORKSHOP-GATE definition (≥3 of jsx / bridge /
tool_engine / connector / runner / substrate), so it requires this AgDR before code.

The hard constraint: the public privacy commitment in `landing/security.html` —
**never transmit prompts, model responses, file paths, project names, or API keys.**
Every instrumentation decision below inherits that.

## Options considered

| # | JSX-emit mechanism | PII chokepoint | Verdict |
|---|--------------------|----------------|---------|
| A | JSX calls PostHog-JS directly in the canvas | splits — redactor logic duplicated in JS | ✗ two redactors drift; the JS one will leak |
| B | JSX → new `bridge.track_event_json(name, props_json)` slot → existing Python `track_event` | single — `pii_redactor` stays the one chokepoint | ✓ chosen |
| C | JSX writes events to a file the Python side tails | adds a runtime + latency, no upside | ✗ over-engineered |

| # | Identity binding | Verdict |
|---|------------------|---------|
| A | call `identify()` from JSX on sign-in | JSX would hold user traits incl. email | ✗ PII crosses into JS |
| B | call `telemetry.identify()` from `app/sign_in.py` (Python) on `user.signed_in`; JSX only fires anonymous events until then | ✓ chosen — traits never leave Python |

## Decision

1. **JSX events go through a bridge slot, not PostHog-JS.** Add
   `bridge.track_event_json(name: str, props_json: str)` +
   `bridge.identify_json(user_id, traits_json)` + `bridge.telemetry_reset()` to
   `app/bridge.py`. JSON in, parsed Python-side, routed through the existing
   `telemetry.track_event` / `identify` / `reset`. The `pii_redactor` chokepoint
   stays the single egress filter. JSX never imports a PostHog SDK.
2. **Identity is bound in Python**, from `app/sign_in.py` on successful sign-in
   (`telemetry.identify(user_id, traits)`), and from `cloud_backend/auth.py` for the
   web path. The install-UUID → user_id alias is automatic on the first `identify`.
3. **Cloud events** (`trial.*`, `plan.changed`, `subscription.cancelled`, `seat.*`,
   `quota.*`, `user.signed_up`) fire from a parallel `cloud_backend/telemetry.py`
   wrapper that mirrors the desktop one (own distinct_id = cloud user_id, same
   internal-domain guard). Built in its own slice.
4. **Event names** follow `object.action` snake_case (per the plan). Every event
   carries `$schema_version` (Phase 0 stamps it). No raw text in any property —
   bounded enums / buckets only, per the plan's property specs.
5. **Slices, each independently shippable + CDP-verified before the next:**
   - **1a** — bridge slots + JSX helper `trackEvent()`; wire the 6 P0 canvas events
     (`node.placed`, `workflow.run_started/completed/failed`, `composer.turn_completed`,
     `host.op_executed`). Verify each fires via PostHog Live Events on the running app.
   - **1b** — `app/sign_in.py` identify/reset wiring + `activation.first_skill_run` +
     `onboarding.step_completed`.
   - **1c** — `cloud_backend/telemetry.py` + the billing/seat/signup events.
   - **1d** — landing snippet in `web/src/layouts/Base.astro` (page_viewed / cta_clicked
     / download_started).
   - **1e** — the daily/hourly snapshot-sync job for group + user traits.

## Consequences

- **Positive:** the primary value action (canvas run) becomes measurable; the
  acquisition funnel becomes visible; one PII chokepoint, auditable.
- **Cost:** `app/bridge.py` gains 3 slots (115+ → 118+). JSX gains a thin helper.
  A new `cloud_backend/telemetry.py`. None change existing behaviour — all additive.
- **Risk:** the autonomous loop also edits `studio-lm.jsx` frequently → do 1a on a
  short-lived branch and merge fast to avoid conflict. Each slice is revertible
  (single-surface diffs).
- **DEFINITION-OF-SHIPPED:** no slice is "shipped" until a CDP screenshot shows the
  event in PostHog Live Events after restart on the committed SHA.

## Artifacts

- Plan: `.telemetry/tracking-plan.yaml` (45 events), `.telemetry/delta.md` (backlog),
  `.telemetry/implementation-guide.md` (the SDK-specific code templates).
- Phase 0 (done): `app/telemetry.py`, `app/requirements.txt` — commit `3a9b82d`.
- This slice (proposed): `app/bridge.py`, `app/web_ui/studio-lm.jsx`,
  `cloud_backend/telemetry.py`, `web/src/layouts/Base.astro`.

## Open fork for founder sign-off (flips status proposed → executed)

- **`account_id` for desktop-only users** (no cloud sign-in): synthesize
  `solo_<distinct_id>` group, or accept missing account rows? Recommendation:
  accept missing — do not invent groups. **Decided 2026-05-31: accept
  missing; desktop-only users get no synthetic account group.** Reversible
  in slice 1c if the founder wants `solo_<distinct_id>` later.

## Slice status

- **1a (bridge + canvas events): BUILT 2026-05-31** — `app/bridge.py` gains
  `track_event_json` / `identify_json` / `telemetry_reset` slots (py_compile +
  AST verified); `app/web_ui/studio-lm.jsx` gains the `trackEvent()` helper +
  `workflow.run_started` wired at both Run call sites (Babel-parse verified).
  Live CDP proof on the running app is pending an app launch — so per
  DEFINITION-OF-SHIPPED this is "built + parse-verified", not yet "shipped".
- 1b–1e: not started.
