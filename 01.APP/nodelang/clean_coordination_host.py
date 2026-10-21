"""Signed internal Workspace Settings and Work effects on the existing graph owner.

Generic peer message/list/inbox dispatch is retired. MCP send/read uses the
application's shared Workshop table without entering this Work authorization host.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import hashlib
import json
import threading
import sys
import time
from typing import Mapping, Sequence
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .agent_session_catalogue import (
    AgentSessionBundle,
    AgentSessionCatalogue,
    AgentSessionProjection,
    create_agent_session,
    install_agent_session_catalogue,
    transition_agent_session,
)
from .clean_agent_coordination import BoundAgentSession, GraphAgentCoordinator
from .clean_runtime_bootstrap import BOOTSTRAP_NAMESPACE
from .coordination_workshop import (
    WorkshopCatalogue,
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
    "scope_lens",
    "revise_instance",
    "attach_agent",
    "detach_agent",
    "execute_workshop_task",
    "run_workshop_task",
    "publish_workshop_result",
    "workspace_roots_state",
    "workspace_roots_settings",
})
_METHOD_ALIASES = {
    "coordination.register_session": "register_session",
    "coordination.scope_lens": "scope_lens",
    "coordination.revise_instance": "revise_instance",
    "coordination.attach_agent": "attach_agent",
    "coordination.detach_agent": "detach_agent",
    "coordination.execute_workshop_task": "execute_workshop_task",
    "coordination.run_workshop_task": "run_workshop_task",
    "coordination.publish_workshop_result": "publish_workshop_result",
    "coordination.private_root_grant_status": "private_root_grant_status",
}


def _coordination_method(value: object) -> str:
    method = _bounded_text(value, "coordination method", 64)
    return _METHOD_ALIASES.get(method, method)


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
    admitted_method = _coordination_method(method)
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



def _boot_note(line: str, runtime_root=None) -> None:
    """One measured line into the owner's boot log (stderr is lost under pythonw)."""
    try:
        import os as _os
        from pathlib import Path as _Path
        root = (
            _Path(runtime_root)
            if runtime_root
            else _Path(_os.environ.get("LOCALAPPDATA", "")) / "ArchHub" / "unified-authority"
        )
        if root.is_dir():
            with (root / "boot-timing.log").open("a", encoding="utf-8") as log:
                log.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  boot phase: " + line + chr(10))
    except Exception:
        pass


def _base_catalogue_reconciliation_decision(
    runtime_root,
    state: Mapping[str, object],
    changed: bool,
    missing: Sequence[str],
) -> tuple[bool, bool]:
    effective_changed = changed if (runtime_root and state) else True
    return bool(missing or effective_changed), effective_changed


def _boot_catalogue_source_hash() -> str | None:
    """Installer and resolver changes invalidate disposable boot reuse."""
    from pathlib import Path
    from .base_universal_catalogue import base_universal_catalogue_hash

    digest = hashlib.sha256(base_universal_catalogue_hash().encode("ascii"))
    try:
        for name in (
            "agent_session_catalogue.py", "coordination_workshop.py", "base_universal_catalogue.py",
            "clean_coordination_host.py", "unified_authority.py",
        ):
            digest.update((Path(__file__).parent / name).read_bytes())
    except OSError:
        return None  # Source unavailable: use the existing presence installers.
    return digest.hexdigest()


