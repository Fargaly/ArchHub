"""Conservative owner admission for ordinary conversation retention.

The caller holds mutation_lock, broker.live_context and stable_snapshot. Existing
composer/native exclusion is acquired without waiting and held through the caller's
ordinary database commit. This module neither activates retention nor writes Cells.
"""
from collections.abc import Mapping
from contextlib import contextmanager
import time

from .cell_protocols import read_relation
from .cell_state_machine import read_instance_state_machine
from .conversation_content import read_content_binding, read_content_space
from .universal_cell import InvalidCell, NULL_CELL_ID, Snapshot


_MAX_REGISTRY_ROWS = 256
_MAX_CELL_READS = 65_536
_MAX_ATOM_BYTES = 8 * 1024 * 1024
_MAX_READ_SECONDS = 2.0
_STATES = frozenset(('open', 'claimed', 'blocked', 'review', 'complete', 'cancelled'))
_TERMINAL = frozenset(('complete', 'cancelled'))


class _Refusal(InvalidCell):
    """Only locally authored, metadata-free diagnostics cross this boundary."""


class _ReadBudgetExceeded(RuntimeError):
    # Separate from InvalidCell: tolerant existing projections must not swallow
    # an exhausted total budget while probing optional protocol capabilities.
    pass


class _BoundedCells(Mapping):
    def __init__(self, cells, check_budget=None):
        self._cells = cells
        self._check_budget = check_budget
        self._reads = 0
        self._bytes = 0
        self._deadline = time.monotonic() + _MAX_READ_SECONDS

    def __getitem__(self, root):
        if self._check_budget is not None:
            try:
                self._check_budget()
            except TimeoutError:
                raise _ReadBudgetExceeded() from None
        self._reads += 1
        if self._reads > _MAX_CELL_READS or time.monotonic() > self._deadline:
            raise _ReadBudgetExceeded()
        cell = self._cells[root]
        self._bytes += len(cell.atom)
        if self._bytes > _MAX_ATOM_BYTES:
            raise _ReadBudgetExceeded()
        return cell

    def __iter__(self):
        raise _ReadBudgetExceeded()

    def __len__(self):
        raise _ReadBudgetExceeded()


def _one(rows, role):
    roots = tuple(row.participant_id for row in rows if row.role_id == role)
    if len(roots) != 1:
        raise _Refusal('Retention requires unambiguous graph control relations')
    return roots[0]


def _roots(snapshot, root, role, *, core=None):
    rows = read_relation(snapshot, root, budget=2 * (_MAX_REGISTRY_ROWS + 4) + 1,
        retain_projection=False)
    if len(rows) > _MAX_REGISTRY_ROWS + len(core or {}):
        raise _Refusal('Retention registry exceeds its bounded graph review; reconcile Work first')
    allowed = {role, *(core or {})}
    if any(row.role_id not in allowed for row in rows):
        raise _Refusal('Retention registry contains an unknown control relation')
    for control_role, expected in (core or {}).items():
        actual = tuple(row.participant_id for row in rows if row.role_id == control_role)
        if actual != (expected,):
            raise _Refusal('Retention Work registry authority changed; reconcile its graph controls')
    roots = tuple(row.participant_id for row in rows if row.role_id == role)
    if len(roots) > _MAX_REGISTRY_ROWS or len(roots) != len(set(roots)):
        raise _Refusal('Retention registry is ambiguous or exceeds its bounded graph review')
    return roots


def _work_scopes(snapshot, registry, conversation_root):
    from .universal_application import _governed_work_interface_target

    current = read_content_binding(snapshot, registry.deliberation_protocol,
        application_root=registry.application_root, space_root=conversation_root)
    definition = registry.standard_library.governed_domains.definitions['governed-work'].definition_root
    roots = _roots(snapshot, registry.governed_work_registry_root, registry.roles['member'], core={
        registry.roles['authority']:definition,
        registry.roles['owner']:registry.authorization.subject_root,
        registry.roles['scope']:registry.map.domains['brain']})
    scopes = {}
    validated_rooms = {conversation_root:current}
    for root in roots:
        members = read_relation(snapshot, root, budget=2048, retain_projection=False)
        if _one(members, registry.assembly_protocol.role('provenance')) != definition:
            raise _Refusal('Retention found Work with unknown assembly authority')
        scope = _governed_work_interface_target(snapshot, registry, root, 'scope')
        if scope not in validated_rooms:
            try:
                validated_rooms[scope] = read_content_binding(snapshot, registry.deliberation_protocol,
                    application_root=registry.application_root, space_root=scope)
            except InvalidCell:
                raise _Refusal('Retention found unmapped Work; review its exact conversation scope first') from None
        bound = validated_rooms[scope]
        if (bound.instance_root, bound.instance_id) != (current.instance_root, current.instance_id):
            raise _Refusal('Retention found Work outside this conversation instance')
        scopes[root] = scope
        machine = read_instance_state_machine(snapshot, registry.assembly_protocol,
            registry.standard_library.state_machine_protocol, root)
        state_cell = snapshot.cells[machine.current_state_root]
        if state_cell.link0 != NULL_CELL_ID or state_cell.link1 != NULL_CELL_ID:
            raise _Refusal('Retention found an unknown Work state; reconcile its state machine')
        state = state_cell.atom.decode('utf-8').casefold()
        if state not in _STATES:
            raise _Refusal('Retention found an unknown Work state; reconcile its state machine')
        if scope == conversation_root and state not in _TERMINAL:
            raise _Refusal('Retention is protected by nonterminal Work in this conversation')
    return scopes


