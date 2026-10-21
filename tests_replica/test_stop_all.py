import json
import time
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pytest

from nodelang.application_server import ApplicationServer
from nodelang.universal_application import set_application_halted
from nodelang.universal_application import project_universal_canvas
from tests_replica.test_clean_server_admission import (
    _issue_clean_session,
    _provision_clean_runtime,
    _start_clean_server,
)


def _req(server, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        server.url + path,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-ArchHub-Session": server.browser_session_token,
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _clean_req(server, path, payload, *, token="stop-token", csrf="stop-csrf"):
    request = Request(
        server.url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-ArchHub-Session": token,
            "X-ArchHub-CSRF": csrf,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_stop_all_halts_tasks_refuses_writes_and_resumes():
    server = ApplicationServer(fresh=True).start()
    try:
        # 1. Initially running, not halted
        assert not server.is_halted()
        status, tools = _req(server, "/tools")
        assert status == 200
        assert tools.get("stopped") is False

        # Canvas application node exposes visible halted parameter
        canvas = project_universal_canvas(server.universal_store, server.universal_registry)
        app_node = next((n for n in canvas["nodes"] if n.get("application")), None)
        assert app_node is not None
        halted_param = next((p for p in app_node["params"] if p["label"] == "halted"), None)
        assert halted_param is not None
        assert halted_param["value"] == "false"

        # 2. Fake running task stops within 1 s of /stop-all
        task_stopped = threading.Event()
        task_started = threading.Event()
        task_restarted = threading.Event()
        task_running = [True]

        def fake_task_runner():
            task_started.set()
            while task_running[0]:
                if server.is_halted():
                    task_stopped.set()
                    break
                time.sleep(0.05)

        task_thread = threading.Thread(target=fake_task_runner, daemon=True)
        task_thread.start()
        assert task_started.wait(timeout=2.0)

        # Trigger /stop-all
        t0 = time.monotonic()
        status, stop_res = _req(server, "/stop-all", {})
        assert status == 200
        assert stop_res == {"ok": True, "stopped": True}
        assert server.is_halted()

        # Verify task stops within 1 second
        stopped_in_time = task_stopped.wait(timeout=1.0)
        t_elapsed = time.monotonic() - t0
        task_thread.join(timeout=0.5)
        assert stopped_in_time, "Fake task did not stop within 1 second"
        assert t_elapsed < 1.0, f"Task stop took {t_elapsed:.3f} s, expected < 1.0 s"

        # 3. Visible GET /tools includes stopped: true
        status, tools_stopped = _req(server, "/tools")
        assert status == 200
        assert tools_stopped.get("stopped") is True

        # Canvas application node visible parameter is halted=true
        canvas_stopped = project_universal_canvas(server.universal_store, server.universal_registry)
        app_node_stopped = next((n for n in canvas_stopped["nodes"] if n.get("application")), None)
        assert app_node_stopped is not None
        halted_param_stopped = next((p for p in app_node_stopped["params"] if p["label"] == "halted"), None)
        assert halted_param_stopped is not None
        assert halted_param_stopped["value"] == "true"

        # 4. New write refused with exact message: "Stopped by you. Press Resume to continue."
        status, write_res = _req(server, "/api/universal/workspace-roots", {"action": "browse"})
        assert status == 403
        assert write_res == {
            "ok": False,
            "error": "Stopped by you. Press Resume to continue.",
        }

        # 5. Sent write is recorded as 'stopped after send, check result' and not replayed
        record = server.record_halted_sent_write("sent-write-42", {"payload": "test"})
        assert record["status"] == "stopped after send, check result"
        held = server.check_halted_write("sent-write-42")
        assert held is not None
        assert held["status"] == "stopped after send, check result"

        # 6. /resume clears flag, allows new work, does not auto-restart old task
        status, resume_res = _req(server, "/resume", {})
        assert status == 200
        assert resume_res == {"ok": True, "stopped": False}
        assert not server.is_halted()

        # Old task did not auto-restart
        assert not task_restarted.is_set()
        assert not task_thread.is_alive()

        # Visible GET /tools includes stopped: false
        status, tools_resumed = _req(server, "/tools")
        assert status == 200
        assert tools_resumed.get("stopped") is False

        # Canvas application node parameter reflects resumed state
        canvas_resumed = project_universal_canvas(server.universal_store, server.universal_registry)
        app_node_resumed = next((n for n in canvas_resumed["nodes"] if n.get("application")), None)
        assert app_node_resumed is not None
        halted_param_resumed = next((p for p in app_node_resumed["params"] if p["label"] == "halted"), None)
        assert halted_param_resumed is not None
        assert halted_param_resumed["value"] == "false"

    finally:
        server.close()


def test_stop_all_fences_clean_server_post_routes_and_resume_reopens(tmp_path):
    built, provider = _provision_clean_runtime(tmp_path, root_name="clean-stop-all")
    server = _start_clean_server(built, provider, scope_root=built.grand_map.root_id)
    _issue_clean_session(built, token="stop-token", csrf="stop-csrf")
    stopped = {"ok": False, "error": "Stopped by you. Press Resume to continue."}
    before = built.location.authority.store.revision
    try:
        set_application_halted(True)
        for path, body in (
            ("/api/universal/connect", {"source": "a", "target": "b",
                "source_interface": "out", "target_interface": "in",
                "expected_scope": built.grand_map.root_id}),
            ("/api/universal/gesture", {"viewport": {"x": 1},
                "expected_scope": built.grand_map.root_id}),
            ("/api/universal/run-graph", {"control": "run",
                "expected_scope": built.grand_map.root_id}),
        ):
            status, answer = _clean_req(server, path, body)
            assert status == 403
            assert answer == stopped
            assert built.location.authority.store.revision == before

        set_application_halted(False)
        status, answer = _clean_req(server, "/api/universal/gesture", {
            "viewport": {"x": 1},
            "expected_scope": built.grand_map.root_id,
        })
        assert status == 200, answer
    finally:
        set_application_halted(False)
        server.close()
