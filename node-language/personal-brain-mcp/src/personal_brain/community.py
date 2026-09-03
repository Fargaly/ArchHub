"""Community discovery + subscribe — Slice 14.

Records which peer firm actor URLs the local firm subscribes to.
A separate poller (run inside the daemon) fetches `/outbox` from each
subscription, runs `evaluate_incoming_pattern` on every Activity, and
imports accepted ones into the local brain (scope=community).

Public surface:
    from personal_brain.community import (
        subscribe, unsubscribe, list_subscriptions, poll_subscription,
        CommunityPoller,
    )

Storage model: each subscription is a Fragment(kind=setup,
scope=user, predicate='subscribed_to', object=<actor_url>).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .federation import (
    ContributorReputation,
    FederationDriver,
    Pattern,
    evaluate_incoming_pattern,
)
from .models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from .storage import BrainStore


# ─────────────────────── data shapes ──────────────────────────────────


@dataclass
class Subscription:
    """One peer outbox we're following."""

    actor_url: str
    display_name: str
    subscribed_at: str
    last_poll_at: Optional[str] = None
    last_accepted: int = 0
    last_quarantined: int = 0
    last_rejected: int = 0


@dataclass
class PollResult:
    actor_url: str
    ok: bool = True
    activities_fetched: int = 0
    activities_new: int = 0
    accepted: int = 0
    quarantined: int = 0
    rejected: int = 0
    error: Optional[str] = None


# ─────────────────────── subscription persistence ─────────────────────


def _sub_frag_id(actor_url: str) -> str:
    import hashlib
    return "sub:" + hashlib.sha256(actor_url.encode("utf-8")).hexdigest()[:16]


def subscribe(
    store: BrainStore, *, actor_url: str, display_name: str = "",
    owner_user: str = "founder",
) -> Subscription:
    """Add a community subscription. Idempotent — re-running overwrites
    the display_name."""
    now = datetime.now(timezone.utc).isoformat()
    frag = Fragment(
        id=_sub_frag_id(actor_url),
        kind=FragmentKind.SETUP,
        text=f"subscribed to community outbox {actor_url}",
        subject="community", predicate="subscribed_to", object=actor_url,
        scope=Scope.USER, visibility=Visibility.PRIVATE,
        owner_user=owner_user,
        provenance=Provenance(
            contributing_agent="community-module",
            contributing_user=owner_user,
        ),
        extra={
            "actor_url": actor_url,
            "display_name": display_name or actor_url,
            "subscribed_at": now,
        },
    )
    store.write_fragment(frag)
    return Subscription(
        actor_url=actor_url,
        display_name=display_name or actor_url,
        subscribed_at=now,
    )


def unsubscribe(store: BrainStore, actor_url: str) -> bool:
    return store.delete_fragment(_sub_frag_id(actor_url))


def list_subscriptions(store: BrainStore) -> list[Subscription]:
    rows = store._conn.execute(
        "SELECT * FROM fragments WHERE kind = 'setup' "
        "AND subject = 'community' AND predicate = 'subscribed_to'"
    ).fetchall()
    out: list[Subscription] = []
    for row in rows:
        try:
            extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
            out.append(Subscription(
                actor_url=extra.get("actor_url") or row["object"],
                display_name=extra.get("display_name") or row["object"],
                subscribed_at=extra.get("subscribed_at") or "",
                last_poll_at=extra.get("last_poll_at"),
                last_accepted=int(extra.get("last_accepted") or 0),
                last_quarantined=int(extra.get("last_quarantined") or 0),
                last_rejected=int(extra.get("last_rejected") or 0),
            ))
        except Exception:
            continue
    return out


# ─────────────────────── outbox fetcher ───────────────────────────────


def fetch_outbox(actor_url: str, *, timeout_s: float = 5.0,
                  http_client: Optional[Any] = None) -> Optional[dict[str, Any]]:
    """GET <peer>/outbox returning the JSON-LD OrderedCollection.
    `http_client` accepts a callable for tests (urllib.request.urlopen-shaped)."""
    if not actor_url.endswith("/outbox"):
        # Allow either /actor or /outbox style
        if actor_url.endswith("/actor"):
            actor_url = actor_url.rsplit("/actor", 1)[0] + "/outbox"
        else:
            actor_url = actor_url.rstrip("/") + "/outbox"
    try:
        opener = http_client or urllib.request.urlopen
        req = urllib.request.Request(actor_url, method="GET",
                                       headers={"Accept": "application/activity+json"})
        with opener(req, timeout=timeout_s) as r:
            data = r.read().decode("utf-8")
        return json.loads(data)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
             json.JSONDecodeError, TimeoutError):
        return None


# ─────────────────────── poller ───────────────────────────────────────


