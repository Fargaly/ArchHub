"""Existing coordination tools over one pre-bound installed Workshop owner.

No enrollment, service startup, provider execution, or new message authority lives
here. Ordinary message IDs are not graph Work roots. Explicit acknowledgement
replies record a caller's statement; they do not change read state or settle Work.
"""

from collections.abc import Mapping
import math
from pathlib import Path
import time

from .application_machine_transport import (
    MachineTransportError, UniversalRuntimeClient, _read_descriptor,
)


_OWNER_FIELDS = (
    "runtime_id", "application_root", "workshop_root", "work_registry_root",
    "database", "pipe", "process_id", "started_at", "key_id", "key_version",
)
_METHODS = frozenset({
    "register_session", "list_agents", "workshop_lens", "scope_lens",
    "send_message", "read_messages", "read_message", "acknowledge_message", "claim_work",
})


def _text(value, label, maximum=512):
    if (type(value) is not str or not value.strip() or "\x00" in value
            or len(value.encode("utf-8")) > maximum):
        raise ValueError("invalid " + label)
    return value


def _integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid " + label)
    return value


def _shape(values, required=(), optional=()):
    if set(values) - set(required) - set(optional) or not set(required) <= set(values):
        raise ValueError("installed Workshop operation has invalid parameters")


