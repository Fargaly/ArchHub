from __future__ import annotations

import sys
import types
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import live_runtime_holders as lrh  # noqa: E402


def test_find_holders_detects_processes_inside_runtime_copy(tmp_path):
    runtime = tmp_path / "node_runtime"
    runtime.mkdir()
    holder = lrh.ProcessRecord(
        pid=10,
        name="python.exe",
        cwd=str(runtime / "nodelang"),
        cmdline="python -m nodelang.application_server",
        create_time=100.0,
        status="running",
        cpu_user_seconds=1.25,
        cpu_system_seconds=0.75,
    )
    unrelated = lrh.ProcessRecord(
        pid=11,
        name="python.exe",
        cwd=str(tmp_path / "other"),
        cmdline="python -m pytest",
    )

    holders = lrh.find_holders(runtime, [unrelated, holder], observed_at=160.0)

    assert holders == [
        {
            "pid": 10,
            "name": "python.exe",
            "cwd": str(runtime / "nodelang"),
            "cmdline": "python -m nodelang.application_server",
            "match": "cwd",
            "create_time": 100.0,
            "age_seconds": 60.0,
            "status": "running",
            "cpu_user_seconds": 1.25,
            "cpu_system_seconds": 0.75,
            "cpu_total_seconds": 2.0,
        }
    ]


def test_audit_reports_archive_unsafe_when_holder_exists(tmp_path, monkeypatch):
    runtime = tmp_path / "node_runtime"
    runtime.mkdir()
    monkeypatch.setattr(
        lrh,
        "iter_processes",
        lambda: [
            lrh.ProcessRecord(
                pid=12,
                name="pythonw.exe",
                cwd=str(runtime),
                cmdline="pythonw run_application_server.py",
            )
        ],
    )

    report = lrh.audit(runtime)

    assert report["schema"] == "archhub-live-runtime-holders/v1"
    assert report["exists"] is True
    assert isinstance(report["observed_at"], float)
    assert report["holder_count"] == 1
    assert report["archive_safe_now"] is False
    assert "do not archive or move" in report["required_action"]


def test_audit_reports_archive_safe_when_runtime_exists_and_no_holders(tmp_path, monkeypatch):
    runtime = tmp_path / "node_runtime"
    runtime.mkdir()
    monkeypatch.setattr(lrh, "iter_processes", lambda: [])

    report = lrh.audit(runtime)

    assert report["holder_count"] == 0
    assert report["archive_safe_now"] is True
    assert report["required_action"] == "archive is safe now"


