"""Idle conversion of owned historical Agent Session receipt scaffolding.

The graph keeps the typed receipt root and all its revisions. Its old children
enter the existing exact trace custody path; this module never removes Cells.
The payload is the existing Agent Body compact receipt v1 format.
"""
from collections import ChainMap
from contextlib import closing
import json
import math
import sqlite3
import time

from . import commit_intent
from .cell_agent_body import _read_authorization_receipt, MAX_RECEIPT_RELATION_MEMBERS
from .cell_authorization import AuthorizationDenied
from .cell_protocols import read_relation
from .conversation_archive import (ArchiveConflict, _open_trace_archive, _trace_digest,
    preserve_trace_batch, choose_trace_batch, trace_archive_path)
from .conversation_history import _RETENTION_SECONDS
from .conversation_migration_activation import _authorize
from .conversation_retention_maintenance import (
    _advance_family_inventory, _legacy_trace_history, _short_lock,
    _family_descriptor, _trace_cell_digest, _user_is_active,
)
from .universal_cell import Cell, InvalidCell, NULL_CELL_ID, Snapshot


_PREFIX = 'app:agent-session:'
_SUFFIXES = (':view-receipt', ':scope-receipt', ':close-receipt')
_VALUES = (':revision', ':evaluated-at', ':context-expires-at', ':policy-digest', ':reason')
_RESOLVER_VALUES = (':resolver-revision', ':resolver-evaluated-at')


