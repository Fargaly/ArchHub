"""Brain Workshop projection of the Universal application runtime.

server.py always tries wire_cell_room(mcp, store). This:
  1. registers the SAME brain.room_say/read/leaf_gate tools + /room page +
     tool-narration observer, all routed through the signed Universal runtime;
  2. shares ONE room handle between the tool path and the brain.context
     injection tail (module singleton).

The legacy Python room is retained only as read/migration evidence. The Brain
server never registers it as authority and ignores BRAIN_CELL_ROOM. When the
Universal Workshop is unavailable, public room tools fail closed. This module
does not seed-migrate history into a hidden local store; replay into
`app:workshop` is a separate, explicit migration step because Universal refs
must already exist as graph Cells.
"""
from __future__ import annotations

LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "control_plane_projection_until_universal_cell_policy"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False

import atexit
import os
import queue
import threading
import time
from typing import Any, Optional

from . import cell_room as CR

# one handle shared by the tool path and the injection path
_HANDLE: Optional[CR.RoomHandle] = None

# tool-call narration runs on ONE background FIFO worker so a tool call never
# waits on the Universal runtime's persist (see _narrate for the measurements)
_NARRATION_QUEUE: "queue.Queue" = queue.Queue(maxsize=1024)
_NARRATION_LOCK = threading.Lock()
_NARRATION_THREAD: Optional[threading.Thread] = None


