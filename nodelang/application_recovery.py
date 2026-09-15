"""Coordinated local recovery beneath the existing application owner.

The graph admits the ordinary store and its conversations. Recovery metadata
describes the copied files; it cannot admit another instance or grant access.
The launcher calls this after construction and before starting its hosts. It is
not a pristine pre-boot or pre-update snapshot.
"""
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
import math
import sqlite3
import sys
import time
import uuid

from .cell_authorization import AuthorizationDenied
from .cell_deliberation import _one, _optional, read_deliberation_space
from .cell_protocols import read_relation
from .conversation_content import (
    APPLICATION_BINDING_BUDGET, CONTROL_BUDGET, _instance_id, read_content_binding,
)
from .conversation_history import ConversationHistoryStore, _APP_ID, _VERSION, _RETENTION_VERSION
from .conversation_migration import _reconcile_database
from .conversation_pages import PAGE_PROTECTION_VERSION, validate_page_schema
from .conversation_migration_activation import (
    _authorize, _configured_target, _reserve, _restore_locking_mode,
)
from .universal_cell import (
    InvalidCell, Snapshot, _HeadRowReader, _LazyHeadCellMap, _SqliteJournal,
)


MAX_CONVERSATIONS = 4096


@contextmanager
def _lock_before(lock, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not lock.acquire(timeout=remaining):
        raise TimeoutError("application recovery ownership wait exhausted its time budget")
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("application recovery ownership wait exhausted its time budget")
        yield
    finally:
        lock.release()


def _inventory(database, snapshot, registry, check):
    """Discover binding incidences, then interpret their actual graph relations.

    This bounded physical scan is not an alternate catalogue or authority.
    Detached historical incidences do not make their old binding current.
    """
    protocol, application = registry.deliberation_protocol, registry.application_root
    members = read_relation(snapshot, application, budget=APPLICATION_BINDING_BUDGET)
    instance_root = _optional(members, protocol.role("scope-content-instance"),
        "application content instance")
    instance_id = None if instance_root is None else _instance_id(snapshot, instance_root)
    bindings, seen = {}, set()
    cursor = database.execute("SELECT link1 FROM current_cells WHERE link0=?",
        (protocol.role("space-content-store"),))
    try:
        for row in cursor:
            check()
            root = row[0]
            if root in seen:
                continue
            seen.add(root)
            if len(seen) > MAX_CONVERSATIONS:
                raise InvalidCell("application recovery binding inventory exceeds its budget")
            relation = read_relation(snapshot, root, budget=8)
            space_root = _one(relation, protocol.role("content-space"), "content conversation")
            scope = _one(relation, protocol.role("content-scope"), "content scope")
            space = read_deliberation_space(snapshot, protocol, space_root, budget=CONTROL_BUDGET)
            if space.content_store_root != root:
                continue
            if scope != application:
                raise InvalidCell("application recovery contains another ordinary content scope")
            binding = read_content_binding(snapshot, protocol,
                application_root=application, space_root=space_root)
            if binding.instance_id != instance_id:
                raise InvalidCell("application recovery content instance mismatch")
            bindings[space_root] = binding.root_id
    finally:
        cursor.close()
    check()
    return instance_id, bindings


def _history_heads(database, instance_id, bindings, check):
    version = database.execute("PRAGMA user_version").fetchone()[0]
    if (database.execute("PRAGMA application_id").fetchone()[0] != _APP_ID or
            version not in (_VERSION, _RETENTION_VERSION, PAGE_PROTECTION_VERSION)):
        raise InvalidCell("application recovery history format is unsupported")
    if version == PAGE_PROTECTION_VERSION:
        validate_page_schema(database)
    elif database.execute("SELECT 1 FROM sqlite_master WHERE name IN "
            "('conversation_pages','conversation_page_tracking','conversation_pages_protected') "
            "OR tbl_name IN ('conversation_pages','conversation_page_tracking') LIMIT 1").fetchone():
        raise InvalidCell("application recovery page protection objects have an older schema version")
    identity = database.execute("SELECT instance_id FROM history_identity WHERE singleton=1").fetchone()
    if identity is None or identity[0] != instance_id:
        raise InvalidCell("application recovery history instance mismatch")
    heads = {}
    for root, head in database.execute(
            "SELECT id,last_sequence FROM conversations ORDER BY id LIMIT ?", (MAX_CONVERSATIONS + 1,)):
        check()
        if len(heads) >= MAX_CONVERSATIONS or type(head) is not int or head < 0:
            raise InvalidCell("application recovery conversation head is invalid or exceeds budget")
        heads[root] = head
    if set(bindings) - heads.keys():
        raise InvalidCell("application recovery is missing an admitted conversation")
    return heads


def _copied_snapshot(database, revision):
    if database.execute("SELECT MAX(revision) FROM revisions").fetchone()[0] != revision:
        raise InvalidCell("application recovery graph revision changed")
    count = database.execute("SELECT count(*) FROM current_cells").fetchone()[0]
    return Snapshot(revision, _LazyHeadCellMap(_HeadRowReader(database,
        base_revision=revision), base_count=count))


def backup_application_recovery(service, directory, *, authentication_context,
                                timeout_seconds=2.0):
    """Internal founder maintenance; no route, worker or implicit authentication.

    Hold owner -> broker -> graph -> journal -> history. Use the actual owned
    SQLite handles, not replacement handles opened from caller-supplied paths.
    Reserve content before pinning either committed source. Keep both fixed
    through copy/verification; release retained content locking before publish.
    The cooperative deadline bounds lock waits, SQL and copy/hash chunks.
    Synchronous authority evaluation and filesystem calls finish before their
    next deadline check; this is not a hard real-time scheduling guarantee.
    """
    from .application_recovery_files import publish_application_recovery

    if authentication_context is None:
        raise AuthorizationDenied("application recovery requires an explicit authenticated context")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3600):
        raise ValueError("application recovery time budget is invalid")
    deadline = time.monotonic() + timeout_seconds

    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError("application recovery time budget exhausted")

    owner = service._owner
    with _lock_before(owner.mutation_lock, deadline):
        service._require_live_owner()
        registry, store = owner.universal_registry, owner.universal_store
        with _lock_before(registry.authorization.broker._lock, deadline), \
                registry.authorization.broker.live_context(authentication_context):
            with _lock_before(store._lock, deadline), store.stable_snapshot() as snapshot:
                _authorize(service, snapshot, authentication_context)
                check()
                journal = store._journal
                if not isinstance(journal, _SqliteJournal):
                    raise InvalidCell("application recovery requires an exclusively owned SQLite graph")
                with _lock_before(journal._io_lock, deadline), ExitStack() as stack:
                    graph = journal._connection
                    if graph.in_transaction:
                        raise InvalidCell("application recovery requires an idle graph connection")
                    history, previous_mode, previous_busy = None, None, None
                    released = False
                    sources = {"graph": graph}
                    graph.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                    stack.callback(graph.set_progress_handler, None, 0)
                    try:
                        # Inventory and admission traverse the shared reader too.
                        # Cover their transactions before the first bounded SQL;
                        # cleanup disables our deadline handler before rollback.
                        if graph.execute("SELECT MAX(revision) FROM revisions").fetchone()[0] != snapshot.revision:
                            raise InvalidCell("application recovery durable graph differs from its owner")
                        instance_id, bindings = _inventory(graph, snapshot, registry, check)
                        for root in bindings:
                            _authorize(service, snapshot, authentication_context, space_root=root)
                            check()
                        if instance_id is None:
                            if service._history is not None or service._path is not None and service._path.exists():
                                raise InvalidCell("unadmitted ordinary history requires migration recovery")
                            heads = {}
                        else:
                            if service._path is None or not service._path.is_file():
                                raise FileNotFoundError("admitted conversation database is missing")
                            if service._history is None:
                                service._history = ConversationHistoryStore(service._path,
                                    instance_id=instance_id, create=False,
                                    busy_timeout_seconds=min(0.2, max(0, deadline - time.monotonic())))
                                check()
                            history = service._history
                            stack.enter_context(_lock_before(history._lock, deadline))
                            _configured_target(service, history)
                            check()
                            if history.instance_id != instance_id:
                                raise InvalidCell("application recovery owned history instance mismatch")
                            if service._pending_backup_lock_mode is not None:
                                _restore_locking_mode(history, service._pending_backup_lock_mode)
                                service._pending_backup_lock_mode = None
                            previous_busy = history._db.execute("PRAGMA busy_timeout").fetchone()[0]
                            history._db.execute("PRAGMA busy_timeout=%d" % max(1,
                                min(200, int((deadline - time.monotonic()) * 1000))))
                            previous_mode = history._db.execute("PRAGMA main.locking_mode").fetchone()[0]
                            history._db.set_progress_handler(
                                lambda: int(time.monotonic() >= deadline), 1000)
                            _reserve(history)
                            sources["content"] = history._db
                            heads = _history_heads(history._db, instance_id, bindings, check)
                        for source in sources.values():
                            source.execute("BEGIN")
                            source.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
                        check()

                        def release_sources():
                            nonlocal released
                            for source in sources.values():
                                source.set_progress_handler(None, 0)
                                if source.in_transaction:
                                    source.rollback()
                            if history is not None and previous_mode is not None:
                                _restore_locking_mode(history, previous_mode)
                                service._pending_backup_lock_mode = None
                            if history is not None and previous_busy is not None:
                                history._db.execute("PRAGMA busy_timeout=%d" % previous_busy)
                            released = True

                        def verify(paths, check_copy):
                            with closing(sqlite3.connect(Path(paths["graph"]).as_uri() + "?mode=ro",
                                    uri=True, timeout=0.2)) as copied_graph:
                                copied_graph.execute("PRAGMA cache_size=-1024")
                                copied_graph.set_progress_handler(
                                    lambda: int(time.monotonic() >= deadline), 1000)
                                copied = _copied_snapshot(copied_graph, snapshot.revision)
                                if _inventory(copied_graph, copied, registry, check_copy) != (instance_id, bindings):
                                    raise InvalidCell("application recovery copied binding correspondence changed")
                            if history is not None:
                                with closing(sqlite3.connect(Path(paths["content"]).as_uri() + "?mode=rw",
                                        uri=True, timeout=0.2, isolation_level=None)) as copied_history:
                                    copied_history.execute("PRAGMA cache_size=-1024")
                                    copied_history.set_progress_handler(
                                        lambda: int(time.monotonic() >= deadline), 1000)
                                    if (copied_history.execute("PRAGMA user_version").fetchone()[0] !=
                                            history._db.execute("PRAGMA user_version").fetchone()[0]):
                                        raise InvalidCell("application recovery copied history version changed")
                                    if _history_heads(copied_history, instance_id, bindings, check_copy) != heads:
                                        raise InvalidCell("application recovery copied history heads changed")
                                    _reconcile_database(copied_history, deadline)
                            check_copy()
                            return {"application_root": registry.application_root,
                                "graph_revision": snapshot.revision, "instance_id": instance_id,
                                "bindings": bindings, "conversation_heads": heads,
                                "boundary": "committed-owner-snapshot"}

                        def before_publish():
                            service._require_live_owner()
                            if history is not None:
                                _configured_target(service, history)
                            check()
                            release_sources()
                            _authorize(service, snapshot, authentication_context)
                            check()
                            for root in bindings:
                                _authorize(service, snapshot, authentication_context, space_root=root)
                                check()

                        directory = Path(directory).resolve()
                        directory.mkdir(parents=True, exist_ok=True)
                        target = directory / ("application-recovery-" + uuid.uuid4().hex)
                        return publish_application_recovery(sources, target,
                            verify_copies=verify, before_publish=before_publish, deadline=deadline)
                    except sqlite3.OperationalError as error:
                        # SQLite reports our cooperative deadline as INTERRUPT,
                        # not TimeoutError. Keep unrelated lock/I/O failures
                        # distinct, and let the existing finally release sources.
                        if (getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT
                                and time.monotonic() >= deadline):
                            raise TimeoutError("application recovery time budget exhausted") from error
                        raise
                    finally:
                        if not released:
                            original = sys.exception()
                            try:
                                if history is not None:
                                    history._db.set_progress_handler(None, 0)
                                for source in sources.values():
                                    source.set_progress_handler(None, 0)
                                    if source.in_transaction:
                                        source.rollback()
                                if history is not None and previous_mode is not None:
                                    _restore_locking_mode(history, previous_mode)
                                    service._pending_backup_lock_mode = None
                                if history is not None and previous_busy is not None:
                                    history._db.execute("PRAGMA busy_timeout=%d" % previous_busy)
                            except BaseException as cleanup:
                                if history is not None:
                                    service._pending_backup_lock_mode = previous_mode
                                if original is not None:
                                    original.add_note("Application recovery source release failed: " + type(cleanup).__name__)
                                else:
                                    raise
