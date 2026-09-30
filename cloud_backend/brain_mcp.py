"""This account's brain, over MCP, on the cloud.

The brain belongs on the cloud, one per account, reachable from every machine
the founder signs in on. The DATA has been here all along -- his replica holds
1,797 facts and answers /v1/brain/stats in 0.9s -- but sessions speak MCP and
this cloud served only REST, so Claude, Codex and Antigravity all point at a
LOCAL daemon on 127.0.0.1:8473 instead. That daemon is the thing that must be
alive, hold a port and survive a wedge; the brain failures the founder hit
came from that, not from the memory itself (audit, 2026-09-07).

The cloud's own attempt to reach a brain proves the shape of the gap:
founder_cockpit.py used to dial the local daemon's loopback address, which inside a
Fly container is that container's own loopback, where no brain has ever run.

This speaks the same stateless streamable-HTTP shape the local daemon speaks
-- one `event: message` block whose `data:` line is the JSON-RPC response --
so an existing client only changes its URL. Identity is the ACCOUNT token,
never a machine, so the same brain answers from any device.

Read-only on purpose. Writes stay on /v1/brain/sync, which already carries
the secret screening and the scope rules; a second write door here would put
that boundary in two places.
"""
from __future__ import annotations

import json
from typing import Any, Callable

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
DEFAULT_PROTOCOL = "2025-03-26"

TOOLS = [
    {
        "name": "brain.health",
        "description": (
            "Whether this account's cloud brain is answering, and how much "
            "it holds."
        ),
        "inputSchema": {
            "type": "object", "properties": {}, "additionalProperties": False,
        },
    },
    {
        "name": "brain.search",
        "description": "Search this account's brain facts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "what to look for"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["q"],
            "additionalProperties": False,
        },
    },
    {
        "name": "brain.list_facts",
        "description": "List this account's brain facts, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
    },
]

# The founder's desktop, read remotely. Only his accounts see or call these
# (answer(is_founder=...)); everyone else gets the brain tools alone. Reads
# only: the desktop answers them with the same local functions its own host
# tools use (nodelang/cloud_relay.py host_read, an allowlist), and nothing that
# executes, captures a screen or sends is listed here.
_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}
OFFICE_READS = (
    "excel.list_workbooks", "excel.list_worksheets", "word.list_documents",
    "word.list_paragraphs", "powerpoint.list_presentations", "powerpoint.list_slides",
)
HOST_TOOLS = [
    {"name": "hosts.state", "inputSchema": _NO_ARGS, "description": (
        "The hosts the founder's ArchHub app last published and how old that "
        "snapshot is. Does not wake the desktop.")},
    {"name": "hosts.status", "inputSchema": _NO_ARGS, "description": (
        "Live: every connector on the founder's desktop and the evidence behind "
        "each operation. Needs ArchHub open and signed in there.")},
    {"name": "revit.sessions", "inputSchema": _NO_ARGS, "description": (
        "Live: the Revit sessions listening on the founder's desktop.")},
    {"name": "connector.rows", "inputSchema": _NO_ARGS, "description": (
        "Live: the host and catalogue rows the founder's desktop probes.")},
    {"name": "office.read", "description": (
        "Live: what Excel, Word or PowerPoint hold open on the founder's desktop."),
     "inputSchema": {"type": "object", "properties": {
         "operation": {"type": "string", "enum": list(OFFICE_READS)},
         "name": {"type": "string", "maxLength": 200,
                  "description": "workbook, document or presentation name"},
     }, "additionalProperties": False}},
    {"name": "outlook.inbox", "description": (
        "Live: the newest items in the founder's open Outlook inbox."),
     "inputSchema": {"type": "object", "properties": {
         "count": {"type": "integer", "minimum": 1, "maximum": 50},
     }, "additionalProperties": False}},
    {"name": "dropbox.list", "description": (
        "Live: the files in one folder of the founder's Dropbox."),
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "maxLength": 300,
                  "description": "folder relative to the Dropbox root"},
     }, "additionalProperties": False}},
]
HOST_TOOL_NAMES = frozenset(tool["name"] for tool in HOST_TOOLS)

