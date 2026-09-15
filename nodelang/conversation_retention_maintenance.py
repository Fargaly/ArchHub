"""One bounded retention batch beneath the existing authenticated owner.

No schema activation, inferred draft clearance, browser identity or new worker.
The ordinary keyset is only an inventory; each candidate needs current graph
authority, page clearance and Work/runtime exclusion before any content change.
"""
from contextlib import contextmanager
import math
import sqlite3
import time

from .cell_authorization import AuthorizationDenied
from .conversation_content import read_content_binding, read_content_space
from .conversation_history import _RETENTION_SECONDS
from .conversation_pages import PAGE_PROTECTION_VERSION
from .conversation_migration_activation import _authorize, _configured_target
from .universal_cell import InvalidCell
from .workshop_retention_guard import admit_conversation_retention


@contextmanager
def _short_lock(lock, check):
    check()
    if not lock.acquire(timeout=0.05):
        raise TimeoutError('retention owner is busy')
    try:
        check()
        yield
    finally:
        lock.release()


def maintain_conversation_retention(service, *, authentication_context,
        after_conversation_id=None, cancellation_event=None, timeout_seconds=2.0):
    if authentication_context is None:
        raise AuthorizationDenied('retention maintenance requires explicit process authentication')
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 2):
        raise ValueError('retention maintenance time budget is invalid')
    if after_conversation_id is not None and (type(after_conversation_id) is not str
            or not after_conversation_id or len(after_conversation_id) > 4096):
        raise ValueError('retention maintenance cursor is invalid')
    if cancellation_event is not None and not callable(getattr(cancellation_event, 'is_set', None)):
        raise ValueError('retention maintenance cancellation is invalid')
    deadline = time.monotonic() + timeout_seconds
    cancelled = lambda: cancellation_event is not None and cancellation_event.is_set()

    def check():
        if cancelled() or time.monotonic() >= deadline:
            raise TimeoutError('retention maintenance cancelled or budget exhausted')

    result = dict(status='idle', inspected=0, protected=0, archived=0, purged=0,
        next_conversation_id=after_conversation_id)
    try:
        return _maintain(service, authentication_context, after_conversation_id,
            deadline, cancelled, check, result)
    except (TimeoutError, sqlite3.OperationalError):
        return {**result, 'status':'deferred'}


def _maintain(service, authentication_context, after_conversation_id, deadline, cancelled, check, result):
    owner = service._owner
    with _short_lock(owner.mutation_lock, check):
        service._require_live_owner()
        store, registry = owner.universal_store, owner.universal_registry
        authority = registry.authorization
        if owner.conversation_content is not service or not service.belongs_to(store, registry):
            raise AuthorizationDenied('retention conversation owner changed')
        with _short_lock(authority.broker._lock, check), authority.broker.live_context(authentication_context):
            with _short_lock(store._lock, check), store.stable_snapshot() as snapshot:
                _authorize(service, snapshot, authentication_context)
                check()
                history = service._history
                if history is None:
                    return {**result, 'status':'not-enabled'}
                with _short_lock(history._lock, check), history._bounded_operations(
                        deadline=deadline, cancelled=cancelled):
                    _configured_target(service, history)
                    if history._db.execute('PRAGMA user_version').fetchone()[0] != PAGE_PROTECTION_VERSION:
                        return {**result, 'status':'not-enabled'}
                    # Seek the primary key. Never filter an unbounded table scan
                    # for eligible rows; protected rows still advance this cursor.
                    rows = history._db.execute('SELECT id FROM conversations WHERE id>? ORDER BY id LIMIT 8',
                        (after_conversation_id or '',)).fetchall()
                    if not rows:
                        return {**result, 'next_conversation_id':None}
                    for row in rows:
                        check()
                        root = row[0]
                        result['inspected'] += 1
                        result['next_conversation_id'] = root
                        try:
                            status = history.retention_status(root)
                            if (status['last_activity_at'] is None
                                    or history._retention_now() - status['last_activity_at'] < _RETENTION_SECONDS):
                                continue
                            if history.page_protection_status(root)['protected']:
                                result['protected'] += 1
                                continue
                            if status['archived_at'] is not None and history._db.execute(
                                    'SELECT 1 FROM messages WHERE conversation_id=? LIMIT 1', (root,)).fetchone() is None:
                                continue
                        except (InvalidCell, ValueError):
                            # An uncertain record protects its own history, but
                            # cannot strand every later room behind this cursor.
                            result['protected'] += 1
                            continue

                        def guard():
                            check()
                            service._require_live_owner()
                            if (owner.universal_store is not store or owner.universal_registry is not registry
                                    or owner.conversation_content is not service or service._history is not history):
                                raise AuthorizationDenied('retention owner changed')
                            _authorize(service, snapshot, authentication_context, space_root=root)
                            identity = authority.broker.resolve(authentication_context)
                            space = read_content_space(snapshot, registry.deliberation_protocol, root)
                            if identity.subject_root not in space.participant_roots:
                                raise AuthorizationDenied('retention owner is not a conversation participant')
                            binding = read_content_binding(snapshot, registry.deliberation_protocol,
                                application_root=registry.application_root, space_root=root)
                            if binding.instance_id != history.instance_id:
                                raise AuthorizationDenied('retention conversation belongs to another instance')
                            service._authorize_content_read(snapshot, registry, space_root=root,
                                authentication_context=authentication_context, principal=identity.subject_root, machine=False)
                            check()

                        def cas(current):
                            return dict(expected_activity_revision=current['activity_revision'],
                                expected_archive_revision=current['archive_revision'],
                                expected_head=current['last_sequence'],
                                expected_content_generation=current['content_generation'])

                        try:
                            guard()
                            with admit_conversation_retention(owner, snapshot, root,
                                    before_commit=guard, check_budget=check) as commit_guard:
                                if status['archived_at'] is None:
                                    status = history.archive(root, **cas(status), protected=False, before_commit=commit_guard)
                                    result['archived'] += 1
                                purged = history.purge_archived(root, **cas(status), protected=False,
                                    before_commit=commit_guard, max_messages=100, max_bytes=1024*1024)
                                result['purged'] += purged['purged']
                        except (AuthorizationDenied, InvalidCell, ValueError):
                            result['protected'] += 1
                        except (TimeoutError, sqlite3.OperationalError):
                            result['status'] = 'deferred'
                            return result
                        if result['archived'] or result['purged']:
                            result['status'] = 'changed'
                            return result  # One mutation-bearing room per tick.
                    return result
