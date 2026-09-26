"""A community owner's join-code signer, for the cloud's join courts.

The same ed25519 raw-key form the retired personal Brain's firm module used
(urlsafe base64 of raw private and public keys; urlsafe base64 signature), so
the cloud verifier is exercised exactly as before without importing it.
"""
import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)


def _generate_keypair():
    priv = Ed25519PrivateKey.generate()
    return (
        base64.urlsafe_b64encode(priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode(),
        base64.urlsafe_b64encode(priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
    )


def _sign(priv_b64, payload):
    priv = Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(priv_b64.encode()))
    return base64.urlsafe_b64encode(priv.sign(payload)).decode()
