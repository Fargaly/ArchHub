"""Consent record for publishing this machine's graph map to the cloud.

The website promises that nothing leaves the machine. That promise is only
true if the upload path is closed until the person on this machine opens it.
The record is one JSON file beside the graph; deleting it withdraws consent.
No network, no defaults written, no second store.
"""
from __future__ import annotations

import json
from pathlib import Path

CONSENT_FILE = "cloud-publish.consent.json"


def cloud_publish_allowed(state_dir: Path) -> bool:
    """True only when this machine holds an explicit publish consent record."""
    record = Path(state_dir) / CONSENT_FILE
    try:
        held = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(held, dict) and held.get("publish_map") is True


def record_cloud_publish_consent(state_dir: Path, *, account: str) -> Path:
    """Write the consent record; called only from an explicit user action."""
    if not isinstance(account, str) or "@" not in account:
        raise ValueError("consent is recorded for a signed-in account")
    record = Path(state_dir) / CONSENT_FILE
    import time
    record.write_text(json.dumps({
        "publish_map": True,
        "account": account,
        "granted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=1), encoding="utf-8")
    return record


__all__ = ["CONSENT_FILE", "cloud_publish_allowed", "record_cloud_publish_consent"]
