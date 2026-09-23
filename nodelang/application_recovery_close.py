"""Preserve final owner commits before the existing application teardown.

The caller quiesces its workers and transports. This module neither starts a
runtime nor replaces current state. A failure before teardown keeps the owned
handles, SQLite reservations and runtime fence available for an explicit retry.
Failure during teardown reports the published recovery path and partial close;
it cannot promise that a closed content owner can run another authorized retry.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import math
import os
import sys
import time

from .application_recovery import _history_heads, _inventory, _lock_before
from .application_recovery_restore_files import _plain_path
from .cell_authorization import AuthorizationDenied
from .conversation_history import ConversationHistoryStore
from .conversation_migration_activation import _authorize, _configured_target, _reserve
from .universal_cell import InvalidCell, _SqliteJournal


def _inputs(directory, authentication_context, timeout_seconds):
    if authentication_context is None:
        raise AuthorizationDenied("recovery close requires an explicit authenticated context")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3600):
        raise ValueError("recovery close time budget is invalid")
    directory = Path(directory).expanduser().resolve()
    ancestor = directory
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        raise NotADirectoryError(ancestor)
    return directory, time.monotonic() + timeout_seconds


def _check(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("application recovery close time budget exhausted")


def _prepared_destination(value, backup_directory, service, store):
    """Inspect exact paths and ancestor markers, never inventory recovery folders."""
    if value is None:
        return None
    destination = _plain_path(Path(value).expanduser())
    if os.path.lexists(destination):
        raise FileExistsError("prepared recovery destination already exists: " + str(destination))
    parent = _plain_path(destination.parent)
    if not parent.is_dir():
        raise FileNotFoundError("prepared recovery destination parent is missing: " + str(parent))
    protected = [_plain_path(Path(backup_directory).expanduser()),
                 _plain_path(Path(store.database_path).parent)]
    if service._path is not None:
        protected.append(_plain_path(service._path.parent))
    for path in protected:
        if destination == path or destination in path.parents or path in destination.parents:
            raise ValueError("prepared recovery destination overlaps live or backup storage: " + str(path))
    for ancestor in destination.parents:
        if os.path.lexists(ancestor / "restoration.json"):
            raise ValueError("prepared recovery destination is inside an existing restoration: " + str(ancestor))
    return destination


@contextmanager
def _budgeted_sql(database, is_open, deadline):
    _check(deadline)
    previous = database.execute("PRAGMA busy_timeout").fetchone()[0]
    database.execute("PRAGMA busy_timeout=%d" % max(1,
        min(200, int((deadline - time.monotonic()) * 1000))))
    database.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        yield
    finally:
        if is_open():
            original = sys.exception()
            try:
                database.set_progress_handler(None, 0)
                database.execute("PRAGMA busy_timeout=%d" % previous)
            except BaseException as cleanup:
                if original is None:
                    raise
                original.add_note("Recovery close SQL setting cleanup failed: " + type(cleanup).__name__)


@contextmanager
def _owned_sources(owner, authentication_context, deadline):
    """Keep the established owner-to-history lock order without a stable view."""
    with _lock_before(owner.mutation_lock, deadline), ExitStack() as stack:
        service = owner.conversation_content
        if service._owner is not owner:
            raise InvalidCell("recovery close content belongs to another owner")
        service._require_live_owner()
        if service._pending_backup_lock_mode is not None:
            raise InvalidCell("finish the authorized backup release retry before recovery close")
        registry, store = owner.universal_registry, owner.universal_store
        broker = registry.authorization.broker
        stack.enter_context(_lock_before(broker._lock, deadline))
        stack.enter_context(broker.live_context(authentication_context))
        stack.enter_context(_lock_before(store._lock, deadline))
        journal = store._journal
        if (not isinstance(journal, _SqliteJournal) or not store.has_exclusive_database_owner
                or store.supports_shared_writers or owner._runtime_fence_release is None):
            raise InvalidCell("recovery close requires its exclusively owned SQLite graph and runtime fence")
        stack.enter_context(_lock_before(journal._io_lock, deadline))
        graph = journal._connection
        if graph is None or graph.in_transaction:
            raise InvalidCell("recovery close requires an idle owned graph connection")
        stack.enter_context(_budgeted_sql(graph, lambda: journal._connection is graph, deadline))
        snapshot = store.snapshot()
        if graph.execute("SELECT MAX(revision) FROM revisions").fetchone()[0] != snapshot.revision:
            raise InvalidCell("recovery close durable graph differs from its owner")
        _authorize(service, snapshot, authentication_context)
        check = lambda: _check(deadline)
        instance_id, bindings = _inventory(graph, snapshot, registry, check)
        for root in bindings:
            _authorize(service, snapshot, authentication_context, space_root=root)
            check()
        history = None
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
            history = service._history
            stack.enter_context(_lock_before(history._lock, deadline))
            _configured_target(service, history)
            if history.instance_id != instance_id or history._db.in_transaction:
                raise InvalidCell("recovery close requires its idle admitted content handle")
            stack.enter_context(_budgeted_sql(history._db,
                lambda: service._history is history and not service._closed, deadline))
            _history_heads(history._db, instance_id, bindings, check)
        check()
        yield service, registry, store, graph, history


def _reserve_graph(graph, revision):
    """Retain raw-SQL writer exclusion on the already owned journal handle."""
    if graph.in_transaction:
        raise InvalidCell("recovery close graph reservation requires an idle connection")
    if graph.execute("PRAGMA main.locking_mode=EXCLUSIVE").fetchone()[0] != "exclusive":
        raise InvalidCell("recovery close graph exclusive ownership unavailable")
    try:
        graph.execute("BEGIN EXCLUSIVE")
        if graph.execute("SELECT MAX(revision) FROM revisions").fetchone()[0] != revision:
            raise InvalidCell("recovery close durable graph changed before reservation")
        graph.execute("COMMIT")
    except BaseException:
        if graph.in_transaction:
            graph.rollback()
        raise


def preflight_recovery_close(owner, directory, *, authentication_context, timeout_seconds,
                             prepared_recovery_directory=None):
    """Check the existing founder and sources before shutdown changes the graph."""
    supplied_directory = directory
    directory, deadline = _inputs(directory, authentication_context, timeout_seconds)
    with _owned_sources(owner, authentication_context, deadline) as sources:
        service, _registry, store, _graph, _history = sources
        _prepared_destination(prepared_recovery_directory, supplied_directory, service, store)
        _check(deadline)


def finalize_recovery_close(owner, directory, *, authentication_context, timeout_seconds,
                            prepared_recovery_directory=None):
    """Commit release, preserve both sources, then finish the existing teardown.

    Called only after the owner has proved worker/transport quiescence, revoked
    browser sessions and flushed its final snapshot. Reservation or backup
    failure deliberately leaves the primary graph/content handles open and fenced
    (the quiesced CDE auxiliary handle is closed before reservation); it never undoes
    a committed release or claims that a shutdown completed.

    An explicit prepared destination adds a full physical copy, hashing and
    retained-prefix verification through the existing restore API, within the
    same remaining time budget. The returned Path still names the immutable
    backup, and no prepared runtime is started here.
    """
    supplied_directory = directory
    directory, deadline = _inputs(directory, authentication_context, timeout_seconds)
    with _owned_sources(owner, authentication_context, deadline) as sources:
        service, registry, store, graph, history = sources
        prepared = _prepared_destination(prepared_recovery_directory, supplied_directory, service, store)
        ownership = owner.runtime_ownership_state()
        if (ownership is None or ownership[0] != registry.application_root
                or ownership[1] != owner._runtime_holder_root
                or ownership[2] not in ("draining", "released")):
            raise InvalidCell("recovery close requires this owner's drained runtime")
        # Workers are quiesced. Release the auxiliary same-database connection
        # before reserving the graph's exclusive recovery lock. Keep the main
        # graph/content handles and ownership fence on preservation failure.
        cde_storage = getattr(store, "_cde_operational_storage", None)
        if cde_storage is not None:
            cde_storage.close()
        _reserve_graph(graph, store.revision)
        if history is not None:
            # The inner backup sees EXCLUSIVE as its previous mode, so its
            # normal release cannot reopen a writer gap before handle closure.
            _reserve(history)
        _check(deadline)
        _authorize(service, store.snapshot(), authentication_context)
        owner._release_runtime_ownership()
        _check(deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("application recovery close time budget exhausted")
        recovery = service.backup_recovery(directory,
            authentication_context=authentication_context,
            timeout_seconds=remaining)
        if prepared is not None:
            prepared_published = False
            try:
                _check(deadline)
                _prepared_destination(prepared, supplied_directory, service, store)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("application recovery close time budget exhausted")
                service.prepare_recovery_restore(recovery, prepared,
                    authentication_context=authentication_context, timeout_seconds=remaining)
                prepared_published = True
                _check(deadline)
            except BaseException as error:
                error.add_note("Final recovery preserved at " + str(recovery)
                    + ("; prepared recovery published at " if prepared_published else "; preparation failed at ")
                    + str(prepared) + "; teardown not started. Owner handles and fences retained.")
                raise
        try:
            _check(deadline)
            # No finally may release resources after a preservation failure.
            # A return requires every existing teardown call to have succeeded.
            if owner.universal_checkpoint_guard is not None:
                owner.universal_checkpoint_guard.close()
            service.close()
            store.close()
            if (owner._owns_universal_checkpoint_signing_authority
                    and owner.universal_checkpoint_signing_authority is not None):
                owner.universal_checkpoint_signing_authority.store.close()
            if owner._runtime_fence_release is not None:
                owner._runtime_fence_release()
                owner._runtime_fence_release = None
        except BaseException as error:
            error.add_note("Final recovery published at " + str(recovery)
                + ("; prepared recovery published at " + str(prepared) if prepared is not None else "")
                + "; shutdown teardown incomplete. The owner may be partially closed; "
                "ordinary retry is not guaranteed.")
            raise
        return recovery
