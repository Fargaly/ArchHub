"""One bounded retention batch beneath the existing authenticated owner.

No schema activation, inferred draft clearance, browser identity or new worker.
The ordinary keyset is only an inventory; each candidate needs current graph
authority, page clearance and Work/runtime exclusion before any content change.
Every batch is written to the user's conversation archive before it is deleted,
and nothing here writes a graph revision.
"""
from contextlib import contextmanager
import math
import sqlite3
import time
import uuid

from .cell_authorization import AuthorizationDenied
from .conversation_archive import (ArchiveConflict, ArchiveIndexStale, archive_directory, archive_file,
    export_messages, read_archive, read_status, rebuild_index, run_record, write_status)
from .conversation_content import read_content_binding, read_content_space
from .conversation_history import _RETENTION_SECONDS, _RETENTION_VERSION
from .conversation_pages import PAGE_PROTECTION_VERSION
from .conversation_migration_activation import _authorize, _configured_target
from .universal_cell import InvalidCell
from .workshop_retention_guard import admit_conversation_retention


# A pass waits for this long after the last user action (a browser POST).
# Reads and polls do not count; they never mutate and the Studio polls.
IDLE_SECONDS = 30.0
CONVERSATIONS_PER_PASS = 8
MESSAGES_PER_PURGE = 100
RESTORE_SECONDS = 20.0
REBUILD_SECONDS = 20.0

# Wall-clock idle time alone never deletes: a clock set forward by a month would
# make every room "idle". Each pass also accumulates app-observed time: within
# one process the wall step may not exceed the monotonic step (plus slack); a
# restart credits at most RESTART_CREDIT_SECONDS of the closed period. A room is
# eligible only after 20 days of BOTH, counted from when a pass first saw its
# current activity. Delay is safe; an early deletion is not.
OBSERVED_FILE = "retention-observed.json"
SAME_PROCESS_SLACK_SECONDS = 120.0
RESTART_CREDIT_SECONDS = 72 * 3600.0
OBSERVED_FLUSH_SECONDS = 600.0
_monotonic = time.monotonic
_PROCESS = uuid.uuid4().hex


class _ObservedClock:
    def __init__(self, directory):
        self.directory = directory
        saved = read_status(directory, OBSERVED_FILE, limit=16 * 1024 * 1024) or {}
        total, wall, anchors = saved.get("total"), saved.get("wall"), saved.get("anchors")
        valid = lambda value: type(value) in (int, float) and math.isfinite(value) and value >= 0
        self.total = float(total) if valid(total) else 0.0
        self.wall = float(wall) if valid(wall) else None
        # The highest wall time ever observed. A restart credits time only
        # beyond it, so setting the clock back and forward earns nothing.
        max_wall = saved.get("max_wall")
        self.max_wall = float(max_wall) if valid(max_wall) else self.wall
        self.mono = None
        self.process = saved.get("process") if type(saved.get("process")) is str else None
        self.anchors = {root: [anchor[0], float(anchor[1])] for root, anchor in
                        (anchors.items() if type(anchors) is dict else ())
                        if type(root) is str and type(anchor) is list and len(anchor) == 2
                        and type(anchor[0]) is int and valid(anchor[1]) and anchor[1] <= self.total}
        self.dirty = self.anchors_changed = False
        self.flushed = _monotonic()

    def advance(self, wall):
        mono = _monotonic()
        if self.wall is None:
            delta = 0.0
        elif self.process == _PROCESS and self.mono is not None:
            delta = min(wall - self.wall, mono - self.mono + SAME_PROCESS_SLACK_SECONDS)
        else:
            delta = min(wall - max(self.wall, self.max_wall or self.wall), RESTART_CREDIT_SECONDS)
        self.total += max(0.0, delta)
        self.wall, self.mono, self.process = wall, mono, _PROCESS
        self.max_wall = wall if self.max_wall is None else max(self.max_wall, wall)
        self.dirty = True
        return max(0.0, delta)

    def observed_idle(self, root, revision):
        anchor = self.anchors.get(root)
        if anchor is None or anchor[0] != revision:
            self.anchors[root] = [revision, self.total]
            self.dirty = self.anchors_changed = True
            return 0.0
        return self.total - anchor[1]

    def flush(self):
        if not self.dirty or not (self.anchors_changed or _monotonic() - self.flushed >= OBSERVED_FLUSH_SECONDS):
            return
        try:
            write_status(self.directory, {"total": self.total, "wall": self.wall, "max_wall": self.max_wall,
                                          "process": self.process, "anchors": self.anchors}, OBSERVED_FILE)
        except OSError:
            return
        self.dirty = self.anchors_changed = False
        self.flushed = _monotonic()


