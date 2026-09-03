"""self_heal_log.py — the process-wide ledger of REAL self-heal events.

ArchHub's differentiator is its self-healing connectors: when a host's
listener drops, a connector goes loaded_dead, or a graph wire lands on a
type-incompatible port, the app recovers WITHOUT the user restarting
anything. Until now those recoveries were invisible — health INDICATORS
(GraphHealthBadge, HomeGraphHealthChip, the connector_health daemon,
host_detector reconnect) show CURRENT state, but nothing recorded the
heal MOMENTS as a timeline the user could see.

This module is that timeline's single source of truth: a bounded,
thread-safe ring buffer of heal events. Producers across the app call
`record_heal(...)` at the exact instant a heal actually happens; the
bridge reads `recent(...)` + `stats()` and the JSX Self-Heal Inspector
renders them.

ANTI-LIE / MAKE-IT-REAL: this log holds ONLY events that were recorded
because a real recovery fired. It never synthesises rows. An empty log
is the honest "no self-heals yet — connectors are healthy" state, not a
reason to fabricate activity.

Design:
  * `deque(maxlen=N)` — O(1) append, auto-evicts the oldest beyond the
    cap, so a long-running session can never grow this unbounded.
  * One module-level lock guards every mutation + snapshot, so the
    background threads that actually heal (connector_health poll thread,
    host_detector probes off the bridge pool) and the Qt main thread
    that reads for the UI never tear a read.
  * Pure in-memory + per-process. No disk, no secrets, no network. The
    timeline is "what this running app healed" — it resets on relaunch,
    which is the honest scope (a heal that happened in a prior process
    is not something this process witnessed).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Optional

# The cap. 200 recent heals is plenty for a live timeline — old heals
# beyond this evict automatically (a heal from hours ago is not what the
# inspector is for). Keep it bounded so a flapping host can't OOM us.
MAX_EVENTS = 200

# Heal kinds we record. Each maps to an icon + label in the JSX
# inspector. Keeping the vocabulary small + named (not free-form) means
# the stat header's by-kind counts stay meaningful and the UI never has
# to render an unknown bucket.
KIND_RECONNECT = "reconnect"        # a host listener came back (down -> live)
KIND_NETLOAD = "netload"            # a connector add-in re-loaded itself (loaded_dead -> live)
KIND_TYPE_HEAL = "type_heal"        # a graph wire re-routed off a type-mismatched port
KIND_WIRE_REMAP = "wire_remap"      # a wire re-pointed after a node's ports changed
KIND_OTHER = "other"                # any other genuine recovery a producer reports

_KNOWN_KINDS = {
    KIND_RECONNECT, KIND_NETLOAD, KIND_TYPE_HEAL, KIND_WIRE_REMAP, KIND_OTHER,
}

_LOCK = threading.Lock()
_EVENTS: "deque[dict]" = deque(maxlen=MAX_EVENTS)
# Monotonically increasing id so the UI can key rows stably even when two
# heals share a wall-clock second.
_SEQ = 0


def _norm_kind(kind: Any) -> str:
    """Map an incoming kind onto the known vocabulary, defaulting to
    KIND_OTHER. Never raises — a producer that reports a typo'd kind
    still gets its REAL heal recorded, just bucketed as 'other'."""
    k = str(kind or "").strip().lower()
    return k if k in _KNOWN_KINDS else KIND_OTHER


def record_heal(kind: str, target: str = "", detail: str = "",
                ts: Optional[float] = None) -> dict:
    """Record one REAL heal event. Returns the stored event dict.

    Call this at the EXACT moment a recovery actually happened — a host
    reconnected, a connector re-loaded, a wire re-routed off a bad port.
    Do NOT call it speculatively or for "about to try" states; this log
    is the record of heals that SUCCEEDED, which is what makes the
    timeline trustworthy (ANTI-LIE).

    Args:
        kind:   one of KIND_* (free strings are accepted but bucketed to
                'other' if unknown).
        target: what healed — e.g. "revit", "autocad", "ai_chat node".
        detail: one human line — e.g. "listener answered on :48884".
        ts:     unix seconds; defaults to now(). Accepting it lets a
                producer record the moment the heal happened rather than
                the moment it got around to logging.

    Thread-safe. Never raises (a logging hiccup must never break the heal
    path itself).
    """
    global _SEQ
    try:
        when = float(ts) if ts is not None else time.time()
    except (TypeError, ValueError):
        when = time.time()
    ev = {
        "kind": _norm_kind(kind),
        "target": str(target or "")[:200],
        "detail": str(detail or "")[:400],
        "ts": when,
    }
    with _LOCK:
        _SEQ += 1
        ev["id"] = _SEQ
        _EVENTS.append(ev)
    return ev


def recent(n: int = 50) -> list[dict]:
    """Return up to `n` most-recent heal events, NEWEST FIRST.

    The inspector renders a reverse-chronological timeline, so newest-first
    is the natural order. Returns copies so a caller can't mutate the ring.
    Empty list when nothing has healed yet — the honest empty state.
    """
    try:
        limit = int(n)
    except (TypeError, ValueError):
        limit = 50
    if limit <= 0:
        return []
    with _LOCK:
        # deque is oldest->newest; reverse for newest-first, then cap.
        snap = list(_EVENTS)
    snap.reverse()
    return [dict(e) for e in snap[:limit]]


def stats() -> dict:
    """Summarise the log for the inspector's stat header.

    Returns:
        {
          "total":     int,                       # heals recorded this session
          "by_kind":   {kind: count, ...},        # counts per known kind
          "last_heal_ts": float | None,           # ts of the most recent heal
          "last_kind":    str | None,             # kind of the most recent heal
          "last_target":  str | None,             # target of the most recent heal
          "max":       int,                        # ring capacity (MAX_EVENTS)
        }

    All-zero / None when nothing has healed — the inspector reads that as
    its honest empty state. Thread-safe; never raises.
    """
    by_kind = {k: 0 for k in _KNOWN_KINDS}
    with _LOCK:
        total = len(_EVENTS)
        last = _EVENTS[-1] if _EVENTS else None
        for e in _EVENTS:
            k = e.get("kind", KIND_OTHER)
            by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "total": total,
        "by_kind": by_kind,
        "last_heal_ts": (last.get("ts") if last else None),
        "last_kind": (last.get("kind") if last else None),
        "last_target": (last.get("target") if last else None),
        "max": MAX_EVENTS,
    }


def clear() -> None:
    """Drop every recorded heal. For tests + a future user 'clear' action.
    Thread-safe; resets the sequence so test runs are deterministic."""
    global _SEQ
    with _LOCK:
        _EVENTS.clear()
        _SEQ = 0
