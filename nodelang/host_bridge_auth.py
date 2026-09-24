"""The one per-install secret every ArchHub host bridge requires from its caller.

The Revit and AutoCAD add-ins compile C# posted to a localhost port; the Rhino,
Blender and 3ds Max bridges run posted Python or MAXScript. Each of them now
refuses every route but /ping unless the request carries HEADER equal to this
secret, compared in constant time, and refuses any request a browser sends
(bridges/sources/shared/BridgeAuth.cs and the "ArchHub bridge caller check"
block in each Python bridge).

The secret is created here, once, with ``secrets.token_urlsafe(32)`` and kept
in the application's credential store (app/secrets_store.py), provider
PROVIDER. On the shipped desktop that store is keyring, i.e. the Windows
Credential Locker, which the bridges read directly with CredReadW: target
"ArchHub" when its user is PROVIDER, otherwise "PROVIDER@ArchHub" -- exactly
where keyring puts it. It is never written to a file, never sent to a
non-loopback address and never placed in a URL.

When the store falls back to the DPAPI file (no keyring), the bridges cannot
read it and refuse with 503 "not provisioned": they fail closed, never open.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

PROVIDER = "archhub-host-bridge"
HEADER = "X-ArchHub-Bridge-Token"
_MINIMUM_LENGTH = 32


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


def _loopback(url: str) -> bool:
    host = urlsplit(url).hostname
    return host in ("127.0.0.1", "localhost", "::1")


def bridge_headers(url: str) -> dict[str, str]:
    """The caller header for one loopback bridge URL; nothing for any other address.

    A store failure yields no header: the bridge then answers 401 and the
    engine reports that refusal, instead of a guessed success.
    """
    if not _loopback(url):
        return {}
    try:
        return {HEADER: ensure_secret()}
    except Exception:  # noqa: BLE001 - reported by the bridge's own refusal
        return {}


__all__ = ["BridgeSecretUnavailable", "HEADER", "PROVIDER", "bridge_headers", "ensure_secret"]
