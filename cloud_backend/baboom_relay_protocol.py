"""Wire-stable, dependency-free BABOOM relay protocol primitives.

This module is intentionally safe to import from the desktop companion.  It
contains no database, HTTP, or credential code; it only defines bytes that a
device and the cloud must agree on when proving enrollment.
"""
from __future__ import annotations

import base64
import json
from typing import Mapping


ENROLLMENT_CONTEXT = b"ArchHub/BABOOM/device-enrollment/v1\x00"


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(value)).rstrip(b"=").decode("ascii")


def canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def enrollment_challenge_payload(
    *,
    user_id: str,
    challenge_id: str,
    challenge: str,
    device_id: str,
    thumbprint: str,
    recipient_thumbprint: str = "",
    universal_device_thumbprint: str = "",
) -> bytes:
    """Exact bytes the relay and Universal Device Custody keys sign."""
    return ENROLLMENT_CONTEXT + canonical_json({
        "challenge": challenge,
        "challenge_id": challenge_id,
        "device_id": device_id,
        "recipient_thumbprint": recipient_thumbprint,
        "thumbprint": thumbprint,
        "universal_device_thumbprint": universal_device_thumbprint,
        "user_id": user_id,
    })


__all__ = ["b64url", "canonical_json", "enrollment_challenge_payload"]