def _observed_clock(service):
    clock = getattr(service, "_retention_observed", None)
    if clock is None:
        clock = service._retention_observed = _ObservedClock(archive_directory(service._path))
    return clock


def _pending_rebuilds(service):
    pending = getattr(service, "_archive_rebuild", None)
    if pending is None:
        pending = service._archive_rebuild = set()
    return pending


def _rebuild_indexes(service, cancelled):
    # Outside every owner lock: a stale or missing archive index is rebuilt by
    # a whole-file scan here, never inside the 2 s pass.
    history, pending = service._history, _pending_rebuilds(service)
    if history is None or service._path is None:
        return
    directory = archive_directory(service._path)
    for root in sorted(pending):
        if cancelled():
            return
        try:
            rebuild_index(archive_file(directory, root), root, history.instance_id,
                          deadline=time.monotonic() + REBUILD_SECONDS)
        except ArchiveConflict:
            pass                     # conflict file written; export refuses this room
        except (OSError, ValueError, TimeoutError):
            continue                 # retried next pass
        pending.discard(root)


def retention_policy(service):
    directory = archive_directory(service._path) if service._path is not None else None
    return {"inactive_days": _RETENTION_SECONDS // 86400,
            "conversations_per_pass": CONVERSATIONS_PER_PASS,
            "messages_per_pass": MESSAGES_PER_PURGE, "pass_seconds": 2.0, "cadence_seconds": 60,
            "idle_seconds": IDLE_SECONDS,
            "archive_folder": None if directory is None else str(directory),
            "preserved": "Conversations with Work (open or finished), open or unsaved pages, "
                         "running model or project work, or an active native reader are never removed."}


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


def _user_is_active(owner):
    last = getattr(owner, 'last_user_action_monotonic', None)
    return type(last) is float and time.monotonic() - last < IDLE_SECONDS


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

    result = dict(status='idle', inspected=0, protected=0, archived=0, purged=0, exported=0,
        next_conversation_id=after_conversation_id)
    if _user_is_active(service._owner):
        # Never on the click path: a pass holds the owner lock for its budget.
        result = {**result, 'status':'waiting-for-idle'}
    else:
        if getattr(service, "_archive_rebuild", None):
            _rebuild_indexes(service, cancelled)
            deadline = time.monotonic() + timeout_seconds
        try:
            result = _maintain(service, authentication_context, after_conversation_id,
                deadline, cancelled, check, result)
        except (TimeoutError, sqlite3.OperationalError):
            result = {**result, 'status':'deferred'}
    _record_run(service, result)
    if getattr(service, "_retention_observed", None) is not None:
        service._retention_observed.flush()   # outside the owner lock
    return result


def _record_run(service, result):
    record = run_record(result)
    service._retention_last_run = record
    if record['archived'] or record['purged'] or record['exported']:
        # Only a pass that changed content is written; an idle pass rewrites nothing.
        try:
            write_status(archive_directory(service._path), record)
        except OSError:
            pass


