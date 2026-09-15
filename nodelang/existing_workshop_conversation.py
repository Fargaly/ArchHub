"""Browser lens over the existing application's admitted deliberation space."""
import time
import json
import hashlib
import re

from .cell_authorization import AuthorizationDenied, AuthorizationRequest, authorize_node_request
from .cell_deliberation import read_deliberation_space, _recent_entries_from_validated_space
from .cell_protocols import read_relation
from .universal_cell import InvalidCell


def canvas_workshop_scope(registry, projection, *, snapshot=None, subject_root=None):
    """Describe admitted Workshop spaces actually in this canvas projection."""
    scope = projection["scope"]["current"]
    workbench = getattr(registry, "workshop_workbench_root", None)
    node = next((row for row in projection.get("nodes", ())
        if row.get("id") in (registry.workshop_root, workbench)), None)
    if node is None and workbench is not None and scope == workbench:
        node = {"id":workbench, "label":"Workshop"}
    if node is not None and node["id"] == workbench:
        attached = snapshot is not None and any(
            member.role_id == registry.roles["scope"] and member.participant_id == registry.workshop_root
            for member in read_relation(snapshot, workbench, budget=100_000))
        if not attached:
            node = None
    workshops = [] if node is None else [{
            "root":registry.workshop_root, "label":node.get("label") or "Workshop",
            "node_root":node["id"],
            "send_category":"note", "is_general":True, "native_work_available":True}]
    if snapshot is not None and workbench is not None:
        registered = {member.participant_id for member in read_relation(snapshot, workbench, budget=100_000)
            if member.role_id == registry.roles["scope"]}
        from .workshop_conversation_catalog import validate_workshop_conversation_scope
        candidates = {row["id"]:row for row in projection.get("nodes", ())
            if row.get("id") in registered and row.get("id") != registry.workshop_root}
        if scope in registered and scope != registry.workshop_root:
            candidates.setdefault(scope, {"id":scope})
        for root, candidate in candidates.items():
            try:
                validate_workshop_conversation_scope(snapshot, registry.deliberation_protocol,
                    application_root=registry.application_root, canonical_root=registry.workshop_root, root=root)
                space = read_deliberation_space(snapshot, registry.deliberation_protocol, root)
            except InvalidCell:
                continue
            if subject_root not in space.participant_roots:
                continue
            workshops.append({"root":root, "label":space.title, "node_root":root,
                "send_category":"note", "is_general":False, "native_work_available":False})
    return {"graph_id":registry.application_root, "root":scope,
        "revision":projection["revision"], "workshops":workshops}


def _admit(owner, binding, root, scope, *, allow_child=False):
    from .universal_application import (
        _view_session_for_context, _require_application_authorization,
        _session_canvas_roots, _cached_authority_snapshot)
    registry, store = owner.universal_registry, owner.universal_store
    if binding.context is None or (root != registry.workshop_root and not allow_child):
        raise AuthorizationDenied("Workshop request is outside this application")
    snapshot = store.snapshot()
    view, context = _view_session_for_context(registry, binding.context)
    if view.root_id != binding.view_root or view.subject_root != binding.subject_root:
        raise AuthorizationDenied("Workshop browser view changed")
    _require_application_authorization(snapshot, registry, "read", root,
        authentication_context=context)
    visible, _relations, _properties, trail = _session_canvas_roots(snapshot, registry, view,
        include_trail=True, authority_snapshot=_cached_authority_snapshot(snapshot, registry.authorization))
    workbench = getattr(registry, "workshop_workbench_root", None)
    workbench_visible = workbench is not None and (workbench in visible or scope == workbench
        or (allow_child and root != registry.workshop_root and scope == root and workbench in trail))
    if workbench_visible:
        workbench_visible = any(member.role_id == registry.roles["scope"] and member.participant_id == root
            for member in read_relation(snapshot, workbench, budget=100_000))
    if not trail or trail[-1] != scope or not (root in visible or workbench_visible):
        raise AuthorizationDenied("Workshop is no longer on this canvas")
    space = read_deliberation_space(snapshot, registry.deliberation_protocol, root)
    if root != registry.workshop_root:
        from .conversation_content import read_content_binding
        if not workbench_visible or binding.subject_root not in space.participant_roots:
            raise AuthorizationDenied("Conversation is not attached to this Workshop or caller")
        read_content_binding(snapshot, registry.deliberation_protocol,
            application_root=registry.application_root, space_root=root)
    if store.revision != snapshot.revision:
        raise AuthorizationDenied("Workshop changed during admission; refresh to continue")
    return snapshot, space


