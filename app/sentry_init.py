"""Sentry crash reporter — opt-in, PII-scrubbed.

Initialised once from main.py before any other PyQt code so an early
import-time crash gets captured. Re-uses the same consent flag as
telemetry.py — one toggle in Settings turns BOTH on/off.

DSN comes from:
  1. secrets_store key 'sentry_dsn' (set by installer / Settings dialog)
  2. env var ARCHHUB_SENTRY_DSN
  3. None — Sentry stays off

The before_send hook redacts every event before it leaves the process.
That covers user paths, API keys, project names, IPs, emails.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from pii_redactor import redact_dict
from secrets_store import load_setting
from telemetry import consent_state, distinct_id


_DSN_KEY = "sentry_dsn"
_initialised = False


def _dsn() -> str | None:
    return (
        load_setting(_DSN_KEY)
        or os.environ.get("ARCHHUB_SENTRY_DSN")
        or None
    )


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Final scrub before any event leaves. Returns None to drop entirely."""
    # Drop test-suite crashes — they pollute the dashboard.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return redact_dict(event)


def init(release: str | None = None) -> bool:
    """Idempotent. Returns True if Sentry actually came up.

    Honours the same opt-in flag as telemetry. If the user is opted
    out, Sentry stays off — they get a degraded experience (no crash
    upload) but zero data ships.
    """
    global _initialised
    if _initialised:
        return True
    if consent_state() is not True:
        return False
    dsn = _dsn()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            release=release,
            traces_sample_rate=0.0,           # no perf traces — too chatty
            send_default_pii=False,
            attach_stacktrace=True,
            max_breadcrumbs=30,
            before_send=_before_send,
            include_local_variables=False,    # local vars often contain secrets
        )
        sentry_sdk.set_user({"id": distinct_id()})
        _initialised = True
        return True
    except Exception:
        return False


def install_qt_excepthook() -> None:
    """Hook PyQt's silent exception handling so unhandled GUI errors
    actually reach Sentry instead of being swallowed by the event loop."""
    if not _initialised:
        return
    try:
        import sentry_sdk
    except ImportError:
        return
    prev_hook = sys.excepthook

    def handler(exc_type, exc, tb):
        try:
            sentry_sdk.capture_exception((exc_type, exc, tb))
        except Exception:
            pass
        # Always chain to the previous hook so the dev console still sees it.
        prev_hook(exc_type, exc, tb)

    sys.excepthook = handler
