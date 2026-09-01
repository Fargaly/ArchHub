"""Brain client for the one ApplicationServer-owned Universal Cell runtime.

This module never opens the Cell database.  It verifies the signed runtime
descriptor, authenticates to the Windows pipe with current-user protected key
material, and invokes only routes admitted by the application graph.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sys
from typing import Any, Iterator, Mapping


class UniversalRuntimeUnavailable(RuntimeError):
    pass


def _workspace_root() -> Path:
    configured = os.environ.get("ARCHHUB_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "00.GOVERNANCE").is_dir():
            return candidate
    raise UniversalRuntimeUnavailable("ArchHub workspace root is unavailable")


def _node_language_root() -> Path:
    configured = os.environ.get("ARCHHUB_NODE_LANGUAGE_ROOT", "").strip()
    root = (
        Path(configured).expanduser().resolve()
        if configured
        else _workspace_root() / "10.PRODUCT" / "13.NODE-LANGUAGE"
    )
    if not (root / "nodelang" / "application_machine_transport.py").is_file():
        raise UniversalRuntimeUnavailable(
            "Universal runtime transport is unavailable"
        )
    return root


def runtime_descriptor_path() -> Path:
    configured = os.environ.get("ARCHHUB_UNIVERSAL_RUNTIME_STATE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise UniversalRuntimeUnavailable("LOCALAPPDATA is unavailable")
    return Path(local) / "ArchHub" / "active-universal-runtime.json"


@contextmanager
def _import_root(root: Path) -> Iterator[None]:
    value = str(root)
    inserted = value not in sys.path
    if inserted:
        sys.path.insert(0, value)
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(value)
            except ValueError:
                pass


def _runtime_types():
    root = _node_language_root()
    with _import_root(root):
        from nodelang.application_machine_transport import (
            MachineTransportError,
            UniversalRuntimeClient,
        )
        from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    return (
        MachineTransportError,
        UniversalRuntimeClient,
        WindowsDpapiSigningKeyProvider,
    )


class UniversalRuntimeBridge:
    """Strict Brain-facing projection of graph-owned work routes."""

    def __init__(self, descriptor_path=None, key_provider=None) -> None:
        (
            self._transport_error,
            client_type,
            provider_type,
        ) = _runtime_types()
        self.descriptor_path = Path(
            descriptor_path or runtime_descriptor_path()
        ).expanduser().resolve()
        self.key_provider = key_provider or provider_type(
            provider_type.default_path()
        )
        self._client = client_type(self.descriptor_path, self.key_provider)

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        try:
            return self._client.request(
                method,
                path,
                body,
                response_timeout_seconds=response_timeout_seconds,
            )
        except self._transport_error as exc:
            raise UniversalRuntimeUnavailable(str(exc)) from exc

    def work_list(
        self, *, response_timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/universal/work",
            response_timeout_seconds=response_timeout_seconds,
        )

    def work_index(
        self, *, response_timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/universal/work",
            {"projection": "index"},
            response_timeout_seconds=response_timeout_seconds,
        )

    def workshop_read(
        self, *, response_timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/universal/workshop",
            response_timeout_seconds=response_timeout_seconds,
        )

    def deliberation_read(
        self,
        *,
        space: str,
        limit: int = 100,
        category: str | None = None,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"space": space, "limit": int(limit)}
        if category is not None:
            body["category"] = category
        return self._request(
            "GET",
            "/api/universal/deliberation",
            body,
            response_timeout_seconds=response_timeout_seconds,
        )

    def deliberation_append(
        self,
        *,
        space: str,
        category: str,
        summary: str,
        payload: object,
        idempotency_key: str,
        created_at: str | None = None,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/universal/deliberation",
            {
                "space": space,
                "category": category,
                "summary": summary,
                "payload": payload,
                "idempotency_key": idempotency_key,
                "created_at": created_at,
            },
            response_timeout_seconds=response_timeout_seconds,
        )

    def browser_handoff_status(
        self, *, response_timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/universal/browser-handoff",
            response_timeout_seconds=response_timeout_seconds,
        )

    def browser_handoff(self) -> dict[str, Any]:
        return self._request("POST", "/api/universal/browser-handoff", {})

    def grand_map_work_preview(
        self,
        *,
        limit: int = 50,
        include_live: bool = False,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/universal/grand-map-work",
            {"limit": int(limit), "include_live": bool(include_live)},
            response_timeout_seconds=response_timeout_seconds,
        )

    def grand_map_work_sync(
        self,
        *,
        limit: int = 25,
        include_live: bool = False,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/universal/grand-map-work",
            {"limit": int(limit), "include_live": bool(include_live)},
            response_timeout_seconds=response_timeout_seconds,
        )

    def roma_tree_get(
        self,
        *,
        tree_id: str,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/universal/roma-tree",
            {"tree_id": tree_id},
            response_timeout_seconds=response_timeout_seconds,
        )

    def roma_tree_list(
        self,
        *,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/universal/roma-tree",
            {},
            response_timeout_seconds=response_timeout_seconds,
        )

    def roma_tree_sync(
        self,
        tree: Mapping[str, object],
        *,
        source: str = "brain.roma",
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/universal/roma-tree",
            {"tree": dict(tree), "source": source},
            response_timeout_seconds=response_timeout_seconds,
        )

    def workshop_say(
        self,
        *,
        category: str,
        text: str,
        refs: list[str] | tuple[str, ...] = (),
        evidence: list[str] | tuple[str, ...] = (),
        recipients: list[str] | tuple[str, ...] = (),
        reply_to: str | None = None,
        idempotency_key: str,
        created_at: str | None = None,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/api/universal/workshop", {
            "category": category,
            "text": text,
            "refs": list(refs),
            "evidence": list(evidence),
            "recipients": list(recipients),
            "reply_to": reply_to,
            "idempotency_key": idempotency_key,
            "created_at": created_at,
        }, response_timeout_seconds=response_timeout_seconds)

    def workshop_gate(
        self,
        *,
        ref: str,
        phase: str,
        response_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST", "/api/universal/workshop-gate",
            {"ref": ref, "phase": phase},
            response_timeout_seconds=response_timeout_seconds,
        )

    @property
    def agent_session_root(self) -> str:
        return str(self._client.agent_session_root)

    def bind_agent_session(
        self, *, runtime: str, external_session_id: str
    ) -> dict[str, Any]:
        try:
            return self._client.bind_agent_session(
                runtime=runtime,
                external_session_id=external_session_id,
            )
        except self._transport_error as exc:
            raise UniversalRuntimeUnavailable(str(exc)) from exc

    def work_create(
        self,
        *,
        title: str,
        description: str = "",
        priority: int = 0,
        external_key: str = "unset",
        references: Mapping[str, str] | None = None,
        structured_references: Mapping[str, object] | None = None,
        x: float = 0.0,
        y: float = 0.0,
        compact_references: bool = False,
        select_created: bool = True,
    ) -> dict[str, Any]:
        return self._request("POST", "/api/universal/work", {
            "title": title,
            "description": description,
            "priority": priority,
            "external_key": external_key,
            "references": dict(references or {}),
            "structured_references": dict(structured_references or {}),
            "x": x,
            "y": y,
            "compact_references": bool(compact_references),
            "select_created": bool(select_created),
        })

    def assembly_create(
        self,
        *,
        definition_key: str,
        fields: Mapping[str, object] | None = None,
        structured_fields: Mapping[str, object] | None = None,
        idempotency_field: str | None = None,
        x: float = 0.0,
        y: float = 0.0,
    ) -> dict[str, Any]:
        return self._request("POST", "/api/universal/assembly", {
            "definition_key": definition_key,
            "fields": dict(fields or {}),
            "structured_fields": dict(structured_fields or {}),
            "idempotency_field": idempotency_field,
            "x": x,
            "y": y,
        })

    def assembly_field_update(
        self,
        *,
        root: str,
        interface: str,
        value: object,
    ) -> dict[str, Any]:
        return self._request("POST", "/api/universal/assembly-field", {
            "root": root,
            "interface": interface,
            "value": value,
        })

    def work_next(self) -> dict[str, Any]:
        if not self.agent_session_root:
            raise UniversalRuntimeUnavailable(
                "next work requires a bound runtime Agent Session"
            )
        return self._request("POST", "/api/universal/work-next", {})

    def value_read(self, root_id: str) -> object:
        return self._request(
            "POST", "/api/universal/value", {"root": root_id}
        )["value"]

    def work_transition(
        self,
        *,
        root_id: str,
        event: str,
        evidence: str = "",
    ) -> dict[str, Any]:
        if not self.agent_session_root:
            raise UniversalRuntimeUnavailable(
                "work transition requires a bound runtime Agent Session"
            )
        return self._request(
            "POST",
            "/api/universal/work-transition",
            {
                "root": root_id,
                "event": event,
                "evidence": evidence,
                "projection": "receipt-v1",
            },
        )

    def work_court(self, root_id: str) -> dict[str, Any]:
        if not self.agent_session_root:
            raise UniversalRuntimeUnavailable(
                "work court requires a bound runtime Agent Session"
            )
        return self._request(
            "POST",
            "/api/universal/work-court",
            {"root": root_id, "projection": "index"},
        )


__all__ = [
    "UniversalRuntimeBridge",
    "UniversalRuntimeUnavailable",
    "runtime_descriptor_path",
]
