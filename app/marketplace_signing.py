"""Marketplace package signing — Ed25519 detached signatures.

Threat model
------------
The marketplace catalog is fetched from a cloud_sync git repo. The git
host (currently GitHub via the user's signed-in remote) signs the
TLS connection but cannot guarantee that any individual catalog *item*
came from the official ArchHub publisher. Without per-item signatures
a compromised PR review process could ship a malicious Skill payload
to every user. With per-item Ed25519 signatures, the install path
verifies that the payload bytes were signed by a key whose public half
ships pinned in this module — so a compromised GitHub Actions step
that lacks the private key cannot push code that any client will run.

Catalog item shape (signed)
---------------------------
```
{
  "id": "official.dimension_walls",
  "name": "...",
  "version": "0.1.0",
  "payload": { ... },                     # the actual Skill/Workflow JSON
  "signature": "<base64 ed25519 sig>",     # signs canonical JSON of payload
  "signed_by": "official"                  # which trusted key signed it
}
```

Trust roots
-----------
TRUSTED_KEYS pins the base64-encoded Ed25519 public keys we accept.
"official" is the ArchHub publishing key (placeholder until v1.0
release; replace before public beta). "community" is reserved for a
future opt-in tier of community-published Skills with looser review.

Public API
----------
    canonical_payload(payload: dict) -> bytes
    sign_payload(payload: dict, private_key_b64: str) -> str
    verify_item(item: dict) -> tuple[bool, str]
    is_signed(item: dict) -> bool
    list_trusted_keys() -> list[str]
"""
from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)


# Pinned trust roots. The "official" key is a placeholder generated for
# v0.39 development — REPLACE with the production publishing key before
# the v1.0 public beta cuts. The "community" slot is reserved.
#
# Generated via:
#   from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
#   from cryptography.hazmat.primitives import serialization
#   import base64
#   sk = Ed25519PrivateKey.generate()
#   pk = sk.public_key()
#   raw = pk.public_bytes_raw()
#   print(base64.b64encode(raw).decode())
#
# The corresponding private key is held offline. It is NOT in the repo.
TRUSTED_KEYS: dict[str, str] = {
    # Dev placeholder — REAL Ed25519 public key (32 bytes b64). The
    # matching private key is held offline by the maintainer and is
    # NEVER committed. Replace this entry before v1.0 public beta with
    # the production publishing key. Tests inject their own keypair via
    # monkeypatch; they do not need this private half.
    "official": "RC1S6NrWT2Vdvcqn92on+w1oToYvqbm9nbJxXynDxlA=",
}


def list_trusted_keys() -> list[str]:
    """Return the names of trusted publishers (catalog items signed by
    one of these are eligible for install)."""
    return sorted(TRUSTED_KEYS.keys())


def canonical_payload(payload: dict[str, Any]) -> bytes:
    """Stable JSON encoding so signature verification is deterministic.

    Sorted keys, no whitespace. The signer must use the SAME encoding
    or signatures won't match. We deliberately exclude `signature` and
    `signed_by` from the canonicalization (they describe the signature
    over the rest, not the rest itself)."""
    cleaned = {k: v for k, v in payload.items()
               if k not in ("signature", "signed_by")}
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any], private_key_b64: str) -> str:
    """Produce an Ed25519 signature over canonical_payload(payload).

    Returns the base64-encoded signature suitable to drop into the
    catalog item's `signature` field. Used by the publishing tool, not
    by clients — exposed so the test suite can sign synthetic items."""
    raw = base64.b64decode(private_key_b64)
    sk = Ed25519PrivateKey.from_private_bytes(raw)
    sig = sk.sign(canonical_payload(payload))
    return base64.b64encode(sig).decode("ascii")


def is_signed(item: dict[str, Any]) -> bool:
    """True iff the item has both a signature and a known signer name.
    Used by the marketplace UI to show a 'signed' chip vs an unsigned
    'community / unverified' warning."""
    return bool(item.get("signature")) and item.get("signed_by") in TRUSTED_KEYS


def verify_item(item: dict[str, Any]) -> tuple[bool, str]:
    """Verify the signature on a catalog item.

    Returns (ok, reason). The reason is a short human-readable string
    suitable for surfacing in toast notifications.

    The signature is computed over the `payload` sub-dict only — the
    enclosing catalog metadata (id, name, runs, etc.) is unsigned by
    design, since those fields can legitimately change in the catalog
    without re-signing the underlying Skill/Workflow code.
    """
    sig_b64 = item.get("signature")
    signer = item.get("signed_by")
    payload = item.get("payload")
    if not sig_b64:
        return False, "Item is unsigned."
    if signer not in TRUSTED_KEYS:
        return False, f"Unknown signer: {signer!r}."
    if not isinstance(payload, dict):
        return False, "Item payload missing."
    try:
        pubkey_raw = base64.b64decode(TRUSTED_KEYS[signer])
        pk = Ed25519PublicKey.from_public_bytes(pubkey_raw)
    except Exception:
        # Pinned key is malformed — refuse rather than fall back.
        return False, f"Trusted key for {signer!r} is malformed."
    try:
        sig = base64.b64decode(sig_b64)
    except Exception:
        return False, "Signature is not valid base64."
    try:
        pk.verify(sig, canonical_payload(payload))
    except InvalidSignature:
        return False, "Signature does not match payload."
    except Exception as ex:
        return False, f"Verification error: {type(ex).__name__}"
    return True, f"Signed by {signer}."
