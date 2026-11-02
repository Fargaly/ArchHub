"""host.exec and connector.call against a fake broker and a fake connector.

Nothing here talks to a live Revit, AutoCAD, or Notion session.
"""
import copy
import json
import os
import re
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

    def launch(argv, creationflags, timeout):
        launched.append((list(argv), creationflags, timeout))
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
    argv, flags, limit = launched[0]
    assert limit == 900
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

    def quiet(argv, creationflags, timeout):
        launched.append((list(argv), creationflags, timeout))
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


def _alive(pid):
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    code = ctypes.c_ulong()
    ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel.CloseHandle(handle)
    return bool(ok) and code.value == 259


def _stop_owned(pid, image):
    """Stop this stand-in pid only, and only when its image name matches."""
    if not _alive(pid):
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x1001, False, int(pid))
    if not handle:
        return
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        query = kernel.QueryFullProcessImageNameW
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        if not query(handle, 0, buffer, ctypes.byref(size)):
            return
        if Path(buffer.value).name.casefold() != image.casefold():
            return
        kernel.TerminateProcess(handle, 1)
    finally:
        kernel.CloseHandle(handle)


def _compile_stand_in(tmp_path):
    windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
    compilers = [
        windir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        windir / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    ]
    csc = next((path for path in compilers if path.is_file()), None)
    assert csc is not None
    source = tmp_path / "standin.cs"
    source.write_text(
        "using System; using System.Diagnostics; using System.IO; using System.Reflection; using System.Threading;"
        "class StandIn { static void Main() {"
        "string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);"
        "File.WriteAllText(Path.Combine(dir, \"child.pid\"), Process.GetCurrentProcess().Id.ToString());"
        "Console.Out.WriteLine(\"PARTIAL-LOG\"); Console.Out.Flush();"
        "Thread.Sleep(Timeout.Infinite); } }",
        encoding="utf-8",
    )
    exe = tmp_path / "standin-console.exe"
    compiled = subprocess.run(
        [str(csc), "/nologo", "/t:exe", "/out:" + str(exe), str(source)],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert compiled.returncode == 0, compiled.stderr or compiled.stdout
    return exe


def test_acad_core_stand_in_times_out_and_keeps_the_claim(monkeypatch, tmp_path):
    import time
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    assert LIBRARY_ITEM_ENGINES["host_exec"]["params"]["timeout"] == 900
    _mode(None)
    drawing = tmp_path / "plan.dwg"
    drawing.write_bytes(b"dwg")
    exe = _compile_stand_in(tmp_path)
    pid_path = tmp_path / "child.pid"
    monkeypatch.setattr("nodelang.host_exec.find_console", lambda explicit: str(exe))
    monkeypatch.setattr("nodelang.host_exec.hidden_cores", lambda: 0)
    monkeypatch.setattr("nodelang.host_exec.free_bytes", lambda: 4 * 2147483648)
    folder = tmp_path / "isolate"
    params = _params(
        host="acad-core", code='(princ "hi")', document=str(drawing),
        isolate_folder=str(folder), timeout=30,
    )
    try:
        started = time.monotonic()
        produced, display = host_exec.host_exec(params)
        elapsed = time.monotonic() - started
        assert display == "Timed out"
        assert produced["result"] == "Timed out"
        assert "PARTIAL-LOG" in produced["log"]
        assert 20 <= elapsed <= 45
        assert pid_path.is_file()
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        assert _alive(pid) is False
        claims = list((folder / "claims").glob("*.claim"))
        assert len(claims) == 1
        claim_text = claims[0].read_text(encoding="utf-8")
        replay_started = time.monotonic()
        replay, _display = host_exec.host_exec(params)
        assert time.monotonic() - replay_started < 5
        assert replay["result"] is None and "claim" in replay["log"]
        assert claims[0].is_file()
        assert claims[0].read_text(encoding="utf-8") == claim_text
        assert _alive(pid) is False
    finally:
        if pid_path.is_file():
            _stop_owned(int(pid_path.read_text(encoding="utf-8").strip() or "0"), exe.name)


def _hang_server():
    import socket
    import threading
    import time
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.2)
    stop = threading.Event()

    def handle(conn):
        try:
            conn.settimeout(2)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            first = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
            path = first.split(" ")[1] if " " in first else ""
            if path == "/exec":
                while not stop.is_set():
                    time.sleep(0.1)
                return
            body = b'{"status":"ok","document":"Drawing","document_title":"Drawing"}'
            head = (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
                b"Connection: close\r\n\r\n" % len(body)
            )
            conn.sendall(head + body)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def accept():
        while not stop.is_set():
            try:
                conn, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=accept, args=(), daemon=True).start()
    return listener, stop, listener.getsockname()[1]


