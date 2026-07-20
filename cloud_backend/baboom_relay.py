"""Device-bound, metadata-only delivery transport for BABOOM commands.

The Universal Cell journal remains the command authority. This module is only
the cloud adapter that authenticates enrolled devices and durably relays a
redacted command summary, digest, lifecycle, and transport receipt.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

import db
from baboom_relay_protocol import canonical_json as _canonical_json
from baboom_relay_protocol import enrollment_challenge_payload


_DEVICE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OUTCOME = re.compile(r"^[a-z][a-z0-9-]{0,79}$")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+|\bbearer\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_JWK = frozenset({"d", "k", "p", "q", "dp", "dq", "qi", "oth"})
_MAX_PROOF_LENGTH = 16 * 1024
_MAX_SUMMARY_LENGTH = 280
_CHALLENGE_TTL_SECONDS = 120
_NONCE_TTL_SECONDS = 90
_DPOP_MAX_AGE_SECONDS = 60
_DPOP_FUTURE_SKEW_SECONDS = 5
_MAX_COMMAND_LIFETIME_SECONDS = 86_400
_MAX_COMMAND_CLOCK_SKEW_SECONDS = 300
_THUMBPRINT = re.compile(r"^[A-Za-z0-9_-]{43}$")
_BRIEF_VERSION = 1
_MAX_BRIEF_CIPHERTEXT_BYTES = 64 * 1024 + 16


class RelayDenied(PermissionError):
    """A caller cannot use the bounded relay in its current state."""


class RelayAuthenticationDenied(RelayDenied):
    """A bearer token was not bound to an enrolled device proof."""


class RelayConflict(RelayDenied):
    """A durable lifecycle transition was already taken or is unavailable."""


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    user_id: str
    device_id: str
    thumbprint: str


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum * 2:
        raise RelayAuthenticationDenied("relay proof component is invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, UnicodeEncodeError) as exc:
        raise RelayAuthenticationDenied("relay proof component is not base64url") from exc
    if len(decoded) > maximum:
        raise RelayAuthenticationDenied("relay proof component is too large")
    return decoded


def _require_device_id(value: str) -> str:
    device_id = str(value or "")
    if not _DEVICE_ID.fullmatch(device_id):
        raise RelayDenied("BABOOM device identity is invalid")
    return device_id


def _require_digest(value: str, *, label: str) -> str:
    digest = str(value or "")
    if not _DIGEST.fullmatch(digest):
        raise RelayDenied("BABOOM %s must be a SHA-256 digest" % label)
    return digest


def _require_outcome(value: str, *, label: str) -> str:
    outcome = str(value or "")
    if not _OUTCOME.fullmatch(outcome):
        raise RelayDenied("BABOOM %s is invalid" % label)
    return outcome


def _safe_summary(value: str) -> str:
    summary = " ".join(str(value or "").split()).strip()
    if not summary or len(summary) > _MAX_SUMMARY_LENGTH:
        raise RelayDenied("BABOOM command summary is invalid")
    if _SECRET.search(summary):
        raise RelayDenied("BABOOM command summary contains a credential")
    return summary


def _public_key(public_jwk: Mapping[str, object]) -> tuple[dict[str, str], str, ec.EllipticCurvePublicKey]:
    if not isinstance(public_jwk, Mapping) or _PRIVATE_JWK.intersection(public_jwk):
        raise RelayDenied("BABOOM device JWK is invalid")
    if set(public_jwk) != {"kty", "crv", "x", "y"}:
        raise RelayDenied("BABOOM device JWK shape is invalid")
    try:
        normalized = {key: str(public_jwk[key]) for key in ("crv", "kty", "x", "y")}
    except (KeyError, TypeError) as exc:
        raise RelayDenied("BABOOM device JWK is invalid") from exc
    if normalized["kty"] != "EC" or normalized["crv"] != "P-256":
        raise RelayDenied("BABOOM device JWK must be P-256")
    x = _b64url_decode(normalized["x"], maximum=64)
    y = _b64url_decode(normalized["y"], maximum=64)
    if len(x) != 32 or len(y) != 32:
        raise RelayDenied("BABOOM device JWK coordinates are invalid")
    try:
        public = ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
        ).public_key()
    except ValueError as exc:
        raise RelayDenied("BABOOM device JWK point is invalid") from exc
    document = _canonical_json(normalized)
    thumbprint = _b64url(hashlib.sha256(document).digest())
    return normalized, thumbprint, public


def _verify_prehashed_signature(public: ec.EllipticCurvePublicKey, signature: str, payload: bytes) -> None:
    raw = _b64url_decode(signature, maximum=128)
    if len(raw) != 64:
        raise RelayAuthenticationDenied("BABOOM device signature is invalid")
    der = utils.encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    try:
        public.verify(
            der, hashlib.sha256(payload).digest(), ec.ECDSA(utils.Prehashed(hashes.SHA256()))
        )
    except InvalidSignature as exc:
        raise RelayAuthenticationDenied("BABOOM device signature did not verify") from exc


def _target_uri(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise RelayAuthenticationDenied("BABOOM DPoP target URI is invalid") from exc
    host = (parsed.hostname or "").lower()
    local_http = parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise RelayAuthenticationDenied("BABOOM DPoP requires HTTPS")
    if (
        not host or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment
    ):
        raise RelayAuthenticationDenied("BABOOM DPoP target authority is invalid")
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    default_port = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    authority = host if port is None or default_port else "%s:%s" % (host, port)
    path = parsed.path or "/"
    if "/./" in path or "/../" in path or path.endswith(("/.", "/..")):
        raise RelayAuthenticationDenied("BABOOM DPoP target path is invalid")
    return urlunsplit((parsed.scheme, authority, path, "", ""))


def _parse_dpop(proof: str, *, bearer_token: str, device_thumbprint: str, method: str, target_uri: str, expected_nonce: str, now: float) -> str:
    if not isinstance(proof, str) or not proof or len(proof) > _MAX_PROOF_LENGTH:
        raise RelayAuthenticationDenied("BABOOM DPoP proof is invalid")
    parts = proof.split(".")
    if len(parts) != 3:
        raise RelayAuthenticationDenied("BABOOM DPoP proof is malformed")
    try:
        header = json.loads(_b64url_decode(parts[0], maximum=4096).decode("utf-8"))
        claims = json.loads(_b64url_decode(parts[1], maximum=8192).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RelayAuthenticationDenied("BABOOM DPoP proof is not JSON") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise RelayAuthenticationDenied("BABOOM DPoP proof shape is invalid")
    if header.get("typ") != "dpop+jwt" or header.get("alg") != "ES256":
        raise RelayAuthenticationDenied("BABOOM DPoP header is invalid")
    public_jwk = header.get("jwk")
    try:
        normalized, thumbprint, public = _public_key(public_jwk)
    except RelayDenied as exc:
        raise RelayAuthenticationDenied("BABOOM DPoP public key is invalid") from exc
    if not hmac.compare_digest(thumbprint, device_thumbprint):
        raise RelayAuthenticationDenied("BABOOM DPoP key is not device-bound")
    required = {"jti", "htm", "htu", "iat", "ath", "nonce"}
    if not required.issubset(claims):
        raise RelayAuthenticationDenied("BABOOM DPoP proof is incomplete")
    proof_id = claims["jti"]
    if not isinstance(proof_id, str) or not (16 <= len(proof_id) <= 256):
        raise RelayAuthenticationDenied("BABOOM DPoP proof id is invalid")
    if not isinstance(claims["htm"], str) or claims["htm"].upper() != method.upper():
        raise RelayAuthenticationDenied("BABOOM DPoP method mismatched")
    if not isinstance(claims["htu"], str) or _target_uri(claims["htu"]) != _target_uri(target_uri):
        raise RelayAuthenticationDenied("BABOOM DPoP target mismatched")
    issued_at = claims["iat"]
    if isinstance(issued_at, bool) or not isinstance(issued_at, (int, float)):
        raise RelayAuthenticationDenied("BABOOM DPoP issued time is invalid")
    age = now - float(issued_at)
    if age < -_DPOP_FUTURE_SKEW_SECONDS or age > _DPOP_MAX_AGE_SECONDS:
        raise RelayAuthenticationDenied("BABOOM DPoP proof is outside its time window")
    expected_ath = _b64url(hashlib.sha256(bearer_token.encode("ascii")).digest())
    if not isinstance(claims["ath"], str) or not hmac.compare_digest(claims["ath"], expected_ath):
        raise RelayAuthenticationDenied("BABOOM DPoP token binding mismatched")
    if not isinstance(claims["nonce"], str) or not hmac.compare_digest(claims["nonce"], expected_nonce):
        raise RelayAuthenticationDenied("BABOOM DPoP nonce mismatched")
    signature = _b64url_decode(parts[2], maximum=128)
    if len(signature) != 64:
        raise RelayAuthenticationDenied("BABOOM DPoP signature is invalid")
    der = utils.encode_dss_signature(
        int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    )
    try:
        public.verify(der, (parts[0] + "." + parts[1]).encode("ascii"), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise RelayAuthenticationDenied("BABOOM DPoP signature did not verify") from exc
    return proof_id


def _active_device(con, user_id: str, device_id: str):
    row = con.execute(
        "SELECT public_jwk_json, thumbprint FROM baboom_devices "
        "WHERE owner_user_id=? AND device_id=? AND revoked_at IS NULL",
        (user_id, device_id),
    ).fetchone()
    if row is None:
        raise RelayAuthenticationDenied("BABOOM device is not enrolled")
    try:
        jwk = json.loads(row["public_jwk_json"])
        _normalized, thumbprint, _public = _public_key(jwk)
    except (TypeError, ValueError, json.JSONDecodeError, RelayDenied) as exc:
        raise RelayAuthenticationDenied("BABOOM device record is invalid") from exc
    if not hmac.compare_digest(str(row["thumbprint"]), thumbprint):
        raise RelayAuthenticationDenied("BABOOM device record drifted")
    return thumbprint


def _recipient_key_row(con, *, user_id: str, device_id: str):
    row = con.execute(
        "SELECT recipient_public_jwk_json, recipient_thumbprint, "
        "universal_device_public_jwk_json, universal_device_thumbprint "
        "FROM baboom_devices "
        "WHERE owner_user_id=? AND device_id=? AND revoked_at IS NULL",
        (user_id, device_id),
    ).fetchone()
    if row is None or not row["recipient_public_jwk_json"] or not row["recipient_thumbprint"]:
        raise RelayConflict("BABOOM target recipient key is not enrolled")
    try:
        public_jwk = json.loads(row["recipient_public_jwk_json"])
        normalized, thumbprint, _public = _public_key(public_jwk)
    except (TypeError, ValueError, json.JSONDecodeError, RelayDenied) as exc:
        raise RelayConflict("BABOOM target recipient key is invalid") from exc
    if not hmac.compare_digest(str(row["recipient_thumbprint"]), thumbprint):
        raise RelayConflict("BABOOM target recipient key drifted")
    custody_public_jwk = row["universal_device_public_jwk_json"]
    custody_thumbprint = str(row["universal_device_thumbprint"] or "")
    if bool(custody_public_jwk) != bool(custody_thumbprint):
        raise RelayConflict("BABOOM target Universal Device Custody record drifted")
    if not custody_thumbprint:
        return normalized, thumbprint, None
    try:
        custody_jwk = json.loads(custody_public_jwk)
        _custody_normalized, verified_custody, _custody_public = _public_key(custody_jwk)
    except (TypeError, ValueError, json.JSONDecodeError, RelayDenied) as exc:
        raise RelayConflict("BABOOM target Universal Device Custody key is invalid") from exc
    if not hmac.compare_digest(custody_thumbprint, verified_custody):
        raise RelayConflict("BABOOM target Universal Device Custody key drifted")
    return normalized, thumbprint, verified_custody


def _brief_component(value: object, *, label: str, minimum: int, maximum: int) -> tuple[str, bytes]:
    if not isinstance(value, str):
        raise RelayDenied("BABOOM brief %s is invalid" % label)
    try:
        decoded = _b64url_decode(value, maximum=maximum)
    except RelayAuthenticationDenied as exc:
        raise RelayDenied("BABOOM brief %s is invalid" % label) from exc
    if not minimum <= len(decoded) <= maximum:
        raise RelayDenied("BABOOM brief %s has invalid length" % label)
    return value, decoded


def _brief_envelope(value: Mapping[str, object]) -> dict[str, object]:
    expected = {
        "version", "ephemeral_public_jwk", "recipient_thumbprint", "salt",
        "nonce", "ciphertext", "ciphertext_digest",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise RelayDenied("BABOOM brief envelope shape is invalid")
    try:
        version = int(value["version"])
        ephemeral = value["ephemeral_public_jwk"]
        recipient_thumbprint = str(value["recipient_thumbprint"])
        ciphertext_digest = str(value["ciphertext_digest"])
    except (TypeError, ValueError) as exc:
        raise RelayDenied("BABOOM brief envelope is invalid") from exc
    if version != _BRIEF_VERSION:
        raise RelayDenied("BABOOM brief envelope version is unsupported")
    normalized_ephemeral, _thumbprint, _public = _public_key(ephemeral)
    if not _THUMBPRINT.fullmatch(recipient_thumbprint):
        raise RelayDenied("BABOOM brief recipient key thumbprint is invalid")
    salt, _ = _brief_component(value["salt"], label="salt", minimum=32, maximum=32)
    nonce, _ = _brief_component(value["nonce"], label="nonce", minimum=12, maximum=12)
    ciphertext, ciphertext_raw = _brief_component(
        value["ciphertext"], label="ciphertext", minimum=17,
        maximum=_MAX_BRIEF_CIPHERTEXT_BYTES,
    )
    if not _DIGEST.fullmatch(ciphertext_digest) or not hmac.compare_digest(
        hashlib.sha256(ciphertext_raw).hexdigest(), ciphertext_digest
    ):
        raise RelayDenied("BABOOM brief ciphertext digest is invalid")
    return {
        "version": version,
        "ephemeral_public_jwk": normalized_ephemeral,
        "recipient_thumbprint": recipient_thumbprint,
        "salt": salt,
        "nonce": nonce,
        "ciphertext": ciphertext,
        "ciphertext_digest": ciphertext_digest,
    }


def begin_enrollment(*, user_id: str, device_id: str, public_jwk: Mapping[str, object], recipient_public_jwk: Mapping[str, object] | None = None, universal_device_public_jwk: Mapping[str, object] | None = None, now: float | None = None) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    device = _require_device_id(device_id)
    _normalized, thumbprint, _public = _public_key(public_jwk)
    recipient_normalized = None
    recipient_thumbprint = ""
    if recipient_public_jwk is not None:
        recipient_normalized, recipient_thumbprint, _recipient = _public_key(recipient_public_jwk)
        if hmac.compare_digest(recipient_thumbprint, thumbprint):
            raise RelayDenied("BABOOM recipient key must be distinct from the signing key")
    universal_normalized = None
    universal_thumbprint = ""
    if universal_device_public_jwk is not None:
        universal_normalized, universal_thumbprint, _universal = _public_key(universal_device_public_jwk)
        if hmac.compare_digest(universal_thumbprint, thumbprint):
            raise RelayDenied("BABOOM Universal Device Custody key must be distinct from the relay signing key")
    challenge_id = "bec_" + secrets.token_urlsafe(18)
    challenge = secrets.token_urlsafe(32)
    expires_at = int(current) + _CHALLENGE_TTL_SECONDS
    with db.connect() as con:
        con.execute("DELETE FROM baboom_enrollment_challenges WHERE expires_at <= ? OR used_at IS NOT NULL", (int(current),))
        con.execute(
            "INSERT INTO baboom_enrollment_challenges "
            "(id, owner_user_id, device_id, thumbprint, recipient_public_jwk_json, recipient_thumbprint, universal_device_public_jwk_json, universal_device_thumbprint, challenge_digest, expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                challenge_id, user_id, device, thumbprint,
                _canonical_json(recipient_normalized).decode("ascii") if recipient_normalized else None,
                recipient_thumbprint or None,
                _canonical_json(universal_normalized).decode("ascii") if universal_normalized else None,
                universal_thumbprint or None,
                hashlib.sha256(challenge.encode("ascii")).hexdigest(), expires_at,
            ),
        )
    return {
        "challenge_id": challenge_id,
        "challenge": challenge,
        "expires_at": expires_at,
        "thumbprint": thumbprint,
        "recipient_thumbprint": recipient_thumbprint,
        "universal_device_thumbprint": universal_thumbprint,
        # The device signs these exact opaque bytes.  Returning the descriptor
        # keeps the cloud's authenticated user binding out of desktop logic.
        "proof_payload": _b64url(enrollment_challenge_payload(
            user_id=user_id, challenge_id=challenge_id, challenge=challenge,
            device_id=device, thumbprint=thumbprint,
            recipient_thumbprint=recipient_thumbprint,
            universal_device_thumbprint=universal_thumbprint,
        )),
    }


def complete_enrollment(*, user_id: str, device_id: str, public_jwk: Mapping[str, object], challenge_id: str, challenge: str, signature: str, recipient_public_jwk: Mapping[str, object] | None = None, universal_device_public_jwk: Mapping[str, object] | None = None, universal_device_signature: str | None = None, now: float | None = None) -> DeviceIdentity:
    current = time.time() if now is None else float(now)
    device = _require_device_id(device_id)
    _normalized, thumbprint, public = _public_key(public_jwk)
    recipient_normalized = None
    recipient_thumbprint = ""
    if recipient_public_jwk is not None:
        recipient_normalized, recipient_thumbprint, _recipient = _public_key(recipient_public_jwk)
        if hmac.compare_digest(recipient_thumbprint, thumbprint):
            raise RelayDenied("BABOOM recipient key must be distinct from the signing key")
    universal_normalized = None
    universal_thumbprint = ""
    universal_public = None
    if universal_device_public_jwk is not None:
        universal_normalized, universal_thumbprint, universal_public = _public_key(universal_device_public_jwk)
        if hmac.compare_digest(universal_thumbprint, thumbprint):
            raise RelayDenied("BABOOM Universal Device Custody key must be distinct from the relay signing key")
    if not isinstance(challenge_id, str) or not challenge_id.startswith("bec_") or len(challenge_id) > 128:
        raise RelayAuthenticationDenied("BABOOM enrollment challenge id is invalid")
    if not isinstance(challenge, str) or not challenge or len(challenge) > 256:
        raise RelayAuthenticationDenied("BABOOM enrollment challenge is invalid")
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM baboom_enrollment_challenges WHERE id=? AND owner_user_id=?",
            (challenge_id, user_id),
        ).fetchone()
        if row is None or row["used_at"] is not None or int(row["expires_at"]) <= current:
            raise RelayAuthenticationDenied("BABOOM enrollment challenge is unavailable")
        if row["device_id"] != device or not hmac.compare_digest(row["thumbprint"], thumbprint):
            raise RelayAuthenticationDenied("BABOOM enrollment challenge binding mismatched")
        challenge_recipient = str(row["recipient_thumbprint"] or "")
        if not hmac.compare_digest(challenge_recipient, recipient_thumbprint):
            raise RelayAuthenticationDenied("BABOOM recipient key enrollment binding mismatched")
        challenge_universal = str(row["universal_device_thumbprint"] or "")
        if not hmac.compare_digest(challenge_universal, universal_thumbprint):
            raise RelayAuthenticationDenied("BABOOM Universal Device Custody enrollment binding mismatched")
        if bool(challenge_universal) != bool(universal_device_signature):
            raise RelayAuthenticationDenied("BABOOM Universal Device Custody proof is required")
        if not hmac.compare_digest(row["challenge_digest"], hashlib.sha256(challenge.encode("ascii")).hexdigest()):
            raise RelayAuthenticationDenied("BABOOM enrollment challenge mismatched")
        _verify_prehashed_signature(
            public, signature,
            enrollment_challenge_payload(
                user_id=user_id, challenge_id=challenge_id, challenge=challenge,
                device_id=device, thumbprint=thumbprint,
                recipient_thumbprint=recipient_thumbprint,
                universal_device_thumbprint=universal_thumbprint,
            ),
        )
        if challenge_universal:
            _verify_prehashed_signature(
                universal_public, str(universal_device_signature),
                enrollment_challenge_payload(
                    user_id=user_id, challenge_id=challenge_id, challenge=challenge,
                    device_id=device, thumbprint=thumbprint,
                    recipient_thumbprint=recipient_thumbprint,
                    universal_device_thumbprint=universal_thumbprint,
                ),
            )
        consumed = con.execute(
            "UPDATE baboom_enrollment_challenges SET used_at=? "
            "WHERE id=? AND used_at IS NULL AND expires_at > ?",
            (int(current), challenge_id, int(current)),
        )
        if consumed.rowcount != 1:
            raise RelayAuthenticationDenied("BABOOM enrollment challenge was already consumed")
        existing = con.execute(
            "SELECT thumbprint, recipient_thumbprint, universal_device_thumbprint FROM baboom_devices WHERE owner_user_id=? AND device_id=?",
            (user_id, device),
        ).fetchone()
        if existing is not None and not hmac.compare_digest(existing["thumbprint"], thumbprint):
            raise RelayDenied("BABOOM device key rotation requires revocation")
        if (
            existing is not None
            and existing["recipient_thumbprint"]
            and recipient_thumbprint
            and not hmac.compare_digest(existing["recipient_thumbprint"], recipient_thumbprint)
        ):
            raise RelayDenied("BABOOM recipient key rotation requires revocation")
        if (
            existing is not None
            and existing["universal_device_thumbprint"]
            and universal_thumbprint
            and not hmac.compare_digest(existing["universal_device_thumbprint"], universal_thumbprint)
        ):
            raise RelayDenied("BABOOM Universal Device Custody key rotation requires revocation")
        con.execute(
            "INSERT INTO baboom_devices (owner_user_id, device_id, public_jwk_json, thumbprint, recipient_public_jwk_json, recipient_thumbprint, universal_device_public_jwk_json, universal_device_thumbprint, created_at, last_seen_at, revoked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,NULL) "
            "ON CONFLICT(owner_user_id, device_id) DO UPDATE SET "
            "recipient_public_jwk_json=COALESCE(excluded.recipient_public_jwk_json, baboom_devices.recipient_public_jwk_json), "
            "recipient_thumbprint=COALESCE(excluded.recipient_thumbprint, baboom_devices.recipient_thumbprint), "
            "universal_device_public_jwk_json=COALESCE(excluded.universal_device_public_jwk_json, baboom_devices.universal_device_public_jwk_json), "
            "universal_device_thumbprint=COALESCE(excluded.universal_device_thumbprint, baboom_devices.universal_device_thumbprint), "
            "last_seen_at=excluded.last_seen_at, revoked_at=NULL",
            (
                user_id, device, _canonical_json(_normalized).decode("ascii"), thumbprint,
                _canonical_json(recipient_normalized).decode("ascii") if recipient_normalized else None,
                recipient_thumbprint or None,
                _canonical_json(universal_normalized).decode("ascii") if universal_normalized else None,
                universal_thumbprint or None, int(current), int(current),
            ),
        )
    return DeviceIdentity(user_id, device, thumbprint)


def issue_nonce(*, user_id: str, device_id: str, now: float | None = None) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    device = _require_device_id(device_id)
    nonce = secrets.token_urlsafe(32)
    expires_at = int(current) + _NONCE_TTL_SECONDS
    with db.connect() as con:
        _active_device(con, user_id, device)
        con.execute("DELETE FROM baboom_relay_nonces WHERE expires_at <= ? OR used_at IS NOT NULL", (int(current),))
        con.execute(
            "INSERT INTO baboom_relay_nonces (id, owner_user_id, device_id, nonce_digest, expires_at) VALUES (?,?,?,?,?)",
            ("bn_" + secrets.token_urlsafe(18), user_id, device, hashlib.sha256(nonce.encode("ascii")).hexdigest(), expires_at),
        )
    return {"nonce": nonce, "expires_at": expires_at}


def authenticate_device_request(*, user_id: str, bearer_token: str, device_id: str, proof: str, method: str, target_uri: str, now: float | None = None) -> DeviceIdentity:
    current = time.time() if now is None else float(now)
    device = _require_device_id(device_id)
    if not bearer_token or len(bearer_token) > 512 or not bearer_token.isascii():
        raise RelayAuthenticationDenied("BABOOM bearer token is invalid")
    try:
        raw_claims = json.loads(_b64url_decode(proof.split(".")[1], maximum=8192).decode("utf-8"))
        nonce = raw_claims.get("nonce") if isinstance(raw_claims, dict) else None
    except (IndexError, UnicodeDecodeError, json.JSONDecodeError, RelayAuthenticationDenied) as exc:
        raise RelayAuthenticationDenied("BABOOM DPoP nonce is unavailable") from exc
    if not isinstance(nonce, str) or not nonce:
        raise RelayAuthenticationDenied("BABOOM DPoP nonce is unavailable")
    try:
        nonce_digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    except UnicodeEncodeError as exc:
        raise RelayAuthenticationDenied("BABOOM DPoP nonce is invalid") from exc
    with db.connect() as con:
        thumbprint = _active_device(con, user_id, device)
        nonce_row = con.execute(
            "SELECT id FROM baboom_relay_nonces WHERE owner_user_id=? AND device_id=? "
            "AND nonce_digest=? AND used_at IS NULL AND expires_at > ?",
            (user_id, device, nonce_digest, int(current)),
        ).fetchone()
        if nonce_row is None:
            raise RelayAuthenticationDenied("BABOOM DPoP nonce is invalid or expired")
        proof_id = _parse_dpop(
            proof, bearer_token=bearer_token, device_thumbprint=thumbprint,
            method=method, target_uri=target_uri, expected_nonce=nonce, now=current,
        )
        try:
            replay = con.execute(
                "INSERT INTO baboom_dpop_proofs (owner_user_id, device_id, proof_jti, received_at) VALUES (?,?,?,?)",
                (user_id, device, proof_id, int(current)),
            )
        except sqlite3.IntegrityError as exc:
            raise RelayAuthenticationDenied("BABOOM DPoP proof was replayed") from exc
        if replay.rowcount != 1:
            raise RelayAuthenticationDenied("BABOOM DPoP proof was replayed")
        consumed = con.execute(
            "UPDATE baboom_relay_nonces SET used_at=? WHERE id=? AND used_at IS NULL AND expires_at > ?",
            (int(current), nonce_row["id"], int(current)),
        )
        if consumed.rowcount != 1:
            raise RelayAuthenticationDenied("BABOOM DPoP nonce was already consumed")
        con.execute(
            "UPDATE baboom_devices SET last_seen_at=? WHERE owner_user_id=? AND device_id=?",
            (int(current), user_id, device),
        )
    return DeviceIdentity(user_id, device, thumbprint)


def _expire_commands(con, *, user_id: str, now: float) -> None:
    con.execute(
        "UPDATE baboom_commands SET state='expired', settled_at=?, outcome_code='delivery-expired' "
        "WHERE owner_user_id=? AND state='queued' AND expires_at <= ?",
        (int(now), user_id, int(now)),
    )
    con.execute(
        "UPDATE baboom_briefs SET revoked_at=COALESCE(revoked_at, ?) "
        "WHERE owner_user_id=? AND command_id IN ("
        "SELECT command_id FROM baboom_commands "
        "WHERE owner_user_id=? AND state='expired')",
        (int(now), user_id, user_id),
    )


def _command_row(row) -> dict[str, object]:
    return {
        "command_id": row["command_id"], "source_device_id": row["source_device_id"],
        "target_device_id": row["target_device_id"], "summary": row["summary"],
        "payload_digest": row["payload_digest"], "state": row["state"],
        "created_at": float(row["created_at"]), "expires_at": float(row["expires_at"]),
        "claimed_at": row["claimed_at"], "settled_at": row["settled_at"],
        "outcome_code": row["outcome_code"],
    }


def submit_command(*, identity: DeviceIdentity, command_id: str, target_device_id: str, summary: str, payload_digest: str, created_at: float, expires_at: float, now: float | None = None) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    command = _require_digest(command_id, label="command id")
    target = _require_device_id(target_device_id)
    if identity.device_id == target:
        raise RelayDenied("BABOOM command target must be a different device")
    message = _safe_summary(summary)
    payload = _require_digest(payload_digest, label="payload digest")
    try:
        created = float(created_at)
        expiry = float(expires_at)
    except (TypeError, ValueError) as exc:
        raise RelayDenied("BABOOM command timestamps are invalid") from exc
    if not math.isfinite(created) or abs(current - created) > _MAX_COMMAND_CLOCK_SKEW_SECONDS:
        raise RelayDenied("BABOOM command creation time is outside the relay window")
    if not math.isfinite(expiry) or expiry <= created or expiry - created > _MAX_COMMAND_LIFETIME_SECONDS:
        raise RelayDenied("BABOOM command expiry must be within one day")
    with db.connect() as con:
        _expire_commands(con, user_id=identity.user_id, now=current)
        _active_device(con, identity.user_id, target)
        existing = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if existing is not None:
            expected = (identity.device_id, target, message, payload, created, expiry)
            actual = (existing["source_device_id"], existing["target_device_id"], existing["summary"], existing["payload_digest"], float(existing["created_at"]), float(existing["expires_at"]))
            if actual != expected:
                raise RelayConflict("BABOOM command idempotency key was reused")
            return _command_row(existing)
        con.execute(
            "INSERT INTO baboom_commands "
            "(owner_user_id, command_id, source_device_id, target_device_id, summary, payload_digest, state, created_at, expires_at) "
            "VALUES (?,?,?,?,?,?, 'queued', ?, ?)",
            (identity.user_id, command, identity.device_id, target, message, payload, created, expiry),
        )
        row = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
    return _command_row(row)


def get_recipient_key(*, identity: DeviceIdentity, target_device_id: str) -> dict[str, object]:
    target = _require_device_id(target_device_id)
    if target == identity.device_id:
        raise RelayDenied("BABOOM recipient key must belong to a different device")
    with db.connect() as con:
        public_jwk, thumbprint, universal_thumbprint = _recipient_key_row(
            con, user_id=identity.user_id, device_id=target
        )
    return {
        "device_id": target,
        "recipient_public_jwk": public_jwk,
        "recipient_thumbprint": thumbprint,
        "universal_device_thumbprint": universal_thumbprint,
    }


def put_encrypted_brief(
    *, identity: DeviceIdentity, command_id: str, envelope: Mapping[str, object],
    now: float | None = None,
) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    command = _require_digest(command_id, label="command id")
    checked = _brief_envelope(envelope)
    with db.connect() as con:
        _expire_commands(con, user_id=identity.user_id, now=current)
        row = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if (
            row is None or row["source_device_id"] != identity.device_id
            or row["state"] != "queued" or float(row["expires_at"]) <= current
        ):
            raise RelayConflict("BABOOM brief is not writable")
        _public_jwk, recipient_thumbprint, _universal_thumbprint = _recipient_key_row(
            con, user_id=identity.user_id, device_id=row["target_device_id"]
        )
        if not hmac.compare_digest(checked["recipient_thumbprint"], recipient_thumbprint):
            raise RelayConflict("BABOOM brief recipient key does not match the target")
        existing = con.execute(
            "SELECT revoked_at FROM baboom_briefs WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if existing is not None and existing["revoked_at"] is not None:
            raise RelayConflict("BABOOM brief was revoked")
        con.execute(
            "INSERT INTO baboom_briefs "
            "(owner_user_id, command_id, recipient_thumbprint, ephemeral_jwk_json, salt, nonce, ciphertext, ciphertext_digest, created_at, updated_at, revoked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,NULL) "
            "ON CONFLICT(owner_user_id, command_id) DO UPDATE SET "
            "recipient_thumbprint=excluded.recipient_thumbprint, "
            "ephemeral_jwk_json=excluded.ephemeral_jwk_json, salt=excluded.salt, "
            "nonce=excluded.nonce, ciphertext=excluded.ciphertext, "
            "ciphertext_digest=excluded.ciphertext_digest, updated_at=excluded.updated_at "
            "WHERE baboom_briefs.revoked_at IS NULL",
            (
                identity.user_id, command, checked["recipient_thumbprint"],
                _canonical_json(checked["ephemeral_public_jwk"]).decode("ascii"),
                checked["salt"], checked["nonce"], checked["ciphertext"],
                checked["ciphertext_digest"], int(current), int(current),
            ),
        )
    return {
        "command_id": command,
        "recipient_thumbprint": checked["recipient_thumbprint"],
        "ciphertext_digest": checked["ciphertext_digest"],
        "status": "stored",
    }


def fetch_encrypted_brief(
    *, identity: DeviceIdentity, command_id: str, now: float | None = None,
) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    command = _require_digest(command_id, label="command id")
    with db.connect() as con:
        _expire_commands(con, user_id=identity.user_id, now=current)
        row = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if (
            row is None or row["target_device_id"] != identity.device_id
            or row["state"] not in {"queued", "claimed"}
        ):
            raise RelayConflict("BABOOM brief is not readable")
        brief = con.execute(
            "SELECT * FROM baboom_briefs WHERE owner_user_id=? AND command_id=? AND revoked_at IS NULL",
            (identity.user_id, command),
        ).fetchone()
        if brief is None:
            raise RelayConflict("BABOOM brief is unavailable")
        try:
            envelope = _brief_envelope({
                "version": _BRIEF_VERSION,
                "ephemeral_public_jwk": json.loads(brief["ephemeral_jwk_json"]),
                "recipient_thumbprint": brief["recipient_thumbprint"],
                "salt": brief["salt"], "nonce": brief["nonce"],
                "ciphertext": brief["ciphertext"],
                "ciphertext_digest": brief["ciphertext_digest"],
            })
        except (TypeError, ValueError, json.JSONDecodeError, RelayDenied) as exc:
            raise RelayConflict("BABOOM brief record is invalid") from exc
    return {"command_id": command, "envelope": envelope}


def revoke_encrypted_brief(
    *, identity: DeviceIdentity, command_id: str, now: float | None = None,
) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    command = _require_digest(command_id, label="command id")
    with db.connect() as con:
        _expire_commands(con, user_id=identity.user_id, now=current)
        row = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if (
            row is None or row["source_device_id"] != identity.device_id
            or row["state"] != "queued"
        ):
            raise RelayConflict("BABOOM brief is not revocable")
        revoked = con.execute(
            "UPDATE baboom_briefs SET revoked_at=COALESCE(revoked_at, ?) "
            "WHERE owner_user_id=? AND command_id=?",
            (int(current), identity.user_id, command),
        )
        if revoked.rowcount != 1:
            raise RelayConflict("BABOOM brief is unavailable")
    return {"command_id": command, "status": "revoked"}


def list_target_commands(*, identity: DeviceIdentity, now: float | None = None) -> list[dict[str, object]]:
    current = time.time() if now is None else float(now)
    with db.connect() as con:
        _expire_commands(con, user_id=identity.user_id, now=current)
        rows = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND target_device_id=? "
            "AND state IN ('queued','claimed') ORDER BY created_at ASC LIMIT 100",
            (identity.user_id, identity.device_id),
        ).fetchall()
    return [_command_row(row) for row in rows]


def list_source_commands(*, identity: DeviceIdentity, now: float | None = None) -> list[dict[str, object]]:
    """Return the caller's own transport receipts without exposing other devices."""
    current = time.time() if now is None else float(now)
    with db.connect() as con:
        _expire_commands(con, user_id=identity.user_id, now=current)
        rows = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND source_device_id=? "
            "ORDER BY created_at DESC LIMIT 100",
            (identity.user_id, identity.device_id),
        ).fetchall()
    return [_command_row(row) for row in rows]


