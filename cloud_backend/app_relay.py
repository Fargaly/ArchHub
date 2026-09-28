"""Relay a founder instruction from the cockpit to the founder's RUNNING application.

The cockpit is the map and the map is the graph, and the graph lives in the
founder's application on his machine. A question about the graph, the agents,
the hosts, the brain or BABOOM is answered by THAT application, never invented
by the cloud. The cloud only queues the instruction as an agent task (kind
``app`` to ask, ``app-execute`` to act, ``host-read`` for one read of a host
tool) and waits for the application's relay thread to claim it and post the
answer.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import db

HOST_READ = "host-read"
APP_KINDS = ("app", "app-execute", HOST_READ)


def default_wait_seconds() -> float:
    """How long the cockpit waits for the app before answering 'not yet'."""
    try:
        return max(0.0, float(os.environ.get("COCKPIT_APP_RELAY_WAIT_S", "18")))
    except ValueError:
        return 18.0


def enqueue(text: str, *, actor: str, execute: bool = False) -> dict:
    return db.enqueue_agent_task(
        directive=text, created_by=actor,
        kind="app-execute" if execute else "app")


def wait_for(task_id: str, *, wait_s: Optional[float] = None,
             poll_s: float = 0.4) -> Optional[dict]:
    """Poll the task row until the app finished it or the wait runs out."""
    deadline = time.monotonic() + (
        default_wait_seconds() if wait_s is None else float(wait_s))
    while True:
        row = db.get_agent_task(task_id)
        if row is None:
            return None
        if row.get("status") in ("done", "failed"):
            return row
        if time.monotonic() >= deadline:
            return row
        time.sleep(poll_s)


def relay(text: str, *, actor: str, execute: bool = False,
          wait_s: Optional[float] = None) -> dict:
    """Queue `text` for the founder's app and return what it answered."""
    task = enqueue(text, actor=actor, execute=execute)
    row = wait_for(task["id"], wait_s=wait_s) or task
    status = str(row.get("status") or "queued")
    result = str(row.get("result") or "")
    base = {"action": "app", "task_id": task["id"], "status": status,
            "execute": bool(execute)}
    if status == "done":
        return {**base, "ok": True,
                "message": result or "Your app answered with no text."}
    if status == "failed":
        return {**base, "ok": False,
                "message": "Your app refused: " + (result or "no reason given")}
    return {**base, "ok": True, "pending_app": True,
            "message": ("Sent to your ArchHub app (%s); it has not answered "
                        "yet. Is ArchHub open and signed in on your machine? "
                        "The answer lands under Agent tasks when it does."
                        % task["id"])}


class DeviceOffline(RuntimeError):
    """No running, signed-in ArchHub app took the read in time."""


def host_read(tool: str, arguments: dict, *, actor: str,
              wait_s: Optional[float] = None) -> object:
    """One read of the founder's desktop, answered by his running application.

    The cloud carries only {tool, args}; the application runs its own local
    read function (nodelang/cloud_relay.py host_read, an allowlist) and posts
    the JSON back. Nothing is invented here: an application that never claims
    the read is reported offline, and the unclaimed row is closed so a device
    that comes back later never runs a read its caller already gave up on.
    """
    directive = json.dumps({"tool": str(tool), "args": dict(arguments or {})},
                           sort_keys=True, separators=(",", ":"))
    task = db.enqueue_agent_task(directive=directive, created_by=actor, kind=HOST_READ)
    row = wait_for(task["id"], wait_s=wait_s) or task
    status = str(row.get("status") or "queued")
    result = str(row.get("result") or "")
    if status == "done":
        try:
            return json.loads(result)
        except ValueError:
            raise RuntimeError("your ArchHub app answered with unreadable data") from None
    if status == "failed":
        raise RuntimeError("your ArchHub app refused: " + (result or "no reason given"))
    if db.expire_agent_task(task["id"], "device_offline: no running ArchHub app claimed this read"):
        raise DeviceOffline("device_offline: ArchHub is not open and signed in on your "
                            "desktop, so nothing was read")
    raise TimeoutError("your ArchHub app took this read but has not answered yet")
