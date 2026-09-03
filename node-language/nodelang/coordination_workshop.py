"""Graph-native planning, assignment, evidence, review, and reporting assemblies."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
import uuid

from .unified_authority import (
    CallerCommandCapability,
    CommandResult,
    UnifiedAuthority,
    composition_root,
    create_relation_node,
    declare_definition,
    instantiate_definition,
    promote_definition,
    published_definition_named,
    read_contained_scope,
    revise_instance,
)
from .universal_cell import InvalidCell


PROVENANCE = {
    "archhub-specification": "SPEC.md sections 5, 9, 10, and 11",
    "w3c-prov-o": "https://www.w3.org/TR/prov-o/",
    "nist-ai-rmf": "https://airc.nist.gov/airmf-resources/airmf/5-sec-core/",
    "mcp-tasks-boundary": (
        "https://modelcontextprotocol.io/specification/2025-11-25/"
        "basic/utilities/tasks"
    ),
    "a2a-task-boundary": "https://a2a-protocol.org/latest/definitions/",
}


@dataclass(frozen=True, slots=True)
class WorkshopCatalogue:
    plan_definition: str
    assignment_definition: str
    evidence_definition: str
    review_definition: str
    message_definition: str


@dataclass(frozen=True, slots=True)
class CoordinationMessageProjection:
    root_id: str
    sender_root: str
    recipient_root: str
    reply_to_root: str | None
    category: str
    body: str
    state: str
    created_revision: int
    current_revision: int


def _subcommand(operation_id: str, label: str) -> str:
    try:
        namespace = uuid.UUID(operation_id)
    except (TypeError, ValueError) as exc:
        raise InvalidCell("workshop operation identity is invalid") from exc
    return str(uuid.uuid5(namespace, label))


def _publish_definition(
    authority: UnifiedAuthority,
    *,
    operation_id: str,
    key: str,
    name: str,
    defaults: Mapping[str, object],
    parameters: Mapping[str, object],
    rules: Mapping[str, object],
    presentation: Mapping[str, object],
    courts: Mapping[str, object],
    caller: CallerCommandCapability,
) -> str:
    held = published_definition_named(authority, name, caller=caller)
    if held is not None:
        return held
    declared = declare_definition(
        authority,
        name,
        defaults,
        parameters=parameters,
        rules=rules,
        presentation=presentation,
        courts=courts,
        provenance=PROVENANCE,
        caller=caller,
        command_id=_subcommand(operation_id, key + ":declare"),
    )
    shared = promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="shared",
        version="1-shared",
        evidence_roots=(declared.receipt_root,),
        caller=caller,
        command_id=_subcommand(operation_id, key + ":share"),
    )
    published = promote_definition(
        authority,
        declared.root_id,
        target_lifecycle="published",
        version="1",
        evidence_roots=(shared.receipt_root,),
        caller=caller,
        command_id=_subcommand(operation_id, key + ":publish"),
    )
    return published.root_id


def install_workshop_catalogue(
    authority: UnifiedAuthority,
    *,
    operation_id: str,
    caller: CallerCommandCapability,
) -> WorkshopCatalogue:
    """Publish reusable coordination assemblies into the one graph catalogue."""
    plan = _publish_definition(
        authority,
        operation_id=operation_id,
        key="coordination-plan",
        name="Coordination plan",
        defaults={"state": "draft", "title": "Untitled coordination plan"},
        parameters={
            "state": {
                "type": "text",
                "options": ["draft", "accepted", "cancelled"],
                "editor": "choice",
            },
            "title": {"type": "text", "editor": "text"},
        },
        rules={
            "state_parameter": "state",
            "transitions": {
                "accepted": {
                    "from": ["draft"],
                    "required_connections": [
                        "objective",
                        "authority",
                        "research",
                        "architect",
                        "critique",
                        "builder",
                        "verifier",
                        "steward",
                        "red-court",
                        "task-graph",
                    ],
                    "distinct_targets": [["builder", "verifier"]],
                },
                "cancelled": {"from": ["draft"]},
            },
        },
        presentation={
            "label": "Plan",
            "panels": ["Overview", "Roles", "Sources", "Courts", "History"],
        },
        courts={
            "five-stage-protocol": "required",
            "builder-verifier-independence": "required",
            "source-revision": "required",
        },
        caller=caller,
    )
    assignment = _publish_definition(
        authority,
        operation_id=operation_id,
        key="work-assignment",
        name="Work assignment",
        defaults={"state": "draft", "title": "Untitled assignment"},
        parameters={
            "state": {
                "type": "text",
                "options": [
                    "draft",
                    "assigned",
                    "working",
                    "input-required",
                    "review",
                    "accepted",
                    "rejected",
                    "failed",
                    "cancelled",
                ],
                "editor": "choice",
            },
            "title": {"type": "text", "editor": "text"},
        },
        rules={
            "state_parameter": "state",
            "transitions": {
                "assigned": {
                    "from": ["draft"],
                    "required_connections": [
                        "obligation", "assignee", "scope", "plan", "court"
                    ],
                    "target_values": {"plan": {"state": "accepted"}},
                },
                "working": {
                    "from": ["assigned"],
                    "required_connections": ["assignee"],
                    "caller_matches_connection": "assignee",
                },
                "input-required": {
                    "from": ["working"],
                    "required_connections": ["assignee"],
                    "caller_matches_connection": "assignee",
                },
                "review": {
                    "from": ["working", "input-required"],
                    "required_connections": ["assignee", "report"],
                    "caller_matches_connection": "assignee",
                },
                "accepted": {
                    "from": ["review"],
                    "required_connections": ["reviewer", "review", "evidence"],
                    "caller_matches_connection": "reviewer",
                    "distinct_targets": [["assignee", "reviewer"]],
                    "target_values": {
                        "review": {"decision": "pass"},
                        "evidence": {"status": "pass"},
                    },
                },
                "rejected": {"from": ["review"]},
                "failed": {
                    "from": ["assigned", "working", "input-required", "review"]
                },
                "cancelled": {
                    "from": ["draft", "assigned", "working", "input-required"]
                },
            },
        },
        presentation={
            "label": "Assignment",
            "panels": ["Work", "Connections", "Evidence", "History"],
        },
        courts={
            "bounded-scope": "required",
            "independent-review": "required",
            "real-artifact-evidence": "required",
        },
        caller=caller,
    )
    evidence = _publish_definition(
        authority,
        operation_id=operation_id,
        key="work-evidence",
        name="Work evidence",
        defaults={"status": "draft", "summary": "No evidence recorded"},
        parameters={
            "status": {
                "type": "text",
                "options": ["draft", "pass", "fail"],
                "editor": "choice",
            },
            "summary": {"type": "text", "editor": "text"},
        },
        rules={
            "state_parameter": "status",
            "transitions": {
                "pass": {
                    "from": ["draft"],
                    "required_connections": ["subject", "producer", "artifact"],
                    "caller_matches_connection": "producer",
                },
                "fail": {
                    "from": ["draft"],
                    "required_connections": ["subject", "producer"],
                    "caller_matches_connection": "producer",
                },
            },
        },
        presentation={
            "label": "Evidence",
            "panels": ["Result", "Artifact", "Provenance", "History"],
        },
        courts={"artifact-bound": "required", "same-revision": "required"},
        caller=caller,
    )
    review = _publish_definition(
        authority,
        operation_id=operation_id,
        key="independent-review",
        name="Independent review",
        defaults={"decision": "pending", "summary": "Review pending"},
        parameters={
            "decision": {
                "type": "text",
                "options": ["pending", "pass", "fail"],
                "editor": "choice",
            },
            "summary": {"type": "text", "editor": "text"},
        },
        rules={
            "state_parameter": "decision",
            "transitions": {
                "pass": {
                    "from": ["pending"],
                    "required_connections": ["assignment", "reviewer", "evidence"],
                    "caller_matches_connection": "reviewer",
                },
                "fail": {
                    "from": ["pending"],
                    "required_connections": ["assignment", "reviewer"],
                    "caller_matches_connection": "reviewer",
                },
            },
        },
        presentation={
            "label": "Review",
            "panels": ["Decision", "Findings", "Evidence", "History"],
        },
        courts={"reviewer-not-builder": "required", "findings-visible": "required"},
        caller=caller,
    )
    message = _publish_definition(
        authority,
        operation_id=operation_id,
        key="coordination-message",
        name="Coordination message",
        defaults={
            "state": "draft",
            "category": "message",
            "body": "New coordination message",
        },
        parameters={
            "state": {
                "type": "text",
                "options": ["draft", "sent", "read", "acted", "cancelled"],
                "editor": "choice",
            },
            "category": {
                "type": "text",
                "options": ["message", "followup", "interrupt-request"],
                "editor": "choice",
            },
            "body": {
                "type": "text",
                "minimum_length": 1,
                "maximum_length": 12_000,
                "editor": "multiline",
            },
        },
        rules={
            "state_parameter": "state",
            "transitions": {
                "sent": {
                    "from": ["draft"],
                    "required_connections": ["sender", "recipient"],
                    "caller_matches_connection": "sender",
                },
                "read": {
                    "from": ["sent"],
                    "required_connections": ["recipient"],
                    "caller_matches_connection": "recipient",
                },
                "acted": {
                    "from": ["read"],
                    "required_connections": ["recipient"],
                    "caller_matches_connection": "recipient",
                },
                "cancelled": {
                    "from": ["draft"],
                    "required_connections": ["sender"],
                    "caller_matches_connection": "sender",
                },
            },
        },
        presentation={
            "label": "Message",
            "panels": ["Message", "Participants", "Reply", "History"],
        },
        courts={
            "authenticated-sender": "required",
            "recipient-read": "required",
            "durable-reply": "required",
        },
        caller=caller,
    )
    return WorkshopCatalogue(plan, assignment, evidence, review, message)


def create_workshop_instance(
    authority: UnifiedAuthority,
    definition_root: str,
    overrides: Mapping[str, object],
    *,
    scope_root: str | None = None,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    target_scope = scope_root or composition_root(
        authority, "Workshop", caller=caller
    )
    return instantiate_definition(
        authority,
        definition_root,
        overrides,
        scope_root=target_scope,
        caller=caller,
        command_id=command_id,
    )


def connect_workshop_instance(
    authority: UnifiedAuthority,
    instance_root: str,
    connection: str,
    target_root: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
    properties: Mapping[str, object] | None = None,
) -> CommandResult:
    if not connection.strip():
        raise InvalidCell("workshop connection name is missing")
    relation_properties = dict(properties or {})
    if "connection" in relation_properties:
        raise InvalidCell("workshop connection property cannot be overridden")
    relation_properties["connection"] = connection.strip()
    return create_relation_node(
        authority,
        (("source", instance_root), ("target", target_root)),
        scope_root=instance_root,
        properties=relation_properties,
        caller=caller,
        command_id=command_id,
    )


def create_coordination_message(
    authority: UnifiedAuthority,
    catalogue: WorkshopCatalogue,
    *,
    recipient_root: str,
    body: str,
    category: str,
    operation_id: str,
    caller: CallerCommandCapability,
    reply_to_root: str | None = None,
) -> CommandResult:
    """Create, wire, and send one authenticated Workshop message assembly."""
    message = create_workshop_instance(
        authority,
        catalogue.message_definition,
        {"body": body, "category": category},
        caller=caller,
        command_id=_subcommand(operation_id, "message:create"),
    )
    connect_workshop_instance(
        authority,
        message.root_id,
        "sender",
        caller.session_root,
        caller=caller,
        command_id=_subcommand(operation_id, "message:sender"),
    )
    connect_workshop_instance(
        authority,
        message.root_id,
        "recipient",
        recipient_root,
        caller=caller,
        command_id=_subcommand(operation_id, "message:recipient"),
    )
    if reply_to_root is not None:
        connect_workshop_instance(
            authority,
            message.root_id,
            "reply-to",
            reply_to_root,
            caller=caller,
            command_id=_subcommand(operation_id, "message:reply-to"),
        )
    return transition_workshop_instance(
        authority,
        message.root_id,
        "state",
        "sent",
        caller=caller,
        command_id=_subcommand(operation_id, "message:send"),
    )


def read_coordination_messages(
    authority: UnifiedAuthority,
    catalogue: WorkshopCatalogue,
    *,
    caller: CallerCommandCapability,
    recipient_root: str | None = None,
    after_revision: int = 0,
) -> tuple[CoordinationMessageProjection, ...]:
    """Read revision-ordered messages directly from the Workshop graph."""
    if type(after_revision) is not int or after_revision < 0:
        raise InvalidCell("message revision cursor is invalid")
    target = caller.session_root if recipient_root is None else recipient_root
    workshop = composition_root(authority, "Workshop", caller=caller)
    projection = read_contained_scope(
        authority,
        workshop,
        scope_root=workshop,
        caller=caller,
    )
    output: list[CoordinationMessageProjection] = []
    for root, instance in projection.instances.items():
        if instance.get("definition") != catalogue.message_definition:
            continue
        connections: dict[str, str] = {}
        for relation in projection.relations.values():
            if ("source", root) not in relation.participants:
                continue
            connection = relation.properties.get("connection")
            targets = tuple(
                value for role, value in relation.participants if role == "target"
            )
            if type(connection) is not str or len(targets) != 1:
                raise InvalidCell("coordination message connection is invalid")
            if connection in connections:
                raise InvalidCell("coordination message connection is duplicated")
            connections[connection] = targets[0]
        if set(("sender", "recipient")) - set(connections):
            raise InvalidCell("coordination message participants are incomplete")
        if connections["recipient"] != target:
            continue
        created_revision = authority.store.cell_created_revision(root)
        if created_revision <= after_revision:
            continue
        values = instance.get("values")
        if not isinstance(values, Mapping) or any(
            type(values.get(name)) is not str
            for name in ("state", "category", "body")
        ):
            raise InvalidCell("coordination message values are invalid")
        output.append(CoordinationMessageProjection(
            root,
            connections["sender"],
            connections["recipient"],
            connections.get("reply-to"),
            str(values["category"]),
            str(values["body"]),
            str(values["state"]),
            created_revision,
            projection.revision,
        ))
    return tuple(sorted(output, key=lambda item: (item.created_revision, item.root_id)))


def transition_coordination_message(
    authority: UnifiedAuthority,
    message_root: str,
    state: str,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    return transition_workshop_instance(
        authority,
        message_root,
        "state",
        state,
        caller=caller,
        command_id=command_id,
    )


def transition_workshop_instance(
    authority: UnifiedAuthority,
    instance_root: str,
    field: str,
    value: str,
    *,
    workshop_scope: str | None = None,
    caller: CallerCommandCapability,
    command_id: str,
) -> CommandResult:
    scope = workshop_scope or composition_root(
        authority, "Workshop", caller=caller
    )
    return revise_instance(
        authority,
        instance_root,
        {field: value},
        scope_root=scope,
        caller=caller,
        command_id=command_id,
    )


def read_workshop_instance(
    authority: UnifiedAuthority,
    instance_root: str,
    *,
    caller: CallerCommandCapability,
) -> Mapping[str, object]:
    projection = read_contained_scope(
        authority,
        instance_root,
        scope_root=instance_root,
        caller=caller,
    )
    instance = projection.instances.get(instance_root)
    if instance is None:
        raise InvalidCell("workshop root is not an instance")
    return MappingProxyType({
        "instance": instance,
        "relations": projection.relations,
        "revision": projection.revision,
    })


__all__ = [
    "CoordinationMessageProjection",
    "WorkshopCatalogue",
    "connect_workshop_instance",
    "create_coordination_message",
    "create_workshop_instance",
    "install_workshop_catalogue",
    "read_coordination_messages",
    "read_workshop_instance",
    "transition_coordination_message",
    "transition_workshop_instance",
]
