# Implementation Guide — ArchHub Telemetry

**Target SDK:** PostHog (Python on desktop + Python on cloud + JS on landing)
**Generated from:** `.telemetry/tracking-plan.yaml` v1 on 2026-05-26.
**Preserves:** `app/telemetry.py` centralized wrapper · `pii_redactor.redact_dict` chokepoint · lazy init · failure-silent contract · shared consent flag with Sentry.

This guide is the contract the implementation phase follows. It teaches **how** to make the three core calls (`identify`, `group`, `track`) in each of ArchHub's three surfaces — Python desktop, Python cloud backend, browser landing site. Wire each of the 45 target events using these templates.

---

## SDK setup

### Dependencies

**Desktop + cloud backend (Python):**

```text
# pin in app/requirements.txt + cloud_backend/requirements.txt
posthog>=4.0.0,<5
```

**Landing (browser):** plain `<script>` snippet from CDN — no build step (matches the existing zero-build landing pattern).

**Sentry stays unchanged** — already wired in `app/sentry_init.py` and the cloud backend's `main.py` (verify in cloud-side). Shared consent flag with PostHog stays.

### Initialization

| Surface | File | Pattern | Init trigger |
|---------|------|---------|--------------|
| Desktop  | `app/telemetry.py` (existing) | Lazy: built on first `track_event` call via `_client_or_none()`. KEEP this. | First call. |
| Cloud    | `cloud_backend/telemetry.py` (NEW) | Eager: build once at FastAPI startup; `flushAt=20`, `flushInterval=10000`. | App startup. |
| Landing  | `web/src/layouts/Base.astro` `<head>` (Astro shared layout — covers all 6 pages) | Plain `<script>` snippet, `defer` attribute, no `autocapture` (we only want what's in the plan). | DOM parse. |

### Environment variables

| Variable                    | Purpose                                                | Required | Default                          |
|-----------------------------|--------------------------------------------------------|----------|----------------------------------|
| `ARCHHUB_POSTHOG_KEY`       | Desktop client project key. Wins over secrets_store.   | yes (prod) | none                           |
| `ARCHHUB_POSTHOG_HOST`      | Ingest host.                                           | no       | `https://eu.i.posthog.com`       |
| `ARCHHUB_POSTHOG_KEY_CLOUD` | Separate project key for the cloud backend (recommended — different distinct_id space, different volume). | yes (prod) | none |
| `ARCHHUB_POSTHOG_KEY_WEB`   | Landing-site project key. May be the same as `_CLOUD`. | yes (prod) | none |
| `ARCHHUB_POSTHOG_DEBUG`     | If set, enables `posthog.debug()` logging.             | no       | unset                            |
| `ARCHHUB_INTERNAL_EMAIL_DOMAINS` | Comma-separated internal-user domains for the `is_internal` guard. | no | `archhub.io,anthropic.com` |

The desktop `secrets_store` keys (`telemetry_posthog_key`, `telemetry_posthog_host`, `sentry_dsn`) remain authoritative on user machines; env vars are the dev / CI override path.

---

## Identity — `identify()`

### Syntax

**Python (desktop + cloud) — Posthog client:**

```python
client.identify(
    distinct_id="usr_abc123",          # cloud user_id from cloud_backend
    properties={...},                  # the trait dict from the tracking plan
)
```

**Browser (landing):**

```javascript
posthog.identify('usr_abc123', { /* traits */ });
```

The Python SDK's `identify` call automatically aliases the previous anonymous `distinct_id` (the install UUID) to the new identified `distinct_id` (cloud `user_id`). No separate `alias()` call is needed.

### User traits (from `tracking-plan.yaml`)

| Trait                  | Type     | PII  | Update pattern | Notes                                                 |
|------------------------|----------|------|----------------|-------------------------------------------------------|
| `email`                | string   | yes  | on_change      | Required. Pass via `$set` to update without resetting other traits. |
| `name`                 | string   | yes  | on_change      | Optional.                                              |
| `created_at`           | datetime | no   | one_time       | Pass via `$set_once`.                                  |
| `first_value_action_at`| datetime | no   | one_time       | Set inside the `activation.first_skill_run` capture using `$set_once`. |
| `last_active_at`       | datetime | no   | on_change      | Set inside every `app.launched` capture via `$set`.    |
| `install_first_seen_at`| datetime | no   | one_time       | Pass via `$set_once` on first `app.launched`.           |
| `plan`                 | enum     | no   | on_change      | `free` / `pro` / `studio` / `enterprise`.              |
| `role`                 | enum     | no   | on_change      | `member` / `admin` / `owner` / `none`.                 |
| `account_id`           | string   | no   | on_change      | Property for filterability; the canonical link is the `group()` call. |
| `is_internal`          | bool     | no   | one_time       | Set at signup. Drives the wrapper's drop-guard.        |
| Snapshot metrics       | int / array | no | scheduled     | `skill_runs_30d`, `workflows_run_30d`, `composer_turns_30d`, `hosts_active_30d`, `providers_configured`, `skill_count_owned`, `install_count`. |

PII traits flow through `pii_redactor.redact_dict` exactly the same as event properties — the redactor recognises email patterns but is configured to preserve them when called from the `identify()` path (the wrapper passes an `is_trait=True` flag through to a `redact_dict_traits()` helper that disables the email regex). Names pass through.

### When to call `identify()`

| Surface | Trigger                                                                 |
|---------|-------------------------------------------------------------------------|
| Desktop | On every successful `user.signed_in` from `app/sign_in.py`. The first call aliases the install UUID to the cloud `user_id`. |
| Cloud   | On every `user.signed_up`, `user.signed_in`, and trait-changing event (plan change, role change). `cloud_backend/auth.py` + `cloud_backend/companies.py`. |
| Landing | Almost never — landing users are anonymous until they sign up. If you can read the cloud user_id from a returning-user cookie, call `identify` once on page load. |

### Template — desktop Python (in `app/telemetry.py`)

```python
def identify(user_id: str,
             traits: dict | None = None,
             *,
             set_once: dict | None = None) -> None:
    """Bind the current distinct_id to a cloud user_id and update traits.

    Called from app/sign_in.py on user.signed_in. The first call after a
    fresh install aliases the install-UUID distinct_id to user_id — no
    separate alias() call needed.
    """
    c = _client_or_none()
    if c is None:
        return
    try:
        props = redact_dict_traits(traits or {})
        # $set / $set_once go in `properties` for the Posthog Python SDK.
        if set_once:
            props["$set_once"] = redact_dict_traits(set_once)
        c.identify(
            distinct_id=user_id,
            properties=props,
        )
        # Cache last-known user_id for the internal-guard fast path.
        _set_cached_user(user_id, traits or {})
    except Exception:
        pass  # Failure-silent contract.
```

### Template — cloud Python (in `cloud_backend/telemetry.py`)

```python
def identify_user(user_id: str, *, email: str, name: str | None,
                  created_at: datetime, plan: str, role: str,
                  account_id: str | None, is_internal: bool) -> None:
    if _client is None:
        return
    try:
        _client.identify(
            distinct_id=user_id,
            properties={
                "email": email,
                "name": name,
                "plan": plan,
                "role": role,
                "account_id": account_id,
                "is_internal": is_internal,
                "$set_once": {"created_at": created_at.isoformat()},
            },
        )
    except Exception:
        pass
```

### Template — landing browser (in a single `<script>` block inside `web/src/layouts/Base.astro`)

```javascript
// Anonymous-only on landing. Identify only when a returning-user cookie
// carries the cloud user_id (set by the cloud relay after sign-in).
const returningUser = readCookie('ah_uid');
if (returningUser) {
  posthog.identify(returningUser);  // Anonymised-distinct-id will alias.
}
```

---

## Groups — `group()` / `groupIdentify()`

The plan defines one group type: `account`. PostHog's `group analytics` is a paid add-on — confirm the plan tier before relying on segmentation. Until then, also mirror critical group traits onto user identify calls as a `account_*` property prefix so segmentation works on the free tier.

### Syntax

**Python:**

```python
client.group_identify(
    group_type="account",
    group_key="acc_abc123",
    properties={"name": "Acme Studio", "plan": "studio", "mrr_usd": 158.0, ...},
)
```

For every event that belongs to an account, pass `groups={"account": "acc_abc123"}` on the `capture` call (Python SDK is stateless — every event must explicitly carry its group).

**Browser:**

```javascript
posthog.group('account', 'acc_abc123', { name: 'Acme Studio', plan: 'studio' });
// Subsequent posthog.capture() calls auto-attach the group.
```

### Group hierarchy

| Level   | SDK group type | ID source                             | Parent |
|---------|----------------|---------------------------------------|--------|
| account | `account`      | `cloud_backend` companies.id (`acc_*`) | none   |

No nested levels. Session and Skill are event properties, not groups (see `tracking-plan.yaml` § Group Hierarchy notes).

### Group traits (from `tracking-plan.yaml`)

Full list in the plan — `name`, `plan`, `billing_provider`, `seat_limit`, `seats_used`, `seats_pending_invite`, `mrr_usd`, `trial_status`, `trial_ends_at`, `relay_managed`, `self_hosted_relay`, `first_value_account_at`, `active_users_30d`, `skill_runs_30d`, `workflows_run_30d`, `hosts_active_30d`, `is_internal`.

### When to call `group_identify()`

| Trigger                                  | Caller                                              |
|------------------------------------------|-----------------------------------------------------|
| Account created                          | `cloud_backend/companies.py:create_company`         |
| Plan changed                             | Stripe webhook handler + Polar webhook handler      |
| Seat invited / accepted / removed        | `cloud_backend/companies.py:invite_member` and the accept-invite endpoint |
| Account renamed                          | `cloud_backend/companies.py:rename_company`         |
| Daily snapshot tick                      | New `cloud_backend/jobs/telemetry_snapshot.py` cron |
| Hourly billing snapshot tick             | Same cron, hourly cadence for `mrr_usd` + `seats_used` |

### Template — `group_identify()` from cloud (in `cloud_backend/telemetry.py`)

```python
def identify_account(account_id: str, *, traits: dict) -> None:
    if _client is None:
        return
    try:
        _client.group_identify(
            group_type="account",
            group_key=account_id,
            properties=redact_dict_traits(traits),
        )
    except Exception:
        pass
```

---

## Events — `track()` / `capture()`

### Syntax

**Python (the existing wrapper — preserved):**

```python
def track_event(name: str,
                *,
                user_id: str | None = None,
                account_id: str | None = None,
                **props: Any) -> None:
    """Centralized capture. Every event goes through this function."""
```

**Browser (landing):**

```javascript
posthog.capture('landing.page_viewed', { page: 'home', ... });
```

### SDK constraints (call them out explicitly)

- **Group analytics is paid.** Free tier still receives the events but can't segment by group. Plan accordingly.
- **Group attribution is per-call in Python.** Pass `groups={"account": account_id}` on every account-level capture — the SDK is stateless server-side.
- **Cardinality cap on group types: 5 per project.** The plan uses 1 (`account`). Headroom exists.
- **Distinct_id continuity.** Calling `identify()` from a fresh anonymous session auto-aliases. Calling `reset()` discards both the distinct_id and group associations — call it on sign-out only when a different user will use the same install.
- **`posthog` Python SDK has no native dataclass support.** Property dicts are JSON-serialisable primitives only. Reject non-JSON values at the wrapper.
- **The `posthog` import is unpinned in `app/requirements.txt` today.** Pin it during this rollout — `posthog>=4.0.0,<5`.
- **No raw error message bodies in event properties.** `pii_redactor` strips paths/keys/emails/IPs/quoted project names, but free-form natural language can still leak. The plan's `error_class` enum is bounded by design — never pass raw exception messages.

### Template — desktop event with group context

```python
# app/skills/usage.py — the renamed skill.run event
from telemetry import track_event

track_event(
    "skill.run",
    skill_id=skill_id,
    success=success,
    elapsed_ms=elapsed_ms,
    is_retry=is_retry,
    error_class=classify_error(error),       # categorical, never raw error text
    invoked_via=invoked_via,                  # canvas_run | composer | palette | trigger
)
# The wrapper attaches user_id + account_id from cached identity, plus
# groups={"account": cached_account_id} on the Posthog capture call.
```

### Template — cloud event with group context

```python
# cloud_backend/billing.py — plan.changed handler inside a webhook
from telemetry import track_event

track_event(
    "plan.changed",
    user_id=user_id,
    account_id=account_id,
    from_plan=from_plan,
    to_plan=to_plan,
    direction=direction,                      # upgraded | downgraded | reactivated
    billing_provider="stripe",
    mrr_delta_usd=mrr_delta,
)
```

### Template — landing event

```javascript
// web/src/layouts/Base.astro — fire on every page view + every CTA click
posthog.capture('landing.page_viewed', {
  page: 'home',
  referrer_class: classifyReferrer(document.referrer),
  utm_source: getQueryParam('utm_source') || null,
  utm_medium: getQueryParam('utm_medium') || null,
  utm_campaign: getQueryParam('utm_campaign') || null,
  device_class: classifyDevice(navigator.userAgent),
});
```

### Group-level attribution

The plan attributes events to two levels:

- **`group_level: user`** — every in-canvas event (`node.placed`, `workflow.run_*`, `composer.*`, `host.op_executed`, `skill.*`, `feedback.submitted`, configuration events, lifecycle events except billing).
- **`group_level: account`** — every billing/seat event + `skill.promoted_to_shared` + `user.signed_up`.
- **`group_level: null`** — pre-signup landing events (`landing.page_viewed`, `landing.cta_clicked`, `landing.download_started`, `landing.waitlist_joined`, `landing.signup_started`).

The wrapper handles the "user-level event that still wants the user's account_id rolled up" case by **always** including `groups={"account": cached_account_id}` when a cached account_id exists — regardless of whether the event is account-level or user-level. PostHog's group analytics can then segment any event by account.

Account-level events additionally carry `account_id` as a property so the free tier (no group-analytics add-on) can still filter on it.

---

## Complete Tracking Module

The desktop wrapper at `app/telemetry.py` exists and works — this section shows the extended version with identity + group + internal-guard wired in, ready to copy. Cloud and landing surfaces follow.

### Desktop: `app/telemetry.py` (extended)

```python
"""Telemetry — opt-in PostHog wrapper for product analytics.

Contract (unchanged from v0):
  1. Off by default.
  2. Cloud-first (eu.i.posthog.com).
  3. PII-redacted at source (pii_redactor).
  4. Non-blocking — PostHog SDK background thread.
  5. Failure-silent — telemetry never breaks the host app.
  6. Feature-flag-capable.

v1 additions:
  - identify() + reset() so the install-UUID → user_id alias happens.
  - is_internal guard at the wrapper — drops events for internal users.
  - EVENT_SCHEMA_VERSION constant + auto-attached to every event property.
  - Cached account_id auto-attached as group context on every capture.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from pii_redactor import redact_dict
from secrets_store import load_setting, save_setting

EVENT_SCHEMA_VERSION = 1

_CONSENT_KEY     = "telemetry_consent"
_DISTINCT_ID_KEY = "telemetry_distinct_id"
_PROJECT_KEY_KEY = "telemetry_posthog_key"
_HOST_KEY        = "telemetry_posthog_host"

_INTERNAL_DOMAINS_ENV = "ARCHHUB_INTERNAL_EMAIL_DOMAINS"
_INTERNAL_DEFAULT = "archhub.io,anthropic.com"

# In-memory identity cache so capture() can attach user_id + account_id
# automatically without every call-site passing them.
_cached_user_id: Optional[str] = None
_cached_account_id: Optional[str] = None
_cached_is_internal: bool = False


def _project_key() -> Optional[str]:
    return load_setting(_PROJECT_KEY_KEY) or os.environ.get("ARCHHUB_POSTHOG_KEY") or None


def _host() -> str:
    return (
        load_setting(_HOST_KEY)
        or os.environ.get("ARCHHUB_POSTHOG_HOST")
        or "https://eu.i.posthog.com"
    )


def consent_state() -> Optional[bool]:
    val = load_setting(_CONSENT_KEY)
    return None if val is None else bool(val)


def set_consent(opted_in: bool) -> None:
    save_setting(_CONSENT_KEY, bool(opted_in))


def distinct_id() -> str:
    did = load_setting(_DISTINCT_ID_KEY)
    if not did:
        did = str(uuid.uuid4())
        save_setting(_DISTINCT_ID_KEY, did)
    return did


def is_enabled() -> bool:
    return consent_state() is True and _project_key() is not None


# -- Lazy SDK client --------------------------------------------------------
_client = None

def _client_or_none():
    global _client
    if _client is not None:
        return _client
    if not is_enabled():
        return None
    try:
        from posthog import Posthog
    except ImportError:
        return None
    try:
        _client = Posthog(
            project_api_key=_project_key(),
            host=_host(),
            disable_geoip=True,
            sync_mode=False,
        )
        if os.environ.get("ARCHHUB_POSTHOG_DEBUG"):
            _client.debug = True
    except Exception:
        _client = None
    return _client


# -- Internal-user guard ----------------------------------------------------
def _is_internal_email(email: str | None) -> bool:
    if not email:
        return False
    domains = (
        os.environ.get(_INTERNAL_DOMAINS_ENV) or _INTERNAL_DEFAULT
    ).split(",")
    return any(email.lower().endswith("@" + d.strip().lower()) for d in domains if d.strip())


def _set_cached_user(user_id: str, traits: dict) -> None:
    global _cached_user_id, _cached_account_id, _cached_is_internal
    _cached_user_id = user_id
    _cached_account_id = traits.get("account_id")
    _cached_is_internal = bool(
        traits.get("is_internal")
        or _is_internal_email(traits.get("email"))
    )


# -- redact_dict for traits is the same primitive; emails are kept ----------
def redact_dict_traits(d: dict | None) -> dict:
    """Same as pii_redactor.redact_dict but preserves emails (traits-only)."""
    # PII policy = traits_only: emails are allowed inside identify() payloads.
    return redact_dict(d, _allow_emails=True) if d else {}


# -- Public surface ---------------------------------------------------------
def track_event(name: str,
                *,
                user_id: str | None = None,
                account_id: str | None = None,
                **props: Any) -> None:
    """Fire an event.

    No-op when:
      * telemetry is off (consent not granted)
      * SDK absent / not initialised
      * cached user is internal (is_internal guard)
    """
    c = _client_or_none()
    if c is None:
        return
    if _cached_is_internal:
        return  # internal users skipped at the chokepoint — mirrors Sentry PYTEST_CURRENT_TEST
    try:
        effective_uid = user_id or _cached_user_id or distinct_id()
        effective_aid = account_id or _cached_account_id
        props = dict(props)
        props["$schema_version"] = EVENT_SCHEMA_VERSION
        groups = {"account": effective_aid} if effective_aid else None
        c.capture(
            distinct_id=effective_uid,
            event=name,
            properties=redact_dict(props),  # event properties NEVER carry PII
            groups=groups,
        )
    except Exception:
        pass


def identify(user_id: str,
             traits: dict | None = None,
             *,
             set_once: dict | None = None) -> None:
    c = _client_or_none()
    if c is None:
        return
    try:
        props = redact_dict_traits(traits or {})
        if set_once:
            props["$set_once"] = redact_dict_traits(set_once)
        c.identify(distinct_id=user_id, properties=props)
        _set_cached_user(user_id, traits or {})
    except Exception:
        pass


def group_account(account_id: str, traits: dict) -> None:
    c = _client_or_none()
    if c is None:
        return
    try:
        c.group_identify(
            group_type="account",
            group_key=account_id,
            properties=redact_dict_traits(traits),
        )
        global _cached_account_id
        _cached_account_id = account_id
    except Exception:
        pass


def reset() -> None:
    """Drop the identity cache. Call on sign-out when a different user
    may sign in on the same install. PostHog Python SDK has no reset() —
    we drop our cache and the next track_event uses the install UUID."""
    global _cached_user_id, _cached_account_id, _cached_is_internal
    _cached_user_id = None
    _cached_account_id = None
    _cached_is_internal = False


def is_feature_enabled(flag: str, default: bool = False) -> bool:
    c = _client_or_none()
    if c is None:
        return default
    try:
        v = c.feature_enabled(flag, _cached_user_id or distinct_id())
        return bool(v) if v is not None else default
    except Exception:
        return default


def shutdown() -> None:
    """Call from main.py atexit."""
    global _client
    if _client is None:
        return
    try:
        _client.flush()
        _client.shutdown()
    finally:
        _client = None
```

### Bridge slots: extend `app/bridge.py`

```python
# app/bridge.py — JSX-facing slots so the React UI never owns the redactor.
import json
from PyQt6.QtCore import pyqtSlot
import telemetry as _t


class ArchHubBridge(QObject):
    # ...existing slots...

    @pyqtSlot(str, str)
    def track_event_json(self, name: str, props_json: str) -> None:
        """JSX calls this; Python keeps the PII chokepoint."""
        try:
            props = json.loads(props_json) if props_json else {}
        except Exception:
            props = {}
        _t.track_event(name, **props)

    @pyqtSlot(str, str)
    def identify_json(self, user_id: str, traits_json: str) -> None:
        try:
            traits = json.loads(traits_json) if traits_json else {}
        except Exception:
            traits = {}
        _t.identify(user_id, traits)

    @pyqtSlot()
    def telemetry_reset(self) -> None:
        _t.reset()
```

### JSX usage: `app/web_ui/studio-lm.jsx`

```javascript
// Helper — keep one wrapper, no scattered raw strings.
async function trackEvent(name, props) {
  const bridge = await window.archhub_bridge_promise;
  bridge.track_event_json(name, JSON.stringify(props || {}));
}

// Usage at every meaningful JSX call site:
async function onNodePlaced(node, viaSource) {
  await trackEvent('node.placed', {
    node_kind: node.kind,
    node_subtype: node.id,
    via: viaSource,
    workflow_node_count: LM_GRAPH.nodes.length,
  });
}

async function onWorkflowRunStarted(runId, graph) {
  await trackEvent('workflow.run_started', {
    workflow_run_id: runId,
    node_count: graph.nodes.length,
    wire_count: graph.wires.length,
    has_ai_node: graph.nodes.some(n => n.cat === 'ai'),
    has_host_node: graph.nodes.some(n => n.cat === 'connector'),
    host_families_used: distinctHostFamilies(graph).slice(0, 5),
    trigger: 'manual_run',
    is_skill_invocation: false,
  });
}
```

### Cloud backend: `cloud_backend/telemetry.py` (new module)

```python
"""Cloud-side telemetry wrapper. Mirrors app/telemetry.py shape.

Differences from desktop:
  - Eager init at FastAPI startup (long-lived process).
  - distinct_id = cloud user_id directly (no install UUID).
  - Internal-user guard reads is_internal from the request's user object.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

_client = None
_internal_domains = (
    os.environ.get("ARCHHUB_INTERNAL_EMAIL_DOMAINS") or "archhub.io,anthropic.com"
).split(",")


def init() -> None:
    """Call once from cloud_backend/main.py startup."""
    global _client
    key = os.environ.get("ARCHHUB_POSTHOG_KEY_CLOUD")
    if not key:
        return
    try:
        from posthog import Posthog
        _client = Posthog(
            project_api_key=key,
            host=os.environ.get("ARCHHUB_POSTHOG_HOST", "https://eu.i.posthog.com"),
            disable_geoip=True,
            sync_mode=False,
            flush_at=20,
            flush_interval=10,
        )
    except Exception:
        _client = None


def is_internal_email(email: str | None) -> bool:
    if not email:
        return False
    return any(email.lower().endswith("@" + d.strip().lower())
               for d in _internal_domains if d.strip())


def track_event(name: str,
                *,
                user_id: str,
                user_email: str | None = None,
                account_id: str | None = None,
                **props: Any) -> None:
    if _client is None:
        return
    if is_internal_email(user_email):
        return
    try:
        from cloud_backend.pii_redactor import redact_dict  # mirror or import desktop
        props["$schema_version"] = 1
        _client.capture(
            distinct_id=user_id,
            event=name,
            properties=redact_dict(props),
            groups={"account": account_id} if account_id else None,
        )
    except Exception:
        pass


def identify_user(user_id: str, *, traits: dict) -> None:
    if _client is None:
        return
    try:
        _client.identify(distinct_id=user_id, properties=traits)
    except Exception:
        pass


def identify_account(account_id: str, *, traits: dict) -> None:
    if _client is None:
        return
    try:
        _client.group_identify(group_type="account", group_key=account_id,
                               properties=traits)
    except Exception:
        pass


def shutdown() -> None:
    if _client is None:
        return
    try:
        _client.flush()
        _client.shutdown()
    except Exception:
        pass
```

Wire init + shutdown into `cloud_backend/main.py`:

```python
# cloud_backend/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
import telemetry as t

@asynccontextmanager
async def lifespan(_app: FastAPI):
    t.init()
    yield
    t.shutdown()

app = FastAPI(lifespan=lifespan)
```

### Landing: `web/src/layouts/Base.astro` (shared layout)

> **Surface migrated 2026-05-28 (track-A).** The landing site is now an Astro app
> at `web/` with six pages (`web/src/pages/{index,features,pricing,community,security,changelog}.astro`),
> all wrapping the shared `web/src/layouts/Base.astro`. The old static
> `landing/index.html` + `landing/security.html` still exist but are superseded —
> instrument the Astro layout, not the static files. One snippet in `Base.astro`'s
> `<head>` covers every page automatically (the layout is imported by all routes).
> When the old `landing/` files are deleted, drop their instrumentation too.

```html
<!-- Insert in Base.astro <head>, before the closing </head>.
     Replace YOUR_PROJECT_KEY with ARCHHUB_POSTHOG_KEY_WEB at build/deploy time.
     Astro renders this verbatim into every page that uses Base.astro. -->
<script defer>
  !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
  posthog.init('YOUR_PROJECT_KEY', {
    api_host: 'https://eu.i.posthog.com',
    autocapture: false,                 // We instrument explicitly; no DOM-noise.
    capture_pageview: false,            // Fired manually below as 'landing.page_viewed'.
    capture_pageleave: false,
    disable_session_recording: true,    // No session replay on the landing site.
    persistence: 'localStorage+cookie',
    loaded: (ph) => {
      if (location.hostname === 'localhost') ph.opt_out_capturing();
    }
  });
</script>
<script defer>
  // Fire the page_viewed event after init. Self-contained — no framework.
  document.addEventListener('DOMContentLoaded', () => {
    if (!window.posthog) return;
    const ref = document.referrer || '';
    let referrer_class = 'direct';
    if (!ref) referrer_class = 'direct';
    else if (/google|bing|duckduckgo|yahoo/i.test(ref)) referrer_class = 'organic_search';
    else if (/(twitter|x\.com|linkedin|reddit|discord)/i.test(ref)) referrer_class = 'social';
    else referrer_class = 'unknown';

    const qp = new URLSearchParams(location.search);
    posthog.capture('landing.page_viewed', {
      page: detectPage(location.pathname),
      referrer_class,
      utm_source: qp.get('utm_source'),
      utm_medium: qp.get('utm_medium'),
      utm_campaign: qp.get('utm_campaign'),
      device_class: matchMedia('(max-width: 720px)').matches ? 'mobile' :
                     matchMedia('(max-width: 1024px)').matches ? 'tablet' : 'desktop',
    });

    // Delegated CTA listener — attach data-cta-id + data-cta-destination on every CTA element.
    document.body.addEventListener('click', (ev) => {
      const cta = ev.target.closest('[data-cta-id]');
      if (!cta) return;
      posthog.capture('landing.cta_clicked', {
        cta_id: cta.dataset.ctaId,
        destination: cta.dataset.ctaDestination || 'unknown',
        page: detectPage(location.pathname),
      });
    });
  });

  function detectPage(p) {
    // Astro routes from web/src/pages/ (trailing slash optional).
    if (p === '/' || p === '' || p.endsWith('/index.html')) return 'home';
    if (p.includes('features')) return 'features';
    if (p.includes('pricing')) return 'pricing';
    if (p.includes('community')) return 'community';
    if (p.includes('security')) return 'security';
    if (p.includes('changelog')) return 'changelog';
    return 'unknown';
  }
</script>
```

CTA elements gain stable IDs in the HTML:

```html
<a href="https://github.com/Fargaly/ArchHub/releases/latest"
   class="btn"
   data-cta-id="hero_download_exe"
   data-cta-destination="download_exe">Download for Windows</a>

<button type="button"
        class="btn copy-cmd"
        data-cmd="winget install Fargaly.ArchHub"
        data-cta-id="hero_winget_copy"
        data-cta-destination="winget_command_copied">winget install Fargaly.ArchHub</button>
```

---

## Architecture

### Client vs server routing

| Event family                         | Fires from         | distinct_id source              |
|--------------------------------------|--------------------|---------------------------------|
| `app.*`, `node.*`, `workflow.*`, `composer.*`, `host.*`, `skill.*`, `vision.*`, `feedback.*`, `provider.*`, `setting.*`, `onboarding.*`, `connector.*`, `update.*`, `error.surfaced`, `telemetry.opted_in`, `activation.first_skill_run`, `marketplace.*`, `host.toggled` | desktop client (Python via wrapper; JSX via bridge slot) | install UUID until sign-in, then cloud user_id |
| `user.signed_up`, `user.signed_in` (web path), `plan.*`, `subscription.*`, `seat.*`, `trial.*`, `quota.*`, `skill.promoted_to_shared` | cloud backend (Python) | cloud user_id |
| `landing.*`                          | browser            | anonymous PostHog distinct_id (auto-aliased on signup via `posthog.identify(user_id)` once the user lands on the post-signup page) |

### Snapshot sync (new cron)

`cloud_backend/jobs/telemetry_snapshot.py` — daily + hourly schedules:

```python
"""Sync trait snapshots to PostHog identify() + group_identify().

Runs from the existing cloud scheduler. Two ticks:
  - hourly: per-account mrr_usd + seats_used  (billing-critical)
  - daily:  per-user + per-account 30d activity counts
"""
def run_hourly() -> None:
    for company in db.iter_active_companies():
        telemetry.identify_account(company.id, traits={
            "mrr_usd": billing.current_mrr(company),
            "seats_used": db.count_members(company.id),
        })

def run_daily() -> None:
    cutoff = now() - timedelta(days=30)
    for user in db.iter_active_users():
        telemetry.identify_user(user.id, traits={
            "skill_runs_30d":    db.count_skill_runs(user.id, since=cutoff),
            "workflows_run_30d": db.count_workflow_runs(user.id, since=cutoff),
            "composer_turns_30d":db.count_composer_turns(user.id, since=cutoff),
            "hosts_active_30d":  db.distinct_hosts(user.id, since=cutoff),
        })
    for company in db.iter_active_companies():
        telemetry.identify_account(company.id, traits={
            "active_users_30d":  db.count_active_users(company.id, since=cutoff),
            "skill_runs_30d":    db.count_company_skill_runs(company.id, since=cutoff),
            "workflows_run_30d": db.count_company_workflow_runs(company.id, since=cutoff),
            "hosts_active_30d":  db.distinct_company_hosts(company.id, since=cutoff),
            "seats_pending_invite": db.count_pending_invites(company.id),
        })
```

### Queues and batching

- **Desktop:** PostHog Python SDK's own background thread (`sync_mode=False`). Default batch size — no custom queue.
- **Cloud:** `flush_at=20, flush_interval=10`. Tune up to `flush_at=100, flush_interval=30` if MRR-per-event volume becomes a concern.
- **Landing:** PostHog JS SDK auto-batches; no custom queue.

### Shutdown / flush

- **Desktop:** `telemetry.shutdown()` wired via `atexit.register(telemetry.shutdown)` from `app/main.py`. Verify the wiring exists during this rollout — the audit flagged it as unverified.
- **Cloud:** lifespan handler shown above.
- **Landing:** `beforeunload` is not wired — PostHog JS uses sendBeacon for the last event, which is sufficient.

### Error handling

Already pervasive:

- Wrapper-internal `try/except: pass` (failure-silent).
- Call-site `try/except: pass` (defence in depth).
- SDK import wrapped — SDK absent = `_client = None` = no-op.
- Internal-user guard rides early in `track_event`.

The Sentry parity `PYTEST_CURRENT_TEST` guard already drops Sentry events during tests; PostHog inherits the same behaviour via the internal-guard (test runs typically use a `test@archhub.io` user). Optional belt-and-braces:

```python
# at the top of track_event() after _client_or_none():
if os.environ.get("PYTEST_CURRENT_TEST"):
    return
```

---

## Verification

### Confirming delivery

| Surface | Where to look                                                                                                              |
|---------|-----------------------------------------------------------------------------------------------------------------------------|
| Desktop | PostHog → Activity → Live Events. Filter by `distinct_id = <your install UUID>` (run `python -c "from app import telemetry; print(telemetry.distinct_id())"`). |
| Cloud   | Same dashboard, filtered to the cloud project key.                                                                          |
| Landing | Same dashboard, filtered to the web project key. Use the PostHog Chrome devtools `posthog.debug()` console for live diagnostics. |

### Expected latency

- Desktop / cloud Python SDK background thread: events visible in PostHog within 10–30 seconds at default batch settings.
- Landing browser SDK: events visible within 1–5 seconds.

### Success vs failure

- Success: `200 OK` from `https://eu.i.posthog.com/capture/`. SDK silent.
- Failure: SDK retries internally; on permanent failure the event is dropped, no exception escapes. Use `posthog.debug()` to surface failures in development.

### Development testing

- Create a `dev` PostHog project (separate API key). Set `ARCHHUB_POSTHOG_KEY` to that key in the dev environment.
- Internal-user guard auto-drops events when signed in with an `@archhub.io` email — useful for production smoke tests where you do not want to pollute analytics.
- `ARCHHUB_POSTHOG_DEBUG=1` enables PostHog SDK debug logging.
- Landing: set `location.hostname === 'localhost'` short-circuit (already shown above).

---

## Rollout strategy

Phased rollout, mirroring `delta.md` Phases 0–8:

1. **Phase 0 (this PR):** Pin `posthog>=4.0.0,<5` in both `requirements.txt`. Add `EVENT_SCHEMA_VERSION = 1`. Add the `redact_dict_traits` + `_is_internal_email` helpers. No new events yet — purely scaffolding.
2. **Phase 1:** Wire `identify` + `group_identify` + `reset` + bridge slots. Ship `user.signed_in` (desktop) + `user.signed_up` (cloud) so identify fires for the first time. Verify live in PostHog Live Events.
3. **Phase 2 (per event):** Rename + ship-change the 5 existing events one by one. Each rename = one PR for clean revert. Confirm the new name appears in PostHog within 10 minutes of merge.
4. **Phase 3 (desktop P0 ADDs):** `node.placed`, `workflow.run_*`, `composer.*`, `host.op_executed`, `activation.first_skill_run`, `onboarding.step_completed`. Concentrated in `app/web_ui/studio-lm.jsx` + `app/run_workflow.py` + `app/chat_window.py`.
5. **Phase 4 (cloud P0 ADDs):** `trial.*`, `plan.changed`, `subscription.cancelled`, `quota.exhausted`. Inside the Stripe + Polar webhook handlers.
6. **Phase 5 (landing):** Land the `<script>` snippet + `data-cta-id` attributes + page_viewed/cta_clicked/download_started events.
7. **Phase 6 (snapshot cron):** Wire the daily + hourly snapshot jobs.
8. **Phase 7 + 8:** Remaining P1/P2 events, plus the optional `relay.request` event in `cloud_backend/proxy.py`.

Monitoring during the first week: PostHog Live Events tail for each phase, with a watch on event-volume per-day per-event. Any 0-volume event after 48 hours = a wiring bug. Any >100k-events/day single-event = a cardinality bug; investigate the property shape (likely an unbounded value snuck through).

---

## SDK-specific constraints (collected)

- Group analytics is a **paid** PostHog feature. Free tier still receives groups but cannot segment by them. Until paid: mirror critical group traits on user identify (`account_plan`, `account_seats_used`).
- Python SDK is stateless — every `capture()` must explicitly pass `groups`. The wrapper handles this from cache.
- Reset semantics in PostHog Python: no `reset()` method on the SDK. Drop the local cache; the next `capture` will fall back to the install UUID until the next `identify`.
- Max 5 group types per project. Plan uses 1.
- Free-form properties = cardinality cost. Everything bounded in the plan; never pass raw text.
- Error messages from exceptions are PII risk — always classify before sending.

---

## Coverage gaps

- **PostHog reference covers Node.js + browser only.** The Python SDK is in use here and is API-compatible with the patterns shown — verified against the existing `app/telemetry.py` code that ships today. Confirm any new SDK release notes before pinning above `posthog>=4.0.0`.
- **Group analytics paid-tier confirmation** — confirm the PostHog plan tier carries Groups before relying on group segmentation. Workaround in the wrapper today: every event also carries `account_id` as a property where applicable.
- **No documented pattern for PyQt6 atexit + PostHog background-thread interaction.** If exit is fast and `atexit` does not fire (force-kill scenarios), some events drop. Mitigate with `flush_at=1` in development; accept the loss in production.
- **Landing → app attribution.** A user who downloads via `landing.cta_clicked` cannot be auto-aliased to their desktop install UUID. The first `user.signed_in` from the desktop binds the two via the user_id alias. Until then they appear as separate distinct_ids — by design.
- **Cloud backend → desktop client correlation.** When the cloud backend fires `plan.changed`, the desktop client's cached `_cached_account_id` is not auto-updated unless the user re-signs-in or the desktop polls account state. Acceptable for v1 — desktop traits resync on next launch.
