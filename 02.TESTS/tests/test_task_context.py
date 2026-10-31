"""Each Workshop task keeps its own .archhub file, scope and progress when Canvas switches A, B, then A."""
import json
from pathlib import Path
from types import SimpleNamespace


def _isolate(monkeypatch, root):
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(root / name))
    monkeypatch.delenv("ARCHHUB_TEST_STATE_DIR", raising=False)


def _file(directory, name, scope, progress, node_id, status, output):
    from nodelang.session_files import new_document, write_document
    document = new_document(name)
    document["nodes"] = [{
        "id": node_id, "type": "note", "title": name, "params": {},
        "position": {"x": 0, "y": 0},
        "result": {"status": status, "output": output, "error": ""},
    }]
    document["properties"] = {"taskContext": {
        "scope": scope, "rules": [name + " rule"], "agents": [name + " agent"],
        "plan": [name + " plan"], "progress": progress,
    }}
    return write_document(str(directory / (name + ".archhub")), document)


def _call(function, *args):
    from nodelang.nograph_server import r_workshop
    req = SimpleNamespace(method="POST", body={
        "action": "data-api", "function": function, "args": list(args), "request_id": "task-context",
    })
    return r_workshop(SimpleNamespace(), req)["result"]


def test_switching_tasks_keeps_each_file_scope_and_progress(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import create
    folder = tmp_path / "files"
    folder.mkdir()
    path_a = _file(folder, "Alpha", "scope-a", {"step": "one", "note": "alpha"}, "node-a", "Done", "alpha-out")
    path_b = _file(folder, "Beta", "scope-b", {"step": "two", "note": "beta"}, "node-b", "Working", "beta-out")
    with application_history() as history:
        task_a = create(history, "Alpha task", "founder")["id"]
        task_b = create(history, "Beta task", "founder")["id"]

    opened_a = _call("openTaskGraph", task_a, path_a)
    opened_b = _call("openTaskGraph", task_b, path_b)
    saved_a = Path(opened_a["path"]).read_bytes()
    saved_b = Path(opened_b["path"]).read_bytes()

    again_a = _call("openTaskGraph", task_a)
    again_b = _call("openTaskGraph", task_b)
    back_a = _call("openTaskGraph", task_a)

    assert Path(again_a["path"]).read_bytes() == saved_a
    assert Path(again_b["path"]).read_bytes() == saved_b
    assert Path(back_a["path"]).read_bytes() == saved_a
    assert Path(back_a["path"]) == Path(path_a) and Path(again_b["path"]) == Path(path_b)
    assert back_a["taskId"] == task_a and back_a["scope"] == "scope-a"
    assert back_a["rules"] == ["Alpha rule"] and back_a["agents"] == ["Alpha agent"] and back_a["plan"] == ["Alpha plan"]
    assert back_a["progress"] == {"step": "one", "note": "alpha"}
    assert back_a["workflow"] == [{"id": "node-a", "type": "note", "title": "Alpha"}]
    assert back_a["activity"] == [{"id": "node-a", "status": "Done", "output": "alpha-out"}]
    assert again_b["taskId"] == task_b and again_b["scope"] == "scope-b"
    assert again_b["progress"] == {"step": "two", "note": "beta"}
    assert again_b["workflow"] == [{"id": "node-b", "type": "note", "title": "Beta"}]
    assert again_b["activity"] == [{"id": "node-b", "status": "Working", "output": "beta-out"}]

    held = {row["id"]: row for row in _call("listTasks")}
    assert held[task_a]["sessionPath"] == back_a["path"] and held[task_a]["sessionOpen"] is True
    assert held[task_b]["sessionPath"] == again_b["path"] and held[task_b]["sessionOpen"] is False
    on_disk = json.loads(Path(path_b).read_text(encoding="utf-8"))["properties"]["taskContext"]
    assert on_disk["scope"] == "scope-b" and on_disk["progress"]["note"] == "beta" and on_disk["task"] == task_b
