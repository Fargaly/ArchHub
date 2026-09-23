"""Graph-held browser sessions with process-held opaque credentials."""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "session-member",
    "subject",
    "view",
    "tenant",
    "assurance",
    "issued-at",
    "expires-at",
    "token-digest",
    "csrf-digest",
    "state",
    "revocation-reason",
)
STATE_NAMES = ("active", "revoked")
MAX_SESSION_SECONDS = 3600.0
# SPEC 3.3: the session identity (subject, view, tenant, assurance, state)
# is graph authority; the per-process credential digests, issue time and
# expiry are a bounded lease record keyed by the session root. A lease is
# opened at sign-in or launch, renewed and closed without a graph revision.
LEASE_KIND = "browser-session"
LEASE_STATES = ("active", "closed")


class BrowserSessionDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserSessionProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown browser-session role") from exc


@dataclass(frozen=True, slots=True)
class BrowserSessionProjection:
    root_id: str
    subject_root: str
    view_root: str
    tenant_root: str
    assurance_root: str
    issued_at_root: str
    expires_at_root: str
    token_digest_root: str
    csrf_digest_root: str
    state_root: str
    state_incidence: str
    revocation_reason_roots: tuple[str, ...]


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("browser-session scalar is missing or invalid") from exc


def _one(members, role_root: str, label: str):
    found = [member for member in members if member.role_id == role_root]
    if len(found) != 1:
        raise InvalidCell("browser session requires exactly one %s" % label)
    return found[0]


def bootstrap_browser_session_protocol(
    store: CellStore, *, prefix: str = "browser-session-protocol"
) -> BrowserSessionProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_browser_session_protocol(store.snapshot(), prefix=prefix)
    batch = CellBatch(store)
    protocol = compose_browser_session_protocol(batch, prefix=prefix)
    batch.commit()
    return protocol


