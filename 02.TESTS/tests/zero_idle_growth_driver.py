"""Driver for tests/test_zero_idle_growth.py: one phase per process, the app's own launcher.

Boots what the installed app runs (nograph_launcher.run -> NoGraphServer) from the source under
test, headless (ARCHHUB_TEST_NO_OPEN), inside the court's isolated profile. Nothing here touches an
installed application or any user state; every path is under the court's tmp dir.

  python zero_idle_growth_driver.py idle <source> <state-dir> <result.json>
  python zero_idle_growth_driver.py restart <source> <state-dir> <result.json>
  python zero_idle_growth_driver.py undo <source> <state-dir> <result.json>
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace


MODE, SOURCE, STATE = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
RESULT = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else None
sys.path.insert(0, str(SOURCE))

INTERVALS = 10
INTERVAL_SECONDS = 4.0      # past the 10 s local probe cache inside the idle window
SETTLE_SECONDS = 3.0


def watched():
    """The app's data dir and every profile folder it may write; the profile's TEMP is not data."""
    return [STATE] + [Path(os.environ[name]) for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE")]


def snapshot():
    files = {}
    for root in watched():
        for path in root.rglob("*"):
            # PowerShell rewrites its own startup cache in place whenever a host probe starts it.
            if path.is_file() and "PowerShell" not in path.parts:
                stat = path.stat()
                files[str(path)] = [stat.st_size, stat.st_mtime_ns]
    return files


def boot():
    """The installed app's boot path, headless. BABOOM stays off: the court has no model provider."""
    os.environ["ARCHHUB_TEST_NO_OPEN"] = "1"
    (STATE / "settings").mkdir(parents=True, exist_ok=True)
    choice = STATE / "settings" / "baboom.json"
    if not choice.exists():
        choice.write_text('{"startup": "off"}', encoding="utf-8")
    from nodelang import nograph_launcher, nograph_server
    threading.Thread(target=nograph_launcher.run, args=(str(STATE),), name="court-app", daemon=True).start()
    deadline = time.monotonic() + 120
    while nograph_server._SERVER is None or nograph_server._SERVER.thread is None:
        if time.monotonic() > deadline:
            raise SystemExit("the app did not start within 120 s")
        time.sleep(0.05)
    time.sleep(SETTLE_SECONDS)
    return nograph_server._SERVER


def route(server, name, body=None, query=None):
    from nodelang import nograph_server
    return getattr(nograph_server, name)(server, SimpleNamespace(method="POST" if body else "GET", path="",
                                                                   query=query or {}, body=body, handler=None))


def workflow():
    from nodelang.session_files import catalogue, new_document
    items = {row["id"]: row for row in catalogue()}
    doc = new_document("Zero idle court")
    for key, item, x in (("list", "n_list", 0), ("slice", "s_slice", 300), ("count", "s_count", 600)):
        doc["nodes"].append({"id": key, "item": item, "type": items[item]["engine"], "title": items[item]["title"],
                             "params": copy.deepcopy(items[item]["params"]), "position": {"x": x, "y": 0}})
    doc["nodes"][0]["params"]["value"] = "[10, 20, 30, 40, 50]"
    doc["nodes"][1]["params"]["count"] = "3"
    doc["wires"] = [{"id": "a", "from": {"node": "list", "socket": "value"}, "to": {"node": "slice", "socket": "items"}},
                    {"id": "b", "from": {"node": "slice", "socket": "items_out"}, "to": {"node": "count", "socket": "items"}}]
    return doc


def body_of(document):
    """What the user authored: solved node results are derived output (canvas_documents._stamp ignores them too)."""
    return {key: ([{k: v for k, v in node.items() if k != "result"} for node in value] if key == "nodes" else value)
            for key, value in document.items() if key != "properties"}


def reads(server, path):
    """What the founder's window and an agent read while nobody acts."""
    route(server, "r_session_files", {"action": "catalogue"})
    route(server, "r_session_files", {"action": "head", "path": path})   # the window's poll for agent edits
    route(server, "r_session_files", {"action": "read", "path": path})
    route(server, "r_canvas")
    route(server, "r_canvas_op", {"op": "project_files", "args": []})


def idle():
    server = boot()
    # User actions before the baseline: the window saves a document in place and opens it.
    saved = route(server, "r_session_files", {"action": "autosave", "document": workflow(), "base_revision": 0})
    route(server, "r_session_files", {"action": "open", "path": saved["path"]})
    reads(server, saved["path"])
    time.sleep(SETTLE_SECONDS)
    baseline = snapshot()
    intervals = []
    for _ in range(INTERVALS):
        time.sleep(INTERVAL_SECONDS)
        reads(server, saved["path"])
        intervals.append(snapshot())
    server.close()
    time.sleep(SETTLE_SECONDS)
    return {"path": saved["path"], "baseline": baseline, "intervals": intervals, "closed": snapshot()}


def restart():
    server = boot()
    path = json.loads(RESULT.read_text(encoding="utf-8"))["path"] if RESULT.exists() else None
    if path:
        reads(server, path)
    time.sleep(SETTLE_SECONDS)
    server.close()
    time.sleep(SETTLE_SECONDS)
    return {"path": path, "after": snapshot()}


def undo():
    from nodelang import canvas_documents as docs
    server = boot()
    saved = route(server, "r_session_files", {"action": "autosave", "document": workflow(), "base_revision": 0})
    path = saved["path"]
    original = body_of(docs.read(path))
    # An agent changes the document (canvas.set_param), then canvas.undo, then the window's redo
    # (the Studio pushes the redone document through autosave), then canvas.undo again.
    edited, _ = docs.edit(path, "agent:court", "set count",
                          lambda d: (next(n for n in d["nodes"] if n["id"] == "slice")["params"].update(count="2"), ["slice"])[1])
    edited = body_of(edited)
    after_undo = body_of(docs.undo_last(path, "You")[0])
    current = docs.read(path)
    redo = route(server, "r_session_files", {"action": "autosave", "document": {**edited, "properties": current["properties"]},
                                             "base_revision": docs.revision(current)})
    after_redo = body_of(redo["document"])
    after_second_undo = body_of(docs.undo_last(path, "You")[0])
    server.close()
    return {"changed": original != edited, "undo_exact": after_undo == original, "redo_exact": after_redo == edited,
            "second_undo_exact": after_second_undo == original,
            "count": [next(n for n in d["nodes"] if n["id"] == "slice")["params"]["count"]
                      for d in (original, edited, after_undo, after_redo, after_second_undo)]}


if __name__ == "__main__":
    result = {"idle": idle, "restart": restart, "undo": undo}[MODE]()
    if MODE == "restart":
        held = json.loads(RESULT.read_text(encoding="utf-8"))
        held.setdefault("restarts", []).append(result["after"])
        result = held
    RESULT.write_text(json.dumps(result), encoding="utf-8")
