"""Provider-neutral Agent Session assemblies on the clean Universal authority."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
import uuid

from .unified_authority import (
    CallerCommandCapability,
    UnifiedAuthority,
    composition_root,
    create_relation_node,
    declare_definition,
    enroll_session,
    instantiate_definition,
    promote_definition,
    read_contained_scope,
    revise_instance,
)
from .universal_cell import InvalidCell


PROVENANCE = {
    "archhub-specification": "SPEC.md sections 4.4, 4.5, 5, and 9",
    "a2a-task-lifecycle": "https://a2a-protocol.org/latest/definitions/",
    "mcp-authorization-boundary": (
        "https://modelcontextprotocol.io/specification/2025-11-25/"
        "basic/authorization"
    ),
}


@dataclass(frozen=True, slots=True)
class AgentSessionCatalogue:
    definition_root: str


@dataclass(frozen=True, slots=True)
class AgentSessionBundle:
    definition_root: str
    session_root: str
    state_root: str


@dataclass(frozen=True, slots=True)
class AgentSessionProjection:
    bundle: AgentSessionBundle
    status: str
    runtime: str
    provider: str
    model: str
    revision: int


def _subcommand(operation_id: str, label: str) -> str:
    try:
        namespace = uuid.UUID(operation_id)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("agent session operation identity is invalid") from exc
    return str(uuid.uuid5(namespace, label))


def install_agent_session_catalogue(
    authority: UnifiedAuthority,
    *,
    operation_id: str,
    caller: CallerCommandCapability,
) -> AgentSessionCatalogue:
    """Publish the reusable visible state carried by every provider session."""
    declared = declare_definition(
        authority,
        "Agent session state",
        {
            "status": "enrolled",
            "runtime": "unbound",
            "provider": "unbound",
            "model": "provider-selected",
        },
        parameters={
            "status": {
                "type": "text",
                "options": [
                    "enrolled",
                    "online",
                    "busy",
                    "input-required",
                    "offline",
                    "closed",
                ],
                "editor": "choice",
            },
            "runtime": {"type": "text", "editor": "text"},
            "provider": {"type": "text", "editor": "text"},
            "model": {"type": "text", "editor": "text"},
        },
        interfaces={
            "identity": {"direction": "input", "required": True},
            "scope": {"direction": "input", "multiple": True},
            "capability": {"direction": "input", "multiple": True},
            "focus": {"direction": "input", "multiple": True},
            "obligation": {"direction": "input", "multiple": True},
            "context": {"direction": "input", "multiple": True},
            "proposal": {"direction": "output", "multiple": True},
            "evidence": {"direction": "output", "multiple": True},
            "cost": {"direction": "output", "multiple": True},
        },
        rules={
            "state_parameter": "status",
            "transitions": {
                "online": {
                    "from": ["enrolled", "offline", "busy", "input-required"],
                    "required_connections": ["identity"],
                    "caller_matches_connection": "identity",
                },
                "busy": {
                    "from": ["online"],
                    "required_connections": ["identity"],
                    "caller_matches_connection": "identity",
                },
                "input-required": {
                    "from": ["busy"],
                    "required_connections": ["identity"],
                    "caller_matches_connection": "identity",
                },
                "offline": {
                    "from": ["enrolled", "online", "busy", "input-required"],
                    "required_connections": ["identity"],
                    "caller_matches_connection": "identity",
                },
                "closed": {
                    "from": [
                        "enrolled", "online", "busy", "input-required", "offline"
                    ],
                    "required_connections": ["identity"],
                    "caller_matches_connection": "identity",
                },
            },
        },
        presentation={
            "label": "Agent Session",
            "panels": [
                "Session",
                "Scope",
                "Capabilities",
                "Focus",
                "Work",
                "Evidence",
                "History",
            ],
        },
        courts={
            "credential-bound": "required",
            "provider-neutral": "required",
            "revocation": "required",
            "independent-review": "required",
        },
        provenance=PROVENANCE,
        caller=caller,
        command_id=_subcommand(operation_id, "declare"),
    )
    shared = promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="shared",
        version="1-shared",
        evidence_roots=(declared.receipt_root,),
        caller=caller,
        command_id=_subcommand(operation_id, "share"),
    )
    published = promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="published",
        version="1",
        evidence_roots=(shared.receipt_root,),
        caller=caller,
        command_id=_subcommand(operation_id, "publish"),
    )
    return AgentSessionCatalogue(published.root_id)


def create_agent_session(
    authority: UnifiedAuthority,
    catalogue: AgentSessionCatalogue,
    *,
    label: str,
    runtime: str,
    provider: str,
    model: str,
    public_key: bytes,
    operation_id: str,
    caller: CallerCommandCapability,
) -> AgentSessionBundle:
    """Create one credentialed composition with one visible catalogue state."""
    values = {
        "runtime": str(runtime).strip().lower(),
        "provider": str(provider).strip().lower(),
        "model": str(model).strip(),
    }
    if any(not value or len(value) > 256 for value in values.values()):
        raise InvalidCell("agent session descriptor is invalid")
    sessions = composition_root(authority, "Agent Sessions", caller=caller)
    enrollment = enroll_session(
        authority,
        label,
        public_key,
        session_container_root=sessions,
        caller=caller,
        command_id=_subcommand(operation_id, "enroll"),
    )
    state = instantiate_definition(
        authority,
        catalogue.definition_root,
        values,
        scope_root=enrollment.root_id,
        caller=caller,
        command_id=_subcommand(operation_id, "state"),
    )
    create_relation_node(
        authority,
        (("source", state.root_id), ("target", enrollment.root_id)),
        scope_root=state.root_id,
        properties={"connection": "identity"},
        caller=caller,
        command_id=_subcommand(operation_id, "identity"),
    )
    return AgentSessionBundle(
        catalogue.definition_root,
        enrollment.root_id,
        state.root_id,
    )


def transition_agent_session(
    authority: UnifiedAuthority,
    bundle: AgentSessionBundle,
    status: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
):
    return revise_instance(
        authority,
        bundle.state_root,
        {"status": status},
        scope_root=bundle.session_root,
        caller=caller,
        command_id=command_id,
    )


def read_agent_session(
    authority: UnifiedAuthority,
    bundle: AgentSessionBundle,
    *,
    caller: CallerCommandCapability,
) -> Mapping[str, object]:
    projection = read_contained_scope(
        authority,
        bundle.session_root,
        scope_root=bundle.session_root,
        caller=caller,
    )
    state = projection.instances.get(bundle.state_root)
    if state is None:
        raise InvalidCell("agent session state is not inside its session composition")
    identity_relations = tuple(
        relation
        for relation in projection.relations.values()
        if relation.properties.get("connection") == "identity"
        and ("source", bundle.state_root) in relation.participants
        and ("target", bundle.session_root) in relation.participants
    )
    if len(identity_relations) != 1:
        raise InvalidCell("agent session identity connection is invalid")
    return MappingProxyType({
        "session_root": bundle.session_root,
        "state_root": bundle.state_root,
        "state": state,
        "revision": projection.revision,
    })


def list_agent_sessions(
    authority: UnifiedAuthority,
    catalogue: AgentSessionCatalogue,
    *,
    caller: CallerCommandCapability,
) -> tuple[AgentSessionProjection, ...]:
    """Project the credentialed session assemblies in the shared container."""
    sessions = composition_root(authority, "Agent Sessions", caller=caller)
    projection = read_contained_scope(
        authority,
        sessions,
        scope_root=sessions,
        caller=caller,
    )
    output: list[AgentSessionProjection] = []
    for state_root, state in projection.instances.items():
        if state.get("definition") != catalogue.definition_root:
            continue
        identities = tuple(
            relation
            for relation in projection.relations.values()
            if relation.properties.get("connection") == "identity"
            and ("source", state_root) in relation.participants
        )
        if len(identities) != 1:
            raise InvalidCell("agent session has no unique identity connection")
        targets = tuple(
            target
            for role, target in identities[0].participants
            if role == "target"
        )
        if len(targets) != 1:
            raise InvalidCell("agent session identity target is invalid")
        values = state.get("values")
        if not isinstance(values, Mapping):
            raise InvalidCell("agent session state values are invalid")
        required = ("status", "runtime", "provider", "model")
        if any(type(values.get(name)) is not str for name in required):
            raise InvalidCell("agent session state is incomplete")
        bundle = AgentSessionBundle(
            catalogue.definition_root,
            targets[0],
            state_root,
        )
        output.append(AgentSessionProjection(
            bundle,
            str(values["status"]),
            str(values["runtime"]),
            str(values["provider"]),
            str(values["model"]),
            projection.revision,
        ))
    return tuple(sorted(output, key=lambda item: item.bundle.session_root))


__all__ = [
    "AgentSessionBundle",
    "AgentSessionCatalogue",
    "AgentSessionProjection",
    "create_agent_session",
    "install_agent_session_catalogue",
    "list_agent_sessions",
    "read_agent_session",
    "transition_agent_session",
]