def test_revit_and_acad_broker_exec_times_out(monkeypatch):
    import time
    _mode(None)
    listener, stop, port = _hang_server()
    monkeypatch.setattr("nodelang.clean_revit_adapter.BROKER_HOST", "127.0.0.1")
    monkeypatch.setattr("nodelang.host_bridge_auth.ensure_secret", lambda: "k" * 32)

    def sessions(service, include_document=True):
        return [{
            "port": port,
            "pid": 1,
            "service": "acad-mcp" if service == "acad" else "revit-mcp",
            "revit_version": "2026" if service == "revit" else "",
            "acad_version": "2026" if service == "acad" else "",
            "document": "Drawing",
        }]

    monkeypatch.setattr("nodelang.host_brokers.broker_sessions", sessions)
    try:
        for host in ("revit", "acad"):
            started = time.monotonic()
            produced, display = host_exec.host_exec(_params(
                host=host, code="return;", document="Drawing", timeout=2,
            ))
            elapsed = time.monotonic() - started
            assert display == "Timed out", (host, display, produced)
            assert produced["result"] == "Timed out"
            assert 1 <= elapsed <= 8, (host, elapsed)
    finally:
        stop.set()
        listener.close()


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


def _script_result(code):
    import re
    bound = {}
    for line in code.splitlines():
        match = re.fullmatch(r"var ([A-Za-z_][A-Za-z0-9_]*) = (.*);", line.strip())
        if not match:
            continue
        literal = match.group(2)
        bound[match.group(1)] = json.loads(literal) if literal[:1] == '"' else literal
    used = re.search(r"(?m)^result = ([A-Za-z_][A-Za-z0-9_]*);", code)
    if used and used.group(1) in bound:
        return bound[used.group(1)]
    return None