def poll_subscription(
    store: BrainStore,
    driver: FederationDriver,
    sub: Subscription,
    *,
    http_client: Optional[Any] = None,
    reputations: Optional[dict[str, ContributorReputation]] = None,
) -> PollResult:
    """One pull cycle for one subscription. Idempotent on pattern_id."""
    reputations = reputations if reputations is not None else {}
    result = PollResult(actor_url=sub.actor_url)

    outbox = fetch_outbox(sub.actor_url, http_client=http_client)
    if outbox is None:
        result.ok = False
        result.error = "fetch failed"
        return result

    activities = outbox.get("orderedItems") or []
    result.activities_fetched = len(activities)

    # Track which pattern_ids we've already imported
    existing_pat_ids = set()
    rows = store._conn.execute(
        "SELECT id FROM fragments WHERE kind = 'fact' "
        "AND scope = 'community' AND id LIKE 'comm-%'"
    ).fetchall()
    for row in rows:
        existing_pat_ids.add(row["id"])

    for activity in activities:
        obj = (activity or {}).get("object") or {}
        contrib_hash = obj.get("contributor_firm_hash") or "unknown"
        rep = reputations.setdefault(
            contrib_hash, ContributorReputation(contributor_id=contrib_hash),
        )
        decision = driver.receive(activity, reputation=rep)

        if decision.accept:
            rep.accepted_count += 1
            result.accepted += 1
            # Persist as a Fragment with scope=community
            _import_pattern_fragment(store, obj, contrib_hash=contrib_hash)
        elif decision.quarantine:
            rep.quarantine_count += 1
            result.quarantined += 1
        else:
            rep.rejected_count += 1
            result.rejected += 1

    # Update subscription stats
    _update_sub_stats(store, sub, result)
    return result


def _import_pattern_fragment(store: BrainStore, pattern_object: dict[str, Any],
                              *, contrib_hash: str) -> None:
    import hashlib
    pattern_id = pattern_object.get("pattern_id") or ""
    summary = pattern_object.get("summary") or ""
    stats = pattern_object.get("statistics") or {}
    frag_id = "comm-" + hashlib.sha256(
        f"{pattern_id}|{contrib_hash}".encode("utf-8")
    ).hexdigest()[:16]
    frag = Fragment(
        id=frag_id, kind=FragmentKind.FACT,
        text=f"[community] {summary}",
        scope=Scope.COMMUNITY, visibility=Visibility.SHARED_PUBLIC,
        owner_user="community",
        provenance=Provenance(
            contributing_agent="community-poller",
            contributing_user=contrib_hash,
            accessed_resources=[f"pattern:{pattern_id}"],
        ),
        extra={
            "pattern_id": pattern_id, "statistics": stats,
            "contributor_firm_hash": contrib_hash,
        },
    )
    store.write_fragment(frag)


def _update_sub_stats(store: BrainStore, sub: Subscription,
                      result: PollResult) -> None:
    frag_id = _sub_frag_id(sub.actor_url)
    row = store._conn.execute(
        "SELECT extra_json FROM fragments WHERE id = ?", (frag_id,),
    ).fetchone()
    if row is None:
        return
    try:
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
    except Exception:
        extra = {}
    extra["last_poll_at"] = datetime.now(timezone.utc).isoformat()
    extra["last_accepted"] = result.accepted
    extra["last_quarantined"] = result.quarantined
    extra["last_rejected"] = result.rejected
    store._conn.execute(
        "UPDATE fragments SET extra_json = ? WHERE id = ?",
        (json.dumps(extra), frag_id),
    )


# ─────────────────────── async poller ─────────────────────────────────


class CommunityPoller:
    """Background thread polling all current subscriptions every N min."""

    def __init__(
        self,
        store: BrainStore,
        driver: FederationDriver,
        *,
        interval_s: float = 30 * 60.0,  # 30 minutes
        http_client: Optional[Any] = None,
    ):
        self.store = store
        self.driver = driver
        self.interval_s = max(30.0, interval_s)
        self.http_client = http_client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Reputations persist for the worker's lifetime; Slice 15
        # persists them to disk.
        self.reputations: dict[str, ContributorReputation] = {}
        self._lock = threading.Lock()
        self._cycle_count = 0
        self._last_results: list[PollResult] = []

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="brain-community-poller", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                pass
            slept = 0.0
            while slept < self.interval_s and not self._stop_event.is_set():
                time.sleep(min(1.0, self.interval_s - slept))
                slept += 1.0

    def tick(self) -> list[PollResult]:
        with self._lock:
            subs = list_subscriptions(self.store)
            results: list[PollResult] = []
            for sub in subs:
                r = poll_subscription(
                    self.store, self.driver, sub,
                    http_client=self.http_client,
                    reputations=self.reputations,
                )
                results.append(r)
            self._cycle_count += 1
            self._last_results = results
            return results

    def status(self) -> dict[str, Any]:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "interval_s": self.interval_s,
            "cycle_count": self._cycle_count,
            "subscriptions_count": len(list_subscriptions(self.store)),
            "last_results": [asdict(r) for r in self._last_results],
        }