# The founder's Workshop, joined by the calling MCP client as ITS OWN agent (Spark
# is one agent, Notion another), exactly as Claude and Codex join it locally: the
# founder's running app binds the client as a runtime Agent Session and answers
# through the installed Workshop coordination client (nodelang/cloud_relay.py
# workshop_call). Listed only to a founder account holding an OAuth token with
# mcp:workshop. Messages and Work claims only; nothing runs on the desktop.
_TEXT_ID = {"type": "string", "minLength": 1, "maxLength": 256}
_SEQUENCE = {"type": "integer", "minimum": 1}
_KEY = {"type": "string", "minLength": 8, "maxLength": 128}
WORKSHOP_MESSAGE_LIMIT = 1500  # one queued task carries 2000 characters
WORKSHOP_TOOLS = [
    {"name": "workshop.lens", "inputSchema": _NO_ARGS, "description": (
        "The founder's Workshop as your agent sees it: its newest messages and "
        "your own agent id. Needs ArchHub open and signed in on his desktop.")},
    {"name": "workshop.agents", "inputSchema": _NO_ARGS, "description": (
        "Agents seen in the Workshop's recent messages, and your own agent id.")},
    {"name": "workshop.read", "description": (
        "A page of Workshop messages visible to your agent, newest first; pass "
        "before=<sequence> for older ones."),
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 20},
         "before": _SEQUENCE,
     }, "additionalProperties": False}},
    {"name": "workshop.message", "description": "One exact Workshop message by id and sequence.",
     "inputSchema": {"type": "object", "properties": {
         "message_id": _TEXT_ID, "sequence": _SEQUENCE,
     }, "required": ["message_id", "sequence"], "additionalProperties": False}},
    {"name": "workshop.post", "description": (
        "Post a message in the Workshop as your agent, to one agent id. Reuse the "
        "same idempotency_key when retrying after a lost reply."),
     "inputSchema": {"type": "object", "properties": {
         "target": _TEXT_ID,
         "message": {"type": "string", "minLength": 1, "maxLength": WORKSHOP_MESSAGE_LIMIT},
         "idempotency_key": _KEY,
         "reply_to": _TEXT_ID,
     }, "required": ["target", "message", "idempotency_key"], "additionalProperties": False}},
    {"name": "workshop.acknowledge", "description": (
        "Reply that you read a message addressed to your agent. Does not claim completion."),
     "inputSchema": {"type": "object", "properties": {
         "message_id": _TEXT_ID, "sequence": _SEQUENCE, "idempotency_key": _KEY,
     }, "required": ["message_id", "sequence", "idempotency_key"], "additionalProperties": False}},
    {"name": "work.claim", "description": (
        "Claim one exact Governed Work (for example Work assigned to your agent). "
        "A claim grants no file writes or execution."),
     "inputSchema": {"type": "object", "properties": {"work_root": _TEXT_ID},
                     "required": ["work_root"], "additionalProperties": False}},
]
WORKSHOP_TOOL_NAMES = frozenset(tool["name"] for tool in WORKSHOP_TOOLS)
WORKSHOP_METHODS = {
    "workshop.lens": "workshop_lens", "workshop.agents": "list_agents",
    "workshop.read": "read_messages", "workshop.message": "read_message",
    "workshop.post": "send_message", "workshop.acknowledge": "acknowledge_message",
    "work.claim": "claim_work",
}
WORKSHOP_SCOPE = "mcp:workshop"


def workshop_client(user: dict) -> dict | None:
    """The OAuth client this call comes from, when it was granted the Workshop."""
    held = user.get("mcp_client") if isinstance(user, dict) else None
    if (not isinstance(held, dict) or not isinstance(held.get("client_id"), str)
            or not held["client_id"] or WORKSHOP_SCOPE not in (held.get("scopes") or [])):
        return None
    return {"client_id": held["client_id"], "client_name": str(held.get("client_name") or "")[:200]}


def _bounded_text(arguments: dict, key: str, limit: int, *, required: bool = True):
    value = arguments.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("%s must be text of at most %d characters" % (key, limit))
    return value


def _sequence(arguments: dict, key: str, *, required: bool = True):
    value = arguments.get(key)
    if value is None and not required:
        return None
    if type(value) is not int or value < 1:
        raise ValueError("%s must be a positive message sequence" % key)
    return value