def test_user_parameters_reach_code_and_connector_args(monkeypatch, tmp_path):
    """A param.value wired to param:<id> is a code variable; connector params fill args."""
    import copy
    from nodelang.enforce import guard_effect
    from nodelang.node_params import add_param
    from nodelang.session_files import catalogue, new_document, read_document, run_document, write_document

    _mode(None)
    calls = _broker(monkeypatch, ["Drawing", "Drawing"])
    host_exec.host_exec(_params(code="result = sheet;", sheet="typed"))
    assert 'var sheet = "typed";' in calls[-1][2]["code"]
    host_exec.host_exec(_params(code="result = sheet;", sheet="typed"), {"sheet": "from-wire"})
    assert 'var sheet = "from-wire";' in calls[-1][2]["code"]

    def running(service, route, body=None, **_kwargs):
        if route == "/info":
            return {"ok": True, "document": "Drawing"}
        return {"ok": True, "result": _script_result(body["code"]), "document": "Drawing"}

    monkeypatch.setattr("nodelang.host_brokers.broker_call", running)
    invoked = []

    def lister():
        return [{"name": "notion-search", "title": "Search", "inputs": ["query"]}]

    def invoker(action, arguments):
        invoked.append((action, arguments))
        return {"ok": True, "action": action}

    monkeypatch.setitem(host_exec.LISTERS, "notion", lister)
    monkeypatch.setitem(host_exec.INVOKERS, "notion", invoker)

    rows = {row["id"]: row for row in catalogue()}
    host_item = next(row for row in rows.values() if row["engine"] == "host.exec")
    call_item = next(row for row in rows.values() if row["engine"] == "connector.call")
    value_item = rows["param.value"]
    doc = new_document("Host inputs")

    def place(node_id, item, x, params):
        doc["nodes"].append({
            "id": node_id, "item": item["id"], "type": item["engine"], "title": item["title"],
            "params": params, "position": {"x": x, "y": 80},
        })

    place("sheet-in", value_item, 0, {"type": "text", "value": "sheet"})
    place("host", host_item, 320, copy.deepcopy(host_item["params"]))
    doc["nodes"][1]["params"]["code"] = "result = sheet;"
    add_param(doc, "host", "sheet", "text", "")
    place("query-in", value_item, 0, {"type": "text", "value": "walls"})
    place("call-query", call_item, 320, copy.deepcopy(call_item["params"]))
    doc["nodes"][3]["params"]["action"] = "notion-search"
    add_param(doc, "call-query", "query", "text", "")
    place("args-in", value_item, 0, {"type": "object", "value": {"query": "doors"}})
    place("call-args", call_item, 320, copy.deepcopy(call_item["params"]))
    doc["nodes"][5]["params"]["action"] = "notion-search"
    doc["nodes"][5].setdefault("paramDefs", []).append({"id": "args", "name": "Args", "type": "object"})
    doc["nodes"][5]["params"]["args"] = {}
    doc["wires"] = [
        {"id": "w-sheet", "from": {"node": "sheet-in", "socket": "value"}, "to": {"node": "host", "socket": "param:sheet"}},
        {"id": "w-query", "from": {"node": "query-in", "socket": "value"}, "to": {"node": "call-query", "socket": "param:query"}},
        {"id": "w-args", "from": {"node": "args-in", "socket": "value"}, "to": {"node": "call-args", "socket": "param:args"}},
    ]
    path = tmp_path / "inputs.archhub"
    write_document(path, doc)
    ran = run_document(read_document(path), invoke=lambda name, effect, params, feeds: guard_effect(name, effect, params, feeds))
    assert ran["succeeded"], {key: row.get("error") for key, row in ran["results"].items() if row.get("error")}
    assert ran["results"]["host"]["output"]["result"] == "sheet"
    assert ("notion-search", {"query": "walls"}) in invoked
    assert ("notion-search", {"query": "doors"}) in invoked
    _mode(None)


def test_python_host_binds_a_parameter_and_stamps_a_pdf(tmp_path):
    """Python runs in its own process: a bound parameter, then a pypdf stamp that leaves the source alone."""
    from pypdf import PdfReader, PdfWriter

    _mode(None)
    produced, _display = host_exec.host_exec(_params(host="python", code="result = x * 2", timeout=30), {"x": 21})
    assert produced["result"] == 42
    assert produced["action"] == "write"

    _mode("Plan only")
    held, display = host_exec.host_exec(_params(host="python", code="result = x * 2", timeout=30), {"x": 21})
    assert display == "Failed" and held["result"] is None and held["action"] == "write"
    _mode(None)

    blocked, _display = host_exec.host_exec(_params(
        host="python", timeout=20,
        code="import socket\nsocket.create_connection(('127.0.0.1', 9))\nresult = 'open'",
    ))
    assert blocked["result"] is None and "network" in blocked["log"].lower()

    source = tmp_path / "sheet.pdf"
    dest = tmp_path / "STAMPED" / "sheet.pdf"
    made = PdfWriter()
    made.add_blank_page(width=200, height=200)
    with source.open("wb") as handle:
        made.write(handle)
    original = source.read_bytes()
    code = (
        "from io import BytesIO\n"
        "from pathlib import Path\n"
        "from pypdf import PdfReader, PdfWriter, Transformation\n"
        "reader = PdfReader(source)\n"
        "stamp = PdfWriter()\n"
        "stamp.add_blank_page(width=40, height=16)\n"
        "raw = BytesIO()\n"
        "stamp.write(raw)\n"
        "page = reader.pages[0]\n"
        "page.merge_transformed_page(PdfReader(raw).pages[0], Transformation().translate(140, 30))\n"
        "out = PdfWriter()\n"
        "out.add_page(page)\n"
        "target = Path(dest)\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "with target.open('wb') as handle:\n"
        "    out.write(handle)\n"
        "result = str(target)\n"
    )
    stamped, _display = host_exec.host_exec(
        _params(host="python", code=code, timeout=30, document=str(tmp_path)),
        {"source": str(source), "dest": str(dest)},
    )
    assert stamped["result"] == str(dest)
    assert source.read_bytes() == original
    assert dest.is_file() and dest.read_bytes() != original
    assert len(PdfReader(str(dest)).pages) == 1
    assert "Python" in [row["label"] for row in host_exec.programs()]
    _mode(None)


