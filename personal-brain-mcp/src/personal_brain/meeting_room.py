"""Legacy Brain meeting-room projection.

The room is the shared workshop record agents must write into before claiming
or completing active work. It is intentionally persisted in brain_meta as one
JSON document: no new table, no external service, and no hidden side channel.
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import html
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .storage import BrainStore


ROOM_META_KEY = "meeting_room_v1"
ROOM_LIMIT = 400
INJECTION_LIMIT = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_doc() -> dict[str, Any]:
    return {"schema": "meeting_room/v1", "events": []}


def _load_doc(store: "BrainStore") -> dict[str, Any]:
    raw = store.get_meta(ROOM_META_KEY)
    if not raw:
        return _empty_doc()
    try:
        doc = json.loads(raw)
    except Exception:
        return _empty_doc()
    if not isinstance(doc, dict):
        return _empty_doc()
    events = doc.get("events")
    if not isinstance(events, list):
        doc["events"] = []
    doc.setdefault("schema", "meeting_room/v1")
    return doc


def _append_event(store: "BrainStore", event: dict[str, Any]) -> dict[str, Any]:
    box: dict[str, Any] = {}

    def _fn(old_raw: Optional[str]):
        try:
            doc = json.loads(old_raw) if old_raw else _empty_doc()
        except Exception:
            doc = _empty_doc()
        if not isinstance(doc, dict):
            doc = _empty_doc()
        events = doc.get("events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        doc["events"] = events[-ROOM_LIMIT:]
        doc["schema"] = "meeting_room/v1"
        box["event"] = event
        return json.dumps(doc, default=str), event

    return store.update_meta(ROOM_META_KEY, _fn) or box.get("event") or event


def room_say(
    store: "BrainStore",
    *,
    frm: str,
    text: str,
    kind: str = "note",
    refs: Optional[list[str]] = None,
    to: Optional[str] = None,
) -> dict[str, Any]:
    """Append one workshop event and return it."""
    events = _load_doc(store).get("events") or []
    event = {
        "id": f"room:{len(events) + 1:06d}",
        "ts": _now(),
        "from": str(frm or "unknown"),
        "to": str(to or ""),
        "kind": str(kind or "note"),
        "refs": [str(ref) for ref in (refs or []) if str(ref).strip()],
        "text": str(text or ""),
    }
    return _append_event(store, event)


def room_read(
    store: "BrainStore",
    *,
    limit: int = 50,
    kind: Optional[str] = None,
    ref: Optional[str] = None,
) -> dict[str, Any]:
    doc = _load_doc(store)
    events = list(doc.get("events") or [])
    if kind:
        events = [e for e in events if e.get("kind") == kind]
    if ref:
        events = [e for e in events if str(ref) in (e.get("refs") or [])]
    limit = max(1, min(int(limit or 50), ROOM_LIMIT))
    return {"ok": True, "schema": doc.get("schema"), "events": events[-limit:],
            "total": len(events)}


def room_leaf_gate(store: "BrainStore", leaf_id: str, phase: str) -> dict[str, Any]:
    """Return whether the workshop has the required evidence for a leaf phase."""
    ref = str(leaf_id or "")
    events = room_read(store, limit=ROOM_LIMIT, ref=ref)["events"]
    kinds = {str(e.get("kind") or "") for e in events}
    required = {
        "claim": {"plan"},
        "done": {"test", "doc", "court"},
    }.get(str(phase or ""), set())
    missing = sorted(required - kinds)
    return {
        "allowed": not missing,
        "phase": phase,
        "leaf_id": ref,
        "required": sorted(required),
        "present": sorted(kinds),
        "missing": missing,
    }


def room_injection_block(store: "BrainStore", *, limit: int = INJECTION_LIMIT) -> str:
    events = room_read(store, limit=limit)["events"]
    lines = ["<meeting_room>"]
    if not events:
        lines.append("No workshop events yet.")
    for event in events:
        refs = ",".join(event.get("refs") or [])
        prefix = f"{event.get('kind')} from {event.get('from')}"
        if event.get("to"):
            prefix += f" to {event.get('to')}"
        if refs:
            prefix += f" refs={refs}"
        lines.append(f"- {prefix}: {event.get('text')}")
    lines.append("</meeting_room>")
    return "\n".join(lines)


def narrate_tool_call(
    store: "BrainStore",
    name: str,
    args: Any,
    result: Any,
) -> None:
    """Best-effort narration of important tool activity into the room."""
    try:
        refs: list[str] = []
        for obj in (args, result):
            if isinstance(obj, dict) and obj.get("leaf_id"):
                refs.append(str(obj.get("leaf_id")))
            if isinstance(obj, dict) and obj.get("work_root"):
                refs.append(str(obj.get("work_root")))
            if isinstance(obj, dict) and isinstance(obj.get("leaf"), dict):
                leaf_id = obj["leaf"].get("leaf_id")
                if leaf_id:
                    refs.append(str(leaf_id))
        kind = "court" if name == "brain.universal_work_court" else "tool"
        room_say(
            store,
            frm="brain",
            kind=kind,
            refs=sorted(set(refs)),
            text=f"{name} executed",
        )
    except Exception:
        return


def register_room_tools(mcp: Any, store: "BrainStore") -> None:
    @mcp.tool(
        name="brain.room_say",
        description=(
            "MIGRATION-ONLY legacy Brain workshop projection. Prefer the "
            "application-owned Universal Cell Workshop route wired by "
            "cell_room_wiring."
        ),
    )
    def brain_room_say(
        frm: str,
        text: str,
        kind: str = "note",
        refs: Optional[list[str]] = None,
        to: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "migration_only": True,
            "deprecated": True,
            "authority_status": "legacy_projection_not_cell_authority",
            "cell_first_alternative": "brain.room_say with Universal Cell Workshop wired",
            "event": room_say(
                store, frm=frm, to=to, kind=kind, refs=refs, text=text),
        }

    @mcp.tool(
        name="brain.room_read",
        description="READ-ONLY migration projection of legacy Brain workshop events.",
    )
    def brain_room_read(
        limit: int = 50,
        kind: Optional[str] = None,
        ref: Optional[str] = None,
    ) -> dict[str, Any]:
        result = room_read(store, limit=limit, kind=kind, ref=ref)
        result["migration_only"] = True
        result["authority_status"] = "legacy_projection_not_cell_authority"
        return result

    @mcp.tool(
        name="brain.room_leaf_gate",
        description=(
            "MIGRATION-ONLY legacy workshop gate. Prefer the Universal Cell "
            "Workshop gate when runtime wiring is available."
        ),
    )
    def brain_room_leaf_gate(leaf_id: str, phase: str) -> dict[str, Any]:
        result = room_leaf_gate(store, leaf_id, phase)
        result["migration_only"] = True
        result["authority_status"] = "legacy_projection_not_cell_authority"
        return result


def register_room_routes(mcp: Any, store: "BrainStore") -> None:
    @mcp.custom_route("/room", methods=["GET"])
    async def room_page(request: Any) -> Any:  # noqa: ARG001
        from starlette.responses import HTMLResponse

        events = room_read(store, limit=80)["events"]
        items = "\n".join(
            "<li><b>{}</b> <span>{}</span><p>{}</p></li>".format(
                html.escape(str(event.get("kind") or "")),
                html.escape(str(event.get("from") or "")),
                html.escape(str(event.get("text") or "")),
            )
            for event in events
        )
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>Brain Room</title>"
            "<style>body{font:14px system-ui;background:#111;color:#eee;padding:24px}"
            "li{margin:0 0 12px;padding:12px;border:1px solid #333;border-radius:6px}"
            "p{margin:6px 0 0;color:#bbb}</style>"
            "<h1>Brain Workshop Room</h1><ul>{}</ul>".format(items)
        )