def _room_admission(service, owner, store, registry, authority, snapshot, history, root,
                    authentication_context):
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
                    version = history._db.execute('PRAGMA user_version').fetchone()[0]
                    if version == _RETENTION_VERSION:
                        # An install created before draft protection: enable it once,
                        # at an idle pass. Its existing rooms stay protected until
                        # their drafts are resolved; rooms created later are born tracked.
                        history.initialize_page_protection(before_commit=check)
                        return {**result, 'status':'upgraded'}
                    if version != PAGE_PROTECTION_VERSION:
                        return {**result, 'status':'not-enabled'}
                    directory = archive_directory(service._path)
                    observed = _observed_clock(service)
                    observed.advance(history._retention_now())
                    # Seek the primary key. Never filter an unbounded table scan
                    # for eligible rows; protected rows still advance this cursor.
                    rows = history._db.execute('SELECT id FROM conversations WHERE id>? ORDER BY id LIMIT ?',
                        (after_conversation_id or '', CONVERSATIONS_PER_PASS)).fetchall()
                    if not rows:
                        return {**result, 'next_conversation_id':None}
                    for row in rows:
                        check()
                        root = row[0]
                        result['inspected'] += 1
                        result['next_conversation_id'] = root
                        try:
                            status = history.retention_status(root)
                            observed_idle = observed.observed_idle(root, status['activity_revision'])
                            if (status['last_activity_at'] is None
                                    or history._retention_now() - status['last_activity_at'] < _RETENTION_SECONDS
                                    or observed_idle < _RETENTION_SECONDS):
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
                            _room_admission(service, owner, store, registry, authority, snapshot,
                                history, root, authentication_context)
                            check()

                        def cas(current):
                            return dict(expected_activity_revision=current['activity_revision'],
                                expected_archive_revision=current['archive_revision'],
                                expected_head=current['last_sequence'],
                                expected_content_generation=current['content_generation'])

                        archive = archive_file(directory, root)

                        def export(messages):
                            check()
                            result['exported'] += len(export_messages(archive, root, history.instance_id,
                                                                      messages, check=check))

                        try:
                            guard()
                            with admit_conversation_retention(owner, snapshot, root,
                                    before_commit=guard, check_budget=check) as commit_guard:
                                if status['archived_at'] is None:
                                    status = history.archive(root, **cas(status), protected=False, before_commit=commit_guard)
                                    result['archived'] += 1
                                purged = history.purge_archived(root, **cas(status), protected=False,
                                    before_commit=commit_guard, max_messages=MESSAGES_PER_PURGE,
                                    max_bytes=1024*1024, export=export)
                                result['purged'] += purged['purged']
                        except ArchiveIndexStale:
                            _pending_rebuilds(service).add(root)
                            result['status'] = 'deferred'
                            return result
                        except (AuthorizationDenied, InvalidCell, ValueError):
                            # Includes ArchiveConflict: the messages stay, the
                            # conflict file names the differing lines.
                            result['protected'] += 1
                        except (TimeoutError, sqlite3.OperationalError, OSError):
                            result['status'] = 'deferred'
                            return result
                        if result['archived'] or result['purged']:
                            result['status'] = 'changed'
                            return result  # One mutation-bearing room per tick.
                    return result


@contextmanager
def _admitted_owner(service, authentication_context):
    """Owner, graph snapshot and history for one founder-initiated archive action."""
    if authentication_context is None:
        raise AuthorizationDenied('conversation archive requires explicit authentication')
    owner = service._owner
    with owner.mutation_lock:
        service._require_live_owner()
        store, registry = owner.universal_store, owner.universal_registry
        authority = registry.authorization
        if owner.conversation_content is not service or not service.belongs_to(store, registry):
            raise AuthorizationDenied('conversation archive owner changed')
        with authority.broker._lock, authority.broker.live_context(authentication_context):
            with store._lock, store.stable_snapshot() as snapshot:
                _authorize(service, snapshot, authentication_context)
                yield owner, store, registry, authority, snapshot, service._history


def _conversation(conversation_id):
    if type(conversation_id) is not str or not conversation_id or len(conversation_id) > 4096:
        raise InvalidCell('conversation archive request names no conversation')
    return conversation_id