def test_connector_call_lists_registered_outlook_and_gates_categorize():
    """Actions come from the connector registry. A categorize send waits; it is not sent."""
    _mode(None)
    names = {row["name"] for row in host_exec.connector_actions("outlook-new")}
    assert "outlook.graph.categories" in names
    assert "outlook.graph.categorize" in names
    classic = {row["name"] for row in host_exec.connector_actions("outlook")}
    assert "outlook.inbox" in classic
    assert "outlook.reply_draft" not in classic and "outlook.forward_draft" not in classic
    ids = {row["id"] for row in host_exec.connectors()}
    assert {"notion", "outlook-new", "dropbox", "office"} <= ids
    preview = host_exec.connector_preview("outlook-new", "outlook.graph.categorize", {"categories": ["Issued"]})
    assert preview["action_class"] == "send"

    invoked = []

    def lister():
        return [
            {"name": "outlook.graph.categories", "title": "Categories", "inputs": ["account"]},
            {"name": "outlook.graph.categorize", "title": "Categorize", "inputs": ["account", "categories"]},
        ]

    def invoker(action, arguments):
        invoked.append((action, arguments))
        return {"ok": True, "action": action}

    host_exec.register_connector("outlook-fake", "Outlook", lister, invoker)
    try:
        listed = {row["name"] for row in host_exec.connector_actions("outlook-fake")}
        assert listed == {"outlook.graph.categories", "outlook.graph.categorize"}
        _mode("Ask first")
        produced, display = host_exec.connector_call({
            "connector": "outlook-fake",
            "action": "outlook.graph.categorize",
            "args": {"account": "owner@example.com", "categories": ["Issued"]},
        })
        assert display == "Waiting for you"
        assert produced["action_class"] == "send"
        assert produced["result"] is None
        assert invoked == []
    finally:
        host_exec.LISTERS.pop("outlook-fake", None)
        host_exec.INVOKERS.pop("outlook-fake", None)
        host_exec._LABELS.pop("outlook-fake", None)
        _mode(None)


def _bound_literal(code, name):
    match = re.search(r'var %s = ("(?:\\.|[^"\\])*");' % name, code)
    assert match, code
    return json.loads(match.group(1))


def _revit_uppercase(monkeypatch, fail_item=None):
    """Fake broker: the Revit script's bound item comes back upper-cased."""
    calls = []

    def fake(service, route, body=None, **_kwargs):
        if route == "/info":
            calls.append((route, None, None))
            return {"ok": True, "document": "Sheet"}
        item = _bound_literal(body["code"], "item")
        suffix = _bound_literal(body["code"], "suffix") if "var suffix = " in body["code"] else ""
        calls.append((route, item, suffix))
        if fail_item is not None and item == fail_item:
            raise ValueError("item %s refused" % item)
        return {"ok": True, "result": str(item).upper(), "document": "Sheet"}

    monkeypatch.setattr("nodelang.host_brokers.broker_call", fake)
    return calls


def _spy_decide(monkeypatch):
    seen = []
    real = host_exec.hook_decision.decide

    def spy(payload, *args, **kwargs):
        decision = real(payload, *args, **kwargs)
        seen.append(decision)
        return decision

    monkeypatch.setattr("nodelang.hook_decision.decide", spy)
    return seen


