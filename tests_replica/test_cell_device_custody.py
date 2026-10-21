"""Courts for graph-visible, non-secret device-key custody authority."""
import base64
import hashlib
import json
from types import MappingProxyType

import pytest

from nodelang.cell_cloud_sessions import device_root_for_thumbprint
from nodelang.cell_device_custody import (
    bootstrap_device_custody_protocol,
    project_device_custody_protocol,
    read_device_custody,
    register_device_custody,
    revoke_device_custody,
)
from nodelang.cell_device_keys import (
    DeviceProofKeyReference,
    PLATFORM_PROVIDER,
    SOFTWARE_PROVIDER,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _reference(*, provider=PLATFORM_PROVIDER, hardware=True):
    public = {
        "crv": "P-256",
        "kty": "EC",
        "x": _b64(b"x" * 32),
        "y": _b64(b"y" * 32),
    }
    document = json.dumps(public, sort_keys=True, separators=(",", ":"))
    thumbprint = _b64(hashlib.sha256(document.encode("ascii")).digest())
    return DeviceProofKeyReference(
        "ArchHub.Device.DPoP.v1",
        provider,
        "ES256",
        thumbprint,
        MappingProxyType(public),
        hardware,
    )


def _provision_device(store, reference):
    root = device_root_for_thumbprint(reference.thumbprint)
    store.commit(store.revision, create=(Cell(
        root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        ("device-proof-key-thumbprint:" + reference.thumbprint).encode(
            "ascii"
        ),
    ),))
    return root


def test_device_custody_is_one_atomic_inspectable_relation_without_key_name():
    store = CellStore()
    protocol = bootstrap_device_custody_protocol(store)
    reference = _reference()
    device_root = _provision_device(store, reference)
    before = store.revision

    custody_root, revision = register_device_custody(
        store, protocol, reference, enrolled_at=1000.0
    )

    assert revision == before + 1 == store.revision
    assert project_device_custody_protocol(store.snapshot()) == protocol
    custody = read_device_custody(
        store.snapshot(), protocol, custody_root
    )
    assert custody.device_root == device_root
    assert custody.state_root == protocol.states["active"]
    assert store.read(custody.provider_root).atom.decode() == PLATFORM_PROVIDER
    assert store.read(custody.algorithm_root).atom == b"ES256"
    assert store.read(custody.hardware_backed_root).atom == b"true"
    assert store.read(custody.enrolled_at_root).atom == b"1000.000000"
    graph_bytes = b"\n".join(
        cell.atom for cell in store.snapshot().cells.values()
    )
    assert reference.key_name.encode("utf-8") not in graph_bytes
    assert hashlib.sha256(reference.key_name.encode()).hexdigest().encode() \
        in graph_bytes
    assert set(json.loads(store.read(custody.public_jwk_root).atom)) \
        == {"crv", "kty", "x", "y"}


def test_device_custody_revocation_is_atomic_and_visible():
    store = CellStore()
    protocol = bootstrap_device_custody_protocol(store)
    reference = _reference()
    _provision_device(store, reference)
    custody_root, _ = register_device_custody(store, protocol, reference)
    before = store.revision

    revision = revoke_device_custody(
        store, protocol, custody_root, reason="Device was retired"
    )

    assert revision == before + 1 == store.revision
    custody = read_device_custody(
        store.snapshot(), protocol, custody_root
    )
    assert custody.state_root == protocol.states["revoked"]
    assert store.read(custody.revocation_reason_roots[0]).atom \
        == b"Device was retired"
    assert revoke_device_custody(
        store, protocol, custody_root, reason="duplicate"
    ) == revision


def test_device_custody_denies_unprovisioned_downgraded_or_duplicate_key():
    store = CellStore()
    protocol = bootstrap_device_custody_protocol(store)
    reference = _reference()
    with pytest.raises(InvalidCell, match="not provisioned"):
        register_device_custody(store, protocol, reference)
    _provision_device(store, reference)
    with pytest.raises(InvalidCell, match="hardware-backed"):
        register_device_custody(
            store, protocol, _reference(hardware=False)
        )
    software = _reference(provider=SOFTWARE_PROVIDER, hardware=False)
    with pytest.raises(InvalidCell, match="not admitted"):
        register_device_custody(store, protocol, software)
    custody_root, _ = register_device_custody(store, protocol, reference)
    assert custody_root.startswith("device-custody:sha256:")
    with pytest.raises(InvalidCell, match="already exists"):
        register_device_custody(store, protocol, reference)


def test_software_custody_can_be_explicitly_admitted_for_nonproduction_use():
    store = CellStore()
    protocol = bootstrap_device_custody_protocol(store)
    reference = _reference(provider=SOFTWARE_PROVIDER, hardware=False)
    _provision_device(store, reference)
    custody_root, _ = register_device_custody(
        store, protocol, reference, allow_software=True
    )
    custody = read_device_custody(store.snapshot(), protocol, custody_root)
    assert store.read(custody.hardware_backed_root).atom == b"false"
