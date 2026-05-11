"""ArchHub Cloud usage meter — cached fetch of remaining quota.

The status bar shows e.g. "Cloud · 47 of 500 left" so the user sees
their quota tick down in real time. Calling /v1/me on every chat
turn would burn round-trips; instead we cache the result for 60
seconds + decrement locally on each successful chat completion. A
refresh fires when:
  • cache TTL expires (60s)
  • the user signs in / signs out
  • the chat layer detects a 402 from the backend (quota exhausted)

Public API
----------
    snapshot() -> dict | None     # {plan, remaining_messages, period_end}
    decrement(n: int = 1) -> None
    invalidate() -> None
    refresh_async(callback=None)  # fire-and-forget /v1/me poll
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional


_TTL_SECONDS = 60.0
_LOCK = threading.Lock()
_CACHED: Optional[dict] = None
_FETCHED_AT: float = 0.0


def snapshot() -> Optional[dict]:
    """Return the last-fetched plan/quota snapshot or None when stale.

    Caller may treat None as "I don't know yet — schedule a refresh
    and render a neutral placeholder."""
    global _CACHED, _FETCHED_AT
    with _LOCK:
        if _CACHED is None:
            return None
        if time.time() - _FETCHED_AT > _TTL_SECONDS:
            return None
        return dict(_CACHED)


def decrement(n: int = 1) -> None:
    """Subtract from the cached remaining-message count after a chat
    turn lands. Optimistic — server is authoritative; if the backend
    later reports a different number, the next refresh corrects it."""
    global _CACHED
    with _LOCK:
        if _CACHED is None:
            return
        cur = int(_CACHED.get("remaining_messages") or 0)
        _CACHED["remaining_messages"] = max(0, cur - max(0, n))


def invalidate() -> None:
    """Force the next snapshot() to return None until a fresh fetch.
    Called on sign-in / sign-out / 402 response."""
    global _CACHED, _FETCHED_AT
    with _LOCK:
        _CACHED = None
        _FETCHED_AT = 0.0


def refresh_async(callback: Optional[Callable[[Optional[dict]], None]] = None) -> None:
    """Kick a /v1/me poll on a worker thread. When it lands, update
    the cache + invoke callback(payload_or_none). Idempotent — safe
    to call from multiple call sites; one fetch in flight at a time
    via the lock."""
    def _job() -> None:
        global _CACHED, _FETCHED_AT
        payload: Optional[dict] = None
        try:
            from cloud_client import me
            payload = me()
        except Exception:
            payload = None
        with _LOCK:
            if payload is not None:
                _CACHED = dict(payload)
                _FETCHED_AT = time.time()
            else:
                _CACHED = None
                _FETCHED_AT = 0.0
        if callback is not None:
            try:
                callback(payload)
            except Exception:
                pass
    threading.Thread(target=_job, daemon=True).start()
