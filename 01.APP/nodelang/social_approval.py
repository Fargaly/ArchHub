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

RUBRIC = ("Target and revision match", "Changes fit the requested scope", "Evidence supports the result")


def require_review_admission(snapshot, permission_root):
    """The same graph parameter constrains consent and use of an existing grant."""
    from .universal_cell import InvalidCell
    cell = snapshot.cells.get(permission_root + ":approval-review")
    if cell is None:
        return
    review = json.loads(cell.atom)
    if (review["status"] != "pending" or any(value is not True for value in review["rubric"].values())
            or any(row.get("decision") == "Reject" for row in review["rows"])):
        raise InvalidCell("Approval review is held; resume or refresh and resolve its evidence before approving")


def _delegation(api, root):
    from .cell_connector_execution import read_connector_delegation
    from .cell_model_execution import read_model_delegation
    from .cell_adapters import read_permission
    from .universal_cell import InvalidCell
    if type(root) is not str:
        raise InvalidCell("Approval requires its exact delegation identity")
    from .host_skill_owner import PREFIX as HOST_PREFIX, HostSkillOwner
    if root.startswith(HOST_PREFIX):
        from types import SimpleNamespace
        owner = HostSkillOwner(api)
        package, _, proposal = owner._proposal(root)
        card = owner.card(root)
        lifecycle = "requested" if card["status"] in {"pending", "postponed"} else "granted" if card["status"] == "approved" else "revoked"
        delegation = SimpleNamespace(root_id=root, permission_root=root, work_root=package,
            input_digest=proposal["input_digest"], expires_at=float("inf"))
        permission = SimpleNamespace(lifecycle_root=api.owner.universal_registry.adapter_protocol.states[lifecycle],
            user_root=api.binding.subject_root)
        return api.admit(), "hostskills", delegation, permission, {"interfaces":{"title":{"value":card["title"]}}}
    from .watcher_owner import PREFIX, approval_context
    if root.startswith(PREFIX):
        return approval_context(api, root)
    snapshot = api.admit()
    registry = api.owner.universal_registry
    if root.startswith(DELEGATION_PREFIX):
        kind = "social"
        delegation = read_connector_delegation(snapshot, registry.baboom_connector_execution_protocol,
                                               registry.adapter_protocol, root)
        if delegation.provider_root not in _social_providers(registry):
            raise InvalidCell("This connector has no social approval owner")
    elif root.startswith("app:baboom-model-delegation:"):
        kind = "model"
        delegation = read_model_delegation(snapshot, registry.baboom_model_execution_protocol,
                                          registry.adapter_protocol, root)
    else:
        raise InvalidCell("Approval requires an existing social or model delegation")
    work = api._work(delegation.work_root)
    permission = read_permission(snapshot, registry.adapter_protocol, delegation.permission_root)
    if permission.user_root != api.binding.subject_root:
        from .cell_authorization import AuthorizationDenied
        raise AuthorizationDenied("Approval belongs to another account")
    return snapshot, kind, delegation, permission, work


def _material(api, kind, delegation):
    from . import universal_application as app
    registry, store = api.owner.universal_registry, api.owner.universal_store
    snapshot = store.snapshot()
    if kind == "social":
        prepared, digest, text = _review(snapshot, registry, delegation)
        return digest, text, prepared.operation
    session, _, work = app._baboom_execution_work_context(store, registry,
        agent_session_root=delegation.session_root, work_root=delegation.work_root,
        authentication_context=api.binding.context)
    view, _ = app._view_session_for_context(registry, api.binding.context)
    provider = next(name for name, root in registry.baboom_model_provider_roots.items()
                    if root == delegation.provider_root)
    request, text, _, _, _ = app._read_baboom_bound_cognition_input(store, registry,
        cognition_request_root=delegation.cognition_request_root, work=work,
        work_root=delegation.work_root, execution_session=session, view_session=view,
        provider=provider, model=delegation.model, authentication_context=api.binding.context,
        content_service=api.owner.conversation_content)
    return request.input_digest, text, delegation.model


