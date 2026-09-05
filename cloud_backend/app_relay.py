"""Relay a founder instruction from the cockpit to the founder's RUNNING application.

The cockpit is the map and the map is the graph, and the graph lives in the
founder's application on his machine. A question about the graph, the agents,
the hosts, the brain or BABOOM is answered by THAT application, never invented
by the cloud. The cloud only queues the instruction as an agent task (kind
``app`` to ask, ``app-execute`` to act) and waits for the application's relay
thread to claim it and post the answer.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import db

APP_KINDS = ("app", "app-execute")


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
