"""One bounded retention batch beneath the existing authenticated owner.

No schema activation, inferred draft clearance, browser identity or new worker.
The ordinary keyset is only an inventory; each candidate needs current graph
authority, page clearance and Work/runtime exclusion before any content change.
Every retired batch has verified cold custody. Expired catalog memberships
are detached through the authenticated graph owner before physical partition.
"""
from contextlib import closing, contextmanager, nullcontext
from collections.abc import Mapping
from datetime import datetime
import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid

from .cell_authorization import AuthorizationDenied
from .conversation_trace_shapes import _trace_family_descriptor
from .conversation_archive import (ArchiveConflict, ArchiveIndexStale, archive_directory, archive_file,
    export_messages, read_archive, read_status, rebuild_index, run_record, write_status)
from .conversation_content import read_content_binding, read_content_space
from .conversation_history import _RETENTION_SECONDS, _RETENTION_VERSION
from .conversation_pages import PAGE_PROTECTION_VERSION
from .conversation_migration_activation import _authorize, _configured_target
from .universal_cell import InvalidCell, MatchBudgetExceeded
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
def _short_lock(lock, check, *, wait_seconds: float = 0.05):
    check()
    if not lock.acquire(timeout=wait_seconds):
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
        after_conversation_id=None, cancellation_event=None, timeout_seconds=2.0, dry_run=False):
    """Explicit bounded archive maintenance, optionally a read-only inventory.

    A dry run shares the ordinary authority and preservation guards. It does
    not activate a schema, update observed activity, rebuild/export archives,
    record a pass or change content. Its cursor covers the same eight rooms;
    callers can continue until the cursor wraps to inventory a whole store.
    """
    if type(dry_run) is not bool:
        raise ValueError('retention maintenance dry-run flag is invalid')
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
    if dry_run:
        result.update(dry_run=True, eligible=[])
    if _user_is_active(service._owner):
        # Never on the click path: a pass holds the owner lock for its budget.
        result = {**result, 'status':'waiting-for-idle'}
    else:
        if not dry_run and getattr(service, "_archive_rebuild", None):
            _rebuild_indexes(service, cancelled)
            deadline = time.monotonic() + timeout_seconds
        try:
            result = _maintain(service, authentication_context, after_conversation_id,
                deadline, cancelled, check, result, dry_run=dry_run)
        except (TimeoutError, sqlite3.OperationalError) as error:
            if isinstance(error, sqlite3.OperationalError) and (
                    getattr(error, 'sqlite_errorcode', 0) & 255) not in (
                    sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT):
                raise
            result = {**result, 'status':'deferred'}
    if not dry_run:
        _record_run(service, result)
    if not dry_run and getattr(service, "_retention_observed", None) is not None:
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


def _trace_cell_digest(cell):
    digest = hashlib.sha256()
    for item in (cell.id.encode(), cell.link0.encode(), cell.link1.encode(), cell.atom):
        digest.update(len(item).to_bytes(8, 'big'))
        digest.update(item)
    return digest.hexdigest()


class _TraceReads(Mapping):
    """Persist exact dependencies while using the existing protocol readers."""
    def __init__(self, cells, history, space_root, check, owner_roots=()):
        self.cells, self.history, self.space_root, self.check = cells, history, space_root, check
        self.owner_roots = list(owner_roots)
        self.owned_ids, self.activity = set(), None

    def __getitem__(self, key):
        self.check()
        cell = self.cells[key]
        digest = _trace_cell_digest(cell)
        previous = self.history._db.execute('SELECT digest FROM trace_migration_cells WHERE conversation_id=? AND cell_id=?',
            (self.space_root, key)).fetchone()
        if previous is not None and previous[0] != digest:
            raise InvalidCell('legacy trace dependency changed during migration')
        owned = any(key == root or key.startswith(root + ':') for root in self.owner_roots)
        if owned:
            self.owned_ids.add(key)
        self.history._db.execute('INSERT INTO trace_migration_cells VALUES(?,?,?,0,?,?,0) ON CONFLICT(conversation_id,cell_id) DO UPDATE SET owned=max(owned,excluded.owned),activity_at=coalesce(excluded.activity_at,activity_at)',
            (self.space_root, key, digest, int(owned), self.activity if owned else None))
        return cell

    def __iter__(self):
        raise InvalidCell('legacy trace migration may not scan the graph')

    def __len__(self):
        return len(self.cells)


def _legacy_trace_history(service, snapshot):
    """Open only this configured owner; never scan or create another profile."""
    from .cell_protocols import read_relation
    from .conversation_content import APPLICATION_BINDING_BUDGET, _instance_id
    from .conversation_history import ConversationHistoryStore
    from .cell_deliberation import _optional
    if service._path is None:
        raise InvalidCell('legacy trace maintenance requires its configured content owner')
    registry = service._owner.universal_registry
    members = read_relation(snapshot, registry.application_root, budget=APPLICATION_BINDING_BUDGET)
    instance_root = _optional(members, registry.deliberation_protocol.role('scope-content-instance'),
                             'application content instance')
    instance = _instance_id(snapshot, instance_root) if instance_root else None
    history = service._history
    if history is not None:
        if instance is not None and history.instance_id != instance:
            raise InvalidCell('legacy trace content instance changed')
        return history
    if service._path.exists() and instance is None:
        # A previous interrupted idle pass can own the file before publishing
        # the first graph binding. Its explicit migration row proves custody.
        uri = service._path.as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as existing:
            instance = existing.execute('SELECT instance_id FROM history_identity WHERE singleton=1').fetchone()[0]
            row = existing.execute('SELECT source_authority,application_root FROM trace_owner WHERE singleton=1').fetchone()
            if row is None or tuple(row) != (service._owner.universal_store.authority_identity, registry.application_root):
                raise InvalidCell('unbound conversation file has no admitted migration custody')
    history = ConversationHistoryStore(service._path, instance_id=instance or uuid.uuid4().hex,
        create=not service._path.exists(), store=service._owner.universal_store if service._embedded else None,
        migration_custody=(service._owner.universal_store.authority_identity, registry.application_root))
    service._history = history
    return history


