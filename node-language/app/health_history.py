"""Per-host health-state history (v0.42).

Ring-buffer log of each connector family's health state, sampled
every time ConnectorHealth ticks (~5 s). Drives the Reality Check
sparklines in the Telemetry page so the architect can see at a
glance whether a host has been flapping, dead, or steady-green over
the last 24 hours without staring at the live dot.

Storage: in-memory ring buffer per family (cap 24h × 12 ticks/min ≈
17,280 entries, but we cap at 4,096 — 5.7 hours at 5s cadence — to
stay light; older entries roll off). Optional disk mirror at
%LOCALAPPDATA%/ArchHub/health_history.json so a Studio relaunch
doesn't lose context.

Public API
----------
    record(family: str, state: str) -> None
    history(family: str, *, since_seconds: int = 86400) -> list[tuple[float, str]]
    success_rate(family: str, *, since_seconds: int = 86400) -> float
    last_failure(family: str) -> tuple[float, str] | None
    families() -> list[str]
    clear() -> None
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional


# Ring buffer cap per family. 4096 entries × 5s = 5h 41m of history,
# enough to spot trends in the sparkline without bloating memory.
# The persistence layer trims to the same cap on save.
_RING_CAP = 4096

# How long a "live" run counts toward the success rate. States below
# count as success; everything else is failure.
_SUCCESS_STATES = {"live"}

_LOCK = threading.Lock()
_RINGS: dict[str, deque[tuple[float, str]]] = {}


def _store_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArchHub"
    base.mkdir(parents=True, exist_ok=True)
    return base / "health_history.json"


def _load_from_disk() -> None:
    """Hydrate the in-memory rings from the persisted JSON if it
    exists. Best-effort: corrupt files are silently dropped — the
    next tick re-populates."""
    p = _store_path()
    if not p.exists():
        return
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return
        for fam, entries in d.items():
            ring: deque[tuple[float, str]] = deque(maxlen=_RING_CAP)
            for e in entries:
                if (isinstance(e, list) and len(e) == 2
                        and isinstance(e[0], (int, float))
                        and isinstance(e[1], str)):
                    ring.append((float(e[0]), e[1]))
            _RINGS[fam] = ring
    except Exception:
        pass


def _save_to_disk() -> None:
    p = _store_path()
    try:
        snap = {fam: list(r) for fam, r in _RINGS.items()}
        p.write_text(json.dumps(snap), encoding="utf-8")
    except Exception:
        pass


# Hydrate once at import time (safe no-op when no file).
_load_from_disk()
_LAST_SAVE = 0.0


def record(family: str, state: str) -> None:
    """Append (now, state) to the family's ring. Only writes when the
    state CHANGED from the previous record — flat runs of "live"
    don't bloat the buffer. Saves to disk at most once per 30s to
    keep IO light."""
    if not family or not state:
        return
    global _LAST_SAVE
    now = time.time()
    with _LOCK:
        ring = _RINGS.get(family)
        if ring is None:
            ring = deque(maxlen=_RING_CAP)
            _RINGS[family] = ring
        # Edge-only recording — repeated identical states roll up.
        if ring and ring[-1][1] == state:
            return
        ring.append((now, state))
        # Throttled persistence.
        if now - _LAST_SAVE > 30.0:
            _LAST_SAVE = now
            _save_to_disk()


def history(family: str, *, since_seconds: int = 86400
            ) -> list[tuple[float, str]]:
    """Return all recorded ticks for the family within the window.
    Result is ordered oldest → newest, copied from the ring so the
    caller can paint without holding the lock."""
    cutoff = time.time() - max(0, since_seconds)
    with _LOCK:
        ring = _RINGS.get(family)
        if not ring:
            return []
        return [(t, s) for (t, s) in ring if t >= cutoff]


def success_rate(family: str, *, since_seconds: int = 86400) -> float:
    """Fraction of time-weighted history where the family was 'live'.

    Time-weighted: we integrate state segments, not raw counts, so a
    family that's been dead for 23h and live for 1h reports ~4%
    even if there were only two recorded ticks.
    """
    items = history(family, since_seconds=since_seconds)
    if not items:
        return 0.0
    now = time.time()
    cutoff = now - since_seconds
    # Build segments [start, end, state]. Last segment runs to now.
    segs: list[tuple[float, float, str]] = []
    prev_t, prev_s = items[0]
    if prev_t > cutoff:
        # Pad the first segment with the first known state back to
        # the cutoff — assume the state held before the window
        # started so we don't undercount.
        segs.append((cutoff, prev_t, prev_s))
    for t, s in items[1:]:
        segs.append((prev_t, t, prev_s))
        prev_t, prev_s = t, s
    segs.append((prev_t, now, prev_s))
    total = sum(end - start for (start, end, _) in segs)
    if total <= 0:
        return 0.0
    good = sum(end - start for (start, end, st) in segs
                if st in _SUCCESS_STATES)
    return good / total


def last_failure(family: str) -> Optional[tuple[float, str]]:
    """Return (timestamp, state) of the most recent non-live entry,
    or None if the family has only ever been live."""
    with _LOCK:
        ring = _RINGS.get(family)
        if not ring:
            return None
        for t, s in reversed(ring):
            if s not in _SUCCESS_STATES:
                return (t, s)
    return None


def families() -> list[str]:
    with _LOCK:
        return sorted(_RINGS.keys())


def clear() -> None:
    """Wipe in-memory + disk. Used by tests."""
    with _LOCK:
        _RINGS.clear()
    try:
        p = _store_path()
        if p.exists():
            p.unlink()
    except Exception:
        pass
