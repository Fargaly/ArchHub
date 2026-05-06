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

from pii_redactor import redact_dict
from secrets_store import load_setting, save_setting

# ---------------------------------------------------------------------------
# Settings keys live in secrets_store (Windows Credential Manager-backed
# JSON) so they survive uninstall/reinstall on the same user account.
# ---------------------------------------------------------------------------
_CONSENT_KEY     = "telemetry_consent"        # bool | null
_DISTINCT_ID_KEY = "telemetry_distinct_id"    # uuid str
_PROJECT_KEY_KEY = "telemetry_posthog_key"    # phc_*  (set by installer or env var)
_HOST_KEY        = "telemetry_posthog_host"   # https://eu.posthog.com  (default)


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
# Public surface — callers use these two.
# ---------------------------------------------------------------------------
def track_event(name: str, **props: Any) -> None:
    """Fire an event. No-op if telemetry off / SDK missing / network down."""
    c = _client_or_none()
    if c is None:
        return
    try:
        c.capture(
            distinct_id=distinct_id(),
            event=name,
            properties=redact_dict(props),
        )
    except Exception:
        # Never let telemetry break the host app.
        pass


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
