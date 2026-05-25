"""Scheduled sync worker — Slice 10.

Background thread that periodically:
  1. Snapshots local firm-scope + project-scope fragments from
     BrainStore.
  2. Pushes the snapshot through the configured Transport (Loro /
     Speckle / JSON file / S3-like).
  3. Pulls the latest remote snapshot.
  4. Calls `merge_snapshots()` to union by HLC.
  5. Writes the merged fragments back into BrainStore.
  6. Records last-sync timestamps in brain_meta.

Live runtime — runs as a thread inside the daemon process. Per
ANTI-LIE MANDATE this is NOT a test fixture; it's the actual worker
that ships.

Public surface:
    from personal_brain.sync_worker import SyncWorker
    worker = SyncWorker(store, transport, interval_s=300)
    worker.start()        # spawns daemon thread
    worker.tick()          # run one sync cycle synchronously (test/CLI)
    worker.stop()          # graceful shutdown
    worker.status()        # last-sync ts, pending count, error count
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .hlc import device_clock
from .models import Fragment, FragmentKind, Scope, Skill
from .storage import BrainStore
from .sync import (
    MergeResult,
    Transport,
    merge_snapshots,
    snapshot_from_store,
    stamp_with_hlc,
)


_META_KEY_LAST_SYNC = "sync_worker.last_sync_ts"
_META_KEY_LAST_RESULT = "sync_worker.last_result_json"
_META_KEY_ERRORS = "sync_worker.error_count"


# ─────────────────────── snapshot helpers ─────────────────────────────


def _scoped_fragments(
    store: BrainStore, scopes: list[Scope], owner_user: Optional[str],
) -> list[dict[str, Any]]:
    """Pull all fragments at the given scopes as plain dicts ready to
    serialise. Uses search_fragments with a wildcard query."""
    out: list[dict[str, Any]] = []
    # `*` doesn't work in FTS5; iterate kinds + each scope
    for scope in scopes:
        # Use scope-only filter with a permissive text query that the
        # FTS5 trigger should always match (every text starts with at
        # least one tokenisable word)
        rows = store._conn.execute(
            """
            SELECT * FROM fragments
            WHERE scope = ?
              AND (? IS NULL OR scope != 'user' OR owner_user = ?)
            """,
            (scope.value, owner_user, owner_user),
        ).fetchall()
        for row in rows:
            d = {k: row[k] for k in row.keys()}
            # Re-shape into Fragment-dict form (provenance is JSON string)
            try:
                prov = json.loads(d.pop("provenance_json", "{}"))
            except Exception:
                prov = {}
            d["provenance"] = prov
            extra = d.pop("extra_json", None)
            if extra:
                try:
                    d["extra"] = json.loads(extra)
                except Exception:
                    d["extra"] = {}
            d.pop("embedding_blob", None)  # don't sync raw embeddings
            d.pop("rowid", None)
            d.pop("created_at", None)
            d.pop("updated_at", None)
            out.append(d)
    return out


def _scoped_skills(
    store: BrainStore, scopes: list[Scope], owner_user: Optional[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for scope in scopes:
        rows = store._conn.execute(
            """
            SELECT * FROM skills
            WHERE scope = ?
              AND (? IS NULL OR scope != 'user' OR owner_user = ?)
            """,
            (scope.value, owner_user, owner_user),
        ).fetchall()
        for row in rows:
            d = {k: row[k] for k in row.keys()}
            for jcol in (
                "triggers_json", "requires_mcps_json",
                "requires_secrets_json", "examples_json",
                "eval_queries_json",
            ):
                key = jcol[:-5]
                val = d.pop(jcol, None)
                if val:
                    try:
                        d[key] = json.loads(val)
                    except Exception:
                        d[key] = []
                else:
                    d[key] = []
            prov = d.pop("provenance_json", None)
            if prov:
                try:
                    d["provenance"] = json.loads(prov)
                except Exception:
                    d["provenance"] = {}
            d.pop("embedding_blob", None)
            out.append(d)
    return out


# ─────────────────────── worker ─────────────────────────────────────────


@dataclass
class SyncCycleResult:
    """One tick's outcome."""

    ok: bool = True
    started_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    pushed_fragments: int = 0
    pushed_skills: int = 0
    remote_fragments: int = 0
    remote_skills: int = 0
    merged_fragments: int = 0
    merged_skills: int = 0
    conflicts_resolved: int = 0
    applied_to_local: int = 0
    error: Optional[str] = None
    transport_name: str = ""


