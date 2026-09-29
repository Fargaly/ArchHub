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
        return 200, sse_block(rpc_id, {"result": {
            "tools": (TOOLS + HOST_TOOLS) if founder else TOOLS}}), sse
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
