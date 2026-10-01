"""BABOOM's interrupt act for agents that can be asked to stop immediately.

The coordination host's interrupt_agent records a message the agent reads on
its next turn. A Claude Code session takes a Session Link peer frame with
priority "now" as a request for immediate interruption
(session_link/interrupt.mjs), so a named Claude Code session goes there.
Session Link reports that frame as sent and unconfirmed: nothing acknowledges
the receiver's abort, so the result is an interruption *request*, never
"interrupted". Codex Desktop exposes no interrupt to other apps: BABOOM says so
and sends nothing. Every other agent keeps the coordination request.

The coordination rows carry no Claude Code session id, so a Claude target names
its exact session id: "interrupt claude:<session id>: why". The answer must
name that same session, a message id and priority "now", with a status Session
Link actually reports; anything else is reported as unknown.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Optional

from .session_link_config import INSTALL_ROOT, SessionLinkConfigRefused, app_state_dir
from .universal_cell import InvalidCell

ASK_ENTRY = Path(__file__).resolve().parent / "session_link" / "ask.mjs"
DEFAULT_REASON = "the founder asked you to stop"
TIMEOUT_SECONDS = 20
RUNNER: Callable[..., subprocess.CompletedProcess] = subprocess.run
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# publicDeliveryReceipt's statuses: the frame was held or turned away, not acted on.
_NOT_DELIVERED = frozenset({"held", "refused", "rejected", "denied", "expired", "dropped"})
CODEX_REFUSAL = ("Codex agents can't be interrupted: Codex Desktop does not expose "
                 "interrupt to other apps. Nothing was sent.")
NAME_CLAUDE = ("Name the Claude Code session to interrupt by its session ID, e.g. "
               "\"interrupt claude:<session id>: why\" (Session Link lists the IDs). Nothing was sent.")
_UNMATCHED = ("Session Link's answer does not match this request (%s); the interrupt may or may not "
              "have been sent. Do not resend automatically.")


def interrupt_claude_session(session_id: str, reason: str, *, environment: Optional[Mapping[str, str]] = None,
                             runner: Optional[Callable[..., subprocess.CompletedProcess]] = None) -> dict:
    """One Session Link interrupt to one exact Claude Code session; its answer, checked."""
    env = dict(os.environ if environment is None else environment)
    node = env.get("SESSION_LINK_NODE") or env.get("CODEX_MCP_NODE_PATH") or str(INSTALL_ROOT / "runtime" / "node.exe")
    if not Path(node).is_absolute() or not Path(node).is_file():
        raise InvalidCell("Session Link's Node runtime is unavailable; nothing was sent.")
    if not env.get("SESSION_LINK_STATE_DIR"):
        try:
            env["SESSION_LINK_STATE_DIR"] = str(app_state_dir(env))
        except SessionLinkConfigRefused as exc:
            raise InvalidCell("Session Link state is unavailable (%s); nothing was sent." % exc) from exc
    try:
        result = (runner or RUNNER)(
            [node, str(ASK_ENTRY), "interrupt", "--app", "claude", "--session", session_id, "--reason", reason],
            env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidCell("Session Link did not answer in %d s; the interrupt may or may not have been sent. "
                          "Do not resend automatically." % TIMEOUT_SECONDS) from exc
    if result.returncode:
        lines = [line.strip() for line in str(result.stderr or "").splitlines() if line.strip()]
        raise InvalidCell("Session Link refused the interrupt: %s" % ((lines[-1] if lines else "no reason given")[:300]))
    try:
        sent = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise InvalidCell(_UNMATCHED % "no readable answer") from None
    if not isinstance(sent, dict):
        raise InvalidCell(_UNMATCHED % "no readable answer")
    if sent.get("target") != session_id:
        raise InvalidCell(_UNMATCHED % "it names another session")
    if not isinstance(sent.get("messageId"), str) or not _UUID.match(sent["messageId"]):
        raise InvalidCell(_UNMATCHED % "no message id")
    if sent.get("priority") != "now":
        raise InvalidCell(_UNMATCHED % "it was not sent as an immediate interruption")
    if sent.get("status") != "sent_unconfirmed" and sent.get("status") not in _NOT_DELIVERED:
        raise InvalidCell(_UNMATCHED % "unknown status")
    return sent


def route_interrupt(spec: Mapping[str, object], row: Optional[Mapping[str, object]] = None, *,
                    environment: Optional[Mapping[str, str]] = None,
                    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None) -> Optional[dict]:
    """Ask a Claude Code session to stop, refuse a Codex agent, or return None for the coordination path.

    Without ``row`` the spoken target is read as ``provider[:session id]``;
    with the resolved coordination row its provider decides (rows carry no
    Claude Code session id).
    """
    target = str(spec.get("target") or "").strip()
    head, _sep, selector = target.partition(":")
    provider = head.casefold()
    if row is not None:
        provider = str(row.get("provider") or row.get("runtime") or "").casefold()
        selector = ""
    if provider == "codex":
        raise InvalidCell(CODEX_REFUSAL)
    if provider != "claude":
        return None
    selector = selector.strip()
    if not _UUID.match(selector):
        raise InvalidCell(NAME_CLAUDE)
    reason = str(spec.get("reason") or "").strip() or DEFAULT_REASON
    sent = interrupt_claude_session(selector, reason, environment=environment, runner=runner)
    data = {"transport": "session-link", "interrupt": sent, "reason": reason, "confirmed": False}
    if sent["status"] == "sent_unconfirmed":
        return {
            "kind": "agent-interrupt-requested",
            "summary": ("Interruption requested for Claude Code session %s (Session Link message %s): "
                        "sent, not confirmed. The session decides under its own permissions."
                        % (sent["target"], sent["messageId"])),
            "data": data,
        }
    return {
        "kind": "agent-interrupt-not-delivered",
        "summary": ("Interruption request for Claude Code session %s was %s by the session; "
                    "it did not interrupt anything." % (sent["target"], sent["status"])),
        "data": data,
    }


__all__ = ["CODEX_REFUSAL", "NAME_CLAUDE", "RUNNER", "interrupt_claude_session", "route_interrupt"]
