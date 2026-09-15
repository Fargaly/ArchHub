"""Explicit browser participant enrollment for the admitted application owner.

HTTP consumers must authenticate the browser token and CSRF before mutation.
The binding is graph-recorded and receipt-checked; a relation label alone grants
no authority. Reads never enroll or restore detached Workshop membership.
"""
from __future__ import annotations

import uuid
import base64

from .agent_session_catalogue import AgentSessionBundle, create_agent_session, read_agent_session
from .clean_agent_coordination import BoundAgentSession, GraphAgentCoordinator
from .unified_authority import (
    create_relation_node, digest, find_receipt, read_contained_scope,
    composition_root, attach_composition_from_scope,
)
from .universal_cell import InvalidCell


def _identity(authority, caller):
    if (caller.actor_root != authority.manifest.principal_root or
            caller.session_root != authority.manifest.bootstrap_session_root):
        raise InvalidCell("browser Workshop caller is not the admitted application owner")
    operation = str(uuid.uuid5(uuid.NAMESPACE_URL, "archhub:browser-participant:v1:" +
        digest({"graph":authority.manifest.graph_id, "owner":caller.actor_root,
            "view":caller.session_root})))
    return operation, "browser-participant." + operation


def _command(operation, label):
    return str(uuid.uuid5(uuid.UUID(operation), label))


def _participants(caller, root):
    return (("source", caller.session_root), ("target", root), ("actor", caller.actor_root))


def resolve_browser_participant(authority, sessions, workshop, key_store, *, caller):
    """Recover only the owner's explicitly authored binding, without writes."""
    operation, key_id = _identity(authority, caller)
    snapshot = authority.store.snapshot()
    def receipt(label):
        found = find_receipt(authority, snapshot, caller.actor_root, caller.session_root,
            _command(operation, label))
        if found is None or found.decision != "allow":
            raise InvalidCell("browser Workshop participant has not been attached")
        return found
    enrollment, state, binding = receipt("enroll"), receipt("state"), receipt("browser-binding")
    root = enrollment.result_root
    source = composition_root(authority, "Agent Sessions", caller=caller)
    public_key = key_store.public_key(key_id)
    if enrollment.request_digest != digest({"intent":"enroll-session", "label":"Application user",
            "public_key":base64.b64encode(public_key).decode("ascii"), "session_container":source}):
        raise InvalidCell("browser participant enrollment receipt is invalid")
    if state.request_digest != digest({"intent":"instantiate-definition",
            "definition":sessions.definition_root,
            "overrides":{"runtime":"browser", "provider":"local", "model":"human"}, "scope":root}):
        raise InvalidCell("browser participant state receipt is invalid")
    properties = {"connection":"browser-participant"}
    participants = _participants(caller, root)
    if binding.request_digest != digest({"intent":"create-relation", "participants":participants,
            "properties":properties, "scope":root}):
        raise InvalidCell("browser Workshop binding receipt is invalid")
    projection = read_contained_scope(authority, root, scope_root=root, caller=caller)
    relation = projection.relations.get(binding.result_root)
    if (relation is None or tuple(relation.participants) != participants or
            dict(relation.properties) != properties or projection.revision != snapshot.revision):
        raise InvalidCell("browser Workshop participant binding changed")
    bundle = AgentSessionBundle(sessions.definition_root, root, state.result_root)
    participant_caller = key_store.bind_session(authority, key_id, root)
    admitted = read_agent_session(authority, bundle, caller=participant_caller)
    if (admitted["state"].get("definition") != sessions.definition_root or
            admitted["revision"] != snapshot.revision):
        raise InvalidCell("browser participant definition changed")
    coordinator = GraphAgentCoordinator(authority, sessions, workshop,
        BoundAgentSession(bundle, participant_caller))
    if authority.store.revision != snapshot.revision:
        raise InvalidCell("browser participant changed during admission")
    return coordinator


def attach_browser_participant(authority, sessions, workshop, key_store, *, caller, command_id,
        _attachment_guard=None):
    """Enroll once, record owner/view binding, then explicitly attach membership."""
    GraphAgentCoordinator._require_operation_id(command_id)
    operation, key_id = _identity(authority, caller)
    prior = find_receipt(authority, authority.store.snapshot(), caller.actor_root,
        caller.session_root, _command(operation, "enroll"))
    public_key = key_store.public_key(key_id) if prior is not None else key_store.ensure(key_id)
    bundle = create_agent_session(authority, sessions, label="Application user",
        runtime="browser", provider="local", model="human", public_key=public_key,
        operation_id=operation, caller=caller)
    create_relation_node(authority, _participants(caller, bundle.session_root),
        scope_root=bundle.session_root, properties={"connection":"browser-participant"},
        caller=caller, command_id=_command(operation, "browser-binding"))
    coordinator = resolve_browser_participant(authority, sessions, workshop, key_store, caller=caller)
    source = composition_root(authority, "Agent Sessions", caller=caller)
    destination = composition_root(authority, "Workshop", caller=caller)
    revision = authority.store.revision
    if _attachment_guard is not None:
        _attachment_guard(authority, coordinator.session_root, revision)
    result = attach_composition_from_scope(authority,
        source, destination, coordinator.session_root, caller=caller, command_id=command_id,
        expected_revision=revision)
    return coordinator, result
