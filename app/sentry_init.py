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
import threading
import time
from collections import defaultdict
from typing import Any

from pii_redactor import redact_dict
from secrets_store import load_setting
from telemetry import consent_state, distinct_id


_DSN_KEY = "sentry_dsn"
_initialised = False

# ─── Anti-flood rate limiter (the CLASS fix) ──────────────────────────────
# A single recurring error (e.g. the ambient self-extend pass cycling a
# signed-out provider chain and logging one archhub.llm ERROR per failing
# provider on every pass) used to ship one Sentry event per occurrence —
# thousands of identical events. The root cause is structural: ANY error
# emitted at logging.ERROR rides the default LoggingIntegration into Sentry,
# so the flood guard must live in before_send where EVERY event funnels.
#
# We FINGERPRINT each event (exception type + top-of-stack frame, or the log
# message) and cap how many events per fingerprint ship per process session.
# Once a fingerprint hits the cap we drop the rest (return None). This makes
# NO recurring error — known OR unknown, present OR future — able to flood:
# a real crash still reports (the first few times), a runaway loop cannot.
#
# A short time-window cap is layered on top so even DISTINCT fingerprints
# can't burst-upload faster than _MAX_PER_WINDOW within _WINDOW_SECONDS.
_FP_CAP = 3                    # max events per distinct fingerprint per session
_MAX_PER_WINDOW = 30          # max events of ANY kind per rolling window
_WINDOW_SECONDS = 60.0

_rl_lock = threading.Lock()
_fp_counts: dict[str, int] = defaultdict(int)
_window_hits: list[float] = []


def _event_fingerprint(event: dict[str, Any], hint: dict[str, Any]) -> str:
    """Stable key for an event: exception type + top frame when present,
    else the log message / event id. Dedups recurring identical errors so
    the per-fingerprint cap bites the SAME error, not unrelated ones."""
    try:
        exc = (event.get("exception") or {}).get("values") or []
        if exc:
            last = exc[-1] or {}
            etype = str(last.get("type") or "Exception")
            frames = ((last.get("stacktrace") or {}).get("frames") or [])
            top = frames[-1] if frames else {}
            where = "{}:{}:{}".format(
                top.get("module") or top.get("filename") or "?",
                top.get("function") or "?",
                top.get("lineno") or "?",
            )
            return "exc|" + etype + "|" + where
    except Exception:
        pass
    # logger record (LoggingIntegration) or message event — key on the
    # logger + the message template so e.g. one archhub.llm ERROR shape
    # collapses to one fingerprint regardless of the interpolated provider.
    try:
        logentry = event.get("logentry") or {}
        msg = (logentry.get("message")
               or event.get("message")
               or "")
        logger = str(event.get("logger") or "")
        level = str(event.get("level") or "")
        return "log|" + logger + "|" + level + "|" + str(msg)[:120]
    except Exception:
        return "evt|" + str(event.get("event_id") or id(event))


def _flood_drop(event: dict[str, Any], hint: dict[str, Any]) -> bool:
    """True if this event should be DROPPED by the anti-flood limiter.
    Combines a per-fingerprint session cap with a rolling-window global cap.
    Thread-safe (Sentry may call before_send from worker threads)."""
    now = time.monotonic()
    fp = _event_fingerprint(event, hint)
    with _rl_lock:
        # Rolling window: prune old hits, then enforce the global burst cap.
        cutoff = now - _WINDOW_SECONDS
        if _window_hits:
            _window_hits[:] = [t for t in _window_hits if t >= cutoff]
        if len(_window_hits) >= _MAX_PER_WINDOW:
            return True
        # Per-fingerprint session cap: the recurring-error killer.
        if _fp_counts[fp] >= _FP_CAP:
            return True
        _fp_counts[fp] += 1
        _window_hits.append(now)
        return False


def _reset_rate_limiter() -> None:
    """Test hook — clear the per-process counters between cases."""
    with _rl_lock:
        _fp_counts.clear()
        _window_hits.clear()


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Final scrub before any event leaves. Returns None to drop entirely."""
    # Drop test-suite crashes — they pollute the dashboard.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    # ANTI-FLOOD (class fix): cap recurring/duplicate events so no error —
    # known or future — can ever flood the dashboard. A genuine crash still
    # reports (the first _FP_CAP times); a runaway loop is silenced after.
    if _flood_drop(event, hint):
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
