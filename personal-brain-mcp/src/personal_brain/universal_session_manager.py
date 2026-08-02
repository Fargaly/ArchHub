"""Process-local custody for graph Agent Session transport capabilities.

The manager is a boundary adapter: it owns no semantic session or work state.
Agent Session identity, work ownership, transitions, and history remain in the
ApplicationServer-owned Universal Cell graph.  Raw vendor session identifiers
are reduced to process-memory lookup digests and are never persisted here.
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import hashlib
import threading
from typing import Any, Callable, Mapping

from .universal_runtime import UniversalRuntimeBridge, UniversalRuntimeUnavailable


def _binding_key(runtime: str, external_session_id: str) -> str:
    if type(runtime) is not str or not runtime.strip():
        raise ValueError("runtime is required")
    if type(external_session_id) is not str or not external_session_id:
        raise ValueError("external session identity is required")
    return hashlib.sha256(
        runtime.strip().encode("utf-8")
        + b"\x00"
        + external_session_id.encode("utf-8")
    ).hexdigest()


class UniversalRuntimeSessionManager:
    """Keep one renewable pipe capability per external agent session."""

    def __init__(
        self,
        bridge_factory: Callable[[], UniversalRuntimeBridge] = (
            UniversalRuntimeBridge
        ),
    ) -> None:
        self._bridge_factory = bridge_factory
        self._bindings: dict[str, UniversalRuntimeBridge] = {}
        self._lock = threading.RLock()

    def enroll(
        self, *, runtime: str, external_session_id: str
    ) -> dict[str, object]:
        key = _binding_key(runtime, external_session_id)
        normalized_runtime = runtime.strip()
        with self._lock:
            bridge = self._bindings.get(key)
            if bridge is not None:
                try:
                    state = bridge.work_index()
                except UniversalRuntimeUnavailable as exc:
                    failure = str(exc).casefold()
                    renewable = (
                        "agent session is unknown",
                        "agent session capability expired",
                    )
                    if not any(message in failure for message in renewable):
                        raise
                    replacement = self._bridge_factory()
                    enrolled = replacement.bind_agent_session(
                        runtime=normalized_runtime,
                        external_session_id=external_session_id,
                    )
                    self._bindings[key] = replacement
                    return {
                        "agent_session": enrolled["agent_session"],
                        "runtime": enrolled["runtime"],
                        "reused": False,
                        "reconnected": True,
                        "revision": enrolled["revision"],
                        "expires_at": enrolled["expires_at"],
                    }
                return {
                    "agent_session": bridge.agent_session_root,
                    "runtime": normalized_runtime,
                    "reused": True,
                    "revision": state["revision"],
                }
            bridge = self._bridge_factory()
            enrolled = bridge.bind_agent_session(
                runtime=normalized_runtime,
                external_session_id=external_session_id,
            )
            self._bindings[key] = bridge
            return {
                "agent_session": enrolled["agent_session"],
                "runtime": enrolled["runtime"],
                "reused": False,
                "revision": enrolled["revision"],
                "expires_at": enrolled["expires_at"],
            }

    @staticmethod
    def _resolve_work_references(
        bridge: UniversalRuntimeBridge, item: Mapping[str, object]
    ) -> dict[str, object]:
        """Attach bounded Cell values to a transport work projection.

        The work object remains graph-owned.  This adapter only dereferences
        declared structured interfaces so an assigned client receives the same
        CDE and policy values that the graph exposes through its wires.
        """
        interfaces = item.get("interfaces")
        interfaces = interfaces if isinstance(interfaces, Mapping) else {}
        resolved: dict[str, object] = {}
        for name in (
            "requirements",
            "cde-container",
            "required-capabilities",
            "applicable-policy",
        ):
            interface = interfaces.get(name)
            interface = interface if isinstance(interface, Mapping) else {}
            target = interface.get("target")
            if isinstance(target, str) and ":data:" in target:
                resolved[name] = bridge.value_read(target)
        return {**item, "resolved": resolved}

    def work_status(
        self, *, runtime: str, external_session_id: str
    ) -> dict[str, object]:
        bridge = self._require(runtime, external_session_id)
        compact_fallback_reason = ""
        try:
            state = bridge.work_list()
            projection = "full"
        except UniversalRuntimeUnavailable as exc:
            state = bridge.work_index()
            projection = "index"
            compact_fallback_reason = str(exc)
        projected: list[dict[str, object]] = []
        for item in state.get("items") or []:
            if isinstance(item, Mapping):
                projected.append(self._resolve_work_references(bridge, item))
        result = {**state, "items": projected, "projection": projection}
        if compact_fallback_reason:
            result["full_projection_unavailable"] = True
            result["full_projection_error"] = compact_fallback_reason
        return result

    def claim_next(
        self, *, runtime: str, external_session_id: str
    ) -> dict[str, object]:
        bridge = self._require(runtime, external_session_id)
        assignment = bridge.work_next()
        work = assignment.get("work")
        if not isinstance(work, Mapping):
            return assignment
        return {
            **assignment,
            "work": self._resolve_work_references(bridge, work),
        }

    def claim_exact(
        self,
        *,
        runtime: str,
        external_session_id: str,
        root_id: str,
    ) -> dict[str, object]:
        """Claim one named Work without scanning the global work frontier."""
        if type(root_id) is not str or not root_id:
            raise ValueError("exact work root is required")
        bridge = self._require(runtime, external_session_id)
        assignment = bridge._request(
            "POST",
            "/api/universal/work-transition",
            {
                "root": root_id,
                "event": "claim",
                "evidence": "",
                "projection": "receipt-v1",
            },
        )
        work = assignment.get("work")
        if not isinstance(work, Mapping):
            return assignment
        return {
            **assignment,
            "work": self._resolve_work_references(bridge, work),
        }

    def create(
        self,
        *,
        runtime: str,
        external_session_id: str,
        title: str,
        description: str = "",
        priority: int = 0,
        external_key: str,
        references: Mapping[str, str] | None = None,
        structured_references: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Create Work directly in the graph for an enrolled Agent Session."""
        bridge = self._require(runtime, external_session_id)
        return bridge.work_create(
            title=title,
            description=description,
            priority=priority,
            external_key=external_key,
            references=references,
            structured_references=structured_references,
            compact_references=True,
            select_created=False,
        )

    def value_read(
        self, *, runtime: str, external_session_id: str, root_id: str
    ) -> object:
        bridge = self._require(runtime, external_session_id)
        return bridge.value_read(root_id)

    def issue_cde_write_permit(
        self,
        *,
        runtime: str,
        external_session_id: str,
        operation: str,
        path: str,
        content_digest: str,
        request_id: str,
        nonce: str,
    ) -> dict[str, object]:
        """Issue one permit from the Session's exact graph-held Work claim."""
        bridge = self._require(runtime, external_session_id)
        return bridge._client.issue_cde_write_permit(
            operation=operation,
            path=path,
            content_digest=content_digest,
            request_id=request_id,
            nonce=nonce,
        )

    def consume_cde_write_permit(
        self,
        *,
        runtime: str,
        external_session_id: str,
        permit: str,
        operation: str,
        path: str,
        content_digest: str,
        request_id: str,
    ) -> dict[str, object]:
        """Settle one exact graph-held permit after its governed write."""
        bridge = self._require(runtime, external_session_id)
        return bridge._client.consume_cde_write_permit(
            permit=permit,
            operation=operation,
            path=path,
            content_digest=content_digest,
            request_id=request_id,
        )

    def migrate_legacy_work(self, store) -> dict[str, object]:
        """Read legacy evidence once and write only through the graph route."""
        from .active_work_cell_migration import migrate_active_work_to_cells

        return migrate_active_work_to_cells(
            store, bridge=self._bridge_factory()
        )

    def transition(
        self,
        *,
        runtime: str,
        external_session_id: str,
        root_id: str,
        event: str,
        evidence: str = "",
    ) -> dict[str, object]:
        bridge = self._require(runtime, external_session_id)
        return bridge.work_transition(
            root_id=root_id, event=event, evidence=evidence
        )

    def adjudicate(
        self,
        *,
        runtime: str,
        external_session_id: str,
        root_id: str,
    ) -> dict[str, object]:
        bridge = self._require(runtime, external_session_id)
        return bridge.work_court(root_id)

    def forget(self, *, runtime: str, external_session_id: str) -> bool:
        key = _binding_key(runtime, external_session_id)
        with self._lock:
            return self._bindings.pop(key, None) is not None

    def _require(
        self, runtime: str, external_session_id: str
    ) -> UniversalRuntimeBridge:
        key = _binding_key(runtime, external_session_id)
        with self._lock:
            bridge = self._bindings.get(key)
        if bridge is None:
            raise RuntimeError("external session is not enrolled")
        return bridge


__all__ = ["UniversalRuntimeSessionManager"]