def compose_browser_session_protocol(
    batch: CellBatch,
    *,
    prefix: str = "browser-session-protocol",
) -> BrowserSessionProtocol:
    """Compose the browser-session vocabulary into a caller-owned batch."""
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    for name, root in (*roles.items(), *states.items()):
        batch.add(_terminal(root, name))
    root_id = prefix + ":root"
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values())
        ),
        relation_id=root_id,
    )
    return BrowserSessionProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def project_browser_session_protocol(
    snapshot: Snapshot, *, prefix: str = "browser-session-protocol"
) -> BrowserSessionProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    root_id = prefix + ":root"
    required = {root_id, *roles.values(), *states.values()}
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("browser-session protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed_roles = {roles["vocabulary-member"], roles["session-member"]}
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("browser-session protocol has an undeclared member")
    vocabulary = {
        member.participant_id for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != {*roles.values(), *states.values()}:
        raise InvalidCell("browser-session vocabulary drifted")
    sessions = [
        member.participant_id for member in members
        if member.role_id == roles["session-member"]
    ]
    if len(sessions) != len(set(sessions)):
        raise InvalidCell("browser-session registry contains a duplicate")
    return BrowserSessionProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def issue_browser_session(
    store: CellStore,
    protocol: BrowserSessionProtocol,
    *,
    subject_root: str,
    view_root: str,
    tenant_root: str,
    assurance_root: str,
    token_digest: str,
    csrf_digest: str,
    issued_at: float | None = None,
    lifetime_seconds: float = 900.0,
) -> tuple[str, int]:
    now = time.time() if issued_at is None else float(issued_at)
    if lifetime_seconds <= 0 or lifetime_seconds > MAX_SESSION_SECONDS:
        raise ValueError("browser session lifetime must be within one hour")
    if not all(
        len(value) == 64 and all(char in "0123456789abcdef" for char in value)
        for value in (token_digest, csrf_digest)
    ):
        raise InvalidCell("browser-session credential digest is invalid")
    snapshot = store.snapshot()
    required = {
        protocol.root_id,
        subject_root,
        view_root,
        tenant_root,
        assurance_root,
        protocol.states["active"],
    }
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("browser-session authority root is missing")
    root_id = "browser-session:" + uuid.uuid4().hex
    values = {
        "issued-at": _terminal(root_id + ":issued-at", repr(now)),
        "expires-at": _terminal(
            root_id + ":expires-at", repr(now + lifetime_seconds)
        ),
        "token-digest": _terminal(root_id + ":token-digest", token_digest),
        "csrf-digest": _terminal(root_id + ":csrf-digest", csrf_digest),
    }
    members = (
        (protocol.role("subject"), subject_root),
        (protocol.role("view"), view_root),
        (protocol.role("tenant"), tenant_root),
        (protocol.role("assurance"), assurance_root),
        (protocol.role("issued-at"), values["issued-at"].id),
        (protocol.role("expires-at"), values["expires-at"].id),
        (protocol.role("token-digest"), values["token-digest"].id),
        (protocol.role("csrf-digest"), values["csrf-digest"].id),
        (protocol.role("state"), protocol.states["active"]),
    )
    relation = compose_relation_cells(members, relation_id=root_id)
    registry_patch = prepare_append_relation_members(
        snapshot,
        protocol.root_id,
        ((protocol.role("session-member"), root_id),),
        budget=100_000,
    )
    revision = store.commit(
        snapshot.revision,
        create=(
            *values.values(),
            *relation.cells,
            *registry_patch.create,
        ),
        replace=registry_patch.replace,
    )
    return root_id, revision


def read_browser_session(
    snapshot: Snapshot,
    protocol: BrowserSessionProtocol,
    session_root: str,
) -> BrowserSessionProjection:
    members = read_relation(snapshot, session_root, budget=256)
    allowed = {
        protocol.role(name) for name in ROLE_NAMES
        if name not in ("vocabulary-member", "session-member")
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("browser session contains an undeclared field")
    subject = _one(members, protocol.role("subject"), "subject")
    view = _one(members, protocol.role("view"), "view")
    tenant = _one(members, protocol.role("tenant"), "tenant")
    assurance = _one(members, protocol.role("assurance"), "assurance")
    issued_at = _one(members, protocol.role("issued-at"), "issued-at")
    expires_at = _one(members, protocol.role("expires-at"), "expires-at")
    token_digest = _one(
        members, protocol.role("token-digest"), "token-digest"
    )
    csrf_digest = _one(
        members, protocol.role("csrf-digest"), "csrf-digest"
    )
    state = _one(members, protocol.role("state"), "state")
    if state.participant_id not in protocol.states.values():
        raise InvalidCell("browser-session state is not admitted")
    reasons = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("revocation-reason")
    )
    if len(reasons) > 1:
        raise InvalidCell("browser session has multiple revocation reasons")
    return BrowserSessionProjection(
        session_root,
        subject.participant_id,
        view.participant_id,
        tenant.participant_id,
        assurance.participant_id,
        issued_at.participant_id,
        expires_at.participant_id,
        token_digest.participant_id,
        csrf_digest.participant_id,
        state.participant_id,
        state.incidence_id,
        reasons,
    )


def list_browser_session_roots(
    snapshot: Snapshot,
    protocol: BrowserSessionProtocol,
) -> tuple[str, ...]:
    roots = tuple(
        member.participant_id for member in read_relation(
            snapshot, protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.role("session-member")
    )
    if len(roots) != len(set(roots)):
        raise InvalidCell("browser-session registry contains a duplicate")
    return roots


@dataclass(frozen=True, slots=True)
class BrowserSessionLease:
    session_root: str
    subject_root: str
    view_root: str
    tenant_root: str
    assurance_root: str
    issued_at: float
    expires_at: float
    token_digest: str
    csrf_digest: str
    state: str
    generation: int


def _digest(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise InvalidCell("browser-session credential digest is invalid")
    return value


def read_browser_session_lease(
    storage, session_root: str
) -> BrowserSessionLease | None:
    row = storage.get_record(LEASE_KIND, session_root)
    if row is None:
        return None
    payload = row["payload"]
    try:
        lease = BrowserSessionLease(
            row["record_root"],
            row["owner_root"],
            str(payload["view"]),
            str(payload["tenant"]),
            str(payload["assurance"]),
            float(payload["issued_at"]),
            float(payload["expires_at"]),
            _digest(payload["token_digest"]),
            _digest(payload["csrf_digest"]),
            str(row["state"]),
            int(row["generation"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCell("browser-session lease is malformed") from exc
    if lease.state not in LEASE_STATES:
        raise InvalidCell("browser-session lease state is unknown")
    return lease


def list_browser_session_leases(
    storage, *, subject_root: str | None = None, states=None
) -> tuple[BrowserSessionLease, ...]:
    return tuple(
        read_browser_session_lease(storage, row["record_root"])
        for row in storage.list_records(
            LEASE_KIND, owner_root=subject_root, states=states, limit=10_000
        )
    )


def _lease_payload(
    *, view_root, tenant_root, assurance_root, issued_at, expires_at,
    token_digest, csrf_digest,
) -> dict:
    return {
        "view": view_root,
        "tenant": tenant_root,
        "assurance": assurance_root,
        "issued_at": float(issued_at),
        "expires_at": float(expires_at),
        "token_digest": _digest(token_digest),
        "csrf_digest": _digest(csrf_digest),
    }


def open_browser_session_lease(
    store: CellStore,
    protocol: BrowserSessionProtocol,
    storage,
    *,
    subject_root: str,
    view_root: str,
    tenant_root: str,
    assurance_root: str,
    token_digest: str,
    csrf_digest: str,
    issued_at: float | None = None,
    lifetime_seconds: float = 900.0,
) -> tuple[str, int]:
    """Open a credential lease on a reusable session identity.

    An existing active graph session for the same exact authority whose lease
    is closed or expired is reused. Only when none exists is a new graph
    session identity composed (the caller supplies the admitted intent).
    """
    now = time.time() if issued_at is None else float(issued_at)
    if lifetime_seconds <= 0 or lifetime_seconds > MAX_SESSION_SECONDS:
        raise ValueError("browser session lifetime must be within one hour")
    payload = _lease_payload(
        view_root=view_root, tenant_root=tenant_root,
        assurance_root=assurance_root, issued_at=now,
        expires_at=now + lifetime_seconds, token_digest=token_digest,
        csrf_digest=csrf_digest,
    )
    snapshot = store.snapshot()
    for lease in list_browser_session_leases(storage, subject_root=subject_root):
        if (
            (lease.view_root, lease.tenant_root, lease.assurance_root)
            != (view_root, tenant_root, assurance_root)
            or (lease.state == "active" and lease.expires_at > now)
        ):
            continue
        try:
            session = read_browser_session(snapshot, protocol, lease.session_root)
        except (InvalidCell, KeyError):
            continue
        if (
            session.state_root != protocol.states["active"]
            or (session.subject_root, session.view_root, session.tenant_root,
                session.assurance_root)
            != (subject_root, view_root, tenant_root, assurance_root)
        ):
            continue
        storage.put_record(
            LEASE_KIND, lease.session_root, owner_root=subject_root,
            state="active", payload=payload,
            authority_revision=snapshot.revision, updated_at=now,
            expected_generation=lease.generation, event="open",
        )
        return lease.session_root, snapshot.revision
    session_root, revision = issue_browser_session(
        store, protocol, subject_root=subject_root, view_root=view_root,
        tenant_root=tenant_root, assurance_root=assurance_root,
        token_digest=token_digest, csrf_digest=csrf_digest, issued_at=now,
        lifetime_seconds=lifetime_seconds,
    )
    storage.put_record(
        LEASE_KIND, session_root, owner_root=subject_root, state="active",
        payload=payload, authority_revision=revision, updated_at=now,
        create_only=True, event="open", retire_states=("closed",),
    )
    return session_root, revision


def adopt_browser_session_lease(
    store: CellStore,
    protocol: BrowserSessionProtocol,
    storage,
    session_root: str,
    *,
    state: str,
) -> BrowserSessionLease:
    """Carry a pre-lease graph session into a lease record, without a revision.

    Graphs written before leases hold the credential scalars as Cells; the
    lease starts from exactly those values and owns them from then on.
    """
    if state not in LEASE_STATES:
        raise InvalidCell("browser-session lease state is unknown")
    snapshot = store.snapshot()
    session = read_browser_session(snapshot, protocol, session_root)
    try:
        issued_at = float(_text(snapshot, session.issued_at_root))
        expires_at = float(_text(snapshot, session.expires_at_root))
    except ValueError as exc:
        raise InvalidCell("browser-session time is invalid") from exc
    storage.put_record(
        LEASE_KIND, session_root, owner_root=session.subject_root, state=state,
        payload=_lease_payload(
            view_root=session.view_root, tenant_root=session.tenant_root,
            assurance_root=session.assurance_root, issued_at=issued_at,
            expires_at=expires_at,
            token_digest=_text(snapshot, session.token_digest_root),
            csrf_digest=_text(snapshot, session.csrf_digest_root),
        ),
        authority_revision=snapshot.revision, updated_at=time.time(),
        create_only=True, event="adopt", retire_states=("closed",),
    )
    return read_browser_session_lease(storage, session_root)


def renew_browser_session_lease(
    store: CellStore,
    storage,
    session_root: str,
    *,
    issued_at: float,
    expires_at: float,
    expected_generation: int,
) -> BrowserSessionLease:
    lease = read_browser_session_lease(storage, session_root)
    if lease is None or lease.state != "active":
        raise BrowserSessionDenied("browser session lease is not active")
    if not 0 < float(expires_at) - float(issued_at) <= MAX_SESSION_SECONDS:
        raise ValueError("browser session lifetime must be within one hour")
    storage.put_record(
        LEASE_KIND, session_root, owner_root=lease.subject_root,
        state="active",
        payload=_lease_payload(
            view_root=lease.view_root, tenant_root=lease.tenant_root,
            assurance_root=lease.assurance_root, issued_at=issued_at,
            expires_at=expires_at, token_digest=lease.token_digest,
            csrf_digest=lease.csrf_digest,
        ),
        authority_revision=store.revision, updated_at=float(issued_at),
        expected_generation=expected_generation, event="renew",
    )
    return read_browser_session_lease(storage, session_root)


def close_browser_session_lease(
    store: CellStore, storage, session_root: str, *, reason: str
) -> bool:
    """End the credential lease; the reusable graph identity is unchanged."""
    reason = str(reason).strip()
    if not reason or len(reason.encode("utf-8")) > 1024:
        raise ValueError("browser-session close reason is required")
    lease = read_browser_session_lease(storage, session_root)
    if lease is None or lease.state == "closed":
        return False
    storage.put_record(
        LEASE_KIND, session_root, owner_root=lease.subject_root,
        state="closed",
        payload={
            **_lease_payload(
                view_root=lease.view_root, tenant_root=lease.tenant_root,
                assurance_root=lease.assurance_root, issued_at=lease.issued_at,
                expires_at=lease.expires_at, token_digest=lease.token_digest,
                csrf_digest=lease.csrf_digest,
            ),
            "reason": reason,
        },
        authority_revision=store.revision, updated_at=time.time(),
        expected_generation=lease.generation, event="close",
    )
    return True


def verify_browser_session(
    snapshot: Snapshot,
    protocol: BrowserSessionProtocol,
    session_root: str,
    *,
    token: str,
    csrf_token: str | None = None,
    require_csrf: bool = False,
    now: float | None = None,
    lease_storage=None,
) -> BrowserSessionProjection:
    registered = [
        member.participant_id for member in read_relation(
            snapshot, protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.role("session-member")
    ]
    if registered.count(session_root) != 1:
        raise BrowserSessionDenied("browser session is not uniquely registered")
    session = read_browser_session(snapshot, protocol, session_root)
    if session.state_root != protocol.states["active"]:
        raise BrowserSessionDenied("browser session is revoked")
    current = time.time() if now is None else float(now)
    lease = (
        None if lease_storage is None
        else read_browser_session_lease(lease_storage, session_root)
    )
    if lease is not None:
        if lease.state != "active":
            raise BrowserSessionDenied("browser session lease is closed")
        if (lease.subject_root, lease.view_root, lease.tenant_root,
                lease.assurance_root) != (
                session.subject_root, session.view_root,
                session.tenant_root, session.assurance_root):
            raise BrowserSessionDenied("browser session lease authority drifted")
        issued_at, expires_at = lease.issued_at, lease.expires_at
        token_digest, csrf_digest = lease.token_digest, lease.csrf_digest
    else:
        try:
            issued_at = float(_text(snapshot, session.issued_at_root))
            expires_at = float(_text(snapshot, session.expires_at_root))
        except ValueError as exc:
            raise BrowserSessionDenied("browser-session time is invalid") from exc
        token_digest = _text(snapshot, session.token_digest_root)
        csrf_digest = _text(snapshot, session.csrf_digest_root)
    if issued_at > current + 5 or expires_at <= current:
        raise BrowserSessionDenied("browser session expired or not yet valid")
    expected_token = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(expected_token, token_digest):
        raise BrowserSessionDenied("browser credential digest drifted")
    if require_csrf:
        if csrf_token is None or not secrets.compare_digest(
            hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(),
            csrf_digest,
        ):
            raise BrowserSessionDenied("browser CSRF digest drifted")
    return session


def revoke_browser_session(
    store: CellStore,
    protocol: BrowserSessionProtocol,
    session_root: str,
    *,
    reason: str,
) -> int:
    reason = str(reason).strip()
    if not reason or len(reason.encode("utf-8")) > 1024:
        raise ValueError("browser-session revocation reason is required")
    snapshot = store.snapshot()
    session = read_browser_session(snapshot, protocol, session_root)
    if session.state_root == protocol.states["revoked"]:
        return snapshot.revision
    reason_root = session_root + ":revocation-reason"
    reason_cell = _terminal(reason_root, reason)
    reason_patch = prepare_append_relation_members(
        snapshot,
        session_root,
        ((protocol.role("revocation-reason"), reason_root),),
        budget=256,
    )
    state_incidence = snapshot.cells[session.state_incidence]
    return store.commit(
        snapshot.revision,
        create=(reason_cell, *reason_patch.create),
        replace=(
            Cell(
                state_incidence.id,
                state_incidence.link0,
                protocol.states["revoked"],
                state_incidence.atom,
            ),
            *reason_patch.replace,
        ),
    )


__all__ = [
    "BrowserSessionDenied",
    "BrowserSessionLease",
    "BrowserSessionProjection",
    "BrowserSessionProtocol",
    "LEASE_KIND",
    "adopt_browser_session_lease",
    "bootstrap_browser_session_protocol",
    "close_browser_session_lease",
    "compose_browser_session_protocol",
    "issue_browser_session",
    "list_browser_session_leases",
    "list_browser_session_roots",
    "open_browser_session_lease",
    "project_browser_session_protocol",
    "read_browser_session",
    "read_browser_session_lease",
    "renew_browser_session_lease",
    "revoke_browser_session",
    "verify_browser_session",
]
