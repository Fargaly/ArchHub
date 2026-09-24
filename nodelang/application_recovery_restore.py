"""Prepare an isolated same-instance restore through the current live owner.

This never replaces live files or starts another owner. A recovery manifest is
physical evidence, not a signature or permission. The current owner's canonical
history admits the recovered prefix; its later commits remain untouched.
"""
from contextlib import ExitStack, closing
from itertools import zip_longest
from pathlib import Path
import math
import sqlite3
import sys
import time

from .application_recovery import _copied_snapshot, _history_heads, _inventory, _lock_before
from .cell_authorization import AuthorizationDenied
from .conversation_history import ConversationHistoryStore
from .conversation_migration import _reconcile_database
from .conversation_pages import (PAGE_FIELDS, PAGE_PROTECTION_VERSION, TRACKING_FIELDS,
                                 normalize_schema_sql, page_schema_statements)
from .conversation_migration_activation import _authorize, _configured_target
from .universal_cell import InvalidCell, _SqliteJournal


_MESSAGE_COLUMNS = ("rowid,id,conversation_id,sequence,author,content,category,recipients,"
    "refs,evidence,reply_to,created_at,idempotency_key,public")
_METADATA_KEYS = {"application_root", "graph_revision", "instance_id", "bindings",
    "conversation_heads", "boundary"}


def _release_read_sources(sources, pinned):
    """Attempt every owned read release, even after an earlier cleanup failure."""
    failures = []
    for database in sources:
        try:
            database.set_progress_handler(None, 0)
        except BaseException as error:
            failures.append(error)
    for database in reversed(pinned):
        try:
            if database.in_transaction:
                database.rollback()
        except BaseException as error:
            failures.append(error)
    if failures:
        first, *others = failures
        for error in others:
            first.add_note("Additional application restore release failure: " + type(error).__name__)
        raise first


def _equal_rows(source, copied, sql, parameters, check, label):
    """Compare one canonical record at a time; never retain a history in RAM."""
    missing = object()
    with closing(source.execute(sql, parameters)) as left, \
            closing(copied.execute(sql, parameters)) as right:
        for expected, actual in zip_longest(left, right, fillvalue=missing):
            check()
            if expected is missing or actual is missing or tuple(expected) != tuple(actual):
                raise InvalidCell("application restore " + label + " differs from its current owner")


# Shapes one store legitimately moves between while its content stays the same:
# retention tombstones gain a content digest at the first verified purge, and a
# v4 store gains its draft-protection tables at an idle pass. A backup taken on
# either side restores as-is; the next idle pass re-applies the upgrade.
_PAGE_OBJECTS = frozenset(statement.split()[2].split('(', 1)[0] for statement in page_schema_statements())
_TOMBSTONE_SHAPES = frozenset(normalize_schema_sql(statement) for statement in (
    ConversationHistoryStore._retention_schema_statements()[1],
    ConversationHistoryStore._with_content_digest(ConversationHistoryStore._retention_schema_statements()[1])))


def _same_shape(name, expected_sql, actual_sql):
    expected, actual = normalize_schema_sql(expected_sql), normalize_schema_sql(actual_sql)
    return expected == actual or (name == "message_tombstones"
                                  and {expected, actual} <= _TOMBSTONE_SHAPES)


def _schema(source, copied, check, *, optional=(), extra=()):
    """Structural comparison: every object has an accepted shape of its owner's.

    ``optional`` objects may be absent from the copy; ``extra`` objects may be
    present only in the copy. Anything else must match a known shape.
    """
    def rows(database):
        values = {}
        for kind, name, table, sql in database.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name LIMIT 129"):
            check()
            if len(values) >= 128:
                raise InvalidCell("application restore schema exceeds its inspection budget")
            values[name] = (kind, table, sql)
        return values
    expected, actual = rows(source), rows(copied)
    for name, (kind, table, sql) in actual.items():
        if name not in expected:
            if name in extra:
                continue
            raise InvalidCell("application restore schema differs from its current owner")
        want_kind, want_table, want_sql = expected[name]
        if (kind, table) != (want_kind, want_table) or not _same_shape(name, want_sql, sql):
            raise InvalidCell("application restore schema differs from its current owner")
    if set(expected) - set(actual) - set(optional):
        raise InvalidCell("application restore schema differs from its current owner")


