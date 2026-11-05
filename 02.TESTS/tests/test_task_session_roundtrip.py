"""Tasks A and B keep session, file, parameters, agents, plan and progress.

Drives the real nograph server over the studio's workshop and session-file
routes, restarts it, and reads both tasks back through those same routes.
"""
import json
from http.client import HTTPConnection
from pathlib import Path


def _isolate(monkeypatch, root):
    for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        path = root / name
        path.mkdir(parents=True)
        monkeypatch.setenv(name, str(path))
    monkeypatch.delenv("ARCHHUB_TEST_STATE_DIR", raising=False)
    monkeypatch.setenv("ARCHHUB_TEST_NO_OPEN", "1")


def _post(connection, path, body, headers):
    connection.request("POST", path, json.dumps(body).encode("utf-8"), headers)
    response = connection.getresponse()
    raw = response.read()
    return response.status, json.loads(raw.decode("utf-8") if raw else "{}")


class _Studio:
    """The same POST bodies studio/api.js sends: workshop() and sessionRequest()."""

    def __init__(self, server):
        self.server = server
        self.connection = HTTPConnection("127.0.0.1", server.port)
        status, signed = _post(self.connection, "/api/universal/session", {}, {
            "Content-Type": "application/json",
            "X-ArchHub-Sign-In": "1",
            "Cookie": "archhub_studio=%s" % server._cookie_token,
        })
        assert status == 200 and signed["ok"] is True, signed
        self.headers = {
            "Content-Type": "application/json",
            "X-ArchHub-Session": signed["token"],
            "X-ArchHub-CSRF": signed["csrf"],
        }

    def workshop(self, function, *args):
        status, body = _post(self.connection, "/api/universal/workshop", {
            "action": "data-api", "function": function, "args": list(args),
            "root": "app:workshop", "scope": "app:workshop", "request_id": "taskab-" + function,
        }, self.headers)
        assert status == 200 and body.get("ok") is True, body
        result = body["result"]
        if isinstance(result, dict):
            assert result.get("ok") is not False, result
        return result

    def files(self, action, **extra):
        status, body = _post(self.connection, "/api/session-files", {"action": action, **extra}, self.headers)
        assert status == 200 and body.get("ok") is True and body.get("cancelled") is not True, body
        return body

    def close(self):
        self.connection.close()


def _edit(studio, task_id, **values):
    return studio.workshop("setTaskSession", task_id, values)


def _save(studio, view):
    opened = studio.files("read", path=view["path"], id=view["id"])
    assert opened["document"]["id"] == view["id"]
    saved = studio.files("save", path=view["path"], document=opened["document"])
    assert Path(saved["path"]) == Path(view["path"])
    return saved["path"]


def _expect(view, spec):
    assert view["taskId"] == spec["taskId"]
    assert Path(view["path"]) == Path(spec["path"])
    assert view["id"] == spec["id"]
    assert view["scope"] == spec["scope"]
    assert view["rules"] == spec["rules"]
    assert view["agents"] == spec["agents"]
    assert view["plan"] == spec["plan"]
    assert view["progress"] == spec["progress"]
    assert view["workflow"] == spec["workflow"]
    assert view["activity"] == spec["activity"]
    assert view["parameters"] == spec["parameters"]
    assert view["messages"] == spec["messages"]
    on_disk = json.loads(Path(view["path"]).read_text(encoding="utf-8"))
    held = on_disk["properties"]["taskContext"]
    assert held["task"] == spec["taskId"]
    assert held["scope"] == spec["scope"] and held["plan"] == spec["plan"]
    assert held["agents"] == spec["agents"] and held["progress"] == spec["progress"]
    assert held["rules"] == spec["rules"]
    by_id = {node["id"]: node for node in on_disk["nodes"]}
    for row in spec["parameters"]:
        assert by_id[row["id"]]["params"] == row["params"]
    for note in spec["messages"]:
        assert any(item.get("text") == note["text"] and item.get("who") == note["who"] for item in on_disk["notes"])


