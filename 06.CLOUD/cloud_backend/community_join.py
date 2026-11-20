"""Verify a community join-code on the cloud, without importing the brain.

A join-code is ``<base64url(payload)>.<base64url(sig)>``: an Ed25519 signature by
the community owner over the canonical payload. The owner key it is checked
against is the one ENROLLED on the cloud for that community (db.community_owners),
looked up server-side. The ``owner_pub`` the code carries is a claim: it must equal
the enrolled key, and it never verifies itself. There is no symmetric (HMAC) form:
its key would travel inside the code, so anyone holding the code could sign one.
Membership recorded from a code verified this way is the ONLY evidence the cloud
accepts for reading or writing a community replica.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REQUIRED = ("community_id", "name", "owner_pub", "role", "transport",
            "issued_by", "issued_at", "expires_at", "nonce")


def _payload_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps({k: data[k] for k in REQUIRED}, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def ed25519_key(pub_b64: str) -> Ed25519PublicKey | None:
    """The owner's public key in the join-code's raw urlsafe-base64 form, or None."""
    try:
        return Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(str(pub_b64).encode()))
    except Exception:
        return None


def verify_signature(pub_b64: str, payload: bytes, sig_b64: str) -> bool:
    """Ed25519 only, as marketplace.py: a key that is not an Ed25519 point verifies nothing."""
    key = ed25519_key(pub_b64)
    if key is None:
        return False
    try:
        key.verify(base64.urlsafe_b64decode(str(sig_b64).encode()), payload)
        return True
    except Exception:
        return False


def read_join_code(envelope: str) -> tuple[dict[str, Any] | None, str, str]:
    """Split a code into (payload, signature, reason); nothing in it is trusted yet."""
    env = (envelope or "").strip()
    if "code=" in env:
        env = env.split("code=", 1)[1].strip()
    if "." not in env:
        return None, "", "malformed join-code (no signature separator)"
    payload_b64, sig = env.split(".", 1)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode("utf-8"))
    except Exception:
        return None, "", "malformed join-code (payload)"
    if not isinstance(data, dict) or any(k not in data for k in REQUIRED):
        return None, "", "malformed join-code (fields)"
    return data, sig, "ok"


def verify_join_code(envelope: str, *, owner_pub: str | None, now: float | None = None) -> tuple[dict[str, Any] | None, str]:
    """(payload, "ok") only for an unexpired code signed by ``owner_pub``, the community's ENROLLED owner key."""
    data, sig, reason = read_join_code(envelope)
    if data is None:
        return None, reason
    if not owner_pub:
        return None, "community has no enrolled owner"
    if str(data["owner_pub"]) != owner_pub:
        return None, "join-code names a different owner than the community's enrolled owner"
    try:
        expired = float(data["expires_at"]) < (now if now is not None else time.time())
    except (TypeError, ValueError):
        return None, "malformed join-code (expiry)"
    if expired:
        return None, "expired"
    if not verify_signature(owner_pub, _payload_bytes(data), sig):
        return None, "signature mismatch"
    return data, "ok"


def enrol_statement(community_id: str, user_id: str) -> bytes:
    """What an owner signs to enrol a community: proves possession of the key for this account and id."""
    return json.dumps({"enrol_community": community_id, "user_id": user_id}, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


__all__ = ["verify_join_code", "read_join_code", "verify_signature", "ed25519_key", "enrol_statement", "REQUIRED"]