class CleanCoordinationHost:
    """Single authority owner for authenticated provider adapters."""

    def __init__(
        self,
        authority: UnifiedAuthority,
        key_store: WindowsDpapiCallerKeyStore,
        *,
        host_invoker=None,
        runtime_root=None,
    ) -> None:
        if host_invoker is not None and not callable(host_invoker):
            raise InvalidCell("coordination host adapter must be callable")
        self.authority = authority
        self.key_store = key_store
        self._host_invoker = host_invoker
        self._workspace_settings = None
        from .runtime_activity import RuntimeActivity
        self.activity = RuntimeActivity()
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._bindings: dict[
            str,
            tuple[AgentSessionBundle, GraphAgentCoordinator],
        ] = {}
        _t = time.monotonic()
        self._founder = key_store.bind_bootstrap(authority, "founder.bootstrap")
        _boot_note("bind_bootstrap %.1fs" % (time.monotonic() - _t), runtime_root)
        _t = time.monotonic()
        from .unified_authority import published_definition_named
        from .stability_runtime import (
            catalogue_refresh_required, read_generation_state, write_generation_state,
        )
        from .base_universal_catalogue import (
            BASE_CATALOGUE, base_universal_catalogue_hash, install_base_universal_catalogue,
        )
        installer_hash = _boot_catalogue_source_hash()
        source_hash = installer_hash or base_universal_catalogue_hash()
        state = read_generation_state(runtime_root) if runtime_root else {}
        changed, generation = catalogue_refresh_required(
            runtime_root or ".", authority, source_hash=source_hash,
        )
        unchanged = bool(runtime_root and state and installer_hash and not changed)
        session_root = published_definition_named(
            authority, "Agent session state", caller=self._founder,
        ) if unchanged else None
        if session_root is not None:
            self._sessions = AgentSessionCatalogue(session_root)
        else:
            self._sessions = install_agent_session_catalogue(
                authority,
                operation_id=str(uuid.uuid5(
                    BOOTSTRAP_NAMESPACE, "agent-session-catalogue:v1",
                )),
                caller=self._founder,
            )
        _boot_note("agent session catalogue %.1fs (%s)" % (
            time.monotonic() - _t,
            "unchanged skipped" if session_root is not None else "installed/present",
        ), runtime_root)
        _t = time.monotonic()
        workshop_roots = tuple(
            published_definition_named(authority, name, caller=self._founder)
            for name in ("Coordination plan", "Work assignment", "Work evidence",
                         "Independent review", "Coordination message")
        ) if unchanged else ()
        if workshop_roots and all(workshop_roots):
            self._workshop = WorkshopCatalogue(*workshop_roots)
        else:
            self._workshop = install_workshop_catalogue(
                authority,
                operation_id=str(uuid.uuid5(
                    BOOTSTRAP_NAMESPACE, "workshop-catalogue:v1",
                )),
                caller=self._founder,
            )
        _boot_note("workshop catalogue %.1fs (%s)" % (
            time.monotonic() - _t,
            "unchanged skipped" if workshop_roots and all(workshop_roots)
            else "installed/present",
        ), runtime_root)
        _t = time.monotonic()
        changed, generation = catalogue_refresh_required(
            runtime_root or ".",
            authority,
            source_hash=source_hash,
        )
        names = tuple(entry["name"] for entry in BASE_CATALOGUE)
        existing = {
            name: published_definition_named(authority, name, caller=self._founder)
            for name in names
        }
        missing = [name for name, root in existing.items() if root is None]
        should_install, changed = _base_catalogue_reconciliation_decision(
            runtime_root, state, changed, missing,
        )
        if should_install:
            self._base_catalogue = install_base_universal_catalogue(
                authority,
                caller=self._founder,
                reconcile_existing=bool(changed),
            )
            _, generation = catalogue_refresh_required(
                runtime_root or ".",
                authority,
                source_hash=source_hash,
            )
            if runtime_root:
                write_generation_state(
                    runtime_root,
                    source_hash=source_hash,
                    generation=generation,
                    warmed=False,
                )
            verdict = "installed/reconciled"
        else:
            self._base_catalogue = {
                name: root for name, root in existing.items() if root is not None
            }
            verdict = "unchanged skipped"
        # An owner does not write to the founder's graph at boot. The
        # expression cells and any visual-system upgrade are migrations
        # someone runs deliberately: a boot that rewrites 24 templates
        # because a vocabulary grew added 136,178 cells in 120 restarts.
        _boot_note("base universal catalogue %.1fs (%d definitions; %s)" % (
            time.monotonic() - _t, len(self._base_catalogue), verdict,
        ), runtime_root)

    def verify_request(self, request: SignedCoordinationRequest) -> None:
        if request.version != _REQUEST_VERSION:
            raise InvalidCell("coordination protocol version is invalid")
        _uuid(request.request_id, "coordination request identity")
        identity = request.identity.normalized()
        if request.key_id != identity.key_id:
            raise InvalidCell("coordination key is not bound to its session")
        if _coordination_method(request.method) not in _METHODS:
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

    def bind_workspace_settings(self, authority, handler):
        """Owner-only in-process wiring: the canvas's own workspace-roots route."""
        if authority is not self.authority or not callable(handler):
            raise InvalidCell("workspace settings must belong to this authority owner")
        self._workspace_settings = handler

    def bind_host_invoker(self, authority, invoker):
        """Owner-only in-process wiring; not exposed as a coordination method."""
        if authority is not self.authority or not callable(invoker):
            raise InvalidCell("coordination adapter must belong to this authority owner")
        with self._changed:
            if self.activity.closing:
                raise InvalidCell("coordination owner is shutting down")
            if self._host_invoker is not None and self._host_invoker is not invoker:
                raise InvalidCell("coordination adapter is already bound")
            self._host_invoker = invoker

    def dispatch(self, request: SignedCoordinationRequest) -> dict[str, object]:
        with self.activity.admit():
            return self._dispatch_admitted(request)

    def begin_shutdown(self):
        self.activity.begin_shutdown()
        with self._changed:
            self._changed.notify_all()

    def _dispatch_admitted(self, request: SignedCoordinationRequest) -> dict[str, object]:
        self.verify_request(request)
        method = _coordination_method(request.method)
        from .workspace_roots_catalogue import (
            ISSUER_IDENTITY,
            SETTINGS_IDENTITY,
            current_registry_statement,
        )
        issuer = CoordinationIdentity(*ISSUER_IDENTITY).normalized().key_id
        if (method == "workspace_roots_state") != (request.key_id == issuer):
            # The permit issuer's key reads the workspace-roots state and nothing
            # else; no other key reads it. No Work, write or session binding.
            raise InvalidCell("coordination method is not admitted for this key")
        settings = CoordinationIdentity(*SETTINGS_IDENTITY).normalized().key_id
        if (method == "workspace_roots_settings") != (request.key_id == settings):
            # Settings -> Workspaces from the desktop: that key asks this owner's
            # own workspace-roots route and nothing else.
            raise InvalidCell("coordination method is not admitted for this key")
        if method == "workspace_roots_settings":
            handler = self._workspace_settings
            if handler is None:
                raise InvalidCell("this graph owner serves no workspace settings")
            # The request already passed verify_request and the settings-key/method
            # gate above, so request.identity is the proven workspace-roots settings
            # principal. Pass it to the handler as trusted internal context -- never a
            # caller-supplied body field -- so the first-enrollment admission is bound
            # to who actually authenticated, not to anything the body can forge.
            admission = {"principal": request.identity.normalized().key_id}
            # Not under the coordinator lock: Add waits for the owner's key prompt
            # and Browse for his folder dialog; the route takes its own locks.
            answer = handler(request.parameters.get("body"), admission=admission)
            return {"ok": True, **answer}
        if method == "workspace_roots_state":
            with self._changed:
                return {"ok": True, **current_registry_statement(
                    self.authority, caller=self._founder,
                    request_id=request.request_id, parameters=request.parameters)}
        if method in {"execute_workshop_task", "run_workshop_task"}:
            from .clean_host_execution import HostOperationFailed, HostOperationUncertain
            message_root = _bounded_text(request.parameters.get("message_root"),
                "coordination message root", 256)
            with self._changed:
                _, coordinator = self._binding(request.identity)
            # Do not hold the coordinator lock during a physical host call:
            # other agents must still be able to read messages or disconnect.
            try:
                if method == "run_workshop_task":
                    command = _uuid(request.parameters.get("idempotency_key"),
                        "coordination idempotency key")
                    result = coordinator.run_workshop_task(message_root,
                        command_id=command, invoker=self._host_invoker)
                    return {"ok":True, **result}
                result = coordinator.execute_claimed_task(message_root, invoker=self._host_invoker)
                return {"ok": True, "message_root": message_root, "effect": result.root_id,
                    "receipt": result.receipt_root, "accepted_revision": result.revision,
                    "replayed": result.replayed}
            except HostOperationFailed as exc:
                return {"ok": False, "outcome":"failed", "error":str(exc),
                    "message_root":message_root, "effect":exc.result_root,
                    "receipt":exc.receipt_root, "accepted_revision":exc.revision,
                    "replayed":exc.replayed}
            except HostOperationUncertain as exc:
                return {"ok":False, "outcome":"uncertain", "error":str(exc),
                    "message_root":message_root}
            finally:
                with self._changed:
                    self._changed.notify_all()
        with self._changed:
            bundle, coordinator = self._binding(request.identity)
            params = dict(request.parameters)
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
            if method == "publish_workshop_result":
                root = _bounded_text(params.get("message_root"), "coordination message root", 256)
                result = coordinator.publish_task_result(root)
                self._changed.notify_all()
                return {"ok":True, **result}
            if method in {"attach_agent", "detach_agent"}:
                target = _bounded_text(params.get("target"), "coordination target", 256)
                command = _uuid(params.get("idempotency_key"), "coordination idempotency key")
                action = coordinator.attach_agent if method == "attach_agent" else coordinator.detach_agent
                result = action(target, command_id=command)
                self._changed.notify_all()
                return {"ok": True, "target": target, "action": method,
                    "accepted_revision": result.revision, "receipt": result.receipt_root,
                    "replayed": result.replayed}
            raise InvalidCell("coordination method is not implemented")



__all__ = [
    "CleanCoordinationHost",
    "CoordinationIdentity",
    "PROVENANCE",
    "SignedCoordinationRequest",
    "sign_coordination_request",
]