def cell_room_enabled() -> bool:
    """Legacy active-work migration switch; not a Brain server authority switch."""
    return os.environ.get("BRAIN_CELL_ROOM", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def cell_room_is_wired() -> bool:
    return _HANDLE is not None


def wire_cell_room(
    mcp: Any,
    store: Any,  # noqa: ARG001
    db_path: Optional[str] = None,
    *,
    bridge: Any = None,
) -> CR.RoomHandle:
    """Build the runtime room adapter and register the Brain surface."""
    global _HANDLE
    _HANDLE = CR.load_room(db_path, bridge=bridge)
    CR.register_cell_room_tools(mcp, _HANDLE)
    _register_route(mcp)
    _register_observer(mcp)
    return _HANDLE


def register_unavailable_cell_room_tools(mcp: Any, error: str) -> None:
    """Expose the Workshop surface as unavailable without writing a side room."""

    @mcp.tool(
        name="brain.room_say",
        description=(
            "CELL-FIRST application Workshop unavailable. Refuses to write "
            "legacy meeting_room_v1 as authority."
        ),
    )
    def brain_room_say(
        frm: str,  # noqa: ARG001
        text: str,  # noqa: ARG001
        kind: str = "note",  # noqa: ARG001
        refs=None,  # noqa: ANN001,ARG001
        to=None,  # noqa: ANN001,ARG001
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "cell_first": True,
            "brain_written": False,
            "authority": "application-owned Universal Cell Workshop",
            "code": "cell_room_unavailable",
            "error": error,
        }

    @mcp.tool(
        name="brain.room_read",
        description="READ-ONLY unavailable Cell runtime Workshop projection.",
    )
    def brain_room_read(
        limit: int = 50,  # noqa: ARG001
        kind=None,  # noqa: ANN001,ARG001
        ref=None,  # noqa: ANN001,ARG001
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "schema": "cell_room/unavailable-v1",
            "events": [],
            "total": 0,
            "cell_first": True,
            "brain_written": False,
            "authority": "application-owned Universal Cell Workshop",
            "code": "cell_room_unavailable",
            "error": error,
        }

    @mcp.tool(
        name="brain.room_leaf_gate",
        description=(
            "CELL-FIRST Workshop gate unavailable. Governed claims fail closed "
            "until the Universal Cell Workshop is wired."
        ),
    )
    def brain_room_leaf_gate(leaf_id: str, phase: str) -> dict[str, Any]:
        return {
            "allowed": False,
            "phase": str(phase),
            "leaf_id": str(leaf_id),
            "missing": ["cell_room_unavailable"],
            "matching_entries": [],
            "cell_first": True,
            "brain_written": False,
            "authority": "application-owned Universal Cell Workshop",
            "code": "cell_room_unavailable",
            "error": error,
        }


def cell_room_injection_tail(limit: int = 12) -> str:
    """The brain.context room tail (parity with meeting_room.room_injection_block)."""
    if _HANDLE is None:
        return ""
    try:
        return CR.room_injection_block(
            _HANDLE,
            limit=limit,
            response_timeout_seconds=CR.PROMPT_PROJECTION_TIMEOUT_SECONDS,
        )
    except Exception:
        return ""


def cell_room_leaf_gate(leaf_id: str, phase: str) -> dict:
    """Evaluate the assignment gate through the runtime Workshop handle."""
    if _HANDLE is None:
        raise CR.UniversalRuntimeUnavailable("runtime Workshop is not wired")
    return CR.room_gate(
        _HANDLE,
        leaf_id,
        phase,
        response_timeout_seconds=CR.PROMPT_PROJECTION_TIMEOUT_SECONDS,
    )


def _say_now(kind: str, refs: list, text: str) -> None:
    try:
        CR.room_say(_HANDLE, frm="brain", kind=kind, refs=refs, text=text)
    except Exception:
        return


def _narration_worker() -> None:
    while True:
        item = _NARRATION_QUEUE.get()
        try:
            if item is None:  # shutdown sentinel
                return
            _say_now(*item)
        finally:
            _NARRATION_QUEUE.task_done()


def _enqueue_narration(kind: str, refs: list, text: str) -> None:
    """Hand one narration to the worker; fall back to an inline say if the
    queue is full, so an event is NEVER dropped (founder 2026-07-17:
    participation is NOT optional)."""
    global _NARRATION_THREAD
    with _NARRATION_LOCK:
        if _NARRATION_THREAD is None or not _NARRATION_THREAD.is_alive():
            _NARRATION_THREAD = threading.Thread(
                target=_narration_worker,
                name="brain-room-narrator",
                daemon=True,
            )
            _NARRATION_THREAD.start()
            atexit.register(_flush_narrations)
    try:
        _NARRATION_QUEUE.put_nowait((kind, refs, text))
    except queue.Full:
        _say_now(kind, refs, text)


def _flush_narrations(timeout_s: float = 10.0) -> None:
    """Drain pending narrations at shutdown — bounded, never raises."""
    deadline = time.monotonic() + timeout_s
    while not _NARRATION_QUEUE.empty() and time.monotonic() < deadline:
        time.sleep(0.05)


def _register_observer(mcp: Any) -> None:
    if _HANDLE is None or not hasattr(mcp, "set_tool_observer"):
        return

    def _narrate(name: str, args: Any, result: Any) -> None:
        # OFF THE CRITICAL PATH (measured 2026-07-27): this narration is one
        # synchronous AF_PIPE round-trip into the Universal runtime, and the
        # runtime persists the event into a ~289MB SQLite store. Cost: 3 brain
        # tool calls = 7.05s wall, of which the authority bridge burned 1.55s
        # CPU while the Brain daemon burned 0.00s — i.e. EVERY brain tool call
        # paid a ~2.4s tax waiting on another process. `ping` / `initialize` /
        # unknown-tool (which skip the observer) answered in 2-13ms. It also
        # pushed brain.health past the stdio singleton guard's probe deadline,
        # which is how this surfaced (see stdio_http_proxy.DEFAULT_HEALTH_
        # TIMEOUT_SEC). Narration is a projection, not authority, so it is now
        # queued to one FIFO worker: the event still lands, in order, and a
        # full queue falls back to the old inline say rather than dropping it.
        try:
            refs: list = []
            for obj in (args, result):
                if isinstance(obj, dict) and obj.get("leaf_id"):
                    refs.append(str(obj["leaf_id"]))
                if isinstance(obj, dict) and obj.get("work_root"):
                    refs.append(str(obj["work_root"]))
                if isinstance(obj, dict) and isinstance(obj.get("leaf"), dict) and obj["leaf"].get("leaf_id"):
                    refs.append(str(obj["leaf"]["leaf_id"]))
            kind = "court" if name == "brain.universal_work_court" else "op"
            _enqueue_narration(kind, sorted(set(refs)), f"{name} executed")
        except Exception:
            return

    mcp.set_tool_observer(_narrate)


def _register_route(mcp: Any) -> None:
    if _HANDLE is None or not hasattr(mcp, "custom_route"):
        return
    import html as _html

    @mcp.custom_route("/room", methods=["GET"])
    async def _room_page(request: Any) -> Any:  # noqa: ARG001
        from starlette.responses import HTMLResponse
        events = CR.room_read(_HANDLE, limit=80)["events"]
        items = "\n".join(
            "<li><b>{}</b> <span>{}</span><p>{}</p></li>".format(
                _html.escape(str(e.get("kind") or "")),
                _html.escape(str(e.get("from") or "")),
                _html.escape(str(e.get("text") or "")))
            for e in events)
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>Brain Room projection</title>"
            "<style>body{font:14px system-ui;background:#111;color:#eee;padding:24px}"
            "li{margin:0 0 12px;padding:12px;border:1px solid #333;border-radius:6px}"
            "p{margin:6px 0 0;color:#bbb}</style>"
            "<h1>Brain Workshop Room (runtime projection)</h1><ul>{}</ul>".format(items))


