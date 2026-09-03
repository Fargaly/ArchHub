"""Attach the BABOOM native companion to a live universal runtime.

Everything here is the production path the courts already prove: a
machine-transport descriptor, one persistent device-proof key for THIS
machine, graph-registered device custody, and the signed agent-session
challenge. No stub answers, no bypass: a companion that cannot prove its
device does not connect.
"""
from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64encode
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from .application_machine_transport import (
    UniversalRuntimeClient,
    runtime_device_proof_payload,
)
from .baboom_native_runtime import create_baboom_native_runtime
from .cell_cloud_sessions import device_root_for_thumbprint
from .cell_device_custody import register_device_custody
from .cell_device_keys import DeviceProofKeyReference, PLATFORM_PROVIDER
from .universal_application import (
    bind_universal_runtime_agent_body_device_custody,
)
from .universal_cell import NULL_CELL_ID, Cell


def _b64url(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _machine_device_key(state_dir: Path):
    """This machine's persistent BABOOM device key, created once."""
    key_path = state_dir / "baboom-device-key.pem"
    if key_path.is_file():
        key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=None
        )
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    numbers = key.public_key().public_numbers()
    public_jwk = {
        "crv": "P-256",
        "kty": "EC",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }
    document = json.dumps(
        public_jwk, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    thumbprint = _b64url(hashlib.sha256(document).digest())
    reference = DeviceProofKeyReference(
        "founder-machine-baboom",
        PLATFORM_PROVIDER,
        "ES256",
        thumbprint,
        public_jwk,
        True,
    )
    return key, reference


def _ensure_device_custody(server, reference) -> str:
    """Register this device in the graph once; replays return the root."""
    store = server.universal_store
    device_root = device_root_for_thumbprint(reference.thumbprint)
    if device_root not in store.snapshot().cells:
        store.commit(store.revision, create=(Cell(
            device_root,
            NULL_CELL_ID,
            NULL_CELL_ID,
            (
                "device-proof-key-thumbprint:" + reference.thumbprint
            ).encode("ascii"),
        ),))
    custody_root = "device-custody:sha256:" + reference.thumbprint
    if custody_root not in store.snapshot().cells:
        custody_root, _ = register_device_custody(
            store,
            server.universal_registry.device_custody_protocol,
            reference,
        )
    bind_universal_runtime_agent_body_device_custody(
        store,
        server.universal_registry,
        runtime="baboom",
        custody_root=custody_root,
    )
    return custody_root


def attach_baboom_companion(
    server,
    *,
    state_dir: Path,
    descriptor_path: Path,
    key_provider,
    external_session_id: str = "founder-desktop-baboom",
):
    """Bind the signed BABOOM agent session and build the live companion."""
    key, reference = _machine_device_key(state_dir)
    custody_root = _ensure_device_custody(server, reference)

    def device_credential(challenge):
        payload = runtime_device_proof_payload(
            runtime_id=challenge["runtime_id"],
            runtime=challenge["runtime"],
            external_session_id=external_session_id,
            challenge_id=challenge["challenge_id"],
            nonce=challenge["nonce"],
        )
        der = key.sign(
            hashlib.sha256(payload).digest(),
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
        left, right = utils.decode_dss_signature(der)
        return {
            "challenge_id": challenge["challenge_id"],
            "custody_root": custody_root,
            "signature": _b64url(
                left.to_bytes(32, "big") + right.to_bytes(32, "big")
            ),
        }

    client = UniversalRuntimeClient(descriptor_path, key_provider)
    host, window = create_baboom_native_runtime(
        client,
        external_session_id=external_session_id,
        device_credential_provider=device_credential,
    )
    host.connect()
    host.start()
    return host, window


__all__ = ["attach_baboom_companion"]
