"""Sending to peers and taking from them, through the same two laws.

`community_fanout_export` and `community_fanout_apply` were two halves of one
mistake: export read the store directly, and apply wrote into it directly. So a
peer could receive a raw fact, and a peer could write one.

Export here can only see what federation already approved for sharing, which is
a redaction the owner chose. Apply cannot write at all -- it hands everything to
the community quarantine, so incoming still has to be judged before it is
visible. The outbox is derived, never queued, so nothing can sit in it that the
owner has not shared.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_brain_community import receive
from .cell_brain_federation import firm_members, visible_to
from .cell_brain_secrets import assert_not_a_secret
from .universal_cell import InvalidCell


@dataclass(frozen=True, slots=True)
class Card:
    fact_root: str
    firm_root: str
    redaction: str


def outbox(snapshot, firm_root):
    """What this firm would send. Derived from shares, never queued."""
    members = firm_members(snapshot, firm_root)
    if not members:
        raise InvalidCell("a firm with no members has nothing to send")
    seen = {}
    for member in members:
        for share in visible_to(snapshot, member):
            if share.firm_root != firm_root:
                continue
            seen[share.fact_root] = Card(
                share.fact_root, share.firm_root, share.redaction)
    return tuple(sorted(seen.values(), key=lambda c: c.fact_root))


def fanout_export(snapshot, firm_root):
    """Only redactions cross. A raw fact cannot be exported at all."""
    cards = outbox(snapshot, firm_root)
    for card in cards:
        assert_not_a_secret(card.redaction, "exported redaction")
    return tuple(card.redaction for card in cards)


def fanout_apply(store, *, peer_root, claims):
    """Take a peer's cards into QUARANTINE. This never writes a fact."""
    landed = []
    for claim in claims:
        landed.append(receive(store, peer_root=peer_root, claim=claim))
    return tuple(landed)