def _execution_clear(snapshot, protocol, adapters, family, work_scopes, conversation_root):
    if family == 'model':
        from .cell_model_execution import read_model_delegation as read_delegation
        from .cell_model_execution import read_model_execution_grant as read_grant
        from .cell_model_execution import read_model_execution_receipt as read_receipt
    elif family == 'connector':
        from .cell_connector_execution import read_connector_delegation as read_delegation
        from .cell_connector_execution import read_connector_execution_grant as read_grant
        from .cell_connector_execution import read_connector_execution_receipt as read_receipt
    else:
        raise _Refusal('Retention execution protocol is unknown')
    roots = {name:_roots(snapshot, protocol.registry(name), protocol.role('registry-member'))
        for name in ('delegation', 'grant', 'receipt')}
    delegations = {}
    for root in roots['delegation']:
        row = read_delegation(snapshot, protocol, adapters, root)
        if row.work_root not in work_scopes:
            raise _Refusal('Retention found execution with unmapped Work; reconcile its conversation scope')
        delegations[root] = row
    grants = {}
    for root in roots['grant']:
        row = read_grant(snapshot, protocol, adapters, root)
        if row.delegation_root not in delegations:
            raise _Refusal('Retention found a grant without its registered delegation')
        grants[root] = row
    receipts = {}
    settled_delegations = set()
    for root in roots['receipt']:
        row = read_receipt(snapshot, protocol, adapters, root)
        if (row.grant_root not in grants or row.delegation_root not in delegations
                or grants[row.grant_root].delegation_root != row.delegation_root
                or row.grant_root in receipts or row.delegation_root in settled_delegations):
            raise _Refusal('Retention found ambiguous execution settlement; reconcile its exact receipts')
        receipts[row.grant_root] = row
        settled_delegations.add(row.delegation_root)
    for root, row in grants.items():
        delegation = delegations[row.delegation_root]
        if work_scopes[delegation.work_root] == conversation_root and root not in receipts:
            raise _Refusal('Retention is protected by an unsettled grant; reconcile its exact receipt, including expired grants')
    for root, row in delegations.items():
        if work_scopes[row.work_root] == conversation_root and root not in settled_delegations:
            raise _Refusal('Retention is protected by an unsettled delegation; reconcile its execution evidence')


def _durable_clear(snapshot, registry, conversation_root, check_budget=None):
    bounded = Snapshot(snapshot.revision, _BoundedCells(snapshot.cells, check_budget))
    try:
        # Owner/store locks were acquired before the journal read scope. Never
        # invoke admission callbacks or acquire any other lock inside this scope.
        with snapshot.read_scope():
            scopes = _work_scopes(bounded, registry, conversation_root)
            _execution_clear(bounded, registry.baboom_model_execution_protocol,
                registry.adapter_protocol, 'model', scopes, conversation_root)
            _execution_clear(bounded, registry.baboom_connector_execution_protocol,
                registry.adapter_protocol, 'connector', scopes, conversation_root)
    except _Refusal:
        raise
    except _ReadBudgetExceeded:
        raise _Refusal('Retention exceeded its bounded graph review; reconcile Work before retrying') from None
    except Exception:
        # Existing protocol errors can include raw root IDs or record values.
        raise _Refusal('Retention could not verify Work or execution evidence; reconcile its graph controls') from None


def _runtime_clear(owner, native):
    try:
        if (owner._model_execution_active is not False
                or owner._model_execution_closing is not False
                or not owner._model_execution_idle.is_set()):
            raise _Refusal('Retention is protected while model or project execution is active or closing')
        if owner._project_work_pending is not None:
            raise _Refusal('Retention is protected by a pending project result; reconcile its receipt')
        if native is not None and (native._status != {'state':'idle'}
                or native._cancel.is_set() or native._project is not False
                or any(getattr(native, field) is not None for field in
                    ('_identity', '_browser_binding', '_prepared', '_grant', '_settled'))):
            raise _Refusal('Retention is protected by native Workshop work; reconcile and release its operation')
    except _Refusal:
        raise
    except Exception:
        raise _Refusal('Retention runtime state is unavailable; restore a verified idle owner') from None