def read_browser_workshop(owner, binding, *, root, scope, after=None, session_token=None,
                          content_after=None, before=None, feed='all'):
    if type(feed) is not str or feed not in {'all', 'messages', 'activity'}:
        raise InvalidCell('Workshop feed must be messages, activity or all')
    # Session enrollment takes the capability lock before writing the graph.
    # Copy connection observations first; never acquire that lock in a snapshot.
    connections_reader = getattr(owner, "_workshop_runtime_connections", None)
    connections = connections_reader() if callable(connections_reader) else {}
    snapshot, space = _admit(owner, binding, root, scope, allow_child=True)
    if getattr(space, "content_store_root", None) is not None:
        from .workshop_session_start import project_workshop_model_agent
        model_agent = project_workshop_model_agent(owner, binding, root, scope)
        result = _read_ordinary_browser_workshop(owner, binding, root=root, scope=scope,
            expected_revision=snapshot.revision, session_token=session_token,
            content_after=content_after, before=before, connections=connections, feed=feed)
        return {**result, "model_agent":model_agent}
    if feed != 'all':
        raise InvalidCell('Workshop feed selection requires ordinary indexed history')
    if content_after is not None or before is not None:
        raise InvalidCell("This Workshop does not support ordinary message positions")
    registry, authority = owner.universal_registry, owner.universal_registry.authorization
    header = {"ok":True, "model_agent":None, "graph_id":registry.application_root, "root":root,
        "scope_root":scope, "revision":snapshot.revision,
        "participants": _workshop_participant_rows(owner, snapshot, space, connections)}
    if after is not None and str(snapshot.revision) == after:
        return {**header, "unchanged":True}
    request_session = (registry.agent_body.session.root_id
        if binding.subject_root == authority.subject_root else binding.subject_root)
    # Decode only the visible panel's bounded tail, never the complete ledger.
    recent = _recent_entries_from_validated_space(snapshot, registry.deliberation_protocol,
        space, limit=100)
    categories = {value:key for key, value in registry.workshop_category_roots.items()}
    projection = owner._filter_universal_machine_workshop({"revision":snapshot.revision,
        "entries":[{"root":entry.root_id, "actor":entry.actor_root,
            "kind":categories.get(entry.category_root, entry.category_root),
            "recipients":list(entry.recipient_roots), "text":entry.content,
            "reply_to":entry.reply_to_root, "evidence":list(entry.evidence_roots),
            "created_at":entry.created_at} for entry in recent]},
        request_agent_session=request_session)
    if projection["revision"] != snapshot.revision or owner.universal_store.revision != snapshot.revision:
        raise AuthorizationDenied("Workshop changed during read; refresh to continue")
    decision = authorize_node_request(snapshot, authority.protocol, space.policy_root,
        authority.broker, binding.context, AuthorizationRequest(action_root=space.action_root,
            object_root=root, resource_lineage_roots=space.scope_roots,
            interface_root=space.interface_root, purpose_root=space.purpose_root,
            classification_root=space.classification_root, audience_root=space.audience_root,
            lifecycle_state_root=space.lifecycle_root, operational_state_root=space.operational_state_root))
    if owner.universal_store.revision != snapshot.revision:
        raise AuthorizationDenied("Workshop changed during authorization; refresh to continue")
    entries = projection["entries"][-100:]
    return {**header, "owner":binding.subject_root, "view":binding.view_root,
        "self":binding.subject_root, "can_join":False,
        "can_send":decision.allowed and binding.subject_root in space.participant_roots,
        "send_category":"note", "execution_nodes":[],
        "has_older":len(space.entry_roots) > len(recent),
        "messages":[{"root":entry["root"], "sender_root":entry["actor"],
            "recipient_root":", ".join(entry["recipients"]) or "Everyone",
            "recipient_roots":entry["recipients"], "body":entry["text"],
            "category":entry["kind"], "state":"recorded", "reply_to_root":entry["reply_to"],
            "evidence_roots":entry["evidence"], "created_at":entry["created_at"]}
            for entry in entries]}


