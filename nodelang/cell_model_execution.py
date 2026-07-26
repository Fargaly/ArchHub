"""Graph-native BABOOM model-delegation records.

The physical model process stays outside the graph.  This protocol persists the
bounded request, released adapter permission, exact BABOOM execution session,
one-use host grant digest, and redacted outcome receipt as ordinary Cell
compositions.  It deliberately stores no prompt, model output, credential, or
live capability token.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
import time
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_adapters import (
    AdapterProtocol,
    PermissionProjection,
    read_permission,
    verify_released_adapter,
)
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "registry-member",
    "protocol-registry",
    "provider-adapter",
    "provider-action",
    "provider-location",
    "provider-datatype",
    "delegation-session",
    "delegation-work",
    "delegation-cognition-request",
    "delegation-provider",
    "delegation-model",
    "delegation-input-digest",
    "delegation-datatype",
    "delegation-permission",
    "delegation-expires-at",
    "grant-delegation",
    "grant-session",
    "grant-expires-at",
    "grant-token-digest",
    "receipt-delegation",
    "receipt-grant",
    "receipt-provider",
    "receipt-model",
    "receipt-input-digest",
    "receipt-output-digest",
    "receipt-output-bytes",
    "receipt-outcome",
    "receipt-created-at",
    "receipt-error-code",
)
REGISTRY_NAMES = ("provider", "delegation", "grant", "receipt")

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_OUTCOMES = frozenset({"succeeded", "failed"})
_MAX_MODEL_BYTES = 256
_MAX_ERROR_BYTES = 128
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BaboomModelExecutionProtocol:
    root_id: str
    roles: Mapping[str, str]
    registries: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown BABOOM execution role %r" % name) from exc

    def registry(self, name: str) -> str:
        try:
            return self.registries[name]
        except KeyError as exc:
            raise InvalidCell("unknown BABOOM execution registry %r" % name) from exc


@dataclass(frozen=True, slots=True)
class ModelProviderProjection:
    root_id: str
    adapter_root: str
    action_root: str
    location_root: str
    datatype_roots: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelDelegationProjection:
    root_id: str
    session_root: str
    work_root: str
    provider_root: str
    model: str
    input_digest: str
    datatype_root: str
    permission_root: str
    expires_at: float
    cognition_request_root: str = ""


@dataclass(frozen=True, slots=True)
class ModelExecutionGrantProjection:
    root_id: str
    delegation_root: str
    session_root: str
    expires_at: float
    token_digest: str


@dataclass(frozen=True, slots=True)
class ModelExecutionReceiptProjection:
    root_id: str
    delegation_root: str
    grant_root: str
    provider_root: str
    model: str
    input_digest: str
    output_digest: str
    output_bytes: int
    outcome: str
    created_at: float
    error_code: str


def _terminal(root_id: str, value: object) -> Cell:
    if isinstance(value, bytes):
        atom = value
    elif isinstance(value, bool):
        atom = b"true" if value else b"false"
    else:
        atom = str(value).encode("utf-8")
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom)


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("%s Cell is missing" % label) from exc
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s must be terminal" % label)
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s must be UTF-8" % label) from exc


def _one(members: Iterable[RelationMember], role_id: str, label: str) -> str:
    values = tuple(member.participant_id for member in members if member.role_id == role_id)
    if len(values) != 1:
        raise InvalidCell("%s requires exactly one participant" % label)
    return values[0]


def _many(members: Iterable[RelationMember], role_id: str) -> tuple[str, ...]:
    return tuple(member.participant_id for member in members if member.role_id == role_id)


def _closed(members: Iterable[RelationMember], allowed: Iterable[str], label: str) -> None:
    allowed_roles = frozenset(allowed)
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("%s has an undeclared role" % label)


def _registered(snapshot: Snapshot, protocol: BaboomModelExecutionProtocol, name: str, root_id: str) -> bool:
    return sum(
        member.role_id == protocol.role("registry-member")
        and member.participant_id == root_id
        for member in read_relation(snapshot, protocol.registry(name), budget=100_000)
    ) == 1


def _require_digest(value: str, label: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise InvalidCell("%s must be a SHA-256 hexadecimal digest" % label)


def _bounded_text(value: str, label: str, limit: int) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > limit:
        raise InvalidCell("%s is invalid or exceeds its bound" % label)
    return value.strip()


def _validated_error_code(outcome: str, error_code: str) -> str:
    if type(error_code) is not str:
        raise InvalidCell("receipt error code is invalid")
    normalized = error_code.strip()
    if len(normalized.encode("utf-8")) > _MAX_ERROR_BYTES:
        raise InvalidCell("receipt error code exceeds its bound")
    if outcome == "succeeded":
        if normalized:
            raise InvalidCell("successful receipt cannot carry an error code")
        return ""
    if _ERROR_CODE.fullmatch(normalized) is None:
        raise InvalidCell("failed receipt error code is invalid")
    return normalized


def bootstrap_baboom_model_execution_protocol(
    store: CellStore,
    *,
    prefix: str = "app:baboom-model-execution:v1",
) -> BaboomModelExecutionProtocol:
    """Create or verify the protocol vocabulary and four append-only registries."""
    root_id = prefix + ":root"
    roles = MappingProxyType({name: prefix + ":role:" + name for name in ROLE_NAMES})
    registries = MappingProxyType({name: prefix + ":registry:" + name for name in REGISTRY_NAMES})
    snapshot = store.snapshot()
    if root_id not in snapshot.cells:
        batch = CellBatch(store)
        for name, root in roles.items():
            batch.add(_terminal(root, name))
        for root in registries.values():
            batch.relation((), relation_id=root)
        batch.relation(
            (
                *((roles["vocabulary-member"], root) for root in roles.values()),
                *((roles["protocol-registry"], root) for root in registries.values()),
            ),
            relation_id=root_id,
        )
        batch.commit()
        snapshot = store.snapshot()
    members = read_relation(snapshot, root_id, budget=100_000)
    vocabulary = set(_many(members, roles["vocabulary-member"]))
    unknown = vocabulary - set(roles.values())
    if unknown:
        raise InvalidCell("BABOOM model-execution vocabulary drifted")
    missing = tuple(root for root in roles.values() if root not in vocabulary)
    if missing:
        patch = prepare_append_relation_members(
            snapshot,
            root_id,
            tuple((roles["vocabulary-member"], root) for root in missing),
            budget=100_000,
        )
        store.commit(
            snapshot.revision,
            create=(*(_terminal(root, name) for name, root in roles.items() if root in missing), *patch.create),
            replace=patch.replace,
        )
        snapshot = store.snapshot()
        members = read_relation(snapshot, root_id, budget=100_000)
    _closed(
        members,
        (roles["vocabulary-member"], roles["protocol-registry"]),
        "BABOOM model-execution protocol",
    )
    if set(_many(members, roles["vocabulary-member"])) != set(roles.values()):
        raise InvalidCell("BABOOM model-execution vocabulary drifted")
    if set(_many(members, roles["protocol-registry"])) != set(registries.values()):
        raise InvalidCell("BABOOM model-execution registry wiring drifted")
    for root in registries.values():
        read_relation(snapshot, root, budget=100_000)
    return BaboomModelExecutionProtocol(root_id, roles, registries)


def register_model_provider(
    store: CellStore,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    provider_id: str,
    adapter_root: str,
    action_root: str,
    location_root: str,
    datatype_roots: Iterable[str],
) -> ModelProviderProjection:
    """Register one released adapter as an execution provider composition."""
    datatypes = tuple(dict.fromkeys(datatype_roots))
    if not datatypes:
        raise InvalidCell("model provider requires at least one data class")
    snapshot = store.snapshot()
    if provider_id in snapshot.cells:
        return read_model_provider(snapshot, protocol, adapter_protocol, provider_id)
    adapter = verify_released_adapter(snapshot, adapter_protocol, adapter_root)
    if (
        action_root not in adapter.action_roots
        or location_root not in adapter.location_roots
        or not set(datatypes).issubset(adapter.datatype_roots)
    ):
        raise InvalidCell("model provider exceeds released adapter bounds")
    relation = compose_relation_cells(
        (
            (protocol.role("provider-adapter"), adapter_root),
            (protocol.role("provider-action"), action_root),
            (protocol.role("provider-location"), location_root),
            *((protocol.role("provider-datatype"), root) for root in datatypes),
        ),
        relation_id=provider_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.registry("provider"),
        protocol.role("registry-member"),
        provider_id,
        budget=100_000,
    )
    store.commit(snapshot.revision, create=(*relation.cells, *patch.create), replace=patch.replace)
    return read_model_provider(store.snapshot(), protocol, adapter_protocol, provider_id)


def read_model_provider(
    snapshot: Snapshot,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    provider_root: str,
) -> ModelProviderProjection:
    if not _registered(snapshot, protocol, "provider", provider_root):
        raise InvalidCell("model provider is not registered exactly once")
    members = read_relation(snapshot, provider_root, budget=100_000)
    _closed(
        members,
        (
            protocol.role("provider-adapter"),
            protocol.role("provider-action"),
            protocol.role("provider-location"),
            protocol.role("provider-datatype"),
        ),
        "model provider",
    )
    provider = ModelProviderProjection(
        provider_root,
        _one(members, protocol.role("provider-adapter"), "provider adapter"),
        _one(members, protocol.role("provider-action"), "provider action"),
        _one(members, protocol.role("provider-location"), "provider location"),
        _many(members, protocol.role("provider-datatype")),
    )
    if not provider.datatype_roots or len(provider.datatype_roots) != len(set(provider.datatype_roots)):
        raise InvalidCell("model provider data classes are invalid")
    adapter = verify_released_adapter(snapshot, adapter_protocol, provider.adapter_root)
    if (
        provider.action_root not in adapter.action_roots
        or provider.location_root not in adapter.location_roots
        or not set(provider.datatype_roots).issubset(adapter.datatype_roots)
    ):
        raise InvalidCell("model provider adapter binding drifted")
    return provider


def create_model_delegation(
    store: CellStore,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    delegation_id: str,
    session_root: str,
    work_root: str,
    provider_root: str,
    model: str,
    input_digest: str,
    datatype_root: str,
    permission_root: str,
    expires_at: float,
    cognition_request_root: str = "",
) -> ModelDelegationProjection:
    """Persist a requested execution before any live host grant can exist."""
    model = _bounded_text(model, "model identity", _MAX_MODEL_BYTES)
    _require_digest(input_digest, "delegation input digest")
    if type(expires_at) not in (int, float) or not math.isfinite(float(expires_at)) or float(expires_at) <= time.time():
        raise InvalidCell("delegation expiry is invalid")
    snapshot = store.snapshot()
    if delegation_id in snapshot.cells:
        raise InvalidCell("model delegation identity already exists")
    provider = read_model_provider(snapshot, protocol, adapter_protocol, provider_root)
    permission = read_permission(snapshot, adapter_protocol, permission_root)
    if (
        permission.adapter_root != provider.adapter_root
        or provider.action_root not in permission.action_roots
        or provider.location_root not in permission.location_roots
        or datatype_root not in provider.datatype_roots
        or datatype_root not in permission.datatype_roots
        or permission.lifecycle_root != adapter_protocol.states["requested"]
    ):
        raise InvalidCell("model delegation permission does not exactly bind its provider")
    for root in (
        session_root, work_root, datatype_root, permission_root,
        *( (cognition_request_root,) if cognition_request_root else () ),
    ):
        if root not in snapshot.cells:
            raise InvalidCell("model delegation references a missing Cell")
    expires_root = delegation_id + ":expires-at"
    model_root = delegation_id + ":model"
    digest_root = delegation_id + ":input-digest"
    relation = compose_relation_cells(
        (
            (protocol.role("delegation-session"), session_root),
            (protocol.role("delegation-work"), work_root),
            *((protocol.role("delegation-cognition-request"), cognition_request_root)
              for _ in (0,) if cognition_request_root),
            (protocol.role("delegation-provider"), provider_root),
            (protocol.role("delegation-model"), model_root),
            (protocol.role("delegation-input-digest"), digest_root),
            (protocol.role("delegation-datatype"), datatype_root),
            (protocol.role("delegation-permission"), permission_root),
            (protocol.role("delegation-expires-at"), expires_root),
        ),
        relation_id=delegation_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.registry("delegation"),
        protocol.role("registry-member"),
        delegation_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(model_root, model),
            _terminal(digest_root, input_digest),
            _terminal(expires_root, repr(float(expires_at))),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_model_delegation(store.snapshot(), protocol, adapter_protocol, delegation_id)


def read_model_delegation(
    snapshot: Snapshot,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    delegation_root: str,
) -> ModelDelegationProjection:
    if not _registered(snapshot, protocol, "delegation", delegation_root):
        raise InvalidCell("model delegation is not registered exactly once")
    members = read_relation(snapshot, delegation_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "delegation-session", "delegation-work", "delegation-provider",
            "delegation-cognition-request",
            "delegation-model", "delegation-input-digest", "delegation-datatype",
            "delegation-permission", "delegation-expires-at",
        )),
        "model delegation",
    )
    model_root = _one(members, protocol.role("delegation-model"), "delegation model")
    digest_root = _one(members, protocol.role("delegation-input-digest"), "delegation input digest")
    expires_root = _one(members, protocol.role("delegation-expires-at"), "delegation expiry")
    cognition_requests = _many(
        members, protocol.role("delegation-cognition-request")
    )
    if len(cognition_requests) > 1:
        raise InvalidCell("model delegation Cognition Request is ambiguous")
    delegation = ModelDelegationProjection(
        delegation_root,
        _one(members, protocol.role("delegation-session"), "delegation session"),
        _one(members, protocol.role("delegation-work"), "delegation work"),
        _one(members, protocol.role("delegation-provider"), "delegation provider"),
        _bounded_text(_text(snapshot, model_root, "delegation model"), "model identity", _MAX_MODEL_BYTES),
        _text(snapshot, digest_root, "delegation input digest"),
        _one(members, protocol.role("delegation-datatype"), "delegation data class"),
        _one(members, protocol.role("delegation-permission"), "delegation permission"),
        float(_text(snapshot, expires_root, "delegation expiry")),
        cognition_requests[0] if cognition_requests else "",
    )
    _require_digest(delegation.input_digest, "delegation input digest")
    if not math.isfinite(delegation.expires_at):
        raise InvalidCell("delegation expiry is invalid")
    provider = read_model_provider(snapshot, protocol, adapter_protocol, delegation.provider_root)
    permission = read_permission(snapshot, adapter_protocol, delegation.permission_root)
    if (
        permission.adapter_root != provider.adapter_root
        or provider.action_root not in permission.action_roots
        or provider.location_root not in permission.location_roots
        or delegation.datatype_root not in provider.datatype_roots
        or delegation.datatype_root not in permission.datatype_roots
    ):
        raise InvalidCell("delegation permission binding drifted")
    return delegation


def create_model_execution_grant(
    store: CellStore,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    grant_id: str,
    delegation_root: str,
    session_root: str,
    expires_at: float,
    token_digest: str,
) -> ModelExecutionGrantProjection:
    """Record the public digest of one in-memory, one-use host capability."""
    _require_digest(token_digest, "execution grant token digest")
    if type(expires_at) not in (int, float) or not math.isfinite(float(expires_at)) or float(expires_at) <= time.time():
        raise InvalidCell("execution grant expiry is invalid")
    snapshot = store.snapshot()
    if grant_id in snapshot.cells:
        raise InvalidCell("execution grant identity already exists")
    delegation = read_model_delegation(snapshot, protocol, adapter_protocol, delegation_root)
    if delegation.session_root != session_root:
        raise InvalidCell("execution grant belongs to another Agent Session")
    if float(expires_at) > delegation.expires_at:
        raise InvalidCell("execution grant outlives its delegation")
    expires_root = grant_id + ":expires-at"
    digest_root = grant_id + ":token-digest"
    relation = compose_relation_cells(
        (
            (protocol.role("grant-delegation"), delegation_root),
            (protocol.role("grant-session"), session_root),
            (protocol.role("grant-expires-at"), expires_root),
            (protocol.role("grant-token-digest"), digest_root),
        ),
        relation_id=grant_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.registry("grant"),
        protocol.role("registry-member"),
        grant_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(expires_root, repr(float(expires_at))),
            _terminal(digest_root, token_digest),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_model_execution_grant(store.snapshot(), protocol, adapter_protocol, grant_id)


def read_model_execution_grant(
    snapshot: Snapshot,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    grant_root: str,
) -> ModelExecutionGrantProjection:
    if not _registered(snapshot, protocol, "grant", grant_root):
        raise InvalidCell("execution grant is not registered exactly once")
    members = read_relation(snapshot, grant_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "grant-delegation", "grant-session", "grant-expires-at", "grant-token-digest",
        )),
        "execution grant",
    )
    expires_root = _one(members, protocol.role("grant-expires-at"), "grant expiry")
    digest_root = _one(members, protocol.role("grant-token-digest"), "grant token digest")
    grant = ModelExecutionGrantProjection(
        grant_root,
        _one(members, protocol.role("grant-delegation"), "grant delegation"),
        _one(members, protocol.role("grant-session"), "grant session"),
        float(_text(snapshot, expires_root, "grant expiry")),
        _text(snapshot, digest_root, "grant token digest"),
    )
    _require_digest(grant.token_digest, "execution grant token digest")
    if not math.isfinite(grant.expires_at):
        raise InvalidCell("execution grant expiry is invalid")
    delegation = read_model_delegation(snapshot, protocol, adapter_protocol, grant.delegation_root)
    if grant.session_root != delegation.session_root or grant.expires_at > delegation.expires_at:
        raise InvalidCell("execution grant delegation binding drifted")
    return grant


def create_model_execution_receipt(
    store: CellStore,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    receipt_id: str,
    delegation_root: str,
    grant_root: str,
    provider_root: str,
    model: str,
    input_digest: str,
    output_digest: str,
    output_bytes: int,
    outcome: str,
    error_code: str = "",
    created_at: float | None = None,
) -> ModelExecutionReceiptProjection:
    """Persist only redacted provider outcome evidence after one host attempt."""
    model = _bounded_text(model, "receipt model", _MAX_MODEL_BYTES)
    _require_digest(input_digest, "receipt input digest")
    _require_digest(output_digest, "receipt output digest")
    if type(output_bytes) is not int or output_bytes < 0 or output_bytes > _MAX_OUTPUT_BYTES:
        raise InvalidCell("receipt output byte count is invalid")
    if outcome not in _OUTCOMES:
        raise InvalidCell("receipt outcome is invalid")
    error_code = _validated_error_code(outcome, error_code)
    timestamp = time.time() if created_at is None else float(created_at)
    if not math.isfinite(timestamp):
        raise InvalidCell("receipt timestamp is invalid")
    snapshot = store.snapshot()
    if receipt_id in snapshot.cells:
        raise InvalidCell("execution receipt identity already exists")
    delegation = read_model_delegation(snapshot, protocol, adapter_protocol, delegation_root)
    grant = read_model_execution_grant(snapshot, protocol, adapter_protocol, grant_root)
    if (
        grant.delegation_root != delegation_root
        or provider_root != delegation.provider_root
        or model != delegation.model
        or input_digest != delegation.input_digest
    ):
        raise InvalidCell("execution receipt does not match its delegated effect")
    if any(
        read_model_execution_receipt(snapshot, protocol, adapter_protocol, member.participant_id).delegation_root == delegation_root
        for member in read_relation(snapshot, protocol.registry("receipt"), budget=100_000)
        if member.role_id == protocol.role("registry-member")
    ):
        raise InvalidCell("delegation already has a settled receipt")
    values = {
        "model": receipt_id + ":model",
        "input": receipt_id + ":input-digest",
        "output": receipt_id + ":output-digest",
        "bytes": receipt_id + ":output-bytes",
        "outcome": receipt_id + ":outcome",
        "created": receipt_id + ":created-at",
        "error": receipt_id + ":error-code",
    }
    relation = compose_relation_cells(
        (
            (protocol.role("receipt-delegation"), delegation_root),
            (protocol.role("receipt-grant"), grant_root),
            (protocol.role("receipt-provider"), provider_root),
            (protocol.role("receipt-model"), values["model"]),
            (protocol.role("receipt-input-digest"), values["input"]),
            (protocol.role("receipt-output-digest"), values["output"]),
            (protocol.role("receipt-output-bytes"), values["bytes"]),
            (protocol.role("receipt-outcome"), values["outcome"]),
            (protocol.role("receipt-created-at"), values["created"]),
            (protocol.role("receipt-error-code"), values["error"]),
        ),
        relation_id=receipt_id,
    )
    patch = prepare_append_relation_member(
        snapshot,
        protocol.registry("receipt"),
        protocol.role("registry-member"),
        receipt_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(
            _terminal(values["model"], model),
            _terminal(values["input"], input_digest),
            _terminal(values["output"], output_digest),
            _terminal(values["bytes"], output_bytes),
            _terminal(values["outcome"], outcome),
            _terminal(values["created"], repr(timestamp)),
            _terminal(values["error"], error_code),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_model_execution_receipt(store.snapshot(), protocol, adapter_protocol, receipt_id)


def read_model_execution_receipt(
    snapshot: Snapshot,
    protocol: BaboomModelExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    receipt_root: str,
) -> ModelExecutionReceiptProjection:
    if not _registered(snapshot, protocol, "receipt", receipt_root):
        raise InvalidCell("execution receipt is not registered exactly once")
    members = read_relation(snapshot, receipt_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "receipt-delegation", "receipt-grant", "receipt-provider", "receipt-model",
            "receipt-input-digest", "receipt-output-digest", "receipt-output-bytes",
            "receipt-outcome", "receipt-created-at", "receipt-error-code",
        )),
        "execution receipt",
    )
    values = {
        name: _one(members, protocol.role(role), "receipt " + name)
        for name, role in (
            ("delegation", "receipt-delegation"), ("grant", "receipt-grant"),
            ("provider", "receipt-provider"), ("model", "receipt-model"),
            ("input", "receipt-input-digest"), ("output", "receipt-output-digest"),
            ("bytes", "receipt-output-bytes"), ("outcome", "receipt-outcome"),
            ("created", "receipt-created-at"), ("error", "receipt-error-code"),
        )
    }
    receipt = ModelExecutionReceiptProjection(
        receipt_root,
        values["delegation"], values["grant"], values["provider"],
        _bounded_text(_text(snapshot, values["model"], "receipt model"), "receipt model", _MAX_MODEL_BYTES),
        _text(snapshot, values["input"], "receipt input digest"),
        _text(snapshot, values["output"], "receipt output digest"),
        int(_text(snapshot, values["bytes"], "receipt output bytes")),
        _text(snapshot, values["outcome"], "receipt outcome"),
        float(_text(snapshot, values["created"], "receipt created at")),
        _text(snapshot, values["error"], "receipt error code"),
    )
    _require_digest(receipt.input_digest, "receipt input digest")
    _require_digest(receipt.output_digest, "receipt output digest")
    if (
        receipt.output_bytes < 0
        or receipt.output_bytes > _MAX_OUTPUT_BYTES
        or receipt.outcome not in _OUTCOMES
        or not math.isfinite(receipt.created_at)
    ):
        raise InvalidCell("execution receipt values are invalid")
    _validated_error_code(receipt.outcome, receipt.error_code)
    delegation = read_model_delegation(snapshot, protocol, adapter_protocol, receipt.delegation_root)
    grant = read_model_execution_grant(snapshot, protocol, adapter_protocol, receipt.grant_root)
    if (
        grant.delegation_root != delegation.root_id
        or receipt.provider_root != delegation.provider_root
        or receipt.model != delegation.model
        or receipt.input_digest != delegation.input_digest
    ):
        raise InvalidCell("execution receipt binding drifted")
    return receipt


__all__ = [
    "BaboomModelExecutionProtocol", "ModelProviderProjection",
    "ModelDelegationProjection", "ModelExecutionGrantProjection",
    "ModelExecutionReceiptProjection", "bootstrap_baboom_model_execution_protocol",
    "register_model_provider", "read_model_provider", "create_model_delegation",
    "read_model_delegation", "create_model_execution_grant",
    "read_model_execution_grant", "create_model_execution_receipt",
    "read_model_execution_receipt",
]