def _card(item_id, node_id, x):
    from nodelang.session_files import catalogue
    item = {row["id"]: row for row in catalogue()}[item_id]
    return {
        "id": node_id, "item": item["id"], "type": item["engine"], "title": item["title"],
        "params": copy.deepcopy(item["params"]), "position": {"x": x, "y": 0},
    }


def _foreach_host_document():
    from nodelang.session_files import new_document
    doc = new_document("Foreach host")
    listing = _card("param.value", "list", 0)
    listing["params"] = {"type": "list", "value": ["a", "b", "c"]}
    mark = _card("param.value", "mark", 40)
    mark["params"] = {"type": "text", "value": "!"}
    batch = _card("l_foreach", "batch", 280)
    run = _card("host_exec", "run", 560)
    run["params"].update(_params(code="result = item;", document="Sheet", transaction=False))
    run["paramDefs"] = [
        {"id": "item", "name": "Item", "type": "text"},
        {"id": "suffix", "name": "Suffix", "type": "text"},
    ]
    doc["nodes"] = [listing, mark, batch, run]
    doc["wires"] = [
        {"id": "w0", "from": {"node": "list", "socket": "value"}, "to": {"node": "batch", "socket": "items"}},
        {"id": "w1", "from": {"node": "batch", "socket": "each"}, "to": {"node": "run", "socket": "param:item"}},
        {"id": "w2", "from": {"node": "mark", "socket": "value"}, "to": {"node": "run", "socket": "param:suffix"}},
    ]
    return doc


def _run_host_document(monkeypatch, fail_item=None):
    from nodelang.session_files import run_document
    _mode(None)
    calls = _revit_uppercase(monkeypatch, fail_item)
    seen = _spy_decide(monkeypatch)
    ran = run_document(doc := _foreach_host_document(), invoke=lambda name, effect, params, feeds: effect(params, feeds))
    return ran, calls, seen, doc


def test_foreach_each_runs_host_exec_once_per_item(monkeypatch):
    """foreach([a,b,c]) -> host.exec runs three times and stacks [A,B,C]."""
    ran, calls, seen, _doc = _run_host_document(monkeypatch)
    assert ran["succeeded"], ran["results"]["run"]
    assert ran["results"]["run"]["output"]["result"] == ["A", "B", "C"]
    execs = [item for route, item, _suffix in calls if route == "/exec"]
    assert execs == ["a", "b", "c"]
    assert [suffix for route, _item, suffix in calls if route == "/exec"] == ["!", "!", "!"]
    assert len(seen) == 3
    assert {row["verdict"] for row in seen} == {"allow"}
    assert {row["action"] for row in seen} == {"write"}


def test_foreach_each_runs_connector_call_once_per_item(monkeypatch):
    """The same list reaches connector.call as three separate calls."""
    from nodelang.session_files import new_document, run_document
    _mode(None)
    doc = new_document("Foreach connector")
    listing = _card("param.value", "list", 0)
    listing["params"] = {"type": "list", "value": ["a", "b", "c"]}
    batch = _card("l_foreach", "batch", 280)
    run = _card("connector_call", "run", 560)
    run["params"]["connector"] = "batch-echo"
    run["params"]["action"] = "echo.item"
    doc["nodes"] = [listing, batch, run]
    doc["wires"] = [
        {"id": "w0", "from": {"node": "list", "socket": "value"}, "to": {"node": "batch", "socket": "items"}},
        {"id": "w1", "from": {"node": "batch", "socket": "each"}, "to": {"node": "run", "socket": "args"}},
    ]
    invoked = []

    def lister():
        return [{"name": "echo.item", "title": "Echo", "inputs": ["args"]}]

    def invoker(action, arguments):
        invoked.append((action, arguments))
        item = arguments["value"] if isinstance(arguments, dict) else arguments
        return str(item).upper()

    host_exec.register_connector("batch-echo", "Batch echo", lister, invoker)
    seen = _spy_decide(monkeypatch)
    try:
        ran = run_document(doc, invoke=lambda name, effect, params, feeds: effect(params, feeds))
    finally:
        host_exec.LISTERS.pop("batch-echo", None)
        host_exec.INVOKERS.pop("batch-echo", None)
        host_exec._LABELS.pop("batch-echo", None)
    assert ran["succeeded"], ran["results"]["run"]
    assert invoked == [
        ("echo.item", {"value": "a"}),
        ("echo.item", {"value": "b"}),
        ("echo.item", {"value": "c"}),
    ]
    assert ran["results"]["run"]["output"]["result"] == ["A", "B", "C"]
    assert len(seen) == 3
    assert {row["verdict"] for row in seen} == {"allow"}


