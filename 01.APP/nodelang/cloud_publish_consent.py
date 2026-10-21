"""Consent record for publishing this machine's graph map to the cloud.

The website promises that nothing leaves the machine. That promise is only
true if the upload path is closed until the person on this machine opens it.
The record is one JSON file beside the graph; deleting it withdraws consent.
No network, no defaults written, no second store.

Consent belongs to the account that gave it (identity = account, never
machine): it holds only while that same account is the one signed in. After a
sign-out or a switch to another account the record grants nothing, the relay
does not start and a running relay stops at its next poll; the new account
must allow publishing itself.
"""
from __future__ import annotations

import json
from pathlib import Path

CONSENT_FILE = "cloud-publish.consent.json"
SIGNED_IN_NOW = object()  # read the account from this machine's cloud.json at call time


def _account(value) -> str:
    return value.strip().casefold() if isinstance(value, str) and "@" in value else ""


def read_cloud_publish_consent(state_dir: Path, account=SIGNED_IN_NOW) -> dict:
    """{allowed, account} for ``account``, the account signed in now (None: nobody).

    Allowed only when the record says publish and was granted by that same
    account; an unreadable record, no sign-in or another account is no consent.
    """
    record = Path(state_dir) / CONSENT_FILE
    try:
        held = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"allowed": False, "account": ""}
    if not isinstance(held, dict) or held.get("publish_map") is not True:
        return {"allowed": False, "account": ""}
    if account is SIGNED_IN_NOW:
        from .cloud_session import signed_in_cloud_account
        account = signed_in_cloud_account()
    granted_by = _account(held.get("account"))
    current = _account(account)
    if not current or granted_by != current:
        return {"allowed": False, "account": ""}
    return {"allowed": True, "account": granted_by}


def cloud_publish_allowed(state_dir: Path, account=SIGNED_IN_NOW) -> bool:
    """True only when ``account`` (signed in now) granted the publish consent."""
    return read_cloud_publish_consent(state_dir, account)["allowed"]


def record_cloud_publish_consent(state_dir: Path, *, account: str) -> Path:
    """Write the consent record; called only from an explicit user action."""
    if not _account(account):
        raise ValueError("consent is recorded for a signed-in account")
    record = Path(state_dir) / CONSENT_FILE
    import time
    record.write_text(json.dumps({
        "publish_map": True,
        "account": _account(account),
        "granted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=1), encoding="utf-8")
    return record


def withdraw_cloud_publish_consent(state_dir: Path) -> None:
    """Delete the record; a running relay stops at its next poll (cloud_relay)."""
    try:
        (Path(state_dir) / CONSENT_FILE).unlink()
    except FileNotFoundError:
        pass


__all__ = [
    "CONSENT_FILE", "cloud_publish_allowed", "read_cloud_publish_consent",
    "record_cloud_publish_consent", "withdraw_cloud_publish_consent",
]