def conversation_retention_overview(service, *, authentication_context, limit=100):
    """Policy, last pass and the archived conversations, for Settings."""
    directory = archive_directory(service._path) if service._path is not None else None
    overview = {"policy": retention_policy(service),
                "last_run": getattr(service, '_retention_last_run', None),
                "last_change": read_status(directory) if directory is not None else None,
                "enabled": False, "archived": [], "more": False}
    with _admitted_owner(service, authentication_context) as (_owner, _store, registry, _authority,
                                                               snapshot, history):
        if history is None:
            return overview
        with history._lock, history._transaction():
            version = history._db.execute('PRAGMA user_version').fetchone()[0]
            overview["store_version"] = version
            if not history._retention_active():
                overview["reason"] = "This conversation store has no retention records yet."
                return overview
            rows = history._db.execute('SELECT conversation_id,archived_at,purged_messages,last_activity_at '
                'FROM conversation_retention WHERE archived_at IS NOT NULL OR purged_messages>0 '
                'ORDER BY conversation_id LIMIT ?', (limit + 1,)).fetchall()
            conversations = history._db.execute('SELECT count(*) FROM conversations').fetchone()[0]
            ready = (history._db.execute("SELECT count(*) FROM conversation_page_tracking WHERE state='ready'")
                     .fetchone()[0] if version == PAGE_PROTECTION_VERSION else 0)
        overview["enabled"] = version == PAGE_PROTECTION_VERSION
        overview["conversations"] = conversations
        overview["drafts_resolved"] = ready
        if version != PAGE_PROTECTION_VERSION:
            overview["reason"] = ("Retention waits for draft protection to be enabled on this "
                                  "conversation store; nothing is removed until then.")
        elif ready < conversations:
            overview["reason"] = ("%d of %d conversations still have unresolved draft pages; "
                                  "retention keeps them until their drafts are resolved." % (conversations - ready, conversations))
        overview["more"] = len(rows) > limit
        for row in rows[:limit]:
            root = row[0]
            try:
                title = read_content_space(snapshot, registry.deliberation_protocol, root).title
            except (InvalidCell, ValueError, KeyError):
                title = None
            path = archive_file(directory, root)
            overview["archived"].append({"conversation": root, "title": title,
                "archived_at": row[1], "removed_messages": row[2], "last_activity_at": row[3],
                "archive_file": str(path), "archive_exists": path.is_file()})
    return overview


def conversation_archive_location(service, conversation_id, *, authentication_context):
    """The archive file for one conversation, or the folder when none exists yet."""
    root = _conversation(conversation_id)
    with _admitted_owner(service, authentication_context):
        if service._path is None:
            raise InvalidCell('conversation content is not enabled')
        directory = archive_directory(service._path)
        path = archive_file(directory, root)
        return {"conversation": root, "path": str(path if path.is_file() else directory),
                "exists": path.is_file()}


def restore_conversation_from_archive(service, conversation_id, *, authentication_context,
                                      timeout_seconds=RESTORE_SECONDS):
    """Re-import one conversation from its archive file. Writes no graph revision."""
    root = _conversation(conversation_id)
    history = service._history
    if history is None or service._path is None:
        raise InvalidCell('conversation content is not enabled')
    path = archive_file(archive_directory(service._path), root)
    # Read the file before any lock: a large archive never holds the owner.
    messages = read_archive(path, root, history.instance_id)
    deadline = time.monotonic() + timeout_seconds
    with _admitted_owner(service, authentication_context) as (owner, store, registry, authority,
                                                               snapshot, current):
        if current is not history:
            raise AuthorizationDenied('conversation archive owner changed')
        _configured_target(service, history)

        def guard():
            if time.monotonic() >= deadline:
                raise TimeoutError('conversation restore exceeded its time budget')
            _room_admission(service, owner, store, registry, authority, snapshot, history, root,
                            authentication_context)

        guard()
        restored = 0
        status = None
        with history._bounded_operations(deadline=deadline, cancelled=lambda: False):
            for start in range(0, len(messages), MESSAGES_PER_PURGE):
                status = history.restore_archived(root, messages[start:start + MESSAGES_PER_PURGE],
                    before_commit=guard, max_messages=MESSAGES_PER_PURGE)
                restored += status["restored"]
            if status is None:
                status = history.record_activity(root, before_commit=guard)
                status["tombstones"] = None
    return {"conversation": root, "restored": restored, "archive_file": str(path),
            "remaining_removed": status.get("tombstones"), "archived_at": status["archived_at"]}