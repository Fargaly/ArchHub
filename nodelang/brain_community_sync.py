"""The Community Brain transport: what may reach the community goes out, what
comes back lands in quarantine.

Founder decision 2026-09-29: every account joins one Community Brain (the cloud
records the membership at first sign-in) and shares by default. What leaves is
decided by the governance layer alone: a memory is offered only while
``may_release(..., to_lake="community")`` allows it -- a community-ceiling class
(published skills, behaviour patterns) on a community stratum, with the gates
granted. Unclassified memories are sealed and never appear here; neither does
any firm- or client-class fact.

What comes back is never merged. Another member's community row is handed to
``cell_brain_community.receive`` and stays QUARANTINED until judged; this
device's own rows are recognised by id and skipped.

One POST per call, against the unchanged ``/v1/brain/sync`` contract. The
transport is injected (``post(payload) -> response``) and the caller keeps the
cursor, so no network call and no token read happen here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .brain_cloud_sync import encode_hlc
from .cell_brain_community import receive, subscribe, subscriptions
from .cell_brain_governance import may_release
from .cell_brain_memory import memories
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

COMMUNITY_LAKE = "community"
PEER_PREFIX = "app:brain:community:peer:"


@dataclass(frozen=True, slots=True)
class CommunityCursor:
    """``since_hlc``: the server's pull cursor. ``shared``: sorted (row id, hlc)
    pairs this device has offered -- its own rows, never re-received."""

    since_hlc: str = ""
    shared: tuple = ()


@dataclass(frozen=True, slots=True)
class CommunityReport:
    offered: int
    withdrawn: int
    quarantined: int
    cursor: CommunityCursor


def peer_root(community_id):
    return PEER_PREFIX + community_id


def join(store, community_id):
    """Hear from the community: its peer root, subscribed once."""
    if not isinstance(community_id, str) or not community_id.strip():
        raise InvalidCell("a community has an id")
    root = peer_root(community_id.strip())
    snapshot = store.snapshot()
    if root not in snapshot.cells:
        store.commit(snapshot.revision, create=(
            Cell(root, NULL_CELL_ID, NULL_CELL_ID, community_id.strip().encode("utf-8")),))
    if root not in subscriptions(store.snapshot()):
        subscribe(store, root)
    return root


def row_id(owner_user, fragment_id):
    """One community row per (account, memory): ids never collide across members."""
    return "community:" + hashlib.sha256(
        ("%s\n%s" % (owner_user, fragment_id)).encode("utf-8")).hexdigest()[:40]


def _outgoing(snapshot, *, session_root, owner_user, firm_root, community_id, shared):
    rows, offered = [], {}
    for memory in memories(snapshot, session_root=session_root):
        if not may_release(snapshot, session_root=session_root, fragment_id=memory.fragment_id,
                           to_lake=COMMUNITY_LAKE, firm_root=firm_root).allowed:
            continue
        rid = row_id(owner_user, memory.fragment_id)
        hlc = encode_hlc(memory.text_clock, memory.text_origin)
        offered[rid] = hlc
        if shared.get(rid) == hlc:
            continue
        rows.append({"id": rid, "kind": memory.kind, "text": memory.text, "scope": "community",
                     "visibility": "shared", "confidence": memory.confidence,
                     "hlc": hlc, "extra": {"community_id": community_id}})
    withdrawn = []
    for rid, hlc in shared.items():
        if rid in offered:
            continue
        # No longer releasable (forgotten, revoked, reclassified): blank the row.
        clock = int(hlc.split(".", 1)[0]) + 1
        withdrawn.append({"id": rid, "kind": "fact", "text": "", "scope": "community",
                          "visibility": "shared", "hlc": encode_hlc(clock, "withdrawn"),
                          "valid_until": "1970-01-01T00:00:00Z",
                          "extra": {"community_id": community_id}})
    return rows, withdrawn, offered


def community_sync_once(store, *, session_root, owner_user, firm_root, community_id,
                        cursor, post):
    """Offer what may reach the community, withdraw what may no longer, and
    quarantine what other members shared."""
    if not isinstance(cursor, CommunityCursor):
        raise InvalidCell("community sync needs its cursor")
    peer = join(store, community_id)
    shared = dict(cursor.shared)
    rows, withdrawn, offered = _outgoing(
        store.snapshot(), session_root=session_root, owner_user=owner_user,
        firm_root=firm_root, community_id=community_id, shared=shared)
    # Always the whole community read-set: the founder review admits a version
    # without changing its hlc, so a cursor would never see it arrive. receive()
    # answers a claim already held from the record, so a full pull adds nothing twice.
    response = post({"since_hlc": "",
                     "delta": {"fragments": rows + withdrawn, "wiring": []}})
    if not isinstance(response, dict) or not isinstance(response.get("new_hlc"), str):
        raise InvalidCell("the sync server answered without a cursor")
    rejected = {str(item.get("id")) for item in (response.get("rejected") or [])
                if isinstance(item, dict)}
    merged = response.get("merged") if isinstance(response.get("merged"), dict) else {}
    quarantined = 0
    for row in merged.get("fragments") or []:
        if not isinstance(row, dict) or row.get("scope") != "community":
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if extra.get("community_id") != community_id or row.get("id") in offered:
            continue
        if row.get("valid_until") or not isinstance(row.get("text"), str) or not row["text"].strip():
            continue
        try:
            receive(store, peer_root=peer, claim=row["text"])
        except InvalidCell:
            continue  # already received, or it looks like a secret: never applied
        quarantined += 1
    kept = {rid: hlc for rid, hlc in offered.items() if rid not in rejected}
    return CommunityReport(len(rows), len(withdrawn), quarantined,
                           CommunityCursor(response["new_hlc"], tuple(sorted(kept.items()))))


__all__ = ["CommunityCursor", "CommunityReport", "community_sync_once", "join",
           "peer_root", "row_id"]