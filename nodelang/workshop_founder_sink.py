"""The founder's Workshop sink: BABOOM's tell lands as conversation content (plan B, S3a, W4a).

BABOOM acts with the founder's own authority (application_server
`_require_founder_machine_session`). Its "tell <agent>: <text>" becomes one ordinary
Workshop message authored by the founder and addressed to one existing participant,
stored by the conversation-content owner. No message Cell, no clean coordination host,
no second identity.

Admission runs before any write, and every refusal there is RefusedWithoutEffect: the
graph revision, the content history and the relay are untouched.
  * the authenticated caller must be the founder (an agent session or any other
    subject is refused, never promoted);
  * the target must already be a participant of the general Workshop and must not be
    the founder;
  * the Workshop must be bound to conversation content (the legacy ledger is never
    written from here);
  * at the pre-append boundary the founder's context is resolved again and the
    conversation's live policy is checked, so a revocation or a policy denial up to
    that point is a typed no-effect refusal.
From the first resolve through the append the sink holds the owner's mutation lock and
the broker's live context (the order every content writer uses), so no other thread can
revoke the context between the boundary and the append's own admission. Anything raised
by the append itself or after it is NOT classified as no-effect: the append may have
committed. A replay with the same idempotency key returns the stored message and adds
none; a replay with different text or target is an idempotency conflict and relays
nothing.

Interrupt is not a Workshop write and has one owner, baboom_session_interrupt (Session Link);
this sink only stores.

Unused until S3b switches BABOOM's tell to it.
"""
from __future__ import annotations

from contextlib import ExitStack

from .cell_authorization import AuthorizationDenied, RefusedWithoutEffect
from .cell_deliberation import read_deliberation_space
from .universal_cell import InvalidCell

def _require_founder(identity, founder):
    if identity.subject_root != founder:
        raise RefusedWithoutEffect("Only the founder tells agents through BABOOM; nothing was sent")


def _admit_at_boundary(snapshot, registry, authentication_context, founder):
    """The last check before the append: live founder context and the conversation's live policy."""
    from .cell_authorization import AuthorizationRequest, require_authorization
    from .conversation_content import read_content_space
    authority = registry.authorization
    try:
        _require_founder(authority.broker.resolve(authentication_context), founder)
        space = read_content_space(snapshot, registry.deliberation_protocol, registry.workshop_root)
        decision = require_authorization(snapshot, authority.protocol, space.policy_root,
            authority.broker, authentication_context, AuthorizationRequest(
                action_root=space.action_root, object_root=space.root_id,
                resource_lineage_roots=space.scope_roots, interface_root=space.interface_root,
                purpose_root=space.purpose_root, classification_root=space.classification_root,
                audience_root=space.audience_root, lifecycle_state_root=space.lifecycle_root,
                operational_state_root=space.operational_state_root))
    except RefusedWithoutEffect:
        raise
    except AuthorizationDenied as denied:
        raise RefusedWithoutEffect("BABOOM's tell is no longer authorized (%s); nothing was sent"
                                   % denied) from denied
    if decision.subject_root != founder:
        raise RefusedWithoutEffect("Only the founder tells agents through BABOOM; nothing was sent")


def founder_tell(owner, authentication_context, *, target_root, text, idempotency_key):
    """Store one founder note to one Workshop participant; refuse before any write otherwise."""
    from .existing_workshop_conversation import _relay_native_recipients
    from .universal_application import (append_universal_workshop_entry,
                                        validate_universal_workshop_entry_content)
    from .conversation_content import workshop_message_identity

    if type(target_root) is not str or not target_root:
        raise InvalidCell("name the agent to tell")
    if type(idempotency_key) is not str or not 1 <= len(idempotency_key) <= 128:
        raise InvalidCell("BABOOM's tell needs an idempotency key of 1-128 characters")
    content = validate_universal_workshop_entry_content(text)
    registry, store = owner.universal_registry, owner.universal_store
    authority = registry.authorization
    founder = authority.subject_root
    # Same order as every content writer: the owner's mutation lock, then the broker's live
    # context. Both re-enter inside the append, and revocation waits for the broker lock.
    with owner.mutation_lock, ExitStack() as held:
        try:
            identity = held.enter_context(authority.broker.live_context(authentication_context))
        except AuthorizationDenied as denied:
            raise RefusedWithoutEffect("BABOOM's Workshop tell needs the founder's live session") from denied
        _require_founder(identity, founder)
        snapshot = store.snapshot()
        space = read_deliberation_space(snapshot, registry.deliberation_protocol, registry.workshop_root)
        if space.content_store_root is None:
            raise RefusedWithoutEffect("The Workshop is not on conversation content yet; nothing was sent")
        if target_root == founder or target_root not in space.participant_roots:
            raise RefusedWithoutEffect("%s is not an agent in this Workshop; nothing was sent" % target_root)
        service = getattr(owner, "conversation_content", None)
        if service is None or not service.belongs_to(store, registry):
            raise RefusedWithoutEffect("Workshop content has no current owner; nothing was sent")
        _admit_at_boundary(snapshot, registry, authentication_context, founder)
        # Past this line nothing is classified as no-effect: the append may have committed.
        # It is bound to the admitted snapshot revision and re-checks its own admission.
        entry = append_universal_workshop_entry(store, registry,
            actor_root=founder, category_root=registry.workshop_category_roots["note"],
            content=content, idempotency_key=idempotency_key, created_at=None,
            recipient_roots=(target_root,), authentication_context=authentication_context,
            expected_revision=snapshot.revision, content_service=service)
    # The relay carries the STORED message, never the caller's text.
    relay = _relay_native_recipients(owner, entry.space_root, entry.message_id, entry.actor_root,
                                     entry.recipient_roots, entry.content)
    return {"ok": True, "workshop": registry.workshop_root, **workshop_message_identity(entry),
            "storage": "conversation-content", "idempotency_key": entry.idempotency_key,
            "target": target_root, **relay}


__all__ = ["founder_tell"]