# ---- self-test (mock mcp; no real server, no live daemon touched) -------
def _selftest() -> dict:
    global _HANDLE
    captured: dict = {"tools": {}, "observer": None, "routes": []}

    class _FakeBridge:
        def __init__(self) -> None:
            self.entries: list[dict[str, Any]] = []

        def workshop_read(self) -> dict[str, Any]:
            return {"workshop": "app:workshop", "entries": list(self.entries)}

        def workshop_say(self, **body: Any) -> dict[str, Any]:
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
            required = {"claim": ("plan",), "done": ("test", "doc", "court")}
            present = {
                entry["kind"] for entry in self.entries
                if ref in entry["refs"]
            }
            missing = [
                kind for kind in required.get(phase, ())
                if kind not in present
            ]
            return {
                "allowed": not missing,
                "missing": missing,
                "matching_entries": [
                    entry["root"] for entry in self.entries
                    if ref in entry["refs"]
                ],
            }

    class _MockMCP:
        def tool(self, name=None, description=None):
            def deco(fn):
                captured["tools"][name] = fn
                return fn
            return deco
        def set_tool_observer(self, fn):
            captured["observer"] = fn
        def custom_route(self, path, methods=None):
            def deco(fn):
                captured["routes"].append(path)
                return fn
            return deco

    m = _MockMCP()
    handle = wire_cell_room(m, store=None, db_path=None, bridge=_FakeBridge())
    assert handle is _HANDLE and _HANDLE is not None
    assert set(captured["tools"]) == {"brain.room_say", "brain.room_read", "brain.room_leaf_gate"}, captured["tools"]
    assert captured["observer"] is not None, "observer not registered"
    assert "/room" in captured["routes"], "room route not registered"

    # tools route to the application runtime room
    say = captured["tools"]["brain.room_say"](frm="claude", text="wired live", kind="exec", to="codex")
    assert say["ok"] and say["event"]["requested_from"] == "claude" and say["event"]["kind"] == "tool"
    read = captured["tools"]["brain.room_read"](limit=10)
    assert read["total"] == 1 and read["events"][0]["text"] == "wired live"

    # injection tail shares the same handle
    tail = cell_room_injection_tail()
    assert "wired live" in tail and tail.startswith("<meeting_room>"), tail

    # observer narrates a graph work-court run into the node room
    captured["observer"](
        "brain.universal_work_court", {"work_root": "work:q"}, {})
    read2 = captured["tools"]["brain.room_read"](limit=10)
    assert read2["total"] == 2, read2["total"]
    narr = read2["events"][-1]
    assert narr["from"] == "app:identity:founder" and narr["kind"] == "court" and "work:q" in narr["refs"], narr

    _HANDLE = None  # reset module singleton after the test
    return {"cell_room_wiring": "GREEN", "tools": 3, "observer": True,
            "route": True, "injection_tail": True, "observer_narration": True,
            "authority": "application-runtime"}


if __name__ == "__main__":
    r = _selftest()
    print("CELL_ROOM_WIRING:", r)
    print("GREEN" if r["cell_room_wiring"] == "GREEN" else "RED")
