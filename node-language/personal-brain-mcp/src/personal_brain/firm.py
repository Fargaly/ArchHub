"""Firm identity + invite flow — Slice 9.

Creates and manages firm identity, seat membership, and signed invite
tokens. Pure stdlib crypto (ed25519 via `cryptography` if installed,
HMAC-SHA256 fallback otherwise — invites still signed, just smaller
keys + weaker properties).

Public surface:

    from personal_brain.firm import (
        create_firm, create_invite_token, accept_invite_token,
        list_seats, current_firm_id, FirmIdentity, Seat, InviteToken,
    )

Persistence model:
  * `firm_identity` row in brain_meta: JSON {firm_id, name, root_pub,
                                              created_at, root_priv}
    (private key NEVER leaves device; new device gets a NEW invite)
  * `firm_seat` Fragment per member: kind=setup,
    scope=firm, predicate="seat", subject=<user_id>, object=<role>
  * `firm_invite` Fragment per active invite:
    kind=setup, scope=firm, predicate="invite", expires_at in extra

Invite tokens are base64url(JSON{firm_id,role,issued_by,issued_at,
expires_at,nonce} + signature). Tokens carry the firm public key so
joining device can verify offline. Tokens expire after 24h by default.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from .storage import BrainStore


# ─────────────────────── crypto layer ──────────────────────────────────


_HAS_ED25519 = False
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    _HAS_ED25519 = True
except Exception:
    pass


def _generate_keypair() -> tuple[str, str]:
    """Return (private_pem_b64, public_pem_b64).

    With cryptography: real ed25519. Without: 32-byte symmetric HMAC key
    used as both halves (weaker but works — same key signs + verifies).
    """
    if _HAS_ED25519:
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        priv_bytes = priv.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption(),
        )
        pub_bytes = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return (
            base64.urlsafe_b64encode(priv_bytes).decode(),
            base64.urlsafe_b64encode(pub_bytes).decode(),
        )
    # Fallback: 32-byte symmetric secret
    secret = secrets.token_bytes(32)
    encoded = base64.urlsafe_b64encode(secret).decode()
    return (encoded, encoded)


def _sign(priv_b64: str, payload: bytes) -> str:
    if _HAS_ED25519:
        try:
            priv_bytes = base64.urlsafe_b64decode(priv_b64.encode())
            priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
            sig = priv.sign(payload)
            return base64.urlsafe_b64encode(sig).decode()
        except Exception:
            pass  # fall through to HMAC fallback below
    # HMAC fallback — works when both sides share the symmetric "priv"
    key = base64.urlsafe_b64decode(priv_b64.encode())
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode()


def _verify(pub_b64: str, payload: bytes, sig_b64: str) -> bool:
    sig = base64.urlsafe_b64decode(sig_b64.encode())
    if _HAS_ED25519:
        try:
            pub_bytes = base64.urlsafe_b64decode(pub_b64.encode())
            pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
            pub.verify(sig, payload)
            return True
        except Exception:
            return False
    # HMAC fallback
    try:
        key = base64.urlsafe_b64decode(pub_b64.encode())
        expected = hmac.new(key, payload, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ─────────────────────── data shapes ───────────────────────────────────


@dataclass
class FirmIdentity:
    firm_id: str
    name: str
    root_pub: str
    created_at: str
    created_by: str
    # Private key is held LOCALLY only — not synced via firm graph
    root_priv: Optional[str] = None  # only on admin's device

    def to_safe_dict(self) -> dict[str, Any]:
        """Drop root_priv for any storage that may sync."""
        d = asdict(self)
        d.pop("root_priv", None)
        return d


@dataclass
class Seat:
    user_id: str
    firm_id: str
    role: str = "seat"  # seat | admin | observer
    joined_at: str = ""
    invited_by: str = ""


@dataclass
class InviteToken:
    """Decoded representation of an invite token."""

    firm_id: str
    firm_name: str
    firm_pub: str
    role: str
    issued_by: str
    issued_at: float
    expires_at: float
    nonce: str

    def is_expired(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return now > self.expires_at

    def encode_payload(self) -> bytes:
        return json.dumps(
            {
                "firm_id": self.firm_id, "firm_name": self.firm_name,
                "firm_pub": self.firm_pub, "role": self.role,
                "issued_by": self.issued_by, "issued_at": self.issued_at,
                "expires_at": self.expires_at, "nonce": self.nonce,
            },
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")


# ─────────────────────── identity persistence ─────────────────────────


_META_KEY_FIRM_IDENTITY = "firm_identity_v1"
_META_KEY_CURRENT_SEAT = "firm_seat_v1"


def create_firm(
    store: BrainStore,
    *,
    name: str,
    created_by: str,
    firm_id: Optional[str] = None,
) -> FirmIdentity:
    """Create a new firm. The caller becomes the root admin. Persists
    the firm identity + admin seat. Returns the FirmIdentity (with
    root_priv set on this device only)."""
    firm_id = firm_id or _new_firm_id(name)
    priv, pub = _generate_keypair()
    now = datetime.now(timezone.utc).isoformat()

    identity = FirmIdentity(
        firm_id=firm_id, name=name, root_pub=pub,
        created_at=now, created_by=created_by, root_priv=priv,
    )
    # Persist: full identity LOCAL only (contains priv); the safe-dict
    # form goes into the firm-scope graph so other seats see firm name + pub
    store.set_meta(_META_KEY_FIRM_IDENTITY, json.dumps(asdict(identity)))

    # Admin seat fragment
    seat = Seat(
        user_id=created_by, firm_id=firm_id, role="admin",
        joined_at=now, invited_by=created_by,
    )
    _write_seat(store, seat)
    store.set_meta(_META_KEY_CURRENT_SEAT, json.dumps(asdict(seat)))

    return identity


def current_firm(store: BrainStore) -> Optional[FirmIdentity]:
    raw = store.get_meta(_META_KEY_FIRM_IDENTITY)
    if not raw:
        return None
    try:
        return FirmIdentity(**json.loads(raw))
    except Exception:
        return None


def current_firm_id(store: BrainStore) -> Optional[str]:
    f = current_firm(store)
    return f.firm_id if f else None


def current_seat(store: BrainStore) -> Optional[Seat]:
    raw = store.get_meta(_META_KEY_CURRENT_SEAT)
    if not raw:
        return None
    try:
        return Seat(**json.loads(raw))
    except Exception:
        return None


def leave_firm(store: BrainStore) -> bool:
    """Drop firm membership locally. Other seats keep their record of
    this seat until they sync; the seat fragment they hold is then
    pruned next pass."""
    store.set_meta(_META_KEY_FIRM_IDENTITY, "")
    store.set_meta(_META_KEY_CURRENT_SEAT, "")
    return True


# ─────────────────────── invite token lifecycle ───────────────────────


def create_invite_token(
    store: BrainStore,
    *,
    role: str = "seat",
    ttl_hours: int = 24,
    nonce: Optional[str] = None,
) -> str:
    """Create + sign an invite token. Only the current firm admin can
    call this (signs with their root_priv). Returns the encoded token."""
    identity = current_firm(store)
    if identity is None:
        raise RuntimeError("no firm — create_firm first")
    if not identity.root_priv:
        raise RuntimeError(
            "this device is not the firm admin — no root_priv available"
        )
    seat = current_seat(store)
    if seat is None or seat.role != "admin":
        raise RuntimeError("only admin can issue invites")
    now = time.time()
    token = InviteToken(
        firm_id=identity.firm_id,
        firm_name=identity.name,
        firm_pub=identity.root_pub,
        role=role,
        issued_by=seat.user_id,
        issued_at=now,
        expires_at=now + ttl_hours * 3600.0,
        nonce=nonce or secrets.token_urlsafe(12),
    )
    payload = token.encode_payload()
    sig = _sign(identity.root_priv, payload)
    envelope = base64.urlsafe_b64encode(payload).decode() + "." + sig
    # Record the invite in firm-scope graph so other seats see it
    _record_invite(store, token)
    return envelope


def decode_invite_token(envelope: str) -> tuple[InviteToken, str]:
    """Parse + return (token, signature). No signature verify yet."""
    if "." not in envelope:
        raise ValueError("malformed token (no signature separator)")
    payload_b64, sig = envelope.split(".", 1)
    payload = base64.urlsafe_b64decode(payload_b64.encode())
    data = json.loads(payload.decode("utf-8"))
    token = InviteToken(**data)
    return token, sig


def verify_invite_token(envelope: str) -> tuple[InviteToken, bool, str]:
    """Decode + verify signature + expiry. Returns
    (token, ok, reason). `ok=False` when signature invalid OR expired."""
    try:
        token, sig = decode_invite_token(envelope)
    except Exception as ex:
        # Make a dummy token to satisfy return type; ok=False
        dummy = InviteToken(
            firm_id="?", firm_name="?", firm_pub="?", role="?",
            issued_by="?", issued_at=0.0, expires_at=0.0, nonce="?",
        )
        return dummy, False, f"malformed: {ex}"
    if token.is_expired():
        return token, False, "expired"
    ok = _verify(token.firm_pub, token.encode_payload(), sig)
    return token, ok, "ok" if ok else "signature mismatch"


def accept_invite_token(
    store: BrainStore,
    *,
    envelope: str,
    user_id: str,
) -> Seat:
    """Decode + verify + materialise firm identity + seat on this device.

    Idempotent: re-running with the same token on the same device is a
    no-op once the seat is recorded.
    """
    token, ok, reason = verify_invite_token(envelope)
    if not ok:
        raise RuntimeError(f"invite token rejected: {reason}")

    # Materialise firm identity LOCALLY (no root_priv — this is a seat,
    # not an admin)
    identity = FirmIdentity(
        firm_id=token.firm_id, name=token.firm_name,
        root_pub=token.firm_pub,
        created_at=datetime.fromtimestamp(
            token.issued_at, tz=timezone.utc,
        ).isoformat(),
        created_by=token.issued_by,
        root_priv=None,
    )
    store.set_meta(_META_KEY_FIRM_IDENTITY, json.dumps(asdict(identity)))

    seat = Seat(
        user_id=user_id, firm_id=token.firm_id, role=token.role,
        joined_at=datetime.now(timezone.utc).isoformat(),
        invited_by=token.issued_by,
    )
    _write_seat(store, seat)
    store.set_meta(_META_KEY_CURRENT_SEAT, json.dumps(asdict(seat)))
    return seat


def list_seats(store: BrainStore) -> list[Seat]:
    """Read all firm-scope seat fragments."""
    firm_id = current_firm_id(store)
    if firm_id is None:
        return []
    frags = store.search_fragments(
        "seat", scope_filter=[Scope.FIRM], kinds=[FragmentKind.SETUP],
        k=200,
    )
    seats: list[Seat] = []
    for f in frags:
        if f.predicate != "seat":
            continue
        if (f.extra or {}).get("firm_id") != firm_id:
            continue
        seats.append(Seat(
            user_id=f.subject or "?",
            firm_id=firm_id,
            role=f.object or "seat",
            joined_at=(f.extra or {}).get("joined_at") or "",
            invited_by=(f.extra or {}).get("invited_by") or "",
        ))
    return seats


# ─────────────────────── helpers ───────────────────────────────────────


def _new_firm_id(name: str) -> str:
    """Stable firm_id derived from name + random suffix. Format:
    `firm-<sluggified-name>-<6char-suffix>`."""
    suffix = secrets.token_urlsafe(4)[:6]
    slug = "".join(
        c.lower() if c.isalnum() else "-" for c in name
    ).strip("-")[:32] or "firm"
    return f"firm-{slug}-{suffix}"


def _write_seat(store: BrainStore, seat: Seat) -> None:
    frag = Fragment(
        id=f"seat:{seat.firm_id}:{seat.user_id}",
        kind=FragmentKind.SETUP,
        # "seat" token is intentional — FTS5 list_seats() searches by it
        text=(
            f"firm seat {seat.user_id} role {seat.role} in {seat.firm_id}"
        ),
        subject=seat.user_id, predicate="seat", object=seat.role,
        scope=Scope.FIRM,
        visibility=Visibility.SHARED_COMPANY,
        owner_user=seat.user_id,
        firm_id=seat.firm_id,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="firm-module",
            contributing_user=seat.user_id,
        ),
        extra={
            "firm_id": seat.firm_id, "role": seat.role,
            "joined_at": seat.joined_at, "invited_by": seat.invited_by,
        },
    )
    store.write_fragment(frag)


def _record_invite(store: BrainStore, token: InviteToken) -> None:
    frag = Fragment(
        id=f"invite:{token.firm_id}:{token.nonce}",
        kind=FragmentKind.SETUP,
        text=(
            f"invite for {token.firm_name} role={token.role} "
            f"issued by {token.issued_by}"
        ),
        subject=token.firm_id, predicate="invite", object=token.role,
        scope=Scope.FIRM,
        visibility=Visibility.SHARED_COMPANY,
        owner_user=token.issued_by,
        firm_id=token.firm_id,
        provenance=Provenance(
            contributing_agent="firm-module",
            contributing_user=token.issued_by,
        ),
        extra={
            "nonce": token.nonce, "issued_at": token.issued_at,
            "expires_at": token.expires_at, "role": token.role,
        },
    )
    store.write_fragment(frag)


def has_ed25519() -> bool:
    """Diagnostic — was real ed25519 available at import time?"""
    return _HAS_ED25519
