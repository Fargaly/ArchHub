# Current instrumentation architecture — ArchHub

**Status:** Factual description as of 2026-05-26. Not a recommendation.

## SDK

- **Package:** `posthog` (Python SDK)
- **Pin status:** Not pinned in `app/requirements.txt` (deliberate — same implicit-local-only / silent-off-in-CI class as `cryptography`, `specklepy`, `mcp`).
- **Companion:** `sentry-sdk` for crash / error, initialised at `app/sentry_init.py`. Same opt-in flag.

## Initialization

- **Where:** Lazy — built on first call to `track_event` via `_client_or_none()` in `app/telemetry.py:97`.
- **What guards init:** `is_enabled()` requires both `consent_state() is True` and a configured project key. Either condition false → `_client_or_none()` returns `None` → `track_event` is a no-op.
- **Failure path on SDK absence:** `from posthog import Posthog` is wrapped in `try/except ImportError` (`telemetry.py:107`). If the SDK is not installed, `_client` stays `None`. No exception escapes.

## Client / server

- **Client only.** Every `track_event` call lives in `app/` (desktop client). `cloud_backend/` contains zero tracking calls. Stripe + Polar webhooks and the FastAPI auth/companies/proxy/marketplace endpoints do not emit telemetry.
- **JSX side.** `app/web_ui/studio-lm.jsx` (~5k lines, the React UI) emits no events. There is no `bridge.track_event` slot or equivalent JS→Python pathway for analytics in the current bridge surface.

## Call routing

- **Centralized wrapper.** `app/telemetry.py:track_event(name, **props) -> None`. Every Python call site imports this and calls through it. Five call sites total today; pattern is uniform.
- **PII chokepoint.** Every `props` dict is sent through `pii_redactor.redact_dict(props)` at `telemetry.py:136` before reaching `posthog.capture(...)`. `redact_dict` walks every string value through `redact()`, which strips Windows + POSIX paths, API/OAuth tokens (Anthropic / OpenAI / OpenRouter / Google / GitHub / PostHog / Sentry DSN), emails, IPv4 addresses, and quoted project-folder names. Names, phone numbers, and free-form natural-language personal text are not scrubbed.
- **Defence-in-depth.** Every call site additionally wraps the `track_event` call in its own `try/except`. The wrapper itself is failure-silent (line 138–140 `except Exception: pass`).

## Identity management

- **Anchor:** `telemetry.distinct_id()` — UUID4 generated on first call and persisted via `secrets_store.save_setting(_DISTINCT_ID_KEY, did)` (Windows Credential Manager-backed JSON). Stable across reinstalls on the same user account; re-rolls only if `%LOCALAPPDATA%/ArchHub` is wiped.
- **No `identify()` calls.** Anonymous-only. Cloud-issued `user_id` from sign-in is never aliased to the install UUID.
- **No `group()` calls.** Multi-seat company context is not attached.
- **No reset / logout teardown.** distinct_id survives sign-out.

## Environment variables and settings

| Setting key                | Source                  | Fallback env var          | Default                          |
|----------------------------|-------------------------|---------------------------|----------------------------------|
| `telemetry_consent`        | secrets_store           | —                         | `null` (prompt on first run)     |
| `telemetry_distinct_id`    | secrets_store           | —                         | generated UUID4                  |
| `telemetry_posthog_key`    | secrets_store           | `ARCHHUB_POSTHOG_KEY`     | `None` (events drop silently)    |
| `telemetry_posthog_host`   | secrets_store           | `ARCHHUB_POSTHOG_HOST`    | `https://eu.i.posthog.com`       |
| `sentry_dsn`               | secrets_store           | `ARCHHUB_SENTRY_DSN`      | `None` (Sentry stays off)        |

## Error handling

- Wrapper-internal: `except Exception: pass` around every `posthog` call (`telemetry.py:139`).
- Call-site: every consumer wraps `track_event` in its own `try/except`.
- Initialisation: SDK import + `Posthog(...)` constructor both wrapped — failure leaves `_client = None`, which makes subsequent `track_event` calls no-ops.
- Sentry `before_send` returns `None` (drops the event) when `PYTEST_CURRENT_TEST` is set. The PostHog wrapper has no equivalent guard.

## Shutdown / flush

- `telemetry.shutdown()` exists (`telemetry.py:160`) and calls `_client.flush()` + `_client.shutdown()`. Whether it is wired into `main.py`'s `atexit` was not verified in this pass; the docstring "Call from main.py atexit so in-flight events flush" reads as intent.

## Async model

- `Posthog(..., sync_mode=False)` — SDK runs its own background thread. `track_event` returns immediately on the calling thread.
- `disable_geoip=True` is set so the ingest endpoint does not attach IP-geo data (the wrapper assumes the redactor has already stripped IPs).

## Feature flags

- `telemetry.is_feature_enabled(flag: str, default: bool = False) -> bool` is wired to PostHog's flag evaluator, keyed on the same `distinct_id` as events.
- No grep hits for `is_feature_enabled` at call sites in the scanned modules — present as a primitive, not yet consumed by feature code paths.

## Patterns worth preserving

These are not recommendations — they describe the current shape so the next phase (implementation guide) can build on them rather than re-invent them.

- One central wrapper (`app/telemetry.py`) — single PII chokepoint, single SDK init, single shutdown call.
- Lazy SDK init — zero import-time cost for users who never opt in.
- Stable, install-scoped, anonymous-by-default `distinct_id` — already meets the privacy commitment in `landing/security.html`.
- Same consent flag governs both PostHog and Sentry — one Settings toggle for both destinations.
- Failure-silent contract at every layer — telemetry can never break the host app.
- Background-thread async — the calling code never waits.
- PostHog EU ingest (`eu.i.posthog.com`) — GDPR-friendly default.
