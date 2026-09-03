"""Provider-neutral coordination adapter over one Universal Cell authority.

The host binds one authenticated Agent Session before exposing these methods.
No tool argument can choose a sender, provider, or external session identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import uuid

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
    revise_instance,
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
    ) -> CoordinationMessageProjection:
        return self.send_message(
            target_session_root=target_session_root,
            body=body,
            operation_id=operation_id,
            category="followup",
            reply_to_root=reply_to_root,
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
