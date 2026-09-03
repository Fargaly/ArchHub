"""Digest-bound court definitions and signed graph attestations.

Court definitions and evidence are ordinary universal cells. Signing authority
is deliberately not graph data: a broker uses an external key provider and an
admitted runner implementation. A cell saying ``result=pass`` therefore has no
authority unless its exact DSSE-style payload and key version verify.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import threading
import time
from types import MappingProxyType
from typing import Callable, Iterable, Mapping
import uuid

from .cell_protocols import CellBatch, RelationMember, read_relation
from .cell_secret_keys import MemorySigningKeyProvider, SigningKeyProvider
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
COURT_PREDICATE_TYPE = "https://archhub.local/attestation/court/v1"
DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"

ROLE_NAMES = (
    "vocabulary-member",
    "name",
    "builder",
    "runner-version",
    "policy-digest",
    "check",
    "predicate-type",
    "lifecycle",
    "digest",
    "court",
    "subject-name",
    "subject-digest",
    "payload",
    "signature",
    "result",
    "issued-at",
    "key-reference",
    "key-version",
)


@dataclass(frozen=True, slots=True)
class AttestationProtocol:
    root_id: str
    roles: Mapping[str, str]
    states: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown attestation role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class CourtDefinition:
    root_id: str
    name_root: str
    builder_root: str
    runner_version_root: str
    policy_digest_root: str
    predicate_type_root: str
    check_roots: tuple[str, ...]
    lifecycle_root: str
    digest_root: str


@dataclass(frozen=True, slots=True)
class CourtInvocation:
    subject_name: str
    subject_digest: str
    subject_content: bytes
    external_parameters: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CourtResult:
    passed: bool
    checks: Mapping[str, bool]
    details: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AttestationProjection:
    root_id: str
    court_root: str
    subject_name_root: str
    subject_digest_root: str
    payload_root: str
    signature_root: str
    result_root: str
    issued_at_root: str
    key_reference_root: str
    key_version_root: str


class CourtEvidenceDenied(PermissionError):
    pass


_EVIDENCE_RECEIPT_KEY = object()


class CourtEvidenceReceipt:
    """Unforgeable, one-use capability returned by exact evidence consume."""

    __slots__ = ("_nonce",)

    def __init__(self, key: object) -> None:
        if key is not _EVIDENCE_RECEIPT_KEY:
            raise TypeError("court evidence receipts are broker-minted")
        self._nonce = secrets.token_hex(16)

    def __reduce_ex__(self, protocol):
        raise TypeError("court evidence receipts cannot be serialized")


@dataclass(frozen=True, slots=True)
class _AdmittedCourt:
    definition_digest: str
    runner: Callable[[CourtInvocation], CourtResult]


@dataclass(slots=True)
class _ConsumedEvidence:
    evidence_root: str
    purpose: str
    court_root: str
    subject_name: str
    subject_digest: str
    parameters: Mapping[str, str]
    expires_at: float
    used: bool = False


def _atom(snapshot: Snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("attestation value is missing or invalid UTF-8") from exc


def _terminal(batch: CellBatch, root_id: str, value: str) -> str:
    encoded = str(value).encode("utf-8")
    if not encoded:
        raise InvalidCell("attestation values cannot be empty")
    batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, encoded))
    return root_id


def _for_role(
    members: Iterable[RelationMember], role_id: str
) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )


def _one(
    members: tuple[RelationMember, ...], role_id: str, label: str
) -> str:
    values = _for_role(members, role_id)
    if len(values) != 1:
        raise InvalidCell("attestation graph requires exactly one %s" % label)
    return values[0]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _definition_digest(
    snapshot: Snapshot, definition: CourtDefinition
) -> str:
    digest = hashlib.sha256()
    for root in (
        definition.root_id,
        definition.name_root,
        definition.builder_root,
        definition.runner_version_root,
        definition.policy_digest_root,
        definition.predicate_type_root,
        *sorted(definition.check_roots),
    ):
        raw = root.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        if root != definition.root_id:
            atom = snapshot.cells[root].atom
            digest.update(len(atom).to_bytes(8, "big"))
            digest.update(atom)
    return digest.hexdigest()


def _dsse_pae(payload_type: str, payload: bytes) -> bytes:
    type_bytes = payload_type.encode("utf-8")
    return b"DSSEv1 %d " % len(type_bytes) + type_bytes + (
        b" %d " % len(payload)
    ) + payload


def bootstrap_attestation_protocol(
    store: CellStore, *, prefix: str = "attestation-protocol"
) -> AttestationProtocol:
    roles = {name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES}
    states = {
        "draft": prefix + ":state:draft",
        "released": prefix + ":state:released",
        "passed": prefix + ":state:passed",
        "failed": prefix + ":state:failed",
    }
    batch = CellBatch(store)
    for name, root in roles.items():
        _terminal(batch, root, name)
    for name, root in states.items():
        _terminal(batch, root, name)
    root_id = prefix + ":root"
    batch.relation([
        *((roles["vocabulary-member"], root) for root in roles.values()),
        *((roles["vocabulary-member"], root) for root in states.values()),
    ], relation_id=root_id)
    batch.commit()
    return AttestationProtocol(
        root_id, MappingProxyType(roles), MappingProxyType(states)
    )


def build_court_definition(
    store: CellStore,
    protocol: AttestationProtocol,
    *,
    court_id: str,
    name: str,
    builder_id: str,
    runner_version: str,
    policy_digest: str,
    checks: Iterable[str],
    predicate_type: str = COURT_PREDICATE_TYPE,
) -> CourtDefinition:
    """Build one released, digest-pinned court contract in the graph."""
    check_names = tuple(dict.fromkeys(str(check) for check in checks))
    if not check_names or any(not check for check in check_names):
        raise InvalidCell("court definition requires named checks")
    batch = CellBatch(store)
    name_root = _terminal(batch, court_id + ":name", name)
    builder_root = _terminal(batch, court_id + ":builder", builder_id)
    version_root = _terminal(
        batch, court_id + ":runner-version", runner_version
    )
    policy_root = _terminal(
        batch, court_id + ":policy-digest", policy_digest
    )
    predicate_root = _terminal(
        batch, court_id + ":predicate-type", predicate_type
    )
    check_roots = tuple(
        _terminal(batch, "%s:check:%d" % (court_id, index), check)
        for index, check in enumerate(check_names)
    )
    digest_root = court_id + ":digest"
    batch.add(Cell(digest_root, NULL_CELL_ID, NULL_CELL_ID, b""))
    batch.relation([
        (protocol.role("name"), name_root),
        (protocol.role("builder"), builder_root),
        (protocol.role("runner-version"), version_root),
        (protocol.role("policy-digest"), policy_root),
        (protocol.role("predicate-type"), predicate_root),
        *((protocol.role("check"), root) for root in check_roots),
        (protocol.role("lifecycle"), protocol.states["released"]),
        (protocol.role("digest"), digest_root),
    ], relation_id=court_id)
    batch.commit()
    definition = read_court_definition(store.snapshot(), protocol, court_id)
    digest = _definition_digest(store.snapshot(), definition).encode("ascii")
    current = store.read(digest_root)
    store.commit(store.revision, replace=(Cell(
        current.id, current.link0, current.link1, digest
    ),))
    return read_court_definition(store.snapshot(), protocol, court_id)


def read_court_definition(
    snapshot: Snapshot,
    protocol: AttestationProtocol,
    court_root: str,
) -> CourtDefinition:
    members = read_relation(snapshot, court_root, budget=1024)
    allowed = {
        protocol.role(name) for name in (
            "name", "builder", "runner-version", "policy-digest", "check",
            "predicate-type", "lifecycle", "digest",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("court definition contains an undeclared field")
    definition = CourtDefinition(
        court_root,
        _one(members, protocol.role("name"), "name"),
        _one(members, protocol.role("builder"), "builder"),
        _one(members, protocol.role("runner-version"), "runner version"),
        _one(members, protocol.role("policy-digest"), "policy digest"),
        _one(members, protocol.role("predicate-type"), "predicate type"),
        _for_role(members, protocol.role("check")),
        _one(members, protocol.role("lifecycle"), "lifecycle"),
        _one(members, protocol.role("digest"), "definition digest"),
    )
    if definition.lifecycle_root != protocol.states["released"]:
        raise InvalidCell("court definition is not released")
    if not definition.check_roots:
        raise InvalidCell("court definition has no checks")
    return definition


def verify_court_definition(
    snapshot: Snapshot,
    protocol: AttestationProtocol,
    court_root: str,
) -> CourtDefinition:
    definition = read_court_definition(snapshot, protocol, court_root)
    if not hmac.compare_digest(
        _atom(snapshot, definition.digest_root),
        _definition_digest(snapshot, definition),
    ):
        raise InvalidCell("court definition has drifted")
    return definition


def read_court_attestation(
    snapshot: Snapshot,
    protocol: AttestationProtocol,
    evidence_root: str,
) -> AttestationProjection:
    members = read_relation(snapshot, evidence_root, budget=1024)
    allowed = {
        protocol.role(name) for name in (
            "court", "subject-name", "subject-digest", "payload",
            "signature", "result", "issued-at", "key-reference",
            "key-version",
        )
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("court attestation contains an undeclared field")
    return AttestationProjection(
        evidence_root,
        _one(members, protocol.role("court"), "court"),
        _one(members, protocol.role("subject-name"), "subject name"),
        _one(members, protocol.role("subject-digest"), "subject digest"),
        _one(members, protocol.role("payload"), "payload"),
        _one(members, protocol.role("signature"), "signature"),
        _one(members, protocol.role("result"), "result"),
        _one(members, protocol.role("issued-at"), "issued timestamp"),
        _one(members, protocol.role("key-reference"), "key reference"),
        _one(members, protocol.role("key-version"), "key version"),
    )


class CourtAttestationBroker:
    """Trusted runner and signer boundary for visible graph evidence."""

    def __init__(
        self,
        *,
        key_provider: SigningKeyProvider | None = None,
        key_id: str = "court-attestation",
    ) -> None:
        self._key_provider = (
            key_provider if key_provider is not None else MemorySigningKeyProvider(
                key_id, secrets.token_bytes(32)
            )
        )
        self._key_id = key_id
        self._courts: dict[str, _AdmittedCourt] = {}
        self._consumed: set[tuple[str, str]] = set()
        self._receipts: dict[CourtEvidenceReceipt, _ConsumedEvidence] = {}
        self._lock = threading.RLock()

    def __reduce_ex__(self, protocol):
        raise TypeError("court attestation brokers cannot be serialized")

    def admit_court(
        self,
        snapshot: Snapshot,
        protocol: AttestationProtocol,
        court_root: str,
        runner: Callable[[CourtInvocation], CourtResult],
    ) -> None:
        definition = verify_court_definition(snapshot, protocol, court_root)
        with self._lock:
            if court_root in self._courts:
                raise CourtEvidenceDenied("court runner is already admitted")
            self._courts[court_root] = _AdmittedCourt(
                _atom(snapshot, definition.digest_root), runner
            )

    def run(
        self,
        store: CellStore,
        protocol: AttestationProtocol,
        court_root: str,
        *,
        subject_name: str,
        subject_content: bytes,
        external_parameters: Mapping[str, str],
    ) -> str:
        snapshot = store.snapshot()
        definition = verify_court_definition(snapshot, protocol, court_root)
        with self._lock:
            admitted = self._courts.get(court_root)
        if admitted is None:
            raise CourtEvidenceDenied("court runner is not admitted")
        if not hmac.compare_digest(
            admitted.definition_digest, _atom(snapshot, definition.digest_root)
        ):
            raise CourtEvidenceDenied("admitted court definition has drifted")
        content = bytes(subject_content)
        subject_digest = hashlib.sha256(content).hexdigest()
        invocation = CourtInvocation(
            subject_name,
            subject_digest,
            content,
            MappingProxyType({
                str(key): str(value)
                for key, value in sorted(external_parameters.items())
            }),
        )
        started_at = datetime.now(timezone.utc).isoformat()
        started_clock = time.monotonic()
        result = admitted.runner(invocation)
        if type(result) is not CourtResult:
            raise CourtEvidenceDenied("court runner returned an invalid result")
        expected_checks = {
            _atom(snapshot, root) for root in definition.check_roots
        }
        if set(result.checks) != expected_checks:
            raise CourtEvidenceDenied("court result does not cover exact checks")
        passed = result.passed and all(
            result.checks[name] for name in expected_checks
        )
        finished_at = datetime.now(timezone.utc).isoformat()
        statement = {
            "_type": STATEMENT_TYPE,
            "subject": [{
                "name": subject_name,
                "digest": {"sha256": subject_digest},
            }],
            "predicateType": _atom(
                snapshot, definition.predicate_type_root
            ),
            "predicate": {
                "court": court_root,
                "courtDigest": _atom(snapshot, definition.digest_root),
                "policyDigest": _atom(
                    snapshot, definition.policy_digest_root
                ),
                "builder": {
                    "id": _atom(snapshot, definition.builder_root),
                    "version": _atom(
                        snapshot, definition.runner_version_root
                    ),
                },
                "invocation": dict(invocation.external_parameters),
                "checks": {
                    name: bool(result.checks[name])
                    for name in sorted(expected_checks)
                },
                "details": {
                    str(key): str(value)
                    for key, value in sorted(result.details.items())
                },
                "result": "pass" if passed else "fail",
                "startedAt": started_at,
                "finishedAt": finished_at,
                "durationMs": round(
                    (time.monotonic() - started_clock) * 1000, 3
                ),
            },
        }
        payload = _canonical_json(statement)
        key_material = self._key_provider.current_reference(self._key_id)
        signature = self._key_provider.sign(
            key_material.key_id,
            key_material.version,
            _dsse_pae(DSSE_PAYLOAD_TYPE, payload),
        )
        token = uuid.uuid4().hex
        evidence_root = "attestation:evidence:" + token
        batch = CellBatch(store)
        subject_name_root = _terminal(
            batch, evidence_root + ":subject-name", subject_name
        )
        subject_digest_root = _terminal(
            batch, evidence_root + ":subject-digest", subject_digest
        )
        payload_root = evidence_root + ":payload"
        batch.add(Cell(payload_root, NULL_CELL_ID, NULL_CELL_ID, payload))
        signature_root = _terminal(
            batch, evidence_root + ":signature", signature
        )
        result_root = protocol.states["passed" if passed else "failed"]
        issued_root = _terminal(
            batch, evidence_root + ":issued-at", finished_at
        )
        key_reference_root = _terminal(
            batch, evidence_root + ":key-reference", key_material.key_id
        )
        key_version_root = _terminal(
            batch, evidence_root + ":key-version", str(key_material.version)
        )
        batch.relation([
            (protocol.role("court"), court_root),
            (protocol.role("subject-name"), subject_name_root),
            (protocol.role("subject-digest"), subject_digest_root),
            (protocol.role("payload"), payload_root),
            (protocol.role("signature"), signature_root),
            (protocol.role("result"), result_root),
            (protocol.role("issued-at"), issued_root),
            (protocol.role("key-reference"), key_reference_root),
            (protocol.role("key-version"), key_version_root),
        ], relation_id=evidence_root)
        batch.commit()
        return evidence_root

    def verify(
        self,
        snapshot: Snapshot,
        protocol: AttestationProtocol,
        evidence_root: str,
        *,
        expected_court_root: str,
        expected_subject_name: str,
        expected_subject_digest: str,
        expected_parameters: Mapping[str, str],
        expected_result: str = "pass",
        max_age_seconds: float = 900.0,
    ) -> Mapping[str, object]:
        if expected_result not in {"pass", "fail"}:
            raise ValueError("expected court result must be pass or fail")
        evidence = read_court_attestation(snapshot, protocol, evidence_root)
        if evidence.court_root != expected_court_root:
            raise CourtEvidenceDenied("attestation came from the wrong court")
        definition = verify_court_definition(
            snapshot, protocol, expected_court_root
        )
        with self._lock:
            admitted = self._courts.get(expected_court_root)
        if admitted is None or not hmac.compare_digest(
            admitted.definition_digest, _atom(snapshot, definition.digest_root)
        ):
            raise CourtEvidenceDenied("court signer-builder pair is not admitted")
        payload = snapshot.cells[evidence.payload_root].atom
        try:
            key_version = int(_atom(snapshot, evidence.key_version_root))
            key_reference = _atom(snapshot, evidence.key_reference_root)
        except Exception as exc:
            raise CourtEvidenceDenied(
                "attestation signing key is unavailable"
            ) from exc
        if not self._key_provider.verify(
            key_reference,
            key_version,
            _dsse_pae(DSSE_PAYLOAD_TYPE, payload),
            _atom(snapshot, evidence.signature_root),
        ):
            raise CourtEvidenceDenied("attestation signature is invalid")
        try:
            statement = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CourtEvidenceDenied("attestation payload is invalid") from exc
        expected_parameters = {
            str(key): str(value)
            for key, value in sorted(expected_parameters.items())
        }
        try:
            subject = statement["subject"]
            predicate = statement["predicate"]
            issued_at = datetime.fromisoformat(
                _atom(snapshot, evidence.issued_at_root)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CourtEvidenceDenied("attestation statement is incomplete") from exc
        expected_statement = (
            statement.get("_type") == STATEMENT_TYPE
            and statement.get("predicateType") == _atom(
                snapshot, definition.predicate_type_root
            )
            and isinstance(subject, list)
            and len(subject) == 1
            and subject[0].get("name") == expected_subject_name
            and subject[0].get("digest", {}).get("sha256")
            == expected_subject_digest
            and predicate.get("court") == expected_court_root
            and predicate.get("courtDigest")
            == _atom(snapshot, definition.digest_root)
            and predicate.get("policyDigest")
            == _atom(snapshot, definition.policy_digest_root)
            and predicate.get("invocation") == expected_parameters
            and predicate.get("result") == expected_result
            and evidence.result_root == protocol.states[
                "passed" if expected_result == "pass" else "failed"
            ]
            and _atom(snapshot, evidence.subject_name_root)
            == expected_subject_name
            and _atom(snapshot, evidence.subject_digest_root)
            == expected_subject_digest
        )
        if not expected_statement:
            raise CourtEvidenceDenied("attestation does not match exact promotion")
        age = datetime.now(timezone.utc).timestamp() - issued_at.timestamp()
        if age < -5 or age > max_age_seconds:
            raise CourtEvidenceDenied("attestation is stale")
        return MappingProxyType(statement)

    def consume(
        self,
        snapshot: Snapshot,
        protocol: AttestationProtocol,
        evidence_root: str,
        *,
        purpose: str,
        expected_court_root: str,
        expected_subject_name: str,
        expected_subject_digest: str,
        expected_parameters: Mapping[str, str],
        max_age_seconds: float = 900.0,
        receipt_lifetime_seconds: float = 120.0,
    ) -> CourtEvidenceReceipt:
        if receipt_lifetime_seconds <= 0 or receipt_lifetime_seconds > 300:
            raise ValueError(
                "court evidence receipt lifetime must be within five minutes"
            )
        self.verify(
            snapshot,
            protocol,
            evidence_root,
            expected_court_root=expected_court_root,
            expected_subject_name=expected_subject_name,
            expected_subject_digest=expected_subject_digest,
            expected_parameters=expected_parameters,
            max_age_seconds=max_age_seconds,
        )
        key = (evidence_root, str(purpose))
        with self._lock:
            if key in self._consumed:
                raise CourtEvidenceDenied(
                    "attestation was already consumed for this purpose"
                )
            self._consumed.add(key)
            receipt = CourtEvidenceReceipt(_EVIDENCE_RECEIPT_KEY)
            self._receipts[receipt] = _ConsumedEvidence(
                evidence_root,
                str(purpose),
                expected_court_root,
                expected_subject_name,
                expected_subject_digest,
                MappingProxyType({
                    str(name): str(value)
                    for name, value in sorted(expected_parameters.items())
                }),
                time.time() + receipt_lifetime_seconds,
            )
        return receipt

    def authorize_consumed_evidence(
        self,
        receipt: object,
        *,
        evidence_root: str,
        purpose: str,
        expected_subject_name: str,
        expected_subject_digest: str,
        expected_parameters: Mapping[str, str],
        now: float | None = None,
    ) -> None:
        """Spend one receipt on the exact transition it was verified for."""
        current = time.time() if now is None else now
        parameters = {
            str(name): str(value)
            for name, value in sorted(expected_parameters.items())
        }
        with self._lock:
            entry = (
                self._receipts.get(receipt)
                if type(receipt) is CourtEvidenceReceipt else None
            )
            if entry is None:
                raise CourtEvidenceDenied("unknown consumed-evidence receipt")
            if entry.used:
                raise CourtEvidenceDenied("consumed-evidence receipt was already used")
            if current >= entry.expires_at:
                raise CourtEvidenceDenied("consumed-evidence receipt expired")
            if (
                entry.evidence_root != evidence_root
                or entry.purpose != purpose
                or entry.subject_name != expected_subject_name
                or entry.subject_digest != expected_subject_digest
                or any(
                    entry.parameters.get(name) != value
                    for name, value in parameters.items()
                )
            ):
                raise CourtEvidenceDenied(
                    "consumed evidence does not authorize this transition"
                )
            entry.used = True


__all__ = [
    "STATEMENT_TYPE", "COURT_PREDICATE_TYPE", "DSSE_PAYLOAD_TYPE",
    "AttestationProtocol", "CourtDefinition", "CourtInvocation",
    "CourtResult", "AttestationProjection", "CourtEvidenceDenied",
    "CourtEvidenceReceipt",
    "CourtAttestationBroker", "bootstrap_attestation_protocol",
    "build_court_definition", "read_court_definition",
    "verify_court_definition", "read_court_attestation",
]
