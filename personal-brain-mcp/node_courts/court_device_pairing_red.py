"""RED courts for new-device pairing authority.

Encodes REMOTE-DEVICE-SESSION-AUTHORITY.md sec 3.3 (new-device admission
sequence) and sec 7.2 courts 1-5. Court 6 (first-device recovery) is HELD OUT:
it needs a separately released root of trust, not the normal pairing path.

These are RED ON PURPOSE. `nodelang.cell_device_pairing` does not exist yet.
The missing mechanism is exactly the gap between "download ArchHub on another
device" and "that device may safely join the existing account":

    pairing request -> trusted-session approval -> one-use grant consumption
    -> returning-device authentication

The returning-device half and this-machine enrollment are already built and
courted. This file states the shape of the missing half BEFORE implementation,
per the red-courts-first discipline.

Machine-light by construction: a bare CellStore() and one protocol bootstrap.
No build_universal_application, no browser, no daemon, no network, no pipe.
"""
import base64
import hashlib
import json
import os
import sys
from types import MappingProxyType

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
# node-language/ inside this repository first (PR #306); the sibling
# 13.NODE-LANGUAGE worktree is the founder-workstation fallback.
NL = next((c for c in (os.path.join(_HERE, "..", "..", "node-language"),
                       os.path.join(_HERE, "..", "..", "..", "13.NODE-LANGUAGE"))
           if os.path.isdir(os.path.join(c, "nodelang"))),
          os.path.join(_HERE, "..", "..", "..", "13.NODE-LANGUAGE"))
sys.path.insert(0, os.path.abspath(NL))

from nodelang.cell_cloud_sessions import device_root_for_thumbprint
from nodelang.cell_device_custody import bootstrap_device_custody_protocol
from nodelang.cell_device_keys import (
    DeviceProofKeyReference,
    PLATFORM_PROVIDER,
    SOFTWARE_PROVIDER,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore

class _MissingPairingAuthority:
    """Stands in for the unbuilt module so each court FAILS red, not skips.

    A skip would be a vacuous green. Importing at module scope would be a
    collection error that breaks every other court in this tree. So the
    import is deferred per-test: collection stays clean, and each court
    fails naming the exact absent mechanism.
    """

    def __getattr__(self, name):
        raise AssertionError(
            "RED: nodelang.cell_device_pairing.%s does not exist. "
            "New-device pairing authority is unbuilt — the gap between "
            "'download ArchHub on another device' and 'that device may join "
            "the account'. See REMOTE-DEVICE-SESSION-AUTHORITY.md sec 3.3 "
            "(sequence) and sec 7.2 (courts 1-5)." % name
        )


try:  # pragma: no cover - flips to the real module on implementation
    from nodelang import cell_device_pairing as pairing  # type: ignore
except ImportError:
    pairing = _MissingPairingAuthority()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _reference(*, provider=PLATFORM_PROVIDER, hardware=True, seed=b"x"):
    """A PRESENTED public key — what a remote device can actually send.

    Never a private key: the remote device holds a non-exporting key and
    presents only the public JWK plus its thumbprint.
    """
    public = {
        "crv": "P-256",
        "kty": "EC",
        "x": _b64(seed * 32),
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
        ("device-proof-key-thumbprint:" + reference.thumbprint).encode("ascii"),
    ),))
    return root


def _bootstrap(store):
    custody = bootstrap_device_custody_protocol(store)
    return custody, pairing.bootstrap_device_pairing_protocol(store)