def workshop_arguments(name: str, arguments: dict) -> dict:
    """Only the declared parameters travel to the desktop, checked and bounded."""
    if name in ("workshop.lens", "workshop.agents"):
        return {}
    if name == "workshop.read":
        limit = arguments.get("limit")
        kept = {"limit": max(1, min(limit, 20)) if type(limit) is int else 10}
        before = _sequence(arguments, "before", required=False)
        if before is not None:
            kept["before"] = before
        return kept
    if name == "workshop.message":
        return {"message_id": _bounded_text(arguments, "message_id", 256),
                "sequence": _sequence(arguments, "sequence")}
    if name == "workshop.post":
        kept = {"target": _bounded_text(arguments, "target", 256),
                "message": _bounded_text(arguments, "message", WORKSHOP_MESSAGE_LIMIT),
                "idempotency_key": _bounded_text(arguments, "idempotency_key", 128)}
        reply_to = _bounded_text(arguments, "reply_to", 256, required=False)
        if reply_to is not None:
            kept["reply_to"] = reply_to
        return kept
    if name == "workshop.acknowledge":
        return {"message_id": _bounded_text(arguments, "message_id", 256),
                "sequence": _sequence(arguments, "sequence"),
                "idempotency_key": _bounded_text(arguments, "idempotency_key", 128)}
    if name == "work.claim":
        return {"work_root": _bounded_text(arguments, "work_root", 256)}
    raise KeyError(name)


def host_arguments(name: str, arguments: dict) -> dict:
    """Only the declared arguments travel to the desktop, bounded."""
    if name == "office.read":
        operation = arguments.get("operation", OFFICE_READS[0])
        if operation not in OFFICE_READS:
            raise ValueError("office.read reads only: %s" % ", ".join(OFFICE_READS))
        kept = {"operation": operation}
        if isinstance(arguments.get("name"), str) and arguments["name"].strip():
            kept["name"] = arguments["name"][:200]
        return kept
    if name == "outlook.inbox":
        count = arguments.get("count")
        return {"count": max(1, min(count, 50)) if type(count) is int else 20}
    if name == "dropbox.list":
        path = arguments.get("path")
        return {"path": path[:300] if isinstance(path, str) else ""}
    return {}


def text_result(payload: object) -> dict:
    """One tool result in the content shape every MCP client reads."""
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
        ]
    }


def account_facts(replica) -> list:
    """This account's facts, from its own replica read-set."""
    import community_review
    merged = community_review.hold_unreviewed(replica.user_id, replica.export_delta(since_hlc=""))
    return [
        fragment for fragment in merged.get("fragments", [])
        if (fragment.get("kind") or "fact") == "fact"
    ]


def call_tool(user: dict, replica, name: str, arguments: dict) -> dict:
    """Answer one tool call from the caller's OWN replica."""
    if name == "brain.health":
        return text_result({
            "ok": True,
            "where": "cloud",
            "account": user.get("email"),
            "facts": len(account_facts(replica)),
            "plan": user.get("plan"),
        })
    if name in ("brain.search", "brain.list_facts"):
        want = arguments.get("limit")
        want = max(1, min(int(want), 200)) if isinstance(want, int) else 20
        rows = account_facts(replica)
        needle = str(arguments.get("q") or "").strip().lower()
        if needle:
            rows = [
                fragment for fragment in rows
                if needle in json.dumps(fragment, ensure_ascii=False).lower()
            ]
        rows = rows[-want:]
        return text_result({
            "count": len(rows),
            "facts": [
                {
                    "text": str(fragment.get("text") or "")[:2000],
                    "subject": fragment.get("subject"),
                    "object": fragment.get("object"),
                }
                for fragment in rows
            ],
        })
    raise KeyError(name)


def call_host_tool(user: dict, name: str, arguments: dict, *,
                   host_read, pushed_hosts) -> dict:
    """One founder read of his desktop: the published snapshot, or live from his app."""
    if name == "hosts.state":
        if pushed_hosts is None:
            raise RuntimeError("this cloud holds no published host snapshot")
        return text_result(pushed_hosts())
    if host_read is None:
        raise RuntimeError("live host reads are not wired on this cloud")
    return text_result(host_read(user, name, host_arguments(name, arguments)))