class SyncWorker:
    """Background sync engine.

    Spawned by the daemon at startup when firm scope is active. Each
    tick:
      - Builds a snapshot of local firm/project-scope fragments + skills
      - Pulls the latest remote snapshot via the Transport
      - Merges by HLC (CRDT-style)
      - Writes any NEW remote fragments back into BrainStore
      - Pushes the merged snapshot back via the Transport

    Thread-safe: uses an internal Lock around tick(). External callers
    can call `tick()` synchronously for tests / manual triggers.
    """

    def __init__(
        self,
        store: BrainStore,
        transport: Transport,
        *,
        scopes: Optional[list[Scope]] = None,
        interval_s: float = 300.0,
        owner_user: Optional[str] = None,
        device_id: Optional[str] = None,
    ):
        self.store = store
        self.transport = transport
        self.scopes = scopes or [Scope.FIRM, Scope.PROJECT]
        self.interval_s = max(5.0, interval_s)
        self.owner_user = owner_user
        self.device_id = device_id or "device-default"
        self._tick_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_result: Optional[SyncCycleResult] = None
        self._cycle_count = 0
        self._error_count = 0

    # ── lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="brain-sync-worker", daemon=True,
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
                self._error_count += 1
            # Sleep in small increments so stop() is responsive
            slept = 0.0
            while slept < self.interval_s and not self._stop_event.is_set():
                time.sleep(min(0.5, self.interval_s - slept))
                slept += 0.5

    # ── one cycle ───────────────────────────────────────────────────

    def tick(self) -> SyncCycleResult:
        """Run one sync cycle. Returns the result. Thread-safe."""
        with self._tick_lock:
            result = SyncCycleResult(
                transport_name=getattr(self.transport, "name", "unknown"),
            )
            t0 = time.perf_counter()
            try:
                # 1. Local snapshot
                fragments = _scoped_fragments(
                    self.store, self.scopes, self.owner_user,
                )
                skills = _scoped_skills(
                    self.store, self.scopes, self.owner_user,
                )
                clock = device_clock()
                for item in fragments:
                    stamp_with_hlc(item, clock=clock)
                for item in skills:
                    stamp_with_hlc(item, clock=clock)
                local_snap = snapshot_from_store(
                    lambda: (len(fragments), len(skills)),
                    fragments, skills,
                    device_id=self.device_id,
                )
                result.pushed_fragments = len(fragments)
                result.pushed_skills = len(skills)

                # 2. Pull
                remote_snap = self.transport.pull() or {}
                result.remote_fragments = len(remote_snap.get("fragments") or [])
                result.remote_skills = len(remote_snap.get("skills") or [])

                # 3. Merge
                merged, mres = merge_snapshots(local_snap, remote_snap)
                result.merged_fragments = mres.fragments
                result.merged_skills = mres.skills
                result.conflicts_resolved = mres.conflicts_resolved

                # 4. Apply new-to-local items into BrainStore
                local_ids = {f.get("id") for f in fragments}
                local_skill_ids = {s.get("id") for s in skills}
                applied = 0
                for f in merged.get("fragments") or []:
                    fid = f.get("id")
                    if not fid or fid in local_ids:
                        continue
                    try:
                        self._write_remote_fragment_into_store(f)
                        applied += 1
                    except Exception:
                        pass
                for s in merged.get("skills") or []:
                    sid = s.get("id")
                    if not sid or sid in local_skill_ids:
                        continue
                    try:
                        self._write_remote_skill_into_store(s)
                        applied += 1
                    except Exception:
                        pass
                result.applied_to_local = applied

                # 5. Push merged
                self.transport.push(merged)

                result.duration_ms = (time.perf_counter() - t0) * 1000.0
                self._last_result = result
                self._cycle_count += 1
                self._persist_status(result)
                return result
            except Exception as ex:
                self._error_count += 1
                result.ok = False
                result.error = f"{type(ex).__name__}: {ex}"
                result.duration_ms = (time.perf_counter() - t0) * 1000.0
                self._last_result = result
                self._persist_status(result)
                return result

    # ── status ──────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "interval_s": self.interval_s,
            "transport": getattr(self.transport, "name", "unknown"),
            "scopes": [s.value for s in self.scopes],
            "cycle_count": self._cycle_count,
            "error_count": self._error_count,
            "last_result": asdict(self._last_result) if self._last_result else None,
        }

    # ── helpers ─────────────────────────────────────────────────────

    def _write_remote_fragment_into_store(self, f: dict[str, Any]) -> None:
        """Insert a remote fragment dict into BrainStore. Coerces shape."""
        from .models import Confidence, Provenance, Visibility
        prov_dict = f.get("provenance") or {}
        if isinstance(prov_dict, str):
            try:
                prov_dict = json.loads(prov_dict)
            except Exception:
                prov_dict = {}
        # Ensure required provenance fields
        prov_dict.setdefault("contributing_agent", "sync-worker")
        prov_dict.setdefault("contributing_user",
                              f.get("owner_user") or "remote")
        try:
            prov = Provenance(**{
                k: v for k, v in prov_dict.items()
                if k in Provenance.__pydantic_fields__
            })
        except Exception:
            prov = Provenance(
                contributing_agent="sync-worker",
                contributing_user=f.get("owner_user") or "remote",
            )
        try:
            fragment = Fragment(
                id=f["id"],
                kind=FragmentKind(f.get("kind") or "fact"),
                text=f.get("text") or "",
                subject=f.get("subject"),
                predicate=f.get("predicate"),
                object=f.get("object"),
                scope=Scope(f.get("scope") or "user"),
                visibility=Visibility(f.get("visibility") or "private"),
                owner_user=f.get("owner_user") or "remote",
                project_id=f.get("project_id"),
                firm_id=f.get("firm_id"),
                confidence=Confidence(f.get("confidence") or "extracted"),
                provenance=prov,
                extra=f.get("extra") or {},
            )
            self.store.write_fragment(fragment)
        except Exception:
            pass  # malformed remote — drop quietly, log later

    def _write_remote_skill_into_store(self, s: dict[str, Any]) -> None:
        from .models import Provenance, Visibility
        prov_dict = s.get("provenance") or {}
        if isinstance(prov_dict, str):
            try:
                prov_dict = json.loads(prov_dict)
            except Exception:
                prov_dict = {}
        prov_dict.setdefault("contributing_agent", "sync-worker")
        prov_dict.setdefault("contributing_user",
                              s.get("owner_user") or "remote")
        try:
            prov = Provenance(**{
                k: v for k, v in prov_dict.items()
                if k in Provenance.__pydantic_fields__
            })
        except Exception:
            prov = Provenance(
                contributing_agent="sync-worker",
                contributing_user=s.get("owner_user") or "remote",
            )
        try:
            skill = Skill(
                id=s["id"],
                name=s["name"],
                description=s["description"],
                triggers=s.get("triggers") or [],
                requires_mcps=s.get("requires_mcps") or [],
                requires_secrets=s.get("requires_secrets") or [],
                body=s.get("body") or "",
                examples=s.get("examples") or [],
                eval_queries=s.get("eval_queries") or [],
                scope=Scope(s.get("scope") or "user"),
                visibility=Visibility(s.get("visibility") or "private"),
                owner_user=s.get("owner_user") or "remote",
                provenance=prov,
                success_count=int(s.get("success_count") or 0),
                fail_count=int(s.get("fail_count") or 0),
                honed_trials=int(s.get("honed_trials") or 0),
                honed_passed=int(s.get("honed_passed") or 0),
                side_effects=s.get("side_effects") or "pure",
            )
            self.store.upsert_skill(skill)
        except Exception:
            pass

    def _persist_status(self, result: SyncCycleResult) -> None:
        try:
            self.store.set_meta(_META_KEY_LAST_SYNC,
                                 datetime.now(timezone.utc).isoformat())
            self.store.set_meta(_META_KEY_LAST_RESULT,
                                 json.dumps(asdict(result)))
            self.store.set_meta(_META_KEY_ERRORS, str(self._error_count))
        except Exception:
            pass