def _humanized_workshop_participant_label(root, roots):
    """Suffix distinct colliding roots, with a finite full-digest fallback."""
    from .universal_application import _humanize_root_id

    base = _humanize_root_id(root)[:80]
    colliding_roots = sorted(
        candidate for candidate in set(roots)
        if _humanize_root_id(candidate)[:80] == base
    )
    if len(colliding_roots) < 2:
        return base
    digests = {candidate: hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        for candidate in colliding_roots}
    for prefix_length in range(8, 65):
        if len({digest[:prefix_length] for digest in digests.values()}) == len(digests):
            return base + "-" + digests[root][:prefix_length]
    # A real full-digest collision must still distinguish exact identities.
    # Sorted distinct roots make the ordinal independent of participant order.
    return base + "-" + digests[root] + "-" + str(colliding_roots.index(root) + 1)


def _workshop_participant_rows(owner, snapshot, space, connections):
    from .cell_agent_body import read_agent_session
    registry = owner.universal_registry
    rows = []
    for root in space.participant_roots:
        runtime_session = root.startswith("app:agent-session:runtime:")
        row = {"root": root, "label": _humanized_workshop_participant_label(root, space.participant_roots),
               "attached": True, "is_agent": runtime_session,
               "connection_status": "disconnected" if runtime_session else "unknown"}
        if runtime_session and root in connections:
            session = read_agent_session(snapshot, registry.agent_body.protocol,
                                         registry.authorization.protocol, root)
            row.update(connections[root])
            if session.state_root != registry.agent_body.protocol.state("active"):
                row["connection_status"] = "disconnected"
        rows.append(row)
    return rows


def _workshop_position_token(prefix, positions, identity):
    # A cache/position hint, never a credential. Current graph admission still
    # surrounds every read, including conditional responses with no bodies.
    material = json.dumps([prefix, identity, *positions], separators=(",", ":"))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return ":".join((prefix, *(str(value) for value in positions), digest))


def _workshop_token_positions(token, prefix, count):
    if type(token) is not str or len(token) > 128:
        raise InvalidCell("Workshop read position is invalid")
    parts = token.split(":")
    if (len(parts) != count + 2 or parts[0] != prefix
            or not re.fullmatch(r"[a-f0-9]{64}", parts[-1])
            or any(not re.fullmatch(r"0|[1-9][0-9]{0,18}", value) for value in parts[1:-1])):
        raise InvalidCell("Workshop read position is invalid")
    positions = tuple(int(value) for value in parts[1:-1])
    if any(value > 2**63 - 1 for value in positions):
        raise InvalidCell("Workshop read position exceeds its limit")
    return positions


