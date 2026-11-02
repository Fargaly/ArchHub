"""A canvas annotation stays in the .archhub file when a task message is saved."""
import json
from types import SimpleNamespace


FIXTURE = {
    "format": "archhub",
    "version": 1,
    "id": "annotated-canvas",
    "title": "Annotated canvas",
    "nodes": [],
    "wires": [],
    "groups": [],
    "notes": [{
        "id": "canvas-note",
        "text": "Founder mark",
        "position": {"x": 10, "y": 20},
    }],
    "viewport": {"x": 0, "y": 0, "zoom": 1},
}


def _isolate(monkeypatch, root):
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(root / name))
    monkeypatch.delenv("ARCHHUB_TEST_STATE_DIR", raising=False)


def _call(function, *args):
    from nodelang.nograph_server import r_workshop
    req = SimpleNamespace(method="POST", body={
        "action": "data-api", "function": function, "args": list(args), "request_id": "task-notes",
    })
    return r_workshop(SimpleNamespace(), req)["result"]


def test_annotation_survives_task_message_save_and_reopen(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    from nodelang.session_files import read_document
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import create

    folder = tmp_path / "files"
    folder.mkdir()
    target = folder / "annotated-canvas.archhub"
    target.write_text(json.dumps(FIXTURE), encoding="utf-8")
    assert read_document(target)["notes"][0]["position"] == {"x": 10, "y": 20}

    with application_history() as history:
        task = create(history, "Keep the mark", "founder")["id"]
    _call("openTaskGraph", task, str(target))
    _call("setTaskSession", task, {"messages": [{"id": "msg-1", "who": "Grove", "text": "First"}]})
    view = _call("setTaskSession", task, {"messages": [
        {"id": "msg-1", "who": "Grove", "text": "First"},
        {"id": "msg-2", "who": "Ada", "text": "Second"},
    ]})

    reopened = read_document(view["path"])
    kept = next(note for note in reopened["notes"] if note.get("id") == "canvas-note")
    assert kept["id"] == "canvas-note"
    assert kept["position"] == {"x": 10, "y": 20}
    assert kept["text"] == "Founder mark"
    assert "role" not in kept
    assert [note["id"] for note in reopened["notes"]] == ["canvas-note", "msg-1", "msg-2"]
    assert view["messages"] == [
        {"id": "msg-1", "who": "Grove", "text": "First"},
        {"id": "msg-2", "who": "Ada", "text": "Second"},
    ]
    assert all(row["id"] != "canvas-note" for row in view["messages"])