def _receipt_shape(snapshot, protocol, authorization, root, check):
    """Validate a real old receipt and collect only its exact generated children."""
    before = _read_authorization_receipt(snapshot, protocol, authorization, root)
    members = read_relation(snapshot, root, budget=MAX_RECEIPT_RELATION_MEMBERS + 1)
    children = {}
    cursor, index = root, 0
    while cursor != NULL_CELL_ID:
        check()
        if index >= MAX_RECEIPT_RELATION_MEMBERS or cursor != (root if index == 0 else root + ':chain:' + str(index)):
            raise InvalidCell('legacy receipt exceeds bounded generated custody shape')
        chain = snapshot.cells[cursor]
        incidence = snapshot.cells[chain.link0]
        if incidence.id != root + ':incidence:' + str(index):
            raise InvalidCell('legacy receipt incidence ownership differs')
        if cursor != root:
            children[cursor] = chain
        children[incidence.id] = incidence
        cursor, index = chain.link1, index + 1
    if index != len(members):
        raise InvalidCell('legacy receipt membership count differs')
    suffixes = _VALUES + (_RESOLVER_VALUES if before.resolver_protocol_root is not None else ())
    values = {}
    for suffix in suffixes:
        cell = snapshot.cells[root + suffix]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell('legacy receipt terminal links differ')
        values[cell.id] = cell.atom.decode('utf-8')
        children[cell.id] = cell
    payload = {'version': 1, 'members': [(m.role_id, m.participant_id) for m in members],
               'values': values}
    compact = Cell(root, NULL_CELL_ID, NULL_CELL_ID,
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    prospective = Snapshot(snapshot.revision, ChainMap({root: compact}, snapshot.cells))
    if _read_authorization_receipt(prospective, protocol, authorization, root) != before:
        raise InvalidCell('compact receipt projection differs from original')
    return before, compact, children


def _begin_receipt(history, store, session, original, compact, activity, check):
    control = json.dumps({'receipt_root': original.id, 'root_digest': _trace_cell_digest(original),
        'target_digest': _trace_cell_digest(compact)}, sort_keys=True, separators=(',', ':'))
    with history._transaction(write=True, before_commit=check):
        state = history._db.execute('SELECT * FROM trace_migrations WHERE conversation_id=?', (session,)).fetchone()
        if state is None:
            if history._db.execute('SELECT 1 FROM conversations WHERE id=?', (session,)).fetchone():
                raise InvalidCell('receipt destination conversation is already owned')
            history._db.execute('INSERT INTO conversations(id) VALUES(?)', (session,))
            history._db.execute('INSERT INTO trace_migrations VALUES(?,?,?,?,?,?,0,?,?,?)',
                (session, store.authority_identity, store.revision, original.id, '', control,
                 'receipt-copying', session, activity))
            return ''
        if state['source_authority'] != store.authority_identity or state['state'] not in ('bound', 'receipt-copying'):
            raise InvalidCell('receipt migration destination has another owner')
        if state['state'] == 'receipt-copying':
            if state['controls'] != control:
                raise InvalidCell('pending receipt custody changed')
            return state['cursor']
        # A kill between the bound seal and graph commit replays that exact
        # receipt without recopying an already durable prefix.
        cursor = state['cursor'] if state['controls'] == control else ''
        history._db.execute("UPDATE trace_migrations SET state='receipt-copying',delta_cell=?,cursor=?,controls=?,last_activity_at=? WHERE conversation_id=?",
            (original.id, cursor, control, activity, session))
        return cursor


def _register_children(history, session, root, cells, activity, cursor, check):
    """Commit an exact custody page and its progress before graph publication."""
    with history._transaction(write=True, before_commit=check):
        for cell in cells:
            check()
            digest = _trace_cell_digest(cell)
            previous = history._db.execute('SELECT digest,owned FROM trace_migration_cells WHERE conversation_id=? AND cell_id=?',
                (session, cell.id)).fetchone()
            owned = int(cell.id != root)
            if previous is not None and tuple(previous) != (digest, owned):
                raise InvalidCell('receipt registered custody differs')
            history._db.execute('INSERT OR IGNORE INTO trace_migration_cells VALUES(?,?,?,1,?,?,0)',
                (session, cell.id, digest, owned, activity if owned else None))
        history._db.execute('UPDATE trace_migrations SET cursor=? WHERE conversation_id=?', (cursor, session))


class _ReceiptCustody:
    """Process-local exact proof, tied to unchanged live and cold generations.

    Only copy progress survives a process restart. A verification cursor is
    meaningful solely while these pinned connections and witnesses survive.
    """
    def __init__(self, store, connection, archive, ordered, session):
        self.store, self.connection = store, connection
        self.ordered, self.session = ordered, session
        self.revision = store.revision
        self.source_version = connection.execute('PRAGMA data_version').fetchone()[0]
        self.cold = _open_trace_archive(archive, store.authority_identity, create=False, check_same_thread=False)
        try:
            self.witness = _open_trace_archive(archive, store.authority_identity, create=False, check_same_thread=False)
            self.cold_version = self.witness.execute('PRAGMA data_version').fetchone()[0]
            self.cold.execute('BEGIN')
            self.cold.execute('SELECT authority FROM trace_identity WHERE singleton=1').fetchone()
        except BaseException:
            self.close()
            raise
        self.index, self.version, self.current = 0, -1, True
        self.index_pending = []
        self.verified_rows = 0

    def close(self):
        for name in ('cold', 'witness'):
            connection = getattr(self, name, None)
            if connection is not None:
                connection.close()
                setattr(self, name, None)

    def guard(self):
        if (self.store.revision != self.revision
                or self.connection.execute('PRAGMA data_version').fetchone()[0] != self.source_version
                or self.witness.execute('PRAGMA data_version').fetchone()[0] != self.cold_version):
            raise ArchiveConflict('receipt custody generation changed during verification')

    def advance(self, check, *, max_rows=256):
        self.guard()
        for _ in range(max_rows):
            check()
            if self.index == len(self.ordered):
                self.guard()
                return True
            cell = self.ordered[self.index]
            if self.current:
                live = self.connection.execute('SELECT cell_id,revision,link0,link1,atom FROM current_cells WHERE cell_id=?', (cell.id,)).fetchone()
                held = self.cold.execute('SELECT cell_id,revision,link0,link1,atom,session_id,digest FROM trace_current WHERE cell_id=?', (cell.id,)).fetchone()
                if live is None or held is None:
                    raise ArchiveConflict('receipt verified custody is incomplete')
                expected = (*live, self.session)
                if (Cell(live[0], live[2], live[3], bytes(live[4])) != cell
                        or tuple(held) != (*expected, _trace_digest(expected))):
                    raise ArchiveConflict('receipt current custody differs')
                self.current = False
                self.index_pending.append(cell.id)
            else:
                live = self.connection.execute('SELECT revision,cell_id,link0,link1,atom,rowid FROM cell_versions WHERE cell_id=? AND revision>? ORDER BY revision LIMIT 1', (cell.id, self.version)).fetchone()
                held = self.cold.execute('SELECT revision,cell_id,link0,link1,atom,source_rowid,digest FROM trace_versions WHERE cell_id=? AND revision>? ORDER BY revision LIMIT 1', (cell.id, self.version)).fetchone()
                if live is None and held is None:
                    if self.version < 0:
                        raise ArchiveConflict('receipt historical custody is missing')
                    self.index, self.version, self.current = self.index+1, -1, True
                elif live is None or held is None or tuple(held) != (*live, _trace_digest(live)):
                    raise ArchiveConflict('receipt historical custody differs')
                else:
                    self.version = live[0]
            self.verified_rows += 1
        self.guard()
        return self.index == len(self.ordered)


def close_trace_receipt_preparation(service):
    proof = getattr(service, '_receipt_custody', None)
    if proof is not None:
        proof.close()
        service._receipt_custody = None
    service._receipt_conversion = None


def _convert_receipt(service, history, snapshot, session, root, activity, context, check):
    owner = service._owner
    store, registry = owner.universal_store, owner.universal_registry
    protocol, authorization = registry.agent_body.protocol, registry.authorization.protocol
    original = snapshot.cells[root]
    cached = getattr(service, '_receipt_conversion', None)
    if cached is None or cached[0] != original:
        before, compact, children = _receipt_shape(snapshot, protocol, authorization, root, check)
        ordered = sorted((original, *children.values()), key=lambda cell: cell.id)
        service._receipt_conversion = (original, before, compact, children, ordered)
    else:
        _, before, compact, children, ordered = cached
    cursor = _begin_receipt(history, store, session, original, compact, activity, check)
    connection, _ = store.sqlite_storage()
    archive = trace_archive_path(service._path)
    import bisect
    start = bisect.bisect_right(ordered, cursor, key=lambda cell: cell.id)
    selected = ordered[start:start+256]
    copied, versions = 0, 0
    if selected:
        for cell in selected:
            check()
            if snapshot.cells.get(cell.id) != cell:
                raise InvalidCell('pending receipt source changed during copy')
        batch = choose_trace_batch(connection, tuple(cell.id for cell in selected), check)
        cold, versions = preserve_trace_batch(connection, archive, store.authority_identity,
                batch, {identifier: session for identifier in batch}, check)
        with closing(cold):
            # The cold owner commits and read-verifies current bytes and all
            # versions before this content index is durably committed.
            history.index_trace_archive(cold, (session,), archive_path=archive,
                                        cell_ids=batch, check=check)
        _register_children(history, session, root, selected[:len(batch)], activity, batch[-1], check)
        copied = len(batch)
        if start + copied < len(ordered):
            return dict(converted=0, copied=copied, versions=versions, pending=True)
    proof = getattr(service, '_receipt_custody', None)
    if proof is None:
        proof = service._receipt_custody = _ReceiptCustody(store, connection, archive, ordered, session)
    try:
        proof.guard()
        if proof.index_pending:
            history.index_trace_archive(proof.cold, (session,), archive_path=archive,
                cell_ids=tuple(proof.index_pending), check=check)
            proof.index_pending.clear()
        complete = proof.advance(check)
        if proof.index_pending:
            history.index_trace_archive(proof.cold, (session,), archive_path=archive,
                cell_ids=tuple(proof.index_pending), check=check)
            proof.index_pending.clear()
        if not complete:
            return dict(converted=0, copied=copied, versions=versions, pending=True)
        # Also validate the existing content seal on an empty-atom retry. This
        # is O(1) for an unchanged owner generation and detects index tampering
        # even when this final page contained only historical version rows.
        history.index_trace_archive(proof.cold, (session,), archive_path=archive,
            cell_ids=(root,), check=check)
        if _read_authorization_receipt(snapshot, protocol, authorization, root) != before:
            raise InvalidCell('copied receipt projection changed before publication')
        proof.guard()
        with history._transaction(write=True, before_commit=check):
            history._db.execute("UPDATE trace_migrations SET state='bound' WHERE conversation_id=?", (session,))
            history._db.execute('UPDATE trace_receipt_state SET dirty=1 WHERE singleton=1')
        check()
        _authorize(service, snapshot, context)
        with commit_intent.declare(commit_intent.MIGRATION,
                actor=registry.authorization.subject_root,
                reason='Archive verified obsolete Agent Session receipt scaffolding'):
            registry.authorization.broker.commit_authenticated(context, store, snapshot.revision,
                                                                replace=(compact,))
        _ack_receipt_revision(store, history, snapshot.revision, root)
    except TimeoutError:
        raise
    except BaseException:
        close_trace_receipt_preparation(service)
        raise
    if _read_authorization_receipt(store.snapshot(), protocol, authorization, root) != before:
        raise InvalidCell('published compact receipt projection differs')
    close_trace_receipt_preparation(service)
    return dict(converted=1, copied=copied, versions=versions, pending=False)


def _ack_receipt_revision(store, history, before_revision, root):
    """The known root-only commit removes edges; keep its old frontier safely.

    This runs under the same exclusive owner/store locks. An unrelated revision
    or any new candidate/trace dependency takes the normal delta/retain path.
    """
    if store.revision != before_revision + 1:
        return
    connection, _ = store.sqlite_storage()
    changed = connection.execute('SELECT cell_id,link0,link1 FROM cell_versions WHERE revision=? LIMIT 257',
        (store.revision,)).fetchall()
    if len(changed) > 256 or not any(row[0] == root for row in changed):
        return
    for identifier, link0, link1 in changed:
        if (identifier != root and _family_descriptor(history, identifier)[1]
                or any(_family_descriptor(history, target)[1] for target in (link0, link1))):
            return
    with history._transaction(write=True):
        history._db.execute("UPDATE trace_family_state SET watermark=?,delta_revision=?,delta_cell='' WHERE singleton=1 AND watermark=? AND phase IN ('export','complete')",
            (store.revision, store.revision+1, before_revision))
        # Only this exact root-only rewrite can preserve the catalog's actual
        # read projection. A broader or foreign commit needs a real new walk.
        cached = getattr(store, '_trace_registry_cache', None)
        if (len(changed) == 1 and changed[0][0] == root and cached is not None
                and cached['complete'] and cached['revision'] == before_revision
                and cached['data_version'] == connection.execute('PRAGMA data_version').fetchone()[0]):
            changed_registry = history._db.execute("UPDATE trace_registry_state SET source_revision=? WHERE singleton=1 AND source_revision=? AND phase IN ('ordinary','complete')",
                (store.revision, before_revision)).rowcount
            if changed_registry:
                cached['revision'] = store.revision


def _boot_receipt_roots(registry):
    # Startup compares these graph receipts with their original publication.
    # Include the exact owner's close root even if it was closed after the
    # registry Session projection was captured.
    agent = registry.agent_body
    session = agent.session
    return frozenset(root for root in (agent.body.creation_receipt_root,
        session.view_receipt_root, session.scope_receipt_root, session.close_receipt_root,
        *(session.root_id + suffix for suffix in _SUFFIXES)) if root)


def _eligible_receipt(snapshot, history, protocol, root, cutoff, *, protected_roots=()):
    if root in protected_roots:
        return None
    suffix = next((value for value in _SUFFIXES if root.endswith(value)), None)
    if suffix is None or not root.startswith(_PREFIX) or snapshot.cells[root].atom:
        return None
    session = root[:-len(suffix)]
    if session not in snapshot.cells:
        # The generic verified family owner admits orphan trace relations.
        # This converter only rewrites a receipt retained by a typed Session.
        return None
    members = read_relation(snapshot, session, budget=MAX_RECEIPT_RELATION_MEMBERS + 1)
    role = 'session-' + suffix[1:]
    receipts = tuple(m.participant_id for m in members if m.role_id == protocol.role(role))
    if receipts != (root,):
        raise InvalidCell('legacy receipt is outside its typed session owner')
    states = tuple(m.participant_id for m in members if m.role_id == protocol.role('session-state'))
    if len(states) != 1 or states[0] not in (protocol.state('active'), protocol.state('closed')):
        raise InvalidCell('legacy receipt session lifecycle differs')
    # These two exact groups cover the session/view/scope chain and the
    # additional close-receipt chain without a repeated live-prefix aggregate.
    ages = history._db.execute('SELECT last_activity_at FROM trace_family_sessions WHERE session_id IN (?,?)',
        (session, session + ':close-receipt')).fetchall()
    if not ages or max(row[0] for row in ages) >= cutoff:
        return None
    return session, max(row[0] for row in ages)


def maintain_trace_receipts(service, *, authentication_context, timeout_seconds=2.0,
                            max_cells=256, cancellation_event=None):
    """One receipt/root inventory page, after the family age scan and before export.

    A completed pass resets family protection ONCE if any root changed. Existing
    registered ownership then admits exact orphan children to normal partition.
    """
    if authentication_context is None:
        raise AuthorizationDenied('receipt maintenance requires process authentication')
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 2 or type(max_cells) is not int or not 1 <= max_cells <= 256
            or cancellation_event is not None and not callable(getattr(cancellation_event, 'is_set', None))):
        raise ValueError('receipt maintenance bounds are invalid')
    deadline = time.monotonic() + timeout_seconds
    owner = service._owner
    def check():
        if time.monotonic() >= deadline or cancellation_event is not None and cancellation_event.is_set():
            raise TimeoutError('receipt maintenance cancelled or budget exhausted')
        if _user_is_active(owner):
            raise TimeoutError('receipt maintenance yielded to foreground activity')
    result = dict(status='receipt-deferred', inspected=0, converted=0, copied=0, versions=0, next_cursor=None)
    if _user_is_active(owner):
        try:
            with _short_lock(owner.mutation_lock, lambda: None):
                close_trace_receipt_preparation(service)
        except TimeoutError:
            return result
        return {**result, 'status': 'waiting-for-idle'}
    try:
        with _short_lock(owner.mutation_lock, check):
            service._require_live_owner()
            store, registry = owner.universal_store, owner.universal_registry
            with _short_lock(registry.authorization.broker._lock, check), registry.authorization.broker.live_context(authentication_context):
                with _short_lock(store._lock, check):
                    snapshot = store.snapshot()
                    protected_roots = _boot_receipt_roots(registry)
                    _authorize(service, snapshot, authentication_context)
                    history = _legacy_trace_history(service, snapshot)
                    history.initialize_trace_maintenance()
                    history.admit_trace_custody(store.authority_identity, registry.application_root)
                    state = history._db.execute('SELECT * FROM trace_receipt_state WHERE singleton=1').fetchone()
                    if state is not None and state['next_due_at'] > time.time():
                        return {**result, 'status': 'receipts-complete'}
                    family = history._db.execute('SELECT phase,watermark FROM trace_family_state WHERE singleton=1').fetchone()
                    if family is None or family['watermark'] != store.revision or family['phase'] not in ('export', 'complete'):
                        advanced = _advance_family_inventory(store, history, check, max_cells)
                        return {**result, 'status': 'receipt-preparing', 'family_status': advanced['status']}
                    with history._transaction(write=True, before_commit=check):
                        history._db.execute("INSERT OR IGNORE INTO trace_receipt_state(singleton,cursor,dirty,next_due_at) VALUES(1,'',0,0)")
                    cursor = state['cursor'] if state is not None else ''
                    connection, _ = store.sqlite_storage()
                    rows = connection.execute('SELECT cell_id FROM current_cells WHERE cell_id>? AND cell_id>=? AND cell_id<? ORDER BY cell_id LIMIT ?',
                        (cursor, _PREFIX, 'app:agent-session;', max_cells)).fetchall()
                    if not rows:
                        with history._transaction(write=True, before_commit=check):
                            dirty = history._db.execute('SELECT dirty FROM trace_receipt_state WHERE singleton=1').fetchone()[0]
                            if dirty:
                                history._db.execute("UPDATE trace_family_state SET phase='reset' WHERE singleton=1")
                            history._db.execute("UPDATE trace_receipt_state SET cursor='',dirty=0,next_due_at=? WHERE singleton=1", (time.time()+3600,))
                        return {**result, 'status': 'receipt-reset' if dirty else 'receipts-complete', 'reset_family': bool(dirty)}
                    for (root,) in rows:
                        check()
                        candidate = _eligible_receipt(snapshot, history, registry.agent_body.protocol,
                            root, time.time() - _RETENTION_SECONDS, protected_roots=protected_roots)
                        result['inspected'] += 1
                        if candidate is not None:
                            result.update(_convert_receipt(service, history, snapshot, candidate[0], root,
                                candidate[1], authentication_context, check))
                            if result.get('pending'):
                                return {**result, 'status': 'receipt-copying'}
                        if result['converted']:
                            break
                    # Only completed roots reach this checkpoint. A pending
                    # conversion returns above and retries the same root.
                    with history._transaction(write=True, before_commit=check):
                        history._db.execute('UPDATE trace_receipt_state SET cursor=? WHERE singleton=1', (root,))
                    return {**result, 'status': 'receipt-scanning'}
    except (TimeoutError, sqlite3.OperationalError) as error:
        if isinstance(error, sqlite3.OperationalError) and (
                getattr(error, 'sqlite_errorcode', 0) & 255) not in (
                sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT):
            raise
        if _user_is_active(owner) or cancellation_event is not None and cancellation_event.is_set():
            try:
                with _short_lock(owner.mutation_lock, lambda: None):
                    close_trace_receipt_preparation(service)
            except TimeoutError:
                # The next owner call retries cleanup without blocking work.
                return {**result, 'cleanup_pending': True}
        return result