def _read_ordinary_browser_workshop(owner, binding, *, root, scope, expected_revision, session_token,
                                    content_after=None, before=None, connections=None, feed='all'):
    """Keep graph/scope authority stable through ordinary-page projection."""
    from .conversation_content import read_content_binding
    registry, store = owner.universal_registry, owner.universal_store
    authority = registry.authorization
    service = getattr(owner, "conversation_content", None)
    if service is None or not service.belongs_to(store, registry):
        raise InvalidCell("ordinary Workshop read requires its current owner")
    with owner.mutation_lock:
        with authority.broker.live_context(binding.context):
            with store.stable_snapshot(expected_revision=expected_revision):
                snapshot, space = _admit(owner, binding, root, scope, allow_child=True)
                content_binding = read_content_binding(snapshot, registry.deliberation_protocol,
                    application_root=registry.application_root, space_root=root)
                identity = [registry.application_root, content_binding.instance_id, root, scope,
                    binding.subject_root, binding.view_root,
                    binding.subject_root == authority.subject_root]
                # Re-admit graph authority on every read, but do not invalidate
                # an ordinary content position for unrelated graph writes.
                # Never reuse a cursor between feeds. Filtering is in storage
                # before paging and audience selection, not on a recent tail.
                if feed != 'all':
                    identity.append(feed)
                before_sequence = None
                before_generation = None
                if before is not None:
                    page_prefix = "p2" if isinstance(before, str) and before.startswith("p2:") else "p1"
                    page_positions = _workshop_token_positions(before, page_prefix, 2 if page_prefix == "p2" else 1)
                    before_sequence = page_positions[0]
                    before_generation = page_positions[1] if page_prefix == "p2" else 0
                    if before_sequence < 1:
                        raise InvalidCell("Workshop older-page position must be positive")
                    if before != _workshop_position_token(page_prefix, page_positions, identity):
                        raise AuthorizationDenied("Workshop page changed; return to latest messages")
                if_visible_head = None
                if_content_generation = None
                if content_after is not None:
                    content_prefix = "c2" if isinstance(content_after, str) and content_after.startswith("c2:") else "c1"
                    positions = _workshop_token_positions(content_after, content_prefix, 3 if content_prefix == "c2" else 2)
                    if (positions[1] == (before_sequence or 0)
                            and content_after == _workshop_position_token(content_prefix, positions, identity)):
                        if_visible_head = positions[0]
                        if content_prefix == "c2":
                            if_content_generation = positions[2]
                page = service.page_for_workshop_browser(session_token, binding=binding, space_root=root,
                    before=before_sequence, if_visible_head=if_visible_head,
                    **({'category': registry.workshop_category_roots[
                        'note' if feed == 'messages' else 'tool']} if feed != 'all' else {}),
                    **({"if_content_generation": if_content_generation}
                       if if_content_generation is not None else {}))
                if page["graph_revision"] != snapshot.revision:
                    raise AuthorizationDenied("Workshop changed during read")
                generation = page.get("content_generation", 0)
                if type(generation) is not int or not 0 <= generation <= 2**63 - 1:
                    raise InvalidCell("Workshop content generation is invalid")
                if before_generation is not None and before_generation != generation:
                    raise AuthorizationDenied("Workshop history changed; return to latest messages")
                def page_token(sequence):
                    return _workshop_position_token("p2" if generation else "p1",
                        (sequence, generation) if generation else (sequence,), identity)
                header = {"ok": True, "graph_id": registry.application_root, "root": root,
                    "scope_root": scope, "revision": snapshot.revision, "storage": "conversation-content",
                    "feed": feed,
                    "content_generation": generation,
                    "participants": _workshop_participant_rows(owner, snapshot, space, connections or {}),
                    "page_before": before,
                    "content_cursor": _workshop_position_token("c2" if generation else "c1",
                        (page["visible_head"], before_sequence or 0, generation) if generation
                        else (page["visible_head"], before_sequence or 0), identity)}
                if page.get("unchanged") is True:
                    if header["content_cursor"] != content_after:
                        raise InvalidCell("Workshop unchanged position does not match")
                    result = {**header, "unchanged": True}
                    if owner._resolve_browser_session(session_token) != binding:
                        raise AuthorizationDenied("Workshop browser binding changed during read")
                    _admit(owner, binding, root, scope, allow_child=True)
                    authority.broker.resolve(binding.context)
                    return result
                categories = {value: key for key, value in registry.workshop_category_roots.items()}
                decision = authorize_node_request(snapshot, authority.protocol, space.policy_root,
                    authority.broker, binding.context, AuthorizationRequest(action_root=space.action_root,
                        object_root=root, resource_lineage_roots=space.scope_roots,
                        interface_root=space.interface_root, purpose_root=space.purpose_root,
                        classification_root=space.classification_root, audience_root=space.audience_root,
                        lifecycle_state_root=space.lifecycle_root,
                        operational_state_root=space.operational_state_root))
                result = {**header,
                    "owner": binding.subject_root, "view": binding.view_root, "self": binding.subject_root,
                    "can_join": False, "can_send": decision.allowed and binding.subject_root in space.participant_roots,
                    "can_manage_history": binding.subject_root == authority.subject_root and binding.subject_root in space.participant_roots,
                    "send_category": "note", "execution_nodes": [], "total": page["total"],
                    "has_older": page["has_older"],
                    "next_before": (page_token(page["messages"][0]["sequence"])
                        if page["has_older"] else None),
                    "messages": [{"root": row["id"], "message_id": row["id"], "sequence": row["sequence"],
                        "sender_root": row["author"],
                        "recipient_root": ", ".join(row["recipients"]) or "Everyone",
                        "recipient_roots": row["recipients"], "body": row["content"],
                        "category": categories.get(row["category"], row["category"]), "state": "recorded",
                        "reply_to_root": row["reply_to"], "reference_roots": row["refs"],
                        "evidence_roots": row["evidence"], "created_at": row["created_at"]}
                        for row in page["messages"]]}
                # Match the actual HTTP encoder (including escaped Unicode).
                # Keep the newest complete messages within the final UI budget.
                encoded_size = lambda value: len(json.dumps(value, separators=(",", ":")).encode())
                used = encoded_size({**result, "messages": []})
                retained = []
                for message in reversed(result["messages"]):
                    cost = encoded_size(message) + (1 if retained else 0)
                    if used + cost > 262144:
                        break
                    retained.append(message)
                    used += cost
                if len(retained) < len(result["messages"]):
                    result["has_older"] = True
                result["messages"] = list(reversed(retained))
                if result["has_older"] and result["messages"]:
                    result["next_before"] = page_token(result["messages"][0]["sequence"])
                # The retained cursor can grow by a digit after byte trimming.
                # Reconcile the final complete envelope, never split a message.
                while encoded_size(result) > 262144 and len(result["messages"]) > 1:
                    result["messages"].pop(0)
                    result["has_older"] = True
                    result["next_before"] = page_token(result["messages"][0]["sequence"])
                if (page["messages"] and not retained) or encoded_size(result) > 262144:
                    raise InvalidCell("Workshop response exceeds its byte budget")
                if owner._resolve_browser_session(session_token) != binding:
                    raise AuthorizationDenied("Workshop browser binding changed during read")
                _admit(owner, binding, root, scope, allow_child=True)
                authority.broker.resolve(binding.context)
                return result