def _graph_prefix(source, copied, revision, check):
    _schema(source, copied, check)
    _equal_rows(source, copied, "SELECT revision,committed_at FROM revisions WHERE revision<=? "
        "ORDER BY revision", (revision,), check, "revision prefix")
    _equal_rows(source, copied, "SELECT revision,cell_id,link0,link1,atom FROM cell_versions "
        "WHERE revision<=? ORDER BY revision,cell_id COLLATE BINARY",
        (revision,), check, "canonical graph prefix")
    # The canonical history above is exact. Its derived current index must be
    # the complete latest head, not a forged alternative sharing its revision.
    if copied.execute("""SELECT 1 FROM current_cells c WHERE NOT EXISTS (
            SELECT 1 FROM cell_versions v WHERE v.cell_id=c.cell_id AND v.revision=c.revision
            AND v.link0 IS c.link0 AND v.link1 IS c.link1 AND v.atom IS c.atom)
            OR EXISTS (SELECT 1 FROM cell_versions newer WHERE newer.cell_id=c.cell_id
            AND newer.revision>c.revision) LIMIT 1""").fetchone():
        raise InvalidCell("application restore current graph index differs from canonical history")
    if copied.execute("""SELECT 1 FROM cell_versions v WHERE NOT EXISTS (
            SELECT 1 FROM current_cells c WHERE c.cell_id=v.cell_id)
            AND NOT EXISTS (SELECT 1 FROM cell_versions newer WHERE newer.cell_id=v.cell_id
            AND newer.revision>v.revision) LIMIT 1""").fetchone():
        raise InvalidCell("application restore current graph index is incomplete")
    check()


def _ordinary_prefix(source, copied, instance_id, bindings, check, deadline):
    version = copied.execute("PRAGMA user_version").fetchone()[0]
    owner_version = source.execute("PRAGMA user_version").fetchone()[0]
    if owner_version != version and {owner_version, version} != {4, PAGE_PROTECTION_VERSION}:
        raise InvalidCell("application restore history version differs from its current owner")
    # A fresh ordinary store may predate later migration ownership tables.
    # Existing records from those tables must still match if they were copied.
    # A v4 backup of a store upgraded since (or the reverse) differs only by the
    # draft-protection objects, which the next idle pass re-creates.
    optional = ("migration_staging", "migration_publications")
    extra = ()
    if version == 4 and owner_version == PAGE_PROTECTION_VERSION:
        optional += tuple(_PAGE_OBJECTS)
    elif version == PAGE_PROTECTION_VERSION and owner_version == 4:
        extra = tuple(_PAGE_OBJECTS)
    _schema(source, copied, check, optional=optional, extra=extra)
    heads = _history_heads(copied, instance_id, bindings, check)
    if version == PAGE_PROTECTION_VERSION and owner_version == PAGE_PROTECTION_VERSION:
        # Page protection is current safety state, not a message prefix. Compare
        # both complete tables, including conversations absent from this copy,
        # so restoring cannot forget later drafts or unknown tracking state.
        _equal_rows(source, copied, "SELECT " + ','.join(PAGE_FIELDS) +
            " FROM conversation_pages ORDER BY conversation_id COLLATE BINARY,page_id COLLATE BINARY",
            (), check, "page protection rows")
        _equal_rows(source, copied, "SELECT " + ','.join(TRACKING_FIELDS) +
            " FROM conversation_page_tracking ORDER BY conversation_id COLLATE BINARY",
            (), check, "page protection tracking")
    # Compare the columns both shapes hold; the content digest only when both do.
    tombstone_columns = "conversation_id,sequence,message_digest,idempotency_digest"
    if version in (4, PAGE_PROTECTION_VERSION) and all("content_digest" in [row[1] for row in
            database.execute("PRAGMA table_info(message_tombstones)")] for database in (source, copied)):
        tombstone_columns += ",content_digest"
    for root, head in heads.items():
        current = source.execute("SELECT last_sequence FROM conversations WHERE id=?", (root,)).fetchone()
        if current is None or type(current[0]) is not int or current[0] < head:
            raise InvalidCell("application restore content is not a retained conversation prefix")
        _equal_rows(source, copied, "SELECT " + _MESSAGE_COLUMNS + " FROM messages "
            "WHERE conversation_id=? AND sequence<=? ORDER BY sequence",
            (root, head), check, "message prefix")
        if version in (4, PAGE_PROTECTION_VERSION):
            # A recovery must not resurrect deleted bodies, forget replay
            # tombstones, or reset a more recent owner activity/archive state.
            # A backup predating those changes needs a fresh compatible capture.
            _equal_rows(source, copied, "SELECT * FROM conversation_retention WHERE conversation_id=?",
                (root,), check, "conversation lifecycle state")
            _equal_rows(source, copied, "SELECT " + tombstone_columns + " FROM message_tombstones "
                "WHERE conversation_id=? AND sequence<=? ORDER BY sequence",
                (root, head), check, "retained tombstone prefix")
    for table in ("migration_staging", "migration_publications"):
        if copied.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)).fetchone():
            if table == "migration_staging":
                _equal_rows(source, copied, "SELECT * FROM migration_staging ORDER BY singleton",
                    (), check, "migration staging evidence")
            else:
                for (root,) in copied.execute("SELECT conversation_id FROM migration_publications"):
                    check()
                    _equal_rows(source, copied, "SELECT * FROM migration_publications WHERE conversation_id=?",
                        (root,), check, "migration publication evidence")
    _reconcile_database(copied, deadline)
    check()
    return heads