# --- sec 7.2 court 2: a pairing names exactly its eight fields -------------
def test_pairing_request_names_subject_tenant_audience_key_expiry_session():
    store = CellStore()
    custody, protocol = _bootstrap(store)
    reference = _reference()
    _provision_device(store, reference)

    request_root, revision = pairing.compose_pairing_request(
        store,
        protocol,
        subject="app:identity:founder",
        tenant="app:tenant:archhub",
        audience="app:audience:archhub-cloud",
        reference=reference,
        expires_at=2000.0,
        authorising_session="app:agent-session:founder",
        action="device-key.pair",
        evidence=("app:evidence:pairing-handle",),
        requested_at=1000.0,
    )

    assert revision == store.revision
    projection = pairing.read_pairing_request(
        store.snapshot(), protocol, request_root
    )
    assert projection.subject_root == "app:identity:founder"
    assert projection.tenant_root == "app:tenant:archhub"
    assert projection.audience_root == "app:audience:archhub-cloud"
    assert projection.key_thumbprint == reference.thumbprint
    assert projection.expires_at == 2000.0
    assert projection.authorising_session_root == "app:agent-session:founder"
    assert projection.action == "device-key.pair"
    assert tuple(projection.evidence_roots) == ("app:evidence:pairing-handle",)
    # the request alone is NOT custody
    assert projection.state_root == protocol.states["requested"]


# --- sec 7.2 court 1: OIDC alone cannot create custody --------------------
def test_presented_key_becomes_custody_only_through_consumed_pairing_grant():
    store = CellStore()
    custody, protocol = _bootstrap(store)
    reference = _reference()
    _provision_device(store, reference)

    request_root, _ = pairing.compose_pairing_request(
        store,
        protocol,
        subject="app:identity:founder",
        tenant="app:tenant:archhub",
        audience="app:audience:archhub-cloud",
        reference=reference,
        expires_at=2000.0,
        authorising_session="app:agent-session:founder",
        action="device-key.pair",
        evidence=("app:evidence:pairing-handle",),
        requested_at=1000.0,
    )

    # an unapproved request can never be consumed into custody
    with pytest.raises(pairing.PairingDenied):
        pairing.consume_pairing_grant(
            store, protocol, custody, request_root, consumed_at=1500.0
        )

    grant_root, _ = pairing.approve_pairing_request(
        store,
        protocol,
        request_root,
        approving_session="app:agent-session:founder",
        approved_at=1100.0,
    )
    custody_root, _ = pairing.consume_pairing_grant(
        store, protocol, custody, request_root, consumed_at=1500.0
    )
    assert custody_root

    # sec 3.3: the pairing authority is ONE-USE
    with pytest.raises(pairing.PairingDenied):
        pairing.consume_pairing_grant(
            store, protocol, custody, request_root, consumed_at=1600.0
        )
    assert pairing.read_pairing_grant(
        store.snapshot(), protocol, grant_root
    ).state_root == protocol.states["consumed"]


# --- sec 7.2 court 3: approval needs a trusted session, not a proposal ----
def test_agent_proposal_is_not_approval():
    store = CellStore()
    custody, protocol = _bootstrap(store)
    reference = _reference()
    _provision_device(store, reference)

    request_root, _ = pairing.compose_pairing_request(
        store,
        protocol,
        subject="app:identity:founder",
        tenant="app:tenant:archhub",
        audience="app:audience:archhub-cloud",
        reference=reference,
        expires_at=2000.0,
        authorising_session="app:agent-session:founder",
        action="device-key.pair",
        evidence=("app:evidence:pairing-handle",),
        requested_at=1000.0,
    )

    with pytest.raises(pairing.PairingDenied):
        pairing.approve_pairing_request(
            store,
            protocol,
            request_root,
            approving_session="app:agent-session:runtime:baboom",
            approved_at=1100.0,
            proposal_only=True,
        )


