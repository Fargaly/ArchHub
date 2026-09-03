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


def verify_browser_session(
    snapshot: Snapshot,
    protocol: BrowserSessionProtocol,
    session_root: str,
    *,
    token: str,
    csrf_token: str | None = None,
    require_csrf: bool = False,
    now: float | None = None,
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
    try:
        issued_at = float(_text(snapshot, session.issued_at_root))
        expires_at = float(_text(snapshot, session.expires_at_root))
    except ValueError as exc:
        raise BrowserSessionDenied("browser-session time is invalid") from exc
    if issued_at > current + 5 or expires_at <= current:
        raise BrowserSessionDenied("browser session expired or not yet valid")
    expected_token = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(
        expected_token, _text(snapshot, session.token_digest_root)
    ):
        raise BrowserSessionDenied("browser credential digest drifted")
    if require_csrf:
        if csrf_token is None or not secrets.compare_digest(
            hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(),
            _text(snapshot, session.csrf_digest_root),
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
    "BrowserSessionProjection",
    "BrowserSessionProtocol",
    "bootstrap_browser_session_protocol",
    "compose_browser_session_protocol",
    "issue_browser_session",
    "list_browser_session_roots",
    "project_browser_session_protocol",
    "read_browser_session",
    "revoke_browser_session",
    "verify_browser_session",
]