def _trace_message(entry, snapshot, registry):
    """Keep original identities/replies and the complete openable value payload."""
    from .conversation_migration import _record
    from .cell_value_graph import read_rooted_value_graph
    record, _, _, _ = _record(entry, snapshot)
    values = []
    for root in entry.reference_roots:
        if root.startswith('app:deliberation-payload:'):
            snapshot.cells.owner_roots.append(root)
            values.append(read_rooted_value_graph(snapshot, registry.value_graph_protocol, root))
    if values:
        receipt = dict(subject=entry.actor_root, space=entry.space_root, category=entry.category_root,
            policy=entry.policy_root, action=entry.authorization_action_root,
            rules=list(entry.authorization_rule_roots), reason=entry.authorization_reason,
            revision=snapshot.revision)
        record['content'] = '\x1eArchHub/conversation-trace/v1\n' + json.dumps(
            dict(summary=entry.content, payload=values[0] if len(values) == 1 else values, receipt=receipt),
            sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        if len(record['content'].encode()) > 16 * 1024 * 1024:
            raise InvalidCell('legacy trace envelope exceeds migration bound')
    return record, bool(values)


def _mark_trace_binding_bound(history, root):
    changed = history._db.execute("UPDATE trace_migrations SET state='bound' WHERE conversation_id=? AND state!='bound'",
        (root,)).rowcount
    if changed:
        history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
        history._db.execute('UPDATE trace_registry_state SET source_revision=-1 WHERE singleton=1')


def _publish_idle_trace_binding(service, history, snapshot, state, check, authentication_context):
    """Rewrite only the bounded control relation after durable message copy."""
    from .cell_deliberation import _optional, _terminal
    from .cell_protocols import compose_relation_cells, prepare_append_relation_members, read_relation
    from .conversation_content import (APPLICATION_BINDING_BUDGET, CONTROL_BUDGET,
        _instance_id, prepare_empty_content_binding, read_content_binding)
    from .universal_cell import overlay_read_snapshot
    registry, store = service._owner.universal_registry, service._owner.universal_store
    protocol, root = registry.deliberation_protocol, state['conversation_id']
    controls = json.loads(state['controls'])
    if len(controls) > CONTROL_BUDGET:
        raise InvalidCell('legacy trace controls exceed their bound')
    # New private chain IDs keep every old incidence and chain available for
    # cold custody. The sole existing root keeps its original semantic identity.
    rebuilt = compose_relation_cells(controls, relation_id='conversation-control:' + uuid.uuid4().hex)
    from .universal_cell import Cell
    first = rebuilt.cells[0] if len(rebuilt.cells) == 1 else rebuilt.cells[1]
    replacement = Cell(root, first.link0, first.link1, first.atom)
    creates = {cell.id: cell for cell in rebuilt.cells if cell.id != rebuilt.build.root_id}
    replaces = {root: replacement}
    candidate = overlay_read_snapshot(snapshot, create=creates.values(), replace=replaces.values())
    application = read_relation(candidate, registry.application_root, budget=APPLICATION_BINDING_BUDGET)
    instance_root = _optional(application, protocol.role('scope-content-instance'), 'application content instance')
    if instance_root is None:
        instance_root = 'conversation-instance:' + history.instance_id
        if instance_root in snapshot.cells:
            raise InvalidCell('legacy trace instance identity already exists outside its owner')
        creates[instance_root] = _terminal(instance_root, history.instance_id)
        patch = prepare_append_relation_members(candidate, registry.application_root,
            ((protocol.role('scope-content-instance'), instance_root),), budget=APPLICATION_BINDING_BUDGET)
        creates.update((cell.id, cell) for cell in patch.create)
        replaces.update((cell.id, cell) for cell in patch.replace)
        candidate = overlay_read_snapshot(snapshot, create=creates.values(), replace=replaces.values())
    elif _instance_id(candidate, instance_root) != history.instance_id:
        raise InvalidCell('legacy trace destination differs from its graph instance')
    prepared = prepare_empty_content_binding(candidate, protocol,
        application_root=registry.application_root, space_root=root)
    creates.update((cell.id, cell) for cell in prepared.create)
    for cell in prepared.replace:
        (creates if cell.id in creates else replaces)[cell.id] = cell
    prospective = overlay_read_snapshot(snapshot, create=creates.values(), replace=replaces.values())
    binding = read_content_binding(prospective, protocol, application_root=registry.application_root, space_root=root)
    with history._transaction(write=True, before_commit=check):
        history._db.execute("UPDATE trace_migrations SET state='pending',binding_root=? WHERE conversation_id=?",
            (binding.root_id, root))
    check()
    _authorize(service, snapshot, authentication_context, space_root=root)
    from . import commit_intent
    with commit_intent.declare(commit_intent.MIGRATION,
            actor=registry.authorization.subject_root,
            reason='Authenticated legacy conversation migration: publish verified content binding'):
        registry.authorization.broker.commit_authenticated(authentication_context, store, snapshot.revision,
            create=tuple(creates.values()), replace=tuple(replaces.values()))
    actual = store.snapshot()
    published = read_content_binding(actual, protocol,
        application_root=registry.application_root, space_root=root)
    retained = [(member.role_id, member.participant_id) for member in
        read_relation(actual, root, budget=CONTROL_BUDGET)
        if member.role_id != protocol.role('space-content-store')]
    if published != binding or retained != [tuple(pair) for pair in controls]:
        raise InvalidCell('legacy trace published binding or retained controls differ')
    with history._transaction(write=True):
        _mark_trace_binding_bound(history, root)
    return binding


def maintain_legacy_traces(service, *, authentication_context, space_root,
                           timeout_seconds=2.0, max_chain_cells=64, cancellation_event=None):
    """One resumable idle batch; no whole transcript walk or global pinned job.

    Only the explicit authenticated owner can invoke this internal migration.
    Source graph writes while a copy is pending refuse publication; copied data
    and the untouched legacy graph remain available for reconciliation. A kill
    after content commit resumes from its durable exact chain cursor.
    """
    from .cell_deliberation import read_deliberation_entry
    from .conversation_content import CONTROL_BUDGET, read_content_binding
    from .universal_cell import NULL_CELL_ID, Snapshot
    if authentication_context is None:
        raise AuthorizationDenied('legacy trace maintenance requires explicit process authentication')
    if type(space_root) is not str or not space_root or len(space_root) > 512:
        raise ValueError('legacy trace space is invalid')
    if type(max_chain_cells) is not int or not 1 <= max_chain_cells <= 256:
        raise ValueError('legacy trace batch is invalid')
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 2:
        raise ValueError('legacy trace time budget is invalid')
    if cancellation_event is not None and not callable(getattr(cancellation_event, 'is_set', None)):
        raise ValueError('legacy trace cancellation is invalid')
    deadline = time.monotonic() + timeout_seconds
    def check():
        if time.monotonic() >= deadline or cancellation_event is not None and cancellation_event.is_set():
            raise TimeoutError('legacy trace maintenance cancelled or budget exhausted')
    result = dict(status='copying', copied=0, inspected=0, space_root=space_root)
    step_started = None
    longest_step = float(getattr(service, '_legacy_trace_step_seconds', 0.0))
    owner = service._owner
    if _user_is_active(owner):
        return {**result, 'status': 'waiting-for-idle'}
    try:
        with _short_lock(owner.mutation_lock, check):
            service._require_live_owner()
            store, registry = owner.universal_store, owner.universal_registry
            with _short_lock(registry.authorization.broker._lock, check), registry.authorization.broker.live_context(authentication_context):
                # The existing owner/store locks exclude graph writes for this
                # bounded pass. A read pin must not span the final graph commit.
                with _short_lock(store._lock, check), nullcontext(store.snapshot()) as snapshot:
                    _authorize(service, snapshot, authentication_context, space_root=space_root)
                    history = _legacy_trace_history(service, snapshot)
                    history.initialize_trace_maintenance()
                    history.admit_trace_custody(store.authority_identity, registry.application_root)
                    with history._bounded_operations(deadline=deadline, cancelled=lambda: time.monotonic() >= deadline):
                        # Export/index commits must be durable before the live
                        # journal partitions, not nested in a history savepoint.
                        bound = history._db.execute("SELECT binding_root,copied FROM trace_migrations WHERE conversation_id=? AND state='bound'",
                            (space_root,)).fetchone()
                        if bound is not None:
                            result['copied'] = bound[1]
                            binding = read_content_binding(snapshot, registry.deliberation_protocol,
                                application_root=registry.application_root, space_root=space_root)
                            if binding.root_id != bound[0] or binding.instance_id != history.instance_id:
                                raise InvalidCell('legacy trace binding changed after publication')
                            return {**result, 'status': 'bound'}
                        with history._transaction(write=True, before_commit=check):
                            state = history._db.execute('SELECT * FROM trace_migrations WHERE conversation_id=?', (space_root,)).fetchone()
                            if state is not None:
                                result['copied'] = state['copied']
                                if state['state'] in ('bound', 'pending'):
                                    try:
                                        binding = read_content_binding(snapshot, registry.deliberation_protocol,
                                            application_root=registry.application_root, space_root=space_root)
                                    except (InvalidCell, MatchBudgetExceeded):
                                        if state['state'] == 'bound':
                                            raise
                                    else:
                                        if binding.root_id != state['binding_root'] or binding.instance_id != history.instance_id:
                                            raise InvalidCell('legacy trace binding changed after publication')
                                        if state['state'] != 'bound':
                                            _mark_trace_binding_bound(history, space_root)
                                        return {**result, 'status': 'bound'}
                                if state['source_authority'] != store.authority_identity:
                                    raise InvalidCell('legacy trace source owner changed')
                                if state['state'] == 'protected-source-changed':
                                    return {**result, 'status': 'source-changed', 'protected': 1}
                                if state['source_revision'] != snapshot.revision or state['delta_cell'] != '\uffff':
                                    # Consume only a bounded journal delta. Unrelated
                                    # user edits never restart a room's transcript.
                                    journal, _ = store.sqlite_storage()
                                    changed = journal.execute('SELECT revision,cell_id FROM cell_versions WHERE revision>? OR (revision=? AND cell_id>?) ORDER BY revision,cell_id LIMIT 257',
                                        (state['source_revision'], state['source_revision'], state['delta_cell'])).fetchall()
                                    for revision, identifier in changed[:256]:
                                        check()
                                        if history._db.execute('SELECT 1 FROM trace_migration_cells WHERE conversation_id=? AND cell_id=?', (space_root, identifier)).fetchone():
                                            history._db.execute("UPDATE trace_migrations SET state='protected-source-changed' WHERE conversation_id=?", (space_root,))
                                            return {**result, 'status': 'source-changed', 'protected': 1}
                                    if len(changed) > 256:
                                        revision, identifier = changed[255]
                                        history._db.execute('UPDATE trace_migrations SET source_revision=?,delta_cell=? WHERE conversation_id=?',
                                            (revision, identifier, space_root))
                                        return {**result, 'status': 'checking-source'}
                                    history._db.execute('UPDATE trace_migrations SET source_revision=?,delta_cell=? WHERE conversation_id=?',
                                        (snapshot.revision, '\uffff', space_root))
                            else:
                                # No already-owned content may be adopted by ID.
                                if history._db.execute('SELECT 1 FROM conversations WHERE id=?', (space_root,)).fetchone():
                                    raise InvalidCell('legacy trace destination conversation is already owned')
                                history._db.execute('INSERT INTO conversations(id) VALUES(?)', (space_root,))
                                history._db.execute('INSERT INTO trace_migrations VALUES(?,?,?,?,?,?,0,?,NULL,NULL)',
                                    (space_root, store.authority_identity, snapshot.revision, '\uffff', space_root, '[]', 'copying'))
                                state = history._db.execute('SELECT * FROM trace_migrations WHERE conversation_id=?', (space_root,)).fetchone()
                            controls, cursor = json.loads(state['controls']), state['cursor']
                            for _ in range(max_chain_cells):
                                # Commit completed entries before the hard
                                # deadline. A long multi-entry batch must not
                                # repeatedly roll back its entire useful prefix.
                                if result['inspected'] and time.monotonic() + max(0.2, longest_step * 2) >= deadline:
                                    break
                                check()
                                if cursor == NULL_CELL_ID:
                                    break
                                step_started = time.monotonic()
                                chain = snapshot.cells.get(cursor)
                                if chain is None or chain.atom:
                                    raise InvalidCell('legacy trace relation chain is malformed')
                                if history._db.execute('SELECT 1 FROM trace_migration_cells WHERE conversation_id=? AND cell_id=? AND walked=1', (space_root, cursor)).fetchone():
                                    raise InvalidCell('legacy trace relation contains a cycle')
                                history._db.execute('INSERT INTO trace_migration_cells VALUES(?,?,?,1,?,NULL,0) ON CONFLICT(conversation_id,cell_id) DO UPDATE SET walked=1',
                                    (space_root, chain.id, _trace_cell_digest(chain), int(chain.id != space_root)))
                                result['inspected'] += 1
                                if chain.link0 == NULL_CELL_ID:
                                    if chain.link1 != NULL_CELL_ID:
                                        raise InvalidCell('legacy trace empty relation has a tail')
                                    cursor = NULL_CELL_ID
                                    break
                                incidence = snapshot.cells.get(chain.link0)
                                if incidence is None or incidence.atom or incidence.link0 not in snapshot.cells or incidence.link1 not in snapshot.cells:
                                    raise InvalidCell('legacy trace incidence is malformed')
                                history._db.execute('INSERT OR IGNORE INTO trace_migration_cells VALUES(?,?,?,0,1,NULL,0)',
                                    (space_root, incidence.id, _trace_cell_digest(incidence)))
                                if incidence.link0 == registry.deliberation_protocol.role('space-entry'):
                                    tracked = Snapshot(snapshot.revision, _TraceReads(snapshot.cells, history, space_root, check, (incidence.link1,)))
                                    entry = read_deliberation_entry(tracked, registry.deliberation_protocol, incidence.link1)
                                    if entry.space_root != space_root or entry.sequence != result['copied'] + 1:
                                        raise InvalidCell('legacy trace entry sequence or space changed')
                                    activity = datetime.fromisoformat(entry.created_at.replace('Z', '+00:00')).timestamp()
                                    tracked.cells.activity = activity
                                    for identifier in tracked.cells.owned_ids:
                                        history._db.execute('UPDATE trace_migration_cells SET activity_at=? WHERE conversation_id=? AND cell_id=?',
                                            (activity, space_root, identifier))
                                    record, structured = _trace_message(entry, tracked, registry)
                                    message = history._append_in_transaction(record)
                                    if message['sequence'] != entry.sequence:
                                        raise InvalidCell('legacy trace indexed sequence differs')
                                    from .conversation_history import migration_message_digest
                                    history._db.execute('INSERT INTO trace_migration_messages VALUES(?,?,?,?)',
                                        (space_root, message['id'], migration_message_digest(message, structured), int(structured)))
                                    result['copied'] += 1
                                    history._db.execute('UPDATE trace_migrations SET last_activity_at=max(coalesce(last_activity_at,?),?) WHERE conversation_id=?',
                                        (activity, activity, space_root))
                                else:
                                    if incidence.link0 == registry.deliberation_protocol.role('space-content-store'):
                                        raise InvalidCell('legacy trace space already has a content binding')
                                    controls.append((incidence.link0, incidence.link1))
                                    if len(controls) > CONTROL_BUDGET:
                                        raise InvalidCell('legacy trace controls exceed their bound')
                                cursor = chain.link1
                                longest_step = max(longest_step, time.monotonic() - step_started)
                                service._legacy_trace_step_seconds = longest_step
                                step_started = None
                            history._db.execute('UPDATE trace_migrations SET cursor=?,controls=?,copied=? WHERE conversation_id=?',
                                (cursor, json.dumps(controls), result['copied'], space_root))
                        if cursor == NULL_CELL_ID:
                            state = history._db.execute('SELECT * FROM trace_migrations WHERE conversation_id=?', (space_root,)).fetchone()
                            _publish_idle_trace_binding(service, history, snapshot, state, check, authentication_context)
                            result['status'] = 'bound'
    except (TimeoutError, sqlite3.OperationalError) as error:
        if isinstance(error, sqlite3.OperationalError) and (
                getattr(error, 'sqlite_errorcode', 0) & 255) not in (
                sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT):
            raise
        if step_started is not None:
            service._legacy_trace_step_seconds = max(longest_step, time.monotonic() - step_started)
        result['status'] = 'deferred'
        # A cancelled transaction reports only its durable cursor, never the
        # entries visited in a rolled-back batch.
        history = service._history
        if history is not None:
            with history._lock:
                row = history._db.execute('SELECT copied FROM trace_migrations WHERE conversation_id=?', (space_root,)).fetchone()
                result['copied'] = row[0] if row else 0
    return result


def maintain_legacy_trace_inventory(service, *, authentication_context, cursor=None,
                                     timeout_seconds=2.0, max_chain_cells=64,
                                     cancellation_event=None):
    """Visit registered conversation scopes without loading a graph inventory.

    The two existing canonical conversation roots and the actual Workbench
    scope chain are the sole inventory. Agent/session roots with no admitted
    conversation binding are never guessed from a name or a Cell prefix.
    Restarting the inventory is safe: per-room progress is durable in history.
    """
    from .conversation_content import CONTROL_BUDGET, read_content_binding
    from .universal_cell import NULL_CELL_ID
    if authentication_context is None:
        raise AuthorizationDenied('legacy trace inventory requires explicit process authentication')
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 2:
        raise ValueError('legacy trace inventory time budget is invalid')
    if type(max_chain_cells) is not int or not 1 <= max_chain_cells <= 256:
        raise ValueError('legacy trace inventory batch is invalid')
    owner = service._owner
    registry, store = owner.universal_registry, owner.universal_store
    state = dict(base=0, chain=registry.workshop_workbench_root, pending=None, steps=0)
    if cursor is not None:
        if (type(cursor) is not dict or set(cursor) != set(state)
                or type(cursor['base']) is not int or not 0 <= cursor['base'] <= 2
                or type(cursor['chain']) is not str or len(cursor['chain']) > 512
                or type(cursor['steps']) is not int or not 0 <= cursor['steps'] <= 100_000
                or cursor['pending'] is not None and (type(cursor['pending']) is not str or len(cursor['pending']) > 512)):
            raise ValueError('legacy trace inventory cursor is invalid')
        state.update(cursor)
    result = dict(status='inventory', inspected=0, copied=0, exported=0, moved=0,
        unsupported='unregistered trace families require explicit semantic ownership', next_cursor=state)
    if _user_is_active(owner):
        return {**result, 'status': 'waiting-for-idle'}
    deadline = time.monotonic() + timeout_seconds
    def check():
        if time.monotonic() >= deadline or cancellation_event is not None and cancellation_event.is_set():
            raise TimeoutError('legacy trace inventory cancelled or budget exhausted')
    try:
        if state['pending'] is None:
            with _short_lock(owner.mutation_lock, check), _short_lock(store._lock, check):
                snapshot = store.snapshot()
                _authorize(service, snapshot, authentication_context)
                bases = (registry.workshop_root, registry.brain_control_ledger_root)
                if state['base'] < len(bases):
                    state['pending'] = bases[state['base']]
                    state['base'] += 1
                else:
                    visited = set()
                    for _ in range(max_chain_cells):
                        check()
                        chain_id = state['chain']
                        if chain_id == NULL_CELL_ID:
                            return {**result, 'status': 'inventory-complete', 'next_cursor': None}
                        if chain_id in visited or state['steps'] >= 100_000:
                            raise InvalidCell('legacy trace inventory Workbench chain is cyclic or exceeds its bound')
                        visited.add(chain_id)
                        chain = snapshot.cells.get(chain_id)
                        if chain is None or chain.atom:
                            raise InvalidCell('legacy trace inventory Workbench chain is malformed')
                        state['steps'] += 1
                        result['inspected'] += 1
                        state['chain'] = chain.link1
                        if chain.link0 == NULL_CELL_ID:
                            if chain.link1 != NULL_CELL_ID:
                                raise InvalidCell('legacy trace inventory empty Workbench has a tail')
                            continue
                        incidence = snapshot.cells.get(chain.link0)
                        if incidence is None or incidence.atom:
                            raise InvalidCell('legacy trace inventory Workbench incidence is malformed')
                        if incidence.link0 != registry.roles['scope'] or incidence.link1 in bases:
                            continue
                        # Actual space controls precede appended history. Inspect
                        # only that bounded header, never a transcript-sized walk.
                        probe, seen, conversation = incidence.link1, set(), False
                        for _ in range(CONTROL_BUDGET):
                            check()
                            if probe == NULL_CELL_ID or probe in seen:
                                break
                            seen.add(probe)
                            cell = snapshot.cells.get(probe)
                            member = snapshot.cells.get(cell.link0) if cell is not None else None
                            if cell is None or member is None:
                                break
                            if member.link0 == registry.deliberation_protocol.role('space-title'):
                                conversation = True
                                break
                            probe = cell.link1
                        if conversation:
                            state['pending'] = incidence.link1
                            break
            if state['pending'] is None:
                return result
        root = state['pending']
        # Existing content scopes without a legacy migration row are already
        # complete. They are not adopted, duplicated, or schema-activated here.
        with _short_lock(owner.mutation_lock, check), _short_lock(store._lock, check):
            snapshot = store.snapshot()
            try:
                binding = read_content_binding(snapshot, registry.deliberation_protocol,
                    application_root=registry.application_root, space_root=root)
            except (InvalidCell, MatchBudgetExceeded):
                binding = None
            if binding is not None:
                history = service._history_for(binding)
                with history._lock:
                    table = history._db.execute("SELECT 1 FROM sqlite_master WHERE name='trace_migrations'").fetchone()
                    migrated = table is not None and history._db.execute('SELECT 1 FROM trace_migrations WHERE conversation_id=?', (root,)).fetchone() is not None
                if not migrated:
                    state['pending'] = None
                    return {**result, 'status': 'already-content', 'space_root': root}
        remaining = deadline - time.monotonic()
        if remaining < 0.05:
            return {**result, 'status': 'deferred'}
        batch = maintain_legacy_traces(service, authentication_context=authentication_context,
            space_root=root, timeout_seconds=remaining, max_chain_cells=max_chain_cells,
            cancellation_event=cancellation_event)
        if batch['status'] == 'bound' or batch['status'] == 'archived' and not batch.get('exported'):
            state['pending'] = None
        elif batch['status'] == 'source-changed':
            # Preserve the exact admitted copy and original graph for explicit
            # reconciliation; another room must not wait behind this one.
            state['pending'] = None
        return {**result, **batch, 'next_cursor': state}
    except (TimeoutError, sqlite3.OperationalError) as error:
        if isinstance(error, sqlite3.OperationalError) and (
                getattr(error, 'sqlite_errorcode', 0) & 255) not in (
                sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT):
            raise
        return {**result, 'status': 'deferred'}


def compact_trace_journal(store, *, check, on_progress=lambda _event: None, wait_seconds: float = 0.05):
    """Bounded incremental reclamation; legacy NONE space is reused in place."""
    if store.database_path is None:
        raise InvalidCell('trace compaction requires a durable journal')
    check()
    with closing(sqlite3.connect(store.database_path, timeout=wait_seconds, isolation_level=None)) as connection:
        before = connection.execute('PRAGMA freelist_count').fetchone()[0]
        if before == 0:
            return dict(status='compacted', reclaimed_pages=0)
        mode = connection.execute('PRAGMA auto_vacuum').fetchone()[0]
        if mode == 0:
            return dict(status='space-reusable', reclaimed_pages=0, remaining_pages=before)
        import shutil
        page_size = connection.execute('PRAGMA page_size').fetchone()[0]
        if shutil.disk_usage(Path(store.database_path).parent).free < 128 * page_size + 1024 * 1024:
            raise OSError('trace compaction paused: insufficient free space')
        on_progress(dict(stage='Compacting archived trace space', completed=0, total=None))
        steps = 0
        def progress():
            nonlocal steps
            check()
            steps += 1000
            on_progress(dict(stage='Compacting archived trace space', completed=steps, total=None))
            return 0
        connection.set_progress_handler(progress, 1000)
        try:
            check()
            connection.execute('PRAGMA incremental_vacuum(128)').fetchall()
            remaining = connection.execute('PRAGMA freelist_count').fetchone()[0]
            connection.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchall()
            live, lock = store.sqlite_storage()
            with lock:
                # Refresh the existing connection's page-one/schema cache
                # before it answers another header-only PRAGMA.
                live.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
        finally:
            connection.set_progress_handler(None, 0)
        on_progress(dict(stage='Compacted archived trace space',
            completed=max(0, before-remaining), total=before))
        return dict(status='compacted' if remaining == 0 else 'compacting',
            reclaimed_pages=max(0, before-remaining), remaining_pages=remaining)


def _registry_payload_owner(history, root):
    if not root.startswith('app:deliberation-payload:'):
        return None
    rows = history._db.execute("SELECT c.conversation_id,coalesce(c.activity_at,m.last_activity_at),c.digest FROM trace_migration_cells c JOIN trace_migrations m ON m.conversation_id=c.conversation_id WHERE c.cell_id=? AND c.owned=1 AND m.state='bound' LIMIT 2", (root,)).fetchall()
    return rows[0] if len(rows) == 1 and rows[0][1] is not None else None


def _registry_partition_admitted(store, history, identifier):
    """Catalog membership is a physical exclusion, independent of cursor phase."""
    connection, _ = store.sqlite_storage()
    state = history._db.execute('SELECT phase,source_revision FROM trace_registry_state WHERE singleton=1').fetchone()
    if state is None and connection.execute('SELECT 1 FROM current_cells WHERE cell_id=?', ('app:value-graph-protocol:root',)).fetchone() is None:
        return True
    cache = getattr(store, '_trace_registry_cache', None)
    if (cache is None or not cache['complete'] or cache['revision'] != store.revision
            or cache['data_version'] != connection.execute('PRAGMA data_version').fetchone()[0]):
        return False
    if identifier in cache['indexes']:
        return False
    if state and (state[0] not in ('ordinary', 'complete') or state[1] != store.revision):
        return False
    # Registered payload ownership already admits descendants by this exact
    # root-and-colon namespace. Check every possible registered ancestor.
    roots = [identifier[:index] for index, char in enumerate(identifier) if char == ':'] + [identifier]
    for root in roots:
        if cache['roots'].get(root, 0):
            return False
        if state is not None and state[0] == 'complete' and _registry_payload_owner(history, root) is not None:
            return False
        if not history._db.execute('SELECT 1 FROM trace_registry_members WHERE payload_root=? LIMIT 1', (root,)).fetchone():
            continue
        if state is None:
            return False
        if history._db.execute('SELECT 1 FROM trace_registry_members WHERE payload_root=? AND detached=0 LIMIT 1', (root,)).fetchone():
            return False
    if history._db.execute('SELECT 1 FROM trace_registry_members WHERE detached=0 AND (live_chain_id=? OR incidence_id=?) LIMIT 1', (identifier, identifier)).fetchone():
        return False
    return True


def _registry_ack_splice(history, pending, revision):
    """Acknowledge only an exact, already authenticated graph publication."""
    with history._registry_custody_write(), history._transaction(write=True):
        for identifier, root, session, activity, digest in pending['custody']:
            history._db.execute('INSERT OR IGNORE INTO trace_registry_detached VALUES(?,?,?,?,?)', (identifier, root, session, activity, digest))
        history._db.execute('UPDATE trace_registry_members SET detached=1 WHERE ordinal=?', (pending['ordinal'],))
        if pending['promoted'] is not None:
            history._db.execute('UPDATE trace_registry_members SET live_chain_id=? WHERE ordinal=?', (pending['root'], pending['promoted']))
        history._db.execute('UPDATE trace_registry_members SET chain_digest=? WHERE live_chain_id=? AND detached=0', (pending['after_digest'], pending['after'][0]))
        history._db.execute('UPDATE trace_registry_state SET pending=NULL,source_revision=?,detach_cursor=? WHERE singleton=1', (revision, pending['ordinal'] + 1))


def _advance_trace_registry(service, history, authentication_context, check, max_cells):
    """Detach verified expired trace registrations using native local splices.

    The derived relation mirror is temporary. It is scanned once, used for a
    prospective graph frontier, then discarded after an ordinary frontier and
    physical export. No catalog edge is ignored by the physical partition.
    """
    from .universal_cell import Cell, NULL_CELL_ID
    from .conversation_archive import preserve_trace_batch, trace_archive_path
    from . import commit_intent
    owner, store = service._owner, service._owner.universal_store
    registry = owner.universal_registry
    store._trace_archive_registry = registry
    protocol = getattr(registry, 'value_graph_protocol', None)
    if protocol is None:
        return None
    state = history._db.execute('SELECT * FROM trace_registry_state WHERE singleton=1').fetchone()
    if state is None:
        with history._transaction(write=True, before_commit=check):
            history._db.execute("INSERT INTO trace_registry_state(singleton,phase,cursor,ordinal,source_revision) VALUES(1,'scan',?,0,?)", (protocol.root_id, store.revision))
        return dict(status='registry-inventory', inspected=0)
    pending = json.loads(state['pending']) if state['pending'] else None
    if pending:
        store._trace_registry_cache = None
        if pending['authority'] != store.authority_identity:
            raise InvalidCell('trace catalog pending custody belongs to another authority')
        def unpack(row):
            return Cell(row[0], row[1], row[2], bytes.fromhex(row[3]))
        actual = store.read(pending['after'][0])
        if actual == unpack(pending['after']):
            # A kill between signed commit and history acknowledgement cannot
            # turn a phase flag into publication authority.
            connection, _ = store.sqlite_storage()
            row = connection.execute('SELECT link0,link1,atom FROM cell_versions WHERE revision=? AND cell_id=?', (pending['revision'] + 1, actual.id)).fetchone()
            if row is None or tuple(row) != (actual.link0, actual.link1, actual.atom):
                raise InvalidCell('trace catalog publication is not its recorded commit')
            _registry_ack_splice(history, pending, pending['revision'] + 1)
            return dict(status='registry-publication-recovered', inspected=1)
        if actual != unpack(pending['before']) or store.revision != pending['revision']:
            raise InvalidCell('trace catalog pending publication changed')
        # No publication happened. Revalidate cold custody and prepare again.
        with history._registry_custody_write(), history._transaction(write=True):
            history._db.execute('UPDATE trace_registry_state SET pending=NULL WHERE singleton=1')
    connection, _ = store.sqlite_storage()
    data_version = connection.execute('PRAGMA data_version').fetchone()[0]
    cache = getattr(store, '_trace_registry_cache', None)
    cache_valid = cache is not None and cache['revision'] == store.revision and cache['data_version'] == data_version
    if cache_valid and state['phase'] == 'scan':
        cache_valid = cache['cursor'] == state['cursor'] and cache['ordinal'] == state['ordinal']
    if cache_valid and state['phase'] in ('prospective', 'detach', 'ordinary'):
        cache_valid = cache['complete']
    if (store.revision != state['source_revision'] or not cache_valid and state['phase'] not in ('reset', 'complete', 'cleanup')
            and not (state['phase'] == 'scan' and state['ordinal'] == 0)):
        store._trace_registry_cache = None
        with history._transaction(write=True):
            history._db.execute("UPDATE trace_registry_state SET phase='reset',cursor=?,ordinal=0,source_revision=?,detach_cursor=0,previous_kept=NULL WHERE singleton=1", (protocol.root_id, store.revision))
            history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
        return dict(status='registry-source-changed', inspected=0)
    phase = state['phase']
    registry_cells = min(max_cells, 1024)
    if phase == 'cleanup':
        from .conversation_archive import _open_trace_archive, _trace_digest
        rows = history._db.execute('SELECT cell_id,conversation_id,digest FROM trace_registry_detached WHERE cell_id>? ORDER BY cell_id LIMIT ?', (state['cursor'], registry_cells)).fetchall()
        absent = []
        for identifier, session, digest in rows:
            check()
            if connection.execute('SELECT 1 FROM current_cells WHERE cell_id=?', (identifier,)).fetchone():
                continue
            with closing(_open_trace_archive(trace_archive_path(service._path), store.authority_identity, create=False)) as cold:
                copied = cold.execute('SELECT cell_id,revision,link0,link1,atom,session_id,digest FROM trace_current WHERE cell_id=?', (identifier,)).fetchone()
                if (copied is None or copied[5] != session or _trace_digest(copied[:-1]) != copied[-1]
                        or _trace_cell_digest(Cell(copied[0], copied[2], copied[3], copied[4])) != digest):
                    raise InvalidCell('trace catalog partition acknowledgement lacks cold custody')
            # The immutable kernel receipt is written only after exact
            # current/all-version cold comparison and atomic live removal.
            # Cleanup removes derived progress, not that custody proof.
            retired = connection.execute('SELECT 1 FROM trace_retired_identities WHERE identity=?',
                (hashlib.sha256(identifier.encode('utf-8')).digest(),)).fetchone()
            if not retired or connection.execute('SELECT 1 FROM cell_versions WHERE cell_id=? LIMIT 1', (identifier,)).fetchone():
                raise InvalidCell('trace catalog progress lacks a committed partition receipt')
            absent.append((identifier,))
        with history._registry_custody_write(), history._transaction(write=True, before_commit=check):
            history._db.execute('DELETE FROM trace_registry_members WHERE ordinal IN (SELECT ordinal FROM trace_registry_members ORDER BY ordinal LIMIT ?)', (registry_cells,))
            history._db.executemany('DELETE FROM trace_registry_detached WHERE cell_id=?', absent)
            if rows:
                history._db.execute('UPDATE trace_registry_state SET cursor=? WHERE singleton=1', (rows[-1][0],))
            if not rows and not history._db.execute('SELECT 1 FROM trace_registry_members LIMIT 1').fetchone():
                history._db.execute("UPDATE trace_registry_state SET phase='complete',next_due_at=? WHERE singleton=1", (time.time()+3600,))
                store._trace_registry_cache = None
        return dict(status='registry-cleanup', inspected=0)
    if phase == 'reset':
        with history._transaction(write=True, before_commit=check):
            history._db.execute('DELETE FROM trace_registry_members WHERE ordinal IN (SELECT ordinal FROM trace_registry_members ORDER BY ordinal LIMIT ?)', (registry_cells,))
            if not history._db.execute('SELECT 1 FROM trace_registry_members LIMIT 1').fetchone():
                history._db.execute("UPDATE trace_registry_state SET phase='scan' WHERE singleton=1")
        return dict(status='registry-reset', inspected=0)
    if phase == 'scan':
        cursor, ordinal = state['cursor'], state['ordinal']
        if ordinal == 0:
            if cursor != protocol.root_id:
                raise InvalidCell('trace catalog traversal did not start at its actual root')
            cache = dict(revision=store.revision, data_version=data_version, complete=False, roots={}, indexes=set(), cursor=protocol.root_id, ordinal=0)
            store._trace_registry_cache = cache
        additions = []
        with history._transaction(write=True, before_commit=check):
            for _ in range(registry_cells):
                check()
                if cursor == NULL_CELL_ID:
                    history._db.execute("UPDATE trace_registry_state SET phase='prospective' WHERE singleton=1")
                    history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
                    break
                if history._db.execute('SELECT 1 FROM trace_registry_members WHERE chain_id=?', (cursor,)).fetchone():
                    raise InvalidCell('trace catalog relation is cyclic')
                chain = store.read(cursor)
                if chain.id == protocol.root_id and not chain.atom and chain.link0 == chain.link1 == NULL_CELL_ID:
                    additions.append((chain.id, None, None))
                    cursor = NULL_CELL_ID
                    history._db.execute("UPDATE trace_registry_state SET phase='prospective' WHERE singleton=1")
                    history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
                    break
                if chain.atom or chain.link0 == NULL_CELL_ID:
                    raise InvalidCell('trace catalog relation is malformed')
                incidence = store.read(chain.link0)
                if incidence.atom:
                    raise InvalidCell('trace catalog incidence is malformed')
                admitted = _registry_payload_owner(history, incidence.link1) if incidence.link0 == protocol.role('value-member') else None
                history._db.execute('INSERT INTO trace_registry_members(ordinal,chain_id,live_chain_id,incidence_id,role_id,payload_root,next_id,chain_digest,incidence_digest,conversation_id,activity_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (ordinal, chain.id, chain.id, incidence.id, incidence.link0, incidence.link1, chain.link1, _trace_cell_digest(chain), _trace_cell_digest(incidence), admitted[0] if admitted else None, admitted[1] if admitted else None))
                additions.append((chain.id, incidence.id, incidence.link1))
                cursor, ordinal = chain.link1, ordinal + 1
            history._db.execute('UPDATE trace_registry_state SET cursor=?,ordinal=? WHERE singleton=1', (cursor, ordinal))
        for chain_id, incidence_id, payload in additions:
            cache['indexes'].add(chain_id)
            if incidence_id is not None:
                cache['indexes'].add(incidence_id)
            if payload is not None:
                cache['roots'][payload] = cache['roots'].get(payload, 0) + 1
        cache['cursor'], cache['ordinal'] = cursor, ordinal
        cache['complete'] = cursor == NULL_CELL_ID
        return dict(status='registry-inventory', inspected=ordinal-state['ordinal'])
    if phase == 'prospective':
        result = _advance_family_inventory(store, history, check, max_cells)
        if result['status'] == 'family-ready':
            with history._transaction(write=True, before_commit=check):
                history._db.execute("UPDATE trace_registry_state SET phase='detach' WHERE singleton=1")
        return {**result, 'status': 'registry-protection'}
    if phase == 'detach':
        row = history._db.execute('SELECT * FROM trace_registry_members WHERE ordinal>=? AND detached=0 ORDER BY ordinal LIMIT 1', (state['detach_cursor'],)).fetchone()
        if row is None:
            with history._transaction(write=True, before_commit=check):
                history._db.execute("UPDATE trace_registry_state SET phase='ordinary' WHERE singleton=1")
                history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
            return dict(status='registry-detached', inspected=0)
        cutoff = time.time() - _RETENTION_SECONDS
        protected = any(history._db.execute('SELECT 1 FROM trace_family_protected WHERE cell_id=?', (ident,)).fetchone() for ident in (row['payload_root'], row['incidence_id'], row['live_chain_id']))
        protected = protected or history._db.execute('SELECT 1 FROM trace_family_protected WHERE cell_id>=? AND cell_id<? LIMIT 1', (row['payload_root']+':', row['payload_root']+';')).fetchone() is not None
        admitted = _registry_payload_owner(history, row['payload_root'])
        if row['role_id'] != protocol.role('value-member') or admitted is None or admitted[1] >= cutoff or protected:
            with history._transaction(write=True, before_commit=check):
                history._db.execute('UPDATE trace_registry_state SET detach_cursor=?,previous_kept=? WHERE singleton=1', (row['ordinal']+1, row['live_chain_id']))
            return dict(status='registry-retained', inspected=1)
        chain, incidence = store.read(row['live_chain_id']), store.read(row['incidence_id'])
        if (chain.link0 != incidence.id or incidence.link0 != protocol.role('value-member') or incidence.link1 != row['payload_root']
                or chain.id not in cache['indexes'] or incidence.id not in cache['indexes']
                or _trace_cell_digest(chain) != row['chain_digest'] or _trace_cell_digest(incidence) != row['incidence_digest']
                or _trace_cell_digest(store.read(row['payload_root'])) != admitted[2]):
            raise InvalidCell('trace catalog member changed after inventory')
        custody, promoted = [incidence.id], None
        if chain.id == protocol.root_id:
            before = chain
            if chain.link1 == NULL_CELL_ID:
                after = Cell(chain.id, NULL_CELL_ID, NULL_CELL_ID, chain.atom)
            else:
                next_chain = store.read(chain.link1)
                if next_chain.id not in cache['indexes']:
                    raise InvalidCell('trace catalog promoted chain is outside actual membership')
                promoted_row = history._db.execute('SELECT ordinal FROM trace_registry_members WHERE live_chain_id=? AND detached=0', (next_chain.id,)).fetchone()
                if promoted_row is None:
                    raise InvalidCell('trace catalog promotion is outside its inventory')
                promoted = promoted_row[0]
                custody.append(next_chain.id)
                after = Cell(chain.id, next_chain.link0, next_chain.link1, chain.atom)
        else:
            custody.append(chain.id)
            before = store.read(state['previous_kept'])
            previous = history._db.execute('SELECT chain_digest FROM trace_registry_members WHERE live_chain_id=? AND detached=0', (before.id,)).fetchone()
            if before.id not in cache['indexes'] or before.link1 != chain.id or previous is None or _trace_cell_digest(before) != previous[0]:
                raise InvalidCell('trace catalog predecessor changed')
            after = Cell(before.id, before.link0, chain.link1, before.atom)
        connection, _ = store.sqlite_storage()
        archive = trace_archive_path(service._path)
        cold, _ = preserve_trace_batch(connection, archive, store.authority_identity, custody, dict.fromkeys(custody, admitted[0]), check)
        cold.close()
        packed = lambda cell: [cell.id, cell.link0, cell.link1, cell.atom.hex()]
        pending = dict(authority=store.authority_identity, ordinal=row['ordinal'], root=protocol.root_id, promoted=promoted, revision=store.revision, after_digest=_trace_cell_digest(after),
            before=packed(before), after=packed(after), custody=[[ident, row['payload_root'], admitted[0], admitted[1], _trace_cell_digest(store.read(ident))] for ident in custody])
        with history._registry_custody_write(), history._transaction(write=True, before_commit=check):
            history._db.execute('UPDATE trace_registry_state SET pending=? WHERE singleton=1', (json.dumps(pending),))
        check()
        if cache['revision'] != store.revision or cache['data_version'] != connection.execute('PRAGMA data_version').fetchone()[0]:
            raise TimeoutError('trace catalog source changed before publication')
        with commit_intent.declare(commit_intent.MIGRATION, actor=registry.authorization.subject_root,
                reason='Authenticated legacy conversation migration: detach verified expired trace catalog member'):
            registry.authorization.broker.commit_authenticated(authentication_context, store, pending['revision'], replace=(after,))
        if store.read(after.id) != after:
            raise InvalidCell('trace catalog publication differs')
        cache['roots'][incidence.link1] -= 1
        for identifier in custody:
            cache['indexes'].discard(identifier)
        cache['revision'] = store.revision
        _registry_ack_splice(history, pending, store.revision)
        return dict(status='registry-detaching', inspected=1)
    if phase == 'complete' and time.time() >= state['next_due_at']:
        with history._transaction(write=True):
            history._db.execute("UPDATE trace_registry_state SET phase='reset',cursor=?,ordinal=0,detach_cursor=0,previous_kept=NULL WHERE singleton=1", (protocol.root_id,))
        return dict(status='registry-due', inspected=0)
    return None


def _family_descriptor(history, identifier):
    """The registered converter can admit wider exact payload custody."""
    detached = history._db.execute('SELECT conversation_id,activity_at,digest FROM trace_registry_detached WHERE cell_id=?', (identifier,)).fetchone()
    if detached:
        return detached[0], True, detached[1], detached[2]
    state = history._db.execute('SELECT phase FROM trace_registry_state WHERE singleton=1').fetchone()
    if state and state[0] in ('prospective', 'detach'):
        member = history._db.execute('SELECT chain_id,incidence_id,chain_digest,incidence_digest,conversation_id FROM trace_registry_members WHERE live_chain_id=? OR incidence_id=? LIMIT 1', (identifier, identifier)).fetchone()
        if member and not history._db.execute('SELECT 1 FROM trace_registry_members WHERE ordinal=0 AND chain_id=?', (identifier,)).fetchone():
            if identifier == member[1] and member[4] is None:
                return None, False, None, None
            return 'trace-catalog', True, 0.0, member[2] if identifier == member[0] else member[3]
    rows = history._db.execute("SELECT c.conversation_id,coalesce(c.activity_at,m.last_activity_at),c.digest FROM trace_migration_cells c JOIN trace_migrations m ON m.conversation_id=c.conversation_id WHERE c.cell_id=? AND c.owned=1 AND m.state='bound' LIMIT 2",
        (identifier,)).fetchall()
    if len(rows) > 1:
        return None, False, None, None
    if rows:
        return rows[0][0], rows[0][1] is not None, rows[0][1], rows[0][2]
    session, candidate = _trace_family_descriptor(identifier)
    if session is None:
        return None, False, None, None
    if candidate and history._db.execute("SELECT 1 FROM trace_migration_cells c JOIN trace_migrations m ON m.conversation_id=c.conversation_id WHERE c.cell_id=? AND c.owned=0 AND m.state IN ('bound','receipt-copying') LIMIT 1",
            (identifier,)).fetchone():
        # The typed converter retains its graph receipt/control root. Its
        # compact value is live graph evidence, rather than trace scaffolding.
        return session, False, None, None
    return session, candidate, None, None


def _record_family_cell(history, row, cutoff, check):
    identifier, _revision, link0, link1, activity = row
    check()
    session, candidate, owned_activity, digest = _family_descriptor(history, identifier)
    session_activity = history._db.execute('SELECT last_activity_at FROM trace_family_sessions WHERE session_id=?', (session,)).fetchone() if candidate and digest is None else None
    if session is not None and candidate and digest is None:
        if session_activity is None or activity > session_activity[0]:
            history._trace_activity_inventory = None
        history._db.execute('INSERT INTO trace_family_sessions VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET last_activity_at=max(last_activity_at,excluded.last_activity_at)',
            (session, activity))
    structural = history._db.execute('SELECT 1 FROM trace_registry_members WHERE live_chain_id=? OR incidence_id=? UNION ALL SELECT 1 FROM trace_registry_detached WHERE cell_id=? LIMIT 1', (identifier, identifier, identifier)).fetchone()
    recent_session = candidate and digest is None and max(activity, session_activity[0] if session_activity else activity) >= cutoff
    if not candidate or not structural and activity >= cutoff or owned_activity is not None and owned_activity >= cutoff or recent_session:
        state = history._db.execute('SELECT phase FROM trace_registry_state WHERE singleton=1').fetchone()
        if state and state[0] in ('prospective', 'detach') and history._db.execute('SELECT 1 FROM trace_registry_members WHERE ordinal=0 AND chain_id=?', (identifier,)).fetchone():
            return
        for target in (link0, link1):
            if _family_descriptor(history, target)[1]:
                history._db.execute('INSERT OR IGNORE INTO trace_family_protected(cell_id) VALUES(?)', (target,))


def _project_trace_catalogue_page(store, history, state, check, max_cells):
    """Remove expired membership from obsolete, typed catalogue versions only.

    Current graph roots and ordinary workflow history are never rewritten.
    Exact originals, including rowids, reach durable cold custody first.
    """
    from .universal_cell import Cell, NULL_CELL_ID, Snapshot
    from .conversation_archive import _open_trace_archive, _trace_digest, trace_archive_path
    from .conversation_trace_receipts import _SUFFIXES, _boot_receipt_roots, _receipt_shape
    connection, _ = store.sqlite_storage()
    phase = history._db.execute('SELECT phase FROM trace_registry_state WHERE singleton=1').fetchone()
    catalog_projection = phase is None or phase[0] in ('ordinary', 'complete')
    cutoff = time.time() - _RETENTION_SECONDS
    def eligible(identifier):
        session, candidate, activity, digest = _family_descriptor(history, identifier)
        if not candidate:
            return False
        if not _registry_partition_admitted(store, history, identifier):
            # A published room may release its obsolete entry membership
            # before the value catalogue detaches the referenced payload.
            # This projects no catalogue edge and retires no live identity.
            cache = getattr(store, '_trace_registry_cache', None)
            if catalog_projection or digest is None or cache and identifier in cache['indexes']:
                return False
            if _trace_cell_digest(store.read(identifier)) != digest:
                raise InvalidCell('historical room entry changed after publication')
        if digest is None:
            row = history._db.execute('SELECT last_activity_at FROM trace_family_sessions WHERE session_id=?', (session,)).fetchone()
            activity = row[0] if row else None
        return activity is not None and activity < cutoff
    def at(identifier, revision):
        check()
        row = connection.execute('SELECT link0,link1,atom FROM cell_versions WHERE cell_id=? AND revision<=? ORDER BY revision DESC LIMIT 1', (identifier, revision)).fetchone()
        if row is None:
            raise InvalidCell('historical catalogue member is missing before custody')
        return Cell(identifier, row[0], row[1], bytes(row[2]))
    def expired(chain, revision, role):
        if chain.atom or chain.link0 == NULL_CELL_ID:
            return False
        incidence = at(chain.link0, revision)
        return not incidence.atom and incidence.link0 == role and (eligible(incidence.id) or eligible(incidence.link1))
    def room_controls(old, revision, registry):
        # Reuse the already published control scaffolding, with historical
        # versions at the same revision. No current Cell or identity changes.
        old_pairs, seen, chain = [], set(), old
        while chain.link0 != NULL_CELL_ID:
            if chain.id in seen or len(seen) >= 256:
                return None
            seen.add(chain.id)
            incidence = at(chain.link0, revision)
            if chain.atom or incidence.atom:
                return None
            if incidence.link0 == registry.deliberation_protocol.role('space-entry'):
                if not expired(chain, revision, incidence.link0):
                    return None
            else:
                old_pairs.append((incidence.link0, incidence.link1))
                if chain.id != old.id and connection.execute('SELECT COUNT(DISTINCT link0) FROM cell_versions WHERE cell_id=?', (chain.id,)).fetchone()[0] != 1:
                    return None  # A changing historical control stays graph.
            if chain.link1 == NULL_CELL_ID:
                break
            chain = at(chain.link1, revision)
        current, seen = store.read(old.id), set()
        controls = []
        while current.link0 != NULL_CELL_ID:
            check()
            if current.id in seen or len(seen) >= 256:
                raise InvalidCell('published conversation controls exceed their bound')
            seen.add(current.id)
            incidence = store.read(current.link0)
            if incidence.link0 != registry.deliberation_protocol.role('space-content-store'):
                controls.append((current, incidence))
            if current.link1 == NULL_CELL_ID:
                break
            current = store.read(current.link1)
        if old_pairs != [(inc.link0, inc.link1) for _chain, inc in controls]:
            return None
        planned = []
        for index, (current, incidence) in enumerate(controls):
            at(incidence.link0, revision)
            at(incidence.link1, revision)
            desired = (incidence, Cell(old.id if index == 0 else current.id, incidence.id,
                controls[index+1][0].id if index+1 < len(controls) else NULL_CELL_ID, b''))
            for cell in desired:
                row = connection.execute('SELECT link0,link1,atom FROM cell_versions WHERE revision=? AND cell_id=?', (revision, cell.id)).fetchone()
                before = Cell(cell.id, row[0], row[1], bytes(row[2])) if row else None
                if before != cell:
                    if before is not None and cell.id != old.id:
                        return None
                    planned.append((revision, before, cell))
        return planned
    projections, frontier, expanded_roots, receipt_seals = [], None, 0, {}
    rows = connection.execute('SELECT v.revision,v.cell_id,v.link0,v.link1,v.atom,c.revision FROM cell_versions v '
        'JOIN current_cells c ON c.cell_id=v.cell_id WHERE (v.revision,v.cell_id)>(?,?) '
        'ORDER BY v.revision,v.cell_id LIMIT ?',
        (state['delta_revision'], state['delta_cell'], max_cells)).fetchall()
    for revision, identifier, link0, link1, atom, current_revision in rows:
        if expanded_roots == 2:
            break
        frontier = (revision, identifier)
        check()
        if revision >= current_revision or atom or identifier in tuple('app:agent-session:founder:' + role for role in ('view-receipt','scope-receipt','close-receipt')):
            continue
        cache = getattr(store, '_trace_registry_cache', None)
        registry = getattr(store, '_trace_archive_registry', None)
        receipt = history._db.execute("SELECT m.conversation_id,c.digest FROM trace_migrations m JOIN trace_migration_cells c ON c.conversation_id=m.conversation_id WHERE c.cell_id=? AND c.owned=0 AND c.walked=1 AND m.source_authority=? AND m.state='bound'", (identifier, store.authority_identity)).fetchone()
        if receipt and registry is not None and identifier in tuple(receipt[0] + suffix for suffix in _SUFFIXES):
            if identifier in _boot_receipt_roots(registry):
                continue
            class HistoricalCells(Mapping):
                def __getitem__(self, key):
                    return at(key, revision)
                def __iter__(self):
                    raise InvalidCell('receipt projection cannot scan history')
                def __len__(self):
                    return len(store.snapshot().cells)
            _before, compact, children = _receipt_shape(Snapshot(revision, HistoricalCells()),
                registry.agent_body.protocol, registry.authorization.protocol, identifier, check)
            if compact != store.read(identifier):
                continue
            end = connection.execute('SELECT MIN(revision) FROM cell_versions WHERE cell_id=? AND revision>?', (identifier, revision)).fetchone()[0]
            changed = False
            for child in children:
                check()
                if connection.execute('SELECT 1 FROM cell_versions WHERE cell_id=? AND revision>? AND revision<? LIMIT 1', (child, revision, end)).fetchone():
                    changed = True
                    break
            if changed:
                continue
            receipt_seals[identifier] = receipt
            projections.append((revision, Cell(identifier, link0, link1, bytes(atom)), compact))
            expanded_roots += 1
            continue
        catalog = catalog_projection and cache and cache['complete'] and cache['revision'] == store.revision and identifier in cache['indexes'] and history._db.execute('SELECT 1 FROM trace_registry_members WHERE live_chain_id=? AND detached=0', (identifier,)).fetchone()
        bound = history._db.execute("SELECT m.binding_root FROM trace_migrations m JOIN trace_migration_cells c ON c.conversation_id=m.conversation_id WHERE m.conversation_id=? AND m.source_authority=? AND m.state='bound' AND c.cell_id=m.conversation_id AND c.walked=1 AND c.owned=0", (identifier, store.authority_identity)).fetchone()
        if bound:
            from .conversation_content import read_content_binding
            registry = getattr(store, '_trace_archive_registry', None)
            if registry is None:
                continue
            binding = read_content_binding(store.snapshot(), registry.deliberation_protocol,
                application_root=registry.application_root, space_root=identifier)
            if binding.root_id != bound[0] or binding.instance_id != history.instance_id:
                raise InvalidCell('historical catalogue binding changed')
        if not (catalog or bound):
            continue
        registry = getattr(store, '_trace_archive_registry', None)
        role = (registry.deliberation_protocol.role('space-entry') if bound
            else registry.value_graph_protocol.role('value-member'))
        old = Cell(identifier, link0, link1, bytes(atom))
        if bound:
            planned = room_controls(old, revision, registry)
            if planned is not None:
                projections.extend(planned)
                expanded_roots += bool(planned)
            continue
        chain, visited = old, set()
        while expired(chain, revision, role):
            if chain.id in visited:
                raise InvalidCell('historical trace catalogue is cyclic')
            visited.add(chain.id)
            chain = at(chain.link1, revision) if chain.link1 != NULL_CELL_ID else Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b'')
        tail = chain.link1
        while tail != NULL_CELL_ID:
            successor = at(tail, revision)
            if not eligible(tail) or not expired(successor, revision, role):
                break
            if tail in visited:
                raise InvalidCell('historical trace catalogue is cyclic')
            visited.add(tail)
            tail = successor.link1
        new = Cell(identifier, chain.link0, tail, old.atom)
        if new != old:
            projections.append((revision, old, new))
            expanded_roots += 1
    if not projections:
        return frontier
    path = trace_archive_path(Path(history._db.execute('PRAGMA database_list').fetchone()[2]))
    with closing(_open_trace_archive(path, store.authority_identity, create=True)) as cold:
        for revision, old, _new in projections:
            if old is None:
                continue
            # Include earlier empty/root versions, retaining the original
            # catalogue timeline alongside every projected membership.
            copied_through = cold.execute('SELECT MAX(revision) FROM trace_versions WHERE cell_id=?', (old.id,)).fetchone()[0]
            for row in connection.execute('SELECT revision,cell_id,link0,link1,atom,rowid FROM cell_versions WHERE cell_id=? AND revision>? AND revision<=? ORDER BY revision', (old.id, -1 if copied_through is None else copied_through, revision)):
                check()
                cold.execute('INSERT INTO trace_versions VALUES(?,?,?,?,?,?,?)', (*row, _trace_digest(row)))
        cold.commit()
    with closing(_open_trace_archive(path, store.authority_identity, create=False)) as cold:
        for identifier, (session, seal) in receipt_seals.items():
            held = cold.execute('SELECT cell_id,revision,link0,link1,atom,session_id,digest FROM trace_current WHERE cell_id=?', (identifier,)).fetchone()
            if (held is None or held[5] != session or _trace_digest(held[:-1]) != held[-1]
                    or _trace_cell_digest(Cell(held[0], held[2], held[3], bytes(held[4]))) != seal):
                raise ArchiveConflict('historical receipt root custody differs')
        for revision, old, _new in projections:
            if old is None:
                continue
            row = cold.execute('SELECT revision,cell_id,link0,link1,atom,source_rowid,digest FROM trace_versions WHERE revision=? AND cell_id=?', (revision, old.id)).fetchone()
            if row is None or _trace_digest(row[:-1]) != row[-1]:
                raise ArchiveConflict('historical catalogue custody readback differs')
        store.partition_archived_cells(cold, (), projections=projections, check=check)
    return frontier


def _advance_family_inventory(store, history, check, max_cells):
    """One keyset/frontier page; no transcript-sized membership mirror."""
    connection, _lock = store.sqlite_storage()
    cutoff = time.time() - _RETENTION_SECONDS
    # Current-row classification writes derived session metadata too. Bound
    # every inventory phase inside the existing SQL/time operation guards.
    page_cells = min(max_cells, 1024)
    frontier = None
    state = history._db.execute('SELECT * FROM trace_family_state WHERE singleton=1').fetchone()
    if state is not None and state['phase'] == 'historical':
        frontier = _project_trace_catalogue_page(store, history, state, check, page_cells)
    with history._transaction(write=True, before_commit=check):
        state = history._db.execute('SELECT * FROM trace_family_state WHERE singleton=1').fetchone()
        if state is None:
            revision = store.revision
            history._db.execute("INSERT INTO trace_family_state(singleton,phase,cursor,watermark,delta_revision,delta_cell) VALUES(1,'scan','',?,?,'')", (revision, revision+1))
            state = history._db.execute('SELECT * FROM trace_family_state WHERE singleton=1').fetchone()
        phase = state['phase']
        if phase == 'complete' and time.time() >= state['next_due_at']:
            history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
            phase = 'reset'
        if phase == 'reset':
            for table, key in (('trace_family_sessions', 'session_id'), ('trace_family_protected', 'cell_id')):
                check()
                history._db.execute('DELETE FROM ' + table + ' WHERE ' + key + ' IN (SELECT ' + key + ' FROM ' + table + ' ORDER BY ' + key + ' LIMIT ?)', (page_cells,))
            pending = any(history._db.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone() is not None
                for table in ('trace_family_sessions', 'trace_family_protected'))
            if not pending:
                history._db.execute("UPDATE trace_family_state SET phase='scan',cursor='',watermark=?,delta_revision=?,delta_cell='' WHERE singleton=1",
                    (store.revision, store.revision+1))
            return dict(status='family-reset', inspected=0, next_cursor='')
        if phase in ('export', 'complete', 'protect') and store.revision > state['watermark']:
            history._db.execute("UPDATE trace_family_state SET phase='delta',delta_revision=watermark+1,delta_cell='' WHERE singleton=1")
            phase = 'delta'
            state = history._db.execute('SELECT * FROM trace_family_state WHERE singleton=1').fetchone()
        if phase == 'scan':
            rows = connection.execute('SELECT c.cell_id,c.revision,c.link0,c.link1,r.committed_at FROM current_cells c JOIN revisions r ON r.revision=c.revision WHERE c.cell_id>? ORDER BY c.cell_id LIMIT ?',
                (state['cursor'], page_cells)).fetchall()
            for row in rows:
                _record_family_cell(history, row, cutoff, check)
            if rows:
                history._db.execute('UPDATE trace_family_state SET cursor=? WHERE singleton=1', (rows[-1][0],))
            else:
                history._db.execute("UPDATE trace_family_state SET phase='historical',cursor='',delta_revision=0,delta_cell='' WHERE singleton=1")
                history._trace_activity_inventory = state['watermark']
            return dict(status='family-inventory', inspected=len(rows), next_cursor=rows[-1][0] if rows else '')
        if phase == 'historical':
            rows = connection.execute('SELECT v.cell_id,v.revision,v.link0,v.link1,r.committed_at '
                'FROM cell_versions v JOIN revisions r ON r.revision=v.revision '
                'WHERE (v.revision,v.cell_id)>(?,?) ' +
                ('AND (v.revision,v.cell_id)<=(?,?) ' if frontier is not None else '') +
                'ORDER BY v.revision,v.cell_id LIMIT ?',
                (state['delta_revision'], state['delta_cell'], *(frontier or ()), page_cells)).fetchall()
            for row in rows:
                _record_family_cell(history, row, cutoff, check)
            if rows:
                history._db.execute('UPDATE trace_family_state SET delta_revision=?,delta_cell=? WHERE singleton=1',
                    (rows[-1][1], rows[-1][0]))
            else:
                history._db.execute("UPDATE trace_family_state SET phase='delta',delta_revision=watermark+1,delta_cell='' WHERE singleton=1")
            return dict(status='family-inventory', inspected=len(rows), next_cursor=str(rows[-1][:2]) if rows else '')
        if phase == 'delta':
            rows = connection.execute('SELECT revision,cell_id FROM cell_versions WHERE (revision,cell_id)>(?,?) ORDER BY revision,cell_id LIMIT ?',
                (state['delta_revision'], state['delta_cell'], page_cells)).fetchall()
            for revision, identifier in rows:
                check()
                current = connection.execute('SELECT c.cell_id,c.revision,c.link0,c.link1,r.committed_at FROM current_cells c JOIN revisions r ON r.revision=c.revision WHERE c.cell_id=?', (identifier,)).fetchone()
                if current is not None:
                    history._db.execute('UPDATE trace_family_protected SET walked=0 WHERE cell_id=?', (identifier,))
                    _record_family_cell(history, current, cutoff, check)
            if rows:
                history._db.execute('UPDATE trace_family_state SET delta_revision=?,delta_cell=? WHERE singleton=1', rows[-1])
            else:
                # The preceding historical pass already retained dependencies
                # using the complete session activity inventory. Only a real
                # delta needs another current-member pass.
                # This disposable witness is lost on restart, which safely
                # keeps the old pass. Back-dated historical maxima invalidate it.
                next_phase = 'protect' if store.revision == state['watermark'] == getattr(history, '_trace_activity_inventory', None) else 'retain'
                history._db.execute("UPDATE trace_family_state SET phase=?,cursor='',watermark=? WHERE singleton=1", (next_phase, store.revision))
            return dict(status='family-delta', inspected=len(rows), next_cursor=str(rows[-1]) if rows else '')
        if phase == 'retain':
            # Session age is now complete. Even an old member of a recent
            # session remains live and therefore protects its dependencies.
            rows = connection.execute('SELECT cell_id,link0,link1 FROM current_cells WHERE cell_id>? ORDER BY cell_id LIMIT ?',
                (state['cursor'], page_cells)).fetchall()
            for identifier, link0, link1 in rows:
                check()
                session, candidate, owned_activity, digest = _family_descriptor(history, identifier)
                activity = history._db.execute('SELECT last_activity_at FROM trace_family_sessions WHERE session_id=?', (session,)).fetchone() if candidate and digest is None else None
                if owned_activity is not None and owned_activity >= cutoff or activity is not None and activity[0] >= cutoff:
                    for target in (link0, link1):
                        if _family_descriptor(history, target)[1]:
                            history._db.execute('INSERT OR IGNORE INTO trace_family_protected(cell_id) VALUES(?)', (target,))
            if rows:
                history._db.execute('UPDATE trace_family_state SET cursor=? WHERE singleton=1', (rows[-1][0],))
            else:
                history._db.execute("UPDATE trace_family_state SET phase='protect',cursor='' WHERE singleton=1")
            return dict(status='family-retained-dependencies', inspected=len(rows), next_cursor=rows[-1][0] if rows else '')
        if phase == 'protect':
            rows = history._db.execute('SELECT cell_id FROM trace_family_protected WHERE walked=0 ORDER BY cell_id LIMIT ?', (page_cells,)).fetchall()
            for (identifier,) in rows:
                check()
                for version in connection.execute('SELECT link0,link1 FROM cell_versions WHERE cell_id=?', (identifier,)):
                    check()
                    for target in version:
                        if _family_descriptor(history, target)[1]:
                            history._db.execute('INSERT OR IGNORE INTO trace_family_protected(cell_id) VALUES(?)', (target,))
                history._db.execute('UPDATE trace_family_protected SET walked=1 WHERE cell_id=?', (identifier,))
            if not rows:
                history._db.execute("UPDATE trace_family_state SET phase='export' WHERE singleton=1")
            return dict(status='family-protection', inspected=len(rows), next_cursor=rows[-1][0] if rows else '')
        return dict(status='family-ready' if phase == 'export' else 'family-complete', inspected=0,
                    next_cursor=state['cursor'])


def partition_archived_trace_batch(store, history, archive_path, ids, sessions, *, check):
    """Admit semantics and indexed custody before the kernel's exact partition."""
    from .conversation_archive import _open_trace_archive, _trace_digest
    identifiers = tuple(dict.fromkeys(ids))
    if not identifiers or len(identifiers) > 256 or not set(identifiers) <= set(sessions):
        raise ValueError('trace partition selection is invalid')
    connection, lock = store.sqlite_storage()
    with lock, history._lock:
        if history._db.in_transaction:
            raise InvalidCell('trace partition requires durably committed conversation content')
        # A small direct batch can finish admission immediately; on a large
        # store check() defers, retaining each committed inventory page.
        while True:
            check()
            result = _advance_family_inventory(store, history, check, 256)
            if result['status'] in ('family-ready', 'family-complete'):
                break
        cutoff = time.time() - _RETENTION_SECONDS
        for identifier in identifiers:
            check()
            if not _registry_partition_admitted(store, history, identifier):
                raise InvalidCell('trace partition preserves current value catalog membership')
            session, candidate, owned_activity, digest = _family_descriptor(history, identifier)
            if not candidate or session != sessions[identifier]:
                raise InvalidCell('trace partition excludes graph and control content')
            row = connection.execute('SELECT r.committed_at FROM current_cells c JOIN revisions r ON r.revision=c.revision WHERE c.cell_id=?', (identifier,)).fetchone()
            age = history._db.execute('SELECT last_activity_at FROM trace_family_sessions WHERE session_id=?', (session,)).fetchone() if digest is None else None
            activity = owned_activity if digest is not None else age[0] if age is not None else None
            detached = history._db.execute('SELECT 1 FROM trace_registry_detached WHERE cell_id=?', (identifier,)).fetchone()
            if row is None or not detached and row[0] >= cutoff or activity is None or activity >= cutoff:
                raise InvalidCell('trace partition requires an inactive session older than20 days')
            if digest is not None and _trace_cell_digest(store.read(identifier)) != digest:
                raise InvalidCell('registered trace candidate changed after content publication')
            if history._db.execute('SELECT 1 FROM trace_family_protected WHERE cell_id=?', (identifier,)).fetchone():
                raise InvalidCell('trace partition preserves graph or recent dependencies')
        with closing(_open_trace_archive(archive_path, store.authority_identity, create=False)) as cold:
            cold.execute('BEGIN')
            history.index_trace_archive(cold, tuple(sessions[ident] for ident in identifiers),
                archive_path=archive_path, check=check, cell_ids=identifiers)
            for identifier in identifiers:
                check()
                current = cold.execute('SELECT cell_id,revision,link0,link1,atom,session_id,digest FROM trace_current WHERE cell_id=?', (identifier,)).fetchone()
                if (current is None or current[5] != sessions[identifier]
                        or _trace_digest(current[:-1]) != current[-1]):
                    raise ArchiveConflict('trace archive current custody digest differs')
                for row in cold.execute('SELECT revision,cell_id,link0,link1,atom,source_rowid,digest FROM trace_versions WHERE cell_id=?', (identifier,)):
                    check()
                    if _trace_digest(row[:-1]) != row[-1]:
                        raise ArchiveConflict('trace archive historical custody digest differs')
            store.partition_archived_cells(cold, identifiers, check=check)
            # Exact bytes now belong to cold custody. Keep content/message
            # seals, but do not retain a second long-ID scaffold inventory.
            with history._registry_custody_write(), history._transaction(write=True, before_commit=check):
                history._db.executemany('DELETE FROM trace_migration_cells WHERE cell_id=? AND owned=1',
                    ((identifier,) for identifier in identifiers))
                history._db.executemany('DELETE FROM trace_registry_detached WHERE cell_id=?', ((identifier,) for identifier in identifiers))
        return len(identifiers)


def maintain_trace_families(service, *, authentication_context, timeout_seconds=2.0,
                            max_cells=1024, cancellation_event=None, prepare_only=False):
    """Authenticated idle fallback for unregistered obsolete trace chains."""
    from .conversation_archive import choose_trace_batch, preserve_trace_batch, trace_archive_path
    if authentication_context is None:
        raise AuthorizationDenied('trace family maintenance requires process authentication')
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 2 or type(max_cells) is not int or not 1 <= max_cells <= 8192
            or type(prepare_only) is not bool):
        raise ValueError('trace family maintenance bounds are invalid')
    deadline = time.monotonic() + timeout_seconds
    owner = service._owner
    def check():
        if (time.monotonic() >= deadline or _user_is_active(owner)
                or cancellation_event is not None and cancellation_event.is_set()):
            raise TimeoutError('trace family maintenance cancelled or budget exhausted')
    result = dict(status='family-deferred', inspected=0, exported=0, moved=0, versions=0, next_cursor=None)
    if _user_is_active(owner):
        return {**result, 'status': 'waiting-for-idle'}
    try:
        with _short_lock(owner.mutation_lock, check):
            service._require_live_owner()
            store, registry = owner.universal_store, owner.universal_registry
            with _short_lock(registry.authorization.broker._lock, check), registry.authorization.broker.live_context(authentication_context):
                with _short_lock(store._lock, check):
                    snapshot = store.snapshot()
                    _authorize(service, snapshot, authentication_context)
                    history = _legacy_trace_history(service, snapshot)
                    history.initialize_trace_maintenance()
                    history.admit_trace_custody(store.authority_identity, registry.application_root)
                    registry_step = _advance_trace_registry(service, history, authentication_context, check, max_cells)
                    if registry_step is not None:
                        return {**result, **registry_step}
                    advanced = _advance_family_inventory(store, history, check, max_cells)
                    if advanced['status'] != 'family-ready':
                        return {**result, **advanced}
                    if prepare_only:
                        return {**result, **advanced}
                    connection, _lock = store.sqlite_storage()
                    cursor = history._db.execute('SELECT cursor FROM trace_family_state WHERE singleton=1').fetchone()[0]
                    rows = connection.execute('SELECT c.cell_id,r.committed_at FROM current_cells c JOIN revisions r ON r.revision=c.revision WHERE c.cell_id>? ORDER BY c.cell_id LIMIT ?', (cursor, min(max_cells, 256))).fetchall()
                    if not rows:
                        with history._transaction(write=True, before_commit=check):
                            cutoff = time.time() - _RETENTION_SECONDS
                            due = history._db.execute('SELECT MIN(last_activity_at)+? FROM trace_family_sessions WHERE last_activity_at>=?',
                                (_RETENTION_SECONDS, cutoff)).fetchone()[0]
                            history._db.execute("UPDATE trace_family_state SET phase='complete',next_due_at=? WHERE singleton=1",
                                (min(due, time.time()+3600) if due is not None else time.time()+3600,))
                            cleaning = history._db.execute("UPDATE trace_registry_state SET phase='cleanup',cursor='' WHERE singleton=1 AND phase='ordinary'").rowcount
                        return {**result, 'status': 'registry-cleanup' if cleaning else 'family-complete'}
                    selected, sessions = [], {}
                    cutoff = time.time() - _RETENTION_SECONDS
                    for identifier, committed_at in rows:
                        check()
                        session, candidate, owned_activity, digest = _family_descriptor(history, identifier)
                        if not candidate:
                            continue
                        age = ((owned_activity,) if digest is not None else
                            history._db.execute('SELECT last_activity_at FROM trace_family_sessions WHERE session_id=?', (session,)).fetchone())
                        protected = history._db.execute('SELECT 1 FROM trace_family_protected WHERE cell_id=?', (identifier,)).fetchone()
                        detached = history._db.execute('SELECT 1 FROM trace_registry_detached WHERE cell_id=?', (identifier,)).fetchone()
                        if (age is not None and age[0] is not None and age[0] < cutoff
                                and (committed_at < cutoff or detached) and protected is None
                                and _registry_partition_admitted(store, history, identifier)):
                            if digest is not None and _trace_cell_digest(store.read(identifier)) != digest:
                                raise InvalidCell('registered trace candidate changed after content publication')
                            selected.append(identifier)
                            sessions[identifier] = session
                    last = rows[-1][0]
                    if selected:
                        # Inventory pages can be larger than the physical
                        # custody transaction, whose existing cap stays 256.
                        identifiers = choose_trace_batch(connection, selected[:256], check)
                        # Unselected eligible cells remain ahead of the cursor.
                        if len(identifiers) < len(selected):
                            last = identifiers[-1]
                        selected_sessions = {ident: sessions[ident] for ident in identifiers}
                        archive = trace_archive_path(service._path)
                        cold, versions = preserve_trace_batch(connection, archive, store.authority_identity,
                            identifiers, selected_sessions, check)
                        cold.close()
                        moved = partition_archived_trace_batch(store, history, archive, identifiers,
                            selected_sessions, check=check)
                        result.update(exported=len(identifiers), moved=moved, versions=versions)
                    with history._transaction(write=True, before_commit=check):
                        history._db.execute('UPDATE trace_family_state SET cursor=? WHERE singleton=1', (last,))
                    return {**result, 'status': 'family-archiving', 'inspected': len(rows), 'next_cursor': last}
    except (TimeoutError, sqlite3.OperationalError) as error:
        if isinstance(error, sqlite3.OperationalError) and (
                getattr(error, 'sqlite_errorcode', 0) & 255) not in (
                sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT):
            raise
        return result


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


