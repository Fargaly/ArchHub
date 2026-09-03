"""Telemetry — opt-in PostHog wrapper for product analytics.

Design contract (every line of this module assumes these):

  1. **Off by default.** First boot writes `telemetry_consent=null` and
     `is_enabled()` returns False until the user explicitly opts in.
  2. **Cloud-first.** Events go to PostHog Cloud (eu.posthog.com by
     default — GDPR safe for EU + UAE users).
  3. **PII-redacted.** Every event property goes through
     `pii_redactor.redact_dict` before posthog.capture().
  4. **Non-blocking.** Network calls happen in PostHog's background
     thread. The chat / Skill matcher must NEVER wait on telemetry.
  5. **Failure-silent.** A telemetry failure must not surface as an
     error to the user. We log + drop.
  6. **Feature flags.** `is_feature_enabled()` consults PostHog's flag
     evaluator with a stable per-install distinct_id. Cached locally
     so a network blip doesn't disable a flag mid-skill-run.

Use `track_event(name, **props)` for product events. Use
`is_feature_enabled(flag, default)` to gate code paths.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Optional

from pii_redactor import redact, redact_dict
from secrets_store import load_setting, save_setting

# ---------------------------------------------------------------------------
# Settings keys live in secrets_store (Windows Credential Manager-backed
# JSON) so they survive uninstall/reinstall on the same user account.
# ---------------------------------------------------------------------------
_CONSENT_KEY     = "telemetry_consent"        # bool | null
_DISTINCT_ID_KEY = "telemetry_distinct_id"    # uuid str
_PROJECT_KEY_KEY = "telemetry_posthog_key"    # phc_*  (set by installer or env var)
_HOST_KEY        = "telemetry_posthog_host"   # https://eu.posthog.com  (default)

# track-G Phase 0: stamped onto every event so downstream consumers can
# detect property additions / renames from the payload alone.
EVENT_SCHEMA_VERSION = 1

# Internal-user exclusion (track-G): events from these email domains drop at
# the wrapper, mirroring sentry_init's PYTEST_CURRENT_TEST guard. Set via env
# (comma-separated) or fall back to the founder defaults.
_INTERNAL_DOMAINS_ENV = "ARCHHUB_INTERNAL_EMAIL_DOMAINS"
_INTERNAL_DEFAULT     = "archhub.io,anthropic.com"

# In-memory identity cache so capture() can attach user_id + account_id (and
# apply the internal-user guard) without every call-site passing them. Set by
# identify() on sign-in, cleared by reset() on sign-out.
_cached_user_id: Optional[str] = None
_cached_account_id: Optional[str] = None
_cached_is_internal: bool = False


def _project_key() -> Optional[str]:
    return (
        load_setting(_PROJECT_KEY_KEY)
        or os.environ.get("ARCHHUB_POSTHOG_KEY")
        or None
    )


def _host() -> str:
    # PostHog Cloud has TWO subdomains per region:
    #   eu.posthog.com       — dashboard / admin UI
    #   eu.i.posthog.com     — ingestion endpoint (where /capture lives)
    # The SDK needs the .i. ingest host or events 404 silently.
    return (
        load_setting(_HOST_KEY)
        or os.environ.get("ARCHHUB_POSTHOG_HOST")
        or "https://eu.i.posthog.com"
    )


def consent_state() -> Optional[bool]:
    """None = never asked; True = opted in; False = opted out."""
    val = load_setting(_CONSENT_KEY)
    if val is None:
        return None
    return bool(val)


def set_consent(opted_in: bool) -> None:
    """Called by the first-run dialog. Persisted across reinstalls."""
    save_setting(_CONSENT_KEY, bool(opted_in))


def distinct_id() -> str:
    """A stable per-install UUID used by PostHog to dedupe events.

    NOT tied to email, hostname, or anything personal. Re-rolls only
    if the user wipes %LOCALAPPDATA%/ArchHub.
    """
    did = load_setting(_DISTINCT_ID_KEY)
    if not did:
        did = str(uuid.uuid4())
        save_setting(_DISTINCT_ID_KEY, did)
    return did


def is_enabled() -> bool:
    """True iff (a) user opted in, (b) a project key is configured."""
    return consent_state() is True and _project_key() is not None


# ---------------------------------------------------------------------------
# Lazy PostHog client. Built on first use so import-time cost is zero
# for users who never opt in.
# ---------------------------------------------------------------------------
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
        # PostHog SDK not installed in the user's Python — silent off.
        return None
    try:
        _client = Posthog(
            project_api_key=_project_key(),
            host=_host(),
            # Background thread is the SDK's default; keep send-on-shutdown.
            disable_geoip=True,    # we don't need IP geolookup; redactor strips IPs anyway
            sync_mode=False,
        )
    except Exception:
        _client = None
    return _client


# ---------------------------------------------------------------------------
# Identity helpers (track-G Phase 0/1)
# ---------------------------------------------------------------------------
def _is_internal_email(email: Optional[str]) -> bool:
    if not email:
        return False
    domains = (os.environ.get(_INTERNAL_DOMAINS_ENV) or _INTERNAL_DEFAULT).split(",")
    el = email.lower()
    return any(el.endswith("@" + d.strip().lower()) for d in domains if d.strip())


def redact_dict_traits(d: Optional[dict]) -> dict:
    """Redact trait values but KEEP emails — PII policy is traits_only, so
    identify() payloads may carry email/name. Event properties still use the
    stricter redact_dict (emails dropped)."""
    if not d:
        return {}
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = redact(v, drop_emails=False)
        elif isinstance(v, dict):
            out[k] = redact_dict_traits(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [redact(x, drop_emails=False) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out


def _set_cached_user(user_id: str, traits: dict) -> None:
    global _cached_user_id, _cached_account_id, _cached_is_internal
    _cached_user_id = user_id
    _cached_account_id = traits.get("account_id")
    _cached_is_internal = bool(
        traits.get("is_internal") or _is_internal_email(traits.get("email"))
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
def track_event(name: str, *, user_id: Optional[str] = None,
                account_id: Optional[str] = None, **props: Any) -> None:
    """Fire an event. No-op if telemetry off / SDK missing / network down /
    the current user is internal.

    user_id + account_id default to the identify()-cached values, so most
    call-sites pass neither. The account id is attached as a PostHog group so
    any event can be segmented by account.
    """
    if _cached_is_internal:
        return  # internal-user guard — drop at the chokepoint
    c = _client_or_none()
    if c is None:
        return
    try:
        effective_uid = user_id or _cached_user_id or distinct_id()
        effective_aid = account_id or _cached_account_id
        props = dict(props)
        props["$schema_version"] = EVENT_SCHEMA_VERSION
        kw: dict = {
            "distinct_id": effective_uid,
            "event": name,
            "properties": redact_dict(props),  # event props NEVER carry PII
        }
        if effective_aid:
            kw["groups"] = {"account": effective_aid}
        c.capture(**kw)
    except Exception:
        # Never let telemetry break the host app.
        pass


def identify(user_id: str, traits: Optional[dict] = None, *,
             set_once: Optional[dict] = None) -> None:
    """Bind the install's distinct_id to a cloud user_id and set traits.

    Called from sign-in. The first call after a fresh install auto-aliases
    the anonymous install UUID to user_id — no separate alias() needed.
    Updates the identity cache so subsequent track_event calls attach the
    user + account automatically.
    """
    _set_cached_user(user_id, traits or {})
    c = _client_or_none()
    if c is None:
        return
    try:
        payload = redact_dict_traits(traits or {})
        if set_once:
            payload["$set_once"] = redact_dict_traits(set_once)
        c.identify(distinct_id=user_id, properties=payload)
    except Exception:
        pass


def group_account(account_id: str, traits: Optional[dict] = None) -> None:
    """Register / update an account-level group in PostHog (B2B segmentation)."""
    global _cached_account_id
    _cached_account_id = account_id
    c = _client_or_none()
    if c is None:
        return
    try:
        c.group_identify(
            group_type="account",
            group_key=account_id,
            properties=redact_dict_traits(traits or {}),
        )
    except Exception:
        pass


def reset() -> None:
    """Clear the identity cache on sign-out so a different user on the same
    install is not attributed to the previous user_id. The next track_event
    falls back to the anonymous install UUID until the next identify()."""
    global _cached_user_id, _cached_account_id, _cached_is_internal
    _cached_user_id = None
    _cached_account_id = None
    _cached_is_internal = False


def is_feature_enabled(flag: str, default: bool = False) -> bool:
    """Return PostHog's verdict on a feature flag for this install.

    `default` returns when telemetry is off OR the SDK is unreachable —
    so callers can wrap risky / experimental code with a flag and still
    get sensible behaviour for users who opted out.
    """
    c = _client_or_none()
    if c is None:
        return default
    try:
        v = c.feature_enabled(flag, distinct_id())
        return bool(v) if v is not None else default
    except Exception:
        return default


def shutdown() -> None:
    """Call from main.py atexit so in-flight events flush."""
    global _client
    if _client is None:
        return
    try:
        _client.flush()
        _client.shutdown()
    finally:
        _client = None
