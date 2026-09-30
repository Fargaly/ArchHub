"""The founder's approval of a social post: the exact request, then Approve or Deny.

An agent prepares a social Work (social.work_prepare) and executes it only after this
approval (social.work_execute). Nothing here sends anything. pending() lists the
social delegations still waiting, each with the review text recomputed from the
Work's current inputs: the operation, the target account and the exact request body,
which carries the post text. decide() is the founder's own gesture in his
authenticated browser session, the same consent primitive project approval uses
(adapter_consent_broker.mint_from_user_gesture + grant_permission). Deny revokes the
requested permission, so the prepared request can never be granted.
"""
from __future__ import annotations

import hashlib
import json
import time

DELEGATION_PREFIX = "app:baboom-connector-delegation:"
PENDING_LIMIT = 20
_PENDING_CACHE = {"key": None, "items": ()}


def _social_providers(registry) -> dict:
    return {root: name for name, root in registry.baboom_connector_provider_roots.items()
            if type(name) is str and name.startswith("social-")}


def _founder(snapshot, registry, binding):
    from .cell_agent_body import read_agent_session
    founder = read_agent_session(snapshot, registry.agent_body.protocol, registry.authorization.protocol,
                                 registry.agent_body.session.root_id)
    if (founder.subject_root != binding.subject_root or founder.body_root != registry.agent_body.body.root_id
            or founder.state_root != registry.agent_body.protocol.state("active")):
        from .cell_authorization import AuthorizationDenied
        raise AuthorizationDenied("Only the founder's own active session approves a social post")
    return founder


def _review(snapshot, registry, delegation):
    from .existing_workshop_social_execution import _review_text, social_material_at
    prepared, raw = social_material_at(snapshot, registry, delegation.work_root)
    return prepared, hashlib.sha256(raw).hexdigest(), _review_text(prepared, "")


def _vault_entry(snapshot, registry, delegation) -> str:
    from .existing_workshop_social_execution import social_material_at
    _prepared, raw = social_material_at(snapshot, registry, delegation.work_root)
    return str(json.loads(raw.decode("utf-8"))["inputs"]["vault_entry"])


def _sent(snapshot, registry, delegation_root) -> bool:
    """True once any execution record (a receipt) exists for this delegation."""
    from .cell_connector_execution import read_connector_execution_receipt
    from .cell_protocols import read_relation
    protocol = registry.baboom_connector_execution_protocol
    for member in read_relation(snapshot, protocol.registry("receipt"), budget=100_000):
        if member.role_id != protocol.role("registry-member"):
            continue
        receipt = read_connector_execution_receipt(snapshot, protocol, registry.adapter_protocol, member.participant_id)
        if receipt.delegation_root == delegation_root:
            return True
    return False


def _account_binding(operation: str, account_id: str, vault_entry: str) -> str:
    """The stored binding of the account a post names (custody's own record), or "unknown"."""
    from .social_custody import social_account_binding
    try:
        return social_account_binding(provider="linkedin" if operation.startswith("linkedin.") else "meta",
                                      account_id=account_id, vault_entry=vault_entry)
    except Exception:
        return "unknown"


def pending(server, binding) -> list:
    """Social delegations awaiting the founder, read from the delegation registry.

    Settings polls this. The walk is the delegation registry relation (as the Work
    projection reads it), never every cell, and an unchanged graph revision answers
    from the previous walk; only expiry is re-applied to a cached answer.
    """
    from .cell_adapters import read_permission
    from .cell_connector_execution import read_connector_delegation
    from .cell_protocols import read_relation
    store, registry = server.universal_store, server.universal_registry
    snapshot = store.snapshot()
    _founder(snapshot, registry, binding)
    now = time.time()
    key = (id(store), snapshot.revision, id(snapshot.cells))
    if _PENDING_CACHE["key"] == key:
        return [dict(item) for item in _PENDING_CACHE["items"] if now < item["expires_at"]]
    providers = _social_providers(registry)
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    items = []
    for member in read_relation(snapshot, protocol.registry("delegation"), budget=100_000):
        if member.role_id != protocol.role("registry-member"):
            continue
        root = member.participant_id
        try:
            delegation = read_connector_delegation(snapshot, protocol, adapters, root)
            if delegation.provider_root not in providers or now >= delegation.expires_at:
                continue
            if read_permission(snapshot, adapters, delegation.permission_root).lifecycle_root != adapters.states["requested"]:
                continue
            prepared, digest, review = _review(snapshot, registry, delegation)
        except Exception:
            continue  # an unreadable or changed request is never offered for approval
        if digest != delegation.input_digest:
            continue
        items.append({"delegation": root, "work": delegation.work_root, "operation": prepared.operation,
                      "account_id": prepared.account_id, "input_digest": digest, "review_text": review,
                      "expires_at": delegation.expires_at,
                      "account_binding": _account_binding(prepared.operation, prepared.account_id,
                                                          _vault_entry(snapshot, registry, delegation))})
    items.sort(key=lambda item: item["expires_at"])
    items = items[:PENDING_LIMIT]          # sorted first: the soonest to expire are never hidden
    _PENDING_CACHE.update(key=key, items=tuple(dict(item) for item in items))
    return items


