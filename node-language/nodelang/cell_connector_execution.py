"""Graph-native BABOOM connector-effect records.

The graph persists only the bounded request, exact released adapter permission,
one-use host grant digest, and a redacted outcome receipt. Connector
credentials, request values, provider output, and live capability handles stay
outside Cells in the admitted local adapter runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_adapters import AdapterProtocol, read_permission, verify_released_adapter
from .cell_protocols import (
    CellBatch,
    RelationMember,
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member", "registry-member", "protocol-registry",
    "provider-adapter", "provider-action", "provider-location",
    "provider-datatype", "provider-operation", "delegation-session",
    "delegation-work", "delegation-provider", "delegation-input-digest",
    "delegation-input-bytes", "delegation-datatype", "delegation-permission",
    "delegation-expires-at", "grant-delegation", "grant-session",
    "grant-expires-at", "grant-token-digest", "receipt-delegation",
    "receipt-grant", "receipt-provider", "receipt-operation",
    "receipt-input-digest", "receipt-input-bytes", "receipt-output-digest",
    "receipt-output-bytes", "receipt-outcome", "receipt-created-at",
    "receipt-error-code",
)
REGISTRY_NAMES = ("provider", "delegation", "grant", "receipt")

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_OPERATION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_OUTCOMES = frozenset({"succeeded", "failed"})
_MAX_OPERATION_BYTES = 128
_MAX_INPUT_BYTES = 256 * 1024
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_ERROR_BYTES = 128


@dataclass(frozen=True, slots=True)
class BaboomConnectorExecutionProtocol:
    root_id: str
    roles: Mapping[str, str]
    registries: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown BABOOM connector-execution role %r" % name) from exc

    def registry(self, name: str) -> str:
        try:
            return self.registries[name]
        except KeyError as exc:
            raise InvalidCell("unknown BABOOM connector-execution registry %r" % name) from exc


@dataclass(frozen=True, slots=True)
class ConnectorProviderProjection:
    root_id: str
    adapter_root: str
    action_root: str
    location_root: str
    datatype_roots: tuple[str, ...]
    operation: str


@dataclass(frozen=True, slots=True)
class ConnectorDelegationProjection:
    root_id: str
    session_root: str
    work_root: str
    provider_root: str
    input_digest: str
    input_bytes: int
    datatype_root: str
    permission_root: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class ConnectorExecutionGrantProjection:
    root_id: str
    delegation_root: str
    session_root: str
    expires_at: float
    token_digest: str


@dataclass(frozen=True, slots=True)
class ConnectorExecutionReceiptProjection:
    root_id: str
    delegation_root: str
    grant_root: str
    provider_root: str
    operation: str
    input_digest: str
    input_bytes: int
    output_digest: str
    output_bytes: int
    outcome: str
    created_at: float
    error_code: str


def _terminal(root_id: str, value: object) -> Cell:
    if isinstance(value, bytes):
        atom = value
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


def _registered(
    snapshot: Snapshot,
    protocol: BaboomConnectorExecutionProtocol,
    name: str,
    root_id: str,
) -> bool:
    return sum(
        member.role_id == protocol.role("registry-member")
        and member.participant_id == root_id
        for member in read_relation(snapshot, protocol.registry(name), budget=100_000)
    ) == 1


def _require_digest(value: str, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise InvalidCell("%s must be a SHA-256 hexadecimal digest" % label)
    return value


def _require_operation(value: str, label: str = "connector operation") -> str:
    if (
        type(value) is not str
        or len(value.encode("utf-8")) > _MAX_OPERATION_BYTES
        or _OPERATION.fullmatch(value) is None
    ):
        raise InvalidCell("%s is invalid" % label)
    return value


def _require_bytes(value: object, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        raise InvalidCell("%s is invalid or exceeds its bound" % label)
    return value


def _validated_error_code(outcome: str, error_code: str) -> str:
    if outcome not in _OUTCOMES:
        raise InvalidCell("connector receipt outcome is invalid")
    if type(error_code) is not str:
        raise InvalidCell("connector receipt error code is invalid")
    normalized = error_code.strip()
    if len(normalized.encode("utf-8")) > _MAX_ERROR_BYTES:
        raise InvalidCell("connector receipt error code exceeds its bound")
    if outcome == "succeeded":
        if normalized:
            raise InvalidCell("successful connector receipt cannot carry an error code")
        return ""
    if _ERROR_CODE.fullmatch(normalized) is None:
        raise InvalidCell("failed connector receipt error code is invalid")
    return normalized


def bootstrap_baboom_connector_execution_protocol(
    store: CellStore,
    *,
    prefix: str = "app:baboom-connector-execution:v1",
) -> BaboomConnectorExecutionProtocol:
    """Create or verify the append-only connector execution vocabulary."""
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
    _closed(
        members,
        (roles["vocabulary-member"], roles["protocol-registry"]),
        "BABOOM connector-execution protocol",
    )
    if set(_many(members, roles["vocabulary-member"])) != set(roles.values()):
        raise InvalidCell("BABOOM connector-execution vocabulary drifted")
    if set(_many(members, roles["protocol-registry"])) != set(registries.values()):
        raise InvalidCell("BABOOM connector-execution registry wiring drifted")
    for root in registries.values():
        read_relation(snapshot, root, budget=100_000)
    return BaboomConnectorExecutionProtocol(root_id, roles, registries)


def register_connector_provider(
    store: CellStore,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    provider_id: str,
    adapter_root: str,
    action_root: str,
    location_root: str,
    datatype_roots: Iterable[str],
    operation: str,
) -> ConnectorProviderProjection:
    """Bind one exact connector operation to a released adapter contract."""
    datatypes = tuple(dict.fromkeys(datatype_roots))
    operation = _require_operation(operation)
    if not datatypes:
        raise InvalidCell("connector provider requires at least one data class")
    snapshot = store.snapshot()
    if provider_id in snapshot.cells:
        return read_connector_provider(snapshot, protocol, adapter_protocol, provider_id)
    adapter = verify_released_adapter(snapshot, adapter_protocol, adapter_root)
    if (
        action_root not in adapter.action_roots
        or location_root not in adapter.location_roots
        or not set(datatypes).issubset(adapter.datatype_roots)
    ):
        raise InvalidCell("connector provider exceeds released adapter bounds")
    operation_root = provider_id + ":operation"
    relation = compose_relation_cells(
        (
            (protocol.role("provider-adapter"), adapter_root),
            (protocol.role("provider-action"), action_root),
            (protocol.role("provider-location"), location_root),
            *((protocol.role("provider-datatype"), root) for root in datatypes),
            (protocol.role("provider-operation"), operation_root),
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
    store.commit(
        snapshot.revision,
        create=(_terminal(operation_root, operation), *relation.cells, *patch.create),
        replace=patch.replace,
    )
    return read_connector_provider(store.snapshot(), protocol, adapter_protocol, provider_id)


def read_connector_provider(
    snapshot: Snapshot,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    provider_root: str,
) -> ConnectorProviderProjection:
    if not _registered(snapshot, protocol, "provider", provider_root):
        raise InvalidCell("connector provider is not registered exactly once")
    members = read_relation(snapshot, provider_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "provider-adapter", "provider-action", "provider-location",
            "provider-datatype", "provider-operation",
        )),
        "connector provider",
    )
    provider = ConnectorProviderProjection(
        provider_root,
        _one(members, protocol.role("provider-adapter"), "provider adapter"),
        _one(members, protocol.role("provider-action"), "provider action"),
        _one(members, protocol.role("provider-location"), "provider location"),
        _many(members, protocol.role("provider-datatype")),
        _require_operation(
            _text(
                snapshot,
                _one(members, protocol.role("provider-operation"), "provider operation"),
                "provider operation",
            )
        ),
    )
    if not provider.datatype_roots or len(provider.datatype_roots) != len(set(provider.datatype_roots)):
        raise InvalidCell("connector provider data classes are invalid")
    adapter = verify_released_adapter(snapshot, adapter_protocol, provider.adapter_root)
    if (
        provider.action_root not in adapter.action_roots
        or provider.location_root not in adapter.location_roots
        or not set(provider.datatype_roots).issubset(adapter.datatype_roots)
    ):
        raise InvalidCell("connector provider adapter binding drifted")
    return provider


def create_connector_delegation(
    store: CellStore,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    delegation_id: str,
    session_root: str,
    work_root: str,
    provider_root: str,
    input_digest: str,
    input_bytes: int,
    datatype_root: str,
    permission_root: str,
    expires_at: float,
) -> ConnectorDelegationProjection:
    """Persist one exact connector effect request without its raw input."""
    _require_digest(input_digest, "connector delegation input digest")
    _require_bytes(input_bytes, "connector delegation input bytes", _MAX_INPUT_BYTES)
    if type(expires_at) not in (int, float) or not math.isfinite(float(expires_at)):
        raise InvalidCell("connector delegation expiry is invalid")
    snapshot = store.snapshot()
    if delegation_id in snapshot.cells:
        raise InvalidCell("connector delegation already exists")
    if session_root not in snapshot.cells or work_root not in snapshot.cells:
        raise InvalidCell("connector delegation session or work is missing")
    provider = read_connector_provider(snapshot, protocol, adapter_protocol, provider_root)
    permission = read_permission(snapshot, adapter_protocol, permission_root)
    if (
        datatype_root not in provider.datatype_roots
        or permission.adapter_root != provider.adapter_root
        or datatype_root not in permission.datatype_roots
    ):
        raise InvalidCell("connector delegation permission binding drifted")
    values = {
        "input": delegation_id + ":input-digest",
        "bytes": delegation_id + ":input-bytes",
        "expiry": delegation_id + ":expires-at",
    }
    relation = compose_relation_cells(
        (
            (protocol.role("delegation-session"), session_root),
            (protocol.role("delegation-work"), work_root),
            (protocol.role("delegation-provider"), provider_root),
            (protocol.role("delegation-input-digest"), values["input"]),
            (protocol.role("delegation-input-bytes"), values["bytes"]),
            (protocol.role("delegation-datatype"), datatype_root),
            (protocol.role("delegation-permission"), permission_root),
            (protocol.role("delegation-expires-at"), values["expiry"]),
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
            _terminal(values["input"], input_digest),
            _terminal(values["bytes"], input_bytes),
            _terminal(values["expiry"], repr(float(expires_at))),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_connector_delegation(store.snapshot(), protocol, adapter_protocol, delegation_id)


def read_connector_delegation(
    snapshot: Snapshot,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    delegation_root: str,
) -> ConnectorDelegationProjection:
    if not _registered(snapshot, protocol, "delegation", delegation_root):
        raise InvalidCell("connector delegation is not registered exactly once")
    members = read_relation(snapshot, delegation_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "delegation-session", "delegation-work", "delegation-provider",
            "delegation-input-digest", "delegation-input-bytes", "delegation-datatype",
            "delegation-permission", "delegation-expires-at",
        )),
        "connector delegation",
    )
    values = {
        name: _one(members, protocol.role(role), "delegation " + name)
        for name, role in (
            ("session", "delegation-session"), ("work", "delegation-work"),
            ("provider", "delegation-provider"), ("input", "delegation-input-digest"),
            ("bytes", "delegation-input-bytes"), ("datatype", "delegation-datatype"),
            ("permission", "delegation-permission"), ("expiry", "delegation-expires-at"),
        )
    }
    delegation = ConnectorDelegationProjection(
        delegation_root,
        values["session"], values["work"], values["provider"],
        _require_digest(_text(snapshot, values["input"], "delegation input digest"), "connector delegation input digest"),
        _require_bytes(int(_text(snapshot, values["bytes"], "delegation input bytes")), "connector delegation input bytes", _MAX_INPUT_BYTES),
        values["datatype"], values["permission"],
        float(_text(snapshot, values["expiry"], "delegation expiry")),
    )
    if not math.isfinite(delegation.expires_at):
        raise InvalidCell("connector delegation expiry is invalid")
    provider = read_connector_provider(snapshot, protocol, adapter_protocol, delegation.provider_root)
    permission = read_permission(snapshot, adapter_protocol, delegation.permission_root)
    if (
        delegation.session_root not in snapshot.cells
        or delegation.work_root not in snapshot.cells
        or delegation.datatype_root not in provider.datatype_roots
        or permission.adapter_root != provider.adapter_root
        or delegation.datatype_root not in permission.datatype_roots
    ):
        raise InvalidCell("connector delegation binding drifted")
    return delegation


def create_connector_execution_grant(
    store: CellStore,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    grant_id: str,
    delegation_root: str,
    session_root: str,
    expires_at: float,
    token_digest: str,
) -> ConnectorExecutionGrantProjection:
    """Persist only a host token digest; the one-use token is never a Cell."""
    _require_digest(token_digest, "connector grant token digest")
    if type(expires_at) not in (int, float) or not math.isfinite(float(expires_at)):
        raise InvalidCell("connector grant expiry is invalid")
    snapshot = store.snapshot()
    if grant_id in snapshot.cells:
        raise InvalidCell("connector execution grant already exists")
    delegation = read_connector_delegation(snapshot, protocol, adapter_protocol, delegation_root)
    permission = read_permission(snapshot, adapter_protocol, delegation.permission_root)
    if permission.lifecycle_root != adapter_protocol.states["granted"]:
        raise InvalidCell("connector execution permission is not granted")
    if session_root != delegation.session_root or session_root not in snapshot.cells:
        raise InvalidCell("connector grant session binding is invalid")
    values = {
        "expiry": grant_id + ":expires-at",
        "token": grant_id + ":token-digest",
    }
    relation = compose_relation_cells(
        (
            (protocol.role("grant-delegation"), delegation_root),
            (protocol.role("grant-session"), session_root),
            (protocol.role("grant-expires-at"), values["expiry"]),
            (protocol.role("grant-token-digest"), values["token"]),
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
            _terminal(values["expiry"], repr(float(expires_at))),
            _terminal(values["token"], token_digest),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_connector_execution_grant(store.snapshot(), protocol, adapter_protocol, grant_id)


def read_connector_execution_grant(
    snapshot: Snapshot,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    grant_root: str,
) -> ConnectorExecutionGrantProjection:
    if not _registered(snapshot, protocol, "grant", grant_root):
        raise InvalidCell("connector execution grant is not registered exactly once")
    members = read_relation(snapshot, grant_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "grant-delegation", "grant-session", "grant-expires-at", "grant-token-digest",
        )),
        "connector execution grant",
    )
    values = {
        name: _one(members, protocol.role(role), "grant " + name)
        for name, role in (
            ("delegation", "grant-delegation"), ("session", "grant-session"),
            ("expiry", "grant-expires-at"), ("token", "grant-token-digest"),
        )
    }
    grant = ConnectorExecutionGrantProjection(
        grant_root,
        values["delegation"], values["session"],
        float(_text(snapshot, values["expiry"], "grant expiry")),
        _require_digest(_text(snapshot, values["token"], "grant token digest"), "connector grant token digest"),
    )
    if not math.isfinite(grant.expires_at):
        raise InvalidCell("connector grant expiry is invalid")
    delegation = read_connector_delegation(snapshot, protocol, adapter_protocol, grant.delegation_root)
    if grant.session_root != delegation.session_root:
        raise InvalidCell("connector grant delegation binding drifted")
    return grant


def create_connector_execution_receipt(
    store: CellStore,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    *,
    receipt_id: str,
    delegation_root: str,
    grant_root: str,
    provider_root: str,
    input_digest: str,
    input_bytes: int,
    output_digest: str,
    output_bytes: int,
    outcome: str,
    error_code: str = "",
    created_at: float | None = None,
) -> ConnectorExecutionReceiptProjection:
    """Record one redacted external outcome and reject duplicate settlement."""
    _require_digest(input_digest, "connector receipt input digest")
    _require_digest(output_digest, "connector receipt output digest")
    _require_bytes(input_bytes, "connector receipt input bytes", _MAX_INPUT_BYTES)
    _require_bytes(output_bytes, "connector receipt output bytes", _MAX_OUTPUT_BYTES)
    error_code = _validated_error_code(outcome, error_code)
    timestamp = time.time() if created_at is None else float(created_at)
    if not math.isfinite(timestamp):
        raise InvalidCell("connector receipt timestamp is invalid")
    snapshot = store.snapshot()
    if receipt_id in snapshot.cells:
        raise InvalidCell("connector execution receipt already exists")
    if any(
        _one(read_relation(snapshot, root, budget=100_000), protocol.role("receipt-delegation"), "receipt delegation") == delegation_root
        for root in _many(
            read_relation(snapshot, protocol.registry("receipt"), budget=100_000),
            protocol.role("registry-member"),
        )
    ):
        raise InvalidCell("connector delegation already has a settled receipt")
    delegation = read_connector_delegation(snapshot, protocol, adapter_protocol, delegation_root)
    grant = read_connector_execution_grant(snapshot, protocol, adapter_protocol, grant_root)
    provider = read_connector_provider(snapshot, protocol, adapter_protocol, provider_root)
    if (
        grant.delegation_root != delegation.root_id
        or provider.root_id != delegation.provider_root
        or input_digest != delegation.input_digest
        or input_bytes != delegation.input_bytes
    ):
        raise InvalidCell("connector receipt binding drifted")
    values = {
        "operation": receipt_id + ":operation",
        "input": receipt_id + ":input-digest",
        "input_bytes": receipt_id + ":input-bytes",
        "output": receipt_id + ":output-digest",
        "output_bytes": receipt_id + ":output-bytes",
        "outcome": receipt_id + ":outcome",
        "created": receipt_id + ":created-at",
        "error": receipt_id + ":error-code",
    }
    relation = compose_relation_cells(
        (
            (protocol.role("receipt-delegation"), delegation_root),
            (protocol.role("receipt-grant"), grant_root),
            (protocol.role("receipt-provider"), provider_root),
            (protocol.role("receipt-operation"), values["operation"]),
            (protocol.role("receipt-input-digest"), values["input"]),
            (protocol.role("receipt-input-bytes"), values["input_bytes"]),
            (protocol.role("receipt-output-digest"), values["output"]),
            (protocol.role("receipt-output-bytes"), values["output_bytes"]),
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
            _terminal(values["operation"], provider.operation),
            _terminal(values["input"], input_digest),
            _terminal(values["input_bytes"], input_bytes),
            _terminal(values["output"], output_digest),
            _terminal(values["output_bytes"], output_bytes),
            _terminal(values["outcome"], outcome),
            _terminal(values["created"], repr(timestamp)),
            _terminal(values["error"], error_code),
            *relation.cells,
            *patch.create,
        ),
        replace=patch.replace,
    )
    return read_connector_execution_receipt(store.snapshot(), protocol, adapter_protocol, receipt_id)


def read_connector_execution_receipt(
    snapshot: Snapshot,
    protocol: BaboomConnectorExecutionProtocol,
    adapter_protocol: AdapterProtocol,
    receipt_root: str,
) -> ConnectorExecutionReceiptProjection:
    if not _registered(snapshot, protocol, "receipt", receipt_root):
        raise InvalidCell("connector execution receipt is not registered exactly once")
    members = read_relation(snapshot, receipt_root, budget=100_000)
    _closed(
        members,
        tuple(protocol.role(name) for name in (
            "receipt-delegation", "receipt-grant", "receipt-provider", "receipt-operation",
            "receipt-input-digest", "receipt-input-bytes", "receipt-output-digest",
            "receipt-output-bytes", "receipt-outcome", "receipt-created-at", "receipt-error-code",
        )),
        "connector execution receipt",
    )
    values = {
        name: _one(members, protocol.role(role), "receipt " + name)
        for name, role in (
            ("delegation", "receipt-delegation"), ("grant", "receipt-grant"),
            ("provider", "receipt-provider"), ("operation", "receipt-operation"),
            ("input", "receipt-input-digest"), ("input_bytes", "receipt-input-bytes"),
            ("output", "receipt-output-digest"), ("output_bytes", "receipt-output-bytes"),
            ("outcome", "receipt-outcome"), ("created", "receipt-created-at"),
            ("error", "receipt-error-code"),
        )
    }
    receipt = ConnectorExecutionReceiptProjection(
        receipt_root,
        values["delegation"], values["grant"], values["provider"],
        _require_operation(_text(snapshot, values["operation"], "receipt operation")),
        _require_digest(_text(snapshot, values["input"], "receipt input digest"), "connector receipt input digest"),
        _require_bytes(int(_text(snapshot, values["input_bytes"], "receipt input bytes")), "connector receipt input bytes", _MAX_INPUT_BYTES),
        _require_digest(_text(snapshot, values["output"], "receipt output digest"), "connector receipt output digest"),
        _require_bytes(int(_text(snapshot, values["output_bytes"], "receipt output bytes")), "connector receipt output bytes", _MAX_OUTPUT_BYTES),
        _text(snapshot, values["outcome"], "receipt outcome"),
        float(_text(snapshot, values["created"], "receipt created at")),
        _text(snapshot, values["error"], "receipt error code"),
    )
    if not math.isfinite(receipt.created_at):
        raise InvalidCell("connector receipt timestamp is invalid")
    _validated_error_code(receipt.outcome, receipt.error_code)
    delegation = read_connector_delegation(snapshot, protocol, adapter_protocol, receipt.delegation_root)
    grant = read_connector_execution_grant(snapshot, protocol, adapter_protocol, receipt.grant_root)
    provider = read_connector_provider(snapshot, protocol, adapter_protocol, receipt.provider_root)
    if (
        grant.delegation_root != delegation.root_id
        or receipt.provider_root != delegation.provider_root
        or receipt.operation != provider.operation
        or receipt.input_digest != delegation.input_digest
        or receipt.input_bytes != delegation.input_bytes
    ):
        raise InvalidCell("connector receipt binding drifted")
    return receipt


__all__ = [
    "BaboomConnectorExecutionProtocol", "ConnectorProviderProjection",
    "ConnectorDelegationProjection", "ConnectorExecutionGrantProjection",
    "ConnectorExecutionReceiptProjection", "bootstrap_baboom_connector_execution_protocol",
    "register_connector_provider", "read_connector_provider", "create_connector_delegation",
    "read_connector_delegation", "create_connector_execution_grant",
    "read_connector_execution_grant", "create_connector_execution_receipt",
    "read_connector_execution_receipt",
]
