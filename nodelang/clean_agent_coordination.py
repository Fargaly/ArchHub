"""Provider-neutral coordination adapter over one Universal Cell authority.

The host binds one authenticated Agent Session before exposing these methods.
No tool argument can choose a sender, provider, or external session identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import uuid
import json

from .agent_session_catalogue import (
    AgentSessionBundle,
    AgentSessionCatalogue,
    AgentSessionProjection,
    list_agent_sessions,
    read_agent_session,
)
from .coordination_workshop import (
    CoordinationMessageProjection,
    WorkshopCatalogue,
    create_coordination_message,
    read_coordination_messages,
    transition_coordination_message,
    transition_workshop_instance,
)
from .unified_application_lens import (
    project_unified_scope,
    project_workshop_lens,
    scope_lens_payload,
)
from .unified_authority import (
    CallerCommandCapability,
    UnifiedAuthority,
    composition_root,
    read_scope_level,
    revise_instance,
    attach_composition_from_scope,
    remove_composition_member,
    read_instance_definition,
    digest,
    find_receipt,
)
from .universal_cell import InvalidCell


@dataclass(frozen=True, slots=True)
class BoundAgentSession:
    bundle: AgentSessionBundle
    caller: CallerCommandCapability


class GraphAgentCoordinator:
    """MCP/A2A-facing operations with graph-bound caller identity."""

    def __init__(
        self,
        authority: UnifiedAuthority,
        session_catalogue: AgentSessionCatalogue,
        workshop_catalogue: WorkshopCatalogue,
        binding: BoundAgentSession,
    ) -> None:
        if binding.caller.session_root != binding.bundle.session_root:
            raise InvalidCell("coordination caller does not match its bound session")
        read_agent_session(authority, binding.bundle, caller=binding.caller)
        self._authority = authority
        self._session_catalogue = session_catalogue
        self._workshop_catalogue = workshop_catalogue
        self._binding = binding

    @property
    def session_root(self) -> str:
        return self._binding.bundle.session_root

    def list_agents(self) -> tuple[AgentSessionProjection, ...]:
        return list_agent_sessions(
            self._authority,
            self._session_catalogue,
            caller=self._binding.caller,
        )

    def workshop_lens(self) -> dict[str, object]:
        """Project Workshop through this exact graph-bound Agent Session."""
        return scope_lens_payload(project_workshop_lens(
            self._authority,
            caller=self._binding.caller,
        ))

    def scope_lens(self, scope_root: str) -> dict[str, object]:
        """Project any admitted composition through this Agent Session."""
        if type(scope_root) is not str or not scope_root:
            raise InvalidCell("scope lens root is invalid")
        return scope_lens_payload(project_unified_scope(
            self._authority,
            scope_root,
            caller=self._binding.caller,
        ))

    def revise_visible_instance(
        self,
        instance_root: str,
        changes: dict[str, object],
        *,
        scope_root: str,
        expected_revision: int,
        command_id: str,
    ) -> dict[str, object]:
        """Revise one visible instance and return its exact accepted lens."""
        self._require_operation_id(command_id)
        if (
            type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise InvalidCell("instance revision base is invalid")
        if type(changes) is not dict:
            raise InvalidCell("instance revision changes are invalid")
        result = revise_instance(
            self._authority,
            instance_root,
            changes,
            scope_root=scope_root,
            caller=self._binding.caller,
            command_id=command_id,
            expected_revision=expected_revision,
        )
        lens = self.scope_lens(scope_root)
        current_revision = lens["revision"]
        if (
            type(current_revision) is not int
            or current_revision < result.revision
            or (not result.replayed and current_revision != result.revision)
        ):
            raise InvalidCell("instance revision lens is not exact")
        return {
            "root_id": result.root_id,
            "accepted_revision": result.revision,
            "revision": current_revision,
            "replayed": result.replayed,
            "lens": lens,
        }

    def send_message(
        self,
        *,
        target_session_root: str,
        body: str,
        operation_id: str,
        category: str = "message",
        reply_to_root: str | None = None,
        execution_root: str | None = None,
        _reply_task_binding: tuple[str, str, str | None] | None = None,
        _delivery_guard=None,
    ) -> CoordinationMessageProjection:
        self._require_session_target(target_session_root)
        self._require_operation_id(operation_id)
        result = create_coordination_message(
            self._authority,
            self._workshop_catalogue,
            recipient_root=target_session_root,
            body=body,
            category=category,
            operation_id=operation_id,
            caller=self._binding.caller,
            reply_to_root=reply_to_root,
            execution_root=execution_root,
            _reply_task_binding=_reply_task_binding,
            _delivery_guard=_delivery_guard,
        )
        messages = read_coordination_messages(
            self._authority,
            self._workshop_catalogue,
            caller=self._binding.caller,
            recipient_root=target_session_root,
        )
        selected = tuple(message for message in messages if message.root_id == result.root_id)
        if len(selected) != 1:
            raise InvalidCell("sent coordination message is not uniquely readable")
        return selected[0]

    def send_followup(
        self,
        *,
        target_session_root: str,
        body: str,
        operation_id: str,
        reply_to_root: str | None = None,
        execution_root: str | None = None,
    ) -> CoordinationMessageProjection:
        return self.send_message(
            target_session_root=target_session_root,
            body=body,
            operation_id=operation_id,
            category="followup",
            reply_to_root=reply_to_root,
            execution_root=execution_root,
        )

    def request_interrupt(
        self,
        *,
        target_session_root: str,
        reason: str,
        operation_id: str,
    ) -> CoordinationMessageProjection:
        return self.send_message(
            target_session_root=target_session_root,
            body=reason,
            operation_id=operation_id,
            category="interrupt-request",
        )

    def inbox(
        self,
        *,
        after_revision: int = 0,
    ) -> tuple[CoordinationMessageProjection, ...]:
        return read_coordination_messages(
            self._authority,
            self._workshop_catalogue,
            caller=self._binding.caller,
            after_revision=after_revision,
        )

    def mark_message_read(
        self,
        message_root: str,
        *,
        command_id: str,
    ):
        self._require_operation_id(command_id)
        return transition_coordination_message(
            self._authority,
            message_root,
            "read",
            caller=self._binding.caller,
            command_id=command_id,
        )

    def start_assignment(self, assignment_root: str, *, command_id: str):
        self._require_operation_id(command_id)
        return transition_workshop_instance(
            self._authority,
            assignment_root,
            "state",
            "working",
            caller=self._binding.caller,
            command_id=command_id,
        )

    def claim_workshop_message(self, message_root: str, *, command_id: str):
        """Claim one targeted task once; a claim is not an execution grant.

        Read/uncertain messages require reconciliation, never automatic retry.
        The physical worker must independently consume its admitted grant and
        recheck attachment immediately before invoking an external environment.
        """
        self._require_operation_id(command_id)
        messages = [message for message in self.inbox() if message.root_id == message_root]
        if len(messages) != 1:
            raise InvalidCell("Workshop task is not in this recipient's inbox")
        message = messages[0]
        if message.category != "followup" or message.state != "sent":
            raise InvalidCell("Workshop task is not an unclaimed targeted followup")
        scope = composition_root(self._authority, "Workshop", caller=self._binding.caller)
        level = read_scope_level(self._authority, scope, scope_root=scope,
            caller=self._binding.caller, budget=20_000)
        if not {message.sender_root, self.session_root} <= set(level.composition_roots):
            raise InvalidCell("Workshop task participants are detached")
        if level.revision != message.current_revision:
            raise InvalidCell("Workshop changed while the task was being claimed")
        result = transition_coordination_message(self._authority, message_root, "read",
            caller=self._binding.caller, command_id=command_id, expected_revision=level.revision)
        if result.replayed:
            raise InvalidCell("Workshop claim was already consumed; reconcile its result")
        return result

    def attach_agent(self, target_session_root: str, *, command_id: str):
        """Explicitly reference an enrolled session using both scope permissions."""
        self._require_operation_id(command_id)
        self._require_session_target(target_session_root)
        source = composition_root(self._authority, "Agent Sessions", caller=self._binding.caller)
        workshop = composition_root(self._authority, "Workshop", caller=self._binding.caller)
        return attach_composition_from_scope(self._authority, source, workshop,
            target_session_root, caller=self._binding.caller, command_id=command_id)

    def execute_claimed_task(self, message_root: str, *, invoker):
        """Execute the node connected to a claimed task, using its saved inputs.

        One task/session has one deterministic host attempt identity. This
        method neither claims tasks nor acquires a physical adapter itself.
        """
        from .clean_host_execution import execute_host_operation, node_host_arguments
        self._require_operation_id(message_root)
        if invoker is None:
            raise InvalidCell("Workshop worker has no admitted host adapter")
        def resolve():
            messages = [message for message in self.inbox() if message.root_id == message_root]
            if len(messages) != 1:
                raise InvalidCell("Workshop task is not in this worker inbox")
            message = messages[0]
            if message.category != "followup" or message.state != "read" or not message.execution_root:
                raise InvalidCell("Workshop task is not claimed with an execution connection")
            scope = composition_root(self._authority, "Workshop", caller=self._binding.caller)
            level = read_scope_level(self._authority, scope, scope_root=scope,
                caller=self._binding.caller, budget=20_000)
            if not {message.sender_root, self.session_root} <= set(level.composition_roots):
                raise InvalidCell("Workshop task participants are detached")
            if message.execution_root not in level.instances:
                raise InvalidCell("Workshop execution node is detached or not an instance")
            definition = read_instance_definition(self._authority, message.execution_root,
                scope_root=scope, caller=self._binding.caller)
            operation = definition.contracts["rules"].get("operation")
            if type(operation) is not str or not operation.strip():
                raise InvalidCell("Workshop execution node declares no operation")
            arguments, revision = node_host_arguments(self._authority, operation.strip(),
                message.execution_root, scope_root=scope, caller=self._binding.caller)
            if revision != message.current_revision or revision != level.revision:
                raise InvalidCell("Workshop task changed during execution admission")
            return message.execution_root, operation.strip(), arguments, revision
        node, operation, arguments, revision = resolve()
        admitted = digest({"node":node, "operation":operation, "arguments":arguments})
        def invoke(accepted_operation, accepted_arguments):
            current_node, current_operation, current_arguments, _ = resolve()
            if digest({"node":current_node, "operation":current_operation,
                    "arguments":current_arguments}) != admitted:
                raise InvalidCell("Workshop execution connection or inputs changed before invocation")
            return invoker(accepted_operation, accepted_arguments)
        command = str(uuid.uuid5(uuid.UUID(message_root), "workshop-execution:" + self.session_root))
        return execute_host_operation(self._authority, operation, arguments,
            caller=self._binding.caller, command_id=command, invoker=invoke,
            subject_root=node, expected_revision=revision)

    def run_workshop_task(self, message_root: str, *, command_id: str, invoker):
        """Run one explicitly selected task and publish its recorded outcome.

        No polling, fan-out, or automatic retry. Interrupted turns reconcile
        through the separate execution and publication operations.
        """
        from .clean_host_execution import HostOperationFailed
        if not callable(invoker):
            raise InvalidCell("Workshop worker has no admitted host adapter")
        self.claim_workshop_message(message_root, command_id=command_id)
        try:
            self.execute_claimed_task(message_root, invoker=invoker)
        except HostOperationFailed:
            # A recorded failure is still a result the lead needs to see.
            # Uncertain effects deliberately propagate without publication.
            pass
        return self.publish_task_result(message_root)

    def detach_agent(self, target_session_root: str, *, command_id: str):
        """Remove only Workshop membership; retain enrollment and history."""
        self._require_operation_id(command_id)
        self._require_session_target(target_session_root)
        workshop = composition_root(self._authority, "Workshop", caller=self._binding.caller)
        return remove_composition_member(self._authority, workshop, target_session_root,
            caller=self._binding.caller, command_id=command_id)

    def publish_task_result(self, message_root: str):
        """Publish a verified recorded outcome; never invoke an external host."""
        from .clean_host_execution import _recorded_host_outcome
        self._require_operation_id(message_root)
        messages = [item for item in self.inbox() if item.root_id == message_root]
        if len(messages) != 1 or messages[0].category != "followup" or messages[0].state not in {"read", "acted"}:
            raise InvalidCell("Workshop result requires this worker's processed task")
        message = messages[0]
        binding = (message.sender_root, message.recipient_root, message.execution_root)
        def current_task():
            current = [item for item in self.inbox() if item.root_id == message_root]
            if (len(current) != 1 or current[0].category != "followup" or
                    current[0].state not in {"read", "acted"} or
                    (current[0].sender_root, current[0].recipient_root, current[0].execution_root) != binding):
                raise InvalidCell("Workshop task connections changed during result publication")
            return current[0]
        command = str(uuid.uuid5(uuid.UUID(message_root), "workshop-execution:" + self.session_root))
        receipt = find_receipt(self._authority, self._authority.store.snapshot(),
            self._binding.caller.actor_root, self.session_root, command)
        if receipt is None or receipt.decision != "allow":
            raise InvalidCell("Workshop task has no completed execution receipt")
        record = _recorded_host_outcome(self._authority, receipt)
        if (type(record.get("succeeded")) is not bool or not message.execution_root or
                record.get("subject") != message.execution_root or
                receipt.request_digest != digest({"intent":"execute-host-operation",
                    "operation":record.get("operation"), "arguments":record.get("arguments"),
                    "subject":record.get("subject")})):
            raise InvalidCell("Workshop execution receipt does not match the task")
        evidence = {"status":"succeeded" if record["succeeded"] else "failed",
            "operation":record["operation"], "node":record["subject"],
            "effect":receipt.result_root, "receipt":receipt.root_id,
            "execution_revision":receipt.result_revision, "outcome":record.get("outcome")}
        body = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        if len(body) > 12_000:
            evidence.pop("outcome")
            evidence["outcome_omitted"] = "Full outcome is preserved at the linked effect."
            body = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        if len(body) > 12_000:
            raise InvalidCell("Workshop result metadata exceeds the message bound")
        current_task()
        reply = self.send_message(target_session_root=message.sender_root, body=body,
            operation_id=str(uuid.uuid5(uuid.UUID(message_root), "workshop-result:" + self.session_root)),
            reply_to_root=message_root, _reply_task_binding=binding)
        latest = current_task()
        if latest.state == "read":
            transition_coordination_message(self._authority, message_root, "acted",
                caller=self._binding.caller,
                command_id=str(uuid.uuid5(uuid.UUID(message_root), "workshop-acted:" + self.session_root)),
                expected_revision=latest.current_revision)
        return {"message_root":message_root, "reply_root":reply.root_id,
            "effect":receipt.result_root, "receipt":receipt.root_id,
            "execution_revision":receipt.result_revision, "status":evidence["status"]}

    def _require_session_target(self, target_root: str) -> None:
        if type(target_root) is not str or not target_root:
            raise InvalidCell("coordination target is invalid")
        known = {
            projection.bundle.session_root
            for projection in self.list_agents()
        }
        if target_root not in known:
            raise InvalidCell("coordination target is not an Agent Session")

    @staticmethod
    def _require_operation_id(value: str) -> None:
        try:
            parsed = uuid.UUID(value)
        except (TypeError, ValueError) as exc:
            raise InvalidCell("coordination operation identity is invalid") from exc
        if str(parsed) != value.lower():
            raise InvalidCell("coordination operation identity is not canonical")


__all__ = ["BoundAgentSession", "GraphAgentCoordinator"]