def prepare_owner_recovery_restore(service, recovery_directory, destination, *,
                                   authentication_context, timeout_seconds=30.0):
    """Publish a new isolated restore directory using normal configured names.

    This operation requires the current owner's trusted graph/content history.
    Offline disaster recovery and in-place rollback require their separate
    admission/compatibility path. No permission is taken from restored policies.
    The deadline is cooperative across locks, SQL and chunked file work.
    """
    from .application_recovery_restore_files import prepare_application_restore

    if authentication_context is None:
        raise AuthorizationDenied("application restore requires an explicit authenticated context")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3600):
        raise ValueError("application restore time budget is invalid")
    deadline = time.monotonic() + timeout_seconds

    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError("application restore time budget exhausted")

    owner = service._owner
    with _lock_before(owner.mutation_lock, deadline):
        service._require_live_owner()
        if service._pending_backup_lock_mode is not None:
            raise InvalidCell("finish the authorized backup release retry before restoring")
        registry, store = owner.universal_registry, owner.universal_store
        broker = registry.authorization.broker
        with _lock_before(broker._lock, deadline), broker.live_context(authentication_context), \
                _lock_before(store._lock, deadline), store.stable_snapshot() as current:
            _authorize(service, current, authentication_context)
            check()
            journal = store._journal
            if not isinstance(journal, _SqliteJournal):
                raise InvalidCell("application restore requires an exclusively owned SQLite graph")
            with _lock_before(journal._io_lock, deadline), ExitStack() as stack:
                graph, history = journal._connection, None
                sources = [graph]
                pinned = []
                released = False
                try:
                    if graph.in_transaction:
                        raise InvalidCell("application restore requires an idle graph connection")
                    graph.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                    graph.execute("BEGIN")
                    pinned.append(graph)
                    if graph.execute("SELECT MAX(revision) FROM revisions").fetchone()[0] != current.revision:
                        raise InvalidCell("application restore durable graph differs from its owner")
                    instance_id, bindings = _inventory(graph, current, registry, check)
                    output_names = {"graph": Path(journal.local_path).name}
                    for root in bindings:
                        _authorize(service, current, authentication_context, space_root=root)
                        check()
                    if instance_id is None:
                        if service._history is not None or service._path is not None and service._path.exists():
                            raise InvalidCell("unadmitted ordinary history requires migration recovery")
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
                        if history.instance_id != instance_id or history._db.in_transaction:
                            raise InvalidCell("application restore requires its idle admitted history handle")
                        sources.append(history._db)
                        history._db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                        history._db.execute("BEGIN")
                        pinned.append(history._db)
                        _history_heads(history._db, instance_id, bindings, check)
                        output_names["content"] = service._path.name

                    def verify(paths, manifest, check_files):
                        metadata = manifest["metadata"]
                        if type(metadata) is not dict or set(metadata) != _METADATA_KEYS:
                            raise InvalidCell("application restore snapshot metadata is unsupported")
                        for key in ("bindings", "conversation_heads"):
                            values = metadata[key]
                            if type(values) is not dict or len(values) > 4096 or any(
                                    type(root) is not str or not root for root in values):
                                raise InvalidCell("application restore snapshot inventory is invalid")
                        if any(type(value) is not str or not value
                                for value in metadata["bindings"].values()) or any(
                                type(value) is not int or value < 0
                                for value in metadata["conversation_heads"].values()):
                            raise InvalidCell("application restore snapshot inventory values are invalid")
                        if metadata["application_root"] != registry.application_root or (
                                metadata["instance_id"] != instance_id or
                                metadata["boundary"] != "committed-owner-snapshot"):
                            raise InvalidCell("application restore snapshot belongs to another instance or scope")
                        revision = metadata["graph_revision"]
                        if type(revision) is not int or not 0 <= revision <= current.revision:
                            raise InvalidCell("application restore graph revision is outside the retained history")
                        with closing(sqlite3.connect(paths["graph"].as_uri() + "?mode=ro",
                                uri=True, timeout=0.2)) as recovered:
                            recovered.execute("PRAGMA cache_size=-1024")
                            recovered.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                            snapshot = _copied_snapshot(recovered, revision)
                            _graph_prefix(graph, recovered, revision, check_files)
                            recovered_instance, recovered_bindings = _inventory(
                                recovered, snapshot, registry, check_files)
                        if recovered_instance != instance_id or recovered_bindings != metadata["bindings"]:
                            raise InvalidCell("application restore graph bindings differ from its snapshot evidence")
                        if history is None:
                            if set(paths) != {"graph"} or metadata["conversation_heads"] != {}:
                                raise InvalidCell("application restore legacy graph has unexpected content")
                        else:
                            if set(paths) != {"graph", "content"}:
                                raise InvalidCell("application restore is missing ordinary content")
                            with closing(sqlite3.connect(paths["content"].as_uri() + "?mode=rw",
                                    uri=True, timeout=0.2, isolation_level=None)) as recovered_history:
                                recovered_history.execute("PRAGMA cache_size=-1024")
                                recovered_history.set_progress_handler(
                                    lambda: int(time.monotonic() >= deadline), 1000)
                                heads = _ordinary_prefix(history._db, recovered_history, instance_id,
                                    recovered_bindings, check_files, deadline)
                            if heads != metadata["conversation_heads"]:
                                raise InvalidCell("application restore content heads differ from its snapshot evidence")
                        check_files()

                    def before_publish():
                        nonlocal released
                        service._require_live_owner()
                        if history is not None:
                            _configured_target(service, history)
                        check()
                        _release_read_sources(sources, pinned)
                        released = True
                        _authorize(service, current, authentication_context)
                        check()
                        for root in bindings:
                            _authorize(service, current, authentication_context, space_root=root)
                            check()

                    return prepare_application_restore(recovery_directory, destination,
                        output_names=output_names, verify_copies=verify,
                        before_publish=before_publish, deadline=deadline)
                finally:
                    if not released:
                        original = sys.exception()
                        try:
                            _release_read_sources(sources, pinned)
                        except BaseException as cleanup:
                            if original is None:
                                raise
                            original.add_note("Application restore source release failed: " + type(cleanup).__name__)
