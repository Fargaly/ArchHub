"""Explicit graph subscriptions from durable reactions to durable signals.

The bridge has no callback configuration hidden in process memory. Each route is
an ordinary Cell relation holding its reaction, observer, policy decision,
trust, visibility, lifecycle, state, and restart cursor.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

from .cell_attention import AttentionProtocol, record_signal
from .cell_authorization import AuthorizationDecision
from .cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_member,
    read_relation,
    rewire_incidence,
)
from .cell_reactions import ReactionProtocol, reaction_events
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


@dataclass(frozen=True, slots=True)
class ReactionSubscriptionProjection:
    root_id: str
    reaction_root: str
    observer_root: str
    trust_root: str
    sensitivity_root: str
    audience_root: str
    lifecycle_root: str
    action_root: str
    authority_root: str
    rule_roots: tuple[str, ...]
    cursor_root: str
    cursor: int
    state_root: str
    state_incidence: str


def _for_role(members, role_root: str):
    return tuple(member for member in members if member.role_id == role_root)


def _one(members, role_root: str, label: str):
    found = _for_role(members, role_root)
    if len(found) != 1:
        raise InvalidCell("reaction subscription requires exactly one %s" % label)
    return found[0]


def _roots(snapshot: Snapshot, values: Iterable[str], label: str) -> None:
    missing = tuple(value for value in values if value not in snapshot.cells)
    if missing:
        raise InvalidCell("%s references missing roots: %r" % (label, missing))


def read_reaction_subscription(
    snapshot: Snapshot,
    attention: AttentionProtocol,
    subscription_root: str,
) -> ReactionSubscriptionProjection:
    members = read_relation(snapshot, subscription_root, budget=100_000)
    cursor_root = _one(
        members, attention.role("subscription-cursor"), "cursor"
    ).participant_id
    state = _one(members, attention.role("subscription-state"), "state")
    try:
        cursor = int(snapshot.cells[cursor_root].atom.decode("ascii"))
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCell("reaction subscription cursor is not an integer") from exc
    return ReactionSubscriptionProjection(
        subscription_root,
        _one(members, attention.role("subscription-reaction"), "reaction").participant_id,
        _one(members, attention.role("subscription-observer"), "observer").participant_id,
        _one(members, attention.role("subscription-trust"), "trust").participant_id,
        _one(members, attention.role("subscription-sensitivity"), "sensitivity").participant_id,
        _one(members, attention.role("subscription-audience"), "audience").participant_id,
        _one(members, attention.role("subscription-lifecycle"), "lifecycle").participant_id,
        _one(members, attention.role("subscription-action"), "action").participant_id,
        _one(members, attention.role("subscription-authority"), "authority").participant_id,
        tuple(
            member.participant_id
            for member in members
            if member.role_id == attention.role("subscription-rule")
        ),
        cursor_root,
        cursor,
        state.participant_id,
        state.incidence_id,
    )


def build_reaction_subscription(
    store: CellStore,
    attention: AttentionProtocol,
    reaction: ReactionProtocol,
    decision: AuthorizationDecision,
    *,
    subscription_id: str,
    reaction_root: str,
    observer_root: str,
    trust_root: str,
    sensitivity_root: str,
    audience_root: str,
    lifecycle_root: str,
) -> ReactionSubscriptionProjection:
    """Create one authorized, visible route from reaction events to signals."""
    if not decision.allowed:
        raise PermissionError("denied reaction subscriptions cannot be built")
    if decision.subject_root != observer_root or decision.object_root != reaction_root:
        raise PermissionError("reaction subscription does not match authorization")
    snapshot = store.snapshot()
    if subscription_id in snapshot.cells:
        raise InvalidCell("reaction subscription root already exists")
    # This validates that the target is a readable reaction manifest.
    reaction_events(snapshot, reaction, reaction_root)
    _roots(
        snapshot,
        (
            observer_root,
            trust_root,
            sensitivity_root,
            audience_root,
            lifecycle_root,
            decision.action_root,
            decision.policy_root,
            *decision.determining_rule_roots,
        ),
        "reaction subscription",
    )
    cursor_root = subscription_id + ":cursor"
    relation = compose_relation_cells(
        (
            (attention.role("subscription-reaction"), reaction_root),
            (attention.role("subscription-observer"), observer_root),
            (attention.role("subscription-trust"), trust_root),
            (attention.role("subscription-sensitivity"), sensitivity_root),
            (attention.role("subscription-audience"), audience_root),
            (attention.role("subscription-lifecycle"), lifecycle_root),
            (attention.role("subscription-action"), decision.action_root),
            (attention.role("subscription-authority"), decision.policy_root),
            *((attention.role("subscription-rule"), root) for root in decision.determining_rule_roots),
            (attention.role("subscription-cursor"), cursor_root),
            (attention.role("subscription-state"), attention.state("active")),
        ),
        relation_id=subscription_id,
    )
    append = prepare_append_relation_member(
        snapshot,
        attention.registry("subscription"),
        attention.role("subscription-member"),
        subscription_id,
        budget=100_000,
    )
    created = (
        Cell(cursor_root, NULL_CELL_ID, NULL_CELL_ID, b"0"),
        *relation.cells,
        *append.create,
    )
    identities = tuple(cell.id for cell in created)
    if len(identities) != len(set(identities)):
        raise InvalidCell("reaction subscription creates duplicate identities")
    store.commit(snapshot.revision, create=created, replace=append.replace)
    return read_reaction_subscription(store.snapshot(), attention, subscription_id)


def set_reaction_subscription_active(
    store: CellStore,
    attention: AttentionProtocol,
    subscription_root: str,
    active: bool,
) -> int:
    subscription = read_reaction_subscription(
        store.snapshot(), attention, subscription_root
    )
    return rewire_incidence(
        store,
        subscription.state_incidence,
        attention.state("active" if active else "blocked"),
    )


def _signal_identity(subscription_root: str, event_root: str) -> tuple[str, str]:
    digest = hashlib.sha256(
        (subscription_root + "\0" + event_root).encode("utf-8")
    ).hexdigest()
    return "attention-signal:reaction:" + digest, "reaction/" + digest


def drain_reaction_subscriptions(
    store: CellStore,
    attention: AttentionProtocol,
    reaction: ReactionProtocol,
    *,
    max_events: int = 1_000,
) -> tuple[str, ...]:
    """Project unconsumed reaction events; each cursor advances durably."""
    if max_events < 1:
        raise ValueError("subscription event budget must be positive")
    emitted: list[str] = []
    registry = read_relation(
        store.snapshot(), attention.registry("subscription"), budget=100_000
    )
    subscriptions = tuple(
        member.participant_id
        for member in registry
        if member.role_id == attention.role("subscription-member")
    )
    for root in subscriptions:
        while len(emitted) < max_events:
            snapshot = store.snapshot()
            subscription = read_reaction_subscription(snapshot, attention, root)
            if subscription.state_root != attention.state("active"):
                break
            events = reaction_events(
                snapshot, reaction, subscription.reaction_root
            )
            if subscription.cursor < 0 or subscription.cursor > len(events):
                raise InvalidCell("reaction subscription cursor is outside its event log")
            if subscription.cursor == len(events):
                break
            event = events[subscription.cursor]
            signal_id, idempotency_key = _signal_identity(root, event.root_id)
            signal_root = record_signal(
                store,
                attention,
                signal_id=signal_id,
                source_root=event.source_root,
                source_revision=event.revision,
                observer_root=subscription.observer_root,
                provenance_root=event.root_id,
                trust_root=subscription.trust_root,
                affected_roots=(event.source_root,),
                observed_at="store-revision:%s" % event.revision,
                sensitivity_root=subscription.sensitivity_root,
                audience_root=subscription.audience_root,
                idempotency_key=idempotency_key,
                lifecycle_root=subscription.lifecycle_root,
                subscription_root=root,
            )
            current = store.snapshot()
            refreshed = read_reaction_subscription(current, attention, root)
            if refreshed.cursor != subscription.cursor:
                raise InvalidCell("reaction subscription cursor changed concurrently")
            cursor = current.cells[refreshed.cursor_root]
            store.commit(
                current.revision,
                replace=(Cell(
                    cursor.id,
                    cursor.link0,
                    cursor.link1,
                    str(subscription.cursor + 1).encode("ascii"),
                ),),
            )
            emitted.append(signal_root)
        if len(emitted) >= max_events:
            break
    return tuple(emitted)


__all__ = [
    "ReactionSubscriptionProjection",
    "build_reaction_subscription",
    "read_reaction_subscription",
    "set_reaction_subscription_active",
    "drain_reaction_subscriptions",
]
