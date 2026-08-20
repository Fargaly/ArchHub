"""Authenticated agent coordination hosted by the one clean graph owner.

MCP stdio adapters obtain caller identity from their process environment as
required by the MCP transport boundary.  They sign a canonical request with a
DPAPI-held Ed25519 key.  This host verifies that request, derives the same
Agent Session identity, and performs the operation through the Universal Cell
authority.  It owns no message queue, session database, or semantic cache.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import json
import threading
import sys
import time
from typing import Mapping
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .agent_session_catalogue import (
    AgentSessionBundle,
    AgentSessionProjection,
    create_agent_session,
    install_agent_session_catalogue,
    transition_agent_session,
)
from .clean_agent_coordination import BoundAgentSession, GraphAgentCoordinator
from .clean_runtime_bootstrap import BOOTSTRAP_NAMESPACE
from .coordination_workshop import (
    CoordinationMessageProjection,
    install_workshop_catalogue,
)
from .runtime_caller_capability import WindowsDpapiCallerKeyStore
from .unified_authority import UnifiedAuthority
from .universal_cell import InvalidCell


PROVENANCE = {
    "mcp-stdio-identity": (
        "https://modelcontextprotocol.io/specification/2025-11-25/"
        "basic/authorization"
    ),
    "mcp-transport-security": (
        "https://modelcontextprotocol.io/specification/2025-11-25/"
        "basic/transports"
    ),
    "a2a-authentication": "https://a2a-protocol.org/latest/specification/",
}
_SESSION_NAMESPACE = uuid.UUID("1f02ad35-978e-4020-8524-5010ecaf3d5b")
_REQUEST_VERSION = "archhub-clean-coordination-v1"
_METHODS = frozenset({
    "register_session",
    "list_agents",
    "scope_lens",
    "workshop_lens",
    "revise_instance",
    "send_message",
    "followup_task",
    "interrupt_agent",
    "inbox",
    "mark_message_read",
    "wait_agent",
})


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidCell("coordination request is not canonical JSON") from exc


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if type(value) is not str:
        raise InvalidCell("%s is invalid" % field)
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or "\r" in normalized
        or "\n" in normalized
    ):
        raise InvalidCell("%s is invalid" % field)
    return normalized


def _uuid(value: object, field: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise InvalidCell("%s is invalid" % field) from exc
    canonical = str(parsed)
    if value != canonical:
        raise InvalidCell("%s is not canonical" % field)
    return canonical


@dataclass(frozen=True, slots=True)
class CoordinationIdentity:
    vendor: str
    session_instance_id: str
    model: str = "provider-selected"

    def normalized(self) -> "CoordinationIdentity":
        return CoordinationIdentity(
            _bounded_text(self.vendor, "coordination vendor", 64).lower(),
            _bounded_text(
                self.session_instance_id,
                "coordination session identity",
                200,
            ),
            _bounded_text(self.model, "coordination model", 256),
        )

    @property
    def key_id(self) -> str:
        normalized = self.normalized()
        digest = hashlib.sha256(
            (normalized.vendor + "\0" + normalized.session_instance_id).encode(
                "utf-8"
            )
        ).hexdigest()
        return "agent-session.%s" % digest


@dataclass(frozen=True, slots=True)
class SignedCoordinationRequest:
    version: str
    request_id: str
    identity: CoordinationIdentity
    key_id: str
    method: str
    parameters: Mapping[str, object]
    signature: str

    def unsigned(self) -> Mapping[str, object]:
        return {
            "version": self.version,
            "request_id": self.request_id,
            "identity": asdict(self.identity.normalized()),
            "key_id": self.key_id,
            "method": self.method,
            "parameters": dict(self.parameters),
        }

    def to_payload(self) -> Mapping[str, object]:
        return {**self.unsigned(), "signature": self.signature}

    @classmethod
    def from_payload(
        cls,
        payload: object,
    ) -> "SignedCoordinationRequest":
        expected = {
            "version",
            "request_id",
            "identity",
            "key_id",
            "method",
            "parameters",
            "signature",
        }
        if type(payload) is not dict or set(payload) != expected:
            raise InvalidCell("coordination request fields are invalid")
        identity = payload["identity"]
        if (
            type(identity) is not dict
            or set(identity) != {"vendor", "session_instance_id", "model"}
            or type(payload["parameters"]) is not dict
            or any(
                type(payload[name]) is not str
                for name in (
                    "version",
                    "request_id",
                    "key_id",
                    "method",
                    "signature",
                )
            )
            or any(
                type(identity[name]) is not str
                for name in ("vendor", "session_instance_id", "model")
            )
        ):
            raise InvalidCell("coordination request identity is invalid")
        try:
            return cls(
                payload["version"],
                payload["request_id"],
                CoordinationIdentity(
                    identity["vendor"],
                    identity["session_instance_id"],
                    identity["model"],
                ),
                payload["key_id"],
                payload["method"],
                dict(payload["parameters"]),
                payload["signature"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCell("coordination request values are invalid") from exc


def sign_coordination_request(
    key_store: WindowsDpapiCallerKeyStore,
    identity: CoordinationIdentity,
    method: str,
    parameters: Mapping[str, object],
    *,
    request_id: str | None = None,
) -> SignedCoordinationRequest:
    normalized = identity.normalized()
    admitted_method = _bounded_text(method, "coordination method", 64)
    if admitted_method not in _METHODS:
        raise InvalidCell("coordination method is not admitted")
    admitted_request = _uuid(
        request_id or str(uuid.uuid4()),
        "coordination request identity",
    )
    key_store.ensure(normalized.key_id)
    unsigned = {
        "version": _REQUEST_VERSION,
        "request_id": admitted_request,
        "identity": asdict(normalized),
        "key_id": normalized.key_id,
        "method": admitted_method,
        "parameters": dict(parameters),
    }
    signature = key_store.sign(normalized.key_id, _canonical(unsigned))
    return SignedCoordinationRequest(
        _REQUEST_VERSION,
        admitted_request,
        normalized,
        normalized.key_id,
        admitted_method,
        dict(parameters),
        base64.b64encode(signature).decode("ascii"),
    )


def _session_projection(value: AgentSessionProjection) -> dict[str, object]:
    return {
        "session_root": value.bundle.session_root,
        "state_root": value.bundle.state_root,
        "status": value.status,
        "runtime": value.runtime,
        "provider": value.provider,
        "model": value.model,
        "revision": value.revision,
    }


def _message_projection(value: CoordinationMessageProjection) -> dict[str, object]:
    return asdict(value)


def _boot_note(line: str) -> None:
    """One measured line into the owner's boot log (stderr is lost under pythonw)."""
    try:
        import os as _os
        from pathlib import Path as _Path
        root = _Path(_os.environ.get("LOCALAPPDATA", "")) / "ArchHub" / "unified-authority"
        if root.is_dir():
            with (root / "boot-timing.log").open("a", encoding="utf-8") as log:
                log.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  boot phase: " + line + chr(10))
    except Exception:
        pass


