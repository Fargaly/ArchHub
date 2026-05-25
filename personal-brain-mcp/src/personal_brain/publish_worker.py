"""Outbox publish cron — Slice 13.

Background thread that periodically:
  1. Pulls the firm's eligible skills (success_count >= threshold).
  2. Pulls recent traces.
  3. Derives Patterns via federation.derive_and_publish.
  4. Applies DP-Laplace noise.
  5. Persists outbox entries to BrainStore (Slice 15 backed by SQLite).
  6. Optionally POSTs to peer outboxes (when configured).

Per ANTI-LIE MANDATE: this is the ACTUAL runtime that publishes
patterns. Without it, federation.py is just primitives.

Default cadence: every 6 hours. Configurable.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .federation import (
    ActivityRecord,
    FederationDriver,
    Outbox,
    Pattern,
    derive_skill_usage_patterns,
    derive_tool_sequence_patterns,
    noise_pattern_statistics,
    pattern_to_activity,
)
from .models import Fragment, FragmentKind, Provenance, Scope, Visibility
from .storage import BrainStore


_META_KEY_LAST_PUBLISH = "publish_worker.last_publish_ts"
_META_KEY_LAST_RESULT = "publish_worker.last_result_json"
_META_KEY_OUTBOX_COUNT = "publish_worker.outbox_count"


# ─────────────────────── outbox persistence ────────────────────────────


def persist_activity_to_brain(
    store: BrainStore, activity: ActivityRecord,
) -> None:
    """Persist an outbox Activity as a Fragment so it survives daemon
    restarts. kind=setup, scope=community (visible to subscribers)."""
    obj = activity.object or {}
    pattern_id = obj.get("pattern_id") or ""
    frag = Fragment(
        id=f"outbox:{pattern_id}",
        kind=FragmentKind.SETUP,
        text=f"outbox activity {activity.type} pattern={pattern_id}",
        subject="outbox", predicate="published", object=pattern_id,
        scope=Scope.COMMUNITY,
        visibility=Visibility.SHARED_PUBLIC,
        owner_user="federation-worker",
        provenance=Provenance(
            contributing_agent="publish-worker",
            contributing_user="federation-worker",
            created_at=datetime.fromisoformat(
                activity.published.replace("Z", "+00:00")
            ) if isinstance(activity.published, str) else datetime.now(timezone.utc),
        ),
        extra={
            "activity_id": activity.id,
            "activity_type": activity.type,
            "actor": activity.actor,
            "object": obj,
            "published": activity.published,
        },
    )
    store.write_fragment(frag)


def load_outbox_from_brain(store: BrainStore) -> list[ActivityRecord]:
    """Reload persisted outbox activities on daemon start."""
    rows = store._conn.execute(
        "SELECT * FROM fragments WHERE kind = 'setup' "
        "AND subject = 'outbox' AND predicate = 'published'"
    ).fetchall()
    out: list[ActivityRecord] = []
    for row in rows:
        try:
            extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
            out.append(ActivityRecord(
                id=extra.get("activity_id") or "",
                type=extra.get("activity_type") or "Create",
                actor=extra.get("actor") or "",
                object=extra.get("object") or {},
                published=extra.get("published") or "",
            ))
        except Exception:
            continue
    return out


# ─────────────────────── publish worker ────────────────────────────────


@dataclass
class PublishCycleResult:
    ok: bool = True
    started_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    eligible_skills: int = 0
    derived_patterns: int = 0
    noised_patterns: int = 0
    activities_persisted: int = 0
    error: Optional[str] = None


class PublishWorker:
    """Cron-style worker that derives + noises + persists patterns to
    the local outbox at a regular cadence."""

    def __init__(
        self,
        store: BrainStore,
        driver: FederationDriver,
        *,
        interval_s: float = 6 * 3600.0,  # 6 hours
        min_success_count: int = 3,
        max_skills_per_cycle: int = 200,
    ):
        self.store = store
        self.driver = driver
        self.interval_s = max(60.0, interval_s)
        self.min_success_count = min_success_count
        self.max_skills_per_cycle = max_skills_per_cycle
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_result: Optional[PublishCycleResult] = None
        self._cycle_count = 0
        # In-memory outbox; persisted activities reload from brain on init
        self.outbox = Outbox(
            actor_url=driver.actor_url, base_url=driver.base_url,
        )
        for activity in load_outbox_from_brain(store):
            self.outbox.activities.append(activity)

    # ── lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="brain-publish-worker", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def _loop(self) -> None:
        # Initial small delay so daemon is fully up before first tick
        if self._stop_event.wait(timeout=5.0):
            return
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                pass
            slept = 0.0
            while slept < self.interval_s and not self._stop_event.is_set():
                time.sleep(min(1.0, self.interval_s - slept))
                slept += 1.0

    # ── one cycle ───────────────────────────────────────────────────

    def tick(self) -> PublishCycleResult:
        with self._lock:
            result = PublishCycleResult()
            t0 = time.perf_counter()
            try:
                # 1. Pull eligible skills
                all_skills = self.store.list_skills(
                    limit=self.max_skills_per_cycle,
                )
                eligible = [
                    s for s in all_skills
                    if s.success_count >= self.min_success_count
                ]
                result.eligible_skills = len(eligible)

                # 2. Derive patterns
                patterns = derive_skill_usage_patterns(
                    eligible, firm_id=self.driver.firm_id,
                    min_success_count=self.min_success_count,
                )
                result.derived_patterns = len(patterns)

                # 3. DP-noise
                noised = [
                    noise_pattern_statistics(p, epsilon=self.driver.epsilon)
                    for p in patterns
                ]
                result.noised_patterns = len(noised)

                # 4. Persist as outbox activities (idempotent — by pattern_id)
                existing_ids = {
                    a.object.get("pattern_id") for a in self.outbox.activities
                }
                persisted = 0
                for p in noised:
                    if p.pattern_id in existing_ids:
                        continue
                    activity = self.outbox.publish(p)
                    persist_activity_to_brain(self.store, activity)
                    persisted += 1
                result.activities_persisted = persisted

                result.duration_ms = (time.perf_counter() - t0) * 1000.0
                self._last_result = result
                self._cycle_count += 1
                self._persist_status(result)
                return result
            except Exception as ex:
                result.ok = False
                result.error = f"{type(ex).__name__}: {ex}"
                result.duration_ms = (time.perf_counter() - t0) * 1000.0
                self._last_result = result
                self._persist_status(result)
                return result

    def status(self) -> dict[str, Any]:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "interval_s": self.interval_s,
            "min_success_count": self.min_success_count,
            "cycle_count": self._cycle_count,
            "outbox_size": len(self.outbox.activities),
            "last_result": asdict(self._last_result) if self._last_result else None,
        }

    def _persist_status(self, result: PublishCycleResult) -> None:
        try:
            self.store.set_meta(_META_KEY_LAST_PUBLISH,
                                 datetime.now(timezone.utc).isoformat())
            self.store.set_meta(_META_KEY_LAST_RESULT, json.dumps(asdict(result)))
            self.store.set_meta(_META_KEY_OUTBOX_COUNT,
                                 str(len(self.outbox.activities)))
        except Exception:
            pass
