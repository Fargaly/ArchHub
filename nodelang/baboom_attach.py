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
    MachineTransportError,
    UniversalRuntimeClient,
    runtime_device_proof_payload,
)
from .baboom_native_runtime import (
    create_baboom_native_host,
    create_baboom_native_projection,
)
from .cell_cloud_sessions import device_root_for_thumbprint
from .cell_device_custody import register_device_custody
from .cell_device_keys import DeviceProofKeyReference, PLATFORM_PROVIDER
from .universal_application import (
    bind_universal_runtime_agent_body_device_custody,
)
from .universal_cell import NULL_CELL_ID, Cell


def _b64url(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _machine_device_key(state_dir: Path, *, create: bool = True):
    """This machine's persistent BABOOM device key, created once."""
    key_path = state_dir / "baboom-device-key.pem"
    if key_path.is_file():
        key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=None
        )
    elif create:
        key = ec.generate_private_key(ec.SECP256R1())
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    else:
        raise MachineTransportError("The existing native device key is unavailable")
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


def _ensure_device_custody(server, reference, *, runtime="baboom", authentication_context=None) -> str:
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
        runtime=runtime,
        custody_root=custody_root,
        authentication_context=authentication_context,
    )
    return custody_root


def device_credential_provider(key, custody_root, external_session_id):
    """Sign challenges for this exact session; never substitute another ID."""
    def sign(challenge):
        payload = runtime_device_proof_payload(
            runtime_id=challenge["runtime_id"], runtime=challenge["runtime"],
            external_session_id=external_session_id,
            challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        der = key.sign(hashlib.sha256(payload).digest(), ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        left, right = utils.decode_dss_signature(der)
        return {"challenge_id":challenge["challenge_id"], "custody_root":custody_root,
            "signature":_b64url(left.to_bytes(32, "big") + right.to_bytes(32, "big"))}
    return sign


def prepare_workshop_execution_client(server, *, state_dir, descriptor_path, key_provider,
        external_session_id, authentication_context, cancellation_event=None, retain_client=None):
    """Explicit native attachment using existing key custody, with no daemon."""
    from .cell_authorization import AuthorizationDenied
    from .universal_application import _require_application_authorization
    if type(external_session_id) is not str or not external_session_id or len(external_session_id) > 128:
        raise MachineTransportError("Workshop session identity is invalid")
    def check_cancelled():
        if cancellation_event is not None and cancellation_event.is_set():
            raise MachineTransportError("Workshop attachment cancelled")
    check_cancelled()
    while not server.mutation_lock.acquire(timeout=.1):
        check_cancelled()
    try:
        check_cancelled()
        authority = server.universal_registry.authorization
        if authentication_context is None or authority.broker.resolve(authentication_context).subject_root != authority.subject_root:
            raise AuthorizationDenied("Native Workshop attachment requires the authenticated founder")
        _require_application_authorization(server.universal_store.snapshot(), server.universal_registry,
            "execute", server.universal_registry.workshop_root, authentication_context=authentication_context)
        key, reference = _machine_device_key(Path(state_dir), create=False)
        custody = _ensure_device_custody(server, reference, runtime="baboom-execution",
            authentication_context=authentication_context)
    finally:
        server.mutation_lock.release()
    check_cancelled()
    client = UniversalRuntimeClient(descriptor_path, key_provider, cancellation_event=cancellation_event)
    # The native owner must retain this exact client before any enrollment can
    # commit. Losing the response must not trigger a replacement enrollment.
    if retain_client is not None:
        retain_client(client)
    client.bind_agent_session(runtime="baboom-execution", external_session_id=external_session_id,
        device_credential_provider=device_credential_provider(key, custody, external_session_id))
    return client


def prepare_baboom_host(
    server,
    *,
    state_dir: Path,
    descriptor_path: Path,
    key_provider,
    external_session_id: str = "founder-desktop-baboom",
    cancellation_event=None,
):
    """Prepare one signed client, with no connection, heartbeat, or Qt window."""
    # Preparation may run beside HTTP/machine requests during a busy boot.
    # Use the same lock as those requests for key/custody admission.
    def check_cancelled():
        if cancellation_event is not None and cancellation_event.is_set():
            raise MachineTransportError("BABOOM attachment cancelled")

    check_cancelled()
    while not server.mutation_lock.acquire(timeout=0.1):
        check_cancelled()
    try:
        check_cancelled()
        key, reference = _machine_device_key(state_dir)
        custody_root = _ensure_device_custody(server, reference)
    finally:
        server.mutation_lock.release()

    check_cancelled()
    client = UniversalRuntimeClient(
        descriptor_path, key_provider, cancellation_event=cancellation_event
    )
    return create_baboom_native_host(
        client,
        external_session_id=external_session_id,
        device_credential_provider=device_credential_provider(key, custody_root, external_session_id),
    )


def attach_baboom_companion(
    server,
    *,
    state_dir: Path,
    descriptor_path: Path,
    key_provider,
    external_session_id: str = "founder-desktop-baboom",
):
    """Compatibility entry point for callers already on the GUI thread."""
    host = prepare_baboom_host(
        server, state_dir=state_dir, descriptor_path=descriptor_path,
        key_provider=key_provider, external_session_id=external_session_id,
    )
    window = None
    try:
        host.connect()
        window = create_baboom_native_projection(
            host, position_path=state_dir / "baboom-position.json"
        )
        host.start()
        return host, window
    except Exception:
        host.stop(timeout_seconds=0.01)
        if window is not None:
            window.close()
        raise


__all__ = ["attach_baboom_companion", "prepare_baboom_host"]
