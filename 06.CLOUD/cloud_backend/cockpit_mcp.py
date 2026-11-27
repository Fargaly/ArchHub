"""The Cockpit's tools over MCP, for the founder's agents and automations.

This is not a second Cockpit. The tools are cockpit_agent.TOOLS themselves (the registry the Cockpit's command box
already drives): this module only lists them as MCP tools, runs the read ones, and turns a write into a held request.
A tool added to that registry appears here, and in every agent that is connected to /mcp, with no change in this file.

Who: only the founder's account (brain_mcp.answer hides these tools from, and refuses them to, every other account).
Reads: run directly. Writes (plan, credits, profile, sessions, flags): the call returns the preview and an approval
id; nothing changes until the founder approves it in the Cockpit Inbox, which then runs the existing executor
(cockpit_agent.confirm_pending) once. Refunds, erasure and impersonation have no tool at all (cockpit_agent.WITHHELD_ACTIONS).
Every call, read, preview or approval, lands in the founder audit log (db.log_founder_action).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import cockpit_agent
import db

log = logging.getLogger(__name__)

PREFIX = "cockpit_"
STATUS_TOOL = PREFIX + "approval_status"
_HELD_NOTE = ("Nothing has changed. The founder approves or rejects this in the Cockpit Inbox; "
              "ask cockpit_approval_status with the approval_id to see the outcome.")


def _schema(spec: dict) -> dict:
    params = spec.get("params") or {"type": "object", "properties": {}}
    return {"type": "object", **{k: v for k, v in params.items() if k != "type"}}


def tools() -> list[dict]:
    """The MCP listing, built from the registry each time so it can never drift from it."""
    out = []
    for name, spec in cockpit_agent.TOOLS.items():
        if spec.get("kind") not in ("read", "write"):
            continue
        desc = spec["desc"]
        if spec["kind"] == "write":
            desc += " Returns the preview and an approval_id; it runs only after the founder approves it in the Cockpit."
        if name == "app_command":
            schema = _schema(spec)
            schema["properties"] = {k: v for k, v in schema["properties"].items() if k != "execute"}
            desc += " From here it only asks; it never executes."
        else:
            schema = _schema(spec)
        # readOnlyHint lets a client run a read without its own prompt; a write call only holds a request, so it is not one
        out.append({"name": PREFIX + name, "description": desc, "inputSchema": schema,
                    "annotations": {"readOnlyHint": spec["kind"] == "read"}})
    out.append({"name": STATUS_TOOL,
                "description": "Whether a held Cockpit write was approved, rejected or is still waiting, and its effect once it ran.",
                "inputSchema": {"type": "object", "properties": {"approval_id": {"type": "string"}},
                                "required": ["approval_id"]},
                "annotations": {"readOnlyHint": True}})
    return out


def names() -> frozenset:
    return frozenset(t["name"] for t in tools())


def _text(payload: object, *, error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}]}
    if error:
        result["isError"] = True
    return result


def _audit(actor: str, tool: str, target: Optional[str], payload: dict, ok: bool) -> None:
    try:
        db.log_founder_action(actor=actor, command="mcp:" + tool, action=tool, target=target,
                              result=json.dumps(payload, default=str)[:2000], ok=ok)
    except Exception:  # noqa: BLE001 - an audit failure must not break the call, but it is never silent
        log.warning("cockpit_mcp: audit row for %s was not written", tool, exc_info=True)


def _status(approval: Optional[dict]) -> dict:
    if approval is None:
        return {"state": "unknown", "error": "no_such_approval"}
    out = {"approval_id": approval["id"], "state": approval["state"], "tool": approval["tool"],
           "summary": (approval.get("preview") or {}).get("summary")}
    if approval.get("result"):
        try:
            out["result"] = json.loads(approval["result"])
        except ValueError:
            out["result"] = approval["result"]
    return out


def call(user: dict, name: str, arguments: dict) -> dict:
    """One MCP tool call by the founder's account. KeyError for a name that is not ours."""
    actor = (user.get("email") or "").strip().lower()
    if name == STATUS_TOOL:
        payload = _status(db.get_agent_approval(str(arguments.get("approval_id") or "")))
        _audit(actor, name, payload.get("approval_id"), payload, payload.get("state") != "unknown")
        return _text(payload)
    if not name.startswith(PREFIX) or name not in names():
        raise KeyError(name)
    tool = name[len(PREFIX):]
    spec = cockpit_agent.TOOLS[tool]
    args = dict(arguments or {})

    if spec["kind"] == "read":
        if tool == "app_command":
            args["execute"] = False
        try:
            payload = spec["run"](args)
        except Exception as exc:  # noqa: BLE001 - the detail goes to the server log, the agent gets the class only
            cockpit_agent._record_read_error(tool, exc)
            payload = {"error": "read_failed", "message": "The read could not be completed."}
            _audit(actor, name, None, payload, False)
            return _text(payload, error=True)
        _audit(actor, name, None, {"ok": "error" not in (payload or {})}, True)
        return _text(payload)

    preview = spec["preview"](args)
    if not isinstance(preview, dict) or "error" in preview:
        _audit(actor, name, None, preview if isinstance(preview, dict) else {}, False)
        return _text(preview, error=True)
    approval_id = db.create_agent_approval(asked_by=actor, tool=tool, args=args, preview=preview)
    payload = {"state": "pending", "approval_id": approval_id, "preview": preview, "message": _HELD_NOTE}
    _audit(actor, name, cockpit_agent._target_of(preview), {"preview": preview.get("summary"), "approval_id": approval_id}, True)
    return _text(payload)


def decide(*, approval_id: str, approve: bool, actor: str) -> dict:
    """The founder's decision from the Cockpit. Approve runs the one existing executor, once; reject ends it."""
    row = db.get_agent_approval(approval_id)
    if row is None or row["state"] != "pending":
        return {"ok": False, "error": "not_pending", "message": "That request was already decided or has expired."}
    if not approve:
        if not db.decide_agent_approval(approval_id, "rejected"):
            return {"ok": False, "error": "not_pending", "message": "That request was already decided or has expired."}
        out = {"ok": True, "state": "rejected", "message": "Rejected. Nothing was changed."}
        _audit(actor, "cockpit_approval", row["preview"].get("summary"), {"approval_id": approval_id, "state": "rejected"}, True)
        return out
    # claim first so a double click or a second tab cannot run it twice, then run the same executor the command box uses
    if not db.decide_agent_approval(approval_id, "approved"):
        return {"ok": False, "error": "not_pending", "message": "That request was already decided or has expired."}
    try:
        result = cockpit_agent.confirm_pending(actor=actor, tool=row["tool"], args=row["args"],
                                               command="approved agent request " + approval_id)
    except Exception as exc:  # noqa: BLE001 - the state must never stay "approved" with nothing recorded
        cockpit_agent._record_write_error(row["tool"], exc)
        result = {"ok": False, "action": row["tool"], "error": type(exc).__name__,
                  "message": "The change could not be completed."}
        _audit(actor, "cockpit_approval", row["preview"].get("summary"), {"approval_id": approval_id, **result}, False)
    with db.connect() as con:
        con.execute("UPDATE founder_agent_approvals SET result = ? WHERE id = ?", (json.dumps(result, default=str)[:2000], approval_id))
    return {"ok": bool(result.get("ok")), "state": "approved", "message": result.get("message") or "Done.", "result": result}