def claim_command(*, identity: DeviceIdentity, command_id: str, now: float | None = None) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    command = _require_digest(command_id, label="command id")
    with db.connect() as con:
        _expire_commands(con, user_id=identity.user_id, now=current)
        claimed = con.execute(
            "UPDATE baboom_commands SET state='claimed', claimed_at=? "
            "WHERE owner_user_id=? AND command_id=? AND target_device_id=? "
            "AND state='queued' AND expires_at > ?",
            (int(current), identity.user_id, command, identity.device_id, int(current)),
        )
        row = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if row is None:
            raise RelayConflict("BABOOM command is not claimable")
        if claimed.rowcount != 1:
            if row["target_device_id"] == identity.device_id and row["state"] == "claimed":
                return _command_row(row)
            raise RelayConflict("BABOOM command is not claimable")
    return _command_row(row)


def settle_command(*, identity: DeviceIdentity, command_id: str, succeeded: bool, outcome_code: str, now: float | None = None) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    command = _require_digest(command_id, label="command id")
    outcome = _require_outcome(outcome_code, label="receipt code")
    state = "completed" if bool(succeeded) else "failed"
    with db.connect() as con:
        settled = con.execute(
            "UPDATE baboom_commands SET state=?, settled_at=?, outcome_code=? "
            "WHERE owner_user_id=? AND command_id=? AND target_device_id=? AND state='claimed'",
            (state, int(current), outcome, identity.user_id, command, identity.device_id),
        )
        row = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if row is None:
            raise RelayConflict("BABOOM command is not settleable")
        if settled.rowcount != 1:
            if (
                row["target_device_id"] == identity.device_id
                and row["state"] == state
                and row["outcome_code"] == outcome
            ):
                return _command_row(row)
            raise RelayConflict("BABOOM command is not settleable")
    return _command_row(row)


