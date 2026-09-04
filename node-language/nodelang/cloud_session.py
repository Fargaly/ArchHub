"""The account signed in to the cloud on THIS machine.

Identity is an email account, never a machine. The only proof of an email on
this machine is the cloud session the person opened with Google: it lives in
%APPDATA%/ArchHub/brain/cloud.json and names the account it was issued to.
Local account routes trust that record and nothing typed into a box.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def cloud_session_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "ArchHub" / "brain" / "cloud.json"


def signed_in_cloud_account(path: Path | None = None) -> str | None:
    """The email the cloud session on this machine was issued to, or None."""
    record = path or cloud_session_path()
    try:
        held = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    email = held.get("email") if isinstance(held, dict) else None
    token = held.get("token") if isinstance(held, dict) else None
    if not isinstance(email, str) or "@" not in email or not token:
        return None
    return email.strip().casefold()


__all__ = ["cloud_session_path", "signed_in_cloud_account"]