def test_inspect_pids_returns_parent_children_ports_without_interrupting(monkeypatch):
    class FakeCpu:
        user = 2.0
        system = 0.5

    class FakeParent:
        pid = 7

    class FakeChild:
        def __init__(self, pid):
            self.pid = pid

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            return 100.0

        def cpu_times(self):
            return FakeCpu()

        def parent(self):
            return FakeParent()

        def children(self, recursive=False):
            assert recursive is False
            return [FakeChild(11), FakeChild(12)]

        def name(self):
            return "python.exe"

        def status(self):
            return "sleeping"

        def cwd(self):
            return "C:\\repo\\node_runtime"

        def cmdline(self):
            return ["python", "-m", "pytest"]

    class FakeLaddr:
        port = 8505

    class FakeConn:
        status = "LISTEN"
        pid = 10
        laddr = FakeLaddr()

    fake_psutil = types.SimpleNamespace(
        Process=FakeProcess,
        net_connections=lambda kind: [FakeConn()],
        AccessDenied=RuntimeError,
        NoSuchProcess=LookupError,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(lrh.time, "time", lambda: 160.0)
    monkeypatch.setattr(
        lrh,
        "_endpoint_fingerprints",
        lambda ports: [{"port": 8505, "path": "/health", "ok": True}],
    )

    report = lrh.inspect_pids([10])

    assert report["schema"] == "archhub-live-runtime-pid-inspection/v1"
    assert report["available"] is True
    assert report["processes"] == [{
        "pid": 10,
        "exists": True,
        "name": "python.exe",
        "status": "sleeping",
        "cwd": "C:\\repo\\node_runtime",
        "cmdline": "python -m pytest",
        "cmdline_argv": ["python", "-m", "pytest"],
        "create_time": 100.0,
        "age_seconds": 60.0,
        "cpu_user_seconds": 2.0,
        "cpu_system_seconds": 0.5,
        "cpu_total_seconds": 2.5,
        "parent_pid": 7,
        "child_pids": [11, 12],
        "listening_ports": [8505],
        "established_connection_count": 0,
        "endpoint_fingerprints": [{"port": 8505, "path": "/health", "ok": True}],
        "launch_mode": "python_module",
        "module": "pytest",
        "stdin_mode": False,
        "script_path": None,
        "script_exists": False,
        "script_size_bytes": None,
        "script_mtime_utc": None,
        "script_sha256": None,
        "process_risk_class": "unclassified_process_holder",
        "drain_posture": "inspect evidence before deciding any handoff",
        "allowed_action": "inspect only; this function never interrupts a process",
    }]


def test_inspect_pids_marks_missing_temp_qa_script(monkeypatch):
    class FakeCpu:
        user = 1.0
        system = 0.25

    class FakeProcess:
        pid = 21

        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            return 100.0

        def cpu_times(self):
            return FakeCpu()

        def parent(self):
            return None

        def children(self, recursive=False):
            return []

        def name(self):
            return "python.exe"

        def status(self):
            return "running"

        def cwd(self):
            return "C:\\repo\\node_runtime"

        def cmdline(self):
            return [
                "python",
                "C:\\Users\\fargaly\\AppData\\Local\\Temp\\archhub_nary_qa_server.py",
            ]

    fake_psutil = types.SimpleNamespace(
        Process=FakeProcess,
        net_connections=lambda kind: [],
        AccessDenied=RuntimeError,
        NoSuchProcess=LookupError,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(lrh.time, "time", lambda: 160.0)
    monkeypatch.setattr(lrh.Path, "is_file", lambda self: False)

    process = lrh.inspect_pids([21])["processes"][0]

    assert process["launch_mode"] == "python_script"
    assert process["script_path"].endswith("archhub_nary_qa_server.py")
    assert process["script_exists"] is False
    assert process["established_connection_count"] == 0
    assert process["process_risk_class"] == "qa_server_script_missing"
    assert "orphaned temp-script holder" in process["drain_posture"]


def test_inspect_pids_marks_stdin_listener_child(monkeypatch):
    class FakeCpu:
        user = 0.0
        system = 0.0

    class FakeParent:
        pid = 117712

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            return 100.0

        def cpu_times(self):
            return FakeCpu()

        def parent(self):
            return FakeParent()

        def children(self, recursive=False):
            return []

        def name(self):
            return "python.exe"

        def status(self):
            return "running"

        def cwd(self):
            return "C:\\repo\\node_runtime"

        def cmdline(self):
            return ["python", "-"]

    class FakeLaddr:
        port = 52780

    class FakeConn:
        status = "LISTEN"
        pid = 147188
        laddr = FakeLaddr()

    fake_psutil = types.SimpleNamespace(
        Process=FakeProcess,
        net_connections=lambda kind: [FakeConn()],
        AccessDenied=RuntimeError,
        NoSuchProcess=LookupError,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(lrh.time, "time", lambda: 160.0)
    monkeypatch.setattr(
        lrh,
        "_endpoint_fingerprints",
        lambda ports: [{"port": 52780, "path": "/", "error_type": "TimeoutError"}],
    )

    process = lrh.inspect_pids([147188])["processes"][0]

    assert process["launch_mode"] == "python_stdin"
    assert process["stdin_mode"] is True
    assert process["listening_ports"] == [52780]
    assert process["established_connection_count"] == 0
    assert process["endpoint_fingerprints"] == [{
        "port": 52780,
        "path": "/",
        "error_type": "TimeoutError",
    }]
    assert process["process_risk_class"] == "stdin_python_listener_child"


def test_endpoint_fingerprints_are_bounded_read_only(monkeypatch):
    seen = {}

    class FakeHeaders(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class FakeResponse:
        status = 200
        headers = FakeHeaders({
            "Content-Type": "application/json",
            "Server": "FakeServer",
        })

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            seen["size"] = size
            return b'{"ok":true}'

    def fake_urlopen(request, timeout):
        seen.setdefault("urls", []).append(request.full_url)
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(lrh, "urlopen", fake_urlopen)

    rows = lrh._endpoint_fingerprints([8516])

    assert seen["method"] == "GET"
    assert seen["timeout"] == lrh.FINGERPRINT_TIMEOUT_SECONDS
    assert seen["size"] == lrh.FINGERPRINT_BODY_BYTES
    assert seen["urls"] == [
        "http://127.0.0.1:8516/",
        "http://127.0.0.1:8516/api/state",
        "http://127.0.0.1:8516/api/universal/health",
        "http://127.0.0.1:8516/health",
    ]
    assert rows[0]["ok"] is True
    assert rows[0]["status"] == 200
    assert rows[0]["body_prefix"] == '{"ok":true}'


def test_inspect_pids_counts_established_connections(monkeypatch):
    class FakeCpu:
        user = 0.0
        system = 0.0

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            return 100.0

        def cpu_times(self):
            return FakeCpu()

        def parent(self):
            return None

        def children(self, recursive=False):
            return []

        def name(self):
            return "python.exe"

        def status(self):
            return "running"

        def cwd(self):
            return "C:\\repo\\node_runtime"

        def cmdline(self):
            return ["python", "C:\\Temp\\archhub_nary_qa_server.py"]

    class FakeLaddr:
        port = 8515

    class ListenConn:
        status = "LISTEN"
        pid = 21
        laddr = FakeLaddr()

    class EstablishedConn:
        status = "ESTABLISHED"
        pid = 21
        laddr = FakeLaddr()

    fake_psutil = types.SimpleNamespace(
        Process=FakeProcess,
        net_connections=lambda kind: [ListenConn(), EstablishedConn()],
        AccessDenied=RuntimeError,
        NoSuchProcess=LookupError,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(lrh.time, "time", lambda: 160.0)
    monkeypatch.setattr(lrh.Path, "is_file", lambda self: False)
    monkeypatch.setattr(lrh, "_endpoint_fingerprints", lambda ports: [])

    process = lrh.inspect_pids([21])["processes"][0]

    assert process["listening_ports"] == [8515]
    assert process["established_connection_count"] == 1


def test_local_application_server_audit_marks_scratch_fresh_qa_safe(monkeypatch, tmp_path):
    workspace = tmp_path / "00.ARCHUB"
    state = (
        workspace
        / "10.PRODUCT"
        / "13.NODE-LANGUAGE"
        / "test-results"
        / "qa-8567-state.json.gz"
    )
    record = lrh.ProcessRecord(
        pid=8567,
        name="python.exe",
        cwd=str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
        cmdline=(
            "python -m nodelang.application_server --host 127.0.0.1 "
            f"--port 8567 --fresh --state-path {state}"
        ),
        create_time=100.0,
        status="sleeping",
        cpu_user_seconds=0.5,
        cpu_system_seconds=0.25,
    )
    monkeypatch.setattr(lrh, "_process_tcp_maps", lambda: ({8567: [8567]}, {}))

    report = lrh.audit_local_application_servers(
        workspace,
        processes=[record],
        observed_at=160.0,
    )

    assert report["schema"] == lrh.LOCAL_APP_SERVER_SCHEMA
    assert report["safe_to_stop_pids"] == [8567]
    row = report["processes"][0]
    assert row["classification"] == "disposable_fresh_qa_runtime"
    assert row["safe_to_stop"] is True
    assert row["state_path"] == str(state)
    assert row["listening_ports"] == [8567]


def test_local_application_server_audit_protects_authority_visible_and_active(monkeypatch, tmp_path):
    workspace = tmp_path / "00.ARCHUB"
    records = [
        lrh.ProcessRecord(
            pid=1,
            name="pythonw.exe",
            cwd=str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
            cmdline=(
                "pythonw -m nodelang.authority_bridge --state-path "
                "C:\\Users\\fargaly\\AppData\\Local\\ArchHub\\node-native-wip.json.gz"
            ),
        ),
        lrh.ProcessRecord(
            pid=2,
            name="python.exe",
            cwd=str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
            cmdline=(
                "python -m nodelang.application_server --host 127.0.0.1 "
                "--port 8501 --state-path C:\\Users\\fargaly\\AppData\\Local\\Temp\\visible.json"
            ),
        ),
        lrh.ProcessRecord(
            pid=3,
            name="python.exe",
            cwd=str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
            cmdline=(
                "python -m nodelang.application_server --host 127.0.0.1 "
                "--port 8555 --fresh --state-path "
                "C:\\Users\\fargaly\\AppData\\Local\\Temp\\archhub-current-memory-qa-8555.json.gz"
            ),
        ),
        lrh.ProcessRecord(
            pid=4,
            name="python.exe",
            cwd=str(workspace / "10.PRODUCT" / "13.NODE-LANGUAGE"),
            cmdline=(
                "python -m nodelang.application_server --host 127.0.0.1 "
                "--port 8487 --fresh --state-path "
                "C:\\Users\\fargaly\\AppData\\Local\\Temp\\archhub-universal-qa-8487.json"
            ),
        ),
    ]
    monkeypatch.setattr(
        lrh,
        "_process_tcp_maps",
        lambda: ({1: [], 2: [8501], 3: [8555], 4: [8484]}, {3: 1}),
    )

    report = lrh.audit_local_application_servers(
        workspace,
        processes=records,
        observed_at=160.0,
    )

    by_pid = {row["pid"]: row for row in report["processes"]}
    assert report["safe_to_stop_pids"] == []
    assert by_pid[1]["classification"] == "protected_authority_bridge"
    assert by_pid[2]["classification"] == "protected_visible_endpoint"
    assert by_pid[3]["classification"] == "protected_active_connections"
    assert by_pid[4]["classification"] == "protected_visible_endpoint"


def test_brain_resource_hygiene_protects_http_listener_and_flags_duplicates(monkeypatch):
    records = [
        lrh.ProcessRecord(
            pid=106564,
            parent_pid=25508,
            name="pythonw.exe",
            cwd="C:\\Users\\fargaly\\00.ARCHUB",
            cmdline="pythonw.exe -m personal_brain.server --http 8473",
            create_time=100.0,
            status="running",
            working_set_bytes=14 * 1024 * 1024,
        ),
        lrh.ProcessRecord(
            pid=99200,
            parent_pid=44836,
            name="python.exe",
            cwd="C:\\Users\\fargaly\\00.ARCHUB",
            cmdline="python.exe -m personal_brain.server",
            create_time=120.0,
            status="sleeping",
            working_set_bytes=862 * 1024 * 1024,
        ),
        lrh.ProcessRecord(
            pid=53948,
            parent_pid=44836,
            name="python.exe",
            cwd="C:\\Users\\fargaly\\00.ARCHUB",
            cmdline="python.exe -m personal_brain.server",
            create_time=130.0,
            status="sleeping",
            working_set_bytes=670 * 1024 * 1024,
        ),
        lrh.ProcessRecord(
            pid=200,
            name="python.exe",
            cwd="C:\\Users\\fargaly\\00.ARCHUB",
            cmdline="python.exe -m pytest",
        ),
    ]
    monkeypatch.setattr(lrh, "_process_tcp_maps", lambda: ({106564: [8473]}, {}))

    report = lrh.audit_brain_resource_hygiene(
        processes=records,
        observed_at=160.0,
    )

    assert report["schema"] == lrh.BRAIN_RESOURCE_HYGIENE_SCHEMA
    assert report["process_count"] == 3
    assert report["protected_pids"] == [106564]
    assert report["release_candidate_pids"] == [53948, 99200]
    assert report["total_release_candidate_working_set_bytes"] == (
        (862 + 670) * 1024 * 1024
    )
    by_pid = {row["pid"]: row for row in report["processes"]}
    assert by_pid[106564]["classification"] == "protected_brain_http_service"
    assert by_pid[106564]["release_candidate"] is False
    assert (
        by_pid[99200]["classification"]
        == "candidate_duplicate_non_listening_brain"
    )
    assert by_pid[99200]["release_candidate"] is True
    assert "exact PID/command/port recheck" in by_pid[99200]["drain_posture"]


def test_brain_resource_hygiene_protects_listeners_active_clients_and_parents(monkeypatch):
    records = [
        lrh.ProcessRecord(
            pid=10,
            parent_pid=1,
            name="python.exe",
            cwd="C:\\repo",
            cmdline="python.exe -m personal_brain.server",
        ),
        lrh.ProcessRecord(
            pid=11,
            parent_pid=1,
            name="python.exe",
            cwd="C:\\repo",
            cmdline="python.exe -m personal_brain.server",
        ),
        lrh.ProcessRecord(
            pid=12,
            parent_pid=1,
            name="python.exe",
            cwd="C:\\repo",
            cmdline="python.exe -m personal_brain.server",
        ),
        lrh.ProcessRecord(
            pid=13,
            parent_pid=12,
            name="python.exe",
            cwd="C:\\repo",
            cmdline="python.exe -m pytest",
        ),
    ]
    monkeypatch.setattr(
        lrh,
        "_process_tcp_maps",
        lambda: ({10: [49999]}, {11: 1}),
    )

    report = lrh.audit_brain_resource_hygiene(
        processes=records,
        observed_at=160.0,
    )

    by_pid = {row["pid"]: row for row in report["processes"]}
    assert report["release_candidate_pids"] == []
    assert by_pid[10]["classification"] == "protected_brain_listener"
    assert by_pid[11]["classification"] == "protected_brain_active_client"
    assert by_pid[12]["classification"] == "protected_brain_parent"