# --- sec 7.2 court 4: drift / expiry / replay all deny --------------------
@pytest.mark.parametrize("drift", ["subject", "tenant", "audience", "key"])
def test_drift_denies_enrollment(drift):
    store = CellStore()
    custody, protocol = _bootstrap(store)
    reference = _reference()
    _provision_device(store, reference)

    request_root, _ = pairing.compose_pairing_request(
        store,
        protocol,
        subject="app:identity:founder",
        tenant="app:tenant:archhub",
        audience="app:audience:archhub-cloud",
        reference=reference,
        expires_at=2000.0,
        authorising_session="app:agent-session:founder",
        action="device-key.pair",
        evidence=("app:evidence:pairing-handle",),
        requested_at=1000.0,
    )
    pairing.approve_pairing_request(
        store,
        protocol,
        request_root,
        approving_session="app:agent-session:founder",
        approved_at=1100.0,
    )

    drifted = {
        "subject": {"subject": "app:identity:someone-else"},
        "tenant": {"tenant": "app:tenant:other"},
        "audience": {"audience": "app:audience:other"},
        "key": {"reference": _reference(seed=b"z")},
    }[drift]

    with pytest.raises(pairing.PairingDenied):
        pairing.consume_pairing_grant(
            store, protocol, custody, request_root,
            consumed_at=1500.0, **drifted,
        )


def test_expiry_denies_enrollment():
    store = CellStore()
    custody, protocol = _bootstrap(store)
    reference = _reference()
    _provision_device(store, reference)

    request_root, _ = pairing.compose_pairing_request(
        store,
        protocol,
        subject="app:identity:founder",
        tenant="app:tenant:archhub",
        audience="app:audience:archhub-cloud",
        reference=reference,
        expires_at=2000.0,
        authorising_session="app:agent-session:founder",
        action="device-key.pair",
        evidence=("app:evidence:pairing-handle",),
        requested_at=1000.0,
    )
    pairing.approve_pairing_request(
        store,
        protocol,
        request_root,
        approving_session="app:agent-session:founder",
        approved_at=1100.0,
    )

    with pytest.raises(pairing.PairingDenied):
        pairing.consume_pairing_grant(
            store, protocol, custody, request_root, consumed_at=2500.0
        )


# --- sec 7.2 court 5: every stage stays separately inspectable -----------
def test_request_authorization_attempt_custody_history_stay_separate():
    store = CellStore()
    custody, protocol = _bootstrap(store)
    reference = _reference()
    _provision_device(store, reference)

    request_root, _ = pairing.compose_pairing_request(
        store,
        protocol,
        subject="app:identity:founder",
        tenant="app:tenant:archhub",
        audience="app:audience:archhub-cloud",
        reference=reference,
        expires_at=2000.0,
        authorising_session="app:agent-session:founder",
        action="device-key.pair",
        evidence=("app:evidence:pairing-handle",),
        requested_at=1000.0,
    )
    grant_root, _ = pairing.approve_pairing_request(
        store,
        protocol,
        request_root,
        approving_session="app:agent-session:founder",
        approved_at=1100.0,
    )
    custody_root, _ = pairing.consume_pairing_grant(
        store, protocol, custody, request_root, consumed_at=1500.0
    )

    roots = {request_root, grant_root, custody_root}
    assert len(roots) == 3, "stages must not collapse into one relation"
    history = pairing.list_pairing_history(store.snapshot(), protocol, request_root)
    assert [entry.state for entry in history] == [
        "requested", "approved", "consumed"
    ]


# --- sec 7.2 court 6 is deliberately NOT encoded here --------------------
def test_first_device_recovery_is_not_reachable_through_normal_pairing():
    """First-device recovery needs a separately released root of trust.

    Held out on purpose (sec 3.3: "OIDC alone is not an acceptable
    first-device root of trust"). The normal pairing path must refuse it.
    """
    store = CellStore()
    custody, protocol = _bootstrap(store)
    reference = _reference(provider=SOFTWARE_PROVIDER, hardware=False)
    _provision_device(store, reference)

    with pytest.raises(pairing.PairingDenied):
        pairing.compose_pairing_request(
            store,
            protocol,
            subject="app:identity:founder",
            tenant="app:tenant:archhub",
            audience="app:audience:archhub-cloud",
            reference=reference,
            expires_at=2000.0,
            authorising_session=None,  # no existing trusted session = first device
            action="device-key.pair",
            evidence=(),
            requested_at=1000.0,
        )