def test_tasks_a_and_b_round_trip_through_the_studio_server(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path / "desk")
    from nodelang.nograph_server import NoGraphServer

    state = tmp_path / "desk" / "LOCALAPPDATA" / "ArchHub"
    state.mkdir(parents=True)
    servers = []
    stopped = set()

    def stop(server):
        if server in stopped:
            return
        stopped.add(server)
        try:
            server.close()
        except Exception:
            pass

    def boot():
        server = NoGraphServer(state).start()
        servers.append(server)
        return server, _Studio(server)

    studio = None
    try:
        server, studio = boot()
        alpha = studio.workshop("createTask", "Task A")
        beta = studio.workshop("createTask", "Task B")
        assert alpha["scope"] == beta["scope"] == ""
        legacy = studio.files("read", path=beta["path"], id=beta["id"])["document"]
        legacy["properties"]["taskContext"]["scope"] = legacy["id"]
        studio.files("save", path=beta["path"], document=legacy)
        beta = studio.workshop("openTaskGraph", beta["taskId"])
        assert beta["scope"] == ""
        assert alpha["taskId"] != beta["taskId"]
        assert Path(alpha["path"]) != Path(beta["path"])

        alpha = _edit(studio, alpha["taskId"], scope="scope-a", rules=["Alpha rule"], agents=["Grove"],
                      plan=["Alpha plan"], progress={"step": "one", "note": "alpha"},
                      nodes=[
                          {"id": "node-a", "type": "note", "title": "Alpha", "params": {"span": 12},
                           "result": {"status": "Done", "output": "alpha-out", "error": ""}},
                          {"id": "agent-a", "type": "thing.agent", "title": "Grove",
                           "params": {"agent": "Grove", "instructions": "Hold the alpha plan"}},
                      ],
                      messages=[{"id": "msg-a", "who": "Grove", "text": "Alpha is moving"}])
        alpha = _edit(studio, alpha["taskId"], parameters=[{"id": "node-a", "params": {"span": 18}}])
        beta = _edit(studio, beta["taskId"], scope="scope-b", rules=["Beta rule"], agents=["Ada"],
                     plan=["Beta plan"], progress={"step": "two", "note": "beta"},
                     nodes=[
                         {"id": "node-b", "type": "note", "title": "Beta", "params": {"span": 4},
                          "result": {"status": "Working", "output": "beta-out", "error": ""}},
                         {"id": "agent-b", "type": "thing.agent", "title": "Ada",
                          "params": {"agent": "Ada", "instructions": "Hold the beta plan"}},
                     ],
                     messages=[{"id": "msg-b", "who": "Ada", "text": "Beta is moving"}])
        beta = _edit(studio, beta["taskId"], parameters=[{"id": "node-b", "params": {"span": 7}}])
        _save(studio, alpha)
        _save(studio, beta)

        spec_a = {"taskId": alpha["taskId"], "path": alpha["path"], "id": alpha["id"], "scope": "scope-a",
                  "rules": ["Alpha rule"], "agents": ["Grove"], "plan": ["Alpha plan"],
                  "progress": {"step": "one", "note": "alpha"},
                  "workflow": [{"id": "node-a", "type": "note", "title": "Alpha"},
                               {"id": "agent-a", "type": "thing.agent", "title": "Grove"}],
                  "activity": [{"id": "node-a", "status": "Done", "output": "alpha-out"}],
                  "parameters": [{"id": "node-a", "params": {"span": 18}},
                                 {"id": "agent-a", "params": {"agent": "Grove", "instructions": "Hold the alpha plan"}}],
                  "messages": [{"id": "msg-a", "who": "Grove", "text": "Alpha is moving"}]}
        spec_b = {"taskId": beta["taskId"], "path": beta["path"], "id": beta["id"], "scope": "scope-b",
                  "rules": ["Beta rule"], "agents": ["Ada"], "plan": ["Beta plan"],
                  "progress": {"step": "two", "note": "beta"},
                  "workflow": [{"id": "node-b", "type": "note", "title": "Beta"},
                               {"id": "agent-b", "type": "thing.agent", "title": "Ada"}],
                  "activity": [{"id": "node-b", "status": "Working", "output": "beta-out"}],
                  "parameters": [{"id": "node-b", "params": {"span": 7}},
                                 {"id": "agent-b", "params": {"agent": "Ada", "instructions": "Hold the beta plan"}}],
                  "messages": [{"id": "msg-b", "who": "Ada", "text": "Beta is moving"}]}

        _expect(studio.workshop("openTaskGraph", beta["taskId"]), spec_b)
        _expect(studio.workshop("openTaskGraph", alpha["taskId"]), spec_a)
        _expect(studio.workshop("openTaskGraph", alpha["taskId"]), spec_a)
        listed = {row["id"]: row for row in studio.workshop("listTasks")}
        assert listed[alpha["taskId"]]["sessionPath"] == alpha["path"]
        assert listed[beta["taskId"]]["sessionPath"] == beta["path"]
        assert listed[alpha["taskId"]]["sessionOpen"] is True
        assert listed[beta["taskId"]]["sessionOpen"] is False

        studio.close()
        stop(server)
        server, studio = boot()
        _expect(studio.workshop("openTaskGraph", alpha["taskId"]), spec_a)
        _expect(studio.workshop("openTaskGraph", beta["taskId"]), spec_b)
        _expect(studio.workshop("openTaskGraph", alpha["taskId"]), spec_a)
        listed = {row["id"]: row for row in studio.workshop("listTasks")}
        assert Path(listed[alpha["taskId"]]["sessionPath"]) == Path(spec_a["path"])
        assert Path(listed[beta["taskId"]]["sessionPath"]) == Path(spec_b["path"])
        assert listed[beta["taskId"]]["sessionOpen"] is False
        assert listed[alpha["taskId"]]["sessionOpen"] is True
    finally:
        if studio is not None:
            studio.close()
        for held in servers:
            stop(held)
