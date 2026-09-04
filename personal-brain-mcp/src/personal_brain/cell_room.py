"""Brain Workshop room as a client of the application-owned Cell runtime.

This module keeps the public Brain room tool surface, but it does not own a
room database and does not import the Node Language internals. The authority is
the active Universal runtime route set:

- `GET /api/universal/workshop`
- `POST /api/universal/workshop`
- `POST /api/universal/workshop-gate`

If the runtime is unavailable, callers get a plain failure from
UniversalRuntimeUnavailable. There is no hidden local fallback authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .universal_runtime import (
    UniversalRuntimeBridge,
    UniversalRuntimeUnavailable,
)


ROOM_LIMIT = 400
PROMPT_PROJECTION_TIMEOUT_SECONDS = 3.0
KINDS = (
    "note", "plan", "test", "doc", "court", "tool", "directive",
    "decision", "finding",
)
_KIND_ALIASES = {
    "say": "note",
    "research": "finding",
    "coord": "plan",
    "exec": "tool",
    "blocker": "finding",
    "op": "tool",
}
_BROADCAST = {"", "all", "all-agents", "everyone", "room", "*"}


@dataclass
class RoomHandle:
    bridge: UniversalRuntimeBridge
    seed_failures: list[dict[str, Any]] = field(default_factory=list)


def normalize_author(frm: Optional[str]) -> str:
    """Preserve the caller label for display only.

    The Universal Workshop actor is the authenticated graph subject; the caller
    label is not used as authority until agent-session participants are admitted
    into `app:workshop` by graph policy.
    """
    return (str(frm or "system").strip() or "system").lower()


def normalize_kind(kind: Optional[str]) -> str:
    raw = (str(kind or "note").strip().lower() or "note")
    mapped = _KIND_ALIASES.get(raw, raw)
    return mapped if mapped in KINDS else "note"


def normalize_recipients(to: Optional[str]) -> tuple[str, ...]:
    raw = (str(to or "").strip().lower())
    if raw in _BROADCAST:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        label = part.strip()
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return tuple(out)


def _entry_to_event(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "room:%06d" % int(entry.get("sequence") or 0),
        "root": str(entry.get("root") or ""),
        "ts": str(entry.get("created_at") or ""),
        "from": str(entry.get("actor") or ""),
        "to": ",".join(str(item) for item in entry.get("recipients") or ()),
        "kind": str(entry.get("kind") or ""),
        "category_root": str(entry.get("category_root") or ""),
        "refs": [str(item) for item in entry.get("refs") or ()],
        "evidence": [str(item) for item in entry.get("evidence") or ()],
        "text": str(entry.get("text") or ""),
    }


def _idempotency_key(
    *,
    frm: str,
    kind: str,
    text: str,
    refs: tuple[str, ...],
    recipients: tuple[str, ...],
    created_at: str,
) -> str:
    payload = {
        "frm": frm,
        "kind": kind,
        "text": text,
        "refs": refs,
        "recipients": recipients,
        "created_at": created_at,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "brain-room:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def open_room(
    db_path: Optional[str] = None,  # noqa: ARG001
    *,
    bridge: UniversalRuntimeBridge | None = None,
) -> RoomHandle:
    return RoomHandle(bridge or UniversalRuntimeBridge())


def refresh_contexts(handle: RoomHandle) -> None:  # noqa: ARG001
    """Compatibility no-op.

    Runtime route credentials are owned by UniversalRuntimeBridge, not by this
    adapter.
    """


def room_say(
    handle: RoomHandle,
    *,
    frm: str,
    text: str,
    kind: str = "note",
    refs: Optional[list[str]] = None,
    to: Optional[str] = None,
    at: Optional[str] = None,
) -> dict[str, Any]:
    caller = normalize_author(frm)
    category = normalize_kind(kind)
    ref_list = tuple(str(root) for root in (refs or ()) if str(root).strip())
    recipients = normalize_recipients(to)
    created_at = str(at) if at else datetime.now(timezone.utc).isoformat()
    entry = handle.bridge.workshop_say(
        category=category,
        text=str(text or ""),
        refs=ref_list,
        evidence=(),
        recipients=(),
        reply_to=None,
        idempotency_key=_idempotency_key(
            frm=caller,
            kind=category,
            text=str(text or ""),
            refs=ref_list,
            recipients=recipients,
            created_at=created_at,
        ),
        created_at=created_at,
    )
    event = _entry_to_event(entry)
    event["requested_from"] = caller
    event["requested_to"] = ",".join(recipients)
    return event


def room_read(
    handle: RoomHandle,
    *,
    limit: int = 50,
    kind: Optional[str] = None,
    ref: Optional[str] = None,
    response_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if response_timeout_seconds is None:
        state = handle.bridge.workshop_read()
    else:
        try:
            state = handle.bridge.workshop_read(
                response_timeout_seconds=response_timeout_seconds
            )
        except TypeError:
            state = handle.bridge.workshop_read()
    events = [_entry_to_event(item) for item in state.get("entries") or ()]
    if kind:
        wanted = normalize_kind(kind)
        events = [item for item in events if item["kind"] == wanted]
    if ref:
        ref_text = str(ref)
        events = [item for item in events if ref_text in item["refs"]]
    bounded = max(1, min(int(limit or 50), ROOM_LIMIT))
    return {
        "ok": True,
        "schema": "cell_room/runtime-workshop-v1",
        "workshop": state.get("workshop"),
        "events": events[-bounded:],
        "total": len(events),
    }


def room_gate(
    handle: RoomHandle,
    leaf_id: str,
    phase: str,
    *,
    response_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if response_timeout_seconds is None:
        gate = handle.bridge.workshop_gate(ref=str(leaf_id), phase=str(phase))
    else:
        try:
            gate = handle.bridge.workshop_gate(
                ref=str(leaf_id),
                phase=str(phase),
                response_timeout_seconds=response_timeout_seconds,
            )
        except TypeError:
            gate = handle.bridge.workshop_gate(ref=str(leaf_id), phase=str(phase))
    return {
        "allowed": bool(gate.get("allowed")),
        "phase": str(phase),
        "leaf_id": str(leaf_id),
        "missing": list(gate.get("missing") or ()),
        "matching_entries": list(gate.get("matching_entries") or ()),
    }


def room_injection_block(
    handle: RoomHandle,
    *,
    limit: int = 12,
    response_timeout_seconds: float | None = None,
) -> str:
    events = room_read(
        handle,
        limit=limit,
        response_timeout_seconds=response_timeout_seconds,
    )["events"]
    lines = ["<meeting_room>"]
    if not events:
        lines.append("No workshop events yet.")
    for event in events:
        refs = ",".join(event.get("refs") or ())
        prefix = f"{event.get('kind')} from {event.get('from')}"
        if event.get("requested_from"):
            prefix += f" requested_by={event.get('requested_from')}"
        if refs:
            prefix += f" refs={refs}"
        lines.append(f"- {prefix}: {event.get('text')}")
    lines.append("</meeting_room>")
    return "\n".join(lines)


def export_events(handle: RoomHandle) -> list[dict[str, Any]]:
    return room_read(handle, limit=ROOM_LIMIT)["events"]


def replay_events(handle: RoomHandle, events: list[dict[str, Any]]) -> int:
    count = 0
    for event in events:
        try:
            room_say(
                handle,
                frm=str(event.get("from") or "system"),
                to=(str(event.get("to")) if event.get("to") else None),
                kind=str(event.get("kind") or "note"),
                text=str(event.get("text") or ""),
                refs=[str(root) for root in event.get("refs") or ()],
                at=str(event.get("ts") or ""),
            )
            count += 1
        except Exception as exc:  # pragma: no cover - migration evidence only.
            handle.seed_failures.append({
                "event": event,
                "error": type(exc).__name__,
                "detail": str(exc),
            })
    return count


def load_room(
    db_path: Optional[str] = None,
    seed_events: Optional[list[dict[str, Any]]] = None,
    *,
    bridge: UniversalRuntimeBridge | None = None,
) -> RoomHandle:
    handle = open_room(db_path, bridge=bridge)
    if seed_events:
        replay_events(handle, seed_events)
    return handle


def register_cell_room_tools(mcp: Any, handle: RoomHandle) -> None:
    @mcp.tool(
        name="brain.room_say",
        description=(
            "CELL-FIRST application Workshop: append a message/evidence node "
            "through the application-owned Universal Cell runtime."
        ),
    )
    def brain_room_say(
        frm: str,
        text: str,
        kind: str = "note",
        to: Optional[str] = None,
        refs: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "cell_first": True,
            "authority": "application-owned Universal Cell Workshop",
            "event": room_say(
                handle, frm=frm, to=to, kind=kind, refs=refs, text=text
            ),
        }

    @mcp.tool(
        name="brain.room_read",
        description=(
            "READ-ONLY Cell runtime projection of recent application Workshop "
            "events."
        ),
    )
    def brain_room_read(
        limit: int = 50,
        kind: Optional[str] = None,
        ref: Optional[str] = None,
    ) -> dict[str, Any]:
        return room_read(handle, limit=limit, kind=kind, ref=ref)

    @mcp.tool(
        name="brain.room_leaf_gate",
        description=(
            "CELL-FIRST Workshop gate: audit a leaf through the "
            "application-owned Universal Cell runtime."
        ),
    )
    def brain_room_leaf_gate(leaf_id: str, phase: str) -> dict[str, Any]:
        result = room_gate(handle, leaf_id, phase)
        result["cell_first"] = True
        result["authority"] = "application-owned Universal Cell Workshop"
        return result


def _selftest() -> dict[str, Any]:
    class _FakeBridge:
        def __init__(self) -> None:
            self.entries: list[dict[str, Any]] = []

        def workshop_read(self) -> dict[str, Any]:
            return {"workshop": "app:workshop", "entries": list(self.entries)}

        def workshop_say(self, **body: Any) -> dict[str, Any]:
            for entry in self.entries:
                if entry["idempotency_key"] == body["idempotency_key"]:
                    return entry
            entry = {
                "root": "app:workshop:entry:%06d" % (len(self.entries) + 1),
                "sequence": len(self.entries) + 1,
                "actor": "app:identity:founder",
                "kind": body["category"],
                "category_root": "app:workshop:category:" + body["category"],
                "recipients": list(body["recipients"]),
                "refs": list(body["refs"]),
                "evidence": list(body["evidence"]),
                "reply_to": body["reply_to"],
                "text": body["text"],
                "created_at": body["created_at"],
                "idempotency_key": body["idempotency_key"],
            }
            self.entries.append(entry)
            return entry

        def workshop_gate(self, *, ref: str, phase: str) -> dict[str, Any]:
            required = {
                "claim": ("plan",),
                "done": ("test", "doc", "court"),
            }.get(phase, ())
            present = {
                entry["kind"] for entry in self.entries
                if ref in entry.get("refs", ())
            }
            missing = [kind for kind in required if kind not in present]
            return {
                "allowed": not missing,
                "missing": missing,
                "matching_entries": [
                    entry["root"] for entry in self.entries
                    if ref in entry.get("refs", ())
                ],
            }

    handle = open_room(bridge=_FakeBridge())  # type: ignore[arg-type]
    event = room_say(
        handle,
        frm="codex",
        kind="plan",
        refs=["app:root"],
        text="runtime route wired",
        at="2026-07-18T10:30:00+00:00",
    )
    assert event["kind"] == "plan"
    assert event["requested_from"] == "codex"
    assert room_gate(handle, "app:root", "claim")["allowed"] is True
    assert room_read(handle, ref="app:root")["total"] == 1
    assert "runtime route wired" in room_injection_block(handle)
    return {"cell_room": "GREEN", "authority": "application-runtime"}


__all__ = [
    "KINDS",
    "ROOM_LIMIT",
    "RoomHandle",
    "UniversalRuntimeUnavailable",
    "export_events",
    "load_room",
    "normalize_author",
    "normalize_kind",
    "normalize_recipients",
    "open_room",
    "refresh_contexts",
    "register_cell_room_tools",
    "replay_events",
    "room_gate",
    "room_injection_block",
    "room_read",
    "room_say",
]


if __name__ == "__main__":
    result = _selftest()
    print("CELL_ROOM:", result)
    print("GREEN" if result["cell_room"] == "GREEN" else "RED")
