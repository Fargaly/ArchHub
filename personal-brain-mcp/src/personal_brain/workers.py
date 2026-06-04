"""Background worker supervisor — the brain's ambient ENGINE.

Per AgDR-0044 §1 + MAKE-IT-REAL-PLAN-2026-05-28 §1: the daemon registered
22 MCP tools but never started the background workers, so Sync / Publish /
Reflexion / Watchdog were all dormant. This module is the missing runtime
switch — `start_workers()` is called once at daemon boot and spins up:

  • SyncWorker      — periodic firm/project-scope CRDT sync (sync_worker.py)
  • PersonalCloudSync — periodic USER-scope sync to the ArchHub cloud per-user
                        replica, privacy-redacted (personal_cloud_sync.py). Inert
                        until the user signs in (cloud.json token).
  • PublishWorker   — periodic DP-noised federation outbox publish (publish_worker.py)
  • ReflexionWorker — drains the skill-mint queue, runs reflect_on_trace (reflexion.py)
  • Watchdog        — monitors the three threads; restarts any that died

Why a NEW module (not inlined into server.py): server.py is the contended
file in the parallel-session overhaul, and the engine-start logic is a
cohesive, independently-testable unit. `build_server` / `main` call
exactly one function here.

Toggle: set env `BRAIN_WORKERS=0` (or `off`/`false`/`no`) to keep the
engine dormant (e.g. for a pure-MCP-tool deployment or a test harness).
Default is ON — the engine runs.

Public surface:
    from personal_brain.workers import start_workers, get_supervisor
    sup = start_workers(store)              # idempotent per store
    sup.status()                            # dict of per-worker liveness
    sup.reflexion                           # the live ReflexionWorker (or None)
    sup.stop()                              # graceful shutdown of all threads

`get_supervisor(store)` returns the supervisor already bound to a store
(or None) so other modules — notably server.py's brain.skill_mint — can
enqueue work onto the live ReflexionWorker without re-creating it.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .storage import BrainStore


_TRUTHY_OFF = {"0", "off", "false", "no", "disabled"}

# One supervisor per BrainStore id(). The daemon opens exactly one store,
# so in practice there is one supervisor; keyed by id() so a second store
# (tests) gets its own and they never cross-talk.
_SUPERVISORS: dict[int, "WorkerSupervisor"] = {}
_REGISTRY_LOCK = threading.Lock()


def workers_enabled() -> bool:
    """The engine runs unless BRAIN_WORKERS is an explicit off value."""
    val = os.environ.get("BRAIN_WORKERS", "1").strip().lower()
    return val not in _TRUTHY_OFF


# ─────────────────────── watchdog ──────────────────────────────────────


class Watchdog:
    """Liveness monitor (AgDR-0044 R3). Polls each supervised worker's
    thread; if a worker thread has died (uncaught crash escaped its own
    try/except loop), the watchdog restarts it and bumps a counter so the
    failure is visible in `status()`.

    Runs as its own daemon thread. Cheap: one wake every `interval_s`.
    """

    def __init__(self, supervisor: "WorkerSupervisor", *, interval_s: float = 30.0):
        self.supervisor = supervisor
        self.interval_s = max(2.0, interval_s)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.restarts = 0
        self.ticks = 0
        self.last_tick_at: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="brain-watchdog", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.is_set():
            slept = 0.0
            while slept < self.interval_s and not self._stop.is_set():
                time.sleep(min(0.5, self.interval_s - slept))
                slept += 0.5
            if self._stop.is_set():
                break
            try:
                self.ticks += 1
                self.last_tick_at = datetime.now(timezone.utc).isoformat()
                self.restarts += self.supervisor.revive_dead()
            except Exception:
                # The watchdog must never die from a transient error.
                pass

    def status(self) -> dict[str, Any]:
        return {
            "alive": self.is_alive(),
            "interval_s": self.interval_s,
            "ticks": self.ticks,
            "restarts": self.restarts,
            "last_tick_at": self.last_tick_at,
        }


# ─────────────────────── organize worker ───────────────────────────────


class OrganizeWorker:
    """Periodic self-tidying pass — runs brain_reembed then brain_organize on
    the sync cadence so the facet map + embeddings stay current as memory
    grows. Both passes are idempotent, so a tick is safe to repeat: reembed
    only fills NULL vectors, organize only rewrites changed labels.

    reembed runs FIRST each tick so organize's centroid math + merge cosines
    operate on freshly-embedded vectors when the embedder is available.

    Mirrors the SyncWorker lifecycle (start/stop/tick/status) so the
    supervisor + watchdog treat it uniformly.
    """

    def __init__(
        self,
        store: BrainStore,
        *,
        interval_s: float = 300.0,
        owner_user: Optional[str] = None,
    ):
        self.store = store
        self.interval_s = max(5.0, interval_s)
        self.owner_user = owner_user
        self._tick_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cycle_count = 0
        self._error_count = 0
        self._last_organize: dict[str, Any] = {}
        self._last_reembed: dict[str, Any] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="brain-organize-worker", daemon=True,
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
            slept = 0.0
            while slept < self.interval_s and not self._stop_event.is_set():
                time.sleep(min(0.5, self.interval_s - slept))
                slept += 0.5

    def tick(self) -> dict[str, Any]:
        """Run one reembed+organize cycle. Thread-safe; callable directly for
        tests / manual triggers."""
        with self._tick_lock:
            from .organize import brain_organize, brain_reembed
            out: dict[str, Any] = {}
            try:
                self._last_reembed = brain_reembed(self.store)
                out["reembed"] = self._last_reembed
            except Exception as ex:  # pragma: no cover - defensive
                self._error_count += 1
                out["reembed_error"] = f"{type(ex).__name__}: {ex}"
            try:
                self._last_organize = brain_organize(
                    self.store, owner_user=self.owner_user
                )
                out["organize"] = self._last_organize
            except Exception as ex:  # pragma: no cover - defensive
                self._error_count += 1
                out["organize_error"] = f"{type(ex).__name__}: {ex}"
            self._cycle_count += 1
            return out

    def status(self) -> dict[str, Any]:
        return {
            "alive": bool(self._thread is not None and self._thread.is_alive()),
            "interval_s": self.interval_s,
            "cycle_count": self._cycle_count,
            "error_count": self._error_count,
            "last_organize": self._last_organize,
            "last_reembed": self._last_reembed,
        }


# ─────────────────────── supervisor ────────────────────────────────────


class WorkerSupervisor:
    """Owns the lifecycle of every background worker for one store.

    Construction does NOT start anything; call `.start()` (or use the
    module-level `start_workers`). Each worker is built defensively — a
    failure constructing one worker (e.g. missing optional dep) is
    recorded in `self.errors` and does not stop the others.
    """

    def __init__(
        self,
        store: BrainStore,
        *,
        sync_interval_s: float = 300.0,
        publish_interval_s: float = 6 * 3600.0,
        watchdog_interval_s: float = 30.0,
        owner_user: Optional[str] = None,
    ):
        self.store = store
        self.sync_interval_s = sync_interval_s
        self.publish_interval_s = publish_interval_s
        self.watchdog_interval_s = watchdog_interval_s
        self.owner_user = owner_user

        self.sync: Any = None          # SyncWorker (firm/project/community)
        self.personal_cloud: Any = None  # PersonalCloudSync (USER scope ⇄ cloud)
        self.publish: Any = None       # PublishWorker
        self.reflexion: Any = None     # ReflexionWorker
        self.organize: Any = None      # OrganizeWorker
        self.watchdog: Optional[Watchdog] = None

        self.errors: list[str] = []
        self.started_at: Optional[str] = None
        self._started = False
        self._lock = threading.Lock()

    # ── construction of individual workers ──────────────────────────

    def _build_sync(self) -> None:
        from .sync import JsonFileTransport
        from .models import Scope
        # Default DiskTransport co-located with the brain db, matching the
        # ARCHITECTURE LOCK "DiskTransport at .speckle/<project>/" spirit:
        # a single JSON snapshot next to brain.db. No server, fully offline.
        snap_path = self.store.path.parent / "brain-sync-snapshot.json"
        transport = JsonFileTransport(snap_path)

        # Dynamic scope: always sync FIRM + PROJECT; ALSO sync COMMUNITY
        # once this device has joined a multi-device community, so the two
        # devices on the same community converge COMMUNITY-scope fragments
        # (the `community` + `community_member` records + any shared facts).
        # Evaluated per-tick so joining/leaving takes effect without a
        # daemon restart.
        store = self.store

        def _resolve_scopes() -> list[Scope]:
            scopes = [Scope.FIRM, Scope.PROJECT]
            try:
                from .community_groups import current_community_id
                if current_community_id(store):
                    scopes.append(Scope.COMMUNITY)
            except Exception:
                pass
            return scopes

        from .sync_worker import SyncWorker
        self.sync = SyncWorker(
            self.store, transport,
            interval_s=self.sync_interval_s,
            owner_user=self.owner_user,
            scope_resolver=_resolve_scopes,
        )

    def _build_personal_cloud(self) -> None:
        """Build the PERSONAL (USER-scope) cloud-sync worker — ADDITIVE sibling
        to the firm SyncWorker above. It converges the signed-in user's
        USER-scope fragments + skills across THEIR devices through the deployed
        ArchHub cloud (POST /v1/brain/sync), privacy-redacted, per-user.

        It is ALWAYS constructed (so it can self-activate the moment a token
        appears — config is re-read each tick) but is INERT until a token
        resolves from cloud.json / env. No token → every tick is a logged
        no-op; it never touches the network and never blocks the daemon. The
        firm sync contract above is untouched.
        """
        from .personal_cloud_sync import PersonalCloudSync
        self.personal_cloud = PersonalCloudSync(
            self.store,
            owner_user=self.owner_user,
            interval_s=self.sync_interval_s,
        )

    def _build_publish(self) -> None:
        from .federation import FederationDriver
        from .firm import current_firm_id
        try:
            firm_id = current_firm_id(self.store) or "local"
        except Exception:
            firm_id = "local"
        driver = FederationDriver(
            firm_id=firm_id,
            actor_url="http://127.0.0.1:8474/actor",
            base_url="http://127.0.0.1:8474",
        )
        from .publish_worker import PublishWorker
        self.publish = PublishWorker(
            self.store, driver, interval_s=self.publish_interval_s,
        )

    def _build_reflexion(self) -> None:
        from .reflexion import ReflexionWorker
        self.reflexion = ReflexionWorker(self.store)

    def _build_organize(self) -> None:
        # Organize rides the SAME cadence as sync (default 300s) — the brain
        # re-tidies (reembed NULL vectors + facet/cluster + merge + archive)
        # every sync cycle. Idempotent, so repeated ticks are cheap no-ops
        # once the store is clean.
        self.organize = OrganizeWorker(
            self.store,
            interval_s=self.sync_interval_s,
            owner_user=self.owner_user,
        )

    # ── lifecycle ───────────────────────────────────────────────────

    def start(self) -> "WorkerSupervisor":
        with self._lock:
            if self._started:
                return self
            self._started = True
            self.started_at = datetime.now(timezone.utc).isoformat()

            for name, builder in (
                ("reflexion", self._build_reflexion),
                ("sync", self._build_sync),
                ("personal_cloud", self._build_personal_cloud),
                ("publish", self._build_publish),
                ("organize", self._build_organize),
            ):
                try:
                    builder()
                    worker = getattr(self, name)
                    if worker is not None:
                        worker.start()
                except Exception as ex:
                    self.errors.append(f"{name}: {type(ex).__name__}: {ex}")

            # Watchdog last — it supervises whatever came up.
            try:
                self.watchdog = Watchdog(
                    self, interval_s=self.watchdog_interval_s,
                )
                self.watchdog.start()
            except Exception as ex:
                self.errors.append(f"watchdog: {type(ex).__name__}: {ex}")
            return self

    def revive_dead(self) -> int:
        """Restart any worker whose thread has died. Returns count revived.
        Called by the Watchdog. The ReflexionWorker is queue-backed and
        long-lived; Sync/Publish own their own threads."""
        revived = 0
        for name, builder in (
            ("sync", self._build_sync),
            ("personal_cloud", self._build_personal_cloud),
            ("publish", self._build_publish),
            ("reflexion", self._build_reflexion),
            ("organize", self._build_organize),
        ):
            worker = getattr(self, name)
            if worker is None:
                continue
            try:
                alive = self._worker_alive(worker)
            except Exception:
                alive = True  # be conservative; don't thrash
            if not alive:
                try:
                    # Rebuild + restart (queue contents on a dead reflexion
                    # worker are lost, but that's strictly better than a
                    # permanently dead worker silently dropping all mints).
                    builder()
                    getattr(self, name).start()
                    revived += 1
                except Exception as ex:
                    self.errors.append(
                        f"revive {name}: {type(ex).__name__}: {ex}"
                    )
        return revived

    @staticmethod
    def _worker_alive(worker: Any) -> bool:
        """Uniform liveness probe across the three worker types.

        SyncWorker / PublishWorker expose `_thread`; ReflexionWorker
        exposes `_thread` + `_running`. A `status()` with `running`/`alive`
        is used when present.
        """
        st = None
        try:
            st = worker.status()
        except Exception:
            st = None
        if isinstance(st, dict):
            if "running" in st:
                return bool(st["running"])
            if "alive" in st:
                return bool(st["alive"])
        thread = getattr(worker, "_thread", None)
        return bool(thread is not None and thread.is_alive())

    def stop(self, timeout_s: float = 5.0) -> None:
        with self._lock:
            if self.watchdog is not None:
                try:
                    self.watchdog.stop(timeout_s=timeout_s)
                except Exception:
                    pass
            for name in ("sync", "personal_cloud", "publish", "reflexion", "organize"):
                worker = getattr(self, name)
                if worker is None:
                    continue
                try:
                    worker.stop(timeout_s=timeout_s)
                except Exception:
                    pass
            self._started = False

    # ── introspection ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        def _wstatus(w: Any) -> dict[str, Any]:
            if w is None:
                return {"built": False, "alive": False}
            out: dict[str, Any] = {"built": True}
            try:
                out["alive"] = self._worker_alive(w)
            except Exception:
                out["alive"] = False
            try:
                s = w.status()
                if isinstance(s, dict):
                    out.update({
                        k: s[k] for k in (
                            "cycle_count", "error_count", "interval_s",
                            "outbox_size", "transport", "signed_in",
                            "since_hlc", "kind",
                        ) if k in s
                    })
            except Exception:
                pass
            return out

        reflexion_alive = self._worker_alive(self.reflexion) if self.reflexion else False
        sync_alive = self._worker_alive(self.sync) if self.sync else False
        personal_cloud_alive = self._worker_alive(self.personal_cloud) if self.personal_cloud else False
        publish_alive = self._worker_alive(self.publish) if self.publish else False
        organize_alive = self._worker_alive(self.organize) if self.organize else False
        watchdog_alive = self.watchdog.is_alive() if self.watchdog else False
        reflexion_results = (
            len(getattr(self.reflexion, "results", []))
            if self.reflexion is not None else 0
        )
        return {
            "started": self._started,
            "started_at": self.started_at,
            "enabled": workers_enabled(),
            "errors": list(self.errors),
            "workers": {
                "sync": _wstatus(self.sync),
                "personal_cloud": _wstatus(self.personal_cloud),
                "publish": _wstatus(self.publish),
                "organize": _wstatus(self.organize),
                "reflexion": {
                    "built": self.reflexion is not None,
                    "alive": reflexion_alive,
                    "results": reflexion_results,
                },
                "watchdog": (
                    self.watchdog.status() if self.watchdog is not None
                    else {"built": False, "alive": False}
                ),
            },
            "all_alive": bool(
                self._started
                and reflexion_alive
                and sync_alive
                and personal_cloud_alive
                and publish_alive
                and organize_alive
                and watchdog_alive
            ),
        }


# ─────────────────────── module-level façade ───────────────────────────


def start_workers(
    store: BrainStore,
    *,
    sync_interval_s: float = 300.0,
    publish_interval_s: float = 6 * 3600.0,
    watchdog_interval_s: float = 30.0,
    owner_user: Optional[str] = None,
    force: bool = False,
) -> Optional[WorkerSupervisor]:
    """Start (once) the background engine for `store`. Idempotent per
    store — repeat calls return the existing supervisor.

    Returns the WorkerSupervisor, or None when disabled via BRAIN_WORKERS.
    `force=True` starts even when the env toggle is off (used by tests).
    """
    if not force and not workers_enabled():
        return None
    key = id(store)
    with _REGISTRY_LOCK:
        existing = _SUPERVISORS.get(key)
        if existing is not None and existing._started:
            return existing
        sup = WorkerSupervisor(
            store,
            sync_interval_s=sync_interval_s,
            publish_interval_s=publish_interval_s,
            watchdog_interval_s=watchdog_interval_s,
            owner_user=owner_user,
        )
        _SUPERVISORS[key] = sup
    sup.start()
    return sup


def get_supervisor(store: BrainStore) -> Optional[WorkerSupervisor]:
    """Return the supervisor bound to `store`, or None if not started."""
    return _SUPERVISORS.get(id(store))


def stop_workers(store: BrainStore, timeout_s: float = 5.0) -> None:
    """Stop + forget the supervisor for `store` (used by tests / shutdown)."""
    with _REGISTRY_LOCK:
        sup = _SUPERVISORS.pop(id(store), None)
    if sup is not None:
        sup.stop(timeout_s=timeout_s)