def cancel_command(*, identity: DeviceIdentity, command_id: str, reason_code: str, now: float | None = None) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    command = _require_digest(command_id, label="command id")
    reason = _require_outcome(reason_code, label="cancellation code")
    with db.connect() as con:
        cancelled = con.execute(
            "UPDATE baboom_commands SET state='cancelled', settled_at=?, outcome_code=? "
            "WHERE owner_user_id=? AND command_id=? AND source_device_id=? AND state='queued'",
            (int(current), reason, identity.user_id, command, identity.device_id),
        )
        row = con.execute(
            "SELECT * FROM baboom_commands WHERE owner_user_id=? AND command_id=?",
            (identity.user_id, command),
        ).fetchone()
        if row is None:
            raise RelayConflict("BABOOM command is not cancellable")
        if cancelled.rowcount != 1:
            if (
                row["source_device_id"] == identity.device_id
                and row["state"] == "cancelled"
                and row["outcome_code"] == reason
            ):
                return _command_row(row)
            raise RelayConflict("BABOOM command is not cancellable")
        con.execute(
            "UPDATE baboom_briefs SET revoked_at=COALESCE(revoked_at, ?) "
            "WHERE owner_user_id=? AND command_id=?",
            (int(current), identity.user_id, command),
        )
    return _command_row(row)


__all__ = [
    "DeviceIdentity", "RelayAuthenticationDenied", "RelayConflict", "RelayDenied",
    "authenticate_device_request", "begin_enrollment", "cancel_command",
    "claim_command", "complete_enrollment", "enrollment_challenge_payload",
    "fetch_encrypted_brief", "get_recipient_key", "issue_nonce",
    "list_source_commands", "list_target_commands", "put_encrypted_brief",
    "revoke_encrypted_brief", "settle_command", "submit_command",
]
