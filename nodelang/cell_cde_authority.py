"""Signed, one-use CDE write permits composed entirely from Universal Cells.

The permit is a policy-enforcement artifact, not authority by itself. It binds
the subject, Work, WIP CDE container, operation, logical path, content digest,
request, nonce, and accepted graph revision. The executor must consume it with
the exact write. This follows NIST SP 800-207 least-privilege enforcement,
RFC 9449 request/replay binding, and the ISO 19650 distinction between editable
WIP information and non-editable Shared/Published information.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
import time
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import (
    CellBatch,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .cell_signing_authority import (
    SigningAuthorityDenied,
    SigningAuthorityProtocol,
    SigningAuthorityProvider,
    prepare_signature_envelope,
    read_signing_key_descriptor,
    verify_signature_envelope,
)
from .universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    Snapshot,
)


STATEMENT_PROTOCOL = "application/vnd.archhub.cde-write-permit.v2"
STATEMENT_CONTEXT = "cde-write-permit"
MAX_PERMIT_SECONDS = 300.0

ROLE_NAMES = (
    "vocabulary-member",
    "permit-member",
    "receipt-member",
    "runtime",
    "agent-session",
    "work",
    "container-root",
    "container-id",
    "container-digest",
    "operation",
    "path",
    "content-digest",
    "request-id",
    "nonce",
    "authority-revision",
    "issued-at",
    "expires-at",
    "signature-envelope",
    "state",
    "receipt-permit",
    "receipt-kind",
    "receipt-digest",
    "receipt-recorded-at",
)
STATE_NAMES = ("active", "consumed", "revoked")
RECEIPT_KINDS = ("consumed", "revoked")
PERMIT_FIELDS = (
    "runtime",
    "agent-session",
    "work",
    "container-root",
    "container-id",
    "container-digest",
    "operation",
    "path",
    "content-digest",
    "request-id",
    "nonce",
    "authority-revision",
    "issued-at",
    "expires-at",
    "signature-envelope",
    "state",
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER_ID = re.compile(r"GM\.[a-z0-9_-]+\.[a-z0-9_-]+\Z")
_CONTAINER_REVISION = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,63}\Z")
_SAFE_PATH_ROOTS = (
    "00.GOVERNANCE/",
    "10.PRODUCT/",
    "20.CLIENTS/",
    "30.KNOWLEDGE/",
    "40.MEDIA/",
    "50.TOOLING/",
    "60.PERSONAL/",
    "70.HANDOFFS/",
    "90.ARCHIVE/",
)


class CdeWriteDenied(PermissionError):
    """One exact graph-held write permit did not authorize the request."""


@dataclass(frozen=True, slots=True)
class CdeWriteAuthorityProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]
    receipt_kinds: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown CDE write-authority role") from exc


@dataclass(frozen=True, slots=True)
class CdeWritePermitProjection:
    root_id: str
    field_roots: Mapping[str, str]
    runtime: str
    agent_session_root: str
    work_root: str
    container_root: str
    container_id: str
    container_digest: str
    operation: str
    path: str
    content_digest: str
    request_id: str
    nonce: str
    authority_revision: int
    issued_at: float
    expires_at: float
    signature_envelope_root: str
    state_root: str
    state_incidence: str


@dataclass(frozen=True, slots=True)
class CdeWriteReceiptProjection:
    root_id: str
    permit_root: str
    kind_root: str
    digest: str
    recorded_at: float


@dataclass(frozen=True, slots=True)
class CdeWriteReceiptPatch:
    """One verified receipt mutation prepared for a wider atomic commit."""

    expected_revision: int
    receipt: CdeWriteReceiptProjection
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]


def _terminal(root_id: str, value: str) -> Cell:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidCell("CDE write-authority value is invalid") from exc
    if not encoded or len(encoded) > 4096:
        raise InvalidCell("CDE write-authority value is empty or too large")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded)


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise KeyError(root_id)
        return cell.atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("CDE write permit %s is invalid" % label) from exc


def _one(members, role_root: str, label: str):
    values = [member for member in members if member.role_id == role_root]
    if len(values) != 1:
        raise InvalidCell("CDE write permit requires exactly one %s" % label)
    return values[0]


def _root(value: object, label: str, *, maximum: int = 512) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > maximum:
        raise InvalidCell("CDE write permit %s is invalid" % label)
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise InvalidCell("CDE write permit %s must be a SHA-256 digest" % label)
    return value


def _time(value: object, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("CDE write permit %s is invalid" % label) from exc
    if not math.isfinite(parsed):
        raise InvalidCell("CDE write permit %s is invalid" % label)
    return parsed


def _revision(value: object) -> int:
    if type(value) is int:
        revision = value
    elif type(value) is str and value.isdigit():
        revision = int(value)
    else:
        raise InvalidCell("CDE write permit revision is invalid")
    if revision < 1:
        raise InvalidCell("CDE write permit revision is invalid")
    return revision


def _path(value: object) -> str:
    path = _root(value, "path", maximum=1024).replace("\\", "/").strip()
    parts = path.split("/")
    if (
        path.startswith("/")
        or not path.startswith(_SAFE_PATH_ROOTS)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise InvalidCell("CDE write permit path is invalid")
    return path


def _grant_path(value: object) -> str:
    path = _root(value, "grant path", maximum=1024).replace("\\", "/").strip()
    path = path.rstrip("/")
    parts = path.split("/")
    if (
        path.startswith("/")
        or not path.startswith(_SAFE_PATH_ROOTS)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise InvalidCell("CDE write grant path is invalid")
    return path


def authorize_cde_container_write(
    container: object,
    *,
    operation: object,
    path: object,
) -> tuple[str, str]:
    """Admit one operation/path through explicit graph-held WIP grants."""
    try:
        if type(container) is not dict:
            raise InvalidCell("CDE write container is not an object")
        container_id = _root(container.get("container_id"), "container")
        if not _CONTAINER_ID.fullmatch(container_id):
            raise InvalidCell("CDE write container identity is invalid")
        for field in (
            "source_requirement",
            "domain",
            "suitability_status",
            "owner",
            "checker",
            "gate_kind",
        ):
            _root(container.get(field), field, maximum=1024)
        if container.get("tier") not in {"T0", "T1", "T2", "T3"}:
            raise InvalidCell("CDE write container tier is invalid")
        if type(container.get("gate_spec")) is not dict:
            raise InvalidCell("CDE write container gate specification is invalid")
        if container.get("lifecycle_state") != "WIP":
            raise CdeWriteDenied("CDE write container must be WIP")
        revision = container.get("revision")
        if (
            type(revision) is not str
            or not _CONTAINER_REVISION.fullmatch(revision)
        ):
            raise InvalidCell("CDE write container revision is invalid")
        requested_operation = _root(
            operation, "operation", maximum=128
        )
        requested_path = _path(path)
        grants = container.get("write_grants")
        if type(grants) is not list or not grants or len(grants) > 256:
            raise InvalidCell("CDE write grants are invalid")
        allowed_paths = container.get("allowed_paths")
        if (
            type(allowed_paths) is not list
            or not allowed_paths
            or len(allowed_paths) > 256
        ):
            raise InvalidCell("CDE write allowed paths are invalid")
        normalized_allowed_paths = tuple(
            _grant_path(item) for item in allowed_paths
        )
        if len(normalized_allowed_paths) != len(set(normalized_allowed_paths)):
            raise InvalidCell("CDE write allowed paths are duplicated")
        admitted = False
        normalized_grants = set()
        for grant in grants:
            if type(grant) is not dict or set(grant) != {
                "path", "scope", "operations"
            }:
                raise InvalidCell("CDE write grant shape is invalid")
            grant_path = _grant_path(grant["path"])
            scope = grant["scope"]
            if scope not in {"exact", "descendants"}:
                raise InvalidCell("CDE write grant scope is invalid")
            operations = grant["operations"]
            if (
                type(operations) is not list
                or not operations
                or len(operations) > 64
            ):
                raise InvalidCell("CDE write grant operations are invalid")
            normalized_operations = tuple(
                _root(item, "grant operation", maximum=128)
                for item in operations
            )
            if len(normalized_operations) != len(set(normalized_operations)):
                raise InvalidCell("CDE write grant repeats an operation")
            grant_identity = (grant_path, scope, normalized_operations)
            if grant_identity in normalized_grants:
                raise InvalidCell("CDE write grant is duplicated")
            normalized_grants.add(grant_identity)
            path_matches = (
                requested_path == grant_path
                if scope == "exact"
                else (
                    requested_path == grant_path
                    or requested_path.startswith(grant_path + "/")
                )
            )
            admitted = admitted or (
                path_matches and requested_operation in normalized_operations
            )
        if {
            identity[0] for identity in normalized_grants
        } != set(normalized_allowed_paths):
            raise InvalidCell(
                "CDE write grants and allowed paths disagree"
            )
        if not admitted:
            raise CdeWriteDenied(
                "CDE write operation or path is not granted"
            )
        canonical = json.dumps(
            container,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    except CdeWriteDenied:
        raise
    except (InvalidCell, TypeError, ValueError, UnicodeError) as exc:
        raise CdeWriteDenied(str(exc)) from exc
    return container_id, hashlib.sha256(canonical).hexdigest()


def _canonical_payload(values: Mapping[str, str]) -> bytes:
    payload = {
        "protocol": STATEMENT_PROTOCOL,
        **{
            name: values[name]
            for name in PERMIT_FIELDS
            if name not in {"signature-envelope", "state"}
        },
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def bootstrap_cde_write_authority_protocol(
    store: CellStore, *, prefix: str = "cde-write-authority-protocol"
) -> CdeWriteAuthorityProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_cde_write_authority_protocol(store.snapshot(), prefix=prefix)
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    kinds = {
        name: "%s:receipt-kind:%s" % (prefix, name)
        for name in RECEIPT_KINDS
    }
    batch = CellBatch(store)
    for name, root in (*roles.items(), *states.items(), *kinds.items()):
        batch.add(_terminal(root, name))
    batch.relation(
        (
            (roles["vocabulary-member"], root)
            for root in (*roles.values(), *states.values(), *kinds.values())
        ),
        relation_id=root_id,
    )
    batch.commit()
    return CdeWriteAuthorityProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(kinds),
    )


def project_cde_write_authority_protocol(
    snapshot: Snapshot, *, prefix: str = "cde-write-authority-protocol"
) -> CdeWriteAuthorityProtocol:
    root_id = prefix + ":root"
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {name: "%s:state:%s" % (prefix, name) for name in STATE_NAMES}
    kinds = {
        name: "%s:receipt-kind:%s" % (prefix, name)
        for name in RECEIPT_KINDS
    }
    expected = set((*roles.values(), *states.values(), *kinds.values()))
    members = read_relation(snapshot, root_id, budget=100_000)
    actual = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    declared_member_roles = {
        roles["vocabulary-member"],
        roles["permit-member"],
        roles["receipt-member"],
    }
    if actual != expected or any(
        member.role_id not in declared_member_roles for member in members
    ):
        raise InvalidCell("CDE write-authority vocabulary drifted")
    for name, root in (*roles.items(), *states.items(), *kinds.items()):
        if _text(snapshot, root, "vocabulary") != name:
            raise InvalidCell("CDE write-authority vocabulary drifted")
    return CdeWriteAuthorityProtocol(
        root_id,
        MappingProxyType(roles),
        MappingProxyType(states),
        MappingProxyType(kinds),
    )


def _permit_values(
    *,
    runtime: object,
    agent_session_root: object,
    work_root: object,
    container_root: object,
    container_id: object,
    container_digest: object,
    operation: object,
    path: object,
    content_digest: object,
    request_id: object,
    nonce: object,
    authority_revision: object,
    issued_at: object,
    expires_at: object,
) -> dict[str, str]:
    issued = _time(issued_at, "issued at")
    expires = _time(expires_at, "expires at")
    if not issued < expires or expires - issued > MAX_PERMIT_SECONDS:
        raise InvalidCell("CDE write permit lifetime is invalid")
    return {
        "runtime": _root(runtime, "runtime", maximum=128).strip().lower(),
        "agent-session": _root(agent_session_root, "agent session"),
        "work": _root(work_root, "Work"),
        "container-root": _root(container_root, "container root"),
        "container-id": _root(container_id, "container"),
        "container-digest": _digest(container_digest, "container digest"),
        "operation": _root(operation, "operation", maximum=128),
        "path": _path(path),
        "content-digest": _digest(content_digest, "content digest"),
        "request-id": _root(request_id, "request", maximum=512),
        "nonce": _root(nonce, "nonce", maximum=512),
        "authority-revision": str(_revision(authority_revision)),
        "issued-at": "%.6f" % issued,
        "expires-at": "%.6f" % expires,
    }


def cde_write_permit_identity(
    *,
    runtime: str,
    agent_session_root: str,
    work_root: str,
    container_root: str,
    container_id: str,
    container_digest: str,
    operation: str,
    path: str,
    content_digest: str,
    request_id: str,
    nonce: str,
    authorization_evidence: str,
) -> str:
    """Derive one stable identity for one exact authorized write request."""
    fields = {
        "runtime": _root(runtime, "runtime", maximum=128).strip().lower(),
        "agent-session": _root(agent_session_root, "agent session"),
        "work": _root(work_root, "Work"),
        "container-root": _root(container_root, "container root"),
        "container-id": _root(container_id, "container"),
        "container-digest": _digest(container_digest, "container digest"),
        "operation": _root(operation, "operation", maximum=128),
        "path": _path(path),
        "content-digest": _digest(content_digest, "content digest"),
        "request-id": _root(request_id, "request", maximum=512),
        "nonce": _root(nonce, "nonce", maximum=512),
        "authorization-evidence": _root(
            authorization_evidence, "authorization evidence", maximum=1024
        ),
    }
    digest = hashlib.sha256(json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()
    return "app:cde-write-permit:" + digest


def issue_cde_write_permit(
    store: CellStore,
    protocol: CdeWriteAuthorityProtocol,
    signing_protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    descriptor_root: str,
    *,
    permit_id: str,
    runtime: str,
    agent_session_root: str,
    work_root: str,
    container_root: str,
    container_id: str,
    container_digest: str,
    operation: str,
    path: str,
    content_digest: str,
    request_id: str,
    nonce: str,
    issued_at: float,
    expires_at: float,
    authorization_evidence: str,
) -> tuple[CdeWritePermitProjection, int]:
    permit_id = _root(permit_id, "identity")
    base = store.snapshot()
    authorization_evidence = _root(
        authorization_evidence, "authorization evidence", maximum=1024
    )
    if permit_id in base.cells:
        existing = verify_cde_write_permit(
            base,
            protocol,
            signing_protocol,
            provider,
            permit_id,
            runtime=runtime,
            agent_session_root=agent_session_root,
            work_root=work_root,
            container_root=container_root,
            container_id=container_id,
            container_digest=container_digest,
            operation=operation,
            path=path,
            content_digest=content_digest,
            request_id=request_id,
            authorization_evidence=authorization_evidence,
            authority_revision=base.revision,
            now=_time(issued_at, "issued at"),
        )
        if not hmac.compare_digest(
            existing.nonce, _root(nonce, "nonce", maximum=512)
        ):
            raise CdeWriteDenied("CDE write permit nonce mismatched")
        return existing, base.revision
    accepted_revision = base.revision + 1
    values = _permit_values(
        runtime=runtime,
        agent_session_root=agent_session_root,
        work_root=work_root,
        container_root=container_root,
        container_id=container_id,
        container_digest=container_digest,
        operation=operation,
        path=path,
        content_digest=content_digest,
        request_id=request_id,
        nonce=nonce,
        authority_revision=accepted_revision,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    for label, root in (
        ("agent session", values["agent-session"]),
        ("Work", values["work"]),
        ("container root", values["container-root"]),
        ("authorization evidence", authorization_evidence),
    ):
        if root not in base.cells:
            raise CdeWriteDenied(
                "CDE write permit %s is not graph-held" % label
            )
    registered_permits = tuple(
        member.participant_id
        for member in read_relation(base, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("permit-member")
    )
    for existing_root in registered_permits:
        existing = _read_cde_write_permit_unchecked(
            base, protocol, existing_root
        )
        if hmac.compare_digest(existing.nonce, values["nonce"]):
            raise CdeWriteDenied("CDE write permit nonce was replayed")
        if hmac.compare_digest(existing.request_id, values["request-id"]):
            raise CdeWriteDenied("CDE write permit request was replayed")
    descriptor = read_signing_key_descriptor(
        base, signing_protocol, descriptor_root
    )
    if descriptor.values["purpose"] != "cde-write-permit":
        raise CdeWriteDenied("signing descriptor has the wrong purpose")
    envelope_root = permit_id + ":signature"
    envelope_cells = prepare_signature_envelope(
        base,
        signing_protocol,
        provider,
        descriptor_root,
        envelope_id=envelope_root,
        statement_protocol=STATEMENT_PROTOCOL,
        context=STATEMENT_CONTEXT,
        payload=_canonical_payload(values),
        authorization_evidence=authorization_evidence,
        issued_at=_iso_timestamp(float(issued_at)),
        request_id=request_id,
    )
    values["signature-envelope"] = envelope_root
    values["state"] = protocol.states["active"]
    fields = {
        name: permit_id + ":" + name
        for name in PERMIT_FIELDS
        if name not in {"signature-envelope", "state"}
    }
    relation = compose_relation_cells(
        (
            *((protocol.role(name), root) for name, root in fields.items()),
            (protocol.role("signature-envelope"), envelope_root),
            (protocol.role("state"), protocol.states["active"]),
        ),
        relation_id=permit_id,
    )
    append = prepare_append_relation_member(
        base,
        protocol.root_id,
        protocol.role("permit-member"),
        permit_id,
        budget=100_000,
    )
    try:
        revision = store.commit(
            base.revision,
            create=(
                *envelope_cells,
                *(_terminal(fields[name], values[name]) for name in fields),
                *relation.cells,
                *append.create,
            ),
            replace=append.replace,
        )
    except Conflict:
        if permit_id not in store.snapshot().cells:
            raise
        return issue_cde_write_permit(
            store,
            protocol,
            signing_protocol,
            provider,
            descriptor_root,
            permit_id=permit_id,
            runtime=runtime,
            agent_session_root=agent_session_root,
            work_root=work_root,
            container_root=container_root,
            container_id=container_id,
            container_digest=container_digest,
            operation=operation,
            path=path,
            content_digest=content_digest,
            request_id=request_id,
            nonce=nonce,
            issued_at=issued_at,
            expires_at=expires_at,
            authorization_evidence=authorization_evidence,
        )
    if revision != accepted_revision:
        raise CdeWriteDenied("CDE write permit accepted revision drifted")
    return read_cde_write_permit(store.snapshot(), protocol, permit_id), revision


def verify_cde_write_permit(
    snapshot: Snapshot,
    protocol: CdeWriteAuthorityProtocol,
    signing_protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    permit_root: str,
    *,
    runtime: str,
    agent_session_root: str,
    work_root: str,
    container_root: str,
    container_id: str,
    container_digest: str,
    operation: str,
    path: str,
    content_digest: str,
    request_id: str,
    authorization_evidence: str,
    authority_revision: int,
    now: float,
    _allow_consumed: bool = False,
    _allow_expired_receipt: bool = False,
) -> CdeWritePermitProjection:
    permit = _read_cde_write_permit_unchecked(snapshot, protocol, permit_root)
    if (
        permit.state_root == protocol.states["consumed"]
        and not _allow_consumed
    ):
        raise CdeWriteDenied("CDE write permit was already consumed")
    if permit.state_root == protocol.states["revoked"]:
        raise CdeWriteDenied("CDE write permit was revoked")
    expected = {
        "runtime": runtime.strip().lower() if type(runtime) is str else runtime,
        "agent session": agent_session_root,
        "Work": work_root,
        "container root": container_root,
        "container id": container_id,
        "container digest": container_digest,
        "operation": operation,
        "path": path.replace("\\", "/") if type(path) is str else path,
        "content digest": content_digest,
        "request": request_id,
        "authorization evidence": authorization_evidence,
    }
    actual = {
        "runtime": permit.runtime,
        "agent session": permit.agent_session_root,
        "Work": permit.work_root,
        "container root": permit.container_root,
        "container id": permit.container_id,
        "container digest": permit.container_digest,
        "operation": permit.operation,
        "path": permit.path,
        "content digest": permit.content_digest,
        "request": permit.request_id,
    }
    for label, value in expected.items():
        if label == "authorization evidence":
            continue
        if type(value) is not str or not hmac.compare_digest(actual[label], value):
            raise CdeWriteDenied("CDE write permit %s mismatched" % label)
    # The caller re-derives the exact Work/CDE authority at the current head.
    # Unrelated accepted facts may advance that head after permit issuance, but
    # a stale caller or a snapshot preceding the signed permit must fail.
    if (
        snapshot.revision != authority_revision
        or authority_revision < permit.authority_revision
    ):
        raise CdeWriteDenied("CDE write permit revision mismatched")
    moment = _time(now, "verification time")
    recovering_consumed_receipt = (
        _allow_consumed
        and _allow_expired_receipt
        and permit.state_root == protocol.states["consumed"]
    )
    if (
        moment < permit.issued_at
        or (
            moment >= permit.expires_at
            and not recovering_consumed_receipt
        )
    ):
        raise CdeWriteDenied("CDE write permit expired or is not yet valid")
    values = {
        "runtime": permit.runtime,
        "agent-session": permit.agent_session_root,
        "work": permit.work_root,
        "container-root": permit.container_root,
        "container-id": permit.container_id,
        "container-digest": permit.container_digest,
        "operation": permit.operation,
        "path": permit.path,
        "content-digest": permit.content_digest,
        "request-id": permit.request_id,
        "nonce": permit.nonce,
        "authority-revision": str(permit.authority_revision),
        "issued-at": "%.6f" % permit.issued_at,
        "expires-at": "%.6f" % permit.expires_at,
    }
    try:
        envelope = verify_signature_envelope(
            snapshot,
            signing_protocol,
            provider,
            permit.signature_envelope_root,
            payload=_canonical_payload(values),
            expected_statement_protocol=STATEMENT_PROTOCOL,
            expected_context=STATEMENT_CONTEXT,
        )
        descriptor = read_signing_key_descriptor(
            snapshot, signing_protocol, envelope.values["key-descriptor"]
        )
    except (InvalidCell, SigningAuthorityDenied) as exc:
        raise CdeWriteDenied("CDE write permit signature is invalid") from exc
    if descriptor.values["purpose"] != "cde-write-permit":
        raise CdeWriteDenied("CDE write permit signing purpose mismatched")
    evidence = expected["authorization evidence"]
    if (
        type(evidence) is not str
        or evidence not in snapshot.cells
        or not hmac.compare_digest(
            envelope.values["authorization-evidence"], evidence
        )
    ):
        raise CdeWriteDenied(
            "CDE write permit authorization evidence mismatched"
        )
    return permit


def _read_cde_write_permit_unchecked(
    snapshot: Snapshot,
    protocol: CdeWriteAuthorityProtocol,
    permit_root: str,
) -> CdeWritePermitProjection:
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("permit-member")
    }
    if permit_root not in registered:
        raise InvalidCell("CDE write permit is not registered")
    members = read_relation(snapshot, permit_root, budget=128)
    declared = {protocol.role(name) for name in PERMIT_FIELDS}
    if any(member.role_id not in declared for member in members):
        raise InvalidCell("CDE write permit contains an undeclared field")
    roots = {name: _one(members, protocol.role(name), name) for name in PERMIT_FIELDS}
    fields = {
        name: roots[name].participant_id
        for name in PERMIT_FIELDS
        if name not in {"signature-envelope", "state"}
    }
    values = {name: _text(snapshot, root, name) for name, root in fields.items()}
    normalized = _permit_values(
        runtime=values["runtime"],
        agent_session_root=values["agent-session"],
        work_root=values["work"],
        container_root=values["container-root"],
        container_id=values["container-id"],
        container_digest=values["container-digest"],
        operation=values["operation"],
        path=values["path"],
        content_digest=values["content-digest"],
        request_id=values["request-id"],
        nonce=values["nonce"],
        authority_revision=values["authority-revision"],
        issued_at=values["issued-at"],
        expires_at=values["expires-at"],
    )
    if normalized != values:
        raise InvalidCell("CDE write permit field encoding drifted")
    state_root = roots["state"].participant_id
    if state_root not in protocol.states.values():
        raise InvalidCell("CDE write permit state is invalid")
    return CdeWritePermitProjection(
        permit_root,
        MappingProxyType(fields),
        values["runtime"],
        values["agent-session"],
        values["work"],
        values["container-root"],
        values["container-id"],
        values["container-digest"],
        values["operation"],
        values["path"],
        values["content-digest"],
        values["request-id"],
        values["nonce"],
        int(values["authority-revision"]),
        float(values["issued-at"]),
        float(values["expires-at"]),
        roots["signature-envelope"].participant_id,
        state_root,
        roots["state"].incidence_id,
    )


def read_cde_write_permit(
    snapshot: Snapshot,
    protocol: CdeWriteAuthorityProtocol,
    permit_root: str,
) -> CdeWritePermitProjection:
    return _read_cde_write_permit_unchecked(snapshot, protocol, permit_root)


def read_cde_write_receipt(
    snapshot: Snapshot,
    protocol: CdeWriteAuthorityProtocol,
    receipt_root: str,
) -> CdeWriteReceiptProjection:
    """Read one registered receipt and re-derive every encoded claim."""
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("receipt-member")
    }
    if receipt_root not in registered:
        raise InvalidCell("CDE write receipt is not registered")
    members = read_relation(snapshot, receipt_root, budget=32)
    fields = (
        "receipt-permit",
        "receipt-kind",
        "receipt-digest",
        "receipt-recorded-at",
    )
    declared = {protocol.role(name) for name in fields}
    if any(member.role_id not in declared for member in members):
        raise InvalidCell("CDE write receipt contains an undeclared field")
    roots = {
        name: _one(members, protocol.role(name), name)
        for name in fields
    }
    permit_root = roots["receipt-permit"].participant_id
    kind_root = roots["receipt-kind"].participant_id
    kind_names = {
        root: name for name, root in protocol.receipt_kinds.items()
    }
    kind = kind_names.get(kind_root)
    if kind is None:
        raise InvalidCell("CDE write receipt kind is invalid")
    prefix = "%s:receipt:%s:" % (permit_root, kind)
    if not receipt_root.startswith(prefix):
        raise InvalidCell("CDE write receipt identity is invalid")
    evidence_digest = receipt_root[len(prefix):]
    _digest(evidence_digest, "receipt evidence")
    digest = _digest(
        _text(
            snapshot,
            roots["receipt-digest"].participant_id,
            "receipt digest",
        ),
        "receipt digest",
    )
    recorded_text = _text(
        snapshot,
        roots["receipt-recorded-at"].participant_id,
        "receipt time",
    )
    recorded_at = _time(recorded_text, "receipt time")
    if recorded_text != "%.6f" % recorded_at:
        raise InvalidCell("CDE write receipt time encoding drifted")
    expected_digest = hashlib.sha256(json.dumps(
        {
            "permit": permit_root,
            "kind": kind,
            "evidence": evidence_digest,
            "recorded-at": recorded_text,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest, expected_digest):
        raise InvalidCell("CDE write receipt digest mismatched")
    return CdeWriteReceiptProjection(
        receipt_root,
        permit_root,
        kind_root,
        digest,
        recorded_at,
    )


def _prepare_receipt(
    snapshot: Snapshot,
    protocol: CdeWriteAuthorityProtocol,
    permit: CdeWritePermitProjection,
    *,
    kind: str,
    evidence: str,
    recorded_at: float,
) -> CdeWriteReceiptPatch:
    if kind not in RECEIPT_KINDS:
        raise InvalidCell("CDE write receipt kind is invalid")
    if permit.root_id not in snapshot.cells:
        raise InvalidCell("CDE write permit is missing")
    recorded = _time(recorded_at, "receipt time")
    evidence_digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    receipt_root = "%s:receipt:%s:%s" % (
        permit.root_id,
        kind,
        evidence_digest,
    )
    if receipt_root in snapshot.cells:
        raise CdeWriteDenied("CDE write receipt was replayed")
    digest_fields = {
        "permit": permit.root_id,
        "kind": kind,
        "evidence": evidence_digest,
        "recorded-at": "%.6f" % recorded,
    }
    receipt_digest = hashlib.sha256(json.dumps(
        digest_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()
    values = {
        "receipt-digest": receipt_digest,
        "receipt-recorded-at": "%.6f" % recorded,
    }
    relation = compose_relation_cells(
        (
            (protocol.role("receipt-permit"), permit.root_id),
            (protocol.role("receipt-kind"), protocol.receipt_kinds[kind]),
            *((protocol.role(name), receipt_root + ":" + name) for name in values),
        ),
        relation_id=receipt_root,
    )
    append = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("receipt-member"),
        receipt_root,
        budget=100_000,
    )
    incidence = snapshot.cells.get(permit.state_incidence)
    if incidence is None:
        raise InvalidCell("CDE write permit state incidence is missing")
    state = Cell(
        incidence.id,
        incidence.link0,
        protocol.states[kind],
        incidence.atom,
    )
    replacements = {state.id: state, **{cell.id: cell for cell in append.replace}}
    receipt = CdeWriteReceiptProjection(
        receipt_root,
        permit.root_id,
        protocol.receipt_kinds[kind],
        receipt_digest,
        recorded,
    )
    return CdeWriteReceiptPatch(
        snapshot.revision,
        receipt,
        (
            *(_terminal(receipt_root + ":" + name, value) for name, value in values.items()),
            *relation.cells,
            *append.create,
        ),
        tuple(replacements.values()),
    )


def _receipt(
    store: CellStore,
    protocol: CdeWriteAuthorityProtocol,
    permit: CdeWritePermitProjection,
    *,
    kind: str,
    evidence: str,
    recorded_at: float,
) -> tuple[CdeWriteReceiptProjection, int]:
    patch = _prepare_receipt(
        store.snapshot(),
        protocol,
        permit,
        kind=kind,
        evidence=evidence,
        recorded_at=recorded_at,
    )
    revision = store.commit(
        patch.expected_revision,
        create=patch.create,
        replace=patch.replace,
    )
    return patch.receipt, revision


def prepare_cde_write_consumption(
    snapshot: Snapshot,
    protocol: CdeWriteAuthorityProtocol,
    signing_protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    permit_root: str,
    **request,
) -> CdeWriteReceiptPatch:
    """Verify one permit and prepare its receipt for an atomic wider commit."""
    permit = verify_cde_write_permit(
        snapshot, protocol, signing_protocol, provider, permit_root, **request
    )
    return _prepare_receipt(
        snapshot,
        protocol,
        permit,
        kind="consumed",
        evidence=permit.content_digest,
        recorded_at=float(request["now"]),
    )


def consume_cde_write_permit(
    store: CellStore,
    protocol: CdeWriteAuthorityProtocol,
    signing_protocol: SigningAuthorityProtocol,
    provider: SigningAuthorityProvider,
    permit_root: str,
    **request,
) -> tuple[CdeWriteReceiptProjection, int]:
    snapshot = store.snapshot()
    permit = _read_cde_write_permit_unchecked(
        snapshot, protocol, permit_root
    )
    if permit.state_root == protocol.states["consumed"]:
        permit = verify_cde_write_permit(
            snapshot,
            protocol,
            signing_protocol,
            provider,
            permit_root,
            _allow_consumed=True,
            _allow_expired_receipt=True,
            **request,
        )
        evidence_digest = hashlib.sha256(
            permit.content_digest.encode("utf-8")
        ).hexdigest()
        receipt_root = "%s:receipt:consumed:%s" % (
            permit.root_id,
            evidence_digest,
        )
        return (
            read_cde_write_receipt(snapshot, protocol, receipt_root),
            snapshot.revision,
        )
    patch = prepare_cde_write_consumption(
        snapshot,
        protocol,
        signing_protocol,
        provider,
        permit_root,
        **request,
    )
    revision = store.commit(
        patch.expected_revision,
        create=patch.create,
        replace=patch.replace,
    )
    return patch.receipt, revision


def revoke_cde_write_permit(
    store: CellStore,
    protocol: CdeWriteAuthorityProtocol,
    permit_root: str,
    *,
    reason: str,
    recorded_at: float | None = None,
) -> tuple[CdeWriteReceiptProjection, int]:
    permit = read_cde_write_permit(store.snapshot(), protocol, permit_root)
    if permit.state_root == protocol.states["consumed"]:
        raise CdeWriteDenied("consumed CDE write permit cannot be revoked")
    if permit.state_root == protocol.states["revoked"]:
        raise CdeWriteDenied("CDE write permit was already revoked")
    reason = _root(reason, "revocation reason", maximum=1024)
    return _receipt(
        store,
        protocol,
        permit,
        kind="revoked",
        evidence=reason,
        recorded_at=time.time() if recorded_at is None else recorded_at,
    )


__all__ = [
    "CdeWriteAuthorityProtocol",
    "CdeWriteDenied",
    "CdeWritePermitProjection",
    "CdeWriteReceiptProjection",
    "CdeWriteReceiptPatch",
    "authorize_cde_container_write",
    "bootstrap_cde_write_authority_protocol",
    "cde_write_permit_identity",
    "consume_cde_write_permit",
    "issue_cde_write_permit",
    "prepare_cde_write_consumption",
    "project_cde_write_authority_protocol",
    "read_cde_write_permit",
    "read_cde_write_receipt",
    "revoke_cde_write_permit",
    "verify_cde_write_permit",
]