def disconnect_browser_workshop_agent(owner, binding, body, *, browser_guard):
    """Disconnect one admitted agent's Session Link channel for the application owner.

    Admission and authorization run under the owner lock; the native wait that
    retires the channel does not, and nothing is written after it. Other agents,
    the graph and history are unchanged. This revokes only that agent's Session
    Link grant: it does not end the machine Agent Session enrolment or cancel a
    request already delivered. A retiring or uncertain channel can be retried.
    """
    from .cell_agent_body import read_agent_session
    from .universal_application import _require_application_authorization
    if (type(body) is not dict or set(body) != {"action", "root", "scope", "revision", "agent"}
            or body["action"] != "agent-disconnect"):
        raise InvalidCell("Workshop agent disconnect fields are invalid")
    agent, expected = body["agent"], body["revision"]
    if (type(agent) is not str or not agent.startswith("app:agent-session:runtime:")
            or type(expected) is not int or expected < 0):
        raise InvalidCell("Workshop agent disconnect values are invalid")
    registry = owner.universal_registry
    relay = getattr(owner, "native_recipient_relay", None)
    if relay is None:
        raise InvalidCell("Session Link relay is unavailable")
    with owner.mutation_lock:
        browser_guard()
        snapshot, space = _admit(owner, binding, body["root"], body["scope"])
        if snapshot.revision != expected:
            raise AuthorizationDenied("Workshop changed; refresh before disconnecting an agent")
        if agent not in space.participant_roots:
            raise AuthorizationDenied("Agent is not a participant of this Workshop")
        session = read_agent_session(snapshot, registry.agent_body.protocol,
                                     registry.authorization.protocol, agent)
        if session.subject_root != registry.authorization.subject_root:
            raise AuthorizationDenied("Agent Session subject is not admitted")
        _require_application_authorization(snapshot, registry, "execute", agent,
                                           authentication_context=binding.context)
    result = relay.detach_channel(agent)
    # The outcome comes only from this call's own result, never from an earlier state
    # read another attach could have overtaken. Only a joined local call counts.
    settled = result.get("status") == "ok" and result.get("local_call_joined") is True
    if settled and result.get("detached") is True and result.get("revoked") is True:
        outcome = "revoked"
    elif settled and result.get("detached") is True:
        outcome = "detached_without_revocation"
    elif settled and result.get("detached") is False and result.get("revoked") is False:
        outcome = "no_channel"
    else:
        outcome = "uncertain"
    return {"ok": True, "graph_id": registry.application_root, "root": body["root"],
            "scope_root": body["scope"], "agent": agent, "revision": expected, "disconnect": result,
            "outcome": outcome, "session_link": relay.channel_states().get(agent, "none")}


