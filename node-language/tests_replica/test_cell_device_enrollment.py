"""End-to-end court for permission-gated, allowlisted device enrollment."""
import base64
import hashlib
import json
from types import MappingProxyType

import pytest

from nodelang.cell_adapters import UserConsentBroker, read_permission
from nodelang.cell_device_custody import read_device_custody
from nodelang.cell_device_enrollment import execute_device_enrollment
from nodelang.cell_device_keys import DeviceProofKeyReference, PLATFORM_PROVIDER
from nodelang.cell_identity import verify_authority_relationship
from nodelang.cell_state_machine import read_evidence
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    edit_universal_interface_value,
    instantiate_universal_definition,
    project_universal_canvas,
    transition_universal_operational_state,
)
from nodelang.universal_cell import InvalidCell


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class _FakeHardwareKey:
    def __init__(self):
        public = {
            "crv": "P-256",
            "kty": "EC",
            "x": _b64(b"d" * 32),
            "y": _b64(b"e" * 32),
        }
        document = json.dumps(public, sort_keys=True, separators=(",", ":"))
        thumbprint = _b64(hashlib.sha256(document.encode("ascii")).digest())
        self.reference = DeviceProofKeyReference(
            "ArchHub.Test.FakeHardwareKey",
            PLATFORM_PROVIDER,
            "ES256",
            thumbprint,
            MappingProxyType(public),
            True,
        )
        self.closed = False

    def close(self):
        self.closed = True


def _configured_request(store, registry):
    canvas = project_universal_canvas(store, registry)
    definition = next(
        item["id"] for item in canvas["catalog"]
        if item["name"] == "Permission Request"
    )
    root, _ = instantiate_universal_definition(
        store, registry, definition, x=420, y=180
    )
    assembly = project_universal_canvas(store, registry)["selected_assembly"]
    interfaces = {item["name"]: item for item in assembly["interfaces"]}
    values = {
        "requester": registry.authorization.subject_root,
        "action": "device-key.enroll",
        "object": "device:this-machine",
        "parameters": '{"algorithm":"ES256","provider":"platform"}',
        "reason": "Enroll this desktop for sender-constrained cloud sessions",
        "expires-at": "2100-01-01T00:00:00Z",
    }
    for name, value in values.items():
        edit_universal_interface_value(
            store, registry, root, interfaces[name]["id"], value
        )
    return root


def _approve(store, registry, root):
    assembly = project_universal_canvas(store, registry)["selected_assembly"]
    approve = next(
        item for item in assembly["operational"]["admitted_transitions"]
        if item["event_label"] == "approve"
    )
    transition_universal_operational_state(
        store,
        registry,
        root,
        approve["event"],
        assembly["operational"]["current_state"],
    )


def test_device_effect_is_impossible_before_approval():
    store, registry = build_universal_application(resolve_map_path())
    root = _configured_request(store, registry)
    called = []

    with pytest.raises(InvalidCell, match="admitted execute"):
        execute_device_enrollment(
            store,
            registry,
            root,
            actor_root=registry.authorization.subject_root,
            consent_broker=UserConsentBroker(),
            key_factory=lambda: called.append(True),
        )
    assert called == []
    assert project_universal_canvas(store, registry)[
        "selected_assembly"
    ]["operational"]["current_state_label"] == "PENDING"


def test_approved_request_executes_allowlisted_hardware_custody_with_receipts():
    store, registry = build_universal_application(resolve_map_path())
    root = _configured_request(store, registry)
    _approve(store, registry, root)
    approved = project_universal_canvas(store, registry)["selected_assembly"]
    execute = next(
        item for item in approved["operational"]["admitted_transitions"]
        if item["event_label"] == "execute"
    )
    assert execute["adapter_execute"] is True
    key = _FakeHardwareKey()

    result = execute_device_enrollment(
        store,
        registry,
        root,
        actor_root=registry.authorization.subject_root,
        consent_broker=UserConsentBroker(),
        key_factory=lambda: key,
    )

    assert result.outcome == "succeeded"
    assert key.closed is True
    settled = project_universal_canvas(store, registry)["selected_assembly"]
    assert settled["operational"]["current_state_label"] == "SUCCEEDED"
    assert [
        item["event_label"] for item in settled["operational"]["history"]
    ][-3:] == ["approve", "execute", "succeed"]
    permission = read_permission(
        store.snapshot(), registry.adapter_protocol,
        result.adapter_permission_root,
    )
    assert permission.lifecycle_root == registry.adapter_protocol.states["granted"]
    custody = read_device_custody(
        store.snapshot(), registry.device_custody_protocol, result.custody_root
    )
    assert custody.device_root == result.device_root
    assert custody.state_root == registry.device_custody_protocol.states["active"]
    relationship = verify_authority_relationship(
        store.snapshot(),
        registry.authorization.identity_protocol,
        registry.authorization.relationship_broker,
        result.relationship_root,
    )
    assert relationship.source_root == result.device_root
    assert relationship.target_root == registry.authorization.subject_root
    admission = read_evidence(
        store.snapshot(), registry.standard_library.state_machine_protocol,
        result.admission_evidence_root,
    )
    receipt = read_evidence(
        store.snapshot(), registry.standard_library.state_machine_protocol,
        result.receipt_evidence_root,
    )
    assert admission.issuer_root == registry.device_custody_adapter_root
    assert json.loads(receipt.payload)["status"] == "succeeded"
    graph_atoms = b"\n".join(
        cell.atom for cell in store.snapshot().cells.values()
    )
    assert key.reference.key_name.encode("utf-8") not in graph_atoms


def test_external_failure_is_receipted_and_retry_requires_new_approval():
    store, registry = build_universal_application(resolve_map_path())
    root = _configured_request(store, registry)
    _approve(store, registry, root)

    result = execute_device_enrollment(
        store,
        registry,
        root,
        actor_root=registry.authorization.subject_root,
        consent_broker=UserConsentBroker(),
        key_factory=lambda: (_ for _ in ()).throw(RuntimeError("TPM unavailable")),
    )

    assert result.outcome == "failed"
    assert result.device_root is None
    failed = project_universal_canvas(store, registry)["selected_assembly"]
    assert failed["operational"]["current_state_label"] == "FAILED"
    approve = next(
        item for item in failed["operational"]["admitted_transitions"]
        if item["event_label"] == "approve"
    )
    assert approve["user_decision"] is True
    _approve(store, registry, root)
    retried = execute_device_enrollment(
        store,
        registry,
        root,
        actor_root=registry.authorization.subject_root,
        consent_broker=UserConsentBroker(),
        key_factory=_FakeHardwareKey,
    )
    assert retried.outcome == "succeeded"
    assert retried.adapter_permission_root != result.adapter_permission_root
