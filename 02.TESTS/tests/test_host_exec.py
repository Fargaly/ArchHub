"""host.exec and connector.call against a fake broker and a fake connector.

Nothing here talks to a live Revit, AutoCAD, or Notion session.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="hostexec-"))
for _name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
    _path = _root / _name
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_name] = str(_path)

from nodelang import host_exec
from nodelang.library_engines import library_catalogue
from nodelang.pipeline_engines import PIPELINE_ENGINES


def _params(**over):
    base = {
        "host": "revit",
        "code": "return;",
        "transaction_name": "ArchHub",
        "transaction": True,
        "document": "",
        "element_limit": 150,
        "sheet_limit": 1,
        "min_free_bytes": 2147483648,
        "max_hidden_core": 1,
        "log_sentinel": "ARCHHUB_CORE_DONE",
        "load_module": "acismobj25.dbx",
        "isolate_user": "tester",
        "isolate_folder": "",
    }
    base.update(over)
    return base


def _mode(mode):
    folder = Path(os.environ["LOCALAPPDATA"]) / "ArchHub" / "settings"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "permissions.json"
    if mode is None:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({"runMode": mode, "tools": {}}), encoding="utf-8")


def _broker(monkeypatch, titles):
    calls = []
    pending = list(titles)

    def fake(service, route, body=None, **_kwargs):
        calls.append((service, route, body))
        if route == "/info":
            return {"ok": True, "document": pending.pop(0) if pending else titles[-1]}
        if route == "/exec" and body is None:
            raise AssertionError("exec was not expected")
        return {"ok": True, "result": {"count": 1}, "document": titles[-1] if titles else ""}

    monkeypatch.setattr("nodelang.host_brokers.broker_call", fake)
    return calls


def test_revit_routes_through_decide_and_wraps_return(monkeypatch):
    _mode(None)
    calls = _broker(monkeypatch, ["Sheet 1", "Sheet 1"])
    seen = []
    real = host_exec.hook_decision.decide

    def spy(payload, *args, **kwargs):
        seen.append(payload)
        return real(payload, *args, **kwargs)

    monkeypatch.setattr("nodelang.hook_decision.decide", spy)
    produced, display = host_exec.host_exec(_params(document="Sheet 1", transaction=False), {"width": 12})
    assert seen[0]["tool_name"] == "write"
    assert [route for _service, route, _body in calls] == ["/info", "/info", "/exec"]
    assert calls[0][0] == "revit"
    body = calls[2][2]
    assert "return null;" in body["code"]
    assert "return result;" in body["code"]
    assert "var width = 12;" in body["code"]
    assert body["transaction"] is False
    assert produced["result"]["count"] == 1
    assert display


def test_revit_refuses_a_changed_document_and_a_long_batch(monkeypatch):
    _mode(None)
    calls = _broker(monkeypatch, ["Sheet 1", "Sheet 2"])
    produced, display = host_exec.host_exec(_params(document="Sheet 1"))
    assert display == "Failed"
    assert produced["result"] is None
    assert "/exec" not in [route for _service, route, _body in calls]

    calls = _broker(monkeypatch, ["Other", "Other"])
    produced, _display = host_exec.host_exec(_params(document="Sheet 1"))
    assert produced["result"] is None
    assert "/exec" not in [route for _service, route, _body in calls]

    calls = _broker(monkeypatch, ["Sheet 1", "Sheet 1"])
    produced, _display = host_exec.host_exec(_params(), {"elements": list(range(151))})
    assert produced["result"] is None
    assert calls == []


def test_plan_only_does_not_call_the_broker(monkeypatch):
    _mode("Plan only")
    calls = _broker(monkeypatch, ["Sheet 1", "Sheet 1"])
    produced, display = host_exec.host_exec(_params())
    assert display == "Failed"
    assert produced["action"] == "write"
    assert produced["result"] is None
    assert calls == []
    _mode(None)


def test_each_host_uses_its_runner(monkeypatch):
    _mode(None)
    calls = _broker(monkeypatch, ["Drawing", "Drawing"])
    host_exec.host_exec(_params(host="acad", code="line;", document="Drawing"))
    assert calls[-1][0] == "acad" and calls[-1][1] == "/exec"

    used = []

    def record(name):
        def runner(params, feeds):
            used.append((name, params))
            return {"ok": True, "out": name}, name
        return runner

    monkeypatch.setattr("nodelang.host_brokers.rhino_exec", record("rhino"))
    monkeypatch.setattr("nodelang.host_brokers.blender_exec", record("blender"))
    monkeypatch.setattr("nodelang.host_brokers.max_exec", record("max"))
    monkeypatch.setattr("nodelang.host_brokers.office_read", record("office"))
    host_exec.host_exec(_params(host="rhino", code="print(1)"))
    host_exec.host_exec(_params(host="blender", code="print(1)"))
    host_exec.host_exec(_params(host="max", code="print 1"), {"height": 3})
    host_exec.host_exec(_params(host="office", code="excel.list_workbooks"))
    assert [name for name, _params in used] == ["rhino", "blender", "max", "office"]
    assert "height = 3" in used[2][1]["code"]
    assert used[3][1]["operation"] == "excel.list_workbooks"


def test_background_autocad_guards(monkeypatch, tmp_path):
    _mode(None)
    drawing = tmp_path / "plan.dwg"
    drawing.write_bytes(b"dwg")
    exe = tmp_path / "accoreconsole.exe"
    exe.write_bytes(b"")
    launched = []
    real_hash = host_exec.hash_file

    def launch(argv, creationflags):
        launched.append((list(argv), creationflags))
        return "ARCHHUB_CORE_DONE\n", 0

    monkeypatch.setattr("nodelang.host_exec.launch_console", launch)
    monkeypatch.setattr("nodelang.host_exec.hidden_cores", lambda: 0)
    monkeypatch.setattr("nodelang.host_exec.free_bytes", lambda: 4 * 2147483648)
    monkeypatch.setattr("nodelang.host_exec.find_console", lambda explicit: str(exe))
    monkeypatch.setattr("nodelang.host_brokers.broker_call", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("broker")))

    folder = tmp_path / "isolate"
    produced, log = host_exec.host_exec(_params(
        host="acad-core", code='(princ "hi")', document=str(drawing), isolate_folder=str(folder),
    ))
    argv, flags = launched[0]
    assert flags == subprocess.CREATE_NO_WINDOW
    assert argv[1:6] == ["/isolate", "tester", str(folder), "/loadmodule", "acismobj25.dbx"]
    assert "/i" in argv and "/s" in argv
    assert produced["result"]["ok"] is True
    assert "ARCHHUB_CORE_DONE" in log
    script = (folder / "run.scr").read_text(encoding="utf-8")
    assert '(princ "ARCHHUB_CORE_DONE")' in script

    replay, _display = host_exec.host_exec(_params(
        host="acad-core", code='(princ "hi")', document=str(drawing), isolate_folder=str(folder),
    ))
    assert replay["result"] is None and "claim" in replay["log"]
    assert len(launched) == 1

    monkeypatch.setattr("nodelang.host_exec.hidden_cores", lambda: 1)
    produced, _display = host_exec.host_exec(_params(
        host="acad-core", code='(princ "other")', document=str(drawing), isolate_folder=str(folder),
    ))
    assert produced["result"] is None and len(launched) == 1

    monkeypatch.setattr("nodelang.host_exec.hidden_cores", lambda: 0)
    monkeypatch.setattr("nodelang.host_exec.free_bytes", lambda: 1)
    produced, _display = host_exec.host_exec(_params(
        host="acad-core", code='(princ "mem")', document=str(drawing), isolate_folder=str(tmp_path / "mem"),
    ))
    assert produced["result"] is None and len(launched) == 1

    sequence = iter(["aa", "aa", "bb", "bb"])
    monkeypatch.setattr("nodelang.host_exec.free_bytes", lambda: 4 * 2147483648)
    monkeypatch.setattr("nodelang.host_exec.hash_file", lambda path: next(sequence))
    produced, _display = host_exec.host_exec(_params(
        host="acad-core", code='(princ "hash")', document=str(drawing), isolate_folder=str(tmp_path / "hash"),
    ))
    assert produced["result"] is None and len(launched) == 1

    def quiet(argv, creationflags):
        launched.append((list(argv), creationflags))
        return "no mark\n", 0

    monkeypatch.setattr("nodelang.host_exec.launch_console", quiet)
    monkeypatch.setattr("nodelang.host_exec.hash_file", real_hash)
    produced, _display = host_exec.host_exec(_params(
        host="acad-core", code='(princ "mark")', document=str(drawing), isolate_folder=str(tmp_path / "mark"),
    ))
    assert produced["result"] is None
    assert "log mark" in produced["log"]

    produced, _display = host_exec.host_exec(_params(
        host="acad-core", code='(princ "unc")', document=r"\\server\share\plan.dwg",
        isolate_folder=str(tmp_path / "unc"),
    ))
    assert produced["result"] is None
    assert "local file" in produced["log"]


def test_program_state_does_not_execute(monkeypatch):
    seen = []
    monkeypatch.setattr("nodelang.host_brokers.broker_call", lambda *args, **kwargs: seen.append(args))
    monkeypatch.setattr("nodelang.host_brokers.broker_sessions", lambda service, include_document=True: [])
    state = host_exec.program_state("revit")
    assert state["label"] == "Revit" and state["state"] == "Not installed" and state["reachable"] is False
    assert seen == []
    monkeypatch.setattr("nodelang.host_brokers.broker_sessions", lambda service, include_document=True: [{"port": 1}] if include_document is False else [])
    state = host_exec.program_state("revit")
    assert state["state"] == "Connected" and state["reachable"] is True
    labels = [row["label"] for row in host_exec.programs()]
    assert "AutoCAD (background)" in labels
    assert "acad-core" not in labels


def test_connector_lists_live_and_gates_sends(monkeypatch):
    _mode(None)
    listed = []
    invoked = []

    def lister():
        listed.append(1)
        return [
            {"name": "notion-search", "title": "Search", "inputs": ["query"]},
            {"name": "post_message", "title": "Post", "inputs": ["text"]},
        ]

    def invoker(action, arguments):
        invoked.append((action, arguments))
        return {"ok": True, "action": action}

    monkeypatch.setitem(host_exec.LISTERS, "notion", lister)
    monkeypatch.setitem(host_exec.INVOKERS, "notion", invoker)
    host_exec.connector_call({"connector": "notion", "action": "notion-search", "args": ""}, {"args": {"query": "walls"}})
    host_exec.connector_call({"connector": "notion", "action": "notion-search", "args": ""}, {"args": {"query": "doors"}})
    assert len(listed) == 2 and len(invoked) == 2
    assert invoked[0] == ("notion-search", {"query": "walls"})

    _mode("Ask first")
    produced, display = host_exec.connector_call(
        {"connector": "notion", "action": "post_message", "args": "hello from the node"},
    )
    assert display == "Waiting for you"
    assert produced["action_class"] == "send"
    assert produced["preview"] == "hello from the node"
    assert len(invoked) == 2 and len(listed) == 2

    _mode(None)
    produced, display = host_exec.connector_call({"connector": "missing", "action": "notion-search", "args": ""})
    assert display == "Failed"
    assert "not connected" in produced["log"]
    assert len(invoked) == 2
    assert host_exec.connector_actions("") == []
    preview = host_exec.connector_preview("notion", "post_message", "shown before approve")
    assert preview["action_class"] == "send" and preview["preview"] == "shown before approve"
    _mode(None)


def test_both_nodes_are_in_the_library():
    items = [item for group in library_catalogue() for item in group["items"] if not item.get("hidden")]
    host = next(item for item in items if item["engine"] == "host.exec")
    connector = next(item for item in items if item["engine"] == "connector.call")
    assert host["title"] == "Run in program"
    assert connector["title"] == "Connector action"
    assert "element_limit" in host["sockets"]["target"]
    assert "action" in connector["sockets"]["target"]
    assert "result" in host["sockets"]["source"] and "log" in host["sockets"]["source"]
    assert host["params"]["element_limit"] == 150
    assert host["params"]["transaction"] is True
    assert "host.exec" in PIPELINE_ENGINES and "connector.call" in PIPELINE_ENGINES
