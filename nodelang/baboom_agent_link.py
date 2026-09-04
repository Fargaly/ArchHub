"""BABOOM's link to the agents on this machine.

Every agent (Codex, Claude, Gemini, OpenCode, Antigravity) registers with the
clean coordination host (:8474) and talks through it. BABOOM is one more
signed identity on that host, so the founder can list who is online, tell an
agent something, or interrupt it -- from the companion or from the cockpit.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Mapping, Optional, Sequence

VENDOR = "archhub"
MODEL = "baboom"
_client = None


def _state_dir() -> Path:
    held = os.environ.get("ARCHHUB_STATE_DIR")
    if held:
        return Path(held)
    return Path(os.environ.get("LOCALAPPDATA") or ".") / "ArchHub"


def session_id(state_dir: Optional[Path] = None) -> str:
    """One stable coordination identity per install, minted on first use."""
    marker = Path(state_dir or _state_dir()) / "baboom-coordination-session"
    try:
        if marker.is_file():
            held = marker.read_text(encoding="utf-8").strip()
            if held:
                return held
        marker.parent.mkdir(parents=True, exist_ok=True)
        fresh = uuid.uuid4().hex
        marker.write_text(fresh, encoding="utf-8")
        return fresh
    except OSError:
        return uuid.uuid4().hex


def client():
    """The signed coordination client, registered once per process."""
    global _client
    if _client is None:
        from .clean_coordination_host import CoordinationIdentity
        from .clean_coordination_mcp import DEFAULT_ENDPOINT, LocalCoordinationClient

        endpoint = os.environ.get("ARCHHUB_COORDINATION_ENDPOINT") or DEFAULT_ENDPOINT
        identity = CoordinationIdentity(VENDOR, session_id(), MODEL)
        made = LocalCoordinationClient(identity, endpoint=endpoint)
        made.call("register_session")
        _client = made
    return _client


def reset() -> None:
    global _client
    _client = None


def list_agents() -> list[dict]:
    rows = client().call("list_agents").get("agents") or []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def resolve_target(name: str, agents: Optional[Sequence[Mapping[str, object]]] = None) -> Optional[dict]:
    """'codex' -> the newest online Codex session; a full session root matches exactly."""
    want = str(name or "").strip().casefold()
    if not want:
        return None
    rows = list(agents if agents is not None else list_agents())
    for row in rows:
        if str(row.get("session_root", "")).casefold() == want:
            return dict(row)

    def matches(row: Mapping[str, object]) -> bool:
        return any(
            want in str(row.get(field, "")).casefold()
            for field in ("provider", "runtime", "session_root", "model")
        )

    found = [row for row in rows if matches(row)]
    found.sort(
        key=lambda row: (str(row.get("status")) == "online", int(row.get("revision") or 0)),
        reverse=True,
    )
    return dict(found[0]) if found else None


def send_message(target_root: str, message: str) -> dict:
    return client().call("send_message", {
        "target": target_root, "message": message,
        "idempotency_key": str(uuid.uuid4()),
    })


def followup_task(target_root: str, message: str) -> dict:
    return client().call("followup_task", {
        "target": target_root, "message": message,
        "idempotency_key": str(uuid.uuid4()),
    })


def interrupt_agent(target_root: str, reason: str) -> dict:
    return client().call("interrupt_agent", {
        "target": target_root, "message": reason,
        "idempotency_key": str(uuid.uuid4()),
    })


__all__ = [
    "client", "followup_task", "interrupt_agent", "list_agents", "reset",
    "resolve_target", "send_message", "session_id",
]
