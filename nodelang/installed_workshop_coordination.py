"""Shared Workshop mailbox plus the separate governed Work reads and claims."""

from collections.abc import Mapping
import math
from pathlib import Path
import time

from .application_machine_transport import (
    MachineTransportError, RuntimeResolutionError, UniversalRuntimeClient, resolve_active_runtime,
)


_OWNER_FIELDS = (
    "runtime_id", "application_root", "workshop_root", "work_registry_root",
    "database", "pipe", "process_id", "started_at", "key_id", "key_version",
)
_METHODS = frozenset({
    "read_messages", "read_message", "claim_work",
    "private_root_grant_status",
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
    """The internal governed Work and host adapter for the installed application.

    Wiring must supply an exclusively owned client bound from authenticated stdio
    identity. Tool parameters cannot select a caller or enroll another session.
    The transport pin checks descriptor identity again at the actual send boundary.
    """

    _ACCESS = "full"

    def __init__(self, client: UniversalRuntimeClient):
        if not isinstance(client, UniversalRuntimeClient):
            raise TypeError("a pre-bound UniversalRuntimeClient is required")
        self._client = client
        self._descriptor_path = Path(client.descriptor_path)
        with client._request_lock:
            self._session = _text(client.agent_session_root, "bound Agent Session")
            _text(client._agent_session_token, "bound Agent Session capability", 4096)
            try:
                self._descriptor = resolve_active_runtime(client.descriptor_path, client.key_provider)
            except RuntimeResolutionError as refusal:
                raise MachineTransportError(
                    "an active persistent Workshop owner is required (%s)" % refusal.kind) from refusal
            if not self._descriptor.database:
                raise MachineTransportError("an active persistent Workshop owner is required")
            if self._session == self._descriptor.agent_session_root:
                raise MachineTransportError("a bound external Agent Session is required")
            client.pin_runtime_descriptor(self._descriptor)
            self._guard()

    def _guard(self):
        client = self._client
        if (client.agent_session_root != self._session
                or type(client._agent_session_token) is not str or not client._agent_session_token
                or client.agent_session_access != self._ACCESS
                or Path(client.descriptor_path) != self._descriptor_path
                or client._pinned_runtime_descriptor != self._descriptor):
            raise MachineTransportError("installed Workshop client binding changed")
        try:
            descriptor = resolve_active_runtime(client.descriptor_path, client.key_provider)
        except RuntimeResolutionError as refusal:
            raise MachineTransportError(
                "installed Workshop owner changed; explicit reattachment is required (%s)" % refusal.kind
            ) from refusal
        if (any(getattr(descriptor, key) != getattr(self._descriptor, key) for key in _OWNER_FIELDS)):
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

    def _page(self, values, deadline):
        body = {"space": self._descriptor.workshop_root,
                "limit": _integer(values.get("limit", 50), "message limit", 1, 100)}
        if values.get("before") is not None:
            body["before"] = _integer(values["before"], "message sequence cursor", 1, 2**63 - 1)
        result = self._request("GET", "/api/universal/deliberation", body, deadline)
        if (result.get("application") != self._descriptor.application_root
                or result.get("space") != self._descriptor.workshop_root
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
                    raise ValueError("no read-state transition is available; use read_message for the exact ordinary message")
                if method == "claim_workshop_message":
                    raise ValueError("ordinary messages are not Work; use claim_work with an exact work_root")
                raise ValueError("this coordination operation is unsupported by the installed Workshop backend")
            if parameters is not None and not isinstance(parameters, Mapping):
                raise ValueError("Workshop parameters must be a mapping")
            values = dict(parameters or {})
            if method == "read_messages":
                _shape(values, optional=("limit", "before"))
                return self._page(values, deadline)
            if method == "read_message":
                _shape(values, ("message_id", "sequence"))
                return self._read_message(values, deadline)
            if method == "private_root_grant_status":
                _shape(values, ("root_id",))
                root_id = _text(values["root_id"], "private root id", 64)
                status = self._client.private_root_grant_status(
                    path="workspace-roots/%s/__grant_status__" % root_id,
                    operation="write_file",
                    response_timeout_seconds=max(0.1, deadline - time.monotonic()),
                )
                if status.get("granted") is True:
                    until = status.get("until")
                    return {**status, "ok": True, "status": "granted until %s" % until}
                reason = status.get("reason")
                if type(reason) is not str or not reason:
                    reason = "no grant: ask the founder in Settings > Workspaces"
                return {**status, "ok": True, "status": reason}
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


class InstalledWorkshopInboxReader(InstalledWorkshopCoordinationClient):
    """Read the deliberation spaces a recovered original actor is authorized for; no writes."""

    _ACCESS = "recovery-read"
    READS = frozenset({"read_messages", "read_message"})

    def call(self, method: str, parameters: Mapping[str, object] | None = None,
             *, timeout_seconds: float = 35.0) -> dict[str, object]:
        if method not in self.READS:
            raise MachineTransportError(self.NOTICE)
        result = super().call(method, parameters, timeout_seconds=timeout_seconds)
        return {**result, "access": "read-only", "notice": self.NOTICE}

    NOTICE = ("Reading messages works. Replies and file changes are paused until "
              "this agent reconnects to the app.")


__all__ = ["InstalledWorkshopCoordinationClient", "InstalledWorkshopInboxReader"]


MAILBOX_ROUTES = frozenset({
    ("POST", "/api/universal/agent-mail/send"),
    ("GET", "/api/universal/agent-mail/read"),
    ("POST", "/api/universal/agent-mail/declare"),
})
_mailbox_now = time.monotonic


def _recent_mailbox_peers(history, space):
    """One bounded public tail, latest key per display address; never a roster."""
    import re
    from .agent_runtime_registry import RUNTIMES
    peers = {}
    for row in history._db.execute(
            "SELECT author,sequence FROM messages WHERE conversation_id=? AND public=1 "
            "ORDER BY sequence DESC LIMIT 100", (space,)):
        label, separator, key = row["author"].removesuffix("]").rpartition(" [")
        if (not separator or label == "BABOOM" or label in peers
                or not re.fullmatch(r"agent:\d+:\d+(?::[0-9a-f]{64})?", key)):
            continue
        runtime = next((name for name, definition in RUNTIMES.items()
            if label.startswith(definition["label"] + " / ")), "mcp")
        peers[label] = {"label": label, "sender_key": key, "runtime": runtime,
                        "sequence": row["sequence"]}
    return list(peers.values())


def dispatch_mailbox(owner, request, peer):
    """Authenticated local transport only: a public room, never Work authority.

    The OS supplies the connection's identity. Session/body fields cannot select
    another sender. Public ordinary messages share the existing Workshop table;
    private messages and other conversations are never included in this API.
    """
    from .application_machine_transport import MachinePipePeer
    from .cell_authorization import AuthorizationDenied
    from .conversation_content import read_content_binding
    from .universal_application import _require_application_authorization
    from uuid import uuid4

    route = (request.get("method"), request.get("path"))
    if route not in MAILBOX_ROUTES or type(peer) is not MachinePipePeer:
        raise AuthorizationDenied("shared messages require an authenticated local pipe")
    if request.get("session") != {}:
        raise AuthorizationDenied("shared messages do not accept an alternate sender")
    body = request.get("body")
    declaring = route[1].endswith("/declare")
    send = route[1].endswith("/send")
    writing = send or declaring
    fields = {"task", "request_id", "paths", "status"} if declaring else {"to", "text"} if send else {"since"}
    optional = {"context"} | ({"declarations_after", "include_archived"} if not writing else {"reply_to"} if send else set())
    if type(body) is not dict or not fields <= set(body) or set(body) - fields - optional:
        raise ValueError("shared message arguments are invalid")
    name = "agent:%d:%d" % (peer.pid, round(peer.created_at * 1000000))
    context = body.get("context", {})
    from .agent_declarations import SESSION_KEYS
    if type(context) is not dict or (context and (len(context) != 1 or not set(context) <= set(SESSION_KEYS))):
        raise ValueError("calling session metadata is invalid")
    if context:
        from hashlib import sha256
        key, value = next(iter(context.items()))
        if type(value) is not str or not value or "\0" in value or len(value.encode("utf-8")) > 256:
            raise ValueError("calling session metadata is invalid")
        # The peer prefix is always OS-observed. Another process cannot claim
        # this connector's name, even with identical vendor correlation data.
        name += ":" + sha256((key + ":" + value).encode("utf-8")).hexdigest()
    import os
    from .agent_runtime_registry import mailbox_label
    label, _runtime = ("BABOOM", "baboom") if peer.pid == os.getpid() else mailbox_label(peer, context)
    if peer.pid == os.getpid() and "archhub/sessionID" in context:
        label = "ArchHub / " + context["archhub/sessionID"]
    identity = {"sender_key": name, "sender_label": label}
    name = label + " [" + name + "]"
    if send:
        target = _text(body["to"], "recipient name", 512)
        if target.casefold() == "founder":
            target = "founder"
        if "\n" in target or "\r" in target:
            raise ValueError("recipient name must be one line")
        text = _text(body["text"], "message", 65536)
        content = _text("To " + target + ":\n" + text, "addressed message", 65536)
        if "reply_to" in body:
            _text(body["reply_to"], "thread message", 512)
    elif not declaring:
        _integer(body["since"], "message cursor", 0, 2**63 - 1)
        if type(body.get("declarations_after", "")) is not str or len(body.get("declarations_after", "")) > 512:
            raise ValueError("invalid declaration cursor")
        if type(body.get("include_archived", False)) is not bool:
            raise ValueError("invalid declaration archive selection")
    with owner.mutation_lock:
        service = owner.conversation_content
        service._require_live_owner()
        registry, store = owner.universal_registry, owner.universal_store
        authority = registry.authorization
        context = authority.session.context()
        from contextlib import nullcontext
        # A declaration writes graph nodes. Ordinary notes/reads retain their
        # stable read boundary; graph writes hold the same owner/broker locks.
        boundary = nullcontext(store.snapshot()) if declaring else store.stable_snapshot()
        with authority.broker.live_context(context), boundary as snapshot:
            space = registry.workshop_root
            binding = read_content_binding(snapshot, registry.deliberation_protocol,
                application_root=registry.application_root, space_root=space)
            history = service._history_for(binding)

            def guard():
                service._require_live_owner()
                authority.broker.resolve(context)
                if not service.belongs_to(store, registry) or store.revision != snapshot.revision:
                    raise AuthorizationDenied("Workshop authority changed")
                _require_application_authorization(snapshot, registry,
                    "edit" if writing else "read", space, authentication_context=context)
                if owner.universal_checkpoint_guard is not None:
                    owner.universal_checkpoint_guard.require_healthy()
                owner.require_universal_http_route("POST" if writing else "GET",
                    "/api/universal/workshop", authentication_context=context)

            guard()
            if declaring:
                from .agent_declarations import publish

                def append_notice(content, key, refs):
                    nonlocal snapshot
                    snapshot = store.snapshot()
                    return history.append(space, author="Workshop coordination", content=content,
                        category=registry.workshop_category_roots["note"], refs=refs,
                        idempotency_key=key, before_commit=guard)

                # publish reuses the currently authenticated identity; the tool
                # cannot name an agent, session, node root or process itself.
                caller = body.get("context", {})
                from .commit_intent import USER_ACTION, declare
                with declare(USER_ACTION, actor=authority.subject_root,
                             reason="authenticated founder-local Workshop task declaration"):
                    result = publish(owner, peer, identity, caller, body,
                        append=append_notice)
                return {**identity, **result}
            if send:
                from collections import deque
                now = _mailbox_now()
                windows = owner._agent_mail_send_windows
                peer_key = (peer.pid, peer.created_at)
                if peer_key not in windows and len(windows) >= 1024:
                    for key in tuple(windows):
                        if not windows[key] or windows[key][-1] <= now - 60:
                            del windows[key]
                    if len(windows) >= 1024:
                        raise AuthorizationDenied("mailbox peer budget exhausted")
                window = windows.setdefault(peer_key, deque())
                while window and window[0] <= now - 60:
                    window.popleft()
                if len(window) >= 30:
                    raise AuthorizationDenied("mailbox permits 30 messages per minute per peer")
                # Addressing is visible text in the ONE shared room, not a private
                # recipients ACL or a native delivery/relay promise.
                row = history.append(space, author=name, content=content,
                    category=registry.workshop_category_roots["note"], recipients=(), idempotency_key=uuid4().hex,
                    reply_to=body.get("reply_to"), reply_principal=name,
                    before_commit=guard)
                window.append(_mailbox_now())
                return {**identity, "sender": name, "to": target, "text": text,
                        "sequence": row["sequence"], "message_id": row["id"]}
            with history._transaction():
                cursor = history._db.execute(
                    "SELECT * FROM messages WHERE conversation_id=? AND public=1 "
                    "AND sequence>? ORDER BY sequence LIMIT 101", (space, body["since"]))
                # Reserve room for the bounded recent-peer metadata envelope.
                rows, more = history._collect(cursor, 100, 180000)
                peers = _recent_mailbox_peers(history, space)
                guard()
            from .agent_declarations import declarations
            import json
            current = sorted(declarations(owner, include_archived=body.get("include_archived",False)), key=lambda row: row["root"])
            result = {**identity, "sender": name, "messages": [], "peers": peers, "more": more,
                      "next_since": body["since"],
                      "declarations": [], "declaration_total":len(current),
                      "working_count":sum(row["current"] and row["status"] == "working" for row in current),
                      "declarations_more":False, "declarations_after":""}
            for row in rows:
                candidate = {**result, "messages":[*result["messages"], row], "next_since":row["sequence"]}
                if len(json.dumps(candidate, ensure_ascii=True).encode()) > 240000:
                    if not result["messages"]:
                        raise ValueError("single Workshop message exceeds the machine envelope budget")
                    result["more"] = True
                    break
                result = candidate
            # The entire envelope shares the existing pipe byte budget. Large
            # declarations page independently of the ordinary message cursor.
            for row in current:
                if row["root"] <= body.get("declarations_after", ""):
                    continue
                candidate = {**result, "declarations":[*result["declarations"], row]}
                if len(json.dumps(candidate, ensure_ascii=True).encode()) > 240000:
                    result["declarations_more"] = True
                    break
                result = candidate
                result["declarations_after"] = row["root"]
            return result
