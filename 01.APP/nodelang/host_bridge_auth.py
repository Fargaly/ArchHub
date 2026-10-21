"""The one authenticated client for every ArchHub host bridge, and the secret it signs with.

The Revit and AutoCAD add-ins compile C# posted to a localhost port; the Rhino,
Blender and 3ds Max bridges run posted Python or MAXScript. Each of them refuses
every route but /ping unless the request is signed with this install's bridge
secret (bridges/sources/shared/BridgeAuth.cs and the "ArchHub bridge caller
check" block in each Python bridge):

    X-ArchHub-Bridge-Time       unix seconds
    X-ArchHub-Bridge-Nonce      32 random hex digits, used once
    X-ArchHub-Bridge-Signature  hex HMAC-SHA256(secret,
                                "METHOD|request-target|time|nonce|sha256hex(body)")

The request-target is the path plus query exactly as sent. A bridge refuses a
time more than SKEW_SECONDS away from its own clock and a nonce it has seen,
so a signature is good for one request only. The secret itself never crosses
the wire: a process squatting a bridge port learns one used-up MAC, not the key.

The secret is created here, once, with ``secrets.token_urlsafe(32)`` and kept
in the application's credential store (app/secrets_store.py), provider
PROVIDER. On the shipped desktop that store is keyring, i.e. the Windows
Credential Locker, which the bridges read directly with CredReadW: target
"ArchHub" when its user is PROVIDER, otherwise "PROVIDER@ArchHub" -- exactly
where keyring puts it. When the store falls back to the DPAPI file (no
keyring), the bridges cannot read it and refuse with 503: they fail closed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from urllib.parse import urlsplit

PROVIDER = "archhub-host-bridge"
TIME_HEADER = "X-ArchHub-Bridge-Time"
NONCE_HEADER = "X-ArchHub-Bridge-Nonce"
SIGNATURE_HEADER = "X-ArchHub-Bridge-Signature"
SKEW_SECONDS = 60
_MINIMUM_LENGTH = 32
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


class BridgeSecretUnavailable(RuntimeError):
    """The credential store could not hold or return the bridge secret."""


def _store():
    from app import secrets_store  # noqa: PLC0415 - the one credential owner
    return secrets_store


def _usable(value: object) -> bool:
    return type(value) is str and len(value) >= _MINIMUM_LENGTH and value.isascii()


def ensure_secret() -> str:
    """This install's bridge secret, created on first use and read back to prove it."""
    store = _store()
    current = store.load_api_key(PROVIDER)
    if _usable(current):
        return current
    created = secrets.token_urlsafe(32)
    store.save_api_key(PROVIDER, created)
    if store.load_api_key(PROVIDER) != created:
        raise BridgeSecretUnavailable("the credential store did not return the bridge secret it saved")
    return created


def signing_text(method: str, target: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    """What both sides MAC; any change to method, target, time, nonce or body breaks it."""
    return "|".join((method.upper(), target, timestamp, nonce,
                     hashlib.sha256(body).hexdigest())).encode("utf-8")


def _target(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + ("?" + parts.query if parts.query else "")


def signed_headers(method: str, url: str, body: bytes, *, secret: str | None = None,
                   now: float | None = None) -> dict[str, str]:
    """Fresh one-use signature headers for exactly this request."""
    key = secret if secret is not None else ensure_secret()
    timestamp = str(int(time.time() if now is None else now))
    nonce = secrets.token_hex(16)
    mac = hmac.new(key.encode("utf-8"), signing_text(method, _target(url), timestamp, nonce, body),
                   hashlib.sha256).hexdigest()
    return {TIME_HEADER: timestamp, NONCE_HEADER: nonce, SIGNATURE_HEADER: mac}


def bridge_request(url: str, body: Mapping[str, object] | None = None, *,
                   timeout: float = 20.0, sign: bool = True) -> tuple[int, dict]:
    """One call to a loopback host bridge; (HTTP status, JSON answer).

    Only loopback URLs are accepted. The request is signed unless sign=False
    (the /ping identity route needs no signature). A store failure sends the
    request unsigned, so the bridge's own 401 is what the caller reports --
    never a guessed success. A refusal's JSON reason is returned, not raised.
    """
    if urlsplit(url).hostname not in _LOOPBACK:
        raise ValueError("host bridges are only called on this machine's loopback address")
    data = b"" if body is None else json.dumps(dict(body)).encode("utf-8")
    method = "GET" if body is None else "POST"
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if sign:
        try:
            headers.update(signed_headers(method, url, data))
        except Exception:  # noqa: BLE001 - reported by the bridge's refusal
            pass
    request = urllib.request.Request(url, data=data if body is not None else None,
                                     method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as refused:
        status, raw = refused.code, refused.read()
    try:
        answer = json.loads(raw.decode("utf-8", "replace")) if raw else {}
    except ValueError:
        answer = {"raw": raw.decode("utf-8", "replace")}
    if not isinstance(answer, dict):
        answer = {"result": answer}
    return status, answer


__all__ = ["BridgeSecretUnavailable", "NONCE_HEADER", "PROVIDER", "SIGNATURE_HEADER",
           "SKEW_SECONDS", "TIME_HEADER", "bridge_request", "ensure_secret",
           "signed_headers", "signing_text"]