def call_workshop_tool(user: dict, name: str, arguments: dict, *, workshop_call) -> dict:
    """One Workshop step as the calling client's own agent, answered by the founder's app."""
    client = workshop_client(user)
    if client is None:
        raise PermissionError("this connection was not granted the Workshop; reconnect "
                              "ArchHub in this application and approve Workshop access")
    if workshop_call is None:
        raise RuntimeError("the Workshop is not wired on this cloud")
    return text_result(workshop_call(user, client, WORKSHOP_METHODS[name],
                                     workshop_arguments(name, arguments)))


def sse_block(rpc_id: object, body: dict) -> bytes:
    """One SSE message block: the exact shape the local daemon returns."""
    said = json.dumps({"jsonrpc": "2.0", "id": rpc_id, **body},
                      ensure_ascii=False)
    return ("event: message\ndata: " + said + "\n\n").encode("utf-8")


def answer(
    message: object,
    *,
    resolve_user: Callable[[], dict],
    open_replica: Callable[[dict], Any],
    is_founder: Callable[[dict], bool] = lambda user: False,
    host_read: Callable[[dict, str, dict], object] | None = None,
    pushed_hosts: Callable[[], dict] | None = None,
    workshop_call: Callable[[dict, dict, str, dict], object] | None = None,
) -> tuple[int, bytes, str]:
    """Dispatch one JSON-RPC message. Returns (status, body, media type).

    Transport-free on purpose, so the whole protocol is testable without a
    socket: the route only reads the request and writes what this says.
    The host tools exist only for an account `is_founder` admits; a live one
    is answered by `host_read(user, tool, arguments)`, hosts.state by
    `pushed_hosts()`.
    """
    sse = "text/event-stream"
    if not isinstance(message, dict):
        return 400, b"{}", "application/json"

    rpc_id = message.get("id")
    method = str(message.get("method") or "")
    params = (
        message.get("params")
        if isinstance(message.get("params"), dict) else {}
    )

    if rpc_id is None and method.startswith("notifications/"):
        return 202, b"", sse

    if method == "initialize":
        wanted = params.get("protocolVersion")
        return 200, sse_block(rpc_id, {"result": {
            "protocolVersion": (
                wanted
                if isinstance(wanted, str) and wanted in PROTOCOL_VERSIONS
                else DEFAULT_PROTOCOL
            ),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "archhub-cloud-brain", "version": "1"},
        }}), sse
    if method == "tools/list":
        # Listing stays open; a founder's token adds his desktop's read tools.
        try:
            lister = resolve_user()
        except Exception:
            lister = None
        founder = lister is not None and bool(is_founder(lister))
        # The Workshop group: the founder's own OAuth client granted mcp:workshop.
        workshop = founder and workshop_client(lister) is not None
        return 200, sse_block(rpc_id, {"result": {
            "tools": (TOOLS + HOST_TOOLS + (WORKSHOP_TOOLS if workshop else []))
            if founder else TOOLS}}), sse
    if method != "tools/call":
        return 200, sse_block(rpc_id, {
            "error": {"code": -32601, "message": "unsupported method"},
        }), sse

    # Every tool call is the ACCOUNT's, never a machine's.
    try:
        user = resolve_user()
    except Exception:
        return 401, sse_block(rpc_id, {
            "error": {"code": -32001, "message": "sign in to reach your brain"},
        }), sse

    name = str(params.get("name") or "")
    arguments = (
        params.get("arguments")
        if isinstance(params.get("arguments"), dict) else {}
    )
    try:
        if name in HOST_TOOL_NAMES:
            if not is_founder(user):
                raise KeyError(name)  # another account is never told they exist
            result = call_host_tool(user, name, arguments,
                                    host_read=host_read, pushed_hosts=pushed_hosts)
        elif name in WORKSHOP_TOOL_NAMES:
            if not is_founder(user):
                raise KeyError(name)  # another account is never told they exist
            result = call_workshop_tool(user, name, arguments, workshop_call=workshop_call)
        else:
            result = call_tool(user, open_replica(user), name, arguments)
    except KeyError:
        return 200, sse_block(rpc_id, {
            "error": {"code": -32602, "message": "unknown tool"},
        }), sse
    except Exception as refusal:
        # A refusal IS the answer; it is never a silent drop.
        return 200, sse_block(rpc_id, {"result": {
            "content": [{
                "type": "text",
                "text": "%s: %s" % (type(refusal).__name__, refusal),
            }],
            "isError": True,
        }}), sse
    return 200, sse_block(rpc_id, {"result": result}), sse