def _relay_native_recipients(owner, space_root, message_id, sender_root, recipient_roots, text):
    """Start the owner's native relay for a stored message; no relay, no change."""
    relay = getattr(owner, "native_recipient_relay", None)
    rows = None if relay is None else relay.request(space_root=space_root,
        message_id=message_id, sender_root=sender_root,
        recipient_roots=tuple(recipient_roots), text=text)
    return {} if rows is None else {"native_delivery": rows}


def send_browser_workshop(owner, binding, body):
    from .universal_application import append_universal_workshop_entry, validate_universal_workshop_entry_content
    from .conversation_content import workshop_message_identity
    expected = {"root", "scope", "category", "text", "refs", "evidence", "recipients",
        "reply_to", "idempotency_key", "created_at"}
    if type(body) is not dict or set(body) != expected:
        raise InvalidCell("Workshop message fields are invalid")
    if (body["category"] != "note" or body["refs"] != [] or body["evidence"] != [] or
            body["reply_to"] is not None or body["created_at"] is not None or
            type(body["recipients"]) is not list or len(body["recipients"]) != 1 or
            any(type(value) is not str or not value for value in body["recipients"]) or
            type(body["idempotency_key"]) is not str or not 1 <= len(body["idempotency_key"]) <= 128):
        raise InvalidCell("Workshop message values are invalid")
    _snapshot, _space = _admit(owner, binding, body["root"], body["scope"], allow_child=True)
    registry = owner.universal_registry
    if body["root"] != registry.workshop_root:
        service = getattr(owner, "conversation_content", None)
        if service is None or not service.belongs_to(owner.universal_store, registry):
            raise InvalidCell("Conversation content requires its current owner")
        result = service.append_authenticated(space_root=body["root"],
            actor_root=binding.subject_root, category_root=registry.workshop_category_roots["note"],
            content=validate_universal_workshop_entry_content(body["text"]),
            idempotency_key=body["idempotency_key"],
            recipient_roots=tuple(body["recipients"]), authentication_context=binding.context,
            expected_revision=_snapshot.revision)
        message = result["message"]
        relay = _relay_native_recipients(owner, body["root"], message["id"], message["author"],
            message["recipients"], message["content"])
        return {"ok":True, "workshop":body["root"], "root":message["id"],
            "message_id":message["id"], "storage":"conversation-content",
            "idempotency_key":message["idempotency_key"], "revision":result["graph_revision"], **relay}
    entry = append_universal_workshop_entry(owner.universal_store, registry,
        actor_root=binding.subject_root, category_root=registry.workshop_category_roots["note"],
        content=validate_universal_workshop_entry_content(body["text"]),
        idempotency_key=body["idempotency_key"], created_at=None,
        recipient_roots=tuple(body["recipients"]), authentication_context=binding.context,
        expected_revision=_snapshot.revision,
        content_service=getattr(owner, "conversation_content", None))
    relay = (_relay_native_recipients(owner, entry.space_root, entry.message_id, entry.actor_root,
        entry.recipient_roots, entry.content) if hasattr(entry, "message_id") else {})
    return {"ok":True, "workshop":registry.workshop_root, **workshop_message_identity(entry),
        "idempotency_key":entry.idempotency_key, "revision":owner.universal_store.revision, **relay}


