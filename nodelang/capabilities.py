"""Unforgeable process-local host capabilities for the universal cell floor.

Handles are deliberately not Cells and cannot be serialized. They terminate
the semantic graph at a real authority boundary. Requests, authority roots,
results, denials, and eventual projected audit records are Cells; the live host
function and possession token remain trusted runtime state.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
import math
import secrets
import threading
import time
from types import MappingProxyType
from typing import Callable, Mapping
import uuid

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


_MINT_KEY = object()

ROLE_NAMES = (
    "vocabulary-member",
    "grant-member",
    "event-member",
    "policy-id",
    "handle-fingerprint",
    "request-scope",
    "authority-scope",
    "session-scope",
    "device-scope",
    "data-class-scope",
    "expires-at",
    "max-invocations",
    "invocation-count",
    "state",
    "event-grant",
    "event-request",
    "event-authority",
    "event-result",
    "event-outcome",
    "event-reason",
    "event-recorded-at",
)
GRANT_STATES = ("active", "revoked")
EVENT_OUTCOMES = ("allowed", "denied", "failed")


class CapabilityDenied(PermissionError):
    """A caller lacks a live capability or supplied invalid graph roots."""


@dataclass(frozen=True, slots=True)
class CapabilityProtocol:
    root_id: str
    roles: Mapping[str, str]
    grant_states: Mapping[str, str]
    event_outcomes: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown capability role") from exc


@dataclass(frozen=True, slots=True)
class CapabilityGrantProjection:
    root_id: str
    policy_id: str
    handle_fingerprint_digest: str
    request_scope_roots: tuple[str, ...]
    authority_scope_roots: tuple[str, ...]
    session_scope_roots: tuple[str, ...]
    device_scope_roots: tuple[str, ...]
    data_class_scope: tuple[str, ...]
    expires_at: float
    max_invocations: int
    invocation_count: int
    state_root: str
    state_incidence: str


@dataclass(frozen=True, slots=True)
class CapabilityEventProjection:
    root_id: str
    grant_root: str
    request_root: str
    authority_root: str
    result_root: str
    outcome: str
    reason: str
    recorded_at: float


class CapabilityHandle:
    """An unforgeable-by-data token whose object identity conveys authority."""

    __slots__ = ("_fingerprint",)

    def __init__(self, mint_key: object) -> None:
        if mint_key is not _MINT_KEY:
            raise CapabilityDenied("capabilities can only be minted by a broker")
        self._fingerprint = secrets.token_hex(12)

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def __repr__(self) -> str:
        return "<CapabilityHandle %s>" % self._fingerprint

    def __reduce_ex__(self, protocol):
        raise TypeError("live capability handles cannot be serialized")


@dataclass(frozen=True, slots=True)
class CapabilityEvent:
    timestamp: float
    handle_fingerprint: str
    policy_id: str
    request_root: str
    authority_root: str
    outcome: str
    reason: str
    grant_root: str = ""


@dataclass(frozen=True, slots=True)
class CapabilityPolicy:
    """Trusted-host grant limits referencing inspectable graph identities."""

    policy_id: str
    request_roots: frozenset[str]
    authority_roots: frozenset[str]
    expires_at: float
    max_invocations: int
    session_roots: frozenset[str] = field(default_factory=frozenset)
    device_roots: frozenset[str] = field(default_factory=frozenset)
    data_classes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("capability policy requires an identity")
        if not self.request_roots or not self.authority_roots:
            raise ValueError("capability policy scopes cannot be empty")
        if self.max_invocations < 1:
            raise ValueError("capability invocation budget must be positive")
        for roots in (
            self.request_roots,
            self.authority_roots,
            self.session_roots,
            self.device_roots,
        ):
            if type(roots) is not frozenset or any(
                type(root) is not str or not root for root in roots
            ):
                raise ValueError("capability root scopes must be frozen strings")
        if type(self.data_classes) is not frozenset or any(
            type(item) is not str or not item for item in self.data_classes
        ):
            raise ValueError("capability data classes must be frozen strings")


@dataclass(slots=True)
class _Entry:
    handler: Callable[[Snapshot, str, str], str]
    policy: CapabilityPolicy
    grant_root: str
    active: bool = True
    invocation_count: int = 0


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("capability %s is invalid" % label) from exc


def _one(members, role_root: str, label: str):
    values = [member for member in members if member.role_id == role_root]
    if len(values) != 1:
        raise InvalidCell("capability requires exactly one %s" % label)
    return values[0]


def _fingerprint_digest(fingerprint: str) -> str:
    return hashlib.sha256(fingerprint.encode("ascii")).hexdigest()


def _grant_root(fingerprint: str) -> str:
    return "capability-grant:sha256:" + _fingerprint_digest(fingerprint)


def _event_root() -> str:
    return "capability-event:%s" % uuid.uuid4().hex


def _finite_time(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("capability %s is invalid" % label) from exc
    if not math.isfinite(result):
        raise InvalidCell("capability %s is invalid" % label)
    return result


def bootstrap_capability_protocol(
    store: CellStore,
    *,
    prefix: str = "capability-protocol",
) -> CapabilityProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_capability_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in GRANT_STATES}
    outcomes = {
        name: "%s:outcome:%s" % (prefix, name)
        for name in EVENT_OUTCOMES
    }
    batch = CellBatch(store)
    for name, root in (*roles.items(), *states.items(), *outcomes.items()):
        batch.add(_terminal(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values(), *outcomes.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return CapabilityProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(outcomes),
    )


def project_capability_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "capability-protocol",
) -> CapabilityProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in GRANT_STATES}
    outcomes = {
        name: "%s:outcome:%s" % (prefix, name)
        for name in EVENT_OUTCOMES
    }
    required = {root_id, *roles.values(), *states.values(), *outcomes.values()}
    if required - set(snapshot.cells):
        raise InvalidCell("capability protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed = {
        roles["vocabulary-member"],
        roles["grant-member"],
        roles["event-member"],
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("capability protocol has an undeclared member")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    expected = {*roles.values(), *states.values(), *outcomes.values()}
    if vocabulary != expected:
        raise InvalidCell("capability protocol vocabulary drifted")
    return CapabilityProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(outcomes),
    )


def _scope_text(snapshot: Snapshot, root_id: str) -> str:
    return _text(snapshot, root_id, "scope value")


def read_capability_grant(
    snapshot: Snapshot,
    protocol: CapabilityProtocol,
    grant_root: str,
) -> CapabilityGrantProjection:
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("grant-member")
    }
    if grant_root not in registered:
        raise InvalidCell("capability grant is not registered")
    members = read_relation(snapshot, grant_root, budget=512)
    allowed = {
        protocol.role(name)
        for name in (
            "policy-id",
            "handle-fingerprint",
            "request-scope",
            "authority-scope",
            "session-scope",
            "device-scope",
            "data-class-scope",
            "expires-at",
            "max-invocations",
            "invocation-count",
            "state",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("capability grant contains an undeclared field")
    state = _one(members, protocol.role("state"), "grant state")
    if state.participant_id not in protocol.grant_states.values():
        raise InvalidCell("capability grant state is invalid")
    expires_at = _finite_time(
        _text(
            snapshot,
            _one(members, protocol.role("expires-at"), "expiry").participant_id,
            "expiry",
        ),
        "expiry",
    )
    try:
        max_invocations = int(_text(
            snapshot,
            _one(
                members,
                protocol.role("max-invocations"),
                "max invocations",
            ).participant_id,
            "max invocations",
        ))
        invocation_count = int(_text(
            snapshot,
            _one(
                members,
                protocol.role("invocation-count"),
                "invocation count",
            ).participant_id,
            "invocation count",
        ))
    except ValueError as exc:
        raise InvalidCell("capability invocation counters are invalid") from exc
    if max_invocations < 1 or invocation_count < 0:
        raise InvalidCell("capability invocation counters are invalid")
    return CapabilityGrantProjection(
        grant_root,
        _text(
            snapshot,
            _one(members, protocol.role("policy-id"), "policy id").participant_id,
            "policy id",
        ),
        _text(
            snapshot,
            _one(
                members,
                protocol.role("handle-fingerprint"),
                "handle fingerprint",
            ).participant_id,
            "handle fingerprint",
        ),
        tuple(
            member.participant_id
            for member in members
            if member.role_id == protocol.role("request-scope")
        ),
        tuple(
            member.participant_id
            for member in members
            if member.role_id == protocol.role("authority-scope")
        ),
        tuple(
            member.participant_id
            for member in members
            if member.role_id == protocol.role("session-scope")
        ),
        tuple(
            member.participant_id
            for member in members
            if member.role_id == protocol.role("device-scope")
        ),
        tuple(
            _scope_text(snapshot, member.participant_id)
            for member in members
            if member.role_id == protocol.role("data-class-scope")
        ),
        expires_at,
        max_invocations,
        invocation_count,
        state.participant_id,
        state.incidence_id,
    )


def read_capability_events(
    snapshot: Snapshot,
    protocol: CapabilityProtocol,
) -> tuple[CapabilityEventProjection, ...]:
    event_roots = tuple(
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("event-member")
    )
    events: list[CapabilityEventProjection] = []
    allowed = {
        protocol.role(name)
        for name in (
            "event-grant",
            "event-request",
            "event-authority",
            "event-result",
            "event-outcome",
            "event-reason",
            "event-recorded-at",
        )
    }
    for root in event_roots:
        members = read_relation(snapshot, root, budget=128)
        if any(member.role_id not in allowed for member in members):
            raise InvalidCell("capability event contains an undeclared field")
        outcome_root = _one(
            members, protocol.role("event-outcome"), "event outcome"
        ).participant_id
        if outcome_root not in protocol.event_outcomes.values():
            raise InvalidCell("capability event outcome is invalid")
        outcome = _text(snapshot, outcome_root, "event outcome")
        events.append(CapabilityEventProjection(
            root,
            _one(members, protocol.role("event-grant"), "event grant").participant_id,
            _text(
                snapshot,
                _one(
                    members,
                    protocol.role("event-request"),
                    "event request",
                ).participant_id,
                "event request",
            ),
            _text(
                snapshot,
                _one(
                    members,
                    protocol.role("event-authority"),
                    "event authority",
                ).participant_id,
                "event authority",
            ),
            _text(
                snapshot,
                _one(
                    members,
                    protocol.role("event-result"),
                    "event result",
                ).participant_id,
                "event result",
            ),
            outcome,
            _text(
                snapshot,
                _one(
                    members,
                    protocol.role("event-reason"),
                    "event reason",
                ).participant_id,
                "event reason",
            ),
            _finite_time(
                _text(
                    snapshot,
                    _one(
                        members,
                        protocol.role("event-recorded-at"),
                        "event time",
                    ).participant_id,
                    "event time",
                ),
                "event time",
            ),
        ))
    return tuple(events)


class CapabilityBroker:
    """Process-local mint, invocation, revocation, and bounded audit authority."""

    def __init__(
        self,
        *,
        audit_limit: int = 10_000,
        store: CellStore | None = None,
        protocol: CapabilityProtocol | None = None,
    ) -> None:
        if audit_limit < 1:
            raise ValueError("capability audit limit must be positive")
        if protocol is not None and store is None:
            raise ValueError("a graph capability protocol requires a CellStore")
        self._entries: dict[CapabilityHandle, _Entry] = {}
        self._events: deque[CapabilityEvent] = deque(maxlen=audit_limit)
        self._store = store
        self._protocol = (
            protocol
            if protocol is not None
            else bootstrap_capability_protocol(store)
            if store is not None
            else None
        )
        self._lock = threading.RLock()

    @property
    def protocol(self) -> CapabilityProtocol | None:
        return self._protocol

    def _commit_grant(self, handle: CapabilityHandle, policy: CapabilityPolicy) -> str:
        if self._store is None or self._protocol is None:
            return ""
        snapshot = self._store.snapshot()
        scoped_roots = (
            *policy.request_roots,
            *policy.authority_roots,
            *policy.session_roots,
            *policy.device_roots,
        )
        missing = [root for root in scoped_roots if root not in snapshot.cells]
        if missing:
            raise InvalidCell("capability grant references a missing scope root")
        root_id = _grant_root(handle.fingerprint)
        if root_id in snapshot.cells:
            raise InvalidCell("capability grant identity already exists")
        data_cells = tuple(
            _terminal(
                "%s:data-class:%s" % (
                    root_id,
                    hashlib.sha256(value.encode("utf-8")).hexdigest(),
                ),
                value,
            )
            for value in sorted(policy.data_classes)
        )
        values = {
            "policy-id": policy.policy_id,
            "handle-fingerprint": _fingerprint_digest(handle.fingerprint),
            "expires-at": "%.6f" % policy.expires_at,
            "max-invocations": str(policy.max_invocations),
            "invocation-count": "0",
        }
        relation = compose_relation_cells(
            (
                *((self._protocol.role(name), root_id + ":" + name)
                  for name in values),
                *((self._protocol.role("request-scope"), root)
                  for root in sorted(policy.request_roots)),
                *((self._protocol.role("authority-scope"), root)
                  for root in sorted(policy.authority_roots)),
                *((self._protocol.role("session-scope"), root)
                  for root in sorted(policy.session_roots)),
                *((self._protocol.role("device-scope"), root)
                  for root in sorted(policy.device_roots)),
                *((self._protocol.role("data-class-scope"), cell.id)
                  for cell in data_cells),
                (self._protocol.role("state"), self._protocol.grant_states["active"]),
            ),
            relation_id=root_id,
        )
        append = prepare_append_relation_member(
            snapshot,
            self._protocol.root_id,
            self._protocol.role("grant-member"),
            root_id,
            budget=100_000,
        )
        self._store.commit(
            snapshot.revision,
            create=(
                *(_terminal(root_id + ":" + name, value)
                  for name, value in values.items()),
                *data_cells,
                *relation.cells,
                *append.create,
            ),
            replace=append.replace,
        )
        return root_id

    def _set_grant_state(self, entry: _Entry, state: str) -> None:
        if (
            self._store is None
            or self._protocol is None
            or not entry.grant_root
        ):
            return
        snapshot = self._store.snapshot()
        grant = read_capability_grant(snapshot, self._protocol, entry.grant_root)
        incidence = snapshot.cells[grant.state_incidence]
        self._store.commit(
            snapshot.revision,
            replace=(Cell(
                incidence.id,
                incidence.link0,
                self._protocol.grant_states[state],
                incidence.atom,
            ),),
        )

    def _set_invocation_count(self, entry: _Entry) -> None:
        if (
            self._store is None
            or self._protocol is None
            or not entry.grant_root
        ):
            return
        snapshot = self._store.snapshot()
        current = snapshot.cells[entry.grant_root + ":invocation-count"]
        self._store.commit(
            snapshot.revision,
            replace=(Cell(
                current.id,
                current.link0,
                current.link1,
                str(entry.invocation_count).encode("ascii"),
            ),),
        )

    def _record_graph_event(
        self,
        *,
        entry: _Entry | None,
        policy_id: str,
        request_root: str,
        authority_root: str,
        result_root: str,
        outcome: str,
        reason: str,
        timestamp: float,
    ) -> str:
        if self._store is None or self._protocol is None:
            return ""
        if outcome not in self._protocol.event_outcomes:
            raise InvalidCell("capability event outcome is undeclared")
        snapshot = self._store.snapshot()
        root_id = _event_root()
        grant_root = (
            entry.grant_root
            if entry is not None and entry.grant_root in snapshot.cells
            else root_id + ":grant"
        )
        values = {
            "event-request": request_root,
            "event-authority": authority_root,
            "event-result": result_root,
            "event-reason": reason,
            "event-recorded-at": "%.6f" % timestamp,
        }
        extra = ()
        if grant_root == root_id + ":grant":
            extra = (_terminal(grant_root, policy_id),)
        relation = compose_relation_cells(
            (
                (self._protocol.role("event-grant"), grant_root),
                *((self._protocol.role(name), root_id + ":" + name)
                  for name in values),
                (
                    self._protocol.role("event-outcome"),
                    self._protocol.event_outcomes[outcome],
                ),
            ),
            relation_id=root_id,
        )
        append = prepare_append_relation_member(
            snapshot,
            self._protocol.root_id,
            self._protocol.role("event-member"),
            root_id,
            budget=100_000,
        )
        self._store.commit(
            snapshot.revision,
            create=(
                *(_terminal(root_id + ":" + name, value)
                  for name, value in values.items()),
                *extra,
                *relation.cells,
                *append.create,
            ),
            replace=append.replace,
        )
        return root_id

    def mint(
        self,
        handler: Callable[[Snapshot, str, str], str],
        policy: CapabilityPolicy,
    ) -> CapabilityHandle:
        if not callable(handler):
            raise TypeError("capability handler must be callable")
        if type(policy) is not CapabilityPolicy:
            raise TypeError("capability minting requires an explicit policy")
        handle = CapabilityHandle(_MINT_KEY)
        grant_root = self._commit_grant(handle, policy)
        with self._lock:
            self._entries[handle] = _Entry(handler, policy, grant_root)
        return handle

    def revoke(self, handle: CapabilityHandle) -> None:
        with self._lock:
            entry = self._entries.get(handle)
            if entry is None:
                raise CapabilityDenied("unknown capability")
            self._set_grant_state(entry, "revoked")
            entry.active = False

    def invoke(
        self,
        handle: object,
        snapshot: Snapshot,
        request_root: str,
        authority_root: str,
    ) -> str:
        now = time.time()
        with self._lock:
            entry = self._entries.get(handle) if type(handle) is CapabilityHandle else None
            fingerprint = (
                handle.fingerprint if type(handle) is CapabilityHandle else "unrecognized"
            )
            policy_id = entry.policy.policy_id if entry is not None else "unknown"
            reason = ""
            if entry is None:
                reason = "unknown-handle"
            elif not entry.active:
                reason = "revoked"
            elif now >= entry.policy.expires_at:
                reason = "expired"
            elif entry.invocation_count >= entry.policy.max_invocations:
                reason = "budget-exhausted"
            elif request_root not in entry.policy.request_roots:
                reason = "request-out-of-scope"
            elif authority_root not in entry.policy.authority_roots:
                reason = "authority-out-of-scope"
            elif request_root not in snapshot.cells or authority_root not in snapshot.cells:
                reason = "missing-graph-root"
            if reason:
                event_root = self._record_graph_event(
                    entry=entry,
                    policy_id=policy_id,
                    request_root=request_root,
                    authority_root=authority_root,
                    result_root="",
                    outcome="denied",
                    reason=reason,
                    timestamp=now,
                )
                self._events.append(CapabilityEvent(
                    now, fingerprint, policy_id, request_root, authority_root,
                    "denied", reason, event_root,
                ))
                raise CapabilityDenied("capability invocation denied: %s" % reason)

            entry.invocation_count += 1
            try:
                self._set_invocation_count(entry)
            except Exception:
                entry.invocation_count -= 1
                raise

            try:
                result_root = entry.handler(snapshot, request_root, authority_root)
            except Exception:
                event_root = self._record_graph_event(
                    entry=entry,
                    policy_id=policy_id,
                    request_root=request_root,
                    authority_root=authority_root,
                    result_root="",
                    outcome="failed",
                    reason="handler-failed",
                    timestamp=now,
                )
                self._events.append(CapabilityEvent(
                    now, fingerprint, policy_id, request_root, authority_root,
                    "failed", "handler-failed", event_root,
                ))
                raise
            if result_root not in snapshot.cells:
                event_root = self._record_graph_event(
                    entry=entry,
                    policy_id=policy_id,
                    request_root=request_root,
                    authority_root=authority_root,
                    result_root=result_root,
                    outcome="denied",
                    reason="unknown-result-root",
                    timestamp=now,
                )
                self._events.append(CapabilityEvent(
                    now, fingerprint, policy_id, request_root, authority_root,
                    "denied", "unknown-result-root", event_root,
                ))
                raise CapabilityDenied("capability returned an unknown result root")
            event_root = self._record_graph_event(
                entry=entry,
                policy_id=policy_id,
                request_root=request_root,
                authority_root=authority_root,
                result_root=result_root,
                outcome="allowed",
                reason="",
                timestamp=now,
            )
            self._events.append(CapabilityEvent(
                now, fingerprint, policy_id, request_root, authority_root,
                "allowed", "", event_root,
            ))
            return result_root

    def audit(self) -> tuple[CapabilityEvent, ...]:
        with self._lock:
            return tuple(self._events)


__all__ = [
    "CapabilityBroker",
    "CapabilityDenied",
    "CapabilityEvent",
    "CapabilityEventProjection",
    "CapabilityGrantProjection",
    "CapabilityHandle",
    "CapabilityPolicy",
    "CapabilityProtocol",
    "bootstrap_capability_protocol",
    "project_capability_protocol",
    "read_capability_events",
    "read_capability_grant",
]
