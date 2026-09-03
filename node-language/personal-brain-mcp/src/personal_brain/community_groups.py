"""Multi-device community — create / join-code / join / list / leave.

AgDR-0044 multi-device extension (founder goal 2026-06-01: "create a
community" + "join it from a second device").

WHY A NEW MODULE (ONE-SYSTEM-PLAN-BEFORE-BUILD check):
  `community.py` already exists, but it is the FEDERATION tier — it records
  which *other firms'* ActivityPub outboxes the local brain subscribes to
  (cross-org pattern sharing, scope=COMMUNITY imports). That is NOT a
  multi-device group the founder's own laptop can join. The names collide
  ("community") but the tiers are different:

    community.py          → subscribe to a PEER FIRM's outbox (read-only pull
                            of DP-noised patterns; no shared writable scope)
    community_groups.py   → THIS module. A multi-device community the founder
                            OWNS: create it, hand a second device a join-code,
                            both devices then converge COMMUNITY-scope
                            fragments through the shared transport.

  This module deliberately REUSES `firm.py`'s proven token design (signed
  base64url envelope, ed25519-or-HMAC, TTL, offline verify) rather than
  minting a parallel crypto layer — the only new concept is that the
  join-code also carries the TRANSPORT CONFIG (owned Speckle server URL or
  cloud relay) so the joining device knows WHERE to sync, not just WHICH
  community.

Persistence model (all daemon-mediated brain writes — reversible):
  * `community_membership_v1` row in brain_meta:
        JSON {community_id, name, role, owner_pub, transport, joined_at,
              owner_priv?}  (owner_priv ONLY on the creator's device)
  * one Fragment per community member (kind=setup, scope=COMMUNITY,
    predicate='community_member', subject=<device/user id>, object=<role>)
    — these sync via the COMMUNITY-scope SyncWorker so every device sees
    the roster.
  * one Fragment per community itself (kind=setup, scope=COMMUNITY,
    predicate='community', subject=<community_id>) so brain.community_list
    has something to enumerate even before any peer joins.

Join-code format (mirrors firm.InviteToken):
    base64url(JSON{community_id, name, owner_pub, role, transport,
                   issued_by, issued_at, expires_at, nonce}) + "." + sig
The joining device decodes, verifies signature + expiry OFFLINE (the
owner_pub travels in the payload), then materialises membership + writes
its own member fragment. No central server is required to JOIN — only to
CONVERGE (that is the transport's job, wired in sync_worker.py).

Public surface:
    from personal_brain.community_groups import (
        create_community, create_join_code, decode_join_code,
        verify_join_code, join_community, current_community,
        list_communities, list_members, leave_community,
        TransportConfig, Community, CommunityMember, JoinCode,
    )
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Reuse the firm crypto primitives verbatim — DO NOT fork a second signer.
from .firm import _generate_keypair, _sign, _verify, has_ed25519  # noqa: F401
from .models import (
    Confidence,
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    Visibility,
)
from .storage import BrainStore


_META_KEY_MEMBERSHIP = "community_membership_v1"


# ─────────────────────── transport config ──────────────────────────────


@dataclass
class TransportConfig:
    """Where a community's devices converge their COMMUNITY-scope brain.

    Two real backends, no external account required for either:
      * kind="cloud_relay"  — POST deltas to ArchHub's /v1/brain/sync replica
                              (the existing cloud_backend). `base_url` is the
                              relay; auth is the user's own bearer token.
      * kind="speckle"      — the user's OWNED Speckle server (speckle_server
                              .start_local). `base_url` = http://localhost:3000
                              by default; no SaaS account.
      * kind="disk"         — local JSON snapshot only (single-device / shared
                              folder like Dropbox/OneDrive). The offline default
                              per ARCHITECTURE LOCK Direction-X.
    """

    kind: str = "disk"  # disk | cloud_relay | speckle
    base_url: str = ""
    # Optional opaque hint the joining device shows the user (e.g. the
    # owned-server install state). Never carries a secret.
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "base_url": self.base_url, "note": self.note}

    @classmethod
    def from_dict(cls, d: Optional[dict[str, Any]]) -> "TransportConfig":
        d = d or {}
        return cls(
            kind=str(d.get("kind") or "disk"),
            base_url=str(d.get("base_url") or ""),
            note=str(d.get("note") or ""),
        )


# ─────────────────────── data shapes ───────────────────────────────────


@dataclass
class Community:
    community_id: str
    name: str
    owner_pub: str
    created_at: str
    created_by: str
    transport: TransportConfig = field(default_factory=TransportConfig)
    role: str = "member"  # owner | member
    # Private key held LOCAL only on the creator's device — never synced,
    # never travels in a join-code.
    owner_priv: Optional[str] = None

    def to_safe_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("owner_priv", None)
        d["transport"] = self.transport.to_dict()
        return d


@dataclass
class CommunityMember:
    member_id: str  # device/user id
    community_id: str
    role: str = "member"
    joined_at: str = ""
    invited_by: str = ""


@dataclass
class JoinCode:
    """Decoded representation of a community join-code."""

    community_id: str
    name: str
    owner_pub: str
    role: str
    transport: dict[str, Any]
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
                "community_id": self.community_id,
                "name": self.name,
                "owner_pub": self.owner_pub,
                "role": self.role,
                "transport": self.transport,
                "issued_by": self.issued_by,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "nonce": self.nonce,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


# ─────────────────────── id helper ─────────────────────────────────────


def _new_community_id(name: str) -> str:
    """Stable id: `comm-<slug>-<6char>`."""
    suffix = secrets.token_urlsafe(4)[:6]
    slug = "".join(
        c.lower() if c.isalnum() else "-" for c in name
    ).strip("-")[:32] or "community"
    return f"comm-{slug}-{suffix}"


# ─────────────────────── create ────────────────────────────────────────


def create_community(
    store: BrainStore,
    *,
    name: str,
    created_by: str,
    transport: Optional[TransportConfig] = None,
    community_id: Optional[str] = None,
) -> Community:
    """Create a new multi-device community. The caller becomes the owner.

    Persists:
      * membership (with owner_priv) to brain_meta — LOCAL only.
      * a COMMUNITY-scope `community` fragment (the group itself) so
        brain.community_list enumerates it.
      * a COMMUNITY-scope `community_member` fragment for the owner.

    Both fragments are scope=COMMUNITY, so the COMMUNITY-scope SyncWorker
    will push them to the shared transport for any device that joins.
    """
    community_id = community_id or _new_community_id(name)
    priv, pub = _generate_keypair()
    now = datetime.now(timezone.utc).isoformat()
    tconf = transport or TransportConfig()

    community = Community(
        community_id=community_id,
        name=name,
        owner_pub=pub,
        created_at=now,
        created_by=created_by,
        transport=tconf,
        role="owner",
        owner_priv=priv,
    )
    # Membership (with priv) is LOCAL only.
    store.set_meta(_META_KEY_MEMBERSHIP, json.dumps(_membership_blob(community)))

    # The community itself — a syncable record so the list is non-empty.
    _write_community_fragment(store, community)
    # Owner's member fragment.
    _write_member_fragment(
        store,
        CommunityMember(
            member_id=created_by, community_id=community_id, role="owner",
            joined_at=now, invited_by=created_by,
        ),
    )
    return community


def _membership_blob(c: Community) -> dict[str, Any]:
    return {
        "community_id": c.community_id,
        "name": c.name,
        "owner_pub": c.owner_pub,
        "created_at": c.created_at,
        "created_by": c.created_by,
        "transport": c.transport.to_dict(),
        "role": c.role,
        "owner_priv": c.owner_priv,  # only on the owner's device
    }


# ─────────────────────── join-code lifecycle ───────────────────────────


def create_join_code(
    store: BrainStore,
    *,
    role: str = "member",
    ttl_hours: int = 168,  # 7 days — communities are longer-lived than firm invites
    nonce: Optional[str] = None,
) -> str:
    """Create + sign a join-code for the CURRENT community. Only the owner
    (the device holding owner_priv) can issue one. The code carries the
    transport config so the joining device knows where to converge."""
    community = current_community(store)
    if community is None:
        raise RuntimeError("no community — create_community first")
    if not community.owner_priv:
        raise RuntimeError(
            "this device is not the community owner — no owner_priv available"
        )
    now = time.time()
    code = JoinCode(
        community_id=community.community_id,
        name=community.name,
        owner_pub=community.owner_pub,
        role=role,
        transport=community.transport.to_dict(),
        issued_by=community.created_by,
        issued_at=now,
        expires_at=now + ttl_hours * 3600.0,
        nonce=nonce or secrets.token_urlsafe(12),
    )
    payload = code.encode_payload()
    sig = _sign(community.owner_priv, payload)
    envelope = base64.urlsafe_b64encode(payload).decode() + "." + sig
    return envelope


def join_url(envelope: str) -> str:
    """A copy-paste URL a second ArchHub instance can open to join.

    The scheme `archhub://community/join?code=<envelope>` is handled by the
    desktop single-instance URL handler; the bare envelope also works when
    pasted into Settings → Brain → Join a community. We return the URL form
    because the founder asked for "a join code/URL"."""
    return f"archhub://community/join?code={envelope}"


def decode_join_code(envelope: str) -> tuple[JoinCode, str]:
    """Parse → (code, signature). No verification yet. Accepts either the
    bare envelope or the `archhub://community/join?code=...` URL form."""
    env = _strip_url(envelope)
    if "." not in env:
        raise ValueError("malformed join-code (no signature separator)")
    payload_b64, sig = env.split(".", 1)
    payload = base64.urlsafe_b64decode(payload_b64.encode())
    data = json.loads(payload.decode("utf-8"))
    code = JoinCode(**data)
    return code, sig


def _strip_url(envelope: str) -> str:
    env = (envelope or "").strip()
    marker = "code="
    if marker in env:
        env = env.split(marker, 1)[1]
    return env.strip()


def verify_join_code(envelope: str) -> tuple[JoinCode, bool, str]:
    """Decode + verify signature + expiry. Returns (code, ok, reason).
    ok=False on malformed / tampered / expired."""
    try:
        code, sig = decode_join_code(envelope)
    except Exception as ex:
        dummy = JoinCode(
            community_id="?", name="?", owner_pub="?", role="?",
            transport={}, issued_by="?", issued_at=0.0, expires_at=0.0,
            nonce="?",
        )
        return dummy, False, f"malformed: {ex}"
    if code.is_expired():
        return code, False, "expired"
    ok = _verify(code.owner_pub, code.encode_payload(), sig)
    return code, ok, "ok" if ok else "signature mismatch"


def join_community(
    store: BrainStore,
    *,
    envelope: str,
    member_id: str,
) -> Community:
    """Decode + verify a join-code, then materialise community membership
    on THIS device. Writes a COMMUNITY-scope member fragment so the owner
    (and every other device) sees the new member after the next sync.

    Idempotent: re-running with the same code on the same device just
    refreshes the member fragment.
    """
    code, ok, reason = verify_join_code(envelope)
    if not ok:
        raise RuntimeError(f"join-code rejected: {reason}")

    tconf = TransportConfig.from_dict(code.transport)
    now = datetime.now(timezone.utc).isoformat()
    community = Community(
        community_id=code.community_id,
        name=code.name,
        owner_pub=code.owner_pub,
        created_at=datetime.fromtimestamp(
            code.issued_at, tz=timezone.utc,
        ).isoformat(),
        created_by=code.issued_by,
        transport=tconf,
        role=code.role,
        owner_priv=None,  # a joiner is NOT the owner
    )
    store.set_meta(_META_KEY_MEMBERSHIP, json.dumps(_membership_blob(community)))

    # Re-assert the community record locally (so this device's list shows it
    # immediately, before the first inbound sync) + write our member row.
    _write_community_fragment(store, community)
    _write_member_fragment(
        store,
        CommunityMember(
            member_id=member_id, community_id=code.community_id,
            role=code.role, joined_at=now, invited_by=code.issued_by,
        ),
    )
    return community


# ─────────────────────── read / leave ──────────────────────────────────


def current_community(store: BrainStore) -> Optional[Community]:
    raw = store.get_meta(_META_KEY_MEMBERSHIP)
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None
    if not d.get("community_id"):
        return None
    return Community(
        community_id=d["community_id"],
        name=d.get("name") or "",
        owner_pub=d.get("owner_pub") or "",
        created_at=d.get("created_at") or "",
        created_by=d.get("created_by") or "",
        transport=TransportConfig.from_dict(d.get("transport")),
        role=d.get("role") or "member",
        owner_priv=d.get("owner_priv"),
    )


def current_community_id(store: BrainStore) -> Optional[str]:
    c = current_community(store)
    return c.community_id if c else None


def list_communities(store: BrainStore) -> list[Community]:
    """Enumerate every community this device knows about — from the synced
    COMMUNITY-scope `community` fragments. Today a device belongs to at most
    one community (the membership blob); but the roster of community records
    can include peers' once federation lands, so we enumerate the fragments
    rather than just the membership blob. The membership blob's transport +
    role override the synced record for the community this device joined.
    """
    frags = store.search_fragments(
        "community", scope_filter=[Scope.COMMUNITY],
        kinds=[FragmentKind.SETUP], k=200,
    )
    mine = current_community(store)
    out: list[Community] = []
    seen: set[str] = set()
    for f in frags:
        if f.predicate != "community":
            continue
        cid = f.subject or (f.extra or {}).get("community_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        extra = f.extra or {}
        out.append(Community(
            community_id=cid,
            name=extra.get("name") or "",
            owner_pub=extra.get("owner_pub") or "",
            created_at=extra.get("created_at") or "",
            created_by=extra.get("created_by") or "",
            transport=TransportConfig.from_dict(extra.get("transport")),
            role=(mine.role if (mine and mine.community_id == cid) else "member"),
            owner_priv=None,
        ))
    # Ensure the device's own community is present even if the fragment
    # search missed it (e.g. FTS quirk) — never report empty when joined.
    if mine and mine.community_id not in seen:
        out.append(mine)
    return out


def list_members(store: BrainStore, community_id: Optional[str] = None) -> list[CommunityMember]:
    """Read all member fragments for a community (synced via COMMUNITY
    scope). Defaults to the current community."""
    cid = community_id or current_community_id(store)
    if cid is None:
        return []
    frags = store.search_fragments(
        "community_member", scope_filter=[Scope.COMMUNITY],
        kinds=[FragmentKind.SETUP], k=500,
    )
    members: list[CommunityMember] = []
    seen: set[str] = set()
    for f in frags:
        if f.predicate != "community_member":
            continue
        extra = f.extra or {}
        if extra.get("community_id") != cid:
            continue
        mid = f.subject or extra.get("member_id") or "?"
        if mid in seen:
            continue
        seen.add(mid)
        members.append(CommunityMember(
            member_id=mid,
            community_id=cid,
            role=f.object or extra.get("role") or "member",
            joined_at=extra.get("joined_at") or "",
            invited_by=extra.get("invited_by") or "",
        ))
    return members


def leave_community(store: BrainStore) -> bool:
    """Drop community membership on this device. The member fragment is
    tombstoned locally; other devices prune it after their next sync."""
    c = current_community(store)
    store.set_meta(_META_KEY_MEMBERSHIP, "")
    if c is not None:
        # Tombstone our member fragment so the roster converges.
        try:
            store.delete_fragment(_member_frag_id(c.created_by, c.community_id))
        except Exception:
            pass
    return True


def set_transport(store: BrainStore, transport: TransportConfig) -> Optional[Community]:
    """Update the current community's transport config on this device.
    Used to point an existing community at a freshly-started owned server."""
    c = current_community(store)
    if c is None:
        return None
    c.transport = transport
    store.set_meta(_META_KEY_MEMBERSHIP, json.dumps(_membership_blob(c)))
    _write_community_fragment(store, c)
    return c


# ─────────────────────── fragment writers ──────────────────────────────


def _community_frag_id(community_id: str) -> str:
    return f"community:{community_id}"


def _member_frag_id(member_id: str, community_id: str) -> str:
    return f"community-member:{community_id}:{member_id}"


def _write_community_fragment(store: BrainStore, c: Community) -> None:
    frag = Fragment(
        id=_community_frag_id(c.community_id),
        kind=FragmentKind.SETUP,
        # "community" token is intentional — FTS5 list_communities() greps it.
        text=f"community {c.name} ({c.community_id}) owner {c.created_by}",
        subject=c.community_id, predicate="community", object=c.role,
        scope=Scope.COMMUNITY,
        visibility=Visibility.SHARED_PUBLIC,
        owner_user=c.created_by,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="community-groups",
            contributing_user=c.created_by,
        ),
        extra={
            "community_id": c.community_id,
            "name": c.name,
            "owner_pub": c.owner_pub,
            "created_at": c.created_at,
            "created_by": c.created_by,
            "transport": c.transport.to_dict(),
        },
    )
    store.write_fragment(frag)


def _write_member_fragment(store: BrainStore, m: CommunityMember) -> None:
    frag = Fragment(
        id=_member_frag_id(m.member_id, m.community_id),
        kind=FragmentKind.SETUP,
        # "community_member" token is intentional — list_members() greps it.
        text=(
            f"community_member {m.member_id} role {m.role} "
            f"in {m.community_id}"
        ),
        subject=m.member_id, predicate="community_member", object=m.role,
        scope=Scope.COMMUNITY,
        visibility=Visibility.SHARED_PUBLIC,
        owner_user=m.member_id,
        confidence=Confidence.EXTRACTED,
        provenance=Provenance(
            contributing_agent="community-groups",
            contributing_user=m.member_id,
        ),
        extra={
            "community_id": m.community_id,
            "member_id": m.member_id,
            "role": m.role,
            "joined_at": m.joined_at,
            "invited_by": m.invited_by,
        },
    )
    store.write_fragment(frag)
