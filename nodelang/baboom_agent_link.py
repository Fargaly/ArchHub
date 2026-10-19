"""BABOOM posts and reads the same Workshop mailbox as every external agent."""
from __future__ import annotations
from typing import Mapping, Optional, Sequence


def _call(method, arguments, mailbox=None):
    if mailbox is not None:
        return mailbox(method, arguments)
    from .native_agent_mcp import _mailbox_call
    return _mailbox_call(method, arguments, {})


def list_agents(*, mailbox=None) -> list[dict]:
    """Latest public activity, bounded by the server; no claim of live presence."""
    page = _call("read", {"since": 0}, mailbox)
    if "declarations" in page:
        rows = list(page["declarations"])
        while page.get("declarations_more"):
            page = _call("read", {"since":page["next_since"],
                "declarations_after":page["declarations_after"]}, mailbox)
            rows.extend(page["declarations"])
        return [{**row, "session_root":row["agent"], "provider":row["agent"],
                 "sender_key":row["session"]} for row in rows]
    return [{"session_root": row["label"], "provider": row["label"],
             "sender_key": row["sender_key"], "runtime": row["runtime"],
             "status": "observed"} for row in page["peers"]]


def resolve_target(name: str, agents: Optional[Sequence[Mapping[str, object]]] = None) -> Optional[dict]:
    target = str(name or "").strip()
    if not target:
        return None
    for row in agents or ():
        if str(row.get("session_root", "")).casefold() == target.casefold():
            return dict(row)
    # A mailbox address is a name, not enrollment or a claim of live presence.
    return {"session_root": target, "provider": target, "runtime": "mcp", "status": "unknown"}


def send_message(target_root: str, message: str, *, mailbox=None) -> dict:
    row = _call("send", {"to": target_root, "text": message}, mailbox)
    return {**row, "message": {"root_id": row["message_id"], "sequence": row["sequence"]}}


def declare(task: str, paths: list[str], status: str, request_id: str, *, mailbox=None) -> dict:
    """BABOOM uses precisely the same declaration tool and graph nodes."""
    return _call("declare", {"task":task, "paths":paths, "status":status, "request_id":request_id}, mailbox)


def interrupt_agent(target_root: str, reason: str, *, mailbox=None) -> dict:
    """Post a stop request; immediate native interruption has a separate adapter."""
    return send_message(target_root, "Stop requested: " + reason, mailbox=mailbox)