class CleanCoordinationHost:
    """Single authority owner for authenticated provider adapters."""

    def __init__(
        self,
        authority: UnifiedAuthority,
        key_store: WindowsDpapiCallerKeyStore,
    ) -> None:
        self.authority = authority
        self.key_store = key_store
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._bindings: dict[
            str,
            tuple[AgentSessionBundle, GraphAgentCoordinator],
        ] = {}
        _t = time.monotonic()
        self._founder = key_store.bind_bootstrap(authority, "founder.bootstrap")
        _boot_note("bind_bootstrap %.1fs" % (time.monotonic() - _t))
        _t = time.monotonic()
        self._sessions = install_agent_session_catalogue(
            authority,
            operation_id=str(uuid.uuid5(
                BOOTSTRAP_NAMESPACE,
                "agent-session-catalogue:v1",
            )),
            caller=self._founder,
        )
        _boot_note("agent session catalogue %.1fs" % (time.monotonic() - _t))
        _t = time.monotonic()
        self._workshop = install_workshop_catalogue(
            authority,
            operation_id=str(uuid.uuid5(
                BOOTSTRAP_NAMESPACE,
                "workshop-catalogue:v1",
            )),
            caller=self._founder,
        )
        _boot_note("workshop catalogue %.1fs" % (time.monotonic() - _t))
        _t = time.monotonic()
        from .base_universal_catalogue import install_base_universal_catalogue
        self._base_catalogue = install_base_universal_catalogue(
            authority, caller=self._founder,
        )
        _boot_note("base universal catalogue %.1fs (%d definitions)" % (
            time.monotonic() - _t, len(self._base_catalogue),
        ))

    def verify_request(self, request: SignedCoordinationRequest) -> None:
        if request.version != _REQUEST_VERSION:
            raise InvalidCell("coordination protocol version is invalid")
        _uuid(request.request_id, "coordination request identity")
        identity = request.identity.normalized()
        if request.key_id != identity.key_id:
            raise InvalidCell("coordination key is not bound to its session")
        if request.method not in _METHODS:
            raise InvalidCell("coordination method is not admitted")
        try:
            signature = base64.b64decode(request.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(
                self.key_store.public_key(request.key_id)
            ).verify(signature, _canonical(request.unsigned()))
        except (ValueError, InvalidSignature) as exc:
            raise InvalidCell("coordination request signature is invalid") from exc

    def _binding(
        self,
        identity: CoordinationIdentity,
    ) -> tuple[AgentSessionBundle, GraphAgentCoordinator]:
        normalized = identity.normalized()
        existing = self._bindings.get(normalized.key_id)
        if existing is not None:
            return existing
        public_key = self.key_store.public_key(normalized.key_id)
        operation = str(uuid.uuid5(
            _SESSION_NAMESPACE,
            "session:" + normalized.key_id,
        ))
        bundle = create_agent_session(
            self.authority,
            self._sessions,
            label=normalized.vendor.title() + " Agent Session",
            runtime=normalized.vendor,
            provider=normalized.vendor,
            model=normalized.model,
            public_key=public_key,
            operation_id=operation,
            caller=self._founder,
        )
        caller = self.key_store.bind_session(
            self.authority,
            normalized.key_id,
            bundle.session_root,
        )
        coordinator = GraphAgentCoordinator(
            self.authority,
            self._sessions,
            self._workshop,
            BoundAgentSession(bundle, caller),
        )
        own = tuple(
            item for item in coordinator.list_agents()
            if item.bundle.session_root == bundle.session_root
        )
        if len(own) != 1:
            raise InvalidCell("bound Agent Session is not uniquely projected")
        if own[0].status in {"enrolled", "offline"}:
            transition_agent_session(
                self.authority,
                bundle,
                "online",
                caller=caller,
                command_id=str(uuid.uuid5(
                    _SESSION_NAMESPACE,
                    "online:%s:%s" % (
                        normalized.key_id,
                        self.authority.store.revision,
                    ),
                )),
            )
            coordinator = GraphAgentCoordinator(
                self.authority,
                self._sessions,
                self._workshop,
                BoundAgentSession(bundle, caller),
            )
        bound = (bundle, coordinator)
        self._bindings[normalized.key_id] = bound
        return bound

    def dispatch(self, request: SignedCoordinationRequest) -> dict[str, object]:
        self.verify_request(request)
        if request.method == "wait_agent":
            parameters = dict(request.parameters)
            return self.wait_for_inbox(
                request,
                after_revision=parameters.get("after_revision", 0),
                timeout_seconds=parameters.get("timeout_seconds", 30.0),
                target_session_root=parameters.get("target"),
            )
        with self._changed:
            bundle, coordinator = self._binding(request.identity)
            params = dict(request.parameters)
            method = request.method
            if method == "register_session":
                own = tuple(
                    item for item in coordinator.list_agents()
                    if item.bundle.session_root == bundle.session_root
                )[0]
                return {
                    "ok": True,
                    "self": _session_projection(own),
                    "revision": self.authority.store.revision,
                }
            if method == "list_agents":
                agents = tuple(coordinator.list_agents())
                return {
                    "ok": True,
                    "self": bundle.session_root,
                    "agents": [_session_projection(item) for item in agents],
                    "count": len(agents),
                    "revision": self.authority.store.revision,
                }
            if method == "workshop_lens":
                return {
                    "ok": True,
                    "lens": coordinator.workshop_lens(),
                    "revision": self.authority.store.revision,
                }
            if method == "scope_lens":
                scope_root = _bounded_text(
                    params.get("scope_root"), "scope lens root", 256
                )
                lens = coordinator.scope_lens(scope_root)
                return {
                    "ok": True,
                    "lens": lens,
                    "revision": lens["revision"],
                }
            if method == "revise_instance":
                instance_root = _bounded_text(
                    params.get("instance_root"), "instance root", 256
                )
                scope_root = _bounded_text(
                    params.get("scope_root"), "instance scope", 256
                )
                changes = params.get("changes")
                if type(changes) is not dict:
                    raise InvalidCell("instance revision changes are invalid")
                expected_revision = params.get("expected_revision")
                if type(expected_revision) is not int or expected_revision < 0:
                    raise InvalidCell("instance revision base is invalid")
                command = _uuid(
                    params.get("idempotency_key"),
                    "coordination idempotency key",
                )
                changed = coordinator.revise_visible_instance(
                    instance_root,
                    changes,
                    scope_root=scope_root,
                    expected_revision=expected_revision,
                    command_id=command,
                )
                self._changed.notify_all()
                return {"ok": True, **changed}
            if method in {"send_message", "followup_task", "interrupt_agent"}:
                target = _bounded_text(
                    params.get("target"), "coordination target", 256
                )
                body = _bounded_text(
                    params.get("message"), "coordination message", 12_000
                )
                operation = _uuid(
                    params.get("idempotency_key"),
                    "coordination idempotency key",
                )
                reply = params.get("reply_to")
                if reply is not None:
                    reply = _bounded_text(reply, "coordination reply", 256)
                if method == "send_message":
                    message = coordinator.send_message(
                        target_session_root=target,
                        body=body,
                        operation_id=operation,
                        reply_to_root=reply,
                    )
                elif method == "followup_task":
                    message = coordinator.send_followup(
                        target_session_root=target,
                        body=body,
                        operation_id=operation,
                        reply_to_root=reply,
                    )
                else:
                    message = coordinator.request_interrupt(
                        target_session_root=target,
                        reason=body,
                        operation_id=operation,
                    )
                self._changed.notify_all()
                return {
                    "ok": True,
                    "message": _message_projection(message),
                    "revision": self.authority.store.revision,
                }
            if method == "inbox":
                after = params.get("after_revision", 0)
                if type(after) is not int or after < 0:
                    raise InvalidCell("coordination revision cursor is invalid")
                messages = coordinator.inbox(after_revision=after)
                return {
                    "ok": True,
                    "messages": [_message_projection(item) for item in messages],
                    "count": len(messages),
                    "revision": self.authority.store.revision,
                }
            if method == "mark_message_read":
                message_root = _bounded_text(
                    params.get("message_root"), "coordination message root", 256
                )
                command = _uuid(
                    params.get("idempotency_key"),
                    "coordination idempotency key",
                )
                result = coordinator.mark_message_read(
                    message_root,
                    command_id=command,
                )
                self._changed.notify_all()
                return {
                    "ok": True,
                    "message_root": result.root_id,
                    "revision": result.revision,
                    "replayed": result.replayed,
                }
            raise InvalidCell("coordination method is not implemented")

    def wait_for_inbox(
        self,
        request: SignedCoordinationRequest,
        *,
        after_revision: int,
        timeout_seconds: float,
        target_session_root: object = None,
    ) -> dict[str, object]:
        if (
            type(after_revision) is not int
            or after_revision < 0
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds < 0
            or timeout_seconds > 60
        ):
            raise InvalidCell("coordination wait boundary is invalid")
        self.verify_request(request)
        target = (
            None
            if target_session_root is None
            else _bounded_text(
                target_session_root,
                "coordination wait target",
                256,
            )
        )
        deadline = time.monotonic() + float(timeout_seconds)
        with self._changed:
            while True:
                _, coordinator = self._binding(request.identity)
                messages = coordinator.inbox(after_revision=after_revision)
                if target is not None:
                    messages = tuple(
                        message for message in messages
                        if message.sender_root == target
                    )
                if messages:
                    return {
                        "ok": True,
                        "status": "message",
                        "messages": [
                            _message_projection(item) for item in messages
                        ],
                        "count": len(messages),
                        "revision": self.authority.store.revision,
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {
                        "ok": True,
                        "status": "timeout",
                        "messages": [],
                        "count": 0,
                        "revision": self.authority.store.revision,
                    }
                self._changed.wait(remaining)


__all__ = [
    "CleanCoordinationHost",
    "CoordinationIdentity",
    "PROVENANCE",
    "SignedCoordinationRequest",
    "sign_coordination_request",
]
