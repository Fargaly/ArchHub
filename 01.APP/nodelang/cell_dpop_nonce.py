"""Stateless, token-bound RFC 9449 resource-server nonce capability.

The nonce is an interaction-boundary artifact, not authority.  Its policy is
owned by the server runtime; its signing key remains in a non-exporting key
provider.  Any cloud instance sharing that provider can validate the nonce,
which avoids a process-local nonce table while still binding it to one access
token, audience, and short time window.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from .cell_secret_keys import SigningKeyProvider


class DpopNonceDenied(PermissionError):
    pass


_PREFIX = "AHN1"
_CONTEXT = b"ArchHub/DPoP-resource-server-nonce/v1\x00"
_MAX_NONCE_LENGTH = 4096
_MAX_PROOF_LENGTH = 64 * 1024


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str, *, maximum: int) -> bytes:
    if not value or len(value) > maximum * 2:
        raise DpopNonceDenied("DPoP nonce component is missing or too large")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError) as exc:
        raise DpopNonceDenied("DPoP nonce component is not base64url") from exc
    if len(decoded) > maximum:
        raise DpopNonceDenied("DPoP nonce component is too large")
    return decoded


def _token_digest(access_token: str) -> str:
    if not access_token or len(access_token) > 512:
        raise DpopNonceDenied("DPoP access token is missing or too large")
    try:
        encoded = access_token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise DpopNonceDenied("DPoP access token must be ASCII") from exc
    return hashlib.sha256(encoded).hexdigest()


class ResourceServerNonceBroker:
    """Mint and validate short-lived self-authenticating DPoP nonces."""

    def __init__(
        self,
        *,
        key_provider: SigningKeyProvider,
        key_id: str,
        audience: str,
        lifetime_seconds: int = 60,
        future_skew_seconds: int = 5,
    ) -> None:
        if not audience or len(audience.encode("utf-8")) > 512:
            raise ValueError("DPoP nonce audience is invalid")
        if lifetime_seconds < 10 or lifetime_seconds > 300:
            raise ValueError("DPoP nonce lifetime must be 10..300 seconds")
        if future_skew_seconds < 0 or future_skew_seconds > 30:
            raise ValueError("DPoP nonce future skew is invalid")
        self._key_provider = key_provider
        self._key_id = key_id
        self._audience = audience
        self._lifetime_seconds = int(lifetime_seconds)
        self._future_skew_seconds = int(future_skew_seconds)

    def mint(self, access_token: str, *, now: float | None = None) -> str:
        current = time.time() if now is None else float(now)
        reference = self._key_provider.current_reference(self._key_id)
        payload = {
            "ath": _token_digest(access_token),
            "aud": self._audience,
            "exp": int(current) + self._lifetime_seconds,
            "iat": int(current),
            "kid": reference.key_id,
            "kv": reference.version,
            "rnd": secrets.token_urlsafe(18),
            "v": 1,
        }
        encoded = _b64encode(json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8"))
        signing_input = _CONTEXT + encoded.encode("ascii")
        signature = self._key_provider.sign(
            reference.key_id, reference.version, signing_input
        )
        nonce = "%s.%s.%s" % (_PREFIX, encoded, signature)
        if len(nonce) > _MAX_NONCE_LENGTH:
            raise RuntimeError("generated DPoP nonce exceeded its protocol bound")
        return nonce

    def verify(
        self,
        nonce: str,
        access_token: str,
        *,
        now: float | None = None,
    ) -> str:
        current = time.time() if now is None else float(now)
        if not isinstance(nonce, str) or len(nonce) > _MAX_NONCE_LENGTH:
            raise DpopNonceDenied("DPoP server nonce is missing or too large")
        parts = nonce.split(".")
        if len(parts) != 3 or parts[0] != _PREFIX:
            raise DpopNonceDenied("DPoP server nonce format is invalid")
        encoded, signature = parts[1], parts[2]
        try:
            payload = json.loads(_b64decode(encoded, maximum=2048).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DpopNonceDenied("DPoP server nonce payload is invalid") from exc
        required = {"ath", "aud", "exp", "iat", "kid", "kv", "rnd", "v"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise DpopNonceDenied("DPoP server nonce fields are invalid")
        if payload["v"] != 1 or payload["kid"] != self._key_id:
            raise DpopNonceDenied("DPoP server nonce authority is invalid")
        if (
            isinstance(payload["kv"], bool)
            or not isinstance(payload["kv"], int)
            or payload["kv"] < 1
        ):
            raise DpopNonceDenied("DPoP server nonce key version is invalid")
        if not isinstance(signature, str) or len(signature) > 1024:
            raise DpopNonceDenied("DPoP server nonce signature is invalid")
        if not self._key_provider.verify(
            self._key_id,
            payload["kv"],
            _CONTEXT + encoded.encode("ascii"),
            signature,
        ):
            raise DpopNonceDenied("DPoP server nonce signature is invalid")
        if not isinstance(payload["aud"], str) or not hmac.compare_digest(
            payload["aud"], self._audience
        ):
            raise DpopNonceDenied("DPoP server nonce audience mismatched")
        expected_digest = _token_digest(access_token)
        if not isinstance(payload["ath"], str) or not hmac.compare_digest(
            payload["ath"], expected_digest
        ):
            raise DpopNonceDenied("DPoP server nonce token binding mismatched")
        if (
            isinstance(payload["iat"], bool)
            or isinstance(payload["exp"], bool)
            or not isinstance(payload["iat"], int)
            or not isinstance(payload["exp"], int)
            or payload["exp"] - payload["iat"] != self._lifetime_seconds
            or current < payload["iat"] - self._future_skew_seconds
            or current >= payload["exp"]
        ):
            raise DpopNonceDenied("DPoP server nonce is outside its time window")
        if not isinstance(payload["rnd"], str) or not (20 <= len(payload["rnd"]) <= 64):
            raise DpopNonceDenied("DPoP server nonce entropy field is invalid")
        return nonce


def extract_unverified_proof_nonce(proof: bytes) -> str:
    """Bounded JWT parsing used only to locate the nonce before verification.

    The returned claim has no authority.  It is first validated by
    ``ResourceServerNonceBroker`` and then compared inside the fully verified
    DPoP JWS by ``JoseRfc9449ProofVerifier``.
    """
    if not isinstance(proof, bytes) or not proof or len(proof) > _MAX_PROOF_LENGTH:
        raise DpopNonceDenied("DPoP proof is missing or too large")
    try:
        compact = proof.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DpopNonceDenied("DPoP proof is not compact ASCII JWS") from exc
    parts = compact.split(".")
    if len(parts) != 3:
        raise DpopNonceDenied("DPoP proof compact format is invalid")
    try:
        claims = json.loads(_b64decode(parts[1], maximum=16 * 1024).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DpopNonceDenied("DPoP proof claims are invalid") from exc
    nonce = claims.get("nonce") if isinstance(claims, dict) else None
    if not isinstance(nonce, str) or not nonce or len(nonce) > _MAX_NONCE_LENGTH:
        raise DpopNonceDenied("DPoP proof has no usable server nonce")
    return nonce


__all__ = [
    "DpopNonceDenied",
    "ResourceServerNonceBroker",
    "extract_unverified_proof_nonce",
]
