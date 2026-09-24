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


# Where the founder question goes is the ONE cloud pin (cloud_relay's
# pinned_cloud_base): cloud.json is editable, so a base it names off the pin is
# never used. None means "the pin"; only a court sets a loopback stand-in here.
FOUNDER_CHECK_BASES: tuple[str, ...] | None = None
# A route the cloud serves to founder accounts only (founder_cockpit
# require_founder: 200 for a founder's bearer token, 403 for anyone else).
FOUNDER_CHECK_PATH = "/founder/api/system"
ME_PATH = "/v1/me"
_FOUNDER_TTL_SECONDS = 600.0
_founder_verdicts: dict[str, tuple[float, str | None]] = {}


def _cloud_get(url: str, bearer: str, timeout: float = 6.0):
    """(HTTP status, JSON object or None) of a GET with the bearer; (None, None) if unreachable."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + bearer, "Accept": "application/json",
        "User-Agent": "ArchHub-desktop/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            code, raw = int(answer.status), answer.read(65536)
    except urllib.error.HTTPError as refused:
        return int(refused.code), None
    except (OSError, ValueError):
        return None, None
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        body = None
    return code, body if isinstance(body, dict) else None


def _pinned_base(held: dict) -> str:
    """The one cloud host a bearer is sent to, from the one pin.

    cloud_relay.pinned_cloud_base (the sign-in lane's single pin) decides when
    this build carries it; before it lands, only the one default address is
    used -- never a base read from cloud.json.
    """
    value = held.get("cloud_base_url")
    if FOUNDER_CHECK_BASES is not None:  # a court's loopback stand-in
        base = str(value or "").rstrip("/")
        return base if base in FOUNDER_CHECK_BASES else FOUNDER_CHECK_BASES[0]
    from . import cloud_relay
    pin = getattr(cloud_relay, "pinned_cloud_base", None)
    return pin(value) if pin is not None else cloud_relay.DEFAULT_BASE


def signed_in_founder_account(path: Path | None = None, *, fetch=None) -> str | None:
    """The founder account the CLOUD names for this machine's session, else None.

    Nothing written on this disk decides it: cloud.json is editable, so the
    only thing taken from it is the bearer token (and a base URL, honoured only
    when it is one of the pinned cloud hosts). The cloud is asked twice with
    that token: /v1/me says WHICH account the token belongs to -- the email
    returned here is the cloud's, never the file's -- and the founder-only
    route says whether that account is a founder; only its 200 grants the
    tier. A refusal, no session, or an unreachable cloud means no founder.
    Definite answers are remembered in this process only, for ten minutes.
    """
    record = path or cloud_session_path()
    try:
        held = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict):
        return None
    bearer = str(held.get("token") or "")
    if not bearer:
        return None
    base = _pinned_base(held)
    import hashlib
    import time
    key = hashlib.sha256(("%s|%s" % (base, bearer)).encode("utf-8")).hexdigest()
    now = time.monotonic()
    cached = _founder_verdicts.get(key)
    if cached is not None and now - cached[0] < _FOUNDER_TTL_SECONDS:
        return cached[1]
    get = fetch or _cloud_get
    code, me = get(base + ME_PATH, bearer)
    if code in (401, 403):
        _founder_verdicts[key] = (now, None)
        return None
    email = str((me or {}).get("email") or "").strip().casefold()
    if code != 200 or "@" not in email:
        return None
    verdict, _body = get(base + FOUNDER_CHECK_PATH, bearer)
    if verdict in (200, 401, 403):
        _founder_verdicts[key] = (now, email if verdict == 200 else None)
    return email if verdict == 200 else None


def login_standing(mail: str, stored_tier: str, cloud_founder: str | None) -> tuple[str, bool]:
    """(tier, founder) a sign-in answers with: founder ONLY on the cloud's word.

    A graph can already hold a founder record (an old graph, a copied graph);
    that record never makes a sign-in a founder. Without the cloud's verdict
    for this very account, a stored "founder" tier answers as "free".
    """
    founder = cloud_founder is not None and cloud_founder == str(mail).strip().casefold()
    if founder:
        return "founder", True
    return ("free" if stored_tier == "founder" else stored_tier), False


__all__ = ["cloud_session_path", "login_standing",
           "signed_in_cloud_account", "signed_in_founder_account"]