def approval_card(api, root):
    from .host_skill_owner import PREFIX as HOST_PREFIX, HostSkillOwner
    if type(root) is str and root.startswith(HOST_PREFIX):
        return HostSkillOwner(api).card(root)
    from .watcher_owner import PREFIX, WatcherOwner
    if type(root) is str and root.startswith(PREFIX):
        return WatcherOwner(api).card(root)
    from .cell_authorization import AuthorizationDenied
    from .universal_cell import InvalidCell
    snapshot, kind, delegation, permission, work = _delegation(api, root)
    registry = api.owner.universal_registry
    held = snapshot.cells.get(delegation.permission_root + ":approval-review")
    values = json.loads(held.atom) if held else {"status":"pending", "rows":[], "rubric":{}, "events":[]}
    card = {**values, "id":root, "delegation":root, "work":delegation.work_root, "taskId":delegation.work_root,
            "input_digest":delegation.input_digest, "approvalKind":kind, "kind":"qc",
            "expires_at":delegation.expires_at, "title":work["interfaces"]["title"]["value"],
            "revision":snapshot.revision}
    try:
        digest, text, operation = _material(api, kind, delegation)
        current = digest == delegation.input_digest and time.time() < delegation.expires_at
        if not held:
            card["rows"] = [{"element":operation, "before":"Not executed", "after":text}]
    except (InvalidCell, AuthorizationDenied):
        current = False
    if card["status"] not in {"contested", "superseded"}:
        if not current:
            card["status"] = "stale"
        elif permission.lifecycle_root == registry.adapter_protocol.states["granted"]:
            card["status"] = "approved"
        elif permission.lifecycle_root != registry.adapter_protocol.states["requested"]:
            card["status"] = "declined"
    return card


def _save_review(api, delegation, card, action, details=None):
    from .universal_cell import Cell, InvalidCell
    from .cell_protocols import prepare_append_relation_members
    from . import universal_application as app
    store, registry = api.owner.universal_store, api.owner.universal_registry
    snapshot = api.admit()
    view, context = app._view_session_for_context(registry, api.binding.context)
    root = delegation.permission_root + ":approval-review"
    event_root = delegation.permission_root + ":approval-event:" + hashlib.sha256(
        (api.request_id + ":" + action).encode()).hexdigest()
    event = {"action":action, "details":details, "input_digest":delegation.input_digest,
             "actor":api.binding.subject_root, "revision":snapshot.revision,
             "status":card["status"]}
    if event_root in snapshot.cells:
        old = json.loads(snapshot.cells[event_root].atom)
        if any(old[key] != event[key] for key in ("action", "details", "input_digest", "actor")):
            raise InvalidCell("Approval request identity already names another action")
        return approval_card(api, delegation.root_id)
    values = {key:card[key] for key in ("status", "rows", "rubric", "events")}
    values["events"] = [*values["events"], event_root]
    if "successor" in card:
        values["successor"] = card["successor"]
    encoded = json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > 65536:
        raise InvalidCell("Approval review exceeds 64 KiB; its existing history remains intact")
    parameter = Cell(root, delegation.root_id, api.binding.subject_root, encoded)
    event_cell = Cell(event_root, delegation.root_id, api.binding.subject_root,
                      json.dumps(event, ensure_ascii=False, allow_nan=False).encode())
    exists = root in snapshot.cells
    patch = prepare_append_relation_members(snapshot, delegation.work_root,
        tuple((registry.roles["member"], member) for member in
              ((event_root,) if exists else (root, event_root))))
    api.guard()
    app._commit_universal_user_change(store, registry, view, context, snapshot,
        route=api.route, command_name="catalog.configure", authorization_scope_root=api.root,
        create=(*patch.create, event_cell, *((parameter,) if not exists else ())),
        replace=(*patch.replace, *((parameter,) if exists else ())))
    return approval_card(api, delegation.root_id)