def _reader_participants(snapshot, registry, conversation_root, check_budget):
    bounded = Snapshot(snapshot.revision, _BoundedCells(snapshot.cells, check_budget))
    try:
        with snapshot.read_scope():
            roots = read_content_space(bounded, registry.deliberation_protocol,
                conversation_root).participant_roots
        if (len(roots) > _MAX_REGISTRY_ROWS or len(roots) != len(set(roots))
                or any(type(root) is not str or not root for root in roots)):
            raise _Refusal('Retention room participants exceed the bounded graph review or are ambiguous')
        return tuple(roots)
    except _Refusal:
        raise
    except Exception:
        raise _Refusal('Retention could not verify room participants within its bounded graph review') from None


def _native_readers_clear(bindings, participants):
    # Look up only this room's admitted principals. Never scan/copy the global
    # registry or inspect its credential fields. Recovery-read capabilities only
    # admit Work recovery routes and cannot read ordinary conversations.
    now = time.time()
    for root in participants:
        if root not in bindings:
            continue
        binding = bindings[root]
        if type(binding) is not dict:
            raise _Refusal('Retention native reader metadata is unavailable; reconcile its session')
        issued, expires = binding.get('issued_at'), binding.get('expires_at')
        if (any(type(value) not in (int, float) or not 0 < value <= 253402300799
                for value in (issued, expires)) or issued > now or expires <= issued):
            raise _Refusal('Retention native reader lifetime is uncertain; reconcile its session')
        if expires > now:
            raise _Refusal('Retention is protected by an active native reader in this room')


@contextmanager
def admit_conversation_retention(owner, snapshot, conversation_root, *, before_commit, check_budget=None):
    """Yield the final admission callback, retaining runtime exclusion until exit.

    Generic active model work has no proven room pointer and protects all rooms.
    Durable Work with a validated scope protects its own room; unmapped or malformed
    evidence protects all rooms. Expiry never proves that an invocation settled.
    """
    if type(conversation_root) is not str or not conversation_root or not callable(before_commit):
        raise _Refusal('Retention requires an exact conversation and final admission callback')
    if check_budget is not None and not callable(check_budget):
        raise _Refusal('Retention requires a trusted budget callback')
    owner_lock = owner.mutation_lock
    store, registry = owner.universal_store, owner.universal_registry
    composer = owner._composer_planning_slot
    native = getattr(owner, '_existing_workshop_native_host', None)
    native_lock = getattr(native, '_action', None) if native is not None else None
    session_lock = getattr(owner, '_machine_agent_session_lock', None)
    bindings = getattr(owner, '_machine_agent_sessions', None)
    held = []
    active = False

    def check_pinned():
        if not callable(getattr(owner_lock, '_is_owned', None)) or not owner_lock._is_owned():
            raise _Refusal('Retention requires the owner mutation lock')
        store_lock = getattr(store, '_lock', None)
        if not callable(getattr(store_lock, '_is_owned', None)) or not store_lock._is_owned():
            raise _Refusal('Retention requires the pinned graph lock on this thread')
        if (owner.mutation_lock is not owner_lock or owner.universal_store is not store
                or owner.universal_registry is not registry
                or getattr(store, '_stable_snapshot_depth', 0) < 1
                or store.revision != snapshot.revision or store.snapshot().cells is not snapshot.cells):
            raise _Refusal('Retention requires the same pinned graph snapshot and owner')

    def check_runtime_identity():
        if (owner._composer_planning_slot is not composer
                or getattr(owner, '_existing_workshop_native_host', None) is not native
                or native is not None and native._action is not native_lock
                or getattr(owner, '_machine_agent_session_lock', None) is not session_lock
                or getattr(owner, '_machine_agent_sessions', None) is not bindings
                or active and not session_lock._is_owned()):
            raise _Refusal('Retention runtime owner changed; retry against the current owner')

    def guard():
        if not active:
            raise _Refusal('Retention runtime exclusion is no longer held')
        check_pinned()
        check_runtime_identity()
        before_commit()
        check_pinned()
        check_runtime_identity()
        _runtime_clear(owner, native)
        _native_readers_clear(bindings, participants)

    check_pinned()
    before_commit()
    check_pinned()
    try:
        # Native perform takes _action before mutation_lock. Waiting here would
        # deadlock that order; a failed nonblocking acquire must refuse immediately.
        for lock, label in ((composer, 'composer'), (native_lock, 'native Workshop'),
                (session_lock, 'native session registry')):
            if lock is None:
                if label == 'native Workshop' and native is None:
                    continue
                raise _Refusal('Retention runtime exclusion lock is unavailable')
            if not lock.acquire(blocking=False):
                raise _Refusal('Retention is protected while '+label+' is busy')
            held.append(lock)
        if (type(bindings) is not dict or not callable(getattr(session_lock, '_is_owned', None))
                or not session_lock._is_owned()):
            raise _Refusal('Retention native session registry is unavailable')
        participants = _reader_participants(snapshot, registry, conversation_root, check_budget)
        active = True
        guard()
        _durable_clear(snapshot, registry, conversation_root, check_budget)
        guard()
        yield guard
    finally:
        active = False
        for lock in reversed(held):
            lock.release()


__all__ = ['admit_conversation_retention']