def approve_browser_workshop_model(owner, binding, body, *, _inspect_only=False):
    """Approve one reviewed delegation through the authenticated founder view.

    The HTTP boundary must require CSRF and an explicit POST. This function
    never enrolls a machine client, obtains an execution token or runs a model.
    """
    from .cell_adapters import read_permission, grant_permission
    from .cell_model_execution import read_model_delegation
    from .cell_agent_body import read_agent_session
    from .universal_application import (
        _require_application_authorization, _view_session_for_context,
        _session_canvas_roots, _cached_authority_snapshot,
    )
    fields = {"root", "scope", "work", "delegation", "input_digest", "revision"}
    if type(body) is not dict or set(body) != fields or type(body["revision"]) is not int:
        raise InvalidCell("Workshop approval fields are invalid")
    if (any(type(body[key]) is not str or not body[key] or len(body[key]) > 4096
            for key in ("root", "scope", "work", "delegation"))
            or type(body["input_digest"]) is not str or len(body["input_digest"]) != 64
            or any(char not in "0123456789abcdef" for char in body["input_digest"])):
        raise InvalidCell("Workshop approval references are invalid")
    snapshot, _space = _admit(owner, binding, body["root"], body["scope"])
    registry, store = owner.universal_registry, owner.universal_store
    identity = registry.authorization.broker.resolve(binding.context)
    if binding.subject_root != registry.authorization.subject_root or identity.subject_root != binding.subject_root:
        raise AuthorizationDenied("Workshop model approval requires the authenticated founder")
    if not _inspect_only and snapshot.revision != body["revision"]:
        raise InvalidCell("Workshop changed since review; refresh before approving")
    founder = read_agent_session(snapshot, registry.agent_body.protocol,
        registry.authorization.protocol, registry.agent_body.session.root_id)
    if (founder.subject_root != binding.subject_root or founder.body_root != registry.agent_body.body.root_id
            or founder.state_root != registry.agent_body.protocol.state("active")):
        raise AuthorizationDenied("Founder approval session is not active")
    view, context = _view_session_for_context(registry, binding.context)
    visible, _relations, _properties, _trail = _session_canvas_roots(snapshot, registry, view,
        include_trail=True, authority_snapshot=_cached_authority_snapshot(snapshot, registry.authorization))
    if body["work"] not in visible:
        raise AuthorizationDenied("Approval Work is no longer on this canvas")
    delegation = read_model_delegation(snapshot, registry.baboom_model_execution_protocol,
        registry.adapter_protocol, body["delegation"])
    if (delegation.work_root != body["work"] or delegation.input_digest != body["input_digest"]
            or (not _inspect_only and time.time() >= delegation.expires_at)):
        raise AuthorizationDenied("Reviewed model delegation changed or expired")
    for target in (delegation.work_root, delegation.root_id):
        _require_application_authorization(snapshot, registry, "execute", target,
            authentication_context=context, resource_lineage_roots=(delegation.work_root,))
    permission = read_permission(snapshot, registry.adapter_protocol, delegation.permission_root)
    if permission.user_root != founder.subject_root:
        raise AuthorizationDenied("Model permission belongs to another user")
    if _inspect_only:
        if store.revision != snapshot.revision:
            raise AuthorizationDenied("Workshop changed during approval read; refresh")
        return {"ok":True, "approved":permission.lifecycle_root == registry.adapter_protocol.states["granted"],
            "awaiting_approval":permission.lifecycle_root == registry.adapter_protocol.states["requested"],
            "expired":time.time() >= delegation.expires_at,
            "delegation":delegation.root_id, "work":delegation.work_root,
            "input_digest":delegation.input_digest, "model":delegation.model,
            "revision":snapshot.revision}
    gesture = owner.adapter_consent_broker.mint_from_user_gesture(delegation.permission_root, founder.subject_root)
    grant_permission(store, registry.adapter_protocol, registry.baboom_model_execution_adapter_catalog_root,
        delegation.permission_root, owner.adapter_consent_broker, gesture,
        expected_revision=snapshot.revision)
    return {"ok":True, "approved":True, "delegation":delegation.root_id,
        "work":delegation.work_root, "input_digest":delegation.input_digest, "revision":store.revision}


def read_browser_workshop_model_approval(owner, binding, fields):
    """Reconcile exact approval state after a lost response; never grant or run."""
    if type(fields) is not dict or set(fields) != {"root", "scope", "work", "delegation", "input_digest"}:
        raise InvalidCell("Workshop approval query is invalid")
    return approve_browser_workshop_model(owner, binding, {**fields, "revision":0}, _inspect_only=True)
