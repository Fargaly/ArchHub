"""Allowlisted execution of an approved device-key Permission Request."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import time
from typing import Callable
import uuid

from .cell_adapters import (
    UserConsentBroker,
    authorize_adapter_invocation,
    build_permission_request as build_adapter_permission,
    grant_permission as grant_adapter_permission,
    read_permission as read_adapter_permission,
    verify_adapter_catalog,
    verify_released_adapter,
)
from .cell_cloud_sessions import (
    device_root_for_thumbprint,
    provision_device_binding,
)
from .cell_device_custody import (
    list_device_custody_roots,
    read_device_custody,
    register_device_custody,
)
from .cell_device_keys import PLATFORM_PROVIDER, WindowsCngDeviceProofKey
from .cell_identity import verify_authority_relationship
from .cell_permission_requests import read_permission_request
from .cell_state_machine import (
    machine_history,
    read_instance_state_machine,
    read_transition,
    transition_machine_with_new_evidence,
)
from .universal_cell import CellStore, InvalidCell


@dataclass(frozen=True, slots=True)
class DeviceEnrollmentResult:
    request_root: str
    outcome: str
    adapter_permission_root: str
    admission_evidence_root: str
    receipt_evidence_root: str
    device_root: str | None
    relationship_root: str | None
    custody_root: str | None
    revision: int


def _text(snapshot, root_id: str) -> str:
    try:
        return snapshot.cells[root_id].atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("device enrollment graph value is invalid") from exc


def _expiry(value: str) -> float:
    try:
        result = float(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidCell("device enrollment expiry is invalid") from exc
        if parsed.tzinfo is None:
            raise InvalidCell("device enrollment expiry lacks a timezone")
        result = parsed.astimezone(timezone.utc).timestamp()
    if not math.isfinite(result):
        raise InvalidCell("device enrollment expiry is not finite")
    return result


def _transition_for_label(snapshot, protocol, machine, label: str):
    matches = []
    for root in machine.transition_roots:
        transition = read_transition(snapshot, protocol, root)
        if (
            transition.from_state_root == machine.current_state_root
            and _text(snapshot, transition.event_root) == label
        ):
            matches.append(transition)
    if len(matches) != 1:
        raise InvalidCell(
            "device enrollment requires one admitted %s transition" % label
        )
    return matches[0]


def _bound_root(snapshot, roots, expected: str, label: str) -> str:
    matched = tuple(root for root in roots if _text(snapshot, root) == expected)
    if len(matched) != 1:
        raise InvalidCell("device adapter %s bound is missing" % label)
    return matched[0]


def _latest_approval_evidence(snapshot, protocol, machine_root: str) -> str:
    approved = tuple(
        event for event in machine_history(snapshot, protocol, machine_root)
        if _text(snapshot, event.event_root) == "approve"
    )
    if not approved or len(approved[-1].evidence_roots) != 1:
        raise InvalidCell("device enrollment lacks exact approval evidence")
    return approved[-1].evidence_roots[0]


def execute_device_enrollment(
    store: CellStore,
    registry,
    request_root: str,
    *,
    actor_root: str,
    consent_broker: UserConsentBroker,
    key_factory: Callable[[], object] | None = None,
    now: float | None = None,
) -> DeviceEnrollmentResult:
    """Execute one approved request; external and graph steps are retry-safe."""
    current_time = time.time() if now is None else float(now)
    snapshot = store.snapshot()
    definition_root = (
        registry.standard_library.governed_domains.definitions[
            "permission-request"
        ].definition_root
    )
    request = read_permission_request(
        snapshot,
        registry.assembly_protocol,
        registry.standard_library.state_machine_protocol,
        request_root,
        expected_definition_root=definition_root,
    )
    if request.fields["requester"] != actor_root:
        raise InvalidCell("device enrollment requester does not match the user")
    if request.fields["action"] != "device-key.enroll":
        raise InvalidCell("permission request is not a device enrollment")
    if request.fields["object"] != "device:this-machine":
        raise InvalidCell("device enrollment object is not this machine")
    try:
        parameters = json.loads(request.fields["parameters"])
    except json.JSONDecodeError as exc:
        raise InvalidCell("device enrollment parameters are invalid") from exc
    if parameters != {"algorithm": "ES256", "provider": "platform"}:
        raise InvalidCell("device enrollment parameters are not admitted")
    expires_at = _expiry(request.fields["expires-at"])
    if current_time >= expires_at:
        raise InvalidCell("device enrollment permission has expired")

    catalog = verify_adapter_catalog(
        snapshot, registry.adapter_protocol, registry.adapter_catalog_root
    )
    adapter_root = registry.device_custody_adapter_root
    if adapter_root not in catalog.adapter_roots:
        raise InvalidCell("device custody adapter is outside the allowlist")
    adapter = verify_released_adapter(
        snapshot, registry.adapter_protocol, adapter_root
    )
    action_root = _bound_root(
        snapshot, adapter.action_roots, "device-key.enroll", "action"
    )
    location_root = _bound_root(
        snapshot,
        adapter.location_roots,
        "windows-cng:platform-provider",
        "location",
    )
    datatype_root = _bound_root(
        snapshot, adapter.datatype_roots, "public-jwk", "datatype"
    )

    operational = registry.standard_library.state_machine_protocol
    machine = read_instance_state_machine(
        snapshot, registry.assembly_protocol, operational, request_root
    )
    execute = _transition_for_label(snapshot, operational, machine, "execute")
    if len(execute.required_evidence_type_roots) != 1 or _text(
        snapshot, execute.required_evidence_type_roots[0]
    ) != "execution admission":
        raise InvalidCell("device execution admission contract drifted")
    approval_evidence = _latest_approval_evidence(
        snapshot, operational, machine.root_id
    )
    permission_root = "adapter-permission:%s" % approval_evidence.rsplit(":", 1)[-1]
    if permission_root not in snapshot.cells:
        build_adapter_permission(
            store,
            registry.adapter_protocol,
            registry.adapter_catalog_root,
            request_id=permission_root,
            adapter_root=adapter_root,
            user_root=actor_root,
            action_roots=(action_root,),
            location_roots=(location_root,),
            datatype_roots=(datatype_root,),
            expires_at=min(expires_at, time.time() + 300.0),
            max_invocations=1,
        )
    permission = read_adapter_permission(
        store.snapshot(), registry.adapter_protocol, permission_root
    )
    if permission.lifecycle_root == registry.adapter_protocol.states["requested"]:
        handle = consent_broker.mint_from_user_gesture(
            permission_root, actor_root
        )
        grant_adapter_permission(
            store,
            registry.adapter_protocol,
            registry.adapter_catalog_root,
            permission_root,
            consent_broker,
            handle,
        )
    authorize_adapter_invocation(
        store.snapshot(),
        registry.adapter_protocol,
        registry.adapter_catalog_root,
        permission_root,
        adapter_root=adapter_root,
        user_root=actor_root,
        action_root=action_root,
        location_root=location_root,
        datatype_root=datatype_root,
        invocation_count=0,
        now=current_time,
    )
    admission_payload = json.dumps({
        "adapter": adapter_root,
        "adapter_permission": permission_root,
        "approval_evidence": approval_evidence,
        "request": request_root,
        "status": "admitted",
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    admission_evidence = "adapter-admission:%s" % uuid.uuid4().hex
    admission_evidence, _, _ = transition_machine_with_new_evidence(
        store,
        operational,
        machine.root_id,
        event_root=execute.event_root,
        expected_state_root=machine.current_state_root,
        actor_root=adapter_root,
        evidence_id=admission_evidence,
        evidence_type_root=execute.required_evidence_type_roots[0],
        evidence_payload=admission_payload,
        evidence_issuer_root=adapter_root,
        trusted_issuer_roots=(adapter_root,),
    )

    device_root = relationship_root = custody_root = None
    receipt_status = "succeeded"
    failure_type = None
    key = None
    try:
        factory = key_factory or (
            lambda: WindowsCngDeviceProofKey(
                "ArchHub.Device.DPoP.v1",
                provider=PLATFORM_PROVIDER,
                create_if_missing=True,
            )
        )
        key = factory()
        reference = key.reference
        if reference.provider != PLATFORM_PROVIDER or not reference.hardware_backed:
            raise InvalidCell("device enrollment did not receive TPM-backed custody")
        device_root = device_root_for_thumbprint(reference.thumbprint)
        relationship_root = "device-binding:sha256:" + reference.thumbprint
        active_snapshot = store.snapshot()
        if relationship_root in active_snapshot.cells:
            relationship = verify_authority_relationship(
                active_snapshot,
                registry.authorization.identity_protocol,
                registry.authorization.relationship_broker,
                relationship_root,
            )
            if (
                relationship.source_root != device_root
                or relationship.target_root != actor_root
                or relationship.kind_root
                != registry.authorization.identity_protocol.kinds["audience-binding"]
                or relationship.tenant_root != registry.authorization.tenant_root
                or relationship.scope_root != registry.authorization.audience_root
            ):
                raise InvalidCell("existing device binding does not match the request")
        else:
            relationship_root = provision_device_binding(
                store,
                registry.authorization.identity_protocol,
                registry.authorization.relationship_broker,
                registry.authorization.relationship_broker
                .mint_from_trusted_administrator(actor_root),
                relationship_id=relationship_root,
                proof_key_thumbprint=reference.thumbprint,
                subject_root=actor_root,
                tenant_root=registry.authorization.tenant_root,
                audience_root=registry.authorization.audience_root,
                administrator_root=actor_root,
                reason="Approved local device proof-key enrollment",
                evidence_roots=(approval_evidence, admission_evidence),
                now=current_time,
            )
        active_snapshot = store.snapshot()
        matching = tuple(
            root for root in list_device_custody_roots(
                active_snapshot, registry.device_custody_protocol
            )
            if read_device_custody(
                active_snapshot, registry.device_custody_protocol, root
            ).device_root == device_root
        )
        if len(matching) > 1:
            raise InvalidCell("device has multiple custody relations")
        if matching:
            custody_root = matching[0]
            custody = read_device_custody(
                active_snapshot, registry.device_custody_protocol, custody_root
            )
            if custody.state_root != registry.device_custody_protocol.states["active"]:
                raise InvalidCell("existing device custody is revoked")
        else:
            custody_root, _ = register_device_custody(
                store, registry.device_custody_protocol, reference,
                enrolled_at=current_time,
            )
    except Exception as exc:
        receipt_status = "failed"
        failure_type = type(exc).__name__
    finally:
        if key is not None:
            key.close()

    active_snapshot = store.snapshot()
    active_machine = read_instance_state_machine(
        active_snapshot, registry.assembly_protocol, operational, request_root
    )
    completion = _transition_for_label(
        active_snapshot,
        operational,
        active_machine,
        "succeed" if receipt_status == "succeeded" else "fail",
    )
    if len(completion.required_evidence_type_roots) != 1 or _text(
        active_snapshot, completion.required_evidence_type_roots[0]
    ) != "execution receipt":
        raise InvalidCell("device execution receipt contract drifted")
    receipt_payload = json.dumps({
        "adapter": adapter_root,
        "custody": custody_root,
        "device": device_root,
        "failure_type": failure_type,
        "relationship": relationship_root,
        "request": request_root,
        "status": receipt_status,
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    receipt_evidence = "adapter-receipt:%s" % uuid.uuid4().hex
    receipt_evidence, _, revision = transition_machine_with_new_evidence(
        store,
        operational,
        active_machine.root_id,
        event_root=completion.event_root,
        expected_state_root=active_machine.current_state_root,
        actor_root=adapter_root,
        evidence_id=receipt_evidence,
        evidence_type_root=completion.required_evidence_type_roots[0],
        evidence_payload=receipt_payload,
        evidence_issuer_root=adapter_root,
        trusted_issuer_roots=(adapter_root,),
    )
    return DeviceEnrollmentResult(
        request_root,
        receipt_status,
        permission_root,
        admission_evidence,
        receipt_evidence,
        device_root,
        relationship_root,
        custody_root,
        revision,
    )


__all__ = ["DeviceEnrollmentResult", "execute_device_enrollment"]
