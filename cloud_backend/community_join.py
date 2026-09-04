"""Verify a community join-code on the cloud, without importing the brain.

The brain issues join-codes as ``<base64url(payload)>.<base64url(sig)>`` signed
by the community owner's key (ed25519, or an HMAC key when the issuing device
had no ed25519). The payload carries ``owner_pub``; verifying against it proves
the code came from that community's owner. Membership recorded from a verified
code is the ONLY evidence the cloud accepts for reading or writing a community
replica -- a key named on the wire is a claim, not a membership.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

try:  # the cloud ships cryptography; the fallback mirrors the brain's HMAC form
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    _HAS_ED25519 = True
except Exception:  # pragma: no cover - environment without cryptography
    _HAS_ED25519 = False

REQUIRED = ("community_id", "name", "owner_pub", "role", "transport",
            "issued_by", "issued_at", "expires_at", "nonce")


def _payload_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps({k: data[k] for k in REQUIRED}, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _verify(pub_b64: str, payload: bytes, sig_b64: str) -> bool:
    try:
        sig = base64.urlsafe_b64decode(sig_b64.encode())
    except Exception:
        return False
    if _HAS_ED25519:
        try:
            pub = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(pub_b64.encode()))
            pub.verify(sig, payload)
            return True
        except Exception:
            pass  # a 32-byte HMAC key is not an ed25519 point; try the HMAC form
    try:
        key = base64.urlsafe_b64decode(pub_b64.encode())
        expected = hmac.new(key, payload, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def verify_join_code(envelope: str, *, now: float | None = None) -> tuple[dict[str, Any] | None, str]:
    """Return (payload, "ok") for a genuine, unexpired code; else (None, reason)."""
    env = (envelope or "").strip()
    if "code=" in env:
        env = env.split("code=", 1)[1].strip()
    if "." not in env:
        return None, "malformed join-code (no signature separator)"
    payload_b64, sig = env.split(".", 1)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode("utf-8"))
    except Exception:
        return None, "malformed join-code (payload)"
    if not isinstance(data, dict) or any(k not in data for k in REQUIRED):
        return None, "malformed join-code (fields)"
    if float(data["expires_at"]) < (now if now is not None else time.time()):
        return None, "expired"
    if not _verify(str(data["owner_pub"]), _payload_bytes(data), sig):
        return None, "signature mismatch"
    return data, "ok"


__all__ = ["verify_join_code", "REQUIRED"]
