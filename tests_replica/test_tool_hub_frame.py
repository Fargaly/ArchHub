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
        assert [row["state"] for row in tools["tools"]] == [
            "running", "unknown", "unknown", "unknown", "unknown", "unknown",
        ]
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
            f"{expected_total} sessions · {expected_running} running."
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