def decide(server, binding, body) -> dict:
    """Approve or deny ONE displayed request: the delegation and its exact input digest."""
    from . import universal_application as app
    from .cell_adapters import grant_permission, read_permission, revoke_permission
    from .cell_connector_execution import read_connector_delegation, read_connector_provider
    from .cell_authorization import AuthorizationDenied
    from .universal_cell import InvalidCell

    if (type(body) is not dict or set(body) != {"delegation", "input_digest", "decision"}
            or body["decision"] not in ("approve", "deny") or type(body["delegation"]) is not str
            or not body["delegation"].startswith(DELEGATION_PREFIX) or type(body["input_digest"]) is not str):
        raise InvalidCell("social approval names one delegation, its input digest and approve or deny")
    store, registry = server.universal_store, server.universal_registry
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    with server.mutation_lock, registry.authorization.broker.live_context(binding.context):
        snapshot = store.snapshot()
        founder = _founder(snapshot, registry, binding)
        delegation = read_connector_delegation(snapshot, protocol, adapters, body["delegation"])
        if delegation.provider_root not in _social_providers(registry):
            raise AuthorizationDenied("This delegation is not a social post")
        if time.time() >= delegation.expires_at:
            raise AuthorizationDenied("This social request expired; the agent must prepare it again")
        prepared, digest, _ = _review(snapshot, registry, delegation)
        if not (body["input_digest"] == digest == delegation.input_digest):
            raise AuthorizationDenied("The post changed since it was shown; review the current one")
        app._require_application_authorization(snapshot, registry, "execute", delegation.root_id,
            authentication_context=binding.context, resource_lineage_roots=(delegation.work_root,))
        permission = read_permission(snapshot, adapters, delegation.permission_root)
        if permission.user_root != founder.subject_root:
            raise AuthorizationDenied("This social permission belongs to another user")
        answer = {"delegation": delegation.root_id, "work": delegation.work_root, "operation": prepared.operation,
                  "account_id": prepared.account_id, "input_digest": digest}
        if body["decision"] == "deny":
            # Deny means "this is not posted": an approved post (a second tab, a stale
            # list) is revoked too, so no grant can be issued or used for it. A post
            # that was already sent cannot be un-sent; say so instead of promising it.
            if _sent(snapshot, registry, delegation.root_id):
                raise InvalidCell("This post was already sent; Deny cannot take it back")
            if permission.lifecycle_root in (adapters.states["requested"], adapters.states["granted"]):
                revoke_permission(store, adapters, delegation.permission_root)
            return {**answer, "decision": "denied", "revision": store.revision}
        if permission.lifecycle_root == adapters.states["granted"]:
            return {**answer, "decision": "approved", "revision": store.revision}
        if permission.lifecycle_root != adapters.states["requested"]:
            raise InvalidCell("This social permission is no longer awaiting approval")
        registry.authorization.broker.resolve(binding.context)
        provider = read_connector_provider(snapshot, protocol, adapters, delegation.provider_root)
        gesture = server.adapter_consent_broker.mint_from_user_gesture(delegation.permission_root, founder.subject_root)
        grant_permission(store, adapters, app._connector_execution_catalog_for_provider(registry, provider),
                         delegation.permission_root, server.adapter_consent_broker, gesture,
                         expected_revision=snapshot.revision)
        return {**answer, "decision": "approved", "revision": store.revision}