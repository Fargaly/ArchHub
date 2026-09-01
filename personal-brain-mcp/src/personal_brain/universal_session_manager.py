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
import logging
import threading
import time
from typing import Any, Callable, Mapping

from .universal_runtime import UniversalRuntimeBridge, UniversalRuntimeUnavailable


_LOG = logging.getLogger(__name__)


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
        *,
        renewal_lead_seconds: float = 60.0,
        renewal_poll_seconds: float = 5.0,
    ) -> None:
        if (
            isinstance(renewal_lead_seconds, bool)
            or not isinstance(renewal_lead_seconds, (int, float))
            or float(renewal_lead_seconds) <= 0
        ):
            raise ValueError("renewal lead must be positive")
        if (
            isinstance(renewal_poll_seconds, bool)
            or not isinstance(renewal_poll_seconds, (int, float))
            or float(renewal_poll_seconds) <= 0
        ):
            raise ValueError("renewal poll interval must be positive")
        self._bridge_factory = bridge_factory
        self._bindings: dict[str, UniversalRuntimeBridge] = {}
        self._binding_expiries: dict[str, float] = {}
        self._renewal_failures: dict[str, str] = {}
        self._renewal_lead_seconds = float(renewal_lead_seconds)
        self._renewal_poll_seconds = float(renewal_poll_seconds)
        self._renewal_stop = threading.Event()
        self._renewal_thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def _record_enrollment_locked(
        self,
        key: str,
        bridge: UniversalRuntimeBridge,
        enrollment: Mapping[str, object],
    ) -> None:
        self._bindings[key] = bridge
        expires_at = enrollment.get("expires_at")
        if (
            not isinstance(expires_at, bool)
            and isinstance(expires_at, (int, float))
        ):
            self._binding_expiries[key] = float(expires_at)
            self._ensure_renewal_thread_locked()
        else:
            self._binding_expiries.pop(key, None)
        self._renewal_failures.pop(key, None)

    def _ensure_renewal_thread_locked(self) -> None:
        thread = self._renewal_thread
        if thread is not None and thread.is_alive():
            return
        self._renewal_stop.clear()
        thread = threading.Thread(
            target=self._renewal_loop,
            name="archhub-agent-session-renewal",
            daemon=True,
        )
        self._renewal_thread = thread
        thread.start()

    def _renewal_loop(self) -> None:
        """Rotate held capabilities before expiry without recreating Cells."""
        while not self._renewal_stop.is_set():
            now = time.time()
            with self._lock:
                due = tuple(
                    (key, self._bindings[key])
                    for key, expires_at in self._binding_expiries.items()
                    if (
                        key in self._bindings
                        and expires_at - now <= self._renewal_lead_seconds
                    )
                )
            for key, bridge in due:
                try:
                    renewed = bridge._client.renew_agent_session()
                    expires_at = renewed.get("expires_at")
                    if (
                        isinstance(expires_at, bool)
                        or not isinstance(expires_at, (int, float))
                        or float(expires_at) <= time.time()
                    ):
                        raise RuntimeError(
                            "Agent Session renewal returned an invalid expiry"
                        )
                except Exception as exc:
                    message = "%s: %s" % (type(exc).__name__, exc)
                    with self._lock:
                        if self._bindings.get(key) is bridge:
                            self._renewal_failures[key] = message
                    _LOG.warning(
                        "Agent Session capability renewal failed for %s: %s",
                        key,
                        message,
                    )
                    continue
                with self._lock:
                    if self._bindings.get(key) is bridge:
                        self._binding_expiries[key] = float(expires_at)
                        self._renewal_failures.pop(key, None)
            self._renewal_stop.wait(self._renewal_poll_seconds)

    def renewal_failures(self) -> Mapping[str, str]:
        """Expose bounded process evidence instead of swallowing heartbeat errors."""
        with self._lock:
            return dict(self._renewal_failures)

    def close(self) -> None:
        """Stop the process-local lease keeper without changing graph state."""
        self._renewal_stop.set()
        with self._lock:
            thread = self._renewal_thread
            self._renewal_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self._renewal_poll_seconds * 2.0))

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
                        "agent session proof is invalid",
                    )
                    if not any(message in failure for message in renewable):
                        raise
                    replacement = self._bridge_factory()
                    enrolled = replacement.bind_agent_session(
                        runtime=normalized_runtime,
                        external_session_id=external_session_id,
                    )
                    self._record_enrollment_locked(key, replacement, enrolled)
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
            self._record_enrollment_locked(key, bridge, enrolled)
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
        state = bridge.work_index()
        projected: list[dict[str, object]] = []
        for item in state.get("items") or []:
            if isinstance(item, Mapping):
                projected.append(self._resolve_work_references(bridge, item))
        return {**state, "items": projected, "projection": "index"}

    def deliberation_append(
        self,
        *,
        runtime: str,
        external_session_id: str,
        space: str,
        category: str,
        summary: str,
        payload: object,
        idempotency_key: str,
        created_at: str | None = None,
    ) -> dict[str, object]:
        """Append through the exact enrolled Agent Session capability."""
        bridge = self._require(runtime, external_session_id)
        return bridge.deliberation_append(
            space=space,
            category=category,
            summary=summary,
            payload=payload,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

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
            removed = self._bindings.pop(key, None) is not None
            self._binding_expiries.pop(key, None)
            self._renewal_failures.pop(key, None)
            return removed

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