class InstalledWorkshopCoordinationClient:
    """A backend for clean_coordination_mcp.build_server(client=...).

    Wiring must supply an exclusively owned client bound from authenticated stdio
    identity. Tool parameters cannot select a caller or enroll another session.
    The transport pin checks descriptor identity again at the actual send boundary.
    """

    def __init__(self, client: UniversalRuntimeClient):
        if not isinstance(client, UniversalRuntimeClient):
            raise TypeError("a pre-bound UniversalRuntimeClient is required")
        self._client = client
        self._descriptor_path = Path(client.descriptor_path)
        with client._request_lock:
            self._session = _text(client.agent_session_root, "bound Agent Session")
            _text(client._agent_session_token, "bound Agent Session capability", 4096)
            self._descriptor = _read_descriptor(client.descriptor_path, client.key_provider)
            if self._descriptor.status != "active" or not self._descriptor.database:
                raise MachineTransportError("an active persistent Workshop owner is required")
            if self._session == self._descriptor.agent_session_root:
                raise MachineTransportError("a bound external Agent Session is required")
            client.pin_runtime_descriptor(self._descriptor)
            self._guard()

    def _guard(self):
        client = self._client
        if (client.agent_session_root != self._session
                or type(client._agent_session_token) is not str or not client._agent_session_token
                or client.agent_session_access != "full"
                or Path(client.descriptor_path) != self._descriptor_path
                or client._pinned_runtime_descriptor != self._descriptor):
            raise MachineTransportError("installed Workshop client binding changed")
        descriptor = _read_descriptor(client.descriptor_path, client.key_provider)
        if (descriptor.status != "active"
                or any(getattr(descriptor, key) != getattr(self._descriptor, key) for key in _OWNER_FIELDS)):
            raise MachineTransportError("installed Workshop owner changed; explicit reattachment is required")

    def _request(self, method, path, body, deadline):
        self._guard()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MachineTransportError("installed Workshop operation exceeded its wait budget")
        result = self._client.request(method, path, body, response_timeout_seconds=remaining)
        if type(result) is not dict or result.get("ok") is False:
            raise MachineTransportError("installed Workshop response is invalid")
        return result

    def _page(self, values, deadline, *, workshop=False):
        if workshop:
            result = self._request("GET", "/api/universal/workshop", {}, deadline)
        else:
            body = {"space": self._descriptor.workshop_root,
                    "limit": _integer(values.get("limit", 50), "message limit", 1, 100)}
            if values.get("before") is not None:
                body["before"] = _integer(values["before"], "message sequence cursor", 1, 2**63 - 1)
            result = self._request("GET", "/api/universal/deliberation", body, deadline)
        if (result.get("application") != self._descriptor.application_root
                or result.get("workshop" if workshop else "space") != self._descriptor.workshop_root
                or result.get("agent_session") != self._session
                or result.get("storage") != "conversation-content"
                or type(result.get("entries")) is not list):
            raise MachineTransportError("ordinary Workshop response identity changed")
        for entry in result["entries"]:
            if (type(entry) is not dict or type(entry.get("message_id")) is not str
                    or not entry["message_id"] or entry.get("root") != entry["message_id"]
                    or type(entry.get("sequence")) is not int or entry["sequence"] < 1
                    or type(entry.get("actor")) is not str or not entry["actor"]
                    or type(entry.get("recipients")) is not list
                    or any(type(root) is not str or not root for root in entry["recipients"])):
                raise MachineTransportError("ordinary Workshop message identity is invalid")
        return {**result, "ok": True}

    def _read_message(self, values, deadline):
        message_id = _text(values["message_id"], "ordinary message ID")
        sequence = _integer(values["sequence"], "ordinary message sequence", 1, 2**63 - 2)
        page = self._page({"limit": 1, "before": sequence + 1}, deadline)
        entries = page["entries"]
        if (len(entries) != 1 or type(entries[0]) is not dict
                or entries[0].get("message_id") != message_id
                or entries[0].get("sequence") != sequence):
            raise MachineTransportError("exact ordinary message is not visible to this session")
        return {"ok": True, "application": page["application"], "space": page["space"],
                "agent_session": self._session, "storage": "conversation-content",
                "revision": page["revision"], "message": entries[0]}

    def _send(self, *, target, message, idempotency_key, reply_to, deadline):
        target = _text(target, "recipient root")
        body = {"category": "note", "text": _text(message, "message", 65536),
                "refs": [], "evidence": [], "recipients": [target],
                "reply_to": None if reply_to is None else _text(reply_to, "ordinary reply message ID"),
                "idempotency_key": _text(idempotency_key, "idempotency key"), "created_at": None}
        result = self._request("POST", "/api/universal/workshop", body, deadline)
        if (result.get("workshop") != self._descriptor.workshop_root
                or result.get("storage") != "conversation-content"
                or result.get("actor") != self._session
                or result.get("recipients") != [target]
                or result.get("reply_to") != reply_to
                or type(result.get("message_id")) is not str or not result["message_id"]
                or result.get("root") != result["message_id"]):
            raise MachineTransportError("ordinary Workshop send response identity changed")
        return {**result, "ok": True}

    def call(self, method: str, parameters: Mapping[str, object] | None = None,
             *, timeout_seconds: float = 35.0) -> dict[str, object]:
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 35):
            raise ValueError("Workshop wait budget must be within 35 seconds")
        deadline = time.monotonic() + timeout_seconds
        with self._client._request_lock:
            self._guard()
            if type(method) is not str or method not in _METHODS:
                if method == "wait_agent":
                    raise ValueError("clean graph revision cursors are unsupported; use read_messages with an ordinary sequence cursor")
                if method == "mark_message_read":
                    raise ValueError("use acknowledge_message with an exact ordinary message_id and sequence; no read-state transition is available")
                if method == "claim_workshop_message":
                    raise ValueError("ordinary messages are not Work; use claim_work with an exact work_root")
                raise ValueError("this coordination operation is unsupported by the installed Workshop backend")
            if parameters is not None and not isinstance(parameters, Mapping):
                raise ValueError("Workshop parameters must be a mapping")
            values = dict(parameters or {})
            if method in {"register_session", "list_agents", "workshop_lens", "scope_lens"}:
                _shape(values, ("scope_root",) if method == "scope_lens" else ())
                if method == "scope_lens" and values["scope_root"] != self._descriptor.workshop_root:
                    raise ValueError("only the existing Workshop scope is supported")
                page = self._page({}, deadline, workshop=True)
                if method in {"workshop_lens", "scope_lens"}:
                    return {**page, "self": self._session, "scope": self._descriptor.workshop_root}
                base = {"ok": True, "application": page["application"], "self": self._session,
                        "scope": self._descriptor.workshop_root, "revision": page["revision"]}
                if method == "register_session":
                    return {**base, "registration": "existing-bound-session"}
                observed = {self._session}
                for entry in page["entries"]:
                    if type(entry) is dict:
                        observed.update(root for root in [entry.get("actor"), *(entry.get("recipients") or [])]
                                        if type(root) is str and root)
                return {**base, "agents": [{"root": root} for root in sorted(observed)],
                        "coverage": "bound self and identities observed in this permitted message page",
                        "complete_roster": False, "presence_verified": False}
            if method == "read_messages":
                _shape(values, optional=("limit", "before"))
                return self._page(values, deadline)
            if method in {"read_message", "acknowledge_message"}:
                required = ("message_id", "sequence") + (("idempotency_key",) if method == "acknowledge_message" else ())
                _shape(values, required)
                if method == "acknowledge_message":
                    _text(values["idempotency_key"], "idempotency key")
                read = self._read_message(values, deadline)
                if method == "read_message":
                    return read
                original = read["message"]
                if self._session not in (original.get("recipients") or []):
                    raise MachineTransportError("only the addressed session may acknowledge this directed message")
                result = self._send(target=original["actor"],
                    message="Read acknowledgement for ordinary message " + values["message_id"],
                    idempotency_key=values["idempotency_key"], reply_to=values["message_id"], deadline=deadline)
                return {**result, "acknowledged_message_id": values["message_id"],
                        "acknowledgement": "explicit-reply", "read_state_changed": False}
            if method == "send_message":
                _shape(values, ("target", "message", "idempotency_key"), ("reply_to",))
                return self._send(target=values["target"], message=values["message"],
                    idempotency_key=values["idempotency_key"], reply_to=values.get("reply_to"), deadline=deadline)
            _shape(values, ("work_root",))
            work_root = _text(values["work_root"], "graph Work root")
            result = self._request("POST", "/api/universal/work-transition",
                {"root": work_root, "event": "claim", "evidence": "", "projection": "receipt-v1"}, deadline)
            if (result.get("work_root") != work_root or result.get("agent_session") != self._session
                    or result.get("event") != "claim" or result.get("projection") != "receipt-v1"
                    or type(result.get("history_root")) is not str):
                raise MachineTransportError("governed Work claim receipt identity changed")
            new_claim = bool(result["history_root"])
            return {**result, "ok": True, "new_claim": new_claim,
                    "claim_status": "claimed" if new_claim else "already-held"}


__all__ = ["InstalledWorkshopCoordinationClient"]