def _maintain(service, authentication_context, after_conversation_id, deadline, cancelled, check, result,
              *, dry_run=False):
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
                if dry_run:
                    result['policy'] = retention_policy(service)
                check()
                history = service._history
                if history is None:
                    return {**result, 'status':'not-enabled'}
                with _short_lock(history._lock, check), history._bounded_operations(
                        deadline=deadline, cancelled=cancelled):
                    _configured_target(service, history)
                    version = history._db.execute('PRAGMA user_version').fetchone()[0]
                    if version == _RETENTION_VERSION:
                        if dry_run:
                            return {**result, 'status':'needs-page-protection'}
                        # An install created before draft protection: enable it once,
                        # at an idle pass. Its existing rooms stay protected until
                        # their drafts are resolved; rooms created later are born tracked.
                        history.initialize_page_protection(before_commit=check)
                        return {**result, 'status':'upgraded'}
                    if version != PAGE_PROTECTION_VERSION:
                        return {**result, 'status':'not-enabled'}
                    directory = archive_directory(service._path)
                    if dry_run:
                        # Advance a disposable copy: dry-run observations must not
                        # help a later maintenance pass earn its inactivity time.
                        original = getattr(service, '_retention_observed', None)
                        observed = copy.copy(original) if original is not None else _ObservedClock(directory)
                    else:
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
                            if dry_run:
                                anchor = observed.anchors.get(root)
                                observed_idle = (observed.total - anchor[1] if anchor is not None
                                    and anchor[0] == status['activity_revision'] else 0.0)
                            else:
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
                                if dry_run:
                                    commit_guard()
                                    # The report samples at most one batch's rows,
                                    # with UTF-8 content payload bytes (not
                                    # an estimate of filesystem space reclaimed).
                                    batch = history._db.execute(
                                        'SELECT length(CAST(content AS BLOB)) FROM messages '
                                        'WHERE conversation_id=? ORDER BY sequence DESC LIMIT ?',
                                        (root, MESSAGES_PER_PURGE)).fetchall()
                                    result['eligible'].append(dict(conversation_id=root,
                                        would_archive=status['archived_at'] is None,
                                        sample_messages=len(batch),
                                        sample_message_limit=MESSAGES_PER_PURGE,
                                        sample_content_bytes=sum(row[0] for row in batch),
                                        archive_file=str(archive)))
                                    continue
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
