import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nodelang.application_server import ApplicationServer


def _get_json(server, path):
    request = Request(
        server.url + path,
        headers={"X-ArchHub-Session": server.browser_session_token},
    )
    with urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _get_status(server, path):
    request = Request(
        server.url + path,
        headers={"X-ArchHub-Session": server.browser_session_token},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status
    except HTTPError as exc:
        return exc.code


def test_frame_hub_endpoints_are_on_the_application_port_and_own_only_hub_files():
    server = ApplicationServer(fresh=True).start()
    try:
        status, tools = _get_json(server, "/tools")
        assert status == 200
        assert [row["id"] for row in tools["tools"]] == [
            "studio", "workshop", "brain", "baboom", "connectors", "cloud",
        ]
        states = [row["state"] for row in tools["tools"]]
        assert states[:5] == [
            "running", "running", "starting", "starting", "starting",
        ]
        assert states[5] in ("starting", "running", "failed")
        assert not any(
            "unknown" in (row["state"] + " " + row["state_word"] + " " + row["stat_line"]).lower()
            for row in tools["tools"]
        )
        assert tools["owned_files"] == [
            "tools.json", "wires.json", "waiting.json", "activity.log",
        ]
        assert not {"hosts", "sessions", "brain", "approvals"} & set(tools)

        status, wires = _get_json(server, "/wires")
        assert status == 200
        assert wires["ok"] is True
        assert "wires" in wires
        assert "hosts" not in wires

        status, waiting = _get_json(server, "/waiting")
        assert status == 200
        assert waiting["ok"] is True
        assert "items" in waiting
        assert "approvals" not in waiting
    finally:
        server.close()


def test_studio_tool_stat_counts_the_same_graph_sessions_as_home():
    server = ApplicationServer(fresh=True).start()
    try:
        status, graphs = _get_json(server, "/api/universal/graphs")
        assert status == 200
        expected_total = len(graphs["graphs"])
        expected_running = len([
            graph for graph in graphs["graphs"]
            if graph.get("state") == "running"
        ])

        status, tools = _get_json(server, "/tools")
        assert status == 200
        studio = next(row for row in tools["tools"] if row["id"] == "studio")
        assert studio["stat_line"] == (
            f"{expected_total} session{'' if expected_total == 1 else 's'} · {expected_running} running."
        )
    finally:
        server.close()


def _post_json(server, path, body):
    request = Request(server.url + path, headers={"Content-Type": "application/json",
        "Origin": server.url, "Cookie": "ArchHub-Session=" + server.browser_session_token,
        "X-ArchHub-CSRF": server.browser_csrf_token}, data=json.dumps(body).encode())
    with urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_studio_tool_count_survives_writes_that_do_not_change_the_graph_list():
    server = ApplicationServer(fresh=True).start()
    try:
        _get_json(server, "/api/universal/graphs")
        status, created = _post_json(server, "/api/universal/graph-create", {"title": "Second graph"})
        assert status == 200
        total = len(created["graphs"])
        assert total >= 2
        revision = server.universal_store.revision
        status, _ = _post_json(server, "/api/universal/node-create", {"title": "Think",
            "engine": "library.think", "params": {}, "x": 240, "y": 200})
        assert status == 200
        assert server.universal_store.revision != revision, "the node write moved the revision"
        status, tools = _get_json(server, "/tools")
        assert status == 200
        studio = next(row for row in tools["tools"] if row["id"] == "studio")
        assert studio["stat_line"].startswith(f"{total} sessions"), studio["stat_line"]
    finally:
        server.close()


def test_tools_route_does_not_scan_graph_projection_on_poll(monkeypatch):
    from nodelang import universal_application, universal_graphs

    def refuse(*_args, **_kwargs):
        raise AssertionError("/tools must not run the graph/canvas projection")

    monkeypatch.setattr(universal_graphs, "project_graph_index", refuse)
    monkeypatch.setattr(universal_application, "project_universal_canvas", refuse)

    server = ApplicationServer(fresh=True).start()
    try:
        status, tools = _get_json(server, "/tools")
        assert status == 200
        assert [row["id"] for row in tools["tools"]] == [
            "studio", "workshop", "brain", "baboom", "connectors", "cloud",
        ]
        assert all(str(row["stat_line"]).strip() for row in tools["tools"])
        assert not any(
            "unknown" in (row["state"] + " " + row["state_word"] + " " + row["stat_line"]).lower()
            or "…" in row["stat_line"]
            for row in tools["tools"]
        )
    finally:
        server.close()


def test_waiting_route_reads_existing_social_approval_producer(monkeypatch):
    from nodelang import social_approval

    def pending(_server, _binding):
        return [{
            "delegation": "app:baboom-connector-delegation:test",
            "work": "work:test",
            "input_digest": "a" * 64,
            "review_text": "Approve the scheduled LinkedIn post",
            "expires_at": 1234567890,
        }]

    monkeypatch.setattr(social_approval, "pending", pending)
    server = ApplicationServer(fresh=True).start()
    try:
        status, waiting = _get_json(server, "/waiting")
        assert status == 200
        assert [item["producer"] for item in waiting["items"]] == ["social_approve"]
        item = waiting["items"][0]
        assert item["summary"] == "Approve the scheduled LinkedIn post"
        assert item["delegation"] == "app:baboom-connector-delegation:test"
        assert item["input_digest"] == "a" * 64
        assert item["work"] == "work:test"
    finally:
        server.close()


def test_waiting_route_reads_workshop_projection_through_admitted_status():
    class WorkshopHost:
        def __init__(self):
            self._identity = ("app", "owner", "view", "room-a", "scope-a", "work-a", "request-a")
            self._status = {
                "state": "awaiting_approval",
                "review_text": "stale private status",
                "input_digest": "0" * 64,
            }
            self.calls = []

        def status(self, binding, *, root, scope, work=None):
            self.calls.append((binding.subject_root, root, scope, work))
            assert root == "room-a"
            assert scope == "scope-a"
            assert work is None
            return {
                "ok": True,
                "state": "awaiting_approval",
                "mode": "project",
                "work": "work-a",
                "review_text": "Approve admitted project input",
                "delegation": "delegation-a",
                "input_digest": "b" * 64,
                "revision": "rev-a",
                "approved": False,
            }

        def close(self):
            pass

    server = ApplicationServer(fresh=True).start()
    host = WorkshopHost()
    server._existing_workshop_native_host = host
    try:
        status, waiting = _get_json(server, "/waiting")
        assert status == 200
        assert waiting["ok"] is True
        assert len(host.calls) == 1
        assert [(item["producer"], item["summary"], item["input_digest"])
                for item in waiting["items"]] == [
            ("workshop_gate", "Approve admitted project input", "b" * 64),
        ]
        assert "stale private status" not in json.dumps(waiting)
    finally:
        server.close()


def test_waiting_route_surfaces_workshop_admission_failure():
    class RefusingWorkshopHost:
        _identity = ("app", "owner", "view", "room-a", "scope-a", "work-a", "request-a")

        def status(self, binding, *, root, scope, work=None):
            raise PermissionError("Workshop changed during admission")

        def close(self):
            pass

    server = ApplicationServer(fresh=True).start()
    server._existing_workshop_native_host = RefusingWorkshopHost()
    try:
        status, waiting = _get_json(server, "/waiting")
        assert status == 200
        assert waiting["ok"] is False
        assert waiting["items"] == []
        assert waiting["errors"] == ["Workshop changed during admission"]
    finally:
        server.close()


def test_wire_route_is_not_advertised_until_it_has_a_real_frame_owner():
    server = ApplicationServer(fresh=True).start()
    try:
        assert _get_status(server, "/wire") == 404
    finally:
        server.close()


def test_studio_tool_count_refreshes_off_the_poll_after_a_list_changing_write(monkeypatch):
    import time
    from nodelang import universal_graphs

    server = ApplicationServer(fresh=True).start()
    try:
        _get_json(server, "/api/universal/graphs")
        rows = [{"id": f"graph:{index}", "title": f"Graph {index}", "state": "idle"} for index in range(3)]
        monkeypatch.setattr(universal_graphs, "project_graph_index",
            lambda *_args, **_kwargs: {"ok": True, "graphs": rows, "current_graph": "graph:0", "canvas": {}})
        # A write that changed the list without a graph route (retract, group, undo).
        for entry in server._tool_hub_graph_sessions_cache.values():
            entry["revision"] = -1
        status, tools = _get_json(server, "/tools")
        assert status == 200
        first = next(row for row in tools["tools"] if row["id"] == "studio")["stat_line"]
        assert not first.startswith("3 sessions"), "the poll serves the last list at once"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status, tools = _get_json(server, "/tools")
            line = next(row for row in tools["tools"] if row["id"] == "studio")["stat_line"]
            if line.startswith("3 sessions"):
                break
            time.sleep(0.1)
        assert line.startswith("3 sessions"), line
    finally:
        server.close()
