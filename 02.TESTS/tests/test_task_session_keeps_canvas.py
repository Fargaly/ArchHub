"""A task-context write keeps the open canvas, including an edit saved just before it."""
import json
from pathlib import Path
from types import SimpleNamespace


def _isolate(monkeypatch, root):
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(root / name))
    monkeypatch.delenv("ARCHHUB_TEST_STATE_DIR", raising=False)


def _file(directory, name, node_id):
    from nodelang.session_files import new_document, write_document
    document = new_document(name)
    document["nodes"] = [{
        "id": node_id, "type": "note", "title": name, "params": {"span": 1},
        "position": {"x": 10, "y": 20},
    }]
    document["notes"] = [{"id": "canvas-note", "text": name + " mark", "position": {"x": 10, "y": 20}}]
    return write_document(str(directory / (name + ".archhub")), document)


def _call(function, *args):
    from nodelang.nograph_server import r_workshop
    req = SimpleNamespace(method="POST", body={
        "action": "data-api", "function": function, "args": list(args), "request_id": "task-keep",
    })
    return r_workshop(SimpleNamespace(), req)["result"]


def _current(root):
    path = root / "LOCALAPPDATA" / "ArchHub" / "sessions-files" / "current.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_context_edit_keeps_canvas_edit_and_the_open_file(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    from nodelang.session_files import read_document, write_document
    from nodelang.workshop_mailbox import application_history
    from nodelang.workshop_tasks import create

    folder = tmp_path / "files"
    folder.mkdir()
    path_a = _file(folder, "Alpha", "node-a")
    path_b = _file(folder, "Beta", "node-b")
    with application_history() as history:
        task_a = create(history, "Alpha task", "founder")["id"]
        task_b = create(history, "Beta task", "founder")["id"]

    opened_a = _call("openTaskGraph", task_a, path_a)
    _call("openTaskGraph", task_b, path_b)
    opened_a = _call("openTaskGraph", task_a)
    assert _current(tmp_path)["path"] == opened_a["path"]

    # The canvas flush: an edit that exists on disk before the task-context write.
    document = read_document(opened_a["path"])
    document["nodes"].append({
        "id": "canvas-edit", "type": "note", "title": "Unsaved wall", "params": {},
        "position": {"x": 48, "y": 64},
    })
    write_document(opened_a["path"], document)

    view_a = _call("setTaskSession", task_a, {
        "scope": "scope-a", "folders": ["C:/work/alpha"], "references": [{"id": "ref-a", "path": "alpha.rvt"}],
        "parameters": [{"id": "node-a", "params": {"span": 3}}],
    })
    view_b = _call("setTaskSession", task_b, {
        "scope": "scope-b", "folders": ["C:/work/beta"], "references": ["sheet-b"],
    })

    assert _current(tmp_path)["id"] == opened_a["id"]
    assert _current(tmp_path)["path"] == opened_a["path"]
    reopened = read_document(opened_a["path"])
    by_id = {node["id"]: node for node in reopened["nodes"]}
    assert by_id["canvas-edit"]["title"] == "Unsaved wall"
    assert by_id["canvas-edit"]["position"] == {"x": 48, "y": 64}
    assert by_id["node-a"]["params"]["span"] == 3
    assert by_id["node-a"]["position"] == {"x": 10, "y": 20}
    note = next(item for item in reopened["notes"] if item["id"] == "canvas-note")
    assert note["text"] == "Alpha mark" and note["position"] == {"x": 10, "y": 20}
    assert view_a["id"] == opened_a["id"]
    assert view_a["folders"] == ["C:/work/alpha"]
    assert view_a["references"] == [{"id": "ref-a", "path": "alpha.rvt"}]
    assert view_a["parameters"][0]["params"]["span"] == 3
    beta = read_document(view_b["path"])
    assert [node["id"] for node in beta["nodes"]] == ["node-b"]
    assert view_b["folders"] == ["C:/work/beta"] and view_b["references"] == ["sheet-b"]
    assert view_b["id"] != view_a["id"]
    again = _call("openTaskGraph", task_a)
    assert again["folders"] == ["C:/work/alpha"]
    assert again["id"] == opened_a["id"]
    assert Path(_current(tmp_path)["path"]) == Path(opened_a["path"])


def test_canvas_open_leaves_the_founders_file_selected(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    from nodelang.canvas_tools import register_canvas_tools
    from nodelang.session_files import SessionFiles, read_document
    from nodelang.workshop_tasks import _current_session

    folder = tmp_path / "files"
    folder.mkdir()
    path_a = _file(folder, "Alpha", "node-a")
    path_b = _file(folder, "Beta", "node-b")
    held = read_document(path_a)
    SessionFiles()._current(held["id"], path_a)
    before = _current(tmp_path)

    class Tools:
        def __init__(self):
            self.tools = {}

        def tool(self, name=None):
            def wrap(fn):
                self.tools[name] = fn
                return fn
            return wrap

    tools = Tools()
    register_canvas_tools(tools)
    opened = tools.tools["canvas.open"](path_b)
    assert opened["title"] == "Beta"
    assert _current(tmp_path) == before
    assert Path(_current_session()) == Path(path_a)
    assert "current.json" not in Path("01.APP/nodelang/workshop_tasks.py").read_text(encoding="utf-8")
    assert "current.json" not in Path("01.APP/nodelang/canvas_tools.py").read_text(encoding="utf-8")