def change_review(api, root, action, *args):
    from .universal_cell import InvalidCell
    snapshot, kind, delegation, permission, _ = _delegation(api, root)
    card = approval_card(api, root)
    requested = api.owner.universal_registry.adapter_protocol.states["requested"]
    if action == "contestDecision":
        reason = args[0]
        if type(reason) is not str or not reason.strip() or len(reason) > 2000:
            raise InvalidCell("Describe what needs review in 1–2000 characters")
        if card["status"] == "superseded":
            raise InvalidCell("Review the successor decision instead")
        card["status"] = "contested"
        return _save_review(api, delegation, card, action, reason.strip())
    if action == "refreshApproval" and kind == "hostskills":
        from .host_skill_owner import HostSkillOwner
        owner = HostSkillOwner(api)
        package, _, proposal = owner._proposal(root)
        return owner.request(package, proposal["action"])
    if action == "refreshApproval" and kind == "watcher":
        raise InvalidCell("Discard the source-bound Watcher draft and read its source before proposing a fresh edit")
    if action == "refreshApproval":
        if card.get("successor"):
            return approval_card(api, card["successor"])
        if kind == "social":
            from .existing_workshop_social_execution import prepare_social_work
            prepared = prepare_social_work(api.owner, work_root=delegation.work_root,
                session_root=delegation.session_root, context=api.binding.context, note="")
            successor = prepared["delegation"]
        else:
            from . import universal_application as app
            registry, store = api.owner.universal_registry, api.owner.universal_store
            provider = next(name for name, target in registry.baboom_model_provider_roots.items()
                            if target == delegation.provider_root)
            options = dict(agent_session_root=delegation.session_root, work_root=delegation.work_root,
                provider=provider, model=delegation.model, data_class=app._text(snapshot, delegation.datatype_root),
                authentication_context=api.binding.context, content_service=api.owner.conversation_content)
            observation = _retained_observation(snapshot, registry, delegation)
            request, _ = app.prepare_universal_baboom_model_cognition_request(store, registry,
                **options, shadow_observation=observation)
            fresh, _, _ = app.request_universal_baboom_model_execution(store, registry,
                **options, cognition_request_root=request.root_id)
            successor = fresh.root_id
        card.update(status="superseded", successor=successor)
        _save_review(api, delegation, card, action, successor)
        return approval_card(api, successor)
    if permission.lifecycle_root != requested or card["status"] not in {"pending", "postponed"}:
        raise InvalidCell("This review is closed or stale; request a fresh review")
    if action == "postponeApproval":
        card["status"] = "postponed"
    elif action == "resumeApproval":
        if card["status"] != "postponed":
            raise InvalidCell("Only a postponed review can resume")
        card["status"] = "pending"
    elif action == "reviewProofRow":
        index, decision = args
        if type(index) is not int or not 0 <= index < len(card["rows"]) or decision not in {"Accept", "Reject"}:
            raise InvalidCell("Review an existing proof row with Accept or Reject")
        card["rows"][index]["decision"] = decision
    elif action == "setApprovalRubric":
        item, checked = args
        if type(item) is not str or item not in RUBRIC or type(checked) is not bool:
            raise InvalidCell("Approval rubric requires an existing criterion and boolean")
        card["rubric"][item] = checked
    else:
        raise InvalidCell("Unknown approval action")
    return _save_review(api, delegation, card, action, list(args))


def _retained_observation(snapshot, registry, delegation):
    from . import universal_application as app
    from .cell_protocols import read_relation
    protocol = registry.agent_body.cognition_protocol
    request = read_relation(snapshot, delegation.cognition_request_root)
    manifests = [m.participant_id for m in request if m.role_id == protocol.role("request-context-manifest")]
    if len(manifests) != 1:
        from .universal_cell import InvalidCell
        raise InvalidCell("Cognition review requires one context manifest")
    for item in read_relation(snapshot, manifests[0]):
        for member in read_relation(snapshot, item.participant_id):
            if member.role_id != protocol.role("manifest-context-root"):
                continue
            value = json.loads(snapshot.cells[member.participant_id].atom)
            if type(value) is dict and value.get("kind") == app._BABOOM_COGNITION_FOREGROUND_CAPSULE_KIND:
                return app._normalise_baboom_foreground_observation(
                    {"kind":app._BABOOM_FOREGROUND_OBSERVATION_KIND, "app":value["app"]})
    return None


def list_reviews(api):
    from .cell_protocols import read_relation
    from .cell_authorization import AuthorizationDenied
    from .universal_cell import InvalidCell
    registry = api.owner.universal_registry
    snapshot = api.admit()
    works = {row["root"] for row in api._works()}
    cards = []
    for protocol in (registry.baboom_connector_execution_protocol, registry.baboom_model_execution_protocol):
        for member in read_relation(snapshot, protocol.registry("delegation")):
            if member.role_id != protocol.role("registry-member"):
                continue
            # Resolve scope before reading any request material.
            from .cell_protocols import read_relation as relation
            participants = relation(snapshot, member.participant_id)
            if not any(p.role_id == protocol.role("delegation-work") and p.participant_id in works for p in participants):
                continue
            try:
                cards.append(approval_card(api, member.participant_id))
            except (InvalidCell, AuthorizationDenied):
                continue
    from .watcher_owner import WatcherOwner
    from .host_skill_owner import HostSkillOwner
    return cards + WatcherOwner(api).reviews() + HostSkillOwner(api).reviews()


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
    from .social_connectors import OPERATIONS
    try:
        return social_account_binding(provider=OPERATIONS[operation][0],
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
        require_review_admission(snapshot, delegation.permission_root)
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


def decide_watcher(api, root, digest, decision):
    """The same authenticated approval owner admits the one Watcher effect gesture."""
    from .watcher_owner import WatcherOwner
    snapshot, _, delegation, _, _ = _delegation(api, root)
    if decision == "approve":
        require_review_admission(snapshot, delegation.permission_root)
    return WatcherOwner(api).decide(root, digest, decision)