def test_foreach_each_records_a_failed_item_and_continues(monkeypatch):
    """Item b is reported. a and c still run. Nothing is dropped from the list."""
    ran, calls, seen, _doc = _run_host_document(monkeypatch, fail_item="b")
    result = ran["results"]["run"]
    assert result["status"] == "Error"
    assert result["output"]["result"] == ["A", None, "C"]
    assert "item b refused" in result["error"]
    assert "item 1:" in result["error"]
    execs = [item for route, item, _suffix in calls if route == "/exec"]
    assert execs == ["a", "b", "c"]
    assert len(seen) == 3


def _stem_host(monkeypatch, fail_item=None):
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    from nodelang.stem_graph_evaluation import StemNode, StemWire, evaluate_stem_graph
    _mode(None)
    calls = _revit_uppercase(monkeypatch, fail_item)
    seen = _spy_decide(monkeypatch)
    evaluation = evaluate_stem_graph(
        [
            StemNode("list", "data.list", {"value": '["a","b","c"]'}),
            StemNode("mark", "data.constant", {"value": "!"}),
            StemNode("batch", "control.foreach", {}),
            StemNode("run", "host.exec", _params(code="result = item;", document="Sheet", transaction=False)),
        ],
        [
            StemWire("list", "value", "batch", "items"),
            StemWire("batch", "each", "run", "item"),
            StemWire("mark", "value", "run", "suffix"),
        ],
        None,
        dict(PIPELINE_ENGINES),
    )
    return evaluation, calls, seen


def test_stem_evaluator_runs_host_exec_once_per_item(monkeypatch):
    """universal_pipeline's evaluator is the same per-item rule."""
    evaluation, calls, seen = _stem_host(monkeypatch)
    assert evaluation.node_outputs["run"]["result"] == ["A", "B", "C"]
    assert "run" not in evaluation.pending
    execs = [item for route, item, _suffix in calls if route == "/exec"]
    assert execs == ["a", "b", "c"]
    assert len(seen) == 3
    assert {row["verdict"] for row in seen} == {"allow"}


def test_stem_evaluator_records_a_failed_item_and_continues(monkeypatch):
    evaluation, calls, seen = _stem_host(monkeypatch, fail_item="b")
    assert evaluation.node_outputs["run"]["result"] == ["A", None, "C"]
    assert "item b refused" in evaluation.pending["run"]
    execs = [item for route, item, _suffix in calls if route == "/exec"]
    assert execs == ["a", "b", "c"]
    assert len(seen) == 3


def test_foreach_each_uses_grasshopper_longest_list():
    from nodelang.stem_graph_evaluation import longest_each_plans, foreach_each_items
    assert foreach_each_items("control.foreach", "results", {"each": "a", "results": ["a", "b"]}) is None
    assert foreach_each_items("control.foreach", "each", {"each": "a", "results": ["a", "b", "c"]}) == ["a", "b", "c"]
    plans = longest_each_plans({"item": ["a", "b", "c"], "extra": ["x"]}, {"suffix": "!"})
    assert [row["item"] for row in plans] == ["a", "b", "c"]
    assert [row["extra"] for row in plans] == ["x", "x", "x"]
    assert [row["suffix"] for row in plans] == ["!", "!", "!"]
